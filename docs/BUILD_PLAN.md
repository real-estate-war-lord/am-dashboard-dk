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
- ~~Copenhagen bydele via `s30` as a third map level.~~ Done in v1.2: 67 kvarterer, 12 indicators, 2016–2026.
- Plandata kommuneplanrammer as a context layer (planned housing capacity).
- Portfolio module: `data/processed/portfolio.json` (schema in `src/app.js` header) — kept out of the public repo or anonymised; the map's "Own properties" toggle and the municipality table's portfolio columns switch on automatically when the file exists.

## Conventions

- English everywhere in code, docs and UI. Danish source names kept verbatim (almene, kommune, postnummer) where the Danish term is the precise one.
- One indicator = one entry in `config/indicators.json`; no numbers are hard-coded in `app.js`.
- Every processed number carries its period (`asof`) and the source's `updated` stamp so the Sources view is always honest.
- Values suppressed by the source (`..`) stay null and render as `–`; never imputed.
- Commit messages: `feat:`, `data:`, `fix:`, `docs:`.

---

## Roadmap after the first public release (2026-09-14)

Status: phases 0–5 done; live at https://real-estate-war-lord.github.io/am-dashboard-dk/ · every push to `main` deploys, the 3rd of each month refreshes data.

### Next three
1. **Rents (phase 4).** boligstat.dk private rent + Landsbyggefonden social rent → `data/external/*.csv`. Fills the two empty chips and gives the Kela-rent analogue. Manual, ~30 min/yr.
2. **Verification log.** 5 municipalities × 3 indicators + 1 Finans Danmark cell checked against statistikbanken.dk; especially EJ56 flats +15.8 % y/y and the single-household definition. Written into DATA_MAP §7.
3. **README for the public.** Screenshot, live link, what/why/how-to-run/how-to-cite, data-licence block.

### UI backlog (one push each)
- Compare mode: pin 2–5 municipalities/postal codes and show them side by side (table + small bars).
- Map legend with actual min/max values (as in the Finnish SVG version) instead of low/high.
- Postal-code level: label declutter at mid zoom; hide street-level merged codes' `°` noise.
- Market view: hero tiles for the *selected municipality* (price, supply, completions) in addition to national.
- Permalinks: encode indicator/mode/municipality in the URL hash so a view can be shared.
- Mobile layout (sidebar collapses; tables scroll).
- Dark theme variant of the palette.

### Data depth (phase 6)
- **BBR via Datafordeler GraphQL** (free key): dwelling size/age/tenure mix per postal code → real postnr-level structure indicators.
- ~~**Copenhagen bydele/roder** via `s30` as a third map level.~~ Done (v1.2). Next candidates below it: sogne (parishes, 2 097 polygons already vendored) once a parish-level statistic is chosen; BBR unit-level structure via Datafordeler.
- **Plandata kommuneplanrammer** as a context layer: planned housing capacity (plot ratio × area) per municipality.
- **Live mortgage yield** (Nationalbanken statbank or Finans Danmark LT10) to replace the retired DNRENTM bond series.
- **Vacancy**: BOL101 BEBO=2000 proxy + Landsbyggefonden ledige boliger.
- **Migration components** (BEV107): internal vs international net migration as separate chips.
- **Eurostat NUTS3 GDP per capita** for the 11 landsdele.

### Portfolio module (what makes it an AM tool)
- `data/processed/portfolio.json` (private, never committed): properties with address → DAR lookup → kommune + postnr + lat/lon.
- "Own properties" markers coloured by vacancy pressure (already wired in `app.js`); municipality table gains Properties/Units columns automatically.
- Rent benchmark: own DKK/m²/month × 12 vs boligstat private rent and LBF social rent for the same municipality → "gap to market" column and chip.
- Portfolio exposure view: share of units by municipality vs growth/price/supply → concentration risk.

### Engineering hygiene
- Unit tests for the calcs in `build_makro.py` (fixtures from real CSV rows).
- `make validate` in CI monthly (catches retired DST tables like PRIS111 → PRIS01).
- Datafordeler DAGI path (docs/GEO.md) exercised once before 2027-01-15 so the boundary refresh is proven.
- Semantic version tags; CHANGELOG per release.
