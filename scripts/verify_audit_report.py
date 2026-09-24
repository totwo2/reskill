#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_audit_report.py —— 审计表证据完整性校验（N0.5 / N4.5）

依据 `publish-code-audit.md`：
  - §三 输出格式（强制）：**每张表的每一行，锚点列和验证方式列不许为空**
    「空锚点行 = 无效判定，脚本拒收（audit-code.md 校验：锚点列空 → exit 1）」
  - §三 表 A/B/C 与 §四 检查清单 各自的列名不同，但**判据是同一条**：
    表头里凡是"证据列"（锚点 / 验证 / 实跑 / 怎么查 / 追调用链），单元格不许为空。
  - §三「最后一条最要命」：声称"实测"却无留痕 = 幻觉。所以**空表也算无效** ——
    交了张只有表头的表，等于没查。

为什么要有这个脚本：
  审计代理是 LLM。它最省事的作弊方式不是编数据，是**交一张格式对、但证据列空着的表** ——
  人扫一眼看不出，机器一眼看得出。这道校验就是拦它。

用法：
    python3 verify_audit_report.py <报告文件> [--kind auto|code|docs] [--json]
    python3 verify_audit_report.py --test

退出码：0 = 通过；1 = 有拒收项；2 = 用法错。
"""

import argparse
import json
import os
import re
import sys

# 表头里出现这些词的列 = 证据列，单元格不许为空。
# 注意：判据文档给的是**列名的含义**，不是**列名的字面** ——
# 实测 selfopt 的真实报告把表 C 的「怎么查（必须是实跑，不是读）」写成了「实跑」，
# 把意图三态表的证据列写成「判据」。所以这里按"词"匹配，不按整串匹配。
EVIDENCE_COLS = ("锚点", "验证", "实跑", "怎么查", "追调用链", "判据")

# 判定列允许的取值（按开头符号判）
VERDICT_SETS = {
    "cover": ("✅", "⚠️", "❌"),          # 表 A 覆盖表：三种，没有"应该实现了"
    "over":  ("🟢", "🔴", "⚪"),          # 表 B 超纲表
}

# 表头特征 → 表身份（用于 kind=code 的三表齐全检查）
# 用**最具辨识度的那一两个词**做键，不要用整串列名（真实报告不会照抄列名）。
TABLE_SIGNATURES = {
    "表A 覆盖表": ("需求", "锚点"),
    "表B 超纲表": ("追调用链",),
    "表C 幻觉表": ("检查项",),
    "N4.5 检查清单": ("文档里写的",),
}

PLACEHOLDER = {"", "-", "--", "—", "–", "~", "/", "n/a", "N/A", "无", "TBD", "tbd"}


def _cells(line):
    """把一行 markdown 表格拆成单元格。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(line):
    """表格的分隔行 |---|---|"""
    s = line.strip()
    if not s.startswith("|"):
        return False
    body = s.strip("|")
    return bool(body) and all(set(c.strip()) <= set("-: ") for c in body.split("|"))


def _blank(cell):
    return cell.strip() in PLACEHOLDER


# 锚点里出现的「路径[:行号]」—— 用来核对锚点是不是真的指得到东西
ANCHOR_RE = re.compile(r"([A-Za-z0-9_][\w./-]*\.(?:py|sh|bash|js|mjs|cjs|ts|tsx|go|java|c|cc|cpp|h|cs|rb|php|rs|lua|md|json|yaml|yml|toml|txt|cfg|ini))(?::(\d+))?")


def verify_anchors(root, cells):
    """核对锚点列里的 文件[:行号] 是否真实存在。

    为什么必须查这个（2026-09-23 实证）：
      selfopt 的真实 audit-code.md 里写 `scripts/analyzer_rules_example.py` 并声称"仅在自身第 17 行"，
      但**那个文件根本不存在**（ls 报 No such file）。
      只查"格子空不空"会放过它 —— **写了但假的锚点，比空锚点更危险**：
      空锚点至少明摆着没证据，假锚点看起来证据齐全。
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    for cell in cells:
        for m in ANCHOR_RE.finditer(cell):
            path, line = m.group(1), m.group(2)
            # 只认像路径的（含 / 或至少是 xxx.py 这种），跳过纯文件名歧义太高的
            if "/" not in path and not os.path.exists(os.path.join(root, path)):
                # 可能是裸文件名，全项目找一次
                hit = None
                for dp, dn, fns in os.walk(root):
                    dn[:] = [d for d in dn if d not in SKIP_ANCHOR_DIRS]
                    if os.path.basename(path) in fns:
                        hit = os.path.join(dp, path); break
                if hit:
                    continue
                out.append(f"锚点文件找不到：{path}")
                continue
            full = os.path.join(root, path)
            if not os.path.exists(full):
                out.append(f"锚点文件不存在：{path}")
                continue
            if line:
                try:
                    n = sum(1 for _ in open(full, encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
                if int(line) > n:
                    out.append(f"锚点行号越界：{path}:{line}（该文件只有 {n} 行）")
    return out


SKIP_ANCHOR_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist", "build"}

# 报告抬头里的「审计对象：<path> @ <commit>」
COMMIT_RE = re.compile(r"@\s*`?([0-9a-f]{7,40})`?")


def current_head(root):
    """取仓库当前 HEAD 短 sha；不是 git 仓库 / 取不到就返回 None。"""
    import subprocess
    for git in ("/usr/bin/git", "git"):
        try:
            r = subprocess.run([git, "-C", root, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            continue
    return None


def report_commit(text):
    m = COMMIT_RE.search(text[:2000])
    return m.group(1) if m else None


def parse_tables(text):
    """抽出所有 markdown 表：返回 [(标题, header, [rows]), ...]

    标题 = 该表之前最近的一行 # 标题（用于报错定位）。
    """
    lines = text.split("\n")
    tables = []
    heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            heading = line.lstrip("#").strip()
        if line.strip().startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            header = _cells(line)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                if not _is_sep(lines[j]):
                    rows.append(_cells(lines[j]))
                j += 1
            tables.append((heading, header, rows))
            i = j
            continue
        i += 1
    return tables


def classify(header):
    h = "".join(header)
    for name, keys in TABLE_SIGNATURES.items():
        if all(k in h for k in keys):
            return name
    return None


def check_report(text, kind, root=None):
    """返回 (findings, tables)；findings = [(级别, 说明), ...]

    root：项目根目录。给了就顺带核对锚点里的 文件[:行号] 是否真实存在。
    """
    findings = []
    tables = parse_tables(text)

    if not tables:
        findings.append(("error", "报告里一张表都没有 —— 没有表的审计等于没做"))
        return findings, tables

    for heading, header, rows in tables:
        where = heading or "(无标题表)"
        if not rows:
            findings.append(("error", f"{where}：表里没有任何数据行（只有表头）—— 空表 = 没查"))
            continue

        # 1) 证据列不许为空
        ev_idx = [i for i, h in enumerate(header) if any(k in h for k in EVIDENCE_COLS)]
        if not ev_idx:
            findings.append(("warn", f"{where}：没找到证据列（表头 {' / '.join(header)}）—— 无法校验，请核对列名"))
        for n, row in enumerate(rows, 1):
            for i in ev_idx:
                cell = row[i] if i < len(row) else ""
                if _blank(cell):
                    col = header[i] if i < len(header) else f"第{i+1}列"
                    findings.append(("error", f"{where} 第 {n} 行：「{col}」为空 —— 空证据行 = 无效判定"))

        # 2) 锚点列：核对锚点指的东西真的在
        #    哪些列算"锚点"：
        #      · 表头含「锚点」的列（表 A 的「代码锚点」）
        #      · 表 B 的第一列「代码」—— 它列的也是代码实体，同样是锚点
        #    不核表 C 的「怎么查」列：那里**故意**会提到不存在的文件
        #    （例："实跑 `pip install x` 无 setup.py" —— setup.py 不存在正是结论）
        anc_idx = {i for i, h in enumerate(header) if "锚点" in h}
        if classify(header) == "表B 超纲表" and header:
            anc_idx.add(0)
        if anc_idx and root:
            # 版本对齐：报告是针对某个 commit 写的。若当前 HEAD 已不是那个 commit，
            # 锚点对不上很可能只是"审计之后代码正常演进了"（例：审计判某文件是死模板，
            # 随后那次提交把它删了 —— 2026-09-23 selfopt 实证）。
            # 那种情况下把 error 降成 warn，否则这道检查会**诬告**审计造假。
            rpt_c = report_commit(text)
            head_c = current_head(root)
            stale = bool(rpt_c and head_c and rpt_c != head_c
                         and not head_c.startswith(rpt_c) and not rpt_c.startswith(head_c))
            for n, row in enumerate(rows, 1):
                cells = [row[i] for i in sorted(anc_idx) if i < len(row)]
                for prob in verify_anchors(root, cells):
                    if stale:
                        findings.append(("warn",
                            f"{where} 第 {n} 行：{prob} —— 但报告针对 {rpt_c}、当前 HEAD {head_c}，"
                            f"锚点对不上可能只是审计之后的正常演进，**不判造假**（要判就 checkout 到 {rpt_c} 复核）"))
                    else:
                        findings.append(("error", f"{where} 第 {n} 行：{prob} —— 假锚点 = 无效判定"))

        # 3) 判定列取值合法
        tid = classify(header)
        v_idx = [i for i, h in enumerate(header) if "判定" in h]
        if tid in ("表A 覆盖表", "表B 超纲表") and v_idx:
            allowed = VERDICT_SETS["cover"] if tid == "表A 覆盖表" else VERDICT_SETS["over"]
            for n, row in enumerate(rows, 1):
                i = v_idx[0]
                cell = row[i] if i < len(row) else ""
                if cell and not cell.startswith(allowed):
                    findings.append(("error",
                        f"{where} 第 {n} 行：判定「{cell[:20]}」不在允许取值 {'/'.join(allowed)} 内"))

    # 4) kind=code 必须三表齐全
    if kind == "code":
        got = {classify(h) for _, h, _ in tables}
        for need in ("表A 覆盖表", "表B 超纲表", "表C 幻觉表"):
            if need not in got:
                findings.append(("error", f"kind=code：缺 {need} —— 三张表必须齐（§三）"))
    elif kind == "docs":
        if "N4.5 检查清单" not in {classify(h) for _, h, _ in tables}:
            findings.append(("error", "kind=docs：缺 N4.5 检查清单表（表头需含「文档里写的」）"))

    return findings, tables


# ---------------------------------------------------------------- 自检
GOOD_CODE = """# audit-code.md（测试样本）

## 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 扫描热点 | ✅ 已实现 | `scanner.py:42` def auto_scan() | `python3 -c "from s import auto_scan"` → exit 0 |
| R2-3 没做的 | ❌ 未实现 | 无锚点 | grep `xx` → 0 命中 |

## 表 B：超纲表
| 代码 | 需求里有吗 | 追调用链 | 判定 |
|---|---|---|---|
| `plugins/` | ❌ 无 | grep → 0 处被主入口调用 | 🔴 加戏，建议删 |
| `io_trace.py` | ❌ 无 | → profile.py → auto_scan() 主入口可达 | 🟢 必要超纲，补登记 |

## 表 C：幻觉表
| 检查项 | 怎么查（必须是实跑，不是读） | 命中 = 幻觉 |
|---|---|---|
| 入口不存在 | 实跑 `python -m x` | 无 __main__.py |
| 空壳函数 | grep `pass$` / TODO | 函数体是占位 |
"""

EMPTY_ANCHOR = """# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 | ✅ 已实现 |  | 跑了 |
"""

EMPTY_VERIFY = """# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 | ✅ 已实现 | `a.py:1` |  |
"""

HEADER_ONLY = """# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
"""

BAD_VERDICT = """# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 | 应该实现了 | `a.py:1` | 跑了 |
"""

MISSING_TABLE_B = """# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 | ✅ 已实现 | `a.py:1` | 跑了 |
"""


def run_test():
    pass_ = 0
    fail = 0
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    f, _ = check_report(GOOD_CODE, "code")
    check("合规三表 → 无 error", not [x for x in f if x[0] == "error"], str(f))

    f, _ = check_report(EMPTY_ANCHOR, "auto")
    check("锚点列空 → error", any("代码锚点" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report(EMPTY_VERIFY, "auto")
    check("验证方式列空 → error", any("验证方式" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report(HEADER_ONLY, "auto")
    check("只有表头没有数据行 → error", any("空表" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report(BAD_VERDICT, "auto")
    check("判定取值非法 → error", any("不在允许取值" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report(MISSING_TABLE_B, "code")
    check("kind=code 缺表 B → error", any("缺 表B" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report("没有任何表格的纯文字报告\n", "auto")
    check("整份没有表 → error", any("一张表都没有" in d for lv, d in f if lv == "error"), str(f))

    f, _ = check_report(GOOD_CODE, "docs")
    check("kind=docs 但缺检查清单表 → error", any("缺 N4.5" in d for lv, d in f if lv == "error"), str(f))

    # 占位符 '-' 也算空
    f, _ = check_report("""# 表 A：覆盖表
| 需求 | 判定 | 代码锚点 | 验证方式 |
|---|---|---|---|
| R2-1 | ✅ 已实现 | - | 跑了 |
""", "auto")
    check("锚点写 '-' 视同空 → error", any("代码锚点" in d for lv, d in f if lv == "error"), str(f))

    # ---- 锚点核对：格子非空 ≠ 锚点是真的（2026-09-23 selfopt 实证）----
    import shutil as _sh
    import tempfile as _tf
    troot = _tf.mkdtemp()
    try:
        os.makedirs(os.path.join(troot, "pkg"), exist_ok=True)
        with open(os.path.join(troot, "pkg", "real.py"), "w", encoding="utf-8") as fh:
            fh.write("def real_fn():\n    return 1\n")

        tpl = ("# 表 A：覆盖表\n"
               "| 需求 | 判定 | 代码锚点 | 验证方式 |\n"
               "|---|---|---|---|\n"
               "| R2-1 | ✅ 已实现 | `%s` def real_fn() | 跑了 |\n")

        f, _ = check_report(tpl % "pkg/real.py:1", "auto", troot)
        check("锚点真实存在 → 无 error", not [x for x in f if x[0] == "error"], str(f))

        f, _ = check_report(tpl % "pkg/nope.py:1", "auto", troot)
        check("锚点文件不存在 → error", any("不存在" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_report(tpl % "pkg/real.py:999", "auto", troot)
        check("锚点行号越界 → error", any("越界" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_report(tpl % "pkg/real.py:1", "auto", None)
        check("不给项目根目录 → 跳过锚点核对（不误报）",
              not [x for x in f if x[0] == "error"], str(f))
    finally:
        _sh.rmtree(troot, ignore_errors=True)

    print("=== 自测（verify_audit_report）===")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            fail += 1
            print(f"      ← {detail[:200]}")
        else:
            pass_ += 1
    print(f"\n通过 {pass_}/{len(results)}")
    return 1 if fail else 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="verify_audit_report.py",
        description="校验审计表证据完整性：锚点列 / 验证列为空即拒收（publish-code-audit.md §三）")
    ap.add_argument("report", nargs="?", help="审计报告文件（audit-code.md / audit-docs.md）")
    ap.add_argument("--kind", choices=["auto", "code", "docs"], default="auto",
                    help="code=必须三表齐全；docs=必须有 N4.5 检查清单；auto=按文件名推断")
    ap.add_argument("--project", default=None,
                    help="项目根目录（用于核对锚点里的文件是否真存在）。"
                         "默认从报告路径推断：报告在 <项目>/.publish-staging/ 下时自动取 <项目>")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args(argv)

    if args.test:
        return run_test()
    if not args.report:
        ap.print_help()
        return 2
    if not os.path.isfile(args.report):
        print(f"ERROR: 找不到报告文件：{args.report}", file=sys.stderr)
        return 2

    kind = args.kind
    if kind == "auto":
        base = os.path.basename(args.report).lower()
        if "audit-code" in base:
            kind = "code"
        elif "audit-docs" in base:
            kind = "docs"

    root = args.project
    if not root:
        d = os.path.dirname(os.path.abspath(args.report))
        if os.path.basename(d) == ".publish-staging":
            root = os.path.dirname(d)

    text = open(args.report, encoding="utf-8").read()
    findings, tables = check_report(text, kind, root)
    errors = [d for lv, d in findings if lv == "error"]
    warns = [d for lv, d in findings if lv == "warn"]

    if args.as_json:
        print(json.dumps({"ok": not errors, "kind": kind, "project": root,
                          "tables": len(tables), "errors": errors,
                          "warnings": warns}, ensure_ascii=False))
        return 1 if errors else 0

    print(f"审计报告校验：{args.report}（kind={kind}）")
    print(f"  表 {len(tables)} 张" + (f"；锚点核对根目录 {root}" if root else "；未给项目根目录 → 跳过锚点核对"))
    for lv, d in findings:
        print(f"  {'🔴' if lv == 'error' else '⚠️ '} {d}")
    print()
    if errors:
        print(f"❌ 拒收：{len(errors)} 项证据不完整。空证据行 / 假锚点 = 无效判定，修好后重跑。")
        return 1
    print(f"✅ 通过：证据列无空缺、锚点均可解析（告警 {len(warns)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
