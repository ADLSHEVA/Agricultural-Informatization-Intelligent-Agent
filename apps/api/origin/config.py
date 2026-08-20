"""Runtime settings for the Origin API.

One object, read from ``ORIGIN_*`` environment variables. The Google SDK's own
names (``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION``) are honoured as
fallbacks so a machine already set up for Vertex needs no Origin-specific env.

Auth to Gemini is **Application Default Credentials only**. API keys are
forbidden by organisation policy, so no key is read here and none is accepted.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORIGIN_", extra="ignore")

    # --- Vertex AI (ADC only) -------------------------------------------------
    # Empty project => no client is built and every model call falls back to a
    # deterministic path. That is what keeps the demo runnable with no cloud.
    gcp_project: str = Field(
        "",
        validation_alias=AliasChoices(
            "ORIGIN_GCP_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"
        ),
    )
    vertex_location: str = Field(
        "global",
        validation_alias=AliasChoices("ORIGIN_VERTEX_LOCATION", "GOOGLE_CLOUD_LOCATION"),
    )
    gemini_model: str = "gemini-3.7-flash"
    llm_daily_call_cap: int = 200

    # --- storage --------------------------------------------------------------
    store: str = "json"  # json | firestore
    bucket: str = ""  # GCS bucket for evidence; empty => local files

    # --- auth -----------------------------------------------------------------
    firebase_project_id: str = ""
    demo_tokens: bool = True

    # --- web ------------------------------------------------------------------
    # Comma-separated. Both loopback spellings by default: the browser sends
    # whichever host the farmer typed, and a mismatch reads as a CORS failure.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def vertex_ready(self) -> bool:
        return bool(self.gcp_project)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Drop the cached Settings. Tests call this after changing the environment."""
    settings.cache_clear()
