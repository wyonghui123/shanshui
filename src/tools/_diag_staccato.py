# -*- coding: utf-8 -*-
"""量化「逐音节阶跃伸缩」造成的顿挫：输出每音节目标时长与相邻边界的瞬时速度跳变。

背景：voice_prosody_process.py 里 stretch[fs:fe] = DUR_FACTOR[role] 是逐音节的
分段常数（阶跃）。输出端每个音节的时长 = 源帧数 × 该常数；边界处局部播放速度
瞬时跳变，听感即「一个字一个字」。本脚本把这个跳变量化出来。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

import sys
import math

FACTOR = {"level": 1.35, "oblique": 0.85, "entering": 0.65, "rhyme": 1.65}
FP = 5.0  # frame_period ms


def analyze(path, dur_scale):
    m = json.load(open(path, encoding="utf-8"))
    syl = m["syllables"]
    rows = []
    for s in syl:
        d = s["frames"] * FACTOR[s["role"]] * dur_scale * FP
        rows.append((s["line"], s["pos"], s["char"], s["role"], s["frames"], d))

    print("== " + os.path.basename(path) + "  dur_scale=" + str(dur_scale) + " ==")
    line = None
    buf_ch, buf_d = [], []
    for li, pos, ch, role, fr, d in rows:
        if li != line:
            if line is not None:
                print("  行%d  字 %s" % (line, " ".join(buf_ch)))
                print("        时长 %s ms" % " ".join("%4.0f" % x for x in buf_d))
            line = li
            buf_ch, buf_d = [], []
        buf_ch.append(ch)
        buf_d.append(d)
    print("  行%d  字 %s" % (line, " ".join(buf_ch)))
    print("        时长 %s ms" % " ".join("%4.0f" % x for x in buf_d))

    ratios = []
    prev = None
    for li, pos, ch, role, fr, d in rows:
        if prev is not None and pos != 1:
            ratios.append(FACTOR[role] / FACTOR[prev])
        prev = role
    logs = [abs(math.log2(r)) for r in ratios]
    print("  边界速度跳变 ×%.2f … ×%.2f   最大 %.2f×   平均 |log2| = %.3f (≈ %.2f 倍)"
          % (min(ratios), max(ratios), max(ratios), sum(logs) / len(logs), 2 ** (sum(logs) / len(logs))))
    print()


if __name__ == "__main__":
    base = os.path.join(ROOT, "dist", "audio", "voice")
    for name, ds in [("jx_emotion_cold_zh-CN-YunjianNeural.json", 1.16),
                     ("bd_emotion_joy_zh-CN-YunjianNeural.json", 0.94),
                     ("jys_emotion_sad_zh-CN-YunjianNeural.json", 1.11)]:
        p = os.path.join(base, name)
        if os.path.exists(p):
            analyze(p, ds)
