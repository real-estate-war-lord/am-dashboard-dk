# Test property pin and the Analysis sheet

**Status:** v2.4 · the pin and the sheet work nationally; two of the seven sections are Copenhagen-metro only
**Code:** `src/testprop.js` (the parser, no DOM, unit-tested) · `src/app.js` (`locate`, `featDistM`, `vAnalysis`)
**Data:** `dist/geo/kommuner_lookup.json` (built by `scripts/build_dashboard.py`), plus every layer the
dashboard already ships

One address, read against every layer at once. Paste a Google Maps link into the box on the map
toolbar and the dashboard drops a pin; *Analyse ›* opens `#analysis?a=<lat>,<lon>` — a single-property
sheet with the area profile, safety, the infrastructure projects nearby, the public buildings and
schools around it, and the sources each figure came from.

## 1. Purpose

The dashboard is built around areas: a municipality, a postal code, a Copenhagen quarter. An
acquisition is about one address. The Analysis sheet is the bridge: it takes a point, works out which
areas contain it, and re-reads every layer from that point outward — with distances computed from the
geometry rather than inherited from whichever polygon the address happens to sit in.

It adds no new source. Everything on the sheet already exists in the dashboard; what is new is that it
is assembled around a coordinate instead of around a boundary.

## 2. What goes in — accepted link formats

`parseLocation(text)` in `src/testprop.js` is the whole intake. It is a **parser, not a resolver**: it
reads the text it is given and never issues a network request or follows a redirect. 15 cases under
`make test-js` (`tests/testprop.test.js`).

The patterns are tried in this order, and the first hit wins:

| # | source | example | why this order |
|---|---|---|---|
| 1 | `place` | `…/place/Name/@55.6,12.5,17z/data=…!3d55.67610!4d12.56830` | `!3d`/`!4d` is the **place pin** — the actual spot |
| 2 | `at` | `…/maps/@55.67610,12.56830,17z` | the `@` triple is only the **viewport centre**, which can sit a street away, so it never beats the pin |
| 3 | `param` | `…/maps?q=55.67610,12.56830` | `q=` · `ll=` · `query=` · `daddr=` · `center=` |
| 4 | `search` | `…/maps/search/55.67610,12.56830` | |
| 5 | `plain` | `55.67610, 12.56830` | comma, semicolon or whitespace |

Before matching, `+` is turned back into a space and the text is `decodeURIComponent`-ed once, so a
copied URL with `%2C` or `+` parses like a plain one. A stray `%` is not fatal — the text is then read
as it stands.

A coarse **54–58 N / 7–16 E** box rejects numbers that cannot be in Denmark, which is what catches a
swapped lon/lat pair (`12.53, 55.64` is refused, naming the expected order). This box is deliberately
generous: Malmö passes it. The real answer to *is this in Denmark* comes from `locate()` (§3), which is
why a point in Øresund is reported as **"in water or outside Denmark — no municipality or postal code
covers it"** rather than silently pinned.

Every failure is a named error rendered as an inline line under the input. There is no `alert()`
anywhere in this path.

### 2b. The short-link limitation

`maps.app.goo.gl`, `goo.gl` and `g.co/kgs` links carry **no coordinates at all** — they are opaque
identifiers that only Google's redirect can expand. Expanding one means an HTTP request to Google from
the reader's browser, which the dashboard does not do: it is a static page with no backend, and
following the redirect would both break under CORS and tell Google which address is being looked at.

So a short link is detected and refused by name:

> Short share links can't be read in the browser. Open the link and copy the full URL from the address
> bar, or right-click the spot in Google Maps and paste the coordinates.

This is a real limitation, not a bug, and the "?" tooltip next to the input repeats it. The Google Maps
share sheet produces short links by default; the long URL is in the address bar after opening one.

## 3. Where the pin is — kommune, postal code, quarter

`locate(lat, lon)` answers at all three levels the dashboard knows:

```
kommune   ← dist/geo/kommuner_lookup.json   (point-in-polygon, holes respected)
postnr    ← the postal-code rings already inlined in the page
kvarter   ← Københavns Kommune's quarter rings, only when the kommune is 101
```

### 3a. Why `kommuner_lookup.json` exists

A postal code can cross a municipality border, so *"the municipality of the postal code the point falls
in"* is a guess, not an answer. The kommune polygons are the register's own boundaries, and the pin
asks them directly.

The file is built by `kommuner_lookup()` in `scripts/build_dashboard.py` from
`data/geo/kommuner.geojson` (DAGI via DAWA), simplified with Shapely at **0.0005°** and rounded to five
decimals: **99 kommuner, 911 kB** (≈285 kB gzipped over GitHub Pages). It is **not** inlined into
`index.html` — it is fetched lazily by `komLoad()` the first time a pin is dropped, or on load when the
page opens straight on an `#analysis` link, so the 4.4 MB dashboard does not grow by another megabyte
for readers who never use the feature.

### 3b. The holes matter

A kommune is stored as `[outer ring, hole, hole, …]` per polygon and tested as
`inPoly = pip(outer) && !holes.some(pip)`.

**Frederiksberg is a hole in København.** Drop the holes and every Frederiksberg pin is labelled
København — a 106 000-inhabitant municipality with its own statbank figures silently absorbed into its
neighbour. The builder keeps every ring of every polygon, and each ring needs ≥ 4 points to survive
simplification.

### 3c. When the file is missing or late

`locate()` degrades instead of failing:

- ring file not yet arrived, or the fetch failed → the kommune is taken from the postal code and the
  answer is tagged **`approx.`** in the header, with a tooltip saying why. The sheet renders; it does
  not wait.
- no kommune **and** no postal code → `{ error: "in water or outside Denmark" }`, shown as the inline
  error under the input; the pin is not dropped and any existing pin is left alone.

`tpRes()` caches the result against `lat,lon,<ring file loaded?>`, so the answer is recomputed exactly
once when the rings land, and the header corrects itself from *approx.* to the register's answer.

## 4. Distances

`featDistM(feature, lat, lon)` — no lookup table, no precomputed matrix. Every distance on the sheet is
computed in the browser from the geometry:

| geometry | method |
|---|---|
| `Point` | great-circle (haversine, R = 6 371 008.8 m) |
| `LineString` / `MultiLineString` | nearest point on any segment |
| `Polygon` / `MultiPolygon` | **0 m** if the pin is inside the outer ring and outside every hole, otherwise the nearest point on any ring |

For lines and rings the degrees are projected to metres **at the pin's own latitude** —
`kx = 111 320 · cos φ`, `ky = 110 540` — and the nearest point on each segment is found by projecting
onto it and clamping to `[0, 1]`. Over the few kilometres this sheet looks at, the error against a
proper geodesic is well under a metre; over Denmark's span it would not be, which is why the same
function is not used for anything larger.

Displayed distances round to the nearest **10 m** below 1 km and to **0.1 km** above it — the precision
the underlying geometry actually supports, given that an infra corridor may be a schematic line and a
BBR point is the building's own coordinate, not its entrance.

### 4a. Rings and radii

| constant | value | what it governs |
|---|---|---|
| `TP_RINGS` | 500 · 1 000 · 1 200 m | the dashed, non-interactive circles drawn around the pin |
| `AN_RING_M` | 1 000 m | public buildings and schools **counted and listed** |
| `AN_PUB_MAP_M` | 2 000 m | public buildings **drawn** on the mini map (twice the counted ring) |
| `AN_INFRA_M` | 3 000 m | infrastructure projects listed, nearest first |
| `AN_CHIP_M` | 1 200 m | an unopened **station** this close becomes a headline chip |
| `AN_NEAREST` | 5 | rows listed per public-building category |

### 4b. Neighbouring municipalities are read too

The per-municipality files (`public/<kommune>.json`, `micro/<kommune>.json`) are loaded on demand, so
a pin near a border would otherwise see only its own municipality's buildings. `anKomsNear()` expands
the ring into a lat/lon box and returns every kommune whose bounding box touches it, the pin's own
first — so a pin in Lyngby reads Gentofte and Gladsaxe as well, and the card says which files it read.
The pin at Sluseholmen (2450 SV) reads **København and Tårnby**.

## 5. The mini map: layer pills and hash parameters

The *Where it is* map carries the same three pills as the Macro map, with the same styling, the same
legends, the same filters and the same popups:

| pill | default | disabled when |
|---|---|---|
| **Infra projects** | on | the layer is empty |
| **Public buildings** | on where the BBR pull reaches the pin | no covered municipality near the pin → *"Not covered yet: Copenhagen metro area only"* |
| **Buildings** | off — `micro/<kommune>.json` is fetched only when switched on | no BBR building file for the pin's municipality, and the tooltip names it |

Schools are **not** a fourth pill: they ride inside Public buildings, and isolating Education (*ONLY* in
the legend) recolours the school markers by FP9 grade — on this map exactly as on the Macro map. The
choropleth underneath follows whichever headline tile is selected, so clicking GROWTH / UNEMP. /
RENTED recolours the areas under the pin.

A file arriving refills the map and the affected cards **in place**: no re-render, so an open popup and
the reader's own zoom survive it.

### 5a. Hash parameters

The sheet:

```
#analysis?a=<lat>,<lon>&la=<label>&ind=<indicator>&y=<year>&lay=<layers>&pub=<categories>&pubkind=<kinds>
```

| parameter | meaning |
|---|---|
| `a` | the pin, `lat,lon`, five decimals — the only required one |
| `la` | the label; default *Test property* is omitted |
| `ind`, `y` | the indicator and year colouring the mini map (as on the Macro map) |
| `lay` | comma-separated subset of `infra`, `public`, `buildings`. **Absent = the defaults** (infra + public). All three off serialises as `lay=none`, which reopens with nothing on |
| `pub` | public-building categories: `edu`, `inst`, `health`, `culture`. All four off is `pub=none`; an empty or unreadable value means *all*, so a hand-typed link cannot blank the map |
| `pubkind` | `existing` and/or `open` |

The map view instead carries the pin itself:

```
#map/<kommune>[/postnr]?ind=…&pin=<lat>,<lon>&pl=<label>
```

so the pin survives a reload, an indicator change and every level change, and *Analyse ›* → **browser
Back** returns to the map with the pin still there. `Copy link` on either view reproduces what is on
screen.

## 6. Coverage — national vs Copenhagen metro

The sheet renders everywhere in Denmark; two of its seven sections do not have national data behind
them and say so rather than showing an empty table.

| section | coverage |
|---|---|
| Header — kommune · postal code · quarter | **national** (quarter: Københavns Kommune only, by definition) |
| Area profile | **national** — 99 municipalities, ~600 postal codes, 67 Copenhagen quarters |
| Safety | **national** at municipality level; postal codes and quarters inherit it (`°`), Copenhagen quarters add the city's own bydel survey (`^`) |
| Infrastructure nearby | **national** — 51 curated projects, but the list is Copenhagen-heavy because the projects are |
| Mini map · Buildings pill | 99 municipalities with a BBR building file |
| **Public buildings within 1 000 m** | **Copenhagen metro set only** — København and 18 suburban municipalities |
| **Schools within 1 000 m** | **Copenhagen metro set only** — 364 grundskoler in the same 19 municipalities |

Outside the metro set both cards read *"Not covered yet: … are available for the Copenhagen metro
area"* and the Public buildings pill is disabled with the same wording. An empty ring inside the
covered area reads *"no public building within 1 000 m"* — a different sentence, because it means
something different. Adding a municipality is `fetch_public_buildings.py --kommune <code>` then
`build_public.py`; see [`PUBLIC_BUILDINGS.md`](PUBLIC_BUILDINGS.md) §5.

## 7. Privacy

The whole feature runs in the reader's browser. The pasted text is parsed locally, the link is never
followed, no coordinate is sent anywhere, and the page has **no backend and no analytics** — the only
requests it makes are for its own static files on GitHub Pages plus OpenStreetMap basemap tiles (which
see the map viewport, as any web map does). `grep -n "localStorage\|sessionStorage\|indexedDB"
src/app.js` returns nothing: the pin is not stored on the device either.

What does travel is the **URL**. The pin lives in the hash (`?a=`/`&pin=`) precisely so a view can be
reloaded and shared — which means anyone given the link gets the coordinate, and it lands in browser
history, in whatever chat or mail carried it, and in the address bar over someone's shoulder. A URL
fragment is not sent to the server, but that is not the risk here; the person you send it to is.

So the box says so, in one muted line under the input on both the map toolbar and the Analysis empty
state:

> Processed in your browser. The location is stored only in the page URL; don't paste confidential deal
> locations if you share the link.

## 8. Sources

The sheet's own *Sources & as of* card is generated from what that particular pin actually read, so it
differs between a Copenhagen address and an Esbjerg one. The full set it can draw on:

| used for | source |
|---|---|
| Locating the pin | **DAGI administrative boundaries** — Klimadatastyrelsen via DAWA (kommuner, postnumre); Københavns Kommune bydele og kvarterer, opendata.dk (CC BY 4.0) |
| Area profile | Danmarks Statistik (FOLK1A, POSTNR1, BOL101, INDKP101, HFUDD11, AUP01 …); Københavns Kommune statbank `s30` for quarters; BBR via Datafordeler for the housing-stock block |
| Safety | Danmarks Statistik STRAF11 / STRAF22; Københavns Kommunes Tryghedsundersøgelse (Epinion) / Københavns Politi for the bydel figures |
| Infrastructure nearby | the curated layer — Transportministeriet (Anlægsstatus), Fingerplan 2019, the regions, Movia, Vejdirektoratet, Bygningsstyrelsen, OSM alignments; see [`INFRA.md`](INFRA.md) |
| Public buildings | BBR via Datafordeler (`byg021BygningensAnvendelse` 410–449, open building cases); see [`PUBLIC_BUILDINGS.md`](PUBLIC_BUILDINGS.md) |
| Schools | Uddannelsesstatistik.dk (STIL); see [`SCHOOLS.md`](SCHOOLS.md) |
| Map and names | © OpenStreetMap contributors (ODbL) — basemap tiles, and building names within 60 m |
| The *OpenStreetMap ↗* link in the header | opens `openstreetmap.org` at the pin — a deliberate outbound click, not a background request |

Every as-of and fetched stamp on the card comes from the built files themselves, not from a hand-kept
list.

## 9. Caveats to repeat wherever these numbers are shown

- **The pin is where you put it.** Google Maps' `@` viewport centre is not the property; the sheet
  prefers the `!3d/!4d` place pin for that reason, but a link copied from a panned map will still be
  off by whatever the reader panned.
- **Distances are to mapped geometry**, not walking routes: a station point, the nearest point of a
  line, 0 m inside a development area. A corridor flagged *schematic* is hand-drawn and its distance is
  indicative. A school's distance is to its register point, not its gate.
- **`approx.` means the kommune came from the postal code** and a postal code can cross a border.
- **An open building case is not a construction schedule** — BBR is owner-reported and carries almost
  no completion dates ([`PUBLIC_BUILDINGS.md`](PUBLIC_BUILDINGS.md) §2).
- **Two sections are metro-only** (§6); *"Not covered yet"* is not *"nothing here"*.
- **A percentile bar is direction-aware** — it always fills toward "better", so a low burglary rate and
  a high income read the same way. An inherited (`°`) figure is ranked against municipalities, not
  against the postal codes that all copy the same number.

## 10. Verification

The pin, the resolution and the distances were checked in the browser on 2026-09-23 against three
locations — 2450 København SV, Nørrebro and Esbjerg — and the nearest station's distance was recomputed
by hand from its coordinates. The results are logged in
[`DATA_MAP.md` §7d](DATA_MAP.md#7d-analysis-sheet--test-property-pin-2026-09-23).
