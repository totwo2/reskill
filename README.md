# reskill — 发版前先审代码，发版后自动收反馈

> 代码写完、测试过了，剩下的事交给它：审代码 → 过质量闸门 → 写 README 与 SKILL.md →
> 定简介标签 → 判形态 → 发双平台 → 收下载与 issue。

## 它解决什么

写一个 skill 或小工具，真正的麻烦从"写完了"才开始：

- **代码是给谁写的？** 有没有为某个需求写了三行、结果根本没人用的功能？
- **README 写得像开发日志**，陌生人扫 3 秒就走。
- **简介和标签填的是技术词**，搜作用词的人永远找不到你。
- **该发 GitHub 还是 SkillHub**、要不要打成 installer，全靠拍脑袋。

reskill 把这四件事变成一条带闸门的流水线，而且**每一步都有独立的判定者**——
写手不给自己打分。

## 30 秒上手

把它装进你的 AI 助手，说一句话：

```
"帮我把这个 skill 发出去"
```

它会自己走完：形态判定 → 事实表 → 写发布物 → 硬闸门 → 质量裁判 → 装配 → 发布 → 收口。

## 一条命令跑完（本机）

项目里备好 `SKILL.md`、`README.md` 和事实表，然后反复调同一个命令：

```bash
python3 scripts/local_publish.py --project <你的项目>
```

看退出码就知道该干什么：

| 退出码 | 含义 |
|---|---|
| **0** | 到终态了：`released`（已发布）或 `deferred`（已搁置） |
| **10** | 停在需要判断的那一步，**任务单已生成**，退出前会告诉你回卷到哪 |
| **1** | 用法或环境有问题，不会瞎跑 |

判定回卷到 `<项目>/.publish-staging/verdicts/<节点>.json`：

```json
{"score": 4.5, "judge": "谁判的", "reason": "判据（带文件:行号）"}
```

**执行器自己不会写这个文件。** 判定必须由执行器之外的主体投递——这是"给自己判分不算数"
的机制保证。判定不合规（缺署名 / 缺判据）会被**原地退回**，不消耗重试次数：
"写错了"和"做不到"不是一回事。

## 它怎么保证质量

三道锁，缺一把就会漏：

| 锁 | 做法 |
|---|---|
| **判据硬化** | 能机器判的全部下沉到脚本：体积、锚点、元数据、命令能不能真跑起来 |
| **全票通过** | 质量裁判 + 流程裁判 + 审计，**任一不过就打回**（不是多数票） |
| **默认安全** | 连续 3 轮不过 → **自动不发**，报告留着，想看再翻 |

**"自动不发"是设计，不是失败。** 它保证发出去的东西不会让你丢人；
代价是偶尔漏发一些本该发的——发得少一点，发得稳一点。

因为不用你操心，判定就得自己留下凭据。

### 判决账本

每次判定落一行 `ledger.jsonl`：

```
时间 / 节点 / 轮次 / 结论 / 分数 / 分数下限 / 判定者署名 / 判据
```

**为什么必须有分数**：只有 pass/fail 的话，"过了就是过了"，放宽标准和合格长得一模一样。
有了分数，才能发现"同类产物这次 2 分、上次 4 分"——那是标准被悄悄放宽时唯一的信号。

## 目录

```
reskill/
├── SKILL.md                        # 大模型执行手册（入口）
├── publish.md                      # 发布流程（GitHub / SkillHub）
├── publish-quality.md              # 四道质量闸门 + 形态判定 + 简介标签
├── publish-code-audit.md           # 第三方源码审计（覆盖 / 超纲 / 幻觉）
├── publish-expert-team.md          # 角色分工与权限边界
├── publish-flow-control.md         # 状态机与节点表
├── publish-llm-gate.md             # 裁判 LLM，含无人值守模式
├── feedback-collector.md           # issue 检查与反馈提取
├── notification.md                 # 多渠道通知
├── references/                     # 规范原文（GitHub skills spec 等）
├── scripts/
│   ├── local_publish.py            # 单入口：一条命令反复调（推荐起点）
│   ├── publish_flow.py             # 状态机 + 判决账本（无人值守）
│   ├── local_executor.py           # 本机真实执行器（机器判 / 读判定收件箱）
│   ├── verdict_dispatch.py         # 判定派发：出题（任务单）+ 收卷（校验）
│   ├── detect_publish_form.sh      # N0 形态判定
│   ├── quality_metrics.py          # 客观代理指标（给 README / SKILL.md 打分）
│   ├── executor_example.py         # 外部执行器接入样板
│   ├── preflight_quality_check.py  # 质量闸门
│   ├── preflight_publish_check.sh  # 发布前检查
│   ├── preflight_secret_scan.sh    # 凭据扫描
│   ├── gh_skill.py                 # GitHub skill 操作
│   ├── gh_release.py               # Release 与 topics
│   ├── check_downloads.py          # 下载量追踪
│   ├── daily_report.py             # 日报
│   └── fetch_my_skills.py          # 同步名下 skill 清单
└── settings/                       # 配置、快照与发布历史
```

## 每个脚本都能自证

不用读代码，跑一下看最后一行：

```bash
cd scripts
python3 local_publish.py --test       # 15 项：机器节点自动走 / 语义节点停下出题 / 坏判定原地退回
python3 publish_flow.py --test        # 23 项：跳步被拒 / 低分不放行 / 超限不发
python3 local_executor.py --test      # 18 项：机器节点真跑，语义节点收件箱空着就不放行
python3 verdict_dispatch.py --test    # 25 项：任务单必须带证据 / 判定校验区分"没判好"与"判定说不"
python3 quality_metrics.py --test     # 6 项：客观指标能区分好样本与坏样本
./detect_publish_form.sh --test       # 5 项：四条发布路径判定正确
```

看到 `结果：N 通过 / 0 失败` 就算通过。合计 **92 项**。

## 想接自己的执行器

默认执行器只验机制、不产内容。要接真实的生成与判定，用 `--exec`：

```bash
python3 scripts/publish_flow.py --project <项目> run --auto \
    --exec "python3 scripts/executor_example.py"
```

执行器从环境变量拿上下文（`PFLOW_NODE` / `PFLOW_PROJECT` / `PFLOW_STAGING` /
`PFLOW_ATTEMPT` / `PFLOW_NEED` / `PFLOW_MIN_SCORE`），在 stdout 最后一行回抛：

```json
{"verdict": "pass|fail", "score": 0-5, "reason": "可验证的判据", "judge": "谁判的"}
```

退出码非 0、或没给出 JSON → **一律判 fail**（默认安全位）。
样板见 `scripts/executor_example.py`。

## 安全

- **不要提交真实 token**。用 `settings/reskill_config.example.yaml` 作模板。
- 每次发布前跑 `bash scripts/preflight_secret_scan.sh .`。
- SkillHub 登录凭据只留在本地 CLI 状态里。

## 许可

MIT
