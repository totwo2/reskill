# feedback-collector.md — 反馈收集与优化

> Main读这个文件。检查用户issues，提取有效反馈，优化skill。

---

## 反馈收集流程

```
检查issues
  ↓
分类：有效反馈 / 无效反馈 / bug报告 / 功能建议
  ↓
提取有效反馈
  ↓
提醒作者
  ↓
作者决策（修/不修/讨论）
  ↓
不管结果如何 → 继续检查 → 持续循环
```

**核心：反馈收集是持续任务，不是一次性任务。**
不管作者修不修，系统一直在跑，一直在收集和整理反馈。

---

## 检查Issues

### Gitee

```bash
curl -s "https://gitee.com/api/v5/repos/{owner}/{repo}/issues?access_token={token}&state=open&sort=created&direction=desc&limit=20"
```

### GitHub

```bash
gh issue list --repo {owner}/{repo} --state open --limit 20
```

### SkillHub

```bash
curl -s "https://api.skillhub.cn/api/v1/search?q={slug}"
```

返回字段：downloads, installs, stars, score。跟踪变化即可判断增长趋势。

---

## 下载量趋势追踪（v1.1.0）

> 让作者看到「又有人下载了」的正反馈。

### 机制

```
scripts/check_downloads.py
  ↓
拉取 skillhub 最新 downloads
  ↓
与 settings/download_history.yaml 上一次快照对比
  ↓
有正增量 → 生成提醒文案（🎉 你的 skill 又有人下载了！ X → Y (+N)）
  ↓
追加新快照到 download_history.yaml
```

### 运行

```bash
python3 scripts/check_downloads.py
```

- 首次运行：建立基线快照，不提醒。
- 后续运行：只要任一 skill 下载量增加，就输出 `new_download` 提醒文案。
- 输出末尾带 `GAINS_JSON=[...]`，供外层解析后通过 notification 渠道推送。
- 建议挂到每日 09:00 cron，与 issue 检查一起跑。

---

## 反馈分类

| 类型 | 特征 | 处理方式 |
|------|------|----------|
| **Bug报告** | "XX不能用"、"报错"、"失败" | 立即修复 |
| **功能建议** | "希望支持"、"能不能加" | 评估后排优先级 |
| **使用困惑** | "怎么用"、"看不懂" | 改文档 |
| **无效反馈** | 无具体信息、广告、spam | 忽略 |

---

## 提取有效反馈

### 有效反馈的标准

1. **有具体场景** — "我在写XX时遇到了XX问题"
2. **有复现步骤** — "先XX，再XX，然后XX"
3. **有期望结果** — "我希望它能XX"
4. **有实际结果** — "但实际是XX"

### 无效反馈的特征

1. "不好用" — 没说哪里不好用
2. "能不能加XX功能" — 没说为什么需要
3. 广告、spam

### 提取模板

```markdown
## Issue #{编号}

**标题：** {标题}
**类型：** Bug/功能建议/使用困惑
**有效度：** 高/中/低

**用户描述：**
{原文摘要}

**核心问题：**
{一句话概括}

**建议处理：**
{怎么改}
```

---

## 自动优化流程

### 1. 收集反馈

```
检查issues → 生成反馈报告
```

### 2. 提醒作者

```
通知用户：“有{N}条新反馈，要看看吗？”
```

### 3. 作者决策

```
作者看反馈报告
  ↓
“修” → 进入修复流程
“不修” → 回复issue“暂不修复+原因” → 关闭issue
“先看看” → 展示详细内容 → 等决策
“讨论” → 在issue里回复/追问 → 持续跟踪
```

### 4. 修复+测试

```
作者说修 → 修改skill文件 → 本地测试 → 作者确认
  ↓
确认通过 → 发布新版本 → 回复issue“已修复，v{版本}” → 关闭issue
确认不通过 → 继续改 → 重新测试
```

### 5. 持续跟踪

```
issue状态：
  open → 待处理/讨论中
  closed → 已修复/明确不修

每次检查issues时：
  新issue → 提醒作者
  已open的issue → 检查是否有新评论
  修复中的issue → 检查测试进度
```

### 6. 关闭issue

**只有两种情况关闭：**
1. 已修复，作者确认，发布新版本
2. 明确不修，回复原因

**讨论中的issue不关闭。**

---

## 反馈报告格式

输出到 `scripts/feedback_report.md`：

```markdown
# 反馈报告 — {日期}

## 概览
- 总issues: {N}
- 有效反馈: {N}
- Bug: {N}
- 功能建议: {N}
- 使用困惑: {N}

## 有效反馈

### Issue #{编号}: {标题}
- **类型：** Bug/功能建议/使用困惑
- **描述：** {摘要}
- **处理：** {怎么改}
- **优先级：** P0/P1/P2

## 已处理
- Issue #{编号}: {处理结果}

## 待处理
- Issue #{编号}: {为什么还没处理}
```

---

## 定时检查

用户可自行配置检查频率，也可以随时停止。

### 配置方式

用户告诉AI：
```
“每天检查一次反馈”
→ AI创建cron任务：每天09:00检查issues

“每周一检查”
→ AI创建cron任务：每周一09:00检查issues

“每3天检查一次”
→ AI创建cron任务：每3天检查issues
```

### 停止方式

用户告诉AI：
```
“停止检查反馈”
→ AI删除cron任务

“暂停一周”
→ AI暂停cron任务，一周后自动恢复
```

### Cron配置

```yaml
# settings/cron_config.yaml
feedback_check:
  enabled: true
  schedule: "0 9 * * *"  # 每天09:00
  channel: "openclaw-weixin"  # 通知渠道
  last_check: "2026-06-12"
```

### 检查频率建议

| 使用场景 | 建议频率 |
|----------|----------|
| skill刚发布 | 每天检查 |
| 稳定期 | 每周检查 |
| 无活跃用户 | 每月检查 |
| 用户提了issue | 立即检查 |

---

## 注意事项

- 不是所有issue都要改，要判断价值
- 优先修bug，其次改文档，最后加功能
- 改完后要验证，不能引入新问题
- 保持向后兼容，不能破坏已有用户的工作流
