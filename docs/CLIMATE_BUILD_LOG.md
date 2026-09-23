# Climate branch (v2.5-climate) — build log

Worktree: `am-dashboard-dk-climate`, branch `v2.5-climate`, parallel to `../am-dashboard-dk`
(never edited from here). Serve on port **8081** so the other session keeps 8080.

## Shared files touched

Files shared with other branches (`config/indicators.json`, `src/app.js`, `src/index.html`,
`Makefile`, `.github/workflows/refresh.yml`, `README.md`, `CHANGELOG.md`, `docs/DATA_MAP.md`)
must be edited only in small, additive ways, and every edit listed here for the merge.

| Date | File | Edit | Why |
|---|---|---|---|
| — | — | none yet | — |

No shared file has been edited on this branch. Everything so far is new, climate-only files:
`scripts/probe_climate.py`, `docs/CLIMATE_PROBE.md`, `docs/CLIMATE_BUILD_LOG.md`.

## Climate-only files (free to change)

`scripts/*climate*`, `scripts/fetch_klimaatlas.py`, `data/raw/{klimaatlas,flood_hazard,dhm,bluespot,fp}/`,
`data/processed/climate/`, `docs/CLIMATE*.md`.

## Worktree environment (2026-09-23)

* `.env` copied from `../am-dashboard-dk` (gitignored, not committed).
* Symlinks to the main folder's gitignored caches (read-only use, no GBs duplicated):
  `data/raw/bbr` (4.0 GB), `data/raw/dar` (78 MB), `data/raw/public`, `data/raw/uddstat`,
  `data/geo/raw` (148 MB). These show as `??` in `git status` — a `.gitignore` entry ends in
  `/` and does not match a symlink. **Never `git add -A` here**; add paths explicitly.
* `data/raw/*.csv` StatBank pulls (25 MB) copied, not symlinked, so a `make fetch` here cannot
  write into the main folder.
* New climate data dirs created as real local dirs (never symlinks):
  `data/raw/klimaatlas`, `data/raw/flood_hazard`, `data/raw/dhm`, `data/raw/bluespot`,
  `data/raw/fp`, `data/processed/climate`.
* Verified: `make validate` and `make build` both exit 0 here (dist/index.html 4.4 MB,
  99 municipalities, 606 areas).

## Probe step (2026-09-23)

`scripts/probe_climate.py` → `docs/CLIMATE_PROBE.md`. Read-only; writes nothing but that one doc.
11 of 12 expected values reproduce. What it changes about the plan:

* **Klimaatlas is the backbone.** Storm surge per coastal stretch (34 with geometry) and cloudburst
  per kommune, sub-second, every expected figure matching, with `periode`/`scenarie` columns that map
  straight onto a Today / 2050 / 2100 horizon pill. No raster work needed for the first layer.
* **MST `OD_fare_2024` cannot give a depth grid over REST** — it is a MapServer, `/exportImage` is
  absent and `/export` returns a rendered PNG. `/identify` does return the modelled depth per point
  (da-DK decimal comma), which is enough for a test-property score.
* **The MST bulk drop is scriptable** — the Cerberus client at sftp.statens-it.dk answers a plain
  HTTP client: `POST /public/op/<id>/get_dir` lists (8 files, 3.49 GB) and `POST /public/op/<id>/zip/`
  downloads. `Oversvømmelsesfare.zip` (3.41 GB) is the depth-raster route if we ever need the grid.
* **Blocked on credentials:** DHM WCS and the bluespot tiles both need a Datafordeler key or service
  user; `.env` carries only `UDDSTAT_API_KEY`. The legacy `ftp.dataforsyningen.dk` /
  `download.dataforsyningen.dk` hosts no longer resolve. Nothing else waits on this.
* **Correction to the brief:** the 2024 risk-area group holds **26** sub-layers, not 25. Layer 33
  (Køge Bugt/København) is a single feature of 101.53 km², which does match.
* **Coast flag is free:** 76 of 99 kommuner are coastal, 9 of the metro 19, computed from
  `data/geo/kommuner.geojson` alone. Borderline cases are listed in the probe doc.
