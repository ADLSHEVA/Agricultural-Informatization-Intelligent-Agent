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
