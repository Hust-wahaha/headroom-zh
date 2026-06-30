# headroom-zh 跟进上游更新后的探索与修复记录（Windows / 弱 GPU）

> 分支：`headroom-zh-upstream-main-clean-2026-06-29`（跟进上游 + 重建 kompress_zh lane + CCR 缓存修复）
> 环境：Windows 11 + RTX 4060 Laptop 8GB；链路 codex(Responses API) ↔ headroom proxy(127.0.0.1:8787) ↔ yunwu.ai
> 时间：2026-06-29 ～ 06-30
> 起点：跟进上游后，实测中文/代码/JSON 实时压缩 token 节省偏低；proxy 启动报 `Code-Aware: DISABLED`、`Kompress: not installed`、`SmartCrusher 预加载报错`。
> 关联：[`实时压缩失效_假设排查方案.md`](./实时压缩失效_假设排查方案.md)（同源问题：预编译 `_core.pyd` 与分支 Python 不同步）。
>
> 本文合并自原 `压缩车道缺失排查_CodeAware与SmartCrusher.md` 与 `main_vs_upstream_压缩车道对照_20260630.md`。

---

## 0. 修复总览

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | SmartCrusher 启动崩溃 | 旧 `_core.pyd` 的 Rust `SmartCrusherConfig` 缺 `lossless_only` 等 6 字段 | shim 降级重试 · commit `5cf6edff` |
| 2 | `Kompress: not installed` 误报 | SmartCrusher 崩溃连带使整个 eager_load 抛出、状态清空 | 随 #1 修复 |
| 3 | `Code-Aware: DISABLED` | `enable_code_aware=False`（默认关）+ `prefer_code_aware_for_code=False`（硬编码，无 env） | env 开启 + 记录已知限制 |
| 4 | kompress_zh 中文车道失效（fallback 英文模型） | 启动不预热 + `_try_kompress_zh` 用 `allow_download=False` 命中冷启动 gate | 启动预热 · commit `198c24ff` |
| 5 | 长文被截断丢锚点 | `max_new_tokens` 固定值，把任意长度都压成定长 | 按输入动态预算 · commit `b4388e68` |
| 6 | 弱 GPU 超时被 fail-open 放行不压 | cap=1024 时单元生成 ~61s，多单元请求 >120s | cap/timeout 标定（command.txt） |

**两条根因主线：**
- **预编译 `_core.pyd` 与上游分支不同步** → #1 SmartCrusher 崩溃 + Windows `detect_content_type` 卡死（同源；后者已用 `HEADROOM_DETECT_BACKEND=python` 规避）。
- **kompress_zh 集成的冷启动 gate + 固定预算** → #4 中文车道根本没用上专用模型、#5 截断。

---

## 1. SmartCrusher 崩溃（旧 `_core.pyd` 缺字段）

**现象**：`SmartCrusherConfig.__new__() got an unexpected keyword argument 'lossless_only'`（启动 eager 预加载 + 运行时 smart_crusher/tabular 压缩各触发）。

**链路**：`SmartCrusher.__init__` → `_build_rust()` 把 Python 配置字段逐一拷进 `headroom._core.SmartCrusherConfig`（PyO3 构造）。本机预编译 `_core.pyd`（2026-06-22 放入、15.6MB、旧构建）的 Rust 配置没有 `lossless_only`。

**实锤复现**：
```python
from headroom._core import SmartCrusherConfig as R
R(lossless_only=False)   # → unexpected keyword argument 'lossless_only'
```
无条件触发（默认 `lossless_only=False` 也会被拷进），所以每次起 proxy 必崩。

**修复（commit `5cf6edff`，三选一采用 ③ shim）**：`smart_crusher.py` 顶部加 `import re`；`_build_rust` 构造改为 while 循环，捕获 `TypeError: unexpected keyword argument 'X'` → 删 X 重试 → `logger.warning` 说明降级。
- 旧 `_core.pyd` 实际缺 **6 个字段**：`lossless_only`、`compaction_core_field_fraction`、`compaction_heterogeneous_core_ratio`、`compaction_max_flatten_inner_keys`、`compaction_min_buckets`、`compaction_max_buckets`——全被降级兜住。
- SmartCrusher 不再崩；JSON 压缩恢复 **3390→1295 字节（省 62%）**。
- 连带：eager_load 不再崩 → Kompress 不再被误报 "not installed"（#2 随之解决）。
- proxy 实跑确认：日志 `dropping 'lossless_only' ... using Rust default` warning 但无崩溃。

> 根治仍是让 `_core.pyd` 与分支同步（换/重编二进制）；shim 是降级（缺字段用 Rust 旧默认）。

---

## 2. 三条车道实测状态（Code-Aware / 英文 Kompress / JSON）

依赖均无缺失（torch 2.11+cu128、transformers 5.6.2、peft 0.19.1、swift 4.1.3、onnxruntime 1.27、tree_sitter parser 全 OK）。直接对三类内容喂 `ContentRouter.compress()` 实测：

| 车道 | 检测 | 实际路由 | 结果 |
|---|---|---|---|
| **JSON 数组 → SmartCrusher** | json_array | SMART_CRUSHER | ✅ **省 45.6%**（shim 后生效） |
| **英文文本 → Kompress(ONNX)** | plain_text | KOMPRESS | ✅ proxy 内生效（冷启动后台加载，启动已预热） |
| **代码段 → Code-Aware** | source_code | **KOMPRESS（降级）** | ❌ **纯代码收不到** |

**代码车道关键坑**（[content_router.py:655/665/1355](../headroom-zh/headroom/transforms/content_router.py)）：
```python
enable_code_aware = False            # HEADROOM_CODE_AWARE_ENABLED=1 只开这个
prefer_code_aware_for_code = False   # 硬编码、无 env；导致 source_code 在路由阶段降级到 KOMPRESS
```
`HEADROOM_CODE_AWARE_ENABLED=1` 只让 Code-Aware 被实例化（横幅 ENABLED），但 `prefer_code_aware_for_code=False` 使纯代码一律降级到英文 Kompress（上游有意"let code pass through unmangled"）。只有 mixed 文档里被切出的代码段才会真正走 Code-Aware。

> 英文 Kompress / kompress_zh 都是冷启动机制（`is_ready()` 前 noop + 后台加载），独立短命脚本里会 noop（伪影），proxy 内启动预热后正常。

---

## 3. kompress_zh 中文车道失效（fallback 英文模型）

**对照实验**（同一 C3.md，proxy 实跑，`strategy_chain` 为铁证）：

```
main:            text  1716->209   chain=['text']                       ← kompress_zh 直接成功
upstream(修复前): kompress_zh 1716->900  chain=['kompress_zh','kompress'] ← fallback 到英文!
```
预热日志 `kompress_zh pre-loaded at startup` 仅 main 会话有；upstream-clean 启动无此行。

**根因链**：
- main：启动预热 → 引擎进 `_engine_cache`；`compress(content, **_)` 无 gate → 中文真用 kompress_zh。
- upstream-clean：**不预热** → 缓存空；`_try_kompress_zh` 硬编码 `allow_download=False` → 命中 `compress` 的 gate（`kompress_zh_compressor.py:211`：`if not allow_download and not _has_cached_engine: return _passthrough()`）→ 吐原文 → content_router 见没压动 → fallback 到 `_try_ml_compressor`（英文 ModernBERT）→ 中文被英文模型抽取式压（成比例 ~50%）。

> 佐证：独立脚本用 `allow_download=True` 绕过 gate 时，upstream-clean 的 kompress_zh 能压到 1698→135（纯模型正常）。proxy 内走 `False` 才触发 fallback。

**修复（commit `198c24ff`，方案 A 启动预热）**：在 `eager_load_compressors` 中对齐 main——`_get_engine(zh.config)` 启动时 build+cache 引擎。
- 修复后实测：C3 `1716->238`、demo_bundle `5884->245`，`chain=['kompress_zh']`，预热日志出现。**中文终于真正走 kompress_zh，不再 fallback。**

| 文件 | main | upstream 修复前 | upstream 修复后 |
|---|---|---|---|
| C3.md | 1716→209 `['text']` | 1716→900 `['kompress_zh','kompress']` | 1716→238 `['kompress_zh']` ✓ |
| demo_bundle | 5884→212 | 5884→2750 (英文 fallback) | 5884→245 `['kompress_zh']` ✓ |

---

## 4. max_new_tokens 截断与动态预算

修复 #3 后发现"不同长度文档都压成 ~240 token 定长"，疑似截断。`finish_reason` 扫描（铁证）：

| 文件 | max_new_tokens | 输出 | finish_reason |
|---|---|---|---|
| C3 (1698) | 192 / 384 / 768 | 194 / 394 / 803 | **length（截断）** |
| | 1280 | **993** | **stop（自然结束）** |
| demo (5798) | 192 / 384 / 768 | 207 / 400 / 830 | **length（截断）** |
| | 1280 | **1340** | **stop（自然结束）** |

**结论**：默认 192 严重截断（C3 完整摘要要 993、demo 要 1340，192 只给 15~20%，锚点几乎必丢）。"定长"是截断假象；放开后输出随输入增长。**此前所有"高压缩率（88~96%）"都是截断换的假高**，自然结束的真实保真压缩率是 C3 41% / demo 77%。

**修复（commit `b4388e68`，动态预算）**：`kompress_zh_compressor.compress`
```python
ratio = _env_float("HEADROOM_KOMPRESS_ZH_RATIO", 0.4)
cap   = _env_int("HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS", 1024)  # 语义从“固定值”改为“封顶”
max_new = min(max(int(units * ratio), 64), cap)                # units = 去空格字符数
```

---

## 5. 弱 GPU cap/timeout 标定（RTX 4060 Laptop, ~17 tok/s）

**生成耗时 ≈ max_new_tokens / 17：** 192→15s · 384→20s · 768→40s · 1024→60s · 1280→75s。
**单请求可容纳单元数 ≈ 超时 / 单元耗时。** 三方权衡（实测）：

| 组合 | 结果 |
|---|---|
| 固定 192 | 快但截断丢锚点（假高） |
| cap 1024 + timeout **120** | 单元 61s，多单元请求 >120s → `TimeoutError` → fail-open 放行**不压** → saved 暴跌 **0.2%** |
| cap 512 + timeout 120 | ~30s/单元，2~3 单元可压完；长文截断到 512（保留 > 192） |
| **cap 1024 + timeout 240（本机默认）** | 单元 44~62s，240s 容纳 3~4 单元；C3+demo 全部压成、无 `TimeoutError`、`chain=['kompress_zh']`、整体 **13.8%** |

**根本矛盾**：弱 GPU 上「完整保真（大 cap）」与「不超时（快）」不可兼得，需按 GPU 速度配平 cap 与 timeout。

**本机最终默认（command.txt）：**
```
HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS = 1024   # 动态预算封顶
HEADROOM_KOMPRESS_ZH_RATIO          = 0.4
HEADROOM_COMPRESSION_TIMEOUT_SECONDS = 240
HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE = 1
HEADROOM_DETECT_BACKEND = python             # 规避 _core detect 卡死
HEADROOM_CODE_AWARE_ENABLED = 1
```
换强 GPU（如 4090）可保持 cap=1024 并把 timeout 调回 120，长文也能完整自然结束。

---

## 6. 依赖加固（`eval/requirements-windows.txt`）

依赖本不缺，但 `[code]` 段原只写 `tree-sitter-language-pack>=0.10.0`（无上限、缺基包），有被传递依赖拉到不兼容 1.x 的风险。已加固：
```
tree-sitter-language-pack>=0.10.0,<1.0   # 1.x 是破坏性重写，get_parser 返回非标准类型会让 code_compressor 静默失效
tree-sitter>=0.25.2,<0.26                # 显式基包并 pin
```
其余 [ml]/[proxy]/[memory] 等段见实际文件。

---

## 7. commit 索引 + 遗留

**本次 commit（`headroom-zh-upstream-main-clean-2026-06-29`，本地领先 origin）：**

| commit | 修复 |
|---|---|
| `5cf6edff` | SmartCrusher 旧 `_core.pyd` 缺字段降级重试 |
| `198c24ff` | 启动预热 kompress_zh，修复中文车道 fallback 到英文 |
| `b4388e68` | max_new_tokens 按输入动态计算，避免截断丢锚点 |

**遗留 / 建议：**
1. 把 SmartCrusher `lossless_only` 与 detect 卡死一并归因到"预编译 `_core.pyd` 与上游不同步"，报上游；最优解是提供与分支匹配的 Windows `_core` 预编译件。
2. Code-Aware 对纯代码不生效是上游有意默认（`prefer_code_aware_for_code=False`），如需压代码要改此项。
3. 用 manifest C3 原题实测 kompress_zh 摘要的**问答保真**（~1100 token 摘要够不够答对锚点），从"token 数好看"验证到"答案正确"。
4. rtk Context Tool 在 codex 下报错并抬高 dashboard 分母——已处理（见 §9）。

---

## 8. 方法备注

- proxy.log：`C:\Users\yanyi\.headroom\logs\proxy.log`（开 `HEADROOM_CODEX_WIRE_DEBUG` 时会快速轮转到 `.1/.2`）。
- 关键字段：`slow compression unit` 行的 `strategy` / `strategy_chain` / `tokens_before/after` / `elapsed_ms`。
- **`strategy_chain` 是判定"实际走了哪个压缩器、有没有 fallback"的唯一可靠依据**；`finish_reason`（底层 infer）是判定"截断 vs 自然结束"的唯一可靠依据。

---

## 9. rtk Context Tool 在 codex 下抬高分母（已处理）

**现象**：codex 读文件时执行 `rtk read <file>` 报 `无法将"rtk"项识别为 cmdlet...`（command not found）。

**来源**：`headroom wrap codex` 曾自动注入 `AGENTS.md`（两处：`~/.codex/AGENTS.md` 全局 + `headroom-zh/AGENTS.md` 项目），内含 `<!-- headroom:rtk-instructions -->` 段，要求 codex"所有 shell 命令前缀 `rtk`"。但 rtk.exe 未在 codex 的 PowerShell PATH——rtk 的自动集成 `register_claude_hooks` 只服务 **Claude Code**（改 `~/.claude/settings.json` 的 PreToolUse hook），codex 这种非 MCP 流式客户端拿到指令却找不到命令。

**对分母的影响**：codex 每条命令先试 `rtk ...` → 失败 → fallback 正常命令 = **多一个请求往返**，每往返重发完整 system prompt + 工具 schema（~12k 不可压外壳）→ 抬高分母、拉低节省率%；且 dashboard `RTK 0`（rtk 本该压 CLI 输出）。中文文档内容本身仍正常走 kompress_zh，不受影响。

**处理（禁用注入）**：删除两处 `AGENTS.md`（备份 `.bak-rtk-20260630`）。codex 不再 prefix rtk → 直接正常命令 → 消除失败往返。
- `~/.codex/config.toml` 的 provider/MCP 配置**保留**（codex 走 proxy 的必要配置；MCP `headroom_retrieve` 是 CCR 检索工具，codex 支持 MCP、不报错，无需动）。
- 若以后想用 rtk 省 CLI 输出：`ensure_rtk()` 下载 rtk.exe 到 `~/.headroom/bin` 并把该目录加入 codex 终端 PATH；但对中文文档评测场景收益有限。
- ⚠️ 重新跑 `headroom wrap codex` 会再次注入 AGENTS.md rtk 段——本机流程用「proxy 单独起 + 普通 codex」，不要 wrap（command.txt 已注明）。
