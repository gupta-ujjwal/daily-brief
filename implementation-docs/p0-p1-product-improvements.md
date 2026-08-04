# p0-p1-product-improvements

> Implemented via `/brainstorm` -> `/develop` on 2026-08-04.

## What

A mix of bugfix and feature across 5 files in the daily-brief pipeline: `fetch_sources.py` (no-signal scoring cap), `automation/gen_gists.py` (gist contract + fallback hardening), `render_brief.py` (category re-scoring, fullest-tab default, sparse-tab merge, dates, reading-time, AI label, rank reason, atomic write), `.claude/skills/daily-brief/template.html` (bookmarks export/import, mobile overlap fix, read-state + "caught up"), and `sources.json` (category weights). Three independently-revertable commits. No API/CLI/DB changes; the external surface is the rendered daily brief HTML.

## Why

The product review (`product-review.html`) identified two critical problems and seven high/medium gaps. The root cause of the most damaging issue (F2: personal Reddit posts out-ranking real news) was a scoring bug: Reddit's `home-rss` tier produces items with `points:0, num_comments:0`, and `score_source()` gave them neutral engagement scores, so a fresh personal post scored 0.92 globally -- rank #2. The fix is two-layered: a no-signal cap (items with zero engagement in a group that has engagement signals are capped at 0.6 `score_norm`) and a post-categorization re-scoring pass in `render_brief.py` that applies per-category weights (`personal: 0.5`) from `sources.json`.

Three approaches were considered: (1) sequential pipeline extension with a re-scoring pass in `render_brief.py` (chosen), (2) rewrite the scoring engine to be category-aware from the start in `fetch_sources.py` (ruled out -- would require calling Claude from the fetch step, breaking pipeline separation), (3) ship P0 only (ruled out -- user requested P0+P1 together).

Two fresh-context review sub-agents (develop-perspective, reliability-tenets) reviewed the plan. Key findings folded in: re-scoring moved from `gen_gists.py` to `render_brief.py` to preserve the AI step's pure contract; gist re-prompting dropped (fallback-only to avoid doubling Claude cost); fail-safe re-scoring emits an HTML sentinel comment on failure; atomic write prevents bad renders from corrupting last-known-good files; 3 independent commits for blast-radius limits. Deferred: post-render anomaly detection (P2), pipeline runtime delta (negligible).

Pre-mortem most-likely failure: `rescore_by_category()` reads `sources.json` -- a syntax error (trailing comma) could crash the pipeline if the try/except is too narrow. Mitigated by wrapping the entire read+parse+apply in try/except with stderr warning + `<!-- rescoring-skipped: <reason> -->` sentinel. Rollback: `git revert` per commit; `category_weights` key removable from `sources.json`; dated briefs never overwritten; `index.html` protected by atomic write.

## How

### Commit 1: P0 scoring + rendering fixes (`3886f26`)

1. **No-signal cap** (`fetch_sources.py:687-688`): In `score_source()`, items with `points==0 and num_comments==0` in a group where `has_signal=True` are capped at 0.6 `score_norm`. Editorial sources (Substack/Medium, where the entire group has no signals) are NOT capped -- the cap only catches items that should have engagement but don't. Refined from the plan after discovering the original cap would unfairly penalize editorial sources.

2. **Category re-scoring** (`render_brief.py:82-106`): New `rescore_by_category()` function called from `main()` after loading `data.json`, before bucketing. Reads `ranking.category_weights` from `sources.json`, multiplies `rank_score` by the category weight, recomputes `feed_score = rank_score / new_top`, re-sorts items in-place. Fail-safe: stderr warning + `<!-- rescoring-skipped -->` HTML sentinel on missing/malformed `sources.json`.

3. **Fullest-tab default** (`render_brief.py:249-252`): `tabs_block()` now sets `checked` on the tab with the most items, not always index 0. Tie-break: industry > learning > products > personal (via `CATEGORY_PRIORITY` dict).

4. **Sparse-tab merge** (`render_brief.py:295-297`): `products` with < 4 items folds into `learning`. `personal` is exempt (coda tab).

5. **Atomic write** (`render_brief.py:325-327`): Render to `.tmp` file, then `os.replace()` -- prevents a bad render from corrupting the output.

6. **sources.json**: Added `"category_weights": {"industry": 1.0, "learning": 1.0, "products": 0.95, "personal": 0.5}`.

7. **Tests** (`test_fetch_sources.py`): `NoSignalCap` test class verifying cap applies to mixed groups but not editorial groups.

### Commit 2: P0 template + gist fixes (`c83a0b8`)

8. **Bookmarks export/import** (`template.html`): Export downloads state as JSON via Blob + download link. Import reads file, merges items and groups without duplicating.

9. **Mobile overlap fix** (`template.html @media`): `.bm-tab` reflows to bottom-right FAB on <=720px instead of fixed vertical handle that overlaps the wrapped tab bar.

10. **Gist fallback hardening** (`gen_gists.py:101-110`): Instead of defaulting ALL items to `category:"industry"` on Claude failure, infers category from source/kind (Show HN -> products, Reddit -> personal, else learning). Uses `title[:150]` as gist fallback. Short gists (<60 chars) fall back to `text[:150]` or first comment[:150] -- no re-prompting.

### Commit 3: P1 ritual features (`5cb677c`)

11. **Date on every card** (`render_brief.py:relative_date()`): Renders `created_at` as "2h ago", "3d ago", or "Aug 2023" for old items.

12. **Reading-time estimate** (`render_brief.py:reading_time()`): From text + comment word count at ~200 wpm. Hidden if < 50 words.

13. **AI gist label** (`render_brief.py:card_block()`): Small "AI gist" tag before the gist text.

14. **Rank reason replaces meter** (`render_brief.py:rank_reason()`): One-line "why you're seeing this" (e.g., "451 pts on HN", "from r/bangalore", "also on Hacker News"). Dead `width()` function removed.

15. **Read-state + "caught up"** (`template.html`): `db_visit_state` in localStorage tracks `lastVisit` + `seen` URLs (try/catch all access). Seen cards dimmed; new-since-last-visit cards get a NEW badge. "You're caught up for today" shown only when there are 0 new items and the reader has visited before.

16. **Gist contract** (`gen_gists.py` prompt): 90-150 char minimum, "why it matters" framing for lead items.

### Review result

Deep review (Step 7.5): **Block: 0, Request changes: 2, Follow-up: 1, Nit: 4** -- clean. Two Request-changes findings were fixed in the amend: (1) "caught up" message was shown unconditionally -- now checks `newCount === 0 && lastVisit > 0`; (2) dead `width()` function removed, redundant `os.replace`/`os.rename` if-else simplified to `os.replace` only. Follow-up (seen-object pruning in localStorage) deferred -- try/catch handles quota-exceeded gracefully.

### Build / format / test

- **Build**: SKIPPED -- pure Python, no compile step. Syntax-verified via `py_compile`.
- **Format**: SKIPPED -- no formatter detected (no black/ruff config).
- **Tests**: PASSED -- `python3 -m unittest test_fetch_sources -v` -- 12/12 OK (10 existing + 2 new NoSignalCap tests).
- **Render verification**: `python3 render_brief.py --data data.json` produces valid HTML with all new elements (AI labels, rank reasons, dates, read-state JS, export/import buttons).
