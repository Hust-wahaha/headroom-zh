# Headroom ZH AutoDL Demo Runbook

## Goal

Show two things at the same time:

1. a real code agent running inside the AutoDL server terminal,
2. a browser-open dashboard that can be switched live during recording.

## Fixed demo baseline

For the current AutoDL recording path, lock the stack to:

- agent: `Codex CLI`
- proxy backend: `https://yunwu.ai/v1`
- model: `gpt-5.4-2026-03-05`
- proxy port: `8790`

Do **not** use `deepseek-v3-1-think-250821` for the Codex demo path.
It works on `/v1/chat/completions`, but Codex uses `/v1/responses`, and that
model does not support the OpenAI Responses API on Yunwu.

## Recommended setup

From the repo root on AutoDL, run:

```bash
export OPENAI_API_KEY="your_yunwu_key"
bash scripts/start_autodl_codex_gpt54_demo.sh
```

That script does the main demo isolation work:

- starts Headroom proxy in `screen`
- points it at `https://yunwu.ai/v1`
- creates a clean per-port `HEADROOM_WORKSPACE_DIR` so dashboard stats start
  from zero
- writes an isolated Codex `config.toml` that includes
  `env_key = "OPENAI_API_KEY"`
- uses isolated `HOME` / `CODEX_HOME` so stale AutoDL `~/.codex` state does
  not pollute the main demo path
- waits long enough for cold `kompress_zh` eager load on AutoDL

Then launch Codex in the same AutoDL terminal:

```bash
cd /root/autodl-tmp/headroom_zh_smoke
bash scripts/launch_autodl_codex_gpt54.sh
```

That keeps the real code agent in the terminal while the proxy stays exposed
for browser-side dashboard switching.

## Browser side

For AutoDL, prefer SSH local port forwarding instead of direct public-port
access.

On the local machine, open a terminal and run:

```bash
ssh -CNg -L 8790:127.0.0.1:8790 root@connect.nmb1.seetacloud.com -p 47263
```

Then open:

- `http://localhost:8790/dashboard`
- `http://localhost:8790/stats-history`

This is the more reliable access path for recording and browser-side switching.

## Recording checklist

- Start the proxy-wrapped agent in the AutoDL terminal.
- Use `gpt-5.4-2026-03-05`, not DeepSeek.
- Start local SSH port forwarding for `8790`.
- Open the dashboard in a browser tab.
- Run one reading-heavy demo case.
- Switch to the dashboard and show token savings.
- Switch back to the terminal and show the agent answer.

Expected clean-start behavior on `8790`:

- dashboard counters start at `0`
- a real long-context case should then drive `/stats` upward on the same run

## Known quirks

These are currently non-blocking:

- Codex may still print a warning about unsupported project-local config keys
  from `/root/.codex/config.toml` if stale global config exists on the server.
  The isolated demo path still works.
- A WebSocket handshake error line can appear in stderr during startup or probe
  runs while the actual turn still completes successfully.

## Recommended demo case

- Primary: `case_01_docs_review`
- Secondary: `case_03_codebase_explore`
- Tertiary: `case_02_log_triage`

## Recommended prompt

Paste directly in the AutoDL terminal inside Codex.
Do not feed the Chinese prompt through a Windows-generated temporary file,
because that path can turn Chinese text into `?` on the remote side.

Primary prompt:

```text
Read /root/autodl-tmp/headroom_zh_smoke/demo_assets/headroom_zh_agent_cases/case_01_docs_review/source_bundle.md

Summarize:
1. project current goal
2. completed work
3. top 3 next steps
4. risks and dependencies

Preserve anchors exactly when they appear:
paths, ports, commands, repo names, model names, script names, versions, checkpoints
```

Secondary prompt:

```text
Read /root/autodl-tmp/headroom_zh_smoke/demo_assets/headroom_zh_agent_cases/case_03_codebase_explore/source_bundle.md

Explain:
1. overall architecture path
2. key /v1/responses Chinese compression functions
3. where stats and dashboard metrics aggregate
4. what files to modify for eval or stat updates

Preserve anchors exactly when they appear:
paths, function names, endpoints, script names, models, ports
```

Tertiary prompt:

```text
Read /root/autodl-tmp/headroom_zh_smoke/demo_assets/headroom_zh_agent_cases/case_02_log_triage/source_bundle.md

Analyze:
1. the likely root cause
2. the strongest evidence from the logs
3. the next 3 debugging steps
4. risks, unknowns, and dependencies

Preserve anchors exactly when they appear:
paths, ports, timestamps, commands, service names, error strings
```
