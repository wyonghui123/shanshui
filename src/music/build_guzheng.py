#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""古筝采样库：Pufermufin 的 24:34 CC0 实录 → 单音干声 WAV + manifest。

素材：Freesound sound 396868 "LOVELY CHINESE GUZHENG PLUCKED.wav"
      作者 Pufermufin，CC0（作者自述 "no credits necessary but I'd like to
      hear what you use it in!"）；设备 Blue Spark + Blue Bluebird 电容话筒
      + Scarlett 6i6 → 真实录音，非合成 patch。
      原文件 495.9 MB / 24:34 / 44.1 kHz / 32-bit float / 立体声；
      HQ 预览（免登录 CDN）实测 23.1 MB / 1474 s，已含完整内容（非截断）。

实测（HQ 预览）：1267 个拨弦瞬态，音高 C2–C#7、54 个不同音高。
      这是深搜后唯一同时满足「真实古筝 + 干声 + CC0 可再分发 + 覆盖足够」
      的公开资源——已排除 CCMUSIC（CC BY-NC-ND）、VCSL 合成 fxp、
      韩国 Gayageum（非古筝）、Freesound 其余演奏片段。

选样策略（不是每个瞬态都用）：作者写的是 "every sound you can get"，
含大量装饰音/刮弦/泛音，故按以下标准筛「干净的单音」：
  ① 起音后 0.5 s 内的 f0 稳定（|偏差| < 稳定阈）——排除滑音/扫弦
  ② 无二次拨弦（该窗内能量不再回升）
  ③ 峰值 ≥ min-peak（排除噪声与极弱触弦）
  ④ f0 吸附到 D 五声音阶的调内音级，容差 snap-cents；
     超出容差者判为装饰音（泛音被当基音、滑音中途取样）
  ⑤ 每音高只取最好的 1 条，避免同一音出现音色差异
另测干湿：本素材 tags 含 reverb，故逐条量尾音衰减长度并在 manifest 记录。
"""
import argparse
import json
import math
import ssl
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
OUT = ROOT / "data" / "source" / "d3" / "guzheng"
SOUND_ID, USER_ID = 396868, 6977826
SR = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get_preview(dst, tries=4, timeout=300):
    url = f"https://cdn.freesound.org/previews/{SOUND_ID // 1000}/" \
          f"{SOUND_ID}_{USER_ID}-hq.mp3"
    if dst.exists() and dst.stat().st_size > 4096:
        return dst.stat().st_size
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                data = r.read()
            dst.write_bytes(data)
            return len(data)
        except Exception as e:
            print(f"    下载第 {t+1} 次失败: {type(e).__name__}")
    return 0


def f0_track(x, sr, lo=60.0, hi=2200.0, win=0.12, hop=0.03):
    """短窗 f0 轨迹（用于判稳定 / 算偏差）。"""
    n = int(win * sr)
    h = int(hop * sr)
    if len(x) < n:
        return np.zeros(0), n, h
    N = 1 << int(math.ceil(math.log2(2 * n)))
    k1, k2 = int(sr / hi), min(int(sr / lo), n - 1)
    out = []
    for s in range(0, len(x) - n, h):
        w = x[s:s + n] * np.hanning(n)
        S = np.abs(np.fft.rfft(w, N)) ** 2
        ac = np.fft.irfft(S)[:n]
        if ac[0] <= 0:
            out.append(0.0)
            continue
        ac = ac / ac[0]
        i = int(np.argmax(ac[k1:k2])) + k1
        out.append(sr / i if i > 0 else 0.0)
    return np.array(out), n, h


def f0_ac(x, sr, lo=60.0, hi=2200.0):
    tr, _, _ = f0_track(x, sr, lo, hi)
    tr = tr[tr > 0]
    return float(np.median(tr)) if len(tr) else 0.0


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
    br = 10 * math.log10(band(1500, 7000) / band(0, 1500))
    fr = sorted(float(np.sqrt(np.mean(x[i:i + 512] ** 2)))
                for i in range(0, n - 512, 512))
    nz = 20 * math.log10(max(float(np.mean(fr[:max(len(fr) // 10, 1)])),
                             1e-9) / (float(np.max(np.abs(x))) + 1e-9))
    att = 0.0
    if len(x) > int(0.23 * sr) + 8:
        r1 = float(np.sqrt(np.mean(x[int(0.01 * sr):int(0.04 * sr)] ** 2)))
        r2 = float(np.sqrt(np.mean(x[int(0.20 * sr):int(0.23 * sr)] ** 2)))
        att = 20 * math.log10(max(r1, 1e-9) / max(r2, 1e-9))
    return roll, cen, br, nz, att


def decay_len(x, sr, rel_db=-40.0, max_s=6.0):
    """衰减到峰值下 rel_db 所需秒数（判干湿：实录带 tags reverb）。"""
    a = np.abs(x)
    pk = float(a.max()) if len(a) else 0.0
    if pk <= 0:
        return 0.0
    W, HOP = 1024, 512
    env = np.array([float(np.sqrt(np.mean(x[i:i + W] ** 2)))
                    for i in range(0, len(x) - W, HOP)])
    if not len(env):
        return 0.0
    edb = 20 * np.log10(env + 1e-9)
    under = np.where(edb < 20 * math.log10(pk) + rel_db)[0]
    if not len(under):
        return float(len(env) * HOP / sr)
    return float(min(under[0] * HOP / sr, max_s))


def de_reverb(x, sr, amount=0.7, max_tail_s=1.8):
    """简易去混响：削掉衰减尾 + 抑制高频旁路噪声。

    素材本身带 reverb（作者 tags 明写），实测「衰减到 −40 dB」中位 2.47 s，
    远超干拨弦的 0.3–0.6 s。真正的干湿分离需要盲源分离，这里不做那件事，
    改用两条保守措施：
      ① 硬截尾到 max_tail_s（琴的拨弦余响本就短于此）
      ② 随时间递增的低通（高频混响尾先掉，保留基频区的拨弦芯）
    不足以变干声，故在 manifest 记 de_reverb=True，渲染时按此调低混响 wet。
    """
    y = x.copy()
    k = int(max_tail_s * sr)
    if k < len(y):
        # 余弦窗收尾，避免硬截断的咔哒
        y = y[:k] * 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / max(k - 1, 1)))
    if amount <= 0:
        return y
    n = len(y)
    # 分 6 段做递增低通：截止频率从 9 kHz 降到 1.6 kHz
    bps = np.array_split(np.arange(n), 6)
    b_prev, a_prev = butter(2, 9000.0 / (sr / 2), btype="low")
    out = np.empty(n)
    for seg_i, bps_i in enumerate(bps):
        fc = 9000.0 * (1.6 / 9.0) ** (seg_i / 5.0)
        bb, aa = butter(2, min(fc, sr / 2 * 0.95) / (sr / 2), btype="low")
        out[bps_i] = lfilter(bb, aa, y[bps_i])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-peak", type=float, default=0.004)
    ap.add_argument("--stab-cents", type=float, default=110.0)
    ap.add_argument("--scale-off", default="0,2,4,7,9",
                    help="允许的调内半音集合（相对主音）。素材为 D 五声音阶，"
                         "只收落在这些音级上的瞬态")
    ap.add_argument("--scale-root", type=int, default=2,
                    help="调内音级根音（0=C … 2=D）")
    ap.add_argument("--snap-cents", type=float, default=80.0,
                    help="f0 吸附到调内音级的容差（音分）。超过即判为滑音/装饰音")
    ap.add_argument("--scale-lo", type=int, default=38)
    ap.add_argument("--scale-hi", type=int, default=86)
    ap.add_argument("--reverb-max", type=float, default=1.2,
                    help="衰减到 -40dB 的秒数上限，超过判为带混响")
    ap.add_argument("--de-reverb", type=float, default=0.7,
                    help=">0 时对超限样本做简易去混响（高频旁路抑制 + 截尾）")
    ap.add_argument("--repluck", type=float, default=0.75,
                    help="0.62s 后能量回升超过此比例即判为二次拨弦")
    ap.add_argument("--win", type=float, default=3.0, help="每条切片秒数")
    ap.add_argument("--need", default="D3-D6", help="必须覆盖的音域")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    mp3 = CACHE / f"gz_full_{SOUND_ID}.mp3"
    n = get_preview(mp3)
    if not n:
        print("✗ 下载失败")
        return 1
    print(f"素材 {mp3.name}  {mp3.stat().st_size:,} B")
    y, sr = sf.read(str(mp3), dtype="float32", always_2d=True)
    y = y.mean(axis=1).astype(np.float64)
    print(f"  {len(y)/sr:.2f}s  峰值 {np.max(np.abs(y)):.3f}")

    # 瞬态检测
    # 瞬态检测：阈值取 88 百分位。素材带 reverb，响度分布很宽
    # （中位 −43.8 dB、峰值 −7.1 dB），用 92 百分位只抓到最响的一小半
    # 拨弦（实测 1267 → 109 候选 → 21 音高，目标音域缺 25 个）；
    # 放宽到 88 百分位才够覆盖。
    W, HOP = 1024, 256
    env = np.array([float(np.sqrt(np.mean(y[i:i + W] ** 2)))
                    for i in range(0, len(y) - W, HOP)])
    edb = 20 * np.log10(env + 1e-9)
    thr = float(np.percentile(edb, 88))
    act = edb > thr
    onsets = [i * HOP for i in range(1, len(act)) if act[i] and not act[i - 1]]
    print(f"  瞬态 {len(onsets)} 个（阈值 {thr:.1f} dB = 88 百分位）")

    win = int(args.win * sr)
    # 调内音级过滤。素材是 D 五声音阶，但作者写了 "every sound you can get"，
    # 里面混了大量装饰音/刮弦/泛音；f0 稳定判据挡不住「单音泛音被当基音」的
    # 情况（C#7 / A#5 / G#3 这类根本不在五声音阶里）。这里再卡一道调性，
    # 避免把泛音当成独立音高收进库里。
    off = {int(x) for x in args.scale_off.split(",") if x.strip() != ""}
    root = args.scale_root

    def snap(m_raw):
        """把实测 f0 吸附到最近的调内音级。

        直接对舍入后的 midi 做「是否在调内」判断是不行的：稳定阈
        （110 音分）本就比一个半音（100 音分）宽，一个略失谐的 D
        会被舍入到 D#，于是被误当调外丢掉——实测那样会白扔掉 150 条
        真实单音。改成「先吸附到最近调内音级，超出容差才判为装饰音」，
        既能把轻微失谐归位，又仍然挡得住滑音/刮弦（那些偏差远大于容差）。
        """
        m0 = int(round(m_raw))
        best = None
        for m in range(m0 - 2, m0 + 3):
            if not (args.scale_lo <= m <= args.scale_hi):
                continue
            if (m - root) % 12 not in off:
                continue
            s = abs(12.0 * math.log2(
                (440.0 * 2 ** ((m_raw - 69) / 12.0))
                / (440.0 * 2 ** ((m - 69) / 12.0)))) * 100.0
            if best is None or s < best[1]:
                best = (m, s)
        if best is None or best[1] > args.snap_cents:
            return None
        return best[0]

    cands = []
    skipped = 0
    for o in onsets:
        if o + win > len(y):
            continue
        seg = y[o:o + win]
        pk = float(np.max(np.abs(seg)))
        if pk < args.min_peak:
            continue
        # f0 稳定性：起音后 0.05–0.55s
        tr, n_, h_ = f0_track(seg[int(0.05 * sr):int(0.55 * sr)], sr)
        tr = tr[tr > 0]
        if len(tr) < 4:
            continue
        med = float(np.median(tr))
        if med <= 0:
            continue
        spread = float(np.max(np.abs(1200.0 * np.log2(tr / med))))
        if spread > args.stab_cents:
            continue                       # 滑音/扫弦，排除
        # 二次拨弦检查：0.6s 之后能量不得显著回升
        a2 = seg[int(0.62 * sr):]
        a1 = seg[int(0.30 * sr):int(0.55 * sr)]
        if len(a2) and len(a1):
            r2 = float(np.sqrt(np.mean(a2 ** 2)))
            r1 = float(np.sqrt(np.mean(a1 ** 2)))
            if r1 > 0 and r2 > r1 * args.repluck:
                continue                   # 后面还有拨弦，排除
        # 干湿测量：衰减到峰值下 40 dB 的秒数。素材带 reverb，
        # 故记下来供渲染时决定混响量，并对超限者做去混响处理。
        dl = decay_len(seg, sr)
        m_raw = 12.0 * math.log2(med / 440.0) + 69
        m = snap(m_raw)
        if m is None:
            skipped += 1
            continue
        cands.append({"onset": o, "pk": pk, "f0": med, "midi": m,
                      "spread": spread, "decay": dl,
                      "dev": 1200.0 * math.log2(
                          med / (440.0 * 2 ** ((m - 69) / 12.0)))})
    print(f"  通过筛选的候选 {len(cands)} 条（调外剔除 {skipped} 条）")

    # 每音高取最优：f0 偏离 12 平均最小、峰值最大、衰减最短（干声优先）
    by = {}
    for c in cands:
        k = c["midi"]
        score = (abs(c["dev"]) / 20.0        # 音高偏差（半音→0.05 权重）
                 - 6.0 * math.log10(max(c["pk"], 1e-3))
                 - 4.0 * min(c["decay"], 2.0))   # 衰减越短越好
        if k not in by or score > by[k]["score"]:
            c["score"] = score
            by[k] = c
    picks = [by[k] for k in sorted(by)]
    print(f"  去重后 {len(picks)} 个音高："
          f"{nn(picks[0]['midi'])}–{nn(picks[-1]['midi'])}")

    need = args.need
    lo_m = 12 * (int(need.split("-")[0][1:]) + 1) + \
        {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}[need.split("-")[0][:-1]]
    hi_m = 12 * (int(need.split("-")[1][1:]) + 1) + \
        {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
         "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}[need.split("-")[1][:-1]]
    have = {c["midi"] for c in picks}
    # 只统计调内音级。五声音阶本来就没有 3、6 音，用半音阶口径报「缺失」
    # 会一直误导（实测会凭空多报 20 多个），故按五声调式查。
    miss = [m for m in range(lo_m, hi_m + 1)
            if (m - root) % 12 in off and m not in have]
    in_scale_n = sum(1 for m in range(lo_m, hi_m + 1)
                     if (m - root) % 12 in off)
    print(f"  目标 {nn(lo_m)}–{nn(hi_m)} 内共 {in_scale_n} 个调内音级："
          f"缺 {len(miss)} 个 "
          f"{[nn(m) for m in miss] if miss else '（全覆盖）'}")

    # 落盘
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("guzheng_*.wav"):
        old.unlink()
    samples = []
    print(f"\n{'音高':>5} {'MIDI':>4} {'实测f0':>8} {'起音':>8} {'时长':>6} "
          f"{'衰减到-40dB':>11} {'滚降':>7} {'质心':>6} {'本底':>7}")
    for c in picks:
        o = c["onset"]
        seg = y[o:o + win]
        if len(seg) < int(0.5 * sr):
            continue
        bb, aa = butter(2, 55.0 / (sr / 2), btype="high")   # C2=65Hz，取 55Hz
        z = lfilter(bb, aa, seg - float(np.mean(seg)))
        dl_raw = decay_len(z, sr)
        wet = dl_raw > args.reverb_max
        if wet and args.de_reverb > 0:
            z = de_reverb(z, sr, args.de_reverb)
            dl = decay_len(z, sr)
        else:
            dl = dl_raw
        pk = float(np.max(np.abs(z)))
        if pk < 0.003:
            continue
        z = z / pk * 0.891
        m = c["midi"]
        f0 = 440.0 * 2.0 ** ((m - 69) / 12.0)   # 以标注音高为基准（已筛稳定）
        roll, cen, br, nz, att = timbre(z, f0, sr)
        p = out / f"guzheng_{m:03d}.wav"
        sf.write(str(p), z, SR, subtype="PCM_16")
        samples.append({"midi": m, "label": nn(m), "f0_hz": round(f0, 2),
                        "file": p.name, "dur_s": round(len(z) / SR, 3),
                        "onset_s": round(o / SR, 2), "peak": round(pk, 4),
                        "f0_spread_cents": round(c["spread"], 1),
                        "decay_raw_s": round(dl_raw, 3),
                        "decay_to_m40db_s": round(dl, 3),
                        "de_reverb": bool(wet and args.de_reverb > 0),
                        "roll_db_oct": round(roll, 2), "centroid_hz": round(cen),
                        "breath_db": round(br, 2), "noise_db": round(nz, 2),
                        "attack_db": round(att, 2)})
        print(f"{nn(m):>5} {m:>4} {c['f0']:8.1f} {c['onset']/SR:7.2f}s "
              f"{len(z)/SR:5.2f}s {dl_raw:6.2f}→{dl:5.2f}s "
              f"{'湿' if wet else '干'} {roll:6.2f} {cen:6.0f} {nz:7.1f}")

    if not samples:
        print("✗ 未切出样本")
        return 1
    mf = {"instrument": "guzheng",
          "source": f"Freesound sound {SOUND_ID} "
                    "LOVELY CHINESE GUZHENG PLUCKED.wav",
          "url": f"https://freesound.org/people/Pufermufin/sounds/{SOUND_ID}/",
          "author": "Pufermufin",
          "recording": "Blue Spark + Blue Bluebird 电容话筒 → Scarlett 6i6（实录）",
          "license": "CC0 1.0",
          "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
          "attribution": "作者自述 no credits necessary（CC0 非强制署名，此处留档）",
          "tuning": "D 五声音阶（作者自述 tuned in D pentatonic）",
          "scale_filter": (f"只收 D 五声音阶（半音 {sorted(off)}）内、"
                           f"{nn(args.scale_lo)}–{nn(args.scale_hi)} 的瞬态："
                           f"f0 先吸附到最近调内音级（容差 {args.snap_cents:.0f} "
                           f"音分），超出即判为滑音/装饰音。调外剔除 {skipped} 条"),
          "source_detail": ("原文件 495.9 MB / 24:34 / 44.1 kHz / 32-bit float / "
                            "立体声；HQ 预览 23.1 MB / 1474 s 已含完整内容。"),
          "derived": ("HQ 预览 → 瞬态检测（92 百分位阈值）→ 筛「干净单音」"
                      f"（f0 稳定 ≤{args.stab_cents:.0f} 音分、峰值 ≥"
                      f"{args.min_peak}、无二次拨弦）→ 每音高取最优 1 条 → "
                      f"{args.win:.0f}s 切片 → 55Hz 高通 → 峰值归一(-1 dBFS) → "
                      "单声道 44.1k"),
          "dry_wet_note": ("素材 tags 含 reverb，故逐条记录「衰减到峰值下 40 dB 的"
                           "秒数」；若偏长说明带环境混响，渲染时混响要相应调低。"),
          "sr": SR, "n": len(samples),
          "range": f"{samples[0]['label']}–{samples[-1]['label']}",
          "samples": samples}
    (out / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"\n{len(samples)} 条 → {out}   音域 {mf['range']}")
    import statistics as st
    for k in ("roll_db_oct", "centroid_hz", "noise_db", "attack_db",
              "decay_to_m40db_s", "f0_spread_cents"):
        print(f"  {k} 中位数: {st.median([s[k] for s in samples]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
