# reskill 交接说明

> 本文档是 reskill 系统的交接指南，帮助接手者快速了解系统架构、配置方式和运行逻辑。

---

## 一、reskill 是什么

reskill 是一个 **Skill 发布、反馈收集与持续优化系统**。核心功能：

1. **发布 Skill** — 推送到 Gitee/GitHub/SkillHub，版本管理
2. **收集反馈** — 定期检查 Issues，提取有效反馈，提醒作者
3. **下载追踪** — 监控 SkillHub 下载量趋势，有新下载自动提醒
4. **通知推送** — 多渠道通知（微信/飞书/钉钉/Telegram）
5. **凭据安全** — 发布前扫描防止 token 泄露

触发词：发布skill、检查反馈、用户意见、优化skill、下载量、同步skill列表

---

## 二、目录结构

```
~/.openclaw/workspace/skills/reskill/
├── .gitignore                      # 排除凭据文件（重要！）
├── SKILL.md                        # 技能入口定义
├── README.md                       # 使用文档
├── publish.md                      # 发布流程（含凭据扫描规则）
├── feedback-collector.md           # 反馈收集流程
├── notification.md                 # 通知渠道配置
├── UPGRADE.md                      # 升级指南
│
├── settings/
│   ├── reskill_config.yaml         # ⚠️ 真实配置（含token，不入库）
│   ├── reskill_config.example.yaml # ✅ 脱敏模板（可入库）
│   ├── notify_config.yaml          # 通知渠道配置
│   ├── download_history.yaml       # 下载量历史快照
│   ├── my_skills_snapshot.yaml     # 名下skill云端快照
│   ├── feedback_report.md          # 反馈报告输出
│   └── release_history/            # 各skill发布历史
│       ├── reskill.yaml
│       ├── quibbler.yaml
│       └── ...
│
├── scripts/
│   ├── preflight_secret_scan.sh    # 🔴 发布前凭据扫描（必跑）
│   ├── check_downloads.py          # 下载量趋势检查
│   ├── fetch_my_skills.py          # 同步名下skill列表
│   ├── gh_skill.py                 # GitHub skill 操作
│   └── gh_release.py               # GitHub release 操作
│
├── references/
│   └── github-skills-spec.md       # GitHub 官方规范参考
│
└── skills/reskill/SKILL.md         # 自引用（skill hub 元数据）
```

---

## 三、配置文件详解

### 3.1 reskill_config.yaml（核心配置）

**位置**：`settings/reskill_config.yaml`

**内容**：
```yaml
repo:                          # Gitee 配置
  platform: gitee
  owner: gaoooyc
  repos:
    - name: reskill
      skillhub_id: '87149'     # SkillHub 上的 ID
  token: "YOUR_GITEE_TOKEN"    # ⚠️ 真实 token，不入库

github:                        # GitHub 配置（可选）
  platform: github
  owner: totwo2
  repos:
    - name: reskill
  token: "YOUR_GITHUB_PAT"     # ⚠️ 真实 token，不入库

skillhub:                      # SkillHub 配置
  api_base: https://api.skillhub.cn
  skills:
    - slug: reskill
      display_name: "Skill发布与反馈优化系统"

notification:                  # 通知配置
  channel: openclaw-weixin     # 默认用微信
  target: "o9cq809iqXaBc_6nnhW_zO43QdbE@im.wechat"
  enabled: true

schedule:                      # 定时任务
  enabled: true
  cron: "0 9 * * *"            # 每天 09:00
```

### 3.2 notify_config.yaml（通知渠道）

**位置**：`settings/notify_config.yaml`

支持渠道：
| 渠道 | 配置字段 | 说明 |
|------|----------|------|
| 微信 | `type: openclaw-weixin` | 默认，已配置 |
| 飞书 | `type: feishu` + webhook | 需要 webhook 地址 |
| 钉钉 | `type: dingtalk` + webhook | 需要 webhook 地址 |
| Telegram | `type: telegram` + bot_token + chat_id | 需要 bot token |
| Discord | `type: discord` + webhook | 需要 webhook 地址 |

---

## 四、核心模块说明

### 4.1 发布流程（publish.md）

**发布前硬性红线**：
```bash
# git push 前（尊重 .gitignore）
bash scripts/preflight_secret_scan.sh .

# skillhub publish 前（打包不看 .gitignore）
bash scripts/preflight_secret_scan.sh . --all
```

- 退出码 0 = 通过，可以发布
- 退出码 1 = 命中凭据，立即中止

**SkillHub 发布特别注意**：
- skillhub 打包不遵守 `.gitignore`
- 发布前必须临时移走：
  - `settings/reskill_config.yaml`
  - `settings/download_history.yaml`
  - `settings/feedback_report.md`
  - `.gitignore` 本身（skillhub 不接受该文件类型）
- 发布后再移回

### 4.2 反馈收集（feedback-collector.md）

**流程**：
```
检查 Issues → 分类 → 提取有效反馈 → 提醒作者 → 作者决策 → 修复+测试 → 发布新版本
```

**反馈分类标准**：
| 类型 | 特征 | 优先级 |
|------|------|--------|
| Bug报告 | "XX不能用"、"报错" | P0 |
| 功能建议 | "希望支持"、"能不能加" | P1/P2 |
| 使用困惑 | "怎么用"、"看不懂" | P1（改文档） |
| 无效反馈 | 无具体信息、广告 | 忽略 |

**有效反馈标准**：
1. 有具体场景
2. 有复现步骤
3. 有期望结果
4. 有实际结果

### 4.3 下载量追踪（scripts/check_downloads.py）

**机制**：
```
拉取 SkillHub 最新 downloads
  ↓
与 download_history.yaml 上一次快照对比
  ↓
有正增量 → 生成提醒文案 → 追加新快照
```

**运行**：
```bash
python3 scripts/check_downloads.py
```

- 首次运行：建立基线快照，不提醒
- 后续运行：有新下载则输出 `GAINS_JSON=[...]` 供推送

### 4.4 名下 Skill 同步（scripts/fetch_my_skills.py）

**功能**：
- 从 SkillHub API 拉取本账号名下全部 skill
- 与 `reskill_config.yaml` 对比
- 云端新增 → 自动追加到配置
- 云端缺失 → 告警（可能下架）
- display_name 不一致 → 同步成云端名称

---

## 五、凭据安全机制

### 5.1 三道防线

1. **`.gitignore` 排除** — 真实 token 文件不入库
2. **`*.example.*` 脱敏** — 入库的是模板，token 填占位符
3. **发布前扫描** — `preflight_secret_scan.sh` 检测泄露

### 5.2 已知 token 位置

| 文件 | Token 类型 | 用途 |
|------|-----------|------|
| `settings/reskill_config.yaml` | Gitee + GitHub PAT | API 访问 |
| `~/.skillhub/credentials.json` | SkillHub skh_ 开头 | SkillHub API |
| `settings/notify_config.yaml` | 微信/飞书/钉钉 token | 通知推送 |

### 5.3 历史事故（2026-06-12）

- **问题**：仓库从建立起无 `.gitignore`，Gitee token 明文推入公开仓库，泄露约一个月
- **修复**：补全 `.gitignore` + 脱敏模板 + 凭据扫描脚本
- **教训**：凭据一旦入公开库 = 已泄露，必须重置

---

## 六、快速操作指南

### 6.1 发布新 Skill

```bash
# 1. 确认目录完整（SKILL.md + 所有模块文件）
# 2. 发布前扫描
bash scripts/preflight_secret_scan.sh .

# 3. git push
git add -A
git commit -m "v1.1: {更新内容}"
git push

# 4. SkillHub 发布（先移走凭据文件）
mv settings/reskill_config.yaml /tmp/
mv .gitignore /tmp/
skillhub publish .
mv /tmp/reskill_config.yaml settings/
mv /tmp/.gitignore .
```

### 6.2 检查反馈

```bash
# 手动运行（或等每天 09:00 自动跑）
python3 scripts/check_downloads.py
# 然后检查 issues
```

### 6.3 同步名下 Skill

```bash
python3 scripts/fetch_my_skills.py
```

### 6.4 配置通知渠道

编辑 `settings/notify_config.yaml`，或告诉 AI：
```
"用飞书通知我"
→ AI 问 webhook 地址
→ AI 写入 notify_config.yaml
```

---

## 七、cron 任务

当前配置（在 `reskill_config.yaml` 的 `schedule` 段）：
```yaml
schedule:
  enabled: true
  cron: "0 9 * * *"    # 每天 09:00
```

如需修改，告知 AI：
```
"每天检查一次反馈"  → cron: "0 9 * * *"
"每周一检查"        → cron: "0 9 * * 1"
"停止检查"          → enabled: false
```

---

## 八、常见问题

### Q: token 泄露了怎么办？
A: 立即去 Gitee/GitHub/SkillHub 重置 token，然后更新 `settings/reskill_config.yaml`

### Q: skillhub publish 报错？
A: 检查是否移走了含 token 的文件和 `.gitignore`

### Q: 下载量不更新？
A: 运行 `python3 scripts/fetch_my_skills.py` 同步清单，再跑 `check_downloads.py`

### Q: 想换通知渠道？
A: 编辑 `settings/notify_config.yaml`，或告诉 AI 切换

---

## 九、相关文档

| 文档 | 路径 | 用途 |
|------|------|------|
| SKILL.md | `./SKILL.md` | 技能入口定义 |
| publish.md | `./publish.md` | 发布流程 + 凭据扫描规则 |
| feedback-collector.md | `./feedback-collector.md` | 反馈收集与优化流程 |
| notification.md | `./notification.md` | 通知渠道配置 |
| UPGRADE.md | `./UPGRADE.md` | 版本升级指南 |

---

## 十、联系与维护

- **仓库**：`gitee.com/gaoooyc/reskill`
- **SkillHub**：`https://skillhub.cn/skills/reskill`
- **版本号**：1.4.0
- **最后更新**：2026-08-17

---

*本文档由 AI 自动生成，基于 reskill 源码和配置整理。如有疑问，请查阅原始文档。*
