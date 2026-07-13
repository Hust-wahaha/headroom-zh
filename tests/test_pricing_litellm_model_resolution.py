from __future__ import annotations

from headroom.pricing.litellm_model_resolution import (
    MODEL_ALIASES,
    LiteLLMModelPrefixRule,
    pricing_lookup_candidates,
    resolution_candidates,
    resolve_litellm_model_name,
)


def test_prefix_rule_matches_case_insensitively() -> None:
    rule = LiteLLMModelPrefixRule("minimax-", "minimax/")

    assert rule.candidate_for("MiniMax-M3") == "minimax/MiniMax-M3"
    assert rule.candidate_for("gpt-4o") is None


def test_resolution_candidates_try_bare_then_matching_prefix_then_alias() -> None:
    assert resolution_candidates("gpt-4o") == ("gpt-4o", "openai/gpt-4o")
    assert resolution_candidates("MiniMax-M3") == ("MiniMax-M3", "minimax/MiniMax-M3")

    retired = "claude-3-5-sonnet-20241022"
    assert resolution_candidates(retired) == (
        retired,
        f"anthropic/{retired}",
        MODEL_ALIASES[retired],
    )


def test_pricing_lookup_candidates_include_provider_prefixes_and_aliases() -> None:
    candidates = pricing_lookup_candidates("claude-3-5-sonnet-20241022")

    assert candidates[0] == "claude-3-5-sonnet-20241022"
    assert "anthropic/claude-3-5-sonnet-20241022" in candidates
    assert "minimax/claude-3-5-sonnet-20241022" in candidates
    assert candidates[-1] == MODEL_ALIASES["claude-3-5-sonnet-20241022"]


def test_resolve_litellm_model_name_returns_first_known_candidate() -> None:
    known = {"openai/gpt-4o"}

    assert resolve_litellm_model_name("gpt-4o", known.__contains__) == "openai/gpt-4o"


def test_resolve_litellm_model_name_returns_original_when_unknown() -> None:
    assert resolve_litellm_model_name("mystery-model", lambda _: False) == "mystery-model"
