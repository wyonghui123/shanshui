// o1_probe_cam.mjs —— 相机轨迹探针（v1.2 新增，对应缺陷 D7）
// 时序题里「速度曲线」「是否持续前推」是连续量，单帧/成对帧都判不了。
// 本脚本不目视，直接从 DOM 采样 #jx-cam / #bd-cam 的 transform scale，
// 得到 s(t) 与速度 v(t) = ds/dt，作为 JX-T5 / BD-T4 / BD-T5 的客观判据。
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };

const require = createRequire(import.meta.url);

function loadPlaywright() {
  const pwCache = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  const candidates = [];
  try { candidates.push({ p: 'playwright', v: require('playwright/package.json').version, rev: null }); } catch (e) {}
  const npxRoot = path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx');
  if (fs.existsSync(npxRoot)) {
    for (const d of fs.readdirSync(npxRoot)) {
      const p = path.join(npxRoot, d, 'node_modules', 'playwright');
      const bj = path.join(npxRoot, d, 'node_modules', 'playwright-core', 'browsers.json');
      if (!fs.existsSync(path.join(p, 'package.json')) || !fs.existsSync(bj)) continue;
      const v = JSON.parse(fs.readFileSync(path.join(p, 'package.json'), 'utf8')).version;
      const b = JSON.parse(fs.readFileSync(bj, 'utf8')).browsers.find(x => x.name === 'chromium');
      candidates.push({ p, v, rev: b && b.revision });
    }
  }
  const usable = candidates.filter(c => c.rev && fs.existsSync(path.join(pwCache, `chromium-${c.rev}`)));
  const pick = (usable.length ? usable : candidates).sort((a, b) => b.v.localeCompare(a.v, undefined, { numeric: true }))[0];
  if (!pick) throw new Error('playwright not found');
  console.log(`using playwright ${pick.v} (chromium rev ${pick.rev || 'n/a'})`);
  return require(pick.p);
}

const { chromium } = loadPlaywright();
const ANIM = path.join(ROOT, 'dist', 'animation', 'ink_animations.html');

const TARGETS = [
  { key: 'jx', T: 19.578, step: 0.5 },
  { key: 'bd', T: 13.631, step: 0.5 }
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1200, height: 1400 }, deviceScaleFactor: 1 });
const out = {};

for (const target of TARGETS) {
  const page = await ctx.newPage();
  await page.addInitScript(() => { try { delete window.IntersectionObserver; } catch (e) {} });
  await page.goto(pathToFileURL(ANIM).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);

  const track = page.locator(`.track[data-track="${target.key}"]`);
  await track.scrollIntoViewIfNeeded();
  const bb = await track.boundingBox();

  const samples = [];
  for (let t = 0; t <= target.T + 1e-6; t = +(t + target.step).toFixed(3)) {
    const frac = Math.min(1, Math.max(0, t / target.T));
    /* 落点内缩 1px：点在最右/最左边缘会落到元素外，事件不触发，读到上一帧的陈旧值 */
    const x = bb.x + Math.min(bb.width - 1, Math.max(1, frac * bb.width));
    await page.mouse.move(x, bb.y + bb.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(60);
    const st = await page.evaluate((k) => {
      const g = document.getElementById(k + '-cam');
      const tr = g.getAttribute('transform') || '';
      const ms = /scale\(([-\d.]+)\)/.exec(tr);
      const mt = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(tr);
      return { s: ms ? parseFloat(ms[1]) : null, tx: mt ? parseFloat(mt[1]) : null, ty: mt ? parseFloat(mt[2]) : null };
    }, target.key);
    samples.push({ t, s: st.s, tx: st.tx, ty: st.ty });
  }
  await page.close();

  /* 速度 v = ds/dt（中心差分），并给出「定格」判定：连续 1s 内 |Δs| < 1e-4 且位移 < 0.5px */
  const rows = samples.map((p, i) => {
    const a = samples[Math.max(0, i - 1)], b = samples[Math.min(samples.length - 1, i + 1)];
    const dt = b.t - a.t || 1;
    const v = (b.s - a.s) / dt;
    const dpos = Math.hypot(b.tx - a.tx, b.ty - a.ty) / dt;
    return { t: p.t, s: p.s, v: +v.toFixed(5), dpos: +dpos.toFixed(3) };
  });

  /* 定格段：从末尾往前找连续 v≈0 且 dpos≈0 的区间 */
  let freezeStart = null;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (Math.abs(rows[i].v) < 1e-4 && rows[i].dpos < 0.5) freezeStart = rows[i].t;
    else break;
  }
  /* 边界修正：定格须连续 ≥1s（见上方口径）。仅末尾单个采样满足 v≈0（时长 0）是边界假阳性，
     不构成定格 —— 否则「末段仍在极缓移动」的曲线会被误判为「末尾定格」。 */
  if (freezeStart !== null && rows[rows.length - 1].t - freezeStart < 1 - 1e-9) freezeStart = null;
  /* 最大速度点 */
  const vmax = rows.reduce((m, r) => (r.v > m.v ? r : m), rows[0]);
  /* 单调性：相邻速度差为正的比例 */
  let inc = 0, dec = 0;
  for (let i = 1; i < rows.length; i++) { if (rows[i].v > rows[i - 1].v + 1e-5) inc++; else if (rows[i].v < rows[i - 1].v - 1e-5) dec++; }

  out[target.key] = {
    T: target.T, step: target.step,
    s_start: rows[0].s, s_end: rows[rows.length - 1].s,
    s_max: Math.max(...rows.map(r => r.s)), s_min: Math.min(...rows.map(r => r.s)),
    vmax: { t: vmax.t, v: vmax.v },
    freeze_from: freezeStart,
    monotonic_inc_steps: inc, monotonic_dec_steps: dec,
    curve: rows.map(r => ({ t: r.t, s: r.s, v: r.v }))
  };
  console.log(`\n[${target.key}] s: ${rows[0].s} → ${rows[rows.length - 1].s}  (max ${out[target.key].s_max})`);
  console.log('  t      s        v');
  for (const r of rows) console.log('  ' + String(r.t).padEnd(6) + String(r.s.toFixed(4)).padEnd(9) + r.v.toFixed(5));
  console.log('  最大速度点 t=' + vmax.t + ' v=' + vmax.v.toFixed(5));
  console.log('  末尾定格自 t=' + (freezeStart === null ? '（无定格）' : freezeStart + 's'));
  console.log('  速度递增步数 ' + inc + ' / 递减步数 ' + dec);
}

await browser.close();
fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_cam_trace.json'), JSON.stringify(out, null, 2));
console.log('\nwritten o1_cam_trace.json');
