from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ConsentState = Literal["draft", "purpose-bound", "refused", "expired", "revoked", "erased"]
EventStatus = Literal["draft", "confirmed"]
Role = Literal["farmer", "partner"]


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
    state: Literal["active", "paused", "revoked"] = "active"
    created_from_consent_id: str | None = None


class ConsentCreateBody(BaseModel):
    pack_id: str
    partner_id: str
    purpose: str = "seasonal_spray_statement"


class BindBody(BaseModel):
    standing: bool = False


class DeskRequestBody(BaseModel):
    farm_id: str
    purpose: str = "seasonal_spray_statement"


class ApiError(BaseModel):
    code: str
    message: str
