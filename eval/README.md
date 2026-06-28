# kompress_zh 中文压缩通道 · 准确率保持评测

本目录是 **headroom-zh fork 内置**的一套 **中文压缩通道 `kompress_zh` 的"准确率保持"评测**。
核心问题只有一个：

> **大幅压缩中文上下文的同时，任务准确率是否保持？**

上游已证明 kompress_zh "能省 token"，但缺这块关键证据。本 `eval/` 就是补这块：
用**真实的 kompress_zh** 压缩中文"工具输出"，再把【原文 / 压缩后】两种上下文发给同一上游 LLM，比较答案。

---

## 目录结构

本评测位于 fork 根目录下的 `eval/` 与 `eval_docs/`（均纳入版本控制）：

```
headroom-zh/                 ← 被评测的 fork 本体（含 kompress_zh 实现）
├─ headroom/                 kompress_zh / content_router 等源码
├─ eval/                     ← 评测代码与材料（本说明的主角）
│  ├─ harness/               评测执行链路（Python 脚本）
│  │  ├─ run_eval.py         步骤①压缩  步骤②上游问答
│  │  ├─ score.py            步骤③生成盲判表  步骤④汇总主结果表
│  │  ├─ results/            产物：compressed.json / answers_*.jsonl / judge_sheet.md / summary.md
│  │  └─ README.md           harness 详细使用说明
│  ├─ materials/             20 题评测材料集
│  │  ├─ manifest.json       20 题总清单（唯一权威索引，自动判分读它）
│  │  ├─ contexts/           A1–A5 / B1–B5 / C1–C5 / D1–D5 材料正文
│  │  └─ README.md           材料设计与判分口径
│  ├─ demo/                  现场 dashboard 演示材料（demo_bundle.md + 说明）
│  ├─ requirements-windows.txt   Windows 本地跑通 kompress_zh 的依赖清单
│  └─ README.md              （本文件）
└─ eval_docs/                ← 评测与排查记录文档
   ├─ 评测方案_v1.md / 评测方案构思与审核纪要.md / 评测结果_v1.md
   ├─ Windows部署修复记录.md          Windows 部署踩坑与修复（cu128 torch 等）
   ├─ 实时压缩失效_假设排查方案.md      实时 proxy 路径排查全记录（终极根因 = Rust 内容检测卡死）
   ├─ codex全局劫持_背景与去劫持操作.md
   ├─ headroom_502_*.md / headroom_setup_log.md   早期接入调试记录
   └─ _kompress_zh_sample.json        压缩前后样本
```

> Windows 部署踩坑与实时压缩排查见 [`../eval_docs/Windows部署修复记录.md`](../eval_docs/Windows部署修复记录.md)
> 与 [`../eval_docs/实时压缩失效_假设排查方案.md`](../eval_docs/实时压缩失效_假设排查方案.md)。本地每次启动的命令备忘不随仓库分发。

---

## `eval/` 评测做了什么

### 设计（唯一变量 = 是否 / 多激进地压缩）

在进程内用**真实的 kompress_zh** 压缩"工具输出"上下文，再把两种上下文直接发给上游 LLM 比较答案。
不依赖 proxy server，变量更纯。三个对照条件：

| 条件 | 是否压缩 | max_new_tokens | 范围 | 用途 |
|---|---|---|---|---|
| `baseline` | 否 | — | 全 20 题 | 效果基准 |
| `kompress_zh_normal` | 是 | 1024 | 全 20 题 | 主对比（给足额度以保留锚点）|
| `kompress_zh_aggressive` | 是 | 64 | A/C 共 10 题 | 破坏档（强制截断丢锚点，自证指标有区分度）|

### 评测材料（20 题 · 4 类）

- **A** 长中文日志排错 · **B** 中文交接文档 QA · **C** 多步操作指令复述 · **D** 中文笔记语义三分类
- 每题埋有"绝不能丢"的**锚点**（路径 / 命令 / 端口 / 错误码 / 数字 / 步骤）
- 材料均为 **≥1768 字符、中文占比 0.36–0.53** 的单块中文文本——这是 kompress_zh 触发的硬条件
  （`role=tool`、单块 ≥500 字、中文占比 ≥30%）。详见 [`materials/README.md`](materials/README.md)。

### 指标口径

- **主指标 = 任务正确率**（人工二值盲判；D 题按"5 条陈述判对 ≥4 记 1"折算）
- **辅助 = 答案锚点保留率**（自动：答案中逐字命中的锚点 / 总锚点）
- **压缩 = 节省 token%**（kompress_zh 内置 compression_ratio 反推）

---

## 如何运行（PowerShell）

前置：按 [`requirements-windows.txt`](requirements-windows.txt) 在 `<repo>\.venv` 装好环境
（踩坑与修复见 [`../eval_docs/Windows部署修复记录.md`](../eval_docs/Windows部署修复记录.md)）。
`<repo>` = 本 fork 根目录。

```powershell
$env:PYTHONUTF8=1
$env:HF_ENDPOINT="https://huggingface.co"   # adapter 已缓存则不联网
$py = "<repo>\.venv\Scripts\python.exe"
cd <repo>\eval\harness

# ① 本地压缩（免费，GPU）→ results/compressed.json
& $py run_eval.py compress

# ② 上游问答（需 key）
$env:OPENAI_BASE_URL="https://yunwu.ai/v1"
$env:OPENAI_API_KEY="sk-xxxx"
& $py run_eval.py answer --smoke   # 先打 1 题测连通
& $py run_eval.py answer           # 全量

# ③ 生成可读盲判表 → 在 results/judge_sheet.md 每条 `correct:` 后填 1/0
& $py score.py prep

# ④ 汇总主结果表 → results/summary.md
& $py score.py aggregate
```

完整说明见 [`harness/README.md`](harness/README.md)。

---

## 主结果（v1）

| 条件 | 样本 | 任务正确率 | 答案锚点命中率 | 平均节省% |
|---|---|---|---|---|
| **Baseline(不压缩)** | 40 | **100.0%** | 79.7% | — |
| **正常档(@1024)** | 40 | **95.0%** | 73.8% | **38.5** |
| **破坏档(激进@64)** | 20 | **0.0%** | 14.0% | 95.6 |

**结论**：正常档省约 38.5% token、正确率仍保持 95%（基线 100%）；而把压缩推到极端（省 95.6%）时
正确率归零——既证明"省 token 不掉效果"成立，又说明评测指标本身**有区分度**（破坏档自检通过）。

> 唯一失分在 A3：压缩未截断、语义也对，但改写式压缩把精确错误码 `BUILD-2051` 改丢了，而该题恰好问错误码——
> 属改写式压缩对"精确标识符"的固有偶发损耗，与压缩预算无关。

---

## 现场 demo

[`demo/`](demo/) 提供一份大体量中文 bundle（≈2.8 万 tokens），让 codex 通读后回答 gist 问题，
从而在 `/dashboard` 上看到 kompress_zh 的明显节省（小文件的压缩量会被 codex 庞大上下文稀释）。
口径提醒：dashboard 百分比是"压缩量 ÷ codex 整条线"，评测里的 38–59% 是"压缩量 ÷ 中文块本身"，分母不同。
