"""Byte-stable output verbosity steering helpers."""

from __future__ import annotations

from typing import Any

from headroom.proxy.output_verbosity_policy import (
    STEERING_SENTINEL as _STEERING_SENTINEL,
)
from headroom.proxy.output_verbosity_policy import (
    replace_or_append_steering_block,
    steering_text,
)


def apply_verbosity_steering(body: dict[str, Any], level: int) -> bool:
    """Append the steering block to the tail of the Anthropic system prompt.

    Appending after the last system block keeps any ``cache_control``
    breakpoint on an earlier block intact: the cached prefix is unchanged and
    only the small, byte-stable steering block is reprocessed.
    """
    text = steering_text(level)
    if text is None:
        return False

    system = body.get("system")
    if system is None:
        body["system"] = [{"type": "text", "text": text}]
        return True
    if isinstance(system, str):
        body["system"] = [
            {"type": "text", "text": system},
            {"type": "text", "text": text},
        ]
        return True
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("text", "").startswith(_STEERING_SENTINEL):
                if block["text"] == text:
                    return False
                block["text"] = text
                return True
        system.append({"type": "text", "text": text})
        return True
    return False


def apply_openai_responses_verbosity_steering(
    body: dict[str, Any],
    level: int,
) -> bool:
    """Append or replace steering in OpenAI Responses ``instructions``."""
    text = steering_text(level)
    if text is None:
        return False

    instructions = body.get("instructions")
    if instructions is None:
        body["instructions"] = text
        return True
    if not isinstance(instructions, str):
        return False

    updated, changed = replace_or_append_steering_block(instructions, text)
    if changed:
        body["instructions"] = updated
    return changed
