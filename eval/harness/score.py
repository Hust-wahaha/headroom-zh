"""评分与汇总。

两步：
  python score.py prep        # 自动算锚点命中率 + 生成【可读的 Markdown 盲判表】供人工二值判分
  python score.py aggregate   # 人工在盲判表填好 correct 后，汇总成 results/summary.md（v1 §5 主结果表）

主指标 = 任务正确率（人工二值，A/B/C 直接判；D 按"5 条陈述判对≥4 记 1"折算为题级二值）。
辅助指标 = 锚点保留率（自动：答案中逐字命中的 anchors / 该题 anchors 总数）。
盲判：judge_sheet 不含组别，judge_map.json 记录映射，避免判分偏向压缩组。
"""
from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
RESULTS = HARNESS / "results"
COMPRESSED = RESULTS / "compressed.json"
JUDGE_MD = RESULTS / "judge_sheet.md"
JUDGE_MAP = RESULTS / "judge_map.json"
SUMMARY = RESULTS / "summary.md"

CONDS = ["baseline", "kompress_zh_normal", "kompress_zh_aggressive"]
COND_LABEL = {"baseline": "Baseline(不压缩)", "kompress_zh_normal": "正常档",
              "kompress_zh_aggressive": "破坏档(激进)"}


def anchor_hit(answer: str, anchors: list[str]) -> tuple[int, int]:
    if not anchors:
        return 0, 0
    return sum(1 for a in anchors if a and a in answer), len(anchors)


def load_answers() -> list[dict]:
    # 合并读取所有 answers_<condition>.jsonl（按条件分文件，支持只重跑某条件）
    files = sorted(p for p in RESULTS.glob("answers_*.jsonl") if p.name != "answers_smoke.jsonl")
    if not files:  # 兼容旧的单文件
        legacy = RESULTS / "answers.jsonl"
        files = [legacy] if legacy.exists() else []
    if not files:
        raise SystemExit("未找到 results/answers_*.jsonl，请先运行 run_eval.py answer")
    recs = []
    for f in files:
        recs += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return recs


def cmd_prep(_args=None) -> None:
    recs = load_answers()
    items, judge_map = [], {}
    for i, r in enumerate(recs):
        hit, tot = anchor_hit(r["answer"], r.get("anchors", []))
        jid = f"J{i:03d}"
        judge_map[jid] = {"id": r["id"], "condition": r["condition"], "run": r["run"],
                          "anchor_hit_rate": round(hit / tot, 3) if tot else None}
        items.append({
            "jid": jid, "category": r["category"], "anchor": f"{hit}/{tot}" if tot else "—",
            "question": r["question"].strip(), "gold": r["gold_answer"].strip(),
            "answer": (r["answer"] or "(空)").strip(), "error": r.get("error"),
        })
    random.seed(42)
    random.shuffle(items)   # 打乱顺序，弱化判分偏向

    out = [
        "# kompress_zh 盲判表",
        "",
        "在每个条目的 `correct:` 后填 **1**（答对）或 **0**（答错），保存后运行 `python score.py aggregate`。",
        "",
        "判分规则：只看【模型答案】是否答对【标准答案】的核心要点。",
        "A/B/C 直接 1/0；D 题（语义三分类，5 条陈述）判对 ≥4 条记 1。**盲判：条目不显示属于哪个组。**",
        "（锚点命中是自动算的辅助参考，不等于判分依据。）",
        "", "---", "",
    ]
    for it in items:
        out.append(f"## {it['jid']} · 类别 {it['category']} · 锚点命中 {it['anchor']}")
        if it["error"]:
            out.append(f"> ⚠️ 调用出错：{it['error']}")
        out.append("")
        out.append("**问题**")
        out.append("")
        out.append(it["question"])
        out.append("")
        out.append("**标准答案**")
        out.append("")
        out.append(it["gold"])
        out.append("")
        out.append("**模型答案**")
        out.append("")
        out.append(it["answer"])
        out.append("")
        out.append("`correct:` ")
        out.append("")
        out.append("---")
        out.append("")
    JUDGE_MD.write_text("\n".join(out), encoding="utf-8")
    JUDGE_MAP.write_text(json.dumps(judge_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {JUDGE_MD} ({len(items)} 条) 和 {JUDGE_MAP}")
    print("→ 打开 judge_sheet.md，在每条的 `correct:` 后填 1/0，保存后运行：python score.py aggregate")


# 解析每个 "## Jxxx ..." 区块后的 `correct:` 值
_BLOCK = re.compile(r"^##\s+(J\d{3})\b", re.M)
_CORRECT = re.compile(r"`?correct:`?\s*([01])")


def _parse_judgments() -> dict[str, int | None]:
    text = JUDGE_MD.read_text(encoding="utf-8")
    marks = list(_BLOCK.finditer(text))
    res: dict[str, int | None] = {}
    for idx, m in enumerate(marks):
        jid = m.group(1)
        block = text[m.end(): marks[idx + 1].start() if idx + 1 < len(marks) else len(text)]
        cm = _CORRECT.search(block)
        res[jid] = int(cm.group(1)) if cm else None
    return res


def cmd_aggregate(_args=None) -> None:
    if not JUDGE_MD.exists():
        raise SystemExit("未找到 judge_sheet.md，请先运行 python score.py prep")
    judge_map = json.loads(JUDGE_MAP.read_text(encoding="utf-8"))
    compressed = json.loads(COMPRESSED.read_text(encoding="utf-8")) if COMPRESSED.exists() else {}
    judged = _parse_judgments()

    agg = defaultdict(lambda: defaultdict(lambda: {"correct": [], "anchor": []}))
    unjudged = 0
    for jid, meta in judge_map.items():
        c = judged.get(jid)
        if c is None:
            unjudged += 1
            continue
        cat = meta["id"][0]
        agg[meta["condition"]][cat]["correct"].append(c)
        if meta.get("anchor_hit_rate") is not None:
            agg[meta["condition"]][cat]["anchor"].append(meta["anchor_hit_rate"])

    sav = defaultdict(lambda: defaultdict(list))
    for key, e in compressed.items():
        cond, tid = key.split("|")
        sav[cond][tid[0]].append(e["savings_pct"])

    def pct(xs):
        return f"{round(100 * sum(xs) / len(xs), 1)}%" if xs else "—"

    lines = ["# kompress_zh 评测主结果（自动汇总）", ""]
    if unjudged:
        lines += [f"> 注意：还有 **{unjudged}** 条未判分（correct 为空），未计入。", ""]

    for cond in CONDS:
        if cond not in agg:
            continue
        lines += [f"## {COND_LABEL[cond]}", "",
                  "| 类别 | 样本 | 任务正确率 | 答案锚点命中率 | 平均节省% |",
                  "|---|---|---|---|---|"]
        ac, aa, as_ = [], [], []
        for cat in ["A", "B", "C", "D"]:
            cc, an, ss = agg[cond][cat]["correct"], agg[cond][cat]["anchor"], sav[cond][cat]
            if not cc and not ss:
                continue
            lines.append(f"| {cat} | {len(cc)} | {pct(cc)} | {pct(an)} | "
                         f"{round(sum(ss)/len(ss),1) if ss else '—'} |")
            ac += cc; aa += an; as_ += ss
        lines.append(f"| **合计** | **{len(ac)}** | **{pct(ac)}** | **{pct(aa)}** | "
                     f"**{round(sum(as_)/len(as_),1) if as_ else '—'}** |")
        lines.append("")

    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {SUMMARY}\n")
    print("\n".join(lines))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep")
    sub.add_parser("aggregate")
    args = ap.parse_args()
    {"prep": cmd_prep, "aggregate": cmd_aggregate}[args.cmd]()


if __name__ == "__main__":
    main()
