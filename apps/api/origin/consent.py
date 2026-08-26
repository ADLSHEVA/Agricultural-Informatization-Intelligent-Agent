from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.compile import BUFFER_KEYS, load_rule
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
    # A lost HTTP response may cause the same consent to be submitted again.
    # Returning the already-bound record is safe; a *different* consent for the
    # same non-reusable pack is still rejected below.
    if consent.state == "purpose-bound":
        return consent
    if consent.state != "draft":
        raise HTTPException(409, {"code": "invalid_state", "message": f"Cannot bind from {consent.state}"})
    if not consent.reuse:
        # The card said "Reuse: No", so it must mean something: this compiled
        # file can be granted exactly once. A second grant of the same pack —
        # even after revoke or expiry — is refused; the partner asks again and
        # a fresh compile comes back to the farmer. Auto-delivery compiles a
        # new pack each time, so the standing-policy loop is unaffected.
        taken = [
            row
            for row in store.list_where("consents", pack_id=consent.pack_id)
            if row.get("id") != consent.id
            and row.get("state") in {"purpose-bound", "revoked", "expired", "erased"}
        ]
        if taken:
            raise HTTPException(
                409,
                {
                    "code": "reuse_forbidden",
                    "message": f"Pack {consent.pack_id} was already granted (reuse is off)",
                },
            )
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
        partner_id=consent.partner_id,
        purpose=consent.purpose,
        until=consent.until,
        pack_hash=digest,
        field_list=consent.fields,
        issued_at=datetime.now(timezone.utc),
        kind=kind,  # type: ignore[arg-type]
        grey=grey,
    )
    store.put("receipts", receipt.id, receipt.model_dump(mode="json"))
    return receipt


def find_open_draft(
    farm_id: str,
    partner_id: str,
    purpose: str,
    event_id: str,
    requested_fields: list[str] | None = None,
) -> ConsentRecord | None:
    """A draft already waiting on the farmer for this same fact?

    Repeated partner asks used to compile a fresh pack and open a new draft
    every time — orphan cards piling up in the wallet while Today showed only
    one of them. If a draft exists whose pack covers this event, partner and
    purpose, reuse it instead of opening another.
    """
    for row in store.list_where("consents", farm_id=farm_id, partner_id=partner_id, state="draft"):
        if row.get("purpose") != purpose:
            continue
        pack = store.get("packs", row.get("pack_id") or "")
        actual = set((pack or {}).get("fields") or {}) - set(BUFFER_KEYS)
        requested = set(requested_fields or actual) - set(BUFFER_KEYS)
        if (
            pack
            and event_id in (pack.get("event_ids") or [])
            and actual == requested
        ):
            return store.as_consent(row)
    return None


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
