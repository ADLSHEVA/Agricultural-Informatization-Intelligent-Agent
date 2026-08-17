from __future__ import annotations

import json
import os
import re
from typing import Any

from origin.models import FarmEventDraft, PlainTalk

MODEL = "gemini-2.5-flash-lite"


def _client():
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    from google import genai

    return genai.Client(api_key=key)


def extract_event(
    *,
    note: str = "",
    parcel_hint: str = "",
    audio: bytes | None = None,
    image: bytes | None = None,
    audio_mime: str = "audio/webm",
    image_mime: str = "image/jpeg",
) -> FarmEventDraft:
    """Flash-Lite only. On failure return a sparse draft for the farmer to fix."""
    client = _client()
    if client is None:
        return _heuristic(note, parcel_hint)

    from google.genai import types

    parts: list[Any] = [
        types.Part.from_text(
            text=(
                "Extract one farm plant-protection event as JSON with keys: "
                "parcel_ref, type, product_name, rate, unit, buffer_m, note, confidence. "
                "type is usually plant_protection. unit default L/ha. "
                "buffer_m is unsprayed strip in metres. confidence 0-1. "
                f"Parcel hint: {parcel_hint or 'unknown'}. "
                f"Farmer note: {note or '(none)'}. "
                "Return JSON only."
            )
        )
    ]
    if audio:
        parts.append(types.Part.from_bytes(data=audio, mime_type=audio_mime))
    if image:
        parts.append(types.Part.from_bytes(data=image, mime_type=image_mime))
    try:
        resp = client.models.generate_content(model=MODEL, contents=parts)
        data = _parse_json(resp.text or "")
        return FarmEventDraft.model_validate(data)
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
    client = _client()
    fallback = _plain_fallback(partner_name, purpose, fields, until, reuse, locale)
    if client is None:
        return fallback
    from google.genai import types

    prompt = (
        f"Write a five-line farmer consent card in language/locale '{locale}'. "
        "JSON keys: who, why, what, until, reuse. Short sentences. No legal jargon. "
        f"Partner: {partner_name}. Purpose: {purpose}. Until: {until}. "
        f"Reuse allowed: {reuse}. Fields they receive: {json.dumps(fields)}. "
        "In 'what', name only those fields. Say they do NOT get yield or revenue. JSON only."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=[types.Part.from_text(text=prompt)]
        )
        return PlainTalk.model_validate(_parse_json(resp.text or ""))
    except Exception:
        return fallback


def _heuristic(note: str, parcel_hint: str) -> FarmEventDraft:
    text = note or ""
    parcel = parcel_hint or ""
    m = re.search(r"parcel\s*(\d+)|(\d+)\s*(?:号地|号田)", text, re.I)
    if m:
        parcel = m.group(1) or m.group(2) or parcel
    rate = None
    rm = re.search(r"(\d+(?:\.\d+)?)\s*(L/?ha|l/ha|升)", text, re.I)
    if rm:
        rate = float(rm.group(1))
    buf = None
    bm = re.search(r"(\d+(?:\.\d+)?)\s*m(?:etre)?s?\s*(?:buffer|strip|河边|缓冲)", text, re.I)
    if not bm:
        bm = re.search(r"(?:buffer|河边|留了)\s*(\d+(?:\.\d+)?)", text, re.I)
    if bm:
        buf = float(bm.group(1))
    product = ""
    pm = re.search(r"product\s+([A-Za-z0-9\-]+)|产品\s*([A-Za-z0-9\-]+)", text, re.I)
    if pm:
        product = pm.group(1) or pm.group(2) or ""
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
