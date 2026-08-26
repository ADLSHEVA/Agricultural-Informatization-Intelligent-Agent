from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ConsentState = Literal["draft", "purpose-bound", "refused", "expired", "revoked", "erased"]
EventStatus = Literal["draft", "confirmed"]
RuleDraftState = Literal["proposed", "approved", "rejected"]
Role = Literal["farmer", "partner"]
RunStatus = Literal["queued", "running", "waiting_for_farmer", "completed", "failed"]


class PlainTalk(BaseModel):
    who: str
    why: str
    what: str
    until: str
    reuse: str


class FarmEventDraft(BaseModel):
    parcel_ref: str = ""
    type: str = "plant_protection"
    product_name: str = ""
    rate: float | None = None
    unit: str = "L/ha"
    buffer_m: float | None = None
    note: str = ""
    confidence: float = 0.0
    provenance: dict = Field(default_factory=dict)


class EventRecord(BaseModel):
    id: str
    farm_id: str
    parcel_id: str
    type: str = "plant_protection"
    time: datetime
    product_name: str = ""
    rate: float | None = None
    unit: str = "L/ha"
    buffer_m: float | None = None
    note: str = ""
    evidence_uris: list[str] = Field(default_factory=list)
    source: Literal["voice", "photo", "import", "note"] = "note"
    status: EventStatus = "draft"
    confidence: float = 0.0
    provenance: dict = Field(default_factory=dict)


class PackRecord(BaseModel):
    id: str
    farm_id: str
    event_ids: list[str]
    rule_id: str
    partner_id: str
    purpose: str
    fields: dict
    checks: dict = Field(default_factory=dict)
    created_at: datetime


class ConsentRecord(BaseModel):
    id: str
    farm_id: str
    pack_id: str
    partner_id: str
    partner_name: str
    purpose: str
    fields: list[str]
    until: date
    reuse: bool = False
    state: ConsentState = "draft"
    locale: str = "en"
    plain_talk: PlainTalk | None = None
    request_id: str | None = None


class ReceiptRecord(BaseModel):
    id: str
    farm_id: str
    consent_id: str
    pack_id: str
    partner_name: str
    # Stable grouping key for the Who page; empty on rows written before it
    # existed (the UI falls back to partner_name for those).
    partner_id: str = ""
    purpose: str = ""
    until: date | None = None
    pack_hash: str
    field_list: list[str]
    issued_at: datetime
    kind: Literal["given", "refused"] = "given"
    grey: bool = False


class TokenRecord(BaseModel):
    id: str
    consent_id: str
    farm_id: str
    partner_id: str
    expires_at: datetime
    revoked: bool = False


class PartnerRequest(BaseModel):
    id: str
    farm_id: str
    partner_id: str
    partner_name: str
    purpose: str
    field_list: list[str]
    rule_id: str = "elevator_spray_statement_v1"
    status: Literal["open", "linked", "superseded"] = "open"
    created_at: datetime


class AgentRun(BaseModel):
    """Durable execution record for one event-driven partner request.

    The trace is intentionally farmer-readable: it proves what ran in the
    background without exposing model chain-of-thought.
    """

    id: str
    trace_id: str
    request_id: str
    farm_id: str
    partner_id: str
    trigger: str = "partner_request"
    status: RunStatus = "queued"
    decision: str | None = None
    reason_code: str | None = None
    consent_id: str | None = None
    pack_id: str | None = None
    delivery_id: str | None = None
    attempts: int = 0
    queue_task: str | None = None
    model: dict = Field(default_factory=dict)
    steps: list[dict] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class Parcel(BaseModel):
    id: str
    farm_id: str
    lpis_id: str
    label: str
    crop: str
    area_ha: float
    geom: dict
    watercourse_buffer_m: float = 0.0


class Farm(BaseModel):
    id: str
    country: str
    locale: str
    display_name: str


class Principal(BaseModel):
    role: Role
    farm_id: str | None = None
    partner_id: str | None = None
    locale: str = "en"


class RuleDraft(BaseModel):
    """A rule pack proposed from a partner questionnaire. Never compiled from.

    `pack` has already been through `questionnaire.sanitize_draft`, so it holds
    only fields Origin will carry. `dropped_refused` and `dropped_unknown` record
    what the questionnaire asked for and did not get — kept so the farmer can see
    the refusal and so it is auditable afterwards.
    """

    id: str
    farm_id: str
    partner_id: str
    partner_name: str
    market: str = "EU"
    source_excerpt: str = ""
    pack: dict
    dropped_refused: list[str] = Field(default_factory=list)
    dropped_unknown: list[str] = Field(default_factory=list)
    plain_summary: str = ""
    state: RuleDraftState = "proposed"
    created_at: datetime
    decided_at: datetime | None = None


class TermsReview(BaseModel):
    """A plain-talk risk card read out of a partner's data terms.

    Everything here is a reading of their document, except `over_ask`, which is
    a deterministic diff against what the farmer has actually allowed.
    """

    id: str
    farm_id: str
    partner_name: str
    locale: str = "en"
    source_excerpt: str = ""
    resale: str = "unclear"
    aggregation: str = "unclear"
    third_parties: list[str] = Field(default_factory=list)
    retention_days: int | None = None
    fields_claimed: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    over_ask: list[str] = Field(default_factory=list)
    plain_summary: str = ""
    created_at: datetime


class EventConfirmBody(BaseModel):
    product_name: str | None = None
    rate: float | None = None
    unit: str | None = None
    buffer_m: float | None = None
    note: str | None = None
    parcel_id: str | None = None


class StandingPolicy(BaseModel):
    """Farmer-set standing share rule. The agent may auto-deliver only inside this box."""

    id: str
    farm_id: str
    partner_id: str
    purpose: str
    allowed_fields: list[str]
    until: date
    reuse: bool = False
    # expired is set lazily (agent.expire_policies_if_due) so Today stops
    # advertising a box whose time has run out.
    state: Literal["active", "paused", "revoked", "expired"] = "active"
    created_from_consent_id: str | None = None


class ConsentCreateBody(BaseModel):
    pack_id: str
    # Both are derived from the pack. Send them to assert what you think you are
    # consenting to — a mismatch is a 409, never a silent substitution.
    partner_id: str | None = None
    purpose: str | None = None


class BindBody(BaseModel):
    standing: bool = False


class DeskRequestBody(BaseModel):
    farm_id: str
    # Default: whatever the partner's own rule pack asks for. Hard-coding a US
    # purpose here would mislabel every EU request on the farmer's Today card.
    purpose: str | None = None


class TermsReviewBody(BaseModel):
    text: str
    partner_name: str | None = None


class ApiError(BaseModel):
    code: str
    message: str
