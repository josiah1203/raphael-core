"""Test gateway config and compat path rewriting."""

from fastapi.testclient import TestClient

from raphael_core.app import _rewrite_compat_path, app


def test_health() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["service"] == "raphael-core"


def test_config() -> None:
    client = TestClient(app)
    res = client.get("/v1/config")
    assert res.status_code == 200
    assert res.json()["platform_name"] == "Raphael"


def test_compat_repos_rewrite() -> None:
    assert _rewrite_compat_path("/v1/repos") == "/v1/workspaces/default/modules"
    assert _rewrite_compat_path("/v1/repos/power-board-v2/branches") == (
        "/v1/workspaces/default/modules/power-board-v2/branches"
    )


def test_compat_adapters_rewrite() -> None:
    assert _rewrite_compat_path("/v1/adapters/kicad/connect") == "/v1/connectors/kicad/connect"
