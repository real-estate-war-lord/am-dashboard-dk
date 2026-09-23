# Services layer — groceries, food, pharmacies, transport stops

**Status:** v2.x · pipeline **and** map overlay · national coverage
**Scripts:** `scripts/fetch_services.py` → `scripts/build_services.py`
**Output:** `data/processed/services/<kommune>.json` (committed) + `index.json`
**Counts:** [`SERVICES_COUNTS.md`](SERVICES_COUNTS.md) · **why these sources:** [`SERVICES_PROBE.md`](SERVICES_PROBE.md)
**On the map:** §8

What is within walking distance of an address: shops, places to eat, a pharmacy, and
the stop you catch a bus or a train at. **44 181 points across all 99 municipalities**,
2.6 MB of processed JSON.

Unlike the public-buildings and schools layers, this one is **national from day one** —
nothing here is gated behind a per-municipality API pull.

## 1. Sources

| what | source | licence | key |
|---|---|---|---|
| Groceries, food, pharmacies | **OpenStreetMap**, Denmark extract from [Geofabrik](https://download.geofabrik.de/europe/denmark.html) (`denmark-latest.osm.pbf`, ~495 MB, rebuilt daily) | **ODbL 1.0** | none |
| Transport stops | **Rejseplanen** static GTFS, `https://www.rejseplanen.info/labs/GTFS.zip` (~55 MB, refreshed roughly fortnightly) | **CC BY 4.0** (§6) | none |
| Municipality boundaries | DAGI via DAWA, already in the repo as `data/geo/kommuner.geojson` | Klimadatastyrelsen, free | none |

### Attribution strings

Carry these wherever the layer's points are shown, alongside the dashboard's existing
attribution line:

- **OSM:** `© OpenStreetMap contributors (ODbL)` — the basemap already carries this, so
  the layer adds no new string, but the *data* now depends on it too, not just the tiles.
- **Geofabrik:** `Data processed by Geofabrik GmbH and created by OpenStreetMap Contributors`
- **Rejseplanen:** `Rejseplanen, CC BY 4.0` — the feed's own `attributions.txt` names
  Rejseplanen as producer with `https://www.rejseplanen.dk`, and Labs' guidelines give
  the licence (§6).

## 2. Categories

`cat` is the layer toggle, `sub` is the legend filter — the same shape as the public
buildings layer's four categories.

| `cat` | `sub` | from |
|---|---|---|
| `grocery` | `supermarket` · `convenience` | OSM `shop=supermarket` / `shop=convenience` |
| `food` | `restaurant` · `cafe` · `bar` · `fast_food` | OSM `amenity=<the value>` |
| `pharmacy` | `pharmacy` | OSM `amenity=pharmacy` |
| `transport` | `metro` · `s-train` · `rail` · `light-rail` · `bus` | GTFS `route_type`, see §4 |

**`shop=discount` is not used.** It returns 0 nationwide — Netto, Rema 1000, Lidl and
Aldi are all tagged `shop=supermarket`. A discount split would have to come from
`brand`/`operator`, which the layer keeps.

**Nodes and ways both count**, ways placed at the average of their node coordinates:
46 % of Danish supermarkets are mapped as a building polygon, not a point, so a
node-only read would lose nearly half of them.

**One point per OSM id.** 27 objects nationally carry two of our tags — a petrol-station
shop that is also a takeaway counter, a bakery that is also a café. Each becomes one
point, and the order `grocery → pharmacy → food` decides which category it lands in.

## 3. Output format

`data/processed/services/<4-digit kommune>.json` — the same filename convention as
`public/` and `micro/`:

```json
{"v":1,"asof":"2026-09-23","kommune":"101","points":[
  ["grocery","supermarket",55.68123,12.57891,"Netto","Netto"],
  ["food","cafe",55.67901,12.56612,"Café Norden"],
  ["transport","metro",55.68384,12.57104,"Nørreport St.",1]
]}
```

| position | field |
|---|---|
| 0 | `cat` |
| 1 | `sub` |
| 2 | `lat`, 5 decimals (≈ 1 m) |
| 3 | `lon`, 5 decimals |
| 4 | `name` — may be `""`; OSM has plenty of unnamed POIs |
| 5 | **optional**, and what it holds depends on `cat`: the **brand** for `grocery`/`food`/`pharmacy` (only when it differs from the name), the **platform count** for `transport` (only when more than one stop was merged). Absent when it would be empty |

`index.json` carries the as-of date, the category/sub vocabulary, the source manifest
(url, licence, fetch date, byte size) and, per kommune, the point count with a
`by_cat` and `by_sub` breakdown — enough to decide whether to fetch a file at all.

## 4. Transport modes

GTFS `route_type` is the only thing that says what a stop is: `stops.txt` itself does
not, so the pipeline joins `stops → stop_times → trips → routes`.

| `route_type` | mode | note |
|---|---|---|
| `1` | `metro` | Copenhagen M1–M4 |
| `109` | `s-train` | **extended** GTFS type, not the base set |
| `2` | `rail` | |
| `0` | `light-rail` | Aarhus and Odense letbane |
| `3`, `700` | `bus` | `700` is an **extended** type — 479 stops |
| `715` | **excluded** | flextur / demand-responsive: not a stop you can walk to and wait at (3 077 stops) |
| `4` | **excluded** | ferry — not one of the modes asked for. 30 stops; one line in `ROUTE_TYPE` brings it back |

A filter of `route_type in (0,1,2,3,4)` would silently drop the entire S-train network,
479 bus stops and all of flextur. The extended types are in the mapping deliberately.

**A stop serving several modes becomes one point per mode**, so Nørreport is a metro
point *and* an S-train point *and* a rail point. 160 stops nationally serve more than
one kept mode.

## 5. Clustering rules

The feed has **`location_type=0` and an empty `parent_station` on all 36 383 stops** —
no station hierarchy at all — so grouping platforms into stations is ours to do.

| | rule |
|---|---|
| `metro` · `s-train` · `rail` · `light-rail` | same normalised name **and** same mode, single-linkage within **150 m** → one point at the mean position, carrying the platform count |
| `bus` | same normalised name and mode within **50 m** — enough to merge the two sides of a street, not enough to merge two stops a block apart |

**Name normalisation:** strip trailing parentheticals (Rejseplanen disambiguates with
`(Metro)`, `(Nørre Voldgade)`, `(togbus)`, `(Skive kom)`), strip a trailing `St.` /
`Station`, drop punctuation, lowercase. Two genuinely different "Nørreport"s are kept
apart by the distance test, not the name — which is why the Skive and Aarhus ones
survive as their own points.

**What this actually does:** heavy rail barely clusters — metro, S-train and rail are
already one row per station in this feed, not one per platform. The real merging is
light rail (173 → 109, paired directional stops) and buses (34 845 → 24 501, −30 %).
Worked examples for Nørreport, København H and Aarhus H are in
[`SERVICES_COUNTS.md`](SERVICES_COUNTS.md).

## 6. The GTFS licence — resolved

**Rejseplanen data is CC BY 4.0.** Rejseplanen Labs' own
["Retningslinjer for Labs"](https://labs.rejseplanen.dk/hc/en-us/articles/21553298043165-Retningslinjer-for-Labs)
states it, which closes the question the probe left open: the third-party catalogues were
right, we simply could not reach a first-party page at the time.

What that means in practice:

- **Attribution is required and sufficient:** `Rejseplanen, CC BY 4.0`, carried on every
  transport popup, in the map footer while the layer is on, and in Market › Sources.
- **Redistribution is allowed**, including the derived, clustered subset in
  `data/processed/services/`, and including commercial use.
- No share-alike obligation, so it does not interact with the ODbL side of the layer —
  OSM-derived points and GTFS-derived points stay separately attributed rather than
  being merged into one dataset under one licence.

The OSM/Geofabrik side is **ODbL 1.0**, stated on the Geofabrik download page.

## 7. Refreshing

```bash
python3 -m pip install -r requirements-services.txt   # osmium + shapely, this layer only

python3 scripts/fetch_services.py      # both raw files, skipped if < 7 days old
python3 scripts/fetch_services.py --force
python3 scripts/fetch_services.py --only gtfs

python3 scripts/build_services.py      # → data/processed/services/ + docs/SERVICES_COUNTS.md
```

`fetch_services.py` streams to a `.part` file and moves it into place, so an
interrupted download never leaves a truncated pbf behind, and records url, licence,
byte size and fetch time in `data/raw/services/manifest.json`. Raw files live under
`data/raw/services/` and are **gitignored**; the processed JSON is committed, so
`make build` and CI need none of this.

**Cadence:** the OSM extract is rebuilt daily and GTFS roughly fortnightly. GTFS is a
*timetable* and goes stale in a way BBR does not — monthly alongside the existing
refresh workflow is the sensible floor for the transport points.

### Sanity checks

`build_services.py` fails (exit 1) if any of these break:

- København (101) groceries within ±5 % of the probe's 513
- metro stations in Denmark between 40 and 50
- no municipality with zero groceries
- processed output under 15 MB (exit 2, so it stops before committing something huge)

## 8. On the map

The **Services** toggle sits in the map toolbar next to *Infra projects* and *Public
buildings*, and is **off by default**. It is built on the same code paths as those two:
the same `.seg`/`.sg` toolbar button, the same legend box in the `.maplegs` column, the
same `.lfpop` two-level popup, the same white-halo circle markers, and the same
"legend is the filter" interaction (click a row to toggle, shift-click to isolate,
*All* to reset).

### Filter and defaults

The legend lists all four categories, always, so an off one is a click from coming back.
Transport carries a sub-toggle because its two halves are three orders of magnitude
apart — 628 stations against 24 412 bus stops.

| | default when the layer is switched on |
|---|---|
| Groceries | **on** |
| Food & drink | off — 14 641 points nationally |
| Pharmacy | **on** |
| Transport → Rail & metro | **on** |
| Transport → Bus | off — 24 412 points nationally |

The filter rides in the hash as `&services=1&srv=g,p,t,rail`, so a filtered view is a
shareable link, exactly like `&pub=`.

### Zoom floors, and why there is no clustering

Each category is drawn only above its own zoom, and below it the legend row says
*zoom in* with a hint line underneath:

| from zoom | category |
|---|---|
| 10 | Rail & metro stations |
| 13 | Groceries, Pharmacy |
| 14 | Food & drink, Bus |

Only points **inside the viewport** (padded 15 %) are drawn, and a redraw happens only
when the map leaves that padding — a small pan costs nothing. The dense categories use
Leaflet's **canvas renderer**; stations stay SVG so they keep their hover growth and
cursor, at the same radius as the infra station markers.

Measured worst case: **zoom 14 over Nørrebro with every category on is 3 346 markers,
rebuilt in 15.6 ms**, with a pan at 0.4 ms. That is inside one frame, so the layer ships
**without a clustering library** — adding `Leaflet.markercluster` would mean a
third-party runtime dependency for a problem the zoom floors already solve. If the
floors are ever loosened, revisit that: the legend already reports the drawn count and
says *at the drawing ceiling* past `SRV_MAX_MARKERS`.

### Loading

Per-kommune files are fetched **only for municipalities whose `index.json` bbox meets
the viewport**, capped at 24 files per pass and never below the lowest active zoom floor
— the national view intersects all 99 bounding boxes, and fetching 2.6 MB to draw
nothing is precisely what this layer must not do. Files are cached for the session.

### Attribution on screen

Both licences appear wherever the points do: each popup carries its own source line
(`© OpenStreetMap contributors, ODbL` or `Rejseplanen, CC BY 4.0`) with the as-of date,
the map footer gains a **Services:** line while the layer is on, and Market › Sources
has a *Services layer* table listing both sources with their licences.

## 9. Caveats to repeat wherever these numbers are shown

- **OSM completeness is not uniform.** Copenhagen is densely mapped; rural Jutland is
  thinner. Zero groceries in a rural postal code may mean "none mapped", not "none".
  This is the layer's biggest weakness and it is not measurable from inside the data.
- **A stop is not a service level.** The layer says a bus stops here, not how often.
  `stop_times` has the frequencies if that is ever wanted.
- **212 points were dropped** for falling outside every Danish municipality polygon —
  mostly Skånetrafiken's Swedish stops, plus harbour and ferry points.
- **Fødevarestyrelsen's Smiley data is deliberately not used.** It has no coordinates
  at all, and it counts every food *business* — canteens, wholesalers, kiosks — not
  places a resident walks into. See [`SERVICES_PROBE.md`](SERVICES_PROBE.md) §5.
- **Overpass is deliberately not used at runtime.** It returned confident wrong zeros
  during the probe. Everything here comes from a versioned file, not a live API.
