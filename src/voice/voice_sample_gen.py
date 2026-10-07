#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绝句配音出样脚本 — 统一入口（多首）
==================================
生成整首样音（四句按「起承转合」逐句合成，带停顿预算拼接）。

后端：
  edge   边缘 TTS（免费、无需 key，立即可用）
  azure  Azure Speech（需 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION）
  volc   火山引擎豆包语音（需 VOLC_ACCESS_KEY / VOLC_SECRET_KEY / VOLC_APP_ID）
  aliyun 阿里云 CosyVoice（需 DASHSCOPE_API_KEY）

用法：
  python src/voice/voice_sample_gen.py --backend edge --voice zh-CN-YunjianNeural --poem jys
  python src/voice/voice_sample_gen.py --backend edge --voice zh-CN-YunjianNeural --poem jx
  python src/voice/voice_sample_gen.py --backend edge --voice zh-CN-YunjianNeural --poem bd
  python src/voice/voice_sample_gen.py --backend azure --voice poet --poem jys

诗目（--poem）：jys 静夜思 / jx 江雪 / bd 早发白帝城
输出：samples/voice/{poem}_edge_{voice}_quatrain.wav / .mp3
依赖：edge-tts、numpy、soundfile、ffmpeg（PATH 中）。
"""

import argparse
import asyncio
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

import subprocess
import sys

# ---------------------------------------------------------------- 参数区
# 逐首诗的四句配置。rate/pitch/vol 供 edge-tts 合成平读底样；pre/post 为底样句间静音
# （仅用于让后处理脚本能切出 4 句，最终停顿由 voice_prosody_process.py 重排）。
POEMS = {
    "jys": {  # 静夜思 · 李白（五言，下平七阳平韵）
        "title": "静夜思 · 李白",
        "lines": [
            {"seg": "起", "text": "床前明月光", "rate": 0.62, "pitch": 0.90, "vol": 0.80, "pre": 0.3, "post": 1.0},
            {"seg": "承", "text": "疑是地上霜", "rate": 0.58, "pitch": 0.85, "vol": 0.70, "pre": 0.6, "post": 1.5},
            {"seg": "转", "text": "举头望明月", "rate": 0.66, "pitch": 1.00, "vol": 0.85, "pre": 0.4, "post": 1.3},
            {"seg": "合", "text": "低头思故乡", "rate": 0.52, "pitch": 0.80, "vol": 0.75, "pre": 0.8, "post": 2.0},
        ],
    },
    "jx": {  # 江雪 · 柳宗元（五言，入声屑韵，折腰体）
        "title": "江雪 · 柳宗元",
        "lines": [
            {"seg": "起", "text": "千山鸟飞绝", "rate": 0.56, "pitch": 0.82, "vol": 0.72, "pre": 0.4, "post": 1.2},
            {"seg": "承", "text": "万径人踪灭", "rate": 0.54, "pitch": 0.80, "vol": 0.68, "pre": 0.5, "post": 1.4},
            {"seg": "转", "text": "孤舟蓑笠翁", "rate": 0.58, "pitch": 0.86, "vol": 0.78, "pre": 0.4, "post": 1.2},
            {"seg": "合", "text": "独钓寒江雪", "rate": 0.50, "pitch": 0.78, "vol": 0.74, "pre": 0.7, "post": 1.8},
        ],
    },
    "bd": {  # 早发白帝城 · 李白（七言，上平十五删平韵）
        "title": "早发白帝城 · 李白",
        "lines": [
            {"seg": "起", "text": "朝辞白帝彩云间", "rate": 0.80, "pitch": 1.02, "vol": 0.86, "pre": 0.3, "post": 0.8},
            {"seg": "承", "text": "千里江陵一日还", "rate": 0.82, "pitch": 1.04, "vol": 0.86, "pre": 0.4, "post": 0.9},
            {"seg": "转", "text": "两岸猿声啼不住", "rate": 0.84, "pitch": 1.06, "vol": 0.90, "pre": 0.3, "post": 0.9},
            {"seg": "合", "text": "轻舟已过万重山", "rate": 0.86, "pitch": 1.06, "vol": 0.90, "pre": 0.4, "post": 1.4},
        ],
    },
}

SR = 24000  # edge-tts 默认 24k；输出统一此采样率

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = "ffmpeg"

# ---------------------------------------------------------------- 工具
def sh(cmd):
    return subprocess.run(cmd, capture_output=True, check=True)

def decode_to_wav(mp3_path, wav_path):
    sh([FFMPEG_BIN, "-y", "-loglevel", "error", "-i", mp3_path, "-ar", str(SR), "-ac", "1", wav_path])

def encode_mp3(wav_path, mp3_path):
    sh([FFMPEG_BIN, "-y", "-loglevel", "error", "-i", wav_path, "-b:a", "192k", mp3_path])

def silent_wav(seconds):
    import numpy as np
    import soundfile as sf
    n = int(SR * seconds)
    data = np.zeros(n, dtype=np.float32)
    tmp = os.path.join(ROOT, "dist", "audio", "voice", "_sil.wav")
    sf.write(tmp, data, SR)
    return tmp

# ---------------------------------------------------------------- edge 后端
def edge_tts_params(line, rate_scale=1.0):
    """SpeechSynthesisUtterance 风格参数 → edge-tts 字符串参数。

    rate_scale 缩放「减速量」：1.0=原样；0.5=减速量减半（更快）；0=恢复常速。
    """
    rate_val = 1.0 - (1.0 - line["rate"]) * rate_scale
    rate = f"{(rate_val - 1.0) * 100:+.0f}%"
    volume = f"{(line['vol'] - 1.0) * 100:+.0f}%"
    pitch_hz = round((line["pitch"] - 1.0) * 80.0)  # 1.0→0Hz, 0.85→-12Hz
    pitch = f"{pitch_hz:+d}Hz"
    return rate, pitch, volume

async def synth_edge_line(voice, line, out_mp3, rate_scale=1.0):
    import edge_tts
    rate, pitch, volume = edge_tts_params(line, rate_scale)
    communicate = edge_tts.Communicate(line["text"], voice, rate=rate, pitch=pitch, volume=volume)
    await communicate.save(out_mp3)
    return out_mp3

def render_edge(voice, outdir, poem_key, poem, rate_scale=1.0, suffix=""):
    import numpy as np
    import soundfile as sf
    os.makedirs(outdir, exist_ok=True)
    lines = poem["lines"]
    parts = []
    for line in lines:
        mp3 = os.path.join(outdir, "_line.mp3")
        asyncio.run(synth_edge_line(voice, line, mp3, rate_scale))
        wav = os.path.join(outdir, "_line.wav")
        decode_to_wav(mp3, wav)
        data, _ = sf.read(wav, dtype="float32")
        parts.append((line, data))
        os.remove(mp3)
        os.remove(wav)
    # 拼接（前停 + 句 + 后停）
    out_wav = os.path.join(outdir, f"{poem_key}_edge_{voice}_quatrain{suffix}.wav")
    chunk = []
    for line, data in parts:
        if line["pre"] > 0:
            chunk.append(np.zeros(int(SR * line["pre"]), dtype=np.float32))
        chunk.append(data)
        if line["post"] > 0:
            chunk.append(np.zeros(int(SR * line["post"]), dtype=np.float32))
    full = np.concatenate(chunk)
    sf.write(out_wav, full, SR)
    out_mp3 = out_wav.replace(".wav", ".mp3")
    encode_mp3(out_wav, out_mp3)
    # 元数据
    meta = {
        "poem": poem["title"],
        "poem_key": poem_key,
        "backend": "edge",
        "voice": voice,
        "sr": SR,
        "duration": float(len(full)) / SR,
        "lines": [
            {"seg": l["seg"], "text": l["text"], "rate": l["rate"], "pitch": l["pitch"],
             "vol": l["vol"], "pre": l["pre"], "post": l["post"]}
            for l in lines
        ],
    }
    with open(out_wav.replace(".wav", ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return out_wav, out_mp3

# ---------------------------------------------------------------- azure 后端
def render_azure(voice, outdir, key, region, poem_key, poem):
    """Azure Speech：逐句 SSML（express-as 情感 + 句级停顿）。voice: poet|lonely|xi。"""
    import azure.cognitiveservices.speech as speechsdk
    os.makedirs(outdir, exist_ok=True)
    style_map = {"poet": "poetry-reading", "lonely": "lonely", "xi": "sad"}
    voice_name = {"poet": "zh-CN-Yunyi:DragonHDFlashLatestNeural",
                  "lonely": "zh-CN-Yunhan:DragonHDFlashLatestNeural",
                  "xi": "zh-CN-YunxiNeural"}[voice]
    style = style_map[voice]
    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)
    synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    mp3s = []
    for line in poem["lines"]:
        rate = f"{line['rate'] * 100:.0f}%"
        break_ms = int(line["post"] * 1000)
        pre_ms = int(line["pre"] * 1000)
        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'
 xmlns:mstts='https://www.w3.org/2001/mstts'>
<voice name='{voice_name}'><mstts:express-as style='{style}' styledegree='1.2'>
<break time='{pre_ms}ms'/><prosody rate='{rate}'>{line["text"]}</prosody>
<break time='{break_ms}ms'/></mstts:express-as></voice></speak>"""
        out_mp3 = os.path.join(outdir, f"_line_{line['seg']}.mp3")
        result = synth.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"[azure] 第{line['seg']}句失败: {result.reason}")
            continue
        with open(out_mp3, "wb") as f:
            f.write(result.audio_data)
        mp3s.append((line, out_mp3))
    return _concat(mp3s, outdir, f"{poem_key}_azure_{voice}_quatrain")

def _concat(mp3s, outdir, name):
    import numpy as np
    import soundfile as sf
    chunk = []
    for line, mp3 in mp3s:
        wav = os.path.join(outdir, "_c.wav")
        decode_to_wav(mp3, wav)
        data, _ = sf.read(wav, dtype="float32")
        chunk.append(np.zeros(int(SR * line["pre"]), dtype=np.float32))
        chunk.append(data)
        chunk.append(np.zeros(int(SR * line["post"]), dtype=np.float32))
        os.remove(wav)
        os.remove(mp3)
    full = np.concatenate(chunk)
    out_wav = os.path.join(outdir, name + ".wav")
    sf.write(out_wav, full, SR)
    out_mp3 = out_wav.replace(".wav", ".mp3")
    encode_mp3(out_wav, out_mp3)
    return out_wav, out_mp3

# ---------------------------------------------------------------- volc 后端
def render_volc(voice, outdir, access_key, secret_key, app_id):
    """火山引擎豆包语音（大模型语音合成，非流式）。voice: qingcang2。"""
    from volcengine.ApiInfo import ApiInfo
    from volcengine.Credentials import Credentials
    from volcengine.base.Service import Service
    import volcengine
    raise NotImplementedError(
        "[volc] 火山引擎 SDK 调用需实测；请先在本机安装 volcengine-python-sdk，"
        "并在脚本中按 https://docs.volcengine.com/docs/6561/1524137 补全请求体。")

# ---------------------------------------------------------------- aliyun 后端
def render_aliyun(voice, outdir, api_key):
    """阿里云 CosyVoice（dashscope 非实时合成）。voice: longanyang 等。"""
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat
    raise NotImplementedError(
        "[aliyun] CosyVoice 调用需实测；请先 pip install dashscope，"
        "并按 https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide 补全。")

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="绝句配音出样（多首）")
    ap.add_argument("--backend", choices=["edge", "azure", "volc", "aliyun"], required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--poem", default="jys", choices=sorted(POEMS.keys()),
                    help="诗目：jys 静夜思 / jx 江雪 / bd 早发白帝城")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "dist", "audio", "voice"))
    ap.add_argument("--rate-scale", type=float, default=1.0,
                    help="缩放减速量：1.0=原样；0.5=减速量减半（更快）；0=常速（仅 edge 后端）")
    ap.add_argument("--suffix", default="", help="输出文件名后缀（仅 edge 后端），如 _fast")
    args = ap.parse_args()

    env = os.environ
    outdir = args.outdir
    poem = POEMS[args.poem]
    os.makedirs(outdir, exist_ok=True)
    print(f"[{args.backend}] poem={args.poem} voice={args.voice} -> {outdir}")

    if args.backend == "edge":
        wav, mp3 = render_edge(args.voice, outdir, args.poem, poem,
                               rate_scale=args.rate_scale, suffix=args.suffix)
        print(f"OK: {mp3}  ({os.path.getsize(mp3)//1024} KB)")

    elif args.backend == "azure":
        key, region = env.get("AZURE_SPEECH_KEY"), env.get("AZURE_SPEECH_REGION")
        if not key or not region:
            sys.exit("[azure] 请设置环境变量 AZURE_SPEECH_KEY 与 AZURE_SPEECH_REGION")
        import azure.cognitiveservices.speech  # noqa: F401
        wav, mp3 = render_azure(args.voice, outdir, key, region, args.poem, poem)
        print(f"OK: {mp3}  ({os.path.getsize(mp3)//1024} KB)")

    elif args.backend == "volc":
        ak = env.get("VOLC_ACCESS_KEY"); sk = env.get("VOLC_SECRET_KEY"); aid = env.get("VOLC_APP_ID")
        if not ak or not sk or not aid:
            sys.exit("[volc] 请设置 VOLC_ACCESS_KEY / VOLC_SECRET_KEY / VOLC_APP_ID")
        render_volc(args.voice, outdir, ak, sk, aid)

    elif args.backend == "aliyun":
        key = env.get("DASHSCOPE_API_KEY")
        if not key:
            sys.exit("[aliyun] 请设置 DASHSCOPE_API_KEY")
        render_aliyun(args.voice, outdir, key)

if __name__ == "__main__":
    main()
