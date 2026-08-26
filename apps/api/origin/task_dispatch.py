"""Cloud Tasks dispatcher for retryable background AgentRun execution."""

from __future__ import annotations

from origin.config import settings


def enqueue(run_id: str) -> str:
    cfg = settings()
    if cfg.agent_dispatch.lower() != "tasks":
        return "inline"
    if not cfg.gcp_project or not cfg.api_base_url or not cfg.internal_token:
        raise RuntimeError(
            "tasks dispatch requires ORIGIN_GCP_PROJECT, ORIGIN_API_BASE_URL, "
            "and ORIGIN_INTERNAL_TOKEN"
        )

    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(cfg.gcp_project, cfg.tasks_location, cfg.tasks_queue)
    task = {
        # A stable task name makes a repeated enqueue request idempotent.
        "name": client.task_path(
            cfg.gcp_project, cfg.tasks_location, cfg.tasks_queue, run_id
        ),
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{cfg.api_base_url.rstrip('/')}/v1/internal/runs/{run_id}/execute",
            "headers": {
                "Content-Type": "application/json",
                "X-Origin-Worker-Token": cfg.internal_token,
            },
            "body": b"{}",
        }
    }
    if cfg.task_service_account:
        task["http_request"]["oidc_token"] = {
            "service_account_email": cfg.task_service_account,
            "audience": cfg.api_base_url.rstrip("/"),
        }
    created = client.create_task(parent=parent, task=task)
    return created.name
