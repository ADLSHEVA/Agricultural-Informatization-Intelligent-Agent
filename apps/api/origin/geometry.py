from __future__ import annotations

from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union

from origin.models import Parcel

# Demo drainage ditch along the north edge of field 3 (metres, local projected sketch).
# US primary: ~16 ft filter strip. EU adapter (GAEC 4) reuses the same geometry.
WATERCOURSE = LineString([(0, 80), (220, 80)])
REQUIRED_BUFFER_M = 5.0


def parcel_polygon(parcel: Parcel):
    return shape(parcel.geom)


def buffer_ok(parcel: Parcel, claimed_buffer_m: float | None) -> dict:
    """Deterministic unsprayed-strip check. No LLM.

    Weekend rule: if the field meets the ditch, claimed buffer must be
    >= the field's required width (default 5 m / 16 ft).
    """
    poly = parcel_polygon(parcel)
    distance = poly.distance(WATERCOURSE)
    touches = distance < 1e-6 or poly.intersects(WATERCOURSE.buffer(0.5))
    required = parcel.watercourse_buffer_m or (REQUIRED_BUFFER_M if touches else 0.0)
    claimed = claimed_buffer_m if claimed_buffer_m is not None else 0.0
    ok = (not touches) or claimed >= required
    return {
        "buffer_ok": ok,
        "gaec4_buffer_ok": ok,
        "touches_watercourse": touches,
        "required_m": required,
        "claimed_m": claimed,
        "distance_m": round(float(distance), 2),
    }


def gaec4_ok(parcel: Parcel, claimed_buffer_m: float | None) -> dict:
    """EU adapter name. Same deterministic check as buffer_ok."""
    return buffer_ok(parcel, claimed_buffer_m)


def watercourse_geojson() -> dict:
    return mapping(WATERCOURSE)


def all_parcels_union(parcels: list[Parcel]):
    return unary_union([parcel_polygon(p) for p in parcels])
