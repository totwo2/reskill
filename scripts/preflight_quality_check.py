#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight_quality_check.py —— 发布物质量闸门（内容层）

=============================================================================
【设计笔记 · 写码前必写（R-BORROW-NOT-COPY）】
-----------------------------------------------------------------------------
1. 解决什么问题
   已发布的 20 个东西，"代码能用"但"包在外面那一层"一塌糊涂：
   README 用数学公式开篇、SKILL.md 前 110 行原理才见到用法、
   frontmatter 没有 description、GitHub topics 为 0。
   本脚本把 `publish-quality.md` 里**可机器判定的规则**变成 exit code，
   让"发布物不合格"从事后感觉变成事前硬拦。

2. 核心机制
   两个 profile（github / skillhub）分别套不同规则集：
     - github:  README 为主页，查"前 30 行有没有数字收益 / 中英逐段对照 / topics 两组词"
     - skillhub: SKILL.md 为入口，查"frontmatter 完整性 / 触发词 / 用法位置 / 开发日志与数学推导"
   可机器判的一律 exit code；**判不了"好不好"的（钩子打动人吗、数字可信吗）
   一律标 [LLM评]，不假装能判**——脚本只管形式，语义交给裁判 LLM。

3. 我的适配点
   - 规则原文出自本 skill 自带的 ../publish-quality.md，不自行发明
   - 老高不读代码（R-NOCODE）→ 自带 --test，一条命令自证，输出说人话
   - 平台元数据（topics/description）本地拿不到 → 支持 --topics / --meta 传入，
     没传就标 [缺数据] 而不是误判为 FAIL
   - 阈值与词表集中在文件顶部 CONFIG，改哪儿一目了然
=============================================================================

用法:
    python3 preflight_quality_check.py --dir <项目目录> --platform github
    python3 preflight_quality_check.py --dir <目录> --platform skillhub
    python3 preflight_quality_check.py --dir <目录> --platform github --topics "ai,llm,python"
    python3 preflight_quality_check.py --test          # 自检，验证规则本身对不对

退出码:
    0 = 通过（可能有 WARN）
    1 = 有 FAIL（一票否决项未过 → 不许发布）
    2 = 用法错误
"""

import argparse
import os
import re
import sys

# =============================================================================
# CONFIG —— 所有阈值与词表集中在这里，改规则只改这一块
# =============================================================================

# 实现黑话词：description 里出现这些 = 站在开发者视角，不是用户视角
IMPL_JARGON = [
    "hook", "旁路", "注入", "闸门", "架构", "中间层", "证人集", "中间件",
    "frontmatter", "pipeline", "dispatcher", "registry", "回调", "callback",
    "agent harness", "编排", "orchestrat", "handoff", "双库制",
]

# 效果作用词：topics 里至少要有这些，才说明照顾到"被痛点扎到的人"
#
# ⚠️ 这张表是**通用默认值**，不是硬指标。它只回答「有没有一个效果类词」，
#    不回答「这个词有没有人搜」——后者由 scripts/check_discoverability.py 量真实搜索池。
#    领域不同效果词也不同，可用 --effect-words 覆盖（如发布工具关心的是省事/少出错，
#    不是 token/latency）。曾经这张表只写了另一个项目（省 token）的词，对发布工具是空的。
EFFECT_WORDS = [
    # 性能 / 成本类
    "token-optimization", "token", "latency", "cost-optimization", "cost",
    "performance", "speed", "提速", "优化", "加速", "saving", "efficiency",
    # 自动化 / 效率类
    "自动化", "automation", "productivity", "workflow-automation",
    "developer-productivity", "time-saving", "one-click",
    # 质量 / 可靠类
    "code-quality", "quality-assurance", "best-practices", "reliability",
    # 发布 / 交付类
    "publishing", "release", "delivery", "ci-cd", "deployment",
]


def set_effect_words(extra):
    """追加效果作用词（--effect-words）。只加不减，避免把默认表误删成空表。"""
    global EFFECT_WORDS
    EFFECT_WORDS = list(EFFECT_WORDS) + [w.strip().lower() for w in extra.split(",") if w.strip()]


# 开发日志特征词（SKILL.md 禁写）
DEVLOG_PATTERNS = [
    r"第\s*\d+\s*轮", r"曾误判", r"回滚", r"历史教训", r"之前的版本",
    r"v\d+\.\d+\s*之前", r"踩坑", r"当时以为",
]

# 数学推导特征词（SKILL.md 禁写，该放 docs/）
MATH_PATTERNS = [
    r"sign\s*test", r"p\s*<\s*0\.\d+", r"显著性", r"零一完备", r"定理",
    r"证明过程", r"符号检验", r"中位数加速比",
]

# 数字收益正则（README 前 30 行必须有）
NUMBER_RE = re.compile(
    r"(\d+\s*%|\d+\s*倍|\d+\s*x\b|\d+\.\d+\s*s\s*→|\d+\s*/\s*\d+\s*→|-\d+\s*%)",
    re.IGNORECASE,
)

MIN_TOPICS = 10          # GitHub 侧 topics 下限（publish-quality.md：15~20，10 为及格线）
README_HEAD_LINES = 30   # "前 30 行有数字" 的判定窗口
USAGE_MAX_RATIO = 0.33   # SKILL.md 用法章节必须出现在前 1/3
USAGE_ABS_MAX_LINES = 40 # 绝对值下限：短文档（<40 行）不按比例算——
                         # 自检时发现：11 行的文档用法在第 5 行=45%，但完全合理。
                         # 真问题是"读 40 行还找不到怎么用"，不是比例。

# 用法章节的标题特征
# 2026-09-12 修正：原先只有"用法/安装/使用"，对 no-bb 的"## 两种接入方式"误报 FAIL。
# 好样本被误报 = 规则不可信，故按真实语料扩词。
USAGE_HEADING_RE = re.compile(
    r"^#{1,4}\s*.{0,8}("   # 允许 8 字以内修饰词："两种接入方式"、"方案 A 安装" 都要能命中
    r"用法|如何使用|怎么用|快速开始|上手|开始使用|getting\s*started|"
    r"quick\s*start|usage|装/用|安装|使用|接入|如何接入|配置|部署|"
    r"install|setup"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


# =============================================================================
# 工具
# =============================================================================

class Result:
    def __init__(self):
        self.items = []   # (级别, 项名, 说明)

    def add(self, level, name, msg):
        self.items.append((level, name, msg))

    def count(self, level):
        return sum(1 for lv, _, _ in self.items if lv == level)

    @property
    def failed(self):
        return self.count("FAIL") > 0


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def split_frontmatter(text):
    """返回 (frontmatter文本, 正文)。没有 frontmatter 则 frontmatter 为 None。"""
    if not text.startswith("---"):
        return None, text
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return None, text
    return parts[0].replace("---", "", 1), parts[1]


def detect_bilingual_mirror(text):
    """
    检测中英逐段对照 —— 2026-09-12 修正（第一版大面积误报）：

    第一版用"中文行占比 30%~70%"判定，结果 9 个仓库全挂——
    但技术文档里命令是英文、说明是中文，比例天然落在区间内，属正常，不是对照。

    强判据（当前）：**同一个标题行内中英并列**，形如
      "## 这是什么 / What is this"、"## 快速开始 / Quick start"
    这才是 publish-quality.md 反对的"逐段对照"写法。
    同时排除 ``` 代码块内的 # 注释（第一版把它们当标题，属噪声）。
    """
    cjk = re.compile(r"[\u4e00-\u9fff]")
    en = re.compile(r"[A-Za-z]{3,}")
    in_code = False
    hits = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s.startswith("#"):
            continue
        if cjk.search(s) and en.search(s) and re.search(r"[/|／]", s):
            hits.append(s[:50])
    return hits


# =============================================================================
# GitHub profile
# =============================================================================

def check_github(text, topics, description, r: Result):
    if text is None:
        r.add("FAIL", "README 存在", "找不到 README.md —— GitHub 主页没有入口")
        return

    # 1. 前 30 行有数字收益
    head = "\n".join(text.splitlines()[:README_HEAD_LINES])
    if NUMBER_RE.search(head):
        r.add("PASS", f"前 {README_HEAD_LINES} 行有数字", "收益可量化")
    else:
        r.add("FAIL", f"前 {README_HEAD_LINES} 行有数字",
              "没有 %、倍、x、耗时对比等可量化收益（selfopt 式：原理开篇）")

    # 2. 中英逐段对照
    mirror = detect_bilingual_mirror(text)
    if mirror:
        r.add("FAIL", "无中英逐段对照",
              f"{len(mirror)} 处中英并列标题，如「{mirror[0]}」—— 应拆 README_EN.md，主页保持单语")
    else:
        r.add("PASS", "无中英逐段对照", "单语干净")

    # 3. 钩子是否打动人 —— 脚本判不了，交裁判
    r.add("LLM评", "钩子（3 秒测试）", "第一屏是不是在说'用户被什么扎着'？需裁判 LLM 或人工判")

    # 4. 数字是否可信 —— 脚本判不了
    r.add("LLM评", "数字可复算", "收益数字能不能复算？不许'显著提升'。需人工/裁判判")

    # 5. topics
    if topics is None:
        r.add("WARN", f"topics ≥{MIN_TOPICS} 且两组词", "[缺数据] 未传 --topics，跳过（不误判为 FAIL）")
    else:
        tp = [t.strip() for t in topics.split(",") if t.strip()]
        if len(tp) < MIN_TOPICS:
            r.add("FAIL", f"topics ≥{MIN_TOPICS}", f"当前 {len(tp)} 个 —— GitHub 不带流量，topics 是唯一搜索入口")
        else:
            has_effect = any(any(w.lower() in t.lower() for w in EFFECT_WORDS) for t in tp)
            if has_effect:
                r.add("PASS", "topics 两组词", f"{len(tp)} 个，含效果作用词")
            else:
                r.add("FAIL", "topics 两组词", f"{len(tp)} 个但全是技术分类词 —— 被痛点扎到的人搜不到你")

    # 6. description 用户视角
    if description is None:
        r.add("WARN", "description 用户视角", "[缺数据] 未传 --description，跳过")
    else:
        hits = [w for w in IMPL_JARGON if w.lower() in description.lower()]
        if hits:
            r.add("FAIL", "description 用户视角", f"命中实现黑话词：{hits} —— 站在开发者视角，不是用户视角")
        else:
            r.add("PASS", "description 用户视角", "未见实现黑话")


# =============================================================================
# SkillHub profile
# =============================================================================

def check_skillhub(text, description, r: Result):
    if text is None:
        r.add("FAIL", "SKILL.md 存在", "找不到 SKILL.md —— SkillHub 只收 skill，没有入口直接拒")
        return

    fm, body = split_frontmatter(text)

    # 1. frontmatter 完整
    if fm is None:
        r.add("FAIL", "frontmatter 存在", "文件开头不是 --- 分隔的 frontmatter")
    else:
        missing = [k for k in ("name", "description") if not re.search(rf"^{k}\s*:", fm, re.MULTILINE | re.IGNORECASE)]
        if missing:
            r.add("FAIL", "frontmatter 完整", f"缺字段：{missing}（selfopt 式：只有 summary，没有 description）")
        else:
            r.add("PASS", "frontmatter 完整", "name + description 齐全")

    # 2. 触发词
    target = fm if fm else text[:2000]
    if "触发词" in target or "触发" in target:
        r.add("PASS", "触发词已写", "frontmatter 含触发词")
    else:
        r.add("FAIL", "触发词已写", "description 末尾必须列 5-8 个真实用户说法")

    # 3. 用法章节位置 ≤ 前 1/3
    lines = text.splitlines()
    total = max(len(lines), 1)
    m = USAGE_HEADING_RE.search(text)
    if m:
        pos = text[:m.start()].count("\n")
        ratio = pos / total
        if ratio <= USAGE_MAX_RATIO or pos <= USAGE_ABS_MAX_LINES:
            r.add("PASS", "用法在前 1/3", f"用法章节位于 {ratio:.0%}（第 {pos} 行，短文档按绝对值判）")
        else:
            r.add("FAIL", "用法在前 1/3",
                  f"用法章节位于 {ratio:.0%} / 第 {pos} 行 —— 要读 {pos} 行才知道怎么干（selfopt 式）")
    else:
        r.add("FAIL", "有用法章节", "找不到'用法/快速开始/安装'类标题 —— 大模型读完不知道怎么下手")

    # 4. 开发日志
    devlog_hits = [p for p in DEVLOG_PATTERNS if re.search(p, body)]
    if devlog_hits:
        r.add("FAIL", "无开发日志", f"命中：{devlog_hits} —— 这是 changelog，不是执行手册")
    else:
        r.add("PASS", "无开发日志", "未见 changelog 式内容")

    # 5. 数学推导
    math_hits = [p for p in MATH_PATTERNS if re.search(p, body, re.IGNORECASE)]
    if math_hits:
        r.add("FAIL", "无数学推导", f"命中：{math_hits} —— 该放 docs/，别占 SKILL.md")
    else:
        r.add("PASS", "无数学推导", "未见证明过程")

    # 6. 判定分支 / 验证 / 边界 —— 部分可判
    has_verify = bool(re.search(r"(验证|verify|装完确认|检查是否生效)", body))
    has_boundary = bool(re.search(r"(适用边界|什么时候没用|别用|不适用|限制)", body))
    r.add("PASS" if has_verify else "FAIL", "装完验证",
          "有验证章节" if has_verify else "缺'装完怎么确认真生效'一条命令")
    r.add("PASS" if has_boundary else "FAIL", "适用边界",
          "有边界说明" if has_boundary else "缺'什么时候没用'（最常被省的一条）")

    # 7. 能不能照着干活 —— 脚本判不了
    r.add("LLM评", "大模型可执行性", "命令可复制吗？判定分支清楚吗？需裁判 LLM 判")

    if description is not None:
        hits = [w for w in IMPL_JARGON if w.lower() in description.lower()]
        if hits:
            r.add("FAIL", "description 用户视角", f"命中实现黑话词：{hits}")
        else:
            r.add("PASS", "description 用户视角", "未见实现黑话")


# =============================================================================
# 输出
# =============================================================================

ICON = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ ", "LLM评": "🤖"}


def render(name, r: Result):
    print(f"\n{'='*72}")
    print(f"  {name}")
    print(f"{'='*72}")
    for lv, item, msg in r.items:
        print(f"  {ICON.get(lv, '·')} [{lv:<5}] {item:<22} {msg}")
    f, w, p, l = r.count("FAIL"), r.count("WARN"), r.count("PASS"), r.count("LLM评")
    print(f"  {'-'*68}")
    verdict = "❌ 不许发布" if r.failed else "✅ 可进入下一关（LLM评 项另判）"
    print(f"  PASS {p} | FAIL {f} | WARN {w} | 需LLM评 {l}   →   {verdict}")
    return 0 if not r.failed else 1


def run_check(dirpath, platform, topics=None, description=None, label=None):
    if platform == "github":
        text = read_text(os.path.join(dirpath, "README.md"))
        r = Result()
        check_github(text, topics, description, r)
    elif platform == "skillhub":
        text = read_text(os.path.join(dirpath, "SKILL.md"))
        r = Result()
        check_skillhub(text, description, r)
    else:
        print(f"ERROR: 未知 platform: {platform}", file=sys.stderr)
        return 2
    return render(label or f"{os.path.basename(dirpath.rstrip('/'))} [{platform}]", r)


# =============================================================================
# 自检：用固定样本验证规则本身对不对（老高只需跑 --test 看结果）
# =============================================================================

def run_test():
    print("=" * 72)
    print("  自检 preflight_quality_check.py —— 验证规则本身判得对不对")
    print("=" * 72)
    ok = True

    # --- 用例 1：坏样本 GitHub（selfopt 式：原理开篇、中英对照、无数字）
    bad_gh = """# selfopt
> A framework for AI agent optimization.
## 三层分工 / Layer Division
| Layer 1 候选生成 | LLM 智能体本身 |
## Math Gate v2.1
- 性能：配对交替测量 + 中位数加速比 + 符号检验（sign test）
"""
    r = Result()
    check_github(bad_gh, "", None, r)
    ok &= _assert("坏样本 GitHub 应判 FAIL", r.failed)

    # --- 用例 2：好样本 GitHub（有数字、单语、topics 两组词齐全）
    good_gh = """# No BB
> 实测思考量最多省 74%、响应时间快 47%，答案一道不错。
| 🧠 思考量 | 标准推理题 -51% |
| ⏱ 响应时间 | 60.8s → 32.1s |
"""
    r = Result()
    check_github(good_gh, "ai,llm,token-optimization,latency,cost-optimization,python,proxy,middleware,reasoning,inference", None, r)
    ok &= _assert("好样本 GitHub 应判 PASS", not r.failed)

    # --- 用例 3：坏样本 SkillHub（无 description、用法在后、有开发日志+数学）
    bad_sh = """---
name: x
summary: something
---
# X
""" + "\n".join(["原理说明 line %d" % i for i in range(120)]) + """
## 用法
第 2 轮曾误判 5 个，回滚才发现。sign test p<0.05 证明有效。
"""
    r = Result()
    check_skillhub(bad_sh, None, r)
    ok &= _assert("坏样本 SkillHub 应判 FAIL", r.failed)

    # --- 用例 4：好样本 SkillHub
    good_sh = """---
name: y
description: 帮你省 token 的工具。触发词：省 token、收敛、减少废话
---
# Y
## 装/用
复制这一行执行。
## 装完验证
跑 xxx 看到 OK 即生效。
## 适用边界
什么时候没用：模型不支持注入时。
"""
    r = Result()
    check_skillhub(good_sh, None, r)
    ok &= _assert("好样本 SkillHub 应判 PASS", not r.failed)

    print("\n" + "=" * 72)
    print("  ✅ 全部自检通过 —— 规则判定逻辑正确" if ok else "  ❌ 自检未全通过 —— 规则有问题，别用")
    print("=" * 72)
    return 0 if ok else 1


def _assert(title, cond):
    print(f"  {'✅' if cond else '❌'} {title}")
    return cond


# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="发布物质量闸门（内容层）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python3 preflight_quality_check.py --test\n"
               "  python3 preflight_quality_check.py --dir ../selfopt --platform github --topics 'ai,python'\n"
               "  python3 preflight_quality_check.py --dir ../no-bb --platform skillhub\n",
    )
    ap.add_argument("--dir", help="项目目录（内含 README.md 或 SKILL.md）")
    ap.add_argument("--platform", choices=["github", "skillhub"], help="按哪个平台规则查")
    ap.add_argument("--topics", help="逗号分隔的 topics（GitHub 侧用；不传则跳过不误判）")
    ap.add_argument("--description", help="平台上的简介文本（不传则跳过）")
    ap.add_argument("--effect-words",
                    help="追加效果作用词（逗号分隔），补在默认表之后；领域不同时用它覆盖，"
                         "例如发布工具关心省事/少出错，而不是 token/latency")
    ap.add_argument("--test", action="store_true", help="自检：验证规则本身判得对不对")
    args = ap.parse_args()

    if args.effect_words:
        set_effect_words(args.effect_words)

    if args.test:
        return run_test()
    if not args.dir or not args.platform:
        ap.print_help()
        print("\nERROR: --dir 与 --platform 必须给（或直接用 --test 自检）", file=sys.stderr)
        return 2
    if not os.path.isdir(args.dir):
        print(f"ERROR: 目录不存在: {args.dir}", file=sys.stderr)
        return 2

    return run_check(args.dir, args.platform, args.topics, args.description)


if __name__ == "__main__":
    sys.exit(main())
