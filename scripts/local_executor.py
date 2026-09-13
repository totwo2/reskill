#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_executor.py — 本机真实执行器

把 reskill 已有的「机器可判」脚本串成一条真实的判定链，替掉占位执行器。

与占位执行器的根本区别
    占位执行器：  产物存在 = 过，分数由执行器自己给（等于没判）
    本执行器：    真跑脚本 → 分数从真实指标来；判不了的节点老实说判不了，不放行

节点分工（诚实边界，别越界）
    N0  形态判定   → 跑 detect_publish_form.sh，读回 form.json        机器判
    N1  事实表     → 查 fact-sheet.md 的出处覆盖率（结构判，非语义判） 机器判（弱）
    N2  写发布物   → 跑 quality_metrics.py，客观分直接当判决分        机器判
    N3  硬闸门     → 跑 preflight_publish_check.sh（凭据/个人痕迹/结构）机器判
    N4  质量裁判   → 读判定收件箱 verdicts/N4.json                    外部判
    N5  装配       → 读判定收件箱                                     外部判
    N6  发布       → 读判定收件箱（出网动作，必须有人授权）            外部判
    N7  收口       → 读判定收件箱                                     外部判

判定收件箱（本文件的核心设计）
    <项目>/.publish-staging/verdicts/<节点>.json
        {"score": 0-5, "judge": "谁判的", "reason": "可验证的判据"}

    执行器**只读不写**。判定必须由执行器之外的主体投递——主 agent 派出的
    只读子 agent、或人。执行器自己写判定 = 自评，等于把闸门废掉。
    收件箱空着 → 判 fail（默认安全位），宁可搁置不可错发。

用法
    python3 publish_flow.py --project <项目> init
    python3 publish_flow.py --project <项目> run --auto \
        --exec "python3 scripts/local_executor.py"

自检
    python3 local_executor.py --test
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 900

# fact-sheet 的出处标记：URL / 日期 / 权威来源词
RE_CITE = re.compile(
    r"https?://"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{4}\s*年\s*\d{1,2}\s*月"
    r"|来源[:：]|出处[:：]|据[^，。；\n]{0,12}(报|网|社|台)"
    r"|年报|公告|研报|白皮书|统计局|工信部|海关|路透|彭博|新华社|财报"
)
RE_DIGIT = re.compile(r"\d")
CITE_MIN_RATIO = 0.60      # 带数字的行里，必须至少六成标了出处


def log(msg):
    sys.stderr.write("[local_executor] %s\n" % msg)


def run(cmd, timeout=TIMEOUT):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "超时（%ss）" % timeout
    except Exception as e:                          # noqa: BLE001
        return 125, "", "无法启动：%s" % e


def verdict(passed, score=None, reason="", judge=None):
    out = {"verdict": "pass" if passed else "fail",
           "score": score, "reason": reason}
    if judge:
        out["judge"] = judge      # 判定者署名要跟着判定一起回抛，账本才有据可查
    return out


# ---------------------------------------------------------------- 机器判节点
def node_n0(ctx):
    """形态判定：跑真脚本，读回 form.json。"""
    script = os.path.join(HERE, "detect_publish_form.sh")
    rc, out, err = run("bash %s %s" % (shlex.quote(script),
                                       shlex.quote(ctx["project"])))
    form_file = os.path.join(ctx["staging"], "form.json")
    if not os.path.exists(form_file):
        return verdict(False, None, "未产出 form.json（脚本 exit=%d）：%s"
                       % (rc, (err or out).strip()[:200]))
    try:
        with open(form_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as e:
        return verdict(False, None, "form.json 不是合法 JSON：%s" % e)

    form = data.get("form")
    if form not in ("skill", "installer", "github-project"):
        return verdict(False, None, "形态非法：%r" % form)
    ev = data.get("evidence") or []
    blk = data.get("blockers") or []
    note = "形态=%s；体积 %sKB；依据：%s" % (form, data.get("size_kb"),
                                        " / ".join(ev) if ev else "无")
    if blk:
        note += "；限制：%s" % " / ".join(blk)
    return verdict(True, None, note)


def node_n1(ctx):
    """事实表：只查出处覆盖率，不判断内容对不对（那是语义判）。"""
    p = os.path.join(ctx["staging"], "fact-sheet.md")
    if not os.path.exists(p):
        return verdict(False, None,
                       "缺产物 fact-sheet.md（该步由写手产出，执行器不代写）")
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        lines = [l.strip() for l in fh if l.strip()]

    data_lines = [l for l in lines if RE_DIGIT.search(l)]
    if not data_lines:
        return verdict(False, None, "事实表里没有任何带数字的行——没有可核对的事实")
    cited = [l for l in data_lines if RE_CITE.search(l)]
    ratio = len(cited) / float(len(data_lines))
    if ratio < CITE_MIN_RATIO:
        return verdict(False, None,
                       "出处覆盖率 %.0f%%（%d/%d 条带数字的行标了出处），低于 %.0f%%："
                       "无出处的数字不许发"
                       % (ratio * 100, len(cited), len(data_lines),
                          CITE_MIN_RATIO * 100))
    return verdict(True, None, "出处覆盖率 %.0f%%（%d/%d）"
                   % (ratio * 100, len(cited), len(data_lines)))


def node_n2(ctx):
    """写发布物：客观分直接当判决分——分数不经过执行器的手。

    发布物落在**项目根**（README.md 覆盖项目里的同名文件），N3 硬闸门查的
    也是项目根，两边必须一致。README.md 与 SKILL.md 都算，取较低者。
    """
    readme = os.path.join(ctx["project"], "README.md")
    if not os.path.exists(readme):
        return verdict(False, None,
                       "缺产物 README.md（该步由写手产出，执行器不代写）")

    script = os.path.join(HERE, "quality_metrics.py")
    rc, out, err = run("%s %s %s"
                       % (shlex.quote(sys.executable), shlex.quote(script),
                          shlex.quote(ctx["project"])))
    try:
        data = json.loads(out)
    except ValueError:
        return verdict(False, None, "quality_metrics 未产出可解析 JSON（exit=%d）：%s"
                       % (rc, (err or out).strip()[:200]))

    files = data.get("files") or {}
    if not files:
        return verdict(False, None, "quality_metrics 没算到任何发布物")
    score = data.get("min_score")
    worst = min(files.items(), key=lambda kv: kv[1].get("score", 0))
    weak = [c for c in worst[1].get("checks", []) if c.get("value", 1) < 1.0]
    reason = "客观分 %.2f（%s；下限 %s）" % (
        score, " / ".join("%s %.2f" % (k, v.get("score")) for k, v in files.items()),
        ctx["min_score"] or "—")
    if weak:
        reason += "；最弱项：" + "；".join(
            "%s（%s）" % (c["check"], c["note"]) for c in weak[:2])
    return verdict(True, score, reason)


def node_n3(ctx):
    """硬闸门：对项目根目录跑发布前综合检查。"""
    script = os.path.join(HERE, "preflight_publish_check.sh")
    rc, out, err = run("bash %s %s" % (shlex.quote(script),
                                       shlex.quote(ctx["project"])))
    if rc == 0:
        return verdict(True, None, "综合检查通过：凭据 / 个人痕迹 / 结构 全绿")
    hits = [l.strip() for l in out.splitlines() if "🔴" in l][:5]
    detail = " | ".join(hits) if hits else (out or err).strip()[:200]
    return verdict(False, None, "综合检查未过（exit=%d）：%s" % (rc, detail))


# ---------------------------------------------------------------- 外部判节点
def read_inbox(ctx):
    p = os.path.join(ctx["staging"], "verdicts", "%s.json" % ctx["node"])
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


def node_external(ctx):
    """语义节点：读判定收件箱。空着 = 判不了 = fail（默认安全位）。

    一条判定要成立，必须「署名 + 判据」齐备：
        没署名 → 查不出是谁判的 = 无人负责
        没判据 → 说了话但没有依据 = 无法复核
    两者缺一即不予采信，宁可搁置不可错发。
    """
    v = read_inbox(ctx)
    if v is None:
        return verdict(False, None,
                       "%s 需外部判定，但收件箱没有判定："
                       ".publish-staging/verdicts/%s.json 不存在或非法。"
                       "（执行器只读不写——判定须由只读子 agent 或人投递）"
                       % (ctx["node"], ctx["node"]))

    judge = v.get("judge")
    if not judge:
        return verdict(False, v.get("score"),
                       "%s 判定没有署名（缺 judge）：无人负责的判定不予采信"
                       % ctx["node"], judge="(未署名)")
    if not v.get("reason"):
        return verdict(False, v.get("score"),
                       "%s 判定没有判据（缺 reason）：无法复核的判定不予采信"
                       % ctx["node"], judge=judge)

    reason = v["reason"]
    score = v.get("score")

    # 署名必须跟着每一次判决回抛，不只是通过的那次。
    # 否决同样要留名，否则事后翻账只查得出"这步没过"，查不出"谁否的"。
    if ctx["min_score"]:
        if score is None:
            return verdict(False, None, "%s 有分数下限 %s，但判定没给分（judge=%s）"
                           % (ctx["node"], ctx["min_score"], judge), judge=judge)
        if float(score) < float(ctx["min_score"]):
            return verdict(False, score, "%s 得分 %s < 下限 %s（judge=%s）"
                           % (ctx["node"], score, ctx["min_score"], judge),
                           judge=judge)
    return verdict(True, score, "%s 外部判定通过：%s（judge=%s）"
                   % (ctx["node"], reason[:300], judge), judge=judge)


# 语义节点：判定来自收件箱，而不是执行器自己算出来的。
# 单一真源在 publish_flow.NODES 的 external 字段——这里不再各写一份，
# 否则节点表加了外部节点、执行器不知道，就会出现"该派的没派"。
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import publish_flow as pf                              # noqa: E402

EXTERNAL_NODES = pf.EXTERNAL_NODES

HANDLERS = {
    "N0": node_n0, "N1": node_n1, "N2": node_n2, "N3": node_n3,
}
HANDLERS.update({n: node_external for n in EXTERNAL_NODES})


def execute(ctx):
    fn = HANDLERS.get(ctx["node"])
    if fn is None:
        return verdict(False, None, "未知节点：%r" % ctx["node"])
    return fn(ctx)


# ---------------------------------------------------------------- 自检
GOOD_README = """# demo-tool

给你的一条命令，把重复劳动干掉。

装上就能用，实测单次处理 500 条只要 3 秒。

## 安装

```
pip install demo-tool
```

## 用法

```
demo-tool run --input data.csv
```

## 为什么

（原理放后面，不占首屏。）
""" + "\n".join(["更多说明 %d，参考 https://example.com/doc" % i for i in range(30)])

BAD_README = """# demo-tool

本项目采用三层架构设计，模块划分为 parser / engine / writer。
我们实现了完整解耦，通过事件总线通信，内部设计模式严谨。

## 架构说明

""" + "\n".join(["分层说明 %d" % i for i in range(40)])

GOOD_SKILL = """---
name: demo-tool
description: 把重复劳动干掉。触发词：批量处理、导出报表、定时任务、数据清洗、自动跑
---

# demo-tool

## 用法

一条命令跑完。

## 原理

后面才讲。
"""

GOOD_FACT = """# 事实表

## 数据

- 2024 年国内市场规模 128 亿元（来源：工信部 2024-03-15 发布）
- 头部三家合计份额 41.2%（出处：XX 研报 2025-01-08）
- 用户平均处理耗时从 12 分钟降到 3 分钟（来源：https://example.com/bench）
- 相关标准已发布 3 项（来源：国家标准公告 2024-11）
"""

BAD_FACT = """# 事实表

## 数据

- 市场规模 130 亿左右
- 头部三家合计份额 41%
- 用户平均耗时从 12 分钟降到 3 分钟
"""

EMPTY_FACT = """# 事实表

## 数据

- 市场规模大概一百多亿
- 头部份额看起来有四成
"""


def _write(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run_test():
    tmp = tempfile.mkdtemp(prefix="lexec-test-")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    def make_project(name, readme, fact=GOOD_FACT):
        p = os.path.join(tmp, name)
        os.makedirs(p)
        _write(os.path.join(p, "README.md"), readme)
        _write(os.path.join(p, "SKILL.md"), GOOD_SKILL)
        _write(os.path.join(p, ".publish-staging", "fact-sheet.md"), fact)
        return p

    def ctx_of(project, node, min_score=None):
        return {"node": node, "project": project,
                "staging": os.path.join(project, ".publish-staging"),
                "attempt": "1", "need": "", "min_score": min_score}

    try:
        # 1) N0 真判形态
        p0 = make_project("n0", GOOD_README)
        v0 = execute(ctx_of(p0, "N0"))
        check("N0 跑真脚本并判出 skill",
              v0["verdict"] == "pass" and "形态=skill" in v0["reason"],
              v0["reason"][:80])

        # 2) N1 出处覆盖率：好的过
        v1 = execute(ctx_of(p0, "N1"))
        check("N1 好事实表通过（出处覆盖率达标）",
              v1["verdict"] == "pass", v1["reason"][:80])

        # 3) N1 出处覆盖率：坏的拦下
        p1 = make_project("n1bad", GOOD_README, fact=BAD_FACT)
        v1b = execute(ctx_of(p1, "N1"))
        check("N1 有数字但无出处 → 拦下（出处覆盖率不达标）",
              v1b["verdict"] == "fail" and "出处覆盖率" in v1b["reason"],
              v1b["reason"][:80])

        # 3b) N1 全中文数字（没有可核对的事实）→ 也拦下
        p1c = make_project("n1empty", GOOD_README, fact=EMPTY_FACT)
        v1c = execute(ctx_of(p1c, "N1"))
        check("N1 没有带数字的行 → 拦下",
              v1c["verdict"] == "fail" and "没有任何带数字的行" in v1c["reason"],
              v1c["reason"][:80])

        # 4) N2 好 README 拿高分
        v2 = execute(ctx_of(p0, "N2", min_score=3))
        check("N2 好 README 分数 ≥ 3",
              v2["verdict"] == "pass" and (v2["score"] or 0) >= 3,
              "score=%s" % v2["score"])

        # 5) N2 坏 README 分数低（客观分真的在拦人）
        p2 = make_project("n2bad", BAD_README)
        v2b = execute(ctx_of(p2, "N2", min_score=3))
        check("N2 坏 README 客观分低于下限",
              v2b["verdict"] == "pass" and (v2b["score"] or 9) < 3,
              "score=%s（state 机内会自动判 fail）" % v2b["score"])

        # 5b) N2 产物只在 staging、不在项目根 → 不算交付
        p2c = make_project("n2staging", GOOD_README)
        os.remove(os.path.join(p2c, "README.md"))
        _write(os.path.join(p2c, ".publish-staging", "README.md"), GOOD_README)
        v2c = execute(ctx_of(p2c, "N2", min_score=3))
        check("N2 发布物放错位置（staging）→ fail",
              v2c["verdict"] == "fail" and "缺产物" in v2c["reason"],
              v2c["reason"][:80])

        # 6) N4 收件箱空 → fail
        v4 = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 收件箱空 → 判 fail（不放行）",
              v4["verdict"] == "fail" and "收件箱" in v4["reason"],
              v4["reason"][:80])

        # 7) N4 收件箱有判定 → pass
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 4.5, "judge": "reader-1",
                           "reason": "按陌生人视角读了三遍，知道装了干什么"},
                          ensure_ascii=False))
        v4b = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 收件箱有判定 → pass",
              v4b["verdict"] == "pass" and v4b["score"] == 4.5,
              v4b["reason"][:80])

        # 8) N4 判定低于下限 → fail
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 1, "judge": "reader-1", "reason": "看不懂"},
                          ensure_ascii=False))
        v4c = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 判定低于下限 → fail",
              v4c["verdict"] == "fail", v4c["reason"][:80])

        # 9) N4 有分数下限但没给分 → fail
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"judge": "reader-1", "reason": "还行"},
                          ensure_ascii=False))
        v4d = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 缺分数 → fail",
              v4d["verdict"] == "fail" and "没给分" in v4d["reason"],
              v4d["reason"][:80])

        # 9b) 判定没署名 → 不予采信（无人负责）
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 4, "reason": "看着还行"},
                          ensure_ascii=False))
        v4e = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 判定未署名 → fail",
              v4e["verdict"] == "fail" and "署名" in v4e["reason"],
              v4e["reason"][:80])

        # 9c) 判定没判据 → 不予采信（无法复核）
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 4, "judge": "reader-1"},
                          ensure_ascii=False))
        v4f = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 判定缺判据 → fail",
              v4f["verdict"] == "fail" and "判据" in v4f["reason"],
              v4f["reason"][:80])

        # 9d) 判定的署名要跟着回抛（账本才有据可查）
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 4.5, "judge": "reader-7",
                           "reason": "README.md:3 首屏讲清了装的收益"},
                          ensure_ascii=False))
        v4g = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 判定署名随判定回抛",
              v4g["verdict"] == "pass" and v4g.get("judge") == "reader-7",
              "judge=%s" % v4g.get("judge"))

        # 9e) 否决的判定同样要带署名 —— 事后翻账要能查出"谁否的"
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 1, "judge": "reader-9",
                           "reason": "README.md:2 看不出收益"},
                          ensure_ascii=False))
        v4h = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 否决也带署名（谁否的要查得到）",
              v4h["verdict"] == "fail" and v4h.get("judge") == "reader-9",
              "judge=%s" % v4h.get("judge"))

        # 9f) 判定压根没署名 → 回抛里明示未署名，不冒用节点默认判定者
        _write(os.path.join(p0, ".publish-staging", "verdicts", "N4.json"),
               json.dumps({"score": 4, "reason": "看着还行"},
                          ensure_ascii=False))
        v4i = execute(ctx_of(p0, "N4", min_score=3))
        check("N4 未署名 → 回抛里明示未署名",
              v4i["verdict"] == "fail" and v4i.get("judge") == "(未署名)",
              "judge=%s" % v4i.get("judge"))

        # 10) 执行器只读不写收件箱
        before = sorted(os.listdir(os.path.join(p0, ".publish-staging", "verdicts")))
        execute(ctx_of(p0, "N5", min_score=None))
        after = sorted(os.listdir(os.path.join(p0, ".publish-staging", "verdicts")))
        check("执行器不自行投递判定（只读不写）", before == after,
              "before=%s after=%s" % (before, after))

        # 11) 未知节点 → fail
        v11 = execute(ctx_of(p0, "N99"))
        check("未知节点 → fail", v11["verdict"] == "fail", v11["reason"][:60])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("local_executor.py 自检 —— %d 项" % len(results))
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
    print("自检通过：机器节点真跑脚本、语义节点收不到判定不放行。")
    return 0


# ---------------------------------------------------------------- 入口
def main():
    if "--test" in sys.argv:
        return run_test()

    staging = os.environ.get("PFLOW_STAGING", ".")
    project = os.environ.get("PFLOW_PROJECT") or os.path.dirname(
        os.path.abspath(staging))
    ctx = {
        "node": os.environ.get("PFLOW_NODE", ""),
        "project": project,
        "staging": staging,
        "attempt": os.environ.get("PFLOW_ATTEMPT", "1"),
        "need": os.environ.get("PFLOW_NEED", ""),
        "min_score": os.environ.get("PFLOW_MIN_SCORE") or None,
    }

    if not os.path.isdir(staging):
        os.makedirs(staging)

    result = execute(ctx)
    log("%s attempt=%s → %s  %s" % (ctx["node"], ctx["attempt"],
                                    result["verdict"], result["reason"][:120]))
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
