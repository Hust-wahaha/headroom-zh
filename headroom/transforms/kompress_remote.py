"""Remote Kompress: offload ML compression to a hosted ``/compress`` endpoint.

Lets a sandboxed proxy — installed WITHOUT the ``[ml]`` extra (no torch/onnx) —
still run Kompress by calling a remote endpoint over HTTP. The class mirrors
:class:`~headroom.transforms.kompress_compressor.KompressCompressor`'s public
surface (``is_ready`` / ``preload`` / ``ensure_background_load`` / ``compress``),
so it is a drop-in at the ContentRouter seam.

Only the model inference is remote. The CCR store + retrieval marker stay
proxy-local (the endpoint is stateless, ``enable_ccr=False``), so
``headroom_retrieve`` keeps working and original content never persists off-box.

Enabled by ``HEADROOM_KOMPRESS_ENDPOINT`` (+ optional
``HEADROOM_KOMPRESS_ENDPOINT_TOKEN``) — see ``ContentRouter._get_kompress``.
"""

from __future__ import annotations

import logging

import httpx

from .kompress_compressor import KompressConfig, KompressResult, store_kompress_in_ccr

logger = logging.getLogger(__name__)

# Below this word count local Kompress passes through verbatim (KompressCompressor
# .compress); mirror it so we never pay a round-trip on a trivially small block.
_MIN_WORDS = 10

# Accept-any-shrink CCR gate, identical to KompressCompressor.compress: only
# store + mark when the shrink is worth the retrieval marker's own cost.
_CCR_RATIO_GATE = 0.8


class RemoteKompressCompressor:
    """Drop-in for KompressCompressor that POSTs to a hosted ``/compress`` endpoint.

    Fails OPEN: any network/HTTP error returns the content verbatim so a flaky
    endpoint degrades compression rather than breaking the proxy.
    """

    name = "kompress_compressor"

    def __init__(
        self,
        endpoint: str,
        token: str | None = None,
        config: KompressConfig | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.config = config or KompressConfig()
        self._url = endpoint.rstrip("/") + "/compress"
        self._headers = {"content-type": "application/json"}
        if token:
            self._headers["authorization"] = f"Bearer {token}"
        # httpx.Client is safe to share across the proxy's worker threads.
        self._client = httpx.Client(timeout=timeout)

    # Nothing to load locally; short-circuit the router straight to compress().
    def is_ready(self) -> bool:
        return True

    def ready_backend(self) -> str | None:
        return "remote"

    def preload(self, *, allow_download: bool = True) -> str:
        return "remote"

    def ensure_background_load(self) -> None:
        return None

    def _passthrough(self, content: str, n_words: int) -> KompressResult:
        return KompressResult(
            compressed=content,
            original=content,
            original_tokens=n_words,
            compressed_tokens=n_words,
            compression_ratio=1.0,
            model_used=self.config.model_id,
        )

    def compress(
        self,
        content: str,
        context: str = "",
        content_type: str | None = None,
        question: str | None = None,
        target_ratio: float | None = None,
        *,
        allow_download: bool = True,
    ) -> KompressResult:
        n_words = len(content.split())
        if n_words < _MIN_WORDS:
            return self._passthrough(content, n_words)

        try:
            resp = self._client.post(
                self._url,
                headers=self._headers,
                json={"content": content, "target_ratio": target_ratio},
            )
            resp.raise_for_status()
            data = resp.json()
            compressed = data["compressed"]
            if not isinstance(compressed, str):
                raise TypeError("remote Kompress response field 'compressed' must be a string")
            # Coerce the numeric/string metadata fields inside the fail-open guard.
            # A 200 response with a malformed field (e.g. a non-numeric string, or
            # an explicit JSON null: data.get returns None for a present key, and
            # float(None)/int(None) raise) would otherwise escape uncaught and break
            # the proxy request, defeating the fail-open contract this class promises.
            result = KompressResult(
                compressed=compressed,
                original=content,
                original_tokens=int(data.get("original_tokens", n_words)),
                compressed_tokens=int(data.get("compressed_tokens", len(compressed.split()))),
                compression_ratio=float(data.get("compression_ratio", 1.0)),
                model_used=str(data.get("model_used", self.config.model_id)),
            )
        except Exception as e:  # fail OPEN — never break the proxy on a bad endpoint
            logger.warning("Remote Kompress failed (%s); passing through", e)
            return self._passthrough(content, n_words)

        # CCR stays PROXY-LOCAL: endpoint is stateless (enable_ccr=False), so we
        # store the mapping + append the retrieval marker here — same policy and
        # marker format as KompressCompressor.compress.
        if self.config.enable_ccr and result.compression_ratio < _CCR_RATIO_GATE:
            cache_key = store_kompress_in_ccr(content, compressed, result.original_tokens)
            if cache_key:
                result.cache_key = cache_key
                result.compressed += (
                    f"\n[{result.original_tokens} items compressed to "
                    f"{result.compressed_tokens}. Retrieve more: hash={cache_key}]"
                )

        return result

    def close(self) -> None:
        self._client.close()
