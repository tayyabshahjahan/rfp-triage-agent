from datetime import date

from conftest import DOCUMENT_TEXT, extraction_fixture, full_assessment

from rfp_agent.graph import RfpTriagePipeline
from rfp_agent.schemas import Assessment, Extraction, RepairResult


class FakeLLM:
    def __init__(self, *, relevance: str = "STRONG", needs_repair: bool = False):
        self.relevance = relevance
        self.needs_repair = needs_repair

    def __call__(self, prompt: str, schema):
        if schema is Extraction:
            quote = "Unsupported agency quote" if self.needs_repair else "Port Alder"
            return extraction_fixture(relevance=self.relevance, agency_quote=quote)
        if schema is RepairResult:
            return RepairResult.model_validate(
                {
                    "patches": [
                        {
                            "item_id": "fact:agency",
                            "evidence": {"quote": "Port Alder", "page": 1},
                        }
                    ]
                }
            )
        if schema is Assessment and "FAST NO-BID" in prompt:
            return Assessment.model_validate(
                {
                    "gates": [
                        {
                            "gate_id": "gate-001",
                            "status": "UNKNOWN",
                            "status_reason": "Registration is unknown.",
                        }
                    ],
                    "fit_factors": [
                        {
                            "factor": "scope_fit",
                            "score": 0,
                            "reason": "The work is outside the profile.",
                        }
                    ],
                    "decision": "NO_BID",
                    "reasons": ["Wrong scope.", "No delivery fit.", "Do not pursue."],
                    "deal_breakers": ["The scope is unrelated."],
                    "what_would_change_my_mind": ["A software scope."],
                    "open_questions_for_agency": [],
                }
            )
        if schema is Assessment:
            return full_assessment()
        raise AssertionError(f"Unexpected schema {schema}")


def test_full_route_builds_bid_report():
    trace = []
    report = RfpTriagePipeline(llm=FakeLLM()).run_pages(
        [DOCUMENT_TEXT], as_of=date(2026, 11, 25), progress=trace.append
    )
    assert report.decision == "BID"
    assert report.fit_score == 7
    assert "assess_full" in [event.node for event in trace]


def test_fast_route_is_decisive_no_bid():
    trace = []
    report = RfpTriagePipeline(llm=FakeLLM(relevance="NONE")).run_pages(
        [DOCUMENT_TEXT], as_of=date(2026, 11, 25), progress=trace.append
    )
    assert report.decision == "NO_BID"
    assert report.fit_score <= 2
    assert "assess_fast" in [event.node for event in trace]


def test_failed_quote_is_repaired_and_reverified():
    trace = []
    report = RfpTriagePipeline(llm=FakeLLM(needs_repair=True)).run_pages(
        [DOCUMENT_TEXT], as_of=date(2026, 11, 25), progress=trace.append
    )
    assert report.verification["unverified"] == 0
    assert report.verification["retries_used"] == 1
    nodes = [event.node for event in trace]
    assert nodes.count("verify") == 2
    assert "repair" in nodes
