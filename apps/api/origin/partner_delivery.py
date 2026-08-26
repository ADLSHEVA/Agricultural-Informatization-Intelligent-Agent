"""Idempotent delivery to the partner inbox, Cloud Storage, and a webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

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
        "attempt_started_at": _now(),
    }
    if existing:
        status = str(existing.get("status") or "")
        if status not in {"failed", "delivering", "recovering"}:
            raise RuntimeError(f"delivery cannot resume from {status or 'unknown'}")
        if status in {"delivering", "recovering"}:
            try:
                started = datetime.fromisoformat(str(existing.get("attempt_started_at") or ""))
            except ValueError:
                started = datetime.min.replace(tzinfo=timezone.utc)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - started <= timedelta(seconds=30):
                raise RuntimeError("delivery is already in progress")
        claim = {**existing, "status": "recovering", "attempt_started_at": _now()}
        if not store.put_if_status("deliveries", delivery_id, claim, {status}):
            current = store.get("deliveries", delivery_id) or {}
            if current.get("status") == "delivered":
                return current
            raise RuntimeError("delivery is already in progress")
        store.put("deliveries", delivery_id, record)
    elif not store.put_if_absent("deliveries", delivery_id, record):
        current = store.get("deliveries", delivery_id) or {}
        if current.get("status") == "delivered":
            return current
        raise RuntimeError("delivery is already in progress")
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


def erase_origin_copy(farm_id: str) -> int:
    """Remove payloads and bucket objects while retaining hash-only audit stubs.

    A webhook recipient may already have exported a copy; that is why erase
    sends a notice first. This function only claims deletion of copies managed
    by Origin itself: Firestore/JSON delivery payloads and the configured GCS
    partner inbox/notice objects.
    """
    rows = store.list_where("deliveries", farm_id=farm_id)
    erased_at = _now()
    for row in rows:
        blobs.delete_uri(row.get("object_uri"))
        pack = row.get("pack") if isinstance(row.get("pack"), dict) else {}
        sensitive = {
            "pack": pack,
            "message": row.get("message"),
            "purpose": row.get("purpose"),
        }
        digest = hashlib.sha256(
            json.dumps(sensitive, default=str, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        stub = {
            "id": row["id"],
            "event": row.get("event"),
            "partner_id": row.get("partner_id"),
            "farm_id": farm_id,
            "consent_id": row.get("consent_id"),
            "status": "origin_copy_erased",
            "destinations": list(row.get("destinations") or []),
            "recipient_notice": row.get("recipient_notice"),
            "content_hash": digest,
            "object_uri": None,
            "erased_at": erased_at,
        }
        if pack:
            stub["pack"] = {"id": pack.get("id"), "fields": {}, "checks": {}}
        store.put("deliveries", row["id"], stub)
    return len(rows)
