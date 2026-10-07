# -*- coding: utf-8 -*-
"""
D2 解析器 + 回归校验

用法：
    python src/d2/d2_resolve.py                 # 跑三首回归，写 d2_regression.json
    python src/d2/d2_resolve.py --poem jx       # 只看一首的解析结果
    python src/d2/d2_resolve.py --word 孤舟      # 看一个意象词的画法束

接口：
    classify(t, word, head=None)         词 → 意象类别
    resolve_node(t, node, ctx)           节点 → 画法束
    resolve_poem(t, pid, imagery, ctx)   全诗 → 三远/皴法/留白区间/形制/静息

分工：D2 给「候选集 + 类别档 + 区间约束」；精确数值由卡5/卡6 求解。
"""
import argparse
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")


# ---------------------------------------------------------------- 诗级上下文
# V/A/T 取自 model_cards.md（江雪）与三首 pipeline.html（实跑值）
POEM_CTX = {
    "jx": {
        "title": "江雪",
        "form": "五言绝句",
        "V": [-0.42, -0.55, -0.35, -0.48],
        "A": [0.22, 0.18, 0.46, 0.71],
        "T": [0.30, 0.38, 0.72, 0.95],
        "polarity": ["孤傲·隐逸（非凄惨）"],
        "text": "千山鸟飞绝|万径人踪灭|孤舟蓑笠翁|独钓寒江雪",
    },
    "bd": {
        "title": "早发白帝城",
        "form": "七言绝句",
        "V": [0.62, 0.78, 0.58, 0.93],
        "A": [0.50, 0.70, 0.86, 0.96],
        "T": [0.35, 0.58, 0.86, 0.74],
        "polarity": ["中性（化用地理典故）", "悲声（文化代码）"],
        "text": "朝辞白帝彩云间|千里江陵一日还|两岸猿声啼不住|轻舟已过万重山",
    },
    "jys": {
        "title": "静夜思",
        "form": "五言绝句",
        "V": [0.10, -0.05, 0.20, -0.25],
        "A": [0.20, 0.35, 0.55, 0.18],
        "T": [0.25, 0.35, 0.30, 0.60],
        "polarity": ["中性（思乡母题）"],
        "text": "床前明月光|疑是地上霜|举头望明月|低头思故乡",
    },
}

# 回归目标（来自三首 pipeline 的实跑值 / 硬约束）
# 注：jx/bd 的意象节点取自 o2_imagery.json；jys 未进 O2，用下方 JYS_FIXTURE
#     （节点口径来自 jingyesi_pipeline.html STEP 2 表）。
REGRESSION_TARGETS = {
    "jx": {
        "yuan": ["平远", "深远"],
        "cun": ["无皴"],
        "rho": 0.79,
        "rho_range": [0.72, 0.85],
        "ink_order": [["孤舟", "千山"], ["蓑笠翁", "千山"], ["孤舟", "独钓"]],
        "ink_void": ["雪", "寒江"],
        "neg_no_paint": ["鸟", "人踪"],
        "figure_size": [["蓑笠翁", "点景"]],
        "polarity_keys": ["隐逸·渔樵", "孤守·不屈"],
        "paradigm": "水墨",
        "viewpoint": "平视",
        "weather": "雪",
        "time_of_day": None,
        "composition": "截断",
        "seal_size": "小幅",
        "seal_format": "册页",
    },
    "bd": {
        "yuan": ["高远", "深远"],
        "cun": ["大斧劈", "小斧劈"],
        "rho": 0.52,
        "rho_range": [0.45, 0.58],
        "ink_order": [["轻舟", "两岸"], ["两岸", "彩云"], ["轻舟", "万重山"]],
        "ink_void": [],
        "neg_no_paint": [],
        "polarity_keys": ["高峻·起点", "轻快·自由", "冷寂·静"],
        "paradigm": "浅绛",
        "viewpoint": "仰视",
        "weather": None,
        "time_of_day": "晨",
        "composition": "险峻",
        "seal_size": "大幅",
        "seal_format": "手卷",
    },
    "jys": {
        "yuan": [],              # 室内小景，三远不适用
        "cun": [],
        "rho": 0.78,
        "rho_range": [0.72, 0.85],
        # 床 c=0.55 与 明月 c=0.40 同属淡阶，墨阶排序无法用「档」区分，
        # 精确关系由 d2_compare.py 按实测 c 校验；此处只留可判的跨档比较。
        "ink_order": [["床", "霜"]],
        "ink_void": [],          # 霜已由「纯留白」改判「虚染」（对齐 pipeline c=0.10 实写）
        "neg_no_paint": [],
        "polarity_keys": ["漂泊·孤立"],
        "paradigm": "水墨",
        "viewpoint": None,
        "weather": None,
        "time_of_day": "夜",
        "composition": "借景",
        "seal_size": "小幅",
        "seal_format": "册页",
    },
}

# 静夜思意象夹具（jingyesi_pipeline.html STEP 2 表；O2 尚未覆盖 jys）
JYS_FIXTURE = {
    "title": "静夜思",
    "author": "李白",
    "nodes": [
        {"id": "jys-1-1", "surface": "床", "channel": "v", "conc": 0.80, "neg_kind": None,
         "layer_hint": "近景", "e": {"head": "床", "pos": "n"}, "gate": {"class": "实写"}},
        {"id": "jys-1-3", "surface": "明月", "channel": "v", "conc": 0.90, "neg_kind": None,
         "layer_hint": "远景", "e": {"head": "月", "pos": "n"}, "gate": {"class": "实写"}},
        {"id": "jys-2-3", "surface": "霜", "channel": "v", "conc": 0.35, "neg_kind": None,
         "layer_hint": "近景", "e": {"head": "霜", "pos": "n"}, "gate": {"class": "虚写（比喻——月光被疑为霜，非真有霜）"}},
        {"id": "jys-4-4", "surface": "故乡", "channel": "x", "conc": 0.10, "neg_kind": None,
         "layer_hint": "画面外", "e": {"head": "乡", "pos": "n"}, "gate": {"class": "不可实写（情感对象，不在画面）"}},
    ],
}

VOID_ROLES = {"不画", "承载留白"}
PIVOT_ROLES = {"焦点"}


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 分类
def classify(t, word, head=None):
    """词 → 意象类别。优先级：word_class > head > 末字 > None"""
    if word in t["word_class"]:
        return t["word_class"][word], "word_class"
    if head and head in t["head_class"]:
        return t["head_class"][head], "head"
    for ch in reversed(word):
        if ch in t["head_class"]:
            return t["head_class"][ch], "tail-char"
    return None, "unresolved"


# ---------------------------------------------------------------- 极性归一（G12）
def norm_polarity(t, raw):
    """自由文本极性标签 → 规范键。命中 normalize 或本身即规范键；否则 None（登记为未归一）。"""
    if raw is None:
        return None
    pol = t["modulators"]["polarity"]
    if raw in pol["normalize"]:
        return pol["normalize"][raw]
    if raw in pol["keys"]:
        return raw
    return None


def is_carrier(node):
    """诗级极性的承载词：焦点词 / 动作词（全诗骨相的落点）。"""
    e = node.get("e") or {}
    gate_cls = (node.get("gate") or {}).get("class", "")
    return bool(node.get("focus")) or bool(e.get("action")) or gate_cls.startswith("动作")


# ---------------------------------------------------------------- 墨阶
def ink_shift(ladder, grade, steps):
    if grade == "留白":
        return "留白"
    i = ladder.index(grade)
    j = max(0, min(i + steps, len(ladder) - 1))
    return ladder[j]


def ink_c(t, grade):
    return t["vocab"]["ink"][grade]["c"]


def ink_rank(ladder, grade):
    """墨阶排序：越小越深。留白比清更淡，排在梯度之外。"""
    return len(ladder) if grade == "留白" else ladder.index(grade)


# ---------------------------------------------------------------- 节点解析
def resolve_node(t, node, ctx):
    word = node["surface"]
    cls, how = classify(t, word, node.get("e", {}).get("head"))
    d = dict(t["class_defaults"].get(cls, t["class_defaults"]["非画"]))
    ov = dict(t["word_override"].get(word, {}))
    note = ov.pop("note", None)
    ov_role = ov.get("role")          # 词级角色优先（如 虚染 覆盖 虚写→承载留白）
    for k, v in ov.items():
        d[k] = v

    gate = (node.get("gate") or {}).get("class", "")
    neg = bool(node.get("neg_kind")) or gate.startswith("不画")

    role = d["role"]
    if neg:
        role = "不画"
    elif ov_role is None and gate.startswith("虚写"):
        role = "承载留白"
    elif ov_role is None and gate.startswith("动作"):
        role = "点缀" if d["role"] != "焦点" else "焦点"

    layer = node.get("layer_hint") or d["layer"]

    # 调制器 layer_technique：按「类别 × 层」给含水/笔法（远山细化的泛化）。
    # 词覆盖优先——已被 word_override 显式指定的键不被调制器覆盖。
    lt = t["modulators"].get("layer_technique", {}).get(cls, {}).get(layer, {})
    for k, v in lt.items():
        if k not in ov:
            d[k] = v

    # 调制器 figure_layer：郭熙「三远与人物」——景深 → 人物尺寸档/墨阶（与 layer_technique 并列）。
    # 词覆盖优先；§5 护栏：中号档仅当角色=主体（全诗唯一实体与动作主体）时生效，否则退回点景档。
    if cls == "人物":
        fl = t["modulators"].get("figure_layer", {}).get(layer, {})
        if "size" not in ov:
            d["size"] = fl.get("size", t["modulators"]["figure_layer"].get("default", "点景"))
        if d["size"] == "中号" and role != "主体":
            d["size"] = "点景"

    if role in VOID_ROLES:
        ink_grade = "留白"
        stroke = "不画"
    else:
        base = d["ink_grade"]
        if role in PIVOT_ROLES:
            steps = 0                                   # R4：焦点不随层/情感变淡，保对比
        else:
            if cls == "人物":
                # figure_layer：景深 → 人物墨阶衰减（郭熙三远与人物），替换通用层衰减，避免双重衰减
                steps = t["modulators"].get("figure_layer", {}).get(layer, {}).get(
                    "ink_steps", t["modulators"]["layer_atten_steps"].get(layer, 0))
            else:
                steps = t["modulators"]["layer_atten_steps"].get(layer, 0)
            # R8：基阶=清 不参与情感位移
            if base != "清" and role in t["modulators"]["emotion"]["ink_shift_roles"]:
                steps += ctx["ink_steps"]
        ink_grade = ink_shift(t["vocab"]["ink_ladder"], base, steps)
        stroke = d["stroke"]

    return {
        "surface": word,
        "class": cls,
        "class_by": how,
        "role": role,
        "yuan_candidates": d.get("yuan", []),
        "cun": d["cun"],
        "ink_grade": ink_grade,
        "ink_c_range": t["vocab"]["ink"][ink_grade]["c"],
        "water": d["water"],
        "stroke": stroke,
        "layer": layer,
        "weight": d.get("weight", 1.0),
        "diantai": bool(d.get("diantai")) and not neg and role not in VOID_ROLES,
        "size": d.get("size") if cls == "人物" and role not in VOID_ROLES else None,
        "polarity_hint": node.get("polarity_hint"),
        "polarity_key": norm_polarity(t, node.get("polarity_hint")),
        "override": note,
    }


# ---------------------------------------------------------------- 诗级解析
def pick_band(bands, value):
    for b in bands:
        lo, hi = b["range"]
        if lo <= value < hi:
            return b
    return bands[-1] if value >= bands[-1]["range"][0] else bands[0]


# ---------------------------------------------------------------- 设色范式（G3 · B 组）
def resolve_paradigm(t, ctx0, vband, p_keys, season, base_tone):
    """设色范式定档：品格 / 季节 / 极性 → 范式候选 + 默认档 + 色域投影。

    D2 只给候选与色域（改写 A 组底色候选），精确用色由卡6 求解（分工铁律）。
    定档规则（P1/P2/P3）为工程裁定——品格闭环 style_grade（D 组）未建，暂以季节 / 极性 / 情感档代偿。
    """
    pgm = t["modulators"]["paradigm"]
    items = t["vocab"]["paradigm"]
    text = ctx0["text"]
    fired = []

    def fire(p, rid):
        if p not in [x[0] for x in fired]:
            fired.append((p, rid))

    # P1 青绿：重彩信号词 或 春/夏（北宗着色山水）
    if any(sig in text for sig in pgm["color_signal"]) or season in ("春", "夏"):
        fire("青绿", "P1")
    # P2 浅绛：极性含 明丽·祥瑞 / 轻快·自由（暖调淡彩）
    if {"明丽·祥瑞", "轻快·自由"} & set(p_keys):
        fire("浅绛", "P2")
    # P3 水墨：V∈{V1,V2} 或 冬（南宗渲淡）
    if vband["band"] in ("V1", "V2") or season == "冬":
        fire("水墨", "P3")

    default = fired[0][0] if fired else pgm["default"]
    candidates = [p for p, _ in fired]
    if pgm["default"] not in candidates:
        candidates.append(pgm["default"])

    proj = pgm["color_projection"][default]
    if proj["mode"] == "保持":
        projected = list(base_tone["color_candidates"])
    else:
        projected = list(items[default]["color_domain"])

    return {
        "default": default,
        "candidates": candidates,
        "ink_bone": items[default]["ink_bone"],
        "ink_bone_scale": proj["ink_bone_scale"],
        "color_domain": items[default]["color_domain"],
        "projection_mode": proj["mode"],
        "projected_color_candidates": projected,
        "rules_fired": [rid for _, rid in fired],
        "evidence": {rid: p for p, rid in fired},
    }


# ---------------------------------------------------------------- C 组·新算子（G1/G2/G4/G5/G6/G7/G8）
def resolve_viewpoint(t, text, yuan, has_landscape):
    """视点档（G7）：空间词 + 三远 → 视点票。三远不适用（室内小景）时视点亦不适用。"""
    vpm = t["modulators"]["viewpoint"]
    vp = t["vocab"]["viewpoint"]
    if not has_landscape:
        return {"applicable": False, "default": None, "candidates": [], "votes": {},
                "horizon": None, "vertical_scale": None,
                "note": "三远不适用（室内小景）→ 视点亦不适用"}
    votes = {}
    for w, view in vpm["words"].items():
        if w in text:
            votes[view] = votes.get(view, 0.0) + vpm["word_w"]
    for y in yuan:
        v = vpm["from_yuan"].get(y)
        if v:
            votes[v] = votes.get(v, 0.0) + vpm["yuan_w"]
    if votes:
        best = max(votes.values())
        top = [v for v, s in votes.items() if s == best]
        chosen = vpm["default"] if vpm["default"] in top else sorted(top)[0]
    else:
        chosen = vpm["default"]
    candidates = [v for v, _ in sorted(votes.items(), key=lambda kv: -kv[1])]
    if chosen not in candidates:
        candidates.append(chosen)
    p = vp[chosen]["params"]
    return {"applicable": True, "default": chosen, "candidates": candidates,
            "votes": {k: round(v, 2) for k, v in votes.items()},
            "horizon": p["horizon"], "vertical_scale": p["vertical_scale"],
            "criterion": vp[chosen]["criterion"]}


def resolve_weather(t, text):
    """天候档（G4）：天候词 → 天候档 + 卡5/卡6 系数。未命中则 null（系数中性）。"""
    wxm = t["modulators"]["weather"]
    wx = t["vocab"]["weather"]
    hit = [w for w in wxm["words"] if w in text]
    if not hit:
        return {"name": None, "sigma_mult": [1.0, 1.0], "blank_bonus": 0.0,
                "mu_mult": [1.0, 1.0], "cun_bias": [], "hit": [],
                "note": "未命中天候词 → 不定档，系数中性"}
    name = wxm["words"][hit[0]]
    d = wx[name]
    return {"name": name, "sigma_mult": d["sigma_mult"], "blank_bonus": d["blank_bonus"],
            "mu_mult": d["mu_mult"], "cun_bias": d["cun_bias"], "quality": d["quality"],
            "hit": hit, "source_id": d["source_id"]}


def resolve_time_of_day(t, text):
    """时辰档（G5）：时辰词 → 时辰档 + 段长乘子 / 墨色候选。未命中则 null。"""
    tw = t["modulators"]["time_words"]
    tod = t["vocab"]["time_of_day"]
    hit = [w for w in tw["map"] if w in text]
    if not hit:
        return {"name": None, "seg_len_mult": [1.0, 1.0], "ink_bias": 0,
                "color": None, "warmth": 0, "hit": [],
                "note": "未命中时辰词 → 不定档，段长乘子中性"}
    name = tw["map"][hit[0]]
    d = tod[name]
    return {"name": name, "seg_len_mult": d["seg_len_mult"], "ink_bias": d["ink_bias"],
            "color": d["color"], "warmth": d["warmth"], "qi": d["qi"],
            "hit": hit, "source_id": d["source_id"]}


def resolve_material(t):
    """材质系数（G6）：取默认档（诗中无依据）→ 卡6 扩散 / 飞白乘子。"""
    mm = t["modulators"]["material"]
    mat = t["vocab"]["material"]
    dflt = mm["default"]
    return {
        "choice": dflt,
        "paper": mat["纸绢"][dflt["纸绢"]],
        "brush": mat["笔"][dflt["笔"]],
        "ink": mat["墨"][dflt["墨"]],
        "note": mm["note"],
    }


def resolve_stroke_quality(t, bundles):
    """笔法质量维（G2）：诗用到的笔法式 → 适用质量维（正向）/ 须避病（负向）。"""
    by = t["modulators"]["stroke_quality"]["by_stroke"]
    used, quality, avoid = [], [], []
    for b in bundles:
        s = b.get("stroke")
        if s in by and s not in used:
            used.append(s)
            for q in by[s]["quality"]:
                if q not in quality:
                    quality.append(q)
            for q in by[s]["avoid"]:
                if q not in avoid:
                    avoid.append(q)
    return {"strokes": used, "quality": quality, "avoid": avoid,
            "note": "笔法式 → 适用质量维（正向）/ 须避病（负向）；作卡6 二级判据。"}


def resolve_composition(t, season, vband, yuan, bundles):
    """构图规则（G1）：边角 / 三叠两段护栏恒生效 + 蹊径六则软目标算子选取。"""
    cm = t["modulators"]["composition"]
    comp = t["vocab"]["composition"]
    has_stone = any(b["class"] == "山石" for b in bundles)
    has_sky = any(b["class"] == "天象" for b in bundles)
    full_span = any(b["layer"] == "全域" and b["class"] in ("天象", "水体") for b in bundles)
    fired = []
    if season == "冬" or vband["band"] in ("V1", "V2"):
        fired.append(("截断", "C1"))
    if has_stone and "高远" in yuan:
        fired.append(("险峻", "C2"))
    if has_sky and full_span:
        fired.append(("借景", "C3"))
    operator = fired[0][0] if fired else cm["default_operator"]
    return {
        "guards": [{"name": "边角", "kind": comp["边角"]["kind"], "rule": comp["边角"]["rule"]},
                   {"name": "三叠两段", "kind": comp["三叠两段"]["kind"], "rule": comp["三叠两段"]["rule"]}],
        "operator": operator,
        "operator_rule": comp[operator]["rule"],
        "candidates": [o for o, _ in fired] or [cm["default_operator"]],
        "rules_fired": [rid for _, rid in fired],
        "note": "边角 / 三叠两段为护栏（恒生效）；蹊径六则为软目标算子池，按语境选一。精确布局由卡5 求解。",
    }


def resolve_seal(t, fmt_candidates, form_len):
    """钤印规则（G8）：形制 → 印位；诗体长度 → 印面大小档。"""
    seal = t["vocab"]["seal"]
    slm = t["modulators"]["seal"]
    fmt = fmt_candidates[0] if fmt_candidates else "题款末"
    pos = seal["positions"].get(fmt, seal["positions"]["题款末"])
    size_key = slm["size_by_len"]["long"] if form_len >= slm["len_ref"] else slm["size_by_len"]["short"]
    return {
        "format": fmt,
        "position": pos["position"],
        "position_note": pos["note"],
        "size": size_key,
        "size_mult": seal["sizes"][size_key]["size_mult"],
        "rule": seal["rule"],
        "note": "D2 只给印位与印面区间，纳入卡7 段尾静默。",
    }


def resolve_poem(t, pid, imagery):
    ctx0 = POEM_CTX[pid]
    poem = imagery["poems"].get(pid) or JYS_FIXTURE
    nodes = poem["nodes"]

    Vmean = statistics.fmean(ctx0["V"])
    vband = pick_band(t["modulators"]["emotion"]["V"], Vmean)
    ctx = {"ink_steps": vband["ink_steps"]}

    bundles = [resolve_node(t, n, ctx) for n in nodes]

    # --- 三远投票 ---
    has_landscape = any(b["class"] in ("山石", "水体") for b in bundles)
    scores = {}
    if has_landscape:
        for b in bundles:
            d = t["class_defaults"].get(b["class"], {})
            w = d.get("weight", 1.0)
            for y, yw in zip(b["yuan_candidates"], d.get("yuan_w", [])):
                scores[y] = scores.get(y, 0.0) + yw * w
        # 空间词票
        text = ctx0["text"]
        for sw, sv in t["modulators"]["space"].items():
            if sw in text:
                scores[sv["yuan"]] = scores.get(sv["yuan"], 0.0) + sv["w"] * 1.5
    yuan = [y for y, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:2]] if scores else []

    # --- 皴法（主体/地标）---
    season_word = [w for w in t["modulators"]["season_words"] if w in ctx0["text"]]
    season = t["modulators"]["season_words"][season_word[0]] if season_word else None
    # 天候档（G4）先于留白：weather.blank_bonus 参与 ρ 区间上调
    weather = resolve_weather(t, ctx0["text"])
    cun = set()
    for b in bundles:
        if b["role"] in ("主体", "地标", "焦点", "点缀"):
            if b["class"] == "山石" and season == "冬":
                cun.add("无皴")          # R10：雪覆山体不露石理
            elif b["cun"] != "无皴":
                cun.add(b["cun"])
    if not cun and any(b["class"] == "山石" for b in bundles):
        cun.add("无皴" if season == "冬" else "披麻皴")

    # --- 留白率区间 ---
    br = t["modulators"]["blank_rules"]
    lo, hi = vband["blank_base"]
    n_neg = sum(1 for n in nodes if n.get("neg_kind"))
    if n_neg >= 1:
        lo += br["neg_node_bonus"]; hi += br["neg_node_bonus"]
    full_span = any(b["layer"] == "全域" and b["class"] in ("天象", "水体") for b in bundles)
    if full_span:
        lo += br["full_span_bonus"]; hi += br["full_span_bonus"]
    paintable = [b for b in bundles if b["class"] != "非画"]
    if len(paintable) <= br["minimal_nodes"]:
        lo += br["minimal_bonus"]; hi += br["minimal_bonus"]
    # R11：实体质量项——实写主体越少，画面越空
    solid_mass = sum(b["weight"] for b in bundles if b["role"] in ("主体", "地标"))
    if solid_mass < br["mass_ref"]:
        mass_bonus = (br["mass_ref"] - solid_mass) * br["mass_slope"]
        lo += mass_bonus; hi += mass_bonus
    else:
        mass_bonus = 0.0
    # G4：天候 ρ 上调（雪景大留白；未定档则中性 0）
    if weather["blank_bonus"]:
        lo += weather["blank_bonus"]; hi += weather["blank_bonus"]
    lo = max(lo, br["cap"][0]); hi = min(hi, br["cap"][1])
    if lo > hi:
        lo, hi = hi, lo

    # --- 形制 + 运动 ---
    fm = t["modulators"]["form"].get(ctx0["form"], {})
    fmt = fm.get("format_candidates", [])
    motion = None
    if yuan:
        motion = t["vocab"]["yuan"][yuan[0]]["motion"]

    # --- 静默预算 ---
    t_bands = t["modulators"]["emotion"]["T"]
    tband = pick_band(t_bands, statistics.fmean(ctx0["T"]))
    # G14：尾部「悬置不释放」——末句 T 高企（≥0.8）时尾部静默升一档，
    # 使 D2 定档与卡7 落地值同源（《江雪》末句 T=0.95 → T4 → 0.26，对齐落地 26%）。
    if ctx0["T"][-1] >= 0.8:
        ti = t_bands.index(tband)
        tband = t_bands[min(ti + 1, len(t_bands) - 1)]

    # --- 季节 ---
    season_qi = t["vocab"]["season"][season]["qi"] if season else None

    # --- 极性归一（G12）：context 裁定 + 焦点/动作承载词 → 规范键候选 ---
    # D2 只给候选集（keys + ink_bias 区间 + 底色候选），精确底色由卡6 求解（分工铁律）。
    pol = t["modulators"]["polarity"]
    carriers = [(lab, "context") for lab in ctx0.get("polarity", [])]
    for n in nodes:
        if is_carrier(n) and n.get("polarity_hint"):
            carriers.append((n["polarity_hint"], "词:" + n["surface"]))
    p_keys, p_evidence, p_unmapped = [], {}, []
    for raw, src in carriers:
        k = norm_polarity(t, raw)
        if k is None:
            p_unmapped.append(raw)
            continue
        p_evidence.setdefault(k, [])
        if src not in p_evidence[k]:
            p_evidence[k].append(src)
        if k not in p_keys:
            p_keys.append(k)
    p_bias = [pol["keys"][k]["ink_bias"] for k in p_keys]
    p_color = []
    for k in p_keys:
        c = pol["keys"][k]["color"]
        if c not in p_color:
            p_color.append(c)
    polarity = {
        "keys": p_keys,
        "ink_bias_range": [min(p_bias), max(p_bias)] if p_bias else None,
        "colors": p_color,
        "evidence": p_evidence,
        "unmapped": p_unmapped,
    }

    # --- 底色通路（A 组）：季节色 + 极性偏置 → 卡6 底色候选 ---
    season_entry = t["vocab"]["season"][season] if season else None
    color_candidates = []
    if season_entry:
        color_candidates.append(season_entry["color"])
    for c in p_color:
        if c not in color_candidates:
            color_candidates.append(c)
    bias_pool = ([season_entry["ink_bias"]] if season_entry else []) + p_bias
    base_tone = {
        "season": {"name": season,
                   "color": season_entry["color"] if season_entry else None,
                   "ink_bias": season_entry["ink_bias"] if season_entry else None},
        "polarity_keys": p_keys,
        "color_candidates": color_candidates,
        "ink_bias_range": [min(bias_pool), max(bias_pool)] if bias_pool else None,
        "note": "D2 只给底色候选（季节色 + 极性键的 ink_bias/color），精确底色由卡6 求解。",
    }

    # --- 设色范式档（G3 · B 组）：品格/季节/极性 → 范式候选 + 默认档 + 色域投影 ---
    # D2 只给候选与色域（改写 A 组底色候选），精确用色由卡6 求解（分工铁律）。
    paradigm = resolve_paradigm(t, ctx0, vband, p_keys, season, base_tone)

    # --- 墨法轴（G11）：墨法候选 + μ 区间，精确墨法与扩散由卡6 求解（分工铁律）---
    im = t["vocab"]["ink_method"]
    im_candidates = {name: {"mu": d["mu"], "water": d["water"], "stroke": d["stroke"], "quality": d["quality"]}
                     for name, d in im.items()}
    im_suggested = ["破墨"]                       # 通用：湿破湿，出层次
    if season == "冬" or vband["band"] in ("V1", "V2"):
        im_suggested.append("宿墨")               # 冷寂 / 冬 → 涩而滞
    if any(b["role"] == "焦点" and b["ink_grade"] in ("焦", "浓") for b in bundles):
        im_suggested.append("焦墨")               # 深色焦点 → 醒提轮廓
    if statistics.fmean(ctx0["A"]) >= 0.6:
        im_suggested.append("飞白")               # 快笔 → 线断意不断
    if vband["band"] == "V5":
        im_suggested.append("泼墨")               # 豪迈 → 气势
    if any(b["class"] == "山石" and b["layer"] in ("远景", "极远") for b in bundles):
        im_suggested.append("积墨")               # 层叠远山 → 厚重
    ink_methods = {
        "candidates": im_candidates,
        "suggested": im_suggested,
        "note": "D2 只给墨法候选 + μ 区间（相对基准 μ0=1.0，L∝√(μ·t)），精确墨法与扩散由卡6 求解。",
    }

    # --- C 组·新算子（G1/G2/G4/G5/G6/G7/G8）---
    # D2 只给候选 / 区间 / 系数，精确数值由卡5 / 卡6 / 卡7 求解（分工铁律）。
    viewpoint = resolve_viewpoint(t, ctx0["text"], yuan, has_landscape)
    time_of_day = resolve_time_of_day(t, ctx0["text"])
    material = resolve_material(t)
    stroke_quality = resolve_stroke_quality(t, bundles)
    composition = resolve_composition(t, season, vband, yuan, bundles)
    seal = resolve_seal(t, fmt, fm.get("len", 0))

    return {
        "poem": pid,
        "title": ctx0["title"],
        "form": ctx0["form"],
        "V_mean": round(Vmean, 3),
        "V_band": vband["band"],
        "T_band": tband["band"],
        "season": season,
        "season_qi": season_qi,
        "yuan": yuan,
        "yuan_scores": {k: round(v, 2) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])},
        "yuan_applicable": has_landscape,
        "cun": sorted(cun),
        "blank_range": [round(lo, 3), round(hi, 3)],
        "solid_mass": round(solid_mass, 2),
        "mass_bonus": round(mass_bonus, 3),
        "format_candidates": fmt,
        "motion": motion,
        "silence_ratio": tband["silence_ratio"],
        "polarity": polarity,
        "base_tone": base_tone,
        "paradigm": paradigm,
        "ink_methods": ink_methods,
        "viewpoint": viewpoint,
        "weather": weather,
        "time_of_day": time_of_day,
        "material": material,
        "stroke_quality": stroke_quality,
        "composition": composition,
        "seal": seal,
        "nodes": bundles,
    }


# ---------------------------------------------------------------- 回归
def regress(t, imagery):
    report = {"checks": [], "summary": {}}
    n_pass = n_total = 0
    for pid, exp in REGRESSION_TARGETS.items():
        r = resolve_poem(t, pid, imagery)
        by = {b["surface"]: b for b in r["nodes"]}
        checks = []

        def add(name, ok, got, want):
            checks.append({"poem": pid, "check": name, "pass": bool(ok), "got": got, "want": want})

        # 1 三远
        if exp["yuan"]:
            add("三远", set(exp["yuan"]).issubset(set(r["yuan"])), r["yuan"], exp["yuan"])
        else:
            add("三远不适用", r["yuan"] == [], r["yuan"], "[]")
        # 2 皴法
        if exp["cun"]:
            add("皴法", set(exp["cun"]) & set(r["cun"]) != set(), r["cun"], exp["cun"])
        else:
            add("皴法不适用", r["cun"] == [], r["cun"], "[]")
        # 3 留白区间包含 pipeline ρ
        lo, hi = r["blank_range"]
        add("留白区间含实测ρ", lo <= exp["rho"] <= hi, r["blank_range"], exp["rho"])
        # 4 墨阶排序（越深 index 越小）
        for a, b in exp["ink_order"]:
            ia = ink_rank(t["vocab"]["ink_ladder"], by[a]["ink_grade"])
            ib = ink_rank(t["vocab"]["ink_ladder"], by[b]["ink_grade"])
            add(f"墨阶 {a}>{b}", ia < ib, f"{a}={by[a]['ink_grade']} vs {b}={by[b]['ink_grade']}", "前者更深")
        # 5 虚写→留白
        for v in exp["ink_void"]:
            add(f"虚写留白 {v}", by[v]["ink_grade"] == "留白", by[v]["ink_grade"], "留白")
        # 6 负节点不画
        for v in exp["neg_no_paint"]:
            add(f"负节点不画 {v}", by[v]["role"] == "不画", by[v]["role"], "不画")
        # 7 figure_layer：人物尺寸档（郭熙三远与人物；景深→尺寸）
        for a, want in exp.get("figure_size", []):
            add(f"人物尺寸 {a}", by[a]["size"] == want, by[a]["size"], want)
        # 8 极性归一（G12）：自由文本全部归一 + 规范键命中
        pl = r["polarity"]
        add("极性归一无漏", pl["unmapped"] == [], pl["unmapped"], "[]")
        if exp.get("polarity_keys"):
            add("极性规范键", set(exp["polarity_keys"]).issubset(set(pl["keys"])), pl["keys"], exp["polarity_keys"])
        # 9 底色通路（A 组）：季节色 + 极性 → 卡6 底色候选
        bt = r["base_tone"]
        add("底色候选非空", bool(bt["color_candidates"]), bt["color_candidates"], "≥1 色")
        add("底色候选含极性色", set(pl["colors"]).issubset(set(bt["color_candidates"])), bt["color_candidates"], pl["colors"])
        # 10 墨法候选（G11）：候选非空 + 语境建议非空
        imv = r["ink_methods"]
        add("墨法候选非空", bool(imv["candidates"]), len(imv["candidates"]), "≥1")
        add("墨法建议非空", bool(imv["suggested"]), imv["suggested"], "≥1")
        # 11 设色范式档（G3 · B 组）：默认档命中 + 候选非空 + 色域投影非空 + 墨骨比例有效
        pg = r["paradigm"]
        if exp.get("paradigm"):
            add("范式默认档", pg["default"] == exp["paradigm"], pg["default"], exp["paradigm"])
        add("范式候选非空", bool(pg["candidates"]), pg["candidates"], "≥1")
        add("范式色域投影非空", bool(pg["projected_color_candidates"]), pg["projected_color_candidates"], "≥1 色")
        add("范式墨骨比例有效", 0.0 <= pg["ink_bone_scale"] <= 1.0, pg["ink_bone_scale"], "[0,1]")
        # 12 静默预算（G14）：jx 尾部悬置 → 0.26，与卡7 落地 26% 同源
        if pid == "jx":
            add("静默预算同源 G14", abs(r["silence_ratio"] - 0.26) < 1e-9, r["silence_ratio"], 0.26)
        # 13 C 组·视点档（G7）
        vpv = r["viewpoint"]
        if exp.get("viewpoint"):
            add("视点档 G7", vpv["default"] == exp["viewpoint"], vpv["default"], exp["viewpoint"])
        else:
            add("视点不适用 G7", vpv["applicable"] is False, vpv["applicable"], False)
        # 14 C 组·天候（G4）
        add("天候档 G4", r["weather"]["name"] == exp.get("weather"), r["weather"]["name"], exp.get("weather"))
        # 15 C 组·时辰（G5）
        add("时辰档 G5", r["time_of_day"]["name"] == exp.get("time_of_day"), r["time_of_day"]["name"], exp.get("time_of_day"))
        # 16 C 组·构图算子（G1）
        add("构图算子 G1", r["composition"]["operator"] == exp.get("composition"), r["composition"]["operator"], exp.get("composition"))
        # 17 C 组·钤印（G8）
        add("钤印印面 G8", r["seal"]["size"] == exp.get("seal_size"), r["seal"]["size"], exp.get("seal_size"))
        add("钤印印位 G8", r["seal"]["format"] == exp.get("seal_format"), r["seal"]["format"], exp.get("seal_format"))
        # 18 C 组·材质（G6）与笔法质量维（G2）非空
        add("材质系数非空 G6", bool(r["material"]["choice"]), r["material"]["choice"], "≥1")
        add("笔法质量维非空 G2", bool(r["stroke_quality"]["quality"]), r["stroke_quality"]["quality"], "≥1")

        n_pass += sum(1 for c in checks if c["pass"])
        n_total += len(checks)
        report["checks"].extend(checks)

    # 10 皴法谱完整性（G10·全局）：vocab 须含新增高频皴 + 独立「干擦」，且山石候选池可取到
    g10_vocab = {"雨点皴", "折带皴", "米点皴", "干擦"}
    g10_pool = {"雨点皴", "折带皴", "米点皴"}
    have_vocab = g10_vocab.issubset(set(t["vocab"]["cun"].keys()))
    have_pool = g10_pool.issubset(set(t["class_defaults"]["山石"].get("cun_alt", [])))
    ok_g10 = have_vocab and have_pool
    report["checks"].append({
        "poem": "全局", "check": "皴法谱 G10", "pass": bool(ok_g10),
        "got": f"vocab={sorted(g10_vocab & set(t['vocab']['cun'].keys()))} pool={sorted(g10_pool & set(t['class_defaults']['山石'].get('cun_alt', [])))}",
        "want": f"vocab⊇{sorted(g10_vocab)} 且 山石池⊇{sorted(g10_pool)}",
    })
    n_total += 1
    n_pass += 1 if ok_g10 else 0

    # 11 墨法独立（G11·全局）：宿墨 / 焦墨独立立档（含 μ），且 μ 排序合理（宿墨比泼墨更滞）
    im = t["vocab"]["ink_method"]
    ok_g11 = ("宿墨" in im and "焦墨" in im
              and all(isinstance(d.get("mu"), list) and len(d["mu"]) == 2 for d in im.values())
              and im["宿墨"]["mu"][1] < im["泼墨"]["mu"][0])
    report["checks"].append({
        "poem": "全局", "check": "墨法独立 G11", "pass": bool(ok_g11),
        "got": f"宿墨μ={im.get('宿墨', {}).get('mu')} 焦墨μ={im.get('焦墨', {}).get('mu')} 泼墨μ={im.get('泼墨', {}).get('mu')}",
        "want": "宿墨/焦墨独立立档且 μ 有效、宿墨 μ < 泼墨 μ",
    })
    n_total += 1
    n_pass += 1 if ok_g11 else 0

    # 12 设色范式档（G3·全局）：四范式齐备 + 定档规则 P1/P2/P3 + 色域投影键一致
    pgv = t["vocab"].get("paradigm", {})
    pgm = t["modulators"].get("paradigm", {})
    ok_g3 = ({"青绿", "浅绛", "水墨", "没骨"}.issubset(set(pgv.keys()))
             and {"P1", "P2", "P3"}.issubset({r["id"] for r in pgm.get("rules", [])})
             and set(pgm.get("color_projection", {}).keys()) == set(pgv.keys()))
    report["checks"].append({
        "poem": "全局", "check": "设色范式档 G3", "pass": bool(ok_g3),
        "got": f"vocab={sorted(pgv.keys())} rules={[r['id'] for r in pgm.get('rules', [])]}",
        "want": "四范式齐备 + 规则 P1/P2/P3 + 色域投影键一致",
    })
    n_total += 1
    n_pass += 1 if ok_g3 else 0

    # 13 C 组·新算子齐备（G1/G2/G4/G5/G6/G7/G8）：七类词表 / 调制器全部落地
    vp2 = t["vocab"].get("viewpoint", {})
    wx2 = t["vocab"].get("weather", {})
    tod2 = t["vocab"].get("time_of_day", {})
    mat2 = t["vocab"].get("material", {})
    sq2 = t["vocab"].get("stroke_quality", {})
    sd2 = t["vocab"].get("stroke_disease", {})
    comp2 = t["vocab"].get("composition", {})
    seal2 = t["vocab"].get("seal", {})
    n_mat2 = sum(len(mat2.get(c, {})) for c in ("纸绢", "笔", "墨"))
    ok_c = (set(vp2) == {"平视", "仰视", "俯视"}
            and {"晴", "雨", "雪", "雾"} <= set(wx2)
            and {"晨", "昼", "暮", "夜"} <= set(tod2)
            and n_mat2 == 8
            and {"筋", "肉", "骨", "气", "平", "留", "圆", "重", "变"} <= set(sq2)
            and {"板", "刻", "结", "有形病", "无形病"} <= set(sd2)
            and {"边角", "三叠两段", "借景", "截断", "险峻"} <= set(comp2)
            and {"手卷", "立轴", "册页", "扇面", "题款末"} <= set(seal2.get("positions", {})))
    report["checks"].append({
        "poem": "全局", "check": "新算子齐备 C 组", "pass": bool(ok_c),
        "got": f"视点{len(vp2)} 天候{len(wx2)} 时辰{len(tod2)} 材质{n_mat2} 质量维{len(sq2)} 病{len(sd2)} 构图{len(comp2)} 印位{len(seal2.get('positions', {}))}",
        "want": "视点3 天候4 时辰4 材质8 质量维9 病5 构图8 印位5",
    })
    n_total += 1
    n_pass += 1 if ok_c else 0

    # 14 C 组·G5 口径：season_words 不再含「月」，月已迁至 time_words（月→夜）
    ok_g5 = ("月" not in t["modulators"]["season_words"]
             and t["modulators"]["time_words"]["map"].get("月") == "夜")
    report["checks"].append({
        "poem": "全局", "check": "时辰口径 G5", "pass": bool(ok_g5),
        "got": f"season_words含月={'月' in t['modulators']['season_words']} time_words[月]={t['modulators']['time_words']['map'].get('月')}",
        "want": "season_words 不含月 且 time_words[月]=夜",
    })
    n_total += 1
    n_pass += 1 if ok_g5 else 0

    report["summary"] = {
        "passed": n_pass, "total": n_total,
        "rate": round(n_pass / n_total, 4) if n_total else 0.0,
        "all_pass": n_pass == n_total,
    }
    return report


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poem", choices=list(POEM_CTX.keys()))
    ap.add_argument("--word")
    args = ap.parse_args()

    t = load(os.path.join(ROOT, "data", "derived", "d2_techniques.json"))
    imagery = load(os.path.join(ROOT, "data", "derived", "o2_imagery.json"))

    if args.word:
        cls, how = classify(t, args.word)
        node = {"surface": args.word, "gate": {"class": "实写"}, "e": {}}
        print(json.dumps({"class": cls, "by": how,
                          "bundle": resolve_node(t, node, {"ink_steps": 0})},
                         ensure_ascii=False, indent=2))
        return

    if args.poem:
        r = resolve_poem(t, args.poem, imagery)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    rep = regress(t, imagery)
    dst = os.path.join(ROOT, "data", "runs", "d2_regression.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print("[D2] 回归校验（对照三首 pipeline 实跑值）")
    cur = None
    for c in rep["checks"]:
        if c["poem"] != cur:
            cur = c["poem"]
            title = POEM_CTX[cur]["title"] if cur in POEM_CTX else cur
            print(f"\n  ── {title} ──")
        flag = "✓" if c["pass"] else "✗"
        print(f"    {flag} {c['check']}: {c['got']}  (期望 {c['want']})")
    s = rep["summary"]
    print(f"\n  合计：{s['passed']}/{s['total']}  通过率 {s['rate']*100:.1f}%  "
          f"{'✓ 全通过' if s['all_pass'] else '✗ 有失败'}")
    print(f"  报告 -> d2_regression.json")


if __name__ == "__main__":
    main()
