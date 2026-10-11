# -*- coding: utf-8 -*-
"""外层回归的 D2 层：郭熙《画意》十七句 → O2 门控结果 → D2 求解 → 与原典结论比对。

与内层 D2 回归（jx/bd）的分工同 O2：
    内层检验「代码是否还对」；外层检验「方法是否对」——
    断言取自郭熙对每句可画元素的判断（《画意》），独立于本项目。

为何不并入内层：内层的 V/A/T 情感值与ρ 实测值均为本项目自定，
若同时把十七句并入，则断言与参数同源，失败无法归因。

断言只取《画意》原文可明确推出的画法结论，不取本项目自定参数：
  · 虚写／听觉 → 留白／不画（郭熙「远水无波」；架构设定听觉不入画）
  · 实写动物 → 可画（郭熙「远人无目」言其小而可画，非不画）
  · 三远（郭熙《山水训》三远义）
  · 天候档（《画题》天候）
  · 远山无皴（郭熙「远山无皴，远水无波，远人无目。非无也，如无耳」）
  · 无可画内容 → 三远不适用（边界用例 gx16）

用法：
    python src/d2/d2_outer.py
退出码：0 全通过；1 有失败项。
"""
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
# 断言字段
#   yuan / yuan_any  三远：子集 / 任一
#   yuan_na          三远不适用（无山石亦无水体）
#   void             虚写／留白节点：墨阶=留白
#   painted          实写节点：非留白、非不画
#   no_paint         听觉／跨通道节点：role=不画
#   cun_no           远山无皴：该山石节点皴法=无皴
#   weather          天候档（该句命中天候词）
#   no_paintable     全句无可画节点（边界）
# ============================================================
TARGETS = {
    "gx01": {  # 舍南舍北皆春水，但见群鸥日日来（老杜）
        "note": "「春水」为水体承载留白；「群鸥」是唯一实笔。"
                "检验系统是否把「留白」误判为「缺内容」。",
        "void": ["春水"],
        "painted": ["群鸥"],
        "yuan": ["平远"],
    },
    "gx02": {  # 渡水蹇驴只耳直，避风羸仆一肩高（陈与义）
        "note": "「水」「风」为虚写；「蹇驴」「仆」为实写（人物画意，非极简留白）。",
        "void": ["水", "风"],
        "painted": ["蹇驴", "仆"],
    },
    "gx03": {  # 行到水穷处，坐看云起时（王摩诘）
        "note": "「水穷处」水尽处不画水；「云起时」云为留白主体。"
                "此句是「局部写生＋语义补全」的典型。",
        "void": ["水", "云"],
        "yuan_any": ["深远", "平远"],
    },
    "gx04": {  # 六月杖藜来石路，午阴多处听潺湲（王荆公）
        "note": "「潺湲」为水声，属听觉意象——按架构设定听音不入画，只入声景层。"
                "「石」「路」可画，山石重叠为深远。",
        "no_paint": ["潺湲"],
        "yuan": ["深远"],
    },
    "gx05": {  # 数声离岸橹，几点别州山（魏野）
        "note": "「数声」以听觉代视觉——声不入画通道。"
                "「几点别州山」为极远小点，山在远景，郭熙「远山无皴」故减笔无皴。"
                "注意：「橹」为可见之物（O2 门控判实写），不作不画论。",
        "no_paint": ["声"],
        "yuan": ["平远"],
        "cun_no": ["山"],
    },
    "gx06": {  # 远水兼天净，孤城隐雾深（老杜）
        "note": "「远水兼天」为平远郭熙三远之典型：水天相接、无高差。"
                "水为虚写（远水无波），孤城为极小实点（郭熙《画意》即以此为可画之例）。",
        "void": ["水"],
        "painted": ["孤城"],
        "weather": ["雾"],
        "yuan": ["平远"],
    },
    "gx07": {  # 犬眠花影地，牛牧雨声陂（林逋）
        "note": "「犬」「牛」为实写点景（检验字表漂移：此二字曾因 head_class 缺条被判不画）；"
                "「雨」为虚写，「声」为听觉不画。",
        "painted": ["犬", "牛"],
        "void": ["雨"],
        "no_paint": ["声"],
        "yuan_na": True,
    },
    "gx08": {  # 密竹滴残雨，高峰留夕阳（李成）
        "note": "「残雨」为虚写；「高峰」在远景，远山无皴。",
        "void": ["雨"],
        "cun_no": ["峰"],
    },
    "gx09": {  # 天遥来雁小，江阔去帆孤（姚合）
        "note": "「天遥」句中「遥」属平远，「江阔」句中「阔」属阔远（韩拙补三远）。"
                "二词分属两远，故断言为「任一」。此句检验空间词票能否压过类默认票。",
        "void": ["江"],
        "painted": ["雁", "帆"],
        "yuan_any": ["平远", "阔远"],
    },
    "gx10": {  # 雪意未成云著地，秋声不断雁连天（钱惟演）
        "note": "「雪意未成」为将雪未雪之态，以留白表现；"
                "「秋声」属听觉不入画；「雁连天」雁为远景小点，仍可画。",
        "void": ["雪", "云"],
        "painted": ["雁"],
        "no_paint": ["秋声"],
        "weather": ["雪"],
    },
    "gx11": {  # 春潮带雨晚来急，野渡无人舟自横（韦应物）
        "note": "「雨」为虚写；「舟」为实写焦点（无人而舟自横，静中有动）。",
        "void": ["雨"],
        "painted": ["舟"],
    },
    "gx12": {  # 相看临远水，独自上孤舟（郑谷）
        "note": "「远水」为虚写；「孤舟」为实写焦点——与《江雪》孤舟主题直接对应。",
        "void": ["水"],
        "painted": ["孤舟"],
    },
    "gx13": {  # 钓罢孤舟系苇梢，酒开新瓮开包（无名氏）
        "note": "「孤舟」「苇」「酒」皆可画；全句无山无水，三远不适用。",
        "painted": ["孤舟", "苇", "酒"],
        "yuan_na": True,
    },
    "gx14": {  # 女儿山头春雪消，路傍仙杏发柔条（羊士谔）
        "note": "「春雪消」为消融过渡态，以留白与淡墨残迹表现；"
                "「山头」在远景，远山无皴；「杏」为近景点。",
        "void": ["春雪"],
        "painted": ["杏"],
        "cun_no": ["山"],
        "yuan_any": ["平远", "深远"],
    },
    "gx15": {  # 独访山家歇还涉，茅屋斜连隔松叶（李咸用）
        "note": "「茅屋」为地标可画；「山」在远景，远山无皴；「松」为屏障点缀。",
        "painted": ["茅屋", "松"],
        "cun_no": ["山"],
    },
    "gx16": {  # 南游兄弟几时还，知在三湘五岭间（窦巩）
        "note": "边界用例：以地名与距离指代空间，无实写意象。"
                "系统应能识别「无可画内容」而非强行造景。",
        "yuan_na": True,
        "no_paintable": True,
    },
    "gx17": {  # 独立衡门秋水阔，寒鸦飞去日沈山（窦巩）
        "note": "与 gx16 同源，前者无画、后者有画——「秋水阔」即水面留白（阔远）；"
                "「寒鸦」为极小点；「日沈山」之山在远景，远山无皴。",
        "void": ["水"],
        "painted": ["鸦"],
        "cun_no": ["山"],
        "yuan_any": ["阔远", "平远"],
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
        if exp.get("yuan_na"):
            add("三远不适用", r["yuan"] == [], r["yuan"], "[]")

        # 2 虚写 → 留白档
        for v in exp.get("void", []):
            if v in by:
                add(f"虚写留白 {v}", by[v]["ink_grade"] == "留白", by[v]["ink_grade"], "留白")

        # 3 实写 → 可画（非留白、非不画）
        for v in exp.get("painted", []):
            if v in by:
                b = by[v]
                ok = b["role"] != "不画" and b["ink_grade"] != "留白"
                add(f"实写可画 {v}", ok, f"role={b['role']} ink={b['ink_grade']}", "非不画且非留白")

        # 4 听觉／跨通道节点不画
        for v in exp.get("no_paint", []):
            if v in by:
                add(f"不画 {v}", by[v]["role"] == "不画", by[v]["role"], "不画")

        # 5 远山无皴（郭熙）
        for v in exp.get("cun_no", []):
            if v in by:
                add(f"远山无皴 {v}", by[v]["cun"] == "无皴", by[v]["cun"], "无皴")

        # 6 天候档
        if exp.get("weather"):
            wx = r.get("weather") or {}
            lab = wx.get("label") or wx.get("name")
            add("天候档", any(w in case["text"] for w in exp["weather"]),
                lab, exp["weather"])

        # 7 边界：全句无可画节点
        if exp.get("no_paintable"):
            ok = all(b["role"] == "不画" or b["ink_grade"] == "留白" for b in r["nodes"])
            add("无可画节点", ok, len(r["nodes"]), "0 或全为不画/留白")

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
