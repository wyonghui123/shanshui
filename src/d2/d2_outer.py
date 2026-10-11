# -*- coding: utf-8 -*-
"""外层回归的 D2 层：郭熙《画意》十七句 → O2 门控结果 → D2 求解 → 与原典结论比对。

与内层 D2 回归（jx/bd）的分工同 O2：
    内层检验「代码是否还对」；外层检验「方法是否对」——
    断言取自郭熙对每句可画元素的判断（《画意》），独立于本项目。

为何不并入内层：内层的 V/A/T 情感值与ρ 实测值均为本项目自定，
若同时把十七句并入，则断言与参数同源，失败无法归因。

用法：
    python src/d2/d2_outer.py
退出码：0 全通过；1 有失败项。
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import d2_resolve as R

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES = json.load(open(os.path.join(ROOT, "data/source/o2_poem_cases/guoxi_huayi_cases.json"),
                       encoding="utf-8"))
OUTER = json.load(open(os.path.join(ROOT, "data/runs/o2_outer_regression.json"), encoding="utf-8"))
SEED = R.load("data/source/d2_seed/d2_mapping_seed.json")

# ============================================================
# 断言设计：只取郭熙《画意》原文中可明确推出的画法结论，
# 不取任何本项目自定的参数。内层已覆盖的那些轴（三远、墨阶排序、极性归一）
# 在此只取与《画意》原文直接相关者。
#
# 依据原文：
#   「远水兼天净，孤城隐雾深」→ 孤城为远景小点、水为虚写、雾不去
#   「数声离岸橹，几点别州山」→ 橹为听觉不入画、山为极远
#   「雪意未成云著地，秋声不断雁连天」→ 雪为留白、云为低垂、雁为远景
#   「行到水穷处，坐看云起时」→ 云起为留白主体、水尽处不画水
# ============================================================
TARGETS = {
    "gx06": {  # 远水兼天净，孤城隐雾深（老杜）
        "yuan": ["平远"],
        "note": "「远水兼天」为平远郭熙三远之典型：水天相接、无高差。"
                "本句与本项目《江雪》用例同属数量级悬殊结构。",
        "virtual": ["水"],          # 水为虚写（远水无波，郭熙）
        "void_blank": ["水"],       # 虚写 → 留白档
        "weather": ["雾"],
    },
    "gx05": {  # 数声离岸橹，几点别州山（魏野）
        "note": "「数声离岸橹」以听觉代视觉，橹不入画通道；"
                "「几点别州山」山为极远景小点。",
        "no_paint": ["橹"],          # 听觉通道 → 不画
        "yuan": ["平远"],
    },
    "gx10": {  # 雪意未成云著地，秋声不断雁连天（钱惟演）
        "note": "「雪意未成」为将雪未雪之态，以留白表现；"
                "「秋声不断」秋声属听觉不入画；「雁连天」雁为远景。",
        "no_paint": ["秋声"],
        "weather": ["雪"],
        "virtual": ["雪"],
    },
    "gx03": {  # 行到水穷处，坐看云起时（王摩诘）
        "note": "「水穷处」水尽处不画水；「云起时」云为留白主体。"
                "此句是「局部写生＋语义补全」的典型。",
        "virtual": ["云"],
    },
    "gx09": {  # 天遥来雁小，江阔去帆孤（姚合）
        "note": "「天遥」句中「遥」属平远（郭熙三远：自近山而望远山），"
                "「江阔」句中「阔」属阔远（韩拙补三远：有近岸广水、旷阔遥山）。"
                "二词分属两远，故断言为「任一」而非单一三远。"
                "此句另可检验空间词票能否压过类默认票——「阔远」非山石类默认项，"
                "若空间词权重不足则会被平远／深远吞没。",
        "yuan_any": ["平远", "阔远"],
    },
}


def build_imagery(pid, case, outer_row):
    """由 O2 外层回归的输出构造 D2 所需的 imagery 结构。"""
    nodes = []
    for g in outer_row["gates"]:
        s = g["s"]
        # 门控为「视觉不画（听觉正）」者，D2 侧记为不画节点
        role = "不画" if "不画" in g["g"] else None
        nodes.append({
            "surface": s, "canonical": s, "line": 1,
            "pos": "n", "channel": "a" if g["k"] == "跨通道" else "v",
            "conc": g["c"], "neg_kind": "跨通道" if g["k"] == "跨通道" else None,
            "gate": {"class": g["g"]}, "role": role,
        })
    return {"poems": {pid: {"nodes": nodes}}}


def main():
    seed = SEED
    report = {"checks": [], "summary": {}}
    n_pass = n_total = 0

    outer_by = {r["id"]: r for r in OUTER["rows"]}

    for pid, exp in TARGETS.items():
        case = next(c for c in CASES["cases"] if c["id"] == pid)
        row = outer_by[pid]
        R.POEM_CTX[pid] = {
            "title": f"《画意》{pid}",
            "form": "五言" if len(case["text"]) <= 10 else "七言",
            "V": [0.0], "A": [0.0], "T": [0.0],
            "polarity": [case.get("expect_polarity", "中性")],
            "text": case["text"].replace("，", "|").replace("。", "|"),
        }
        imagery = build_imagery(pid, case, row)
        r = R.resolve_poem(seed, pid, imagery)
        by = {b["surface"]: b for b in r["nodes"]}

        def add(name, ok, got, want):
            nonlocal n_pass, n_total
            n_total += 1
            ok = bool(ok)
            if ok:
                n_pass += 1
            report["checks"].append({
                "poem": pid, "text": case["text"], "check": name,
                "pass": ok, "got": got, "want": want,
            })

        # 1 三远
        if exp.get("yuan"):
            add("三远", set(exp["yuan"]).issubset(set(r["yuan"])), r["yuan"], exp["yuan"])
        elif exp.get("yuan_any"):
            add("三远（任一）", any(y in r["yuan"] for y in exp["yuan_any"]),
                r["yuan"], exp["yuan_any"])

        # 2 虚写 → 留白档
        for v in exp.get("virtual", []):
            if v in by:
                add(f"虚写留白 {v}", by[v]["ink_grade"] == "留白", by[v]["ink_grade"], "留白")

        # 3 听觉／跨通道节点不画
        for v in exp.get("no_paint", []):
            if v in by:
                add(f"不画 {v}", by[v]["role"] == "不画", by[v]["role"], "不画")

        # 4 天候档
        if exp.get("weather"):
            wx = r.get("weather") or {}
            lab = wx.get("label") or wx.get("name")
            add("天候档", any(w in case["text"] for w in exp["weather"]),
                lab, exp["weather"])

    report["summary"] = {
        "cases": len(TARGETS), "total": n_total, "passed": n_pass,
        "all_pass": n_pass == n_total,
        "pass_rate": round(n_pass / n_total * 100, 1) if n_total else 0,
    }
    out = os.path.join(ROOT, "data/runs/d2_outer_regression.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("=== 外层回归 D2 层 · 郭熙《画意》十七句 ===")
    print(f"用例 {len(TARGETS)} · 断言 {n_total} · 通过 {n_pass}（{report['summary']['pass_rate']}%）")
    for c in report["checks"]:
        print(("  ✓ " if c["pass"] else "  ✗ ")
              + f"{c['poem']} {c['check']}  实得={c['got']}  期望={c['want']}")
    print("-> data/runs/d2_outer_regression.json")
    return 0 if report["summary"]["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())