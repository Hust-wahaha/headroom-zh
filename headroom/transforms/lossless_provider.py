"""Pluggable provider for information-preserving compaction of protected output.

Excluded ("protected") tool results are kept out of *lossy* compression for
accuracy; the content router still applies reversible/data-preserving folds to
them via :meth:`ContentRouter._lossless_compact_excluded`. This module lets an
external extension supply that compaction instead of the built-in folds — the
same open-core pattern as the ``proxy_extension`` / ``compressor`` seams.

Contract — ``provider(content: str) -> tuple[compacted: str, kind: str] | None``:

* ``compacted`` MUST be information-preserving — byte-recoverable, or
  data-lossless for structured data (same guarantee the built-in path gives).
  Return ``None`` to leave the content unchanged.
* The provider MUST be deterministic and depend only on ``content`` (no
  cross-message state), so the proxy's prefix cache stays byte-stable across
  turns.

A registered provider is *authoritative*: when one is set the router does not run
its built-in folds — it falls back to the built-in only if the provider raises.
Default is ``None`` → the router uses its built-in folds, unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

#: ``content -> (compacted, kind) | None``.
LosslessProvider = Callable[[str], "tuple[str, str] | None"]

_provider: LosslessProvider | None = None


def set_lossless_provider(provider: LosslessProvider | None) -> None:
    """Register (or clear, with ``None``) the lossless compaction provider."""
    global _provider
    _provider = provider


def get_lossless_provider() -> LosslessProvider | None:
    """Return the registered provider, or ``None`` if the built-in should run."""
    return _provider
