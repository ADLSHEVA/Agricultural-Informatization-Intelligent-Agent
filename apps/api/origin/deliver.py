from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.consent import _receipt, expire_if_due
from origin.models import ConsentRecord, PackRecord, ReceiptRecord, TokenRecord


LIVE = {"purpose-bound"}


def issue(consent: ConsentRecord) -> tuple[TokenRecord, ReceiptRecord]:
    tokens = store.list_where("tokens", consent_id=consent.id)
    token = (
        store.as_token(tokens[0])
        if tokens
        else TokenRecord(
            id=f"tok-{uuid4().hex[:12]}",
            consent_id=consent.id,
            farm_id=consent.farm_id,
            partner_id=consent.partner_id,
            expires_at=datetime.combine(consent.until, datetime.max.time()).replace(
                tzinfo=timezone.utc
            ),
            revoked=False,
        )
    )
    if not tokens:
        store.put("tokens", token.id, token.model_dump(mode="json"))
    receipts = [
        row
        for row in store.list_where("receipts", consent_id=consent.id)
        if row.get("kind") == "given"
    ]
    receipt = (
        store.as_receipt(receipts[0])
        if receipts
        else _receipt(consent, kind="given", grey=False)
    )
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
    now_iso = datetime.now(timezone.utc).isoformat()
    # A dead token kills visibility even if the consent state has not been
    # flipped yet: revoked OR past its expires_at.
    live = any(
        (not t.get("revoked")) and str(t.get("expires_at") or "") > now_iso
        for t in tokens
    )
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


def find_live_consent(
    farm_id: str,
    partner_id: str,
    purpose: str,
    event_id: str,
    requested_fields: list[str] | None = None,
) -> tuple[ConsentRecord, dict, dict] | None:
    """An open file that already covers exactly this fact?

    Asking again used to compile an identical pack and bind a second consent,
    token and receipt every time. If a live consent exists for the same farm,
    partner and purpose whose pack was compiled from this same event, reuse it
    instead of stacking another copy.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for row in store.list_where("consents", farm_id=farm_id, partner_id=partner_id):
        if row.get("purpose") != purpose or row.get("state") != "purpose-bound":
            continue
        pack = store.get("packs", row.get("pack_id") or "")
        if not pack or event_id not in (pack.get("event_ids") or []):
            continue
        if requested_fields and not set(requested_fields) <= set(pack.get("fields") or {}):
            continue
        c = store.as_consent(row)
        if expire_if_due(c).state != "purpose-bound":
            continue
        tokens = [
            t
            for t in store.list_where("tokens", consent_id=c.id)
            if (not t.get("revoked")) and str(t.get("expires_at") or "") > now_iso
        ]
        if not tokens:
            continue
        return c, pack, tokens[0]
    return None


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
    # Newest first by the pack's own creation time. Consent ids are random hex,
    # so sorting on them shuffled the inbox arbitrarily between runs.
    pairs: list[tuple[str, dict]] = []
    for slot in buckets.values():
        if slot["live"]:
            pairs.append((slot["live_ts"], slot["live"]))
        elif slot["grey"]:
            pairs.append((slot["grey_ts"], slot["grey"]))
    pairs.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in pairs]
