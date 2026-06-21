# Headroom ZH AutoDL Repro Guide

## Purpose

This note is for teammates who need to continue or reproduce the current
`headroom-zh` AutoDL path, especially on a fresh or partially fresh
environment.

It is **not** the primary recording script walkthrough. For the exact demo flow,
see:

- `docs/HEADROOM_ZH_AUTODL_DEMO_RUNBOOK.md`
- `docs/HEADROOM_ZH_STATUS_2026-06-20.md`

This guide focuses on:

- what is already verified,
- what the current scripts assume,
- what must usually be rebuilt on a new AutoDL machine,
- what is still uncertain and should not be overstated.

## Scope boundary

This guide reflects the currently verified working path:

- `Codex CLI`
- local Headroom proxy
- OpenAI-compatible upstream at `https://yunwu.ai/v1`
- model `gpt-5.4-2026-03-05`
- Chinese reading-heavy workloads through `/v1/responses`
- dashboard checks on `/dashboard` and `/stats-history`

It does **not** claim that a completely blank AutoDL machine has already been
re-derived end to end with zero manual repair.

In other words:

- the path is **verified on the current prepared AutoDL environment**,
- the path is **documented for teammate continuation**,
- but a brand-new machine may still require extra environment work.

## What is already verified

These statements are backed by the current project docs and scripts:

- `kompress_zh` is active on the verified Codex live path.
- the Chinese branch can produce visible savings on real reading-heavy runs.
- `/stats`, `/dashboard`, and `/stats-history` can reflect that activity.
- the demo bootstrap isolates `HEADROOM_WORKSPACE_DIR`, `HOME`, and
  `CODEX_HOME` per port so stale state does not leak into the visible counters.
- the current recommended demo port is `8790`.

## What the current scripts assume

The current AutoDL bootstrap is opinionated. On a new machine, do not assume
these defaults exist automatically.

### 1. Python path assumption

`scripts/start_autodl_codex_gpt54_demo.sh` defaults to:

```bash
PYTHON_BIN=/root/autodl-tmp/qwen_ws/.venv/bin/python
```

This means the script assumes:

- a Python virtual environment already exists,
- the Headroom repo can be imported from that interpreter,
- required runtime packages for the current proxy path are already installed.

If that venv does not exist on the new machine, set `PYTHON_BIN` explicitly or
rebuild an equivalent environment first.

### 2. Node / Codex assumption

The launch path assumes:

```bash
PATH=/root/.headroom/bin:/opt/node-v22/bin:$PATH
```

and then launches:

```bash
codex
```

This means the script assumes:

- Node is available under `/opt/node-v22/bin`,
- `codex` is already installed and callable in that environment,
- `rtk` can be found under `/root/.headroom/bin`.

If a new AutoDL machine does not already have those pieces, the demo scripts
will not self-install all of them for you.

### 3. API key assumption

Both demo scripts read:

```bash
ENV_FILE=/root/.config/headroom-zh/env.sh
```

If that file exists, it is sourced. Otherwise `OPENAI_API_KEY` must already be
exported in the shell.

At minimum, the current path expects:

```bash
export OPENAI_API_KEY="..."
```

If the key is missing, the scripts fail early by design.

### 4. HF mirror assumption

The bootstrap sets:

```bash
HF_ENDPOINT=https://hf-mirror.com
```

This is not cosmetic. It is part of the current practical path for pulling
model-related artifacts reliably in the verified environment.

On a new environment:

- keep this unless you have a better reachable mirror,
- expect slower first load if cache is cold,
- expect possible failures if mirror access is unstable.

### 5. Rust core bypass assumption

The verified path intentionally uses:

```bash
HEADROOM_REQUIRE_RUST_CORE=false
```

This is important.

The current AutoDL demonstration path is **Python-first**, not a fresh Rust-core
bring-up. Do not waste time trying to prove Rust parity before the Python path
is working.

## Recommended reproduction ladder

Do not jump straight to the full Codex demo on a new environment.

Use this ladder instead.

### Level 0: environment inspection

Before running anything, check:

- does `PYTHON_BIN` exist?
- does `codex` exist?
- does `/opt/node-v22/bin` exist?
- does `/root/.config/headroom-zh/env.sh` exist?
- does the repo path exist where you think it exists?

Suggested checks:

```bash
ls /root/autodl-tmp/qwen_ws/.venv/bin/python
which codex
ls /opt/node-v22/bin
cat /root/.config/headroom-zh/env.sh
```

If these basics fail, fix them first instead of debugging proxy behavior.

### Level 1: smoke path only

Run the narrow smoke test first:

```bash
python scripts/smoke_autodl_headroom.py
python scripts/smoke_autodl_headroom.py --expect-kompress
```

Why:

- this path uses a mock upstream,
- it verifies local proxy startup,
- it verifies `/readyz`, `/dashboard`, `/stats-history`,
- it avoids mixing Codex runtime issues with proxy/runtime issues too early.

If Level 1 fails, do **not** proceed to Codex yet.

### Level 2: isolated proxy bootstrap

If smoke passes, launch the real proxy bootstrap:

```bash
export OPENAI_API_KEY="your_key"
bash scripts/start_autodl_codex_gpt54_demo.sh
```

Check:

- proxy ready on `8790`,
- screen session created,
- `/readyz` works,
- generated `CODEX_HOME` config exists,
- dashboard starts from zero.

### Level 3: real Codex path

Then launch:

```bash
bash scripts/launch_autodl_codex_gpt54.sh
```

At this point, use a **reading-heavy** case only.

Do **not** use a tiny or generic task, because that can make the system look
useless even when the path is technically fine.

## Fresh-environment checklist

On a new AutoDL machine, expect to re-check or rebuild at least these items:

### Required

- repo checkout path
- Python interpreter / venv
- Node path
- `codex` binary availability
- `OPENAI_API_KEY`
- network reachability for the selected upstream
- model artifact reachability or cache

### Highly recommended

- isolated per-port workspace
- isolated `HOME`
- isolated `CODEX_HOME`
- SSH port forwarding for browser-side dashboard viewing
- `screen` for long-running proxy process

### Nice to have, but not the first blocker

- prettier warning-free Codex startup
- Rust-core path
- fine-grained metrics cleanup

## Known good commands

### Start proxy path

```bash
export OPENAI_API_KEY="your_key"
bash scripts/start_autodl_codex_gpt54_demo.sh
```

### Launch Codex on the isolated path

```bash
bash scripts/launch_autodl_codex_gpt54.sh
```

### Attach to the proxy screen

```bash
screen -r hrzh_demo_8790
```

If that exact name does not exist, inspect:

```bash
screen -list
```

### Browser-side local forwarding

On the local machine:

```bash
ssh -CNg -L 8790:127.0.0.1:8790 root@connect.nmb1.seetacloud.com -p 47263
```

Then open:

- `http://localhost:8790/dashboard`
- `http://localhost:8790/stats-history`

## Common failure modes

### 1. `OPENAI_API_KEY` missing

Symptom:

- bootstrap fails immediately,
- Codex launch script refuses to start.

Action:

- export the key in the shell, or
- put it in `/root/.config/headroom-zh/env.sh`.

### 2. Proxy never becomes ready

Symptom:

- `proxy did not become ready on port 8790`

Possible causes:

- cold model load,
- bad Python environment,
- failed upstream-related initialization,
- missing packages,
- path mismatch for `PYTHON_BIN`.

Action:

```bash
screen -r hrzh_demo_8790
```

Look at the actual runtime trace before changing multiple variables at once.

### 3. Dashboard is not zero on a "fresh" run

Symptom:

- counters already nonzero before the demo.

Possible cause:

- stale workspace or reused isolated directories.

Action:

- verify `HEADROOM_WORKSPACE_DIR`,
- verify `CODEX_HOME_DIR`,
- verify `CODEX_USER_HOME_DIR`,
- confirm the bootstrap really removed the prior visible counters.

### 4. Codex shows config warnings

Symptom:

- warnings about unsupported keys in `/root/.codex/config.toml`

Current status:

- known non-blocking in the verified path,
- annoying, but not yet treated as a hard blocker.

Do not mistake this for proof that the isolated demo path failed.

### 5. WebSocket noise appears during startup

Symptom:

- handshake or transport warnings in stderr

Current status:

- sometimes still non-blocking,
- a run can still complete and record savings.

Judge by:

- whether the turn completed,
- whether `/stats` moved,
- whether `/dashboard` reflects the run.

### 6. Wrong model choice on the Codex path

Symptom:

- `/v1/responses` path fails or behaves inconsistently.

Current recommendation:

- use `gpt-5.4-2026-03-05` on the current Codex demo path,
- do **not** switch that path to DeepSeek for now.

### 7. Windows local SSH config issue

Symptom:

- local port-forward command fails with SSH config permission errors.

Current status:

- this is a local client-side issue, not a server-side Headroom bug.

If it happens, fix the local SSH config permissions or bypass the problematic
local config in an OS-appropriate way.

This guide does not normalize one exact local fix because teammate machines may
differ.

## What is still unclear or not fully re-validated

These points should be stated honestly to avoid misleading teammates.

### 1. Blank-machine rebuild is not fully re-derived here

We know the prepared AutoDL environment works.

We do **not** claim that this document alone fully reconstructs:

- the Python environment from zero,
- the Node/Codex installation from zero,
- every dependency fetch path from zero,
- every model cache state from zero.

### 2. The exact "minimum dependency set" is not fully frozen

The scripts clearly express some assumptions, but the smallest reproducible env
spec for a brand-new machine is still not written as a single lockstep install
recipe.

### 3. Rust-native parity is intentionally deferred

If someone wants to rebuild the Rust core first, that is a separate engineering
task, not the fastest path to reproducing the verified Chinese demo.

## Recommended teammate workflow

If another teammate takes over:

1. Read this file first.
2. Read `docs/HEADROOM_ZH_STATUS_2026-06-20.md` second.
3. Run Level 0 and Level 1 checks before touching the live Codex path.
4. Only after smoke is stable, move to `start_autodl_codex_gpt54_demo.sh`.
5. Record any new environment-specific fixes in a dated note instead of
   silently editing the story in multiple places.

## Suggested next doc improvement

The next useful documentation task is a separate:

- "blank AutoDL machine bootstrap checklist"

only after someone really walks that path again from a colder environment and
confirms each install step live.
