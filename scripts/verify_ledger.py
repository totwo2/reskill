#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ledger.py —— 判决账本的「独立性证据」校验

**先说清一件事（老高 2026-09-23 17:44 指正，本脚本因此重写）**

判定者**永远是同一个大模型**。这是物理事实，任何设计都改变不了 ——
所谓"专家团队的不同专家"，本质是同一个模型扮演不同角色，最多是 `笛子(质量裁判)` 加个括号。

所以本脚本**不查"判定者名字是否互不相同"**（初版查这个，前提就错了）：
- 换个括号就绕过去了，查不出任何真东西；
- 更糟的是它会给出**虚假安心** —— 仿佛改了名字就有了独立判断。

**"独立"要的不是换脑子，是换输入 + 断锚定。** 同一个模型，只要满足四条，就能产出**有效**的独立判定：

  ① 只看产物，不看作者的推理 —— 作者的自我合理化不会被继承
  ② 判定者之间互不可见 —— 不会被先出的判定锚定
  ③ 每步是新实例 —— 不带着"我刚写的所以它对"这个前提
  ④ 身份只给该看的（J2 只给前 30 行）

**本脚本查的是这四条在账本上留下的可校验痕迹**：

| 查什么 | 为什么它能证明"独立" |
|---|---|
| 判定理由**必须带锚点**（`文件:行号` / 命令输出 / 实测结果） | 凭印象的判定 = 没真去看产物 |
| 判定理由**不得出现作者视角**（"设计意图 / 我写的 / 本意是 / 我们打算"） | 作者回读的语言指纹 —— 出现即说明它站在写手的位置判自己 |
| 判定理由**不得引用别的判定**（"上一轮判定说 / 见 N4.json"） | 引用即说明判定者互相可见 → 锚定发生了 |
| 判定**必须署名 + 有理由** | 无署名判定不予采信 |

**判定者主体只有 1 个 → 只报告，不判错。** 那是事实，不是缺陷；报告它是为了让读的人
知道"这一版没有任何跨模型的独立视角"，而不是让它冒充"三权分立已成立"。

用法：
    python3 verify_ledger.py <ledger.jsonl> [--json]
    python3 verify_ledger.py <项目目录>            # 自动找 <项目>/.publish-staging/ledger.jsonl
    python3 verify_ledger.py --test

退出码：0 = 通过；1 = 有拒收项；2 = 用法错。
"""

import argparse
import json
import os
import re
import sys

# 这些节点是"判定节点"（要外部主体投判定），脚本节点（N0/N3）不算
# 依据 publish_flow.py 的 NODES：external=True 的那几个 + N1(judge=audit)
JUDGE_NODES = ("N1", "N4", "N5", "N6", "N7")

# 机器侧判定者：这些不算"外部裁判"，不查独立性证据（脚本本来就是脚本）
MACHINE_JUDGES = {"script", "audit", "quality", "releaser", ""}

# 署名里去掉括号后缀，看"主体"是谁（只用于报告，不用于判错）
PAREN_RE = re.compile(r"[（(].*?[)）]")

# ① 锚点：证明判定者"真去看过产物"，而不是凭印象
ANCHOR_RE = re.compile(
    r"[\w./-]+\.(?:py|sh|bash|js|mjs|cjs|ts|go|java|c|cc|cpp|h|cs|rb|php|rs|lua"
    r"|md|json|yaml|yml|toml|txt|cfg|ini):\d+"      # 文件:行号
    r"|第\s*\d+\s*行"                                 # 第 N 行
    r"|exit\s*[=＝]?\s*\d+"                          # exit 0
    r"|\d+\s*(?:PASS|FAIL|通过|失败)"                 # 6 PASS
    r"|\b(?:grep|python3?|pytest|npm|node)\b"        # 跑了命令
    r"|\bgit\s+(?:status|diff|log|show)\b"
    r"|--test\b"
)

# ② 作者回读的语言指纹：出现这些 = 它站在写手的位置判自己
AUTHOR_VOICE = (
    "设计意图", "本意是", "我写的", "我原本", "我们打算", "我的实现", "设计上",
    "按我的设计", "我故意", "我特意",
    "design intent", "i wrote", "we intended", "my implementation", "as i designed",
)

# ③ 引用别的判定 = 判定者互相可见 → 锚定已经发生
CROSS_REF = (
    "上一轮判定", "上轮判定", "前一个判定", "其他判定者", "别的判定",
    "prev verdict", "previous verdict", "other judges",
)
CROSS_REF_RE = re.compile(r"见\s*N\d|见N\d")


def normalize_judge(j):
    s = (j or "").strip()
    s = PAREN_RE.sub("", s).strip()
    return s


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"_bad": f"第 {n} 行不是合法 JSON"})
    return rows


def check_ledger(rows):
    """返回 (findings, stats)；findings = [(级别, 说明), ...]"""
    findings = []
    bad = [r for r in rows if "_bad" in r]
    for r in bad:
        findings.append(("error", r["_bad"]))
    rows = [r for r in rows if "_bad" not in r]

    if not rows:
        findings.append(("error", "账本是空的 —— 没跑过就没有账，别当成通过"))
        return findings, {}

    # 同一判定事件被重复 append = 真实 bug（selfopt 账本里「N1 第 1 轮 judge=笛子」
    # 被记了两次，理由文本还略有出入）。判定事件由 (node, attempt, judge) 唯一标识，
    # 出现两次就是重复。报一条 note，并对后续检查去重。
    seen = set()
    dup_count = 0
    dedup = []
    for r in rows:
        key = (str(r.get("node")), str(r.get("attempt")), str(r.get("judge") or "").strip())
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        dedup.append(r)
    if dup_count:
        findings.append(("note",
            f"账本里有 {dup_count} 次「同一 (node,attempt,judge) 被记了多次」"
            f"（写账本时重复 append，理由文本可能还略有出入）—— 这本身是数据 bug，"
            f"但判定结论不因此改变，已对后续检查去重"))
    rows = dedup

    # 只取判定节点里**真正投了判定**的行（pass/fail 都算，但要有人署名）
    judge_rows = [r for r in rows if str(r.get("node", "")) in JUDGE_NODES]

    # 1) 每个判定行：署名 + 理由 + 三条独立性证据
    for r in judge_rows:
        node, att = r.get("node"), r.get("attempt")
        j = str(r.get("judge") or "").strip()
        rs = str(r.get("reason") or "").strip()
        where = f"{node} 第 {att} 轮"

        if not j:
            findings.append(("error", f"{where}：判定没有署名 —— 无署名判定不予采信"))
        if not rs:
            findings.append(("error", f"{where}：判定没有理由 —— 无判据的判定等于没判"))
        if not j or not rs or j in MACHINE_JUDGES:
            continue          # 机器侧判定者不查"独立性证据"（脚本本来就是脚本）

        # ① 锚点：真去看过产物
        if not ANCHOR_RE.search(rs):
            findings.append(("error",
                f"{where}：判定理由没有任何锚点（文件:行号 / 命令 / 实测结果）—— "
                f"凭印象的判定，不是独立判定"))

        # ② 作者回读的语言指纹
        voice = [w for w in AUTHOR_VOICE if w.lower() in rs.lower()]
        if voice:
            findings.append(("error",
                f"{where}：判定理由出现作者视角（{'、'.join(voice)}）—— "
                f"这是站在写手的位置判自己，不是独立判定"))

        # ③ 引用别的判定 = 判定者互相可见 → 锚定已发生
        cross = [w for w in CROSS_REF if w.lower() in rs.lower()]
        if CROSS_REF_RE.search(rs):
            cross.append("见 Nx")
        if cross:
            findings.append(("error",
                f"{where}：判定理由引用了别的判定（{'、'.join(cross)}）—— "
                f"判定者互相可见 = 锚定已经发生（§7.5 要求判定互不可见）"))

    # 2) 脚本节点不该冒充判定者
    for r in rows:
        if str(r.get("node")) in ("N0", "N3") and str(r.get("judge")) not in ("", "script"):
            findings.append(("warn",
                f"{r.get('node')} 是脚本节点，却由「{r.get('judge')}」署名 —— 脚本节点应当 judge=script"))

    # 3) 判定主体数量 —— **只报告，不判错**
    #    同一个大模型扮演不同角色是物理事实，加括号改变不了它。
    #    报告它是为了让读的人知道"这一版没有跨模型的独立视角"，
    #    而不是让"三权分立"这四个字冒充已经成立。
    named = [r for r in judge_rows if str(r.get("judge") or "").strip()]
    human = [r for r in named if str(r.get("judge")).strip() not in MACHINE_JUDGES]
    bodies = {normalize_judge(r["judge"]) for r in human}
    if len(human) >= 2 and len(bodies) < 2:
        who = next(iter(bodies)) if bodies else "(空)"
        findings.append(("note",
            f"判定者主体只有 1 个（「{who}」），分饰 {len(human)} 个判定节点 —— "
            f"**这是事实不是缺陷**：同一个大模型扮演不同角色，换名字改变不了共享盲区。"
            f"独立性靠的是输入隔离 + 断锚定（上面三条），不是靠换署名"))

    stats = {
        "rows": len(rows),
        "judge_rows": len(named),
        "human_judge_rows": len(human),
        "judge_bodies": sorted(bodies),
        "machine_judges_seen": sorted({str(r.get("judge")).strip() for r in named
                                       if str(r.get("judge")).strip() in MACHINE_JUDGES}),
        "nodes_judged": sorted({str(r.get("node")) for r in named}),
    }
    return findings, stats


# ---------------------------------------------------------------- 自检
GOOD = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N0", "attempt": 1, "verdict": "pass", "judge": "script", "reason": "形态=skill"},
    {"node": "N1", "attempt": 1, "verdict": "pass", "judge": "auditor-a",
     "reason": "出处覆盖率 100%（12/12），见 fact-sheet.md:3-15"},
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "reader-b",
     "reason": "README.md:5-9 钩子直给痛点；实测 1.9x 有出处"},
    {"node": "N5", "attempt": 1, "verdict": "pass", "score": 2, "judge": "assembler-c",
     "reason": "git status --short 仅新增 .publish-staging/，git diff --stat 为空"},
]) + "\n"

# 同一个主体分饰 —— 但理由带锚点。**不该判错**（这是物理事实，不是缺陷）
SAME_BODY = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N1", "attempt": 1, "verdict": "pass", "judge": "笛子",
     "reason": "出处覆盖率 100%，见 fact-sheet.md:3"},
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "笛子(质量裁判)",
     "reason": "README.md:5-9 钩子达标"},
    {"node": "N5", "attempt": 1, "verdict": "pass", "score": 2, "judge": "笛子(装配审计)",
     "reason": "git diff --stat 为空"},
]) + "\n"

NO_ANCHOR = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N1", "attempt": 1, "verdict": "pass", "judge": "a", "reason": "事实表落地"},
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "b",
     "reason": "README.md:5 达标"},
]) + "\n"

FIXTURE_AUTHOR_VOICE = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "b",
     "reason": "按我的设计意图，README.md:5 这样写是合理的"},
]) + "\n"

FIXTURE_CROSS_REF = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "b",
     "reason": "上一轮判定说没问题，README.md:5 可过"},
]) + "\n"

NO_SIGN = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N1", "attempt": 1, "verdict": "pass", "judge": "", "reason": "x"},
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "b",
     "reason": "README.md:5 达标"},
]) + "\n"

NO_REASON = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"node": "N1", "attempt": 1, "verdict": "pass", "judge": "a", "reason": ""},
    {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "b",
     "reason": "README.md:5 达标"},
]) + "\n"


def run_test():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    def write(name, text):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    try:
        f, _ = check_ledger(load_rows(write("good.jsonl", GOOD)))
        check("三个不同主体 + 理由带锚点 → 无 error", not [x for x in f if x[0] == "error"], str(f))

        f, _ = check_ledger(load_rows(write("same.jsonl", SAME_BODY)))
        check("同一主体分饰、但理由带锚点 → 无 error（是事实不是缺陷）",
              not [x for x in f if x[0] == "error"], str(f))
        check("同一主体分饰 → 有 note 报告（不冒充三权分立）",
              any("这是事实不是缺陷" in d for lv, d in f if lv == "note"), str(f))

        f, _ = check_ledger(load_rows(write("noanchor.jsonl", NO_ANCHOR)))
        check("判定理由无锚点 → error",
              any("没有任何锚点" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger(load_rows(write("voice.jsonl", FIXTURE_AUTHOR_VOICE)))
        check("判定理由出现作者视角 → error",
              any("作者视角" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger(load_rows(write("cross.jsonl", FIXTURE_CROSS_REF)))
        check("判定理由引用别的判定 → error",
              any("引用了别的判定" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger(load_rows(write("nosign.jsonl", NO_SIGN)))
        check("判定无署名 → error", any("没有署名" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger(load_rows(write("noreason.jsonl", NO_REASON)))
        check("判定无理由 → error", any("没有理由" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger([])
        check("空账本 → error（不当作通过）", any("账本是空的" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger(load_rows(write("bad.jsonl", "{不是json}\n")))
        check("坏 JSON 行 → error", any("不是合法 JSON" in d for lv, d in f if lv == "error"), str(f))

        f, _ = check_ledger([
            {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "a",
             "reason": "README.md:5 达标"},
            {"node": "N4", "attempt": 1, "verdict": "pass", "score": 4, "judge": "a",
             "reason": "README.md:5 达标"},
        ])
        check("同一事件重复记录 → note 报告",
              any("被记了多次" in d for lv, d in f if lv == "note"), str(f))
        check("重复记录去重后 → 该判定不被重复判 error",
              len([d for lv, d in f if lv == "error"]) == 0, str(f))

        f, _ = check_ledger([
            {"node": "N0", "judge": "笛子", "reason": "x"},
            {"node": "N4", "judge": "a", "reason": "README.md:5 达标"},
            {"node": "N5", "judge": "b", "reason": "README.md:6 达标"},
        ])
        check("脚本节点冒充判定者 → warn",
              any("脚本节点" in d for lv, d in f if lv == "warn"), str(f))

        # 机器侧判定者不查独立性证据（audit 本来就没锚点）
        f, _ = check_ledger([
            {"node": "N1", "judge": "audit", "reason": "出处覆盖率 17%"},
            {"node": "N4", "judge": "a", "reason": "README.md:5 达标"},
        ])
        check("机器侧判定者（audit）不查锚点 → 不误报",
              not any("没有任何锚点" in d for lv, d in f if lv == "error"), str(f))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=== 自测（verify_ledger）===")
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
        prog="verify_ledger.py",
        description="判决账本「独立性证据」校验：查判定是否真独立（带锚点 / 不站作者视角 / 不互相引用）")
    ap.add_argument("target", nargs="?", help="ledger.jsonl 文件，或项目目录")
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args(argv)

    if args.test:
        return run_test()
    if not args.target:
        ap.print_help()
        return 2

    path = args.target
    if os.path.isdir(path):
        path = os.path.join(path, ".publish-staging", "ledger.jsonl")
    if not os.path.isfile(path):
        print(f"ERROR: 找不到账本：{path}", file=sys.stderr)
        return 2

    findings, stats = check_ledger(load_rows(path))
    errors = [d for lv, d in findings if lv == "error"]
    warns = [d for lv, d in findings if lv == "warn"]
    notes = [d for lv, d in findings if lv == "note"]

    if args.as_json:
        print(json.dumps({"ok": not errors, "path": path, "stats": stats,
                          "errors": errors, "warnings": warns, "notes": notes},
                         ensure_ascii=False))
        return 1 if errors else 0

    print(f"账本校验：{path}")
    print(f"  共 {stats.get('rows', 0)} 行；判定行 {stats.get('judge_rows', 0)} 行"
          f"（其中外部主体 {stats.get('human_judge_rows', 0)} 行）")
    print(f"  判定过的节点：{', '.join(stats.get('nodes_judged', [])) or '（无）'}")
    print(f"  判定者主体（去括号后）：{', '.join(stats.get('judge_bodies', [])) or '（无）'}")
    print()
    for lv, d in findings:
        icon = {"error": "🔴", "warn": "⚠️ ", "note": "ℹ️ "}[lv]
        print(f"  {icon} {d}")
    if errors:
        print(f"\n❌ 拒收：{len(errors)} 项 —— 判定缺少独立性证据（不是独立判定）。")
        return 1
    print(f"\n✅ 通过：判定均带独立性证据（告警 {len(warns)} 项、说明 {len(notes)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
