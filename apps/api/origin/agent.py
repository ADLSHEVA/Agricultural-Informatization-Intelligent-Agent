"""Origin Agent — decide and deliver inside a farmer-set standing policy.

The decision is a policy match against YAML-compiled fields: strict containment,
same purpose, not past `until`. Gemini is called **after** the decision exists,
only to phrase it in the farmer's language, and a failure there changes nothing.
It never decides whether to share.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import consent, deliver, store
from origin.compile import compile_event, load_rule, partner_index, rule_for_market
from origin.gemini_router import narrate_decision
from origin.models import ConsentRecord, EventRecord, PartnerRequest, StandingPolicy

# Last resort only, for when `rules/` is empty or a partner has no pack yet: it
# stops the UI printing a bare slug. The YAML packs are the source of truth.
FALLBACK_PARTNER_NAMES = {
    "heartland-grain": "Heartland Grain LLC",
}


def partner_display(partner_id: str) -> str:
    entry = partner_index().get(partner_id)
    if entry:
        return entry["name"]
    return FALLBACK_PARTNER_NAMES.get(partner_id, partner_id)


def default_rule_for_farm(farm: dict | None) -> str:
    """Select the US pack and fail closed for unsupported/unknown markets."""
    country = str((farm or {}).get("country") or "").upper()
    if country != "US":
        raise HTTPException(
            422,
            {
                "code": "unsupported_market",
                "message": "This hackathon build supports US farms only",
            },
        )
    return rule_for_market("US")


def default_rule_for(partner_id: str, farm: dict | None = None) -> str:
    """The approved pack for a known partner; unknown partners fail closed."""
    entry = partner_index().get(partner_id)
    if entry:
        if entry.get("market") != "US":
            return default_rule_for_farm(farm)
        return entry["rule_id"]
    raise HTTPException(
        422,
        {"code": "unknown_partner", "message": "No approved US rule exists for this partner"},
    )


def activate_standing(bound: ConsentRecord) -> StandingPolicy:
    existing = store.list_where("policies", created_from_consent_id=bound.id)
    if existing:
        return store.as_policy(existing[0])
    policy = StandingPolicy(
        id=f"pol-{bound.id.removeprefix('cns-')}",
        farm_id=bound.farm_id,
        partner_id=bound.partner_id,
        purpose=bound.purpose,
        allowed_fields=list(bound.fields),
        until=bound.until,
        reuse=bound.reuse,
        state="active",
        created_from_consent_id=bound.id,
    )
    payload = policy.model_dump(mode="json")
    if not store.put_if_absent("policies", policy.id, payload):
        return store.as_policy(store.get("policies", policy.id) or payload)
    return policy


def revoke_standing_for(consent: ConsentRecord) -> None:
    """Revoking current access also closes the matching automation boundary."""
    for row in store.list_where(
        "policies",
        farm_id=consent.farm_id,
        partner_id=consent.partner_id,
    ):
        if row.get("purpose") != consent.purpose:
            continue
        if row.get("state") in {"active", "paused"}:
            row["state"] = "revoked"
            store.put("policies", row["id"], row)


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


def expire_policies_if_due() -> None:
    """Lazy expiry for standing policies — the mirror of consent.expire_if_due.

    Without it Today kept advertising boxes whose time had run out: the agent's
    own matching ignores them by date, but the farmer-visible list never moved.
    """
    today = date.today()
    for row in store.list_where("policies", state="active"):
        try:
            until = date.fromisoformat(str(row.get("until") or ""))
        except ValueError:
            continue
        if until < today:
            row["state"] = "expired"
            store.put("policies", row["id"], row)


def latest_confirmed(farm_id: str, parcel_id: str) -> EventRecord | None:
    rows = store.list_where("events", farm_id=farm_id, status="confirmed")
    rows = [row for row in rows if row.get("parcel_id") == parcel_id]
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
) -> dict:
    """Compile is already done. Auto-bind if a standing policy covers the pack."""
    fields = list(pack.fields.keys())
    policy = match_standing(pack.farm_id, pack.partner_id, pack.purpose, fields)
    draft = consent.open_draft(pack, locale=locale, request_id=request_id)
    if policy is None:
        reason_code, extra = diagnose_ask(pack.farm_id, pack.partner_id, pack.purpose, fields)
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

    # A newly compiled consent can never outlive the standing box that made it
    # automatic, even when a questionnaire expresses its expiry as +Nd.
    if draft.until > policy.until:
        draft.until = policy.until
        store.put("consents", draft.id, draft.model_dump(mode="json"))
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


def _link(request_id: str) -> None:
    row = store.get("requests", request_id)
    if row:
        row["status"] = "linked"
        store.put("requests", request_id, row)


def tick_request(req: PartnerRequest, *, event_id: str | None = None) -> dict:
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

    parcel_id = req.parcel_id or str(farm.get("default_parcel_id") or "")
    if not parcel_id:
        return _blocked("partner request does not identify a field")
    if event_id:
        event_row = store.get("events", event_id)
        event = (
            store.as_event(event_row)
            if event_row
            and event_row.get("farm_id") == req.farm_id
            and event_row.get("parcel_id") == parcel_id
            and event_row.get("status") == "confirmed"
            else None
        )
    else:
        event = latest_confirmed(req.farm_id, parcel_id)
    if event is None:
        return _blocked("no confirmed field fact to compile")

    parcel_row = store.get("parcels", event.parcel_id)
    if not parcel_row:
        return _blocked("confirmed event points at an unknown field")

    # Resolve the partner's active approved rule at execution time. A request
    # opened before questionnaire approval must not stay pinned to seed YAML.
    rule_id = default_rule_for(req.partner_id, farm)
    active_rule = load_rule(rule_id)
    if req.rule_id != rule_id or req.field_list != list(active_rule["fields"]):
        req.rule_id = rule_id
        req.field_list = list(active_rule["fields"])
        store.put("requests", req.id, req.model_dump(mode="json"))

    # A card for exactly this fact may already be waiting on the farmer. Reuse
    # it — a second ask must not stack another pack and draft in the wallet.
    pending = consent.find_open_draft(
        req.farm_id, req.partner_id, req.purpose, event.id, req.field_list
    )
    if pending is not None:
        _link(req.id)
        return _write_log(
            {
                "farm_id": req.farm_id,
                "request_id": req.id,
                "pack_id": pending.pack_id,
                "consent_id": pending.id,
                "decision": "ask_farmer",
                "reason_code": "pending_decision",
                "extra_fields": [],
                "reason": f"a card for this fact is already waiting ({pending.id})",
                "note": narrate_decision(
                    decision="ask_farmer",
                    reason_code="pending_decision",
                    partner_name=req.partner_name,
                    purpose=req.purpose,
                    fields=list(pending.fields),
                    extra_fields=[],
                    locale=locale,
                ),
            }
        ) | {"mode": "ask", "consent": pending}

    # A live file compiled from this same event may already cover the ask.
    # Re-delivering would bind an identical consent, token and receipt.
    live = deliver.find_live_consent(
        req.farm_id, req.partner_id, req.purpose, event.id, req.field_list
    )
    if live is not None:
        existing, pack_row, token = live
        _link(req.id)
        return _write_log(
            {
                "farm_id": req.farm_id,
                "request_id": req.id,
                "pack_id": existing.pack_id,
                "consent_id": existing.id,
                "decision": "auto_deliver",
                "reason_code": "already_live",
                "extra_fields": [],
                "reason": f"the current file ({existing.id}) already covers this exact fact",
                "note": narrate_decision(
                    decision="auto_deliver",
                    reason_code="already_live",
                    partner_name=req.partner_name,
                    purpose=req.purpose,
                    fields=list(existing.fields),
                    extra_fields=[],
                    locale=locale,
                ),
            }
        ) | {"mode": "auto", "consent": existing}

    pack = compile_event(
        event,
        store.as_parcel(parcel_row),
        rule_id=rule_id,
        requested_fields=req.field_list,
        purpose=req.purpose,
        idempotency_key=(
            f"{req.id}:{event.id}:{rule_id}:{req.purpose}:"
            f"{','.join(sorted(req.field_list))}"
        ),
    )
    result = fulfill_pack(pack=pack, request_id=req.id, locale=locale)
    # A consent card is a durable checkpoint and may leave the request linked.
    # Auto delivery becomes terminal only after the destination succeeds.
    if result.get("mode") == "ask":
        _link(req.id)
    return result


def tick_farm(farm_id: str) -> list[dict]:
    actions = []
    for row in store.list_where("requests", farm_id=farm_id, status="open"):
        actions.append(tick_request(store.as_request(row)))
    return actions


def last_auto(farm_id: str) -> dict | None:
    rows = store.list_where("agent_log", farm_id=farm_id)
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("at", ""), reverse=True)
    latest = rows[0]
    if latest.get("decision") != "auto_deliver":
        return None
    try:
        happened = datetime.fromisoformat(str(latest.get("at") or ""))
    except ValueError:
        return None
    return latest if datetime.now(timezone.utc) - happened <= timedelta(minutes=10) else None


def last_decision(farm_id: str) -> dict | None:
    """The most recent agent decision of any kind, so the farmer can read the
    narration behind an `ask_farmer` too — that is where the over-ask shows up."""
    rows = store.list_where("agent_log", farm_id=farm_id)
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("at", ""), reverse=True)
    return rows[0]
