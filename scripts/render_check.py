#!/usr/bin/env python3
"""render_check.py —— 本地 GitHub 风格渲染预检（零网络，推送前必跑）

为什么存在：渲染层缺陷（{owner} 占位符没填、表格没成表、<占位> 被浏览器吞、emoji 丢失、
相对链接断链）只有"渲染后"才看得出，而此前要在 push 之后才能拿到渲染页 —— 顺序反了。
本工具在本地把 markdown 渲染成 HTML，把这类问题拦在推送之前。

用法：
  python3 render_check.py <README.md> [更多.md ...] [--html-dir <目录>]

输出：逐文件报告 + 可选渲染 HTML（供首屏读者作为输入）。

诚实边界：本工具是 **GFM 近似**（CommonMark + 表格/删除线/任务清单插件），
不是 GitHub 逐像素复刻（无 @mention、语法高亮、自动链接细节）。
权威复核 = 推送批次里 `gh api /markdown`（GFM 精确渲染）或线上页面。
"""
import re
import sys
import html
import pathlib

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

MD = MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": False})
MD.enable("table")
tasklists_plugin(MD)

# 常见"该填没填"的占位符形态：{owner} {slug} {name} … 与 <skill> <素材名> …
BRACE_PH = re.compile(r"\{[a-z_][a-z_0-9\-]*\}")
ANGLE_PH = re.compile(r"<[a-z][a-z0-9_\-]{1,20}>")


def render(md_text: str) -> str:
    return MD.render(md_text)


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def in_code_spans(html_body: str) -> str:
    """去掉 <pre> 块与内联 <code> —— 得到"正文层"（GitHub 上代码里的占位符是参数说明，
    如 `FILE=<path>`，属有意展示，不该报"未填"）。"""
    return re.sub(r"<pre.*?</pre>|<code.*?</code>", "", html_body, flags=re.S)


def visible_all(html_body: str) -> str:
    """读者实际可见的全部文本（含代码）—— 用于"被吞"计数：内联 code 内容 GitHub 上可见。"""
    return html.unescape(re.sub(r"<[^>]+>", "", html_body))


def check(name: str, md_text: str, html_body: str):
    findings = []

    # 1) 未填占位符（正文层：代码块/内联代码里的占位符是参数说明，合法）
    visible = strip_tags(in_code_spans(html_body))
    vis_all = visible_all(re.sub(r"<pre.*?</pre>", "", html_body, flags=re.S))
    braces = sorted(set(BRACE_PH.findall(visible)))
    angles = sorted(set(a for a in ANGLE_PH.findall(visible)))
    if braces:
        findings.append(f"[严重] 花括号占位符未填（代码块外可见）: {', '.join(braces[:8])}")
    if angles:
        findings.append(f"[严重] 尖括号占位符出现在正文（可能被吞或未填）: {', '.join(angles[:8])}")

    # 2) <xx> 被吞检测：同类比较 —— 源码排除围栏代码块（代码块里的占位符是形态说明，合法）
    md_nofence = re.sub(r"```.*?```|~~~.*?~~~", "", md_text, flags=re.S)
    src_angle = len(ANGLE_PH.findall(md_nofence))
    vis_angle = len(ANGLE_PH.findall(vis_all))
    if src_angle > vis_angle:
        findings.append(f"[严重] 尖括号形态源码 {src_angle} 处、渲染后仅可见 {vis_angle} 处 → 有内容被当 HTML 吞掉")

    # 3) 表格真伪
    md_table_lines = len([l for l in md_text.splitlines() if re.match(r"\s*\|.+\|\s*$", l)])
    tr_count = len(re.findall(r"<tr", html_body))
    table_count = len(re.findall(r"<table", html_body))
    if md_table_lines >= 2 and table_count == 0:
        findings.append(f"[严重] 源码有表格语法（{md_table_lines} 行）但渲染后 0 个 <table>")

    # 4) emoji 丢失（同类比较：源码排除围栏代码块 —— 代码块里的 emoji 是展示内容，合法）
    src_emoji = len(re.findall(r"[\U0001F300-\U0001FAFF\u2700-\u27BF\u2705\u274C\u26A0]", md_nofence))
    vis_emoji = len(re.findall(r"[\U0001F300-\U0001FAFF\u2700-\u27BF\u2705\u274C\u26A0]", visible))
    if src_emoji > vis_emoji:
        findings.append(f"[一般] emoji 源码 {src_emoji} 个、渲染后 {vis_emoji} 个 → 有丢失")

    # 5) 相对链接断链
    base = pathlib.Path(name).parent
    hrefs = re.findall(r'href="([^"#]+)"', html_body)
    broken = []
    for h in hrefs:
        if re.match(r"https?://|mailto:", h):
            continue
        if not (base / h.split("#")[0]).exists():
            broken.append(h)
    if broken:
        findings.append(f"[严重] 相对链接断链（文件不存在）: {', '.join(sorted(set(broken))[:6])}")

    # 6) 阅读顺序（前 10 块）
    blocks = re.findall(r"<h1[^>]*>(.*?)</h1>|<h2[^>]*>(.*?)</h2>|<p[^>]*>(.*?)</p>", html_body, re.S)
    order = []
    for a, b, c in blocks:
        t = strip_tags(a or b or c).strip()
        if t:
            order.append(("h1" if a else "h2" if b else "p ", t[:80]))
    return findings, {"table": table_count, "tr": tr_count, "emoji": vis_emoji, "blocks": order[:10]}


def main(argv):
    paths, html_dir = [], None
    i = 0
    while i < len(argv):
        if argv[i] == "--html-dir":
            html_dir = pathlib.Path(argv[i + 1]); html_dir.mkdir(parents=True, exist_ok=True); i += 2
        else:
            paths.append(argv[i]); i += 1
    if not paths:
        print(__doc__); return 2
    rc = 0
    for p in paths:
        p = pathlib.Path(p)
        md_text = p.read_text(encoding="utf-8")
        # 输入防护：本工具只吃 markdown 源码。渲染后的 HTML 是输出不是输入 ——
        # 喂 HTML 会把标签全报成"被吞的尖括号"（2026-09-18 回归实测）。
        if p.suffix.lower() in (".html", ".htm") or re.match(r"\s*<(?:!doctype|html|article|body)", md_text, re.I):
            print(f"❌ {p.name}: 输入是 HTML，不是 markdown 源码 —— 本工具只吃 .md（渲染后的 HTML 是我的输出）")
            rc = 1
            continue
        html_body = render(md_text)
        findings, stats = check(str(p), md_text, html_body)
        print(f"\n===== {p.name} =====")
        print(f"表格 {stats['table']} 个 / {stats['tr']} 行 · emoji {stats['emoji']} 个")
        print("首屏阅读顺序（前 10 块）:")
        for tag, t in stats["blocks"]:
            print(f"  [{tag}] {t}")
        if findings:
            rc = 1
            print("发现的问题:")
            for f in findings:
                print(f"  {f}")
        else:
            print("✅ 渲染预检通过（GFM 近似层）")
        if html_dir:
            out = html_dir / (p.stem + ".rendered.html")
            out.write_text(f'<article>{html_body}</article>', encoding="utf-8")
            print(f"渲染 HTML → {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
