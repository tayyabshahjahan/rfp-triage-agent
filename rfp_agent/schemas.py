"""Pydantic data contracts shared by extraction, assessment, and reporting."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DateKind = Literal[
    "PROPOSAL_DUE",
    "QUESTIONS_DUE",
    "PRE_PROPOSAL_MEETING",
    "SITE_VISIT",
    "WORK_START",
    "AWARD",
    "ISSUE_DATE",
    "ADDENDUM",
    "OTHER",
]
RequirementCategory = Literal[
    "CERTIFICATION",
    "SET_ASIDE",
    "CLEARANCE",
    "PAST_PERFORMANCE",
    "STAFFING",
    "TECHNICAL_SKILL",
    "SECURITY_COMPLIANCE",
    "INSURANCE_BONDING",
    "REGISTRATION_LICENSE",
    "SUBMISSION_FORMAT",
    "COMMERCIAL",
    "OTHER",
]
GateType = Literal[
    "MANDATORY_MEETING",
    "ELIGIBILITY",
    "REGISTRATION_OR_CERT",
    "BONDS_AND_INSURANCE",
    "SUBMISSION_RULES",
    "FORMAT_AND_FORMS",
    "ADDENDUM_ACK",
    "ONSITE_PRESENCE",
    "PRICE_CEILING",
]
GateStatus = Literal["PASS", "FAIL", "UNKNOWN"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    quote: str = Field(min_length=1, description="Short verbatim contiguous PDF quote")
    page: int = Field(ge=1)
    verified: bool | None = None
    match: Literal["exact", "normalized", "fuzzy", "none"] | None = None
    page_corrected: bool = False


class FactField(StrictModel):
    value: str
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def missing_values_have_no_evidence(self) -> FactField:
        if self.value == "Not stated" and self.evidence is not None:
            raise ValueError("'Not stated' facts must have null evidence")
        return self


class Facts(StrictModel):
    agency: FactField
    rfp_number_and_title: FactField
    scope_summary: FactField
    contract_type: FactField
    contract_value_or_budget: FactField
    term: FactField
    place_of_performance: FactField
    submission_method: FactField
    evaluation_method: FactField


class SupersededDate(StrictModel):
    date_text: str
    date: str
    reason: str


class DateItem(StrictModel):
    what: str
    kind: DateKind
    date_text: str
    date: str
    time: str | None = None
    timezone: str | None = None
    mandatory_attendance: bool | None = None
    superseded: list[SupersededDate] = Field(default_factory=list)
    ambiguity_note: str | None = None
    evidence: Evidence
    date_check: Literal["ok", "mismatch", "unparseable"] | None = None
    days_remaining: int | None = None
    timing: Literal["PASSED", "TODAY", "UPCOMING"] | None = None


class Requirement(StrictModel):
    category: RequirementCategory
    text: str
    mandatory: Literal["YES", "NO", "UNCLEAR"]
    evidence: Evidence


class GateCandidate(StrictModel):
    gate_id: str = ""
    type: GateType
    title: str
    requirement: str
    action: str
    action_date: str | None = None
    consequence: str
    evidence: Evidence


class Ambiguity(StrictModel):
    topic: str
    detail: str
    evidence: Evidence


class Relevance(StrictModel):
    level: Literal["STRONG", "PARTIAL", "NONE"]
    reason: str


class Extraction(StrictModel):
    facts: Facts
    summary: list[str] = Field(min_length=3, max_length=5)
    dates: list[DateItem] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    gate_candidates: list[GateCandidate] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    buyer_work_category: str
    relevance: Relevance


class AssessmentGate(StrictModel):
    gate_id: str
    status: GateStatus
    status_reason: str


class FitFactor(StrictModel):
    factor: str
    score: int = Field(ge=0, le=10)
    reason: str


class Assessment(StrictModel):
    gates: list[AssessmentGate] = Field(default_factory=list)
    fit_factors: list[FitFactor] = Field(min_length=1)
    decision: Literal["BID", "NO_BID"]
    reasons: list[str] = Field(min_length=3, max_length=3)
    deal_breakers: list[str] = Field(default_factory=list)
    what_would_change_my_mind: list[str] = Field(default_factory=list)
    open_questions_for_agency: list[str] = Field(default_factory=list)


class EvidencePatch(StrictModel):
    item_id: str
    evidence: Evidence | None


class RepairResult(StrictModel):
    patches: list[EvidencePatch]


class VerificationSummary(StrictModel):
    total_items: int
    verified: int
    unverified: int
    retries_used: int = 0
    failing_ids: list[str] = Field(default_factory=list)


class TraceEvent(StrictModel):
    node: str
    status: Literal["ok", "error"]
    seconds: float
    note: str = ""


class FinalReport(BaseModel):
    """The public JSON shape. Extra fields are forbidden to catch assembly mistakes."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["BID", "NO_BID"]
    fit_score: int = Field(ge=0, le=10)
    deadlines: list[dict[str, Any]]
    requirements: list[dict[str, Any]]
    reasons: list[str] = Field(min_length=3, max_length=3)
    summary: list[str]
    facts: dict[str, Any]
    fit_factors: list[dict[str, Any]]
    fit_score_raw: float
    deal_breakers: list[str]
    what_would_change_my_mind: list[str]
    open_questions_for_agency: list[str]
    ambiguities: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    calendar: list[dict[str, Any]]
    verification: dict[str, Any]
    guardrail_notes: list[str]
    warnings: list[str]
    meta: dict[str, Any]
