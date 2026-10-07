#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D3 采样播放器（示范 · 江雪）

用 GuqinSonGest（CC BY 4.0，Zenodo 14962054）真实古琴「接触麦」干声替代
music_render.py 里的合成音源（Karplus-Strong 拨弦 / 加性泛音）。

为什么替换：合成拨弦的激励是宽带白噪，音头上升 <1 ms，听感即「电子滴答」；
真实录音不存在这个瞬态（详见 _archive/_scratch_diag_2026-10-05 的盲听与频谱诊断）。

接口与合成器保持一致，渲染器只换音源、声法表与装配逻辑不动：

    bank = Bank(sr)                       # 载入 samples/manifest.json
    y = bank.note("san", f0, dur, tau=2.2, ...)   # 返回单位峰值波形

音色档 kind ∈ {san, an, vib, gli, fan}：
  · san 散音：长散音（空弦干声）
  · an  按音：短按音（各徽位干声）
  · vib 吟猱：真实颤吟干声（用于 expr == nao）
  · gli 走手音：真实绰/注滑音干声（用于 expr == chuo/zhu）
  · fan 泛音：钟磬式泛音阶梯（str1 各徽位 + 其它弦）
音高一律以「就近源 + 重采样变调」兑现；变调比 = f0_target / f0_source。

本数据集（GuqinSonGest）只有一根空弦（G2）的散/按干声，泛音覆盖 C3–C5。
故取源有两级：先在本音色档内就近取；若所需变调超过 max_semi（默认 12 半音 ≈ 一个八度），
则回退到「全池就近」，宁可换音色档也不让音色被过度变调拖薄（实测：G2 散音升到 C4 以上，
>4k/<0.8k 能量比升到 1.5–2.0，音色变尖）。回退事件在 meta 里登记，便于溯源。

另有 DiziBank 播放笛实录（Hypnotriod, Freesound pack 21613, CC0 1.0）：

    dbank = DiziBank(sr)                 # 载入 dizi/manifest.json
    y = dbank.note(f0, dur, tau=...)     # 笛主奏（早发白帝城）

以及 XiaoBank 播北箫实录（pattingthestar, CC0 1.0，由 Beixiao-Raw.sf2 切出）：

    xbank = XiaoBank(sr)                 # 载入 xiao/manifest.json
    y = xbank.phrase(notes, sr)          # 箫主奏（静夜思），连奏乐句

另有 KhimBank（扬琴，替代「古琴代琵琶」）与 GuzhengBank（古筝，替代
「古琴代筝」）两只拨弦库。两者都是单音拨弦，接口刻意对齐（pick/note），
差别在衰减长度与调性约束：

    gbank = GuzhengBank(sr)              # 载入 guzheng/manifest.json
    y, info = gbank.note(f0, dur, return_info=True)
"""
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "source" / "d3" / "samples"
DIZI = ROOT / "data" / "source" / "d3" / "dizi"
XIAO = ROOT / "data" / "source" / "d3" / "xiao"
KHIM = ROOT / "data" / "source" / "d3" / "khim"
GUZHENG = ROOT / "data" / "source" / "d3" / "guzheng"


# ---------------------------------------------------------------- 基础工具

def highpass(x, sr, fc=35.0):
    """一阶高通：去直流与低频手噪（接触麦录音常带 20 Hz 以下的晃动）。"""
    if len(x) < 8:
        return x
    c = math.exp(-2.0 * math.pi * fc / sr)
    return lfilter([c, -c], [1.0, -c], x)


def onset_index(x, sr, rel=0.06, back_ms=4.0):
    """起音点：包络首次超过 rel×峰值处，向前回退 back_ms 以保住拨弦瞬态。"""
    k = max(int(0.002 * sr), 1)
    env = np.convolve(np.abs(x), np.ones(k) / k, mode="same")
    pk = float(env.max()) if len(env) else 0.0
    if pk <= 0.0:
        return 0
    idx = np.where(env > rel * pk)[0]
    if len(idx) == 0:
        return 0
    return max(int(idx[0] - back_ms / 1000.0 * sr), 0)


def resample(x, sr_in, sr_out):
    if sr_in == sr_out or len(x) < 2:
        return x
    n = int(round(len(x) * sr_out / sr_in))
    pos = np.arange(n) * (sr_in / sr_out)
    return np.interp(pos, np.arange(len(x)), x)


def read_ramp(n, ms, sr):
    """末段升余弦释放（顿）。与 music_render.read_ramp 同口径。"""
    k = min(int(ms / 1000.0 * sr), n)
    env = np.ones(n)
    if k > 1:
        env[n - k:] = 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / (k - 1)))
    return env


# ---------------------------------------------------------------- 采样库

class Bank:
    """载入 manifest.json 里的干声，按音色档建池，提供就近取源与变调播放。"""

    def __init__(self, sr, manifest=SAMPLES / "manifest.json"):
        man = json.loads(Path(manifest).read_text(encoding="utf-8"))
        self.license = man["license"]
        self.sr = int(sr)
        self.pool = {"san": [], "an": [], "vib": [], "gli": [], "fan": []}
        self.fallback_log = []          # 记录「档内变调超阈 → 回退全池」的事件
        for s in man["samples"]:
            lab = s["label"]
            if lab.startswith("vib_"):
                kind = "vib"            # 真实颤吟单独成池（expr == nao）
            elif lab.startswith("gli_"):
                kind = "gli"            # 真实走手音单独成池（expr == chuo/zhu）
            else:
                kind = s["technique"]
            if kind not in self.pool:
                continue
            p = SAMPLES / s["file"]
            if not p.exists():
                continue
            data, sr_in = sf.read(str(p), always_2d=True)
            x = data.mean(axis=1).astype(np.float64)
            x = highpass(x - float(np.mean(x)), sr_in)
            x = resample(x, sr_in, self.sr)
            x = x[onset_index(x, self.sr):]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            if pk > 0:
                x /= pk
            self.pool[kind].append({
                "label": lab, "x": x, "f0": float(s["f0_hz"]),
                "note": s.get("note", ""), "dur": len(x) / self.sr,
                "member": s["member"],
            })
        for k in self.pool:
            self.pool[k].sort(key=lambda d: d["f0"])

    def _best(self, cands, f0, need_s):
        best, best_key = None, None
        for c in cands:
            semi = abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6)))
            ratio = f0 / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1          # 长度不足者排后
            key = (round(semi, 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        return best

    def pick(self, kind, f0, need_s=0.0, max_semi=None):
        """就近取源：档内优先；若档内最近源的变调超过 max_semi，回退到全池就近。"""
        best = self._best(self.pool.get(kind, []), f0, need_s)
        if best is None:
            return self._best([c for v in self.pool.values() for c in v], f0, need_s)
        if max_semi is not None:
            semi = abs(12.0 * math.log2(f0 / max(best["f0"], 1e-6)))
            if semi > max_semi:
                alt = self._best([c for v in self.pool.values() for c in v], f0, need_s)
                if alt is not None and alt is not best:
                    self.fallback_log.append(
                        {"want": kind, "f0": round(f0, 1), "got": alt["label"],
                         "semi": round(12.0 * math.log2(f0 / max(alt["f0"], 1e-6)), 2)})
                    return alt
        return best

    def note(self, kind, f0, dur, tau, sr=None, vib_cents=0.0, vib_rate=0.0,
             glide_from_semi=0.0, glide_time=0.0, dun_ms=None, fade_ms=5.0,
             seed=0, max_semi=None):
        """按处方播放一个音：就近取源 → 变调（可含走手音/吟猱调制）→ 施加衰减与顿。"""
        sr = int(sr or self.sr)
        n_out = max(int(dur * sr), 8)
        src = self.pick(kind, f0, need_s=dur, max_semi=max_semi)
        x = src["x"]
        base = f0 / max(src["f0"], 1e-6)

        t = np.arange(n_out) / sr
        semi = np.zeros(n_out)
        if glide_time > 0.0:
            g = np.clip(1.0 - t / glide_time, 0.0, 1.0)
            semi += glide_from_semi * g
        if vib_cents:
            semi += (vib_cents / 100.0) * np.sin(2.0 * math.pi * vib_rate * t)
        ratio = base * np.power(2.0, semi / 12.0)
        pos = np.concatenate([[0.0], np.cumsum(ratio[:-1])])
        last = len(x) - 2
        if last <= 0:
            return np.zeros(n_out)
        pos = np.clip(pos, 0.0, last)
        y = np.interp(pos, np.arange(len(x)), x)
        # 源不够长（变调比大、音符又长）时在耗尽处 20 ms 内淡出，不复制末样（否则成直流「噗」）
        tail = np.clip((last - pos) / (0.020 * sr), 0.0, 1.0)
        y *= tail

        y *= np.exp(-t / max(tau, 1e-3))                     # 声法表 decay_tau
        if dun_ms:
            y *= read_ramp(n_out, float(dun_ms), sr)
        else:
            k = min(int(fade_ms / 1000.0 * sr), n_out)
            if k > 1:
                y[n_out - k:] *= np.linspace(1.0, 0.0, k)
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        return y


def load(sr):
    return Bank(sr)


# ---------------------------------------------------------------- 笛：真实干声

class XiaoBank:
    """北箫实录采样库（pattingthestar, CC0 1.0，见 manifest 的 license 字段）。

    素材来自 Beixiao-Raw.sf2（NeoSoundFonts/pattingthestar-instruments），
    由 src/music/build_xiao.py 按包络事件切出：**7 个音高 D5–A6**，
    实测 f0 587–1760 Hz。许可 CC0 1.0（SF2 内 ICOP 字段亦写明
    "Creative Commons 0 1.0"），可再分发。

    为什么必须换掉合成箫：原 xiao_phrase 实测 582 个孤立谱峰（最高高出中位
    181 dB），本质是正弦堆叠；且气声带通中心跟随音高上扫（f×1.6），
    330→392 Hz 的滑音会扫出一记啸叫 → 听感「见鬼一样恐怖」。
    实录箫有真实管腔共振、气声与本底噪声（本库中位约 −13 dB）。

    **本库是「重新切分 + 八度偏低」的版本，早先的版本是错的**（详见
    manifest 的 name_field_unreliable 与 README）：
      · 早先按 shdr 的 16 个 name 严格等分，等分与真实发声不对齐
        （同名段 L 与 R 实测差整整 2×，而同期双麦必然同频）；
      · shdr name 标称 C4–D#5，是**低八度**的错标。已用谐波幅度序列
        逐点核对：每处谱线都从 h=1 起最强并逐次衰减，**没有缺失的基频**，
        故实测的 D5–A6 就是真实音高，name 不可采信。
    ⇒ 结论：这份实录是**高音区**的箫。旋律若写在 C4 一带，就得整体降
    10 半音去迁就它，音色会垮掉（《静夜思》此前正是如此，故听感上
    「只剩筝」）。正确做法是把旋律**记在素材真实音区**，见
    jys_music.json 的 register_note。
    """

    def __init__(self, sr, manifest=XIAO / "manifest.json"):
        p = Path(manifest)
        self.samples = []
        self.license = {}
        self.meta = {}
        self.sr = int(sr)
        if not p.exists():
            return
        man = json.loads(p.read_text(encoding="utf-8"))
        self.license = {"license": man.get("license", ""),
                        "author": man.get("author", ""),
                        "source": man.get("source", ""),
                        "url": man.get("url", "")}
        self.meta = man
        for smp in man["samples"]:
            f = XIAO / smp["file"]
            if not f.exists():
                continue
            data, sr_in = sf.read(str(f), always_2d=True)
            x = data.mean(axis=1).astype(np.float64)
            # 与笛库同口径：90Hz 高通拦掉实录低频轰鸣，不碰 f0≥260Hz 的基频
            x = highpass(x - float(np.mean(x)), sr_in, 90.0)
            x = resample(x, sr_in, self.sr)
            x = x[onset_index(x, self.sr):]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            if pk > 0:
                x /= pk
            self.samples.append({"label": smp["label"], "x": x,
                                "f0": float(smp["f0_hz"]),
                                "midi": int(smp["midi"]),
                                "dur": len(x) / self.sr})
        self.samples.sort(key=lambda d: d["f0"])

    def pick(self, f0, need_s=0.0, max_semi=None):
        """就近取源；变调超过 max_semi 者不取（避免强变调把音色拖薄）。"""
        best, best_key = None, None
        for c in self.samples:
            semi = abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6)))
            if max_semi is not None and semi > max_semi:
                continue
            ratio = f0 / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1
            key = (round(semi, 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        if best is None and self.samples:      # 全部超界时退回就近
            return min(self.samples,
                       key=lambda c: abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6))))
        return best

    def phrase(self, notes, sr, tau=3.2, glide_s=0.055, vib_cents=14.0,
               vib_rate=4.8, accent=None, rel_ms=130.0, atk_floor=0.42,
               max_semi=None, return_info=False):
        """连奏乐句：一次起音 + 换指滑音（与 DiziBank.phrase 同结构）。

        与逐字 note 的区别在于音高轨迹连续、共享一条积分相位，故不会
        「一声一声重新吹」。起音不从 0 起（atk_floor）——真实吹管换气后是
        「续上」，从 0 起会让每句开头「咯噔」一下（实测乐句边界落差
        −2.3～−6.5 dB，改为不从 0 起后收窄到 −1.4～−4.7 dB）。
        """
        sr = int(sr)
        notes = [(float(d), float(f)) for d, f in notes if d > 0]
        if not notes:
            return (np.zeros(8), None) if return_info else np.zeros(8)
        times = [0.0]
        for d, _f in notes[:-1]:
            times.append(times[-1] + d)
        body = times[-1] + notes[-1][0]
        total = body + max(rel_ms, 40.0) / 1000.0
        n = max(int(total * sr), 8)
        t = np.arange(n) / sr

        # 源样本按「乐句中位音高」选：整句共享一个源，音色才稳定
        fs = [f for _d, f in notes]
        mid = math.exp(sum(math.log(max(f, 1e-6)) for f in fs) / len(fs))
        src = self.pick(mid, need_s=body, max_semi=max_semi)
        if src is None:
            return (np.zeros(n), None) if return_info else np.zeros(n)
        x = src["x"]

        # 音高轨迹 knots：每个字处换指，滑音窗 = glide_s
        kt, kv = [0.0], [math.log2(max(fs[0], 1e-6))]
        for i, (d, f) in enumerate(notes):
            kt.append(times[i])
            kv.append(math.log2(max(f, 1e-6)))
            if i + 1 < len(notes):
                kt.append(min(times[i] + glide_s, times[i + 1]))
                kv.append(math.log2(max(f, 1e-6)))
        logf = np.interp(t, kt, kv)
        if vib_cents:
            # 气震渐入：真实吹管的揉音起音先稳再渐深
            logf = logf + (vib_cents / 1200.0) * np.minimum(t / 0.25, 1.0) * \
                np.sin(2.0 * math.pi * vib_rate * t)
        f_trk = np.power(2.0, logf)

        # 积分重采样：把音高轨迹兑现为对源样本的读指针。
        # 步长是「源样本数 / 输出样本」＝ f / f_src（无量纲），不能再除 sr——
        # 除 sr 会把播放速度压低 44100 倍，整条乐句掉进 <80Hz 的次声区而听不见。
        pos = np.clip(np.cumsum(f_trk) / max(src["f0"], 1e-6),
                      0.0, max(len(x) - 2, 1))
        y = np.interp(pos, np.arange(len(x)), x)
        tail = np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)
        y = y * tail

        env = np.ones(n)
        atk = min(int(0.055 * sr), n)
        fl = float(atk_floor)
        env[:atk] = fl + (1.0 - fl) * (
            0.5 * (1.0 - np.cos(math.pi * np.arange(atk) / max(atk, 1))))
        acc = accent or [1.0] * len(notes)
        for i, (d, _f) in enumerate(notes):
            if i == 0:
                continue
            # 咬字：字头前微微收气，再给明确凸起（单靠正向凸起在混响下测不到）
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
        k = min(int(rel_ms / 1000.0 * sr), n)
        if k > 1:
            y[n - k:] *= 0.5 * (1.0 + np.cos(math.pi * np.arange(k) / (k - 1)))
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        info = {"src": src["label"], "src_f0": src["f0"],
                "transpose_semi": 12.0 * math.log2(mid / max(src["f0"], 1e-6))}
        return (y, info) if return_info else y


class KhimBank:
    """扬琴实录采样库（pattingthestar, CC0 1.0，见 manifest 的 license 字段）。

    素材来自 Khim.sf2（NeoSoundFonts/pattingthestar-instruments），
    由 build_khim.py 切出：11 个音高 A3–D#6，每个音高含 L/R 两个麦克风位。
    扬琴是中国乐器，替掉原先「古琴代琵琶」的支持层比用古琴顶替更贴合。

    与笛/箫同为 Polyphone 转换产物，故有同一批坑：数值字段全坏、
    音高标记高一个八度。build_khim.py 已用「实测 f0 落在 name 标称
    的高八度附近则下移八度」的规则校正，manifest 的 f0_hz 是真实基频。

    拨弦音色的关键是**快速衰减**：实测起音瞬态中位 +9.5 dB
    （起音后 30ms 的 RMS 比 210ms 窗高 9.5 dB），与笛/箫的吹管音色
    （持续气声）形成层次差。note() 因此用短 tau + 顿音，而非吹管的连奏。
    """

    def __init__(self, sr, manifest=KHIM / "manifest.json"):
        p = Path(manifest)
        self.samples = []
        self.license = {}
        self.meta = {}
        self.sr = int(sr)
        if not p.exists():
            return
        man = json.loads(p.read_text(encoding="utf-8"))
        self.license = {"license": man.get("license", ""),
                        "author": man.get("author", ""),
                        "source": man.get("source", ""),
                        "url": man.get("url", "")}
        self.meta = man
        for smp in man["samples"]:
            f = KHIM / smp["file"]
            if not f.exists():
                continue
            data, sr_in = sf.read(str(f), always_2d=True)
            x = data.mean(axis=1).astype(np.float64)
            # 70Hz 高通（A3=220Hz 为最低音，取 70Hz 不碰基频）
            x = highpass(x - float(np.mean(x)), sr_in, 70.0)
            x = resample(x, sr_in, self.sr)
            x = x[onset_index(x, self.sr):]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            if pk > 0:
                x /= pk
            self.samples.append({"label": smp["label"], "x": x,
                                "f0": float(smp["f0_hz"]),
                                "midi": int(smp["midi"]),
                                "dur": len(x) / self.sr})
        self.samples.sort(key=lambda d: d["f0"])

    def pick(self, f0, need_s=0.0, max_semi=None):
        """就近取源；变调超过 max_semi 者不取（扬琴高把位变调会明显失真）。"""
        best, best_key = None, None
        for c in self.samples:
            semi = abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6)))
            if max_semi is not None and semi > max_semi:
                continue
            ratio = f0 / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1
            key = (round(semi, 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        if best is None and self.samples:
            return min(self.samples,
                       key=lambda c: abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6))))
        return best

    def note(self, f0, dur, tau=0.85, sr=None, dun_ms=None, fade_ms=90.0,
             max_semi=None, return_info=False):
        """单音拨弦：积分重采样变调 + 指数衰减 + 顿音。

        tau 短（0.85s）以还原扬琴的快速衰减；拨弦的余响比吹管短得多，
        用吹管的 tau 会让每个点都拖着一条混响尾巴，反而糊。
        """
        sr = self.sr if sr is None else int(sr)
        src = self.pick(f0, need_s=dur, max_semi=max_semi)
        if src is None:
            return (np.zeros(8), None) if return_info else np.zeros(8)
        x = src["x"]
        n = max(int(dur * sr), 8)
        t = np.arange(n) / sr
        ratio = f0 / max(src["f0"], 1e-6)
        # 步长＝f0/f_src（无量纲源样本/输出样本）；除 sr 会把音压进次声区
        pos = np.cumsum(np.full(n, ratio))
        pos = np.clip(pos, 0.0, max(len(x) - 2, 1))
        y = np.interp(pos, np.arange(len(x)), x)
        # 源耗尽处渐隐（20ms）。读指针被 clip 钉在源末尾后会「保持最后一个采样值」，
        # 那就是一段直流；再乘指数衰减包络即成低频轰鸣（实测 D#5 源仅 0.42s、
        # 请求 1.0s → 0.55s 直流，<80Hz 占输出能量 75%）。与 XiaoBank.phrase 同口径。
        y = y * np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)
        y = y * np.exp(-t / max(tau, 1e-3))
        if dun_ms:                     # 拨弦的「止弦」：短而干
            k = min(int(dun_ms / 1000.0 * sr), n)
            if k > 1:
                y[n - k:] *= 0.5 * (1.0 - np.cos(np.pi * np.arange(k) / (k - 1)))
        else:
            k = min(int(fade_ms / 1000.0 * sr), n)
            if k > 1:
                y[n - k:] *= 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / (k - 1)))
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        info = {"src": src["label"], "src_f0": src["f0"],
                "transpose_semi": 12.0 * math.log2(f0 / max(src["f0"], 1e-6))}
        return (y, info) if return_info else y


class GuzhengBank:
    """古筝实录采样库（Pufermufin, Freesound sound 396868, CC0 1.0）。

    这是深搜后唯一同时满足「真实古筝 + CC0 可再分发 + 覆盖足够」的
    公开资源，已排除 CCMUSIC（BY-NC-ND）、VCSL 合成 fxp、韩国 Gayageum
    （非古筝）。原录音 24:34 的一把 D 五声音阶古筝实录，由
    build_guzheng.py 切成 15 个单音（见 guzheng/manifest.json）。

    两条与笛/箫/扬琴都不同的性质，故 note() 不能照抄扬琴：

    ① **调性受限**：素材是 D 五声音阶，只有 D E F# A B 五个音级。
       取源不能只按音高就近，还必须先落在调内音级上——否则会把
       D# 当 D 变调，音准立刻露馅。故 pick() 里做「先吸附到最近调内
       音级，再就近取源」，snap_cents 之外判为调外。
    ② **素材带混响**：作者 tags 明写 reverb，实测「衰减到峰值下 40 dB」
       中位 1.21 s，远长于干拨弦的 0.3–0.6 s。build 阶段只做了截尾 +
       递增低通这类保守处理，并非真正的干湿分离，所以渲染层的混响
       wet 要相应调低（见 note 的 tau 注释）。

    拨弦的衰减比扬琴慢（古筝弦长、弦粗，余响更长），故 tau 默认取
    1.6s 而非扬琴的 0.85s。
    """

    def __init__(self, sr, manifest=GUZHENG / "manifest.json"):
        p = Path(manifest)
        self.samples = []
        self.license = {}
        self.meta = {}
        self.sr = int(sr)
        if not p.exists():
            return
        man = json.loads(p.read_text(encoding="utf-8"))
        self.license = {"license": man.get("license", ""),
                        "author": man.get("author", ""),
                        "source": man.get("source", ""),
                        "url": man.get("url", "")}
        self.meta = man
        # 调内音级集合（相对根音）= 素材的 D 五声音阶。写死在这里而
        # 不是解析 manifest 的 scale_filter 文本：那条是人读的描述，
        # 解析它等于给注释加一层解析器。改调式时这两处要一起改。
        off = {0, 2, 4, 7, 9}
        root = 2                                   # D 五声音阶
        for s in man.get("samples", []):
            f = GUZHENG / s["file"]
            if not f.exists():
                continue
            data, sr_in = sf.read(str(f), always_2d=True)
            x = data.mean(axis=1).astype(np.float64)
            # 60Hz 高通（最低音 D2=73Hz，取 60Hz 不碰基频）
            x = highpass(x - float(np.mean(x)), sr_in, 60.0)
            x = resample(x, sr_in, self.sr)
            x = x[onset_index(x, self.sr):]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            if pk > 0:
                x /= pk
            self.samples.append({"label": s["label"], "x": x,
                                "f0": float(s["f0_hz"]),
                                "midi": int(s["midi"]),
                                "dur": len(x) / self.sr,
                                "de_reverb": bool(s.get("de_reverb")),
                                "decay": float(s.get("decay_to_m40db_s", 0.0))})
        self.samples.sort(key=lambda d: d["f0"])
        self.off, self.root = off, root

    def _in_scale(self, midi):
        return (midi - self.root) % 12 in self.off

    def snap(self, f0, cents=80.0):
        """吸附到最近的调内音级。

        返回 (midi, 偏差音分, 是否在容差内)。注意即使**不**在容差内也
        返回真实的偏差音分——调用方要靠它区分「调内原生」和「调外硬变调」，
        返回 None 会把这个信息一起丢掉（曾因此把调外的 C5 误报成 0 偏差）。
        """
        m0 = int(round(12.0 * math.log2(max(f0, 1e-6) / 440.0) + 69))
        best = None
        for m in range(m0 - 2, m0 + 3):
            if not self._in_scale(m):
                continue
            nom = 440.0 * 2 ** ((m - 69) / 12.0)
            d = abs(1200.0 * math.log2(max(f0, 1e-6) / nom))
            if best is None or d < best[1]:
                best = (m, d)
        if best is None:
            return None
        return best[0], best[1], best[1] <= cents

    def pick(self, f0, need_s=0.0, max_semi=None, snap_cents=80.0):
        """就近取源，限调内音级。

        先把目标音高吸附到最近的调内音级（不去贴合源），再在调内源里
        按变调量就近取。这样音准偏差恒在 snap_cents 内，不会为了
        「少变调」而把 D# 拿来顶 D。

        返回 (源, 实际目标频率, 调内偏差音分, 偏差是否在容差内)。
        目标音本身调外时（如 D 调素材上的 C），snap 会失败——此时不
        强行改音高（那会破坏曲子的调式），而是保留原音高、如实报告
        偏差，让调用方知道这一点是靠变调硬补的。
        """
        sn = self.snap(f0, snap_cents)
        if sn is not None and sn[2]:
            tgt = 440.0 * 2 ** ((sn[0] - 69) / 12.0)
        else:
            tgt = f0                      # 调外音：保留原音高，不改调式
        dev = sn[1] if sn is not None else None
        in_tol = bool(sn[2]) if sn is not None else False
        best, best_key = None, None
        for c in self.samples:
            semi = abs(12.0 * math.log2(tgt / max(c["f0"], 1e-6)))
            if max_semi is not None and semi > max_semi:
                continue
            ratio = tgt / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1
            key = (round(semi, 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        if best is None and self.samples:
            best = min(self.samples,
                       key=lambda c: abs(12.0 * math.log2(tgt / max(c["f0"], 1e-6))))
        if best is None:
            return None, tgt, dev, in_tol
        return best, tgt, dev, in_tol

    def note(self, f0, dur, tau=1.6, sr=None, dun_ms=None, fade_ms=140.0,
             max_semi=None, snap_cents=80.0, return_info=False):
        """单音拨弦：调内吸附取源 + 积分重采样变调 + 指数衰减 + 止弦/淡出。

        tau 比扬琴长（1.6s vs 0.85s）：古筝弦长弦粗，余响本就比扬琴慢。
        但素材带混响，衰减尾巴里混着环境声，故仍不宜取更长——这里
        的取舍是「保住拨弦芯、把混响尾巴留给混响器」，而不是让混响
        在采样里就活两遍。
        """
        sr = self.sr if sr is None else int(sr)
        src, tgt, snap_dev, in_tol = self.pick(f0, need_s=dur, max_semi=max_semi,
                                                snap_cents=snap_cents)
        if src is None:
            return (np.zeros(8), None) if return_info else np.zeros(8)
        x = src["x"]
        n = max(int(dur * sr), 8)
        t = np.arange(n) / sr
        ratio = tgt / max(src["f0"], 1e-6)
        # 步长＝tgt/f_src（无量纲源样本/输出样本）；除 sr 会把音压进次声区
        pos = np.cumsum(np.full(n, ratio))
        pos = np.clip(pos, 0.0, max(len(x) - 2, 1))
        y = np.interp(pos, np.arange(len(x)), x)
        # 源耗尽处渐隐（20ms）——与扬琴同一处修正：源短于请求时值时，读指针被
        # clip 钉在末尾会「保持最后一个采样值」成直流。古筝素材够长才没暴露，
        # 但不能依赖素材长度，故在此统一兜住。
        y = y * np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)
        y = y * np.exp(-t / max(tau, 1e-3))
        if dun_ms:                     # 「止弦」/ 刮奏：短而干
            k = min(int(dun_ms / 1000.0 * sr), n)
            if k > 1:
                y[n - k:] *= 0.5 * (1.0 - np.cos(np.pi * np.arange(k) / (k - 1)))
        else:
            k = min(int(fade_ms / 1000.0 * sr), n)
            if k > 1:
                y[n - k:] *= 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / (k - 1)))
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        info = {"src": src["label"], "src_f0": src["f0"],
                "snap_dev_cents": (round(snap_dev, 1)
                                   if snap_dev is not None else None),
                "in_scale": in_tol,
                "de_reverb": src.get("de_reverb", False),
                "transpose_semi": 12.0 * math.log2(tgt / max(src["f0"], 1e-6))}
        return (y, info) if return_info else y


# 笛库「气声不主导」白名单：screen_dizi.py 逐条体检（1.5s 有声段
# HNR ≥ 6dB 且前 80ms 起音跃变 < 14dB）实测通过的 13 条，覆盖 395–977Hz。
# 包内另有 12 条 HNR 为负（谐波被气声淹没，最差 dizi_088 仅 −21.9dB），
# 只适合做点缀，不做主奏取源。
DIZI_CLEAN_OK = frozenset({
    "dizi_067", "dizi_068", "dizi_081", "dizi_082", "dizi_072", "dizi_073",
    "dizi_074", "dizi_075", "dizi_076", "dizi_077", "dizi_078", "dizi_090",
    "dizi_083",
})


class DiziBank:
    """竹笛实录采样库（Hypnotriod, Freesound pack 21613, CC0 1.0）。

    为什么不用加性合成：实测对比（本包 vs 原 dizi_note 合成器）——

        谐波滚降   -13.6 dB/oct  vs  -6.9 dB/oct   合成器泛音过多、过亮
        频谱质心    5004 Hz       vs  2024–2586 Hz  合成器听感「电子」
        气声(1.5–7k) -16.5 dB    vs  -10.9 dB      真实吹奏有气息噪声
        音内漂移    ±0–11 音分   vs  0            真实演奏有自然游移

    采样库覆盖 G4–G6（实测 f0 395–1554 Hz），《早发白帝城》主奏音域 G4–G5
    全部落在原始音高上，就近取源的变调量 <2 半音，无需强变调。

    注意：manifest 的 f0_hz 一律为谐波求和实测值，而非包名标注的音名
    （该包文件名音名整体高一个八度；另有 3 条实测落到低八度，见 pitch_log）。
    播放一律以 f0_hz 为准，故个别八度错标不影响输出音高。
    """

    def __init__(self, sr, manifest=DIZI / "manifest.json"):
        man = json.loads(Path(manifest).read_text(encoding="utf-8"))
        self.license = man["license"]
        self.sr = int(sr)
        self.samples = []
        self.pitch_log = []
        for s in man["samples"]:
            p = DIZI / s["file"]
            if not p.exists():
                continue
            data, sr_in = sf.read(str(p), always_2d=True)
            x = data.mean(axis=1).astype(np.float64)
            # 90Hz 而非 35Hz：实录笛的 20–100Hz 为 0.0%，但按 35Hz 处理时
            # 乐句里仍出现大量 20–200Hz 成分（源谱无、乐句有 → 变调积分器
            # 产生的低频漂移）。90Hz 足以拦掉它，又不碰 f0≥260Hz 的基频。
            x = highpass(x - float(np.mean(x)), sr_in, 90.0)
            x = resample(x, sr_in, self.sr)
            x = x[onset_index(x, self.sr):]
            pk = float(np.max(np.abs(x))) if len(x) else 0.0
            if pk > 0:
                x /= pk
            f0 = float(s["f0_hz"])
            # 标注八度自检：以 440 为基准检查是否偏离整数八度（记一条日志，不阻断）
            semis = 12.0 * math.log2(f0 / 440.0)
            if abs(semis / 12.0 - round(semis / 12.0)) < 0.06 and abs(round(semis / 12.0)) > 0:
                self.pitch_log.append({"label": s["label"], "note": s.get("note", ""),
                                       "f0_hz": f0, "octave_off": int(round(semis / 12.0))})
            self.samples.append({
                "label": s["label"], "x": x, "f0": f0,
                "note": s.get("note", ""), "dur": len(x) / self.sr,
            })
        self.samples.sort(key=lambda d: d["f0"])
        # 只收录白名单里实际存在的样本，避免 manifest 变动后出现幽灵 label
        self.clean_ok = frozenset(l for l in DIZI_CLEAN_OK
                                  if any(c["label"] == l for c in self.samples))

    def pick(self, f0, need_s=0.0, clean_only=False):
        """就近取源；长度不足者排后。

        clean_only=True 时只在 CLEAN_OK 白名单内取源。
        该白名单来自逐条体检（screen_dizi.py：1.5s 有声段 HNR 与起音检查），
        用来排除气声主导的素材——本包 25 条里 12 条 HNR < 6dB（最差
        dizi_088 仅 −21.9dB，谐波占比 0.006，几乎是纯气声）。若让它们
        参与主奏取源，会把「箫的尖啸」换成「笛的气声」，问题依旧。
        白名单只约束 opt-in 调用，默认 None = 行为不变。
        """
        pool = self.samples
        if clean_only and self.clean_ok:
            pool = [c for c in self.samples if c["label"] in self.clean_ok]
            if not pool:
                pool = self.samples
        best, best_key = None, None
        for c in pool:
            semi = abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6)))
            ratio = f0 / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1
            key = (round(semi, 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        return best

    def note(self, f0, dur, tau, sr=None, vib_cents=0.0, vib_rate=5.6,
             glide_from_semi=0.0, glide_time=0.0, dun_ms=None, fade_ms=6.0,
             breath=0.0, seed=0, return_info=False):
        """按处方播放一个笛音：就近取源 → 变调（可含走手音/气震）→ 衰减与顿。

        breath ∈ [0,1]：额外的竹笛气声量。实录本身已带气息噪声，默认 0 即可；
        旋律密集处可略加 0.1–0.2 让快速乐句不显得干。
        """
        sr = int(sr or self.sr)
        n_out = max(int(dur * sr), 8)
        src = self.pick(f0, need_s=dur)
        if src is None:
            return (np.zeros(n_out), None) if return_info else np.zeros(n_out)
        x = src["x"]
        base = f0 / max(src["f0"], 1e-6)

        t = np.arange(n_out) / sr
        semi = np.zeros(n_out)
        if glide_time > 0.0:
            semi += glide_from_semi * np.clip(1.0 - t / glide_time, 0.0, 1.0)
        if vib_cents:
            # 气震渐入：笛的揉音不是一上来就满，起音先稳再渐深
            ramp = np.minimum(t / 0.22, 1.0)
            semi += (vib_cents / 100.0) * ramp * np.sin(2.0 * math.pi * vib_rate * t)
        ratio = base * np.power(2.0, semi / 12.0)
        pos = np.clip(np.concatenate([[0.0], np.cumsum(ratio[:-1])]), 0.0, len(x) - 2)
        y = np.interp(pos, np.arange(len(x)), x)
        tail = np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)
        y *= tail

        y *= np.exp(-t / max(tau, 1e-3))
        if dun_ms:
            y *= read_ramp(n_out, float(dun_ms), sr)
        else:
            k = min(int(fade_ms / 1000.0 * sr), n_out)
            if k > 1:
                y[n_out - k:] *= np.linspace(1.0, 0.0, k)
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        if return_info:
            return y, {"src": src["label"], "src_f0": round(src["f0"], 1),
                       "f0": round(f0, 1),
                       "transpose_semi": round(12.0 * math.log2(base), 2)}
        return y


    def phrase(self, notes, sr, tau=2.6, glide_s=0.045, vib_cents=0.0, vib_rate=5.6,
               accent=None, rel_ms=110.0, breath=0.0, atk_floor=0.45,
               phrase_gain=1.0):
        """连奏乐句：一条气息内吹完一串音，只在音与音之间换指，不重新起音。

        「一字一声」听感怪的根因就是逐音独立起音 + 独立释放。本方法让整串音
        共享一次吹奏起音，音高按 knots 连续滑动（换指），每个字只留一个轻微的
        音量起伏（吐字感），故听感是乐句而非风琴。

        notes  : [(dur_s, f0), ...] 逐音时长与目标音高，按时间先后
        accent  : 与 notes 等长的力度系数（1.0 = 正常）；入声处可给 1.2 制造「顿」
        glide_s : 换指滑音时长。真实竹笛换指约 30–50ms，取 45ms 接近演奏感
        """
        sr = int(sr)
        notes = [(float(d), float(f)) for d, f in notes if d > 0]
        if not notes:
            return np.zeros(8)
        # 源样本按「乐句中位音高」选取：整句共享一个源，音色才稳定
        fs = [f for _d, f in notes]
        mid = math.exp(sum(math.log(max(f, 1e-6)) for f in fs) / len(fs))
        src = self.pick(mid, need_s=sum(d for d, _ in notes))
        if src is None:
            return np.zeros(8)
        x = src["x"]

        # 音高轨迹 knots：起音处即中位音高，之后每个音在换指窗内滑到目标
        times = [0.0]
        for d, _f in notes[:-1]:
            times.append(times[-1] + d)
        body = times[-1] + notes[-1][0]
        total = body + max(rel_ms, 40.0) / 1000.0
        n = max(int(total * sr), 8)
        kt = [0.0]
        kv = [math.log2(max(mid, 1e-6) / max(src["f0"], 1e-6))]
        for i, (d, f) in enumerate(notes):
            tc = times[i]
            kt.append(tc)
            kv.append(math.log2(max(f, 1e-6) / max(src["f0"], 1e-6)))
            # 同音则不产生滑音（避免无谓的微小抖动）
            if i + 1 < len(notes):
                kt.append(min(tc + d, times[i + 1]))
                kv.append(math.log2(max(f, 1e-6) / max(src["f0"], 1e-6)))
        logf = np.interp(np.arange(n) / sr, kt, kv)
        if vib_cents:
            t = np.arange(n) / sr
            logf = logf + (vib_cents / 1200.0) * np.minimum(t / 0.22, 1.0) \
                * np.sin(2.0 * math.pi * vib_rate * t)
        # kv 是 log2(f/f_src)，故 2**logf 已是无量纲步长（源样本/输出样本）；
        # 再除 sr 会把整句压低 44100 倍，掉进次声区而听不见。
        pos = np.cumsum(np.power(2.0, logf))
        y = np.interp(np.clip(pos, 0.0, len(x) - 2), np.arange(len(x)), x)
        y *= np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)

        # 音量：整句一次柔和起音；每个字叠一个明显的咬字凸起。
        # 起音不从 0 开始（floor）——真实吹管换气后是「续上」而非「重新吹」，
        # 从 0 起会让每句开头出现一个「咯噔」，听感又变回风琴。
        env = np.ones(n)
        atk = min(int(0.040 * sr), n)
        fl = float(atk_floor)
        env[:atk] = fl + (1.0 - fl) * (0.5 * (1.0 - np.cos(math.pi * np.arange(atk) / max(atk, 1))))
        acc = accent or [1.0] * len(notes)
        t = np.arange(n) / sr
        for i, (d, _f) in enumerate(notes):
            if i == 0:
                continue
            # 咬字：先微微下压（换指前的气口），再给一个明确的字头凸起。
            # 单靠正向凸起在混响下测不出来，实测 <4dB，故改为「压—提」双向且加深度。
            depth = 0.10 + 0.34 * max(acc[i] - 1.0, 0.0)
            w = min(max(0.060, d * 0.30), 0.11)
            i0, i1 = int(times[i] / sr), min(int((times[i] + w) / sr) + 1, n)
            if i1 > i0 + 1:
                shape = 0.5 * (1.0 - np.cos(2.0 * math.pi * np.arange(i1 - i0) / (i1 - i0 - 1)))
                env[i0:i1] += depth * shape
                # 字头前 40ms 略收气，字才咬得出来
                pre0 = max(i0 - int(0.040 * sr), 0)
                if i0 > pre0:
                    env[pre0:i0] *= 0.82
        y *= env
        y *= np.exp(-t / max(tau, 1e-3))
        k = min(int(rel_ms / 1000.0 * sr), n)      # 乐句末尾换气
        if k > 1:
            y[n - k:] *= 0.5 * (1.0 + np.cos(math.pi * np.arange(k) / (k - 1)))
        pk = float(np.max(np.abs(y)))
        if pk > 0:
            y /= pk
        return y


def load_dizi(sr):
    return DiziBank(sr)
