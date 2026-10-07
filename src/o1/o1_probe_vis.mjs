// o1_probe_vis.mjs —— 元素可见性探针（O1.2）
// EXIST / NEGATIVE 两类题（共 18 道）问的是「某意象在判读帧上是否被画出来」。
// 目视之外还可以客观核对：把动画定位到判读帧时刻，读该元素的有效不透明度与包围盒。
// 输出 o1_vis.json：帧时刻 → { 元素id: { effOpacity, bbox, childCount } }
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
  return require(pick.p);
}
const { chromium } = loadPlaywright();

const ANIM = path.join(ROOT, 'dist', 'animation', 'ink_animations.html');
const QSET = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'source', 'o1_qset.json'), 'utf8'));

/* 判读帧只按「时刻」采样：去诗帧与同刻普通帧的元素可见性一致（题诗是独立图层） */
const TIMES = {};
for (const p of QSET.poems) {
  TIMES[p.id] = { T: p.total_s, ts: [...new Set(p.frames.map(f => f.t))].sort((a, b) => a - b) };
}

/* 关注元素（与 o1_source_facts.mjs 的 WATCH 保持一致） */
const WATCH = {
  jx: ['jx-far', 'jx-waterline', 'jx-water', 'jx-path', 'jx-reed', 'jx-boat', 'jx-line', 'jx-snow', 'jx-anno', 'jx-poemink', 'jx-seal'],
  bd: ['bd-cloud', 'bd-city', 'bd-far', 'bd-cliff', 'bd-cun', 'bd-mist', 'bd-water', 'bd-trail', 'bd-boat', 'bd-anno', 'bd-poemink', 'bd-seal'],
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1200, height: 1400 }, deviceScaleFactor: 1 });
const out = {};

for (const [key, cfg] of Object.entries(TIMES)) {
  const page = await ctx.newPage();
  await page.addInitScript(() => { try { delete window.IntersectionObserver; } catch (e) {} });
  await page.goto(pathToFileURL(ANIM).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);

  /* 关标注层：与基线判读条件一致（标注会直接写出意象名） */
  try { await page.click(`#${key}-anno-btn`); } catch (e) {}

  const track = page.locator(`.track[data-track="${key}"]`);
  await track.scrollIntoViewIfNeeded();
  const bb = await track.boundingBox();

  const frames = {};
  for (const t of cfg.ts) {
    const frac = Math.min(1, Math.max(0, t / cfg.T));
    const x = bb.x + Math.min(bb.width - 1, Math.max(1, frac * bb.width));
    await page.mouse.move(x, bb.y + bb.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(60);

    frames[t] = await page.evaluate((ids) => {
      const res = {};
      for (const id of ids) {
        const el = document.getElementById(id);
        if (!el) { res[id] = { present: false }; continue; }
        /* 有效不透明度 = 自身与各级祖先 computed opacity 之积 */
        let op = 1, node = el;
        while (node && node.nodeType === 1) {
          const cs = window.getComputedStyle(node);
          op *= parseFloat(cs.opacity === '' ? '1' : cs.opacity);
          node = node.parentElement;
        }
        let box = null;
        try { const b = el.getBBox(); box = { w: +b.width.toFixed(1), h: +b.height.toFixed(1) }; } catch (e) {}
        /* 屏幕归一化矩形：getBBox 给的是「变换前」的局部坐标，SPATIAL 题问的是画面上
           的位置，必须用 getBoundingClientRect（已含相机 transform）再按 SVG 视口归一 */
        let rect = null;
        try {
          const r = el.getBoundingClientRect();
          const sr = el.ownerSVGElement.getBoundingClientRect();
          rect = {
            cx: +(((r.left + r.width / 2) - sr.left) / sr.width).toFixed(4),
            cy: +(((r.top + r.height / 2) - sr.top) / sr.height).toFixed(4),
            x: +((r.left - sr.left) / sr.width).toFixed(4),
            y: +((r.top - sr.top) / sr.height).toFixed(4),
            w: +(r.width / sr.width).toFixed(4),
            h: +(r.height / sr.height).toFixed(4),
          };
        } catch (e) {}
        /* 逐段拉出的笔画（钓丝、船迹）不透明度恒为 1，靠 stroke-dashoffset 控制可见比例 —— 必须一并采样，
           否则会把「还没开始画」误判成「已画」 */
        const dashes = [];
        const pushDash = (node) => {
          if (!node.hasAttribute || !node.hasAttribute('stroke-dashoffset')) return;
          const arr = (node.getAttribute('stroke-dasharray') || '').trim().split(/[\s,]+/).map(Number);
          const off = parseFloat(node.getAttribute('stroke-dashoffset'));
          const total = arr[0] || 100;
          dashes.push({ off, total, visibleFrac: +(1 - Math.min(1, Math.max(0, off / total))).toFixed(4) });
        };
        pushDash(el);
        el.querySelectorAll('[stroke-dashoffset]').forEach(pushDash);
        const minVisible = dashes.length ? Math.min(...dashes.map(d => d.visibleFrac)) : null;
        res[id] = {
          present: true,
          effOpacity: +op.toFixed(4),
          attrOpacity: el.getAttribute('opacity'),
          bbox: box,
          rect,
          childCount: el.children.length,
          dashes,
          /* 综合可见性：不透明度 × 描边可见比例（无 dash 动画时即不透明度） */
          vis: +(op * (minVisible == null ? 1 : minVisible)).toFixed(4),
        };
      }
      return res;
    }, WATCH[key]);
  }
  await page.close();
  out[key] = { T: cfg.T, frames };

  console.log(`\n=== ${key}（判读帧 ${cfg.ts.join(', ')}）===`);
  for (const t of cfg.ts) {
    const line = WATCH[key].map(id => {
      const v = frames[t][id];
      if (!v.present) return null;
      const drawn = v.vis > 0.05 && v.bbox && v.bbox.w * v.bbox.h > 0;
      return id.replace(/^(jx|bd)-/, '') + '=' + (drawn ? v.vis : '·');
    }).filter(Boolean);
    console.log(`  t=${String(t).padEnd(5)} 可见: ` + line.join('  '));
  }
}

await browser.close();
fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_vis.json'), JSON.stringify(out, null, 2));
console.log('\n-> o1_vis.json');
