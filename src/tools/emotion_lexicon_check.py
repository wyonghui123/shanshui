# -*- coding: utf-8 -*-
"""D6 · 情感词表护栏：结构校验 + 字面情感统计（ρ/H 的统计前提）。

结构：data/source/emotion_lexicon.json 的 meta / taxonomy / words 三段齐备；
      每词 cat ∈ taxonomy、kind ∈ {qing,jing}、i ∈ [0,1]；每类 V/A/T 在量程内。
统计：对每首已登记诗（取 context.text.base），按「最长匹配」扫描情感词，算
      · 情语密度 q = Σi(情语) / 总字数
      · 景语密度 j = Σi(景语) / 总字数
      · 字面情感底色 ŷ_literal = Σ i·anchor(cat) / Σ i（情语 + 景语加权）
      ρ / H 本身属卡3（示意式 ρ=d(y,ŷ_literal)、韵味∝H(情感|字面)），本护栏只提供
      ŷ_literal 的可算输入，不裁定 ρ/H 数值。

硬判据（不通过则退出码 1）：
  · 结构合法（cat 可解析、kind/i 合规、V/A/T 在量程）
  · 江雪「直接情感词数 = 0」（卡3 关键事实，model_cards.md §卡片3）
  · 静夜思「含情语」（诗中「思」为直接情感词）
  · 每首诗的 ŷ_literal 可算（无缺 anchor）

用法：
    python src/tools/emotion_lexicon_check.py     # 校验并写 data/runs/emotion_lexicon.json
退出码：0 全通过；1 有错误。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LEX = os.path.join(ROOT, "data", "source", "emotion_lexicon.json")
CONTEXT_DIR = os.path.join(ROOT, "data", "source", "context")
OUT = os.path.join(ROOT, "data", "runs", "emotion_lexicon.json")

# 诗 id ↔ 语境目录（与 d1_resolve.PID_TITLE 同源；新诗加入时在此登记）
PID_TITLE = {"jx": "江雪", "jys": "静夜思", "bd": "早发白帝城"}
KINDS = ("qing", "jing")
RANGES = {"V": (-1.0, 1.0), "A": (0.0, 1.0), "T": (0.0, 1.0)}


def load_lexicon(path=LEX):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def struct_errors(lex):
    """结构校验：三段齐备 + 每词可解析 + 量程合规。"""
    errs = []
    for k in ("meta", "taxonomy", "words"):
        if k not in lex:
            errs.append("缺顶层字段 %r" % k)
    if errs:
        return errs
    tax = lex["taxonomy"]
    for cat, a in tax.items():
        for dim, (lo, hi) in RANGES.items():
            v = a.get(dim)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append("taxonomy.%s.%s 非数值" % (cat, dim))
            elif not (lo <= v <= hi):
                errs.append("taxonomy.%s.%s=%s 越界 [%s,%s]" % (cat, dim, v, lo, hi))
    for w, e in lex["words"].items():
        if e.get("cat") not in tax:
            errs.append("words.%s.cat=%r 不在 taxonomy" % (w, e.get("cat")))
        if e.get("kind") not in KINDS:
            errs.append("words.%s.kind=%r 非 %s" % (w, e.get("kind"), KINDS))
        i = e.get("i")
        if not isinstance(i, (int, float)) or isinstance(i, bool) or not (0.0 <= i <= 1.0):
            errs.append("words.%s.i=%r 越界 [0,1]" % (w, i))
        if not e.get("gloss"):
            errs.append("words.%s 缺 gloss" % w)
    return errs


def scan(text, words, maxlen):
    """最长匹配扫描：返回命中列表 [{'w','cat','kind','i','code','pos'}]。"""
    hits, i, n = [], 0, len(text)
    while i < n:
        for L in range(min(maxlen, n - i), 0, -1):
            w = text[i:i + L]
            if w in words:
                e = words[w]
                hits.append({"w": w, "cat": e["cat"], "kind": e["kind"],
                             "i": e["i"], "code": e.get("code"), "pos": i})
                i += L
                break
        else:
            i += 1
    return hits


def literal_profile(hits, tax):
    """字面情感底色 ŷ_literal = Σ i·anchor(cat) / Σ i（情语 + 景语加权）。"""
    sw = sum(h["i"] for h in hits)
    if sw == 0:
        return None, 0.0
    return {d: round(sum(h["i"] * tax[h["cat"]][d] for h in hits) / sw, 4)
            for d in ("V", "A", "T")}, sw


def load_poems():
    poems = {}
    for pid, title in PID_TITLE.items():
        p = os.path.join(CONTEXT_DIR, title, "context.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            ctx = json.load(f)
        poems[pid] = {"title": ctx.get("poem", title), "lines": ctx["text"]["base"]}
    return poems


def main():
    lex = load_lexicon()
    errs = struct_errors(lex)
    tax, words = lex["taxonomy"], lex["words"]
    maxlen = max(len(w) for w in words)
    n_qing = sum(1 for e in words.values() if e["kind"] == "qing")

    poems = load_poems()
    rep_poems = {}
    checks = []
    for pid, po in poems.items():
        text = "".join(po["lines"])
        hits = scan(text, words, maxlen)
        qing = [h for h in hits if h["kind"] == "qing"]
        jing = [h for h in hits if h["kind"] == "jing"]
        naive = [h for h in hits if not h.get("code")]   # 字面剖面（不含文化代码词）
        coded = [h for h in hits if h.get("code")]        # 文化代码词（义在传统中）
        ylit, _ = literal_profile(naive, tax)
        ylit_all, _ = literal_profile(hits, tax)
        N = len(text)
        rep_poems[pid] = {
            "title": po["title"], "n_chars": N,
            "qing": qing, "jing": jing, "coded": coded,
            "qing_count": len(qing),
            "qing_density": round(sum(h["i"] for h in qing) / N, 4),
            "jing_density": round(sum(h["i"] for h in jing) / N, 4),
            "y_literal": ylit,
            "y_literal_with_code": ylit_all,
        }
        if ylit is None and naive:
            errs.append("%s: 命中词但 ŷ_literal 不可算" % pid)

    # 硬判据（真源：docs/design/model_cards.md §卡片3）
    jx = rep_poems.get("jx", {})
    if jx.get("qing_count") != 0:
        errs.append("江雪「直接情感词数」应为 0，实为 %d：%s"
                    % (jx.get("qing_count"), [h["w"] for h in jx.get("qing", [])]))
    else:
        checks.append("江雪 情语数 = 0 ✓（卡3 关键事实）")
    jys = rep_poems.get("jys", {})
    if jys.get("qing_count", 0) < 1:
        errs.append("静夜思应含情语（「思」），实为 %d" % jys.get("qing_count", 0))
    else:
        checks.append("静夜思 含情语 %s ✓" % [h["w"] for h in jys["qing"]])

    # 字面剖面方向（真源：model_cards.md §卡片3 对两首诗的字面描述）
    bd = rep_poems.get("bd", {})
    if bd.get("y_literal") and bd["y_literal"]["V"] <= 0:
        errs.append("白帝城字面剖面应偏正（卡3「字面上全是欢快」），实为 V=%s"
                    % bd["y_literal"]["V"])
    elif bd.get("y_literal"):
        checks.append("白帝城 字面剖面 V=%s > 0 ✓（卡3「字面上全是欢快」）"
                      % bd["y_literal"]["V"])
    if jx.get("y_literal") and jx["y_literal"]["V"] >= 0:
        errs.append("江雪字面剖面应偏负（孤/寒），实为 V=%s" % jx["y_literal"]["V"])
    elif jx.get("y_literal"):
        checks.append("江雪 字面剖面 V=%s < 0 ✓（孤/寒之景）" % jx["y_literal"]["V"])

    rep = {
        "meta": {"name": "emotion_lexicon_report", "version": "1.0",
                 "role": "D6 护栏：情感词表结构 + 字面情感统计（ρ/H 统计前提）",
                 "note": "ρ/H 属卡3，本报告只给 ŷ_literal 与密度，不裁定 ρ/H 数值。"},
        "lexicon": {"taxonomy": len(tax), "words": len(words), "qing": n_qing,
                    "jing": len(words) - n_qing},
        "poems": rep_poems,
        "checks": checks,
        "errors": errs,
        "summary": {"poems": len(rep_poems), "errors": len(errs), "all_pass": not errs},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)

    print("[D6·情感词表] taxonomy %d 类 · words %d（情语 %d / 景语 %d）"
          % (len(tax), len(words), n_qing, len(words) - n_qing))
    for pid, p in rep_poems.items():
        y, ya = p["y_literal"], p["y_literal_with_code"]
        print("  [%s] %s  %d 字 | 情语 %d（密度 %.3f）· 景语 %d · 代码词 %d"
              % (pid, p["title"], p["n_chars"], p["qing_count"], p["qing_density"],
                 len(p["jing"]), len(p["coded"])))
        print("       ŷ_literal(字面) V=%s A=%s T=%s ｜ 含代码 V=%s A=%s T=%s"
              % (y["V"] if y else "—", y["A"] if y else "—", y["T"] if y else "—",
                 ya["V"] if ya else "—", ya["A"] if ya else "—", ya["T"] if ya else "—"))
    for c in checks:
        print("  ✓ " + c)
    for e in errs:
        print("  ✗ " + e)
    print("  %s → %s" % ("✓ 全通过" if not errs else "✗ %d 处错误" % len(errs), OUT))
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()
