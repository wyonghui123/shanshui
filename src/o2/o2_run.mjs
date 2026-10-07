// o2_run.mjs —— O2 意象抽取一键跑（抽取 → 复核工装页）
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STEPS = [
  { f: 'o2_imagery.mjs', desc: '格律分词 → 意象抽取 → 依存消歧 → 可画性门控 + gold 验证 + 画面核对' },
  { f: 'o2_build_harness.mjs', desc: '生成复核工装页 o2_imagery_harness.html' },
];
for (let i = 0; i < STEPS.length; i++) {
  const s = STEPS[i];
  console.log('\n──────── [' + (i + 1) + '/' + STEPS.length + '] ' + s.f + ' —— ' + s.desc + ' ────────');
  const r = spawnSync(process.execPath, [s.f], { cwd: __dirname, stdio: 'inherit' });
  if (r.status !== 0) { console.log('\n✗ 中止于 ' + s.f + '（exit ' + r.status + '）'); process.exit(r.status || 1); }
}
console.log('\n════ O2 完成：o2_imagery.json · o2_imagery_report.md · o2_imagery_harness.html ════');
