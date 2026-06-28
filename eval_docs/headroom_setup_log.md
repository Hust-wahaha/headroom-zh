# Headroom 安装与配置探索记录

> 记录日期：2026-06-22  
> 环境：Windows 11 家庭版，PowerShell，Claude Code VSCode 插件

---

## 一、背景

[headroom-ai](https://github.com/chopratejas/headroom) 是一个 token 压缩工具，通过拦截发往 LLM 的请求并压缩上下文来降低 token 消耗。本文记录在 Windows 环境下完整安装、配置、问题排查及最终成功使用的全过程。

---

## 二、初始状态检查

**操作：** 检查 headroom 是否已安装。

**发现：**  
headroom 已在 `C:\Users\<user>\.claude\.claude.json` 中以 MCP server 形式声明：

```json
"headroom": {
  "command": "headroom",
  "args": ["mcp", "serve"]
}
```

但实际可执行文件 **并未安装**，`where.exe headroom` 和 `pip show headroom` 均找不到。Claude Code 启动时静默失败，该 MCP server 形同虚设。

---

## 三、安装方式选择

**问题：** 官方文档建议 `pip install "headroom-ai[all]"`，是否需要新建 conda 环境？

**结论：** 不需要 conda 环境。headroom 是一个全局命令行工具，应使用 `uv tool install` 安装，效果等同 pipx：
- 创建隔离的专属环境
- 将 `headroom` 命令注册到全局 PATH
- 完全不影响任何项目的 `.venv`

---

## 四、安装过程与问题排查

### 4.1 首次安装尝试：终端闪退

**操作：**
```powershell
uv tool install "headroom-ai[all]"
```

**现象：** 安装进行到 torch（117MB）下载阶段时，终端直接闪退关闭。换到 Windows Terminal 也复现。

**诊断：** 将输出重定向到日志文件：
```powershell
uv tool install headroom-ai *> C:\Users\<user>\headroom_install.log
Get-Content C:\Users\<user>\headroom_install.log | Select-Object -Last 30
```

**日志关键内容：**
```
Building headroom-ai==0.25.0
...
Compiling memoffset v0.9.1
error: failed to run custom build command for `memoffset v0.9.1`
Caused by: 拒绝访问。 (os error 5)
```

**根本原因：** headroom-ai 是 Python + Rust 混合包，安装时需要本地编译 Rust 组件（通过 maturin）。编译生成的 `.exe` 文件被 **360安全卫士** 实时扫描拦截，导致 os error 5（拒绝访问）。

> 注：系统使用 360安全卫士，Microsoft Defender 已被其接管并关闭，因此需要在 360 而非 Defender 中操作。

### 4.2 解决：360安全卫士添加信任

**操作：**  
360安全卫士 → 设置 → 信任区 → 添加文件夹：
```
C:\Users\<user>\AppData\Local\uv
```

**再次安装：**
```powershell
uv tool install headroom-ai --reinstall
```

**结果：** 安装成功，输出 `Installed 1 executable: headroom`。

```powershell
uv tool list
# headroom-ai v0.25.0
#   - headroom

headroom --version
# headroom, version 0.25.0
```

### 4.3 附：项目 .venv 残留清理

安装过程中发现 headroom 的旧版本（0.23.0）存在于项目的 `.venv` 中（原因不明，可能之前手动 pip 安装过）。需清理以避免 PATH 优先级冲突：

```powershell
uv pip uninstall headroom-ai
```

---

## 五、配置调整：改为手动启动

**问题：** `.claude.json` 中的 MCP 配置会让 headroom 在 Claude Code 每次启动时自动以 `headroom mcp serve` 模式运行，用户希望改为手动通过 `headroom wrap` 控制启动。

**操作：** 手动编辑 `C:\Users\<user>\.claude\.claude.json`，删除 headroom MCP 条目，仅保留 serena：

```json
{
  "mcpServers": {
    "serena": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/oraios/serena",
        "serena", "start-mcp-server",
        "--project-from-cwd", "--context", "claude-code"
      ]
    }
  }
}
```

---

## 六、headroom wrap claude 的兼容性问题

### 6.1 Claude Pro OAuth → 502 错误

**操作：**
```powershell
headroom wrap claude
```

**现象：** Claude Code 启动，发送消息后报 `API Error: 502 status code (no body)`。

**根本原因分析：**
- Claude Code CLI（Claude Pro 订阅）使用 **OAuth 令牌**认证 + **SSE 流式响应**
- headroom 在 Windows 上处理 OAuth + SSE 的组合存在兼容性缺陷
- 这是 headroom 的已知 bug，与配置无关

### 6.2 尝试 DeepSeek API → 仍然 502

**操作：** 配置 DeepSeek API 环境变量后再启动：
```powershell
$env:ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN="<DeepSeek API Key>"
$env:ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
# ... 其他模型映射
headroom wrap claude
```

**现象：** Claude Code 正确识别了 DeepSeek 模型（`deepseek-v4-pro[1m]`），但发消息仍然 502。

**根本原因：** headroom proxy **硬编码**将请求转发到 `api.anthropic.com`，不读取 `ANTHROPIC_BASE_URL` 作为上游地址。请求路径为：

```
Claude Code → headroom:8787 → api.anthropic.com（硬编码）
```

DeepSeek Key 发往 Anthropic 服务器，认证失败，502。

**结论：** `headroom wrap claude` 在当前环境下（Windows + Claude Pro OAuth 或第三方 API）均无法使用。

---

## 七、headroom wrap codex 的使用

### 7.1 UnicodeDecodeError

**操作：** 配置 DeepSeek API 环境变量后运行：
```powershell
headroom wrap codex
```

**报错：**
```
UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 212
```

**根本原因：** headroom 读取 codex 配置文件 `C:\Users\<user>\.codex\config.toml` 时未指定编码，默认使用系统编码 GBK（中文 Windows）。但该文件为 UTF-8 编码，且包含中文路径（如 `f:\模式识别课设\...`），GBK 解码失败。

这是 headroom 在中文 Windows 上的已知 bug（`config_file.read_text()` 缺少 `encoding='utf-8'` 参数）。

### 7.2 解决方案

**操作：** 运行前设置 `PYTHONUTF8=1` 强制 Python 使用 UTF-8 作为默认编码：

```powershell
$env:PYTHONUTF8=1
headroom wrap codex
```

**结果：** 成功启动，对话与 token 压缩正常运行。

---

## 八、完整使用流程（最终方案）

```powershell
# 1. 配置 DeepSeek API（或其他兼容 Anthropic 格式的 API）
$env:ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN="<你的 API Key>"
$env:ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_EFFORT_LEVEL="max"

# 2. 修复中文 Windows 编码问题
$env:PYTHONUTF8=1

# 3. 启动（以 codex 为例）
headroom wrap codex
```

查看 token 节省情况：打开浏览器访问 `http://127.0.0.1:8787`。

---

## 九、关键结论汇总

| 场景 | 是否可用 | 备注 |
|------|---------|------|
| headroom wrap claude（Claude Pro OAuth） | ❌ | Windows + OAuth + SSE 兼容性 bug |
| headroom wrap claude（DeepSeek API） | ❌ | headroom 硬编码上游为 Anthropic |
| headroom wrap codex（DeepSeek API） | ✅ | 需加 `$env:PYTHONUTF8=1` |
| VSCode Claude Code 插件 | ✅（不经 headroom） | 直连 Anthropic，不受影响 |

### 已知 Bug（中文 Windows 特有）

1. **360安全卫士阻断 Rust 编译**：安装时需将 `C:\Users\<user>\AppData\Local\uv` 加入 360 信任区
2. **headroom wrap codex GBK 编码错误**：运行前需设置 `$env:PYTHONUTF8=1`

---

## 十、附：.serena 文件夹说明

项目目录下自动生成的 `.serena/` 文件夹来自 **Serena MCP server**，是正常行为，用于存储项目级代码索引与记忆。已将其加入项目 `.gitignore`，无需手动删除。
