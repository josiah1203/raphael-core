"""Gateway-native health endpoints with optional upstream aggregation."""

from __future__ import annotations

import os
from typing import Any

import httpx

from raphael_core.services import iter_unique_services, service_label, service_url


def gateway_health() -> dict[str, str]:
    return {"status": "ok", "service": "raphael-core"}


def _aggregate_enabled() -> bool:
    return os.environ.get("RAPHAEL_HEALTH_AGGREGATE", "").lower() in ("1", "true", "yes")


def aggregate_health(timeout_s: float = 1.0) -> dict[str, Any]:
    """Probe each configured upstream service /health endpoint."""
    services: dict[str, str] = {}
    degraded = False
    with httpx.Client(timeout=timeout_s) as client:
        for name, env_key in iter_unique_services():
            url = f"{service_url(env_key)}/health"
            try:
                res = client.get(url)
                if res.status_code == 200:
                    services[name] = "ok"
                else:
                    services[name] = f"error:{res.status_code}"
                    degraded = True
            except httpx.RequestError:
                services[name] = "unreachable"
                degraded = True
    return {
        "status": "degraded" if degraded else "ok",
        "service": "raphael-core",
        "services": services,
    }


def platform_health() -> dict[str, Any]:
    if _aggregate_enabled():
        return aggregate_health()
    return gateway_health()
