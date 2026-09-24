# Climate risk layer — storm surge, sea level, rainfall, flood risk areas

**Status:** **released in v2.6** · pipeline **and** map overlay · national coverage
**Scope:** published screening data only. No model of our own, at any point (§6).
**Scripts:** `scripts/fetch_klimaatlas.py` · `scripts/fetch_kyst_surge.py` · `scripts/fetch_flood_official.py` · `scripts/fetch_fp_claims.py` → `scripts/build_climate.py` · `scripts/build_kyst_zones.py` · `scripts/build_climate_coast_map.py`
**Output:** `data/processed/climate/` (committed, 32 MB) — `index.json`, `risk_areas.json`, `surge_{today,2070,2120}/<kommune>.json`
**Build log:** [`CLIMATE_BUILD_LOG.md`](CLIMATE_BUILD_LOG.md) · **why these sources:** [`CLIMATE_PROBE.md`](CLIMATE_PROBE.md)
**Verification:** [`verification/climate_v2_6.csv`](verification/climate_v2_6.csv), `scripts/verify_climate.py`, summary in [`DATA_MAP.md §7f`](DATA_MAP.md)
**On the map:** §5

## 0. What it is for

One question, asked of an area rather than a building: **how exposed is it to the sea, and how
much does that change by 2070 and 2120?** The layer answers it the way the authorities answer it —
with the flood extents Kystdirektoratet publishes, the climate figures DMI Klimaatlas publishes,
and the designation the Floods Directive gives — and it stops exactly where they stop.

It is a **screening layer for comparing areas**. It is not a property-level flood assessment, it
carries no depth, and it knows nothing about a dike, a pump, a floor level or a drainage plan.
Every surface in the UI says so.

## 1. Sources

| what | source | licence / attribution | key |
|---|---|---|---|
| Sea level, storm surge, surge frequency | **DMI Klimaatlas v2025a** — `VandstandStormflodKyst_latest` layer 0 (values, 3 162 rows) and layer 1 (34 coastal stretches, geometry) on `https://services9.arcgis.com/qH1Ysxh3VVYXbkQU/arcgis/rest/services` | **"Contains data from the Danish Meteorological Institute"** (`Indeholder data fra DMI`) | none |
| 100-year hourly rainfall, cloudbursts | **DMI Klimaatlas v2025a** — `NedboerKommuner_latest` layer 0 (5 586 rows, per kommune) | as above | none |
| Storm-surge extents 2020 / 2070 / 2120 | **Kystdirektoratet, Kystplanlægger oversvømmelsesfare** — `https://gisportal.mst.dk/server/rest/services/ekstern/Kystplanlaegger_Oversvommelsesfare_2/MapServer`, layers **3 / 12 / 21** (100-year event) | Kystdirektoratet, free public data | none |
| Designated flood risk areas | **Miljøstyrelsen / Kystdirektoratet**, Floods Directive 2024 screening (`plantrin 1`) — `https://gisportal.mst.dk/server/rest/services/ekstern/OD_risikoomraader_2024/MapServer`, group 16, 26 sub-layers | Miljøstyrelsen, free public data | none |
| Weather-damage claims | **Forsikring & Pension**, Datawrapper datasets `TUJ9b` (claims) and `z0zEO` (claims per 1 000 inhabitants), `https://datawrapper.dwcdn.net/<chart>/<version>/dataset.csv` | **no licence stated** — see the note below | none |
| Dwelling counts (the exposure denominator) | BBR via Datafordeler, already in the repo (`data/processed/bbr.json`) | Indeholder data fra Klimadatastyrelsen | yes (already held) |
| Kommune / postal-code / quarter boundaries | DAGI via DAWA and Københavns Kommune, already in the repo | Klimadatastyrelsen; Københavns Kommune | none |

### Attribution strings

Carry these wherever the layer's figures are shown:

- **DMI:** `Contains data from the Danish Meteorological Institute (DMI Klimaatlas v2025a)`
- **Kystdirektoratet:** `Kystdirektoratet, Kystplanlægger oversvømmelsesfare` — with the horizon
  year, because the extent is dated: `Kystdirektoratet 2070`.
- **Miljøstyrelsen:** `Miljøstyrelsen / Kystdirektoratet, risikoområder (oversvømmelsesdirektivet 2024)`
- **Forsikring & Pension:** `Forsikring & Pension, vejrskader (chart TUJ9b / z0zEO, version 4, fetched 2026-09-23)`

### The F&P note — a snapshot, deliberately

Forsikring & Pension publishes these two figures as Datawrapper charts and **states no licence at
all**. The repo therefore treats them as a **dated snapshot with attribution**, not as a feed:
the chart id *and its version number* are recorded in `data/processed/climate/index.json`, the
fetch date travels with the value, and `make links` re-fetches the same versioned URL and checks
all 98 rows still agree. If F&P publishes a new version, the URL changes and the check says so
rather than silently following it. Two figures from a trade body are not the backbone of the
layer, and nothing else depends on them.

## 2. The horizon — one pill, two calendars

The zones and the figures come from different publishers with different calendars, and the UI
never lets them blur. One control (`hz=today|2070|2120`) moves both, and **every label names both**.

| horizon id | surge zone drawn | Klimaatlas period behind the figures | sea scenario | rain scenario | percentile |
|---|---|---|---|---|---|
| `today` | published **2020** extent | **1981–2010** reference period (`scenarie 0`, `periode 1`) | — (observed baseline) | — | 50 |
| `2070` | published **2070** extent | **2041–2070** (`periode 3`) | **SSP2-4.5** (`245`) | **RCP4.5** (`45`) | 50 |
| `2120` | published **2120** extent | **2071–2100** (`periode 4`) — *the latest period Klimaatlas publishes* | **SSP2-4.5** (`245`) | **RCP4.5** (`45`) | 50 |

Read the third row carefully: **there is no 2120 climate period.** Kystdirektoratet publishes a
2120 flood extent; Klimaatlas's last period ends in 2100. Pairing them is the only way to show a
2120 zone next to a figure at all, so the label says `2120 — zones: Kystdirektoratet 2120 ·
figures: Klimaatlas 2071–2100, latest Klimaatlas period`, everywhere, without exception. A unit
test asserts that exact wording (`tests/climate.test.js`).

`absolutaendring = 1` and `aarstid = 1` (annual) throughout. The **low–high range** shown in small
grey on the climate sheet is the same percentile under **SSP1-2.6 / SSP5-8.5** for sea and
**RCP2.6 / RCP8.5** for rain; `p10`/`p90` at the chosen scenario are carried in the data too.

## 3. Indicators

Eight, all `level: kommune`, all `direction: lower_better`, all `calc: climate`.

| key | unit | horizon | source field |
|---|---|---|---|
| `sealevel_cm` | cm | ✓ | Klimaatlas `Middelvandstand` |
| `surge100_cm` | cm above normal | ✓ | Klimaatlas `Stormfl100Aarsh` |
| `surge_freq_x` | × today | ✓ | Klimaatlas `StormflNuvaerende100Aarsh` |
| `rain100_1h_mm` | mm / hour | ✓ | Klimaatlas `Time100Aarsh` |
| `cloudbursts_yr` | events / yr | ✓ | Klimaatlas `Skybrud` |
| `weather_claims_1000` | claims / 1 000 inh. | — | F&P `z0zEO` |
| `flood_risk_area` | yes / no | — | Floods Directive 2024 designation |
| `surge_dw_pct` | % of dwellings | ✓ | counted here, from the published extent + BBR |

The two without a horizon are **one published figure each**, so they read the same at every
horizon and the sheet marks them `same` rather than going blank when the pill moves.

`surge_dw_pct` is the only one with a figure of its own **below** kommune level: postal codes and
Copenhagen quarters carry their own share and are therefore never marked `°`.

## 4. Methods

### 4.1 Which coastal stretch a kommune belongs to — longest shared coastline

Klimaatlas publishes the sea figures per **coastal stretch**, not per kommune. A kommune's
coastline is what is left of its boundary after subtracting every neighbour's (60 m tolerance,
EPSG:25832); that coastline is sampled every **25 m**, each sample is assigned to its nearest
stretch within **2 km**, and the kommune takes **the stretch holding the most samples**.

**77 of 99 kommuner are coastal. 42 of them touch more than one stretch.** Every other stretch a
kommune touches is kept in `other_kystkoder`, named beside the figure in the UI, and **never
combined into a number**.

> This replaced a `MAX` across stretches in v2.6 step 2. A maximum of two published figures is a
> figure nobody published — the conservative reading was still an invention. The new rule changed
> at least one value for **36 of the 42** multi-stretch kommuner; København moved from Køge Bugt
> (SJ8) to Øresund (SJ7), where almost all of its 116 km of coast actually lies.

### 4.2 Which kommuner are in a designated flood risk area — the ≥ 1 km² rule

The 2024 designation names **51 kommuner**; an any-touch spatial join returns **56**. Requiring
**≥ 1 km² inside a designated area** drops exactly the five that clip an edge (Rødovre 0.05 km²,
Albertslund 0.06, Høje-Taastrup 0.27, Egedal 0.33, Brøndby 0.71) and reproduces the official 51.
The cut sits in a real gap — the next kommune up holds 1.82 km² — so it is not a fitted constant.
The five are kept as `kommuner_marginal` and flagged `flood_risk_area = 0`.

### 4.3 Dwellings in the zone — BBR point plus 5 m

A dwelling counts when its **BBR building point falls inside the published polygon, allowing 5 m**,
because BBR gives a point, not a footprint. Dwelling definition is the repo's v1.4 one (Enhed
`boligtype` 1–5, `status` 6) and the denominator comes from `data/processed/bbr.json`, so the share
is consistent with every other BBR figure in the dashboard.

Computed for **kommuner, postal codes and Copenhagen quarters × 3 horizons**. The invariants
`2120 ≥ 2070 ≥ today` hold for every kommune on both area and dwellings — **0 violations**.

### 4.4 Zone geometry — simplified for the page, not for the count

The zones drawn on the map are simplified at **8 m** in EPSG:25832 (inside one 10 m cell), pinholes
under 2 000 m² filled, parts under 200 m² dropped, coordinates at 6 decimals. **The exposure counts
in §4.3 are computed on the raw, unsimplified polygons** — the simplification is a drawing
decision, never a counting one. Verified independently: §7.

### 4.5 Why the zone information is in the area popup

The extents cover half a municipality at a time. Drawn as clickable polygons they would swallow the
polygon click that opens a municipality — the map's main verb. So the zones are drawn in their own
Leaflet pane with **`pointer-events: none`**, and what they know about the clicked point is folded
into that same area popup instead: the click handler records the latlng before the popup builds
itself, and the popup tests it against the loaded extents.

**This is a deliberate deviation** from the original brief, which asked for popups on the zone
polygons themselves. The two requirements cannot both hold, and losing a click on the choropleth is
the worse failure. `make ui-check` asserts both halves: the pane takes no pointer events, and a
polygon click still opens a popup that carries the climate block.

## 5. On the map and in the app

| surface | what it shows |
|---|---|
| **`Climate risk` pill** (after `Services`) | `&climate=1`. Risk areas nationally; surge zones fetched per kommune for the viewport from **zoom 10** |
| **`#climatelegend`** | layer toggles (shift-click to isolate, `All`, `&clim=none` = "All hidden"), the horizon pill, and the screening footnote. Every legend block in the column folds from its own header — four of them is more than a screen holds |
| **Indicator dropdown** | a `Climate` group; the `Climate` chip is `surge_dw_pct`. For a Climate indicator the year selector is replaced by the horizon pill |
| **Area popup** | hazard, the full horizon label, the clicked point's in-zone answer, the area's share, the risk-area name, source and fetch date, and *Open climate sheet ›* |
| **Area card** | `Climate: 9,7 % dwellings in storm-surge zone (2070) · official risk area` |
| **`#climate/<kommune>`** | every indicator × 3 horizons with the low–high range, zone km² and dwellings per horizon, the stretch used and the others it touches, the risk-area flag, claims with rank, a verify link per row |
| **Analysis sheet** | a fourth overlay pill and a `Climate` section: the pin tested against the extent per horizon (`Today no · 2070 no · 2120 yes`), the area's figures, the risk-area flag |
| **Compare** | a `Climate` section: a per-horizon in-zone row for both sides (in zone = the worse side) plus four indicators |

Null values are grey and carry the publisher's own reason — `not coastal` for a landlocked kommune —
and **never take a rank**. A landlocked kommune has no sea level; that is not a zero.

## 6. Coverage, and what was left out

**Coverage is national** for every indicator. 77 of 99 kommuner have sea figures; all 99 have rain
figures; 85 have a surge zone at 2120, 81 at today.

Deliberately **not** built:

- **Cloudburst / pluvial flood zones.** The only route was the DHM `Bluespot_ekstremregn` raster
  behind a Datafordeler login this repo does not hold (`CLIMATE_PROBE.md` §5–6), and the alternative
  was to model surface water ourselves. An indicator that can only be estimated has no place in a
  layer that shows published figures. `rain100_1h_mm`, `cloudbursts_yr` and `weather_claims_1000`
  stay, because all three are published numbers rather than modelled exposure.
- **Groundwater.** Rising groundwater is a real and separate hazard with its own national mapping
  effort; nothing published today gives a per-area figure on the same footing as these, and
  inferring one from terrain would be our model, not a source's.
- **Flood depth.** Kystdirektoratet publishes depth only as a rendered map layer and through
  `/identify`, one point per request — and a point read is not safe on its own: a Sydhavn point
  reads `NoData` while a cell 150 m away carries 0.19 m. The layer shows **extent, not depth**.
- **Return periods other than 100 years.** 50, 1 000 and 10 000-year layers exist. One event is
  enough for a screening comparison, and four would quadruple the download for no added judgement.

## 7. Independent verification

`scripts/verify_climate.py` re-reads the published files and re-queries the sources **without
importing a single pipeline module**, then writes every compared value to
`docs/verification/climate_v2_6.csv`. Its gates and results are summarised in `DATA_MAP.md §7f`.

It re-queries Klimaatlas for every indicator × kommune × horizon, recomputes the coast mapping with
a different geometry method, re-fetches both F&P datasets, re-derives the 51 designated kommuner,
recounts every exposure figure on the raw polygons with a different point-in-polygon
implementation, and checks a sample of buildings against Kystdirektoratet's own `/identify`.

## 8. Refreshing it

| part | cadence | how |
|---|---|---|
| Klimaatlas values | **monthly, automated** (`refresh.yml`) | `python scripts/fetch_klimaatlas.py && python scripts/build_climate.py` — no key, ~7 s |
| F&P claims | **monthly, automated** | `python scripts/fetch_fp_claims.py` — the chart version is recorded; a new version fails the value check rather than passing silently |
| Surge zones | **manual, by decision** | `python scripts/fetch_kyst_surge.py && python scripts/build_kyst_zones.py` — 208 MB from a service that answers HTTP 500 on a multi-feature page, so the fetcher pulls **one OBJECTID at a time** with backoff (~2 min per horizon) and the rebuild recounts exposure against BBR |
| Risk areas | **manual, by decision** | `python scripts/fetch_flood_official.py --areas` — 26 sub-layers, ~90 MB raw |
| Coast mapping | **manual**, after a boundary change | `python scripts/build_climate_coast_map.py` — writes the committed `data/external/klimaatlas_coast_kommune.csv` |

The zones and the risk areas are **not** in the monthly job on purpose: they are large, slow,
served by an endpoint that needs retry logic, and they change when an authority republishes a
designation — an event worth a human decision and a changelog line, not a cron job. Klimaatlas and
F&P are small, keyless and quick, so they ride along with the monthly StatBank refresh.

After any manual rebuild: `make validate && make build`, `make test`, `make ui-check`, and
`python scripts/verify_climate.py` before a release.

## 9. Caveats

- **Screening, not assessment.** The extents compare areas. They do not tell you whether a given
  building floods, and they account for no defence, pump or floor level.
- **Two calendars.** The zone year and the Klimaatlas period are different things and are always
  labelled as such. 2120 figures are 2071–2100 figures.
- **One scenario on the surface.** SSP2-4.5 / RCP4.5 at p50 is what the map and the tables show.
  The low–high range is on the climate sheet; the high scenario is materially worse and is one
  click away, never averaged in.
- **The extent is not the coastline.** Kystplanlægger covers the whole coast, so a pin can sit in a
  coastal kommune and still be dry at all three horizons — two of the three points checked by hand
  during the build were.
- **F&P is a snapshot** of an unlicensed chart, versioned and attributed (§1).
- **`surge_dw_pct` is ours, from their polygon.** The extent and the dwelling register are both
  published; the count inside the polygon is arithmetic we perform, and §7 exists because of that.
