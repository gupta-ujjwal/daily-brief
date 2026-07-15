# Personalize the daily-brief from my accounts' feeds

> Implemented via `/brainstorm` → `/develop` on 2026-07-15.

## What

Turns the brief's Reddit and Substack sources from hardcoded public lists into the
user's **own** feeds, and adds **Medium** as a fourth source — while keeping Hacker
News generic. Each personalized source now runs a **per-source tiered fetch**: it
tries the richest durable tier it can authenticate, and falls back automatically so
the brief always builds. A new `auth.py` loads per-account credentials from
`~/.config/secrets/`; a provenance footer in the HTML shows which tier served each
source. Touches `fetch_sources.py`, new `auth.py`, `render_brief.py`, `sources.json`,
the render `template.html`, `README.md`, `automation/run_daily.sh`, `.gitignore`, and
adds `test_fetch_sources.py`. External surface: `sources.json` gains per-source tier
config + a `medium` block; new (optional) secret files; an additive provenance footer.
No public API or DB.

## Why

The brief answered "what's happening in tech?" from curated lists someone typed by
hand (`sources.json`). The goal was to make it answer "what's happening in **my**
world?" by pulling the user's algorithmic/subscription feeds instead.

**Research reshaped the design**: "algorithmic feed" durability differs sharply per
platform, so a one-size "cookie + fallback" model was wrong-shaped. Each platform gets
its *durable* tier as the primary:

- **Reddit** — OAuth `GET /best` is the true personalized home feed (documented, fails
  loudly). Private tokenized RSS is a fallback, but it can silently return r/popular,
  so it's validity-checked. Public subreddits are the final fallback.
- **Substack** — the durable path is fetching your subscription list
  (`/public_profile/self`) and reusing the per-publication RSS pipeline. The aggregated
  reader inbox (`/api/v1/reader/posts`) is richer but undocumented/fragile, so it's
  **off by default**.
- **Medium** — has *no* durable personalized-feed API (the cookie/GraphQL path is
  Cloudflare-guarded and breaks within months), so the primary tier reconstructs a
  pseudo-personalized feed from the public RSS of the authors/publications/tags you
  follow (`medium.follows`). The GraphQL tier is an off-by-default stub.

**Approaches considered.** (1) *Per-source tiered fetch with a shared auth layer* —
chosen. (2) *Cookie-only algo feeds, hard-fail to lists* — rejected: it makes the
*fragile* tiers primary and Reddit's silent r/popular degrade becomes a correctness
bug the binary fallback never catches. (3) *Separate `personal_sources.py` module* —
rejected: duplicates parsing and creates two definitions of "a source" for no gain
(rule-of-three unmet; only three fetchers, all in one file).

**Plan-review dispositions (all FIX folded in):** per-tier *validity* check, not just
non-empty (catches silent degradation); total non-raising auth boundary; 24h freshness
guard on tier-1; served-tier provenance in the HTML artifact; per-source wall-clock
budget so one slow fetch can't stall the run; one shared `run_tiers` helper (no
copy-paste); durable tiers primary with fragile cookie tiers as off-by-default stubs.
Deferred: the separate-module approach (not chosen).

**Pre-mortem.** Most-likely failure: a Substack/Reddit credential silently expires and
the source falls to its generic tier — the provenance footer + `PERSONALIZATION
DEGRADED` stderr line make it visible rather than invisible-for-weeks. **Rollback:**
delete the secret files → every tier-1 returns `None` → all sources fall to today's
behavior, zero code change (or `git revert` the branch). No migration, no Pages
rollback (footer is additive).

## How

Built as one shared mechanism plus three thin per-source tier ladders.

- **`auth.py` (new, total/non-raising).** `read_secret` / `read_json_secret` load from
  `~/.config/secrets/` (override via `$BRIEF_SECRETS_DIR`, used by tests).
  `reddit_bearer()` exchanges a stored refresh token for a 1-hour bearer;
  `substack_cookie_header()` normalizes the `substack.sid` cookie. Every accessor
  returns `None` on any missing secret / malformed file / failed exchange — it never
  raises into the fetchers.
- **`run_tiers(label, tiers)`** — the one shared fallback engine. Advances to the next
  tier on *exception OR empty OR failed validity check*, returns `(items,
  served_tier)`. The validity check is what distinguishes a real personalized feed
  from a plausible-but-wrong one (Reddit's `_reddit_rss_is_personalized` rejects an
  all-r/popular degrade by requiring overlap with the configured subreddits; lenient —
  any intersection passes).
- **`time_budget(seconds, label)`** — a SIGALRM context manager giving each source a
  hard wall-clock bound (default 120s), so a stalled multi-tier fetch degrades that one
  source to empty instead of stalling the whole run. Caught by the run loop's
  `except`; itimer + handler restored in `finally`; no-ops where SIGALRM is absent.
- **Fetchers.** Reddit: `fetch_reddit` → `[home-oauth, home-rss, public]`. Substack:
  `fetch_substack_tiered` → `[inbox (off), subscriptions, feeds]` (subscriptions and
  the fallback share `_substack_feeds`). Medium: `fetch_medium` →
  `[graphql (off stub), follows]`. All emit the existing item-dict shape, so
  `score_source` / `merge_dedup` / rendering are unchanged.
- **Detection (`is_degraded`).** Extracted and scoped to `GENERIC_FALLBACK =
  {reddit, substack}` (credential-backed sources that have a generic tier) with an
  `intended` guard (creds actually configured). Returns the list of configured sources
  that nonetheless fell to their generic tier ⇒ expired cookie/token. Medium is
  excluded (its only tier is public RSS — can't expire, can't mask others), and the
  zero-setup default never false-alarms.
- **Render.** `render_brief.py` gains a `provenance_line` → a footer "Personalized from
  — Reddit: your home feed · …", rendered red with a "refresh your cookies/tokens" note
  when degraded. `template.html` adds the Medium color/legend/accent + a `{{PROVENANCE}}`
  slot. `sources.json` adds `per_source_timeout`, `reddit.home_limit`, `substack`
  tier flags + `user_id`, a `medium` block with example `follows`, and a `medium`
  ranking weight. `README.md` documents credential extraction per platform;
  `run_daily.sh` notes the secrets are read directly by `auth.py`.

**Deviation from plan.** The plan's "spike each tier-1 live shape first" step needs the
user's live credentials (Reddit refresh token, `substack.sid`), which weren't
available at implementation time. The tier-1 authed paths (`fetch_reddit_best`,
`fetch_substack_subscriptions`, `fetch_substack_inbox`) are therefore coded to the
researched API shapes and will need live verification when the user adds credentials —
called out in the handoff. The entire **graceful-degradation path was verified
end-to-end** with an empty secrets dir (all sources cascade to their generic tiers;
Medium's `follows` RSS fetched 10 live items; provenance + degraded fields correct;
no unfilled template placeholders).

**Build / test / review.** `python3 -m py_compile` passes for all modules (pure
Python, no build step, no formatter configured). `test_fetch_sources.py` (stdlib
`unittest`, 10 tests) passes — covering `run_tiers` fallthrough, the `is_degraded`
predicate (incl. a regression test that Medium's `follows` can't mask a Reddit
degrade), the Reddit validity marker, the Medium URL builder, and auth totality.
Autonomous `/deep-review` ran two iterations: iteration 1 found 1 Block (a defect in
`is_degraded` where Medium's always-`follows` tier masked Reddit/Substack degradation)
+ 3 Request-changes + 4 Nits; all were fixed (the Block via the scoping + `intended`
guard, plus a `_parse_ts` dedupe, `auth.read_secret` made public, `isinstance` guards,
and the new test module). Iteration 2 (fresh context) confirmed **clean — 0 Block**,
masking gap closed.
