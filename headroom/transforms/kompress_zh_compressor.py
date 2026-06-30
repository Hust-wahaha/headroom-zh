"""kompress_zh: Swift-backed Chinese plain-text compressor.

This compressor is intentionally separate from the original ModernBERT-based
Kompress pipeline. It targets Chinese-dominant plain-text blocks and keeps the
English Kompress path intact for English prose.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)

BASE_MODEL_ID = "Qwen/Qwen3.5-0.8B"
ADAPTER_MODEL_ID = "Deserveall/kompress_zh-baseline-v1-lora"
KOMPRESS_ZH_MAX_NEW_TOKENS_ENV = "HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS"  # now the CAP for the dynamic budget
KOMPRESS_ZH_RATIO_ENV = "HEADROOM_KOMPRESS_ZH_RATIO"  # input-units -> max_new_tokens ratio
KOMPRESS_ZH_SYSTEM_PROMPT_ENV = "HEADROOM_KOMPRESS_ZH_SYSTEM_PROMPT"
KOMPRESS_ZH_USER_PROMPT_ENV = "HEADROOM_KOMPRESS_ZH_USER_PROMPT"
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_THINK_SHELL_PATTERN = re.compile(r"^\s*<think>\s*</think>\s*", re.IGNORECASE | re.DOTALL)
_WHITESPACE_PATTERN = re.compile(r"\s+")

_engine_cache: dict[tuple[str, str, bool, int], Any] = {}
_engine_lock = threading.Lock()

DEFAULT_SYSTEM_PROMPT = (
    "你是一个面向中文 Agent 场景的压缩改写助手。"
    "你的任务是忠实压缩中文长段落，尽量缩短但不丢失关键约束、结论、路径、命令、数字与文件名。"
    "可轻量结构化、轻量文言化，但必须保持现代中文可读。"
)
DEFAULT_USER_PROMPT_TEMPLATE = (
    "请压缩改写下面这段中文文本。"
    "要求：保真、简洁、保留关键锚点；允许轻结构化和轻文言化，但不要写成纯古文。\n\n原文：\n{text}"
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s must be an integer, got %r; using default=%d", name, raw, default)
        return default
    return max(1, value)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s must be a float, got %r; using default=%s", name, raw, default)
        return default
    return value if value > 0 else default


def _system_prompt() -> str:
    return os.environ.get(KOMPRESS_ZH_SYSTEM_PROMPT_ENV, DEFAULT_SYSTEM_PROMPT)


def _user_prompt_template() -> str:
    return os.environ.get(KOMPRESS_ZH_USER_PROMPT_ENV, DEFAULT_USER_PROMPT_TEMPLATE)


def _approx_text_units(content: str) -> int:
    cjk_chars = len(_CJK_CHAR_PATTERN.findall(content))
    if cjk_chars:
        return len(_WHITESPACE_PATTERN.sub("", content))
    return len(content.split())


def _normalize_prediction_text(text: str) -> str:
    return _THINK_SHELL_PATTERN.sub("", text).strip()


def _build_request_messages(content: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": _user_prompt_template().format(text=content)}]


def is_kompress_zh_available() -> bool:
    try:
        import peft  # noqa: F401
        import swift  # noqa: F401
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class KompressZhConfig:
    base_model_id: str = BASE_MODEL_ID
    adapter_model_id: str = ADAPTER_MODEL_ID
    max_new_tokens: int = 192
    max_batch_size: int = 4
    language_model_only: bool = True


@dataclass
class KompressZhResult:
    compressed: str
    original: str
    original_tokens: int
    compressed_tokens: int
    model_used: str

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.compressed_tokens)


def _get_model_processor_language_only(model_id: str, *, enabled: bool) -> tuple[Any, Any]:
    from swift import get_model_processor

    if not enabled:
        return get_model_processor(model_id)

    attempts = (
        {"model_kwargs": {"language_model_only": True}},
        {"language_model_only": True},
    )
    type_errors: list[str] = []
    for kwargs in attempts:
        try:
            return get_model_processor(model_id, **kwargs)
        except TypeError as exc:
            type_errors.append(f"{kwargs}: {exc}")

    raise RuntimeError(
        "Failed to enable language-model-only mode with the local swift version.\n"
        + "\n".join(type_errors)
    )


def _build_engine(config: KompressZhConfig) -> Any:
    from peft import PeftModel
    from swift import get_template
    from swift.infer_engine import TransformersEngine

    model, tokenizer = _get_model_processor_language_only(
        config.base_model_id, enabled=config.language_model_only
    )
    model = PeftModel.from_pretrained(model, config.adapter_model_id)
    template = get_template(tokenizer, default_system=_system_prompt())
    if hasattr(template, "enable_thinking"):
        template.enable_thinking = False
    if hasattr(template, "response_prefix"):
        template.response_prefix = ""
    return TransformersEngine(model, template=template, max_batch_size=config.max_batch_size)


def _get_engine(config: KompressZhConfig) -> Any:
    key = (
        config.base_model_id,
        config.adapter_model_id,
        config.language_model_only,
        config.max_batch_size,
    )
    with _engine_lock:
        cached = _engine_cache.get(key)
        if cached is not None:
            return cached
        engine = _build_engine(config)
        _engine_cache[key] = engine
        return engine


def _has_cached_engine(config: KompressZhConfig) -> bool:
    key = (
        config.base_model_id,
        config.adapter_model_id,
        config.language_model_only,
        config.max_batch_size,
    )
    with _engine_lock:
        return key in _engine_cache


def unload_kompress_zh_model() -> bool:
    with _engine_lock:
        if not _engine_cache:
            return False
        _engine_cache.clear()
        return True


class KompressZhCompressor(Transform):
    name: str = "kompress_zh_compressor"

    def __init__(self, config: KompressZhConfig | None = None):
        self.config = config or KompressZhConfig()

    def compress(self, content: str, *, allow_download: bool = True, **_: Any) -> KompressZhResult:
        units = _approx_text_units(content)
        cjk_chars = len(_CJK_CHAR_PATTERN.findall(content))
        if units < 10 and cjk_chars < 20:
            return self._passthrough(content, units)

        if not is_kompress_zh_available():
            logger.debug("kompress_zh dependencies not available")
            return self._passthrough(content, units)

        if not allow_download and not _has_cached_engine(self.config):
            return self._passthrough(content, units)

        try:
            from swift.infer_engine import InferRequest, RequestConfig

            engine = _get_engine(self.config)
            # Dynamic generation budget: scale max_new_tokens by input size so
            # short docs finish naturally (finish_reason=stop) and long docs are
            # not truncated to a tiny fixed length (which silently drops anchors
            # — measured: a fixed 192 cut C3 1716->194 and demo_bundle 5884->207,
            # both finish_reason=length). Capped to bound latency on weak GPUs.
            # HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS is the CAP (default 1024);
            # HEADROOM_KOMPRESS_ZH_RATIO is the units->budget ratio (default 0.4,
            # set slightly above the model's natural retention so it reaches stop).
            ratio = _env_float(KOMPRESS_ZH_RATIO_ENV, 0.4)
            cap = _env_int(KOMPRESS_ZH_MAX_NEW_TOKENS_ENV, 1024)
            max_new = min(max(int(units * ratio), 64), cap)
            logger.debug(
                "kompress_zh dynamic max_new_tokens=%d (units=%d ratio=%.2f cap=%d)",
                max_new, units, ratio, cap,
            )
            request = InferRequest(messages=_build_request_messages(content))
            request_config = RequestConfig(
                max_tokens=max_new,
                temperature=0.0,
                top_p=1.0,
                top_k=20,
                repetition_penalty=1.0,
            )
            response = engine.infer([request], request_config)[0]
            compressed = _normalize_prediction_text(response.choices[0].message.content)
            if not compressed:
                return self._passthrough(content, units)
            compressed_tokens = _approx_text_units(compressed)
            return KompressZhResult(
                compressed=compressed,
                original=content,
                original_tokens=units,
                compressed_tokens=compressed_tokens,
                model_used=self.config.adapter_model_id,
            )
        except Exception as exc:
            logger.warning("kompress_zh compression failed: %s", exc)
            return self._passthrough(content, units)

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **_: Any,
    ) -> TransformResult:
        tokens_before = sum(tokenizer.count_text(str(m.get("content", ""))) for m in messages)
        transformed: list[dict[str, Any]] = []
        transforms_applied: list[str] = []

        for message in messages:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "tool" and isinstance(content, str):
                result = self.compress(content)
                transformed.append({**message, "content": result.compressed})
                if result.compressed != content:
                    transforms_applied.append(self.name)
            else:
                transformed.append(message)

        tokens_after = sum(tokenizer.count_text(str(m.get("content", ""))) for m in transformed)
        return TransformResult(
            messages=transformed,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
        )

    def _passthrough(self, content: str, n_words: int) -> KompressZhResult:
        return KompressZhResult(
            compressed=content,
            original=content,
            original_tokens=n_words,
            compressed_tokens=n_words,
            model_used=self.config.adapter_model_id,
        )
