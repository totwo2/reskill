---
name: reskill
slug: reskill
version: 3.0.0
displayName: Skill发布质量闸门与反馈系统
description: |
  发 skill 之前先审代码：第三方审计代理对照需求查覆盖/超纲/幻觉，再过质量闸门——
  形态适配（GitHub 项目 / SkillHub 三分支判定）、简介与标签、README 用户视角、SKILL.md 大模型视角。
  过闸后按判定结果发布到 GitHub + SkillHub，追踪下载量趋势、收集 issue 反馈、多渠道通知作者决策。
  触发词：发布skill、推到github、推到skillhub、审代码、代码真的实现了吗、有没有超纲、
  检查反馈、用户意见、优化skill、下载量、下载趋势、同步skill列表、查名下skill、配置通知
license: MIT
allowed-tools: "Read Write Edit Bash Glob Grep WebFetch WebSearch Skill Agent"
---

# reskill — Skill 发布质量闸门与反馈系统

> 发布物质量不合格，就不许发。发完之后，持续收反馈。

---

## 启动路由

| 用户说 | 动作 |
|--------|------|
| "发布skill" / "推到github" / "推到skillhub" | **publish-code-audit.md 审代码** → publish-quality.md 质量闸门 → publish.md 发布 |
| "审代码" / "这代码真的实现了吗" / "有没有超纲" | **publish-code-audit.md** → 覆盖表 / 超纲表 / 幻觉表 |
| "检查发布物质量" / "这 README 行不行" | publish-quality.md → 双维度打分 |
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
| **第三方代码审计** | **publish-code-audit.md** | **源码 vs 需求（覆盖/超纲/幻觉）+ 文档 vs 源码；审计代理定义与硬规则** |
| **发布物质量** | **publish-quality.md** | **双平台形态三分支 + 元数据 + README/SKILL.md 模板 + 双维度打分** |
| **专家团队编排** | **publish-expert-team.md** | **闸门不交专家；双平台两线流程（N0–N7）；约束四层；蜂巢适用边界** |
| **流程强制执行** | **publish-flow-control.md** | **状态机：启动清单、节点准入/准出、产物即证据、防跳步** |
| **大模型闸门** | **publish-llm-gate.md** | **脚本管形式/裁判管语义；流程裁判四问；双裁判架构；裁判不失效的条件** |
| 发布 | publish.md | 推送到 GitHub / SkillHub，版本管理 |
| 反馈 | feedback-collector.md | 检查issues，提取有效反馈，提醒作者 |
| 通知 | notification.md | 多渠道消息通知（微信/飞书/钉钉/Telegram） |
| 下载量追踪 | scripts/check_downloads.py | SkillHub下载量趋势快照+增量提醒 |
| 名下skill同步 | scripts/fetch_my_skills.py | 同步SkillHub官方API名下的skill列表 |
| 发布前扫描 | scripts/preflight_publish_check.sh | 凭据 + 个人痕迹 + 结构，综合闸门 |

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
1. `scripts/preflight_publish_check.sh` 退出码 0
2. 质量闸门四道全过（publish-quality.md 第五节打分，任一维度 <3 分不发）
3. gh 与 sh 版本号数字对齐（gh 带 `v`，sh 不带）
4. `fetch_my_skills.py` 已同步监控清单

**完成后的输出契约固定三行**：版本号 / 平台链接 / 同步状态。写完闭嘴。

> 改进建议必须有 source（issue 编号、脚本 exit code、用户原话）。
> **没有 source 的建议 = 臆测，不输出。**
