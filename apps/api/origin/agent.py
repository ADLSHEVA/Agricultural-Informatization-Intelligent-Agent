"""Origin Agent — decide and deliver inside a farmer-set standing policy.

Gemini never decides whether to share. YAML compile + policy match only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from origin import consent, deliver, store
from origin.compile import compile_event
from origin.models import ConsentRecord, EventRecord, PartnerRequest, StandingPolicy

PARTNER_NAMES = {
    "heartland-grain": "Heartland Grain LLC",
    "loire-cereals-coop": "Loire Cereals Co-op",
}

PARTNER_RULES = {
    "heartland-grain": "elevator_spray_statement_v1",
    "loire-cereals-coop": "coop_ppp_statement_v1",
}

DEFAULT_RULE = "elevator_spray_statement_v1"


def partner_display(partner_id: str) -> str:
    return PARTNER_NAMES.get(partner_id, partner_id)


def default_rule_for(partner_id: str) -> str:
    return PARTNER_RULES.get(partner_id, DEFAULT_RULE)


def activate_standing(bound: ConsentRecord) -> StandingPolicy:
    policy = StandingPolicy(
        id=f"pol-{uuid4().hex[:10]}",
        farm_id=bound.farm_id,
        partner_id=bound.partner_id,
        purpose=bound.purpose,
        allowed_fields=list(bound.fields),
        until=bound.until,
        reuse=bound.reuse,
        state="active",
        created_from_consent_id=bound.id,
    )
    store.put("policies", policy.id, policy.model_dump(mode="json"))
    return policy


def match_standing(
    farm_id: str, partner_id: str, purpose: str, fields: list[str]
) -> StandingPolicy | None:
    today = date.today()
    for row in store.list_where("policies", farm_id=farm_id, partner_id=partner_id, state="active"):
        policy = store.as_policy(row)
        if policy.purpose != purpose:
            continue
        if policy.until < today:
            continue
        if set(fields) <= set(policy.allowed_fields):
            return policy
    return None


def latest_confirmed(farm_id: str) -> EventRecord | None:
    rows = store.list_where("events", farm_id=farm_id, status="confirmed")
    if not rows:
        return None
    events = [store.as_event(row) for row in rows]
    return max(events, key=lambda item: item.time)


def _write_log(payload: dict) -> dict:
    payload = {
        **payload,
        "id": payload.get("id") or f"agt-{uuid4().hex[:10]}",
        "at": datetime.now(timezone.utc).isoformat(),
    }
    store.put("agent_log", payload["id"], payload)
    return payload


def fulfill_pack(
    *,
    pack,
    request_id: str | None,
    locale: str,
    force_ask: bool = False,
) -> dict:
    """Compile is already done. Auto-bind if a standing policy covers the pack."""
    policy = None
    if not force_ask:
        policy = match_standing(pack.farm_id, pack.partner_id, pack.purpose, list(pack.fields.keys()))
    draft = consent.open_draft(pack, locale=locale, request_id=request_id)
    if policy is None:
        return _write_log(
            {
                "farm_id": pack.farm_id,
                "request_id": request_id,
                "pack_id": pack.id,
                "consent_id": draft.id,
                "decision": "ask_farmer",
                "reason": "new partner, new purpose, or extra fields — farmer must give or refuse",
            }
        ) | {"mode": "ask", "consent": draft}

    bound = consent.bind(draft)
    token, receipt = deliver.issue(bound)
    return _write_log(
        {
            "farm_id": pack.farm_id,
            "request_id": request_id,
            "pack_id": pack.id,
            "consent_id": bound.id,
            "policy_id": policy.id,
            "decision": "auto_deliver",
            "reason": f"standing policy {policy.id} already covers {pack.purpose}",
        }
    ) | {"mode": "auto", "consent": bound, "token": token, "receipt": receipt, "policy": policy}


def tick_request(req: PartnerRequest) -> dict:
    """Run one open partner request to a decision. No chat. No Gemini on share/no-share."""
    event = latest_confirmed(req.farm_id)
    if event is None:
        return _write_log(
            {
                "farm_id": req.farm_id,
                "request_id": req.id,
                "decision": "need_capture",
                "reason": "no confirmed field fact to compile",
            }
        ) | {"mode": "need_capture"}

    parcel_row = store.get("parcels", event.parcel_id)
    if not parcel_row:
        return _write_log(
            {
                "farm_id": req.farm_id,
                "request_id": req.id,
                "decision": "need_capture",
                "reason": "confirmed event points at an unknown field",
            }
        ) | {"mode": "need_capture"}

    rule_id = req.rule_id or default_rule_for(req.partner_id)
    pack = compile_event(event, store.as_parcel(parcel_row), rule_id=rule_id)
    farm = store.get("farms", req.farm_id) or {}
    result = fulfill_pack(pack=pack, request_id=req.id, locale=farm.get("locale", "en"))
    if result.get("mode") in {"auto", "ask"}:
        row = store.get("requests", req.id) or req.model_dump(mode="json")
        row["status"] = "linked"
        store.put("requests", req.id, row)
    return result


def tick_farm(farm_id: str) -> list[dict]:
    actions = []
    for row in store.list_where("requests", farm_id=farm_id, status="open"):
        actions.append(tick_request(store.as_request(row)))
    return actions


def last_auto(farm_id: str) -> dict | None:
    rows = [r for r in store.list_where("agent_log", farm_id=farm_id) if r.get("decision") == "auto_deliver"]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("at", ""), reverse=True)
    return rows[0]
