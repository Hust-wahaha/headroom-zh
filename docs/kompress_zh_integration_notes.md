# kompress_zh Integration Notes

## Goal

Integrate `kompress_zh` into `headroom-zh` as an additional Chinese plain-text
compression branch while preserving the original English `Kompress` path.

This is not a repo-wide replacement of `Kompress`.

## Intended Final Behavior

- English or non-Chinese-dominant plain text:
  - stays on the original `Kompress` path
- Chinese-dominant plain text:
  - routes to `kompress_zh`
- Structured content:
  - keeps existing Headroom routing
  - JSON/code/log/html should not be hijacked by `kompress_zh`

## Changes That Should Be Kept

### 1. Compression API surface

Files:

- `headroom/compress.py`

Keep:

- `CompressConfig.kompress_zh_model`
- pass-through of `kompress_zh_model` into `pipeline.apply(...)`

Reason:

- allows runtime override of the Chinese adapter without disturbing the
  original English compressor config

### 2. Router changes

Files:

- `headroom/transforms/content_router.py`

Keep:

- `_is_chinese_dominant_text(...)`
- `_get_kompress_zh(...)`
- `_runtime_kompress_zh_model`
- Chinese-aware `_try_ml_compressor(...)`
- `_estimate_text_tokens(...)` and related call-site replacements

Reason:

- language routing is the core integration seam
- Chinese compression must not be judged with the old whitespace-only token
  estimate or valid compressions may be rejected by router thresholds

### 3. Chinese compressor implementation

Files:

- `headroom/transforms/kompress_zh_compressor.py`

Keep:

- Swift-backed inference path
- `language_model_only=True`
- `PeftModel.from_pretrained(...)`
- `get_template(..., default_system=...)`
- disable visible thinking output
- request shape aligned to project eval path: template carries system prompt,
  request sends user message only

Reason:

- the earlier bare `transformers` loader produced prompt echo / passthrough
- the Swift path was the one validated against the actual training/eval stack

### 4. Dependencies

Files:

- `pyproject.toml`

Keep:

- `peft>=0.11.0,<1.0`
- `ms-swift>=4.1.3`

Reason:

- `kompress_zh` now depends on the same inference stack as the training/eval
  project

### 5. Regression coverage

Files:

- `tests/test_transforms/test_content_router.py`

Keep:

- Chinese-dominant detector tests
- English text stays on original `_get_kompress`
- Chinese text uses `_get_kompress_zh`

Reason:

- these are the minimum routing regressions worth pinning

## Changes That Should NOT Be Carried Forward Blindly

### 1. Repo-wide README wording that implies Kompress was replaced

Do not present the repo as if `kompress_zh` replaced the original text
compressor entirely.

Correct framing:

- Headroom keeps the original English/plain-text compressor
- `kompress_zh` is an additional Chinese branch

### 2. Experimental smoke scripts

Do not ship these as product code:

- temporary remote upload scripts
- one-off smoke harnesses
- AutoDL-only validation helpers

These are validation artifacts, not user-facing repo assets.

### 3. Unrelated ONNX export changes

Do not mix Chinese `kompress_zh` integration with unrelated edits to legacy
ONNX export scripts unless there is a separate reason to keep them.

## Validation Status

Validated on the remote AutoDL environment on 2026-06-14 and 2026-06-15:

- real base model cache present
- real adapter checkpoint used
- English route confirmed independent
- Chinese route produced actual compressed text
- `ContentRouter.apply(...)` level validation passed for:
  - OpenAI-style `tool` message path
  - content-block `tool_result` path

Representative observed result:

- Chinese tool output was compressed and accepted by the router
- transformed markers included:
  - `router:text:...`
  - `router:tool_result:text`

## Remaining Non-Blocking Cleanup

- local full `pytest` is still not a trustworthy gate on this Windows machine
  because the repo-local environment lacks `headroom._core` and `tiktoken`
- the Windows zip packaging path used for remote smoke emits a Linux `unzip`
  warning about backslash separators; harmless for smoke, but not ideal for a
  polished validation toolchain

## Recommended Next Step

Use `headroom-zh-publish-tmp` as the clean promotion worktree.

Reason:

- it contains only the relevant integration changes
- `headroom-zh-audit` is polluted with many anonymous temporary files and is
  not a good direct commit surface
