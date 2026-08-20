"""Origin Agent — decide and deliver inside a farmer-set standing policy.

The decision is a policy match against YAML-compiled fields: strict containment,
same purpose, not past `until`. Gemini is called **after** the decision exists,
only to phrase it in the farmer's language, and a failure there changes nothing.
It never decides whether to share.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from origin import consent, deliver, store
from origin.compile import compile_event, partner_index, rule_for_market
from origin.gemini_router import narrate_decision
from origin.models import ConsentRecord, EventRecord, PartnerRequest, StandingPolicy

# Last resort only, for when `rules/` is empty or a partner has no pack yet: it
# stops the UI printing a bare slug. The YAML packs are the source of truth.
FALLBACK_PARTNER_NAMES = {
    "heartland-grain": "Heartland Grain LLC",
    "loire-cereals-coop": "Loire Cereals Co-op",
}


def partner_display(partner_id: str) -> str:
    entry = partner_index().get(partner_id)
    if entry:
        return entry["name"]
    return FALLBACK_PARTNER_NAMES.get(partner_id, partner_id)


def default_rule_for_farm(farm: dict | None) -> str:
    """Pick a pack by where the farm is. The only jurisdiction test in the code.

    Everything else about a market lives in the YAML. An unknown country reads
    as EU: this is an EU hackathon, and the EU pack is the one whose framing
    (GAEC 4, GDPR) is safe to show a farmer we cannot place.
    """
    country = str((farm or {}).get("country") or "").upper()
    return rule_for_market("US" if country == "US" else "EU")


def default_rule_for(partner_id: str, farm: dict | None = None) -> str:
    """The pack this partner asks under; an unknown partner falls back to market."""
    entry = partner_index().get(partner_id)
    if entry:
        return entry["rule_id"]
    return default_rule_for_farm(farm)


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


def diagnose_ask(
    farm_id: str, partner_id: str, purpose: str, fields: list[str]
) -> tuple[str, list[str]]:
    """Why the agent has to ask. Pure code — this grants nothing.

    Returns a reason code and, where the farmer has already drawn a box for this
    purpose, the fields the partner now wants that were never inside it.
    """
    today = date.today()
    active = [
        store.as_policy(row)
        for row in store.list_where("policies", farm_id=farm_id, partner_id=partner_id, state="active")
    ]
    live = [p for p in active if p.until >= today]
    if not live:
        return ("expired_policy" if active else "new_partner"), []
    same_purpose = [p for p in live if p.purpose == purpose]
    if not same_purpose:
        return "new_purpose", []
    widest = max(same_purpose, key=lambda p: len(set(p.allowed_fields)))
    extra = sorted(set(fields) - set(widest.allowed_fields))
    return ("extra_fields" if extra else "no_match"), extra


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
    fields = list(pack.fields.keys())
    policy = None
    if not force_ask:
        policy = match_standing(pack.farm_id, pack.partner_id, pack.purpose, fields)
    draft = consent.open_draft(pack, locale=locale, request_id=request_id)
    if policy is None:
        reason_code, extra = (
            ("farmer_asked", [])
            if force_ask
            else diagnose_ask(pack.farm_id, pack.partner_id, pack.purpose, fields)
        )
        return _write_log(
            {
                "farm_id": pack.farm_id,
                "request_id": request_id,
                "pack_id": pack.id,
                "consent_id": draft.id,
                "decision": "ask_farmer",
                "reason_code": reason_code,
                "extra_fields": extra,
                "reason": "new partner, new purpose, or extra fields — farmer must give or refuse",
                "note": narrate_decision(
                    decision="ask_farmer",
                    reason_code=reason_code,
                    partner_name=draft.partner_name,
                    purpose=pack.purpose,
                    fields=fields,
                    extra_fields=extra,
                    locale=locale,
                ),
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
            "reason_code": "standing_policy",
            "extra_fields": [],
            "reason": f"standing policy {policy.id} already covers {pack.purpose}",
            "note": narrate_decision(
                decision="auto_deliver",
                reason_code="standing_policy",
                partner_name=bound.partner_name,
                purpose=pack.purpose,
                fields=fields,
                extra_fields=[],
                locale=locale,
            ),
        }
    ) | {"mode": "auto", "consent": bound, "token": token, "receipt": receipt, "policy": policy}


def tick_request(req: PartnerRequest) -> dict:
    """Run one open partner request to a decision. No chat. No Gemini on share/no-share."""
    farm = store.get("farms", req.farm_id) or {}
    locale = farm.get("locale", "en")

    def _blocked(reason: str) -> dict:
        return _write_log(
            {
                "farm_id": req.farm_id,
                "request_id": req.id,
                "decision": "need_capture",
                "reason_code": "need_capture",
                "extra_fields": [],
                "reason": reason,
                "note": narrate_decision(
                    decision="need_capture",
                    reason_code="need_capture",
                    partner_name=req.partner_name,
                    purpose=req.purpose,
                    fields=list(req.field_list),
                    extra_fields=[],
                    locale=locale,
                ),
            }
        ) | {"mode": "need_capture"}

    event = latest_confirmed(req.farm_id)
    if event is None:
        return _blocked("no confirmed field fact to compile")

    parcel_row = store.get("parcels", event.parcel_id)
    if not parcel_row:
        return _blocked("confirmed event points at an unknown field")

    rule_id = req.rule_id or default_rule_for(req.partner_id, farm)
    pack = compile_event(event, store.as_parcel(parcel_row), rule_id=rule_id)
    result = fulfill_pack(pack=pack, request_id=req.id, locale=locale)
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


def last_decision(farm_id: str) -> dict | None:
    """The most recent agent decision of any kind, so the farmer can read the
    narration behind an `ask_farmer` too — that is where the over-ask shows up."""
    rows = store.list_where("agent_log", farm_id=farm_id)
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("at", ""), reverse=True)
    return rows[0]
