"""Code-memory MCP is selectable via --code-memory (default tokensave).

Covers the resolver precedence (selector > deprecated flags > default), the
orchestrator dispatch for each selection, and that --code-memory is exposed on
the code-memory-capable subcommands (claude/codex/grok) but not others.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from click.testing import CliRunner

from headroom.cli import wrap


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("HEADROOM_CODE_MEMORY", None)
    return env


def test_default_is_serena() -> None:
    with patch.dict(os.environ, _clean_env(), clear=True):
        assert wrap._resolve_code_memory({}) == wrap._CODE_MEMORY_SERENA


def test_selector_env_wins() -> None:
    for val in (wrap._CODE_MEMORY_SERENA, wrap._CODE_MEMORY_NONE, wrap._CODE_MEMORY_TOKENSAVE):
        with patch.dict(os.environ, {"HEADROOM_CODE_MEMORY": val}):
            # selector beats any legacy flag
            assert wrap._resolve_code_memory({"serena": True, "no_tokensave": True}) == val


def test_deprecated_flags_map_into_selector() -> None:
    with patch.dict(os.environ, _clean_env(), clear=True):
        assert wrap._resolve_code_memory({"serena": True}) == wrap._CODE_MEMORY_SERENA
        assert wrap._resolve_code_memory({"no_tokensave": True}) == wrap._CODE_MEMORY_SERENA
        # --no-serena means "not serena" → the other real graph, tokensave
        assert wrap._resolve_code_memory({"no_serena": True}) == wrap._CODE_MEMORY_TOKENSAVE
        assert (
            wrap._resolve_code_memory({"no_tokensave": True, "no_serena": True})
            == wrap._CODE_MEMORY_NONE
        )


def test_serena_dashboard_disabled_flips_existing_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".serena" / "serena_config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "web_dashboard: true\nweb_dashboard_open_on_launch: true\ngui_log_window: false\n"
    )
    wrap._ensure_serena_dashboard_disabled()
    text = cfg.read_text()
    assert "web_dashboard_open_on_launch: false" in text
    assert "web_dashboard: true" in text  # other keys preserved


def test_serena_dashboard_disabled_creates_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    wrap._ensure_serena_dashboard_disabled()
    cfg = tmp_path / ".serena" / "serena_config.yml"
    assert cfg.exists()
    assert "web_dashboard_open_on_launch: false" in cfg.read_text()


def test_invalid_env_raises() -> None:
    import click

    with patch.dict(os.environ, {"HEADROOM_CODE_MEMORY": "bogus"}):
        try:
            wrap._resolve_code_memory({})
        except click.ClickException:
            pass
        else:  # pragma: no cover
            raise AssertionError("invalid HEADROOM_CODE_MEMORY should raise ClickException")


def _dispatch_calls(selection: str, extra: dict | None = None) -> list[str]:
    """Run the orchestrator with a given selection, recording which setup/disable
    helpers fire (all mocked)."""
    calls: list[str] = []
    env = _clean_env()
    env["HEADROOM_CODE_MEMORY"] = selection
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(
            wrap, "_setup_tokensave_mcp", lambda *a, **k: (calls.append("tokensave"), True)[1]
        ),
        patch.object(wrap, "_setup_serena_mcp", lambda *a, **k: calls.append("serena")),
        patch.object(
            wrap, "_disable_tokensave_mcp", lambda *a, **k: calls.append("disable_tokensave")
        ),
        patch.object(wrap, "_disable_serena_mcp", lambda *a, **k: calls.append("disable_serena")),
    ):
        wrap._setup_coding_compressor(object(), serena_context="claude-code", **(extra or {}))
    return calls


def test_orchestrator_dispatch() -> None:
    assert _dispatch_calls(wrap._CODE_MEMORY_TOKENSAVE) == ["tokensave", "disable_serena"]
    assert _dispatch_calls(wrap._CODE_MEMORY_SERENA) == ["disable_tokensave", "serena"]
    assert set(_dispatch_calls(wrap._CODE_MEMORY_NONE)) == {"disable_tokensave", "disable_serena"}


def test_code_memory_option_present_only_on_code_memory_agents() -> None:
    runner = CliRunner()
    for tool in ("claude", "codex", "grok"):
        out = runner.invoke(wrap.wrap, [tool, "--help"]).output
        assert "--code-memory" in out, f"--code-memory missing from `wrap {tool} --help`"
    # aider does not register a code-memory MCP → no flag
    out = runner.invoke(wrap.wrap, ["aider", "--help"]).output
    assert "--code-memory" not in out
