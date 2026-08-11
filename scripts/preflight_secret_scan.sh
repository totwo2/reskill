#!/usr/bin/env bash
# preflight_secret_scan.sh — 发布前凭据扫描（机制性防线）
# 用法:
#   bash scripts/preflight_secret_scan.sh [目录]           # 默认：尊重 .gitignore（用于 git push 前）
#   bash scripts/preflight_secret_scan.sh [目录] --all      # 扫全部文件（用于 skillhub 打包前，不看 .gitignore）
# 命中任何疑似凭据 → 退出码 1 → 必须中止发布。
set -u
DIR="."
SCAN_ALL=0
for a in "$@"; do
  case "$a" in
    --all) SCAN_ALL=1 ;;
    *) DIR="$a" ;;
  esac
done
cd "$DIR" || { echo "目录不存在: $DIR"; exit 2; }

if [ "$SCAN_ALL" = "1" ]; then
  echo "===== 发布前凭据扫描 [全量/打包模式]: $(pwd) ====="
else
  echo "===== 发布前凭据扫描 [尊重.gitignore/git模式]: $(pwd) ====="
fi

# 选文件：默认模式仅扫 git 将提交的文件（尊重 .gitignore）；--all 模式扫全部
if [ "$SCAN_ALL" = "0" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  FILES=$( { git ls-files; git ls-files --others --exclude-standard; } 2>/dev/null \
    | grep -vE '\.example\.|preflight_secret_scan\.sh' )
else
  FILES=$(find . -type f \
    -not -path "*/.git/*" \
    -not -name "*.example.*" \
    -not -name "preflight_secret_scan.sh" 2>/dev/null)
fi

# 凭据特征模式
PATTERNS=(
  'access_token["'"'"' :=]+[0-9a-f]{20,}'   # gitee/通用 hex token
  'token["'"'"' :=]+[0-9a-f]{24,}'          # 长 hex token
  'skh_[0-9A-Za-z]{8,}'                     # skillhub token
  'gh[pousr]_[0-9A-Za-z]{20,}'             # github token
  'sk-[0-9A-Za-z]{20,}'                     # openai 风格
  'AKIA[0-9A-Z]{16}'                        # aws
  'xox[baprs]-[0-9A-Za-z-]{10,}'           # slack
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'      # 私钥
)

HIT=0
for f in $FILES; do
  for p in "${PATTERNS[@]}"; do
    if grep -nEi "$p" "$f" >/dev/null 2>&1; then
      echo "🔴 疑似凭据: $f"
      grep -nEi "$p" "$f" 2>/dev/null | sed -E 's/([0-9a-fA-F]{6})[0-9a-fA-F]{10,}/\1***REDACTED***/g' | head -3
      HIT=1
    fi
  done
done

echo "----------------------------------------"
if [ "$HIT" = "1" ]; then
  echo "❌ 扫描未通过：发现疑似凭据，禁止发布！"
  echo "   处理：把凭据移出仓库 → 改用 *.example.* 脱敏文件 → 加入 .gitignore → 重扫。"
  exit 1
else
  echo "✅ 扫描通过：未发现凭据，可以发布。"
  exit 0
fi
