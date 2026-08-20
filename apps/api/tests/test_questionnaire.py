"""Block A — a questionnaire becomes a draft pack the farmer must approve.

The HTTP test that posts a yield-and-revenue elevator form is the D6 evidence:
the model (or the offline scanner) may *read* those asks; the sanitiser is what
stops them ever becoming a field Origin will compile.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from origin.compile import compile_event, load_rule, partner_index, rule_for_market
from origin.main import app
from origin.models import EventRecord, Parcel
from origin.questionnaire import NEVER_SHARE, sanitize_draft
from origin.seed import PARCELS, ensure_demo

FARMER = {"Authorization": "Bearer demo-farmer"}
PARTNER = {"Authorization": "Bearer demo-partner"}

# A real-looking US elevator intake. The words "yield" and "revenue" are the
# payload — the offline scanner must see them so the sanitiser has something to
# refuse. Without those two words this test would pass even if the gate was gone.
ELEVATOR_QUESTIONNAIRE = """
HEARTLAND GRAIN LLC
2026 Crop Year Delivery Questionnaire — Riverside Farms

To issue this season's spray statement and receive your lot, please supply:

1. Parcel / field identification
2. Date of each plant-protection application
3. Product name and application rate (L/ha)
4. Width of the unsprayed filter strip at the watercourse (buffer)
5. Yield for the delivered lot (bushels per acre / tonnes per hectare)
6. Revenue / crop sale value of the lot

By returning this form you authorise Heartland Grain to retain the above
for the crop year.
"""


def _parcel3() -> Parcel:
    _, label, crop, area, ring, buf = next(p for p in PARCELS if p[0] == "p3")
    return Parcel(
        id="p3",
        farm_id="demo-farm",
        lpis_id="x",
        label=label,
        crop=crop,
        area_ha=area,
        geom={"type": "Polygon", "coordinates": [ring + [ring[0]]]},
        watercourse_buffer_m=buf,
    )


def test_sanitize_draft_drops_yield_and_revenue():
    pack, refused, unknown = sanitize_draft(
        {
            "fields": ["parcel_id", "yield", "revenue", "soil_n", "product_name"],
            "purpose": "seasonal_spray_statement",
            "until": "end_of_calendar_year",
            "reuse": False,
        },
        market="US",
        partner_id="heartland-grain",
    )
    assert "yield" not in pack["fields"]
    assert "revenue" not in pack["fields"]
    assert refused == ["yield", "revenue"]
    assert "soil_n" in unknown
    assert "parcel_id" in pack["fields"]
    assert "product_name" in pack["fields"]
    assert pack["exclude"] == list(NEVER_SHARE)
    assert pack["market"] == "US"


def test_elevator_questionnaire_cannot_ask_yield_or_revenue(local_store):
    """D6 in the wire: POST the form, yield and revenue must not survive."""
    ensure_demo()
    c = TestClient(app)
    posted = c.post(
        "/v1/desk/questionnaires",
        data={"farm_id": "demo-farm", "text": ELEVATOR_QUESTIONNAIRE},
        headers=PARTNER,
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    fields = body["pack"]["fields"]
    assert "yield" not in fields
    assert "revenue" not in fields
    assert "yield" in body["refused_fields"]
    assert "revenue" in body["refused_fields"]
    assert body["state"] == "proposed"
    assert body["farm_id"] == "demo-farm"
    assert body["partner_id"] == "heartland-grain"

    listed = c.get("/v1/rule-drafts", headers=FARMER)
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == body["id"] for row in listed.json())


def test_farmer_cannot_post_a_questionnaire(local_store):
    ensure_demo()
    c = TestClient(app)
    r = c.post(
        "/v1/desk/questionnaires",
        data={"farm_id": "demo-farm", "text": ELEVATOR_QUESTIONNAIRE},
        headers=FARMER,
    )
    assert r.status_code == 403


def test_empty_questionnaire_is_rejected(local_store):
    ensure_demo()
    c = TestClient(app)
    r = c.post(
        "/v1/desk/questionnaires",
        data={"farm_id": "demo-farm", "text": "   "},
        headers=PARTNER,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_questionnaire"


def test_approve_makes_the_pack_compilable(local_store):
    """Without the store overlay, approve writes a pack nobody can load."""
    ensure_demo()
    c = TestClient(app)
    posted = c.post(
        "/v1/desk/questionnaires",
        data={"farm_id": "demo-farm", "text": ELEVATOR_QUESTIONNAIRE},
        headers=PARTNER,
    )
    assert posted.status_code == 200, posted.text
    draft_id = posted.json()["id"]

    partner_forbidden = c.post(f"/v1/rule-drafts/{draft_id}/approve", headers=PARTNER)
    assert partner_forbidden.status_code == 403

    approved = c.post(f"/v1/rule-drafts/{draft_id}/approve", headers=FARMER)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["state"] == "approved"
    assert "yield" in body["refused_fields"]
    rule_id = body["pack"]["id"]

    loaded = load_rule(rule_id)
    assert loaded["id"] == rule_id
    assert loaded["origin"] == "questionnaire_draft"
    assert "yield" not in loaded["fields"]
    assert partner_index()["heartland-grain"]["rule_id"] == rule_id
    assert rule_for_market("US") == rule_id

    event = EventRecord(
        id="e-q",
        farm_id="demo-farm",
        parcel_id="p3",
        time=datetime.now(timezone.utc),
        product_name="X",
        rate=1.2,
        buffer_m=5,
        status="confirmed",
    )
    pack = compile_event(event, _parcel3(), rule_id=rule_id)
    assert "yield" not in pack.fields
    assert "revenue" not in pack.fields
    assert pack.rule_id == rule_id
    assert pack.fields["product_name"] == "X"
    assert pack.fields["buffer_ok"] is True

    again = c.post(f"/v1/rule-drafts/{draft_id}/approve", headers=FARMER)
    assert again.status_code == 409


def test_reject_is_final_and_does_not_install_a_pack(local_store):
    ensure_demo()
    c = TestClient(app)
    posted = c.post(
        "/v1/desk/questionnaires",
        data={"farm_id": "demo-farm", "text": ELEVATOR_QUESTIONNAIRE},
        headers=PARTNER,
    )
    draft_id = posted.json()["id"]
    rule_id = posted.json()["pack"]["id"]

    rejected = c.post(f"/v1/rule-drafts/{draft_id}/reject", headers=FARMER)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["state"] == "rejected"

    assert partner_index()["heartland-grain"]["rule_id"] == "elevator_spray_statement_v1"
    # Unknown id falls back to the shipped US pack, not to a ghost store pack.
    assert load_rule(rule_id)["id"] == "elevator_spray_statement_v1"

    again = c.post(f"/v1/rule-drafts/{draft_id}/approve", headers=FARMER)
    assert again.status_code == 409


def test_store_pack_overrides_yaml_of_the_same_id(local_store):
    local_store.put(
        "rule_packs",
        "elevator_spray_statement_v1",
        {
            "id": "elevator_spray_statement_v1",
            "partner": "heartland-grain",
            "partner_name": "Heartland Grain LLC",
            "market": "US",
            "purpose": "seasonal_spray_statement",
            "fields": ["parcel_id", "date", "product_name"],
            "exclude": ["yield", "revenue"],
            "checks": [],
            "origin": "questionnaire_draft",
        },
    )
    pack = load_rule("elevator_spray_statement_v1")
    assert pack["fields"] == ["parcel_id", "date", "product_name"]
    assert pack["origin"] == "questionnaire_draft"


def test_new_partner_pack_does_not_steal_the_market_default(local_store):
    local_store.put(
        "rule_packs",
        "midwest_mill_residue_v1",
        {
            "id": "midwest_mill_residue_v1",
            "partner": "midwest-mill",
            "partner_name": "Midwest Mill",
            "market": "US",
            "purpose": "residue_statement",
            "fields": ["parcel_id", "date", "product_name"],
            "exclude": ["yield", "revenue"],
            "checks": [],
            "origin": "questionnaire_draft",
        },
    )
    assert rule_for_market("US") == "elevator_spray_statement_v1"
    assert partner_index()["midwest-mill"]["rule_id"] == "midwest_mill_residue_v1"
    assert partner_index()["heartland-grain"]["rule_id"] == "elevator_spray_statement_v1"
