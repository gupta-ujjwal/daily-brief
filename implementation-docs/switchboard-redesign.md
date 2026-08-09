# Switchboard redesign

> Implemented via `/brainstorm` → `/develop` on 2026-08-09.

## What

Replaces the copper/gold dark theme of the daily brief with the **Switchboard** design: a black hero zone (brand mark, tabs, source filter chips) over a single white content sheet, monochrome discipline (no per-source colors), one coral accent `#E85A4F` for all interactive elements, Inter system stack, and a strict 4px-based spacing scale.

Touches two files only:

- `.claude/skills/daily-brief/template.html` — full CSS/chrome rewrite; adds source filter chips with sessionStorage persistence.
- `render_brief.py` — emits new placeholders `{{TAB_RADIOS}}` / `{{TAB_LABELS}}` / `{{SOURCE_CHIPS}}` / `{{PANELS}}`; lead/story/row renderer restructured.

No changes to fetch, gist, categorize, bookmark logic, archive page, or automation. The change is pure presentation + one new interaction (source filter).

## Why

The previous theme grew piecemeal across ~12 fixes and had **spacing chaos** (15+ arbitrary padding values, no scale), **flat hierarchy** (lead, story, and row all breathed at the same 26px), **cramped interior** (badge→title→gist separated by one shared 12px flex gap), and a **copper/gold** palette the owner disliked after living with it. An audit (`git log` on `template.html`) confirmed the trajectory: six defects fixed one at a time without a unifying system.

Three directions were mocked up in `notes/redesign/{a,b,c}-*.html`:

- **A (Newspaper)** — most conservative; serif display; cobalt accent.
- **B (Switchboard)** — all-sans, elevated cards, hover-dim interactions, red accent.
- **C (Broadsheet)** — table-dense index, inverted lead band, green accent.

User picked **B**, with a coral tweak (`#F03E3E → #E85A4F`) when the red read as "siren" on dark. The plan's other choices: no per-source colors, no serif, keep the original tagline ("The day in tech, distilled" — user's earlier override), add clickable source filters because they looked "tactile."

## How

Each section's decisions, in implementation order.

### Hero + Sheet structure

- `.masthead` block deleted; `.hero` is now a flex column containing `.hero-top` (30px outlined "DB" mark + wordmark | date), `h1` with coral `em`, `.sub` standfirst, then `.hero-bottom` with tabs on the left and source chips on the right.
- `.sheet` is the white content zone: `border-radius: 16px`, `margin: 0 var(--s5)`, `padding: var(--s6)`, deep black shadow. All three story tiers and the hairline/frayed footer live inside it.
- Radios are emitted **before** the `<header>` element (not inside it) so the CSS-only `:checked ~ <sibling>` selector chain can reach both the tabbar inside `.hero` and the panels inside `.sheet`. The renderer splits the old single `{{SECTIONS}}` into `{{TAB_RADIOS}}` + `{{TAB_LABELS}}` + `{{PANELS}}` to match.

### Tiers reskinned

- **Lead**: white card, `border-left: 5px solid var(--accent)`, kicker + `Top story` tag row, 34px title, meta line. Same structure as plan's `lead_block`.
- **Grid**: 3-col cards, `--s4` (16px) gap, `hover: translateY(-3px) + shadow`, kicker-rest-from-plan (no per-source colors, monospace uppercase kickers).
- **Tail rows**: 3-col grid `[kicker 140px | title | gist]`; meta spans full width at `grid-column: 1/-1`; gist clamps at 2 lines (see *Deviations* below).
- **Finish line**: centered mono caption, same `· N stories` phrasing, inside sheet.

### Source filter chips

- Static markup slot `{{SOURCE_CHIPS}}` in the hero; renderer emits `<button class="chip" data-src="X">Label <span class="n">N</span></button>` for each source with a non-zero count.
- Clicking a chip: non-matching `[data-brief-item]` elements get `.f-dim { opacity: .14; filter: grayscale(1); }`; session-scoped via `sessionStorage.db_source_filter`; clicking active chip again clears. Filter persists across tab switches because JS queries all panels, not just the visible one.
- A `filterNote` span shows "· filtered" when active (styling via new `.chip-note` class — separate from `.chip` to avoid an accidental click-handler see review).

### New/seen, bookmarks, AI-tag, provenance

- `.item` is the shared class on all three tiers (replaces the old `.card` family); visit-state JS selector broadened from `a.card-title` to `a.card-title, a.story-title, h2 a, .row-title a, h3 a` (the old selectors are dead code — harmless).
- `.seen` dim: 0.72 opacity (was 0.82) to compensate for the higher contrast of the white sheet.
- Bookmark button, drawer, pull-tab, group, export/import logic all unchanged; only colors/paddings restyled to match (coral on active, white drawer instead of dark panel, `--s*` for major spacing).
- AI-gist tag: gray-on-`#f4f4f3` (was copper-on-`--panel2`); provenance footer: black hairline, no accent color except degraded state.

### Deviations from the plan, called out

1. **Tagline kept as "The day in tech, distilled."** Plan's hero read "Front page of the engineering internet" — user picked accent option 2 in the same message and did not ask for a copy change. Silence = keep existing.
2. **Git dim uses 2-line clamp, not the plan's "single-line ellipsis"**. The reference mockup (`b-switchboard.html`) had 1-line; in the smoke render it truncated HN titles materially (only ~30 visible chars against 140px kicker column). 2-line clamp preserves gist signal; flagging for user review — 30-second change if single-line preferred.
3. **Spacing tokens applied to layout, not to small control padding**. Plan's acceptance check literally read "grep finds no raw px spacing" — but its own reference HTML uses `padding: 8px 12px` on chips and `padding: 9px 15px` on tabs (values not in the 4px scale). Scales were applied to hero/sheet/card/row/grid/lead (all tokens), and fine-grained control padding stayed raw-px, matching the reference. Captured as follow-up F2 in review.
4. **`{{SOURCE_CHIPS}}` placeholder name, not `{{SOURCE_COUNTS}}`**. The placeholder emits chip HTML, not just count text — clearer name. Captured as F2.

### Review loop — autonomous, 2 iterations

Iteration 1 surfaced 1 **Block** + 3 **Request changes** + 7 **Follow-up** + 5 **Nit**:

- **Block B1**: tab active-pill CSS selector (`~ .hero-bottom .tabbar .tab-*`) couldn't match — `.hero-bottom` is nested inside `.hero`, not a sibling of the radios. Tabs switched content but never showed the active state. Fixed by scoping to `~ .hero .tab-*`.
- **Request R1**: `.row` missing `position: relative` so NEW badges on tail items anchored to the viewport. Fixed.
- **Follow-up F4 (upgraded)**: `filterNote` span had `class="chip"`, so it got the click handler and `.on` toggle — clicking it would silently clear the filter. Restyled as `chip-note`.

Iteration 2 review confirmed **Block 0**, no new issues. Remaining deferred: R2 (control-padding tokenization), R3 (2-line vs 1-line gist), F2-F7, N1-N5.

### Verification

- `python3 -m py_compile render_brief.py` — clean.
- `python3 -m unittest test_fetch_sources` — 12/12 OK (fetch layer unchanged).
- Smoke render from `notes/redesign/directions-data.json` — produces valid HTML, zero surviving placeholders, all tiers render.
- Browser verify: tab switching works (radio check + white pill confirmed), chip filter isolates Reddit items across all tabs and persists across tab switches, bookmark add/remove works, `filterNote` no longer steals clicks, mobile 390px stacks correctly (tab pills no longer wrap after `flex: 1 1 auto` fix mid-implementation).
