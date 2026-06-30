# 评测材料集（20 题）· kompress_zh 准确率保持评测

本目录是 [`../../eval_docs/评测方案_v1.md`](../../eval_docs/评测方案_v1.md) 第八章"交付物"第 2 项的落地：
20 个中文上下文评测题的**材料正文 + 标准答案 + 锚点集 + 判分 rubric**。

## 目录结构

```
materials/
  README.md            ← 本文件
  manifest.json        ← 20 题总清单（唯一权威索引，自动判分读它）
  contexts/
    A1.md … A5.md      ← 任务 A 材料正文（长中文日志排错）
    B1.md … B5.md      ← 任务 B 材料正文（中文交接文档 QA）
    C1.md … C5.md      ← 任务 C 材料正文（多步指令复述/重排）
    D1.md … D5.md      ← 任务 D 材料正文（中文笔记语义三分类）
```

每个 `contexts/<ID>.md` **只含一段连贯中文正文**——它就是评测时要作为"工具输出"注入给 agent 的上下文。
问题、标准答案、锚点、rubric 全部在 `manifest.json` 里。

## manifest.json 字段

| 字段 | 含义 |
|---|---|
| `id` | 题号（A1–A5 / B1–B5 / C1–C5 / D1–D5） |
| `category` | 任务类别 |
| `source_type` | `自造` 或 `真实文档中文化` |
| `source_ref` | 真实文档出处（B/D 用，便于评委对照原始英文源） |
| `context_file` | 材料正文相对路径 |
| `context_char_len` / `context_cjk_ratio` | 字符数 / 中文占比（自检用） |
| `ability` | 考察能力 |
| `question` | 给 agent 的完整问题（**baseline 与压缩组逐字一致**） |
| `gold_answer` | 标准参考答案 |
| `anchors` | 必须在正文中**逐字出现**的关键锚点（自动匹配用，已校验 100% 命中） |
| `rubric` | 判分标准 |

## 关键约束（为什么材料长这样）

`kompress_zh` 只在满足以下条件时才会触发（源码：`headroom/transforms/content_router.py`）：

1. 内容位于 `tool` 消息 / `tool_result` 块中；
2. 单块长度 ≥ **500 字符**（`min_chars_for_block_compression=500`）；
3. 中文占比 ≥ **30%**（`_is_chinese_dominant_text`，`ratio=0.30`）。

故所有材料均为 **≥1768 字符、中文占比 0.36–0.53** 的单块中文文本，注入时**必须作为工具输出**
（`role="tool"` 或 `tool_result` 块），否则不会走中文压缩通道，评测无效。

## ⚠️ 关于 B/D"真实文档中文化"（诚实声明）

仓库内的真实文档（`HEADROOM_ZH_AUTODL_REPRO_GUIDE.md`、`kompress_zh_integration_notes.md`、
`HEADROOM_ZH_STATUS_2026-06-20.md`）**本身是英文写的**，直接注入会被判为非中文、走英文 `Kompress`，
**触发不了 `kompress_zh`**。而本评测的对象正是中文通道。

因此 B/D 材料是这些真实文档的**忠实中文化呈现**：
- **真实锚点逐字保留**（端口 `8790`、`PYTHON_BIN=/root/autodl-tmp/qwen_ws/.venv/bin/python`、
  `HEADROOM_REQUIRE_RUST_CORE=false`、SSH 端口 `47263`、`gpt-5.4-2026-03-05`、脚本名、
  `peft>=0.11.0,<1.0`、`ms-swift>=4.1.3`、`headroom._core`、`tiktoken` 等）；
- **真实语义结构保留**（Level 0–3 复现阶梯；Should-be-Kept / NOT-carried-forward / Remaining-cleanup 三类语义）；
- `source_ref` 标注对应英文源文件，**可逐条对照核验**。

这既保证触发中文压缩通道，又保留代表性——且这正是 README 自述的目标场景（"中文交接 bundle"）。
A/C 则为完全自造（合成日志 / 合成阶梯），负责"难度可控、便于对照"。**全部材料公开，接受复核。**

## 破坏组（aggressive 档）如何实现

评测方案 v1 §3.2 要求的"破坏组"有**真实的同压缩器旋钮**（源码：`kompress_zh_compressor.py`），
无需手工删锚点：

- `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS`：默认 192，调到很低（如 `32`）会强制截断输出 → 丢锚点；
- `HEADROOM_KOMPRESS_ZH_SYSTEM_PROMPT` / `HEADROOM_KOMPRESS_ZH_USER_PROMPT`：默认 prompt 明确要求
  "保留路径/命令/数字/文件名"，覆盖为"极致压缩、可丢弃锚点、只留大意"即制造破坏档。

破坏组只跑 **A/C 共 10 题**（锚点最硬、最能体现掉点），用于反向自证指标有区分度。

## 判分口径

- **主指标 = 任务正确率（二值）。** A/B/C 的 rubric 已是二值。
- **D 题分项 rollup 为题级二值**：D 的 rubric 给了分项细分（识别限定语义陷阱权重最高），
  统一**按"5 条陈述判对 ≥4 条记 1，否则 0"**折算为题级二值，纳入主指标；分项分仅作错因分析。
- **锚点保留率（辅助指标）**：对压缩组，统计 agent 答案中命中的 `anchors` 数 / 该题 `anchors` 总数，
  解释"压缩有没有丢关键信息"。
- 判分采用 baseline 与压缩组**答案匿名混合**后判分（盲的是组别归属，非题目答案）。

## 下一步

按 v1 §六 推进评测执行 harness：把 `context_file` 作为工具输出注入 → 分别经
baseline / headroom_zh 正常档 / aggressive 破坏档 → 收集答案 → 自动锚点匹配 + 人工二值判分 →
产出 v1 §五 的主结果表与破坏组对比图。
