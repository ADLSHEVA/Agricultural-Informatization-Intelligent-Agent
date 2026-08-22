from __future__ import annotations

from fastapi import Header, HTTPException

from origin.config import settings
from origin.models import Principal

# Weekend demo tokens. Firebase JWT replaces this when credentials exist.
# ORIGIN_DEMO_TOKENS=false kills this path entirely (no other auth exists yet).
DEMO = {
    "demo-farmer": Principal(role="farmer", farm_id="demo-farm", locale="en"),
    "demo-partner": Principal(
        role="partner", partner_id="heartland-grain", farm_id="demo-farm", locale="en"
    ),
}


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, {"code": "unauthorized", "message": "Missing bearer token"})
    token = authorization.split(" ", 1)[1].strip()
    who = DEMO.get(token) if settings().demo_tokens else None
    if who is None:
        raise HTTPException(401, {"code": "unauthorized", "message": "Unknown token"})
    return who


def farmer_only(who: Principal) -> Principal:
    if who.role != "farmer" or not who.farm_id:
        raise HTTPException(403, {"code": "forbidden", "message": "Farmer token required"})
    return who


def partner_only(who: Principal) -> Principal:
    if who.role != "partner" or not who.partner_id:
        raise HTTPException(403, {"code": "forbidden", "message": "Partner token required"})
    return who
