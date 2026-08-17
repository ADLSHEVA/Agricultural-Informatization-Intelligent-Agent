# Origin frontend and backend design

Language choice first, then screens, APIs, and data. This is the implementation spec that sits under the OPM framework.

Updated architecture diagrams (English):

- `opm/framework.txt` → `opm/rendered/framework.png` — overall framework, two Cloud Run services
- `opm/stack.txt` → `opm/rendered/stack.png` — TypeScript web + Python API + Gemini only on the API
- `opm/struct.txt` → `opm/rendered/struct.png` — aggregation with language labels

## 1. Languages

**Use two languages. Do not use one stack for both sides.**

| Side | Language | Why |
|---|---|---|
| Farmer PWA + Partner Desk | **TypeScript** | Browser, camera, MediaRecorder, PWA, large-tap UI. No serious alternative. |
| Origin API (compile, consent, Gemini, geometry) | **Python 3.12** | Vertex AI / Gemini SDK is first-class; YAML rule packs + Pydantic are the compiler; GAEC 4 buffer is `shapely`; FastAPI on Cloud Run is the cheap default. |

Rejected options:

| Option | Why not |
|---|---|
| All TypeScript (Next.js API routes) | Fine for a toy chat demo. Weak for a deterministic rule compiler, parcel geometry, and Vertex in `europe-west1`. One language saves setup, not the 48-hour risk. |
| Go / Java API | Cloud Run likes them. Gemini + YAML rules + geometry would eat the weekend. Java also tempts a full EDC connector, which we already refused. |
| PHP / Ruby (farmOS, Ekylibre) | Good FMIS history. Wrong product. Origin is not an FMIS. |
| Flutter / Kotlin native | Farmer must not visit an app store. PWA only. |

Runtime split:

- `apps/web` — TypeScript, Next.js App Router, Tailwind, PWA. Static export or Node on Cloud Run.
- `apps/api` — Python 3.12, FastAPI, Uvicorn, one Cloud Run service, `min-instances=0`.
- Shared contract: OpenAPI generated from FastAPI; TypeScript types via `openapi-typescript`.

Gemini stays behind the Python API. The browser never holds a Gemini key.

---

## 2. Repository

```
agri/
  apps/
    web/                  # TypeScript PWA
      app/
        page.tsx          # Today
        capture/page.tsx
        consent/[id]/page.tsx
        receipts/page.tsx
        desk/page.tsx     # Partner Desk, separate host or /desk
      components/         # Card, BigButton, PlainTalk, ReceiptRow
      lib/api.ts
    api/                  # Python
      origin/
        main.py
        capture.py        # Gemini extract
        compile.py        # YAML rules, no LLM
        consent.py        # bind / revoke / explain
        geometry.py       # GAEC 4 buffer
        models.py
        gemini_router.py  # Flash-Lite only
      rules/
        ie_cap_2026.yaml
        coop_ppp_statement.yaml
      tests/
  opm/                    # DOT + rendered diagrams
  docs/
```

Two Cloud Run services, one Firebase/GCP project, region `europe-west1`.

---

## 3. Frontend (TypeScript)

### 3.1 Stack

- Next.js 15 (App Router) + TypeScript strict
- Tailwind, no component library that ships a sidebar/dashboard
- `next-pwa` or Serwist for install + offline shell
- Firebase Auth (email magic link or demo PIN for the weekend)
- Fetch only the Python API; no Firestore from the browser except Auth

Visual constitution (from LiteFarm / sonu-ai / SARAL):

- One column, max width 28rem, phone first
- Touch targets ≥ 56px
- Contrast for sunlight (near-black on cream, not grey on white)
- No hamburger, no KPI tiles, no settings maze
- First run: pick country (sets farmer locale for Gemini plain-talk) → tap one parcel (or accept the demo farm) → Today

### 3.2 Four farmer screens

| Route | Job | Primary control | Must not show |
|---|---|---|---|
| `/` Today | One card: “record what you just did” or “Co-op wants a spray statement” | One yellow button | Charts, menu |
| `/capture` Speak / Snap | Hold to talk, or take a photo of the can / note | Hold-to-talk + camera shutter | Form fields on first paint |
| `/consent/[id]` | Three lines **in the farmer’s locale** + Give / Refuse | Two equal buttons | “Accept all”, PDF terms |
| `/receipts` Who has it | Receipts; Revoke; Export my data; Erase my data | Revoke / Export / Erase | Partner analytics |

Partner Desk is `/desk` on a second hostname or a query flag. Farmer navigation never links there.

### 3.3 Capture interaction

1. Farmer holds Speak. Browser records `audio/webm`.
2. Optional: camera `capture="environment"` for the product label.
3. `POST /v1/events` with `multipart/form-data` (`audio`, `image`, `parcel_id`).
4. API returns a **draft Farm Event** card: crop, product, rate, parcel, buffer note.
5. Farmer taps **That’s right** or edits at most three words, then `POST /v1/events/{id}/confirm`.
6. Confirm runs Compiling. Today then shows “Co-op can use this — review consent”.

If offline: queue the blob in IndexedDB; Today shows “will send when you have signal”. Do not run Gemini in the browser.

### 3.4 Consent card (the Challenge 3 surface)

The API, not the UI, writes the three lines. UI only renders:

```
Who:   Loire Cereals Co-op
Why:   This season’s plant-protection statement
What:  Parcel 3, product X, 1.2 L/ha, date — not your yield
Until: 31 Dec 2026
Reuse: No
```

Buttons: **Give** · **Refuse**.

- Give → `POST /v1/consents/{id}/bind` → state `purpose-bound` → token + receipt.
- Refuse → `POST /v1/consents/{id}/refuse` → state **`refused` (final)**. Do **not** delete the draft. No token, Desk never sees the pack. Receipts list keeps a “you said no” row so the farmer can prove they refused.

XOR: from `draft` the farmer handles Binding **or** Refusing, never both.

### 3.5 Client state

Keep it boring. No Redux.

- Server state: React Query or SWR against `/v1/*`
- Local: `draftEvent` after capture, auth token, offline queue
- Routes are the state machine: Today → Capture → Consent → Receipts

### 3.6 Frontend modules

```
components/BigButton.tsx      // 56px+, one label, one action
components/TodayCard.tsx
components/DraftEventCard.tsx // confirm / fix three words
components/PlainTalk.tsx      // the three-line consent
components/ReceiptRow.tsx     // who, until, revoke
lib/api.ts                    // typed client from OpenAPI
lib/offlineQueue.ts
```

---

## 4. Backend (Python)

### 4.1 Stack

- FastAPI + Pydantic v2 + Uvicorn
- `google-genai` or `google-cloud-aiplatform` (Vertex, `europe-west1`)
- `google-cloud-firestore`, `google-cloud-storage`
- `shapely` + `pyyaml`
- Firebase Admin to verify ID tokens
- Secret Manager for the Gemini/Vertex credential

No always-on Vertex endpoint. Call the Gemini API; scale to zero with the Cloud Run instance.

### 4.2 Bounded context (maps to OPM processes)

| Module | OPM process | LLM? |
|---|---|---|
| `capture.py` | Capturing | Yes — Flash-Lite, audio/image → Farm Event JSON |
| `compile.py` | Compiling | **No** — YAML + geometry only |
| `consent.py` Explaining | Explaining | Yes — Flash-Lite, request → three plain lines |
| `consent.py` Minimizing / Binding / Revoking | Minimizing, Binding, Revoking | **No** |
| `deliver.py` | Delivering | No — issue token, write receipt, copy pack to partner view |
| `geometry.py` | instrument of Compiling | No — buffer vs watercourse |

If Flash-Lite extraction fails, return the draft with empty fields and let the farmer type three words. Do not escalate to Pro.

### 4.3 HTTP API

All farmer routes require a Firebase ID token. Desk routes require a partner role.

```
POST   /v1/events                 multipart audio|image + parcel_id
POST   /v1/events/{id}/confirm
GET    /v1/events/{id}

GET    /v1/packs                  packs waiting for consent
GET    /v1/packs/{id}

POST   /v1/consents               { pack_id, partner_id, purpose }
POST   /v1/consents/{id}/bind
POST   /v1/consents/{id}/refuse   # draft → refused (kept, not deleted)
POST   /v1/consents/{id}/revoke

GET    /v1/receipts
GET    /v1/me/export              # GDPR Art. 20 portable JSON
DELETE /v1/me                     # GDPR Art. 17 erase evidence + disable tokens

GET    /v1/desk/packs             partner; 410 if revoked / expired / refused
GET    /v1/desk/packs/{id}
POST   /v1/desk/requests          partner asks for a statement
```

Error shape: `{ "code": "consent_revoked", "message": "..." }`. Never leak other farmers’ packs.

### 4.4 Canonical records (Firestore)

Collections, one document type each:

```
farms/{farmId}
  country, locale, display_name

parcels/{parcelId}
  farm_id, lpis_id, crop, area_ha, geom (GeoJSON), watercourse_buffer_m

events/{eventId}
  farm_id, parcel_id, type, time, product, rate, unit, note,
  evidence_uris[], source (voice|photo|import), status (draft|confirmed)

packs/{packId}
  event_ids[], rule_id, schema, fields{}, partner_hint

consents/{consentId}
  pack_id, partner_id, purpose, fields[], until, reuse,
  state (draft|purpose-bound|refused|expired|revoked),
  locale,
  plain_talk { who, why, what, until, reuse }

receipts/{receiptId}
  consent_id, pack_hash, field_list, issued_at

tokens/{tokenId}
  consent_id, expires_at, revoked
```

Storage paths: `gs://…/evidence/{farmId}/{eventId}/audio.webm` and `…/label.jpg`. Lifecycle: 30 days.

### 4.5 Farm Event (Gemini output, then farmer-confirmed)

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

Pydantic validates units and required keys. Low confidence still shows the card; the farmer is the source of truth.

### 4.6 Rule pack (no LLM)

```yaml
id: coop_ppp_statement_v1
partner: loire-cereals-coop
purpose: seasonal_plant_protection_statement
until: end_of_calendar_year
reuse: false
fields:
  - parcel_id
  - date
  - product_name
  - rate
  - unit
  - buffer_m
exclude:
  - yield
  - revenue
checks:
  - gaec4_buffer_ok
```

`compile.py` copies only listed fields, runs `checks`, writes `packs/{id}`. A second pack (national spray register, buyer residue sheet) is another YAML file on the same event. That is Challenge 1 as a side effect, not a second product.

### 4.7 Gemini router

```
extract_event(audio, image, parcel_hint) -> FarmEventDraft           # Flash-Lite
explain_consent(request, minimised_fields, locale) -> PlainTalk      # Flash-Lite, farmer locale
```

`locale` comes from `farms.locale` (set on first-run country). Explaining writes the three-line card in that language at almost no extra token cost. System prompts and questionnaire skeletons go through context cache. Daily quota + Cloud billing cap. Log model name and token counts on every call.

---

## 5. Auth and tenancy

- Farmer: Firebase Auth → API verifies JWT → `farm_id` from custom claim.
- Partner: same project, role `partner`, `partner_id` claim. Desk queries only packs whose consent is `purpose-bound` and token live.
- Revoke: set consent `revoked`, disable token. Desk GET returns 410. Farmer receipts stay, marked revoked.
- Refuse: set consent `refused` (final). No token. Desk 410. Keep the document so the farmer can show they said no.
- Export (`GET /v1/me/export`): JSON Portable Pack of events, packs, consents, receipts (GDPR Art. 20). Farmer handles Exporting from Who has it.
- Erase (`DELETE /v1/me`): delete evidence blobs, disable all tokens, tombstone consents as erased (GDPR Art. 17). Receipts remain as a hash-only stub so the farmer still sees “who had it”. Not a fifth screen.

No public bucket listing. Evidence URLs are signed and short-lived.

---

## 6. Deploy and cost (matches the framework)

| Service | Image | Scaling |
|---|---|---|
| `origin-web` | Node, Next.js | Cloud Run `min=0` |
| `origin-api` | Python 3.12 slim | Cloud Run `min=0`, 512Mi, concurrency 20 |
| Firestore / Storage / Auth | managed | pay per use |
| Gemini | Vertex API, Flash-Lite | no dedicated endpoint |

Local: `firebase emulators` + FastAPI on `:8000` + `next dev`. Production: one GCP project, `europe-west1`.

---

## 7. 48-hour cut

Must work on Sunday:

1. Demo farm, six parcels, one watercourse
2. Voice or photo → draft event → confirm
3. One YAML pack (co-op statement) + GAEC 4 check
4. Plain-talk consent → Give → receipt
5. Desk can open the pack; Revoke greys it out

Can wait: ISOXML import, second Member State pack, real LPIS, offline sync polish, native speech-to-text besides Gemini audio.

---

## 8. Why this split holds the OPM model

- Farmer **handles** Capturing, Consenting, Revoking — those are the only TypeScript screens that call mutating endpoints.
- Gemini Flash-Lite is an **environmental instrument** of Capturing and Explaining — Python owns the client.
- Rule Pack is an **instrument** of Compiling — Python, no model.
- Partner Desk is a separate object. The farmer PWA must not import it.
