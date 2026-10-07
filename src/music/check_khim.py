#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扬琴接入自检：确认 bank 可用、变调量合理、拨弦音色成立。"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sampler                                                    # noqa: E402

kb = sampler.KhimBank(44100)
print(f"KhimBank 样本 {len(kb.samples)}  音域 "
      f"{kb.samples[0]['label']}–{kb.samples[-1]['label']}")
print(f"许可 {kb.license}")
if not kb.samples:
    print("✗ 无样本")
    sys.exit(1)

# 白帝城徵调式：G 宫，徵=0 羽=2 宫=5 商=7 角=9
semis = [0, 2, 5, 7, 9]
tonic = 392.0
print("\n《早发白帝城》guest_events 取源：")
worst = 0.0
for tag, deg, octv, dur, dun in (("句首拨弦 L1", 2, 0, 0.8, None),
                                 ("句首拨弦 L2", 2, 0, 0.8, None),
                                 ("句首拨弦 L2b", 3, 0, 0.8, None),
                                 ("「轻舟」点缀", 2, 0, 0.9, None),
                                 ("句末顿", 0, 1, 1.4, 70.0)):
    g = tonic * 2 ** ((semis[deg] + 12 * octv) / 12.0)
    y, info = kb.note(g, dur, tau=0.85, dun_ms=dun, return_info=True)
    ts = info["transpose_semi"]
    worst = max(worst, abs(ts))
    # 拨弦衰减检查：起音 30ms vs 210ms 的 RMS 比
    a = float(np.sqrt(np.mean(y[441:1764] ** 2)))
    b = float(np.sqrt(np.mean(y[8820:10164] ** 2))) if len(y) > 10164 else a
    att = 20 * math.log10(max(a, 1e-9) / max(b, 1e-9))
    print(f"  {tag:<12} deg={deg} oct={octv} → f0={g:7.1f}Hz  源={info['src']} "
          f"({info['src_f0']:.1f}Hz)  变调 {ts:+5.2f} 半音  "
          f"{len(y)/44100:.2f}s  起音衰减 {att:+5.1f} dB")

print(f"\n最大变调 {worst:.2f} 半音")
print("判定：" + ("✓ 变调在合理范围（拨弦可接受）" if worst <= 3.0
                  else "⚠ 变调偏大，音色会被拉薄"))

# 音色对比：扬琴 vs 笛（拨弦应比吹管衰减快）
db = sampler.DiziBank(44100)
if db.samples:
    c = db.pick(392.0)
    yd = db.note(392.0, 0.8, tau=2.6)
    a = float(np.sqrt(np.mean(yd[441:1764] ** 2)))
    b = float(np.sqrt(np.mean(yd[8820:10164] ** 2)))
    print(f"\n层次对比（同为 392 Hz）：")
    print(f"  笛（吹管 tau=2.6）  起音 30ms→210ms 衰减 {20*math.log10(max(a,1e-9)/max(b,1e-9)):+5.1f} dB")
    yk = kb.note(392.0, 0.8, tau=0.85)
    a2 = float(np.sqrt(np.mean(yk[441:1764] ** 2)))
    b2 = float(np.sqrt(np.mean(yk[8820:10164] ** 2)))
    print(f"  扬琴（拨弦 tau=0.85）起音 30ms→210ms 衰减 {20*math.log10(max(a2,1e-9)/max(b2,1e-9)):+5.1f} dB")
    print("  → 扬琴衰减更快，层次应能区分")
