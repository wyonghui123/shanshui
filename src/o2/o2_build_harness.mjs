// o2_build_harness.mjs —— 由 o2_imagery.json 生成复核工装页 o2_imagery_harness.html
// 目的：把「人工抽节点」降级为「人工复核」——诗面高亮 + 意象表 + 消歧卡 + gold 对照 + 画面核对 + 复核队列。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));
const O = rd('o2_imagery.json');
const G = rd('o2_gold.json');

const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = v => (v == null ? '—' : (v * 100).toFixed(1) + '%');
const clsOf = n => n.neg_kind === '缺席' ? 'neg' : n.neg_kind === '跨通道' ? 'cross' : n.gate.class.startsWith('动作') ? 'act' : n.gate.class === '实写' ? 'solid' : n.gate.class === '虚写' ? 'faint' : 'void';
const clsName = { solid: '实写', faint: '虚写', void: '不可实写', neg: '负节点·缺席', cross: '负节点·跨通道', act: '动作' };

function poemHTML(p) {
  const P = O.poems[p], g = G.poems[p];
  const nodes = P.nodes;
  const linesHTML = g.text.map((line, li) => {
    const chars = [...line].map((ch, ci) => {
      const pos = ci + 1;
      const n = nodes.find(x => x.line === li + 1 && pos >= x.span[0] && pos <= x.span[1]);
      return n ? `<span class="ch ${clsOf(n)}" title="${esc(n.canonical)}｜${esc(clsName[clsOf(n)])}｜可画性 ${n.conc == null ? '—' : n.conc}">${esc(ch)}</span>` : `<span class="ch">${esc(ch)}</span>`;
    }).join('');
    return `<div class="pline"><span class="lno">${li + 1}</span>${chars}</div>`;
  }).join('');

  const rows = nodes.map(n => `<tr>
    <td class="em">${esc(n.canonical)}</td><td class="num">${n.line}</td><td class="num">${n.span[0]}–${n.span[1]}</td>
    <td class="num">${esc(n.channel)}</td><td class="num">${n.conc == null ? '—' : n.conc}</td>
    <td><span class="pill ${clsOf(n)}">${esc(n.neg_kind ? '负节点·' + n.neg_kind : n.gate.class)}</span></td>
    <td class="dim">${esc(n.layer_hint || '—')}</td><td class="dim">${esc(n.polarity_hint || '—')}</td>
    <td class="dim">${esc(n.neg_kind ? n.gate.render : n.gate.basis)}</td></tr>`).join('');

  const dis = P.disambiguation.map(d => `<div class="card dis">
    <div class="dh">第${d.line}句「${esc(d.span)}」${d.need_review ? '<span class="tag review">需复核</span>' : '<span class="tag ok">已定</span>'}</div>
    <div class="drow"><span class="dk">取</span><span class="dv">${esc(d.chosen)}</span></div>
    <div class="drow"><span class="dk">备选</span><span class="dv dim">${esc(d.alt)}</span></div>
    <div class="drow"><span class="dk">理由</span><span class="dv dim">${esc(d.why)}</span></div></div>`).join('') || '<div class="dim">本诗无需消歧。</div>';

  const v = O.validation[p];
  const vrows = v.rows.map(r => `<tr>
    <td class="em">${esc(r.canonical)}</td>
    <td class="num">${r.in_auto ? '✓' : '✗'}</td>
    <td class="num">${r.line == null ? '—' : r.line ? '✓' : '✗'}</td>
    <td class="num">${r.span == null ? '—' : r.span ? '✓' : '✗'}</td>
    <td class="dim">${esc(r.class_gold)}</td><td class="dim">${esc(r.class_auto || '未抽出')}</td>
    <td class="num">${r.class_ok ? '✓' : '✗'}</td></tr>`).join('');
  const vextra = v.extra.length ? `<tr class="extra"><td colspan="7">自动多出：${v.extra.map(e => esc(e.canonical)).join('、')}</td></tr>` : '';

  const c = O.crosscheck[p];
  return `<section class="poem">
  <div class="ph"><h2>《${esc(P.title)}》${esc(P.author)}</h2><span class="form">${esc(P.form.name)} · ${P.counts.imagery} 节点（正 ${P.counts.pos} / 留白 ${P.counts.blank} / 负 ${P.counts.neg} / 动作 ${P.counts.action}）</span>
    <span class="seg">分词校验 ${P.segment_ok ? '✓' : '✗'}</span></div>
  <div class="poembox">${linesHTML}</div>
  <div class="legend">${Object.entries(clsName).map(([k, v2]) => `<span class="lg"><i class="sw ${k}"></i>${v2}</span>`).join('')}</div>

  <h3>意象表</h3>
  <table><thead><tr><th>意象</th><th>句</th><th>位置</th><th>通道</th><th>可画性</th><th>档</th><th>层级(提示)</th><th>极性(提示)</th><th>门控依据 / 渲染作用</th></tr></thead><tbody>${rows}</tbody></table>

  <h3>依存消歧（O6 顺带产出）</h3>
  ${dis}

  <h3>验证 vs 人工 gold</h3>
  <div class="rates"><span>召回 <b>${pct(v.recall)}</b></span><span>精确 <b>${pct(v.precision)}</b></span><span>句 <b>${pct(v.lineOk)}</b></span><span>位置 <b>${pct(v.spanOk)}</b></span><span>类型 <b>${pct(v.classOk)}</b></span></div>
  <table class="small"><thead><tr><th>意象</th><th>抽出</th><th>句</th><th>位置</th><th>gold 类型</th><th>自动类型</th><th>类型符</th></tr></thead><tbody>${vrows}${vextra}</tbody></table>

  <h3>意象 ↔ 画面 核对</h3>
  <div class="cross">
    <div><span class="ck">已画</span>${c.drawnImagery.map(x => `<span class="chip">${esc(x)}</span>`).join('') || '<span class="dim">—</span>'}</div>
    <div><span class="ck">应画未画</span>${c.missing.length ? c.missing.map(m => `<span class="chip warn">${esc(m.canonical)}</span>`).join('') : '<span class="dim">无</span>'}</div>
    <div><span class="ck">画中多出</span>${c.extra_in_art.length ? c.extra_in_art.map(m => `<span class="chip warn">${esc(m.el)}</span>`).join('') : '<span class="dim">无</span>'}</div>
    <div><span class="ck">设计附加</span>${(c.design_added && c.design_added.length) ? c.design_added.map(m => `<span class="chip design">${esc(m.el)}</span><span class="dim">${esc(m.note || '')}</span>`).join('') : '<span class="dim">无</span>'}</div>
    <div><span class="ck">负节点泄漏</span>${c.negLeak.length ? c.negLeak.map(x => `<span class="chip bad">${esc(x)}</span>`).join('') : '<span class="dim">无</span>'}</div>
  </div>
</section>`;
}

const rq = ['歧义句', '未登录词'].map(k => {
  const items = O.review_queue.filter(r => r.kind === k);
  if (!items.length) return '';
  return `<h3>${esc(k)}（${items.length}）</h3><ul class="rq">` + items.map(it =>
    `<li><span class="poemtag">《${esc(G.poems[it.poem].title)}》</span>第${it.line}句 <code>${esc(it.item)}</code>：${esc(it.detail)}${it.why ? '<div class="why">' + esc(it.why) + '</div>' : ''}</li>`).join('') + '</ul>';
}).join('');

const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>O2 意象抽取 · 复核工装页</title>
<style>
:root{--paper:#F6F3EC;--paper2:#fff;--ink:#1C1C1C;--ink2:#4A4640;--ink3:#8A8578;--line:rgba(28,28,28,.14);--line2:rgba(28,28,28,.07);--zhu:#A83A2C;--qing:#3E5C76;--jin:#B08430;--serif:"Songti SC","STSong",SimSun,"Noto Serif SC",Georgia,serif;--sans:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.75;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:52px 28px 88px}
header{border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:36px}
.eyebrow{font-size:12px;letter-spacing:.22em;color:var(--ink3);text-transform:uppercase;margin-bottom:14px}
h1{font-family:var(--serif);font-size:29px;font-weight:600;margin:0 0 8px;letter-spacing:.04em}
.sub{color:var(--ink3);font-size:13px}.sub code{font-family:var(--mono);font-size:12px;background:var(--paper2);border:1px solid var(--line2);border-radius:4px;padding:0 4px}
h2{font-family:var(--serif);font-size:22px;font-weight:600;margin:0;letter-spacing:.03em}
h3{font-family:var(--serif);font-size:16px;font-weight:600;margin:30px 0 10px;letter-spacing:.02em;color:var(--ink2)}
section.poem{border-top:1px solid var(--line);padding-top:26px;margin-top:40px}
.ph{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.form{font-size:12.5px;color:var(--ink3)}.seg{font-family:var(--mono);font-size:11.5px;color:var(--qing)}
.poembox{background:var(--paper2);border:1px solid var(--line);border-radius:10px;padding:20px 22px;box-shadow:0 1px 2px rgba(28,28,28,.04)}
.pline{font-family:var(--serif);font-size:26px;letter-spacing:.06em;line-height:1.9;white-space:nowrap}
.lno{font-family:var(--mono);font-size:11px;color:var(--ink3);margin-right:14px;vertical-align:middle}
.ch{padding:1px 0;border-bottom:3px solid transparent;transition:background .12s}
.ch.solid{border-bottom-color:var(--ink)}
.ch.faint{border-bottom:2px dashed var(--ink3)}
.ch.void{border-bottom:2px dotted rgba(28,28,28,.28);color:var(--ink3)}
.ch.neg{color:var(--zhu);border-bottom:2px dashed var(--zhu);text-decoration:line-through;text-decoration-color:rgba(168,58,44,.55)}
.ch.cross{color:var(--jin);border-bottom:2px wavy var(--jin)}
.ch.act{color:var(--qing);border-bottom:2px solid var(--qing)}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:12px 2px 0;font-size:12px;color:var(--ink3)}
.lg{display:inline-flex;align-items:center;gap:6px}.sw{width:16px;height:0;border-bottom:3px solid transparent;display:inline-block}
.sw.solid{border-bottom-color:var(--ink)}.sw.faint{border-bottom:2px dashed var(--ink3)}.sw.void{border-bottom:2px dotted rgba(28,28,28,.28)}.sw.neg{border-bottom:2px dashed var(--zhu)}.sw.cross{border-bottom:2px wavy var(--jin)}.sw.act{border-bottom:2px solid var(--qing)}
table{width:100%;border-collapse:collapse;background:var(--paper2);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line2);text-align:left;vertical-align:top}
thead th{background:rgba(28,28,28,.03);font-weight:600;font-size:12px;color:var(--ink2);letter-spacing:.02em}
tbody tr:last-child td{border-bottom:0}.num{font-family:var(--mono);font-size:12px;white-space:nowrap}
.em{font-family:var(--serif);font-size:15px;font-weight:600}.dim{color:var(--ink3);font-size:12.5px}
tr.extra td{color:var(--zhu);font-size:12.5px}
table.small{font-size:12.5px}
.pill{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.pill.solid{color:var(--ink);background:rgba(28,28,28,.05)}
.pill.faint{color:var(--ink2);background:rgba(138,133,120,.12)}
.pill.void{color:var(--ink3);background:rgba(138,133,120,.08)}
.pill.neg{color:var(--zhu);background:rgba(168,58,44,.10);border-color:rgba(168,58,44,.30)}
.pill.cross{color:var(--jin);background:rgba(176,132,48,.12);border-color:rgba(176,132,48,.32)}
.pill.act{color:var(--qing);background:rgba(62,92,118,.10);border-color:rgba(62,92,118,.30)}
.card.dis{background:var(--paper2);border:1px solid var(--line);border-left:3px solid var(--qing);border-radius:8px;padding:12px 14px;margin-bottom:10px}
.dh{font-weight:600;font-size:13.5px;margin-bottom:6px;display:flex;align-items:center;gap:8px}
.tag{font-size:11px;padding:0 7px;border-radius:999px;border:1px solid var(--line)}
.tag.review{color:var(--zhu);border-color:rgba(168,58,44,.35);background:rgba(168,58,44,.08)}
.tag.ok{color:var(--qing);border-color:rgba(62,92,118,.30);background:rgba(62,92,118,.08)}
.drow{display:flex;gap:10px;font-size:13px;margin-top:3px}.dk{flex:none;width:34px;color:var(--ink3);font-size:12px;padding-top:1px}
.rates{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--ink3);margin:8px 0 10px}.rates b{font-family:var(--mono);color:var(--ink);font-size:13px}
.cross>div{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:6px 0}.ck{flex:none;width:74px;font-size:12px;color:var(--ink3)}
.chip{font-size:12px;padding:1px 9px;border-radius:999px;background:var(--paper2);border:1px solid var(--line)}
.chip.warn{color:var(--jin);border-color:rgba(176,132,48,.35);background:rgba(176,132,48,.10)}
.chip.bad{color:var(--zhu);border-color:rgba(168,58,44,.35);background:rgba(168,58,44,.10)}
.chip.design{color:var(--ink2);border-color:var(--line);background:rgba(28,28,28,.045)}
ul.rq{margin:0;padding-left:0;list-style:none}ul.rq li{background:var(--paper2);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:13px}
.poemtag{font-family:var(--serif);font-weight:600;margin-right:4px}
ul.rq code{font-family:var(--mono);font-size:12px;background:var(--paper);border:1px solid var(--line2);border-radius:4px;padding:0 4px}
.why{color:var(--ink3);font-size:12.5px;margin-top:4px}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:12px}
</style></head><body><div class="wrap">
<header>
  <div class="eyebrow">O2 · 意象抽取半自动化 · 复核工装页</div>
  <h1>输入诗 → 意象表 + 正负节点标注</h1>
  <div class="sub">格律先验分词 → 名词意象抽取 → 依存消歧 → 可画性门控（C5）。当前为<code>词典+规则替身</code>，可插拔接口：①分词 ${esc(O.meta.pluggable['①分词'])}　②意象 ${esc(O.meta.pluggable['②意象'])}　③消歧 ${esc(O.meta.pluggable['③消歧'])}。<br>${esc(O.meta.scope_note)}　生成 ${esc(O.meta.generated)}</div>
</header>
${O.poems && Object.keys(O.poems).map(poemHTML).join('')}
<section class="poem"><h2>复核队列</h2>${rq || '<div class="dim">无待复核项。</div>'}</section>
<footer>o2_imagery_harness.html · 由 src/o2/o2_build_harness.mjs 生成 · 数据源 o2_imagery.json / o2_gold.json</footer>
</div></body></html>`;

fs.writeFileSync(path.join(ROOT, 'dist', 'harness', 'o2_imagery_harness.html'), html);
console.log('written o2_imagery_harness.html  (' + (html.length / 1024).toFixed(0) + ' KB)');
