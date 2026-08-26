# Frontend and backend contract

This document describes the current implementation. Product and architecture choices are binding in [decisions.md](decisions.md).

## Runtime profiles

| Concern | Local/demo | Google Cloud |
|---|---|---|
| State | Locked JSON document | Firestore collections |
| Evidence/delivery | Local `data/` blobs | Cloud Storage objects |
| Agent execution | Inline `AgentRun` | Authenticated Cloud Tasks request |
| Model | Deterministic fallback when unconfigured | Gemini on Vertex AI through ADC |
| Identity | Explicit demo bearer principals | Firebase ID token claims |

Both profiles execute `runs.execute`; there is no separate cloud-only agent implementation.

## Frontend

`apps/web` is a strict TypeScript Next.js application with two deliberately separate surfaces:

- Farmer: **Today**, **Speak**, and **Who**. Consent is a task reached from a run, not a permanent navigation tab.
- Partner: `/desk`, an inbox and request launcher that is never linked from farmer navigation.

### Farmer flow

1. `GET /v1/today` returns the current request, draft consent, recent `AgentRun` records, and standing permissions.
2. `/capture` submits audio, image, or note evidence and renders extraction confidence plus provenance.
3. Confirming an event with an open request compiles a purpose-specific pack and advances its run. With no request, it stores the confirmed fact and sends nothing.
4. `/consent/{id}` renders recipient, purpose, expiry, and every outgoing field/value pair.
5. `/receipts` groups access by recipient and purpose, shows delivery state, and offers revoke, export, and erase actions with accurate limits.

Render serves the browser application, which talks only to the FastAPI service over HTTPS. It has no Vertex AI, Firestore, or Cloud Storage credentials. `NEXT_PUBLIC_API_URL` is fixed during the Render build, and Cloud Run permits only the deployed Render origin through CORS.

## Backend

`apps/api/origin` separates probabilistic interpretation from deterministic authority.

| Module | Role | Model authority |
|---|---|---|
| `gemini_router.py` | Structured extraction, explanations, decision narration, questionnaire and terms reading | Drafts and narration only |
| `runs.py` | Durable `AgentRun` lifecycle and step trace | Orchestration only |
| `task_dispatch.py` | Cloud Tasks enqueueing | None |
| `agent.py` | Standing-permission matching | Deterministic |
| `compile.py` / `geometry.py` | Field minimization and buffer checks | Deterministic |
| `consent.py` | Bind, refuse, expire, and revoke transitions | Deterministic |
| `partner_delivery.py` | Idempotent desk, Storage, and webhook delivery | Deterministic |
| `store.py` / `store_firestore.py` | Local and Firestore persistence | None |
| `blobs.py` | Local and Cloud Storage objects | None |
| `auth.py` | Demo principals or verified Firebase claims | None |

## AgentRun state machine

```text
created -> queued -> running -> completed
                         |  \-> waiting_for_farmer -> completed
                         \----> failed (retryable by Cloud Tasks)
```

A run records:

- request, farm, partner, trigger, status, and attempt count;
- trace ID and queue task name;
- deterministic decision and reason code;
- pack, consent, and delivery identifiers;
- model provenance and a farmer-readable step timeline;
- timestamps and a safe error summary.

No private chain-of-thought is stored or exposed.

## Core HTTP surface

```text
GET    /health
GET    /v1/today
POST   /v1/events
POST   /v1/events/{id}/confirm

GET    /v1/packs/{id}
POST   /v1/consents/{id}/bind
POST   /v1/consents/{id}/refuse
POST   /v1/consents/{id}/revoke

GET    /v1/receipts
GET    /v1/me/export
DELETE /v1/me

POST   /v1/desk/requests
GET    /v1/desk/packs
GET    /v1/desk/packs/{id}
GET    /v1/desk/agent-runs
GET    /v1/agent-runs

POST   /v1/internal/runs/{id}/execute
```

The internal worker endpoint requires `X-Origin-Worker-Token`; Cloud Tasks may additionally attach an OIDC identity token.

## Idempotency and failure behavior

- A repeated open request is reused instead of stacking cards.
- A duplicate task executes the same run identifier.
- Delivery is keyed by consent, so retries return the existing destination.
- A missing confirmed fact or uncovered request pauses rather than sends.
- A model outage selects a labeled deterministic fallback.
- A webhook failure marks delivery failed so the task can retry.
- Desk reads require a live purpose-bound consent and token.

## Configuration

All runtime configuration is under the `ORIGIN_` prefix. The complete reference is [apps/api/.env.example](../apps/api/.env.example). Browser build-time values use `NEXT_PUBLIC_` variables and are listed in `apps/web/lib/session.ts`.

Google Cloud deployment automation lives in [deploy/deploy.ps1](../deploy/deploy.ps1), while the web service definition lives in [render.yaml](../render.yaml). The judge-facing system diagram is [architecture.md](architecture.md).
