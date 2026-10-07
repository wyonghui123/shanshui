# -*- coding: utf-8 -*-
"""D5 · context.json schema 固化：结构校验 + 语义交叉核对。

结构：按 data/source/context/schema.json（draft-07 子集）校验每首诗的 context.json。
语义（schema 表达不了的跨字段约束）：
  · 所有 source_ids / sources[].id 必须能互相解析（引用不悬空、来源不重复）
  · prosody.pingze 逐句须与 text.base 对齐（句数一致、text 逐句相同）
  · rhyme_feet ⊆ 各句句末字；rusheng_chars ⊆ 全诗字
  · 每首诗的 id 全局唯一

用法：
    python src/tools/context_schema_check.py          # 校验并写 data/runs/context_schema.json
退出码：0 全通过；1 有错误。
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CONTEXT_DIR = os.path.join(ROOT, "data", "source", "context")
SCHEMA = os.path.join(CONTEXT_DIR, "schema.json")
OUT = os.path.join(ROOT, "data", "runs", "context_schema.json")


# ---------------- 轻量 JSON Schema（draft-07 子集） ----------------
def _type_ok(val, t):
    if isinstance(t, list):            # draft-07 联合类型，如 ["number","null"]
        return any(_type_ok(val, x) for x in t)
    if t == "object":
        return isinstance(val, dict)
    if t == "array":
        return isinstance(val, list)
    if t == "string":
        return isinstance(val, str)
    if t == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if t == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if t == "boolean":
        return isinstance(val, bool)
    if t == "null":
        return val is None
    return True


def validate(val, sch, path, root, errs):
    if "$ref" in sch:
        ref = sch["$ref"]
        node = root
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return validate(val, node, path, root, errs)
    if "const" in sch and val != sch["const"]:
        errs.append("%s: 应为常量 %r，实为 %r" % (path, sch["const"], val))
    if "enum" in sch and val not in sch["enum"]:
        errs.append("%s: 不在枚举 %s 内（实为 %r）" % (path, sch["enum"], val))
    if "type" in sch and not _type_ok(val, sch["type"]):
        errs.append("%s: 类型应为 %s，实为 %s" % (path, sch["type"], type(val).__name__))
        return
    if isinstance(val, str):
        if "minLength" in sch and len(val) < sch["minLength"]:
            errs.append("%s: 长度 < %d" % (path, sch["minLength"]))
        if "maxLength" in sch and len(val) > sch["maxLength"]:
            errs.append("%s: 长度 > %d" % (path, sch["maxLength"]))
        if "pattern" in sch and not re.search(sch["pattern"], val):
            errs.append("%s: 不匹配 %s（实为 %r）" % (path, sch["pattern"], val))
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if "minimum" in sch and val < sch["minimum"]:
            errs.append("%s: < 最小值 %s" % (path, sch["minimum"]))
        if "maximum" in sch and val > sch["maximum"]:
            errs.append("%s: > 最大值 %s" % (path, sch["maximum"]))
    if isinstance(val, dict):
        for req in sch.get("required", []):
            if req not in val:
                errs.append("%s: 缺必填字段 %r" % (path, req))
        props = sch.get("properties", {})
        for k, v in val.items():
            if k in props:
                validate(v, props[k], "%s.%s" % (path, k), root, errs)
            else:
                addl = sch.get("additionalProperties", True)
                if addl is False:
                    errs.append("%s.%s: 不允许的字段" % (path, k))
                elif isinstance(addl, dict):
                    validate(v, addl, "%s.%s" % (path, k), root, errs)
        if "minProperties" in sch and len(val) < sch["minProperties"]:
            errs.append("%s: 字段数 < %d" % (path, sch["minProperties"]))
        if "propertyNames" in sch:
            for k in val:
                pn = sch["propertyNames"]
                if "pattern" in pn and not re.search(pn["pattern"], k):
                    errs.append("%s: 字段名 %r 不匹配 %s" % (path, k, pn["pattern"]))
    if isinstance(val, list):
        if "minItems" in sch and len(val) < sch["minItems"]:
            errs.append("%s: 元素数 < %d" % (path, sch["minItems"]))
        if "items" in sch:
            for i, v in enumerate(val):
                validate(v, sch["items"], "%s[%d]" % (path, i), root, errs)


# ---------------- 语义交叉核对 ----------------
def collect_source_ids(obj, path, out):
    """递归收集所有 source_ids 数组里的引用（含单数 source_id）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("source_ids", "source_id") and isinstance(v, (list, str)):
                ids = v if isinstance(v, list) else [v]
                out.extend((i, "%s.%s" % (path, k)) for i in ids)
            else:
                collect_source_ids(v, "%s.%s" % (path, k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_source_ids(v, "%s[%d]" % (path, i), out)


def semantic_errors(ctx, path):
    errs = []
    ids = [s.get("id") for s in ctx.get("sources", [])]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        errs.append("%s: sources 中重复 id %s" % (path, dup))
    known = set(ids)
    refs = []
    collect_source_ids(ctx, path, refs)
    for sid, where in refs:
        if sid not in known:
            errs.append("%s: 引用了不存在的来源 %s" % (where, sid))

    base = ctx.get("text", {}).get("base", [])
    pr = ctx.get("prosody", {})
    pz = pr.get("pingze", [])
    if pz:
        if len(pz) != len(base):
            errs.append("%s: prosody.pingze 句数 %d ≠ text.base 句数 %d" % (path, len(pz), len(base)))
        for i, row in enumerate(pz):
            if i < len(base) and row.get("text") != base[i]:
                errs.append("%s: prosody.pingze[%d].text=%r ≠ text.base[%d]=%r"
                            % (path, i, row.get("text"), i, base[i]))
            if row.get("text") and row.get("pattern") and len(row["pattern"]) != len(row["text"]):
                errs.append("%s: prosody.pingze[%d] 平仄串长度 %d ≠ 句长 %d"
                            % (path, i, len(row["pattern"]), len(row["text"])))
    ends = {ln[-1] for ln in base if ln}
    for ch in pr.get("rhyme_feet", []):
        if ch not in ends:
            errs.append("%s: 韵脚 %r 不在各句句末字内" % (path, ch))
    all_chars = set("".join(base))
    for ch in pr.get("rusheng_chars", []):
        if ch not in all_chars:
            errs.append("%s: 入声字 %r 不在诗中" % (path, ch))
    return errs


def main():
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    reports, err_total = [], 0
    seen_ids = {}
    for name in sorted(os.listdir(CONTEXT_DIR)):
        p = os.path.join(CONTEXT_DIR, name, "context.json")
        if not os.path.exists(p):
            continue
        rel = os.path.relpath(p, ROOT)
        ctx = json.load(open(p, encoding="utf-8"))
        errs = []
        validate(ctx, schema, rel, schema, errs)
        errs += semantic_errors(ctx, rel)
        pid = ctx.get("id")
        if pid:
            if pid in seen_ids:
                errs.append("%s: id %r 与 %s 重复" % (rel, pid, seen_ids[pid]))
            seen_ids[pid] = rel
        reports.append({"file": rel, "id": pid, "errors": errs})
        err_total += len(errs)

    rep = {"meta": {"name": "context_schema", "schema": "poem-context/v1",
                    "role": "D5 护栏：context.json 结构 + 语义交叉核对"},
           "files": reports, "summary": {"files": len(reports), "errors": err_total,
                                          "ok": err_total == 0}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)

    print("[D5·语境 schema] poem-context/v1")
    for r in reports:
        mark = "✓" if not r["errors"] else "✗"
        print("  %s %s (id=%s)" % (mark, r["file"], r["id"]))
        for e in r["errors"]:
            print("      ✗ " + e)
    print("  %s %d 个 context.json，%d 处错误 → %s"
          % ("✓" if err_total == 0 else "✗", len(reports), err_total, OUT))
    if err_total:
        sys.exit(1)


if __name__ == "__main__":
    main()
