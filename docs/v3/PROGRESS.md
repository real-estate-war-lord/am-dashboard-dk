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

---

## P4 — Map: Climate as an indicator family, Layers ▾, the unified search, the legend stack

Commit: `v3.0 P4: Climate as an indicator, Layers menu, unified search, one-row map toolbar`
Gate: green — build, 83 node tests, 42 python tests, 129/129 route×viewport smoke checks with **0 JS
errors**, 30/30 acceptance criteria (3 from P1 + 8 from P2 + 9 from P3 + 10 from P4), budgets
(app.js 387 KB / 450 KB, style.css 130 KB / 140 KB).

### What was built

**1. Climate is an indicator family, not an overlay** (spec §1 decision 3). `MK.clim`, the
`Climate risk` toolbar button, the `climate=1` key, the `clim=` filter and the floating filter card
are gone. `climOn()` is now `CLIM && S.view === "makro" && isClim(MK.ind) && MK.zones`: choosing any
Climate indicator draws the official risk areas plus the storm-surge extent for the active horizon
(zoom ≥ 10 for the zones) as a **context layer** under the fill, with its own keys-only legend card
(`data-testid=legend-zones`) and one `[data-layer=zones]` row in the Layers menu to hide it
(`zones=0`). A non-Climate indicator has neither. `#map?…&climate=1` redirects to
`ind=surge_dw_pct` through `route_core` (P2's `keepClimateFlag` option, its app.js call site and its
node test are deleted, as P2 said this phase would do). The Climate chip stays in the chips row.

**2. `Layers ▾`** (`layersMenu()`, `data-testid=layers-btn` / `layers-pop`, count badge
`Layers · n`). Feature layers = Infra projects · Public buildings · Services, each with the
category / kind filters that used to live inside its floating legend (`data-pubcat`, `data-pubkind`,
`data-srvcat`, `data-srvmode` and the `All` resets keep their handlers, they just moved). Context =
the Climate zones (only while a Climate indicator is) and the test-property radius (only while there
is a pin); `D.portfolio`'s "Own properties" toggle moved here too. `MAP_LAYERS` is the one list;
`mapLayerToggle()` the one handler. The menu survives a re-render (`UI.layOpen`) so two ticks need
one trip to the button, and closes on Esc, on an outside click and on any navigation.

**3. One URL key for the layers.** `lay=infra,public,services`, written by `hashFor()` and read by
`parseHash()`. The v2.6 flags are converted in `route_core.layerFlags()` (idempotent, 8 new node
tests) — so old links keep working and there is still one serialiser.

**4. The toolbar is one row** (`mkTools()` → `[data-row=1]` and `[data-row=2]`):
`[search][Layers ▾][Indicator ▾][Period]` plus the drilled-state segments, chips below, info strip
below that. Full screen moved to the top bar right (`pageActions()` in `renderTop()`,
`data-testid=map-full`). The paste box, the privacy paragraph, the two jump buttons and the four
overlay buttons all left. **Map top at 1366×768: 186 px** (was ~330), height 518 px.

**5. The unified search** (`data-testid=search`) is a real combobox, not a `<datalist>`: municipality
/ postal code / quarter by name or code **and** Google Maps links or `lat, lon` through the same
`parseLocation()` the test property uses. A location produces a `search-coord` row — "Open as test
property" → `#property?p=…`. "Jump to: Denmark · Copenhagen" sits at the top of the dropdown and only
moves the camera (the C / D shortcuts are unchanged). ↑ ↓ move, Enter takes the highlighted row or
the first one, Esc closes. The privacy sentence is the `?` tooltip on the box.

**6. The legend stack** (`#maplegs`, spec §4.5). All five legends are now one bottom-right stack:
indicator (`legend`), zones (`legend-zones`), infra / public / services (`legend-*`). They are
**keys only** — every filter moved to the Layers menu — and a legend container is rendered only for a
live layer. `lgFit()` keeps the stack inside the map, inside 60 % of its height and at most two
cards wide, folding the topmost feature legend to its title when it has to (AC-LG1).

**7. The drilled municipality card is collapsible** (spec §5.1), closed by default, state in
`localStorage.mstrip`. The identity line and the five headline figures stay in the summary.

**8. Outlook draws in purple** (`RAMP_GROUP` in `mkShade()`, AC-M4) — on the map, in Charts and on
the area page alike. Climate was already blue.

### ACs delivered
AC-L1, AC-L2, AC-L3, AC-LG1, AC-M1, AC-M2, AC-M3 (read `#properties` as `#property`, amendment A2),
AC-M4, AC-S3 — all MUST — plus the phase-local **AC-P4SR** (the jumps moved into the dropdown and
still only move the camera). All registered in `tests/ui_ac.py` under `phase="P4"`.

### Deviations
- **The Outlook ramp is two purples, not one** — every Outlook indicator is `scale: diverging`, so a
  single hue would throw the sign of the projection away. See `DECISIONS.md`.
- **`clim=` is deleted rather than kept**: the risk areas and the surge extent are one context layer
  with one switch now. An old link carrying `clim=areas` shows both parts instead of one.
- **AC-S3's drilled-state assertion is mine, not the spec's** (the AC only names `#map`). It asserts
  the drilled map starts ≤ 320 px down with ≥ 300 px on the first screen; it is 302 px.
- **AC-LG1 uses Aarhus, not Copenhagen** — see the limitation below.
- `pubLegendHtml`'s `only` links and the `data-pubonly` handler are gone: shift-click on a category
  in the Layers menu still isolates it, and "only" was a legend affordance.

### Known issues / open items
- **A Climate indicator does not survive drilling into Copenhagen in quarter mode.**
  `data/processed/cph.json` carries no Climate keys, so `curInds()` swaps the indicator (and with it
  the zones) on `#map/101`. v2.6 behaviour, surfaced not fixed — it needs quarter-level climate
  figures in the build. Daytime data task, logged in `DECISIONS.md`.
- Horizontal overflow at 390 px is still a note on every route (v2.6 defect); **P8 flips
  `OVERFLOW_FATAL = True`**. The new popovers are width-capped to the viewport and do not add to it.
- `mkRefreshTools()` still rebuilds the toolbar's innerHTML on the zoom ladder, so a zoom closes an
  open search dropdown (the Layers menu survives it — `UI.layOpen` is re-rendered open).
- The Layers menu's feature rows are switches, not links: there is no "open this layer's list" from
  the menu. The card segments (`data-publist`) are still the way into the public-building list.

### What the next phase must know
- **`climOn()` is the one test for "are the zones on screen"** and it is bound to the active
  indicator. Anything that wants to draw or count zones outside the macro map (the test property,
  the climate sheet) must not use it — they have their own state (`ANL.climate`, `CS.code`).
- **`lay=` on the map and `lay=` on the test property mean different things** (`infra,public,services`
  vs `infra,public,micro,climate`). `route_core.layerFlags()` only runs on the `map` head.
- **`layersMenu()` is where a new map layer goes**: one entry in `MAP_LAYERS` (label, `on()`,
  `avail()`, `sub()`, optional `filters()`), one branch in `mapLayerToggle()`, one legend container
  in `vMakro()` and one id in `LG_FOLD_ORDER`. Do not add a toolbar button.
- **The legend containers are conditional.** `setXLegend()` returns early when its box is not in the
  DOM, so a layer that draws without its container gets no legend — render the container in
  `vMakro()` in the same commit.
- **`areaSearch()` / `asrchRows()` is the one search.** A new kind of result (an address, a project)
  is a branch in `asrchRows()`, not a second box. `data-testid=search` is the input itself.
- P5 (area page) and P6 (test property) inherit `indPicker` + `periodControl` + `layersMenu` as the
  toolbar vocabulary; the area page has no feature layers, so it needs the picker and period only.
- **The top bar has an actions slot now** (`pageActions()` in `renderTop()`, `.hd-act`). P7's
  `Export ▾` on the Data header and P5's page-level buttons belong there rather than in a card head.

---

## P5 — The area page rebuilt around the study row

Commit: `v3.0 P5: area page rebuilt around the study row`
Gate: green — build, 88 node tests (83 + 5 new picker/route tests), 42 python tests, 141/141
route×viewport smoke checks with **0 JS errors**, 42/42 acceptance criteria (3 P1 + 8 P2 + 9 P3 +
10 P4 + 12 P5), budgets (app.js 407 KB / 450 KB, style.css 136 KB / 140 KB).

### What was built

**1. The page is four things in a column** (spec §5.2): `#artop` (header card — title, pills,
`Show on map` · `↗ Chart` · `Buildings ›` — the five headline tiles, then one toolbar row
`[Indicator ▾][Period]` with the chips under it), the **study row**, and `#arsecs` (four
`<details>`). The v2.6 **KEY FIGURES** block (12 group segments × a tile grid), the separate
**Trend** and **Neighbours** cards and the lower tab bar are deleted, with `AR.group`, `AR.tab`,
`tileSpark()`, `outlookCard()`'s card wrapper and the `data-argroup` / `data-artab` / `data-arind`
handlers. Area-page ids are now the picker's own `data-ind`, so a tile, a table row and a chip are
one control.

**2. HeadlineTiles** (`headlineHtml()` → `data-testid=tiles`, one `tile-<key>` per tile, §4.7):
mono label, the figure, `Δ y/y · #n of N` under it, 84 px, a real `<button>`. A tile whose figure is
the municipality's gets `.inh`, the inherited palette and the words **municipality figure** instead
of a rank — never a lone `°` (§1 decision 7). A projection tile carries a `Projection` pill. The
component is shared: the test property's header and the map's pin popup render the same tiles
(the popup passes `{bare:true}`, so there is one `[data-testid=tiles]` per page, not one per marker).

**3. `studyRow(entity, opts)`** — the reusable component the phase file asks for, and what P6 points
at the pin's finest area. It reads nothing off `AR` or the hash: `opts` carries `gap`, `mapId`,
`legendId`, `mapKey` and the one-line `note` over the map.
- **`chartPanel(e, opts)`** (`chart-panel`): a heading that names the indicator (`panel-title`), one
  headline row — value · Δ y/y · `#n of N` · vs median, plus a `Projection` / horizon pill and, on an
  inherited figure, "København (municipality figure)" — then the body, then `source · table · as of ·
  Verify ↗` and the definition. Four bodies: **History** (this area solid, its municipality solid,
  the peer median dashed and, on a municipality page, Denmark's own national figure dashed),
  **Snapshot** (`state-nohistory` + a `dist-strip`: one tick per peer with a figure, the median
  marked, this area a labelled dot), **Outlook** (`outlook-chart`), **Climate** (`clim-bars`: three
  horizon bars with the publisher's low–high whisker, the municipalities' median as a dashed tick,
  and a `Climate sheet ›` link). Nothing is drawn between the horizons.
- **`miniMap(opts)`** (`minimap`, §4.6): draggable, scroll zoom, `+ −` top-left, the legend inside,
  the note along the top, and `⤢` (`minimap-full`) → a fixed overlay, `✕` or Esc to close,
  `invalidateSize()` after each transition. The selected area keeps its 2 px outline; clicking a
  neighbour opens its page; zooming never selects.

**4. The indicator changes in place.** `pickInd()`, `climSetHz()` and the year select call
`areaRefresh()` before falling back to `renderKeep()`. It replaces `#artop`, the chart panel and
`#arsecs`, and repaints the polygons through the new **`arMapPaint(fit)`** on the map that is
already there — so the scroll position, the reader's pan and zoom and the full-screen overlay all
survive (AC-P4). `arMapInit()` now only builds the map and calls `arMapPaint(true)` once.

**5. Four toggles, one URL key.** `sec-outlook` · `sec-figures` · `sec-sub` · `sec-info`, open state
in `show=` (`none` when the reader closed everything). Default: municipality → `outlook` open,
postal code and quarter → nothing. *All figures* is the full indicator table (§4.8: inherited rows
`.inh` + a `muni` tag instead of `°`, projection rows a pill, the active row `.hi.on`) with the BBR
housing-stock distributions, and on a quarter page the Safety survey and the KK-vs-DST forecast note,
as sub-headings under it.

**6. The picker groups inherited indicators.** `picker_core.groupedLevel(list, order, isInherited)`
(new, pure, 4 node tests) puts every row whose figure is the municipality's under one **From the
municipality** sub-heading at the end; the popover's rows now live *inside* their `[data-group]`
container so the group can be hidden with them (AC-I5). The area page is the fourth route on the
shared picker (`PICKER_ROUTES` in `tests/ui_ac.py`).

**7. The KK vs BBR "built 2010+" gap** (ENG_BRIEF §3.4) is surfaced on the four Copenhagen quarters
where the two shares differ by more than 15 pp: the two rows are renamed (`indLabel()` →
"Dwellings commissioned 2010+ (KK, dwelling)" / "Dwellings in buildings built 2010+ (BBR, building
year)") and a one-line caveat (`data-testid=newstock-note`) says the first counts the dwelling's
commissioning year and the second the building's construction year. **Labels only — no data change.**

**8. `route_core.areaTabs()`** turns the v2.6 `t=` / `g=` into `show=` (idempotent, 2 new node
tests), so `#area/kommune/751?ind=unemp&t=bbr` still lands on the indicator table.

**9. Two smaller fixes that fell out of the rebuild.** `ePeers(e, key)` / `ePeerLabel(e, key)` name
the pool a figure belongs to — the page's own level, or the municipalities when the value on screen
is the municipality's — and `tileStats()`, `areaChart()` and the distribution strip all compare
against it, so an inherited figure is no longer measured against 606 postal codes that do not
publish it. And `tests/ui_ac.py`'s `goto(..., wait=…)` waits for `state="attached"` like
`tests/ui_smoke.py` does: a Leaflet pane has no size, so the default "visible" wait burned its full
15 s on every map AC and then passed anyway (~90 s a run).

### ACs delivered
AC-P1, AC-P2, AC-P3, AC-P4, AC-P5, AC-H1, AC-H2, AC-I5, AC-E2, AC-MM1, AC-MM2, AC-R2 — all MUST,
all registered in `tests/ui_ac.py` under `phase="P5"`. AC-I1 and AC-I4 (P3) now also run on
`#area/kommune/101`.

### Deviations
- **AC-P5 is asserted on the study row, not on the page.** Horizontal overflow at 390 px is the
  v2.6 shell defect P8 owns; the row and its two halves are checked against the column they sit in.
  See `DECISIONS.md` — a Leaflet container always reports `scrollWidth > clientWidth`.
- **The full-screen overlay is `z-index:1400`, not §4.6's `100`** — the picker is 1200 — and it
  carries its own chips row (`minimap-chips`), because it covers the page's toolbar and the phase
  file requires an indicator change to work while the map is full screen.
- **The BBR distributions are a sub-heading of All figures**, not a fifth toggle: §5.2 lists four.
- **The header actions stay in the header card**, where §5.2 draws them, rather than in the top
  bar's actions slot P4 introduced.
- The history line gained a fourth series (Denmark's own national figure) on municipality pages;
  §5.2 asks for "Denmark (dashed green, municipalities only)" beside the peer median, and the two
  are different things, so the legend names both.

### Known issues / open items
- Horizontal overflow at 390 px is still a note on every route (v2.6 defect); **P8 flips
  `OVERFLOW_FATAL = True` in `tests/ui_smoke.py`**. At 390 the area page's column is ~232 px wide
  because the ≤900 px media query gives the sidebar a full-width grid column — everything in the
  study row is laid out correctly inside that column, it is the column that is wrong.
- `style.css` is at 136 KB of the 140 KB budget. P6–P9 have ~4 KB; the v2.6 Finnish-commented
  legacy block (lines 76–1110, mostly unused by the DK app) is where a daytime clean-up would find
  room.
- The KK vs BBR gap and the surge keys' horizon-in-the-`desc` are both still data tasks.

### What the next phase must know
- **`studyRow(entity, opts)` is P6's.** Hand it `tpEntity(r)` (the pin's quarter → postal code →
  municipality) and `{ mapId: "anmap", legendId: "anlegend", mapKey: "anmap", note: … }`. The map
  key must be in `LF_MAPS`; `data-mapkey` on the wrapper is how `mmFull()` finds the instance to
  call `invalidateSize()` on. Do **not** write a second chart panel.
- **`headlineHtml(e)` is the §4.7 tile component** and already emits `tile-<key>` + `data-ind`, so
  AC-TP3 ("clicking `tile-unemp` sets `ind=unemp` and changes the mini-map legend title") is a
  matter of wiring the test property's own refresh, not of new markup. `{bare:true}` leaves the test
  id off for a copy inside a popup.
- **An in-place update is `areaRefresh()`-shaped**: replace the parts, never the map. P6 wants the
  same for the test property — the pattern is one `#<id>` per region of the page plus
  `arMapPaint()`-style repainting, and `UI.mmFull` already survives it.
- **`AR.show` / `show=`** is the fold-state pattern for §5.5′'s `tp-sec-<name>` sections: one
  `AR_SECS`-style list, a `<details data-sec=…>` per section, one branch in the `toggle` listener,
  one `arShowParts()`-style serialiser in `hashFor()`.
- `pickInherits(i, level)` + `PC.groupedLevel()` is the whole of "From the municipality" — a view
  that shows a finer level than the figure gets it for free once `pickLevel()` knows the level.
- `srcNoteBody(extra)` is the source catalogue without the `<details>` around it; `srcNote()` is
  still the wrapped version every other view uses.

---

## P6 — The test property rebuilt around the study row (one pin)

Commit: `v3.0 P6: test property rebuilt on the study row, Layers ▾, radius and eight sections`
Gate: green — build, 88 node tests, 42 python tests, 150/150 route×viewport smoke checks with **0 JS
errors**, 49/49 acceptance criteria (3 P1 + 8 P2 + 9 P3 + 10 P4 + 12 P5 + 7 P6), budgets
(app.js 420 KB / 450 KB, style.css 136 KB / 140 KB).

### What was built

**1. `#property?p=lat,lon[:label]` is the area page's study row, anchored on a pin** (spec §5.5′).
`vAnalysis()` is now three regions in a column — `#tptop` (header card + one toolbar row), the
**shared `studyRow(e, opts)`**, and `#tpsecs` (eight `<details>`) — pointed at `tpEntity()`, the
pin's finest published area (quarter > postal code > municipality). No second chart panel and no
second mini map were written: the panel, the four bodies (history · snapshot · outlook · climate),
the headline tiles, the picker, the period control and the ⤢ overlay are P3's and P5's components.
The v2.6 "Where it is" card, the `anLayerBar()` pill row and the eight free-standing cards are gone.
- `anRes()` / `anEntity()` are the memoised located result and entity for the page's pin (the same
  arrangement `tpRes()` has for the map's pin). `curInds()`, `curPool()` and `pickLevel()` answer
  from them, so the picker, the year list and the `muni` tags are the pin's level, not the map's.
- The identity line carries a `read as <level>` tag: the figures are the quarter's / postal code's /
  municipality's, never the address's.

**2. One toolbar row** (`data-testid=tp-toolbar`): `[Indicator ▾][Period]` on the left, `Layers ▾`
and a `radius` select on the right, chips underneath — the §5.5′ layout.
- **`layersMenu(kind)`** now serves both maps. `TP_LAYERS` (infra · public buildings · BBR buildings,
  plus the municipality's storm-surge zones as context) is the test property's list, `MAP_LAYERS` the
  map's; `mapLayerToggle()` routes to `tpLayerToggle()` here. A layer toggle redraws the overlays on
  the map that is already there and re-renders the menu — it never rebuilds the page.
- **`rad=`** (500 m · 1 km · 2 km · 5 km, default 1 km) draws the solid ring on the mini map *and* is
  the ring "Public buildings within" and "Schools within" count inside.

**3. The tiles, the picker and the chips all drive the page in place.** `tpRefresh()` is the
`areaRefresh()` of this page: it replaces `#tptop`, the chart panel, the note, the chips and
`#tpsecs`, then repaints the map through the new **`anMapPaint()`** (`anMapInit()` was split into
"build the map" and "draw this indicator on it", exactly as P5 split `arMapInit`). `pickInd()`,
`climSetHz()`, the year select and the radius select all try `areaRefresh() || tpRefresh()` before
falling back to `renderKeep()`, so the reader's pan, zoom and full-screen overlay survive every pick.

**4. One paste box, one pin.** `tpBox()` gained `data-testid=prop-input` and a `Go` button; Enter,
paste and Go all run `tpGo()`. On this page a new link **replaces** the pin and its label (a different
address is a different property). The empty state is `data-testid=state-empty` with the caret already
in the box, the privacy line and one example link.

**5. Eight `<details>`** (`tp-sec-outlook|profile|safety|infra|public|schools|climate|sources`), open
state in the same `show=` key the area page uses, on its own `AN.show` set and `data-tpsec` branch.
Default open: `infra`. The existing card content moved in unchanged apart from losing its card
wrapper (`anOutlookBody`, `anIndTable`, `anInfraBody`, `anPubBody`, `anSchBody`, `anClimBody`,
`anSources`) — the card heads became the sections' summaries and hints.

**6. Public buildings are grouped.** Rows whose name, BBR use code and distance (to 20 m) all match
are one row with a `×n` badge — one building registered as several bodies. The caption says how many
records were folded; the distance shown is the nearest of them.

**7. Header actions** (spec §5.5′): `Open on map ›` · `Copy link` · one link per level the pin sits
in (quarter · postal code · municipality) · `OpenStreetMap ↗`. `D.portfolio`'s "own properties" path
is untouched — it is still one row in the map's Layers menu and is hidden without the file.

**8. The mini map's legend stack.** `miniMap(opts)` takes `opts.legends`, and the indicator legend
plus the pin's overlay legends now live in one `.maplegs` column, indicator first. `lgFit()` was
split into `lgFitIn(wrap, map, order)` and runs over the mini map's stack too, so §4.5's
"never more than 60 % of the map's height" holds there as well — the overlay legends fold to their
titles when they would not fit.

### ACs delivered
AC-TP2, AC-TP3, AC-TP5, AC-E1 (read `#properties` as `#property`), and **AC-MM1TP / AC-MM2TP** —
AC-MM1 and AC-MM2 asserted on the test property, registered under their own ids because P5 owns
`AC-MM1`/`AC-MM2` on the area page and an id may be registered once. Plus the phase-local
**AC-TPSEC** (the eight sections, `show=`, and the public-building grouping). **AC-TP1** (P2) is
re-checked by the suite and still passes. AC-I1 and AC-I4 (P3) now also run on `#property`.

### Deviations
- **AC-P1MM (P1-local) was updated**: it counted 3 rings + the pin on `LF.anPinG`, and §5.5′ adds the
  ring the radius select names, so it counts 5. The invariant is unchanged; see `DECISIONS.md`.
- **Multi-pin stays in the codec only.** `route_core.propParse/propSerialise` are still list-capable
  and `p=a;b` still parses, but only the first item is rendered and only one is written (amendment
  A2). *Several pasted links all appearing on the map is the owner's future idea* — it needs no
  format change when it lands, only a view that loops.
- **The indicator list on a Copenhagen pin is the quarter registry.** `curInds()` now answers from
  the pin's entity, which is right, but it means price/m² and private rent are not in the picker on
  a Copenhagen pin — the quarter layer does not publish them. Before P6 the list came from the map's
  own state, so it depended on where the reader had last been. In `DECISIONS.md`.
- **The radius select replaced the Layers ▾ radius row on this page.** §5.5′ draws it in the toolbar;
  the Layers menu keeps its radius row on the *map*, where it filters the overlays around the pin.
- **`Sources & as of` links to `Data › Sources`**, not to the v2.6 `#market?src=1` spelling.

### Known issues / open items
- Horizontal overflow at 390 px is still a note on every route (v2.6 shell defect); **P8 flips
  `OVERFLOW_FATAL = True` in `tests/ui_smoke.py`**.
- At ≤ 800 px the five headline tiles wrap 2×3 and the sixth grid cell shows the `.tiles` background
  as a grey slab. It is the shared §4.7 component, so the area page has it too (it arrived with P5);
  a `:last-child` span or an odd-count rule in `.tiles` would fix both. Cosmetic, P8/P9.
- `style.css` is at 136 KB of the 140 KB budget (3.9 KB left for P7–P9). The v2.6 Finnish-commented
  legacy block (lines 76–1110, mostly unused by the DK app) is where a daytime clean-up would find
  room; P6 reclaimed the `.anhead .hl` rules it made dead.
- The Export ▾ menu and the two Test property CSV files (AC-TP4, §5.5′) are **P7's** — the sidebar
  button still calls `exportAll()`.
- The KK vs BBR "built 2010+" gap and the surge keys' horizon-in-the-`desc` are still data tasks.

### What the next phase must know
- **`tpRefresh()` is the test property's `areaRefresh()`.** Anything that changes what the page is
  showing (an indicator, a horizon, a year, a layer, the radius) must call
  `areaRefresh() || tpRefresh()` before `renderKeep()`, or the map is torn down and the reader loses
  their pan, zoom and full-screen overlay.
- **`anMapPaint()` draws, `anMapInit()` builds.** A repaint never moves the camera; only the init
  fits the bounds, and only for a pin/radius it has not framed before (`LF.anKey`).
- **`anEntity()` is the test property's `areaEntity()`** and it is memoised in `ANC` on
  `lat,lon,<have the kommune rings landed>`. Call it rather than `locate()` — `locate()` walks 606
  postal-code rings and the picker asks for the level on every render.
- **`layersMenu(kind)` takes a list now.** A third map with layers adds a `*_LAYERS` array and one
  branch in `mapLayerToggle()`; it does not add a menu.
- **`miniMap({..., legends})`** is how extra legend cards get inside a mini map, and
  `lgFitIn(wrap, map, order)` is how a stack is kept inside its map. Give a new legend an id and put
  it in the fold order (`MM_FOLD_ORDER`) or it will never fold.
- **P7 (Export):** `anRing()`, `anPubKoms()`, `anPubGroup()` and `anInfraRows()` are the functions
  that decide what the Test property CSV's `nearby` file must contain — the export should read the
  same ones so the file and the page can never disagree. `tpEntity()` gives it the
  `level, code, value_type` columns for the long schema.
- **P8 (responsive):** the test property's toolbar puts `Layers ▾` and the radius in a `.tp-right`
  block that becomes a full-width row below 600 px; the study row is the same component the area
  page uses, so whatever P8 does to `.studyrow` applies to both.

---

## P7 — One export model, with sources on every row

Commit: `v3.0 P7: one export model, Export ▾ menu and sources on every row`
Gate: green — build, **116 node tests**, 42 python tests, 150/150 route×viewport smoke checks with
**0 JS errors**, **55/55 acceptance criteria** (3 P1 + 8 P2 + 9 P3 + 10 P4 + 12 P5 + 7 P6 + 6 P7),
budgets (app.js 446 KB / 450 KB, style.css 139 KB / 140 KB).

### What was built

**1. `src/export_core.js`** (IIFE → `window.EXPORT_CORE`, pure, wired into `src/index.html` and
`scripts/build_dashboard.py` as `{{EXPORT_JS}}`, 28 `node --test` cases in `tests/export.test.js`).
It owns everything about a file that is a function of the registry and the source catalogue alone:
- the **column sets** — one long schema for areas, national series and the test property
  (`level … licence`, spec §4.9 verbatim), and an own schema for projects, the sources catalogue,
  the climate exposure and the test property's `nearby` file;
- the **source columns** of one row (`source, table_id, source_url, as_of, fetched, licence`),
  filled in one fixed order: `tables` → `proj` → `climate_src` → `src_page` → a `KK…` id parsed out
  of the source string (the quarter registry carries it nowhere else, ENG_BRIEF §3.2) → a DST id
  named in prose → `n/a (register/curated)`. **No row has a blank `source`, `as_of`, `table_id` or
  `fetched`** (AC-X4);
- the **unit fix**: a `fmt: kdkk` indicator is stored in DKK, so the file writes the raw number and
  says `DKK / yr`; any other row whose unit says kDKK with a value ≥ 10 000 is converted, so the
  label always matches the number (AC-X2);
- `period_type` (year · quarter · month · school_year · window · snapshot · horizon · projection,
  read off the publisher's own period label) and `value_type` (actual · projection · inherited ·
  derived, read off the registry);
- the **CSV rules**: UTF-8 BOM, `;`, `.` decimals, no grouping, no separator or newline inside a
  cell, header first, one comment-free file.

**2. Seven files, one menu.** `Export ▾` (`export-btn` / `export-menu`, `role=dialog`) renders in
the **sidebar footer** (which also gained the build/version line of spec §4.1), in the **Data
header** and in the **test-property header**; one is open at a time (`UI.xOpen` names which).
Items: `view · areas · projects · national · sources · climate · property`.
- `areas_long_<date>.csv` — **104 028 rows**: 99 municipalities, 606 postal codes, 67 quarters ×
  every indicator × every published period, plus the Climate family at its three horizons. A
  municipality figure read on a finer level is one `inherited` row with `inherited_from` set.
- `projects_<date>.csv` — 51 rows, own schema, plus the postal codes and quarters each project
  serves and its geometry kind, length and station count.
- `national_series_<date>.csv`, `sources_<date>.csv`, `climate_exposure_<date>.csv` (level ×
  horizon: dwellings, dwellings in zone, share, zone km²), `test_property_<date>.csv` (the pin's
  three columns in front of the long schema, every level it sits in) **+
  `test_property_nearby_<date>.csv`** (`kind, name, type, status, distance_m, source, source_url`),
  and `This view` (the wide Areas table, one area's figures, or the plotted series).
- A one-line **toast** (`export-toast`) says what was written: `areas_long_2026-09-24.csv · 104 028
  rows · 3 levels · every published period`. The lazy public-building and school files are awaited
  before the `nearby` file is written.

**3. The v2.6 export paths are gone.** `exportAll()` (the single long CSV that jammed projects and
macro series into indicator columns), `exportCsv()` and `exportPipelineCsv()` are deleted, with the
sidebar's four-line explanation. The Areas and Projects toolbar buttons call the same builders
(`This view (CSV)`, `Projects (CSV)`). **Data › Sources renders `EXPORT_CORE.sourceRecs()`** — the
rows the catalogue file writes — so the table and the file cannot disagree; `SRC_PUB`,
`srcPublisher` and `srcTableId` went with it.

### ACs delivered
AC-X1, AC-X2 (adapted as the phase file asks: kDKK rows are < 10 000 *because* an income row is
written in DKK), AC-X3, AC-X4, AC-TP4 — all MUST — plus the phase-local **AC-XMENU** (one menu in
three places, Esc, the v2.6 button gone, and Data › Sources ≡ the sources file). Registered under
`phase="P7"` in `tests/ui_ac.py`.

### Deviations
- **Inherited figures are written for the latest period only** (own figures keep their full
  history). The municipality's series is in the same file on its own rows; repeating it under 606
  postal codes would have tripled the file to say nothing new. In `DECISIONS.md`.
- **The wide "This view" file carries provenance in its column headers**
  (`growth (% / yr) · FOLK1A POSTNR1 · as of 2025→2026`). §4.9 asks for that export to stay wide
  *and* for every file to carry its sources; a wide layout has nowhere else to put them.
- **Charts keeps its own `⤓ Data CSV`** (the picture's own table, including quarters and the BBR
  distributions); `Export ▾ › This view` writes the plotted series in the long schema.
- **Copenhagen quarters have no Climate rows in `areas_long`** — the quarter registry publishes no
  Climate indicator (the P4 limitation). Their zone exposure *is* in `climate_exposure`, which
  reads the per-horizon index directly.
- **`dwellings` / `dwellings_in_zone` are empty for a municipality** in `climate_exposure`: the
  inline payload keeps the municipal share and the zone area only (the counts are per postal code
  and per quarter). The share and the zone area are there, and the source columns are filled.
- Services are not in the `nearby` file: the test property's layers are infra, public buildings and
  BBR buildings (P6), so there is no service list on that page to export.

### Known issues / open items
- `style.css` is at **139 KB of the 140 KB budget** (≈ 1.0 KB left). P8 rebuilds the responsive
  shell and will need room: the v2.6 Finnish-commented legacy block (`src/style.css` lines 76–1110,
  mostly unused by the DK app) is where a daytime clean-up would find several KB. P7 reclaimed the
  two dead sidebar rules (`.side-foot label`, `#remu`).
- `app.js` is at 446 KB of 450 KB (≈ 14 KB left) — new pure logic belongs in a `*_core.js` file.
- The sidebar's Export ▾ popover is sized to the 240 px panel because `aside` scrolls and would cut
  anything wider off. When P8 turns the sidebar into a 52 px top bar with a drawer, that menu wants
  re-checking (the header copy is unaffected).
- Horizontal overflow at 390 px is still a note on every route; **P8 flips `OVERFLOW_FATAL = True`**.
- Data tasks unchanged: the KK vs BBR "built 2010+" gap, the surge keys' horizon-in-the-`desc`, and
  `cph.json` indicators carrying no `tables` (the export parses the `KK…` id out of the prose).

### What the next phase must know
- **Every new file goes through `EXPORT_CORE`**, and every builder gets a `node --test` case. app.js
  supplies the data and two callbacks (`periods(i, o, level, inherited)` and `inherited(i, row)`);
  nothing about a column, a unit or a source belongs in app.js.
- **`exportGo(kind)` is the one entry point** (`[data-export=<kind>]`), `exSave(stem, cols, rows,
  extra)` the one writer: it names the file with the data's build date, adds the BOM through
  `downloadCsv()` and shows the toast. A new dataset is one `EX_ITEMS` row plus one `exportGo`
  branch.
- **`UI.xOpen` is `"side" | "page" | ""`** — the trigger toggles, so anything that opens the menu
  programmatically must check first (the AC helper `open_export()` does).
- **P8/P9:** `[data-testid=export-btn]` and `[data-testid=export-menu]` exist twice on the Data and
  test-property routes (one per trigger, §10 names both ids); scope a locator to `.hd-act` or
  `#xfoot`, or take `.first`, rather than asserting there is only one.
- **P9 (docs):** the file names, the schemas and the "every row carries its source" line belong in
  `README.md` / `CHANGELOG.md`; the column list is in `docs/v3/UI_SPEC_v3.md` §4.9 and in the header
  of `src/export_core.js`.

---

## P8 — The responsive shell, the number rules, the sheets and accessibility

Commit: `v3.0 P8: responsive shell, number rules, sheets and accessibility`
Gate: green — build, 116 node tests, 42 python tests, 150/150 route×viewport smoke checks with
**0 JS errors and 0 horizontal overflow** (`OVERFLOW_FATAL = True`), **63/63 acceptance criteria**
(3 P1 + 8 P2 + 9 P3 + 10 P4 + 12 P5 + 7 P6 + 6 P7 + 8 P8), budgets
(app.js 445 KiB / 450, style.css 136 KiB / 140).

### What was built

**1. The app shell is a layout at every width** (spec §4.1, §6). `src/index.html` gained a 52 px
`.mtop` bar (`topbar-mobile`) with `☰` (`nav-toggle`) and a `.drawer` (`nav-drawer`) **around the
existing `<aside>`** — one element is the sidebar and the drawer's panel, so there is no second copy
of the nav (and no third `export-btn`). `.drawer` is `display:contents` at ≥ 1025 px, so the desktop
grid is unchanged apart from `--sidew` becoming a flat **240 px** (§4.1; the 212/180 steps went).
Below 1025 px: one column, `body{overflow:auto}`, `.app{display:block}` — the page scrolls natively
— and the drawer is a fixed off-canvas panel with a scrim, Esc, a focus trap and focus handed back
to `☰` (`navDrawer()`, `navFocusables()`, `NAVD`). The closed drawer is `visibility:hidden`, which
is what keeps `<aside>` out of the tab order, the a11y tree and Playwright's `is_visible()`.

**2. Horizontal overflow is gone at every viewport, and it was one bug.**
`@media (max-width:900px){:root{--sidew:100%}}` never undid `.app{grid-template-columns:var(--sidew)
1fr}`, so at 390 px the phone grid was `390px 1fr` and every page was laid out in a second column
starting at x ≈ 412 (the ~232 px content column P5 reported). `.card{overflow-x:auto}` masked it per
card. Deleting both cleared **all** routes at 390, 1366, 1440 and 1536 in one go.
`tests/ui_smoke.py` now has `OVERFLOW_FATAL = True`, checks **every** viewport rather than only
phone width, adds `1536x864` to `VIEWPORTS`, and reports the offending elements by name through one
shared expression (`OVERFLOW_JS`) that `tests/ui_ac.py` imports for AC-R1.

**3. The rest of the §6 matrix.** Toolbars stack — `.trow` / `.artools` needed an explicit
`width:100%` below 1025 px, because nested in two flex columns the map toolbar's first row was
sized to its *max-content* (597 px at 390) and the card simply clipped the picker's right-hand end;
AC-S1 now asserts that no toolbar control runs past `#mapcard`. The chips row scrolls sideways;
tables scroll inside their card with the first column pinned (`.scrollx > .tbl th/td:first-child`);
the tile grid goes 5 → 3+2 → 2 **and fills its last row**, which removes the grey slab P6 logged;
the map goes edge to edge inside its card at ≤ 600 px (a map is the one thing that wants every
pixel — AC-S1 asks for ≥ 350 of 390); the legend stack folds behind one `Legend ▾` pill
(`legend-toggle`), toggled in place so the map underneath is never torn down; the breadcrumb bar is
sticky under the 52 px bar and the two together stay inside §6's 96 px.

**4. The number rules through one path** (spec §2.4). `rankHtml(rk, label)` is now the only rank
renderer — `#n of N` everywhere with a `title` that names the peers ("of 77 municipalities with a
figure"); the climate sheet's `#n / N` was the last survivor of the second format. `DASH` / `NC`
separate "the publisher has no figure" from "not computed at this level". `projPersons()` /
`projValueHtml()` / `smallBaseTag()` read the projection's own window out of the registry and render
a projected % change **persons-first with a `small base` tag** when the base is under 1 000 persons,
on the headline tiles, the chart panel's headline row and the Population-outlook tiles alike.

**5. Sheets** (§5.7). `sheetTiles()` gives the project, public-building, school and climate sheets
one §4.7 tile row (`data-testid=tiles`) and **never renders an empty slot** (AC-SH1). The climate
sheet's header uses the shared PeriodControl (`periodHz()` → `data-testid=period[data-mode=horizon]`
around the same `hzPill`), and "Show the zones on the map" emits the canonical
`map/<kom>?ind=surge_dw_pct&hz=<hz>` (AC-SH2). The project sheet gained its `Source ↗ · updated`
line and the school sheet a `Verify ↗ Uddannelsesstatistik` line under the tiles.

**6. Empty / loading / error states** (§4.10). `stateCard(kind, title, note, action)` →
`data-testid=state-empty|state-loading|state-error`, mono caption, one action, a three-bar skeleton
while loading, never a modal. Wired into the two places that actually wait for a file: the test
property before `geo/kommuner_lookup.json` lands (and an error card when it fails), and the
public-building sheet before `public/<kom>.json` does.

**7. Accessibility** (§7). One `:focus-visible` ring for the whole app; `aria-expanded` on every
popover trigger (the new `nav-toggle` and `legend-toggle` join the picker, Layers and Export);
11 px captions off `--muted` onto `--cap-ink` (`#6F7168`) on `.cap,.hint,.xcap,.laynote,.mm-note`;
the breadcrumb `›` separators are `aria-hidden`; the search dropdown's rows are `tabindex="-1"`
(it is a listbox driven by ↑ ↓ and Enter, and it opens on focus — 606 postal codes in the tab order
buried every control after it, which is what AC-A2's twelve tabs exposed) and it now closes when
focus leaves the box, so tabbing past it no longer leaves a list standing over the toolbar.

**8. The P4 Copenhagen-climate limitation is fixed in the UI.** `#map/101` with a Climate indicator
now switches to the **postal-code** view instead of swapping the indicator (and the storm-surge
zones) away: `cph.json` publishes no Climate key, but the postal codes do. No data change.

**9. Room for it.** 15.8 KB of the v2.6 Finnish-commented legacy CSS was deleted — 17 contiguous
blocks whose class names occur in no `src/*.js` and not in `src/index.html` (`.tg*`, `.tgroup*`,
`.mix-*`, `.pcard`/`.pc-*`, `.vbanner`/`.vb-*`, `.mk-*`, `.cxy*`, `.wk*`, `.sortth`, `.chwrap`).
`style.css` went 139 KB → 129 KiB before P8's own block.

### ACs delivered
AC-S1, AC-S2, AC-R1, AC-SH1, AC-SH2, AC-A1, AC-A2, AC-G1 — all MUST, all registered in
`tests/ui_ac.py` under `phase="P8"`. AC-S3 (P4) and AC-P5/AC-R2 (P5) still pass.

### Deviations
- **AC-A1 is a DOM check, not axe-core**, exactly as the phase file allows: `src/vendor/axe.min.js`
  is not in the repo and the run installs nothing. It asserts an accessible name on every visible
  control, `aria-expanded` on everything with `aria-haspopup`/`aria-controls`, and a text
  alternative on every `img` / `svg[role=img]`, on the four routes the spec names. Leaflet's own
  controls are excluded — vendor markup, not ours. **A daytime follow-up should run real axe-core.**
- **AC-G1 is asserted in two halves** (see `DECISIONS.md`): none of the dashboard's *own* words
  (button, heading, `th`, tile label, tag, chip, legend title) matches the phrase, and every
  remaining visible match is a verbatim substring of the built registry — the publisher's prose.
  Two DST descriptions use "score" as a verb and Uddannelsesstatistik publishes the FP9 grade
  "pupil-weighted"; `data/` is out of this run's reach. The four captions where **app.js itself**
  said "weighted" were reworded, so nothing is exempted by name.
- **AC-SH2 lands on `map/101/postnr`**, not `map/101`. The AC asks for "a hash starting `map/101`",
  which it is; the postal-code view is what makes the surge indicator and its zones survive the
  drill (item 8 above).
- **The school sheet's `Verify ↗` is one line under the tile row**, not one link per tile as §5.7
  reads. Six identical links inside six 84 px tiles is noise; the line names the institution number
  and the school year the tiles are from.
- `1536x864` is in `tests/ui_smoke.py`'s `VIEWPORTS` but **not** in the gate's `--viewports` (the
  gate script is outside this run's allowed files). AC-R1 walks all four widths itself.

### Known issues / open items
- `src/app.js` is at **445 KiB of the 450 KiB budget** (≈ 5 KB left) and `src/style.css` at 136 KiB
  of 140 (≈ 4 KB). P9 has room for docs and small fixes only; anything larger wants either a
  new `*_core.js` or another pass over the legacy CSS (≈ 6 KB of contiguous dead blocks remain, and
  ~17 KB more in single lines — the same analysis, run per rule instead of per block).
- The small-base rule has **no live case in the Danish data**: the smallest projection base is well
  over 1 000 persons, so `smallBaseTag()` never fires on a real page today. It is exercised by
  reading `projValueHtml`/`projPersons` directly, not by a route.
- `stateCard` is wired into two lazy paths. The services, micro and climate-zone loads still show
  their v2.6 inline text; a later pass can move them onto the same component.
- The KK vs BBR "built 2010+" gap and the surge keys' horizon-in-the-`desc` are still data tasks.
- `scripts/ui_check.py` still drives `#compare` (P2's note) and is not part of the gate.

### What the next phase must know
- **The shell is `.mtop` + `.drawer` + `<aside>` + `<main>` in `src/index.html`.** A new sidebar item
  goes in `renderNav()` and appears in both places automatically, because there is only one place.
  Anything that opens the drawer programmatically must go through `navDrawer(true|false)` — it owns
  `aria-expanded`, the body class, the focus trap and the focus hand-back.
- **Overflow is fatal now.** A new card, table or toolbar that is wider than its column fails the
  gate at 390 *and* at 1366. Put a table in `.scrollx`, cap a popover at `100vw`, and check the
  smoke message — it names the element.
- **`rankHtml`, `DASH`, `NC`, `projValueHtml`, `smallBaseTag` are the §2.4 path.** A new surface that
  shows a rank or a projected change uses them; do not re-format inline.
- **`sheetTiles(items)` is the §5.7 tile row** — `[label, valueHtml, subHtml]`, a null slot is
  dropped. `stateCard(kind, …)` is the §4.10 card, with the `state-*` test ids.
- **`periodHz(where)`** is the PeriodControl in horizon mode on its own, for a header that is not
  driven by the picker's active indicator (the climate sheet).
- P9 (docs): the responsive matrix, the drawer, the `state-*` ids and the number rules belong in
  `README.md`; `OVERFLOW_FATAL` and the two-half AC-G1 belong in `tests/README.md`.
