# Headroom ZH Status - 2026-06-20

## Scope

This note records the latest verified state of `headroom-zh-audit` after the
real `Codex CLI -> headroom -> yunwu GPT-5.4` AutoDL run was debugged,
measured, and replay-validated.

This is the current source-of-truth status for the Chinese demo stack.

## Executive summary

`headroom_zh` is now beyond smoke-only validation.

The meaningful path has been verified on the real AutoDL machine for:

- `Codex CLI`
- local Headroom proxy
- Yunwu OpenAI-compatible upstream at `https://yunwu.ai/v1`
- model `gpt-5.4-2026-03-05`
- browser-open `/dashboard` and `/stats-history`
- long Chinese reading-heavy workloads routed through `/v1/responses`

Current conclusion:

- the Chinese compression branch is genuinely active in the live Codex path,
- dashboard accounting is now credible for the demo path,
- the stack is ready for recording, classroom presentation, and downstream
  `headroom-zh` integration work.

## What changed in this round

### 1. Real runtime blocker identified and fixed

The earlier "Codex path looks like noop" diagnosis was wrong.

The real blocker was in `headroom/transforms/kompress_zh_compressor.py`:

- `PeftModel.from_pretrained(...)` could still trigger a HuggingFace metadata
  lookup even when the adapter files already existed locally.
- Inside the proxy runtime on AutoDL, that could fail with a network-side
  connection error and silently fall back to passthrough.
- The result looked like routing failure, but it was actually loader failure.

The fix was to resolve the LoRA adapter to a local snapshot first and load it
with `local_files_only=True`.

### 2. `/v1/responses` live-path accounting corrected

The WebSocket Codex path now records meaningful display stats for:

- attempted input size,
- live modified units,
- per-frame token savings,
- dashboard-visible totals.

Relevant implementation files already updated in the repo include:

- `headroom/proxy/handlers/openai.py`
- `headroom/proxy/server.py`
- `headroom/dashboard/templates/dashboard.html`
- `tests/test_openai_responses_compression_units.py`
- `tests/test_proxy_dashboard_stats_cache.py`

### 3. Demo bootstrap isolated from stale Codex state

The AutoDL demo scripts now use per-port isolated directories for:

- `HEADROOM_WORKSPACE_DIR`
- `CODEX_HOME`
- `HOME`

This prevents stale `~/.codex` state and old dashboard counters from leaking
into a fresh recording run.

Relevant scripts:

- `scripts/start_autodl_codex_gpt54_demo.sh`
- `scripts/launch_autodl_codex_gpt54.sh`

The bootstrap also keeps:

- `PATH` ready for `rtk`,
- `HF_ENDPOINT=https://hf-mirror.com`,
- a longer proxy startup wait for cold `kompress_zh` eager load.

## Verified evidence

### Direct compressor check on AutoDL

The Chinese compressor itself is working on the target machine.

A direct remote invocation compressed the main docs-review bundle to a much
shorter output and reported large savings:

- compressed length: `459`
- tokens saved: `2452`
- ratio: about `0.15`

### Captured real WebSocket frame replay

The first real Codex `/v1/responses` frame that carried the long Chinese tool
output was replayed through the live router/compression path.

Observed result:

- long `function_call_output.output` block compressed from length `3305` to `459`
- replay result: `modified = true`
- replay reported saved tokens: `1432`
- transforms included:
  - `router:openai:responses:function_call_output:text`
  - `text`

That proves the extractor shape and the live compression hook are correct for
the actual Codex payload shape.

### Clean `8795` verification instance

A real docs-review Codex run against the isolated verification instance
produced large recorded savings in live stats.

Key result:

- before total saved: `54056`
- after total saved: `103314`
- delta: `49258`

The same run also increased:

- `compressions_by_strategy.text`
- `codex_ws.units_modified_total`
- `codex_ws.unit_tokens_saved_sum`
- `codex_ws.frame_tokens_saved_sum`

Recent requests in `/stats` explicitly showed:

- `endpoint = responses_ws`
- `router:openai:responses:function_call_output:text`
- `text`

### Fresh `8790` demo instance from zero

The main demo port was then restarted with a clean isolated workspace.

Fresh start state:

- `tokens_saved = 0`
- `requests_total = 0`
- `text_count = 0`
- `ws_units_modified = 0`

After a real long Chinese docs-review Codex run:

- `tokens_saved = 27866`
- `requests_total = 10`
- `text_count = 12`
- `ws_units_modified = 49`
- `ws_unit_saved = 27668`
- `ws_frame_saved = 27866`

`proxy_savings.json` matched the same run:

- `lifetime_tokens_saved = 27866`
- `lifetime_requests = 10`

This is the current best demonstration-grade proof because it starts at zero,
then visibly grows during the real Codex session.

## Current recommended demo stack

For recording and live playback, lock the stack to:

- agent: `Codex CLI`
- proxy backend: `https://yunwu.ai/v1`
- model: `gpt-5.4-2026-03-05`
- main demo port: `8790`

Do not use DeepSeek on this Codex path.
The problem is not model quality; the problem is Yunwu support for Codex's
`/v1/responses` route.

## Recommended demo order

1. `case_01_docs_review`
2. `case_03_codebase_explore`
3. `case_02_log_triage`

Reasoning:

- `case_01` gives the clearest reading-heavy Chinese story.
- `case_03` is the best "real code agent" companion case.
- `case_02` is still useful, but less visually decisive as the lead demo.

See:

- `docs/HEADROOM_ZH_AUTODL_DEMO_RUNBOOK.md`
- `demo_assets/headroom_zh_agent_cases/`

## Known residual issues

These do not block the current demo path, but they are not yet fully polished:

- Codex can still print an `Ignored unsupported project-local config keys in /root/.codex/config.toml`
  warning if stale global config exists on the machine. The isolated demo path
  still works correctly despite this warning.
- A WebSocket handshake error line can occasionally appear in stderr during
  startup or probe runs, while the actual turn still completes and records
  savings normally.
- The local Windows machine is still not the preferred source of truth for
  end-to-end runtime verification because Rust/native pieces remain less stable
  there than on AutoDL.

## What this means now

At this point, the project has crossed from:

- "Chinese branch exists and smoke passes"

to:

- "real coding-agent path is live, measurable, and demo-ready."

That is enough to support:

- recorded demos,
- course-project explanation,
- repo-facing documentation,
- next-step integration into the fuller `headroom-zh` code line.

## Recommended next engineering work

1. Clean up the remaining stale `/root/.codex` warning path so the demo starts
   cleaner.
2. Turn the current recording workflow into a stable presentation checklist
   with fixed prompts and screenshot targets.
3. Continue integrating the validated `kompress_zh` path into the main
   `headroom-zh` fork while keeping the Chinese demo assets and runbooks
   project-specific.
