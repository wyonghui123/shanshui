#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键生成某首诗的全部配音样本。

流程（每音色）：edge 底样 -> 吟诵版（纯韵律）-> 情感版（韵律 + 情感层）。
停顿/气口/句首滑音等结构规则由 voice_prosody_process.py 恒定施加，此处不重复。

用法：
  python src/voice/voice_build_all.py --poem jx
  python src/voice/voice_build_all.py --poem bd
  python src/voice/voice_build_all.py --poem jx --voices zh-CN-YunjianNeural
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

OUTDIR = os.path.join(ROOT, "dist", "audio", "voice")
GEN = os.path.join(ROOT, "src", "voice", "voice_sample_gen.py")
PROS = os.path.join(ROOT, "src", "voice", "voice_prosody_process.py")

VOICES = ["zh-CN-YunjianNeural", "zh-CN-YunxiNeural", "zh-CN-YunyangNeural"]
PRESET_TAG = {"sad_longing": "sad", "cold_lonely": "cold", "joyful_swift": "joy"}


def run(cmd):
    print(">>", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)), flush=True)
    subprocess.run(cmd, check=True, cwd=HERE)


def main():
    sys.path.insert(0, HERE)
    from voice_prosody_process import POEMS

    ap = argparse.ArgumentParser()
    ap.add_argument("--poem", required=True, choices=sorted(POEMS.keys()))
    ap.add_argument("--voices", nargs="*", default=VOICES)
    ap.add_argument("--skip-base", action="store_true", help="跳过 edge 底样，复用已有")
    args = ap.parse_args()

    poem = POEMS[args.poem]
    preset = poem["emotion"]
    tag = PRESET_TAG[preset]
    os.makedirs(OUTDIR, exist_ok=True)

    for v in args.voices:
        base = os.path.join(OUTDIR, f"{args.poem}_edge_{v}_quatrain.wav")
        if not args.skip_base:
            run([sys.executable, GEN, "--backend", "edge", "--voice", v, "--poem", args.poem])
        if not os.path.exists(base):
            sys.exit(f"缺少底样：{base}")

        run([sys.executable, PROS,
             "--in-wav", base,
             "--out-wav", os.path.join(OUTDIR, f"{args.poem}_prosody_{v}.wav"),
             "--out-json", os.path.join(OUTDIR, f"{args.poem}_prosody_{v}.json"),
             "--poem", args.poem])

        run([sys.executable, PROS,
             "--in-wav", base,
             "--out-wav", os.path.join(OUTDIR, f"{args.poem}_emotion_{tag}_{v}.wav"),
             "--out-json", os.path.join(OUTDIR, f"{args.poem}_emotion_{tag}_{v}.json"),
             "--poem", args.poem, "--emotion", preset,
             "--ratio-gain", "1.0", "--match-duration"])

    print(f"=== {args.poem} ALL DONE ({len(args.voices)} voices) ===")


if __name__ == "__main__":
    main()
