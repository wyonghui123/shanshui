/* 外层回归：郭熙《画意》十七句 → O2 意象抽取 → 门控 → 与人工标注比对。
 *
 * 与内层回归（o2_imagery.mjs，jx/bd 两首自证用例）的分工：
 *   内层检验「代码是否还对」——用例与标注同源，改代码即改标注；
 *   外层检验「方法是否对」——标注独立于本项目，由北宋郭熙的诗画选编充当金标准，
 *   故此处的失败反映方法的系统性偏置，而非代码回归。
 *
 * 用法：node src/o2/o2_outer.mjs            # 跑回归并写出报告
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const rd = p => JSON.parse(readFileSync(join(ROOT, p), 'utf8'));
const has = p => existsSync(join(ROOT, p));

const LEX = rd('data/source/o2_lexicon.json');
const GATE = rd('data/source/o2_gate.json');
const CASES = rd('data/source/o2_poem_cases/guoxi_huayi_cases.json');
const W = LEX.words;

/* ---- 以下三个函数与 o2_imagery.mjs 逐字相同，改动须同步 ---- */
const caesurae = per => (per === 5 ? [2] : per === 7 ? [2, 4] : []);

function segment(line, form) {
  const n = line.length;
  const byFirst = {};
  for (const w of Object.keys(W)) { (byFirst[w[0]] ||= []).push(w); }
  for (const k of Object.keys(byFirst)) byFirst[k].sort((a, b) => b.length - a.length);
  const score = w => {
    const lex = !!W[w];
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
        if (caesurae(form.perLine).includes(j) && j < n) sc += 0.3;
        if (!best[j] || sc > best[j].s) best[j] = { s: sc, toks: [...best[i].toks, { w, i, len: w.length }] };
      }
    }
    const j = i + 1, sc = best[i].s + 0.4;
    if (!best[j] || sc > best[j].s) best[j] = { s: sc, toks: [...best[i].toks, { w: line[i], i, len: 1 }] };
  }
  const toks = best[n].toks.map(t => {
    const e = W[t.w] || null;
    return { w: t.w, pos: e ? e.pos : 'x', i: t.i, len: t.len, span: [t.i + 1, t.i + t.len], e };
  });
  return { toks, ok: toks.reduce((a, t) => a + t.len, 0) === n };
}

const isImagery = t => (t.pos === 'n' || t.pos === 'nq') && !(t.e && t.e.non_visual);
const isAction = t => t.pos === 'v' && t.e && t.e.action;
const canonOf = t => (t.e && t.e.canonical) || t.w;

function gate(node) {
  const e = node.e || {};
  if (node.neg_kind === '缺席') return { class: '不画（负节点）' };
  if (node.neg_kind === '跨通道') return { class: '视觉不画（听觉正）' };
  if (isAction(node)) return { class: '动作' };
  const c = e.conc == null ? 0.5 : e.conc;
  const T = GATE.thresholds;
  if (c >= T.real) return { class: '实写' };
  if (c >= T.blank) return { class: '虚写' };
  return { class: '不可实写' };
}
/* ---- 与主文件同步段结束 ---- */

const rows = [];
let nPass = 0;

for (const C of CASES.cases) {
  // 《画意》十七句为七言或五言联句，按「每句字数」定格律顿
  const text = C.text;
  const halves = text.split(/[，。]/).filter(Boolean);
  const form = { perLine: halves[0] ? halves[0].length : text.length };

  const got = [];
  let segOk = true;
  halves.forEach((line, li) => {
    const seg = segment(line, form);
    if (!seg.ok) segOk = false;
    for (const t of seg.toks) {
      if (!isImagery(t) && !isAction(t)) continue;
      const neg_kind = (t.e && t.e.audio) || t.e?.channel === 'a' ? '跨通道' : null;
      const node = {
        surface: t.w, canonical: canonOf(t), line: li + 1, span: t.span,
        conc: t.e ? (t.e.conc == null ? null : t.e.conc) : null,
        neg_kind, unknown: !t.e,
      };
      node.gate = gate({ ...node, e: t.e });
      got.push(node);
    }
  });

  const gotIcons = got.filter(n => !n.neg_kind).map(n => n.canonical);
  const want = C.expect_icons;
  const hit = want.filter(w => gotIcons.includes(w) || got.some(n => n.surface === w));
  const missed = want.filter(w => !(gotIcons.includes(w) || got.some(n => n.surface === w)));
  const unknown = got.filter(n => n.unknown).map(n => n.surface);

  // 判定：意象全中、无未登录词、且分词完整覆盖原句
  const ok = missed.length === 0 && unknown.length === 0 && segOk;
  if (ok) nPass++;

  rows.push({
    id: C.id, text, grade: C.grade,
    seg_ok: segOk,
    want, got: gotIcons, hit, missed,
    unknown,
    gates: got.map(n => ({ s: n.surface, c: n.conc, g: n.gate.class, k: n.neg_kind })),
    pass: ok,
    note: C.note,
  });
}

const n = rows.length;
const pct = x => (x * 100).toFixed(1) + '%';
const recall = rows.reduce((a, r) => a + r.hit.length, 0) / rows.reduce((a, r) => a + r.want.length, 0);
const precision = rows.reduce((a, r) => a + r.hit.length, 0) / Math.max(1, rows.reduce((a, r) => a + r.hit.length + r.missed.length, 0));

const report = {
  meta: {
    name: 'o2_outer_regression',
    generated: '2026-10-11',
    role: '郭熙《画意》十七句的外层回归。标注独立于本项目，充当金标准，'
      + '故失败反映方法的系统性偏置而非代码回归。与内层（jx/bd）的分工：内层检验代码正确性，外层检验方法有效性。',
    lexicon_version: LEX.meta.version + (LEX.meta.supplemented_at ? '（' + LEX.meta.supplemented_at + ' 补充）' : ''),
    gate_version: GATE.meta.version,
    thresholds: GATE.thresholds,
    source: CASES.meta.source,
  },
  summary: {
    cases: n, pass: nPass,
    pass_rate: pct(nPass / n),
    icon_recall: pct(recall),
    icon_precision: pct(precision),
    failures: rows.filter(r => !r.pass).map(r => r.id),
    unknown_tokens: [...new Set(rows.flatMap(r => r.unknown))],
  },
  rows,
};

writeFileSync(join(ROOT, 'data/runs/o2_outer_regression.json'), JSON.stringify(report, null, 2) + '\n');

console.log('\n=== 外层回归 · 郭熙《画意》十七句 ===');
console.log(`词典 ${report.meta.lexicon_version} · 门限 实写≥${GATE.thresholds.real} 虚写≥${GATE.thresholds.blank}`);
console.log(`用例 ${n} · 通过 ${nPass}（${pct(nPass / n)}） · 意象召回 ${pct(recall)} · 精确 ${pct(precision)}`);
console.log(`未登录词：${report.summary.unknown_tokens.length ? report.summary.unknown_tokens.join(' ') : '无'}`);
console.log('');
for (const r of rows) {
  console.log(`${r.pass ? '  ✓' : '  ✗'} ${r.id} ${r.text}`);
  console.log(`     期望 ${r.want.join('／')}`);
  console.log(`     实得 ${r.got.join('／') || '（无）'}${r.missed.length ? `　漏 ${r.missed.join('／')}` : ''}${r.unknown.length ? `　未登录 ${r.unknown.join('／')}` : ''}`);
  if (!r.pass) console.log(`     门控 ${r.gates.map(g => `${g.s}:${g.g}`).join(' ')}`);
}
console.log('\n-> data/runs/o2_outer_regression.json');