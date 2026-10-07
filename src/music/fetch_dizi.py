#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓取并制作 D3 笛采样库（实录）。

来源：Freesound「Flute Dizi C all notes + pitched semitones」（Hypnotriod, pack 21613）
      许可 CC0 1.0（Public Domain）—— 已在 Freesound 的 CC0 筛选下复核。
      公开可取的素材为 192kbps HQ 预览 MP3（原始 WAV 需登录 Freesound；
      本脚本只走公开预览，保证「一条命令可复现」）。

产物：data/source/d3/dizi/dizi_<midi>.wav（单声道 44.1k）+ manifest.json
处理：转单声道 44.1k → 一阶高通 60Hz（去竹管录音的低频晃动）→
      去起音前静音（向前回退 5ms 保住起音瞬态）→ 去尾部静音 → 峰值归一 → 实测 f0

为什么换成实录：加性合成的笛谐波滚降只有 −6.9 dB/oct（近似锯齿波），听感「电子」；
本包实录中位 −13.6 dB/oct，且有逐音不同的自然漂移与气声，是合成做不出来的。
"""
import json
import math
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "source" / "d3" / "dizi"

# pack 21613 的 25 条：MIDI 号 → Freesound sound id（文件名里的编号即 MIDI）
MIDI2SID = {
    67: 384940, 68: 384939, 69: 384938, 70: 384937, 71: 384944, 72: 384943,
    73: 384942, 74: 384941, 75: 384946, 76: 384945, 77: 384956, 78: 384955,
    79: 384954, 80: 384953, 81: 384960, 82: 384959, 83: 384958, 84: 384957,
    85: 384962, 86: 384961, 87: 384950, 88: 384951, 89: 384948, 90: 384949,
    91: 384952,
}
USER_ID = 5093019
SR = 44100

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_note_name(m):
    return "%s%d" % (NOTE_NAMES[m % 12], m // 12 - 1)


def highpass(x, sr, fc=60.0):
    if len(x) < 8:
        return x
    c = math.exp(-2.0 * math.pi * fc / sr)
    return lfilter([c, -c], [1.0, -c], x)


def f0_harmonic(x, sr, lo=150.0, hi=2000.0):
    w = x - float(np.mean(x))
    n = len(w)
    if n < 256:
        return 0.0
    nfft = 1 << int(np.ceil(math.log2(2 * n)))
    X = np.abs(np.fft.rfft(w * np.hanning(n), nfft))
    fr = np.fft.rfftfreq(nfft, 1.0 / sr)
    best, bf = -1.0, 0.0
    for f0 in np.arange(lo, hi, 0.25):
        s = 0.0
        for k in range(1, 9):
            fk = f0 * k
            if fk > sr / 2 - 50:
                break
            i0 = np.searchsorted(fr, fk * 0.985)
            i1 = np.searchsorted(fr, fk * 1.015)
            if i1 > i0:
                s += float(X[i0:i1 + 1].max())
        if s > best:
            best, bf = s, f0
    return bf


def decode_mp3(path):
    """先试 libsndfile（对个别 Xing 头损坏的预览更宽容），再回退 ffmpeg。"""
    try:
        y, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return y.mean(axis=1).astype(np.float64), sr
    except Exception:
        with tempfile.TemporaryDirectory() as td:
            wav = str(Path(td) / "a.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), wav],
                           check=True, stderr=subprocess.DEVNULL)
            y, sr = sf.read(wav, dtype="float32", always_2d=True)
        return y.mean(axis=1).astype(np.float64), sr


def fetch(midi, cache: Path, tries=5):
    """下载并校验：Freesound CDN 偶发返回截断/损坏的预览，需解码验证后重试。"""
    sid = MIDI2SID[midi]
    dst = cache / ("dizi_%03d.mp3" % midi)
    url = "https://cdn.freesound.org/previews/%d/%d_%d-hq.mp3" % (sid // 1000, sid, USER_ID)
    for _ in range(tries):
        if dst.exists() and dst.stat().st_size > 0:
            try:
                decode_mp3(dst)
                return dst
            except Exception:
                dst.unlink(missing_ok=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
                f.write(r.read())
        except Exception:
            dst.unlink(missing_ok=True)
    raise RuntimeError("MIDI %d 下载 %d 次仍不可解码" % (midi, tries))


def trim(x, sr, rel_on=0.06, back_ms=5.0, rel_off=0.004, pad_ms=60.0):
    a = np.abs(x)
    pk = float(a.max()) if len(a) else 0.0
    if pk <= 0:
        return x
    on = np.where(a > rel_on * pk)[0]
    i0 = max(int(on[0] - back_ms / 1000.0 * sr), 0) if len(on) else 0
    off = np.where(a > rel_off * pk)[0]
    i1 = min(int(off[-1] + pad_ms / 1000.0 * sr), len(x)) if len(off) else len(x)
    return x[i0:i1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "_src_preview"
    cache.mkdir(exist_ok=True)
    samples = []
    for midi in sorted(MIDI2SID):
        mp3 = fetch(midi, cache)
        y, sr_in = decode_mp3(mp3)
        if sr_in != SR:
            n = int(round(len(y) * SR / sr_in))
            y = np.interp(np.arange(n) * (sr_in / SR), np.arange(len(y)), y)
        y = highpass(y - float(np.mean(y)), SR, 60.0)
        y = trim(y, SR)
        pk = float(np.max(np.abs(y))) if len(y) else 0.0
        if pk > 0:
            y /= pk
        f0 = f0_harmonic(y, SR)
        name = "dizi_%03d.wav" % midi
        sf.write(str(OUT / name), y.astype(np.float32), SR, subtype="PCM_16")
        samples.append({
            "label": "dizi_%03d" % midi,
            "file": name,
            "midi": midi,
            "note": midi_note_name(midi),
            "sr": SR,
            "dur_s": round(len(y) / SR, 3),
            "f0_hz": round(f0, 2),
            "f0_source": "实测（谐波求和）",
        })
        print("  %-4s MIDI %3d  f0 %8.2f Hz  %5.2fs" % (midi_note_name(midi), midi, f0, len(y) / SR))

    f0s = [s["f0_hz"] for s in samples]
    man = {
        "license": {
            "dataset": "Flute Dizi C all notes + pitched semitones",
            "author": "Hypnotriod (Freesound)",
            "source": "Freesound pack 21613",
            "url": "https://freesound.org/people/Hypnotriod/packs/21613/",
            "license": "CC0 1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "attribution": "Hypnotriod, Freesound pack 21613, CC0 1.0",
            "note": "公开可取素材为 192kbps HQ 预览 MP3（原始 WAV 需登录 Freesound）；"
                    "包名含 '+ pitched semitones'，即半音由真实录音变调得到。"
                    "文件名标注的音名比实际高一个八度，实测音域 G4–G6。",
            "f0_method": "谐波求和（150–2000Hz 内 8 次谐波能量最大者）",
        },
        "range_hz": [round(min(f0s), 2), round(max(f0s), 2)],
        "samples": samples,
    }
    (OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出 %d 条 manifest → %s" % (len(samples), OUT / "manifest.json"))
    print("音域实测 %.1f – %.1f Hz" % (min(f0s), max(f0s)))


if __name__ == "__main__":
    sys.exit(main())
