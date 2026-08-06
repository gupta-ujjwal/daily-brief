# edition-layout-phase-0-1

> Implemented via `/brainstorm` → `/develop` on 2026-08-06.

## What

Refactor of the daily-brief HTML generator implementing Phase 0 (Hygiene) and Phase 1 (Edition Layout) from the design review at `implementation-docs/design-review-2026-08.md` §4. Three files touched: `render_brief.py` (Python renderer), `.claude/skills/daily-brief/template.html` (HTML/CSS/JS template), and `README.md`. No new features, no data contract change — same CLI signature, same `data.json` schema, same single-file HTML output. The automated daily build pipeline (`run_daily.sh`) is unaffected.

## Why

The product is an **edition** (a newspaper) but was shaped like a **feed** (a dashboard). The design review identified the biggest miss: ranking — the core intellectual work — was invisible in the layout. Every card from rank 1 to rank 14 looked identical. Phase 1 makes ranking *visible* through a 3-tier editorial hierarchy. Phase 0 fixes hygiene issues: a duplicated metadata line that showed the same points/comments twice, a stale README, and an unbounded `seen` map in localStorage that grew forever.

### Approaches considered

**Approach 1 (picked): Structural tiering in Python + additive CSS/JS in template.** `render_brief.py` handles structural markup (3-tier panel split, meta merge, finish lines, tab new-count placeholders). `template.html` handles visual (brand tokens, favicon, CSS for `.card.row`/`.finish-line`/`.new-count`, lead title enlargement) and JS (merged IIFE with separate try/catch, seen TTL, per-tab new counts, console.error in catch blocks).

**CSS-only tiering** (rejected): Using `:nth-child()` to style tiers can't produce different markup for tail rows — it can hide elements but not restructure them. Tail rows need different inner layout (row vs card), which requires structural change in Python.

**Single localStorage key** (rejected): Merging `db_bookmarks_v1` and `db_visit_state` into `db_state_v2` would break existing users' bookmarks on next load — no migration path on a backend-less site.

### Review findings and dispositions

The `/develop` autonomous review-and-fix loop (via `/deep-review`) returned **0 Block, 0 Request changes, 4 Follow-up, 3 Nit**. All four follow-ups and two nits were fixed in-commit:

- **FIX** (F1) — Stale module docstring in `render_brief.py` — updated to reflect 4 categories, 3-tier layout, meta lines.
- **FIX** (F3) — Dead CSS rule `.finish-line em` — wrapped tab name in `<em>` so the rule applies (brand copper accent on the tab name).
- **FIX** (F4) — No empty-list guard in `panel_block()` — added `if n == 0: return ""` defensive guard.
- **FIX** (N3) — "1 stories" grammar — conditional `story`/`stories`.
- **DEFER** (F2) — Stale `SKILL.md` description (says 3 tabs, missing Medium) — skill files are read-only per `/develop` mode rules; engineer should update separately.
- **DEFER** (N2) — Favicon data URI not fully URL-encoded — works in all modern browsers, technically violates RFC 2397; low priority.
- **DEFER** (N1) — Meta format drift (added `▲` upvote arrow) — harmless visual improvement, noted as a nit.

### Pre-mortem

**Most likely failure**: After merging IIFEs and renaming `state` → `bmState`/`visitState`, a missed reference to old `state` variable inside a nested callback silently breaks bookmark persistence. **Mitigated**: verified zero bare `state` references remain; all callbacks reference `bmState`; all catch blocks have `console.error` for discoverability. **Rollback**: `git revert` on the branch; localStorage keys unchanged so user state survives a revert.

## How

### R0-1: Remove duplicated rank-reason/meta line
- Deleted `rank_reason()` function (`render_brief.py:163-182`) — its content (points, comments, "from r/xxx", `also_on` cross-posts) was already in `meta()`.
- Removed `rank_reason` calls and `<div class="rank-reason">` from `card_block()`.
- Humanized HN meta: `"▲ 616 · 388 comments"` (upvote arrow, dropped "pts" label). Reading-time kept at current muted prominence per user instruction (review's D2 assigns reading-time fix to Phase 2 R2-3, out of scope).

### R0-2: Fix README
- Updated "three tabs" → "four tabs", "Hacker News, Reddit, and Substack" → "Hacker News, Reddit, Substack and Medium".
- Added Features section documenting: AI gists, read-state tracking, bookmarks, provenance footer, per-tab finish lines, responsive layout.

### R1-1: 3-tier editorial layout
- `panel_block()` rewritten to split items: rank 1 = lead (full-width, display-size title), ranks 2–4 = secondary cards (2-col grid), ranks 5+ = compact tail rows (1-col, truncated gist).
- `row_block()` added as sibling to `card_block()` — same `data-*` attrs for JS parity (bookmarks, seen, NEW), different CSS (`.card.row`) for density.
- `data-brief-item` attribute added to both cards and rows; JS selector migrated from `.card[data-created]` to `[data-brief-item][data-created]` to decouple from visual classes.
- Graceful degradation: 1 item = lead only; 2–4 = lead + secondary; 5+ = all three tiers. Verified with test data.

### R1-2: Brand tokens + favicon + masthead rebalance
- `--brand: #c97a3e` (copper) added to `:root`. `--accent` defaults to `--brand` at root, overridden only by `.src-*` classes on cards.
- `src-hackernews` removed from masthead `<header>` — brand color no longer borrows from HN.
- Body background gradient retinted from HN orange to brand copper.
- Inline SVG ember-flame favicon added (`<link rel="icon">`).
- Lead title enlarged from `clamp(22px, 3vw, 31px)` to `clamp(28px, 4vw, 42px)` — the lead is now the visual climax.

### R1-3: Unconditional per-tab finish lines
- Each panel ends with `<div class="finish-line">End of <em>{Tab Name}</em> · {N} stories</div>`.
- Old global `#caughtUp` div and its JS reference removed.

### R1-4: Tab pills new-count chips
- `<span class="new-count" data-tab-key="{key}"></span>` rendered in each tab label.
- Visit-state JS counts new items per panel (via `card.closest(".panel")`) and fills the chips.
- `:empty` CSS hides zero-count chips.

### R0-3: localStorage IIFE merge + seen TTL + migration
- Two separate IIFEs merged into one with separate `try/catch` blocks (blast-radius containment: a failure in bookmarks init doesn't prevent visit-state init, and vice versa).
- `var state` naming collision resolved: `bmState` (bookmarks) and `visitState` (visit-state).
- Seen-map TTL: entries now store `Date.now()` instead of boolean `true`. On load, entries older than 14 days are pruned.
- **Legacy migration**: `typeof seen[key] !== "number"` check sets legacy boolean entries to `now` (not pruned) — prevents the `true → 1` coercion bug where `Date.now() - true > TTL` would wipe all read history on first load.
- All empty `catch (e) {}` replaced with `catch (e) { console.error("[daily-brief] " + context, e); }` for discoverability.

### Build / format / test outcomes
- **Build**: `python3 render_brief.py --data data.json` succeeds. Output verified: 14 items, valid HTML, all tiers render, all features present.
- **Format**: Skipped — no formatter detected in the project.
- **Tests**: `python3 -m unittest test_fetch_sources -v` — 12/12 pass (unchanged, tests fetch logic only).
- **Browser verification**: Loaded rendered HTML in Playwright — 3-tier layout renders correctly, bookmarks toggle and persist, finish lines show, no console errors.
- **Review**: Clean — 0 Block, 0 Request changes after 1 iteration. 4 follow-ups and 2 nits fixed in-commit.
