# Design prompt — Caarya profiling

Paste everything below the line into Claude, from the project root.

---

## The job

Restyle this app's visual design. **Presentation only — do not change any
behaviour, copy, scoring or markup structure.** The app works and is tested; this
is a skin, not a rewrite.

## What the app is

Caarya profiles students on their skills and connects them to companies. This is
the student-facing half: a five-step form (your details → role → areas of work →
jobs you'd own → rate yourself) that ends in a profile report telling a student,
honestly, whether what they *want* to do matches what they're actually *good at*.

It's used by Indian undergraduates, mostly on phones, often for the first time,
often nervous about the answer. The report carries real news — sometimes "you're
ready", sometimes "you're not there yet", sometimes "you picked the wrong thing".

## The design direction

**Playful, bright, and orange.** Right now it's a muted terracotta on warm
off-white — competent but flat and a bit severe. It should feel like something a
21-year-old actually wants to open: energetic, confident, warm, modern.

Push on: a genuinely bright orange as the primary, generous rounding, confident
type scale with real contrast between the big moments and the quiet detail,
motion that rewards progress, colour used with conviction rather than sprinkled.

**The one hard constraint on "playful":** this report tells some students they're
not ready yet. Playful must read as *warm and encouraging*, never as *jolly about
bad news*. No confetti on a low score, no cartoon mascots delivering rejection, no
emoji doing the work that words should do. The tone to hit is a good teacher who
likes you and is being straight with you.

## Stack

Vanilla HTML/CSS/JS, no build step, no framework, no dependencies. Fonts may come
from Google Fonts. Everything else stays inline in:

- `static/css/styles.css` — the entire stylesheet, wizard and report both
- `static/index.html`, `static/report.html` — shells only, edit sparingly
- `static/js/*.js` — **avoid**, except where a purely visual element must be added

## Work through the token system

`styles.css` starts with a `:root` block of custom properties and a
`@media (prefers-color-scheme: dark)` block that redefines them. **Change the
token values there; do not scatter new hex codes through the rules.** Both blocks
must stay in sync — dark mode is not optional and must look deliberate, not
inverted.

Current tokens: `--bg --surface --surface-2 --border --border-strong --ink --ink-2
--ink-3 --accent --accent-soft --accent-ink --good --good-soft --warn --warn-soft
--bad --bad-soft --radius --radius-sm --shadow --font --mono`. Add tokens if you
need them; don't remove any that are in use.

### The colour trap to solve

The accent is already orange-ish (`#b2542b`), and the app uses four *semantic*
band colours that must stay instantly distinguishable from each other **and** from
the accent:

| Band | Means | Currently |
|---|---|---|
| `strong` | Well ahead | green |
| `emerging` | Ready to start | accent orange |
| `stretch` | Almost | amber |
| `gap` | Not yet | red |

Make the accent brighter and `emerging`, `stretch` and the accent start colliding.
Solve this deliberately — reassign the band ramp, change its hues, or separate it
from the brand accent entirely. Don't let "almost" and "ready" look the same.

Colour must never be the only signal: every score already carries a text label and
a number. Keep it that way.

## Components to attend to

**Wizard:** the left phase rail with its numbered dots, big step headings, choice
cards for roles/areas/jobs (`.choice`, selected state via `aria-pressed`), the
1–5 rating rows and their scale buttons (`.rating-row`, `.scale`), chips and tag
inputs, the fixed bottom nav bar with the progress track.

**Report:** the hero card carrying the one-sentence verdict (`.hero`, tinted per
verdict via `.hero.aligned/.partial/.redirect/.early/.insufficient`), the numbered
action list (`.actions`), the score meters with their "ready starts at 60" tick
(`.meter-row`, `.meter-track`, `.meter-fill`, `.meter-ready`), the 2×2
interest-versus-ability grid (`.quad`), the "Show me the numbers" disclosure
(`details.disclosure`), the follow-up accordion (`.followup-*`), pills (`.pill`
with `.strong/.emerging/.stretch/.gap/.neutral/.chosen`).

The hero is the single most important element on the page. It should land.

## Do not break

- **Never rename or remove these class names** — JavaScript queries them:
  `.err .field .field.invalid .rating-row .rating-row.unanswered .chip .tag
  .actions .hero .hero-line .hero-detail .meter-row .meter-score .meter-ready
  .quad-box .followup-head .followup-body .disclosure .view-toggle .no-print`
  You may add classes freely.
- **`aria-pressed`, `aria-expanded` and `<details>/<summary>`** drive real state.
  Style them, don't replace them with divs.
- **Keyboard and focus:** every control keeps a visible focus ring. Don't remove
  outlines without replacing them with something better.
- **Contrast:** body text and any text on a coloured fill must clear WCAG AA
  (4.5:1), in both themes. Bright orange on white fails easily — check it.
- **Print:** `@media print` must still produce a clean page; the disclosure opens
  automatically before printing.
- **Phone width:** the whole thing must work at 390px with no horizontal scroll.
  The meters and the action list are the two things that break first.
- **No new runtime dependencies.** Google Fonts is the only permitted external.

## Verify before you report back

```bash
python3 app.py                  # http://localhost:5000
python3 seed_profiles.py        # 3 example students, second terminal
python3 -m pytest tests/test_scoring.py
```

Then look at what you made:

- `/report/1` (a student who's ready), `/report/2` (one told to reconsider),
  `/report/3` (one who rated everything 5) — all three hero states.
- The same reports in dark mode and at 500px wide.
- `/` and walk the wizard: choice cards, the rating grid, the progress bar.
- `/report/1?view=company` — the denser recruiter view, which must stay readable.

Screenshot each in headless Chrome and actually look at them before saying you're
done. `README.md` explains the product; the report's job is to be understood on
first read, so if a change makes it prettier but harder to parse, it's wrong.
