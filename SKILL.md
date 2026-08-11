---
name: reskill
slug: reskill
version: 1.2.0
displayName: Skill发布与反馈优化系统
description: |
  Skill发布、用户反馈收集与持续优化系统。发布skill到Gitee/GitHub/SkillHub，
  自动同步名下已发布skill列表，定期检查用户意见，提取有效反馈，
  提醒作者决策，自动优化skill。支持下载量趋势追踪（有新下载自动提醒）、
  发布前凭据扫描、多渠道消息通知（微信/飞书/钉钉/Telegram）。
  触发词：发布skill、检查反馈、用户意见、优化skill、更新skill、配置通知、下载量、下载趋势、同步skill列表、查名下skill
license: MIT
tags:
  - publish
  - feedback
  - optimization
  - skillhub
  - github
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

---

## GitHub Skill 生命周期管理（已固化）

> 来源：https://agentskills.io/specification.md + gh CLI v2.94.0 实测
> 最后更新：2026-08-11
> 规范版本：v1.0.0（Agent Skills Specification）

### 发布/更新结构要求

#### 仓库要求
| 要求 | 说明 |
|------|------|
| 仓库类型 | 必须 public |
| Topic | 必须包含 `agent-skills` |
| License | 推荐包含（MIT 等） |
| Release | 每个版本必须有对应 tag + release |

#### SKILL.md frontmatter 要求
| 字段 | 必填 | 规则 |
|------|------|------|
| name | ✅ | 1-64字符，仅小写字母数字连字符，首尾/连续连字符不允许，必须与目录名相同 |
| description | ✅ | 1-1024字符，描述用途+触发场景 |
| license | ❌ | 许可证名称或文件引用 |
| compatibility | ❌ | 环境要求（≤500字符） |
| metadata | ❌ | 任意 key-value 映射 |
| allowed-tools | ❌ | 空格分隔的预授权工具（必须是字符串，不是数组） |

#### 仓库结构（Skill 发现约定）
```
# 单 skill 仓库（根级别）
repo-name/
├── SKILL.md          # 必需
├── README.md         # 推荐
├── scripts/          # 可选
├── references/       # 可选
├── assets/           # 可选
├── LICENSE           # 推荐
└── .gitignore        # 推荐

# 多 skill 仓库
repo-name/
├── skills/
│   ├── skill-a/
│   │   └── SKILL.md
│   └── skill-b/
│       └── SKILL.md
└── README.md
```

Skill 发现路径（gh skill install 实测）：
- `skills/*/SKILL.md`
- `skills/{scope}/*/SKILL.md`
- `*/SKILL.md`（根级别）
- `plugins/{scope}/skills/*/SKILL.md`

#### 渐进式披露
| 层级 | 内容 | Token 预算 | 加载时机 |
|------|------|-----------|----------|
| 元数据 | name + description | ~100 tokens | 启动时 |
| 指令 | SKILL.md 正文 | <5000 tokens | 激活时 |
| 资源 | scripts/references/assets | 按需 | 需要时 |

### 发布流程（gh skill publish）

```bash
# 1. 凭据扫描（reskill 强制闸门）
bash scripts/preflight_secret_scan.sh .

# 2. 验证（不发布）
gh skill publish --dry-run

# 3. 自动修复可修复问题（如剥离 install metadata）
gh skill publish --fix
# 审查改动后 commit，再重新 publish

# 4. 发布（指定 tag）
gh skill publish --tag v1.2.0
```

`gh skill publish` 会自动：
- 添加 `agent-skills` topic
- 创建 GitHub release（自动生成 release notes）
- 剥离 install metadata（`metadata.github-*`）
- 验证 frontmatter 合法性

### 更新流程（gh skill update）

```bash
# 更新所有已安装 skill
gh skill update --all

# 更新指定 skill
gh skill update <owner>/<repo>
```

版本解析优先级：
1. 最新 tagged release
2. 默认分支 HEAD

固定版本：
```bash
# 方式1：在 skill 名后加 @version
gh skill install github/awesome-copilot git-commit@v1.2.0

# 方式2：--pin 标志
gh skill install github/awesome-copilot git-commit --pin v1.2.0
```

已安装 skill 的 frontmatter 会注入 source tracking metadata，用于 update 检测变化。

### 与 SkillHub 发布的关键差异
| 维度 | gh skill publish | skillhub publish |
|------|-----------------|------------------|
| 凭据扫描 | 无强制（依赖 GitHub Secret scanning） | **强制**（preflight_secret_scan.sh） |
| 打包方式 | 仓库即目录，不打包 | 打包 zip，`.gitignore` 无效 |
| 发布前处理 | 自动剥离 install metadata | 需手动移走含 token 文件 |
| 索引机制 | GitHub API + topic 搜索 | SkillHub 自有市场 |
| 网络要求 | 需访问 github.com | 国内 skillhub.cn 高速 |

### 发布检查清单（每次发布前）
- [ ] 已跑 `bash scripts/preflight_secret_scan.sh .` 且退出码 0（硬性前置）
- [ ] SKILL.md frontmatter name 1-64 字符（小写字母数字连字符）
- [ ] description 1-1024 字符，含触发关键词
- [ ] name 与目录名相同
- [ ] allowed-tools 是字符串（不是数组）
- [ ] 仓库 public + `agent-skills` topic 已加
- [ ] LICENSE 文件存在
- [ ] 每个版本有对应 tag + release
- [ ] 已跑 `gh skill publish --dry-run` 看到 ✅
- [ ] 已跑 `python3 scripts/gh_skill.py check-spec` 确认规范未变

### 规范变更检测

reskill 提供 `gh_skill.py check-spec` 自动检测规范变化：
- agentskills.io 规范文档最后修改时间
- gh CLI 版本和子命令变化
- 本地固化规范版本
- 已知 skill 仓库最近推送

当规范更新时，手动更新本 SKILL.md 和 publish.md 中的规范章节。
```
