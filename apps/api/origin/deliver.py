from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.consent import _receipt, expire_if_due
from origin.models import ConsentRecord, PackRecord, ReceiptRecord, TokenRecord


LIVE = {"purpose-bound"}


def issue(consent: ConsentRecord) -> tuple[TokenRecord, ReceiptRecord]:
    token = TokenRecord(
        id=f"tok-{uuid4().hex[:12]}",
        consent_id=consent.id,
        farm_id=consent.farm_id,
        partner_id=consent.partner_id,
        expires_at=datetime.combine(consent.until, datetime.max.time()).replace(tzinfo=timezone.utc),
        revoked=False,
    )
    store.put("tokens", token.id, token.model_dump(mode="json"))
    receipt = _receipt(consent, kind="given", grey=False)
    return token, receipt


def lot_passport(consent: ConsentRecord, pack: PackRecord) -> dict:
    return {
        "kind": "lot_passport",
        "partner": consent.partner_name,
        "purpose": consent.purpose,
        "until": consent.until.isoformat(),
        "fields": pack.fields,
        "consent_id": consent.id,
    }


def desk_visible(consent: ConsentRecord) -> None:
    consent = expire_if_due(consent)
    tokens = store.list_where("tokens", consent_id=consent.id)
    live = any(not t.get("revoked") for t in tokens)
    if consent.state not in LIVE or not live:
        raise HTTPException(
            410,
            {"code": "consent_unavailable", "message": f"Pack not visible ({consent.state})"},
        )
