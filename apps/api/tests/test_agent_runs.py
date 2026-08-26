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
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "purpose": "residue_statement"},
        headers=PARTNER,
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


def test_extra_fields_are_reported_on_the_farmer_decision(local_store):
    from datetime import date, timedelta

    from origin import store

    ensure_demo()
    store.put(
        "policies",
        "pol-too-small",
        {
            "id": "pol-too-small",
            "farm_id": "demo-farm",
            "partner_id": "heartland-grain",
            "purpose": "seasonal_spray_statement",
            "allowed_fields": ["parcel_id"],
            "until": str(date.today() + timedelta(days=30)),
            "reuse": True,
            "state": "active",
        },
    )
    client = TestClient(app)
    event = client.post(
        "/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=FARMER
    ).json()
    result = client.post(
        f"/v1/events/{event['id']}/confirm", json={"rate": 1.2}, headers=FARMER
    )
    assert result.status_code == 200, result.text
    decision = result.json()["agent"]
    assert decision["reason_code"] == "extra_fields"
    assert "product_name" in decision["extra_fields"]
    assert result.json()["auto"] is False


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
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "parcel_id": "p4"},
        headers=PARTNER,
    )
    assert request.status_code == 200, request.text
    run = request.json()["run"]
    assert run["status"] == "completed"
    assert run["decision"] == "auto_deliver"
    assert run["reason_code"] == "standing_policy"
    assert run["delivery_id"]
    assert len(store.list_where("deliveries")) == before + 1


def test_confirm_retries_auto_delivery_after_destination_failure(local_store, monkeypatch):
    """A failed destination leaves the exact event/request resumable."""
    from origin import partner_delivery, store

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

    requested = client.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "parcel_id": "p4"},
        headers=PARTNER,
    ).json()
    event = client.post(
        "/v1/events",
        data={"parcel_id": "p4", "note": "product Y 0.8 L/ha"},
        headers=FARMER,
    ).json()
    real_send = partner_delivery.send
    calls = 0

    def flaky_send(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated destination outage")
        return real_send(*args, **kwargs)

    monkeypatch.setattr(partner_delivery, "send", flaky_send)
    transport_client = TestClient(app, raise_server_exceptions=False)
    failed = transport_client.post(
        f"/v1/events/{event['id']}/confirm",
        json={"product_name": "Y", "rate": 0.8, "buffer_m": 0},
        headers=FARMER,
    )
    assert failed.status_code == 500
    assert store.get("events", event["id"])["status"] == "confirmed"
    assert store.get("requests", requested["id"])["status"] == "open"
    assert store.get("agent_runs", requested["run"]["id"])["status"] == "failed"

    resumed = client.post(
        f"/v1/events/{event['id']}/confirm",
        json={"product_name": "Y", "rate": 0.8, "buffer_m": 0},
        headers=FARMER,
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["auto"] is True
    assert store.get("requests", requested["id"])["status"] == "completed"
    p4_packs = [
        row
        for row in store.list_where("packs", farm_id="demo-farm")
        if event["id"] in row.get("event_ids", [])
    ]
    assert len(p4_packs) == 1


def test_bind_retry_recovers_a_failed_webhook_delivery(local_store, monkeypatch):
    from origin import partner_delivery, store

    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=FARMER
    ).json()
    result = client.post(
        f"/v1/events/{event['id']}/confirm", json={"rate": 1.2}, headers=FARMER
    ).json()
    consent_id = result["consent"]["id"]
    calls = 0

    def flaky_post(_payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated webhook outage")
        return {"configured": True, "status": 200}

    monkeypatch.setattr(partner_delivery, "_post", flaky_post)
    first = TestClient(app, raise_server_exceptions=False).post(
        f"/v1/consents/{consent_id}/bind",
        json={"standing": True},
        headers=FARMER,
    )
    assert first.status_code == 500
    failed = store.list_where("deliveries", farm_id="demo-farm")
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert store.get("requests", "req-demo-open")["status"] == "linked"

    retry = client.post(
        f"/v1/consents/{consent_id}/bind",
        json={"standing": True},
        headers=FARMER,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["delivery"]["id"] == failed[0]["id"]
    assert retry.json()["delivery"]["status"] == "delivered"
    assert store.get("requests", "req-demo-open")["status"] == "completed"
    assert len(store.list_where("policies", created_from_consent_id=consent_id)) == 1


def test_waiting_worker_retry_is_a_noop(local_store, monkeypatch):
    from origin import config, store

    monkeypatch.setenv("ORIGIN_INTERNAL_TOKEN", "worker-test-token")
    config.reset_settings()
    try:
        ensure_demo()
        before = store.get("agent_runs", "run-demo-open")
        response = TestClient(app).post(
            "/v1/internal/runs/run-demo-open/execute",
            headers={"X-Origin-Worker-Token": "worker-test-token"},
        )
        assert response.status_code == 200
        after = store.get("agent_runs", "run-demo-open")
        assert response.json()["status"] == "waiting_for_farmer"
        assert after == before
        assert not store.list_where("agent_log", farm_id="demo-farm")
    finally:
        config.reset_settings()


def test_refusal_is_terminal_for_its_request_and_run(local_store):
    from origin import runs, store

    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=FARMER
    ).json()
    result = client.post(
        f"/v1/events/{event['id']}/confirm", json={"rate": 1.2}, headers=FARMER
    ).json()
    consent_id = result["consent"]["id"]
    refused = client.post(f"/v1/consents/{consent_id}/refuse", headers=FARMER)
    assert refused.status_code == 200
    request = store.get("requests", "req-demo-open")
    run = store.get("agent_runs", "run-demo-open")
    assert request["status"] == "refused"
    assert run["status"] == "completed"
    assert run["decision"] == "farmer_refused"
    assert runs.execute(run["id"]).status == "completed"
    assert not store.list_where("deliveries", farm_id="demo-farm")


def test_request_uses_its_parcel_not_the_latest_farm_event(local_store):
    from origin import store

    ensure_demo()
    client = TestClient(app)
    p4 = client.post(
        "/v1/events", data={"parcel_id": "p4", "note": "product Y"}, headers=FARMER
    ).json()
    assert client.post(
        f"/v1/events/{p4['id']}/confirm", json={"rate": 0.8}, headers=FARMER
    ).json()["saved_only"] is True

    p3_request = client.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "parcel_id": "p3", "purpose": "residue_statement"},
        headers=PARTNER,
    ).json()
    assert p3_request["run"]["decision"] == "need_capture"
    assert not [
        row
        for row in store.list_where("packs", farm_id="demo-farm")
        if p4["id"] in row.get("event_ids", [])
    ]

    p4_request = client.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "parcel_id": "p4", "purpose": "residue_statement"},
        headers=PARTNER,
    ).json()
    assert p4_request["run"]["decision"] == "ask_farmer"
    pack = store.get("packs", p4_request["run"]["pack_id"])
    assert pack["fields"]["parcel_id"] == "p4"


def test_concurrent_worker_and_confirm_create_one_pack_and_consent(local_store):
    from concurrent.futures import ThreadPoolExecutor

    from origin import agent, capture, store

    ensure_demo()
    event = capture.create_draft(
        farm_id="demo-farm", parcel_id="p3", note="product X 1.2 L/ha"
    )
    event = capture.confirm(event, product_name="X", rate=1.2)
    request = store.as_request(store.get("requests", "req-demo-open"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: agent.tick_request(request, event_id=event.id),
                range(2),
            )
        )

    assert {result["decision"] for result in results} <= {"ask_farmer"}
    packs = store.list_where("packs", farm_id="demo-farm")
    consents = store.list_where("consents", farm_id="demo-farm")
    assert len(packs) == 1
    assert len(consents) == 1
    assert consents[0]["pack_id"] == packs[0]["id"]


def test_bound_consent_cannot_gain_standing_on_retry(local_store):
    from origin import store

    ensure_demo()
    client = TestClient(app)
    event = client.post(
        "/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=FARMER
    ).json()
    result = client.post(
        f"/v1/events/{event['id']}/confirm", json={"rate": 1.2}, headers=FARMER
    ).json()
    consent_id = result["consent"]["id"]
    assert client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": False}, headers=FARMER
    ).json()["policy"] is None
    retry = client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": True}, headers=FARMER
    )
    assert retry.status_code == 200
    assert retry.json()["policy"] is None
    assert not store.list_where("policies", created_from_consent_id=consent_id)


def test_auto_consent_is_clamped_to_the_standing_policy(local_store):
    from datetime import date, timedelta

    from origin import store

    ensure_demo()
    client = TestClient(app)
    first = client.post(
        "/v1/events", data={"parcel_id": "p3", "note": "product X"}, headers=FARMER
    ).json()
    result = client.post(
        f"/v1/events/{first['id']}/confirm", json={"rate": 1.2}, headers=FARMER
    ).json()
    consent_id = result["consent"]["id"]
    bound = client.post(
        f"/v1/consents/{consent_id}/bind", json={"standing": True}, headers=FARMER
    ).json()
    policy = bound["policy"]
    short_until = (date.today() + timedelta(days=2)).isoformat()
    policy["until"] = short_until
    store.put("policies", policy["id"], policy)

    requested = client.post(
        "/v1/desk/requests",
        json={"farm_id": "demo-farm", "parcel_id": "p4"},
        headers=PARTNER,
    ).json()
    event = client.post(
        "/v1/events", data={"parcel_id": "p4", "note": "product Y"}, headers=FARMER
    ).json()
    auto = client.post(
        f"/v1/events/{event['id']}/confirm", json={"rate": 0.8}, headers=FARMER
    )
    assert auto.status_code == 200, auto.text
    assert auto.json()["auto"] is True
    assert auto.json()["consent"]["until"] == short_until
    assert store.get("requests", requested["id"])["status"] == "completed"


def test_cloud_tasks_mode_returns_before_agent_execution(local_store, monkeypatch):
    from origin import config, task_dispatch

    monkeypatch.setenv("ORIGIN_AGENT_DISPATCH", "tasks")
    config.reset_settings()
    monkeypatch.setattr(task_dispatch, "enqueue", lambda run_id: f"queues/demo/tasks/{run_id}")
    try:
        ensure_demo()
        client = TestClient(app)
        response = client.post(
            "/v1/desk/requests",
            json={"farm_id": "demo-farm", "purpose": "residue_statement"},
            headers=PARTNER,
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


def test_internal_worker_requires_google_identity_when_enabled(local_store, monkeypatch):
    from origin import auth, config

    monkeypatch.setenv("ORIGIN_INTERNAL_TOKEN", "worker-test-token")
    monkeypatch.setenv("ORIGIN_REQUIRE_WORKER_OIDC", "true")
    monkeypatch.setenv("ORIGIN_API_BASE_URL", "https://origin-api.example")
    monkeypatch.setenv("ORIGIN_TASK_SERVICE_ACCOUNT", "origin-runtime@example.iam.gserviceaccount.com")
    config.reset_settings()
    try:
        ensure_demo()
        client = TestClient(app)
        headers = {"X-Origin-Worker-Token": "worker-test-token"}
        missing = client.post("/v1/internal/runs/run-demo-open/execute", headers=headers)
        assert missing.status_code == 403

        monkeypatch.setattr(
            auth,
            "_verified_worker_claims",
            lambda _token, _audience: {
                "email": "wrong@example.iam.gserviceaccount.com",
                "email_verified": True,
            },
        )
        wrong = client.post(
            "/v1/internal/runs/run-demo-open/execute",
            headers={**headers, "Authorization": "Bearer signed-task-token"},
        )
        assert wrong.status_code == 403

        monkeypatch.setattr(
            auth,
            "_verified_worker_claims",
            lambda _token, audience: {
                "email": "origin-runtime@example.iam.gserviceaccount.com",
                "email_verified": True,
                "aud": audience,
            },
        )
        accepted = client.post(
            "/v1/internal/runs/run-demo-open/execute",
            headers={**headers, "Authorization": "Bearer signed-task-token"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "waiting_for_farmer"
    finally:
        config.reset_settings()
