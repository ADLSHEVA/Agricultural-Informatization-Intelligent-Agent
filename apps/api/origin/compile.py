from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from origin import store
from origin.geometry import buffer_ok
from origin.models import EventRecord, PackRecord, Parcel

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
DEFAULT_RULE = "elevator_spray_statement_v1"
BUFFER_KEYS = ("buffer_ok", "gaec4_buffer_ok")


def load_rule(rule_id: str = DEFAULT_RULE) -> dict:
    path = RULES_DIR / f"{rule_id.replace('_v1', '')}.yaml"
    if not path.exists():
        path = RULES_DIR / "elevator_spray_statement.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
