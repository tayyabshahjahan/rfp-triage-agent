"""Run the real Gemini pipeline against the two challenge sample PDFs."""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
load_dotenv(ROOT / ".env")


def check_report(report: dict[str, object]) -> tuple[str, list[str]]:
    title = str(report["facts"]["rfp_number_and_title"]["value"])
    errors: list[str] = []
    if "PA-DPI-2026-114" in title:
        if report["decision"] != "BID":
            errors.append("expected BID")
        if int(report["fit_score"]) < 7:
            errors.append("expected fit >= 7")
        proposal_dates = [item for item in report["deadlines"] if item["kind"] == "PROPOSAL_DUE"]
        if not proposal_dates or proposal_dates[0]["date"] != "2027-01-15":
            errors.append("proposal due date is not 2027-01-15")
        return "Port Alder", errors
    if "LC-FM-2027-03" in title:
        if report["decision"] != "NO_BID":
            errors.append("expected NO_BID")
        if int(report["fit_score"]) > 2:
            errors.append("expected fit <= 2")
        return "Larkspur", errors
    return title, ["unrecognized sample RFP"]


def main() -> int:
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    if len(pdfs) != 2:
        print(f"Expected 2 PDFs in {SAMPLES}; found {len(pdfs)}.")
        return 2
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is required for the real sample run.")
        return 2

    sys.path.insert(0, str(ROOT))
    from rfp_agent.graph import RfpTriagePipeline
    from rfp_agent.llm import LlmError
    from rfp_agent.pdf_ingest import PdfIngestError

    pipeline = RfpTriagePipeline()
    rows: list[tuple[str, str, float, str]] = []
    for path in pdfs:
        started = time.perf_counter()
        try:
            report = pipeline.run_pdf(path.read_bytes(), path.name, as_of=date.today())
        except (LlmError, PdfIngestError) as exc:
            seconds = time.perf_counter() - started
            rows.append((path.stem, "FAIL", seconds, str(exc)))
            continue
        seconds = time.perf_counter() - started
        name, errors = check_report(report.model_dump(mode="json"))
        rows.append((name, "PASS" if not errors else "FAIL", seconds, "; ".join(errors)))

    print(f"{'Sample':<24} {'Result':<8} {'Seconds':>8}  Notes")
    print("-" * 72)
    for name, result, seconds, notes in rows:
        print(f"{name:<24} {result:<8} {seconds:>8.2f}  {notes}")
    return 1 if any(result == "FAIL" for _, result, _, _ in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
