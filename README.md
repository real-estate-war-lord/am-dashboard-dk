# Macro Dashboard — Denmark (AM dashboard, Danish edition)

**Live:** https://real-estate-war-lord.github.io/am-dashboard-dk/

An open-data market map for residential asset management in Denmark: 36 indicators for all 98 municipalities and ~600 postal-code areas — demographics, income, jobs, housing stock, rents, owner-occupied prices, days on market, supply, construction and safety (reported crime) — plus a national macro panel (CPI, net price index, rent indices, house price index, interest rates, unemployment, GDP, forced sales). Every number comes from a public Danish source and is traceable back to the exact table and period.

![Macro map — private rental rent by municipality, 2026](docs/screenshot.png)

## What you get

- **Macro map** — choropleth by municipality (five quintile colour classes, legend on the map), zoom in for postal codes (and Copenhagen quarters); breadcrumb navigation, area search, grouped indicator selector with quick chips and a folded explanation (definition, source table, period, coverage, caveats), year selector 2016–2026. Popups show the selected indicator with its rank and four headline figures, link to the area page, the buildings layer and the chart generator, and fold all values underneath.
- **Area pages** — every municipality, postal code and Copenhagen quarter has its own page (`#area/<type>/<code>`): headline row (five key figures with y/y and rank), key-figure tiles by theme with sparklines against the median; trend chart vs municipality and median; context map with clickable neighbours; tabs for all indicators, the BBR housing stock and sub-areas; ↗ opens any figure in Charts.
- **Table** — everything side by side (municipalities / postal codes / quarters) with search, region filter, minimum population, sorting and CSV export.
- **Housing stock from BBR** — the building register itself, aggregated per postal code and Copenhagen quarter: tenure, unoccupied share, sizes, age, building type (free Datafordeler API key needed to refresh; the aggregated file is committed).
- **Buildings (Micro)** — inside a municipality, every residential building with 2+ dwellings as a dot: address, BFE property number, tenure, size, year built, rooms; find by address, filter and export. Loaded per municipality on demand.
- **Charts** — chart generator: indicator × areas × years, median line and Denmark reference line, PNG and CSV export, shareable URL; each indicator's axis starts at its first year (crime: 2007), rolling-quarter series can be shown quarterly, related indicators can be overlaid, and series breaks are marked.
- **Export data** (sidebar) — one long-format CSV of every level, indicator and year plus the macro series, ready for analysis in Claude, Python or Excel.
- **Test property** — paste a Google Maps link or a `lat, lon` pair and get a one-property Analysis sheet (`#analysis`): where it is (kommune · postal code · Copenhagen quarter), the area profile with a direction-aware percentile bar against every area of the same level, safety, every infrastructure project within 3 km with its computed distance, the public buildings and schools within 1 000 m, and the sources with their as-of stamps. The mini map carries the same layer pills as the Macro map — Infra projects · Public buildings · Buildings — with the same legends, filters and popups; its choropleth follows whichever headline tile is selected. Shareable URL (`&lay=`, `&ind=`, `&pub=`); the pin travels between the map and the sheet.
- **Market** — KPI tiles and series for the national picture.
- **Sources** — folded under Market: every table with its "updated" stamp, plus indicator definitions.

### Safety

Reported crime from Statistics Denmark (STRAF11, quarterly from 2007; STRAF22, annual) per municipality, by place of offence: all penal-code offences, violence, property crime and drug/weapons offences per 1,000 inhabitants, residential burglaries per 1,000 dwellings, the year-on-year change, and the share of penal-code reports that led to a charge. Counts are summed over the latest four quarters (they are not seasonally adjusted), ranks read "lower is better", and postal codes and Copenhagen quarters show their municipality's value (°) — there is no open crime statistic below municipality level. Charts show the full series from 2007, yearly or quarterly, against Denmark as a whole, with the 2013 change in the sexual-offence rules marked. Copenhagen's 67 quarters carry their own figures from Københavns Kommunes Tryghedsundersøgelse (reported crime per 1,000 inhabitants and the share of residents feeling safe in their neighbourhood, published per bydel, marked `^`). Reported ≠ solved, and drug/weapons figures mostly reflect police activity; see [`docs/DATA_MAP.md` §3.8](docs/DATA_MAP.md).

![Macro map — reported crime per 1,000 inhabitants by municipality, rolling 4 quarters to 2026 Q2](docs/screenshot-crime.png)

### Infrastructure pipeline

An *Infra projects* overlay on the map: 51 curated projects that will change accessibility — metro and light rail, motorways, bridges and tunnels, hospitals, BRT lines, campuses, state buildings and urban-development areas. Line style shows the status (study · decided · under construction · opened), a click opens the project's datasheet with its budget, opening year, length and the areas it serves, and the **Pipeline** view lists them all with filters and CSV export. Area cards show the three nearest upcoming projects. Budgets and years come from each project's own official source and are left empty when that source does not state them; geometry drawn by hand is marked as a schematic corridor. Method and sources: [`docs/INFRA.md`](docs/INFRA.md).

![Infrastructure overlay — planned metro, roads and development areas over the crime choropleth in Copenhagen](docs/screenshot-infra.png)

### Public buildings

A second overlay draws the public building stock from BBR: schools, daycare, institutions, health and culture buildings, coloured by category, with floor area, year built and address. Buildings with an **open building case** (permit ≤ 3 years) are drawn hollow and dashed — BBR's case data carries almost no completion dates, so the layer reports case activity, never a construction schedule. The legend doubles as a filter (category, existing vs open case) and the filter is part of the URL. Area cards gain a **PUBLIC** line whose segments open a filtered list. **Coverage: the Copenhagen metro set — København and 18 suburban municipalities, 7 517 buildings; other municipalities to follow.** Method and caveats: [`docs/PUBLIC_BUILDINGS.md`](docs/PUBLIC_BUILDINGS.md).

![Public buildings overlay — the Copenhagen metro set at zoom 10, large buildings and open cases](docs/screenshot-public.png)

### School quality

Every Education building that sits on a school's site carries that school's figures from **Uddannelsesstatistik.dk**: the FP9 grade average shown against its own municipality and against Denmark, the **socioeconomic reference** — the grade the ministry's model expects from the pupils' background — and whether the gap is statistically significant, pupil well-being, pupils and class size, over the three latest school years. A school datasheet gives the three-year table, the benchmarks, the four well-being sub-indicators and the buildings on its site. Filter the public layer down to **Education alone** and the markers switch to a five-step grade ramp with a matching legend; a school that publishes no grade — no 9th grade, or a cell the source suppressed — keeps the plain Education hue with a thin outline rather than the bottom bin, because those are not low-scoring schools. 364 schools in the Copenhagen metro set, 96 % of them placed on a BBR building. A grade average mostly tracks intake, which is exactly why the socioeconomic reference sits next to it everywhere it appears. Method, cube codes and the discretion rules: [`docs/SCHOOLS.md`](docs/SCHOOLS.md).

![School quality — Frederiksberg with the public layer filtered to Education, markers coloured by FP9 grade average](docs/screenshot-schools.jpg)

### Test property and the Analysis sheet

Paste a Google Maps link — or a plain `55.67610, 12.56830` — into the box on the map toolbar and the dashboard pins that point, drills to its municipality at postal-code level and draws 500 / 1 000 / 1 200 m rings around it; *Analyse ›* opens the **Analysis sheet** (`#analysis?a=<lat>,<lon>`), one address read against every layer at once: where it is (kommune · postal code · Copenhagen quarter, from the kommune's own boundary rings rather than from its postal code, so a Frederiksberg address is not labelled København), the full area profile with a direction-aware percentile bar against every area of the same level, safety, every infrastructure project within 3 km with its distance **computed from the geometry** — a station point, the nearest point of a line, 0 m inside a development area — the public buildings and schools within 1 000 m including the ones across a municipality border, and a sources card built from what that pin actually read. The mini map carries the same three layer pills as the Macro map with the same legends, filters and popups, and its choropleth follows whichever headline tile you click. The link is the state: `&lay=`, `&ind=`, `&pub=` and the pin itself travel in it, so *Copy link* reproduces the view and Back returns to the map with the pin intact. It all runs in the browser — the link is parsed, never followed, which is also why short `maps.app.goo.gl` links are refused by name instead of guessed at, and why the box says the location is stored only in the page URL. **Coverage: national, except public buildings and schools (Copenhagen metro set).** Method, formats, distances and caveats: [`docs/ANALYSIS.md`](docs/ANALYSIS.md).

![Analysis sheet — a test property in 2450 København SV with the infra and public-building overlays on the mini map](docs/screenshot-analysis.jpg)

### Services — shops, food, pharmacies and transport stops

A third map overlay beside *Infra projects* and *Public buildings*: **44 181 points across all 99 municipalities** — groceries, restaurants/cafés/bars/takeaway, pharmacies, and every metro, S-train, rail, light-rail and bus stop in the national timetable. Shops and eating places come from the **Geofabrik OpenStreetMap extract** (nodes *and* building polygons — 46 % of Danish supermarkets are mapped as a polygon, so a node-only read loses half of them); stops come from **Rejseplanen's static GTFS**, with the modes resolved through `stops → stop_times → trips → routes` because `stops.txt` does not carry them, and platforms clustered into stations by name and mode because the feed ships no station hierarchy at all. The legend doubles as the filter — Groceries · Food & drink · Pharmacy · Transport, the last split into *Rail & metro* and *Bus* — and the filter travels in the URL. Performance is the shape of the thing: each category has a zoom floor (rail & metro from 10, groceries and pharmacies from 13, food and buses from 14) with a *"Zoom in to see …"* hint below it, only the viewport is drawn, and per-municipality files load only for bounding boxes actually in view. Worst case measured — zoom 14 over Nørrebro with every category on — is 3 346 markers rebuilt in 15.6 ms, so there is no clustering library and no CDN dependency. **Coverage is national, but OpenStreetMap density is not uniform: an empty rural postal code may mean "nothing mapped", not "nothing there"**, which is why there are no area-level service indicators. Method, licences and caveats: [`docs/SERVICES.md`](docs/SERVICES.md); how the sources were chosen: [`docs/SERVICES_PROBE.md`](docs/SERVICES_PROBE.md).

![Services overlay — Nørrebro at zoom 15 with groceries, food & drink, pharmacies and transport stops over the growth choropleth](docs/screenshot-services.jpg)

### Population outlook

Where a municipality — or a Copenhagen quarter — is **projected** to be in 2040, from the publishers' own runs. Ten indicators per area from **Danmarks Statistik's `FRKM126`** (2026 vintage): total growth to 2040 and to 2031, the change per 1 000 inhabitants per year, the absolute change in persons, and the 0–5, 6–16, 20–34 and 80+ cohorts, with 20–34 also shown **against Denmark's own −7.1 %** — because the national cohort shrinks over the window, only 7 of 98 municipalities gain any at all, and the relative map is the one that reads. Copenhagen's 67 quarters get the same ten again from **Københavns Kommune's own `KKFR2026`**, kept in its own file and its own view: the two runs are **never spliced**, and where both describe the same city the gap is stated (DST +5.9 %, KK +8.3 % by 2040) rather than averaged away. Beside them sits **net dwelling additions** from `BOL101` — what the stock actually did, a measurement, in its own unit, with nothing computed between the two. The colour model is diverging and centred on zero because growth and decline are different phenomena, and the indicators carry a `neutral` direction: a shrinking municipality is not failing, so nothing here is coloured good-to-bad or ranked best-to-worst. Area pages show the observed population as a solid line and the projection dashed to 2040 with a *today* marker, so a projected point never reads as an actual; Copenhagen quarters add one line of the forecast's own past accuracy. **Projections are scenarios, not guarantees** — and the housing-gap indicator that would have needed an assumption of ours is deliberately not here. Method, sources and what is excluded: [`docs/FORECAST.md`](docs/FORECAST.md).

![Population outlook — young adults 20–34 projected to 2040 against Denmark's own change, by municipality](docs/screenshot-outlook.jpg)

## Data sources (all free, no key unless noted)

| layer | source | tables |
|---|---|---|
| Population, households, income, unemployment, education, ancestry, housing stock, housing benefit, construction | Statistics Denmark, StatBank API | FOLK1A, POSTNR1, FAM55N, INDKP101, IFOR22, AUP01, HFUDD11, FOLK1E, BOL101, BOL106, BOST63, BYGV33 |
| Realised prices DKK/m², asking-price discount, days on market, homes for sale | Finans Danmark, Boligmarkedsstatistikken (via `api.statbank.dk/v1/s20`) | BM010, BM011, BM030, BM031, UDB010 |
| Private rental rent DKK/m²/yr | Social- og Boligstyrelsen, boligstat.dk (housing-benefit register × BBR) | Huslejestatistik 2026 |
| Social housing rent DKK/m²/yr | Landsbyggefonden, Huslejestatistik 2026 | Tabel 7 |
| Reported crime (place of offence) and charges | Statistics Denmark, StatBank API | STRAF11, STRAF22 |
| Infrastructure projects: alignments (Greater Copenhagen) | Plan- og Landdistriktsstyrelsen, Fingerplan 2019 (WFS) | metro, letbane, rail, motorway and study corridors |
| Infrastructure projects: budgets and opening years | Transportministeriet, *Status for anlægs- og byggeprojekter* (Anlægsstatus) | half-yearly PDF |
| Hospitals, BRT, campuses, state buildings | the regions, Movia, Vejdirektoratet, municipalities, Bygningsstyrelsen | project pages, agendas and annual reports |
| Infrastructure geometry outside Greater Copenhagen | OpenStreetMap via Overpass | © OpenStreetMap contributors (ODbL) |
| Public buildings (schools, daycare, health, culture) | BBR via Datafordeler (free API key) | anvendelse 410–449; addresses from DAR; names from OpenStreetMap |
| School quality: FP9 grades, socioeconomic reference, well-being, pupils, class size | Børne- og Undervisningsministeriet / STIL, Uddannelsesstatistik.dk (free API key) | GS cubes KARA/KARAGNS, KARA/KARADM, TRIV/TRIVIND, ELEV/ELEVEX, OVER/OVERSKO; Institutionsregisteret for location and type |
| Copenhagen quarters: reported crime and feeling safe, per bydel | Københavns Kommune, Tryghedsundersøgelsen (Epinion) / Københavns Politi | annual report (PDF) |
| Macro series | Statistics Denmark incl. Danmarks Nationalbank mirrors | PRIS01, PRIS04, HUS1, EJ56, DNRENTM, AUS07, NKN1, TVANG1 |
| Boundaries | Klimadatastyrelsen, DAGI (via DAWA, vendored 2026-09-14) | kommuner, postnumre, sogne |

Full catalogue, indicator mapping and verification log: [`docs/DATA_MAP.md`](docs/DATA_MAP.md).

## Run it yourself

Python 3.10+, no packages required (`shapely` and `openpyxl` optional for geometry and the LBF import).

```bash
git clone https://github.com/real-estate-war-lord/am-dashboard-dk.git && cd am-dashboard-dk
make validate   # check every table/value code against the live API
make fetch      # ~36 pulls to data/raw (no key)
make build      # raw → data/processed → dist/index.html
make serve      # http://localhost:8080
make test       # unit tests (python + node --test)
```

`make geo` re-vendors boundaries (DAWA closed 2026-10-01 — see `docs/GEO.md` for the Datafordeler route). Rents are updated yearly with `scripts/import_lbf.py` and `scripts/import_boligstat.py` (see `data/external/SOURCES.md`).

Every push to `main` rebuilds and deploys to GitHub Pages; on the 3rd of each month the workflow also refreshes the data.

## Documentation

- `docs/DATA_VERIFICATION_GUIDE.pdf` — every indicator, its source table and codes, the computation, one-click links that reproduce the source cells, and a worked re-check of 28 figures against the live sources (22 Sep 2026).

| doc | read it when |
|---|---|
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | you are about to run something — steps, expected output, troubleshooting |
| [`docs/DATA_FOLDERS.md`](docs/DATA_FOLDERS.md) | where a file belongs, what is committed, how a number is traced to its source |
| [`docs/DATA_MAP.md`](docs/DATA_MAP.md) | source catalogue, Finnish → Danish indicator mapping, verification log |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | phases done and the roadmap |
| [`docs/SCHOOLS.md`](docs/SCHOOLS.md) | school quality — cube codes, the BBR join, discretion rules, cadence |
| [`docs/ANALYSIS.md`](docs/ANALYSIS.md) | the test-property pin and the Analysis sheet — link formats, kommune resolution, distances, coverage, privacy |
| [`docs/SERVICES.md`](docs/SERVICES.md) | the services layer — sources, categories, zoom floors, clustering rules, refresh |
| [`docs/FORECAST.md`](docs/FORECAST.md) | the population outlook — sources, the hard-data rule, what is shown and what is research |
| [`docs/GEO.md`](docs/GEO.md) | boundary pipeline |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed in which version |

`config/indicators.json` is the single registry: key, label, unit, table, query, calculation, native geography, colour. Adding an indicator is one entry there — no code changes.

## Design

The UI is a port of a Finnish asset-management dashboard's market section: same palette, typography, choropleth colour model and interaction pattern, rebuilt in English for Danish data. Leaflet (BSD-2) for the map, OpenStreetMap tiles.

## Caveats worth knowing

- Rent levels come from housing-benefit households and skew low; market asking rents are typically higher.
- Cooperative dwellings (andelsboliger) count as rented in DST's tenure statistic.
- Finans Danmark suppresses cells with few trades; small municipalities and most rural postal codes show no price.
- Street-level postal codes in central Copenhagen (1000–1999) are merged by name.
- Copenhagen quarters (kvarterer) use Københavns Kommune's own statbank (`s30`); unemployment there exists only per district (bydel) and is repeated on each quarter of the district.
- Copenhagen quarter crime and safety figures come from the city's own annual survey (police figures for the previous calendar year), so they are not comparable with the national crime indicators.
- The public-buildings layer covers the Copenhagen metro set only, and BBR is owner-reported: floor area, use and status are as reported, not as surveyed. An open building case is not a construction schedule.
- The outlook is a projection, not a measurement: it carries each area's recent fertility, mortality and migration forward and contains no housing programme, so a large planned development is not in it. DST's run and Københavns Kommune's run disagree by 2.2 % for Copenhagen by 2040 and are never combined.
- The services layer is as complete as OpenStreetMap is in that place, and that varies: Copenhagen is densely mapped, rural Jutland is not. Transport stops are the live timetable, so a stop is where you can catch something, not how often.
- The Analysis sheet's distances are to mapped geometry, not walking routes, and its infra list is the curated layer — an existing station that is not a project in it will not appear. Short `maps.app.goo.gl` links cannot be resolved in a browser; paste the long URL.
- The infrastructure layer is a curated list, not a register: it holds the projects named in `docs/INFRA.md` and nothing else, and ten of its geometries are schematic corridors drawn by hand.
- Crime figures are reported offences by place of offence, per municipality only; they exclude the traffic law, break in 2007 and on 1 July 2013 (sexual offences), and DST writes suppressed cells as 0, so a zero on a small island may be suppressed.

## Licence and attribution

Code: MIT. Data: each source's own terms (all permit reuse with attribution). When you reuse the data or the map, credit: *Danmarks Statistik (incl. crime statistics STRAF11/STRAF22) · Indeholder data fra Klimadatastyrelsen (BBR, DAR) · Københavns Kommune, Tryghedsundersøgelsen / Københavns Politi · Plan- og Landdistriktsstyrelsen (Fingerplan 2019) · Transportministeriet (Anlægsstatus) · the regions, Movia and Bygningsstyrelsen for their own projects · © OpenStreetMap contributors (ODbL) · Finans Danmark, Boligmarkedsstatistikken · Social- og Boligstyrelsen, boligstat.dk · Landsbyggefonden · Indeholder data fra Klimadatastyrelsen (DAGI) · Danmarks Nationalbank · Kilde: Uddannelsesstatistik.dk (Børne- og Undervisningsministeriet / STIL), retrieved 2026-09-23 · Institutionsregisteret, STIL · Danmarks Statistik FRKM126 / FRDK126 (municipal population projection) · Københavns Kommune KKFR2026 (befolkningsfremskrivning).*

The services layer adds two of its own, carried on every popup, in the map footer while the layer is on, and in Market › Sources:

- **© OpenStreetMap contributors, ODbL** — shops, eating places and pharmacies (Denmark extract processed by Geofabrik GmbH)
- **Rejseplanen, CC BY 4.0** — metro, S-train, rail, light-rail and bus stops

To cite: *AM Dashboard — Denmark Edition, v1.0 (2026), https://github.com/real-estate-war-lord/am-dashboard-dk.*
