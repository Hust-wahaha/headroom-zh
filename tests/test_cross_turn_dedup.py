"""Cross-turn dedup: cache-safety (prefix-monotonicity) + accuracy (info-preserving)."""

import re

from headroom.transforms.cross_turn_dedup import (
    DedupBlock,
    dedup_blocks,
    is_prefix_monotonic,
)

_PTR_RE = re.compile(r"identical to output shown earlier \(turn (\d+), lines (\d+)-(\d+)\)")


def _blk(text, turn, protected=False):
    return DedupBlock(text=text, turn=turn, protected=protected)


def _code(prefix, n):
    # A realistic, non-trivial multi-line source span.
    return "\n".join(
        f"{prefix}    result_{i} = compute_overdraft(business_id={i}, amount={i * 100})"
        for i in range(n)
    )


def _reconstruct(orig_blocks, out_blocks):
    """Replace each pointer with the referenced turn's original lines and assert
    it reproduces the original block — proves references are faithful & in-context."""
    by_turn = {b.turn: b.text.split("\n") for b in orig_blocks}
    for orig, out in zip(orig_blocks, out_blocks):
        if orig.protected:
            assert out.text == orig.text
            continue
        rebuilt = []
        for line in out.text.split("\n"):
            m = _PTR_RE.search(line)
            if m and line.startswith("[headroom:"):
                t, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
                assert t < orig.turn, "reference must point to an EARLIER turn"
                rebuilt.extend(by_turn[t][a : b + 1])
            else:
                rebuilt.append(line)
        assert "\n".join(rebuilt) == orig.text, f"turn {orig.turn} not faithfully reconstructable"


def test_verbatim_reread_is_folded_keep_earliest():
    span = _code("", 8)
    blocks = [_blk(f"cat merge.py\n{span}\ntail", 1), _blk(f"sed run\n{span}\nmore", 5)]
    out, stats = dedup_blocks(blocks)
    assert out[0].text == blocks[0].text  # earliest untouched
    assert "[headroom:" in out[1].text  # later occurrence folded
    assert stats["spans_folded"] == 1
    _reconstruct(blocks, out)


def test_cache_safety_prefix_monotonic():
    span = _code("x", 10)
    blocks = [
        _blk("intro line one\nintro line two\n" + span, 1),
        _blk("unrelated diff output\n@@ -1 +1 @@\n-a\n+b", 2),
        _blk("here again:\n" + span, 3),
        _blk("and once more\n" + span + "\ntrailer", 4),
    ]
    assert is_prefix_monotonic(blocks) is True


def test_below_min_lines_not_folded():
    span = _code("", 3)  # below min_lines (7)
    blocks = [_blk(span, 1), _blk(span, 2)]
    out, stats = dedup_blocks(blocks)
    assert stats["spans_folded"] == 0
    assert out[1].text == blocks[1].text


def test_trivial_repeated_lines_not_folded():
    junk = "\n".join(["}"] * 20)  # trivial lines only
    blocks = [_blk(junk, 1), _blk(junk, 2)]
    out, stats = dedup_blocks(blocks)
    assert stats["spans_folded"] == 0


def test_deterministic():
    span = _code("z", 9)
    blocks = [_blk(span, 1), _blk("mid\n" + span, 2), _blk(span, 3)]
    a, _ = dedup_blocks(blocks)
    b, _ = dedup_blocks(blocks)
    assert [x.text for x in a] == [x.text for x in b]


def test_protected_block_not_rewritten_but_is_reference_target():
    span = _code("", 8)
    blocks = [
        _blk(span, 1, protected=True),  # cache_control block — never rewritten
        _blk("later:\n" + span, 2),  # should still fold against the protected one
    ]
    out, stats = dedup_blocks(blocks)
    assert out[0].text == blocks[0].text
    assert "[headroom:" in out[1].text
    _reconstruct(blocks, out)


def test_info_preserving_reconstruction_multiref():
    s1 = _code("a", 7)
    s2 = _code("b", 8)
    blocks = [
        _blk("h1\n" + s1, 1),
        _blk("h2\n" + s2, 2),
        _blk("mix\n" + s1 + "\n---\n" + s2, 3),  # two folds in one block
    ]
    out, stats = dedup_blocks(blocks)
    assert stats["spans_folded"] == 2
    _reconstruct(blocks, out)


# --------------------------------------------------------------------------
# Integration: full router.apply() path (content-block tool_result format)
# --------------------------------------------------------------------------
def _mk_tok():
    from headroom.providers import OpenAIProvider
    from headroom.tokenizer import Tokenizer

    return Tokenizer(OpenAIProvider().get_token_counter("gpt-4o"), "gpt-4o")


def _toolmsg(text, tid):
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}],
    }


def _apply_fresh(messages):
    # Fresh router per call: tests the pure-function (prefix-monotonic) property,
    # not cross-call cache state.
    import copy

    from headroom.transforms.content_router import ContentRouter, ContentRouterConfig

    r = ContentRouter(ContentRouterConfig(lossless=True, enable_cross_turn_dedup=True))
    return r.apply(copy.deepcopy(messages), _mk_tok()).messages


def test_apply_dedups_reread_and_keeps_prefix_stable():
    span = "\n".join(
        f"    result_{i} = compute_overdraft(business_id={i}, amount={i * 100})" for i in range(12)
    )
    m1 = [
        {"role": "user", "content": "fix the overdraft bug"},
        {"role": "assistant", "content": "cat merge.py"},
        _toolmsg(f"$ cat merge.py\n{span}\n# end", "t1"),
    ]
    m2 = m1 + [
        {"role": "assistant", "content": "sed -n range"},
        _toolmsg(f"$ sed -n 1,20p merge.py\n{span}\n# more", "t2"),
    ]
    out1 = _apply_fresh(m1)
    out2 = _apply_fresh(m2)

    # Dedup fired on the later re-read (turn t2), earliest (t1) untouched.
    later = out2[-1]["content"][0]["content"]
    earlier = out2[2]["content"][0]["content"]
    assert "[headroom:" in later
    assert "[headroom:" not in earlier and span in earlier

    # CACHE-SAFETY at the router level: appending turn t2 did NOT change any
    # earlier message's emitted bytes → the prompt-cache prefix is stable.
    def _tool_texts(msgs):
        return [
            b["content"]
            for m in msgs
            if isinstance(m.get("content"), list)
            for b in m["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]

    assert _tool_texts(out2)[:1] == _tool_texts(out1)  # t1 block byte-identical


def test_apply_no_dedup_when_flag_off():
    span = "\n".join(f"    v_{i} = f({i})" for i in range(12))
    import copy

    from headroom.transforms.content_router import ContentRouter, ContentRouterConfig

    msgs = [
        _toolmsg(f"a\n{span}", "t1"),
        _toolmsg(f"b\n{span}", "t2"),
    ]
    r = ContentRouter(ContentRouterConfig(lossless=True, enable_cross_turn_dedup=False))
    out = r.apply(copy.deepcopy(msgs), _mk_tok()).messages
    joined = "".join(b["content"] for m in out for b in m["content"] if isinstance(b, dict))
    assert "[headroom:" not in joined


def test_apply_dedup_runs_in_ccr_mode_too():
    # Dedup is no longer gated to lossless mode: with lossless=False (CCR) and
    # the flag on, an exact re-read still folds to an in-context pointer.
    span = "\n".join(f"    total_{i} = reconcile(entry_id={i}, ledger=book_{i})" for i in range(12))
    import copy

    from headroom.transforms.content_router import ContentRouter, ContentRouterConfig

    msgs = [
        _toolmsg(f"$ cat ledger.py\n{span}\n# eof", "t1"),
        {"role": "assistant", "content": "re-check"},
        _toolmsg(f"$ cat ledger.py\n{span}\n# eof", "t2"),  # exact re-run
    ]
    r = ContentRouter(ContentRouterConfig(lossless=False, enable_cross_turn_dedup=True))
    out = r.apply(copy.deepcopy(msgs), _mk_tok()).messages
    joined = "".join(
        b["content"]
        for m in out
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict)
    )
    assert "[headroom:" in joined  # dedup fired despite lossless=False
