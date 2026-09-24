#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace_callchain.py —— 表 B 超纲判定的调用链自动追（N0.5）

依据 `publish-code-audit.md` §三 表 B：

    超纲判定只有一个硬判据：把调用链追到主入口。
      grep -rn "<这个模块的符号>" .
        → 命中只在自己文件内 = 死代码 = 加戏
        → 能一路追到主入口    = 必要（需求清单写漏了，补登记）
        → 追不到但删不掉      = 存疑，交人

**本脚本只做 grep 级近似，不是 AST。** 它回答的是文件级可达性：
"从主入口出发，能不能走到这个文件？" —— 与判据文档给的 grep 方法同粒度。
查不出结论时它说 `uncertain`，**不猜**（缺证据不得放行）。

用法：
    python3 trace_callchain.py <项目目录> --target <文件或符号> [--entry <文件或符号>]... [--json]
    python3 trace_callchain.py <项目目录> --target scripts/foo.py --show-path
    python3 trace_callchain.py --test

退出码：0 = 可达；1 = 不可达（死代码）；3 = 存疑（追不到但删不掉）；2 = 用法错。
"""

import argparse
import json
import os
import re
import sys
from collections import deque

# 认哪些源码后缀
DEFAULT_EXTS = (".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".go",
                ".java", ".c", ".cc", ".cpp", ".h", ".cs", ".rb", ".php", ".rs", ".lua")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".publish-staging", ".mypy_cache", ".pytest_cache", "dist", "build",
             ".tox", ".eggs"}

# 太短或太通用的符号不参与建边（否则满图都是边，等于没追）
STOP = {"main", "test", "init", "self", "data", "name", "path", "args", "true",
        "false", "none", "null", "import", "return", "print", "file", "text",
        "value", "item", "list", "dict", "str", "int", "run", "load", "save"}
MIN_SYM_LEN = 4

# 各语言"定义符号"的正则（取第 1 组为符号名）
DEF_PATTERNS = [
    re.compile(r"^\s*def\s+(\w+)", re.M),
    re.compile(r"^\s*class\s+(\w+)", re.M),
    re.compile(r"^\s*(?:async\s+)?function\s+(\w+)", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=", re.M),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)", re.M),
    re.compile(r"^\s*type\s+(\w+)", re.M),
    re.compile(r"^\s*(?:public|private|protected|static|final|\s)+[\w<>\[\],\s]+\s+(\w+)\s*\(", re.M),
    re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{", re.M),
    re.compile(r"^\s*fn\s+(\w+)", re.M),
    re.compile(r"^\s*sub\s+(\w+)", re.M),
]

# "这是主入口"的信号
ENTRY_HINTS = [
    re.compile(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]'),
    re.compile(r"^\s*func\s+main\s*\(", re.M),
    re.compile(r"^\s*package\s+main", re.M),
    re.compile(r"public\s+static\s+void\s+main\s*\(", re.M),
    re.compile(r"^\s*#!\s*/usr/bin/env\s+(?:python|bash|sh|node)", re.M),
]
ENTRY_NAMES = ("__main__.py", "main.py", "cli.py", "app.py", "run.py", "index.js",
               "index.ts", "main.go", "main.sh", "run.sh")


def collect_files(root, exts):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(exts):
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def defined_symbols(text):
    syms = set()
    for pat in DEF_PATTERNS:
        for m in pat.finditer(text):
            s = m.group(1)
            if len(s) >= MIN_SYM_LEN and s.lower() not in STOP:
                syms.add(s)
    return syms


def load_project(root, exts):
    """返回 {relpath: {"text":..., "syms": set(), "stem": str}}"""
    files = {}
    for rel in collect_files(root, exts):
        try:
            text = open(os.path.join(root, rel), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        syms = defined_symbols(text)
        if len(stem) >= MIN_SYM_LEN and stem.lower() not in STOP:
            syms.add(stem)          # 文件名本身也是可被 import/require 的符号
        files[rel] = {"text": text, "syms": syms, "stem": stem}
    return files


def build_edges(files):
    """A → B：A 的正文里出现了 B 定义的符号（且不是 B 自己）"""
    edges = {k: set() for k in files}
    for a, fa in files.items():
        for b, fb in files.items():
            if a == b or not fb["syms"]:
                continue
            for s in fb["syms"]:
                if re.search(r"\b%s\b" % re.escape(s), fa["text"]):
                    edges[a].add(b)
                    break
    return edges


def detect_entries(files, edges):
    """主入口候选：显式 main 信号 / 约定文件名 / 无入边的根"""
    entries, why = [], {}
    for rel, f in files.items():
        if any(p.search(f["text"]) for p in ENTRY_HINTS):
            entries.append(rel); why[rel] = "显式 main / shebang 信号"
        elif os.path.basename(rel) in ENTRY_NAMES:
            entries.append(rel); why[rel] = "约定入口文件名"
    if not entries:
        inbound = {k: 0 for k in files}
        for a, bs in edges.items():
            for b in bs:
                inbound[b] += 1
        roots = [k for k, n in inbound.items() if n == 0]
        if roots:
            entries = roots
            for r in roots:
                why[r] = "无入边的根文件（可能是入口）"
    return entries, why


def resolve_target(files, target):
    """target 可以是文件路径、文件名、符号名，或 `模块.符号` 形式"""
    t = target.replace("\\", "/")
    if t in files:
        return t
    for rel in files:
        if rel.endswith("/" + t) or os.path.basename(rel) == t:
            return rel
    # `core.do_work` 这种点号写法：取最后一段当符号名再试
    cands = [t] if "." not in t else [t, t.rsplit(".", 1)[1]]
    for c in cands:
        hits = [rel for rel, f in files.items() if c in f["syms"]]
        if len(hits) == 1:
            return hits[0]
    return None


def bfs(edges, entries, target):
    """从 entries 出发 BFS，返回 (是否可达, 最短路径)"""
    seen = {e: [e] for e in entries}
    q = deque(entries)
    while q:
        cur = q.popleft()
        if cur == target:
            return True, seen[cur]
        for nxt in sorted(edges.get(cur, ())):
            if nxt not in seen:
                seen[nxt] = seen[cur] + [nxt]
                q.append(nxt)
    return False, []


def inbound_count(edges, target):
    return sum(1 for a, bs in edges.items() if a != target and target in bs)


def analyze(root, target, entry_args, exts):
    files = load_project(root, exts)
    if not files:
        return {"ok": False, "reason": "项目里没找到任何源码文件"}
    edges = build_edges(files)

    if entry_args:
        entries = []
        for e in entry_args:
            r = resolve_target(files, e)
            if r:
                entries.append(r)
        why = {e: "手动指定" for e in entries}
    else:
        entries, why = detect_entries(files, edges)

    tgt = resolve_target(files, target)
    if tgt is None:
        return {"ok": False,
                "reason": f"找不到目标「{target}」—— 既不是文件路径，也不是唯一符号名",
                "files": len(files)}

    if not entries:
        return {"ok": True, "target": tgt, "verdict": "uncertain",
                "reason": "定不出主入口（没有任何 main 信号、也没有无入边的根）—— 必须人工指定 --entry",
                "entries": [], "files": len(files)}

    reach, path = bfs(edges, entries, tgt)
    inb = inbound_count(edges, tgt)

    if reach:
        verdict, note = "reachable", "主入口可达 → 必要超纲，补登记进 R2"
    elif inb == 0:
        verdict, note = "dead", "零外部引用 → 死代码 / 加戏，建议删"
    else:
        verdict, note = "uncertain", f"追不到主入口，但有 {inb} 处外部引用 → 存疑，交人"

    return {"ok": True, "target": tgt, "verdict": verdict, "reason": note,
            "entries": entries, "entry_why": why, "inbound": inb,
            "path": path, "files": len(files),
            "method": "grep 级文件可达性（非 AST），与 publish-code-audit.md §三 表 B 同粒度"}


# ---------------------------------------------------------------- 自检
def _mk(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)


def run_test():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    try:
        proj = os.path.join(tmp, "p")
        # 入口 → core → helper（可达链）
        _mk(proj, "main.py",
            "import core\n\nif __name__ == \"__main__\":\n    core.do_work()\n")
        _mk(proj, "core.py",
            "import helper\n\ndef do_work():\n    return helper.assist_me()\n")
        _mk(proj, "helper.py",
            "def assist_me():\n    return 1\n")
        # 死代码：只被自己引用
        _mk(proj, "orphan_module.py",
            "def orphan_function():\n    return orphan_function\n")
        # 悬空但被别的不可达文件引用
        _mk(proj, "island_a.py", "import island_b\n\ndef island_entry():\n    return island_b\n")
        _mk(proj, "island_b.py", "def lonely_helper():\n    return 2\n")

        r = analyze(proj, "helper.py", None, DEFAULT_EXTS)
        check("可达链 helper.py → reachable", r.get("verdict") == "reachable", str(r))
        check("可达链给出路径", r.get("path") and r["path"][0] == "main.py", str(r.get("path")))

        r = analyze(proj, "orphan_module.py", None, DEFAULT_EXTS)
        check("零引用孤儿 → dead", r.get("verdict") == "dead", str(r))

        r = analyze(proj, "island_b.py", None, DEFAULT_EXTS)
        check("不可达但有外部引用 → uncertain", r.get("verdict") == "uncertain", str(r))

        r = analyze(proj, "core.do_work", ["main.py"], DEFAULT_EXTS)
        check("按符号名 + 手动入口 → 可达", r.get("verdict") == "reachable", str(r))

        r = analyze(proj, "不存在的符号xyz", None, DEFAULT_EXTS)
        check("目标不存在 → ok=False", r.get("ok") is False, str(r))

        # 完全定不出入口的项目
        # 注意：符号名要 ≥ MIN_SYM_LEN(4)，否则不参与建边 —— 这里用长名
        p2 = os.path.join(tmp, "p2")
        _mk(p2, "alpha_mod.py",
            "import beta_module\n\ndef alpha_entry():\n    return beta_module\n")
        _mk(p2, "beta_module.py", "def beta_helper():\n    return 1\n")
        r = analyze(p2, "beta_module.py", ["alpha_mod.py"], DEFAULT_EXTS)
        check("手动指定入口可用", r.get("verdict") == "reachable", str(r))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=== 自测（trace_callchain）===")
    bad = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            bad += 1
            print(f"      ← {detail[:220]}")
    print(f"\n通过 {len(results)-bad}/{len(results)}")
    return 1 if bad else 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="trace_callchain.py",
        description="表 B 超纲判定的调用链自动追：从主入口出发，判断目标文件是否可达")
    ap.add_argument("project", nargs="?", help="项目根目录")
    ap.add_argument("--target", help="要判的目标：文件路径 / 文件名 / 符号名")
    ap.add_argument("--entry", action="append", default=None,
                    help="手动指定主入口（可重复）。不指定则自动探测")
    ap.add_argument("--ext", default=None, help="逗号分隔的源码后缀，默认常见 19 种")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args(argv)

    if args.test:
        return run_test()
    if not args.project or not args.target:
        ap.print_help()
        return 2
    if not os.path.isdir(args.project):
        print(f"ERROR: 不是目录：{args.project}", file=sys.stderr)
        return 2

    exts = tuple(e if e.startswith(".") else "." + e for e in args.ext.split(",")) \
        if args.ext else DEFAULT_EXTS

    r = analyze(args.project, args.target, args.entry, exts)

    if args.as_json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        if not r.get("ok"):
            print(f"❌ {r.get('reason')}")
            return 2
        icon = {"reachable": "🟢", "dead": "🔴", "uncertain": "⚪"}[r["verdict"]]
        print(f"目标：{r['target']}")
        print(f"  {icon} 判定：{r['verdict']} —— {r['reason']}")
        print(f"  入边数：{r['inbound']}（除自己以外有多少文件引用它）")
        print(f"  主入口：{', '.join(r['entries']) or '（无）'}")
        for e in r["entries"]:
            print(f"          └ {e}  ← {r['entry_why'].get(e, '')}")
        if r["path"]:
            print(f"  可达路径：{' → '.join(r['path'])}")
        print(f"  扫描 {r['files']} 个源码文件；方法：{r['method']}")

    return {"reachable": 0, "dead": 1, "uncertain": 3}.get(r.get("verdict"), 2)


if __name__ == "__main__":
    sys.exit(main())
