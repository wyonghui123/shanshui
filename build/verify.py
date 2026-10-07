# -*- coding: utf-8 -*-
"""全链路体检：一次跑完「D2 回归 + 注入快照 + 场景几何三方 + 交付包同步 + HTML 本地链接」。

用法：
    python build/verify.py     # 体检
退出码：0 全通过；1 有失败项。
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
NODE = shutil.which("node") or "node"
REF = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']')
EXTERNAL = ("http://", "https://", "data:", "#", "//", "mailto:")
SKIP_DIRS = ("_archive", ".trae-html-share-packages", "__pycache__")


def run(label, args, tail=None):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    print(("  ✓ " if ok else "  ✗ ") + label)
    if not ok or tail:
        lines = (r.stdout or "").rstrip().splitlines()
        if r.returncode != 0:
            lines += (r.stderr or "").rstrip().splitlines()
        for line in (lines[-tail:] if tail else lines):
            print("      " + line)
    return 0 if ok else 1


def check_links():
    print("── HTML 本地链接")
    files = miss_total = 0
    for r, d, fs in os.walk(ROOT):
        if any(x in r for x in SKIP_DIRS):
            continue
        for f in fs:
            if not f.endswith(".html"):
                continue
            p = os.path.join(r, f)
            files += 1
            base = os.path.dirname(p)
            t = open(p, encoding="utf-8", errors="ignore").read()
            miss = []
            for m in REF.finditer(t):
                v = m.group(1)
                if v.startswith(EXTERNAL):
                    continue
                tgt = os.path.normpath(os.path.join(base, v.split("?")[0].split("#")[0]))
                if not os.path.exists(tgt):
                    miss.append(v)
            if miss:
                miss_total += len(miss)
                print("      ✗ " + os.path.relpath(p, ROOT))
                for v in sorted(set(miss)):
                    print("          " + v)
    print("  %s %d 个 HTML，缺失 %d" % ("✓" if not miss_total else "✗", files, miss_total))
    return miss_total


def _relay(label, args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "").rstrip()
    if r.returncode != 0:
        out += ("\n" + (r.stderr or "").rstrip()).rstrip()
    print(out)
    return 0 if r.returncode == 0 else 1


def check_scene():
    """场景几何单一真源：动画 ↔ data/source/scene/<pid>.json ↔ 全链路 STEP5/STEP6。

    由 build/scene_render.py --check 承担，逐值覆盖全部命名元素（云 / 山 / 舟 …）。
    取代早先只针对「彩云」的窄口径基线（render_geom_baseline.json 已归档）。
    """
    return _relay("场景几何", [PY, os.path.join("build", "scene_render.py"), "--check"])


def check_assert():
    """度量断言：画面属性 ↔ D2 处方（焦点 / 含水档 / 人物 size）。

    由 build/scene_assert.py 承担——把 D2 现算的 role/water/size 与冻结场景里量得的
    画面属性对账，防「模型算了、画面没照做」。几何一致 ≠ 处方兑现，二者互补。
    """
    return _relay("度量断言", [PY, os.path.join("build", "scene_assert.py")])


def main():
    fails = 0

    print("── 输入端护栏（Wave 0 + G13）")
    fails += run("D1 音韵护栏", [PY, os.path.join("src", "d1", "d1_resolve.py"), "--check"])
    fails += run("D5 语境 schema", [PY, os.path.join("src", "tools", "context_schema_check.py")])
    fails += run("D6 情感词表", [PY, os.path.join("src", "tools", "emotion_lexicon_check.py")])
    fails += run("O2 虚实阈值 G13", [NODE, os.path.join("src", "o2", "o2_imagery.mjs"), "--check"], tail=8)

    print("── 控制链与交付")
    fails += run("D2 回归", [PY, os.path.join("src", "d2", "d2_resolve.py")], tail=2)
    rep_path = os.path.join(ROOT, "data", "runs", "d2_regression.json")
    rep = json.load(open(rep_path, encoding="utf-8"))
    if rep["summary"]["all_pass"]:
        print("  ✓ D2 回归全通过（%d/%d）" % (rep["summary"]["passed"], rep["summary"]["total"]))
    else:
        print("  ✗ D2 回归未全通过"); fails += 1

    fails += run("D2 注入快照", [PY, os.path.join("src", "d2", "d2_inject.py"), "--check"])
    fails += check_scene()
    fails += check_assert()
    fails += run("题诗字体子集", [PY, os.path.join("build", "font_subset.py"), "--check"], tail=4)
    fails += run("题诗逐笔数据", [PY, os.path.join("build", "stroke_data.py"), "--check"], tail=4)
    for pid in ("jx", "bd", "jys"):
        fails += run("D3 音乐轨 · %s" % pid,
                     [PY, os.path.join("src", "music", "music_render.py"), "--pid", pid, "--check"], tail=10)
    fails += run("音频引用版本戳", [PY, os.path.join("src", "music", "stamp_audio_ver.py"), "--check"], tail=4)
    fails += run("交付包同步", [PY, os.path.join("build", "assemble.py"), "--check"])
    fails += check_links()

    print()
    if fails:
        print("✗ 全链路体检未通过（%d 项）" % fails)
        sys.exit(1)
    print("✓ 全链路体检通过")


if __name__ == "__main__":
    main()
