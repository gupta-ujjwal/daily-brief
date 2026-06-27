#!/usr/bin/env python3
"""Generate archive.html at the repo root: a dated list of every brief.

Globs briefs/*.html and writes a small, self-contained index linking to each
day, newest first. Matches the brief's dark editorial styling. Run after a new
brief is rendered.

    python3 automation/gen_archive.py
"""
import datetime
import glob
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})\.html$")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Brief · Archive</title>
<style>
  :root {{ --bg:#100f0c; --panel:#18160f; --ink:#f0ebdd; --ink-dim:#cfc8b6;
    --muted:#8d8676; --line:#2a271e; --accent:#ff8c42; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.6 -apple-system,"Segoe UI",Roboto,system-ui,sans-serif;
    background-image:radial-gradient(900px 500px at 85% -10%,rgba(255,140,66,.10),transparent 60%);
    background-attachment:fixed; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:48px 24px 80px; }}
  .eyebrow {{ font:600 12px/1 ui-monospace,Menlo,monospace; text-transform:uppercase;
    letter-spacing:.16em; color:var(--accent); }}
  h1 {{ font:800 40px/1.05 Georgia,serif; letter-spacing:-.025em; margin:12px 0 6px; }}
  .sub {{ color:var(--muted); margin:0 0 28px; }}
  .sub a {{ color:var(--accent); text-decoration:none; }}
  ol {{ list-style:none; margin:0; padding:0; }}
  li a {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px;
    text-decoration:none; color:var(--ink); padding:16px 18px; border:1px solid var(--line);
    border-radius:12px; background:var(--panel); margin-bottom:10px; transition:border-color .15s; }}
  li a:hover {{ border-color:color-mix(in srgb,var(--accent) 55%,var(--line)); }}
  .d {{ font:700 17px/1.2 Georgia,serif; }}
  .iso {{ font:600 12px/1 ui-monospace,monospace; color:var(--muted); }}
  footer {{ color:var(--muted); font:12px/1.5 ui-monospace,monospace; margin-top:36px; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="eyebrow">Daily Brief</div>
    <h1>Archive</h1>
    <p class="sub">{count} editions · <a href="index.html">latest →</a></p>
    <ol>
      {rows}
    </ol>
    <footer>Updated {updated}</footer>
  </div>
</body>
</html>
"""


def main():
    entries = []
    for path in glob.glob(os.path.join(HERE, "briefs", "*.html")):
        m = DATE_RE.search(os.path.basename(path))
        if not m:
            continue
        iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        entries.append((iso, d))
    entries.sort(reverse=True)

    rows = "\n      ".join(
        f'<li><a href="briefs/{iso}.html"><span class="d">{d.strftime("%A, %-d %B %Y")}</span>'
        f'<span class="iso">{iso}</span></a></li>'
        for iso, d in entries
    ) or '<li style="color:var(--muted)">No briefs yet.</li>'

    updated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    html = PAGE.format(count=len(entries), rows=rows, updated=updated)
    out = os.path.join(HERE, "archive.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}: {len(entries)} editions")


if __name__ == "__main__":
    main()
