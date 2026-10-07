// o1_retest_pack.mjs —— 同源复判 · 盲判任务包导出（O1.3-B）
// 目的：把 12 道「目视层」题抽出来，剥掉一切答案线索，交给全新上下文的判读者。
// 剥掉：expect（期望答案）、measured（题内实测值）、基线答案、基线 evidence。
// 保留：题干、选项、判读帧名 + 帧时刻、media、probe_assisted。
// 用法：node src/o1/o1_retest_pack.mjs  →  o1_retest_pack.json
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));

const QSET = rd('o1_qset.json');
const CARDS = rd('o1_judge_cards.json');

const THUMB_DIR = path.join(ROOT, 'dist', 'figures', 'thumbs');
const thumbOf = name => {
  const p = path.join(THUMB_DIR, name + '.jpg');
  return fs.existsSync(p) ? path.relative(ROOT, p).replace(/\\/g, '/') : null;
};

/* 判读帧名 → 该帧的时刻（用于告诉判读者「哪一帧是起点、哪一帧是终点」） */
const frameTime = {};
for (const poem of QSET.poems) for (const f of poem.frames) frameTime[poem.id + '/' + f.name] = f.t;

const cards = CARDS.cards.filter(c => !c.auto.decidable);
const missing = [];

const items = cards.map(c => {
  const frames = c.frame.split('+').map(s => s.trim()).filter(Boolean);
  const images = frames.map(n => ({ frame: n, t: frameTime[c.poem + '/' + n] ?? null, file: thumbOf(n) }));
  for (const im of images) if (!im.file) missing.push(c.id + ' → ' + im.frame);

  return {
    id: c.id,
    poem: c.poem,
    axis: c.axis,
    basis: c.basis,
    type: c.type,
    media: c.media || 'single',
    probe_assisted: !!c.probe_assisted,
    q: c.q,
    options: c.options,
    images,
    answer_schema: { answer: '必须与 options 中某一项完全一致', conf: 'high|mid|low', evidence: '判读依据（看图所得，勿引用源码参数）' },
  };
});

const out = {
  meta: {
    generated: new Date().toISOString().slice(0, 19),
    purpose: '同源复判 · 盲判任务包（O1.3-B）',
    source_qset: 'o1_qset.json @ v' + QSET.meta.version,
    n: items.length,
    stripped: ['expect', 'measured', 'baseline.answer', 'baseline.evidence'],
    note: '本包不含任何期望答案与基线作答。判读者须仅依据 images 所列帧图作答，不得读取项目内其他 JSON。',
  },
  items,
};

fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_retest_pack.json'), JSON.stringify(out, null, 2));

console.log('=== o1_retest_pack.json ===');
console.log('盲判题数 ' + items.length + '（自动层不可判者）');
console.log('按轴：' + Object.entries(items.reduce((a, x) => (a[x.axis] = (a[x.axis] || 0) + 1, a), {})).map(([k, v]) => k + ' ' + v).join('　'));
console.log('按诗：' + Object.entries(items.reduce((a, x) => (a[x.poem] = (a[x.poem] || 0) + 1, a), {})).map(([k, v]) => k + ' ' + v).join('　'));
console.log('');
for (const it of items) {
  const ims = it.images.map(i => i.frame + '@' + (i.t == null ? '?' : i.t + 's')).join(' + ');
  console.log('  ' + it.id.padEnd(8) + it.axis.padEnd(9) + it.media.padEnd(7) + ims.padEnd(28) + '「' + it.q.slice(0, 30) + '」');
}
if (missing.length) {
  console.log('\n⚠ 缺图 ' + missing.length + ' 处：' + missing.join('；'));
  process.exit(1);
}
console.log('\n所有判读帧缩略图齐备。');
