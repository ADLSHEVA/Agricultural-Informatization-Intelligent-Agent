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


def _is_live(consent: ConsentRecord) -> bool:
    try:
        desk_visible(consent)
        return True
    except HTTPException:
        return False


def desk_inbox(partner_id: str) -> list[dict]:
    """One current file per farm + purpose.

    Asking again under standing permission used to append another identical
    live row. The desk should show the file they can open now, and a grey
    row only when they can no longer open anything for that farm and purpose.
    """
    buckets: dict[tuple[str, str], dict] = {}
    for c_row in store.list_where("consents", partner_id=partner_id):
        c = store.as_consent(c_row)
        pack = store.get("packs", c.pack_id) or {}
        ts = str(pack.get("created_at") or "")
        key = (c.farm_id, c.purpose)
        slot = buckets.setdefault(key, {"live": None, "live_ts": "", "grey": None, "grey_ts": ""})
        if _is_live(c):
            if ts >= slot["live_ts"]:
                slot["live"] = {
                    "consent": c.model_dump(mode="json"),
                    "pack": pack,
                    "grey": False,
                }
                slot["live_ts"] = ts
            continue
        if c.state in {"revoked", "expired", "refused", "erased"} and ts >= slot["grey_ts"]:
            slot["grey"] = {
                "consent": c.model_dump(mode="json"),
                "pack": {"id": pack.get("id"), "fields": {}},
                "grey": True,
            }
            slot["grey_ts"] = ts
    out: list[dict] = []
    for slot in buckets.values():
        if slot["live"]:
            out.append(slot["live"])
        elif slot["grey"]:
            out.append(slot["grey"])
    out.sort(key=lambda row: row.get("consent", {}).get("id", ""), reverse=True)
    return out
