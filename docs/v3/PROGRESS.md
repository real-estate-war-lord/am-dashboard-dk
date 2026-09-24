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
