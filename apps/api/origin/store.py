from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from origin.models import (
    ConsentRecord,
    EventRecord,
    Farm,
    PackRecord,
    Parcel,
    PartnerRequest,
    ReceiptRecord,
    StandingPolicy,
    TokenRecord,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "origin.json"
_lock = threading.Lock()


def _empty() -> dict[str, Any]:
    return {
        "farms": {},
        "parcels": {},
        "events": {},
        "packs": {},
        "consents": {},
        "receipts": {},
        "tokens": {},
        "requests": {},
        "policies": {},
        "agent_log": {},
        "evidence": {},
        "rule_drafts": {},
        "rule_packs": {},
        "terms_reviews": {},
    }


def _load() -> dict[str, Any]:
    if not DB_PATH.exists():
        return _empty()
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def _save(db: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, default=str, indent=2), encoding="utf-8")
    tmp.replace(DB_PATH)


def snapshot() -> dict[str, Any]:
    with _lock:
        return _load()


def put(collection: str, item_id: str, payload: dict[str, Any]) -> None:
    with _lock:
        db = _load()
        db.setdefault(collection, {})[item_id] = payload
        _save(db)


def get(collection: str, item_id: str) -> dict[str, Any] | None:
    with _lock:
        return _load().get(collection, {}).get(item_id)


def delete(collection: str, item_id: str) -> None:
    with _lock:
        db = _load()
        db.get(collection, {}).pop(item_id, None)
        _save(db)


def list_where(collection: str, **equals: Any) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_load().get(collection, {}).values())
    out = []
    for row in rows:
        if all(row.get(k) == v for k, v in equals.items()):
            out.append(row)
    return out


def replace_all(db: dict[str, Any]) -> None:
    with _lock:
        _save(db)


def as_event(row: dict[str, Any]) -> EventRecord:
    return EventRecord.model_validate(row)


def as_pack(row: dict[str, Any]) -> PackRecord:
    return PackRecord.model_validate(row)


def as_consent(row: dict[str, Any]) -> ConsentRecord:
    return ConsentRecord.model_validate(row)


def as_receipt(row: dict[str, Any]) -> ReceiptRecord:
    return ReceiptRecord.model_validate(row)


def as_token(row: dict[str, Any]) -> TokenRecord:
    return TokenRecord.model_validate(row)


def as_request(row: dict[str, Any]) -> PartnerRequest:
    return PartnerRequest.model_validate(row)


def as_farm(row: dict[str, Any]) -> Farm:
    return Farm.model_validate(row)


def as_parcel(row: dict[str, Any]) -> Parcel:
    return Parcel.model_validate(row)


def as_policy(row: dict[str, Any]) -> StandingPolicy:
    return StandingPolicy.model_validate(row)
