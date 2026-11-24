"""Streamlit presentation layer for the RFP triage pipeline."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from html import escape

import streamlit as st

from rfp_agent.cache import cache_key, load_cached, save_cached
from rfp_agent.config import GEMINI_MODEL, PROJECT_ROOT
from rfp_agent.graph import RfpTriagePipeline
from rfp_agent.ics import build_ics
from rfp_agent.llm import LlmError
from rfp_agent.pdf_ingest import PdfIngestError
from rfp_agent.prompts import PROMPT_VERSION
from rfp_agent.schemas import FinalReport, TraceEvent

SAMPLES_DIR = PROJECT_ROOT / "samples"
HEADLINE_DATES = [
    ("QUESTIONS_DUE", "Questions due"),
    ("PROPOSAL_DUE", "Proposal due"),
    ("WORK_START", "Work start"),
]


def humanize(value: str) -> str:
    return value.replace("_", " ").title()


def evidence_rows(report: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def add(item: str, evidence: dict[str, object] | None) -> None:
        if evidence:
            rows.append(
                {
                    "Item": item,
                    "Page": evidence.get("page"),
                    "Verified": evidence.get("verified"),
                    "Match": evidence.get("match"),
                    "Quote": evidence.get("quote"),
                }
            )

    for name, fact in report["facts"].items():
        add(humanize(name), fact.get("evidence"))
    for item in report["deadlines"]:
        add(str(item["what"]), item.get("evidence"))
    for item in report["requirements"]:
        add(str(item["text"]), item.get("evidence"))
    for item in report["gates"]:
        add(str(item["title"]), item.get("evidence"))
    for item in report["ambiguities"]:
        add(str(item["topic"]), item.get("evidence"))
    return rows


def render_header(report: dict[str, object]) -> None:
    decision = str(report["decision"])
    banner_class = "bid" if decision == "BID" else "no-bid"
    st.markdown(
        f'<div class="decision {banner_class}">{decision.replace("_", "-")}</div>',
        unsafe_allow_html=True,
    )
    verification = report["verification"]
    columns = st.columns(4)
    columns[0].metric("Fit score", f"{report['fit_score']}/10")
    columns[1].metric("Run time", f"{report['meta']['seconds']}s")
    columns[2].metric(
        "Evidence verified",
        f"{verification['verified']} / {verification['total_items']}",
    )
    columns[3].metric("Pages", report["meta"]["pages"])
    for note in report["guardrail_notes"]:
        st.warning(note)
    for warning in report["warnings"]:
        st.warning(warning)


def render_dates(report: dict[str, object]) -> None:
    deadlines = report["deadlines"]
    rows: list[dict[str, object]] = []
    used: set[int] = set()
    for kind, label in HEADLINE_DATES:
        match = next(
            ((index, item) for index, item in enumerate(deadlines) if item["kind"] == kind),
            None,
        )
        if not match:
            rows.append({"Milestone": label, "Date": "Not stated", "Time": "", "Status": ""})
            continue
        index, item = match
        used.add(index)
        rows.append(
            {
                "Milestone": item["what"],
                "Date": item["date"],
                "Time": " ".join(part for part in [item.get("time"), item.get("timezone")] if part),
                "Status": item.get("timing") or "",
                "Days": item.get("days_remaining"),
            }
        )
    for index, item in enumerate(deadlines):
        if index in used:
            continue
        rows.append(
            {
                "Milestone": item["what"],
                "Date": item["date"],
                "Time": " ".join(part for part in [item.get("time"), item.get("timezone")] if part),
                "Status": item.get("timing") or "",
                "Days": item.get("days_remaining"),
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_report(report: dict[str, object]) -> None:
    st.subheader("Summary")
    for sentence in report["summary"]:
        st.write(sentence)

    st.subheader("Facts")
    facts = [
        {"Field": humanize(name), "Value": value["value"]}
        for name, value in report["facts"].items()
    ]
    st.dataframe(facts, hide_index=True, use_container_width=True)

    st.subheader("Key dates")
    render_dates(report)

    st.subheader("Requirements")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in report["requirements"]:
        grouped[str(item["category"])].append(item)
    if not grouped:
        st.write("Not stated")
    for category, items in grouped.items():
        st.markdown(f"**{humanize(category)}**")
        st.dataframe(
            [
                {
                    "Mandatory": item["mandatory"],
                    "Requirement": item["text"],
                    "Page": item["evidence"]["page"],
                }
                for item in items
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Fit factors")
    st.dataframe(
        [
            {
                "Factor": humanize(item["factor"]),
                "Score": f"{item['score']}/10",
                "Reason": item["reason"],
            }
            for item in report["fit_factors"]
        ],
        hide_index=True,
        use_container_width=True,
    )

    sections = [
        ("Three strongest reasons", report["reasons"]),
        ("Deal-breakers", report["deal_breakers"]),
        ("What would change the decision", report["what_would_change_my_mind"]),
        ("Open questions for the agency", report["open_questions_for_agency"]),
    ]
    for title, items in sections:
        st.subheader(title)
        if items:
            for item in items:
                st.write(f"- {item}")
        else:
            st.write("None")

    st.subheader("Ambiguities")
    if report["ambiguities"]:
        for item in report["ambiguities"]:
            st.warning(f"{item['topic']}: {item['detail']} (page {item['evidence']['page']})")
    else:
        st.write("None identified")


def render_radar(report: dict[str, object]) -> None:
    rows = report["gates"]
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ["FAIL", "UNKNOWN", "PASS"]
    }
    upcoming = [
        row for row in rows if row.get("days_remaining") is not None and row["days_remaining"] >= 0
    ]
    next_action = min(upcoming, key=lambda row: row["days_remaining"]) if upcoming else None
    columns = st.columns(4)
    columns[0].metric("Fail", counts["FAIL"])
    columns[1].metric("Unknown", counts["UNKNOWN"])
    columns[2].metric("Pass", counts["PASS"])
    columns[3].metric(
        "Next action",
        (f"{next_action['days_remaining']} days" if next_action else "Not stated"),
        next_action["action_date"] if next_action else None,
    )

    for row in rows:
        with st.container(border=True):
            badge_class = str(row["status"]).lower()
            st.markdown(
                f'<span class="gate-status {badge_class}">{row["status"]}</span> '
                f"<strong>{escape(str(row['title']))}</strong>",
                unsafe_allow_html=True,
            )
            st.caption(humanize(str(row["type"])))
            st.write(row["requirement"])
            st.write(f"**Why:** {row['status_reason']}")
            if row.get("suggested_question"):
                st.write(f"**Ask the agency:** {row['suggested_question']}")
            st.write(f"**Action:** {row['action']}")
            do_by = row["action_date"] or "Not stated"
            if row.get("days_remaining") is not None:
                do_by += f" ({row['days_remaining']} days)"
            st.write(f"**Do by:** {do_by}")
            st.write(f"**Consequence:** {row['consequence']}")
            evidence = row["evidence"]
            badge = "verified" if evidence.get("verified") else "UNVERIFIED"
            st.caption(f'"{evidence["quote"]}" - page {evidence["page"]} - {badge}')

    st.subheader("Do-by calendar")
    st.dataframe(
        [
            {
                "Date": item["date"],
                "Time": item.get("time") or "",
                "Item": item["title"],
                "Status": item.get("timing") or "",
                "Days": item.get("days_remaining"),
            }
            for item in report["calendar"]
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.download_button(
        "Download calendar (.ics)",
        data=build_ics(report["calendar"]),
        file_name="rfp-do-by-calendar.ics",
        mime="text/calendar",
    )


def render_evidence(report: dict[str, object]) -> None:
    rows = evidence_rows(report)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    unverified = [row for row in rows if not row["Verified"]]
    if unverified:
        st.warning(f"{len(unverified)} evidence item(s) remain unverified after retries.")


def render_json(report: dict[str, object]) -> None:
    st.json(report)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    st.download_button(
        "Download report.json",
        data=payload,
        file_name="report.json",
        mime="application/json",
    )


def chosen_file(uploaded_file, sample_name: str) -> tuple[bytes, str] | None:
    if uploaded_file is not None:
        return uploaded_file.getvalue(), uploaded_file.name
    if sample_name != "Choose a sample":
        path = SAMPLES_DIR / sample_name
        return path.read_bytes(), path.name
    return None


st.set_page_config(page_title="RFP Triage Agent", page_icon=":page_facing_up:", layout="wide")
st.markdown(
    """
    <style>
    .block-container { max-width: 1180px; padding-top: 2rem; }
    .decision { padding: .8rem 1rem; border-left: 6px solid; font-size: 1.35rem;
                font-weight: 700; margin: .5rem 0 1rem; }
    .decision.bid { background: #e8f5ee; border-color: #147d47; color: #0c5f34; }
    .decision.no-bid { background: #fdecec; border-color: #b4232c; color: #861a21; }
    [data-testid="stMetric"] { border-top: 2px solid #d6d9de; padding-top: .75rem; }
    .gate-status { display: inline-block; padding: .12rem .42rem; margin-right: .35rem;
                   color: white; font-size: .75rem; font-weight: 700; border-radius: 3px; }
    .gate-status.fail { background: #b4232c; }
    .gate-status.unknown { background: #9a6700; }
    .gate-status.pass { background: #147d47; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("RFP Triage Agent")
st.write("Upload a text-searchable government RFP to get an evidence-backed bid decision.")

with st.sidebar:
    st.text_input("Model", value=GEMINI_MODEL, disabled=True)
    as_of = st.date_input("As of", value=date.today())
    use_cache = st.toggle("Use cached result", value=True)

samples = sorted(path.name for path in SAMPLES_DIR.glob("*.pdf"))
sample_name = st.selectbox("Try a sample", ["Choose a sample", *samples])
uploaded_file = st.file_uploader("RFP PDF", type=["pdf"])

if st.button("Analyze", type="primary", use_container_width=False):
    st.session_state.pop("report", None)
    selection = chosen_file(uploaded_file, sample_name)
    if selection is None:
        st.info("Upload a PDF or choose a sample first.")
    else:
        file_bytes, file_name = selection
        key = cache_key(file_bytes, GEMINI_MODEL, PROMPT_VERSION)
        cached = load_cached(key) if use_cache else None
        if cached and cached.meta.get("as_of") != as_of.isoformat():
            cached = None
        if cached:
            st.session_state["report"] = cached.model_dump(mode="json")
            st.success("Loaded the cached analysis.")
        else:
            try:
                with st.status("Analyzing the RFP", expanded=True) as status:

                    def show_progress(event: TraceEvent) -> None:
                        detail = f" - {event.note}" if event.note else ""
                        status.write(f"{humanize(event.node)}: {event.seconds:.2f}s{detail}")

                    result = RfpTriagePipeline().run_pdf(
                        file_bytes,
                        file_name,
                        as_of=as_of,
                        progress=show_progress,
                    )
                    status.update(label="Analysis complete", state="complete", expanded=False)
                save_cached(result, key)
                st.session_state["report"] = result.model_dump(mode="json")
            except (PdfIngestError, LlmError) as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "The analysis could not be completed. Check the server logs and try again."
                )

if "report" in st.session_state:
    current_report = FinalReport.model_validate(st.session_state["report"]).model_dump(mode="json")
    render_header(current_report)
    report_tab, radar_tab, evidence_tab, json_tab = st.tabs(
        ["Report", "Disqualification Radar", "Evidence", "JSON"]
    )
    with report_tab:
        render_report(current_report)
    with radar_tab:
        render_radar(current_report)
    with evidence_tab:
        render_evidence(current_report)
    with json_tab:
        render_json(current_report)
