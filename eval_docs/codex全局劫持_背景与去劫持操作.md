# Codex 全局被 Headroom 劫持 · 背景与「去流量劫持」操作手册

> 用途：记录 headroom 对**全局** `~/.codex` / `~/.claude` 的注入现状，以及**只去除 codex 流量劫持**的精确操作。
> 日后需要执行时，直接把本文件指给助手：「按 `eval_docs/codex全局劫持_背景与去劫持操作.md` 去掉 codex 流量劫持」。
> **当前状态：尚未执行清理（仅记录）。** 排查日期 2026-06-28。

---

## 0. 一句话背景

`headroom wrap codex` / `headroom install` 把自己写进了**全局** `~/.codex/config.toml`，其中
`model_provider = "headroom"` 是**顶层全局**设置 → **任何目录**下启动 codex 都会被路由到本地 proxy
`http://127.0.0.1:8787/v1`。后果：**proxy 没开时，全局 codex 发消息直接连不上 8787**。
`codex /status` 显示 `Model provider: OpenAI via Headroom proxy` 就是这个注入的结果。

---

## 1. 现状全清单（排查结果）

### 1.1 `~/.codex/config.toml`（重度，含流量劫持）

对比 `~/.codex/config.toml.headroom-backup`（headroom 改之前：`model=gpt-5.2-codex`、**无** provider）：

| 注入项 | 位置 | 作用 | 是否流量劫持 |
|---|---|---|---|
| `model_provider = "headroom"` + `openai_base_url="http://127.0.0.1:8787/v1"` | 顶部「Headroom proxy」块 | ★ 全局把 codex 路由到 proxy | **是** |
| `[model_providers.headroom]`（name/base_url/supports_websockets/env_key/env_http_headers）| 底部「Headroom proxy」块 | proxy provider 定义 | 是（配套）|
| `[mcp_servers.headroom]`（command=headroom，args=["mcp","serve"]）| 中部 | 每次 codex 启动 spawn headroom MCP | 否 |
| `[mcp_servers.serena]` | 底部 | 每次启动 spawn serena MCP | 否 |
| `~/.codex/AGENTS.md`（`<!-- headroom:rtk-instructions -->` RTK 指令）| 独立文件 | 全局 codex 都被注入「命令前缀 rtk」指令 | 否 |
| `model = "gpt-5.4"` | 顶部 | 我们调试时改的（备份原值 gpt-5.2-codex）| 否 |

### 1.2 `~/.claude`（轻度，**无流量劫持**）

- `~/.claude/settings.json`：`extraKnownMarketplaces.headroom-marketplace`（github `chopratejas/headroom` 插件源）
- `~/.claude.json`：顶层 `mcpServers` 里有 `headroom` + `serena`（每次 Claude Code 启动都 spawn）；`pluginUsage` 里 `headroom@headroom-marketplace` 已启用
- ✅ **没有 `ANTHROPIC_BASE_URL`** → **Claude Code 流量未被劫持**，只是会全局起 headroom/serena 进程
- 注：`settings.json` 里的 `HTTP_PROXY/HTTPS_PROXY=127.0.0.1:7890` 是用户自己的科学上网代理，**与 headroom 无关，勿动**。

### 1.3 影响评估

- **codex = 严重**：全局被劫持，proxy 没开就发不出消息。
- **claude = 轻**：流量正常，仅多 spawn headroom/serena MCP 进程 + 装了插件。

---

## 2. 「只去 codex 流量劫持」操作（日后执行）

目标：让**全局 codex 恢复默认**（不再强制走 proxy），但**保留**本项目按需使用 headroom 的能力；
MCP / AGENTS.md / claude 的注入**本次不动**（可日后单独清）。

### 2.1 备份

```powershell
Copy-Item "C:\Users\yanyi\.codex\config.toml" "C:\Users\yanyi\.codex\config.toml.bak-dehijack"
```

### 2.2 从 `~/.codex/config.toml` 删除这两段（**仅这两段**）

**A. 顶部块（去掉全局 provider 切换）：**
```toml
# --- Headroom proxy (auto-injected by headroom wrap codex) ---
model_provider = "headroom"
openai_base_url = "http://127.0.0.1:8787/v1"
# --- end Headroom ---
```

**B. 底部块（去掉 provider 定义）：**
```toml
# --- Headroom proxy (auto-injected by headroom wrap codex) ---
[model_providers.headroom]
name = "OpenAI via Headroom proxy"
base_url = "http://127.0.0.1:8787/v1"
supports_websockets = false
env_key = "OPENAI_API_KEY"
env_http_headers = { "X-Headroom-Project" = "HEADROOM_PROJECT" }
# --- end Headroom ---
```

> 保留：`model`、`model_reasoning_effort`、`personality`、`[mcp_servers.*]`、`[projects.*]`、`[tui.*]` 全部不动。
> （`headroom unwrap` 理论上也能撤销，但它可能同时动 MCP；手删这两段最精准可控，故首选手删。）

### 2.3 恢复全局 codex 正常登录

调试期间执行过 `codex logout`（切 API key 模式）。去劫持后若要让全局 codex 正常用，二选一：
- 用回 ChatGPT 订阅：`codex login`
- 或继续用 API key：保留系统用户环境变量 `OPENAI_API_KEY`（codex 默认 openai provider 会读；上游为 api.openai.com，**注意 yunwu key 在官方 openai 会被拒**——若仍想用 yunwu，见下一节项目内用法）

### 2.4 验证

```powershell
# 任意非本项目目录下：
codex
# 进去后 /status 应显示 Model provider 为默认（OpenAI，而非 "OpenAI via Headroom proxy"）
```

---

## 3. 去劫持后，本项目仍要用 headroom 的方法

去掉全局 `model_provider` 后，本项目用 headroom 需在**启动时临时指定 provider**（而非依赖全局）。
两种方式（届时同步更新 `command.txt`（本地命令备忘，未随仓库分发））：

- **命令行临时指定**（推荐，最干净）：
  ```powershell
  # 终端 A 照常起 proxy（含 HEADROOM_RUST_DETECT=0 等，见 command.txt）
  # 终端 B：
  codex -c model_provider=headroom -c 'model_providers.headroom.base_url="http://127.0.0.1:8787/v1"' -c 'model_providers.headroom.env_key="OPENAI_API_KEY"' -c 'model_providers.headroom.supports_websockets=false'
  ```
- 或保留一个**项目内** codex 配置/profile，仅本项目生效（codex 支持 `--profile`）。

> 关键：去劫持只是把「全局默认」改回原样；headroom 这条路本身（proxy + RUST_DETECT=0 修复 + API 路由配置）依然可用，只是改为**按需显式开启**。

---

## 4. 回滚（撤销本次去劫持）

```powershell
Copy-Item "C:\Users\yanyi\.codex\config.toml.bak-dehijack" "C:\Users\yanyi\.codex\config.toml" -Force
```

---

## 5. 关联文档

- 实时压缩根因与修复：[`实时压缩失效_假设排查方案.md`](./实时压缩失效_假设排查方案.md)（终极根因 = Rust `_core.pyd` 内容检测卡死，修复 `HEADROOM_RUST_DETECT=0`）
- 启动/配置链：`command.txt`（本地命令备忘，未随仓库分发）
- 备份基线：`~/.codex/config.toml.headroom-backup`（headroom 改前）、`~/.codex/config.toml.bak-dehijack`（本操作前，执行时生成）

## 6. 待办（本次仅记录，未执行）

- [ ] 执行 §2「只去 codex 流量劫持」
- [ ] （可选）清 codex 的 headroom MCP + AGENTS.md（§1.1 中未劫持项）
- [ ] （可选）清 claude 的 headroom MCP + 插件源（§1.2）
- [ ] 子模块 headroom-zh 提交我们的修复（helpers.py / content_router.py），避免 HEAD 重置丢失
