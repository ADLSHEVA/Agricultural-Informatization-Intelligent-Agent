# Origin decision record

Last updated: **26 August 2026**. When another document conflicts with this file, this record wins.

## Product and competition

| ID | Decision | Reason |
|---|---|---|
| D1 | Origin is optimized for Google's All Things Agentic Hackathon and the Taskmaster use case. | A durable request-to-action workflow is stronger than a generic farm assistant. |
| D2 | This submission supports one market and one loop: a US grain partner requests a parcel-specific spray statement from a farmer. Unsupported markets fail closed. | Judges should understand the product in one sentence and one demo. |
| D3 | The differentiator is bounded delegation: capture once, automatically fulfill only requests inside a farmer-drawn permission boundary. | It combines useful automation with a defensible trust model. |

## Agent architecture

| ID | Decision | Reason |
|---|---|---|
| D4 | Use the Google Gen AI SDK directly; do not add LangGraph for this submission. | The judged path stays visibly Google-native, while `AgentRun` and Cloud Tasks already provide the state machine and retry semantics required here. |
| D5 | Every new partner request creates a durable `AgentRun`; an equivalent still-open request reuses that request and run. | Queueing, retries, status, trace IDs, and human pauses become inspectable without stacking duplicate work. |
| D6 | Cloud Tasks dispatches production runs; local development executes the identical lifecycle inline. | The demo is resilient offline without creating a second behavior model. |
| D7 | Delivery is idempotent per consent and may target the Partner Desk, Cloud Storage, and an optional HMAC-signed webhook. | A useful agent must take an external action without duplicating it on retry. |

## Model authority

| ID | Decision |
|---|---|
| D8 | Gemini may extract, classify, summarize, and phrase. It may never authorize a share, run the field geometry check, or expand a requested field set. |
| D9 | The deterministic gate alone checks partner, purpose, requested-field containment, expiry, reuse, and geometry. |
| D10 | Model output is a draft until farmer confirmation or deterministic validation. Every call records model, provider, location, token metadata, fallback reason, and trace ID. |
| D11 | Vertex AI uses Application Default Credentials. No Gemini API key is stored in code, deployment configuration, or documentation. |

## Data and consent

| ID | Decision |
|---|---|
| D12 | A consent screen displays exact field names and values, recipient, purpose, and expiry. Standing permission is opt-in and scoped to the same dimensions. |
| D13 | Revocation disables Origin-issued access immediately and records a recipient notice. The UI never claims it can delete a copy already downloaded by a recipient. |
| D14 | Private-tenant erasure removes events, evidence, managed GCS inbox/notice objects, delivery payloads, model/run traces, questionnaire/terms source text, and permission fields while retaining hash-only receipt/delivery stubs. Recipient notices are sent first; the public shared demo blocks erasure. |
| D15 | Yield and revenue are denied at the compiler boundary, including model-generated synonyms normalized from questionnaires. |

## Runtime and deployment

| ID | Decision |
|---|---|
| D16 | Production serves the responsive Next.js web app on Render; the agent and data plane use Cloud Run, Cloud Tasks, Firestore, Cloud Storage, Vertex AI, and Cloud Logging. The local profile uses JSON and local blobs. |
| D17 | Firebase ID-token verification is supported for production; explicit demo principals remain available only when `ORIGIN_DEMO_TOKENS=true`. |
| D18 | Gemini 3.7 Flash is the default model and may be overridden through `ORIGIN_GEMINI_MODEL`. `global` is the default Vertex location; a regional location may be selected when model availability and residency needs require it. |
| D19 | Apache-2.0 is the repository license. |
| D20 | Origin is one responsive web product, not a separate native mobile app. Farmer capture is touch-friendly; consent review and the Partner Desk are progressively desktop-oriented. |
| D21 | A partner request identifies a parcel. Confirm retries resume the same event; request and run transitions use compare-and-set, and cloud workers require both HMAC and Google OIDC. |

## Non-goals for this submission

- Replacing a farm-management information system
- Letting a model autonomously invent data-sharing policy
- Claiming legal compliance or remote deletion of recipient downloads
- ISOXML, OEM, or real land-registry integrations
- A second orchestration framework that does not improve the demo outcome
