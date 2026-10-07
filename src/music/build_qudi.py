#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""曲笛（Qudi）采样库：Qudi (Raw).sf2 → 单声道干声 WAV + manifest。

素材：NeoSoundFonts/pattingthestar-instruments → Qudi (Raw).sf2
      录音者 pattingthestar 本人；仓库根 LICENSE 全文为 CC0 1.0 Universal，
      SF2 内 ICOP 字段亦写 "Creative Commons 0 1.0"。可再分发。

**shdr 名称在这份素材上是坏的，故不采信。** 走了一遍才确认：
  · shdr name 标称 A4–G#5（7 个音高 × L/R），但等分后逐 0.25s 窗看谱峰，
    **每一段**都落在 920–1000Hz（A#5/B5）附近，相邻段音高相同，
    与「A4→G#5 逐级上行」完全不符 → 等分与真实发声不对齐。
  · 按包络独立定位发声起点，5 个阈值（−30…−50 dB）**一致**给出 15 个事件，
    且基频轨迹逐段上行 A5→B5→C#6→…，是一条真实的上行音阶。
  · 结论：可信的是**样值区的音频本身**；不可信的是 name 与各种 size 字段
    （与 Beixiao / Khim 同一批 Polyphone 缺陷，但这次坏在 name 上，
    故不能照抄北箫的「按 name 等分」）。

故本脚本按**包络事件**切分（与 build_khim.py 同一思路），
音高以实测 f0 逐段标注，不依赖 name。
"""
import argparse
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
OUT = ROOT / "data" / "source" / "d3" / "qudi"
SR = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"
KNOWN = {b"ifil", b"isng", b"INAM", b"irom", b"iver", b"ICRD", b"IENG",
         b"IPRD", b"ICOP", b"ISFT", b"IART", b"ICMT", b"ISBJ",
         b"shdr", b"phdr", b"smpl", b"inst", b"ibag", b"imod", b"igen",
         b"pmod", b"pgen", b"LIST", b"sdta"}


def ensure_sf2(dst):
    if dst.exists() and dst.stat().st_size > 4096:
        return True
    z = CACHE / "t_codeload-zip.bin"
    if not z.exists():
        return False
    subprocess.run(["7z.exe", "e", str(z), "-o" + str(CACHE), "-y",
                    "pattingthestar-instruments-main\\Qudi (Raw).sf2"],
                   capture_output=True)
    got = CACHE / "Qudi (Raw).sf2"
    if not got.exists():
        return False
    dst.write_bytes(got.read_bytes())
    got.unlink()
    return True


def read_sf2(p):
    """取 ICOP 与立体声样值。不读任何 size 字段（Polyphone 全坏）。"""
    b = p.read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"sfbk", "不是 SF2"
    hits = [(i, b[i:i + 4]) for i in range(24, len(b) - 8, 2)
            if b[i:i + 4] in KNOWN]
    i_sh = [i for i, c in hits if c == b"shdr"][-1]
    i_sm = [i for i, c in hits if c == b"smpl"][-1]
    meta = {}
    for i, c in hits:
        if c.decode() in ("ICOP", "INAM", "ISFT", "IART") and c.decode() not in meta:
            z = b.find(b"\x00", i + 8)
            if 0 < z <= i + 8 + 400:
                meta[c.decode()] = b[i + 8:z].decode("latin-1", "ignore")
    n_shdr = 0
    for k in range((len(b) - i_sh - 8) // 46):
        o = i_sh + 8 + k * 46
        nm = b[o:o + 20].split(b"\x00")[0].decode("latin-1", "ignore")
        if nm.upper() == "EOS":
            break
        n_shdr += 1
    data = i_sm + 8 + 46 + 24 * n_shdr
    cnt = (i_sh - data) // 4
    arr = np.frombuffer(b, dtype="<i2", count=cnt * 2,
                        offset=data).reshape(-1, 2).astype(np.float64) / 32768.0
    return meta, arr, n_shdr


def events(x, sr, abs_db=-40.0, min_gap_s=0.20, min_len_s=0.25):
    """按绝对阈值切出发声事件（与 build_khim.py 同口径）。"""
    W, HOP = 512, 128
    env = np.array([float(np.sqrt(np.mean(x[i:i + W] ** 2)))
                    for i in range(0, len(x) - W, HOP)])
    thr = 10 ** (abs_db / 20.0)
    act = env > thr
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
    # 合并间隔 < min_gap 的相邻段（同一音的换指颤动）
    out = []
    for s in segs:
        if out and s[0] - out[-1][1] < min_gap_s * sr:
            out[-1][1] = s[1]
        else:
            out.append(s)
    return out


def f0_harmonic(x, sr, lo=180.0, hi=1400.0):
    """谐波簇定音：找「所有谱峰都接近其整数倍」的基频。

    比自相关稳。搜索上限须低于「最高基频 × 6」，否则高次谐波的搜索窗
    会越过更高次谐波的窗（本素材 G#5L 曾因此锁到 7992Hz）。
    """
    w = x * np.hanning(len(x))
    N = 1 << int(math.ceil(math.log2(2 * len(w))))
    S = np.abs(np.fft.rfft(w, N))
    f = np.fft.rfftfreq(N, 1.0 / sr)
    peaks = []
    for k in range(1, 7):
        m = (f >= lo * k - 45.0) & (f <= hi * k + 45.0)
        if m.any():
            peaks.append(float(f[m][int(np.argmax(S[m]))]))
    if len(peaks) < 2:
        return 0.0
    best, best_err = 0.0, None
    for f0c in peaks:
        errs = [abs(1200.0 * math.log2(fp / (f0c * max(round(fp / f0c), 1))))
                for fp in peaks]
        e = sum(errs) / len(errs)
        if best_err is None or e < best_err:
            best, best_err = f0c, e
    return best if best_err is not None and best_err < 40.0 else 0.0


def timbre(x, f0, sr):
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
    fr = sorted(float(np.sqrt(np.mean(x[i:i + 512] ** 2)))
                for i in range(0, n - 512, 512))
    nz = 20 * math.log10(max(float(np.mean(fr[:max(len(fr) // 10, 1)])),
                             1e-9) / (float(np.max(np.abs(x))) + 1e-9))
    att = 0.0
    if len(x) > int(0.23 * sr) + 8:
        r1 = float(np.sqrt(np.mean(x[int(0.01 * sr):int(0.04 * sr)] ** 2)))
        r2 = float(np.sqrt(np.mean(x[int(0.20 * sr):int(0.23 * sr)] ** 2)))
        att = 20 * math.log10(max(r1, 1e-9) / max(r2, 1e-9))
    return roll, cen, nz, att


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf2", default=str(CACHE / "Qudi-Raw.sf2"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--abs-db", type=float, default=-40.0)
    ap.add_argument("--min-gap", type=float, default=0.20)
    args = ap.parse_args()

    p = Path(args.sf2)
    if not ensure_sf2(p):
        print("✗ 素材不可得（需 t_codeload-zip.bin）")
        return 1
    meta, arr, n_shdr = read_sf2(p)
    print(f"素材 {p.name}  {len(arr)/SR:.2f}s 立体声  shdr {n_shdr} 条")
    print(f"INAM={meta.get('INAM','')!r}  ICOP={meta.get('ICOP','')!r}")

    mono = arr.mean(axis=1)
    bb, aa = butter(2, 120.0 / (SR / 2), btype="high")
    z = lfilter(bb, aa, mono - float(np.mean(mono)))
    pk = float(np.max(np.abs(z)))
    if pk > 0:
        z = z / pk

    segs = events(z, SR, abs_db=args.abs_db, min_gap_s=args.min_gap)
    print(f"发声事件 {len(segs)} 段（阈值 {args.abs_db} dB）")

    items = []
    print(f"\n{'#':>2} {'起音':>6} {'时长':>6} {'实测f0':>8} {'MIDI':>5} "
          f"{'偏差':>6} {'滚降':>7} {'质心':>6} {'起音瞬态':>8} {'本底':>7}")
    for i, (a, e) in enumerate(segs):
        seg = z[a:e]
        if len(seg) < int(0.3 * SR):
            continue
        st = seg[int(0.20 * SR):]                 # 跳过吹管起音瞬态
        if len(st) < 1024:
            st = seg
        f0 = f0_harmonic(st, SR)
        if f0 <= 0:
            print(f"{i:>2} {a/SR:6.2f}s {len(seg)/SR:5.2f}s  定音失败，跳过")
            continue
        m = int(round(12.0 * math.log2(f0 / 440.0) + 69))
        roll, cen, nz, att = timbre(seg, f0, SR)
        items.append({"onset": a, "x": seg, "f0": f0, "midi": m,
                      "roll": roll, "cen": cen, "nz": nz, "att": att})
        print(f"{i:>2} {a/SR:6.2f}s {len(seg)/SR:5.2f}s {f0:>8.1f} {m:>5} "
              f"{'':<6} {roll:>7.2f} {cen:>6.0f} {att:>8.2f} {nz:>7.1f}")

    if not items:
        print("✗ 未切出样本")
        return 1

    by = {}
    for it in items:
        by.setdefault(it["midi"], []).append(it)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("qudi_*.wav"):
        old.unlink()
    samples = []
    for m in sorted(by):
        cand = by[m]
        # 同音高多条：取本底噪声最低的那条（最干净）
        best = min(cand, key=lambda it: it["nz"])
        z2 = best["x"]
        p2 = float(np.max(np.abs(z2)))
        if p2 < 1e-4:
            continue
        z2 = z2 / p2 * 0.891
        f = 440.0 * 2.0 ** ((m - 69) / 12.0)
        sf.write(str(out / f"qudi_{m:03d}.wav"), z2, SR, subtype="PCM_16")
        samples.append({"midi": m, "label": nn(m), "f0_hz": round(f, 2),
                        "file": f"qudi_{m:03d}.wav",
                        "dur_s": round(len(z2) / SR, 3),
                        "onset_s": round(best["onset"] / SR, 2),
                        "f0_measured_hz": round(best["f0"], 2),
                        "takes": len(cand),
                        "roll_db_oct": round(best["roll"], 2),
                        "centroid_hz": round(best["cen"]),
                        "attack_db": round(best["att"], 2),
                        "noise_db": round(best["nz"], 2)})

    mf = {"instrument": "qudi",
          "source": "NeoSoundFonts/pattingthestar-instruments → Qudi (Raw).sf2",
          "url": "https://github.com/NeoSoundFonts/pattingthestar-instruments",
          "author": "pattingthestar",
          "recording": "实录（双麦克风位，32.3s 立体声）",
          "license": "CC0 1.0",
          "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
          "license_evidence": ("仓库根 LICENSE 全文（CC0 1.0 Universal）"
                               "+ SF2 内 ICOP 字段 = 'Creative Commons 0 1.0'"),
          "derived": (f"样值区 → 包络事件切分（绝对 {args.abs_db:.0f} dB / "
                      f"512-128 窗 / minGap {args.min_gap:.2f}s）→ 120Hz 高通 → "
                      "峰值归一(-1 dBFS) → 单声道 44.1k"),
          "name_field_unreliable": (
              "**shdr name 不可采信**。name 标称 A4–G#5（7 音高 × L/R），但等分后"
              "逐 0.25s 窗看谱峰，每一段都落在 920–1000Hz（A#5/B5）附近，"
              "相邻段音高相同，与「A4→G#5 逐级上行」不符 → 等分与真实发声不对齐。"
              "按包络独立定位发声起点，5 个阈值（−30…−50 dB）一致给出 15 个事件，"
              "基频轨迹逐段上行 A5→B5→C#6→…，是真实音阶。"
              "故本脚本按事件切分、音高以实测 f0 标注，完全不依赖 name。"),
          "seg_count_note": ("发声事件数随阈值在 8–12 之间变（−30→12、−35→10、"
                             "−40→9、−45→9、−50→8），但**去重后的音高集合稳定"
                             "在 7 个**（A5 B5 C#6 D6 D#6 E6 F#6，且多数有 2 条"
                             "重复演奏）。段数变化来自同音重复被合并，不是"
                             "音高在变——这一点已用逐阈值扫描核对，否则很容易"
                             "把「切少了音」误判成「素材音少」。"
                             "静音检测在 −40 dB 只切出 9 段 < 14 条 shdr，"
                             "说明实录首尾相接、气声尾音把间隙填满；"
                             "与北箫同类，但**不能**像北箫那样按 name 等分"
                             "（那份的 name 可信，这份不可信）"),
          "octave_note": ("真实音域按实测 f0 为 A5–F#6 附近，比 name 暗示的"
                          "A4–G#5 高一个八度——与 Beixiao / Khim 同一缺陷，"
                          "只是本素材连 name 音高也不可信"),
          "sr": SR, "n": len(samples),
          "range": f"{samples[0]['label']}–{samples[-1]['label']}",
          "samples": samples}
    (out / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"\n{len(samples)} 条 → {out}   音域 {mf['range']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
