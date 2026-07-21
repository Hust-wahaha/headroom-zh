"""RTK is opt-in (off by default): enabled only via --rtk / HEADROOM_RTK=1.

Regression for the RTK-default flip: the three RTK entry points must no-op
unless explicitly opted in, and every wrap subcommand must expose --rtk.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from click.testing import CliRunner

from headroom.cli import wrap


def _no_rtk_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("HEADROOM_RTK", None)
    return env


def test_rtk_opt_in_off_by_default() -> None:
    with patch.dict(os.environ, _no_rtk_env(), clear=True):
        assert wrap._rtk_opt_in() is False


def test_rtk_opt_in_on_via_env() -> None:
    for val in ("1", "true", "yes", "on"):
        with patch.dict(os.environ, {"HEADROOM_RTK": val}):
            assert wrap._rtk_opt_in() is True


def test_rtk_entry_points_noop_when_not_opted_in(tmp_path) -> None:
    agents = tmp_path / "AGENTS.md"
    with patch.dict(os.environ, _no_rtk_env(), clear=True):
        assert wrap._setup_rtk() is None
        assert wrap._ensure_rtk_binary() is None
        assert wrap._inject_rtk_instructions(agents) is False
        assert not agents.exists()  # nothing written when RTK is off


def test_rtk_flag_present_on_subcommands() -> None:
    runner = CliRunner()
    for tool in ("claude", "codex", "copilot", "aider", "continue"):
        out = runner.invoke(wrap.wrap, [tool, "--help"]).output
        assert "--rtk" in out, f"--rtk missing from `wrap {tool} --help`"
