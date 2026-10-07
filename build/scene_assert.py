# -*- coding: utf-8 -*-
"""度量断言：画面属性 ↔ D2 处方（焦点 / 含水档 / 人物 size）。

与 build/scene_render.py --check 互补：
  · scene_render --check 管「几何不许漂移」（动画 ↔ 场景数据 ↔ 全链路逐值一致）；
  · 本工具管「画出来的属性要兑现 D2 的处方」——把 D2 现算的 role/water/size
    与冻结场景里量得的画面属性对账，防「模型算了、画面没照做」。

测量口径（全部从 data/source/scene/<pid>.json 量取，非人工转录）：
  · eff   有效墨浓度 = 层不透明度 × max over 基元( 色深 × 基元不透明度 )
          色深 = 1 − 相对亮度(sRGB)；渐变取各 stop 的最大 色深×stop-opacity。
  · soft  柔度 = 该层（含基元级 filter）所用滤镜的最大 高斯模糊σ 与 位移scale。
  · 人高  人物子集包围盒高度 / viewBox 高。

断言（读 D2 现算值 d2_resolve.resolve_poem，不写死档位）：
  A 焦点  role=焦点 → mode=darkest 者 eff 须为全场最深；
                     mode=brightest 者最亮可见填充须显著亮于其背景层。
  B 含水  高/极高 → eff ≤ 0.30 且 soft（σ>0 或 位移≥10）；
          低/极低 → eff ≥ 0.40 且 σ=0；
          中      → 0.05 ≤ eff ≤ 0.70。
  C 人物  人高占比 ∈ D2 size_ladder 对应档位区间。

尺寸档区间来源：docs/design/ink_figure_grammar.html §5「四档」
（极写意 ≤4% / 极小点景 4–6% / 点景 6–9% / 中号 9–30%）。

用法：
    python build/scene_assert.py            # 三首
    python build/scene_assert.py --poem jx
退出码：0 全通过；1 有失败项。
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCENE_DIR = os.path.join(ROOT, "data", "source", "scene")
sys.path.insert(0, os.path.join(ROOT, "src", "d2"))
import d2_resolve as R  # noqa: E402

ORDER = ["bd", "jx", "jys"]

# 人物尺寸档（来源：docs/design/ink_figure_grammar.html §5）
SIZE_BANDS = [
    ("极写意", 0.00, 0.04),
    ("极小点景", 0.04, 0.06),
    ("点景", 0.06, 0.09),
    ("中号", 0.09, 0.30),
]

# 画面契约：D2 节点 → 冻结场景图层（人审后固定，避免「自由发挥」式漂移）
SPEC = {
    "bd": {
        "focus": [{"layer": "bd-boat", "node": "轻舟", "mode": "darkest"}],
        "water": [
            {"layer": "bd-cloud", "node": "彩云"},
            {"layer": "bd-far", "node": "万重山"},
            {"layer": "bd-city", "node": "白帝"},
            {"layer": "bd-cliff", "node": "两岸"},
            {"layer": "bd-boat", "node": "轻舟"},
        ],
        "figure": [],
    },
    "jx": {
        "focus": [{"layer": "jx-boat", "node": "孤舟", "mode": "darkest"}],
        "water": [
            {"layer": "jx-far", "node": "千山"},
            {"layer": "jx-path", "node": "万径"},
            {"layer": "jx-boat", "node": "孤舟"},
            {"layer": "jx-line", "node": "独钓"},
        ],
        "figure": [{"layer": "jx-boat", "node": "蓑笠翁", "shapes": [1, 2]}],
    },
    "jys": {
        "focus": [
            {"layer": "sy-moon", "node": "明月", "mode": "brightest", "bg": "sy-night"},
            # 背影为 design 附加（诗中无「人」字），非 D2 节点；作情感焦点的可见性护栏。
            {"layer": "sy-figure", "node": None, "mode": "darkest", "basis": "design"},
        ],
        "water": [
            {"layer": "sy-moon", "node": "明月"},
            {"layer": "sy-frost", "node": "霜"},
        ],
        "figure": [],
    },
}

# ---------------------------------------------------------------- 颜色 / 滤镜 / 渐变
NUM = re.compile(r"-?\d+(?:\.\d+)?")
FILTER_RE = re.compile(r'<filter id="([^"]+)"[^>]*>(.*?)</filter>', re.S)
GRAD_RE = re.compile(r'<linearGradient id="([^"]+)"[^>]*>(.*?)</linearGradient>', re.S)
STOP_RE = re.compile(r'<stop[^>]*stop-color="([^"]+)"[^>]*stop-opacity="([^"]+)"')
SIGMA_RE = re.compile(r'<feGaussianBlur[^>]*stdDeviation="([\d.]+)"')
DISP_RE = re.compile(r'<feDisplacementMap[^>]*scale="([\d.]+)"')


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def color_lum(h):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def color_dark(h):
    return 1.0 - color_lum(h)


def url_id(v):
    m = re.search(r"url\(#([^)]+)\)", v or "")
    return m.group(1) if m else None


def parse_defs(defs):
    filters, grads = {}, {}
    for fid, body in FILTER_RE.findall(defs):
        sig = [float(x) for x in SIGMA_RE.findall(body)]
        disp = [float(x) for x in DISP_RE.findall(body)]
        filters[fid] = (max(sig) if sig else 0.0, max(disp) if disp else 0.0)
    for gid, body in GRAD_RE.findall(defs):
        grads[gid] = [(c, float(o)) for c, o in STOP_RE.findall(body)]
    return filters, grads


# ---------------------------------------------------------------- 逐层测量
def shape_ink(sh, grads):
    """单基元的有效墨浓度：色深 × 基元不透明度。"""
    a = sh["attrs"]
    op = float(a.get("opacity", 1))
    cands = []
    for key in ("fill", "stroke"):
        v = a.get(key)
        if not v or v == "none":
            continue
        if v.startswith("#"):
            cands.append(color_dark(v))
        else:
            gid = url_id(v)
            if gid in grads:
                cands.append(max(color_dark(c) * o for c, o in grads[gid]))
    return (max(cands) if cands else 0.0) * op


def layer_eff(L, grads):
    base = float(L.get("opacity") or 1)
    return base * max([shape_ink(sh, grads) for sh in L["shapes"]] or [0.0])


def layer_soft(L, filters):
    ids = set()
    if L.get("filter"):
        ids.add(L["filter"])
    for sh in L["shapes"]:
        fid = url_id(sh["attrs"].get("filter"))
        if fid:
            ids.add(fid)
    sig = max([filters.get(i, (0, 0))[0] for i in ids] or [0.0])
    disp = max([filters.get(i, (0, 0))[1] for i in ids] or [0.0])
    return sig, disp


def shape_pts(sh):
    a, t = sh["attrs"], sh["tag"]
    if t in ("path", "polygon", "polyline"):
        nums = [float(x) for x in NUM.findall(a.get("d") or a.get("points") or "")]
        return list(zip(nums[0::2], nums[1::2]))
    if t == "circle":
        cx, cy, r = float(a["cx"]), float(a["cy"]), float(a["r"])
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if t == "ellipse":
        cx, cy = float(a["cx"]), float(a["cy"])
        rx, ry = float(a["rx"]), float(a["ry"])
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    if t == "rect":
        x, y = float(a["x"]), float(a["y"])
        return [(x, y), (x + float(a["width"]), y + float(a["height"]))]
    if t == "line":
        return [(float(a["x1"]), float(a["y1"])), (float(a["x2"]), float(a["y2"]))]
    return []


def shape_bright(sh, grads):
    """单基元的可见亮度：亮度 × 不透明度（取填充；用于「最亮区」判定）。"""
    a = sh["attrs"]
    v = a.get("fill")
    if not v or v == "none":
        return 0.0
    op = float(a.get("opacity", 1))
    if v.startswith("#"):
        return color_lum(v) * op
    gid = url_id(v)
    if gid in grads:
        return max(color_lum(c) * o for c, o in grads[gid])
    return 0.0


# ---------------------------------------------------------------- 断言
class Result:
    def __init__(self):
        self.rows = []
        self.fails = 0

    def add(self, ok, kind, item, detail):
        self.rows.append((bool(ok), kind, item, detail))
        if not ok:
            self.fails += 1


def check_poem(pid, t, imagery):
    sc = json.load(open(os.path.join(SCENE_DIR, "%s.json" % pid), encoding="utf-8"))
    filters, grads = parse_defs(sc["defs"])
    H = sc["viewBox"][3]
    by_id = {L["id"]: L for L in sc["layers"]}
    bundles = {b["surface"]: b for b in R.resolve_poem(t, pid, imagery)["nodes"]}
    spec = SPEC[pid]
    res = Result()

    # 可参与「最深」比较的层（排除标注层与不可见层）
    def painted():
        out = {}
        for L in sc["layers"]:
            if L["id"].endswith("-anno") or (L.get("opacity") == "0"):
                continue
            out[L["id"]] = layer_eff(L, grads)
        return out

    # A 焦点
    effs = painted()
    for f in spec["focus"]:
        L = by_id.get(f["layer"])
        if L is None:
            res.add(False, "焦点", f["layer"], "缺层")
            continue
        if f["mode"] == "darkest":
            me = layer_eff(L, grads)
            others = {k: v for k, v in effs.items() if k != L["id"]}
            top = max(others.values()) if others else 0.0
            ok = me >= top - 1e-9
            who = max(others, key=others.get) if others else "—"
            basis = "D2 role=焦点" if f.get("node") else "design 焦点"
            res.add(ok, "焦点", "%s@%s" % (f.get("node") or L["label"], L["id"]),
                    "eff=%.3f 全场最深（次深 %s=%.3f）[%s]" % (me, who, top, basis))
        else:  # brightest
            me = max([shape_bright(sh, grads) for sh in L["shapes"]] or [0.0])
            bg = by_id.get(f["bg"])
            bv = max([shape_bright(sh, grads) for sh in bg["shapes"]] or [0.0]) if bg else 0.0
            d = me - bv
            res.add(d >= 0.30, "焦点", "%s@%s" % (f.get("node") or L["label"], L["id"]),
                    "亮度 %.3f − 背景 %s %.3f = %.3f ≥ 0.30（视觉焦点最亮）"
                    % (me, f["bg"], bv, d))

    # B 含水
    for w in spec["water"]:
        L = by_id.get(w["layer"])
        b = bundles.get(w["node"])
        if L is None or b is None:
            res.add(False, "含水", "%s@%s" % (w["node"], w["layer"]), "缺层或缺 D2 节点")
            continue
        grade = b["water"]
        eff = layer_eff(L, grads)
        sig, disp = layer_soft(L, filters)
        if grade in ("高", "极高"):
            ok = eff <= 0.30 and (sig > 0 or disp >= 10)
            rule = "eff≤0.30 且 soft"
        elif grade in ("低", "极低"):
            ok = eff >= 0.40 and sig == 0
            rule = "eff≥0.40 且 σ=0"
        else:
            ok = 0.05 <= eff <= 0.70
            rule = "0.05≤eff≤0.70"
        res.add(ok, "含水", "%s@%s" % (w["node"], L["id"]),
                "%s → eff=%.3f σ=%.1f disp=%.1f（%s）" % (grade, eff, sig, disp, rule))

    # C 人物 size
    for fg in spec["figure"]:
        L = by_id.get(fg["layer"])
        b = bundles.get(fg["node"])
        if L is None or b is None:
            res.add(False, "人物", "%s@%s" % (fg["node"], fg["layer"]), "缺层或缺 D2 节点")
            continue
        pts = []
        for i in fg["shapes"]:
            if i < len(L["shapes"]):
                pts += shape_pts(L["shapes"][i])
        if not pts:
            res.add(False, "人物", fg["node"], "人物子集无几何")
            continue
        ys = [p[1] for p in pts]
        frac = (max(ys) - min(ys)) / H
        tier = b["size"]
        band = next((bb for bb in SIZE_BANDS if bb[0] == tier), None)
        lo, hi = (band[1], band[2]) if band else (0.0, 1.0)
        res.add(lo <= frac <= hi, "人物", "%s@%s" % (fg["node"], L["id"]),
                "人高 %.1f%% ∈ %s %g–%g%%" % (frac * 100, tier, lo * 100, hi * 100))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poem", choices=ORDER)
    args = ap.parse_args()
    poems = [args.poem] if args.poem else ORDER

    t = json.load(open(os.path.join(ROOT, "data", "derived", "d2_techniques.json"), encoding="utf-8"))
    imagery = json.load(open(os.path.join(ROOT, "data", "derived", "o2_imagery.json"), encoding="utf-8"))

    print("── 度量断言（画面属性 ↔ D2 处方：焦点 / 含水档 / 人物 size）")
    total = Result()
    report = {"poems": {}, "summary": {}}
    for pid in poems:
        res = check_poem(pid, t, imagery)
        title = R.POEM_CTX[pid]["title"]
        print("  [%s] %s" % (pid, title))
        rows = []
        for ok, kind, item, detail in res.rows:
            print("    %s [%s] %s  %s" % ("✓" if ok else "✗", kind, item, detail))
            rows.append({"ok": ok, "kind": kind, "item": item, "detail": detail})
        total.fails += res.fails
        total.rows += res.rows
        report["poems"][pid] = {"title": title, "rows": rows,
                                "ok": sum(1 for r in rows if r["ok"]), "n": len(rows)}

    n = len(total.rows)
    report["summary"] = {"ok": n - total.fails, "n": n, "fails": total.fails}
    with open(os.path.join(ROOT, "data", "runs", "scene_assert.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print()
    if total.fails:
        print("✗ 度量断言未通过（%d/%d 项失败）" % (total.fails, n))
        sys.exit(1)
    print("✓ 度量断言全通过（%d 项）" % n)


if __name__ == "__main__":
    main()
