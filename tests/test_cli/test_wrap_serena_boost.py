"""Serena "boost" wrap-time helpers: prefer-Serena instruction injection,
repo-language scoping of ``.serena/project.yml``, and symbol-cache pre-indexing.

All Serena subprocess calls are mocked — these tests never invoke real ``uvx``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from headroom.cli import wrap as wrap_cli

# ---------------------------------------------------------------------------
# _inject_serena_instructions
# ---------------------------------------------------------------------------


def _opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the opt-in gate so injection actually writes.

    Instruction injection rewrites the user's CLAUDE.md/AGENTS.md, so it is
    off by default (mirrors RTK). Tests that exercise the write path must opt
    in via ``HEADROOM_SERENA_INSTRUCTIONS``.
    """
    monkeypatch.setenv("HEADROOM_SERENA_INSTRUCTIONS", "1")


def test_inject_creates_file_and_mentions_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _opt_in(monkeypatch)
    target = tmp_path / "AGENTS.md"
    assert wrap_cli._inject_serena_instructions(target) is True

    content = target.read_text()
    assert wrap_cli._SERENA_MARKER in content
    # The whole point is steering the agent toward Serena's symbol tools.
    for tool in ("get_symbols_overview", "find_symbol", "find_referencing_symbols"):
        assert tool in content, f"{tool} missing from injected guidance"


def test_inject_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _opt_in(monkeypatch)
    target = tmp_path / "AGENTS.md"
    wrap_cli._inject_serena_instructions(target)
    wrap_cli._inject_serena_instructions(target)  # second call is a no-op

    content = target.read_text()
    assert content.count(wrap_cli._SERENA_MARKER) == 1


def test_inject_appends_to_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _opt_in(monkeypatch)
    target = tmp_path / "CLAUDE.md"
    target.write_text("# Project notes\n\nkeep me\n")
    wrap_cli._inject_serena_instructions(target)

    content = target.read_text()
    assert "keep me" in content  # existing content preserved
    assert wrap_cli._SERENA_MARKER in content


def test_inject_off_by_default_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without opting in, injection is a no-op: returns False and never touches
    # the user's hint file (the default, so the two OpenCode AGENTS.md tests pass).
    monkeypatch.delenv("HEADROOM_SERENA_INSTRUCTIONS", raising=False)

    missing = tmp_path / "AGENTS.md"
    assert wrap_cli._inject_serena_instructions(missing) is False
    assert not missing.exists()  # nothing created

    existing = tmp_path / "CLAUDE.md"
    existing.write_text("# Project notes\n\nkeep me\n")
    assert wrap_cli._inject_serena_instructions(existing) is False
    assert existing.read_text() == "# Project notes\n\nkeep me\n"  # untouched
    assert wrap_cli._SERENA_MARKER not in existing.read_text()


def test_instruction_file_target_per_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    class _Reg:
        def __init__(self, name: str) -> None:
            self.name = name

    assert wrap_cli._serena_instruction_file(_Reg("claude")).name == "CLAUDE.md"
    assert wrap_cli._serena_instruction_file(_Reg("codex")).name == "AGENTS.md"
    assert wrap_cli._serena_instruction_file(_Reg("grok")).name == "AGENTS.md"


# ---------------------------------------------------------------------------
# _detect_repo_languages
# ---------------------------------------------------------------------------


def test_detect_maps_extensions_to_serena_languages(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print(1)\n")
    (tmp_path / "web.ts").write_text("export const x = 1\n")
    (tmp_path / "main.go").write_text("package main\n")

    assert set(wrap_cli._detect_repo_languages(tmp_path)) == {"python", "typescript", "go"}


def test_detect_ignores_deps_and_venv(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print(1)\n")
    # Languages that appear ONLY inside ignored dirs must not be reported.
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.rs").write_text("fn main() {}\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.rb").write_text("puts 1\n")

    detected = set(wrap_cli._detect_repo_languages(tmp_path))
    assert detected == {"python"}
    assert "rust" not in detected
    assert "ruby" not in detected


def test_detect_orders_by_file_count(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"m{i}.py").write_text("x = 1\n")
    (tmp_path / "main.go").write_text("package main\n")

    ordered = wrap_cli._detect_repo_languages(tmp_path)
    assert ordered[0] == "python"  # most files → default/fallback language first


def test_detect_empty_when_no_source(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# hi\n")  # markup, not mapped
    assert wrap_cli._detect_repo_languages(tmp_path) == []


# ---------------------------------------------------------------------------
# _scope_serena_languages — pins languages into .serena/project.yml
# ---------------------------------------------------------------------------


def test_scope_creates_project_yml_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("print(1)\n")

    wrap_cli._scope_serena_languages()

    cfg = tmp_path / ".serena" / "project.yml"
    assert cfg.exists()
    text = cfg.read_text()
    assert 'languages: ["python"]' in text
    assert "project_name:" in text  # required field written too


def test_scope_updates_existing_inline_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("print(1)\n")
    (tmp_path / "main.go").write_text("package main\n")
    cfg = tmp_path / ".serena" / "project.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('project_name: "demo"\nlanguages: ["python"]\nencoding: "utf-8"\n')

    wrap_cli._scope_serena_languages()

    text = cfg.read_text()
    # go + python (one file each → alphabetical tie-break), inline flow list.
    assert 'languages: ["go", "python"]' in text
    assert 'encoding: "utf-8"' in text  # other keys preserved


def test_scope_leaves_block_style_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("print(1)\n")
    cfg = tmp_path / ".serena" / "project.yml"
    cfg.parent.mkdir(parents=True)
    original = 'project_name: "demo"\nlanguages:\n- typescript\n'
    cfg.write_text(original)

    wrap_cli._scope_serena_languages()

    # Block-style list is not something our single-line edit can safely touch,
    # so it is left exactly as-is rather than corrupted.
    assert cfg.read_text() == original


def test_scope_noop_when_no_languages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# hi\n")

    wrap_cli._scope_serena_languages()

    assert not (tmp_path / ".serena" / "project.yml").exists()


# ---------------------------------------------------------------------------
# _index_serena_project — best-effort, timeout-guarded pre-index
# ---------------------------------------------------------------------------


def _stub_uvx(monkeypatch: pytest.MonkeyPatch, present: bool = True) -> None:
    monkeypatch.setattr(
        wrap_cli.shutil,
        "which",
        lambda name, *a, **k: "/usr/bin/uvx" if (present and name == "uvx") else None,
    )


def test_preindex_runs_serena_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _stub_uvx(monkeypatch)
    mock_run = Mock(
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    monkeypatch.setattr(wrap_cli, "run", mock_run)

    wrap_cli._index_serena_project()

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "uvx"
    assert cmd[-3:] == ["serena", "project", "index"]
    assert "git+https://github.com/oraios/serena" in cmd
    assert kwargs["cwd"] == str(tmp_path)  # invoked in the project cwd
    assert "timeout" in kwargs  # timeout-guarded


def test_preindex_skips_without_uvx(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_uvx(monkeypatch, present=False)
    mock_run = Mock(side_effect=AssertionError("run must not be called without uvx"))
    monkeypatch.setattr(wrap_cli, "run", mock_run)

    wrap_cli._index_serena_project()  # no exception

    mock_run.assert_not_called()


def test_preindex_timeout_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_uvx(monkeypatch)
    monkeypatch.setattr(
        wrap_cli,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired(cmd="serena", timeout=1)),
    )
    # Must not propagate.
    wrap_cli._index_serena_project(verbose=True)


def test_preindex_generic_error_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_uvx(monkeypatch)
    monkeypatch.setattr(wrap_cli, "run", Mock(side_effect=RuntimeError("boom")))
    # Must not propagate.
    wrap_cli._index_serena_project(verbose=True)
