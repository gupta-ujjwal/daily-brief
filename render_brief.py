#!/usr/bin/env python3
"""Render a ranked data.json into the daily-brief magazine HTML.

The model's only job is to add a one-line "gist" and a "category" to each item in
data.json (see the daily-brief skill). This script does the rest deterministically:
groups items into four category sections, renders a 3-tier editorial layout per
section (lead card, secondary card grid, compact tail rows), builds the hero
(brand, tabs, source filter chips, time-budget control), and fills template.html.
Keeping layout in code (not hand-built each run) makes scheduled runs reliable.

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

# Tie-break order for tab selection: first category wins on equal counts.
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


# Seconds a reader spends deciding on one story (headline + gist + judgement).
# Used only for the aggregate "~N min to skim" figure, never per-item — a
# per-item number derived from fetched excerpts is what made the old one fake.
SECS_PER_STORY = 10

BOOKMARK_SVG = ('<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">'
                '<path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"/></svg>')


def save_btn(it, small=False):
    """Labelled save control — 40px target, visible pressed state, same
    localStorage payload as the production template so saved data is portable."""
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
    cls = "btn bm-btn" + (" btn-sm" if small else "")
    return (f'<button class="{cls}" type="button" aria-pressed="false" {attrs}>'
            f'{BOOKMARK_SVG}<span class="bm-label">Save</span></button>')


def read_label(it, lead=False):
    src = it.get("source")
    if src == "reddit" and (it.get("kind") == "ask" or not it.get("url")):
        return "Open the thread" if lead else "Open"
    if src in ("substack", "medium"):
        return "Read the post" if lead else "Read"
    return "Read the story" if lead else "Read"


def actions(it, lead=False):
    """Read / Discuss / Save — labelled, never hover-only, so touch works."""
    small = not lead
    url = it.get("url") or it.get("discuss_url") or ""
    disc = it.get("discuss_url") or ""
    sm = " btn-sm" if small else ""
    parts = [f'<a class="btn btn-primary{sm}" href="{esc(url)}">{read_label(it, lead)} →</a>']
    if disc and disc != url:
        n = it.get("num_comments") or 0
        label = f"{n} comments" if n else "Discuss"
        parts.append(f'<a class="btn{sm}" href="{esc(disc)}">{esc(label)}</a>')
    parts.append(save_btn(it, small))
    return '<div class="actions">' + "".join(parts) + "</div>"


def meta(it):
    """Signal only — score, volume, recency. No fabricated reading time, and no
    action links (those moved into the action row where they are legible)."""
    parts = []
    s = it.get("source")
    if s == "hackernews":
        parts.append(f"▲ {it.get('points', 0)}")
        if it.get("num_comments"):
            parts.append(f"{it['num_comments']} comments")
    elif s == "reddit":
        if it.get("num_comments"):
            parts.append(f"{it['num_comments']} comments")
    elif it.get("author"):
        parts.append(esc(it["author"]))
    rd = relative_date(it.get("created_at", 0))
    if rd:
        parts.append(rd)
    if it.get("also_on"):
        also = ", ".join(sorted(set(it["also_on"])))
        parts.append(f'<span class="also">also on {esc(also)}</span>')
    return " · ".join(p for p in parts if p)


def gist_p(it):
    g = it.get("gist", "")
    if not g:
        return ""
    glyph = '<span class="gm" title="AI-written summary" aria-hidden="true">&#10022;</span>'
    return f'<p class="gist">{glyph}{esc(g)}</p>'


def item_attrs(it, rank):
    return (f'data-src="{esc(it["source"])}" data-created="{it.get("created_at", 0)}" '
            f'data-rank="{rank}" data-brief-item')


def why_top(it):
    """Say what earned the lead slot instead of an unexplained 'TOP STORY'."""
    if it.get("num_comments", 0) >= 100:
        return f"Top story · most discussed"
    if it.get("points", 0) >= 200:
        return f"Top story · {it['points']} points"
    return "Top story"


def lead_block(it, rank):
    return f'''<article class="item lead" {item_attrs(it, rank)}>
        <div class="top-row">
          <span class="src-kicker">{esc(it['source_label'])}</span>
          <span class="tag">{esc(why_top(it))}</span>
        </div>
        <h2><a href="{esc(it['url'])}">{esc(it['title'])}</a></h2>
        {gist_p(it)}
        <div class="meta">{meta(it)}</div>
        {actions(it, lead=True)}
      </article>'''


def story_block(it, rank):
    return f'''<article class="item story" {item_attrs(it, rank)}>
        <span class="src-kicker">{esc(it['source_label'])}</span>
        <h3><a href="{esc(it['url'])}">{esc(it['title'])}</a></h3>
        {gist_p(it)}
        <div class="meta">{meta(it)}</div>
        {actions(it)}
      </article>'''


def row_block(it, rank):
    """Title hard-left where the eye lands; source demoted into the meta line."""
    return f'''<article class="item row" {item_attrs(it, rank)}>
        <div class="row-main">
          <h4 class="row-title"><a href="{esc(it['url'])}">{esc(it['title'])}</a></h4>
          {gist_p(it)}
          <div class="meta"><span class="src-kicker">{esc(it['source_label'])}</span>{' · ' + meta(it) if meta(it) else ''}</div>
        </div>
        {actions(it)}
      </article>'''


def done_block(name, n):
    noun = "story" if n == 1 else "stories"
    return f'''<div class="done">
          <p class="done-h">You're caught up.</p>
          <p class="done-sub"><b class="doneCount">{n}</b> <span class="doneNoun">{noun}</span> in {esc(name)} · <b class="doneSaved">0</b> saved today</p>
          <div class="actions">
            <button class="btn" type="button" data-open-saved>Review what you saved</button>
            <a class="btn" href="{{{{ROOT}}}}archive.html">Earlier editions</a>
          </div>
          <p class="done-next">Next edition tomorrow, 8:00</p>
        </div>'''


def panel_block(key, name, intro, items):
    n = len(items)
    if n == 0:
        return ""
    parts = [
        '<p class="trim" hidden><span class="trim-text"></span>'
        '<button type="button" data-show-all>Show everything →</button></p>',
        lead_block(items[0], 0),
    ]
    secondary = items[1:4]
    tail = items[4:]
    if secondary:
        cards = "\n        ".join(story_block(it, i + 1) for i, it in enumerate(secondary))
        parts.append(f'<div class="grid">\n        {cards}\n        </div>')
    if tail:
        rows = "\n        ".join(row_block(it, i + 4) for i, it in enumerate(tail))
        parts.append(f'<div class="tail">\n        {rows}\n        </div>')
    parts.append(done_block(name, n))
    inner = "\n        ".join(parts)
    return f'''<section id="panel-{key}" class="panel">
        <p class="panel-intro">{intro}</p>
        {inner}
      </section>'''


def tabs_block(present):
    """Build (radios_html, labels_html, panels_html) for the template's
    {{TAB_RADIOS}} / {{TAB_LABELS}} / {{PANELS}} placeholders. Keeping the three
    zones separate lets the template pin radios BEFORE the hero (so the CSS-only
    sibling selectors reach both the topbar and the sheet).

    Default tab = editorial priority (The Wire first), NOT the fullest bucket.
    The counts on each pill already tell the reader where the volume is."""
    best_i = min(range(len(present)),
                 key=lambda i: CATEGORY_PRIORITY.get(present[i][0], 99))
    radios, labels, panels = [], [], []
    for i, (key, name, intro, items) in enumerate(present):
        checked = " checked" if i == best_i else ""
        radios.append(f'<input type="radio" name="brieftab" id="tab-{key}" class="tabinput"{checked}>')
        labels.append(f'<label for="tab-{key}" class="tab tab-{key}">{esc(name)} '
                      f'<span class="n">{len(items)}</span>'
                      f'<span class="new-count" data-tab-key="{key}"></span></label>')
        panels.append(panel_block(key, name, intro, items))
    return ("\n  ".join(radios),
            "\n        ".join(labels),
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


def skim_minutes(items):
    """Honest aggregate: seconds-per-story * stories, rounded to minutes."""
    return max(1, round(len(items) * SECS_PER_STORY / 60))


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
    weekday_date = today.strftime("%A, %-d %B %Y")
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
           .replace("{{WEEKDAY_DATE}}", esc(weekday_date))
           .replace("{{GENERATED}}", gen)
           .replace("{{TAB_RADIOS}}", radios_html)
           .replace("{{TAB_LABELS}}", labels_html)
           .replace("{{SOURCE_CHIPS}}", chips_block(d))
           .replace("{{PANELS}}", panels_html)
           .replace("{{TOTAL_STORIES}}", str(len(items)))
           .replace("{{TOTAL_MINS}}", str(skim_minutes(items)))
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
