"""Pure quote verification: the model proposes evidence; code checks it."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio

from .config import FUZZY_MATCH_THRESHOLD
from .schemas import Evidence, EvidencePatch, Extraction, VerificationSummary

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


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


def ensure_gate_ids(extraction: Extraction) -> None:
    for index, gate in enumerate(extraction.gate_candidates, start=1):
        if not gate.gate_id:
            gate.gate_id = f"gate-{index:03d}"


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
            ref.owner.evidence = patch.evidence  # type: ignore[attr-defined]
            continue
        if patch.item_id.startswith("fact:"):
            ref.owner.value = "Not stated"  # type: ignore[attr-defined]
            ref.owner.evidence = None  # type: ignore[attr-defined]
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
