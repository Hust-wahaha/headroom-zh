"""Tests for the /v1/compress endpoint in the proxy server.

These tests verify that the compression-only endpoint works correctly
for the TypeScript SDK and other HTTP clients.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

# Skip if fastapi not available
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from headroom.proxy.server import ProxyConfig, create_app


@pytest.fixture
def client():
    """Create test client with optimization enabled."""
    config = ProxyConfig(
        optimize=True,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
    )
    app = create_app(config)
    # /v1/compress is loopback-gated (#1227).
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as c:
        yield c


@pytest.fixture
def client_no_optimize():
    """Create test client with optimization disabled."""
    config = ProxyConfig(
        optimize=False,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
    )
    app = create_app(config)
    # /v1/compress is loopback-gated (#1227).
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as c:
        yield c


class TestCompressEndpointValidation:
    """Test request validation for /v1/compress."""

    def test_missing_messages_returns_400(self, client):
        """Request without messages field should return 400."""
        response = client.post("/v1/compress", json={"model": "gpt-4"})
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "invalid_request"
        assert "messages" in data["error"]["message"]

    def test_missing_model_returns_400(self, client):
        """Request without model field should return 400."""
        response = client.post(
            "/v1/compress",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "invalid_request"
        assert "model" in data["error"]["message"]

    def test_invalid_json_returns_400(self, client):
        """Request with invalid JSON should return 400."""
        response = client.post(
            "/v1/compress",
            content=b"not valid json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["type"] == "invalid_request"


class TestCompressEndpointBasic:
    """Test basic compress endpoint behavior."""

    def test_empty_messages_returns_empty(self, client):
        """Empty messages list should return as-is with zero metrics."""
        response = client.post(
            "/v1/compress",
            json={"messages": [], "model": "gpt-4"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["tokens_before"] == 0
        assert data["tokens_after"] == 0
        assert data["tokens_saved"] == 0
        assert data["compression_ratio"] == 1.0
        assert data["transforms_applied"] == []
        assert data["ccr_hashes"] == []

    def test_basic_compression_response_shape(self, client):
        """Verify the response contains all expected fields."""
        response = client.post(
            "/v1/compress",
            json={
                "messages": [{"role": "user", "content": "Hello, world!"}],
                "model": "gpt-4",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Check all expected fields are present
        assert "messages" in data
        assert "tokens_before" in data
        assert "tokens_after" in data
        assert "tokens_saved" in data
        assert "compression_ratio" in data
        assert "transforms_applied" in data
        assert "ccr_hashes" in data

        # Messages should be a list
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) >= 1

        # Numeric fields should be non-negative
        assert data["tokens_before"] >= 0
        assert data["tokens_after"] >= 0
        assert data["tokens_saved"] >= 0
        assert data["compression_ratio"] > 0

    def test_bypass_header_returns_uncompressed(self, client):
        """X-Headroom-Bypass header should skip compression."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        response = client.post(
            "/v1/compress",
            json={"messages": messages, "model": "gpt-4"},
            headers={"x-headroom-bypass": "true"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == messages
        assert data["tokens_before"] == 0
        assert data["tokens_after"] == 0
        assert data["tokens_saved"] == 0
        assert data["compression_ratio"] == 1.0
        assert data["transforms_applied"] == []
        assert data["ccr_hashes"] == []

    def test_bypass_header_case_insensitive(self, client):
        """Bypass header should be case-insensitive."""
        messages = [{"role": "user", "content": "Hello"}]
        response = client.post(
            "/v1/compress",
            json={"messages": messages, "model": "gpt-4"},
            headers={"x-headroom-bypass": "TRUE"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == messages


class TestCompressEndpointCompression:
    """Test that actual compression happens for large content."""

    def test_large_tool_output_gets_compressed(self, client):
        """Large tool output content should result in tokens_saved > 0."""
        # Create a large repetitive tool output that should be compressible
        large_data = json.dumps(
            [
                {
                    "id": i,
                    "name": f"Item {i}",
                    "description": f"This is a detailed description for item number {i}. "
                    f"It contains various attributes and metadata that are typical "
                    f"of API responses. The item has a status of active and was "
                    f"created on 2024-01-{(i % 28) + 1:02d}. Additional fields "
                    f"include category=electronics, price={i * 10.99:.2f}, "
                    f"rating={4.0 + (i % 10) / 10:.1f}, stock={i * 5}.",
                    "tags": ["electronics", "sale", "featured", "new-arrival"],
                    "metadata": {
                        "created_by": "system",
                        "updated_at": "2024-01-15T00:00:00Z",
                        "version": i,
                        "source": "api",
                    },
                }
                for i in range(200)
            ]
        )

        messages = [
            {"role": "user", "content": "What items are available?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "list_items",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": large_data,
            },
            {"role": "user", "content": "Summarize the first 5 items."},
        ]

        response = client.post(
            "/v1/compress",
            json={"messages": messages, "model": "gpt-4"},
        )
        assert response.status_code == 200
        data = response.json()

        # With a large tool output, the pipeline should process successfully
        assert data["tokens_before"] > 0
        assert data["tokens_after"] > 0
        assert data["tokens_after"] <= data["tokens_before"]
        assert data["tokens_saved"] == data["tokens_before"] - data["tokens_after"]
        assert 0 < data["compression_ratio"] <= 1.0
        assert isinstance(data["transforms_applied"], list)

    def test_small_content_may_not_compress(self, client):
        """Small messages may not get compressed but should still work."""
        response = client.post(
            "/v1/compress",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "model": "gpt-4",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Should still return valid response regardless of compression
        assert data["tokens_before"] >= 0
        assert data["tokens_after"] >= 0
        assert isinstance(data["transforms_applied"], list)

    def test_success_records_request_outcome(self, client, monkeypatch):
        """A completed compression should update request metrics."""
        proxy = client.app.state.proxy
        result = SimpleNamespace(
            messages=[{"role": "user", "content": "compressed"}],
            tokens_before=12,
            tokens_after=7,
            transforms_applied=["test_transform"],
            transforms_summary={"test_transform": 1},
            markers_inserted=[],
        )
        run_compression = AsyncMock(return_value=result)
        record_outcome = AsyncMock()
        monkeypatch.setattr(proxy, "_run_compression_in_executor", run_compression)
        monkeypatch.setattr(proxy, "_record_request_outcome", record_outcome)

        response = client.post(
            "/v1/compress",
            json={
                "messages": [{"role": "user", "content": "compress me"}],
                "model": "gpt-4",
            },
        )

        assert response.status_code == 200
        record_outcome.assert_awaited_once()
        outcome = record_outcome.await_args.args[0]
        assert outcome.provider == "compress"
        assert outcome.model == "gpt-4"
        assert outcome.original_tokens == 12
        assert outcome.optimized_tokens == 7
        assert outcome.tokens_saved == 5
        assert outcome.attempted_input_tokens == 12
        assert outcome.num_messages == 1
        assert outcome.transforms_applied == ("test_transform",)
        assert outcome.total_latency_ms >= 0

    def test_compression_error_records_failed_request(self, client, monkeypatch):
        """A hard compression failure should increment failed metrics."""
        proxy = client.app.state.proxy
        run_compression = AsyncMock(side_effect=RuntimeError("compression broke"))
        record_failed = AsyncMock()
        monkeypatch.setattr(proxy, "_run_compression_in_executor", run_compression)
        monkeypatch.setattr(proxy.metrics, "record_failed", record_failed)

        response = client.post(
            "/v1/compress",
            json={
                "messages": [{"role": "user", "content": "compress me"}],
                "model": "gpt-4",
            },
        )

        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "type": "compression_error",
                "message": "compression broke",
            }
        }
        record_failed.assert_awaited_once_with(provider="compress")

    def test_compression_timeout_records_fail_open_outcome(self, client, monkeypatch):
        """A timeout should count as a zero-savings completed request."""
        proxy = client.app.state.proxy
        run_compression = AsyncMock(side_effect=TimeoutError)
        record_outcome = AsyncMock()
        record_compression_failed = Mock()
        monkeypatch.setattr(proxy, "_run_compression_in_executor", run_compression)
        monkeypatch.setattr(proxy, "_record_request_outcome", record_outcome)
        monkeypatch.setattr(
            proxy.metrics,
            "record_compression_failed",
            record_compression_failed,
        )
        messages = [{"role": "user", "content": "compress me"}]

        response = client.post(
            "/v1/compress",
            json={"messages": messages, "model": "gpt-4"},
        )

        assert response.status_code == 200
        assert response.json()["messages"] == messages
        assert response.json()["skip_reason"] == "compression_timeout"
        record_compression_failed.assert_called_once_with("timeout")
        record_outcome.assert_awaited_once()
        outcome = record_outcome.await_args.args[0]
        assert outcome.provider == "compress"
        assert outcome.model == "gpt-4"
        assert outcome.original_tokens == 0
        assert outcome.optimized_tokens == 0
        assert outcome.tokens_saved == 0


class TestCompressEndpointDoesNotBlockLoop:
    """/v1/compress must offload to the compression executor so a slow/large
    payload cannot freeze the single event loop (#718)."""

    async def test_compress_does_not_block_liveness(self, monkeypatch):
        import asyncio
        import threading
        from types import SimpleNamespace

        import httpx

        config = ProxyConfig(
            optimize=True,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
        )
        app = create_app(config)
        proxy = app.state.proxy

        entered = threading.Event()
        release = threading.Event()

        def blocking_apply(**kwargs):
            # Stand in for a large CPU-bound compression: blocks its worker until
            # released. If this ran inline on the loop (the bug), the loop would
            # be frozen and /livez below could not be served.
            entered.set()
            release.wait(timeout=10)
            return SimpleNamespace(
                messages=kwargs["messages"],
                tokens_before=10,
                tokens_after=5,
                transforms_applied=[],
                transforms_summary={},
                markers_inserted=[],
            )

        monkeypatch.setattr(proxy.openai_pipeline, "apply", blocking_apply)

        # /v1/compress is loopback-gated (#1227) — present as 127.0.0.1.
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            compress = asyncio.create_task(
                client.post(
                    "/v1/compress",
                    json={
                        "messages": [{"role": "user", "content": "hello world"}],
                        "model": "gpt-4",
                    },
                )
            )
            # Wait until the compression is actually in flight (running in the
            # executor thread), then prove the loop is still responsive.
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "compression never started"

            livez = await asyncio.wait_for(client.get("/livez"), timeout=5)
            assert livez.status_code == 200
            assert livez.json()["alive"] is True
            # The compression is still blocked — /livez was served concurrently.
            assert not compress.done()

            release.set()
            resp = await asyncio.wait_for(compress, timeout=5)
            assert resp.status_code == 200
            assert resp.json()["tokens_saved"] == 5
