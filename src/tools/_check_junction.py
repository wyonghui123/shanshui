# -*- coding: utf-8 -*-
"""句间衔接核验：句末渐弱差异 + 句首滑音衔接。

用法: python src/tools/_check_junction.py <wav>
输出:
  - 逐句 句末/句首 对数音高，句间跳进（半音）
  - 句首 250ms 内的滑音位移（半音）
  - 逐句 句末段/句中段 的 RMS 比（渐弱深度）
"""
import sys

import numpy as np
import pyworld as pw
import soundfile as sf

FRAME_PERIOD = 5.0


def detect_lines(env, sr, frame_period, n_expect=4):
    """平滑包络 + 自适应阈值 + 合并短静音，稳健切出 4 句。"""
    # 平滑包络（~40ms）
    k = max(1, int(40.0 / frame_period))
    sm = np.convolve(env, np.ones(k) / k, mode="same")
    floor = np.percentile(sm, 10)
    peak = np.percentile(sm, 99)
    thr = floor + 0.12 * (peak - floor)
    voiced = sm > thr

    # 初步游程
    runs = []
    i = 0
    n = len(env)
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        s = i
        while i < n and voiced[i]:
            i += 1
        runs.append([s, i])

    # 合并间隔 < 300ms 的相邻游程
    min_gap = int(300.0 / frame_period)
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    # 过滤过短段（< 0.30s）
    min_len = int(0.30 * sr / (sr * frame_period / 1000.0))
    segs = [(a, b) for a, b in merged if b - a >= min_len]

    if len(segs) != n_expect:
        print(f"[warn] 检测到 {len(segs)} 段（期望 {n_expect}）: "
              + ", ".join(f"{a}-{b}" for a, b in segs))
    return segs


def robust_log2(vals):
    """剔除倍频/杂散帧后的对数音高中位。"""
    if len(vals) == 0:
        return None
    med = float(np.median(vals))
    keep = np.abs(np.log2(vals / med)) <= 7.0 / 12.0
    vals = vals[keep]
    return float(np.median(np.log2(vals))) if len(vals) else None


def seg_log2(f0, a, b, ms, frame_period, from_end):
    idx = np.flatnonzero(f0[a:b] > 0)
    if len(idx) == 0:
        return None
    vals = f0[a + idx]
    k = max(1, int(ms / frame_period))
    return robust_log2(vals[-k:] if from_end else vals[:k])


def main():
    path = sys.argv[1]
    x, sr = sf.read(path, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    f0, t = pw.harvest(x, sr, f0_floor=71.0, f0_ceil=600.0, frame_period=FRAME_PERIOD)
    hop = int(sr * FRAME_PERIOD / 1000.0)
    env = np.array([
        np.sqrt(np.mean(x[i * hop:min(i * hop + hop, len(x))] ** 2)) if min(i * hop + hop, len(x)) > i * hop else 0.0
        for i in range(len(f0))
    ])
    segs = detect_lines(env, sr, FRAME_PERIOD)

    print(f"文件: {path}")
    print(f"总时长: {len(x)/sr:.3f}s  段数: {len(segs)}")
    print()
    print(f"{'句':>2} {'区间(s)':>14} {'句首音高(Hz)':>12} {'句末音高(Hz)':>12} "
          f"{'句间跳进(半音)':>14} {'句末/峰值(dB)':>14}")
    print("-" * 84)

    prev_end = None
    for li, (a, b) in enumerate(segs):
        e_log2 = seg_log2(f0, a, b, 120.0, FRAME_PERIOD, True)
        h_log2 = seg_log2(f0, a, b, 120.0, FRAME_PERIOD, False)
        e_hz = 2.0 ** e_log2 if e_log2 else float("nan")
        h_hz = 2.0 ** h_log2 if h_log2 else float("nan")
        jump = (h_log2 - prev_end) * 12.0 if (prev_end is not None and h_log2 is not None) else float("nan")

        # 渐弱：句末 150ms 有声段 RMS 相对句内峰值
        voiced = np.flatnonzero(f0[a:b] > 0)
        peak = env[a:b].max() if b > a else 0.0
        if len(voiced):
            kk = max(1, int(150.0 / FRAME_PERIOD))
            end_env = env[a + voiced[-kk:]]
            fade_db = 20.0 * np.log10((end_env.mean() + 1e-9) / (peak + 1e-9))
        else:
            fade_db = float("nan")

        print(f"{li+1:>2} {t[a]:>6.2f}-{t[b-1]:>6.2f} {h_hz:>12.1f} {e_hz:>12.1f} "
              f"{jump:>14.2f} {fade_db:>14.2f}")
        prev_end = e_log2

    print()
    print("判据：句间跳进 ≤ 2.0 半音（滑音压缩生效）；句末/峰值仅承(轻)与合(重)应明显下降")
    print()
    print("句首 0-300ms 音高轨迹（半音，相对各句自身首帧）：")
    marks = [5, 15, 25, 35, 45, 55]  # 帧号 -> 25..275ms
    for li, (a, b) in enumerate(segs):
        vals = []
        for m in marks:
            w = f0[a + m - 1:a + m + 1]
            w = w[w > 0]
            vals.append(float(np.median(np.log2(w))) if len(w) else None)
        base = next((v for v in vals if v is not None), None)
        if base is None:
            continue
        s = "  ".join(f"{m*5:>3}ms " + ("  --  " if v is None else f"{(v-base)*12:+5.2f}")
                      for m, v in zip(marks, vals))
        print(f"  句{li+1}: {s}")

    hop = int(sr * FRAME_PERIOD / 1000.0)
    print()
    print("停顿段扫描（检测到的句间空隙内峰值及其位置）：")
    for li in range(1, len(segs)):
        pb = segs[li - 1][1]
        ca = segs[li][0]
        if ca <= pb:
            print(f"  {li}→{li+1}: 检测为连续（无空隙）")
            continue
        seg_x = x[pb * hop:ca * hop]
        k = int(np.argmax(np.abs(seg_x)))
        print(f"  {li}→{li+1}: 空隙 {t[pb]:.2f}–{t[ca]:.2f}s "
              f"({(ca-pb)*FRAME_PERIOD/1000:.2f}s)  峰值 {np.max(np.abs(seg_x)):.4f} @ {t[pb]+k/sr:.2f}s")


if __name__ == "__main__":
    main()
