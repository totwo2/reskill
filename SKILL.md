---
name: reskill
slug: reskill
version: 1.2.1
displayName: Skill发布与反馈优化系统
description: |
  Skill publishing, user feedback collection, and continuous optimization system. Publish skills to SkillHub/Gitee/GitHub,
  periodically check user issues, extract actionable feedback, notify the author, and auto-optimize skills.
  Includes download trend tracking (auto-alert on new downloads) and multi-channel notifications (WeChat/Feishu/DingTalk/Telegram).
  Triggers: publish skill, check feedback, user issues, optimize skill, update skill, configure notification, download trends, publish to skillhub.
  Skill发布与反馈优化系统：发布skill到SkillHub/Gitee/GitHub，定期检查用户意见，提取有效反馈，提醒作者决策，自动优化skill。支持下载量趋势追踪与多渠道消息通知。
---

# reskill — Skill发布与反馈优化系统

> 发布skill，收集意见，持续优化。

---

## 启动路由

| 用户说 | 动作 |
|--------|------|
| "发布skill" / "推到skillhub" / "发布到skillhub" | publish.md → SkillHub社区源发布 |
| "发布skill" / "推到gitee" / "推到github" | publish.md → Gitee/GitHub发布流程 |
| "检查反馈" / "有没有issue" / "用户意见" | feedback-collector.md → 检查issues+SkillHub数据 |
| "下载量" / "下载趋势" / "有没有新下载" | scripts/check_downloads.py → 对比快照+增量提醒 |
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

---

## 模块索引

| 模块 | 文件 | 用途 |
|------|------|------|
| 发布 | publish.md | 推送到SkillHub社区源/Gitee/GitHub，版本管理 |
| 反馈 | feedback-collector.md | 检查issues，提取有效反馈，提醒作者 |
| 通知 | notification.md | 多渠道消息通知（微信/飞书/钉钉/Telegram） |

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

github:
  platform: github
  owner: totwo2
  repos:
    - name: reskill
    - name: zhi-py-opt
    - name: quibbler
    - name: da-jia-answer
  token: xxx  # GitHub PAT (scopes: repo)

skillhub:
  api_base: "https://api.skillhub.cn"
  skills:
    - slug: everytime-novel
    - slug: reskill

notification:
  channel: openclaw-weixin
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
