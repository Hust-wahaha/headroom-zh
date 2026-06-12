"""kompress_zh: Qwen + LoRA Chinese plain-text compressor.

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

from .base import Transform

logger = logging.getLogger(__name__)

BASE_MODEL_ID = "Qwen/Qwen3.5-0.8B"
ADAPTER_MODEL_ID = "Deserveall/kompress_zh-baseline-v1-lora"
KOMPRESS_ZH_MAX_NEW_TOKENS_ENV = "HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS"
KOMPRESS_ZH_PROMPT_ENV = "HEADROOM_KOMPRESS_ZH_PROMPT"
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_model_cache: dict[tuple[str, str], tuple[Any, Any]] = {}
_model_lock = threading.Lock()

DEFAULT_PROMPT_TEMPLATE = (
    "请将下面这段中文文本压缩改写为更短版本。要求：保留核心语义；尽量保留路径、命令、文件名、"
    "数字、URL 等关键锚点；允许轻结构化；允许轻文言压缩感；不要编造新信息。\n\n"
    "<原文>\n{text}\n"
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


def _prompt_template() -> str:
    return os.environ.get(KOMPRESS_ZH_PROMPT_ENV, DEFAULT_PROMPT_TEMPLATE)


def _approx_text_units(content: str) -> int:
    whitespace_tokens = len(content.split())
    cjk_chars = len(_CJK_CHAR_PATTERN.findall(content))
    return max(whitespace_tokens, cjk_chars)


def is_kompress_zh_available() -> bool:
    try:
        import peft  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass
class KompressZhConfig:
    base_model_id: str = BASE_MODEL_ID
    adapter_model_id: str = ADAPTER_MODEL_ID
    device_map: str = "auto"
    max_new_tokens: int = 192


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


def _load_model(base_model_id: str, adapter_model_id: str, device_map: str) -> tuple[Any, Any]:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    key = (base_model_id, adapter_model_id)
    with _model_lock:
        cached = _model_cache.get(key)
        if cached is not None:
            return cached

        tokenizer = AutoTokenizer.from_pretrained(base_model_id, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            base_model_id,
            trust_remote_code=True,
            device_map=device_map,
            torch_dtype="auto",
        )
        model = PeftModel.from_pretrained(model, adapter_model_id)
        model.eval()

        _model_cache[key] = (model, tokenizer)
        return model, tokenizer


def unload_kompress_zh_model() -> bool:
    with _model_lock:
        if not _model_cache:
            return False
        _model_cache.clear()
        return True


class KompressZhCompressor(Transform):
    name: str = "kompress_zh_compressor"

    def __init__(self, config: KompressZhConfig | None = None):
        self.config = config or KompressZhConfig()

    def compress(self, content: str, **_: Any) -> KompressZhResult:
        units = _approx_text_units(content)
        cjk_chars = len(_CJK_CHAR_PATTERN.findall(content))
        if units < 10 and cjk_chars < 20:
            return self._passthrough(content, units)

        if not is_kompress_zh_available():
            logger.debug("kompress_zh dependencies not available")
            return self._passthrough(content, units)

        try:
            model, tokenizer = _load_model(
                self.config.base_model_id,
                self.config.adapter_model_id,
                self.config.device_map,
            )
            prompt = _prompt_template().format(text=content)
            inputs = tokenizer(prompt, return_tensors="pt")
            inputs = inputs.to(model.device)
            outputs = model.generate(
                **inputs,
                max_new_tokens=_env_int(
                    KOMPRESS_ZH_MAX_NEW_TOKENS_ENV, self.config.max_new_tokens
                ),
            )
            prompt_tokens = inputs["input_ids"].shape[-1]
            generated_ids = outputs[0][prompt_tokens:]
            compressed = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
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

    def _passthrough(self, content: str, n_words: int) -> KompressZhResult:
        return KompressZhResult(
            compressed=content,
            original=content,
            original_tokens=n_words,
            compressed_tokens=n_words,
            model_used=self.config.adapter_model_id,
        )
