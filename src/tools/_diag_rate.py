# -*- coding: utf-8 -*-
"""比较不同底样语速/文本切分下的「连贯度」：生成 edge 样本 -> 转 wav -> 输出包络与谷值统计。"""
import asyncio
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

try:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FF = "ffmpeg"

SR = 24000
FP = 20.0
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

OUT = os.path.join(ROOT, "dist", "audio", "voice")


def synth(text, voice, rate, out_wav):
    import edge_tts
    mp3 = out_wav.replace(".wav", ".mp3")
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(mp3))
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", mp3, "-ar", str(SR), "-ac", "1", out_wav],
                   check=True)
    os.remove(mp3)


def report(path, label):
    x, sr = sf.read(path, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    hop = int(sr * FP / 1000.0)
    n = len(x) // hop
    e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)) for i in range(n)])
    pk = np.percentile(e, 99)
    db = 20 * np.log10(np.maximum(e, 1e-9) / pk)
    # 谷值：低于 -18dB 且两侧都有更高能量的连续帧
    low = db < -18.0
    valleys = []
    i = 0
    while i < n:
        if not low[i]:
            i += 1
            continue
        s = i
        while i < n and low[i]:
            i += 1
        if s > 0 and i < n:                      # 行内
            valleys.append((i - s) * FP)
    deep = [v for v in valleys if v >= 60.0]     # ≥60ms 的深谷 = 明显的「断」
    line = "".join(" .:-=+*#%@"[int(np.clip((d + 40) / 4.0, 0, 9))] for d in db)
    print(f"-- {label}  时长 {len(x)/sr:.2f}s  谷值段 {len(valleys)}（≥60ms: {len(deep)}）"
          f"  最深谷 {max(valleys) if valleys else 0:.0f}ms")
    for i in range(0, len(line), 70):
        print("     " + line[i:i + 70])


if __name__ == "__main__":
    voice = "zh-CN-YunjianNeural"
    cases = [
        ("床前明月光", "-38%", "单句 rate-38%（当前底样）"),
        ("床前明月光", "-18%", "单句 rate-18%"),
        ("床前明月光", "-5%", "单句 rate-5%"),
        ("床前明月光，疑是地上霜。举头望明月，低头思故乡。", "-18%", "整首 一语气 rate-18%"),
    ]
    for idx, (text, rate, label) in enumerate(cases):
        wav = os.path.join(OUT, f"_rate{idx}.wav")
        synth(text, voice, rate, wav)
        report(wav, label)
        print()
