# tests/

Four layers, fastest first. None of them touches the network except through the local dev server.

| Layer | Command | What it covers |
|---|---|---|
| Python unit | `python3 -m unittest discover -s tests -p 'test_*.py'` | the build scripts' arithmetic (`test_safety.py`, `test_climate.py`) |
| JS unit | `node --test tests/*.test.js` (or `make test-js`) | the pure modules: `climate_core.js`, `testprop.js`, `route_core.js` |
| Both | `make test` | the two above |
| UI smoke | `make smoke` | every route × 3 viewports in a real browser: zero JS errors, DOM landmarks, screenshots |
| UI acceptance | `make ac` | one test per acceptance criterion (AC) of `docs/v3/UI_SPEC_v3.md` |

The two UI layers need a built `dist/` and a server on port 8080:

```bash
python3 scripts/build_dashboard.py
make serve &            # python3 -m http.server 8080 -d dist
make smoke && make ac
```

They also need Playwright, which lives in `.venv-ui/` (created once by `./overnight.sh preflight`;
see `docs/v3/ENG_BRIEF_v3.md` §6). `make smoke` and `make ac` pick it up automatically —
override with `make smoke UIPY=python3 UIURL=http://localhost:9000/`.

`./overnight.sh gate <PHASE>` runs build + both unit layers + smoke + acceptance + the size
budgets in one go, and is the only gate that counts.

## tests/ui_smoke.py — routes × viewports

Visits every route at 1440×900, 1366×768 and 390×844. A route fails on any `pageerror` or
`console.error` (tile and font requests are whitelisted), on a missing or empty DOM landmark, or
on a false expression over the app's own globals (`state=`). Screenshots and `report.json` go to
`--out/<phase>/`.

Adding a route: append one dict to `ROUTES` with `hash`, `land` (CSS selectors; a trailing `!`
means "and not empty"), optionally `wait`, `settle` and `state`.

**Keep the old v2.6 hashes in `ROUTES`.** `#table/kommune`, `#pipeline`, `#market`, `#sources`,
`#analysis?a=…`, `#compare?a=…` are the redirect test: links shared from v2.6 must keep landing on
the right view for as long as the dashboard exists.

`OVERFLOW_FATAL` is `False` until P8: horizontal overflow at 390 px is a known v2.6 defect on every
route, so it is reported as a note instead of failing the run. P8 rebuilds the responsive shell and
flips the flag.

CLI: `--url --out --phase --only --viewports --headed --allow-errors --no-network --full-page`.

## tests/ui_ac.py — one function per acceptance criterion

Each AC of the UI spec becomes one registered function:

```python
@ac("AC-M9", phase="P1", viewport="1440x900")
def ac_m9(page, base):
    """Zooming never changes the selection."""
    goto(page, "map/101?ind=growth", settle=1500)
    ...                 # raise AssertionError to fail
```

`--phase-upto P3` runs every AC registered for P1…P3, so each phase's gate re-runs all earlier
phases' criteria. A phase adds a test for every MUST AC it delivers and never deletes or weakens an
earlier one — if an owner amendment voids an AC, say so in `docs/v3/PROGRESS.md` and remove it there.

The page boots once per viewport (the same way `ui_smoke.py` does), external hosts are blocked
unless `--network` is passed, and `ERRORS` holds the live `pageerror` / `console.error` list so an
AC can assert on it. `report.json` and a screenshot per AC go to `--out`.

CLI: `--url --phase-upto --only --viewports --out --headed --network`.
