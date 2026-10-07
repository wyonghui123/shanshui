# -*- coding: utf-8 -*-
"""D1 中古音韵书 · 构建脚本

输入：data/source/rhyme/pingshui_rhyme_dict.json（pingshui-rhyme 0.20 预抓取数据，MIT；
      底本 = 维基文库《平水韻》，公有领域）
输出：d1_rhyme.json —— 字→四声(平/上/去/入)+韵部 的查询表，供 O1 格律解析与卡1语音韵律查表。

设计原则（对齐 voice_prosody_process.py 的消费格式）：
  tone  平/上/去/入  →  level / oblique / oblique / entering
  role  平声韵脚     →  rhyme（拖长）；其余 role = tone
"""
import json
import os
import sys
from collections import Counter

import zhconv  # 仅构建期使用：把源数据（繁体）归一到简体索引

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

SRC = os.path.join(ROOT, "data", "source", "rhyme", "pingshui_rhyme_dict.json")
SUPP = os.path.join(ROOT, "data", "source", "d1_supplement.json")
OUT = os.path.join(ROOT, "data", "derived", "d1_rhyme.json")

# 声调组 → (四声, 声组名)。平水韵 106 部：上平15 + 下平15 + 上29 + 去30 + 入17。
TONE_GROUPS = [
    ("上平聲部", "平", "上平"),
    ("下平聲部", "平", "下平"),
    ("上聲部", "上", "上"),
    ("去聲部", "去", "去"),
    ("入聲部", "入", "入"),
]
# 四声 → 平仄码（voice_prosody_process.py 的 tone 字段）
TONE_CODE = {"平": "level", "上": "oblique", "去": "oblique", "入": "entering"}

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
           "九": 9, "十": 10}


_NUM_CHARS = set("一二三四五六七八九十")


def lead_num(s: str) -> str:
    """取韵部名开头的中文数字部分：一東→一；十灰→十；十一真→十一；二十九豏→二十九"""
    i = 0
    while i < len(s) and s[i] in _NUM_CHARS:
        i += 1
    return s[:i]


def cn_num(s: str) -> int:
    """解析韵部序号的中文数字：一→1 十→10 十一→11 二十→20 二十九→29 三十→30"""
    if "十" not in s:
        return _CN_NUM[s]
    left, _, right = s.partition("十")
    tens = _CN_NUM[left] if left else 1
    ones = _CN_NUM[right] if right else 0
    return tens * 10 + ones


def strip_prefix(rhyme_full: str, tone_group: str) -> str:
    """上平聲一東 → 一東；上聲一董 → 一董"""
    prefix = {"上平": "上平聲", "下平": "下平聲", "上": "上聲",
              "去": "去聲", "入": "入聲"}[tone_group]
    return rhyme_full[len(prefix):] if rhyme_full.startswith(prefix) else rhyme_full


def main() -> None:
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)

    rhymes = {}      # 韵部简称 → 记录
    chars = {}       # 简体字 → [读法...]
    t2s = {}         # 繁体字 → 简体字（供繁体输入归一，构建期由 zhconv 生成）
    order = []       # 保持 106 部顺序

    for bucket in ("ping", "ze"):
        for tone_group_key, tone, tg_short in TONE_GROUPS:
            group = src[bucket].get(tone_group_key, {})
            for rhyme_full, char_list in group.items():
                rhyme = strip_prefix(rhyme_full, tg_short)
                seq = cn_num(lead_num(rhyme))
                # 源数据每个韵部的字以「单元素列表内一整串」存储，需拼回后再逐字拆
                char_str = "".join(char_list)
                rec = {
                    "rhyme": rhyme,
                    "rhyme_full": rhyme_full,
                    "tone": tone,
                    "tone_group": tg_short,
                    "seq": seq,
                    "n": len(char_str),
                }
                rhymes[rhyme] = rec
                order.append(rhyme)
                for ch in char_str:
                    simp = zhconv.convert(ch, "zh-cn")
                    t2s[ch] = simp
                    chars.setdefault(simp, []).append({
                        "tone": tone,
                        "tone_group": tg_short,
                        "rhyme": rhyme,
                        "code": TONE_CODE[tone],
                        "src": rhyme_full,
                        "trad": ch,
                    })

    # 补遗层：主表漏收的常用字（人工、有据、宁缺毋滥）
    n_supp = 0
    if os.path.exists(SUPP):
        with open(SUPP, encoding="utf-8") as f:
            supp = json.load(f)
        for ch, rec in supp["chars"].items():
            if rec["rhyme"] not in rhymes:
                raise SystemExit(f"补遗韵部不存在：{ch} → {rec['rhyme']}")
            if rec.get("trad"):
                t2s[rec["trad"]] = ch
            chars.setdefault(ch, []).append({
                "tone": rec["tone"],
                "tone_group": rec["tone_group"],
                "rhyme": rec["rhyme"],
                "code": TONE_CODE[rec["tone"]],
                "src": "补遗",
                "trad": rec.get("trad", ch),
            })
            n_supp += 1

    # 去重同一字的重复读法（同韵部重复收录时）
    for ch, reads in chars.items():
        seen, uniq = set(), []
        for r in reads:
            key = (r["tone"], r["rhyme"])
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        chars[ch] = uniq

    # 统计
    n_multi = sum(1 for v in chars.values() if len(v) > 1)
    n_jianpingze = sum(1 for v in chars.values()
                       if {r["code"] for r in v} & {"level"}
                       and {r["code"] for r in v} & {"oblique", "entering"})
    n_ru = sum(1 for v in chars.values() if any(r["tone"] == "入" for r in v))
    tone_counter = Counter(r["tone"] for v in chars.values() for r in v)

    meta = {
        "name": "d1_rhyme",
        "version": "1.0",
        "generated": "2026-10-03",
        "standard": "平水韵（106 部：上平15 下平15 上29 去30 入17）",
        "purpose": "字 → 四声(平/上/去/入) + 韵部；供 O1 格律解析与卡1语音韵律查表。"
                   "替代 src/voice/voice_prosody_process.py 中手工标注的 (字,平仄,角色) 三元组。",
        "consumption": {
            "tone_code": TONE_CODE,
            "role_rule": "平声韵脚 → role=rhyme（拖长，×1.65）；入声韵脚 role=entering（×0.65）；其余 role=tone",
        },
        "index": {
            "key": "简体字（chars 以简体为键；每读法带 trad 字段回溯源字形）",
            "t2s": "繁体字 → 简体字；供繁体输入归一（解析器无需再依赖 zhconv）",
            "normalize": "查询时先查 chars[ch]；未命中则查 t2s[ch] 再查 chars",
        },
        "source": {
            "package": "pingshui-rhyme 0.20",
            "author": "rbnyng",
            "repo": "https://github.com/rbnyng/pingshui_rhyme",
            "license": "MIT",
            "upstream": "维基文库《平水韻》 https://zh.wikisource.org/wiki/平水韻 （底本公有领域）",
            "vendored_file": "data/source/rhyme/pingshui_rhyme_dict.json",
            "retrieved": "2026-10-03",
        },
        "counts": {
            "rhymes": len(rhymes),
            "unique_chars": len(chars),
            "readings": sum(len(v) for v in chars.values()),
            "multi_reading_chars": n_multi,
            "jian_ping_ze_chars": n_jianpingze,
            "chars_with_ru": n_ru,
            "supplement_chars": n_supp,
            "by_tone": dict(tone_counter),
        },
        "supplement_file": "d1_supplement.json",
    }

    out = {"meta": meta, "rhymes": {r: rhymes[r] for r in order},
           "chars": chars, "t2s": t2s}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[D1] 韵部 {len(rhymes)} 部 | 收字 {len(chars)} 个 | 读法 {meta['counts']['readings']} 条 | 补遗 {n_supp}")
    print(f"[D1] 多音字 {n_multi} | 兼平仄 {n_jianpingze} | 含入声字 {n_ru}")
    print(f"[D1] 四声分布 {dict(tone_counter)}")
    print(f"[D1] 写出 → {OUT}")


if __name__ == "__main__":
    main()
