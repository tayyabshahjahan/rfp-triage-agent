"""Run PDFs through the live pipeline and save hash-addressed reports."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from rfp_agent.cache import pdf_sha256  # noqa: E402
from rfp_agent.config import PRECOMPUTED_DIR  # noqa: E402
from rfp_agent.graph import RfpTriagePipeline  # noqa: E402
from rfp_agent.llm import LlmError  # noqa: E402
from rfp_agent.pdf_ingest import PdfIngestError  # noqa: E402
from rfp_agent.schemas import TraceEvent  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="+", type=Path, help="PDF file(s) to analyze")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=date.today(),
        help="Assessment date in YYYY-MM-DD format",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    PRECOMPUTED_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0

    for path in args.pdf:
        try:
            file_bytes = path.read_bytes()

            def show_progress(event: TraceEvent) -> None:
                detail = f" - {event.note}" if event.note else ""
                print(f"{event.node}: {event.seconds:.2f}s{detail}", flush=True)

            report = RfpTriagePipeline().run_pdf(
                file_bytes,
                path.name,
                as_of=args.as_of,
                progress=show_progress,
            )
        except (LlmError, PdfIngestError, OSError) as exc:
            failures += 1
            print(f"Could not save {path}: {exc}", file=sys.stderr)
            continue
        report.meta["saved_result_date"] = date.today().isoformat()
        destination = PRECOMPUTED_DIR / f"{pdf_sha256(file_bytes)}.json"
        destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Saved {path.name} -> {destination}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
