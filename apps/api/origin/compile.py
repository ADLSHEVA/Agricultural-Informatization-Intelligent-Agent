from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import yaml

from origin import store
from origin.geometry import buffer_ok
from origin.models import EventRecord, PackRecord, Parcel

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
DEFAULT_RULE = "elevator_spray_statement_v1"
BUFFER_KEYS = ("buffer_ok", "gaec4_buffer_ok")


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
        pack = _yaml_packs().get(DEFAULT_RULE) or packs.get(DEFAULT_RULE)
    if pack is None:
        raise FileNotFoundError(f"no rule pack with an id found under {RULES_DIR}")
    return deepcopy(pack)


def _partner_entry(rule_id: str, pack: dict) -> tuple[str, dict] | None:
    partner_id = str(pack.get("partner") or "").strip()
    if not partner_id:
        return None
    return partner_id, {
        "name": str(pack.get("partner_name") or partner_id),
        "rule_id": rule_id,
        "market": str(pack.get("market") or "").upper(),
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
    """The pack serving a market: `US` -> elevator, `EU` -> co-op.

    A store pack for the same partner as the shipped market pack replaces it.
    A newly onboarded partner does not steal the market default.
    """
    wanted = market.upper()
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
    return shipped_id


def _buffer_field(rule: dict) -> str | None:
    names = list(rule.get("checks", [])) + list(rule.get("fields", []))
    for key in BUFFER_KEYS:
        if key in names:
            return key
    return None


def compile_event(event: EventRecord, parcel: Parcel, rule_id: str = DEFAULT_RULE) -> PackRecord:
    """YAML + geometry only. Gemini never runs here."""
    rule = load_rule(rule_id)
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
    buffer_field = _buffer_field(rule)
    fields = {key: source.get(key) for key in rule["fields"] if key not in BUFFER_KEYS}
    checks = {}
    if buffer_field:
        checks = buffer_ok(parcel, event.buffer_m)
        fields[buffer_field] = checks["buffer_ok"]
    for banned in rule.get("exclude", []):
        fields.pop(banned, None)

    pack = PackRecord(
        id=f"pack-{uuid4().hex[:10]}",
        farm_id=event.farm_id,
        event_ids=[event.id],
        rule_id=rule["id"],
        partner_id=rule["partner"],
        purpose=rule["purpose"],
        fields=fields,
        checks=checks,
        created_at=datetime.now(timezone.utc),
    )
    store.put("packs", pack.id, pack.model_dump(mode="json"))
    return pack
