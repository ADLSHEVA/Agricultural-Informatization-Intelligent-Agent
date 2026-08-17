# Origin

Farmer-controlled share compiler for the **EU Agri-Hackathon 2026**, Challenge #3: *Flowing data, empowered collaboration*.

**You originated it. You decide who uses it.**

Origin is not a farm-management system and not a data marketplace. It is the farmer-side **compiler + consent wallet + receipt book**: capture a field fact once, pack only the fields a partner asked for, bind a purpose and an expiry, and revoke. Farmers keep control; partners stop sending the same questionnaire again.

Chinese project log (latest status): [`docs/进展.md`](docs/进展.md).

## Why this exists

EU farmers re-enter the same spray, harvest, or practice facts for co-ops, mills, retailers, certifiers, and paying agencies. US growers say the same about elevators, carbon programmes, and OEM clouds. Origin applies the EU **once-only** idea and the Code of Conduct **data originator** rule: one capture, many share packs, farmer-held consent.

Challenge 1 (less form time) and Challenge 2 (field data) are inputs and side effects, not a second product.

## Demo (Sunday loop)

1. Open [http://localhost:3000](http://localhost:3000). Today shows *Loire Cereals Co-op wants a statement*.
2. Speak, snap a can, or send the typed note on parcel 3 (5 m buffer).
3. Confirm the draft card (you are the source of truth).
4. Give or refuse the three-line consent card.
5. Partner desk at `/desk` can open the pack; **Revoke** greys it out.
6. **Who has it**: export (GDPR Art. 20) or erase (Art. 17).

Farmer navigation is three tabs only: **Today · Speak · Who**. Desk is never linked from those tabs.

## Stack

| Piece | Tech | Role |
|---|---|---|
| `apps/web` (`origin-web`) | TypeScript, Next.js 15 PWA | Four farmer screens + Partner Desk |
| `apps/api` (`origin-api`) | Python 3.12+, FastAPI | Capture, YAML compile, consent, deliver, GAEC 4, Gemini |
| Gemini Flash-Lite | Vertex / AI Studio, `europe-west1` in production | Extract event + plain-talk consent **in the farmer locale** |
| Rule packs | YAML + Shapely | Deterministic compile. **No LLM on GAEC or “should we share?”** |

Two Cloud Run services, `min-instances=0`. The browser never holds a Gemini key. Locally the API uses a JSON store under `apps/api/data/` (gitignored). Demo tokens: `demo-farmer`, `demo-partner`.

Architecture diagrams (English, OPM / ISO 19450, Graphviz):

| Source | Rendered |
|---|---|
| [`opm/framework.txt`](opm/framework.txt) | [`opm/rendered/framework.png`](opm/rendered/framework.png) |
| [`opm/stack.txt`](opm/stack.txt) | [`opm/rendered/stack.png`](opm/rendered/stack.png) |
| [`opm/states.txt`](opm/states.txt) | [`opm/rendered/states.png`](opm/rendered/states.png) |
| [`opm/sd1_1.txt`](opm/sd1_1.txt) | [`opm/rendered/sd1_1.png`](opm/rendered/sd1_1.png) |

Design spec: [`docs/frontend-backend.md`](docs/frontend-backend.md).

## Consent states

```
draft ──Binding──► purpose-bound ──Expiring──► expired
  │                      │
  └──Refusing──► refused └──Revoking──► revoked
```

`refused` is a **final** state (not a deleted draft). Desk returns **410** for refused / expired / revoked. Erase tombstones consents and leaves hash-only receipts.

## Run locally

**API** (PowerShell):

```powershell
cd apps\api
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn origin.main:app --reload --port 8000
```

Optional: `$env:GEMINI_API_KEY = "..."` for real Flash-Lite extract/explain. Without a key, a heuristic extractor and an English/French template still complete the loop.

**Web:**

```powershell
cd apps\web
npm install
npm run dev
```

| URL | Who |
|---|---|
| http://localhost:3000 | Farmer |
| http://localhost:3000/desk | Partner (not in farmer nav) |
| http://127.0.0.1:8000/docs | OpenAPI |

## Tests

```powershell
cd apps\api
$env:PYTHONPATH = "."
py -3 -m pytest tests -q
```

Includes GAEC 4 compile checks and the full Sunday loop (capture → confirm → bind → desk visible → revoke → grey).

```powershell
cd apps\web
npx tsc --noEmit
```

Re-render OPM figures after editing a `.txt`:

```powershell
dot -Tpng -Gdpi=150 -o opm\rendered\framework.png opm\framework.txt
```

## Status (16 August 2026)

**Done:** product and OPM architecture; expert-review gaps (partner request, expiry, adapter phase 2, GCP wiring, cost labels); refuse / locale / GDPR export-erase; runnable vertical slice.

**Not yet:** Firebase Auth, Firestore/GCS in production, Cloud Run deploy, ISOXML import, second Member State rule pack, real LPIS, polished offline queue.

Licence intended for the hackathon: **EUPL-1.2** (open-source mention). Team keeps IP of what is built during 16–18 October 2026.
