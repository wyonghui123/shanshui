# -*- coding: utf-8 -*-
"""句末渐弱 A/B：同一句结构下，比较「后版/前版」句末包络的 dB 差。

用法: python src/tools/_compare_fade.py <after.wav> <before.wav>
若渐弱差异化生效：起/承/转 三句后版应更响（>0 dB），合句两者相同（≈0 dB）。
"""
import sys

import numpy as np
import pyworld as pw
import soundfile as sf

FRAME_PERIOD = 5.0


def env_of(path):
    x, sr = sf.read(path, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    f0, t = pw.harvest(x, sr, f0_floor=71.0, f0_ceil=600.0, frame_period=FRAME_PERIOD)
    hop = int(sr * FRAME_PERIOD / 1000.0)
    env = np.array([
        np.sqrt(np.mean(x[i * hop:min(i * hop + hop, len(x))] ** 2))
        if min(i * hop + hop, len(x)) > i * hop else 0.0
        for i in range(len(f0))
    ])
    return f0, env, t, sr


def detect_lines(env, sr, n_expect=4):
    k = max(1, int(40.0 / FRAME_PERIOD))
    sm = np.convolve(env, np.ones(k) / k, mode="same")
    floor = np.percentile(sm, 10)
    peak = np.percentile(sm, 99)
    voiced = sm > floor + 0.12 * (peak - floor)
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
    for r in runs:
        if merged and r[0] - merged[-1][1] < int(300.0 / FRAME_PERIOD):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if b - a >= int(0.30 * 1000 / FRAME_PERIOD)]


def main():
    after, before = sys.argv[1], sys.argv[2]
    f0a, enva, ta, _ = env_of(after)
    f0b, envb, tb, _ = env_of(before)
    segs = detect_lines(enva, 1, 4)
    print(f"AFTER : {after}")
    print(f"BEFORE: {before}")
    print(f"段数: {len(segs)}")
    print()
    print(f"{'句':>2} {'区间(s)':>14} {'前版句末(dB)':>13} {'后版句末(dB)':>13} {'后-前(dB)':>11}")
    print("-" * 70)
    for li, (a, b) in enumerate(segs):
        L = b - a
        # 句末 25% 包络均值（两版同区间）
        tail_a = enva[b - L // 4:b].mean()
        tail_b = envb[b - L // 4:b].mean()
        da = 20.0 * np.log10(tail_a + 1e-9)
        db = 20.0 * np.log10(tail_b + 1e-9)
        print(f"{li+1:>2} {ta[a]:>6.2f}-{ta[b-1]:>6.2f} {db:>13.2f} {da:>13.2f} {da-db:>11.2f}")
    print()
    print("预期：起/承/转 后版更响（后-前 > 0）；合句后版=前版（≈0）")


if __name__ == "__main__":
    main()
