"""Weighted fit scoring and deterministic decision guardrails."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .config import (
    FIT_WEIGHTS,
    HIGH_NO_BID_SCORE_WARNING,
    LOW_BID_SCORE_WARNING,
    SCOPE_NO_BID_THRESHOLD,
)
from .schemas import Assessment


def score_assessment(assessment: Assessment) -> dict[str, object]:
    factors = {factor.factor: factor.score for factor in assessment.fit_factors}
    raw = sum(FIT_WEIGHTS[name] * factors.get(name, 0) for name in FIT_WEIGHTS)
    rounded = int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    score = max(0, min(10, rounded))
    decision = assessment.decision
    notes: list[str] = []
    warnings: list[str] = []

    scope_fit = factors.get("scope_fit", 0)
    failed_gates = [gate for gate in assessment.gates if gate.status == "FAIL"]
    if scope_fit <= SCOPE_NO_BID_THRESHOLD:
        if score > SCOPE_NO_BID_THRESHOLD:
            score = SCOPE_NO_BID_THRESHOLD
        if decision != "NO_BID":
            notes.append(f"Model said {decision}; forced NO_BID because scope_fit is {scope_fit}.")
        decision = "NO_BID"
    if failed_gates:
        gate_ids = ", ".join(gate.gate_id for gate in failed_gates)
        if decision != "NO_BID":
            notes.append(f"Model said {decision}; forced NO_BID because gate {gate_ids} is FAIL.")
        decision = "NO_BID"

    if decision == "BID" and score < LOW_BID_SCORE_WARNING:
        warnings.append("The BID decision and low fit score look inconsistent.")
    if (
        decision == "NO_BID"
        and score >= HIGH_NO_BID_SCORE_WARNING
        and not failed_gates
        and scope_fit > SCOPE_NO_BID_THRESHOLD
    ):
        warnings.append("The NO_BID decision and high fit score look inconsistent.")

    return {
        "fit_score_raw": round(raw, 2),
        "fit_score": score,
        "decision": decision,
        "guardrail_notes": notes,
        "warnings": warnings,
    }
