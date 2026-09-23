# Infrastructure projects layer

**Status:** v2.1 (in progress) · data only, no UI yet
**Output:** `data/geo/infra_projects.geojson` — a curated FeatureCollection (WGS84) of the major
transport and urban-development projects that will change accessibility in Denmark over the next
two decades.

## 1. Why it is curated by hand

There is no Danish open dataset of "infrastructure projects". The money and the timetable live in
Transportministeriet's half-yearly report (a PDF), the geometry lives in a planning WFS that covers
Greater Copenhagen only, and everything else has to come from OpenStreetMap or be left empty. So the
list of record is a CSV a human maintains, `data/external/infra_projects.csv`, and the build only
resolves geometry, computes the municipalities a project touches, and writes GeoJSON.

The rule for every figure: **if the source does not state it, the field stays empty.** No budget,
opening year or agency is estimated or interpolated to fill a gap.

Geometry is the one exception, and it is labelled. Where no source publishes an alignment, the row may
carry a **schematic** corridor drawn by hand so the project is visible on a map — such a feature has
`schematic: true` and a `notes` line beginning "schematic corridor — not an official alignment". Ten of
the 34 features are schematic — eight drawn by hand and the two M5 lines drawn through their stations;
they show *where* a project runs, never how it will be built, and must not be measured against.

## 2. Schema

`data/geo/infra_projects.geojson` — `FeatureCollection`, WGS84 (`EPSG:4326`), one feature per CSV row.

| property | type | meaning |
|---|---|---|
| `id` | slug | stable identifier, e.g. `m5-phase-1`; stations use `<line>-st-<name>` |
| `name` | string | project name, Danish where that is the published name |
| `label_short` | string | short map label for zoomed-out views ("M5 phase 1", "Ring 3"); from the CSV column of the same name, defaulting to the first three words of `name` |
| `type` | enum | `metro` · `letbane` · `brt` · `rail` · `road` · `bridge_tunnel` · `urban_dev` · `hospital` · `university` · `public_building` (a state building: courthouse, ministry, parliament) |
| `status` | enum | `study` · `decided` · `construction` · `opened` (see §5) |
| `open_year` | int \| null | currently expected opening year |
| `open_year_original` | int \| null | opening year first decided, when the source names one — the delay is the interesting number |
| `budget_mdkk` | number \| null | approved total expenditure, mio. DKK, in the price level the source states (noted per row) |
| `agency` | string | Banedanmark, Vejdirektoratet, Sund & Bælt, Metroselskabet, By & Havn, … |
| `kommuner` | list of 3-digit codes | municipalities the geometry touches — **computed** by the build, not maintained by hand |
| `parent_id` | slug \| null | stations point at their line |
| `source_url` | url | required on every row |
| `source_doc` | string \| null | e.g. `Anlægsstatus 1H 2026 p. 34` |
| `geometry_source` | string \| null | how the geometry was resolved (§4), kept in the output so every shape can be traced |
| `updated` | date | build date |
| `map` | bool | default `true`. `false` keeps the project off the map while leaving it in the file — for a programme with no alignment (`signalprogrammet`, nationwide signalling), which belongs in the pipeline table only |
| `schematic` | bool | true when the geometry was drawn by hand (`manual:…`) or derived from station points (`stations`) — it shows where a project runs, not how it will be built |
| `kommuner_override` (CSV only) | list of codes | used when the spatial join returns nothing, e.g. Lynetteholm, which is reclaimed land outside every DAGI municipality polygon |
| `notes` | string \| null | caveats: schematic geometry, price level, phased openings |

Geometry: `LineString` / `MultiLineString` for alignments, `Point` for stations, `Polygon` /
`MultiPolygon` for development areas, and `null` when no source has one.

## 3. Sources

| source | what it gives | access | licence / attribution |
|---|---|---|---|
| **Transportministeriet, "Status for anlægs- og byggeprojekter" (Anlægsstatus), 1. halvår 2026** — [PDF, 86 pp.](https://www.trm.dk/media/vtuldjoz/anlaegsstatus-1-halvaar-2026.pdf) | budgets, spend to date, original and current opening year, responsible agency | PDF, read with `scripts/parse_anlaegsstatus.py` | CC BY-NC-ND (stated on p. 2) — cite *Transportministeriet* |
| **Fingerplan 2019 WFS**, Plan- og Landdistriktsstyrelsen — `https://gisp.bpst.dk/fingerplan19/wfs` | planned alignments and reservations in Greater Copenhagen (metro, light rail, rail, motorways, corridors under study) | WFS 2.0, no key, `fingerplan19:theme-<layer>` | *Plan- og Landdistriktsstyrelsen, Fingerplan 2019* |
| **OpenStreetMap** via Overpass | geometry outside the Fingerplan's area, and existing features used as indicative locations | Overpass API, cached in `data/raw/osm/` | **© OpenStreetMap contributors**, ODbL — required wherever this geometry is shown |
| **Metroselskabet M5** — https://metroselskabet.dk/m5/ | station list and phasing (phase 1 2036, phase 2 2045) | web | cite *Metroselskabet* |
| Hovedstadens Letbane, Aarhus Letbane, By & Havn, Femern A/S | opening years and project pages for what Anlægsstatus does not cover | web | cite the company |

The source PDFs are **not committed** (`data/external/*.pdf` is gitignored); the CSV and the scripts
reproduce everything derived from them.

**The fetched geometry is committed**, like the other vendored boundaries in `data/geo/`:
`data/raw/fingerplan/*.geojson` and the Overpass answers in `data/raw/osm/*.json`. The build must work
offline and in CI, and both services are slow and rate-limited (Overpass answers 429 and 504 under
load). Re-fetch only when a plan changes: delete the file and re-run the fetch or the build.

### Attribution string for the map footer

> Indeholder data fra Plan- og Landdistriktsstyrelsen (Fingerplan 2019) og Transportministeriet
> (Anlægsstatus). Enkelte linjeføringer er hentet fra OpenStreetMap, © OpenStreetMap contributors (ODbL).

## 4. `geometry_source` vocabulary

| form | resolves to |
|---|---|
| `fingerplan:<layer>:all` | every feature of a vendored Fingerplan layer, merged |
| `fingerplan:<layer>:<attr>=<value>` | the features of that layer whose attribute matches, e.g. `fp19vp_motorvejanlaeg_udv:kode=2` |
| `osm:<Overpass QL fragment>` | an Overpass query, e.g. `osm:way["name"="Storstrømsbroen"](54.90,11.80,55.05,12.00)` |
| `manual:<lon>,<lat>` | a single coordinate |
| `manual:wkt:<WKT>` | a geometry written out by hand — a **schematic** corridor or area, never an official alignment; the row's `notes` open with "schematic corridor — not an official alignment" and the feature carries `schematic: true` |
| `stations` | a line drawn through this project's own station points, in CSV order — used where no alignment is published (M5). Always flagged as indicative in `notes` |
| *(empty)* | no geometry; the feature still carries its figures |

The build reduces what a source returns to what the project needs: a station gets the representative
point of whatever was matched, a corridor gets the merged lines simplified to ~20 m, a development
area gets a polygon when the source has one. Two Fingerplan motorway reservations carry no project
name in the data and are identified by location — that is recorded in each row's `notes`.

## 5. Status vocabulary

| status | means |
|---|---|
| `study` | under investigation, no construction decision — no budget or opening year is published yet (Østlig Ringvej, Kattegat, HH, Aarhus Letbane etape 2) |
| `decided` | politically decided and financed, construction not started (M5) |
| `construction` | being built (Femern, Storstrømsbroen, Nordhavnstunnel, Ny bane over Vestfyn) |
| `opened` | in service; kept in the layer because it still explains today's accessibility (Ring 3 letbane, København–Ringsted) |

A project that opens in stages keeps the **last** stage in `open_year` and explains the stages in
`notes` (Storstrømsbroen: road 2026, rail 2027).

## 6. Refresh procedure

Anlægsstatus appears twice a year (spring and autumn). Per edition:

1. Download the new PDF to `data/external/anlaegsstatus_<edition>.pdf` (gitignored).
2. `python3 scripts/parse_anlaegsstatus.py --pdf data/external/anlaegsstatus_<edition>.pdf` and read
   the project table: approved total expenditure and current opening year per project.
3. For every row of `data/external/infra_projects.csv` that the report covers, update `budget_mdkk`,
   `open_year`, `open_year_original`, `status` and `source_doc` (`Anlægsstatus <edition> p. n`).
   A project that has opened moves to `status: opened`; a project the report drops keeps its last
   known figures and says so in `notes`. Values the report withholds (`[fortroligt]`) or has not
   settled (`Under afklaring`) are left empty.
4. Check the price level: the report restates everything in the edition's prices, but a few projects
   (Femern) are quoted in their own act's price level — note it on the row.
5. Re-run the geometry only when a plan changes: `python3 scripts/fetch_infra_fingerplan.py`
   (Fingerplan is static until a new Fingerplan is issued) and `python3 scripts/build_infra.py`.
   Overpass answers are cached under `data/raw/osm/`; delete a cache file to re-query it.
6. Commit `data/external/infra_projects.csv` and `data/geo/infra_projects.geojson`, and bump the
   `updated` date (the build sets it).

Separately: when Metroselskabet, Aarhus Letbane or By & Havn publish a new timetable, update the row
and its `source_url`.

## 7. Known gaps

- The Fingerplan covers **Greater Copenhagen only**. Alignments on Fyn and in Jylland come from OSM
  or are empty; the layer is not a national geometry register.
- M5's alignment is not published as open data. The line is drawn through its station points and the
  stations that have no site yet sit at the named landmark — both are marked in `notes`.
- Anlægsstatus is a report on **state** construction projects. Company projects (Metroselskabet,
  Hovedstadens Letbane, By & Havn, Aarhus Letbane) have no budget in it, so those rows have
  `budget_mdkk: null` unless another source states a figure.
- Ten features are **schematic** (`schematic: true`). Eight are drawn by hand because no source
  publishes an alignment — Kattegat, Aarhus Letbane etape 2, Storstrømsbroen, Nordhavnstunnel,
  Ringsted–Odense, Signalprogrammet and the Lynetteholm and Nordhavn areas — and the two M5 lines are
  drawn through their station points. Signalprogrammet is nationwide, so its line is only a sketch of
  the main København–Odense–Fredericia–Aarhus–Aalborg corridor and the project carries `map: false`. They are fit for showing *where* a
  project is, not for any measurement.
- `kommuner` is computed from the geometry; `kommuner_override` covers what the join cannot answer.

## 8. Added 2026-09-23 (route A: public projects)

Fifteen non-transport and remaining transport projects were added, each verified against an official
publisher on 23 September 2026. Where a figure was not published, the field is empty — the research
notes for each row sit in its `notes`.

| project(s) | source used |
|---|---|
| Nyt Hospital Nordsjælland, Nyt Hospital Bispebjerg, Ny Psykiatri Bispebjerg | Region Hovedstaden's agenda system, `edagsorden.regionh.dk` — regionsrådsmøde 15.09.2026 (quarterly reports) and 07.04.2026. www.regionh.dk and godtsygehusbyggeri.dk's per-project pages could not be used: the first is behind a bot check, the second returns 404 |
| Nyt OUH | Region Syddanmark, *Årsrapport og ledelsesberetning 2025*; ouh.dk project pages |
| Nyt Aalborg Universitetshospital | Region Nordjylland, `byghospitalsbyen.rn.dk` (Indvielse, Hospitalsbyen i tal), `aalborguh.rn.dk` (flytteplan), Regnskab 2025 |
| Aalborg Plusbus, BRT 400S, BRT 200S | Movia, *BRT-katalog: Seks BRT-projekter på tværs af Danmark* (jan. 2021); Vejdirektoratet's project pages for 400S and 200S |
| BRT Ringvejen, Aarhus | Aarhus Kommune, *Aftale om grøn mobilitetsplan* (7 Aug 2024) |
| BRT/letbane Frederikssundsvej | Københavns Kommune, Økonomiudvalget 22.01.2025, punkt 7 |
| Universitetsbyen and Universitetsbyen Syd | Aarhus Universitet, *Udviklings- og byggeprojekter i Aarhus* |
| DTU Bygning 330 | DTU, *DTU Space nye bygning* |
| RUC Pergola, Fremtidens Folketing | Bygningsstyrelsen, bygst.dk project pages |

Two finished kvalitetsfond hospitals are kept as **landmark `opened` rows** because they still explain
today's hospital geography: Regionshospitalet Gødstrup (2022, 3.150 mio. kr.) and AUH Skejby (2019,
6.350 mio. kr., accounts closed 2024) — sources: Region Midtjylland's Gødstrup timeline and Godt
Sygehusbyggeri's AUH article.

**Checked and deliberately left out:** Nyt Hospital Herlev (fully in use 2022) and Nyt Hospital
Hvidovre (ultimo 2024) — finished kvalitetsfond projects with no remaining stage. Københavns Universitet Nørre Campus / Panum —
no current large stage is published anywhere official. Odense BRT, BRT Ring 2½, BRT Hillerødmotorvejen,
BRT Roskilde and BRT Helsingør — no such decided project exists. BRT 150S, BRT Randers, Plusbus 2 and
BRT i Lautrup — mulighedsstudie only, with no decision, budget or year published.

**Figures that could not be verified and are therefore empty:** Aalborg Plusbus's opening date (the
official Aalborg Kommune and NT pages now 404; September 2023 appears only in press), Nyt Hospital
Bispebjerg's opening year (a 2030–2032 window, not a year), Universitetsbyen Syd's move-in years (two
official AU pages disagree), and every budget marked "not published" above.
