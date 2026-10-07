// o1_vlm_check.mjs —— VLM 通道探活：确认端点可达 + 是否支持视觉输入
// 用法：node src/o1/o1_vlm_check.mjs [image]
// 退出码 0 = 可用视觉；2 = 可达但不认图；1 = 不可达
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const D = (...p) => path.join(ROOT, 'data', ...p);
const CATS = ['source', 'derived', 'runs'];
const datapath = f => { for (const c of CATS) { const p = D(c, f); if (fs.existsSync(p)) return p; } return D('derived', f); };


const BASE = (process.env.ANTHROPIC_BASE_URL || '').replace(/\/+$/, '');
const TOKEN = process.env.ANTHROPIC_AUTH_TOKEN || '';
const MODEL = process.env.ANTHROPIC_MODEL || process.env.ANTHROPIC_DEFAULT_SONNET_MODEL || '';

if (!BASE || !TOKEN) {
  console.error('缺少 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN');
  process.exit(1);
}

const imgPath = process.argv[2] || path.join(ROOT, 'dist', 'figures', 'thumbs', 'jx_02.jpg');
const ext = path.extname(imgPath).toLowerCase();
const media = ext === '.png' ? 'image/png' : 'image/jpeg';
const data = fs.readFileSync(imgPath).toString('base64');

const body = {
  model: MODEL,
  max_tokens: 128,
  messages: [{
    role: 'user',
    content: [
      { type: 'image', source: { type: 'base64', media_type: media, data } },
      { type: 'text', text: '这张图里是否有山？只回答「有」或「没有」，不要解释。' }
    ]
  }]
};

async function tryCall(label, headers) {
  const url = BASE + '/v1/messages';
  const t0 = Date.now();
  try {
    const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
    const txt = await res.text();
    let json = null;
    try { json = JSON.parse(txt); } catch (e) {}
    const text = json && json.content ? json.content.map(c => c.text || '').join('') : '';
    console.log(`[${label}] HTTP ${res.status} · ${Date.now() - t0}ms`);
    if (!res.ok) { console.log('  body: ' + txt.slice(0, 400)); return null; }
    if (json && json.error) { console.log('  error: ' + JSON.stringify(json.error).slice(0, 300)); return null; }
    console.log('  model: ' + (json.model || MODEL) + ' · usage: ' + JSON.stringify(json.usage || {}));
    console.log('  回答: ' + (text || '(空)').trim());
    return text;
  } catch (e) {
    console.log(`[${label}] 连接失败: ${e.message}`);
    return null;
  }
}

const common = { 'content-type': 'application/json', 'anthropic-version': '2023-06-01' };
let out = await tryCall('x-api-key', { ...common, 'x-api-key': TOKEN });
if (out == null) out = await tryCall('bearer', { ...common, authorization: 'Bearer ' + TOKEN });

if (out == null) { console.error('VLM 不可达'); process.exit(1); }
const ok = /有|没有|是|否|yes|no|山/i.test(out);
console.log(ok ? '判定：端点可用，且能对图像作答（视觉通道通）' : '判定：端点可达，但回答未体现图像内容（疑似不认图）');
process.exit(ok ? 0 : 2);
