# publish.md — Skill发布流程

> Main读这个文件。把skill推到SkillHub社区源 / Gitee / GitHub。

---

## 🎯 首选通道：SkillHub 社区源发布（v1.2.0 新增）

**SkillHub 是本技能生态的主发布地**（api.skillhub.cn），无需 Git 仓库即可上线，自带下载量/安装量追踪（配合 `scripts/check_downloads.py`）。

### 前置条件

1. 本机已安装 skillhub CLI（`~/.skillhub/skills_store_cli.py`，wrapper 在 `~/.local/bin/skillhub`）。
2. **已登录**：`skillhub login --key skh_xxx`（token 只存在于本机登录态，**绝不写入 skill 包内任何文件**）。
3. 待发布 skill 的 `SKILL.md` frontmatter 必须含：`slug`（kebab-case 3-128）、`displayName`、`version`（SemVer）、`description`。
4. **发布前凭据扫描（硬性）**：`bash scripts/preflight_secret_scan.sh . --all` → 退出码必须 0。

### 发布命令

```bash
# 预检（本地校验 metadata + 打包，不发 HTTP）
skillhub publish {skill目录} --dry-run

# 正式发布
skillhub publish {skill目录} --changelog "v1.0: 初始发布"
```

- `--version` 可覆盖 SKILL.md 中的 version。
- `--token` 覆盖登录态 token（CI 用，**仍不进包**）。
- 输出含新发布/更新的 slug + 版本即成功。

### 版本更新

```
1. 修改 skill 文件
2. 更新 SKILL.md frontmatter 里的 version
3. skillhub publish {skill目录} --changelog "v1.1: {更新内容摘要}"
```

### ⚠️ 打包注意（token 保护）

**skillhub publish 打包不遵守 `.gitignore`，会把目录里所有文件打进 zip。** 发布前必须确认：

- ❌ 目录里没有 `settings/reskill_config.yaml`（真 token 配置）——只有 `reskill_config.example.yaml`（占位符）才安全
- ❌ 没有 `download_history.yaml` / `feedback_report.md` 等本地运行产物
- ❌ 没有 `.git/`、`_meta.json` 等本地状态文件
- ✅ 有 `*.example.*` 脱敏模板 + 凭据扫描 exit 0，才能发

**真 token 只走登录态（`skillhub login --key`）或 `--token` 参数，任何情况下不落进 skill 目录。**

---

## Gitee / GitHub 发布（备选通道）

---

## ☠️ 发布前硬性红线（每次必做，不可跳过）

**任何 git push / skillhub publish 之前，必须先跑凭据扫描：**

```bash
# git push 前（尊重 .gitignore，只扫将入库的文件）
bash scripts/preflight_secret_scan.sh .

# skillhub publish 前（打包不看 .gitignore，扫全部文件）
bash scripts/preflight_secret_scan.sh . --all
```

- 退出码 **0** = 通过，才能发布。
- 退出码 **1** = 命中凭据，**立即中止发布**，先把凭据移出仓库（改用 `*.example.*` 脱敏 + `.gitignore`）再重扫。

历史教训（2026-06-12 `50c6124` 提交把 gitee token 明文推入公开仓库，汄露约一个月）：
1. 仓库从建立起无 `.gitignore` → 无机制阻止敏感文件入库
2. 配置与凭据未分离（token 混在 reskill_config.yaml）
3. 发布前无凭据扫描
→ 三道防线现均已补：`.gitignore` + `*.example.*` 脱敏 + 本扫描器。

**skillhub publish 特别注意**：打包不遵守 `.gitignore`，发布前必须把含 token 的 `settings/reskill_config.yaml`、`download_history.yaml`、`feedback_report.md` 临时移出目录（以及 `.gitignore` 本身，skillhub 不接受该文件类型），发布后再移回。

---

## 发布流程

### 首次发布

```
1. 确认skill目录完整（SKILL.md + 所有模块文件）
2. git init
3. git add -A
4. git commit -m "v1.0: 初始发布"
5. git remote add origin {仓库地址}
6. git push -u origin master
```

### 版本更新

```
1. 修改skill文件
2. 更新版本号（在SKILL.md或README.md里）
3. git add -A
4. git commit -m "v1.1: {更新内容摘要}"
5. git push
```

---

## 平台选择

| 平台 | 优势 | 劣势 |
|------|------|------|
| Gitee | 国内稳定，速度快 | 国际用户少 |
| GitHub | 全球通用，skillhub支持 | 国内不稳定 |

**建议：** 国内用户用Gitee，国际用户用GitHub。两个都推也行。

---

## Gitee发布步骤

### 1. 创建仓库

```bash
curl -s -X POST "https://gitee.com/api/v5/user/repos" \
  -H "Content-Type: application/json" \
  -d '{
    "access_token": "{token}",
    "name": "{仓库名}",
    "description": "{描述}",
    "private": false,
    "auto_init": false
  }'
```

### 2. 推代码

```bash
cd {skill目录}
git init
git remote add origin https://{用户名}:{token}@gitee.com/{用户名}/{仓库名}.git
git add -A
git commit -m "v1.0: 初始发布"
git push -u origin master
```

### 3. 版本更新

```bash
git add -A
git commit -m "v1.1: {更新内容}"
git push
```

---

## GitHub发布步骤

### 方式一：gh skill publish（Agent Skills 标准发布）

GitHub Agent Skills 规范支持通过 `gh skill publish` 直接发布技能包到 GitHub 仓库。

```bash
# 预检（dry-run，不实际推送）
gh skill publish --dry-run

# 正式发布
gh skill publish
```

- 自动创建/更新 GitHub 仓库，技能以标准目录结构存储。
- 安装者可通过 `gh skill install {owner}/{repo} {skill-name}` 一键安装。
- 发布前确保 SKILL.md frontmatter 符合 Agent Skills 规范（name 全小写连字符、description 有英文）。

### 方式二：手动创建仓库 + 推代码

```bash
# 1. 创建仓库
gh repo create {仓库名} --public --description "{描述}"

# 2. 推代码
cd {skill目录}
git init
git add -A
git commit -m "v1.0: 初始发布"
git remote add origin https://github.com/{用户名}/{仓库名}.git
git push -u origin master
```

### CN 网络加速（GitHub clone 超时处理）

如果 `git clone https://github.com/...` 超时，替换域名为镜像：
- `github.com` → `kkgithub.com`（首选）
- `github.com` → `bgithub.xyz`（备选）
- 或加代理前缀：`https://gh-proxy.com/https://github.com/...`

---

## 版本号规范

```
v1.0 — 初始发布
v1.1 — 小修改（修复bug、更新文档）
v2.0 — 大改（架构变化、新模块）
```

---

## 发布检查清单

- [ ] **已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0**（硬性前置）
- [ ] SKILL.md 有name和description
- [ ] 所有模块文件存在
- [ ] README.md 写清楚使用方法
- [ ] 没有敏感信息（token、密码、个人路径）
- [ ] 版本号已更新
