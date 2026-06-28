# Headroom ZH on Windows — Setup, Fixes & Multi-Scenario Quickstart

This guide makes `kompress_zh` (the Chinese compression channel) work on
Windows, including the **real-time Codex/Claude path through the local proxy**.
It is the Windows counterpart to `HEADROOM_ZH_AUTODL_REPRO_GUIDE.md` (Linux).

Verified on: Windows 11, RTX 4060 Laptop GPU (8 GB), CUDA 12.8, Python 3.12
(uv-managed), Codex CLI via an OpenAI-compatible upstream.

---

## TL;DR — the one Windows-specific bug you must know

On Windows, the prebuilt Rust core `headroom/_core.pyd`'s
`detect_content_type` **hangs indefinitely on any input**. It sits on the
text-unit compression path, so every tool-output unit that should reach
`kompress_zh` hangs until the compression timeout and is forwarded
**uncompressed** — the GPU stays idle, and the dashboard never moves above the
fixed `tool_schema_compaction` baseline (~1.3 %).

**Fix:** set `HEADROOM_RUST_DETECT=0` (this fork) to route content detection
through the pure-Python regex detector. Default behavior (Rust) is unchanged on
platforms where the Rust core works (Linux/AutoDL run `_core` built from source
and are unaffected).

> Why AutoDL/Linux doesn't hit this: the `.py` code is identical; only the
> compiled `_core` artifact differs. Linux builds `_core` from source (works);
> Windows here uses a prebuilt `_core.pyd` whose magika/ONNX-Runtime detection
> hangs. AutoDL additionally runs with `HEADROOM_REQUIRE_RUST_CORE=false`.

---

## 1. One-time environment setup (deployment)

Root cause of the original "Chinese never compresses" on Windows was a broken
torch (`c10.dll` `OSError [WinError 1114]`) from building the venv on Anaconda's
Python. Do NOT use Anaconda base Python.

```powershell
# 0. Leave conda base (its MKL/OpenMP DLLs conflict with torch libiomp5md.dll)
conda deactivate

# 1. Clean uv-managed CPython + venv in the repo
uv python install 3.12
cd <repo>\headroom-zh
uv venv --python cpython-3.12.13-windows-x86_64-none .venv

# 2. Install deps: cu128 GPU torch + ms-swift Qwen implicit deps + headroom
uv pip install --python .venv\Scripts\python.exe `
  --index-strategy unsafe-best-match -r eval\requirements-windows.txt
#   torch/torchvision via --extra-index-url https://download.pytorch.org/whl/cu128
#   plus explicit: torchvision, qwen-vl-utils, av  (ms-swift Qwen loader needs these)

# 3. editable mount (no cargo on Windows): write repo root into a .pth.
#    If the path has non-ASCII chars AND Python is 3.12.x, write the .pth as
#    GBK(cp936) (Python 3.12 reads .pth in the locale encoding; 3.13+ uses UTF-8).

# 4. Verify
$env:PYTHONUTF8=1; $env:HF_ENDPOINT="https://huggingface.co"
.venv\Scripts\python.exe -c "import torch;print('cuda',torch.cuda.is_available());from headroom.transforms.kompress_zh_compressor import is_kompress_zh_available as a;print('zh',a())"
#   expect: cuda True   zh True
```

Notes:
- The LoRA adapter `Deserveall/kompress_zh-baseline-v1-lora` downloads reliably
  only from `huggingface.co` on some networks (hf-mirror blob endpoint may fail);
  use `HF_ENDPOINT=https://huggingface.co` for the adapter.
- `is_kompress_zh_available()` only catches `ImportError`; a broken torch raises
  `OSError`, so a DLL failure shows as a hard error, not graceful skip.

---

## 2. Environment variables (this fork)

| Variable | Purpose |
|---|---|
| `HEADROOM_RUST_DETECT=0` | **Required on Windows.** Bypass the hanging Rust content detector; use Python regex detector. |
| `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS` | Chinese compression output budget. Smaller (e.g. 128) = faster decode; larger (1024) = higher fidelity. |
| `HEADROOM_COMPRESSION_TIMEOUT_SECONDS` | Compression timeout (now configurable; default 30). Weak GPUs want 60–120. |
| `HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE=1` | On timeout, forward the original instead of returning 413 — keeps the client from retry-looping. |
| `HF_ENDPOINT=https://huggingface.co` | Model/adapter download endpoint. |
| `OPENAI_API_KEY` | Upstream API key (when using API-key auth). |
| `OPENAI_API_URL` | **Proxy upstream base** (NOT `OPENAI_BASE_URL`). e.g. `https://yunwu.ai`. Proxy appends `/v1/responses`. |
| `HEADROOM_CODEX_WIRE_DEBUG=1` (+ `_DIR`) | Capture request/response frames for debugging. |

---

## 3. Multi-scenario quickstart

Pick the row that matches your setup. All scenarios require
`HEADROOM_RUST_DETECT=0` (§ TL;DR) and a healthy venv (§1).

Two integration styles:
- **Durable wrap (global):** `headroom wrap <client>` writes the client's global
  config (`~/.codex/config.toml` `model_provider="headroom"`). Convenient, but it
  routes **every** session of that client through the proxy — even in unrelated
  projects, and it fails when the proxy is not running. It also re-writes the
  provider block on each run (dropping any hand-added `env_key`).
- **Scoped (recommended for shared machines):** keep the global config clean;
  run `headroom proxy` yourself and point the client at it per session
  (`codex -c model_provider=headroom ...`). No global side effects.

> Stop the proxy reliably (Ctrl+C often can't, because the loaded CUDA model
> blocks shutdown):
> ```powershell
> Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
>   Where-Object { $_.CommandLine -like '*headroom.cli*proxy*' } |
>   ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
> ```

### Scenario A — Codex + OpenAI-compatible relay (e.g. yunwu) + API key — DURABLE wrap

This is the "global" style. The relay must support the Responses API
(`/v1/responses`); many relays support it over HTTP but **not** WebSocket.

One-time `~/.codex/config.toml` (the wrap injects most of this; ensure `env_key`
and `supports_websockets=false` are present):

```toml
model = "gpt-5.4"                       # use a model the relay actually serves
model_provider = "headroom"
[model_providers.headroom]
name = "OpenAI via Headroom proxy"
base_url = "http://127.0.0.1:8787/v1"
supports_websockets = false             # relay 404s WS /v1/responses; force HTTP
env_key = "OPENAI_API_KEY"              # else Codex sends no bearer -> 401
env_http_headers = { "X-Headroom-Project" = "HEADROOM_PROJECT" }
```

```powershell
codex logout                            # Codex defaults to ChatGPT OAuth; switch to API key
# Terminal A — proxy (keep open; do NOT use `headroom wrap`, it rewrites config)
cd <repo>\headroom-zh; conda deactivate; .\.venv\Scripts\Activate.ps1
$env:OPENAI_API_KEY="sk-..."            # or read from a user env var
$env:OPENAI_API_URL="https://yunwu.ai"  # proxy upstream (NOT OPENAI_BASE_URL)
$env:HF_ENDPOINT="https://huggingface.co"; $env:PYTHONUTF8=1
$env:HEADROOM_RUST_DETECT=0
$env:HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS=128
$env:HEADROOM_COMPRESSION_TIMEOUT_SECONDS=120
$env:HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE=1
headroom proxy --openai-api-url "https://yunwu.ai"
# Terminal B — plain codex (NOT `headroom wrap codex`)
$env:OPENAI_API_KEY="sk-..."
cd <your project>; codex
```

### Scenario B — Codex + relay — SCOPED (no global config change)

Keep `~/.codex/config.toml` free of `model_provider="headroom"`. Start the proxy
(Terminal A as in A), then per session:

```powershell
codex -c model_provider=headroom `
  -c 'model_providers.headroom.base_url="http://127.0.0.1:8787/v1"' `
  -c 'model_providers.headroom.env_key="OPENAI_API_KEY"' `
  -c 'model_providers.headroom.supports_websockets=false'
```

Only sessions launched this way go through Headroom; everything else is untouched.

### Scenario C — Codex + official OpenAI

Same as A/B but set the proxy upstream to OpenAI and use an OpenAI key:
`$env:OPENAI_API_URL="https://api.openai.com"`. WebSockets are supported here, so
`supports_websockets=true` is fine.

### Scenario D — Claude Code + Headroom

Point Claude at the proxy via `ANTHROPIC_BASE_URL`:

```powershell
# Terminal A: headroom proxy (with HEADROOM_RUST_DETECT=0 etc., upstream = your Anthropic-compatible endpoint)
# Terminal B:
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8787"
claude
```

### Scenario E — Proxy only (any OpenAI-compatible client)

```powershell
headroom proxy --openai-api-url "<upstream>"
# then point your app: OPENAI_BASE_URL=http://127.0.0.1:8787/v1
```

---

## 4. Weak-GPU tuning (8 GB laptops)

- Inference time is dominated by the **output budget**
  (`HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS`), not input size, until inputs get very
  large. Laptop GPUs throttle under sustained load (SW Power Cap), so timings
  drift; plug in AC and use the "best performance" power profile.
- Recommended laptop defaults: budget 128, timeout 120, fail-open on.
- Very large single Chinese units (≳20k chars) can exceed timeout or OOM on 8 GB;
  fail-open keeps the client working (those units pass through uncompressed).
- For stable, high-savings real-time demos, prefer a larger GPU (see AutoDL guide).

---

## 5. Troubleshooting (symptom → cause → fix)

| Symptom (client / proxy.log) | Cause | Fix |
|---|---|---|
| Long "working", fan on, **GPU idle**, dashboard stuck ~1.3 % | Rust `_core.pyd` `detect_content_type` hangs | `HEADROOM_RUST_DETECT=0` |
| `import torch` → `OSError [WinError 1114] c10.dll` | venv on Anaconda Python / cpu torch on non-ASCII path | rebuild venv on uv CPython + cu128 torch (§1) |
| `401 Missing bearer` (from proxy) | Codex provider missing `env_key` | add `env_key="OPENAI_API_KEY"` |
| `401 invalid_api_key` with `cf-ray` (from upstream) | proxy forwarded to api.openai.com, not your relay | set `OPENAI_API_URL=https://<relay>` (not `OPENAI_BASE_URL`) |
| `Missing environment variable OPENAI_API_KEY` (from Codex) | Codex process lacks the key | export `OPENAI_API_KEY` in the codex shell |
| `WS upstream ... HTTP 404 Invalid URL (/v1/responses)` then retry churn | relay has no WS `/v1/responses` | `supports_websockets=false` (forces HTTP) |
| Connect refused `os error 10061` at 8787 | proxy not running | start `headroom proxy` |
| `/status` shows Headroom proxy in unrelated projects | durable wrap edited global config | use Scoped style (Scenario B) or remove the global `model_provider` block |
| First Chinese block times out, later ones OK | kompress_zh cold load on first call | already mitigated by startup preload; raise timeout if needed |

---

## 6. What this fork changes vs upstream

- `content_router._detect_content`: `HEADROOM_RUST_DETECT=0` escape hatch
  (Python regex detector) for the Windows Rust-core hang. Default unchanged.
- `content_router.eager_load_compressors`: preload `kompress_zh` at startup
  (mirrors the English Kompress preload) to remove first-request cold load.
- `helpers.COMPRESSION_TIMEOUT_SECONDS`: configurable via
  `HEADROOM_COMPRESSION_TIMEOUT_SECONDS`.
