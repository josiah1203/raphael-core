"""Gateway upstream service registry."""

from __future__ import annotations

import os

SERVICE_ROUTES: list[tuple[str, str]] = [
    ("/v1/identity", "RAPHAEL_IDENTITY_URL"),
    ("/v1/orgs", "RAPHAEL_ORGS_URL"),
    ("/v1/workspaces", "RAPHAEL_WORKSPACES_URL"),
    ("/v1/artifacts", "RAPHAEL_ARTIFACTS_URL"),
    ("/v1/ingest", "RAPHAEL_ARTIFACTS_URL"),
    ("/v1/objects", "RAPHAEL_ARTIFACTS_URL"),
    ("/v1/events", "RAPHAEL_AUDIT_URL"),
    ("/v1/iam", "RAPHAEL_ADMIN_URL"),
    ("/v1/sessions", "RAPHAEL_SYNC_URL"),
    ("/v1/projects", "RAPHAEL_WORKSPACES_URL"),
    ("/v1/reviews", "RAPHAEL_REVIEWS_URL"),
    ("/v1/automations", "RAPHAEL_AUTOMATION_URL"),
    ("/v1/connectors", "RAPHAEL_CONNECTORS_URL"),
    ("/v1/webhooks", "RAPHAEL_CONNECTORS_URL"),
    ("/v1/adapters", "RAPHAEL_CONNECTORS_URL"),
    ("/v1/notifications", "RAPHAEL_NOTIFICATIONS_URL"),
    ("/v1/audit", "RAPHAEL_AUDIT_URL"),
    ("/v1/timeline", "RAPHAEL_AUDIT_URL"),
    ("/v1/graph", "RAPHAEL_GRAPH_URL"),
    ("/v1/intelligence", "RAPHAEL_AI_URL"),
    ("/v1/ai", "RAPHAEL_AI_URL"),
    ("/v1/admin", "RAPHAEL_ADMIN_URL"),
    ("/v1/sync", "RAPHAEL_SYNC_URL"),
    ("/v1/ops", "RAPHAEL_OPS_URL"),
    ("/v1/rwu", "RAPHAEL_RWU_URL"),
    ("/v1/repos", "RAPHAEL_WORKSPACES_URL"),
    ("/v1/comments", "RAPHAEL_COMMENTS_URL"),
    ("/v1/messaging", "RAPHAEL_MESSAGING_URL"),
    ("/v1/links", "RAPHAEL_LINKS_URL"),
    ("/v1/registry", "RAPHAEL_REGISTRY_URL"),
    ("/v1/environments", "RAPHAEL_ENVIRONMENTS_URL"),
    ("/v1/analytics", "RAPHAEL_ANALYTICS_URL"),
]


def service_url(env_key: str) -> str:
    return os.environ.get(env_key, "http://127.0.0.1:8080").rstrip("/")


def service_label(env_key: str) -> str:
    return env_key.removeprefix("RAPHAEL_").removesuffix("_URL").replace("_", "-").lower()


def iter_unique_services() -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for _, env_key in SERVICE_ROUTES:
        if env_key in seen:
            continue
        seen.add(env_key)
        out.append((service_label(env_key), env_key))
    return out
