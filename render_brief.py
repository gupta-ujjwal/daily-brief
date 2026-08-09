#!/usr/bin/env python3
"""Render a ranked data.json into the daily-brief magazine HTML.

The model's only job is to add a one-line "gist" and a "category" to each item in
data.json (see the daily-brief skill). This script does the rest deterministically:
groups items into four category sections, renders a 3-tier editorial layout per
section (lead card, secondary card grid, compact tail rows), builds the hero
(brand, tabs, source filter chips), and fills template.html. Keeping layout in
code (not hand-built each run) makes scheduled runs reliable.

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

LEGEND = {  # source key -> short chip label for the filter chips
    "hackernews": "HN",
    "reddit": "Reddit",
    "substack": "Substack",
    "medium": "Medium",
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
            name = LEGEND[key]
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


def lead_block(it):
    """Tier 1: full-width lead card — coral left edge, TOP STORY tag, biggest title."""
    g = it.get("gist", "")
    ai_label = '<span class="ai-tag">AI gist</span>' if g else ""
    gist = f'<p class="gist">{ai_label}{esc(g)}</p>' if g else ""
    return f'''<article class="item lead" data-src="{esc(it['source'])}" data-created="{it.get('created_at', 0)}" data-brief-item>
        <div class="top-row">
          <span class="src-kicker">{esc(it['source_label'])}</span>
          <span style="display:inline-flex;align-items:center;gap:10px">
            <span class="tag">Top story</span>{bookmark_btn(it)}
          </span>
        </div>
        <h2><a href="{esc(it['url'])}">{esc(it['title'])}</a></h2>
        {gist}
        <div class="meta">{meta(it)}</div>
      </article>'''


def story_block(it):
    """Tier 2: secondary grid card — kicker + save button row, serif-free title."""
    g = it.get("gist", "")
    ai_label = '<span class="ai-tag">AI gist</span>' if g else ""
    gist = f'<p class="gist">{ai_label}{esc(g)}</p>' if g else ""
    return f'''<article class="item story" data-src="{esc(it['source'])}" data-created="{it.get('created_at', 0)}" data-brief-item>
        <div class="kicker"><span class="src-kicker">{esc(it['source_label'])}</span>{bookmark_btn(it)}</div>
        <h3><a href="{esc(it['url'])}">{esc(it['title'])}</a></h3>
        {gist}
        <div class="meta">{meta(it)}</div>
      </article>'''


def row_block(it):
    """Tier 3: tail row — [kicker | title | gist] grid, meta full-width under."""
    g = it.get("gist", "")
    ai_label = '<span class="ai-tag">AI gist</span>' if g else ""
    gist = f'<p class="gist">{ai_label}{esc(g)}</p>' if g else ""
    return f'''<article class="item row" data-src="{esc(it['source'])}" data-created="{it.get('created_at', 0)}" data-brief-item>
        <span class="src-kicker">{esc(it['source_label'])}</span>
        <span class="row-title"><a href="{esc(it['url'])}">{esc(it['title'])}</a>{bookmark_btn(it)}</span>
        {gist}
        <div class="meta">{meta(it)}</div>
      </article>'''


def panel_block(key, name, intro, items):
    n = len(items)
    if n == 0:
        return ""
    parts = [lead_block(items[0])]
    secondary = items[1:4]
    tail = items[4:]
    if secondary:
        sec_cards = "\n        ".join(story_block(it) for it in secondary)
        parts.append(f'<div class="grid">\n        {sec_cards}\n        </div>')
    if tail:
        tail_rows = "\n        ".join(row_block(it) for it in tail)
        parts.append(f'<div class="tail">\n        {tail_rows}\n        </div>')
    noun = "story" if n == 1 else "stories"
    parts.append(f'<div class="finish">End of <em>{esc(name)}</em> · {n} {noun}</div>')
    inner = "\n        ".join(parts)
    return f'''<section id="panel-{key}" class="panel">
        <p class="panel-intro">{intro}</p>
        {inner}
      </section>'''


def tabs_block(present):
    """Build (radios_html, labels_html, panels_html) for the template's
    {{TAB_RADIOS}} / {{TAB_LABELS}} / {{PANELS}} placeholders. Keeping the three
    zones separate lets the template pin radios BEFORE the hero (so the CSS-only
    sibling selectors reach both the tabbar and the sheet)."""
    radios, labels, panels = [], [], []
    best_i = max(range(len(present)), key=lambda i: (
        len(present[i][3]), -CATEGORY_PRIORITY.get(present[i][0], 99)))
    for i, (key, name, intro, items) in enumerate(present):
        checked = " checked" if i == best_i else ""
        radios.append(f'<input type="radio" name="brieftab" id="tab-{key}" class="tabinput"{checked}>')
        labels.append(f'<label for="tab-{key}" class="tab tab-{key}">{esc(name)} '
                      f'<span class="n">{len(items)}</span>'
                      f'<span class="new-count" data-tab-key="{key}"></span></label>')
        panels.append(panel_block(key, name, intro, items))
    return ("\n    ".join(radios),
            "\n          ".join(labels),
            "\n      ".join(panels))


def chips_block(d):
    """Source filter chips with counts — one button per source present."""
    counts = d.get("source_counts", {})
    chips = []
    for key, label in LEGEND.items():
        n = counts.get(key, 0)
        if n:
            chips.append(f'<button class="chip" type="button" data-src="{key}">'
                         f'{esc(label)}<span class="n">{n}</span></button>')
    return "\n          ".join(chips)


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

    gen = datetime.datetime.fromtimestamp(d.get("generated_at", 0)).strftime("%d %b %Y, %H:%M")
    radios_html, labels_html, panels_html = tabs_block(present)

    tmpl = open(TEMPLATE).read()
    out = (tmpl
           .replace("{{DATE}}", esc(disp_date))
           .replace("{{GENERATED}}", gen)
           .replace("{{TAB_RADIOS}}", radios_html)
           .replace("{{TAB_LABELS}}", labels_html)
           .replace("{{SOURCE_CHIPS}}", chips_block(d))
           .replace("{{PANELS}}", panels_html)
           .replace("{{PROVENANCE}}", provenance_line(d))
           .replace("{{ROOT}}", esc(args.root_prefix)))
    if rescore_sentinel:
        out = rescore_sentinel + "\n" + out
    if "{{" in out:
        raise SystemExit(f"unfilled placeholder remains in template: "
                         f"{[m for m in out.split('{{')[1:]][:3]}")

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
