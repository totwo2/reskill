---
name: reskill
slug: reskill
version: 2.0.5
displayName: Skill发布与反馈优化系统
description: |
  Skill发布、用户反馈收集与持续优化系统。发布skill到Gitee/GitHub/SkillHub，
  自动同步名下已发布skill列表，定期检查用户意见，提取有效反馈，
  提醒作者决策，自动优化skill。支持下载量趋势追踪（有新下载自动提醒）、
  发布前凭据扫描、多渠道消息通知（当前会话/飞书/钉钉/Telegram/邮件）。
  触发词：发布skill、检查反馈、用户意见、优化skill、更新skill、配置通知、下载量、下载趋势、同步skill列表、查名下skill
license: MIT
allowed-tools: "Read Write Edit Bash Glob Grep WebFetch WebSearch Skill Agent"
---

# reskill — Skill发布与反馈优化系统

> 发布skill，收集意见，持续优化。

---

## 启动路由

| 用户说 | 动作 |
|--------|------|
| "发布skill" / "推到gitee" / "推到github" / "推到skillhub" | publish.md → 发布流程 |
| "检查反馈" / "有没有issue" / "用户意见" | feedback-collector.md → 检查issues+SkillHub数据 |
| "下载量" / "下载趋势" / "有没有新下载" | scripts/check_downloads.py → 对比快照+增量提醒 |
| "同步skill列表" / "查名下skill" / "我在skillhub发了啥" | scripts/fetch_my_skills.py → 拉取名下skill+对比本地 |
| "优化skill" / "根据反馈改" | feedback-collector.md → 提取+修复 |
| "更新skill" / "发新版本" | publish.md → 版本更新+发布 |
| "配置通知" / "飞书通知我" / "钉钉通知我" | notification.md → 配置通知渠道 |

---

## 架构

```
发布 → 用户使用 → 提issue/安装 → 收集反馈 → 提醒作者 → 作者决策 → 修复+测试 → 发布新版本
```

## 数据源

| 源 | 检查内容 | API |
|----|----------|-----|
| Gitee/GitHub Issues | 用户反馈、bug报告 | 平台API |
| SkillHub | downloads/installs/stars变化 | https://api.skillhub.cn/api/v1/search?q={slug} |
| SkillHub (名下) | 本账号发布的所有skill | https://api.skillhub.cn/api/v1/users/{handle}/skills |

---

## 模块索引

| 模块 | 文件 | 用途 |
|------|------|------|
| 发布 | publish.md | 推送到Gitee/GitHub，版本管理 |
| 反馈 | feedback-collector.md | 检查issues，提取有效反馈，提醒作者 |
| 通知 | notification.md | 多渠道消息通知（微信/飞书/钉钉/Telegram） |
| 下载量追踪 | scripts/check_downloads.py | SkillHub下载量趋势快照+增量提醒 |
| 名下skill同步 | scripts/fetch_my_skills.py | 同步SkillHub官方API名下的skill列表 |
| 发布前扫描 | scripts/preflight_secret_scan.sh | 发布前扫描凭据防泄露 |

---

## 用户需要提供

| 信息 | 说明 | 示例 |
|------|------|------|
| 仓库地址 | 要监控的Gitee/GitHub仓库 | gitee.com/gaoooyc/reskill |
| Token | 平台API访问权限 | Gitee私人令牌 / GitHub PAT |
| 通知渠道 | 接收通知的方式 | 微信（默认）/飞书webhook/钉钉webhook |

### 配置示例

用户告诉AI：
```
“监控 gitee.com/gaoooyc/reskill 的issues”
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

用户需要告诉AI：
```
“监控这个仓库：gitee.com/xxx/xxx”
“Token是：xxx”
“用微信通知我”
```

AI写入 `settings/reskill_config.yaml`：
```yaml
repo:
  platform: gitee  # gitee / github
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
