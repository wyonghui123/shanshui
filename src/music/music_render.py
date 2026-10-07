#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
D3 音乐层渲染器（示范 · 江雪）
读 data/source/d3/<pid>_music.json（声法表，单一真源）→ 渲染 dist/audio/music/<pid>.wav

古琴音源用 sampler.Bank 播放 GuqinSonGest 真实干声（CC BY 4.0）；
笛用 sampler.DiziBank 播放 Hypnotriod 笛实录（Freesound pack 21613, CC0 1.0）；
箫仍为合成（未找到可再分发的免费箫实录）。声法表与装配逻辑不动，只换音源
（见 sampler.py 顶部说明）。

设计对齐 docs/research/music_expression_elements.html §2/§3/§4：
  · 调式（轴A）羽调式 / 正调 → 五声音阶取音
  · 音色（轴B）古琴（散音 / 泛音 / 按音）+ 箫偶入
  · 手法（轴C）吟 / 猱 / 绰 / 注（走手音）
  · 板式（轴D）散板：入声处顿
  · 结构（轴E）散起 → 入调 → 入慢 → 复起 → 尾声
  · 静默（轴F）不设长静默：音随下一次起音收（连贯叠音织体），行间气口由余响贯入；
    仅入声「顿」保留短促释放（音色手法，非留白）

用法：
  python src/music/music_render.py                 # 渲染 jx
  python src/music/music_render.py --pid jx --check # 渲染并断言
  python src/music/music_render.py --selftest      # 负向扰动测试（证明断言能失败）
"""
import argparse, json, math, sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter, fftconvolve

import sampler

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- 基础

def db(x, floor=-120.0):
    return max(20.0 * math.log10(max(abs(x), 1e-12)), floor)


def semitone(hz, semi):
    return hz * (2.0 ** (semi / 12.0))


def read_ramp(n, ms, sr):
    """末段升余弦释放（顿）"""
    k = min(int(ms / 1000.0 * sr), n)
    env = np.ones(n)
    if k > 1:
        env[n - k:] = 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / (k - 1)))
    return env


# ---------------------------------------------------------------- 箫：气声竹管

def xiao_phrase(notes, sr, tau=2.6, glide_s=0.045, vib_cents=16.0, vib_rate=4.8,
                accent=None, rel_ms=110.0, seed=0, atk_floor=0.42):
    """合成箫的连奏乐句：一次起音 + 换指滑音；音色按真实箫的声学结构重建。

    与逐字 xiao_note 的区别在于相位连续：整句共用一条积分相位，音与音之间靠
    换指滑音过渡，故不会出现「一声一声重新吹」的风琴感。

    音色不再是正弦堆叠（那会让听感发「鬼」），而是四层：
      1) 管腔共振：非谐整数倍的驻波峰（开孔管的模态比 ~1, 2.0–2.1, 3.0–3.2…）
      2) 吹口气声：宽频 turbulence，带通中心**固定**（由吹口决定，不随音高扫）
      3) 筒音膜感：2.0–2.4 倍频的轻微成分，起音后渐入
      4) 低频胸腔共鸣：给一点底，避免听起来悬空
    """
    notes = [(float(d), float(f)) for d, f in notes if d > 0]
    if not notes:
        return np.zeros(8)
    times = [0.0]
    for d, _f in notes[:-1]:
        times.append(times[-1] + d)
    body = times[-1] + notes[-1][0]
    total = body + max(rel_ms, 40.0) / 1000.0
    n = max(int(total * sr), 8)
    t = np.arange(n) / sr

    # 音高轨迹：每字处换指，滑音窗 = glide_s
    kt, kv = [0.0], [math.log2(max(notes[0][1], 1e-6))]
    for i, (d, f) in enumerate(notes):
        kt.append(times[i])
        kv.append(math.log2(max(f, 1e-6)))
        if i + 1 < len(notes):
            kt.append(min(times[i] + glide_s, times[i + 1]))
            kv.append(math.log2(max(f, 1e-6)))
    logf = np.interp(t, kt, kv)
    if vib_cents:
        logf = logf + (vib_cents / 1200.0) * np.minimum(t / 0.25, 1.0) * \
            np.sin(2.0 * math.pi * vib_rate * t)
    f_trk = np.power(2.0, logf)
    ph = 2.0 * math.pi * np.cumsum(f_trk) / sr

    # 1) 管腔共振：模态比刻意取非整数倍，这是「像管乐器」的关键
    y = np.zeros(n)
    modes = ((1.00, 0.62), (2.03, 0.30), (3.11, 0.17), (4.17, 0.10),
             (5.29, 0.06), (6.41, 0.035))
    for r, g0 in modes:
        y += g0 * np.sin(r * ph)

    # 2) 吹口气声：中心频率固定在 ~1.9kHz（吹口尺寸决定，不跟音高走）
    rng = np.random.default_rng(seed + 977)
    br = rng.standard_normal(n)
    b1, a1 = butter(2, [700 / (sr / 2), 3400 / (sr / 2)], btype="band")
    y += 0.26 * lfilter(b1, a1, br)
    # 气声随音高略增（高音需更急的吹），但绝不改变带通中心
    y += 0.10 * lfilter(b1, a1, br) * np.clip((f_trk - 240.0) / 260.0, 0.0, 1.0)

    # 3) 筒音膜感：起音后渐入的 2.2 倍频成分
    y += 0.045 * np.sin(2.2 * ph) * np.minimum(t / 0.18, 1.0)

    # 4) 低频胸腔感
    b0, a0 = butter(2, 260 / (sr / 2), btype="low")
    y += 0.20 * lfilter(b0, a0, y)

    env = np.ones(n)
    # 起音不从 0 起：换气后是「续上」，从 0 起会让每句开头「咯噔」一下
    atk = min(int(0.060 * sr), n)          # 箫起音比笛更慢（气柱起振）
    fl = float(atk_floor)
    env[:atk] = fl + (1.0 - fl) * (
        0.5 * (1.0 - np.cos(math.pi * np.arange(atk) / max(atk, 1))))
    acc = accent or [1.0] * len(notes)
    for i, (d, _f) in enumerate(notes):
        if i == 0:
            continue
        # 咬字：字头前微微收气，再给明确凸起（单靠正向凸起在混响下测不出来）
        depth = 0.09 + 0.30 * max(acc[i] - 1.0, 0.0)
        w = min(max(0.065, d * 0.30), 0.12)
        i0, i1 = int(times[i] / sr), min(int((times[i] + w) / sr) + 1, n)
        if i1 > i0 + 1:
            shape = 0.5 * (
                1.0 - np.cos(2.0 * math.pi * np.arange(i1 - i0) / (i1 - i0 - 1)))
            env[i0:i1] += depth * shape
            pre0 = max(i0 - int(0.045 * sr), 0)
            if i0 > pre0:
                env[pre0:i0] *= 0.80
    y = y * env * np.exp(-t / max(tau, 1e-3))
    b2, a2 = butter(2, 5200 / (sr / 2), "low")
    y = lfilter(b2, a2, y)
    k = min(int(rel_ms / 1000.0 * sr), n)
    if k > 1:
        y[n - k:] *= 0.5 * (1.0 + np.cos(math.pi * np.arange(k) / (k - 1)))
    pk = float(np.max(np.abs(y)))
    if pk > 0:
        y /= pk
    return y


def xiao_note(f0, dur, sr, seed=0):
    n = max(int(dur * sr), 8)
    t = np.arange(n) / sr
    rng = np.random.default_rng(seed + 313)
    vib = (18.0 / 100.0) * np.sin(2.0 * math.pi * 4.8 * t)      # 18 音分、4.8Hz
    ph = 2.0 * math.pi * f0 * np.cumsum(2.0 ** (vib / 12.0)) / sr
    y = np.zeros(n)
    for k in range(1, 6):
        y += (1.0 / k ** 1.8) * np.sin(k * ph)
    # 气声：带通噪声，随包络起伏
    b, a = butter(2, [600 / (sr / 2), 3500 / (sr / 2)], btype="band")
    br = lfilter(b, a, rng.normal(0, 1, n))
    atk = min(int(0.15 * sr), n)
    env = np.ones(n)
    env[:atk] = 0.5 * (1.0 - np.cos(np.pi * np.arange(atk) / atk))
    rel = min(int(0.35 * sr), n)
    env[n - rel:] *= 0.5 * (1.0 + np.cos(np.pi * np.arange(rel) / rel))
    y = y * env + 0.16 * br * env
    b2, a2 = butter(2, 4200 / (sr / 2), "low")
    y = lfilter(b2, a2, y)
    y /= (np.max(np.abs(y)) + 1e-12)
    return y


# ---------------------------------------------------------------- 笛：明亮竹管（合成 fallback）

def dizi_note(f0, dur, sr, seed=0):
    """加性合成笛——只作显式 fallback 与诊断对照，默认不走此路。

    实测对比：谐波滚降 -6.9 dB/oct、质心 2024–2586 Hz、无音内漂移，
    听感「不是笛子」。默认音色见 sampler.DiziBank（CC0 笛实录）。
    """
    n = max(int(dur * sr), 8)
    t = np.arange(n) / sr
    rng = np.random.default_rng(seed + 971)
    ramp = np.minimum(t / 0.22, 1.0)
    vib = (24.0 / 100.0) * ramp * np.sin(2.0 * math.pi * 5.6 * t)     # 24 音分、5.6Hz 气震
    ph = 2.0 * math.pi * f0 * np.cumsum(2.0 ** (vib / 12.0)) / sr
    y = np.zeros(n)
    for k in range(1, 9):
        y += (1.0 / k ** 1.15) * np.sin(k * ph)                       # 泛音更足 → 明亮
    y *= (1.0 + 0.05 * np.sin(2.0 * math.pi * 2.0 * f0 * t))          # 笛膜嗡鸣（轻幅调）
    b, a = butter(2, [1200 / (sr / 2), 5500 / (sr / 2)], btype="band")
    br = lfilter(b, a, rng.normal(0, 1, n))
    atk = min(int(0.045 * sr), n)                                    # 快起音
    env = np.ones(n)
    env[:atk] = 0.5 * (1.0 - np.cos(np.pi * np.arange(atk) / atk))
    rel = min(int(0.16 * sr), n)
    env[n - rel:] *= 0.5 * (1.0 + np.cos(np.pi * np.arange(rel) / rel))
    y = y * env + 0.09 * br * env
    b2, a2 = butter(2, 9000 / (sr / 2), "low")
    y = lfilter(b2, a2, y)
    y /= (np.max(np.abs(y)) + 1e-12)
    return y


# 吹管声部：声法表 events[] / guest_events 里带 voice（或 instrument）的条目走这里。
# 笛 = 实录（DiziBank）；箫 = 合成（无免费可再分发的箫实录）。
VOICE_SYNTH = {"dizi": dizi_note, "xiao": xiao_note}
VOICE_MAX_DUR = {"dizi": 1.8, "xiao": 2.4}     # 吹管单音最长时值（防止过长的「假持续」）
# 笛的实录衰减：实录本身是长音，用较大的 tau 保住自然延音；再由 fade 收尾
DIZI_TAU = {"none": 2.6, "yin": 2.4, "nao": 1.9}
DIZI_VIB = {"none": (0.0, 5.6), "yin": (10.0, 5.2), "nao": (22.0, 5.0)}


# ---------------------------------------------------------------- 琴体共鸣 + 混响

BODY_BANDS = [(90, 180, 0.32), (400, 900, 0.20), (2000, 3500, 0.10)]


def body(x, sr, bands=None):
    """琴体共鸣：给干声补三段体腔共振。

    bands 可被声法表 mix.body_bands 覆盖（如《静夜思》削掉 2–3.5k 抬升，
    该段抬升会把箫本就偏亮的高阶谐波再顶一截，是「亮刺/鬼气」的帮凶）。
    """
    y = x.copy()
    for lo, hi, g in (BODY_BANDS if bands is None else bands):
        if float(g) == 0.0:
            continue
        b, a = butter(2, [lo / (sr / 2), hi / (sr / 2)], btype="band")
        y += float(g) * lfilter(b, a, x)
    return y


def make_ir(sr, rt60, predelay_ms, seed=7, ch=2):
    L = int(rt60 * 1.5 * sr)
    t = np.arange(L) / sr
    decay = 10.0 ** (-3.0 * t / rt60)
    irs = []
    for c in range(ch):
        rng = np.random.default_rng(seed + 31 * c)
        ir = rng.normal(0, 1, L) * decay
        b, a = butter(1, 5000 / (sr / 2), "low")
        ir = lfilter(b, a, ir)
        ir[:int(predelay_ms / 1000.0 * sr)] = 0.0
        for d_ms, g in [(11, 0.55), (19, 0.42), (27, 0.30), (41, 0.22), (53, 0.15)]:
            idx = int((predelay_ms + d_ms) / 1000.0 * sr)
            if idx < L:
                ir[idx] += g * (1.0 if c == 0 else 0.85)
        ir /= math.sqrt(float(np.sum(ir ** 2)) + 1e-12)
        irs.append(ir)
    return irs


def reverb(x, sr, tiers):
    """双档混响：近场（短 RT60，给琴体空间）+ 远场（长 RT60，低电平给「空阔」）。
    江雪铁律「句末顿」要求静默段残余 ≤ −40 dBFS，故长混响只能以低电平存在。"""
    out = np.stack([x, x], axis=1) * (1.0 - sum(float(t["wet"]) for t in tiers))
    for t in tiers:
        irs = make_ir(sr, float(t["rt60"]), float(t["predelay_ms"]), seed=int(float(t["rt60"]) * 100) + 7)
        lp = float(t.get("lp_hz", 0.0))
        for c, ir in enumerate(irs):
            w = fftconvolve(x, ir)[:len(x)]
            if lp > 0.0:
                b, a = butter(2, lp / (sr / 2), "low")
                w = lfilter(b, a, w)
            out[:, c] += w * float(t["wet"])
    return out


# ---------------------------------------------------------------- 装配

def _legato_groups(ev_list, legato, lead, pitch):
    """把逐字主奏事件按「换气」切成乐句组，每组一次连奏吹完。

    切分规则全部来自声法表 rules.legato，渲染器不自行编曲：
      · max_notes      每句最多几个字，超了就换气（避免一口气太长憋住）
      · break_gap_s    相邻两字起音间隔超过此值 → 换气断开
      · accent_role    需要加重（做出「顿」感）的字类，入声等
      · tail_hold_s    句末延音（余响）
    返回 {voice: [组…]}，每组含 onset / notes=[(dur, f0)] / accent / trace。
    """
    max_notes = int(legato.get("max_notes", 99))
    break_gap = float(legato.get("break_gap_s", 10.0))
    accent_roles = set(legato.get("accent_role", ["entering"]))
    accent_gain = float(legato.get("accent_gain", 0.22))
    tail_hold = float(legato.get("tail_hold_s", 0.0))

    evs = [it for it in ev_list if it["ev"].get("voice") == lead]
    if not evs:
        return {}

    # 切分思路（两层）：
    #   ① 先按「气口」把整段切成句——相邻两字起音间隔超过 break_gap 即换气；
    #   ② 句内每 max_notes 字封一个乐句。
    # 韵脚（rhyme）代表句尾收束：若韵脚后面本句就没字了，就把它并进当前乐句，
    # 否则会出现「两个音 + 一记孤立尾音」，听感仍像风琴。min_notes 防止切出 1 字乐句。
    min_notes = int(legato.get("min_notes", 2))
    sentences, cur = [], []
    for it in evs:
        if cur and (it["onset"] - cur[-1]["onset"]) > break_gap:
            sentences.append(cur)
            cur = []
        cur.append(it)
    if cur:
        sentences.append(cur)

    raw = []
    for si, sent in enumerate(sentences):
        i = 0
        while i < len(sent):
            # 韵脚且其后本句无字 → 并入本乐句（句尾收束，不另起）
            chunk_end = i
            while (chunk_end + 1 < len(sent) and chunk_end - i + 1 < max_notes
                   and not (sent[chunk_end + 1]["ev"].get("rhyme")
                            and chunk_end + 1 == len(sent) - 1)):
                chunk_end += 1
            if sent[chunk_end]["ev"].get("rhyme") and chunk_end > i:
                pass                      # 韵脚已含在本 chunk 内
            raw.append(sent[i:chunk_end + 1])
            i = chunk_end + 1
        # 句子尾部若剩 1 字且上一乐句已够长，则并回上一乐句
        if (len(raw) >= 2 and len(raw[-1]) == 1
                and len(raw[-2]) < max_notes + 1 and not raw[-1][0]["ev"].get("rhyme")):
            raw[-2] = raw[-2] + raw[-1]
            raw.pop()
        elif len(raw) == 1 and len(raw[0]) == 1 and si > 0 and sentences[si - 1]:
            pass

    # 全局去 1 字句：孤立的单字乐句并入相邻乐句
    merged = True
    while merged and len(raw) > 1:
        merged = False
        for gi, g in enumerate(raw):
            if len(g) >= min_notes:
                continue
            prev_ok = gi > 0 and len(raw[gi - 1]) < max_notes
            next_ok = gi + 1 < len(raw) and len(raw[gi + 1]) < max_notes
            if prev_ok:
                raw[gi - 1] = raw[gi - 1] + g
                raw.pop(gi)
                merged = True
                break
            if next_ok:
                raw[gi] = g + raw[gi + 1]
                raw.pop(gi + 1)
                merged = True
                break
    raw = [g for g in raw if g]

    out = []
    for g in raw:
        notes, accent, tr, aexpr = [], [], [], []
        for j, it in enumerate(g):
            ev = it["ev"]
            f = pitch(ev["deg"], ev.get("oct", 0))
            # 组内每音的时长 = 到下一字起音的间隔；末音按 ring（含 overlap）
            dur = (g[j + 1]["onset"] - it["onset"]) if j + 1 < len(g) else max(it["ring"], 0.30)
            if tail_hold > 0 and j + 1 == len(g):
                dur += tail_hold
            notes.append((max(dur, 0.06), f))
            accent.append(1.0 + (accent_gain if ev.get("role") in accent_roles else 0.0))
            aexpr.append(ev.get("expr", "none"))
            tr.append({"line": ev.get("line"), "pos": ev.get("pos"), "char": ev.get("char"),
                       "want": lead, "expr": ev.get("expr", "none"), "f0": round(f, 1),
                       "kind": lead + "_legato", "group": len(out), "role": ev.get("role")})
        # 组内 gain 的时长加权平均：连奏后 phrase() 内部已峰值归一化，
        # 逐字 gain 若不继承进来，笛会比古琴客声响 30dB（实测 +31.0dB），
        # 压满混响后实录笛的气声与膜鸣被推成薄膜状共鸣 → 听感「是琴声」。
        wsum = sum(max(d, 0.06) for d, _f in notes)
        ggain = sum(float(it["ev"].get("gain", 1.0)) * max(d, 0.06)
                    for (d, _f), it in zip(notes, g)) / max(wsum, 1e-9)
        out.append({"onset": g[0]["onset"], "notes": notes, "accent": accent,
                    "gain": ggain,
                    "accent_expr": aexpr[0] if aexpr else "none", "trace": tr})
    return {lead: out}


def build(plan, sr, perturb_mute=None, bank=None, dizi_bank=None,
          xiao_bank=None, khim_bank=None, guzheng_bank=None):
    anchor = plan["anchor"]
    T = float(anchor["T"])
    n_total = int(round(T * sr))
    dry = np.zeros(n_total)
    if bank is None:
        bank = sampler.Bank(sr)      # 真实古琴干声（GuqinSonGest, CC BY 4.0）
    if dizi_bank is None:
        dizi_bank = sampler.DiziBank(sr)   # 真实笛干声（Hypnotriod, CC0 1.0）
    if xiao_bank is None:
        # 真实箫干声（pattingthestar, CC0 1.0）；缺失时 _render_phrase 退回合成
        xiao_bank = sampler.XiaoBank(sr)
    if khim_bank is None:
        # 真实扬琴干声（pattingthestar, CC0 1.0）；支持层用，替掉「古琴代琵琶」
        khim_bank = sampler.KhimBank(sr)
    if guzheng_bank is None:
        # 真实古筝干声（Pufermufin, Freesound 396868, CC0 1.0）；
        # 支持层用，替掉「古琴代筝」。缺失时 guest_events 退回合成。
        guzheng_bank = sampler.GuzhengBank(sr)

    win = [(float(a), float(b)) for a, b in anchor["line_windows"]]

    # 逐字起音：以 voice_json 的 frames 作权重，线性分配到各行窗口
    voice_json = ROOT / anchor["voice_json"]
    weights = {}
    if voice_json.exists():
        vd = json.loads(voice_json.read_text(encoding="utf-8"))
        for s in vd.get("syllables", []):
            weights[(int(s["line"]), int(s["pos"]))] = float(s.get("frames", 1))
    onsets = {}
    for li, (a, b) in enumerate(win, start=1):
        pos = [p for (l, p) in weights if l == li]
        if not pos:
            continue
        w = np.array([weights[(li, p)] for p in sorted(pos)], dtype=float)
        w = w / w.sum()
        cum = np.concatenate([[0.0], np.cumsum(w)[:-1]])
        for k, p in enumerate(sorted(pos)):
            onsets[(li, p)] = a + (b - a) * float(cum[k])

    mode = plan["mode"]
    tonic = float(mode["tonic_hz"])
    semis = mode["scale_semitones"]

    def pitch(deg, octv):
        return semitone(tonic, semis[int(deg)] + 12 * int(octv))

    # 音色档内变调上限：超过则回退「全池就近」（数据集只有一根 G2 弦的散/按干声）
    MAX_SEMI = float(plan.get("mix", {}).get("max_transpose_semi", 12.0))
    trace = []
    # 采样库缺失时的退路登记（真实干声之间互退，不退到合成音）
    bank_fallback = []

    def render_ev(ev, seed):
        voice = ev.get("voice", "qin")
        f = pitch(ev["deg"], ev.get("oct", 0))
        expr = ev.get("expr", "none")
        if voice == "dizi" and dizi_bank is not None:
            # 笛主奏：真实竹笛干声（Hypnotriod, CC0）。就近取源 + 变调 <2 半音。
            dur = min(float(ev["_dur"]), VOICE_MAX_DUR["dizi"])
            vc, vr = DIZI_VIB.get(expr, DIZI_VIB["none"])
            y, info = dizi_bank.note(f, dur, tau=DIZI_TAU.get(expr, DIZI_TAU["none"]),
                                     vib_cents=vc, vib_rate=vr, return_info=True)
            trace.append({"line": ev.get("line"), "pos": ev.get("pos"), "char": ev.get("char"),
                          "want": "dizi", "expr": expr, "f0": round(f, 1),
                          "kind": "dizi", "src": info["src"], "src_f0": info["src_f0"],
                          "transpose_semi": info["transpose_semi"]})
            return y
        if voice in VOICE_SYNTH:
            # 箫：合成（无免费可再分发的箫实录）。笛走到这里只可能是显式 fallback。
            dur = min(float(ev["_dur"]), VOICE_MAX_DUR[voice])
            y = VOICE_SYNTH[voice](f, dur, sr, seed=seed)
            trace.append({"line": ev.get("line"), "pos": ev.get("pos"), "char": ev.get("char"),
                          "want": voice, "expr": expr, "f0": round(f, 1),
                          "kind": voice + "_synth"})
            return y
        color = ev["color"]
        if color == "san":
            if expr == "chuo":
                # 绰：用真实走手音干声（样本自带上滑），不再叠加合成滑音
                y, kind = bank.note("gli", f, ev["_dur"], tau=2.2, max_semi=MAX_SEMI), "gli"
            else:
                y = bank.note("san", f, ev["_dur"], tau=2.2, max_semi=MAX_SEMI,
                              vib_cents=6.0 if expr == "yin" else 0.0, vib_rate=5.2)
                kind = "san"
        elif color == "an":
            kind = "an"
            y = None
            if expr == "nao":
                # 真实颤吟样本只在音高接近时用：变调会同比放大颤吟速率
                s = bank.pick("vib", f)
                if s is not None and abs(12.0 * math.log2(f / max(s["f0"], 1e-6))) <= 3.0:
                    y, kind = bank.note("vib", f, ev["_dur"], tau=1.15, max_semi=MAX_SEMI), "vib"
            if y is None and expr == "zhu":
                # 注：用真实走手音干声（样本自带下滑）
                y, kind = bank.note("gli", f, ev["_dur"], tau=1.15, max_semi=MAX_SEMI), "gli"
            if y is None:
                y = bank.note("an", f, ev["_dur"], tau=1.15, max_semi=MAX_SEMI,
                              vib_cents=(22.0 if expr == "nao" else 8.0) if expr in ("nao", "yin") else 0.0,
                              vib_rate=2.6 if expr == "nao" else 5.6)
                kind = "an"
        elif color == "fan":
            dun = 60.0 if (expr == "dun" and not ev.get("rhyme") and not ev.get("line_end")) else None
            y = bank.note("fan", f, ev["_dur"], tau=2.0 if ev.get("rhyme") else 1.9,
                          dun_ms=dun, max_semi=MAX_SEMI)
            kind = "fan"
        else:
            raise ValueError(color)
        trace.append({"line": ev.get("line"), "pos": ev.get("pos"), "char": ev.get("char"),
                      "want": color, "expr": expr, "f0": round(f, 1), "kind": kind})
        return y

    # 全局起音序列（跨行）：每个音「响到下一次起音」→ 连贯叠音织体。
    # 行间气口不再留白——前音余响贯入后句，消除「断」。
    rules = plan.get("rules", {})
    ring_max = float(rules.get("ring_max_s", 3.0))
    ring_min = float(rules.get("ring_min_s", 0.35))
    overlap = float(rules.get("note_overlap_s", 0.25))
    rel_ms = float(rules.get("note_release_ms", 120.0))
    ev_list = []
    for li, (a, _b) in enumerate(win, start=1):
        for ev in plan["events"]:
            if int(ev["line"]) != li:
                continue
            ev_list.append({"li": li, "ev": ev, "onset": onsets.get((li, int(ev["pos"])), a)})
    ev_list.sort(key=lambda z: z["onset"])
    for i, it in enumerate(ev_list):
        if i + 1 < len(ev_list):
            span = ev_list[i + 1]["onset"] - it["onset"] + overlap
        else:
            span = T - it["onset"]                  # 末音余响贯至曲末
        it["ring"] = max(min(span, ring_max), ring_min)

    # 吹管主奏「乐句化」：逐字事件按气口分组，每组用一次连奏吹完（见 rules.legato）。
    # 逐字独立起音 + 独立释放会让一句变成一串风琴，故这里整句一次起音 + 换指滑音。
    # 实录笛走 DiziBank.phrase；合成箫走 xiao_phrase（同一套乐句逻辑）。
    rules_all = plan.get("rules", {})
    legato = rules_all.get("legato", {})
    lead = rules_all.get("legato_voice", "dizi")
    legato_groups = []
    lead_bus = np.zeros(n_total)         # 主奏干声轨（配比诊断与调试用）
    vgroups = _legato_groups(ev_list, legato, lead, pitch) if legato else {}

    for it in ev_list:
        ev = dict(it["ev"])
        if legato and ev.get("voice") == lead:
            continue                      # 主奏声部改由下面的乐句连奏统一铺
        ev["_dur"] = it["ring"]
        y = render_ev(ev, seed=1000 * it["li"] + int(ev["pos"]))
        y = y * read_ramp(len(y), rel_ms, sr)        # 平滑释放，避免截断爆音
        y = y * float(ev["gain"])
        j = int(round(it["onset"] * sr))
        k = min(len(y), n_total - j)
        if k > 0:
            dry[j:j + k] += y[:k]

    for g in vgroups.get(lead, []):
        if lead == "dizi" and dizi_bank is not None and dizi_bank.samples:
            y = dizi_bank.phrase(
                g["notes"], sr,
                tau=float(legato.get("tau", 2.6)),
                glide_s=float(legato.get("glide_ms", 45.0)) / 1000.0,
                vib_cents=0.0,
                rel_ms=float(legato.get("phrase_release_ms", 110.0)),
                accent=g["accent"],
                atk_floor=float(legato.get("atk_floor", 0.45)),
            )
        elif lead == "xiao" and xiao_bank is not None and xiao_bank.samples:
            vc, _vr = DIZI_VIB.get(g["accent_expr"], DIZI_VIB["none"])
            y = xiao_bank.phrase(
                g["notes"], sr,
                tau=float(legato.get("tau", 2.6)),
                glide_s=float(legato.get("glide_ms", 45.0)) / 1000.0,
                vib_cents=float(legato.get("vib_cents", vc)),
                rel_ms=float(legato.get("phrase_release_ms", 110.0)),
                accent=g["accent"],
                atk_floor=float(legato.get("atk_floor", 0.42)),
            )
        else:
            vc, vr = DIZI_VIB.get(g["accent_expr"], DIZI_VIB["none"])
            y = xiao_phrase(g["notes"], sr, tau=float(legato.get("tau", 2.6)),
                            glide_s=float(legato.get("glide_ms", 45.0)) / 1000.0,
                            vib_cents=float(legato.get("vib_cents", vc)),
                            vib_rate=vr, accent=g["accent"],
                            rel_ms=float(legato.get("phrase_release_ms", 110.0)),
                            atk_floor=float(legato.get("atk_floor", 0.42)))
        y = _tilt(y, sr, float(legato.get("hp_hz", 0.0)),
                  float(legato.get("tilt_db", 0.0)))
        tone = legato.get("tone") or {}
        if tone:
            y = _tone(y, sr,
                      lp_hz=float(tone.get("lp_hz", 0.0)),
                      lp_order=int(tone.get("lp_order", 2)),
                      shelf_hz=float(tone.get("shelf_hz", 0.0)),
                      shelf_db=float(tone.get("shelf_db", 0.0)))
        y = y * float(legato.get("gain", 1.0)) * float(g.get("gain", 1.0))
        j = int(round(g["onset"] * sr))
        k = min(len(y), n_total - j)
        if k > 0:
            dry[j:j + k] += y[:k]
            lead_bus[j:j + k] += y[:k]      # 主奏干声轨，供配比诊断与调试
        legato_groups.append({"voice": lead,
                              "gain": float(g.get("gain", 1.0)),
                              "tau": float(legato.get("tau", 2.6)),
                              "glide_ms": float(legato.get("glide_ms", 45.0)),
                              "vib_cents": float(legato.get("vib_cents", 0.0)),
                              "rel_ms": float(legato.get("phrase_release_ms", 110.0)),
                              "onset": round(g["onset"], 3),
                              "chars": "".join(t["char"] or "?" for t in g["trace"]),
                              "n": len(g["notes"]),
                              "dur_s": round(len(y) / sr, 3),
                              "notes": g["notes"],        # 供护栏复算同一乐句
                              "accent": g["accent"]})
        trace.extend(g["trace"])        # 逐字记录仍留档，便于溯源每个字的音高

    line_gain = {}
    for li, (a, b) in enumerate(win, start=1):
        i0, i1 = int(round(a * sr)), int(round(b * sr))
        line_gain[li] = float(np.max(np.abs(dry[i0:i1])) + 1e-9)

    # 低音层（散起 / 气口）的音源选择。
    #
    # 为什么不能一律用古琴 bank：GuqinSonGest 只有 G2（96.87 Hz）一根空弦。
    # 《静夜思》的低音区在 C4，而 Bank.note 会把它硬升 17.2 个半音到一个八度
    # 以上——该库 docstring 自己写了「G2 散音升到 C4 以上音色变尖」，而散音/气口
    # 这两处调用**没有传 max_semi**，护栏被绕开。后果实测
    # （_archive/_scratch_diag_2026-10-06/ghost_probe.py）：
    #   · 变调 +17.2 半音 → 气口音成为一根薄而尖的「啸叫」，而非低音地基；
    #   · 气口窗口内 60–160 Hz 能量占比 = 0.0000，低音地基根本没落地；
    #   · 基频落在 160–320 Hz，与主奏 C5 同音级差八度 → 空洞的「鬼叫」感。
    #
    # 故声法表可给散起/气口指定 drone=guzheng：古筝素材原生覆盖 D2–A5
    # （D3=146.83 Hz 为素材原生音），低音区无需任何强变调。
    # **默认仍是古琴**（江雪《江雪》写的是 G2 区，正是古琴原生音区，不可动），
    # 只有显式写 "drone": "guzheng" 的声法表才切筝。
    # max_semi 同为**逐声法表开启**（drone_max_semi）：古琴回退路径要保持既有
    # 行为不变——直接补一个默认上限会让江雪/白帝城的散音换源、整曲重渲。
    def drone_note(spec, dur, tau, f):
        gain = float(spec["gain"])
        if spec.get("drone") == "guzheng" and guzheng_bank is not None \
                and guzheng_bank.samples:
            y, info = guzheng_bank.note(f, dur, tau=tau, return_info=True)
            trace.append({"line": spec.get("line"), "pos": spec.get("pos"),
                          "want": "drone", "f0": round(f, 1),
                          "kind": "drone_guzheng", "src": info["src"],
                          "src_f0": info["src_f0"],
                          "transpose_semi": info["transpose_semi"]})
            return y * gain
        # 回退古琴：max_semi 只在声法表显式要求时才生效
        y = bank.note(spec.get("color", "san"), f, dur, tau=tau,
                      max_semi=spec.get("drone_max_semi")) * gain
        trace.append({"line": spec.get("line"), "pos": spec.get("pos"),
                      "want": "drone", "f0": round(f, 1), "kind": "drone_guqin"})
        return y

    # 散起：空镜起兴的低散音（余响贯入第 1 句）
    qs = plan.get("散起")
    if qs:
        f = pitch(qs["deg"], qs.get("oct", 0))
        dur = min(win[0][1] - float(qs["at"]) + 0.6, 3.4)
        y = drone_note(qs, dur, float(qs.get("tau", 2.4)), f)
        j = int(round(float(qs["at"]) * sr))
        k = min(len(y), n_total - j)
        dry[j:j + k] += y[:k]

    # 气口低散音：行间气口贯入的长散音，填满「断」处（用户要求：音乐自然连续）
    for g in plan.get("breath_events", []):
        f = pitch(g["deg"], g.get("oct", 0))
        y = drone_note(g, float(g["ring"]), float(g.get("tau", 2.4)), f)
        j = int(round(float(g["at"]) * sr))
        k = min(len(y), n_total - j)
        if k > 0:
            dry[j:j + k] += y[:k]

    # 客声：吹管偶入（箫 / 笛）或古琴点缀（代琵琶 / 筝）
    # 对齐口径：主奏连奏乐句按气口切分，客声按逐字起音定位，两者不重合 →
    # 古琴拨弦会正好顶在笛的换气口上（实测 6.79s 有 8.4dB 起伏、乐句起点却在 6.81s）。
    # 故客声默认 align=phrase：吸附到最近乐句边界之后 settle_s 毫秒，
    # 即「乐句头已过、气息正稳时」再点缀，听感才对得上主奏的乐句线。
    settle = float(plan.get("rules", {}).get("guest_align_settle_s", 0.06))
    ph_starts = [g["onset"] for g in legato_groups] if legato_groups else []
    for g in plan.get("guest_events", []):
        key = (int(g["at_line"]), int(g["at_pos"]))
        a, b = win[int(g["at_line"]) - 1]
        onset = onsets.get(key, a)
        if g.get("align", "phrase") == "phrase" and ph_starts:
            nxt = [t for t in ph_starts if t <= onset + 0.001]
            onset = (max(nxt) if nxt else min(ph_starts)) + settle
        f = pitch(g["deg"], g.get("oct", 0))
        inst = g.get("instrument", "xiao")
        if inst == "khim" and khim_bank is not None and khim_bank.samples:
            # 扬琴支持层（真实干声，pattingthestar CC0 1.0）：中国乐器，
            # 替掉原先「古琴代琵琶」。拨弦用短 tau（0.85s）还原快速衰减，
            # 顿音用 dun（止弦），与笛的吹管音色形成层次差。
            dur = min(float(g.get("dur", 0.9)), b - onset)
            dun = 70.0 if g.get("expr") == "dun" else None
            y, info = khim_bank.note(f, max(dur, 0.35), tau=0.85, dun_ms=dun,
                                     max_semi=MAX_SEMI, return_info=True)
            y = y * float(g["gain"])
            trace.append({"line": int(g["at_line"]), "pos": int(g["at_pos"]),
                          "want": "khim", "expr": g.get("expr", "none"),
                          "f0": round(f, 1), "kind": "khim",
                          "src": info["src"], "src_f0": info["src_f0"],
                          "transpose_semi": round(info["transpose_semi"], 2)})
        elif inst == "guzheng" and guzheng_bank is not None and guzheng_bank.samples:
            # 古筝支持层（真实干声，Pufermufin / Freesound 396868, CC0 1.0）：
            # 替掉原先「古琴代筝」。与扬琴同为拨弦但两点不同——
            # ① 素材是 D 五声音阶，取源由 GuzhengBank.snap 吸附到调内音级，
            #    音准偏差恒在 snap_cents 内；
            # ② 素材 tags 含 reverb（build 阶段只做了截尾 + 递增低通，非真正
            #    干湿分离），故 tau 取 1.6s 而非扬琴 0.85s，并靠混响层做
            #    空间，而不在采样里留两遍混响。
            dur = min(float(g.get("dur", 0.9)), b - onset)
            dun = 90.0 if g.get("expr") == "dun" else None
            y, info = guzheng_bank.note(f, max(dur, 0.35), tau=1.6, dun_ms=dun,
                                        max_semi=MAX_SEMI, return_info=True)
            y = y * float(g["gain"])
            trace.append({"line": int(g["at_line"]), "pos": int(g["at_pos"]),
                          "want": "guzheng", "expr": g.get("expr", "none"),
                          "f0": round(f, 1), "kind": "guzheng",
                          "src": info["src"], "src_f0": info["src_f0"],
                          "snap_dev_cents": info["snap_dev_cents"],
                          "in_scale": info["in_scale"],
                          "transpose_semi": round(info["transpose_semi"], 2)})
        elif inst == "guzheng":
            # 采样库缺失时的显式退路：仍走古琴真实干声（原先的「代筝」），
            # 不用合成音。走 else 分支会 VOICE_SYNTH["guzheng"] KeyError，
            # 因为 VOICE_SYNTH 只收笛/箫两个吹管合成器。
            bank_fallback.append({"line": int(g["at_line"]), "pos": int(g["at_pos"]),
                                  "want": "guzheng", "used": "guqin",
                                  "note": "guzheng/manifest.json 缺失或为空，退回古琴干声"})
            y = bank.note(g.get("color", "an"), f, float(g.get("dur", 0.9)),
                          tau=2.0, max_semi=MAX_SEMI) * float(g["gain"])
        elif inst == "guqin":
            col = g.get("color", "an")
            y = bank.note(col, f, float(g.get("dur", 0.9)),
                          tau=1.2 if col == "an" else 2.0, max_semi=MAX_SEMI) * float(g["gain"])
        elif inst == "dizi" and dizi_bank is not None:
            dur = min(float(g["dur"]), b - onset)
            y = dizi_bank.note(f, dur, tau=DIZI_TAU["none"]) * float(g["gain"])
        else:
            dur = min(float(g["dur"]), b - onset)
            y = VOICE_SYNTH[inst](f, dur, sr, seed=500 + key[0] * 10 + key[1]) * float(g["gain"])
        j = int(round(onset * sr))
        k = min(len(y), n_total - j)
        if k > 0:
            dry[j:j + k] += y[:k]

    dry = body(dry, sr, plan.get("mix", {}).get("body_bands"))

    mx = plan["mix"]
    out = reverb(dry, sr, mx["reverb_tiers"])

    # 负向扰动（自检用）：抹掉一段 → 连续性断言必须失败
    if perturb_mute is not None:
        a, b = perturb_mute
        out[int(a * sr):int(b * sr)] = 0.0

    target = 10.0 ** (float(mx["target_peak_dbfs"]) / 20.0)
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out *= target / peak
    # 软限幅：soft_clip ∈ [0,1]，1=极窄动态（江雪），0=不压（宽动态）。表里以此表达「宽 / 中 / 窄动态」。
    sc = float(mx.get("soft_clip", 1.0))
    if sc > 0.0:
        out = (1.0 - sc) * out + sc * (np.tanh(out / target) * target)

    # 曲末短渐隐：保证在 T 处归零，不产生截断爆音
    k = min(int(float(mx.get("tail_fade_ms", 300.0)) / 1000.0 * sr), len(out))
    if k > 1:
        out[len(out) - k:] *= (0.5 * (1.0 + np.cos(np.pi * np.arange(k) / max(k - 1, 1))))[:, None]

    meta = {"onsets": {f"{k[0]}-{k[1]}": round(v, 3) for k, v in onsets.items()},
            "line_peak": {str(k): round(db(v, -60), 1) for k, v in line_gain.items()},
            "ring_s": [round(it["ring"], 3) for it in ev_list],
            "dizi_src": [t for t in trace if t.get("kind") == "dizi_legato"],
            "dizi_legato_groups": legato_groups,
            "lead_bus": lead_bus,
            "dizi_octave_flags": (dizi_bank.pitch_log if dizi_bank is not None else []),
            "guest_src": [t for t in trace
                          if t.get("kind") in ("khim", "guzheng")],
            "bank_fallback": bank_fallback,
            "trace": trace}
    return out, meta


# ---------------------------------------------------------------- 度量

def measure(mix, sr, plan):
    """连续性度量：短时 RMS（100ms 窗 / 20ms 跳）低于 floor 视为「静默」，
    取最长静默段与静默占比。音乐应连贯 → 最长静默须很小。"""
    mono = mix.mean(axis=1)
    n = len(mono)
    peak = float(np.max(np.abs(mix)))
    rms = float(np.sqrt(np.mean(mono ** 2)))
    crest = 20 * math.log10(peak / max(rms, 1e-12))
    floor_db = float(plan["checks"]["gap_floor_dbfs"])
    hop = max(int(0.020 * sr), 1)
    wn = max(int(0.100 * sr), hop + 1)
    gaps, cur = [], None
    for i0 in range(0, max(n - wn, 1), hop):
        seg = mono[i0:i0 + wn]
        v = db(float(np.sqrt(np.mean(seg ** 2))))
        if v < floor_db:
            t0 = i0 / sr
            if cur is None:
                cur = [t0, t0 + wn / sr]
            else:
                cur[1] = t0 + wn / sr
        elif cur is not None:
            gaps.append(cur)
            cur = None
    if cur is not None:
        gaps.append(cur)
    gap_total = sum(b - a for a, b in gaps)
    longest = max((b - a for a, b in gaps), default=0.0)
    return {"duration_s": round(n / sr, 4), "peak_dbfs": round(db(peak), 2),
            "rms_dbfs": round(db(rms), 2), "crest_db": round(crest, 2),
            "gap_floor_dbfs": floor_db,
            "gaps": [[round(a, 3), round(b, 3)] for a, b in gaps],
            "longest_gap_s": round(longest, 3), "gap_total_s": round(gap_total, 3),
            "gap_ratio": round(gap_total / (n / sr), 4)}


def check(m, plan):
    c = plan["checks"]
    T = float(plan["anchor"]["T"])
    fails = []
    if abs(m["duration_s"] - T) > c["duration_tolerance_samples"] / plan["mix"]["sr"] + 1e-6:
        fails.append(f"时长 {m['duration_s']}s ≠ T {T}s")
    if m["longest_gap_s"] > c["max_gap_s"]:
        fails.append(f"最长静默 {m['longest_gap_s']}s > {c['max_gap_s']}s（音乐不连续）")
    lo, hi = c["peak_dbfs_range"]
    if not (lo <= m["peak_dbfs"] <= hi):
        fails.append(f"峰值 {m['peak_dbfs']} dBFS 不在 [{lo},{hi}]")
    if m["crest_db"] > c["crest_factor_db_max"]:
        fails.append(f"波峰因数 {m['crest_db']} dB > {c['crest_factor_db_max']}（动态过宽）")
    return fails


# ---------------------------------------------------------------- 单元「处方兑现」断言

def detect_f0(x, sr, lo=80.0, hi=1600.0, t0=0.02, t1=0.30):
    """自相关基频检测（用于合成器单元校验）。

    不能用「FFT 峰值」直接取基频：琴音（尤其亮按音）的二倍频常与基频等强甚至更强，
    argmax 会把 2f0 误判为 f0。改为自相关：越过首个反相零点后取首个显著局部极大，
    该点即基频周期（2f0 处恰好反相抵消，不会误选）。"""
    a, b = int(t0 * sr), int(t1 * sr)
    w = x[a:b]
    if len(w) < 64:
        return 0.0
    w = w - float(np.mean(w))
    n = len(w)
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    W = np.fft.rfft(w, nfft)
    ac = np.fft.irfft(np.abs(W) ** 2, nfft)[:n]
    if ac[0] <= 1e-12:
        return 0.0
    ac = ac / ac[0]
    k_min = max(2, int(sr / hi))
    k_max = min(n - 2, int(sr / lo))
    if k_max <= k_min + 1:
        return 0.0
    mx = float(np.max(ac[k_min:k_max + 1]))
    if mx <= 1e-9:
        return 0.0
    # 越过首个零点：基频周期之前必先经历一次反相（自相关过零）
    k0 = k_min
    while k0 < k_max and ac[k0] > 0.0:
        k0 += 1
    if k0 >= k_max:
        k0 = k_min
    # 首个显著局部极大 = 基频周期
    best = None
    for k in range(max(k0, k_min + 1), k_max):
        if ac[k] > ac[k - 1] and ac[k] >= ac[k + 1] and ac[k] >= 0.6 * mx:
            best = k
            break
    if best is None:
        best = k_min + int(np.argmax(ac[k_min:k_max + 1]))
    if k_min < best < k_max:
        a1, b1, c1 = ac[best - 1], ac[best], ac[best + 1]
        den = a1 - 2.0 * b1 + c1
        d = 0.0 if abs(den) < 1e-12 else 0.5 * (a1 - c1) / den
        d = max(-0.5, min(0.5, d))
        lag = best + d
    else:
        lag = float(best)
    return float(sr / max(lag, 1e-9))


def unit_checks(sr, bank, dizi_bank=None):
    """证明采样播放器「按处方出声」：音高落在指定音上、走手音真的滑。"""
    fails = []
    cases = [
        ("散音样本 440Hz", lambda: bank.note("san", 440.0, 1.0, tau=2.2), 440.0, 0.03),
        ("按音样本 349.23Hz", lambda: bank.note("an", 349.23, 1.0, tau=1.15), 349.23, 0.03),
        ("泛音样本 261.63Hz", lambda: bank.note("fan", 261.63, 1.0, tau=1.9), 261.63, 0.03),
        ("箫(合成) 392Hz", lambda: xiao_note(392.0, 1.0, sr, seed=4), 392.0, 0.03),
        ("笛(合成fallback) 392Hz", lambda: dizi_note(392.0, 1.0, sr, seed=6), 392.0, 0.03),
    ]
    if dizi_bank is not None:
        # 笛实录的音高断言用「同检测器残差」口径，不能直接比目标 Hz。
        # 原因：自相关检测器对真实吹奏有系统偏置（实测源样本本身被读高 +38～+133 音分，
        # 因为真实笛的泛音结构让自相关的首个局部极大偏离真实周期）。
        # 故改为：渲染色与「同一源样本原样」在同口径下比对，残差即变调精度。
        by_label = {s["label"]: s for s in dizi_bank.samples}
        for want in (392.0, 523.25, 587.33, 659.25, 784.0):
            y, info = dizi_bank.note(want, 1.0, tau=2.6, return_info=True)
            src = by_label[info["src"]]
            y_got = detect_f0(y, sr, lo=want * 0.72, hi=want * 1.40)
            s_got = detect_f0(src["x"], sr, lo=want * 0.72, hi=want * 1.40)
            if s_got <= 0 or y_got <= 0:
                fails.append(f"笛(实录) {want:.2f}Hz 检测失败")
                print(f"    笛(实录) {want:.2f}Hz: 检测失败  ✗")
                continue
            resid = 1200.0 * math.log2((y_got / s_got) / (want / src["f0"]))
            ok = abs(resid) <= 15.0
            print(f"    笛(实录) {want:.2f}Hz ← {info['src']}: 变调残差 {resid:+.1f} 音分"
                  f"（≤15，源自身读数偏差已扣除）" + ("  ✓" if ok else "  ✗"))
            if not ok:
                fails.append(f"笛(实录) {want:.2f}Hz 变调残差 {resid:+.1f} 音分 > 15")
    for name, make, want, tol in cases:
        got = detect_f0(make(), sr)
        ok = abs(got - want) / want <= tol
        print(f"    {name}: 测得 {got:.1f} Hz（期望 {want:.2f}，容差 {tol*100:.0f}%）"
              + ("  ✓" if ok else "  ✗"))
        if not ok:
            fails.append(f"{name} 实测 {got:.1f} ≠ {want:.2f}")
    # 走手音：注（下滑）。走手音只持续 glide_time，故必须比对「起音瞬间」与「稳定段」，
    # 若按整段 0.02–0.30s 取值则整段都在滑完之后，必然测不到。
    g = bank.note("an", 440.0, 1.0, tau=1.15, glide_from_semi=1.5, glide_time=0.14)
    f_start = detect_f0(g, sr, t0=0.015, t1=0.060)
    f_end = detect_f0(g, sr, t0=0.25, t1=0.45)
    semis = 12 * math.log2(max(f_start, 1e-6) / max(f_end, 1e-6))
    ok = 0.4 <= semis <= 1.8
    print(f"    走手音·注: 起音高出 {semis:+.2f} 半音（期望 ≈ +1.2，窗口 0.015–0.06s vs 0.25–0.45s）"
          + ("  ✓" if ok else "  ✗"))
    if not ok:
        fails.append(f"走手音未生效（{semis:+.2f} 半音）")
    return fails


def unit_negative(sr, bank, dizi_bank=None):
    """证明单元断言可失败（否则是永远通过的「空断言」）：
    ① 故意升 1.5 半音的音，音高断言必须判失败；
    ② 不加走手音，走手音断言必须判失败；
    ③ 笛实录的「变调残差」断言也必须可失败（故意错 1.5 半音取源）。"""
    fails = []
    got = detect_f0(bank.note("san", 440.0 * 2 ** (1.5 / 12), 1.0, tau=2.2), sr)
    if abs(got - 440.0) / 440.0 <= 0.03:
        fails.append(f"音高断言是空断言：故意升 1.5 半音（实测 {got:.1f} Hz）仍判通过")
    g = bank.note("an", 440.0, 1.0, tau=1.15)   # 不给 glide
    semis = 12 * math.log2(max(detect_f0(g, sr, t0=0.015, t1=0.060), 1e-6)
                           / max(detect_f0(g, sr, t0=0.25, t1=0.45), 1e-6))
    if 0.4 <= semis <= 1.8:
        fails.append(f"走手音断言是空断言：不加走手音（实测 {semis:+.2f} 半音）仍判通过")
    # ③ 笛变调残差：用「比就近取源刻意偏 1.5 半音」的样本冒充，残差断言必须判失败
    if dizi_bank is not None and dizi_bank.samples:
        want = 587.33
        nearest = min(dizi_bank.samples, key=lambda c: abs(12.0 * math.log2(want / c["f0"])))
        wrong = min((c for c in dizi_bank.samples if c["label"] != nearest["label"]),
                    key=lambda c: abs(abs(12.0 * math.log2(want / c["f0"])) - 1.5))
        y = dizi_bank.note(want, 1.0, tau=2.6, return_info=True)[0]
        y_got = detect_f0(y, sr, lo=want * 0.72, hi=want * 1.40)
        s_got = detect_f0(wrong["x"], sr, lo=want * 0.72, hi=want * 1.40)
        if y_got > 0 and s_got > 0:
            resid = 1200.0 * math.log2((y_got / s_got) / (want / wrong["f0"]))
            ok = abs(resid) > 15.0
            print(f"    负向（笛错 1.5 半音取源 {wrong['label']}）残差: {resid:+.1f} 音分（应 >15）"
                  + ("  ✓" if ok else "  ✗"))
            if not ok:
                fails.append(f"笛变调残差断言是空断言：错 1.5 半音（{resid:+.1f} 音分）仍判通过")
    return fails


# ---------------------------------------------------------------- 音色护栏（防「电子滴答」回归）
#
# 采样替换前用「音头上升时间」判「咔」；该口径只盯瞬态，抓不住更细的音色劣化（如变调过度
# 变尖薄）。采样替换后升级为「与参考采样的频谱包络距离」：渲染出的音，其 24 带对数频谱包络
# 必须贴近真实录音的包络；宽带合成音（白噪「滴答」）与之距离显著更大。
ENV_DIST_MAX = 3.0    # dB：归一化（去均值）24 带包络的 RMS 距离上限
# 半音：主奏旋律到最近可用采样源的最大变调量上限。超过则音色已不是该乐器
# （见 register_checks 的实测背景：《静夜思》曾达 +10 半音，听感只剩筝）
REGISTER_MAX_SEMI = 4.0
# 音分：渲染出的主奏「实测音高」与声法表处方音高的最大允许偏差。
# 这条是「兑现」而非「处方」——register_checks 只管处方变调量，管不到渲染结果。
# 实测踩坑：采样器读指针步长多除了一个 sr，处方全对，渲染却掉进次声区（偏差数千音分）。
REALIZATION_TOL_CENTS = 50.0


def band_envelope(y, sr, f_lo=80.0, f_hi=8000.0, n_band=24, dur=0.30):
    """24 带对数频谱包络（dB，去均值 → 只比形状、不比电平）。"""
    n = min(int(dur * sr), len(y))
    if n < 128:
        return np.zeros(n_band)
    w = y[:n] * np.hanning(n)
    Y = np.abs(np.fft.rfft(w))
    f = np.fft.rfftfreq(n, 1.0 / sr)
    edges = np.geomspace(f_lo, f_hi, n_band + 1)
    env = np.zeros(n_band)
    for i in range(n_band):
        m = (f >= edges[i]) & (f < edges[i + 1])
        env[i] = math.sqrt(float(np.mean(Y[m] ** 2))) if m.any() else 1e-9
    env = 20.0 * np.log10(env + 1e-9)
    return env - float(env.mean())


def env_distance(y, ref, sr):
    """两条波形频谱包络的 RMS 距离（dB）。"""
    return float(np.sqrt(np.mean((band_envelope(y, sr) - band_envelope(ref, sr)) ** 2)))


def timbre_checks(sr, bank):
    """音色护栏：渲染音（各音色档、源音高零变调）的频谱包络须贴近参考采样。"""
    fails = []
    for name, kind in [("散音", "san"), ("按音", "an"), ("泛音", "fan")]:
        pool = bank.pool.get(kind) or []
        if not pool:
            continue
        src = pool[0]
        y = bank.note(kind, src["f0"], 1.0, tau=2.0, max_semi=0.0)
        d = env_distance(y, src["x"], sr)
        ok = d <= ENV_DIST_MAX
        print(f"    {name}包络距离: {d:.2f} dB（≤{ENV_DIST_MAX}，源 {src['label']}）"
              + ("  ✓" if ok else "  ✗"))
        if not ok:
            fails.append(f"{name}音色偏离参考采样 {d:.2f} dB > {ENV_DIST_MAX}")
    return fails


def _tilt(x, sr, hp_hz=0.0, tilt_db=0.0, pivot_hz=2000.0):
    """吹管整形：hp_hz 去掉管腔低频轰鸣，tilt_db 在 pivot 处抬亮。

    两者都只影响音色平衡，不改音高与包络，故不影响任何音高断言。
    """
    y = x
    if hp_hz and hp_hz > 0:
        b, a = butter(2, min(hp_hz / (sr / 2), 0.98), btype="high")
        y = lfilter(b, a, y)
    if tilt_db:
        lo, hi = 120.0, min(6500.0, sr / 2 - 100.0)
        b1, a1 = butter(1, hi / (sr / 2), btype="low")
        b2, a2 = butter(1, lo / (sr / 2), btype="low")
        side = lfilter(b1, a1, y) - lfilter(b2, a2, y)
        g = 10.0 ** (float(tilt_db) / 20.0)
        y = y + (g - 1.0) * side
    return y


def _tone(x, sr, lp_hz=0.0, lp_order=2, shelf_hz=0.0, shelf_db=0.0):
    """主奏音色整形（去「亮刺 / 鬼气」用，只改音色平衡，不动音高与包络）。

    lp_hz    低通截止：削掉高阶谐波与宽带气噪的高频段；
    shelf_hz 高架转折，shelf_db 取负值压该点以上频段（保基频、压 2–4 次谐波）。

    北箫实录的 2–4 次谐波实测几乎与基频同强（D5 谐波 72/67/65/64 dB），
    质心 2877 Hz，远高于真箫的 1000–1500 Hz；此整形把质心拉回真箫区间。
    """
    y = x
    if shelf_hz and shelf_db:
        b, a = butter(2, min(float(shelf_hz) / (sr / 2), 0.98), btype="high")
        y = y + (10.0 ** (float(shelf_db) / 20.0) - 1.0) * lfilter(b, a, y)
    if lp_hz and float(lp_hz) > 0:
        b, a = butter(int(lp_order), min(float(lp_hz) / (sr / 2), 0.98), btype="low")
        y = lfilter(b, a, y)
    return y


def _render_phrase(g, sr, dizi_bank, xiao_bank=None):
    """按乐句的 voice 渲染：实录笛走 DiziBank，实录箫走 XiaoBank。

    合成音源（dizi_note / xiao_phrase）只作显式 fallback 与诊断对照，
    默认不走此路——合成笛实测谐波滚降 −6.9 dB/oct、合成箫实测 582 个孤立谱峰
    （最高高出中位 181 dB），听感分别「不像笛子」与「发鬼」。
    """
    voice = g.get("voice", "dizi")
    if voice == "dizi" and dizi_bank is not None and dizi_bank.samples:
        return dizi_bank.phrase(g["notes"], sr, tau=float(g.get("tau", 3.1)),
                                glide_s=float(g.get("glide_ms", 42)) / 1000.0,
                                vib_cents=0.0,
                                rel_ms=float(g.get("rel_ms", 105.0)),
                                accent=g["accent"]) * float(g.get("gain", 1.0))
    if voice == "xiao" and xiao_bank is not None and xiao_bank.samples:
        return xiao_bank.phrase(g["notes"], sr, tau=float(g.get("tau", 3.2)),
                                glide_s=float(g.get("glide_ms", 55)) / 1000.0,
                                vib_cents=float(g.get("vib_cents", 14)),
                                rel_ms=float(g.get("rel_ms", 130.0)),
                                accent=g["accent"]) * float(g.get("gain", 1.0))
    return xiao_phrase(g["notes"], sr, tau=float(g.get("tau", 3.2)),
                       glide_s=float(g.get("glide_ms", 55)) / 1000.0,
                       vib_cents=float(g.get("vib_cents", 14)), vib_rate=4.8,
                       accent=g["accent"],
                       rel_ms=float(g.get("rel_ms", 130.0))) * float(g.get("gain", 1.0))


# 箫音色判据阈值（实测标定，见 docs/research 音乐研究报告 §6）
#   峰高突出度 = 带内最强谱峰高出中位的 dB 数：真实箫 38–62 dB（源样本 62），
#   旧正弦堆叠 173 dB。取 90 留双向余量。
#   谱平坦度 = 带内几何均值/算术均值：真实箫 1.0e-3–7.2e-3，正弦堆叠 7e-15，
#   相差约 11 个数量级。取 1e-4。
XIAO_PEAK_DB_MAX = 90.0
XIAO_FLATNESS_MIN = 1.0e-4


def _xiao_timbre_features(y, sr):
    """箫音色的两个可分辨特征：(谱峰最高突出度 dB, 谱平坦度)。"""
    n = min(len(y), sr)
    w = y[:n] * np.hanning(n)
    N = 1 << int(math.ceil(math.log2(2 * n)))
    S = np.abs(np.fft.rfft(w, N)) ** 2
    f = np.fft.rfftfreq(N, 1.0 / sr)
    m = (f > 200) & (f < 5000)
    S2 = S[m]
    med = float(np.median(S2))
    hi = 0.0
    for i in range(2, len(S2) - 2):
        if S2[i] > S2[i - 1] and S2[i] > S2[i + 1] and S2[i] > med:
            hi = max(hi, 10.0 * math.log10(S2[i] / max(med, 1e-30)))
    geo = math.exp(float(np.mean(np.log(np.maximum(S2, 1e-30)))))
    flat = geo / max(float(np.mean(S2)), 1e-30)
    return hi, flat


def xiao_timbre_checks(sr, groups, xiao_bank=None):
    """箫音色护栏（防「见鬼一样恐怖」）。

    那个问题的实测根因：合成箫是纯正弦堆叠 + 带通中心随音高上扫的噪声层。
    前者让听感像电子音（稀疏、锐利、无管腔感），后者在滑音时扫出一记啸叫。
    现在主奏已换成北箫实录（CC0 1.0），故断言施于实测音色：
    ① 谱峰不得稀疏如正弦（峰高突出度）；
    ② 谐波之间须有真实本底噪声（谱平坦度）——实录带气息与环境噪声，
       正弦堆叠在谐波之间近乎全空。

    已废弃的判据「泛音非等距度」：原先假设真实管乐器模态比非整数倍，
    但实测这份北箫源样本的泛音偏差只有 0.8 音分，与正弦堆叠的 0.3 音分
    不可分——该判据对本素材不成立（此前它测的是次声垃圾才「通过」），故移除。
    """
    if not groups:
        return []
    fails = []
    g0 = groups[0]
    y = _render_phrase(g0, sr, None, xiao_bank)
    hi, flat = _xiao_timbre_features(y, sr)
    ok = hi <= XIAO_PEAK_DB_MAX
    print(f"    箫谱峰最高突出度: {hi:.1f} dB 高于中位"
          f"（≤{XIAO_PEAK_DB_MAX:.0f}；正弦堆叠实测 173）" + ("  ✓" if ok else "  ✗"))
    if not ok:
        fails.append(f"箫频谱退化为纯正弦（峰高达中位 {hi:.0f} dB "
                     f"> {XIAO_PEAK_DB_MAX:.0f}），听感会发「鬼」")
    ok2 = flat >= XIAO_FLATNESS_MIN
    print(f"    箫谐波间本底噪声（谱平坦度）: {flat:.2e}"
          f"（≥{XIAO_FLATNESS_MIN:.0e}；正弦堆叠实测 7e-15）" + ("  ✓" if ok2 else "  ✗"))
    if not ok2:
        fails.append(f"箫谐波之间近乎全空（谱平坦度 {flat:.2e} "
                     f"< {XIAO_FLATNESS_MIN:.0e}），像正弦堆叠而非实录管乐")
    return fails


def xiao_timbre_negative(sr, groups):
    """负向：旧的正弦堆叠版必须被判失败，证明护栏非空。

    复原旧实现（整数倍正弦 + 带通中心随音高上扫）后重跑同一断言。
    """
    if not groups:
        return []
    fails = []
    g0 = groups[0]
    notes = g0["notes"]
    t = np.arange(int((sum(d for d, _ in notes) + 0.2) * sr)) / sr
    fs = [f for _d, f in notes]
    times = np.concatenate([[0.0], np.cumsum([d for d, _ in notes[:-1]])])
    logf = np.interp(t, np.concatenate([times, [times[-1]]]),
                     np.concatenate([np.log2(fs), [np.log2(fs[-1])]]))
    ftr = np.power(2.0, logf)
    ph = 2.0 * math.pi * np.cumsum(ftr) / sr
    old = np.zeros(len(t))
    for k in range(1, 6):
        old += (1.0 / k ** 1.8) * np.sin(k * ph)
    rng = np.random.default_rng(11)
    br = rng.standard_normal(len(t))
    b1, a1 = butter(2, np.clip(ftr * 1.6, 200.0, 4200.0) / (sr / 2), "band")
    old += 0.15 * lfilter(b1, a1, br)
    hi, flat = _xiao_timbre_features(old, sr)
    ok = hi > XIAO_PEAK_DB_MAX
    ok2 = flat < XIAO_FLATNESS_MIN
    print(f"    负向（旧正弦堆叠版）峰高突出度: {hi:.1f} dB（应 >{XIAO_PEAK_DB_MAX:.0f}）"
          + ("  ✓" if ok else "  ✗"))
    print(f"    负向（旧正弦堆叠版）谱平坦度: {flat:.2e}（应 <{XIAO_FLATNESS_MIN:.0e}）"
          + ("  ✓" if ok2 else "  ✗"))
    if not ok:
        fails.append(f"箫峰高护栏无区分力：旧正弦堆叠版（峰高 {hi:.0f} dB）仍判通过")
    if not ok2:
        fails.append(f"箫本底噪声护栏无区分力：旧正弦堆叠版（平坦度 {flat:.2e}）仍判通过")
    return fails


def legato_checks(sr, dizi_bank, groups, xiao_bank=None):
    """连奏护栏：证明笛声部真的是「一乐句一次起音」而非逐字风琴。

    口径：量笛乐句的短时 RMS 包络（40ms 窗 / 10ms 跳），数显著下凹（谷）密度。
    逐字独立起音 + 独立释放在 0.3s 间隔下会切出与字数相当的深谷；连奏后谷只出现在换气处。
    """
    if not groups or (dizi_bank is None and xiao_bank is None):
        return []
    fails = []
    g0 = groups[0]
    y = _render_phrase(g0, sr, dizi_bank, xiao_bank)
    n = len(y)
    hop, wn = max(int(0.010 * sr), 1), max(int(0.040 * sr), 1)
    env = np.array([float(np.sqrt(np.mean(y[i:i + wn] ** 2)))
                    for i in range(0, max(n - wn, 1), hop)])
    env_db = 20.0 * np.log10(env + 1e-9)
    dips = 0
    for i in range(2, len(env_db) - 2):
        if max(env_db[i - 2:i + 3].max() - env_db[i], 0.0) > 4.0:
            dips += 1
    span = n / sr
    rate = dips / max(span, 1e-6)
    ok = rate <= 4.5
    print(f"    连奏起伏密度: {dips} 次 / {span:.2f}s = {rate:.1f} 次每秒（≤4.5）"
          f"，本句 {g0['n']} 字" + ("  ✓" if ok else "  ✗"))
    if not ok:
        fails.append(f"笛连奏起伏密度 {rate:.1f} 次每秒 > 4.5（听感会回到逐字风琴）")
    body = y[:int((span - 0.15) * sr)]
    if len(body) > wn:
        floor = db(float(np.min(np.convolve(np.abs(body), np.ones(wn) / wn, mode="valid"))), -60)
        ok2 = floor > -46.0
        print(f"    乐句内最低瞬时电平: {floor:.1f} dBFS（>-46，连绵不断气）"
              + ("  ✓" if ok2 else "  ✗"))
        if not ok2:
            fails.append(f"笛乐句内出现近静默（{floor:.1f} dBFS），连奏被切断")
    return fails


def legato_negative(sr, dizi_bank, groups):
    """负向：逐字独立起音（不走 phrase）必须被判失败，证明护栏非空。"""
    if not groups or dizi_bank is None:
        return []
    g0 = groups[0]
    parts, t = [], 0.0
    note_fn = (dizi_bank.note if g0.get("voice") == "dizi" and dizi_bank is not None
               else (lambda f, d, **kw: xiao_note(f, d, sr, seed=7)))
    for (d, f) in g0["notes"]:
        yi = note_fn(f, d, tau=2.6, fade_ms=6.0)
        yi = yi * read_ramp(len(yi), 120.0, sr)
        parts.append((t, yi))
        t += d
    n = max(int((t + 0.2) * sr), 8)
    y = np.zeros(n)
    for off, yi in parts:
        j = int(off * sr)
        k = min(len(yi), n - j)
        if k > 0:
            y[j:j + k] += yi[:k]
    hop, wn = max(int(0.010 * sr), 1), max(int(0.040 * sr), 1)
    env = np.array([float(np.sqrt(np.mean(y[i:i + wn] ** 2)))
                    for i in range(0, max(len(y) - wn, 1), hop)])
    env_db = 20.0 * np.log10(env + 1e-9)
    dips = sum(1 for i in range(2, len(env_db) - 2)
               if max(env_db[i - 2:i + 3].max() - env_db[i], 0.0) > 4.0)
    rate = dips / max(len(y) / sr, 1e-6)
    ok = rate > 4.5
    print(f"    负向（逐字独立起音 {g0['n']} 字）起伏密度: {rate:.1f} 次每秒（应 >4.5）"
          + ("  ✓" if ok else "  ✗"))
    if not ok:
        return [f"笛连奏护栏是空断言：逐字独立起音（{rate:.1f} 次每秒）仍判通过"]
    return []


def dizi_timbre_checks(sr, dizi_bank):
    """笛音色护栏：实录渲染音的频谱包络须贴近源样本。

    这条断言正是为了钉死「笛主奏听起来完全不是笛子」那个回归：
    合成笛的泛音过密、包络形状与真实吹奏差得远，必然被这里判失败。
    """
    fails = []
    for src in dizi_bank.samples[::6]:          # 抽样若干条覆盖全音域
        y = dizi_bank.note(src["f0"], 1.0, tau=2.6)
        d = env_distance(y, src["x"], sr)
        ok = d <= ENV_DIST_MAX
        print(f"    笛 {src['note'] or src['label']} 包络距离: {d:.2f} dB"
              f"（≤{ENV_DIST_MAX}，源 {src['label']}）" + ("  ✓" if ok else "  ✗"))
        if not ok:
            fails.append(f"笛 {src['label']} 音色偏离实录 {d:.2f} dB > {ENV_DIST_MAX}")
    # 与合成笛的对照：合成笛必须明显更远，否则说明护栏不具区分力
    if dizi_bank.samples:
        s0 = dizi_bank.samples[len(dizi_bank.samples) // 2]
        d_syn = env_distance(dizi_note(s0["f0"], 1.0, sr, seed=6), s0["x"], sr)
        ok = d_syn > ENV_DIST_MAX
        print(f"    对照·合成笛对同一源样本包络距离: {d_syn:.2f} dB（应 >{ENV_DIST_MAX}）"
              + ("  ✓" if ok else "  ✗"))
        if not ok:
            fails.append(f"笛音色护栏无区分力：合成笛包络距离 {d_syn:.2f} dB 仍判通过")
    return fails


def register_checks(plan, meta, lead_bank, lead_key, label):
    """音区护栏（防「主奏被整体移调，音色垮掉、听感只剩支持层」）。

    这条断言钉死的是用户实际报的问题：「静夜思/白帝城 只听到琴或者筝」。
    实测根因不在响度（主奏其实比支持层高 4–7 dB，根本没被盖住），
    而在**采样库音区与旋律音区差了约一个八度**：北箫库真实音域是
    D5–A6，而旋律记在 C4–A4，取源平均要变调 +10 半音。变调超过
    ±3 半音后，吹管的管腔共振与气声结构就垮了，主奏在听感上「消失」。

    判据：旋律每个字到最近可用源的变调量不得超过 REGISTER_MAX_SEMI。
    这与「笛音色」「箫音色」那两条护栏互补——那两条量音色像不像，
    这条量音高迁就得多狠；音色护栏在大幅变调下也可能因为源本身被
    拉伸后包络仍然自洽而放过去。
    """
    fails = []
    if lead_bank is None or not getattr(lead_bank, "samples", None):
        return fails
    srcs = []
    for s in lead_bank.samples:
        if "f0_hz" in s:
            srcs.append(float(s["f0_hz"]))
        elif "f0" in s:
            srcs.append(float(s["f0"]))
    if not srcs:
        return fails

    gaps = []
    for t in meta.get("trace", []):
        if t.get("kind") not in (f"{lead_key}_legato", lead_key,
                                 f"{lead_key}_note"):
            continue
        f = t.get("f0")
        if not f:
            continue
        gaps.append(min(abs(12.0 * math.log2(f / c)) for c in srcs))
    if not gaps:
        return fails
    med = sorted(gaps)[len(gaps) // 2]
    worst = max(gaps)
    ok = worst <= REGISTER_MAX_SEMI
    print(f"    {label}库音域 {min(srcs):.0f}–{max(srcs):.0f} Hz · "
          f"旋律变调 中位 {med:.2f} / 最大 {worst:.2f} 半音"
          f"（须 ≤{REGISTER_MAX_SEMI}）" + ("  ✓" if ok else "  ✗"))
    if not ok:
        fails.append(
            f"{label}旋律最大变调 {worst:.2f} 半音 > {REGISTER_MAX_SEMI}："
            f"主奏被整体移调出采样库音区，音色已不是该乐器"
            f"（修法：把旋律记在素材真实音区，而非加大变调硬拗）")
    return fails


def realization_checks(sr, meta, lead_bank, lead_key, label):
    """处方兑现护栏：渲染出的主奏，实测音高须落在声法表写的音高上。

    为什么必须有这条：register_checks 量的是**处方**（旋律到最近采样源的变调量），
    不是**兑现**（渲染音频的实际音高）。实测踩过的坑——采样器读指针步长写成
    cumsum(ratio)/sr（多除了一个采样率），处方完全正确，但渲染出的整条旋律
    掉进 <80Hz 的次声区、主奏听不见，只剩支持层（用户报「只听到琴或者筝」）。
    当时所有旧护栏都通过，因为没有一条去看渲染音频的实际音高。

    做法：对每个乐句用其中位音高做「稳态探针」（同音重复两拍，避免滑音干扰
    f0 检测），实测 f0 与处方音高比对。
    """
    groups = meta.get("dizi_legato_groups") or []
    if not groups or lead_bank is None or not getattr(lead_bank, "samples", None):
        return []
    fails = []
    devs = []
    for g in groups:
        fs = [f for _d, f in g["notes"]]
        if not fs:
            continue
        mid = math.exp(sum(math.log(max(f, 1e-6)) for f in fs) / len(fs))
        y = lead_bank.phrase(
            [(0.8, mid), (0.8, mid)], sr,
            tau=float(g.get("tau", 3.2)),
            glide_s=float(g.get("glide_ms", 55.0)) / 1000.0,
            vib_cents=0.0,
            rel_ms=float(g.get("rel_ms", 130.0)),
            accent=[1.0, 1.0])
        f0 = detect_f0(y, sr, t0=0.30, t1=0.80, lo=100.0, hi=2500.0)
        if f0 > 0:
            devs.append(1200.0 * math.log2(f0 / mid))
    if not devs:
        return [f"{label}渲染音高无法测量：稳态探针检不出基频，主奏很可能没出声"]
    worst = max(abs(d) for d in devs)
    med = sorted(abs(d) for d in devs)[len(devs) // 2]
    ok = worst <= REALIZATION_TOL_CENTS
    print(f"    {label}渲染音高兑现：{len(devs)} 句稳态探针，实测偏差 "
          f"中位 {med:.1f} / 最大 {worst:.1f} 音分"
          f"（须 ≤{REALIZATION_TOL_CENTS:.0f}）" + ("  ✓" if ok else "  ✗"))
    if not ok:
        fails.append(f"{label}渲染音高未兑现：实测偏差最大 {worst:.1f} 音分 "
                     f"> {REALIZATION_TOL_CENTS:.0f}，主奏被渲染到错误音区（听不见）")
    return fails


def realization_negative(sr, meta, lead_bank, lead_key):
    """证明「处方兑现」护栏可失败：复现旧 bug（读指针多除一个 sr）后必须被判失败。"""
    groups = meta.get("dizi_legato_groups") or []
    if not groups or lead_bank is None or not getattr(lead_bank, "samples", None):
        return []
    orig = lead_bank.phrase

    def buggy(notes, sr_, **kw):
        y = orig(notes, sr_, **kw)
        idx = np.arange(len(y)) / float(sr_)      # 复现「多除一个 sr」：播放慢 sr 倍
        return np.interp(idx, np.arange(len(y)), y)

    lead_bank.phrase = buggy
    try:
        f = realization_checks(sr, meta, lead_bank, lead_key, lead_key)
    finally:
        lead_bank.phrase = orig
    if f:
        print("  ✓ 自检通过：兑现护栏可失败（复现旧 bug 后如实判失败）")
    else:
        return ["兑现护栏是空断言：复现旧 bug（读指针多除 sr）后仍判通过"]
    return []


def timbre_negative(sr, bank):
    """证明音色护栏可失败：宽带白噪「滴答」（正是要防的电子打点）必须被判失败。"""
    pool = bank.pool.get("san") or []
    if not pool:
        return []
    n = int(1.0 * sr)
    t = np.arange(n) / sr
    click = np.random.default_rng(0).normal(0, 1, n) * np.exp(-t / 0.05)
    d = env_distance(click, pool[0]["x"], sr)
    print(f"    负向（白噪「滴答」）包络距离: {d:.2f} dB（应 >{ENV_DIST_MAX}）")
    if d <= ENV_DIST_MAX:
        return [f"音色护栏是空断言：白噪「滴答」（包络距离 {d:.2f} dB）仍判通过"]
    return []


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="jx")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    plan_path = ROOT / "data" / "source" / "d3" / f"{args.pid}_music.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sr = int(plan["mix"]["sr"])

    bank = sampler.Bank(sr)          # 真实古琴干声（GuqinSonGest, CC BY 4.0）
    dizi_bank = sampler.DiziBank(sr)  # 真实笛干声（Hypnotriod, CC0 1.0）
    xiao_bank = sampler.XiaoBank(sr)  # 真实箫干声（pattingthestar, CC0 1.0）
    khim_bank = sampler.KhimBank(sr)  # 真实扬琴干声（pattingthestar, CC0 1.0）
    guzheng_bank = sampler.GuzhengBank(sr)  # 真实古筝干声（Pufermufin, CC0 1.0）
    mix, meta = build(plan, sr, bank=bank, dizi_bank=dizi_bank,
                      xiao_bank=xiao_bank, khim_bank=khim_bank,
                      guzheng_bank=guzheng_bank)
    m = measure(mix, sr, plan)
    print(f"[{args.pid}] 声法表 {plan_path.relative_to(ROOT)}  v{plan['meta']['version']}")
    print(f"  调式 {plan['mode']['name']}（{plan['mode']['tonic']}）· 板式 {plan['meter']['name']}"
          f" · 结构 {' → '.join(s['seg'] for s in plan['structure'])}")
    print(f"  时长 {m['duration_s']}s ｜ 峰值 {m['peak_dbfs']} dBFS ｜ RMS {m['rms_dbfs']} ｜ 波峰因数 {m['crest_db']} dB")
    print(f"  最长静默 {m['longest_gap_s']}s（≤{plan['checks']['max_gap_s']}）"
          f" ｜ 静默合计 {m['gap_total_s']}s（占比 {m['gap_ratio']}，门限 {m['gap_floor_dbfs']} dBFS）")
    for g in m["gaps"]:
        print(f"    [{g[0]} → {g[1]}]")
    print(f"  逐字起音(s): " + " ".join(f"{k}={v}" for k, v in list(meta["onsets"].items())[:5]) + " …")
    if meta.get("dizi_legato_groups"):
        VN = {"dizi": "笛", "xiao": "箫"}
        gv = meta["dizi_legato_groups"][0].get("voice", "dizi")
        print(f"  {VN.get(gv, gv)}乐句连奏（{len(meta['dizi_legato_groups'])} 句，每句一次起音）：")
        for d in meta["dizi_legato_groups"]:
            print(f"    {d['onset']:>6.2f}s  {d['chars']}  {d['n']}字 {d['dur_s']:.2f}s")
    if meta.get("dizi_octave_flags"):
        print("  ⚠ 采样库八度自检（以实测 f0 为准，不影响输出音高）："
              + ", ".join(f"{d['label']}→{d['note']} 差{d['octave_off']:+d}八度"
                          for d in meta["dizi_octave_flags"]))

    # 支持层取源（扬琴 / 古筝）：打印源音高与变调量，便于核对是否被
    # 过度变调拉薄。调内吸附的偏差也一并列出——五声音阶素材上这一项
    # 若超过 snap_cents（80），说明该音不在素材的调内。
    GN = {"khim": "扬琴", "guzheng": "古筝"}
    for t in meta.get("guest_src", []):
        if t.get("snap_dev_cents") is None:
            extra = ""
        elif t.get("in_scale"):
            extra = "，调内"
        else:
            extra = (f"，⚠ 调外（最近调内音差 {t['snap_dev_cents']:.0f} 音分，"
                     f"靠变调补足）")
        print(f"  {GN.get(t['kind'], t['kind'])}轻点 {t['line']}-{t['pos']}："
              f"{t['f0']:.1f}Hz ← {t['src']} 变调 {t['transpose_semi']:+.2f} 半音"
              f"{extra}")
    for fb in meta.get("bank_fallback", []):
        print(f"  ⚠ 采样库退路 {fb['line']}-{fb['pos']}："
              f"想要 {fb['want']}，实得 {fb['used']}（{fb['note']}）")

    if not args.check and not args.selftest:
        out = Path(args.out) if args.out else ROOT / "dist" / "audio" / "music" / f"{args.pid}.wav"
        if not out.is_absolute():
            out = ROOT / out          # 相对路径按仓库根解析，避免 relative_to 报错
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), mix, sr, subtype="PCM_16")
        try:
            shown = out.relative_to(ROOT)
        except ValueError:
            shown = out
        print(f"  → {shown}  ({out.stat().st_size/1024:.0f} KB)")
        return

    fails = check(m, plan)
    if args.check:
        print("  单元「处方兑现」：")
        fails += unit_checks(sr, bank, dizi_bank)
        print("  音色护栏（防「电子滴答」）：")
        fails += timbre_checks(sr, bank)
        if dizi_bank.samples:
            print("  笛音色护栏（防「不像笛子」）：")
            fails += dizi_timbre_checks(sr, dizi_bank)
        if meta.get("dizi_legato_groups"):
            print("  连奏护栏（防「一字一声」）：")
            fails += legato_checks(sr, dizi_bank, meta["dizi_legato_groups"],
                                   xiao_bank)
            gv = meta["dizi_legato_groups"][0].get("voice")
            if gv == "xiao":
                print("  箫音色护栏（防「发鬼」）：")
                fails += xiao_timbre_checks(sr, meta["dizi_legato_groups"],
                                            xiao_bank)
        # 音区护栏：主奏旋律不得被大幅移调去迁就采样库（防「只听到支持层」）
        _lead = plan.get("instrument", {}).get("lead")
        if _lead == "xiao" and xiao_bank is not None and xiao_bank.samples:
            print("  音区护栏（防「主奏被移调出素材音区」）：")
            fails += register_checks(plan, meta, xiao_bank, "xiao", "箫")
        elif _lead == "dizi" and dizi_bank is not None and dizi_bank.samples:
            print("  音区护栏（防「主奏被移调出素材音区」）：")
            fails += register_checks(plan, meta, dizi_bank, "dizi", "笛")
        # 处方兑现：渲染音频的实际音高必须等于声法表处方（register_checks 只管处方量）
        if _lead == "xiao" and xiao_bank is not None and xiao_bank.samples:
            print("  处方兑现护栏（防「渲染音高掉出音区」）：")
            fails += realization_checks(sr, meta, xiao_bank, "xiao", "箫")
        elif _lead == "dizi" and dizi_bank is not None and dizi_bank.samples:
            print("  处方兑现护栏（防「渲染音高掉出音区」）：")
            fails += realization_checks(sr, meta, dizi_bank, "dizi", "笛")
        if fails:
            print("  ✗ 断言失败：")
            for f in fails:
                print("    - " + f)
            sys.exit(1)
        print("  ✓ 全部断言通过")

    if args.selftest:
        # 负向扰动：抹掉一段 → 连续性断言必须失败（否则是永远通过的「空断言」）
        mut = tuple(float(x) for x in plan["anchor"]["breath_windows"][1])
        bad, _ = build(plan, sr, perturb_mute=mut, bank=bank, dizi_bank=dizi_bank)
        mb = measure(bad, sr, plan)
        fb = [f for f in check(mb, plan) if "最长静默" in f]
        if fb:
            print(f"  ✓ 自检通过：抹掉 {mut} 后连续性断言如期失败（{fb[0]}）")
        else:
            print("  ✗ 自检失败：扰动后连续性断言仍通过 → 该断言是空断言")
            sys.exit(1)
        # 负向扰动：合成器单元断言也必须可失败
        nf = unit_negative(sr, bank, dizi_bank)
        if nf:
            print("  ✗ 自检失败：单元断言为空断言：")
            for f in nf:
                print("    - " + f)
            sys.exit(1)
        print("  ✓ 自检通过：单元断言可失败（音高 / 走手音均为非空断言）")
        # 负向扰动：音色护栏也必须可失败
        tf = timbre_negative(sr, bank)
        if tf:
            print("  ✗ 自检失败：音色护栏为空断言：")
            for f in tf:
                print("    - " + f)
            sys.exit(1)
        print("  ✓ 自检通过：音色护栏可失败（宽带白噪「滴答」被判失败）")
        # 负向扰动：连奏护栏也必须可失败
        if meta.get("dizi_legato_groups"):
            lf = legato_negative(sr, dizi_bank, meta["dizi_legato_groups"])
            if lf:
                print("  ✗ 自检失败：连奏护栏为空断言：")
                for f in lf:
                    print("    - " + f)
                sys.exit(1)
            print("  ✓ 自检通过：连奏护栏可失败（逐字独立起音被判失败）")
        if meta.get("dizi_legato_groups") and meta["dizi_legato_groups"][0].get("voice") == "xiao":
            xf = xiao_timbre_negative(sr, meta["dizi_legato_groups"])
            if xf:
                print("  ✗ 自检失败：箫音色护栏为空断言：")
                for f in xf:
                    print("    - " + f)
                sys.exit(1)
            print("  ✓ 自检通过：箫音色护栏可失败（旧正弦堆叠版被判失败）")
        # 负向扰动：处方兑现护栏也必须可失败
        _lead_s = plan.get("instrument", {}).get("lead")
        if _lead_s == "xiao" and xiao_bank is not None and xiao_bank.samples:
            rf = realization_negative(sr, meta, xiao_bank, "xiao")
        elif _lead_s == "dizi" and dizi_bank is not None and dizi_bank.samples:
            rf = realization_negative(sr, meta, dizi_bank, "dizi")
        else:
            rf = []
        if rf:
            print("  ✗ 自检失败：兑现护栏为空断言：")
            for f in rf:
                print("    - " + f)
            sys.exit(1)


if __name__ == "__main__":
    main()
