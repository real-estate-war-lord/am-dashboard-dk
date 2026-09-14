# AM Dashboard — Denmark Edition: Open Data Map

**Status:** v0.1 · 2026-09-14 · research & verification round complete, no data ingested yet
**Scope:** the *Macro / Market* layer of the dashboard (the Finnish edition's `makro` view plus a Denmark-specific market panel). Portfolio data (rent roll, lettings, capex, etc.) is out of scope for this document — it comes from the owner's own systems and is joined in later.
**Principle:** same design and logic as the Finnish edition (choropleth map with an indicator chip row, municipality → sub-area drill-down, comparison tables, source notes), but every number comes from **Danish open sources**. Nothing is carried over from the Finnish data.

---

## 0. TL;DR — what the Danish edition can be built on

| Layer | Source | Access | Geography | Verified |
|---|---|---|---|---|
| Demographics, income, jobs, education, housing stock, housing benefit, construction | **Statistics Denmark StatBank API** (`api.statbank.dk/v1`) | REST, no key, CSV/JSON-stat | 98 municipalities; population also by **postal code (POSTNR1)**, parish (SOGN1), urban area (BY1) | ✅ live pulls |
| Owner-occupied prices, sales, days on market, supply | **Finans Danmark Boligmarkedsstatistik** via the same API, sub-database **`s20`** | REST, no key | 98 municipalities **and 471 postal codes** (quarterly); municipalities monthly | ✅ live pulls |
| Rent levels | **boligstat.dk** (Social- og Boligstyrelsen) private-rental DKK/m² (built from the housing-benefit register × BBR — the exact analogue of the Finnish *Kela-vuokra*) + **Landsbyggefonden Huslejestatistik** (social housing, Excel) + DST rent index **HUS1** | static pages / Excel / API | municipality | ✅ docs, ⚠ data pages need scraping |
| Boundaries (postal codes, municipalities, parishes) | **DAGI** — today via DAWA GeoJSON, after 1 Oct 2026 via Datafordeler | REST today; API key later | polygons | ✅ live pulls · **⚠ DAWA closes 2026-10-01 10:00** |
| Building/unit register | **BBR** via Datafordeler GraphQL v3 | free API key (email sign-up) | every building & unit | ✅ docs |
| Copenhagen sub-areas | **Københavns Kommune statbank** via sub-database **`s30`** | REST, no key | 10 bydele / ~400 roder | ✅ catalogue |
| Macro (CPI, net price index, rates, GDP, HPI) | DST + Danmarks Nationalbank mirror tables (DNRENTM etc.) + Eurostat NUTS3 | REST, no key | national / region / province | ✅ |
| Planning & zoning | **Plandata.dk WFS** (kommuneplanrammer, lokalplaner) | WFS, JSON, no key | polygons | ✅ capabilities |

**What is *not* openly available in Denmark** (and how the Finnish edition's equivalents map): private asking rents at postal-code level (BoligPortal / Boligsiden / husleje.dk are proprietary), owner names (EJF is restricted), energy-label bulk data (Energistyrelsen issues credentials on request), income/education below municipality level (DST sells it as *Nøgletal på postnumre*).

---

## 1. Indicator map — Finnish `makro` view → Danish equivalent

The Finnish `MAKRO_IND` list drives the chip row, the choropleth and both tables. Each indicator is re-sourced below. `geo` = finest open geography. Codes are DST table codes unless stated.

| # | FI key | FI indicator (source) | DK indicator | DK source & query | geo | cadence / latest |
|---|---|---|---|---|---|---|
| 1 | `growth` | Population growth %/yr (Paavo 2020→2025) | Population growth %/yr | `FOLK1A` (quarterly, y/y same quarter) for municipalities; `POSTNR1` (1 Jan, annual) for postal codes; `BEV107` gives ready-made components (births, deaths, internal & international net migration) | kommune, **postnr**, sogn (`SOGN1`) | Q · 2026Q3 / annual · 2026 |
| 2 | `income` | Median disposable income of household-dwelling units (Paavo) | Disposable income — average per person (`INDKP101`, ENHED=116, INDKOMSTTYPE=100) and **median equivalised** (`IFOR22`, 5th decile bound) | DST | kommune (postnr only as paid product) | annual · 2024 |
| 3 | `young` | Young adults 20–34 % | Share aged 20–34 | `FOLK1A` single-year ages (kommune); `POSTNR1` 5-yr bands 20-24/25-29/30-34 (postnr) | kommune, **postnr** | Q / annual |
| 4 | `yks` | Single-person households % | Single-person households % of households | `FAM55N` HUSTYP M+K (or HUSSTØR=1) / total; `BY4` for urban areas | kommune, byområde | annual · 2026 |
| 5 | `kela` | Housing-allowance recipients % of households (Kela) | Housing-benefit households % | `BOST63` (YDELSESTYPE 1000 all / 1010 boligsikring ordinary rental, ENHED 3000 households, MND=012) ÷ `FAM55N` total households | kommune | annual w/ monthly detail · 2025 |
| 6 | `kelarent` | Kela average rent €/m² of benefit recipients, free-market stock | **Private rental rent DKK/m²/yr** — boligstat.dk, computed by the ministry from *Boligstøtteregister × BBR* (87 % coverage of private rentals in ≥3-unit buildings, 2015–2025). Companion: **Landsbyggefonden** social-housing rent DKK/m²/yr by municipality (Excel), and `BOST63` ENHED 3010/3030 average & median benefit amount | boligstat.dk (scrape), lbf.dk (xlsx) | kommune (× construction period) | annual · 2025 / 1 Jan 2026 |
| 7 | `vuok` | Renter households % | Rented dwellings % of occupied stock | `BOL101` UDLFORH=LEJ ÷ (EJ+LEJ), BEBO=1000; split by EJER (20 almene, 41 andels, 10/30 private) | kommune | annual · 2026 |
| 8 | `tyott` | Unemployment rate % | Registered unemployment % of labour force | `AUP01` (monthly provisional), `AUP02` final | kommune | monthly · 2026M07 |
| 9 | `kork` | Tertiary education % of 18+ | Higher education % of 15–69 | `HFUDD11` (H40+H50+H60+H70+H80) ÷ total, or long-cycle only (H60+H70+H80) | kommune | annual · 2025 |
| 10 | `kt` | Apartment (multi-storey) share of dwellings | Multi-dwelling buildings share | `BOL101` ANVENDELSE=140 ÷ all dwellings | kommune | annual · 2026 |
| 11 | `vk` | Foreign-language speakers % | Immigrants + descendants % of population | `FOLK1C`/`FOLK1E` HERKOMST ≠ Danish origin; `KMSTA001` at parish level | kommune, sogn | Q · 2026Q3 |
| 12 | `akoko` | Average dwelling size m² (table only) | Average m² per dwelling | `BOL106` | kommune | annual · 2026 |

### 1b. Denmark-only indicators worth adding to the chip row

These have no Finnish counterpart because Finland has no open equivalent, but they are the strongest data in the Danish stack:

| key | indicator | source | geo | cadence |
|---|---|---|---|---|
| `price_m2` | Realised price DKK/m², owner-occupied flats (ejerlejligheder) | `s20/BM011` PRIS20=REAL, EJKAT20=Ejerlejlighed | **postnr** (471) / kommune (`BM010`) | quarterly · 2026K1 |
| `discount` | Asking → realised price discount % | `(UDBUD − REAL)/UDBUD` from `BM010/011` | postnr / kommune | quarterly |
| `dom` | Days on market of sold flats | `s20/BM031` (postnr) / `BM030` (kommune) | postnr / kommune | quarterly |
| `supply` | Homes for sale (count) & asking DKK/m² | `s20/UDB010`, `UDB020`, `UDB030` (time on market) | kommune | **monthly** · 2026M08 |
| `pipeline` | Dwellings permitted / started / completed, by builder type (private, almene, andel) | `BYGV33` | kommune | quarterly · 2026Q2 |
| `almene` | Social housing share of dwellings | `BOL101` EJER=20 ÷ all | kommune | annual |
| `vacancy` | Dwellings without registered residents (vacancy proxy — includes 2nd homes/renovation, flag it) | `BOL101` BEBO=2000 | kommune | annual |
| `forced` | Forced sales (tvangsauktioner) | `TVANG3` (kommune, annual), `TVANG1` (national, monthly) | kommune | annual · 2025 |
| `rent_idx` | Rent index, private rental 2021=100, y/y % | `HUS1` EJENDOMSKATE=552, TAL=310 | DK + 5 regions | quarterly · 2026Q2 |
| `benefit_avg` | Average housing-benefit DKK/month | `BOST63` ENHED=3010 | kommune | annual |

---

## 2. Geography model

The Finnish edition uses two levels: municipality (`kunnat`, 8) and postal-code area (`areas`, 220 polygons with `ring`). Denmark supports three, and the data availability differs by level — this drives the drill-down logic:

| level | count | polygon source | which indicators exist here |
|---|---|---|---|
| **Kommune** (municipality) | 98 | DAGI `kommuneinddeling` (DAWA: `/kommuner?format=geojson`) | *everything* in §1 and §1b |
| **Postnummer** (postal code) | ~600 polygons (471 with price data) | DAGI `postnumre` (DAWA: `/postnumre?format=geojson`) | population, growth, age bands (`POSTNR1`); price/m², sales, days on market (`BM011/021/031`) |
| **Sogn** (parish) | ~2,150 | DAGI `sogneinddeling` (DAWA: `/sogne?format=geojson`) | population & age (`SOGN1`), ancestry (`KMSTA001`), vital stats (`KMSTA003`) |
| Copenhagen bydel / rode | 10 / ~400 | Københavns Kommune open data (opendata.dk, GeoJSON) | dwellings by tenure/size/year (`s30/KKBOL1-4`), population (`KKBEF1/3`), households (`KKHUS1`) |

**Design consequence:** keep the Finnish zoom-based level switch (`zoom ≥ 11 → micro`), but because most socio-economic indicators stop at municipality level, colour postal-code polygons **by their municipality's value** (exactly what the Finnish `lfLayers()` already does with `byK[a.kunta]`), and switch to the polygon's own value only for the indicators that exist at that level (`growth`, `young`, `price_m2`, `discount`, `dom`). Mark the fallback with the same `°` convention the Finnish `vksrc` flag uses. Postal codes that span two municipalities (e.g. 2200 København N spans København + Frederiksberg) need a dominant-municipality mapping — `POSTNR1` labels list the municipalities in the value text.

**Codes:** DST uses 3-digit municipality codes (`101` København … `851` Aalborg); DAGI uses 4-digit (`0101`). Parish code is the same 4-digit `kode` in both. Postal code is the plain 4-digit `nr`.

### ⚠ Boundary data — action required before 1 October 2026

Klimadatastyrelsen closes **DAWA in its entirety on 1 Oct 2026 at 10:00**. After that the only official route is the modernised **Datafordeler** (GraphQL / file download, free API key, EPSG:25832 only, no GeoJSON output). Plan:

1. **Now:** run `scripts/fetch_geo_dawa.py` → commits `data/geo/{kommuner,postnumre,sogne,landsdele,regioner}.geojson` (WGS84, simplified to ~50 m tolerance for the browser; keep raw copies too). Licence: *Vilkår for brug af frie geografiske data* — free reuse incl. redistribution; attribution string `"Indeholder data fra Klimadatastyrelsen, DAGI, hentet <date>"` goes in the map footer.
2. **Later refresh:** Datafordeler → *DAGI Fildownload* (GPKG) → `ogr2ogr -t_srs EPSG:4326 -f GeoJSON`. Requires a Datafordeler user + IT-system + API key (email registration is enough for open datasets; MitID Erhverv only for protected ones). Legacy REST/WFS/username access ends **15 Jan 2027**.
3. Fallback if both fail: Eurostat GISCO LAU boundaries (municipalities only).

---

## 3. Source catalogue

### 3.1 Statistics Denmark StatBank API — backbone

- Base: `https://api.statbank.dk/v1/` · endpoints `subjects`, `tables?subjects=<id>`, `tableinfo/<TABLE>`, `data/<TABLE>/<FORMAT>` · **no key** · formats `CSV` (semicolon), `JSONSTAT`, `BULK` (no cell limit) · cell limit 1,000,000 for non-bulk · `lang=en|da` · time selectors `(1)` latest, `(-n+8)` last 8, quarters written `2026K1` · POST JSON body recommended for wide pulls · console at `https://api.statbank.dk/console`.
- Licence: free use incl. commercial, with attribution to Danmarks Statistik.
- Verified pull (2026-09-14):
  `https://api.statbank.dk/v1/data/POSTNR1/CSV?lang=en&PNR20=2100,2200,8000&KØN=TOT&ALDER=IALT&Tid=2025,2026`
  → `2100 København Ø: 91 554 → 92 234`, `8000 Aarhus C: 80 224 → 81 105`.
- Verified pull: `BOST63` Copenhagen Dec 2025 → 31 399 households on boligsikring, avg 1 298 DKK/month.
- Freshness: use `tableinfo` (not the `tables` listing, which caches stale `latestPeriod`).

Full table list used by the Danish edition (all verified to exist):

| domain | tables |
|---|---|
| population | `FOLK1A` `FOLK1AM` `BEFOLK3` `POSTNR1` `POSTNR2` `SOGN1` `KM1` `BY1` `BY3` `BEV107` |
| households | `FAM55N` `FAM44N` `BY4` `BOL106` |
| income | `INDKP101` `INDKP105/106` `IFOR22` `IFOR32/35` `IFOR41` `INDKF101` `AINDK1` |
| labour | `AUP01` `AUP02` `AUF01` `AULP01` `RAS400` `AUS07` |
| education | `HFUDD11` |
| housing stock | `BOL101` `BOL102` `BOL103` `BOL104` `BOL106` `BYGB12` |
| housing benefit | `BOST63` `BOST64` |
| migration | `BEV107` `FLY66` `FLYUNG1/2` `VAN1AAR` |
| ancestry | `FOLK1C` `FOLK1E` `KMSTA001` |
| construction | `BYGV33` `BYGV22` `BYGV11` `BYGV80` |
| prices & sales | `EJ56` `EJ99` `EJEN77` `EJ121` `TVANG1` `TVANG3` |
| rents | `HUS1` `LABY32` `PRIS01` (041000 actual rentals) |
| macro | `PRIS01` `PRIS04` (net price index — used in NPI-indexed leases) `ILON12` `SBLON1` `NKN1` `NAN1` `DNRENTM` `DNRENTD` `MPK3` `DNRNURI` `DNRUURI` |

### 3.2 Finans Danmark Boligmarkedsstatistik — sub-database `s20`

- Same engine and syntax as DST: `https://api.statbank.dk/v1/s20/{tables,tableinfo,data}` · no key · variables must be addressed by code (`PNR20`, `EJKAT20`, `PRIS20`, `Tid`).
- Verified pull (2026-09-14):
  `https://api.statbank.dk/v1/s20/data/BM011/CSV?PNR20=2100,2200,8000&EJKAT20=*&PRIS20=REAL&Tid=2026K1`
  → ejerlejlighed realised DKK/m² 2026K1: 2100 København Ø **79 842**, 2200 København N **78 107**, 8000 Aarhus C **48 265**. Cells with too few trades are `..` or `0` — treat both as null.
- Tables: `BM010` (kommune) / `BM011` (postnr) DKK/m² for UDBUD (first asking), NEDTAG (at delisting), REAL (realised) × parcel-/rækkehus, ejerlejlighed, fritidshus, quarterly 1992– · `BM020/021` sales counts · `BM030/031` days on market · `UDB010/020/030` monthly supply, asking DKK/m², time on market (kommune) · `UL10/UL30` mortgage lending · `LT10` loan offers · `ROE1` arrears & repossessions.
- Method break 2014K1; source is Boligsiden + mortgage banks. Cite "Finans Danmark, Boligmarkedsstatistikken".

### 3.3 Rent levels

| source | content | access | notes |
|---|---|---|---|
| **boligstat.dk** (Social- og Boligstyrelsen) | Rent DKK/m²/yr, *private rental* and *almene*, by municipality × construction period, 2015–2025; also stock, evictions (udsættelser), urban renewal | static HTML/maps, no API (PxWeb path returns 404) → scrape once a year | Private rent = housing-benefit register × BBR, upscaled; ministry warns inter-municipal comparison is indicative. This is the *Kela-vuokra* analogue and should be labelled with the same caveat the Finnish glossary uses. |
| **Landsbyggefonden Huslejestatistik 2026** | Avg rent DKK/m²/yr for almene family/youth/elderly dwellings by municipality, construction period, size; national family-dwelling avg 960 DKK/m² (1 Jan 2026) | `https://lbf.dk/media/tdtm43i4/basistabeller-for-huslejestatistik-2026.xlsx` | 100 % coverage of social housing (Huslejeregisteret). |
| DST `HUS1` / `LABY32` | Rent index 2021=100 by region / municipality group, private vs almene vs andel | API | Trend only, not level. |
| DST `BOST63` | Avg/median housing-benefit DKK per household | API | Proxy of rent burden. |
| Not open | BoligPortal, Boligsiden udbudsleje, husleje.dk, Huslejenævn decisions | web only / paid | Candidate for a separate "market listings" module with explicit ToS review (see §5). |

### 3.4 Buildings & units — BBR via Datafordeler

- GraphQL v3: `POST https://graphql.datafordeler.dk/BBR/v3?apiKey=<key>` — entities `BBR_Bygning` (use code `byg021BygningensAnvendelse`, year `byg026Opførelsesår`, area `byg038SamletBygningsareal`), `BBR_Enhed` (unit use, m², rooms), `Ejendomsrelation` (ownership type: private, almene, andel, company). Filter by `kommunekode`, paginate.
- File download (full JSON per municipality) as an alternative for aggregation to postnr/sogn.
- Registration: Datafordeler Administration — email/password is enough; API key valid 2 years; free. Document the sign-up in `CONTRIBUTING.md`; never commit keys (`.env`).
- Use in dashboard: dwelling counts, size mix and construction-year mix at **postal-code / parish** level (which DST only gives at municipality level), and address-level joins for the owner's own properties (units, year built, energy-label link key).

### 3.5 Copenhagen detail — sub-database `s30`

`https://api.statbank.dk/v1/s30/tables` → `KKBOL1–4` (dwellings by district/rode × tenure × size × year), `KKBEF1/3` (population by district, quarterly to 2026K3), `KKHUS1` (households), `KKFR2026` (projection). District polygons from opendata.dk (Københavns Kommune, CC BY 4.0). Use this for a Copenhagen "micro" level below postal code.

### 3.6 Macro panel

| indicator | source | geo | cadence |
|---|---|---|---|
| CPI, and *actual rentals* sub-index | `PRIS01` (ECOICOP, group 041000) | national | monthly · 2026M08 |
| Net price index (rent indexation basis) | `PRIS04` | national | monthly |
| Rent index private / almene / andel | `HUS1` | DK + 5 regions | quarterly · 2026Q2 (DK all housing 111.8, +2.7 % y/y) |
| House price index flats / houses / andel | `EJ56` (regions, provinces), `EJ99` (DK & Byen København, incl. andelsboliger) | region / province | quarterly |
| Sales volumes, avg price | `EJEN77` | province | quarterly |
| Policy & money-market rates, mortgage bond yields | `DNRENTM` (monthly), `DNRENTD` (daily) — Nationalbank data mirrored in DST; fuller set at `nationalbanken.statbank.dk` (no API sub-database found; use CSV export) | national | monthly / daily |
| New & outstanding mortgage lending by rate fixation | `DNRNURI`, `DNRUURI`; Finans Danmark `s20/UL10`, `UL30` | national | monthly / quarterly |
| Unemployment (seasonally adj.) | `AUS07` | national / region | monthly |
| GDP | `NKN1` (quarterly s.a.), `NAN1` (annual); regional GDP per capita via Eurostat `nama_10r_3gdp` (NUTS3 = the 11 landsdele) | national / NUTS3 | quarterly / annual |
| Wages | `SBLON1` standardised earnings index, `ILON12` | national | quarterly |
| Forced sales | `TVANG1` | national | monthly |
| Construction headline | `BYGV80/88/90` (delay-adjusted) | national | monthly |

### 3.7 Context layers (optional, all open)

- **Plandata.dk WFS** — `https://geoserver.plandata.dk/geoserver/wfs` layers `pdk:theme_pdk_kommuneplanramme_vedtaget_v` (allowed use, plot ratio, max storeys → planned housing capacity), `pdk:theme_pdk_lokalplan_vedtaget` / `_forslag`, zoning. `outputFormat=json`, `cql_filter=komnr=101`. No key.
- **Parallelsamfundslisten & udsatte boligområder** (Social- og Boligministeriet, 1 Dec each year) — PDF → CSV; Copenhagen publishes the polygons on opendata.dk.
- **opendata.dk CKAN** — `https://admin.opendata.dk/api/3/action/package_search?q=bolig` — Copenhagen/Aarhus layers: almene boligforeninger, udsatte byområder, byfornyelse, BBR-bygninger Aarhus (WFS). CC BY 4.0.
- **Rejseplanen GTFS** (CC BY 4.0, sign-up form) — public-transport accessibility score per polygon.
- **noegletal.dk** — municipal tax rate (kommuneskat), land tax (grundskyldspromille), liquidity; Excel export from the web UI, no API.
- **Energy labels** — Energistyrelsen EMOData (`emoweb.dk/emodata`, Basic-auth credentials by email to emo-info@ens.dk); aggregate share of A–C labels per area only if a bulk extract is granted.

---

## 4. What the Danish `makro` view looks like (design carried over, data replaced)

Same shell as the Finnish edition — Leaflet map card with accent border, chip row of indicators, legend scaled to the visible set, source note, "own properties" toggle, popup listing every indicator of the polygon, comparison tables sorted by the active indicator. Changes that the Danish data forces:

1. **Chip row** = §1 keys 1–12 plus `price_m2`, `dom`, `supply`, `pipeline`, `almene`. One hue per indicator as in `MK_HUE`; new hues for price (deep blue), days-on-market (ochre), pipeline (green), almene (grey-blue).
2. **Levels:** kommune (z < 11) → postnummer (z ≥ 11); Copenhagen optionally → bydel. Each indicator declares its native level; below that level the polygon takes the parent value and the `°` marker.
3. **Tables:** "Municipalities compared" (98 rows, all indicators + portfolio join on `kommunekode`) and "<Municipality> by postal code" (own-value columns only: population, growth, 20–34 %, price/m², discount, days on market, sales; municipality-level columns greyed with `°`).
4. **Market panel (new card, Denmark-only):** four KPI tiles (`.hero`) — private rent index y/y (`HUS1`), ejerlejlighed price/m² y/y in the portfolio's municipalities (`BM010`), homes for sale y/y (`UDB010`), completions last 4Q (`BYGV33`) — each with a 24-month sparkline. Below it a small macro table (CPI, net price index, policy rate, 30-yr mortgage bond yield, unemployment) with "as of" dates.
5. **Portfolio joins** (when portfolio data is added later): properties matched by `kommunekode` (from address → DAR) and postal code; marker colour = vacancy pressure exactly as in the Finnish edition; a "rent vs area" column comparing the owner's DKK/m²/month × 12 against boligstat.dk private rent and LBF social rent for the same municipality and construction period.
6. **Source note** lists: Danmarks Statistik (table codes + fetch date), Finans Danmark Boligmarkedsstatistik, Social- og Boligstyrelsen boligstat.dk, Landsbyggefonden, Klimadatastyrelsen DAGI (attribution string), Danmarks Nationalbank.

---

## 5. Gaps and decisions still open

| gap | options | recommendation |
|---|---|---|
| No open **asking-rent** data at postal-code level (the Finnish *Market / comps* view uses competitor listings) | (a) request a data agreement with BoligPortal / Boligsiden; (b) husleje.dk registration (basic stats free, reuse terms unclear); (c) own scraper with ToS review; (d) skip and use boligstat.dk + LBF as the rent benchmark | Start with (d); revisit (a) once the dashboard has a user base. |
| Income / education / households below municipality | DST *Nøgletal på postnumre* (paid, ~3.7–11.5 kDKK/table/yr) or BBR-derived structural proxies (size mix, construction year, tenure) at postnr | Use BBR proxies; note the paid option in README. |
| Nationalbank API | No `api.statbank.dk` sub-database code found for `nationalbanken.statbank.dk` | Use DST mirrors `DNRENTM/DNRENTD/MPK3`; add CSV export fallback. |
| Vacancy | `BOL101` BEBO=2000 is a registration-based proxy; LBF publishes vacant social dwellings separately | Show both, with caveat text. |
| Energy labels | Credentials on request; no bulk table | Phase 2. |
| QGIS in the pipeline | QGIS is useful for *inspecting* and one-off simplification of DAGI/Plandata layers, but the repo pipeline should be reproducible in code (Python + geopandas/shapely or mapshaper CLI) | Code first; QGIS as an optional inspection step documented in `docs/GEO.md`. |

---

## 6. Repository layout (GitHub)

```
am-dashboard-dk/
├── README.md                 # what it is, how to run, attribution
├── docs/
│   ├── DATA_MAP.md           # this file
│   └── GEO.md                # boundary pipeline (DAWA → Datafordeler), QGIS notes
├── config/
│   └── indicators.json       # indicator registry: key, label, unit, table, query, level, hue
├── scripts/
│   ├── fetch_geo_dawa.py     # ⚠ run before 2026-10-01: vendors DAGI GeoJSON
│   ├── fetch_statbank.py     # generic DST / s20 / s30 fetcher (POST JSON → CSV → parquet)
│   ├── build_makro.py        # joins indicators to polygons → data/processed/makro.json
│   └── build_dashboard.py    # inlines window.DATA into the HTML template
├── data/
│   ├── geo/                  # kommuner.geojson, postnumre.geojson, sogne.geojson (+ raw/)
│   ├── raw/                  # per-table CSV pulls, dated (gitignored above a size limit)
│   └── processed/            # makro.json, market.json
├── src/
│   └── index.html            # dashboard template (design ported from the Finnish edition)
└── .github/workflows/
    └── refresh.yml           # monthly cron: fetch → build → commit data/processed
```

**Refresh cadence:** monthly workflow is enough — AUP01/UDB010/PRIS01/DNRENTM are monthly, BM0xx/BYGV33/HUS1 quarterly, everything else annual. Each pull is stamped with `tableinfo.updated` so the source note can show the real "as of" date per indicator, as the Finnish `makro.src.haettu` does.

---

## 7. Verification log

| date | check | result |
|---|---|---|
| 2026-09-14 | `POSTNR1` CSV pull, 3 postal codes, 2025–2026 | ✅ values returned |
| 2026-09-14 | `s20/BM011` CSV pull, ejerlejlighed REAL 2026K1 | ✅ 79 842 / 78 107 / 48 265 DKK/m² |
| 2026-09-14 | `BOST63` CSV pull, København & Aarhus Dec 2025 | ✅ households + avg DKK |
| 2026-09-14 | `FOLK1A`, `HUS1`, `s20/tables`, `s30/tables`, `tableinfo` for ~40 tables | ✅ (research agents) |
| 2026-09-14 | DAWA `/postnumre`, `/kommuner`, `/sogne` GeoJSON | ✅ respond; closure notice confirmed for 2026-10-01 |
| 2026-09-14 | Plandata WFS GetCapabilities, opendata.dk CKAN, Eurostat `nama_10r_3gdp` | ✅ |
| 2026-09-14 | boligstat.dk PxWeb API, rkr.statistikbank.dk `/api/v1/` | ❌ 404 — use `s20` / scrape |
| 2026-09-14 | Nationalbank sub-database on `api.statbank.dk` | ❌ not found |
| — | Datafordeler GraphQL with a real key, EMOData, Rejseplanen GTFS download | not yet (need credentials) |

Sources: Danmarks Statistik API docs (https://www.dst.dk/en/Statistik/brug-statistikken/muligheder-i-statistikbanken/api) · Finans Danmark Boligmarkedsstatistikken (https://finansdanmark.dk/tal-og-data/boligstatistik/boligmarkedsstatistikken/) · Klimadatastyrelsen, DAWA lukker 1. oktober 2026 (https://www.klimadatastyrelsen.dk/om-klimadatastyrelsen/nyheder/nyhedsarkiv/2026/jul/dawa-lukker-d-1-oktober-2026) · Datafordeler transition plan (https://datafordeler.dk/vejledning/transitionsnetvaerk/) · BBR GraphQL (https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/) · boligstat.dk om husleje (https://boligstat.dk/boligstat/dokumenter/omhusleje.html) · Landsbyggefonden Huslejestatistik 2026 (https://lbf.dk/viden/statistikker/huslejestatistik/huslejestatistik-2026) · Plandata WFS (https://geoserver.plandata.dk/geoserver/wfs?request=GetCapabilities&service=WFS) · Eurostat API (https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10r_3gdp?geo=DK011&unit=EUR_HAB&time=2023) · Frie geografiske data, vilkår (https://dataforsyningen.dk/asset/PDF/rettigheder_vilkaar/Vilk%C3%A5r%20for%20brug%20af%20frie%20geografiske%20data.pdf)
