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
import contextlib
import html
import json
import math
import os
import re
import signal
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import auth

UA = {"User-Agent": auth.UA}  # single source of truth in auth.py
ALGOLIA = "https://hn.algolia.com/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))


def _parse_ts(s):
    """Best-effort feed timestamp → epoch int: RFC822 (RSS pubDate) or ISO-8601
    (Atom updated/published). Returns 0 when unparseable."""
    if not s:
        return 0
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        try:
            return int(time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            return 0


def get(url, parse="json", retries=2, headers=None):
    """HTTP GET with bounded retry. `headers` (dict) is merged over the default
    User-Agent — used to pass Cookie / Authorization for authenticated sources."""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
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


# --------------------------------------------------------------------------- #
# Tiered fetch: try the richest DURABLE source first, fall back on failure.
#
# Each personalized source declares an ordered list of tiers. run_tiers advances
# to the next tier on: an exception, an empty result, OR a validity check that
# rejects the result. The validity check is what catches "plausible-but-wrong"
# degradation (e.g. Reddit's tokenized RSS silently returning r/popular instead
# of your subscriptions) — non-emptiness alone is not enough to accept a tier.
# --------------------------------------------------------------------------- #
def run_tiers(label, tiers):
    """tiers: list of (tier_name, fetch_fn, accept_fn|None).
    Returns (items, served_tier_name). served_tier_name is None if all tiers
    fell through (the source contributes nothing, but the brief still renders)."""
    for name, fetch_fn, accept in tiers:
        try:
            items = fetch_fn()
        except Exception as e:
            print(f"  {label}: tier '{name}' errored ({e}) — falling back", file=sys.stderr)
            continue
        if not items:
            print(f"  {label}: tier '{name}' empty — falling back", file=sys.stderr)
            continue
        if accept and not accept(items):
            print(f"  {label}: tier '{name}' failed validity check — falling back", file=sys.stderr)
            continue
        print(f"  {label}: served by tier '{name}' ({len(items)} items)", file=sys.stderr)
        return items, name
    print(f"  {label}: ALL tiers failed — contributing nothing", file=sys.stderr)
    return [], None


class _Timeout(Exception):
    pass


@contextlib.contextmanager
def time_budget(seconds, label):
    """Hard wall-clock bound for a single source's whole fetch, so a slow
    multi-tier fetch (or a network stall) can't stall the daily run and starve
    the other sources. Uses SIGALRM (Unix, main thread); a no-op elsewhere."""
    if not seconds or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise _Timeout(f"{label} exceeded {seconds}s budget")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


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
# Reddit — tiered: your personalized home feed first, public subreddits as the
# durable fallback.
#
#   tier 1  home-oauth   GET oauth.reddit.com/best  — your algorithmic home feed
#                        (needs reddit_oauth.json; the only TRUE personalized tier)
#   tier 2  home-rss     tokenized private RSS      — subscription home feed;
#                        validity-checked because it can silently degrade to
#                        r/popular (NewsBlur #13757)
#   tier 3  public       hardcoded subreddit top/.rss — always available fallback
#
# The public tier: top/.rss is ranked by score, so feed position seeds
# candidates. Each post's own comments RSS then tells us whether it has real
# discussion: keep only posts with >= min_comments, attach the top comments (for
# a real gist), and use the comment count as the cross-platform engagement signal.
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


def fetch_reddit_public(cfg, since):
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
            ts = _parse_ts(_atom_text(entry, "updated") or _atom_text(entry, "published"))
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


def fetch_reddit_best(cfg, since, bearer):
    """Tier 1: your personalized 'Best'-ranked home feed via OAuth. Because a
    valid bearer returns YOUR home by construction, this tier is trusted on a
    non-empty result — the validity marker is reserved for the RSS tier that can
    silently degrade."""
    if not bearer:
        return []
    limit = cfg.get("home_limit", 25)
    headers = {"Authorization": f"Bearer {bearer}"}
    data = get(f"https://oauth.reddit.com/best?limit={limit}", headers=headers)
    if not isinstance(data, dict):
        return []
    items = []
    for child in (data.get("data", {}) or {}).get("children", []) or []:
        d = child.get("data") or {}
        ts = int(d.get("created_utc") or 0)
        if ts and ts < since:
            continue
        sid = d.get("id")
        is_self = bool(d.get("is_self"))
        permalink = "https://www.reddit.com" + (d.get("permalink") or "")
        items.append({
            "source": "reddit", "source_label": f"r/{d.get('subreddit', '')}",
            "kind": "ask" if is_self else "link",
            "title": d.get("title"),
            "url": permalink if is_self else (d.get("url") or permalink),
            "discuss_url": permalink,
            "points": int(d.get("score") or 0),
            "num_comments": int(d.get("num_comments") or 0),
            "author": d.get("author") or "",
            "text": strip_html(d.get("selftext") or "")[:600] if is_self else "",
            "created_at": ts, "comments": [], "_subreddit": (d.get("subreddit") or "").lower(),
        })
    return items


def _reddit_home_rss_url(cfg):
    """Read the tokenized private-RSS home URL from a secret file (its embedded
    token is a credential, so it lives in secrets, not committed config)."""
    return auth.read_secret("reddit_home_rss")  # e.g. https://www.reddit.com/.rss?feed=<hex>&user=<u>


def fetch_reddit_private_rss(cfg, since):
    """Tier 2: the account's tokenized home-feed RSS. Subscription-based (not
    algorithmic), and known to occasionally silently return r/popular — so its
    result is validity-checked against your configured subreddits before use."""
    url = _reddit_home_rss_url(cfg)
    if not url:
        return []
    root = ET.fromstring(get(url, parse="text"))
    items = []
    for entry in root.findall(f"{ATOM}entry"):
        title = _atom_text(entry, "title")
        link_el = entry.find(f"{ATOM}link")
        permalink = link_el.get("href", "") if link_el is not None else ""
        ts = _parse_ts(_atom_text(entry, "updated") or _atom_text(entry, "published"))
        if ts and ts < since:
            continue
        cat_el = entry.find(f"{ATOM}category")
        subreddit = (cat_el.get("term", "") if cat_el is not None else "").lower()
        content = _atom_text(entry, "content")
        mlink = re.search(r'href="([^"]+)"[^>]*>\s*\[link\]', content)
        article = mlink.group(1) if mlink else permalink
        author_el = entry.find(f"{ATOM}author")
        author = _atom_text(author_el, "name") if author_el is not None else ""
        items.append({
            "source": "reddit", "source_label": f"r/{subreddit}" if subreddit else "Reddit",
            "kind": "link", "title": title, "url": article, "discuss_url": permalink,
            "points": 0, "num_comments": 0, "author": author,
            "text": "", "created_at": ts, "comments": [], "_subreddit": subreddit,
        })
    return items


def _reddit_rss_is_personalized(cfg):
    """Accept the private-RSS tier only if its posts overlap the subreddits you
    actually care about (the configured list). Lenient — any intersection passes;
    an all-r/popular degrade (no overlap) is rejected so we fall to tier 3."""
    wanted = {s.lower() for s in cfg.get("subreddits", [])}

    def accept(items):
        if not wanted:
            return True  # nothing to check against — don't block the feed
        got = {it.get("_subreddit", "") for it in items}
        return bool(wanted & got)

    return accept


def fetch_reddit(cfg, since, bearer=None):
    """Orchestrate Reddit's tiers. Returns (items, served_tier)."""
    tiers = [
        ("home-oauth", lambda: fetch_reddit_best(cfg, since, bearer), None),
        ("home-rss", lambda: fetch_reddit_private_rss(cfg, since),
         _reddit_rss_is_personalized(cfg)),
        ("public", lambda: fetch_reddit_public(cfg, since), None),
    ]
    items, tier = run_tiers("reddit", tiers)
    for it in items:
        it.pop("_subreddit", None)
    return items, tier


# --------------------------------------------------------------------------- #
# Substack — tiered: your subscriptions first, hardcoded feeds as the fallback.
#
#   tier 1  inbox    GET /api/v1/reader/posts (cookie)   — aggregated for-you feed
#                    (OFF BY DEFAULT: undocumented, fragile; enable in config)
#   tier 2  subs     /public_profile/self → subscriptions[] → each pub's /feed
#                    (cookie; durable — reuses the per-publication RSS path)
#   tier 3  feeds    hardcoded feeds in sources.json     — always-available fallback
# --------------------------------------------------------------------------- #
def _tag(el, name):
    child = el.find(name)
    return child.text if child is not None and child.text else ""


def _substack_feeds(feeds, since, cfg):
    """Fetch a list of [{name, url}] Substack RSS feeds into ranked items. Shared
    by the subscriptions tier (feeds derived from your account) and the hardcoded
    fallback tier (feeds listed in sources.json) — same parsing, different source
    of the feed list."""
    skip = [p.lower() for p in cfg.get("skip_patterns", ["open thread"])]
    items = []
    for feed in feeds:
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
            ts = _parse_ts(_tag(entry, "pubDate"))
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


def _substack_window(cfg, since):
    # Newsletters publish weekly-ish, so they get their own wider window.
    win = cfg.get("window_hours")
    return int(time.time()) - win * 3600 if win else since


def fetch_substack(cfg, since):
    """Tier 3 fallback: the hardcoded feeds in sources.json."""
    return _substack_feeds(cfg.get("feeds", []), _substack_window(cfg, since), cfg)


def fetch_substack_subscriptions(cfg, since, cookie):
    """Tier 2: derive your followed publications from your Substack account, then
    reuse the per-publication RSS path. Needs only the substack.sid cookie — the
    /api/v1/subscriptions endpoint returns publications[] with a subdomain each,
    so no user_id is required. Returns [] if the cookie is absent/expired."""
    if not cookie:
        return []
    data = get("https://substack.com/api/v1/subscriptions?tvOnly=false",
               headers={"Cookie": cookie})
    if not isinstance(data, dict):
        return []
    feeds = []
    for pub in data.get("publications", []) or []:
        domain = pub.get("custom_domain") or (
            f"{pub['subdomain']}.substack.com" if pub.get("subdomain") else None)
        if domain:
            feeds.append({"name": pub.get("name") or domain,
                          "url": f"https://{domain}/feed"})
    return _substack_feeds(feeds, _substack_window(cfg, since), cfg)


def fetch_substack_inbox(cfg, since, cookie):
    """Tier 1 (OFF BY DEFAULT): the aggregated reader inbox. Undocumented and
    fragile — enabled only when config `substack.use_inbox` is true and the
    cookie is present. Verify the live JSON shape before relying on it."""
    if not (cookie and cfg.get("use_inbox")):
        return []
    since = _substack_window(cfg, since)
    data = get("https://substack.com/api/v1/reader/posts", headers={"Cookie": cookie})
    posts = data.get("posts") if isinstance(data, dict) else data
    items = []
    for p in posts or []:
        post = p.get("post") if isinstance(p, dict) and "post" in p else p
        if not isinstance(post, dict):
            continue
        ts = _parse_ts(post.get("post_date") or post.get("published_at"))
        if ts and ts < since:
            continue
        pubname = (post.get("publishedBylines") or [{}])[0].get("name") if post.get("publishedBylines") else None
        items.append({
            "source": "substack",
            "source_label": (post.get("publication") or {}).get("name") or pubname or "Substack",
            "kind": "newsletter", "title": post.get("title"),
            "url": post.get("canonical_url") or post.get("url"),
            "discuss_url": post.get("canonical_url") or post.get("url"),
            "points": 0, "num_comments": int(post.get("comment_count") or 0),
            "author": pubname or "", "text": strip_html(post.get("description") or "")[:600],
            "created_at": ts, "comments": [],
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[: cfg.get("keep", 10)]


def fetch_substack_tiered(cfg, since, cookie):
    """Orchestrate Substack's tiers. Returns (items, served_tier)."""
    tiers = [
        ("inbox", lambda: fetch_substack_inbox(cfg, since, cookie), None),
        ("subscriptions", lambda: fetch_substack_subscriptions(cfg, since, cookie), None),
        ("feeds", lambda: fetch_substack(cfg, since), None),
    ]
    return run_tiers("substack", tiers)


# --------------------------------------------------------------------------- #
# Medium — no durable algorithmic feed exists, so the primary tier reconstructs
# a pseudo-personalized feed from the public RSS of the authors / publications /
# tags you follow (configured in sources.json → medium.follows).
#
#   tier 1  graphql   internal GraphQL 'For you' (cookies sid+uid)
#                     (OFF BY DEFAULT, unimplemented stub: Cloudflare-guarded,
#                      breaks within months — see the README)
#   tier 2  follows   RSS of @authors / publications / tag/<t> you follow — durable
# --------------------------------------------------------------------------- #
def _medium_feed_url(entry):
    typ, handle = entry.get("type"), (entry.get("handle") or "").lstrip("@")
    if not handle:
        return None
    if typ == "author":
        return f"https://medium.com/feed/@{handle}"
    if typ == "publication":
        return f"https://medium.com/feed/{handle}"
    if typ == "tag":
        return f"https://medium.com/feed/tag/{handle}"
    return None


def fetch_medium_follows(cfg, since):
    """Tier 2 (primary durable): merge the public RSS of everything you follow."""
    win = cfg.get("window_hours")
    if win:
        since = int(time.time()) - win * 3600
    items = []
    for entry in cfg.get("follows", []):
        url = _medium_feed_url(entry)
        label = entry.get("label") or entry.get("handle")
        if not url:
            continue
        try:
            root = ET.fromstring(get(url, parse="text"))
        except Exception as e:
            print(f"  medium {label} failed: {e}", file=sys.stderr)
            continue
        channel = root.find("channel")
        if channel is None:
            continue
        for it in channel.findall("item"):
            link = _tag(it, "link")
            title = _tag(it, "title")
            ts = _parse_ts(_tag(it, "pubDate"))
            if ts and ts < since:
                continue
            desc = _tag(it, "{http://purl.org/rss/1.0/modules/content/}encoded") or _tag(it, "description")
            author = _tag(it, "{http://purl.org/dc/elements/1.1/}creator") or label
            items.append({
                "source": "medium", "source_label": f"Medium · {label}", "kind": "newsletter",
                "title": title, "url": link, "discuss_url": link,
                "points": 0, "num_comments": 0, "author": author,
                "text": strip_html(desc)[:600], "created_at": ts, "comments": [],
            })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[: cfg.get("keep", 10)]


def fetch_medium_graphql(cfg, since):
    """Tier 1 (OFF BY DEFAULT): the authenticated 'For you' feed via Medium's
    internal GraphQL. Left as a documented stub — the sid/uid cookie path is
    Cloudflare-guarded and stops working within months, so it is intentionally
    not wired up; the durable follows-RSS tier is the real primary."""
    return []


def fetch_medium(cfg, since):
    """Orchestrate Medium's tiers. Returns (items, served_tier)."""
    tiers = [
        ("graphql", lambda: fetch_medium_graphql(cfg, since), None),
        ("follows", lambda: fetch_medium_follows(cfg, since), None),
    ]
    return run_tiers("medium", tiers)


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


# Sources whose personalization depends on a credential AND that have a generic
# fallback tier — the only ones that can signal "your cookie/token expired". Medium
# is deliberately absent: its `follows` tier is public RSS with no credential, so it
# can neither expire nor mask another source's degrade.
GENERIC_FALLBACK = {"reddit": "public", "substack": "feeds"}


def is_degraded(provenance, intended):
    """Return the list of sources whose personalization was CONFIGURED (`intended`)
    yet fell to their generic fallback tier — i.e. an expired cookie/token to
    refresh. Empty in the zero-setup default (nothing intended), so no false alarm.
    Truthy iff at least one configured source silently degraded."""
    return [s for s, generic in GENERIC_FALLBACK.items()
            if intended.get(s) and provenance.get(s) == generic]


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

    # Personal-account credentials (all TOTAL — a None just disables that tier).
    bearer = auth.reddit_bearer()
    substack_cookie = auth.substack_cookie_header()

    # Each thunk returns (items, served_tier). HN is generic (single tier);
    # the personalized sources run their fallback ladder. `served_tier` feeds the
    # provenance footer so a silent degrade is visible in the brief itself.
    budget = cfg.get("per_source_timeout", 120)
    fetchers = [
        ("hackernews", lambda: (fetch_hackernews(cfg.get("hackernews", {}), since), "front-page")),
        ("reddit", lambda: fetch_reddit(cfg.get("reddit", {}), since, bearer)),
        ("substack", lambda: fetch_substack_tiered(cfg.get("substack", {}), since, substack_cookie)),
        ("medium", lambda: fetch_medium(cfg.get("medium", {}), since)),
    ]

    groups = []
    counts = {}
    provenance = {}
    for name, fn in fetchers:
        try:
            with time_budget(budget, name):
                items, tier = fn()
        except Exception as e:
            print(f"{name} failed entirely: {e}", file=sys.stderr)
            items, tier = [], None
        score_source(items, rank_cfg, weights.get(name, 1.0))
        counts[name] = len(items)
        provenance[name] = tier
        groups.append(items)
        print(f"  {name}: {len(items)} items (tier: {tier})", file=sys.stderr)

    merged = merge_dedup(groups)[: cfg.get("final_keep", 30)]
    # Final feed-relative score (0..1) for rendering meter bars.
    top = merged[0]["rank_score"] if merged else 1.0
    for it in merged:
        it["feed_score"] = round(it["rank_score"] / top, 4) if top else 0.0

    # Degraded = a source whose personalization the user CONFIGURED nonetheless
    # fell to its generic fallback tier (⇒ expired cookie/token). Scoped to the
    # credential-backed sources so Medium's always-`follows` state can't mask a
    # Reddit/Substack degrade, and so the zero-setup default never false-alarms.
    intended = {
        "reddit": bool(auth.read_json_secret("reddit_oauth.json")
                       or auth.read_secret("reddit_home_rss")),
        "substack": bool(substack_cookie),
    }
    stale = is_degraded(provenance, intended)
    degraded = bool(stale)
    if degraded:
        print(f"PERSONALIZATION DEGRADED — {', '.join(stale)} fell back to a generic "
              "tier despite configured credentials; refresh your cookies/tokens "
              "(see README).", file=sys.stderr)

    bundle = {
        "generated_at": int(time.time()),
        "window_hours": hours,
        "source_counts": counts,
        "provenance": provenance,
        "degraded": degraded,
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
