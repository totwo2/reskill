#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_criteria_hash.py — 判据防篡改：哈希记账 + 变动提示（不硬拦，Q5 落地）

背景（publish-team-roster.md §7.3 / Q5）：
  gate:15 已有纪律「禁止改判据让检查通过」但无校验。补机器校验：
  对判据文件做哈希，与台账冻结值比对；不一致即提示哪个文件变了。
  **Q5 决议（名册 §六 第 3 条）：记账 + 变动提示，不硬拦**——
  硬拦会让每次合法改判据都卡流程（一天改了 4 个判据文件）。
  故默认 exit 0（只提示），仅 --strict 才 REJECT（exit 1），把"要不要卡"交给调用方。

判据文件（默认）：skill 目录下的 publish-*.md + preflight_* + 判定派发/打分脚本。
  可用 --files 显式指定，或用 --auto 让脚本按默认集合扫描 <skill_dir>。

台账位置：--baseline PATH（默认 <skill_dir>/.publish-staging/criteria_hashes.json）。
  首次运行（或 --init）写基线；之后运行比对。

退出码：
  0 = 基线一致 / 首次写基线 / 有变动但非 --strict
  1 = --strict 且有变动 / 基线损坏

用法：
  python3 verify_criteria_hash.py --skill <dir> [--init] [--strict] [--baseline P] [--files a.md b.py]
  python3 verify_criteria_hash.py --test
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile


DEFAULT_GLOBS = ("publish-*.md", "preflight_quality_check.py", "preflight_publish_check.sh",
                 "preflight_secret_scan.sh", "preflight_allow.txt",
                 "verdict_dispatch.py", "quality_metrics.py")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(skill_dir, explicit=None):
    if explicit:
        files = []
        for p in explicit:
            ap = p if os.path.isabs(p) else os.path.join(skill_dir, p)
            if os.path.isfile(ap):
                files.append(ap)
            else:
                sys.stderr.write(f"WARN 跳过不存在的判据文件：{p}\n")
        return sorted(set(files))
    files = []
    for name in DEFAULT_GLOBS:
        if name.endswith(".md") or name.endswith(".py") or name.endswith(".sh") or name.endswith(".txt"):
            import glob as _g
            files.extend(_g.glob(os.path.join(skill_dir, name)))
    return sorted(set(files))


def snapshot(files):
    return {os.path.basename(f): _sha(f) for f in files}


def run(skill_dir, baseline, init=False, strict=False, explicit=None):
    files = collect_files(skill_dir, explicit)
    if not files:
        print("ℹ️  未找到判据文件，跳过。")
        return 0
    cur = snapshot(files)

    if init or not os.path.exists(baseline):
        os.makedirs(os.path.dirname(baseline) or ".", exist_ok=True)
        with open(baseline, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        print(f"🟢 基线已写入 {baseline}（{len(cur)} 个判据文件）")
        return 0

    base = json.load(open(baseline, encoding="utf-8"))
    changed, added, removed = [], [], []
    for k in cur:
        if k not in base:
            added.append(k)
        elif base[k] != cur[k]:
            changed.append(k)
    for k in base:
        if k not in cur:
            removed.append(k)

    n = len(changed) + len(added) + len(removed)
    if n == 0:
        print(f"🟢 判据哈希一致（{len(cur)} 个文件，对照基线 {os.path.basename(baseline)}）")
        return 0

    print(f"🟡 [变动提示] 判据发生变动（共 {n} 项），请确认是否为有意修订：")
    for k in changed:
        print(f"   ✎ 已修改：{k}")
    for k in added:
        print(f"   ＋ 新增：{k}")
    for k in removed:
        print(f"   － 移除：{k}")
    print("   （默认不硬拦；合法修订照常进行。如需卡流程请加 --strict）")
    return 1 if strict else 0


# --------------------------------------------------------------------------- 自测
def _selftest():
    failures = []
    with tempfile.TemporaryDirectory() as d:
        # 造判据文件
        open(os.path.join(d, "publish-x.md"), "w", encoding="utf-8").write("判据一：必须带锚点")
        open(os.path.join(d, "preflight_y.py"), "w", encoding="utf-8").write("def check(): return 1")
        bl = os.path.join(d, ".publish-staging", "criteria_hashes.json")

        # T1: --init 写基线
        rc = run(d, bl, init=True)
        if rc != 0:
            failures.append(f"T1 init 应 exit 0，实际 {rc}")

        # T2: 无变动再跑 → exit 0
        rc = run(d, bl)
        if rc != 0:
            failures.append(f"T2 无变动应 exit 0，实际 {rc}")

        # T3: 改一个判据文件 → 变动提示，默认 exit 0
        open(os.path.join(d, "publish-x.md"), "w", encoding="utf-8").write("判据一：必须带锚点（修订后）")
        rc = run(d, bl)
        if rc != 0:
            failures.append(f"T3 变动默认应 exit 0，实际 {rc}")

        # T4: --strict 有变动 → exit 1
        rc = run(d, bl, strict=True)
        if rc != 1:
            failures.append(f"T4 --strict 变动应 exit 1，实际 {rc}")

        # T5: 覆盖回原内容 → 再次一致 exit 0
        open(os.path.join(d, "publish-x.md"), "w", encoding="utf-8").write("判据一：必须带锚点")
        rc = run(d, bl)
        if rc != 0:
            failures.append(f"T5 还原后应 exit 0，实际 {rc}")

    print(f"\n自测：{'全部通过 ✅' if not failures else '有失败 ❌'}")
    for f in failures:
        print("  - " + f)
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="判据哈希记账 + 变动提示（不硬拦）")
    ap.add_argument("--skill", help="skill 目录（判据文件所在）")
    ap.add_argument("--baseline", help="基线 JSON 路径（默认 <skill>/.publish-staging/criteria_hashes.json）")
    ap.add_argument("--files", nargs="*", help="显式指定判据文件（覆盖默认集合）")
    ap.add_argument("--init", action="store_true", help="写基线（首次或主动重置）")
    ap.add_argument("--strict", action="store_true", help="有变动时 exit 1（REJECT）；默认只提示")
    ap.add_argument("--test", action="store_true", help="跑自测")
    args = ap.parse_args()
    if args.test:
        return _selftest()
    if not args.skill:
        ap.error("必须提供 --skill（或 --test）")
    skill = os.path.abspath(args.skill)
    bl = args.baseline or os.path.join(skill, ".publish-staging", "criteria_hashes.json")
    return run(skill, bl, init=args.init, strict=args.strict, explicit=args.files)


if __name__ == "__main__":
    sys.exit(main())
