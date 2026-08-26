from __future__ import annotations

from datetime import datetime, timezone
import hmac
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from origin import (
    agent,
    capture,
    consent,
    deliver,
    partner_delivery,
    questionnaire,
    runs,
    store,
    terms,
)
from origin.auth import farmer_only, partner_only, principal, verify_worker_oidc
from origin.compile import load_rule
from origin.config import settings
from origin.models import (
    BindBody,
    ConsentCreateBody,
    DeskRequestBody,
    EventConfirmBody,
    PartnerRequest,
    Principal,
    RuleDraft,
    TermsReviewBody,
)
from origin.seed import ensure_demo

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings().seed_demo:
        ensure_demo()
    yield


app = FastAPI(title="Origin API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_parcel(row: dict, farm: dict) -> str:
    """Read migrated requests without ever falling back to the latest event."""
    return str(row.get("parcel_id") or farm.get("default_parcel_id") or "")


def _requests_for_parcel(farm_id: str, parcel_id: str, statuses: set[str]) -> list[dict]:
    farm = store.get("farms", farm_id) or {}
    rows = [
        row
        for row in store.list_where("requests", farm_id=farm_id)
        if row.get("status") in statuses and _request_parcel(row, farm) == parcel_id
    ]
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def _request_for_event(farm_id: str, event_id: str, parcel_id: str) -> dict | None:
    """Prefer the request already tied to this fact, then the oldest open ask."""
    for row in store.list_where("consents", farm_id=farm_id):
        pack = store.get("packs", str(row.get("pack_id") or "")) or {}
        request = store.get("requests", str(row.get("request_id") or ""))
        if (
            event_id in (pack.get("event_ids") or [])
            and request
            and request.get("status") in {"open", "linked"}
            and _request_parcel(request, store.get("farms", farm_id) or {}) == parcel_id
        ):
            return request
    rows = _requests_for_parcel(farm_id, parcel_id, {"open"})
    return rows[0] if rows else None


def _expire_farm_consents(farm_id: str) -> None:
    for row in store.list_where("consents", farm_id=farm_id):
        consent.expire_if_due(store.as_consent(row))


@app.get("/health")
def health() -> dict:
    cfg = settings()
    return {
        "ok": True,
        "service": "origin-api",
        "version": app.version,
        "store": cfg.store,
        "agent_dispatch": cfg.agent_dispatch,
        "shared_demo": cfg.shared_demo,
        "vertex": {
            "configured": cfg.vertex_ready,
            "model": cfg.gemini_model,
            "location": cfg.vertex_location,
        },
    }


@app.get("/v1/today")
def today(who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    agent.expire_policies_if_due()
    _expire_farm_consents(who.farm_id)
    farm = store.get("farms", who.farm_id)
    parcels = store.list_where("parcels", farm_id=who.farm_id)
    # Longest waiting first — dict order would make the visible card random.
    open_reqs = sorted(
        store.list_where("requests", farm_id=who.farm_id, status="open"),
        key=lambda r: str(r.get("created_at") or ""),
    )
    def _waiting_since(row: dict) -> str:
        pack = store.get("packs", row.get("pack_id") or "") or {}
        return str(pack.get("created_at") or "")
    drafts = sorted(
        (c for c in store.list_where("consents", farm_id=who.farm_id) if c.get("state") == "draft"),
        key=_waiting_since,
    )
    policies = store.list_where("policies", farm_id=who.farm_id, state="active")
    return {
        "farm": farm,
        "parcels": parcels,
        "open_request": open_reqs[0] if open_reqs else None,
        "open_requests": open_reqs,
        "draft_consent": drafts[0] if drafts else None,
        "draft_consents": drafts,
        "standing_policies": policies,
        "last_auto": agent.last_auto(who.farm_id),
        "last_decision": agent.last_decision(who.farm_id),
        "agent_runs": runs.recent_for_farm(who.farm_id, limit=5),
    }


@app.post("/v1/events")
async def post_event(
    # Required: a missing parcel must fail loudly, never silently land on
    # Ditch 40 — the one field where a buffer claim has legal weight.
    parcel_id: str = Form(...),
    note: str = Form(""),
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    who: Principal = Depends(principal),
) -> dict:
    farmer_only(who)
    if not parcel_id.strip():
        raise HTTPException(400, {"code": "bad_parcel", "message": "parcel_id is required"})
    audio_bytes = await audio.read() if audio is not None else None
    image_bytes = await image.read() if image is not None else None
    limit = settings().max_upload_bytes
    if any(len(payload) > limit for payload in (audio_bytes or b"", image_bytes or b"")):
        raise HTTPException(
            413,
            {
                "code": "evidence_too_large",
                "message": f"Each evidence file must be {limit} bytes or smaller",
            },
        )
    source = "voice" if audio_bytes else "photo" if image_bytes else "note"
    open_reqs = _requests_for_parcel(who.farm_id, parcel_id, {"open"})
    request_id = open_reqs[0]["id"] if open_reqs else None
    with runs.request_trace(request_id):
        event = capture.create_draft(
            farm_id=who.farm_id,
            parcel_id=parcel_id,
            note=note,
            source=source,
            audio=audio_bytes or None,
            image=image_bytes or None,
            audio_mime=audio.content_type if audio else "audio/webm",
            image_mime=image.content_type if image else "image/jpeg",
        )
    return event.model_dump(mode="json")


@app.get("/v1/events/{event_id}")
def get_event(event_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("events", event_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Event not found"})
    return row


@app.post("/v1/events/{event_id}/confirm")
def confirm_event(
    event_id: str, body: EventConfirmBody, who: Principal = Depends(principal)
) -> dict:
    farmer_only(who)
    row = store.get("events", event_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Event not found"})
    patch = body.model_dump(exclude_unset=True)
    # Resolve the parcel before anything is written. A failed confirm must not
    # leave a confirmed event behind — the agent would wedge into need_capture
    # forever with nothing on Today explaining why.
    target_parcel = patch.get("parcel_id") or row["parcel_id"]
    if row.get("status") == "confirmed" and target_parcel != row.get("parcel_id"):
        raise HTTPException(
            409,
            {"code": "already_confirmed", "message": "A confirmed event cannot move fields"},
        )
    parcel_row = store.get("parcels", target_parcel)
    if not parcel_row or parcel_row.get("farm_id") != who.farm_id:
        raise HTTPException(
            400,
            {"code": "bad_parcel", "message": f"Unknown parcel {target_parcel}"},
        )
    # A lost response or double tap resumes the same confirmed fact. It never
    # recompiles merely because the HTTP call was repeated.
    event = (
        store.as_event(row)
        if row.get("status") == "confirmed"
        else capture.confirm(store.as_event(row), **patch)
    )
    farm = store.get("farms", who.farm_id) or {}
    request = _request_for_event(who.farm_id, event.id, event.parcel_id)
    if not request:
        # Capturing a fact is not permission to publish it. Keep the confirmed
        # event ready; a future partner request may use standing permission.
        return {
            "event": event.model_dump(mode="json"),
            "pack": None,
            "consent": None,
            "auto": False,
            "saved_only": True,
            "agent": {
                "decision": "stored_for_future_request",
                "reason_code": "no_open_request",
                "note": "Fact confirmed. No partner request is open, so nothing was sent.",
            },
        }
    req_id = request["id"]
    with runs.request_trace(req_id):
        result = agent.tick_request(store.as_request(request), event_id=event.id)
        runs.complete_from_result(req_id, result)
    consent_obj = result.get("consent")
    pack_row = (
        store.get("packs", consent_obj.pack_id)
        if consent_obj is not None and getattr(consent_obj, "pack_id", None)
        else None
    )
    payload = {
        "event": event.model_dump(mode="json"),
        "pack": pack_row,
        "consent": consent_obj.model_dump(mode="json") if consent_obj else None,
        "auto": result.get("mode") == "auto",
        "agent": {
            k: result.get(k)
            for k in ("decision", "reason", "reason_code", "extra_fields", "note", "policy_id")
        },
    }
    if result.get("mode") == "auto":
        receipt_obj = result.get("receipt")
        if receipt_obj is not None:
            payload["receipt"] = receipt_obj.model_dump(mode="json")
        elif consent_obj is not None:
            receipts = store.list_where("receipts", consent_id=consent_obj.id)
            payload["receipt"] = receipts[0] if receipts else None
    return payload


@app.get("/v1/packs")
def list_packs(who: Principal = Depends(principal)) -> list[dict]:
    farmer_only(who)
    return store.list_where("packs", farm_id=who.farm_id)


@app.get("/v1/packs/{pack_id}")
def get_pack(pack_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("packs", pack_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Pack not found"})
    return row


@app.post("/v1/consents")
def create_consent(body: ConsentCreateBody, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    pack_row = store.get("packs", body.pack_id)
    if not pack_row or pack_row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Pack not found"})
    pack = store.as_pack(pack_row)
    # The pack decides partner and purpose. If the caller stated either, it must
    # agree: a consent card that says something other than what the client
    # showed the farmer is exactly the confusion Origin exists to remove.
    for name, claimed, actual in (
        ("partner_id", body.partner_id, pack.partner_id),
        ("purpose", body.purpose, pack.purpose),
    ):
        if claimed is not None and claimed != actual:
            raise HTTPException(
                409,
                {
                    "code": "pack_mismatch",
                    "message": f"Pack {pack.id} has {name} {actual!r}, not {claimed!r}",
                },
            )
    farm = store.get("farms", who.farm_id) or {}
    draft = consent.open_draft(pack, locale=farm.get("locale", "en"))
    return draft.model_dump(mode="json")


@app.get("/v1/consents/{consent_id}")
def get_consent(consent_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    record = store.as_consent(row)
    pack = store.get("packs", record.pack_id) or {}
    return {
        **record.model_dump(mode="json"),
        "pack_fields": pack.get("fields") or {},
        "checks": pack.get("checks") or {},
    }


@app.post("/v1/consents/{consent_id}/bind")
def bind_consent(
    consent_id: str, body: BindBody | None = None, who: Principal = Depends(principal)
) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    record = store.as_consent(row)
    if record.state == "draft":
        record.standing_requested = bool(body and body.standing)
        store.put("consents", record.id, record.model_dump(mode="json"))
    bound = consent.bind(record)
    token, receipt = deliver.issue(bound)
    pack = store.get("packs", bound.pack_id)
    passport = deliver.lot_passport(bound, store.as_pack(pack))
    policy = agent.activate_standing(bound) if bound.standing_requested else None
    delivery = runs.complete_manual_consent(bound)
    return {
        "consent": bound.model_dump(mode="json"),
        "token": token.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "passport": passport,
        "policy": policy.model_dump(mode="json") if policy else None,
        "delivery": delivery,
    }


@app.post("/v1/consents/{consent_id}/refuse")
def refuse_consent(consent_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    refused, receipt = consent.refuse(store.as_consent(row))
    runs.complete_refusal(refused)
    return {"consent": refused.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json")}


@app.post("/v1/consents/{consent_id}/revoke")
def revoke_consent(consent_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    record = store.as_consent(row)
    pack_row = store.get("packs", record.pack_id)
    revoked = consent.revoke(record)
    agent.revoke_standing_for(revoked)
    notice = partner_delivery.send_notice(
        "access_revoked",
        revoked,
        store.as_pack(pack_row) if pack_row else None,
    )
    return {**revoked.model_dump(mode="json"), "recipient_notice": notice}


@app.get("/v1/receipts")
def list_receipts(who: Principal = Depends(principal)) -> list[dict]:
    farmer_only(who)
    agent.expire_policies_if_due()
    _expire_farm_consents(who.farm_id)
    rows = store.list_where("receipts", farm_id=who.farm_id)
    rows.sort(key=lambda r: r.get("issued_at", ""), reverse=True)
    return [
        {**row, "delivery": partner_delivery.for_consent(str(row.get("consent_id") or ""))}
        for row in rows
    ]


@app.post("/v1/terms/review")
def review_terms(body: TermsReviewBody, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    farm = store.get("farms", who.farm_id) or {}
    record = terms.review(
        farm_id=who.farm_id,
        text=body.text,
        partner_hint=(body.partner_name or "").strip(),
        locale=str(farm.get("locale") or who.locale or "en"),
    )
    return record.model_dump(mode="json")


@app.get("/v1/me/export")
def export_me(who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    farm = store.get("farms", who.farm_id) or {}
    return {
        "kind": "portable_pack",
        "article": "US farm-data originator portable copy",
        "basis": ["Ag Data Transparent principles", "farmer as data originator"],
        "farm": farm,
        "parcels": store.list_where("parcels", farm_id=who.farm_id),
        "events": store.list_where("events", farm_id=who.farm_id),
        "packs": store.list_where("packs", farm_id=who.farm_id),
        "consents": store.list_where("consents", farm_id=who.farm_id),
        "policies": store.list_where("policies", farm_id=who.farm_id),
        "receipts": store.list_where("receipts", farm_id=who.farm_id),
    }


@app.delete("/v1/me")
def erase_me(who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    if settings().shared_demo:
        raise HTTPException(
            403,
            {
                "code": "shared_demo_protected",
                "message": "Erasure is disabled in the public shared demo tenant",
            },
        )
    # Notify recipients before scrubbing the packs that identify what was sent.
    for row in store.list_where("consents", farm_id=who.farm_id):
        if (
            row.get("state") in {"purpose-bound", "revoked", "expired"}
            and partner_delivery.for_consent(row["id"])
        ):
            record = store.as_consent(row)
            pack_row = store.get("packs", record.pack_id)
            partner_delivery.send_notice(
                "deletion_requested",
                record,
                store.as_pack(pack_row) if pack_row else None,
            )
    capture.wipe_evidence(who.farm_id)
    delivery_count = partner_delivery.erase_origin_copy(who.farm_id)
    run_rows = store.list_where("agent_runs", farm_id=who.farm_id)
    trace_ids = {str(row.get("trace_id") or "") for row in run_rows}
    for ev in store.list_where("events", farm_id=who.farm_id):
        provenance = ev.get("provenance") if isinstance(ev.get("provenance"), dict) else {}
        trace_ids.add(str(provenance.get("trace_id") or ""))
        store.delete("events", ev["id"])
    for c in store.list_where("consents", farm_id=who.farm_id):
        c["state"] = "erased"
        c["plain_talk"] = None
        c["fields"] = []
        c["request_id"] = None
        c["standing_requested"] = False
        store.put("consents", c["id"], c)
        consent._disable_tokens(c["id"])
        consent._grey_receipts(c["id"])
        for token in store.list_where("tokens", consent_id=c["id"]):
            store.delete("tokens", token["id"])
    # Packs hold copied field values (product, rate). The events were scrubbed
    # above; leaving the same values in packs would make erase cosmetic.
    for p in store.list_where("packs", farm_id=who.farm_id):
        p["event_ids"] = []
        p["fields"] = {}
        p["checks"] = {}
        store.put("packs", p["id"], p)
    # Receipts become hash-only stubs: the farmer still sees who had it and can
    # verify the pack_hash, but what was in the pack is gone (docs §5).
    for r in store.list_where("receipts", farm_id=who.farm_id):
        r["field_list"] = []
        store.put("receipts", r["id"], r)
    for policy in store.list_where("policies", farm_id=who.farm_id):
        policy["state"] = "revoked"
        policy["allowed_fields"] = []
        store.put("policies", policy["id"], policy)
    # Model traces and uploaded source text are operational data, not receipt
    # proofs. Remove them instead of leaving farmer notes in secondary tables.
    for collection in ("agent_log", "rule_drafts", "terms_reviews"):
        for row in store.list_where(collection, farm_id=who.farm_id):
            store.delete(collection, row["id"])
    for row in run_rows:
        store.delete("agent_runs", row["id"])
    for row in store.list_where("llm_calls"):
        if str(row.get("trace_id") or "") in trace_ids:
            store.delete("llm_calls", row["id"])
    for row in store.list_where("requests", farm_id=who.farm_id):
        store.delete("requests", row["id"])
    return {
        "ok": True,
        "code": "origin_copy_erased",
        "delivery_stubs": delivery_count,
        "message": "Origin's activity facts, evidence, and managed delivery copies were erased; recipient notices were sent first.",
    }


@app.post("/v1/desk/requests")
def desk_request(body: DeskRequestBody, who: Principal = Depends(principal)) -> dict:
    partner_only(who)
    partner_id = who.partner_id or ""
    farm = store.get("farms", body.farm_id)
    if not farm:
        # An unknown farm must not collect junk requests (and agent_log noise);
        # the partner gets a clean 404 instead.
        raise HTTPException(404, {"code": "not_found", "message": "Farm not found"})
    rule_id = agent.default_rule_for(partner_id, farm)
    rule = load_rule(rule_id)
    parcel_id = str(body.parcel_id or farm.get("default_parcel_id") or "")
    parcel = store.get("parcels", parcel_id)
    if not parcel_id or not parcel or parcel.get("farm_id") != body.farm_id:
        raise HTTPException(
            422,
            {"code": "bad_parcel", "message": "A valid farm parcel is required"},
        )
    purpose = body.purpose or rule["purpose"]
    field_list = list(rule["fields"])
    candidates = [
        row
        for row in store.list_where("requests", farm_id=body.farm_id, partner_id=partner_id)
        if row.get("status") in {"open", "linked"}
        and _request_parcel(row, farm) == parcel_id
        and row.get("purpose") == purpose
        and (row.get("status") == "open" or row.get("field_list") == field_list)
    ]
    candidates.sort(key=lambda row: str(row.get("created_at") or ""))
    reused = bool(candidates)
    if reused:
        req = store.as_request(candidates[0])
        if req.status == "open" and (req.rule_id != rule_id or req.field_list != field_list):
            req.rule_id = rule_id
            req.field_list = field_list
            store.put("requests", req.id, req.model_dump(mode="json"))
    else:
        req = PartnerRequest(
            id=f"req-{uuid4().hex[:10]}",
            farm_id=body.farm_id,
            partner_id=partner_id,
            partner_name=agent.partner_display(partner_id),
            parcel_id=parcel_id,
            purpose=purpose,
            field_list=field_list,
            rule_id=rule_id,
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        store.put("requests", req.id, req.model_dump(mode="json"))
    run = runs.latest_for_request(req.id)
    if run is None:
        run = runs.create_for_request(req)
    fresh = store.get("requests", req.id) or req.model_dump(mode="json")
    return {
        **fresh,
        "reused": reused,
        "run": run.model_dump(mode="json"),
        "agent": {
            "decision": run.decision,
            "reason_code": run.reason_code,
            "consent_id": run.consent_id,
            "run_id": run.id,
            "trace_id": run.trace_id,
            "status": run.status,
        },
    }


@app.post("/v1/internal/runs/{run_id}/execute")
def execute_run(
    run_id: str,
    x_origin_worker_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    expected = settings().internal_token
    if not expected or not x_origin_worker_token or not hmac.compare_digest(
        expected, x_origin_worker_token
    ):
        raise HTTPException(403, {"code": "forbidden", "message": "Worker token required"})
    verify_worker_oidc(authorization)
    return runs.execute(run_id).model_dump(mode="json")


@app.get("/v1/agent-runs")
def farmer_agent_runs(who: Principal = Depends(principal)) -> list[dict]:
    farmer_only(who)
    return runs.recent_for_farm(who.farm_id, limit=20)


@app.get("/v1/desk/agent-runs")
def partner_agent_runs(who: Principal = Depends(principal)) -> list[dict]:
    partner_only(who)
    return runs.recent_for_partner(who.partner_id or "", limit=20)


def _rule_draft_out(draft: RuleDraft | dict) -> dict:
    """Wire the stored field names to the API names the farmer UI will read.

    The store keeps `dropped_refused` / `dropped_unknown` (what the sanitiser
    actually did). The contract also exposes `refused_fields` / `unknown_fields`
    so the D6 assertion — yield and revenue do not survive — is visible without
    knowing the internal names.
    """
    data = draft.model_dump(mode="json") if isinstance(draft, RuleDraft) else dict(draft)
    data["refused_fields"] = list(data.get("dropped_refused") or [])
    data["unknown_fields"] = list(data.get("dropped_unknown") or [])
    # The farmer should read a date, not the rule-pack keyword.
    pack = data.get("pack") or {}
    if isinstance(pack, dict) and pack.get("until"):
        data["until_date"] = questionnaire.preview_until(pack)
    return data


@app.post("/v1/desk/questionnaires")
async def desk_questionnaire(
    farm_id: str = Form(...),
    text: str = Form(""),
    document: UploadFile | None = File(default=None),
    who: Principal = Depends(principal),
) -> dict:
    partner_only(who)
    farm = store.get("farms", farm_id)
    if not farm:
        raise HTTPException(404, {"code": "not_found", "message": "Farm not found"})
    if str(farm.get("country") or "").upper() != "US":
        raise HTTPException(
            422,
            {"code": "unsupported_market", "message": "This hackathon build supports US farms only"},
        )
    market = "US"
    doc_bytes = await document.read() if document is not None else None
    if doc_bytes and len(doc_bytes) > settings().max_upload_bytes:
        raise HTTPException(
            413,
            {
                "code": "document_too_large",
                "message": f"The questionnaire must be {settings().max_upload_bytes} bytes or smaller",
            },
        )
    mime = document.content_type if document is not None else "application/pdf"
    draft = questionnaire.propose(
        farm_id=farm_id,
        partner_id=who.partner_id or "",
        market=market,
        text=text,
        document=doc_bytes or None,
        document_mime=mime or "application/pdf",
        partner_hint=agent.partner_display(who.partner_id or ""),
    )
    return _rule_draft_out(draft)


@app.get("/v1/rule-drafts")
def list_rule_drafts(who: Principal = Depends(principal)) -> list[dict]:
    farmer_only(who)
    return [_rule_draft_out(row) for row in questionnaire.list_for(who.farm_id)]


@app.post("/v1/rule-drafts/{draft_id}/approve")
def approve_rule_draft(draft_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    return _rule_draft_out(questionnaire.decide(draft_id, who.farm_id, approve=True))


@app.post("/v1/rule-drafts/{draft_id}/reject")
def reject_rule_draft(draft_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    return _rule_draft_out(questionnaire.decide(draft_id, who.farm_id, approve=False))


@app.get("/v1/desk/packs")
def desk_packs(who: Principal = Depends(principal)) -> list[dict]:
    partner_only(who)
    rows = deliver.desk_inbox(who.partner_id or "")
    for row in rows:
        consent_id = str((row.get("consent") or {}).get("id") or "")
        row["delivery"] = partner_delivery.for_consent(consent_id)
    return rows


@app.get("/v1/desk/packs/{pack_id}")
def desk_pack(pack_id: str, who: Principal = Depends(principal)) -> dict:
    partner_only(who)
    pack = store.get("packs", pack_id)
    if not pack:
        raise HTTPException(404, {"code": "not_found", "message": "Pack not found"})
    matches = [c for c in store.list_where("consents", pack_id=pack_id) if c.get("partner_id") == who.partner_id]
    if not matches:
        raise HTTPException(404, {"code": "not_found", "message": "No consent"})
    c = store.as_consent(matches[0])
    deliver.desk_visible(c)
    return {
        "consent": c.model_dump(mode="json"),
        "pack": pack,
        "passport": deliver.lot_passport(c, store.as_pack(pack)),
        "delivery": partner_delivery.for_consent(c.id),
    }
