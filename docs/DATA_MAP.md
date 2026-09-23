# AM Dashboard — Denmark Edition: Open Data Map

**Status:** v2.0 · 2026-09-22 · Safety (crime) added; see §3.8 and the verification log in §7
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
| Safety — reported crime, charges | **Statistics Denmark StatBank API** `STRAF11` (quarterly) / `STRAF22` (annual) | REST, no key | 98 municipalities (place of offence) | ✅ live pulls |

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
| crime | `STRAF11` (quarterly, place of offence) `STRAF22` (annual, reports and charges) — see §3.8 |
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

### 3.4 Buildings & units — BBR via Datafordeler (implemented v1.4)

Endpoint `https://graphql.datafordeler.dk/BBR/v3?apiKey=…` (free key: portal.datafordeler.dk → IT-systemer → API-Keys; new keys take a while to activate — 401 for the first hours). Entities used: `BBR_Enhed` (dwelling units) and `BBR_Bygning` (buildings), cursor-paged 1 000 per request, filtered `kommunekode` + `status = 6` (current). Field names use ASCII transliteration (`byg026Opfoerelsesaar`, `enh031AntalVaerelser`); the coordinate is an object (`byg404Koordinat { wkt crs }`, EPSG:25832).

| field | meaning | used for |
|---|---|---|
| `enh023Boligtype` | 1 dwelling, 2 mixed, 3 single room, 4 shared, 5 summer house, E business | dwelling filter (1–5) |
| `enh045Udlejningsforhold` | 1 rented (incl. andel), 2 owner-occupied, 3 not in use | renters_bbr, vacant_bbr |
| `enh026EnhedensSamledeAreal`, `enh031AntalVaerelser` | area m², rooms | avg_m2_bbr, small_bbr, distributions |
| `bygning` → `byg026Opfoerelsesaar`, `byg021BygningensAnvendelse`, `byg404Koordinat` | year built, use (140 = multi-dwelling), point | new_stock_bbr, flats_bbr, placement |

Placement: point-in-polygon (shapely) into `data/geo/postnumre.geojson` and `cph_kvarterer.geojson`; 99 % of dwellings get a coordinate. Throughput ≈ 70 units/s per worker (buildings 10× faster); Copenhagen + 18 suburbs ≈ 1 h with 4 workers, whole country ≈ 3–4 h. Raw pulls (`data/raw/bbr/`) are gitignored; only `data/processed/bbr.json` is committed, so CI needs no key.

**Verification (2026-09-14):** Frederiksberg BBR 57 942 dwellings (boligtype 1–5, status 6) vs DST BOL101 2026 57 576 → +0.6 %. Tenure known for 99.97 %; 74 % rented incl. andel.

**Addresses and BFE (v1.8):** DAR GraphQL (`https://graphql.datafordeler.dk/DAR/v3`, same key): `DAR_Husnummer` (husnummertekst, navngivenVej, postnummer) → `DAR_NavngivenVej.vejnavn`, `DAR_Postnummer.postnr/navn`. Property number: `BBR_Bygning.grund` → `BBR_Grund.bestemtFastEjendom` → `BBR_Ejendomsrelation.bfeNummer` (`BBR_BygningEjendomsrelation` only covers buildings on foreign ground). Lookups by id lists of 100; whole country ≈ 25 min. Coverage 100 % of Micro buildings.

Not in BBR: rents, migration, population — those stay with DST/boligstat. Unoccupied share is owner-reported and lags; DST BOL101 BEBO=2000 (municipality) is the reference vacancy figure.

### 3.4b Public buildings — BBR anvendelse 410–449 (v2.2, pilot)

The same register as §3.4, sliced by building use instead of dwellings: schools, daycare, health and
culture buildings (`byg021BygningensAnvendelse` 410–449) as **existing stock** (status 6) and as
**open building cases** (status 2/3 joined through `BBR_Sagsniveau` to `BBR_BBRSag`). Coordinates come
from `byg404Koordinat`, and from DAR (`husnummer` → `DAR_Adressepunkt`) for the 83 % of open-case
buildings BBR has not placed; names from OpenStreetMap within 60 m.

Measured 2026-09-23 on the pilot (København + Frederiksberg, 290 open cases): **1 of 290** carried an
expected completion date, 91 % a permit date, median permit age 4.1 years in København. That is why the
layer speaks of *open building cases* rather than planned or ongoing construction, draws only cases with
a permit ≤ 3 years old, and ships no forward-looking "planned buildings" indicator. Full method,
code lists and caveats: [`docs/PUBLIC_BUILDINGS.md`](PUBLIC_BUILDINGS.md).

### 3.5 Copenhagen detail — sub-database `s30`

`https://api.statbank.dk/v1/s30/tables` → 48 tables. **Implemented in v1.2 as a third map level: 67 quarters (kvarterer).** The area variable is `OMRKK`: `1000` = city total, `1001–1010` = 10 districts (bydele), `2001–2012` = local committees (lokaludvalg), `20101–21211` = kvarterer (code `2LLxx` → lokaludvalg `20LL` → bydel, mapping in `scripts/build_cph.py`). Polygons: `wfs-kbhkort.kk.dk/k101` layers `kvarter` and `bydel` (CC BY 4.0, `scripts/fetch_geo_cph.py`); the WFS `kvarternr` equals the statbank code one-to-one.

| key | table (pull) | selection | calc | note |
|---|---|---|---|---|
| growth | KKBEF1 (`KKBEF1_pop`) | all dims SUM, quarterly | yoy_pct | same quarter previous year |
| young | KKBEF1 (`KKBEF1_age`) | ALDER TOT + 20…34 | share_of_total | |
| single | KKHUS1 (`KKHUS1_size`) | HUSSTØR 001 / TOT | share_of_total | one-person households (household size = 1), not "single men + women" as in FAM55N |
| income_med | KKIND4 | DECILGR 5 | value_div_1000 | 5th decile boundary = median disposable income, persons 15+; lag ~2 years |
| higher_ed | KKUDD1 | HFUAMS 04–08 / TOT | share_of_total | short-cycle … PhD, of 15–69 |
| renters, private_rental, andel, almene | KKBOL3 (`KKBOL3_tenure`) | EJER 02+03+04+05, 02, 03, 04 / 01–05 | share_of_total | `99` unknown excluded from denominator |
| avg_m2 | KKBOL3 (`KKBOL3_size`) | ENHED 03 | passthrough | average m² per dwelling |
| new_stock | KKBOL3 (`KKBOL3_year`) | IBRUGKK 13–28 (2010…2025) / TOT | share_of_total | share of stock commissioned 2010+ |
| unemp | KKLEDIG2 ÷ KKBEF1_pop | ALERAMS SUM | ratio_pct | **district level only** (KKLEDIG2 has 23 area codes, no kvarterer) — each quarter shows its bydel's value; denominator is the same year's population, not the labour force |

Not usable at quarter level: KKLEDIG2 (unemployment, bydel only), KKIND* other than the decile table (means at bydel), anything with `OMRKK` limited to 23 codes — check `validate_config.py`'s `OMRKK=* (n codes)` line: 93 codes = kvarter level available, 23 = districts only.

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

### 3.8 Safety (crime) — `STRAF11` / `STRAF22` (implemented v2.0)

| table | content | geography (`OMRÅDE`, 106 codes) | period | raw pull |
|---|---|---|---|---|
| `STRAF11` | Reported criminal offences (*anmeldelser*) by **place of offence** (*gerningskommune*) and type of offence (`OVERTRÆD`, 77 codes); excludes the traffic law | `000` Denmark, 5 regions, 98 municipalities | quarterly, 2007K1– (latest 2026K2, updated 2026-07-16) | `dst_STRAF11_offences` |
| `STRAF22` | Reported offences and reports that led to a charge (`ANMSIGT`: `ANM` reported, `SIG` with a charge) | same | annual, 2007– (latest 2025, updated 2026-02-19) | `dst_STRAF22_charges` |
| `FOLK1A` | Population, 1st day of the quarter (`KØN=TOT`, `ALDER=IALT`, `Tid=*`) — denominator | same | quarterly, 2008K1– | `dst_FOLK1A_pop_long` |
| `BOL101` | Dwellings, occupied + unoccupied (`BEBO=1000,2000`, other dimensions summed by the API, `Tid=*`) — denominator | same | annual (1 Jan), 2010– **without 2021 and 2022** | `dst_BOL101_dw_long` |

Codes fetched: `STRAF11` `OVERTRÆD` = `TOT` total · `1` Criminal Code total (headline) · `11` sexual · `12` violence · `13` property · `14` other penal · `1320` residential burglary · `1345` bicycle theft · `3` special acts total · `3210` Euphoriants Act (drugs) · `3410` Weapons Act. `STRAF22` `OVERTRÆD` = `1`, `12`, `1320` × `ANMSIGT` = `ANM`, `SIG`. Full time range (`Tid=*`) regardless of `history_years`.

| key | indicator | codes | calc (`scripts/build_makro.py`) | direction |
|---|---|---|---|---|
| `crime_1000` | Reported crime per 1,000 inhabitants — chip *Crime* | `1` | `rolling4q_per_1000_pop` | lower better |
| `violence_1000` | Violent crime per 1,000 inh. | `12` | `rolling4q_per_1000_pop` | lower better |
| `property_1000` | Property crime per 1,000 inh. | `13` | `rolling4q_per_1000_pop` | lower better |
| `burglary_1000dw` | Residential burglaries per 1,000 dwellings | `1320` | `rolling4q_per_1000_dwellings` | lower better |
| `drugs_weapons_1000` | Drug and weapons offences per 1,000 inh. | `3210` + `3410` | `rolling4q_per_1000_pop` | lower better |
| `crime_trend` | Reported crime, y/y % | `1` | `rolling4q_yoy_pct` | lower better |
| `clearance_pct` | Penal-code reports with a charge, % | `STRAF22` `1`: `SIG` ÷ `ANM` × 100 | `ratio_pct` | higher better |

Calculation rules:
- **Rolling 4 quarters** (the counts are not seasonally adjusted): the live value is the sum of the four quarters ending at the latest quarter (`2025K3→2026K2`). A window with a missing quarter gives no value; nothing is imputed.
- **Population at the end of the window.** FOLK1A counts the 1st day of a quarter, so the end of 2026K2 is FOLK1A 2026K3 (falls back to the window's last quarter while the next one is unpublished). Dwellings: BOL101 on 1 Jan of the following year, else 1 Jan of the window's year.
- **Yearly history** (map year selector, area pages, Charts *Yearly*): each calendar year is its Q1–Q4 sum ÷ population at the end of Q4. `history_from: 2007` → Charts reach 2007 (burglary 2009, crime_trend 2008); `map_from: 2008` → the map/table year selector starts in 2008.
- **Quarterly series** (Charts *Quarterly*): one rolling-4Q value per quarter from 2008K1 (crime_trend 2008K4, burglary 2009K1 with a gap in 2021), municipalities and Denmark (`000`, the dashed reference line).
- Verified in `tests/test_safety.py`: København 2025K3–2026K2 code 1 = 15 323 + 14 713 + 15 205 + 15 045 = 60 286 ÷ 670.389 → **89.9**; clearance 2025 = 11 763 ÷ 68 802 → **17.1 %**.

**Geography — what is true where.** Every Safety figure exists **per municipality only** (place of offence). Postal codes and Copenhagen quarters show their municipality's value, marked `°`, on the map, in the table, in popups and on area pages; ranks are computed among municipalities only. No police-district (*politikreds*) or finer police data is used.

Caveats (also in each indicator's `note`):
- Reported offences, not solved cases (reported ≠ solved); place of offence, not the offender's residence; the traffic law is excluded.
- Series breaks: 2007 (police reform — the series starts there); **1 July 2013** Criminal Code amendments on sexual offences (DST footnote; marked in Charts on the penal-code series `crime_1000`, `crime_trend`, `clearance_pct`); **2023** ≈ 1 700 reports missing in *Legislation on animals, hunting etc.* (DST footnote) — a special-acts category that none of the dashboard series include, so no marker is drawn.
- `suppressedDataValue` is `0` in both tables: a suppressed cell and a true zero look the same. Zeros occur only on small islands (Christiansø, Ærø, Fanø, Samsø, Læsø) and are taken as counts.
- Drug and weapons offences largely reflect police activity (stop-and-search, visitation zones), not incidence.
- Clearance counts charges for reports of the same year, so the latest year can still rise as cases are processed.
- Christiansø (91 inhabitants) has per-1,000 rates that are noise; burglary per dwelling and crime y/y are empty there (no BOL101 dwellings; zero base).

> **Internal note.** v1 = STRAF11/STRAF22 via API. Planned: v2.0.1 Copenhagen 13 bydele from KK Tryghedsundersøgelse PDF. Available later if needed: Tryghedsundersøgelsen (Justitsministeriet, kommune, PDF), udsatte boligområder list (SBST, PDF), politi.dk statistics (politikreds).

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
| **Current mortgage bond yields** | DST `DNRENTM` mortgage-bond series (`CRO30Y` etc.) end Nov 2012 (verified 2026-09-14) | v1 shows the Nationalbank CD and lending rates only; source a live 30-year yield from Nationalbanken's own statbank (`DNRENTD`-family) or Finans Danmark `s20/LT10` loan offers in phase 6. |
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
| 2026-09-22 | `STRAF11`, `STRAF22` tableinfo + `validate_config.py` (all 11 + 3 × 2 codes ✓); test cells `STRAF11` code 1 2026K2 København / Aarhus / Odense / Denmark, `STRAF22` København 2025 | ✅ 15 045 / 5 202 / 2 977 / 76 275; ANM 68 802, SIG 11 763 |
| 2026-09-22 | Safety indicators, 10-area check against statistikbanken.dk (§7c) | ⏳ statistikbanken values pending |
| 2026-09-22 | `crime_1000` København recomputed by hand from `data/raw`: STRAF11 code 1 15323 + 14713 + 15205 + 15045 = 60 286 ÷ FOLK1A 2026K3 670 389 × 1000 | ✅ 89.93 = dashboard 89.93 |
| 2026-09-22 | `crime_1000` Aarhus recomputed by hand from `data/raw`: STRAF11 code 1 5937 + 5010 + 4281 + 5202 = 20 430 ÷ FOLK1A 2026K3 378 270 × 1000 | ✅ 54.01 = dashboard 54.01 |
| 2026-09-22 | `crime_1000` Odense recomputed by hand from `data/raw`: STRAF11 code 1 2970 + 3608 + 2523 + 2977 = 12 078 ÷ FOLK1A 2026K3 213 140 × 1000 | ✅ 56.67 = dashboard 56.67 |
| 2026-09-22 | Copenhagen bydele from the KK Tryghedsundersøgelse PDF, three rows read off the pages: Indre By 90 % / 263 per 1 000 (pp. 70, 74), Bispebjerg 80 % (pp. 49–50), Valby 79 % / 43 (p. 98) | ✅ CSV matches; Bispebjerg fact box p. 49 prints Brønshøj-Husum's 76 % / 64 % — results page p. 50 and the p. 7 map give 80 % / 70 %, which is what the CSV uses |
| 2026-09-23 | `m5-phase-1` re-read at metroselskabet.dk/m5 | ✅ open_year 2036 ("Første etape af M5 der efter planen åbner i 2036"); no budget on the page, CSV empty ✓ |
| 2026-09-23 | `femern-tunnel` re-read at the cited Femern A/S article (17 May 2026) | ❌→fixed: the article gives **no** opening year for the road (only "vejforbindelsen åbner først" and that Germany cannot open its rail land facilities in 2029); `open_year` 2032 was not in the source and has been emptied, `open_year_original` 2029 kept. Budget 55.100 mio. kr. (2015 prices) verified in Anlægsstatus 1H 2026 p. 50 |
| 2026-09-23 | `nordhavnstunnel` re-read in Anlægsstatus 1H 2026 p. 34 | ✅ "Nordhavnstunnel 4.495,2 … 2028" = CSV 4 495,2 / 2028 |
| 2026-09-23 | `nyt-hospital-nordsjaelland` re-read in the Q2 2026 quarterly report (Region H) | ✅ opening: "Ultimo sep. 2027 · 1. patient" = CSV 2027. ⚠ the budget 7.992 mio. kr. (PL25E2) is **not** restated in that report — it comes from the Q3 2025 report; `source_doc` now cites both |
| 2026-09-23 | `hilleroedmotorvejen-forlaengelse` re-read in Anlægsstatus 1H 2026 p. 34 | ✅ "Udvidelse af Hillerødmotorvejens forlængelse til motorvej 1.614,7 … 2027" = CSV 1 614,7 / 2027 |
| 2026-09-23 | Public buildings: 5 records re-queried one by one from BBR (GraphQL, `id_lokalId`) — code / m² / year built | ✅ all five identical to the built files |
| 2026-09-23 | · Københavns Professionshøjskole, Campus (101, education) | ✅ 429 / 71 159 m² / 2018, status 6 |
| 2026-09-23 | · Langbjergskolen (153, institutions) | ✅ 441 / 13 498 m² / 1970, status 6 |
| 2026-09-23 | · Hvidovre Hospital (167, health) | ✅ 431 / 109 049 m² / 1977, status 6 |
| 2026-09-23 | · Sprogcenter Hellerup, Tuborg campus (157, culture) | ✅ 416 / 25 000 m² / 1901, status 6 |
| 2026-09-23 | · Frederiksberg Teater (147, open case) | ✅ 411, status 3, no area or year in BBR — permit 2026-09-02, age 0.1 yr, no expected completion |
| 2026-09-23 | School quality: 5 schools re-queried one at a time from the STIL API (single-institution filter, fresh call, no cache) — FP9 grade and well-being for 2025/2026, socioøkonomisk reference for 2024/2025 (it is published a year behind) | ✅ all 20 comparisons identical to `data/processed/schools.json`, including a suppressed cell and both significance directions |
| 2026-09-23 | · Skolen på Duevej (147007, folkeskole, Frederiksberg) | ✅ grade 8.5 = 8.5 · soc.ref. diff 0.2 = 0.2 (På niveau) · well-being 3.6 = 3.6 |
| 2026-09-23 | · Lindevangskolen (147002, folkeskole, Frederiksberg) | ✅ grade 7.6 = 7.6 · soc.ref. diff 0.5 = 0.5 (På niveau) · well-being 3.6 = 3.6 |
| 2026-09-23 | · Den Classenske Legatskole (101001, folkeskole, København) | ✅ grade 8.9 = 8.9 · soc.ref. diff 0.7 = 0.7 (Over niveau) · well-being 3.7 = 3.7 |
| 2026-09-23 | · Krebs' Skole (101083, fri grundskole, København) | ✅ grade 9.3 = 9.3 · soc.ref. diff 0.8 = 0.8 (Over niveau) · well-being – = – |
| 2026-09-23 | · Nørre Fælled Skole (101045, folkeskole, København) | ✅ grade 7.8 = 7.8 · soc.ref. diff -0.8 = -0.8 (Under niveau) · well-being 3.7 = 3.7 |

### 7b. Calculation verification (phase B, 2026-09-14)

Each dashboard value below was recomputed by hand from separate API pulls of the underlying cells (different query, no pipeline code involved).

| indicator | cell | independent value | dashboard | result |
|---|---|---|---|---|
| House price index, flats (y/y) | EJ56 DK 2026K1, TAL=310 as published by DST | **15.8 %** (index 106.9 → 123.8) | 15.81 % | ✅ genuine, not a bug |
| Realised price DKK/m², flats | BM010 København 2025K2–2026K1: 60 503 / 64 254 / 68 247 / 72 846 → mean | 66 462.5 | 66 462.5 | ✅ |
| Realised price DKK/m², flats | BM010 Aarhus, same quarters | 38 842.75 | 38 842.75 | ✅ |
| Housing-benefit households % | BOST63 Aarhus Dec 2025 all types 53 934 ÷ FAM55N households 186 792 | 28.87 % | 28.87 % | ✅ (high: students on boligsikring + pensioners on boligydelse) |
| Housing-benefit households % | København 58 399 ÷ 332 181 | 17.58 % | 17.58 % | ✅ |
| Single-person households % | FAM55N København (73 557 + 94 258) ÷ 332 181 | 50.52 % | 50.52 % | ✅ |
| Rented dwellings % | BOL101 København 2026 LEJ 263 497 ÷ (EJ 65 525 + LEJ 263 497) | 80.08 % | 80.08 % | ✅ — note DST counts andelsbolig residents as tenants |
| Unemployment % | AUP01 København / Gentofte 2026M07 | 4.3 / 2.7 | 4.3 / 2.7 | ✅ |
| Population growth | FOLK1A København 2025K3 667 574 → 2026K3 670 389 | +0.42 % | +0.42 % | ✅ |
| Private rent DKK/m²/yr | boligstat.dk 2026 København / hele landet | 1 637 / 1 277 | 1 637 (national not shown) | ✅ |
| Social rent DKK/m²/yr | LBF Tabel 7 familieboliger 2026 København | 1 077 | 1 077 | ✅ |

Definitions confirmed against the source metadata in the same pass: FOLK1E origin codes 24/25/34/35 = immigrants + descendants; HFUDD11 H40–H80 = short-, medium- and long-cycle higher education incl. PhD; BYGV33 phase 3 = completed.


### 7c. Safety check against statistikbanken.dk (2026-09-22)

Dashboard values as built on 2026-09-22 (window 2025K3→2026K2; clearance 2025). The raw cells are what statistikbanken.dk shows directly: `STRAF11` code 1 summed over 2025K3–2026K2, `FOLK1A` 2026K3, `STRAF22` code 1 `SIG` / `ANM` 2025. The *statistikbanken.dk* column is filled in from a manual lookup.

| area | code | STRAF11 code 1, 4Q sum | FOLK1A 2026K3 | crime_1000 | violence_1000 | burglary_1000dw | crime_trend | clearance (SIG / ANM) | statistikbanken.dk | result |
|---|---|---|---|---|---|---|---|---|---|---|
| København | 101 | 60 286 | 670 389 | 89,9 | 6,3 | 2,8 | −5,6 % | 11 763 / 68 802 → 17,1 % | ⟨statistikbanken⟩ | pending |
| Aarhus | 751 | 20 430 | 378 270 | 54,0 | 4,4 | 7,1 | −10,7 % | 4 644 / 22 603 → 20,5 % | ⟨statistikbanken⟩ | pending |
| Odense | 461 | 12 078 | 213 140 | 56,7 | 6,3 | 8,5 | +3,2 % | 4 158 / 12 675 → 32,8 % | ⟨statistikbanken⟩ | pending |
| Aalborg | 851 | 8 818 | 226 404 | 38,9 | 4,4 | 3,4 | −1,9 % | 2 825 / 9 265 → 30,5 % | ⟨statistikbanken⟩ | pending |
| Frederiksberg | 147 | 6 423 | 105 947 | 60,6 | 3,5 | 2,3 | −11,4 % | 1 135 / 7 576 → 15,0 % | ⟨statistikbanken⟩ | pending |
| Gentofte | 157 | 3 557 | 75 241 | 47,3 | 3,6 | 12,9 | −16,8 % | 786 / 4 206 → 18,7 % | ⟨statistikbanken⟩ | pending |
| Lyngby-Taarbæk | 173 | 3 203 | 58 671 | 54,6 | 4,1 | 8,8 | −12,1 % | 793 / 3 335 → 23,8 % | ⟨statistikbanken⟩ | pending |
| Esbjerg | 561 | 4 878 | 114 824 | 42,5 | 4,7 | 3,8 | −12,3 % | 2 096 / 5 421 → 38,7 % | ⟨statistikbanken⟩ | pending |
| Randers | 730 | 3 671 | 100 921 | 36,4 | 5,0 | 4,1 | −11,6 % | 1 282 / 4 176 → 30,7 % | ⟨statistikbanken⟩ | pending |
| Denmark | 000 | 300 999 | 6 031 699 | 49,9 | 5,0 | 5,3 | −5,0 % | 84 741 / 327 755 → 25,9 % | ⟨statistikbanken⟩ | pending |

### 7d. Analysis sheet / test-property pin (2026-09-23)

Checked in the browser against the built `dist/` on `localhost:8080`, v2.4. Three pins, chosen for the
three coverage cases: a Copenhagen quarter, a second quarter with a dense public layer, and a point
well outside the metro set.

| # | check | pin | result |
|---|---|---|---|
| 1 | Sheet renders, pin resolved to kommune · postnr · quarter | 55.64820, 12.53740 | ✅ **København · 2450 København SV · Gl. Sydhavn**, no `approx.` — the kommune came from the rings |
| 2 | All seven sections populated | 55.64820, 12.53740 | ✅ area profile 19 indicators · Safety 8 · Infrastructure 7 projects within 3 km · Public buildings 56 in the ring (2 municipality files: **København + Tårnby**) · Schools 5 · Sources & as of |
| 3 | Sheet renders in a second quarter | 55.69200, 12.55000 | ✅ **København · 2200 København N · Blågårdskvarteret/Assistens/Rantzausgade**; Infrastructure 9 · Public buildings 2 files · Schools 11 · no empty section |
| 4 | Outside the metro set: the two uncovered sections say so | 55.46700, 8.45200 | ✅ **Esbjerg · 6700 Esbjerg**; Public buildings *"Not covered yet: public buildings are available for the Copenhagen metro area."*, Schools the same sentence; Infrastructure *"no project in the layer within 3 km"* (a different, correct sentence); area profile and Safety fully populated |
| 5 | Public buildings pill disabled outside coverage | 55.46700, 8.45200 | ✅ `disabled`, tooltip *"Not covered yet: Copenhagen metro area only"*; Infra projects on, Buildings enabled (*"BBR buildings with ≥ 2 dwellings in Esbjerg"*) |
| 6 | Cold load straight on an `#analysis` link, no visit to the map first | 55.64820, 12.53740 | ✅ sheet renders; network shows `geo/kommuner_lookup.json`, `schools.json`, `public/0101.json`, `public/0185.json` all 200, no console errors |

#### Nearest station in the infra list, for a ruler check

Pin **55.64820, 12.53740** (2450 København SV). `featDistM` over the whole layer, everything within 6 km,
nearest first — the station rows are the `Point` geometries:

| distance | geometry | project | station coordinates |
|---|---|---|---|
| 1 583 m | MultiLineString | Østlig Ringvej (harbour tunnel) — road, study | — |
| 1 612 m | LineString | Signalprogrammet — rail, under construction | — |
| 2 129 m | MultiLineString | Den nye bane København–Ringsted — rail, opened | — |
| 2 321 m | LineString | Metro M5 phase 1 (København H – Prags Boulevard) — metro, decided | — |
| **2 325 m** | **Point** | **M5: v/Bryggebroen** — metro, decided, 2036 | **55.66189, 12.56542** |
| 2 471 m | LineString | Udvidelse af Amagermotorvejen — road, under construction | — |
| 2 848 m | Point | M5: København H — metro, decided | 55.66775, 12.56673 |

**The nearest station of any mode in the layer is `M5: v/Bryggebroen` at 2 325 m** (the sheet rounds it
to *2,3 km*), from 55.64820, 12.53740 to 55.66189, 12.56542 — measure that pair with the Google Maps
ruler. Recomputed by hand as a check: Δlat 0.01369° × 110 540 = 1 513 m, Δlon 0.02802° × 111 320 ·
cos 55.65° = 1 759 m, hypotenuse **2 320 m** — the 5 m difference is the great-circle formula against
the flat-earth approximation, as expected at this distance. No station is inside the 1 200 m chip ring,
so the sheet shows no headline chip here.

Note that the infra layer is a **curated project list**, not a station register: the existing
Sydhavn / Ny Ellebjerg stations are not in it, so "nearest station" here means the nearest station
*in the layer*.

#### Pin flow and legend (same session)

| check | result |
|---|---|
| Long Google Maps place URL (`…/place/…/@55.6482,12.5374,17z/data=…!3d55.64820!4d12.53740`) → pin | ✅ drilled to `#map/101/postnr?ind=growth&pin=55.64820,12.53740`, popup *København · 2450 København SV · Gl. Sydhavn* |
| *Analyse ›* in the popup → sheet | ✅ `#analysis?a=55.64820,12.53740&la=Test%20property` |
| Browser **Back** → map with the pin intact | ✅ hash keeps `pin=`, one `.tp-pin` marker on the map, `TP` state restored |
| `https://maps.app.goo.gl/…` | ✅ inline error *"Short share links can't be read in the browser…"*; the existing pin is untouched |
| A point in Øresund, 55.70000, 12.75000 | ✅ inline error *"…is in water or outside Denmark — no municipality or postal code covers it."*; no pin dropped, URL unchanged |
| Public buildings legend — one category off | ✅ greyed, and the counts follow: 180 existing → 98 with Education off |
| …all four off | ✅ legend stays, reads **All categories hidden · Show all**, counts line reads *nothing drawn* |
| …*Show all* | ✅ all four back on, counts return to 180 existing · 6 open cases |
| Layer pill off | ✅ the legend box is `display:none`, 0 × 0 px — no empty white bar; no `.maplegend` anywhere is visible-but-empty |

`make test` (12 Python + 15 JS), `make validate` (0 ✗) and `make build` (0 ⚠) all pass on the same
commit. Method and the rest of the feature: [`ANALYSIS.md`](ANALYSIS.md).

### 7e. Outlook layer — full independent verification (2026-09-23)

Not a sample. `scripts/verify_forecast_full.py` re-pulls the source tables from the API with its
own request, its own CSV parsing and its own arithmetic — it imports nothing from
`build_forecast.py` — and diffs the result cell by cell against what the pipeline shipped, so a bug
in the build cannot hide in the check.

| # | check | result |
|---|---|---|
| 1 | `FRKM126` → `forecast.json`, every cell re-pulled and diffed: **98 kommuner × 15 years × 8 fields** | ✅ **11 760 cells, 0 mismatches** |
| 2 | Σ 98 kommuner vs `FRDK126`'s published national total, all 15 years | ✅ largest gap **129 persons on 6.0 M (0.0022 %)** |
| 3 | `KKFR2026` → `cph_forecast.json`, every cell re-pulled and diffed: **93 OMRKK areas × 15 years × 8 fields** | ✅ **11 160 cells, 0 mismatches** |
| 4 | Σ kvarterer = Σ bydele = city, all 15 years | ✅ worst Δ **5 / 2 persons** (tolerance ±10) |
| 5 | Every `fc_*` for every area, recomputed here from the raw cells | ✅ **980 municipal + 930 Copenhagen values, 0 mismatches** |
| 6 | `hist_net_dwell` recomputed from `BOL101` + `FOLK1A` | ✅ **98 municipalities, 0 mismatches** |

**22 920 re-pulled cells and 2 008 recomputed indicator values, 0 mismatches.**

The two non-zero numbers are rounding, not error, and both are expected:

- **129 persons** between Σ of the 98 municipalities and `FRDK126`. They are two separately
  published tables of one projection run, each rounded per cell. §3 predicts this and check 5 of
  `validate_forecast.py` reconciles the 20–34 share of it to **0.0004 pp**.
- **5 persons** between Σ kvarterer and the city in `KKFR2026`, against a ±10 tolerance. Same cause.

The recomputed baselines match the documented ones exactly: Denmark's own 20–34 change is
**−7.1092 %** (§3 quotes −7.1092 against `FRDK126`'s −7.1096) and København's is **−3.15 %** (§8).

Three source quirks the verification had to get right, each a way a lazier check would have
silently passed:

- **`FRDK126` has no age-total code**, and its `HERKOMST` elimination value is *"persons of Danish
  origin"* — 5.0 M, not 6.0 M. Asking for `Tid` alone returns that subset without complaining. All
  five origin groups have to be requested and summed.
- **`KKFR2026` spells the sex variable `KON`**; `FRKM126` spells it `KØN`.
- **`total` is the publisher's own `ALDER=TOT` cell, not the sum of the age groups.** Summing ages
  instead produces a ±1–5 person difference on every area and every year — 1 120 false mismatches
  on the first run of this script, which is exactly the artefact §2 documents.

Reproduce with `python3 scripts/verify_forecast_full.py --report` (`--cached` reuses its own pulls;
they land in `data/raw/verify/`, gitignored).

## 8. Infrastructure overlay (v2.1)

The curated layer of major transport and public projects — 51 projects with geometry, their status,
budget and opening year — has its own document: [`docs/INFRA.md`](INFRA.md). It covers the schema,
the `geometry_source` vocabulary, the status words, every source with its licence, the twice-yearly
refresh procedure and the known gaps. The data lives in `data/external/infra_projects.csv` (the list
of record), `data/geo/infra_projects.geojson` (built) and `data/processed/infra_index.json` (which
projects serve each municipality, postal code and quarter).

### Deliberately not automated

| left manual | why |
|---|---|
| **Plandata.dk planning pipeline** (kommuneplanrammer → planned housing capacity per area) | An option, not a decision: the WFS is open and would give a "planned m² per area" indicator, but plot ratios and allowed use need interpretation per municipality before the number means anything. |
| **Vejdirektoratet's geocloud WFS** (road project alignments) | Login-gated; the open Fingerplan layers plus OpenStreetMap cover what the overlay needs. |
| **A national register of planned infrastructure** | There is none. Anlægsstatus is a PDF of state projects, the Fingerplan covers Greater Copenhagen only, and the rest lives on each agency's own pages — which is why the project list is curated by hand and every row carries its source. |

### Planned for v2.2

**Public buildings overlay from BBR (Datafordeler):** existing public-use buildings (`byg021BygningensAnvendelse`
42x — schools, institutions, hospitals, offices of public administration) plus buildings under
construction or with an open building case. The BBR schema for building cases has to be verified
first — the fields and their coverage are not confirmed yet.


## 9. Public buildings (BBR)

Schools, daycare, health and culture buildings from the same register as §3.4, sliced by use instead of
dwellings. Method, code lists and caveats: [`docs/PUBLIC_BUILDINGS.md`](PUBLIC_BUILDINGS.md).

- **Codes** `byg021BygningensAnvendelse` **410–449**, grouped into education (42x), institutions (44x),
  health (43x), culture (41x). The exact code and its official label stay on every record.
- **Existing** = status **6 Opført**. Statuses 9/10/11/13/14 are closed versions of re-coded buildings and
  are never counted.
- **Open building case** = status 2/3 joined through `BBR_Sagsniveau` to `BBR_BBRSag`, drawn only while the
  permit (`sag003`, else `sag002`) is **three years old or less**; older ones are counted in the area panel
  but never mapped.
- **Why there is no "planned buildings" layer:** measured 2026-09-23 on 290 open cases — **1** carried an
  expected completion date, 91 % a permit date, and the median permit in København was **4.1 years** old.
  BBR status 3 mostly means a case was never closed, so the layer reports case activity, not a pipeline.
- **Coordinates**: `byg404Koordinat`, and DAR (`husnummer` → `DAR_Adressepunkt`) for the 83 % of open-case
  buildings BBR has not placed. **Names**: OpenStreetMap within 60 m, 30 % of the metro set.
- **Coverage**: the Copenhagen metro set — København and the 18 contiguous suburban municipalities,
  7 517 buildings (6 769 existing, 257 recent open cases, 491 stale). Everywhere else the indicators are
  empty and no PUBLIC line appears.
- **Extending it**: `python3 scripts/fetch_public_buildings.py --kommune <code>` (or `--all`) then
  `python3 scripts/build_public.py`; both resume, and the UI picks up whatever files exist.


## 10. School quality (STIL)

FP9 grades, the socioøkonomisk reference, elevtrivsel, elevtal and klassekvotient per school, joined onto
the §9 Education buildings. Method, cube codes, the measured join and the discretion rules:
[`docs/SCHOOLS.md`](SCHOOLS.md).

- **API** `POST https://api.uddannelsesstatistik.dk/Api/v1/statistik`, Bearer key in `.env`
  (`UDDSTAT_API_KEY`), paged on `side`. The cube catalogue is `POST /Api/v1/skema` — found through the
  OpenAPI spec at `/swagger/v1/swagger.json`, documented nowhere in `/GetStarted`, and it makes guessing
  codes unnecessary (`scripts/fetch_uddstat.py --skema`).
- **Cubes used** (all område `GS`):

  | cube | what it gives |
  |---|---|
  | `KARA/KARAGNS` | FP9 grade average, bundne prøver (+ the number who sat them, the aggregation weight) |
  | `KARA/KARADM` | FP9 dansk and matematik |
  | `TRIV/TRIVIND` | elevtrivsel — generel + faglig, social, støtte og inspiration, ro og orden |
  | `ELEV/ELEVEX` | elevtal, total and by herkomst |
  | `OVER/OVERSKO` | **socioøkonomisk reference** (grade, expected, difference, significance) **and** klassekvotient, per afdeling |
  | `KARA/KARAGNS` at `[Beliggenhedskommune]` and at `[Skoleår]` alone | the kommune and Denmark benchmarks |

- **⚠ `SOCR/SOCREFEX` and `SOCR/SOCREF3ÅR` are NOT used — they return 0 rows.** Both are listed by the
  catalogue and advertise their measures and dimension members, but every detaljering tried (institution
  level, with and without `[Fag]` / `[Prøveform]` / `[Skoleår]`, filtered and national, `tomme_rækker` both
  ways) comes back empty; `SOCR/KVALSOC` reports no dimensions at all, and the `SOCREFSIKK` emne is named
  *SocRef_Bag_Login*. The reference therefore comes from `OVER/OVERSKO`, which spells the verdict
  **`Over niveau` / `Under niveau` / `På niveau`** — not the `Bedre/Dårligere end forventet` the SOCREFEX
  dimension advertises. There is no 3-year variant, and the layer does not synthesise one.
- **Join to BBR**: institutionsnummer → institution register coordinates → **every** building with
  anvendelse **421** within **150 m** (campus rule — a school is one point but a median of several
  buildings). Measured over the 364 metro grundskoler: **325 direct on 421 (89.3 %)**, **+24 on a 420/429
  fallback at the same radius → 349 (95.9 %)**, 15 with no education building, 1 with no coordinate;
  **1 236 school↔building links**. Widening the radius to 250 m was measured and rejected in favour of
  widening the code set. `bbr_match` on each record says which rule fired.
  *(The v2.3 planning note quoted 89.5 % / 97 % — those came from the intake pass that had silently
  dropped København; see the correction box in `docs/SCHOOLS.md` §4. The figures above are the built ones.)*
- **Aggregates** (`school_grade_avg`, `school_socref_diff`, `school_trivsel`, `pupils_per_school`, written
  into `public_index.json` beside the §9 counts): **pupil-weighted over folkeskoler and frie grundskoler
  that publish a value; specialskoler excluded** — their intake makes an average meaningless. Each measure
  is weighted by **its own** denominator: grades and the reference by the pupils who sat the exams, trivsel
  by the pupils who answered. That lands **17 of 19 municipalities within ±0.1 of STIL's own published
  kommune figure** (against 15 when weighting everything by the total roll).
- **Discretion**: a cell under 3 observations — under **5 pupils** for trivsel and the socioøkonomisk
  reference — is **omitted from the response, not nulled**. A missing school can only be counted from the
  outside, against the register. Nothing is ever filled with 0; every dash in the UI carries a tooltip
  saying it is suppressed.
- **Coverage** of the 364 metro grundskoler: grade average **271 (74 %)**, socioøkonomisk reference
  **254 (70 %)**, klassekvotient **280 (77 %)**, elevtrivsel **196 (54 %)**. The gaps are mostly schools
  with no 9th grade (0.–6. klasse) and small schools under the survey floor — not join failures.
- **Cadence**: grades and the socioøkonomisk reference each **September** (for the school year just ended),
  elevtrivsel each **May**, elevtal in the autumn, and the **institution register daily** — the register is
  the volatile one, so its retrieval date is kept next to the cube retrieval date.
- **Licence**: free reuse including commercial. Attribution **"Kilde: Uddannelsesstatistik.dk"** plus the
  retrieval date is required wherever a number is shown, and is carried on every popup, sheet, panel and chart.
- **Extending it**: `python3 scripts/fetch_uddstat.py --schools` then `python3 scripts/build_schools.py`
  (or `make schools`). `build_schools.py` must run **after** `build_public.py` — it rewrites the same
  per-kommune files and the same index.


Sources: Danmarks Statistik API docs (https://www.dst.dk/en/Statistik/brug-statistikken/muligheder-i-statistikbanken/api) · Finans Danmark Boligmarkedsstatistikken (https://finansdanmark.dk/tal-og-data/boligstatistik/boligmarkedsstatistikken/) · Klimadatastyrelsen, DAWA lukker 1. oktober 2026 (https://www.klimadatastyrelsen.dk/om-klimadatastyrelsen/nyheder/nyhedsarkiv/2026/jul/dawa-lukker-d-1-oktober-2026) · Datafordeler transition plan (https://datafordeler.dk/vejledning/transitionsnetvaerk/) · BBR GraphQL (https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/) · boligstat.dk om husleje (https://boligstat.dk/boligstat/dokumenter/omhusleje.html) · Landsbyggefonden Huslejestatistik 2026 (https://lbf.dk/viden/statistikker/huslejestatistik/huslejestatistik-2026) · DST STRAF11 documentation (https://www.dst.dk/documentationofstatistics/c1ac7749-1e15-4d3a-8ed0-fb2d26a9fe93) · Plandata WFS (https://geoserver.plandata.dk/geoserver/wfs?request=GetCapabilities&service=WFS) · Eurostat API (https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10r_3gdp?geo=DK011&unit=EUR_HAB&time=2023) · Frie geografiske data, vilkår (https://dataforsyningen.dk/asset/PDF/rettigheder_vilkaar/Vilk%C3%A5r%20for%20brug%20af%20frie%20geografiske%20data.pdf)

## 11. Test property pin and the Analysis sheet (v2.4)

One coordinate read against every layer above. It adds **no new source** — the only new *file* is
`dist/geo/kommuner_lookup.json`, the DAGI kommune rings (99 kommuner, simplified 0.0005°, 911 kB)
built by `scripts/build_dashboard.py` and fetched lazily, so a pin can be placed in the right
municipality rather than in the municipality of its postal code. Holes are kept: Frederiksberg is a
hole in København. Accepted link formats, the short-link limitation, the distance method, the layer
pills and hash parameters, coverage and the privacy wording:
[`docs/ANALYSIS.md`](ANALYSIS.md). Verification: §7d.
