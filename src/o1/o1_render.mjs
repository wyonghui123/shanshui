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

  // 优先选「所需 chromium 版本已下载」的那一个
  const usable = candidates.filter(c => c.rev && fs.existsSync(path.join(pwCache, `chromium-${c.rev}`)));
  const pick = (usable.length ? usable : candidates).sort((a, b) => b.v.localeCompare(a.v, undefined, { numeric: true }))[0];
  if (!pick) throw new Error('playwright not found');
  console.log(`using playwright ${pick.v} (chromium rev ${pick.rev || 'n/a'}) from ${pick.p}`);
  return require(pick.p);
}

const { chromium } = loadPlaywright();

const ANIM = path.join(ROOT, 'dist', 'animation', 'ink_animations.html');
const OUT = path.join(ROOT, 'dist', 'figures');
fs.mkdirSync(OUT, { recursive: true });

const TARGETS = [
  { key: 'jx', T: 19.578, frames: [
    { t: 0.78,  name: 'jx_01',            anno: false },
    { t: 5.09,  name: 'jx_02',            anno: false },
    { t: 7.83,  name: 'jx_05',            anno: false },
    { t: 7.83,  name: 'jx_05_nopoem',     anno: false, hidePoem: true },
    { t: 12.14, name: 'jx_03',            anno: false },
    { t: 19.03, name: 'jx_04',            anno: false },
    { t: 19.03, name: 'jx_04_nopoem',     anno: false, hidePoem: true },
    { t: 19.03, name: 'jx_04_anno',       anno: true  }
  ]},
  { key: 'bd', T: 13.631, frames: [
    { t: 0.57,  name: 'bd_01',            anno: false },
    { t: 2.56,  name: 'bd_02',            anno: false },
    { t: 8.26,  name: 'bd_03',            anno: false },
    { t: 13.27, name: 'bd_04',            anno: false },
    { t: 13.27, name: 'bd_04_nopoem',     anno: false, hidePoem: true },
    { t: 13.27, name: 'bd_04_anno',       anno: true  }
  ]},
  // 静夜思：未纳入 O1 问题集，仅出图（起 0.9 / 承 6.0 / 转·举头 10.4 / 合末·低头+钤印 17.6）
  { key: 'sy', T: 18.187, frames: [
    { t: 0.9,   name: 'sy_01',            anno: false },
    { t: 6.0,   name: 'sy_02',            anno: false },
    { t: 10.4,  name: 'sy_03',            anno: false },
    { t: 17.6,  name: 'sy_04',            anno: false },
    { t: 17.6,  name: 'sy_04_nopoem',     anno: false, hidePoem: true },
    { t: 17.6,  name: 'sy_04_anno',       anno: true  }
  ]}
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1200, height: 1400 }, deviceScaleFactor: 2 });

for (const target of TARGETS) {
  for (const f of target.frames) {
    const page = await ctx.newPage();
    await page.addInitScript(() => { try { delete window.IntersectionObserver; } catch (e) {} });
    await page.goto(pathToFileURL(ANIM).href, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);

    if (!f.anno) {
      await page.click(`#${target.key}-anno-btn`);
    }
    await page.addStyleTag({ content: '.hud{display:none !important}' });
    if (f.hidePoem) {
      await page.addStyleTag({ content: `#${target.key}-poemink{display:none !important}` });
    }

    const track = page.locator(`.track[data-track="${target.key}"]`);
    await track.scrollIntoViewIfNeeded();
    const bb = await track.boundingBox();
    const frac = Math.min(1, Math.max(0, f.t / target.T));
    await page.mouse.move(bb.x + frac * bb.width, bb.y + bb.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(250);

    const stage = page.locator(`#p-${target.key} .stage`);
    await stage.screenshot({ path: path.join(OUT, `${f.name}.png`) });
    console.log(`saved ${f.name}.png  (t=${f.t}s, anno=${f.anno}, hidePoem=${!!f.hidePoem})`);
    await page.close();
  }
}

await browser.close();
console.log('done ->', OUT);
