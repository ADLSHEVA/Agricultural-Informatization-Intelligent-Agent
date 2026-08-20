from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from uuid import uuid4

from origin import store
from origin.gemini_router import extract_event
from origin.models import EventRecord, FarmEventDraft
from origin.store import DATA_DIR

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
    ev_dir = DATA_DIR / "evidence" / farm_id / event_id
    if audio:
        ev_dir.mkdir(parents=True, exist_ok=True)
        path = ev_dir / "audio.webm"
        path.write_bytes(audio)
        evidence.append(str(path))
    if image:
        ev_dir.mkdir(parents=True, exist_ok=True)
        path = ev_dir / "label.jpg"
        path.write_bytes(image)
        evidence.append(str(path))

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
    root = DATA_DIR / "evidence" / farm_id
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file():
            path.unlink()
