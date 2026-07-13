"""Output token shaping for proxied Anthropic requests.

Headroom's transforms compress what goes INTO the model. This module is the
first request-side lever on what comes OUT of it. The proxy never generates
output tokens, so every lever here works by reshaping the request:

1. Verbosity steering — a deterministic instruction block appended to the
   TAIL of the system prompt (after any ``cache_control`` breakpoint, so the
   provider prefix cache is preserved). Five levels, from "no ceremony" to
   full caveman.

2. Effort routing — agentic loops are mostly mechanical continuations (the
   last message is a clean tool_result: a file read, a passing test). Thinking
   bills as output tokens, and harnesses like Claude Code pin
   ``output_config.effort`` at ``xhigh`` for every turn. On turns classified
   as mechanical we lower an explicitly-present effort; on errors or new user
   asks we leave it alone. For legacy models still sending
   ``thinking.budget_tokens`` we clamp the budget to the API floor instead.

Safety rules (each prevents a concrete failure mode):
- Never INJECT ``output_config.effort`` where the client didn't send it —
  models without effort support 400 on it. Lowering an existing value is
  always valid.
- Never toggle ``thinking.type`` — disabling thinking while history carries
  thinking blocks 400s on some models, and the toggle busts the messages
  cache tier.
- Steering text is byte-stable per level and applied idempotently, so
  repeated requests keep an identical prefix.

Turn classification is purely structural (block types, roles, ``is_error``
flags) — no content regexes or keyword patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from headroom.proxy import runtime_env
from headroom.proxy.output_effort_policy import (
    EFFORT_RANK as _EFFORT_RANK,
)
from headroom.proxy.output_effort_policy import (
    LEGACY_THINKING_FLOOR,
    can_create_openai_text_verbosity,
    clamp_legacy_thinking_budget,
    lower_effort_value,
    lower_text_verbosity_value,
)
from headroom.proxy.output_steering import (
    apply_openai_responses_verbosity_steering,
    apply_verbosity_steering,
    replace_or_append_steering_block,
    steering_text,
)
from headroom.proxy.output_turn_policy import (
    TurnKind,
    classify_openai_responses_input,
    classify_turn,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LEGACY_THINKING_FLOOR",
    "OutputShaperSettings",
    "ShapeResult",
    "TurnKind",
    "apply_openai_responses_verbosity_steering",
    "apply_verbosity_steering",
    "classify_openai_responses_input",
    "classify_turn",
    "resolve_verbosity_level",
    "route_effort",
    "route_openai_reasoning_effort",
    "route_openai_text_verbosity",
    "shape_openai_responses_request",
    "shape_request",
    "steering_text",
]

_replace_or_append_steering_block = replace_or_append_steering_block


@dataclass(frozen=True)
class OutputShaperSettings:
    """Runtime settings, resolved once per request from the environment.

    Env-driven (like HEADROOM_INTERCEPT_ENABLED) so the proxy picks it up
    without config plumbing through the server. Off by default.
    """

    enabled: bool = False
    verbosity_level: int = 2
    effort_router_enabled: bool = True
    mechanical_effort: str = "low"

    @classmethod
    def from_env(cls) -> OutputShaperSettings:
        enabled = runtime_env.getenv("HEADROOM_OUTPUT_SHAPER", "").lower() in (
            "1",
            "true",
            "yes",
        )
        try:
            level = int(runtime_env.getenv("HEADROOM_VERBOSITY_LEVEL", "2"))
        except ValueError:
            level = 2
        level = max(0, min(4, level))
        router = runtime_env.getenv("HEADROOM_EFFORT_ROUTER", "1").lower() not in (
            "0",
            "false",
            "no",
        )
        mech = runtime_env.getenv("HEADROOM_MECHANICAL_EFFORT", "low")
        if mech not in _EFFORT_RANK:
            mech = "low"
        return cls(
            enabled=enabled,
            verbosity_level=level,
            effort_router_enabled=router,
            mechanical_effort=mech,
        )


def resolve_verbosity_level(settings: OutputShaperSettings) -> tuple[int, str]:
    """Resolve the live verbosity level and its source.

    Precedence:
      1. ``HEADROOM_VERBOSITY_LEVEL`` set explicitly → manual override.
      2. AIMD controller state (when ``HEADROOM_VERBOSITY_AUTOTUNE`` is on).
      3. Learned ``verbosity.json`` from ``learn --verbosity``.
      4. The settings default.

    Returns ``(level, source)``. Kept separate from :func:`shape_request` so the
    body-mutating core stays a pure function of an explicit level.
    """
    if runtime_env.getenv("HEADROOM_VERBOSITY_LEVEL"):
        return settings.verbosity_level, "env"

    try:
        from ..paths import workspace_dir

        ws = workspace_dir()
    except Exception:
        return settings.verbosity_level, "default"

    autotune = runtime_env.getenv("HEADROOM_VERBOSITY_AUTOTUNE", "").lower() in ("1", "true", "yes")
    if autotune:
        ctrl_path = ws / "verbosity_controller.json"
        if ctrl_path.exists():
            try:
                import json as _json

                level = int(
                    _json.loads(ctrl_path.read_text()).get("level", settings.verbosity_level)
                )
                return max(0, min(4, level)), "controller"
            except (OSError, ValueError):
                pass

    prof_path = ws / "verbosity.json"
    if prof_path.exists():
        try:
            import json as _json

            level = int(_json.loads(prof_path.read_text()).get("verbosity_level", -1))
            if 0 <= level <= 4:
                return level, "learned"
        except (OSError, ValueError):
            pass

    return settings.verbosity_level, "default"


@dataclass
class ShapeResult:
    """What the shaper did to a request body."""

    changed: bool = False
    labels: list[str] | None = None

    def __post_init__(self) -> None:
        if self.labels is None:
            self.labels = []


def route_effort(
    body: dict[str, Any],
    kind: TurnKind,
    settings: OutputShaperSettings,
) -> list[str]:
    """Lower thinking/effort spend on mechanical continuations.

    Returns labels for each mutation made (empty list = untouched).
    """
    if kind is not TurnKind.MECHANICAL_CONTINUATION:
        return []

    labels: list[str] = []

    # Modern lever: output_config.effort. Only lower a value the client
    # explicitly sent — presence proves the target model accepts the param.
    output_config = body.get("output_config")
    if isinstance(output_config, dict):
        effort = output_config.get("effort")
        lowered = lower_effort_value(effort, settings.mechanical_effort)
        if lowered is not None:
            output_config["effort"] = lowered
            labels.append(f"output_shaper:effort:{effort}->{lowered}")

    # Legacy lever: clamp thinking.budget_tokens on models still using the
    # enabled/budget_tokens form. The type field itself is never touched.
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        budget = thinking.get("budget_tokens")
        clamped = clamp_legacy_thinking_budget(
            thinking_type=thinking.get("type"),
            budget_tokens=budget,
            floor=LEGACY_THINKING_FLOOR,
        )
        if clamped is not None:
            thinking["budget_tokens"] = clamped
            labels.append(f"output_shaper:thinking_budget:{budget}->{clamped}")

    return labels


def route_openai_reasoning_effort(
    body: dict[str, Any],
    kind: TurnKind,
    settings: OutputShaperSettings,
) -> list[str]:
    """Lower explicitly-present OpenAI reasoning effort on mechanical turns."""
    if kind is not TurnKind.MECHANICAL_CONTINUATION:
        return []

    reasoning = body.get("reasoning")
    if not isinstance(reasoning, dict):
        return []
    effort = reasoning.get("effort")
    target = settings.mechanical_effort
    lowered = lower_effort_value(effort, target)
    if lowered is not None:
        reasoning["effort"] = lowered
        return [f"output_shaper:reasoning_effort:{effort}->{lowered}"]
    return []


def route_openai_text_verbosity(body: dict[str, Any]) -> list[str]:
    """Set or lower OpenAI ``text.verbosity`` conservatively."""
    text_config = body.get("text")
    can_create = can_create_openai_text_verbosity(body.get("model"))
    if text_config is None:
        if not can_create:
            return []
        body["text"] = {"verbosity": "low"}
        return ["output_shaper:text_verbosity:unset->low"]
    if not isinstance(text_config, dict):
        return []

    verbosity = text_config.get("verbosity")
    if verbosity is None:
        if not can_create:
            return []
        text_config["verbosity"] = "low"
        return ["output_shaper:text_verbosity:unset->low"]
    lowered = lower_text_verbosity_value(verbosity)
    if lowered is not None:
        text_config["verbosity"] = lowered
        return [f"output_shaper:text_verbosity:{verbosity}->{lowered}"]
    return []


def shape_openai_responses_request(
    body: dict[str, Any],
    settings: OutputShaperSettings | None = None,
    level_override: int | None = None,
) -> ShapeResult:
    """Apply OpenAI Responses output-shaping levers in place."""
    if settings is None:
        settings = OutputShaperSettings.from_env()
    result = ShapeResult()
    if not settings.enabled:
        return result

    assert result.labels is not None  # __post_init__ guarantees

    level = settings.verbosity_level if level_override is None else level_override
    if level > 0 and apply_openai_responses_verbosity_steering(body, level):
        result.changed = True
        result.labels.append(f"output_shaper:verbosity:L{level}")

    kind = classify_openai_responses_input(body.get("input"))
    if settings.effort_router_enabled:
        labels = route_openai_reasoning_effort(body, kind, settings)
        if labels:
            result.changed = True
            result.labels.extend(labels)
            logger.debug("OpenAIOutputShaper: turn=%s mutations=%s", kind.value, labels)

    labels = route_openai_text_verbosity(body)
    if labels:
        result.changed = True
        result.labels.extend(labels)

    return result


def shape_request(
    body: dict[str, Any],
    settings: OutputShaperSettings | None = None,
    level_override: int | None = None,
) -> ShapeResult:
    """Apply all output-shaping levers to an Anthropic request body in place.

    ``level_override`` supersedes ``settings.verbosity_level`` when given — the
    handler passes the level resolved by :func:`resolve_verbosity_level` (learned
    profile / controller / env) so the body-mutating core stays level-agnostic.
    """
    if settings is None:
        settings = OutputShaperSettings.from_env()
    result = ShapeResult()
    if not settings.enabled:
        return result

    assert result.labels is not None  # __post_init__ guarantees this

    level = settings.verbosity_level if level_override is None else level_override
    if level > 0 and apply_verbosity_steering(body, level):
        result.changed = True
        result.labels.append(f"output_shaper:verbosity:L{level}")

    if settings.effort_router_enabled:
        kind = classify_turn(body.get("messages", []))
        labels = route_effort(body, kind, settings)
        if labels:
            result.changed = True
            result.labels.extend(labels)
        logger.debug("OutputShaper: turn=%s mutations=%s", kind.value, labels)

    return result
