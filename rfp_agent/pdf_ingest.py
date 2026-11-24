"""Extract per-page PDF text and reject inputs this app cannot handle safely."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from .config import MAX_EMPTY_PAGE_RATIO, MAX_PAGES, MIN_AVERAGE_CHARS_PER_PAGE


class PdfIngestError(ValueError):
    """A friendly input error that can be shown directly in the UI."""


def validate_pages(
    pages: list[str],
    *,
    max_pages: int = MAX_PAGES,
    min_average_chars: int = MIN_AVERAGE_CHARS_PER_PAGE,
    max_empty_ratio: float = MAX_EMPTY_PAGE_RATIO,
) -> None:
    if not pages:
        raise PdfIngestError("The PDF has no pages.")
    if len(pages) > max_pages:
        raise PdfIngestError(
            f"This PDF has {len(pages)} pages; the configured limit is {max_pages}."
        )

    lengths = [len(page.strip()) for page in pages]
    average_chars = sum(lengths) / len(lengths)
    empty_ratio = sum(length < 20 for length in lengths) / len(lengths)
    if average_chars < min_average_chars or empty_ratio > max_empty_ratio:
        raise PdfIngestError(
            "This looks like a scanned or image-heavy PDF. OCR is not supported yet; "
            "please upload a text-searchable PDF."
        )


def number_pages(pages: list[str]) -> str:
    return "\n\n".join(
        f"[[PAGE {page_number}]]\n{text.strip()}" for page_number, text in enumerate(pages, start=1)
    )


def extract_pdf(file_bytes: bytes, file_name: str) -> tuple[list[str], str]:
    if not file_name.lower().endswith(".pdf") or not file_bytes.startswith(b"%PDF"):
        raise PdfIngestError("Please upload a valid PDF file.")

    pages: list[str] = []
    primary_error: Exception | None = None
    try:
        import pdfplumber

        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # pragma: no cover - fallback depends on malformed PDFs
        primary_error = exc

    if not pages:
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            detail = f" ({type(primary_error or exc).__name__})" if primary_error else ""
            raise PdfIngestError(f"The PDF could not be read{detail}.") from exc

    validate_pages(pages)
    return pages, number_pages(pages)


def load_pdf(path: Path) -> tuple[list[str], str]:
    return extract_pdf(path.read_bytes(), path.name)
