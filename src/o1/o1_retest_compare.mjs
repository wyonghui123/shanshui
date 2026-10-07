// o1_retest_compare.mjs —— O1.3-B 同源复判 · 一致性比对
// 输入：o1_retest.json（盲判）/ o1_baseline.json（v1.2 基线）/ o1_qset.json（权重与期望）
// 输出：o1_retest_compare.json + o1_retest_report.md
// 注意：本比对只度量「同一模型两次判读的一致性」，不构成独立验证。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));

const R = rd('o1_retest.json');
const BASE = rd('o1_baseline.json');
const QSET = rd('o1_qset.json');

const norm = s => (s == null ? '' : String(s).trim());

const qById = {};
for (const p of QSET.poems) for (const q of p.questions) qById[q.id] = q;
const bById = {};
for (const r of BASE.results) bById[r.id] = r;

const rows = R.answers.map(a => {
  const b = bById[a.id] || {};
  const q = qById[a.id] || {};
  const bAns = norm(b.answer), rAns = norm(a.answer), exp = norm(b.expect || q.expect);
  return {
    id: a.id,
    poem: q.poem || b.poem,
    axis: q.axis,
    w: q.w ?? 1,
    q: q.q,
    expect: exp,
    baseline: bAns,
    retest: rAns,
    agree: bAns === rAns,
    baseline_hit: bAns !== '' && bAns === exp,
    retest_hit: rAns !== '' && rAns === exp,
    retest_conf: a.conf,
    judge: a.judge,
    retest_evidence: a.evidence,
    baseline_evidence: b.evidence,
  };
});

const n = rows.length;
const sum = (arr, f) => arr.reduce((a, x) => a + f(x), 0);
const wSum = sum(rows, r => r.w);
const agree = rows.filter(r => r.agree);
const disagree = rows.filter(r => !r.agree);
const wAgree = sum(rows, r => (r.agree ? r.w : 0));

const metrics = {
  n,
  agree: agree.length,
  disagree: disagree.length,
  agreement_rate: +(agree.length / n).toFixed(4),
  weight_sum: +wSum.toFixed(1),
  agree_weight: +wAgree.toFixed(1),
  agreement_rate_weighted: +(wAgree / wSum).toFixed(4),
  baseline_hit: rows.filter(r => r.baseline_hit).length,
  retest_hit: rows.filter(r => r.retest_hit).length,
  // 基线命中但复判未中 = 潜在不稳（若用复判覆盖，会造成回退）
  baseline_hit_retest_miss: rows.filter(r => r.baseline_hit && !r.retest_hit).map(r => r.id),
  // 基线未中但复判命中 = 潜在改进
  baseline_miss_retest_hit: rows.filter(r => !r.baseline_hit && r.retest_hit).map(r => r.id),
  conf_dist: ['high', 'mid', 'low'].reduce((a, c) => (a[c] = rows.filter(r => r.retest_conf === c).length, a), {}),
  low_conf_ids: rows.filter(r => r.retest_conf === 'low').map(r => r.id),
};

const out = {
  meta: {
    generated: new Date().toISOString().slice(0, 19),
    purpose: 'O1.3-B 同源复判 · 一致性比对',
    retest: 'o1_retest.json（3 个全新上下文判读者，同一底层模型）',
    baseline: BASE.meta.run_id || 'o1_baseline.json',
    caveat: R.meta.caveat,
    definition: {
      agreement: 'norm(基线作答) === norm(复判作答)',
      hit: 'norm(作答) === norm(expect)',
      not_independent: '同源复判，非独立验证；一致率高只说明该模型判读稳定，不代表判读正确。',
    },
  },
  metrics,
  rows,
};

fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_retest_compare.json'), JSON.stringify(out, null, 2));

/* ---------- 控制台 ---------- */
const pct = v => (v * 100).toFixed(1) + '%';
console.log('=== O1.3-B 同源复判 · 一致性 ===');
console.log('判读题数 ' + n + '（目视层）');
console.log('两次判读一致 ' + metrics.agree + '/' + n + '　一致率 ' + pct(metrics.agreement_rate) + '（加权 ' + pct(metrics.agreement_rate_weighted) + '）');
console.log('基线命中 ' + metrics.baseline_hit + '　复判命中 ' + metrics.retest_hit);
console.log('复判置信度：high ' + metrics.conf_dist.high + '　mid ' + metrics.conf_dist.mid + '　low ' + metrics.conf_dist.low);
if (disagree.length) {
  console.log('\n不一致 ' + disagree.length + ' 题：');
  for (const r of disagree) console.log('  ~ ' + r.id + ' [' + r.axis + '] 期望「' + r.expect + '」\n      基线「' + r.baseline + '」(' + (r.baseline_hit ? '命中' : '未中') + ') → 复判「' + r.retest + '」(' + (r.retest_hit ? '命中' : '未中') + '，conf=' + r.retest_conf + ')\n      复判依据：' + r.retest_evidence);
} else {
  console.log('\n无分歧：12 题两次判读完全一致。');
}
if (metrics.baseline_hit_retest_miss.length) console.log('\n⚠ 基线命中 → 复判未中（潜在不稳）：' + metrics.baseline_hit_retest_miss.join(', '));
if (metrics.baseline_miss_retest_hit.length) console.log('↑ 基线未中 → 复判命中（潜在改进）：' + metrics.baseline_miss_retest_hit.join(', '));
if (metrics.low_conf_ids.length) console.log('低置信题：' + metrics.low_conf_ids.join(', '));

/* ---------- Markdown 报告 ---------- */
const L = [];
L.push('# O1.3-B · 同源复判报告（判读稳定性检验）', '');
L.push('> **结论定性**：本次为**同源复判**——判读者与 v1.2 基线是**同一个模型**（dcwcoding）。');
L.push('> 它只回答「同一模型两次判读是否稳定」，**不构成独立第二意见，不能用来证明判读正确**。', '');
L.push('- 生成时间：' + out.meta.generated);
L.push('- 复判来源：' + out.meta.retest);
L.push('- 比对基线：' + out.meta.baseline);
L.push('- 盲判条件：3 个全新上下文的判读者，仅凭帧缩略图作答；未读取任何项目 JSON，未见期望答案与基线作答。', '');
L.push('## 总览', '', '| 指标 | 值 |', '| --- | --- |');
L.push('| 判读题数（目视层） | ' + n + ' |');
L.push('| 两次判读一致 | ' + metrics.agree + ' / ' + n + ' |');
L.push('| **一致率** | **' + pct(metrics.agreement_rate) + '**（加权 ' + pct(metrics.agreement_rate_weighted) + '） |');
L.push('| 基线命中 | ' + metrics.baseline_hit + ' / ' + n + ' |');
L.push('| 复判命中 | ' + metrics.retest_hit + ' / ' + n + ' |');
L.push('| 复判置信度分布 | high ' + metrics.conf_dist.high + ' · mid ' + metrics.conf_dist.mid + ' · low ' + metrics.conf_dist.low + ' |', '');
L.push('## 逐题对照', '', '| 题号 | 轴 | 期望 | 基线 | 复判 | 一致 | 复判置信 |', '| --- | --- | --- | --- | --- | --- | --- |');
for (const r of rows) L.push('| `' + r.id + '` | ' + r.axis + ' | ' + r.expect + ' | ' + r.baseline + ' | ' + r.retest + ' | ' + (r.agree ? '✔' : '✘') + ' | ' + r.retest_conf + ' |');
L.push('');
if (disagree.length) {
  L.push('## 分歧明细', '');
  for (const r of disagree) {
    L.push('### `' + r.id + '`　期望「' + r.expect + '」');
    L.push('- 基线作答：**' + r.baseline + '**（' + (r.baseline_hit ? '命中' : '未中') + '）');
    L.push('- 复判作答：**' + r.retest + '**（' + (r.retest_hit ? '命中' : '未中') + '，conf=' + r.retest_conf + '）');
    L.push('- 基线依据：' + (r.baseline_evidence || '—'));
    L.push('- 复判依据：' + r.retest_evidence);
    L.push('');
  }
} else {
  L.push('## 分歧明细', '', '无——12 题两次判读完全一致。', '');
}
if (metrics.baseline_hit_retest_miss.length || metrics.baseline_miss_retest_hit.length || metrics.low_conf_ids.length) {
  L.push('## 风险与待办', '');
  if (metrics.baseline_hit_retest_miss.length) L.push('- **潜在不稳**（基线命中、复判未中）：`' + metrics.baseline_hit_retest_miss.join('`, `') + '` —— 若用复判覆盖 VLM 层，会触发 o1_score 回退门槛，主链路将中止。');
  if (metrics.baseline_miss_retest_hit.length) L.push('- 潜在改进（基线未中、复判命中）：`' + metrics.baseline_miss_retest_hit.join('`, `') + '`');
  if (metrics.low_conf_ids.length) L.push('- 低置信题（conf=low）：`' + metrics.low_conf_ids.join('`, `') + '` —— 判读者自认不确定，是最需要外部裁定的题。');
  L.push('');
}
L.push('## 如何解读一致率', '');
L.push('- **一致率高 ≠ 判读正确**：同一模型有系统性偏好，两次都可能同样偏。');
L.push('- **一致率低 ≠ 画面有问题**：可能只是该题本身超出静态帧可判范围（如「雪是否持续飘落」需看运动而非两帧）。');
L.push('- 一致率真正的作用：**筛出「同一模型都不稳定」的题**，这些题才需要人工裁定或改判据。', '');
L.push('## 下一步', '');
L.push('1. 对上表中分歧/低置信的题做人工裁定，写进 `o1_qset.json` 的 expect 或改判据；');
L.push('2. 若某题属于「静态帧无法判」的类型，应在题面标注并改用 probe/media 判据，而非依赖目视；');
L.push('3. 若要真正的独立验证，必须换一个**不同厂商/不同模型**的多模态端点重跑本流程。', '');

fs.writeFileSync(path.join(ROOT, 'docs', 'reports', 'o1_retest_report.md'), L.join('\n'));
console.log('\n-> o1_retest_compare.json / o1_retest_report.md');
