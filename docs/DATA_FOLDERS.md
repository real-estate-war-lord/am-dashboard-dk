# Data folders — what lives where, and why

The rule: **data flows one way, left to right, and every folder has exactly one producer.**

```
config/            hand-edited      → the registry: what to fetch, how to compute, how to show
data/geo/          fetch_geo_dawa   → boundary polygons (committed, simplified)
data/raw/          fetch_statbank   → untouched API pulls, dated (CSV not committed; .meta.json committed)
data/external/     hand-filled      → the few series with no API (rents), as small CSVs (committed)
data/processed/    build_*          → the JSON the dashboard reads (committed)
dist/              build_dashboard  → the single-file dashboard (index.html committed; fixture.html never)
```

| folder | producer | consumer | in git? | naming |
|---|---|---|---|---|
| `config/indicators.json` | you / Claude | every script | yes | one registry, no other config files |
| `data/geo/<layer>.geojson` | `scripts/fetch_geo_dawa.py` | `build_makro.py` | **yes** (simplified, ~few MB) | `kommuner`, `postnumre`, `sogne`, `landsdele`, `regioner` |
| `data/geo/raw/` | same script | nobody (archive) | no | full-precision originals |
| `data/geo/ATTRIBUTION.txt` | same script | README / map footer | yes | required by the DAGI licence |
| `data/raw/<db>_<TABLE>_<YYYY-MM-DD>.csv` | `scripts/fetch_statbank.py` | `build_makro.py`, `build_market.py` | no (regenerable; can be large) | `dst_FOLK1A_2026-09-15.csv`, `s20_BM011_2026-09-15.csv` — the newest date wins |
| `data/raw/<db>_<TABLE>.meta.json` | same script | builders (labels), Sources view (freshness) | yes | one per table, overwritten on every fetch |
| `data/external/<indicator>.csv` | you, by hand, once a year | `build_makro.py` | yes | `rent_private.csv`, `rent_social.csv`; format `kommune;value`; header row required |
| `data/external/SOURCES.md` | you | readers | yes | where each file came from, URL, date, who copied it |
| `data/processed/makro.json` | `scripts/build_makro.py` | `build_dashboard.py` | yes | municipalities + postal-code areas + indicator definitions + provenance |
| `data/processed/market.json` | `scripts/build_market.py` | `build_dashboard.py` | yes | national macro series |
| `data/processed/portfolio.json` | (later, private) | `build_dashboard.py` | **no** — never in the public repo | schema in `src/app.js` header |
| `dist/index.html` | `scripts/build_dashboard.py` | GitHub Pages, your browser | yes | the deliverable |
| `dist/fixture.html` | `make fixture` | you, for design checks | no | synthetic numbers |

## Provenance chain

Every number on the screen can be traced back:

1. **Screen** → indicator label + ⓘ tooltip (definition, source, caveat) — from `config/indicators.json`.
2. **`data/processed/makro.json`** → `indicators[].asof` gives the period used per geography, `meta.sources[].asof` gives the source's own "updated" date.
3. **`data/raw/*.meta.json`** → the full StatBank `tableinfo` at fetch time (variables, codes, update timestamp).
4. **`data/raw/*.csv`** → the exact rows the calc consumed (regenerate with `make fetch` on any date).

## What never goes into git

`.env` (API keys), `data/raw/*.csv`, `data/geo/raw/`, `dist/fixture.html`, `tests/fixture_*.json`, anything portfolio-related. See `.gitignore`.

## Refresh policy

| cadence | what | why |
|---|---|---|
| monthly (Action) | `make fetch && make build` | AUP01, UDB010, PRIS01, DNRENTM are monthly |
| quarterly | check `make validate` still passes | DST occasionally retires or renames tables (PRIS111 → PRIS01 happened in 2026) |
| yearly | `data/external/*.csv` from boligstat.dk and LBF | published once a year |
| once, before 2026-10-01 | `make geo` | DAWA closes; afterwards Datafordeler (docs/GEO.md) |
