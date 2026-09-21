# publish.md — Skill发布流程

> Main读这个文件。**发布前先过 `publish-quality.md` 质量闸门**，再按本文推到 GitHub / SkillHub。
> 代码能跑 ≠ 发布物能看。简介、标签、README、SKILL.md 不合格，不许发。

---

## 凭据扫描：边界与责任

**扫描是发布期闸门，只保护开发者，不检查用户数据。**

| 角色 | 谁的数据 | 是否扫描 | 在哪里 |
|---|---|---|---|
| **开发者**（写 reskill、上传 GitHub 仓库的人） | reskill_config.yaml.example、SKILL.md、scripts/*、download_history.yaml 里的示例值 | **必扫** | 即将 commit / push 的文件 |
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

**任何 git push / skillhub publish 之前，必须先跑综合检查闸门（凭据 + 个人痕迹 + 结构）：**

```bash
# 总闸门（推荐，覆盖全部）：凭据扫描 + 个人痕迹词库 + 结构完整性
bash scripts/preflight_publish_check.sh .

# 仅凭据扫描（总闸门内部已包含，单独跑用于快速排障）
bash scripts/preflight_secret_scan.sh .
```

- **退出码 0 = 通过，才能发布。**
- **退出码 1 = 命中，立即中止发布**，修复命中项后重扫。
- 综合检查覆盖（2026-08-25 教训固化）：
  1. 凭据扫描（复用 preflight_secret_scan.sh 全部模式）
  2. 个人痕迹词库：第三方借鉴（Headroom/JiangGong/vLLM/…）、平台品牌（workbuddy）、实验语境（窗口一/实验 v4）、旧业务词（zhangsan/财务部/公文/审批…）、个人绝对路径、剥离/边界叙事（"已剥离"/"不含（边界说明）"）——**此处为摘要，完整词库以 `scripts/preflight_publish_check.sh` 的 PATTERNS 为单一真源**；本文件本身的这类命中已在 `scripts/preflight_allow.txt` 登记豁免
  3. 结构完整性：SKILL.md frontmatter、README 双语、MANIFEST 引用文件存在、pytest 配置有效、无 .venv/__pycache__ 入库

**教训（2026-08-25）：** 仅凭据扫描不够——发布后才发现 README 非双语、含边界说明、代码带旧业务词/实验语境/品牌残留，被迫 force-push 重写历史。综合闸门把这些从"靠人审查"变成"机制拦截"。

历史教训（2026-06-12 `50c6124` 提交把 gitee token 明文推入公开仓库，汄露约一个月）：
1. 仓库从建立起无 `.gitignore` → 无机制阻止敏感文件入库
2. 配置与凭据未分离（token 混在 reskill_config.yaml）
3. 发布前无凭据扫描
→ 三道防线现均已补：`.gitignore` + `*.example.*` 脱敏 + 本扫描器。

**skillhub publish 特别注意**：打包不遵守 `.gitignore`，发布前必须把**全部个人实例数据**临时移出目录（以及 `.gitignore` 本身，skillhub 不接受该文件类型），发布后再移回。完整清单（2026-08-18 校准，覆盖所有运行时产物）：

```bash
# 发布前：移出个人实例数据（skillhub 打包不看 .gitignore，不移必漏）
mkdir -p /tmp/reskill_publish_exclude
cd {skill目录}
mv settings/reskill_config.yaml settings/download_history.yaml \
   settings/feedback_report.md settings/my_skills_snapshot.yaml \
   settings/daily_state.json \
   settings/release_history .workbuddy _meta.json \
   /tmp/reskill_publish_exclude/
mv .gitignore /tmp/reskill_publish_exclude/   # skillhub 不接受该文件类型

# skillhub publish ...

# 发布后：全部移回
mv /tmp/reskill_publish_exclude/reskill_config.yaml \
   /tmp/reskill_publish_exclude/download_history.yaml \
   /tmp/reskill_publish_exclude/feedback_report.md \
   /tmp/reskill_publish_exclude/my_skills_snapshot.yaml \
   /tmp/reskill_publish_exclude/daily_state.json \
   /tmp/reskill_publish_exclude/release_history \
   /tmp/reskill_publish_exclude/.workbuddy \
   /tmp/reskill_publish_exclude/_meta.json \
   settings/ 2>/dev/null; mv /tmp/reskill_publish_exclude/.gitignore .
rmdir /tmp/reskill_publish_exclude
```

发布前可跑 `git ls-files` 检查进包清单，确认 `settings/` 下**只剩 `reskill_config.example.yaml`**（脱敏模板）——这是"干净发布"的硬标准。

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

## 平台与形态（定形态是第一步）

> **先读 `publish-quality.md`。形态错了，后面 README / 元数据全白做。**

| 平台 | 发布形态 | 入口文件 | 版本写法 | 受众语言 |
|---|---|---|---|---|
| **GitHub** | 普通项目仓库（什么都能发） | `README.md` | `v1.2.0`（带 v） | 英文优先 |
| **SkillHub** | **skill installer 形态（只能发 skill）** | `SKILL.md` | `1.2.0`（不带 v） | 中文优先 |

- 把 GitHub 普通项目直接推 SkillHub → 无 `SKILL.md` / 缺 `slug` → 发布被拒或装不上
- 把 SkillHub 的 skill 原样推 GitHub → 主页是"技能说明"不是"项目主页" → 没人停留

**形态判定谁来做（2026-09-17 老高定）：** 由专家团「分发形态判定官」（`form-decider`）出结论 ——
`verdicts/<指纹>/04-form.md`。**主理人不代判**（代判即顶替成员产出）。发布执行照该结论走，
**判定结果不必再回问老高**。判据见 `publish-quality.md` §一。

**Gitee 已于 2026-09-11 从本项目移除，不再是发布目标。**

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

### skillhub publish 已知限制（2026-09-06 no-bb 发布实测）
- **SKILL.md frontmatter 必须有 `slug` 字段**（与 name 一致即可），缺失报 `SKILL.md 缺少 slug`
- **--version 必须三段 SemVer**（1.0.0 ✓，1.0 ✗ 报 `version 不是合法 SemVer`）——与 gh 侧 vX.Y.Z 数字对齐但 skillhub 侧永不带 v
- 发布成功返回 `✓ Published: skillId=<id>`，把 id 记入 reskill_config.yaml 的 skillhub.repos/skills 段做监控

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
- [ ] **About topics 已加（所有 gh 仓库通用，老高 2026-09-06 定）**：skill 仓库加 `agent-skills`；普通软件仓库 15~20 个 topic，**两组词都要覆盖**：①技术分类词（ai/llm/proxy/python/…）②效果作用词（项目省/快/优化的维度，如 token-optimization/latency/cost-optimization/test-time-compute——搜作用词的人才是被痛点扎到的目标用户）；命令：
  `gh api repos/<owner>/<repo>/topics -X PUT --input - <<< '{"names":["t1","t2"]}'`
- [ ] topic `agent-skills` 已加（skill 仓库）
- [ ] LICENSE 文件存在（MIT）
- [ ] 每个版本有对应 tag + release
- [ ] 已跑 `gh skill publish --dry-run` 看到 ✅
- [ ] 已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0（硬性前置）

---

## 对外产物里的路径怎么写（作者侧约定）

**一句话判据：这段路径是给谁看的？给机器执行的写「值」，给人 / 大模型看的写「形状」。**

| 载体 | 谁决定这个地址 | 写法 |
|---|---|---|
| 平台集成代码：hook 挂载点、运行时探测、配置文件位置 | **平台规定**，不由大模型安排 | **真实地址**——写含糊就装不上 |
| 面向大模型 / 读者的说明：SKILL.md、references、模板、README | 大模型自己拼，或由代码算好注入 | **占位符 / 形状 / 相对路径** |

**四级优先（与功能无关的路径一律按此写）：**

1. **占位符** —— `{evidence_dir}`。由代码算好注入时首选；`{...}` 长得就像待填，不会被静默复制。
2. **形状** —— `<工作区>/reports/<日期>/evidence/<角色号>`。要大模型自己拼时用。
3. **相对路径** —— `evidence/A01/01-install.log`。能相对就相对，最短、最不易出错。
4. **绝不写真实值** —— 盘符下的用户目录、家目录下的具体用户名，一律不出现。

**第 4 条不是洁癖**：真实值在对方机器上**根本不存在**，照着字面执行就是失败——它同时是功能缺陷与个人痕迹，两件事一个根。

**自检**：同一份文档里「一处用占位符、另一处写死样例」即视为缺陷——写死的那处会把人带偏。

**合法例外**：`/tmp/xxx`、`./relative/path` 这类可移植且不含个人信息的路径可以直接写。判据是「换台机器还能不能跑」，不是「看起来像不像路径」。

---

## 发布总闸门（五道，顺序执行；任一不过 = 不许发）

### 闸门 0 · 发布物质量（最容易翻车的一道，详见 publish-quality.md）

- [ ] **形态选对**：GitHub = 普通项目（README 入口）；SkillHub = skill installer（SKILL.md 入口）
- [ ] **双平台同名可对应**（不许 gh 一个名、sh 一个拼音名）
- [ ] **description 是用户视角**：说收益，不说实现机制；SkillHub 侧必须带触发词
- [ ] **topics 已填且两组词齐全**（技术分类词 + 效果作用词），GitHub 侧 15~20 个
- [ ] **README 过 3 秒测试**：钩子 → 数字 → 30 秒上手 → 装完验证（原理放后面）
- [ ] **SKILL.md 是执行手册**：description 带触发词、命令可复制、用法在前 1/3、有适用边界、无开发日志
- [ ] **双维度打分**：用户视角 ≥3 分 **且** 大模型视角 ≥3 分

### 闸门 1 · 凭据与个人痕迹

- [ ] 已跑 `bash scripts/preflight_publish_check.sh .` 且退出码 0
- [ ] 无 token / 个人绝对路径 / 第三方品牌残留

### 闸门 2 · 结构完整性

- [ ] SKILL.md frontmatter 齐全（name / slug / displayName / description）
- [ ] README 存在（GitHub 侧双语）
- [ ] MANIFEST 引用的文件都存在
- [ ] 无 .venv / __pycache__ 入库

### 闸门 3 · 版本

- [ ] gh 与 sh 版本号数字一致（gh 带 `v`，sh 不带）
- [ ] SkillHub 同版本不可重发，必须升号

### 闸门 4 · 发布后

- [ ] 已跑 `python3 scripts/fetch_my_skills.py` 同步监控清单
- [ ] 输出契约三行：版本号 / 平台链接 / 同步状态 → **收口，不再输出改进建议**
