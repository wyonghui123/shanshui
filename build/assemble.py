# -*- coding: utf-8 -*-
"""交付包装配：从 canonical 重建 dist/三首诗歌交付/。

映射：
  01_诗全流程分析/<poem>_pipeline.html   ← dist/pipelines/            （原样复制）
  02_水墨动画_带语音/ink_animations.html ← dist/animation/            （音轨路径改写为包内 samples/）
  02_水墨动画_带语音/strokes.js          ← dist/animation/            （逐笔中线/字形数据，原样复制）
  02_水墨动画_带语音/fonts/*.woff2       ← dist/animation/fonts/      （题诗字体子集，相对路径与源一致，不改写）
  02_水墨动画_带语音/samples/voice/*.wav ← dist/audio/voice/          （原样复制）
  02_水墨动画_带语音/samples/music/*.wav ← dist/audio/music/          （D3 音乐轨，原样复制）
  index.html                             ← 手工维护，装配不触碰

用法：
    python build/assemble.py           # 装配（幂等）
    python build/assemble.py --check   # 只校验交付副本是否与 canonical 同步
"""
import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
PKG = os.path.join(DIST, "三首诗歌交付")
PIPES = os.path.join(DIST, "pipelines")
ANIM_SRC = os.path.join(DIST, "animation", "ink_animations.html")
ANIM_STROKES = os.path.join(DIST, "animation", "strokes.js")
ANIM_FONTS = os.path.join(DIST, "animation", "fonts")
AUDIO_SRC = os.path.join(DIST, "audio", "voice")
MUSIC_SRC = os.path.join(DIST, "audio", "music")

POEMS = ["jiangxue", "baidicheng", "jingyesi"]
WAVS = ["jx_emotion_cold_zh-CN-YunjianNeural.wav",
        "bd_emotion_joy_zh-CN-YunjianNeural.wav",
        "jys_emotion_sad_zh-CN-YunjianNeural.wav"]
MUSIC_WAVS = ["jx.wav", "bd.wav", "jys.wav"]


def anim_transform(text):
    """canonical（dist/animation）-> 交付包（包内 samples/）。"""
    return (text
            .replace("audio: '../audio/voice/", "audio: 'samples/voice/")
            .replace("music: '../audio/music/", "music: 'samples/music/")
            .replace("dist/audio/voice/{poem}_emotion_*.wav",
                     "samples/voice/{poem}_emotion_*.wav"))


def expected():
    out = {}
    for p in POEMS:
        out["01_诗全流程分析/%s_pipeline.html" % p] = \
            open(os.path.join(PIPES, "%s_pipeline.html" % p), "rb").read()
    with open(ANIM_SRC, encoding="utf-8") as f:
        out["02_水墨动画_带语音/ink_animations.html"] = \
            anim_transform(f.read()).encode("utf-8")
    out["02_水墨动画_带语音/strokes.js"] = \
        open(ANIM_STROKES, "rb").read()
    for fp in sorted(glob.glob(os.path.join(ANIM_FONTS, "*.woff2"))):
        out["02_水墨动画_带语音/fonts/" + os.path.basename(fp)] = \
            open(fp, "rb").read()
    for w in WAVS:
        out["02_水墨动画_带语音/samples/voice/" + w] = \
            open(os.path.join(AUDIO_SRC, w), "rb").read()
    for w in MUSIC_WAVS:
        out["02_水墨动画_带语音/samples/music/" + w] = \
            open(os.path.join(MUSIC_SRC, w), "rb").read()
    return out


def main():
    check = "--check" in sys.argv
    exp = expected()
    drift = 0
    for rel, data in exp.items():
        dst = os.path.join(PKG, rel.replace("/", os.sep))
        if check:
            cur = open(dst, "rb").read() if os.path.exists(dst) else None
            ok = cur == data
            print(("  ✓ " if ok else "  ✗ ") + rel)
            drift += 0 if ok else 1
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            print("  → " + rel)
    if check:
        print("\n" + ("✓ 交付包与 canonical 同步"
                      if drift == 0 else "✗ %d 项漂移（跑 python build/assemble.py 修复）" % drift))
        sys.exit(1 if drift else 0)
    print("\n装配完成：%d 项" % len(exp))


if __name__ == "__main__":
    main()
