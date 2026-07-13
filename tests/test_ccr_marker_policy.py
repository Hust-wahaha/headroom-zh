from __future__ import annotations

from headroom.ccr.tool_injection import CCRToolInjector
from headroom.proxy.ccr_marker_policy import has_new_ccr_markers, should_inject_ccr_tool


def _hashes(*contents: str) -> list[str]:
    injector = CCRToolInjector(
        provider="anthropic",
        inject_tool=False,
        inject_system_instructions=False,
    )
    injector.scan_for_markers([{"role": "user", "content": content} for content in contents])
    return injector.detected_hashes


def test_has_new_ccr_markers_filters_replayed_forwarded_markers() -> None:
    marker = "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]"

    assert (
        has_new_ccr_markers(
            current_detected_hashes=_hashes(marker),
            previous_forwarded_messages=[{"role": "user", "content": marker}],
            provider="anthropic",
        )
        is False
    )


def test_has_new_ccr_markers_detects_hash_not_seen_in_previous_forward() -> None:
    old = "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]"
    new = "[50 items compressed to 5. Retrieve more: hash=deadbeefdeadbeefdeadbeef]"

    assert (
        has_new_ccr_markers(
            current_detected_hashes=_hashes(old, new),
            previous_forwarded_messages=[{"role": "user", "content": old}],
            provider="anthropic",
        )
        is True
    )


def test_has_new_ccr_markers_treats_missing_previous_forward_as_new() -> None:
    marker = "[100 items compressed to 10. Retrieve more: hash=abc123def456abc123def456]"

    assert (
        has_new_ccr_markers(
            current_detected_hashes=_hashes(marker),
            previous_forwarded_messages=None,
            provider="anthropic",
        )
        is True
    )


def test_has_new_ccr_markers_returns_false_without_current_hashes() -> None:
    assert (
        has_new_ccr_markers(
            current_detected_hashes=[],
            previous_forwarded_messages=None,
            provider="anthropic",
        )
        is False
    )


def test_should_inject_ccr_tool_overrides_frozen_prefix_deferral_for_markers() -> None:
    assert should_inject_ccr_tool(
        configured_inject_tool=True,
        frozen_message_count=3,
        has_compressed_content=True,
    ) == (True, True)


def test_should_inject_ccr_tool_defers_frozen_prefix_without_markers() -> None:
    assert should_inject_ccr_tool(
        configured_inject_tool=True,
        frozen_message_count=3,
        has_compressed_content=False,
    ) == (False, False)


def test_should_inject_ccr_tool_injects_configured_tool_without_frozen_prefix() -> None:
    assert should_inject_ccr_tool(
        configured_inject_tool=True,
        frozen_message_count=0,
        has_compressed_content=False,
    ) == (True, False)
