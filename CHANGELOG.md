# Changelog

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
