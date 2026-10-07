// 由 o1_qset.json + o1_baseline.json + o1_probe.json 生成评估工装页 o1_eval_harness.html
// v1.2：适配 media 字段、defect_fixes、findings、discrimination、cam_trace、rho_definitions
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
const BASE = rd('o1_baseline.json');
const PROBE = rd('o1_probe.json');

const HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>O1 · 水墨动画忠实度评估工装</title>
<style>
  :root{
    --paper:#F6F3EC; --paper-2:#FFFFFF;
    --ink:#1C1C1C; --ink-2:#4A4640; --ink-3:#8A8578;
    --line:rgba(28,28,28,.14); --line-2:rgba(28,28,28,.07);
    --zhu:#A83A2C; --zhu-soft:rgba(168,58,44,.10);
    --qing:#3E5C76; --qing-soft:rgba(62,92,118,.10);
    --jin:#B08430; --jin-soft:rgba(176,132,48,.12);
    --lv:#4E6B4A; --lv-soft:rgba(78,107,74,.11);
    --zi:#6B5B95; --zi-soft:rgba(107,91,149,.11);
    --serif:"Songti SC","STSong","SimSun","Noto Serif SC",Georgia,serif;
    --sans:"PingFang SC","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
    --mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.75;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:52px 30px 100px}

  header{border-bottom:1px solid var(--line);padding-bottom:28px;margin-bottom:34px}
  .eyebrow{font-size:12px;letter-spacing:.22em;color:var(--ink-3);text-transform:uppercase;margin-bottom:16px}
  h1{font-family:var(--serif);font-size:31px;font-weight:600;margin:0 0 8px;letter-spacing:.04em}
  .sub{color:var(--ink-3);font-size:13px;margin-bottom:20px}
  .meta{display:flex;flex-wrap:wrap;gap:8px}
  .tag{font-size:12px;padding:3px 11px;border-radius:999px;border:1px solid var(--line);color:var(--ink-2);background:var(--paper-2)}
  .tag.zhu{color:var(--zhu);border-color:rgba(168,58,44,.32);background:var(--zhu-soft)}
  .tag.qing{color:var(--qing);border-color:rgba(62,92,118,.30);background:var(--qing-soft)}
  .tag.jin{color:var(--jin);border-color:rgba(176,132,48,.34);background:var(--jin-soft)}

  section{margin-bottom:52px}
  .sec-head{display:flex;align-items:baseline;gap:14px;margin-bottom:6px}
  .sec-no{font-family:var(--mono);font-size:12px;color:var(--zhu);border:1px solid rgba(168,58,44,.32);border-radius:4px;padding:1px 7px;flex:none}
  h2{font-family:var(--serif);font-size:20px;font-weight:600;margin:0;letter-spacing:.03em}
  .sec-note{color:var(--ink-3);font-size:12.5px;margin:0 0 20px}
  h3{font-size:13.5px;font-weight:600;margin:24px 0 10px;color:var(--ink)}

  .card{background:var(--paper-2);border:1px solid var(--line-2);border-radius:10px;padding:20px 22px;margin-bottom:14px}
  .card.tight{padding:15px 18px}
  .pos{background:var(--paper-2);border:1px solid var(--line-2);border-left:3px solid var(--jin);border-radius:8px;padding:16px 20px;margin-bottom:16px}
  .pos h4{font-family:var(--serif);font-size:15px;margin:0 0 4px}
  .pos .r{font-size:13px;font-weight:600;color:var(--ink);margin-bottom:9px}
  .pos .prow{display:grid;grid-template-columns:92px 1fr;gap:5px 14px;font-size:12.8px;color:var(--ink-2);margin:0}
  .pos .prow dt{color:var(--ink-3);font-size:12px}
  .pos .prow dd{margin:0}

  /* 记分卡 */
  .score{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px}
  .sc{background:var(--paper-2);border:1px solid var(--line-2);border-radius:10px;padding:16px 16px 14px}
  .sc .n{font-family:var(--serif);font-size:30px;font-weight:600;line-height:1.1;letter-spacing:.02em}
  .sc .l{font-size:12px;color:var(--ink-3);margin-top:4px}
  .sc.ok .n{color:var(--qing)} .sc.def .n{color:var(--zhu)} .sc.miss .n{color:var(--jin)}

  /* 表 */
  table{width:100%;border-collapse:collapse;font-size:12.8px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line-2);vertical-align:top}
  th{font-weight:600;font-size:11.5px;color:var(--ink-3);letter-spacing:.06em;border-bottom:1px solid var(--line);white-space:nowrap}
  tbody tr:last-child td{border-bottom:none}
  tbody tr.row-defect{background:rgba(168,58,44,.045)}
  tbody tr.row-miss{background:rgba(176,132,48,.055)}
  td.num,th.num{font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
  .ev{color:var(--ink-3);font-size:11.8px;line-height:1.6}
  .q{min-width:180px}

  .chip{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:4px;font-family:var(--mono);white-space:nowrap}
  .chip.EXIST{color:var(--qing);background:var(--qing-soft)}
  .chip.ATTR{color:var(--jin);background:var(--jin-soft)}
  .chip.SPATIAL{color:var(--lv);background:var(--lv-soft)}
  .chip.TEMPORAL{color:var(--zi);background:var(--zi-soft)}
  .chip.NEGATIVE{color:var(--zhu);background:var(--zhu-soft)}
  .chip.b-poem{color:var(--ink-2);background:rgba(28,28,28,.06)}
  .chip.b-design{color:var(--ink-3);background:rgba(28,28,28,.035)}
  .res{font-weight:600;font-size:11.5px;white-space:nowrap}
  .res.hit{color:var(--qing)} .res.def{color:var(--zhu)} .res.miss{color:var(--jin)}
  .conf{font-size:10.5px;color:var(--ink-3);font-family:var(--mono)}

  /* 条形 */
  .bars{display:flex;flex-direction:column;gap:9px}
  .bar-row{display:grid;grid-template-columns:110px 1fr 62px;align-items:center;gap:12px;font-size:12.5px}
  .bar-track{height:9px;background:rgba(28,28,28,.07);border-radius:99px;overflow:hidden}
  .bar-fill{height:100%;border-radius:99px;background:var(--qing)}
  .bar-fill.partial{background:var(--jin)}
  .bar-val{font-family:var(--mono);font-size:11.5px;color:var(--ink-2);text-align:right}

  /* 规则表 */
  .rules{margin:0;padding-left:20px}
  .rules li{margin-bottom:5px;font-size:12.8px;color:var(--ink-2)}

  /* 缺陷卡 */
  .def{background:var(--paper-2);border:1px solid var(--line-2);border-left:3px solid var(--zhu);border-radius:8px;padding:15px 18px;margin-bottom:11px}
  .def .h{display:flex;align-items:baseline;gap:10px;margin-bottom:5px;flex-wrap:wrap}
  .def .h b{font-size:13.5px}
  .def .id{font-family:var(--mono);font-size:11px;color:var(--zhu);border:1px solid rgba(168,58,44,.3);border-radius:4px;padding:0 6px}
  .def .where{font-size:11.5px;color:var(--ink-3);font-family:var(--mono)}
  .def p{margin:0 0 7px;font-size:12.8px;color:var(--ink-2)}
  .def .fix{font-size:12.5px;color:var(--lv);border-top:1px dashed var(--line);padding-top:7px}
  .def .fix b{color:var(--ink-2)}
  .def .ok{font-family:var(--mono);font-size:10.5px;color:var(--lv);border:1px solid rgba(78,107,74,.35);background:var(--lv-soft);border-radius:4px;padding:0 6px}

  /* 发现卡 */
  .fnd{background:var(--paper-2);border:1px solid var(--line-2);border-left:3px solid var(--jin);border-radius:8px;padding:15px 18px;margin-bottom:11px}
  .fnd .h{display:flex;align-items:baseline;gap:10px;margin-bottom:5px;flex-wrap:wrap}
  .fnd .h b{font-size:13.5px}
  .fnd .id{font-family:var(--mono);font-size:11px;color:var(--jin);border:1px solid rgba(176,132,48,.35);border-radius:4px;padding:0 6px}
  .fnd .where{font-size:11.5px;color:var(--ink-3);font-family:var(--mono)}
  .fnd p{margin:0 0 6px;font-size:12.8px;color:var(--ink-2)}
  .fnd .k{font-family:var(--mono);font-size:11px;color:var(--ink-3)}
  .fnd .act{font-size:12.5px;color:var(--qing);border-top:1px dashed var(--line);padding-top:7px}
  .fnd .act b{color:var(--ink-2)}

  /* 图册 */
  .gal{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .fr{background:var(--paper-2);border:1px solid var(--line-2);border-radius:9px;overflow:hidden}
  .fr a{display:block;line-height:0}
  .fr img{width:100%;display:block;transition:opacity .15s}
  .fr a:hover img{opacity:.86}
  .fr .cap{padding:9px 12px 11px;line-height:1.5}
  .fr .cap b{font-family:var(--mono);font-size:11.5px;display:block;color:var(--ink-2)}
  .fr .cap span{font-size:11.5px;color:var(--ink-3)}
  .fr .cap .tp{font-family:var(--mono);font-size:10.5px;color:var(--zhu)}

  /* 命令 */
  pre{background:#FBFAF6;border:1px solid var(--line-2);border-radius:8px;padding:13px 15px;overflow:auto;font-family:var(--mono);font-size:11.8px;line-height:1.7;color:var(--ink-2);margin:0 0 10px}

  .hl{background:rgba(176,132,48,.13);padding:1px 4px;border-radius:3px}
  footer{border-top:1px solid var(--line);padding-top:20px;color:var(--ink-3);font-size:12px}
  @media (max-width:860px){ .score{grid-template-columns:repeat(2,1fr)} .gal{grid-template-columns:repeat(2,1fr)} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">Poetics Pipeline · Optimization O1</div>
    <h1>水墨动画忠实度评估工装</h1>
    <div class="sub">问题由「诗」生成，答案由「画面」给出 —— 把「像不像」变成「可不可数」。注意：这是<b>忠实度护栏</b>，不是意境／美感的评分。</div>
    <div class="meta" id="meta"></div>
  </header>

  <section>
    <div class="sec-head"><span class="sec-no">§0</span><h2>基线总览</h2></div>
    <div class="pos" id="positioning"></div>
    <p class="sec-note" id="headline"></p>
    <div class="score" id="scores"></div>
    <div class="card tight">
      <div style="font-size:12.8px;color:var(--ink-2)" id="baseline-note"></div>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§1</span><h2>评估模板</h2></div>
    <p class="sec-note">模板 = 轴 + 依据 + 作答类型 + 媒体类型 + 打分口径 + 生成规则 + 判读协议 + 留白口径。实例化时才填入具体问题与期望答案。</p>
    <div class="card"><h3 style="margin-top:0">五个评估轴</h3><div id="axes"></div></div>
    <div class="card"><h3 style="margin-top:0">依据（basis）</h3><div id="basis"></div></div>
    <div class="card"><h3 style="margin-top:0">媒体类型（media，v1.2 新增）</h3><div id="media"></div></div>
    <div class="card"><h3 style="margin-top:0">打分口径</h3><div id="scoring"></div></div>
    <div class="card"><h3 style="margin-top:0">留白率口径（rho，v1.2 分列）</h3><div id="rho"></div></div>
    <div class="card"><h3 style="margin-top:0">问题生成规则</h3><ul class="rules" id="rules"></ul></div>
    <div class="card"><h3 style="margin-top:0">判读协议（v1.1 建立 · v1.2 补全）</h3><div id="protocol"></div></div>
    <div class="card"><h3 style="margin-top:0">已知混淆源</h3><div id="confounds"></div></div>
    <div class="card"><h3 style="margin-top:0">复跑命令</h3><pre id="cmds"></pre></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§2</span><h2>问题集与基线作答</h2></div>
    <p class="sec-note">判读帧（frame）与媒体类型（media）为逐题必填 —— 不绑定帧的构图题在镜头推近前后会给出两个答案（v1.3 已把《江雪》推近压平，但 12 秒内构图仍随帧变化）；过程性题（时序）单帧不可判。证据栏中的数值均来自像素级实测或 DOM 采样。</p>
    <div id="poems"></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§3</span><h2>按轴 / 按依据拆解</h2></div>
    <p class="sec-note">分母为权重和；「题面缺陷」与「无素材不可判」不计入分母。</p>
    <div class="card"><h3 style="margin-top:0">按轴</h3><div class="bars" id="axis-bars"></div></div>
    <div class="card"><h3 style="margin-top:0">按依据</h3><div class="bars" id="basis-bars"></div></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§4</span><h2>仪器缺陷修复清单（<span id="def-range">D1–D8</span>）</h2></div>
    <p class="sec-note">基线真正的产出不是「画面得了几分」，而是清单里的每一条 —— 尺子本身的问题。v1.2 修 D1–D7 并由 src/o1/o1_validate.mjs 加机器断言防复发；v1.3 的 D8 由探针自身的边界校验就地防复发。</p>
    <div id="defects"></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§5</span><h2>资产口径发现（<span id="fnd-range">F1–F5</span>）</h2></div>
    <p class="sec-note">修尺子的副产物：探针把「标签／设计序列」与「画面键值」对不上的地方翻了出来。F1–F4 属资产口径问题（不改画面即不影响观感，但会被后续版本继承）；F5 则是探针把「缩放过大破坏意境」量出来之后据以改画面的裁定记录。</p>
    <div id="findings"></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§6</span><h2>区分度灵敏度分析</h2></div>
    <p class="sec-note">D5 的诉求是「题目要能测出改进」。本轮画面已达标（全中），故不能靠分数证明区分度，改做灵敏度分析：逐题给出「最近的一个错误选项」与到该选项的余量，余量越小说明题目越敏感。</p>
    <div class="card" style="padding:0;overflow:hidden" id="discrimination"></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§7</span><h2>客观实测</h2></div>
    <p class="sec-note">属性类题若肉眼处于阈值附近，改由探针给硬数据；相机轨迹由 DOM 采样给出。纸色 #F6F3EC（lum≈243）。</p>
    <div class="card"><h3 style="margin-top:0">关键测量</h3><div id="probe-keys"></div></div>
    <div class="card"><h3 style="margin-top:0">留白率直方图（按亮度分档）</h3><div id="probe-blank"></div></div>
    <div class="card"><h3 style="margin-top:0">相机轨迹（src/o1/o1_probe_cam.mjs 采样 scale）</h3><div id="probe-cam"></div></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§8</span><h2>关键帧图册</h2></div>
    <p class="sec-note">14 帧。基线一律关闭「画中物标注」；负节点题以「去题诗」帧复核。点图可看原图。</p>
    <div class="gal" id="gallery"></div>
  </section>

  <section>
    <div class="sec-head"><span class="sec-no">§9</span><h2>结论与下一步</h2></div>
    <div class="card" id="next"></div>
  </section>

  <footer>O1 评估闭环 · 工装页由 src/o1/o1_build_harness.mjs 从 o1_qset.json / o1_baseline.json / o1_probe.json 生成 · 可复跑</footer>
</div>

<script>
const QSET = ${JSON.stringify(QSET)};
const BASE = ${JSON.stringify(BASE)};
const PROBE = ${JSON.stringify(PROBE)};

const AXIS_ORDER = ['EXIST','ATTR','SPATIAL','TEMPORAL','NEGATIVE'];
const $ = id => document.getElementById(id);
const pct = v => (v * 100).toFixed(1) + '%';
const esc = s => String(s == null ? '' : s);

/* header meta */
$('meta').innerHTML = [
  ['tag qing', '问题集 v' + QSET.meta.version],
  ['tag', '基线 ' + BASE.meta.run_id],
  ['tag', BASE.meta.date],
  ['tag jin', BASE.meta.judge],
  ['tag', '判读帧 ' + QSET.poems.reduce((a,p)=>a+p.frames.length,0) + ' 帧']
].map(([c,t]) => '<span class="'+c+'">'+t+'</span>').join('');

/* positioning —— 护栏而非目标，防误用 */
const POS = QSET.meta.positioning;
$('positioning').innerHTML = POS ? (
  '<h4>O1 的定位：护栏，不是目标</h4>'
  + '<div class="r">' + esc(POS.role) + '</div>'
  + '<dl class="prow">'
  + '<dt>量什么</dt><dd>' + esc(POS.measures) + '</dd>'
  + '<dt>不量什么</dt><dd>' + esc(POS.not_measures) + '</dd>'
  + '<dt>怎么用</dt><dd>' + esc(POS.usage) + '</dd>'
  + '<dt>相关</dt><dd>' + esc(POS.related) + '</dd>'
  + '</dl>'
) : '';

$('headline').innerHTML = BASE.meta.totals.headline;

/* scores */
const T = BASE.meta.totals;
$('scores').innerHTML = [
  ['', T.questions, '总题数'],
  ['ok', T.hit, '命中'],
  ['miss', T.miss, '未命中（画面错）'],
  ['def', T.defect, '题面缺陷（不计分）'],
  ['ok', pct(T.rate_excl_defect), '有效题加权通过率']
].map(([c,n,l]) => '<div class="sc '+c+'"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>').join('');

$('baseline-note').innerHTML =
  '加权通过率 <span class="hl">' + pct(T.rate_excl_defect) + '</span>（' + T.hit_weight + ' / ' + T.weight_sum + '）'
  + '　·　题面缺陷 <b>' + T.defect + '</b>　·　无素材不可判 <b>' + T.unreadable + '</b>'
  + '　·　较 v1.1：' + T.prev_questions + ' 题 / 缺陷 ' + T.prev_defect + ' → ' + T.questions + ' 题 / 缺陷 ' + T.defect
  + '<br>两处此前已知的问题 —— 《江雪》水纹观感、《早发白帝城》远山与两岸的空间关系 —— 在基线下均已达标（BD-S4 / BD-S5 即这两处的检验点）。'
  + '<br><b>口径提醒</b>：以上通过率是「忠实度」口径（护栏），不等于意境／美感评分 —— 见上方定位说明。';

/* axes */
$('axes').innerHTML = AXIS_ORDER.map(a =>
  '<div style="display:flex;gap:11px;padding:7px 0;border-bottom:1px solid var(--line-2)">'
  + '<span class="chip '+a+'" style="flex:none;height:19px">'+a+'</span>'
  + '<span style="font-size:12.8px;color:var(--ink-2)">'+QSET.meta.axes[a]+'</span></div>').join('');

$('basis').innerHTML = Object.entries(QSET.meta.basis).map(([k,v]) =>
  '<div style="display:flex;gap:11px;padding:6px 0"><span class="chip b-'+k+'" style="flex:none;height:19px">'+k+'</span>'
  + '<span style="font-size:12.8px;color:var(--ink-2)">'+v+'</span></div>').join('');

$('media').innerHTML = Object.entries(QSET.meta.media_types || {}).map(([k,v]) =>
  '<div style="display:flex;gap:11px;padding:6px 0"><span class="chip b-poem" style="flex:none;height:19px">'+k+'</span>'
  + '<span style="font-size:12.8px;color:var(--ink-2)">'+v+'</span></div>').join('');

$('scoring').innerHTML = Object.entries(QSET.meta.scoring).map(([k,v]) =>
  '<div style="font-size:12.8px;color:var(--ink-2);padding:4px 0"><span style="font-family:var(--mono);font-size:11.5px;color:var(--ink-3)">'+k+'</span>　'+v+'</div>').join('');

const RHO = QSET.meta.rho_definitions || {};
$('rho').innerHTML = Object.entries(RHO).map(([k,v]) =>
  '<div style="font-size:12.8px;color:var(--ink-2);padding:4px 0"><span style="font-family:var(--mono);font-size:11.5px;color:var(--lv)">'+k+'</span>　'+v+'</div>').join('');

$('rules').innerHTML = QSET.meta.generation_rules.map(r => '<li>'+r+'</li>').join('');

$('protocol').innerHTML = Object.entries(QSET.meta.protocol).map(([k,v]) =>
  '<div style="font-size:12.8px;color:var(--ink-2);padding:4px 0"><span style="font-family:var(--mono);font-size:11.5px;color:var(--qing)">'+k+'</span>　'+v+'</div>').join('');

$('confounds').innerHTML = QSET.meta.known_confounds.map(c => '<div style="font-size:12.8px;color:var(--ink-2);padding:4px 0">· '+c+'</div>').join('');

$('cmds').textContent = [
  '# 1. 按节拍抽关键帧（关自动播放 / 关标注 / 可选去题诗）',
  'node src/o1/o1_render.mjs',
  '',
  '# 2. 像素级探针：留白率、墨色分布、极淡笔画对比度',
  'node src/o1/o1_probe.mjs',
  'node src/o1/o1_probe2.mjs',
  '',
  '# 3. 相机轨迹探针（连续量，供 media=probe 的题判定）',
  'node src/o1/o1_probe_cam.mjs',
  '',
  '# 4. 结构校验（frame 绑定 / 负节点去诗帧 / 选项覆盖 / media）',
  'node src/o1/o1_validate.mjs',
  '',
  '# 5. 缩略图 + 重生成本工装页',
  'node src/o1/o1_thumbs.mjs',
  'node src/o1/o1_build_harness.mjs'
].join('\\n');

/* poems tables */
$('poems').innerHTML = QSET.poems.map(p => {
  const res = BASE.results.filter(r => r.poem === p.id);
  const roll = BASE.rollup.by_poem[p.id];
  const qmap = {};
  p.questions.forEach(q => qmap[q.id] = q);
  const rows = res.map(r => {
    const q = qmap[r.id] || {};
    const isDef = r.verdict === 'defect' || r.s === null;
    const isMiss = r.s === 0;
    const resTxt = isDef ? '题面缺陷' : (isMiss ? '未命中' : '命中');
    const resCls = isDef ? 'def' : (isMiss ? 'miss' : 'hit');
    const flags = [];
    if (q.probe_assisted) flags.push('探针辅助');
    if (r.measured) flags.push('实测 ' + r.measured.value + (r.measured.unit || ''));
    const conf = r.conf + (flags.length ? (' · ' + flags.join(' · ')) : '');
    return '<tr class="'+(isDef?'row-defect':(isMiss?'row-miss':''))+'">'
      + '<td class="num">'+r.id+'</td>'
      + '<td><span class="chip '+r.axis+'">'+r.axis+'</span></td>'
      + '<td><span class="chip b-'+r.basis+'">'+r.basis+'</span></td>'
      + '<td class="num" style="font-size:11px">'+r.frame+'</td>'
      + '<td class="num" style="font-size:11px">'+(r.media||'single')+'</td>'
      + '<td class="q">'+(q.q||'')+'</td>'
      + '<td>'+r.expect+'</td>'
      + '<td>'+r.answer+'</td>'
      + '<td class="num">'+r.w.toFixed(1)+'</td>'
      + '<td><span class="res '+resCls+'">'+resTxt+'</span><br><span class="conf">'+conf+'</span></td>'
      + '<td class="ev">'+r.evidence+'</td>'
      + '</tr>';
  }).join('');
  return '<div class="card" style="padding:0;overflow:hidden">'
    + '<div style="padding:16px 22px 12px;border-bottom:1px solid var(--line-2)">'
    + '<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">'
    + '<h3 style="margin:0;font-family:var(--serif);font-size:18px">'+p.title+'</h3>'
    + '<span style="font-size:12px;color:var(--ink-3)">'+p.author+'　'+p.form+'　'+p.total_s+'s</span></div>'
    + '<div style="margin-top:8px;font-size:12.5px;color:var(--ink-2)">'
    + p.segments.map(s => '<span style="margin-right:16px"><b style="font-family:var(--serif)">'+s.name+'</b> '+s.line+' <span class="conf">'+s.t+'–'+(s.t+s.dur)+'s</span></span>').join('')
    + '</div>'
    + '<div style="margin-top:9px;font-size:12.5px">加权通过率 <b style="color:var(--qing)">'+pct(roll.rate_excl_defect)+'</b>'
    + '　·　'+roll.questions+' 题　命中 '+roll.hit+(roll.defect?('　题面缺陷 '+roll.defect):'')+'</div>'
    + '</div>'
    + '<div style="overflow-x:auto"><table><thead><tr>'
    + '<th>ID</th><th>轴</th><th>依据</th><th>判读帧</th><th>媒体</th><th>问题</th><th>期望</th><th>基线作答</th><th class="num">w</th><th>结果</th><th>证据 / 实测</th>'
    + '</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
}).join('');

/* bars */
function bars(el, entries){
  el.innerHTML = entries.map(([label, d]) => {
    const r = d.rate;
    return '<div class="bar-row"><div>'+label+'</div>'
      + '<div class="bar-track"><div class="bar-fill'+(r<1?' partial':'')+'" style="width:'+(r*100).toFixed(1)+'%"></div></div>'
      + '<div class="bar-val">'+pct(r)+'</div></div>';
  }).join('');
}
bars($('axis-bars'), AXIS_ORDER.filter(a => BASE.rollup.by_axis[a]).map(a => [a + '　<span class="conf">w=' + BASE.rollup.by_axis[a].weight_sum.toFixed(1) + '</span>', BASE.rollup.by_axis[a]]));
bars($('basis-bars'), Object.entries(BASE.rollup.by_basis).map(([k,v]) => [k + '　<span class="conf">w=' + v.weight_sum.toFixed(1) + '</span>', v]));

/* defect fixes */
$('defects').innerHTML = (BASE.defect_fixes || []).map(d =>
  '<div class="def"><div class="h"><span class="id">'+d.id+'</span><b>'+esc(d.title)+'</b>'
  + '<span class="ok">'+(d.status === 'verified' ? '已核验' : '已修复')+'</span></div>'
  + '<div class="fix"><b>'+esc(d.ver || 'v1.2')+'</b>　'+esc(d.verdict)+'</div></div>').join('');
$('def-range').textContent = 'D1–D' + (BASE.defect_fixes || []).length;

/* findings */
$('findings').innerHTML = (BASE.findings || []).map(f =>
  '<div class="fnd"><div class="h"><span class="id">'+f.id+'</span><b>'+esc(f.title)+'</b>'
  + '<span class="where">'+esc(f.where)+'</span></div>'
  + '<p>'+esc(f.detail)+'</p>'
  + '<p class="k">影响：'+esc(f.impact)+'</p>'
  + '<div class="act"><b>建议</b>　'+esc(f.action)+'</div></div>').join('');
$('fnd-range').textContent = 'F1–F' + (BASE.findings || []).length;

/* discrimination */
const DIS = BASE.discrimination || { items: [] };
$('discrimination').innerHTML =
  '<div style="padding:14px 22px 10px;border-bottom:1px solid var(--line-2);font-size:12.5px;color:var(--ink-2)">'+esc(DIS.note)+'</div>'
  + '<div style="overflow-x:auto"><table><thead><tr>'
  + '<th>ID</th><th>期望档位</th><th>最近的错误选项</th><th>余量</th><th>敏感度</th>'
  + '</tr></thead><tbody>'
  + DIS.items.map(it =>
      '<tr><td class="num">'+it.id+'</td><td>'+esc(it.expected)+'</td>'
      + '<td style="color:var(--ink-3)">'+esc(it.nearest_wrong)+'</td>'
      + '<td class="num">'+esc(it.margin)+'</td>'
      + '<td><span class="res '+(/high/.test(it.sens)?'hit':'miss')+'">'+esc(it.sens)+'</span></td></tr>').join('')
  + '</tbody></table></div>';

/* probe */
$('probe-keys').innerHTML = BASE.probe.key_measurements.map(m =>
  '<div style="padding:7px 0;border-bottom:1px solid var(--line-2)">'
  + '<div style="font-size:12.8px;color:var(--ink);font-weight:600">'+esc(m.item)+'</div>'
  + '<div style="font-size:12.5px;color:var(--ink-2)"><span style="font-family:var(--mono)">'+esc(m.value)+'</span></div>'
  + '<div style="font-size:12px;color:var(--lv)">'+esc(m.verdict)+'</div></div>').join('');

const bk = Object.entries(BASE.probe.blank_rate);
$('probe-blank').innerHTML = bk.map(([name, d]) =>
  '<div style="padding:8px 0;border-bottom:1px solid var(--line-2)">'
  + '<div style="font-size:12.5px;font-family:var(--mono);color:var(--ink-2);margin-bottom:4px">'+name+'</div>'
  + '<div style="display:flex;height:12px;border-radius:3px;overflow:hidden">'
  + '<div style="width:'+(d['留白≥240']*100)+'%;background:#EFECE3"></div>'
  + '<div style="width:'+(d['极淡225-240']*100)+'%;background:#D8D3C6"></div>'
  + '<div style="width:'+(d['中灰150-225']*100)+'%;background:#A8A296"></div>'
  + '<div style="width:'+(d['浓墨<150']*100)+'%;background:#3A362F"></div>'
  + '</div>'
  + '<div style="font-size:11px;color:var(--ink-3);font-family:var(--mono);margin-top:4px">'
  + '留白 '+(d['留白≥240']*100).toFixed(1)+'%　极淡 '+(d['极淡225-240']*100).toFixed(2)+'%　中灰 '+(d['中灰150-225']*100).toFixed(1)+'%　浓墨 '+(d['浓墨<150']*100).toFixed(2)+'%</div></div>').join('');

/* camera trace */
const CAM = (BASE.probe.cam_trace) || {};
const CAM_LABEL = { jx: '《江雪》', bd: '《早发白帝城》' };
$('probe-cam').innerHTML = Object.entries(CAM).filter(([k]) => k !== 'script').map(([k, c]) => {
  const bits = [];
  bits.push('s ' + c.s_start + ' → ' + c.s_end);
  if (c.s_min != null) bits.push('s_min ' + c.s_min);
  if (c.s_max != null) bits.push('s_max ' + c.s_max);
  if (c.vmax) bits.push('vmax ' + c.vmax.v + '/s @ t=' + c.vmax.t);
  if (c.tail_v != null) bits.push('末段 v ' + c.tail_v + '/s');
  if (c.dip) bits.push('回退 ' + c.dip.from + '→' + c.dip.to + ' @ t=' + c.dip.t);
  return '<div style="padding:9px 0;border-bottom:1px solid var(--line-2)">'
    + '<div style="font-size:12.8px;color:var(--ink);font-weight:600">'+(CAM_LABEL[k]||k)+'</div>'
    + '<div style="font-size:12.5px;color:var(--ink-2)">'+esc(c.shape)+'</div>'
    + '<div style="font-size:11.5px;color:var(--ink-3);font-family:var(--mono);margin-top:3px">'+bits.join('　·　')+'</div></div>';
}).join('') + (CAM.script ? '<div class="conf" style="margin-top:8px">数据源：'+CAM.script+'</div>' : '');

/* gallery */
const allFrames = [];
QSET.poems.forEach(p => p.frames.forEach(f => allFrames.push({ poem: p.title, ...f })));
$('gallery').innerHTML = allFrames.map(f =>
  '<div class="fr"><a href="../figures/'+f.name+'.png" target="_blank">'
  + '<img src="../figures/thumbs/'+f.name+'.jpg" alt="'+f.name+'" loading="lazy"></a>'
  + '<div class="cap"><b>'+f.name+'</b><span>'+f.label+'</span> <span class="tp">t='+f.t+'s · '+f.poem+'</span></div></div>').join('');

/* next */
$('next').innerHTML = '<div style="font-size:13px;color:var(--ink-2);margin-bottom:10px">'
  + 'O1 的目标是「先造尺子」。v1.2 修完 D1–D7、v1.3 修完 D8 并压平《江雪》推近后重跑基线，下一步按依赖关系推进：</div>'
  + BASE.next.map(n => '<div style="display:flex;gap:12px;padding:7px 0;border-bottom:1px solid var(--line-2)">'
    + '<span class="chip b-poem" style="flex:none;height:19px">'+n.id+'</span>'
    + '<div><div style="font-size:12.8px;color:var(--ink)">'+n.task+'</div>'
    + '<div style="font-size:12px;color:var(--ink-3)">'+n.why+'</div></div></div>').join('');
</script>
</body>
</html>
`;

fs.writeFileSync(path.join(ROOT, 'dist', 'harness', 'o1_eval_harness.html'), HTML);
console.log('written o1_eval_harness.html  (' + (HTML.length / 1024).toFixed(0) + ' KB)');
