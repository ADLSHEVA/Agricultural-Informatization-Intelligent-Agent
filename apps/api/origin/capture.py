from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args
from uuid import uuid4

from origin import blobs, store
from origin.gemini_router import extract_event
from origin.models import EventRecord, FarmEventDraft

# Which event fields may legitimately be set back to null — `rate` and
# `buffer_m` today. Read off the model so it cannot drift from it.
NULLABLE_EVENT_FIELDS = {
    name
    for name, field in EventRecord.model_fields.items()
    if type(None) in get_args(field.annotation)
}


def create_draft(
    *,
    farm_id: str,
    parcel_id: str,
    note: str = "",
    source: str = "note",
    audio: bytes | None = None,
    image: bytes | None = None,
    audio_mime: str = "audio/webm",
    image_mime: str = "image/jpeg",
) -> EventRecord:
    draft: FarmEventDraft = extract_event(
        note=note,
        parcel_hint=parcel_id,
        audio=audio,
        image=image,
        audio_mime=audio_mime,
        image_mime=image_mime,
    )
    event_id = f"evt-{uuid4().hex[:10]}"
    evidence: list[str] = []
    if audio:
        evidence.append(
            blobs.save_evidence(
                farm_id=farm_id,
                event_id=event_id,
                filename="audio.webm",
                data=audio,
                content_type=audio_mime,
            )
        )
    if image:
        evidence.append(
            blobs.save_evidence(
                farm_id=farm_id,
                event_id=event_id,
                filename="label.jpg",
                data=image,
                content_type=image_mime,
            )
        )

    parcel = draft.parcel_ref or parcel_id
    if parcel.isdigit():
        parcel = f"p{parcel}" if not parcel.startswith("p") else parcel
    if store.get("parcels", parcel) is None:
        parcel = parcel_id

    event = EventRecord(
        id=event_id,
        farm_id=farm_id,
        parcel_id=parcel,
        type=draft.type or "plant_protection",
        time=datetime.now(timezone.utc),
        product_name=draft.product_name,
        rate=draft.rate,
        unit=draft.unit or "L/ha",
        buffer_m=draft.buffer_m,
        note=draft.note or note,
        evidence_uris=evidence,
        source=source,  # type: ignore[arg-type]
        status="draft",
        confidence=draft.confidence,
        provenance=draft.provenance,
    )
    store.put("events", event.id, event.model_dump(mode="json"))
    return event


def confirm(event: EventRecord, **patch) -> EventRecord:
    """Apply the farmer's corrections. They are the source of truth, so an
    explicit null on a nullable field clears a guess the extractor got wrong.

    Callers must send only the keys the farmer actually touched
    (`exclude_unset=True`); otherwise every untouched field arrives as None and
    a correction of one number would wipe the rest.
    """
    data = event.model_dump()
    for key, value in patch.items():
        if key not in data:
            continue
        if value is None and key not in NULLABLE_EVENT_FIELDS:
            continue  # a null cannot clear a required string — keep what we have
        data[key] = value
    data["status"] = "confirmed"
    updated = EventRecord.model_validate(data)
    store.put("events", updated.id, updated.model_dump(mode="json"))
    return updated


def wipe_evidence(farm_id: str) -> None:
    blobs.wipe_evidence(farm_id)
