#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_publish.py — 本机发布链单入口

把状态机、真实执行器、判定派发器串成一条命令。你只需要反复调它：

    1) 机器节点（N0–N3）  它自己跑脚本判完
    2) 撞到语义节点       它出题、打印任务单，然后**停下**，退出码 10
    3) 你（或主 agent 派的只读子 agent）按任务单回卷
    4) 再调一次，继续往下一节点走
    5) 走满 → released，退出码 0

为什么第 2 步要"停下"而不是"自己判"：
    执行器只读不写收件箱。判定必须由执行器之外的主体投递——
    它自己写判定 = 自评 = 把闸门废掉。所以这里只能停。

退出码（供 cron / 主 agent 判断该干什么）
    0   终态已到（released / deferred）
    10  停在语义节点等投递，任务单已生成
    1   用法或环境错误

用法
    python3 local_publish.py --project <项目>
    python3 local_publish.py --project <项目> --exec "python3 /abs/path/local_executor.py"
    python3 local_publish.py --project <项目> report
    python3 local_publish.py --test
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import publish_flow as pf          # noqa: E402
import verdict_dispatch as vd      # noqa: E402

EXIT_TERMINAL = 0
EXIT_AWAITING = 10
EXIT_ERROR = 1


def default_exec():
    return "%s %s" % (sys.executable, os.path.join(HERE, "local_executor.py"))


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _capture(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **kw)
    return rc, buf.getvalue()


# ---------------------------------------------------------------- 单步推进
def cmd_step(args):
    """推进一轮：机器节点自动判，遇到语义节点就停下出题。"""
    project = os.path.abspath(args.project)
    if not os.path.exists(pf.state_path(project)):
        return _fail("尚未 init：先跑 publish_flow.py --project <项目> init")

    exec_cmd = args.exec_cmd or default_exec()

    st = pf.load_state(project)
    if st["state"] != "in_progress":
        return _terminal(project, st, "流程已在终态，无需推进")

    # 收件箱质检：判定本身不成立时（没署名 / 没判据 / JSON 坏 / 缺分数）原地退回，
    # 不吃重试次数 —— 否则同一份坏判定会被连读三次，把「写错了」当成「做不到」，
    # 直接判死搁置。
    # 注意只拦 kind == "invalid"：判定成立但给了低分（below_floor）是一次真实否决，
    # 要让它照常计入重试，累计超限才自动搁置。
    cur = pf.NODES[st["node_index"]]
    if cur["id"] in vd.le.EXTERNAL_NODES:
        _, cout = _capture(vd.cmd_collect, argparse.Namespace(project=project))
        col = json.loads(cout)
        mine = [d for d in col["delivered"] if d["node"] == cur["id"]]
        if mine and mine[0].get("kind") == "invalid":
            emit({
                "ok": False,
                "state": "in_progress",
                "invalid_verdict": True,
                "awaiting_verdict": cur["id"],
                "awaiting_name": cur["name"],
                "reply_to": os.path.join(vd.verdicts_dir(project),
                                         "%s.json" % cur["id"]),
                "problems": mine[0].get("problems") or [],
                "note": "收件箱里的判定不成立，已原地退回（不消耗重试次数）。"
                        "改好判定后重跑本命令。",
            })
            return EXIT_AWAITING

    rc, out = _capture(pf.cmd_run, pf._ns(
        project=project, exec_cmd=exec_cmd, pause_external=True))
    if rc not in (0, None):
        return _fail("状态机退出码 %s" % rc)

    res = json.loads(out)
    state = res["state"]
    awaiting = res.get("awaiting")

    if state != "in_progress":
        return _terminal(project, pf.load_state(project), "走满全部节点")

    if awaiting:
        # 出题：生成任务单；出不了题（如零证据）本身就是错误
        brief = vd.build_brief(project)
        if not brief.get("ok"):
            return _fail("无法出题：%s" % brief.get("reason"))

        task_file = os.path.join(vd.pending_dir(project),
                                 "%s.task.json" % brief["node"])
        brief["pending_file"] = task_file
        vd._write_json(task_file, brief)

        # 出题方负责把投递口建好，判定者只需写文件
        vdir = vd.verdicts_dir(project)
        if not os.path.isdir(vdir):
            os.makedirs(vdir)

        emit({
            "ok": True,
            "state": state,
            "progress": "%d/%d" % (pf.load_state(project)["node_index"],
                                   len(pf.NODES)),
            "awaiting_verdict": brief["node"],
            "awaiting_name": brief["node_name"],
            "judge_category": brief["judge_category"],
            "min_score": brief["min_score"],
            "good_looks_like": brief["good_looks_like"],
            "must_read": [m.get("path") for m in brief["must_read"]],
            "must_run": brief["must_run"],
            "evidence_hint": brief["evidence_hint"],
            "reply_to": brief["reply_to"],
            "reply_schema": brief["reply_schema"],
            "task_file": task_file,
            "note": "%s 需外部判定，不能由执行器自评。"
                    "把判定写进 reply_to，然后重跑本命令。" % brief["node"],
            "trace": res.get("trace", []),
        })
        return EXIT_AWAITING

    # 既没终态、也没等投递 —— 状态机不该出现这种情况
    return _fail("异常中间态：state=%s awaiting=%s" % (state, awaiting))


def _terminal(project, st, why):
    led = pf.read_ledger(project)
    emit({
        "ok": True,
        "state": st["state"],
        "why": why,
        "progress": "%d/%d" % (st["node_index"], len(pf.NODES)),
        "ledger_rows": len(led),
        "ledger": led,
        "note": ("已发布。" if st["state"] == "released"
                 else "已搁置：没发出去，也没失败。报告就在账本里，你想看再翻。"),
    })
    return EXIT_TERMINAL


def _fail(msg):
    emit({"ok": False, "error": msg})
    return EXIT_ERROR


# ---------------------------------------------------------------- 报告
def cmd_report(args):
    project = os.path.abspath(args.project)
    st = pf.load_state(project)
    led = pf.read_ledger(project)
    scored = [r for r in led if r.get("score") is not None]
    judges = {}
    for r in led:
        judges[r["judge"]] = judges.get(r["judge"], 0) + 1

    emit({
        "state": st["state"],
        "progress": "%d/%d" % (st["node_index"], len(pf.NODES)),
        "attempts": st["attempts"],
        "rows": len(led),
        "scored_rows": len(scored),
        "min_score_seen": min((r["score"] for r in scored), default=None),
        "judges": judges,
        "ledger": led,
        "note": "每一行都能被事后翻出来对账：谁判的、给几分、依据什么。",
    })
    return EXIT_TERMINAL


# ---------------------------------------------------------------- 自检
def cmd_test(_args=None):
    tmp = tempfile.mkdtemp(prefix="lpublish-test-")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    def write(path, text):
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def step(p):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_step(argparse.Namespace(project=p, exec_cmd=None))
        try:
            return rc, json.loads(buf.getvalue())
        except ValueError:
            return rc, {"raw": buf.getvalue()}

    try:
        p = os.path.join(tmp, "proj")
        os.makedirs(p)
        write(os.path.join(p, "SKILL.md"),
              "---\nname: demo-tool\n"
              "description: 把重复劳动干掉。触发词：批量处理、导出报表、定时任务、"
              "数据清洗、自动跑\n---\n\n# demo-tool\n\n## 用法\n\n跑。\n\n## 原理\n\n后讲。\n")
        write(os.path.join(p, "README.md"),
              "# demo-tool\n\n[English](README_EN.md) | 简体中文\n\n"
              "给你的一条命令，把重复劳动干掉。"
              "装上就能用，实测单次处理 500 条只要 3 秒。\n\n"
              "## 安装\n\n```\npip install demo-tool\n```\n\n"
              "## 用法\n\n```\ndemo-tool run --input data.csv\n```\n\n"
              "## 为什么\n\n原理放后面。\n")
        # GitHub 侧必须中英双语（分文件）—— 2026-09-23 起是硬要求，fixture 要跟上
        write(os.path.join(p, "README_EN.md"),
              "# demo-tool\n\nEnglish | [简体中文](README.md)\n\n"
              "One command that kills repetitive work. Install it and it just runs; "
              "measured at 3 seconds for 500 rows.\n\n"
              "## Install\n\n```\npip install demo-tool\n```\n\n"
              "## Usage\n\n```\ndemo-tool run --input data.csv\n```\n")
        write(os.path.join(p, pf.STAGING, "fact-sheet.md"),
              "# 事实表\n\n- 2024 年市场规模 128 亿元（来源：工信部 2024-03-15）\n"
              "- 头部份额 41.2%（出处：行业研报 2025-01-08）\n")

        def init(p):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pf.cmd_init(argparse.Namespace(project=p))

        # 1) 未 init → 报错，不瞎跑
        rc1, r1 = step(p)
        check("未 init → 退出码 1（不瞎跑）",
              rc1 == EXIT_ERROR and not r1.get("ok"), "rc=%s" % rc1)

        init(p)

        # 2) 第一步：机器节点判完，停在 N4
        rc2, r2 = step(p)
        check("首步 → 退出码 10（停在语义节点）", rc2 == EXIT_AWAITING,
              "rc=%s" % rc2)
        check("停在 N4 且给出回填路径",
              r2.get("awaiting_verdict") == "N4"
              and (r2.get("reply_to") or "").endswith(os.path.join("verdicts", "N4.json")),
              str(r2.get("awaiting_verdict")))
        check("任务单落盘", os.path.exists(r2.get("task_file") or ""), str(r2.get("task_file")))
        check("已判的机器节点落了账",
              [row.get("node") for row in (r2.get("trace") or [])] == ["N0", "N1", "N2", "N3"],
              str([row.get("node") for row in (r2.get("trace") or [])]))
        check("停下不消耗重试次数",
              (pf.load_state(p).get("attempts") or {}) == {},
              str(pf.load_state(p).get("attempts")))

        # 3) 回卷 → 继续推进，逐节点走到终态
        seen = []
        rc = rc2
        guard = 0
        while rc == EXIT_AWAITING and guard < 10:
            guard += 1
            node = r2.get("awaiting_verdict") if guard == 1 else r.get("awaiting_verdict")
            seen.append(node)
            write((r2.get("reply_to") if guard == 1 else r.get("reply_to")) or "",
                  json.dumps({"score": 4.5, "judge": "reader-%s" % node.lower(),
                              "reason": "依任务单判：%s" % node}, ensure_ascii=False))
            rc, r = step(p)

        check("逐节点推进 N4→N7", seen == ["N4", "N5", "N6", "N7"], str(seen))
        check("走满 → 退出码 0 且 released",
              rc == EXIT_TERMINAL and r.get("state") == "released",
              "rc=%s state=%s" % (rc, r.get("state")))
        check("账本 8 行、8 行都有署名",
              len(r.get("ledger") or []) == len(pf.NODES)
              and all(x.get("judge") for x in (r.get("ledger") or [])),
              "%d 行" % len(r.get("ledger") or []))

        # 4) 终态后再调 → 仍是 0，不重复推进
        rc4, r4 = step(p)
        check("终态后重跑 → 退出码 0（幂等）",
              rc4 == EXIT_TERMINAL and r4.get("state") == "released",
              "rc=%s" % rc4)

        # 5) report 能读出每个判定者
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_report(argparse.Namespace(project=p))
        rep = json.loads(buf.getvalue())
        check("report 列出判定者与分数下限",
              "reader-n4" in (rep.get("judges") or []) and rep.get("rows") == len(pf.NODES),
              str(rep.get("judges")))

        # 6) 判定缺署名 → 不予采信，不推进
        p2 = os.path.join(tmp, "proj2")
        os.makedirs(p2)
        write(os.path.join(p2, "SKILL.md"),
              "---\nname: d\ndescription: 触发词：a、b、c、d、e\n---\n\n## 用法\n\n跑。\n")
        write(os.path.join(p2, "README.md"),
              "# d\n\n[English](README_EN.md) | 简体中文\n\n"
              "给你的一条命令，装上就能用，实测 500 条 3 秒。\n\n## 用法\n\n```\nd\n```\n")
        write(os.path.join(p2, "README_EN.md"),
              "# d\n\nEnglish | [简体中文](README.md)\n\n"
              "One command, install and run; measured 3 seconds for 500 rows.\n")
        write(os.path.join(p2, pf.STAGING, "fact-sheet.md"),
              "# 事实表\n\n- 2024 年规模 128 亿元（来源：工信部 2024-03-15）\n")
        init(p2)
        step(p2)                                   # 停在 N4
        write(os.path.join(p2, pf.STAGING, "verdicts", "N4.json"),
              json.dumps({"score": 5, "reason": "没署名"}, ensure_ascii=False))
        rc6, r6 = step(p2)
        check("判定未署名 → 原地退回，不吃重试次数",
              rc6 == EXIT_AWAITING and r6.get("invalid_verdict") is True
              and (pf.load_state(p2).get("attempts") or {}) == {}
              and pf.load_state(p2).get("node_index") == 4,
              "rc=%s r6=%s" % (rc6, str(r6)[:80]))
        check("退回时说明缺什么",
              any("缺 judge" in x for x in (r6.get("problems") or [])),
              str(r6.get("problems"))[:80])

        # 7) 判定成立但给低分 → 真实否决，计入重试 → 超限自动搁置（不发）
        p3 = os.path.join(tmp, "proj3")
        os.makedirs(p3)
        write(os.path.join(p3, "SKILL.md"),
              "---\nname: d\ndescription: 触发词：a、b、c、d、e\n---\n\n## 用法\n\n跑。\n")
        write(os.path.join(p3, "README.md"),
              "# d\n\n[English](README_EN.md) | 简体中文\n\n"
              "给你的一条命令，装上就能用，实测 500 条 3 秒。\n\n## 用法\n\n```\nd\n```\n")
        write(os.path.join(p3, "README_EN.md"),
              "# d\n\nEnglish | [简体中文](README.md)\n\n"
              "One command, install and run; measured 3 seconds for 500 rows.\n")
        write(os.path.join(p3, pf.STAGING, "fact-sheet.md"),
              "# 事实表\n\n- 2024 年规模 128 亿元（来源：工信部 2024-03-15）\n")
        init(p3)
        step(p3)                                   # 停在 N4
        write(os.path.join(p3, pf.STAGING, "verdicts", "N4.json"),
              json.dumps({"score": 1.0, "judge": "reader-1",
                          "reason": "README.md:2 看不出装的收益"}, ensure_ascii=False))
        rc7, r7 = step(p3)
        st7 = pf.load_state(p3)
        check("低分判定 → 计入重试并自动搁置（不发）",
              rc7 == EXIT_TERMINAL and r7.get("state") == "deferred"
              and (st7.get("attempts") or {}).get("N4") == pf.MAX_ROUNDS,
              "rc=%s state=%s attempts=%s" % (rc7, r7.get("state"),
                                              st7.get("attempts")))
        check("搁置也留账本：每条否决都记着谁判的",
              len([x for x in (r7.get("ledger") or [])
                   if x.get("node") == "N4" and x.get("verdict") == "fail"
                   and x.get("judge") == "reader-1"]) == pf.MAX_ROUNDS,
              str([(x.get("node"), x.get("judge")) for x in (r7.get("ledger") or [])]))
    except Exception as exc:      # noqa: BLE001
        # 兜底：自检自己崩了，也必须报成一项 FAIL —— 不能把失败盖成 traceback。
        # 2026-09-23 教训：`r2["task_file"]` 用下标取键，闸门变化后该键不存在，
        # 于是抛 KeyError 崩掉，把「首步没停在 N4」这个真失败完全盖住 ——
        # 一份会崩的自检，比没有自检更糟：它让人以为"没报错就是过了"。
        results.append(("自检自身未崩溃", False,
                        "%s: %s（自检代码有 bug，不是被测对象的问题）"
                        % (type(exc).__name__, exc)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("local_publish.py 自检 —— %d 项" % len(results))
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
    print("自检通过：机器节点自动判、语义节点停下出题、回卷后继续、无署名不采信。")
    return 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="local_publish.py",
        description="本机发布链单入口：机器节点自动判，语义节点停下等你（或子 agent）投判定")
    ap.add_argument("--project", default=os.getcwd(), help="项目根目录")
    ap.add_argument("--exec", dest="exec_cmd", default=None,
                    help="外部执行器命令（默认用同目录 local_executor.py）")
    ap.add_argument("--test", action="store_true", help="跑内置自检，不需要项目")
    ap.add_argument("--version", action="version", version="1.0.0")

    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("step", help="推进一轮（默认动作）")
    sub.add_parser("report", help="打一份完整报告（含账本全文）")

    args = ap.parse_args(argv)

    if args.test:
        return cmd_test()

    if args.cmd == "report":
        return cmd_report(args)
    return cmd_step(args)


if __name__ == "__main__":
    sys.exit(main())
