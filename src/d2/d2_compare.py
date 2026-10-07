# -*- coding: utf-8 -*-
"""
D2 × pipeline 对照表

用途：接入卡 2/5/6 前的「对账」——把三首 pipeline 里硬编码的画法参数
      与 D2 现算值逐项比对，确认无偏差后再替换。

用法：
    python src/d2/d2_compare.py            # 打印偏差 + 写 d2_compare.json
    python src/d2/d2_compare.py --all      # 打印全部逐项（不只偏差）

数据来源（人工从 pipeline HTML 抽出，见各诗 STEP 5/6）：
    jiangxue_pipeline.html   §STEP5 / §6.1
    baidicheng_pipeline.html §STEP5 / §6.1
    jingyesi_pipeline.html   §STEP5 / §6.1
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
import d2_resolve as R  # noqa: E402


# 区域 → 意象节点；water=含水档；c=墨浓度实测值；stroke=笔法
PIPELINE = {
    "jx": {
        "rho": 0.79, "rho_range": [0.72, 0.85],
        "yuan": ["平远", "深远"], "cun": ["无皴"],
        "zones": {
            "远山":    {"node": "千山",   "water": "高",  "c": 0.12, "stroke": "大晕染·慢扩散"},
            "万径":    {"node": "万径",   "water": "中",  "c": 0.06, "stroke": "枯笔擦"},
            "孤舟":    {"node": "孤舟",   "water": "低",  "c": 0.92, "stroke": "中锋·一次落笔"},
            "蓑笠翁":  {"node": "蓑笠翁", "water": "低",  "c": 0.95, "stroke": "顿笔·侧锋"},
            "钓丝":    {"node": "独钓",   "water": "极低", "c": 0.40, "stroke": "飞白"},
            "寒江/雪": {"node": "寒江",   "water": None,  "c": 0.00, "stroke": "不画"},
        },
    },
    "bd": {
        "rho": 0.52, "rho_range": [0.45, 0.58],
        "yuan": ["高远", "深远"], "cun": ["大斧劈", "小斧劈"],
        "zones": {
            "彩云":     {"node": "彩云",   "water": "极高", "c": 0.06, "stroke": "大晕染·几乎无形"},
            "白帝城":   {"node": "白帝",   "water": "中",   "c": 0.35, "stroke": "点景·数笔即成"},
            "两岸山壁": {"node": "两岸",   "water": "中",   "c": 0.72, "stroke": "斧劈皴·侧锋快扫"},
            "万重山":   {"node": "万重山", "water": "高",   "c": 0.18, "stroke": "层叠淡墨·逐层递淡"},
            "轻舟":     {"node": "轻舟",   "water": "极低", "c": 0.88, "stroke": "中锋·一次落笔·带拖尾"},
            "猿声":     {"node": "猿声",   "water": None,   "c": 0.00, "stroke": "不画"},
        },
    },
    "jys": {
        "rho": 0.78, "rho_range": [0.72, 0.85],
        "yuan": [], "cun": [],
        "zones": {
            "榻沿(床前)": {"node": "床",   "water": None, "c": 0.55, "stroke": "写+染"},
            "月晕/月光":  {"node": "明月", "water": None, "c": 0.40, "stroke": "染（湿渲）"},
            "地上霜":     {"node": "霜",   "water": None, "c": 0.10, "stroke": "染（上浓下淡）"},
        },
    },
}


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    t = load(os.path.join(ROOT, "data", "derived", "d2_techniques.json"))
    imagery = load(os.path.join(ROOT, "data", "derived", "o2_imagery.json"))

    report = {"poems": {}, "summary": {}}
    n_ok = n_diff = 0

    for pid, p in PIPELINE.items():
        r = R.resolve_poem(t, pid, imagery)
        by = {b["surface"]: b for b in r["nodes"]}
        rows = []

        def add(kind, item, want, got, ok):
            nonlocal n_ok, n_diff
            rows.append({"kind": kind, "item": item, "pipeline": want, "d2": got, "ok": bool(ok)})
            if ok:
                n_ok += 1
            else:
                n_diff += 1

        # 诗级
        add("三远", "三远候选", p["yuan"], r["yuan"],
            set(p["yuan"]).issubset(set(r["yuan"])) if p["yuan"] else r["yuan"] == [])
        add("留白", "ρ 区间含实测", f"{p['rho_range']} ∋ {p['rho']}", r["blank_range"],
            r["blank_range"][0] <= p["rho"] <= r["blank_range"][1])
        add("皴法", "皴法", p["cun"], r["cun"],
            (set(p["cun"]) & set(r["cun"]) != set()) if p["cun"] else r["cun"] == [])

        # 分区笔墨
        for zname, z in p["zones"].items():
            b = by.get(z["node"])
            if b is None:
                add("笔墨", f"{zname}（缺节点 {z['node']}）", "-", "-", False)
                continue
            # 含水：pipeline 未标档（None）者属「特殊渲染/不画」，不构成偏差
            if z["water"] is None:
                add("含水", zname, "—(未标档)", b["water"], True)
            else:
                add("含水", zname, z["water"], b["water"], z["water"] == b["water"])
            # 墨浓度（实测 c 是否落在 D2 墨阶区间内）
            c_lo, c_hi = b["ink_c_range"]
            add("墨阶", zname, f"c={z['c']}", f"{b['ink_grade']} [{c_lo},{c_hi}]",
                c_lo <= z["c"] <= c_hi)
            # 笔法
            want = z["stroke"].split("·")[0]
            got = b["stroke"].split("·")[0]
            add("笔法", zname, z["stroke"], b["stroke"],
                want in b["stroke"] or got in z["stroke"])

        report["poems"][pid] = {
            "title": R.POEM_CTX[pid]["title"],
            "rho": p["rho"], "rows": rows,
            "n_ok": sum(1 for x in rows if x["ok"]), "n": len(rows),
        }

    report["summary"] = {"ok": n_ok, "diff": n_diff, "total": n_ok + n_diff,
                         "rate": round(n_ok / (n_ok + n_diff), 4)}

    with open(os.path.join(ROOT, "data", "runs", "d2_compare.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[D2 × pipeline] 对照表")
    for pid, pr in report["poems"].items():
        print(f"\n  ── {pr['title']}  ({pr['n_ok']}/{pr['n']}) ──")
        for x in pr["rows"]:
            if x["ok"] and not args.all:
                continue
            flag = "✓" if x["ok"] else "✗"
            print(f"    {flag} [{x['kind']}] {x['item']}: pipeline={x['pipeline']}  D2={x['d2']}")
    s = report["summary"]
    print(f"\n  合计：一致 {s['ok']} / 偏差 {s['diff']}  一致率 {s['rate']*100:.1f}%")
    print("  报告 -> d2_compare.json")


if __name__ == "__main__":
    main()
