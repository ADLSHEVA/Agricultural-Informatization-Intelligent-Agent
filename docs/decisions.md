# Origin — decision record

One row per decision that more than one document depends on. If a statement
elsewhere in the repo contradicts a row here, this file wins and the other
document is wrong.

Last updated: **20 August 2026**

## Model and cloud

| # | Decision | Supersedes |
|---|---|---|
| **D1** | Authentication to Gemini is **ADC only**. No API keys anywhere in code, docs, or deployment — the organisation's security policy forbids them. Local: `gcloud auth application-default login`. Cloud Run: the service account, with `roles/aiplatform.user`. | every `GEMINI_API_KEY` / `GOOGLE_API_KEY` instruction |
| **D2** | **Vertex AI**, not AI Studio: `genai.Client(vertexai=True, project=…, location=…)`. Project `project-5e761e8c-65aa-4033-8cb`, overridable with `ORIGIN_GCP_PROJECT`. | the AI Studio client |
| **D3** | Location **`global`** by default — verified working on the dev machine. `europe-west1` stays a supported override (`ORIGIN_VERTEX_LOCATION`) for an EU data-residency demo, subject to the model being served there. | unconditional `europe-west1` |
| **D4** | Model **`gemini-3.7-flash`**, overridable with `ORIGIN_GEMINI_MODEL`. The cost guard is now "**Flash tier only, never Pro**". | `gemini-2.5-flash-lite`, and the phrase "Flash-Lite only" |
| **D5** | **No Secret Manager entry for a model credential.** ADC removes the secret, so the wiring is an IAM binding, not a stored string. | "Secret Manager for the Gemini/Vertex credential" |

### Residency caveat — state it, do not bury it

`location="global"` routes inference outside a guaranteed EU region. Origin's
GDPR argument does not rest on inference locality; it rests on **which fields
ever leave the farm**. The compile step ships the minimised field set named in a
YAML rule pack and never yield or revenue, and the farmer holds revoke and
erase. If a judge presses on residency, `ORIGIN_VERTEX_LOCATION=europe-west1` is
the switch, and the only cost is model availability in that region.

## Authority

| # | Decision |
|---|---|
| **D6** | Gemini may **read and phrase**. It may **never** decide whether to share, and it may **never** run the buffer check. Everything the model emits is a *draft* that a human or a deterministic YAML rule pack must approve before it has any effect. |

D6 is enforced in code, not by convention:

- `compile.py` and `geometry.py` contain no model call at all.
- `agent.py` reaches its decision by policy match **first**; narration is
  generated afterwards and is discarded without changing anything if it fails.
- Block A's `sanitize_draft()` intersects any model-proposed field list with the
  canonical vocabulary and unconditionally drops `yield` and `revenue`, so a
  questionnaire cannot widen the field set by asking nicely.

## Scope

| # | Decision |
|---|---|
| **D7** | Licence **Apache-2.0** (`LICENSE`). | 
| **D8** | Confirmed feature blocks: **A** questionnaire → draft rule pack, **B** partner terms → plain-talk risk card, **C** agent decision narration + over-ask diff, **F** GCP wiring. Declined this round: vendor export mapping (Deere / FieldView / ISOXML import), once-only cross-partner dedup. |
| **D9** | Block F is delivered as **code-ready plus deployment manifests**, not a live deploy. Cloud adapters are lazy imports behind settings, so the local JSON store and the offline fallbacks keep the demo runnable with no credentials and no cloud SDKs installed. |
| **D10** | Two markets from one core: the same event compiles into a US pack (`elevator_spray_statement_v1`, `buffer_ok`) and an EU pack (`coop_ppp_statement_v1`, `gaec4_buffer_ok`). Selection follows `farms.country` / `farms.locale`. Nothing in `origin/` is jurisdiction-specific. |
| **D11** | `reuse: false` is enforced, not decorative: a compiled pack can be granted **once**. Binding a second consent for the same pack raises 409 `reuse_forbidden`, even after revoke or expiry — sharing again needs a fresh compile, which returns to the farmer. Auto-delivery compiles a new pack per request, so standing policies are unaffected. | — |

## Superseded, for the record

Anything below is **no longer true** and should be deleted on sight:

- `GEMINI_API_KEY` or `GOOGLE_API_KEY` as a way to run Origin (D1)
- "Gemini Flash-Lite `gemini-2.5-flash-lite`" as the model (D4)
- "AI Studio key" as the auth path (D2)
- "Secret Manager for the Gemini/Vertex credential" (D5)
- EUPL-1.2 as the licence (D7)
- "the agent contains no Gemini" — it now does, bounded by D6
