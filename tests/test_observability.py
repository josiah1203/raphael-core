"""Observability: metrics endpoint and request ID propagation."""

from fastapi.testclient import TestClient

from raphael_core.app import app


def test_metrics_endpoint() -> None:
    client = TestClient(app)
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "raphael_gateway_requests_total" in res.text


def test_request_id_propagation() -> None:
    client = TestClient(app)
    res = client.get("/v1/config", headers={"X-Raphael-Request-Id": "test-req-abc"})
    assert res.status_code == 200
    assert res.headers.get("x-raphael-request-id") == "test-req-abc"


def test_request_id_generated_when_missing() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
