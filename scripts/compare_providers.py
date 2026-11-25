"""Compare configured LLM providers on the bundled sample PDFs."""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples"
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from rfp_agent.graph import RfpTriagePipeline  # noqa: E402
from rfp_agent.llm import configured_provider_order  # noqa: E402

EXPECTED_PROPOSAL_DATES = {
    "Sample-RFP-1-Port-Alder-Permit-Automation.pdf": "2027-01-15",
    "Sample-RFP-2-Larkspur-County-Janitorial.pdf": "2026-12-15",
}


def proposal_due(report: dict[str, object]) -> str | None:
    deadlines = report["deadlines"]
    return next(
        (str(item["date"]) for item in deadlines if item["kind"] == "PROPOSAL_DUE"),
        None,
    )


def main() -> int:
    providers = configured_provider_order()
    pdfs = sorted(SAMPLES_DIR.glob("*.pdf"))
    rows: list[tuple[str, str, str, str, float, str]] = []

    for provider in providers:
        os.environ["LLM_PROVIDER_ORDER"] = provider
        for path in pdfs:
            started = time.perf_counter()
            try:
                report = RfpTriagePipeline().run_pdf(
                    path.read_bytes(),
                    path.name,
                    as_of=date.today(),
                ).model_dump(mode="json")
                expected = EXPECTED_PROPOSAL_DATES.get(path.name)
                due_correct = "yes" if expected and proposal_due(report) == expected else "no"
                quotes_verified = (
                    "yes" if report["verification"]["unverified"] == 0 else "no"
                )
                error = ""
            except Exception as exc:
                due_correct = "no"
                quotes_verified = "no"
                error = str(exc)
            rows.append(
                (
                    provider,
                    path.stem,
                    due_correct,
                    quotes_verified,
                    time.perf_counter() - started,
                    error,
                )
            )

    print(
        f"{'Provider':<10} {'Sample':<48} {'Due correct':<12} "
        f"{'Quotes verified':<16} {'Seconds':>8}  Errors"
    )
    print("-" * 120)
    for provider, sample, due, quotes, seconds, error in rows:
        print(
            f"{provider:<10} {sample:<48} {due:<12} "
            f"{quotes:<16} {seconds:>8.2f}  {error}"
        )
    return 1 if any(error for *_, error in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
