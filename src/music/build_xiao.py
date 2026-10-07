#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""北箫（Beixiao）采样库：Beixiao-Raw.sf2 → 单声道干声 WAV + manifest。

素材：NeoSoundFonts/pattingthestar-instruments → Beixiao-Raw.sf2
      录音者 pattingthestar 本人，CC0 1.0（文件内 ICOP 字段亦写明
      "Creative Commons 0 1.0"）。

该 SF2 由 Polyphone 写出，数值字段几乎全坏（实测）：
  · RIFF size = 1,514,897,408（实际 8,407,906）
  · 所有 chunk size 为垃圾值（ifil len = 0x04000000）
  · smpl 的 root/tune 给出不可能音高（A#18 / G#1 等）
  · shdr 的 start/end/loopStart/loopEnd 全是垃圾（循环段算出 4294 秒）
已实测定位：smpl@244、shdr@8,407,116、样值区 706..8,406,584（47.65s 立体声）。

**⚠ 重做：shdr 的 name 与样值区不是对应关系，等分法已废弃。**
  本脚本早先按「16 个 name 严格等分」切分，理由是「47.65s 内无低于
  −25 dB 的间隙」。事后用包络独立复核，发现等分与真实发声**不对齐**：
    · 16 段实测 f0 与其 name 标称的偏差散在 +708 / +1133 / +1189 /
      +1205 / +2404 音分各处，甚至有 3 段根本定不出音高；
    · 同一 name 段的 L 与 R 实测差了整整一个八度（D4L 读 D6=1177Hz、
      D4R 读 D5=589Hz）——若 L/R 是同期双麦，L/R 必然同频。
  这与曲笛（Qudi (Raw).sf2，同一 Polyphone 批次）是**同一个缺陷**：
  name 字段不可信，等分会把错的音频贴上错的标签。
  后果是渲染时「按标签取源 + 大幅变调补差」= 用错的音频硬拗到目标音高，
  听感上该乐器就消失了（《静夜思》的箫即如此）。

故改为**按包络事件切分**（与 build_khim.py / build_qudi.py 同一思路），
音高以实测 f0 逐段标注，完全不依赖 name。复核基准：包络在
−25/−30/−40 dB 三个阈值下均给出 16 个发声起点，与 16 条 shdr 数量吻合。
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
OUT = ROOT / "data" / "source" / "d3" / "xiao"
SR = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"

# 已实测定位的字节偏移（见 README「北箫素材的坑」）
I_SHDR, N_SHDR = 8_407_116, 17
I_SMPL, N_SMPL = 244, 17
DATA = I_SMPL + 8 + 46 + N_SMPL * 24        # 样值区起点 = 706
DATA_END = 8_406_584                         # 尾部 LIST 起点


def events(x, sr, abs_db=-40.0, min_gap_s=0.18, min_len_s=0.40):
    """按绝对阈值切出发声事件（与 build_khim.py 同口径）。

    用绝对阈值而非相对：气声吹奏的包络本身抬得很高（实测中位 −9.3 dB），
    相对阈值会随窗长漂移，导致切分点逐次错位——这正是扬琴那边踩过的坑。
    """
    W, HOP = 512, 128
    env = np.array([float(np.sqrt(np.mean(x[i:i + W] ** 2)))
                    for i in range(0, len(x) - W, HOP)])
    act = env > (10 ** (abs_db / 20.0))
    segs, a = [], None
    for i, v in enumerate(act):
        if v and a is None:
            a = i
        elif not v and a is not None:
            if (i - a) * HOP / sr >= min_len_s:
                segs.append([a * HOP, i * HOP])
            a = None
    if a is not None and (len(act) - a) * HOP / sr >= min_len_s:
        segs.append([a * HOP, len(act) * HOP])
    out = []
    for s in segs:                            # 合并间隔过短的（换指颤动）
        if out and s[0] - out[-1][1] < min_gap_s * sr:
            out[-1][1] = s[1]
        else:
            out.append(s)
    return out


def f0_harmonic(x, sr, lo=150.0, hi=1600.0):
    """谐波簇定音：找「所有谱峰都接近其整数倍」的基频。

    不用自相关——北箫这类吹管的谐波很强，自相关容易锁到 2×（实测 D4L
    锁到 1177Hz 而非 589Hz）。谐波簇以「各峰互为整数倍」为唯一判据，
    对倍频/亚倍频免疫。
    """
    w = x * np.hanning(len(x))
    N = 1 << int(math.ceil(math.log2(2 * len(w))))
    S = np.abs(np.fft.rfft(w, N))
    f = np.fft.rfftfreq(N, 1.0 / sr)
    peaks = []
    for k in range(1, 7):
        m = (f >= lo * k - 45) & (f <= hi * k + 45)
        if m.any():
            peaks.append(float(f[m][int(np.argmax(S[m]))]))
    if len(peaks) < 2:
        return 0.0
    best, err = 0.0, None
    for c in peaks:
        es = [abs(1200 * math.log2(p / (c * max(round(p / c), 1))))
              for p in peaks]
        e = sum(es) / len(es)
        if err is None or e < err:
            best, err = c, e
    return best if err is not None and err < 45 else 0.0


def timbre(x, f0, sr):
    """谐波滚降 / 频谱质心 / 气声 / 本底噪声（与笛库同口径，可横向对比）。"""
    n = min(len(x), sr)
    w = x[:n] * np.hanning(n)
    N = 1 << int(math.ceil(math.log2(2 * n)))
    S = np.abs(np.fft.rfft(w, N)) ** 2
    f = np.fft.rfftfreq(N, 1.0 / sr)

    def band(lo, hi):
        return float(np.sum(S[(f >= lo) & (f < hi)])) + 1e-20

    Hs = [10 * math.log10(band(k * f0 - 30, k * f0 + 30)) for k in range(1, 9)]
    roll = (Hs[3] - Hs[0]) / 3.0 if (Hs[3] - Hs[0]) < -1e-6 else 0.0
    cen = float(np.sum(f * S) / (float(np.sum(S)) + 1e-20))
    br = 10 * math.log10(band(1500, 7000) / band(0, 1500))
    fr = sorted(float(np.sqrt(np.mean(x[i:i + 512] ** 2)))
                for i in range(0, n - 512, 512))
    nz = 20 * math.log10(max(float(np.mean(fr[:max(len(fr) // 10, 1)])),
                             1e-9) / (float(np.max(np.abs(x))) + 1e-9))
    return roll, cen, br, nz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf2", default=str(CACHE / "Beixiao-Raw.sf2"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--abs-db", type=float, default=-40.0)
    ap.add_argument("--min-gap", type=float, default=0.18)
    ap.add_argument("--min-len", type=float, default=0.40)
    args = ap.parse_args()

    b = Path(args.sf2).read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"sfbk", "不是 SF2"

    names = []
    for k in range(N_SHDR):
        o = I_SHDR + 8 + k * 46
        nm = b[o:o + 20].split(b"\x00")[0].decode("latin-1", "ignore")
        if nm == "EOS":
            break
        if nm.startswith("Beixiao"):
            names.append(nm)

    arr = np.frombuffer(b, dtype="<i2", count=((DATA_END - DATA) // 4) * 2,
                        offset=DATA).reshape(-1, 2).astype(np.float64) / 32768.0
    print(f"素材 {args.sf2}  样值区 {DATA:,}..{DATA_END:,}  "
          f"{len(arr):,} 帧 = {len(arr)/SR:.2f}s 立体声")
    print(f"shdr name {len(names)} 条（**仅记录，不用于切分**）")

    mono = arr.mean(axis=1)
    bb, aa = butter(2, 90.0 / (SR / 2), btype="high")
    z = lfilter(bb, aa, mono - float(np.mean(mono)))

    # 复核：多阈值下事件数应稳定，且与 16 条 shdr 吻合
    W, HOP = 512, 128
    env = np.array([float(np.sqrt(np.mean(z[i:i + W] ** 2)))
                    for i in range(0, len(z) - W, HOP)])
    edb = 20 * np.log10(env + 1e-9)
    for thr in (-25, -30, -35, -40, -45):
        n_ev = int(np.sum((edb[1:-1] > thr) & (edb[:-2] <= thr)
                          & (edb[2:] <= thr)))
        print(f"  复核 阈值 {thr:>4} dB → {n_ev:>3} 个发声起点"
              f"（shdr {len(names)} 条）")

    segs = events(z, SR, abs_db=args.abs_db, min_gap_s=args.min_gap,
                  min_len_s=args.min_len)
    print(f"\n发声事件 {len(segs)} 段（阈值 {args.abs_db} dB / "
          f"minGap {args.min_gap:.2f}s / minLen {args.min_len:.2f}s）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("xiao_*.wav"):
        old.unlink()

    items = []
    print(f"\n{'#':>2} {'起音':>6} {'时长':>6} {'实测f0':>8} {'MIDI':>5} "
          f"{'滚降':>7} {'质心':>6} {'气声':>7} {'本底':>7}")
    for i, (a, e) in enumerate(segs):
        seg = z[a:e]
        if len(seg) < int(0.35 * SR):
            continue
        st = seg[int(0.25 * SR):]              # 跳过吹管起音瞬态
        if len(st) < 1024:
            st = seg
        f0 = f0_harmonic(st, SR)
        if f0 <= 0:
            print(f"{i:>2} {a/SR:6.2f}s {len(seg)/SR:5.2f}s  定音失败，跳过")
            continue
        m = int(round(12.0 * math.log2(f0 / 440.0) + 69))
        roll, cen, br, nz = timbre(seg, f0, SR)
        items.append({"onset": a, "y": seg, "f0": f0, "midi": m,
                      "roll": roll, "cen": cen, "br": br, "nz": nz})
        print(f"{i:>2} {a/SR:6.2f}s {len(seg)/SR:5.2f}s {f0:>8.1f} {m:>5} "
              f"{roll:>7.2f} {cen:>6.0f} {br:>7.2f} {nz:>7.1f}")

    if not items:
        print("✗ 未切出任何样本", file=sys.stderr)
        return 1

    # 同音高去重：保留本底噪声最低者（最干净），先定名单再统一落盘
    by = {}
    for it in items:
        cur = by.get(it["midi"])
        if cur is None or it["nz"] < cur["nz"]:
            by[it["midi"]] = it
    samples = []
    for m in sorted(by):
        it = by[m]
        y = it["y"]
        pk = float(np.max(np.abs(y)))
        if pk < 1e-4:
            continue
        y = y / pk * 0.891
        f = 440.0 * 2.0 ** ((m - 69) / 12.0)
        fn = f"xiao_{m:03d}.wav"
        sf.write(str(out / fn), y, SR, subtype="PCM_16")
        samples.append({"midi": m, "label": nn(m), "f0_hz": round(f, 2),
                        "file": fn, "dur_s": round(len(y) / SR, 3),
                        "onset_s": round(it["onset"] / SR, 2),
                        "f0_measured_hz": round(it["f0"], 2),
                        "roll_db_oct": round(it["roll"], 2),
                        "centroid_hz": round(it["cen"]),
                        "breath_db": round(it["br"], 2),
                        "noise_db": round(it["nz"], 2)})

    if not samples:
        print("✗ 落盘后为空", file=sys.stderr)
        return 1

    mf = {"instrument": "xiao_beixiao",
          "source": "NeoSoundFonts/pattingthestar-instruments → Beixiao-Raw.sf2",
          "author": "pattingthestar（本人录音）",
          "post_process": "Yingchun Soul / Polyphone",
          "license": "CC0 1.0",
          "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
          "url": "https://github.com/NeoSoundFonts/pattingthestar-instruments",
          "sf2_note": ("该 SF2 由 Polyphone 写出，数值字段几乎全坏："
                       "RIFF size=1,514,897,408（实际 8,407,906）、chunk size "
                       "垃圾、smpl 音高不可能（A#18/G#1）、shdr 的 "
                       "start/end/loop 全垃圾。已实测定位：smpl@244、"
                       "shdr@8,407,116、样值区 706..8,406,584。"),
          "name_field_unreliable": (
              "**shdr name 与样值区不是对应关系，不能按 name 等分。**"
              "早先按 16 个 name 严格等分，实测每段与其 name 标称的偏差散在 "
              "+708/+1133/+1189/+1205/+2404 音分各处，3 段定不出音高；"
              "且同名段的 L 与 R 实测差整整一个八度（D4L=1177Hz vs "
              "D4R=589Hz）——同期双麦的 L/R 必然同频，故等分确实错位。"
              "与曲笛 Qudi (Raw).sf2（同一 Polyphone 批次）是同一缺陷。"
              "现改为按包络事件切分、音高以实测 f0 标注，不依赖 name。"),
          "derived": (f"样值区 → 包络事件切分（绝对 {args.abs_db:.0f} dB / "
                      f"512-128 窗 / minGap {args.min_gap:.2f}s / "
                      f"minLen {args.min_len:.2f}s）→ 90Hz 高通 → "
                      "峰值归一(-1 dBFS) → 单声道 44.1k"),
          "f0_method": "谐波簇（各谱峰互为整数倍），不用自相关——自相关对本素材会锁到 2×（实测 D4L 读到 1177Hz 而非 589Hz）",
          "sr": SR, "n": len(samples),
          "range": f"{samples[0]['label']}–{samples[-1]['label']}",
          "samples": samples}
    (out / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"\n{len(samples)} 条 → {out}   音域 {mf['range']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
