# RFP Triage Agent

An evidence-first Streamlit app that reads one text-searchable government RFP and returns a
human-readable bid triage report plus downloadable JSON and calendar files.

**Live app:** https://rfp-triage-agent.streamlit.app

## What It Does

- Extracts facts, dates, requirements, ambiguities, and disqualification gates from every page.
- Verifies each quoted source against the PDF before company fit is assessed.
- Scores fit against one editable, verbatim idiaz.io profile and applies deterministic no-bid rules.
- Shows the Disqualification Radar and a merged Do-By Calendar with `.ics` download.
- Caches reports by document hash, model, and prompt version to conserve free-tier quota.

The app does not search for RFPs, write proposals, or use outside facts about idiaz.io.

## Quick Start

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at least one of `GEMINI_API_KEY` or `GROQ_API_KEY`. The default provider order is
`gemini,groq`; configure it with `LLM_PROVIDER_ORDER`. `GEMINI_FALLBACK_MODEL` optionally adds
a second Gemini model before the app moves to Groq. The app reads environment variables first
and then Streamlit secrets.

```bash
streamlit run app.py
```

Optional Docker path:

```bash
docker build -t rfp-triage-agent .
docker run --rm -p 8501:8501 -e GEMINI_API_KEY=your_key rfp-triage-agent
```

## Architecture

```mermaid
flowchart LR
    A[ingest: code] --> B[analyze: LLM]
    B --> C[verify: code]
    C --> D[recall: LLM]
    D --> C
    C -->|bad quote, attempts left| E[repair: LLM]
    E --> C
    C -->|relevance STRONG/PARTIAL| F[assess_full: LLM]
    C -->|relevance NONE| G[assess_fast: LLM]
    F --> H[guardrails: code]
    G --> H
    H --> I[build_report: code]
```

| Node | Why code or LLM |
|---|---|
| `ingest` | PDF parsing, page limits, and scanned detection are deterministic. |
| `analyze` | A model is useful for reading varied prose, tables, appendices, and forms. |
| `verify` | Source quotes must be checked mechanically, not trusted because a model supplied them. |
| `recall` | A second pass receives the first inventory and uncovered obligation cues, then returns only missing requirements and dates. |
| `repair` | The model gets one narrow chance to find corrected evidence for only failed items. |
| `assess_full` | Fit and delivery judgment need language understanding, but only over verified extraction. |
| `assess_fast` | Clearly unrelated work gets a cheaper, decisive no-bid while retaining a full report. |
| `guardrails` | Weights, rounding, score caps, and forced no-bids must be repeatable. |
| `build_report` | Date checks, radar ordering, calendar creation, and JSON assembly are deterministic. |

LangGraph earns its place here because the verify-and-repair loop and fast no-bid route are real
control-flow branches. Without those branches, plain Python would be simpler.

## Model Choice

The default Gemini model is `gemini-3.5-flash-lite`, configurable with `GEMINI_MODEL`. Google's official model
page, checked on 2026-11-25, lists it as a stable Flash-Lite model with a 1,048,576-token input
limit, 65,536-token output limit, structured outputs, and free-tier use. Those properties fit
long RFPs and the no-payment-card constraint. Temperature is zero and thinking uses the model's
supported `MINIMAL` level for predictability and latency.

The second provider uses the official Groq SDK and `openai/gpt-oss-120b`, configurable with
`GROQ_MODEL`. It supports JSON-schema output and an 8,000-token free-tier response budget,
which is large enough for the extraction schema; Qwen's 1,000-token free-tier output allowance was
not. Pydantic validates every response after provider-side structured output.
Groq calls are spaced at least 30 seconds apart to respect its free-plan request limit. A run that
falls back repeatedly can therefore take longer than the normal Gemini path. Both
providers retry 429 and 5xx responses with exponential backoff, then fail over in the configured
order.

All provider access lives in `rfp_agent/llm.py` behind
`generate_json(prompt, schema) -> validated object`.

## Accuracy Controls

Every extracted fact, deadline, requirement, gate, and ambiguity carries a short quote and a
1-based physical page. Verification normalizes Unicode, quotes, dash characters, soft hyphens,
line-break hyphenation, whitespace, and case. It checks the stated page, searches other pages and
corrects the page number, then permits fuzzy matching only at 92 or higher. Unsupported items are
repaired at most twice and otherwise remain visibly `UNVERIFIED`.

The assessment receives a copy containing only verified evidence plus this exact profile:

> A US-registered, AI-native engineering studio with a small senior team. What we build:
> automation platforms, compliance tooling, AI-integrated ops software, web and mobile apps.

Missing company facts therefore remain `UNKNOWN`, never inferred as `PASS`.

## Scoring And Guardrails

The raw score is:

`0.35*scope_fit + 0.25*eligibility + 0.20*delivery_feasibility + 0.20*commercial_risk`

Code rounds half up. A `scope_fit` of 2 or lower caps the result at 2 and forces `NO_BID`. Any
failed gate also forces `NO_BID`. If code changes the model decision, the reason is shown in the
report. Suspicious score/decision combinations produce warnings but are not silently changed.

## Bonus Feature: Disqualification Radar

The radar puts mechanical rejection risks before proposal scoring: mandatory meetings,
eligibility, registrations, bonds, submission mechanics, forms, addenda, onsite rules, and price
ceilings. Each row includes status, required action, do-by date, consequence, and verified quote.
The same actions are merged with all deadlines into a chronological calendar and `.ics` file.
I chose it because a good scope match is irrelevant when one missed filing, certification, bond,
or contact restriction makes the proposal nonresponsive. The feature is visible as its own UI tab.

## Tests And Sample Results

Network-free checks:

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest
```

Current local result: **50 passed** on Python 3.13.5. The tests cover evidence normalization and
matching, dates, scoring guardrails, radar sorting, RFC 5545 parsing, ingest validation, and both
LangGraph routes with a FakeLLM, plus provider retry and failover behavior.

Run the two real PDFs with:

```bash
python scripts/run_samples.py
```

Create hash-addressed saved results only through the live pipeline:

```bash
python scripts/save_precomputed.py samples/example.pdf
python scripts/compare_providers.py
```

| Sample | Expected | Real result | Time |
|---|---:|---:|---:|
| Port Alder `PA-DPI-2026-114` | BID, score >= 7 | PASS | 22.08s |
| Larkspur `LC-FM-2027-03` | NO_BID, score <= 2 | PASS | 14.87s |

Measured locally on 2026-11-25 with `gemini-3.5-flash-lite`; free-tier latency can vary.

## Deployment

The target is Streamlit Community Cloud because it is free, deploys directly from GitHub, and
supports encrypted app secrets. Select `app.py` as the entry point, make the app public, add the
provider API keys in the Cloud secrets editor, and keep `.streamlit/secrets.toml` out of git. No
secret is baked into the Docker image, cache, report, prompt logs, or CI.

## What Went Wrong And How I Fixed It

- A Cedar Hollow test run captured its feature matrix but skipped obligations buried in security,
  acceptance, support, submission and contract sections. I reproduced it from the downloaded JSON,
  expanded the section-by-section extraction rules, and added deterministic uncovered-line cues to
  the recall pass.
- The calendar initially crashed when a model returned non-ISO dates or times. Date/time parsing now
  validates defensively, normalizes US timezone names to IANA zones, and inherits timezone headings
  such as `Date and time (Pacific)`.
- The first Streamlit deployment attempted to build an older PyArrow on Python 3.14 and failed for
  lack of CMake. Updating Streamlit and pinning a wheel-backed PyArrow fixed the cloud build; later
  deploys also added automatic Gemini-to-Groq failover for free-tier outages.

## Known Limitations

- Scanned PDFs are rejected. Next: add OCR with page-level confidence and retain physical pages.
- PDFs over the configured limit are rejected. Next: add verified chunked map-reduce extraction.
- The model can still miss or misunderstand language. Next: add more golden RFPs and human review.
- Free-tier quotas can still exhaust both configured providers during sustained traffic.
- This is bid triage, not legal advice. Next: add an explicit review/approval workflow.

AI coding assistants were used; the author is responsible for the result and can explain every part.
