"""Cross-turn (whole-conversation) verbatim de-duplication.

Bash coding agents re-display the same file bytes many times across turns
(``cat foo.py`` -> ``sed -n 75,100p foo.py`` -> ``git diff`` -> ``cat foo.py``
again). Every per-block compressor is blind to this: the redundancy is *across*
blocks. This transform replaces a contiguous span in a later tool output that
already appeared verbatim in an earlier tool output with a compact in-context
pointer to the original.

Two hard invariants, both required for production use:

1. CACHE-SAFETY via *prefix-monotonicity*. Blocks are processed in order and a
   block is only ever matched against content from *strictly earlier* blocks.
   Therefore the rewritten output of blocks ``0..k`` is byte-identical whether
   or not block ``k+1`` exists — appending a turn never mutates an earlier turn,
   so the upstream prompt-cache prefix stays byte-stable. References are
   ABSOLUTE (an earlier block's ordinal), never relative, so a frozen pointer's
   text never changes. :func:`is_prefix_monotonic` asserts this.

2. ACCURACY via *no information leaves the window*. Only spans that are present
   VERBATIM in an earlier block's already-emitted output are back-referenced
   (the "verbatim corpus"), and the earliest occurrence is never rewritten
   (keep-earliest), so the original the pointer names is always physically in
   context. Only large, non-trivial contiguous spans are folded.

Pure stdlib, deterministic, never raises (returns input unchanged on any error).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DedupBlock", "dedup_blocks", "is_prefix_monotonic"]

# A run must be at least this many lines AND this many chars to be worth a
# pointer. Small dups are left alone (fragmenting context is not worth it) —
# and a larger floor keeps the pointer comfortably shorter than the span it
# replaces, so a fold is always a net byte win.
DEFAULT_MIN_LINES = 7
DEFAULT_MIN_CHARS = 120
# Cap anchor candidates examined per line so a hot line (e.g. ``    return``)
# can't blow up matching. Deterministic: candidates are kept in first-seen order.
MAX_ANCHOR_CANDIDATES = 16


@dataclass
class DedupBlock:
    """One tool-output block. ``turn`` is a STABLE absolute ordinal used in the
    pointer text (must not change as the conversation grows). ``protected`` marks
    blocks that must not be rewritten (e.g. carry a cache_control breakpoint) —
    they are still indexed as reference targets."""

    text: str
    turn: int
    protected: bool = False


def _is_trivial(line: str) -> bool:
    """A line too common/short to safely anchor a match on its own."""
    s = line.strip()
    if len(s) < 4:
        return True
    return s in {
        "return",
        "pass",
        "else:",
        "try:",
        "except:",
        "finally:",
        "break",
        "continue",
        "});",
        "})",
        "],",
        "),",
        '"""',
        "'''",
        "...",
    }


def _pointer(span: list[str], ref_turn: int, ref_line: int) -> str:
    """A one-line, obviously-a-reference marker naming the in-context original.

    Includes a first-line anchor so the model can locate the block it already
    saw. Marker-free of any ``hash=`` retrieval token: recovery is in-context
    (the original is physically present earlier in the same request)."""
    anchor = next((ln.strip() for ln in span if ln.strip()), "")
    if len(anchor) > 80:
        anchor = anchor[:77] + "..."
    end_line = ref_line + len(span) - 1
    return (
        f"[headroom: {len(span)} lines identical to output shown earlier "
        f"(turn {ref_turn}, lines {ref_line}-{end_line}) — starts: {anchor!r}]"
    )


def _index_lines(
    lines: list[str | None],
    block_pos: int,
    anchor_index: dict[str, list[tuple[int, int]]],
) -> None:
    """Record each non-trivial line's (block_pos, line_idx) as a future anchor.

    Keeps first-seen order and caps the candidate list per line. Only VERBATIM
    (surviving) lines should be passed here — never the lines of a span that was
    replaced by a pointer."""
    for li, ln in enumerate(lines):
        if ln is None or _is_trivial(ln):
            continue
        bucket = anchor_index.setdefault(ln, [])
        if len(bucket) < MAX_ANCHOR_CANDIDATES:
            bucket.append((block_pos, li))


def _longest_match(
    cur: list[str],
    start: int,
    anchor_index: dict[str, list[tuple[int, int]]],
    corpus: list[list[str | None]],
) -> tuple[int, int, int] | None:
    """Longest contiguous run in ``cur`` starting at ``start`` that appears
    verbatim inside a single earlier block. Returns (length, block_pos,
    ref_line_idx) or None. ``corpus[block_pos]`` holds that block's VERBATIM
    lines (``None`` where a span was already folded, which breaks contiguity)."""
    anchor = cur[start]
    candidates = anchor_index.get(anchor)
    if not candidates:
        return None
    best_len = 0
    best_bp = best_li = -1
    for bp, li in candidates:
        block_lines = corpus[bp]
        k = 0
        while (
            start + k < len(cur)
            and li + k < len(block_lines)
            and block_lines[li + k] is not None
            and cur[start + k] == block_lines[li + k]
        ):
            k += 1
        # Deterministic tie-break: longer wins; on ties keep the earliest
        # (smallest block_pos, then line) already held in best_*.
        if k > best_len:
            best_len, best_bp, best_li = k, bp, li
    if best_len == 0:
        return None
    return best_len, best_bp, best_li


def dedup_blocks(
    blocks: list[DedupBlock],
    *,
    min_lines: int = DEFAULT_MIN_LINES,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> tuple[list[DedupBlock], dict]:
    """Rewrite later verbatim spans to in-context pointers. Prefix-monotonic
    (cache-safe) and information-preserving (accuracy-safe). Returns
    (new_blocks, stats). Never raises."""
    stats = {"spans_folded": 0, "lines_removed": 0, "chars_removed": 0, "blocks": len(blocks)}
    try:
        # corpus[i] = verbatim lines of block i's OUTPUT (None where folded).
        corpus: list[list[str | None]] = []
        anchor_index: dict[str, list[tuple[int, int]]] = {}
        out_blocks: list[DedupBlock] = []

        for blk in blocks:
            lines = blk.text.split("\n")

            if blk.protected:
                # Never rewrite; still a valid verbatim reference target.
                verbatim: list[str | None] = list(lines)
                _index_lines(verbatim, len(corpus), anchor_index)
                corpus.append(verbatim)
                out_blocks.append(blk)
                continue

            out: list[str] = []
            verbatim = []
            i = 0
            n = len(lines)
            while i < n:
                m = _longest_match(lines, i, anchor_index, corpus)
                if m is not None and m[0] >= min_lines:
                    span = lines[i : i + m[0]]
                    span_text = "\n".join(span)
                    if len(span_text) >= min_chars:
                        ref_turn = blocks[m[1]].turn
                        ptr = _pointer(span, ref_turn, m[2])
                        out.append(ptr)
                        # Folded span is NOT verbatim in this block's output:
                        # mark None so it can't seed a later contiguous match,
                        # and don't index it (keep-earliest).
                        verbatim.extend([None] * m[0])
                        stats["spans_folded"] += 1
                        stats["lines_removed"] += m[0]
                        stats["chars_removed"] += len(span_text) - len(ptr)
                        i += m[0]
                        continue
                out.append(lines[i])
                verbatim.append(lines[i])
                i += 1

            # Index only the surviving verbatim lines of THIS block (first-seen).
            # None entries (folded spans) are kept in place so positions stay
            # aligned with ``corpus``; _index_lines skips them.
            _index_lines(verbatim, len(corpus), anchor_index)
            corpus.append(verbatim)
            out_blocks.append(DedupBlock(text="\n".join(out), turn=blk.turn, protected=False))

        return out_blocks, stats
    except Exception:  # never break the proxy
        return blocks, {"spans_folded": 0, "lines_removed": 0, "chars_removed": 0, "error": True}


def is_prefix_monotonic(
    blocks: list[DedupBlock],
    *,
    min_lines: int = DEFAULT_MIN_LINES,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> bool:
    """CACHE-SAFETY invariant: for every k, dedup(blocks[:k]) equals dedup(full)
    truncated to its first k blocks. i.e. appending a later turn never changes an
    earlier turn's rewritten bytes, so the prompt-cache prefix stays stable."""
    full, _ = dedup_blocks(blocks, min_lines=min_lines, min_chars=min_chars)
    full_text = [b.text for b in full]
    for k in range(1, len(blocks) + 1):
        partial, _ = dedup_blocks(blocks[:k], min_lines=min_lines, min_chars=min_chars)
        if [b.text for b in partial] != full_text[:k]:
            return False
    return True
