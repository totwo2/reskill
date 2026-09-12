#!/usr/bin/env bash
# preflight_publish_check.sh — 发布前综合检查闸门（凭据 + 个人痕迹 + 结构完整性）
# 用法:
#   bash scripts/preflight_publish_check.sh [目录]
# 任何一项命中 → 退出码 1 → 必须中止发布（比凭据扫描更严，是发布期总闸门）。
#
# 覆盖（2026-08-25 教训固化）:
#   1. 凭据扫描（复用 preflight_secret_scan.sh）
#   2. 个人痕迹词库：第三方借鉴/品牌残留/实验语境/旧业务场景词/个人绝对路径
#   3. 结构完整性：SKILL.md frontmatter / README 双语 / MANIFEST 引用存在 /
#      pytest 配置有效 / 无 .venv 等入库
set -u
DIR="."
for a in "$@"; do
  case "$a" in
    --all) ;;   # 兼容占位（综合检查本就全量扫源码与文档）
    *) DIR="$a" ;;
  esac
done
cd "$DIR" 2>/dev/null || { echo "目录不存在: $DIR"; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAIL=0
hit() { echo "  🔴 $1"; FAIL=1; }

echo "===== 发布前综合检查: $(pwd) ====="

# ============================================================
# 1. 凭据扫描（复用既有闸门）
# ============================================================
echo "--- [1/3] 凭据扫描 ---"
bash "$SCRIPT_DIR/preflight_secret_scan.sh" . || FAIL=1

# ============================================================
# 2. 个人痕迹词库扫描（覆盖源码 + 文档 + 配置）
# ============================================================
echo "--- [2/3] 个人痕迹词库 ---"
FILES=$(find . -type f \
  -not -path "*/.git/*" \
  -not -path "*/.venv/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/node_modules/*" \
  -not -name "*.example.*" \
  -not -name "preflight_publish_check.sh" \
  -not -name "preflight_secret_scan.sh" 2>/dev/null)

# 词库：所有模式独立成行（中英文、大小写混合、变体），命中即拦。
# 刻意排除：qclaw/openclaw（可选兼容功能）、启发式（heuristic 通用词）、通知/报告/文档（通用词）
PATTERNS=(
  # --- 第三方借鉴痕迹 ---
  '取百家之长' '设计思路受' '借鉴' '取经' '模仿' '抄袭'
  '万星' '开源项目' 'inspired by' 'based on' 'credit to'
  'Headroom' 'JiangGong' 'Flink Agents' 'CowAgent' 'CMU' 'Caveman'
  'PenguinHarness' 'vLLM' 'LLMRouter' 'Portkey' 'QueQiao'
  'Darwin\.skill' 'SESA' 'VeriSkill' 'ironclaw' 'nanobot'
  'hindsight' 'TencentDB' 'UIUC'
  # --- 平台/品牌残留 ---
  'workbuddy' '\.workbuddy' 'old brand' '品牌残留'
  # --- 实验语境残留 ---
  '窗口一' '窗口二' '实验 v[0-9]' '完成体分层' '\[⑤'
  # --- 旧业务场景词（精确，避免通用词误报）---
  'zhangsan' '财务部' '企业级' '企业内部' '智能办公'
  '写公文' '写请示' '会议纪要' '请假' '审批流程' '用印' '调岗' '花名册' '报销'
  # --- 个人绝对路径 ---
  '[^a-zA-Z0-9]/Users/[A-Za-z]' '[^a-zA-Z0-9]/home/[A-Za-z]' 'C:\\Users\\'
  # --- 边界/剥离叙事残留（干净包不解释"没有什么"）---
  '不含（边界说明）' '不需要：Web 服务' '已剥离' '全不要'
)

for f in $FILES; do
  for p in "${PATTERNS[@]}"; do
    if grep -niE "$p" "$f" >/dev/null 2>&1; then
      hit "$p 命中: $f"
      grep -niE "$p" "$f" 2>/dev/null | head -2
    fi
  done
done

# ============================================================
# 3. 结构完整性
# ============================================================
echo "--- [3/3] 结构完整性 ---"
# 3.1 SKILL.md frontmatter
if [ -f SKILL.md ]; then
  grep -q '^name:' SKILL.md || hit "SKILL.md 缺 name"
  grep -q '^description:' SKILL.md || hit "SKILL.md 缺 description"
  grep -q '^topics:' SKILL.md || echo "  ⚠️ SKILL.md 无 topics（可搜索性弱，建议加）"
else
  hit "缺 SKILL.md（Agent Skill 发布必需）"
fi

# 3.2 README（双语）
if [ -f README.md ]; then
  grep -qE '[A-Za-z]{10,}' README.md || echo "  ⚠️ README.md 纯中文，无英文段（gh 侧建议双语）"
  if ! grep -qE '[一-鿿]' README.md; then
    echo "  ⚠️ README.md 纯英文，建议中英并排"
  fi
else
  hit "缺 README.md"
fi
[ -f README.en.md ] || echo "  ⚠️ 无 README.en.md（英文镜像，可选）"

# 3.3 MANIFEST.in 引用文件存在
if [ -f MANIFEST.in ]; then
  while IFS= read -r line; do
    case "$line" in
      include\ *) fn="${line#include }"; [ -f "$fn" ] || hit "MANIFEST.in 引用的文件不存在: $fn" ;;
      recursive-include\ *) ;;  # 目录级递归，跳过
    esac
  done < MANIFEST.in
fi

# 3.4 pytest 配置指向存在目录
if [ -f pytest.ini ]; then
  tp=$(grep -E '^testpaths' pytest.ini | sed 's/^testpaths[[:space:]]*=[[:space:]]*//' | tr ',' ' ')
  for d in $tp; do
    [ -d "$d" ] || hit "pytest.ini testpaths 指向不存在的目录: $d"
  done
fi

# 3.5 git 仓库时确认无环境/缓存入库
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git ls-files 2>/dev/null | grep -qE '(^|/)\.venv/|__pycache__|\.pyc$'; then
    hit ".venv/__pycache__/pyc 已入库，需清理"
  fi
fi

# ============================================================
echo "----------------------------------------"
if [ "$FAIL" = "1" ]; then
  echo "❌ 综合检查未通过：存在命中项，禁止发布！修复后重跑。"
  exit 1
else
  echo "✅ 综合检查通过：凭据/个人痕迹/结构全部就绪，可以发布。"
  exit 0
fi
