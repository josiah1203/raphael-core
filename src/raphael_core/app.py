"""Raphael API gateway — routing, auth, compat shims."""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from raphael_core.auth import validate_jwt
from raphael_core.health import platform_health
from raphael_core.logging_config import configure_logging
from raphael_core.metrics import REQUEST_LATENCY, REQUESTS_TOTAL, UPSTREAM_ERRORS, metrics_body, path_prefix
from raphael_core.services import SERVICE_ROUTES, service_label, service_url
from raphael_contracts.errors import ErrorResponse

configure_logging()
logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE = os.environ.get("RAPHAEL_DEFAULT_WORKSPACE", "default")
LEGACY_AUTH_PREFIX = "/api/v1/auth"

app = FastAPI(title="raphael-core", version="0.1.0")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-raphael-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Raphael-Request-Id"] = request_id
    return response


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
    if path.startswith("/v1/events/"):
        return path.replace("/v1/events/", "/v1/audit/events/", 1)
    if path.startswith("/v1/iam/"):
        return path.replace("/v1/iam/", "/v1/admin/iam/", 1)
    if path.startswith("/v1/ingest/"):
        return path.replace("/v1/ingest/", "/v1/artifacts/ingest/", 1)
    if path.startswith("/v1/objects/"):
        return path.replace("/v1/objects/", "/v1/artifacts/objects/", 1)
    if path.startswith("/v1/adapters"):
        return path.replace("/v1/adapters", "/v1/connectors", 1)
    if path.startswith("/v1/webhooks"):
        return path.replace("/v1/webhooks", "/v1/connectors/webhooks", 1)
    if path == "/v1/search" or path.startswith("/v1/search/"):
        return "/v1/intelligence/ask" if path == "/v1/search" else path.replace("/v1/search", "/v1/intelligence", 1)
    if path == "/v1/suggestions" or path.startswith("/v1/suggestions/"):
        return path.replace("/v1/suggestions", "/v1/intelligence/suggestions", 1)
    if path.startswith("/v1/workflows"):
        return path.replace("/v1/workflows", "/v1/automations", 1)
    if path.startswith(LEGACY_AUTH_PREFIX):
        return path.replace(LEGACY_AUTH_PREFIX, "/v1/identity", 1)
    return path


def _resolve_upstream(path: str) -> tuple[str, str, str] | None:
    rewritten = _rewrite_compat_path(path)
    for prefix, env_key in SERVICE_ROUTES:
        if rewritten.startswith(prefix) or path.startswith(prefix):
            return service_url(env_key), rewritten, service_label(env_key)
    return None


def _validate_org_membership(user_id: str, org_id: str) -> bool:
    orgs_url = os.environ.get("RAPHAEL_ORGS_URL", "http://127.0.0.1:8082").rstrip("/")
    try:
        with httpx.Client(timeout=3.0) as client:
            res = client.get(f"{orgs_url}/v1/orgs/{org_id}/membership/{user_id}")
            return res.status_code == 200
    except httpx.RequestError:
        return False


def _inject_auth_headers(request: Request, headers: dict[str, str]) -> tuple[dict[str, str], str, ErrorResponse | None]:
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key", "")
    request_id = getattr(request.state, "request_id", None) or request.headers.get("x-raphael-request-id") or str(uuid.uuid4())
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
    auth_error: ErrorResponse | None = None
    if not any(path.startswith(p) for p in public_paths):
        ctx = validate_jwt(auth or None, api_key or None)
        if ctx:
            headers.update(ctx)
            jwt_org = headers.get("X-Raphael-Org-Id", "")
            org_override = request.headers.get("x-raphael-org-id")
            if org_override:
                user_id = headers.get("X-Raphael-User-Id", "")
                if org_override != jwt_org and not _validate_org_membership(user_id, org_override):
                    auth_error = ErrorResponse(
                        code="forbidden",
                        message=f"User is not a member of organization {org_override}",
                    )
                else:
                    headers["X-Raphael-Org-Id"] = org_override
    return headers, request_id, auth_error


@app.get("/health")
def health() -> dict[str, str]:
    return platform_health()


@app.get("/metrics")
def prometheus_metrics() -> PlainTextResponse:
    body, content_type = metrics_body()
    return PlainTextResponse(content=body, media_type=content_type)


@app.get("/v1/config")
def platform_config() -> dict[str, Any]:
    return {
        "api_base": os.environ.get("RAPHAEL_PUBLIC_API_BASE", "http://127.0.0.1:8080"),
        "ui_port": int(os.environ.get("RAPHAEL_UI_PORT", "5173")),
        "mode": "raphael",
        "platform_name": "Raphael",
        "version": "0.1.0",
        "features": {
            "reviews": True,
            "automations": True,
            "connectors": True,
            "intelligence": True,
            "comments": True,
            "messaging": True,
            "links": True,
            "registry": True,
            "environments": True,
            "analytics": True,
        },
        "deprecation": {"repos_api": "Use /v1/workspaces/{id}/modules instead of /v1/repos"},
    }


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(full_path: str, request: Request) -> Response:
    path = f"/{full_path}"
    prefix = path_prefix(path)
    started = time.perf_counter()

    if path in ("/health", "/v1/health"):
        return JSONResponse(platform_health())
    upstream = _resolve_upstream(path)
    if not upstream:
        err = ErrorResponse(code="not_found", message=f"No route for {path}")
        REQUESTS_TOTAL.labels(method=request.method, path_prefix=prefix, status_code="404").inc()
        return JSONResponse(status_code=404, content=err.model_dump())

    base_url, target_path, service_name = upstream
    url = f"{base_url}{target_path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers, request_id, auth_error = _inject_auth_headers(request, {})
    if auth_error:
        REQUESTS_TOTAL.labels(method=request.method, path_prefix=prefix, status_code="403").inc()
        return JSONResponse(
            status_code=403,
            content=auth_error.model_dump(),
            headers={"X-Raphael-Request-Id": request_id},
        )
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
            UPSTREAM_ERRORS.labels(path_prefix=prefix).inc()
            REQUESTS_TOTAL.labels(method=request.method, path_prefix=prefix, status_code="502").inc()
            logger.warning(
                "upstream_error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "upstream": base_url,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            err = ErrorResponse(
                code="upstream_error",
                message=f"Service {service_name} unreachable: {exc}",
            )
            return JSONResponse(
                status_code=502,
                content=err.model_dump(),
                headers={
                    "X-Raphael-Request-Id": request_id,
                    "X-Raphael-Upstream-Service": service_name,
                },
            )

    latency = time.perf_counter() - started
    status = str(upstream_res.status_code)
    REQUESTS_TOTAL.labels(method=request.method, path_prefix=prefix, status_code=status).inc()
    REQUEST_LATENCY.labels(method=request.method, path_prefix=prefix).observe(latency)
    logger.info(
        "proxy_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "status_code": upstream_res.status_code,
            "upstream": base_url,
            "latency_ms": round(latency * 1000, 2),
        },
    )

    out_headers: dict[str, str] = {"X-Raphael-Request-Id": request_id}
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
