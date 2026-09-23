# Public buildings layer (BBR)

**Status:** v2.2 · Copenhagen metro set — København and the 18 contiguous suburban municipalities
**Output:** `data/processed/public/<kommune>.json` (loaded on demand, like the Buildings layer) and
`data/processed/public_index.json` (counts per municipality, postal code and Copenhagen quarter).

Schools, daycare, health and culture buildings from BBR — the standing stock, plus the buildings that
currently have an open building case. Same register as the Buildings (Micro) layer, different slice.

## 1. What is in it

| kind | BBR status | meaning |
|---|---|---|
| `existing` | 6 Opført | the standing public building: area, year built, floors |
| `case` | 2 Projekteret · 3 Under opførelse | the building has an **open building case**; shown with its permit date and age |

Statuses 9 Afsluttet, 10 Historisk, 11 Fejlregistreret, 13 and 14 are **closed versions** of a building —
typically the old row left behind when a building was re-coded from a phased-out code to a finer one
(440 → 441). They are never counted; counting them would double-count the stock.

Codes (BBR *BygAnvendelse*, [teknik.bbr.dk](https://teknik.bbr.dk/kodelister/0/1/0/BygAnvendelse)), grouped into four categories:

| category | codes |
|---|---|
| education | 420 (udfases) · 421 Grundskole · 422 Universitet · 429 Anden undervisning/forskning |
| institutions | 440 (udfases) · 441 Daginstitution · 442 Servicefunktion døgninstitution · 443 Kaserne · 444 Fængsel · 449 Anden institution |
| health | 430 (udfases) · 431 Hospital og sygehus · 432 Hospice · 433 Sundhedscenter, lægehus · 439 Anden sundhed |
| culture | 410 (udfases) · 411 Biograf, teater · 412 Museum · 413 Bibliotek · 414 Kirke · 415 Forsamlingshus · 416 Forlystelsespark · 419 Anden kultur |

Each record keeps its exact code and the code list's own label, so a regrouping later does not need a refetch.

## 2. The building case, and why it is not a pipeline

A building carries no case reference. The link runs

```
BBR_Bygning ← BBR_Sagsniveau (sagsdataBygning / stamdataBygning) → BBR_BBRSag
```

and of the cases found for a building the layer keeps the newest **open** one: no
`sag010FuldfoerelseAfByggeri` and status not 9 Afsluttet / 14 Henlagt.

### Measurement, 23 September 2026 (pilot: 290 open-case buildings in 101 + 147)

| what | result |
|---|---|
| resolve to a case at all | **290 / 290** |
| have an **open** case | 290 / 290 |
| have an expected completion date (`sag009ForventetFuldfoertDato`) | **1 / 290 (0.3 %)** |
| have a permit date (`sag003Byggetilladelsesdato`) | 265 / 290 (91 %) |
| have a start date (`sag005Paabegyndelsesdato`) | 158 / 290 (54 %) |
| median age of the permit/case date, København | **4.1 years** (111 of 249 older than 5 years, 40 older than 10) |
| had a coordinate in BBR (`byg404Koordinat`) | 50 / 290 (17 %) — 100 % of *existing* buildings have one |

**This is why the layer says "open building case" and never "planned" or "under construction".** BBR's
status 3 largely means nobody closed the case, not that something is being built; there is no
completion date to show; and the register is owner-reported. Every case popup carries the line
*"Owner-reported BBR case — not a confirmed construction schedule"*.

Consequences in the layer:

- Only cases whose permit (or case) date is **three years old or less** are drawn on the map.
- Older ones are counted and listed in the area panel under *Stale open cases (permit > 3 yrs)*,
  never on the map.
- There is no forward-looking "planned buildings" indicator. `public_recent_cases_n` counts recent
  case activity and says so in its own caveat.

## 3. Coordinates and names

- `byg404Koordinat` (EPSG:25832 → WGS84) where BBR has it — every existing building, 17 % of the cases.
- Otherwise the building's `husnummer` → `DAR_Husnummer` → `DAR_Adressepunkt.position`, which also
  gives the street address and postal code. Across the metro set this placed every open-case building
  BBR had not placed, so **all of them have a point**.
- Names are optional and come from OpenStreetMap (`amenity=school|kindergarten|university|college|
  hospital|clinic|doctors|library|theatre|museum` with a `name`) when a named feature lies within
  **60 m**: 2 243 of 7 517 buildings in the metro set got one (§4b). Otherwise the popup shows the address.
  Attribution: **© OpenStreetMap contributors (ODbL)**.
- Placement into postal codes and Copenhagen quarters is point-in-polygon, as in the BBR Micro layer.

## 4. Indicators

| indicator | meaning |
|---|---|
| `public_m2_per_1000` | floor area of existing public buildings per 1,000 inhabitants |
| `public_recent_cases_n` | public buildings with an open case whose permit is ≤ 3 years old |

Both sit in the *Growth signals* group, are hidden from the chip row, and carry the pilot-coverage
caveat: only municipalities whose BBR pull has been run have values (§4b).

## 4b. Coverage — Copenhagen metro set, 23 September 2026

`--metro` covers København and the 18 contiguous suburban municipalities (the same list the BBR
dwellings layer uses). **7 517 buildings** in 19 municipalities: 6 769 existing, 257 recent open
cases (permit ≤ 3 years) and 491 stale ones. Fetch took 58 s with 3 workers; every open-case building
without a BBR coordinate was placed through DAR, so all of them are mappable.

| municipality | existing | recent cases | stale cases | named from OSM |
|---|---|---|---|---|
| København (101) | 2 542 | 97 | 152 | 847 (30 %) |
| Frederiksberg (147) | 462 | 18 | 23 | 151 (30 %) |
| Ballerup (151) | 287 | 12 | 11 | 100 (32 %) |
| Brøndby (153) | 157 | 6 | 3 | 63 (38 %) |
| Dragør (155) | 93 | 0 | 3 | 31 (32 %) |
| Gentofte (157) | 349 | 6 | 15 | 113 (31 %) |
| Gladsaxe (159) | 267 | 19 | 19 | 93 (30 %) |
| Glostrup (161) | 194 | 9 | 58 | 82 (31 %) |
| Herlev (163) | 149 | 9 | 21 | 68 (38 %) |
| Albertslund (165) | 162 | 6 | 14 | 31 (17 %) |
| Hvidovre (167) | 261 | 10 | 1 | 77 (28 %) |
| Høje-Taastrup (169) | 276 | 14 | 8 | 102 (34 %) |
| Lyngby-Taarbæk (173) | 513 | 22 | 40 | 115 (20 %) |
| Rødovre (175) | 150 | 4 | 15 | 45 (27 %) |
| Ishøj (183) | 125 | 2 | 12 | 46 (33 %) |
| Tårnby (185) | 205 | 4 | 11 | 81 (37 %) |
| Vallensbæk (187) | 58 | 1 | 4 | 13 (21 %) |
| Furesø (190) | 221 | 8 | 65 | 100 (34 %) |
| Rudersdal (230) | 298 | 10 | 16 | 85 (26 %) |
| **total** | **6 769** | **257** | **491** | **2 243 (30 %)** |

OSM name match by category: education 1 158/2 687 (43 %), institutions 712/2 740 (26 %), health
135/616 (22 %), culture 238/1 474 (16 %). A building without a match shows its address instead.

Municipalities outside this set have no file: their indicators are empty and no PUBLIC line appears on
their area card. Adding one is `fetch_public_buildings.py --kommune <code>` then `build_public.py`.

### Drawing density

Copenhagen alone holds 2 542 existing public buildings, so the map thins them by zoom:

| zoom | drawn |
|---|---|
| < 9 | recent open cases only (257 in the metro set) |
| 9–12 | open cases + existing buildings ≥ 1 000 m² (2 080) |
| ≥ 13 | everything (7 026) |

The legend says which rule is in force. Per-municipality files load for whatever is in the viewport and
stay cached for the session.

### The legend is the filter

The legend always lists **all four categories**, whatever the filter, plus the existing / open-case key.
A category that is switched off is greyed, struck through and drawn with a hollow swatch — it is still a
click away from coming back. *ONLY* (or shift-click) isolates one; *All* resets. With every category off
the legend stays and reads **All categories hidden · Show all**, and the counts line says *nothing drawn*.
The counts always describe what is actually on the map, after the filter and the zoom rule.

Isolating Education turns on grade mode (see `SCHOOLS.md`): the FP9 ramp is appended **under** the
category rows, never in place of them.

The filter rides in the hash as `&pub=edu,inst,health,culture` and `&pubkind=existing|open`. All four off
is `&pub=none` — a real state that reopens hidden. An empty or unreadable `pub=` means *all*, so a
hand-typed link cannot blank the map.

A legend box with nothing to say is hidden, never left as an empty white bar over the map
(`.maplegend:empty`). The public and infra legends stack in one scrolling column at the top right.

## 5. Refresh

```bash
python3 scripts/fetch_public_buildings.py --kommune 0101,0147   # BBR + the cases + DAR geocoding
python3 scripts/build_public.py --kommune 0101,0147             # → data/processed/public/*.json + index
make build
```

The fetch needs `DATAFORDELER_API_KEY` in `.env`. Raw pulls under `data/raw/public/` and
`data/raw/dar/public_adresse.jsonl` are gitignored; the processed files are committed, so the
dashboard builds without a key. Adding a municipality is a matter of running both scripts with its
code — the UI picks up whatever files exist.

## 6. Caveats to repeat wherever the numbers are shown

- **Owner-reported.** BBR is maintained by owners and municipalities; area, use and status are as
  reported, not as surveyed.
- **Phased-out codes.** 410 / 420 / 430 / 440 are being replaced by the finer codes but are still in
  use, so a category total mixes both. The exact code is kept on every record.
- **Pilot coverage.** Only the municipalities listed in `public_index.json → kommuner` have data;
  everywhere else the indicators and the area line are empty rather than zero.
- **An open case is not a schedule.** See §2.
