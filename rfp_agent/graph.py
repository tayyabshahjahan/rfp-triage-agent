"""LangGraph orchestration for the evidence-first RFP pipeline."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import MAX_REPAIR_ATTEMPTS
from .llm import (
    LlmError,
    clear_call_metadata,
    configured_model_signature,
    consume_call_metadata,
    generate_json,
    llm_progress,
)
from .pdf_ingest import extract_pdf, number_pages, validate_pages
from .profile import IDIAZ_PROFILE
from .prompts import assess_prompt, extract_prompt, recall_prompt, repair_prompt
from .report import build_report
from .schemas import (
    Assessment,
    Extraction,
    FinalReport,
    RecallResult,
    RepairResult,
    TraceEvent,
    VerificationSummary,
)
from .scoring import score_assessment
from .verify import (
    apply_patches,
    ensure_gate_ids,
    failing_item_payload,
    merge_recall,
    verify_extraction,
)

LlmFunction = Callable[[str, type[Any]], Any]
ProgressFunction = Callable[[TraceEvent], None]


class GraphState(TypedDict, total=False):
    file_name: str
    file_bytes: bytes
    pages: list[str]
    numbered_text: str
    extraction: Extraction
    verification: VerificationSummary
    recall_done: bool
    attempt: int
    assessment: Assessment
    score: dict[str, object]
    llm_calls: list[dict[str, object]]
    report: FinalReport
    trace: list[TraceEvent]
    error: str
    as_of: date
    started: float


def _verified_copy(extraction: Extraction) -> Extraction:
    """Remove unsupported evidence before the profile-aware judgment call."""

    clean = extraction.model_copy(deep=True)
    for _, fact in clean.facts:
        if fact.evidence is not None and not fact.evidence.verified:
            fact.value = "Not stated"
            fact.evidence = None
    clean.dates = [item for item in clean.dates if item.evidence.verified]
    clean.requirements = [item for item in clean.requirements if item.evidence.verified]
    clean.gate_candidates = [item for item in clean.gate_candidates if item.evidence.verified]
    for item in clean.gate_candidates:
        if item.consequence_evidence is None or not item.consequence_evidence.verified:
            item.consequence = "Not stated"
            item.consequence_evidence = None
    clean.ambiguities = [item for item in clean.ambiguities if item.evidence.verified]
    return clean


def _assessment_json(extraction: Extraction, *, fast: bool) -> str:
    payload: dict[str, object] = {
        "facts": {name: fact.value for name, fact in extraction.facts},
        "summary": extraction.summary,
        "dates": [
            {
                "what": item.what,
                "kind": item.kind,
                "date": item.date,
                "time": item.time,
                "timezone": item.timezone,
            }
            for item in extraction.dates
        ],
        "gate_candidates": [
            {
                "gate_id": item.gate_id,
                "type": item.type,
                "title": item.title,
                "requirement": item.requirement,
                "action_date": item.action_date,
                "consequence": item.consequence,
            }
            for item in extraction.gate_candidates
        ],
        "ambiguities": [
            {"topic": item.topic, "detail": item.detail}
            for item in extraction.ambiguities
        ],
        "buyer_work_category": extraction.buyer_work_category,
        "relevance": extraction.relevance.model_dump(mode="json"),
    }
    if not fast:
        payload["requirements"] = [
            {
                "requirement_id": item.requirement_id,
                "category": item.category,
                "mandatory": item.mandatory,
                "text": item.text[:160],
            }
            for item in extraction.requirements
        ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RfpTriagePipeline:
    def __init__(self, llm: LlmFunction = generate_json, model: str | None = None):
        self.llm = llm
        self.model = model or configured_model_signature()
        self.graph = self._build_graph()

    @staticmethod
    def _event(
        state: GraphState,
        node: str,
        started: float,
        note: str = "",
        llm_metadata: dict[str, object] | None = None,
    ) -> list[TraceEvent]:
        metadata = llm_metadata or {}
        return [
            *state.get("trace", []),
            TraceEvent(
                node=node,
                status="ok",
                seconds=round(time.perf_counter() - started, 3),
                note=note,
                provider=str(metadata["provider"]) if metadata.get("provider") else None,
                model=str(metadata["model"]) if metadata.get("model") else None,
                retries=int(metadata.get("retries", 0)),
            ),
        ]

    def _invoke_llm(
        self,
        state: GraphState,
        node: str,
        prompt: str,
        schema: type[Any],
    ) -> tuple[Any, list[dict[str, object]], dict[str, object] | None]:
        clear_call_metadata()
        result = self.llm(prompt, schema)
        metadata = consume_call_metadata()
        calls = list(state.get("llm_calls", []))
        if metadata:
            calls.append({"node": node, **metadata})
        return result, calls, metadata

    def _ingest(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        if state.get("pages"):
            pages = state["pages"]
            validate_pages(pages)
            numbered_text = number_pages(pages)
        else:
            pages, numbered_text = extract_pdf(state["file_bytes"], state["file_name"])
        return {
            "pages": pages,
            "numbered_text": numbered_text,
            "trace": self._event(state, "ingest", started, f"{len(pages)} pages"),
        }

    def _analyze(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        extraction, llm_calls, llm_metadata = self._invoke_llm(
            state, "analyze", extract_prompt(state["numbered_text"]), Extraction
        )
        ensure_gate_ids(extraction)
        return {
            "extraction": extraction,
            "llm_calls": llm_calls,
            "trace": self._event(
                state,
                "analyze",
                started,
                f"{len(extraction.requirements)} requirements",
                llm_metadata,
            ),
        }

    def _verify(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        verification = verify_extraction(state["extraction"], state["pages"])
        verification.retries_used = state.get("attempt", 0)
        return {
            "extraction": state["extraction"],
            "verification": verification,
            "trace": self._event(
                state,
                "verify",
                started,
                f"{verification.verified}/{verification.total_items} verified",
            ),
        }

    @staticmethod
    def _route_after_verify(state: GraphState) -> str:
        if not state.get("recall_done", False):
            return "recall"
        if state["verification"].unverified and state.get("attempt", 0) < MAX_REPAIR_ATTEMPTS:
            return "repair"
        if state["extraction"].relevance.level == "NONE":
            return "assess_fast"
        return "assess_full"

    def _recall(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        extraction = state["extraction"]
        recalled, llm_calls, llm_metadata = self._invoke_llm(
            state,
            "recall",
            recall_prompt(
                state["numbered_text"],
                [
                    f"{item.requirement_id or '-'}|{item.mandatory}|{item.text[:48]}"
                    for item in extraction.requirements
                ],
                [
                    f"{item.kind}|{item.date}|{item.what[:80]}"
                    for item in extraction.dates
                ],
            ),
            RecallResult,
        )
        requirements_added, dates_added = merge_recall(extraction, recalled)
        return {
            "extraction": extraction,
            "recall_done": True,
            "llm_calls": llm_calls,
            "trace": self._event(
                state,
                "recall",
                started,
                f"{requirements_added} requirements, {dates_added} dates added",
                llm_metadata,
            ),
        }

    def _repair(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        failing = failing_item_payload(state["extraction"], state["verification"].failing_ids)
        repaired, llm_calls, llm_metadata = self._invoke_llm(
            state,
            "repair",
            repair_prompt(state["numbered_text"], failing),
            RepairResult,
        )
        apply_patches(state["extraction"], repaired.patches)
        return {
            "extraction": state["extraction"],
            "attempt": state.get("attempt", 0) + 1,
            "llm_calls": llm_calls,
            "trace": self._event(
                state,
                "repair",
                started,
                f"{len(repaired.patches)} patches",
                llm_metadata,
            ),
        }

    def _assess(self, state: GraphState, *, fast: bool) -> dict[str, object]:
        started = time.perf_counter()
        clean = _verified_copy(state["extraction"])
        prompt = assess_prompt(_assessment_json(clean, fast=fast), IDIAZ_PROFILE, fast=fast)
        node = "assess_fast" if fast else "assess_full"
        assessment, llm_calls, llm_metadata = self._invoke_llm(
            state, node, prompt, Assessment
        )
        factor_names = [factor.factor for factor in assessment.fit_factors]
        if fast:
            if factor_names != ["scope_fit"] or assessment.fit_factors[0].score > 1:
                raise LlmError("Fast assessment returned an invalid fit factor.")
        elif factor_names != [
            "scope_fit",
            "eligibility",
            "delivery_feasibility",
            "commercial_risk",
        ]:
            raise LlmError("Full assessment returned the wrong fit factors.")
        return {
            "assessment": assessment,
            "llm_calls": llm_calls,
            "trace": self._event(
                state, node, started, assessment.decision, llm_metadata
            ),
        }

    def _assess_full(self, state: GraphState) -> dict[str, object]:
        return self._assess(state, fast=False)

    def _assess_fast(self, state: GraphState) -> dict[str, object]:
        return self._assess(state, fast=True)

    def _guardrails(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        score = score_assessment(
            state["assessment"], state["extraction"].gate_candidates
        )
        note = f"{score['decision']} {score['fit_score']}/10"
        return {
            "score": score,
            "trace": self._event(state, "guardrails", started, note),
        }

    def _build_report(self, state: GraphState) -> dict[str, object]:
        started = time.perf_counter()
        total_seconds = time.perf_counter() - state["started"]
        report = build_report(
            extraction=state["extraction"],
            assessment=state["assessment"],
            verification=state["verification"],
            file_name=state["file_name"],
            page_count=len(state["pages"]),
            model=self.model,
            seconds=total_seconds,
            as_of=state["as_of"],
            score_result=state["score"],
            llm_calls=state.get("llm_calls", []),
        )
        return {
            "report": report,
            "trace": self._event(state, "build_report", started, "report ready"),
        }

    def _build_graph(self):
        builder = StateGraph(GraphState)
        builder.add_node("ingest", self._ingest)
        builder.add_node("analyze", self._analyze)
        builder.add_node("verify", self._verify)
        builder.add_node("recall", self._recall)
        builder.add_node("repair", self._repair)
        builder.add_node("assess_full", self._assess_full)
        builder.add_node("assess_fast", self._assess_fast)
        builder.add_node("guardrails", self._guardrails)
        builder.add_node("build_report", self._build_report)
        builder.add_edge(START, "ingest")
        builder.add_edge("ingest", "analyze")
        builder.add_edge("analyze", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {
                "recall": "recall",
                "repair": "repair",
                "assess_full": "assess_full",
                "assess_fast": "assess_fast",
            },
        )
        builder.add_edge("recall", "verify")
        builder.add_edge("repair", "verify")
        builder.add_edge("assess_full", "guardrails")
        builder.add_edge("assess_fast", "guardrails")
        builder.add_edge("guardrails", "build_report")
        builder.add_edge("build_report", END)
        return builder.compile()

    def _run(self, initial: GraphState, progress: ProgressFunction | None = None) -> FinalReport:
        last_trace_count = 0
        final_state: GraphState | None = None

        def provider_progress(message: str) -> None:
            if progress:
                progress(
                    TraceEvent(
                        node="llm_retry",
                        status="ok",
                        seconds=0,
                        note=message,
                    )
                )

        with llm_progress(provider_progress if progress else None):
            for state in self.graph.stream(initial, stream_mode="values"):
                final_state = state
                events = state.get("trace", [])
                if progress:
                    for event in events[last_trace_count:]:
                        progress(event)
                last_trace_count = len(events)
        if final_state is None or "report" not in final_state:
            raise RuntimeError("The graph ended without a report.")
        return final_state["report"]

    def run_pdf(
        self,
        file_bytes: bytes,
        file_name: str,
        *,
        as_of: date | None = None,
        progress: ProgressFunction | None = None,
    ) -> FinalReport:
        return self._run(
            {
                "file_name": file_name,
                "file_bytes": file_bytes,
                "attempt": 0,
                "recall_done": False,
                "llm_calls": [],
                "trace": [],
                "as_of": as_of or date.today(),
                "started": time.perf_counter(),
            },
            progress,
        )

    def run_pages(
        self,
        pages: list[str],
        *,
        file_name: str = "fixture.pdf",
        as_of: date | None = None,
        progress: ProgressFunction | None = None,
    ) -> FinalReport:
        return self._run(
            {
                "file_name": file_name,
                "pages": pages,
                "attempt": 0,
                "recall_done": False,
                "llm_calls": [],
                "trace": [],
                "as_of": as_of or date.today(),
                "started": time.perf_counter(),
            },
            progress,
        )
