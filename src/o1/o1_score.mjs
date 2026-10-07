// o1_score.mjs —— 评分 / 汇总 / 回归比对（O1.2 收口）
// 把「逐题作答」的结果算成分数，并与 v1.2 基线逐题比对：
//   1) 评分：s = 1 若 effective.answer === expect，加权通过率 = Σ(w·s)/Σ(w)；
//   2) 汇总：按诗 / 按轴 / 按 basis 分列，并分列「自动层 / 目视层」的命中率；
//   3) 回归：逐题与 o1_baseline.json 比对 hit/miss，报出改进 / 回退 / 口径漂移；
//   4) 门槛：任何回退（基线命中 → 现在未中）即退出码非 0，可直接进 CI。
// 依赖：o1_qset.json / o1_judge_cards.json / o1_baseline.json（可选 o1_lint.json）
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

const QSET = rd('o1_qset.json');
const CARDS = rd('o1_judge_cards.json');
const BASE = has('o1_baseline.json') ? rd('o1_baseline.json') : null;
const LINT = has('o1_lint.json') ? rd('o1_lint.json') : null;
const lintErrors = LINT ? (LINT.findings || []).filter(f => f.sev === 'error') : [];
const lintWarns = LINT ? (LINT.findings || []).filter(f => f.sev === 'warn') : [];

const cards = CARDS.cards;
const norm = s => (s == null ? '' : String(s).trim());
const hit = c => norm(c.effective.answer) !== '' && norm(c.effective.answer) === norm(c.expect);

/* ---------- 1) 评分 ---------- */
const results = cards.map(c => ({
  id: c.id, poem: c.poem, axis: c.axis, basis: c.basis, w: c.w,
  type: c.type, expect: c.expect,
  answer: c.effective.answer, source: c.effective.source,
  s: hit(c) ? 1 : 0,
  auto_decidable: !!c.auto.decidable,
  auto_verdict: c.auto.decidable ? c.auto.verdict : null,
  vlm_answer: c.vlm ? c.vlm.answer : null,
  conflict: !!c.conflict,
}));

const sum = (arr, f) => arr.reduce((a, x) => a + f(x), 0);
function rollup(arr) {
  const w = sum(arr, x => x.w), hw = sum(arr, x => x.s * x.w);
  return { questions: arr.length, weight_sum: +w.toFixed(1), hit_weight: +hw.toFixed(1), rate: w ? +(hw / w).toFixed(4) : null, hit: arr.filter(x => x.s).length };
}
const group = (arr, key) => {
  const out = {};
  for (const k of [...new Set(arr.map(x => x[key]))]) out[k] = rollup(arr.filter(x => x[key] === k));
  return out;
};

const totals = { ...rollup(results), auto_covered: results.filter(r => r.auto_decidable).length, vlm_covered: results.filter(r => !r.auto_decidable && r.vlm_answer != null).length };
const by_poem = group(results, 'poem');
const by_axis = group(results, 'axis');
const by_basis = group(results, 'basis');
const by_source = { auto: rollup(results.filter(r => r.source === 'auto')), vlm: rollup(results.filter(r => r.source === 'vlm')) };

/* ---------- 2) 回归比对 ---------- */
let regressions = [], improvements = [], answer_diffs = [], stable_miss = [];
if (BASE) {
  const bById = {}; for (const r of BASE.results) bById[r.id] = r;
  for (const r of results) {
    const b = bById[r.id];
    if (!b) { regressions.push({ id: r.id, note: '基线无此题' }); continue; }
    const bHit = norm(b.answer) === norm(b.expect);
    const cHit = !!r.s;
    const ansChanged = norm(b.answer) !== norm(r.answer);
    if (bHit && !cHit) regressions.push({ id: r.id, expect: r.expect, baseline: b.answer, now: r.answer, source: r.source, why: '基线命中 → 现在未中' });
    else if (!bHit && cHit) improvements.push({ id: r.id, expect: r.expect, baseline: b.answer, now: r.answer, source: r.source });
    else if (!bHit && !cHit) stable_miss.push({ id: r.id, expect: r.expect, baseline: b.answer, now: r.answer });
    if (ansChanged) answer_diffs.push({ id: r.id, baseline: b.answer, now: r.answer, baseline_hit: bHit, now_hit: cHit });
  }
}

/* ---------- 3) 与基线的总量差 ---------- */
let totals_diff = null;
if (BASE) {
  const bt = BASE.meta.totals;
  totals_diff = {
    baseline: { questions: bt.questions, hit: bt.hit, miss: bt.miss, weight_sum: bt.weight_sum, hit_weight: bt.hit_weight, rate: bt.rate_excl_defect },
    now: { questions: totals.questions, hit: totals.hit, miss: totals.questions - totals.hit, weight_sum: totals.weight_sum, hit_weight: totals.hit_weight, rate: totals.rate },
    delta: { questions: totals.questions - bt.questions, hit: totals.hit - bt.hit, weight_sum: +(totals.weight_sum - bt.weight_sum).toFixed(1), rate: +(totals.rate - bt.rate_excl_defect).toFixed(4) },
  };
}

const gate = { pass: regressions.length === 0, regressions: regressions.length, improvements: improvements.length };

const out = {
  meta: {
    generated: new Date().toISOString().slice(0, 19),
    qset: 'o1_qset.json @ v' + QSET.meta.version,
    judge_cards: 'o1_judge_cards.json',
    baseline: BASE ? (BASE.meta.run_id || 'o1_baseline.json') : null,
    scoring: QSET.meta.scoring,
    note: '评分口径与问题集 meta.scoring 一致（逐题全等 + 加权通过率）。回归比对以基线 o1_baseline.json 的逐题 hit/miss 为参照；任何回退即 gate.pass=false。',
  },
  totals,
  by_poem, by_axis, by_basis, by_source,
  totals_diff,
  regression: { gate, regressions, improvements, stable_miss, answer_diffs },
  conflicts: CARDS.conflicts || [],
  lint: LINT ? { errors: lintErrors.length, warns: lintWarns.length, items: lintErrors } : null,
  results,
};
fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_score.json'), JSON.stringify(out, null, 2));

/* ---------- 控制台报告 ---------- */
const pct = v => (v == null ? '—' : (v * 100).toFixed(1) + '%');
console.log('=== o1_score.json —— 评分 / 汇总 / 回归 ===');
console.log('题数 ' + totals.questions + '　加权通过率 ' + pct(totals.rate) + '　（命中 ' + totals.hit + ' / 权重 ' + totals.hit_weight + ' / ' + totals.weight_sum + '）');
console.log('自动层覆盖 ' + totals.auto_covered + ' 题（' + pct(totals.auto_covered / totals.questions) + '）· 目视层 ' + totals.vlm_covered + ' 题');
console.log('  自动层命中率 ' + pct(by_source.auto.rate) + '　目视层命中率 ' + pct(by_source.vlm.rate));
console.log('\n按诗：' + Object.entries(by_poem).map(([k, v]) => k + ' ' + v.hit + '/' + v.questions + ' (' + pct(v.rate) + ')').join('　'));
console.log('按轴：' + Object.entries(by_axis).map(([k, v]) => k + ' ' + pct(v.rate)).join('　'));
console.log('按据：' + Object.entries(by_basis).map(([k, v]) => k + ' ' + pct(v.rate)).join('　'));

if (totals_diff) {
  const d = totals_diff.delta;
  console.log('\n与基线比对（' + out.meta.baseline + '）：');
  console.log('  基线 ' + totals_diff.baseline.hit + '/' + totals_diff.baseline.questions + ' (' + pct(totals_diff.baseline.rate) + ')'
    + ' → 现在 ' + totals_diff.now.hit + '/' + totals_diff.now.questions + ' (' + pct(totals_diff.now.rate) + ')'
    + '　Δ命中 ' + (d.hit >= 0 ? '+' : '') + d.hit + '　Δ题数 ' + (d.questions >= 0 ? '+' : '') + d.questions);
}
console.log('\n回归门槛：' + (gate.pass ? '✔ 通过（无回退）' : '✗ 未通过'));
if (regressions.length) { console.log('  回退 ' + regressions.length + '：'); for (const r of regressions) console.log('    ✗ ' + r.id + ' 期望「' + r.expect + '」基线「' + r.baseline + '」→ 现在「' + r.now + '」(' + r.source + ')'); }
if (improvements.length) { console.log('  改进 ' + improvements.length + '：'); for (const r of improvements) console.log('    ↑ ' + r.id + ' 基线「' + r.baseline + '」→ 现在「' + r.now + '」'); }
if (stable_miss.length) { console.log('  持续未中 ' + stable_miss.length + '：'); for (const r of stable_miss) console.log('    · ' + r.id + ' 期望「' + r.expect + '」答「' + r.now + '」'); }
if (answer_diffs.length) { console.log('\n作答文本差异 ' + answer_diffs.length + ' 处（口径漂移核对）：'); for (const d of answer_diffs) console.log('  ~ ' + d.id + '：基线「' + d.baseline + '」→ 现在「' + d.now + '」'); }
if (out.conflicts.length) { console.log('\n⚠ 自动层 / 目视层冲突 ' + out.conflicts.length + ' 处'); }
if (out.lint) { console.log('\n证据口径核对（o1_lint.json）：错误 ' + out.lint.errors + ' · 提示 ' + out.lint.warns); }

/* ---------- Markdown 报告 ---------- */
const L = [];
L.push('# O1 评估闭环 · 评分与回归报告', '');
L.push('- 生成时间：' + out.meta.generated);
L.push('- 问题集：' + out.meta.qset + '　判读卡：' + out.meta.judge_cards);
L.push('- 基线：' + (out.meta.baseline || '—'), '');
  const POS = QSET.meta.positioning;
  if (POS) {
    L.push('## 定位（勿误用）', '');
    L.push('- **' + POS.role + '**');
    L.push('- 量什么：' + POS.measures);
    L.push('- 不量什么：' + POS.not_measures);
    L.push('- 怎么用：' + POS.usage);
    L.push('- 相关：' + POS.related, '');
  }
  L.push('## 总览', '');
L.push('| 指标 | 值 |', '| --- | --- |');
L.push('| 题数 | ' + totals.questions + ' |');
L.push('| 加权通过率 | ' + pct(totals.rate) + ' |');
L.push('| 命中 / 权重 | ' + totals.hit + ' 题 / ' + totals.hit_weight + ' ÷ ' + totals.weight_sum + ' |');
L.push('| 自动层覆盖 | ' + totals.auto_covered + ' 题（' + pct(totals.auto_covered / totals.questions) + '），命中率 ' + pct(by_source.auto.rate) + ' |');
L.push('| 目视层 | ' + totals.vlm_covered + ' 题，命中率 ' + pct(by_source.vlm.rate) + ' |');
L.push('| 回归门槛 | ' + (gate.pass ? '通过（无回退）' : '未通过：回退 ' + regressions.length + ' 处') + ' |', '');
L.push('## 分轴', '', '| 轴 | 命中 / 题 | 通过率 |', '| --- | --- | --- |');
for (const [k, v] of Object.entries(by_axis)) L.push('| ' + k + ' | ' + v.hit + ' / ' + v.questions + ' | ' + pct(v.rate) + ' |');
L.push('', '## 分诗', '', '| 诗 | 命中 / 题 | 通过率 |', '| --- | --- | --- |');
for (const [k, v] of Object.entries(by_poem)) L.push('| ' + k + ' | ' + v.hit + ' / ' + v.questions + ' | ' + pct(v.rate) + ' |');
L.push('', '## 与基线比对（' + out.meta.baseline + '）', '');
if (totals_diff) L.push('- 基线 ' + totals_diff.baseline.hit + '/' + totals_diff.baseline.questions + '（' + pct(totals_diff.baseline.rate) + '）→ 现在 ' + totals_diff.now.hit + '/' + totals_diff.now.questions + '（' + pct(totals_diff.now.rate) + '）');
L.push('- 回退 ' + regressions.length + ' · 改进 ' + improvements.length + ' · 持续未中 ' + stable_miss.length, '');
if (regressions.length) { L.push('### 回退', ''); for (const r of regressions) L.push('- `' + r.id + '` 期望「' + r.expect + '」：基线「' + r.baseline + '」→ 现在「' + r.now + '」'); L.push(''); }
if (improvements.length) { L.push('### 改进', ''); for (const r of improvements) L.push('- `' + r.id + '`：基线「' + r.baseline + '」→ 现在「' + r.now + '」'); L.push(''); }
if (stable_miss.length) { L.push('### 持续未中', ''); for (const r of stable_miss) L.push('- `' + r.id + '` 期望「' + r.expect + '」，答「' + r.now + '」'); L.push(''); }
if (answer_diffs.length) { L.push('### 作答文本差异（口径漂移核对）', ''); for (const d of answer_diffs) L.push('- `' + d.id + '`：基线「' + d.baseline + '」→ 现在「' + d.now + '」'); L.push(''); }
L.push('## 待定资产口径（o1_lint.json）', '');
if (out.lint && out.lint.errors) for (const e of out.lint.items) L.push('- `' + e.id + '` [' + e.rule + '] ' + e.msg);
else L.push('- 无');
L.push('');
fs.writeFileSync(path.join(ROOT, 'docs', 'reports', 'o1_score_report.md'), L.join('\n'));
console.log('\n-> o1_score.json / o1_score_report.md');

process.exit(gate.pass ? 0 : 1);
