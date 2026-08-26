"""Block B — a pasted clause becomes a risk card, not a consent.

The HTTP test that posts a resale clause against a live standing policy is the
acceptance: red flags must fire, and `over_ask` is a set difference in code,
never a model verdict.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from origin.main import app
from origin.models import StandingPolicy
from origin.seed import ensure_demo
from origin.questionnaire import canonical_name
from origin.terms import allowed_now

FARMER = {"Authorization": "Bearer demo-farmer"}
PARTNER = {"Authorization": "Bearer demo-partner"}

ALLOWED = ["parcel_id", "date", "product_name", "rate", "unit", "buffer_m"]

# An elevator data-terms paragraph that actually says the quiet parts out loud.
RESALE_TERMS = """
Heartland Grain LLC — Data Terms for Crop Year 2026

By delivering grain you grant Heartland Grain a perpetual, irrevocable licence
to resell, sublicense and otherwise monetize the following farm records, and to
share them with unnamed third parties:

- parcel / field identification
- date of each plant-protection application
- product name and application rate
- unsprayed filter strip / watercourse buffer
- yield (bushels per acre)
- revenue / crop sale value of the lot

Records are retained indefinitely. No deletion is offered.
"""


def _arm_standing(store) -> None:
    policy = StandingPolicy(
        id="pol-terms",
        farm_id="demo-farm",
        partner_id="heartland-grain",
        purpose="seasonal_spray_statement",
        allowed_fields=list(ALLOWED),
        until=date.today() + timedelta(days=120),
        reuse=False,
        state="active",
    )
    store.put("policies", policy.id, policy.model_dump(mode="json"))


def test_resale_clause_raises_flags_and_over_ask(local_store):
    ensure_demo()
    _arm_standing(local_store)
    c = TestClient(app)
    posted = c.post(
        "/v1/terms/review",
        json={"text": RESALE_TERMS, "partner_name": "Heartland Grain LLC"},
        headers=FARMER,
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["resale"] == "yes"
    assert body["red_flags"], body
    assert any("sell" in f.lower() or "license" in f.lower() or "licen" in f.lower() for f in body["red_flags"])
    assert "yield" in body["over_ask"]
    assert "revenue" in body["over_ask"]
    for kept in ALLOWED:
        assert kept not in body["over_ask"]
    assert "yield" in body["fields_claimed"]
    assert "revenue" in body["fields_claimed"]
    assert body["farm_id"] == "demo-farm"
    assert body["id"].startswith("trv-")


def test_partner_cannot_review_terms(local_store):
    ensure_demo()
    c = TestClient(app)
    r = c.post(
        "/v1/terms/review",
        json={"text": RESALE_TERMS, "partner_name": "Heartland Grain LLC"},
        headers=PARTNER,
    )
    assert r.status_code == 403


def test_empty_terms_are_rejected(local_store):
    ensure_demo()
    c = TestClient(app)
    r = c.post("/v1/terms/review", json={"text": "   "}, headers=FARMER)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_terms"


def test_over_ask_is_empty_when_the_policy_already_covers_the_ask(local_store):
    """If they only ask for what the standing policy already allows, no over-ask."""
    ensure_demo()
    _arm_standing(local_store)
    c = TestClient(app)
    posted = c.post(
        "/v1/terms/review",
        json={
            "text": (
                "Heartland Grain LLC asks only for parcel identification, the date, "
                "product name, application rate and the watercourse buffer. "
                "We will not sell this data. You may request deletion at any time. "
                "Retained 90 days."
            ),
            "partner_name": "Heartland Grain LLC",
        },
        headers=FARMER,
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["resale"] == "no"
    assert "yield" not in body["over_ask"]
    assert "revenue" not in body["over_ask"]
    for kept in ALLOWED:
        assert kept not in body["over_ask"]


def test_terms_field_coinages_use_the_same_canonical_gate():
    assert canonical_name("delivered_lot_yield") == "yield"
    assert canonical_name("crop_sale_revenue") == "revenue"
    assert canonical_name("watercourse_buffer_strip_width") == "buffer_m"


def test_unknown_partner_does_not_inherit_another_partners_allowance(local_store):
    ensure_demo()
    _arm_standing(local_store)
    allowed, matched = allowed_now("demo-farm", "Unrelated Analytics Inc")
    assert allowed == []
    assert matched is None
