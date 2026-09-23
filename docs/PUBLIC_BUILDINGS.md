# Public buildings layer (BBR)

**Status:** v2.2 · pilot on København (101) and Frederiksberg (147)
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
  gives the street address and postal code. In the pilot this placed the remaining 240 cases, so
  **290 / 290 have a point**.
- Names are optional and come from OpenStreetMap (`amenity=school|kindergarten|university|college|
  hospital|clinic|doctors|library|theatre|museum` with a `name`) when a named feature lies within
  **60 m**: 998 of 3,294 pilot buildings got one. Otherwise the popup shows the address.
  Attribution: **© OpenStreetMap contributors (ODbL)**.
- Placement into postal codes and Copenhagen quarters is point-in-polygon, as in the BBR Micro layer.

## 4. Indicators

| indicator | meaning |
|---|---|
| `public_m2_per_1000` | floor area of existing public buildings per 1,000 inhabitants |
| `public_recent_cases_n` | public buildings with an open case whose permit is ≤ 3 years old |

Both sit in the *Growth signals* group, are hidden from the chip row, and carry the pilot-coverage
caveat: only municipalities whose BBR pull has been run have values.

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
