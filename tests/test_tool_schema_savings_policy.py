from __future__ import annotations

from headroom.proxy.tool_schema_savings_policy import (
    TOOL_SCHEMA_SAVINGS_TAGS,
    tool_schema_saved_from_tags,
)


def test_tool_schema_saved_from_tags_sums_headroom_deferral_tags() -> None:
    assert (
        tool_schema_saved_from_tags(
            {
                "tool_search_deferred_tokens": "120",
                "turn_hook_tools_saved_tokens": 30,
                "unrelated": 999,
            }
        )
        == 150
    )


def test_tool_schema_saved_from_tags_ignores_invalid_values() -> None:
    assert (
        tool_schema_saved_from_tags(
            {
                "tool_search_deferred_tokens": "not-an-int",
                "turn_hook_tools_saved_tokens": None,
            }
        )
        == 0
    )


def test_tool_schema_saved_from_tags_rejects_non_mapping_tags() -> None:
    assert tool_schema_saved_from_tags(None) == 0
    assert tool_schema_saved_from_tags([("tool_search_deferred_tokens", 10)]) == 0


def test_tool_schema_savings_tags_are_stable() -> None:
    assert TOOL_SCHEMA_SAVINGS_TAGS == (
        "tool_search_deferred_tokens",
        "turn_hook_tools_saved_tokens",
    )
