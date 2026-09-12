#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quality_metrics.py — 发布物质量的「客观代理指标」

定位（别越界）：
    它只算**可机器算的那半边**——数字、位置、比例、残留词。
    它给不出「好不好」的最终结论，那是独立判定者的活（主观分 0-5）。
    它存在的意义是：判定者想在主观分上松一点时，客观数字把它顶住。

用法：
    python3 quality_metrics.py <项目目录>
    python3 quality_metrics.py --file README.md <项目目录>
    python3 quality_metrics.py --test

输出：JSON 到 stdout，并写入 <项目>/.publish-staging/quality-metrics.json
"""

import argparse
import json
import os
import re
import sys
import tempfile
import shutil

PASS_LINE = 3.0          # 客观分下限，与 publish_flow.py 的 N2/N4 min_score 对齐

FIRST_SCREEN_LINES = 30  # 真实用户在首屏看到的内容量

RE_NUM = re.compile(r"\d")
RE_ACTION = re.compile(
    r"安装|装好|用法|使用方法|快速开始|上手|三步|install|usage|quick ?start|getting started",
    re.I)
RE_ARCH = re.compile(r"架构|architecture|设计模式|模块划分|分层|技术原理|实现原理", re.I)
RE_YOU = re.compile(r"你|您|\byou\b|\byour\b", re.I)
RE_WE = re.compile(r"我们|本系统|本公司|本项目|\bwe\b|\bour\b", re.I)
RE_CODE = re.compile(r"```|\$ |^\s{0,4}[a-z_]+ --?[a-z]")
RE_DEVLOG = re.compile(r"TODO|FIXME|变更日志|CHANGELOG|开发日志|调试|debug|未完成|待办", re.I)
RE_MATH = re.compile(r"\$\$|\\frac|\\sum|\\int|推导|引理|证明过程")
RE_USAGE_HEAD = re.compile(
    r"^#{1,4}\s*(用法|使用方法|快速开始|怎么用|安装与用法|启动路由|路由|入口|"
    r"usage|quick ?start)", re.I)

README_RULES = [
    ("首屏出现数字（可信的量化信息）", 1.0,
     lambda t, f: (1.0 if RE_NUM.search(f) else 0.0,
                   "前 %d 行%s数字" % (FIRST_SCREEN_LINES,
                                   "含" if RE_NUM.search(f) else "无"))),
    ("首屏有行动词（装了/怎么用）", 0.9,
     lambda t, f: (1.0 if RE_ACTION.search(f) else 0.0,
                   "安装/用法类词%s" % ("命中" if RE_ACTION.search(f) else "未命中"))),
    ("首屏主语是「你」不是「我们」", 0.9,
     lambda t, f: (1.0 if len(RE_YOU.findall(f)) > len(RE_WE.findall(f)) else 0.0,
                   "你/您 %d 次 vs 我们/本系统 %d 次"
                   % (len(RE_YOU.findall(f)), len(RE_WE.findall(f))))),
    ("首屏不是架构讲解", 0.6,
     lambda t, f: (0.0 if (RE_ARCH.search(f) and not RE_ACTION.search(f)) else 1.0,
                   "架构词 %d 个" % len(RE_ARCH.findall(f)))),
    ("有可复制的命令块", 0.5,
     lambda t, f: (1.0 if RE_CODE.search(t) else 0.0, "含代码块或命令行")),
    ("首屏长度适中（200-1500 字）", 0.5,
     lambda t, f: (1.0 if 200 <= len(f) <= 1500 else 0.0, "首屏 %d 字" % len(f))),
]

SKILL_RULES = [
    ("frontmatter 齐（name + description）", 1.0, None),
    ("用法出现在前 1/3", 1.2, None),
    ("触发词 ≥5 个", 0.8, None),
    ("无开发日志残留", 0.8,
     lambda t, f: (0.0 if RE_DEVLOG.search(t) else 1.0,
                   "残留 %d 处" % len(RE_DEVLOG.findall(t)))),
    ("不是数学推导开篇", 0.6,
     lambda t, f: (0.0 if RE_MATH.search(f) else 1.0, "首屏公式密度")),
]


def read_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def frontmatter(lines):
    """取 --- 之间的字段名集合"""
    if not lines or lines[0].strip() != "---":
        return set(), 0
    keys = set()
    end = 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:", lines[i])
        if m:
            keys.add(m.group(1))
    return keys, end


def count_triggers(lines):
    for line in lines:
        if "触发词" in line:
            tail = line.split("触发词", 1)[1]
            parts = [p for p in re.split(r"[、，,;；\s]+", tail) if p.strip()]
            return len(parts)
    return 0


def score_readme(lines):
    text = "\n".join(lines)
    first = "\n".join(lines[:FIRST_SCREEN_LINES])
    rows, num, den = [], 0.0, 0.0
    for name, w, fn in README_RULES:
        v, note = fn(text, first)
        rows.append({"check": name, "weight": w, "value": round(v, 2), "note": note})
        num += w * v
        den += w
    return round(5.0 * num / den, 2), rows


def score_skill(lines):
    keys, fm_end = frontmatter(lines)
    total = max(len(lines), 1)
    text = "\n".join(lines)
    first = "\n".join(lines[:FIRST_SCREEN_LINES])

    usage_line = None
    for i in range(fm_end + 1, len(lines)):
        if RE_USAGE_HEAD.search(lines[i]):
            usage_line = i
            break
    usage_ratio = (usage_line / total) if usage_line is not None else 1.0
    triggers = count_triggers(lines)
    fm_ok = 1.0 if {"name", "description"} <= keys else 0.0

    rows, num, den = [], 0.0, 0.0
    for name, w, fn in SKILL_RULES:
        if fn is not None:
            v, note = fn(text, first)
        elif name.startswith("frontmatter"):
            v, note = fm_ok, "找到字段 %s" % ",".join(sorted(keys)) if keys else "无 frontmatter"
        elif name.startswith("用法"):
            v, note = (1.0 if usage_ratio < 1 / 3 else 0.0), \
                      ("用法在第 %s 行 / 共 %d 行（%.0f%%）"
                       % (usage_line, total, usage_ratio * 100) if usage_line is not None
                       else "未找到用法章节")
        else:
            v, note = (1.0 if triggers >= 5 else 0.0), "触发词 %d 个" % triggers
        rows.append({"check": name, "weight": w, "value": round(v, 2), "note": note})
        num += w * v
        den += w
    return round(5.0 * num / den, 2), rows


def analyze(project, only=None):
    targets = []
    if only:
        targets = [(only, os.path.join(project, only))]
    else:
        for fn in ("README.md", "SKILL.md"):
            p = os.path.join(project, fn)
            if os.path.exists(p):
                targets.append((fn, p))

    out = {"project": os.path.abspath(project), "pass_line": PASS_LINE, "files": {}}
    for name, path in targets:
        lines = read_lines(path)
        if name.lower().startswith("readme"):
            score, rows = score_readme(lines)
        else:
            score, rows = score_skill(lines)
        out["files"][name] = {
            "score": score,
            "pass": score >= PASS_LINE,
            "lines": len(lines),
            "checks": rows,
        }
    if out["files"]:
        out["min_score"] = min(v["score"] for v in out["files"].values())
        out["pass"] = out["min_score"] >= PASS_LINE
    else:
        out["min_score"] = None
        out["pass"] = False
    return out


def write_report(project, data):
    d = os.path.join(project, ".publish-staging")
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(os.path.join(d, "quality-metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------- 自检
GOOD_README = """# no-bb

给你的一条命令，让模型说完就停。

## 安装

```
pip install no-bb
```

装上以后，你的对话会自动被拼上一句约束。实测思考量 -33%~-51%，响应最高 -47%。

## 用法

把 base_url 指过来就行。

```
export NOBB=1
```

## 为什么

（原理放在后面，不占首屏。）
""" + "\n".join(["细节行 %d" % i for i in range(40)])

BAD_README = """# x

本系统采用三层架构设计，模块划分为 ingest / distill / recall 三层。
我们实现了完整的解耦，通过事件总线通信，架构清晰。

""" + "\n".join(["更多架构描述 %d" % i for i in range(40)])

GOOD_SKILL = """---
name: demo
description: 做某件事。触发词：发布skill、推到github、检查反馈、下载量、配置通知
---

# demo

## 用法

就这样用。

## 原理

后面才讲。
"""

BAD_SKILL = """---
name: demo
---

# demo

## 数学推导

$$E = mc^2$$

## 原理

推导过程如下。

## 用法

TODO 还没写

""" + "\n".join(["填充 %d" % i for i in range(40)])


def run_test():
    tmp = tempfile.mkdtemp(prefix="qm-test-")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    try:
        cases = [
            ("good", GOOD_README, GOOD_SKILL),
            ("bad", BAD_README, BAD_SKILL),
        ]
        scores = {}
        for tag, rd, sk in cases:
            p = os.path.join(tmp, tag)
            os.makedirs(p)
            with open(os.path.join(p, "README.md"), "w", encoding="utf-8") as fh:
                fh.write(rd)
            with open(os.path.join(p, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write(sk)
            data = analyze(p)
            scores[tag] = data
            write_report(p, data)

        g, b = scores["good"], scores["bad"]
        check("好 README 分数 > 坏 README",
              g["files"]["README.md"]["score"] > b["files"]["README.md"]["score"],
              "%.2f vs %.2f" % (g["files"]["README.md"]["score"], b["files"]["README.md"]["score"]))
        check("好 SKILL 分数 > 坏 SKILL",
              g["files"]["SKILL.md"]["score"] > b["files"]["SKILL.md"]["score"],
              "%.2f vs %.2f" % (g["files"]["SKILL.md"]["score"], b["files"]["SKILL.md"]["score"]))
        check("好样本整体 pass", g["pass"] is True, "min=%.2f" % g["min_score"])
        check("坏样本整体 fail", b["pass"] is False, "min=%.2f" % b["min_score"])
        check("报告落盘", os.path.exists(os.path.join(tmp, "good", ".publish-staging", "quality-metrics.json")))
        check("触发词被计数",
              any("触发词" in r["note"] for r in g["files"]["SKILL.md"]["checks"]), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("quality_metrics.py 自检 —— %d 项" % len(results))
    bad = 0
    for name, ok, detail in results:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   ← " + detail) if (detail and not ok) else ""))
        if not ok:
            bad += 1
    print("结果：%d 通过 / %d 失败" % (len(results) - bad, bad))
    if bad:
        print("自检未通过。")
        return 1
    print("自检通过：客观指标能区分好样本与坏样本。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quality_metrics.py",
                                 description="发布物质量的客观代理指标")
    ap.add_argument("project", nargs="?", default=os.getcwd())
    ap.add_argument("--file", default=None, help="只算某一个文件，如 README.md")
    ap.add_argument("--test", action="store_true", help="跑内置自检")
    args = ap.parse_args(argv)

    if args.test:
        return run_test()

    if not os.path.isdir(args.project):
        sys.stderr.write("ERROR: 目录不存在：%s\n" % args.project)
        return 1

    data = analyze(args.project, only=args.file)
    write_report(args.project, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("pass") else 2


if __name__ == "__main__":
    sys.exit(main())
