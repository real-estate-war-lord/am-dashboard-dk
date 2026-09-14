# Changelog

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
