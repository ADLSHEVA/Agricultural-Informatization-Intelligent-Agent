# Origin

Farmer-controlled share compiler for the **EU Agri-Hackathon 2026**, Challenge #3: *Flowing data, empowered collaboration*.

**You originated it. You decide who uses it.**

Origin is not a farm-management system and not a data marketplace. It is the farmer-side **compiler + consent wallet + receipt book**: capture a field fact once, pack only the fields a partner asked for, bind a purpose and an expiry, and revoke. Farmers keep control; partners stop sending the same questionnaire again.

Binding technical decisions: [`docs/decisions.md`](docs/decisions.md). Design spec: [`docs/frontend-backend.md`](docs/frontend-backend.md).

## Why this exists

EU farmers re-enter the same spray, harvest, or practice facts for co-ops, mills, retailers, certifiers, and paying agencies. US growers say the same about elevators, carbon programmes, and OEM clouds. Origin applies the EU **once-only** idea and the Code of Conduct **data originator** rule: one capture, many share packs, farmer-held consent.

Challenge 1 (less form time) and Challenge 2 (field data) are inputs and side effects, not a second product.

## Two markets, one core

The compile step is a rule pack, so the same event serves either side of the Atlantic. Nothing in `origin/` is jurisdiction-specific.

| | US | EU |
|---|---|---|
| Demo partner | Heartland Grain LLC (elevator) | Loire Cereals Co-op |
| Rule pack | `elevator_spray_statement_v1` | `coop_ppp_statement_v1` |
| Buffer check field | `buffer_ok` (~16 ft filter strip) | `gaec4_buffer_ok` (GAEC 4, 5 m) |
| Framing | farm-data originator, Ag Data Transparent | GDPR Art. 20 / 17, EU Code of Conduct |
| Export label | "US farm-data originator portable copy" | "GDPR Art. 20" |

Which one a farm gets follows `farms.country` and `farms.locale`. The seeded demo farm is **US**; the EU pack is proven by `tests/test_compile.py`, which compiles one event into both.

## Demo (Sunday loop)

Seeded demo farm: **Riverside Farms**, Story County IA, 212 ac, six fields. Field 3 (*Ditch 40*) touches a drainage ditch and needs a 5.0 m ≈ 16 ft unsprayed filter strip.

1. Open [http://localhost:3000](http://localhost:3000). Today shows *Heartland Grain LLC wants a spray statement*.
2. Speak, snap a can, or send the typed note on field 3 (16 ft filter strip).
3. Confirm the draft card (you are the source of truth).
4. Give or refuse the five-line consent card. Ticking **"do this automatically next time"** also arms a standing policy (off by default).
5. Partner desk at `/desk` can open the pack; **Revoke** greys it out.
6. **Who has it**: export (GDPR Art. 20) or erase (Art. 17).
7. Back at `/desk`, **Ask the farm again**: the agent auto-delivers under the standing policy, and Today reports *Origin already sent it*.

Farmer navigation is three tabs only: **Today · Speak · Who**. Consent is reached by push, never by tab. Desk is never linked from those tabs.

## Stack

| Piece | Tech | Role |
|---|---|---|
| `apps/web` (`origin-web`) | TypeScript, Next.js 15, React 19, hand-written CSS | Four farmer screens + Partner Desk |
| `apps/api` (`origin-api`) | Python 3.12+, FastAPI, Pydantic v2 | Capture, YAML compile, consent, deliver, agent, buffer check, Gemini |
| Gemini on **Vertex AI** | `gemini-3.7-flash`, `vertexai=True`, **ADC only — no API keys** | Read voice/photo into a draft event, phrase the consent card in the farmer's locale, narrate agent decisions |
| Rule packs | YAML + Shapely | Deterministic compile. **No LLM on the buffer check or on "should we share?"** |

Two Cloud Run services, `min-instances=0`. The browser never reaches Vertex — the credential lives only on `origin-api`, and it is an Application Default Credential, never a key (organisation policy forbids API keys). Locally the API uses a JSON store under `apps/api/data/` (gitignored). Demo tokens: `demo-farmer`, `demo-partner`.

With no project configured, every model call takes a deterministic fallback and the whole demo loop still completes. See [`docs/decisions.md`](docs/decisions.md) for the binding decisions.

Architecture diagrams (English, OPM / ISO 19450, Graphviz):

| Source | Rendered | Shows |
|---|---|---|
| [`opm/framework.txt`](opm/framework.txt) | [`opm/rendered/framework.png`](opm/rendered/framework.png) | one-page overall framework |
| [`opm/sd.txt`](opm/sd.txt) | [`opm/rendered/sd.png`](opm/rendered/sd.png) | SD — Sharing under farmer control |
| [`opm/sd1.txt`](opm/sd1.txt) | [`opm/rendered/sd1.png`](opm/rendered/sd1.png) | SD1 — Sharing in-zoomed |
| [`opm/sd1_1.txt`](opm/sd1_1.txt) | [`opm/rendered/sd1_1.png`](opm/rendered/sd1_1.png) | SD1.1 — Consenting in-zoomed |
| [`opm/sd1_2.txt`](opm/sd1_2.txt) | [`opm/rendered/sd1_2.png`](opm/rendered/sd1_2.png) | SD1.2 — Deciding in-zoomed (the agent; narration attaches after the decision) |
| [`opm/states.txt`](opm/states.txt) | [`opm/rendered/states.png`](opm/rendered/states.png) | consent and rule-draft lifecycles |
| [`opm/stack.txt`](opm/stack.txt) | [`opm/rendered/stack.png`](opm/rendered/stack.png) | language split, Gemini only on the API |
| [`opm/struct.txt`](opm/struct.txt) | [`opm/rendered/struct.png`](opm/rendered/struct.png) | aggregation with language labels |
| [`opm/legend.txt`](opm/legend.txt) | [`opm/rendered/legend.png`](opm/rendered/legend.png) | OPM notation key |

Design spec: [`docs/frontend-backend.md`](docs/frontend-backend.md).

## Consent states

```
draft ──Binding──► purpose-bound ──Expiring──► expired
  │                      │
  └──Refusing──► refused └──Revoking──► revoked
```

`refused` is a **final** state (not a deleted draft). Desk returns **410** for refused / expired / revoked. Erase tombstones consents as `erased` and leaves hash-only receipts.

## The Origin agent

`origin/agent.py` closes the loop when a partner asks again. It is a policy matcher, not a chatbot — **Gemini never decides whether to share.**

- **Standing policy** (`StandingPolicy`): the box the farmer drew when they ticked *do this automatically next time*. Partner + purpose + allowed fields + expiry.
- **Three decisions**, all written to `agent_log`: `auto_deliver` (a standing policy strictly covers the pack's fields), `ask_farmer` (new partner, new purpose, or an extra field), `need_capture` (nothing confirmed to compile).
- Auto-delivery is *inside the box only*: `set(pack fields) ⊆ set(policy.allowed_fields)`, same purpose, not past `until`. One extra field drops it back to `ask_farmer`.
- Today surfaces the last auto-delivery so the farmer always learns what went out, and can revoke it from **Who**.

## Run locally

**API** (PowerShell):

```powershell
cd apps\api
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn origin.main:app --reload --port 8000
```

Optional, for real Gemini calls on Vertex AI (there is **no API key** — organisation policy forbids them):

```powershell
gcloud auth application-default login
$env:ORIGIN_GCP_PROJECT = "project-5e761e8c-65aa-4033-8cb"
```

`ORIGIN_VERTEX_LOCATION` defaults to `global`; set `europe-west1` for an EU data-residency demo. `ORIGIN_GEMINI_MODEL` defaults to `gemini-3.7-flash`. See [`apps/api/.env.example`](apps/api/.env.example). Without a project, a heuristic extractor and an English/French template still complete the loop.

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

**34 passed** as of 22 August 2026, with **no credentials configured**. Coverage includes buffer compile checks (one event into both the US and the EU pack), the Sunday loop (capture → confirm → bind + standing → desk → auto-deliver → revoke, desk showing one current file not stacked copies), rule-pack market keys, the offline Vertex fallback, block A (`test_questionnaire.py`: yield and revenue cannot survive, including Gemini coinages), and block B (`test_terms.py`: a resale clause against a standing policy raises flags and lists `over_ask`). Keep the suite green offline — that is the demo-safety guarantee.

```powershell
cd apps\web
npx tsc --noEmit
```

Re-render the OPM figures after editing any `.txt` (Graphviz here is `C:\Users\Administrator\Graphviz\bin\dot.exe`):

```powershell
Set-Location opm
foreach ($f in @("sd","sd1","sd1_1","sd1_2","framework","stack","states","struct","legend")) {
  dot -Tpng -Gdpi=150 -o "rendered\$f.png" "$f.txt"
  dot -Tsvg -o "rendered\$f.svg" "$f.txt"
}
```

## Status (22 August 2026)

**Done:** product and OPM architecture; expert-review gaps (partner request, expiry, adapter phase 2, GCP wiring, cost labels); refuse / locale / GDPR export-erase; US and EU rule packs off one event; Origin agent with standing policies and auto-delivery; agent decision narration and over-ask diff (block C, wired end to end); **Gemini on Vertex AI through ADC, with no API key anywhere**; OPM sources cover the agent layer, including the new SD1.2, and all nine render clean.

**Verified 22 August 2026:** `pytest` **34 passed** with *no credentials configured at all*; `tsc --noEmit` exit 0. Live Vertex (`gemini-3.7-flash`, ADC, `location=global`) ran the farmer loop: questionnaire → approve → Speak → Give → Who → Desk current file. Yield and revenue did not survive sanitise. Desk shows one live file per farm and purpose (`deliver.desk_inbox`); Who groups receipts by partner.

**Block A:** partner questionnaire → sanitised draft → farmer approve/reject. Desk uploads the form; Today shows the draft. `_canonical_name` folds Gemini coinages onto the vocabulary. Covered by `tests/test_questionnaire.py`.

**Block B:** farmer pastes a partner clause on `/terms` (reached from Who, not a fourth tab). Resale flags come from the reading; `over_ask[]` is a set difference against live standing policies, in code. Covered by `tests/test_terms.py`.

**Not yet:** Firestore/GCS/Firebase adapters plus Cloud Run manifests (block F), live Cloud Run deploy, ISOXML import, real LPIS, polished offline queue.

Licence: **Apache-2.0** (see [`LICENSE`](LICENSE)). Team keeps IP of what is built during 16–18 October 2026.
