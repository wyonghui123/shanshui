# -*- coding: utf-8 -*-
"""题诗字体 · 毛笔字候选样张（一次性决策工具）。

取 Google Fonts CSS2 的 `text=` 子集（与 build/font_subset.py 同机制），
把 6 款候选按「动画真实字号 / 真实竖排字距 / 放大笔锋 / 落款小字」四档
渲染成一张自包含 HTML（字体 base64 内嵌，离线可看），供选型比对。

用法：python src/tools/_font_sample_sheet.py
产物：docs/research/font_brush_samples.html
"""
import base64
import os
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "research", "font_brush_samples.html")

POEMS = [
    "千山鸟飞绝", "万径人踪灭", "孤舟蓑笠翁", "独钓寒江雪",
    "朝辞白帝彩云间", "千里江陵一日还", "两岸猿声啼不住", "轻舟已过万重山",
    "床前明月光", "疑是地上霜", "举头望明月", "低头思故乡",
]
SEALS = "江雪白帝静夜"
TITLES = "早发城思"
AUTHORS = "柳宗元李白"
CHARS = "".join(sorted(set("".join(POEMS)) | set(AUTHORS) | set(SEALS) | set(TITLES)))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (Google Fonts 字族, 显示名, 气质标签, 许可, 是否现状)
CANDS = [
    ("LXGW WenKai TC",  "霞鹜文楷",   "楷 · 清劲（现状）", "OFL-1.1", True),
    ("Ma Shan Zheng",   "马善政毛笔楷", "毛笔楷 · 圆厚",   "OFL-1.1", False),
    ("Zhi Mang Xing",   "志莽行书",   "行书 · 流动",      "OFL-1.1", False),
    ("Long Cang",       "龙藏",       "行楷 · 秀逸",      "OFL-1.1", False),
    ("Liu Jian Mao Cao","柳建毛草",   "毛草 · 狂放",      "OFL-1.1", False),
    ("ZCOOL XiaoWei",   "站酷小薇",   "宋/明 · 端雅",     "OFL-1.1", False),
]

# 动画真实参数（取自 dist/animation/ink_animations.html）
REAL = {"jx": {"fontSize": 23, "charPitch": 30},
        "bd": {"fontSize": 21, "charPitch": 28},
        "sy": {"fontSize": 22, "charPitch": 30}}


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_subset(family):
    q = urllib.parse.urlencode({"family": family, "text": CHARS, "display": "swap"})
    css = get("https://fonts.googleapis.com/css2?" + q, timeout=30).decode("utf-8")
    urls = re.findall(r"url\((https://[^)]+)\)", css)
    if not urls:
        raise RuntimeError("无字体 URL：" + css[:160])
    return get(urls[0], timeout=60)


def main():
    faces, rows = [], []
    for i, (fam, name, note, lic, is_now) in enumerate(CANDS):
        try:
            data = fetch_subset(fam)
        except Exception as e:
            print("✗ %s 取字失败：%s" % (fam, e))
            continue
        b64 = base64.b64encode(data).decode()
        faces.append('@font-face{font-family:"F%d";src:url(data:font/woff2;base64,%s) '
                     'format("woff2");font-display:block}' % (i, b64))
        rows.append((i, fam, name, note, lic, is_now, len(data)))
        print("✓ %-18s %-8s %6d bytes" % (fam, name, len(data)))

    def row_html(r):
        i, fam, name, note, lic, is_now, size = r
        badge = '<span class="now">现状</span>' if is_now else ""
        return f'''
    <tr>
      <th class="fam">
        <div class="fname" style="font-family:'F{i}'">{name}</div>
        <div class="fmeta">{fam}</div>
        <div class="fmeta">{note}　{lic}　{size // 1024}KB</div>
        {badge}
      </th>
      <td class="paper">
        <div class="hz" style="font-family:'F{i}';font-size:21px;line-height:1.9">朝辞白帝彩云间</div>
        <div class="hz" style="font-family:'F{i}';font-size:21px;line-height:1.9">千里江陵一日还</div>
      </td>
      <td class="paper">
        <div class="hz" style="font-family:'F{i}';font-size:46px;line-height:1.35">朝辞白帝</div>
      </td>
      <td class="paper vcell">
        <div class="vt" style="font-family:'F{i}'">朝辞白帝彩云间</div>
      </td>
      <td class="paper">
        <div class="hz" style="font-family:'F{i}';font-size:12px;line-height:1.8;opacity:.9">李白　柳宗元</div>
        <div class="hz" style="font-family:'F{i}';font-size:24px;line-height:1.5">李白</div>
      </td>
    </tr>'''

    html = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>题诗字体 · 毛笔字候选样张</title>
<style>
  %s
  :root{--paper:#F6F3EC;--ink:#161616;--ink2:#5A564D;--ink3:#8A8578;
        --line:#D9D3C6;--zhu:#A83A2C;--bg:#EDE9E0;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:"Segoe UI",system-ui,-apple-system,"Microsoft YaHei",sans-serif;
       -webkit-font-smoothing:antialiased}
  .wrap{max-width:1180px;margin:0 auto;padding:40px 30px 70px}
  h1{font-size:25px;margin:0 0 6px;font-weight:600;letter-spacing:.5px}
  .sub{color:var(--ink2);font-size:13.5px;line-height:1.85;margin:0 0 4px}
  .sub b{color:var(--ink)}
  .hr{height:1px;background:var(--line);margin:22px 0 26px}
  table{border-collapse:separate;border-spacing:0 12px;width:100%%}
  thead th{font-size:12px;color:var(--ink3);font-weight:500;text-align:left;
           padding:0 14px 2px;letter-spacing:.4px}
  tbody th,tbody td{background:var(--paper);border-top:1px solid var(--line);
                    border-bottom:1px solid var(--line);vertical-align:middle}
  tbody th{border-left:1px solid var(--line);border-radius:8px 0 0 8px;
           width:210px;padding:14px 16px;text-align:left;font-weight:400}
  tbody td{border-right:1px solid var(--line);padding:14px 16px}
  tbody td:last-child{border-radius:0 8px 8px 0}
  .fam .fname{font-size:26px;line-height:1.25;color:var(--ink)}
  .fam .fmeta{font-size:11.5px;color:var(--ink3);margin-top:5px;
              font-family:ui-monospace,Consolas,monospace}
  .now{display:inline-block;margin-top:7px;font-size:11px;color:#fff;
       background:var(--zhu);border-radius:3px;padding:1px 6px}
  .hz{white-space:nowrap;color:var(--ink)}
  .vcell{width:78px;text-align:center}
  .vt{writing-mode:vertical-rl;text-orientation:upright;
      font-size:21px;line-height:28px;height:196px;margin:0 auto;color:var(--ink)}
  .note{margin-top:30px;background:#fff;border:1px solid var(--line);border-radius:10px;
        padding:18px 22px;font-size:13px;line-height:1.95;color:var(--ink2)}
  .note h2{font-size:14px;margin:0 0 8px;color:var(--ink);font-weight:600}
  .note li{margin:3px 0}
  .note code{background:#F1EDE4;border-radius:3px;padding:1px 5px;font-size:12px;
             font-family:ui-monospace,Consolas,monospace}
  .note .warn{color:var(--zhu)}
</style>
</head>
<body>
<div class="wrap">
  <h1>题诗字体 · 毛笔字候选样张</h1>
  <p class="sub">字符集 <b>%d 字</b>（三首题诗 ∪ 落款 柳宗元/李白 ∪ 印章 江雪白帝静夜 ∪ 诗题）。
     子集经 Google Fonts CSS2 <code>text=</code> 取用字，与 <code>build/font_subset.py</code> 同机制。</p>
  <p class="sub">四档对照：<b>横排 21px</b>（白帝城实际字号）｜<b>横排 46px</b>（放大看笔锋/飞白）｜
     <b>竖排 21px · 字距 28px</b>（动画真实排布）｜<b>落款 12px / 24px</b>（正文 ×0.58）。</p>
  <div class="hr"></div>
  <table>
    <thead>
      <tr><th>字族</th><th>横排 · 实际字号 21px</th><th>横排 · 放大 46px</th>
          <th>竖排 · 真实字距</th><th>落款 · 小字 / 放大</th></tr>
    </thead>
    <tbody>%s
    </tbody>
  </table>
  <div class="note">
    <h2>选型要点（务必连同样张一起看）</h2>
    <ul>
      <li><b>换字体只改「静态字形」，不改「书写动画」。</b>当前逐字写出是
          <code>clipPath</code> 矩形揭示，不是真笔顺——毛笔字被矩形自上而下揭开，
          <span class="warn">反而更容易看出是「假书写」</span>。要真像毛笔写出来，需升级为
          <code>path 字形 + 逐笔描边</code>（依赖笔顺数据）。</li>
      <li><b>小字号是硬约束。</b>正文仅 21–23px、落款 ≈12–13px；行书/毛草在此尺寸易糊、飞白丢失。
          若正文改用毛笔楷，落款是否同步改行书需单独试（「文正款活」）。</li>
      <li><b>墨色未分档。</b>题诗现固定 <code>#161616</code>；毛笔字换入后，
          「浓/淡/枯/润」是否要跟着分档，是另一项待定。</li>
      <li>六款均 SIL OFL 1.1，可商用、可自持子集。</li>
    </ul>
  </div>
</div>
</body>
</html>
''' % ("\n  ".join(faces), len(CHARS), "".join(row_html(r) for r in rows))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("\n→ 写入 %s（%d bytes）" % (os.path.relpath(OUT, ROOT), len(html)))


if __name__ == "__main__":
    main()
