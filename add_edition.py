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
under a list item renders as a muted summary block. In list items, a tag written as
", new." or ", from your X saves." / ", from your saves." becomes a badge.
The first '# ' heading is the edition title.
"""
import argparse, datetime as dt, html, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
ED = ROOT / "editions"
SITE = "Weekly AI learning plan"

CSS = """
:root{color-scheme:light dark;--bg:#fafaf9;--fg:#1c1917;--muted:#6b6560;--card:#fff;--line:#e7e5e4;--accent:#2563eb;--new:#15803d;--newbg:#dcfce7;--save:#a16207;--savebg:#fef3c7}
@media(prefers-color-scheme:dark){:root{--bg:#121110;--fg:#ecebe9;--muted:#a09a94;--card:#1b1a19;--line:#2c2a28;--accent:#7aa7ff;--new:#86efac;--newbg:#14391f;--save:#fde68a;--savebg:#3d2f08}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:46rem;margin:0 auto;padding:1.25rem 1rem 4rem}
header.site{max-width:46rem;margin:0 auto;padding:1rem 1rem 0;display:flex;justify-content:space-between;gap:1rem;font-size:.95rem}
header.site a{color:var(--muted);text-decoration:none;font-weight:600}
a{color:var(--accent)}
h1{font-size:1.75rem;line-height:1.25;margin:.5rem 0 1rem}
h2{font-size:1.25rem;margin:2.2rem 0 .6rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
h3{font-size:1.05rem;margin:1.5rem 0 .4rem}
ul,ol{padding:0;margin:.5rem 0;list-style:none}
li{background:var(--card);border:1px solid var(--line);border-radius:.6rem;padding:.7rem .9rem;margin:.55rem 0}
ol{counter-reset:n}ol>li{counter-increment:n;padding-left:2.6rem;position:relative}
ol>li::before{content:counter(n);position:absolute;left:.8rem;top:.7rem;font-weight:700;color:var(--muted)}
.badge{display:inline-block;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;border-radius:999px;padding:.05rem .55rem;vertical-align:.1em}
.badge.new{color:var(--new);background:var(--newbg)}.badge.saves{color:var(--save);background:var(--savebg)}
nav.pn{display:flex;justify-content:space-between;gap:1rem;margin:2.5rem 0 0;font-size:.95rem}
nav.pn a{flex:1;border:1px solid var(--line);background:var(--card);border-radius:.6rem;padding:.6rem .8rem;text-decoration:none}
nav.pn a.next{text-align:right}nav.pn span.ph{flex:1}
.idx li{padding:0}.idx li a{display:block;padding:.8rem .9rem;text-decoration:none;color:var(--fg)}
.idx small{display:block;color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;margin-top:3rem}
.summary{display:block;color:var(--muted);font-size:.93em;line-height:1.5;margin-top:.45rem}
"""

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
                out[-1] = out[-1][:-5] + '<span class="summary">%s</span></li>' % inline(continuation)
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
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{css_prefix}style.css">
</head><body>
<header class="site"><a href="{home_prefix}index.html">{SITE}</a><a href="{home_prefix}index.html">Archive</a></header>
<main>
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
        body = f'<p class="muted" style="color:var(--muted);margin:0">Edition of {nice(d)}</p>\n{render_md(md)}\n<nav class="pn">{prev}{nxt}</nav>'
        (ED / f"{d}.html").write_text(page(f"{title_of(md)} – {SITE}", body, "../", "../"), encoding="utf-8")
    items = "\n".join(
        f'<li><a href="editions/{d}.html">{html.escape(title_of((ED / f"{d}.md").read_text(encoding="utf-8")))}'
        f'<small>{nice(d)}</small></a></li>' for d in reversed(dates))
    body = f'<h1>{SITE}</h1>\n<p>Weekly editions, newest first. Must Watch picks plus agents, investing and product reading, planned around about 10 hours a week.</p>\n<ul class="idx">\n{items}\n</ul>'
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
