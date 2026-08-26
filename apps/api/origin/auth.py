from __future__ import annotations

from functools import lru_cache

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


@lru_cache(maxsize=1)
def _firebase_app():
    """Initialize Firebase Admin only when production ID tokens are enabled."""
    import firebase_admin

    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(
            options={"projectId": settings().firebase_project_id}
        )


def _firebase_principal(token: str) -> Principal | None:
    if not settings().firebase_project_id:
        return None
    try:
        from firebase_admin import auth

        decoded = auth.verify_id_token(token, app=_firebase_app(), check_revoked=True)
    except Exception:
        return None
    role = str(decoded.get("role") or "")
    if role not in {"farmer", "partner"}:
        return None
    return Principal(
        role=role,
        farm_id=decoded.get("farm_id"),
        partner_id=decoded.get("partner_id"),
        locale=str(decoded.get("locale") or "en"),
    )


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, {"code": "unauthorized", "message": "Missing bearer token"})
    token = authorization.split(" ", 1)[1].strip()
    who = DEMO.get(token) if settings().demo_tokens else None
    if who is None:
        who = _firebase_principal(token)
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


def _verified_worker_claims(token: str, audience: str) -> dict:
    """Verify the Google-signed identity attached by Cloud Tasks."""
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)


def verify_worker_oidc(authorization: str | None) -> None:
    """Require the configured task service account in cloud deployments.

    The private HMAC header remains a second independent check in the route.
    Local development leaves this off explicitly.
    """
    cfg = settings()
    if not cfg.require_worker_oidc:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(403, {"code": "forbidden", "message": "Worker identity required"})
    token = authorization.split(" ", 1)[1].strip()
    audience = cfg.api_base_url.rstrip("/")
    if not audience or not cfg.task_service_account:
        raise HTTPException(503, {"code": "worker_auth_misconfigured", "message": "Worker identity is not configured"})
    try:
        claims = _verified_worker_claims(token, audience)
    except Exception:
        raise HTTPException(403, {"code": "forbidden", "message": "Invalid worker identity"}) from None
    email = str(claims.get("email") or "")
    verified = claims.get("email_verified")
    if email != cfg.task_service_account or verified not in {True, "true"}:
        raise HTTPException(403, {"code": "forbidden", "message": "Wrong worker identity"})
