# -*- coding: utf-8 -*-
"""
韵律后处理：将平读 TTS 样本改写为吟诵腔（多首绝句）。

吟诵规则编码（传统吟诵通则）：
  - 平长仄短   ：平声字时长约 1.35x，仄声字约 0.85x
  - 入短韵长   ：入声字 0.65x 短促；平声韵脚字 1.65x 拖长
  - 句调曲线   ：起（中平微降）、承（低抑下降）、转（上扬）、合（深降渐弱）
  - 2-3 顿     ：句内顿感由时长差自然形成，不另插静音

实现：pyworld 分析 -> 逐音节时长伸缩（时间轴重映射）+ 句级 F0 改写 -> 合成。

诗目（--poem）：jys 静夜思 / jx 江雪 / bd 早发白帝城
"""
import argparse
import json
import os
import sys

import numpy as np
import pyworld as pw
import soundfile as sf


# ---------------- 逐首诗的格律表 ----------------
# 音节三元组 (字, 平仄, 角色)
#   tone 平仄 : level=平声, oblique=仄声, entering=入声(仄)
#   role 角色 : level=平声, oblique=仄声, entering=入声, rhyme=平声韵脚（拖长）
POEMS = {
    "jys": {
        "title": "静夜思 · 李白",
        "n_syl": 5,
        "syllables": [
            ("床", "level", "level"), ("前", "level", "level"), ("明", "level", "level"),
            ("月", "entering", "entering"), ("光", "rhyme", "rhyme"),
            ("疑", "level", "level"), ("是", "oblique", "oblique"), ("地", "oblique", "oblique"),
            ("上", "oblique", "oblique"), ("霜", "rhyme", "rhyme"),
            ("举", "oblique", "oblique"), ("头", "level", "level"), ("望", "oblique", "oblique"),
            ("明", "level", "level"), ("月", "entering", "entering"),
            ("低", "level", "level"), ("头", "level", "level"), ("思", "level", "level"),
            ("故", "oblique", "oblique"), ("乡", "rhyme", "rhyme"),
        ],
        # 起（中平微降）、承（低抑下降）、转（上扬）、合（深降渐弱）
        "lines": [
            {"seg": "起", "f0_mul": 1.00, "f0_slope": -0.8, "amp": 1.00},
            {"seg": "承", "f0_mul": 0.94, "f0_slope": -1.6, "amp": 0.92},
            {"seg": "转", "f0_mul": 1.06, "f0_slope": +0.6, "amp": 1.04},
            {"seg": "合", "f0_mul": 0.90, "f0_slope": -1.2, "amp": 0.95},
        ],
        "tail_fade": [0.0, 0.15, 0.0, 0.55],
        "pause_base": [1.40, 1.05, 1.70],
        "pause_min": 0.70, "pause_max": 2.40,
        "lead_pause": 0.25, "tail_pause": 1.60,
        "emotion": "sad_longing",
    },
    "jx": {  # 江雪 · 柳宗元（五言，入声屑韵，折腰体：第 3 句不押韵）
        "title": "江雪 · 柳宗元",
        "n_syl": 5,
        "syllables": [
            ("千", "level", "level"), ("山", "level", "level"), ("鸟", "oblique", "oblique"),
            ("飞", "level", "level"), ("绝", "entering", "entering"),
            ("万", "oblique", "oblique"), ("径", "oblique", "oblique"), ("人", "level", "level"),
            ("踪", "level", "level"), ("灭", "entering", "entering"),
            ("孤", "level", "level"), ("舟", "level", "level"), ("蓑", "level", "level"),
            ("笠", "entering", "entering"), ("翁", "level", "level"),
            ("独", "entering", "entering"), ("钓", "oblique", "oblique"), ("寒", "level", "level"),
            ("江", "level", "level"), ("雪", "entering", "entering"),
        ],
        # 清冷孤寂：整体低抑，转句只略提（孤舟蓑笠翁），合句深收
        "lines": [
            {"seg": "起", "f0_mul": 0.99, "f0_slope": -0.6, "amp": 0.98},
            {"seg": "承", "f0_mul": 0.95, "f0_slope": -1.4, "amp": 0.92},
            {"seg": "转", "f0_mul": 0.97, "f0_slope": -0.2, "amp": 0.97},
            {"seg": "合", "f0_mul": 0.89, "f0_slope": -1.3, "amp": 0.90},
        ],
        "tail_fade": [0.0, 0.15, 0.0, 0.55],
        "pause_base": [1.30, 1.20, 1.10],
        "pause_min": 0.70, "pause_max": 2.40,
        "lead_pause": 0.35, "tail_pause": 1.80,
        "emotion": "cold_lonely",
    },
    "bd": {  # 早发白帝城 · 李白（七言，上平十五删平韵）
        "title": "早发白帝城 · 李白",
        "n_syl": 7,
        "syllables": [
            ("朝", "level", "level"), ("辞", "level", "level"), ("白", "entering", "entering"),
            ("帝", "oblique", "oblique"), ("彩", "oblique", "oblique"), ("云", "level", "level"),
            ("间", "rhyme", "rhyme"),
            ("千", "level", "level"), ("里", "oblique", "oblique"), ("江", "level", "level"),
            ("陵", "level", "level"), ("一", "entering", "entering"), ("日", "entering", "entering"),
            ("还", "rhyme", "rhyme"),
            ("两", "oblique", "oblique"), ("岸", "oblique", "oblique"), ("猿", "level", "level"),
            ("声", "level", "level"), ("啼", "level", "level"), ("不", "entering", "entering"),
            ("住", "oblique", "oblique"),
            ("轻", "level", "level"), ("舟", "level", "level"), ("已", "oblique", "oblique"),
            ("过", "oblique", "oblique"), ("万", "oblique", "oblique"), ("重", "level", "level"),
            ("山", "rhyme", "rhyme"),
        ],
        # 轻快畅意：整体上行、句幅放开，合句开阔不收
        "lines": [
            {"seg": "起", "f0_mul": 1.02, "f0_slope": +0.2, "amp": 1.00},
            {"seg": "承", "f0_mul": 1.04, "f0_slope": +0.4, "amp": 1.02},
            {"seg": "转", "f0_mul": 1.06, "f0_slope": +0.8, "amp": 1.05},
            {"seg": "合", "f0_mul": 1.08, "f0_slope": +0.5, "amp": 1.06},
        ],
        "tail_fade": [0.0, 0.0, 0.0, 0.12],
        "pause_base": [0.80, 0.75, 0.70],
        "pause_min": 0.55, "pause_max": 1.80,
        "lead_pause": 0.20, "tail_pause": 1.20,
        "emotion": "joyful_swift",
    },
}

DUR_FACTOR = {"level": 1.35, "oblique": 0.85, "entering": 0.65, "rhyme": 1.65}

# 句间衔接（起承转合的结构规则，与情感无关，恒定生效）
JUNCTION_GLIDE_MS = 250.0   # 句首滑音时长：从前句尾音滑入本句目标音高
MAX_JUMP_SEMI = 2.0         # 句间音高跳进上限（半音），超出则压缩

# 句间气口（吸气声）与自适应停顿预算（同属结构规则，与情感无关，恒定生效）
BREATH_MS = 170.0          # 气口时长
BREATH_LEAD_MS = 90.0      # 气口收尾距下一句起音的时间
BREATH_RATIO = 0.30        # 气口峰值 / 相邻句 RMS（0.30 ≈ −10.5dB；相对语音峰值约 −30dB，可闻但不抢）
PAUSE_REF_END_MS = 700.0   # 韵脚时长参考值：短于此则补停顿，长于此则略减
PAUSE_GAIN = 0.6           # 韵脚每短 100ms，补 60ms 停顿

# 情感层预设。依据：情绪语音的声学相关量 —— 语速、音高、音域、句调走向、
# 气声化（高频非周期成分）、句末渐弱。每首诗的默认情感预设见 POEMS[*]["emotion"]。
EMOTION_PRESETS = {
    "sad_longing": {
        "label": "悲伤·思念",
        "dur_scale": 1.11,       # 整体时长倍率（1.11 ≈ 放慢到 0.9 倍语速，含停顿）
        "f0_mul": 0.93,          # 整体降调
        "range_k": 0.72,         # 音域压缩至 72%（悲伤语音的稳定相关量）
        "slope_extra": -0.7,     # 句调再下沉（%/s）
        "vibrato_hz": 5.2,       # 颤音频率（Hz）
        "vibrato_depth": 0.009,  # 颤音深度（±15 音分）
        "breath": 0.55,          # 气声化：把 2-6kHz 非周期成分抬到该下限（源在此带仅 0.42）
        "breath_band": (2000.0, 6000.0),
        "hf_tilt": 0.35,         # 高频谱倾斜（1.5kHz 起线性提升，Nyquist 处 +1.2dB）
        "tail_fade": 0.30,       # 句末渐弱覆盖比例（深度按诗目 tail_fade 分句取值）
    },
    "cold_lonely": {
        "label": "清冷·孤寂",
        "dur_scale": 1.16,       # 更慢，寒意与空阔
        "f0_mul": 0.90,          # 更低
        "range_k": 0.66,         # 音域更窄，情绪内敛
        "slope_extra": -0.8,
        "vibrato_hz": 4.6,
        "vibrato_depth": 0.010,
        "breath": 0.60,          # 气声更重（寒江的水汽与呼吸感）
        "breath_band": (2000.0, 6000.0),
        "hf_tilt": 0.42,
        "tail_fade": 0.30,
    },
    "joyful_swift": {
        "label": "轻快·畅意",
        "dur_scale": 0.94,       # 略快（千里江陵一日还）
        "f0_mul": 1.06,          # 略高
        "range_k": 1.12,         # 音域放开（>1 为展宽）
        "slope_extra": +0.6,     # 句调再上扬
        "vibrato_hz": 6.0,
        "vibrato_depth": 0.008,
        "breath": 0.34,          # 气声很轻（明亮）
        "breath_band": (2000.0, 6000.0),
        "hf_tilt": 0.18,
        "tail_fade": 0.16,
    },
}


def detect_line_segments(env, sr, frame_period):
    """按能量静音切句。返回 [(start_frame, end_frame), ...]，env 为逐帧能量。"""
    hop = int(sr * frame_period / 1000.0)
    n = len(env)
    thr = np.percentile(env, 25) * 0.35
    voiced = env > thr
    segs = []
    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        s = i
        while i < n and voiced[i]:
            i += 1
        e = i
        if e - s > int(0.05 * sr / hop):  # 至少 50ms
            segs.append((s, e))
    return segs


def detect_syllable_onsets(env, sr, frame_period, n_syl):
    """句内音节边界：取能量谷点 + 等分兜底。"""
    hop = int(sr * frame_period / 1000.0)
    s, e = 0, len(env)
    seg_env = env[s:e]
    n = len(seg_env)
    # 等分兜底边界（帧索引）
    uniform = [int(round(k * n / n_syl)) for k in range(n_syl + 1)]
    # 用能量谷修正：在每个等分区间附近找局部最小
    win = max(2, int(0.06 * sr / hop))  # 60ms 搜索窗
    bounds = [uniform[0]]
    for k in range(1, n_syl):
        lo = max(uniform[k] - win, bounds[-1] + 2)
        hi = min(uniform[k] + win, n - 1)
        idx = lo + int(np.argmin(seg_env[lo:hi + 1]))
        bounds.append(idx)
    bounds.append(uniform[-1])
    return bounds


def build_warp_stretch(spans, roles, n_frames, frame_period, dur_scale, ratio_gain,
                       match_duration=False, smooth_ms=45.0):
    """连续时间规整（取代逐音节阶跃伸缩）。

    两步：
      1) 理想伸缩 —— 逐音节分段常数（平长仄短倍率），静音段 1:1；
      2) 高斯平滑 —— 沿时间做凸平滑，把音节边界处的瞬时跳变摊开到 ~±3σ。
    凸平滑不会越界（结果始终落在理想值的 [min,max] 内），故不会像单调三次插值那样
    在短音节上过冲（实测 PCHIP 会把 0.72 的入声瞬时压到 0.27）。平滑后再整体归一，
    使总时长精确等于「逐音节阶跃（旧行为）」，动画时序无需重排。

    ratio_gain 收窄倍率差：factor' = 1 + ratio_gain × (factor − 1)。
    match_duration=True 时按旧行为总时长归一（否则平滑本身会轻微改变总长）。
    """
    def fac_sm(role):
        return 1.0 + ratio_gain * (DUR_FACTOR[role] - 1.0)

    ideal = np.ones(n_frames)
    for (fs, fe), role in zip(spans, roles):
        ideal[fs:fe] = fac_sm(role)
    ideal = ideal * dur_scale

    if smooth_ms > 0 and n_frames > 3:
        sigma = max(0.5, smooth_ms / frame_period)
        rad = max(1, int(3.0 * sigma))
        k = np.exp(-0.5 * (np.arange(-rad, rad + 1) / sigma) ** 2)
        k /= k.sum()
        pad = np.pad(ideal, rad, mode="edge")
        ideal = np.convolve(pad, k, mode="same")[rad:rad + n_frames]

    if match_duration:
        step = np.ones(n_frames)
        for (fs, fe), role in zip(spans, roles):
            step[fs:fe] = DUR_FACTOR[role]
        step = step * dur_scale
        cur = float(ideal.sum())
        if cur > 0:
            ideal = ideal * (float(step.sum()) / cur)
    return np.clip(ideal, 0.2, 4.0)


def make_breath(sr, dur_ms, seed=0):
    """合成一段吸气噪声：400–3000Hz 带通，渐强后速收（吸气在起音处被掩蔽）。峰值归一到 1。"""
    n = max(16, int(sr * dur_ms / 1000.0))
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    k_lo = max(1, int(sr / 3000.0))
    x = np.convolve(x, np.ones(k_lo) / k_lo, mode="same")       # 低通 ~3kHz
    k_hi = max(1, int(sr / 400.0))
    x = x - np.convolve(x, np.ones(k_hi) / k_hi, mode="same")   # 高通 ~400Hz
    m = float(np.max(np.abs(x)))
    if m > 0:
        x = x / m
    env = np.power(np.linspace(0.0, 1.0, n), 0.8)
    cut = max(1, int(0.04 * n))
    env[-cut:] *= np.linspace(1.0, 0.0, cut)
    return x * env


def rebuild_with_pauses(y, seg_ranges, syl_meta, sr, frame_period, preset, poem):
    """按「句尾韵脚时长」重排句间停顿，并在气口处插入吸气声。

    返回 (新波形, 各气口实际停顿秒数, 各行时序 [(起, 止), ...])。停顿越短补得越多——韵脚
    短促（入声）需更多留白收束；韵脚拖长（平声）本身已留足余地。行时序是最终输出时间轴上的
    实测值，供声画同步（动画按配音重定时）直接取用。
    """
    n_lines = len(poem["lines"])
    line_lens = [poem["n_syl"]] * n_lines
    total_syl = sum(line_lens)
    if len(seg_ranges) != n_lines or len(syl_meta) != total_syl:
        return y, [], []

    hop = int(sr * frame_period / 1000.0)
    dur_scale = preset["dur_scale"] if preset else 1.0

    # 逐句韵脚时长（ms）：旧帧数 × 字调伸缩 × 整体倍率
    end_ms = []
    idx = 0
    for li in range(n_lines):
        m = syl_meta[idx + line_lens[li] - 1]
        end_ms.append(m["frames"] * DUR_FACTOR[m["role"]] * dur_scale * frame_period)
        idx += line_lens[li]

    margin = int(0.08 * sr)
    blocks = []
    for a, b in seg_ranges:
        blocks.append(y[max(0, a * hop - margin):min(len(y), b * hop + margin)])

    rms = float(np.sqrt(np.mean(np.concatenate(blocks) ** 2)))
    breath_amp = BREATH_RATIO * rms

    if os.environ.get("VPP_DEBUG"):
        blk_total = sum(len(b) for b in blocks)
        print(f"[dbg] synth_len={len(y)} ({len(y)/sr:.3f}s)  "
              f"segs={[(int(a), int(b)) for a, b in seg_ranges]}  "
              f"blocks_total={blk_total} ({blk_total/sr:.3f}s)  "
              f"coverage={blk_total/max(len(y),1):.3f}  rms={rms:.5f} breath_amp={breath_amp:.5f}")

    pauses = []
    line_times = []
    parts = [np.zeros(int(poem["lead_pause"] * sr))]
    cur = len(parts[0]) / sr
    for li, blk in enumerate(blocks):
        parts.append(blk)
        line_times.append((round(cur, 3), round(cur + len(blk) / sr, 3)))
        cur += len(blk) / sr
        if li < len(blocks) - 1:
            p = poem["pause_base"][li] + PAUSE_GAIN * (PAUSE_REF_END_MS - end_ms[li]) / 1000.0
            p = float(np.clip(p, poem["pause_min"], poem["pause_max"]))
            pauses.append(round(p, 3))
            gap = np.zeros(int(p * sr))
            br = make_breath(sr, BREATH_MS, seed=li) * breath_amp
            end = len(gap) - int(BREATH_LEAD_MS / 1000.0 * sr)
            start = max(0, end - len(br))
            end = min(len(gap), start + len(br))
            if end > start:
                gap[start:end] += br[:end - start]
            if os.environ.get("VPP_DEBUG"):
                print(f"[dbg] gap{li} p={p:.3f}s gap_len={len(gap)} breath_len={len(br)} "
                      f"raw_peak={np.max(np.abs(make_breath(sr, BREATH_MS, seed=li))):.4f} "
                      f"amp={breath_amp:.6f} placed_peak={np.max(np.abs(gap)):.6f}")
            parts.append(gap)
            cur += p
        else:
            parts.append(np.zeros(int(poem["tail_pause"] * sr)))
            cur += poem["tail_pause"]
    return np.concatenate(parts), pauses, line_times


def detect_output_lines(sp, frame_period, n_expect=4):
    """在重映射后的时间轴上直接切句：谱能量平滑 + 自适应阈值 + 合并短静音。

    比「输入帧号线性/累积映射」稳健：后者易把尾部静音或杂散浊帧算进句尾。
    """
    e = np.log(sp.sum(axis=1) + 1e-9)
    k = max(1, int(40.0 / frame_period))
    sm = np.convolve(e, np.ones(k) / k, mode="same")
    floor = np.percentile(sm, 10)
    peak = np.percentile(sm, 99)
    thr = floor + 0.15 * (peak - floor)
    voiced = sm > thr

    runs = []
    i, n = 0, len(sm)
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        s = i
        while i < n and voiced[i]:
            i += 1
        runs.append([s, i])

    min_gap = int(250.0 / frame_period)
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    min_len = int(400.0 / frame_period)
    return [(a, b) for a, b in merged if b - a >= min_len]


def stretch_f0_sp_ap(f0, sp, ap, stretch, frame_period):
    """按逐帧伸缩因子做时间轴重映射（基于累积时间）。"""
    n = len(f0)
    src_t = np.arange(n) * frame_period
    cum = np.cumsum(stretch) * frame_period  # 目标累计时间（各帧结束时刻，长度 n）
    total = cum[-1]
    n_tgt = max(2, int(total / frame_period) + 1)
    tgt_t = np.arange(n_tgt) * frame_period
    src_pos = np.interp(tgt_t, cum, src_t)
    new_f0 = np.interp(src_pos, src_t, f0)
    new_sp = np.column_stack([np.interp(src_pos, src_t, sp[:, d]) for d in range(sp.shape[1])])
    new_ap = np.column_stack([np.interp(src_pos, src_t, ap[:, d]) for d in range(ap.shape[1])])
    return new_f0, new_sp, new_ap, tgt_t


def apply_f0_line(f0, t, f0_mul, f0_slope):
    """句级 F0 改写：整体倍乘 + 斜率（%/s，负=下降）。"""
    if len(f0) == 0:
        return f0
    voiced = f0 > 0
    base = np.median(f0[voiced]) if voiced.any() else 150.0
    dur_s = t[-1] / 1000.0
    slope_factor = 1.0 + (f0_slope / 100.0) * dur_s / 2.0  # 中心点斜率修正
    nf0 = f0.copy()
    for i in range(len(nf0)):
        if nf0[i] > 0:
            rel = t[i] / 1000.0 / dur_s if dur_s > 0 else 0.5
            nf0[i] = nf0[i] * f0_mul * (1.0 + (f0_slope / 100.0) * (rel - 0.5))
    return nf0


def apply_amp_line(env, line_amp, seg, sr, frame_period):
    """句级响度改写（作用于幅度包络）。"""
    return env * line_amp


def apply_emotion(f0, sp, ap, t, preset, sr):
    """情感层：音域压缩 + 整体降调 + 颤音 + 气声化（非周期成分 + 高频谱倾斜）。"""
    nf0 = f0.copy()
    voiced = nf0 > 0
    if voiced.any():
        med = float(np.median(nf0[voiced]))
        # 以中位数为轴压缩/展宽音域，再整体移调
        nf0[voiced] = med * (1.0 + preset["range_k"] * (nf0[voiced] / med - 1.0)) * preset["f0_mul"]
        # 颤音：正弦调制 F0
        tsec = t / 1000.0
        vib = 1.0 + preset["vibrato_depth"] * np.sin(2.0 * np.pi * preset["vibrato_hz"] * tsec)
        nf0[voiced] = nf0[voiced] * vib[voiced]
    # 气声化：1.5kHz 起线性提升高频能量 + 抬高 2-6kHz 非周期成分下限
    nb = sp.shape[1]
    freqs = np.linspace(0.0, sr / 2.0, nb)
    knee = 1500.0
    w = np.clip((freqs - knee) / max(sr / 2.0 - knee, 1.0), 0.0, 1.0)
    nsp = sp * (1.0 + preset["hf_tilt"] * w)[None, :]
    lo, hi = preset["breath_band"]
    ramp = max((hi - lo) * 0.25, 1.0)
    wb = np.clip((freqs - lo) / ramp, 0.0, 1.0) * np.clip((hi - freqs) / ramp, 0.0, 1.0)
    nap = np.maximum(ap, preset["breath"] * wb[None, :])
    return nf0, nsp, nap


def apply_tail_fade(sp, f0, seg_ranges, fade_ratio, fade_amts):
    """句末渐弱：深度按句取值（0 = 不渐弱，保留起承转的推进感）。

    只在句内「有声帧」上做渐弱——估计区间尾部常含静音，直接按帧长计算会落空。
    """
    nsp = sp.copy()
    for (a, b), amt in zip(seg_ranges, fade_amts):
        if amt <= 0:
            continue
        idx = a + np.flatnonzero(f0[a:b] > 0)
        if len(idx) < 4:
            continue
        fl = max(1, int(len(idx) * fade_ratio))
        ramp = np.linspace(1.0, 1.0 - amt, fl)
        nsp[idx[-fl:]] *= ramp[:, None]
    return nsp


def line_end_log2(f0, a, b, tail_ms=120.0, frame_period=5.0, tol_semi=7.0):
    """句尾有声段的对数音高中位（作为下一句滑音的锚点）。

    先剔除倍频/杂散帧（偏离句内中位音高 > tol_semi 半音），再取末尾 120ms 中位。
    """
    idx = np.flatnonzero(f0[a:b] > 0)
    if len(idx) == 0:
        return None
    vals = f0[a + idx]
    med = float(np.median(vals))
    keep = np.abs(np.log2(vals / med)) <= tol_semi / 12.0
    vals, idx = vals[keep], idx[keep]
    if len(vals) == 0:
        return None
    k = max(1, int(tail_ms / frame_period))
    return float(np.median(np.log2(vals[-k:])))


def apply_junction_glide(f0, a, b, prev_end_log2, glide_frames, max_jump_semi):
    """句首滑音衔接：从前句尾音滑入本句目标音高，跳进限制在 ±max_jump_semi 半音内。"""
    if prev_end_log2 is None or a >= b:
        return
    seg = f0[a:b]
    idx = np.flatnonzero(seg > 0)
    if len(idx) == 0:
        return
    start = int(idx[0])
    head = idx[:max(1, int(120.0 / 5.0))]
    t0 = float(np.median(np.log2(seg[head])))
    lim = max_jump_semi / 12.0
    anchor = float(np.clip(prev_end_log2, t0 - lim, t0 + lim))
    G = min(glide_frames, len(seg) - start)
    if G <= 0:
        return
    adjust = np.linspace(1.0, 0.0, G) * (anchor - t0)
    for k in range(G):
        j = start + k
        if seg[j] > 0:
            seg[j] *= 2.0 ** adjust[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-wav", required=True)
    ap.add_argument("--out-wav", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--poem", default="jys", choices=sorted(POEMS.keys()),
                    help="诗目：jys 静夜思 / jx 江雪 / bd 早发白帝城")
    ap.add_argument("--emotion", default=None, choices=sorted(EMOTION_PRESETS.keys()),
                    help="叠加情感层预设（不指定则仅吟诵韵律）")
    ap.add_argument("--warp", default="smooth", choices=["smooth", "step"],
                    help="时间规整：smooth=连续（默认，消除逐音节顿挫）/ step=逐音节分段常数（旧行为）")
    ap.add_argument("--ratio-gain", type=float, default=0.7,
                    help="平长仄短倍率差的收敛系数：factor'=1+g(factor-1)，g<1 收窄对比（默认 0.7）")
    ap.add_argument("--match-duration", action="store_true",
                    help="音节总时长对齐「逐音节阶跃」旧行为，使总时长不变（动画时序无需重排）")
    ap.add_argument("--warp-smooth-ms", type=float, default=45.0,
                    help="smooth 模式的高斯平滑 σ（ms）：越大过渡越缓，越小越接近阶跃（默认 45）")
    args = ap.parse_args()

    poem = POEMS[args.poem]
    LINES = poem["lines"]
    SYLLABLES = poem["syllables"]
    n_syl = poem["n_syl"]
    n_lines = len(LINES)
    preset = EMOTION_PRESETS[args.emotion] if args.emotion else None

    x, sr = sf.read(args.in_wav, dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    frame_period = 5.0
    hop = int(sr * frame_period / 1000.0)

    # WORLD 分析
    f0, t = pw.harvest(x, sr, f0_floor=71.0, f0_ceil=600.0, frame_period=frame_period)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)

    # 逐帧能量
    n_frames = len(f0)
    env = np.zeros(n_frames)
    for i in range(n_frames):
        s = i * hop
        e = min(s + hop, len(x))
        if e > s:
            env[i] = np.sqrt(np.mean(x[s:e] ** 2))

    # 1) 切句（静音阈值）；2) 句内切音节；3) 逐音节伸缩
    segs = detect_line_segments(env, sr, frame_period)
    if len(segs) != n_lines:
        print(f"[warn] 检测到 {len(segs)} 句（期望 {n_lines}），按整体 {n_lines} 等分兜底", file=sys.stderr)
        n = n_frames
        segs = [(int(round(k * n / n_lines)), int(round((k + 1) * n / n_lines))) for k in range(n_lines)]
    # 过滤过短片段（边缘残留）
    segs = [s for s in segs if s[1] - s[0] > int(0.15 * sr / hop)]

    dur_scale = preset["dur_scale"] if preset else 1.0
    spans, roles = [], []
    syl_meta = []
    offset = 0  # 已处理音节游标
    for li, ((s0, e0), line_cfg) in enumerate(zip(segs, LINES)):
        bounds = detect_syllable_onsets(env[s0:e0], sr, frame_period, n_syl)
        for k in range(n_syl):
            fs = s0 + bounds[k]
            fe = max(s0 + bounds[k + 1], fs + 1)
            ch, tone, role = SYLLABLES[offset + k]
            spans.append((fs, fe))
            roles.append(role)
            syl_meta.append({
                "char": ch, "tone": tone, "role": role,
                "line": li + 1, "pos": k + 1,
                "frames": int(fe - fs),
            })
        offset += n_syl

    if args.warp == "smooth":
        # 连续时间规整：dur_scale 与倍率收敛已在内部生效
        stretch = build_warp_stretch(spans, roles, n_frames, frame_period,
                                     dur_scale, args.ratio_gain, args.match_duration,
                                     args.warp_smooth_ms)
    else:
        stretch = np.ones(n_frames)
        for (fs, fe), role in zip(spans, roles):
            stretch[fs:fe] = DUR_FACTOR[role]
        if preset:
            stretch = stretch * preset["dur_scale"]

    # 客观指标：把「顿挫」量化——逐帧跳变 + 相邻音节速度比
    d = np.abs(np.diff(stretch)) if n_frames > 1 else np.zeros(1)
    syl_means = [float(stretch[fs:fe].mean()) if fe > fs else 1.0 for (fs, fe) in spans]
    ratios = []
    for k in range(1, len(syl_means)):
        if syl_meta[k]["line"] == syl_meta[k - 1]["line"] and syl_means[k - 1] > 0 and syl_means[k] > 0:
            ratios.append(max(syl_means[k] / syl_means[k - 1], syl_means[k - 1] / syl_means[k]))
    warp_stats = {
        "逐帧最大跳变": round(float(d.max()), 4),
        "逐帧平均跳变": round(float(d.mean()), 4),
        "音节间最大速度比": round(float(max(ratios)) if ratios else 1.0, 3),
        "音节间平均速度比": round(float(np.mean(ratios)) if ratios else 1.0, 3),
    }
    if os.environ.get("VPP_DEBUG"):
        print(f"[dbg] warp={args.warp} ratio_gain={args.ratio_gain} "
              f"stretch[{stretch.min():.3f},{stretch.max():.3f}] "
              f"max|Δframe|={d.max():.4f} mean|Δframe|={d.mean():.4f} "
              f"音节间最大速度比={warp_stats['音节间最大速度比']}")
    if os.environ.get("VPP_DEBUG") == "2":
        qs = np.percentile(stretch, [0, 1, 5, 25, 50, 75, 95, 99, 100])
        print("[dbg2] stretch 分位 p0/1/5/25/50/75/95/99/100 = "
              + " ".join(f"{v:.3f}" for v in qs))
        # 逐音节目标时长（源帧 × 该音节区间内的平均伸缩）
        rows = []
        for (fs, fe), role in zip(spans, roles):
            seg = stretch[fs:fe]
            rows.append((role, (fe - fs) * frame_period, float(seg.mean()) if len(seg) else 0.0))
        print("[dbg2] 逐音节 角色/源时长ms/平均伸缩: "
              + " ".join(f"{r}:{d:.0f}ms×{s:.2f}" for r, d, s in rows))

    # 时间轴重映射
    new_f0, new_sp, new_ap, new_t = stretch_f0_sp_ap(f0, sp, ap, stretch, frame_period)

    # 句级 F0 改写（在重映射后按新时间轴定位句子）
    # 优先在新时间轴上直接检测 n_lines 句；失败再退回「旧帧 i -> 新时刻 cum[i]」映射
    cum = np.cumsum(stretch) * frame_period
    det = detect_output_lines(new_sp, frame_period)
    if len(det) == n_lines:
        new_segs = det
    else:
        print(f"[warn] 输出端检测到 {len(det)} 句（期望 {n_lines}），退回映射估计", file=sys.stderr)
        new_segs = []
        for (s0, e0) in segs:
            t_start = float(cum[s0]) if s0 > 0 else 0.0
            t_end = float(cum[e0 - 1])
            a = max(0, int(t_start / frame_period))
            b = min(len(new_f0), max(a + 1, int(t_end / frame_period)))
            new_segs.append((a, b))

    slope_extra = preset["slope_extra"] if preset else 0.0
    for li, (a, b) in enumerate(new_segs):
        if b > a:
            new_f0[a:b] = apply_f0_line(
                new_f0[a:b], new_t[a:b] - new_t[a],
                LINES[li]["f0_mul"], LINES[li]["f0_slope"] + slope_extra)

    # 句间滑音衔接：从前句尾音滑入本句目标音高（跳进限制 ±MAX_JUMP_SEMI 半音）
    if len(new_segs) >= 2:
        glide_frames = max(1, int(JUNCTION_GLIDE_MS / frame_period))
        for li in range(1, len(new_segs)):
            pa, pb = new_segs[li - 1]
            ca, cb = new_segs[li]
            prev_end = line_end_log2(new_f0, pa, pb, frame_period=frame_period)
            apply_junction_glide(new_f0, ca, cb, prev_end, glide_frames, MAX_JUMP_SEMI)

    # 情感层（可选）：音域压缩 + 移调 + 颤音 + 气声 + 句末渐弱
    if preset:
        new_f0, new_sp, new_ap = apply_emotion(new_f0, new_sp, new_ap, new_t, preset, sr)
        new_sp = apply_tail_fade(new_sp, new_f0, new_segs, preset["tail_fade"], poem["tail_fade"])

    # 合成 + 归一化（先归一化，气口才能按真实语音电平定标）
    y = pw.synthesize(new_f0, new_sp, new_ap, sr, frame_period)
    y = np.nan_to_num(y)
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.95

    # 句间气口 + 自适应停顿预算（结构规则，恒定生效）
    y, pauses, line_times = rebuild_with_pauses(y, new_segs, syl_meta, sr, frame_period, preset, poem)
    sf.write(args.out_wav, y, sr)

    # 行文本（自音节表重建，供核对）
    line_texts, off = [], 0
    for _ in range(n_lines):
        line_texts.append("".join(s[0] for s in SYLLABLES[off:off + n_syl]))
        off += n_syl

    # 元数据
    meta = {
        "poem": poem["title"],
        "poem_key": args.poem,
        "backend": "edge+prosody" + ("+emotion" if preset else ""),
        "voice": os.path.basename(args.in_wav),
        "sr": sr,
        "duration": round(len(y) / sr, 3),
        "emotion": preset["label"] if preset else None,
        "line_texts": line_texts,
        "rules": {
            "平长仄短": DUR_FACTOR,
            "时间规整": {"方式": args.warp,
                         "倍率收敛": (args.ratio_gain if args.warp == "smooth" else 1.0),
                         "平滑σ_ms": (args.warp_smooth_ms if args.warp == "smooth" else None),
                         "对齐旧时长": bool(args.warp == "smooth" and args.match_duration),
                         "客观指标": warp_stats},
            "句调": [{"seg": l["seg"], "f0_mul": l["f0_mul"], "f0_slope_pct_per_s": l["f0_slope"]} for l in LINES],
            "句间衔接": {
                "句末渐弱深度": poem["tail_fade"],
                "句首滑音_ms": JUNCTION_GLIDE_MS,
                "跳进上限_半音": MAX_JUMP_SEMI,
                "气口_ms": BREATH_MS,
                "实际停顿_秒": pauses,
                "行时序_秒": line_times,
            },
        },
        "syllables": syl_meta,
    }
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"OK  {args.out_wav}")
    print(f"    [{args.poem}] 时长 {meta['duration']}s  音节数 {len(syl_meta)}  行时序 {line_times}")


if __name__ == "__main__":
    main()
