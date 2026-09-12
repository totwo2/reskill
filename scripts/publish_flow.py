#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_flow.py — 发布流程状态机（无人值守版 · slice 1）

三权分立里，本脚本独占「推进权」：
    持状态 · 管推进 · 记判决账本

它不生成内容（执行者是外部子 agent），也不判质量（判定结论由 done 回抛）。
它只做一件事：让流程不可能被跳过，让每一次判定都留下可对账的凭据。

无人值守语义（这是与旧版最大的差别）：
    任一步不过 → 自动打回重试 → 累计达 MAX_ROUNDS 仍不过 → 终态 deferred
    deferred = 没发出去，但也没失败，报告一直在，你想看再翻。

    两个终态，只有两个：
      released  已发布
      deferred  已搁置（默认安全位）

节点表本身就是「质量卡」的定义：每个节点写明它要交什么、好长什么样、
谁来判、分数下限。加节点只改 NODES，不改逻辑。

用法：
    python3 publish_flow.py --project <路径> init
    python3 publish_flow.py --project <路径> next
    python3 publish_flow.py --project <路径> done N2 --score 4 --judge quality --reason "..."
    python3 publish_flow.py --project <路径> status
    python3 publish_flow.py --project <路径> run --auto
    python3 publish_flow.py --test
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

VERSION = "3.0.0-slice1"

MAX_ROUNDS = 3          # 单节点累计打回上限，达到即 deferred
STAGING = ".publish-staging"
STATE_FILE = ".publish-state.json"
LEDGER_FILE = "ledger.jsonl"

# ---------------------------------------------------------------- 节点表
# need      : 该节点必须落地的产物（None = 无文件产物，只看判定）
# min_score : 分数下限，None = 只判 pass/fail
# judge     : 该节点的判定者身份（署名用）
# good      : 质量卡的「合格样本」——这一步的好长什么样
NODES = [
    {
        "id": "N0", "name": "形态判定", "need": "form.json", "min_score": None,
        "judge": "script",
        "good": "判定出 gh / sh / installer 三条路径中的一条，并给出依据",
    },
    {
        "id": "N1", "name": "事实表", "need": "fact-sheet.md", "min_score": None,
        "judge": "audit",
        "good": "每条数字都有出处与日期，无来源不明的数据",
    },
    {
        "id": "N2", "name": "写发布物", "need": "README.md", "min_score": 3,
        "judge": "quality",
        "good": "前 30 行让一个陌生人明白装了能得到什么",
    },
    {
        "id": "N3", "name": "硬闸门", "need": None, "min_score": None,
        "judge": "script",
        "good": "形式类检查全绿：文件在、格式对、元数据齐",
    },
    {
        "id": "N4", "name": "质量裁判", "need": None, "min_score": 3,
        "judge": "quality",
        "good": "独立判定者按该步产物的真实用户身份打分，判据带锚点",
    },
    {
        "id": "N5", "name": "装配", "need": None, "min_score": None,
        "judge": "audit",
        "good": "只动了该动的文件，没有顺手优化别处",
    },
    {
        "id": "N6", "name": "发布", "need": None, "min_score": None,
        "judge": "script",
        "good": "双平台产物齐备，Release 已建成",
    },
    {
        "id": "N7", "name": "收口", "need": None, "min_score": None,
        "judge": "script",
        "good": "三行契约齐、监控清单已同步",
    },
]

VALID_STATES = ("in_progress", "released", "deferred")


# ---------------------------------------------------------------- 基础设施
def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def die(msg, code=1):
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(code)


def staging_dir(project):
    return os.path.join(project, STAGING)


def state_path(project):
    return os.path.join(staging_dir(project), STATE_FILE)


def ledger_path(project):
    return os.path.join(staging_dir(project), LEDGER_FILE)


def load_state(project):
    p = state_path(project)
    if not os.path.exists(p):
        die("尚未 init：找不到 %s" % p)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(project, st):
    d = staging_dir(project)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(state_path(project), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_ledger(project, row):
    d = staging_dir(project)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(ledger_path(project), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_ledger(project):
    p = ledger_path(project)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- 核心推进
def _apply_verdict(project, st, node, passed, score, judge, reason, artifact):
    """唯一的推进入口。判决落账 → 改状态 → 存盘。"""
    nid = node["id"]
    attempt = st["attempts"].get(nid, 0) + 1

    row = {
        "ts": now(),
        "node": nid,
        "node_name": node["name"],
        "attempt": attempt,
        "verdict": "pass" if passed else "fail",
        "score": score,
        "min_score": node["min_score"],
        "judge": judge,
        "reason": reason,
        "artifact": artifact or node["need"],
    }
    append_ledger(project, row)

    if passed:
        st["node_index"] += 1
        if st["node_index"] >= len(NODES):
            st["state"] = "released"
    else:
        st["attempts"][nid] = attempt
        if attempt >= MAX_ROUNDS:
            st["state"] = "deferred"

    st["updated_at"] = now()
    save_state(project, st)
    return row


def _node_card(st):
    node = NODES[st["node_index"]]
    return {
        "node": node["id"],
        "name": node["name"],
        "attempt_next": st["attempts"].get(node["id"], 0) + 1,
        "max_rounds": MAX_ROUNDS,
        "artifact_required": node["need"],
        "min_score": node["min_score"],
        "judge": node["judge"],
        "quality_card": {"good_looks_like": node["good"]},
        "staging": staging_dir(st["project"]),
    }


# ---------------------------------------------------------------- 命令
def cmd_init(args):
    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        die("项目路径不存在：%s" % project)
    os.makedirs(staging_dir(project), exist_ok=True)
    st = {
        "version": VERSION,
        "project": project,
        "mode": "auto",
        "state": "in_progress",
        "node_index": 0,
        "attempts": {},
        "started_at": now(),
        "updated_at": now(),
    }
    save_state(project, st)
    emit({"ok": True, "project": project, "state": st["state"],
          "node": NODES[0]["id"], "staging": staging_dir(project)})


def cmd_next(args):
    st = load_state(args.project)
    if st["state"] != "in_progress":
        emit({"done": True, "state": st["state"], "node_index": st["node_index"]})
        return
    emit(_node_card(st))


def cmd_done(args):
    st = load_state(args.project)
    if st["state"] != "in_progress":
        die("流程已结束（%s），不能再记录判定" % st["state"])

    node = NODES[st["node_index"]]
    if args.node != node["id"]:
        die("节点不匹配：当前停在 %s，你提交的是 %s —— 不许跳步"
            % (node["id"], args.node))

    passed = (args.verdict == "pass")
    if passed and node["min_score"] is not None:
        if args.score is None:
            passed = False
            args.reason = (args.reason + " " if args.reason else "") + \
                          "[自动判 fail：该步有分数下限 %s，但没给分数]" % node["min_score"]
        elif args.score < node["min_score"]:
            passed = False
            args.reason = (args.reason + " " if args.reason else "") + \
                          "[自动判 fail：得分 %s < 下限 %s]" % (args.score, node["min_score"])

    row = _apply_verdict(args.project, st, node, passed, args.score,
                         args.judge, args.reason, args.artifact)
    emit({"ok": True, "node": node["id"], "verdict": row["verdict"],
          "score": row["score"], "min_score": node["min_score"],
          "attempt": row["attempt"], "max_rounds": MAX_ROUNDS,
          "state": st["state"], "node_index": st["node_index"],
          "next_node": NODES[st["node_index"]]["id"] if st["state"] == "in_progress" else None})


def cmd_status(args):
    st = load_state(args.project)
    led = read_ledger(args.project)
    cur = NODES[st["node_index"]]["id"] if st["state"] == "in_progress" else None
    emit({
        "state": st["state"],
        "current_node": cur,
        "progress": "%d/%d" % (st["node_index"], len(NODES)),
        "attempts": st["attempts"],
        "ledger_rows": len(led),
        "started_at": st["started_at"],
        "updated_at": st["updated_at"],
    })


def _run_external(project, node, attempt, cmd):
    """调外部执行器（真实执行器的接入点）。

    约定——环境变量传入上下文：
        PFLOW_NODE / PFLOW_STAGING / PFLOW_ATTEMPT / PFLOW_NEED / PFLOW_MIN_SCORE
    约定——stdout 最后一行 JSON 回抛判定：
        {"verdict": "pass|fail", "score": 0-5|null, "reason": "可验证的判据"}
    退出码非 0，或没给出 JSON → 一律判 fail（默认安全位）。
    """
    env = dict(os.environ)
    env.update({
        "PFLOW_NODE": node["id"],
        "PFLOW_STAGING": staging_dir(project),
        "PFLOW_ATTEMPT": str(attempt),
        "PFLOW_NEED": node["need"] or "",
        "PFLOW_MIN_SCORE": "" if node["min_score"] is None else str(node["min_score"]),
    })

    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, env=env, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, None, "[执行器超时 1800s] %s" % cmd
    except Exception as e:                       # noqa: BLE001
        return False, None, "[执行器无法启动：%s] %s" % (e, cmd)

    if r.returncode != 0:
        return False, None, "[执行器 exit %d] %s" % (
            r.returncode, (r.stderr or "").strip()[:200])

    payload = None
    for line in reversed((r.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    if payload is None:
        return False, None, ("[执行器未回抛 JSON 判定] %s"
                             % (r.stdout or "").strip()[:200])

    verdict = payload.get("verdict", "fail")
    return (verdict == "pass"), payload.get("score"), payload.get("reason", "")


def cmd_run(args):
    """无人值守推进。

    两种执行器：
      内置占位（默认）  产物存在即视为通过 —— 只验机制，不产内容
      外部（--exec）    真实执行器的接入点，负责生成产物并回抛判定
    """
    st = load_state(args.project)
    trace = []
    guard = 0
    external = bool(getattr(args, "exec_cmd", None))

    while st["state"] == "in_progress" and guard < 200:
        guard += 1
        node = NODES[st["node_index"]]
        attempt = st["attempts"].get(node["id"], 0) + 1

        if external:
            passed, score, reason = _run_external(
                st["project"], node, attempt, args.exec_cmd)
        else:
            sd = staging_dir(st["project"])
            if node["need"]:
                ok = os.path.exists(os.path.join(sd, node["need"]))
                reason = ("产物存在：%s" % node["need"]) if ok \
                    else ("缺产物：%s" % node["need"])
            else:
                ok = True
                reason = "无文件产物，占位执行器直接放行"
            passed, score = ok, (4 if (ok and node["min_score"] is not None) else None)

        if passed and node["min_score"] is not None:
            if score is None or score < node["min_score"]:
                passed = False
                reason = "%s [自动判 fail：分数 %s < 下限 %s]" % (
                    reason, score, node["min_score"])

        row = _apply_verdict(st["project"], st, node, passed, score,
                             node["judge"], reason, node["need"])
        trace.append({"node": node["id"], "verdict": row["verdict"],
                      "attempt": row["attempt"]})
        if st["state"] != "in_progress":
            break

    emit({"ok": True, "state": st["state"], "node_index": st["node_index"],
          "executor": "external" if external else "placeholder",
          "trace": trace})


# ---------------------------------------------------------------- 自检
def _ns(**kw):
    base = {"project": None, "node": None, "score": None,
            "judge": "quality", "reason": "", "verdict": "pass",
            "artifact": None, "exec_cmd": None}
    base.update(kw)
    return argparse.Namespace(**base)


def _quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            fn(*a, **kw)
            return True, buf.getvalue()
        except SystemExit as e:
            return (e.code in (0, None)), buf.getvalue()


def cmd_test(_args=None):
    tmp = tempfile.mkdtemp(prefix="pflow-test-")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    def mkproj(name, artifacts=()):
        p = os.path.join(tmp, name)
        os.makedirs(p)
        ok, _ = _quiet(cmd_init, _ns(project=p))
        assert ok, "init 失败"
        for a in artifacts:
            with open(os.path.join(staging_dir(p), a), "w", encoding="utf-8") as f:
                f.write("x\n")
        return p

    try:
        # 场景 1：显式全过 → released
        p1 = mkproj("case1")
        for n in NODES:
            _quiet(cmd_done, _ns(project=p1, node=n["id"], score=4,
                                 judge=n["judge"], reason="ok"))
        st = load_state(p1)
        check("场景1 全过 → released", st["state"] == "released",
              "实际=%s" % st["state"])
        check("场景1 节点走满", st["node_index"] == len(NODES),
              "node_index=%s" % st["node_index"])
        led = read_ledger(p1)
        check("场景1 账本行数 = 判决次数", len(led) == len(NODES),
              "%d vs %d" % (len(led), len(NODES)))
        check("场景1 账本带分数与署名",
              all(r["score"] is not None or r["min_score"] is None for r in led)
              and all(r["judge"] for r in led),
              "")

        # 场景 2：分数低于下限 → 自动 fail，连续 3 次 → deferred
        p2 = mkproj("case2")
        for i in range(MAX_ROUNDS):
            _quiet(cmd_done, _ns(project=p2, node="N0", score=5, reason="过 N0"))
            _quiet(cmd_done, _ns(project=p2, node="N1", score=5, reason="过 N1"))
            _quiet(cmd_done, _ns(project=p2, node="N2", score=1,
                                 judge="quality", reason="不像给人看的"))
        st2 = load_state(p2)
        check("场景2 低分被自动判 fail", st2["attempts"].get("N2") == MAX_ROUNDS,
              "attempts=%s" % st2["attempts"])
        check("场景2 超限 → deferred（不发）", st2["state"] == "deferred",
              "实际=%s" % st2["state"])
        led2 = read_ledger(p2)
        fails = [r for r in led2 if r["node"] == "N2" and r["verdict"] == "fail"]
        check("场景2 每次打回都落账", len(fails) == MAX_ROUNDS,
              "%d 条" % len(fails))

        # 场景 3：跳步被拒
        p3 = mkproj("case3")
        ok3, out3 = _quiet(cmd_done, _ns(project=p3, node="N3", score=5))
        check("场景3 跳步被拒", not ok3 and "不许跳步" in out3, out3.strip()[:60])

        # 场景 4：终态后不能再记判定
        p4 = mkproj("case4")
        for n in NODES:
            _quiet(cmd_done, _ns(project=p4, node=n["id"], score=5, judge=n["judge"]))
        ok4, out4 = _quiet(cmd_done, _ns(project=p4, node="N7", score=5))
        check("场景4 终态后拒收判定", not ok4 and "已结束" in out4, out4.strip()[:60])

        # 场景 5：run --auto 产物齐全 → released
        p5 = mkproj("case5", artifacts=("form.json", "fact-sheet.md", "README.md"))
        _quiet(cmd_run, _ns(project=p5))
        st5 = load_state(p5)
        check("场景5 自动模式 → released", st5["state"] == "released",
              "实际=%s" % st5["state"])

        # 场景 6：run --auto 缺产物 → 反复打回 → deferred
        p6 = mkproj("case6")
        _quiet(cmd_run, _ns(project=p6))
        st6 = load_state(p6)
        check("场景6 自动模式缺产物 → deferred", st6["state"] == "deferred",
              "实际=%s" % st6["state"])

        # 场景 7：外部执行器（产物 + JSON 回抛）→ released
        ex_ok = os.path.join(tmp, "exec_ok.sh")
        with open(ex_ok, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env bash\n")
            f.write('if [ -n "$PFLOW_NEED" ]; then : > "$PFLOW_STAGING/$PFLOW_NEED"; fi\n')
            f.write('echo \'{"verdict": "pass", "score": 4, "reason": "外部执行器占位"}\'\n')
        os.chmod(ex_ok, 0o755)

        p7 = mkproj("case7")
        _quiet(cmd_run, _ns(project=p7, exec_cmd=ex_ok))
        st7 = load_state(p7)
        check("场景7 外部执行器 → released", st7["state"] == "released",
              "实际=%s" % st7["state"])
        led7 = read_ledger(p7)
        check("场景7 外部判定照样落账",
              len(led7) == len(NODES) and all(r["judge"] for r in led7),
              "%d 条" % len(led7))

        # 场景 8：外部执行器失败 → 反复打回 → deferred
        ex_bad = os.path.join(tmp, "exec_bad.sh")
        with open(ex_bad, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env bash\n")
            f.write('echo "boom" >&2\n')
            f.write("exit 1\n")
        os.chmod(ex_bad, 0o755)

        p8 = mkproj("case8")
        _quiet(cmd_run, _ns(project=p8, exec_cmd=ex_bad))
        st8 = load_state(p8)
        check("场景8 执行器失败 → deferred", st8["state"] == "deferred",
              "实际=%s" % st8["state"])
        check("场景8 失败原因照样落账",
              any("执行器 exit" in (r.get("reason") or "")
                  for r in read_ledger(p8)), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("publish_flow.py 自检 —— %d 项" % len(results))
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
    print("自检通过：状态机可跑、跳步被拒、低分不放行、超限自动不发。")
    return 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    p = argparse.ArgumentParser(
        prog="publish_flow.py",
        description="发布流程状态机（无人值守版）：持状态、管推进、记判决账本")
    p.add_argument("--project", default=os.getcwd(), help="项目根目录（默认当前目录）")
    p.add_argument("--test", action="store_true", help="跑内置自检，不需要项目")
    p.add_argument("--version", action="version", version=VERSION)

    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("init", help="开一次发布")
    sub.add_parser("next", help="取当前节点任务卡")
    sub.add_parser("status", help="看状态与账本概况")

    d = sub.add_parser("done", help="提交一次判定")
    d.add_argument("node", help="节点 id，如 N2")
    d.add_argument("--score", type=int, default=None, help="0-5 分")
    d.add_argument("--judge", default="quality", help="判定者署名")
    d.add_argument("--reason", default="", help="可验证的判据")
    d.add_argument("--verdict", default="pass", choices=["pass", "fail"])
    d.add_argument("--artifact", default=None, help="产物路径")

    r = sub.add_parser("run", help="无人值守推进")
    r.add_argument("--auto", action="store_true", help="无需人工输入")
    r.add_argument("--exec", dest="exec_cmd", default=None,
                   help="外部执行器命令；留空则用内置占位执行器（产物存在即通过）")

    args = p.parse_args(argv)

    if args.test:
        return cmd_test()

    if not args.cmd:
        p.print_help()
        return 0

    return {
        "init": cmd_init,
        "next": cmd_next,
        "done": cmd_done,
        "status": cmd_status,
        "run": cmd_run,
    }[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
