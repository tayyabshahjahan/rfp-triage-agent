# Demo Questions And Short Answers

1. **Why this Gemini model?** It has a long context window, structured output, a stable Flash-Lite
   endpoint, and a free tier. The name is configurable because model availability changes.

2. **Why two model calls?** The first call extracts only document facts. The second judges fit only
   after code verifies the evidence, which separates reading from company-specific judgment.

3. **Why LangGraph?** The app has a real retry loop and a real fast-route branch. The individual
   nodes are still small Python functions.

4. **How do you know a quote is real?** Code normalizes the quote and page text, checks the stated
   page, checks every other page, and only then allows a 92+ fuzzy match.

5. **What stops hallucinated dates?** A date must have a verified quote. Code also parses the exact
   printed text and warns when it disagrees with the model's ISO date.

6. **What if the PDF is scanned?** It is rejected with an OCR-not-supported message based on low
   text density and empty-page ratio.

7. **What if it is 300 pages?** It is rejected at the configurable page limit. The next design would
   use chunked extraction with cross-chunk reconciliation and the same quote checks.

8. **What happens on a 429?** The Gemini adapter retries with exponential backoff up to three times,
   then shows a friendly rate-limit message. Cached results avoid repeat calls.

9. **How are secrets handled?** Environment variables take priority, then Streamlit secrets. Keys
   are ignored by git and are never logged, cached, or placed in Docker layers.

10. **Why can a gate be UNKNOWN?** The company profile is intentionally sparse. Missing facts such
    as certifications, registrations, employee count, and past projects cannot become PASS.

11. **How is the score calculated?** Gemini supplies four explained factor scores. Code applies
    fixed weights, half-up rounding, and no-bid guardrails.

12. **What is the Disqualification Radar?** It puts mechanical rejection risks, required actions,
    due dates, consequences, and evidence in the order a bid lead should handle them.

13. **How do addenda work?** The extraction prompt requires the latest authoritative date, keeps the
    replaced date in `superseded`, and flags ambiguity rather than silently choosing.

14. **Why no vector database?** One RFP fits the model context. RAG could hide appendices or separate
    an addendum from the date it changes, while adding infrastructure without solving verification.

15. **What would you build next?** OCR, more golden documents, chunked processing for very long RFPs,
    and a human approval step before a bid decision is acted on.
