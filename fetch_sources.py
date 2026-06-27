#!/usr/bin/env python3
"""Fetch and rank today's best tech reading from multiple platforms.

Pulls from Hacker News (Algolia API), Reddit (public JSON), and a curated list
of Substack newsletters (RSS), normalizes each platform's signals onto a common
0..1 scale, then merges everything into a SINGLE ranked feed.

Config lives in sources.json (subreddits, Substack feeds, ranking weights).
Output is a compact data.json the daily-brief skill turns into HTML. Each item
carries enough context (top comments / excerpt) to write a one-line gist with no
extra fetches. Sources fail independently: a dead feed never sinks the brief.
"""
import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "daily-brief/2.0 (personal tech digest; +https://news.ycombinator.com)"}
ALGOLIA = "https://hn.algolia.com/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))


def get(url, parse="json", retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            if parse == "json":
                return json.loads(raw)
            return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503) and attempt < retries:
                time.sleep(2 + 2 * attempt)  # 2s, 4s — bounded backoff
                continue
            raise
    raise last


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def norm_url(url):
    """Canonical key for dedup: host + path, sans scheme/query/trailing slash."""
    if not url:
        return None
    try:
        p = urllib.parse.urlparse(url)
        host = (p.netloc or "").lower().lstrip("www.")
        path = (p.path or "").rstrip("/")
        return f"{host}{path}" or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Hacker News (Algolia)
# --------------------------------------------------------------------------- #
def hn_search(tags, since_ts, hits=40):
    params = urllib.parse.urlencode(
        {"tags": tags, "numericFilters": f"created_at_i>{since_ts}", "hitsPerPage": hits}
    )
    return get(f"{ALGOLIA}/search?{params}").get("hits", [])


def hn_comments(story_id, limit=5, max_len=400):
    try:
        item = get(f"{ALGOLIA}/items/{story_id}")
    except Exception:
        return []
    out = []
    for c in item.get("children") or []:
        if not c or not c.get("text"):
            continue
        txt = strip_html(c["text"])
        if len(txt) < 40:
            continue
        out.append({"author": c.get("author"), "text": txt[:max_len]})
    out.sort(key=lambda c: len(c["text"]), reverse=True)
    return out[:limit]


def fetch_hackernews(cfg, since):
    items = []
    seen = set()  # an Ask/Show post can also hit the front page — keep it once
    stories = hn_search("front_page", since, hits=50)
    stories.sort(key=lambda h: h.get("points") or 0, reverse=True)
    for h in stories[: cfg.get("top", 14)]:
        sid = h.get("objectID")
        seen.add(sid)
        items.append({
            "source": "hackernews", "source_label": "Hacker News", "kind": "link",
            "title": h.get("title"), "url": h.get("url"),
            "discuss_url": f"https://news.ycombinator.com/item?id={sid}",
            "points": h.get("points") or 0, "num_comments": h.get("num_comments") or 0,
            "author": h.get("author"), "text": strip_html(h.get("story_text")),
            "created_at": h.get("created_at_i") or 0,
            "comments": hn_comments(sid) if (h.get("num_comments") or 0) else [],
        })
    if cfg.get("include_ask", True):
        asks = hn_search("ask_hn", since, hits=40)
        asks.sort(key=lambda h: h.get("points") or 0, reverse=True)
        for h in [a for a in asks if a.get("objectID") not in seen][: cfg.get("ask", 6)]:
            sid = h.get("objectID")
            seen.add(sid)
            items.append({
                "source": "hackernews", "source_label": "Ask HN", "kind": "ask",
                "title": h.get("title"),
                "url": f"https://news.ycombinator.com/item?id={sid}",
                "discuss_url": f"https://news.ycombinator.com/item?id={sid}",
                "points": h.get("points") or 0, "num_comments": h.get("num_comments") or 0,
                "author": h.get("author"), "text": strip_html(h.get("story_text")),
                "created_at": h.get("created_at_i") or 0,
                "comments": hn_comments(sid) if (h.get("num_comments") or 0) else [],
            })
    if cfg.get("include_show", True):
        shows = hn_search("show_hn", since, hits=40)
        shows.sort(key=lambda h: h.get("points") or 0, reverse=True)
        for h in [s for s in shows if s.get("objectID") not in seen][: cfg.get("show", 6)]:
            sid = h.get("objectID")
            seen.add(sid)
            # Show HN posts link to the project; fall back to the thread if none.
            url = h.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            items.append({
                "source": "hackernews", "source_label": "Show HN", "kind": "show",
                "title": h.get("title"), "url": url,
                "discuss_url": f"https://news.ycombinator.com/item?id={sid}",
                "points": h.get("points") or 0, "num_comments": h.get("num_comments") or 0,
                "author": h.get("author"), "text": strip_html(h.get("story_text")),
                "created_at": h.get("created_at_i") or 0,
                "comments": hn_comments(sid) if (h.get("num_comments") or 0) else [],
            })
    return items


# --------------------------------------------------------------------------- #
# Reddit (public RSS — the .json API is widely IP-blocked / 403)
#
# top/.rss is ranked by score, so feed position seeds candidates. Each post's
# own comments RSS then tells us whether it has real discussion: we keep only
# posts with >= min_comments, attach the top comments (for a real gist), and use
# the comment count as the engagement signal for cross-platform ranking.
# --------------------------------------------------------------------------- #
ATOM = "{http://www.w3.org/2005/Atom}"


def _atom_text(entry, tag):
    el = entry.find(f"{ATOM}{tag}")
    return (el.text or "") if el is not None else ""


def _is_post_stub(content):
    """The submission's own entry in its comments feed (not a comment)."""
    return "[link]" in content and "[comments]" in content


def reddit_post_comments(permalink, limit=4, max_len=400):
    """Fetch a post's comments RSS → (comment_count, top comments)."""
    url = permalink.rstrip("/") + "/.rss"
    try:
        root = ET.fromstring(get(url, parse="text"))
    except Exception:
        return 0, []
    comments = []
    for e in root.findall(f"{ATOM}entry"):
        content = _atom_text(e, "content")
        if _is_post_stub(content):
            continue
        body = strip_html(content)
        if len(body) < 40:
            continue
        author_el = e.find(f"{ATOM}author")
        comments.append({
            "author": _atom_text(author_el, "name") if author_el is not None else "",
            "text": body[:max_len],
        })
    count = len(comments)
    comments.sort(key=lambda c: len(c["text"]), reverse=True)
    return count, comments[:limit]


def fetch_reddit(cfg, since):
    raw = []
    seen = set()
    t = cfg.get("time", "day")
    delay = cfg.get("request_delay", 2)
    for i, sub in enumerate(cfg.get("subreddits", [])):
        if i:
            time.sleep(delay)  # Reddit 429s on rapid bursts
        try:
            xml = get(f"https://www.reddit.com/r/{sub}/top/.rss?t={t}", parse="text")
            root = ET.fromstring(xml)
        except Exception as e:
            print(f"  reddit r/{sub} failed: {e}", file=sys.stderr)
            continue
        for pos, entry in enumerate(root.findall(f"{ATOM}entry")):
            title = _atom_text(entry, "title")
            permalink = ""
            link_el = entry.find(f"{ATOM}link")
            if link_el is not None:
                permalink = link_el.get("href", "")
            updated = _atom_text(entry, "updated") or _atom_text(entry, "published")
            ts = 0
            if updated:
                try:
                    ts = int(parsedate_to_datetime(updated).timestamp())
                except Exception:
                    try:  # Atom uses ISO 8601, not RFC822
                        ts = int(time.mktime(time.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")))
                    except Exception:
                        ts = 0
            if ts and ts < since:
                continue
            sid = permalink or title
            if sid in seen:
                continue
            seen.add(sid)
            content = _atom_text(entry, "content")
            # Pull the external article link out of the Reddit content blob.
            mlink = re.search(r'href="([^"]+)"[^>]*>\s*\[link\]', content)
            mcomments = re.search(r'href="([^"]+)"[^>]*>\s*\[comments\]', content)
            permalink = (mcomments.group(1) if mcomments else permalink)
            article = mlink.group(1) if mlink else permalink
            is_self = (article == permalink)
            author_el = entry.find(f"{ATOM}author")
            author = _atom_text(author_el, "name") if author_el is not None else ""
            # Drop the boilerplate table (thumbnail / "submitted by" / link / comments);
            # what remains on a self post is the actual selftext.
            body = strip_html(re.sub(r"<table>.*?</table>", " ", content, flags=re.S))
            raw.append({
                "source": "reddit", "source_label": f"r/{sub}",
                "kind": "ask" if is_self else "link",
                "title": title, "url": article, "discuss_url": permalink,
                "points": 0, "num_comments": 0, "author": author,
                "text": body[:600] if is_self else "", "created_at": ts,
                "_pos": pos, "comments": [],
            })
    # Walk candidates in feed-position order; fetch each post's comments RSS and
    # keep only those with real discussion, until we have `keep` (or hit the cap).
    raw.sort(key=lambda x: x["_pos"])
    keep = cfg.get("keep", 14)
    min_comments = cfg.get("min_comments", 3)
    max_fetch = cfg.get("max_fetch", keep + 12)
    cdelay = cfg.get("comment_delay", 1.5)
    kept = []
    for i, it in enumerate(raw[:max_fetch]):
        if len(kept) >= keep:
            break
        if i:
            time.sleep(cdelay)
        count, comments = reddit_post_comments(it["discuss_url"], limit=cfg.get("fetch_comments", 4))
        if count < min_comments:
            continue
        it["num_comments"] = count
        it["comments"] = comments
        kept.append(it)
    for it in kept:
        it.pop("_pos", None)
    print(f"  reddit: kept {len(kept)} of {len(raw)} candidates (>= {min_comments} comments)", file=sys.stderr)
    return kept


# --------------------------------------------------------------------------- #
# Substack (RSS)
# --------------------------------------------------------------------------- #
def _tag(el, name):
    child = el.find(name)
    return child.text if child is not None and child.text else ""


def fetch_substack(cfg, since):
    # Newsletters publish weekly-ish, so they get their own wider window.
    win = cfg.get("window_hours")
    if win:
        since = int(time.time()) - win * 3600
    # Recurring non-article posts (open threads, etc.) are noise — skip by title.
    skip = [p.lower() for p in cfg.get("skip_patterns", ["open thread"])]
    items = []
    for feed in cfg.get("feeds", []):
        name, url = feed.get("name"), feed.get("url")
        try:
            xml = get(url, parse="text")
            root = ET.fromstring(xml)
        except Exception as e:
            print(f"  substack {name} failed: {e}", file=sys.stderr)
            continue
        channel = root.find("channel")
        if channel is None:
            continue
        for entry in channel.findall("item"):
            link = _tag(entry, "link")
            title = _tag(entry, "title")
            if any(p in (title or "").lower() for p in skip):
                continue
            pub = _tag(entry, "pubDate")
            ts = 0
            if pub:
                try:
                    ts = int(parsedate_to_datetime(pub).timestamp())
                except Exception:
                    ts = 0
            if ts and ts < since:
                continue
            desc = _tag(entry, "description") or _tag(entry, "{http://purl.org/rss/1.0/modules/content/}encoded")
            author = _tag(entry, "{http://purl.org/dc/elements/1.1/}creator") or name
            items.append({
                "source": "substack", "source_label": name, "kind": "newsletter",
                "title": title, "url": link, "discuss_url": link,
                "points": 0, "num_comments": 0, "author": author,
                "text": strip_html(desc)[:600], "created_at": ts, "comments": [],
            })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[: cfg.get("keep", 10)]


# --------------------------------------------------------------------------- #
# Ranking: normalize each source to 0..1, blend, merge
# --------------------------------------------------------------------------- #
def score_source(items, rank_cfg, weight):
    """Assign rank_score in-place. Percentile (position) + engagement, weighted."""
    n = len(items)
    if not n:
        return
    pw = rank_cfg.get("percentile_weight", 0.6)
    ew = rank_cfg.get("engagement_weight", 0.4)
    # Any engagement signal? Points (HN) or comment counts (HN / Reddit-via-RSS).
    has_signal = any(it["points"] or it["num_comments"] for it in items)
    if has_signal:
        items.sort(key=lambda x: (x["points"], x["num_comments"]), reverse=True)
        eng = [math.log1p(it["points"]) + 0.5 * math.log1p(it["num_comments"]) for it in items]
    else:
        # Editorial sources (Substack): no votes/comments — order by recency, neutral engagement.
        items.sort(key=lambda x: x["created_at"], reverse=True)
        eng = [0.5] * n
    emax = max(eng) or 1.0
    for i, it in enumerate(items):
        percentile = 1.0 - (i / (n - 1) if n > 1 else 0.0)
        engagement = eng[i] / emax
        base = pw * percentile + ew * engagement
        it["score_norm"] = round(base, 4)
        it["rank_score"] = round(base * weight, 4)


def merge_dedup(groups):
    """Flatten source groups, dedup by canonical URL keeping the best-ranked."""
    by_key, no_key = {}, []
    for items in groups:
        for it in items:
            key = norm_url(it.get("url"))
            if not key:
                no_key.append(it)
                continue
            cur = by_key.get(key)
            if cur is None or it["rank_score"] > cur["rank_score"]:
                if cur:
                    it.setdefault("also_on", []).extend(
                        [cur["source_label"]] + cur.get("also_on", []))
                by_key[key] = it
            else:
                cur.setdefault("also_on", []).append(it["source_label"])
    merged = list(by_key.values()) + no_key
    merged.sort(key=lambda x: x["rank_score"], reverse=True)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "sources.json"))
    ap.add_argument("--hours", type=int, help="override lookback window")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    hours = args.hours or cfg.get("window_hours", 24)
    since = int(time.time()) - hours * 3600
    rank_cfg = cfg.get("ranking", {})
    weights = rank_cfg.get("source_weights", {})

    groups = []
    counts = {}
    fetchers = [
        ("hackernews", fetch_hackernews),
        ("reddit", fetch_reddit),
        ("substack", fetch_substack),
    ]
    for name, fn in fetchers:
        try:
            items = fn(cfg.get(name, {}), since)
        except Exception as e:
            print(f"{name} failed entirely: {e}", file=sys.stderr)
            items = []
        score_source(items, rank_cfg, weights.get(name, 1.0))
        counts[name] = len(items)
        groups.append(items)
        print(f"  {name}: {len(items)} items", file=sys.stderr)

    merged = merge_dedup(groups)[: cfg.get("final_keep", 30)]
    # Final feed-relative score (0..1) for rendering meter bars.
    top = merged[0]["rank_score"] if merged else 1.0
    for it in merged:
        it["feed_score"] = round(it["rank_score"] / top, 4) if top else 0.0

    bundle = {
        "generated_at": int(time.time()),
        "window_hours": hours,
        "source_counts": counts,
        "items": merged,
    }
    text = json.dumps(bundle, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}: {len(merged)} ranked items "
              f"({', '.join(f'{k}={v}' for k, v in counts.items())})", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
