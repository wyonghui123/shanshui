# -*- coding: utf-8 -*-
"""给 ink_animations.html 的音频引用盖上「内容哈希」版本号（防 file:// 缓存旧音频）。

为什么需要：
  音频轨（voice / music）重渲后，页面里的引用字符串没变，`file://` 下浏览器会继续
  播它缓存里的旧 wav。用户听到的就不是新修好的声音——《静夜思》北箫修好（原先读指针
  多除一个 sr，整条主奏掉进 <80Hz 次声区）后，用户仍「只听到筝」，根因即此：页面引用
  是 `../audio/music/jys.wav`，浏览器拿的是旧文件。
  查询串会构成一个新 URL，强制浏览器重新取文件。

做法：
  对页面里每个 `../audio/(voice|music)/<name>.wav` 引用，计算该 wav 的 md5 前 8 位，
  写成 `../audio/(voice|music)/<name>.wav?v=<hash8>`。音频一变，版本号自动变。

幂等：先剥掉旧的 `?v=...` 再按当前文件重算，重复运行结果一致。

用法：
    python src/music/stamp_audio_ver.py            # 写盘
    python src/music/stamp_audio_ver.py --check    # 只校验（有漂移则退出码 1）
"""
import hashlib
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANIM = os.path.join(ROOT, "dist", "animation", "ink_animations.html")
ANIM_DIR = os.path.dirname(ANIM)

# 匹配 ../audio/voice/xxx.wav 或 ../audio/music/xxx.wav，可选带 ?v=xxxx
REF = re.compile(r"(\.\./audio/(?:voice|music)/[A-Za-z0-9_\-]+\.wav)(?:\?v=[0-9a-fA-F]+)?")


def md5_8(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()[:8]


def main():
    check = "--check" in sys.argv
    with open(ANIM, encoding="utf-8") as f:
        src = f.read()

    missing, stamped, changed = [], [], []

    def repl(m):
        ref = m.group(1)
        path = os.path.normpath(os.path.join(ANIM_DIR, ref.replace("/", os.sep)))
        if not os.path.exists(path):
            missing.append(ref)
            return m.group(0)
        want = "%s?v=%s" % (ref, md5_8(path))
        got = m.group(0)
        stamped.append(ref)
        if want != got:
            changed.append((ref, got, want))
        return want

    out = REF.sub(repl, src)

    print("── 音频引用版本戳（%s）" % os.path.relpath(ANIM, ROOT))
    for ref in stamped:
        print("  · %s" % ref)
    if missing:
        print("  ⚠ 引用了不存在的文件：%s" % "、".join(sorted(set(missing))))

    if check:
        if changed:
            print("\n✗ %d 处版本戳漂移（跑 python src/music/stamp_audio_ver.py 修复）：" % len(changed))
            for ref, got, want in changed:
                print("    %s\n      now  %s\n      want %s" % (ref, got, want))
            sys.exit(1)
        print("\n✓ 版本戳与音频文件一致（%d 处）" % len(stamped))
        return

    if not changed:
        print("\n✓ 无需改动（%d 处版本戳已是最新）" % len(stamped))
        return
    with open(ANIM, "w", encoding="utf-8") as f:
        f.write(out)
    print("\n✓ 已更新 %d 处版本戳" % len(changed))


if __name__ == "__main__":
    main()
