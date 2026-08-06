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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, ".claude", "skills", "daily-brief", "template.html")
SOURCES = os.path.join(HERE, "sources.json")

LEGEND = {  # source key -> (legend dot class, display name)
    "hackernews": ("hn", "Hacker News"),
    "reddit": ("reddit", "Reddit"),
    "substack": ("substack", "Substack"),
    "medium": ("medium", "Medium"),
}

# Per-source served tier -> short human label for the provenance footer. Tiers not
# listed (e.g. "front-page" for HN) are treated as generic and not shown.
TIER_LABELS = {
    "home-oauth": "your home feed", "home-rss": "your home RSS",
    "public": "generic subreddits (fallback)",
    "inbox": "your inbox", "subscriptions": "your subscriptions",
    "feeds": "curated list (fallback)",
    "follows": "your follows", "graphql": "your For-you",
}


def provenance_line(d):
    """A one-line 'where each personal source came from' note for the footer, so a
    silently-degraded feed (e.g. Reddit fell back to generic subreddits) is visible
    in the brief itself rather than buried in logs."""
    prov = d.get("provenance") or {}
    parts = []
    for key in ("reddit", "substack", "medium"):
        tier = prov.get(key)
        if tier and tier in TIER_LABELS:
            _, name = LEGEND[key]
            parts.append(f"{name}: {TIER_LABELS[tier]}")
    if not parts:
        return ""
    cls = "provenance degraded" if d.get("degraded") else "provenance"
    body = " · ".join(parts)
    warn = " — refresh your cookies/tokens" if d.get("degraded") else ""
    return f'<div class="{cls}">Personalized from — {esc(body)}{warn}</div>'

# category key -> (tab name, one-line intro). Order = tab order.
CATEGORIES = [
    ("industry", "The Wire", "What's moving across the industry — funding, deals, launches and power plays."),
    ("learning", "Deep Dives", "Essays, ideas and new tech worth slowing down to understand."),
    ("products", "Worth a Try", "Products, repos and apps to look out for and actually use."),
    ("personal", "Off the Clock", "Your world beyond tech — local, hobby and the rest of your personal feed."),
]
DEFAULT_CATEGORY = "industry"

# Tie-break order for fullest-tab selection: first category wins on equal counts.
CATEGORY_PRIORITY = {key: i for i, (key, _, _) in enumerate(CATEGORIES)}

# Populated by rescore_by_category() if it skips; emitted as an HTML comment
# so a silent ranking degradation is visible in the page source.
rescore_sentinel = ""


def esc(s):
    return html.escape(s or "")


def rescore_by_category(items):
    """Apply per-category weights after gists/categories are assigned, then
    recompute feed_score and re-sort items in-place. Reads
    ranking.category_weights from sources.json. Fail-safe: on any error, sets a
    sentinel comment and leaves scores untouched."""
    global rescore_sentinel
    try:
        with open(SOURCES) as f:
            cfg = json.load(f)
        weights = cfg.get("ranking", {}).get("category_weights", {})
        if not weights:
            rescore_sentinel = "<!-- rescoring-skipped: no category_weights in sources.json -->"
            return
    except Exception as e:
        rescore_sentinel = f"<!-- rescoring-skipped: {esc(str(e))} -->"
        print(f"  rescore: skipped — {e}", file=sys.stderr)
        return
    for it in items:
        cat = it.get("category", DEFAULT_CATEGORY)
        w = weights.get(cat, 1.0)
        it["rank_score"] = round(it.get("rank_score", 0) * w, 4)
    top = max((it.get("rank_score", 0) for it in items), default=1.0) or 1.0
    for it in items:
        it["feed_score"] = round(it.get("rank_score", 0) / top, 4)
    items.sort(key=lambda x: x.get("rank_score", 0), reverse=True)


# Outline bookmark icon; CSS fills it when the card is saved.
BOOKMARK_SVG = ('<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">'
                '<path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"/></svg>')


def bookmark_btn(it):
    """A per-card save button carrying the story's data so the client can persist
    it to localStorage without re-deriving anything. Keyed by url (or discuss_url)."""
    key = it.get("url") or it.get("discuss_url") or ""
    data = {
        "data-url": key,
        "data-title": it.get("title") or "",
        "data-source": it.get("source") or "",
        "data-label": it.get("source_label") or "",
        "data-gist": it.get("gist") or "",
        "data-cat": it.get("category") or "",
        "data-discuss": it.get("discuss_url") or key,
    }
    attrs = " ".join(f'{k}="{esc(v)}"' for k, v in data.items())
    return (f'<button class="bm-btn" type="button" aria-label="Save to bookmarks" '
            f'title="Save" {attrs}>{BOOKMARK_SVG}</button>')


def relative_date(ts):
    """Turn an epoch timestamp into a relative date string."""
    if not ts:
        return ""
    now = datetime.datetime.now().timestamp()
    diff = now - ts
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    if diff < 604800:
        return f"{int(diff / 86400)}d ago"
    dt = datetime.datetime.fromtimestamp(ts)
    if dt.year == datetime.datetime.now().year:
        return dt.strftime("%b %d")
    return dt.strftime("%b %Y")


def reading_time(it):
    """Rough reading-time estimate from available text length."""
    text = (it.get("text") or "")
    comments = it.get("comments") or []
    for c in comments:
        text += " " + (c.get("text") or "")
    words = len(text.split())
    if words < 50:
        return ""
    mins = max(1, round(words / 200))
    return f"{mins} min read"


def meta(it):
    s = it.get("source")
    parts = []
    if s == "hackernews":
        parts.append(f"▲ {it.get('points', 0)} · {it.get('num_comments', 0)} comments")
        link = "discuss →"
    elif s == "reddit":
        if it.get("num_comments"):
            parts.append(f"{it['num_comments']} comments")
        link = "discuss →" if it.get("kind") == "ask" else "open →"
    else:
        if it.get("author"):
            parts.append(esc(it["author"]))
        link = "read →"
    rd = relative_date(it.get("created_at", 0))
    if rd:
        parts.append(f'<span class="date">{rd}</span>')
    rt = reading_time(it)
    if rt:
        parts.append(f'<span class="rtime">{rt}</span>')
    if it.get("also_on"):
        also = ", ".join(sorted(set(it["also_on"])))
        parts.append(f'<span class="also">also on {esc(also)}</span>')
    a = f'<a href="{esc(it.get("discuss_url"))}">{link}</a>'
    inner = " · ".join(p for p in parts if p)
    return f"{inner} · {a}" if inner else a


def card_block(it, lead=False):
    g = it.get("gist", "")
    ai_label = '<span class="ai-tag">AI gist</span>' if g else ""
    gist = f'<p class="card-gist">{ai_label}{esc(g)}</p>' if g else ""
    cls = "card lead" if lead else "card"
    right = '<span class="lead-tag">Top</span>' if lead else ""
    return f'''<article class="{cls} src-{it['source']}" data-created="{it.get('created_at', 0)}" data-brief-item>
        <div class="kicker"><span class="badge">{esc(it['source_label'])}</span>
          <span class="kicker-r">{right}{bookmark_btn(it)}</span></div>
        <a class="card-title" href="{esc(it['url'])}">{esc(it['title'])}</a>
        {gist}
        <div class="meta">{meta(it)}</div>
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
    best_i = max(range(len(present)), key=lambda i: (
        len(present[i][3]), -CATEGORY_PRIORITY.get(present[i][0], 99)))
    for i, (key, name, intro, items) in enumerate(present):
        checked = " checked" if i == best_i else ""
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

    rescore_by_category(items)

    today = datetime.date.today()
    disp_date = args.date or today.strftime("%-d %B %Y")
    out_path = args.out or os.path.join(HERE, "briefs", f"{today.isoformat()}.html")

    # Group into category buckets, preserving the global rank order within each.
    valid = {key for key, _, _ in CATEGORIES}
    buckets = {key: [] for key in valid}
    for it in items:
        cat = it.get("category")
        buckets[cat if cat in valid else DEFAULT_CATEGORY].append(it)
    # Merge sparse tabs: products (< 4 items) folds into learning; personal is
    # exempt (it's a coda tab — a thin personal section is fine).
    if len(buckets.get("products", [])) < 4:
        buckets["learning"].extend(buckets["products"])
        del buckets["products"]
    present = [(key, name, intro, buckets[key])
               for key, name, intro in CATEGORIES if buckets.get(key)]
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
           .replace("{{PROVENANCE}}", provenance_line(d))
           .replace("{{ROOT}}", esc(args.root_prefix))
           .replace("{{SECTIONS}}", tabs))
    if rescore_sentinel:
        out = rescore_sentinel + "\n" + out
    if "{{" in out:
        raise SystemExit("unfilled placeholder remains in template")

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(out)
    os.replace(tmp_path, out_path)
    print(f"wrote {out_path}: {len(items)} items, {len(out)} bytes")


if __name__ == "__main__":
    main()
