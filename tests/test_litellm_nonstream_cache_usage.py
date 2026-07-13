"""Non-streaming LiteLLM responses must surface Bedrock cache token usage (GH #1345).

LiteLLM reports ``prompt_tokens`` as the total prompt size including cached
tokens, while the Anthropic response shape expects ``input_tokens`` to exclude
cache reads/writes and to carry ``cache_read_input_tokens`` /
``cache_creation_input_tokens`` alongside. The streaming and OpenAI paths
already map these fields; the non-streaming ``complete_message`` path dropped
them, so a working Bedrock prompt cache was indistinguishable from a broken
one for non-streaming clients.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

litellm_backend = pytest.importorskip("headroom.backends.litellm")
_anthropic_usage_from_litellm = litellm_backend._anthropic_usage_from_litellm


def test_plain_usage_without_cache_fields() -> None:
    usage = _anthropic_usage_from_litellm(SimpleNamespace(prompt_tokens=100, completion_tokens=7))
    assert usage == {"input_tokens": 100, "output_tokens": 7}


def test_cache_read_surfaced_and_input_excludes_cached() -> None:
    usage = _anthropic_usage_from_litellm(
        SimpleNamespace(
            prompt_tokens=1213,
            completion_tokens=4,
            cache_read_input_tokens=1202,
            cache_creation_input_tokens=0,
        )
    )
    assert usage["input_tokens"] == 11
    assert usage["cache_read_input_tokens"] == 1202
    assert usage["cache_creation_input_tokens"] == 0


def test_cache_write_on_first_call() -> None:
    usage = _anthropic_usage_from_litellm(
        SimpleNamespace(
            prompt_tokens=1237,
            completion_tokens=4,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=1226,
        )
    )
    assert usage["input_tokens"] == 11
    assert usage["cache_creation_input_tokens"] == 1226


def test_prompt_tokens_details_fallback() -> None:
    usage = _anthropic_usage_from_litellm(
        SimpleNamespace(
            prompt_tokens=1213,
            completion_tokens=4,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1202, cache_creation_tokens=0),
        )
    )
    assert usage["input_tokens"] == 11
    assert usage["cache_read_input_tokens"] == 1202


def test_input_tokens_never_negative() -> None:
    usage = _anthropic_usage_from_litellm(
        SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=1,
            cache_read_input_tokens=15,
        )
    )
    assert usage["input_tokens"] == 0
