# -*- coding: utf-8 -*-
"""场景几何单一真源：抽取 / 渲染 / 注入 / 校验（三首配置驱动）

问题：动画（dist/animation/ink_animations.html 的 #<pid>-cam）与全链路
静帧 / 线稿（dist/pipelines/<poem>_pipeline.html 的 STEP6 / STEP5）
原本是各自手绘的两张 SVG —— 同一首诗、两套取景，几何互不相同，且会静默漂移。

方案 A（几何冻结为数据）：
  1. --extract  把动画 #<pid>-cam 的场景几何抽取并冻结为 data/source/scene/<pid>.json。
                动画是「绘制面」，<pid>.json 是冻结后的「单一真源」。
  2. --write    由 <pid>.json 渲染 STEP5 线稿（draft 主题）与 STEP6 静帧（ink 主题），
                注入 pipeline 的标记块内（幂等）。
  3. --check    校验 <pid>.json == 现抽动画；pipeline == 由 <pid>.json 重渲的结果。
                两者皆过 => 动画 ↔ 场景数据 ↔ 全链路 三方几何一致。

静止态口径（三首统一）：
  · 相机取 identity；
  · 各层显隐取终态（JS 淡入完成的可见态）；
  · JS 变换（漂移 / 振荡 / 姿态旋转）一律丢弃，取 SVG 基础位；
  · 描边类（dashoffset）取画完态（0）；
  · JS 生成的内容（水纹 / 飘雪）按固定种子与终态参数静态复现。

用法：
    python build/scene_render.py --extract [--poem jx]
    python build/scene_render.py --write   [--poem jx]
    python build/scene_render.py --check   [--poem jx]
"""
import argparse
import json
import math
import os
import re
import sys
import textwrap

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIM = os.path.join(ROOT, "dist", "animation", "ink_animations.html")
SCENE_DIR = os.path.join(ROOT, "data", "source", "scene")

ORDER = ["bd", "jx", "jys"]

VOID = {"path", "rect", "ellipse", "circle", "line", "polygon", "polyline", "use", "image", "stop"}
TAG_RE = re.compile(r'<(/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)(/?)>', re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
GEO = ["d", "cx", "cy", "rx", "ry", "r", "x", "y", "width", "height",
       "x1", "y1", "x2", "y2", "points"]


# ---------------------------------------------------------------- 逐诗配置
# draft 主题：几何取自 <pid>.json，仅换「表现」。keep_opacity=True 表示沿用原笔触透明度。
POEMS = {
    "bd": {
        "name": "早发白帝城",
        "art": "art-bd", "cam": "bd-cam", "seal": "bd-seal",
        "grain": "bdGrain", "anno": "bd-anno", "bare_default": "bd-river",
        "pipeline": "baidicheng_pipeline.html",
        "rho_spec": ("留白率 ρ", 2, 0.52),
        "gravity_spec": ("视觉重心 g", 2, (0.41, 0.69)),
        "labels": {
            "bd-cloud": "彩云", "bd-city": "白帝城", "bd-far": "万重山", "bd-river": "江水",
            "bd-cliff": "两岸山壁", "bd-cun": "斧劈皴", "bd-mist": "峡口雾", "bd-water": "水纹",
            "bd-trail": "拖尾", "bd-boat": "轻舟", "bd-bow": "船头破水", "bd-anno": "画中物标注",
        },
        "layer_opacity": {"bd-mist": "1"},
        "js_layers": {"bd-water": "ripples"},
        "draft": {
            "bd-cloud": {"fill": "#C9C5BA", "opacity": "0.42"},
            "bd-city":  {"fill": "#4A4640", "opacity": "0.55"},
            "bd-far":   {"fill": "#8A8578", "opacity": "0.20"},
            "bd-river": {"fill": "#FBF9F4", "stroke": "rgba(62,92,118,.16)", "sw": "1"},
            "bd-cliff": {"fill": "#4A4640", "opacity": "0.26"},
            "bd-cun":   {"fill": "none", "stroke": "#4A4640", "opacity": "0.30"},
            "bd-mist":  {"skip": True},
            "bd-water": {"fill": "none", "stroke": "#8A8578", "sw": "1.1", "keep_opacity": True},
            "bd-trail": {"fill": "none", "stroke": "#1C1C1C", "dash": "10 6", "keep_opacity": True},
            "bd-boat":  {"fill": "#1C1C1C", "opacity": "0.88"},
            "bd-bow":   {"fill": "none", "stroke": "#3A362F", "keep_opacity": True},
        },
        "overlay": "bd",
        "aria_ink": "早发白帝城水墨静帧：淡墨彩云、斧劈皴山壁、斜向江水留白、浓墨轻舟带飞白拖尾、层叠远山",
        "caption_ink": "笔墨渲染结果（静帧）。彩云用极高含水 + 强模糊，近乎无形；"
                       "山壁用斧劈皴（噪声位移 + 枯笔扫痕）；万重山三层递淡模拟空气透视；"
                       "轻舟为唯一浓墨，尾部拖出飞白，长度与笔速成正比。留白 %g%%。"
                       "静帧几何冻结自动画 <code>#bd-cam</code>（<code>data/source/scene/bd.json</code>），与动画逐值一致。",
        "aria_draft": "早发白帝城构图线稿：高处白帝城与彩云、两岸夹峙山壁、中央江水斜向延伸、左下轻舟、远处层叠万重山",
        "caption_draft": "构图解算结果（线稿）。采用高远 + 深远：仰视白帝城（左上高处），"
                         "层峦向消失点递远。两岸山壁压住画面两侧，中央江水呈斜向白带。"
                         "留白率 %g，远低于《江雪》的 0.79。线稿几何与静帧、动画共用同一份冻结场景"
                         "（<code>data/source/scene/bd.json</code>）。",
    },
    "jx": {
        "name": "江雪",
        "art": "art-jx", "cam": "jx-cam", "seal": "jx-seal",
        "grain": "jxGrain", "anno": "jx-anno", "bare_default": "jx-waterline",
        "pipeline": "jiangxue_pipeline.html",
        "rho_spec": ("留白率 ρ", 2, 0.79),
        "gravity_spec": ("视觉重心 g", 2, (0.65, 0.69)),
        "labels": {
            "jx-far": "远山", "jx-waterline": "山脚水痕", "jx-path": "万径", "jx-reed": "芦苇",
            "jx-boat": "孤舟", "jx-line": "钓丝", "jx-snow": "飘雪", "jx-anno": "画中物标注",
        },
        "layer_opacity": {},
        "js_layers": {"jx-snow": "snow"},
        "snow": {"count": 46, "dens": 0.85, "T": 19.578},
        "draft": {
            "jx-far":       {"fill": "#8A8578", "opacity": "0.18"},
            "jx-waterline": {"fill": "none", "stroke": "#8A8578", "sw": "1", "keep_opacity": True},
            "jx-path":      {"fill": "none", "stroke": "#8A8578", "opacity": "0.28"},
            "jx-reed":      {"fill": "none", "stroke": "#4A4640", "opacity": "0.42"},
            "jx-boat":      {"fill": "#1C1C1C", "opacity": "0.88"},
            "jx-line":      {"fill": "none", "stroke": "#1C1C1C", "sw": "1.1", "opacity": "0.55"},
            "jx-snow":      {"skip": True},
        },
        "overlay": "jx",
        "aria_ink": "江雪水墨静帧：淡墨远山、浓墨孤舟、大片留白、飘雪",
        "caption_ink": "笔墨渲染结果（静帧）。远山用纤维噪声扰动 + 高斯模糊模拟高含水晕染；"
                       "孤舟与翁用同一噪声但低模糊，保持笔锋；钓丝以飞白（噪声位移 + 断续）呈现；"
                       "飘雪为 JS 生成、按终态密度 0.85 静态复现。留白占 %g%%。"
                       "静帧几何冻结自动画 <code>#jx-cam</code>（<code>data/source/scene/jx.json</code>），与动画逐值一致。",
        "aria_draft": "江雪构图线稿：淡墨远山、大片留白、右下角孤舟与蓑笠翁",
        "caption_draft": "构图解算结果（线稿）。三分网格用于校验重心，地平线定在 0.42H 取平远。"
                         "留白区同时承载了「雪」「寒江」和两个负节点，留白占 %g%%。"
                         "线稿几何与静帧、动画共用同一份冻结场景（<code>data/source/scene/jx.json</code>）。",
    },
    "jys": {
        "name": "静夜思",
        "art": "art-sy", "cam": "sy-cam", "seal": "sy-seal",
        "grain": "syGrain", "anno": "sy-anno", "bare_default": None,
        "pipeline": "jingyesi_pipeline.html",
        "rho_spec": ("留白约束", 2, 0.78),
        "gravity_spec": (None, 2, (0.65, 0.69)),
        "labels": {
            "sy-night": "夜空", "sy-moon": "明月", "sy-cloud": "薄云", "sy-win": "窗棂",
            "sy-glint": "窗内月光", "sy-bed": "床前", "sy-frost": "地上霜",
            "sy-figure": "背影", "sy-anno": "画中物标注",
        },
        "layer_opacity": {
            "sy-night": "1", "sy-moon": "1", "sy-cloud": "0.9", "sy-win": "1",
            "sy-glint": "0.85", "sy-bed": "1", "sy-frost": "1", "sy-figure": "1",
        },
        "js_layers": {},
        "draft": {
            "sy-night":  {"skip": True},
            "sy-moon":   {"fill": "none", "stroke": "#3E5C76", "opacity": "0.9"},
            "sy-cloud":  {"fill": "none", "stroke": "#8A8578", "opacity": "0.5"},
            "sy-win":    {"fill": "none", "stroke": "#B08430", "opacity": "0.8", "dash": "7 5"},
            "sy-glint":  {"skip": True},
            "sy-bed":    {"fill": "none", "stroke": "#4A4640", "opacity": "0.5"},
            "sy-frost":  {"fill": "none", "stroke": "#8A8578", "opacity": "0.65", "dash": "5 5"},
            "sy-figure": {"fill": "#1C1C1C", "opacity": "0.9"},
        },
        "overlay": "jys",
        "aria_ink": "静夜思水墨静帧：夜空、明月与月晕、窗棂、床前月光、虚染的霜、浓墨背影",
        "caption_ink": "笔墨渲染结果（静帧）。夜空以「上浓下淡」的淡墨压暗，明月用两圈晕（半径 62 / 88），"
                       "圆心留纸色、边缘湿渲不闭合而「亮」；窗棂几笔立住「人在屋内」；霜以极淡墨湿渲、边缘不闭合（=「疑」）；"
                       "背影用整块浓墨剪影，仅以纸色线破开衣缝，人便从夜色里立出。留白占 %g%%。"
                       "静帧几何冻结自动画 <code>#sy-cam</code>（<code>data/source/scene/jys.json</code>），与动画逐值一致。",
        "aria_draft": "静夜思构图线稿：三层结构（天、窗与光、床前），明月为视觉焦点、背影为情感焦点，窗棂为 design 附加，大片留白",
        "caption_draft": "构图解算结果（线稿）。室内小景不设地平线、不用三远，改以「天 → 窗与光 → 床前」三层立骨；"
                         "明月定视觉焦点、背影定情感焦点；留白同时承载夜空与画面外的「故乡」——它唯一合法的渲染位置，留白占 %g%%。"
                         "线稿几何与静帧、动画共用同一份冻结场景（<code>data/source/scene/jys.json</code>）。",
    },
}


# ---------------------------------------------------------------- SVG 小工具
def attrs_of(s):
    return dict(ATTR_RE.findall(s))


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).strip()


def children(s):
    """按嵌套计数，逐个产出 s 的顶层元素 (tag, attrs_str, inner, raw)。"""
    i, n = 0, len(s)
    while i < n:
        m = TAG_RE.search(s, i)
        if not m:
            return
        closing, name, a, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:
            i = m.end()
            continue
        if selfclose or name.lower() in VOID:
            yield (name, a, "", m.group(0))
            i = m.end()
            continue
        depth, j, end = 1, m.end(), n
        while depth > 0:
            mm = TAG_RE.search(s, j)
            if not mm:
                end, j = n, n
                break
            if mm.group(1) == "/" and mm.group(2) == name:
                depth -= 1
            elif mm.group(1) == "" and mm.group(2) == name and not mm.group(4):
                depth += 1
            j = mm.end()
            if depth == 0:
                end = mm.start()
        yield (name, a, s[m.end():end], s[m.start():j])
        i = j


def collect_shapes(inner):
    """把一层里的绘制基元摊平：所有嵌套 <g> 递归展开（含带 id 的 <g>，
    如《静夜思》的背影内 sy-body / sy-head —— 其姿态 transform 即被丢弃，取基础位）。"""
    out = []
    for t, a, i, _ in children(inner):
        if t == "g":
            out.extend(collect_shapes(i))
        else:
            sh = {"tag": t, "attrs": attrs_of(a)}
            if t == "text":
                sh["text"] = strip_tags(i)
            out.append(sh)
    return out


def url_id(v):
    m = re.search(r"url\(#([^)]+)\)", v or "")
    return m.group(1) if m else None


def group_span(html, start):
    depth = 0
    for mm in re.finditer(r"<g\b|</g>", html[start:]):
        if mm.group(0) == "</g>":
            depth -= 1
            if depth == 0:
                return start + mm.start(), start + mm.end()
        else:
            depth += 1
    return start, len(html)


def rnd(seed):
    x = math.sin(seed * 127.1 + 311.7) * 43758.5453
    return x - math.floor(x)


# ---------------------------------------------------------------- JS 生成内容的静态复现
def synth_ripples(html, cfg):
    """复现《早发白帝城》里由 JS 生成的水纹，冻结在 t=0 相位（静帧）。"""
    m = re.search(r"var ROWS = \[([\s\S]*?)\];", html)
    if not m:
        raise SystemExit("✗ 未在动画 JS 中找到 ROWS（水纹行表）")
    rows = []
    for rm in re.finditer(r"\{([^}]*)\}", m.group(1)):
        kv = dict(re.findall(r"(\w+)\s*:\s*(-?[\d.]+)", rm.group(1)))
        rows.append({k: float(v) for k, v in kv.items()})
    shapes = []
    for ri, r in enumerate(rows):
        cx_row = 480 - (r["y"] - 302) * 28 / 298
        x0 = cx_row - r["span"] / 2
        segs = []
        for si in range(int(r["n"])):
            segs.append({
                "x": x0 + r["span"] * (si + rnd(ri * 29 + si * 13) * 0.52) / r["n"],
                "len": r["span"] * (0.26 + rnd(ri * 37 + si * 19) * 0.24) / r["n"],
                "dir": 1 if rnd(ri * 11 + si * 23) > 0.5 else -1,
                "ph": rnd(ri * 41 + si * 7) * 6.283,
            })
        ph = rnd(ri * 53) * 6.283
        y_now = r["y"] + math.sin(ph) * 3.2
        dep = max(0.0, min(1.0, (y_now - 300) / 300))
        sw = r["w"] * (0.82 + dep * 0.40)
        op = r["o"] * (0.55 + dep * 0.55)
        d = ""
        for sg in segs:
            amp = r["amp"] * (0.65 + 0.35 * math.sin(sg["ph"]))
            x1, x2 = sg["x"], sg["x"] + sg["len"]
            d += "M%.1f %.1f Q%.1f %.1f %.1f %.1f" % (
                x1, y_now, (x1 + x2) / 2, y_now + sg["dir"] * amp, x2, y_now)
        shapes.append({"tag": "path", "attrs": {
            "fill": "none", "stroke": "#3A362F", "stroke-linecap": "round",
            "stroke-width": "%.2f" % sw, "opacity": "%.3f" % op, "d": d}})
    return shapes


def synth_snow(html, cfg):
    """复现《江雪》里由 JS 生成的飘雪，冻结在终态（t=T，密度取 snowKeys 末值）。"""
    p = cfg["snow"]
    n, dens, T = p["count"], p["dens"], p["T"]
    out = []
    for i in range(n):
        x = 20 + rnd(i * 7 + 2) * 860
        y = rnd(i * 11 + 3) * 660
        vy = 22 * (0.65 + rnd(i * 13 + 4) * 0.85)
        ph = rnd(i * 17 + 5) * 6.283
        th = rnd(i * 19 + 6)
        y_raw = (y + vy * T) % 660
        a = max(0.0, min(1.0, (dens - th) / 0.14))
        if y_raw < 40:
            a *= y_raw / 40
        if y_raw > 600:
            a *= (660 - y_raw) / 60
        op = a * 0.42
        if op < 0.002:
            continue
        out.append({"tag": "circle", "attrs": {
            "fill": "#8A8578",
            "r": "%.2f" % (1.0 + rnd(i * 3 + 1) * 1.1),
            "cx": "%.1f" % (x + math.sin(T * 0.35 + ph) * 16),
            "cy": "%.1f" % (y_raw - 30),
            "opacity": "%.3f" % op}})
    return out


JS_HANDLERS = {"ripples": synth_ripples, "snow": synth_snow}


# ---------------------------------------------------------------- 抽取
def build_layer(at, inner, labels, clip=None):
    lid = at.get("id")
    return {
        "id": lid, "label": labels.get(lid, lid),
        "filter": url_id(at.get("filter")), "opacity": at.get("opacity"),
        "clip": clip, "shapes": collect_shapes(inner),
    }


def extract_scene(pid, cfg):
    html = open(ANIM, encoding="utf-8").read()
    svg_m = re.search(r'<svg\b[^>]*\bid="%s"[^>]*>' % cfg["art"], html)
    if not svg_m:
        raise SystemExit("✗ 未找到动画 %s" % cfg["art"])
    tail = html[svg_m.end():]
    dm = re.search(r"<defs>([\s\S]*?)</defs>", tail)
    defs = dm.group(1).strip() if dm else ""

    cam_m = re.search(r'<g\b[^>]*\bid="%s"[^>]*>' % cfg["cam"], tail)
    if not cam_m:
        raise SystemExit("✗ 未找到动画 %s" % cfg["cam"])
    cam_start = cam_m.end()
    cam_close, _ = group_span(tail, cam_m.start())
    inner = tail[cam_start:cam_close]

    labels = cfg["labels"]
    layers, bare = [], []

    def flush_bare():
        if not bare:
            return
        lid = next((a["id"] for _, a, _ in bare if a.get("id")), cfg["bare_default"])
        shapes = [{"tag": t, "attrs": {k: v for k, v in a.items() if k != "id"}}
                  for t, a, _ in bare]
        layers.append({"id": lid, "label": labels.get(lid, lid), "filter": None,
                       "opacity": None, "clip": None, "shapes": shapes})
        bare.clear()

    for t, a, i, _ in children(inner):
        at = attrs_of(a)
        if t == "g":
            flush_bare()
            if "clip-path" in at:
                clip = url_id(at["clip-path"])
                for t2, a2, i2, _ in children(i):
                    if t2 == "g":
                        layers.append(build_layer(attrs_of(a2), i2, labels, clip=clip))
            else:
                layers.append(build_layer(at, i, labels))
        else:
            bare.append((t, at, None))
    flush_bare()

    # 静止态修正：显隐取终态；描边取画完态；JS 生成内容静态复现
    for L in layers:
        if L["id"] in cfg["layer_opacity"]:
            L["opacity"] = cfg["layer_opacity"][L["id"]]
        for sh in L["shapes"]:
            if "stroke-dashoffset" in sh["attrs"]:
                sh["attrs"]["stroke-dashoffset"] = "0"
        if L["id"] in cfg["js_layers"]:
            L["shapes"] = JS_HANDLERS[cfg["js_layers"][L["id"]]](html, cfg)

    seal = None
    sm = re.search(r'<g\b[^>]*\bid="%s"[^>]*>' % cfg["seal"], tail)
    if sm:
        s_start, _ = group_span(tail, sm.start())
        sat = attrs_of(sm.group(0)[3:-1])
        sat["opacity"] = "1"                     # 终态可见
        seal = {"attrs": sat, "shapes": collect_shapes(tail[sm.end():s_start])}

    return {
        "meta": {
            "poem": cfg["name"], "pid": pid,
            "role": "场景几何单一真源（冻结自动画 #%s）：动画与全链路静帧/线稿皆由此渲染。" % cfg["cam"],
            "source": "dist/animation/ink_animations.html#%s" % cfg["cam"],
            "generated_by": "python build/scene_render.py --extract",
            "rest_state": "相机 identity；各层显隐取终态；JS 变换（漂移/振荡/姿态）取基础位；"
                          "描边取画完态（dashoffset=0）；JS 生成内容（水纹 t=0 相位 / 飘雪终态）静态复现。",
            "note": "本文件由 --extract 从动画抽取，勿手改；改场景请改动画后重抽再 --write。",
        },
        "viewBox": [0, 0, 900, 600],
        "paper": "#F6F3EC",
        "defs": defs,
        "layers": layers,
        "seal": seal,
    }


# ---------------------------------------------------------------- 渲染
def svg_attrs(a):
    return "".join(' %s="%s"' % (k, v) for k, v in a.items())


def shape_svg(sh):
    tag, a = sh["tag"], sh["attrs"]
    if tag == "text":
        return "<text%s>%s</text>" % (svg_attrs(a), sh.get("text", ""))
    return "<%s%s/>" % (tag, svg_attrs(a))


def layer_open(L):
    a = []
    if L.get("id"):
        a.append('id="%s"' % L["id"])
    if L.get("filter"):
        a.append('filter="url(#%s)"' % L["filter"])
    if L.get("clip"):
        a.append('clip-path="url(#%s)"' % L["clip"])
    if L.get("opacity") not in (None, "1"):
        a.append('opacity="%s"' % L["opacity"])
    return "<g %s>" % " ".join(a) if a else "<g>"


def seal_svg(sc, indent):
    if not sc.get("seal"):
        return ""
    sp = " " * indent
    out = [sp + "<!-- 印章 -->", sp + "<g%s>" % svg_attrs(sc["seal"]["attrs"])]
    for sh in sc["seal"]["shapes"]:
        out.append(sp + "  " + shape_svg(sh))
    out.append(sp + "</g>")
    return "\n".join(out)


def render_ink(sc, rho, cfg):
    vb = sc["viewBox"]
    o = ['      <svg viewBox="%d %d %d %d" role="img" aria-label="%s">'
         % (vb[0], vb[1], vb[2], vb[3], cfg["aria_ink"])]
    o.append("        <defs>")
    for line in textwrap.dedent("\n" + sc["defs"]).splitlines():
        o.append(("          " + line).rstrip())
    o.append("        </defs>")
    o.append('        <rect x="0" y="0" width="%d" height="%d" fill="%s"/>' % (vb[2], vb[3], sc["paper"]))
    o.append('        <rect x="0" y="0" width="%d" height="%d" filter="url(#%s)" opacity="0.055"/>'
             % (vb[2], vb[3], cfg["grain"]))
    o.append('        <g id="%s">' % cfg["cam"])
    for L in sc["layers"]:
        if L["id"] == cfg["anno"]:
            continue
        o.append("          <!-- %s -->" % L["label"])
        o.append("          " + layer_open(L))
        for sh in L["shapes"]:
            o.append("            " + shape_svg(sh))
        o.append("          </g>")
    o.append("        </g>")
    seal = seal_svg(sc, 8)
    if seal:
        o.append(seal)
    o.append("      </svg>")
    o.append("      <figcaption>%s</figcaption>" % (cfg["caption_ink"] % rho))
    return "\n".join(o)


def shape_svg_draft(sh, st):
    src = sh["attrs"]
    a = {k: src[k] for k in GEO if k in src}
    a["fill"] = st.get("fill", "none")
    stroke = st.get("stroke") or src.get("stroke")
    if stroke:
        a["stroke"] = stroke
    if "stroke-width" in src:
        a["stroke-width"] = src["stroke-width"]
    elif st.get("sw"):
        a["stroke-width"] = st["sw"]
    if "stroke-linecap" in src:
        a["stroke-linecap"] = src["stroke-linecap"]
    if st.get("dash"):
        a["stroke-dasharray"] = st["dash"]
    if st.get("keep_opacity") and "opacity" in src:
        a["opacity"] = src["opacity"]
    tag = sh["tag"]
    if tag == "text":
        return "<text%s>%s</text>" % (svg_attrs(a), sh.get("text", ""))
    return "<%s%s/>" % (tag, svg_attrs(a))


def _line_inter(p1, p2, p3, p4):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return (px, py)


def vanishing_point(sc, layer_id):
    """由江水楔形两侧内缘延长求消失点（几何自洽，不另设常数）。"""
    river = next((L for L in sc["layers"] if L["id"] == layer_id), None)
    if not river or not river["shapes"]:
        return None
    d = river["shapes"][0]["attrs"].get("d", "")
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    pts = list(zip(nums[0::2], nums[1::2]))
    bot = [p for p in pts if abs(p[1] - 600) < 1e-6]
    top = [p for p in pts if abs(p[1] - 302) < 1e-6]
    if len(bot) < 2 or len(top) < 2:
        return None
    bl, br = min(bot, key=lambda p: p[0]), max(bot, key=lambda p: p[0])
    tl, tr = min(top, key=lambda p: p[0]), max(top, key=lambda p: p[0])
    return _line_inter(bl, tl, br, tr)


def anno_svg(sc, cfg, indent=8):
    anno = next((L for L in sc["layers"] if L["id"] == cfg["anno"]), None)
    if not anno:
        return []
    sp = " " * indent
    o = [sp + "<!-- 画中物标注（锚点取自动画 #%s） -->" % cfg["anno"], sp + "<g>"]
    for sh in anno["shapes"]:
        t, src = sh["tag"], sh["attrs"]
        if t == "line":
            o.append('%s  <line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#3E5C76" stroke-width="1" opacity="0.55"/>'
                     % (sp, src.get("x1"), src.get("y1"), src.get("x2"), src.get("y2")))
        elif t == "circle":
            o.append('%s  <circle cx="%s" cy="%s" r="%s" fill="#3E5C76" opacity="0.55"/>'
                     % (sp, src.get("cx"), src.get("cy"), src.get("r")))
        elif t == "text":
            anchor = ' text-anchor="%s"' % src["text-anchor"] if "text-anchor" in src else ""
            o.append('%s  <text x="%s" y="%s"%s fill="#3E5C76" font-size="12" '
                     'font-family="PingFang SC, sans-serif">%s</text>'
                     % (sp, src.get("x"), src.get("y"), anchor, sh.get("text", "")))
    o.append(sp + "</g>")
    return o


def gravity_svg(gravity, anchor, indent=8):
    gx, gy = gravity[0] * 900, gravity[1] * 600
    sp = " " * indent
    return [
        sp + "<!-- 视觉重心 -->",
        sp + '<circle cx="%.0f" cy="%.0f" r="4" fill="none" stroke="#A83A2C" stroke-width="1.5"/>' % (gx, gy),
        sp + '<line x1="%.0f" y1="%.0f" x2="%d" y2="%d" stroke="#A83A2C" stroke-width="1" stroke-dasharray="4 4"/>'
        % (gx, gy, anchor[0], anchor[1]),
        sp + '<text x="%d" y="%d" font-size="12" fill="#A83A2C" font-family="PingFang SC, sans-serif">视觉重心 (%.2f, %.2f)</text>'
        % (anchor[0] + 4, anchor[1] + 4, gravity[0], gravity[1]),
    ]


def overlay_bd(sc, rho, gravity):
    sp = " " * 8
    o = []
    vp = vanishing_point(sc, "bd-river")
    if vp:
        vx, vy = vp
        o.append(sp + "<!-- 消失点：江水两侧内缘延长交点 -->")
        o.append(sp + '<circle cx="%.1f" cy="%.1f" r="3.5" fill="none" stroke="#B08430" stroke-width="1.5"/>' % (vx, vy))
        o.append(sp + '<line x1="%.1f" y1="%.1f" x2="640" y2="256" stroke="#B08430" stroke-width="1" stroke-dasharray="4 4"/>' % (vx, vy))
        o.append(sp + '<text x="646" y="252" font-size="12" fill="#B08430" font-family="PingFang SC, sans-serif">消失点 · 两岸内缘延长交点</text>')
    o += gravity_svg(gravity, (470, 440))
    o.append(sp + "<!-- 留白标注 -->")
    o.append(sp + '<text x="452" y="182" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">留白区 ρ = %g</text>' % rho)
    o.append(sp + '<text x="452" y="200" font-size="11" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">（彩云 + 江水 + 峡中雾）</text>')
    return o


def overlay_jx(sc, rho, gravity):
    sp = " " * 8
    o = [
        sp + "<!-- 地平线（平远 0.42H） -->",
        sp + '<line x1="0" y1="252" x2="900" y2="252" stroke="rgba(62,92,118,.30)" stroke-width="1" stroke-dasharray="6 5"/>',
        sp + '<text x="14" y="246" font-size="12" fill="#3E5C76" font-family="PingFang SC, sans-serif">地平线 0.42H</text>',
    ]
    o += gravity_svg(gravity, (700, 352))
    o.append(sp + "<!-- 留白标注 -->")
    o.append(sp + '<text x="340" y="380" font-size="13" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">留白区 ρ = %g</text>' % rho)
    o.append(sp + '<text x="340" y="400" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">（寒江 + 雪 + 飞绝的鸟 + 灭掉的人踪）</text>')
    return o


def overlay_jys(sc, rho, gravity):
    sp = " " * 8
    o = [
        sp + "<!-- 三层结构（室内小景，不设地平线、不用三远） -->",
        sp + '<g stroke="rgba(138,133,120,.5)" stroke-width="1" stroke-dasharray="6 5">',
        sp + '  <line x1="0" y1="140" x2="900" y2="140"/>',
        sp + '  <line x1="0" y1="330" x2="900" y2="330"/>',
        sp + '  <line x1="0" y1="486" x2="900" y2="486"/>',
        sp + '</g>',
        sp + '<text x="14" y="134" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif">远景层 · 天（夜空 + 明月）</text>',
        sp + '<text x="14" y="324" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif">中景层 · 窗与光</text>',
        sp + '<text x="14" y="480" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif">近景层 · 床前</text>',
        sp + "<!-- 焦点：明月（视觉） / 背影（情感） -->",
        sp + '<circle cx="660" cy="185" r="60" fill="none" stroke="#3E5C76" stroke-width="1.4" stroke-dasharray="4 4"/>',
        sp + '<text x="660" y="112" font-size="12.5" fill="#3E5C76" font-family="PingFang SC, sans-serif" text-anchor="middle">明月 · 视觉焦点</text>',
        sp + '<circle cx="400" cy="420" r="54" fill="none" stroke="#A83A2C" stroke-width="1.4" stroke-dasharray="4 4"/>',
        sp + '<text x="400" y="352" font-size="12.5" fill="#A83A2C" font-family="PingFang SC, sans-serif" text-anchor="middle">背影 · 情感焦点</text>',
    ]
    o += gravity_svg(gravity, (700, 352))
    o.append(sp + "<!-- 留白标注 -->")
    o.append(sp + '<text x="205" y="252" font-size="13" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">留白区 ρ = %g</text>' % rho)
    o.append(sp + '<text x="205" y="272" font-size="12" fill="#8A8578" font-family="PingFang SC, sans-serif" text-anchor="middle">（夜空 + 月光未照到的地面 + 画面外的「故乡」）</text>')
    return o


OVERLAYS = {"bd": overlay_bd, "jx": overlay_jx, "jys": overlay_jys}


def render_draft(sc, rho, gravity, cfg):
    vb = sc["viewBox"]
    o = ['      <svg viewBox="%d %d %d %d" role="img" aria-label="%s">'
         % (vb[0], vb[1], vb[2], vb[3], cfg["aria_draft"])]
    o.append('        <rect x="0" y="0" width="%d" height="%d" fill="%s"/>' % (vb[2], vb[3], sc["paper"]))
    o.append("        <!-- 三分网格 -->")
    o.append('        <g stroke="rgba(28,28,28,.07)" stroke-width="1">')
    for x in (300, 600):
        o.append('          <line x1="%d" y1="0" x2="%d" y2="600"/>' % (x, x))
    for y in (200, 400):
        o.append('          <line x1="0" y1="%d" x2="900" y2="%d"/>' % (y, y))
    o.append("        </g>")

    for L in sc["layers"]:
        if L["id"] == cfg["anno"]:
            continue
        st = cfg["draft"].get(L["id"])
        if not st or st.get("skip"):
            continue
        a = []
        if L.get("clip"):
            a.append('clip-path="url(#%s)"' % L["clip"])
        if st.get("opacity") is not None:
            a.append('opacity="%s"' % st["opacity"])
        o.append("        <!-- %s -->" % L["label"])
        o.append("        <g%s>" % ((" " + " ".join(a)) if a else ""))
        for sh in L["shapes"]:
            o.append("          " + shape_svg_draft(sh, st))
        o.append("        </g>")

    o += OVERLAYS[cfg["overlay"]](sc, rho, gravity)
    o += anno_svg(sc, cfg)
    seal = seal_svg(sc, 8)
    if seal:
        o.append(seal)
    o.append("      </svg>")
    o.append("      <figcaption>%s</figcaption>" % (cfg["caption_draft"] % rho))
    return "\n".join(o)


# ---------------------------------------------------------------- 注入 / 校验
def replace_block(html, pid, key, content):
    b = "<!-- SCENE:%s:%s:begin -->" % (pid, key)
    e = "<!-- SCENE:%s:%s:end -->" % (pid, key)
    if b not in html or e not in html:
        raise SystemExit("✗ pipeline 缺标记 %s / %s" % (b, e))
    pat = re.compile(re.escape(b) + r".*?" + re.escape(e), re.S)
    return pat.sub(lambda m: b + "\n" + content + "\n" + e, html, count=1)


TR_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.S)
TD_RE = re.compile(r"<td(\s[^>]*)?>(.*?)</td>", re.S)


def _cell(row, idx):
    tds = TD_RE.findall(row)
    return strip_tags(tds[idx][1]) if idx < len(tds) else ""


def step5_numbers(html, cfg):
    """ρ 与视觉重心取自 pipeline 表格（单一出处），供线稿标注同步。"""
    rho_row, rho_col, rho_def = cfg["rho_spec"]
    g_row, g_col, g_def = cfg["gravity_spec"]
    rho, gravity = rho_def, g_def
    for m in TR_RE.finditer(html):
        row = m.group(0)
        label = _cell(row, 0)
        if label == rho_row:
            try:
                rho = float(_cell(row, rho_col))
            except ValueError:
                pass
        elif g_row and label == g_row:
            g = re.findall(r"-?\d+(?:\.\d+)?", _cell(row, g_col))
            if len(g) >= 2:
                gravity = (float(g[0]), float(g[1]))
    return rho, gravity


def scene_path(pid):
    return os.path.join(SCENE_DIR, "%s.json" % pid)


def load_scene(pid):
    with open(scene_path(pid), encoding="utf-8") as f:
        return json.load(f)


def do_extract(poems):
    os.makedirs(SCENE_DIR, exist_ok=True)
    for pid in poems:
        cfg = POEMS[pid]
        sc = extract_scene(pid, cfg)
        with open(scene_path(pid), "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=1)
        n = sum(len(L["shapes"]) for L in sc["layers"])
        print("  ✓ 已冻结场景 %s（%d 层 / %d 基元）"
              % (os.path.relpath(scene_path(pid), ROOT), len(sc["layers"]), n))


def do_write(poems):
    for pid in poems:
        cfg = POEMS[pid]
        sc = load_scene(pid)
        path = os.path.join(ROOT, "dist", "pipelines", cfg["pipeline"])
        html = open(path, encoding="utf-8").read()
        rho, gravity = step5_numbers(html, cfg)
        html = replace_block(html, pid, "draft", render_draft(sc, rho, gravity, cfg))
        html = replace_block(html, pid, "ink", render_ink(sc, rho, cfg))
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print("  ✓ 已重渲 %s（STEP5 线稿 + STEP6 静帧，ρ=%g）"
              % (os.path.relpath(path, ROOT), rho))


def _diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s.%s 仅 B 有" % (path, k))
            elif k not in b:
                out.append("%s.%s 仅 A 有" % (path, k))
            else:
                out += _diff(a[k], b[k], "%s.%s" % (path, k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s 长度 %d↔%d" % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, "%s[%d]" % (path, i))
    elif a != b:
        out.append("%s %s ↔ %s" % (path, a, b))
    return out


def do_check(poems):
    print("── 场景几何（动画 ↔ scene/<pid>.json ↔ 全链路）")
    fails = 0
    for pid in poems:
        cfg = POEMS[pid]
        path = os.path.join(ROOT, "dist", "pipelines", cfg["pipeline"])
        print("  [%s] %s" % (pid, cfg["name"]))
        try:
            fresh = extract_scene(pid, cfg)
            cur = load_scene(pid)
        except SystemExit as e:
            fails += 1
            print("    ✗ %s" % e)
            continue
        if fresh == cur:
            print("    ✓ %s.json 与动画 #%s 一致（现抽 = 冻结）" % (pid, cfg["cam"]))
        else:
            fails += 1
            print("    ✗ %s.json 与动画漂移（跑 --extract 重新冻结）：" % pid)
            for line in _diff(cur, fresh)[:12]:
                print("        " + line)

        html = open(path, encoding="utf-8").read()
        rho, gravity = step5_numbers(html, cfg)
        expected = replace_block(html, pid, "draft", render_draft(cur, rho, gravity, cfg))
        expected = replace_block(expected, pid, "ink", render_ink(cur, rho, cfg))
        if expected == html:
            print("    ✓ 全链路 STEP5/STEP6 与 %s.json 一致（重渲 = 落盘）" % pid)
        else:
            fails += 1
            print("    ✗ 全链路 STEP5/STEP6 与 %s.json 漂移（跑 --write 重渲）" % pid)

    if fails:
        print("  ✗ 场景几何三方不一致（%d 项）" % fails)
    else:
        print("  ✓ 动画 ↔ 场景数据 ↔ 全链路 三方几何一致（%d 首）" % len(poems))
    return fails


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--extract", action="store_true", help="从动画抽取场景，冻结为 <pid>.json")
    g.add_argument("--write", action="store_true", help="由 <pid>.json 渲染并注入 pipeline")
    g.add_argument("--check", action="store_true", help="校验三方几何一致")
    ap.add_argument("--poem", choices=ORDER, help="只处理一首（默认三首）")
    args = ap.parse_args()

    poems = [args.poem] if args.poem else ORDER
    if args.extract:
        print("[场景几何] 抽取")
        do_extract(poems)
    elif args.write:
        print("[场景几何] 渲染注入")
        do_write(poems)
    else:
        sys.exit(1 if do_check(poems) else 0)


if __name__ == "__main__":
    main()
