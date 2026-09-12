#!/usr/bin/env bash
# detect_publish_form.sh — N0 形态判定
#
# 判定一个项目该走哪条发布路径：
#   skill           是 skill，且装得进 skill 包        → SkillHub + GitHub
#   installer       不是 skill，但装得进 skill 包      → GitHub + SkillHub（内嵌代码）
#   github-project  装不进包 / 需编译 / 常驻服务       → 只发 GitHub
#
# 用法：
#   ./detect_publish_form.sh [项目目录]
#   ./detect_publish_form.sh --test
#   SIZE_LIMIT_MB=4 ./detect_publish_form.sh /path/to/proj
#
# 输出：JSON 到 stdout，并写入 <项目>/.publish-staging/form.json

set -uo pipefail

DIR="${1:-.}"
SIZE_LIMIT_MB="${SIZE_LIMIT_MB:-2}"

# ---------------------------------------------------------------- 工具
dir_size_kb() {
  python3 - "$1" <<'PY'
import os, sys
root = sys.argv[1]
total = 0
skip = {'.git', '.publish-staging', 'node_modules', '__pycache__', '.venv', 'venv'}
for dp, dn, fn in os.walk(root):
    dn[:] = [d for d in dn if d not in skip]
    for f in fn:
        try:
            total += os.path.getsize(os.path.join(dp, f))
        except OSError:
            pass
print(int(total / 1024))
PY
}

# ---------------------------------------------------------------- 自检
run_test() {
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  pass=0; fail=0

  mk() { mkdir -p "$tmp/$1"; }

  # 1) 是 skill，体积小 → skill
  mk s1 && printf -- '---\nname: x\n---\n' > "$tmp/s1/SKILL.md"
  # 2) 需编译（go.mod）→ github-project
  mk s2 && printf 'module x\n' > "$tmp/s2/go.mod"
  # 3) 有 pyproject，小 → installer
  mk s3 && printf '[project]\nname = "x"\n' > "$tmp/s3/pyproject.toml"
  # 4) 常驻服务（Dockerfile）→ github-project
  mk s4 && printf 'FROM python:3.12\n' > "$tmp/s4/Dockerfile"
  # 5) 是 skill 但超体积 → github-project
  mk s5 && printf -- '---\nname: y\n---\n' > "$tmp/s5/SKILL.md"
  python3 -c "open('$tmp/s5/blob.bin','wb').write(b'0'*3*1024*1024)"

  expect() {
    local name="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
      printf '  [PASS] %s → %s\n' "$name" "$got"; pass=$((pass+1))
    else
      printf '  [FAIL] %s → 期望 %s，实际 %s\n' "$name" "$want" "$got"; fail=$((fail+1))
    fi
  }

  expect "是 skill 且不超体积"          "skill"          "$(SIZE_LIMIT_MB=2 "$0" "$tmp/s1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["form"])')"
  expect "需编译 go.mod"                "github-project" "$("$0" "$tmp/s2" | python3 -c 'import json,sys;print(json.load(sys.stdin)["form"])')"
  expect "非 skill 但装得进包"          "installer"      "$("$0" "$tmp/s3" | python3 -c 'import json,sys;print(json.load(sys.stdin)["form"])')"
  expect "常驻服务 Dockerfile"          "github-project" "$("$0" "$tmp/s4" | python3 -c 'import json,sys;print(json.load(sys.stdin)["form"])')"
  expect "skill 超体积上限"             "github-project" "$(SIZE_LIMIT_MB=2 "$0" "$tmp/s5" | python3 -c 'import json,sys;print(json.load(sys.stdin)["form"])')"

  echo "detect_publish_form.sh 自检 —— 5 项"
  echo "结果：$pass 通过 / $fail 失败"
  [ "$fail" -eq 0 ] && echo "自检通过：四条路径判定正确。" || echo "自检未通过。"
  return "$fail"
}

if [ "$DIR" = "--test" ]; then
  run_test
  exit $?
fi

if [ ! -d "$DIR" ]; then
  echo "ERROR: 目录不存在：$DIR" >&2
  exit 1
fi

# ---------------------------------------------------------------- 判定
size_kb="$(dir_size_kb "$DIR")"
size_mb_int=$(( size_kb / 1024 ))
limit_kb=$(( SIZE_LIMIT_MB * 1024 ))

is_skill=0;      [ -f "$DIR/SKILL.md" ] && is_skill=1
needs_build=0;   for f in Cargo.toml go.mod pom.xml build.gradle Makefile CMakeLists.txt; do [ -f "$DIR/$f" ] && needs_build=1; done
is_service=0;    for f in Dockerfile docker-compose.yml docker-compose.yaml; do [ -f "$DIR/$f" ] && is_service=1; done
has_manifest=0;  for f in pyproject.toml setup.py package.json; do [ -f "$DIR/$f" ] && has_manifest=1; done
oversize=0;      [ "$size_kb" -gt "$limit_kb" ] && oversize=1

evidence=""; blockers=""
add_ev()  { evidence="${evidence}${evidence:+, }\"$1\""; }
add_blk() { blockers="${blockers}${blockers:+, }\"$1\""; }

[ "$is_skill" -eq 1 ]     && add_ev "SKILL.md 存在"
[ "$has_manifest" -eq 1 ] && add_ev "有包清单（pyproject/setup.py/package.json）"
[ "$needs_build" -eq 1 ]  && add_ev "需编译（发现构建清单）"
[ "$is_service" -eq 1 ]   && add_ev "常驻服务（发现 Dockerfile/compose）"
add_ev "体积 ${size_kb}KB（上限 ${SIZE_LIMIT_MB}MB）"

if [ "$is_skill" -eq 1 ] && [ "$oversize" -eq 0 ]; then
  form="skill"; publish_to='"skillhub", "github"'
elif [ "$is_skill" -eq 1 ] && [ "$oversize" -eq 1 ]; then
  form="github-project"; publish_to='"github"'
  add_blk "skill 包体积超 ${SIZE_LIMIT_MB}MB，装不进 SkillHub"
elif [ "$oversize" -eq 1 ]; then
  form="github-project"; publish_to='"github"'
  add_blk "体积超 ${SIZE_LIMIT_MB}MB"
elif [ "$needs_build" -eq 1 ]; then
  form="github-project"; publish_to='"github"'
  add_blk "需编译，装不进 skill 包"
elif [ "$is_service" -eq 1 ]; then
  form="github-project"; publish_to='"github"'
  add_blk "常驻服务，装不进 skill 包"
elif [ "$has_manifest" -eq 1 ]; then
  form="installer"; publish_to='"github", "skillhub"'
else
  form="github-project"; publish_to='"github"'
  add_ev "未发现 skill 标识，按普通项目处理"
fi

json="{
  \"form\": \"$form\",
  \"publish_to\": [$publish_to],
  \"size_kb\": $size_kb,
  \"size_limit_mb\": $SIZE_LIMIT_MB,
  \"evidence\": [$evidence],
  \"blockers\": [$blockers]
}"

staging="$DIR/.publish-staging"
mkdir -p "$staging"
printf '%s\n' "$json" > "$staging/form.json"
printf '%s\n' "$json"
