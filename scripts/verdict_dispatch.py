#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verdict_dispatch.py — 判定派发器（出题 / 收卷）

补上无人值守链里缺的那一环：「谁来判」。

它自己不判、也绝不碰收件箱，只做两件事：

    出题 brief
        按当前节点生成一张判定任务单 → .publish-staging/pending/<节点>.task.json
        任务单写明：读哪些材料、按什么标准打分、回填到哪、回填什么格式。
        主 agent 拿这张单子去派只读子 agent。

    收卷 collect
        扫描 .publish-staging/verdicts/，校验每份判定是否合法、会不会通过。
        只校验，不改写——改判定的人只能是判定者自己。

三权边界（合起来才成立）
    local_executor.py    只读 verdicts/  → 执行者不自评
    verdict_dispatch.py  只写 pending/   → 派发者不代判
    判定者（只读子 agent / 人）         → 唯一有权写 verdicts/ 的主体

判定不复用执行器的嘴
    任务单里不含任何"我觉得这步做得怎么样"的判断，只给材料与标准。
    判定者必须自己去读产物，并给出带锚点（文件:行号）的判据。

用法
    python3 verdict_dispatch.py --project <项目> status
    python3 verdict_dispatch.py --project <项目> brief
    python3 verdict_dispatch.py --project <项目> brief --node N4
    python3 verdict_dispatch.py --project <项目> collect
    python3 verdict_dispatch.py --test
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

import publish_flow as pf          # noqa: E402  单一真源：节点表 / 状态 / 账本
import local_executor as le        # noqa: E402  单一真源：哪些节点要外部判

FIRST_LINES = 60                   # 任务单里带多少行材料摘要

# 0-5 分怎么打 —— 判定者照这个开口，不照执行者的话术开口
RUBRIC = [
    ["5", "超标：不止达标，还有可被引用的亮点"],
    ["4", "好：目标使用者看完就能用，不必猜"],
    ["3", "及格：能用，但有明显可改进处"],
    ["2", "勉强：要使用者自己补脑，或信息缺失"],
    ["1", "差：形式上有，实质没达到目的"],
    ["0", "空或错：产物缺失，或与目标无关"],
]

CONSTRAINTS = [
    "只读：不得修改任何产物文件",
    "只允许写一个文件：reply_to 指定的那份判定 JSON",
    "判据必须可验证：引用原文 + 文件:行号；无锚点的判定视为无效",
    "不采信执行者的陈述，只看产物本身",
    "该节点有分数下限时必须给分数，缺分数会被自动判 fail",
    "拿不准就判 fail —— 搁置是安全位，错发不是",
]

# 每个语义节点该拿什么当证据（由派发器声明，不重复节点表）
#
# files    —— 可以直接摘录给判定者的产物
# commands —— 没有现成文件时，判定者必须自己去取的证据（只读命令）
#
# 一条铁律：files 与 commands 不能同时为空。
# 判定者手上没有证据，就只能盖章放行 —— 那一步的"好不好"等于没人判。
MATERIALS = {
    "N4": {"files": ("README.md", "SKILL.md"), "commands": (),
           "hint": "判发布物本身：README 给陌生人看，SKILL.md 给大模型看（两份都要看）。"},
    "N5": {"files": (), "commands": ("git status --short", "git diff --stat"),
           "hint": "判装配是否克制：先取工作区改动清单，再看有没有顺手改动无关文件。"},
    "N6": {"files": (), "commands": ("git tag --points-at HEAD", "git remote -v"),
           "hint": "判发布动作与产物。本地阶段没有出网授权时不得判 pass。"},
    "N7": {"files": (), "commands": ("git describe --tags", "git log --oneline -1"),
           "hint": "判收口是否齐备：三行契约（版本/变更/回滚）、监控清单已同步。"},
}


# ---------------------------------------------------------------- 路径
def pending_dir(project):
    return os.path.join(project, pf.STAGING, "pending")


def verdicts_dir(project):
    return os.path.join(project, pf.STAGING, "verdicts")


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _write_json(path, obj):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------- 出题
def _excerpt(path):
    """给判定者一段材料摘要——只给材料，不给结论。"""
    if not os.path.exists(path):
        return {"path": path, "exists": False}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        return {"path": path, "exists": False, "error": str(e)}
    return {
        "path": path,
        "exists": True,
        "lines": len(lines),
        "excerpt": "\n".join(lines[:FIRST_LINES]),
        "truncated": len(lines) > FIRST_LINES,
    }


def build_brief(project, node_id=None):
    """按当前节点生成判定任务单。不改状态、不写收件箱。"""
    st = pf.load_state(project)

    if st["state"] != "in_progress":
        return {"ok": False, "done": True, "state": st["state"],
                "reason": "流程已结束（%s），没有节点需要判定" % st["state"]}

    node = pf.NODES[st["node_index"]]
    nid = node["id"]

    if node_id and node_id != nid:
        return {"ok": False,
                "reason": "节点不匹配：当前停在 %s，请求的是 %s（不许跳步）"
                          % (nid, node_id)}

    if nid not in le.EXTERNAL_NODES:
        return {"ok": False, "node": nid, "node_name": node["name"],
                "reason": "%s（%s）由机器判：执行器自动跑脚本，不需要派发判定"
                          % (nid, node["name"]),
                "judge_owner": node["judge"]}

    mat = MATERIALS.get(nid, {"files": (), "commands": (), "hint": ""})
    must_read = [_excerpt(os.path.join(project, f)) for f in mat["files"]]
    commands = list(mat.get("commands") or ())

    # 证据闸门：没材料、又没取证据的命令 → 判定者只能盖章，这一步的"好不好"落空
    if not must_read and not commands:
        return {"ok": False, "node": nid, "node_name": node["name"],
                "reason": "%s 的任务单没有任何证据来源（既无材料也无取证据命令）："
                          "判定者无从判「好不好」，拒绝出题（先补 MATERIALS[%s]）"
                          % (nid, nid)}

    reply_to = os.path.join(verdicts_dir(project), "%s.json" % nid)

    return {
        "ok": True,
        "task": "verdict",
        "node": nid,
        "node_name": node["name"],
        "attempt_next": st["attempts"].get(nid, 0) + 1,
        "max_rounds": pf.MAX_ROUNDS,
        "min_score": node["min_score"],
        "judge_category": node["judge"],
        "good_looks_like": node["good"],
        "must_read": must_read,
        "must_run": commands,
        "evidence_hint": mat["hint"],
        "rubric": RUBRIC,
        "reply_to": reply_to,
        "reply_schema": {
            "score": "0-5 的小数；该节点有下限时必填，缺分数自动判 fail",
            "judge": "判定者署名——谁判的就写谁，不能留空",
            "reason": "判据，必须带锚点：引用原文 + 文件:行号",
        },
        "constraints": CONSTRAINTS,
    }


def cmd_brief(args):
    brief = build_brief(args.project, args.node)
    if brief.get("ok"):
        # 出题方负责把「投递口」建好 —— 判定者只管写文件，不该自己去 mkdir
        vd = verdicts_dir(args.project)
        if not os.path.isdir(vd):
            os.makedirs(vd)
        f = os.path.join(pending_dir(args.project), "%s.task.json" % brief["node"])
        brief["pending_file"] = f
        _write_json(f, brief)
    emit(brief)
    return 0


# ---------------------------------------------------------------- 收卷
def _validate(project, fname, current):
    """校验一份判定。只读，不改。"""
    stem = os.path.splitext(fname)[0]
    known = {n["id"]: n for n in pf.NODES}

    if stem not in known:
        return {"file": fname, "node": stem, "ok": False, "will_pass": False,
                "problems": ["不是已知节点 id，执行器读不到它"]}

    node = known[stem]
    p = os.path.join(verdicts_dir(project), fname)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            v = json.load(fh)
    except (ValueError, OSError) as e:
        return {"file": fname, "node": stem, "ok": False, "will_pass": False,
                "problems": ["JSON 读不出来：%s（执行器会当空处理 → 直接 fail）" % e]}

    if not isinstance(v, dict):
        return {"file": fname, "node": stem, "ok": False, "will_pass": False,
                "problems": ["顶层不是对象，无法作为判定读取"]}

    judge, reason, score = v.get("judge"), v.get("reason"), v.get("score")
    problems = []
    # kind 区分两种"不通过"，处理方式完全不同：
    #   invalid     判定本身不成立（没署名/没判据/JSON 坏/缺分数）
    #               → 这不是判决，退回判定者重投，不吃重试次数
    #   below_floor 判定成立，但给了低分 → 这是一次真实否决
    #               → 计入重试，累计超限自动搁置（不发）
    kind = "ok"

    if not judge:
        problems.append("缺 judge：判定者没署名，事后翻账查不出是谁判的")
        kind = "invalid"
    if not reason:
        problems.append("缺 reason：没有判据，判定无法被复核")
        kind = "invalid"

    will_pass = True
    if node["min_score"] is not None:
        if score is None:
            problems.append("缺 score：该节点有下限 %s，缺分数会被自动判 fail"
                            % node["min_score"])
            will_pass = False
            kind = "invalid"
        else:
            try:
                if float(score) < float(node["min_score"]):
                    problems.append("分数 %s 低于下限 %s：这票会被自动判 fail"
                                    % (score, node["min_score"]))
                    will_pass = False
                    if kind == "ok":
                        kind = "below_floor"
            except (TypeError, ValueError):
                problems.append("score 不是数字：%r" % (score,))
                will_pass = False
                kind = "invalid"
    else:
        try:
            if score is not None:
                float(score)
        except (TypeError, ValueError):
            problems.append("score 不是数字：%r" % (score,))
            will_pass = False
            kind = "invalid"

    out = {
        "file": fname, "node": stem, "node_name": node["name"],
        "judge": judge, "score": score, "min_score": node["min_score"],
        "kind": kind,
        "will_pass": will_pass and bool(judge) and bool(reason),
        "problems": problems,
    }
    if stem != current:
        out["note"] = "当前停在 %s，这份判定要等到那一步才会被读到" % current
    return out


def cmd_collect(args):
    st = pf.load_state(args.project)
    vd = verdicts_dir(args.project)
    current = pf.NODES[st["node_index"]]["id"] if st["state"] == "in_progress" else None

    files = sorted(f for f in os.listdir(vd) if f.endswith(".json")) \
        if os.path.isdir(vd) else []

    delivered = [_validate(args.project, f, current) for f in files]
    awaiting = current if (current and current in le.EXTERNAL_NODES) else None
    missing = bool(awaiting) and not os.path.exists(
        os.path.join(vd, "%s.json" % awaiting))

    emit({
        "state": st["state"],
        "current_node": current,
        "awaiting_verdict": awaiting,
        "missing_current_verdict": missing,
        "delivered": delivered,
        "not_passing": [d["node"] for d in delivered if not d.get("will_pass")],
        "all_delivered_ok": all(d.get("will_pass") for d in delivered),
        "ready_to_advance": (awaiting is None) or not missing,
    })
    return 0


# ---------------------------------------------------------------- 状态
def cmd_status(args):
    st = pf.load_state(args.project)
    current = pf.NODES[st["node_index"]]["id"] if st["state"] == "in_progress" else None
    external = bool(current) and current in le.EXTERNAL_NODES
    has_v = bool(current) and os.path.exists(
        os.path.join(verdicts_dir(args.project), "%s.json" % current))
    has_task = bool(current) and os.path.exists(
        os.path.join(pending_dir(args.project), "%s.task.json" % current))

    emit({
        "state": st["state"],
        "current_node": current,
        "current_name": pf.NODES[st["node_index"]]["name"] if current else None,
        "judged_by": ("外部判定者（收件箱）" if external
                      else ("机器（执行器自动跑脚本）" if current else None)),
        "needs_dispatch": external and not has_v,
        "pending_task": has_task,
        "verdict_delivered": has_v,
        "progress": "%d/%d" % (st["node_index"], len(pf.NODES)),
        "ledger_rows": len(pf.read_ledger(args.project)),
    })
    return 0


# ---------------------------------------------------------------- 自检
def cmd_test(_args=None):
    tmp = tempfile.mkdtemp(prefix="vdispatch-test-")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    def mkproj(name):
        p = os.path.join(tmp, name)
        os.makedirs(p)
        _write_text(os.path.join(p, "README.md"),
                    "# demo\n\n给你的一条命令，装上就能用，实测 500 条 3 秒。\n"
                    "\n## 用法\n\n```\ndemo run\n```\n")
        _write_text(os.path.join(p, "SKILL.md"),
                    "---\nname: demo\ndescription: x\n触发词：a、b、c、d、e\n---\n"
                    "\n# demo\n\n## 用法\n\n跑。\n")
        ok, out = pf._quiet(pf.cmd_init, pf._ns(project=p))
        assert ok, "init 失败：%s" % out
        return p

    def advance_before(p, nid):
        st = pf.load_state(p)
        while st["state"] == "in_progress":
            node = pf.NODES[st["node_index"]]
            if node["id"] == nid:
                break
            pf._quiet(pf.cmd_done, pf._ns(project=p, node=node["id"], score=5,
                                          judge=node["judge"], reason="ok"))
            st = pf.load_state(p)

    def put(p, node, obj):
        _write_json(os.path.join(verdicts_dir(p), "%s.json" % node), obj)

    def _capture(fn, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(argparse.Namespace(**kw))
        return json.loads(buf.getvalue())

    def collect(p):
        return _capture(cmd_collect, project=p)

    try:
        # 1) 机器节点不该派发
        p0 = mkproj("case1")
        b0 = build_brief(p0)
        check("机器节点不派发（N0 由脚本判）",
              b0["ok"] is False and "机器判" in b0["reason"],
              b0.get("reason", "")[:50])

        s0 = _capture(cmd_status, project=p0)
        check("status 认得出当前节点由谁判",
              s0["current_node"] == "N0" and "机器" in s0["judged_by"]
              and s0["needs_dispatch"] is False, str(s0)[:60])

        # 2) 语义节点出题
        p1 = mkproj("case2")
        advance_before(p1, "N4")
        brief = build_brief(p1)
        check("语义节点出题（N4）", brief["ok"] and brief["node"] == "N4",
              str(brief.get("reason", ""))[:50])
        check("任务单带材料摘要（README + SKILL 两份）",
              len(brief["must_read"]) == 2
              and all(m.get("exists") for m in brief["must_read"]),
              str([m.get("exists") for m in brief["must_read"]]))
        check("任务单带打分标准与硬约束",
              len(brief["rubric"]) == 6 and len(brief["constraints"]) >= 5,
              "rubric=%d constraints=%d" % (len(brief["rubric"]),
                                            len(brief["constraints"])))
        check("任务单写明回填路径",
              brief["reply_to"].endswith(os.path.join("verdicts", "N4.json")),
              brief["reply_to"])
        check("任务单不含结论（只给材料，不给判断）",
              "verdict" not in brief.get("reason", "")
              and brief.get("good_looks_like") == pf.NODES[4]["good"],
              "")

        # 2b) 无现成产物的节点：任务单必须给"取证据的命令"，不能空手
        p1b = mkproj("case2b")
        advance_before(p1b, "N5")
        brief5 = build_brief(p1b)
        check("N5 任务单带取证据命令（该步没有现成产物）",
              brief5["ok"] and len(brief5.get("must_run") or ()) >= 2,
              "must_run=%s" % (brief5.get("must_run"),))
        check("N5 任务单不虚构材料文件",
              brief5["must_read"] == [] or all(m.get("exists")
                                               for m in brief5["must_read"]),
              str(brief5["must_read"])[:60])

        # 2c) 证据闸门：材料与命令皆空 → 拒绝出题（判定者只能盖章）
        saved = dict(MATERIALS)
        MATERIALS["N4"] = {"files": (), "commands": (), "hint": ""}
        try:
            b_gate = build_brief(p1)
            check("零证据的任务单 → 拒绝出题",
                  b_gate["ok"] is False and "证据" in b_gate["reason"],
                  str(b_gate.get("reason", ""))[:60])
        finally:
            MATERIALS.clear()
            MATERIALS.update(saved)

        # 3) 出题不代判：pending 写了，verdicts 不动
        _capture(cmd_brief, project=p1, node=None)
        check("出题写 pending 任务单",
              os.path.exists(os.path.join(pending_dir(p1), "N4.task.json")), "")
        check("出题不写收件箱（派发者不代判）",
              not os.path.exists(os.path.join(verdicts_dir(p1), "N4.json")), "")

        # 4) 收卷：无判定 → 报缺
        c0 = collect(p1)
        check("收卷报缺当前节点判定",
              c0["missing_current_verdict"] and c0["ready_to_advance"] is False,
              str(c0)[:60])

        # 5) 合法判定 → 会通过
        put(p1, "N4", {"score": 4.5, "judge": "reader-1",
                       "reason": "README.md:3 首屏讲清了装的收益"})
        c1 = collect(p1)
        check("合法判定 → will_pass 且不再报缺",
              c1["all_delivered_ok"] and not c1["missing_current_verdict"]
              and c1["delivered"][0]["will_pass"], str(c1["delivered"][0])[:80])

        # 6) 低分 → 会被自动判 fail
        put(p1, "N4", {"score": 1, "judge": "reader-1", "reason": "看不懂"})
        c2 = collect(p1)
        check("低于下限 → 收卷提前拦下（不等执行器）",
              c2["not_passing"] == ["N4"] and not c2["delivered"][0]["will_pass"],
              str(c2["not_passing"]))
        check("低于下限归类 below_floor（真实否决，吃重试）",
              c2["delivered"][0]["kind"] == "below_floor",
              str(c2["delivered"][0]["kind"]))

        # 7) 缺署名
        put(p1, "N4", {"score": 4.5, "reason": "还行"})
        c3 = collect(p1)
        check("缺署名 → 收卷报出",
              any("缺 judge" in p for p in c3["delivered"][0]["problems"]),
              str(c3["delivered"][0]["problems"])[:80])
        check("缺署名归类 invalid（判定不成立，退回重投）",
              c3["delivered"][0]["kind"] == "invalid",
              str(c3["delivered"][0]["kind"]))

        # 8) 缺判据
        put(p1, "N4", {"score": 4.5, "judge": "reader-1"})
        c4 = collect(p1)
        check("缺判据 → 收卷报出",
              any("缺 reason" in p for p in c4["delivered"][0]["problems"]),
              str(c4["delivered"][0]["problems"])[:80])

        # 9) 有下限但缺分数
        put(p1, "N4", {"judge": "reader-1", "reason": "还行"})
        c5 = collect(p1)
        check("有下限却缺分数 → 会被判 fail",
              not c5["delivered"][0]["will_pass"], str(c5["delivered"][0])[:80])

        # 10) JSON 非法
        _write_text(os.path.join(verdicts_dir(p1), "N4.json"), "{坏掉的 json")
        c6 = collect(p1)
        check("JSON 非法 → 收卷报出（执行器会静默当空）",
              any("JSON" in p for p in c6["delivered"][0]["problems"]),
              str(c6["delivered"][0]["problems"])[:80])

        # 11) 未来节点的判定 → 标注稍后才读
        put(p1, "N4", {"score": 4.5, "judge": "reader-1", "reason": "ok"})
        put(p1, "N6", {"score": 4, "judge": "releaser-1", "reason": "pre-判"})
        c7 = collect(p1)
        n6 = [d for d in c7["delivered"] if d["node"] == "N6"][0]
        check("未来节点的判定会被标注（当前读不到）",
              "note" in n6 and "N4" in n6["note"], n6.get("note", "")[:60])

        # 12) 节点不匹配 → 拒绝
        b12 = build_brief(p1, "N5")
        check("请求非当前节点 → 拒绝（不许跳步）",
              b12["ok"] is False and "不匹配" in b12["reason"],
              b12.get("reason", "")[:50])

        # 13) 收卷不改写（幂等）
        before = open(os.path.join(verdicts_dir(p1), "N4.json"),
                      encoding="utf-8").read()
        collect(p1)
        after = open(os.path.join(verdicts_dir(p1), "N4.json"),
                     encoding="utf-8").read()
        check("收卷只读不改（判定内容原样）", before == after, "")

        # 14) 终态后不出题
        p2 = mkproj("case3")
        for n in pf.NODES:
            pf._quiet(pf.cmd_done, pf._ns(project=p2, node=n["id"], score=5,
                                          judge=n["judge"], reason="ok"))
        b14 = build_brief(p2)
        check("流程已结束 → 不再出题",
              b14["ok"] is False and b14.get("done") is True,
              str(b14)[:50])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("verdict_dispatch.py 自检 —— %d 项" % len(results))
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
    print("自检通过：机器节点不派发、语义节点出题带材料与标准、收卷只读不改。")
    return 0


def _write_text(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------- 入口
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="verdict_dispatch.py",
        description="判定派发器：出题（生成判定任务单）+ 收卷（校验判定合法性）")
    ap.add_argument("--project", default=os.getcwd(), help="项目根目录（默认当前目录）")
    ap.add_argument("--test", action="store_true", help="跑内置自检，不需要项目")
    ap.add_argument("--version", action="version", version="1.0.0")

    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="看当前节点该由谁判、缺什么")

    b = sub.add_parser("brief", help="出题：生成当前节点的判定任务单")
    b.add_argument("--node", default=None, help="指定节点（默认当前节点）")

    sub.add_parser("collect", help="收卷：校验已投递的判定")

    args = ap.parse_args(argv)

    if args.test:
        return cmd_test()

    if not args.cmd:
        ap.print_help()
        return 0

    return {
        "status": cmd_status,
        "brief": cmd_brief,
        "collect": cmd_collect,
    }[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
