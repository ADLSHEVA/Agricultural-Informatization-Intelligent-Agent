from __future__ import annotations

from datetime import datetime, timezone

from origin import store

# Local projected metres. Field 3 (Ditch 40) touches the drainage ditch at y=80.
# 5.0 m = 16.4 ft unsprayed filter strip for the US elevator check.
PARCELS = [
    ("p1", "North 80", "corn", 18.0, [(0, 0), (200, 0), (200, 70), (0, 70)], 0.0),
    ("p2", "Home 40", "soybeans", 14.5, [(200, 0), (400, 0), (400, 70), (200, 70)], 0.0),
    ("p3", "Ditch 40", "corn", 16.0, [(0, 70), (220, 70), (220, 150), (0, 150)], 5.0),
    ("p4", "South 40", "soybeans", 12.0, [(220, 70), (420, 70), (420, 160), (220, 160)], 0.0),
    ("p5", "East 35", "corn", 13.5, [(0, 150), (200, 150), (200, 240), (0, 240)], 0.0),
    ("p6", "Rye cover", "cereal rye", 12.0, [(200, 160), (400, 160), (400, 250), (200, 250)], 0.0),
]


def ensure_demo() -> None:
    farm = {
        "id": "demo-farm",
        "country": "US",
        "locale": "en",
        "display_name": "Riverside Farms (demo, Story County IA, 212 ac)",
        "default_parcel_id": "p3",
    }
    existing_farm = store.get("farms", farm["id"])
    if not existing_farm:
        store.put("farms", farm["id"], farm)
    elif not existing_farm.get("default_parcel_id"):
        existing_farm["default_parcel_id"] = "p3"
        store.put("farms", farm["id"], existing_farm)
    for pid, label, crop, area, ring, buf in PARCELS:
        if not store.get("parcels", pid):
            store.put(
                "parcels",
                pid,
                {
                "id": pid,
                "farm_id": "demo-farm",
                "lpis_id": f"US-IA-STORY-{pid.upper()}",
                "label": label,
                "crop": crop,
                "area_ha": area,
                "geom": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
                "watercourse_buffer_m": buf,
                },
            )
    if not store.list_where("requests", farm_id="demo-farm"):
        created_at = datetime.now(timezone.utc).isoformat()
        store.put(
            "requests",
            "req-demo-open",
            {
                "id": "req-demo-open",
                "farm_id": "demo-farm",
                "partner_id": "heartland-grain",
                "partner_name": "Heartland Grain LLC",
                "parcel_id": "p3",
                "purpose": "seasonal_spray_statement",
                "field_list": [
                    "parcel_id",
                    "date",
                    "product_name",
                    "rate",
                    "unit",
                    "buffer_m",
                    "buffer_ok",
                ],
                "rule_id": "elevator_spray_statement_v1",
                "status": "open",
                "created_at": created_at,
            },
        )
    seed_request = store.get("requests", "req-demo-open")
    if seed_request and not seed_request.get("parcel_id"):
        seed_request["parcel_id"] = "p3"
        store.put("requests", seed_request["id"], seed_request)
    if (
        seed_request
        and seed_request.get("status") == "open"
        and not store.list_where("agent_runs", request_id="req-demo-open")
    ):
        now = datetime.now(timezone.utc).isoformat()
        store.put(
            "agent_runs",
            "run-demo-open",
            {
                "id": "run-demo-open",
                "trace_id": "trc-demo-request",
                "request_id": "req-demo-open",
                "farm_id": "demo-farm",
                "partner_id": "heartland-grain",
                "trigger": "seeded_partner_request",
                "status": "waiting_for_farmer",
                "decision": "need_capture",
                "reason_code": "need_capture",
                "attempts": 0,
                "steps": [
                    {
                        "name": "request_received",
                        "status": "completed",
                        "detail": "Partner request persisted before execution.",
                        "at": now,
                    },
                    {
                        "name": "human_boundary",
                        "status": "waiting",
                        "detail": "A confirmed field fact is required before the request can continue.",
                        "at": now,
                    },
                ],
                "created_at": now,
                "updated_at": now,
            },
        )
