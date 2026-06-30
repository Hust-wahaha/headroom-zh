# Headroom 502 调试日志总结

## 背景

2026-06-22，在 Windows 11 环境下使用 Claude Code v2.1.178 与 headroom-ai 0.26.0 时，多个项目中出现 `502 status code (no body)`。错误提示要求检查本地 inference gateway：`127.0.0.1:8787`。

## 问题链路

### 1. `kompress_zh` 被绑定到本地 Headroom 代理

`kompress_zh/.claude/settings.json` 中存在：

- `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`
- Headroom 的 `SessionStart` / `PreToolUse` hooks
- 启用的 `headroom@headroom-marketplace` 插件

这导致 VSCode 扩展的请求被硬绑到本地 Headroom 代理。代理不在线时，请求必然失败并报 502。

### 2. 其他项目不受影响的原因

`lora-finetune-qwen` 没有 `.claude/settings.json`，因此 VSCode 扩展直连 Anthropic，不经过 Headroom 代理。

### 3. 关闭其他项目的 Headroom 终端会影响 `kompress_zh`

两个项目共用 `127.0.0.1:8787` 这一全局本地代理端口。若 `lora-finetune-qwen` 中启动的 `headroom wrap claude` 终端关闭，代理进程随之退出，`kompress_zh` 中被硬绑到代理的请求也会失败。

### 4. 配置来源

用户并未手动在 `kompress_zh` 中运行 `headroom wrap claude`。配置很可能由 VSCode 的 Headroom marketplace 插件自动写入。

## 已完成的修复

对 `kompress_zh/.claude/settings.json` 做了清理：

- 移除 `env`
- 移除 Headroom hooks
- 关闭 `headroom@headroom-marketplace`
- 只保留必要 permissions

修复后，VSCode 扩展恢复直连 Anthropic，不再依赖本地 Headroom 代理。

## `headroom_zh_eval` 中继续排查的结果

### 1. 首次失败：Torch `c10.dll` 初始化错误

`headroom wrap claude` 能启动代理，但请求仍 502。日志显示：

```text
WARNING - Eager preload failed for ContentRouter: [WinError 1114]
DLL 初始化失败 — c10.dll
```

原因是 headroom-ai 使用 Anaconda Python 3.12.4 安装，触发了 Windows 上 torch `c10.dll` 初始化冲突。

处理方式：

```powershell
uv tool uninstall headroom-ai
uv tool install "headroom-ai[all]" `
  --python "C:\Users\yanyi\AppData\Roaming\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" `
  --reinstall
```

随后验证 torch 可正常导入：

```text
OK 2.12.1+cpu
```

### 2. 第二次失败：缺少 `fastapi`

如果只安装 `headroom-ai` 而不带 extra，会缺少代理依赖并报：

```text
Proxy dependencies not installed
No module named 'fastapi'
```

改用 `headroom-ai[all]` 后解决。

### 3. 代理健康，但 Claude Code CLI 仍 502

代理启动后：

- `/health` 正常
- `/readyz` 正常
- 手动 POST 到 `/v1/messages` 能立即转发到 Anthropic，并返回 `401 invalid x-api-key`
- `/stats` 能看到 API 请求计数

但 Claude Code CLI 发送消息时：

- 等待约 3 分钟
- 最终 502
- `proxy.log` 中没有 Claude Code CLI 的 POST 请求记录

## 关键差异

| 维度 | 手动测试请求 | Claude Code CLI 请求 |
|---|---|---|
| 认证方式 | `x-api-key` | Claude Pro OAuth token |
| 响应模式 | 非流式 | SSE 流式 |
| 代理日志 | 有 POST 记录 | 无 POST 记录 |
| 结果 | 立即返回 401 | 约 3 分钟后 502 |

## 最终结论

Headroom 在当前 Windows 环境下不兼容 Claude Code CLI 的 Claude Pro OAuth + SSE 流式请求。

具体表现：

- API key 形式的普通请求可以通过 Headroom 代理转发
- Claude Pro OAuth 流式请求无法正常通过 Headroom 代理
- 请求不进入 `proxy.log`
- 最终由 Claude Code CLI 超时并报 502

这是 Headroom 上游在 Windows 平台上的兼容性问题，已整理信息提交 GitHub Q&A issue。

## DeepSeek 方案的额外结论

尝试设置：

```powershell
$env:ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN="<DeepSeek API Key>"
```

再运行 `headroom wrap claude` 后仍然 502。

原因是 Headroom 当前会把上游硬编码为 `api.anthropic.com`，不读取外部设置的 `ANTHROPIC_BASE_URL`。因此实际链路变成：

```text
Claude Code -> headroom:8787 -> api.anthropic.com
```

DeepSeek API Key 被发送到 Anthropic，自然无法认证。

## 可用性判断

| 使用方式 | 状态 | 说明 |
|---|---|---|
| VSCode 扩展直连 Anthropic | 可用 | 不经过 Headroom |
| MCP 工具 compress/retrieve/stats | 可用 | 只需单独运行 `headroom proxy` |
| `headroom wrap claude` + Claude Pro OAuth | 不可用 | Windows 上 SSE/OAuth 代理失败 |
| `headroom wrap claude` + DeepSeek API | 不可用 | Headroom 上游硬编码到 Anthropic |
| Anthropic 官方 API Key | 理论可用 | 需使用 `ANTHROPIC_API_KEY`，按量计费 |

## 建议

当前最稳妥方案是放弃 `headroom wrap claude`：

```powershell
uv tool uninstall headroom-ai
```

推荐使用双线方案：

- VSCode 插件继续走 Claude Pro / Anthropic 直连
- 终端需要 DeepSeek 时单独配置 DeepSeek API
- 若只需要 Headroom MCP 压缩工具，可单独运行 `headroom proxy`，不要用 `headroom wrap claude`

