from pathlib import Path

from rfp_agent.cache import load_precomputed, pdf_sha256

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_precomputed_reports_match_pdf_hashes():
    for pdf_path in sorted((ROOT / "samples").glob("*.pdf")):
        file_bytes = pdf_path.read_bytes()
        report = load_precomputed(file_bytes)

        assert report is not None
        assert report.meta["file_name"] == pdf_path.name
        assert report.meta["saved_result_date"] == "2026-11-25"
        assert (ROOT / "samples" / "precomputed" / f"{pdf_sha256(file_bytes)}.json").exists()
