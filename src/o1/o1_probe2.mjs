// 细网格墨迹图：定位《江雪》下半幅里非纸面像素的位置与形状
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
const FRAMES = path.join(ROOT, 'dist', 'figures');

const SPECS = [
  { img: 'jx_05_nopoem.png', label: 'jx_05 去诗 · 万径区 (x0-0.32, y0.38-0.58)', region: [0.0, 0.38, 0.32, 0.58] },
  { img: 'jx_02.png',        label: 'jx_02 带诗 · 万径区 (x0-0.32, y0.38-0.58)', region: [0.0, 0.38, 0.32, 0.58] },
  { img: 'jx_01.png',        label: 'jx_01 · 万径区 (x0-0.32, y0.38-0.58)',       region: [0.0, 0.38, 0.32, 0.58] },
];

const browser = await chromium.launch();
const page = await browser.newPage();

for (const spec of SPECS) {
  const url = 'data:image/png;base64,' + fs.readFileSync(path.join(FRAMES, spec.img)).toString('base64');
  const r = await page.evaluate(async ({ url, region }) => {
    const img = new Image(); img.src = url; await img.decode();
    const W = img.naturalWidth, H = img.naturalHeight;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.drawImage(img, 0, 0);
    const [x0, y0, x1, y1] = region;
    const px0 = Math.round(x0 * W), py0 = Math.round(y0 * H);
    const px1 = Math.round(x1 * W), py1 = Math.round(y1 * H);
    const w = px1 - px0, h = py1 - py0;
    const d = cx.getImageData(px0, py0, w, h).data;
    const GX = 60, GY = 24;
    const grid = Array.from({ length: GY }, () => Array(GX).fill(0));
    const cnt = Array.from({ length: GY }, () => Array(GX).fill(0));
    let darkest = { lum: 999, x: -1, y: -1 };
    let nonPaper = 0, total = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (d[i + 3] < 8) continue;
      const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      total++;
      if (lum < 238) nonPaper++;
      if (lum < darkest.lum) darkest = { lum: +lum.toFixed(1), x: +(px0 + x) / W, y: +(py0 + y) / H };
      const gx = Math.min(GX - 1, Math.floor(x / w * GX));
      const gy = Math.min(GY - 1, Math.floor(y / h * GY));
      grid[gy][gx] += lum; cnt[gy][gx]++;
    }
    return { W, H, grid: grid.map((row, gy) => row.map((v, gx) => v / cnt[gy][gx])), darkest, nonPaper, total };
  }, { url, region: spec.region });

  console.log(`\n### ${spec.label}`);
  console.log(`非纸面(<238)像素占比 ${(r.nonPaper / r.total * 100).toFixed(2)}%  最暗点 lum=${r.darkest.lum} @ (${r.darkest.x.toFixed(3)}, ${r.darkest.y.toFixed(3)})`);
  const ramp = ' .:-=+*#%@';
  console.log('墨迹图（每格 60x24 均值；「.」=纸面，「@」=最浓）：');
  for (const row of r.grid) {
    console.log('  ' + row.map(v => {
      if (v >= 240) return ' ';
      if (v >= 236) return '.';
      if (v >= 228) return ':';
      if (v >= 215) return '-';
      if (v >= 200) return '=';
      if (v >= 180) return '+';
      if (v >= 150) return '*';
      if (v >= 100) return '#';
      return '@';
    }).join(''));
  }
}
await browser.close();
