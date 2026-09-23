# Schools layer (STIL education statistics)

**Status:** v2.3 · intake only — API client and institution register are in, **no indicators and no UI yet**
**Client:** `scripts/fetch_uddstat.py` · **Cache:** `data/raw/uddstat/<emne>_<underemne>.jsonl` + `.meta.json`
**Register:** `data/external/institutionsregister.csv`

School-quality measures per school — FP9 grades, socioøkonomisk reference, elevtrivsel, elevtal,
klassekvotient — joined onto the BBR *Grundskole* buildings already in the Public buildings layer.

## 1. Sources

| what | where | note |
|---|---|---|
| Statistics | `POST https://api.uddannelsesstatistik.dk/Api/v1/statistik` | `Authorization: Bearer <UDDSTAT_API_KEY>`, JSON body, paged on `side` |
| Cube catalogue | `POST https://api.uddannelsesstatistik.dk/Api/v1/skema` | drill-down; see §2 |
| OpenAPI spec | `GET /swagger/v1/swagger.json` | the only machine-readable contract; `/api-docs` is the ReDoc page for it |
| DCAT metadata | `GET /Metadata/v1/DCAT-AP-DK` | RDF/XML, ~400 kB; dataset-level for data.gov.dk, not cube-level |
| Online tool | [api.uddannelsesstatistik.dk/OnlineTool](https://api.uddannelsesstatistik.dk/OnlineTool) | builds a query body by hand; not needed, `--skema` covers it |
| Institution register | [uddannelsesstatistik.dk](https://uddannelsesstatistik.dk) → Institutionsregister | 4 976 active institutions, 30 columns, semicolon-separated, **UTF-8 with BOM** |

**Licence.** Free reuse including commercial. Attribution is required wherever a number is shown:
**"Kilde: Uddannelsesstatistik.dk"** plus the retrieval date. Every cached file records both in its
`.meta.json`; the UI must carry the same line.

## 2. Cube codes (verified 23 September 2026)

`/Api/v1/skema` is a drill-down: `{}` → områder, `{område}` → emner, `{område,emne}` → underemner,
`{område,emne,underemne}` → that cube's `detaljer` (dimensions, with member counts), `nøgletal`
(measures) and `rapporter`. Adding `{detalje:"<dimension>"}` lists that dimension's members.
So no guessing is needed — `python3 scripts/fetch_uddstat.py --map` reprints the table below.

Område **GS** (Grundskolen) has 17 emner. The five datasets this project wants:

| dataset | emne / underemne | measures to take |
|---|---|---|
| **FP9, bundne prøver** | `KARA` / `KARAGNS` — *Gennemsnit i obligatoriske og bundne prøver* | `Gennemsnit i bundne prøver`, `Gennemsnit i bundne 9.-klasseprøver`, `Antal elever med alle bundne prøver` |
| **FP9, dansk + matematik** | `KARA` / `KARADM` — *Gennemsnit i dansk og matematik 9. klasse* | `Gennemsnit - Dansk bundne prøver`, `Gennemsnit - Matematik bundne prøver`, `Andel elever med mindst 2 i dansk og matematik` |
| **Socioøkonomisk reference** | `SOCR` / `SOCREFEX` (1-årig) and `SOCR` / `SOCREF3ÅR` (3-årig) | `Karakter`, `Soc_ref`, `Forskel`, `Signifikant` (the 3-årig cube suffixes each with ` - 3-årig`) |
| **Elevtrivsel** | `TRIV` / `TRIVIND` — *Trivselsindikatorer* | `Indikatorsvar` (the 0–5 score), `Andel Indikatorsvar`, `Antal Indikatorsvar`, plus the ` - Kommunetal` / ` - Landstal` variants for context |
| **Elevtal** | `ELEV` / `ELEVEX` — *Elevtal* | `Antal elever`, `Inklusionsgrad`, `Andel der modtager seg specialundervisning` |
| **Klassekvotient** | `OVER` / `OVERSKO` — *Skoleoverblik* | `Klassekvotient`, `Klassekvotient Kommune`, `Klassekvotient Land`, `Elevtal`, `Samlet elevfravær` |

Useful neighbours found on the way: `KARA/KARAFF` (per fag/fagdisciplin, measure
`Elevgennemsnit (uden vægtning)`), `KARA/KARAMIN2`, `ELEVFRAV`, `KOMP` (kompetencedækning),
`NATI` (testresultater), `SOCREFSIKK` (*SocRef_Bag_Login* — behind a login, not usable),
and the four `KVAL*` kommunerapport cubes, which are the municipal aggregates of the same figures.

### Dimensions that matter

Present on essentially every GS cube:

- `[Institution].[Institutionsnummer]` — **the join key.** Also `[Institution].[Institution]` (name),
  `[Institution].[Afdelingsnummer]` / `[Afdeling]` for the department level, `[Institution].[Institutionstype]`,
  `[Institution].[Beliggenhedskommune]` and `[…kommunenummer]`.
- `[Skoleår].[Skoleår]` — `"2024/2025"`. `SOCREF3ÅR` uses `[Skoleår].[Skoleårsinterval (3-årig)]`
  with values like `"2022/23-2024/25"`.

Cube-specific:

- `TRIVIND`: `[Trivselsindikator].[Trivselsindikator]` has exactly the five we want —
  **Generel trivsel** (the samlet indicator) plus **Social trivsel**, **Faglig trivsel**,
  **Støtte og inspiration**, **Ro og orden**. Also `[Klassetrin]`, `[Køn]`, `[Herkomst]`,
  and `[Trivselsindikator Svarintervaller]` for the response distribution.
- `SOCREFEX` / `SOCREF3ÅR`: `[Socioøkonomisk Reference Forskel].[1 årig - …]` carries the significance
  verdict as text — `Bedre end forventet`, `Dårligere end forventet`, `På Niveau`, `<fejl>`.
  Treat `<fejl>` as missing. Also `[Fag]`, `[Fagdisciplin]`, `[Prøveform]`.
- `ELEVEX`: `[Herkomst].[Herkomst]` (5 members) and `[Herkomst].[Herkomstgruppe]` (4) — so elevtal
  by herkomst **is** available, as hoped.
- `OVERSKO` is the odd one out: it has `[Institution].[Afdelingsnummer]` and `[Afdeling]` but
  **no `[Institutionsnummer]`**. Klassekvotient must be joined on afdelingsnummer, or read from
  `ELEVEX` + a class count instead.

### Coverage

Latest three school years, confirmed to carry data (not just to be listed as members):

| cube | earliest | latest three |
|---|---|---|
| `KARA/KARAGNS`, `KARA/KARADM` | 2010/2011 | **2023/2024 · 2024/2025 · 2025/2026** |
| `TRIV/TRIVIND` | 2014/2015 | **2023/2024 · 2024/2025 · 2025/2026** |
| `ELEV/ELEVEX` | 2008/2009 | **2023/2024 · 2024/2025 · 2025/2026** |
| `OVER/OVERSKO` | 2018/2019 | **2023/2024 · 2024/2025 · 2025/2026** |
| `SOCR/SOCREF3ÅR` | 2007/08-2009/10 | **2020/21-2022/23 · 2021/22-2023/24 · 2022/23-2024/25** |

National `Gennemsnit i bundne prøver`: 7,5 (2023/24) · 7,6 (2024/25) · 7,5 (2025/26).

## 3. Discretion rules — read before building any indicator

**Suppressed cells are omitted from the response, not returned as null.** A cube drops any cell with
fewer than 3 observations, and fewer than **5 pupils** for trivsel and socioøkonomisk reference.

Consequences, all of which have bitten this kind of dataset before:

1. **An absent row means "too small to publish", never "zero" and never "no school".** Never fill a
   missing value with 0, and never let a missing row drop a school out of a denominator silently.
2. `tomme_rækker: true` returns the empty combinations of the dimensions you asked for, but it does
   **not** un-suppress anything — the value comes back blank.
3. The finer the `detaljering`, the more is suppressed. Asking for trivsel by indicator × klassetrin ×
   køn at school level will hollow out small schools. Take the coarsest cut that answers the question.
4. Small schools, specialskoler and new schools are suppressed far more often than large folkeskoler,
   so any ranking built from present-values-only is biased toward big schools. Show *n* alongside
   every school-level figure, and mark suppressed as "ikke offentliggjort", distinct from "no data".
5. `dknum()` in the client returns `None` for blank and for the `-` / `..` / `*` markers, never 0.

Values arrive as Danish-formatted strings: `"2.351"` is 2351, `"7,3"` is 7.3, `"100,0 %"` is 100.0.
`dknum()` handles all three. The raw strings are what gets cached, so a parsing fix never needs a refetch.

## 4. Join plan

```
STIL cube row
  └── [Institution].[Institutionsnummer]          e.g. "101172"
        └── institutionsregister.csv : Institutionsnummer
              └── "Geokode: Breddegrad" / "Geokode: Længdegrad"   (WGS84, already in the file)
                    └── nearest BBR building, anvendelse 421, within 150 m
                          └── data/processed/public/<kommune>.json
```

No DAR geocoding is needed — the register already carries coordinates, and in the metro set
**100 %** of grundskole rows have them.

**Campus rule.** A school is one register point but usually several buildings. Attach the school to
**every** 421 building within 150 m of the register point, not just the nearest one. In the metro set
that is 885 school↔building links for 205 schools, a median of 4 buildings per school (range 1–12).
Consequence: a school-level figure must not be summed over its buildings — it is one value painted
onto several footprints. Keep the school as the record and the buildings as its geometry.

**Reverse direction.** A 421 building with no school within 150 m is left unlabelled; it stays a plain
public building. 1 343 of the metro 421 buildings exist against 229 schools, so most buildings are
outbuildings, halls and annexes rather than unmatched schools.

### Measured, 23 September 2026 — the 19 metro kommuner

| what | result |
|---|---|
| register rows, all types, all of Denmark | 4 976 |
| grundskole-type rows in the 19 metro kommuner | **229** (155 folkeskoler · 48 friskoler og private grundskoler · 26 specialskoler for børn) |
| of those, with coordinates | **229 / 229 (100 %)** |
| BBR 421 buildings with coordinates, same 19 kommuner | 1 343 |
| schools with ≥1 421 building within 150 m | **205 / 229 (89.5 %)** |
| school→building links | 885 · median 4 per school · max 12 |
| nearest-421 distance, all 229 schools | median **19 m** · p90 71 m · max 361 m |

Efterskoler (195 nationally), specialskoler for voksne, ungdomsskoler, FGU and gymnasier are excluded
by type. The register's type column is **`Institutionstype, navn`** (with `Institutionstype, nr`
alongside); `Enhedsart` is a different axis — of the 229, 176 are *Institution uden enheder*,
37 *Afdeling (underordnet enhed)* and 16 *Hovedskole (institution med enheder)*. Decide before
building indicators whether a Hovedskole and its Afdelinger are one row or several, because the
cubes publish both levels and double-counting here is easy.

### The 24 unmatched schools, and what to do about them

They are not a geocoding failure. They are schools **whose building is not coded 421**: hospital
schools, special-needs units, 10th-grade centres inside erhvervsskoler (TEC, NEXT Ishøj/Ballerup),
and private schools in buildings coded 429. Widening the code set beats widening the radius:

| code set | ≤150 m | ≤250 m |
|---|---|---|
| 421 only | 205 (90 %), 885 links | 213 (93 %), 1 012 links |
| 421 + 420 | 205 (90 %), 926 links | 214 (93 %), 1 062 links |
| **421 + 420 + 429** | **221 (97 %), 1 069 links** | 224 (98 %), 1 283 links |
| 421 + 420 + 422 + 429 | 221 (97 %), 1 079 links | 224 (98 %), 1 320 links |

**Recommendation for the build step:** match 421 first, then fall back to 420/429 for a school with
no 421 hit, keeping the radius at 150 m. That reaches 97 % without the false pairing that 250 m buys.
Adding 422 (Universitet) gains nothing. The remaining ~8 have no education-coded building at all and
should stay listed without geometry rather than be forced onto a neighbour's footprint.

## 5. Cadence

| source | published | refresh |
|---|---|---|
| FP9 grades (`KARA/*`) | each **September**, for the school year just ended | September |
| Socioøkonomisk reference (`SOCR/*`) | with the grades, September | September |
| Elevtrivsel (`TRIV/TRIVIND`) | each **May**, survey run Jan–Mar | May |
| Elevtal (`ELEV/ELEVEX`) | autumn, for the school year then starting | September |
| Skoleoverblik (`OVER/OVERSKO`) | follows the grades | September |
| Institutionsregister | **daily** | with each build; it is the volatile one — schools merge, split and close |
| BBR 421 buildings | via the Public buildings layer, see `docs/PUBLIC_BUILDINGS.md` | with that layer |

The register is the moving part. A school that closed or merged keeps its rows in the cubes under the
old institutionsnummer, so a join against a freshly pulled register will silently drop it. Keep the
retrieval date of the register next to the cube retrieval date and do not assume they agree.

## 6. Caveats to repeat wherever the numbers are shown

- **"Kilde: Uddannelsesstatistik.dk"** and the retrieval date. Required by the licence.
- A blank is "ikke offentliggjort" (under 3 obs, under 5 pupils for trivsel/socioøkonomisk reference),
  not a zero and not a bad school.
- A grade average is **not** a quality ranking. The socioøkonomisk reference exists precisely because
  intake differs; if only one of the two is shown, show the reference difference, not the raw average.
- Trivsel is a 0–5 self-report from a survey with real non-response. `Antal Indikatorsvar` next to it.
- One school covers several buildings; the figure belongs to the school, not to each footprint.
- The 3-årig socioøkonomisk reference lags the 1-årig by design — do not put them on one time axis.

## 7. Usage

```bash
python3 scripts/fetch_uddstat.py --example                 # documented ELEV/ELEVEX call, København
python3 scripts/fetch_uddstat.py --skema                   # the 7 områder
python3 scripts/fetch_uddstat.py --skema GS                # the 17 GS emner
python3 scripts/fetch_uddstat.py --skema GS/KARA/KARAGNS   # dimensions + measures of one cube
python3 scripts/fetch_uddstat.py --skema GS/TRIV/TRIVIND --detalje "[Trivselsindikator].[Trivselsindikator]"
python3 scripts/fetch_uddstat.py --map                     # all six cubes above, in one go
python3 scripts/fetch_uddstat.py --query q.json            # run a saved body, cache the rows
```

`--query` takes the statistik body as JSON and caches to `data/raw/uddstat/<emne>_<underemne>.jsonl`
with a `.meta.json` recording the query, its hash, the row count, the retrieval date and the
attribution string. Changing the measures or the detaljering changes the hash and forces a refetch,
so a cached file can never hold rows from a different query than the one asked for.
