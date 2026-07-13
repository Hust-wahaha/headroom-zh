"""Tests for output verbosity steering helpers."""

from __future__ import annotations

from headroom.proxy.output_steering import (
    apply_openai_responses_verbosity_steering,
    apply_verbosity_steering,
    replace_or_append_steering_block,
    steering_text,
)


def test_replace_or_append_steering_block_replaces_existing_block() -> None:
    old = steering_text(1)
    new = steering_text(3)
    assert old is not None
    assert new is not None
    updated, changed = replace_or_append_steering_block(f"System.\n\n{old}\n\nTail.", new)

    assert changed is True
    assert old not in updated
    assert updated == f"System.\n\n{new}\n\nTail."


def test_anthropic_steering_preserves_cached_prefix_block() -> None:
    cached = {
        "type": "text",
        "text": "Big system prompt.",
        "cache_control": {"type": "ephemeral"},
    }
    body = {"system": [cached.copy()]}

    assert apply_verbosity_steering(body, 2) is True
    assert body["system"][0] == cached
    assert body["system"][1] == {"type": "text", "text": steering_text(2)}


def test_openai_responses_steering_is_idempotent() -> None:
    body = {"instructions": "System."}

    assert apply_openai_responses_verbosity_steering(body, 2) is True
    snapshot = body.copy()
    assert apply_openai_responses_verbosity_steering(body, 2) is False
    assert body == snapshot
