# -*- coding: utf-8 -*-
"""
D2 → pipeline 构建期注入

方案①：把三首 pipeline HTML 里的「画法参数」从硬编码改为读 D2。
  · STEP 5  留白率 ρ 区间、三远法求解结果   ← D2 现算
  · STEP 6  分区笔墨（含水 p / 墨阶 / 笔法） ← D2 现算
  · STEP 6  人物尺寸档（figure_layer：景深 → 尺寸） ← D2 现算（当前仅《江雪》接入）
  · 每首内嵌一份 D2 快照 <script id="d2-snapshot">，供离线复核
  · STEP 5 / STEP 6 章节头加 D2 徽标 + 注入说明行

原则（对齐 d2_resolve.py 的分工）：
  D2 给「候选集 + 类别档 + 区间约束」；精确数值（ρ、c）仍由卡5/卡6 求解。
  注入只覆盖 D2 拥有的字段，求解值原样保留并就地按 D2 区间判读。

用法：
    python src/d2/d2_inject.py            # 注入（幂等，可反复跑）
    python src/d2/d2_inject.py --check    # 只校验：HTML 内嵌快照 vs 现算 D2
    python src/d2/d2_inject.py --poem jx  # 只处理一首
"""
import argparse
import html as html_mod
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

sys.path.insert(0, HERE)
import d2_resolve as R  # noqa: E402

VOID_ROLES = {"不画", "承载留白"}

# 尺寸档 → 人高占比区间（仅用于注入单元格的提示文案，口径同 ink_figure_grammar.html 四档）
SIZE_PCT = {"极写意": "≤4%", "极小点景": "4–6%", "点景": "6–9%", "中号": "9–30%"}

# ---------------------------------------------------------------- 逐诗接线表
# zones: 区域行标签 → D2 节点名（None = D2 无对应节点，保持原样）
POEMS = {
    "jx": {
        "file": "jiangxue_pipeline.html",
        "rho_before": [0.72, 0.85],
        "step5": {
            "rho_row": "留白率 ρ", "rho_range_col": 1, "rho_verdict_col": 3,
            "yuan_row": "三远法", "yuan_result_col": 2, "yuan_verdict_col": 3,
        },
        "step6": {"cols": (1, 2, 3), "size_col": 4, "size_header": "尺寸档"},   # (含水 p, 墨浓度, 笔法) + 尺寸档
        "zones": {
            "远山": "千山", "万径": "万径", "孤舟": "孤舟",
            "蓑笠翁": "蓑笠翁", "钓丝": "独钓", "寒江 / 雪": "寒江",
        },
    },
    "bd": {
        "file": "baidicheng_pipeline.html",
        "rho_before": [0.45, 0.58],
        "step5": {
            "rho_row": "留白率 ρ", "rho_range_col": 1, "rho_verdict_col": 4,
            "yuan_row": "三远法", "yuan_result_col": 2, "yuan_verdict_col": 4,
        },
        "step6": {"cols": (1, 2, 3)},
        "zones": {
            "彩云": "彩云", "白帝城": "白帝", "两岸山壁": "两岸",
            "万重山": "万重山", "江水": None, "轻舟": "轻舟", "猿声": "猿声",
        },
    },
    "jys": {
        "file": "jingyesi_pipeline.html",
        "rho_before": [0.72, 0.85],
        "step5": {"note_range": True},   # 区间写在 sec-note 里，无表格行
        "step6": {"object_col": 1},      # 墨分五色：墨阶 | 对象 | 笔法
        # 墨阶行标签 → D2 节点
        "ink_rows": {"中": "床", "淡": "明月", "极淡": "霜"},
    },
}

TD_RE = re.compile(r'<td(\s[^>]*)?>(.*?)</td>', re.S)
TR_RE = re.compile(r'<tr[^>]*>.*?</tr>', re.S)
TAG_RE = re.compile(r'\s*<span class="d2-tag[^"]*"[^>]*>.*?</span>', re.S)


# ---------------------------------------------------------------- 小工具
def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def strip_tags(s):
    return html_mod.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def fmt_num(x):
    return f"{x:g}"


def fmt_range(lo, hi):
    return f"[{fmt_num(lo)}, {fmt_num(hi)}]"


def step_spans(html):
    marks = [(m.start(), int(m.group(1)))
             for m in re.finditer(r'<span class="sec-no">STEP (\d+)</span>', html)]
    spans = {}
    for i, (pos, step) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        spans[step] = (pos, end)
    return spans


def find_row(sec_text, label):
    """返回 (start, end, row_html)；按首个 <td> 文本匹配行标签。"""
    for m in TR_RE.finditer(sec_text):
        tds = TD_RE.findall(m.group(0))
        if tds and strip_tags(tds[0][1]) == label:
            return m.start(), m.end(), m.group(0)
    return None


def clean_cell(row_html, idx):
    """取第 idx 个 <td> 的纯文本，并剥掉此前注入的 D2 标记（保证幂等）。"""
    tds = TD_RE.findall(row_html)
    if idx >= len(tds):
        return ""
    return strip_tags(TAG_RE.sub('', tds[idx][1])).strip()


def replace_cell(row_html, idx, inner=None, d2key=None, td_class=None):
    """替换第 idx 个 <td> 的内容/属性。inner=None 表示只改属性。"""
    out, last = [], 0
    for i, m in enumerate(TD_RE.finditer(row_html)):
        out.append(row_html[last:m.start()])
        if i == idx:
            attrs = m.group(1) or ''
            attrs = re.sub(r'\s*data-d2="[^"]*"', '', attrs)
            if d2key:
                attrs += f' data-d2="{d2key}"'
            if td_class is not None:
                attrs = re.sub(r'\s*class="[^"]*"', '', attrs)
                if td_class:
                    attrs += f' class="{td_class}"'
            body = m.group(2) if inner is None else inner
            out.append(f'<td{attrs}>{body}</td>')
        else:
            out.append(m.group(0))
        last = m.end()
    out.append(row_html[last:])
    return ''.join(out)


def ensure_cell(row_html, idx, inner, d2key=None, td_class=None):
    """确保第 idx 个 <td> 存在：不足则补到行尾，再替换其内容/属性。"""
    if idx < len(TD_RE.findall(row_html)):
        return replace_cell(row_html, idx, inner, d2key, td_class)
    attrs = ''
    if d2key:
        attrs += f' data-d2="{d2key}"'
    if td_class:
        attrs += f' class="{td_class}"'
    pos = row_html.rfind('</td>') + len('</td>')
    return row_html[:pos] + f'<td{attrs}>{inner}</td>' + row_html[pos:]


def edit_row(sec_text, label, edits):
    """edits: {col: (inner, d2key, td_class)}。返回新 sec_text。"""
    hit = find_row(sec_text, label)
    if not hit:
        return sec_text, False
    start, end, row = hit
    for col, spec in edits.items():
        inner, d2key, td_class = spec
        row = replace_cell(row, col, inner, d2key, td_class)
    return sec_text[:start] + row + sec_text[end:], True


def merge_stroke(d2_stroke, pipe_text):
    """笔法：以 D2 基笔法为准，保留 pipeline 的诗级修饰语。"""
    pp = [p.strip() for p in pipe_text.split('·')]
    dp = [p.strip() for p in d2_stroke.split('·')]
    if pp and dp and pp[0] == dp[0]:
        return ' · '.join(pp)
    return ' · '.join(dp + pp[1:])


def edit_section(html, spans, step, fn):
    if step not in spans:
        return html
    a, b = spans[step]
    return html[:a] + fn(html[a:b]) + html[b:]


def put_size_column(sec, spec, by):
    """在含「含水 p」的表中追加「尺寸档」列。

    人物行取 figure_layer 的 size（景深 → 尺寸），非人物行填「—」。
    幂等：表头/单元格存在即替换，不累加。
    """
    sc = spec["step6"].get("size_col")
    if sc is None:
        return sec
    header = spec["step6"].get("size_header", "尺寸档")
    tgt = next((m for m in re.finditer(r'<table>.*?</table>', sec, re.S)
                if '含水' in m.group(0)), None)
    if not tgt:
        return sec
    tbl = tgt.group(0)

    if header not in tbl:
        tbl = re.sub(r'</tr>\s*</thead>', f'<th>{header}</th></tr></thead>',
                     tbl, count=1, flags=re.S)

    tb = re.search(r'<tbody>.*?</tbody>', tbl, re.S)
    if not tb:
        return sec

    def row_fn(m):
        row = m.group(0)
        tds = TD_RE.findall(row)
        if not tds:
            return row
        label = strip_tags(tds[0][1])
        node = spec["zones"].get(label)
        b = by.get(node) if node else None
        size = (b or {}).get("size")
        if size:
            pct = SIZE_PCT.get(size, "")
            inner = (f'{size} <span class="d2-tag" title="figure_layer：景深 '
                     f'{b["layer"]} → {size}（{pct}）">{pct}</span>')
            return ensure_cell(row, sc, inner, f"zones.{label}.size", "num")
        return ensure_cell(row, sc, "—", None, "num")

    new_tb = TR_RE.sub(row_fn, tb.group(0))
    tbl = tbl[:tb.start()] + new_tb + tbl[tb.end():]
    return sec[:tgt.start()] + tbl + sec[tgt.end():]


# ---------------------------------------------------------------- 底色通路（A 组）
def _join(seq, sep=' / '):
    return sep.join(seq) if seq else '—'


def _range_or_dash(rng):
    return fmt_range(*rng) if rng else '—'


def _kv_rows(rows):
    """(环节, D2 字段, 值, data-d2, td_class) → <tr> 行。"""
    return '\n'.join(
        '          <tr><td>%s</td><td><code>%s</code></td><td data-d2="%s"%s>%s</td></tr>'
        % (a, b, d2, ' class="%s"' % cls if cls else '', v)
        for a, b, v, d2, cls in rows)


def _card(card_id, title, rows, caption):
    """C 组算子卡模板：id 供幂等替换；值单元格带 data-d2 溯源。"""
    return (
        f'<div class="card tight" id="{card_id}">\n'
        f'      <h3 style="margin-top:0">{title}</h3>\n'
        '      <table>\n'
        '        <thead><tr><th>环节</th><th>D2 字段</th><th>值</th></tr></thead>\n'
        '        <tbody>\n' + _kv_rows(rows) + '\n'
        '        </tbody>\n'
        '      </table>\n'
        f'      <p class="caption" style="margin:8px 0 0">{caption}</p>\n'
        '    </div>')


def base_tone_card(r):
    """6.3 底色通路：D2 的 polarity / base_tone 候选 → 卡6 消费端（A 组接线）。

    此前 polarity / base_tone 只在 D2 侧算出、无消费端；本卡把它落进 STEP 6（卡6），
    使「季节色 + 极性色 → 底色候选 + 墨偏区间」这条链在交付页可见且可溯源。
    """
    bt, pol, sea = r["base_tone"], r["polarity"], r["base_tone"]["season"]
    rows = [
        ("季节", "season", sea["name"] or '—', "poem_level.base_tone.season.name", "num"),
        ("季节色", "vocab.season.color", sea["color"] or '—', "poem_level.base_tone.season.color", None),
        ("极性键", "polarity.keys · G12 归一", _join(pol["keys"]), "poem_level.base_tone.polarity_keys", None),
        ("极性色", "modulators.polarity.color", _join(pol["colors"]), "poem_level.polarity.colors", None),
        ("底色候选", "base_tone.color_candidates", _join(bt["color_candidates"]),
         "poem_level.base_tone.color_candidates", None),
        ("墨偏区间", "base_tone.ink_bias_range", _range_or_dash(bt["ink_bias_range"]),
         "poem_level.base_tone.ink_bias_range", "num"),
    ]
    trs = '\n'.join(
        '          <tr><td>%s</td><td><code>%s</code></td><td data-d2="%s"%s>%s</td></tr>'
        % (a, b, d2, ' class="%s"' % cls if cls else '', v)
        for a, b, v, d2, cls in rows)
    return ('<div class="card tight" id="d2-base-tone">\n'
            '      <h3 style="margin-top:0">6.3 底色通路（A 组 · D2 候选 → 卡6 求解）</h3>\n'
            '      <table>\n'
            '        <thead><tr><th>环节</th><th>D2 字段</th><th>值</th></tr></thead>\n'
            '        <tbody>\n' + trs + '\n'
            '        </tbody>\n'
            '      </table>\n'
            '      <p class="caption" style="margin:8px 0 0">D2 只给<b>候选</b>与<b>墨偏区间</b>；'
            '卡6 在候选内求解精确底色（分工铁律）。本节即该候选的消费端（A 组接线）。</p>\n'
            '    </div>')


def put_base_tone_card(sec, r):
    """幂等插入 6.3 底色通路卡：存在即替换，否则插在 STEP 6 的 </section> 之前。"""
    return put_card(sec, "d2-base-tone", base_tone_card(r))


def put_card(sec, card_id, card):
    """幂等插入卡：存在即替换，否则插在 STEP 6 的 </section> 之前（顺序追加）。"""
    if f'id="{card_id}"' in sec:
        return re.sub(r'<div class="card tight" id="%s">.*?</div>' % re.escape(card_id),
                      lambda m: card, sec, count=1, flags=re.S)
    i = sec.rfind('</section>')
    if i < 0:
        return sec
    return sec[:i] + card + '\n' + sec[i:]


# ---------------------------------------------------------------- 设色范式 / 墨法轴（B 组）
def paradigm_card(r):
    """6.4 设色范式：D2 的 paradigm 候选 / 默认档 / 色域投影 → 卡6 消费端（G3 · B 组接线）。

    D2 只给范式候选与色域（改写 A 组底色候选），精确用色由卡6 求解（分工铁律）。
    """
    pg = r["paradigm"]
    ev = _join([f'{rid}→{p}' for rid, p in pg["evidence"].items()])
    rows = [
        ("范式默认档", "paradigm.default", pg["default"], "poem_level.paradigm.default", "num"),
        ("范式候选", "paradigm.candidates", _join(pg["candidates"]), "poem_level.paradigm.candidates", None),
        ("墨骨强度", "vocab.paradigm.ink_bone × color_projection.ink_bone_scale",
         f'{pg["ink_bone"]} × {fmt_num(pg["ink_bone_scale"])}',
         "poem_level.paradigm.ink_bone_scale", "num"),
        ("色域", "vocab.paradigm.color_domain", _join(pg["color_domain"]),
         "poem_level.paradigm.color_domain", None),
        ("色域投影", "paradigm.projected_color_candidates", _join(pg["projected_color_candidates"]),
         "poem_level.paradigm.projected_color_candidates", None),
        ("定档规则", "modulators.paradigm.rules", ev or '（默认档）',
         "poem_level.paradigm.rules_fired", None),
    ]
    trs = '\n'.join(
        '          <tr><td>%s</td><td><code>%s</code></td><td data-d2="%s"%s>%s</td></tr>'
        % (a, b, d2, ' class="%s"' % cls if cls else '', v)
        for a, b, v, d2, cls in rows)
    return ('<div class="card tight" id="d2-paradigm">\n'
            '      <h3 style="margin-top:0">6.4 设色范式（G3 · B 组 · D2 候选 → 卡6 求解）</h3>\n'
            '      <table>\n'
            '        <thead><tr><th>环节</th><th>D2 字段</th><th>值</th></tr></thead>\n'
            '        <tbody>\n' + trs + '\n'
            '        </tbody>\n'
            '      </table>\n'
            '      <p class="caption" style="margin:8px 0 0">范式由品格 / 季节 / 极性定档（青绿 ← 北宗着色山水；'
            '浅绛 ← 元人淡彩；水墨 ← 南宗渲淡；没骨 ← 徐崇嗣纯色）。D2 只给<b>候选</b>与<b>色域投影</b>，'
            '精确用色由卡6 在色域内求解（分工铁律）。</p>\n'
            '    </div>')


def ink_method_card(r):
    """6.5 墨法轴：D2 的 ink_method 候选 + μ 扩散区间 → 卡6 消费端（G11 · B 组接线）。

    μ = 卡6 扩散律系数（L∝√(μ·t)）；D2 只给候选与 μ 区间，精确墨法与扩散由卡6 求解。
    """
    im = r["ink_methods"]
    sug = set(im["suggested"])
    trs = []
    for name, d in im["candidates"].items():
        mark = ('<span class="d2-tag" title="语境建议：本诗可优先取此墨法">建议</span>'
                if name in sug else '—')
        trs.append('          <tr><td>%s</td><td class="num" data-d2="vocab.ink_method.%s.mu">%s</td>'
                   '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (name, name, fmt_range(*d["mu"]), d["water"], d["stroke"], d["quality"], mark))
    return ('<div class="card tight" id="d2-ink-method">\n'
            '      <h3 style="margin-top:0">6.5 墨法轴（G11 · B 组 · D2 候选 → 卡6 求解）</h3>\n'
            '      <table>\n'
            '        <thead><tr><th>墨法</th><th>μ 区间</th><th>含水</th><th>笔法</th>'
            '<th>质感</th><th>语境建议</th></tr></thead>\n'
            '        <tbody>\n' + '\n'.join(trs) + '\n'
            '        </tbody>\n'
            '      </table>\n'
            '      <p class="caption" style="margin:8px 0 0">μ = 卡6 扩散律系数（<code>L ∝ √(μ·t)</code>，'
            '基准 μ0=1.0）；宿墨 μ 偏低（更慢更滞）、焦墨 / 飞白 μ 极低（几乎不洇）。'
            'D2 只给<b>候选</b>与<b>μ 区间</b>，精确墨法与扩散由卡6 求解。</p>\n'
            '    </div>')


# ---------------------------------------------------------------- C 组·新算子卡（G1/G2/G4/G5/G6/G7/G8）
def viewpoint_card(r):
    """5.1 视点档（G7）：空间词 + 三远 → 视点档 + 地平线 / 垂直尺度区间 → 卡5 求解。"""
    vp = r["viewpoint"]
    if not vp["applicable"]:
        rows = [("适用性", "viewpoint.applicable", vp["note"], "poem_level.viewpoint.applicable", None)]
    else:
        votes = _join([f'{k} {fmt_num(v)}' for k, v in vp["votes"].items()], '　')
        rows = [
            ("视点档", "viewpoint.default", vp["default"], "poem_level.viewpoint.default", "num"),
            ("判据", "vocab.viewpoint.criterion", vp["criterion"], "poem_level.viewpoint.criterion", None),
            ("视点票", "viewpoint.votes", votes or '—', "poem_level.viewpoint.votes", None),
            ("候选", "viewpoint.candidates", _join(vp["candidates"]), "poem_level.viewpoint.candidates", None),
            ("地平线区间", "vocab.viewpoint.params.horizon", _range_or_dash(vp["horizon"]),
             "poem_level.viewpoint.horizon", "num"),
            ("垂直尺度", "vocab.viewpoint.params.vertical_scale", _range_or_dash(vp["vertical_scale"]),
             "poem_level.viewpoint.vertical_scale", "num"),
        ]
    return _card(
        "d2-viewpoint", "5.1 视点档（G7 · C 组 · D2 → 卡5）", rows,
        "视点独立于三远：郭熙三远覆盖<b>仰视 / 平视</b>，<b>俯视</b>补沈括「以大观小」。"
        "D2 由空间词（仰 / 俯 / 瞰…）与三远归属投票定档，并给出<b>地平线区间</b>与<b>垂直尺度</b>；"
        "精确构图由卡5 在区间内求解。")


def weather_card(r):
    """5.2 天候（G4）：天候词 → 天候档 + 卡5 ρ 加成 / 卡6 σ·μ 乘子。"""
    wx = r["weather"]
    rows = [
        ("天候档", "weather.name", wx["name"] or "未命中（系数中性）", "poem_level.weather.name", "num"),
        ("命中词", "weather.hit", _join(wx["hit"]), "poem_level.weather.hit", None),
        ("σ 乘子（卡6）", "weather.sigma_mult", _range_or_dash(wx["sigma_mult"]),
         "poem_level.weather.sigma_mult", "num"),
        ("μ 乘子（卡6）", "weather.mu_mult", _range_or_dash(wx["mu_mult"]),
         "poem_level.weather.mu_mult", "num"),
        ("留白加成（卡5）", "weather.blank_bonus", fmt_num(wx["blank_bonus"]),
         "poem_level.weather.blank_bonus", "num"),
        ("皴法偏置", "weather.cun_bias", _join(wx["cun_bias"]), "poem_level.weather.cun_bias", None),
    ]
    if wx.get("quality"):
        rows.insert(2, ("质感", "vocab.weather.quality", wx["quality"], "poem_level.weather.quality", None))
    if wx.get("source_id"):
        rows.append(("来源", "vocab.weather.source_id", wx["source_id"], "poem_level.weather.source_id", None))
    return _card(
        "d2-weather", "5.2 天候（G4 · C 组 · D2 → 卡5 / 卡6）", rows,
        "天候由天候词定档（「日」因歧义不收，只收晴 / 霁 / 雨 / 雪 / 雾 / 烟）。"
        "雪 → 卡5 留白率上调、σ 上调；雾 → 卡6 空气透视（σ 大幅上调）；雨 → 雨点皴 / 湿度。"
        "D2 只给<b>乘子与加成</b>，精确 σ / μ 由卡6 求解。")


def composition_card(r):
    """5.3 构图规则（G1）：边角 / 三叠两段护栏 + 蹊径六则软目标算子。"""
    cp = r["composition"]
    g0, g1 = cp["guards"][0], cp["guards"][1]
    rows = [
        (f'护栏·{g0["name"]}', "composition.guards.边角", f'{g0["kind"]}｜{g0["rule"]}',
         "poem_level.composition.guards", None),
        (f'护栏·{g1["name"]}', "composition.guards.三叠两段", f'{g1["kind"]}｜{g1["rule"]}',
         "poem_level.composition.guards", None),
        ("软目标算子", "composition.operator", cp["operator"], "poem_level.composition.operator", "num"),
        ("算子规则", "vocab.composition.rule", cp["operator_rule"],
         "poem_level.composition.operator_rule", None),
        ("候选", "composition.candidates", _join(cp["candidates"]),
         "poem_level.composition.candidates", None),
        ("触发规则", "composition.rules_fired", _join(cp["rules_fired"]) or "（默认）",
         "poem_level.composition.rules_fired", None),
    ]
    return _card(
        "d2-composition", "5.3 构图规则（G1 · C 组 · D2 → 卡5）", rows,
        "边角（马远「马一角」/ 夏圭「夏半边」）与三叠两段为<b>护栏</b>（恒生效）；"
        "蹊径六则（石涛《画语录》）为<b>软目标算子池</b>，D2 按语境（季节 / V 档 / 山石 / 天象）选一。"
        "精确布局由卡5 求解。")


def material_card(r):
    """6.6 材质系数（G6）：纸绢 / 笔 / 墨 → 卡6 扩散 · 飞白 · 墨色乘子。"""
    m = r["material"]
    paper, brush, ink = m["paper"], m["brush"], m["ink"]
    rows = [
        ("纸绢", "material.choice.纸绢", m["choice"]["纸绢"], "poem_level.material.choice.纸绢", None),
        ("扩散 D 乘子", "vocab.material.纸绢.D_mult", _range_or_dash(paper["D_mult"]),
         "poem_level.material.paper.D_mult", "num"),
        ("μ 乘子", "vocab.material.纸绢.mu_mult", _range_or_dash(paper["mu_mult"]),
         "poem_level.material.paper.mu_mult", "num"),
        ("飞白阈值", "vocab.material.纸绢.feibai_threshold", _range_or_dash(paper["feibai_threshold"]),
         "poem_level.material.paper.feibai_threshold", "num"),
        ("笔", "material.choice.笔", m["choice"]["笔"], "poem_level.material.choice.笔", None),
        ("笔刚度", "vocab.material.笔.stiffness", _range_or_dash(brush["stiffness"]),
         "poem_level.material.brush.stiffness", "num"),
        ("笔蓄水", "vocab.material.笔.water_cap", _range_or_dash(brush["water_cap"]),
         "poem_level.material.brush.water_cap", "num"),
        ("墨", "material.choice.墨", m["choice"]["墨"], "poem_level.material.choice.墨", None),
        ("墨色", "vocab.material.墨.hue", ink["hue"], "poem_level.material.ink.hue", None),
        ("墨温", "vocab.material.墨.warmth", fmt_num(ink["warmth"]), "poem_level.material.ink.warmth", "num"),
    ]
    return _card(
        "d2-material", "6.6 材质系数（G6 · C 组 · D2 → 卡6）", rows,
        "材质改卡6 扩散律：生宣吸水强（D / μ 乘子 &gt;1）、熟宣不洇墨（&lt;1）、绢居中；"
        "硬毫（狼毫）弹性强、软毫（羊毫）蓄水多；松烟偏冷、油烟偏暖。"
        "D2 只给<b>乘子与区间</b>，精确扩散由卡6 求解。当前取默认档（诗中无材质依据）。")


def stroke_quality_card(r):
    """6.7 笔法质量维（G2）：笔法式 → 适用质量维（正向）/ 须避病（负向）。"""
    sq = r["stroke_quality"]
    rows = [
        ("笔法式", "stroke_quality.strokes", _join(sq["strokes"]),
         "poem_level.stroke_quality.strokes", None),
        ("适用质量维", "stroke_quality.quality", _join(sq["quality"]),
         "poem_level.stroke_quality.quality", None),
        ("须避病", "stroke_quality.avoid", _join(sq["avoid"]), "poem_level.stroke_quality.avoid", None),
    ]
    return _card(
        "d2-stroke-quality", "6.7 笔法质量维（G2 · C 组 · D2 → 卡6）", rows,
        "笔法由<b>形态名</b>升为<b>质量判据</b>：四势（荆浩《笔法记》：筋 / 肉 / 骨 / 气）与"
        "五笔（黄宾虹：平 / 留 / 圆 / 重 / 变）为正向二级判据；二病（郭若虚三病：板 / 刻 / 结；"
        "荆浩二病：有形病 / 无形病）为负向过滤。D2 由诗用笔法式映射到适用质量维与须避病。")


def time_of_day_card(r):
    """7.2 时辰（G5）：时辰词 → 时辰档 + 段长乘子 / 墨偏 / 色温 → 卡7 求解。"""
    td = r["time_of_day"]
    rows = [
        ("时辰档", "time_of_day.name", td["name"] or "未命中（乘子中性）",
         "poem_level.time_of_day.name", "num"),
        ("命中词", "time_of_day.hit", _join(td["hit"]), "poem_level.time_of_day.hit", None),
        ("段长乘子", "time_of_day.seg_len_mult", _range_or_dash(td["seg_len_mult"]),
         "poem_level.time_of_day.seg_len_mult", "num"),
        ("墨偏", "time_of_day.ink_bias", fmt_num(td["ink_bias"]),
         "poem_level.time_of_day.ink_bias", "num"),
    ]
    if td.get("color"):
        rows += [
            ("色", "time_of_day.color", td["color"], "poem_level.time_of_day.color", None),
            ("冷暖", "time_of_day.warmth", fmt_num(td["warmth"]),
             "poem_level.time_of_day.warmth", "num"),
            ("气", "vocab.time_of_day.qi", td["qi"], "poem_level.time_of_day.qi", None),
        ]
    return _card(
        "d2-time-of-day", "7.2 时辰（G5 · C 组 · D2 → 卡7）", rows,
        "时辰由时辰词定档（郭熙「朝暮」；「月」由季节词迁来，属天象 / 时辰）。"
        "暮 / 夜 → 段长乘子 &gt;1、墨偏 ↑、色偏赭 / 冷灰；晨 → 淡青。"
        "D2 只给<b>乘子与墨偏档</b>，精确时长由卡7 求解。")


def seal_card(r):
    """7.3 钤印（G8）：形制 → 印位；诗体长度 → 印面大小档 → 卡7 段尾静默。"""
    s = r["seal"]
    rows = [
        ("形制", "seal.format", s["format"], "poem_level.seal.format", None),
        ("印位", "seal.position", s["position"], "poem_level.seal.position", None),
        ("印位说明", "vocab.seal.positions.note", s["position_note"],
         "poem_level.seal.position_note", None),
        ("印面档", "seal.size", s["size"], "poem_level.seal.size", "num"),
        ("印面乘子", "vocab.seal.sizes.size_mult", _range_or_dash(s["size_mult"]),
         "poem_level.seal.size_mult", "num"),
        ("通例", "vocab.seal.rule", s["rule"], "poem_level.seal.rule", None),
    ]
    return _card(
        "d2-seal", "7.3 钤印（G8 · C 组 · D2 → 卡7）", rows,
        "钤印由形制定印位（手卷卷末 / 图前、立轴左下 / 右下加押角、册页下角…），"
        "由诗体长度定印面大小档（长诗大幅、短诗小幅），并守「印不可比字大」。"
        "D2 只给<b>印位与印面区间</b>，纳入卡7 段尾静默。")


def put_c_step5(sec, r):
    """卡5 消费端：视点（G7）+ 天候（G4）+ 构图规则（G1）。"""
    sec = put_card(sec, "d2-viewpoint", viewpoint_card(r))
    sec = put_card(sec, "d2-weather", weather_card(r))
    sec = put_card(sec, "d2-composition", composition_card(r))
    return sec


def put_c_step6(sec, r):
    """卡6 消费端：材质系数（G6）+ 笔法质量维（G2）。"""
    sec = put_card(sec, "d2-material", material_card(r))
    sec = put_card(sec, "d2-stroke-quality", stroke_quality_card(r))
    return sec


def put_c_step7(sec, r):
    """卡7 消费端：时辰（G5）+ 钤印（G8）。"""
    sec = put_card(sec, "d2-time-of-day", time_of_day_card(r))
    sec = put_card(sec, "d2-seal", seal_card(r))
    return sec


# ---------------------------------------------------------------- 徽标 / 说明行
CSS = """<style id="d2-style">
  .d2-badge { display:inline-block; margin-left:8px; padding:1px 6px; border-radius:4px;
    font-family:var(--mono); font-size:10px; letter-spacing:.08em; vertical-align:middle;
    color:var(--qing); border:1px solid rgba(62,92,118,.35); background:var(--qing-soft); cursor:help; }
  .d2-note { margin:-12px 0 18px; font-size:12px; color:var(--ink-3); }
  .d2-note code { font-family:var(--mono); font-size:11px; color:var(--qing); }
  .d2-tag { display:inline-block; margin-left:4px; padding:0 4px; border-radius:3px;
    font-family:var(--mono); font-size:10px; color:var(--qing);
    border:1px solid rgba(62,92,118,.3); background:var(--qing-soft); cursor:help; }
  .d2-tag.warn { color:var(--zhu); border-color:rgba(168,58,44,.35); background:var(--zhu-soft); }
  /* 顶部横幅：一眼看到「本页参数已改为读 D2」 */
  .d2-banner { display:flex; gap:12px; align-items:flex-start; margin:0 0 40px;
    padding:15px 18px 15px 20px; border-radius:10px;
    border:1px solid rgba(62,92,118,.30); background:var(--qing-soft);
    box-shadow: inset 4px 0 0 var(--qing); }
  .d2-banner .d2-badge { margin:3px 0 0; flex:none; }
  .d2-banner-body { font-size:12.5px; color:var(--ink-2); line-height:1.75; }
  .d2-banner-body b { color:var(--qing); }
  .d2-banner code { font-family:var(--mono); font-size:11px; color:var(--qing); }
  .d2-diff { margin-top:7px; font-family:var(--mono); font-size:12px; color:var(--ink-2); }
  .d2-diff s { color:var(--ink-3); }
  .d2-diff b { color:var(--qing); }
  /* D2 拥有的单元格：淡底 + 左细线，便于扫读 */
  td[data-d2] { background:rgba(62,92,118,.055); box-shadow: inset 2px 0 0 rgba(62,92,118,.38); }
</style>"""

BADGE = ('<span class="d2-badge" title="本节画法参数由 D2 构建期注入'
         '（d2_techniques.json → src/d2/d2_inject.py）">D2</span>')


def drop_banner(html):
    """删除既有 D2 横幅（按 div 嵌套配平定位结束），使横幅可随重跑刷新。"""
    key = '<div class="d2-banner" id="d2-banner">'
    i = html.find(key)
    if i < 0:
        return html
    depth, pos = 0, i
    tag = re.compile(r'</?div\b')
    while pos < len(html):
        m = tag.search(html, pos)
        if not m:
            break
        if html[m.start():m.start() + 2] == '</':
            depth -= 1
            if depth == 0:
                end = html.find('>', m.start()) + 1
                return (html[:i] + html[end:]).replace('</header>\n\n\n', '</header>\n\n', 1)
        else:
            depth += 1
        pos = m.end()
    return html


def put_banner(html, pid, r, spec):
    """页面顶部插入 D2 横幅：本页哪些步骤改为读 D2、留白区间注入前后对照。幂等可刷新。"""
    html = drop_banner(html)
    lo, hi = r["blank_range"]
    yuan = ' + '.join(r["yuan"]) if r["yuan"] else '不适用'
    cun = ' + '.join(r["cun"]) if r["cun"] else '不适用'
    before = spec.get("rho_before")
    rho_txt = (f'<s>{fmt_range(*before)}</s> → <b>{fmt_range(lo, hi)}</b>'
               if before else f'<b>{fmt_range(lo, hi)}</b>')
    banner = (
        '<div class="d2-banner" id="d2-banner">\n'
        '  ' + BADGE + '\n'
        '  <div class="d2-banner-body"><b>本页画法参数已改为「读 D2」</b>'
        '（构建期注入 · <code>d2_techniques.json</code> → <code>src/d2/d2_inject.py</code>）：'
        'STEP 5 的留白率 / 三远、STEP 6 的含水 / 墨阶 / 笔法不再逐首硬编码，'
        '由 D2 现算后写入；下表带淡蓝底纹的单元格即为 D2 拥有的字段。'
        'C 组新算子（视点 G7 / 天候 G4 / 构图 G1 / 材质 G6 / 笔法质量维 G2 / 时辰 G5 / 钤印 G8）'
        '已注入 <b>5.1–5.3</b> / <b>6.6–6.7</b> / <b>7.2–7.3</b>。\n'
        f'    <div class="d2-diff">留白率区间：{rho_txt}　·　三远：{yuan}　·　皴法：{cun}</div>\n'
        '  </div>\n'
        '</div>'
    )
    return html.replace('</header>', '</header>\n\n' + banner, 1)



def put_badge(sec_text, step):
    # 注意：sec_text 从 <span class="sec-no"> 起，不含其外层 <div class="sec-head">
    pat = re.compile(r'(<span class="sec-no">STEP %d</span>.*?)(</div>)' % step, re.S)
    if 'class="d2-badge"' in sec_text:
        return sec_text
    return pat.sub(lambda m: m.group(1) + BADGE + m.group(2), sec_text, count=1)


def put_note(sec_text, note_html):
    if 'class="d2-note"' in sec_text:
        return re.sub(r'<p class="d2-note">.*?</p>', note_html, sec_text, count=1, flags=re.S)
    m = re.search(r'<p class="sec-note">.*?</p>', sec_text, re.S)
    if not m:
        return sec_text
    return sec_text[:m.end()] + '\n  ' + note_html + sec_text[m.end():]


# ---------------------------------------------------------------- 快照
def build_payload(pid, r, zones):
    zmap = {}
    by = {b["surface"]: b for b in r["nodes"]}
    for label, node in zones.items():
        if node is None or node not in by:
            continue
        b = by[node]
        zmap[label] = {
            "node": b["surface"], "class": b["class"], "role": b["role"],
            "yuan": b["yuan_candidates"], "cun": b["cun"],
            "ink_grade": b["ink_grade"], "ink_c_range": b["ink_c_range"],
            "water": b["water"], "stroke": b["stroke"], "layer": b["layer"],
        }
        if b.get("size"):                       # 仅人物节点（figure_layer）
            zmap[label]["size"] = b["size"]
    return {
        "generated_by": "src/d2/d2_inject.py",
        "source": "d2_techniques.json + o2_imagery.json",
        "poem": pid, "title": r["title"],
        "poem_level": {
            "yuan": r["yuan"], "cun": r["cun"], "blank_range": r["blank_range"],
            "season": r["season"], "format_candidates": r["format_candidates"],
            "motion": r["motion"], "silence_ratio": r["silence_ratio"],
            "yuan_applicable": r["yuan_applicable"],
            "polarity": r["polarity"], "base_tone": r["base_tone"],
            "paradigm": r["paradigm"], "ink_methods": r["ink_methods"],
            # C 组·新算子（G1/G2/G4/G5/G6/G7/G8）
            "viewpoint": r["viewpoint"], "weather": r["weather"],
            "time_of_day": r["time_of_day"], "material": r["material"],
            "stroke_quality": r["stroke_quality"], "composition": r["composition"],
            "seal": r["seal"],
        },
        "zones": zmap,
    }


def snapshot_script(payload):
    js = json.dumps(payload, ensure_ascii=False, indent=2).replace('</', '<\\/')
    return ('<script type="application/json" id="d2-snapshot">\n'
            + js + '\n</script>')


def put_snapshot(html, script):
    if 'id="d2-snapshot"' in html:
        return re.sub(r'<script type="application/json" id="d2-snapshot">.*?</script>',
                      lambda m: script, html, count=1, flags=re.S)
    return html.replace('</body>', '  ' + script + '\n</body>', 1)


# 徽标/横幅为「一次性插入、不随重跑刷新」，早期版本写的是裸脚本名。
# 这里做一次幂等归一，把历史残留的裸名补成带目录的全路径。
STALE_REFS = (
    ('（d2_techniques.json → d2_inject.py）',
     '（d2_techniques.json → src/d2/d2_inject.py）'),
    ('<code>d2_techniques.json</code> → <code>d2_inject.py</code>',
     '<code>d2_techniques.json</code> → <code>src/d2/d2_inject.py</code>'),
)


def refresh_script_refs(html):
    for old, new in STALE_REFS:
        html = html.replace(old, new)
    return html


# ---------------------------------------------------------------- 注入主体
def inject_jx_bd(html, pid, r, spec, payload):
    by = {b["surface"]: b for b in r["nodes"]}
    lo, hi = r["blank_range"]
    spans = step_spans(html)
    s5spec = spec["step5"]

    # ---- STEP 5
    def s5(sec):
        sec = put_badge(sec, 5)
        yuan = ' + '.join(r["yuan"]) if r["yuan"] else '不适用'
        cun = ' + '.join(r["cun"]) if r["cun"] else '不适用'
        sec = put_note(sec, f'<p class="d2-note">D2 画法束（构建期注入 · '
                            f'<code>d2_techniques.json</code>）：三远 = {yuan}　·　皴法 = {cun}'
                            f'　·　留白 ρ ∈ {fmt_range(lo, hi)}。'
                            f'C 组算子（视点 G7 / 天候 G4 / 构图 G1）见 <b>5.1–5.3</b>。</p>')

        # 留白率 ρ
        hit = find_row(sec, s5spec["rho_row"])
        if hit:
            _, _, row = hit
            tds = TD_RE.findall(row)
            rng_col, vd_col = s5spec["rho_range_col"], s5spec["rho_verdict_col"]
            target = tds[rng_col][1]
            new_target = re.sub(r'\[[\d.]+\s*,\s*[\d.]+\]', fmt_range(lo, hi), target, count=1)
            solver = strip_tags(tds[2][1])
            try:
                rho = float(solver)
            except ValueError:
                rho = None
            ok = rho is not None and lo <= rho <= hi
            vd = f'✓ 通过（{fmt_num(rho)} ∈ {fmt_range(lo, hi)}）' if ok else \
                 f'✗ 越界（{solver} ∉ {fmt_range(lo, hi)}）'
            sec, _ = edit_row(sec, s5spec["rho_row"], {
                rng_col: (new_target, f"poem_level.blank_range", None),
                vd_col: (vd, f"poem_level.blank_range", "ok" if ok else "bad"),
            })

        # 三远法
        hit = find_row(sec, s5spec["yuan_row"])
        if hit:
            _, _, row = hit
            d2res = ' + '.join(r["yuan"])
            solver = clean_cell(row, s5spec["yuan_result_col"])
            for pre in (d2res + ' · ', d2res):
                if solver.startswith(pre):
                    solver = solver[len(pre):].strip()
                    break
            new_res = d2res + (f' · {solver}' if solver else '')
            ok = bool(r["yuan"])
            sec, _ = edit_row(sec, s5spec["yuan_row"], {
                s5spec["yuan_result_col"]: (new_res, "poem_level.yuan", "num"),
                s5spec["yuan_verdict_col"]: ('✓', "poem_level.yuan", "ok" if ok else "bad"),
            })
        sec = put_c_step5(sec, r)
        return sec

    # ---- STEP 6
    def s6(sec):
        sec = put_badge(sec, 6)
        note = ('<p class="d2-note">本表含水 p / 墨阶 / 笔法由 D2 构建期注入'
                '（<code>d2_techniques.json</code> → <code>src/d2/d2_inject.py</code>）；'
                '墨浓度 c 为卡6 求解值，就地按 D2 墨阶区间判读。')
        if spec["step6"].get("size_col") is not None:
            note += ('人物行的<b>尺寸档</b>由 <code>figure_layer</code> 调制器给出'
                     '（郭熙「三远与人物」：景深 → 尺寸；非人物行「—」）。')
        note += ('底色候选（A 组：季节色 + 极性色）见 <b>6.3</b>，'
                 '设色范式（G3）见 <b>6.4</b>，墨法轴（G11）见 <b>6.5</b>，'
                 '材质系数（G6）见 <b>6.6</b>，笔法质量维（G2）见 <b>6.7</b>；'
                 '精确底色 / 用色 / 墨法均由卡6 在候选内求解。')
        note += '</p>'
        sec = put_note(sec, note)
        wc, cc, sc = spec["step6"]["cols"]
        for label, node in spec["zones"].items():
            if node is None or node not in by:
                continue
            b = by[node]
            is_void = b["role"] in VOID_ROLES or b["ink_grade"] == "留白"
            _, _, row = find_row(sec, label)
            edits = {}
            if not is_void:
                edits[wc] = (b["water"], f"zones.{label}.water", "num")
                edits[sc] = (merge_stroke(b["stroke"], clean_cell(row, sc)),
                             f"zones.{label}.stroke", None)
            clo, chi = b["ink_c_range"]
            ctxt = clean_cell(row, cc)
            try:
                cval = float(ctxt)
            except ValueError:
                cval = None
            ok = (cval is not None and clo <= cval <= chi) if not is_void else (cval == 0)
            grade = b["ink_grade"]
            tag = (f'<span class="d2-tag{" warn" if not ok else ""}" '
                   f'title="D2 墨阶 {grade} ∈ {fmt_range(clo, chi)}；实测 c={ctxt}'
                   f'{" ✓" if ok else " ✗"}">{grade}</span>')
            edits[cc] = (f'{ctxt} {tag}', f"zones.{label}.ink_grade", "num")
            sec, _ = edit_row(sec, label, edits)
        sec = put_size_column(sec, spec, by)
        sec = put_base_tone_card(sec, r)
        sec = put_card(sec, "d2-paradigm", paradigm_card(r))
        sec = put_card(sec, "d2-ink-method", ink_method_card(r))
        sec = put_c_step6(sec, r)
        return sec

    # ---- STEP 7
    def s7(sec):
        sec = put_badge(sec, 7)
        sec = put_note(sec, '<p class="d2-note">时辰（G5）定段长乘子 / 墨偏；'
                            '钤印（G8）定印位与印面档，纳入卡7 段尾静默。'
                            'D2 只给档与区间，精确时长 / 布局由卡7 求解。</p>')
        sec = put_c_step7(sec, r)
        return sec

    html = edit_section(html, spans, 5, s5)
    spans = step_spans(html)
    html = edit_section(html, spans, 6, s6)
    spans = step_spans(html)
    html = edit_section(html, spans, 7, s7)
    return html


def inject_jys(html, pid, r, spec, payload):
    lo, hi = r["blank_range"]
    by = {b["surface"]: b for b in r["nodes"]}
    spans = step_spans(html)

    def s5(sec):
        sec = put_badge(sec, 5)
        sec = re.sub(r'\[[\d.]+\s*,\s*[\d.]+\]', fmt_range(lo, hi), sec, count=1)
        sec = put_note(sec, f'<p class="d2-note">D2 留白约束（构建期注入 · '
                            f'<code>d2_techniques.json</code>）：ρ ∈ {fmt_range(lo, hi)}'
                            f'；三远/皴法不适用（室内小景）。'
                            f'C 组算子（视点 G7 / 天候 G4 / 构图 G1）见 <b>5.1–5.3</b>。</p>')
        sec = put_c_step5(sec, r)
        return sec

    def s6(sec):
        sec = put_badge(sec, 6)
        sec = put_note(sec, '<p class="d2-note">墨分五色为诗级设计分层（含 design 附加：'
                            '背影、窗棂）；D2 覆盖的对象就地标注其墨阶与区间，供交叉复核。'
                            '底色候选（A 组）见 <b>6.3</b>，设色范式（G3）见 <b>6.4</b>，'
                            '墨法轴（G11）见 <b>6.5</b>，材质系数（G6）见 <b>6.6</b>，'
                            '笔法质量维（G2）见 <b>6.7</b>。</p>')
        oc = spec["step6"]["object_col"]
        for grade_label, node in spec["ink_rows"].items():
            if node not in by:
                continue
            b = by[node]
            hit = find_row(sec, grade_label)
            if not hit:
                continue
            _, _, row = hit
            orig = clean_cell(row, oc)
            clo, chi = b["ink_c_range"]
            tag = (f'<span class="d2-tag" title="D2 墨阶 {b["ink_grade"]} ∈ '
                   f'{fmt_range(clo, chi)}">{b["ink_grade"]}</span>')
            sec, _ = edit_row(sec, grade_label, {
                oc: (orig + ' ' + tag, f"zones.{grade_label}.ink_grade", None),
            })
        sec = put_base_tone_card(sec, r)
        sec = put_card(sec, "d2-paradigm", paradigm_card(r))
        sec = put_card(sec, "d2-ink-method", ink_method_card(r))
        sec = put_c_step6(sec, r)
        return sec

    def s7(sec):
        sec = put_badge(sec, 7)
        sec = put_note(sec, '<p class="d2-note">时辰（G5）定段长乘子 / 墨偏；'
                            '钤印（G8）定印位与印面档，纳入卡7 段尾静默。'
                            'D2 只给档与区间，精确时长 / 布局由卡7 求解。</p>')
        sec = put_c_step7(sec, r)
        return sec

    html = edit_section(html, spans, 5, s5)
    spans = step_spans(html)
    html = edit_section(html, spans, 6, s6)
    spans = step_spans(html)
    html = edit_section(html, spans, 7, s7)
    return html


# ---------------------------------------------------------------- 主流程
def do_inject(t, imagery, only=None):
    for pid, spec in POEMS.items():
        if only and pid != only:
            continue
        r = R.resolve_poem(t, pid, imagery)
        payload = build_payload(pid, r, spec.get("zones", spec.get("ink_rows", {})))
        path = os.path.join(ROOT, "dist", "pipelines", spec["file"])
        html = load_text(path)
        if 'id="d2-style"' in html:
            html = re.sub(r'<style id="d2-style">.*?</style>',
                          lambda m: CSS, html, count=1, flags=re.S)
        else:
            html = html.replace('</head>', '  ' + CSS + '\n</head>', 1)
        html = put_banner(html, pid, r, spec)
        if pid == "jys":
            html = inject_jys(html, pid, r, spec, payload)
        else:
            html = inject_jx_bd(html, pid, r, spec, payload)
        html = put_snapshot(html, snapshot_script(payload))
        html = refresh_script_refs(html)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✓ {spec['file']}  ← D2({r['title']})  "
              f"三远={'+'.join(r['yuan']) or '—'}  ρ∈{fmt_range(*r['blank_range'])}")


def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def do_check(t, imagery):
    bad = 0
    for pid, spec in POEMS.items():
        r = R.resolve_poem(t, pid, imagery)
        payload = build_payload(pid, r, spec.get("zones", spec.get("ink_rows", {})))
        html = load_text(os.path.join(ROOT, "dist", "pipelines", spec["file"]))
        m = re.search(r'<script type="application/json" id="d2-snapshot">(.*?)</script>',
                      html, re.S)
        if not m:
            print(f"  ✗ {spec['file']}：缺 D2 快照"); bad += 1; continue
        got = json.loads(m.group(1).replace('<\\/', '</'))
        ok = got == payload
        # 逐字段定位偏差
        diffs = []
        if got.get("poem_level") != payload["poem_level"]:
            for k, v in payload["poem_level"].items():
                if got.get("poem_level", {}).get(k) != v:
                    diffs.append(f"poem_level.{k}: {got.get('poem_level',{}).get(k)} → {v}")
        if got.get("zones") != payload["zones"]:
            for k, v in payload["zones"].items():
                if got.get("zones", {}).get(k) != v:
                    diffs.append(f"zones.{k}")
        print(f"  {'✓' if ok else '✗'} {spec['file']}：快照{'一致' if ok else '漂移'}"
              + (('  ' + '; '.join(diffs[:6])) if diffs else ''))
        if not ok:
            bad += 1
    print(f"\n  {'✓ 全部一致' if bad == 0 else f'✗ {bad} 首漂移'}（快照 vs 现算 D2）")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--poem", choices=list(POEMS.keys()))
    args = ap.parse_args()

    t = load(os.path.join(ROOT, "data", "derived", "d2_techniques.json"))
    imagery = load(os.path.join(ROOT, "data", "derived", "o2_imagery.json"))

    if args.check:
        print("[D2 → pipeline] 快照校验")
        sys.exit(1 if do_check(t, imagery) else 0)

    print("[D2 → pipeline] 构建期注入")
    do_inject(t, imagery, args.poem)
    print("\n  复核：python src/d2/d2_inject.py --check")


if __name__ == "__main__":
    main()
