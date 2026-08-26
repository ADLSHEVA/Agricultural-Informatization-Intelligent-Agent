"""Evidence and delivery-object storage with local and Cloud Storage backends."""

from __future__ import annotations

import json
from functools import lru_cache

from origin import store
from origin.config import settings


@lru_cache(maxsize=1)
def _bucket():
    if not settings().bucket:
        return None
    from google.cloud import storage

    client = storage.Client(project=settings().gcp_project or None)
    return client.bucket(settings().bucket)


def save_evidence(
    *, farm_id: str, event_id: str, filename: str, data: bytes, content_type: str
) -> str:
    bucket = _bucket()
    object_name = f"evidence/{farm_id}/{event_id}/{filename}"
    if bucket is not None:
        blob = bucket.blob(object_name)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{bucket.name}/{object_name}"

    path = store.DATA_DIR / object_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def save_delivery(*, partner_id: str, delivery_id: str, payload: dict) -> str | None:
    bucket = _bucket()
    if bucket is None:
        return None
    object_name = f"partner-inbox/{partner_id}/{delivery_id}.json"
    bucket.blob(object_name).upload_from_string(
        json.dumps(payload, default=str, separators=(",", ":")),
        content_type="application/json",
    )
    return f"gs://{bucket.name}/{object_name}"


def save_notice(*, partner_id: str, notice_id: str, payload: dict) -> str | None:
    bucket = _bucket()
    if bucket is None:
        return None
    object_name = f"partner-notices/{partner_id}/{notice_id}.json"
    bucket.blob(object_name).upload_from_string(
        json.dumps(payload, default=str, separators=(",", ":")),
        content_type="application/json",
    )
    return f"gs://{bucket.name}/{object_name}"


def wipe_evidence(farm_id: str) -> None:
    bucket = _bucket()
    if bucket is not None:
        for blob in bucket.list_blobs(prefix=f"evidence/{farm_id}/"):
            blob.delete()
        return

    root = store.DATA_DIR / "evidence" / farm_id
    if not root.exists():
        return
    # Files only; empty directories are harmless and avoid recursive deletion.
    for path in root.rglob("*"):
        if path.is_file():
            path.unlink()
