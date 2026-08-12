# notification.md — 消息通知接口

> 用户配置通知渠道，AI通过该渠道推送反馈报告。

---

## 支持的渠道

| 渠道 | 配置方式 | 说明 |
|------|----------|------|
| 微信 | openclaw-weixin | 默认，已配置 |
| 飞书 | feishu webhook | 需要webhook地址 |
| 钉钉 | dingtalk webhook | 需要webhook地址 |
| Telegram | telegram bot | 需要bot token + chat_id |
| Discord | discord webhook | 需要webhook地址 |
| 企业微信 | wecom webhook | 需要webhook地址 |
| 邮件 | smtp | 需要邮箱配置 |

---

## 配置方式

在项目的 `settings/notify_config.yaml` 里配置：

```yaml
# 通知配置
channels:
  - name: 微信
    type: openclaw-weixin
    enabled: true
    events:
      - new_feedback    # 有新反馈
      - fix_complete     # 修复完成
      - new_version      # 新版本发布

  - name: 飞书群
    type: feishu
    webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
    enabled: false
    events:
      - new_feedback

  - name: 钉钉群
    type: dingtalk
    webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
    enabled: false
    events:
      - new_feedback

  - name: Telegram
    type: telegram
    bot_token: "xxx"
    chat_id: "xxx"
    enabled: false
    events:
      - new_feedback
      - new_version
```

---

## 通知事件

| 事件 | 触发时机 | 通知内容 |
|------|----------|----------|
| `new_feedback` | 检查到新issue | "有{N}条新反馈，要看看吗？" |
| `new_download` | 下载量比上次快照增加 | "🎉 你的 skill 又有人下载了！{skill} X→Y (+N)" |
| `fix_complete` | 修复完成 | "已修复{N}个问题，要发布吗？" |
| `new_version` | 新版本发布 | "v{版本}已发布，更新内容：{摘要}" |
| `issue_closed` | issue关闭 | "Issue #{编号}已关闭：{原因}" |

---

## 通知格式

### 新反馈通知

```
📢 新反馈提醒

Skill: {skill名}
平台: Gitee/GitHub
新issue: {N}条

有效反馈:
- Issue #{编号}: {标题} ({类型})

回复"看反馈"查看详情，回复"修"开始修复。
```

### 修复完成通知

```
✅ 修复完成

Skill: {skill名}
修复问题: {N}个
版本: v{版本}

修改内容:
- {修改1}
- {修改2}

回复"发布"推送到Gitee/GitHub。
```

---

## 推送方式

AI根据配置，选择对应渠道推送：

```
读 settings/notify_config.yaml
  ↓
找到 enabled=true 的渠道
  ↓
根据事件类型匹配 channels
  ↓
调用对应渠道的webhook/API推送消息
```

### 飞书webhook

```bash
curl -X POST "{webhook}" \
  -H "Content-Type: application/json" \
  -d '{"msg_type":"text","content":{"text":"{消息内容}"}}'
```

### 钉钉webhook

```bash
curl -X POST "{webhook}" \
  -H "Content-Type: application/json" \
  -d '{"msgtype":"text","text":{"content":"{消息内容}"}}'
```

### Telegram

```bash
curl -X POST "https://api.telegram.org/bot{token}/sendMessage" \
  -d "chat_id={chat_id}&text={消息内容}"
```

---

## 默认行为

如果用户没有配置 `notify_config.yaml`：
- 默认使用当前会话渠道推送（微信/飞书/钉钉，取决于用户在哪聊）
- 不主动推送，只在用户问"有没有反馈"时才检查

---

## 配置示例

用户只需告诉AI：

```
"飞书群通知我"
→ AI问webhook地址
→ AI写入notify_config.yaml
→ 以后有反馈自动推飞书群
```

```
"只用微信通知"
→ AI写入notify_config.yaml（微信enabled=true，其他enabled=false）
```
