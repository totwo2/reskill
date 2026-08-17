#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reskill v1.3.0 — 同步 SkillHub 名下 skill 列表
用途：从 SkillHub 官方 API 拉取当前用户发布的所有 skill，
      与本地 reskill_config.yaml 的 skillhub.skills 段对比：
        - 新发布（本地无）→ 追加
        - 已下架 / 改名（云端无）→ 标记
      并写一份明文快照到 settings/my_skills_snapshot.yaml（供审计）
      以及一份机器可读 diff 给外层提示。
用法: python3 fetch_my_skills.py [--dry-run] [--token TOKEN] [--handle HANDLE]
"""
import json, urllib.request, urllib.error, os, sys, argparse, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.dirname(HERE), "settings")
CONFIG = os.path.join(SETTINGS, "reskill_config.yaml")
SNAPSHOT = os.path.join(SETTINGS, "my_skills_snapshot.yaml")
API_BASE = "https://api.skillhub.cn"


def load_config():
    """读 yaml 配置，缺 PyYAML 时回退到最小解析（仅顶层 skillhub.skills）。"""
    try:
        import yaml
        with open(CONFIG, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        # 没有 PyYAML：用正则手工解析 skillhub.skills 段
        cfg = {"skillhub": {"skills": []}}
        txt = open(CONFIG, encoding="utf-8").read()
        m = re.search(r"^skillhub:\s*\n((?:  [^\n]*\n)+)", txt, re.MULTILINE)
        if not m:
            return cfg
        block = m.group(1)
        cur = None
        for line in block.splitlines():
            line_s = line.strip()
            if line_s.startswith("- slug:"):
                cur = {"slug": line_s.split(":", 1)[1].strip()}
                cfg["skillhub"]["skills"].append(cur)
            elif cur and line_s.startswith("display_name:"):
                cur["display_name"] = line_s.split(":", 1)[1].strip().strip('"')
        return cfg


def save_config(cfg):
    """写回 yaml（要求 PyYAML；否则退化为手工写 skillhub 段）。"""
    try:
        import yaml as _y
        with open(CONFIG, "w", encoding="utf-8") as f:
            _y.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return True
    except ImportError:
        return False  # 退化为手工写


def fetch_my_skills(token, handle):
    """调 SkillHub 官方 API：/api/v1/users/<handle>/skills"""
    url = f"{API_BASE}/api/v1/users/{handle}/skills"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"❌ HTTP {e.code}: {e.reason} — 检查 token/handle 是否正确")
    except urllib.error.URLError as e:
        raise SystemExit(f"❌ 网络错误: {e.reason}")

    skills = data.get("skills") or []
    return data.get("count", len(skills)), skills


def diff(local_skills, remote_skills):
    """对比本地 vs 云端，返回 (新增, 缺失, 改名/版本不一致)。"""
    local_map = {s["slug"]: s for s in local_skills}
    remote_map = {s["slug"]: s for s in remote_skills}

    added = [s for s in remote_skills if s["slug"] not in local_map]
    missing = [s for s in local_skills if s["slug"] not in remote_map]
    updated = []
    for s in remote_skills:
        ls = local_map.get(s["slug"])
        if not ls:
            continue
        # display_name 不一致 → 改名
        remote_name = s.get("name") or s.get("displayName") or ""
        if remote_name and remote_name != ls.get("display_name", ""):
            updated.append({"slug": s["slug"], "from": ls.get("display_name"),
                            "to": remote_name, "version": s.get("version")})
    return added, missing, updated


def write_snapshot(remote_skills, count, handle):
    """写云端快照供审计。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# SkillHub 名下 skill 快照 — {ts}",
             f"# handle: {handle}  count: {count}", ""]
    for s in remote_skills:
        lines.append(f"- slug: {s['slug']}")
        lines.append(f"  name: {s.get('name') or s.get('displayName') or ''}")
        lines.append(f"  version: {s.get('version', '?')}")
        lines.append(f"  downloads: {s.get('downloads', 0)}")
        lines.append(f"  stars: {s.get('stars', 0)}")
        lines.append(f"  category: {s.get('category', '?')}")
        lines.append(f"  updated_at: {s.get('updatedAt') or s.get('updated_at') or '?'}")
        lines.append("")
    open(SNAPSHOT, "w", encoding="utf-8").write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只对比不写入")
    ap.add_argument("--token", default=os.environ.get("SKILLHUB_TOKEN"),
                    help="SkillHub token（默认读 $SKILLHUB_TOKEN）")
    ap.add_argument("--handle", default=None, help="SkillHub handle（默认从 ~/.skillhub/cli 读）")
    args = ap.parse_args()

    # handle 默认从 cli config 读
    handle = args.handle
    token = args.token
    if not handle or not token:
        cred_path = os.path.expanduser("~/.skillhub/credentials.json")
        if os.path.exists(cred_path):
            try:
                cred = json.load(open(cred_path))
                u = cred.get("user", {})
                handle = handle or u.get("handle")
                token = token or u.get("token")
            except Exception:
                pass
    if not handle:
        raise SystemExit("❌ 缺 handle。传 --handle user_xxx 或先 `skillhub login`。")
    if not token:
        raise SystemExit("❌ 缺 token。设置 $SKILLHUB_TOKEN 或传 --token。")

    print(f"🔍 拉取 SkillHub handle={handle} 的名下 skill...")
    count, remote = fetch_my_skills(args.token, handle)
    print(f"   云端共 {count} 个 skill\n")

    cfg = load_config()
    local = cfg.get("skillhub", {}).get("skills", [])
    local_slugs = {s["slug"] for s in local}
    added, missing, updated = diff(local, remote)

    print(f"📊 对比结果：")
    print(f"   本地监控: {len(local)} 个")
    print(f"   云端发布: {count} 个")
    print(f"   新发布（本地无）: {len(added)}")
    print(f"   云端缺失（已下架？）: {len(missing)}")
    print(f"   改名/版本不一致: {len(updated)}")

    if added:
        print(f"\n🆕 新增 skill（建议加入监控）：")
        for s in added:
            print(f"   • {s['slug']} | {s.get('name') or s.get('displayName')} "
                  f"| v{s.get('version')} | {s.get('downloads', 0)} downloads")
    if missing:
        print(f"\n⚠️  本地有但云端没有（可能下架或改名）：")
        for s in missing:
            print(f"   • {s['slug']} | {s.get('display_name')}")
    if updated:
        print(f"\n🔄 改名 / 不一致：")
        for u in updated:
            print(f"   • {u['slug']} : 「{u['from']}」 → 「{u['to']}」 (v{u['version']})")

    if args.dry_run:
        print("\n[dry-run] 未写入任何文件。")
        return

    # 写云端快照
    write_snapshot(remote, count, handle)
    print(f"\n✅ 快照已写入: {SNAPSHOT}")

    # 增量更新 reskill_config.yaml
    if added or updated:
        # 更新本地 skills 列表
        existing = {s["slug"]: s for s in local}
        for s in remote:
            slug = s["slug"]
            name = s.get("name") or s.get("displayName") or slug
            if slug not in existing:
                existing[slug] = {"slug": slug, "display_name": name}
            else:
                existing[slug]["display_name"] = name
        # 按云端顺序输出
        new_list = [existing[s["slug"]] for s in remote if s["slug"] in existing]
        cfg["skillhub"]["skills"] = new_list

        ok = save_config(cfg)
        if ok:
            print(f"✅ reskill_config.yaml 已更新（{len(new_list)} 个 skill）")
        else:
            print("⚠️  PyYAML 未安装，无法自动写回 yaml。请手动合并：")
            print(f"   新 skillhub.skills = {[s['slug'] for s in new_list]}")
    else:
        print(f"\n✅ 配置已是最新，无需更新。")

    # 输出机器可读 diff 给外层
    print("\nDIFF_JSON=" + json.dumps({
        "added": [s["slug"] for s in added],
        "missing": [s["slug"] for s in missing],
        "updated": updated,
        "total_remote": count,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()