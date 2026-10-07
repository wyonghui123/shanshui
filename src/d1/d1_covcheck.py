# -*- coding: utf-8 -*-
"""D1 覆盖率工装：在常见近体诗语料上统计 D1 的查得率，输出 d1_coverage.json。

用途：D1 的「可度量」护栏——换源/加补遗后重跑，确认覆盖率不降。
用法：python src/d1/d1_covcheck.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

D1 = os.path.join(ROOT, "data", "derived", "d1_rhyme.json")
OUT = os.path.join(ROOT, "data", "runs", "d1_coverage.json")

# 语料：20 首常见近体诗（绝句为主），代表项目目标域
CORPUS = {
    "静夜思": "床前明月光疑是地上霜举头望明月低头思故乡",
    "江雪": "千山鸟飞绝万径人踪灭孤舟蓑笠翁独钓寒江雪",
    "早发白帝城": "朝辞白帝彩云间千里江陵一日还两岸猿声啼不住轻舟已过万重山",
    "登鹳雀楼": "白日依山尽黄河入海流欲穷千里目更上一层楼",
    "春晓": "春眠不觉晓处处闻啼鸟夜来风雨声花落知多少",
    "相思": "红豆生南国春来发几枝愿君多采撷此物最相思",
    "鹿柴": "空山不见人但闻人语响返景入深林复照青苔上",
    "竹里馆": "独坐幽篁里弹琴复长啸深林人不知明月来相照",
    "送别": "山中相送罢日暮掩柴扉春草明年绿王孙归不归",
    "悯农": "锄禾日当午汗滴禾下土谁知盘中餐粒粒皆辛苦",
    "望庐山瀑布": "日照香炉生紫烟遥看瀑布挂前川飞流直下三千尺疑是银河落九天",
    "绝句": "两个黄鹂鸣翠柳一行白鹭上青天窗含西岭千秋雪门泊东吴万里船",
    "赠汪伦": "李白乘舟将欲行忽闻岸上踏歌声桃花潭水深千尺不及汪伦送我情",
    "黄鹤楼送孟浩然之广陵": "故人西辞黄鹤楼烟花三月下扬州孤帆远影碧空尽唯见长江天际流",
    "山行": "远上寒山石径斜白云生处有人家停车坐爱枫林晚霜叶红于二月花",
    "泊船瓜洲": "京口瓜洲一水间钟山只隔数重山春风又绿江南岸明月何时照我还",
    "枫桥夜泊": "月落乌啼霜满天江枫渔火对愁眠姑苏城外寒山寺夜半钟声到客船",
    "出塞": "秦时明月汉时关万里长征人未还但使龙城飞将在不教胡马度阴山",
    "凉州词": "葡萄美酒夜光杯欲饮琵琶马上催醉卧沙场君莫笑古来征战几人回",
    "九月九日忆山东兄弟": "独在异乡为异客每逢佳节倍思亲遥知兄弟登高处遍插茱萸少一人",
}


def main():
    d = json.load(open(D1, encoding="utf-8"))
    chars, t2s = set(d["chars"]), d["t2s"]

    def known(ch):
        return ch in chars or (t2s.get(ch) in chars)

    per_poem, missing, tot = {}, set(), 0
    for title, text in CORPUS.items():
        miss = [c for c in text if not known(c)]
        tot += len(text)
        missing |= set(miss)
        per_poem[title] = {"chars": len(text), "missing": miss}

    report = {
        "meta": {
            "role": "D1 覆盖率护栏：换源/加补遗后重跑，确认不降。",
            "corpus_size": len(CORPUS),
            "d1_chars": len(chars),
            "d1_source": d["meta"]["source"]["package"],
        },
        "summary": {
            "chars_total": tot,
            "missing_total": sum(len(v["missing"]) for v in per_poem.values()),
            "coverage": round(1 - sum(len(v["missing"]) for v in per_poem.values()) / tot, 4),
            "missing_unique": sorted(missing),
        },
        "per_poem": per_poem,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    s = report["summary"]
    print(f"[D1·覆盖] 语料 {len(CORPUS)} 首 / {s['chars_total']} 字 | 覆盖率 {s['coverage']:.1%} "
          f"| 缺 {s['missing_total']} 字（{len(s['missing_unique'])} 个不同）")
    if s["missing_unique"]:
        print(f"[D1·覆盖] 缺失字：{''.join(s['missing_unique'])}")
    print(f"[D1·覆盖] 报告 → {OUT}")


if __name__ == "__main__":
    main()
