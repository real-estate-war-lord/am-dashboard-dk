# v3.0 — build progress

One section per phase, appended at the end of the phase. Read it before starting yours: it says what
already exists, what was decided along the way (details in `DECISIONS.md`) and what is still open.

---

## P1 — Foundation: map lifecycle, test harness, route aliases (dormant), design tokens

Commit: `v3.0 P1: map lifecycle, ui_smoke/ui_ac harness, dormant route aliases, design tokens`
Gate: green — build, 61 node tests, 42 python tests, 84/84 route×viewport smoke checks with **0 JS
errors**, 3/3 acceptance criteria, budgets (app.js 361 KB / 450 KB, style.css 115 KB / 140 KB).

### What was built

**1. Map lifecycle (ENG_BRIEF §2.4 — all four root causes fixed).** `src/app.js`:
- `LF_MAPS` names the four map keys (`map`, `amap`, `anmap`, `pmap`) and the layer groups that live on
  each. `dropMap(key)` does `map.off(); map.stop(); map.remove()`, nulls the key, its groups and (for
  the macro map) its draw caches. `dropMaps()` runs at the **top of `render()`**, before `#body` is
  replaced — so no map ever outlives its container. Every `xInit` calls `dropMap` instead of its own
  ad-hoc `LF.x.remove()`.
- `mapPanes(map)` creates `srvpane`/`pubpane`/`climpane` **per map** plus four canvas renderers, stored
  on `map._am`; `amOf(map)` is the accessor. `pubMarkers`, `pubClusterMarkers`, `lfServicesLayers`,
  `lfClimateLayers`, `lfMicroLayers` and the analysis micro layer now read the renderer of the map they
  are drawing on. The app-wide `LF.canvas / srvCanvas / pubCanvas / climCanvas / anCanvas` are **gone** —
  this was root cause 1 (`appendChild`), and 2 (`intersects`, `lat`) with it.
- `L.Map.prototype` guards for `_onZoomTransitionEnd`, `_move` and `_getMapPanePos` (the Canvas guard
  pattern, one level up) — root cause 3 (`_leaflet_pos`).
- `mapInit(fn)` debounces every init through one `LF.initTimer`; each init starts with
  `if (S.view !== "<its view>") return;`.
- `window.__maps` = the live Leaflet instances, kept in sync by `syncMaps()` on every create and drop.
  This is the spec's §10 test hook and the ACs use it.

**Result:** the `analysis` route, which threw 2–3 JS errors and left `#anlegend` empty at every viewport
in v2.6, is now clean — public-building markers draw, the indicator legend fills, and `fitBounds` on the
outer ring runs (it used to be unreachable because `anMapOverlays()` threw before it).

**2. Test property mini map** — `dragging: true`, the reader's centre and zoom kept across re-renders
(`LF.anCenter` / `LF.anZoom`, set on `moveend`), and a `⌖` re-centre control (`anRecentreControl()`,
`data-testid=minimap-recentre`). Full screen is P6's.

**3. Harness in the repo.**
- `docs/v3/ui_smoke_v3.py` → `tests/ui_smoke.py` (git mv, CLI unchanged). New: `OVERFLOW_FATAL = False`
  (phone overflow reported as a note, not a failure, until P8); landmark waits use Playwright
  `state="attached"` (Leaflet panes have no size — the default `visible` wait timed out for 15 s on the
  `analysis` route at every viewport, 45 s per run for nothing); the `map`, `area_kommune` and
  `analysis` routes assert `window.__maps.length === 1` and the analysis map asserts `dragging.enabled()`.
- `tests/ui_ac.py` — the acceptance runner. `@ac("AC-XX", phase="P1", viewport="1440x900")` registers a
  `(page, base_url) -> None` function; `--phase-upto P<n>` runs every AC of every phase up to and
  including `<n>`; one page per viewport, external hosts blocked, `report.json` + a screenshot per AC.
  `ERRORS` is the live pageerror/console.error list an AC can assert on.
- `make smoke` / `make ac` (both expect a server on :8080; `UIPY` picks up `.venv-ui` automatically),
  documented in `tests/README.md`.

**4. `src/route_core.js`** (IIFE → `window.ROUTE_CORE`, wired into `src/index.html` and
`scripts/build_dashboard.py` as `{{ROUTE_JS}}` + `check_js`). Pure, 29 node tests in
`tests/route.test.js`. API: `splitHash`, `buildHash`, `parseLatLon`, `propParse`/`propSerialise`
(list-capable), `climateFlag`, `toV3` (old → canonical v3, **idempotent**), `toInternal` (either
spelling → `{view, parts, query}` using the unchanged v2.6 `S.view` ids).
Table: `table/<lvl>`→`data/areas/<lvl>` · `pipeline`→`data/projects` · `market`→`data/national` ·
`market?src=1` and `sources`→`data/sources` · `analysis?a=&la=`→`property?p=lat,lon:label` ·
`compare?a=<type>:<code>`→`area/<type>/<code>` (→`map` if unparsable) · `map…&climate=1`→ the same map
with `ind=surge_dw_pct` unless the link already names a climate indicator.

**5. Design tokens** — spec §2.1–2.3 in a third `:root` block at the end of `src/style.css`: the
projection/climate/inherited colours, focus ring, `--nodata`, `--cap-ind`… the `--s1…--s6` spacing
scale with card/gutter/control sizes, and the type scale. **No view is restyled.**

### ACs delivered
- **AC-MM3** (MUST) — `#map → #area/kommune/101 → #analysis → #map` produces zero `pageerror`, both
  walked slowly and switched every 50 ms three times over; exactly one live map afterwards.
- **AC-M9** (MUST) — on `#map/101`, `setZoom(12)` then `setZoom(9)` leaves the hash path, `MK.muni`,
  `MK.cphView` and `LF.level` unchanged.
- **AC-P1MM** (P1-local) — on `#analysis?a=55.6545,12.539` the mini map is draggable, a 120 px drag
  moves its centre, `⌖` re-centres on the pin, and the pin + its three rings are on the map.

### Deviations
- The phase file says the alias table covers `analysis → property`; the **new spellings are not emitted**
  (`const ROUTE_V3 = false` in app.js). `hashFor()` ends in `routeOut(...)` and `parseHash()` starts with
  the rewrite, both behind that one flag — P2 flips it and both directions come on together.
- AC-MM3 walks to `#analysis`, not `#properties`: the Test property route is P6's rename. The AC keeps
  its spec id because it is the same navigation and the same invariant.
- The phase file's `dropMap` list of "renderers" became `map._am`, which `map.remove()` disposes of with
  the map — nothing left in `LF` to null.

### Known issues / open items
- Horizontal overflow at 390 px on all 28 routes (v2.6 defect). Reported as a smoke note;
  **P8 must set `OVERFLOW_FATAL = True` in `tests/ui_smoke.py`** when the responsive shell lands.
- `tests/test_safety.py` needs Python ≥ 3.12 to import (`build_makro.py:851`); the gate treats the
  python unit tests as informational. Unchanged by this phase.
- `make build` still fails on Python < 3.12 — use `python3 scripts/build_dashboard.py`.

### What the next phase must know
- **`render()` now drops every live map first.** Anything that re-renders while a map is on screen
  rebuilds that map. If a view needs to update *without* losing its map (P4's "no full page rebuild on
  the area page", AC-P4), update in place — do not call `render()`/`renderKeep()`.
- **Never create a map outside an `xInit`, and always through `mapInit(fn)`**: register it in `LF_MAPS`
  (key + its layer groups), call `dropMap(key)` first, `LF.<key> = map; syncMaps();` after, and start
  the init with the `S.view` guard. A map that is not in `LF_MAPS` is a map `render()` cannot drop.
- **Never share a renderer or a pane between maps.** `amOf(map).{base,srv,pub,clim}` — the map you are
  drawing on, every time.
- `window.__maps` is the contract for every map-related AC from here on (MM1, MM2, M9, TP2).
- **P2** flips `ROUTE_V3` to `true` in `src/app.js` and adds the new hashes to `tests/ui_smoke.py`
  ROUTES **next to** the old ones — the old ones stay for ever, they are the redirect test.
- **P6** should build the Test property page on `route_core.propParse/propSerialise` rather than a
  second codec, and can use `toInternal()` to get `{a, la}` out of `p=`.
- Every phase: add one `@ac(...)` per MUST AC it delivers to `tests/ui_ac.py`, and never weaken an
  earlier phase's.

---

## P2 — Navigation, the Data section, Compare deleted, the redirects live

Commit: `v3.0 P2: nav + Data section, v3 hashes live, Compare deleted, breadcrumbs`
Gate: green — build, 63 node tests, 42 python tests, 117/117 route×viewport smoke checks with **0 JS
errors**, 11/11 acceptance criteria (3 from P1 + 8 from P2), budgets (app.js 353 KB / 450 KB,
style.css 115 KB / 140 KB).

### What was built

**1. Four destinations.** `VIEWS` / `NAV_GROUPS` are now `Market intelligence: Map · Data · Charts`
and `Analysis: Test property`. Market, Pipeline and Compare are gone as nav items. Every nav button
carries `data-testid=nav-item`, the `<aside>` carries `data-testid=sidebar`, and the footer export
button `data-testid=export-btn` (P7 turns it into the menu). The sidebar's `on` mapping folds
`table`/`pipeline`/`market`/`project` onto **Data** and the sheets onto **Map**.

**2. The Data section** — `#data/areas/<level>` · `#data/projects` · `#data/national` ·
`#data/sources`, `#data` → `#data/areas/kommune`. One tab bar (`dataTabs()`,
`data-testid=data-tabs`, four `data-testid=data-tab` buttons) rendered at the top of `vTable`,
`vPipeline` and `vMarket`. **The internal view ids are unchanged** (`table`, `pipeline`, `market` +
`MKT.src`) — only the hash spelling, the labels and the breadcrumb moved.
- **Areas** = the old Table, behaviour untouched; the table gained `data-testid=areas-table`.
- **Projects** = the old Pipeline with its `ptype`/`pstatus` filters and CSV button
  (`data-testid=projects-table`); the toolbar keeps the `n of N projects` count and the caption
  names the publishers (Fingerplan, Anlægsstatus, the agencies' decision documents).
- **National series** = the old Market rebuilt as a table (`data-testid=national-table`):
  `Series · Latest · Period (+ month/quarter/year tag) · y/y · Source · Last 5 years` sparkline.
  The four big `lineChart()` charts and `lineChart()` itself are **deleted**; the four headline
  tiles stay as a compact row (`.hero.hero-nat`, no sparkline inside the tile).
- **Sources** = the old accordion as a sortable table (`data-testid=sources-table`):
  `Source · Publisher · Tables · As of · Fetched · Licence · Used for · ↗`. Publisher is read off
  the catalogue key (`dst/` → Danmarks Statistik …), "Used for" joins indicators through their
  `tables` list with a named fallback for the register/curated sources, and an empty **Fetched**
  falls back to the build date with a `build` tag (AC-D4).

**3. The v3 hashes are live.** `ROUTE_V3` is deleted; `hashFor()` always ends in `RC.toV3()` and
`parseHash()` always starts from `RC.toInternal()`. `parseHash()` then ends with a canonical
`replaceState` of `hashFor()`, so the address bar always shows what the app would serialise — an old
link redirects exactly once and every route round-trips (AC-U1). `climate=1` is deliberately left
alone (`keepClimateFlag`) until the Climate phase.
Redirects verified in the suite: `#table/<lvl>` → `#data/areas/<lvl>`, `#pipeline[?filters]` →
`#data/projects`, `#market` → `#data/national`, `#market?src=1` and `#sources` → `#data/sources`,
`#analysis?a=&la=` → `#property?p=lat,lon:label`, `#compare?a=&b=` → the **a** side's area page.

**4. Compare is deleted** (amendment A1): `vCompare`, `cmpRow`, `cmpZoneRow`, `cmpInZone`,
`cmpSection`, `cmpPick`, `cmpBetter`, `cmpValCell`, `cmpSrcCode`, `cmpResolve`, `cmpIdFromOpt`,
`CMP`, `CMP_CLIM_KEYS`, the `cmpa`/`cmpb` change handlers, the `VIEWS`/`RENDER`/`crumbs` entries,
the `hashFor`/`parseHash` branches and the `.cmp*` CSS. No route shows the word (AC-TP6).

**5. Test property route** `#property?p=lat,lon[:label]` (A3). `analysisLink()` now builds it
through `RC.propSerialise` (`propLink()`), so the popup "Analyse ›" button, the nav item and the
pin-drop all emit the new hash; `#analysis?a=…&la=…` redirects to it. The view is still the existing
`analysis` sheet — §5.5′ is P6's rebuild.

**6. Breadcrumbs** for every view. Data → `Denmark › Data › <tab>`; project sheet →
`Denmark › Data › Projects › <name>`; **public-building sheet → `Denmark › København › <building>`**
(AC-SH3 — v2.6 showed "Macro map"); public list and school list gained the municipality; the test
property no longer pushes a "Map" crumb.

**7. Tests.** `tests/ui_smoke.py` ROUTES: eight new `#data/*` + two `#property` routes, a
`compare_redirect` route replacing `compare`, and a new `redirect=` field checked by
`hash_mismatch()` (same path, and every query key the expectation names) — the old hashes all carry
one now, so they are literally the redirect test. `tests/ui_ac.py` gained AC-D1, AC-D2, AC-D3,
AC-D4, AC-SH3, AC-TP1, AC-TP6, AC-U1. `tests/route.test.js` gained the `data` alias and
`keepClimateFlag` cases (31 route tests, 63 node tests in all).

### ACs delivered
AC-D1, AC-D2 (read as the four amended items), AC-D3, AC-D4, AC-SH3, AC-TP1, AC-TP6, AC-U1 — all
MUST, all registered in `tests/ui_ac.py` under `phase="P2"`.

### Deviations
- **AC-D2 is asserted with four nav items**, not the spec's five: owner amendment A1 removes
  Compare, and Market/Pipeline were already folded into Data by §1 of the spec.
- The **`keepClimateFlag` option** is new in `route_core.js` and not in any phase file. Flipping the
  route flag would otherwise have activated P1's `climate=1` → `ind=surge_dw_pct` rewrite, which
  deletes the working Climate-risk overlay button two phases early (the smoke `map_climate` route
  asserts `MK.clim`). The Climate phase deletes the option, its app.js call sites and its node test
  in the same commit that removes `MK.clim`.
- **Internal view ids kept** (`table`, `pipeline`, `market`) as the phase file allows; there is no
  `S.view === "data"`. Anything testing for one should test `isData()`.
- The National series `↗ Chart` per row is SHOULD in the spec and is **not** built — the table is
  the MUST. Charts does not yet take a national series as an entity (that is the Charts phase).

### Known issues / open items
- `scripts/ui_check.py` (the older headless-Chrome check) still drives `#compare` and asserts its
  climate rows. It is outside this run's allowed files and is **not** part of `./overnight.sh gate`;
  `make ui-check` will fail its compare group until someone removes that block.
- Horizontal overflow at 390 px is still a note on every route (v2.6 defect); **P8 flips
  `OVERFLOW_FATAL = True`**. The Data tab bar is already `overflow-x:auto` below 600 px.
- The Data tabs do not yet carry the view's query state in their `data-go` (they emit a bare path),
  so switching tabs keeps the indicator only because `parseHash()` leaves `MK.ind` alone when the
  hash names none. If a later phase makes the tabs stateful, give them `withQ()`.
- `exportCsv` / `exportAll` are untouched — the Export phase owns the schema and the menu.

### What the next phase must know
- **`hashFor()` is the single serialiser and it is now enforced**: `parseHash()` rewrites the address
  bar to `hashFor()` on every parse. A new URL key must be written by `hashFor()` *and* read by
  `parseHash()`, or it will be silently dropped from the bar one frame after it is set.
- **Add a hash spelling in `src/route_core.js`, not in app.js.** `toV3()` (old → canonical, must stay
  idempotent — there is a test for it) and `toInternal()` (either spelling → the v2.6 view id).
- **Never remove an old hash from `tests/ui_smoke.py` ROUTES.** Give a new route a `redirect=` when
  it must land somewhere else; `hash_mismatch()` checks the path plus the query keys you name.
- The Data section is three views behind one tab bar: a change to the Areas tab is a change to
  `vTable`, to Projects `vPipeline`, to National series / Sources `vMarket` / `vSources`.
- `dataTabs()`, `dataTabHash()`, `dataTab()` and `isData()` are the helpers to reuse; `DATA_TABS`
  is the one list of tab ids and labels.
- The Export phase: the footer button is `[data-testid=export-btn]` in `src/index.html` and still
  calls `exportAll()`; the spec wants the same menu in the Data page header.

---

## P3 — The shared IndicatorPicker, the chips row and the PeriodControl

Commit: `v3.0 P3: shared IndicatorPicker, PeriodControl and chips on Map, Data › Areas and Charts`
Gate: green — build, 83 node tests (63 + 20 new picker tests), 42 python tests, 123/123
route×viewport smoke checks with **0 JS errors**, 20/20 acceptance criteria (3 from P1 + 8 from P2 +
9 from P3), budgets (app.js 372 KB / 450 KB, style.css 121 KB / 140 KB).

### What was built

**1. `src/picker_core.js`** (IIFE → `window.PICKER_CORE`, wired into `src/index.html` and
`scripts/build_dashboard.py` as `{{PICKER_JS}}` + `check_js`, 20 node tests in
`tests/picker.test.js`). The parts of the picker that are a function of the registry alone:
`GROUP_ORDER` (**moved here** — app.js now reads `PC.GROUP_ORDER`), `GROUP_PILL`
(`Outlook → Projection`, `Climate → Horizon`), `grouped()`, `matches()`/`filter()` (label · short ·
group · unit, every word has to hit), `periodMode()` (`horizon | projection | year`), `PERIOD_KEY`
(`hz | "" | y`), `availTag()` and `step()` for ↑/↓.

**2. One IndicatorPicker** (`indPicker(target)`, `data-testid=ind-picker`). Button showing
`label · unit` plus a `municipality` tag when the figure is not native to the level on screen;
popover with a search box, the twelve groups as `[data-group]` headers with their pill, and one row
per indicator carrying label, unit, `↓ lower is better` and the availability tag (`muni` · `2016–` ·
`snapshot` · `horizons` · `2026→2040`). `role=listbox` + `aria-activedescendant`, `aria-expanded` on
the button, ↑/↓/Enter/Esc, Esc returns focus to the button. The popover ships with the view and is
hidden — opening it toggles a class, so nothing re-renders and the search box keeps focus.

**3. The chips row** (`indChips(target)`, `data-testid=ind-chips`): `QUICK_KEYS` ∩ the level's
indicator list, the active one filled (`.chip.on`). Rows and chips share `data-ind=<key>`; the old
`data-indq` / `#indsel` / `indQuick()` / `indSelect()` are deleted.

**4. One PeriodControl** (`periodControl(target)`, `data-testid=period`) with four renderings:
`period-year` (the year select, `#yearsel`), `period-hz` (the horizon segments — `hzPill()`, reused
so the climate sheet gets the same test id), `period-proj` (the static
`Projection 2026→2040 · DST 2026 · FRKM126` badge) and `period-asof` for a single-as-of snapshot.
`yearSelect()` is now an alias of it, so the area page and the sheets share the one implementation
until P5/P6 rebuild their toolbars. `hz=` leaves the URL when the indicator leaves the Climate
family; `y=` already did.

**5. Adopted on Map, Data › Areas and Charts.** The map toolbar's `indSelect() + yearSelect()` and
the `#mkquick` chips, the Areas tab's toolbar, and the Charts `<select id="chind">` all became the
shared pair. Charts writes to `CH.ind` through the same component (`data-target=chind`).

**6. Data › Areas**: every indicator column header carries `data-col=<key>`, the active one also
`.on` (green underline + tint), and the table is sorted by it — best first, the direction each
header declares in `data-best` (AC-D5).

**7. Charts: Climate is a horizon chart** (`chartSvgClim`, AC-C2). `chartMode()` returns `clim` for
any Climate indicator; the x axis is Today · 2070 · 2120 (`[data-hztick]`, with the Klimaatlas
period under each), one bar per area per horizon (`[data-series][data-hz]`), the publisher's own
low–high range as a whisker where there is one, and the municipalities' median as a dashed tick per
horizon. Nothing is drawn between the horizons. `Data CSV` gains an area × horizon file with the
range columns. To make this possible `climValue(o, k, hz)` and `climHzFor(k, hz)` now take an
explicit horizon (default `HZ.h`).

**8. Chart test ids**: every generator SVG is `data-testid=chart-svg`; line paths and bars carry
`data-series=<name>` + `data-series-kind=area|median|national` (AC-C1).

**9. The harness serves `dist/` itself when it has to.** Mid-run, port 8080 was taken over by a
sibling project on this machine (`Macro Dashboard · Sweden`), and because `overnight.sh gate` starts
a server only when nothing answers on :8080, every route turned into "missing landmark" and every
state expression into a ReferenceError — a catastrophic-looking failure with no cause in this repo.
`our_url()` in `tests/ui_smoke.py` (imported by `tests/ui_ac.py`) now reads the page title first and,
when it belongs to someone else, serves this repo's `dist/` on a free loopback port from inside the
test process. It prints one line when it does. `assert_this_app()` re-checks after boot.

### ACs delivered
AC-I1, AC-I2, AC-I3, AC-I4, AC-T1, AC-T2, AC-D5, AC-C1, AC-C2 — all MUST, all registered in
`tests/ui_ac.py` under `phase="P3"`. AC-I5 (the "From the municipality" group on a postal-code page)
is P5's, as the phase file says.

### Deviations
- **AC-I1 is asserted on `map`, `data/areas/kommune` and `charts`** — the routes that had adopted
  the picker when P3 landed. The area page and the test property keep their v2.6 selectors until
  P5/P6; `PICKER_ROUTES` at the top of the P3 block in `tests/ui_ac.py` is the list to extend.
- **AC-D5 sorts best first, not "descending regardless"** — the AC's own parenthetical contradicts
  itself and the table's caption has said "best first" since v2.6. See `DECISIONS.md`.
- **Charts gets no PeriodControl.** Its `from ▾ / to ▾` selects *are* its period control (spec §5.4
  lists them in the toolbar), and a Climate chart shows all three horizons rather than choosing one.
- The row availability tag has five shapes rather than the three named in §4.2, and all nine
  `QUICK_KEYS` chips are rendered rather than "the first 8" (§4.2's own diagram lists nine). Both in
  `DECISIONS.md`.
- **A data defect is surfaced, not fixed**: the surge keys' registry `desc` names the default
  horizon inside the sentence. `climDescNeutral()` drops that word in the horizon chart's subtitle
  only. Daytime data task.

### Known issues / open items
- The map toolbar still carries the v2.6 `Infra projects` / `Public buildings` / `Services` /
  `Climate risk` buttons and both search boxes — **P4** replaces them with `Layers ▾` and the
  unified search, and that is also what will bring the toolbar down to one row (AC-M1, AC-S3).
- `indExplain()` (the ⓘ strip under the toolbar) still renders its own label/unit/level tags, which
  now repeat what the picker button says. P4 owns the info strip (spec §5.1) and should fold them.
- Horizontal overflow at 390 px is still a note on every route (v2.6 defect); **P8 flips
  `OVERFLOW_FATAL = True`**.
- **Port 8080 is contested on this machine.** A sibling project (`Macro Dashboard · Sweden`) held it
  for most of this phase. The runners now serve `dist/` themselves when that happens, so the gate is
  unaffected, but anyone opening `http://localhost:8080/` for the morning review may be looking at
  the wrong dashboard — check the page title first.
- `mkRefreshTools()` rebuilds the toolbar's innerHTML on the zoom ladder, so a zoom closes an open
  popover. Harmless, but P4 should keep it in mind when it rebuilds `mkTools`.

### What the next phase must know
- **`indPicker(target)` / `indChips(target)` / `periodControl(target)` are the three calls.**
  `target` is `"ind"` (the global `MK.ind`) or `"chind"` (Charts). A view adopts the toolbar by
  calling all three — do not write a fourth selector. `pickCtx(target)` is where a new target's
  list, level and current key would go.
- **One picker per page.** `indPopEl()` takes the first `[data-testid=ind-picker]`, and AC-I1 asserts
  there is exactly one. A view that wants two indicators (P5's overlay, a future compare) needs the
  component to be scoped by id first.
- **`pickLevel()` decides which rows read `muni`.** P5's AC-I5 ("From the municipality" group with
  `.tag-muni` on `#area/postnr/2450`) is a grouping change on top of `pickInherits()`, which already
  returns the right answer for postnr and kvarter — the tag text is already `muni`.
- **`pickYears(key, level)` is memoised** in `PICK_YEARS`. It has to be: `yearsForPool()` over 63
  indicators × 606 postal codes is ~0.7 M reads, and the popover asks for all of them every render.
- **`hzParts()` in `hashFor()` is the one place `hz=` is written.** The Climate phase deletes the
  `MK.clim` term from it when the overlay goes.
- **`climValue(o, k, hz)` takes a horizon now.** Anything that wants a figure at a horizon other
  than the pill's (P5's three-bar `clim-bars`, P7's export) should pass it rather than move `HZ.h`.
- **`tests/ui_ac.py`'s `boot()` hops through Data before the map**, so an AC always starts on a
  freshly rendered page. Leave that in: without it an AC inherits the previous one's open popovers.
- `tests/ui_smoke.py` gained `map_proj` and `charts_clim`, and the `map`, `data_areas`, `charts` and
  `charts_dist` routes now land on the picker's test ids instead of `#indsel` / `#chind`.
- **If a gate ever fails on every route at once, read the first line of the smoke output.** It now
  says which dashboard the URL was serving. `our_url()` recovers by serving `dist/` itself, so a
  phase should never go red for someone else's server again.
