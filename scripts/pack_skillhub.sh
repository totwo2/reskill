#!/usr/bin/env bash
# pack_skillhub.sh — N6-S 打包：给 SkillHub 出一份「干净副本」
#
# 为什么需要这一步（不是多余动作）：
#   skillhub CLI 的打包排除表写死只有 .git/.idea/.vscode/node_modules/__pycache__
#   + *.pyc/.DS_Store/Thumbs.db 这几项（skills_store_cli.py:2227）。
#   它不认 .publish-staging/，也不认自测临时目录。
#   所以直接把 skill 目录丢给 publish，这些中间产物会被当成正式文件一起传上去。
#   本脚本先复制出一份干净副本，再拿副本去 publish。
#
# 用法：
#   ./pack_skillhub.sh <skill 目录> [--out DIR] [--json]
#   ./pack_skillhub.sh --test
#
# 输出：干净副本的绝对路径（stdout 最后一行）；--json 时输出 JSON。
#       调用方接着跑：skillhub publish "<副本路径>" --changelog "..."
#
# 额外排除（可选）：PACK_EXTRA_EXCLUDE="名字1,名字2" ./pack_skillhub.sh <dir>

set -uo pipefail

ARG="${1:-}"

# ---------------------------------------------------------------- 核心（python）
# 复制 + 排除 + 事后校验放在同一段里，避免"复制完才发现漏排"。
PACK_PY='
import json, os, shutil, sys

src, out, extra = sys.argv[1], sys.argv[2], sys.argv[3]

# 目录名：整棵剪掉
DIR_EXCLUDE = {
    ".git", ".idea", ".vscode", "node_modules", "__pycache__",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".publish-staging",          # 发布流程自己的暂存区
}
# 目录名后缀：自测临时目录（脚本 --test 会在旧版本里往包内写）
DIR_EXCLUDE_SUFFIX = ("_selftest_tmp",)
# 文件名：整份剪掉
# LICENSE 也要剪：SkillHub 实测拒收该文件类型（400「不允许的文件类型」），
# 许可只能靠 SKILL.md frontmatter 的 license: 声明（HANDOVER.md 2026-09-18 实测）。
FILE_EXCLUDE = {".DS_Store", "Thumbs.db", ".gitignore",
                "LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"}
# 文件后缀：整类剪掉
FILE_EXCLUDE_SUFFIX = (".pyc", ".pyo", ".pyd")

for name in [x.strip() for x in extra.split(",") if x.strip()]:
    DIR_EXCLUDE.add(name)
    FILE_EXCLUDE.add(name)

src = os.path.abspath(os.path.expanduser(src))
out = os.path.abspath(os.path.expanduser(out))

if not os.path.isdir(src):
    print(f"ERROR: 不是目录：{src}", file=sys.stderr); sys.exit(1)
if not os.path.isfile(os.path.join(src, "SKILL.md")):
    print(f"ERROR: 目录内没有 SKILL.md，不是 skill 包：{src}", file=sys.stderr); sys.exit(1)

# 旧副本先清掉，避免上一版的残留文件混进这一版
if os.path.isdir(out):
    shutil.rmtree(out)
os.makedirs(out, exist_ok=True)

def skip_dir(name):
    return name in DIR_EXCLUDE or any(name.endswith(s) for s in DIR_EXCLUDE_SUFFIX)

def skip_file(name):
    return name in FILE_EXCLUDE or any(name.endswith(s) for s in FILE_EXCLUDE_SUFFIX)

copied, skipped = [], []
for root, dirs, files in os.walk(src, followlinks=False):
    pruned = [d for d in dirs if skip_dir(d)]
    for d in pruned:
        skipped.append(os.path.relpath(os.path.join(root, d), src) + "/")
    dirs[:] = sorted(d for d in dirs if not skip_dir(d))
    for d in dirs:
        rel = os.path.relpath(os.path.join(root, d), src)
        os.makedirs(os.path.join(out, rel), exist_ok=True)
    for f in sorted(files):
        rel = os.path.relpath(os.path.join(root, f), src)
        if skip_file(f):
            skipped.append(rel); continue
        ap = os.path.join(root, f)
        if os.path.islink(ap):          # 软连接不跟随（可能指向包外）
            skipped.append(rel + " (软连接)"); continue
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(ap, dst)
        copied.append(rel)

# ---- 事后校验：副本里不许再出现这些 ----
bad = []
for root, dirs, files in os.walk(out):
    for name in list(dirs) + files:
        if skip_dir(name) or skip_file(name):
            bad.append(os.path.relpath(os.path.join(root, name), out))
if bad:
    print("ERROR: 干净副本里仍检出应排除的路径：", file=sys.stderr)
    for b in sorted(bad):
        print("  " + b, file=sys.stderr)
    sys.exit(1)
if not os.path.isfile(os.path.join(out, "SKILL.md")):
    print("ERROR: 副本缺少 SKILL.md（复制过程异常）", file=sys.stderr); sys.exit(1)

total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs)
print(json.dumps({
    "out": out,
    "files": len(copied),
    "bytes": total,
    "kb": round(total / 1024, 1),
    "file_list": sorted(copied),
    "skipped_count": len(skipped),
    "skipped": sorted(skipped),
}, ensure_ascii=False))
'

# ---------------------------------------------------------------- 自检
run_test() {
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  pass=0; fail=0

  # 造一个"脏"skill 目录：正式文件 + 四类噪音
  mkdir -p "$tmp/dirty/scripts/__pycache__" \
           "$tmp/dirty/scripts/_selftest_tmp" \
           "$tmp/dirty/.publish-staging" \
           "$tmp/dirty/.git"
  printf -- '---\nname: x\n---\n\n# x\n' > "$tmp/dirty/SKILL.md"
  printf '# rules\n'                     > "$tmp/dirty/rules.md"
  printf 'print(1)\n'                    > "$tmp/dirty/scripts/run.py"
  printf 'noise\n'                       > "$tmp/dirty/scripts/__pycache__/run.pyc"
  printf 'noise\n'                       > "$tmp/dirty/scripts/_selftest_tmp/dirty.md"
  printf '{"form":"skill"}\n'            > "$tmp/dirty/.publish-staging/form.json"
  printf 'noise\n'                       > "$tmp/dirty/.git/config"
  printf 'noise\n'                       > "$tmp/dirty/.DS_Store"
  printf 'MIT License\n'                 > "$tmp/dirty/LICENSE"

  expect() {
    local name="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
      printf '  [PASS] %s\n' "$name"; pass=$((pass+1))
    else
      printf '  [FAIL] %s（期望 %s，实际 %s）\n' "$name" "$want" "$got"; fail=$((fail+1))
    fi
  }

  json="$("$0" "$tmp/dirty" --json 2>/dev/null)"
  outdir="$(printf '%s' "$json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["out"])')"

  expect "副本里没有 .publish-staging"  "0" "$(find "$outdir" -name '.publish-staging' | wc -l | tr -d ' ')"
  expect "副本里没有 __pycache__"       "0" "$(find "$outdir" -name '__pycache__' -o -name '*.pyc' | wc -l | tr -d ' ')"
  expect "副本里没有 _selftest_tmp"     "0" "$(find "$outdir" -name '*_selftest_tmp' | wc -l | tr -d ' ')"
  expect "副本里没有 .git"              "0" "$(find "$outdir" -name '.git' -o -name '.DS_Store' | wc -l | tr -d ' ')"
  expect "副本里没有 LICENSE(平台拒收)" "0" "$(find "$outdir" -name 'LICENSE*' -o -name 'COPYING' | wc -l | tr -d ' ')"
  expect "保留 SKILL.md"                "1" "$([ -f "$outdir/SKILL.md" ] && echo 1 || echo 0)"
  expect "保留 rules.md"                "1" "$([ -f "$outdir/rules.md" ] && echo 1 || echo 0)"
  expect "保留 scripts/run.py"          "1" "$([ -f "$outdir/scripts/run.py" ] && echo 1 || echo 0)"
  expect "文件数=3"                     "3" "$(printf '%s' "$json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["files"])')"
  expect "排除项有计数(含被剪目录)"     "1" "$(printf '%s' "$json" | python3 -c 'import json,sys;print(1 if json.load(sys.stdin)["skipped_count"] >= 5 else 0)')"

  # 没有 SKILL.md 时必须拒收
  mkdir -p "$tmp/notskill" && printf 'x\n' > "$tmp/notskill/a.md"
  "$0" "$tmp/notskill" >/dev/null 2>&1
  expect "非 skill 目录拒收(退出码非0)" "1" "$([ $? -ne 0 ] && echo 1 || echo 0)"

  echo "pack_skillhub.sh 自检 —— 11 项"
  echo "结果：$pass 通过 / $fail 失败"
  [ "$fail" -eq 0 ] && echo "自检通过：副本干净、正式文件齐全、非 skill 拒收。" || echo "自检未通过。"
  return "$fail"
}

if [ "$ARG" = "--test" ]; then
  run_test
  exit $?
fi

if [ -z "$ARG" ]; then
  echo "用法: $0 <skill 目录> [--out DIR] [--json]" >&2
  echo "      $0 --test" >&2
  exit 2
fi

# ---------------------------------------------------------------- 参数
OUT=""
AS_JSON=0
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --out)  OUT="${2:-}"; shift 2 ;;
    --json) AS_JSON=1; shift ;;
    *) echo "ERROR: 未知参数 $1" >&2; exit 2 ;;
  esac
done

SKILL_DIR="$(cd "$ARG" 2>/dev/null && pwd)" || { echo "ERROR: 目录不存在：$ARG" >&2; exit 1; }
[ -n "$OUT" ] || OUT="$SKILL_DIR/.publish-staging/pack/$(basename "$SKILL_DIR")"

RESULT="$(python3 -c "$PACK_PY" "$SKILL_DIR" "$OUT" "${PACK_EXTRA_EXCLUDE:-}")" || exit 1

if [ "$AS_JSON" -eq 1 ]; then
  printf '%s\n' "$RESULT"
else
  # 用环境变量把 JSON 递进去：heredoc 占着 stdin，不能再靠管道喂
  PACK_RESULT="$RESULT" python3 - <<'PY'
import json, os
d = json.loads(os.environ["PACK_RESULT"])
print("干净副本：", d["out"])
print(f"文件 {d['files']} 个 · {d['kb']}KB · 已排除 {d['skipped_count']} 项")
for p in d["file_list"]:
    print("  " + p)
PY
  printf '%s' "$RESULT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["out"])'
fi
