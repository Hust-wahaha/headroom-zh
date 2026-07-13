"""Behavior-driven Playwright validation for context-tool (RTK) availability
messaging on the dashboard (issue #1831).

Local runs only import/collect this file (Windows dev sandboxes don't run the
real browser here); the "Dashboard Playwright" CI check executes it for real.
"""

from __future__ import annotations

import copy
import json
from urllib.parse import urlsplit

import pytest

from headroom.dashboard import get_dashboard_html

playwright = pytest.importorskip("playwright.sync_api")
Page = playwright.Page
expect = playwright.expect
sync_playwright = playwright.sync_playwright


def _base_stats() -> dict:
    return {
        "cost": {
            "savings_usd": 12.34,
            "compression_savings_usd": 12.34,
            "cache_savings_usd": 5.25,
            "cli_tokens_avoided": 0,
        },
        "requests": {
            "total": 128,
            "cached": 96,
            "rate_limited": 0,
            "failed": 0,
            "by_provider": {"anthropic": 128},
            "by_model": {"claude-opus-4-6": 128},
        },
        "tokens": {
            "input": 245_000,
            "output": 88_000,
            "saved": 143_000,
            "cli_tokens_avoided": 0,
            "total_before_compression": 388_000,
            "savings_percent": 36.86,
        },
        "overhead": {"average_ms": 14.2, "min_ms": 4.5, "max_ms": 42.7},
        "ttfb": {"average_ms": 1320.0, "min_ms": 420.0, "max_ms": 2900.0},
        "latency": {"average_ms": 1510.0, "min_ms": 520.0, "max_ms": 3300.0},
        "waste_signals": {"json_bloat": 95_000, "repetition": 48_000},
        "savings_history": [
            ["2026-04-01T00:00:00Z", 12_000],
            ["2026-04-05T00:00:00Z", 143_000],
        ],
        "persistent_savings": {
            "display_session": {},
            "lifetime": {"tokens_saved": 143_000, "compression_savings_usd": 12.34},
        },
        "pipeline_timing": {},
        "compression_cache": {"mode": "cache"},
        "prefix_cache": {"by_provider": {}, "totals": {}, "prefix_freeze": {}},
    }


def _sample_stats(*, available: bool, tokens_saved: int = 0) -> dict:
    """Build a /stats payload with context_tool/cli_filtering availability set.

    `_base_stats()` has no `savings` key at all, so writing
    `savings.by_layer.cli_filtering` requires a `.setdefault(...)` chain
    rather than direct key assignment (would otherwise raise `KeyError`).
    """
    stats = copy.deepcopy(_base_stats())
    stats["tokens"]["cli_tokens_avoided"] = tokens_saved
    stats["context_tool"] = {
        "configured": "rtk",
        "label": "RTK",
        "available": available,
        "stats": {"tool": "rtk", "label": "RTK", "installed": available},
    }
    cli_filtering = (
        stats.setdefault("savings", {}).setdefault("by_layer", {}).setdefault("cli_filtering", {})
    )
    cli_filtering.update(
        {
            "tool": "rtk",
            "label": "RTK",
            "available": available,
            "tokens": tokens_saved,
            "tokens_saved": tokens_saved,
            "session": {},
            "lifetime": {"tokens_saved": 0},
            "session_savings_pct": 0.0,
        }
    )
    return stats


def _sample_history(*, available: bool, lifetime_tokens_saved: int = 456_700) -> dict:
    return {
        "history": [
            {
                "timestamp": "2026-04-05T00:00:00Z",
                "total_tokens_saved": 143_000,
                "compression_savings_usd": 12.34,
            },
        ],
        "series": {"daily": [], "weekly": [], "monthly": []},
        "lifetime": {"tokens_saved": 143_000, "compression_savings_usd": 12.34},
        "cli_filtering": {
            "tool": "rtk",
            "label": "RTK",
            "available": available,
            "lifetime": {"tokens_saved": lifetime_tokens_saved},
            "session": {},
        },
    }


def _install_dashboard_routes(page: Page, stats: dict, history: dict) -> None:
    health = {"status": "healthy", "version": "0.3.0"}
    dashboard_html = get_dashboard_html()

    def handler(route) -> None:  # type: ignore[no-untyped-def]
        # Match on the URL path only: the dashboard fetches /stats?cached=1,
        # so suffix checks against the full URL miss it and the request
        # escapes the harness to the real network.
        path = urlsplit(route.request.url).path
        if path in ("/dashboard", "/"):
            route.fulfill(status=200, content_type="text/html", body=dashboard_html)
            return
        if "/stats-history" in path:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(history),
            )
            return
        if path.endswith("/stats"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(stats))
            return
        if path.endswith("/health"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(health))
            return
        route.continue_()

    page.route("**/*", handler)


def test_dashboard_session_view_shows_not_installed_message_when_unavailable() -> None:
    """Session view shows a distinct "not installed" message, not `0`, when
    `context_tool.available` is False (the #1831 bug this fix addresses).
    """
    stats = _sample_stats(available=False, tokens_saved=0)
    history = _sample_history(available=False)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1720, "height": 1400}, color_scheme="dark")
        _install_dashboard_routes(page, stats, history)
        page.goto("http://headroom.local/dashboard", wait_until="load")

        expect(page.get_by_text("RTK not installed", exact=True)).to_be_visible()
        expect(page.get_by_text("not installed", exact=True)).to_be_visible()
        expect(page.get_by_text("RTK 0 this session (0.0%)", exact=True)).to_have_count(0)

        browser.close()


def test_dashboard_session_view_shows_real_zero_row_when_installed_but_zero() -> None:
    """Boundary value 0.0: installed but genuinely zero savings still renders
    the real number, not the "not installed" message -- proves the new guard
    doesn't over-trigger on the exact case the #1831 reporter would hit again.
    """
    stats = _sample_stats(available=True, tokens_saved=0)
    history = _sample_history(available=True, lifetime_tokens_saved=0)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1720, "height": 1400}, color_scheme="dark")
        _install_dashboard_routes(page, stats, history)
        page.goto("http://headroom.local/dashboard", wait_until="load")

        expect(page.get_by_text("RTK 0 this session (0.0%)", exact=True)).to_be_visible()
        expect(page.get_by_text("RTK not installed", exact=True)).to_have_count(0)
        # The Token Usage panel's "not installed" row uses `x-show`, which
        # toggles CSS display and keeps the node in the DOM (unlike the
        # ternary-swapped "RTK not installed" text above, which is genuinely
        # absent). Assert hidden, not absent, matching the repo's existing
        # `x-show` convention in tests/test_dashboard_cache_lifetime_playwright.py.
        expect(page.get_by_text("not installed", exact=True)).to_be_hidden()

        browser.close()


def test_dashboard_historical_tab_hides_lifetime_card_when_unavailable() -> None:
    """The Historical tab's lifetime card stays hidden (same as the existing
    hard-failure hide-card behavior) when `cli_filtering.available` is False.
    """
    stats = _sample_stats(available=True, tokens_saved=5_000)
    history = _sample_history(available=False)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1720, "height": 1400}, color_scheme="dark")
        _install_dashboard_routes(page, stats, history)
        page.goto("http://headroom.local/dashboard", wait_until="load")

        page.get_by_role("button", name="Historical").click()
        expect(page.get_by_text("Historical Summary")).to_be_visible()
        expect(page.get_by_text("RTK Lifetime Saved")).to_have_count(0)

        browser.close()


def test_dashboard_historical_tab_shows_lifetime_card_when_available() -> None:
    """The Historical tab's lifetime card still renders the real number when
    `cli_filtering.available` is True (existing behavior, unchanged).
    """
    stats = _sample_stats(available=True, tokens_saved=5_000)
    history = _sample_history(available=True, lifetime_tokens_saved=456_700)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1720, "height": 1400}, color_scheme="dark")
        _install_dashboard_routes(page, stats, history)
        page.goto("http://headroom.local/dashboard", wait_until="load")

        page.get_by_role("button", name="Historical").click()
        expect(page.get_by_text("RTK Lifetime Saved")).to_be_visible()
        expect(page.get_by_text("456.7k")).to_be_visible()

        browser.close()
