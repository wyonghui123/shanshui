# -*- coding: utf-8 -*-
"""D1 中古音韵书 · 解析器 + 回归校验

职责：
  1) 查表：字 → 四声/韵部/平仄选项（D1 是「数据」，不负责消歧）
  2) 韵脚判定：由句末字反推韵部，标出押韵的句
  3) 生成 voice_prosody_process.py 需要的 (字, tone, role) 三元组
  4) 回归：与 voice_prosody_process.py 中手工标注的 POEMS 逐字比对，输出覆盖率/命中率/歧义清单

用法：
  python src/d1/d1_resolve.py                      # 跑三首诗的回归校验
  python src/d1/d1_resolve.py --lines "千山鸟飞绝|万径人踪灭|孤舟蓑笠翁|独钓寒江雪"
"""
import argparse
import ast
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

D1 = os.path.join(ROOT, "data", "derived", "d1_rhyme.json")
VOICE = os.path.join(ROOT, "src", "voice", "voice_prosody_process.py")
OUT = os.path.join(ROOT, "data", "runs", "d1_regression.json")
PROSODY = os.path.join(ROOT, "data", "derived", "d1_prosody.json")
CHECK_OUT = os.path.join(ROOT, "data", "runs", "d1_prosody_check.json")
CONTEXT_DIR = os.path.join(ROOT, "data", "source", "context")
# 诗 id ↔ 语境目录名（新诗加入时在此登记；id 用作派生文件与下游的键）
PID_TITLE = {"jx": "江雪", "jys": "静夜思", "bd": "早发白帝城"}

# 四声 → 平仄；入声单列（仄但需短促处理）。manual 的 "rhyme" 指平声韵脚。
PING = "平"
ZE = "仄"
CODE2ZE = {"level": PING, "oblique": ZE, "entering": ZE, "rhyme": PING}


def load_d1(path=D1):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(d1, ch):
    """归一：简体直取；繁体经 t2s 映射。返回索引键，未收录返回 None。"""
    if ch in d1["chars"]:
        return ch
    simp = d1.get("t2s", {}).get(ch)
    return simp if simp in d1["chars"] else None


def readings(d1, ch):
    """返回该字的全部读法；未收录返回 []。自动处理繁体输入。"""
    key = norm(d1, ch)
    return d1["chars"][key] if key else []


def tone_options(d1, ch):
    """返回该字的平仄选项集合，如 {'平'} / {'仄'} / {'平','仄'}；未收录 → None。"""
    rs = readings(d1, ch)
    if not rs:
        return None
    return {PING if r["tone"] == "平" else ZE for r in rs}


def has_tone(d1, ch, tone):
    rs = readings(d1, ch)
    return any(r["tone"] == tone for r in rs)


def rhyme_of(d1, ch, tone=None):
    """返回该字所属韵部（可指定四声）；多韵部时返回列表。"""
    rs = readings(d1, ch)
    if tone:
        rs = [r for r in rs if r["tone"] == tone]
    return [r["rhyme"] for r in rs]


def detect_rhyme(d1, lines):
    """由句末字反推韵部（通用：绝句 / 律诗 / 任意句数，平韵仄韵皆可）。

    对每个候选韵部统计「句末字命中它的句号」；取覆盖句数最多者（须 ≥ 2 句）。
    并列时先比覆盖「押韵位（第 2、4 句）」的数目，再比句数，最后按韵部序。
    这样折腰体（第 3 句不入韵）自然只收 1/2/4 句，不误判第 3 句。
    返回 (韵部简称 或 None, 押韵句号列表)。
    """
    if len(lines) < 2:
        return None, []
    cover = {}   # 韵部 → 命中它的句号集合（1 基）
    for i, ln in enumerate(lines):
        for r in set(rhyme_of(d1, ln[-1])):
            cover.setdefault(r, set()).add(i + 1)

    def key(r):
        ls = cover[r]
        return (-len(ls), -len({2, 4} & ls),
                d1["rhymes"][r]["tone_group"], d1["rhymes"][r]["seq"])

    cands = [r for r in cover if len(cover[r]) >= 2]
    if not cands:
        return None, []
    rhyme = sorted(cands, key=key)[0]
    return rhyme, sorted(cover[rhyme])


def detect_form(lines):
    """由句长与句数判体式：五言/七言 × 绝句(4)/律诗(8)/其他。杂言返回 None。"""
    lens = {len(ln) for ln in lines}
    if len(lens) != 1:
        return None
    yan = {5: "五言", 7: "七言"}.get(lens.pop())
    if not yan:
        return None
    n = len(lines)
    if n == 4:
        return yan + "绝句"
    if n == 8:
        return yan + "律诗"
    return "%s%d句" % (yan, n)


def rusheng_chars(d1, lines):
    """全诗含入声读法的字（去重，保持出现次序）。"""
    out = []
    for ln in lines:
        for ch in ln:
            if ch not in out and has_tone(d1, ch, "入"):
                out.append(ch)
    return out



def meter_fill(d1, rows, lines):
    """近体诗「二四六分明」：句内偶数位平仄交替，用于消歧兼平仄字。

    只改「偶数位 + 兼平仄 + 非韵脚」的字；奇数位（一三五不论）不动。
    返回被改写的字数。这是启发式（属卡1「格律解析」），D1 本身只提供选项。
    """
    fixed = 0
    for li, ln in enumerate(lines, 1):
        evens = [p for p in (2, 4, 6) if p <= len(ln)]
        line_rows = {r["col"]: r for r in rows if r["line"] == li}
        resolved = {}
        for p in evens:
            r = line_rows[p]
            if r["tone"] is not None and (not r["ambiguous"] or r.get("resolved_by")):
                resolved[p] = PING if r["tone"] == "level" else ZE
        for p in evens:
            r = line_rows[p]
            if not r["ambiguous"] or r["role"] == "rhyme" or r.get("resolved_by") == "hand":
                continue
            ref = None
            for q in reversed([e for e in evens if e < p]):
                if q in resolved:
                    ref = resolved[q]
                    break
            if ref is None:
                for q in [e for e in evens if e > p]:
                    if q in resolved:
                        ref = resolved[q]
                        break
            if ref is None:
                continue
            want = ZE if ref == PING else PING
            if want == ZE:
                r["tone"] = next(x["code"] for x in readings(d1, r["char"])
                                 if x["code"] in ("oblique", "entering"))
            else:
                r["tone"] = "level"
            r["role"] = r["tone"]
            r["ambiguous"] = False
            r["resolved_by"] = "meter"
            resolved[p] = want
            fixed += 1
    return fixed


def hand_authority(d1, lines, hand_patterns):
    """手工格律的「定夺」：返回 {行号: {列号: '平'/'仄'}}，只采纳与全行非歧义字一致的行。

    hand_patterns 取自 context.json 的 prosody.pingze[].pattern。若某行手工谱与该行任一
    「唯一读法」的字冲突（典型如七绝标准模板被当作实读：标「千」为仄而「千」实为平），
    判为模板/异文，整行不采纳，退回默认读。这样既能「以手工为准」消歧歧义字，又不会被
    模板带偏——是「人工定夺优先 + 一致性校验」，不是无条件照抄。
    """
    auth = {}
    if not hand_patterns:
        return auth
    for li, ln in enumerate(lines, 1):
        hp = hand_patterns[li - 1] if li - 1 < len(hand_patterns) else None
        if not hp or len(hp) != len(ln):
            continue
        ok = True
        for ci, ch in enumerate(ln, 1):
            t = hp[ci - 1]
            opts = tone_options(d1, ch)
            if t in (PING, ZE) and opts and len(opts) == 1 and next(iter(opts)) != t:
                ok = False
                break
        if ok:
            auth[li] = {ci: hp[ci - 1] for ci in range(1, len(ln) + 1)
                        if hp[ci - 1] in (PING, ZE)}
    return auth


def analyze(d1, lines, rhyme=None, meter=False, hand_patterns=None):
    """逐字给出 (tone_code, role) 与歧义标记。

    role: 平声韵脚 → rhyme；入声韵脚 → entering；其余 = tone_code。
    meter=True 时，对偶数位兼平仄字按「二四六分明」消歧。
    兼平仄且非韵脚的字：hand_patterns（context.json 手工谱）能定夺时优先采用（标 resolved_by=hand），
    否则退回默认读（取平）并保留歧义标记 ◐。
    """
    if rhyme is None:
        rhyme, _ = detect_rhyme(d1, lines)
    _, feet = detect_rhyme(d1, lines) if rhyme else (None, [])
    if rhyme:
        feet = [i + 1 for i, ln in enumerate(lines) if rhyme in set(rhyme_of(d1, ln[-1]))]
    auth = hand_authority(d1, lines, hand_patterns)

    rows, unknown, ambiguous = [], [], []
    for li, ln in enumerate(lines, 1):
        for ci, ch in enumerate(ln, 1):
            rs = readings(d1, ch)
            is_foot = (ci == len(ln)) and (li in feet)
            if not rs:
                unknown.append({"line": li, "col": ci, "char": ch})
                rows.append({"line": li, "col": ci, "char": ch, "tone": None,
                             "role": None, "options": None, "ambiguous": None,
                             "resolved_by": None})
                continue
            opts = tone_options(d1, ch)
            amb = opts == {PING, ZE}
            hand = auth.get(li, {}).get(ci) if (amb and not is_foot) else None
            # 选读：韵脚优先匹配韵部；唯一读法直取；兼平仄 → 手工谱优先，否则默认取平
            if is_foot and rhyme in set(rhyme_of(d1, ch)):
                rr = next(r for r in rs if r["rhyme"] == rhyme)
            elif len(opts) == 1:
                rr = rs[0]
            elif hand == ZE:
                rr = next((r for r in rs if r["tone"] != "平"), rs[0])
            else:
                rr = next((r for r in rs if r["tone"] == "平"), rs[0])
            tone = rr["code"]
            role = "rhyme" if (is_foot and rr["tone"] == "平") else tone
            if amb and is_foot:
                resolved_by = "rhyme"     # 韵脚读法由韵部唯一确定，不再以 ◐ 示歧义
            elif amb and hand:
                resolved_by = "hand"
            else:
                resolved_by = None
            if amb and not is_foot:
                ambiguous.append({"line": li, "col": ci, "char": ch,
                                  "options": sorted(opts),
                                  "chosen": PING if tone == "level" else ZE,
                                  "resolved_by": resolved_by})
            rows.append({"line": li, "col": ci, "char": ch, "tone": tone, "role": role,
                         "options": sorted(opts) if opts else None, "ambiguous": amb,
                         "resolved_by": resolved_by})
    if meter:
        meter_fill(d1, rows, lines)
        ambiguous = [{"line": r["line"], "col": r["col"], "char": r["char"],
                      "options": r["options"],
                      "chosen": PING if r["tone"] == "level" else ZE,
                      "resolved_by": r.get("resolved_by") or "meter"}
                     for r in rows if r["ambiguous"]]
    # 每行平仄串：手工定夺或格律消歧的字给出实读，其余歧义位以 ◐ 标
    patterns = []
    for li, ln in enumerate(lines, 1):
        s = ""
        for r in [x for x in rows if x["line"] == li]:
            if r["tone"] is None:
                s += "?"
            elif r["ambiguous"] and not r.get("resolved_by"):
                s += "◐"
            else:
                s += PING if r["tone"] == "level" else ZE
        patterns.append(s)
    return {"rhyme": rhyme, "rhyme_feet_lines": feet, "rows": rows,
            "patterns": patterns, "unknown": unknown, "ambiguous": ambiguous}


def hand_patterns_of(ctx):
    """取 context.json 手工格律谱（prosody.pingze[].pattern）；无则 None。"""
    if not ctx:
        return None
    pz = ctx.get("prosody", {}).get("pingze", [])
    return [x.get("pattern") for x in pz] or None


def analyze_poem(d1, lines, rhyme=None, meter=True, hand_patterns=None):
    """通用入口：任意诗 → 体式 / 韵部 / 韵脚 / 入声字 / 平仄谱 / 逐字三元组。

    meter=True 时按「二四六分明」消歧兼平仄字（近体诗默认）。兼平仄的非韵脚字若 context.json
    手工谱能定夺，则优先采用（见 hand_authority）。三元组取消歧后的结果，与
    src/voice/voice_prosody_process.py 的 (字, tone, role) 消费格式一致。
    """
    res = analyze(d1, lines, rhyme=rhyme, meter=False, hand_patterns=hand_patterns)
    resm = analyze(d1, lines, rhyme=rhyme, meter=meter, hand_patterns=hand_patterns)
    r = resm["rhyme"]
    rtone = d1["rhymes"][r]["tone"] if r else None
    feet_lines = resm["rhyme_feet_lines"]
    # 消费约定（对齐 voice_prosody_process.py）：平声韵脚 tone 与 role 同为 "rhyme"；
    # 入声韵脚 tone=role="entering"；其余 tone=role=平仄码。
    triples = [[row["char"], ("rhyme" if row["role"] == "rhyme" else row["tone"]), row["role"]]
               for row in resm["rows"]]
    lens = {len(x) for x in lines}
    return {
        "lines": lines,
        "form": detect_form(lines),
        "n_syl": lens.pop() if len(lens) == 1 else None,
        "rhyme": r,
        "rhyme_tone": rtone,
        "rhyme_feet": [lines[i - 1][-1] for i in feet_lines],
        "rhyme_feet_lines": feet_lines,
        "rusheng_chars": rusheng_chars(d1, lines),
        "patterns": res["patterns"],
        "patterns_meter": resm["patterns"],
        "syllables": triples,
        "unknown": resm["unknown"],
        "ambiguous": res["ambiguous"],
        "hand_resolved": [a for a in res["ambiguous"] if a.get("resolved_by") == "hand"],
    }


def load_context(pid):
    """读 data/source/context/<诗>/context.json；返回 (context, lines) 或 (None, None)。"""
    title = PID_TITLE.get(pid)
    if not title:
        return None, None
    p = os.path.join(CONTEXT_DIR, title, "context.json")
    if not os.path.exists(p):
        return None, None
    with open(p, encoding="utf-8") as f:
        ctx = json.load(f)
    return ctx, ctx["text"]["base"]


def build_prosody(d1):
    """对全部已登记的诗跑通用解析，返回 d1_prosody 结构。"""
    poems = {}
    for pid in PID_TITLE:
        ctx, lines = load_context(pid)
        if not lines:
            continue
        rec = analyze_poem(d1, lines, hand_patterns=hand_patterns_of(ctx))
        rec["title"] = ctx.get("poem")
        poems[pid] = rec
    return {
        "meta": {
            "name": "d1_prosody",
            "version": "1.1",
            "role": "D1 通用化的产物：由 d1_rhyme.json 自动解析三首诗的体式/韵脚/入声/平仄/三元组；"
                    "替代 context.json 与 voice_prosody_process.py 中手工标注的 prosody。"
                    "v1.1：兼平仄的非韵脚字以 context.json 手工谱定夺（经全行一致性校验，见 hand_authority），"
                    "避免启发式默认读在「一三五不论」位取错（如「望」误取平）。",
            "source": "data/derived/d1_rhyme.json + data/source/context/<诗>/context.json（text.base + prosody.pingze）",
            "consumption": "voice_prosody_process.py 的 (字,tone,role)；卡1 格律；O2 分词格律先验",
        },
        "poems": poems,
    }


def check_prosody(d1):
    """护栏：自动解析 vs ① context.json 手工 prosody ② voice 手工三元组。

    硬判据（不通过则退出码 1）：
      · 覆盖率 100%（三首诗无未收录字）
      · 体式一致
      · 韵脚字一致
      · 韵部声类一致（平 / 仄 / 入）
      · voice 三元组：平仄选项命中 100%
    软记录（仅报告，供人工复核）：
      · 平仄谱逐句差异（手工谱在「一三五不论」位可能与逐字实读不同；或手工谱整行为标准模板）
      · 入声字集合差异（手工标注可能只记韵脚）
      · 手工定夺：兼平仄字被手工谱改写为实读的清单（默认启发式会取平）
    """
    gt = extract_ground_truth()
    rep = {"poems": {}, "summary": {}}
    hard_fail = 0
    for pid, lines in POEM_LINES.items():
        ctx, clines = load_context(pid)
        rec = analyze_poem(d1, lines, hand_patterns=hand_patterns_of(ctx))
        p = {"auto": {"form": rec["form"], "rhyme": rec["rhyme"],
                      "rhyme_tone": rec["rhyme_tone"], "rhyme_feet": rec["rhyme_feet"],
                      "rusheng": rec["rusheng_chars"], "patterns_meter": rec["patterns_meter"]},
             "hand_resolved": rec.get("hand_resolved", []),
             "issues": [], "notes": []}
        if clines and clines != lines:
            p["issues"].append("context.text.base 与 POEM_LINES 不一致")
        if ctx:
            hp = ctx["prosody"]
            if rec["form"] and hp.get("form") and rec["form"] != hp["form"]:
                p["issues"].append("体式不一致：auto=%s hand=%s" % (rec["form"], hp["form"]))
            if hp.get("rhyme_feet") and rec["rhyme_feet"] != hp["rhyme_feet"]:
                p["issues"].append("韵脚不一致：auto=%s hand=%s"
                                   % (rec["rhyme_feet"], hp["rhyme_feet"]))
            hg = hp.get("rhyme_group", "")
            h_tone = next((t for t in ("入声", "平声", "上声", "去声") if t in hg), None)
            if h_tone and rec["rhyme_tone"]:
                a_tone = {"入": "入声", "平": "平声", "上": "上声", "去": "去声"}[rec["rhyme_tone"]]
                if a_tone != h_tone:
                    p["issues"].append("韵部声类不一致：auto=%s hand=%s" % (a_tone, h_tone))
            h_pz = [x.get("pattern") for x in hp.get("pingze", [])]
            if h_pz and h_pz != rec["patterns_meter"]:
                p["notes"].append({"平仄谱差异": {"auto": rec["patterns_meter"], "hand": h_pz}})
            h_ru = hp.get("rusheng_chars")
            if h_ru is not None and h_ru != rec["rusheng_chars"]:
                p["notes"].append({"入声字差异": {"auto": rec["rusheng_chars"], "hand": h_ru}})
            if rec.get("hand_resolved"):
                p["notes"].append({"手工定夺（歧义字以手工谱为准）": [
                    {"char": a["char"], "line": a["line"], "col": a["col"],
                     "hand": a["chosen"], "default": PING}
                    for a in rec["hand_resolved"]]})
        # voice 三元组命中
        manual = gt[pid]["syllables"]
        hit = sum(1 for (mch, mtone, _), (ch, tone, _r)
                  in zip(manual, rec["syllables"])
                  if mch == ch and CODE2ZE.get(mtone, ZE) in tone_options(d1, ch))
        p["voice_option_hit"] = {"hit": hit, "total": len(manual)}
        if hit != len(manual):
            p["issues"].append("voice 三元组平仄选项未全覆盖 %d/%d" % (hit, len(manual)))
        # 三元组逐字差异（软记录）：多为「一三五不论」位的兼平仄字，自动取默认读
        p["triple_mismatch"] = [
            {"i": i, "auto": list(a), "manual": list(m)}
            for i, (m, a) in enumerate(zip(manual, rec["syllables"])) if list(a) != list(m)]
        if rec["unknown"]:
            p["issues"].append("有未收录字：%s" % [u["char"] for u in rec["unknown"]])
        if p["issues"]:
            hard_fail += 1
        rep["poems"][pid] = p
    rep["summary"] = {
        "poems": len(rep["poems"]),
        "hard_fail": hard_fail,
        "all_pass": hard_fail == 0,
    }
    return rep


def extract_ground_truth():
    """从 voice_prosody_process.py 提取手工标注的 POEMS（纯字面量，ast 安全解析）。"""
    with open(VOICE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "POEMS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("未找到 POEMS")


POEM_LINES = {
    "jys": ["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"],
    "jx": ["千山鸟飞绝", "万径人踪灭", "孤舟蓑笠翁", "独钓寒江雪"],
    "bd": ["朝辞白帝彩云间", "千里江陵一日还", "两岸猿声啼不住", "轻舟已过万重山"],
}


def regression(d1):
    gt = extract_ground_truth()
    report = {"poems": {}, "summary": {}}
    tot = hit_opt = hit_auto = hit_meter = amb_n = unk_n = 0
    for key, lines in POEM_LINES.items():
        manual = gt[key]["syllables"]
        res = analyze(d1, lines)
        res_m = analyze(d1, lines, meter=True)
        flat = [r for r in res["rows"]]
        flat_m = [r for r in res_m["rows"]]
        assert len(flat) == len(manual), (key, len(flat), len(manual))
        mism_auto, mism_opt, unknown = [], [], []
        for i, (r, rm, (mch, mtone, mrole)) in enumerate(zip(flat, flat_m, manual)):
            tot += 1
            if mch != r["char"]:
                unknown.append({"i": i, "expect": mch, "got": r["char"]})
                continue
            if r["options"] is None:
                unk_n += 1
                unknown.append({"i": i, "char": r["char"], "reason": "D1 未收录"})
                continue
            manual_ze = CODE2ZE.get(mtone, ZE)     # rhyme→平；entering/oblique→仄
            auto_ze = PING if r["tone"] == "level" else ZE
            meter_ze = PING if rm["tone"] == "level" else ZE
            if manual_ze in r["options"]:
                hit_opt += 1
            else:
                mism_opt.append({"i": i, "char": r["char"], "manual": mtone,
                                 "manual_ze": manual_ze, "options": r["options"]})
            if manual_ze == auto_ze:
                hit_auto += 1
            else:
                mism_auto.append({"i": i, "char": r["char"], "manual": mtone,
                                  "manual_ze": manual_ze, "auto_ze": auto_ze})
            if manual_ze == meter_ze:
                hit_meter += 1
            if r["ambiguous"]:
                amb_n += 1
        report["poems"][key] = {
            "lines": lines,
            "detected_rhyme": res["rhyme"],
            "rhyme_feet_lines": res["rhyme_feet_lines"],
            "patterns": res["patterns"],
            "patterns_meter": res_m["patterns"],
            "ambiguous_chars": res["ambiguous"],
            "mismatch_options": mism_opt,
            "mismatch_auto": mism_auto,
            "unknown": unknown,
        }
    report["summary"] = {
        "chars_total": tot,
        "coverage": round((tot - unk_n) / tot, 4),
        "option_hit_rate": round(hit_opt / tot, 4),
        "auto_hit_rate": round(hit_auto / tot, 4),
        "meter_hit_rate": round(hit_meter / tot, 4),
        "ambiguous_chars": amb_n,
        "unknown_chars": unk_n,
    }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", help="以 | 分隔的诗句，直接输出 (字,平仄,角色) 三元组")
    ap.add_argument("--poem", help="诗 id（%s），输出该诗的通用解析" % "/".join(PID_TITLE))
    ap.add_argument("--check", action="store_true", help="只跑护栏：自动解析 vs 手工 prosody / voice 三元组")
    ap.add_argument("--no-build", action="store_true", help="默认模式下不写 d1_prosody.json")
    args = ap.parse_args()
    d1 = load_d1()

    if args.lines:
        lines = [s.strip() for s in args.lines.split("|") if s.strip()]
        res = analyze(d1, lines)
        print(f"体式：{detect_form(lines)}  韵部：{res['rhyme']}  押韵句：{res['rhyme_feet_lines']}")
        print(f"平仄串：{' '.join(res['patterns'])}")
        print("三元组：")
        for r in res["rows"]:
            print(f"  (\"{r['char']}\", \"{r['tone']}\", \"{r['role']}\")")
        return

    if args.poem:
        ctx, lines = load_context(args.poem)
        if not lines:
            raise SystemExit("未知诗 id 或无 context.json：%s" % args.poem)
        rec = analyze_poem(d1, lines)
        print(f"[{args.poem}] {rec['title']}  {rec['form']}  韵部={rec['rhyme']}（{rec['rhyme_tone']}）")
        print(f"     韵脚={rec['rhyme_feet']}（句 {rec['rhyme_feet_lines']}）  入声字={rec['rusheng_chars']}")
        print(f"     平仄谱={rec['patterns_meter']}")
        print("     三元组=" + " ".join("(%s,%s,%s)" % tuple(s) for s in rec["syllables"]))
        return

    if args.check:
        chk = check_prosody(d1)
        _write(CHECK_OUT, chk)
        _print_check(chk)
        if not chk["summary"]["all_pass"]:
            sys.exit(1)
        return

    rep = regression(d1)
    _write(OUT, rep)
    s = rep["summary"]
    print("=" * 56)
    for key, p in rep["poems"].items():
        print(f"[{key}] 韵部={p['detected_rhyme']}  押韵句={p['rhyme_feet_lines']}")
        print(f"     平仄串(默认)={p['patterns']}")
        print(f"     平仄串(二四六分明)={p['patterns_meter']}")
        if p["ambiguous_chars"]:
            print(f"     兼平仄字={[a['char'] + '(' + '/'.join(a['options']) + ')' for a in p['ambiguous_chars']]}")
        if p["mismatch_options"]:
            print(f"     ⚠ 选项未覆盖={p['mismatch_options']}")
        if p["mismatch_auto"]:
            print(f"     自动选读错={[(m['char'], m['manual'], m['auto_ze']) for m in p['mismatch_auto']]}")
        if p["unknown"]:
            print(f"     ⚠ 未收录={p['unknown']}")
    print("=" * 56)
    print(f"逐字总数 {s['chars_total']} | 覆盖率 {s['coverage']:.1%} | 选项命中 {s['option_hit_rate']:.1%} "
          f"| 自动选读命中 {s['auto_hit_rate']:.1%} | 二四六分明命中 {s['meter_hit_rate']:.1%} "
          f"| 兼平仄 {s['ambiguous_chars']} | 未收录 {s['unknown_chars']}")
    print(f"报告 → {OUT}")

    if not args.no_build:
        pro = build_prosody(d1)
        _write(PROSODY, pro)
        print(f"[D1·通用] 派生 → {PROSODY}（{len(pro['poems'])} 首）")

    chk = check_prosody(d1)
    _write(CHECK_OUT, chk)
    _print_check(chk)
    if not chk["summary"]["all_pass"]:
        sys.exit(1)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _print_check(chk):
    print("=" * 56)
    print("[D1·护栏] 自动解析 vs 手工标注")
    for pid, p in chk["poems"].items():
        a = p["auto"]
        print(f"[{pid}] {a['form']} 韵={a['rhyme']}({a['rhyme_tone']}) 韵脚={a['rhyme_feet']} "
              f"voice 选项命中 {p['voice_option_hit']['hit']}/{p['voice_option_hit']['total']}"
              f"  三元组差异 {len(p['triple_mismatch'])}")
        for it in p["issues"]:
            print("     ✗ " + it)
        for n in p["notes"]:
            for k, v in n.items():
                if isinstance(v, dict):
                    print(f"     · {k}：auto={v['auto']} hand={v['hand']}")
                else:
                    print("     · %s：%s" % (k, "; ".join(
                        "%s(句%d·%d) hand=%s 默认=%s" % (x["char"], x["line"], x["col"],
                                                          x["hand"], x["default"]) for x in v)))
        for m in p["triple_mismatch"]:
            print(f"     · 三元组[{m['i']}] auto={m['auto']} manual={m['manual']}")
    s = chk["summary"]
    print(f"[D1·护栏] {s['poems']} 首 | {'✓ 全通过' if s['all_pass'] else '✗ 硬判据失败 %d 首' % s['hard_fail']}"
          f" → {CHECK_OUT}")


if __name__ == "__main__":
    main()
