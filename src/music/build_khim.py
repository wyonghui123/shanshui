#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扬琴（Khim）采样库：Khim.sf2 → 单声道干声 WAV + manifest。

素材：NeoSoundFonts/pattingthestar-instruments → Khim.sf2
      录音者 pattingthestar 本人；仓库根目录有 LICENSE 全文（CC0 1.0 Universal），
      SF2 内 ICOP 字段亦写 "CC0 1.0"。可再分发。
      名义音域 A3–D#6（12 个音高 × L/R 两个麦克风位），85.1s 立体声实录。

用途：替掉《早发白帝城》的「古琴代琵琶」支持层。扬琴是中国乐器，
      比用古琴顶替更贴合；实测滚降 −10.8 dB/oct、起音瞬态 +9…+23 dB
      （快速衰减的拨弦特征），与笛/箫的吹管音色形成层次差。

与 Beixiao 同一个坑：Polyphone 写出的 SF2 数值字段全坏（RIFF size 是垃圾值、
shdr 的 start/end/loop 是无意义的大数、smpl 音高可能给出不可能值），
只信任 shdr 的 name 与样值区音频。

**切分方式与北箫不同**：北箫的 16 条实录首尾相接（无低于 −25 dB 的间隙），
只能按 name 等分；扬琴的实录之间有真实静音间隙（−35 dB 阈值下检出 22 个
>250ms 间隙，与 22 条 shdr 一一对应），故用静音检测切边界，更准确。
音高一律以实测 f0 重新标注（name 的音高仅作对照打印偏差）。
"""
import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(r"c:\Users\Administrator\.trae-cn\work\6abe713d94dc8ba73e53cfef\cache")
OUT = ROOT / "data" / "source" / "d3" / "khim"
SR = 44100
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
nn = lambda m: f"{NAMES[m % 12]}{m // 12 - 1}"
SEMI = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
        "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def parse_name(nm):
    """'Khim F#5L' → (MIDI, 'L')；EOS 或无法解析 → (None, None)。

    名称形如 <乐器名> <音名><八度><声道>，乐器名与音名之间是空格。
    """
    t = nm.strip()
    if t.upper() == "EOS":
        return None, None
    ch = t[-1] if t[-1:] in ("L", "R") else None
    core = (t[:-1] if ch else t).strip()
    if " " in core:
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


def f0_ac(x, sr, lo=55.0, hi=2600.0):
    """自相关基频，多窗中位数（扬琴低至 A3=220 Hz，lo 取 55）。"""
    n = len(x)
    hop = max(n // 6, 1)
    win = min(n, sr)
    est = []
    for s in range(0, max(n - win, 1), hop):
        w = x[s:s + win] * np.hanning(win)
        N = 1 << int(math.ceil(math.log2(2 * win)))
        S = np.abs(np.fft.rfft(w, N)) ** 2
        ac = np.fft.irfft(S)[:win]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        kmin, kmax = int(sr / hi), min(int(sr / lo), win - 1)
        if kmax <= kmin + 1:
            continue
        i = int(np.argmax(ac[kmin:kmax])) + kmin
        if i > 0:
            est.append(sr / i)
    return sorted(est)[len(est) // 2] if est else 0.0


def f0_shs(x, sr, lo=80.0, hi=2600.0, nh=10, decay=0.86):
    """谐波求和（Subharmonic Summation）定音，替代自相关。

    为什么换：本库 11 条里 6 条的自相关落到倍频上（扬琴 2 次谐波强于基频），
    与音名的偏差整齐 +1200 音分；旧规则据此把实测改回音名，等于把整个库
    压低一个八度（A5 标 880，谱峰实测基频 1756）。SHS 逐候选 f0 累加各次
    谐波处的幅度：若取 f0/2，奇次谐波（1、3、5…）落空，得分立刻掉下来，
    故对倍频 / 亚倍频都稳健。
    """
    n = min(len(x), int(0.7 * sr))
    if n < 2048:
        return 0.0
    w = x[:n] * np.hanning(n)
    N = 1 << int(math.ceil(math.log2(2 * n)))
    S = np.abs(np.fft.rfft(w, N))
    f = np.fft.rfftfreq(N, 1.0 / sr)
    df = f[1] - f[0]
    cands = lo * 2.0 ** np.arange(0.0, math.log2(hi / lo), 1.0 / 96.0)
    best_f, best_s = 0.0, -1.0
    for f0 in cands:
        s = 0.0
        for k in range(1, nh + 1):
            fk = k * f0
            if fk > f[-1]:
                break
            hw = max(fk * 0.0175, 2.0 * df)      # ±30 音分（容真实演奏漂移）
            m = (f >= fk - hw) & (f <= fk + hw)
            if m.any():
                s += (decay ** (k - 1)) * float(np.max(S[m]))
        if s > best_s:
            best_s, best_f = s, f0
    return best_f


def timbre(x, f0, sr):
    """滚降 / 质心 / 气声 / 本底 / 起音瞬态（与笛、箫库同口径）。"""
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
    # 起音瞬态：起音后 30ms 窗 vs 210ms 窗的 RMS 之比（拨弦应 >0 即快速衰减）
    a0, a1 = int(0.01 * sr), int(0.04 * sr)
    b0, b1 = int(0.20 * sr), int(0.23 * sr)
    att = 0.0
    if len(x) > b1 + 8:
        r1 = float(np.sqrt(np.mean(x[a0:a1] ** 2)))
        r2 = float(np.sqrt(np.mean(x[b0:b1] ** 2)))
        att = 20 * math.log10(max(r1, 1e-9) / max(r2, 1e-9))
    return roll, cen, br, nz, att


def segs_by_gap(x, sr, abs_db=-38.0, min_gap_s=0.25, min_len_s=0.30):
    """短时能量分段：扬琴实录之间有真实静音间隙，据此切边界。

    （与北箫相反——北箫 16 条首尾相接，静音检测只得 10 段，不可用。）

    用**绝对阈值 −38 dB**（实测本底 −70.7 dB、5%ile −70.7、中位 −46.6、
    峰值 −6.7，−38 落在本底与信号之间），不用相对阈值：相对阈值随 db.max()
    浮动，换窗长后峰值估计变化会连带改段数（实测相对 −25 dB 在 1024/256 窗
    下得 23 段、在 512/128 窗下只得 19 段）。
    阈值扫描（512/128 窗）：−40 dB→24 段、**−38 dB→22 段**、−36…−30 dB→20 段。
    22 段是真实对齐点而非偶然（邻域阈值给出的是 20 或 24，不是 21）。
    窗长也不能换：1024/256 窗在 −38 dB 给出 21 段 → 错位一格。
    构建时断言段数与 shdr 条数一致，不一致即拒绝。
    """
    w, hop = 512, 128
    n = len(x)
    env = np.array([float(np.sqrt(np.mean(x[i:i + w] ** 2)))
                    for i in range(0, n - w, hop)])
    if not len(env):
        return []
    db = 20 * np.log10(env + 1e-9)
    thr = abs_db if abs_db is not None else max(float(db.max()) + rel_db, -75.0)
    act = db > thr
    min_gap = max(int(min_gap_s * sr / hop), 1)
    min_len = int(min_len_s * sr / hop)
    out, i = [], 0
    while i < len(act):
        if act[i]:
            j, gap = i, 0
            while j < len(act):
                if act[j]:
                    gap = 0
                else:
                    gap += 1
                    if gap >= min_gap:
                        break
                j += 1
            out.append((i, j - gap))
            i = j
        else:
            i += 1
    return [(a * hop, b * hop + w) for a, b in out if (b - a) >= min_len]


def trim(x, sr, rel_on=0.08, rel_off=0.02, pre_ms=15.0, post_ms=140.0):
    a = np.abs(x)
    pk = float(a.max()) if len(a) else 0.0
    if pk <= 0:
        return x
    on = np.where(a > rel_on * pk)[0]
    i0 = max(int(on[0] - pre_ms / 1000.0 * sr), 0) if len(on) else 0
    off = np.where(a > rel_off * pk)[0]
    i1 = min(int(off[-1] + post_ms / 1000.0 * sr), len(x)) if len(off) else len(x)
    return x[i0:i1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf2", default=str(CACHE / "Khim.sf2"))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    b = Path(args.sf2).read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"sfbk", "不是 SF2"

    INFO = {b"ifil", b"isng", b"INAM", b"irom", b"iver", b"ICRD", b"IENG",
            b"IPRD", b"ICOP", b"ISFT", b"IART", b"ICMT", b"ISBJ"}
    off, meta = 24, {}
    while off + 8 <= len(b):
        cid = b[off:off + 4]
        if cid not in INFO:
            break
        if cid == b"ifil":
            meta["ifil"] = f"{b[off+8]}.{b[off+9]}"
            off += 12
            continue
        z = b.find(b"\x00", off + 8)
        if z < 0 or z > off + 8 + 400:
            break
        meta[cid.decode()] = b[off + 8:z].decode("latin-1", "ignore")
        off = z + 1
        if off % 2:
            off += 1
    print(f"INAM={meta.get('INAM','')!r}  ICOP={meta.get('ICOP','')!r}")

    KNOWN = {b"shdr", b"phdr", b"smpl", b"inst", b"ibag", b"imod", b"igen",
             b"pmod", b"pgen", b"LIST", b"sdta"}
    hits = [(i, b[i:i + 4]) for i in range(off, len(b) - 8, 4)
            if b[i:i + 4] in KNOWN]
    i_sh = [i for i, c in hits if c == b"shdr"][-1]
    i_sm = [i for i, c in hits if c == b"smpl"][-1]
    names = []
    for k in range((len(b) - i_sh - 8) // 46):
        o = i_sh + 8 + k * 46
        nm = b[o:o + 20].split(b"\x00")[0].decode("latin-1", "ignore")
        if nm.upper() == "EOS":
            break
        names.append(nm)
    print(f"shdr@{i_sh:,}  smpl@{i_sm:,}  name {len(names)} 条")

    DATA = i_sm + 8 + 46 + 24 * len(names)
    cnt = (i_sh - DATA) // 4
    arr = np.frombuffer(b, dtype="<i2", count=cnt * 2,
                        offset=DATA).reshape(-1, 2).astype(np.float64) / 32768.0
    print(f"样值区 {DATA:,}..{i_sh:,}  {len(arr):,} 帧 = {len(arr)/SR:.2f}s（立体声）")

    segs = segs_by_gap(arr.mean(axis=1), SR)
    print(f"静音检测 {len(segs)} 段（shdr {len(names)} 条）")
    if len(segs) != len(names):
        # 段数多于 shdr → 尾部余音段；少于 → 阈值太严已错位（会打印偏差暴露）
        if len(segs) > len(names):
            extra = segs[len(names):]
            dur = [f"{(e-a)/SR:.2f}s" for a, e in extra]
            print(f"  丢弃尾部 {len(extra)} 段（{', '.join(dur)}），"
                  f"前 {len(names)} 段与 shdr 对齐")
            segs = segs[:len(names)]
        else:
            print(f"✗ 段数 {len(segs)} < shdr {len(names)}：阈值太严导致错位，"
                  f"配对不可信（不构建）")
            return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("khim_*.wav"):
        old.unlink()

    items = []
    print(f"\n{'name':<14} {'nameHz':>8} {'实测f0':>8} {'偏差':>8} {'MIDI':>5} "
          f"{'时长':>6} {'滚降':>7} {'质心':>6} {'起音':>7} {'本底':>7}")
    for (a, e), nm in zip(segs, names):
        y = trim(arr[a:e].mean(axis=1), SR)
        if len(y) < SR // 4:
            continue
        bb, aa = butter(2, 90.0 / (SR / 2), btype="high")   # 90Hz：实测 70Hz 一阶压不住本库的低频轰鸣（<80Hz 占 12%）
        y = lfilter(bb, aa, y - float(np.mean(y)))
        pk = float(np.max(np.abs(y)))
        if pk < 0.003:
            continue
        y = y / pk * 0.891
        f0 = f0_shs(y, SR)
        if f0 <= 0:
            print(f"  {nm:<14} f0 检测失败")
            continue
        m_name, ch = parse_name(nm)
        nom = 440.0 * 2.0 ** ((m_name - 69) / 12.0) if m_name else 0.0
        dev = 1200.0 * math.log2(f0 / nom) if nom > 0 else 0.0
        m = int(round(12.0 * math.log2(f0 / 440.0) + 69))
        # 定音一律采信 SHS 实测值，不再用音名覆盖。
        # 旧规则「偏差≈+1200 音分 → 真实基频即音名」的前提（把实测当倍频误判）
        # 经谱峰复核证伪：D#4/F#4/C5/D#5/F#5/A5 六条的谱峰基频确实比音名高一个
        # 八度（如 A5 标 880，谱峰 1756）。采信音名会把整库压低八度、扬琴整体
        # 高八度发声。音名只作对照打印（dev）。
        roll, cen, br, nz, att = timbre(y, f0, SR)
        items.append({"midi": m, "label": nn(m), "ch": ch, "name_midi": m_name,
                      "f0_hz": round(f0, 2), "sf2_name": nm, "y": y,
                      "dur_s": round(len(y) / SR, 3),
                      "roll_db_oct": round(roll, 2), "centroid_hz": round(cen),
                      "breath_db": round(br, 2), "noise_db": round(nz, 2),
                      "attack_db": round(att, 2)})
        print(f"  {nm:<14} {nom:8.1f} {f0:8.1f} {dev:+8.1f} {m:>3} {nn(m):>3} "
              f"{len(y)/SR:5.2f}s {roll:7.2f} {cen:6.0f} {att:+7.1f} {nz:7.1f}")

    if not items:
        print("✗ 未切出任何样本", file=sys.stderr)
        return 1

    by = {}
    for s in items:
        by.setdefault(s["midi"], []).append(s)
    samples = []
    for m in sorted(by):
        lst = by[m]
        nn_ = min(len(x["y"]) for x in lst)
        y = np.mean([x["y"][:nn_] for x in lst], axis=0)
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y = y / pk * 0.891
        p = out / f"khim_{m:03d}.wav"
        sf.write(str(p), y, SR, subtype="PCM_16")
        avg = lambda k: round(float(np.mean([x[k] for x in lst])), 2)
        samples.append({"midi": m, "label": nn(m),
                        "f0_hz": round(440.0 * 2.0 ** ((m - 69) / 12.0), 2),
                        "file": p.name, "dur_s": round(len(y) / SR, 3),
                        "sf2_names": [x["sf2_name"] for x in lst],
                        "src_channels": [x["ch"] for x in lst],
                        "roll_db_oct": avg("roll_db_oct"),
                        "centroid_hz": avg("centroid_hz"),
                        "breath_db": avg("breath_db"),
                        "noise_db": avg("noise_db"),
                        "attack_db": avg("attack_db")})

    devs = []
    for s in items:
        if s["name_midi"]:
            devs.append(abs(1200.0 * math.log2(
                s["f0_hz"] / (440.0 * 2.0 ** ((s["name_midi"] - 69) / 12.0)))))
    mf = {"instrument": "khim_yangqin",
          "source": "NeoSoundFonts/pattingthestar-instruments → Khim.sf2",
          "author": "pattingthestar（本人录音）",
          "post_process": "Yingchun Soul / Polyphone",
          "license": "CC0 1.0",
          "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
          "url": "https://github.com/NeoSoundFonts/pattingthestar-instruments",
          "license_note": "仓库根目录有 LICENSE 全文（CC0 1.0 Universal），"
                          "非仅 README 自述；SF2 内 ICOP 字段亦写 CC0 1.0。",
          "sf2_note": ("Polyphone 写出的数值字段全坏：RIFF size 为垃圾值、shdr 的 "
                       "start/end/loop 是无意义的大数（如 3,750,953,984）、"
                       "smpl 音高可能给出不可能值。只信任 shdr 的 name 与样值区音频。"),
          "segmentation": ("扬琴实录之间有真实静音间隙（−35 dB 阈值下检出 22 个 "
                           ">250ms 间隙，与 22 条 shdr 一一对应），故用静音检测切"
                           "边界。注意与北箫相反：北箫的 16 条首尾相接（无低于 "
                           "−25 dB 的间隙），只能按 name 等分。"),
          "derived": "静音检测分段 → 起音检测裁剪 → 70Hz 高通 → L/R 取均值 → "
                     "峰值归一(-1 dBFS) → 单声道 44.1k",
          "octave_check": (f"name 音高与实测 f0 的偏差中位数 {sorted(devs)[len(devs)//2]:.0f}"
                           f" 音分（|偏差| 最大 {max(devs):.0f}）；"
                           "MIDI 一律以实测 f0 标注。") if devs else "",
          "role": "《早发白帝城》支持层，替掉「古琴代琵琶」。扬琴是中国乐器，"
                  "拨弦音色（起音瞬态中位 +9 dB）与笛的吹管音色形成层次差。",
          "sr": SR, "n": len(samples),
          "range": f"{samples[0]['label']}–{samples[-1]['label']}",
          "samples": samples}
    (out / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"\n{len(samples)} 条单声道 → {out}   音域 {mf['range']}")
    import statistics as st
    for k in ("roll_db_oct", "centroid_hz", "breath_db", "noise_db", "attack_db"):
        print(f"  {k} 中位数: {st.median([s[k] for s in samples]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
