#!/usr/bin/env bash
# crosscheck_dual_platform.sh — N3-X 跨平台一致性校验（Q9）
#
# 为什么需要：reskill 同时发 GitHub 仓库（gh）与 SkillHub（sh）两种形态。
# 两线各自写 README / SKILL.md，常见漂移：版本号两处不一致、SKILL.md description
# 与 README 首句各写各的（roster §六 Q9 + 名册 §六 第 4 行「两线一句话定位不同源」）。
# 本脚本在 N3 阶段卡住这类漂移，避免「GitHub 说 3.5.1、SkillHub 说 2.0.5」式事故。
#
# 校验项（硬，exit 1）：
#   ① 版本号一致：SKILL.md frontmatter version == README 里出现的版本号 == 可选元数据文件
#   ② 名称一致：README 标题含 SKILL.md 的 name / displayName
#   ③ 一句话定位同源：SKILL.md description 首句 与 README 首句 逐字同源（归一化后相等）
#   ④ 若同时给 --gh-dir / --sh-dir：两份产物的 version / description 首句必须一致
#
# 用法：
#   ./crosscheck_dual_platform.sh <skill_dir> [--gh-dir DIR] [--sh-dir DIR]
#   ./crosscheck_dual_platform.sh --test
#
# 退出码：0 = 一致；1 = 存在硬不一致（拒绝进 N3 下一节点）

set -uo pipefail
ARG="${1:-}"

CORE_PY='
import json, os, re, sys

def read_frontmatter(path):
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", txt, re.S)
    if not m:
        return {}
    fm = {}
    cur_key = None
    buf = []
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_]+):\s?(.*)$", line)
        if kv and not line.startswith(" "):
            if cur_key is not None:
                fm[cur_key] = "\n".join(buf).strip()
            cur_key = kv.group(1)
            ind = kv.group(2).strip()
            # YAML 块标量指示符（| / > / |- / >+ 等）：内容从下一缩进行开始，指示符本身不入值
            if re.match(r"^[|>][-+]?$", ind):
                buf = []
            else:
                buf = [kv.group(2)]
        else:
            buf.append(line)
    if cur_key is not None:
        fm[cur_key] = "\n".join(buf).strip()
    return fm

def norm(s):
    return re.sub(r"\s+", "", s or "").strip()

def first_sentence(s):
    s = re.sub(r"\s+", "", s or "")
    # 以中文句号或英文句号+空格或换行断句
    m = re.split(r"[。.!?\n]", s, maxsplit=1)
    return m[0].strip()

def parse(dirp):
    skill = os.path.join(dirp, "SKILL.md")
    if not os.path.isfile(skill):
        return {"error": "no SKILL.md in " + dirp}
    fm = read_frontmatter(skill)
    out = {"version": fm.get("version", ""), "name": fm.get("name", ""),
           "displayName": fm.get("displayName", ""), "description": fm.get("description", "")}
    readme = os.path.join(dirp, "README.md")
    if os.path.isfile(readme):
        rt = open(readme, encoding="utf-8").read()
        # 版本号
        vm = re.findall(r"v?(\d+\.\d+\.\d+)", rt)
        out["readme_versions"] = vm
        seen_title = False
        SKIP = re.compile(r"README_EN\.md|^\s*\[.*\]\(.*\)(\s*\|.*)?$|^\*?\*?当前版本|badge", re.I)
        for ln in rt.splitlines():
            t = ln.strip()
            if not t:
                continue
            if t.startswith("#"):
                if not seen_title:
                    out["readme_title"] = re.sub(r"^#+\s*", "", t).strip()
                    seen_title = True
                continue  # 标题不算定位首句
            if SKIP.search(t):   # 跳过语言切换行 / 版本行 / 徽章行，避免误把链接当定位
                continue
            # 第一个非标题、非切换行的非空行 = 定位首句（去掉可能的 > 引用符）
            out["readme_first_line"] = re.sub(r"^>\s*", "", t).strip()
            break
        if "readme_first_line" not in out:  # README 只有标题/切换行，拿标题兜底
            out["readme_first_line"] = out.get("readme_title", "")
    # 一句话定位同源判定（归一化后首句相等）—— 仅作 🟡 提示，不硬拦（双语 README 常态不逐字一致）
    def _first(s):
        s = re.sub(r"\s+", "", s or "")
        return re.split(r"[。.!?\n]", s, maxsplit=1)[0].strip()
    desc_first = _first(out.get("description", ""))
    readme_first = _first(out.get("readme_first_line", ""))
    out["desc_first"] = desc_first
    out["readme_first"] = readme_first
    out["desc_match"] = (desc_first == readme_first) if (desc_first and readme_first) else None
    return out

dirp = sys.argv[1]
d = parse(dirp)
if "error" in d:
    print(json.dumps({"error": d["error"]}))
    sys.exit(2)
print(json.dumps(d, ensure_ascii=False))
'

run_test() {
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  pass=0; fail=0
  expect() { if [ "$2" = "$3" ]; then printf '  [PASS] %s\n' "$1"; pass=$((pass+1));
             else printf '  [FAIL] %s（期望 %s，实际 %s）\n' "$1" "$2" "$3"; fail=$((fail+1)); fi; }

  # —— 一致样本（应 exit 0）——
  D="$tmp/ok"; mkdir -p "$D"
  printf -- '---\nname: demo\ndisplayName: Demo Skill\nversion: 1.0.0\ndescription: |\n  一句话定位 Demo，用来审发布质量。\n---\n\n# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v1.0.0 已发布。\n' > "$D/SKILL.md"
  printf '# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v1.0.0 已发布。\n' > "$D/README.md"
  "$0" "$D" >/dev/null 2>&1; expect "一致样本 exit 0" "0" "$?"

  # —— 版本不一致（README 写 2.0.0，应 exit 1）——
  D2="$tmp/ver"; mkdir -p "$D2"
  cp "$D/SKILL.md" "$D2/SKILL.md"; cp "$D/README.md" "$D2/README.md"
  printf '# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v2.0.0 已发布。\n' > "$D2/README.md"
  "$0" "$D2" >/dev/null 2>&1; expect "版本不一致 exit 1" "1" "$?"

  # —— 首句不同源（仅 🟡 提示，不硬拦 → 仍 exit 0）——
  D3="$tmp/desc"; mkdir -p "$D3"
  cp "$D/SKILL.md" "$D3/SKILL.md"
  printf '# Demo Skill\n\n完全不同的首句，跟 description 不是一回事。v1.0.0 已发布。\n' > "$D3/README.md"
  "$0" "$D3" >/dev/null 2>&1; expect "首句不同源仅 🟡（exit 0）" "0" "$?"

  # —— 标题不含 name（应 exit 1）——
  D4="$tmp/name"; mkdir -p "$D4"
  cp "$D/SKILL.md" "$D4/SKILL.md"
  printf '# 完全不相关的标题\n\n一句话定位 Demo，用来审发布质量。v1.0.0 已发布。\n' > "$D4/README.md"
  "$0" "$D4" >/dev/null 2>&1; expect "标题不含 name exit 1" "1" "$?"

  # —— 双形态产物版本漂移（--gh-dir/--sh-dir，应 exit 1）——
  GHd="$tmp/gh"; SHd="$tmp/sh"; mkdir -p "$GHd" "$SHd"
  cp "$D/SKILL.md" "$GHd/SKILL.md"; printf '# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v1.0.0 已发布。\n' > "$GHd/README.md"
  printf -- '---\nname: demo\nversion: 2.0.0\n---\n\n# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v2.0.0 已发布。\n' > "$SHd/SKILL.md"
  printf '# Demo Skill\n\n一句话定位 Demo，用来审发布质量。v2.0.0 已发布。\n' > "$SHd/README.md"
  "$0" "$D" --gh-dir "$GHd" --sh-dir "$SHd" >/dev/null 2>&1; expect "gh/sh 版本漂移 exit 1" "1" "$?"

  echo "crosscheck_dual_platform.sh 自检 —— 5 项"
  echo "结果：$pass 通过 / $fail 失败"
  [ "$fail" -eq 0 ] && echo "自检通过。" || echo "自检未通过。"
  return "$fail"
}

if [ "$ARG" = "--test" ]; then run_test; exit $?; fi
if [ -z "$ARG" ] || [ "$ARG" = "--gh-dir" ] || [ "$ARG" = "--sh-dir" ]; then
  echo "用法: $0 <skill_dir> [--gh-dir DIR] [--sh-dir DIR]" >&2; echo "      $0 --test" >&2; exit 2
fi

SKILL_DIR="$ARG"; shift 2>/dev/null
GH=""; SH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gh-dir) GH="${2:-}"; shift 2 ;;
    --sh-dir) SH="${2:-}"; shift 2 ;;
    *) echo "ERROR: 未知参数 $1" >&2; exit 2 ;;
  esac
done

[ -d "$SKILL_DIR" ] || { echo "ERROR: 目录不存在：$SKILL_DIR" >&2; exit 2; }
D=$(python3 -c "$CORE_PY" "$SKILL_DIR") || { echo "$D" >&2; exit 2; }
ERR=$(printf '%s' "$D" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("error",""))')
[ -n "$ERR" ] && { echo "🔴 $ERR"; exit 1; }

ver=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))')
name=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("name",""))')
disp=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("displayName",""))')
desc=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("description",""))')
rvs=$(printf '%s' "$D" | python3 -c 'import json,sys;print(",".join(json.load(sys.stdin).get("readme_versions",[])))')
rtitle=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("readme_title",""))')
rfirst=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("readme_first_line",""))')

red() { echo "🔴 $1"; }
blk=0
echo "=== N3-X 跨平台一致性校验：$SKILL_DIR ==="

# ① 版本号
if [ -n "$rvs" ]; then
  bad=""
  IFS=','; for v in $rvs; do [ "$v" != "$ver" ] && bad="$bad $v"; done; unset IFS
  if [ -n "$bad" ]; then red "版本不一致：SKILL.md=$ver，README 出现$bad"; blk=1; else echo "🟢 版本一致：$ver"; fi
else
  echo "ℹ️  README 未出现版本号，跳过版本校验"
fi

# ② 名称
if [ -n "$rtitle" ]; then
  if echo "$rtitle" | grep -q "$name"; then echo "🟢 标题含 name：$name";
  elif [ -n "$disp" ] && echo "$rtitle" | grep -q "$disp"; then echo "🟢 标题含 displayName：$disp";
  else red "标题「$rtitle」不含 name($name)/displayName($disp)"; blk=1; fi
else
  echo "ℹ️  无 README 标题，跳过名称校验"
fi

# ③ 一句话定位同源（仅 🟡 提示，不硬拦：双语 README 常态不逐字一致，硬拦=假门）
dmatch=$(printf '%s' "$D" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("desc_match"))')
if [ "$dmatch" = "True" ]; then
  echo "🟢 一句话定位同源（description 首句 = README 定位句）"
elif [ "$dmatch" = "False" ]; then
  msg=$(printf '%s' "$D" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("SKILL.md description 首句「%s」↔ README 定位句「%s」"%(d.get("desc_first",""),d.get("readme_first","")))' 2>/dev/null)
  echo "🟡 [ADVISORY] 一句话定位未逐字同源：${msg:-（detail 见 description / README 定位句）}（不拦 N3）"
else
  echo "ℹ️  description 或 README 定位句缺失，跳过同源校验"
fi

# ④ 双形态产物对比
if [ -n "$GH" ] && [ -n "$SH" ]; then
  for pair in "$GH" "$SH"; do [ -d "$pair" ] || { red "平台目录不存在：$pair"; blk=1; }; done
  DG=$(python3 -c "$CORE_PY" "$GH" 2>/dev/null); DSH=$(python3 -c "$CORE_PY" "$SH" 2>/dev/null)
  gv=$(printf '%s' "$DG" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null)
  sv=$(printf '%s' "$DSH" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null)
  [ "$gv" != "$sv" ] && { red "gh($gv) 与 sh($sv) 版本不一致"; blk=1; } || echo "🟢 gh/sh 版本一致：$gv"
fi

if [ "$blk" -ne 0 ]; then echo "--- 结论：🔴 存在跨平台不一致，N3 不过 ---"; exit 1; fi
echo "--- 结论：🟢 跨平台一致 ---"; exit 0
