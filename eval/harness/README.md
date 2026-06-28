# kompress_zh 评测 harness 使用说明

实现 [`../../eval_docs/评测方案_v1.md`](../../eval_docs/评测方案_v1.md) 的脚本化执行链路。

## 设计

在进程内用**真实的 kompress_zh** 压缩"工具输出"上下文，再把【原文 / 压缩后】两种上下文
直接发给上游 LLM，比较答案。唯一变量 = 是否 / 多激进地压缩（不依赖 proxy server，
变量更纯、最稳）。

三个条件（对应方案 v1 第三章）：

| 条件 | 压缩 | max_new_tokens | 范围 | 用途 |
|---|---|---|---|---|
| `baseline` | 否 | — | 全 20 题 | 效果基准 |
| `kompress_zh_normal` | 是 | 1024 | 全 20 题 | 主对比（给足额度以保留锚点）|
| `kompress_zh_aggressive` | 是 | 64 | A/C 共 10 题 | 破坏档（强制截断丢锚点，自证指标有区分度）|

> max_new_tokens 是关键旋钮：太低会截断长材料导致"假性掉点"。1024 给正常档足够额度；
> 64 给破坏档制造"丢锚点→掉点"。两者均可在 `run_eval.py` 的 `CONDITIONS` 调整。

## 运行步骤（PowerShell）

```powershell
$env:PYTHONUTF8=1
$env:HF_ENDPOINT="https://huggingface.co"   # adapter 已缓存则不联网
$py = "<repo>\.venv\Scripts\python.exe"
cd <repo>\eval\harness

# 1) 本地压缩（免费，GPU）—— 产出 results/compressed.json（含每题 orig/comp tokens、节省%）
& $py run_eval.py compress

# 2) 上游问答（需 key）—— 先连通性自测，再全量
$env:OPENAI_BASE_URL="https://yunwu.ai/v1"
$env:OPENAI_API_KEY="sk-xxxx"
& $py run_eval.py answer --smoke           # 只打 1 题测通
& $py run_eval.py answer                    # 全量（baseline+正常档 20×2 + 破坏档 10×2 ≈ 100 次）
# 也可分条件：& $py run_eval.py answer --condition baseline

# 3) 评分：自动锚点命中 + 生成【可读 Markdown 盲判表】
& $py score.py prep
#   → 打开 results/judge_sheet.md，在每条的 `correct:` 后填 1/0（盲判，不看组别；
#     D 题按"5 条陈述判对≥4 记 1"折算为题级二值），保存

# 4) 汇总成主结果表
& $py score.py aggregate                    # → results/summary.md（v1 §5 表）
```

## 产物（`results/`）

- `compressed.json` —— 每题每条件的压缩前后 token 与节省%、压缩文本
- `answers.jsonl` —— 每次上游调用的答案 + 元信息（含锚点、gold、压缩元数据）
- `judge_sheet.md` —— 可读盲判表（隐藏组别，每条填 `correct: 1/0`）；`judge_map.json` 为映射
- `summary.md` —— 按类别/合计的 任务正确率 + 锚点保留率 + 平均节省% 主结果表

## 指标口径（与方案 v1 §4 一致）

- **主指标 = 任务正确率**（人工二值，盲判；D 题 ≥4/5 折算题级二值）
- **辅助 = 锚点保留率**（自动：答案中逐字命中的 anchors / 总 anchors）
- **压缩 = 节省 token%**（kompress_zh 内置 compression_ratio 反推）
- 重复：每题 temp=0 跑 2 次核验一致性（`--repeats`，默认 2）

## 注意

- 涉及 LoRA adapter 时用 `HF_ENDPOINT=https://huggingface.co`（hf-mirror 的 blob 端点本机不通；
  adapter 首次下载后即缓存，之后离线可用）。详见 [`../../eval_docs/Windows部署修复记录.md`](../../eval_docs/Windows部署修复记录.md)。
- 上游若为推理型模型不支持 `temperature`，脚本会自动回退为不带该参数重试。
