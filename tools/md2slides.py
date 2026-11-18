# -*- coding: utf-8 -*-
"""把「一页一节」的精简笔记 Markdown 转成 16:9 横版 HTML / PDF。

用法:
    python md2slides.py <input.md> [-o out.pdf] [--html]
规则:
    * 文件开头到第一个 "## " 之前的内容 = 封面页
    * 每个 "## " 开头的二级标题 = 一页（幻灯片）
"""
import os
import re
import sys
import html
import subprocess
import argparse

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME = next((p for p in CHROME_CANDIDATES if os.path.exists(p)), CHROME_CANDIDATES[0])

HERE = os.path.dirname(os.path.abspath(__file__))
MATHJAX_LOCAL = os.path.join(HERE, "tex-svg.js")
MATHJAX_TMP = os.path.join(os.environ.get("TEMP", "."), "mj.js")
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"

SLIDE_W, SLIDE_H = 1280, 720


def mathjax_source():
    """优先用 tools/tex-svg.js，其次 %TEMP%\\mj.js，最后从 CDN 下载一次。"""
    for p in (MATHJAX_LOCAL, MATHJAX_TMP):
        if os.path.exists(p) and os.path.getsize(p) > 100000:
            return p
    import urllib.request
    print("downloading MathJax ->", MATHJAX_TMP)
    urllib.request.urlretrieve(MATHJAX_URL, MATHJAX_TMP)
    return MATHJAX_TMP


def inline(text):
    """行内元素：先保护公式/代码，再转义，最后处理加粗斜体。"""
    stash = []

    def keep(s):
        stash.append(s)
        return "\x00%d\x00" % (len(stash) - 1)

    text = re.sub(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$",
                  lambda m: keep('<span class="m">\\(' + html.escape(m.group(1), quote=False) + '\\)</span>'), text)
    text = re.sub(r"`([^`]+)`", lambda m: keep("<code>" + html.escape(m.group(1)) + "</code>"), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    for i, s in enumerate(stash):
        text = text.replace("\x00%d\x00" % i, s)
    return text


def split_cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def render_block(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("$$"):
            buf = []
            if s == "$$":
                i += 1
                while i < n and lines[i].strip() != "$$":
                    buf.append(lines[i])
                    i += 1
                i += 1
            else:
                buf.append(s.strip("$"))
                i += 1
                while i < n and not lines[i].strip().endswith("$$"):
                    buf.append(lines[i])
                    i += 1
                if i < n:
                    buf.append(lines[i].strip()[:-2])
                    i += 1
            tex = "\n".join(buf).strip()
            out.append('<div class="blk">\\[%s\\]</div>' % html.escape(tex, quote=False))
            continue
        if s.startswith("###"):
            out.append("<h3>%s</h3>" % inline(s.lstrip("#").strip()))
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            if len(rows) >= 2 and re.match(r"^\|[\s:\-\|]+\|?$", rows[1].strip()):
                head = split_cells(rows[0])
                body = [split_cells(r) for r in rows[2:]]
                t = ["<table><thead><tr>"]
                t += ["<th>%s</th>" % inline(c) for c in head]
                t.append("</tr></thead><tbody>")
                for r in body:
                    t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
                t.append("</tbody></table>")
                out.append('<div class="tbl">%s</div>' % "".join(t))
            else:
                out.append("<p>%s</p>" % inline(rows[0]))
            continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline(" ".join(buf)))
            continue
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if m:
            ordered = bool(re.match(r"\d+\.", m.group(2)))
            items = []
            base = len(m.group(1))
            while i < n:
                mm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not mm or len(mm.group(1)) != base:
                    break
                items.append(mm.group(3))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(x) for x in items), tag))
            continue
        buf = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^\s*([-*+]|\d+\.|\||>|#{1,3}\s|\$\$)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(buf)))
    return "\n".join(out)


def build(md_path):
    text = open(md_path, encoding="utf-8-sig").read()
    text = re.sub(r"(?m)^-{3,}\s*$", "", text)
    chunks = re.split(r"(?m)^##\s+", text)
    title_md, sections = chunks[0], chunks[1:]
    slides = []
    t_lines = [l for l in title_md.split("\n") if l.strip()]
    title = ""
    for l in t_lines:
        if l.startswith("# "):
            title = l[2:].strip()
    sub = " ".join(l.strip().lstrip(">").strip() for l in t_lines if l.strip().startswith(">"))
    other = [l for l in t_lines
             if not l.startswith("# ") and not l.strip().startswith(">")]
    slides.append('<section class="slide cover">'
                  '<svg class="bg" viewBox="0 0 1280 720" preserveAspectRatio="none">'
                  '<rect width="1280" height="720" fill="#0f2b46"/>'
                  '<rect x="60" y="640" width="1160" height="6" fill="#2f7ec4"/></svg>'
                  '<div class="inner"><h1>%s</h1>%s%s</div></section>' % (
                      inline(title), "<p class='sub'>%s</p>" % inline(sub) if sub else "",
                      render_block(other) if other else ""))
    for sec in sections:
        lines = sec.split("\n")
        head = lines[0].strip()
        slides.append('<section class="slide"><h2>%s</h2>%s</section>' % (
            inline(head), render_block(lines[1:])))
    return "\n".join(slides)


CSS = """
@page { size: %(w)dpx %(h)dpx; margin: 0; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { margin:0; padding:0; background:#fff; }
body { font-family: "Microsoft YaHei","Segoe UI",system-ui,sans-serif; color:#14181f; }
section.slide {
  width: %(w)dpx; height: %(h)dpx; padding: 26px 34px 20px;
  page-break-after: always; break-after: page; overflow: hidden;
  display: flex; flex-direction: column; background:#fff;
}
section.slide:last-child { page-break-after: auto; break-after: auto; }
.cover { position: relative; justify-content:center; align-items:center; text-align:center; }
.cover .bg { position:absolute; left:0; top:0; width:100%%; height:100%%; }
.cover .inner { position: relative; z-index: 2; color:#fff; width:100%%; }
.cover h1 { font-size: 46px; margin:0 0 18px; color:#fff; border:none; }
.cover .sub { font-size: 20px; opacity:.92; }
.cover p { font-size: 20px; color:#dce8f4; }
h2 { font-size: 34px; margin: 0 0 12px; padding-bottom: 7px; color:#0f2b46;
     border-bottom: 4px solid #2f7ec4; flex: 0 0 auto; }
h3 { font-size: 25px; margin: 10px 0 6px; color:#1d5c96; }
p, li { font-size: 24px; line-height: 1.5; margin: 6px 0; }
ul, ol { margin: 4px 0 4px 2px; padding-left: 28px; }
li { margin: 4px 0; }
strong { color:#b3261e; }
em { color:#0f2b46; font-style: normal; border-bottom:1px dotted #999; }
code { font-family: Consolas,monospace; background:#eef2f7; padding:0 4px; border-radius:3px; }
blockquote { margin: 9px 0; padding: 9px 14px; background:#fff7e6; border-left:6px solid #f0a500; font-size: 23px; }
.blk { margin: 10px 0; text-align:center; overflow:hidden; }
.tbl { margin: 8px 0; }
table { border-collapse: collapse; width: 100%%; font-size: 21px; }
th, td { border: 1px solid #b9c6d4; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background:#e8f0f8; }
td { line-height:1.35; }
mjx-container[display="true"] { margin: 3px 0 !important; }
"""

JS = """
function fits(el) { return el.scrollHeight <= el.clientHeight + 2; }
function fitAll() {
  document.querySelectorAll('section.slide').forEach(function (s) {
    if (s.classList.contains('cover')) return;
    var scale = 1.0, guard = 0;
    while (!fits(s) && guard < 24) {
      scale -= 0.05;
      s.style.transform = 'scale(' + scale + ')';
      s.style.transformOrigin = 'top left';
      s.style.width = (100 / scale) + '%';
      s.style.height = (100 / scale) + '%';
      guard++;
    }
  });
  document.title = 'SLIDES_READY';
}
window.addEventListener('load', function () {
  if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
    MathJax.startup.promise.then(fitAll).catch(fitAll);
  } else { setTimeout(fitAll, 500); }
});
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()

    body = build(args.md)
    mj = open(mathjax_source(), encoding="utf-8").read()
    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']],tags:'none'},
 svg:{fontCache:'global'},startup:{}};</script>
<script>%s</script>
<style>%s</style></head><body>%s<script>%s</script></body></html>""" % (
        mj, CSS % {"w": SLIDE_W, "h": SLIDE_H}, body, JS)

    base = os.path.splitext(args.md)[0]
    out_html = base + "_slides.html"
    open(out_html, "w", encoding="utf-8").write(doc)
    print("HTML:", out_html)

    if args.html:
        return
    out_pdf = args.out or (base + ".pdf")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--virtual-time-budget=60000", "--no-pdf-header-footer",
           "--print-to-pdf=" + out_pdf, "file:///" + out_html.replace("\\", "/")]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = os.path.exists(out_pdf)
    print("PDF:", out_pdf, "ok" if ok else "FAILED")
    if not ok:
        print(res.stderr[-2000:])
    else:
        print("size:", os.path.getsize(out_pdf), "bytes")


if __name__ == "__main__":
    main()
