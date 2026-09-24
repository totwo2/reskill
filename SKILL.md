---
name: reskill
slug: reskill
version: 3.5.1
kind: feature
license: MIT
homepage: https://github.com/totwo2/reskill
# kind 决定 README 前 30 行按哪套判据（闸门 preflight_quality_check.py）：
#   perf    优化类 —— 收益本身是数字，必须给量化佐证（selfopt / no-bb 属此类）
#   feature 功能类 —— 以前没有这能力，无基线可比，写「它自动替你做了什么」
# reskill 是功能类：它把「人肉发版」这件事自动化，没有可对照的性能基线，
# 硬编一个「效率提升 X%」反而违反本项目自己的「数字必须可复算」。
displayName: Skill发布质量闸门与反馈系统
description: |
  发 skill 之前先审代码：第三方审计代理对照需求查覆盖/超纲/幻觉，再过质量闸门——
  形态适配（GitHub 项目 / SkillHub 三分支判定）、简介与标签、README 用户视角、SKILL.md 大模型视角。
  过闸后按判定结果发布到 GitHub + SkillHub，追踪下载量趋势、收集 issue 反馈、多渠道通知作者决策。
  触发词：发布skill、推到github、推到skillhub、发版、走完整发布流程、全自动发布、
  审代码、代码真的实现了吗、有没有超纲、谁来判、判定派发、
  检查反馈、用户意见、优化skill、下载量、下载趋势、同步skill列表、查名下skill、配置通知
topics:
  - agent-skills
  - skill-publishing
  - release-automation
  - publish-pipeline
  - github-release
  - skillhub
  - quality-gate
  - code-audit
  - preflight-check
  - version-management
  - ci-cd
  - one-click-publish
  - publish-safety
  - unattended-release
  - release-checklist
  - download-tracking
  - feedback-collection
  - content-quality
  - skill-maintenance
license: MIT
allowed-tools: "Read Write Edit Bash Glob Grep WebFetch WebSearch Skill Agent"
---

# reskill — Skill 发布质量闸门与反馈系统

> 发布物质量不合格，就不许发。发完之后，持续收反馈。

---

## 三段分工：谁判、谁审、谁发

发布分成三段。**只有第三段可以单独使用**；前两段都是判定，判定不能自评。

> **先分清主体：这三段是「发布闸门专家团」的三段，不是 reskill 的三段。**
> reskill 是三段**共用的判据库 + 工具箱**——它提供判据（规则文档）、量尺（检查脚本）、执行件（发布脚本），
> 但它自己**不产出任何发布物**。写简介、写标签、写 README 是第②段写手岗位的活；
> reskill 只在旁边递尺子（`check_discoverability.py` 量标签有没有人搜），量完报数，不替你写。
>
> **团队里具体有哪些专家、各自干什么、拿什么工具，见 `publish-team-roster.md`（角色单一真源）。**

| 段 | 谁 | 用什么 | 判什么 |
|---|---|---|---|
| ① 机器判定 | `gate` 命令 | `gate check <目录>` / `gate inbox <目录>`；内部**复用**本 skill 的 `preflight_secret_scan.sh`、`preflight_publish_check.sh` | 硬错：凭据泄漏、个人痕迹、版本打架、标签格式 |
| ② 独立评审 | 「发布闸门专家团」`publish-gate-team` | 只读 `gate inbox` 产出的**物料箱**；**产出** README / 简介 / 标签 进暂存区 | 软质量：形态判断、简介与标签、README 首屏、文案、跨出口一致性 |
| ③ 执行发布 | **本 skill 的脚本 + gh 官方命令** | **SkillHub**：`pack_skillhub.sh` 出干净副本 → `skillhub publish`。**GitHub**：`gh_skill.py` / `local_publish.py` 推文件 → **建 release 按布局选**（`publish.md` §检查清单）：`skills/<name>/` 布局用 `gh skill publish --tag vX.Y.Z`（在**仓库根**跑），根级 `SKILL.md` 布局用 `gh_release.py` | 不改判据，只按前两段的结论动手 |

**三条边界（违反任意一条 = 拆闸门）：**

- **① 不许绕过。** 直接跑 `preflight_*.sh` 而不经 `gate`，等于自己给自己判。`gate` 只是**调用**这些脚本——判据仍在本 skill 里，所以改判据等于同时改闸门，按纪律必须先报批。
- **② 不许自评。** 本 skill 的 `preflight_quality_check.py` / `quality_metrics.py` 是**作者自查工具**，不能当终审。终审是专家团（独立上下文，陌生人视角）。
- **③ 是唯一可单独使用的段。** `gate` 只判不放行——它不写 README、不打包、不推 GitHub、不推 SkillHub。最后一米永远是本 skill 的执行件（含 gh 官方命令，如 `gh skill publish`）。

> 一句话：**reskill 是「闸门之后的执行手册 + 判据库」，不是「可以绕过的裁判」。**

---

## 启动路由

> **发布类请求第一步永远是 `gate inbox <候选包目录>`。**
> 它一次完成「检查 + 冻结指纹 + 打包物料箱」，并把**物料箱目录**打印出来 ——
> 那个目录就是交给「发布闸门专家团」（`publish-gate-team`）的**全部输入**。
> 机器判定 `REJECT` → 就地改产物重跑，不要往下走。
> 给专家的东西只有两样：**物料箱路径 + 该岗位判据路径**，多一个字都是喂料。

| 用户说 | 动作 |
|--------|------|
| "发布skill" / "推到github" / "推到skillhub" | **`gate inbox`** → 召唤「发布闸门专家团」审 → publish.md 执行发布 |
| "发版" / "走完整发布流程" / "全自动发布" | **scripts/local_publish.py**（单入口：一条命令反复调，机器节点自动判、语义节点停下出题） |
| "谁来判" / "这一步好不好谁负责" / "判定派发" | **scripts/verdict_dispatch.py** → 出题（判定任务单）/ 收卷（校验判定合法性） |
| "审代码" / "这代码真的实现了吗" / "有没有超纲" | **publish-code-audit.md** → 覆盖表 / 超纲表 / 幻觉表 |
| "检查发布物质量" / "这 README 行不行" | publish-quality.md → 双维度打分 |
| "这批标签有没有人搜" / "可发现性" | scripts/check_discoverability.py → **只量**每个标签的真实搜索池 + 名称查重。**写标签是第②段写手岗位的活，本 skill 不产出标签** |
| "该写数字还是写功能" / "这项目算哪类" | **看有没有基线**：有（改前 vs 改后）= `perf`，必须给数字；没有（以前根本没这能力）= `feature`，写「它自动替你做了什么」。声明在 SKILL.md 的 `kind:`，闸门按它选判据 |
| "检查反馈" / "有没有issue" / "用户意见" | feedback-collector.md → 检查 GitHub issues + SkillHub 数据 |
| "下载量" / "下载趋势" / "有没有新下载" | scripts/check_downloads.py → 对比快照+增量提醒 |
| "同步skill列表" / "查名下skill" | scripts/fetch_my_skills.py → 拉取名下skill+对比本地 |
| "优化skill" / "根据反馈改" | feedback-collector.md → 提取+修复 |
| "更新skill" / "发新版本" | publish-quality.md → publish.md → 版本更新+发布 |
| "配置通知" / "飞书通知我" | notification.md → 配置通知渠道 |

> **发布类请求先过 `publish-code-audit.md`，再过 `publish-quality.md`。**
> 顺序不能倒：代码是不是真的、是不是你要的，比包装好不好看优先。
> 简介、标签、README、SKILL.md 是用户和大模型真正接触到的东西——
> **但那层包装再漂亮，里面是模型编出来的东西，发出去就是骗人。**

---

## 架构

```
质量闸门 → 发布 → 用户使用 → 提issue/安装 → 收集反馈 → 提醒作者 → 作者决策 → 修复+测试 → 发新版本
```

## 数据源

| 源 | 检查内容 | API |
|----|----------|-----|
| GitHub Issues | 用户反馈、bug报告 | GitHub API |
| SkillHub | downloads/installs/stars变化 | https://api.skillhub.cn/api/v1/search?q={slug} |
| SkillHub (名下) | 本账号发布的所有skill | https://api.skillhub.cn/api/v1/users/{handle}/skills |

---

## 模块索引

| 模块 | 文件 | 用途 |
|------|------|------|
| **团队名册（角色单一真源）** | **publish-team-roster.md** | **谁在场（J1–J4 / E1–E2）+ 各自工具白名单与产出 + 三权分立 + reskill 供给表。改角色只改这一份** |
| **第三方代码审计** | **publish-code-audit.md** | **源码 vs 需求（覆盖/超纲/幻觉）+ 文档 vs 源码；审计代理定义与硬规则** |
| **发布物质量** | **publish-quality.md** | **双平台形态三分支 + 元数据 + README/SKILL.md 模板 + 双维度打分** |
| **专家团队编排** | **publish-expert-team.md** | **闸门不交专家；双平台两线流程（N0–N7）；约束四层；蜂巢适用边界** |
| **流程强制执行** | **publish-flow-control.md** | **状态机：启动清单、节点准入/准出、产物即证据、防跳步** |
| **大模型闸门** | **publish-llm-gate.md** | **脚本管形式/裁判管语义；流程裁判四问；双裁判架构；裁判不失效的条件** |
| 发布 | publish.md | 推送到 GitHub / SkillHub，版本管理 |
| 反馈 | feedback-collector.md | 检查issues，提取有效反馈，提醒作者 |
| 通知 | notification.md | 多渠道消息通知（微信/飞书/钉钉/Telegram） |
| **发布状态机** | **scripts/publish_flow.py** | **无人值守：持状态 / 管推进 / 记判决账本；两个终态 released / deferred** |
| **本机真实执行器** | **scripts/local_executor.py** | **机器节点真跑脚本；语义节点读「判定收件箱」，收不到就不放行** |
| **客观代理指标** | **scripts/quality_metrics.py** | **给 README / SKILL.md 打客观分，判定者想松口时顶住它** |
| **形态判定** | **scripts/detect_publish_form.sh** | **N0：skill / installer / github-project 三路判定** |
| **本机发布单入口** | **scripts/local_publish.py** | **一条命令反复调：机器节点自动判、语义节点停下出题；退出码 0=终态 / 10=等投递 / 1=错误** |
| **判定派发** | **scripts/verdict_dispatch.py** | **出题（生成判定任务单）/ 收卷（校验判定合法性，只校验不改判定）** |
| 下载量追踪 | scripts/check_downloads.py | SkillHub下载量趋势快照+增量提醒 |
| 名下skill同步 | scripts/fetch_my_skills.py | 同步SkillHub官方API名下的skill列表 |
| 发布前扫描 | scripts/preflight_publish_check.sh | 凭据 + 个人痕迹 + 结构，综合闸门 |
| 可发现性 | scripts/check_discoverability.py | 量每个 topic 的真实搜索池（低于下限=没人搜）+ 名称查重。需联网 |
| **发布物质量闸门** | **scripts/preflight_quality_check.py** | **前 30 行收益陈述按 `kind` 分判据：perf 优化类要量化数字 / feature 功能类要「自动替你做了什么」；未声明只给 WARN** |

---

## 用户需要提供

| 信息 | 说明 | 示例 |
|------|------|------|
| 仓库地址 | 要监控的GitHub仓库 | github.com/totwo2/reskill |
| Token | 平台API访问权限 | GitHub PAT |
| 通知渠道 | 接收通知的方式 | 微信（默认）/飞书webhook/钉钉webhook |

### 配置示例

用户告诉AI：
```
“监控 github.com/totwo2/reskill 的issues”
→ AI记录仓库地址
→ AI用已有token检查issues
→ 用当前会话渠道通知
```

如果用户要换通知渠道：
```
“用飞书通知我”
→ AI问webhook地址
→ 写入notify_config.yaml
```

---

## 快速开始

### 第一步：用户提供配置

```
“监控这个仓库：github.com/xxx/xxx”
“Token是：xxx”
“用微信通知我”
```

AI写入 `settings/reskill_config.yaml`：
```yaml
repo:
  platform: github
  owner: xxx
  repos:
    - name: everytime-novel
      skillhub_id: "87148"
    - name: reskill
      skillhub_id: "87149"
  token: xxx

skillhub:
  api_base: "https://api.skillhub.cn"
  skills:
    - slug: everytime-novel
    - slug: reskill

notification:
  channel: session
  target: "xxx@im.wechat"
  enabled: true

schedule:
  enabled: true
  cron: "0 9 * * *"  # 每天09:00
```

### 第二步：验证配置

```
AI用token调API，确认能访问仓库
→ “配置成功，已开始监控”
```

### 第三步：自动运行

```
按schedule定期检查issues
→ 提取有效反馈
→ 通过notification渠道提醒作者
→ 持续循环
```

---

## 发布完成契约（DONE Gate）

**六个条件全绿 = 发布完成，立即收口，禁止再输出"改进建议 / 后续可优化"。**

0. **第三方审计两跑通过**：N0.5 幻觉表 0 命中 + 覆盖表无 ❌；N4.5 文档每条命令/入口/数字都有源码锚点
1. **`gate check <候选包>` 退出码 0**（闸门内部会调用 `preflight_publish_check.sh`，
   但入口只能是 `gate` —— 直接跑 preflight 交差等于自评，不算数）
2. 质量闸门四道全过（publish-quality.md 第五节打分，任一维度 <3 分不发）
3. gh 与 sh 版本号数字对齐（gh 带 `v`，sh 不带）
4. **监控清单已同步**：本次发布的 skill 必须出现在 `settings/reskill_config.yaml` 的 `skillhub.skills` 里
   （写 `slug` + SkillHub 上的 `display_name` 原文）。
   **已发布的 skill 一律自动纳入监控，不必询问 —— 这是发布动作的一部分，不是可选项。**
   验收：`python3 scripts/fetch_my_skills.py --dry-run` 显示「新发布（本地无）: 0」。

**完成后的输出契约固定三行**：版本号 / 平台链接 / 同步状态。写完闭嘴。

> 改进建议必须有 source（issue 编号、脚本 exit code、用户原话）。
> **没有 source 的建议 = 臆测，不输出。**
