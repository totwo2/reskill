#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reskill — 每日检查统一日报生成器
=================================
一次运行，拉取所有已监控平台的核心指标：
  ⭐ stars      （SkillHub / GitHub / Gitee 三平台）
  📥 downloads  （仅 SkillHub）
  🐛 open issues（GitHub / Gitee）

行为：
  • 首次运行（无 settings/daily_state.json）→ 输出【全量】基线。
  • 之后运行 → 输出【增量】：仅列出 star / 下载量 / issue 有变化的项，
    以及新增的 issue（含标题）。无变化则明确提示。

输出直接打印到 stdout，由外层（WorkBuddy 自动化）作为任务结果返回；
本脚本不做任何外部推送（微信 / 飞书 / 钉钉等）。

依赖：仅 Python 标准库；GitHub 数据走 `gh` CLI（需已登录），
Gitee / SkillHub 走官方 API（token 从 settings/reskill_config.yaml
与 ~/.skillhub/credentials.json 读取，绝不打印）。
"""
import json
import os
import sys
import subprocess
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.dirname(HERE), "settings")
CONFIG = os.path.join(SETTINGS, "reskill_config.yaml")
STATE = os.path.join(SETTINGS, "daily_state.json")
SKILLHUB_CREDS = os.path.expanduser("~/.skillhub/credentials.json")
TODAY = datetime.datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 1. 极简 YAML 解析（仅覆盖本配置固定结构：github / repo / skillhub 三段）
#    不依赖 PyYAML，保证脚本在任意 python3 下可移植。
# ---------------------------------------------------------------------------
def parse_config(path):
    cfg = {"github": {"repos": []}, "repo": {"repos": []}, "skillhub": {"skills": []}}
    if not os.path.exists(path):
        return cfg
    section = None
    sublist = None
    cur = None
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()
        if indent == 0:
            section = s.split(":", 1)[0]
            sublist = None
            cur = None
            continue
        if s.startswith("- "):
            content = s[2:].strip()
            if ":" in content:
                k, v = content.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
            else:
                k, v = "_", content
            if section == "github" and sublist == "repos":
                cur = {"name": (v if k == "name" else content)}
                cfg["github"]["repos"].append(cur)
            elif section == "repo" and sublist == "repos":
                cur = {"name": (v if k == "name" else content)}
                cfg["repo"]["repos"].append(cur)
            elif section == "skillhub" and sublist == "skills":
                cur = {}
                if k != "_":
                    cur[k] = v
                cfg["skillhub"]["skills"].append(cur)
            else:
                cur = {k: v} if k != "_" else {}
            continue
        # 普通 key: value（非列表项）
        if ":" in s:
            k, v = s.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v == "" and k in ("repos", "skills"):
                sublist = k
                continue
            if indent > 2 and cur is not None and sublist in ("repos", "skills"):
                cur[k] = v
            else:
                sublist = None
                if section in ("github", "repo", "skillhub"):
                    cfg.setdefault(section, {})[k] = v
    return cfg


# ---------------------------------------------------------------------------
# 2. 凭据
# ---------------------------------------------------------------------------
def load_skillhub_creds():
    if os.path.exists(SKILLHUB_CREDS):
        try:
            d = json.load(open(SKILLHUB_CREDS, encoding="utf-8"))
            u = d.get("user", {})
            return u.get("token"), u.get("handle")
        except Exception:
            return None, None
    return None, None


# ---------------------------------------------------------------------------
# 3. 各平台抓取
# ---------------------------------------------------------------------------
def fetch_skillhub(token, handle):
    """返回 {slug: {stars, downloads, version, name}} 或 {}"""
    out = {}
    if not token or not handle:
        return out
    url = f"https://api.skillhub.cn/api/v1/users/{handle}/skills"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception:
        return out
    for s in (data.get("skills") or []):
        slug = s.get("slug")
        if not slug:
            continue
        out[slug] = {
            "stars": int(s.get("stars") or 0),
            "downloads": int(s.get("downloads") or 0),
            "version": s.get("version") or "?",
            "name": s.get("name") or s.get("displayName") or slug,
        }
    return out


def gh_json(args):
    try:
        p = subprocess.run(["gh"] + args, capture_output=True,
                           text=True, timeout=40)
        if p.returncode != 0:
            return None
        return json.loads(p.stdout)
    except Exception:
        return None


def fetch_github(owner, repos):
    out = {}
    for name in repos:
        stars = None
        issues = None
        v = gh_json(["api", f"repos/{owner}/{name}", "--jq", ".stargazers_count"])
        if v is not None:
            try:
                stars = int(str(v).strip())
            except Exception:
                stars = None
        ils = gh_json(["issue", "list", "--repo", f"{owner}/{name}",
                       "--state", "open", "--json", "number,title"])
        if isinstance(ils, list):
            issues = [{"id": str(i.get("number")), "title": i.get("title") or ""}
                      for i in ils]
        out[name] = {"stars": stars, "issues": issues}
    return out


def fetch_gitee(owner, token, repos):
    out = {}
    for name in repos:
        stars = None
        issues = None
        try:
            u = f"https://gitee.com/api/v5/repos/{owner}/{name}?access_token={token}"
            with urllib.request.urlopen(u, timeout=20) as r:
                d = json.load(r)
            stars = d.get("stargazers_count")
        except Exception:
            stars = None
        try:
            u2 = (f"https://gitee.com/api/v5/repos/{owner}/{name}/issues"
                  f"?state=open&access_token={token}&per_page=50")
            with urllib.request.urlopen(u2, timeout=20) as r:
                arr = json.load(r)
            issues = [{"id": str(i.get("number") or i.get("id")),
                       "title": i.get("title") or ""} for i in arr]
        except Exception:
            issues = None
        out[name] = {"stars": stars, "issues": issues}
    return out


# ---------------------------------------------------------------------------
# 4. 状态（基线）读写
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            return None
    return None


def save_state(state):
    json.dump(state, open(STATE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def build_serializable(skillhub_raw, github_raw, gitee_raw):
    return {
        "date": TODAY,
        "skillhub": {slug: {"stars": d["stars"], "downloads": d["downloads"]}
                     for slug, d in skillhub_raw.items() if isinstance(d, dict)},
        "github": {name: {"stars": g["stars"],
                          "issue_ids": [i["id"] for i in (g["issues"] or [])]}
                   for name, g in github_raw.items()},
        "gitee": {name: {"stars": g["stars"],
                         "issue_ids": [i["id"] for i in (g["issues"] or [])]}
                  for name, g in gitee_raw.items()},
    }


# ---------------------------------------------------------------------------
# 5. 报告生成
# ---------------------------------------------------------------------------
def _fmt(v):
    return "❓" if v is None else str(v)


def compose_full(cfg, skillhub_raw, github_raw, gitee_raw):
    lines = [f"📊 reskill 每日检查 — {TODAY}（首次全量基线）", ""]
    gh_owner = cfg.get("github", {}).get("owner", "?")
    ge_owner = cfg.get("repo", {}).get("owner", "?")

    lines.append(f"【SkillHub · {len(skillhub_raw)} 个】⭐stars  📥downloads")
    for slug, d in skillhub_raw.items():
        lines.append(f"  {slug:<34} ⭐{_fmt(d['stars']):>5}  📥{_fmt(d['downloads']):>5}")
    if not skillhub_raw:
        lines.append("  （无数据 / 凭据缺失）")

    lines.append("")
    lines.append(f"【GitHub · {len(github_raw)} 个】（{gh_owner}）⭐stars  🐛open issues")
    for name, g in github_raw.items():
        cnt = len(g["issues"]) if g["issues"] is not None else None
        lines.append(f"  {name:<34} ⭐{_fmt(g['stars']):>5}  🐛{_fmt(cnt):>4}")
    if not github_raw:
        lines.append("  （无数据）")

    lines.append("")
    lines.append(f"【Gitee · {len(gitee_raw)} 个】（{ge_owner}）⭐stars  🐛open issues")
    for name, g in gitee_raw.items():
        cnt = len(g["issues"]) if g["issues"] is not None else None
        lines.append(f"  {name:<34} ⭐{_fmt(g['stars']):>5}  🐛{_fmt(cnt):>4}")
    if not gitee_raw:
        lines.append("  （无数据）")

    lines.append("")
    lines.append("✅ 已建立基线，明日将仅显示增量变化。")
    return "\n".join(lines)


def compose_incremental(prev, cfg, skillhub_raw, github_raw, gitee_raw):
    changes = []  # (platform_label, name, detail_lines)

    def diff_section(plat_label, prev_map, cur_raw, has_downloads=False):
        sec = []
        cur_map = {k: v for k, v in cur_raw.items()}
        # 新增监控项
        for name, d in cur_raw.items():
            if name not in prev_map:
                stars = d.get("stars")
                dl = d.get("downloads") if has_downloads else None
                iss = d.get("issues")
                cnt = len(iss) if iss is not None else None
                bits = [f"⭐{_fmt(stars)}"]
                if has_downloads:
                    bits.append(f"📥{_fmt(dl)}")
                bits.append(f"🐛{_fmt(cnt)}")
                sec.append(f"  🆕 {name}（新增监控）{'  '.join(bits)}")
        # 已有项变化
        for name, d in cur_raw.items():
            if name not in prev_map:
                continue
            p = prev_map[name]
            bits = []
            cur_stars = d.get("stars")
            if cur_stars is not None and p.get("stars") is not None \
                    and cur_stars != p.get("stars"):
                bits.append(f"⭐{p['stars']}→{cur_stars} ({'+' if cur_stars > p['stars'] else ''}{cur_stars - p['stars']})")
            if has_downloads:
                cur_dl = d.get("downloads")
                if cur_dl is not None and p.get("downloads") is not None \
                        and cur_dl != p.get("downloads"):
                    bits.append(f"📥{p['downloads']}→{cur_dl} ({'+' if cur_dl > p['downloads'] else ''}{cur_dl - p['downloads']})")
            # issues
            cur_ids = set(str(i["id"]) for i in (d.get("issues") or []))
            prev_ids = set(str(x) for x in (p.get("issue_ids") or []))
            new_ids = cur_ids - prev_ids
            if new_ids:
                for i in (d.get("issues") or []):
                    if str(i["id"]) in new_ids:
                        bits.append(f"🐛新#{i['id']}「{i['title']}」")
            if bits:
                sec.append(f"  • {name}: " + "  ".join(bits))
        if sec:
            changes.append((plat_label, sec))

    diff_section("SkillHub", prev.get("skillhub", {}), skillhub_raw, has_downloads=True)
    diff_section(f"GitHub/{cfg.get('github',{}).get('owner','?')}",
                 prev.get("github", {}), github_raw)
    diff_section(f"Gitee/{cfg.get('repo',{}).get('owner','?')}",
                 prev.get("gitee", {}), gitee_raw)

    total_cur = (len(skillhub_raw) + len(github_raw) + len(gitee_raw))
    if not changes:
        return (f"📊 reskill 每日检查 — {TODAY}（增量 · 较 {prev.get('date','?')}）\n\n"
                f"✅ 今日无变化（{total_cur} 个监控项的 stars / 下载量 / issues 均与基线一致）。")
    lines = [f"📊 reskill 每日检查 — {TODAY}（增量 · 较 {prev.get('date','?')}）", ""]
    lines.append("🔥 变化项：")
    for label, sec in changes:
        lines.append(f"【{label}】")
        lines.extend(sec)
    lines.append("")
    lines.append(f"📌 其余监控项无变化。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. 主流程
# ---------------------------------------------------------------------------
def main():
    if "--test" in sys.argv:
        cfg = parse_config(CONFIG)
        # 脱敏：不回显真实 token
        for sec in ("github", "repo"):
            if sec in cfg and "token" in cfg[sec]:
                t = cfg[sec]["token"]
                cfg[sec]["token"] = (t[:4] + "…" + t[-4:]) if t and len(t) > 8 else "***"
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return

    cfg = parse_config(CONFIG)
    sh_token, sh_handle = load_skillhub_creds()
    gh_owner = cfg.get("github", {}).get("owner")
    gh_repos = [r.get("name") for r in cfg.get("github", {}).get("repos", []) if r.get("name")]
    ge_owner = cfg.get("repo", {}).get("owner")
    ge_token = cfg.get("repo", {}).get("token")
    ge_repos = [r.get("name") for r in cfg.get("repo", {}).get("repos", []) if r.get("name")]
    sh_slugs = [s.get("slug") for s in cfg.get("skillhub", {}).get("skills", []) if s.get("slug")]

    # 抓取（各自容错）
    skillhub_raw = fetch_skillhub(sh_token, sh_handle)
    # 仅保留配置中监控的 slug
    skillhub_raw = {s: skillhub_raw[s] for s in sh_slugs if s in skillhub_raw}

    github_raw = fetch_github(gh_owner, gh_repos) if gh_owner and gh_repos else {}
    gitee_raw = fetch_gitee(ge_owner, ge_token, ge_repos) if ge_owner and ge_token and ge_repos else {}

    prev = load_state()
    if prev is None:
        report = compose_full(cfg, skillhub_raw, github_raw, gitee_raw)
    else:
        report = compose_incremental(prev, cfg, skillhub_raw, github_raw, gitee_raw)

    save_state(build_serializable(skillhub_raw, github_raw, gitee_raw))
    print(report)


if __name__ == "__main__":
    main()
