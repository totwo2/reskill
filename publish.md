# publish.md — Skill发布流程

> Main读这个文件。把skill推到Gitee/GitHub。

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

### 1. 创建仓库

```bash
gh repo create {仓库名} --public --description "{描述}"
```

### 2. 推代码

```bash
cd {skill目录}
git init
git add -A
git commit -m "v1.0: 初始发布"
git remote add origin https://github.com/{用户名}/{仓库名}.git
git push -u origin master
```

---

## 版本号规范

```
v1.0 — 初始发布
v1.1 — 小修改（修复bug、更新文档）
v2.0 — 大改（架构变化、新模块）
```

---

## 发布后监控同步

发布完成后调一下同步脚本，将新增skill自动加入监控清单：

```bash
python3 scripts/fetch_my_skills.py  # 从 ~/.skillhub/credentials.json 读token
```

该脚本会：
- 从 SkillHub 官方 API `/api/v1/users/<handle>/skills` 拉取本账号名下全部 skill
- 与 `reskill_config.yaml` 的 `skillhub.skills` 段对比
  - **云端新增** → 自动追加到配置
  - **云端缺失** → 告警（可能下架）
  - **display_name 不一致** → 同步成云端名称
- 写云端快照到 `settings/my_skills_snapshot.yaml` 供审计
- 退出码 0（无变化） / 2（有新增待写入配置）

---

## gh skill 发布进阶（调研中）

> GitHub Agent Skills 官方发布路径（2026-04 GitHub 支持）。
> 本节为调研笔记，不是马上投产的脚本。

### gh skill CLI 状态
- gh CLI ≥ v2.90.0 可用，本机 2.94.0 (preview)
- 子命令：`search` / `install` / `preview` / `list` / `update` / `publish`
- 别名：`gh skills`

### 发布完整流程（官网规范，调研后补全）
1. **结构校验**：仓库路径遵守 `<owner>/<skill-name>`，根目录包含 `SKILL.md`（YAML frontmatter name+description + Markdown 正文）
2. **可选文件夹**：`scripts/`、`references/`、`assets/`（保持一层深）
3. **发布命令**：`gh skill publish <owner>/<repo>`（或带 `--dry-run` 先预览）
4. **后索引动作**：gh 会在仓库添加 `agent-skills` topic tag + 仓库 description 附上 skill manifest
5. **更新动作**：`gh skill update <owner>/<repo>` 重新拉索引（版本号在 SKILL.md frontmatter 改）

### 关键差异（vs skillhub publish）
- gh skill 不强制扫描凭据，**依赖 GitHub Secret scanning + Code scanning + Dependabot**
- gh skill publish 不打包（仓库即目录），`.gitignore` 有效
- gh skill 索引会读 SKILL.md frontmatter，name/description 不合格会拒绝发布

### 本 reskill 的 GitHub 发布检查清单
- [ ] SKILL.md frontmatter name 1-64 字符（小写字母数字连字符，首尾/连续连字符不允许）
- [ ] description 1-1024 字符，含触发关键词
- [ ] 仓库 description 已填
- [ ] topic `agent-skills` 已加
- [ ] LICENSE 文件存在（MIT）
- [ ] 已跑 `gh skill publish --dry-run` 看到 ✅

详细调研结果待续…

---

## 发布检查清单

- [ ] **已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0**（硬性前置）
- [ ] SKILL.md 有 name 和 description
- [ ] 所有模块文件存在
- [ ] README.md 写清楚使用方法
- [ ] 没有敏感信息（token、密码、个人路径）
- [ ] 版本号已更新
- [ ] **发布后已跑 `python3 scripts/fetch_my_skills.py`**（自动同步监控清单）
