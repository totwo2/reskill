# publish.md — Skill发布流程

> Main读这个文件。把skill推到Gitee/GitHub。

---

## 凭据扫描：边界与责任

**扫描是发布期闸门，只保护开发者，不检查用户数据。**

| 角色 | 谁的数据 | 是否扫描 | 在哪里 |
|---|---|---|---|
| **开发者**（写 reskill、上传 GitHub/Gitee 仓库的人） | reskill_config.yaml.example、SKILL.md、scripts/*、download_history.yaml 里的示例值 | **必扫** | 即将 commit / push 的文件 |
| **最终用户**（下载 reskill 跑监控的人） | settings/reskill_config.yaml（真实 token）、settings/download_history.yaml（自己的下载快照）、settings/feedback_report.md、settings/my_skills_snapshot.yaml | **绝不扫描** | 用户的本地 settings/ 目录 |

**边界划分原则：**

1. **reskill_config.yaml.example**（脱敏模板、公开入库）→ 必须扫，确保无真实凭据
2. **settings/reskill_config.yaml**（用户实例、含真实 token）→ 必须被 `.gitignore` 排除，绝不入库
3. **下载快照、反馈报告、名下快照**（用户运行时数据）→ 全部被 `.gitignore` 排除
4. **scripts/preflight_secret_scan.sh** 默认走 `.gitignore` 范围（开发者视角），加 `--all` 才扫所有（仅 skillhub publish 临时使用）

**为什么这样划分：**

- 凭据扫描的目的是**保护开发者不因疏忽推 token 到公开仓库**
- 用户的 token 是用户自己的资产，必须保留在本地、必须升级时不丢
- 扫描用户数据 = 破坏升级体验（升级不能要求用户重新填 token）+ 侵犯隐私

**如果发现扫描命中用户 settings/ 下的文件：**

- 立即停止扫描
- 检查 `.gitignore` 是否已排除该文件（`settings/*`）
- 如果已排除但扫描仍命中 → 升级扫描器逻辑，跳过 `.gitignore` 内的文件
- 绝不向用户报错 "你的 token 泄露了"（这是误报，用户 token 本就在 settings/）

---

## ☠️ 发布前硬性红线（每次必做，不可跳过）

**任何 git push / skillhub publish 之前，必须先跑凭据扫描：**

```bash
# git push 前（尊重 .gitignore，只扫将入库的文件——这是日常使用方式）
bash scripts/preflight_secret_scan.sh .

# skillhub publish 前（打包不看 .gitignore，扫全部文件——临时使用）
bash scripts/preflight_secret_scan.sh . --all
```

- 退出码 **0** = 通过，才能发布。
- 退出码 **1** = 命中凭据，**立即中止发布**，先把凭据移出仓库（改用 `*.example.*` 脱敏 + `.gitignore`）再重扫。
- **扫描不命中用户 settings/ 下的真实 token**——见上面"凭据扫描：边界与责任"章节

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

## 发布到 GitHub Release（gh release create）专用 playbook

> 裸 `git push` + tag **不算正式发布**。GitHub Release = tag + 标题 + 发布说明 + 自动 zip/tarball，用户才能在 Releases 页订阅/下载。**必须建 Release，不能只推 tag。**
> （selfopt 曾只推了 tag 没建 Release，后补 `gh release create v2.0.3` 才补齐。）

### 关键认知：tag ≠ Release
- **tag** 只是历史锚点（Git ref），无标题、无说明、无下载入口。
- **GitHub Release** 建立在 tag 之上，带标题 + 发布说明 + 自动下载包，是正式"发布"。
- `gh release create <tag>`：tag 不存在时**自动从默认分支最新状态建 tag + Release 一步到位**；tag 已存在则直接挂 Release。

### 首次发布（gh）

```bash
1. 代码已 commit 到 master/main（含双语 README、LICENSE、SKILL.md 的 slug/displayName）
2. 建仓库（若还没有）：
   gh repo create {仓库名} --public --description "{描述}"
3. git push -u origin master
4. 建首个 Release（自动建 tag + Release）：
   gh release create v1.0 -t "v1.0 {一句话}" -n "{发布说明，gh 侧用双语}"
5. git fetch --tags origin   # 把新 tag 拉回本地
6. 同步发 sh（中文 README，同版本号）—— 走"双发软件两边一起发"纪律
```

### 后续增量发布（gh）

```bash
1. 改完代码，commit 到 master/main
2. 先定版本号并和 sh 对齐（两边同 numeric 版本；gh 带 v，sh 不带）
3. gh release create vX.Y.Z --generate-notes
   # --generate-notes：调用 Release Notes API 自动汇总上次 Release 以来的 commit，生成标题+说明，默认标 latest
   # 想手写说明：-F changelog.md 或 -n "..."
4. git fetch --tags origin   # 同步本地 tag
5. 立刻发 sh 同版本（临时换中文 README → skillhub publish . --version X.Y.Z → 恢复双语 README）
```

### 可选参数
- `-t/--title` 标题；`--latest`（默认）标最新；`-p/--prerelease` / `-d/--draft`
- `--verify-tag`：若先在本地建 tag 再确保远端已存在，用它兜底
- 建完 `git fetch --tags origin` 把新 tag 拉回本地

### 我们这边的固定约束（叠加在官方流程上）
- **SemVer**：`v主.次.修`；gh tag 带 `v`、sh 去 `v`、数字一致。
- **README 分流**：gh README 保持**双语**（repo 源文件）；sh 才临时换**单语中文**——两边下载包内容天然分流，符合"gh 双语 / sh 中文"规范。
- **发布说明**：gh 侧用双语（面向 gh 受众）；sh changelog 用中文。
- **双发纪律**：双发软件（gh + sh）更新必须两边同步、同版本号一起发，不单方面漏一边。
- ⚠️ **SkillHub 不允许同版本重发**（报 `slug 冲突: 版本 X 已存在，请使用新的版本号发布`）。故"同版本改成中文"走不通，只能两平台同升一个新版本号来满足"sh 中文 + 版本一致"。

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

## GitHub Agent Skills 官方发布/更新结构规范（已固化）

> 来源：https://agentskills.io/specification.md + gh CLI v2.94.0 实测
> 最后更新：2026-08-11

### 发布要求（publish）

| 要求 | 说明 | 验证方式 |
|------|------|----------|
| 仓库 public | 必须公开 | `gh repo view --json visibility` |
| `agent-skills` topic | gh skill publish 自动添加 | `gh api repos/<owner>/<repo>/topics` |
| SKILL.md frontmatter | name+description 必填，allowed-tools 必须是字符串 | `gh skill publish --dry-run` |
| name 规则 | 1-64字符，仅小写字母数字连字符，首尾/连续连字符不允许，必须与目录名相同 | agentskills.io 规范 |
| description 规则 | 1-1024字符，描述用途+触发场景 | agentskills.io 规范 |
| Release 存在 | 每个版本必须有对应 tag + release | `gh release list` |
| 版本标签 | semver 推荐（v1.2.0），--tag 指定 | `gh skill publish --tag v1.2.0` |
| Skill 发现约定 | `skills/*/SKILL.md`、`skills/{scope}/*/SKILL.md`、`*/SKILL.md`、`plugins/{scope}/skills/*/SKILL.md` | gh skill install 实测 |
| 自动清理 | publish 会剥离 install metadata（`metadata.github-*`） | `gh skill publish --fix` |

### 更新要求（update）

| 要求 | 说明 |
|------|------|
| 版本通过 git tag 管理 | 每次更新打新 tag |
| 版本解析优先级 | 最新 tagged release > 默认分支 HEAD |
| 已安装 skill 的 source tracking | frontmatter 注入 source repo 信息，用于 update 检测变化 |
| 固定版本 | `gh skill install --pin v1.2.0` 或 `skill@v1.2.0` |
| 更新命令 | `gh skill update --all` 或 `gh skill update <owner>/<repo>` |

### gh skill publish 命令
```bash
# 预览验证（不发布）
gh skill publish --dry-run

# 指定 tag 发布（非交互）
gh skill publish --tag v1.2.0

# 自动修复可修复问题（剥离 install metadata）
gh skill publish --fix
```

### gh skill update 命令
```bash
# 更新所有已安装 skill
gh skill update --all

# 更新指定 skill
gh skill update <owner>/<repo>
```

### 关键差异（vs skillhub publish）
- gh skill 不强制扫描凭据，**依赖 GitHub Secret scanning + Code scanning + Dependabot**
- gh skill publish 不打包（仓库即目录），`.gitignore` 有效
- gh skill 索引会读 SKILL.md frontmatter，name/description 不合格会拒绝发布
- skillhub publish 打包不看 .gitignore，发布前必须临时移走含 token 的文件

### 本 reskill 的 GitHub 发布检查清单
- [ ] SKILL.md frontmatter name 1-64 字符（小写字母数字连字符，首尾/连续连字符不允许）
- [ ] description 1-1024 字符，含触发关键词
- [ ] name 与目录名相同
- [ ] allowed-tools 是字符串（不是数组）
- [ ] 仓库 description 已填
- [ ] topic `agent-skills` 已加
- [ ] LICENSE 文件存在（MIT）
- [ ] 每个版本有对应 tag + release
- [ ] 已跑 `gh skill publish --dry-run` 看到 ✅
- [ ] 已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0（硬性前置）

---

## 发布检查清单

- [ ] **已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0**（硬性前置）
- [ ] SKILL.md 有 name 和 description
- [ ] 所有模块文件存在
- [ ] README.md 写清楚使用方法
- [ ] 没有敏感信息（token、密码、个人路径）
- [ ] 版本号已更新
- [ ] **发布后已跑 `python3 scripts/fetch_my_skills.py`**（自动同步监控清单）
