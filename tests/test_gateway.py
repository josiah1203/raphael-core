"""Test gateway config and compat path rewriting."""

from fastapi.testclient import TestClient

from raphael_core.app import _rewrite_compat_path, app


def test_health() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["service"] == "raphael-core"


def test_v1_health_default() -> None:
    client = TestClient(app)
    res = client.get("/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "raphael-core"
    assert body["status"] == "ok"
    assert "services" not in body


def test_v1_health_aggregate(monkeypatch) -> None:
    import httpx
    from raphael_core import health as health_mod

    monkeypatch.setenv("RAPHAEL_HEALTH_AGGREGATE", "1")
    monkeypatch.setenv("RAPHAEL_ARTIFACTS_URL", "http://artifacts-upstream:8091")
    monkeypatch.setenv("RAPHAEL_WORKSPACES_URL", "http://workspaces-upstream:8083")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url: str):
            class Res:
                status_code = 200

            if "artifacts" in url:
                return Res()
            raise httpx.ConnectError("down")

    monkeypatch.setattr(health_mod.httpx, "Client", FakeClient)

    body = health_mod.aggregate_health()
    assert body["status"] == "degraded"
    assert body["services"]["artifacts"] == "ok"
    assert body["services"]["workspaces"] == "unreachable"


def test_config() -> None:
    client = TestClient(app)
    res = client.get("/v1/config")
    assert res.status_code == 200
    assert res.json()["platform_name"] == "Raphael"


def test_v1_health_gateway_native() -> None:
    client = TestClient(app)
    res = client.get("/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "raphael-core"
    assert body["status"] == "ok"


def test_v1_health_aggregate_optional(monkeypatch) -> None:
    from raphael_core import health as health_mod

    monkeypatch.setenv("RAPHAEL_HEALTH_AGGREGATE", "1")

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(health_mod.httpx, "Client", lambda timeout: FakeClient())

    client = TestClient(app)
    res = client.get("/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "services" in body
    assert isinstance(body["services"], dict)
    assert len(body["services"]) > 0


def test_compat_repos_rewrite() -> None:
    assert _rewrite_compat_path("/v1/repos") == "/v1/workspaces/default/modules"
    assert _rewrite_compat_path("/v1/repos/power-board-v2/branches") == (
        "/v1/workspaces/default/modules/power-board-v2/branches"
    )


def test_compat_adapters_rewrite() -> None:
    assert _rewrite_compat_path("/v1/adapters/kicad/connect") == "/v1/connectors/kicad/connect"


def test_upstream_error_includes_service_name(monkeypatch) -> None:
    import httpx
    from raphael_core import app as core_app

    monkeypatch.setenv("RAPHAEL_AUTOMATION_URL", "http://raphael-automation-unreachable:8095")

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            raise httpx.ConnectError("Name or service not known")

    monkeypatch.setattr(core_app.httpx, "AsyncClient", lambda **kwargs: FailingClient())

    client = TestClient(app)
    res = client.get("/v1/automations", headers={"Authorization": "Bearer invalid"})
    assert res.status_code == 502
    body = res.json()
    assert body.get("code") == "upstream_error"
    assert "automation" in body.get("message", "").lower()
