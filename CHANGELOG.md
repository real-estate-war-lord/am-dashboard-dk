# Changelog

## v2.0 — 2026-09-22
- **Safety indicators** from Statistics Denmark — `STRAF11` (reported offences by place of offence, quarterly from 2007) and `STRAF22` (reports and charges, annual): reported crime, violent crime, property crime and drug/weapons offences per 1,000 inhabitants, residential burglaries per 1,000 dwellings, reported crime y/y and the share of penal-code reports with a charge. Rolling four quarters, municipality level; postal codes and Copenhagen quarters inherit the municipality value (°). Registry fields `direction`, `note`, `chip`, `history_from`, `map_from`, `breaks`.
- **Map and table**: *Crime* chip, *Safety* group in the indicator select (terracotta ramp), fifth figure *Crime* in the municipality card, Safety block in popups and on area pages, Safety columns in the table while a Safety indicator is selected; the details line shows the registry note and "Danmarks Statistik, STRAF11 / FOLK1A, as of 2025K3→2026K2, fetched …".
- **Direction-aware ranks**: "#n of 98" counts from the best end — for *lower is better* indicators (Safety, unemployment) #1 is the lowest value; y/y and vs-median colours and the first click on a table column follow the same sense; legends say "↓ lower is better · darkest = highest".
- **Charts**: axis starts at each indicator's first year (crime 2007); *Yearly | Quarterly* toggle for rolling-quarter series (2008 Q1 → latest); overlays of related indicators; dashed *Denmark* reference line (DST area 000); series breaks from the registry drawn as markers with the source's wording as tooltip; the axis stays at 0 for all-positive series.
- **Year selector**: Safety indicators offer 2008 → latest; rolling indicators whose window ends in the latest year are labelled "2026 (latest)" instead of "latest (2025 data)".
- **Sources**: *Fetched* column filled for every table (date of the raw pull); STRAF11/STRAF22 listed with their `updated` stamps.
- **Copenhagen quarters get their own safety figures** from Københavns Kommunes Tryghedsundersøgelse 2026 (Epinion) / Københavns Politi: reported crime per 1,000 inhabitants (2025) and the new indicator *Feeling safe in own neighbourhood* (2026 survey), published per bydel and shown on all 67 quarters with a `^` marker and the level tag *bydel (KK survey)*. `scripts/import_kk_tryghed.py` extracts the 13 areas from the PDF with cross-checks; `data/external/cph_bydel_map.csv` maps them to the quarters (Nørrebro split into Indre and Ydre, confirmed against the report's populations). Quarter pages and popups also show the survey's reported-offence count and its violence and burglary rates per 1,000 inhabitants.
- **Units**: rates per 1,000 no longer borrow the ‰ sign — "263" on the map and in the legend, "90 / 1,000" in cards, tables, popups and chart legends. Map labels no longer overlap, and a figure published per bydel is labelled once per bydel.
- The infrastructure-projects overlay moves to v2.1.
- Tests: `tests/test_safety.py` (`python3 -m unittest discover -s tests`) — rolling window, suppression, multi-code select, yearly filing, København 89.9 per 1,000 and clearance 17.1 % from the raw pulls.

## v1.9 — 2026-09-20
- **Overview first**: the top bar is a breadcrumb (Denmark › municipality › area — every step a link) and the sidebar shows names only; the duplicate card titles, back-links and "× Denmark" chips are gone, so the map starts ~110 px higher.
- **Indicator picker**: grouped select plus quick chips (Growth · Price/m² · Rent · Unemp. · Rented · Supply) on the map and in the table; the indicator's definition, source, coverage and history are folded behind *ⓘ details* (one line by default).
- **Map colours and legend**: five quintile classes instead of a min–max ramp (each class holds a fifth of the visible areas, so outliers no longer flatten the map), a stronger ramp, and a class-break legend drawn on the map (bottom right) for the macro map, the buildings layer and the area-page map. Building shares (rented, unoccupied, < 50 m²) use fixed breaks. Fewer, cleaner labels: the 12 largest municipalities at national zoom, values from zoom 8, no overlapping names.
- **Area pages**: headline row with the five key figures (value, y/y, rank) under the title; tiles show one theme at a time (Demographics first) with a single context line (#rank · vs median) and a ↗ into Charts; the explanatory paragraph became an ⓘ tooltip; *All indicators*, *Housing stock (BBR)* and *Quarters & postal codes* are tabs of one card — the page is about 2 200 px instead of 5 000.
- **Map popups** in two levels: the selected indicator big with its rank, four headline figures, buttons *Open page › · Zoom to municipality · Buildings › · ↗ Chart*, and *All N values* folded underneath. Building cards name their quarter / postal code with a link to it.
- **Buildings**: address search first, filters folded behind *Filters (n active) ▾*.
- **Charts**: the empty state explains what to do and offers the quick picks; the "single snapshot" note only appears when it applies; every tile, table row and popup has a ↗ that opens Charts with that area and indicator.

## v1.8 — 2026-09-18
- **Addresses and property numbers on buildings**: `scripts/fetch_dar.py` pulls the access address from DAR (husnummer → street + postal code) and the BFE property number from BBR (building → grund → ejendomsrelation) for every building in the Micro layer — 174 539 / 174 551 buildings (100 %) got an address, all got a BFE. Building cards show the address as title, the BFE and how many other buildings share the property; CSV export carries both columns.
- **Find address** box in Buildings mode: type "Nordens Plads 4" → the map zooms to the building and opens its card (filters are widened if the building was filtered out).

## v1.6 — 2026-09-15
- **Charts** (new nav item): pick an indicator, up to 8 areas (municipalities, postal codes, Copenhagen quarters — search box or quick picks), year range and a median line; download as PNG (2400×1280, self-contained with title, legend and source) or the data as CSV; the URL holds the whole setup.
- **Sources** merged into Market: folded panel *Sources, freshness and indicator definitions* at the bottom (`#market?src=1` opens it).
- **Full-screen map**: ⤢ button on the map card (Esc exits); works in Areas and Buildings mode.
- Charts: lagging sources no longer leave a gap before an isolated "latest" point — series end at the last year with data and the legend shows that year; **Bars** mode (latest value per area, median marker) for indicators without a time series; **Distribution** mode: BBR donuts per area (dwelling size, rooms, year built, building type) with CSV; Auto picks line/bars.
- Map popups are wider with two columns — all indicators visible without scrolling; building popups likewise.
- New count indicators next to the normalised ones: *Dwellings completed, last 4Q (number)* and *Homes for sale (number)*.

## v1.5 — 2026-09-15
- **Buildings (Micro) layer** inside the map view: when a municipality is open, *Areas | Buildings* switches to every residential building with ≥ 2 dwellings as a dot (size = dwellings, colour = rented share / unoccupied / average size / year built / dwellings / < 50 m² / floors), filters (min. dwellings, year built, building type, rented ≥ %), building popup with tenure, sizes and rooms, CSV export of the filtered set, link from area pages. `scripts/build_micro.py` writes one compact file per municipality (`data/processed/micro/<kommune>.json`, loaded on demand — the page must be served over http: `make serve` or GitHub Pages).
- BBR coverage: Copenhagen and the 18 suburban municipalities (776 791 dwellings); the rest of the country follows as it is fetched.

## v1.4 — 2026-09-14
- **BBR housing stock at postal-code and quarter level** (Datafordeler GraphQL, free API key): `scripts/fetch_bbr.py` pulls current dwellings and buildings per municipality (resumable, `--metro` / `--all`, `--workers`), `scripts/build_bbr.py` places each dwelling by its building's coordinate into postal codes and Copenhagen quarters and writes `data/processed/bbr.json`.
- Seven new indicators, group *Housing stock (BBR)*: rented share, unoccupied share, average size, share < 50 m², built 2010+, multi-dwelling share, dwellings per building — same definition at every level, so no inherited ° values. Validation: Frederiksberg 57 942 dwellings vs DST BOL101 57 576 (+0.6 %).
- Area pages: *Housing stock — BBR register* card with rooms, size, year-built and building-type distributions (municipality as reference tick).
- Coverage grows as municipalities are fetched (first: Copenhagen and 18 suburban municipalities); areas without a pull show –.

## v1.3 — 2026-09-14
- Map view is map-only: area selector (Denmark / region › municipality), indicator + year, selected-municipality strip with rank and a link to its page. Tables moved to the Table view (own nav item; rows open area pages; Δ column), trend chart removed from the map.
- Area pages for every municipality, postal code and Copenhagen quarter (`#area/<type>/<code>`): key-figure tiles by group (Δ since first year, rank among peers, sparkline), trend chart vs municipality and median of peers, context map (neighbours clickable), all-indicator comparison table, sub-area table (postal codes / quarters).
- Navigation by URL hash — every screen has a permalink, browser back/forward and Esc work; popups link to area pages; legend shows min/max; polygons highlight on hover; faster wheel zoom.
- Map view: searchable area box (type a municipality, postal code or quarter; Enter opens it), source list folded under *Data information*.
- Area page tiles: *All figures* first (max 14 = 7 × 2), each tile with y/y change, sparkline against the median of peers (dashed), rank bar, change since 2016 and gap to the median.
- Responsive layout for laptops with 125–150 % display scaling (Windows): narrower sidebar and type below 1400 px, map height follows the window, tile grid 7 → 5 → 4 columns, stable scrollbar gutter; a drilled-in municipality shows its sub-areas at any zoom.
- Sidebar: renamed *Macro Dashboard*; footer replaced by **Export data** — one long-format CSV (level; code; name; parent; region; population; year; indicator; label; unit; value; as_of) of every level, indicator and year plus the macro series.

## v1.2 — 2026-09-14
- Copenhagen quarter level: 67 kvarterer from Københavns Kommune's statbank (`s30`, config section `cph`, `scripts/build_cph.py`) with 12 indicators and 2016–2026 history; polygons from the municipality's WFS (`scripts/fetch_geo_cph.py`, CC BY 4.0).
- UI: clicking København shows quarters with a *Quarters | Postal codes* toggle; table mode gains a *Copenhagen quarters* level; popups, trend chart, CSV export and year selector work on quarters.
- Map: fractional zoom so a municipality fills the map after drill-down; labels rebuilt on every zoom step and shown only where the polygon is wide enough on screen (fixes the label pile-up in Copenhagen).
- Unemployment in Copenhagen is district-level (bydel) by source — repeated on each quarter and flagged in the indicator explanation.

## v1.1 — 2026-09-14
- Time series 2016–2026 for every indicator (same calculation per year, same quarter/month each year; values filed under the data's own year so lagging sources do not repeat).
- Year selector next to the indicator selector; map, tables, popups and CSV follow the selected year; "Δ since 2016" column.
- Trend card: selected indicator over the years for pinned municipalities (☆ in the table) or the five largest.

## v1.0 — 2026-09-14
- First public release on GitHub Pages: 99 municipalities, 606 postal-code areas, 20 indicators, 13 macro series.
- Rents: private (boligstat.dk 2026, 95 municipalities) and social (Landsbyggefonden 2026, 98) with reproducible import scripts.
- UI: grouped indicator selector with explanation panel; Map/Table mode with search, region filter, min-population and CSV export; popups survive auto-pan; OpenStreetMap basemap.
- Geometry: postal codes clipped to municipalities, central-Copenhagen street codes merged, dominant municipality by overlap area.
- Verification: 11 cells recomputed independently (docs/DATA_MAP.md §7b).
- CI: every push deploys; monthly data refresh.

## v0.2 — 2026-09-14
- Dashboard template (`src/`): design ported from the Finnish edition, English UI, registry-driven indicators, views Macro map / Market / Sources.
- Pipeline scripts: `validate_config`, `fetch_statbank` (DST + Finans Danmark `s20`), `fetch_geo_dawa`, `build_makro`, `build_market`, `build_dashboard`.
- Docs: `DATA_MAP.md` (sources), `BUILD_PLAN.md` (phases), `RUNBOOK.md` (step-by-step), `DATA_FOLDERS.md` (folder conventions), `GEO.md` (boundaries).
- `Makefile`, monthly GitHub Action with Pages deploy, MIT licence.

## v0.1 — 2026-09-14
- Data map research: Statistics Denmark, Finans Danmark, DAGI/DAWA, BBR, rents, macro sources; key endpoints verified live.
