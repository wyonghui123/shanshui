// o1_source_facts.mjs —— 从 ink_animations.html 抽取结构化事实（O1.2）
// 目的：把「哪条笔触挂了哪个滤镜」「有没有水纹组」这类判据从散文证据变成可核对的机器事实。
// 只做静态抽取（标签属性 / 滤镜定义 / 渐变定义 / 水纹行表），不启动浏览器。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const SRC = path.join(ROOT, 'dist', 'animation', 'ink_animations.html');
const html = fs.readFileSync(SRC, 'utf8');

const attrsOf = tag => {
  const o = {};
  const re = /([\w:-]+)\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = re.exec(tag)) !== null) o[m[1]] = m[2];
  return o;
};

/* 几何属性白名单：只取数值型坐标，供「渲染层几何」逐值比对。
   刻意不收 path 的 d —— 那是整串路径，收进来会让事实文件体积翻倍；
   需要比 path 时按字符串单独比。 */
const GEO_ATTRS = ['cx', 'cy', 'rx', 'ry', 'r', 'x', 'y', 'width', 'height', 'x1', 'y1', 'x2', 'y2'];
const geomOf = a => {
  const g = {};
  for (const k of GEO_ATTRS) if (a[k] != null) g[k] = parseFloat(a[k]);
  return g;
};

/* ---- 1. 带 id 的元素 ---- */
const elements = {};
const elRe = /<(g|path|rect|ellipse|circle|line|polygon|polyline|text|clipPath)\b([^>]*\bid="([^"]+)"[^>]*)>/g;
let m;
while ((m = elRe.exec(html)) !== null) {
  const tag = m[1], raw = m[2], id = m[3];
  const a = attrsOf(raw);
  const f = /url\(#([^)]+)\)/.exec(a.filter || '');
  elements[id] = {
    tag,
    filter: f ? f[1] : null,
    opacity: a.opacity != null ? parseFloat(a.opacity) : null,
    strokeWidth: a['stroke-width'] != null ? parseFloat(a['stroke-width']) : null,
    classes: a.class || null,
    fill: a.fill || null,
    stroke: a.stroke || null,
    geom: geomOf(a),
  };
}

/* ---- 1b. 绘制基元（path/rect/ellipse/…）与「哪个组挂了哪个滤镜」的完整归属 ----
   只看组自身的 filter 属性会漏掉「组无滤镜、子笔触各挂滤镜」的情况（如 #bd-trail 的
   两条拖痕各自挂 bdDry），也会误判「组挂 A、子笔触是渐变填充」的山壁主体。 */
const PRIM = /<(path|rect|ellipse|circle|line|polygon|polyline)\b([^>]*?)\/?>/g;
const prims = [];
while ((m = PRIM.exec(html)) !== null) {
  const a = attrsOf(m[2]);
  prims.push({
    tag: m[1], idx: m.index,
    fill: a.fill || null, stroke: a.stroke || null,
    opacity: a.opacity != null ? parseFloat(a.opacity) : null,
    filter: (/url\(#([^)]+)\)/.exec(a.filter || '') || [])[1] || null,
    geom: geomOf(a),
  });
}

/* 用嵌套计数求 <g id="X"> … </g> 的跨度 */
function spanOf(id) {
  const esc = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const om = new RegExp('<g\\b[^>]*\\bid="' + esc + '"').exec(html);
  if (!om) return null;
  const re = /<g\b|<\/g>/g;
  re.lastIndex = om.index;
  let depth = 0, mm;
  while ((mm = re.exec(html)) !== null) {
    if (mm[0] === '</g>') { depth--; if (depth === 0) return { start: om.index, end: mm.index }; }
    else depth++;
  }
  return { start: om.index, end: html.length };
}

/* ---- 2. 滤镜定义 ---- */
const filters = {};
const fRe = /<filter\b([^>]*)>([\s\S]*?)<\/filter>/g;
while ((m = fRe.exec(html)) !== null) {
  const id = attrsOf(m[1]).id;
  const inner = m[2];
  const blur = [...inner.matchAll(/<feGaussianBlur[^>]*stdDeviation="([^"]+)"/g)].map(x => parseFloat(x[1]));
  const disp = [...inner.matchAll(/<feDisplacementMap[^>]*scale="([^"]+)"/g)].map(x => parseFloat(x[1]));
  const turb = [...inner.matchAll(/<feTurbulence[^>]*baseFrequency="([^"]+)"[^>]*numOctaves="([^"]+)"/g)]
    .map(x => ({ baseFrequency: parseFloat(x[1]), numOctaves: parseInt(x[2], 10) }));
  const comp = /<feComposite/.test(inner);
  filters[id] = {
    gaussianBlur: blur,
    displacementScale: disp,
    turbulence: turb,
    feComposite: comp,
    /* 判据分类：有模糊 → 湿笔晕染；只有位移 → 干笔毛边；有 feComposite → 飞白 */
    kind: blur.length ? 'wet' : (comp ? 'feibai' : (disp.length ? 'dry' : 'plain')),
  };
}

/* ---- 3. 渐变定义 ---- */
const gradients = {};
const gRe = /<(linearGradient|radialGradient)\b([^>]*)>([\s\S]*?)<\/\1>/g;
while ((m = gRe.exec(html)) !== null) {
  const id = attrsOf(m[2]).id;
  const stops = [...m[3].matchAll(/<stop[^>]*offset="([^"]+)"[^>]*stop-color="([^"]+)"[^>]*stop-opacity="([^"]+)"/g)]
    .map(x => ({ offset: x[1], color: x[2], opacity: parseFloat(x[3]) }));
  gradients[id] = stops;
}

/* ---- 4. 水纹行表（ROWS 只画进带 -water 组的诗） ---- */
let waterRowsDeclared = 0, waterRows = [];
const rw = /var ROWS = \[([\s\S]*?)\];/.exec(html);
if (rw) {
  waterRows = [...rw[1].matchAll(/\{\s*y:\s*([\d.]+)[^}]*?o:\s*([\d.]+)[^}]*?n:\s*(\d+)[^}]*?span:\s*([\d.]+)/g)]
    .map(x => ({ y: parseFloat(x[1]), opacity: parseFloat(x[2]), strokes: parseInt(x[3], 10), span: parseFloat(x[4]) }));
  waterRowsDeclared = waterRows.length;
}

const poems = ['jx', 'bd'];
const waterPerPoem = {};
for (const k of poems) waterPerPoem[k] = elements[k + '-water'] ? waterRowsDeclared : 0;

/* ---- 5. 关注元素的存在性清单（含「本该有却缺席」） ---- */
const WATCH = {
  jx: ['jx-cam', 'jx-far', 'jx-waterline', 'jx-water', 'jx-path', 'jx-reed', 'jx-boat', 'jx-line', 'jx-snow', 'jx-anno', 'jx-poemink', 'jx-seal'],
  bd: ['bd-cam', 'bd-cloud', 'bd-city', 'bd-far', 'bd-cliff', 'bd-cun', 'bd-mist', 'bd-water', 'bd-trail', 'bd-boat', 'bd-bow', 'bd-anno', 'bd-poemink', 'bd-seal'],
};
const presence = {};
for (const [k, ids] of Object.entries(WATCH)) {
  presence[k] = {};
  for (const id of ids) presence[k][id] = elements[id]
    ? { present: true, filter: elements[id].filter, filterKind: elements[id].filter ? filters[elements[id].filter].kind : null, opacity: elements[id].opacity }
    : { present: false };
}

/* ---- 6. 元素 → 滤镜 反查表 ---- */
const byFilter = {};
for (const [id, e] of Object.entries(elements)) {
  if (!e.filter) continue;
  (byFilter[e.filter] = byFilter[e.filter] || []).push(id);
}

/* ---- 7. 关注元素的「笔触清单」：组内所有绘制基元的填充/描边/透明度/滤镜 ----
   用于把「墨色浓淡」「湿笔/干笔」这类判据从散文证据换成可计算事实。 */
const paints = {};
for (const ids of Object.values(WATCH)) {
  for (const id of ids) {
    const el = elements[id];
    if (!el) { paints[id] = null; continue; }
    if (el.tag !== 'g') {
      paints[id] = [{ tag: el.tag, fill: el.fill, stroke: el.stroke, opacity: el.opacity, filter: el.filter, geom: el.geom }];
      continue;
    }
    const sp = spanOf(id);
    paints[id] = sp
      ? prims.filter(p => p.idx > sp.start && p.idx < sp.end)
          .map(p => ({
            tag: p.tag,
            /* 组上的 fill/stroke 会被子笔触继承（如 #jx-reed 的 stroke 写在组上），
               子笔触自己没写时必须回落到组值，否则「墨色/干湿」判据会读到空 */
            fill: p.fill != null ? p.fill : el.fill,
            stroke: p.stroke != null ? p.stroke : el.stroke,
            opacity: p.opacity,
            filter: p.filter,
            geom: p.geom,
          }))
      : [];
  }
}

/* ---- 8. 滤镜 → 使用方（区分「组自身挂」与「子笔触挂」） ---- */
const filterUsage = {};
const addUse = (fid, el, scope) => { (filterUsage[fid] = filterUsage[fid] || []).push({ el, scope }); };
for (const [id, e] of Object.entries(elements)) if (e.filter) addUse(e.filter, id, 'self');
for (const [id, list] of Object.entries(paints)) {
  if (!list) continue;
  for (const p of list) if (p.filter) addUse(p.filter, id, 'descendant');
}

const out = {
  meta: {
    source: 'ink_animations.html',
    bytes: Buffer.byteLength(html),
    generated: new Date().toISOString().slice(0, 19),
    note: '静态抽取：标签属性（含数值几何 cx/cy/rx/ry…）+ 滤镜/渐变定义 + 水纹行表。用于把散文证据换成可核对事实。path 的 d 不入库，需要时按字符串单比。',
  },
  elements,
  filters,
  gradients,
  waterRows: { declared: waterRowsDeclared, rows: waterRows, perPoem: waterPerPoem },
  presence,
  byFilter,
  paints,
  filterUsage,
};

fs.writeFileSync(path.join(ROOT, 'data', 'derived', 'o1_source_facts.json'), JSON.stringify(out, null, 2));

console.log('=== o1_source_facts.json ===');
console.log('元素 ' + Object.keys(elements).length + ' 个 · 滤镜 ' + Object.keys(filters).length + ' 个 · 渐变 ' + Object.keys(gradients).length + ' 个');
console.log('\n滤镜分类：');
for (const [id, f] of Object.entries(filters)) {
  console.log('  ' + id.padEnd(12) + f.kind.padEnd(8)
    + ' blur[' + f.gaussianBlur.join(',') + ']'
    + ' disp[' + f.displacementScale.join(',') + ']'
    + (f.feComposite ? ' +feComposite' : '')
    + '  ← ' + (byFilter[id] || []).join(' '));
}
console.log('\n水纹：ROWS 声明 ' + waterRowsDeclared + ' 道 · jx=' + waterPerPoem.jx + ' 道 · bd=' + waterPerPoem.bd + ' 道');

const cloudGeom = (paints['bd-cloud'] || []).filter(p => p.tag === 'ellipse');
console.log('\n彩云几何（bd-cloud，cx/cy/rx/ry）：'
  + cloudGeom.map(p => [p.geom.cx, p.geom.cy, p.geom.rx, p.geom.ry].join('/')).join(' · '));

console.log('\n关注元素存在性：');
for (const [k, o] of Object.entries(presence)) {
  const miss = Object.entries(o).filter(([, v]) => !v.present).map(([id]) => id);
  console.log('  ' + k + '：' + Object.keys(o).length + ' 个，缺席 ' + (miss.length ? miss.join(' ') : '无'));
}

console.log('\n滤镜使用方（self=组自身 / descendant=子笔触）：');
for (const [fid, uses] of Object.entries(filterUsage)) {
  console.log('  ' + fid.padEnd(11) + filters[fid].kind.padEnd(8)
    + uses.map(u => u.el + (u.scope === 'descendant' ? '(子)' : '')).join(' '));
}
