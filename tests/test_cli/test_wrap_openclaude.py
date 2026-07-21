"""Tests for `headroom wrap openclaude` command (issue #1411)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import pytest
from click.testing import CliRunner

import headroom.cli.wrap as wrap_cli
from headroom.cli.main import main

OPENCLAUDE_BINARY = "openclaude"
OPENCLAUDE_INSTRUCTIONS_FILE = "CONVENTIONS.md"
OPENCLAUDE_MODEL_ARG = "gpt-4o"
RTK_BINARY = "rtk"
UTF8_ENCODING = "utf-8"
WINDOWS_DEFAULT_TEXT_ENCODING = "cp1252"


def _expected_project_prefix() -> str:
    return f"/p/{quote(Path.cwd().name, safe='')}"


@pytest.fixture(autouse=True)
def _enable_rtk(monkeypatch: pytest.MonkeyPatch) -> None:
    # RTK is opt-in (off by default); these tests exercise the RTK-on injection path.
    monkeypatch.setenv("HEADROOM_RTK", "1")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_wrap_openclaude_routes_proxy_envs(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value=OPENCLAUDE_BINARY):
        with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
            result = runner.invoke(
                main,
                ["wrap", "openclaude", "--no-rtk", "--", "--model", OPENCLAUDE_MODEL_ARG],
            )

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    prefix = _expected_project_prefix()
    assert env["OPENAI_API_BASE"] == f"http://127.0.0.1:8787{prefix}/v1"
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:8787{prefix}"
    assert captured["tool_label"] == "OPENCLAUDE"
    assert captured["agent_type"] == "openclaude"
    assert captured["args"] == ("--model", OPENCLAUDE_MODEL_ARG)


def test_wrap_openclaude_default_rtk_injects_instructions(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    original_write_text = Path.write_text

    def write_text_with_windows_default(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if encoding is None:
            encoded = data.encode(WINDOWS_DEFAULT_TEXT_ENCODING, errors=errors or "strict")
            self.write_bytes(encoded)
            return len(data)
        return original_write_text(
            self,
            data,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    def fake_launch_tool(**_kwargs):  # noqa: ANN003
        return None

    with patch("headroom.cli.wrap.shutil.which", return_value=OPENCLAUDE_BINARY):
        with patch("headroom.cli.wrap._ensure_rtk_binary", return_value=tmp_path / RTK_BINARY):
            with patch.object(
                Path,
                "write_text",
                autospec=True,
                side_effect=write_text_with_windows_default,
            ):
                with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                    result = runner.invoke(main, ["wrap", "openclaude"])

    instructions = tmp_path / OPENCLAUDE_INSTRUCTIONS_FILE
    assert result.exit_code == 0, result.output
    assert instructions.exists()
    assert wrap_cli._RTK_MARKER in instructions.read_text(encoding=UTF8_ENCODING)


def test_wrap_openclaude_missing_binary_errors(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("headroom.cli.wrap.shutil.which", return_value=None):
        result = runner.invoke(main, ["wrap", "openclaude", "--no-rtk"])
    assert result.exit_code == 1
    assert "openclaude" in result.output.lower()
