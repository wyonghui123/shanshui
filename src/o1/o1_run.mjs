// o1_run.mjs —— O1 评估闭环一键复跑（固化入口）
// 顺序：结构校验 → 源码事实 → 像素探针 → 可见性探针 → 判读卡 → 证据口径 → 评分/回归
// 任一环节失败即中止；评分环节的回退门槛（exit 1）会原样上报。
// 用法：node src/o1/o1_run.mjs   （Windows: node src/o1/o1_run.mjs）
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const STEPS = [
  { f: 'o1_validate.mjs', desc: '问题集结构断言 + 基线交叉核对' },
  { f: 'o1_source_facts.mjs', desc: '源码结构化事实抽取' },
  { f: 'o1_probe.mjs', desc: '像素探针（留白 / 分区墨密度）' },
  { f: 'o1_probe_cam.mjs', desc: '相机轨迹采样（DOM scale → o1_cam_trace.json）' },
  { f: 'o1_probe_vis.mjs', desc: '按判读帧采样元素可见性' },
  { f: 'o1_judge.mjs', desc: '判读卡组装（自动层 + 目视层）' },
  { f: 'o1_lint.mjs', desc: '证据栏口径核对（反查源码事实）' },
  { f: 'o1_score.mjs', desc: '评分 / 汇总 / 基线回归比对' },
];

const t0 = Date.now();
for (let i = 0; i < STEPS.length; i++) {
  const s = STEPS[i];
  const n = String(i + 1).padStart(2, '0');
  console.log('\n──────── [' + n + '/' + STEPS.length + '] ' + s.f + ' —— ' + s.desc + ' ────────');
  const r = spawnSync(process.execPath, [s.f], { cwd: __dirname, stdio: 'inherit' });
  if (r.status !== 0) {
    console.log('\n✗ 中止于 ' + s.f + '（exit ' + r.status + '）');
    process.exit(r.status || 1);
  }
}
console.log('\n════ O1 闭环复跑完成（' + ((Date.now() - t0) / 1000).toFixed(1) + 's）════');
console.log('产物：o1_source_facts.json · o1_probe.json · o1_vis.json · o1_judge_cards.json · o1_lint.json · o1_score.json · o1_score_report.md');
