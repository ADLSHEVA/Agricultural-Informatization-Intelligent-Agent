"""Firestore adapter with the same deliberately small API as ``store.py``.

Imports are lazy so local development and the offline test suite do not need
Google Cloud packages or credentials. Collections are prefixed to isolate the
hackathon demo from unrelated data in the same project.
"""

from __future__ import annotations

from functools import lru_cache
import json
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


def _to_firestore(payload: dict[str, Any]) -> dict[str, Any]:
    """Encode values Firestore cannot represent without changing app models.

    Firestore rejects arrays nested directly inside arrays. GeoJSON Polygon
    coordinates require exactly that shape, so keep the complete geometry as a
    compact JSON string inside a tagged map and restore it on every read.
    """
    encoded = dict(payload)
    geom = encoded.get("geom")
    if isinstance(geom, dict):
        encoded["geom"] = {
            "encoding": "geojson",
            "value": json.dumps(geom, separators=(",", ":")),
        }
    return encoded


def _from_firestore(payload: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(payload)
    geom = decoded.get("geom")
    if isinstance(geom, dict) and geom.get("encoding") == "geojson":
        value = geom.get("value")
        if isinstance(value, str):
            decoded["geom"] = json.loads(value)
    return decoded


def put(collection: str, item_id: str, payload: dict[str, Any]) -> None:
    _collection(collection).document(item_id).set(_to_firestore(payload))


def put_if_status(
    collection: str,
    item_id: str,
    payload: dict[str, Any],
    allowed_statuses: set[str],
) -> bool:
    """Firestore transaction used as the AgentRun compare-and-set boundary."""
    from google.cloud import firestore

    client = _client()
    ref = _collection(collection).document(item_id)
    transaction = client.transaction()

    @firestore.transactional
    def update(transaction) -> bool:
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return False
        current = _from_firestore(snap.to_dict())
        if current.get("status") not in allowed_statuses:
            return False
        transaction.set(ref, _to_firestore(payload))
        return True

    return bool(update(transaction))


def put_if_absent(collection: str, item_id: str, payload: dict[str, Any]) -> bool:
    """Create a document once using a Firestore transaction."""
    from google.cloud import firestore

    client = _client()
    ref = _collection(collection).document(item_id)
    transaction = client.transaction()

    @firestore.transactional
    def create(transaction) -> bool:
        snap = ref.get(transaction=transaction)
        if snap.exists:
            return False
        transaction.set(ref, _to_firestore(payload))
        return True

    return bool(create(transaction))


def get(collection: str, item_id: str) -> dict[str, Any] | None:
    snap = _collection(collection).document(item_id).get()
    return _from_firestore(snap.to_dict()) if snap.exists else None


def delete(collection: str, item_id: str) -> None:
    _collection(collection).document(item_id).delete()


def list_where(collection: str, **equals: Any) -> list[dict[str, Any]]:
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = _collection(collection)
    # Use at most one server-side equality filter, then apply the remaining
    # predicates in process. This small hackathon dataset does not need a
    # composite index for every farm/partner/status combination, and it avoids
    # a production-only FAILED_PRECONDITION that the JSON tests cannot reveal.
    items = list(equals.items())
    if items:
        field, value = items[0]
        query = query.where(filter=FieldFilter(field, "==", value))
    rows = [_from_firestore(snap.to_dict()) for snap in query.stream()]
    return [row for row in rows if all(row.get(key) == value for key, value in items)]


def snapshot() -> dict[str, Any]:
    return {
        name: {snap.id: _from_firestore(snap.to_dict()) for snap in _collection(name).stream()}
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
