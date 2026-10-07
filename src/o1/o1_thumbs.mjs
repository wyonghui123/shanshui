// 生成关键帧缩略图，供评估工装 HTML 使用（原图 ~1.8MB/张，缩略图 ~120KB）
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

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
  return require(pick.p);
}
const { chromium } = loadPlaywright();

const SRC = path.join(ROOT, 'dist', 'figures');
const DST = path.join(SRC, 'thumbs');
fs.mkdirSync(DST, { recursive: true });

const files = fs.readdirSync(SRC).filter(f => f.endsWith('.png'));
const browser = await chromium.launch();
const page = await browser.newPage();

for (const f of files) {
  const url = 'data:image/png;base64,' + fs.readFileSync(path.join(SRC, f)).toString('base64');
  const dataUrl = await page.evaluate(async ({ url }) => {
    const img = new Image(); img.src = url; await img.decode();
    const W = 760;
    const H = Math.round(img.naturalHeight * W / img.naturalWidth);
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d');
    cx.fillStyle = '#F6F3EC'; cx.fillRect(0, 0, W, H);
    cx.drawImage(img, 0, 0, W, H);
    return cv.toDataURL('image/jpeg', 0.86);
  }, { url });
  fs.writeFileSync(path.join(DST, f.replace(/\.png$/, '.jpg')), Buffer.from(dataUrl.split(',')[1], 'base64'));
  console.log(`thumb ${f} -> ${f.replace(/\.png$/, '.jpg')}`);
}
await browser.close();
console.log('done ->', DST);
