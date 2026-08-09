# Daily Brief — Design Review (Switchboard build, 9 Aug 2026)

Reviewed live at `http://localhost:8765/` at 1440×900 and 390×844, against `index.html`
and `render_brief.py`. Lens: consumer product design. Grounded in NN/g findings on
above-the-fold attention, F-pattern scanning, filter interaction cost, badge blindness,
and completion/closure signals.

Supersedes the layout sections of `design-review-2026-08.md` — the Phase-1 restructure
it recommended (lead → 3 cards → tail rows) has shipped and works. What follows is the
next layer.

---

## 0. The headline finding

**The page opens on the wrong tab, and it contradicts its own promise.**

`render_brief.py:263` picks the default tab by item *count*:

```python
best_i = max(range(len(present)), key=lambda i: (
    len(present[i][3]), -CATEGORY_PRIORITY.get(present[i][0], 99)))
```

Today "Off the Clock" has 11 items and The Wire has 6, so a page whose H1 reads
*"The day in tech, distilled"* opens on **r/homelabporn — "Forget Labporn, show me
some slutracks."**

Volume is not importance. This is the first impression, every single day, and it is
being decided by an accident of Reddit's posting rate. It undoes the ranking work the
whole pipeline exists to do.

**Fix:** default to `CATEGORY_PRIORITY` order, always. The Wire opens unless it is
empty. Tab order should encode editorial priority; the counts already tell the reader
where the volume is. (~2 lines.)

This is the single highest-leverage change on the page and it costs nothing.

---

## 1. Above the fold — 60% of the first screen is preamble

Measured hero height: **511px on a 390×844 phone.** The first story headline starts
below the fold. On desktop the hero is 320px and its **entire right half is empty**.

What occupies that space:

- A 4-line paragraph explaining what the product is (the reader knows — they came back)
- The sentence *"Toggle a source below to isolate it:"* — instructions for a control
  that is 40px away and self-evident

NN/g's finding is that attention decays sharply below the fold; the top of the page is
the most expensive real estate you own, and it is currently spent on self-description.

**Fix:**

- Delete the paragraph. Move "what this is / how bookmarks work" into a small `?`
  popover or the footer.
- Replace it with a **stat bar the reader actually wants**:
  `Sunday, 9 August · 30 stories · ~22 min · 6 new since Friday`
- Compress the masthead to a **sticky 48–56px bar** carrying logo, tabs, `Saved (n)`.
  Tabs stay reachable while scrolling — right now once you scroll, tab switching means
  scrolling back to the top.
- Target: first headline visible within 200px on mobile.

That alone converts the fold from "about this product" to "here is the day."

---

## 2. Visible action items — currently there are effectively none

You asked for this specifically, and it is the clearest gap.

The only actions on a card today are:

| Action | Current treatment | Problem |
|---|---|---|
| Save | 22×22px unlabeled outline icon, `#B0B0B0` on white | **2.17:1 contrast**; below the WCAG 2.5.8 24×24 minimum and far below the 44×44 touch target NN/g and Apple both recommend |
| Open / Discuss | 12px monospace coral text link | **3.50:1 contrast** — fails AA. The primary CTA is the least legible text on the page |

There is no mark-as-read, no dismiss, no share, no "save for weekend", no way to act on
a story other than leaving.

**Fix — give every card a real action row:**

```
┌────────────────────────────────────────────────┐
│ HACKER NEWS                          TOP STORY │
│                                                │
│ DeepMind's WeatherNext model achieves…         │
│ ✦ DeepMind's WeatherNext beats traditional…    │
│                                                │
│ ▲393 · 118 comments · 1d ago                   │
│ ┌────────┐ ┌──────────┐ ┌──────┐               │
│ │ Read → │ │ Discuss  │ │ Save │   ← 40px tall │
│ └────────┘ └──────────┘ └──────┘     labelled  │
└────────────────────────────────────────────────┘
```

- Labelled buttons, min 40px tall, 44px touch targets on mobile.
- `Save` flips to a filled state with the label `Saved` — visible system status, not a
  silently-filled icon.
- On the tail rows, actions can appear on hover on desktop but must be **always visible
  on touch** (hover does not exist there).

---

## 3. Contrast — measured, and a lot of it fails

Computed WCAG ratios against the actual rendered colors:

| Element | Color on white | Ratio | AA (4.5:1) |
|---|---|---|---|
| `open →` / `discuss →` links | `#E85A4F` | **3.50** | ✗ |
| Tail-row gist | `#909090` | **3.19** | ✗ |
| Card meta line | `#8E8E8E` | **3.28** | ✗ |
| "END OF THE WIRE" finish line | `#A8A8A8` | **2.38** | ✗ |
| Bookmark icon at rest | `#B0B0B0` | **2.17** | ✗ |
| Source kicker | `#777777` | 4.48 | borderline |
| Card gist | `#5A5A5A` | 6.90 | ✓ |
| Hero subtitle (on black) | `#9A9A9A` | 7.04 | ✓ |

The pattern is consistent and worth naming: **the content passes, every action and every
piece of metadata fails.** The things the reader is supposed to *do* are styled as if
they were decoration.

**Fix:**

- Darken the accent for use on white to **`#C8412F` (4.6:1)**. Keep the bright
  `#E85A4F` for the black hero, where it measures a comfortable 5.66:1 — two accent
  tokens, `--accent-on-dark` / `--accent-on-light`.
- Floor all metadata at `#6B6B6B` (5.3:1).
- The finish line should not be a 2.38:1 whisper (see §7).

Also: **one `:focus` rule in 122 CSS rules**, and it is on the new-group input. The
tabs are `<label>`s driving `opacity: 0` radios, so keyboard focus lands on an invisible
1px element — a keyboard user tabbing through has no idea where they are. Add
`:focus-visible` rings globally and `.tabinput:focus-visible + …` styling for the tabs.

---

## 4. The tail rows scan backwards

Tail rows are `grid-template-columns: 140px 1.35fr 1fr` — **the source name sits in the
leftmost column and the headline starts 372px in.**

The F-pattern says the left edge of the first line is where the eye lands. That position
currently holds `R/WHATSTHISPLANT`. The headline — the only thing that decides whether
the reader clicks — is indented past the fold of attention.

It also produces the ragged look visible in the screenshot, where
`COMPOUNDING DIVIDENDS` overflows its 140px column and collides with the title.

**Fix:** title first, hard left. Source demoted into the meta line under it, where it
already appears for Substack items anyway. Two columns, not three: `title + gist` /
`meta`. This also fixes mobile, where the gist is currently `display: none` — the gist
is the product's value-add and it is the first thing dropped on phones.

---

## 5. The source filter makes scanning worse, not better

`.f-dim { opacity: .14; filter: grayscale(1); }` — filtered-out stories stay in the
layout at 14% opacity. Filtering to "HN only" leaves you scrolling past 24 ghost cards
to find 6 real ones, and the ghosts are still keyboard-focusable and still read by
screen readers.

NN/g on filtering: the point of a filter is to reduce the set. Dimming increases visual
noise while removing none of the interaction cost.

**Fix:** `display: none` the non-matching items, show a `6 of 30 stories · clear filter`
line, and make the chips multi-select (right now selecting HN then Reddit just swaps —
"HN and Substack" is not expressible). Session-scoped persistence is the right call;
keep it.

---

## 6. Badge inflation and fake precision

**30 `AI GIST` chips on 30 items.** A label that appears on every item without exception
is not read after the third one — it has become texture. The honesty it was added for
(good instinct, worth keeping) is better served once, prominently, than 30 times faintly.

**Fix:** one line under the stat bar — *"Every summary below is AI-written from the
source."* Then a single quiet `✦` glyph on each gist for anyone who wants the per-item
reminder.

**Reading time is fabricated.** Every item on the page says "1 min read" or "2 min read"
— there are only those two values across 30 stories, because it is computed from the
fetched excerpt (`render_brief.py:159`), not the article. A number that is always the
same is worse than no number: it teaches the reader that the metadata is decorative.

**Fix:** either probe real content-length at build time, or drop it from cards and use
it only in the aggregate ("~22 min today"), where the error averages out and it powers
something useful (§8).

---

## 7. The finish line is the product's best moment and it is styled as a footnote

`END OF THE WIRE · 6 STORIES` — 10.5px, letterspaced, `#A8A8A8`, **2.38:1**.

This is the emotional payoff of a *finite* product. It is the one thing an infinite feed
structurally cannot offer, and it is the strongest argument for coming back tomorrow:
this ends, and you can finish it. Right now it is the least visible element on the page.

**Fix — make completion a designed moment:**

```
        ─────────────────────────────
              You're caught up.
     30 stories · 4 saved · back tomorrow, 8am

        [ Review your 4 saved ]  [ Yesterday's brief ]
        ─────────────────────────────
```

Unconditional, per-tab, and at real size. Give it the saved-items callback and the
archive link — the two things that extend the session past the last story.

---

## 8. Why would they come back? — the missing ritual layer

Today the only thing that changes between visits is the `NEW` badge, and a reader who
opens the brief at the same time each day never sees one. There is no continuity between
sessions: no unfinished state, no accumulation, no reason the product is *theirs*.

Three additions, in order of leverage per unit of work:

**a) Time budget — the strongest hook, and cheap.**
A three-way control in the stat bar: `3 min · 10 min · Everything`. It answers the
question the reader actually has at 8am ("do I have time for this right now?"), and it
makes the ranking *do something visible* — at 3 min you get the lead plus two, at 10 min
the cards, at Everything the tail. Pure client-side, `data-rank` is already on the
elements. This converts the brief from "a page of links" to "a thing that fits my
morning", which is what makes a ritual.

**b) Continuity across editions.**
`4 unread from yesterday` as a chip in the masthead, and let the reader open them. Right
now yesterday's brief is a dead archive link. A reader who missed Friday should be
greeted with Friday, not asked to go looking.

**c) The saved list should pay off.**
Bookmarks currently go into a drawer and are never mentioned again. Give the reader a
weekly moment — Sunday's brief opens with *"You saved 11 things this week. 3 unread."*
That is the product remembering them, which is the entire difference between a page and
a habit. It also makes bookmarking feel worth doing, which it currently does not.

Explicitly **not** recommended: streaks, badges, notification nags. Wrong audience —
this reader will resent being gamified. Continuity and closure, not points.

---

## 9. Theme and layout — keep the direction, fix the void

The black-hero-over-white-sheet is genuinely good and more distinctive than the previous
dark theme. Two problems:

1. **The sheet floats in an infinite black void.** On Off the Clock the black surround is
   ~40% of the total page area, and it reads as unfinished rather than intentional.
   Either let the sheet run full-bleed below the hero (black band on top, white page
   below — a masthead, which is what it wants to be), or cap the void with a black
   footer band so the composition closes.

2. **The empty right half of the hero.** With the paragraph gone (§1), that space is the
   natural home for the stat bar and time budget — a genuine two-column masthead instead
   of a left-aligned block with dead space beside it.

Keep: the single-accent discipline, source-identity-as-text-not-color, the mono/sans
pairing, the lead card's coral left edge. Those are working.

---

## 10. Priority

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | Default to The Wire, not the fullest tab | ~2 lines | Fixes the first impression, daily |
| 2 | Labelled action row on every card (Read / Discuss / Save), 44px targets | S | You asked for visible actions; there are none |
| 3 | Contrast pass — `#C8412F` on white, metadata floor, focus rings | S | Every action currently fails AA |
| 4 | Kill the hero paragraph → stat bar; sticky compact masthead | M | Recovers the fold |
| 5 | Time budget control (3 / 10 / all) | M | The return-visit hook |
| 6 | Tail rows: title-first, keep gist on mobile | S | Fixes the scan path |
| 7 | Filter hides instead of dimming; multi-select | S | Filter currently adds cost |
| 8 | Designed completion state + saved-list callback | S | The finite-product payoff |
| 9 | AI GIST once, not 30×; fix or drop reading time | S | Badge blindness, fake precision |
| 10 | Close the black void; two-column masthead | M | Composition |

Items 1–3 are a single afternoon and fix the credibility problems. 4, 5 and 8 are the
redesign that changes whether the reader comes back.

No pipeline changes required for any of it except #9's reading-time probe.

---

## 11. Prototype

All ten items are implemented against today's real `data.json`:

- `.claude/skills/daily-brief/template-v2.html` — the redesigned template
- `render_prototype.py` — fills it; imports ranking/date/provenance helpers from
  `render_brief.py` so there is one implementation of the data logic
- `_redesign.html` — the built page (`python3 render_prototype.py`)

The production path is untouched: `render_brief.py` and `template.html` are unmodified
and still render `index.html` exactly as before.

Measured against the current build, same edition, same data:

| | Current | Prototype |
|---|---|---|
| Opens on | Off the Clock (r/homelabporn) | The Wire |
| Mobile hero height | 511px | 241px |
| First headline (390px viewport) | ~675px | ~510px |
| Primary action above the fold (mobile) | none | `Read the story →` |
| Save target | 22×22px icon | 40px labelled button |
| Action-link contrast | 3.50:1 | 4.94:1 |
| Metadata contrast | 3.19–3.28:1 | 5.33:1 |
| Lowest measured ratio on the page | 2.17:1 | 4.94:1 |
| `AI GIST` badges | 30 | 0 (one note + a `✦` glyph) |
| Filtered-out stories | dimmed, still scrolled past, still tabbable | removed; `tabindex="-1"` |
| Source filter | single-select | multi-select + clear |
| `:focus` rules | 1 of 122 | global `:focus-visible`, incl. the tab labels |

Verified interactively: `Top 3` trims Off the Clock 11 → 3 with an honest
"8 more below your cutoff · Show everything →" escape hatch; the skim readout follows
(≈5 min → ≈2 min); the completion block recounts to match; `Reddit` + `Substack`
compose to 11 of 11; `clear` restores.

Open question for the next pass: the `Show` control is per-section, so "Top 3" on a
6-story Wire and an 11-story Off the Clock trim by different amounts. A single global
budget spent across sections in rank order would be truer to "I have 3 minutes" — worth
trying once the shape is agreed.
