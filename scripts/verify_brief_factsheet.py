#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_brief_factsheet.py — requirement-brief.md 结构校验 + 与 fact-sheet.md 的联动校验

用途：
  N0.2 节点产出 requirement-brief.md 后，本脚本做两件事：
  ① 结构校验（机器可靠，对应 N0.2 准出 / .publish-state.json 的 N0.2.evidence）：
       - R1–R5 五节齐全
       - R4「已否决」非空（rejected_section_nonempty）
       - 至少 1 处老高原话 blockquote（has_quotes）
  ② 与 fact-sheet.md 的联动校验（N1 签字前置：两张纸必须对得上）：
       - 🔴 硬矛盾：R3/R4 条目原话作为「能力」出现在事实表能力清单 → 拒绝签字（exit 1）
       - 🟡 覆盖缺口：R2 在事实表能力清单找不到对应
       - 🟡 禁区未登记：R3 在事实表「禁用词」找不到对应
       - 🟡 否决泄漏：R4 出现在事实表能力描述

设计纪律（与 verify_ledger / trace_callchain 同源）：
  - 查得出的结论才下判；查不出的一律报「需人工确认」（🟡），绝不替人判「你错了」。
  - 只对「清清楚楚的文本矛盾」和「N0.2 结构硬规则」才 exit 1 拦签字；
    其余启发式一律 🟡 + exit 0，交人眼。诬告比不查更糟。

退出码：
  0 = 结构过 + 无 🔴（可能有 🟡，交人看）
  1 = 结构不过（无 R4 / 无原话）或发现 🔴 硬矛盾（两张纸对不上）

用法：
  python3 verify_brief_factsheet.py --brief requirement-brief.md [--factsheet fact-sheet.md]
  python3 verify_brief_factsheet.py --test        # 自测
"""

import argparse
import os
import re
import sys
import tempfile


# ---- 中文常见停用词（用于覆盖缺口判定的降噪） ----
STOPWORDS = set(
    "功能 支持 提供 可以 这个 一个 我们 他们 需要 应该 必须 实现 代码 文件 使用 "
    "用户 项目 系统 数据 进行 以及 并且 通过 对于 基于 方式 方法 东西 内容 情况 "
    "部分 其他 一些 这些 那些 是否 存在 生成 处理 检查 命令 脚本 工具 能力 特性 "
    "能够 用来 用于 自动 相关 各种 多个 直接 简单 方便 要求 需求 东西 事情 问题 "
    "做到 该 该当 时候 一种 这样 那样 没有 不是 就是 因为 所以 但是 如果 而且 "
    "这个 那个".split()
)

NEG_PREFIXES = ("不要", "别", "禁止", "不得", "不允许", "避免", "切勿", "不许", "不可")


class Finding:
    def __init__(self, severity, code, message, detail=""):
        self.severity = severity  # "🔴" / "🟡" / "ℹ️"
        self.code = code
        self.message = message
        self.detail = detail

    def render(self):
        d = f"  ↳ {self.detail}" if self.detail else ""
        return f"{self.severity} [{self.code}] {self.message}{d}"


# ----------------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------------

def _split_sections(text):
    """返回 {heading_title_lower_stripped: body_text}，仅按 '## ' 切。"""
    sections = {}
    cur = None
    buf = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            if cur is not None:
                buf.append(line)
            continue
        m = re.match(r"^##\s+(.*)$", line)
        if m and not in_fence:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1).strip()
            buf = []
        else:
            if cur is not None:
                buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections


def _strip_fences(text):
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _count_quotes(text):
    """统计「老高原话」锚点数：即中文引号对「...」的数量（代码块外的 R1/R2/R3 原话）。
    注意：模板自带的「> 来源：...」说明 blockquote 不含「」对，不计入，
    避免让 has_quotes 永远为真。"""
    clean = _strip_fences(text)
    return len(re.findall(r"「[^」\n]+」", clean))


def _parse_table_rows(section_body):
    """返回 markdown 表格的数据行（去表头、去分隔行），每行按 '|' 切分并去空白。"""
    rows = []
    for ln in section_body.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        if re.match(r"^\|[\s:|-]+\|$", s):  # 分隔行
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and cells[0] in ("#", "编号"):  # 表头
            continue
        rows.append(cells)
    return rows


def _parse_r4_list(section_body):
    """R4 已否决区：提取 bullet 项文本（去引号、去「提出过/未采纳」等废话）。"""
    items = []
    for ln in section_body.splitlines():
        s = ln.strip()
        if s.startswith("-") or s.startswith("*"):
            t = s.lstrip("-*").strip().strip("`").strip()
            # 去掉形如 「xxx」——提出过，未采纳，不算需求 的尾部
            t = re.split(r"[—–-]", t)[0].strip().strip("「」\"'")
            if t:
                items.append(t)
    return items


def _find_capability_lines(factsheet_text):
    """抽取事实表里「能力/功能/支持/特性」清单的条目行（bullet 或表格行）。"""
    sections = _split_sections(factsheet_text)
    cap_lines = []
    cap_head_re = re.compile(r"能力|功能|支持|特性|capabilit|能做", re.I)
    for title, body in sections.items():
        if cap_head_re.search(title):
            for ln in body.splitlines():
                s = ln.strip()
                if s.startswith("|"):
                    cells = [c.strip() for c in s.strip("|").split("|")]
                    cap_lines.extend([c for c in cells if len(c) >= 2])
                elif s.startswith("-") or s.startswith("*"):
                    cap_lines.append(s.lstrip("-*").strip())
                elif len(s) >= 2 and not s.startswith("#"):
                    cap_lines.append(s)
    # 去重
    seen, out = set(), []
    for c in cap_lines:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _find_field_lines(factsheet_text, *keywords):
    """抽取标题含 keyword 的 section body 行。"""
    sections = _split_sections(factsheet_text)
    out = []
    for title, body in sections.items():
        if any(k in title for k in keywords):
            for ln in body.splitlines():
                s = ln.strip()
                if s.startswith("-") or s.startswith("*"):
                    out.append(s.lstrip("-*").strip())
                elif s.startswith("|"):
                    cells = [c.strip() for c in s.strip("|").split("|")]
                    out.extend([c for c in cells if len(c) >= 2])
    return out


def _strip_neg(text):
    t = text.strip().strip("「」\"'")
    for p in NEG_PREFIXES:
        if t.startswith(p):
            t = t[len(p):].strip()
    return t


def _has_meaningful_overlap(a, b, min_len=2):
    """a、b 是否有非停用词的公共子串（滑窗）。用于覆盖缺口/禁区登记判定。"""
    a = _strip_neg(a)
    if len(a) < min_len:
        return False
    for i in range(len(a) - min_len + 1):
        sub = a[i:i + min_len]
        if sub in STOPWORDS:
            continue
        if sub in b:
            return True
    return False


def _subject_in_capability(subject, cap_lines):
    """subject（已去否定前缀）是否与某条能力行有「非停用词、≥3 字」的公共片段。
    返回命中的能力行或 None。用于抓「明确不要却写成能力」的硬矛盾。
    min_len=3 + 停用词过滤，避免「功能/数字」这类泛词误报。"""
    subj = _strip_neg(subject)
    if len(subj) < 2:
        return None
    for cl in cap_lines:
        if _has_meaningful_overlap(subj, cl, min_len=3):
            return cl
    return None


# ----------------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------------

def check_structure(brief_text):
    findings = []
    sections = _split_sections(brief_text)
    # R1–R5 齐全（标题里含 R1..R5 即可，允许中文后缀）
    present = set()
    for title in sections:
        m = re.match(r"R([1-5])\b", title)
        if m:
            present.add("R" + m.group(1))
    for r in ("R1", "R2", "R3", "R4", "R5"):
        if r not in present:
            findings.append(Finding("🔴", "STRUCT_MISSING_" + r,
                                     f"缺 {r} 节", "N0.2 五节必须齐全"))
    # R4 非空
    r4_body = sections.get("R4 已否决（审计禁止据此判定）", "")
    r4_items = _parse_r4_list(r4_body)
    if not r4_items:
        findings.append(Finding("🔴", "STRUCT_R4_EMPTY",
                                 "R4「已否决」为空",
                                 "N0.2 准出要求 rejected_section_nonempty=true；空=没翻聊天，审计会拿废案当需求"))
    # 老高原话锚点
    nq = _count_quotes(brief_text)
    if nq == 0:
        findings.append(Finding("🔴", "STRUCT_NO_QUOTE",
                                 "无任何老高原话 blockquote（>）",
                                 "N0.2 准出要求 has_quotes=true；每条需求须附原话"))
    # R5 签字块（仅 WARN：签字是 N1 动作，可暂不填）
    if "signed_by" not in brief_text or "confirmed_at" not in brief_text:
        findings.append(Finding("🟡", "STRUCT_R5_UNSIGNED",
                                 "R5 签字块缺 signed_by / confirmed_at",
                                 "签字在 N1 与事实表同批做；此处先提示"))
    return findings


def check_linkage(brief_text, factsheet_text):
    findings = []
    sections = _split_sections(brief_text)
    cap_lines = _find_capability_lines(factsheet_text)
    ban_lines = _find_field_lines(factsheet_text, "禁用词", "不写", "禁区", "不要写")

    # R2 覆盖
    r2_rows = _parse_table_rows(sections.get("R2 必须做到", ""))
    r2_unmatched = []
    for cells in r2_rows:
        if len(cells) < 2:
            continue
        req = cells[1]
        if not req or req in ("需求",):
            continue
        if cap_lines and not any(_has_meaningful_overlap(req, cl) for cl in cap_lines):
            r2_unmatched.append(req)
    if r2_unmatched:
        findings.append(Finding("🟡", "LINK_R2_GAP",
                                 f"{len(r2_unmatched)} 条 R2 在事实表能力清单找不到对应（覆盖缺口）",
                                 "；".join(r2_unmatched[:3]) + ("…" if len(r2_unmatched) > 3 else "")))

    # R3 明确不要
    r3_rows = _parse_table_rows(sections.get("R3 明确不要（禁区）", ""))
    r3_unregistered = []
    r3_contra = []
    for cells in r3_rows:
        if len(cells) < 2:
            continue
        item = cells[1]
        if not item or item in ("不要什么",):
            continue
        # 硬矛盾：R3 作为能力出现在事实表
        hit = _subject_in_capability(item, cap_lines)
        if hit:
            r3_contra.append((item, hit))
            continue
        # 禁区未登记进禁用词
        if ban_lines and not any(_has_meaningful_overlap(item, bl) for bl in ban_lines):
            r3_unregistered.append(item)
    if r3_contra:
        for item, hit in r3_contra:
            findings.append(Finding("🔴", "LINK_R3_CONTRA",
                                     "R3 明确不要却作为能力出现在事实表 → 两张纸对不上，拒绝签字",
                                     f"R3「{item}」↔ 事实表能力行「{hit}」"))
    if r3_unregistered:
        findings.append(Finding("🟡", "LINK_R3_UNREG",
                                 f"{len(r3_unregistered)} 条 R3 未在事实表「禁用词」登记",
                                 "；".join(r3_unregistered[:3]) + ("…" if len(r3_unregistered) > 3 else "")))

    # R4 已否决泄漏
    r4_items = _parse_r4_list(sections.get("R4 已否决（审计禁止据此判定）", ""))
    r4_leak = []
    for item in r4_items:
        hit = _subject_in_capability(item, cap_lines)
        if hit:
            r4_leak.append((item, hit))
    if r4_leak:
        for item, hit in r4_leak:
            findings.append(Finding("🟡", "LINK_R4_LEAK",
                                     "R4 已否决条目出现在事实表能力描述（否决泄漏）",
                                     f"R4「{item}」↔ 事实表「{hit}」"))

    # 事实表必备字段（仅 WARN）
    missing = [f for f in ("一句话定位", "收益数字", "禁用词", "痛点场景")
               if f not in factsheet_text]
    if missing:
        findings.append(Finding("🟡", "FSHEET_MISSING_FIELDS",
                                 f"事实表缺必备字段：{', '.join(missing)}",
                                 "N1 事实表应含 一句话定位/收益数字(framing)/禁用词/痛点场景"))
    return findings


def run(brief_path, factsheet_path=None):
    if not os.path.exists(brief_path):
        print(f"🔴 [STRUCT_NO_FILE] requirement-brief.md 不存在：{brief_path}")
        return 1
    brief_text = open(brief_path, encoding="utf-8").read()
    findings = check_structure(brief_text)
    if factsheet_path:
        if not os.path.exists(factsheet_path):
            findings.append(Finding("🟡", "FSHEET_NO_FILE",
                                     f"事实表不存在：{factsheet_path}", "仅做结构校验"))
        else:
            fs_text = open(factsheet_path, encoding="utf-8").read()
            findings += check_linkage(brief_text, fs_text)

    print(f"=== verify_brief_factsheet: {os.path.basename(brief_path)}"
          + (f" ↔ {os.path.basename(factsheet_path)}" if factsheet_path else " (仅结构)") + " ===")
    if not findings:
        print("ℹ️  无问题。")
    else:
        for f in findings:
            print(f.render())
    has_block = any(f.severity == "🔴" for f in findings)
    print(f"--- 结论：{'🔴 存在硬问题，拒绝签字 / N0.2 不过' if has_block else '🟢 结构过，无硬矛盾（🟡 项交人眼）'} ---")
    return 1 if has_block else 0


# ----------------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------------

def _selftest():
    failures = []

    def make_brief(r4="", quotes=True, r3=None, r2=None, r5=True):
        q = '> 老高原话：「就 B」——AI 自优化方向\n' if quotes else ""
        r3_rows = r3 or "| 1 | 不要吹收益数字 | 「中位 1.5x 是假的」 |"
        r2_rows = r2 or "| 1 | 扫描本地项目找热点 | 「改完先不发布」 | 会话 |"
        r5 = ("\nsigned_by: 老高\nconfirmed_at: ____\n" if r5 else "")
        body = f"""# 需求清单
> 来源：测试会话。
{q}
## R1 一句话要什么
> 老高原话：「就 B」

## R2 必须做到
| # | 需求 | 老高原话 | 出处 |
|---|---|---|---|
{r2_rows}

## R3 明确不要（禁区）
| # | 不要什么 | 老高原话 |
|---|---|---|
{r3_rows}

## R4 已否决（审计禁止据此判定）
{r4}

## R5 老高对这份清单的确认
{r5}"""
        if not quotes:  # 真·无原话：去掉所有「」对，模拟没附老高原话
            body = re.sub(r"「[^」\n]*」", "", body)
        return body

    def make_fsheet(cap=None, ban=None, fields=True):
        cap = cap or "- 扫描本地项目找热点并给出建议"
        ban = ban or "- 不吹收益数字"
        f = "" if fields else "随便写写"
        return f"""# 事实表
## 一句话定位
AI 自优化方向工具

## 收益数字
实测加速比（带 evidence/block/bound 标注）

## 禁用词
{ban}

## 痛点场景
昨天不知道怎么给大模型说

## 能力清单
{cap}
{f}"""

    # T1: 正常对齐 → exit 0
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        fp = os.path.join(d, "fs.md")
        open(bp, "w", encoding="utf-8").write(make_brief(r4='- 「给 selfopt 补 CLI」——提出过，未采纳'))
        open(fp, "w", encoding="utf-8").write(make_fsheet())
        rc = run(bp, fp)
        if rc != 0:
            failures.append(f"T1 正常对齐应 exit 0，实际 {rc}")

    # T2: R4 为空 → exit 1
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        open(bp, "w", encoding="utf-8").write(make_brief(r4=""))
        rc = run(bp)
        if rc != 1:
            failures.append(f"T2 R4 空应 exit 1，实际 {rc}")

    # T3: 无原话 → exit 1
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        open(bp, "w", encoding="utf-8").write(make_brief(r4='- 「CLI」未采纳', quotes=False))
        rc = run(bp)
        if rc != 1:
            failures.append(f"T3 无原话应 exit 1，实际 {rc}")

    # T4: R3 硬矛盾（不要吹收益数字，事实表能力写「提供收益数字对比」）→ exit 1
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        fp = os.path.join(d, "fs.md")
        open(bp, "w", encoding="utf-8").write(make_brief(
            r4='- 「CLI」未采纳',
            r3="| 1 | 不要吹收益数字 | 「中位 1.5x 是假的」 |"))
        open(fp, "w", encoding="utf-8").write(make_fsheet(
            cap="- 提供收益数字对比功能"))
        rc = run(bp, fp)
        if rc != 1:
            failures.append(f"T4 R3 硬矛盾应 exit 1，实际 {rc}")

    # T5: R2 覆盖缺口 + R3 禁区未登记 → exit 0（仅 🟡）
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        fp = os.path.join(d, "fs.md")
        open(bp, "w", encoding="utf-8").write(make_brief(
            r4='- 「CLI」未采纳',
            r2="| 1 | 扫描本地项目找热点并自动修复 | 「改完先不发布」 | 会话 |",
            r3="| 1 | 不要暴露内部路径 | 「内部路径不能写」 |"))
        open(fp, "w", encoding="utf-8").write(make_fsheet(
            cap="- 扫描本地项目找热点", ban="- 不吹收益数字"))
        rc = run(bp, fp)
        if rc != 0:
            failures.append(f"T5 仅 🟡 应 exit 0，实际 {rc}")

    # T6: 事实表缺字段 → exit 0（仅 🟡）
    with tempfile.TemporaryDirectory() as d:
        bp = os.path.join(d, "brief.md")
        fp = os.path.join(d, "fs.md")
        open(bp, "w", encoding="utf-8").write(make_brief(r4='- 「CLI」未采纳'))
        open(fp, "w", encoding="utf-8").write(make_fsheet(fields=False))
        rc = run(bp, fp)
        if rc != 0:
            failures.append(f"T6 事实表缺字段应 exit 0（🟡），实际 {rc}")

    print(f"\n自测：{'全部通过 ✅' if not failures else '有失败 ❌'}")
    for f in failures:
        print("  - " + f)
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="requirement-brief 结构 + 与 fact-sheet 联动校验")
    ap.add_argument("--brief", help="requirement-brief.md 路径")
    ap.add_argument("--factsheet", help="fact-sheet.md 路径（可选；不传则仅结构校验）")
    ap.add_argument("--test", action="store_true", help="跑自测")
    args = ap.parse_args()
    if args.test:
        return _selftest()
    if not args.brief:
        ap.error("必须提供 --brief（或 --test）")
    return run(args.brief, args.factsheet)


if __name__ == "__main__":
    sys.exit(main())
