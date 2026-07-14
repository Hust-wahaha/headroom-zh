from __future__ import annotations

import time

from headroom.transforms.content_detector import ContentType
from headroom.transforms.content_router import (
    CompressionStrategy,
    ContentRouter,
    ContentRouterConfig,
    RouterCompressionResult,
    RoutingDecision,
)


class _Tokenizer:
    def count_text(self, content: str) -> int:
        return len(content.split())


def _compression_result(content: str, compressed: str) -> RouterCompressionResult:
    return RouterCompressionResult(
        compressed=compressed,
        original=content,
        strategy_used=CompressionStrategy.TEXT,
        routing_log=[
            RoutingDecision(
                content_type=ContentType.PLAIN_TEXT,
                strategy=CompressionStrategy.TEXT,
                original_tokens=len(content.split()),
                compressed_tokens=len(compressed.split()),
            )
        ],
    )


def _router() -> ContentRouter:
    return ContentRouter(
        ContentRouterConfig(
            protect_recent_code=0,
            protect_analysis_context=False,
            skip_user_messages=False,
        )
    )


def _messages() -> list[dict[str, str]]:
    return [
        {"role": "assistant", "content": "frozen prefix content remains unchanged"},
        {
            "role": "assistant",
            "content": "pending cache miss content takes the inline compression branch",
        },
    ]


def test_single_cache_miss_fails_open_at_deadline(monkeypatch, caplog):
    router = _router()

    def slow_compress(content, *, context="", bias=1.0):
        time.sleep(0.2)
        return _compression_result(content, "compressed output")

    monkeypatch.setattr(router, "compress", slow_compress)
    monkeypatch.setenv("HEADROOM_COMPRESSION_DEADLINE_MS", "10")

    started = time.perf_counter()
    result = router.apply(
        _messages(),
        _Tokenizer(),
        frozen_message_count=1,
        min_tokens_to_compress=1,
    )

    assert time.perf_counter() - started < 0.12
    assert result.messages[1]["content"] == _messages()[1]["content"]
    assert "failing open via PASSTHROUGH" in caplog.text


def test_single_cache_miss_preserves_under_deadline_output(monkeypatch):
    router = _router()
    monkeypatch.setattr(
        router,
        "compress",
        lambda content, *, context="", bias=1.0: _compression_result(content, "compressed output"),
    )
    monkeypatch.setenv("HEADROOM_COMPRESSION_DEADLINE_MS", "1000")

    result = router.apply(
        _messages(),
        _Tokenizer(),
        frozen_message_count=1,
        min_tokens_to_compress=1,
    )

    assert result.messages[1]["content"] == "compressed output"


def test_single_cache_miss_preserves_disabled_deadline(monkeypatch):
    router = _router()
    monkeypatch.setattr(
        router,
        "compress",
        lambda content, *, context="", bias=1.0: _compression_result(content, "compressed output"),
    )
    monkeypatch.setenv("HEADROOM_COMPRESSION_DEADLINE_MS", "0")

    result = router.apply(
        _messages(),
        _Tokenizer(),
        frozen_message_count=1,
        min_tokens_to_compress=1,
    )

    assert result.messages[1]["content"] == "compressed output"
