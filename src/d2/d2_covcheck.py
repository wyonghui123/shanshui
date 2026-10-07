# -*- coding: utf-8 -*-
"""
D2 覆盖率护栏

用法：
    python src/d2/d2_covcheck.py            # 检查并写 d2_coverage.json
    python src/d2/d2_covcheck.py --strict   # 有未覆盖词时退出码 1

检查三层：
    ① 词典词（o2_lexicon.words）——必须 100% 落到某个类别（否则 D2 无画法束）
    ② 中心字（每词 head）——用于「未在 word_class 命中时」兜底；缺失只告警
    ③ 实跑意象节点（o2_imagery.nodes + 静夜思夹具）——必须全部落类

定位：与 d1_covcheck.py 并列的「数据可得性」护栏。D2 靠「类别默认 + 词覆盖」两级，
      词覆盖必须完整，中心字覆盖决定泛化能力（新词能否只靠中心字落类）。
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")


sys.path.insert(0, HERE)
from d2_resolve import classify, JYS_FIXTURE, POEM_CTX  # noqa: E402


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    t = load(os.path.join(ROOT, "data", "derived", "d2_techniques.json"))
    lex = load(os.path.join(ROOT, "data", "source", "o2_lexicon.json"))
    imagery = load(os.path.join(ROOT, "data", "derived", "o2_imagery.json"))

    # ① 词典词
    word_rows, unresolved = [], []
    for word, e in lex["words"].items():
        cls, how = classify(t, word, e.get("head"))
        row = {"word": word, "head": e.get("head"), "class": cls, "by": how,
               "conc": e.get("conc"), "channel": e.get("channel")}
        word_rows.append(row)
        if cls is None:
            unresolved.append(row)

    # ② 中心字（仅统计「会真正依赖它」的字：未被任何 word_class 词覆盖的 head）
    heads = sorted({e.get("head") for e in lex["words"].values() if e.get("head")})
    head_rows = []
    for h in heads:
        in_head = h in t["head_class"]
        # 该 head 下是否有词已在 word_class 命中（命中则 head 不必需）
        dependent = [w for w, e in lex["words"].items() if e.get("head") == h]
        needed = [w for w in dependent if w not in t["word_class"]]
        head_rows.append({"head": h, "in_head_class": in_head,
                          "words": dependent, "needed_by": needed})
    missing_heads = [r for r in head_rows if not r["in_head_class"]]
    critical_heads = [r for r in missing_heads if r["needed_by"]]

    # ③ 实跑意象节点
    node_rows, unresolved_nodes = [], []
    for pid in POEM_CTX:
        poem = imagery["poems"].get(pid) or JYS_FIXTURE
        for n in poem["nodes"]:
            cls, how = classify(t, n["surface"], (n.get("e") or {}).get("head"))
            row = {"poem": pid, "id": n["id"], "surface": n["surface"], "class": cls, "by": how}
            node_rows.append(row)
            if cls is None:
                unresolved_nodes.append(row)

    n_w = len(word_rows)
    n_n = len(node_rows)
    rep = {
        "meta": {
            "name": "d2_coverage",
            "role": "D2 覆盖率护栏：词典词 / 中心字 / 实跑节点 三层落类检查",
            "lexicon": lex["meta"].get("name"), "lexicon_version": lex["meta"].get("version"),
        },
        "words": {
            "total": n_w,
            "covered": n_w - len(unresolved),
            "rate": round((n_w - len(unresolved)) / n_w, 4) if n_w else 1.0,
            "unresolved": unresolved,
        },
        "heads": {
            "total": len(heads),
            "in_head_class": len(heads) - len(missing_heads),
            "missing": [{"head": r["head"], "words": r["words"], "needed_by": r["needed_by"]}
                        for r in missing_heads],
            "critical_missing": [{"head": r["head"], "needed_by": r["needed_by"]}
                                 for r in critical_heads],
        },
        "nodes": {
            "total": n_n,
            "covered": n_n - len(unresolved_nodes),
            "rate": round((n_n - len(unresolved_nodes)) / n_n, 4) if n_n else 1.0,
            "unresolved": unresolved_nodes,
        },
    }
    rep["ok"] = (not unresolved) and (not unresolved_nodes) and (not critical_heads)

    with open(os.path.join(ROOT, "data", "runs", "d2_coverage.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print("[D2] 覆盖率护栏")
    print(f"  ① 词典词   {rep['words']['covered']}/{n_w}  覆盖率 {rep['words']['rate']*100:.1f}%")
    for r in unresolved:
        print(f"      ✗ 未覆盖：{r['word']} (head={r['head']})")
    print(f"  ② 中心字   {rep['heads']['in_head_class']}/{len(heads)} 在 head_class")
    if critical_heads:
        for r in critical_heads:
            print(f"      ✗ 关键缺失：'{r['head']}' ← {r['needed_by']}")
    for r in missing_heads:
        if not r["needed_by"]:
            print(f"      · 可选缺失：'{r['head']}'（其词已由 word_class 覆盖：{r['words']}）")
    print(f"  ③ 实跑节点 {rep['nodes']['covered']}/{n_n}  覆盖率 {rep['nodes']['rate']*100:.1f}%")
    for r in unresolved_nodes:
        print(f"      ✗ 未覆盖：{r['poem']} {r['surface']}")
    print(f"\n  结论：{'✓ 全通过' if rep['ok'] else '✗ 有缺口'}  → d2_coverage.json")

    if args.strict and not rep["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
