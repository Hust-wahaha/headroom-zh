"""Token counting must run off the event loop (GH #1701): the Anthropic messages
handler resolved the tokenizer and counted the conversation inline in the async
handler. For HF-backed models (e.g. deepseek-*) first use triggers an unbounded
network download, freezing the whole server (610s request, then /livez, /readyz
and /health hang until kill). The fix routes resolution + counting through
HeadroomProxy._count_tokens_offloaded (compression executor, bounded by
COMPRESSION_TIMEOUT_SECONDS, fail-open to estimation), and offloads the inline
batch pipeline.apply() calls the same way.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time

from headroom.proxy.handlers.anthropic import AnthropicHandlerMixin
from headroom.proxy.handlers.batch import BatchHandlerMixin
from headroom.proxy.server import ProxyConfig, create_app
from headroom.tokenizers import EstimatingTokenCounter


def _make_proxy():  # noqa: ANN202 — returns the internal HeadroomProxy
    app = create_app(
        ProxyConfig(
            optimize=True,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
        )
    )
    return app.state.proxy


def test_handlers_offload_token_counting_and_batch_apply() -> None:
    """Wiring guard: the request paths must use the offloaded helpers, not inline
    get_tokenizer/count_messages or pipeline.apply on the event loop."""
    fn = AnthropicHandlerMixin.handle_anthropic_messages
    assert inspect.iscoroutinefunction(fn)
    src = inspect.getsource(fn)
    assert "_count_tokens_offloaded(" in src, "token counting not offloaded"
    assert "tokenizer = get_tokenizer(" not in src, "tokenizer resolved inline on the loop"

    for mixin, method in (
        (AnthropicHandlerMixin, "handle_anthropic_batch_create"),
        (BatchHandlerMixin, "handle_google_batch_create"),
        (BatchHandlerMixin, "_compress_batch_jsonl"),
    ):
        fn = getattr(mixin, method)
        assert inspect.iscoroutinefunction(fn), f"{method} must be async"
        src = inspect.getsource(fn)
        if "pipeline.apply(" in src:
            assert "_run_compression_in_executor(" in src, f"{method}: apply() not offloaded"
            assert "COMPRESSION_TIMEOUT_SECONDS" in src, f"{method}: offload missing timeout"

    helper_src = inspect.getsource(AnthropicHandlerMixin._count_tokens_offloaded)
    assert "COMPRESSION_TIMEOUT_SECONDS" in helper_src
    assert "EstimatingTokenCounter" in helper_src, "helper must fail open to estimation"


async def test_count_tokens_offloaded_runs_on_worker_thread(monkeypatch) -> None:  # noqa: ANN001
    proxy = _make_proxy()
    loop_thread = threading.current_thread().name
    seen: dict[str, str] = {}

    class _SpyTokenizer(EstimatingTokenCounter):
        def count_messages(self, messages):  # noqa: ANN001, ANN201
            seen["thread"] = threading.current_thread().name
            return super().count_messages(messages)

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda *a, **k: _SpyTokenizer())

    _, tokens = await proxy._count_tokens_offloaded("gpt-4", [{"role": "user", "content": "hi"}])

    assert tokens > 0
    assert seen["thread"].startswith("headroom-compress")
    assert seen["thread"] != loop_thread


async def test_count_tokens_offloaded_keeps_loop_responsive(monkeypatch) -> None:  # noqa: ANN001
    """A slow tokenizer (stand-in for an HF network load) must not starve the loop —
    the pre-fix inline call yielded ~0 ticks here."""
    proxy = _make_proxy()
    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    class _SlowTokenizer(EstimatingTokenCounter):
        def count_messages(self, messages):  # noqa: ANN001, ANN201
            time.sleep(0.3)
            return super().count_messages(messages)

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda *a, **k: _SlowTokenizer())

    tick_task = asyncio.create_task(_ticker())
    try:
        _, tokens = await proxy._count_tokens_offloaded("m", [{"role": "user", "content": "hi"}])
    finally:
        tick_task.cancel()

    assert tokens > 0
    assert ticks >= 5


async def test_count_tokens_offloaded_fails_open(monkeypatch) -> None:  # noqa: ANN001
    """Resolution errors and timeouts downgrade to estimation instead of raising."""
    proxy = _make_proxy()

    def _boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("tokenizer backend exploded")

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", _boom)

    tokenizer, tokens = await proxy._count_tokens_offloaded(
        "deepseek-chat", [{"role": "user", "content": "hello world"}]
    )

    assert isinstance(tokenizer, EstimatingTokenCounter)
    assert tokens > 0
    # Logged-once bookkeeping records the downgraded model.
    assert "deepseek-chat" in proxy._token_count_fallback_models
