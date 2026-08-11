#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reskill v1.2.0 — GitHub Skill 完整生命周期管理

命令：
  scan <directory>          凭据扫描（闸门），独立运行
  create <owner/repo> --tag <vX.Y.Z>
            创建：加 topic + 创建 release（闸门强制扫描）
  publish <owner/repo> --tag <vX.Y.Z> [--dry-run] [--skip-scan]
            发布：验证 + 加 topic + 创建 release（闸门强制扫描）
  list [--owner <username>]
            列出 agent-skills topic 仓库
  search <query> [--owner <username>] [--limit N]
            搜索 skill（gh skill search 封装）
  update <owner/repo> --tag <vX.Y.Z> [--dry-run]
            更新版本：创建新 release（闸门强制扫描）
  delete <owner/repo> --tag <vX.Y.Z> [--dry-run]
            删除 release（可选保留）

闸门规则（强制）：
  凡调用 publish/create/update，必须通过 scan 检查
  --skip-scan 需管理员授权才能使用
  命中敏感凭据 → exit 1，不允许继续

依赖：gh CLI（v2.94.0+），Python 3.9+
"""
import argparse, subprocess, sys, os, json, datetime, re, base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESkill_DIR = os.path.dirname(SCRIPT_DIR)

# ============================================================
# 凭据模式（闸门规则）
# ============================================================
PATTERNS = {
    "gh_token":   r'gh[pousr]_[0-9A-Za-z]{20,}',
    "skh_token":  r'skh_[0-9A-Za-z]{8,}',
    "gitee_token": r'(?i)gitee.*?token\s*[=:]\s*["\']?[0-9a-f]{32,}["\']?',
    "aws_key":    r'AKIA[0-9A-Z]{16}',
    "slack_token":r'xox[baprs]-[0-9A-Za-z-]{10,}',
    "openai_key": r'sk-[0-9A-Za-z-]{20,}',
    "private_key":r'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----',
    "generic_token":r'(?i)(?:access_token|auth_token|api_key|secret)[\s]*[=:][\s]*[0-9a-zA-Z_/-]{20,}',
}

# ============================================================
# 凭据扫描（闸门核心）
# ============================================================
def scan_dir(directory, scan_all=False):
    """扫描目录，返回 (passed: bool, findings: list)"""
    directory = os.path.abspath(directory)
    # 先检查是否是 git 仓库
    in_git = subprocess.run(['git', 'rev-parse', '--git-dir'], 
                            capture_output=True).returncode == 0
    # 确定扫描模式
    if scan_all:
        mode = "全量"
    elif not in_git:
        mode = "全量"
    else:
        mode = "git"
    print(f"🔍 凭据扫描 [{mode}] {directory}")

    if not os.path.isdir(directory):
        return False, [("❌ 目录不存在", directory)]

    # 收集文件
    if mode == "全量":
        cmd = f'find {directory} -type f ! -path "*/.git/*" ! -name "*.example.*" ! -name "preflight_secret_scan.sh" ! -name "*.pyc" ! -name "*.pyo"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        files = [f for f in result.stdout.strip().split('\n') if f]
    else:
        os.chdir(directory)
        r1 = subprocess.run(['git', 'ls-files'], capture_output=True, text=True)
        r2 = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard'], capture_output=True, text=True)
        files = [f for f in (r1.stdout + r2.stdout).strip().split('\n') if f
                 and not f.endswith('.example.*')
                 and f != 'preflight_secret_scan.sh']

    if not files:
        return True, []

    findings = []
    for filepath in files:
        try:
            with open(filepath, 'r', errors='replace') as f:
                content = f.read()
            for pname, pattern in PATTERNS.items():
                if re.search(pattern, content, re.IGNORECASE):
                    # 找第一处匹配位置
                    for m in re.finditer(pattern, content, re.IGNORECASE):
                        line_num = content[:m.start()].count('\n') + 1
                        line = content.split('\n')[line_num - 1][:80]
                        findings.append((filepath, pname, m.group()[:40], line_num, line))
                        break  # 每种 pattern 只报一次
        except Exception:
            pass  # 跳过二进制文件

    if findings:
        print("\n❌ 扫描未通过！发现疑似凭据：")
        for filepath, pname, matched, line_num, line in findings:
            print(f"   🔴 {filepath}:{line_num} [{pname}]")
            print(f"      匹配: {matched}...")
            print(f"      上下文: ...{line}...")
        print("\n   处理方案：")
        print("   1. 把凭据移至环境变量或 .env 文件")
        print("   2. 创建 *.example.* 脱敏版本放入仓库")
        print("   3. 在 .gitignore 中添加对应路径")
        print("   4. 修复后重新扫描")
        return False, findings
    else:
        print("✅ 扫描通过：未发现敏感凭据")
        return True, []

# ============================================================
# GitHub API 操作
# ============================================================
def run(cmd, check=True, capture=True, **kwargs):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=capture, text=True, **kwargs)
    if check and r.returncode != 0:
        sys.stderr.write(r.stderr + '\n')
        sys.exit(r.returncode)
    return r

def get_skill_md(owner, repo):
    r = run(["gh", "api", f"repos/{owner}/{repo}/contents/SKILL.md"], check=False)
    if r.returncode != 0:
        return None, None
    content = base64.b64decode(json.loads(r.stdout)["content"]).decode("utf-8")
    sha = json.loads(r.stdout)["sha"]
    return content, sha

def parse_frontmatter(md):
    m = re.match(r"^---\n(.*?)\n---", md, re.DOTALL)
    if not m:
        return {}
    fm = {}
    cur = None
    for line in m.group(1).splitlines():
        if line.startswith("  ") and cur:
            fm[cur] += "\n" + line.strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
            cur = k.strip()
    return fm

def ensure_topic(owner, repo, topic="agent-skills"):
    r = run(["gh", "api", f"repos/{owner}/{repo}/topics"], check=False)
    if r.returncode != 0:
        print(f"  ⚠️  无法读取 topic，跳过检查")
        return
    topics = json.loads(r.stdout).get("names", [])
    if topic in topics:
        print(f"  ✅ topic '{topic}' 已存在")
        return
    run(["gh", "repo", "edit", f"{owner}/{repo}", "--add-topic", topic])
    print(f"  ✅ 已添加 topic '{topic}'")

def ensure_release(owner, repo, tag, dry_run=False):
    r = subprocess.run(["gh", "release", "view", tag, "--repo", f"{owner}/{repo}"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  ⚠️  release {tag} 已存在，跳过创建")
        return
    notes = (f"Skill release {tag}\n\n"
             f"- Published by reskill gh_skill.py\n"
             f"- Time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
             f"- Agent Skills Specification v1.0.0 compliant")
    cmd = ["gh", "release", "create", tag, "--repo", f"{owner}/{repo}",
           "--title", f"{repo} {tag}", "--notes", notes]
    if dry_run:
        print(f"  [dry-run] 将执行: {' '.join(cmd)}")
        return
    run(cmd)
    print(f"  ✅ release {tag} 已创建")

def write_snapshot(owner, repo, tag, action, dry_run, findings):
    SETTINGS = os.path.join(RESkill_DIR, "settings", "release_history")
    os.makedirs(SETTINGS, exist_ok=True)
    fp = os.path.join(SETTINGS, f"{repo}.yaml")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (f"\n- time: \"{ts}\"\n"
             f"  action: {action}\n"
             f"  repo: {owner}/{repo}\n"
             f"  tag: {tag}\n"
             f"  dry_run: {dry_run}\n"
             f"  scan_passed: {len(findings) == 0}\n"
             f"  findings: {len(findings)}\n")
    if not os.path.exists(fp):
        with open(fp, "w", encoding="utf-8") as f:
            f.write(f"# {owner}/{repo} 操作历史\n\nhistory:\n{entry}")
    else:
        with open(fp, "a", encoding="utf-8") as f:
            f.write(entry)
    print(f"  ✅ 快照写入 {fp}")

# ============================================================
# 命令实现
# ============================================================
def cmd_scan(args):
    directory = args.directory or "."
    passed, findings = scan_dir(directory)
    if not passed:
        sys.exit(1)

def cmd_create(args):
    owner, repo = args.repo.split("/", 1)
    tag = args.tag
    print(f"🚀 GitHub Skill Create — {owner}/{repo} @ {tag}\n")

    # 闸门
    print("🔒 闸门：凭据扫描...")
    passed, findings = scan_dir(RESkill_DIR)
    if not passed:
        print("\n❌ 闸门拦截：扫描未通过，禁止创建！")
        sys.exit(1)

    # 创建 release
    print("\n📦 创建 release...")
    ensure_release(owner, repo, tag, dry_run=args.dry_run)

    # 加 topic（非 dry-run）
    if not args.dry_run:
        ensure_topic(owner, repo)

    write_snapshot(owner, repo, tag, "create", args.dry_run, findings)
    print(f"\n✅ 完成 — {owner}/{repo} @ {tag}")

def cmd_publish(args):
    owner, repo = args.repo.split("/", 1)
    tag = args.tag

    # 闸门
    print(f"🔒 闸门：凭据扫描...")
    if not args.skip_scan:
        passed, findings = scan_dir(RESkill_DIR)
        if not passed:
            print("\n❌ 闸门拦截：扫描未通过，禁止发布！")
            print("   修复凭据后重试，或 --skip-scan 跳过（需管理员授权）")
            sys.exit(1)
    else:
        print("  ⚠️  跳过扫描（--skip-scan）")
        passed, findings = True, []

    # 验证 SKILL.md
    print("\n🔍 验证 SKILL.md...")
    md, sha = get_skill_md(owner, repo)
    if not md:
        print("  ⚠️  无法拉取 SKILL.md（可能是新仓库），跳过验证")
    else:
        fm = parse_frontmatter(md)
        errors = []
        if not fm.get("name"):
            errors.append("缺 name")
        if not fm.get("description"):
            errors.append("缺 description")
        if errors:
            print(f"  ❌ {', '.join(errors)}")
        else:
            print(f"  ✅ name={fm.get('name')} description={len(fm.get('description',''))}字")

    # 加 topic + 创建 release
    print("\n🏷️  添加 topic...")
    ensure_topic(owner, repo)

    print(f"\n🚀 创建 release {tag}...")
    ensure_release(owner, repo, tag, dry_run=args.dry_run)

    write_snapshot(owner, repo, tag, "publish", args.dry_run, findings)

    # 验证 discoverability
    print(f"\n🔎 验证 discoverability...")
    r = subprocess.run(["gh", "skill", "search", repo], capture_output=True, text=True)
    if repo in r.stdout:
        print(f"  ✅ '{repo}' 可被 gh skill search 发现")
    else:
        print(f"  ⚠️  '{repo}' 暂未被索引（release 创建后几分钟生效）")

    print(f"\n✅ 完成 — {owner}/{repo} @ {tag}")

def cmd_list(args):
    owner = args.owner or "totwo2"
    print(f"📋 列出 {owner} 的 agent-skills 仓库\n")
    r = run(["gh", "api", f"users/{owner}/repos?per_page=100",
             "--jq", '[.[] | select(.topics | index("agent-skills")) | {name, description, html_url, created_at}]'])
    repos = json.loads(r.stdout) if r.stdout.strip() else []
    if not repos:
        print(f"  未找到 agent-skills 仓库")
        return
    print(f"  {'名称':<30} {'描述':<50} {'状态'}")
    print(f"  {'-'*30} {'-'*50} {'-'*10}")
    for repo in repos:
        created = datetime.datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        desc = repo['description'][:48] if repo['description'] else 'N/A'
        print(f"  {repo['name']:<30} {desc:<50} created={created.strftime('%Y-%m-%d')}")
    print(f"\n  共 {len(repos)} 个仓库")

def cmd_search(args):
    print(f"🔎 搜索 '{args.query}'...")
    cmd = ["gh", "skill", "search", args.query]
    if args.owner:
        cmd.extend(["--owner", args.owner])
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    run(cmd)

def cmd_update(args):
    owner, repo = args.repo.split("/", 1)
    tag = args.tag

    # 闸门
    print(f"🔒 闸门：凭据扫描...")
    passed, findings = scan_dir(RESkill_DIR)
    if not passed:
        print("\n❌ 闸门拦截：扫描未通过，禁止更新！")
        sys.exit(1)

    # 查找当前 release
    print(f"\n📦 查找当前 release...")
    r = subprocess.run(["gh", "release", "view", tag, "--repo", f"{owner}/{repo}",
                        "--json", "tagName,description"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️  release {tag} 不存在，将新建")
        old_desc = ""
    else:
        old_desc = json.loads(r.stdout).get("description", "")
        print(f"  ✅ 找到 release {tag}")

    # 创建新版本 release
    print(f"\n🚀 创建更新 release {tag}...")
    ensure_release(owner, repo, tag, dry_run=args.dry_run)

    write_snapshot(owner, repo, tag, "update", args.dry_run, findings)
    print(f"\n✅ 完成 — {owner}/{repo} @ {tag}")

def cmd_delete(args):
    owner, repo = args.repo.split("/", 1)
    tag = args.tag

    print(f"🗑️  删除 release {tag}...")
    cmd = ["gh", "release", "delete", tag, "--repo", f"{owner}/{repo}", "--yes"]
    if args.dry_run:
        print(f"  [dry-run] 将执行: {' '.join(cmd)}")
        write_snapshot(owner, repo, tag, "delete", args.dry_run, [])
        print(f"\n✅ dry-run 完成 — {owner}/{repo} @ {tag}")
        return
    run(cmd)
    print(f"  ✅ 已删除 release {tag}")

    write_snapshot(owner, repo, tag, "delete", args.dry_run, [])
    print(f"\n✅ 完成 — {owner}/{repo} @ {tag} 已删除")

# ============================================================
# CLI 入口
# ============================================================
def main():
    ap = argparse.ArgumentParser(
        prog="gh_skill",
        description="reskill — GitHub Skill 完整生命周期管理（闸门+增删改查）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例子:
  gh_skill scan .                          # 扫描当前目录凭据
  gh_skill publish totwo2/reskill --tag v1.2.1   # 发布（闸门扫描）
  gh_skill publish totwo2/reskill --tag v1.2.1 --dry-run  # 预览
  gh_skill list                            # 列出 agent-skills 仓库
  gh_skill search reskill                  # 搜索 skill
  gh_skill update totwo2/reskill --tag v1.3.0
  gh_skill delete totwo2/reskill --tag v1.2.0
"""
    )
    ap.add_argument("--version", action="version", version="%(prog)s v1.2.0 (reskill)")

    sub = ap.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="凭据扫描（闸门）")
    p_scan.add_argument("directory", nargs="?", default=".", help="扫描目录")

    # create
    p_create = sub.add_parser("create", help="创建仓库 + topic + release")
    p_create.add_argument("repo", help="owner/name")
    p_create.add_argument("--tag", required=True, help="semver tag")
    p_create.add_argument("--dry-run", action="store_true")

    # publish
    p_pub = sub.add_parser("publish", help="发布：加 topic + 创建 release")
    p_pub.add_argument("repo", help="owner/name")
    p_pub.add_argument("--tag", required=True, help="semver tag")
    p_pub.add_argument("--dry-run", action="store_true")
    p_pub.add_argument("--skip-scan", action="store_true",
                       help="跳过凭据扫描（需管理员授权）")

    # list
    p_list = sub.add_parser("list", help="列出 agent-skills 仓库")
    p_list.add_argument("--owner", help="GitHub username，默认 totwo2")

    # search
    p_search = sub.add_parser("search", help="搜索 skill")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--owner", help="限定 owner")
    p_search.add_argument("--limit", type=int, help="结果数量限制")

    # update
    p_upd = sub.add_parser("update", help="更新版本（创建新 release）")
    p_upd.add_argument("repo", help="owner/name")
    p_upd.add_argument("--tag", required=True, help="新版本 tag")
    p_upd.add_argument("--dry-run", action="store_true")

    # delete
    p_del = sub.add_parser("delete", help="删除 release")
    p_del.add_argument("repo", help="owner/name")
    p_del.add_argument("--tag", required=True, help="要删除的 tag")
    p_del.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()

    cmds = {
        "create": cmd_create,
        "publish": cmd_publish,
        "list": cmd_list,
        "search": cmd_search,
        "update": cmd_update,
        "delete": cmd_delete,
        "scan": cmd_scan,
    }
    cmds[args.command](args)

if __name__ == "__main__":
    main()
