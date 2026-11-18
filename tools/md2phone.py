# -*- coding: utf-8 -*-
"""把精简笔记 Markdown 转成手机竖版 720×1280 的 PDF（连续排版，自动分页）。

用法:
    python md2phone.py <input.md> [-o out.pdf] [--html]
规则:
    * 文件开头到第一个 "## " 之前的内容 = 封面页（# 一级标题 + > 引用行）
    * 其余内容连续排版，按 720×1280 自动分页，右下角加页码
"""
import os
import re
import sys
import html
import argparse
import subprocess

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

PAGE_W, PAGE_H = 720, 1280


def mathjax_source():
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
    text = text.replace("&lt;br&gt;", "<br>")
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


def render_blocks(lines):
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
            startnum = int(m.group(2)[:-1]) if ordered else 1
            items = []
            base = len(m.group(1))
            while i < n:
                mm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not mm:
                    break
                ind = len(mm.group(1))
                if ind == base:
                    items.append([mm.group(3), []])
                    i += 1
                elif ind > base and items:
                    while i < n:
                        m2 = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                        if not m2 or len(m2.group(1)) <= base:
                            break
                        items[-1][1].append(m2.group(3))
                        i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            sub_tag = "ul"
            attr = ' start="%d"' % startnum if ordered and startnum != 1 else ""
            lis = []
            for text, sub in items:
                if sub:
                    lis.append("<li>%s<%s>%s</%s></li>" % (
                        inline(text), sub_tag,
                        "".join("<li>%s</li>" % inline(x) for x in sub), sub_tag))
                else:
                    lis.append("<li>%s</li>" % inline(text))
            out.append("<%s%s>%s</%s>" % (tag, attr, "".join(lis), tag))
            continue
        buf = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^\s*([-*+]|\d+\.|\||>|#{1,3}\s|\$\$)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(buf)))
    return out


def render_block(lines):
    return "\n".join(render_blocks(lines))


def build(md_path):
    text = open(md_path, encoding="utf-8-sig").read()
    text = re.sub(r"(?m)^-{3,}\s*$", "", text)
    chunks = re.split(r"(?m)^##\s+", text)
    title_md, sections = chunks[0], chunks[1:]

    t_lines = [l for l in title_md.split("\n") if l.strip()]
    title = ""
    for l in t_lines:
        if l.startswith("# "):
            title = l[2:].strip()
    quotes = [l.strip().lstrip(">").strip() for l in t_lines if l.strip().startswith(">")]
    sub = quotes[0] if quotes else ""
    star = " ".join(quotes[1:]) if len(quotes) > 1 else ""
    other = [l for l in t_lines if not l.startswith("# ") and not l.strip().startswith(">")]

    cover = ['<section class="slide cover"><div class="inner">',
             '<h1>%s</h1>' % inline(title)]
    if sub:
        cover.append('<p class="sub">%s</p>' % inline(sub))
    if star:
        cover.append('<p class="star">%s</p>' % inline(star))
    if other:
        cover.append(render_block(other))
    cover.append('</div></section>')

    body = ['<section class="content">']
    for sec in sections:
        lines = sec.split("\n")
        head = lines[0].strip()
        blocks = render_blocks(lines[1:])
        if blocks and len(blocks[0]) < 600:
            body.append('<div class="sec"><div class="grp"><h2>%s</h2>%s</div>%s</div>' % (
                inline(head), blocks[0], "\n".join(blocks[1:])))
        else:
            body.append('<div class="sec"><h2>%s</h2>%s</div>' % (inline(head), "\n".join(blocks)))
    body.append("</section>")

    return "\n".join(cover + body), title


CSS = """
@page { size: 720px 1280px; margin: 0; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { margin:0; padding:0; background:#fff; width: 720px; max-width: 720px; overflow-x: hidden; }
body { font-family: "Microsoft YaHei","Segoe UI",system-ui,sans-serif; color:#14181f;
       font-size: 22px; line-height: 1.6; overflow-wrap: break-word; }
section.cover { height: 1280px; page-break-after: always; break-after: page; position: relative;
  background: #0f2b46; color: #fff; display: flex; flex-direction: column; justify-content: center;
  padding: 0 56px; }
section.cover::after { content:""; position:absolute; left:56px; right:56px; bottom:56px; height:6px;
  background:#2f7ec4; }
.cover h1 { font-size: 44px; line-height: 1.3; margin: 0 0 34px; color:#fff; font-weight: 700; }
.cover .sub { font-size: 21px; color:#cfe0ef; margin: 0 0 20px; }
.cover .star { font-size: 24px; line-height:1.55; color:#e8f0f8; margin: 6px 0 0; }
.cover strong { color:#ff9a8b; }
.cover .m { color:#9ecbff; }
section.content { padding: 34px 40px 40px; }
.sec { break-inside: auto; }
.grp { break-inside: avoid; page-break-inside: avoid; }
h2 { font-size: 27px; margin: 26px 0 10px; padding-bottom: 6px; color:#0f2b46;
     border-bottom: 4px solid #2f7ec4; break-after: avoid; page-break-after: avoid; }
section.content > .sec:first-child h2 { margin-top: 0; }
h3 { font-size: 23px; margin: 16px 0 6px; color:#1d5c96; break-after: avoid; page-break-after: avoid; }
p { margin: 8px 0; }
ul, ol { margin: 6px 0; padding-left: 30px; }
ul ul, ol ul { margin: 4px 0; padding-left: 26px; }
ul ul li { font-size: 21px; }
li { margin: 5px 0; }
strong { color:#b3261e; }
em { color:#0f2b46; font-style: normal; border-bottom:1px dotted #999; }
code { font-family: Consolas,monospace; background:#eef2f7; padding:0 4px; border-radius:3px; font-size: 20px; }
blockquote { margin: 12px 0; padding: 10px 14px; background:#fff7e6; border-left:6px solid #f0a500;
  break-inside: avoid; page-break-inside: avoid; }
.tbl { margin: 10px 0; break-inside: avoid; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 18px; }
th, td { border: 1px solid #b9c6d4; padding: 4px 6px; text-align: left; vertical-align: top; line-height:1.4; }
th { background:#e8f0f8; }
.blk { margin: 12px 0; text-align:center; break-inside: avoid; page-break-inside: avoid;
  max-width: 620px; overflow: hidden; }
.blk mjx-container { max-width: 100% !important; }
.blk svg, mjx-container svg { max-width: 100% !important; height: auto !important; }
td mjx-container, th mjx-container, li mjx-container, p mjx-container { max-width: 100% !important; }
"""

JS = "window.addEventListener('load', function(){ \
  if (window.MathJax && MathJax.startup && MathJax.startup.promise) { MathJax.startup.promise.catch(function(){}); } });"


def stamp_page_numbers(pdf_path):
    import pymupdf
    doc = pymupdf.open(pdf_path)
    n = len(doc)
    for i in range(1, n):
        page = doc[i]
        w, h = page.rect.width, page.rect.height
        page.insert_text((w - 50, h - 22), str(i), fontsize=13,
                         fontname="helv", color=(0.42, 0.47, 0.53))
    doc.saveIncr()
    doc.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()

    body, title = build(args.md)
    mj = open(mathjax_source(), encoding="utf-8").read()
    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>%s</title>
<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']],tags:'none'},
 svg:{fontCache:'global'},startup:{}};</script>
<script>%s</script>
<style>%s</style></head><body>%s<script>%s</script></body></html>""" % (
        html.escape(title), mj, CSS, body, JS)

    base = os.path.splitext(args.md)[0]
    out_html = base + "_phone.html"
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
        n = stamp_page_numbers(out_pdf)
        os.remove(out_html)
        print("pages:", n, "size:", os.path.getsize(out_pdf), "bytes")


if __name__ == "__main__":
    main()
