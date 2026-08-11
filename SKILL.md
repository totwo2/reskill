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

## 1. 触发词（命中即启动）

| 用户说法 | 意图 | 入口文件 |
|---------|------|---------|
| "发布skill" / "推到gitee" / "推到github" / "推到skillhub" | 发布新skill | publish.md |
| "检查反馈" / "有没有issue" / "用户意见" / "查下反馈" | 检查issues+SkillHub数据 | feedback-collector.md |
| "下载量" / "下载趋势" / "有没有新下载" | 下载量趋势追踪 | scripts/check_downloads.py |
| "同步skill列表" / "查名下skill" / "我在skillhub发了啥" | 拉取名下skill列表 | scripts/fetch_my_skills.py |
| "优化skill" / "根据反馈改" / "改一下这个skill" | 提取反馈+修复 | feedback-collector.md |
| "更新skill" / "发新版本" / "升级skill" | 版本更新+发布 | publish.md |
| "配置通知" / "飞书通知我" / "钉钉通知我" / "微信通知" | 配置通知渠道 | notification.md |

**注意**：触发词不限于上述 exact match，用户表达类似意图也应启动。

---

## 2. 执行前必读

### 2.1 前置检查清单

启动任何操作前，先确认：
- [ ] 用户已提供必要信息（仓库地址、token、通知渠道等）
- [ ] `settings/reskill_config.yaml` 存在且配置正确（如果已有配置）
- [ ] 网络可达（GitHub/Gitee/SkillHub API）

### 2.2 配置文件位置

```
settings/
├── reskill_config.example.yaml   # 配置模板
├── reskill_config.yaml           # 用户实际配置（可能不存在）
├── notify_config.yaml            # 通知渠道配置
└── release_history/
    └── reskill.yaml              # 发布历史记录
```

如果 `reskill_config.yaml` 不存在，先引导用户配置，或从 `reskill_config.example.yaml` 复制后填写。

---

## 3. 各模块操作手册

### 3.1 发布 skill（publish.md）

**触发**：用户说"发布skill"、"推到github"等

**前置**：
1. 确认 skill 目录结构完整（SKILL.md + scripts/ + README.md + LICENSE）
2. 确认 frontmatter 合法（name/description/tags/allowed-tools/license）
3. 跑凭据扫描：`bash scripts/preflight_secret_scan.sh .`
4. 确认退出码为 0

**流程**：
```bash
# 1. 初始化 git 仓库（如果还没有）
git init
git add -A
git commit -m "init: <skill-name> v<version> for GitHub Agent Skills"

# 2. 创建 GitHub 仓库（如果还没有）
gh repo create <owner>/<repo-name> --public --source=. --remote=origin

# 3. 推送代码
git push -u origin main

# 4. 创建 tag（如果还没有）
git tag v<version>
gh release create v<version> --title "<skill-name> v<version>" --notes-file /dev/stdin

# 5. 验证 skill（注意：gh skill publish 有已知 bug，见 3.1.1）
gh skill publish --dry-run
```

**3.1.1 已知问题：gh skill publish 验证 bug**

`gh skill publish --dry-run` 在 v2.97.0 及更早版本中存在稳定复现的验证错误：
```
error <skill-name> name "<skill-name>" does not match directory name "."
```

无论怎么指定目录参数（`.`、绝对路径、相对路径），该错误始终出现。

**Workaround**：
- 手动完成发布流程（git push + gh release create）
- 或等待 GitHub CLI 修复
- 该 bug 不影响 skill 的实际使用，只影响 `gh skill publish` 的自动验证步骤

**已确认**：本 skill 已通过手动方式成功发布到 GitHub（totwo2/reskill、totwo2/zhi-py-opt、totwo2/da-jia-answer、totwo2/quibbler）。

---

### 3.2 检查反馈（feedback-collector.md）

**触发**：用户说"检查反馈"、"有没有issue"等

**流程**：
1. 读取 `settings/reskill_config.yaml`，获取仓库列表
2. 对每个仓库：
   - 调用 GitHub/Gitee API 获取 issues
   - 过滤有效反馈（非重复、非已解决）
   - 提取关键信息（问题类型、严重程度、用户情绪）
3. 汇总结果，按优先级排序
4. 通过当前会话渠道通知用户

**输出格式**：
```
📊 反馈检查报告（2026-08-11）

reskill（totwo2/reskill）
- 新增 2 个 issue
- 高优先级：1（gh skill publish 验证 bug）
- 中优先级：1（文档建议）
- 低优先级：0

建议处理：
1. [高] 回复 issue #3，说明 gh skill publish bug 的 workaround
2. [中] 更新 README.md，补充使用示例
```

---

### 3.3 下载量追踪（scripts/check_downloads.py）

**触发**：用户说"下载量"、"下载趋势"等

**脚本**：`scripts/check_downloads.py`

**用法**：
```bash
python3 scripts/check_downloads.py --skill <slug> --api-base https://api.skillhub.cn
```

**输出**：
- 当前下载量
- 与上次快照对比（增量）
- 如果有新下载，触发通知

---

### 3.4 名下 skill 同步（scripts/fetch_my_skills.py）

**触发**：用户说"同步skill列表"、"查名下skill"等

**脚本**：`scripts/fetch_my_skills.py`

**用法**：
```bash
python3 scripts/fetch_my_skills.py --handle <github-username> --api-base https://api.skillhub.cn
```

**输出**：
- SkillHub 上该用户名下的所有 skill 列表
- 与本地 skill 目录对比
- 缺失/过期提醒

---

### 3.5 配置通知（notification.md）

**触发**：用户说"配置通知"、"飞书通知我"等

**支持的渠道**：
- 微信（openclaw-weixin）
- 飞书（feishu webhook）
- 钉钉（dingtalk webhook）
- Telegram（bot token + chat id）

**配置方式**：
1. 用户提供渠道类型和接收地址
2. AI 写入 `settings/notify_config.yaml`
3. 发送测试消息验证
4. 启用定时检查

---

## 4. 错误处理

### 4.1 常见错误

| 错误 | 原因 | 处理 |
|------|------|------|
| `gh skill publish` 报 directory name 错误 | v2.97.0 bug | 跳过验证，手动完成发布 |
| API 返回 401 | Token 无效 | 提示用户更新 token |
| API 返回 404 | 仓库不存在 | 检查仓库地址拼写 |
| 网络超时 | GitHub/Gitee 访问慢 | 重试或使用代理 |
| 凭据扫描失败 | 发现敏感信息 | 中止发布，提示用户清理 |

### 4.2 重试策略

- 网络请求：最多重试 3 次，间隔指数退避
- 工具调用失败：换方案（如 web_search 替代 web_fetch）
- 子代理失败：降级为单代理串行，向用户明示

---

## 5. 数据流

```
用户输入
  → 触发词匹配
  → 读取配置（reskill_config.yaml）
  → 执行对应模块
  → 输出结果
  → 通知用户（如果配置了）
```

---

## 6. 与其他 skill 的协作

- **find-skills**：搜索其他 skill 时，find-skills 会调用 reskill 的 `fetch_my_skills.py` 同步名下 skill
- **skillhub-preference**：skill 安装偏好管理，与 reskill 的发布流程互补

---

## 7. 快速命令参考

```bash
# 发布流程
bash scripts/preflight_secret_scan.sh .
git init && git add -A && git commit -m "init"
gh repo create <owner>/<repo> --public --source=. --remote=origin
git push -u origin main
git tag v<version> && gh release create v<version>

# 反馈检查
python3 scripts/fetch_my_skills.py --handle <username>
python3 scripts/check_downloads.py --skill <slug>

# 凭据扫描
bash scripts/preflight_secret_scan.sh .
```

---

*最后更新：2026-08-11*
