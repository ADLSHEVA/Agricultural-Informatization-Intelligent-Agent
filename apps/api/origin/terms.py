"""Block B — a partner's data terms become a plain-talk risk card.

The farmer pastes the clause they were sent. Gemini reads it; nothing here trusts
that reading with a decision. The one number that matters — what the partner
claims versus what the farmer has actually allowed — is a set difference computed
in code against live `StandingPolicy` rows, so it cannot be talked around.

Reviewing is not consenting. Nothing in this module grants, revokes, or delivers.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from origin import store
from origin.compile import BUFFER_KEYS
from origin.gemini_router import digest_terms
from origin.models import TermsReview
from origin.questionnaire import NEVER_SHARE, canonical_name

# Longest retention Origin will call reasonable without comment. A season plus a
# compliance year: past this the farmer is being asked for an archive, not a
# statement.
RETENTION_SOFT_CAP_DAYS = 730


def allowed_now(farm_id: str, partner_name: str) -> tuple[list[str], str | None]:
    """What this farm has actually allowed, and which partner the name resolved to.

    Matches a partner by display name because that is all the farmer has when
    pasting terms out of an email — there is no partner token in this flow. With
    An unmatched name gets no allowance. Guessing the union of unrelated
    partners would under-report an over-ask.
    """
    today = date.today()
    live = [
        store.as_policy(row)
        for row in store.list_where("policies", farm_id=farm_id, state="active")
    ]
    live = [p for p in live if p.until >= today]
    if not live:
        return [], None

    wanted = partner_name.strip().lower()
    named = [p for p in live if _partner_label(p.partner_id).lower() == wanted]
    if named:
        allowed: set[str] = set()
        for policy in named:
            allowed |= set(policy.allowed_fields)
        return sorted(allowed), named[0].partner_id

    return [], None


def _partner_label(partner_id: str) -> str:
    # Imported here, not at module scope: `agent` imports the compile layer, and
    # this module is imported from it in turn once the endpoints are wired.
    from origin.agent import partner_display

    return partner_display(partner_id)


def review(*, farm_id: str, text: str, partner_hint: str = "", locale: str = "en") -> TermsReview:
    """Read a clause, then diff it against what the farmer already allowed."""
    if not text.strip():
        raise HTTPException(400, {"code": "empty_terms", "message": "Paste the clause first"})

    digest = digest_terms(text=text, partner_hint=partner_hint, locale=locale)
    partner_name = str(digest.get("partner_name") or partner_hint or "This partner").strip()

    claimed_raw = [
        str(f).strip().lower() for f in (digest.get("fields_claimed") or []) if str(f).strip()
    ]
    claimed = sorted({canonical_name(name) for name in claimed_raw})
    allowed, _matched = allowed_now(farm_id, partner_name)
    # The whole point of the card: fields they claim that no live policy covers.
    # Buffer check keys are Origin's own compliance verdicts, never a farmer fact,
    # so they do not count as an over-ask.
    over_ask = [f for f in claimed if f not in set(allowed) and f not in set(BUFFER_KEYS)]

    red_flags = [str(f).strip() for f in (digest.get("red_flags") or []) if str(f).strip()]
    red_flags += _code_flags(claimed, over_ask, digest, locale)

    record = TermsReview(
        id=f"trv-{uuid4().hex[:10]}",
        farm_id=farm_id,
        partner_name=partner_name,
        locale=locale,
        source_excerpt=text.strip()[:600],
        resale=_tri(digest.get("resale")),
        aggregation=_tri(digest.get("aggregation")),
        third_parties=[
            str(t).strip() for t in (digest.get("third_parties") or []) if str(t).strip()
        ],
        retention_days=_retention(digest.get("retention_days")),
        fields_claimed=claimed,
        red_flags=_dedupe(red_flags),
        over_ask=over_ask,
        plain_summary=str(digest.get("plain_summary") or "").strip(),
        created_at=datetime.now(timezone.utc),
    )
    store.put("terms_reviews", record.id, record.model_dump(mode="json"))
    return record


def _code_flags(claimed: list[str], over_ask: list[str], digest: dict, locale: str) -> list[str]:
    """Flags Origin raises itself, whatever the model said.

    These are set facts about the clause, not readings of it, so they are computed
    here rather than asked for in the prompt.
    """
    fr = locale.startswith("fr")
    flags: list[str] = []

    refused = [f for f in NEVER_SHARE if f in set(claimed)]
    if refused:
        joined = ", ".join(refused)
        flags.append(
            f"Ils demandent {joined} — Origin ne transporte jamais cela"
            if fr
            else f"They ask for {joined} — Origin never carries that"
        )
    if over_ask:
        joined = ", ".join(over_ask)
        flags.append(
            f"Au-delà de ce que vous avez autorisé : {joined}"
            if fr
            else f"Beyond what you have allowed: {joined}"
        )
    retention = _retention(digest.get("retention_days"))
    if retention is None:
        flags.append(
            "Aucune durée de conservation n’est indiquée" if fr else "No retention period is stated"
        )
    elif retention > RETENTION_SOFT_CAP_DAYS:
        years = round(retention / 365, 1)
        flags.append(
            f"Ils gardent vos données {years} ans"
            if fr
            else f"They keep your data for {years} years"
        )
    return flags


def _tri(value) -> str:
    """`yes` / `no` / `unclear`. Anything else reads as unclear — a model that
    invents a fourth answer must not become a fourth meaning."""
    text = str(value or "").strip().lower()
    return text if text in {"yes", "no", "unclear"} else "unclear"


def _retention(value) -> int | None:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def list_for(farm_id: str) -> list[dict]:
    rows = store.list_where("terms_reviews", farm_id=farm_id)
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows
