// O1 客观探针：对关键帧做像素级统计，为「留白率」「万径是否渲染」「雪点是否存在」提供硬证据
// 用已缓存的 playwright 起一个 chromium，把 PNG 画到 canvas 上读像素，不依赖任何图像库。
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

const FRAMES = path.join(ROOT, 'dist', 'figures');

// region 用归一化坐标 [x0, y0, x1, y1]
const SPECS = [
  { img: 'jx_02.png', name: 'jx_02 全幅',            region: [0, 0, 1, 1] },
  { img: 'jx_02.png', name: 'jx_02 下半(排芦苇)',    region: [0.22, 0.52, 1, 0.99] },
  { img: 'jx_05_nopoem.png', name: 'jx_05去诗 下半(排芦苇)', region: [0.22, 0.52, 1, 0.99] },
  { img: 'jx_05_nopoem.png', name: 'jx_05去诗 江面(下半·左)',  region: [0.22, 0.52, 0.6, 0.99] },
  { img: 'jx_01.png', name: 'jx_01 上半(山/天空)',    region: [0, 0, 1, 0.5] },
  { img: 'jx_04.png', name: 'jx_04 全幅',            region: [0, 0, 1, 1] },
  { img: 'bd_02.png', name: 'bd_02 全幅',            region: [0, 0, 1, 1] },
  { img: 'bd_04_nopoem.png', name: 'bd_04去诗 全幅',  region: [0, 0, 1, 1] },
  { img: 'bd_02.png', name: 'bd_02 近水带(y0.62-1.0)', region: [0.1, 0.62, 0.9, 1.0] },
  /* v1.2/O1.2 补：疏密与留白形状题需要分区数据（BD-A7 / BD-A8），远山墨色题需要山带（JX-A2） */
  { img: 'bd_02.png', name: 'bd_02 左壁(x0-0.30)',    region: [0, 0, 0.30, 1] },
  { img: 'bd_02.png', name: 'bd_02 中央峡口(x0.44-0.62)', region: [0.44, 0, 0.62, 1] },
  { img: 'bd_02.png', name: 'bd_02 右壁(x0.70-1)',    region: [0.70, 0, 1, 1] },
  { img: 'jx_02.png', name: 'jx_02 山带(y0.24-0.52)', region: [0, 0.24, 1, 0.52] },
];

const browser = await chromium.launch();
const page = await browser.newPage();
const out = [];

for (const spec of SPECS) {
  const file = path.join(FRAMES, spec.img);
  // about:blank 页面无法解码 file:// 图片，改为内联 base64
  const url = 'data:image/png;base64,' + fs.readFileSync(file).toString('base64');
  const res = await page.evaluate(async ({ url, region }) => {
    const img = new Image();
    img.src = url;
    await img.decode();
    const W = img.naturalWidth, H = img.naturalHeight;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.drawImage(img, 0, 0);
    const [x0, y0, x1, y1] = region;
    const px0 = Math.round(x0 * W), py0 = Math.round(y0 * H);
    const px1 = Math.round(x1 * W), py1 = Math.round(y1 * H);
    const w = px1 - px0, h = py1 - py0;
    const d = cx.getImageData(px0, py0, w, h).data;

    // 纸色基线：#F6F3EC ≈ lum 243。用「明显暗于纸」判定墨迹。
    let sum = 0, n = 0, paper = 0, faint = 0, ink = 0, dark = 0;
    let minLum = 255;
    const GX = 12, GY = 6;
    const grid = Array.from({ length: GY }, () => Array(GX).fill(0));
    const gcnt = Array.from({ length: GY }, () => Array(GX).fill(0));
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        const a = d[i + 3];
        if (a < 8) { continue; }                       // 圆角外的透明像素不计
        const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        sum += lum; n++;
        if (lum < minLum) minLum = lum;
        if (lum >= 240) paper++;                        // 留白/纸面
        else if (lum >= 225) faint++;                   // 极淡墨（几乎看不出）
        else if (lum >= 150) ink++;                     // 中灰（山石等）
        else dark++;                                    // 浓墨
        const gx = Math.min(GX - 1, Math.floor(x / w * GX));
        const gy = Math.min(GY - 1, Math.floor(y / h * GY));
        grid[gy][gx] += lum; gcnt[gy][gx]++;
      }
    }
    return {
      W, H, region,
      px: { w, h, n },
      meanLum: +(sum / n).toFixed(1),
      minLum: +minLum.toFixed(1),
      paperFrac: +(paper / n).toFixed(4),
      faintFrac: +(faint / n).toFixed(4),
      inkFrac: +(ink / n).toFixed(4),
      darkFrac: +(dark / n).toFixed(4),
      faintPlusInkFrac: +((faint + ink + dark) / n).toFixed(4),
      grid: grid.map((row, gy) => row.map((v, gx) => Math.round(v / gcnt[gy][gx]))),
    };
  }, { url, region: spec.region });

  out.push({ name: spec.name, img: spec.img, ...res });
  console.log(`\n=== ${spec.name} (${res.W}x${res.H}, region ${spec.region.map(v => v.toFixed(2)).join(',')}) ===`);
  console.log(`meanLum=${res.meanLum}  minLum=${res.minLum}  留白(≥240)=${(res.paperFrac * 100).toFixed(1)}%  极淡(225-240)=${(res.faintFrac * 100).toFixed(2)}%  中灰(150-225)=${(res.inkFrac * 100).toFixed(2)}%  浓墨(<150)=${(res.darkFrac * 100).toFixed(2)}%`);
  console.log('亮度网格(12x6, 越暗数值越小):');
  for (const row of res.grid) console.log('  ' + row.map(v => String(v).padStart(4)).join(''));
}

fs.writeFileSync(path.join(ROOT, 'data', 'runs', 'o1_probe.json'), JSON.stringify(out, null, 2));
console.log('\n-> o1_probe.json');
await browser.close();
