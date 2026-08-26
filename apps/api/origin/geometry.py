from __future__ import annotations

from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union

from origin.models import Parcel

# Demo drainage ditch along the north edge of field 3 (metres, local projected sketch).
# US demo: 5 m / 16.4 ft filter strip.
# SINGLE-FARM ASSUMPTION: one module-level watercourse serves the seeded demo
# farm only. A second farm needs per-farm watercourses on the parcel/farm record.
WATERCOURSE = LineString([(0, 80), (220, 80)])
REQUIRED_BUFFER_M = 5.0

# A field "meets" the ditch only if it shares real frontage with it. Tolerance
# absorbs sketch imprecision; the minimum length stops a single corner point
# from counting — field 4 starts exactly where the ditch ends, and a shared
# corner is not a bank you can leave a filter strip on.
TOUCH_TOL_M = 0.5
MIN_FRONTAGE_M = 1.0


def parcel_polygon(parcel: Parcel):
    return shape(parcel.geom)


def buffer_ok(parcel: Parcel, claimed_buffer_m: float | None) -> dict:
    """Deterministic unsprayed-strip check. No LLM.

    Weekend rule: if the field meets the ditch, claimed buffer must be
    >= the field's required width (default 5 m / 16.4 ft).
    """
    poly = parcel_polygon(parcel)
    distance = poly.distance(WATERCOURSE)
    frontage = poly.buffer(TOUCH_TOL_M).intersection(WATERCOURSE).length
    touches = frontage >= MIN_FRONTAGE_M
    recorded = parcel.watercourse_buffer_m
    required = recorded if recorded > 0 else (REQUIRED_BUFFER_M if touches else 0.0)
    claimed = claimed_buffer_m if claimed_buffer_m is not None else 0.0
    ok = (not touches) or claimed >= required
    return {
        "buffer_ok": ok,
        "touches_watercourse": touches,
        "required_m": required,
        "claimed_m": claimed,
        "distance_m": round(float(distance), 2),
        "frontage_m": round(float(frontage), 2),
    }


def watercourse_geojson() -> dict:
    return mapping(WATERCOURSE)


def all_parcels_union(parcels: list[Parcel]):
    return unary_union([parcel_polygon(p) for p in parcels])
