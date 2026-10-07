// o1_validate.mjs —— 问题集结构校验器（v1.2 新增，对应缺陷 D1/D2/D3/D6/D7）
// 把「靠人工自觉」的判读规则变成机器可执行的断言；退出码非 0 即表示问题集不可用于基线。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const QSET = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'source', 'o1_qset.json'), 'utf8'));

const errors = [];
const warns = [];
const err = (code, msg) => errors.push({ code, msg });
const warn = (code, msg) => warns.push({ code, msg });

const AXES = ['EXIST', 'ATTR', 'SPATIAL', 'TEMPORAL', 'NEGATIVE'];
const MEDIA = ['single', 'pair', 'video', 'probe'];
const YESNO = ['是', '否'];

/* 从「中部偏上（0.40–0.50H）」这类选项文本里解析数值区间，支持 – - ~ 三种连接符 */
function parseBands(text){
  const out = [];
  const re = /(\d+(?:\.\d+)?)\s*[–\-~]\s*(\d+(?:\.\d+)?)/g;
  let m;
  while ((m = re.exec(text)) !== null) out.push([parseFloat(m[1]), parseFloat(m[2])]);
  return out;
}

const seenIds = new Set();
let qTotal = 0, wTotal = 0;

for (const poem of QSET.poems) {
  const frameNames = new Set(poem.frames.map(f => f.name));
  for (const q of poem.questions) {
    qTotal++;
    const at = `${poem.id}/${q.id}`;
    wTotal += (q.w || 0);

    /* D2 —— 每题必须绑定判读帧 */
    if (!q.frame || typeof q.frame !== 'string') {
      err('E_FRAME_MISSING', `${at} 缺 frame 字段（D2：不绑帧的构图题在镜头推近前后会有两个答案）`);
    } else {
      const used = q.frame.split('+').map(s => s.trim()).filter(Boolean);
      for (const f of used) {
        if (!frameNames.has(f)) err('E_FRAME_UNKNOWN', `${at} 引用了不存在的帧「${f}」`);
      }
    }

    /* 唯一 ID */
    if (seenIds.has(q.id)) err('E_DUP_ID', `${at} 题号重复`);
    seenIds.add(q.id);

    /* 轴合法 */
    if (!AXES.includes(q.axis)) err('E_AXIS', `${at} 非法 axis「${q.axis}」`);

    /* 权重 */
    if (!(q.w > 0)) err('E_WEIGHT', `${at} 权重必须 > 0`);

    /* 作答类型 */
    if (q.type === 'choice') {
      if (!Array.isArray(q.options) || q.options.length < 2) {
        err('E_OPTIONS', `${at} choice 题须有 ≥2 个 options`);
      } else if (!q.options.includes(q.expect)) {
        err('E_EXPECT', `${at} expect「${q.expect}」不在 options 内`);
      }
    } else if (q.type === 'yes_no') {
      if (!YESNO.includes(q.expect)) err('E_EXPECT', `${at} yes_no 题 expect 必须是「是」或「否」`);
      if (q.options) warn('W_OPTIONS', `${at} yes_no 题不应带 options`);
    } else {
      err('E_TYPE', `${at} 未知 type「${q.type}」`);
    }

    /* D7 —— 时序题必须成对帧、视频或客观探针 */
    if (q.axis === 'TEMPORAL' && !['pair', 'video', 'probe'].includes(q.media)) {
      err('E_TEMPORAL_MEDIA', `${at} 时序题 media 必须为 pair / video / probe（D7：单帧判不了过程）`);
    }

    /* media 与 frame 的一致性 */
    if (!MEDIA.includes(q.media)) {
      err('E_MEDIA', `${at} media 必须 ∈ {single,pair,video}`);
    } else if (q.media === 'single' && q.frame && q.frame.includes('+')) {
      err('E_MEDIA_FRAME', `${at} media=single 但 frame 用了「+」连接多帧`);
    } else if (q.media === 'pair' && q.frame && !q.frame.includes('+')) {
      err('E_MEDIA_FRAME', `${at} media=pair 但 frame 只给了一帧`);
    }

    /* D3 —— 负节点题一律绑去诗帧 */
    if (q.axis === 'NEGATIVE' && q.frame) {
      for (const f of q.frame.split('+').map(s => s.trim())) {
        if (!/nopoem/.test(f)) {
          err('E_NEG_NOPOEM', `${at} 负节点题绑了非去诗帧「${f}」（D3：题诗文字里的意象词会造成假阳性）`);
        }
      }
    }

    /* D1 —— 有实测值的题，选项档位必须覆盖实测值 */
    if (q.measured && typeof q.measured.value === 'number') {
      const bands = parseBands(q.expect || '');
      if (!bands.length) {
        warn('W_MEASURED_NOBAND', `${at} 带 measured 但 expect 选项未写出数值区间，无法机器核对覆盖`);
      } else if (!bands.some(([a, b]) => q.measured.value >= a && q.measured.value <= b)) {
        err('E_OPTION_GAP', `${at} 实测 ${q.measured.value}${q.measured.unit || ''} 不落在 expect 档位 ${JSON.stringify(bands)} 内（D1：选项有空档）`);
      }
    }

    /* D6 —— 极淡元素题必须挂判读协议 */
    if (q.probe_assisted && !QSET.meta.protocol.reading_protocol) {
      err('E_PROBE_PROTOCOL', `${at} probe_assisted=true 但 meta.protocol.reading_protocol 缺失（D6）`);
    }
  }
}

/* 全局：模板必备块 */
for (const key of ['axes', 'basis', 'scoring', 'generation_rules', 'protocol', 'rho_definitions', 'media_types']) {
  if (!QSET.meta[key]) err('E_META', `meta.${key} 缺失`);
}

/* 基线交叉核对（若存在 o1_baseline.json）—— 防「问题集改了、基线没重跑」的静默漂移 */
const basePath = path.join(ROOT, 'data', 'source', 'o1_baseline.json');
if (fs.existsSync(basePath)) {
  const BASE = JSON.parse(fs.readFileSync(basePath, 'utf8'));
  const qById = {};
  for (const p of QSET.poems) for (const q of p.questions) qById[q.id] = q;
  const rById = {};
  for (const r of BASE.results) rById[r.id] = r;

  for (const id of Object.keys(qById)) {
    const r = rById[id];
    if (!r) { err('E_BASE_MISSING', id + ' 在问题集中但基线无作答'); continue; }
    const q = qById[id];
    if (r.frame !== q.frame) err('E_BASE_FRAME', id + ' 基线判读帧「' + r.frame + '」≠ 问题集「' + q.frame + '」（基线需重跑）');
    if (r.media !== q.media) err('E_BASE_MEDIA', id + ' 基线 media「' + r.media + '」≠ 问题集「' + q.media + '」');
    if (Math.abs((r.w || 0) - (q.w || 0)) > 1e-9) err('E_BASE_W', id + ' 基线权重 ' + r.w + ' ≠ 问题集 ' + q.w);
  }
  for (const id of Object.keys(rById)) if (!qById[id]) err('E_BASE_EXTRA', id + ' 在基线中但问题集无此题');

  const bt = BASE.meta.totals;
  if (bt.questions !== qTotal) err('E_BASE_TOTAL', '基线题数 ' + bt.questions + ' ≠ 问题集 ' + qTotal);
  if (Math.abs(bt.weight_sum - wTotal) > 1e-9) err('E_BASE_TOTAL', '基线权重和 ' + bt.weight_sum + ' ≠ 问题集 ' + wTotal.toFixed(1));
  if (BASE.meta.qset && !BASE.meta.qset.includes('v' + QSET.meta.version)) {
    err('E_BASE_VERSION', '基线标称问题集「' + BASE.meta.qset + '」与当前 v' + QSET.meta.version + ' 不符');
  }
  console.log('基线交叉核对：' + BASE.results.length + ' 条作答 ↔ 问题集 ' + qTotal + ' 题');
}

const byAxis = {};
for (const p of QSET.poems) for (const q of p.questions) byAxis[q.axis] = (byAxis[q.axis] || 0) + 1;

console.log('=== o1_qset.json @ v' + QSET.meta.version + ' 校验 ===');
console.log('题数 ' + qTotal + '　权重和 ' + wTotal.toFixed(1));
console.log('按轴 ' + JSON.stringify(byAxis));
console.log('按诗 ' + QSET.poems.map(p => p.id + '=' + p.questions.length).join(' '));
console.log('');
if (errors.length) {
  console.log('错误 ' + errors.length + '：');
  for (const e of errors) console.log('  ✗ [' + e.code + '] ' + e.msg);
} else {
  console.log('错误 0 —— 结构断言全部通过');
}
if (warns.length) {
  console.log('提示 ' + warns.length + '：');
  for (const w of warns) console.log('  · [' + w.code + '] ' + w.msg);
}
process.exit(errors.length ? 1 : 0);
