import pytest

from rfp_agent.pdf_ingest import PdfIngestError, number_pages, validate_pages


def test_number_pages_uses_physical_one_based_markers():
    assert number_pages(["first", "second"]) == ("[[PAGE 1]]\nfirst\n\n[[PAGE 2]]\nsecond")


def test_scanned_detection():
    with pytest.raises(PdfIngestError, match="OCR"):
        validate_pages(["", "tiny"], min_average_chars=20)


def test_page_limit():
    with pytest.raises(PdfIngestError, match="limit"):
        validate_pages(["enough text"] * 3, max_pages=2, min_average_chars=1)
