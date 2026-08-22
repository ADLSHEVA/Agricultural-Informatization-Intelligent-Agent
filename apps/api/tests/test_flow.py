from origin.main import app
from origin.seed import ensure_demo
from fastapi.testclient import TestClient


def test_sunday_loop(tmp_path, monkeypatch):
    from origin import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "origin.json")
    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    ev = c.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "Parcel 3 product X 1.2 L/ha 5 m buffer"},
        headers=h,
    )
    assert ev.status_code == 200, ev.text
    eid = ev.json()["id"]
    conf = c.post(f"/v1/events/{eid}/confirm", json={"product_name": "X", "rate": 1.2, "buffer_m": 5}, headers=h)
    assert conf.status_code == 200, conf.text
    cid = conf.json()["consent"]["id"]
    assert conf.json()["auto"] is False
    assert conf.json()["pack"]["fields"]["buffer_ok"] is True
    bound = c.post(f"/v1/consents/{cid}/bind", json={"standing": True}, headers=h)
    assert bound.status_code == 200, bound.text
    assert bound.json()["policy"]["state"] == "active"
    desk = c.get("/v1/desk/packs", headers={"Authorization": "Bearer demo-partner"})
    assert desk.status_code == 200
    assert any(not row["grey"] for row in desk.json())
    asked = c.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm"},
        headers={"Authorization": "Bearer demo-partner"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["agent"]["decision"] == "auto_deliver"
    desk_auto = c.get("/v1/desk/packs", headers={"Authorization": "Bearer demo-partner"})
    live = [row for row in desk_auto.json() if not row["grey"]]
    # Asking again replaces the current file; it must not stack a second copy.
    assert len(live) == 1
    # Both the first Give and the auto-delivery are live until revoked.
    for consent_id in {cid, live[0]["consent"]["id"]}:
        rev = c.post(f"/v1/consents/{consent_id}/revoke", headers=h)
        assert rev.status_code == 200
    desk2 = c.get("/v1/desk/packs", headers={"Authorization": "Bearer demo-partner"})
    assert any(row["grey"] for row in desk2.json())
    assert not any(not row["grey"] for row in desk2.json())


def test_double_confirm_is_refused_not_duplicated(local_store):
    """A retry or double tap must not compile a second pack / open a second
    consent for the same fact."""
    from origin import store

    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    ev = c.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "Parcel 3 product X 1.2 L/ha 5 m buffer"},
        headers=h,
    )
    eid = ev.json()["id"]
    first = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    assert first.status_code == 200, first.text
    again = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_confirmed"
    assert len(store.list_where("packs", farm_id="demo-farm")) == 1
    assert len(store.list_where("consents", farm_id="demo-farm")) == 1


def test_confirm_with_unknown_parcel_leaves_the_draft_alone(local_store):
    """The parcel check runs before anything is written: a failed confirm must
    not leave a confirmed event pointing at a field that does not exist."""
    from origin import store

    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=h)
    eid = ev.json()["id"]
    bad = c.post(f"/v1/events/{eid}/confirm", json={"parcel_id": "p999"}, headers=h)
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "bad_parcel"
    row = store.get("events", eid)
    assert row["status"] == "draft"
    assert row["parcel_id"] == "p3"


def test_desk_request_unknown_farm_is_404(local_store):
    """An unknown farm gets a clean 404 and collects no junk request rows."""
    from origin import store

    ensure_demo()
    c = TestClient(app)
    r = c.post(
        "/v1/desk/requests",
        json={"farm_id": "no-such-farm"},
        headers={"Authorization": "Bearer demo-partner"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"
    assert not store.list_where("requests", farm_id="no-such-farm")
    assert not store.list_where("agent_log", farm_id="no-such-farm")


def test_post_event_requires_a_parcel(local_store):
    """A missing or blank parcel must fail loudly, never land silently on p3."""
    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    missing = c.post("/v1/events", data={"note": "product X"}, headers=h)
    assert missing.status_code == 422
    blank = c.post("/v1/events", data={"parcel_id": "   ", "note": "product X"}, headers=h)
    assert blank.status_code == 400
    assert blank.json()["detail"]["code"] == "bad_parcel"


def test_reuse_off_blocks_second_bind_of_the_same_pack(local_store):
    """`Reuse: No` on the card must mean something: one grant per compiled pack,
    even after revoke; sharing again needs a fresh compile that returns to the
    farmer. Auto-delivery compiles a new pack each time, so it is unaffected."""
    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=h)
    eid = ev.json()["id"]
    conf = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    pack_id = conf.json()["pack"]["id"]
    cid1 = c.post("/v1/consents", json={"pack_id": pack_id}, headers=h).json()["id"]
    assert c.post(f"/v1/consents/{cid1}/bind", json={}, headers=h).status_code == 200
    cid2 = c.post("/v1/consents", json={"pack_id": pack_id}, headers=h).json()["id"]
    again = c.post(f"/v1/consents/{cid2}/bind", json={}, headers=h)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "reuse_forbidden"
    # Revoking the first grant does not re-open the pack either.
    assert c.post(f"/v1/consents/{cid1}/revoke", headers=h).status_code == 200
    cid3 = c.post("/v1/consents", json={"pack_id": pack_id}, headers=h).json()["id"]
    third = c.post(f"/v1/consents/{cid3}/bind", json={}, headers=h)
    assert third.status_code == 409


def test_erase_leaves_hash_only_stubs(local_store):
    """Art. 17 promise: after erase, nothing readable of the shared content
    survives anywhere the API can hand back — but the hash does."""
    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    p = {"Authorization": "Bearer demo-partner"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=h)
    eid = ev.json()["id"]
    conf = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    pack_id = conf.json()["pack"]["id"]
    cid = conf.json()["consent"]["id"]
    assert c.post(f"/v1/consents/{cid}/bind", json={}, headers=h).status_code == 200
    erased = c.request("DELETE", "/v1/me", headers=h)
    assert erased.status_code == 200
    export = c.get("/v1/me/export", headers=h).json()
    assert all(row["fields"] == {} and row["checks"] == {} for row in export["packs"])
    for receipt in export["receipts"]:
        assert receipt["field_list"] == []
        assert receipt["pack_hash"]  # the proof survives
        assert receipt["partner_name"]  # Who still shows who had it
    assert {row["state"] for row in export["consents"]} == {"erased"}
    assert export["events"][0]["product_name"] == ""
    # And the desk is locked out.
    desk = c.get(f"/v1/desk/packs/{pack_id}", headers=p)
    assert desk.status_code == 410


def test_desk_inbox_orders_by_pack_creation(local_store):
    """Inbox order must follow pack creation time, not random consent hex."""
    from datetime import date, timedelta

    from origin import deliver, store

    ensure_demo()
    until = str(date.today() + timedelta(days=30))

    def seed(farm_id: str, pack_id: str, consent_id: str, token_id: str, created_at: str):
        store.put("farms", farm_id, {"id": farm_id, "country": "US", "locale": "en", "display_name": farm_id})
        store.put(
            "packs",
            pack_id,
            {
                "id": pack_id,
                "farm_id": farm_id,
                "event_ids": [],
                "rule_id": "elevator_spray_statement_v1",
                "partner_id": "heartland-grain",
                "purpose": "seasonal_spray_statement",
                "fields": {"parcel_id": "p1"},
                "checks": {},
                "created_at": created_at,
            },
        )
        store.put(
            "consents",
            consent_id,
            {
                "id": consent_id,
                "farm_id": farm_id,
                "pack_id": pack_id,
                "partner_id": "heartland-grain",
                "partner_name": "Heartland Grain LLC",
                "purpose": "seasonal_spray_statement",
                "fields": ["parcel_id"],
                "until": until,
                "reuse": False,
                "state": "purpose-bound",
            },
        )
        store.put(
            "tokens",
            token_id,
            {
                "id": token_id,
                "consent_id": consent_id,
                "farm_id": farm_id,
                "partner_id": "heartland-grain",
                "expires_at": f"{until}T23:59:59+00:00",
                "revoked": False,
            },
        )

    seed("farm-a", "pack-old", "cns-old", "tok-old", "2026-08-01T00:00:00+00:00")
    seed("farm-b", "pack-new", "cns-new", "tok-new", "2026-08-20T00:00:00+00:00")
    inbox = deliver.desk_inbox("heartland-grain")
    ids = [row["pack"]["id"] for row in inbox]
    assert ids == ["pack-new", "pack-old"]


def test_repeat_asks_reuse_the_card_then_the_live_file(local_store):
    """Asking twice must not stack packs: an undecided ask reuses the open
    card; a bound ask points at the already-live file instead of re-delivering."""
    from origin import store

    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    p = {"Authorization": "Bearer demo-partner"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X 1.2 L/ha"}, headers=h)
    eid = ev.json()["id"]
    conf = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    cid = conf.json()["consent"]["id"]

    ask1 = c.post("/v1/desk/requests", json={"farm_id": "demo-farm"}, headers=p)
    assert ask1.status_code == 200, ask1.text
    assert ask1.json()["agent"]["decision"] == "ask_farmer"
    assert ask1.json()["agent"]["reason_code"] == "pending_decision"
    assert ask1.json()["agent"]["consent_id"] == cid
    drafts = [x for x in store.list_where("consents", farm_id="demo-farm") if x["state"] == "draft"]
    assert len(drafts) == 1
    assert len(store.list_where("packs", farm_id="demo-farm")) == 1

    assert c.post(f"/v1/consents/{cid}/bind", json={}, headers=h).status_code == 200
    ask2 = c.post("/v1/desk/requests", json={"farm_id": "demo-farm"}, headers=p)
    assert ask2.status_code == 200, ask2.text
    body = ask2.json()
    assert body["agent"]["decision"] == "auto_deliver"
    assert body["agent"]["reason_code"] == "already_live"
    assert len(store.list_where("packs", farm_id="demo-farm")) == 1
    assert len(store.list_where("consents", farm_id="demo-farm")) == 1
    assert len(store.list_where("tokens", farm_id="demo-farm")) == 1


def test_expired_policy_drops_off_today(local_store):
    """Lazy expiry: a policy past its until stops being advertised as active."""
    from datetime import date, timedelta

    from origin import store

    ensure_demo()
    store.put(
        "policies",
        "pol-stale",
        {
            "id": "pol-stale",
            "farm_id": "demo-farm",
            "partner_id": "heartland-grain",
            "purpose": "seasonal_spray_statement",
            "allowed_fields": ["parcel_id"],
            "until": str(date.today() - timedelta(days=1)),
            "reuse": False,
            "state": "active",
            "created_from_consent_id": None,
        },
    )
    c = TestClient(app)
    t = c.get("/v1/today", headers={"Authorization": "Bearer demo-farmer"}).json()
    assert all(row["id"] != "pol-stale" for row in t["standing_policies"])
    assert store.get("policies", "pol-stale")["state"] == "expired"


def test_dead_token_hides_the_pack_even_before_the_state_flips(local_store):
    """desk_visible honours token.expires_at, not just the revoked flag."""
    from origin import store

    ensure_demo()
    c = TestClient(app)
    h = {"Authorization": "Bearer demo-farmer"}
    p = {"Authorization": "Bearer demo-partner"}
    ev = c.post("/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=h)
    eid = ev.json()["id"]
    conf = c.post(f"/v1/events/{eid}/confirm", json={"rate": 1.2}, headers=h)
    pack_id = conf.json()["pack"]["id"]
    cid = conf.json()["consent"]["id"]
    assert c.post(f"/v1/consents/{cid}/bind", json={}, headers=h).status_code == 200
    tok = next(iter(store.list_where("tokens", consent_id=cid)))
    tok["expires_at"] = "2000-01-01T00:00:00+00:00"
    store.put("tokens", tok["id"], tok)
    r = c.get(f"/v1/desk/packs/{pack_id}", headers=p)
    assert r.status_code == 410
