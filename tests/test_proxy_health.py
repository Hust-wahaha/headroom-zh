from fastapi.testclient import TestClient

from headroom.proxy.models import ProxyConfig
from headroom.proxy.server import create_app


def test_readyz_excludes_kompress_from_aggregate_readiness(monkeypatch):
    monkeypatch.setenv("HEADROOM_SKIP_UPSTREAM_CHECK", "1")

    app = create_app(
        ProxyConfig(
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
        )
    )
    app.state.ready = True
    proxy = app.state.proxy
    proxy.http_client = object()
    proxy.warmup.kompress.mark_error("model not cached")

    client = TestClient(app)
    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["status"] == "healthy"
    assert payload["checks"]["kompress"] == {
        "enabled": True,
        "ready": False,
        "status": "unhealthy",
        "backend": None,
    }
