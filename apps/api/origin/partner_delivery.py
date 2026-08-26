"""Idempotent delivery to the partner inbox, Cloud Storage, and a webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx

from origin import blobs, store
from origin.config import settings
from origin.models import ConsentRecord, PackRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"partner webhook returned HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: partner destination unavailable"


def _post(payload: dict) -> dict:
    cfg = settings()
    if not cfg.partner_webhook_url:
        return {"configured": False, "status": "not_configured"}
    body = json.dumps(payload, default=str, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "Idempotency-Key": payload["id"]}
    if cfg.partner_webhook_secret:
        headers["X-Origin-Signature"] = hmac.new(
            cfg.partner_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
    response = httpx.post(cfg.partner_webhook_url, content=body, headers=headers, timeout=10.0)
    response.raise_for_status()
    return {"configured": True, "status": response.status_code}


def send(
    consent: ConsentRecord,
    pack: PackRecord,
    *,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> dict:
    """Deliver once per consent; retries reuse the same delivery id."""
    delivery_id = f"dlv-{consent.id.removeprefix('cns-')}"
    existing = store.get("deliveries", delivery_id)
    if existing and existing.get("status") == "delivered":
        return existing

    payload = {
        "id": delivery_id,
        "event": "origin.share_pack.delivered",
        "run_id": run_id,
        "trace_id": trace_id,
        "partner_id": consent.partner_id,
        "farm_id": consent.farm_id,
        "consent_id": consent.id,
        "purpose": consent.purpose,
        "valid_until": consent.until.isoformat(),
        "pack": {
            "id": pack.id,
            "fields": pack.fields,
            "checks": pack.checks,
            "created_at": pack.created_at.isoformat(),
        },
        "sent_at": _now(),
    }
    record = {
        **payload,
        "status": "delivering",
        "destinations": ["origin_partner_desk"],
        "object_uri": None,
        "webhook": {"configured": False, "status": "not_attempted"},
        "recipient_notice": "not_required",
    }
    store.put("deliveries", delivery_id, record)
    try:
        object_uri = blobs.save_delivery(
            partner_id=consent.partner_id, delivery_id=delivery_id, payload=payload
        )
        if object_uri:
            record["object_uri"] = object_uri
            record["destinations"].append("cloud_storage_partner_inbox")
        record["webhook"] = _post(payload)
        if record["webhook"].get("configured"):
            record["destinations"].append("partner_webhook")
        record["status"] = "delivered"
        record["delivered_at"] = _now()
        record["error"] = None
        store.put("deliveries", delivery_id, record)
        return record
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = _safe_error(exc)
        record["failed_at"] = _now()
        store.put("deliveries", delivery_id, record)
        raise


def send_notice(kind: str, consent: ConsentRecord, pack: PackRecord | None) -> dict:
    """Notify recipients without claiming that their downloaded copies vanished."""
    delivery_id = f"dlv-{consent.id.removeprefix('cns-')}"
    notice_id = f"ntc-{kind}-{consent.id.removeprefix('cns-')}"
    payload = {
        "id": notice_id,
        "event": f"origin.share_pack.{kind}",
        "partner_id": consent.partner_id,
        "farm_id": consent.farm_id,
        "consent_id": consent.id,
        "pack_id": pack.id if pack else consent.pack_id,
        "purpose": consent.purpose,
        "requested_at": _now(),
        "message": (
            "Future access through Origin is disabled. Confirm handling of any "
            "previously exported copy under the applicable agreement."
        ),
    }
    notice = {**payload, "status": "recorded", "object_uri": None, "webhook": {}}
    try:
        notice["object_uri"] = blobs.save_notice(
            partner_id=consent.partner_id, notice_id=notice_id, payload=payload
        )
        notice["webhook"] = _post(payload)
        notice["status"] = "sent" if notice["object_uri"] or notice["webhook"].get("configured") else "recorded"
    except Exception as exc:
        notice["status"] = "failed"
        notice["error"] = _safe_error(exc)
    store.put("deliveries", notice_id, notice)
    current = store.get("deliveries", delivery_id)
    if current:
        current["access_status"] = kind
        current["recipient_notice"] = notice["status"]
        current["notice_id"] = notice_id
        store.put("deliveries", delivery_id, current)
    return notice


def for_consent(consent_id: str) -> dict | None:
    delivery_id = f"dlv-{consent_id.removeprefix('cns-')}"
    return store.get("deliveries", delivery_id)
