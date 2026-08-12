#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reskill v1.1.0 — 下载量趋势追踪
每次运行：拉取 skillhub 最新下载量 → 与上一次快照对比 → 有正增量则输出提醒文案 → 追加新快照。
用法: python3 check_downloads.py
"""
import json, urllib.request, datetime, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.dirname(HERE), "settings")
HISTORY = os.path.join(SETTINGS, "download_history.yaml")

SKILLS = [
    ("everytime-novel", "全流程网络小说写作系统"),
    ("reskill", "Skill发布与反馈优化系统"),
    ("zhi-neng-py-jiao-ben-you-hua", "智能py脚本优化"),
    ("da-jia-dou-lai-hui-da", "大家都来回答"),
    ("quibbler", "唱唱反调·人群模拟器"),
    ("tmeetpeople", "二创tmeet人员管理版"),
    ("fangdai-haiyao-hai-duojiu", "房贷还要还多久"),
]


def fetch_downloads(slug):
    try:
        d = json.load(urllib.request.urlopen(
            f"https://api.skillhub.cn/api/v1/search?q={slug}", timeout=15))
        arr = d if isinstance(d, list) else (d.get("results") or d.get("data") or [])
        hit = [x for x in arr if x.get("slug") == slug]
        return (hit[0].get("downloads") or 0) if hit else None
    except Exception:
        return None


def read_last_snapshot():
    """返回上一次快照 {slug: downloads}，无历史则返回 None。"""
    if not os.path.exists(HISTORY):
        return None
    txt = open(HISTORY, encoding="utf-8").read()
    blocks = re.split(r"-\s+time:", txt)
    if len(blocks) < 2:
        return None
    last = blocks[-1]
    snap = {}
    for slug, _ in SKILLS:
        m = re.search(rf"{re.escape(slug)}:\s*(\d+)", last)
        if m:
            snap[slug] = int(m.group(1))
    return snap or None


def append_snapshot(cur):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f'- time: "{now}"\n'
    for slug, _ in SKILLS:
        line += f"  {slug}: {cur.get(slug, 0)}\n"
    if not os.path.exists(HISTORY):
        header = ("# 下载量历史快照 — reskill v1.1.0 趋势追踪\n"
                  "# 每次监控运行时追加一条\n\nsnapshots:\n")
        open(HISTORY, "w", encoding="utf-8").write(header + line)
    else:
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(line)


def main():
    last = read_last_snapshot()
    cur = {}
    for slug, _ in SKILLS:
        v = fetch_downloads(slug)
        cur[slug] = v if v is not None else (last.get(slug, 0) if last else 0)

    gains = []
    for slug, name in SKILLS:
        if last and slug in last:
            delta = cur[slug] - last[slug]
            if delta > 0:
                gains.append((slug, name, last[slug], cur[slug], delta))

    print(f"=== 下载量检查 {datetime.datetime.now():%Y-%m-%d %H:%M} ===")
    for slug, name in SKILLS:
        prev = last.get(slug) if last else None
        tag = f"(上次 {prev})" if prev is not None else "(首次)"
        print(f"  {name:<22} 下载 {cur[slug]:>5} {tag}")

    if gains:
        print("\n" + "=" * 40)
        print("📈 有新下载！提醒文案：\n")
        msg = "🎉 你的 skill 又有人下载了！\n"
        for slug, name, p, c, d in gains:
            msg += f"\n• 「{name}」 {p} → {c}  (+{d})"
        msg += "\n\n持续被使用，继续加油 💪"
        print(msg)
        print("=" * 40)
        # 供外层解析：机器可读增量
        print("\nGAINS_JSON=" + json.dumps(
            [{"slug": s, "name": n, "delta": d} for s, n, _, _, d in gains],
            ensure_ascii=False))
    else:
        print("\n无新增下载（或首次运行建立基线）。")

    append_snapshot(cur)
    print("\n快照已追加至 download_history.yaml")


if __name__ == "__main__":
    main()
