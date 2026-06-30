"""kompress_zh 准确率保持评测 harness（脚本化路径）。

设计：在进程内用真实的 kompress_zh 压缩"工具输出"上下文，再把【原文 / 压缩后】
两种上下文直接发给上游 LLM，比较答案。唯一变量 = 是否 / 多激进地压缩。

三个条件（对应 评测方案_v1.md）：
  - baseline             : 不压缩，原文上下文
  - kompress_zh_normal   : kompress_zh 默认档（max_new_tokens 见 CONDITIONS），全 20 题
  - kompress_zh_aggressive: 破坏档（max_new_tokens 很低，强制截断丢锚点），仅 A/C 共 10 题

两步：
  python run_eval.py compress          # 本地 GPU 压缩（免费），产出 results/compressed.json
  python run_eval.py answer            # 调上游 LLM（需 OPENAI_API_KEY），产出 results/answers.jsonl
  python run_eval.py answer --smoke    # 只打 1 题，测连通性
环境变量：
  OPENAI_BASE_URL   上游地址（默认 https://yunwu.ai/v1）
  OPENAI_API_KEY    上游 key（answer 步骤必需）
  HEADROOM_EVAL_MODEL  模型（默认 gpt-5.4-2026-03-05）
  HF_ENDPOINT       默认 https://huggingface.co（adapter 已缓存则不联网）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")
os.environ.setdefault("PYTHONUTF8", "1")

ROOT = Path(__file__).resolve().parents[1]          # eval_docs/
MATERIALS = ROOT / "materials"
MANIFEST = MATERIALS / "manifest.json"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

# 每个条件的压缩参数。max_new_tokens 控制压缩输出上限：
#   normal 给足额度以保留锚点；aggressive 故意压到很低制造"丢锚点 -> 掉点"。
CONDITIONS = {
    "baseline":               {"compress": False},
    "kompress_zh_normal":     {"compress": True,  "max_new_tokens": 1024, "scope": "all"},
    "kompress_zh_aggressive": {"compress": True,  "max_new_tokens": 64,  "scope": "AC"},
}

DEFAULT_MODEL = os.environ.get("HEADROOM_EVAL_MODEL", "gpt-5.4-2026-03-05")
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://yunwu.ai/v1")


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def in_scope(task_id: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "AC":
        return task_id[0] in ("A", "C")
    return False


def build_prompt(context: str, question: str) -> list[dict]:
    """统一的提问模板：把上下文当作'工具调用返回的资料'交给模型。
    baseline 与压缩组逐字一致，唯一差异是 context 是否被压缩。"""
    system = "你是一个严谨的中文编码助手。请只依据用户提供的【资料】回答【问题】，不要编造资料中没有的信息。"
    user = (
        "以下是某次工具调用返回的资料，请仔细阅读后回答问题。\n\n"
        f"【资料】\n{context}\n\n"
        f"【问题】\n{question}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------- 步骤 1：本地压缩（免费，GPU）----------------
def cmd_compress(args: argparse.Namespace) -> None:
    from headroom.transforms.kompress_zh_compressor import (
        KompressZhCompressor, KompressZhConfig, is_kompress_zh_available,
    )
    if not is_kompress_zh_available():
        sys.exit("kompress_zh 不可用：请先按 eval_docs/Windows部署修复记录.md 修好环境。")

    manifest = load_manifest()
    # 为每个需要压缩的条件建一个压缩器（共享底层引擎，仅 max_new_tokens 不同）
    compressors = {
        name: KompressZhCompressor(KompressZhConfig(max_new_tokens=cfg["max_new_tokens"]))
        for name, cfg in CONDITIONS.items() if cfg["compress"]
    }

    out_path = RESULTS / "compressed.json"
    # 增量 + 断点续跑：已存在的条目跳过，每条压缩后立即落盘，避免超时丢进度
    out: dict[str, dict] = {}
    if out_path.exists():
        out = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"resume: {len(out)} entries already done, will skip them", flush=True)

    t_start = time.time()
    for cond_name, cfg in CONDITIONS.items():
        if not cfg["compress"]:
            continue
        comp = compressors[cond_name]
        for task in manifest:
            tid = task["id"]
            if not in_scope(tid, cfg["scope"]):
                continue
            key = f"{cond_name}|{tid}"
            if key in out:
                continue
            ctx = (MATERIALS / task["context_file"].replace("/", os.sep)).read_text(encoding="utf-8")
            t0 = time.time()
            r = comp.compress(ctx)
            dt = round(time.time() - t0, 1)
            out[key] = {
                "id": tid, "condition": cond_name,
                "original_tokens": r.original_tokens,
                "compressed_tokens": r.compressed_tokens,
                "compression_ratio": round(r.compression_ratio, 4),
                "savings_pct": round((1 - r.compression_ratio) * 100, 1),
                "changed": r.compressed != ctx,
                "compressed_text": r.compressed,
            }
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{cond_name}] {tid}: {r.original_tokens}->{r.compressed_tokens} "
                  f"({out[key]['savings_pct']}% saved, {dt}s)", flush=True)

    print(f"\nwrote {out_path} ({len(out)} entries, "
          f"{round(time.time()-t_start,1)}s total)", flush=True)


# ---------------- 步骤 2：上游问答（需 key）----------------
def _client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("缺少 OPENAI_API_KEY。请先 $env:OPENAI_API_KEY=\"sk-...\"")
    return OpenAI(base_url=DEFAULT_BASE_URL, api_key=key)


def _ask(client, model: str, messages: list[dict]) -> str:
    # 优先 temperature=0；个别推理模型不支持 temperature 时回退
    for kwargs in ({"temperature": 0}, {}):
        try:
            resp = client.chat.completions.create(model=model, messages=messages, **kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            last = e
    raise last


def cmd_answer(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    compressed = {}
    cpath = RESULTS / "compressed.json"
    if cpath.exists():
        compressed = json.loads(cpath.read_text(encoding="utf-8"))
    elif any(c["compress"] for c in CONDITIONS.values()):
        sys.exit("未找到 results/compressed.json，请先运行：python run_eval.py compress")

    client = _client()
    model = args.model or DEFAULT_MODEL
    repeats = 1 if args.smoke else args.repeats
    conds = [args.condition] if args.condition else list(CONDITIONS.keys())

    # 按条件分文件，便于只重跑某个条件而不动其他条件的结果（score.py 会合并读取）
    n = 0
    for cond_name in conds:
        out_path = RESULTS / ("answers_smoke.jsonl" if args.smoke
                              else f"answers_{cond_name}.jsonl")
        with out_path.open("w", encoding="utf-8") as fout:
            cfg = CONDITIONS[cond_name]
            for task in manifest:
                tid = task["id"]
                if cfg["compress"] and not in_scope(tid, cfg["scope"]):
                    continue
                if cfg["compress"]:
                    entry = compressed.get(f"{cond_name}|{tid}")
                    if not entry:
                        print(f"  skip {cond_name}|{tid}: no compressed entry", flush=True)
                        continue
                    context = entry["compressed_text"]
                    comp_meta = {k: entry[k] for k in
                                 ("original_tokens", "compressed_tokens", "compression_ratio", "savings_pct")}
                else:
                    context = (MATERIALS / task["context_file"].replace("/", os.sep)).read_text(encoding="utf-8")
                    comp_meta = {}
                messages = build_prompt(context, task["question"])
                for run_idx in range(repeats):
                    t0 = time.time()
                    try:
                        answer = _ask(client, model, messages)
                        err = None
                    except Exception as e:
                        answer, err = "", f"{type(e).__name__}: {e}"
                    rec = {
                        "id": tid, "category": task["category"], "condition": cond_name,
                        "run": run_idx, "model": model,
                        "question": task["question"], "gold_answer": task["gold_answer"],
                        "anchors": task["anchors"], "answer": answer, "error": err,
                        "elapsed_s": round(time.time() - t0, 1), **comp_meta,
                    }
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()
                    n += 1
                    print(f"[{cond_name}] {tid} run{run_idx}: "
                          f"{'ERR '+err if err else str(len(answer))+' chars'} ({rec['elapsed_s']}s)", flush=True)
                    if args.smoke:
                        print("--- smoke answer ---\n" + answer[:600], flush=True)
                        print(f"\nwrote {out_path}", flush=True)
                        return
    print(f"\nwrote {out_path} ({n} calls)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("compress")
    pa = sub.add_parser("answer")
    pa.add_argument("--condition", choices=list(CONDITIONS.keys()))
    pa.add_argument("--repeats", type=int, default=2)
    pa.add_argument("--model", default=None)
    pa.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    {"compress": cmd_compress, "answer": cmd_answer}[args.cmd](args)


if __name__ == "__main__":
    main()
