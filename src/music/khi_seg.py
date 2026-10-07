#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扬琴分段阈值扫描：找出能让段数对上 22 条 shdr 的阈值。

背景：−35 dB / 250ms 只切出 16 段（应 22），配对错位 → 实测 f0 与 name 偏差
在 −3896…+3021 音分乱跳。需确认是阈值太严还是「L/R 非同期」的问题。
"""
import math
from pathlib import Path

import numpy as np

CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
SR = 44100
b = (CACHE / "Khim.sf2").read_bytes()
I_SH, I_SM, N = 15_011_000, 188, 22
DATA = I_SM + 8 + 46 + 24 * N
cnt = (I_SH - DATA) // 4
arr = np.frombuffer(b, dtype="<i2", count=cnt * 2,
                    offset=DATA).reshape(-1, 2).astype(np.float64) / 32768.0
mono = arr.mean(axis=1)

W, HOP = 512, 128
env = np.array([float(np.sqrt(np.mean(mono[i:i + W] ** 2)))
                for i in range(0, len(mono) - W, HOP)])
edb = 20 * np.log10(env + 1e-9)
print(f"包络 {len(env)} 点（{W/SR*1000:.0f}ms 窗 / {HOP/SR*1000:.0f}ms 跳）")
print(f"max {edb.max():.1f}  中位 {np.median(edb):.1f}  "
      f"5%ile {np.percentile(edb,5):.1f}  10%ile {np.percentile(edb,10):.1f}")


def segs(thr_db, min_gap_s, min_len_s, abs_thr=None):
    thr = max(float(edb.max()) + thr_db, -75.0) if abs_thr is None else abs_thr
    act = edb > thr
    mg = max(int(min_gap_s * SR / HOP), 1)
    ml = int(min_len_s * SR / HOP)
    out, i = [], 0
    while i < len(act):
        if act[i]:
            j, gap = i, 0
            while j < len(act):
                if act[j]:
                    gap = 0
                else:
                    gap += 1
                    if gap >= mg:
                        break
                j += 1
            out.append((i * HOP, j * HOP + W))
            i = j
        else:
            i += 1
    return [s for s in out if (s[1] - s[0]) >= ml], thr


print(f"\n{'相对阈值':>8} {'绝对dB':>8} {'minGap':>7} {'minLen':>7} {'段数':>5}")
best = None
for rel in (-50, -45, -40, -38, -36, -35, -34, -32, -30, -28, -25, -22, -20):
    for mg in (0.08, 0.12, 0.18, 0.25):
        s, thr = segs(rel, mg, 0.30)
        flag = " ← 22!" if len(s) == 22 else ""
        if len(s) in (21, 22, 23):
            best = (rel, mg, len(s), thr, s)
        if len(s) == 22 or (rel in (-45, -35, -30) and mg in (0.12, 0.25)):
            print(f"  {rel:>6} dB {thr:8.1f} {mg:7.2f} {0.30:7.2f} {len(s):>5}{flag}")

if best:
    rel, mg, n_, thr, s = best
    print(f"\n采用 相对 {rel} dB（绝对 {thr:.1f}）minGap {mg}s → {n_} 段")
    print("各段（对照 22 条 shdr name 顺序）：")
    SEMI = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
            "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    def midi_of(nm):
        t = nm.strip()
        if t.upper() == "EOS":
            return None
        core = t[:-1].strip() if t[-1:] in "LR" else t
        if " " in core:
            core = core.split()[-1]
        if not core or not core[-1].isdigit():
            return None
        o = int(core[-1])
        r = core[:-1]
        if r in SEMI:
            return 12 * (o + 1) + SEMI[r]
        if r.endswith("#") and r[:-1] in SEMI:
            return 12 * (o + 1) + SEMI[r[:-1]] + 1
        return None

    def f0(x):
        n = len(x)
        w = min(n, SR)
        W2 = 1 << int(math.ceil(math.log2(2 * w)))
        S = np.abs(np.fft.rfft(x[:w] * np.hanning(w), W2)) ** 2
        ac = np.fft.irfft(S)[:w]
        if ac[0] <= 0:
            return 0.0
        ac = ac / ac[0]
        k1, k2 = int(SR / 2600), min(int(SR / 55), w - 1)
        i = int(np.argmax(ac[k1:k2])) + k1
        return SR / i if i > 0 else 0.0

    for k, (a, e) in enumerate(s):
        nm = b[I_SH + 8 + k * 46:I_SH + 8 + k * 46 + 20].split(b"\x00")[0].decode("latin-1", "ignore")
        m = midi_of(nm)
        y = mono[a:e]
        f = f0(y)
        nom = 440.0 * 2.0 ** ((m - 69) / 12.0) if m else 0
        dev = 1200.0 * math.log2(f / nom) if nom > 0 and f > 0 else 0
        lbl = f"{NAMES[m%12]}{m//12-1}" if m else "???"
        print(f"  [{k:2d}] {nm:<14} {lbl:>4}  实测 {f:7.1f}Hz  "
              f"偏差 {dev:+7.0f} 音分  {(e-a)/SR:5.2f}s")
