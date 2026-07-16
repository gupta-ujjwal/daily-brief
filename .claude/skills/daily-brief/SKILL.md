---
name: daily-brief
description: Build an engaging single-file HTML daily read that blends Hacker News, Reddit and Substack, ranked across platforms and split across three tabs — The Wire (industry), Deep Dives (learning) and Worth a Try (products). Fetches the last 24h via official APIs / RSS, writes a one-line gist per item, and outputs a dated briefs/<date>.html in a bold magazine layout. Use when the user asks for their daily tech brief / digest, or when run on a schedule.
---

# Daily Brief

Produce a single-file HTML magazine of the day's best tech reading — pulled from
**Hacker News, Reddit, and Substack**, ranked across platforms, and split across
three clickable tabs: **The Wire** (industry), **Deep Dives** (learning) and
**Worth a Try** (products).

## Steps

1. **Fetch the data.** From the skill's project root run:
   ```bash
   python3 fetch_sources.py --out data.json
   ```
   This reads `sources.json` (subreddits, Substack feeds, ranking weights) and
   writes `data.json` with one already-ranked `items` array plus `source_counts`.
   Each item carries `source, source_label, kind, title, url, discuss_url,
   points, num_comments, author, text, comments[], rank_score, feed_score`
   (0–1, feed-relative) and an optional `also_on[]`. HN contributes front-page,
   **Ask HN** and **Show HN** (`kind` = `link`/`ask`/`show`); Reddit posts are
   filtered to those with real discussion (≥ `min_comments`). Sources fail
   independently — a quiet or blocked source just contributes fewer items.

2. **Write gists + categorize.** Read `data.json`. For every item add two keys:
   - `"gist"` — a **one-line gist** (≤ 25 words): what the thread is arguing about
     or the key takeaway, not a restatement of the title.
     - HN (incl. Ask/Show) and Reddit: distill from `comments` / `text`.
     - Substack: distill from the `text` excerpt (it's the post's opening).
     - No usable `comments`/`text`? Infer from the title/`source_label`, or keep it
       short. If you truly can't, set `""`.
   - `"category"` — one of (key → tab it lands in):
     - `"industry"` → **The Wire**: business, funding, M&A, layoffs, policy,
       company/strategy moves, notable launches as news.
     - `"learning"` → **Deep Dives**: essays, deep-dives, techniques, research,
       opinion/discussion, new capabilities and concepts to understand.
     - `"products"` → **Worth a Try**: things to try or adopt — Show HN, repos,
       frameworks, tools, devices, apps, services.
     - `"personal"` → **Off the Clock**: NON-tech, personal-interest or local posts
       — local city/community, cars/watches/hobbies, lifestyle, memes, sports, real
       estate, personal-finance chatter (mostly from a personalized Reddit home feed).

     Decide tech-vs-personal FIRST: anything not about tech/software/business/science
     is `"personal"`. Among tech items, pick by the reader's intent (read-to-know →
     industry, read-to-learn → learning, go-try-it → products).

   Write both fields back into `data.json` (leave everything else untouched).

3. **Render HTML.** Run the renderer — it splits items into the three tabs (ranked
   within each, top item as a full-width lead card), builds the pure-CSS tab bar,
   badges, score meters and the source legend, escapes everything, and fills
   `template.html`:
   ```bash
   python3 render_brief.py --data data.json --date "25 June 2026" \
       --out briefs/2026-06-25.html
   ```
   It errors loudly if a placeholder is left unfilled. Items missing a valid
   `category` fall back to The Wire; empty tabs are omitted (first tab is active). Layout is
   fixed in code — don't hand-build the HTML. (To restyle, edit `template.html` /
   `render_brief.py`, not the per-day output.)

4. **Report** the saved path and a 3-line summary of the day's highlights across
   the sources.

## Notes
- Self-contained: all CSS is inline in the template, no external assets.
- Quiet/blocked source? Still produce the file with whatever ranked.
- **Tuning** is in `sources.json`: `hackernews.{top,ask,show}`,
  `reddit.{subreddits,min_comments,max_fetch}`, `substack.feeds`,
  `ranking.source_weights`, per-source `keep`, and `final_keep`. Substack uses a
  wider `window_hours` (newsletters publish weekly). CLI overrides: `--hours`,
  `--config`.
- Reddit uses public RSS (the JSON API is widely IP-blocked). Comment counts come
  from each post's comments RSS, which also seeds the gist and the engagement
  signal — so the fetch makes one request per Reddit candidate and can be slow
  under rate-limiting (bounded by `reddit.max_fetch` / `comment_delay`).
