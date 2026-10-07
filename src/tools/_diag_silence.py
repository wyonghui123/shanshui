# -*- coding: utf-8 -*-
"""量化「逐字念」的两种可能成因，直接测音频（不依赖元数据）。

判据 A（阶跃伸缩）：音节边界处局部速度瞬时跳变 —— 由 _diag_staccato.py 量化。
判据 B（句内留白）：底样 TTS 在慢速下字间插入静音，后处理若 1:1 保留，听感即
                   「一个字一个字」。本脚本测：每句内的静音占比、静音段数量与时长。

输出：行内静音占比 ρ、行内静音段数、各段中位时长；并给出全片统计。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

import sys

import numpy as np
import soundfile as sf

FP = 5.0  # ms


def frame_env(x, sr, fp=FP):
    hop = max(1, int(sr * fp / 1000.0))
    n = int(np.ceil(len(x) / hop))
    env = np.zeros(n)
    for i in range(n):
        s = i * hop
        e = min(s + hop, len(x))
        if e > s:
            env[i] = np.sqrt(np.mean(x[s:e] ** 2))
    return env


def analyze(path, n_lines):
    x, sr = sf.read(path, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    env = frame_env(x, sr)

    # 全片有声帧（相对峰值）
    peak = np.percentile(env, 99)
    thr = peak * 0.06                       # -24dB 相对峰值
    voiced = env > thr

    # 切行（静音间隔 >= 250ms 视为行界）
    runs, i, n = [], 0, len(env)
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        s = i
        while i < n and voiced[i]:
            i += 1
        runs.append([s, i])
    merged = []
    gap_min = int(250.0 / FP)
    for r in runs:
        if merged and r[0] - merged[-1][1] < gap_min:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    lines = [r for r in merged if (r[1] - r[0]) * FP >= 400.0]

    print(f"== {os.path.basename(path)}  时长 {len(x)/sr:.3f}s  检出 {len(lines)} 行（期望 {n_lines}）==")
    all_gaps = []
    for li, (a, b) in enumerate(lines):
        seg = env[a:b]
        seg_peak = np.percentile(seg, 99)
        seg_thr = seg_peak * 0.10            # 行内判静音阈值（-20dB）
        sv = seg > seg_thr
        # 行内静音段（被有声夹住的）
        gaps = []
        j = 0
        m = len(sv)
        while j < m:
            if sv[j]:
                j += 1
                continue
            g0 = j
            while j < m and not sv[j]:
                j += 1
            if g0 > 0 and j < m:             # 只算行内（非行首尾）
                gaps.append((j - g0) * FP)
        silence_ratio = 1.0 - float(sv.mean())
        all_gaps += gaps
        gtxt = " ".join(f"{g:.0f}" for g in gaps) if gaps else "-"
        print(f"  行{li+1}  {a*FP/1000:6.2f}-{b*FP/1000:6.2f}s  "
              f"行内静音占比 {silence_ratio*100:4.1f}%  静音段 {len(gaps)}  段长ms [{gtxt}]")

    if all_gaps:
        print(f"  ── 行内静音段合计 {len(all_gaps)}  中位 {np.median(all_gaps):.0f}ms  "
              f"最大 {max(all_gaps):.0f}ms  ≥60ms 的段 {sum(g>=60 for g in all_gaps)}")
    print()


if __name__ == "__main__":
    base = os.path.join(ROOT, "dist", "audio", "voice")
    targets = sys.argv[1:] or [
        "jx_edge_zh-CN-YunjianNeural_quatrain.wav",
        "jx_emotion_cold_zh-CN-YunjianNeural.wav",
        "ab/jx_step.wav",
        "ab/jx_smooth.wav",
    ]
    nl = {"jx": 4, "bd": 4, "jys": 4}
    for name in targets:
        p = os.path.join(base, name)
        if not os.path.exists(p):
            print(f"[skip] {name} 不存在")
            continue
        key = name.split("_")[0].lstrip("_") if name.startswith("_") else name.split("_")[0]
        analyze(p, nl.get(key, 4))
