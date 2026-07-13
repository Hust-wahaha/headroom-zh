"""CCR marker freshness and retrieval-tool injection policy."""

from __future__ import annotations

from typing import Any, Literal


def has_new_ccr_markers(
    *,
    current_detected_hashes: list[str],
    previous_forwarded_messages: list[dict[str, Any]] | None,
    provider: Literal["anthropic", "openai", "google"],
) -> bool:
    """Return whether current CCR hashes contain hashes not previously forwarded."""

    current = set(current_detected_hashes)
    if not current:
        return False
    if not previous_forwarded_messages:
        return True

    from headroom.ccr.tool_injection import CCRToolInjector

    previous = CCRToolInjector(
        provider=provider,
        inject_tool=False,
        inject_system_instructions=False,
    )
    previous.scan_for_markers(previous_forwarded_messages)
    return bool(current - set(previous.detected_hashes))


def should_inject_ccr_tool(
    *,
    configured_inject_tool: bool,
    frozen_message_count: int,
    has_compressed_content: bool,
) -> tuple[bool, bool]:
    """Decide whether the CCR retrieval tool must be injected this turn."""

    inject_tool = configured_inject_tool
    if inject_tool and frozen_message_count > 0:
        inject_tool = False
    is_marker_override = not inject_tool and has_compressed_content
    return (inject_tool or is_marker_override), is_marker_override
