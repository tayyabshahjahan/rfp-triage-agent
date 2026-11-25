"""Pure quote verification: the model proposes evidence; code checks it."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio

from .config import FUZZY_MATCH_THRESHOLD
from .dates import normalize_time
from .schemas import (
    DateItem,
    Evidence,
    EvidencePatch,
    Extraction,
    RecallResult,
    Requirement,
    VerificationSummary,
)

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})
_CUE_PATTERN = re.compile(
    r"(?i)\b(?:shall|must|required|mandatory|may not|will (?:provide|deliver|perform|"
    r"comply|maintain|submit|supply|install|retain|notify)|at least|within \d|no later|"
    r"due|deadline|valid for|availability|uptime|acceptance|service level|support|"
    r"response|resolution|insurance|bond|retainage|liability|indemn|terminat|on-?site|"
    r"subcontract|prevailing wage|encrypt|hosting|data (?:stored|processed|used)|"
    r"page limit|attachment|addendum|exception|waiv|training|migration|audit|public record)\b"
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DASHES).translate(_QUOTES).replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\r?\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class EvidenceRef:
    item_id: str
    evidence: Evidence
    owner: object
    collection: str | None = None
    attribute: str = "evidence"


def ensure_gate_ids(extraction: Extraction) -> None:
    for index, gate in enumerate(extraction.gate_candidates, start=1):
        if not gate.gate_id:
            gate.gate_id = f"gate-{index:03d}"


def normalize_gate_types(extraction: Extraction) -> None:
    for gate in extraction.gate_candidates:
        text = normalize_text(
            " ".join([gate.title, gate.requirement, gate.action, gate.evidence.quote])
        )
        contact_rule = (
            "procurement contact" in text
            or "contact with any other" in text
            or ("communicat" in text and "writing" in text)
        )
        if contact_rule:
            gate.type = "COMMUNICATION_RESTRICTION"


def iter_evidence(extraction: Extraction) -> Iterable[EvidenceRef]:
    for name, fact in extraction.facts:
        if fact.evidence is not None:
            yield EvidenceRef(f"fact:{name}", fact.evidence, fact)
    for index, item in enumerate(extraction.dates):
        yield EvidenceRef(f"date:{index}", item.evidence, item, "dates")
    for index, item in enumerate(extraction.requirements):
        yield EvidenceRef(f"requirement:{index}", item.evidence, item, "requirements")
    for item in extraction.gate_candidates:
        yield EvidenceRef(f"gate:{item.gate_id}", item.evidence, item, "gate_candidates")
        if item.consequence_evidence is not None:
            yield EvidenceRef(
                f"gate:{item.gate_id}:consequence",
                item.consequence_evidence,
                item,
                attribute="consequence_evidence",
            )
    for index, item in enumerate(extraction.ambiguities):
        yield EvidenceRef(f"ambiguity:{index}", item.evidence, item, "ambiguities")


def _mark(evidence: Evidence, match: str, *, page: int | None = None) -> None:
    if page is not None and page != evidence.page:
        evidence.page = page
        evidence.page_corrected = True
    evidence.match = match  # type: ignore[assignment]
    evidence.verified = match != "none"


def _verify_one(evidence: Evidence, pages: list[str]) -> None:
    quote = evidence.quote
    normalized_quote = normalize_text(quote)
    stated_index = evidence.page - 1

    if 0 <= stated_index < len(pages):
        stated_page = pages[stated_index]
        if quote in stated_page:
            _mark(evidence, "exact")
            return
        if normalized_quote and normalized_quote in normalize_text(stated_page):
            _mark(evidence, "normalized")
            return

    for page_number, page in enumerate(pages, start=1):
        if quote in page:
            _mark(evidence, "exact", page=page_number)
            return
        if normalized_quote and normalized_quote in normalize_text(page):
            _mark(evidence, "normalized", page=page_number)
            return

    best_score = 0.0
    best_page = evidence.page
    for page_number, page in enumerate(pages, start=1):
        score = partial_ratio(normalized_quote, normalize_text(page))
        if score > best_score:
            best_score = score
            best_page = page_number
    if best_score >= FUZZY_MATCH_THRESHOLD:
        _mark(evidence, "fuzzy", page=best_page)
    else:
        _mark(evidence, "none")


def verify_extraction(extraction: Extraction, pages: list[str]) -> VerificationSummary:
    ensure_gate_ids(extraction)
    refs = list(iter_evidence(extraction))
    for ref in refs:
        _verify_one(ref.evidence, pages)
    failing = [ref.item_id for ref in refs if not ref.evidence.verified]
    return VerificationSummary(
        total_items=len(refs),
        verified=len(refs) - len(failing),
        unverified=len(failing),
        failing_ids=failing,
    )


def failing_item_payload(extraction: Extraction, failing_ids: list[str]) -> list[dict[str, object]]:
    wanted = set(failing_ids)
    return [
        {"item_id": ref.item_id, "bad_quote": ref.evidence.quote, "page": ref.evidence.page}
        for ref in iter_evidence(extraction)
        if ref.item_id in wanted
    ]


def apply_patches(extraction: Extraction, patches: list[EvidencePatch]) -> None:
    refs = {ref.item_id: ref for ref in iter_evidence(extraction)}
    removals: dict[str, set[int]] = {}
    for patch in patches:
        ref = refs.get(patch.item_id)
        if ref is None:
            continue
        if patch.evidence is not None:
            setattr(ref.owner, ref.attribute, patch.evidence)
            continue
        if patch.item_id.startswith("fact:"):
            ref.owner.value = "Not stated"  # type: ignore[attr-defined]
            ref.owner.evidence = None  # type: ignore[attr-defined]
        elif patch.item_id.endswith(":consequence"):
            ref.owner.consequence = "Not stated"  # type: ignore[attr-defined]
            ref.owner.consequence_evidence = None  # type: ignore[attr-defined]
        elif ref.collection:
            collection = getattr(extraction, ref.collection)
            removals.setdefault(ref.collection, set()).add(collection.index(ref.owner))

    for collection_name, indices in removals.items():
        collection = getattr(extraction, collection_name)
        setattr(
            extraction,
            collection_name,
            [item for index, item in enumerate(collection) if index not in indices],
        )
    ensure_gate_ids(extraction)


def _requirement_key(requirement: Requirement) -> tuple[str, str]:
    requirement_id = normalize_text(str(requirement.requirement_id or ""))
    if requirement_id:
        return "id", requirement_id
    return "text", normalize_text(requirement.text)


def _date_key(item: DateItem) -> tuple[str, str, str]:
    return (item.date, normalize_time(item.time) or "", normalize_text(item.what))


def _merge_date_details(existing: DateItem, incoming: DateItem) -> None:
    if existing.kind == "OTHER" and incoming.kind != "OTHER":
        existing.kind = incoming.kind
    if existing.time is None and incoming.time is not None:
        existing.time = incoming.time
    if existing.timezone is None and incoming.timezone is not None:
        existing.timezone = incoming.timezone
    if existing.mandatory_attendance is None:
        existing.mandatory_attendance = incoming.mandatory_attendance
    known = {(item.date, normalize_text(item.date_text)) for item in existing.superseded}
    for item in incoming.superseded:
        key = (item.date, normalize_text(item.date_text))
        if key not in known:
            existing.superseded.append(item)
            known.add(key)


def dedupe_dates(items: list[DateItem]) -> int:
    """Remove semantic date duplicates while preserving the first visible row."""

    unique: list[DateItem] = []
    by_key: dict[tuple[str, str, str], DateItem] = {}
    for item in items:
        key = _date_key(item)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            unique.append(item)
            continue
        _merge_date_details(existing, item)
    removed = len(items) - len(unique)
    items[:] = unique
    return removed


def requirement_coverage_cues(
    pages: list[str], extraction: Extraction, *, limit: int = 80
) -> list[str]:
    """Surface likely obligation lines not represented in the first extraction pass."""

    covered_parts: list[str] = []
    for item in extraction.requirements:
        covered_parts.extend([item.text, item.evidence.quote])
    for item in extraction.dates:
        covered_parts.extend([item.what, item.date_text, item.evidence.quote])
    covered = normalize_text(" ".join(covered_parts))
    cues: list[str] = []
    seen: set[str] = set()
    for page_number, page in enumerate(pages, start=1):
        page_cues = 0
        for raw_line in page.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip(" \t-\u2022")
            normalized = normalize_text(line)
            if not 20 <= len(line) <= 320 or len(normalized.split()) < 4:
                continue
            is_bullet = raw_line.lstrip().startswith(("-", "\u2022"))
            if not is_bullet and not _CUE_PATTERN.search(line):
                continue
            if normalized in covered or normalized in seen:
                continue
            tokens = {
                token
                for token in re.findall(r"[a-z0-9.$%/-]+", normalized)
                if len(token) > 3
            }
            if tokens and sum(token in covered for token in tokens) / len(tokens) >= 0.8:
                continue
            cues.append(f"p{page_number}: {line[:200]}")
            seen.add(normalized)
            page_cues += 1
            if len(cues) >= limit:
                return cues
            if page_cues >= 12:
                break
    return cues


def merge_recall(extraction: Extraction, recall: RecallResult) -> tuple[int, int]:
    """Merge only genuinely new recall items, preserving the initial extraction order."""

    requirement_keys = {_requirement_key(item) for item in extraction.requirements}
    added_requirements = 0
    for item in recall.requirements:
        key = _requirement_key(item)
        if key in requirement_keys:
            continue
        extraction.requirements.append(item)
        requirement_keys.add(key)
        added_requirements += 1

    dedupe_dates(extraction.dates)
    dates_by_key = {_date_key(item): item for item in extraction.dates}
    added_dates = 0
    for item in recall.dates:
        key = _date_key(item)
        if key in dates_by_key:
            _merge_date_details(dates_by_key[key], item)
            continue
        extraction.dates.append(item)
        dates_by_key[key] = item
        added_dates += 1
    return added_requirements, added_dates
