# Common rules for every v3.0 overnight phase (read before your phase file)

You are one of nine sequential, unattended Claude Code sessions building **Macro Dashboard v3.0** (the UI
overhaul) in this repo. Nobody is awake to answer questions: when something is ambiguous, choose the option
that best fits `docs/v3/UI_SPEC_v3.md`, write the decision down in `docs/v3/DECISIONS.md` (append, one line,
prefixed with your phase id) and carry on. Never stop to ask.

## Read first (in this order, don't read app.js end to end)
1. `docs/v3/UI_SPEC_v3.md` — **the OWNER AMENDMENTS at the top override everything else**, then the sections
   your phase names. It is the source of truth for layout, behaviour, test ids and acceptance criteria (AC).
2. `docs/v3/ENG_BRIEF_v3.md` §1 (architecture map with line numbers — they drift as phases land, re-grep),
   §2 (harness, root causes), and anything your phase file points to.
3. `docs/v3/PROGRESS.md` — what earlier phases did, deviations, and open items. Read it; append to it at the end.
4. Navigate app.js with `grep -n "^function \|^const [A-Z_]* = {" src/app.js` and targeted reads.

## Hard principles (never violate)
- Hard data only: official figures or plain arithmetic on them. No scores, weights, rankings-as-verdicts, models.
- Every figure traceable (source, table id, as-of, verify link). Projections never look like actuals.
- Zooming a map never changes the selection. Selection = explicit click / search / breadcrumb only.
- English UI. Shareable state in the URL; `hashFor()` is the only serialiser, `parseHash()` the only parser.
- Old links keep working (redirect table). Evolve the existing look (dark green sidebar, paper background,
  mono labels, green ramps) — don't replace it.

## Allowed / forbidden
- Allowed: `src/**`, `tests/**`, `docs/**`, `Makefile`, `README.md`, `CHANGELOG.md`, and
  `scripts/build_dashboard.py` only to wire in a new `src/*.js` file (placeholder + `check_js`).
- **Forbidden** (the wrapper hard-fails the phase if touched): `.github/`, `data/`, `config/`, `dist/public/`,
  any other `scripts/*` file. No data changes — data issues are surfaced in the UI with a caveat and logged in
  `docs/v3/DECISIONS.md`.
- **No network scripts**: never run `make fetch/validate/links/refresh/validate-forecast`, `scripts/fetch_*`,
  `pip install`, `npm install`, `playwright install`. Everything you need is installed.
- **Never push, never merge, never switch branch.** You are on branch `v3.0-ui`.
- New JS files: IIFE exposing one `window.X` (see `src/climate_core.js`); wire into `src/index.html` and
  `scripts/build_dashboard.py` in the same commit (one global scope — a colliding top-level const blanks the page).
- Budgets: `src/app.js` ≤ 450 KB, `src/style.css` ≤ 140 KB. Delete dead code you replace (don't leave both).

## Self-check (run it yourself before committing; the wrapper re-runs it and does not trust your word)
```bash
./overnight.sh gate <PHASE>     # build + node tests + python tests + smoke (3 viewports) + AC suite + budgets
```
It prints the log path. Iterate until green. Look at the screenshots it writes (`logs/<run>/shots/<PHASE>/`)
with your image-reading tool for the views you changed, at 1440×900, 1366×768 and 390×844 — fix anything that
looks broken, misaligned, clipped, overlapping or inconsistent with the spec, even if tests pass.

## Tests you own
- `tests/ui_smoke.py` (route × viewport smoke; fatal on pageerror/console.error, landmark checks). Keep the OLD
  hashes in its ROUTES — they are the redirect tests. Update landmarks for views you change.
- `tests/ui_ac.py` (acceptance suite: one function per AC id from the spec, registered with the phase that
  delivered it). **Add a test for every MUST AC your phase delivers.** Never delete or weaken an earlier
  phase's AC test unless the owner amendments void it (then say so in PROGRESS.md).
- Pure logic in new `src/*_core.js` files gets `node --test` tests in `tests/*.test.js`.

## Finish
1. `./overnight.sh gate <PHASE>` is green.
2. Append a section to `docs/v3/PROGRESS.md`: what you built, ACs delivered (ids), deviations and why,
   known issues, what the next phase must know.
3. Exactly one commit: `git add -A && git commit -m "v3.0 <PHASE>: <scope>"` with the trailer lines
   `Co-Authored-By: Claude <noreply@anthropic.com>`. Working tree clean afterwards.
4. If you cannot make the gate green after serious effort: write `docs/v3/phases/<PHASE>.FAILED.md` (what you
   tried, the failing output, your best guess at the fix) and stop. The wrapper saves it and rolls back.

## Tool permissions in this run (no bypass — anything else is denied automatically, don't retry it)
File tools: Read (also for screenshots/images), Edit, Write, Glob, Grep — inside the repo.
Shell: `git status|diff|log|show|add|commit|mv|rm|restore`, `git checkout -- <paths>`, `./overnight.sh gate <PHASE>`,
`python3 scripts/build_dashboard.py`, `.venv-ui/bin/python3 tests/ui_smoke.py …`, `.venv-ui/bin/python3 tests/ui_ac.py …`,
`node --test …`, `node --check …`, `ls`, `wc`, `grep`, `head`, `tail`, `mkdir`.
Not available: push/reset/branch/merge, network, package installs, arbitrary python/node one-liners. If you need a
quick experiment, write it as a test in `tests/` and run it through the commands above.
