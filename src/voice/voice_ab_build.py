# -*- coding: utf-8 -*-
"""生成「配音连贯性」A/B 试听素材并产出 voice_ab.html。

针对用户反馈「一个字一个字念出来、不连贯」，把三种成因各出一个对照档：
  plain   平读底样        —— edge 原始朗读
  step    旧版·逐音节阶跃  —— 逐字独立伸缩，字间语速瞬跳（顿挫来源）
  smooth  当前·连续规整    —— σ45 高斯平滑，倍率差全对比（已并入动画）
  soft    备选A·对比减半   —— σ45 + 倍率差减半（字长更均匀）
  soft70  备选B·更缓       —— σ70 + 倍率差减半（连贯度最高）
  fast    备选C·底样加速   —— 底样减速量减半后再规整（针对「念得慢」）

用法：python src/voice/voice_ab_build.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

OUT = os.path.join(ROOT, "dist", "audio", "voice")
AB = os.path.join(OUT, "ab")
HTML_DIR = os.path.join(ROOT, "docs", "research")   # voice_ab.html 落盘处，音频相对引用以它为基准
GEN = os.path.join(ROOT, "src", "voice", "voice_sample_gen.py")
PROS = os.path.join(ROOT, "src", "voice", "voice_prosody_process.py")

VOICE = "zh-CN-YunjianNeural"
POEMS = [
    {"key": "jys", "preset": "sad_longing", "tag": "sad",
     "title": "静夜思 · 李白", "lines": ["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"]},
    {"key": "jx", "preset": "cold_lonely", "tag": "cold",
     "title": "江雪 · 柳宗元", "lines": ["千山鸟飞绝", "万径人踪灭", "孤舟蓑笠翁", "独钓寒江雪"]},
    {"key": "bd", "preset": "joyful_swift", "tag": "joy",
     "title": "早发白帝城 · 李白", "lines": ["朝辞白帝彩云间", "千里江陵一日还", "两岸猿声啼不住", "轻舟已过万重山"]},
]

SMOOTH_CUR = ["--warp", "smooth", "--ratio-gain", "1.0", "--match-duration", "--warp-smooth-ms", "45"]

VARIANTS = [
    {"id": "plain", "label": "平读底样", "tag": "参照",
     "desc": "edge 原始朗读，未做任何韵律后处理。"},
    {"id": "step", "label": "旧版 · 逐音节阶跃", "tag": "问题版",
     "desc": "每个字独立伸缩（平 1.35 / 仄 0.85 / 入 0.65 / 韵 1.65），字与字之间语速瞬间跳变——你听到的「一字一顿」就是它。",
     "args": ["--warp", "step"]},
    {"id": "smooth", "label": "当前 · 连续规整 σ45", "tag": "已并入动画",
     "desc": "理想倍率沿时间做高斯平滑（σ=45ms），字间语速连续变化；平长仄短的对比保持全量。",
     "args": SMOOTH_CUR},
    {"id": "soft", "label": "备选A · 对比减半 σ45", "tag": "更连贯",
     "desc": "平长仄短对比收窄一半（factor′=1+0.5(f−1)），字长更均匀，听感更接近「说话」。",
     "args": ["--warp", "smooth", "--ratio-gain", "0.5", "--match-duration", "--warp-smooth-ms", "45"]},
    {"id": "soft70", "label": "备选B · 对比减半 σ70", "tag": "最连贯",
     "desc": "过渡更缓（σ=70ms）叠加对比减半；连贯度最高，吟诵腔最弱。",
     "args": ["--warp", "smooth", "--ratio-gain", "0.5", "--match-duration", "--warp-smooth-ms", "70"]},
    {"id": "fast", "label": "备选C · 底样加速", "tag": "针对念得慢",
     "desc": "底样减速量减半（-38% → -19%），再走当前规整。直接针对「念得太慢、拖字」这一成因。",
     "src_suffix": "_fast", "src_rate_scale": 0.5, "args": SMOOTH_CUR},
]


def run(cmd):
    subprocess.run(cmd, check=True, cwd=HERE,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def ensure_sources(poem):
    plain = os.path.join(OUT, f"{poem['key']}_edge_{VOICE}_quatrain.wav")
    fast = os.path.join(OUT, f"{poem['key']}_edge_{VOICE}_quatrain_fast.wav")
    if not os.path.exists(plain):
        run([sys.executable, GEN, "--backend", "edge", "--voice", VOICE, "--poem", poem["key"]])
    if not os.path.exists(fast):
        run([sys.executable, GEN, "--backend", "edge", "--voice", VOICE, "--poem", poem["key"],
             "--rate-scale", "0.5", "--suffix", "_fast"])
    return plain, fast


def build():
    os.makedirs(AB, exist_ok=True)
    result = []
    for poem in POEMS:
        plain, fast = ensure_sources(poem)
        row = {"poem": poem, "variants": []}
        for v in VARIANTS:
            src = fast if v.get("src_suffix") else plain
            if v["id"] == "plain":
                wav, js = src, None
            else:
                wav = os.path.join(AB, f"{poem['key']}_{v['id']}.wav")
                js = os.path.join(AB, f"{poem['key']}_{v['id']}.json")
                run([sys.executable, PROS, "--in-wav", src, "--out-wav", wav, "--out-json", js,
                     "--poem", poem["key"], "--emotion", poem["preset"]] + v["args"])
            meta = json.load(open(js, encoding="utf-8")) if js and os.path.exists(js) else None
            dur = meta["duration"] if meta else _wav_dur(wav)
            stats = (meta["rules"]["时间规整"]["客观指标"] if meta else None)
            row["variants"].append({
                "id": v["id"], "label": v["label"], "tag": v["tag"], "desc": v["desc"],
                "rel": os.path.relpath(wav, HTML_DIR).replace("\\", "/"),
                "dur": dur, "stats": stats,
            })
            print(f"  [{poem['key']}] {v['id']:7s} {dur:6.3f}s  "
                  f"{'maxΔ=' + format(stats['逐帧最大跳变'], '.4f') + ' 音节比×' + format(stats['音节间最大速度比'], '.2f') if stats else ''}")
        result.append(row)
    write_html(result)
    with open(os.path.join(AB, "voice_ab_data.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("OK  voice_ab.html")


def _wav_dur(path):
    import soundfile as sf
    info = sf.info(path)
    return round(info.frames / info.samplerate, 3)


def write_html(rows):
    def fmt_stats(s):
        if not s:
            return "—"
        return (f"逐帧最大跳变 {s['逐帧最大跳变']:.4f} ｜ "
                f"音节间速度比 ×{s['音节间最大速度比']:.2f}（均 ×{s['音节间平均速度比']:.2f}）")

    secs = []
    for r in rows:
        cards = []
        for v in r["variants"]:
            cards.append(f"""
      <div class="card" data-id="{v['id']}">
        <div class="chead">
          <span class="vlabel">{v['label']}</span>
          <span class="vtag t-{v['id']}">{v['tag']}</span>
        </div>
        <p class="vdesc">{v['desc']}</p>
        <audio controls preload="none" src="{v['rel']}"></audio>
        <div class="vmeta">时长 {v['dur']:.3f}s ｜ {fmt_stats(v['stats'])}</div>
      </div>""")
        secs.append(f"""
    <section class="poem">
      <h2>{r['poem']['title']}</h2>
      <p class="lines">{'　'.join(r['poem']['lines'])}</p>
      <div class="grid">{''.join(cards)}
      </div>
    </section>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>配音连贯性 A/B 试听</title>
<style>
  :root {{
    --paper:#f6f1e7; --ink:#2b2724; --ink-soft:#6b625a; --line:#d9cfbf;
    --accent:#8c3a2e; --jade:#3f6b5c;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
    font-family:"Songti SC","Noto Serif SC","Source Han Serif SC",Georgia,serif;
    line-height:1.75; }}
  .wrap {{ max-width:1060px; margin:0 auto; padding:44px 26px 90px; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:18px; margin-bottom:10px; }}
  h1 {{ font-size:30px; margin:0 0 6px; letter-spacing:.04em; }}
  .sub {{ color:var(--ink-soft); font-size:14px; }}
  .intro {{ background:#fbf7ef; border:1px solid var(--line); border-left:4px solid var(--accent);
    padding:16px 20px; margin:22px 0 34px; font-size:14.5px; }}
  .intro b {{ color:var(--accent); }}
  .intro code {{ background:#efe7d8; padding:1px 5px; border-radius:3px; font-size:13px; }}
  h2 {{ font-size:22px; margin:38px 0 2px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
  .lines {{ color:var(--ink-soft); font-size:14px; letter-spacing:.14em; margin:8px 0 18px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; }}
  .card {{ background:#fdfbf6; border:1px solid var(--line); border-radius:6px; padding:14px 16px; }}
  .card[data-id="smooth"] {{ border-color:var(--jade); box-shadow:0 0 0 2px rgba(63,107,92,.12); }}
  .card[data-id="step"] {{ border-color:#d8b9b3; background:#fdf6f4; }}
  .chead {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .vlabel {{ font-weight:600; font-size:15.5px; }}
  .vtag {{ font-size:11.5px; padding:1px 8px; border-radius:10px; color:#fff; }}
  .t-plain {{ background:#9a9188; }}
  .t-step {{ background:#b5533f; }}
  .t-smooth {{ background:var(--jade); }}
  .t-soft {{ background:#5c7a99; }}
  .t-soft70 {{ background:#4b6b8a; }}
  .t-fast {{ background:#8a6d3b; }}
  .vdesc {{ font-size:13px; color:var(--ink-soft); margin:8px 0 10px; min-height:52px; }}
  audio {{ width:100%; height:36px; }}
  .vmeta {{ font-size:12px; color:#8a8078; margin-top:8px; font-family:Consolas,monospace; }}
  .verdict {{ margin-top:46px; background:#fbf7ef; border:1px solid var(--line); padding:20px 24px; }}
  .verdict h3 {{ margin:0 0 10px; font-size:17px; }}
  .verdict ol {{ margin:0; padding-left:22px; font-size:14px; }}
  .verdict li {{ margin:6px 0; }}
  footer {{ margin-top:40px; color:#9a9188; font-size:12px; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>配音连贯性 A/B 试听</h1>
    <div class="sub">静夜思 · 江雪 · 早发白帝城　｜　音色 zh-CN-Yunjian（云健）· 情感版</div>
  </header>

  <div class="intro">
    <p>你反馈的「一个字一个字念出来、不连贯」，来自两处：<b>其一</b>，旧版对每个字做<b>独立</b>的时长伸缩
    （平 1.35 / 仄 0.85 / 入 0.65 / 韵 1.65），字与字交界处语速<b>瞬间跳变</b>（最大约 2.1×），听感即一顿一顿；
    <b>其二</b>，底样本身念得很慢（约 -38%），字间留白被放大。</p>
    <p>下方每首诗给出六个版本：<code>旧版·逐音节阶跃</code> 是问题原貌；<code>当前·连续规整 σ45</code> 是已并入动画的修复版
    （理想倍率沿时间高斯平滑，字间语速连续，总时长与旧版对齐）；另有三个备选档，分别从<b>收窄倍率差</b>、
    <b>加大平滑</b>、<b>加速底样</b>三个方向进一步提升连贯度。请逐条试听，在文末给出选择。</p>
  </div>
{''.join(secs)}

  <div class="verdict">
    <h3>请裁定</h3>
    <ol>
      <li>「当前·连续规整 σ45」相比「旧版·逐音节阶跃」，顿挫是否已消除？</li>
      <li>三首中哪一档最合你意？（当前 / 备选A / 备选B / 备选C）</li>
      <li>若选「备选C·底样加速」，动画需按新时长重新对齐（我可自动重排）。</li>
    </ol>
  </div>

  <footer>voice_ab.html　·　素材由 src/voice/voice_ab_build.py 生成　·　音频位于 dist/audio/voice/ab/</footer>
</div>
</body>
</html>"""
    with open(os.path.join(HTML_DIR, "voice_ab.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    build()
