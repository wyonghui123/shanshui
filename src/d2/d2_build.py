# -*- coding: utf-8 -*-
"""
D2 构建脚本：源（画论） + 种子（映射） + 补遗 → 主表 d2_techniques.json

用法：
    python src/d2/d2_build.py

产物：
    d2_techniques.json   自包含主表（含来源索引与统计）
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

SRC = os.path.join(ROOT, "data", "source", "d2_seed")


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    theory = load(os.path.join(SRC, "painting_theory.json"))
    seed = load(os.path.join(SRC, "d2_mapping_seed.json"))
    supp = load(os.path.join(ROOT, "data", "source", "d2_supplement.json"))

    vocab = seed["vocab"]
    classes = seed["classes"]
    head_class = dict(seed["head_class"])
    word_class = dict(seed["word_class"])
    class_defaults = seed["class_defaults"]
    word_override = dict(seed.get("word_override", {}))
    modulators = seed["modulators"]
    rules = seed["rules"]

    errors = []

    # --- 合并补遗（种子优先）---
    merged_from_supp = 0
    for w, c in supp.get("word_class", {}).items():
        if w not in word_class:
            word_class[w] = c
            merged_from_supp += 1

    # --- 来源索引 ---
    sources = {e["id"]: e for e in theory["entries"]}
    # basis 允许直接引用「等级」token（无单一原文者），如 通例 / 裁定
    grade_tokens = set(theory["meta"]["grade_scale"].keys())
    basis_ok = set(sources.keys()) | grade_tokens

    # --- 完整性校验 ---
    valid_yuan = set(vocab["yuan"].keys())
    valid_cun = set(vocab["cun"].keys())
    valid_ink = set(vocab["ink"].keys())
    valid_water = set(vocab["water"].keys())
    valid_stroke = set(vocab["stroke"].keys())
    valid_layer = set(vocab["layer"])
    valid_season = set(vocab["season"].keys())
    class_names = set(classes.keys())

    # vocab 各表的 source_id 须指向 painting_theory 的 id（保证取值可回溯）
    for table, tbl in vocab.items():
        if not isinstance(tbl, dict):
            continue
        for key, d in tbl.items():
            if not isinstance(d, dict):
                continue
            sid = d.get("source_id")
            if sid and sid not in sources:
                errors.append(f"vocab.{table}['{key}'].source_id = '{sid}' 未在 painting_theory 中定义")

    for ch, c in head_class.items():
        if c not in class_names:
            errors.append(f"head_class['{ch}'] -> 未定义类别 '{c}'")
    for w, c in word_class.items():
        if c not in class_names:
            errors.append(f"word_class['{w}'] -> 未定义类别 '{c}'")
    for cname, d in class_defaults.items():
        if cname not in class_names:
            errors.append(f"class_defaults 含未定义类别 '{cname}'")
        for y in d.get("yuan", []):
            if y not in valid_yuan:
                errors.append(f"class_defaults['{cname}'].yuan 含未知远 '{y}'")
        for y in d.get("cun_alt", []):
            if y not in valid_cun:
                errors.append(f"class_defaults['{cname}'].cun_alt 含未知皴 '{y}'")
        if d.get("cun") not in valid_cun:
            errors.append(f"class_defaults['{cname}'].cun = '{d.get('cun')}' 未定义")
        if d.get("ink_grade") not in valid_ink:
            errors.append(f"class_defaults['{cname}'].ink_grade = '{d.get('ink_grade')}' 未定义")
        if d.get("water") not in valid_water:
            errors.append(f"class_defaults['{cname}'].water = '{d.get('water')}' 未定义")
        if d.get("stroke") not in valid_stroke:
            errors.append(f"class_defaults['{cname}'].stroke = '{d.get('stroke')}' 未定义")
        if d.get("layer") not in valid_layer:
            errors.append(f"class_defaults['{cname}'].layer = '{d.get('layer')}' 未定义")
        for b in d.get("basis", []):
            if b not in basis_ok:
                errors.append(f"class_defaults['{cname}'].basis 含未知来源 '{b}'")
    for k, v in modulators["space"].items():
        if v["yuan"] not in valid_yuan:
            errors.append(f"space['{k}'] -> 未知远 '{v['yuan']}'")
    for k, v in modulators["season_words"].items():
        if v not in valid_season:
            errors.append(f"season_words['{k}'] -> 未知季节 '{v}'")
    pol = modulators.get("polarity", {})
    pol_keys = pol.get("keys", {})
    if not pol_keys:
        errors.append("modulators.polarity 缺 keys（8 个规范键）")
    for lab, k in pol.get("normalize", {}).items():
        if k not in pol_keys:
            errors.append(f"polarity.normalize['{lab}'] -> 未定义键 '{k}'")
    # 墨法轴（G11）：mu 为卡6 扩散系数区间；water / stroke 须在词表内
    ink_method = vocab.get("ink_method", {})
    if "宿墨" not in ink_method or "焦墨" not in ink_method:
        errors.append("vocab.ink_method 缺「宿墨」或「焦墨」（G11 要求二者独立立档）")
    for mname, d in ink_method.items():
        mu = d.get("mu")
        if not (isinstance(mu, list) and len(mu) == 2 and 0 < mu[0] <= mu[1]):
            errors.append(f"ink_method['{mname}'].mu = {mu} 须为 0 < lo ≤ hi 的二元区间")
        if d.get("water") not in valid_water:
            errors.append(f"ink_method['{mname}'].water = '{d.get('water')}' 未定义")
        if d.get("stroke") not in valid_stroke:
            errors.append(f"ink_method['{mname}'].stroke = '{d.get('stroke')}' 未定义")
    # 设色范式档（G3 · B 组）：vocab.paradigm 四范式 + 定档规则 + 色域投影
    paradigm = vocab.get("paradigm", {})
    pg_required = {"青绿", "浅绛", "水墨", "没骨"}
    if not pg_required.issubset(set(paradigm.keys())):
        errors.append(f"vocab.paradigm 缺范式：{sorted(pg_required - set(paradigm.keys()))}")
    for pname, d in paradigm.items():
        if d.get("ink_bone") not in ("无", "轻", "中", "重"):
            errors.append(f"paradigm['{pname}'].ink_bone = '{d.get('ink_bone')}' 非法（须 无/轻/中/重）")
        if not isinstance(d.get("color_domain"), list):
            errors.append(f"paradigm['{pname}'].color_domain 须为列表")
    pgm = modulators.get("paradigm", {})
    if pgm.get("default") not in paradigm:
        errors.append(f"modulators.paradigm.default = '{pgm.get('default')}' 未在 vocab.paradigm 中定义")
    for r in pgm.get("rules", []):
        if r.get("then") not in paradigm:
            errors.append(f"paradigm.rules['{r.get('id')}'].then = '{r.get('then')}' 未在 vocab.paradigm 中定义")
    cp = pgm.get("color_projection", {})
    if set(cp.keys()) != set(paradigm.keys()):
        errors.append(f"paradigm.color_projection 键 {sorted(cp.keys())} 须与 vocab.paradigm 一致 {sorted(paradigm.keys())}")
    for pname, d in cp.items():
        s = d.get("ink_bone_scale")
        if not (isinstance(s, (int, float)) and 0.0 <= s <= 1.0):
            errors.append(f"paradigm.color_projection['{pname}'].ink_bone_scale = {s} 须在 [0,1]")

    # --- C 组 · 新算子 / 新调制器（G1/G2/G4/G5/G6/G7/G8）---
    # 视点档（G7）
    vp = vocab.get("viewpoint", {})
    if set(vp.keys()) != {"平视", "仰视", "俯视"}:
        errors.append(f"vocab.viewpoint 须恰为 平视/仰视/俯视，现为 {sorted(vp.keys())}")
    for name, d in vp.items():
        h = d.get("params", {}).get("horizon")
        if not (isinstance(h, list) and len(h) == 2 and h[0] <= h[1]):
            errors.append(f"viewpoint['{name}'].params.horizon = {h} 须为二元升序区间")
        for y in d.get("params", {}).get("yuan_affinity", []):
            if y not in valid_yuan:
                errors.append(f"viewpoint['{name}'].yuan_affinity 含未知远 '{y}'")
    vpm = modulators.get("viewpoint", {})
    if vpm.get("default") not in vp:
        errors.append(f"modulators.viewpoint.default = '{vpm.get('default')}' 未在 vocab.viewpoint 中定义")
    for w, v in vpm.get("words", {}).items():
        if v not in vp:
            errors.append(f"viewpoint.words['{w}'] -> 未知视点 '{v}'")
    for y, v in vpm.get("from_yuan", {}).items():
        if y not in valid_yuan:
            errors.append(f"viewpoint.from_yuan 含未知远 '{y}'")
        if v not in vp:
            errors.append(f"viewpoint.from_yuan['{y}'] -> 未知视点 '{v}'")

    # 天候（G4）
    wx = vocab.get("weather", {})
    wx_required = {"晴", "雨", "雪", "雾"}
    if not wx_required.issubset(set(wx.keys())):
        errors.append(f"vocab.weather 缺天候：{sorted(wx_required - set(wx.keys()))}")
    for name, d in wx.items():
        for k in ("sigma_mult", "mu_mult"):
            r = d.get(k)
            if not (isinstance(r, list) and len(r) == 2 and 0 < r[0] <= r[1]):
                errors.append(f"weather['{name}'].{k} = {r} 须为 0 < lo ≤ hi 的二元区间")
        sid = d.get("source_id")
        if sid and sid not in sources:
            errors.append(f"weather['{name}'].source_id = '{sid}' 未在 painting_theory 中定义")
        for c in d.get("cun_bias", []):
            if c not in valid_cun:
                errors.append(f"weather['{name}'].cun_bias 含未知皴 '{c}'")
    for w, v in modulators.get("weather", {}).get("words", {}).items():
        if v not in wx:
            errors.append(f"weather.words['{w}'] -> 未知天候 '{v}'")

    # 时辰（G5）
    tod = vocab.get("time_of_day", {})
    tod_required = {"晨", "昼", "暮", "夜"}
    if not tod_required.issubset(set(tod.keys())):
        errors.append(f"vocab.time_of_day 缺时辰：{sorted(tod_required - set(tod.keys()))}")
    for name, d in tod.items():
        r = d.get("seg_len_mult")
        if not (isinstance(r, list) and len(r) == 2 and 0 < r[0] <= r[1]):
            errors.append(f"time_of_day['{name}'].seg_len_mult = {r} 须为 0 < lo ≤ hi 的二元区间")
        sid = d.get("source_id")
        if sid and sid not in sources:
            errors.append(f"time_of_day['{name}'].source_id = '{sid}' 未在 painting_theory 中定义")
    for w, v in modulators.get("time_words", {}).get("map", {}).items():
        if v not in tod:
            errors.append(f"time_words.map['{w}'] -> 未知时辰 '{v}'")
    if "月" in modulators["season_words"]:
        errors.append("season_words 仍含「月」（G5：月属天象 / 时辰，非季节；应迁至 time_words）")

    # 材质系数（G6）
    mat = vocab.get("material", {})
    for cat in ("纸绢", "笔", "墨"):
        if not isinstance(mat.get(cat), dict) or not mat[cat]:
            errors.append(f"vocab.material 缺类别 '{cat}'")
    if mat.get("source_id") and mat["source_id"] not in sources:
        errors.append(f"material.source_id = '{mat['source_id']}' 未在 painting_theory 中定义")
    for cat in ("纸绢", "笔", "墨"):
        for name, d in mat.get(cat, {}).items():
            for k, r in d.items():
                if k.endswith("_mult") or k in ("feibai_threshold", "stiffness", "water_cap"):
                    if not (isinstance(r, list) and len(r) == 2 and 0 < r[0] <= r[1]):
                        errors.append(f"material['{cat}']['{name}'].{k} = {r} 须为 0 < lo ≤ hi 的二元区间")
    for cat, name in modulators.get("material", {}).get("default", {}).items():
        if name not in mat.get(cat, {}):
            errors.append(f"modulators.material.default['{cat}'] = '{name}' 未在 vocab.material 中定义")

    # 笔法质量维（G2）
    sq = vocab.get("stroke_quality", {})
    sq_required = {"筋", "肉", "骨", "气", "平", "留", "圆", "重", "变"}
    if not sq_required.issubset(set(sq.keys())):
        errors.append(f"vocab.stroke_quality 缺质量维：{sorted(sq_required - set(sq.keys()))}")
    sd = vocab.get("stroke_disease", {})
    sd_required = {"板", "刻", "结", "有形病", "无形病"}
    if not sd_required.issubset(set(sd.keys())):
        errors.append(f"vocab.stroke_disease 缺病：{sorted(sd_required - set(sd.keys()))}")
    for table in (sq, sd):
        for name, d in table.items():
            sid = d.get("source_id")
            if sid and sid not in sources:
                errors.append(f"stroke_quality/disease['{name}'].source_id = '{sid}' 未在 painting_theory 中定义")
    for sname, d in modulators.get("stroke_quality", {}).get("by_stroke", {}).items():
        if sname not in valid_stroke:
            errors.append(f"stroke_quality.by_stroke 含未知笔法 '{sname}'")
        for q in d.get("quality", []):
            if q not in sq:
                errors.append(f"stroke_quality.by_stroke['{sname}'].quality 含未知质量维 '{q}'")
        for q in d.get("avoid", []):
            if q not in sd:
                errors.append(f"stroke_quality.by_stroke['{sname}'].avoid 含未知病 '{q}'")

    # 构图规则（G1）
    comp = vocab.get("composition", {})
    xijing = {"对景不对山", "对山不对景", "倒景", "借景", "截断", "险峻"}
    if not xijing.issubset(set(comp.keys())):
        errors.append(f"vocab.composition 缺蹊径六则：{sorted(xijing - set(comp.keys()))}")
    for name, d in comp.items():
        sid = d.get("source_id")
        if sid and sid not in sources:
            errors.append(f"composition['{name}'].source_id = '{sid}' 未在 painting_theory 中定义")
    cm = modulators.get("composition", {})
    if cm.get("default_operator") not in comp:
        errors.append(f"modulators.composition.default_operator = '{cm.get('default_operator')}' 未在 vocab.composition 中定义")
    for r in cm.get("rules", []):
        if r.get("then") not in comp:
            errors.append(f"composition.rules['{r.get('id')}'].then = '{r.get('then')}' 未在 vocab.composition 中定义")

    # 钤印规则（G8）
    seal = vocab.get("seal", {})
    for f in vocab["format"].keys():
        if f not in seal.get("positions", {}):
            errors.append(f"vocab.seal.positions 缺形制 '{f}'")
    if "题款末" not in seal.get("positions", {}):
        errors.append("vocab.seal.positions 缺 '题款末'")
    for name, d in seal.get("sizes", {}).items():
        r = d.get("size_mult")
        if not (isinstance(r, list) and len(r) == 2 and 0 < r[0] <= r[1]):
            errors.append(f"seal.sizes['{name}'].size_mult = {r} 须为二元区间")
    if seal.get("source_id") and seal["source_id"] not in sources:
        errors.append(f"seal.source_id = '{seal['source_id']}' 未在 painting_theory 中定义")
    for k, v in modulators.get("seal", {}).get("size_by_len", {}).items():
        if v not in seal.get("sizes", {}):
            errors.append(f"seal.size_by_len['{k}'] = '{v}' 未在 vocab.seal.sizes 中定义")

    for cname, by_layer in modulators.get("layer_technique", {}).items():
        if cname not in class_names:
            errors.append(f"layer_technique 含未定义类别 '{cname}'")
        for lname, attrs in by_layer.items():
            if lname not in valid_layer:
                errors.append(f"layer_technique['{cname}'] 含未知层 '{lname}'")
            if "water" in attrs and attrs["water"] not in valid_water:
                errors.append(f"layer_technique['{cname}']['{lname}'].water = '{attrs['water']}' 未定义")
            if "stroke" in attrs and attrs["stroke"] not in valid_stroke:
                errors.append(f"layer_technique['{cname}']['{lname}'].stroke = '{attrs['stroke']}' 未定义")
            if "cun" in attrs and attrs["cun"] not in valid_cun:
                errors.append(f"layer_technique['{cname}']['{lname}'].cun = '{attrs['cun']}' 未定义")
    for cname, d in class_defaults.items():
        if len(d.get("yuan", [])) != len(d.get("yuan_w", [])):
            errors.append(f"class_defaults['{cname}'] yuan 与 yuan_w 长度不一致")

    if errors:
        print("[D2] 校验失败：")
        for e in errors:
            print("  ✗", e)
        sys.exit(1)

    out = {
        "meta": {
            "name": "d2_techniques",
            "version": "1.0",
            "generated": "2026-10-03",
            "role": "D2 主表：意象类别/情感 → 三远、皴法、墨色、含水、笔法、层、留白、点苔。图侧 L1 要素的共同上游。",
            "division_of_labor": "D2 给「候选集 + 类别档 + 区间约束」；精确数值由卡5 构图求解器与卡6 笔墨物理给出。",
            "grade_scale": theory["meta"]["grade_scale"],
            "source_doc": "data/source/d2_seed/painting_theory.json",
            "seed_doc": "data/source/d2_seed/d2_mapping_seed.json",
            "supplement_doc": "data/source/d2_supplement.json",
            "fields": {
                "class_defaults.yuan": "三远候选（按权重降序）",
                "class_defaults.cun": "皴法",
                "class_defaults.ink_grade": "墨分五色档（焦/浓/重/淡/清/留白）",
                "vocab.ink_method": "墨法轴（破/积/泼/宿/焦/飞白）→ mu 扩散系数区间（卡6）",
                "class_defaults.water": "含水档（极低/低/中/高/极高）",
                "class_defaults.stroke": "笔法",
                "class_defaults.layer": "景深",
                "class_defaults.blank_bias": "留白倾向（-2..+2）",
                "class_defaults.diantai": "是否点苔",
                "class_defaults.role": "画面角色（主体/地标/焦点/点缀/引导/承载留白/不画）",
                "class_defaults.weight": "三远投票权重",
                "modulators.emotion": "V/A/T 档 → 留白区间/墨阶位移/静默/重心",
                "modulators.layer_atten_steps": "层 → 墨阶变淡步数（空气透视）",
                "modulators.layer_technique": "类别×层 → 含水/笔法（远山细化的泛化规则；词覆盖优先）",
                "modulators.figure_layer": "景深 → 人物尺寸档/墨阶（郭熙三远与人物；词覆盖优先；中号仅角色=主体可用）",
                "modulators.space": "空间词 → 三远票",
                "modulators.season_words": "物候词 → 四时",
                "modulators.polarity": "文化极性 → 墨/底色偏置（keys 8 规范键 + normalize 自由文本归一）",
                "vocab.paradigm": "设色范式（青绿/浅绛/水墨/没骨）→ 墨骨强度 + 色域（卡6）",
                "modulators.paradigm": "品格/季节/极性 → 范式候选 + 默认档 + 色域投影（G3）",
                "modulators.form": "诗体 → 装裱形制候选",
                "modulators.blank_rules": "留白率区间算法",
                "vocab.viewpoint": "视点档（平视/仰视/俯视）→ 地平线/纵比区间（卡5；G7）",
                "modulators.viewpoint": "空间词/三远 → 视点票（G7）",
                "vocab.weather": "天候（晴/雨/雪/雾）→ σ/μ 乘子 + ρ 上调 + 皴建议（卡5/卡6；G4）",
                "modulators.weather": "天候词 → 天候档（G4）",
                "vocab.time_of_day": "时辰（晨/昼/暮/夜）→ 段长乘子 + 墨/色候选（卡7；G5）",
                "modulators.time_words": "时辰词 → 时辰档（G5；含由 season_words 迁来的「月」）",
                "vocab.material": "材质系数（纸绢/笔/墨）→ D/μ 乘子 + 飞白阈值 + 冷暖（卡6；G6）",
                "modulators.material": "材质默认档（生宣/兼毫/松烟；G6）",
                "vocab.stroke_quality": "笔法质量维（荆浩四势 + 黄宾虹五笔；卡6；G2）",
                "vocab.stroke_disease": "用笔负判据（郭若虚三病 + 荆浩二病；卡6；G2）",
                "modulators.stroke_quality": "笔法式 → 适用质量维 / 须避病（G2）",
                "vocab.composition": "构图规则（边角/三叠两段/蹊径六则；卡5；G1）",
                "modulators.composition": "语境 → 蹊径软目标算子（G1）",
                "vocab.seal": "钤印规则（印位/印面；卡7；G8）",
                "modulators.seal": "形制/尺幅 → 印位 / 印面大小（G8）"
            }
        },
        "vocab": vocab,
        "classes": classes,
        "head_class": head_class,
        "word_class": word_class,
        "class_defaults": class_defaults,
        "word_override": word_override,
        "modulators": modulators,
        "rules": rules,
        "technique_triggers": supp.get("technique_triggers", {}),
        "sources": sources,
        "stats": {
            "n_classes": len(classes),
            "n_head_class": len(head_class),
            "n_word_class": len(word_class),
            "n_word_class_from_supplement": merged_from_supp,
            "n_class_defaults": len(class_defaults),
            "n_yuan": len(valid_yuan),
            "n_cun": len(valid_cun),
            "n_ink_method": len(ink_method),
            "n_paradigm": len(paradigm),
            "n_viewpoint": len(vp),
            "n_weather": len(wx),
            "n_time_of_day": len(tod),
            "n_material": sum(len(mat.get(c, {})) for c in ("纸绢", "笔", "墨")),
            "n_stroke_quality": len(sq),
            "n_stroke_disease": len(sd),
            "n_composition": len(comp),
            "n_seal_positions": len(seal.get("positions", {})),
            "n_polarity_keys": len(pol_keys),
            "n_polarity_normalize": len(pol.get("normalize", {})),
            "n_sources": len(sources),
            "n_rules": len(rules),
        },
    }

    dst = os.path.join(ROOT, "data", "derived", "d2_techniques.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("[D2] 构建完成 -> d2_techniques.json")
    for k, v in out["stats"].items():
        print(f"  {k}: {v}")
    print("  校验：全部通过 ✓")


if __name__ == "__main__":
    main()
