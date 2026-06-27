#!/usr/bin/env python3
"""Render a ranked data.json into the daily-brief magazine HTML.

The model's only job is to add a one-line "gist" and a "category" to each item in
data.json (see the daily-brief skill). This script does the rest deterministically:
groups items into the three category sections, renders a lead card + card grid per
section (ranked within), builds source badges and score meters, and fills
template.html. Keeping layout in code (not hand-built each run) makes scheduled
runs reliable.

    python3 render_brief.py --data data.json --date "25 June 2026" \
        --out briefs/2026-06-25.html
"""
import argparse
import datetime
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, ".claude", "skills", "daily-brief", "template.html")

LEGEND = {  # source key -> (legend dot class, display name)
    "hackernews": ("hn", "Hacker News"),
    "reddit": ("reddit", "Reddit"),
    "substack": ("substack", "Substack"),
}

# category key -> (tab name, one-line intro). Order = tab order.
CATEGORIES = [
    ("industry", "The Wire", "What's moving across the industry — funding, deals, launches and power plays."),
    ("learning", "Deep Dives", "Essays, ideas and new tech worth slowing down to understand."),
    ("products", "Worth a Try", "Products, repos and apps to look out for and actually use."),
]
DEFAULT_CATEGORY = "industry"


def esc(s):
    return html.escape(s or "")


def meta(it):
    s = it.get("source")
    parts = []
    if s == "hackernews":
        parts.append(f"{it.get('points', 0)} pts · {it.get('num_comments', 0)} comments")
        link = "discuss →"
    elif s == "reddit":
        if it.get("num_comments"):
            parts.append(f"{it['num_comments']} comments")
        link = "discuss →" if it.get("kind") == "ask" else "open →"
    else:
        if it.get("author"):
            parts.append(esc(it["author"]))
        link = "read →"
    if it.get("also_on"):
        also = ", ".join(sorted(set(it["also_on"])))
        parts.append(f'<span class="also">also on {esc(also)}</span>')
    a = f'<a href="{esc(it.get("discuss_url"))}">{link}</a>'
    inner = " · ".join(p for p in parts if p)
    return f"{inner} · {a}" if inner else a


def width(it):
    return round(float(it.get("feed_score", 0)) * 100)


def card_block(it, lead=False):
    g = it.get("gist", "")
    gist = f'<p class="card-gist">{esc(g)}</p>' if g else ""
    cls = "card lead" if lead else "card"
    right = '<span class="lead-tag">Top</span>' if lead else ""
    return f'''<article class="{cls} src-{it['source']}">
        <div class="kicker"><span class="badge">{esc(it['source_label'])}</span>{right}</div>
        <a class="card-title" href="{esc(it['url'])}">{esc(it['title'])}</a>
        {gist}
        <div class="meta">{meta(it)}</div>
        <div class="meter"><span style="width:{width(it)}%"></span></div>
      </article>'''


def panel_block(key, intro, items):
    cards = [card_block(it, lead=(i == 0)) for i, it in enumerate(items)]
    cards_html = "\n        ".join(cards)
    return f'''<section id="panel-{key}" class="panel">
        <p class="panel-intro">{intro}</p>
        <div class="grid">
        {cards_html}
        </div>
      </section>'''


def tabs_block(present):
    """present = list of (key, name, intro, items) for non-empty categories."""
    radios, labels, panels = [], [], []
    for i, (key, name, intro, items) in enumerate(present):
        checked = " checked" if i == 0 else ""
        radios.append(f'<input type="radio" name="brieftab" id="tab-{key}" class="tabinput"{checked}>')
        labels.append(f'<label for="tab-{key}" class="tab tab-{key}">{name} '
                      f'<span class="count">{len(items)}</span></label>')
        panels.append(panel_block(key, intro, items))
    return (f'<div class="tabs">\n      '
            + "\n      ".join(radios)
            + '\n      <nav class="tabbar">\n        '
            + "\n        ".join(labels)
            + '\n      </nav>\n      '
            + "\n      ".join(panels)
            + '\n    </div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "data.json"))
    ap.add_argument("--out", help="output HTML path (default briefs/<date>.html)")
    ap.add_argument("--date", help="display date, e.g. '25 June 2026'")
    ap.add_argument("--root-prefix", default="",
                    help="relative path to the site root for links (e.g. '../' for files in briefs/)")
    args = ap.parse_args()

    with open(args.data) as f:
        d = json.load(f)
    items = d.get("items", [])
    if not items:
        raise SystemExit("no items in data.json — nothing to render")

    today = datetime.date.today()
    disp_date = args.date or today.strftime("%-d %B %Y")
    out_path = args.out or os.path.join(HERE, "briefs", f"{today.isoformat()}.html")

    # Group into category buckets, preserving the global rank order within each.
    valid = {key for key, _, _ in CATEGORIES}
    buckets = {key: [] for key in valid}
    for it in items:
        cat = it.get("category")
        buckets[cat if cat in valid else DEFAULT_CATEGORY].append(it)
    present = [(key, name, intro, buckets[key])
               for key, name, intro in CATEGORIES if buckets[key]]
    tabs = tabs_block(present)

    legend = []
    for key, (cls, name) in LEGEND.items():
        n = d.get("source_counts", {}).get(key, 0)
        if n:
            legend.append(f'<span><i class="{cls}"></i>{name} · {n}</span>')

    gen = datetime.datetime.fromtimestamp(d.get("generated_at", 0)).strftime("%d %b %Y, %H:%M")
    tmpl = open(TEMPLATE).read()
    out = (tmpl
           .replace("{{DATE}}", esc(disp_date))
           .replace("{{GENERATED}}", gen)
           .replace("{{SOURCE_LEGEND}}", "\n        ".join(legend))
           .replace("{{ROOT}}", esc(args.root_prefix))
           .replace("{{SECTIONS}}", tabs))
    if "{{" in out:
        raise SystemExit("unfilled placeholder remains in template")

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(out)
    print(f"wrote {out_path}: {len(items)} items, {len(out)} bytes")


if __name__ == "__main__":
    main()
