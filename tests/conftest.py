from __future__ import annotations

from rfp_agent.schemas import Assessment, Extraction

DOCUMENT_TEXT = (
    "Port Alder requests an automation platform for permit intake. "
    "Proposals are due January 15, 2027. "
    "The bidder must submit through the procurement portal. "
    "Portal registration is required before submission. "
    + "Background information for evaluation. "
    * 20
)


def extraction_fixture(
    *, relevance: str = "STRONG", agency_quote: str = "Port Alder"
) -> Extraction:
    missing = {"value": "Not stated", "evidence": None}
    return Extraction.model_validate(
        {
            "facts": {
                "agency": {
                    "value": "Port Alder",
                    "evidence": {"quote": agency_quote, "page": 1},
                },
                "rfp_number_and_title": missing,
                "scope_summary": {
                    "value": "Automation platform for permit intake",
                    "evidence": {
                        "quote": "automation platform for permit intake",
                        "page": 1,
                    },
                },
                "contract_type": missing,
                "contract_value_or_budget": missing,
                "term": missing,
                "place_of_performance": missing,
                "submission_method": missing,
                "evaluation_method": missing,
            },
            "summary": [
                "The buyer wants permit intake automation.",
                "Proposals are due in January.",
                "Submission uses a procurement portal.",
            ],
            "dates": [
                {
                    "what": "Proposal due",
                    "kind": "PROPOSAL_DUE",
                    "date_text": "January 15, 2027",
                    "date": "2027-01-15",
                    "time": None,
                    "timezone": None,
                    "mandatory_attendance": None,
                    "superseded": [],
                    "ambiguity_note": None,
                    "evidence": {
                        "quote": "Proposals are due January 15, 2027.",
                        "page": 1,
                    },
                }
            ],
            "requirements": [
                {
                    "category": "SUBMISSION_FORMAT",
                    "text": "Submit through the procurement portal.",
                    "mandatory": "YES",
                    "evidence": {
                        "quote": "must submit through the procurement portal",
                        "page": 1,
                    },
                }
            ],
            "gate_candidates": [
                {
                    "type": "REGISTRATION_OR_CERT",
                    "title": "Portal registration",
                    "requirement": "Register before submitting.",
                    "action": "Confirm portal registration.",
                    "action_date": "2027-01-14",
                    "consequence": "Not stated",
                    "evidence": {
                        "quote": "Portal registration is required before submission.",
                        "page": 1,
                    },
                }
            ],
            "ambiguities": [],
            "buyer_work_category": "permit intake automation",
            "relevance": {
                "level": relevance,
                "reason": "The requested work is an automation platform.",
            },
        }
    )


def full_assessment() -> Assessment:
    return Assessment.model_validate(
        {
            "gates": [
                {
                    "gate_id": "gate-001",
                    "status": "UNKNOWN",
                    "status_reason": "Portal registration is not in the profile.",
                }
            ],
            "fit_factors": [
                {"factor": "scope_fit", "score": 9, "reason": "Direct scope match."},
                {"factor": "eligibility", "score": 5, "reason": "Registration unknown."},
                {
                    "factor": "delivery_feasibility",
                    "score": 8,
                    "reason": "A focused software delivery.",
                },
                {
                    "factor": "commercial_risk",
                    "score": 7,
                    "reason": "No adverse terms were stated.",
                },
            ],
            "decision": "BID",
            "reasons": ["Strong scope match.", "Feasible delivery.", "Manageable risk."],
            "deal_breakers": [],
            "what_would_change_my_mind": ["A disqualifying registration rule."],
            "open_questions_for_agency": ["When must portal registration be complete?"],
        }
    )
