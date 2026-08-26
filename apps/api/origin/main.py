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
from origin.auth import farmer_only, partner_only, principal
from origin.compile import compile_event, load_rule
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


@app.get("/health")
def health() -> dict:
    cfg = settings()
    return {
        "ok": True,
        "service": "origin-api",
        "version": app.version,
        "store": cfg.store,
        "agent_dispatch": cfg.agent_dispatch,
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
        "draft_consent": drafts[0] if drafts else None,
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
    open_reqs = sorted(
        store.list_where("requests", farm_id=who.farm_id, status="open"),
        key=lambda row: str(row.get("created_at") or ""),
    )
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
    if row.get("status") == "confirmed":
        # One event, one outcome. A retry (double tap, lost response) must not
        # compile a second pack and open a second consent for the same fact.
        raise HTTPException(
            409,
            {"code": "already_confirmed", "message": "Event was already confirmed"},
        )
    patch = body.model_dump(exclude_unset=True)
    # Resolve the parcel before anything is written. A failed confirm must not
    # leave a confirmed event behind — the agent would wedge into need_capture
    # forever with nothing on Today explaining why.
    target_parcel = patch.get("parcel_id") or row["parcel_id"]
    parcel_row = store.get("parcels", target_parcel)
    if not parcel_row:
        raise HTTPException(
            400,
            {"code": "bad_parcel", "message": f"Unknown parcel {target_parcel}"},
        )
    # exclude_unset: only the fields the farmer actually edited. Sending the
    # whole model would arrive as a wall of nulls and blank the untouched ones.
    event = capture.confirm(store.as_event(row), **patch)
    farm = store.get("farms", who.farm_id) or {}
    open_reqs = sorted(
        store.list_where("requests", farm_id=who.farm_id, status="open"),
        key=lambda request: str(request.get("created_at") or ""),
    )
    if not open_reqs:
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
    req_id = open_reqs[0]["id"] if open_reqs else None
    # No open request means no partner asked, so the pack follows the farm's
    # market — a US default here would hand an EU farm the elevator pack.
    rule_id = (open_reqs[0].get("rule_id") if open_reqs else None) or agent.default_rule_for_farm(farm)
    request = open_reqs[0] if open_reqs else None
    pack = compile_event(
        event,
        store.as_parcel(parcel_row),
        rule_id=rule_id,
        requested_fields=request.get("field_list") if request else None,
        purpose=request.get("purpose") if request else None,
    )
    if req_id:
        req = open_reqs[0]
        req["status"] = "linked"
        store.put("requests", req_id, req)
    with runs.request_trace(req_id):
        result = agent.fulfill_pack(
            pack=pack,
            request_id=req_id,
            locale=farm.get("locale", "en"),
        )
        runs.complete_from_result(req_id, result)
    payload = {
        "event": event.model_dump(mode="json"),
        "pack": pack.model_dump(mode="json"),
        "consent": result["consent"].model_dump(mode="json"),
        "auto": result.get("mode") == "auto",
        "agent": {
            k: result.get(k)
            for k in ("decision", "reason", "reason_code", "extra_fields", "note", "policy_id")
        },
    }
    if result.get("mode") == "auto":
        payload["receipt"] = result["receipt"].model_dump(mode="json")
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
    bound = consent.bind(store.as_consent(row))
    token, receipt = deliver.issue(bound)
    pack = store.get("packs", bound.pack_id)
    passport = deliver.lot_passport(bound, store.as_pack(pack))
    policy = agent.activate_standing(bound) if body and body.standing else None
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
    us = farm.get("country") == "US"
    return {
        "kind": "portable_pack",
        "article": "US farm-data originator portable copy" if us else "GDPR Art. 20",
        "basis": (
            ["Ag Data Transparent principles", "farmer as data originator"]
            if us
            else ["GDPR Art. 20", "EU Code of Conduct data originator"]
        ),
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
    # Notify recipients before scrubbing the packs that identify what was sent.
    for row in store.list_where("consents", farm_id=who.farm_id):
        if row.get("state") == "purpose-bound":
            record = store.as_consent(row)
            pack_row = store.get("packs", record.pack_id)
            partner_delivery.send_notice(
                "deletion_requested",
                record,
                store.as_pack(pack_row) if pack_row else None,
            )
    capture.wipe_evidence(who.farm_id)
    for ev in store.list_where("events", farm_id=who.farm_id):
        ev["note"] = ""
        ev["product_name"] = ""
        ev["rate"] = None
        ev["evidence_uris"] = []
        store.put("events", ev["id"], ev)
    for c in store.list_where("consents", farm_id=who.farm_id):
        c["state"] = "erased"
        c["plain_talk"] = None
        store.put("consents", c["id"], c)
        consent._disable_tokens(c["id"])
        consent._grey_receipts(c["id"])
    # Packs hold copied field values (product, rate). The events were scrubbed
    # above; leaving the same values in packs would make erase cosmetic.
    for p in store.list_where("packs", farm_id=who.farm_id):
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
        store.put("policies", policy["id"], policy)
    return {
        "ok": True,
        "code": "origin_copy_erased",
        "message": "Origin's stored facts were erased; recipient notices were recorded separately.",
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
    req = PartnerRequest(
        id=f"req-{uuid4().hex[:10]}",
        farm_id=body.farm_id,
        partner_id=partner_id,
        partner_name=agent.partner_display(partner_id),
        purpose=body.purpose or rule["purpose"],
        field_list=list(rule["fields"]),
        rule_id=rule_id,
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    store.put("requests", req.id, req.model_dump(mode="json"))
    run = runs.create_for_request(req)
    fresh = store.get("requests", req.id) or req.model_dump(mode="json")
    return {
        **fresh,
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
) -> dict:
    expected = settings().internal_token
    if not expected or not x_origin_worker_token or not hmac.compare_digest(
        expected, x_origin_worker_token
    ):
        raise HTTPException(403, {"code": "forbidden", "message": "Worker token required"})
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
    market = "US" if str(farm.get("country") or "").upper() == "US" else "EU"
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
