"""Raphael API gateway — routing, auth, compat shims."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from raphael_core.auth import validate_jwt
from raphael_contracts.errors import ErrorResponse

DEFAULT_WORKSPACE = os.environ.get("RAPHAEL_DEFAULT_WORKSPACE", "default")

SERVICE_ROUTES: list[tuple[str, str]] = [
    ("/v1/identity", "RAPHAEL_IDENTITY_URL"),
    ("/v1/orgs", "RAPHAEL_ORGS_URL"),
    ("/v1/workspaces", "RAPHAEL_WORKSPACES_URL"),
    ("/v1/artifacts", "RAPHAEL_ARTIFACTS_URL"),
    ("/v1/reviews", "RAPHAEL_REVIEWS_URL"),
    ("/v1/automations", "RAPHAEL_AUTOMATION_URL"),
    ("/v1/connectors", "RAPHAEL_CONNECTORS_URL"),
    ("/v1/webhooks", "RAPHAEL_CONNECTORS_URL"),
    ("/v1/adapters", "RAPHAEL_CONNECTORS_URL"),  # compat alias
    ("/v1/notifications", "RAPHAEL_NOTIFICATIONS_URL"),
    ("/v1/audit", "RAPHAEL_AUDIT_URL"),
    ("/v1/timeline", "RAPHAEL_AUDIT_URL"),  # compat → /v1/audit/timeline
    ("/v1/graph", "RAPHAEL_GRAPH_URL"),
    ("/v1/ai", "RAPHAEL_AI_URL"),
    ("/v1/admin", "RAPHAEL_ADMIN_URL"),
    ("/v1/sync", "RAPHAEL_SYNC_URL"),
    ("/v1/ops", "RAPHAEL_OPS_URL"),
    ("/v1/rwu", "RAPHAEL_RWU_URL"),
    ("/v1/repos", "RAPHAEL_WORKSPACES_URL"),  # compat prefix
]

LEGACY_AUTH_PREFIX = "/api/v1/auth"
PAUSED_TIER2_PREFIXES = (
    "/v1/comments",
    "/v1/messaging",
    "/v1/links",
    "/v1/workflows",
    "/v1/registry",
    "/v1/environments",
    "/v1/analytics",
    "/v1/search",
)

app = FastAPI(title="raphael-core", version="0.1.0")


def _service_url(env_key: str) -> str:
    return os.environ.get(env_key, "http://127.0.0.1:8080").rstrip("/")


def _rewrite_compat_path(path: str) -> str:
    """Map legacy /v1/repos/* to /v1/workspaces/{default}/modules/*."""
    if path == "/v1/repos":
        return f"/v1/workspaces/{DEFAULT_WORKSPACE}/modules"
    m = re.match(r"^/v1/repos/([^/]+)(/.*)?$", path)
    if m:
        module_id, rest = m.group(1), m.group(2) or ""
        return f"/v1/workspaces/{DEFAULT_WORKSPACE}/modules/{module_id}{rest}"
    if path == "/v1/timeline":
        return "/v1/audit/timeline"
    if path.startswith("/v1/adapters"):
        return path.replace("/v1/adapters", "/v1/connectors", 1)
    if path.startswith("/v1/webhooks"):
        return path.replace("/v1/webhooks", "/v1/connectors/webhooks", 1)
    if path.startswith(LEGACY_AUTH_PREFIX):
        return path.replace(LEGACY_AUTH_PREFIX, "/v1/identity", 1)
    return path


def _resolve_upstream(path: str) -> tuple[str, str] | None:
    rewritten = _rewrite_compat_path(path)
    for prefix, env_key in SERVICE_ROUTES:
        if rewritten.startswith(prefix) or path.startswith(prefix):
            return _service_url(env_key), rewritten
    return None


def _inject_auth_headers(request: Request, headers: dict[str, str]) -> dict[str, str]:
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key", "")
    request_id = request.headers.get("x-raphael-request-id") or str(uuid.uuid4())
    headers["X-Raphael-Request-Id"] = request_id
    if auth:
        headers["Authorization"] = auth
    if api_key:
        headers["X-API-Key"] = api_key
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    accept = request.headers.get("accept")
    if accept:
        headers["Accept"] = accept
    public_paths = ("/health", "/v1/health", "/v1/config", "/v1/identity/register", "/v1/identity/login")
    path = request.url.path
    if not any(path.startswith(p) for p in public_paths):
        ctx = validate_jwt(auth or None, api_key or None)
        if ctx:
            headers.update(ctx)
    return headers


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "raphael-core"}


@app.get("/v1/config")
def platform_config() -> dict[str, Any]:
    return {
        "api_base": os.environ.get("RAPHAEL_PUBLIC_API_BASE", "http://127.0.0.1:8080"),
        "ui_port": int(os.environ.get("RAPHAEL_UI_PORT", "5173")),
        "mode": "raphael",
        "platform_name": "Raphael",
        "version": "0.1.0",
        "features": {"reviews": True, "automations": True, "connectors": True},
        "deprecation": {"repos_api": "Use /v1/workspaces/{id}/modules instead of /v1/repos"},
    }


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(full_path: str, request: Request) -> Response:
    path = f"/{full_path}"
    if path in ("/health", "/v1/health"):
        return JSONResponse(health())
    if any(path.startswith(prefix) for prefix in PAUSED_TIER2_PREFIXES):
        err = ErrorResponse(
            code="not_implemented",
            message=f"{path} is paused pending Calliope source parity",
        )
        return JSONResponse(status_code=501, content=err.model_dump())

    upstream = _resolve_upstream(path)
    if not upstream:
        err = ErrorResponse(code="not_found", message=f"No route for {path}")
        return JSONResponse(status_code=404, content=err.model_dump())

    base_url, target_path = upstream
    url = f"{base_url}{target_path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = _inject_auth_headers(request, {})
    body = await request.body()

    compat = path != target_path
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            upstream_res = await client.request(
                request.method,
                url,
                headers=headers,
                content=body if body else None,
            )
        except httpx.RequestError as exc:
            err = ErrorResponse(code="upstream_error", message=str(exc))
            return JSONResponse(status_code=502, content=err.model_dump())

    out_headers: dict[str, str] = {}
    if compat:
        out_headers["Deprecation"] = "true"
        out_headers["Link"] = f'<{target_path}>; rel="successor-version"'
    if upstream_res.headers.get("content-type"):
        out_headers["content-type"] = upstream_res.headers["content-type"]
    out_headers["X-Raphael-Upstream"] = base_url

    return Response(
        content=upstream_res.content,
        status_code=upstream_res.status_code,
        headers=out_headers,
    )
