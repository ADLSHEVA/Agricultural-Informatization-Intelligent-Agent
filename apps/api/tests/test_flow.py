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
    assert len(live) >= 2
    rev = c.post(f"/v1/consents/{cid}/revoke", headers=h)
    assert rev.status_code == 200
    desk2 = c.get("/v1/desk/packs", headers={"Authorization": "Bearer demo-partner"})
    assert any(row["grey"] for row in desk2.json())
