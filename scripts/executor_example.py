#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
executor_example.py — 外部执行器的接入样板

接入方式：
    python3 scripts/publish_flow.py --project <项目> run --auto \
        --exec "python3 scripts/executor_example.py"

它示范了执行器必须满足的两个约定：

  1. 从环境变量读上下文
       PFLOW_NODE      当前节点，如 N2
       PFLOW_STAGING   暂存区路径（产物写这里）
       PFLOW_ATTEMPT   这是第几轮（打回会累加）
       PFLOW_NEED      该节点必须交出的产物
       PFLOW_MIN_SCORE 分数下限（空字符串 = 该节点不看分数）

  2. 在 stdout 最后一行回抛判定
       {"verdict": "pass|fail", "score": 0-5|null, "reason": "可验证的判据"}

    退出码非 0、或没给出 JSON → 自动判 fail（默认安全位，宁可搁置不可错发）。

把 do_work() 换成真正的活，这个执行器就变成真的了。
"""

import json
import os
import sys


def do_work(node, staging, attempt, need, min_score):
    """占位实现：让产物存在，并给一个刚好及格的分数。

    真正要接的三件事（对应 publish-expert-team.md 的节点表）：
        N0   形态判定      → 调 detect_publish_form.sh
        N2   写发布物      → 派子 agent 写 README / SKILL.md
        N4   质量裁判      → 派只读子 agent（独立模型）打分，并附可验证判据
    其余节点按同法各自实现。
    """
    if need:
        path = os.path.join(staging, need)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("placeholder for %s (attempt %d)\n" % (need, attempt))

    score = int(min_score) if min_score else None
    return {
        "verdict": "pass",
        "score": score,
        "reason": "占位执行器：产物 %s 就绪（第 %d 轮）" % (need or "无", attempt),
    }


def main():
    node = os.environ.get("PFLOW_NODE", "")
    staging = os.environ.get("PFLOW_STAGING", ".")
    attempt = int(os.environ.get("PFLOW_ATTEMPT", "1") or "1")
    need = os.environ.get("PFLOW_NEED", "")
    min_score = os.environ.get("PFLOW_MIN_SCORE", "")

    if not os.path.isdir(staging):
        os.makedirs(staging)

    verdict = do_work(node, staging, attempt, need, min_score or None)
    sys.stdout.write(json.dumps(verdict, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
