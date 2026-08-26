"""Firestore adapter with the same deliberately small API as ``store.py``.

Imports are lazy so local development and the offline test suite do not need
Google Cloud packages or credentials. Collections are prefixed to isolate the
hackathon demo from unrelated data in the same project.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

COLLECTIONS = (
    "farms",
    "parcels",
    "events",
    "packs",
    "consents",
    "receipts",
    "tokens",
    "requests",
    "policies",
    "agent_log",
    "rule_drafts",
    "rule_packs",
    "terms_reviews",
    "agent_runs",
    "deliveries",
    "llm_calls",
)


@lru_cache(maxsize=1)
def _client():
    from google.cloud import firestore

    from origin.config import settings

    return firestore.Client(project=settings().gcp_project or None)


def _collection(name: str):
    from origin.config import settings

    prefix = settings().firestore_prefix.strip() or "origin"
    return _client().collection(f"{prefix}_{name}")


def put(collection: str, item_id: str, payload: dict[str, Any]) -> None:
    _collection(collection).document(item_id).set(payload)


def get(collection: str, item_id: str) -> dict[str, Any] | None:
    snap = _collection(collection).document(item_id).get()
    return snap.to_dict() if snap.exists else None


def delete(collection: str, item_id: str) -> None:
    _collection(collection).document(item_id).delete()


def list_where(collection: str, **equals: Any) -> list[dict[str, Any]]:
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = _collection(collection)
    for field, value in equals.items():
        query = query.where(filter=FieldFilter(field, "==", value))
    return [snap.to_dict() for snap in query.stream()]


def snapshot() -> dict[str, Any]:
    return {
        name: {snap.id: snap.to_dict() for snap in _collection(name).stream()}
        for name in COLLECTIONS
    }


def replace_all(db: dict[str, Any]) -> None:
    """Replace the prefixed demo dataset. Intended for explicit maintenance."""
    client = _client()
    for name in COLLECTIONS:
        refs = list(_collection(name).list_documents())
        for offset in range(0, len(refs), 400):
            batch = client.batch()
            for ref in refs[offset : offset + 400]:
                batch.delete(ref)
            batch.commit()
    for name, rows in db.items():
        for item_id, payload in rows.items():
            put(name, item_id, payload)
