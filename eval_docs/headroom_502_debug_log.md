# Headroom 502 错误排查全记录

**日期**：2026-06-22  
**环境**：Windows 11 (10.0.26200)，RTX 4060 Laptop，Claude Code v2.1.178，headroom-ai 0.26.0

---

## 一、问题发现

在 `kompress_zh` 项目下通过 VSCode 扩展对话时，发送消息后出现：

```
API Error: 502 status code (no body). This is a server-side issue, usually temporary —
try again in a moment. If it persists, check your inference gateway (127.0.0.1:8787).
```

重试多次（attempt 7/10、10/10）均失败，持续约 3 分钟后放弃。

---

## 二、初步定位

### 2.1 为什么提示 127.0.0.1:8787？

查看 `kompress_zh/.claude/settings.json`，发现其中配置了：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"
  },
  "hooks": {
    "SessionStart": [{ "type": "command", "command": "headroom.EXE init hook ensure ..." }],
    "PreToolUse":   [{ "type": "command", "command": "headroom.EXE init hook ensure ..." }]
  },
  "enabledPlugins": { "headroom@headroom-marketplace": true }
}
```

**结论**：VSCode 扩展读取此配置，将所有 API 请求硬绑到本地代理 `http://127.0.0.1:8787`。代理不在线时请求必然失败。

### 2.2 为什么 lora-finetune-qwen 项目不受影响？

`lora-finetune-qwen` 项目没有 `.claude/settings.json`，VSCode 扩展直连 Anthropic，不经过任何代理。

### 2.3 为什么关闭 lora-finetune-qwen 的 headroom 终端会导致 kompress_zh 502？

两个项目共用同一个代理进程（端口 8787 全局唯一）。在 `lora-finetune-qwen` 下开启的 `headroom wrap claude` 终端关闭后，代理进程死亡，`kompress_zh` 的硬绑随即断联。

### 2.4 kompress_zh 的配置是怎么写进去的？

用户从未手动在 `kompress_zh` 下运行 `headroom wrap claude`。原因是 VSCode 扩展的 **Headroom marketplace 插件**在被启用时，自动向当前项目的 `settings.json` 写入了 hooks 和 `ANTHROPIC_BASE_URL`。

---

## 三、修复 kompress_zh 的自动触发问题

将 `kompress_zh/.claude/settings.json` 改为只保留 permissions，去掉 `env` 和 `hooks`：

```json
{
  "permissions": { "allow": [ ... ] },
  "enabledPlugins": { "headroom@headroom-marketplace": false }
}
```

**效果**：VSCode 扩展直连 Anthropic，不再依赖本地代理，关闭任何 headroom 终端都不影响该项目对话。

---

## 四、尝试在 headroom_zh_eval 下使用 headroom wrap claude

### 4.1 首次启动失败：ContentRouter c10.dll 错误

`headroom wrap claude` 能启动代理，但发送消息后仍 502。查看代理日志：

```
WARNING - Eager preload failed for ContentRouter: [WinError 1114]
DLL 初始化失败 — c10.dll
Error loading ".../headroom-ai/Lib/site-packages/torch/lib/c10.dll"
```

**原因**：headroom-ai 使用 Anaconda Python 3.12.4 作为 base 安装，Anaconda 的 c10.dll 在 Windows 上存在 DLL 初始化冲突（与本项目 CLAUDE.md 记录的主线 torch 坑完全相同）。

验证：
```powershell
& "C:\Users\yanyi\AppData\Roaming\uv\tools\headroom-ai\Scripts\python.exe" `
  -c "import torch; print(torch.__version__)"
# → OSError: [WinError 1114] ... c10.dll
```

### 4.2 重装 headroom-ai（指定 uv 独立 CPython）

```powershell
uv tool uninstall headroom-ai   # 需先关闭 headroom 进程，否则报"拒绝访问"
uv tool install "headroom-ai[all]" `
  --python "C:\Users\yanyi\AppData\Roaming\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" `
  --reinstall
```

验证 torch 恢复正常：
```powershell
& "C:\Users\yanyi\AppData\Roaming\uv\tools\headroom-ai\Scripts\python.exe" `
  -c "import torch; print('OK', torch.__version__)"
# → OK 2.12.1+cpu
```

### 4.3 重装后新问题：Proxy exited with code 1，缺少 fastapi

```
Error: Proxy dependencies not installed. Run: pip install headroom-ai[proxy]
Details: No module named 'fastapi'
```

**原因**：最初重装时只用了 `headroom-ai`（无 extra），未包含代理所需的 fastapi 等依赖。改用 `headroom-ai[all]` 解决。

### 4.4 代理启动成功，但 Claude Code CLI 请求仍 502（3 分钟超时）

代理正常启动，`/health` 和 `/readyz` 均返回 200。但发送消息后每次等待约 3 分钟后报：

```
502 status code (no body) · Retrying in 24s · attempt 10/10
```

---

## 五、深入排查：代理日志无 POST 记录

整个 3 分钟超时过程中，`proxy.log` 里**完全没有** Claude Code CLI 的 POST 请求记录，只有浏览器（Edge）的 `/health` 和 `/stats` 心跳。

### 5.1 验证代理转发能力

手动向代理发送 POST 请求：

```powershell
$body = '{"model":"claude-haiku-4-5-20251001","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
Invoke-WebRequest -Uri "http://127.0.0.1:8787/v1/messages" -Method POST `
  -Body $body -ContentType "application/json" -Headers @{"x-api-key"="dummy"} -UseBasicParsing
```

结果：立即收到 Anthropic 返回的 `401 authentication_error: invalid x-api-key`，`stats` 端点显示 `api_requests: 1, providers: anthropic`。

**结论**：代理本身可以正常转发请求到 Anthropic，问题不在代理的基本转发逻辑。

### 5.2 与 Claude Code CLI 请求的关键差异

| 维度 | 手动测试请求（成功） | Claude Code CLI 请求（失败） |
|------|---------------------|------------------------------|
| 认证方式 | `x-api-key` | OAuth token（Claude Pro 订阅） |
| 响应模式 | 非流式 | SSE 流式 |
| 日志记录 | 有 POST 记录 | 无任何记录 |
| 结果 | 立即返回 401 | 3 分钟超时后 502 |

---

## 六、最终结论

### 根本原因

**Headroom 代理在 Windows 上不兼容 Claude Code CLI 的 OAuth 流式请求。**

具体表现为：Claude Code CLI 通过 Claude Pro 订阅（OAuth token）发出的 SSE 流式请求，在经过 Headroom 代理时既不出现在日志中，也得不到响应，最终超时 502。而使用 `x-api-key` 的非流式测试请求可以正常转发。

这是上游 Headroom 在 Windows 平台的兼容性问题，已向官方提交 Q&A issue。

### 各部署方式的可用性

| 方式 | 状态 | 说明 |
|------|------|------|
| VSCode 扩展直连 Anthropic | ✅ 正常 | 不经过代理，完全可用 |
| MCP 工具（compress/retrieve/stats） | ✅ 可用 | 需代理进程运行（`headroom proxy`），但不需要 `wrap claude` |
| `headroom wrap claude` 代理模式 | ❌ Windows 不可用 | OAuth 流式请求无法通过代理 |

### 若需使用 MCP 压缩功能

单独启动代理（不包裹 Claude）：

```powershell
headroom proxy
```

代理运行期间，VSCode 扩展内的 `mcp__headroom__headroom_compress` / `headroom_retrieve` / `headroom_stats` 工具可正常使用，对话本身仍直连 Anthropic，不受代理影响。

---

## 七、已提交的 GitHub Issue（Q&A）

**Title**: Claude Code CLI (OAuth/Claude Pro) requests timeout with 502 (no body) — but API-key requests forward correctly

**关键信息**：
- 代理可正常转发 API key 请求（401 立即返回）
- Claude Code CLI 的 OAuth 流式请求不出现在 proxy.log，3 分钟后 502
- 平台：Windows 11，headroom-ai 0.26.0，Claude Code v2.1.178

## 补充：
我通过uv tool install "headroom-ai[all]"重新安装了headroom（之前uninstall卸载了），之后新开一个终端，先配置deepseek api：
”$env:ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN="<你的 DeepSeek API Key>"
$env:ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_EFFORT_LEVEL="max"
“
接着headroom wrap claude，显示如图，api似乎能正常连接上Claude code，但是发送消息后还是报502错误

确认了：headroom 把上游硬编码成 api.anthropic.com，不读你设的 ANTHROPIC_BASE_URL。所以请求路径是：


Claude Code → headroom:8787 → api.anthropic.com（硬编码）
而 DeepSeek 的 Key 发到 Anthropic 服务器上当然认证失败，502。

结论就是 headroom 目前只支持两种场景：

Anthropic 官方 API Key（ANTHROPIC_API_KEY，按量计费）
❌ Claude Pro OAuth → 502（Windows SSE 兼容问题）
❌ DeepSeek API → 502（硬编码上游）
你的两条路都堵死了，建议彻底放弃 headroom，直接卸掉：


uv tool uninstall headroom-ai
VSCode 插件走 Claude Pro、终端单独配 DeepSeek API 的双线方案本身没问题，只是不经过 headroom 压缩而已