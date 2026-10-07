// o1_lint.mjs —— 用源码事实反查问题集/基线的「证据栏」（O1.2）
// 问题集里的 why 与基线里的 evidence 是散文，最容易出现「滤镜挂错」「道数写错」
// 「本该缺席的组被当成存在」这类口径错误 —— 判读没错，但依据写错了，
// 会被后续版本继承。本脚本把可核对的部分机器化：
//   R1 滤镜归属：why 里「#元素 … 某滤镜」的搭配必须与源码使用方一致
//   R2 水纹道数：why 里的「N 道」必须等于源码 ROWS 在该诗下的道数
//   R3 存在性口径：why 里「无/没有 #X」必须与源码存在性一致
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const QSET = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'source', 'o1_qset.json'), 'utf8'));
const F = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'derived', 'o1_source_facts.json'), 'utf8'));
const BASE = fs.existsSync(path.join(ROOT, 'data', 'source', 'o1_baseline.json'))
  ? JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'source', 'o1_baseline.json'), 'utf8')) : null;

const findings = [];
const add = (sev, rule, id, msg, extra) => findings.push({ sev, rule, id, msg, ...(extra || {}) });

const FILTER_IDS = new Set(Object.keys(F.filters));
const WATCHED = new Set([].concat(...Object.values(F.presence).map(o => Object.keys(o))));

/* 某滤镜的全部使用方（组自身 + 子笔触）；排除 *-cam 这类整场景容器，去重 */
const usersOf = f => [...new Set((F.filterUsage[f] || []).map(u => u.el))].filter(e => !/-cam$/.test(e));

const EL_RE = /#((?:jx|bd)-[a-z][a-z-]*)/g;

/* ---------- R1 滤镜归属 ---------- */
function r1(text, id, field) {
  for (const m of text.matchAll(EL_RE)) {
    const el = m[1];
    if (!F.elements[el]) continue;
    const win = text.slice(m.index, m.index + 64);
    for (const fm of win.matchAll(/\b((?:jx|bd)[A-Z][A-Za-z]*)\b/g)) {
      const fid = fm[1];
      if (!FILTER_IDS.has(fid)) continue;         // bdCliffL 之类是渐变，不是滤镜
      const users = usersOf(fid);
      if (!users.length) { add('error', 'R1', id, `${field}：提到滤镜 ${fid}，但源码中无人使用`, { el, fid }); continue; }
      if (!users.includes(el)) {
        add('error', 'R1', id,
          `${field}：把 ${fid} 挂在 #${el} 上，但源码里 ${fid} 的使用方是 ${users.join(' / ')}（#${el} 自身用 ${F.elements[el].filter || '无滤镜'}）`,
          { el, fid, actualUsers: users, declared: F.elements[el].filter });
      }
    }
  }
}

/* ---------- R2 水纹道数 ---------- */
function r2(text, id, poem, field) {
  const cm = /(\d+)\s*道/.exec(text);
  if (!cm) return;
  if (!/水纹|水波|ROWS|道数/.test(text)) return;
  const claimed = parseInt(cm[1], 10);
  const actual = F.waterRows.perPoem[poem];
  if (claimed !== actual) {
    add('error', 'R2', id, `${field}：水纹道数写「${claimed} 道」，源码实测 ${poem} = ${actual} 道`, { claimed, actual });
  }
}

/* ---------- R3 存在性口径 ---------- */
function r3(text, id, field) {
  for (const m of text.matchAll(EL_RE)) {
    const el = m[1];
    if (!WATCHED.has(el)) continue;
    const present = F.presence[el.split('-')[0]][el].present;
    /* 只看「同一分句」内的否定/存在，避免「A 无、#B 有」这类跨句误伤 */
    const tail = text.slice(Math.max(0, m.index - 16), m.index).split(/[，,；;。、\n]/).pop();
    const head = text.slice(m.index, m.index + 20).split(/[，,；;。、\n]/)[0];
    if (/无|没有|不存在|未出现/.test(tail) && present) {
      add('error', 'R3', id, `${field}：称「无 #${el}」，但源码中存在该元素`, { el });
    }
    if (/存在|出现|画出|挂了|已画/.test(head) && !present) {
      add('error', 'R3', id, `${field}：称 #${el} 存在，但源码中缺席`, { el });
    }
  }
}

for (const poem of QSET.poems) {
  for (const q of poem.questions) {
    const why = q.why || '';
    r1(why, q.id, 'why');
    r2(why, q.id, poem.id, 'why');
    r3(why, q.id, 'why');
    const b = BASE && BASE.results.find(r => r.id === q.id);
    if (b && b.evidence) {
      r1(b.evidence, q.id, 'baseline.evidence');
      r2(b.evidence, q.id, poem.id, 'baseline.evidence');
      r3(b.evidence, q.id, 'baseline.evidence');
    }
  }
}

const out = {
  meta: {
    generated: new Date().toISOString().slice(0, 19),
    qset: 'o1_qset.json @ v' + QSET.meta.version,
    facts: F.meta.source,
    note: '只核对「可静态核对」的证据栏：滤镜归属 / 水纹道数 / 元素存在性。墨色亮度、位置等由 src/o1/o1_judge.mjs 的自动层计算。',
  },
  counts: {
    error: findings.filter(f => f.sev === 'error').length,
    warn: findings.filter(f => f.sev === 'warn').length,
  },
  findings,
};
fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_lint.json'), JSON.stringify(out, null, 2));

console.log('=== o1_lint.json —— 证据栏口径核对 ===');
console.log('错误 ' + out.counts.error + ' · 提示 ' + out.counts.warn);
for (const f of findings) console.log('  ' + (f.sev === 'error' ? '✗' : '·') + ' [' + f.rule + '] ' + f.id + ' —— ' + f.msg);
if (!findings.length) console.log('  证据栏与源码事实一致');
