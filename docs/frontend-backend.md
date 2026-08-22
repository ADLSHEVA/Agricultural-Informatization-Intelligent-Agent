# Origin frontend and backend design

Language choice first, then screens, APIs, and data. This is the implementation spec that sits under the OPM framework.

Every subsection is marked **✅ built** (in the repo today, verified by `pytest` / `tsc`) or **⏳ planned** (decided, not wired). The point of the marks is to stop this document drifting from the code again. Cross-document decisions live in [`decisions.md`](decisions.md) — if this file contradicts it, this file is wrong.

Last verified 21 August 2026: `pytest` 32 passed with no credentials configured, `tsc --noEmit` clean, all nine Graphviz sources rendering. Block A/B screens wired. Desk inbox is one live file per farm and purpose.

Updated architecture diagrams (English):

- `opm/framework.txt` → `opm/rendered/framework.png` — overall framework, two Cloud Run services
- `opm/sd.txt` / `sd1.txt` / `sd1_1.txt` — SD, Sharing in-zoomed, Consenting in-zoomed
- `opm/states.txt` — consent lifecycle
- `opm/stack.txt` → `opm/rendered/stack.png` — TypeScript web + Python API + Gemini only on the API
- `opm/struct.txt` → `opm/rendered/struct.png` — aggregation with language labels
- `opm/legend.txt` — OPM notation key

## 1. Languages ✅

**Use two languages. Do not use one stack for both sides.**

| Side | Language | Why |
|---|---|---|
| Farmer PWA + Partner Desk | **TypeScript** | Browser, camera, MediaRecorder, PWA, large-tap UI. No serious alternative. |
| Origin API (compile, consent, agent, Gemini, geometry) | **Python 3.12** | Vertex AI / Gemini SDK is first-class; YAML rule packs + Pydantic are the compiler; the watercourse buffer check is `shapely`; FastAPI on Cloud Run is the cheap default. |

Rejected options:

| Option | Why not |
|---|---|
| All TypeScript (Next.js API routes) | Fine for a toy chat demo. Weak for a deterministic rule compiler, parcel geometry, and the Vertex AI SDK. One language saves setup, not the 48-hour risk. |
| Go / Java API | Cloud Run likes them. Gemini + YAML rules + geometry would eat the weekend. Java also tempts a full EDC connector, which we already refused. |
| PHP / Ruby (farmOS, Ekylibre) | Good FMIS history. Wrong product. Origin is not an FMIS. |
| Flutter / Kotlin native | Farmer must not visit an app store. PWA only. |

Runtime split:

- `apps/web` — TypeScript, Next.js 15 App Router, React 19. **Hand-written CSS** in `app/globals.css`; Tailwind was specced and not adopted. ⏳ PWA manifest exists, no service worker yet.
- `apps/api` — Python 3.12, FastAPI, Uvicorn, one Cloud Run service, `min-instances=0`.
- Shared contract: OpenAPI generated from FastAPI. ⏳ TypeScript types via `openapi-typescript`; `lib/api.ts` is hand-written today.

Gemini stays behind the Python API. The browser never reaches Vertex, and there is no key to leak — the credential is an ADC/service-account identity on `origin-api` only. ✅

---

## 2. Repository ✅

```
agri/
  apps/
    web/                    # TypeScript PWA
      app/
        page.tsx            # Today
        capture/page.tsx    # Speak / Snap + confirm draft
        consent/[id]/page.tsx
        receipts/page.tsx   # Who has it
        desk/page.tsx       # Partner Desk at /desk — questionnaire upload
        terms/page.tsx      # risk card, reached from /receipts (not a tab)
        layout.tsx
        globals.css         # hand-written, no Tailwind
      components/
        BigButton.tsx
        Shell.tsx           # three-tab farmer nav, hidden on /desk
      lib/
        api.ts              # hand-written client
        session.ts          # demo bearer tokens + API base
      public/manifest.json
    api/                    # Python
      origin/
        main.py             # routes only
        config.py           # ORIGIN_* settings; Vertex project/location/model
        auth.py             # bearer -> Principal, farmer_only / partner_only
        capture.py          # draft event + evidence files
        compile.py          # YAML rules, no LLM
        consent.py          # open_draft / bind / refuse / revoke / expire
        deliver.py          # token, receipt, lot passport, desk visibility
        agent.py            # standing policies, auto-deliver decisions
        geometry.py         # watercourse buffer, no LLM
        gemini_router.py    # Vertex via ADC + offline fallbacks
        models.py           # Pydantic records
        questionnaire.py    # block A: questionnaire -> draft rule pack
        terms.py            # block B: partner terms -> risk card (module only)
        seed.py             # demo farm + parcels + open request
        store.py            # JSON store (Firestore stand-in)
      rules/
        elevator_spray_statement.yaml   # US elevator
        coop_ppp_statement.yaml         # EU co-op
      .env.example          # environment reference (not auto-loaded)
      data/                 # gitignored JSON store + evidence blobs
      tests/
        test_compile.py
        test_flow.py
        test_questionnaire.py
        test_rules_and_config.py
  opm/                      # DOT sources + rendered PNG/SVG
  docs/
    decisions.md
    frontend-backend.md
```

⏳ Two Cloud Run services in `europe-west1`, one Firebase/GCP project. Model inference goes to Vertex at `ORIGIN_VERTEX_LOCATION`, default `global`.

---

## 3. Frontend (TypeScript)

### 3.1 Stack

- ✅ Next.js 15 (App Router) + React 19 + TypeScript strict
- ✅ Hand-written CSS, one column, no component library that ships a sidebar/dashboard
- ⏳ `next-pwa` or Serwist for install + offline shell — `public/manifest.json` only, so far
- ⏳ Firebase Auth (email magic link or demo PIN) — today `lib/session.ts` holds the two demo bearer tokens
- ✅ Fetch only the Python API; no Firestore from the browser

Visual constitution:

- **Office web first.** Challenge 3 (consent, receipts, terms, questionnaires) is the same class of work as John Deere Operations Center **Web** and EU CAP geospatial **online applications** — farm office / kitchen table, not in-cab. USDA (2023): 82% of farms have a smartphone *and* 69% a desktop/laptop; Deere ships Web + Mobile as two surfaces. Origin is the Web surface.
- Farmer pages: office web portal. Work canvas is **~90% of the viewport** (`min(90vw, 120rem)`), gutters `5vw`, aligned with the top bar. Cards fill that canvas (hero cards span the row; lists use `auto-fit` min 28rem). Body copy stays `max-width: 65ch`. Primary buttons cap at ~24rem so they do not become billboards. Light top bar on desktop (Today · Speak · Who), bottom tabs only below 800px. Not a phone chassis and not a 42rem reading strip on a 1440px monitor. Type: Outfit. Accent: forest green on bone paper (not cream+brass).
- Partner desk `/desk`: same ~90vw canvas, two columns on desktop.
- Touch targets ≥ 56px on the narrow layout; contrast for mixed indoor light (near-black on cream)
- No hamburger, no KPI tiles, no settings maze, no fourth farmer tab
- ⏳ First run: pick country (sets farmer locale for Gemini plain-talk) → tap one parcel (or accept the demo farm) → Today. Today the demo farm is seeded server-side.

### 3.2 Four farmer screens ✅

| Route | Job | Primary control | Must not show |
|---|---|---|---|
| `/` Today | One card: “record what you just did”, “<partner> wants a spray statement”, or “Origin already sent it” | One yellow button | Charts, menu |
| `/capture` Speak / Snap | Hold to talk, or take a photo of the can / note | Hold-to-talk + camera shutter | Form fields on first paint |
| `/consent/[id]` | Five plain lines **in the farmer’s locale** + Give / Refuse + standing-policy tick | Two equal buttons | “Accept all”, PDF terms |
| `/receipts` Who has it | Receipts; Revoke; Export my data; Erase my data | Revoke / Export / Erase | Partner analytics |

Bottom navigation is **three tabs** — Today · Speak · Who. `/consent/[id]` is reached by push from Today or Capture, never by tab. Partner Desk is `/desk`; `Shell.tsx` hides farmer nav there and farmer nav never links to it.

### 3.3 Capture interaction ✅

1. Farmer holds Speak. Browser records `audio/webm` via MediaRecorder.
2. Optional: camera `capture="environment"` for the product label.
3. `POST /v1/events` with `multipart/form-data` (`audio`, `image`, `parcel_id`, `note`).
4. API returns a **draft Farm Event** card: parcel, product, rate, buffer.
5. Farmer taps **That’s right** or edits at most three words, then `POST /v1/events/{id}/confirm`.
6. Confirm runs Compiling **and** the agent: it either routes to `/consent/{id}` or, under a standing policy, straight to `/receipts` with the pack already delivered.

⏳ If offline: queue the blob in IndexedDB; Today shows “will send when you have signal”. Do not run Gemini in the browser.

### 3.4 Consent card (the Challenge 3 surface) ✅

The API, not the UI, writes the lines. UI only renders. US demo:

```
Who:   Heartland Grain LLC
Why:   This season’s spray record for the elevator
What:  parcel_id=p3, date, product_name=X, rate=1.2, unit=L/ha, buffer_m=5, buffer_ok=True
       Not your yield or revenue.
Until: 31 Dec 2026
Reuse: No
```

EU demo, same event, `coop_ppp_statement_v1`, `locale=fr`:

```
Who:   Loire Cereals Co-op
Why:   Déclaration phytosanitaire de la saison
What:  … Pas de rendement ni de revenu.
Until: 31 Dec 2026
Reuse: Non
```

Buttons: **Give** · **Refuse**. Plus one tick box: *do this automatically next time* → `POST /v1/consents/{id}/bind {"standing": true}` also arms a `StandingPolicy`.

- Give → `POST /v1/consents/{id}/bind` → state `purpose-bound` → token + receipt + lot passport.
- Refuse → `POST /v1/consents/{id}/refuse` → state **`refused` (final)**. Do **not** delete the draft. No token, Desk never sees the pack. Receipts list keeps a “you said no” row so the farmer can prove they refused.

XOR: from `draft` the farmer handles Binding **or** Refusing, never both.

### 3.5 Client state ✅

Keep it boring. No Redux.

- Server state: plain `useEffect` + `fetch` against `/v1/*`. ⏳ React Query / SWR if refetching gets hairy.
- Local: `draft` after capture, demo token, ⏳ offline queue
- Routes are the state machine: Today → Capture → Consent → Receipts

### 3.6 Frontend modules

```
components/BigButton.tsx      # ✅ 56px+, one label, one action
components/Shell.tsx          # ✅ three-tab nav, hidden on /desk
lib/api.ts                    # ✅ hand-written; ⏳ generate from OpenAPI
lib/session.ts                # ✅ demo tokens + API base
lib/offlineQueue.ts           # ⏳
```

Cards, draft-event card, plain-talk block and receipt rows are inline in their page files. Extract only if a second page needs them.

---

## 4. Backend (Python)

### 4.1 Stack

- ✅ FastAPI + Pydantic v2 + Uvicorn
- ✅ `google-genai` against **Vertex AI** (`vertexai=True`), authenticated by **ADC only** — organisation policy forbids API keys. Project and location come from `ORIGIN_GCP_PROJECT` / `ORIGIN_VERTEX_LOCATION` (`origin/config.py`), default location `global`, `europe-west1` supported as an override
- ✅ `shapely` + `pyyaml`
- ✅ JSON store at `apps/api/data/origin.json`, evidence under `data/evidence/{farm}/{event}/`
- ⏳ `google-cloud-firestore`, `google-cloud-storage` — lazy imports behind `ORIGIN_STORE` / `ORIGIN_BUCKET`, so nothing breaks uninstalled
- ⏳ Firebase Admin to verify ID tokens; today two demo bearer tokens in `auth.py`, gated by `ORIGIN_DEMO_TOKENS`
- ✅ **No Secret Manager entry for the model credential** — ADC replaced it. Cloud Run gets `roles/aiplatform.user` on its service account instead of a stored key

No always-on Vertex endpoint. Call the model per request; scale to zero with the Cloud Run instance. With no project configured, `_client()` returns `None` and every call takes its deterministic fallback.

### 4.2 Bounded context (maps to OPM processes) ✅

| Module | OPM process | LLM? |
|---|---|---|
| `capture.py` | Capturing | Yes — audio/image/note → Farm Event JSON |
| `compile.py` | Compiling | **No** — YAML + geometry only |
| `consent.py` `open_draft` → Explaining | Explaining | Yes — pack → plain lines in farmer locale |
| `consent.py` Minimizing / Binding / Refusing / Revoking / Expiring | same | **No** |
| `deliver.py` | Delivering | No — issue token, write receipt, lot passport, desk gate |
| `agent.py` | Deciding (in-zoomed in [`opm/sd1_2.txt`](../opm/sd1_2.txt)) | **No** for the decision; ✅ yes for the narration written *after* it (block C) |
| `geometry.py` | instrument of Compiling | No — buffer vs watercourse |
| `questionnaire.py` ✅ module + routes + screens | Rule-pack authoring (block A) | Yes — **draft only**; `sanitize_draft()` then the farmer approves |
| `terms.py` ✅ module + routes + screens | Terms review (block B) | Yes — digest and phrasing only; the over-ask diff is code |
| `config.py` | — | No — settings, no logic |

If extraction fails, `gemini_router.py` falls back to a regex heuristic and returns a sparse draft for the farmer to fix. Do not escalate to Pro.

**Hard rule:** the model may read and phrase. It may never decide whether to share, and it may never run the buffer check. Blocks A, B and C obey this — model output is always a draft that a human or a YAML rule pack must approve. See `docs/decisions.md` D6.

### 4.3 HTTP API ✅

Farmer routes require a farmer bearer token; desk routes require a partner one. ⏳ Firebase ID tokens replace both.

```
GET    /health

GET    /v1/today                  farm, parcels, open_request, draft_consent,
                                  standing_policies, last_auto

POST   /v1/events                 multipart audio|image + parcel_id + note
GET    /v1/events/{id}
POST   /v1/events/{id}/confirm    -> event + pack + consent + auto + agent decision

GET    /v1/packs
GET    /v1/packs/{id}

POST   /v1/consents               { pack_id, partner_id, purpose }
GET    /v1/consents/{id}
POST   /v1/consents/{id}/bind     { standing?: bool } -> token + receipt + passport + policy
POST   /v1/consents/{id}/refuse   # draft -> refused (kept, not deleted)
POST   /v1/consents/{id}/revoke

GET    /v1/receipts
GET    /v1/me/export              # GDPR Art. 20 portable JSON (US label if country=US)
DELETE /v1/me                     # Art. 17 erase evidence + disable tokens

GET    /v1/desk/packs             partner; `desk_inbox` — one current file per farm+purpose, grey only if none live
GET    /v1/desk/packs/{id}        410 if revoked / expired / refused / erased
POST   /v1/desk/requests          partner asks; returns the agent decision

✅ POST   /v1/desk/questionnaires  partner; multipart farm_id + text + optional file
✅                                 -> RuleDraft (already sanitised), state proposed
✅ GET    /v1/rule-drafts          farmer; drafts awaiting a verdict
✅ POST   /v1/rule-drafts/{id}/approve   -> re-sanitises, writes the pack to the store
✅ POST   /v1/rule-drafts/{id}/reject    -> rejected (final, kept for the record)
✅ POST   /v1/terms/review         farmer; pasted clause -> TermsReview + over_ask[]
```

Block A routes are covered by `tests/test_questionnaire.py`. Block B routes are covered by `tests/test_terms.py`. Screens: `/desk` uploads a questionnaire; Today shows proposed drafts for Approve / Refuse; `/terms` is reached from Who (no fourth tab).

Error shape: `{ "code": "consent_unavailable", "message": "..." }`, sent as FastAPI `detail`. Never leak other farmers’ packs — every farmer route checks `row.farm_id == principal.farm_id`.

### 4.4 Canonical records

✅ as Pydantic models in `models.py`, persisted in the JSON store under the same collection names. ⏳ same shapes in Firestore.

```
farms/{farmId}
  country, locale, display_name

parcels/{parcelId}
  farm_id, lpis_id, label, crop, area_ha, geom (GeoJSON), watercourse_buffer_m

events/{eventId}
  farm_id, parcel_id, type, time, product_name, rate, unit, buffer_m, note,
  evidence_uris[], source (voice|photo|import|note), status (draft|confirmed), confidence

packs/{packId}
  farm_id, event_ids[], rule_id, partner_id, purpose, fields{}, checks{}, created_at

consents/{consentId}
  farm_id, pack_id, partner_id, partner_name, purpose, fields[], until, reuse,
  state (draft|purpose-bound|refused|expired|revoked|erased),
  locale, plain_talk { who, why, what, until, reuse }, request_id

receipts/{receiptId}
  farm_id, consent_id, pack_id, partner_name, pack_hash, field_list,
  issued_at, kind (given|refused), grey

tokens/{tokenId}
  consent_id, farm_id, partner_id, expires_at, revoked

requests/{requestId}
  farm_id, partner_id, partner_name, purpose, field_list, rule_id,
  status (open|linked|superseded), created_at

policies/{policyId}
  farm_id, partner_id, purpose, allowed_fields[], until, reuse,
  state (active|paused|revoked), created_from_consent_id

agent_log/{entryId}
  farm_id, request_id, pack_id, consent_id, policy_id, decision, reason, at,
  reason_code (new_partner|new_purpose|extra_fields|expired_policy|…),
  extra_fields[], note (the narration, written after the decision)

✅ rule_drafts/{draftId}            # block A — id rdr-<10hex>
  farm_id, partner_id, state (proposed|approved|rejected),
  pack{} (already through sanitize_draft), dropped_refused[] / dropped_unknown[],
  API also exposes refused_fields[] / unknown_fields[],
  plain_summary, created_at, decided_at

✅ rule_packs/{packId}              # block A — approved drafts, keyed like the YAML packs
  same shape as rules/*.yaml, plus origin: "questionnaire_draft"
  compile.load_rule reads these first; partner_index / rule_for_market overlay YAML

✅ terms_reviews/{reviewId}         # block B — id trv-<10hex>
  farm_id, partner_name, locale, resale, aggregation,
  third_parties[], retention_days, fields_claimed[],
  over_ask[] (computed in code, not by the model), red_flags[], created_at
```

`rule_drafts`, `rule_packs` and `terms_reviews` are in `store._empty()`. `compile.py` overlays `rule_packs` on `rules/*.yaml` (same id or same partner replaces the shipped pack; a new partner does not steal the market default).

Evidence paths locally: `data/evidence/{farmId}/{eventId}/audio.webm` and `label.jpg`. ⏳ `gs://…` with a 30-day lifecycle.

### 4.5 Farm Event (Gemini output, then farmer-confirmed) ✅

```json
{
  "parcel_ref": "3",
  "type": "plant_protection",
  "product_name": "X",
  "rate": 1.2,
  "unit": "L/ha",
  "buffer_m": 5,
  "confidence": 0.86
}
```

Pydantic validates keys and types. `capture.create_draft` resolves `parcel_ref` against real parcels and falls back to the parcel the farmer picked. Low confidence still shows the card; the farmer is the source of truth.

### 4.6 Rule packs (no LLM) ✅

One event, two packs. That is the whole two-market argument.

```yaml
# rules/elevator_spray_statement.yaml — US
id: elevator_spray_statement_v1
partner: heartland-grain
partner_name: Heartland Grain LLC
purpose: seasonal_spray_statement
until: end_of_calendar_year
reuse: false
fields: [parcel_id, date, product_name, rate, unit, buffer_m, buffer_ok]
exclude: [yield, revenue]
checks: [buffer_ok]
```

```yaml
# rules/coop_ppp_statement.yaml — EU
id: coop_ppp_statement_v1
partner: loire-cereals-coop
partner_name: Loire Cereals Co-op
purpose: seasonal_plant_protection_statement
until: end_of_calendar_year
reuse: false
fields: [parcel_id, date, product_name, rate, unit, buffer_m, gaec4_buffer_ok]
exclude: [yield, revenue]
checks: [gaec4_buffer_ok]
```

`compile.py` copies only listed `fields`, runs the buffer check under whichever name the pack uses, drops anything in `exclude`, and writes `packs/{id}`. `load_rule` looks up by pack `id`: store `rule_packs` first, then `rules/*.yaml`. A third pack is another YAML file — or an approved questionnaire draft — on the same event. That is Challenge 1 as a side effect, not a second product.

### 4.7 Gemini router ✅

Vertex AI, ADC only. `origin/config.py` holds project, location, model and the daily call cap; `gemini_router._generate()` is the single call site.

```
extract_event(note, parcel_hint, audio, image) -> FarmEventDraft   # regex fallback
explain_consent(partner_name, purpose, fields, until, reuse, locale) -> PlainTalk
✅ narrate_decision(decision, pack, policy, locale) -> str   # block C, after the decision
✅ draft_rule_pack(text) -> dict             # block A, then sanitize_draft(), then the farmer
✅ digest_terms(text, locale) -> dict        # block B, then the code-computed over-ask diff
```

`locale` comes from `farms.locale`. Explaining writes the card in that language at almost no extra token cost. Every call is wrapped so that no credentials and no network still complete the demo loop.

✅ `_generate()` logs model name, location and prompt/output/total token counts on every call, and enforces `ORIGIN_LLM_DAILY_CALL_CAP` in-process. ⏳ context cache for system prompts and a Cloud billing budget cap.

### 4.8 Origin agent ✅

`agent.py` answers “the partner asked again — now what?” without a chat turn and without Gemini.

```
activate_standing(bound_consent)              -> StandingPolicy       # farmer ticked the box
match_standing(farm, partner, purpose, fields)-> StandingPolicy | None
fulfill_pack(pack, request_id, locale)        -> ask | auto
tick_request(partner_request)                 -> need_capture | ask | auto
```

Decision table, every row logged to `agent_log`:

| Decision | When | Effect |
|---|---|---|
| `need_capture` | no confirmed event, or it points at an unknown parcel | Today asks the farmer to record |
| `ask_farmer` | no active policy covers (partner, purpose, ⊇ fields) | draft consent, farmer gives or refuses |
| `auto_deliver` | a policy matches and `set(pack.fields) ⊆ set(policy.allowed_fields)` and `until` not passed | bind, issue token + receipt, surface on Today as `last_auto` |

Containment is strict and one-directional: an extra field the farmer never approved drops the request back to `ask_farmer`. Purpose must match exactly. Revoking the consent or the policy stops all future auto-delivery.

---

## 5. Auth and tenancy

- ⏳ Farmer: Firebase Auth → API verifies JWT → `farm_id` from custom claim. ✅ today: `Authorization: Bearer demo-farmer`.
- ⏳ Partner: same project, role `partner`, `partner_id` claim. ✅ today: `Bearer demo-partner` → `heartland-grain`.
- ✅ Desk queries only packs whose consent is `purpose-bound` **and** whose token is live; anything else is returned as a greyed row with empty fields.
- ✅ Revoke: set consent `revoked`, disable tokens, grey receipts. Desk GET returns 410. Farmer receipts stay.
- ✅ Refuse: set consent `refused` (final). No token. Desk 410. Keep the document so the farmer can show they said no.
- ✅ Expire: `expire_if_due` runs lazily on every desk read; past `until` → `expired`, tokens disabled, receipts greyed.
- ✅ Export (`GET /v1/me/export`): JSON portable pack of farm, parcels, events, packs, consents, policies, receipts. Labelled GDPR Art. 20, or “US farm-data originator portable copy” when `country == "US"`.
- ✅ Erase (`DELETE /v1/me`): wipe evidence blobs, blank note/product/rate on events, tombstone consents as `erased`, disable all tokens, revoke policies. Receipts remain as hash-only stubs so the farmer still sees “who had it”. Not a fifth screen.

⏳ No public bucket listing; evidence URLs signed and short-lived.

---

## 6. Deploy and cost (matches the framework) ⏳

| Service | Image | Scaling |
|---|---|---|
| `origin-web` | Node, Next.js | Cloud Run `min=0` |
| `origin-api` | Python 3.12 slim | Cloud Run `min=0`, 512Mi, concurrency 20 |
| Firestore / Storage / Auth | managed | pay per use |
| Gemini | Vertex AI, Flash tier, ADC via the service account (`roles/aiplatform.user`) | no dedicated endpoint |

Local today: FastAPI on `:8000` + `next dev` on `:3000` + the JSON store — no emulator needed. Production: one GCP project, Cloud Run in `europe-west1`, Vertex inference at `ORIGIN_VERTEX_LOCATION` (`global` by default; see `docs/decisions.md` D3 for the residency trade-off).

---

## 7. 48-hour cut

Working now ✅:

1. Demo farm, six parcels, one watercourse
2. Voice, photo, or typed note → draft event → confirm
3. Two YAML packs (US elevator + EU co-op) off one event, with the buffer check
4. Plain-talk consent → Give / Refuse → receipt
5. Desk can open the pack; Revoke greys it out
6. Standing policy → partner asks again → agent auto-delivers → Today reports it

Can wait ⏳: ISOXML import, real LPIS, offline sync polish, native speech-to-text besides Gemini audio, Firebase Auth, Firestore/GCS.

---

## 8. Why this split holds the OPM model

- Farmer **handles** Capturing, Consenting, Refusing, Revoking, Exporting, Erasing — those are the only TypeScript screens that call mutating endpoints.
- Vertex AI Gemini is an **environmental instrument** of Capturing, Explaining, Narrating, Authoring and Digesting — Python owns the client, and it holds an ADC, never a key.
- Rule Pack is an **instrument** of Compiling — Python, no model.
- Standing Policy is an **instrument** of the agent’s Deciding — the farmer draws the box, the machine stays inside it. ✅ now drawn, in [`opm/sd1_2.txt`](../opm/sd1_2.txt) (Deciding in-zoomed) as well as `framework`, `stack`, `sd`, `sd1` and `struct`.
- Sanitising is a **process**, not a promise: the `AutoDeliver -> Narrating` edge in SD1.2 is labelled *verdict, already final*, which is D6 drawn rather than asserted.
- Partner Desk is a separate object. The farmer PWA must not import it.
