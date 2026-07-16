# daily-brief

A daily tech read that blends **Hacker News, Reddit, and Substack**, ranked across
platforms and split across three clickable tabs — **The Wire** (industry),
**Deep Dives** (learning) and **Worth a Try** (products) — as a single-file HTML
magazine with a one-line gist per item.

## How it works

```
fetch_sources.py  ──►  data.json  ──►  [Claude gists+tags]  ──►  render_brief.py  ──►  briefs/<date>.html
  (HN API, Reddit       (one ranked     (gist + category per      (groups into 3        (self-contained,
   RSS, Substack RSS)     feed)           item, via the skill)      three CSS tabs)       magazine layout)
```

- **`fetch_sources.py`** — pulls from three platforms, normalizes each one's
  signals onto a common 0–1 scale, and merges everything into a **single ranked
  feed**. Sources fail independently, so a blocked or quiet source just
  contributes fewer items.
  - **Hacker News** — front-page + Ask HN via the official
    [Algolia HN Search API](https://hn.algolia.com/api); caches top comments per
    thread for the gist.
  - **Reddit** — configured subreddits via public RSS (the JSON API is widely
    IP-blocked). Ranked by feed position; no vote/comment counts.
  - **Substack** — a curated list of newsletters via RSS, over a wider window
    (newsletters publish weekly, not daily).
- **`sources.json`** — all tuning: subreddits, Substack feeds, ranking weights,
  per-source `keep`, window. Edit this to make the brief yours.
- **`render_brief.py`** — deterministic renderer. Reads `data.json` (with a `gist`
  and `category` per item), splits items across the three tabs (pure-CSS, no JS),
  and emits the magazine HTML, so layout never depends on the model hand-writing markup.
- **`.claude/skills/daily-brief/`** — the skill Claude runs: fetch → gist →
  render → save to `briefs/`.
- **`briefs/`** — dated output, one HTML file per day.

## Ranking & grouping

Points aren't comparable across platforms, so each source is normalized
independently: a blend of **feed position** (percentile) and **engagement**
(log-scaled points + comments), times a per-source weight. The results are merged,
deduped by URL, and ranked into one feed. Claude then tags each item with a
**category** — `industry` / `learning` / `products` — and the renderer lays them
out under three clickable tabs (**The Wire**, **Deep Dives**, **Worth a Try**),
ranked within each (top item as a full-width lead). Tune the weights in
`sources.json → ranking`; rename tabs in `render_brief.py → CATEGORIES`.

Recurring non-article Substack posts (e.g. "Open Thread") are filtered via
`substack.skip_patterns` so they don't headline a section.

## Customize your sources

Edit `sources.json`:

```jsonc
{
  "reddit":   { "subreddits": ["programming", "rust", "selfhosted"] },
  "substack": { "feeds": [ { "name": "My Newsletter", "url": "https://x.substack.com/feed" } ] },
  "ranking":  { "source_weights": { "hackernews": 1.0, "reddit": 0.92, "substack": 0.9 } }
}
```

## Personalize from your accounts

By default the Reddit and Substack sources fall back to curated public lists (in
`sources.json`) and Medium pulls a few public tag/publication feeds — so the brief
**always builds with zero setup**. Add credentials to pull *your* feeds instead.
Each source tries the richest tier it can and **falls back automatically**; a
provenance line in the brief's footer shows which tier served each source, so a
stale cookie is visible at a glance (and the footer turns red — "refresh your
cookies/tokens" — if every personal source has fallen back).

All credentials live in `~/.config/secrets/` (same place as `anthropic_token`),
are read directly by `auth.py`, and are never committed. Absent or expired
credentials simply disable that tier.

### Reddit — your home feed (`GET /best`)

1. Create a Reddit app at <https://www.reddit.com/prefs/apps> (type **script** or
   **installed app**). Note the client id and secret.
2. Mint a **refresh token** once via the OAuth auth-code flow (scopes: `read`,
   `mysubreddits`; `duration=permanent`). Password-grant is avoided because it
   breaks under 2FA.
3. Write `~/.config/secrets/reddit_oauth.json`:
   ```json
   { "client_id": "…", "client_secret": "…", "refresh_token": "…" }
   ```

*(Optional, zero-auth fallback tier)* Enable private RSS feeds in old-Reddit
`prefs/feeds/`, copy the home-feed URL, and drop it in
`~/.config/secrets/reddit_home_rss` (one line). It's subscription-based (not
algorithmic) and validity-checked against your `reddit.subreddits` list, since this
feed can silently degrade to r/popular.

### Substack — your subscriptions

1. Log in at substack.com, open DevTools → Application → Cookies → copy the
   **`substack.sid`** value (it's `HttpOnly`, so use the cookie panel, not the
   console). Put it in `~/.config/secrets/substack_sid` (one line — bare value or
   `substack.sid=…`). Lasts ~3 months. That's the only step — the brief calls
   `/api/v1/subscriptions` to get your followed publications and reads each one's
   RSS (no user_id needed).
2. *(Optional, off by default)* set `substack.use_inbox: true` to use the aggregated
   reader inbox (`/api/v1/reader/posts`) — richer ordering but undocumented and
   fragile; verify the live shape if it misbehaves.

### Medium — your follows

Medium has **no durable personalized-feed API**, so personalization is a hand-curated
list of who/what you follow in `sources.json → medium.follows`:
```jsonc
"follows": [
  { "type": "author",      "handle": "@some-writer",   "label": "Some Writer" },
  { "type": "publication", "handle": "better-programming" },
  { "type": "tag",         "handle": "machine-learning" }
]
```
The brief merges the public RSS of each. (`medium.use_graphql` is an off-by-default
stub for the cookie/GraphQL "For you" feed — intentionally not wired up because it
breaks within months.)

## Run it manually

In Claude Code, from this folder:

```
/daily-brief
```

Or just the data layer:

```bash
python3 fetch_sources.py --out data.json     # tweak with --hours 24 --config sources.json
```

## Automated daily publishing (GitHub Pages)

The repo publishes itself. A systemd user timer (via home-manager) runs
`automation/run_daily.sh` every morning, which:

```
fetch_sources.py → gen_gists.py (claude -p) → render_brief.py → gen_archive.py → git push
```

- `automation/gen_gists.py` — headless replacement for the model's gist+category
  step; drives the logged-in `claude` CLI (no API key). Falls back to safe
  defaults if the call fails, so a brief is always produced.
- `render_brief.py` writes both the dated `briefs/<date>.html` **and** the root
  `index.html` (always the latest).
- `automation/gen_archive.py` rebuilds `archive.html`.
- The script commits and pushes; **GitHub Pages** serves it.

Bookmark the Pages root — it always shows the latest edition:
**https://gupta-ujjwal.github.io/daily-brief/**

### Schedule (home-manager)

`modules/daily-brief.nix` in the home-manager config defines the service + timer
(daily, `Persistent=true`). Change the time via `OnCalendar`. Run by hand any time:

```bash
./automation/run_daily.sh        # full fetch → gist → render → push
BRIEF_MODEL=haiku ./automation/run_daily.sh   # cheaper/faster gists
```

You can also still run it interactively in Claude Code with `/daily-brief`.
