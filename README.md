# AM Dashboard — Denmark Edition

Open-data macro & market layer for a residential asset-management dashboard, built for the Danish market. Same design and logic as the Finnish edition (choropleth map with indicator chips, municipality → postal-code drill-down, comparison tables, source notes) — but every number comes from **Danish open sources**, and the code base is English.

## Documentation

| doc | read it when |
|---|---|
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | you are about to run something — step by step, expected output, troubleshooting |
| [`docs/DATA_FOLDERS.md`](docs/DATA_FOLDERS.md) | you wonder where a file belongs, what is committed, how a number is traced to its source |
| [`docs/DATA_MAP.md`](docs/DATA_MAP.md) | you need the source catalogue, indicator mapping (FI → DK), verification log |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | you want the phases from empty repo to public GitHub Pages |
| [`docs/GEO.md`](docs/GEO.md) | boundaries: DAWA now, Datafordeler after 2026-10-01 |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed in which version |

## ⚠ Do this before 1 October 2026

Klimadatastyrelsen closes the DAWA API on **2026-10-01 10:00**. The boundary polygons the map needs (postal codes, municipalities, parishes) are vendored from it:

```bash
python scripts/fetch_geo_dawa.py --simplify 0.0005   # shapely optional
git add data/geo && git commit -m "Vendor DAGI boundaries (DAWA, $(date +%F))"
```

After that date, boundaries come from Datafordeler (free API key, GPKG → `ogr2ogr`), see `docs/DATA_MAP.md` §2.

## Data sources (all free, no key unless noted)

| layer | source |
|---|---|
| Demographics, income, jobs, education, housing stock, housing benefit, construction | Statistics Denmark StatBank API |
| Prices, sales, days on market, supply (municipality + postal code) | Finans Danmark Boligmarkedsstatistik via `api.statbank.dk/v1/s20` |
| Rents | boligstat.dk (private, from housing-benefit register × BBR), Landsbyggefonden (social housing), DST rent index |
| Boundaries | DAGI (Klimadatastyrelsen) |
| Buildings & units | BBR via Datafordeler GraphQL (free key) |
| Copenhagen sub-areas | Københavns Kommune statbank via `api.statbank.dk/v1/s30` |
| Macro | DST, Danmarks Nationalbank mirrors, Eurostat NUTS3 |

## Run it

```bash
make validate   # 1. check config codes against the live API (fix TODO_* codes first)
make geo        # 2. vendor DAGI boundaries — before 2026-10-01
make fetch      # 3. pull ~40 tables to data/raw (no key)
make build      # 4. raw → processed → dist/index.html
make serve      # 5. http://localhost:8080
```

`make fixture` renders the design with synthetic numbers (dist/fixture.html) — for development only.

```
scripts/fetch_geo_dawa.py   →  data/geo/*.geojson
scripts/fetch_statbank.py   →  data/raw/*.csv (+ .meta.json with "updated" stamps)
scripts/build_makro.py      →  data/processed/makro.json   (municipalities + postal-code areas)
scripts/build_market.py     →  data/processed/market.json  (national macro series)
scripts/build_dashboard.py  →  dist/index.html             (self-contained, opens from disk)
```

Plan and phases: [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

`config/indicators.json` is the single registry: key, label, unit, table, query, native geography level, choropleth hue.

## Attribution

Map footer and source notes must carry: *Danmarks Statistik · Finans Danmark, Boligmarkedsstatistikken · Social- og Boligstyrelsen, boligstat.dk · Landsbyggefonden · Indeholder data fra Klimadatastyrelsen (DAGI) · Danmarks Nationalbank.*

## Status

v0.2 — data map, pipeline scripts and the dashboard template (design ported from the Finnish edition). No real data built yet — run the pipeline.
