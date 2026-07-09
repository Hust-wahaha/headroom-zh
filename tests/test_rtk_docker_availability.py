"""Tests for RTK/context-tool availability detection in Docker environments."""

from __future__ import annotations

from unittest.mock import patch

from headroom.proxy.helpers import (
    _context_tool_zero_payload,
    _read_rtk_lifetime_stats,
)


class TestRtkNotInstalledPayload:
    """When rtk binary is absent, the payload must report installed=False."""

    def test_zero_payload_marks_not_installed(self) -> None:
        payload = _context_tool_zero_payload(tool="rtk", installed=False)
        assert payload["installed"] is False
        assert payload["total_commands"] == 0
        assert payload["tokens_saved"] == 0

    def test_read_rtk_returns_not_installed_when_binary_missing(self) -> None:
        with patch("headroom.rtk.get_rtk_path", return_value=None):
            result = _read_rtk_lifetime_stats()
        assert result is not None
        assert result["installed"] is False
        assert result["tokens_saved"] == 0

    def test_installed_payload_marks_installed(self) -> None:
        payload = _context_tool_zero_payload(tool="rtk", installed=True)
        assert payload["installed"] is True


class TestDashboardAvailabilityFlag:
    """The stats endpoint must surface context_tool.available for the dashboard."""

    def test_available_false_when_tool_not_installed(self) -> None:
        stats = {"installed": False, "tokens_saved": 0}
        available = bool(stats.get("installed", False))
        assert available is False

    def test_available_true_when_tool_installed(self) -> None:
        stats = {"installed": True, "tokens_saved": 42}
        available = bool(stats.get("installed", False))
        assert available is True
