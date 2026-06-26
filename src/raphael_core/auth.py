"""JWT validation middleware for raphael-core gateway."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_jwt(token: str, secret: str) -> dict[str, Any] | None:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")

        def pad(s: str) -> str:
            return s + "=" * (-len(s) % 4)

        body = json.loads(base64.urlsafe_b64decode(pad(body_b64)))
        expected = hmac.new(secret.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256).digest()
        if _b64url(expected) != sig_b64:
            return None
        if body.get("exp", 0) < time.time():
            return None
        return body
    except Exception:
        return None


def validate_jwt(authorization: str | None, api_key: str | None) -> dict[str, str] | None:
    """Return X-Raphael headers if auth valid, else None."""
    secret = os.environ.get("RAPHAEL_JWT_SECRET", "dev-secret-with-32-byte-minimum-length!!")
    identity_url = os.environ.get("RAPHAEL_IDENTITY_URL", "http://127.0.0.1:8081").rstrip("/")

    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        payload = _decode_jwt(token, secret)
        if payload:
            return {
                "X-Raphael-User-Id": str(payload.get("sub", "usr_default")),
                "X-Raphael-Org-Id": str(payload.get("org_id", "org_default")),
                "X-Raphael-Scopes": "read,write",
            }

    if api_key:
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(f"{identity_url}/v1/identity/verify-key", json={"api_key": api_key})
                if res.status_code == 200:
                    data: dict[str, Any] = res.json()
                    return {
                        "X-Raphael-User-Id": data.get("user_id", "usr_default"),
                        "X-Raphael-Org-Id": data.get("org_id", "org_default"),
                        "X-Raphael-Scopes": ",".join(data.get("scopes", ["read", "write"])),
                    }
        except httpx.RequestError:
            pass

    return None
