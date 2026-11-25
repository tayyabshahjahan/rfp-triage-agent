"""Weighted fit scoring and deterministic decision guardrails."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .config import (
    FIT_WEIGHTS,
    HIGH_NO_BID_SCORE_WARNING,
    LOW_BID_SCORE_WARNING,
    MIN_BID_FIT_SCORE,
    SCOPE_NO_BID_THRESHOLD,
)
from .schemas import Assessment, GateCandidate

_ALWAYS_UNKNOWN_GATE_TYPES = {"ELIGIBILITY", "REGISTRATION_OR_CERT", "ONSITE_PRESENCE"}
_PROFILE_DEPENDENT_TERMS = (
    "employee count",
    "employee",
    "employees",
    "revenue",
    "past project",
    "prior project",
    "similar project",
    "past performance",
    "project experience",
    "project history",
    "projects completed",
    "completed projects",
    "certificat",
    "registr",
    "staff location",
    "staff located",
    "personnel location",
    "local office",
)


def _requires_profile_confirmation(candidate: GateCandidate) -> bool:
    if candidate.type in _ALWAYS_UNKNOWN_GATE_TYPES:
        return True
    text = " ".join(
        [candidate.title, candidate.requirement, candidate.action, candidate.evidence.quote]
    ).casefold()
    staff_location = ("staff" in text or "personnel" in text) and "locat" in text
    return staff_location or any(term in text for term in _PROFILE_DEPENDENT_TERMS)


def score_assessment(
    assessment: Assessment, gate_candidates: list[GateCandidate] | None = None
) -> dict[str, object]:
    factors = {factor.factor: factor.score for factor in assessment.fit_factors}
    raw = sum(FIT_WEIGHTS[name] * factors.get(name, 0) for name in FIT_WEIGHTS)
    rounded = int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    score = max(0, min(10, rounded))
    model_decision = assessment.decision
    notes: list[str] = []
    warnings: list[str] = []

    candidates = {candidate.gate_id: candidate for candidate in gate_candidates or []}
    for gate in assessment.gates:
        candidate = candidates.get(gate.gate_id)
        if gate.status != "PASS" or candidate is None:
            continue
        if _requires_profile_confirmation(candidate):
            gate.status = "UNKNOWN"
            gate.status_reason = "Compliance is unconfirmed by the company profile."
            notes.append(
                f"Changed {gate.gate_id} from PASS to UNKNOWN because it depends on "
                "company facts not confirmed by the profile."
            )

    scope_fit = factors.get("scope_fit", 0)
    failed_gates = [gate for gate in assessment.gates if gate.status == "FAIL"]
    if scope_fit <= SCOPE_NO_BID_THRESHOLD:
        if score > SCOPE_NO_BID_THRESHOLD:
            score = SCOPE_NO_BID_THRESHOLD

    decision = (
        "BID"
        if not failed_gates
        and scope_fit > SCOPE_NO_BID_THRESHOLD
        and score >= MIN_BID_FIT_SCORE
        else "NO_BID"
    )
    if decision != model_decision:
        failed_gate_ids = ", ".join(gate.gate_id for gate in failed_gates) or "none"
        notes.append(
            f"Model said {model_decision}; guardrail set {decision} using FAIL gates "
            f"({failed_gate_ids}), scope_fit {scope_fit}, and fit_score {score}."
        )

    if model_decision == "BID" and score < LOW_BID_SCORE_WARNING:
        warnings.append("The model's BID decision and low fit score look inconsistent.")
    if (
        model_decision == "NO_BID"
        and score >= HIGH_NO_BID_SCORE_WARNING
        and not failed_gates
        and scope_fit > SCOPE_NO_BID_THRESHOLD
    ):
        warnings.append("The model's NO_BID decision and high fit score look inconsistent.")

    return {
        "fit_score_raw": round(raw, 2),
        "fit_score": score,
        "decision": decision,
        "model_decision": model_decision if decision != model_decision else None,
        "guardrail_notes": notes,
        "warnings": warnings,
    }
