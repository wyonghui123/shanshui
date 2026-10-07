// o3_build_harness.mjs —— 由 o3_negatives.json 生成复核工装页 o3_negatives_harness.html
// 目的：把「人工标负节点」降级为「人工复核」——两条独立判据并排 + 代价行可审计 + gold 对照 + 复核队列。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const rd = f => JSON.parse(fs.readFileSync(datapath(f), 'utf8'));
const O3 = rd('o3_negatives.json');
const O2 = rd('o2_imagery.json');
const G = rd('o2_gold.json');

const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = v => (v == null ? '—' : (v * 100).toFixed(1) + '%');
const vCls = v => v === '负节点' ? 'neg' : v === '留白节点' ? 'void' : v === '动作节点' ? 'act' : v === '待复核' ? 'review' : 'pos';

function poemHTML(p) {
  const P = O3.poems[p], o2 = O2.poems[p], g = G.poems[p], v = O3.validation[p];
  const goldNeg = new Set(g.rows.filter(r => r.gold_class.startsWith('负节点')).map(r => r.canonical));
  const slots = P.slots;

  const text = o2.text.map((line, i) => `<div class="pline"><span class="lno">${i + 1}</span>${esc(line)}</div>`).join('');

  /* 主表 */
  const rows = P.rows.map(r => {
    const disagree = r.c1 !== r.c2 && r.verdict !== '留白节点';
    const isGold = goldNeg.has(r.canonical);
    const goldTag = isGold ? '<span class="tag goldneg">gold 负</span>' : '';
    return `<tr class="${disagree ? 'disagree' : ''}">
      <td class="em">${esc(r.canonical)}${goldTag}</td>
      <td class="num">${r.line}</td>
      <td class="num">${esc(r.channel)}</td>
      <td><span class="pill ${vCls(r.verdict)}">${esc(r.verdict)}</span>${r.neg_kind ? '<span class="dim k">' + esc(r.neg_kind) + '</span>' : ''}</td>
      <td class="num">${r.net.deg}<span class="dim"> (${r.net.deg_all})</span></td>
      <td class="num">${r.net.link}</td>
      <td class="num">${r.mass}</td>
      <td class="num ${r.ot.frac > 0.5 ? 'hot' : ''}">${pct(r.ot.frac)}</td>
      <td class="num dim">${pct(r.ot.sinkhorn_frac)}</td>
      <td class="c">${r.c1 ? '<b class="y">✓</b>' : '<span class="n">·</span>'}</td>
      <td class="c">${r.c2 ? '<b class="y">✓</b>' : '<span class="n">·</span>'}</td>
      <td class="c">${r.agree ? '<b class="y">一致</b>' : '<span class="n">不一致</span>'}</td>
    </tr>`;
  }).join('');

  /* 代价行：每个意象对 4 槽 + 弃置槽的代价，标出最小值；min>τ 即弃置 */
  const costRows = P.rows.map(r => {
    const C = r.ot.cost, tau = O3.meta.params.tau;
    const minC = Math.min(...C), minJ = C.indexOf(minC);
    const cells = C.map((c, j) => `<td class="num ${j === minJ ? 'minc' : ''}">${c.toFixed(2)}</td>`).join('');
    const discarded = minC > tau;
    return `<tr>
      <td class="em">${esc(r.canonical)}</td>${cells}
      <td class="num ${discarded ? 'hot' : ''}">${tau.toFixed(2)}</td>
      <td class="c">${discarded ? '<span class="tag neg">弃置</span>' : '<span class="tag ok">入槽</span>'}</td>
      <td class="dim">${esc(slots.map((s, j) => s.name + ' ' + C[j].toFixed(2)).join('　'))}</td>
    </tr>`;
  }).join('');

  const c = P.counts;
  const vrows = v.gold.length || v.got.length ? `<div class="rates">
    <span>精确 <b>${pct(v.precision)}</b></span><span>召回 <b>${pct(v.recall)}</b></span>
    <span>gold 负 <b>${esc(v.gold.join('、') || '—')}</b></span><span>自动负 <b>${esc(v.got.join('、') || '—')}</b></span>
    ${v.false_pos.length ? '<span class="bad">误报 ' + esc(v.false_pos.join('/')) + '</span>' : ''}
    ${v.false_neg.length ? '<span class="bad">漏报 ' + esc(v.false_neg.join('/')) + '</span>' : ''}
  </div>` : '<div class="dim">本诗无 gold 负节点标注。</div>';

  return `<section class="poem">
  <div class="ph"><h2>《${esc(P.title)}》${esc(o2.author || '')}</h2>
    <span class="form">${esc(o2.form.name)} · ${c.nodes} 节点（负 ${c.negatives} / 留白 ${P.blank.length} / 待复核 ${c.review}）</span>
    <span class="seg">Sinkhorn 行和误差 ${(P.sinkhorn_conv * 100).toFixed(2)}%</span></div>
  <div class="poembox">${text}</div>

  <h3>双判据总表</h3>
  <table><thead><tr>
    <th>意象</th><th>句</th><th>通道</th><th>裁定</th>
    <th title="视觉共现度（括号内为含跨通道边的原始度）">视觉度</th><th title="该意象映射到的画面元素数">画面连接</th><th title="按门控档 + 焦点加成的基础质量">质量</th>
    <th title="判据二：熵正则部分 OT 的未运输质量占比">未运输占比</th><th title="带容量 Sinkhorn 交叉核对">Sinkhorn</th>
    <th>判据一</th><th>判据二</th><th>一致</th>
  </tr></thead><tbody>${rows}</tbody></table>
  <div class="legend">
    <span class="lg"><i class="sw neg"></i>负节点</span><span class="lg"><i class="sw void"></i>留白节点</span>
    <span class="lg"><i class="sw act"></i>动作节点</span><span class="lg"><i class="sw pos"></i>正节点</span>
    <span class="lg dim">判据一：视觉共现度 ≤ ${O3.meta.params.degLow} 且 画面连接 = 0</span>
    <span class="lg dim">判据二：未运输占比 &gt; ${O3.meta.params.untransported_cut}</span>
  </div>

  <h3>判据二 · 代价行（可审计）</h3>
  <div class="note">每个意象对 4 个槽位与「弃置槽 τ」的代价 C = ${O3.meta.params.w.sem}·语义 + ${O3.meta.params.w.depth}·景深 + ${O3.meta.params.w.neg}·负节点 + ${O3.meta.params.w.channel}·跨通道。最小值落在弃置槽之上（即 min &gt; τ = ${O3.meta.params.tau}）→ 该意象宁可不画 → 判据二成立。</div>
  <table><thead><tr>
    <th>意象</th>${slots.map(s => `<th title="景深 ${s.depth} · 容量 ${s.cap}">${esc(s.name)}</th>`).join('')}<th title="弃置槽成本">弃置 τ</th><th>取向</th><th>代价明细</th>
  </tr></thead><tbody>${costRows}</tbody></table>

  <h3>验证 vs 人工 gold</h3>
  ${vrows}
</section>`;
}

const rq = O3.review_queue.length
  ? `<ul class="rq">` + O3.review_queue.map(r => `<li><span class="poemtag">《${esc(O3.poems[r.poem].title)}》</span><code>${esc(r.canonical)}</code>：${esc(r.kind)}<div class="why">${esc(r.detail)}</div></li>`).join('') + '</ul>'
  : '<div class="dim">无（两条判据完全一致）。</div>';

const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>O3 负节点双判据 · 复核工装页</title>
<style>
:root{--paper:#F6F3EC;--paper2:#fff;--ink:#1C1C1C;--ink2:#4A4640;--ink3:#8A8578;--line:rgba(28,28,28,.14);--line2:rgba(28,28,28,.07);--zhu:#A83A2C;--qing:#3E5C76;--jin:#B08430;--serif:"Songti SC","STSong",SimSun,"Noto Serif SC",Georgia,serif;--sans:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.75;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:52px 28px 88px}
header{border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:36px}
.eyebrow{font-size:12px;letter-spacing:.22em;color:var(--ink3);text-transform:uppercase;margin-bottom:14px}
h1{font-family:var(--serif);font-size:29px;font-weight:600;margin:0 0 8px;letter-spacing:.04em}
.sub{color:var(--ink3);font-size:13px}.sub code{font-family:var(--mono);font-size:12px;background:var(--paper2);border:1px solid var(--line2);border-radius:4px;padding:0 4px}
h2{font-family:var(--serif);font-size:22px;font-weight:600;margin:0;letter-spacing:.03em}
h3{font-family:var(--serif);font-size:16px;font-weight:600;margin:30px 0 10px;letter-spacing:.02em;color:var(--ink2)}
section.poem{border-top:1px solid var(--line);padding-top:26px;margin-top:40px}
.ph{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.form{font-size:12.5px;color:var(--ink3)}.seg{font-family:var(--mono);font-size:11.5px;color:var(--qing)}
.poembox{background:var(--paper2);border:1px solid var(--line);border-radius:10px;padding:16px 20px;box-shadow:0 1px 2px rgba(28,28,28,.04)}
.pline{font-family:var(--serif);font-size:22px;letter-spacing:.08em;line-height:1.85;white-space:nowrap}
.lno{font-family:var(--mono);font-size:11px;color:var(--ink3);margin-right:14px;vertical-align:middle}
.note{font-size:12.5px;color:var(--ink3);background:var(--paper2);border:1px solid var(--line2);border-left:3px solid var(--qing);border-radius:8px;padding:10px 14px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;background:var(--paper2);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line2);text-align:left;vertical-align:middle}
thead th{background:rgba(28,28,28,.03);font-weight:600;font-size:12px;color:var(--ink2);letter-spacing:.02em;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}.num{font-family:var(--mono);font-size:12px;white-space:nowrap}
.em{font-family:var(--serif);font-size:15px;font-weight:600}.dim{color:var(--ink3);font-size:12.5px}
.c{text-align:center}.k{margin-left:6px;font-size:11px}
.y{color:var(--qing)}.n{color:rgba(28,28,28,.22)}
.hot{color:var(--zhu);font-weight:600}.minc{background:rgba(62,92,118,.10);font-weight:600}
.bad{color:var(--zhu);font-weight:600}
tr.disagree{background:rgba(176,132,48,.06)}
.pill{display:inline-block;font-size:11.5px;padding:1px 9px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.pill.pos{color:var(--ink);background:rgba(28,28,28,.05)}
.pill.void{color:var(--ink3);background:rgba(138,133,120,.10)}
.pill.neg{color:var(--zhu);background:rgba(168,58,44,.10);border-color:rgba(168,58,44,.30)}
.pill.act{color:var(--qing);background:rgba(62,92,118,.10);border-color:rgba(62,92,118,.30)}
.pill.review{color:var(--jin);background:rgba(176,132,48,.12);border-color:rgba(176,132,48,.32)}
.tag{font-size:10.5px;padding:0 7px;border-radius:999px;border:1px solid var(--line);margin-left:6px;white-space:nowrap}
.tag.goldneg{color:var(--zhu);border-color:rgba(168,58,44,.35);background:rgba(168,58,44,.08)}
.tag.ok{color:var(--qing);border-color:rgba(62,92,118,.30);background:rgba(62,92,118,.08)}
.tag.neg{color:var(--zhu);border-color:rgba(168,58,44,.35);background:rgba(168,58,44,.10)}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:12px 2px 0;font-size:12px;color:var(--ink3)}
.lg{display:inline-flex;align-items:center;gap:6px}.sw{width:16px;height:0;border-bottom:3px solid transparent;display:inline-block}
.sw.pos{border-bottom-color:var(--ink)}.sw.void{border-bottom:2px dotted rgba(28,28,28,.28)}.sw.neg{border-bottom:2px dashed var(--zhu)}.sw.act{border-bottom:2px solid var(--qing)}
.rates{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--ink3);margin:8px 0 10px}.rates b{font-family:var(--mono);color:var(--ink);font-size:13px}
ul.rq{margin:0;padding-left:0;list-style:none}ul.rq li{background:var(--paper2);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:13px}
.poemtag{font-family:var(--serif);font-weight:600;margin-right:4px}
ul.rq code{font-family:var(--mono);font-size:12px;background:var(--paper);border:1px solid var(--line2);border-radius:4px;padding:0 4px}
.why{color:var(--ink3);font-size:12.5px;margin-top:4px}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);color:var(--ink3);font-size:12px}
</style></head><body><div class="wrap">
<header>
  <div class="eyebrow">O3 · 负节点双判据 · 复核工装页</div>
  <h1>把「留白」从手感变成判据</h1>
  <div class="sub">两条独立判据交叉验证，<b>一致才判负节点</b>：① 视觉共现网络低度　② 构图 OT 未运输质量。${esc(O3.meta.note)}<br>输入 <code>o2_imagery.json</code> / <code>o2_gold.json</code>　生成 ${esc(O3.meta.generated)}</div>
</header>
${Object.keys(O3.poems).map(poemHTML).join('')}
<section class="poem"><h2>复核队列（判据不一致项）</h2>${rq}</section>
<footer>o3_negatives_harness.html · 由 src/o3/o3_build_harness.mjs 生成 · 数据源 o3_negatives.json</footer>
</div></body></html>`;

fs.writeFileSync(path.join(ROOT, 'dist', 'harness', 'o3_negatives_harness.html'), html);
console.log('written o3_negatives_harness.html  (' + (html.length / 1024).toFixed(0) + ' KB)');
