# Daily Brief — Design & UX Review (PM / UX lens)

> Reviewed against the 6 Aug 2026 edition, `template.html`, `render_brief.py`, `fetch_sources.py`, `gen_gists.py`, and the prior artifacts (`product-review.html`, `roadmap.md`). Scope: functional + non-functional design, theme, layout, look & feel, kept against the product's true value.

---

## 1. First-principles frame: the true value

**"Your sources, ranked for you, transparently — the AI decides what's worth your time, and you read the original. Finite, finishable, and yours."**

Three jobs the reader hires this product for:

1. **Orient in < 2 minutes** — what happened in my tech world since yesterday?
2. **Trust the triage** — ordering and gist must be legible and honest, or the reader goes back to raw HN.
3. **Finish** — the ritual completes; "done", not an infinite feed.

Track assumption: **Track A — superb personal tool**, single reader-owner, zero backend. Everything fits the single-file static architecture.

## 2. Status check vs. prior review (what's already shipped)

| Prior finding | Status |
|---|---|
| F1 — default tab opens on emptiest bucket | **Fixed** — `tabs_block()` selects the fullest tab (`render_brief.py:245-246`) |
| F2 — personal items out-rank news | **Mostly fixed** — `category_weights.personal: 0.5` rescoring (`render_brief.py:82-106`) + cap on zero-signal items (`fetch_sources.py:687-688`) |
| F3 — no per-item date / reading time | **Shipped** — relative dates + read-time on every card |
| F4/P1-5 — read-state, NEW badges, "caught up" | **Shipped** (template visit-state IIFE) |
| F5/P0-3 — bookmark export/import | **Shipped** (JSON out/in) |
| F6/P1-2 — gist contract 90–150 chars + lead framing | **Shipped** in prompt + `<60`-char repair fallback (`gen_gists.py:130-134`) |
| P1-3 — AI gist labeling | **Shipped** (AI GIST tag) |
| P1-4 — mystery score meter | **Shipped in degraded form** — replaced with `rank_reason` text, but it now **duplicates the meta line verbatim** (see N2 in §3.C) |
| F8/P0-4 — mobile bookmark overlap | **Fixed** — pill sits bottom-right, fully in-viewport at 390px; minor residual occlusion of the *last card's* action row at page bottom |
| README staleness | README still says "three tabs… HN, Reddit, Substack" — product has **4 tabs and 4 sources** |

Remaining work is design-layer, not bug-fixing.

## 3. Design review by lens

### A. Theme & visual identity — functional, but the brand doesn't know what it is

- Warm "ember ledger" dark theme is distinctive and pleasant. **Keep it.**
- No brand mark, no favicon, no identity — "Daily Brief" is a category, not a product name. A morning ritual object needs a mark.
- **Color system conflict**: masthead runs on HN orange (`header.masthead.src-hackernews` → `--accent: var(--hn)`), so the global brand color is *borrowed from a source*. Brand accent and source accents should be separate tokens.
- Four tab hues + four source hues = **8 chromatic meanings**; source color is redundant with the already-good text badge.

### B. Layout & hierarchy — the page sells "list", not "edition"

Biggest design-level miss. The product is an **edition** (a newspaper) but shaped like a **feed** (a dashboard).

1. **Lead story is undersold** — masthead dwarfs the lead card. The lead should be the visual climax: larger display type, standfirst gist, above the fold.
2. **Uniform card sameness** — rank 2 and rank 14 look identical. Ranking is the core intellectual work and the layout hides it. Needs graded hierarchy: lead → 2–3 secondary "column" cards → compact list rows for the tail.
3. **Card grid wastes the signal** — two-column grids are for browsing equal-weight items; a ranked list wants headline-list density. 14 Deep Dives as cards = ~5 viewport-heights of scrolling for ~14 sentences.
4. **"Top" tag is weak** — muted mono "TOP" loses to the bookmark icon. Should say what makes it top ("most discussed today · 388 comments").

### C. Interaction design — tabs are the wrong default; done-state is buried

1. **CSS-only tabs hide content** — no URL state (can't deep-link to a tab), no ARIA tab semantics (radio+label, not `tablist/tab/tabpanel`), Ctrl+F can't search hidden panels.
2. **Tab counts are good; new-since-visit counts would be better** — visit data already exists; pills could show "3 new" per tab.
3. **"Caught up" moment is misplaced and conditional** — only renders when `newCount === 0 && lastVisit > 0`. First-time readers and readers with any new item never see a finish line. Should be **unconditional and per-tab**: "End of Deep Dives · 14 stories · you're done here."
4. **Read-state is binary and instant** — seen cards dim to 50% opacity, fighting readability for revisits. Softer: dim the newness signal, not the content. Also `seen` keys grow unbounded in localStorage.
5. **No keyboard affordances** — j/k/o/b would fit the HN-reader audience perfectly.
6. **Bookmark drawer discoverability** — ghost-outline icon with no first-time hint; drawer title "Saved ★" vs handle "Bookmarks" — pick one name. First save should open the drawer once.
7. **Merged sparse tabs lose category semantics** — a products item folded into Deep Dives gets no cue that it was "Worth a Try" (`render_brief.py:291-293`); add a small category chip on merged items.

### D. Content design — gists are good; meta is noisy; titles are raw

1. **N2 (shipped defect): duplicated metadata** — every HN card shows `616 pts · 388 comments` in meta AND `616 pts on HN · 388 comments` as `rank_reason` beneath (`render_brief.py:163-182` vs `185-210`). Fix: one humanized line — "▲ 616 · 388 · 10h ago · HN" — and reserve the second line for genuine *why-you're-seeing-this* info (cross-posts, provenance).
2. **Reading-time is broken by construction** — computed from the *fetched excerpt/comments* (`render_brief.py:150-160`), not the article; everything says "1–2 min read". Either drop it, or make it honest: fetch content-length at build time per kept item (~30 lines in the fetch layer).
3. **Gists are genuinely good now** — argumentative, honest AI-GIST label. Refinements: (a) the "AI gist" chip reads like a warning label; quieter treatment (italic gist + small ✦ glyph with tooltip) conveys the same honesty with less visual tax; (b) lead framing is inconsistent — pass `is_lead` candidates explicitly to the gist prompt rather than positional "FIRST item in each category".
4. **Titles are unedited** — "Summer AI Coding Updates ☀️" keeps emoji; Reddit titles run 3 lines. Clamp (`line-clamp: 2`) and normalize prefix cruft ("YSK:", "[BUY]") at gist time.
5. **"Off the Clock" is a design success** — the separate tab with its own accent genuinely solves newsroom-vs-group-chat at the presentation layer. Protect it.

### E. Non-functional review

| Area | Verdict |
|---|---|
| **Accessibility** | Tabs lack ARIA semantics; no skip-link; sparse focus styles; NEW badge is pseudo-element text (screen-reader-invisible — needs visually-hidden text or aria-label); `prefers-reduced-motion` unhandled |
| **Mobile** | Single column works; tab pill fixed in view; tab bar wraps with orphan words (cosmetic); guarantee clearance between pill and last card actions |
| **Performance** | Single file, no assets, ~50KB — superb; the *build* is the slow part (serial Reddit comment fetches) |
| **Security** | Everything escaped via `esc()`; localStorage origin-scoped; fine for single-file |
| **Resilience** | Degraded sources are visible content (provenance footer) — excellent pattern, keep |
| **Global state** | Two separate localStorage IIFEs (bookmarks, visit-state); `seen` map needs TTL/age pruning |

## 4. Improvement plan

### Phase 0 — Hygiene (hours)

- **R0-1** Remove duplicated rank-reason/meta line; merge into one humanized meta row.
- **R0-2** Fix README (4 tabs, 4 sources, current feature set).
- **R0-3** Prune `seen` map by age; unify the two localStorage modules.

### Phase 1 — Make the edition look like an edition (core design work)

- **R1-1** Restructure each tab: full-width editorial lead (display-size title, standfirst gist), 2–4 secondary cards, then compact headline-list rows for the tail. Highest-leverage change — makes ranking *visible*.
- **R1-2** Rebalance the masthead; separate brand-accent tokens from source-accent tokens; add a favicon/identity mark.
- **R1-3** Unconditional per-tab finish line ("End of Deep Dives — 14 stories").
- **R1-4** Tab pills show new-count chips alongside totals.

### Phase 2 — Interaction honesty (small JS)

- **R2-1** Replace CSS-hack tabs with ~40 lines of JS: real ARIA tabs, arrow keys, `#tab=deep-dives` URL state.
- **R2-2** Keyboard navigation (j/k/o/b).
- **R2-3** Fix or remove the fake reading-time (build-time probe vs drop).
- **R2-4** Clamp long titles; strip Reddit prefix cruft at gist time.
- **R2-5** Bookmark drawer on-boarding: first-visit hint; first save opens drawer once.

### Phase 3 — Comfort & access

- **R3-1** Light theme (reference implementation in `product-review.html`), `prefers-color-scheme` + toggle.
- **R3-2** `prefers-reduced-motion`, focus-visible rings, skip-link, screen-reader text for NEW/seen states.
- **R3-3** Soften seen-treatment (badge, not 50% opacity).
- **R3-4** Mobile clearance between bookmark pill and final card.

### Phase 4 — Deliberate stretch (only if desired)

- **R4-1** Edition-level client-side search (enabled by R2-1 rendering-but-hiding tabs).
- **R4-2** Markdown export of bookmarks (Obsidian/Readwise path).
- **R4-3** "Also on" cross-post chips (data already exists).

### Explicit non-goals

No full summaries behind the gist; no streaks/engagement mechanics; no social features; no backend. The single-file static architecture is a design asset.

### Biggest revamp endorsed

Phase 1's layout restructure — no pipeline change, same `data.json`, but converts the page from dashboard-of-cards into the morning-edition object the product already is in spirit.
