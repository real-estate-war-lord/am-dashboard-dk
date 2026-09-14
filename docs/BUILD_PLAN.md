# Build plan — from empty repo to a public GitHub dashboard

**Operating model.** The pipeline runs on your own computer (Python 3.10+, no extra packages required; `shapely` optional). Claude writes and fixes code; you run the network steps in Terminal because the assistant's shells have no access to Danish APIs; you paste the output back and the next iteration fixes whatever broke. Every step is idempotent and re-runnable.

```
config/indicators.json ──► validate_config.py ──► fetch_statbank.py ──► data/raw/*.csv
data/geo/*.geojson     ◄── fetch_geo_dawa.py                                   │
                                                          build_makro.py  ◄────┘
                                                          build_market.py
                                                          build_dashboard.py ──► dist/index.html ──► GitHub Pages
```

## Phase 0 — Repository (day 1)

- [ ] Unzip the skeleton into your project folder, `git init`, first commit.
- [ ] Create the GitHub repository (public), push. Settings → Pages → Source: *GitHub Actions*.
- [ ] `make fixture` → open `dist/fixture.html` to confirm the design renders on your machine (synthetic numbers, never publish).

**Definition of done:** repo public, fixture renders, licence and attribution in place.

## Phase 1 — Geometry (before 1 Oct 2026, hard deadline)

- [ ] `make geo` → `data/geo/{kommuner,postnumre,sogne,landsdele,regioner}.geojson` + `ATTRIBUTION.txt`.
- [ ] Sanity: 98 municipalities, ~600 postal codes, every postal code has `kommuner[0]`.
- [ ] Commit the simplified GeoJSON (raw copies stay out of git).

Fallback after the deadline: Datafordeler DAGI Fildownload → `ogr2ogr` (docs/GEO.md).

## Phase 2 — Code validation (1 session)

- [ ] `make validate` → paste the output to Claude. Known unknowns marked `TODO_*` in `config/indicators.json`: EJ56 flat-index codes, DNRENTM instrument codes, BYGV33 phase code, UDB010 all-Denmark code, IFOR22 decile variable, FOLK1E origin codes, INDKP101 `KOEN`.
- [ ] Config corrected until `validate` prints only ✓.

## Phase 3 — First data build (1 session)

- [ ] `make fetch` (≈40 small pulls, no key, a minute or two).
- [ ] `make build` → read the ⚠ warnings; fix calcs; rebuild.
- [ ] `make serve` → http://localhost:8080 — real Danish map.
- [ ] Spot-check 5 municipalities × 3 indicators against the StatBank web UI (statistikbanken.dk) and note the check in `docs/DATA_MAP.md` §7.

## Phase 4 — Rents (external files)

- [ ] boligstat.dk private rent DKK/m² by municipality → `data/external/rent_private.csv` (`kommune;value`). Annual; scrape or copy.
- [ ] Landsbyggefonden `basistabeller-for-huslejestatistik-2026.xlsx` → `data/external/rent_social.csv`.
- [ ] Rebuild; both appear as chips and table columns with their caveats.

## Phase 5 — Publish (1 session)

- [ ] Commit `data/processed/*.json` and `dist/index.html`; push. GitHub Action deploys Pages and refreshes monthly (`.github/workflows/refresh.yml`).
- [ ] README: screenshot, live link, how to run, attribution block.
- [ ] Tag `v1.0`.

## Phase 6 — Depth (ongoing)

- BBR via Datafordeler GraphQL (free key): dwelling size/age/tenure mix at postal-code level → new postnr-level indicators.
- Copenhagen bydele via `s30` as a third map level.
- Plandata kommuneplanrammer as a context layer (planned housing capacity).
- Portfolio module: `data/processed/portfolio.json` (schema in `src/app.js` header) — kept out of the public repo or anonymised; the map's "Own properties" toggle and the municipality table's portfolio columns switch on automatically when the file exists.

## Conventions

- English everywhere in code, docs and UI. Danish source names kept verbatim (almene, kommune, postnummer) where the Danish term is the precise one.
- One indicator = one entry in `config/indicators.json`; no numbers are hard-coded in `app.js`.
- Every processed number carries its period (`asof`) and the source's `updated` stamp so the Sources view is always honest.
- Values suppressed by the source (`..`) stay null and render as `–`; never imputed.
- Commit messages: `feat:`, `data:`, `fix:`, `docs:`.
