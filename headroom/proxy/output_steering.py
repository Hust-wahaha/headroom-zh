"""Byte-stable output verbosity steering helpers."""

from __future__ import annotations

from typing import Any

# Sentinel prefix marks the steering block so application is idempotent and
# the block is recognizable in logs/diffs.
_STEERING_SENTINEL = "<headroom_output_shaping>"
_STEERING_SUFFIX = "</headroom_output_shaping>"

# Levels are cumulative: each includes everything above it. Text must stay
# byte-stable across releases for prefix-cache friendliness; treat edits to
# these strings as cache-busting changes.
_VERBOSITY_LEVELS = {
    1: (
        "Skip preamble and postamble. Do not announce what you are about to "
        "do or recap what you just did; start with the substance."
    ),
    2: (
        "Skip preamble and postamble; start with the substance. Never restate "
        "code, file contents, diffs, or tool output that already appear in "
        "this conversation — reference them by path and line instead. After a "
        "tool call succeeds, continue without narrating the result."
    ),
    3: (
        "Skip preamble and postamble. Never restate code, file contents, "
        "diffs, or tool output already in this conversation — reference by "
        "path and line. Give conclusions only; omit rationale unless the user "
        "asks why. Prefer the smallest edit over rewriting whole files. Keep "
        "prose to the minimum needed to be unambiguous."
    ),
    4: (
        "Minimum tokens. Fragments fine. No preamble, no postamble, no "
        "restating context, no rationale. Answer, smallest-possible edits, "
        "nothing else."
    ),
}


def steering_text(level: int) -> str | None:
    """The full steering block for a verbosity level, or None for level 0."""
    text = _VERBOSITY_LEVELS.get(level)
    if text is None:
        return None
    return f"{_STEERING_SENTINEL}\n{text}\n{_STEERING_SUFFIX}"


def replace_or_append_steering_block(existing: str, block: str) -> tuple[str, bool]:
    """Replace an existing steering block in text, or append one at the tail."""
    start = existing.find(_STEERING_SENTINEL)
    if start >= 0:
        end = existing.find(_STEERING_SUFFIX, start)
        end = len(existing) if end < 0 else end + len(_STEERING_SUFFIX)
        prefix = existing[:start].rstrip()
        suffix = existing[end:].lstrip("\n")
        parts = [part for part in (prefix, block, suffix) if part]
        updated = "\n\n".join(parts)
        return updated, updated != existing

    updated = f"{existing.rstrip()}\n\n{block}" if existing.strip() else block
    return updated, updated != existing


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
