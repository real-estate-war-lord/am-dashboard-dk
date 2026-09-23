# Integrating `v2.x-services`

**Branch:** `v2.x-services` · **frozen 2026-09-23** · 3 commits ahead of `main`
**Base:** `main` at `d773ca3` (*release: v2.4 test property pin and Analysis sheet*)
**Not merged, not pushed.** To be integrated together with the climate-risk and
population-forecast branches; the version number is set then, not here.

What the layer is and how it works: [`SERVICES.md`](SERVICES.md). This file is only
about landing it next to two other branches without surprises.

## 1. Commits

| | |
|---|---|
| `a992b5d` | `probe: services layer source feasibility (no dashboard changes)` |
| `b593082` | `feat: services data pipeline (OSM + GTFS)` |
| `5642574` | `feat: Services map overlay (OSM + Rejseplanen)` |

`git diff --stat main...v2.x-services` → **111 files, +2 808 / −9**, of which 100 are
new per-municipality data files that no other branch will touch.

## 2. Every file this branch changes

### New files — zero conflict risk

| file | what |
|---|---|
| `scripts/fetch_services.py` | downloads the OSM extract + GTFS zip (stdlib `urllib`) |
| `scripts/build_services.py` | builds `data/processed/services/` and `SERVICES_COUNTS.md` |
| `scripts/probe_services.py` | the source feasibility probe; not part of the build |
| `requirements-services.txt` | `osmium==4.3.1`, `shapely==2.1.2` — this layer only |
| `docs/SERVICES.md` · `docs/SERVICES_COUNTS.md` · `docs/SERVICES_PROBE.md` · `docs/INTEGRATION_services.md` | |
| `docs/screenshot-services.jpg` | the README image |
| `data/processed/services/*.json` | **100 files** — 99 municipalities + `index.json` |

### Modified files — the ones to read before merging

| file | lines | what changed |
|---|---|---|
| `src/app.js` | **+307 / −9**, 13 hunks | the whole overlay; see §3 |
| `src/style.css` | +29, **1 hunk** | one block appended before `.maplegend .lgsub`, plus a `@media (max-width:900px)` block inside it |
| `scripts/build_dashboard.py` | +11, 3 hunks | see §3 |
| `.gitignore` | +5 | `data/raw/probe/`, `data/raw/services/`, `dist/services/` |
| `README.md` | +6 | one section + screenshot, a docs-table row, two attribution lines, one caveat |
| `CHANGELOG.md` | +23 | a new `## Unreleased — Services overlay` block at the top |

**`src/index.html` is untouched.** The services index rides inside the existing
`{{DATA}}` payload, so there is no template conflict.

## 3. Shared touch points

These are the places another overlay branch will almost certainly also edit. Each is a
**one-line insertion** except where noted — mechanical to resolve, but they *will*
collide if climate or forecast add an overlay the same way.

### `src/app.js`

| # | where | the edit | collision |
|---|---|---|---|
| 1 | `const MK = {…}` (l. 71) | adds `, srv: false` to the end of the object literal | **likely** — any branch adding an overlay flag edits this same line |
| 2 | `hashFor()` (l. ~157) | one line: `if (S.view === "makro" && MK.srv) { q.push("services=1"); q.push(...srvHashParts()); }` | **likely** — same function, adjacent lines |
| 3 | `parseHash()` (l. ~206) | appends `MK.srv = q.services === "1";` to the existing `MK.infra = … MK.pub = …` line, and adds `srvParseFilter(q);` next to `pubParseFilter(q)` | **likely** — same two lines |
| 4 | the global click delegate (l. ~300) | +11 lines: `[data-services]`, `[data-srvcat]`, `[data-srvmode]`, `[data-srvall]` | low — distinct selectors, but the same `if` chain |
| 5 | `setLegend()` (l. 443) | appends `setServicesLegend();` to the one-line body | **likely** — one line, every legend-owning layer appends here |
| 6 | `vMakro()` toolbar (l. 585) | inserts the `${SRV ? …data-services… : ""}` segment into the **single very long `<div class="tools">` template line**, after the Public buildings segment | **high** — it is one line and every overlay adds a button to it |
| 7 | `vMakro()` map markup (l. ~589) | inserts `<div class="maplegend serviceslegend" id="serviceslegend"></div>` into the `.maplegs` column, between the public and infra boxes | **high** — one line, same container |
| 8 | `lfLayers()` (l. ~1866) | one line `lfServicesLayers();` after `lfPublicLayers();` | medium |
| 9 | `lfInit()` (l. ~1888) | +6 lines: creates the `srvpane` pane and `LF.srvCanvas` | medium — see §4 |
| 10 | `lfInit()` `moveend` (l. ~1897) | adds `if (MK.srv) lfServicesLayers();` to the existing handler | medium |
| 11 | `lfInit()` `zoomend` (l. ~1914) | adds `if (MK.srv) lfServicesLayers(true);` after the `MK.pub` line | medium |
| 12 | after `publicLine()` (l. ~2358) | **+258 lines — the whole services module.** Self-contained: `SRV`, `SRV_FILES`, `SRV_CAT`, `SRV_MODE`, `SRV_SUB`, `SRV_TGROUP`, `SF`, `srv*()`, `lfServicesLayers()`, `setServicesLegend()` | **none** — a clean block; take it wholesale |
| 13 | `vSources()` (l. ~3109) | +9 lines: appends the services attribution to the `.cap` line and adds a *Services layer* card | medium — the `.cap` line itself is shared |

**Nothing in the services module reads or writes another layer's state.** The only
shared mutable object is `MK` (one new key, `srv`) and `LF` (new keys `srvG`, `srvStG`,
`srvCanvas`, `srvDrawn`, `srvN`). No existing function's behaviour is changed — every
edit is an addition.

### `scripts/build_dashboard.py`

| # | where | the edit |
|---|---|---|
| 1 | `main()`, after `public_index = load(...)` | `services_index = load(PROC / "services" / "index.json")` |
| 2 | the `data = {…}` payload dict, after the `"public"` key | `"services": services_index,` |
| 3 | after the public-buildings copy block | copies `data/processed/services/*.json` → `dist/services/` |

All three are the same pattern the public-buildings layer already uses, so a climate or
forecast branch adding a per-kommune dataset will collide in **exactly these three
places**. Resolution is always "keep both".

### `src/style.css`

One block inserted immediately before `.maplegend .lgsub{…}`, marked
`/* ---- Services overlay (docs/SERVICES.md) ---- */`. It contains its own
`@media (max-width:900px)` rules, which **also restyle `.maplegend .pubtog`** (making
the public-buildings legend's toggles tappable on a phone) — the one place this branch
changes another layer's appearance. Intentional; call it out if the mobile pass is
revisited.

### `README.md` / `CHANGELOG.md`

Ordinary prose conflicts. The CHANGELOG entry is a whole new top block titled
`## Unreleased — Services overlay`; if the other branches do the same, merge the three
into one release entry and give it its version number then.

## 4. Reserved names

Anything else added during integration must avoid these.

| kind | value | notes |
|---|---|---|
| **Leaflet pane** | **`srvpane`, z-index 450** | between `overlayPane` (400) and `markerPane` (600). **Another overlay adding a pane must not reuse 450** — pick 440 or 460 and decide the stacking deliberately. Required, not cosmetic: a canvas renderer built at map init lands *under* the area polygons and the choropleth fill washes the dots out ([`SERVICES.md`](SERVICES.md) §8) |
| **URL hash keys** | **`services`** (`services=1`) and **`srv`** (`srv=g,f,p,t,rail,bus`) | `srv` values: `g` grocery · `f` food · `p` pharmacy · `t` transport · `rail` · `bus`; `srv=none` is a real state |
| **`MK` key** | `srv` | |
| **`LF` keys** | `srvG`, `srvStG`, `srvCanvas`, `srvDrawn`, `srvN` | |
| **DOM ids** | `serviceslegend` | |
| **data attributes** | `data-services`, `data-srvcat`, `data-srvmode`, `data-srvall` | |
| **CSS classes** | `.serviceslegend`, `.srvcat`, `.srvmodes`, `.srvzoom`, `.srvhint`, `.srv-station` | |
| **globals** | `SRV`, `SRV_FILES`, `SRV_CAT`, `SRV_MODE`, `SRV_SUB`, `SRV_TGROUP`, `SRV_ATTRIB`, `SRV_SHORT`, `SRV_LONG`, `SRV_RAIL_MODES`, `SRV_MAX_MARKERS`, `SRV_MAX_FILES`, `SRV_DEFAULT_CATS`, `SRV_DEFAULT_MODES`, `srvCoarse`, `SF` | |
| **payload key** | `D.services` | written by `build_dashboard.py` |
| **dist path** | `dist/services/<4-digit kommune>.json` | gitignored, copied at build |
| **colours** | grocery `#E8590C` · food `#C2255C` · pharmacy `#5F3DC4` · metro `#1864AB` · s-train `#0B7285` · rail `#343A40` · light-rail `#9C36B5` · bus `#868E96` | chosen to avoid the choropleth green ramp, the infra greys/teal and the four public-building tones. A new layer needs hues outside **all** of those |

## 5. Post-integration smoke test

Six checks, ~5 minutes, on `make build` + `cd dist && python3 -m http.server 8080`.

| # | do this | expect |
|---|---|---|
| 1 | Open `#map/101/postnr?ind=growth`, click **Services** in the toolbar | Layer appears; legend box between Public buildings and Infra; defaults **Groceries + Pharmacy + Rail & metro** on, **Food & drink + Bus** off. Click again → layer and legend gone, no empty white box left behind |
| 2 | With all four categories on, step the zoom 15 → 13 → 12 → 10 → 9 | z15 everything · z13 food and bus gone, hint *"Zoom in to see food & drink, bus stops"* · z12 rail/metro only · z10 rail/metro only, **44 metro stations nationally** · z9 nothing drawn, hint names all four |
| 3 | Zoom to Nørreport, click the metro marker | Popup: **Nørreport St.** · pills *Transport* / *Metro station* · *Also served by: Bus · Rail · S-train* · `Rejseplanen, CC BY 4.0 · data as of <date>` |
| 4 | `#map/751?ind=growth&services=1&srv=g` at zoom 13 over Aarhus | ~137 orange dots (86 supermarkets + 51 convenience), other three categories struck through in the legend, dots fully saturated **over the dark choropleth as well as off it** (the pane check) |
| 5 | Copy the URL with a filter applied, reload it in a new tab | Same categories, same sub-toggles, layer still on. Hash carries `services=1` and `srv=…` |
| 6 | Narrow the window under 900 px | Legend goes full width, category rows ≥ 24 px tall, *Rail & metro* / *Bus* render as pills with a filled on-state, markers still tappable, legend causes no horizontal scroll |

Also worth a glance: the map footer gains a **Services:** line while the layer is on,
and Market › Sources shows the *Services layer* table with both licences.

## 6. Smoke-test result on this branch — 2026-09-23

Run on `v2.x-services`, `make build` → `dist/` on `localhost:8080`, Chrome.
**6 of 6 pass. No console errors.** Measured, not eyeballed — the figures below are
what the page reported.

| # | result |
|---|---|
| 1 | ✅ **Toggle.** On: `MK.srv` true, defaults `grocery + pharmacy + transport/rail`, legend 190 px tall and visible, hash gains `services=1`. Off: `LF.srvG`/`LF.srvStG` both cleared, legend `display:none` at **0 × 0 px**, and **zero** `.maplegend` elements anywhere are visible-but-empty |
| 2 | ✅ **Zoom floors.** z15 **1 164** (food 905 · grocery 114 · pharmacy 11 · bus 121 · metro 9 · s-train 3 · rail 1), no hint · z13 **751**, food and bus absent, *"Zoom in to see food & drink, bus stops"* · z12 **136**, transport only · z10 **183**, transport only, **metro = 44** (the whole national network) · z9 **0**, *"Zoom in to see groceries, food & drink, pharmacy, transport"* |
| 3 | ✅ **Nørreport popup**: *Nørreport St.* · Transport · Metro station · Type Metro station · **Also served by Bus · Rail · S-train** · Municipality København · Position 55.68384, 12.57104 · **Rejseplanen, CC BY 4.0 · data as of 2026-09-23** |
| 4 | ✅ **Aarhus z13, groceries only**: **137** points (`supermarket` 86 + `convenience` 51); Food & drink, Pharmacy and Transport all struck through in the legend. Pane verified live — `srvpane` present at **z-index 450**, the canvas renderer reports `pane: "srvpane"`, so dots render above the choropleth rather than under it |
| 5 | ✅ **Hash round-trip.** `srvSetFilter` wrote `srv=f,t,bus`; reloading that URL in a fresh document restored `MK.srv` true, cats `food + transport`, sub-toggle `bus` on / `rail` off, with the legend rows and chips matching. `srv=none` also round-trips and reopens as *All categories hidden · Show all* |
| 6 | ✅ **414 px.** Legend **278 px** wide, category rows **26 px** tall, chips **90 × 26** and **39 × 26** with `border-radius: 999px` and a filled `--ink` background for the on-state. The legend fits inside its map wrapper (278 ≤ 302 px) and **adds no horizontal scrolling**: `document.scrollWidth` is **772 px with the layer on and 772 px with it off** — identical, so the page's overflow at this width is entirely pre-existing (`.topbar` / `.crumbs`, also on `main`) and not this layer's |

**One thing check 6 could not exercise:** the coarse-pointer marker radii (dots 6.5 px,
stations 9 px instead of 4.5 / 7). Desktop Chrome reports `matchMedia("(pointer:
coarse)")` as `false` even at 414 px, so the branch is present and syntactically
exercised but has not been confirmed on real touch hardware. Worth one pass on a phone
at integration.

Supporting measurements from the same session: worst case **zoom 14 over Nørrebro with
every category on = 3 346 markers, full rebuild 15.6 ms, pan 0.4 ms**; per-kommune
loading stays capped (12 files over Copenhagen, 26 cumulative after also visiting
Aarhus, against 99 available); `make test` (12 Python + 15 JS) and `make build`
(0 ⚠) both pass.

**Fixed during this run:** below Transport's own zoom floor the hint read *"…,
transport, rail & metro stops, bus stops"* — the category and both of its sub-groups,
saying the same thing three times. The sub-group hints are now suppressed while the
category itself is already named.

## 7. Integration checklist

- [ ] Merge `v2.x-services` together with the climate and forecast branches; resolve
      the §3 touch points, keeping every layer's addition
- [ ] Give each overlay a **distinct pane z-index** (services holds 450)
- [ ] Check no two overlays claim the same hash key (services holds `services`, `srv`)
- [ ] Merge the three `## Unreleased` CHANGELOG blocks into one release entry and set
      the version
- [ ] Drop the *"On branch `v2.x-services`, not yet merged"* note from the README
      section and update `SERVICES.md`'s status line
- [ ] `make test` · `make build` · run §5
- [ ] `python3 scripts/fetch_services.py && python3 scripts/build_services.py` if the
      data is older than a month at that point — GTFS is a timetable and goes stale
