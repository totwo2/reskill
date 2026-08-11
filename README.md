# reskill — Skill Publishing & Feedback System

> Publish skills, collect feedback, keep improving.

A complete toolkit for AI agent skill creators: publish to SkillHub/Gitee/GitHub, monitor user issues, track download trends, and get notified — all automated.

[中文说明见下方](#中文说明)

---

## What it does

| Feature | Description |
|---------|-------------|
| **Publish** | Push skills to SkillHub community, Gitee, or GitHub (supports `gh skill publish`) |
| **Feedback** | Auto-check open issues on Gitee/GitHub, classify and extract actionable feedback |
| **Download tracking** | Monitor SkillHub download counts, alert you when someone new installs your skill |
| **Notifications** | Push updates via WeChat / Feishu / DingTalk / Telegram |

## Install

```bash
# From GitHub Agent Skills
gh skill install {owner} reskill

# From SkillHub (CN)
skillhub install reskill --namespace user_c18b02ff
```

## Quick start

Tell your AI assistant:

```
"Publish this skill to GitHub"
"Check if there are new issues"
"Any new downloads lately?"
"Notify me on Feishu when there's feedback"
```

The skill handles the rest — scanning, publishing, monitoring, and notifying.

## Structure

```
reskill/
├── SKILL.md                  # AI execution instructions
├── publish.md                # Publishing workflow (SkillHub/Gitee/GitHub)
├── feedback-collector.md     # Issue checking & feedback extraction
├── notification.md           # Multi-channel notification config
├── scripts/
│   ├── preflight_secret_scan.sh   # Credential scan before publish
│   └── check_downloads.py         # Download trend tracker
└── settings/
    └── reskill_config.example.yaml   # Config template (no real tokens)
```

## Security

- **Never** commit real tokens. Use `settings/reskill_config.example.yaml` as template.
- Run `bash scripts/preflight_secret_scan.sh .` before every publish.
- SkillHub login tokens stay in local CLI state only.

## License

MIT

---

## 中文说明

reskill 是一个 Skill 发布与反馈优化系统：

- **发布**：把 skill 推到 SkillHub 社区源 / Gitee / GitHub
- **反馈**：定期检查 issues，提取有效反馈，提醒作者
- **下载量追踪**：监控 SkillHub 下载量变化，有新下载自动提醒
- **通知**：支持微信/飞书/钉钉/Telegram 多渠道推送

### 触发词

发布skill、检查反馈、用户意见、优化skill、更新skill、配置通知、下载量、下载趋势、发布到skillhub
