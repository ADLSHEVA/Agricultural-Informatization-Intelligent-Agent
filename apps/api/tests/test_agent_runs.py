"""Event-driven AgentRun lifecycle and auditable delivery evidence."""

from fastapi.testclient import TestClient

from origin.main import app
from origin.seed import ensure_demo

FARMER = {"Authorization": "Bearer demo-farmer"}
PARTNER = {"Authorization": "Bearer demo-partner"}


def test_partner_request_creates_a_traceable_run(local_store):
    ensure_demo()
    client = TestClient(app)
    response = client.post(
        "/v1/desk/requests", json={"farm_id": "demo-farm"}, headers=PARTNER
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["id"].startswith("run-")
    assert run["trace_id"].startswith("trc-")
    assert run["status"] == "waiting_for_farmer"
    assert run["decision"] == "need_capture"
    assert [step["name"] for step in run["steps"]] == [
        "request_received",
        "background_dispatch",
        "policy_routing",
        "policy_routing",
        "human_boundary",
    ]
    today = client.get("/v1/today", headers=FARMER).json()
    assert today["agent_runs"][0]["trace_id"] == run["trace_id"]


def test_manual_approval_records_a_real_delivery(local_store):
    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "product X 1.2 L/ha 5 m buffer"},
        headers=FARMER,
    ).json()
    assert event["provenance"]["trace_id"] == "trc-demo-request"
    confirmed = client.post(
        f"/v1/events/{event['id']}/confirm",
        json={"product_name": "X", "rate": 1.2, "unit": "L/ha", "buffer_m": 5},
        headers=FARMER,
    ).json()
    consent_id = confirmed["consent"]["id"]
    card = client.get(f"/v1/consents/{consent_id}", headers=FARMER).json()
    assert card["pack_fields"]["date"]
    assert card["pack_fields"]["unit"] == "L/ha"
    assert card["pack_fields"]["buffer_ok"] is True

    bound = client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": True}, headers=FARMER
    )
    assert bound.status_code == 200, bound.text
    delivery = bound.json()["delivery"]
    assert delivery["status"] == "delivered"
    assert delivery["destinations"] == ["origin_partner_desk"]

    receipts = client.get("/v1/receipts", headers=FARMER).json()
    assert receipts[0]["purpose"] == "seasonal_spray_statement"
    assert receipts[0]["delivery"]["id"] == delivery["id"]


def test_bind_retry_is_idempotent_and_revoke_closes_policy(local_store):
    from origin import store

    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "product X 1.2 L/ha 5 m buffer"},
        headers=FARMER,
    ).json()
    confirmed = client.post(
        f"/v1/events/{event['id']}/confirm",
        json={"product_name": "X", "rate": 1.2, "buffer_m": 5},
        headers=FARMER,
    ).json()
    consent_id = confirmed["consent"]["id"]

    first = client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": True}, headers=FARMER
    )
    retry = client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": True}, headers=FARMER
    )
    assert first.status_code == retry.status_code == 200
    assert first.json()["delivery"]["id"] == retry.json()["delivery"]["id"]
    assert len(store.list_where("tokens", consent_id=consent_id)) == 1
    assert len(store.list_where("receipts", consent_id=consent_id)) == 1
    assert len(store.list_where("policies", created_from_consent_id=consent_id)) == 1

    revoked = client.post(f"/v1/consents/{consent_id}/revoke", headers=FARMER)
    assert revoked.status_code == 200
    assert store.list_where("policies", created_from_consent_id=consent_id)[0]["state"] == "revoked"


def test_changed_purpose_stops_at_the_farmer_boundary(local_store):
    from origin import store

    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "product X 1.2 L/ha 5 m buffer"},
        headers=FARMER,
    ).json()
    confirmed = client.post(
        f"/v1/events/{event['id']}/confirm",
        json={"product_name": "X", "rate": 1.2, "buffer_m": 5},
        headers=FARMER,
    ).json()
    consent_id = confirmed["consent"]["id"]
    assert client.post(
        f"/v1/consents/{consent_id}/bind",
        json={"standing": True},
        headers=FARMER,
    ).status_code == 200
    delivery_count = len(store.list_where("deliveries"))

    changed = client.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "purpose": "carbon_practice_statement"},
        headers=PARTNER,
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["run"]["status"] == "waiting_for_farmer"
    assert body["agent"]["decision"] == "ask_farmer"
    assert body["agent"]["reason_code"] == "new_purpose"
    draft = store.get("consents", body["agent"]["consent_id"])
    assert draft["purpose"] == "carbon_practice_statement"
    assert len(store.list_where("deliveries")) == delivery_count


def test_new_fact_waits_then_background_request_auto_delivers(local_store):
    from origin import store

    ensure_demo()
    client = TestClient(app)

    first = client.post(
        "/v1/events",
        data={"parcel_id": "p3", "note": "product X 1.2 L/ha 5 m buffer"},
        headers=FARMER,
    ).json()
    first_result = client.post(
        f"/v1/events/{first['id']}/confirm",
        json={"product_name": "X", "rate": 1.2, "buffer_m": 5},
        headers=FARMER,
    ).json()
    assert client.post(
        f"/v1/consents/{first_result['consent']['id']}/bind",
        json={"standing": True},
        headers=FARMER,
    ).status_code == 200

    second = client.post(
        "/v1/events",
        data={"parcel_id": "p4", "note": "product Y 0.8 L/ha"},
        headers=FARMER,
    ).json()
    stored = client.post(
        f"/v1/events/{second['id']}/confirm",
        json={"product_name": "Y", "rate": 0.8, "buffer_m": 0},
        headers=FARMER,
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["saved_only"] is True
    assert stored.json()["consent"] is None
    before = len(store.list_where("deliveries"))

    request = client.post(
        "/v1/desk/requests", json={"farm_id": "demo-farm"}, headers=PARTNER
    )
    assert request.status_code == 200, request.text
    run = request.json()["run"]
    assert run["status"] == "completed"
    assert run["decision"] == "auto_deliver"
    assert run["reason_code"] == "standing_policy"
    assert run["delivery_id"]
    assert len(store.list_where("deliveries")) == before + 1


def test_cloud_tasks_mode_returns_before_agent_execution(local_store, monkeypatch):
    from origin import config, task_dispatch

    monkeypatch.setenv("ORIGIN_AGENT_DISPATCH", "tasks")
    config.reset_settings()
    monkeypatch.setattr(task_dispatch, "enqueue", lambda run_id: f"queues/demo/tasks/{run_id}")
    try:
        ensure_demo()
        client = TestClient(app)
        response = client.post(
            "/v1/desk/requests", json={"farm_id": "demo-farm"}, headers=PARTNER
        )
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        assert run["status"] == "queued"
        assert run["decision"] is None
        assert run["queue_task"].endswith(run["id"])
        assert not local_store.list_where("agent_log", farm_id="demo-farm")
    finally:
        config.reset_settings()


def test_internal_worker_requires_its_token(local_store, monkeypatch):
    from origin import config, runs, store

    monkeypatch.setenv("ORIGIN_INTERNAL_TOKEN", "worker-test-token")
    config.reset_settings()
    try:
        ensure_demo()
        request = store.as_request(store.get("requests", "req-demo-open"))
        # Create inline, then reset it to queued to exercise the worker route.
        run = runs.create_for_request(request)
        row = store.get("agent_runs", run.id)
        row["status"] = "queued"
        store.put("agent_runs", run.id, row)

        client = TestClient(app)
        denied = client.post(f"/v1/internal/runs/{run.id}/execute")
        assert denied.status_code == 403
        accepted = client.post(
            f"/v1/internal/runs/{run.id}/execute",
            headers={"X-Origin-Worker-Token": "worker-test-token"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "waiting_for_farmer"
    finally:
        config.reset_settings()
