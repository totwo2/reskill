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
#   4. 语义关实际状态：本次走了多少验证（状态机 / 需求蒸馏 / 事实表 / verdicts / ledger）
#      —— 防「gate 的 PASS 被读成全流程都过了」（2026-09-23 教训）
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
echo "--- [1/4] 凭据扫描 ---"
bash "$SCRIPT_DIR/preflight_secret_scan.sh" . || FAIL=1

# ============================================================
# 2. 个人痕迹词库扫描（覆盖源码 + 文档 + 配置）
# ============================================================
echo "--- [2/4] 个人痕迹词库 ---"
ALLOW_FILE="$SCRIPT_DIR/preflight_allow.txt"

if git rev-parse --git-dir >/dev/null 2>&1; then
  # git 仓库：只取「已跟踪 + 未跟踪但未被忽略」的文件（与 secret_scan 同口径）
  FILES=$( { git ls-files; git ls-files --others --exclude-standard; } 2>/dev/null \
    | grep -vE '\.example\.' \
    | grep -vE '(^|/)(preflight_publish_check|preflight_secret_scan)\.sh$' \
    | grep -vE '(^|/)preflight_allow\.txt$' \
    | sort -u )
else
  FILES=$(find . -type f \
    -not -path "*/.git/*" \
    -not -path "*/.venv/*" \
    -not -path "*/__pycache__/*" \
    -not -path "*/node_modules/*" \
    -not -name "*.example.*" \
    -not -name "preflight_publish_check.sh" \
    -not -name "preflight_secret_scan.sh" \
    -not -name "preflight_allow.txt" 2>/dev/null)
fi

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

# 性能：40+ 个词条逐条 grep，子进程启动开销会拖到分钟级。
# 做法 —— 先合并成一次 grep 判空（零命中直接跳过，这是绝大多数文件），
# 只有确有命中的文件才走逐条精确匹配。判定语义不变，只是省掉无用调用。
PATFILE="$(mktemp)"
trap 'rm -f "$PATFILE"' EXIT
printf '%s\n' "${PATTERNS[@]}" > "$PATFILE"

scanned=0; skipped=0; waived=0

# 豁免清单一次性载入内存（原先每判定一次就重读一遍文件，纯开销）
# 豁免判定：preflight_allow.txt 每行 <文件glob>|<词条原文>|<理由>
ALLOW_G=(); ALLOW_P=()
if [ -f "$ALLOW_FILE" ]; then
  while IFS='|' read -r g p r; do
    case "${g:-}" in ''|\#*) continue ;; esac
    ALLOW_G+=("$g"); ALLOW_P+=("${p:-}")
  done < "$ALLOW_FILE"
fi

allowed() {  # $1=文件 $2=词条 → 0=已登记豁免
  local base i; base="$(basename "$1")"
  for ((i=0; i<${#ALLOW_G[@]}; i++)); do
    # shellcheck disable=SC2254  —— glob 需展开，不能加引号
    case "$base" in ${ALLOW_G[$i]}) ;; *) continue ;; esac
    [ "${ALLOW_P[$i]}" = "$2" ] && return 0
  done
  return 1
}

# 性能（2026-09-17 优化；纯实现改动，判定语义与输出逐字不变）：
#   原慢速路径对「每个命中文件 × 每个词条」各起一次 grep 子进程。实测 24 个文件时
#   约 600 次调用 ≈ 110s，超过 gate 的 60s 看门狗 → 恒被判超时 = 永久 REJECT。
#   改为「文件读一次 + bash 内建 =~ 匹配」，零子进程。语义对齐 `grep -niE`：
#     · ERE 语法相同 —— 直接复用同一个 PATTERNS 数组，不做任何改写
#     · 大小写不敏感由 nocasematch 提供，且只在匹配期间开启：
#       allowed() 里的 case 是大小写敏感 glob，若受影响会改变豁免口径。
#   输出仍按 PATTERNS 原顺序；每个词条取前 2 行命中（与原先的 head -2 同）。
_nocase_restore="$(shopt -p nocasematch 2>/dev/null || echo 'shopt -u nocasematch')"

for f in $FILES; do
  scanned=$((scanned+1))
  # 快速路径：合并 pattern 一次判空（grep -f 即多模式 OR）。
  # 零命中 → 既没有要报的，也没有要过豁免判定的，直接跳过。
  if ! grep -qiEf "$PATFILE" "$f" 2>/dev/null; then
    skipped=$((skipped+1)); continue
  fi
  # 慢速路径：一次读入全部行（含无末尾换行的最后一行），再逐词条做内建匹配。
  LINES=(); nlines=0
  while IFS= read -r _line || [ -n "$_line" ]; do
    nlines=$((nlines+1)); LINES[$nlines]="$_line"
  done < "$f"

  for p in "${PATTERNS[@]}"; do
    out=""; nm=0
    shopt -s nocasematch
    for ((i=1; i<=nlines; i++)); do
      if [[ ${LINES[$i]} =~ $p ]]; then
        if [ -z "$out" ]; then out="${i}:${LINES[$i]}"
        else out="${out}"$'\n'"${i}:${LINES[$i]}"; fi
        nm=$((nm+1))
        [ "$nm" -ge 2 ] && break
      fi
    done
    eval "$_nocase_restore"
    [ -n "$out" ] || continue
    if allowed "$f" "$p"; then
      waived=$((waived+1))
      echo "  ⚪ 已豁免: ${p} @ ${f}（见 preflight_allow.txt）"
      continue
    fi
    hit "$p 命中: $f"
    printf '%s\n' "$out" | head -2
  done
done
echo "  （扫描 $scanned 个文件；快速路径跳过 $skipped 个；豁免 $waived 条）"

# ============================================================
# 3. 结构完整性
# ============================================================
echo "--- [3/4] 结构完整性 ---"
# 3.1 SKILL.md frontmatter
# 发现约定（2026-09-16 扩容，老高批）：
#   Agent Skill 产物要求「至少一份可被发现的 SKILL.md」。顶层 `SKILL.md` 是
#   SkillHub installer 形态与根 SKILL.md 仓库（如 reskill）的写法；GitHub 侧标准
#   布局是 `skills/<name>/SKILL.md`（gh skill publish 以仓库根为目标、校验所有
#   可发现的 skill）。
#   原实现只认顶层 `[ -f SKILL.md ]`，会误拒所有用标准布局的 skill 仓库 ——
#   quibbler / da-jia-answer / zhi-py-opt 的 tag 提交正是
#   "move SKILL.md to skills/<name>/ for gh skill publish compatibility"。
#   注 1：检查面比原来**更严** —— 原来是查 1 个文件，现在逐份校验。
#   注 2：publish.md 记的其余发现形式（skills/{scope}/*/、plugins/{scope}/skills/*/）
#         暂不纳入（宁可漏放不可误放），遇到再加。
#   2026-09-17 二次修正（实测 gh skill install 的发现约定后）：
#     官方六条约定 = skills/*/SKILL.md、skills/{scope}/*/SKILL.md、{prefix}/skills/*/SKILL.md、
#     {prefix}/skills/{scope}/*/SKILL.md、*/SKILL.md、plugins/*/skills/*/SKILL.md。
#     **顶层 SKILL.md 不在其中** —— 实测 `gh skill preview totwo2/reskill` 报 "no skills found"。
#   本次把判据分成两半，各归其主：
#     · 本闸门只判「**有入口时入口是否合格**」→ 逐份校验 name / description / topics
#     · 「**要不要有入口**」= 形态问题 → 归「分发形态判定官」，本闸门不判
#   故：顶层 SKILL.md 与「完全无入口」一律**警告**而非 FAIL
#       （前者不被发现，后者对普通项目/ B 类 installer 是正常的）。
check_skill_md() {
  local sf="$1"
  echo "  · 校验 $sf"
  grep -q '^name:' "$sf" || hit "$sf 缺 name"
  grep -q '^description:' "$sf" || hit "$sf 缺 description"
  grep -q '^topics:' "$sf" || echo "  ⚠️ $sf 无 topics（可搜索性弱，建议加）"
}

found_skill=0
for sf in skills/*/SKILL.md; do
  [ -f "$sf" ] || continue
  check_skill_md "$sf"
  found_skill=1
done

if [ -f SKILL.md ]; then
  check_skill_md "SKILL.md"
  echo "  ⚠️ 顶层 SKILL.md —— 不在 gh skill install 的发现约定内（应放 skills/<name>/），"
  echo "     故本仓库装不下来。若是 skill 包请移动；若是普通项目，本行可忽略。"
fi

if [ "$found_skill" = "0" ]; then
  echo "  ⚠️ 未发现 skill 入口（skills/<name>/SKILL.md）"
  echo "     · 按 skill 发布 → 缺入口，装不上（缺陷）"
  echo "     · 普通项目 / B 类 installer → 无需入口，本行可忽略"
  echo "     形态由「分发形态判定官」判，不由本闸门判。"
fi

# 3.2 README（GitHub 侧必须中英双语：分文件 + 顶部互链）
# 判据：publish-quality.md §二「语言策略」——老高 2026-09-23 定，硬要求不是加分项。
# 文件名惯例是 README_EN.md（下划线 + 大写 EN，no-bb / quibbler 基准）。
# 2026-09-23 修：原先只查 README.en.md（点 + 小写），与惯例不符 →
#               连 no-bb / quibbler 都被误报「无英文镜像」。现在兼容多种变体。
if [ -f README.md ]; then
  EN=""
  for cand in README_EN.md README.en.md README_en.md README-EN.md; do
    [ -f "$cand" ] && EN="$cand" && break
  done
  if [ -z "$EN" ]; then
    hit "缺英文镜像 README_EN.md —— GitHub 侧必须中英双语（分文件，主文档保持单语）"
  else
    grep -qE 'README[._-][Ee][Nn]' README.md \
      || echo "  ⚠️ README.md 顶部缺指向英文镜像的互链（照 no-bb：[English]($EN) | 简体中文）"
    grep -qE 'README\.md' "$EN" \
      || echo "  ⚠️ $EN 顶部缺指回中文主文档的互链（照 no-bb：English | [简体中文](README.md)）"
    grep -qE '([A-Za-z]{2,}[[:space:]]+){3,}[A-Za-z]{2,}' "$EN" \
      || echo "  ⚠️ $EN 里没有成句英文 —— 英文镜像疑似空壳"
    grep -qE '[一-鿿]' README.md \
      || echo "  ⚠️ README.md 里没有中文 —— 主文档应为中文单语"
  fi
else
  hit "缺 README.md"
fi

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
# 4. 语义关实际状态：本次到底走了多少验证（gate 不判质量，只报事实）
# ============================================================
# 为什么必须有这一段（2026-09-23 everytime-novel 实跑教训）：
#   gate 的 PASS 只代表「机器关通过」，**不代表语义关跑过**。
#   那次实跑 gate 给了 PASS，但暂存区里只有 form.json 和 pack/ ——
#   没有需求蒸馏、没有事实表、没有 verdicts/、没有 ledger.jsonl，
#   状态机甚至从未 init（publish_flow.py status 报「尚未 init」）。
#   也就是说：那次发布**只过了机器关，语义关是"在对话里跑的"，没落盘**。
#   这一段把这件事显式报出来，防止 PASS 被读成"全流程都过了"。
echo "--- [4/4] 语义关实际状态（gate 不判质量，只报事实）---"

STAGING=".publish-staging"
sem_missing=0
report_art() {   # $1=标签  $2=相对路径
  if [ -e "$STAGING/$2" ]; then
    printf '  ✅ %s：有\n' "$1"
  else
    printf '  ·  %s：缺\n' "$1"
    sem_missing=$((sem_missing+1))
  fi
}

if [ -d "$STAGING" ]; then
  report_art "状态机 init（.publish-state.json）" ".publish-state.json"
  report_art "需求蒸馏（requirement-brief.md）"   "requirement-brief.md"
  report_art "事实表（fact-sheet.md）"             "fact-sheet.md"
  report_art "独立判定落盘（verdicts/）"           "verdicts"
  report_art "判决账本（ledger.jsonl）"            "ledger.jsonl"

  # ⚠️ 这里**故意不设 hit**（2026-09-23 修正）：
  #   曾加过一条「状态机已 init 但 verdicts/ 为空 → 自相矛盾」的硬拦，
  #   结果在正常中间态上假阳性 —— 状态机先跑完机器节点 N0–N3，才轮到 N4 建 verdicts/，
  #   所以"init 了但还没有 verdicts"是**合法中间态**，不是矛盾。
  #   而且 deferred 也可能纯粹由机器节点连挂 3 轮造成（此时确实没有 verdicts）。
  #   → 从产物本身推不出"声称跑过却没判定"这个结论，**所以只报不拦**。
  #   这一段的价值是"把事实说出口"，不是"拦住" —— 别再加 hit。

  if [ "$sem_missing" -ge 4 ]; then
    echo "  → 本次实际档位：最低档（只有机器关 + 打包 + 发布）"
    echo "  ⚠️  gate 的 PASS 只代表「机器关通过」，不代表语义关跑过。别把两者混为一谈。"
  elif [ "$sem_missing" -eq 0 ]; then
    echo "  → 本次实际档位：全链（语义关产物齐全）"
  else
    echo "  → 本次实际档位：降档（语义关产物缺 $sem_missing 项）"
    echo "  （注：状态机跑到一半时 verdicts/ 尚不存在，属正常中间态，不是异常）"
  fi
else
  echo "  ·  无 .publish-staging/ —— 未走发布链"
  echo "  → 本次实际档位：链外（普通项目，或首次发布尚未起链）"
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
