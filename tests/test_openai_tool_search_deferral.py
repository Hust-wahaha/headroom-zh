"""Server-side Tool Search deferral for OpenAI Responses (gpt-5.4+).

The OpenAI-side analogue of the Anthropic path (issue #746): mark non-core
function / MCP tools ``defer_loading: true`` and inject ``{"type": "tool_search"}``
so OpenAI keeps their heavy parameter schemas out of the model's context until
searched. Gated to gpt-5.4+ (older models 400 on the fields).
"""

from __future__ import annotations

import copy

import pytest

from headroom.proxy.helpers import (
    _model_supports_openai_tool_search,
    inject_tool_search_deferral_openai,
)


def _fn(name: str) -> dict:
    return {"type": "function", "name": name, "parameters": {"type": "object", "properties": {}}}


_CORE = ["bash", "read", "write", "edit", "grep", "glob"]
_NONCORE = [f"slack_{i}" for i in range(10)]  # 6 core + 10 non-core = 16 tools (>= min 12)


def _tools() -> list[dict]:
    return [_fn(n) for n in _CORE + _NONCORE]


# --- model gating ------------------------------------------------------------


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.5", "gpt-5.4-2026-02-01", "gpt-6", "gpt-6.2"])
def test_model_supported(model):
    assert _model_supports_openai_tool_search(model) is True


@pytest.mark.parametrize(
    "model", ["gpt-4o", "gpt-4.1", "gpt-5", "gpt-5.3", "o3", "", None, "claude-opus-4-8"]
)
def test_model_unsupported(model):
    assert _model_supports_openai_tool_search(model) is False


def test_env_override_wins_then_falls_back(monkeypatch):
    monkeypatch.setenv("HEADROOM_OPENAI_TOOL_SEARCH_MODELS", r"^my-model")
    assert _model_supports_openai_tool_search("my-model-v1") is True
    assert _model_supports_openai_tool_search("gpt-5.4") is False  # override replaces the gate
    # a malformed regex must not crash — fall back to the version gate.
    monkeypatch.setenv("HEADROOM_OPENAI_TOOL_SEARCH_MODELS", "[unclosed")
    assert _model_supports_openai_tool_search("gpt-5.4") is True


# --- deferral behavior -------------------------------------------------------


def test_defers_non_core_and_injects_search_tool():
    tools = _tools()
    out = inject_tool_search_deferral_openai(tools, "gpt-5.5")
    assert out is not tools  # new list
    assert out[0] == {"type": "tool_search"}  # search tool injected, first, once
    assert sum(1 for t in out if t.get("type") == "tool_search") == 1
    by_name = {t["name"]: t for t in out if t.get("type") == "function"}
    for c in _CORE:
        assert not by_name[c].get("defer_loading")  # core stays resident
    for n in _NONCORE:
        assert by_name[n].get("defer_loading") is True  # non-core deferred


def test_defers_mcp_server():
    tools = [_fn(n) for n in _CORE] + [{"type": "mcp", "server_label": "sentry"}]
    tools += [_fn(f"x{i}") for i in range(8)]
    out = inject_tool_search_deferral_openai(tools, "gpt-5.5")
    mcp = next(t for t in out if t.get("type") == "mcp")
    assert mcp.get("defer_loading") is True


def test_hosted_tools_stay_resident():
    tools = [_fn(n) for n in _CORE] + [{"type": "web_search"}, {"type": "code_interpreter"}]
    tools += [_fn(f"x{i}") for i in range(8)]
    out = inject_tool_search_deferral_openai(tools, "gpt-5.5")
    ws = next(t for t in out if t.get("type") == "web_search")
    ci = next(t for t in out if t.get("type") == "code_interpreter")
    assert "defer_loading" not in ws  # hosted tools can't be deferred
    assert "defer_loading" not in ci


def test_does_not_mutate_input():
    tools = _tools()
    snapshot = copy.deepcopy(tools)
    inject_tool_search_deferral_openai(tools, "gpt-5.5")
    assert tools == snapshot  # deferred tools are copies; the input is untouched


# --- no-op guards ------------------------------------------------------------


def test_noop_for_unsupported_model():
    tools = _tools()
    assert inject_tool_search_deferral_openai(tools, "gpt-4o") is tools


def test_noop_below_min_tools():
    tools = [_fn(f"x{i}") for i in range(5)]  # < 12
    assert inject_tool_search_deferral_openai(tools, "gpt-5.5") is tools


def test_noop_when_tool_search_already_present():
    tools = [{"type": "tool_search"}] + [_fn(f"x{i}") for i in range(15)]
    assert inject_tool_search_deferral_openai(tools, "gpt-5.5") is tools


def test_noop_when_nothing_deferrable():
    tools = [_fn(n) for n in _CORE * 3]  # 18 core tools, none deferrable
    assert inject_tool_search_deferral_openai(tools, "gpt-5.5") is tools


def test_noop_for_non_list():
    assert inject_tool_search_deferral_openai(None, "gpt-5.5") is None
