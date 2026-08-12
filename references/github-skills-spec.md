# GitHub Agent Skills 发布规范

> 来源：https://agentskills.io/specification.md
> 最后检查：2026-08-11
> 规范版本：v1.0.0（Agents Skills Specification）

---

## 一、仓库要求

### 1.1 基本信息
| 项目 | 要求 |
|------|------|
| 仓库类型 | Public（公开） |
| Topic | 必须包含 `agent-skills` |
| License | 推荐包含（MIT 等开源协议） |
| Release | 每个发布版本需有对应 release |

### 1.2 仓库结构
```
repo-name/
├── SKILL.md          # 必需：skill 的元数据+指令
├── README.md         # 推荐：人类可读的文档
├── scripts/          # 可选：可执行脚本
├── references/       # 可选：参考文档
├── assets/           # 可选：静态资源
├── LICENSE           # 推荐：许可证文件
├── .gitignore        # 推荐：排除敏感文件
└── .github/          # 可选：CI/CD 配置
```

### 1.3 多 Skill 仓库
如果仓库包含多个 skill：
```
repo-name/
├── skills/
│   ├── skill-a/
│   │   └── SKILL.md
│   └── skill-b/
│       └── SKILL.md
└── README.md
```

---

## 二、SKILL.md 格式要求

### 2.1 Frontmatter 必填字段

| 字段 | 必填 | 约束 |
|------|------|------|
| `name` | ✅ | 1-64字符，仅小写字母数字连字符，不能首尾连字符，不能连续连字符 |
| `description` | ✅ | 1-1024字符，描述用途和触发场景 |
| `license` | ❌ | 许可证名称或文件引用 |
| `compatibility` | ❌ | 环境要求（≤500字符） |
| `metadata` | ❌ | 任意 key-value 映射 |
| `allowed-tools` | ❌ | 空格分隔的预授权工具（实验性） |

### 2.2 name 字段规则
```yaml
# ✅ 合法
name: reskill
name: pdf-processing
name: data-analysis

# ❌ 非法
name: PDF-Processing    # 大写不允许
name: -pdf              # 不能以连字符开头
name: pdf--processing   # 不能连续连字符
name: 智能py脚本        # 中文不允许（只允许 a-z, 0-9, -）
```

### 2.3 description 字段规则
```yaml
# ✅ 好的示例
description: |
  Skill发布、用户反馈收集与持续优化系统。发布skill到Gitee/GitHub/SkillHub，
  自动同步名下已发布skill列表，定期检查用户意见，提取有效反馈，
  提醒作者决策，自动优化skill。
  触发词：发布skill、检查反馈、用户意见、优化skill、更新skill、配置通知、下载量、下载趋势、同步skill列表、查名下skill

# ❌ 差的示例
description: 发布skill的工具。  # 太短，缺少触发词
```

### 2.4 正文内容
- Markdown 格式
- 无格式限制
- 推荐包含：步骤说明、输入输出示例、边缘情况处理
- 建议控制在 500 行以内（<5000 tokens）

---

## 三、发布流程

### 3.1 标准发布步骤
1. **凭据扫描**（强制）：确保无敏感 token/密钥
2. **规范验证**：检查 SKILL.md frontmatter 合法性
3. **添加 Topic**：`agent-skills`
4. **创建 Release**：语义化版本 tag（如 v1.2.0）
5. **发布说明**：包含变更日志

### 3.2 gh skill publish 命令
```bash
# 预览验证（不发布）
gh skill publish --dry-run

# 验证 + 发布
gh skill publish --tag v1.2.0

# 自动修复可修复的问题
gh skill publish --fix
```

### 3.3 手动发布流程
```bash
# 1. 验证 SKILL.md
skills-ref validate ./my-skill

# 2. 添加 topic（GitHub API）
gh repo edit totwo2/reskill --add-topic agent-skills

# 3. 创建 release
gh release create v1.2.0 --title "reskill v1.2.0" --notes "发布说明"

# 4. 验证 discoverability
gh skill search reskill
```

---

## 四、渐进式披露原则

### 4.1 三层加载模型
| 层级 | 内容 | Token 预算 | 加载时机 |
|------|------|-----------|----------|
| 元数据 | name + description | ~100 tokens | 启动时 |
| 指令 | SKILL.md 正文 | <5000 tokens | 激活时 |
| 资源 | scripts/references/assets | 按需 | 需要时 |

### 4.2 最佳实践
- **SKILL.md 控制在 500 行以内**
- 详细参考文档放入 `references/` 目录
- 脚本放入 `scripts/` 目录
- 使用相对路径引用（一层深）

---

## 五、安全要求

### 5.1 禁止提交的内容
- Personal Access Tokens (PAT)
- API Keys
- OAuth Secrets
- Private Keys
- 任何用户凭据

### 5.2 推荐做法
- 使用环境变量替代硬编码
- 创建 `*.example.*` 脱敏版本
- `.gitignore` 排除敏感文件
- 发布前扫描凭据

---

## 六、变更检测机制

### 6.1 规范来源
- 官方规范：https://agentskills.io/specification.md
- CLI 文档：`gh skill --help`、`gh skill publish --help`
- 参考仓库：https://github.com/anthropics/skills

### 6.2 检测频率
- 每次发布前自动检测
- 或手动运行：`gh_skill.py check-spec`

### 6.3 检测内容
1. 规范文档是否更新（检查 last-modified 时间）
2. CLI 命令是否有变化（`gh skill --help`）
3. 本地固化的规范是否需要更新

---

## 七、本地固化规范

### 7.1 已固化要求
- SKILL.md name 字段：小写字母数字连字符，≤64字符
- description 字段：中英文结合，含触发词，≤1024字符
- 仓库必须包含 `agent-skills` topic
- 每个版本必须有对应 release
- 发布前强制凭据扫描

### 7.2 本仓库验证清单
- [ ] name 字段符合规范（小写、无特殊字符）
- [ ] description 字段包含触发词
- [ ] SKILL.md ≤500行
- [ ] 无敏感凭据
- [ ] `agent-skills` topic 已添加
- [ ] release tag 已创建
- [ ] README.md 包含英文介绍

---

## 八、更新历史

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-08-11 | v1.0.0 | 首次固化规范 |
