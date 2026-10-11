#!/usr/bin/env python3
"""Add (or replace) a weekly edition and rebuild the whole site.

Usage:
    python3 add_edition.py PLAN.md 2026-10-18 [--label "Week of Oct 18–24"] [--no-push]

- Copies PLAN.md to editions/YYYY-MM-DD.md (the source of truth)
- Re-renders every editions/*.html (so prev/next links stay correct)
- Regenerates index.html (archive, newest first)
- Unless --no-push, commits and pushes to origin/main (GitHub Pages redeploys).

Markdown subset: # title, ## sections, ### subsections, numbered and bullet lists,
[text](url) links, **bold**, *italic*, paragraphs. An indented `**Summary:** ...` line
under a list item renders as a closed, native click-to-expand summary block. In list items, a tag written as
", new." or ", from your X saves." / ", from your saves." becomes a badge.
The first '# ' heading is the edition title.
"""
import argparse, datetime as dt, html, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
ED = ROOT / "editions"
SITE = "Weekly AI learning plan"

CSS = (ROOT / "style.css").read_text(encoding="utf-8")

def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: '<a href="%s" rel="noopener">%s</a>' % (m.group(2).replace('"', "%22"), m.group(1)), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r", new\.", ' <span class="badge new">new</span>.', s)
    s = re.sub(r", from your (?:X )?saves\.", ' <span class="badge saves">from your saves</span>.', s)
    return s

def render_md(md):
    out, lst, para = [], None, []
    def flush_p():
        if para: out.append("<p>%s</p>" % inline(" ".join(para))); para.clear()
    def close_l():
        nonlocal lst
        if lst: out.append("</%s>" % lst); lst = None
    for line in md.splitlines():
        t = line.rstrip()
        m = re.match(r"(#{1,3}) (.*)", t)
        if m:
            flush_p(); close_l(); n = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (n, inline(m.group(2)), n)); continue
        m = re.match(r"(\d+)\. (.*)", t)
        if m or t.startswith("- "):
            flush_p(); kind = "ol" if m else "ul"
            if lst != kind: close_l(); out.append("<%s>" % kind); lst = kind
            out.append("<li>%s</li>" % inline(m.group(2) if m else t[2:])); continue
        if lst and (t.startswith("  ") or t.startswith("\t")) and out and out[-1].endswith("</li>"):
            continuation = t.strip()
            if continuation.startswith("**Summary:**"):
                item_html = out[-1][4:-5]
                summary_text = continuation[len("**Summary:**"):].strip()
                out[-1] = ('<li><details class="resource-details">'
                            '<summary class="resource-summary">'
                            '<span class="resource-title">%s</span>'
                            '<span class="disclosure-label disclosure-closed" aria-hidden="true">'
                            '<span class="disclosure-copy">Read summary </span>+</span>'
                            '<span class="disclosure-label disclosure-open" aria-hidden="true">'
                            '<span class="disclosure-copy">Hide summary </span>−</span>'
                            '</summary><div class="summary">'
                            '<span class="summary-kicker">Extended summary</span>'
                            '<p>%s</p></div></details></li>') % (item_html, inline(summary_text))
                continue
        if not t.strip(): flush_p(); close_l(); continue
        close_l(); para.append(t.strip())
    flush_p(); close_l()
    return "\n".join(out)

def title_of(md):
    m = re.search(r"^# (.+)$", md, re.M)
    return m.group(1).strip() if m else "Weekly AI learning plan"

def nice(d):
    return dt.date.fromisoformat(d).strftime("%a, %b %-d, %Y")

def page(title, body, css_prefix, home_prefix):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{css_prefix}style.css">
</head><body>
<header class="site"><a class="brand" href="{home_prefix}index.html">{SITE}</a><a href="{home_prefix}index.html">Archive</a></header>
<main class="page">
{body}
<footer>Static page, no trackers.</footer>
</main></body></html>
"""

def build():
    (ROOT / "style.css").write_text(CSS.strip() + "\n", encoding="utf-8")
    dates = sorted(p.stem for p in ED.glob("*.md"))
    for i, d in enumerate(dates):
        md = (ED / f"{d}.md").read_text(encoding="utf-8")
        older = dates[i - 1] if i > 0 else None
        newer = dates[i + 1] if i + 1 < len(dates) else None
        prev = f'<a class="prev" href="{older}.html">&larr; Previous<br><small>{nice(older)}</small></a>' if older else '<span class="ph"></span>'
        nxt = f'<a class="next" href="{newer}.html">Next &rarr;<br><small>{nice(newer)}</small></a>' if newer else '<span class="ph"></span>'
        body = f'<p class="edition-meta">Edition of {nice(d)}</p>\n{render_md(md)}\n<nav class="pn" aria-label="Edition navigation">{prev}{nxt}</nav>'
        (ED / f"{d}.html").write_text(page(f"{title_of(md)} – {SITE}", body, "../", "../"), encoding="utf-8")
    items = "\n".join(
        f'<li><a href="editions/{d}.html">{html.escape(title_of((ED / f"{d}.md").read_text(encoding="utf-8")))}'
        f'<small>{nice(d)}</small></a></li>' for d in reversed(dates))
    body = f'<p class="edition-meta">Archive</p>\n<h1>{SITE}</h1>\n<p class="site-intro">Weekly editions, newest first. Must Watch picks plus agents, investing and product reading, planned around about 10 hours a week.</p>\n<ul class="idx">\n{items}\n</ul>'
    (ROOT / "index.html").write_text(page(SITE, body, "", ""), encoding="utf-8")
    (ROOT / ".nojekyll").write_text("")
    return dates

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown", nargs="?", help="markdown file for the new edition")
    ap.add_argument("date", nargs="?", help="edition date YYYY-MM-DD")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    ED.mkdir(exist_ok=True)
    if a.markdown:
        if not a.date: sys.exit("date required")
        dt.date.fromisoformat(a.date)
        dest = ED / f"{a.date}.md"
        if pathlib.Path(a.markdown).resolve() != dest.resolve():
            shutil.copyfile(a.markdown, dest)
    dates = build()
    print("Built %d edition(s): %s" % (len(dates), ", ".join(dates)))
    if a.markdown and not a.no_push:
        run = lambda *c: subprocess.run(c, cwd=ROOT, check=True)
        run("git", "add", "-A")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
            run("git", "commit", "-m", f"Add edition {a.date}")
        run("git", "push", "origin", "HEAD:main")

if __name__ == "__main__":
    main()
