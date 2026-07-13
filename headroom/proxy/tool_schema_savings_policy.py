"""Tool-schema savings attribution policy for proxy stats."""

from __future__ import annotations

TOOL_SCHEMA_SAVINGS_TAGS: tuple[str, ...] = (
    "tool_search_deferred_tokens",
    "turn_hook_tools_saved_tokens",
)


def tool_schema_saved_from_tags(tags: object) -> int:
    """Return tool-definition tokens Headroom kept out of context for one request.

    The summed tags are set only on paths where Headroom performed the deferral,
    so clients that already had tool search enabled contribute zero here.
    """
    if not isinstance(tags, dict):
        return 0

    total = 0
    for key in TOOL_SCHEMA_SAVINGS_TAGS:
        try:
            total += int(tags.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
    return total
