# 升级流程指南

> 当 totwo2/reskill 发布新版本时，本机要升级的标准流程。
> 不是脚本，是操作清单。手工执行，保留判断空间。

---

## 何时升级

- totwo2/reskill 在 GitHub 发布了新 tag（v1.4.0+）
- 老高主动要求升级
- 新版本里有 v1.3.0 之后新增的能力（fetch_my_skills.py / gh_release.py / check_downloads.py 等）

**决策原则**：v1.3.0 那次升级没经过本机验证就直接推回了 totwo2，结果 release 流程里有硬编码 bug。**后续升级必须先在本地调试通过，再决定是否同步源。**

---

## 升级流程（4 步）

### 1. 备份

```bash
cd ~/.openclaw/workspace/skills/reskill
VERSION_OLD=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
# 备份整个目录（不含 .git 和 settings/，因为这是实例数据）
BACKUP_DIR="../reskill.bak-$(date +%Y%m%d)-${VERSION_OLD}"
cp -R . "$BACKUP_DIR"
echo "✅ 备份已存到 $BACKUP_DIR"
```

**保留备份至少 7 天**。失败要回滚时用。

---

### 2. 拉源

**优先从 GitHub release 拉 ZIP**（避免 git 历史冲突）：

```bash
# 老高指定新版本号（如 v1.4.0）
NEW_VERSION="v1.4.0"
WORK_DIR=/tmp/reskill-upgrade-$NEW_VERSION
mkdir -p $WORK_DIR
cd $WORK_DIR

# 下载并解压 GitHub source archive
curl -sL "https://github.com/totwo2/reskill/archive/refs/tags/$NEW_VERSION.tar.gz" -o source.tar.gz
tar -xzf source.tar.gz
# 解压后目录名是 reskill-{tag}（去掉 v 前缀）
SRC_DIR="reskill-${NEW_VERSION#v}"
ls $SRC_DIR | head -20  # 确认文件齐全
```

**或者用 git clone**（如果需要看完整历史）：

```bash
git clone --branch $NEW_VERSION --depth 1 https://github.com/totwo2/reskill.git $WORK_DIR/reskill
```

---

### 3. 合并进本机

**保留**（绝不能覆盖）：
- `.git/` — 自己的 git 历史
- `settings/reskill_config.yaml` — 真实 token 配置
- `settings/download_history.yaml` — 监控基线
- `settings/feedback_report.md` — 历史报告
- `settings/my_skills_snapshot.yaml` — 已同步快照
- `settings/release_history/` — release 记录

**覆盖**（从源拉新）：
- `SKILL.md`、`README.md`、`LICENSE`
- `publish.md`、`feedback-collector.md`、`notification.md`
- `references/`、`skills/reskill/SKILL.md`
- `scripts/check_downloads.py`、`scripts/fetch_my_skills.py`（如新版有）
- `scripts/preflight_secret_scan.sh`（如新版有）

**操作步骤**：

```bash
cd ~/.openclaw/workspace/skills/reskill

# 3.1 复制源文件（不含 .git 和 settings/）
rsync -av --exclude='.git' --exclude='settings/' $WORK_DIR/$SRC_DIR/ ./

# 3.2 凭据扫描（发布期闸门）
bash scripts/preflight_secret_scan.sh . 2>&1 | tail -5
# 期望：✅ 扫描通过：未发现凭据

# 3.3 看 diff，识别破坏性变更
git diff --stat HEAD
git diff HEAD -- SKILL.md publish.md scripts/
```

---

### 4. 验证 + 提交

```bash
# 4.1 升级 version 号
# 编辑 SKILL.md 的 version: 字段

# 4.2 跑一次核心脚本（不传 cron input，验证脚本独立能跑）
python3 scripts/check_downloads.py
# 期望：7 个 skill 全部列出，下载数有现存快照

# 4.3 同步名下 skill
python3 scripts/fetch_my_skills.py
# 期望：新增 0 / 缺失 0 / 更新 0（如果不一致要人工确认）

# 4.4 模拟发布（如果打算同步源到 totwo2）
bash scripts/preflight_secret_scan.sh . --all
# 期望：✅ 扫描通过

# 4.5 提交
git add -A
git commit -m "v1.4.0: upgrade from totwo2/reskill $NEW_VERSION"
git tag $NEW_VERSION

# 4.6 推送（按需）
# git push origin master --tags
```

---

## 回滚

如果升级后出问题：

```bash
cd ~/.openclaw/workspace/skills/reskill
# 方案 A：用 git 回到前一个 tag
git reset --hard $VERSION_OLD

# 方案 B：用备份恢复（更彻底）
rm -rf ./*
cp -R $BACKUP_DIR/. .
git status  # 确认 working tree 干净
```

**回滚后**：
- 通知老高：升级失败，已回滚到 vX.Y.Z
- 记录到 settings/feedback_report.md：失败原因
- 不强行打新 tag

---

## 注意事项

1. **不要执行 `skillhub upgrade` 命令**——它会按本机 skill 的 config.json 批量升级所有 skill，但本机 reskill 已经从 Gitee 改成 totwo2 GitHub 源，不在 skillhub CLI 的升级路径里
2. **不要 git pull origin**——本机 origin 是 Gitee gaoooyc/reskill，totwo2 的版本单独 fetch
3. **每次升级前确认老高是否要求同步源**——如果只升级本机，跳过 4.6 推送
4. **settings/ 永远不能覆盖**——用户的真实 token 和监控基线是私有的
5. **凭据扫描要在 3.2 跑一次**——即时不打算发布，验证源是否带脏数据
