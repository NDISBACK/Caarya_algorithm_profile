# Caarya — Student Profiling Form

The student-facing half of Caarya: a form that asks what a student wants to get
paid for, what they're actually good at, and then tells them honestly whether
those two things agree.

The company-matching dashboard and the admin portal are separate builds. This one
is written so both can plug in: the taxonomy and the form questions live in JSON,
and every completed profile is stored with its computed report ready to read.

## Run it

Two separate programs, sharing the data on disk:

```bash
pip3 install -r requirements.txt

python3 app.py          # students   → http://localhost:5000
python3 admin_app.py    # admin      → http://localhost:5001
```

`app.py` is the public one. It contains no administrative code at all — the
taxonomy editor is a different program, so the two can be deployed and
firewalled independently. They read and write the same `data/taxonomy.json` and
`caarya.db`, which means they need the same machine or the same volume; an edit
in the admin is live for the next student who loads the form.

> **The admin has no authentication yet.** Don't expose its port. When you add a
> login it goes in `admin_app.py::_authenticate`, the single hook every admin
> request already passes through.

If it refuses to start, something else is already on the port — most often an
older copy of this server, which would otherwise keep answering your browser with
stale code. The error says how to find and stop it, or use
`CAARYA_PORT=5050 python3 app.py`.

`GET /api/health` tells you which build is actually answering (pid, start time,
and a fingerprint of the source files) — worth checking first if the UI is doing
something the code says it shouldn't.

In a second terminal:

```bash
python3 seed_profiles.py              # three shaped example students
python3 -m pytest tests/test_scoring.py
```

## The flow

Six sections, then the report. On a wide screen the form sits between two
gutters that do real work: a **journey map** on the right that fills in as you
answer — your role, the areas you choose, the jobs under them, and a pip per
skill that colours in as you rate it, using the same level rule as the report's
skills map so the two read as one object — and a **companion** on the left that
drifts toward your cursor and reacts to what you do. Below 1240px the companion
goes; below 1000px the map becomes a summary strip above the form that expands
on tap. The form column itself never moves width, so nothing shifts under
someone mid-answer.

```
1  About you           name, email, phone, city
2  Your links          LinkedIn, GitHub, portfolio, resume
3  Education           college, degree, year, scores, languages, certs
4  What you've done    tool stack, experience, projects, leadership
5  What you want       role → business services → value constructs
6  Rate yourself       the skills behind your picks, then adaptive rounds
   ── REPORT ──
   Availability & location, fit & motivation (optional, on the report page)
```

Links, education and evidence of work are collected **before** the skills
section, so the profile feels like a profile rather than a quiz. Only
availability, location and fit are left for the report page — those are matching
data rather than things a student enjoys filling in, and they don't affect the
score.

The draft saves to `localStorage` after every change.

## How the algorithm decides

In plain language, in the order it happens.

**1. Your ratings become scores.** 1 → 0, 3 → 50, 5 → 100.

**2. We adjust for how you rate, not just what you rate.** Each rating is read
against the rest of your answers. Mark almost everything top and a top mark
counts for a little less; be hard on yourself throughout and your high marks
count for a little more. A flat sheet of 5s lands at 85, not 100 — because it
tells us nothing about which of your skills is stronger.

**3. Each piece of work gets a score.** 60% from the technical skills it needs,
40% from the human ones. Technical weighs more because it's the harder thing for
a company to coach through quickly.

**4. A real gap drags the score down instead of averaging away.** If one skill
the work depends on is far weaker than the rest, the score is pulled toward that
weak point. You can't ship an API you can't build, however well you document it.
An even profile barely moves; a genuine hole bites.

**5. We keep track of how sure we are.** Confidence comes from how much of an
area you rated, whether you used the whole scale or clicked the same number down
the page, and — once you add your experience — whether your projects back up what
you claimed. Comparisons between areas run on the *cautious* end of the range, so
rating yourself confidently can't by itself earn a recommendation.

**6. We estimate carefully about what we never asked.** Skills overlap between
areas, so answers about one tell us something about another. Everything inferred
that way is labelled *estimated* wherever it appears and carries far less
confidence than a real answer.

**7. We only ask extra questions while they still matter.** After the skills
behind your choices, each further round is chosen from your answers so far,
aimed at the areas that could still overtake your pick, and stops as soon as one
has clearly won. Usually 1–3 short rounds of four.

**8. Then we draw your skills map** — every skill behind the work you chose,
each marked twice: where you are, and where "ready" sits. The distance between
the two is the picture. Marks are coloured by level, never by whether that
particular job happens to need them raised, so a skill at 1 of 5 never looks
healthy just because something else is the bigger blocker.

**9. And we place each area on a grid** of what you want against what you're
ready for: *Sweet spot*, *Stretch*, *Hidden strength*, *Park it*.

**10. And we measure the distance, not just the score.** For anything not yet
ready we work out exactly what closes the gap — "two skills, three points" — and
recommend the reachable ones first rather than whatever scored highest.

### What it will and won't claim

- **Missing is never weak.** An area rated on fewer than half its skills is left
  unscored, not scored zero.
- **A redirect takes real evidence.** We only suggest a different area when it
  beats your own picks by 8 points *on cautious scores*. Below that it's noise in
  a self-rating, and the report says so instead of inventing advice.
- **Low everywhere isn't a wrong choice.** If nothing scores higher for you
  either, the verdict is "early days", not "you picked wrong".
- **We can't detect lying.** Straight 5s still outscore honest 3s and 4s. What
  the confidence maths does is shrink that advantage and say plainly why the
  ranking is soft — not overturn it.
- **Only technical skills get the evidence check.** There is no honest way to
  look for proof of "problem solving" in a list of repo links.

### Numbers you can tune

All in `scoring.py`, at the top:

| Constant | Default | What it does |
|---|---|---|
| `TECHNICAL_WEIGHT` / `TRANSFERABLE_WEIGHT` | .60 / .40 | the split within a value construct |
| `BOTTLENECK_PULL` | 0.35 | how hard the weakest must-have drags the score |
| `MIN_COVERAGE` | 0.5 | how much must be rated before we'll score an area |
| `CALIBRATION_WEIGHT` | 0.30 | how much comes from your own range vs face value |
| `UNCERTAINTY_SPAN` | 20 | points given up by a completely unconfident score |
| `REDIRECT_MARGIN` | 8 | margin before we suggest a different area |
| `READY_THRESHOLD` | 60 | the line between stretch and ready |
| `BATCH_SIZE` / `MAX_EXTRA_ROUNDS` | 4 / 3 | length of the adaptive rounds |

## Admin panel

`http://localhost:5000/admin` — four CRUD tables over everything students choose
from, plus a read-only view of who has completed the form.

Each tab opens with what you're looking at and a few counts, then a toolbar that
keeps searching, filtering and creating visually separate.

| Tab | What each row shows |
|---|---|
| **Roles** | tagline, business services, value constructs, students |
| **Business Services** | its role, value constructs, students |
| **Value Constructs** | its business service, technical/transferable counts, students |
| **Skills** | type, which value constructs use it, students who rated it |
| **Students** | completed profiles, fit, verdict, opening the candidate view |

The relationships read straight off the row rather than being hidden in a tree.
Clicking a parent cell jumps to that parent's table filtered to it, so the four
tables navigate as one thing. Each table has a search box; value constructs
filter by business service and skills by type.

Opening a student shows their profile **exactly as a company sees it**
(`/students/<id>` on the admin app) — locked to the company view with no way to
switch to the personal one. An admin reviewing candidates should see what a
recruiter sees, not the coaching written for the student.

Clicking any row opens a **drawer** with the full editor. For a value construct
that means both skill pickers, each showing how many other value constructs use
a skill, with inline creation. Changes save as you type. A value construct with
no technical skills says **none** rather than `0`, because it can't be scored
properly in that state.

Edits are **live immediately** — the panel writes `data/taxonomy.json` and forces
a reload, so the next student to load the form sees them. "Preview as a student"
opens the real form. Any row deep-links: `/admin#vc/vc-design-rest-apis`.

Two rules it enforces:

- **IDs never change.** They're generated from the name once. Renaming changes a
  label, because stored profiles reference the ID.
- **Deleting something students were scored on archives it instead.** It leaves
  the student form, but old reports can still name it. Genuinely unused items
  delete outright. The dialog tells you which will happen before you commit.

Every write validates the whole taxonomy first and is refused if it wouldn't
load, then writes atomically with a timestamped copy into `data/backups/`.

Note the admin deliberately uses the model's own vocabulary — Roles, Business
Services, Value Constructs — while the student form translates them into plain
English. Two audiences, two vocabularies.

> **Access:** the admin routes only answer requests from the machine running the
> server, and refuse anything arriving through a proxy. That is the whole of the
> protection — enough for local work and **not enough to deploy**. Real
> authentication belongs in `admin.py::_local_only`, which exists so there is one
> obvious place to put it.

## Changing the content

Nothing about roles or questions is in the code.

- `data/taxonomy.json` — roles, business services, value constructs, the skill
  registry, industries, causes, tool stack. Validated on load: a typo'd skill id
  fails loudly at startup rather than silently producing a wrong score.
- `data/profile_schema.json` — every field, with each phase marked
  `stage: "core"` (before the report) or `stage: "followup"` (offered after it).
  Moving a phase between the two is a data change, not a code change.

Ships with **Backend Development** only — five business services, twenty-five
value constructs, eighty-five distinct skills. The engine is role-agnostic and
starts recommending across roles as soon as the admin portal adds more.

Skill ids are shared across value constructs deliberately. `problem-solving`
appears in four, `systems-thinking` in three, `sql` and `redis` in two each. That
overlap is what lets one answer carry evidence into an area the student never
picked.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/taxonomy` | role tree, industries, causes, tool stack |
| `GET /api/profile-schema` | field definitions, with core/followup stages |
| `POST /api/skill-set` | the skills behind the chosen work |
| `POST /api/skill-set/next` | the next adaptive round, or `done` |
| `POST /api/profile` | core submission → `{profile_id, report}`, persisted |
| `PATCH /api/profile/<id>/details` | the follow-up section; recomputes the report |
| `GET /api/profile/<id>` | stored profile and report — **the hook for the company dashboard** |
| `GET /api/profiles` | thin listing, seed of the company-side view |
| `GET /api/health` | which build is answering: pid, start time, source fingerprint |

Adaptive questioning is stateless: the client sends everything rated so far and
gets back the next batch, so a refresh mid-round costs nothing. Everything the
client validates, the server validates again from the same schema.

## Report

`/report/<id>` has two views off one report object.

**Your view** is written to be understood on first read. It opens with one plain
sentence answering "am I good at what I want?", then at most three numbered
things to do, then every area of the role scored out of 100 with a plain label
(*Well ahead · Ready to start · Almost · Not yet*) and a tick marking where ready
starts. Internal vocabulary appears only as small print after the plain word —
"Jobs you said you want to own (value constructs)" — so a student meets the
model's language without being blocked by it.

Everything technical sits behind a **Show me the numbers** disclosure, closed by
default: the full verdict reasoning, the interest × ability grid, per-area
confidence, technical vs people skills, strengths and gaps, and a plain-English
account of how the score was worked out. Nothing is hidden from a student who
wants it; it just stops being the first thing they hit. The disclosure opens
automatically when printing.

The headline and the three actions are generated in `scoring.py`
(`plain_summary`, `next_steps`) rather than in the browser, so they are unit
tested and reusable by the company dashboard or an email.

**Company view** (`?view=company`) is denser: availability and terms, where the
student sits on the grid, strongest value constructs with confidence, area fit,
exactly what the candidate was told, skills claimed at 4–5 with nothing in their
history to back them, and how to read the numbers given their answering pattern.
It says plainly when a student has done the skills assessment but not the
availability section, because that is the difference between a matchable profile
and an unmatchable one. Both views print cleanly.

## Design

Bright, warm and orange, in `static/css/styles.css` only — everything is driven
by custom properties in `:root`, mirrored in a `prefers-color-scheme: dark`
block. Two fonts from Google Fonts: **Inter** for text, **Plus Jakarta Sans**
for headings and numbers (`--font-display`).

The four score bands deliberately do **not** derive from the brand orange —
brightening the accent made "Ready to start" collide with it, so the ramp runs
its own hues (green / blue / amber / red). Colour is never the only signal:
every band also carries a word and a number. Every text/background pair clears
WCAG AA in both themes, and the stylesheet honours `prefers-reduced-motion`.

The background on every page is **colour bends**: flowing bands of the brand
palette rendered on the GPU by `static/js/bends.js`. It's raw WebGL — one
fragment shader with two domain warps — rather than a framework, because the
site has no build step and the effect is a single shader. It's built to be cheap
on the mid-range phones students actually use: half-resolution buffer, capped at
30fps, stopped entirely when the tab is hidden, a single static frame under
`prefers-reduced-motion`, and if WebGL is unavailable it simply never appears and
the stylesheet's own background shows instead. Its colours come from
`--bend-1…4` and `--bend-strength`, so it follows the theme without knowing any
brand colours itself.

While the report is being worked out the wizard shows a **reasoning trace**
(`static/js/thoughtline.js`): a breathing glyph, a live clock, and the ten steps
`scoring.build_report` genuinely performs, which then fold into "Your profile is
ready". The trace is held open for about ten seconds — `HOLD_MS` in that file —
which paces the animation, not the request; the scoring itself finishes in well
under a second. That's why the settled line doesn't claim a thinking time: the
wait is real, the computation behind it isn't ten seconds long.

Motion elsewhere is deliberate rather than decorative: steps slide, cards and
rows enter in sequence, chips pop when chosen, and on the report the score bars
fill and the numbers count up — a number that lands on 39 reads differently from
one that was simply printed there. All of it respects `prefers-reduced-motion`.

The companion (`static/js/buddy.js`) listens for `caarya:mood` events on the
document and never reads wizard state or the DOM around it. Deleting the file
leaves the form working exactly as it did — which is checked, not assumed. It is
decoration: absent where there is no cursor, still under `prefers-reduced-motion`.

`design-prompt.md` holds the brief this was built from.

## Files

```
app.py               the public student app
admin_app.py         the admin app — separate program, separate port
scoring.py           the fit algorithm (pure, no Flask import)
taxonomy_loader.py   loads/validates the taxonomy, skill similarity index
validators.py        server-side validation, stage aware
db.py                SQLite schema and queries
data/                taxonomy.json, profile_schema.json
static/              wizard and report (vanilla HTML/CSS/JS, no build step)
  js/journey.js      the map that builds as you answer
  js/buddy.js        the companion — decoration, safe to delete
tests/               46 scoring tests
seed_profiles.py     three shaped students through the real API
```

## Notes for the next build

- `caarya.db` is created on first run. `profiles.report_json` holds the computed
  report whole, so the company dashboard never re-runs the algorithm.
- `profiles` keeps role, fit, verdict, hours, work mode and start date as real
  columns — the filters a company dashboard will want first.
- `scoring.py` imports nothing from Flask, so the matching engine can import it
  directly.
- **No documents are stored.** There is no upload endpoint and nothing is
  written to disk beyond the taxonomy and the database — a portfolio is a set of
  links, not files.
- `CAARYA_RELOAD=0` stops the data files being re-read on every request;
  `CAARYA_PORT` moves the server off 5000.
- `init_db()` migrates a database created by an earlier build rather than leaving
  it missing columns — `CREATE TABLE IF NOT EXISTS` does nothing to a table that
  already exists, which otherwise shows up as a 500 on the next read.
- Unhandled errors come back as JSON with the exception in `details`, and the
  full traceback is printed to the terminal running `app.py`.
