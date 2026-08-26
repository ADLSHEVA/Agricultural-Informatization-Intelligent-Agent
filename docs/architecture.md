# Architecture

![Origin Google Cloud architecture](architecture.png)

Origin separates ambiguity from authority:

- Render serves one responsive Next.js application: touch-friendly farmer capture in the field and a desktop-first Partner Desk in the office. The browser holds no Google Cloud credentials.
- Gemini 3.7 Flash on Vertex AI reads voice, photos, questionnaires, and phrases short explanations.
- The deterministic gate alone decides whether a share is covered by the farmer's standing permission. It checks partner, purpose, field containment, expiry, and field geometry.
- Every partner request becomes an `AgentRun` before execution. Cloud Tasks dispatches it asynchronously and retries failures; the local profile runs the same lifecycle inline.
- Firestore holds durable state and the farmer-readable step trace. Cloud Storage holds evidence and a partner-specific JSON inbox. An optional HMAC-signed webhook integrates a partner's own system.
- Every model call and background run carries the same trace ID into Cloud Logging. The UI exposes action summaries and model provenance, never private chain-of-thought.

## Failure boundaries

| Failure | Behaviour |
|---|---|
| Vertex unavailable or daily cap reached | Deterministic fallback; provenance says fallback |
| Missing confirmed fact | Run pauses at `waiting_for_farmer`; nothing is sent |
| New purpose or extra field | Scoped consent card; nothing is sent |
| Duplicate task or HTTP retry | Existing request, consent, and delivery identifiers are reused |
| Partner webhook failure | Delivery is marked failed; Cloud Tasks retries the run |
| Consent revoked | Access token dies immediately; recipient notice is recorded without claiming downloaded copies disappeared |

The large OPM diagrams in `opm/` remain the detailed engineering appendix. This page is the judge-facing architecture.
