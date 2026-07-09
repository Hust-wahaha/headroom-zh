"""Lossless-first dispatch (intended design).

Lossless folds run FIRST for every tool-output block, regardless of the
``lossless`` flag, and are accepted on a real byte reduction even when the word
count is flat (the case the word-ratio gate used to reject). In lossless-only
mode (flag on, no CCR) foldable content folds and non-foldable content is left
verbatim (no lossy drop). In CCR mode (flag off) a foldable block still keeps
its byte-exact fold — the lossless floor is never discarded by a later lossy
stage.
"""

from headroom.transforms.content_router import ContentRouter, ContentRouterConfig
from headroom.transforms.lossless_compaction import search_unheading


def _grep_block() -> str:
    # Long, repeated path prefixes → search_heading collapses to --heading form.
    # Word count stays flat/rises while bytes drop a lot (heading adds path words).
    paths = [
        "src/services/wallet/overdraft/automated_overdraft_initiation.py",
        "src/services/wallet/overdraft/capacity_limits.py",
    ]
    return (
        "\n".join(
            f"{p}:{ln}:    result = compute_overdraft_capacity(business_id, amount)"
            for p in paths
            for ln in range(1, 40)
        )
        + "\n"
    )


def _code_block() -> str:
    return (
        "\n".join(
            f"    def method_{i}(self, arg_{i}):\n        return self.reg[{i}] + arg_{i} * {i}"
            for i in range(40)
        )
        + "\n"
    )


def _compress(content: str, *, lossless: bool):
    router = ContentRouter(ContentRouterConfig(lossless=lossless))
    tr: list[str] = []
    out, was = router._compress_block_content(
        content,
        hash((content, lossless)),
        "",
        1.0,
        1.0,
        None,
        tr,
        {},
        [],
        "tool_result",
        "tool",
        True,
    )
    return out, was, tr


def test_flag_on_search_folds_lossless_byte_exact():
    block = _grep_block()
    out, was, tr = _compress(block, lossless=True)
    assert was is True
    assert tr == ["router:tool_result:lossless_search"]
    assert len(out) < len(block)
    # word count is flat/higher -> the old word-ratio gate would have rejected it
    assert len(out.split()) >= len(block.split())
    # fully recoverable
    assert search_unheading(out) == block


def test_flag_on_search_fold_is_deterministic():
    block = _grep_block()
    out1, _, _ = _compress(block, lossless=True)
    out2, _, _ = _compress(block, lossless=True)
    assert out1 == out2  # pure function of content -> prefix-cache safe


def test_flag_on_leaves_non_foldable_code_verbatim():
    # Lossless-only mode must never emit a lossy / marker-free drop.
    out, was, tr = _compress(_code_block(), lossless=True)
    assert was is False
    assert tr == []


def test_flag_off_still_keeps_lossless_floor_for_foldable():
    block = _grep_block()
    out, was, tr = _compress(block, lossless=False)
    assert was is True
    assert tr == ["router:tool_result:lossless_search"]
    assert search_unheading(out) == block


def test_has_lossless_fold_admits_small_block_below_size_floor():
    # A <500-char search block must be admitted — lossless has NO size floor
    # (the min_chars floor guards the lossy path only).
    router = ContentRouter(ContentRouterConfig(lossless=True))
    small = "\n".join(f"pkg/mod/long_filename.py:{n}:value = {n}" for n in range(1, 8)) + "\n"
    assert len(small) < 500
    assert router._has_lossless_fold(small) is True
    # non-foldable tiny code must NOT be admitted (stays "small")
    assert router._has_lossless_fold("def f():\n    return 1\n") is False


def test_lossless_mode_non_foldable_is_lossless_noop_not_ratio_too_high():
    # In lossless-only mode, code with no byte-lossless fold is left verbatim.
    # That is NOT a rejected compression, so it must not be bucketed as
    # ratio_too_high (which means "a lossy attempt didn't shrink enough").
    router = ContentRouter(ContentRouterConfig(lossless=True))
    code = "\n".join(f"    x{i} = compute_value({i}, offset={i * 3})" for i in range(60)) + "\n"
    rc: dict = {}
    out, was = router._compress_block_content(
        code,
        hash(code),
        "",
        1.0,
        1.0,
        None,
        [],
        rc,
        [],
        "tool_result",
        "tool",
        True,
    )
    assert was is False
    assert rc.get("lossless_noop", 0) >= 1
    assert rc.get("ratio_too_high", 0) == 0
