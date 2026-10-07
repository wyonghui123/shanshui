#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查筝采样库对「五声调式音阶」的覆盖，而非对半音阶的覆盖。

关键事实：素材是 Pufermufin 的一把 D 五声音阶古筝（作者自述 tuned in D
pentatonic）。五声音阶天然只有 5 个音级（宫商角徵羽），不存在 3 音（mi）
与 6 音（la/b）的对应半音。所以「缺 E3/F#3/A#3/C4」不是素材缺陷，
而是五声调式本来就不用那些音——用半音阶口径去检查会一直报「缺失」。

本脚本按三首诗的调式音阶逐级检查覆盖：
  《江雪》   羽调式 D  → D E F# A B（D 羽）
  《早发白帝城》徵调式 G → G A B D E（G 徵）
  《静夜思》 宫调式 C  → C D E G A（C 宫）
并给出「每个音级取最近可用源」的变调量。
"""
import json
import math
from pathlib import Path

OUT = Path(r"C:\Users\Administrator\AppData\Roaming\TRAE SOLO CN\ModularData"
           r"\ai-agent\work-mode-projects\6abe713d94dc8ba73e53cfec"
           r"\data\source\d3\guzheng")
mf = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
smp = mf["samples"]
have = {s["midi"]: s for s in smp}
f0s = {s["midi"]: s["f0_hz"] for s in smp}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"

print(f"采样库 {len(smp)} 条，音域 {mf['range']}")
print("已有：")
for m in sorted(have):
    print(f"  {nn(m):>4} MIDI{m:>3}  f0={f0s[m]:7.1f}Hz  {have[m]['dur_s']:.2f}s  "
          f"decay {have[m].get('decay_to_m40db_s', 0):.2f}s  "
          f"{'去混响' if have[m].get('de_reverb') else '干'}")

# 五声音阶在 MIDI 上的半音集合（D 宫 / D 商 等，同一集合不同主音）
PENTA = {0, 2, 4, 7, 9}     # C 宫式：宫商角徵羽 = C D E G A


def nearest(m):
    """最近的可用采样；返回 (midi, 变调半音数)。

    注意：manifest 的 f0_hz 保留 2 位小数，但被 round 到 0.1 Hz 的量级，
    低音区（36–110 Hz）一个 0.1 Hz 的舍入就有 0.2 半音误差。
    故这里用「manifest 记录的 midi 对应的标称频率」而非 f0_hz 来算变调——
    f0_hz 仍用于人工核对与音色分析，定位取源用标称值更准。
    """
    want = 440.0 * 2 ** ((m - 69) / 12.0)
    best = None
    for k in sorted(f0s):
        nom = 440.0 * 2 ** ((k - 69) / 12.0)
        s = abs(12.0 * math.log2(want / nom))
        if best is None or s < best[1]:
            best = (k, s)
    return best


print("\n按五声调式检查（三首诗的实际用音）：")
for name, tonic, octv, degs in (
        ("《江雪》羽调式 D", 38, 0, [0, 2, 4, 7, 9]),
        ("《早发白帝城》徵调式 G", 43, 0, [0, 2, 4, 7, 9]),
        ("《静夜思》宫调式 C", 48, 0, [0, 2, 4, 7, 9]),
):
    print(f"\n  {name}")
    rows = []
    for o in (-1, 0, 1):
        for d in degs:
            m = tonic + o * 12 + d
            if m in f0s:
                rows.append((m, 0.0, "原生"))
            else:
                k, semi = nearest(m)
                rows.append((m, semi, f"← {nn(k)}"))
    for m, semi, tag in rows:
        want = 440.0 * 2 ** ((m - 69) / 12.0)
        mark = "✓" if semi <= 0.5 else ("~" if semi <= 2.0 else "✗")
        print(f"    {mark} {nn(m):>4} MIDI{m:>3} 目标 {want:7.1f}Hz  "
              f"变调 {semi:+5.2f} 半音  {tag}")
    worst = max(s for _m, s, _t in rows)
    print(f"    → 最大变调 {worst:.2f} 半音")
