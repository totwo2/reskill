#!/usr/bin/env python3
"""可发现性检查 —— 把规范里「写用户会搜的那个词」落成可执行的量。

publish-quality.md 里「③ 可发现性」写明：

    具体落在 topics / description / 名称：写用户会搜的那个词
    GitHub 尤其如此：它不带流量，topics + description 是唯一能被人搜到的入口

但此前的闸门只量「有没有 + 分两组」，不量「这词有没有人搜」，名称更是完全没查。
本脚本补的就是这两格。

检查项
------
  R1 名称查重    仓库名在全站有多少同名仓库；有没有同名且更热的竞品
  R2 topic 池子  每个 topic 的真实搜索池大小；池子过小 = 没人这么搜
  R3 汇总        零流量 topic 的占比

设计约定
--------
  * 出错必须暴露   —— 不吞异常、不静默降级
  * 联网失败 = WARN，不是 FAIL —— 拿不到数据不等于不合规（与闸门「缺数据不误判」一致）
  * 退出码         0=通过 / 1=有死词 / 2=用法错 / 3=自证失败

用法
----
  python3 check_discoverability.py --repo totwo2/reskill --topics "a,b,c"
  python3 check_discoverability.py --repo totwo2/reskill --topics-file topics.txt
  python3 check_discoverability.py --topics "a,b,c" --min-pool 50 --json
  python3 check_discoverability.py --self-test      # 离线自证，不联网
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MIN_POOL = 50      # topic 搜索池下限：低于此值 = 全站几乎没人用这个词找东西
NAME_COLLISION_SHOW = 10   # 名称查重时看前几名


# --------------------------------------------------------------------------
# 纯逻辑部分（可离线自证）
# --------------------------------------------------------------------------

def classify_topic(topic, pool, min_pool):
    """把一个 topic 的池子大小判成 PASS / WARN / FAIL。pool=None 表示没拿到数据。"""
    if pool is None:
        return "WARN", f"`{topic}` 拿不到搜索池数据（联网失败？）—— 未判定，不按不合规处理"
    if pool <= 0:
        return "FAIL", f"`{topic}` 全站 0 个仓库 —— 这词不存在，等于没写"
    if pool < min_pool:
        return "FAIL", f"`{topic}` 搜索池仅 {pool}（下限 {min_pool}）—— 没人这么搜，占着位置不带流量"
    return "PASS", f"`{topic}` 搜索池 {pool}"


def classify_name(total, collisions):
    """名称查重。collisions = [(full_name, stars), ...] 同名的其它仓库。"""
    if total is None:
        return "WARN", "名称查重拿不到数据（联网失败？）—— 未判定"
    hot = [(n, s) for n, s in collisions if s > 0]
    if hot:
        hottest = max(hot, key=lambda x: x[1])
        return "WARN", (f"全站 {total} 个同名仓库，其中 `{hottest[0]}` 有 ★{hottest[1]} "
                        f"—— 搜这个词先出别人；名称本身不承载搜索意图（改名代价高，此项不判 FAIL）")
    if total > 200:
        return "PASS", f"全站 {total} 个同名仓库，但都无星，不构成压制"
    return "PASS", f"全站 {total} 个同名仓库，重名压力小"


def summarize(topic_results, name_result):
    """汇总。只要有 FAIL 就整体不通过。"""
    fails = [m for level, m in topic_results if level == "FAIL"]
    warns = [m for level, m in topic_results if level == "WARN"]
    if name_result[0] == "FAIL":
        fails.append(name_result[1])
    if name_result[0] == "WARN":
        warns.append(name_result[1])
    return ("FAIL" if fails else "PASS"), fails, warns


# --------------------------------------------------------------------------
# 取数部分
# --------------------------------------------------------------------------

def _api(path, params):
    """调 GitHub API。先试 gh（已认证，限速宽松），失败退到匿名 urllib。"""
    url = "https://api.github.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        cp = subprocess.run(["gh", "api", "-X", "GET", path] +
                            sum([["-f", f"{k}={v}"] for k, v in (params or {}).items()], []),
                            capture_output=True, text=True, timeout=30)
        if cp.returncode == 0 and cp.stdout.strip():
            return json.loads(cp.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "reskill-check-discoverability",
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        print(f"  [取数失败] {url} -> {e}", file=sys.stderr)
        return None


def topic_pool(topic):
    d = _api("/search/repositories", {"q": f"topic:{topic}", "per_page": 1})
    return None if d is None else d.get("total_count")


def name_collisions(name, exclude_full):
    d = _api("/search/repositories", {"q": name, "per_page": NAME_COLLISION_SHOW})
    if d is None:
        return None, []
    hits = [(i["full_name"], i.get("stargazers_count", 0)) for i in d.get("items", [])
            if i["full_name"] != exclude_full and i["name"].lower() == name.lower()]
    return d.get("total_count"), hits


# --------------------------------------------------------------------------
# 自证（离线，不联网）
# --------------------------------------------------------------------------

def self_test():
    cases = []

    def ck(desc, got, want):
        cases.append((desc, got == want, f"got={got!r} want={want!r}"))

    # classify_topic
    ck("池子 1（只有自己）判 FAIL", classify_topic("x", 1, 50)[0], "FAIL")
    ck("池子 0 判 FAIL", classify_topic("x", 0, 50)[0], "FAIL")
    ck("池子 49 判 FAIL", classify_topic("x", 49, 50)[0], "FAIL")
    ck("池子 50 判 PASS（边界）", classify_topic("x", 50, 50)[0], "PASS")
    ck("池子 8000 判 PASS", classify_topic("x", 8000, 50)[0], "PASS")
    ck("拿不到数据判 WARN 不判 FAIL", classify_topic("x", None, 50)[0], "WARN")

    # classify_name
    ck("有同名热竞品判 WARN", classify_name(1218, [("a/b", 59)])[0], "WARN")
    ck("同名但全无星判 PASS", classify_name(1218, [("a/b", 0)]), classify_name(1218, [("a/b", 0)]))
    ck("同名但全无星判 PASS(级别)", classify_name(1218, [("a/b", 0)])[0], "PASS")
    ck("名字拿到数据失败判 WARN", classify_name(None, [])[0], "WARN")
    ck("重名少判 PASS", classify_name(3, [])[0], "PASS")

    # summarize
    ck("有 FAIL 则整体 FAIL", summarize([("FAIL", "m")], ("PASS", ""))[0], "FAIL")
    ck("全 PASS 则整体 PASS", summarize([("PASS", "m")], ("PASS", ""))[0], "PASS")
    ck("只有 WARN 不拦", summarize([("WARN", "m")], ("PASS", ""))[0], "PASS")
    ck("名称 WARN 不拦", summarize([("PASS", "m")], ("WARN", "n"))[0], "PASS")
    ck("FAIL 会被汇总进 fails", len(summarize([("FAIL", "m")], ("PASS", ""))[1]), 1)
    ck("WARN 会被汇总进 warns", len(summarize([("WARN", "m")], ("PASS", ""))[2]), 1)

    bad = [(d, e) for d, ok, e in cases if not ok]
    for d, ok, e in cases:
        print(f"  {'PASS' if ok else 'FAIL'}  {d}")
    print(f"\n自证：{len(cases) - len(bad)}/{len(cases)} 通过")
    return 0 if not bad else 3


# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="可发现性检查：topic 有没有人搜 + 名称有没有被占")
    p.add_argument("--repo", help="owner/name，用于名称查重时排除自己")
    p.add_argument("--name", help="要查重的仓库名（缺省从 --repo 取）")
    p.add_argument("--topics", help="逗号分隔的 topics")
    p.add_argument("--topics-file", help="从文件读 topics（每行一个，或逗号分隔）")
    p.add_argument("--min-pool", type=int, default=DEFAULT_MIN_POOL)
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--self-test", action="store_true", help="离线自证，不联网")
    a = p.parse_args()

    if a.self_test:
        return self_test()

    topics = []
    if a.topics:
        topics += [t.strip() for t in a.topics.split(",") if t.strip()]
    if a.topics_file:
        with open(a.topics_file, encoding="utf-8") as f:
            for line in f:
                topics += [t.strip() for t in line.replace(",", "\n").split("\n") if t.strip()]
    topics = list(dict.fromkeys(topics))   # 去重保序

    if not topics and not a.name and not a.repo:
        p.error("至少给 --topics / --name / --repo 之一，或用 --self-test")

    name = a.name or (a.repo.split("/")[-1] if a.repo else None)
    topic_results, pools = [], {}
    for t in topics:
        pool = topic_pool(t)
        pools[t] = pool
        topic_results.append(classify_topic(t, pool, a.min_pool))

    name_result = ("PASS", "(未查名称)")
    collisions = []
    if name:
        total, collisions = name_collisions(name, a.repo or "")
        name_result = classify_name(total, collisions)

    overall, fails, warns = summarize(topic_results, name_result)

    if a.json:
        print(json.dumps({
            "overall": overall,
            "min_pool": a.min_pool,
            "topics": [{"topic": t, "pool": pools.get(t), "level": lv, "msg": m}
                       for t, (lv, m) in zip(topics, topic_results)],
            "name": {"name": name, "level": name_result[0], "msg": name_result[1],
                     "collisions": collisions},
            "fails": fails, "warns": warns,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"可发现性检查（topic 池子下限 {a.min_pool}）\n")
        print(f"[名称] {name_result[0]}  {name_result[1]}\n")
        print(f"[topics] 共 {len(topics)} 个")
        for lv, m in sorted(topic_results, key=lambda x: {"FAIL": 0, "WARN": 1, "PASS": 2}[x[0]]):
            print(f"  {lv:4} {m}")
        if fails:
            print(f"\n不合规 {len(fails)} 项：")
            for m in fails:
                print(f"  - {m}")
        if warns:
            print(f"\n未判定（不拦）{len(warns)} 项：")
            for m in warns:
                print(f"  - {m}")
        print(f"\n结论：{overall}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
