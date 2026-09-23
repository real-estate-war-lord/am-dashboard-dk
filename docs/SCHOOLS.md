# Schools layer (STIL education statistics)

**Status:** v2.3 · live — grades, socioeconomic reference and well-being on the Education buildings
**Fetch:** `scripts/fetch_uddstat.py --schools` · **Build:** `scripts/build_schools.py`
**Cache:** `data/raw/uddstat/<emne>_<underemne>[_<tag>].jsonl` + `.meta.json`
**Outputs:** `data/processed/schools.json` · `school` refs in `data/processed/public/<kommune>.json` ·
school aggregates in `data/processed/public_index.json`
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
| **Socioøkonomisk reference** | ~~`SOCR` / `SOCREFEX`, `SOCR` / `SOCREF3ÅR`~~ → **`OVER` / `OVERSKO`** | `SocRef Karaktergennemsnit`, `SocRef Socioøkonomisk reference`, `SocRef Forskel`, `SocRef Signifikant forskel` |
| **Elevtrivsel** | `TRIV` / `TRIVIND` — *Trivselsindikatorer* | `Indikatorsvar` (the 0–5 score), `Andel Indikatorsvar`, `Antal Indikatorsvar`, plus the ` - Kommunetal` / ` - Landstal` variants for context |
| **Elevtal** | `ELEV` / `ELEVEX` — *Elevtal* | `Antal elever`, `Inklusionsgrad`, `Andel der modtager seg specialundervisning` |
| **Klassekvotient** | `OVER` / `OVERSKO` — *Skoleoverblik* | `Klassekvotient`, `Klassekvotient Kommune`, `Klassekvotient Land`, `Elevtal`, `Samlet elevfravær` |

### ⚠ The SOCR cubes are empty through the API

`GS/SOCR/SOCREFEX` and `GS/SOCR/SOCREF3ÅR` are listed by `/Api/v1/skema`, advertise their measures and
their dimension members, and **return 0 rows at every detaljering tried** — institution level, with and
without `[Fag]`, `[Prøveform]`, `[Skoleår]`, with and without a kommune filter, nationally, and with
`tomme_rækker` both ways. `GS/SOCR/KVALSOC` reports no dimensions and no measures at all. The `SOCREFSIKK`
emne is named *SocRef_Bag_Login*, so the socioøkonomisk reference looks to be gated behind a login.

**The layer takes the socioøkonomisk reference from `OVER/OVERSKO` instead**, which carries the same four
figures per afdeling and does return data. Consequences, both of which the UI has to respect:

* **The verdict vocabulary differs.** OVERSKO says **`Over niveau` / `Under niveau` / `På niveau`**, not
  the `Bedre end forventet` / `Dårligere end forventet` / `På Niveau` that the SOCREFEX *dimension*
  advertises. Only the first two are significant. Mapping the SOCREFEX words silently labels every one of
  the 38 schools with a significant difference as "as expected" — it did, until the browser check caught it.
* **No 3-year variant.** `soc_ref_diff_3yr` is not available; OVERSKO publishes the 1-year figure only.
  A 3-year mean of the 1-year differences is *not* the official 3-year reference (that re-runs the model
  over three pooled years), so the layer does not compute one.

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
  **no `[Institutionsnummer]`**. Everything it publishes — klassekvotient *and* the socioøkonomisk
  reference — is joined on afdelingsnummer, through the register's `Hovedinstitution` column. Where a
  school has several afdelinger the build takes the pupil-weighted mean (weight: that afdeling's own
  `Elevtal`), and keeps the significance verdict only when every afdeling agrees.
- **The socioøkonomisk reference lags the grades by a year.** 2025/2026 has grades, klassekvotient,
  elevtal and trivsel but no `SocRef *`. So `latest` is resolved **per measure**, each with its own
  `latest_year`; a single "latest year" for the whole record would blank the reference on every school.

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

> **Correction, and the bug to remember.** The register spells København's municipality
> **`"Københavns Kommune"`** — the genitive. Stripping `" Kommune"` yields `"Københavns"`, which matches
> neither `data/geo/kommuner.geojson` nor the cubes' `[Institution].[Beliggenhedskommune]`, both of which
> say `"København"`. The first pass of this document therefore reported **229 schools** for the metro set;
> the real figure is **364** — København, 135 of them, had been silently dropped. Stripping a trailing "s"
> is not a safe general fix: Assens, Horsens, Randers, Aarhus, Stevns, Halsnæs, Norddjurs, Nordfyns and
> Syddjurs all really end in one. `fetch_uddstat.KOMMUNE_ALIAS` spells out the single exception, and
> `register_kommune()` is the only place the register's kommune cell is read.

**Campus rule.** A school is one register point but usually several buildings. Attach the school to
**every** 421 building within 150 m of the register point, not just the nearest one. In the metro set
that is 1 236 school↔building links for 349 schools. Consequence: a school-level figure must not be
summed over its buildings — it is one value painted onto several footprints. Keep the school as the
record and the buildings as its geometry; the popup says "one of N buildings on this school's site".

**Reverse direction.** A 421 building with no school within 150 m is left unlabelled and stays a plain
public building — most are outbuildings, halls and annexes rather than unmatched schools.

### Measured, 23 September 2026 — the 19 metro kommuner

| what | result |
|---|---|
| register rows, all types, all of Denmark | 4 976 |
| grundskole-type rows in the 19 metro kommuner | **364** (folkeskoler · frie/private grundskoler · specialskoler for børn) |
| of those, with coordinates | **363 / 364** |
| matched to a BBR **421** building ≤ 150 m | **325 (89.3 %)** |
| matched on the **420/429 fallback** ≤ 150 m | **24 (6.6 %)** → **349 (95.9 %) with geometry** |
| no education building within 150 m | 15 (4.1 %), kept without a footprint |
| school→building links | **1 236** |

The fallback is the recommendation the intake pass measured, now implemented: 421 first, then 420/429
at the *same* 150 m radius, never a wider radius. `bbr_match` on each record records which rule fired
(`"421"` · `"fallback_42x"` · `"none"`) so the sheet can say so out loud.

### Measure coverage — how much of the layer is actually populated

| measure | schools with a value | of 364 |
|---|---|---|
| FP9 grade average | 271 | 74 % |
| socioøkonomisk reference | 254 | 70 % |
| klassekvotient | 280 | 77 % |
| elevtrivsel (generel) | 196 | 54 % |

The gaps are **not** join failures. A school with no 9th grade (0.–6. klasse) publishes no FP9 grade at
all; trivsel is the thinnest because the survey is not run everywhere every year and small schools fall
under the 5-pupil floor. This is the concrete reason the UI must never read a dash as a low grade — and
why 0.–6. klasse schools keep the base Education hue in grade-colour mode rather than the bottom bin.

## 4b. Area aggregates

Written by `build_schools.py` into `data/processed/public_index.json` under the same `areas` keys the
public-buildings layer uses (`kommune:101`, `postnr:2000`, `kvarter:20702`), so the existing
`calc_public_index` plumbing in `build_makro.py` picks them up with a sibling `calc_schools`.

| key | meaning |
|---|---|
| `school_grade_avg` | pupil-weighted FP9 grade average |
| `school_socref_diff` | pupil-weighted actual − expected |
| `school_trivsel` | pupil-weighted generel trivsel, 1–5 |
| `pupils_per_school`, `school_pupils`, `schools_n`, `school_grade_share` | size and how much of the area publishes |

**Population: folkeskoler + frie grundskoler that have a value. Specialskoler are excluded** — their
intake makes an average meaningless — but they are still *listed* in the school panel.

**Each measure is weighted by its own denominator**, not by the school's total roll: the grade average
and the reference difference by `grade_n` (the pupils who actually sat the exams), trivsel by
`trivsel_n` (the pupils who answered). This matters more than it sounds:

| weighting | municipalities within ±0.1 of STIL's own kommune figure | mean abs. difference |
|---|---|---|
| by `pupils_total` (whole roll) | 15 / 19 | 0.11 |
| **by each measure's own denominator** | **17 / 19** | **0.068** |

The two that still differ are **Herlev (+0.59)** and **Albertslund (+0.17)**, both small: Herlev has only
two schools that publish a grade, one of them a private school with 24 exam pupils and an average of 10.2.
STIL's kommune figure covers school types this layer excludes by design (ungdomsskoler, 10.-klasse centres
inside erhvervsskoler), so the two are close but not the same statistic. A folkeskole-only aggregate was
tested and is **worse** (5 / 19 within ±0.1), which rules out "STIL excludes private schools" as the
explanation. **The popup and the sheet therefore benchmark against STIL's own published kommune and
national figures, not against this layer's area aggregate** — the two answer different questions.

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

## 5b. What the dashboard shows

**Indicators** (group *Schools*, kommune + postnr level). None carries `chip: true`, so none appears in
the chip row — they are reachable from the indicator select, the table, the area page and the map.

| key | fmt | direction |
|---|---|---|
| `school_grade_avg` | `idx` (7,4) | higher_better |
| `school_socref_diff` | `signdec1` (+0,3) — **added for this layer**; the only signed formatter before it appended a % sign | higher_better |
| `school_trivsel` | `idx`, unit 1–5 | higher_better |
| `pupils_per_school` | `int` | higher_better |

**Popup.** An Education building whose BBR id is in a school's `bbr_ids` carries a school block: name,
type, FP9 grade with *kommune* and *DK* beside it, the reference difference (`+0,3 ✓ above expected` /
`≈ as expected` / `−0,4 ✓ below expected`), well-being out of 5, pupils, class size, school year, and
`Open school sheet ›`. Every building of a campus shows the same block and says so.

**School sheet** (`#school/<institutionsnummer>`): header, six key tiles, the three-year table, benchmarks
vs kommune and Denmark, the four trivsel sub-indicators, and the linked BBR buildings with m² and year.

**Grade colour mode.** When — and only when — the public filter is Education *and nothing else*
(`#…&public=1&pub=edu`), Education markers are coloured on the 5-step ramp of `school_grade_avg`,
classed by quintile over the schools of the **loaded** municipalities, and the legend switches to
*FP9 grade avg* with its bins. Any other filter combination returns to the category colours.

A school **with no grade keeps the base Education hue, drawn hollow with a thin outline** — never the
bottom bin. A 0.–6. klasse school, a specialskole and a suppressed school are not bad schools; painting
them the darkest-low colour would be the single most misleading thing this layer could do.

**Area card.** The PUBLIC line gains `schools 8,4 avg` when the area has a value; it opens a panel of the
area's schools sorted by grade, each linking to its sheet. **Charts** gains a *Schools* card for each
selected municipality: the three-year grade trend against Denmark.

## 6. Caveats to repeat wherever the numbers are shown

- **"Kilde: Uddannelsesstatistik.dk"** and the retrieval date. Required by the licence.
- A blank is "ikke offentliggjort" (under 3 obs, under 5 pupils for trivsel/socioøkonomisk reference),
  not a zero and not a bad school.
- A grade average is **not** a quality ranking. The socioøkonomisk reference exists precisely because
  intake differs; if only one of the two is shown, show the reference difference, not the raw average.
- Trivsel is a 0–5 self-report from a survey with real non-response. `Antal Indikatorsvar` next to it.
- One school covers several buildings; the figure belongs to the school, not to each footprint.
- The socioøkonomisk reference is published a year behind the grades: the newest school year normally
  shows a grade and a dash for the reference. That is a lag, not a suppression.
- The area aggregate (folkeskoler + frie grundskoler, this layer) and STIL's published kommune figure
  are **different statistics**. Benchmark a school against STIL's figure, which is what the sheet does.

## 7. Usage

```bash
# the layer, end to end (build_schools must run AFTER build_public — it rewrites the same files)
python3 scripts/fetch_uddstat.py --schools                 # all 8 pulls → data/raw/uddstat/
python3 scripts/build_schools.py                           # → schools.json + school refs + aggregates
make build                                                 # picks both up; make schools does the two above

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
