# -*- coding: utf-8 -*-
"""题诗 / 落款 / 印章字体子集：生成 / 校验 dist/animation/fonts/*.woff2。

字族表（七款，对应书体谱系 篆 / 隶 / 楷 / 行 / 草 各档）：

  A. 题诗用（Google Fonts CSS2 的 `text=` 直取子集，不落全字库，均 SIL OFL 1.1）
     PoemKai        poem-kai.woff2       霞鹜文楷 LXGW WenKai TC      楷·温润（全局兜底）
     PoemMaShan     poem-mashan.woff2    马善政毛笔楷 Ma Shan Zheng    楷·开张（白帝城 / 静夜思）
     PoemLongCang   poem-longcang.woff2  龙藏 Long Cang               行楷·瘦劲（江雪）
     PoemZhiMang    poem-zhimang.woff2   志莽行书 Zhi Mang Xing        行·流动（落款）
     PoemCao        poem-cao.woff2       柳建毛草 Liu Jian Mao Cao     草·狂放（谱系占位，三首未用）

  B. 隶档（下载源字库 → 子集；「作者声明」免费商用+可嵌入，非 OFL，出处见 README）
     PoemDaoLi      poem-li.woff2        阿里妈妈刀隶体 AlimamaDaoLiTi  隶（谱系占位，三首未用）

  C. 印章（下载源字库 → 子集 → 按 OFL §3 改名）
     PoemSeal       seal-script.woff2    敬峰中山王篆 JFZSKSealScript   篆（印章）

  书体谱系与情感空间的对应（「收放轴」↔ 唤醒 A）：篆隶（极收）→ 楷（收）→ 行（半放）→ 草（放）。
  草档补的是高唤醒区（怒 / 惧 / 惊），使 V/A/T 空间四象限齐备；隶 / 草两档为谱系占位，三首题诗未用。

字符集：
  题诗 = 三首绝句题诗用字 ∪ 落款（诗人名）用字 ∪ 印章用字 ∪ 诗题用字（共 69 字）。
  落款 = 柳宗元李白（江雪·柳宗元；早发白帝城·李白；静夜思·李白）。
  印章 = 江雪白帝静夜（江雪 / 白帝 / 静夜）。

用法：
    python build/font_subset.py            # 打印字符集与各字体状态
    python build/font_subset.py --fetch    # 联网重取并写入全部 canonical 字体（并重内嵌印章篆体）
    python build/font_subset.py --embed    # 仅把印章篆体 base64 内嵌进三张全链路页
    python build/font_subset.py --check    # 离线校验覆盖 + HTML 引用 + 全链路页内嵌（缺口即 exit 1）
"""
import base64
import io
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

# fontTools 子集化的输出受 Python 哈希随机化影响（内部集合序），跨进程会变字节。
# 固定 PYTHONHASHSEED 后重新执行自身，令 --fetch 字节级幂等（重复运行不产生假漂移）。
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    sys.exit(subprocess.call([sys.executable] + sys.argv))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "dist", "animation", "fonts")
ANIM_HTML = os.path.join(ROOT, "dist", "animation", "ink_animations.html")
PIPE_DIR = os.path.join(ROOT, "dist", "pipelines")
PIPELINE_HTMLS = ["jiangxue_pipeline.html", "baidicheng_pipeline.html",
                  "jingyesi_pipeline.html"]

# 全链路页（dist/pipelines/*.html）内嵌印章篆体：三页均为自足单文件（无外部依赖），
# 故以 base64 内嵌；否则页内 font-family="PoemSeal" 会静默回退宋体，与动画的篆书印章不一致。
SEAL_BEGIN = "<!-- poem-seal-font:begin -->"
SEAL_END = "<!-- poem-seal-font:end -->"

POEMS = [
    "千山鸟飞绝", "万径人踪灭", "孤舟蓑笠翁", "独钓寒江雪",
    "朝辞白帝彩云间", "千里江陵一日还", "两岸猿声啼不住", "轻舟已过万重山",
    "床前明月光", "疑是地上霜", "举头望明月", "低头思故乡",
]
SEALS = "江雪白帝静夜"
TITLES = "早发城思"
AUTHORS = "柳宗元李白"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def charset():
    return "".join(sorted(set("".join(POEMS)) | set(AUTHORS) | set(SEALS) | set(TITLES)))


# —— A. Google Fonts 直取子集（family 原样、文件不修改，仅 CSS 起别名） ——
GF_FONTS = [
    ("PoemKai",      "LXGW WenKai TC", "poem-kai.woff2",      "霞鹜文楷 · 楷·温润（兜底）"),
    ("PoemMaShan",   "Ma Shan Zheng",  "poem-mashan.woff2",   "马善政毛笔楷 · 楷·开张"),
    ("PoemLongCang", "Long Cang",      "poem-longcang.woff2", "龙藏 · 行楷·瘦劲"),
    ("PoemZhiMang",  "Zhi Mang Xing",  "poem-zhimang.woff2",  "志莽行书 · 行·落款"),
    ("PoemCao",      "Liu Jian Mao Cao", "poem-cao.woff2",    "柳建毛草 · 草·狂放（谱系占位）"),
]

# —— B/C. 下载源字库后自子集 ——
# rename=True 时按 OFL §3 改写 name 表族名（仅用于确有 OFL 的篆体）。
FILE_FONTS = [
    {
        "alias": "PoemSeal", "out": "seal-script.woff2", "chars": SEALS,
        "label": "敬峰中山王篆 · 篆（印章）", "rename": True,
        "urls": [
            "https://cdn.jsdelivr.net/gh/jeffi369/JFZSKSealScript@HEAD/fonts/JFZSKSealScript_V3.ttf",
            "https://fastly.jsdelivr.net/gh/jeffi369/JFZSKSealScript@HEAD/fonts/JFZSKSealScript_V3.ttf",
        ],
        "min_bytes": 500000,
    },
    {
        "alias": "PoemDaoLi", "out": "poem-li.woff2", "chars": None,
        "label": "阿里妈妈刀隶体 · 隶（作者声明，非 OFL）", "rename": False,
        "urls": [
            "https://cdn.jsdelivr.net/npm/@fontpkg/alimama-dao-li-ti@1.0.5/AlimamaDaoLiTi.ttf",
            "https://fastly.jsdelivr.net/npm/@fontpkg/alimama-dao-li-ti@1.0.5/AlimamaDaoLiTi.ttf",
        ],
        "min_bytes": 500000,
    },
]


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_gf(family, text):
    q = urllib.parse.urlencode({"family": family, "text": text, "display": "swap"})
    css = _get("https://fonts.googleapis.com/css2?" + q, timeout=30).decode("utf-8")
    urls = re.findall(r"url\((https://[^)]+)\)", css)
    if not urls:
        raise RuntimeError("Google Fonts 未返回字体 URL（CSS 片段：%r）" % css[:200])
    return _get(urls[0], timeout=90)


def fetch_src(urls, min_bytes):
    last = None
    for u in urls:
        try:
            data = _get(u)
            if len(data) >= min_bytes:
                return data
            last = RuntimeError("响应过小（%d bytes）：%s" % (len(data), u))
        except Exception as e:  # 网络失败换镜像
            last = e
    raise RuntimeError("源字库下载失败：%s" % last)


def _rename(font, family):
    """改写 name 表标识字段（family/subfamily/full/PS），保留版权与许可记录。"""
    ps = family.replace(" ", "")
    for rec in font["name"].names:
        if rec.nameID in (1, 16):
            rec.string = family
        elif rec.nameID in (2, 17):
            rec.string = "Regular"
        elif rec.nameID == 3:
            rec.string = ps + "-Regular"
        elif rec.nameID == 4:
            rec.string = family
        elif rec.nameID == 6:
            rec.string = ps


def subset_file(data, text, family=None):
    from fontTools import subset
    from fontTools.ttLib import TTFont

    opts = subset.Options()
    opts.name_IDs = ["*"]          # 保留版权 / 许可记录（OFL 要求随附）
    opts.name_legacy = True
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.recalc_timestamp = False   # 保 head.modified 不变，令子集字节级可复现（重复 --fetch 幂等）
    opts.drop_tables += ["FFTM", "DSIG"]

    font = TTFont(io.BytesIO(data))
    sub = subset.Subsetter(options=opts)
    sub.populate(text=text)
    sub.subset(font)
    if family:
        _rename(font, family)
    font.flavor = "woff2"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def coverage(path):
    from fontTools.ttLib import TTFont
    return TTFont(path).getBestCmap()


def _empty_outlines(path, chars):
    """子集后仍为空轮廓的字（覆盖到码位却画不出字形，等同缺字）。"""
    from fontTools.ttLib import TTFont
    font = TTFont(path)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    bad = []
    for ch in chars:
        g = cmap.get(ord(ch))
        if g is None:
            bad.append(ch)
            continue
        if not getattr(glyf[g], "numberOfContours", 0):  # 0=空；-1=复合（有内容）
            bad.append(ch)
    return bad


def status(rel, label, chars, glyphs=False):
    path = os.path.join(FONT_DIR, rel)
    if not os.path.exists(path):
        print("✗ %s 缺失：dist/animation/fonts/%s（跑 --fetch 生成）" % (label, rel))
        return False
    cmap = coverage(path)
    missing = [c for c in chars if ord(c) not in cmap]
    if glyphs and not missing:
        missing = _empty_outlines(path, chars)
    print("%s：fonts/%s（%d bytes）" % (label, rel, os.path.getsize(path)))
    print("  覆盖 %d/%d，缺字 %d 个%s"
          % (len(chars) - len(missing), len(chars), len(missing),
             "" if not missing else "：" + "".join(missing)))
    return not missing


def seal_style(nl):
    with open(os.path.join(FONT_DIR, "seal-script.woff2"), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return nl.join([
        SEAL_BEGIN,
        '<style id="poem-seal-font">',
        "/* 印章篆体子集内嵌（敬峰中山王篆，SIL OFL 1.1，依 OFL §3 改名 PoemSeal）。",
        "   全链路页为自足单文件，内嵌后方与动画的篆书印章一致；由 build/font_subset.py 生成，勿手改。 */",
        '@font-face{font-family:"PoemSeal";'
        'src:url("data:font/woff2;base64,%s") format("woff2");'
        'font-weight:400;font-style:normal;font-display:swap;}' % b64,
        "</style>",
        SEAL_END,
    ])


def embed_pipelines():
    """把印章篆体以 base64 内嵌进三张全链路页（幂等：标记块原地替换）。"""
    if not os.path.exists(os.path.join(FONT_DIR, "seal-script.woff2")):
        print("✗ 缺 dist/animation/fonts/seal-script.woff2，无法内嵌（先跑 --fetch）")
        return False
    ok = True
    for name in PIPELINE_HTMLS:
        path = os.path.join(PIPE_DIR, name)
        raw = open(path, "rb").read()
        html = raw.decode("utf-8")
        block = seal_style("\r\n" if "\r\n" in html else "\n")
        if SEAL_BEGIN in html:
            html = re.sub(re.escape(SEAL_BEGIN) + r".*?" + re.escape(SEAL_END),
                          lambda m: block, html, count=1, flags=re.S)
        elif "</head>" in html:
            html = html.replace("</head>", block + "\n</head>", 1)
        else:
            print("✗ %s 无 </head>，无法内嵌" % name)
            ok = False
            continue
        open(path, "wb").write(html.encode("utf-8"))
        print("  → 印章篆体内嵌：dist/pipelines/" + name)
    return ok


def check_pipelines():
    """校验三张全链路页确实内嵌了当前印章篆体（否则印章回退宋体）。"""
    with open(os.path.join(FONT_DIR, "seal-script.woff2"), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    ok = True
    for name in PIPELINE_HTMLS:
        html = open(os.path.join(PIPE_DIR, name), "rb").read().decode("utf-8")
        if SEAL_BEGIN not in html or b64 not in html:
            print("✗ 全链路页未内嵌最新印章篆体（印章将回退宋体）：dist/pipelines/" + name)
            ok = False
    return ok


def main():
    chars = charset()
    if "--embed" in sys.argv:
        sys.exit(0 if embed_pipelines() else 1)
    if "--fetch" in sys.argv:
        os.makedirs(FONT_DIR, exist_ok=True)
        for alias, family, rel, label in GF_FONTS:
            data = fetch_gf(family, chars)
            with open(os.path.join(FONT_DIR, rel), "wb") as f:
                f.write(data)
            print("→ %-16s %-24s %d bytes（%s）" % (rel, family, len(data), label))
        for spec in FILE_FONTS:
            text = spec["chars"] or chars
            raw = fetch_src(spec["urls"], spec["min_bytes"])
            sub = subset_file(raw, text, spec["alias"] if spec["rename"] else None)
            with open(os.path.join(FONT_DIR, spec["out"]), "wb") as f:
                f.write(sub)
            print("→ %-16s %-24s %d bytes（源 %d bytes，%s）"
                  % (spec["out"], spec["alias"], len(sub), len(raw), spec["label"]))
        embed_pipelines()
        return

    ok = True
    for alias, family, rel, label in GF_FONTS:
        ok &= status(rel, "%-12s %s" % (alias, label), chars)
    for spec in FILE_FONTS:
        text = spec["chars"] or chars
        ok &= status(spec["out"], "%-12s %s" % (spec["alias"], spec["label"]),
                     text, glyphs=bool(spec["chars"]))

    # 全链路页须内嵌印章篆体（否则页内印章回退宋体，与动画不一致）
    ok &= check_pipelines()

    # 反向护栏：动画 HTML 必须确实引用各字体（防「字体在、页面没引」或改名后静默失联）
    html = io.open(ANIM_HTML, encoding="utf-8").read()
    for alias, _family, rel, _label in GF_FONTS:
        ref = 'url("fonts/%s")' % rel
        if ref not in html:
            print("✗ 动画未引用字体：" + ref)
            ok = False
    for spec in FILE_FONTS:
        ref = 'url("fonts/%s")' % spec["out"]
        if ref not in html:
            print("✗ 动画未引用字体：" + ref)
            ok = False

    if not ok:
        sys.exit(1)
    if "--check" in sys.argv:
        print("✓ %d 款字体覆盖完整，均被 ink_animations.html 引用，且三张全链路页已内嵌印章篆体"
              % (len(GF_FONTS) + len(FILE_FONTS)))


if __name__ == "__main__":
    main()
