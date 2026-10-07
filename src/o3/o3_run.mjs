// o3_run.mjs —— O3 负节点双判据一键跑（双判据判定 → 复核工装页）
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STEPS = [
  { f: 'o3_negatives.mjs', desc: '视觉共现网络低度 + 熵正则部分 OT 未运输质量 → 交叉验证 → gold 对照' },
  { f: 'o3_build_harness.mjs', desc: '生成复核工装页 o3_negatives_harness.html' },
];
for (let i = 0; i < STEPS.length; i++) {
  const s = STEPS[i];
  console.log('\n──────── [' + (i + 1) + '/' + STEPS.length + '] ' + s.f + ' —— ' + s.desc + ' ────────');
  const r = spawnSync(process.execPath, [s.f], { cwd: __dirname, stdio: 'inherit' });
  if (r.status !== 0) { console.log('\n✗ 中止于 ' + s.f + '（exit ' + r.status + '）'); process.exit(r.status || 1); }
}
console.log('\n════ O3 完成：o3_negatives.json · o3_negatives_report.md · o3_negatives_harness.html ════');
