from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.compile import load_rule
from origin.gemini_router import explain_consent
from origin.models import ConsentRecord, PackRecord, PlainTalk, ReceiptRecord


def year_end(today: date | None = None) -> date:
    today = today or date.today()
    return date(today.year, 12, 31)


def until_from_rule(rule: dict, today: date | None = None) -> date:
    """Read the expiry the rule pack asked for.

    Accepts ``end_of_calendar_year``, ``+90d``, or an ISO date. Anything we do
    not recognise falls back to year end rather than granting a longer window —
    a rule pack typo must never widen a consent.
    """
    today = today or date.today()
    raw = str(rule.get("until") or "").strip()
    if not raw or raw == "end_of_calendar_year":
        return year_end(today)
    days = re.fullmatch(r"\+(\d+)d", raw)
    if days:
        return today + timedelta(days=int(days.group(1)))
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return year_end(today)


def open_draft(pack: PackRecord, locale: str, request_id: str | None = None) -> ConsentRecord:
    rule = load_rule(pack.rule_id)
    partner_name = rule.get("partner_name", pack.partner_id)
    reuse = bool(rule.get("reuse", False))
    until = until_from_rule(rule)
    talk = explain_consent(
        partner_name=partner_name,
        purpose=pack.purpose,
        fields=pack.fields,
        until=until.isoformat(),
        reuse=reuse,
        locale=locale,
    )
    consent = ConsentRecord(
        id=f"cns-{uuid4().hex[:10]}",
        farm_id=pack.farm_id,
        pack_id=pack.id,
        partner_id=pack.partner_id,
        partner_name=partner_name,
        purpose=pack.purpose,
        fields=list(pack.fields.keys()),
        until=until,
        reuse=reuse,
        state="draft",
        locale=locale,
        plain_talk=talk,
        request_id=request_id,
    )
    store.put("consents", consent.id, consent.model_dump(mode="json"))
    return consent


def bind(consent: ConsentRecord) -> ConsentRecord:
    if consent.state != "draft":
        raise HTTPException(409, {"code": "invalid_state", "message": f"Cannot bind from {consent.state}"})
    consent.state = "purpose-bound"
    store.put("consents", consent.id, consent.model_dump(mode="json"))
    return consent


def refuse(consent: ConsentRecord) -> tuple[ConsentRecord, ReceiptRecord]:
    if consent.state != "draft":
        raise HTTPException(409, {"code": "invalid_state", "message": f"Cannot refuse from {consent.state}"})
    consent.state = "refused"
    store.put("consents", consent.id, consent.model_dump(mode="json"))
    receipt = _receipt(consent, kind="refused", grey=True)
    return consent, receipt


def revoke(consent: ConsentRecord) -> ConsentRecord:
    if consent.state != "purpose-bound":
        raise HTTPException(409, {"code": "invalid_state", "message": f"Cannot revoke from {consent.state}"})
    consent.state = "revoked"
    store.put("consents", consent.id, consent.model_dump(mode="json"))
    _disable_tokens(consent.id)
    _grey_receipts(consent.id)
    return consent


def expire_if_due(consent: ConsentRecord) -> ConsentRecord:
    if consent.state == "purpose-bound" and date.today() > consent.until:
        consent.state = "expired"
        store.put("consents", consent.id, consent.model_dump(mode="json"))
        _disable_tokens(consent.id)
        _grey_receipts(consent.id)
    return consent


def _receipt(consent: ConsentRecord, kind: str, grey: bool) -> ReceiptRecord:
    import hashlib

    pack_row = store.get("packs", consent.pack_id) or {}
    digest = hashlib.sha256(repr(pack_row.get("fields", {})).encode()).hexdigest()[:16]
    receipt = ReceiptRecord(
        id=f"rcp-{uuid4().hex[:10]}",
        farm_id=consent.farm_id,
        consent_id=consent.id,
        pack_id=consent.pack_id,
        partner_name=consent.partner_name,
        pack_hash=digest,
        field_list=consent.fields,
        issued_at=datetime.now(timezone.utc),
        kind=kind,  # type: ignore[arg-type]
        grey=grey,
    )
    store.put("receipts", receipt.id, receipt.model_dump(mode="json"))
    return receipt


def _disable_tokens(consent_id: str) -> None:
    for row in store.list_where("tokens", consent_id=consent_id):
        row["revoked"] = True
        store.put("tokens", row["id"], row)


def _grey_receipts(consent_id: str) -> None:
    for row in store.list_where("receipts", consent_id=consent_id):
        row["grey"] = True
        store.put("receipts", row["id"], row)


def empty_talk() -> PlainTalk:
    return PlainTalk(who="", why="", what="", until="", reuse="No")
