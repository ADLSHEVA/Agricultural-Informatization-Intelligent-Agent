"""Durable, auditable execution lifecycle for the background Origin agent."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from origin import agent, partner_delivery, store, task_dispatch
from origin.config import settings
from origin.gemini_router import begin_trace, end_trace, last_provenance
from origin.models import AgentRun, ConsentRecord, PartnerRequest

log = logging.getLogger("origin.agent_run")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "Required agent state was not found"
    if isinstance(exc, RuntimeError):
        return str(exc)[:200]
    return f"{type(exc).__name__}: agent execution failed"


def _step(run: AgentRun, name: str, status: str, detail: str) -> None:
    run.steps.append(
        {"name": name, "status": status, "detail": detail, "at": _now().isoformat()}
    )
    run.updated_at = _now()


def _save(run: AgentRun) -> AgentRun:
    store.put("agent_runs", run.id, run.model_dump(mode="json"))
    log.info(
        "agent_run trace_id=%s run_id=%s request_id=%s status=%s decision=%s attempts=%s",
        run.trace_id,
        run.id,
        run.request_id,
        run.status,
        run.decision or "pending",
        run.attempts,
    )
    return run


def _latest_for_request(request_id: str | None) -> AgentRun | None:
    if not request_id:
        return None
    matches = store.list_where("agent_runs", request_id=request_id)
    if not matches:
        return None
    return AgentRun.model_validate(
        max(matches, key=lambda row: str(row.get("created_at") or ""))
    )


@contextmanager
def request_trace(request_id: str | None):
    """Correlate farmer resume steps with the AgentRun that requested them."""
    run = _latest_for_request(request_id)
    if run is None:
        yield None
        return
    token = begin_trace(run.trace_id)
    try:
        yield run
    finally:
        end_trace(token)


def create_for_request(req: PartnerRequest) -> AgentRun:
    now = _now()
    run = AgentRun(
        id=f"run-{uuid4().hex[:10]}",
        trace_id=f"trc-{uuid4().hex[:12]}",
        request_id=req.id,
        farm_id=req.farm_id,
        partner_id=req.partner_id,
        created_at=now,
        updated_at=now,
    )
    _step(run, "request_received", "completed", "Partner request persisted before execution.")
    _save(run)
    if settings().agent_dispatch.lower() == "tasks":
        try:
            run.queue_task = task_dispatch.enqueue(run.id)
            _step(run, "background_dispatch", "completed", "Queued in Google Cloud Tasks.")
            return _save(run)
        except Exception as exc:
            run.status = "failed"
            run.error = _safe_error(exc)
            _step(run, "background_dispatch", "failed", run.error)
            _save(run)
            raise
    _step(run, "background_dispatch", "completed", "Executed inline for local development.")
    _save(run)
    return execute(run.id)


def execute(run_id: str) -> AgentRun:
    row = store.get("agent_runs", run_id)
    if not row:
        raise KeyError(f"AgentRun {run_id} not found")
    run = AgentRun.model_validate(row)
    if run.status == "completed":
        return run

    request_row = store.get("requests", run.request_id)
    if not request_row:
        run.status = "failed"
        run.error = "Partner request disappeared before execution"
        _step(run, "load_request", "failed", run.error)
        _save(run)
        raise RuntimeError(run.error)

    run.status = "running"
    run.attempts += 1
    run.error = None
    _step(run, "policy_routing", "running", "Evaluating facts, purpose, and standing permission.")
    _save(run)
    trace_token = begin_trace(run.trace_id)
    try:
        result = agent.tick_request(store.as_request(request_row))
        run.model = last_provenance()
        run.decision = result.get("decision")
        run.reason_code = result.get("reason_code")
        run.consent_id = result.get("consent_id") or getattr(result.get("consent"), "id", None)
        run.pack_id = result.get("pack_id")
        _step(
            run,
            "policy_routing",
            "completed",
            f"Decision: {run.decision} ({run.reason_code}).",
        )

        if result.get("mode") == "auto":
            consent_obj = result.get("consent")
            if not isinstance(consent_obj, ConsentRecord):
                consent_obj = store.as_consent(store.get("consents", run.consent_id) or {})
            pack_row = store.get("packs", consent_obj.pack_id)
            if not pack_row:
                raise RuntimeError("Pack missing at delivery time")
            delivery = partner_delivery.send(
                consent_obj,
                store.as_pack(pack_row),
                run_id=run.id,
                trace_id=run.trace_id,
            )
            run.pack_id = consent_obj.pack_id
            run.delivery_id = delivery["id"]
            run.status = "completed"
            _step(
                run,
                "partner_delivery",
                "completed",
                "Minimal pack delivered and receipt recorded.",
            )
        else:
            run.status = "waiting_for_farmer"
            detail = (
                "A scoped consent card is waiting for the farmer."
                if result.get("mode") == "ask"
                else "A confirmed field fact is required before the request can continue."
            )
            _step(run, "human_boundary", "waiting", detail)
        return _save(run)
    except Exception as exc:
        run.status = "failed"
        run.error = _safe_error(exc)
        _step(run, "execution", "failed", run.error)
        _save(run)
        raise
    finally:
        end_trace(trace_token)


def complete_from_result(request_id: str | None, result: dict) -> AgentRun | None:
    if not request_id:
        return None
    run = _latest_for_request(request_id)
    if run is None:
        return None
    run.decision = result.get("decision")
    run.reason_code = result.get("reason_code")
    consent_obj = result.get("consent")
    run.consent_id = result.get("consent_id") or getattr(consent_obj, "id", None)
    run.pack_id = result.get("pack_id") or getattr(consent_obj, "pack_id", None)
    run.model = last_provenance()
    if result.get("mode") == "auto" and isinstance(consent_obj, ConsentRecord):
        pack_row = store.get("packs", consent_obj.pack_id)
        if pack_row:
            delivery = partner_delivery.send(
                consent_obj,
                store.as_pack(pack_row),
                run_id=run.id,
                trace_id=run.trace_id,
            )
            run.delivery_id = delivery["id"]
        run.status = "completed"
        _step(run, "partner_delivery", "completed", "Pack delivered after the missing fact was confirmed.")
    else:
        run.status = "waiting_for_farmer"
        _step(run, "human_boundary", "waiting", "Consent is required before delivery.")
    return _save(run)


def complete_manual_consent(consent_obj: ConsentRecord) -> dict:
    pack_row = store.get("packs", consent_obj.pack_id)
    if not pack_row:
        raise RuntimeError("Pack missing at delivery time")
    run = _latest_for_request(consent_obj.request_id)
    delivery = partner_delivery.send(
        consent_obj,
        store.as_pack(pack_row),
        run_id=run.id if run else None,
        trace_id=run.trace_id if run else None,
    )
    if run:
        if run.status == "completed" and run.delivery_id == delivery["id"]:
            return delivery
        run.status = "completed"
        run.decision = "farmer_approved"
        run.consent_id = consent_obj.id
        run.pack_id = consent_obj.pack_id
        run.delivery_id = delivery["id"]
        _step(run, "farmer_approval", "completed", "Farmer approved the scoped pack.")
        _step(run, "partner_delivery", "completed", "Pack delivered to configured destinations.")
        _save(run)
    return delivery


def complete_refusal(consent_obj: ConsentRecord) -> None:
    if not consent_obj.request_id:
        return
    run = _latest_for_request(consent_obj.request_id)
    if run is None:
        return
    run.status = "completed"
    run.decision = "farmer_refused"
    run.consent_id = consent_obj.id
    _step(run, "farmer_refusal", "completed", "Farmer refused; no data was delivered.")
    _save(run)


def recent_for_farm(farm_id: str, limit: int = 5) -> list[dict]:
    rows = store.list_where("agent_runs", farm_id=farm_id)
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows[:limit]


def recent_for_partner(partner_id: str, limit: int = 10) -> list[dict]:
    rows = store.list_where("agent_runs", partner_id=partner_id)
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows[:limit]
