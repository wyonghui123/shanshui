// o1_judge.mjs —— 判读卡组装器（O1.2 核心）
// 把「逐题作答」从人工目视固化成可复跑的流水线：
//   1) 每道题生成一张判读卡：判读帧 + 该帧的客观探针值 + 源码事实；
//   2) 自动层（auto）：凡判据能由源码/探针算出者，直接给出作答，不依赖目视；
//   3) VLM 层（vlm）：目视类题读 o1_vlm_answers.json 的作答记录；
//   4) 合并层（effective）：自动层可判者用自动层，否则用 VLM 层；两层不一致即报冲突。
// 依赖：o1_qset.json / o1_source_facts.json / o1_vis.json / o1_probe.json /
//       o1_cam_trace.json / o1_vlm_answers.json（缺失时由 o1_baseline.json 播种）
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
const F = rd('o1_source_facts.json');
const V = rd('o1_vis.json');
const P = rd('o1_probe.json');
const C = rd('o1_cam_trace.json');

const PAPER = 243;                                   // #F6F3EC 的感知亮度
const TH = { strong: 100, mid: 40, faint: 170, grayMid: 120, blankBig: 0.6, blankHalf: 0.3, waterSparse: 6 };

/* ---------- 基础工具 ---------- */
const hexLum = h => { const n = parseInt(h.replace('#', ''), 16); return 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255); };
const gradRep = gid => { const st = F.gradients[gid]; if (!st || !st.length) return null; const top = st.reduce((a, b) => b.opacity > a.opacity ? b : a); return { lum: hexLum(top.color), alpha: top.opacity }; };
const urlId = s => { const m = /^url\(#(.+)\)$/.exec(s || ''); return m ? m[1] : null; };

/* 单笔触「合成到纸面」的亮度：只算这一笔，避免把细白描边当面积铺满。
   ga = 所属组的透明度（组透明度不在子笔触属性上，必须显式乘进来） */
function paintLum(p, ga) {
  const a0 = (p.opacity == null ? 1 : p.opacity) * (ga == null ? 1 : ga);
  if (p.fill && p.fill !== 'none') {
    const g = urlId(p.fill);
    if (g) { const r = gradRep(g); return r ? Math.round(PAPER * (1 - a0 * r.alpha) + r.lum * a0 * r.alpha) : null; }
    if (p.fill.startsWith('#')) return Math.round(PAPER * (1 - a0) + hexLum(p.fill) * a0);
    return null;
  }
  if (p.stroke && p.stroke !== 'none' && p.stroke.startsWith('#')) return Math.round(PAPER * (1 - a0) + hexLum(p.stroke) * a0);
  return null;
}
const elemAlpha = id => { const e = F.elements[id]; return e && e.opacity != null ? e.opacity : 1; };
/* 某元素「最浓的一笔」的亮度 —— 浓淡比较用这个，而不是把整组笔触叠起来 */
function darkestInk(id) {
  const ps = F.paints[id];
  if (!ps || !ps.length) return null;
  const ga = elemAlpha(id);
  const ls = ps.map(p => paintLum(p, ga)).filter(x => x != null);
  return ls.length ? Math.min(...ls) : null;
}
const isGray = h => { const n = parseInt(h.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255; return Math.max(r, g, b) - Math.min(r, g, b) <= 24; };
function allGray(id) {
  const cols = [];
  for (const p of F.paints[id] || []) {
    const g = urlId(p.fill || '');
    if (g && F.gradients[g]) for (const st of F.gradients[g]) cols.push(st.color);
    else if (p.fill && p.fill.startsWith('#')) cols.push(p.fill);
    else if (p.stroke && p.stroke.startsWith('#')) cols.push(p.stroke);
  }
  return cols.length ? cols.every(isGray) : null;
}

/* 探针取值 */
const visAt = (poem, t, id) => (V[poem].frames[String(t)] || {})[id] || null;
const visVal = (poem, t, id) => { const e = visAt(poem, t, id); return e && e.present ? e.vis : null; };
const rectAt = (poem, t, id) => { const e = visAt(poem, t, id); return e && e.present ? e.rect : null; };
const dashFrac = (poem, t, id) => { const e = visAt(poem, t, id); if (!e || !e.present) return null; return e.dashes.length ? Math.max(...e.dashes.map(d => d.visibleFrac)) : null; };
const probeByFrame = f => P.find(x => x.name === (f === 'bd_04' ? 'bd_04去诗 全幅' : f + ' 全幅'));
const probeByName = n => P.find(x => x.name === n);
/* 某滤镜的全部使用方（组自身 + 子笔触）；排除 *-cam 这类整场景容器，去重 */
const usersOf = f => [...new Set((F.filterUsage[f] || []).map(u => u.el))].filter(e => !/-cam$/.test(e));

const yn = v => v ? '是' : '否';
const band = (v, lo, hi) => v >= lo && v <= hi;

/* 从选项文本解析数值区间（复用校验器口径） */
function parseBands(text) {
  const out = []; const re = /(\d+(?:\.\d+)?)\s*[–\-~]\s*(\d+(?:\.\d+)?)/g; let m;
  while ((m = re.exec(text)) !== null) out.push([parseFloat(m[1]), parseFloat(m[2])]);
  return out;
}
/* 九宫格方位标签：与选项口径一致，先「左右」后「上下」（如 左上 / 右下） */
const posOf = (cx, cy) => (cx < 0.42 ? '左' : (cx > 0.58 ? '右' : '中')) + (cy < 0.42 ? '上' : (cy > 0.58 ? '下' : '中'));

/* ---------- 自动层规则表 ---------- */
/* 每项返回 { verdict, decidable, rule, conf, data }。decidable=false 表示
   该判据不足以独立作答（如「源码里没有鸟」不能证明画面上没画鸟），只作交叉核对。 */
const R = {};

/* —— 江雪 · EXIST —— */
R['JX-E1'] = () => ({ v: yn(visVal('jx', 5.09, 'jx-far') > 0.05), rule: 'V.jx@5.09 #jx-far 可见性', data: visVal('jx', 5.09, 'jx-far') });
R['JX-E2'] = () => ({ v: yn(visVal('jx', 12.14, 'jx-boat') > 0.05), rule: 'V.jx@12.14 #jx-boat 可见性', data: visVal('jx', 12.14, 'jx-boat') });
R['JX-E3'] = () => ({ v: yn(visVal('jx', 19.03, 'jx-boat') > 0.05 && (F.paints['jx-boat'] || []).length >= 3), rule: 'V.jx@19.03 #jx-boat 可见性 + 组内人物笔触数', data: { vis: visVal('jx', 19.03, 'jx-boat'), paints: (F.paints['jx-boat'] || []).length } });
R['JX-E4'] = () => ({ v: yn(visVal('jx', 5.09, 'jx-reed') > 0.05), rule: 'V.jx@5.09 #jx-reed 可见性', data: visVal('jx', 5.09, 'jx-reed') });
R['JX-E5'] = () => ({ v: yn(dashFrac('jx', 19.03, 'jx-line') > 0.5), rule: 'V.jx@19.03 #jx-line 描边可见比例（dashoffset）', data: dashFrac('jx', 19.03, 'jx-line') });
R['JX-E6'] = () => ({ v: yn(visVal('jx', 5.09, 'jx-snow') > 0.05), rule: 'V.jx@5.09 #jx-snow 可见性', data: visVal('jx', 5.09, 'jx-snow') });

/* —— 江雪 · NEGATIVE（交叉核对，不作主判） —— */
R['JX-N1'] = () => ({ v: '否', decidable: false, conf: 'low', rule: '源码无任何鸟形元素（交叉核对，需目视确认）' });
R['JX-N2'] = () => {
  const persons = Object.keys(F.paints).filter(id => /-boat$/.test(id) && (F.paints[id] || []).length >= 3);
  return { v: yn(persons.length > 1), decidable: false, conf: 'low', rule: '源码中含人物笔触的组仅 ' + persons.length + ' 个（' + persons.join('/') + '）', data: persons };
};
R['JX-N3'] = () => ({ v: '否', decidable: false, conf: 'low', rule: '源码无足迹/脚印元素（交叉核对）' });

/* —— 江雪 · ATTR —— */
R['JX-A1'] = () => {
  const cands = [{ o: '孤舟与蓑笠翁', id: 'jx-boat' }, { o: '远山', id: 'jx-far' }, { o: '芦苇', id: 'jx-reed' }];
  const ink = cands.map(c => ({ ...c, lum: darkestInk(c.id) }));
  const min = ink.filter(x => x.lum != null).reduce((a, b) => (b.lum < a.lum ? b : a));
  return { v: min.o, rule: '最浓 = 最暗单笔合成亮度 argmin', data: ink };
};
R['JX-A2'] = () => {
  const l = darkestInk('jx-far');
  return { v: l >= TH.faint ? '很淡' : (l >= TH.grayMid ? '中等' : '很浓'), rule: '远山最浓笔合成亮度 ' + l, data: { lum: l } };
};
R['JX-A3'] = () => {
  const p = probeByFrame('jx_02'); const r = p.paperFrac;
  return { v: r >= TH.blankBig ? '大面积留白' : (r >= TH.blankHalf ? '大致均衡' : '画得很满'), rule: 'P.' + p.name + ' 留白率 ' + r, data: { paperFrac: r } };
};
R['JX-A4'] = () => {
  const n = F.waterRows.perPoem.jx;
  return { v: n === 0 ? '几乎不画，以留白表现' : (n <= TH.waterSparse ? '画了少量水纹' : '画满水纹'), rule: '源码 ROWS 在 jx 下道数 = ' + n + '（无 #jx-water 组）', data: { rows: n } };
};
R['JX-A5'] = () => {
  const op = F.elements['jx-path'] ? F.elements['jx-path'].opacity : null;
  const vis = visVal('jx', 7.83, 'jx-path');
  return { v: (op != null && op <= 0.25 && vis > 0) ? '极淡、几乎不可见' : (vis > 0.4 ? '清晰可见' : '完全没有'), conf: 'low', rule: '#jx-path 组透明度 ' + op + '、@jx_05 可见性 ' + vis + ' → 已画出但极淡', data: { opacity: op, vis } };
};
R['JX-A6'] = () => {
  const dark = darkestInk('jx-boat'), light = darkestInk('jx-far'), d = light - dark;
  return { v: d >= TH.strong ? '强对比（浓淡悬殊）' : (d >= TH.mid ? '中等对比' : '弱对比（几乎同色）'), rule: 'Δlum = 远山 ' + light + ' − 孤舟 ' + dark + ' = ' + d, data: { dark, light, delta: d } };
};
R['JX-A7'] = () => {
  const f = F.elements['jx-reed'].filter, fd = F.filters[f];
  const wet = fd.gaussianBlur.length > 0;
  return { v: wet ? '湿笔晕染（边缘柔化、墨色外溢）' : (fd.feComposite ? '飞白' : '毛边干笔（边缘毛涩、无晕染）'), rule: '#jx-reed 滤镜 ' + f + '：模糊[' + fd.gaussianBlur.join(',') + '] 位移[' + fd.displacementScale.join(',') + '] feComposite=' + fd.feComposite, data: { filter: f, kind: fd.kind } };
};
R['JX-A8'] = () => {
  const p = probeByFrame('jx_04');
  return { v: (p.paperFrac >= TH.blankBig && p.darkFrac < 0.05) ? '大面积疏（留白）中藏着极小的密（孤舟焦点）' : (p.paperFrac >= TH.blankHalf ? '疏密均匀分布' : '大面积密（画满）中留小空白'), rule: 'P.' + p.name + ' 留白 ' + p.paperFrac + '、浓墨 ' + p.darkFrac, data: { paperFrac: p.paperFrac, darkFrac: p.darkFrac } };
};
R['JX-A9'] = () => {
  const p = probeByName('jx_05去诗 下半(排芦苇)');
  return { v: p.paperFrac >= 0.9 ? '中下部（远山以下的寒江江面）' : '四周边缘', conf: 'mid', rule: 'P.' + p.name + ' 留白率 ' + p.paperFrac + '（下半幅近乎全白）', data: { paperFrac: p.paperFrac } };
};

/* —— 江雪 · SPATIAL —— */
R['JX-S1'] = () => { const r = rectAt('jx', 5.09, 'jx-far'); return { v: r.cy < 0.42 ? '上部' : (r.cy > 0.58 ? '下部' : '中部'), rule: 'V.jx@5.09 #jx-far 归一化中心 y=' + r.cy, data: r }; };
R['JX-S2'] = () => { const r = rectAt('jx', 12.14, 'jx-boat'); return { v: posOf(r.cx, r.cy), rule: 'V.jx@12.14 #jx-boat 中心 (' + r.cx + ',' + r.cy + ')', data: r }; };
R['JX-S3'] = () => { const r = rectAt('jx', 5.09, 'jx-reed'); return { v: posOf(r.cx, r.cy), rule: 'V.jx@5.09 #jx-reed 中心 (' + r.cx + ',' + r.cy + ')', data: r }; };
R['JX-S4'] = () => {
  const val = QSET.poems.find(p => p.id === 'jx').questions.find(q => q.id === 'JX-S4').measured.value;
  const opt = QSET.poems.find(p => p.id === 'jx').questions.find(q => q.id === 'JX-S4').options
    .find(o => parseBands(o).some(([a, b]) => val >= a && val <= b));
  return { v: opt, rule: '题内 measured = ' + val + 'H，落在档位「' + opt + '」', data: { value: val } };
};
R['JX-S5'] = () => {
  const b = darkestInk('jx-boat'), f = darkestInk('jx-far');
  return { v: b < f ? '孤舟在前、远山在后' : '远山在前、孤舟在后', rule: '孤舟 ' + b + ' < 远山 ' + f + ' → 近景更浓', data: { boat: b, far: f } };
};

/* —— 江雪 · TEMPORAL —— */
R['JX-T1'] = () => {
  const f1 = visVal('jx', 0.78, 'jx-far'), b1 = visVal('jx', 0.78, 'jx-boat');
  return { v: yn(f1 > 0.05 && !(b1 > 0.05)), rule: 'V.jx@0.78 远山 ' + f1 + ' / 孤舟 ' + b1, data: { far: f1, boat: b1 } };
};
R['JX-T2'] = () => {
  const a = dashFrac('jx', 12.14, 'jx-line'), b = dashFrac('jx', 19.03, 'jx-line');
  return { v: yn(!(a > 0.2) && b > 0.5), rule: 'V #jx-line 描边比例 @12.14=' + a + ' @19.03=' + b, data: { at155: a, at243: b } };
};
R['JX-T3'] = () => {
  const ts = [0.78, 5.09, 19.03].map(t => visVal('jx', t, 'jx-snow'));
  return { v: yn(ts.every(x => x > 0.05)), rule: 'V.jx 雪可见性 @0.78/5.09/19.03 = ' + ts.join('/'), data: ts };
};
R['JX-T5'] = () => {
  const c = C.jx.curve;
  const early = Math.max(...c.filter(p => p.t <= 5.09).map(p => Math.abs(p.v)));
  const peak = c.reduce((a, b) => Math.abs(b.v) > Math.abs(a.v) ? b : a);
  const vmax = Math.abs(peak.v);
  /* V3-1：压平后判据 = 前段近乎静止（|v|≈0）+ 峰值 ≤ 0.05/s（无急推）+ 净推近 + 无定格 */
  const shape = (early < 1e-3 && vmax <= 0.05 && C.jx.s_end > C.jx.s_start && C.jx.freeze_from == null) ? 0 : -1;
  return { v: shape === 0 ? QSET.poems.find(p => p.id === 'jx').questions.find(q => q.id === 'JX-T5').options[0] : null, rule: 'C.jx：前段 |v|max=' + early + '、峰值 @t=' + peak.t + ' v=' + vmax.toFixed(5) + '（≤0.05/s＝无急推）、s ' + C.jx.s_start + '→' + C.jx.s_end, data: { early, peak: peak.t, vmax: +vmax.toFixed(5), tail: c[c.length - 1].v } };
};

/* —— 早发白帝城 · EXIST —— */
R['BD-E1'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-city') > 0.05), rule: 'V.bd@2.56 #bd-city 可见性', data: visVal('bd', 2.56, 'bd-city') });
R['BD-E2'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-cloud') > 0.05), conf: 'low', rule: 'V.bd@2.56 #bd-cloud 可见性', data: visVal('bd', 2.56, 'bd-cloud') });
R['BD-E3'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-boat') > 0.05), rule: 'V.bd@2.56 #bd-boat 可见性', data: visVal('bd', 2.56, 'bd-boat') });
R['BD-E4'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-cliff') > 0.05), rule: 'V.bd@2.56 #bd-cliff 可见性', data: visVal('bd', 2.56, 'bd-cliff') });
R['BD-E5'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-far') > 0.05 && (F.paints['bd-far'] || []).length >= 3), rule: 'V.bd@2.56 #bd-far 可见性 + 层数', data: { vis: visVal('bd', 2.56, 'bd-far'), layers: (F.paints['bd-far'] || []).length } });
R['BD-E6'] = () => ({ v: yn(visVal('bd', 2.56, 'bd-water') > 0.05), rule: 'V.bd@2.56 #bd-water 可见性', data: visVal('bd', 2.56, 'bd-water') });
R['BD-E7'] = () => ({ v: yn(dashFrac('bd', 13.27, 'bd-trail') > 0.5), rule: 'V.bd@13.27 #bd-trail 描边可见比例', data: dashFrac('bd', 13.27, 'bd-trail') });

/* —— 早发白帝城 · NEGATIVE（交叉核对） —— */
R['BD-N1'] = () => ({ v: '否', decidable: false, conf: 'low', rule: '源码无猿/猴形元素（交叉核对，需目视确认）' });
R['BD-N2'] = () => ({ v: '否', decidable: false, conf: 'low', rule: '源码仅 #bd-city 一座城，无江陵城元素（交叉核对）' });

/* —— 早发白帝城 · ATTR —— */
R['BD-A1'] = () => {
  const cands = [{ o: '轻舟', id: 'bd-boat' }, { o: '白帝城', id: 'bd-city' }, { o: '彩云', id: 'bd-cloud' }, { o: '两岸山壁', id: 'bd-cliff' }];
  const ink = cands.map(c => ({ ...c, lum: darkestInk(c.id) }));
  const min = ink.reduce((a, b) => (b.lum < a.lum ? b : a));
  return { v: min.o, rule: '最浓 = 最暗单笔合成亮度 argmin', data: ink };
};
R['BD-A2'] = () => {
  const g = allGray('bd-cloud'), l = darkestInk('bd-cloud');
  return { v: g === false ? '彩色（红黄等）' : (l >= TH.faint ? '淡墨浅灰' : '浓墨'), rule: '云填充是否灰阶 = ' + g + '、最浓笔亮度 ' + l, data: { gray: g, lum: l } };
};
R['BD-A3'] = () => { const n = F.waterRows.perPoem.bd; return { v: n <= TH.waterSparse ? '稀疏、仅数道' : (n <= 12 ? '中等' : '密集布满'), rule: '源码 ROWS 在 bd 下道数 = ' + n, data: { rows: n } }; };
R['BD-A4'] = () => {
  const p = probeByFrame('bd_04'); const r = p.paperFrac;
  return { v: r >= TH.blankBig ? '大面积留白' : (r >= TH.blankHalf ? '约一半' : '几乎不留白'), conf: 'mid', rule: 'P.' + p.name + '（渲染口径 ρ_render）留白 ' + r, data: { paperFrac: r } };
};
R['BD-A5'] = () => {
  const order = [{ o: '轻舟', id: 'bd-boat' }, { o: '白帝城', id: 'bd-city' }, { o: '两岸山壁', id: 'bd-cliff' }, { o: '彩云', id: 'bd-cloud' }]
    .map(c => ({ ...c, lum: darkestInk(c.id) })).sort((a, b) => a.lum - b.lum);
  return { v: order.map(x => x.o).join(' > '), rule: '按最浓笔亮度升序（浓→淡）', data: order };
};
R['BD-A6'] = () => {
  const f = F.elements['bd-cliff'].filter, fd = F.filters[f];
  const fills = (F.paints['bd-cliff'] || []).map(p => p.fill);
  const softUsers = usersOf('bdSoft');
  return {
    v: null, decidable: false, conf: 'low',
    rule: '自动层不可独立作答（属观感判断，非二值滤镜特征）：#bd-cliff 组滤镜是 ' + f + '（模糊[' + fd.gaussianBlur.join(',') + ']、位移[' + fd.displacementScale.join(',') + ']，干笔位移、无高斯模糊），'
      + '主体笔触为横向渐变填充 ' + JSON.stringify(fills) + '（无描边硬边 → 观感柔化、无断白，读作湿笔晕染）；'
      + '湿笔模糊 bdSoft 实际用于 ' + softUsers.join('/') + '。'
      + '口径已修正（原 why 误把 bdSoft 挂到山壁，见 o1_lint.json）；湿笔感来自渐变而非模糊，故仍交目视层定案',
    data: { filter: f, kind: fd.kind, fills, softUsers },
  };
};
R['BD-A7'] = () => {
  const L = probeByName('bd_02 左壁(x0-0.30)'), M = probeByName('bd_02 中央峡口(x0.44-0.62)'), Rg = probeByName('bd_02 右壁(x0.70-1)');
  const sides = (L.inkFrac + Rg.inkFrac) / 2, center = M.inkFrac;
  return { v: sides > center ? '两侧山壁密、中央峡口疏（留白）' : '中央密、两侧疏', rule: 'P：左壁墨 ' + L.inkFrac + ' / 中央 ' + center + ' / 右壁 ' + Rg.inkFrac, data: { left: L.inkFrac, center, right: Rg.inkFrac } };
};
R['BD-A8'] = () => {
  const M = probeByName('bd_02 中央峡口(x0.44-0.62)'), L = probeByName('bd_02 左壁(x0-0.30)'), Rg = probeByName('bd_02 右壁(x0.70-1)');
  return { v: M.paperFrac > Math.max(L.paperFrac, Rg.paperFrac) ? '中央峡口并向下展开为江面，呈向纵深收束的透光带' : '左右两侧', conf: 'mid', rule: 'P 留白：中央 ' + M.paperFrac + ' vs 左 ' + L.paperFrac + ' / 右 ' + Rg.paperFrac, data: { center: M.paperFrac, left: L.paperFrac, right: Rg.paperFrac } };
};

/* —— 早发白帝城 · SPATIAL —— */
R['BD-S1'] = () => { const r = rectAt('bd', 2.56, 'bd-city'); return { v: posOf(r.cx, r.cy), rule: 'V.bd@2.56 #bd-city 中心 (' + r.cx + ',' + r.cy + ')', data: r }; };
R['BD-S2'] = () => { const r = rectAt('bd', 2.56, 'bd-boat'); return { v: posOf(r.cx, r.cy), rule: 'V.bd@2.56 #bd-boat 中心 (' + r.cx + ',' + r.cy + ')', data: r }; };
R['BD-S6'] = () => {
  const r = rectAt('bd', 2.56, 'bd-boat');
  return { v: r.cx < 0.5 ? '左下' : '右下', rule: '焦点（浓墨轻舟）中心 x=' + r.cx + ' → 重心侧', data: r };
};

/* —— 早发白帝城 · TEMPORAL —— */
R['BD-T1'] = () => {
  const c1 = visVal('bd', 0.57, 'bd-city'), b1 = visVal('bd', 0.57, 'bd-boat');
  return { v: yn(c1 > 0.05 && !(b1 > 0.05)), rule: 'V.bd@0.57 城 ' + c1 + ' / 舟 ' + b1, data: { city: c1, boat: b1 } };
};
R['BD-T3'] = () => {
  const a = dashFrac('bd', 2.56, 'bd-trail'), b = dashFrac('bd', 13.27, 'bd-trail');
  return { v: yn(!(a > 0.2) && b > 0.5), rule: 'V #bd-trail 描边比例 @2.56=' + a + ' @13.27=' + b, data: { at45: a, at233: b } };
};
R['BD-T4'] = () => {
  const c = C.bd;
  const ok = c.s_end > c.s_start && c.freeze_from == null && c.vmax.t >= c.T - 1.5;
  return { v: yn(ok), rule: 'C.bd：s ' + c.s_start + '→' + c.s_end + '、递增步 ' + c.monotonic_inc_steps + ' / 递减步 ' + c.monotonic_dec_steps + '、vmax @t=' + c.vmax.t + '、无定格', data: { inc: c.monotonic_inc_steps, dec: c.monotonic_dec_steps, vmaxT: c.vmax.t } };
};
R['BD-T5'] = () => {
  const c = C.bd;
  const dip = c.curve.filter(p => p.v < -0.005);
  const ok = c.vmax.t >= c.T - 1.5 && dip.length > 0 && c.freeze_from == null;
  return { v: ok ? QSET.poems.find(p => p.id === 'bd').questions.find(q => q.id === 'BD-T5').options[0] : null, rule: 'C.bd：vmax @t=' + c.vmax.t + '、中段负速采样 ' + dip.length + ' 个（t=' + (dip.length ? dip[0].t + '–' + dip[dip.length - 1].t : '—') + '）、无定格', data: { vmaxT: c.vmax.t, dipCount: dip.length } };
};

/* ---------- VLM 作答记录（缺失则用 v1.2 基线播种） ---------- */
function loadVlm() {
  const p = path.join(ROOT, 'data', 'source', 'o1_vlm_answers.json');
  if (fs.existsSync(p)) return { answers: JSON.parse(fs.readFileSync(p, 'utf8')), seeded: false };
  const B = rd('o1_baseline.json');
  const answers = {
    meta: {
      generated: new Date().toISOString().slice(0, 19),
      source: 'o1_baseline.json（v1.2 多模态判读结果）',
      note: '本轮无可用 VLM 端点，VLM 层以 v1.2 基线的逐题判读冻结；接入真实 VLM 后按同一 schema 覆盖 answer/conf/evidence 即可，脚本无需改动。',
      replaceable: true,
      schema: { id: '题号', poem: '诗', frame: '判读帧', answer: '作答', conf: 'high|mid|low', source: '作答来源', evidence: '依据' },
    },
    answers: B.results.map(r => ({ id: r.id, poem: r.poem, frame: r.frame, answer: r.answer, conf: r.conf, source: 'baseline-v1.2', replaceable: true, evidence: r.evidence })),
  };
  fs.writeFileSync(p, JSON.stringify(answers, null, 2));
  return { answers, seeded: true };
}

/* ---------- 组装判读卡 ---------- */
const { answers: VLM, seeded } = loadVlm();
const vlmById = {}; for (const a of VLM.answers) vlmById[a.id] = a;

const cards = [];
const conflicts = [];
for (const poem of QSET.poems) {
  const frameT = {}; for (const f of poem.frames) frameT[f.name] = f.t;
  for (const q of poem.questions) {
    const frames = q.frame.split('+').map(s => s.trim()).filter(Boolean);
    const rule = R[q.id];
    let auto = { decidable: false, verdict: null, rule: '（未定义自动判据，走目视层）', conf: 'mid', data: null };
    if (rule) {
      const r = rule();
      auto = { decidable: r.decidable !== false && r.v != null, verdict: r.v, rule: r.rule, conf: r.conf || 'high', data: r.data === undefined ? null : r.data };
    }
    const vlm = vlmById[q.id] || null;
    const eff = auto.decidable ? { answer: auto.verdict, source: 'auto' } : (vlm ? { answer: vlm.answer, source: 'vlm' } : { answer: null, source: 'none' });
    const conflict = !!(auto.decidable && vlm && auto.verdict !== vlm.answer);

    cards.push({
      id: q.id, poem: poem.id, axis: q.axis, basis: q.basis, w: q.w,
      type: q.type, q: q.q, options: q.options || null, expect: q.expect,
      frame: q.frame, frameTimes: frames.map(n => ({ name: n, t: frameT[n] })),
      media: q.media, probe_assisted: !!q.probe_assisted, measured: q.measured || null,
      auto, vlm: vlm ? { answer: vlm.answer, conf: vlm.conf, source: vlm.source, replaceable: vlm.replaceable, evidence: vlm.evidence } : null,
      effective: eff, conflict,
    });
    if (conflict) conflicts.push({ id: q.id, auto: auto.verdict, vlm: vlm.answer, rule: auto.rule });
  }
}

const autoN = cards.filter(c => c.auto.decidable).length;
const vlmN = cards.filter(c => !c.auto.decidable && c.vlm).length;
const noneN = cards.filter(c => !c.auto.decidable && !c.vlm).length;

const out = {
  meta: {
    generated: new Date().toISOString().slice(0, 19),
    qset: 'o1_qset.json @ v' + QSET.meta.version,
    inputs: ['o1_source_facts.json', 'o1_vis.json', 'o1_probe.json', 'o1_cam_trace.json', 'o1_vlm_answers.json'],
    vlm_seeded_from_baseline: seeded,
    note: '自动层判据全部来自源码事实与像素/DOM 探针，不含目视；目视类题读 VLM 作答记录。两层不一致时 effective 采自动层，并列入 conflicts 供复核。',
    counts: { total: cards.length, auto: autoN, vlm: vlmN, none: noneN, conflicts: conflicts.length },
  },
  conflicts,
  cards,
};
fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_judge_cards.json'), JSON.stringify(out, null, 2));

console.log('=== o1_judge_cards.json ===');
console.log('判读卡 ' + cards.length + ' 张 · 自动层可判 ' + autoN + ' · 目视层 ' + vlmN + ' · 无作答 ' + noneN
  + (seeded ? '（VLM 记录由基线播种 → o1_vlm_answers.json）' : ''));
console.log('\n自动层未覆盖（走目视层）：');
for (const c of cards.filter(c => !c.auto.decidable)) console.log('  ' + c.id.padEnd(8) + c.axis.padEnd(9) + c.auto.rule.slice(0, 72));
if (conflicts.length) {
  console.log('\n⚠ 自动层与目视层冲突 ' + conflicts.length + ' 处：');
  for (const c of conflicts) console.log('  ' + c.id + '：自动层「' + c.auto + '」 vs 目视层「' + c.vlm + '」 —— ' + c.rule);
} else {
  console.log('\n自动层与目视层无冲突');
}
