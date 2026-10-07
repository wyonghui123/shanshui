# -*- coding: utf-8 -*-
"""加 XiaoBank：北箫实录采样库（pattingthestar, CC0 1.0），并接进 music_render。

素材：NeoSoundFonts/pattingthestar-instruments → Beixiao-Raw.sf2
      录音者 pattingthestar 本人；文件内 ICOP 字段写明 "Creative Commons 0 1.0"。
      由 src/music/build_xiao.py 从 SF2 切出（该 SF2 数值字段全坏，只有 shdr 的
      name 与样值区音频可信；详见 build_xiao.py 顶部说明）。
      音域 C5–D6（实测 f0 531–1192 Hz），覆盖《静夜思》主奏音域。

为什么要换：原合成箫实测 582 个孤立谱峰（最高高出中位 181 dB），
本质是正弦堆叠 + 带通中心随音高上扫的噪声层 → 用户反馈「见鬼一样恐怖」。
实录箫有真实管腔共振、气声与本底噪声。
"""
from pathlib import Path

F = Path(r"C:\Users\Administrator\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent"
         r"\work-mode-projects\6abe713d94dc8ba73e53cfec\src\music\sampler.py")
s = F.read_text(encoding="utf-8")

XIAO_DIR = 'XIAO = D3 / "xiao"\n'

# 1) 目录常量
if "XIAO = D3" not in s:
    s = s.replace('DIZI = D3 / "dizi"\n', 'DIZI = D3 / "dizi"\n' + XIAO_DIR, 1)

# 2) XiaoBank：与 DiziBank 同机制（就近取源 + 积分重采样 + 衰减）
XIAO_BANK = '''

class XiaoBank:
    """北箫实录采样库（pattingthestar, CC0 1.0，见 manifest 的 license 字段）。

    素材来自 Beixiao-Raw.sf2（NeoSoundFonts/pattingthestar-instruments），
    由 build_xiao.py 切出：8 个音高 C5–D6，每个音高带 L/R 两个麦克风位
    （同期录制），实测 f0 531–1192 Hz。

    为什么必须换掉合成箫：原 xiao_phrase 实测 582 个孤立谱峰（最高高出中位
    181 dB），本质是正弦堆叠；且气声带通中心跟随音高上扫（f×1.6），
    330→392 Hz 的滑音会扫出一记啸叫 → 听感「见鬼一样恐怖」。
    实录箫有真实管腔共振、气声与本底噪声（本库中位 −13.2 dB）。

    与 DiziBank 同样的坑：shdr 的 name 里音高标记高一个八度，
    故 manifest 的 f0_hz / midi 一律以实测值为准，播放也只看 f0。
    """

    def __init__(self, sr, manifest=XIAO / "manifest.json"):
        p = Path(manifest)
        self.samples = []
        self.license = {}
        self.meta = {}
        if not p.exists():
            return
        man = json.loads(p.read_text(encoding="utf-8"))
        self.license = {"license": man.get("license", ""),
                        "author": man.get("author", ""),
                        "source": man.get("source", ""),
                        "url": man.get("url", "")}
        self.meta = man
        self.sr = int(sr)
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
        """就近取源；变调超过 max_semi 者不取（避免强变调失真）。"""
        best, best_key = None, None
        for c in self.samples:
            semi = 12.0 * math.log2(f0 / max(c["f0"], 1e-6))
            if max_semi is not None and abs(semi) > max_semi:
                continue
            ratio = f0 / max(c["f0"], 1e-6)
            avail = c["dur"] / max(ratio, 1e-6)
            short = 0 if avail >= need_s else 1
            key = (round(abs(semi), 1), short)
            if best_key is None or key < best_key:
                best, best_key = c, key
        if best is None and self.samples:      # 全部超界时退回就近
            return min(self.samples,
                       key=lambda c: abs(12.0 * math.log2(f0 / max(c["f0"], 1e-6))))
        return best

    def phrase(self, notes, sr, tau=3.2, glide_s=0.055, vib_cents=14.0,
               vib_rate=4.8, accent=None, rel_ms=130.0, atk_floor=0.42,
               max_semi=None):
        """连奏乐句：一次起音 + 换指滑音（与 dizi_bank.phrase 同结构）。

        与逐字 note 的区别在于音高轨迹连续、共享一条积分相位，故不会
        「一声一声重新吹」。起音不从 0 起（atk_floor）——真实吹管换气后是
        「续上」，从 0 起会让每句开头「咯噔」一下。
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

        # 音高轨迹：逐字换指，滑音窗 = glide_s
        kt, kv = [0.0], [math.log2(max(notes[0][1], 1e-6))]
        for i, (d, f) in enumerate(notes):
            kt.append(times[i])
            kv.append(math.log2(max(f, 1e-6)))
            if i + 1 < len(notes):
                kt.append(min(times[i] + glide_s, times[i + 1]))
                kv.append(math.log2(max(f, 1e-6)))
        logf = np.interp(t, kt, kv)
        if vib_cents:
            # 气震渐入：真实吹管的揉音起音先稳再渐深
            logf = logf + (vib_cents / 1200.0) * np.minimum(t / 0.25, 1.0) * \\
                np.sin(2.0 * math.pi * vib_rate * t)
        f_trk = np.power(2.0, logf)

        # 源样本按整句中位音高选，中途不变（真实换指不换音色）
        mid = float(np.median(f_trk))
        src = self.pick(mid, need_s=body, max_semi=max_semi)
        if src is None:
            return np.zeros(n)
        x = src["x"]
        pos = np.clip((np.cumsum(f_trk) / sr) * (src["f0"] / 1.0), 0.0, len(x) - 2)
        y = np.interp(pos, np.arange(len(x)), x)
        tail = np.clip((len(x) - 2 - pos) / (0.020 * sr), 0.0, 1.0)
        y = y * tail
        if pos[-1] >= len(x) - 3:              # 源不够长则自然收
            y *= np.linspace(1.0, 0.0, n, endpoint=False)[-min(n, len(y)):] \\
                if len(y) == n else 1.0

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
                    1.0 - np.cos(2.0 * np.pi * np.arange(i1 - i0) / (i1 - i0 - 1)))
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
        return y
'''

if "class XiaoBank" not in s:
    anchor = "\n\ndef onset_index("
    assert anchor in s, f"锚点 {s.count(anchor)}"
    s = s.replace(anchor, XIAO_BANK + anchor, 1)

F.write_text(s, encoding="utf-8")
print("XiaoBank 已加入 sampler.py")
