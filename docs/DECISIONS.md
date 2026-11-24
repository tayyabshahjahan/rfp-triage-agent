# Engineering Decisions

1. **Two model stages.** One giant prompt and many specialized agents were considered. Extraction
   is profile-free so company assumptions cannot contaminate document facts; assessment then uses
   only verified extraction.

2. **LangGraph only for control flow.** A plain function chain was considered. The bounded repair
   loop and fast no-bid branch justify a small state graph; business logic remains ordinary Python.

3. **Whole-document extraction.** RAG and per-page map-reduce were considered. RFPs fit the chosen
   model's long context, and whole-document reading preserves addenda and cross-page relationships.

4. **Evidence on every material item.** Trusting structured output was considered. Short quotes and
   physical pages make mistakes visible and allow deterministic verification.

5. **Fuzzy matching only after exact checks.** Embeddings were considered. Normalized text plus a
   strict RapidFuzz threshold is smaller, explainable, and does not need another service.

6. **Editable profile constant.** A database and hidden prompt text were considered. One verbatim
   constant makes the only allowed company facts reviewable and prevents accidental enrichment.

7. **Code owns maths and dates.** Letting Gemini calculate scores and urgency was considered.
   Decimal half-up rounding, ISO checks, and `as_of` calculations are deterministic and testable.

8. **Fast no-bid route.** Always running a nuanced assessment was considered. Clearly unrelated
   scopes need a quick, cheap answer, while gates and questions still remain visible.

9. **Hand-written ICS.** A runtime calendar dependency was considered. The needed RFC 5545 subset
   is small; tests parse the result with `icalendar` as a development-only dependency.

10. **Streamlit Community Cloud.** A separate API and frontend were considered. Streamlit provides
    uploads, tables, secrets, and downloads on a free GitHub-linked deployment with much less code.
