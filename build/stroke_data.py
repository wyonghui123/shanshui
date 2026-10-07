# -*- coding: utf-8 -*-
"""题诗「真笔顺书写」数据：笔画中线 + 我们字体的字形轮廓。

背景：题诗原为 clipPath 矩形自上而下「揭示」，不是书写。要「逐笔写出」需要
每个字的**笔画顺序**与**中线（运笔轨迹）**——这两样是字体里没有的，取自
hanzi-writer-data（源自 Make Me a Hanzi，Arphic Public License）。

产物 `dist/animation/strokes.js`（`window.POEM_STROKES`），含：
  meta   : 坐标系与出处（引用/许可）
  chars  : 每字的中线折线（笔顺序，已换算到我们的设计单位 upem=1000）
  glyphs : 每字体 × 每字 的字形轮廓 path（design 单位）+ advance + 遮罩带宽 w

遮罩带宽 w 的算法：把字形轮廓离散成边界点，取「边界点到最近中线的最大距离」为
所需半径（≈ 最粗笔画半宽 + 折角外扩），再乘安全系数 → 保证中线带铺满整个字形；
末笔走完时中线带的并集即字形本体。

用法：
    python build/stroke_data.py --fetch   # 联网取源并冻结到 data/source/strokes/
    python build/stroke_data.py           # 由冻结源生成 dist/animation/strokes.js
    python build/stroke_data.py --check   # 校验产物与当前字体/源一致（幂等）
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "source", "strokes")
OUT = os.path.join(ROOT, "dist", "animation", "strokes.js")
FONT_DIR = os.path.join(ROOT, "dist", "animation", "fonts")

DATA_URL = "https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/%s.json"
REF_BOX = 1024.0          # hanzi-writer-data 坐标系：x∈[0,1024]，基线 y=0，y 向上
UPEM = 1000.0             # 我们字体 head.unitsPerEm
SCALE = UPEM / REF_BOX    # 参考坐标 → 我们的设计单位
SAFETY = 1.12             # 遮罩带宽安全系数
RDP_EPS = 6.0             # 中线简化容差（参考坐标单位）

POEMS = {
    "jx":  {"lines": ["千山鸟飞绝", "万径人踪灭", "孤舟蓑笠翁", "独钓寒江雪"],
            "author": "柳宗元", "face": "PoemLongCang"},
    "bd":  {"lines": ["朝辞白帝彩云间", "千里江陵一日还", "两岸猿声啼不住", "轻舟已过万重山"],
            "author": "李白", "face": "PoemMaShan"},
    "jys": {"lines": ["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"],
            "author": "李白", "face": "PoemMaShan"},
}
FONT_FILE = {
    "PoemLongCang": "poem-longcang.woff2",
    "PoemMaShan": "poem-mashan.woff2",
    "PoemZhiMang": "poem-zhimang.woff2",
}
AUTHOR_FACE = "PoemZhiMang"


# ---------- 字形轮廓 → 边界点 / path ----------

class FlattenPen(BasePen):
    """把字形轮廓离散成折线（用于算带宽与覆盖）。"""

    def __init__(self, glyphSet, steps=8):
        super().__init__(glyphSet)
        self.contours = []
        self._cur = None
        self.steps = steps

    def _moveTo(self, pt):
        self._cur = [pt]
        self.contours.append(self._cur)

    def _lineTo(self, pt):
        self._cur.append(pt)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self._cur.append((
                u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
            ))

    def _qCurveToOne(self, p1, p2):
        p0 = self._cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self._cur.append((
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            ))

    def _closePath(self):
        self._cur = None

    def _endPath(self):
        self._cur = None


def glyph_geometry(font, ch):
    """返回 (path_d, advance, boundary_points[list[(x,y)]])，design 单位。"""
    cmap = font.getBestCmap()
    gname = cmap.get(ord(ch))
    if gname is None:
        raise KeyError("字体缺字：%s" % ch)
    gs = font.getGlyphSet()
    adv = font["hmtx"][gname][0]
    sp = SVGPathPen(gs)
    gs[gname].draw(sp)
    fp = FlattenPen(gs)
    gs[gname].draw(fp)
    pts = [p for c in fp.contours for p in c]
    return sp.getCommands(), adv, pts


# ---------- 中线 ----------

def rdp(points, eps):
    """Ramer–Douglas–Peucker 简化折线。"""
    if len(points) < 3:
        return list(points)
    a = np.asarray(points[0], float)
    b = np.asarray(points[-1], float)
    ab = b - a
    l2 = float(ab @ ab)
    if l2 == 0:
        d = np.linalg.norm(np.asarray(points, float) - a, axis=1)
    else:
        t = np.clip(((np.asarray(points, float) - a) @ ab) / l2, 0, 1)
        proj = a + t[:, None] * ab
        d = np.linalg.norm(np.asarray(points, float) - proj, axis=1)
    i = int(np.argmax(d))
    if d[i] > eps:
        return rdp(points[:i + 1], eps)[:-1] + rdp(points[i:], eps)
    return [points[0], points[-1]]


def dist_to_polyline(P, poly):
    """P:(N,2) 到一条折线各段的最近距离 → (N,)。"""
    if len(poly) < 2:
        return np.full(len(P), np.inf)
    A = poly[:-1]
    B = poly[1:]
    AB = B - A
    L2 = np.einsum("ij,ij->i", AB, AB)
    L2[L2 == 0] = 1e-9
    d = P[:, None, :] - A[None, :, :]
    t = np.clip(np.einsum("nij,ij->ni", d, AB) / L2[None, :], 0, 1)
    proj = A[None, :, :] + t[:, :, None] * AB[None, :, :]
    return np.sqrt(np.einsum("nij,nij->ni", P[:, None, :] - proj, P[:, None, :] - proj)).min(1)


def stroke_widths(pts, medians):
    """逐笔遮罩带宽：每个边界点归属最近的中线，取该笔内最大距离定带宽。

    比「全场统一带宽」更紧——统一带宽按最远点取值，会把相邻笔画一并罩进来，
    运笔时会提前带出别的笔画；逐笔带宽只保证本笔自己的轮廓被覆盖，
    各笔带宽之并仍铺满整个字形（每个边界点至少被其最近的那一笔覆盖）。
    """
    if not len(pts) or not medians:
        return [0.0] * len(medians)
    P = np.asarray(pts, float)
    D = np.stack([dist_to_polyline(P, m) for m in medians], axis=1)   # (N,K)
    idx = D.argmin(1)
    dmin = D.min(1)
    ws = []
    for k in range(len(medians)):
        sel = dmin[idx == k]
        ws.append(2.0 * float(sel.max()) * SAFETY if sel.size else 0.0)
    pos = [w for w in ws if w > 0]
    floor = (min(pos) if pos else 0.0)
    return [w if w > 0 else floor for w in ws]


def coverage_protrusion(pts, medians, widths):
    """覆盖护栏：所有边界点中「最外凸」的量 = max( dist(p, 最近中线) − w/2 )。

    点 p 归属最近中线 k 时，其到该笔锋带边缘的有符号距离为 dist(p,m_k) − w_k/2；
    取全场最大。≤0 表示每个边界点都落在带的并集内（末笔走完即字形本体，无空洞）；
    >0 说明有轮廓点露在带外，写完会缺肉——SAFETY 被调小到 1 以下即触发。
    """
    if not len(pts) or not medians:
        return float("-inf")
    P = np.asarray(pts, float)
    D = np.stack([dist_to_polyline(P, m) for m in medians], axis=1)
    idx = D.argmin(1)
    dmin = D.min(1)
    W = np.asarray(widths, float)[idx]
    return float((dmin - W / 2.0).max())


def polyline_len(poly):
    if len(poly) < 2:
        return 0.0
    d = np.diff(np.asarray(poly, float), axis=0)
    return float(np.sqrt((d ** 2).sum(1)).sum())


# ---------- 取源 ----------

def fetch(ch):
    path = os.path.join(CACHE, ch + ".json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    url = DATA_URL % urllib.parse.quote(ch)
    last = None
    for attempt in range(5):
        try:
            raw = urllib.request.urlopen(url, timeout=60).read()
            break
        except Exception as e:                       # 网络抖动（SSL 握手超时等）→ 重试
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        raise SystemExit("取源失败 %s：%s" % (ch, last))
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)
    return json.loads(raw)


def needed():
    """→ (chars:set, glyph_pairs:set[(face,char)])"""
    chars, pairs = set(), set()
    for cfg in POEMS.values():
        for line in cfg["lines"]:
            for ch in line:
                chars.add(ch)
                pairs.add((cfg["face"], ch))
        for ch in cfg["author"]:
            chars.add(ch)
            pairs.add((AUTHOR_FACE, ch))
    return chars, pairs


# ---------- 构建 ----------

def build(write=True):
    chars, pairs = needed()
    fonts = {face: TTFont(os.path.join(FONT_DIR, fn)) for face, fn in FONT_FILE.items()}
    for face, fn in FONT_FILE.items():
        if fonts[face]["head"].unitsPerEm != UPEM:
            raise SystemExit("upem 非 %d：%s" % (UPEM, fn))

    out_chars, out_glyphs = {}, {}
    prot_worst, cov_nglyph = float("-inf"), 0
    for ch in sorted(chars):
        src = fetch(ch)
        meds = [rdp([tuple(map(float, p)) for p in m], RDP_EPS) for m in src["medians"]]
        meds_design = [[(x * SCALE, y * SCALE) for x, y in m] for m in meds]
        lens = [polyline_len(m) for m in meds_design]
        out_chars[ch] = {
            "m": [[[round(x, 1), round(y, 1)] for x, y in m] for m in meds_design],
            "l": [round(v, 1) for v in lens],
        }
        med_arr = [np.asarray(m, float) for m in meds_design]
        for face, _ in [p for p in pairs if p[1] == ch]:
            d, adv, pts = glyph_geometry(fonts[face], ch)
            ws = stroke_widths(pts, med_arr)
            prot_worst = max(prot_worst, coverage_protrusion(pts, med_arr, ws))
            cov_nglyph += 1
            out_glyphs.setdefault(face, {})[ch] = {
                "d": d, "a": adv, "w": [round(v, 1) for v in ws],
            }
    stats = {"glyphs": cov_nglyph, "prot_worst": prot_worst}

    data = {
        "meta": {
            "ref": REF_BOX, "scale": SCALE, "upem": UPEM,
            "src": "hanzi-writer-data@2.0.1 (Make Me a Hanzi / Arphic Public License)",
            "note": "m=笔画中线(笔顺序,design 单位)；glyphs[face][ch]={d 字形path,a advance,w 逐笔遮罩带宽}",
        },
        "chars": out_chars,
        "glyphs": {f: out_glyphs[f] for f in sorted(out_glyphs)},
    }
    js = "window.POEM_STROKES = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    if write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(js)
    return data, js, stats


def main():
    if "--fetch" in sys.argv:
        chars, _ = needed()
        os.makedirs(CACHE, exist_ok=True)
        for ch in sorted(chars):
            fetch(ch)
        print("已冻结 %d 字 → %s" % (len(chars), os.path.relpath(CACHE, ROOT)))
        return
    check = "--check" in sys.argv
    data, js, stats = build(write=not check)
    if check:
        ok = True
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else None
        if cur != js:
            print("✗ strokes.js 与字体/源不同步（跑 python build/stroke_data.py 修复）")
            ok = False
        if stats["prot_worst"] > 0:
            print("✗ 笔锋带覆盖不足：最外凸 %.1f > 0（末笔走完会缺肉）" % stats["prot_worst"])
            ok = False
        if not ok:
            sys.exit(1)
        print("✓ strokes.js 同步：%d 字 · %d 字体 · 覆盖外凸 ≤ %.1f（design 单位）"
              % (len(data["chars"]), len(data["glyphs"]), stats["prot_worst"]))
        return
    print("→ dist/animation/strokes.js  %d 字 · %d 字体 · %.1f KB · 覆盖外凸 ≤ %.1f"
          % (len(data["chars"]), len(data["glyphs"]), len(js.encode("utf-8")) / 1024,
             stats["prot_worst"]))


if __name__ == "__main__":
    main()
