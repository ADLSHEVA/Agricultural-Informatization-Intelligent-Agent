"""Gemini router — Vertex AI via ADC only.

Organisation policy forbids API keys, so there is no ``GEMINI_API_KEY`` path.
Locally run ``gcloud auth application-default login``; on Cloud Run the service
account needs ``roles/aiplatform.user``.

**Hard rule:** the model may read and phrase. It may never decide whether to
share, and it may never run the buffer check. Every function here has a
deterministic fallback, so no credentials and no network still completes the
demo loop.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from functools import lru_cache
from typing import Any

from origin.config import settings
from origin.models import FarmEventDraft, PlainTalk

log = logging.getLogger("origin.llm")

# We pass no tools, so the SDK's automatic-function-calling advisory is noise.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

_calls: dict[str, int] = {}


@lru_cache(maxsize=4)
def _vertex_client(project: str, location: str):
    from google import genai

    return genai.Client(vertexai=True, project=project, location=location)


def _client():
    """A Vertex client, or None when no project is configured."""
    s = settings()
    if not s.vertex_ready:
        return None
    try:
        return _vertex_client(s.gcp_project, s.vertex_location)
    except Exception as exc:  # missing ADC, bad project, SDK not installed
        log.warning("vertex client unavailable (%s); using deterministic fallbacks", exc)
        return None


def _budget_ok() -> bool:
    """In-process daily call cap, so a stuck loop cannot run up a bill."""
    cap = settings().llm_daily_call_cap
    if cap <= 0:
        return True
    day = date.today().isoformat()
    used = _calls.get(day, 0)
    if used >= cap:
        log.warning("daily call cap %d reached on %s; using deterministic fallback", cap, day)
        return False
    _calls[day] = used + 1
    return True


def _generate(parts: list[Any], *, label: str) -> str | None:
    """One call site for every model request. Returns None on any failure."""
    client = _client()
    if client is None or not _budget_ok():
        return None
    s = settings()
    try:
        resp = client.models.generate_content(model=s.gemini_model, contents=parts)
    except Exception as exc:
        log.warning("%s failed on %s @ %s: %s", label, s.gemini_model, s.vertex_location, exc)
        return None
    usage = getattr(resp, "usage_metadata", None)
    log.info(
        "%s model=%s location=%s prompt_tokens=%s output_tokens=%s total_tokens=%s",
        label,
        s.gemini_model,
        s.vertex_location,
        getattr(usage, "prompt_token_count", "?"),
        getattr(usage, "candidates_token_count", "?"),
        getattr(usage, "total_token_count", "?"),
    )
    return resp.text or None


def _text_part(text: str):
    from google.genai import types

    return types.Part.from_text(text=text)


def extract_event(
    *,
    note: str = "",
    parcel_hint: str = "",
    audio: bytes | None = None,
    image: bytes | None = None,
    audio_mime: str = "audio/webm",
    image_mime: str = "image/jpeg",
) -> FarmEventDraft:
    """Read voice / photo / note into a draft event. On failure return a sparse
    draft for the farmer to fix — the farmer is always the source of truth."""
    if _client() is None:
        return _heuristic(note, parcel_hint)

    from google.genai import types

    parts: list[Any] = [
        _text_part(
            "Extract one farm plant-protection event as JSON with keys: "
            "parcel_ref, type, product_name, rate, unit, buffer_m, note, confidence. "
            "type is usually plant_protection. unit default L/ha. "
            "buffer_m is unsprayed strip in metres. confidence 0-1. "
            f"Parcel hint: {parcel_hint or 'unknown'}. "
            f"Farmer note: {note or '(none)'}. "
            "Return JSON only."
        )
    ]
    if audio:
        parts.append(types.Part.from_bytes(data=audio, mime_type=audio_mime))
    if image:
        parts.append(types.Part.from_bytes(data=image, mime_type=image_mime))

    raw = _generate(parts, label="extract_event")
    if raw is None:
        return _heuristic(note, parcel_hint)
    try:
        return FarmEventDraft.model_validate(_parse_json(raw))
    except Exception:
        return _heuristic(note, parcel_hint)


def explain_consent(
    *,
    partner_name: str,
    purpose: str,
    fields: dict,
    until: str,
    reuse: bool,
    locale: str,
) -> PlainTalk:
    """Phrase the five-line consent card in the farmer's own language."""
    fallback = _plain_fallback(partner_name, purpose, fields, until, reuse, locale)
    if _client() is None:
        return fallback

    prompt = (
        f"Write a five-line farmer consent card in language/locale '{locale}'. "
        "JSON keys: who, why, what, until, reuse. Short sentences. No legal jargon. "
        f"Partner: {partner_name}. Purpose: {purpose}. Until: {until}. "
        f"Reuse allowed: {reuse}. Fields they receive: {json.dumps(fields)}. "
        "In 'what', name only those fields. Say they do NOT get yield or revenue. JSON only."
    )
    raw = _generate([_text_part(prompt)], label="explain_consent")
    if raw is None:
        return fallback
    try:
        return PlainTalk.model_validate(_parse_json(raw))
    except Exception:
        return fallback


def narrate_decision(
    *,
    decision: str,
    reason_code: str,
    partner_name: str,
    purpose: str,
    fields: list[str],
    extra_fields: list[str],
    locale: str,
) -> str:
    """Say, in the farmer's own words, what the agent just did and why.

    Called **after** the decision exists. The model is handed a verdict and
    asked to phrase it — it is never asked whether to share. A failure here
    changes nothing: the template line stands and the decision is untouched.
    """
    fallback = _narration_fallback(
        decision=decision,
        reason_code=reason_code,
        partner_name=partner_name,
        purpose=purpose,
        fields=fields,
        extra_fields=extra_fields,
        locale=locale,
    )
    if _client() is None:
        return fallback

    prompt = (
        "You are writing one short note for a farmer, in language/locale "
        f"'{locale}'. Two sentences maximum, plain words, no legal jargon, no "
        "greeting, no markdown. Do not offer advice and do not ask a question.\n"
        f"What already happened: decision={decision} ({reason_code}).\n"
        f"Partner: {partner_name}. Purpose: {purpose}.\n"
        f"Fields in the pack: {', '.join(fields) or 'none'}.\n"
        f"Fields the partner wanted that the farmer never allowed: "
        f"{', '.join(extra_fields) or 'none'}.\n"
        + (
            "Say plainly that this was sent under permission the farmer already "
            "gave, name what went, and say it did not include yield or revenue."
            if decision == "auto_deliver"
            else "Say plainly that nothing was sent and why the farmer is being asked."
        )
        + " Return the note only."
    )
    raw = _generate([_text_part(prompt)], label="narrate_decision")
    if raw is None:
        return fallback
    line = " ".join(raw.split()).strip('"').strip()
    # Truncate a rambling model rather than trusting it to be brief.
    return line[:400] or fallback


def _narration_fallback(
    *,
    decision: str,
    reason_code: str,
    partner_name: str,
    purpose: str,
    fields: list[str],
    extra_fields: list[str],
    locale: str,
) -> str:
    extra = ", ".join(extra_fields)
    shown = ", ".join(fields)
    if locale.startswith("fr"):
        if decision == "auto_deliver":
            return (
                f"Origin a envoyé à {partner_name} les champs que vous avez déjà "
                f"acceptés ({shown}). Ni rendement, ni revenu. Révoquez depuis "
                "« Qui » si c’était une erreur."
            )
        if decision == "need_capture":
            return (
                f"{partner_name} attend, mais aucun fait confirmé n’est prêt. "
                "Enregistrez la parcelle d’abord — rien n’est parti."
            )
        if reason_code == "extra_fields" and extra:
            return (
                f"{partner_name} demande maintenant aussi : {extra}. Ce n’était "
                "pas dans votre cadre, donc Origin n’a rien envoyé."
            )
        if reason_code == "new_purpose":
            return (
                f"{partner_name} demande pour une autre raison cette fois "
                f"({purpose}). Rien n’est parti de la ferme."
            )
        return (
            f"{partner_name} n’avait jamais demandé. Rien n’est parti — ouvrez "
            "la carte pour décider."
        )

    if decision == "auto_deliver":
        return (
            f"Origin sent {partner_name} the fields you already agreed to "
            f"({shown}). Not your yield or revenue. Revoke on Who if that was wrong."
        )
    if decision == "need_capture":
        return (
            f"{partner_name} is waiting, but there is no confirmed field fact to "
            "compile. Record the field first — nothing has gone out."
        )
    if reason_code == "extra_fields" and extra:
        return (
            f"{partner_name} now also wants {extra}. That was never in your box, "
            "so Origin sent nothing and is asking you."
        )
    if reason_code == "new_purpose":
        return (
            f"{partner_name} is asking for a different reason this time "
            f"({purpose}). Nothing left the farm."
        )
    return (
        f"{partner_name} has not asked before. Nothing left the farm — open the "
        "card and decide."
    )


def draft_rule_pack(
    *,
    text: str = "",
    document: bytes | None = None,
    document_mime: str = "application/pdf",
    partner_hint: str = "",
    market: str = "EU",
) -> dict:
    """Read a partner questionnaire into a **proposed** rule pack.

    The return value is a proposal, not a pack: `questionnaire.sanitize_draft`
    decides what survives, and the farmer decides whether it is ever used. With
    no client, a keyword scan keeps the screen working offline.
    """
    fallback = _questionnaire_heuristic(text, partner_hint, market)
    if _client() is None:
        return fallback

    from google.genai import types

    parts: list[Any] = [
        _text_part(
            "Read this partner questionnaire and describe, as JSON, the smallest "
            "data pack that would answer it. Keys: partner_name, purpose, "
            "fields (array of snake_case names), until, reuse (boolean), notes. "
            "`purpose` is one snake_case phrase, e.g. seasonal_spray_statement. "
            "`until` is one of: end_of_calendar_year, +Nd, or an ISO date. "
            "List every field the questionnaire actually asks for, including any "
            "you think the farmer should refuse — do not filter, that is not your "
            f"job. Market: {market}. Partner hint: {partner_hint or 'unknown'}.\n"
            f"Questionnaire:\n{text or '(see attached document)'}\n"
            "Return JSON only."
        )
    ]
    if document:
        parts.append(types.Part.from_bytes(data=document, mime_type=document_mime))

    raw = _generate(parts, label="draft_rule_pack")
    if raw is None:
        return fallback
    try:
        proposal = _parse_json(raw)
    except Exception:
        return fallback
    if not isinstance(proposal, dict) or not proposal.get("fields"):
        return fallback
    return proposal


def digest_terms(*, text: str, partner_hint: str = "", locale: str = "en") -> dict:
    """Read a partner's data terms into a plain-talk risk card.

    Reading only. The over-ask diff against what the farmer actually allowed is
    computed in `terms.py`, in code, never here.
    """
    fallback = _terms_heuristic(text, partner_hint, locale)
    if _client() is None:
        return fallback

    prompt = (
        "Read these partner data terms for a farmer and answer as JSON with keys: "
        "partner_name, resale, aggregation, third_parties (array), "
        "retention_days (integer or null), fields_claimed (array of snake_case "
        "field names), red_flags (array of short phrases), plain_summary.\n"
        "`resale` and `aggregation` are one of: yes, no, unclear. "
        "`red_flags` names anything a farmer would regret signing — resale, "
        "perpetual or irrevocable licences, no deletion route, unnamed third "
        "parties. Quote nothing; say it plainly.\n"
        f"Write `plain_summary` and every red flag in language/locale '{locale}', "
        "two sentences maximum, no legal jargon.\n"
        f"Partner hint: {partner_hint or 'unknown'}.\nTerms:\n{text}\n"
        "Return JSON only."
    )
    raw = _generate([_text_part(prompt)], label="digest_terms")
    if raw is None:
        return fallback
    try:
        digest = _parse_json(raw)
    except Exception:
        return fallback
    return digest if isinstance(digest, dict) else fallback


# Phrases that betray a field ask, in EN and FR. Used by both offline scanners —
# and they must catch `yield` and `revenue`, because the whole point of the
# sanitiser is visible only when something is actually refused.
_FIELD_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("parcel_id", ("parcel", "field id", "field number", "block", "lpis", "parcelle", "îlot")),
    ("date", ("date", "when", "day of application", "jour")),
    ("product_name", ("product", "active substance", "chemical", "pesticide", "produit", "substance")),
    ("rate", ("rate", "dose", "dosage", "litres per", "l/ha", "application rate")),
    ("unit", ("unit", "unité")),
    ("buffer_m", ("buffer", "filter strip", "watercourse", "gaec", "bande tampon", "cours d'eau")),
    ("yield", ("yield", "tonnes per hectare", "t/ha", "harvest volume", "rendement")),
    ("revenue", ("revenue", "price", "income", "turnover", "sale value", "chiffre", "revenu")),
)


def _cued_fields(text: str) -> list[str]:
    low = (text or "").lower()
    found = [name for name, cues in _FIELD_CUES if any(cue in low for cue in cues)]
    if "rate" in found and "unit" not in found:
        found.append("unit")  # a rate with no unit is not a fact
    return found


def _questionnaire_heuristic(text: str, partner_hint: str, market: str) -> dict:
    fields = _cued_fields(text) or ["parcel_id", "date", "product_name", "rate", "unit", "buffer_m"]
    low = (text or "").lower()
    purpose = "seasonal_spray_statement" if market.upper() == "US" else "seasonal_plant_protection_statement"
    if "carbon" in low or "mrv" in low:
        purpose = "carbon_practice_statement"
    elif "organic" in low or "certif" in low:
        purpose = "certification_statement"
    return {
        "partner_name": partner_hint or "New partner",
        "purpose": purpose,
        "fields": fields,
        "until": "end_of_calendar_year",
        "reuse": "reuse" in low or "share with" in low,
        "notes": "Read offline by keyword scan — no model was reachable.",
    }


def _terms_heuristic(text: str, partner_hint: str, locale: str) -> dict:
    low = (text or "").lower()
    resale = "yes" if any(w in low for w in ("resell", "re-sell", "sell", "licen", "monetis", "monetiz")) else "unclear"
    if any(w in low for w in ("will not sell", "never sell", "no resale", "not be sold")):
        resale = "no"
    aggregation = "yes" if any(w in low for w in ("aggregate", "aggregated", "anonymis", "anonymiz", "benchmark")) else "unclear"

    retention = None
    rm = re.search(r"(\d+)\s*(day|month|year|jour|mois|an)", low)
    if rm:
        span = {"day": 1, "jour": 1, "month": 30, "mois": 30, "year": 365, "an": 365}[rm.group(2)]
        retention = int(rm.group(1)) * span
    if "indefinit" in low or "perpetu" in low or "illimit" in low:
        retention = None

    flags: list[str] = []
    if resale == "yes":
        flags.append("They may sell or license your data on")
    if "perpetu" in low or "irrevocab" in low or "illimit" in low:
        flags.append("The licence they want does not end")
    if "sublicen" in low or "sous-licen" in low:
        flags.append("They can hand it to someone else")
    if not any(w in low for w in ("delete", "deletion", "erase", "supprim", "effac")):
        flags.append("No deletion route is named")
    if "third part" in low or "tiers" in low:
        flags.append("Unnamed third parties are mentioned")

    summary = (
        "Lecture hors ligne par mots-clés — aucun modèle joignable. Vérifiez vous-même."
        if locale.startswith("fr")
        else "Read offline by keyword scan — no model was reachable. Check it yourself too."
    )
    return {
        "partner_name": partner_hint or "This partner",
        "resale": resale,
        "aggregation": aggregation,
        "third_parties": [],
        "retention_days": retention,
        "fields_claimed": _cued_fields(text),
        "red_flags": flags,
        "plain_summary": summary,
    }


def _heuristic(note: str, parcel_hint: str) -> FarmEventDraft:
    text = note or ""
    parcel = parcel_hint or ""
    m = re.search(r"parcel\s*(\d+)", text, re.I)
    if m:
        parcel = m.group(1) or parcel
    rate = None
    rm = re.search(r"(\d+(?:\.\d+)?)\s*(L/?ha|l/ha)", text, re.I)
    if rm:
        rate = float(rm.group(1))
    buf = None
    bm = re.search(r"(\d+(?:\.\d+)?)\s*m(?:etre)?s?\s*(?:buffer|strip)", text, re.I)
    if not bm:
        bm = re.search(r"(?:buffer)\s*(\d+(?:\.\d+)?)", text, re.I)
    if bm:
        buf = float(bm.group(1))
    product = ""
    pm = re.search(r"product\s+([A-Za-z0-9\-]+)", text, re.I)
    if pm:
        product = pm.group(1) or ""
    return FarmEventDraft(
        parcel_ref=parcel,
        product_name=product,
        rate=rate,
        buffer_m=buf,
        note=note,
        confidence=0.35 if text else 0.1,
    )


def _plain_fallback(
    partner_name: str, purpose: str, fields: dict, until: str, reuse: bool, locale: str
) -> PlainTalk:
    shown = ", ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    if locale.startswith("fr"):
        return PlainTalk(
            who=partner_name,
            why="Déclaration phytosanitaire de la saison",
            what=f"{shown}. Pas de rendement ni de revenu.",
            until=until,
            reuse="Non" if not reuse else "Oui",
        )
    why = "This season’s spray record for the elevator"
    if "carbon" in purpose or "mrv" in purpose:
        why = "This season’s practice record for the carbon program"
    elif "plant_protection" in purpose or "coop" in partner_name.lower():
        why = "This season’s plant-protection statement"
    return PlainTalk(
        who=partner_name,
        why=why,
        what=f"{shown}. Not your yield or revenue.",
        until=until,
        reuse="No" if not reuse else "Yes",
    )


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)
