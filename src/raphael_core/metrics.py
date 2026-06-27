"""Prometheus metrics for gateway proxy traffic."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS_TOTAL = Counter(
    "raphael_gateway_requests_total",
    "Total proxied HTTP requests",
    ["method", "path_prefix", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "raphael_gateway_request_duration_seconds",
    "Proxied request latency in seconds",
    ["method", "path_prefix"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

UPSTREAM_ERRORS = Counter(
    "raphael_gateway_upstream_errors_total",
    "Upstream connection failures",
    ["path_prefix"],
)


def path_prefix(path: str) -> str:
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "v1":
        return f"/v1/{parts[1]}"
    return path.split("?")[0][:64] or "/"


def metrics_body() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
