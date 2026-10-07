# -*- coding: utf-8 -*-
"""把语音包络画成 ASCII 条带，用于肉眼判断「连贯」还是「一字一顿」。

每行取一个语音块（按 250ms 静音切分），以 20ms 为帧输出相对峰值(dB)的条带。
若条带内部出现与字数同频的深谷（凹到 -25dB 以下且窄），即为「一字一顿」的指纹。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

import sys

import numpy as np
import soundfile as sf

FP = 20.0  # ms


def env_of(path):
    x, sr = sf.read(path, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    hop = int(sr * FP / 1000.0)
    n = len(x) // hop
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) for i in range(n)])
    return e, sr


def blocks(e, sr):
    peak = np.percentile(e, 99)
    voiced = e > peak * 0.05
    out, i, n = [], 0, len(e)
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        s = i
        while i < n and voiced[i]:
            i += 1
        out.append((s, i))
    # 合并 <250ms 的缝
    mg = []
    for r in out:
        if mg and r[0] - mg[-1][1] < int(250.0 / FP):
            mg[-1] = (mg[-1][0], r[1])
        else:
            mg.append(r)
    return [r for r in mg if (r[1] - r[0]) * FP >= 400.0]


def plot(e, a, b, label):
    seg = e[a:b]
    pk = np.max(seg)
    print(f"  [{label}] {a*FP/1000:.2f}-{b*FP/1000:.2f}s  ({len(seg)} 帧 × {FP:.0f}ms)")
    line = ""
    for v in seg:
        db = 20 * np.log10(max(v, 1e-9) / max(pk, 1e-9))
        # -40dB..0dB -> 0..10 格
        k = int(np.clip((db + 40) / 4.0, 0, 9))
        line += " .:-=+*#%@"[k]
    # 每 60 帧（1.2s）折行
    w = 60
    for i in range(0, len(line), w):
        print("      " + line[i:i + w])


if __name__ == "__main__":
    base = os.path.join(ROOT, "dist", "audio", "voice")
    for name in sys.argv[1:]:
        p = os.path.join(base, name)
        if not os.path.exists(p):
            print(f"[skip] {name}")
            continue
        e, sr = env_of(p)
        print(f"== {name} ==")
        for bi, (a, b) in enumerate(blocks(e, sr)):
            plot(e, a, b, f"行{bi+1}")
        print()
