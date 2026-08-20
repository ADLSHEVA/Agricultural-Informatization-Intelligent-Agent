"""Rule packs as the source of truth, and the no-credentials guarantee.

The last test is the one that matters most on demo day: with no project
configured, nothing reaches Vertex and every model call takes a deterministic
path. If it ever fails, the Sunday loop depends on a network call.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from origin import agent, capture
from origin.compile import load_rule, partner_index, rule_for_market
from origin.consent import until_from_rule, year_end
from origin.main import app
from origin.models import EventRecord
from origin.seed import ensure_demo


# --- rule packs drive partner and market selection ---------------------------


def test_partner_index_comes_from_yaml(local_store):
    index = partner_index()
    assert index["heartland-grain"] == {
        "name": "Heartland Grain LLC",
        "rule_id": "elevator_spray_statement_v1",
        "market": "US",
    }
    assert index["loire-cereals-coop"]["market"] == "EU"


def test_market_picks_the_pack(local_store):
    assert rule_for_market("US") == "elevator_spray_statement_v1"
    assert rule_for_market("EU") == "coop_ppp_statement_v1"


def test_farm_country_picks_the_pack(local_store):
    assert agent.default_rule_for_farm({"country": "US"}) == "elevator_spray_statement_v1"
    assert agent.default_rule_for_farm({"country": "FR"}) == "coop_ppp_statement_v1"
    # An unplaceable farm reads as EU rather than being handed the US pack.
    assert agent.default_rule_for_farm(None) == "coop_ppp_statement_v1"


def test_unknown_partner_falls_back_to_the_farms_market(local_store):
    assert agent.default_rule_for("nobody-ltd", {"country": "FR"}) == "coop_ppp_statement_v1"
    assert agent.partner_display("nobody-ltd") == "nobody-ltd"


def test_load_rule_survives_a_version_bump(local_store):
    """Packs are found by their `id`, not by a filename guessed from it."""
    assert load_rule("coop_ppp_statement_v1")["partner"] == "loire-cereals-coop"
    assert load_rule("does_not_exist_v9")["id"] == "elevator_spray_statement_v1"


# --- the rule pack's `until` is honoured, not decorative ---------------------


def test_until_reads_the_rule():
    today = date(2026, 8, 20)
    assert until_from_rule({"until": "end_of_calendar_year"}, today) == date(2026, 12, 31)
    assert until_from_rule({"until": "+90d"}, today) == today + timedelta(days=90)
    assert until_from_rule({"until": "2026-10-18"}, today) == date(2026, 10, 18)
    # A typo must never widen a consent, so unknown spellings clamp to year end.
    assert until_from_rule({"until": "whenever"}, today) == year_end(today)
    assert until_from_rule({}, today) == year_end(today)


def test_shipped_packs_expire_at_year_end(local_store):
    for rule_id in ("elevator_spray_statement_v1", "coop_ppp_statement_v1"):
        assert until_from_rule(load_rule(rule_id)) == year_end()


# --- confirm patches only what the farmer touched ----------------------------


def _draft(store) -> EventRecord:
    event = EventRecord(
        id="evt-patch",
        farm_id="demo-farm",
        parcel_id="p3",
        time=datetime.now(timezone.utc),
        product_name="Guessed X",
        rate=1.2,
        buffer_m=5.0,
        note="voice draft",
    )
    store.put("events", event.id, event.model_dump(mode="json"))
    return event


def test_confirm_leaves_untouched_fields_alone(local_store):
    updated = capture.confirm(_draft(local_store), rate=1.4)
    assert updated.rate == 1.4
    assert updated.product_name == "Guessed X"  # not blanked
    assert updated.status == "confirmed"


def test_confirm_clears_a_nullable_field(local_store):
    """The farmer is the source of truth: an explicit null drops a bad guess."""
    updated = capture.confirm(_draft(local_store), rate=None)
    assert updated.rate is None
    assert updated.buffer_m == 5.0


def test_confirm_will_not_null_a_required_field(local_store):
    updated = capture.confirm(_draft(local_store), parcel_id=None, product_name=None)
    assert updated.parcel_id == "p3"
    assert updated.product_name == "Guessed X"


# --- a consent card never silently substitutes partner or purpose ------------


def test_consent_rejects_a_pack_mismatch(local_store):
    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X 1.2 L/ha 5 m"}, headers=h)
    eid = ev.json()["id"]
    pack_id = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2, "buffer_m": 5}, headers=h).json()["pack"]["id"]

    bad = c.post(
        "/v1/consents",
        json={"pack_id": pack_id, "partner_id": "someone-else"},
        headers=h,
    )
    assert bad.status_code == 409, bad.text
    assert bad.json()["detail"]["code"] == "pack_mismatch"

    ok = c.post(
        "/v1/consents",
        json={"pack_id": pack_id, "partner_id": "heartland-grain", "purpose": "seasonal_spray_statement"},
        headers=h,
    )
    assert ok.status_code == 200, ok.text


# --- no credentials, no network ---------------------------------------------


def test_no_project_means_no_vertex_client(monkeypatch):
    from origin import config, gemini_router

    for var in ("ORIGIN_GCP_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    config.reset_settings()
    try:
        assert config.settings().vertex_ready is False
        assert gemini_router._client() is None
        # Fallbacks still produce a usable draft and a readable consent card.
        draft = gemini_router.extract_event(note="parcel 3 product X 1.2 L/ha 5 m buffer")
        assert draft.rate == 1.2
        talk = gemini_router.explain_consent(
            partner_name="Heartland Grain LLC",
            purpose="seasonal_spray_statement",
            fields={"parcel_id": "p3"},
            until="2026-12-31",
            reuse=False,
            locale="en",
        )
        assert talk.who and talk.why and talk.until
    finally:
        config.reset_settings()


def test_no_api_key_is_read_anywhere(monkeypatch):
    """Organisation policy forbids API keys. Setting one must change nothing."""
    from origin import config, gemini_router

    monkeypatch.delenv("ORIGIN_GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "should-be-ignored")
    monkeypatch.setenv("GOOGLE_API_KEY", "should-be-ignored")
    config.reset_settings()
    try:
        assert gemini_router._client() is None
    finally:
        config.reset_settings()
