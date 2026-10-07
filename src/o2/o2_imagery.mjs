// o2_imagery.mjs —— O2 意象抽取半自动化
// 四步（与路线图 O2 一一对应）：
//   ① 格律先验分词  [PLUG] 真链路 = T15 TopWORDS-Poetry 格律先验
//   ② 名词意象抽取  [PLUG] 真链路 = C1 Albert-BiLSTM-MHA-CRF
//   ③ 依存消歧      [PLUG] 真链路 = B2 UD-Kanbun / guwencombo（O6 顺带产出）
//   ④ 可画性门控（C5）：可画性低 → 标记「不宜实写，应留白／虚写」
// 产出：o2_imagery.json（意象表 + 正负节点 + 复核队列）、o2_imagery_report.md
// 验证：与人工 gold（o2_gold.json）逐列比对，并与画面元素（o1_source_facts.json）交叉核对。
// 模型未接入时用「词典 + 规则」替身跑通接口；替换时只动标了 [PLUG] 的函数，schema 不变。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));
const has = f => fs.existsSync(datapath(f));

const LEX = rd('o2_lexicon.json');
const GOLD = rd('o2_gold.json');
const GATE = rd('o2_gate.json');   // G13：虚实阈值真源（不写死在代码里）
const FACTS = has('o1_source_facts.json') ? rd('o1_source_facts.json') : null;
const W = LEX.words;
const ARGV = process.argv.slice(2);
const CHECK = ARGV.includes('--check');
const CALIBRATE = ARGV.includes('--calibrate');

/* 格律顿：五言在 2 字后，七言在 2、4 字后（音节顿位置） */
const caesurae = per => (per === 5 ? [2] : per === 7 ? [2, 4] : []);

/* ================= ① 格律先验分词 [PLUG] =================
   动态规划求最大似然切分：Σ score(词) ，约束 Σ len = 每句字数；
   格律顿位置给边界加分（先验）。词典命中加分、多字词加分。 */
function segment(line, form) {
  const n = line.length;
  const byFirst = {};
  for (const w of Object.keys(W)) { (byFirst[w[0]] ||= []).push(w); }
  for (const k of Object.keys(byFirst)) byFirst[k].sort((a, b) => b.length - a.length);

  const score = w => {
    const lex = !!W[w];
    // 词长收益 + 词典命中，再减「按词计费」的常数：避免两个单字词拼过一个大词（猿|声 > 猿声）
    return (lex ? 1.0 : 0) + w.length * 1.0 + (w.length - 1) * 0.5 - 0.6;
  };
  const best = new Array(n + 1).fill(null);
  best[0] = { s: 0, toks: [] };
  for (let i = 0; i < n; i++) {
    if (!best[i]) continue;
    for (const w of (byFirst[line[i]] || [])) {
      if (line.startsWith(w, i)) {
        const j = i + w.length;
        let sc = best[i].s + score(w);
        if (caesurae(form.perLine).includes(j) && j < n) sc += 0.3;   // 格律先验
        if (!best[j] || sc > best[j].s) best[j] = { s: sc, toks: [...best[i].toks, { w, i, len: w.length }] };
      }
    }
    // 允许单字兜底（未登录词）
    const j = i + 1, sc = best[i].s + 0.4;
    if (!best[j] || sc > best[j].s) best[j] = { s: sc, toks: [...best[i].toks, { w: line[i], i, len: 1 }] };
  }
  const toks = best[n].toks.map(t => {
    const e = W[t.w] || null;
    return { w: t.w, pos: e ? e.pos : 'x', i: t.i, len: t.len, span: [t.i + 1, t.i + t.len], e };
  });
  return { toks, sum: toks.reduce((a, t) => a + t.len, 0), perLine: form.perLine, ok: toks.reduce((a, t) => a + t.len, 0) === n };
}

/* ================= ② 名词意象抽取 [PLUG] ================= */
const isImagery = t => t.pos === 'n' || t.pos === 'nq';
const isAction = t => t.pos === 'v' && t.e && t.e.action;
const canonOf = t => (t.e && t.e.canonical) || t.w;

/* ================= ③ 依存消歧 [PLUG] ================= */
/* 逐句建边：否定存在 / 处所 / 并列 / 定中（词内）。
   歧义句（如「孤舟蓑笠翁」）同时给出候选读法与取舍理由。 */
function parseLine(toks, line) {
  const edges = [], notes = [];
  const idx = toks.map((t, k) => ({ t, k })).filter(x => isImagery(x.t) || isAction(x.t));

  // 否定存在：负谓词（飞绝/灭/不住）回指同句最近的意象
  for (let k = 0; k < toks.length; k++) {
    const t = toks[k];
    if (t.pos === 'v' && t.e && t.e.neg) {
      for (let m = k - 1; m >= 0; m--) {
        if (isImagery(toks[m])) { edges.push({ from: canonOf(toks[m]), to: t.w, rel: 'neg-exist', src: 'rule:neg' }); break; }
      }
    }
  }
  // 处所：方位后置词（间）／处所名词（岸/洲/汀）指向后续或前置意象
  for (let k = 0; k < toks.length; k++) {
    const t = toks[k];
    if (t.e && t.e.locative && t.pos !== 'postp') {
      for (let m = k + 1; m < toks.length; m++) {
        if (isImagery(toks[m])) { edges.push({ from: canonOf(toks[m]), to: canonOf(t), rel: 'locative', src: 'rule:loc' }); break; }
      }
    }
    if (t.pos === 'postp' && t.e && t.e.locative) {
      for (let m = k - 1; m >= 0; m--) {
        if (isImagery(toks[m])) { edges.push({ from: canonOf(toks[m]), to: t.w, rel: 'locative', src: 'rule:loc' }); break; }
      }
    }
  }
  // 并列：相邻意象、中间无谓词 → coexist
  for (let k = 1; k < toks.length; k++) {
    const a = toks[k - 1], b = toks[k];
    if (isImagery(a) && isImagery(b)) edges.push({ from: canonOf(a), to: canonOf(b), rel: 'coexist', src: 'rule:adjacent' });
  }
  // 词内修饰（千山=千+山 等）已在词典 mod 字段，登记为 intra 边
  for (const t of toks) if (t.e && t.e.mod) edges.push({ from: t.w, to: t.e.head || t.w, rel: 'mod(intra)', src: 'lexicon:mod' });

  // 歧义句显式登记（供人工复核）
  const surf = toks.map(t => t.w).join('');
  if (/孤舟蓑笠翁/.test(surf)) notes.push({
    span: surf, chosen: '两个并列意象（孤舟 ‖ 蓑笠翁）', alt: '「孤舟上的蓑笠翁」定中／领属（合并为一）',
    why: '① 五言 2/3 顿把「孤舟」与「蓑笠翁」切在顿的两侧；② 全诗节点两两成对（千山/万径、鸟/人踪、孤舟/蓑笠翁），并列读法维持对仗；③ 「独钓」以「翁」为施事，合并则「独钓」失独立主体。',
    need_review: true,
  });
  if (/寒江雪/.test(surf)) notes.push({
    span: surf, chosen: '两个意象（寒江 ‖ 雪）', alt: '「寒江之雪」定中（合并为一）',
    why: '「雪」为全域覆盖物，「寒江」为水域；二者景深不同（中景／全域），gold 亦分列。', need_review: true,
  });
  if (/两岸猿声/.test(surf)) notes.push({
    span: surf, chosen: '处所+主体（两岸 ⊃ 猿声）', alt: '「两岸的猿声」定中',
    why: '「两岸」标处所、「猿声」为主体；猿声为听觉通道，视觉不画。', need_review: false,
  });
  return { edges, notes };
}

/* ================= ④ 可画性门控（C5） ================= */
/* 阈值来自 data/source/o2_gate.json（G13 标定）；null 可画性取中性 0.5（落虚写档）。 */
function gate(node) {
  const e = node.e || {};
  if (node.neg_kind === '缺席') return { class: '不画（负节点）', render: '约束留白的面积与连通性', basis: '否定性存在：本该有而没有' };
  if (node.neg_kind === '跨通道') return { class: '视觉不画（听觉正）', render: '约束音频轨与视觉轨的相位差', basis: '听觉通道为正、视觉通道为负' };
  if (isAction(node)) return { class: '动作（以钓丝／船迹代形）', render: '以轨迹而非实体呈现', basis: '动词意象，无独立实体' };
  const c = e.conc == null ? 0.5 : e.conc;
  const T = GATE.thresholds;
  if (c >= T.real) return { class: '实写', render: '直接绘制', basis: `可画性 ${c} ≥ ${T.real}` };
  if (c >= T.blank) return { class: '虚写', render: '淡染／留白式表现，仍占位', basis: `可画性 ${c} ∈ [${T.blank}, ${T.real})` };
  return { class: '不可实写', render: '留白／转译为空间或时间量感', basis: `可画性 ${c} < ${T.blank}` };
}

/* ================= 主流程 ================= */
const poems = ['jx', 'bd'];
const out = { meta: {}, poems: {} };
const review = [];

for (const p of poems) {
  const G = GOLD.poems[p];
  const form = G.form;
  const nodes = [], allEdges = [], allNotes = [];
  let segOk = true;

  G.text.forEach((line, li) => {
    const seg = segment(line, form);
    if (!seg.ok) segOk = false;
    const { edges, notes } = parseLine(seg.toks, line);
    allEdges.push(...edges.map(e => ({ ...e, line: li + 1 })));
    allNotes.push(...notes.map(n => ({ ...n, line: li + 1 })));

    // 先收集本句意象，再定负节点
    const lineImagery = seg.toks.filter(t => isImagery(t) || isAction(t));
    const negHeads = new Set(edges.filter(e => e.rel === 'neg-exist').map(e => e.from));
    for (const t of lineImagery) {
      const canonical = canonOf(t);
      const e = t.e || {};
      let neg_kind = null;
      if (negHeads.has(canonical)) neg_kind = '缺席';
      else if (e.audio || e.channel === 'a') neg_kind = '跨通道';
      const node = {
        id: `${p}-${li + 1}-${t.span[0]}`, poem: p, surface: t.w, canonical, line: li + 1, span: t.span,
        pos: t.pos, channel: e.channel || (t.pos === 'v' ? 'v' : 'v'),
        conc: e.conc == null ? null : e.conc, neg_kind,
        layer_hint: e.layer || null, layer_source: e.layer ? 'lexicon-hint' : null,
        polarity_hint: e.polarity || null, polarity_source: e.polarity ? 'lexicon-hint' : null,
        focus: !!e.focus, e,
      };
      node.gate = gate(node);
      nodes.push(node);
    }
  });

  // 复核队列：歧义句 / 未登录词 / 低置信（词典缺可画性）
  for (const n of allNotes) if (n.need_review) review.push({ poem: p, kind: '歧义句', line: n.line, item: n.span, detail: `取「${n.chosen}」，备选「${n.alt}」`, why: n.why });
  for (const nd of nodes) if (nd.conc == null) review.push({ poem: p, kind: '未登录词', line: nd.line, item: nd.surface, detail: '词典无可画性初值，需人工给值' });

  const act = nodes.filter(n => !n.neg_kind && n.gate.class.startsWith('动作'));
  const neg = nodes.filter(n => n.neg_kind);
  const blank = nodes.filter(n => !n.neg_kind && n.gate.class === '不可实写');
  const pos = nodes.filter(n => !n.neg_kind && (n.gate.class === '实写' || n.gate.class === '虚写'));

  out.poems[p] = {
    title: G.title, author: G.author, form, text: G.text,
    segment_ok: segOk,
    nodes, edges: allEdges, disambiguation: allNotes,
    nodes_summary: {
      正节点: pos.map(n => n.canonical),
      留白节点: blank.map(n => n.canonical),
      负节点: neg.map(n => ({ canonical: n.canonical, kind: n.neg_kind })),
      动作节点: act.map(n => n.canonical),
    },
    counts: { imagery: nodes.length, pos: pos.length, blank: blank.length, neg: neg.length, action: act.length },
  };
}

/* ================= 验证 vs gold ================= */
function validate(p) {
  const gold = GOLD.poems[p].rows, got = out.poems[p].nodes;
  const gotBy = {}; for (const n of got) gotBy[n.canonical] = n;
  const goldBy = {}; for (const r of gold) goldBy[r.canonical] = r;
  const rows = [];
  // 类型映射：门控档 → gold 类型词表
  const clsMap = n => n.neg_kind === '缺席' ? '负节点-缺席'
    : n.neg_kind === '跨通道' ? '负节点-跨通道'
    : n.gate.class.startsWith('动作') ? '动作'
    : n.gate.class;
  for (const r of gold) {
    const g = gotBy[r.canonical];
    rows.push({
      canonical: r.canonical, in_gold: true, in_auto: !!g,
      line: g ? (g.line === r.line) : null,
      span: g ? (g.span[0] === r.span[0] && g.span[1] === r.span[1]) : null,
      class_gold: r.gold_class, class_auto: g ? clsMap(g) : null,
      class_ok: g ? (clsMap(g) === r.gold_class) : null,
    });
  }
  const extra = got.filter(n => !goldBy[n.canonical]).map(n => ({ canonical: n.canonical, line: n.line, class_auto: clsMap(n) }));
  const recall = rows.filter(r => r.in_auto).length / rows.length;
  const precision = rows.filter(r => r.in_auto).length / got.length;
  const lineOk = rows.filter(r => r.line === true).length / rows.length;
  const spanOk = rows.filter(r => r.span === true).length / rows.length;
  const classOk = rows.filter(r => r.class_ok === true).length / rows.length;
  return { recall, precision, lineOk, spanOk, classOk, rows, extra };
}

out.validation = {};
for (const p of poems) out.validation[p] = validate(p);

/* ================= 交叉核对 vs 画面 ================= */
out.crosscheck = {};
if (FACTS) {
  for (const p of poems) {
    const map = GOLD.drawn_map[p];
    const drawnImagery = [];
    for (const m of map) if (m.role === 'imagery' && m.canonical) { drawnImagery.push(m.canonical); if (m.with) drawnImagery.push(...m.with.split('/')); }
    const drawnNoSource = map.filter(m => m.role === 'imagery' && !m.canonical);
    const drawnDesign = map.filter(m => m.role === 'design');
    const nodes = out.poems[p].nodes;
    const byCanon = {}; for (const n of nodes) byCanon[n.canonical] = n;
    // 应画（实写/虚写正节点）却未在画面出现
    const missing = nodes.filter(n => !n.neg_kind && n.gate.class !== '动作（以钓丝／船迹代形）' && ['实写', '虚写'].includes(n.gate.class) && !drawnImagery.includes(n.canonical))
      .map(n => ({ canonical: n.canonical, class: n.gate.class, line: n.line }));
    // 画中有、意象表无
    const extra_in_art = drawnNoSource.map(m => ({ el: m.el, note: m.note || null }));
    // 负节点是否确实没画（应当缺席）
    const negLeak = nodes.filter(n => n.neg_kind && drawnImagery.includes(n.canonical)).map(n => n.canonical);
    out.crosscheck[p] = { drawnImagery, missing, extra_in_art, design_added: drawnDesign.map(m => ({ el: m.el, note: m.note || null })), negLeak };
  }
}

out.meta = {
  generated: new Date().toISOString().slice(0, 19),
  lexicon: 'o2_lexicon.json @ v' + LEX.meta.version,
  gold: 'o2_gold.json @ v' + GOLD.meta.version,
  gate: 'o2_gate.json @ v' + GATE.meta.version + ' · real=' + GATE.thresholds.real + ' blank=' + GATE.thresholds.blank,
  pluggable: { '①分词': 'T15 TopWORDS-Poetry 格律先验', '②意象': 'C1 Albert-BiLSTM-MHA-CRF', '③消歧': 'B2 UD-Kanbun / guwencombo' },
  current: '词典 + 规则替身（模型未接入）；接口固定，替换 [PLUG] 函数即可',
  scope_note: '层级与极性为词典提示，非可自动推断项；正式层级由 O4 构图求解器给出。',
};
out.review_queue = review;

fs.writeFileSync(path.join(ROOT, 'data', 'derived', 'o2_imagery.json'), JSON.stringify(out, null, 2));

/* ================= 控制台报告 ================= */
const pct = v => (v == null ? '—' : (v * 100).toFixed(1) + '%');
console.log('=== o2_imagery.json —— 意象抽取（格律分词 → 意象 → 消歧 → 可画性门控）===');
for (const p of poems) {
  const P = out.poems[p];
  console.log(`\n《${P.title}》${P.author} · ${P.form.name} · 分词校验 ${P.segment_ok ? '✓' : '✗'}`);
  console.log('  节点 ' + P.counts.imagery + '（正 ' + P.counts.pos + ' / 留白 ' + P.counts.blank + ' / 负 ' + P.counts.neg + ' / 动作 ' + P.counts.action + '）');
  for (const n of P.nodes) {
    const tag = n.neg_kind ? `负节点(${n.neg_kind})` : n.gate.class;
    console.log(`    ${String(n.line)}句 ${String(n.span[0])}–${String(n.span[1])}  ${n.canonical.padEnd(4, '　')}  ${tag}  通道=${n.channel}  可画性=${n.conc == null ? '—' : n.conc}`);
  }
  const v = out.validation[p];
  console.log(`  验证 gold：召回 ${pct(v.recall)} · 精确 ${pct(v.precision)} · 句 ${pct(v.lineOk)} · 位置 ${pct(v.spanOk)} · 类型 ${pct(v.classOk)}`);
  const c = out.crosscheck[p];
  console.log(`  画面核对：已画 ${c.drawnImagery.join('/') || '—'}｜应画未画 ${c.missing.length ? c.missing.map(m => m.canonical).join('/') : '无'}｜画中多出 ${c.extra_in_art.length ? c.extra_in_art.map(m => m.el).join('/') : '无'}｜设计附加 ${c.design_added.length ? c.design_added.map(m => m.el).join('/') : '无'}｜负节点泄漏 ${c.negLeak.length ? c.negLeak.join('/') : '无'}`);
}
console.log('\n复核队列 ' + review.length + ' 条（歧义句 ' + review.filter(r => r.kind === '歧义句').length + ' / 未登录词 ' + review.filter(r => r.kind === '未登录词').length + ' / 层级待定 ' + review.filter(r => r.kind === '层级待定').length + '）');
console.log('-> o2_imagery.json');

/* ================= Markdown 报告 ================= */
const L = [];
L.push('# O2 意象抽取 · 报告', '');
L.push('- 生成：' + out.meta.generated);
L.push('- 词典：' + out.meta.lexicon + '　gold：' + out.meta.gold);
L.push('- 模型状态：' + out.meta.current);
L.push('- 可插拔接口：①分词=' + out.meta.pluggable['①分词'] + '　②意象=' + out.meta.pluggable['②意象'] + '　③消歧=' + out.meta.pluggable['③消歧'], '');
for (const p of poems) {
  const P = out.poems[p], v = out.validation[p], c = out.crosscheck[p];
  L.push('## 《' + P.title + '》' + P.author + '（' + P.form.name + '）', '');
  L.push('| 意象 | 句 | 位置 | 通道 | 可画性 | 档 | 层级(提示) | 极性(提示) |', '| --- | --- | --- | --- | --- | --- | --- | --- |');
  for (const n of P.nodes) {
    const cls = n.neg_kind ? '**负节点（' + n.neg_kind + '）**' : n.gate.class;
    L.push('| ' + n.canonical + ' | ' + n.line + ' | ' + n.span[0] + '–' + n.span[1] + ' | ' + n.channel + ' | ' + (n.conc == null ? '—' : n.conc) + ' | ' + cls + ' | ' + (n.layer_hint || '—') + ' | ' + (n.polarity_hint || '—') + ' |');
  }
  L.push('', '**正/负节点**：正 ' + (P.nodes_summary.正节点.join('、') || '—') + '；留白 ' + (P.nodes_summary.留白节点.join('、') || '—') + '；负 ' + (P.nodes_summary.负节点.map(x => x.canonical + '(' + x.kind + ')').join('、') || '—') + '；动作 ' + (P.nodes_summary.动作节点.join('、') || '—'), '');
  L.push('**消歧**：');
  for (const d of P.disambiguation) L.push('- 第' + d.line + '句「' + d.span + '」→ 取 **' + d.chosen + '**；备选：' + d.alt + (d.need_review ? '（需复核）' : ''));
  L.push('');
  L.push('**验证 gold**：召回 ' + pct(v.recall) + ' · 精确 ' + pct(v.precision) + ' · 句 ' + pct(v.lineOk) + ' · 位置 ' + pct(v.spanOk) + ' · 类型 ' + pct(v.classOk));
  const bad = v.rows.filter(r => r.class_ok === false || r.in_auto === false);
  if (bad.length) for (const b of bad) L.push('  - ✗ `' + b.canonical + '`：gold ' + b.class_gold + ' vs 自动 ' + (b.class_auto || '未抽出'));
  if (v.extra.length) for (const e of v.extra) L.push('  - ＋ 自动多出 `' + e.canonical + '`（gold 无）');
  L.push('');
  L.push('**画面核对**：已画 ' + (c.drawnImagery.join('、') || '—') + '；应画未画 ' + (c.missing.length ? c.missing.map(m => m.canonical).join('、') : '无') + '；画中多出 ' + (c.extra_in_art.length ? c.extra_in_art.map(m => '`' + m.el + '`' + (m.note ? '（' + m.note + '）' : '')).join('、') : '无') + '；设计附加 ' + (c.design_added.length ? c.design_added.map(m => '`' + m.el + '`' + (m.note ? '（' + m.note + '）' : '')).join('、') : '无') + '；负节点泄漏 ' + (c.negLeak.length ? c.negLeak.join('、') : '无'), '');
}
L.push('## 复核队列', '');
const kinds = ['歧义句', '未登录词'];
for (const k of kinds) { const items = review.filter(r => r.kind === k); if (!items.length) continue; L.push('### ' + k + '（' + items.length + '）', ''); for (const it of items) L.push('- 《' + it.poem + '》第' + it.line + '句 `' + it.item + '`：' + it.detail + (it.why ? ' —— ' + it.why : '')); L.push(''); }
fs.writeFileSync(path.join(ROOT, 'docs', 'reports', 'o2_imagery_report.md'), L.join('\n'));
console.log('-> o2_imagery_report.md');

/* ================= ⑤ 虚实阈值校准（G13） =================
   阈值真源在 data/source/o2_gate.json；本段负责重算（--calibrate）与校验（--check）。
   校准口径：相邻两类样本的中点（1D 最大裕度分界），使阈值到两侧最近样本裕度相等。
   证伪：把阈值推过任一侧最近样本，gold 分类必出错 —— 否则校验是「永远通过」的空断言。 */
const clsOf = (c, T) => c >= T.real ? '实写' : c >= T.blank ? '虚写' : '不可实写';

// 可门控行：排除负节点 / 动作（不走 conc 门），并要求 conc 有值
function gateRows() {
  const rows = [];
  for (const p of poems) for (const r of GOLD.poems[p].rows) {
    if (r.neg_kind || r.gold_class === '动作') continue;
    const e = W[r.surface] || W[r.canonical];
    if (!e || e.conc == null) continue;
    rows.push({ poem: p, canonical: r.canonical, conc: e.conc, gold: r.gold_class });
  }
  return rows;
}
function calibrate(rows) {
  const pick = cls => rows.filter(r => r.gold === cls).map(r => r.conc);
  const maxBlank = Math.max(...pick('虚写')), minReal = Math.min(...pick('实写'));
  const maxNone = Math.max(...pick('不可实写')), minBlank = Math.min(...pick('虚写'));
  const r4 = x => Math.round(x * 1e4) / 1e4;   // conc 为两位小数，阈值/裕度取四位即可，避免浮点长尾
  return {
    thresholds: { real: r4((maxBlank + minReal) / 2), blank: r4((maxNone + minBlank) / 2) },
    margins: { real: r4((minReal - maxBlank) / 2), blank: r4((minBlank - maxNone) / 2) },
    evidence: { max_blank: maxBlank, min_real: minReal, max_none: maxNone, min_blank: minBlank },
  };
}

const ROWS = gateRows();
const CAL = calibrate(ROWS);

if (CALIBRATE) {
  const frozen = {
    ...GATE,
    thresholds: CAL.thresholds,
    margins: CAL.margins,
    evidence: CAL.evidence,
    meta: { ...GATE.meta, generated: new Date().toISOString().slice(0, 10) },
  };
  fs.writeFileSync(datapath('o2_gate.json'), JSON.stringify(frozen, null, 2) + '\n');
  console.log(`\n[--calibrate] real=${CAL.thresholds.real} blank=${CAL.thresholds.blank} → o2_gate.json`);
}

if (CHECK) {
  const T = GATE.thresholds, chk = [];
  const add = (name, pass, got, want) => chk.push({ name, pass: !!pass, got, want });
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  add('阈值=最大裕度中点', near(T.real, CAL.thresholds.real) && near(T.blank, CAL.thresholds.blank),
    `real=${T.real} blank=${T.blank}`, `real=${CAL.thresholds.real} blank=${CAL.thresholds.blank}`);
  add('阈值落可行区间', CAL.evidence.max_blank < T.real && T.real <= CAL.evidence.min_real
    && CAL.evidence.max_none < T.blank && T.blank <= CAL.evidence.min_blank,
    `max_blank=${CAL.evidence.max_blank} real=${T.real} min_real=${CAL.evidence.min_real}｜max_none=${CAL.evidence.max_none} blank=${T.blank} min_blank=${CAL.evidence.min_blank}`,
    'max_blank<real≤min_real 且 max_none<blank≤min_blank');
  add('边界裕度>0', CAL.margins.real > 0 && CAL.margins.blank > 0,
    `real=±${CAL.margins.real} blank=±${CAL.margins.blank}`, '>0');
  const errs = ROWS.filter(r => clsOf(r.conc, T) !== r.gold);
  add('gold 分类全对', errs.length === 0, errs.map(r => `${r.canonical}:${r.gold}≠${clsOf(r.conc, T)}`).join('/') || '全对', '0 错');
  const pR = ROWS.filter(r => clsOf(r.conc, { ...T, real: CAL.evidence.max_blank }) !== r.gold);
  const pB = ROWS.filter(r => clsOf(r.conc, { ...T, blank: CAL.evidence.max_none }) !== r.gold);
  add('证伪·real 推过界必错', pR.length > 0, pR.map(r => r.canonical).join('/') || '无', '≥1 错');
  add('证伪·blank 推过界必错', pB.length > 0, pB.map(r => r.canonical).join('/') || '无', '≥1 错');
  const bad = chk.filter(c => !c.pass);
  console.log('\n=== O2 虚实阈值 G13 校验（o2_gate.json @ v' + GATE.meta.version + '）===');
  for (const c of chk) console.log(`  ${c.pass ? '✓' : '✗'} ${c.name}：${c.got}  (期望 ${c.want})`);
  console.log(`  合计 ${chk.length - bad.length}/${chk.length}  ${bad.length ? '✗ 未通过' : '✓ 全通过'}`);
  if (bad.length) process.exitCode = 1;
}
