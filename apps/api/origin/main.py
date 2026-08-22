from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from origin import agent, capture, consent, deliver, questionnaire, store, terms
from origin.auth import farmer_only, partner_only, principal
from origin.compile import BUFFER_KEYS, compile_event, load_rule
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
    ensure_demo()
    yield


app = FastAPI(title="Origin API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/v1/today")
def today(who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    farm = store.get("farms", who.farm_id)
    parcels = store.list_where("parcels", farm_id=who.farm_id)
    open_reqs = store.list_where("requests", farm_id=who.farm_id, status="open")
    drafts = [c for c in store.list_where("consents", farm_id=who.farm_id) if c.get("state") == "draft"]
    policies = store.list_where("policies", farm_id=who.farm_id, state="active")
    return {
        "farm": farm,
        "parcels": parcels,
        "open_request": open_reqs[0] if open_reqs else None,
        "draft_consent": drafts[0] if drafts else None,
        "standing_policies": policies,
        "last_auto": agent.last_auto(who.farm_id),
        "last_decision": agent.last_decision(who.farm_id),
    }


@app.post("/v1/events")
async def post_event(
    parcel_id: str = Form("p3"),
    note: str = Form(""),
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    who: Principal = Depends(principal),
) -> dict:
    farmer_only(who)
    audio_bytes = await audio.read() if audio is not None else None
    image_bytes = await image.read() if image is not None else None
    source = "voice" if audio_bytes else "photo" if image_bytes else "note"
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
    open_reqs = store.list_where("requests", farm_id=who.farm_id, status="open")
    req_id = open_reqs[0]["id"] if open_reqs else None
    # No open request means no partner asked, so the pack follows the farm's
    # market — a US default here would hand an EU farm the elevator pack.
    rule_id = (open_reqs[0].get("rule_id") if open_reqs else None) or agent.default_rule_for_farm(farm)
    pack = compile_event(event, store.as_parcel(parcel_row), rule_id=rule_id)
    if req_id:
        req = open_reqs[0]
        req["status"] = "linked"
        store.put("requests", req_id, req)
    result = agent.fulfill_pack(
        pack=pack,
        request_id=req_id,
        locale=farm.get("locale", "en"),
    )
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
    return store.as_consent(row).model_dump(mode="json")


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
    return {
        "consent": bound.model_dump(mode="json"),
        "token": token.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "passport": passport,
        "policy": policy.model_dump(mode="json") if policy else None,
    }


@app.post("/v1/consents/{consent_id}/refuse")
def refuse_consent(consent_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    refused, receipt = consent.refuse(store.as_consent(row))
    return {"consent": refused.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json")}


@app.post("/v1/consents/{consent_id}/revoke")
def revoke_consent(consent_id: str, who: Principal = Depends(principal)) -> dict:
    farmer_only(who)
    row = store.get("consents", consent_id)
    if not row or row.get("farm_id") != who.farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Consent not found"})
    revoked = consent.revoke(store.as_consent(row))
    return revoked.model_dump(mode="json")


@app.get("/v1/receipts")
def list_receipts(who: Principal = Depends(principal)) -> list[dict]:
    farmer_only(who)
    rows = store.list_where("receipts", farm_id=who.farm_id)
    rows.sort(key=lambda r: r.get("issued_at", ""), reverse=True)
    return rows


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
    for policy in store.list_where("policies", farm_id=who.farm_id):
        policy["state"] = "revoked"
        store.put("policies", policy["id"], policy)
    return {"ok": True, "code": "erased"}


@app.post("/v1/desk/requests")
def desk_request(body: DeskRequestBody, who: Principal = Depends(principal)) -> dict:
    partner_only(who)
    partner_id = who.partner_id or ""
    farm = store.get("farms", body.farm_id) or {}
    rule_id = agent.default_rule_for(partner_id, farm)
    rule = load_rule(rule_id)
    req = PartnerRequest(
        id=f"req-{uuid4().hex[:10]}",
        farm_id=body.farm_id,
        partner_id=partner_id,
        partner_name=agent.partner_display(partner_id),
        purpose=body.purpose or rule["purpose"],
        field_list=[f for f in rule["fields"] if f not in BUFFER_KEYS],
        rule_id=rule_id,
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    store.put("requests", req.id, req.model_dump(mode="json"))
    decision = agent.tick_request(req)
    fresh = store.get("requests", req.id) or req.model_dump(mode="json")
    return {
        **fresh,
        "agent": {
            k: decision.get(k)
            for k in (
                "decision",
                "reason",
                "reason_code",
                "extra_fields",
                "note",
                "mode",
                "consent_id",
                "policy_id",
            )
        },
    }


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
    return deliver.desk_inbox(who.partner_id or "")


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
    return {"consent": c.model_dump(mode="json"), "pack": pack, "passport": deliver.lot_passport(c, store.as_pack(pack))}
