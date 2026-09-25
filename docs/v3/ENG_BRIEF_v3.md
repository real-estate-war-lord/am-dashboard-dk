# ENGINEERING BRIEF — v3.0 UI overhaul, unattended overnight run

Repo: `am-dashboard-dk` at v2.6, commit `c020f37` (main). All line numbers below refer to that commit's
`src/app.js` (4 257 lines, 358 KB). Read `CONTEXT_UI.md` first for *what* changes; this brief is *how the code
is built, how to verify it, what was found, and in what order to do it*.

> **Superseded parts:** the phase plan in §5 and the run script in §6.3 are replaced by `docs/v3/phases/P*.md`
> and `overnight.sh` at the repo root. The run uses an explicit tool allow-list (`--permission-mode acceptEdits
> --allowedTools …`), never a permission bypass — see `_COMMON.md`. Owner amendments in `UI_SPEC_v3.md` (top): Compare is deleted; the test
> property stays single (route `#property`), portfolio is LATER. Paths: the smoke draft lives at
> `docs/v3/ui_smoke_v3.py` until P1 moves it to `tests/ui_smoke.py`.

Navigation trick for any session: `grep -n "^function \|^const [A-Z_]* = {" src/app.js` gives the whole
map in ~450 lines. Never read app.js end to end.

---

## 1. Architecture map of `src/app.js`

### 1.1 Build & load order (scripts/build_dashboard.py → dist/index.html)
`src/index.html` is a template with placeholders, replaced in this order: `{{LEAFLET_CSS}}`, `{{APP_CSS}}`
(style.css), `{{LEAFLET_JS}}` (src/vendor/leaflet.js, 1.x), `window.DATA = {{DATA}}`, `{{TESTPROP_JS}}`,
`{{CLIMATE_JS}}`, `{{APP_JS}}`. All are **classic scripts in one global lexical scope**: a top-level `const`
in one file that collides with another is a SyntaxError that blanks the page (this is why climate_core.js is
an IIFE exposing `window.CLIMATE_CORE`, and testprop.js only exposes `parseLocation` + `TP_*`). `check_js()`
runs `node --check` per file before inlining. Adding a source file = edit **both** `src/index.html` and
`build_dashboard.py` (`.replace("{{X}}", ...)`). Build takes **0.7 s**, needs no network, only stdlib
(shapely optional). Output 5.0–5.2 MB (DATA ≈ 4.3 MB); on-demand files copied next to it: `micro/`,
`public/`, `services/`, `climate/`, `geo/kommuner_lookup.json`, `schools.json`, `infra_*`.
`dist/index.html` and the copied folders are **git-ignored** (only `dist/public/*.json` is tracked — leave it).

### 1.2 Data globals (lines 23–60, 1296–1302, 2420, 2630–2633, 2934, 3212–3243, 3739)
| Global | Source | Notes |
|---|---|---|
| `D` | `window.DATA` | schema comment at top of file (lines 5–12) |
| `IND` | `D.indicators` (63) | national indicator registry (config/indicators.json → build_makro.py) |
| `MUNI`, `AREAS`, `byCode`, `byNr` | municipalities (99), postal codes (606) | `AREAS[i].rings` = Leaflet-order `[lat,lon]` rings |
| `CPH`, `IND_CPH`, `byQ`, `CPH_MUNI="101"` | `D.cph` | Copenhagen quarters (31 indicators, key `geo_level` kvarter/bydel) |
| `IND_Q` (line 60) | `IND_CPH` + national Safety | the quarter-level indicator list |
| `NAT` | `D.national` | national values per indicator (Denmark line in charts) |
| `D.macro` | market.json | `series{key:[{t,v}]}`, `latest{key:{v,t,label,unit,yoy,src}}` → vMarket |
| `INFRA_ALL/INFRA/INFRA_BY/INFRA_IDX` | `D.infra`, `D.infra_index` | projects; `map:false` = list only |
| `PUB`, `PUB_FILES` | `D.public` + lazy `public/<kom>.json` | public buildings |
| `SRV`, `SRV_FILES` | `D.services` + lazy `services/<kom>.json` | OSM/Rejseplanen points |
| `CLIM`, `CZ`, `CRA` | `D.climate` + lazy `climate/surge_<hz>/<kom>.json`, `climate/risk_areas.json` | |
| `MICRO_IDX`, `MICRO` | `D.micro` + lazy `micro/<kom>.json` | BBR building dots |
| `SCH_META`, `SCH_BY`, `SCHOOLS` | `D.public.schools` + lazy `schools.json` | |
| `KOM` (206) | lazy `geo/kommuner_lookup.json` | kommune rings for the test-property pin (`locate()` 1535) |
| `D.portfolio` | `data/processed/portfolio.json` (absent → null) | "Own properties" hook, see 1.10 |

### 1.3 State objects (all plain mutable objects; the hash is the source of truth)
| Obj | Line | Fields | Owner view |
|---|---|---|---|
| `S` | 146 | `view` ∈ makro, table, area, charts, market, pipeline, project, public, publist, school, schoollist, analysis, climate, compare | router |
| `MK` | 149 | `ind, muni, own, year, cphView, micro, mind, infra, pub, srv, clim, focus` | macro map (`ind`/`year` are **global** — area, analysis, table reuse them) |
| `HZ` | 3217 | `h` ∈ today/2070/2120 | climate horizon (hash `hz=`) |
| `CF` | 3222 | `show` Set(areas,surge) | climate overlay filter (hash `clim=`) |
| `AR` | 166 | `type, code, group, ind, sub, tab` | area page |
| `T` | 207 | `q, level, region, minPop` | table |
| `CH` | 169 | `ind, areas[], y0, y1, median, title, mode, dist, fq, ov[], nat` | charts |
| `AN` / `ANL` / `TP` | 182 / 186 / 197 | `a, label` / `infra,pub,micro,climate` / `lat,lon,label,res,msg,fit,rad` | analysis sheet / its layer pills / the pin |
| `CMP` | 3496 | `a, b` ("kommune:101", "kvarter:20602", "postnr:2450") | compare |
| `CS` | 3609 | `code` (4-digit) | climate sheet |
| `PR, PB, PL, SC, SL` | 170–174 | project id / public building / public list key / school nr / school list key | sheets |
| `PIPE` | 181 | `type, status` | pipeline filters |
| `MKT` | 168 | `src` | market: sources fold open |
| `PF`, `SF` | 176, 2970 | public cats/kind; services cats/tmodes | overlay filters (hash `pub=`, `srv=`) |
| `MF` | 162 | building filters | micro mode |
| `UI`, `LEGC` | 167, 3192 | fold states that survive re-render | |
| `LF` | 209 | `map, center, zoom, level, ctx, areaG, labG, ...` **plus** `amap` (area mini-map), `anmap` (analysis mini-map), `pmap` (project/public sheet map), the renderers `canvas, srvCanvas, pubCanvas, climCanvas, anCanvas`, and every layer group (`infraG, pubG, srvG, climAreaG, climZoneG, anInfraG, anPubG, anClimG, tpG …`) | ALL maps share this bag — see §2.4 |

### 1.4 Routing (lines 236–318)
- `hashFor()` 237: serialises state → `path?query`. Path per view: `map[/<muni>[/postnr]]`, `table/<level>`,
  `area/<type>/<code>`, `charts`, `analysis`, `market`, `project/<id>`, `compare`, `climate/<code>`,
  `public/<kom>/<id>`, `publist/<key>`, `school/<nr>`, `schoollist/<key>`, `pipeline`. Common query:
  `ind=`, `y=`, `hz=`; map-only: `micro, mind, infra, public, pub, services, srv, climate, clim, focus, pin, pl, rad`;
  area: `g, sub, t`; charts: `ind,a,y0,y1,med,mode,dist,fq,ov,nat`; analysis: `a, la, ind, y, lay, pub, hz`;
  compare: `a, b, hz`; pipeline: `ptype, pstatus`; market: `src`.
- `parseHash()` 273: the inverse; **`#sources` → view market with `MKT.src=true`** (old alias already exists —
  extend this pattern for v3 redirects). Falls back to `makro` for any unknown path. Coerces `MK.ind` into
  `curInds()` and `MK.year` into `yearsFor()`. Sets `LF.pendingFit` when a municipality is first shown.
- `go(hash)` 316 sets `location.hash` (or re-renders if identical); `syncHash()` 317 = `replaceState`
  (no history entry, used by in-view controls); `hashchange` listener 318 → `parseHash(); render()`.
- Boot: last two lines of the file `parseHash(); render();` (4256–4257).

### 1.5 Render pipeline
- `VIEWS` 321 (id, label, blurb, hash) and `NAV_GROUPS` 329 → `renderNav()` 332 (sidebar; `on` mapping
  folds area→makro, project→pipeline, sheets→makro). `crumbs()` 339 → `renderTop()` 358 (breadcrumb).
- `RENDER` 362 maps `S.view` → `vXxx()`; `render()` 365 = nav + top + `body.innerHTML = vX()` + `enableSort`.
  `renderKeep()` 371 preserves `#main.scrollTop`. Views return HTML strings; maps are created **after** via
  `setTimeout(xxInit, 0)` inside the view function.
- Events: one delegated `click` handler 373–454 keyed on `data-*` attributes (`data-go`, `data-indq`,
  `data-arind`, `data-infra`, `data-public`, `data-services`, `data-climate`, `data-hz`, `data-fs`, …), one
  `change` handler 455–477 keyed on element ids (`indsel`, `yearsel`, `areaq`, `chind`, `cmpa/cmpb`, …),
  `paste`/`input`/`keydown` 479–504 (Enter in `#tpq`/`#areaq`/`#chq`; `c`/`d` map jumps; Esc = back on area).
  Leaflet popups swallow clicks, so popup links are re-wired in `map.on("popupopen")` (2366, 1810).

### 1.6 Views — where each is rendered
| View | Function | Line | Map init | Notes |
|---|---|---|---|---|
| Macro map | `vMakro` | 847 | `lfInit` 2336 → `lfLayers` 2254 | toolbar `mkTools` 834 (`mkRefreshTools` 838 re-renders toolbar in place); `indQuick` chips; `indExplain` 653; `muniStrip` 738; legends `setLegend` 608 (calls all four overlay legends) |
| Table | `vTable` 909, `tableRows` 875, `tableCols` 881, `tableBodyHtml` 886, `renderTableBody` 903 | 909 | – | level segs `data-tlevel`; export `exportCsv` 932 |
| Area page | `vArea` 1195, `areaEntity` 970, `headlineHtml` 1034, `tileHtml` 1023, `outlookCard` 1109, `areaChart` 1141, `areaCompareTable` 1154, `areaSubTable` 1167, `bbrCard` 1185, `kkCard` 1243 | 1195 | `arMapInit` 1266 (`arMapMode` 1256) | HL_KEYS 215 = headline tiles; `eVal`/`inherits` 991–992 = ° municipality fallback |
| Charts | `vCharts` 2561, `chartSeries` 2454, `chartSvg*` 2481–2560 | 2561 | – | `chartPng` 2611, `chartCsv` 2618; `chEntity` 2404 resolves "kommune:101" ids |
| Market | `vMarket` 4200, `lineChart` 4185, `spark` 4178 | 4200 | – | Sources fold `vSources` 4225 |
| Pipeline | `vPipeline` 4050, `pipeRows` 4044 | 4050 | – | `exportPipelineCsv` 4072 |
| Project sheet | `vProject` 3974 | 3974 | `prMapInit` 4018 (`LF.pmap`) | |
| Analysis (test property) | `vAnalysis` 2066, `anHead` 1768, `anLayerBar` 1791, `anIndTable` 1752, `anOutlookCard` 1684, `anInfraCard` 1939, `anPubCard` 1964, `anSchCard` 2002, `anClimCard` 3710, `anSources` 2024, `anFill` 2048 (async re-fill of pub/sch/clim cards) | 2066 | `anMapInit` 1901 → `anMapOverlays` 1822 | pin parsing `tpParse` 1589/`tpGo` 1571/`tpDrop` 1577 (uses `parseLocation` from testprop.js); `locate` 1535, `tpEntity` 1551 |
| Compare | `vCompare` 3571, `cmpRow` 3528, `cmpZoneRow` 3554 | 3571 | – | |
| Climate sheet | `vClimate` 3629, `climHzCells` 3612 | 3629 | – | |
| Public sheet/list | `vPublic` 4085 / `vPubList` 4145 | | `pbMapInit` 4128 (`LF.pmap`) | |
| School sheet/list | `vSchool` 3818 / `vSchoolList` 3898, `schoolsChartCard` 3955 | | – | |

### 1.7 Indicators, selectors, values
- Registry fields (from makro.json): `key,label,short,unit,level(kommune|postnr|kvarter),fmt,group,direction,
  desc,source,warn,note,asof{level:period},hist_asof,tables[],src_verify[],src_page[pub,url],climate_src,
  proj{from,to,publisher,vintage,table,src,caveat},chip,chip_label,map_from,history_from,q_periods,table_only`.
- `GROUP_ORDER` 616 fixes optgroup order (12 groups incl. "Climate"). `indSelect()` 622 = grouped
  `<select id="indsel">`; `indQuick()` 628 = chips from `QUICK_KEYS` 219 (6 fixed + every `chip:true`).
  `curInds()` 233 = the list for the current context (IND vs IND_Q), `curInd()` 234, `curPool()` 231.
- Value access is **always** `V(o, key, year)` 225 → climate keys go to `climValue` 3264, others to
  `o[key]` (latest) or `o.hist[key][year]`. `yearsFor()` 232, `histYears` 230. Formatting `FMT` 33
  (`kdkk: v => nf(v/1000,0)+" kDKK"` at line 35 — see §3.2), `fmtOf`, `fmtTight`.
- Colour: `scaleOf` 573 (quintiles), `mkShade` 542, `divergingScale` 561, `legendHtml` 588.
- Source links: `srcUrl/srcLink` 80–95 (StatBank per-area CSV query), `pickSrc`/`indSrcLink` 104–125
  (StatBank → `src_page` → climate `climSrcLink` 3440), `srcLine` 676 (publisher, tables, as-of, fetched).

### 1.8 Maps — every `L.map` call
| Line | Var | View | Options of note |
|---|---|---|---|
| 2340 | `LF.map` | macro | panes `srvpane` z450, `pubpane` z440, `climpane` z430 (pointer-events none); renderers `LF.canvas/srvCanvas/pubCanvas/climCanvas`; tiles OSM; `moveend`/`zoomend` handlers redraw overlays |
| 1270 | `LF.amap` | area page | no custom panes |
| 1907 | `LF.anmap` | analysis | **`dragging:false`** (the bug), no custom panes, own `LF.anCanvas` |
| 4022 | `LF.pmap` | project sheet | |
| 4131 | `LF.pmap` | public-building sheet | |
Each init only removes *its own previous* map (`LF.x.remove()`), never the others → §2.4.
Overlay layer builders (macro map): `lfInfraLayers` 1373 + `lfInfraLabels` 1428, `lfPublicLayers` 2790 +
`lfPublicLabels` 2843 + `pubMarkers` 2821 (shared with analysis), `lfServicesLayers` 3113,
`lfClimateLayers` 3361, `lfMicroLayers` 2231, `lfLabels` 2105, `tpLayers` 1597. `lfDrop(...keys)` 2317
removes layer groups from `LF.map` only. Canvas prototype guard 2308–2313 (only `_redraw`/`_update`).
Full screen: `toggleFullscreen` 2390 (`#mapcard`). Jumps `MAP_JUMPS` 2327.

### 1.9 Climate: overlay vs indicator (the thing to unify)
- **Overlay** = `MK.clim` (hash `climate=1`), toolbar button `data-climate` (411), `lfClimateLayers` 3361
  draws `CRA` risk areas + `CZ` surge zones into `climpane`; legend `climLegendHtml` 3393 carries the
  layer toggles (`data-climlay`, `CF.show`) **and** a horizon pill (`data-hz`). Zones need zoom ≥ `CLIM_ZOOM` 10.
- **Indicator** = any `IND` with `group:"Climate"` (`CLIM_KEYS` 3218, `isClim`). `V()` routes to
  `climValue` 3264 (reads `CLIM.kommune[kom][key][hz]` or the per-horizon exposure tables for `surge_dw_pct`).
  `yearSelect()` 684 already returns `hzPill("tools")` when a Climate indicator is selected — so "horizon
  replaces the year selector" exists. `climSetHz` 3247 drops zones and re-renders.
- Unify plan: delete `MK.clim` toggle & button; make `lfClimateLayers` draw when `isClim(curInd().key)`
  (treat `climOn()` 3228 as `isClim(MK.ind)`), keep `hz=` in hash, keep `clim=` filter, drop `climate=1`
  from `hashFor` but **still accept it in `parseHash`** (map it to `MK.ind = "surge_dw_pct"` if `ind` is
  not a climate key). Analysis (`ANL.climate`), Compare and the climate sheet are independent and stay.

### 1.10 Exports and the portfolio hook
- `exportCsv` 932 (table, wide), `exportAll` 946 (sidebar "⤓ Export data": long format, columns
  `level;code;name;parent;region;population;year;indicator;label;unit;value;as_of`; municipalities, postal
  codes, quarters, then **project rows jammed into the same columns** (961), then macro series (964)),
  `exportPipelineCsv` 4072, `exportMicroCsv` 2224, `chartCsv` 2618, `chartPng` 2611, `downloadCsv` 942.
- `D.portfolio` (line 12 schema; toolbar button 836 `data-mkown`; markers 2291–2299): a static
  `data/processed/portfolio.json` of own properties. Not present in the repo → button hidden. v3 Properties
  should treat it as an optional *seed* (import its `lat/lon/name` as pins), not as the store.

### 1.11 Other files
- `src/climate_core.js` (5 KB, IIFE → `window.CLIMATE_CORE`, also `module.exports`): `CLIM_HZ,
  CLIM_ZONE_YEAR, CLIM_FIG, CLIM_LAY, hzShort, hzLabel, hzParse, hzSerialise, climFilterParse/Serialise,
  pipLL, gjHit`. Pattern to copy for any new pure logic (export builders, URL alias table, portfolio codec).
- `src/testprop.js` (4 KB): `parseLocation(text)` + `TP_BOUNDS/TP_FORMATS/TP_SHORT_MSG`.
- `src/style.css` (1 699 lines, 114 KB): sections are Finnish-commented legacy (lines 76–1110, many unused
  by the DK app) then `/* ---- Denmark edition additions ---- */` 1157 onward: v1.3 area pages 1189,
  v1.3.1 responsive scaling 1244 (`--sidew`, `#lfmap` height clamp, breakpoints 1500/1400/1180/820),
  v1.9 breadcrumb/legend 1330, infra 1427, outlook 1506, services 1530, schools 1562, test property 1572,
  analysis 1604, climate legend 1672, compare 1693. Mobile rule: `@media (max-width:900px)` line 455
  (app grid → 1 column, aside stacks on top — the aside keeps its full nav height, which is the "sidebar
  covers the screen" issue; every route also has horizontal overflow at 390 px, see §2.3).

---

## 2. Verification harness

### 2.1 What exists (v2.6)
| Check | Command | Time | Covers |
|---|---|---|---|
| Python unit | `python3 -m unittest discover -s tests -p 'test_*.py'` | 0.1 s | build_makro calcs (test_safety: 11 tests, rolling 4Q), climate build (test_climate: 31 incl. 11 skipped without raw pulls) |
| JS unit | `node --test tests/*.test.js` | 0.3 s | `climate_core` (gjHit, hz round-trip, labels) 17 tests; `testprop` parseLocation 15 tests |
| Both | `make test` | <1 s | |
| Syntax gate | inside `python3 scripts/build_dashboard.py` | 0.7 s | `node --check` on the three JS files |
| **UI check** | `make ui-check` = `python3 scripts/ui_check.py` | ~30–60 s | headless Chrome (not Playwright): loads `tests/ui_check.html` which iframes dist/index.html and `eval`s the app's own globals. 8 groups / ~30 asserts, **climate-centric**: overlay legend text, hz pill ↔ hash ↔ values, Frederiksberg null, climpane pointer-events, polygon click popup + climate block, `#climate/0167` sheet, analysis climate section + zone fetches, compare climate rows, legend folding. Blocks all external hosts (`--host-resolver-rules`). Needs a Chrome/Chromium binary on PATH or in /Applications. |
| Fixture render | `make fixture` | s | synthetic data build (never ship) |
| Not for the night | `make validate`, `make links`, `make fetch`, `make refresh`, `make validate-forecast` | minutes–hours | **all hit the network** |

**Caveat found:** under Python 3.11 `tests/test_safety.py` fails to import because `scripts/build_makro.py:851`
uses a backslash inside an f-string (Python ≥ 3.12 only). GitHub Actions uses 3.12. `make build` calls
build_makro.py **without** `|| true`, so on a Mac with python3 < 3.12 `make build` fails; use
`python3 scripts/build_dashboard.py` directly (it only reads the committed `data/processed/*.json`). Check
`python3 --version` in the pre-flight (§6).

### 2.2 Proposed Playwright smoke test — `ui_smoke_v3.py` (draft written to this scratchpad)
- Visits 28 routes (every view incl. old aliases, overlays, climate indicator, micro mode, pin, three area
  types, both chart modes, project/public/school sheets, compare, climate sheet) at **1440×900, 1366×768,
  390×844**; boots once per viewport then drives by `location.hash` exactly as `tests/ui_check.html` does.
- Fails on any `pageerror` or `console.error` (tile/font network noise whitelisted), on missing/empty DOM
  landmarks (`#lfmap .leaflet-pane`, `#maplegend!`, `.arhead h2!`, `#anmap`, `table tbody tr`, `svg`…), on a
  false app-state expression (`S.view==='area' && !!LF.amap`), and on horizontal overflow at phone width.
- Saves `shots/<phase>/<route>_<viewport>.png` (+ `_full` with `--full-page`) and `report.json`.
- `--only`, `--viewports`, `--allow-errors` (diagnostic mode), `--no-network` (deterministic: aborts every
  request not to the local server), `--phase P3` (folder name). Extend per phase by appending to `ROUTES`
  (new v3 hashes) while **keeping the old hashes** — they double as the redirect test.
- Runtime measured here: **57 s per viewport** (≈3 min for all three); 84 route×viewport checks.
- Intended repo home: `tests/ui_smoke.py` + Makefile target `smoke: python3 tests/ui_smoke.py --no-network`.
  Serve dist with `python3 -m http.server 8080 -d dist` (the script does not start a server — the runner does).

### 2.3 Baseline results on v2.6 (diagnostic run, `--allow-errors --no-network`)
- 1440×900 and 1366×768: **27/28 pass**; only `analysis` fails (2–3 JS errors, `#anlegend` empty).
- 390×844: every route reports horizontal overflow (root: `@media (max-width:900px)` keeps the 268/212 px
  sidebar grid columns semantics but content cards are wider than 390 px; `.card{overflow-x:auto}` masks it
  per card while `#main` still scrolls). The mobile screenshot shows only the sidebar in the first screen.
- Screenshots: `scratchpad/shots/diag3/` (85 files).

### 2.4 Root causes of the headless page errors (all reproduced, stack-traced against dist/index.html)
1. **`Cannot read properties of undefined (reading 'appendChild')`** — `Renderer.onAdd → this.getPane().appendChild`.
   `pubMarkers()` 2834 creates circle markers with `renderer: LF.pubCanvas, pane: "pubpane"`. Those exist only
   on the macro map (`lfInit` 2347–2351). `anMapOverlays()` 1872 reuses `pubMarkers` on the analysis
   mini-map (`LF.anmap`), which has no `pubpane`, so the renderer's `getPane()` is `undefined`. Verified in
   the browser: `LF.pubCanvas._map === LF.anmap`, `LF.anmap.getPane('pubpane') === undefined`,
   `LF.pubCanvas._bounds === undefined`. Because `anMapOverlays` throws, `setLegend("anlegend", …)` at the
   end of `anMapInit` 1936 never runs → the empty `#anlegend` landmark. Also happens on a **cold load** of an
   analysis URL when `LF.pubCanvas` is undefined? No — then `renderer: undefined` falls back to the map's
   default renderer and it works; the error needs a prior visit to the macro map (normal usage).
2. **`… (reading 'intersects')`** and **`… (reading 'lat')`** — same failed renderer: `_redraw → _draw →
   _updatePath → _updateCircle → _empty → this._renderer._bounds.intersects` (bounds never set because
   `onAdd` threw before `_update`), and `_onZoom → _updateTransform → project(this._center=undefined)`.
   Fixing (1) removes both.
3. **`… (reading '_leaflet_pos')`** — `Map._onZoomTransitionEnd → _move → _getMapPanePos(this._mapPane)`
   on a map whose `remove()` already deleted `_mapPane`: a zoom animation (`fitBounds`/`setView`) was still in
   flight when the map was torn down. Reproduced by switching routes every 40–60 ms (analysis → area → map →
   analysis). Real-world trigger: `vAnalysis` schedules `setTimeout(anMapInit,0)` from both the `hashchange`
   render and the `komLoad().then(renderKeep)` re-render (parseHash 294), i.e. two inits within ~100 ms.
   Fix: (a) prototype guard like the Canvas one: `L.Map.prototype._onZoomTransitionEnd` and `_move` return
   early when `!this._mapPane`; (b) a single `dropMap(key)` helper that does `map.off(); map.stop();
   map.remove()` and nulls the key, called for **every** `LF.*map` at the top of `render()` (today the
   macro/area/analysis/project maps are only removed when the same view re-inits, so a map whose DOM is gone
   lives on and still receives async callbacks: `pubLoad` 2650, `srvLoad`, `climLoad` 3309, `loadMicro` 2196
   all do `if (MK.pub && LF.map) lfPublicLayers(true)` / `anMapOverlays()`); (c) debounce the `setTimeout(xInit,0)`
   calls via one `LF.initTimer` (clearTimeout before scheduling) and re-check `S.view` inside each init.
4. **Analysis mini-map cannot be dragged** — `dragging: false` at line 1907, by design in v2.4 ("a drag
   would lose the rings"). v3: `dragging: true`, keep the reader's zoom/center in `LF.anZoom/LF.anCenter`
   (there is already a "keep zoom on re-render" branch at 1933–1935), add a "⌖ re-centre" control, and a
   `⤢ full screen` reusing `toggleFullscreen` generalised to take a card id.
- Recommended v3 structure for (1): give each map its own pane+renderer set via a helper
  `mapPanes(map) → {pub, srv, clim}` stored on the map object (`map._am = {...}`), and have `pubMarkers(rows,
  map, gm)` read `map._am.pub` instead of `LF.pubCanvas`. Same for `lfClimateLayers` if it is ever reused.

---

## 3. Data / export facts for the export redesign

### 3.1 Where source metadata lives
- **`config/indicators.json`** (63 national + `cph` block of 31 + `macro` series). Per indicator: `sources[]`
  with `{db, table, vars, geo, pull, share, select}`, `calc`, `source` (free text), `desc`, `warn`, `note`.
- **`data/processed/makro.json`** (built by `build_makro.py`): `meta.sources[]` = catalogue rows
  `{key:"dst/FOLK1A", label, tables (description), asof, fetched, url (tableinfo), licence}`; per indicator
  `tables: ["dst/IFOR22"]` (joins to the catalogue), `src_verify[] {db, table, area_var, years, vars,
  publisher_label}` (per-area verify query), `src_page: [publisher, url]` (non-StatBank), `asof{level}`,
  `hist_asof{year:{level}}`, `proj{table, publisher, vintage, src}`, `climate_src` (recipe for the climate
  verify URL). `data/processed/cph.json`: `meta.sources[]` (s30 KK tables), indicators carry only `source`
  text + `asof/hist_asof` — **no `tables`, no `src_verify`** (gap; the KK table id is only in the `source` string
  "Københavns Kommune, KKBOL3").
- Publisher id → name is hard-coded in `srcLine` 678: `{dst: "Danmarks Statistik", s20: "Finans Danmark",
  s30: "Københavns Kommune"}`. Use the same map in the export.

### 3.2 Coverage of table_id / publisher / URL per indicator (national registry, 63)
- **Full (tables + src_verify + catalogue url)**: 27 — growth, income, income_med, young, single, benefit,
  renters, unemp, higher_ed, flats, foreign, price_m2, discount, dom, supply, supply_n, pipeline,
  completions_n, almene, avg_m2, and the 7 Safety keys (crime_1000 … clearance_pct). `hist_net_dwell` has
  src_verify but `tables:null` (catalogue key is `net_dwellings`).
- **`src_page` only (publisher + one page URL, no table id / per-area query)**: 19 — rent_private,
  rent_social (boligstat.dk / LBF PDF), the 7 `*_bbr` keys (BBR via Datafordeler), projects_upcoming,
  stations_planned_1200m (curated layer, docs/INFRA.md), public_m2_per_1000, public_recent_cases_n,
  the 4 school keys (Uddannelsesstatistik.dk cubes).
- **`proj.table/src`** (DST FRKM126 / KK KKFR2026): 10 Outlook keys — table id and vintage available via
  `i.proj`, no `tables`.
- **`climate_src`**: 8 Climate keys — publisher and dataset in `source` text + verify recipe; no StatBank id.
- Copenhagen quarter registry (31): table id only inside the `source` string; parse `/, (KK[A-Z0-9]+)/`
  or better: add `tables` to `build_cph.py` output (data change — **out of scope for the night**; do the
  regex on the UI side and note it).
- **Export columns that can be filled for every row today**: `publisher` (from `tables[0]` prefix, `proj`,
  `src_page[0]`, climate → "Kystdirektoratet/DMI/F&P/Miljøstyrelsen" per `climate_src`, KK for quarters),
  `source` (free text — always present), `as_of` (always), `period_type` (derive: `q_periods` → quarter,
  `proj` → projection window, `asof` text with `→` → rolling, else year), `source_url` (catalogue `url`, or
  `src_page[1]`, or `proj.src` url, or climate verify URL, or empty for KK quarter indicators → fill with
  `https://api.statbank.dk/v1/s30/tableinfo/<KKTABLE>` from the regex), `table_id` (empty for the 19
  src_page-only keys — say "n/a (register/curated)" rather than blank).

### 3.3 The kDKK / DKK income unit issue
- `income`, `income_med` have `unit: "kDKK / yr"`, `fmt: "kdkk"`, `calc: "value_div_1000"` in config. But
  `build_makro.py:291` maps `"value_div_1000": calc_passthrough` → the stored value is **DKK** (København
  `income_med` = 291 834). The UI formatter `kdkk` (app.js:35) divides by 1 000 on display; `exportAll`
  and `exportCsv` write the raw `V()` value with the `kDKK / yr` unit → **export says kDKK, values are DKK**.
  Same for the Copenhagen quarter `income_med` (KKIND4).
- Fix in the UI export layer (no data change): when `i.fmt === "kdkk"` either write `value/1000` with unit
  kDKK, or (cleaner, lossless) write the raw value and set `unit: "DKK / yr"`. Recommend the latter plus a
  `unit_note` column. Add a node test for the export row builder (pure function in a new `src/export_core.js`).

### 3.4 "Dwellings built 2010+": KK (`new_stock`) vs BBR (`new_stock_bbr`) — likely definitional cause
- **KK `new_stock`** (config `cph` → `KKBOL3_year`, `calc: share_of_total`): numerator `IBRUGKK` codes 13–28
  (= years 2010…2025), denominator `TOT` (which **includes code 99 "Unknown"**), `EJER=SUM, BYGANVEND=SUM,
  ENHED=01` (number of dwellings). KKBOL3 is Københavns Kommune's own tabulation of BBR; `IBRUGKK` = "year
  of commissioning" (*ibrugtagningsår*) of the **dwelling**.
- **BBR `new_stock_bbr`** (`scripts/build_bbr.py:102–119`): per dwelling unit (BBR_Enhed, status 6, boligtype
  1–5), year taken from the **building's** `byg026Opfoerelsesaar` (original construction year); numerator
  `y >= 2010`, denominator = units with a **known** year (1000 < y ≤ 2100). `byg027OmTilbygningsaar`
  (year of major rebuild/extension) is fetched (`fetch_bbr.py:43`) but **not used**. Units are assigned to
  quarters by point-in-polygon of the building coordinate into `cph_kvarterer.geojson`, not by KK's own
  address→quarter key.
- Why KK is *higher*: a dwelling created inside an older building (conversion of brewery/naval/industrial
  buildings, added floors, subdivisions) gets a **2010+ commissioning year in KK's dwelling-level tabulation
  but the building's original `byg026` (often 1900s) in ours**. The four outliers are exactly conversion-led
  redevelopments: Vesterbro syd (Carlsberg Byen), Holmen og Refshaleøen (naval yard), Faste Batteri (2 093
  dwellings in only 46 buildings, 45/bld — large converted/mixed blocks), Nordøstamager. The unknown-year
  denominator difference works in the *opposite* direction (would lower KK), so it cannot explain the gap.
  Geography drift (building point vs KK key) is a secondary contributor.
- What to do in v3 (UI/docs only): label the two clearly ("commissioned 2010+ (KK, dwelling)" vs "in
  buildings built 2010+ (BBR, building year)"), keep both, add a one-line note on the quarter page when the
  gap exceeds 15 pp, and file a data task: use `max(byg026, byg027)` or the unit-level commissioning field in
  build_bbr.py and re-validate against KKBOL3 (needs the raw BBR pull, which is git-ignored and not on this
  machine). **Do not change data overnight.**

### 3.5 Other export audit items (from CONTEXT) and where they come from
- Period formats mixed in `year`: quarters from `q_periods` indicators (`2024K3`), months from macro series
  (`2024M08`), windows from Outlook `proj.from→to`. Add `period_type` + keep `period` verbatim.
- Missing from the export today: services (`SRV`/`SRV_FILES`, per kommune counts in `SRV.kommuner`), public
  buildings (`PUB.areas`), schools (`SCHOOLS` lazy), outlook trajectories (`o.fc` age arrays used by
  `popOutlookChart` 1064), climate zones exposure (`CLIM.zones[hz].postnr/kvarter`), test property. Each
  is a separate file in the new Export menu; the lazy ones must be fetched before export (await).

---

## 4. Risk register

| # | Risk | Where | Mitigation |
|---|---|---|---|
| R1 | **Top-level const collision** between app.js and a new file blanks the page (no error until runtime) | index.html script order | new files as IIFE exposing one `window.X`; smoke `map` route catches it (boot wait times out) |
| R2 | **`node --check` passes but a runtime ReferenceError** in a rarely-hit branch | any refactor | the smoke test's 28 routes + `--no-network`; keep `pageerror` fatal |
| R3 | **Old shared links** break: `#table/kommune`, `#pipeline`, `#market`, `#sources`, `#analysis?a=…`, `#map/101?climate=1`, `#area/...?g=…&t=…`, `#project/…`, `#compare?a=…`, `#climate/0167` | parseHash | add an alias table at the top of `parseHash` mapping old path → new (`table/<lvl>`→`data/areas/<lvl>`, `pipeline`→`data/projects`, `market`→`data/national`, `sources`→`data/sources`, `analysis`→`properties`, `climate=1`→climate indicator) then `history.replaceState` to the canonical hash; keep `S.view` ids **unchanged internally** (`makro`, `table`, `market`, `pipeline`, `analysis`) so RENDER/nav logic keeps working — only the *hash spelling* and nav labels change. Smoke ROUTES keep the old hashes. |
| R4 | **GitHub Pages workflow** `.github/workflows/refresh.yml`: push to main → `python scripts/build_dashboard.py` (3.12) → deploy `dist/` | must not be touched | never push overnight; do not rename/move `scripts/build_dashboard.py`, `src/index.html`, `data/processed`; any new src file must be wired into build_dashboard.py in the same commit; do not add pip deps to the build path |
| R5 | **Merge with upstream main** later: monthly data refresh commits touch `data/processed/**` and `data/raw/*.meta.json` only | | v3 branch must not edit `data/processed` or `config/indicators.json` → zero conflict surface. CHANGELOG.md/README.md are edited by humans too — put v3 notes in a new top section only. |
| R6 | **Perf/size budget**: dist 5.0 MB (DATA 4.3 MB, app.js 0.36 MB, css 0.11 MB). Portfolio of 20–30 pins × 60 indicators is trivial; but a multi-map area page + full-screen must keep one map per view. | | budget: app.js ≤ 450 KB, style.css ≤ 140 KB, dist ≤ 5.5 MB; smoke route time ≤ 3 s at 1440 (print `ms`) |
| R7 | **Network during the run**: build/tests/smoke need none (fonts + OSM tiles are fetched by the page but fail gracefully; use `--no-network`). `claude -p` itself needs the API. Never run `make validate/links/fetch/refresh` or any `fetch_*.py`. | | overnight.sh exports `AM_NO_NET=1` (informational) and the phase prompts forbid network scripts |
| R8 | **Python version on the Mac** (< 3.12 breaks `make build` and test_safety import) | | pre-flight; use `python3 scripts/build_dashboard.py` + `node --test` + smoke as the gate, `make test` only if 3.12 |
| R9 | **Playwright not installed on the Mac** | | pre-flight installs `playwright` + chromium into a venv; fallback gate = `make ui-check` (needs Chrome.app) |
| R10 | **Unattended agent drifts** (rewrites unrelated code, "fixes" data, edits workflow) | | phase prompts list allowed files; `git diff --stat` checked by overnight.sh against an allow-list; hard-fail the phase if `.github/`, `data/`, `config/`, `scripts/build_*` changed (except build_dashboard.py in P1) |
| R11 | **Zooming must never change selection** (v2.5.1 rule) | area mini-map, properties map | smoke `state` check: after `map.zoomIn()` on the area page, `AR.code` and `MK.muni` unchanged (add in P4) |
| R12 | **Full-screen + `body.innerHTML` re-render** kills the fullscreen element | `toggleFullscreen` | v3 maps that re-render on selector change must update in place (like `mkRefreshTools`) or exit fullscreen first |
| R13 | `dist/public/*.json` is tracked | | do not delete/regenerate dist tracked files; build copies identical files |
| R14 | Screenshot/visual regressions are not asserted (only errors/landmarks) | | keep `_view` screenshots per phase for the morning review; do not attempt pixel diffs overnight |

### Should app.js be split into modules first? — **No, not overnight.**
- Benefit: smaller reads per session, cleaner ownership. Cost/risk: the build inlines fixed placeholders
  (each new file = index.html + build_dashboard.py + `check_js` edit), one shared global scope (R1), 4 257
  lines of cross-references with no import graph, no bundler, and the only safety net is runtime. A
  mechanical concatenation split (`src/app/*.js` joined in order) is *possible* with zero semantic change but
  gives nothing the sessions cannot get from `grep -n "^function"` — the sessions are sequential, so there
  are no merge conflicts to avoid. Do the split as a daytime, human-reviewed refactor after v3.0.
- Do extract **new pure logic** into IIFE files (like climate_core.js): `src/export_core.js` (row builders,
  unit fix, source columns), `src/route_core.js` (alias table + parse/serialise for the new hashes),
  `src/portfolio_core.js` (pin list ⇄ URL codec, stats). These are testable with `node --test` and keep
  app.js growth in check.

---

## 5. Recommended phase order (7 sequential `claude -p` sessions)

Conventions for every phase: work on branch `v3.0-ui` (created in pre-flight from main); start with
`git tag v3-p<N>-start`; end with exactly one commit `v3.0 P<N>: <scope>` (plus `Co-Authored-By` lines);
**self-check** = `python3 scripts/build_dashboard.py && node --test tests/*.test.js && (serve dist) &&
python3 tests/ui_smoke.py --no-network --phase P<N>` — 0 JS errors, all landmarks, 3 viewports;
**rollback rule** = if the self-check fails after the agent's own fix attempts (the wrapper retries the
phase once with the failure log appended), `git reset --hard v3-p<N>-start` and mark the phase FAILED in
`OVERNIGHT_REPORT.md`; P1 failure stops the night (everything depends on it); P2–P7 failures skip to the
next phase only where the dependency table allows.

| Phase | Scope | Files touched | Depends on | Est. |
|---|---|---|---|---|
| **P1 Foundation** | (a) map lifecycle: `dropMap()` helper called from `render()`, per-map panes/renderers (`map._am`), `L.Map` prototype guards for `_onZoomTransitionEnd`/`_move`, init debounce; (b) analysis map `dragging:true` + re-centre; (c) commit the smoke test as `tests/ui_smoke.py` + Makefile `smoke:` target + `tests/README` lines; (d) `src/route_core.js` alias table (old→new hashes, both directions) wired into `parseHash`/`hashFor` **with the new spellings not yet emitted** (flag `ROUTE_V3=false`) so links stay identical this phase. | app.js (maps, render, parseHash), src/route_core.js (new), index.html, build_dashboard.py (`{{ROUTE_JS}}`), tests/ui_smoke.py, tests/route.test.js, Makefile | – | 1–1.5 h |
| **P2 Nav + Data section** | Sidebar: Map · Data · Charts · Properties · Compare. `Data` = old `table` view with tabs Areas (kommune/postnr/kvarter) · Projects (old pipeline table + filters) · National series (old market tiles/table/charts) · Sources (old vSources). Flip `ROUTE_V3=true`: emit `data/areas/<lvl>`, `data/projects`, `data/national`, `data/sources`; old hashes redirect. Charts: allow national `D.macro.series` keys in `chEntity`/`chartSeries` as a "Denmark series" source. Remove Market and Pipeline nav items. | app.js (VIEWS, NAV_GROUPS, renderNav, crumbs, vTable→vData shell, vPipeline/vMarket/vSources become tab bodies, vCharts), route_core.js, style.css (tabs) | P1 | 1.5–2 h |
| **P3 Export redesign** | `src/export_core.js` (pure): row builders for Areas (long, with `publisher, table_id, source, source_url, as_of, period, period_type, unit` and the kDKK fix), Projects (own file), National series (own file), Sources catalogue, Climate exposure, current view (wide). One Export ▾ menu in Data + keep sidebar button → opens the same menu. Remove project rows from the long CSV. Node tests for each builder (units, column count, no `;` in cells, every row has publisher + source). | src/export_core.js (new), app.js (export* functions → thin wrappers, menu UI), index.html, build_dashboard.py, tests/export.test.js, style.css | P2 (menu location) — can run after P1 if P2 failed, placing the menu on the old Table view | 1–1.5 h |
| **P4 Area page** | header + headline tiles (postal-code inherited values visibly dimmed + "municipality figure") → grouped indicator `<select>` + chips (reuse `indSelect`/`indQuick` with `curInds()`) → `grid: chart 60% / mini-map 40%` same height, draggable, ⤢ full screen (generalise `toggleFullscreen(cardId)`), map colours by the selected indicator (`arMapInit` already does) → toggles: Population outlook · All figures (areaCompareTable) · Quarters & postal codes (areaSubTable) · Housing stock (BBR). Remove the 11-group × tiles block. Update in place on selector change (no full re-render inside fullscreen). | app.js (vArea, arMapInit, tile/headline helpers, click handlers `data-arind/data-artab`), style.css | P1 | 1.5–2 h |
| **P5 Climate as an indicator + toolbar** | Remove the Climate-risk overlay button/`MK.clim`; zones + risk areas draw automatically when `isClim(curInd().key)` (`climOn() := isClim(MK.ind)`), horizon pill already replaces the year selector; legend keeps layer toggles. `climate=1` in old links → select `surge_dw_pct`. Toolbar: group Infra / Public / Services under one `Layers ▾` popover (keep the same `data-*` handlers), Quarters/Postal segs stay, jumps stay; target ≤ 1 row of controls at 1366. | app.js (mkTools, lfClimateLayers, climOn, parseHash, legends), style.css | P1 (P2 nav not required) | 1–1.5 h |
| **P6 Properties (portfolio)** | `analysis` → Properties: several pins (`a=` becomes a list `a=lat,lon;lat,lon`, labels `la=` list; codec in `src/portfolio_core.js`, cap 30 with a visible note), numbered pins on a draggable map, headline tiles for the *selected* property, indicator dropdown driving the mini-map colour + highlighted row, portfolio table (row per property × chosen indicators, portfolio median/min/max — no weights), Export portfolio (uses export_core with source columns), `D.portfolio` seeds pins if present. Keep every existing card (infra/public/schools/climate) for the selected property. | app.js (vAnalysis family, anMapInit/anMapOverlays, hash), src/portfolio_core.js (new), tests/portfolio.test.js, index.html, build_dashboard.py, style.css | P1, P3 (export), P4 (selector pattern) | 2 h |
| **P7 Responsive + polish + docs** | 390 px: collapsible sidebar (hamburger, `aside` off-canvas), no horizontal overflow (smoke rule becomes fatal at 390), 1366×768: controls ≤ 120 px above the map. Rank denominators consistent, outlook tiles show persons prominently, sources table "Fetched" fallback, public-building list grouped. CHANGELOG v3.0 section, README nav/URL section, docs/UI_V3.md (routes table incl. redirects), version strings. Final full smoke with `--full-page`. | style.css, app.js (small), CHANGELOG.md, README.md, docs/UI_V3.md | all | 1–1.5 h |

Total ≈ 9–12 h wall-clock at the outside; realistic overnight window 8 h → if behind schedule, overnight.sh
skips P7 polish items but still runs the docs part (P7 prompt has a `MINIMAL=1` mode).

Phase prompt file skeleton (one per phase, `phases/P<N>.md`): 1) read `ENG_BRIEF_v3.md` §1 + §2 + this
phase's row; 2) scope + explicit **allowed files**; 3) acceptance list; 4) the exact self-check commands;
5) "commit with message `v3.0 P<N>: …`; never push; never touch .github/, data/, config/; never run
fetch/validate; if the self-check cannot be made green, write `phases/P<N>.FAILED.md` with what you tried
and stop."

---

## 6. Environment prerequisites on the owner's Mac + overnight.sh

### 6.1 Pre-flight (run by the human before bed; also encoded in `overnight.sh preflight`)
```bash
cd ~/path/to/am-dashboard-dk
git status --porcelain            # must be empty
git checkout -b v3.0-ui main
python3 --version                 # 3.12+ preferred (3.11 breaks `make build` and test_safety import; build_dashboard.py itself is fine)
node --version                    # 18+ (22 here); `node --test` needs ≥18, `--check` any
claude --version                  # 2.1.x; `claude -p` must be logged in (run `claude` once interactively)
python3 -m venv .venv-ui && . .venv-ui/bin/activate
pip install playwright && python3 -m playwright install chromium     # ~150 MB, once; needs network NOW, not later
python3 -c "from playwright.sync_api import sync_playwright; print('playwright ok')"
python3 scripts/build_dashboard.py && node --test tests/*.test.js
(cd dist && python3 -m http.server 8080 >/dev/null 2>&1 &) ; sleep 1
python3 tests/ui_smoke.py --no-network --phase baseline --allow-errors    # or scratchpad/ui_smoke_v3.py before P1 commits it
caffeinate -V >/dev/null 2>&1 || echo "no caffeinate?"   # ships with macOS
```
Fallback if Playwright cannot be installed: `make ui-check` works with `/Applications/Google Chrome.app` and
covers the climate paths only; the phase prompts then say "smoke unavailable — run `make ui-check` and the
node tests" (weaker gate; flag it in the report).

Python packages used by build/tests: **stdlib only** (shapely optional for kommune-ring simplification — the
build prints a note and ships unsimplified rings, 924 kB instead of ~300 kB; acceptable). Playwright is the
only extra, in a venv. No pip installs during the night.

### 6.2 Claude Code CLI flags (verified against `claude --help`, v2.1.281)
Exist: `-p/--print`, `--permission-mode <acceptEdits|auto|bypassPermissions|manual|dontAsk|plan>`,
`--dangerously-skip-permissions`, `--allowedTools`, `--disallowedTools`, `--output-format <text|json|stream-json>`,
`--model`, `--fallback-model`, `--max-budget-usd` ("only works with --print"; whether it applies to
subscription auth is **unverified**), `--append-system-prompt`, `--add-dir`, `--no-session-persistence`,
`--effort <low|medium|high|xhigh|max>`, `--verbose`. **Not found in this version's help: `--max-turns`** —
do not rely on it; bound each phase with a shell `timeout` instead. Prompt text is passed as the positional
argument or on stdin (`claude -p < phases/P1.md` works; the positional form is used below for clarity).

### 6.3 `overnight.sh` skeleton (also written to the scratchpad next to this brief)
See `overnight.sh`. Behaviour: `caffeinate -dimsu` wraps the whole run; serves `dist/` once on :8080;
for each phase: tag, run `claude -p` with the phase prompt (+ brief path) under `timeout`, capture
stream to `logs/P<N>.log`, then run the gate script itself (never trust the agent's word), verify exactly
one new commit and that the diff touches only allowed paths; on failure retry once with the gate output
appended to the prompt; on second failure `git reset --hard` to the tag and either stop (P1) or continue;
appends a row to `OVERNIGHT_REPORT.md` with timings, commit hash, gate result, screenshot folder; never
pushes; leaves the http server running for the morning review.

Morning review checklist (top of OVERNIGHT_REPORT.md): open `shots/P7/*_1440x900.png` side by side with
`scratchpad/v26/*.png`; open http://localhost:8080/#table/kommune and #pipeline and #analysis?a=… to see the
redirects; `git log --oneline main..v3.0-ui`; decide per phase; then `git push -u origin v3.0-ui` and open
a PR (Pages deploys only from main).
