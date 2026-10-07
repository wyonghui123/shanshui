// 声画同步体检：加载动画页抓 console/page 错误；再解析源码里的音轨路径与 cfg.T，
// 与 WAV 头算出的真实时长核对（不依赖 window 全局，配置在 IIFE 内）。
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
const src = fs.readFileSync(ANIM, 'utf8');

// 从源码里抠出每首诗的 T 与 audio（配置在 IIFE 内，无法从 window 读）
const cfgRe = /var\s+(JX|BD|SY)\s*=\s*\{([\s\S]*?)\n\s*\};/g;
const cfgs = [];
let m;
while ((m = cfgRe.exec(src)) !== null) {
  const body = m[2];
  const t = (body.match(/\bT:\s*([\d.]+)/) || [])[1];
  const audio = (body.match(/audio:\s*'([^']+)'/) || [])[1] || null;
  cfgs.push({ key: m[1], T: t ? +t : null, audio });
}

function wavDuration(file) {
  const buf = fs.readFileSync(file);
  if (buf.toString('ascii', 0, 4) !== 'RIFF' || buf.toString('ascii', 8, 12) !== 'WAVE') return null;
  let off = 12, fmt = null, dataSize = null;
  while (off + 8 <= buf.length) {
    const id = buf.toString('ascii', off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === 'fmt ') fmt = { ch: buf.readUInt16LE(off + 10), sr: buf.readUInt32LE(off + 12), bits: buf.readUInt16LE(off + 22) };
    if (id === 'data') { dataSize = size; break; }
    off += 8 + size + (size % 2);
  }
  if (!fmt || dataSize == null) return null;
  return dataSize / (fmt.sr * fmt.ch * (fmt.bits / 8));
}

const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('console', e => { if (e.type() === 'error') errors.push('console: ' + e.text()); });
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('requestfailed', r => errors.push('requestfailed: ' + r.url() + ' (' + (r.failure() || {}).errorText + ')'));
await page.goto(pathToFileURL(ANIM).href, { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(800);
await browser.close();

console.log('诗   T(源码)   音轨时长(WAV头)   差    音轨');
for (const c of cfgs) {
  let dur = null, note = '';
  if (c.audio) {
    const f = path.join(path.dirname(ANIM), c.audio);
    if (fs.existsSync(f)) { dur = +wavDuration(f).toFixed(3); }
    else { note = '（文件缺失）'; }
  } else { note = '（无音轨）'; }
  const delta = (dur != null && c.T != null) ? +(dur - c.T).toFixed(3) : '';
  console.log(`${c.key.padEnd(3)} ${String(c.T).padEnd(8)} ${String(dur).padEnd(16)} ${String(delta).padEnd(6)} ${c.audio || '—'} ${note}`);
}
console.log('\nJS/资源错误：' + (errors.length ? '\n  ' + errors.join('\n  ') : '无'));
