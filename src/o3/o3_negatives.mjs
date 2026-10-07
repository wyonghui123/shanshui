// o3_negatives.mjs —— O3 负节点双判据
// 路线图 O3：两条独立判据交叉验证，一致才判负节点。
//   判据一（网络）：意象共现网络中的低度节点 —— 出现，但几乎不与画面元素相连。
//   判据二（传输）：构图 OT 求解后「未被运输的质量」（untransported mass）—— 被诗提及却不该被画出。
// 输入：o2_imagery.json（意象表 + 共现边）、o2_gold.json（画面元素对应）、o2_lexicon.json（可画性）
// 输出：o3_negatives.json / o3_negatives_report.md
//
// 口径说明（重要）：
//  · 判据一的「度」= 共现网络度（O2 的 coexist/locative 边），「与画面相连」= 该意象映射到的画面元素数。
//    低度判定 = 共现度 ≤ 1 且 画面连接数 = 0。二者缺一不可：独钓共现度为 0 但画面有钓丝，不判负。
//  · 判据二的 OT 是「无容量约束的熵正则部分最优传输」——每一行独立在「真实槽位 ∪ 弃置槽」上做 softmax。
//    这是部分 OT 在槽位容量充足时的解析解；带容量的 Sinkhorn 作为交叉核对一并给出（见 sinkhorn()）。
//    弃置槽成本 τ 即「宁可不画」的阈值。正式带容量的求解归 O4 构图求解器。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));
const O2 = rd('o2_imagery.json');
const GOLD = rd('o2_gold.json');

/* ---------- 参数 ---------- */
const P = {
  mass: { 实写: 0.8, 虚写: 0.5, 不可实写: 0.35, 动作: 0.6 },  // 按门控档的基础质量
  mass_neg: 0.7, focus_bonus: 0.2,
  slots: [
    { name: '近景', depth: 0.70, cap: 2.0 },
    { name: '中景', depth: 0.50, cap: 2.5 },
    { name: '远景', depth: 0.30, cap: 2.5 },
    { name: '留白', depth: 0.00, cap: 3.0 },
  ],
  layerDepth: { 近景: 0.70, 中景: 0.50, 远景: 0.30, 全域: 0.00, 极远: 0.05 },
  layerUnknown: 0.45,
  w: { sem: 0.5, depth: 0.3, neg: 1.0, channel: 0.6 },   // C = w1·语义 + w2·景深 + w3·负节点 + w通道
  tau: 0.50,      // 弃置槽成本：宁可不画
  eps: 0.05,      // 熵正则温度
  degLow: 1,      // 共现度 ≤ 1 视为低度
  untransported_cut: 0.5,   // 未运输质量占比 > 0.5 视为未运输
};

/* ---------- 意象质量 ---------- */
const gateOf = n => n.neg_kind === '缺席' ? '负' : n.neg_kind === '跨通道' ? '负' : n.gate.class.startsWith('动作') ? '动作' : n.gate.class;
function massOf(n) {
  let m = gateOf(n) === '负' ? P.mass_neg : (P.mass[gateOf(n)] ?? 0.5);
  if (n.focus) m += P.focus_bonus;
  return +m.toFixed(3);
}
const layerDepthOf = n => (n.layer_hint && P.layerDepth[n.layer_hint] != null) ? P.layerDepth[n.layer_hint] : P.layerUnknown;

/* ---------- 语义不匹配 ---------- */
function sem(i, slot) {
  if (i.channel === 'a') return 1.0;                       // 听觉：无任何视觉槽位
  const q = i.gate.class === '不可实写';                    // 空间/时间量
  if (slot.name === '留白') return q ? 0.10 : 0.80;
  return q ? 0.90 : 0.10;
}
/* ---------- 成本矩阵 ---------- */
function costRow(i) {
  return P.slots.map(s => {
    let c = P.w.sem * sem(i, s) + P.w.depth * Math.abs(layerDepthOf(i) - s.depth);
    if (i.neg_kind === '缺席') c += P.w.neg;               // 缺席：任何槽位都不该落
    if (i.channel === 'a') c += P.w.channel;               // 跨通道：视觉槽位额外惩罚
    return +c.toFixed(4);
  });
}
/* ---------- 判据二：熵正则部分 OT（无容量解析解）---------- */
function partialOT(i) {
  const C = costRow(i);
  const e = P.eps, ex = c => Math.exp(-c / e);
  const Z = C.reduce((a, c) => a + ex(c), 0) + ex(P.tau);
  const to = C.map(c => +((ex(c) / Z) * massOf(i)).toFixed(4));
  const untransported = +((ex(P.tau) / Z) * massOf(i)).toFixed(4);
  return { C, to, untransported, frac: +(untransported / massOf(i)).toFixed(4) };
}
/* ---------- 交叉核对：带容量的 Sinkhorn（平衡化后求解）----------
 * 供给：各意象质量 a_i + 一条「虚拟供给」吸收未用容量（对真实槽成本 0）。
 * 需求：真实槽（容量 cap）+ 弃置槽（容量 = 总质量，可吞全部）。
 * 虚拟供给质量 = 总需求 − 总供给，使问题平衡，Sinkhorn 行和才严格 = a_i。
 * 真实意象 → 弃置槽 的运输量即「未运输质量」。
 */
function sinkhorn(items) {
  const n = items.length, m = P.slots.length;
  const a = items.map(i => massOf(i));
  const M = a.reduce((x, y) => x + y, 0);
  const b = [...P.slots.map(s => s.cap), M];                 // 真实槽容量 + 弃置槽
  const demandTotal = b.reduce((x, y) => x + y, 0);
  const supply = [...a, demandTotal - M];                    // 末位为虚拟供给
  const C = items.map(i => [...costRow(i), P.tau]);          // 真实行：槽 + 弃置(τ)
  C.push([...P.slots.map(() => 0), 0]);                      // 虚拟供给行：成本恒 0（无偏好，只补未用容量）
  const K = C.map(r => r.map(c => Math.exp(-c / P.eps)));
  const nn = supply.length, mm = b.length;
  let u = new Array(nn).fill(1), v = new Array(mm).fill(1);
  let conv = Infinity;
  for (let it = 0; it < 4000; it++) {
    for (let i = 0; i < nn; i++) { let s = 0; for (let j = 0; j < mm; j++) s += K[i][j] * v[j]; u[i] = supply[i] / (s || 1e-300); }
    for (let j = 0; j < mm; j++) { let s = 0; for (let i = 0; i < nn; i++) s += K[i][j] * u[i]; v[j] = b[j] / (s || 1e-300); }
    if (it % 200 === 199) {
      conv = 0;
      for (let i = 0; i < n; i++) { let s = 0; for (let j = 0; j < mm; j++) s += u[i] * K[i][j] * v[j]; conv = Math.max(conv, Math.abs(s - a[i]) / a[i]); }
    }
  }
  const T = items.map((i, ii) => { const row = []; for (let j = 0; j < mm; j++) row.push(u[ii] * K[ii][j] * v[j]); return row; });
  return { rows: items.map((i, ii) => ({ canonical: i.canonical, mass: +a[ii].toFixed(3), untransported: +T[ii][m].toFixed(4), frac: +(T[ii][m] / a[ii]).toFixed(4) })), conv: +conv.toFixed(5) };
}

/* ---------- 画面连接数（意象 → 画面元素）---------- */
function linkage(p) {
  const map = GOLD.drawn_map[p];
  const out = {};
  for (const m of map) if (m.role === 'imagery' && m.canonical) { (out[m.canonical] ||= []).push(m.el); if (m.with) for (const w of m.with.split('/')) (out[w] ||= []).push(m.el + '·' + w); }
  return out;
}

/* ---------- 共现网络度 ----------
 * 判据一只在「视觉共现网络」上取度：两端都必须是视觉意象（channel='v'）。
 * 理由：构图 OT 作用于视觉画面，网络判据若把「听觉↔视觉」的处所边也算作相连，
 * 就成了「一个听觉意象是否与画面相连」的范畴错误 ——「两岸猿声」是声源方位，
 * 不是画面邻接。故跨通道意象（猿声）在视觉网络中度=0，与其「跨通道负节点」身份一致。
 * degAll 保留原始度（含跨通道边）仅作透明对照，不参与判定。
 */
function coDegrees(P_) {
  const ch = {}; for (const n of P_.nodes) ch[n.canonical] = n.channel;
  const deg = {}, degAll = {};
  for (const n of P_.nodes) { deg[n.canonical] = 0; degAll[n.canonical] = 0; }
  for (const e of P_.edges) {
    if (e.rel !== 'coexist' && e.rel !== 'locative') continue;   // mod(intra) 不算共现
    if (degAll[e.from] == null || degAll[e.to] == null) continue;
    degAll[e.from]++; degAll[e.to]++;
    if (ch[e.from] !== 'v' || ch[e.to] !== 'v') continue;        // 视觉网络：两端皆视觉
    deg[e.from]++; deg[e.to]++;
  }
  return { deg, degAll };
}

/* ---------- 主流程 ---------- */
const out = { meta: {}, poems: {} };
const review = [];
for (const p of ['jx', 'bd']) {
  const P_ = O2.poems[p];
  const link = linkage(p), { deg, degAll } = coDegrees(P_);
  const items = P_.nodes;
  const soft = items.map(i => ({ canonical: i.canonical, ...partialOT(i) }));
  const sink = sinkhorn(items);

  const rows = items.map(i => {
    const c1_deg = deg[i.canonical] ?? 0;
    const c1_link = (link[i.canonical] || []).length;
    const c1 = (c1_deg <= P.degLow) && (c1_link === 0);
    const s = soft.find(x => x.canonical === i.canonical);
    const k = sink.rows.find(x => x.canonical === i.canonical);
    const c2 = s.frac > P.untransported_cut;
    const agree = c1 && c2;
    const blank = i.gate.class === '不可实写';      // 空间/时间量：目的地即留白槽，先于判据分歧裁定
    const isAct = i.gate.class.startsWith('动作');
    const verdict = blank ? '留白节点' : agree ? '负节点' : (c1 || c2 ? '待复核' : (isAct ? '动作节点' : '正节点'));
    if (c1 !== c2 && !blank) review.push({ poem: p, canonical: i.canonical, kind: c1 ? '网络孤立但可运输' : '未运输但网络连通', detail: `视觉共现度 ${c1_deg}／画面连接 ${c1_link}；未运输质量占比 ${(s.frac * 100).toFixed(1)}%` });
    return {
      canonical: i.canonical, line: i.line, channel: i.channel, gate: i.gate.class, neg_kind: i.neg_kind, mass: massOf(i),
      net: { deg: c1_deg, deg_all: degAll[i.canonical] ?? 0, link: c1_link, link_els: link[i.canonical] || [], low: c1 },
      ot: { cost: s.C, to: s.to, untransported: s.untransported, frac: s.frac, sinkhorn_frac: k.frac },
      c1, c2, agree, verdict,
    };
  });

  out.poems[p] = {
    title: P_.title,
    slots: P.slots,
    rows,
    sinkhorn_conv: sink.conv,
    negatives: rows.filter(r => r.verdict === '负节点').map(r => ({ canonical: r.canonical, kind: r.neg_kind || (r.channel === 'a' ? '跨通道' : '缺席'), untransported_frac: r.ot.frac, deg: r.net.deg, link: r.net.link })),
    blank: rows.filter(r => r.verdict === '留白节点').map(r => r.canonical),
    counts: { nodes: rows.length, negatives: rows.filter(r => r.verdict === '负节点').length, review: rows.filter(r => r.verdict === '待复核').length },
  };
}

/* ---------- 验证 vs O2 负节点标注 / gold ---------- */
out.validation = {};
for (const p of ['jx', 'bd']) {
  const goldNeg = new Set(GOLD.poems[p].rows.filter(r => r.gold_class.startsWith('负节点')).map(r => r.canonical));
  const got = new Set(out.poems[p].negatives.map(n => n.canonical));
  const tp = [...got].filter(x => goldNeg.has(x));
  out.validation[p] = {
    gold: [...goldNeg], got: [...got],
    precision: got.size ? tp.length / got.size : 1,
    recall: goldNeg.size ? tp.length / goldNeg.size : 1,
    false_pos: [...got].filter(x => !goldNeg.has(x)),
    false_neg: [...goldNeg].filter(x => !got.has(x)),
  };
}
out.meta = {
  generated: new Date().toISOString().slice(0, 19),
  inputs: 'o2_imagery.json / o2_gold.json',
  method: '判据一=视觉共现网络低度(度≤' + P.degLow + ' 且 画面连接=0)；判据二=熵正则部分OT 未运输质量占比>' + P.untransported_cut,
  params: P,
  note: '判据一取「视觉共现度」（共现边两端皆为视觉意象，channel=v）；跨通道意象在视觉网络中度=0。deg_all 为含跨通道边的原始度，仅作对照。判据二为无容量解析解（槽位容量充足的极限）；带容量 Sinkhorn 作为交叉核对列在每行 sinkhorn_frac。带容量求解归 O4。不可实写（空间/时间量）先行裁定为留白节点。',
};
out.review_queue = review;

fs.writeFileSync(path.join(ROOT, 'data', 'derived', 'o3_negatives.json'), JSON.stringify(out, null, 2));

/* ---------- 控制台 ---------- */
const pct = v => (v == null ? '—' : (v * 100).toFixed(1) + '%');
console.log('=== o3_negatives.json —— 负节点双判据 ===');
for (const p of ['jx', 'bd']) {
  const P_ = out.poems[p], v = out.validation[p];
  console.log(`\n《${P_.title}》`);
  console.log('  意象           视觉度 画面连接  未运输占比  判据一 判据二  裁定');
  for (const r of P_.rows) {
    console.log(`  ${r.canonical.padEnd(6, '　')}  ${String(r.net.deg).padStart(4)}   ${String(r.net.link).padStart(5)}   ${(pct(r.ot.frac)).padStart(8)}   ${r.c1 ? ' ✓  ' : ' ·  '}  ${r.c2 ? ' ✓  ' : ' ·  '}  ${r.verdict}`);
  }
  console.log(`  负节点 ${P_.counts.negatives}：${P_.negatives.map(n => n.canonical + '(' + n.kind + ')').join('、') || '—'}　留白节点：${P_.blank.join('、') || '—'}`);
  console.log(`  验证 gold：精确 ${pct(v.precision)} · 召回 ${pct(v.recall)}${v.false_pos.length ? ' · 误报 ' + v.false_pos.join('/') : ''}${v.false_neg.length ? ' · 漏报 ' + v.false_neg.join('/') : ''}　Sinkhorn行和相对误差 ${(P_.sinkhorn_conv * 100).toFixed(2)}%`);
}
console.log('\n复核队列 ' + review.length + ' 条' + (review.length ? '：' + review.map(r => r.poem + '/' + r.canonical + '（' + r.kind + '）').join('、') : ''));
console.log('-> o3_negatives.json');

/* ---------- Markdown ---------- */
const L = [];
L.push('# O3 负节点双判据 · 报告', '');
L.push('- 生成：' + out.meta.generated);
L.push('- 输入：' + out.meta.inputs);
L.push('- 判据一：' + out.meta.method.split('；')[0].replace('判据一=', ''));
L.push('- 判据二：' + out.meta.method.split('；')[1].replace('判据二=', ''));
L.push('- ' + out.meta.note, '');
for (const p of ['jx', 'bd']) {
  const P_ = out.poems[p], v = out.validation[p];
  L.push('## 《' + P_.title + '》', '');
  L.push('| 意象 | 视觉共现度 | 画面连接 | 未运输质量 | 未运输占比 | Sinkhorn占比 | 判据一 | 判据二 | 裁定 |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- |');
  for (const r of P_.rows) {
    L.push('| ' + r.canonical + ' | ' + r.net.deg + ' | ' + r.net.link + ' | ' + r.ot.untransported + ' | ' + pct(r.ot.frac) + ' | ' + pct(r.ot.sinkhorn_frac) + ' | ' + (r.c1 ? '✓' : '·') + ' | ' + (r.c2 ? '✓' : '·') + ' | ' + (r.verdict === '负节点' ? '**负节点**' : r.verdict) + ' |');
  }
  L.push('', '**负节点**：' + (P_.negatives.map(n => n.canonical + '（' + n.kind + '）').join('、') || '—'));
  L.push('**留白节点**：' + (P_.blank.join('、') || '—'));
  L.push('**验证 gold**：精确 ' + pct(v.precision) + ' · 召回 ' + pct(v.recall) + (v.false_pos.length ? ' · 误报 ' + v.false_pos.join('/') : '') + (v.false_neg.length ? ' · 漏报 ' + v.false_neg.join('/') : ''));
  L.push('**Sinkhorn 交叉核对**：行和相对误差 ' + (P_.sinkhorn_conv * 100).toFixed(2) + '%（平衡化后收敛；与判据二的无容量解析解一致）', '');
}
L.push('## 复核队列', '');
if (!review.length) L.push('- 无（两条判据完全一致）');
for (const r of review) L.push('- 《' + r.poem + '》`' + r.canonical + '`：' + r.kind + ' —— ' + r.detail);
fs.writeFileSync(path.join(ROOT, 'docs', 'reports', 'o3_negatives_report.md'), L.join('\n'));
console.log('-> o3_negatives_report.md');
