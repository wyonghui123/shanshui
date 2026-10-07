#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扬琴切分诊断：静音检测是否成立 + 名称解析修正。"""
import math
import struct
from pathlib import Path

import numpy as np

CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
SR = 44100
b = (CACHE / "Khim.sf2").read_bytes()

# 名称解析：'Khim F#5L' → 剥掉乐器名（第一个空格前），再解析音高
SEMI = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
        "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"


def parse_name(nm):
    t = nm.strip()
    if t.upper() == "EOS":
        return None, None
    ch = t[-1] if t[-1:] in ("L", "R") else None
    core = (t[:-1] if ch else t).strip()
    if " " in core:                      # 剥掉乐器名前缀 'Khim'
        core = core.split()[-1]
    if not core or not core[-1].isdigit():
        return None, ch
    octv = int(core[-1])
    rest = core[:-1]
    if rest in SEMI:
        return 12 * (octv + 1) + SEMI[rest], ch
    if rest.endswith("#") and rest[:-1] in SEMI:
        return 12 * (octv + 1) + SEMI[rest[:-1]] + 1, ch
    if rest.endswith("b") and rest[:-1] in SEMI:
        return 12 * (octv + 1) + SEMI[rest[:-1]] - 1, ch
    return None, ch


I_SH, I_SM = 15_011_000, 188
names = []
for k in range(22):
    o = I_SH + 8 + k * 46
    nm = b[o:o + 20].split(b"\x00")[0].decode("latin-1", "ignore")
    if nm.upper() == "EOS":
        break
    names.append(nm)
print("名称解析（剥前缀后）：")
for nm in names:
    m, ch = parse_name(nm)
    print(f"  {nm:<16} {'MIDI' + str(m) + ' ' + nn(m) if m else '???'} {ch or ''}")
mids = [parse_name(n)[0] for n in names if parse_name(n)[0] is not None]
print(f"可解析 {len(mids)}/{len(names)}，音域 {nn(min(mids))}–{nn(max(mids))}")

# 静音检测
DATA = I_SM + 8 + 46 + 24 * len(names)
cnt = (I_SH - DATA) // 4
arr = np.frombuffer(b, dtype="<i2", count=cnt * 2,
                    offset=DATA).reshape(-1, 2).astype(np.float64) / 32768.0
mono = arr.mean(axis=1)
print(f"\n样值区 {DATA:,}..{I_SH:,}  {len(mono):,} 帧 = {len(mono)/SR:.2f}s")

W, HOP = 1024, 256
env = np.array([float(np.sqrt(np.mean(mono[i:i + W] ** 2)))
                for i in range(0, len(mono) - W, HOP)])
edb = 20 * np.log10(env + 1e-9)
print(f"包络 {len(env)} 点；max {edb.max():.1f}  5%ile {np.percentile(edb,5):.1f}  "
      f"10%ile {np.percentile(edb,10):.1f}  中位 {np.median(edb):.1f}")
for thr in (-50, -45, -40, -35, -30):
    print(f"  阈值 {thr:>4} dB → {int(np.sum(edb > thr)):>4} 点有声 "
          f"({100*np.sum(edb>thr)/len(edb):.0f}%)")

# 找间隙
for thr in (-40, -35, -30):
    gap = []
    cur = None
    for i, v in enumerate(edb):
        if v <= thr:
            cur = i if cur is None else cur
        else:
            if cur is not None and (i - cur) * HOP / SR > 0.25:
                gap.append((cur * HOP / SR, i * HOP / SR))
            cur = None
    if cur is not None and (len(edb) - cur) * HOP / SR > 0.25:
        gap.append((cur * HOP / SR, len(edb) * HOP / SR))
    print(f"\n阈值 {thr} dB → {len(gap)} 个 >250ms 间隙")
    for a, e in gap[:26]:
        print(f"    {a:6.2f} – {e:6.2f}s  ({(e-a)*1000:.0f} ms)")
