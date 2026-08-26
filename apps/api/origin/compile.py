from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from pathlib import Path
from uuid import uuid4

import yaml

from origin import store
from origin.geometry import buffer_ok
from origin.models import EventRecord, PackRecord, Parcel

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
DEFAULT_RULE = "elevator_spray_statement_v1"
BUFFER_KEYS = ("buffer_ok",)


@lru_cache(maxsize=1)
def _yaml_packs() -> dict[str, dict]:
    """Shipped packs in `rules/`, keyed by `id`, parsed once.

    Scanning beats deriving a filename from the id: a pack can be renamed or
    bumped to `_v2`. A pack with no `id` is skipped — it cannot be addressed.
    """
    index: dict[str, dict] = {}
    for path in sorted(RULES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        rule_id = str(data.get("id") or "").strip()
        if rule_id:
            index[rule_id] = data
    return index


def _store_packs() -> dict[str, dict]:
    """Approved packs. Cloud Run cannot write YAML, so this is where they live."""
    index: dict[str, dict] = {}
    for pack in store.list_where("rule_packs"):
        if not isinstance(pack, dict):
            continue
        rule_id = str(pack.get("id") or "").strip()
        if rule_id:
            index[rule_id] = pack
    return index


def _packs() -> dict[str, dict]:
    """YAML first, store overlays by id — an approved draft replaces a shipped pack."""
    index = dict(_yaml_packs())
    index.update(_store_packs())
    return index


def reload_rules() -> None:
    """Drop the parsed-YAML cache. Store packs are read live and need no clear."""
    _yaml_packs.cache_clear()


def load_rule(rule_id: str = DEFAULT_RULE) -> dict:
    packs = _packs()
    pack = packs.get(rule_id)
    if pack is None:
        raise KeyError(f"unknown rule pack: {rule_id}")
    return deepcopy(pack)


def _partner_entry(rule_id: str, pack: dict) -> tuple[str, dict] | None:
    partner_id = str(pack.get("partner") or "").strip()
    market = str(pack.get("market") or "").upper()
    if not partner_id or market != "US":
        return None
    return partner_id, {
        "name": str(pack.get("partner_name") or partner_id),
        "rule_id": rule_id,
        "market": market,
    }


def partner_index() -> dict[str, dict]:
    """`partner_id` -> `{name, rule_id, market}`.

    YAML ships the defaults; a store pack for the same partner replaces them.
    A newly onboarded partner appears alongside. `agent.py` reads this instead
    of keeping a second copy of the partner list.
    """
    index: dict[str, dict] = {}
    for rule_id, pack in _yaml_packs().items():
        entry = _partner_entry(rule_id, pack)
        if entry:
            index[entry[0]] = entry[1]
    for rule_id, pack in _store_packs().items():
        entry = _partner_entry(rule_id, pack)
        if entry:
            index[entry[0]] = entry[1]
    return index


def rule_for_market(market: str) -> str:
    """Return the active US default pack and reject unsupported markets.

    A store pack for the same partner as the shipped market pack replaces it.
    A newly onboarded partner does not steal the market default.
    """
    wanted = market.upper()
    if wanted != "US":
        raise KeyError(f"unsupported market: {market}")
    shipped_id = DEFAULT_RULE
    shipped_partner = ""
    for rule_id, pack in _yaml_packs().items():
        if str(pack.get("market") or "").upper() == wanted:
            shipped_id = rule_id
            shipped_partner = str(pack.get("partner") or "")
            break
    stored = _store_packs()
    if shipped_id in stored:
        return shipped_id
    if shipped_partner:
        for rule_id, pack in stored.items():
            if str(pack.get("partner") or "") == shipped_partner:
                return rule_id
    if shipped_partner:
        return shipped_id
    raise KeyError("no shipped US rule pack is configured")


def _buffer_field(rule: dict) -> str | None:
    names = list(rule.get("checks", [])) + list(rule.get("fields", []))
    for key in BUFFER_KEYS:
        if key in names:
            return key
    return None


def compile_event(
    event: EventRecord,
    parcel: Parcel,
    rule_id: str = DEFAULT_RULE,
    *,
    requested_fields: list[str] | None = None,
    purpose: str | None = None,
    idempotency_key: str | None = None,
) -> PackRecord:
    """YAML + geometry only. Gemini never runs here."""
    rule = load_rule(rule_id)
    pack_id = (
        f"pack-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]}"
        if idempotency_key
        else f"pack-{uuid4().hex[:10]}"
    )
    if idempotency_key:
        existing = store.get("packs", pack_id)
        if existing:
            return store.as_pack(existing)
    source = {
        "parcel_id": event.parcel_id,
        "date": event.time.date().isoformat(),
        "product_name": event.product_name,
        "rate": event.rate,
        "unit": event.unit,
        "buffer_m": event.buffer_m,
        "yield": None,
        "revenue": None,
    }
    rule_fields = list(rule["fields"])
    requested = set(requested_fields if requested_fields is not None else rule_fields)
    # A request can ask for a subset of its approved rule pack, never for a
    # field the rule does not carry. The API creates requests from that rule;
    # this second boundary keeps imported/stale records conservative too.
    requested &= set(rule_fields)
    buffer_field = _buffer_field(rule)
    fields = {
        key: source.get(key)
        for key in rule_fields
        if key in requested and key not in BUFFER_KEYS
    }
    checks = {}
    if buffer_field and buffer_field in requested:
        checks = buffer_ok(parcel, event.buffer_m)
        fields[buffer_field] = checks["buffer_ok"]
    for banned in rule.get("exclude", []):
        fields.pop(banned, None)

    pack = PackRecord(
        id=pack_id,
        farm_id=event.farm_id,
        event_ids=[event.id],
        rule_id=rule["id"],
        partner_id=rule["partner"],
        purpose=purpose or rule["purpose"],
        fields=fields,
        checks=checks,
        created_at=datetime.now(timezone.utc),
    )
    payload = pack.model_dump(mode="json")
    if idempotency_key and not store.put_if_absent("packs", pack.id, payload):
        return store.as_pack(store.get("packs", pack.id) or payload)
    if not idempotency_key:
        store.put("packs", pack.id, payload)
    return pack
