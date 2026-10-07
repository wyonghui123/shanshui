# -*- coding: utf-8 -*-
"""分享包审计：判定 .trae-html-share-packages 内各 zip 是否已过期。

判定口径：
  ① 主页面：取 zip 内的「主页面」（与 zip 同名的那份 HTML），按字节哈希比对仓库内
     现存 HTML。匹配上任意一份即为「同步」（分享包会对引用做路径改写，如音轨 →
     samples/voice/，故用「是否等于某现存页面」而非「是否等于唯一源文件」）。
  ② 内嵌资产：包内 wav / woff2 / js / mp3 / png 等资产，按「同名文件的哈希集合」
     比对仓库现存同类文件。若某资产哈希不在集合内，说明它已被重渲 / 重建而未随包更新
     （如音乐轨重渲后旧包仍内嵌旧 wav）——判「过期」。缺此检查会漏检「HTML 未变但
     内嵌资产已变」的过期包。
  两条均通过才判「同步」。

用法：
    python src/tools/_share_pkg_audit.py             # 列出（只读）
    python src/tools/_share_pkg_audit.py --archive   # 把过期包移入 _archive
"""
import argparse
import datetime
import hashlib
import os
import shutil
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARE = os.path.join(ROOT, ".trae-html-share-packages")
ARCHIVE = os.path.join(ROOT, "_archive",
                       "_share_packages_stale_" + datetime.date.today().isoformat())
SKIP = ("_archive", ".trae-html-share-packages", "__pycache__")
ASSET_EXT = (".wav", ".woff2", ".js", ".mp3", ".png")


def md5(b):
    return hashlib.md5(b).hexdigest()


def current_hashes():
    """仓库内现存 HTML 的哈希集合（排除归档与分享包目录）。"""
    h = {}
    for r, d, fs in os.walk(ROOT):
        if any(x in r for x in SKIP):
            continue
        for f in fs:
            if f.endswith(".html"):
                p = os.path.join(r, f)
                h.setdefault(md5(open(p, "rb").read()), []).append(os.path.relpath(p, ROOT))
    return h


def current_asset_hashes():
    """仓库内现存资产（同名 → 哈希集合），用于核对包内资产是否已过期。"""
    h = {}
    for r, d, fs in os.walk(ROOT):
        if any(x in r for x in SKIP):
            continue
        for f in fs:
            if f.lower().endswith(ASSET_EXT):
                p = os.path.join(r, f)
                h.setdefault(f, set()).add(md5(open(p, "rb").read()))
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true", help="把过期分享包移入 _archive")
    args = ap.parse_args()

    known = current_hashes()
    assets = current_asset_hashes()
    stale, fresh = [], []

    for r, d, fs in os.walk(SHARE):
        for f in sorted(fs):
            if not f.endswith(".zip"):
                continue
            zp = os.path.join(r, f)
            rel = os.path.relpath(zp, SHARE)
            main = f[:-4]
            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                entry = next((n for n in names if os.path.basename(n) == main), None)
                if entry is None:
                    stale.append((rel, "包内无主页面 %s" % main))
                    continue
                body = z.read(entry)
                drift = []
                for n in names:
                    if n == entry or n.endswith("/"):
                        continue
                    bn = os.path.basename(n)
                    if bn.lower().endswith(ASSET_EXT) and bn in assets:
                        if md5(z.read(n)) not in assets[bn]:
                            drift.append(bn)
            hit = known.get(md5(body))
            if hit and not drift:
                fresh.append((rel, hit))
            elif hit and drift:
                stale.append((rel, "HTML 同步，但内嵌资产过期：%s" % "、".join(drift)))
            else:
                stale.append((rel, None))

    print("── 分享包审计（%d 个）" % (len(stale) + len(fresh)))
    print("  同步 %d 个：" % len(fresh))
    for rel, hit in fresh:
        print("    ✓ %s  →  %s" % (rel, hit[0]))
    print("  过期 %d 个：" % len(stale))
    for rel, why in stale:
        print("    ✗ %s  →  %s" % (rel, why if isinstance(why, str) else "与任何现存页面都不一致"))

    if not args.archive:
        print("\n（只读。加 --archive 归档过期包）")
        return

    if not stale:
        print("\n无过期分享包，无需归档。")
        return

    for rel, _ in stale:
        src = os.path.join(SHARE, rel)
        dst = os.path.join(ARCHIVE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        print("    → %s" % os.path.relpath(dst, ROOT))
    print("\n已归档 %d 个过期分享包 -> %s" % (len(stale), os.path.relpath(ARCHIVE, ROOT)))


if __name__ == "__main__":
    main()
