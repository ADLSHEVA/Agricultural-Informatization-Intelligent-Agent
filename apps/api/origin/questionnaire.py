"""Block A — a partner questionnaire becomes a *draft* rule pack.

Onboarding a partner used to mean hand-writing YAML, which meant a code change.
Now the questionnaire is read into a proposal, a deterministic sanitiser cuts the
proposal down to what Origin will ever carry, and the farmer approves or rejects.
Nothing compiles from an unapproved draft.

`sanitize_draft` is what makes the Gemini boundary real instead of aspirational:
however insistently a questionnaire asks, `yield` and `revenue` do not survive,
and neither does any field the compiler cannot produce from a field fact. The
model never sees this function's output — it cannot argue with it.

Approved packs are written to the store rather than to `rules/*.yaml`, because
Cloud Run's filesystem is read-only and an approved pack is data, not source.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.compile import BUFFER_KEYS, reload_rules
from origin.consent import until_from_rule
from origin.gemini_router import draft_rule_pack
from origin.models import RuleDraft

# Everything the compiler can actually produce from one confirmed field fact.
# A proposal asking for anything else is asking for something Origin does not have.
CARRYABLE_FIELDS = ("parcel_id", "date", "product_name", "rate", "unit", "buffer_m")

# Never carried, whoever asks and however the questionnaire words it. These are
# also written into every pack's `exclude:` list, so the compiler drops them a
# second time even if a pack is hand-edited later.
NEVER_SHARE = ("yield", "revenue")

# Exact spellings we have already seen. `_canonical_name` also folds new
# coinages by token (`delivered_lot_yield` -> `yield`) so the next Gemini run
# cannot dodge the gate by inventing another synonym.
FIELD_ALIASES = {
    "field_id": "parcel_id",
    "field_identification": "parcel_id",
    "parcel": "parcel_id",
    "block": "parcel_id",
    "product": "product_name",
    "buffer": "buffer_m",
    "application_date": "date",
    "spray_date": "date",
    "day_of_application": "date",
    "application_rate": "rate",
    "dose": "rate",
    "dosage": "rate",
    "buffer_strip_width": "buffer_m",
    "buffer_width": "buffer_m",
    "watercourse_buffer_width": "buffer_m",
    "filter_strip": "buffer_m",
    "unsprayed_strip": "buffer_m",
    "lot_yield": "yield",
    "harvest_yield": "yield",
    "crop_yield": "yield",
    "harvest_volume": "yield",
    "crop_sale_value": "revenue",
    "sale_value": "revenue",
    "income": "revenue",
    "turnover": "revenue",
}

# Which buffer check a market's pack proves compliance with.
MARKET_BUFFER_CHECK = {"US": "buffer_ok", "EU": "gaec4_buffer_ok"}

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str, default: str) -> str:
    out = _SLUG.sub("_", str(text or "").strip().lower()).strip("_")
    return out or default


def _canonical_name(name: str) -> str:
    """Fold a model-proposed field onto Origin's vocabulary, or leave it unknown."""
    raw = _SLUG.sub("_", str(name or "").strip().lower()).strip("_")
    if not raw:
        return raw
    if raw in FIELD_ALIASES:
        return FIELD_ALIASES[raw]
    if raw in CARRYABLE_FIELDS or raw in NEVER_SHARE or raw in BUFFER_KEYS:
        return raw
    toks = set(raw.split("_"))
    if "yield" in toks or "bushel" in toks or "bushels" in toks or "rendement" in toks:
        return "yield"
    if toks & {"revenue", "income", "turnover"} or ("sale" in toks and "value" in toks):
        return "revenue"
    if "buffer" in toks or "gaec" in toks or ("filter" in toks and "strip" in toks):
        return "buffer_m"
    if "parcel" in toks or "lpis" in toks:
        return "parcel_id"
    if "field" in toks and toks & {"id", "identification", "number", "block"}:
        return "parcel_id"
    if "product" in toks or "pesticide" in toks or "chemical" in toks or "substance" in toks:
        return "product_name"
    if "date" in toks:
        return "date"
    if "rate" in toks or "dose" in toks or "dosage" in toks:
        return "rate"
    if "unit" in toks:
        return "unit"
    return raw


def sanitize_draft(proposal: dict, *, market: str, partner_id: str) -> tuple[dict, list[str], list[str]]:
    """Cut a proposal down to a pack Origin will carry.

    Returns the pack, the fields refused outright, and the fields dropped as
    unknown. Order follows `CARRYABLE_FIELDS`, not the questionnaire's, so two
    partners asking for the same facts get byte-identical field lists.
    """
    asked = [_canonical_name(f) for f in (proposal.get("fields") or []) if str(f).strip()]
    asked_set = set(asked)

    refused = [f for f in NEVER_SHARE if f in asked_set]
    kept = [f for f in CARRYABLE_FIELDS if f in asked_set]
    unknown = sorted(asked_set - set(kept) - set(refused) - set(BUFFER_KEYS))

    market = market.upper() if market.upper() in MARKET_BUFFER_CHECK else "EU"
    check = MARKET_BUFFER_CHECK[market]
    # The buffer check rides along with the buffer width: a partner who wants to
    # know the strip exists gets the verdict, computed by Shapely, not claimed.
    checks = [check] if ("buffer_m" in kept or any(k in asked_set for k in BUFFER_KEYS)) else []
    if checks and "buffer_m" not in kept:
        kept.append("buffer_m")

    default_purpose = (
        "seasonal_spray_statement" if market == "US" else "seasonal_plant_protection_statement"
    )
    pack = {
        "id": f"{_slug(partner_id, 'partner')}_{_slug(proposal.get('purpose'), default_purpose)}_v1",
        "partner": partner_id,
        "partner_name": str(proposal.get("partner_name") or partner_id),
        "market": market,
        "purpose": _slug(proposal.get("purpose"), default_purpose),
        "until": _normalise_until(proposal.get("until")),
        "reuse": bool(proposal.get("reuse")),
        "fields": kept + checks,
        "exclude": list(NEVER_SHARE),
        "checks": checks,
        "origin": "questionnaire_draft",
    }
    return pack, refused, unknown


def _normalise_until(raw) -> str:
    """Keep only spellings `consent.until_from_rule` understands.

    A value we cannot parse becomes year end rather than being passed through to
    be silently misread later.
    """
    text = str(raw or "").strip()
    if text == "end_of_calendar_year" or re.fullmatch(r"\+\d+d", text):
        return text
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return "end_of_calendar_year"


def propose(
    *,
    farm_id: str,
    partner_id: str,
    market: str,
    text: str = "",
    document: bytes | None = None,
    document_mime: str = "application/pdf",
    partner_hint: str = "",
) -> RuleDraft:
    """Read a questionnaire and store the sanitised result as a proposed draft."""
    if not text.strip() and not document:
        raise HTTPException(400, {"code": "empty_questionnaire", "message": "Send text or a file"})

    proposal = draft_rule_pack(
        text=text,
        document=document,
        document_mime=document_mime,
        partner_hint=partner_hint or partner_id,
        market=market,
    )
    pack, refused, unknown = sanitize_draft(proposal, market=market, partner_id=partner_id)

    draft = RuleDraft(
        id=f"rdr-{uuid4().hex[:10]}",
        farm_id=farm_id,
        partner_id=partner_id,
        partner_name=pack["partner_name"],
        market=pack["market"],
        source_excerpt=text.strip()[:600],
        pack=pack,
        dropped_refused=refused,
        dropped_unknown=unknown,
        plain_summary=_summary(pack, refused, unknown),
        state="proposed",
        created_at=datetime.now(timezone.utc),
    )
    store.put("rule_drafts", draft.id, draft.model_dump(mode="json"))
    return draft


def _summary(pack: dict, refused: list[str], unknown: list[str]) -> str:
    lines = [
        f"{pack['partner_name']} would get {', '.join(pack['fields'])}, "
        f"for {pack['purpose'].replace('_', ' ')}, until {pack['until'].replace('_', ' ')}."
    ]
    if refused:
        lines.append(f"They asked for {', '.join(refused)}. Origin does not carry that, so it was removed.")
    if unknown:
        lines.append(f"Origin has no field for {', '.join(unknown)}, so it was left out.")
    return " ".join(lines)


def decide(draft_id: str, farm_id: str, *, approve: bool) -> RuleDraft:
    """Approve or reject a draft. Approval is the only route into `rule_packs`."""
    row = store.get("rule_drafts", draft_id)
    if not row or row.get("farm_id") != farm_id:
        raise HTTPException(404, {"code": "not_found", "message": "Draft not found"})
    draft = RuleDraft.model_validate(row)
    if draft.state != "proposed":
        raise HTTPException(409, {"code": "invalid_state", "message": f"Already {draft.state}"})

    draft.state = "approved" if approve else "rejected"
    draft.decided_at = datetime.now(timezone.utc)
    if approve:
        # Sanitise once more on the way in. The draft has been sitting in the
        # store, and a pack is only ever as trustworthy as its last check.
        pack, refused, unknown = sanitize_draft(
            draft.pack, market=draft.market, partner_id=draft.partner_id
        )
        draft.pack = pack
        # Re-sanitise is a gate on the pack, not a wipe of the audit trail:
        # the questionnaire's original asks stay visible after approval.
        draft.dropped_refused = [f for f in NEVER_SHARE if f in set(draft.dropped_refused) | set(refused)]
        draft.dropped_unknown = sorted(set(draft.dropped_unknown) | set(unknown))
        store.put("rule_packs", pack["id"], pack)
        reload_rules()
    store.put("rule_drafts", draft.id, draft.model_dump(mode="json"))
    return draft


def list_for(farm_id: str, state: str | None = None) -> list[dict]:
    rows = store.list_where("rule_drafts", farm_id=farm_id)
    if state:
        rows = [r for r in rows if r.get("state") == state]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


def preview_until(pack: dict) -> str:
    """What the pack's `until` resolves to today — shown next to the draft so the
    farmer reads a date, not a rule-pack keyword."""
    return until_from_rule(pack).isoformat()
