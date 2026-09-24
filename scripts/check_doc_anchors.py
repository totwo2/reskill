#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_anchors.py —— N4.5 文档↔实现一致性 自动化（publish-code-audit.md §四）

**干什么**：把「文档里出现的每一个可执行、可定位的东西」抽出来，去源码里找锚点。
找不到 = 幻觉，打回 N2。这是把人工审计文档那一步脚本化。

**抽什么**（与 §四 检查清单对齐）：
  ① 代码块里的命令（```bash / ```sh / ```console）—— 安装命令、快速开始的每条命令
  ② 反引号标识符 —— 入口（函数名/文件名/模块路径）、"支持 XX"
  ③ （可选）数字 —— 回 fact-sheet.md 找出处（--check-numbers 时启用）

**怎么判**（默认 grep 模式，安全；--run 才真跑）：
  · `python -m X`        → 源码里 X/__main__.py 或 X.py 存在
  · `pip install X`      → 项目根有 setup.py / pyproject.toml
  · `python X.py`        → X.py 存在
  · `./X` / `node X.js`  → 文件存在
  · `auto_scan()` 标识符 → grep `def auto_scan`
  · `scanner.py` 文件名  → 全项目找得到
  · `pkg.mod` 模块路径   → pkg/mod.py 存在

**输出**：一份 markdown 报告，表头严格对齐 `verify_audit_report.py` 的 kind=docs 契约
（`| 文档里写的 | 实跑 | 不符 = fail |`），可直接被该脚本校验。

用法：
    python3 check_doc_anchors.py <项目源码目录> --readme <README.md> [--docs SKILL.md ...]
                                      [--commit <sha>] [--run] [--check-numbers] [--json]
    python3 check_doc_anchors.py --test

退出码：0 = 全部通过；1 = 有 FAIL；2 = 用法错。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# 报告抬头里的 commit 行（供 verify_audit_report.py 做版本对齐）
COMMIT_HINT = re.compile(r"@\s*`?([0-9a-f]{7,40})`?")

# 反引号标识符（行内 `...`）
BACKTICK_RE = re.compile(r"`([^`\n]+)`")

# 代码块 ```lang ... ```
FENCE_RE = re.compile(r"^```(\w*)\s*$", re.M)


# ---------------------------------------------------------------- 抽取

def split_fences(text):
    """返回 [(lang, body), ...] 仅取代码块（lang 空也算）。"""
    out = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^```(\w*)\s*$", lines[i])
        if m:
            lang = m.group(1)
            buf = []
            j = i + 1
            while j < len(lines) and not re.match(r"^```\s*$", lines[j]):
                buf.append(lines[j])
                j += 1
            out.append((lang, "\n".join(buf)))
            i = j + 1
            continue
        i += 1
    return out


def extract_commands(fences):
    """从代码块里抽命令。每行视为一条（过滤明显非命令）。"""
    cmds = []
    SAFE_VERB = re.compile(
        r"^\s*(python3?|pip3?|node|npm|npx|bash|sh|deno|bun|ruby|perl|cargo|go|./[\w.-]+|"
        r"\w[\w.-]*\.py|\w[\w.-]*\.js|\w[\w.-]*\.sh)\b")
    for _lang, body in fences:
        for line in body.split("\n"):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if SAFE_VERB.match(s):
                cmds.append(s)
    return cmds


def extract_identifiers(text):
    """从全文反引号里抽标识符（函数名/文件名/模块路径），去命令里的。"""
    ids = []
    for tok in BACKTICK_RE.findall(text):
        t = tok.strip().rstrip("()").strip()
        if not t or t in ("bash", "sh", "python", "python3"):
            continue
        # 跳过整段命令（含空格的通常是要执行的，不是标识符）
        if " " in t and not re.match(r"^[\w./-]+\.[\w]+$", t):
            continue
        ids.append(t)
    return ids


# ---------------------------------------------------------------- 判定

def _walk_find(root, name):
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__", "node_modules",
                                              ".venv", "dist", "build")]
        if name in fns:
            return os.path.join(dp, name)
    return None


def check_entry(kind, token, root):
    """返回 (found: bool, detail: str)。

    kind: 'mod'（-m X）/ 'pip' / 'pyfile' / 'bin' / 'func' / 'file' / 'modpath'
    """
    if kind == "mod":
        cand = [token, token.replace("-", "_")]
        for c in cand:
            if os.path.isfile(os.path.join(root, c, "__main__.py")):
                return True, f"grep {c}/__main__.py → 存在"
            if os.path.isfile(os.path.join(root, c + ".py")):
                return True, f"grep {c}.py → 存在"
        return False, f"{token}/__main__.py 与 {token}.py 均无"
    if kind == "pip":
        for f in ("setup.py", "pyproject.toml", "setup.cfg"):
            if os.path.isfile(os.path.join(root, f)):
                return True, f"根目录有 {f}"
        return False, "根目录无 setup.py/pyproject.toml"
    if kind == "pyfile":
        if os.path.isfile(os.path.join(root, token)):
            return True, f"ls {token} → 存在"
        hit = _walk_find(root, token)
        return (hit is not None), (f"全项目找 {token} → 存在" if hit else f"{token} 不存在")
    if kind == "bin":
        if os.path.isfile(os.path.join(root, token)):
            return True, f"ls {token} → 存在"
        return False, f"{token} 不存在"
    if kind == "func":
        # grep def <tok> 或 <tok>( 在源码
        pat = re.compile(r"(def\s+" + re.escape(token) + r"\b|function\s+" + re.escape(token) + r"\b|\b" + re.escape(token) + r"\s*\()")
        for dp, dn, fns in os.walk(root):
            dn[:] = [d for d in dn if d not in (".git", "__pycache__", "node_modules", ".venv")]
            for fn in fns:
                if fn.endswith((".py", ".js", ".ts", ".go", ".rb", ".sh", ".lua")):
                    try:
                        for line in open(os.path.join(dp, fn), encoding="utf-8", errors="ignore"):
                            if pat.search(line):
                                return True, f"grep def {token} → {fn}"
                    except OSError:
                        pass
        return False, f"grep def {token} → 0 命中"
    if kind == "file":
        # 文件名或含 / 的路径
        base = os.path.basename(token)
        hit = _walk_find(root, base)
        if hit:
            return True, f"全项目找 {base} → 存在"
        if "/" in token and os.path.isfile(os.path.join(root, token)):
            return True, f"ls {token} → 存在"
        return False, f"{token} 不存在"
    if kind == "modpath":
        # a.b.c → a/b/c.py
        rel = token.replace(".", os.sep) + ".py"
        if os.path.isfile(os.path.join(root, rel)):
            return True, f"ls {rel} → 存在"
        return False, f"{rel} 不存在"
    return False, "未知判定类型"


def classify_command(cmd, root):
    """把一条命令归类为 (kind, token, display)。"""
    # python -m X
    m = re.search(r"python3?\s+-m\s+([\w.-]+)", cmd)
    if m:
        return "mod", m.group(1), cmd
    # pip install X
    m = re.search(r"pip3?\s+install\s+([\w.-]+)", cmd)
    if m:
        return "pip", m.group(1), cmd
    # python X.py / python X
    m = re.search(r"python3?\s+([\w./-]+\.py|\w[\w.-]*)", cmd)
    if m:
        tok = m.group(1)
        return "pyfile", tok, cmd
    # ./X
    m = re.search(r"\.{1,2}/([\w./-]+)", cmd)
    if m:
        return "bin", m.group(1), cmd
    # node X.js
    m = re.search(r"\b(node|npm run)\s+([\w./-]+)", cmd)
    if m:
        return "bin", m.group(2), cmd
    # 退化：取第一个像文件/标识符的 token
    m = re.search(r"([\w./-]+\.\w{1,4})", cmd)
    if m:
        return "file", m.group(1), cmd
    return "file", cmd.split()[0] if cmd.split() else cmd, cmd


def classify_identifier(tok):
    """把反引号标识符归类为 (kind, token)。"""
    if re.match(r"^[\w./-]+\.[A-Za-z]+$", tok):       # scanner.py / a/b.py
        return "file", tok
    if re.match(r"^[\w.]+/[\w.]+$", tok) and "." in tok.split("/")[-1]:
        return "file", tok
    if re.match(r"^[A-Za-z_][\w.]*\.[A-Za-z_][\w.]*$", tok):  # pkg.mod
        return "modpath", tok
    if re.match(r"^[A-Za-z_]\w*$", tok):              # auto_scan
        return "func", tok
    if "/" in tok:                                     # plugins/
        return "file", tok
    return "func", tok


# ---------------------------------------------------------------- 主流程

def analyze(root, readmes, run=False, check_numbers=False):
    """返回 (rows, stats)；rows = [(claim, how, verdict), ...]"""
    root = os.path.abspath(root)
    texts = []
    for p in readmes:
        if os.path.isfile(p):
            texts.append(open(p, encoding="utf-8").read())
    doc = "\n".join(texts)

    fences = []
    for t in texts:
        fences.extend(split_fences(t))
    commands = extract_commands(fences)
    identifiers = extract_identifiers(doc)

    rows = []
    seen = set()

    def add(claim, kind, token, display):
        key = (claim, token)
        if key in seen:
            return
        seen.add(key)
        found, detail = check_entry(kind, token, root)
        if run and kind in ("mod", "pip", "pyfile", "bin"):
            found, detail = _try_run(display, root, found, detail)
        verdict = "通过" if found else f"fail: {detail}"
        rows.append((claim, f"{display} → {detail}", verdict))

    for c in commands:
        kind, tok, disp = classify_command(c, root)
        add(f"命令：{c}", kind, tok, disp)

    for tok in identifiers:
        kind, t = classify_identifier(tok)
        add(f"标识符：`{tok}`", kind, t, f"grep {tok}")

    if check_numbers:
        for num in re.findall(r"\d+(?:\.\d+)?\s*(?:x|倍|%|%)", doc):
            rows.append((f"数字：{num}", "回 fact-sheet.md 找出处（人工）", "请人工核对"))

    stats = {"commands": len(commands), "identifiers": len(identifiers),
             "rows": len(rows), "fails": sum(1 for r in rows if r[2].startswith("fail"))}
    return rows, stats


def _try_run(cmd, root, grep_found, grep_detail):
    """--run 时真跑命令（在临时目录，超时 10s）。grep 已找到也跑一下验证可运行。"""
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(cmd, shell=True, cwd=td, capture_output=True,
                               text=True, timeout=10,
                               env={**os.environ, "PYTHONPATH": root})
            ok = r.returncode == 0
            detail = f"实跑 exit={r.returncode}" + ("" if ok else f"：{r.stderr[:80]}")
            return ok, detail
    except Exception as e:
        return False, f"实跑异常：{e}"


def render_markdown(root, commit, rows):
    lines = ["# N4.5 第三方代码审计（文档↔实现一致性·自动）", ""]
    lines.append(f"审计对象：`{root}` @ `{commit or 'HEAD'}`")
    lines.append("")
    lines.append("## N4.5 检查清单（文档说的能不能在源码里找到）")
    lines.append("| 文档里写的 | 实跑 | 不符 = fail |")
    lines.append("|---|---|---|")
    for claim, how, verdict in rows:
        lines.append(f"| {claim} | {how} | {verdict} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 自检

def run_test():
    import shutil
    tmp = tempfile.mkdtemp()
    results = []
    try:
        # 造一个真实项目
        pkg = os.path.join(tmp, "mypkg")
        os.makedirs(os.path.join(pkg, "mypkg"))
        open(os.path.join(pkg, "mypkg", "__main__.py"), "w").write("def main(): pass\n")
        open(os.path.join(pkg, "setup.py"), "w").write("from setuptools import setup\n")
        open(os.path.join(pkg, "scanner.py"), "w").write("def auto_scan():\n    return 1\n")
        open(os.path.join(pkg, "ghost.py"), "w").write("def ghost_fn():\n    pass\n")

        readme = os.path.join(tmp, "README.md")
        open(readme, "w", encoding="utf-8").write(
            "# 测试包\n\n安装：\n\n```bash\npip install mypkg\npython -m mypkg\n```\n\n"
            "快速开始：\n\n```bash\npython scanner.py\n```\n\n"
            "入口函数 `auto_scan()`，模块 `mypkg.scanner`（注：不存在），文件 `ghost.py`。\n"
            "虚构入口 `nonexistent_fn()`。\n")

        rows, stats = analyze(pkg, [readme])

        def find(claim_sub):
            for r in rows:
                if claim_sub in r[0]:
                    return r
            return None

        # pip install mypkg → 应有 setup.py → 通过
        r = find("pip install mypkg")
        results.append(("pip install mypkg → 通过", r is not None and r[2] == "通过", str(r)))
        # python -m mypkg → __main__.py → 通过
        r = find("python -m mypkg")
        results.append(("python -m mypkg → 通过", r is not None and r[2] == "通过", str(r)))
        # python scanner.py → 文件存在 → 通过
        r = find("python scanner.py")
        results.append(("python scanner.py → 通过", r is not None and r[2] == "通过", str(r)))
        # auto_scan() → def 存在 → 通过
        r = find("auto_scan")
        results.append(("auto_scan() → 通过", r is not None and r[2] == "通过", str(r)))
        # ghost.py → 存在 → 通过
        r = find("ghost.py")
        results.append(("ghost.py → 通过", r is not None and r[2] == "通过", str(r)))
        # mypkg.scanner → 模块路径不存在 → fail
        r = find("mypkg.scanner")
        results.append(("mypkg.scanner → fail（路径不存在）",
                        r is not None and r[2].startswith("fail"), str(r)))
        # nonexistent_fn() → 无 def → fail
        r = find("nonexistent_fn")
        results.append(("nonexistent_fn() → fail（无 def）",
                        r is not None and r[2].startswith("fail"), str(r)))

        # 报告过 verify_audit_report.py（kind=docs）
        rep = render_markdown(pkg, "abc1234", rows)
        rep_path = os.path.join(tmp, "audit-docs.md")
        open(rep_path, "w", encoding="utf-8").write(rep)
        v = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__),
                        "verify_audit_report.py"), rep_path, "--project", pkg],
                        capture_output=True, text=True)
        results.append(("产出报告过 verify_audit_report.py（kind=docs）",
                        v.returncode == 0, v.stdout[-200:]))

        # 负样本：纯虚构 README → 应全 fail
        bad = os.path.join(tmp, "BAD.md")
        open(bad, "w", encoding="utf-8").write(
            "# 虚构\n```bash\npython -m nope\n```\n入口 `missing_fn()`。\n")
        rows2, _ = analyze(pkg, [bad])
        results.append(("虚构文档 → 有 fail", any(r[2].startswith("fail") for r in rows2), str(rows2)))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=== 自测（check_doc_anchors）===")
    bad = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            bad += 1
            print(f"      ← {detail[:200]}")
    print(f"\n通过 {len(results)-bad}/{len(results)}")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="check_doc_anchors.py",
        description="N4.5 文档↔实现一致性自动化：抽 README 命令/标识符 → 源码找锚点")
    ap.add_argument("project", nargs="?", help="项目源码目录")
    ap.add_argument("--readme", action="append", default=[], help="README/SKILL 文件路径（可多次）")
    ap.add_argument("--commit", default=None, help="被审 commit（写入报告抬头，供版本对齐）")
    ap.add_argument("--run", action="store_true", help="真跑命令（默认仅 grep/ls 校验入口存在）")
    ap.add_argument("--check-numbers", action="store_true", help="额外抽出数字交人工核对")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args(argv)

    if args.test:
        return run_test()
    if not args.project:
        ap.print_help()
        return 2
    if not args.readme:
        # 默认找项目根下的 README.md / SKILL.md
        for cand in ("README.md", "SKILL.md", "readme.md", "skill.md"):
            p = os.path.join(args.project, cand)
            if os.path.isfile(p):
                args.readme.append(p)
    if not args.readme:
        print("ERROR: 找不到要审的文档，用 --readme 指定", file=sys.stderr)
        return 2

    rows, stats = analyze(args.project, args.readme, run=args.run,
                           check_numbers=args.check_numbers)
    rep = render_markdown(args.project, args.commit, rows)

    if args.json:
        print(json.dumps({"ok": stats["fails"] == 0, "stats": stats,
                          "report": rep}, ensure_ascii=False))
        return 1 if stats["fails"] else 0

    print(rep)
    print(f"\n# 统计：{stats['rows']} 项检查，{stats['fails']} 项 fail")
    return 1 if stats["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
