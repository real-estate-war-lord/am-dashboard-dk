# UI v3.0 — routes, components, exports, tests

What the interface is, in the terms the code uses. Written at the end of the v3.0 overhaul (P9).
The *why* of each decision is in [`docs/v3/UI_SPEC_v3.md`](v3/UI_SPEC_v3.md) (the specification, with the
owner amendments at the top) and [`docs/v3/DECISIONS.md`](v3/DECISIONS.md) (every choice taken while
building it). What each phase shipped is in [`docs/v3/PROGRESS.md`](v3/PROGRESS.md).

The app is one page: `src/index.html` + `src/app.js` + four pure helper modules, built into
`dist/index.html` by `scripts/build_dashboard.py`. There is no framework and no bundler.

---

## 1. Navigation

Four destinations in two groups. Market, Pipeline, Compare and the Analysis sheet are gone as
destinations — their content did not go anywhere, only their entry did.

```
MACRO DASHBOARD
 MARKET INTELLIGENCE
  Map            #map[/<kommune>[/postnr]]
  Data           #data/areas/<level> · #data/projects · #data/national · #data/sources
  Charts         #charts?…
 ANALYSIS
  Test property  #property?p=<lat>,<lon>[:label]
 ── footer ──
  Export ▾   ·  built <date> · v3.0
```

At ≤ 1024 px the sidebar becomes a 52 px top bar with a `☰` drawer (same `<aside>` element, no second
copy of the nav). Esc closes it, focus is trapped while it is open and handed back to `☰`.

## 2. Routes

`src/route_core.js` is the only place a hash spelling is decided: `toV3()` turns any old spelling into
the canonical v3 one (and is idempotent, so it can run on every `hashchange`), `toInternal()` turns
either spelling into the internal view id. `hashFor()` in `app.js` is the only serialiser and
`parseHash()` the only parser; `parseHash()` ends with a canonical `replaceState`, so the address bar
always shows exactly what the app would write.

### 2.1 Canonical routes

| Hash | View |
|---|---|
| `#map` · `#map/<kommune>` · `#map/<kommune>/postnr` | the choropleth, drilled or not |
| `#area/kommune/<code>` · `#area/postnr/<nr>` · `#area/kvarter/<code>` | one area |
| `#data/areas/<kommune\|postnr\|kvarter>` | Data › Areas (the old Table) |
| `#data/projects` | Data › Projects (the old Pipeline) |
| `#data/national` | Data › National series (the old Market) |
| `#data/sources` | Data › Sources (the old sources accordion) |
| `#charts?ind=…&a=<type>:<code>,…` | the chart generator |
| `#property?p=<lat>,<lon>[:label]` | Test property (one pin) |
| `#project/<id>` | project sheet |
| `#public/<kommune>/<id>` · `#publist/<filter>` | public-building sheet and list |
| `#school/<nr>` · `#schoollist/<filter>` | school sheet and list |
| `#climate/<kommune>` | climate deep-dive sheet |

### 2.2 Redirects — every v2.6 link still works

Each one is a route in `tests/ui_smoke.py` with a `redirect=` field, checked at every viewport on
every run. **Never remove an old hash from that list: it is the redirect test.**

| Old link | Lands on |
|---|---|
| `#table/<level>` | `#data/areas/<level>` |
| `#pipeline[?ptype=&pstatus=]` | `#data/projects[?…]` (filters kept) |
| `#market` | `#data/national` |
| `#market?src=1` · `#sources` | `#data/sources` |
| `#data` · `#data/areas` | `#data/areas/kommune` |
| `#analysis?a=<lat>,<lon>&la=<label>` | `#property?p=<lat>,<lon>:<label>` |
| `#analysis` (no pin) | `#property` (empty state) |
| `#compare?a=<type>:<code>&b=…` | `#area/<type>/<code>` of the **a** side (`#map` if unparsable) |
| `#map?…&infra=1&public=1&services=1` | `#map?…&lay=infra,public,services` |
| `#map?…&climate=1` | `#map?…&ind=surge_dw_pct` (an explicit climate indicator in the link wins) |
| `#area/…?t=bbr\|ind` · `?t=sub` | `?show=figures` · `?show=sub` (`g=` is dropped) |

### 2.3 Query keys

| Key | Meaning | Where |
|---|---|---|
| `ind` | active indicator key | map, area, data/areas, charts, property, sheets |
| `y` | year, only when it is not the latest | indicators with a year series |
| `hz` | `today \| 2070 \| 2120` | Climate indicators, climate sheet |
| `lay` | comma list of feature layers | map: `infra,public,services` · property: `infra,public,services,buildings,climate` |
| `zones` | `0` hides the storm-surge context layer | map and test property, while a Climate indicator is active |
| `rings` | `0` hides the radius rings | test property |
| `srv`, `pub`, `pubkind` | the sub-filters of the Services and Public-buildings layers | map and test property, when that layer is on |
| `p` | `lat,lon[:label]` (codec is list-capable; v3.0 renders one) | test property |
| `rad` | radius ring in metres: `500 \| 1000 \| 2000 \| 5000` | test property |
| `show` | comma list of open sections, `none` when all closed | area page (`outlook,figures,sub,info`), test property (`outlook,profile,safety,infra,public,schools,climate,sources`) |
| `q, region, minpop` | Areas table filters | data/areas |
| `ptype, pstatus` | project filters | data/projects |
| `a, y0, y1, med, mode, dist, t` | chart setup | charts |
| `pin, pl` | the pin dropped on the map (`lat,lon` and its label) and its `rad` rings — the map's search box writes them and stays where it is; the pin card's **View test property ›** is the step on to `#property?p=…` | map |
| `micro, mind` | the BBR buildings mode of the drilled map | map |

A key is written only when its value differs from the default, so a shared link stays short.

## 3. Components

One implementation each. A view adopts a control by calling it — there is no second copy anywhere.

| Component | Call | Test id |
|---|---|---|
| IndicatorPicker | `indPicker(target)` | `ind-picker`, `ind-picker-btn`, `ind-picker-pop`, `ind-search`, `[data-group]`, `[data-ind]` |
| Chips row | `indChips(target)` | `ind-chips` |
| PeriodControl (year / horizon / projection / as-of) | `periodControl(target)`, `periodHz(where)` | `period`, `period-year`, `period-hz`, `[data-hz]`, `period-proj` |
| Layers menu (two lists: `MAP_LAYERS`, `TP_LAYERS`) | `layersMenu(kind)` | `layers-btn`, `layers-pop`, `[data-layer]` |
| Export menu | `exportMenu(at)`, `exportGo(kind)` | `export-btn`, `export-menu`, `[data-export]` |
| Study row = chart panel + mini map | `studyRow(entity, opts)` | `study-row`, `chart-panel`, `minimap`, `minimap-full` |
| Chart panel bodies | history · snapshot · outlook · climate | `state-nohistory`, `dist-strip`, `outlook-chart`, `clim-bars` |
| Headline tiles | `headlineHtml(e)` | `tiles`, `tile-<key>` |
| Sheet tiles (no empty slot) | `sheetTiles(items)` | `tiles` |
| State cards | `stateCard(kind, title, note, action)` | `state-empty`, `state-loading`, `state-error` |
| Legend stack | `setLegend(...)`, `lgFitIn(wrap, map, order)` | `legend`, `legend-zones`, `legend-infra`, `legend-public`, `legend-services`, `legend-toggle` |
| Unified search (areas, codes, Maps links, coordinates) | `areaSearch()`, `asrchRows()` | `search`, `search-coord` |
| Pin card (the dropped pin, under the map's info strip) | `mkPinCard()`, `mkPinRefresh()` | `pin-card`, `pin-open` |
| Shell | `renderNav()`, `navDrawer(open)` | `sidebar`, `nav-item`, `nav-toggle`, `nav-drawer`, `topbar-mobile` |

`window.__maps` is the array of live Leaflet instances — the test hook every map AC uses. Every map is
registered in `LF_MAPS`, created inside an `xInit` through `mapInit(fn)`, and dropped by `dropMaps()`
at the top of `render()`.

Number rules go through one path: `fmt()`/`nf()` (da-DK on screen), `rankHtml()` (`#n of N`
everywhere), `DASH` (the publisher has no figure) vs `NC` (not computed at this level),
`projValueHtml()`/`smallBaseTag()` (persons first when the base is under 1 000).

### 3.1 Helper modules (pure, IIFE, one `window.X` each, unit-tested with `node --test`)

| File | Global | Owns | Tests |
|---|---|---|---|
| `src/route_core.js` | `ROUTE_CORE` | hash split/build, the alias table, `toV3`/`toInternal`, the property codec, Google Maps link parsing | `tests/route.test.js` |
| `src/picker_core.js` | `PICKER_CORE` | `GROUP_ORDER`, grouping, search matching, period mode, availability tags | `tests/picker.test.js` |
| `src/climate_core.js` | `CLIMATE_CORE` | horizons, the two calendars, zone/figure labels | `tests/climate.test.js` |
| `src/export_core.js` | `EXPORT_CORE` | every column set, the source columns, the unit fix, `period_type`/`value_type`, the CSV rules | `tests/export.test.js` |
| `src/pin_core.js` | `PIN_CORE` | where a point is (ray casting, bounding boxes, great-circle and feature distances) and what it can be read as (the indicator union, the inheritance rule, the area path, the services filter) | `tests/pin.test.js` |

`src/panels.js` (`window.PANELS`) is **not** a pure module: it is app.js's chart-drawing half — the
four bodies of the chart panel (history line, population outlook, distribution strip, Climate
horizons) — split out so `src/app.js` stays inside its 450 KB budget. It reads app.js's own helpers
through the shared global scope and is covered by the acceptance suite, not by `node --test`.

A new `src/*.js` must be wired into **both** `src/index.html` and `scripts/build_dashboard.py` in the
same commit — the build inlines them into one global scope, so a colliding top-level `const` blanks
the page.

## 4. Export

`Export ▾` sits in the sidebar footer, in the Data header and in the test-property header. One menu is
open at a time (`UI.xOpen`). Every item downloads immediately and a one-line toast says what was
written. `exportGo(kind)` is the single entry point, `exSave(stem, cols, rows, extra)` the single
writer.

| Item | File | Schema |
|---|---|---|
| This view (CSV) | `<view>_<date>.csv` | wide — what is on screen, each column's provenance in its header |
| All area data | `areas_long_<date>.csv` | long (below) — 3 levels × every indicator × every published period |
| Projects | `projects_<date>.csv` | own schema, never mixed into indicator columns |
| National series | `national_series_<date>.csv` | long |
| Sources catalogue | `sources_<date>.csv` | `key, label, publisher, tables, as_of, fetched, url, licence, used_for` |
| Climate exposure | `climate_exposure_<date>.csv` | level × horizon: dwellings, dwellings in zone, share, zone km² |
| Test property | `test_property_<date>.csv` + `test_property_nearby_<date>.csv` | long behind `property_label, lat, lon`; nearby = `kind, name, type, status, distance_m, source, source_url` — `kind` ∈ `infra \| public \| school \| service` (services while that layer is on) |

**Long schema** (areas, national series, test property):

```
level, code, name, parent_code, parent_name, region, population,
indicator, label, unit, period, period_type, value, value_type,
inherited_from, direction, source, table_id, source_url, as_of, fetched, licence
```

- `period_type` ∈ `year | quarter | month | school_year | window | snapshot | horizon | projection`;
  `period` is the publisher's own label (`2024`, `2024K3`, `2026M08`, `2025/2026`, `2025K3→2026K3`,
  `2070`, `2026→2040`).
- `value_type` ∈ `actual | projection | inherited | derived`. `inherited_from` carries the
  municipality code when the figure is the municipality's, read at a finer level.
- **No row has a blank `source`, `table_id`, `as_of` or `fetched`** — the fallback order is
  `tables` → `proj` → `climate_src` → `src_page` → a `KK…` id parsed out of the source string → a DST
  id named in prose → `n/a (register/curated)`.
- The unit label always matches the number: a `kdkk` indicator is stored in DKK, so the file writes the
  raw number and says `DKK / yr`; any other kDKK row with a value ≥ 10 000 is converted.
- CSV: UTF-8 with BOM, `;` separator, `.` decimals, no thousands grouping, one header row, no comments.
  The separator can never occur inside a cell, so nothing is quoted and Danish Excel opens it on a
  double-click.

Data › Sources renders `EXPORT_CORE.sourceRecs()` — literally the rows the sources file writes — so the
table and the file cannot disagree.

## 5. Responsive

| Width | Sidebar | Toolbars | Study row | Tables | Tiles |
|---|---|---|---|---|---|
| ≥ 1440 | 240 px | one row + chips | 60 / 40 | full | 5 |
| 1536×864, 1366×768 | 240 px | one row + chips | 58 / 42 | full | 5 |
| 1025–1250 | 240 px | two rows | 55 / 45 | scroll inside the card | 3 + 2 |
| ≤ 1024 | 52 px top bar + drawer | stacked, chips scroll sideways | stacked | scroll-x, first column pinned | 3 + 2 |
| ≤ 600 | 52 px top bar + drawer | stacked, picker popover full width | stacked | scroll-x, first column pinned | 2 |

No element may make the page scroll sideways at any of those widths — `OVERFLOW_FATAL = True` in
`tests/ui_smoke.py` fails the run and names the offending element.

## 6. Tests

```bash
python3 scripts/build_dashboard.py          # src/ → dist/index.html
node --test tests/*.test.js                 # 131 pure unit tests (route, picker, climate, export, pin, testprop)
make serve                                  # http://localhost:8080

# route × viewport smoke: DOM landmarks, app-state expressions, redirects,
# zero pageerror/console.error, zero horizontal overflow, screenshots
.venv-ui/bin/python3 tests/ui_smoke.py --url http://localhost:8080/ --no-network \
    --viewports 1440x900,1536x864,1366x768,390x844 --out shots [--full-page]

# acceptance suite: one function per AC id from the spec, registered with the phase that shipped it
.venv-ui/bin/python3 tests/ui_ac.py --url http://localhost:8080/ --phase-upto P10 --out logs/ac

./overnight.sh gate P10                     # all of the above + the size budgets, in one command
```

`make smoke` and `make ac` are the short forms. Both runners check the page title first and serve
`dist/` themselves on a free port if something else owns :8080 — they print one line when they do.

Budgets: `src/app.js` ≤ 450 KB, `src/style.css` ≤ 140 KB. New pure logic belongs in a `*_core.js` file.
