# Population OUTLOOK 2026–2040 — source research

**Status:** research only · 2026-09-23 · branch `v2.4-forecast` · no app code touched
**Scope:** what exists openly for projecting population forward to 2040, at municipality level for all
of Denmark and at **kvarter** level for Copenhagen. Raw pulls land in `data/raw/forecast/`.
**Verdict up front:** both layers exist, are free, and are API-served. Copenhagen's own forecast is
published on the *same* `OMRKK` code list the dashboard's kvarter layer already uses, so it drops in
with no geography mapping. See §6.

---

## 0. TL;DR — the four tables that matter

| # | Source | Table | Geography | Age | Horizon | Vintage |
|---|---|---|---|---|---|---|
| 1 | Danmarks Statistik | `FRKM126` | 98 kommuner + Christiansø | single years 0–99, 100+ | **2050** | 2026 |
| 2 | Danmarks Statistik | `FRDK126` | Denmark (by ancestry) | single years 0–104, 105+ | 2070 | 2026 |
| 3 | Københavns Kommune | `s30/KKFR2026` | city + 11 bydele + 13 lokaludvalg + **68 kvarterer** | single years 0–98, 99+ | **2060** | 2026 |
| 4 | Københavns Kommune | `s30/KKFRBEDI` | same 92 districts | 5-year bands | 2059 | 2026 |

All four: `api.statbank.dk`, REST, no key, free reuse incl. commercial with attribution.

---

## 1. Statistics Denmark — municipal projection

### 1.1 Catalogue

`GET https://api.statbank.dk/v1/tables?lang=en&format=JSON` → 2 309 tables. Filtering on the `FRKM` /
`FRDK` / `FRLD` prefixes returns **nine** tables, and **only the 2026 vintage exists** — DST replaces
the projection tables each year rather than keeping a history, so the id itself carries the vintage
(`FRKM1` + `26`). A fetcher must resolve the latest id from the catalogue every spring, not hard-code it.

| id | text | period | vars |
|---|---|---|---|
| **`FRKM126`** | Population projections 2026 | 2026–2050 | municipality, age, sex, time |
| `FRKM226` | Key figures 2026: components of change | 2026–2050 | municipality, type of movement, time |
| `FRLD126` | Population projections 2026 | 2026–2050 | region/province, age, sex, time |
| `FRLD226` | Key figures 2026: components of change | 2026–2050 | province, type of movement, time |
| **`FRDK126`** | Population projections 2026 for the country | 2026–2070 | ancestry, sex, age, time |
| `FRDK226` | Key figures 2026: components of change | 2026–2070 | ancestry, type of movement, time |
| `FRDK326` | Assumptions of **fertility** | 1992–2069 | age, ancestry, time |
| `FRDK426` | Assumptions of **mortality** | 2026–2069 | sex, age, life table, time |
| `FRDK526` | Assumptions of **migration** | 2026–2069 | sex, age, ancestry, movement, time |

All nine were last updated **2026-06-12**. The national projection is the joint DST/DREAM product;
`FRDK3–526` publish its fertility, mortality and migration assumptions explicitly, which is enough to
document (and, if ever wanted, re-run) the outlook without guessing.

### 1.2 `FRKM126` — variables and codes

From `GET /v1/tableinfo/FRKM126?lang=en&format=JSON` (cached at `data/raw/forecast/dst/tableinfo_FRKM126.json`):

| var | text | n | elimination | codes |
|---|---|---|---|---|
| `KOMMUNEDK` | municipality | **99** | yes | `101` … `860`, three digits, no leading zeros |
| `ALDER` | age | 102 | yes | `TOT`, then `0`, `1`, … `99`, `100-` — **single years** |
| `KØN` | sex | 2 | yes | `M`, `K` — **split, and there is no total value** |
| `Tid` | time | 25 | — | `2026` … **`2050`** |

Answers to the four questions asked:

- **Area list:** 99 values = the 98 kommuner **plus Christiansø (`411`)**, which is not a municipality.
  There is **no "All Denmark" total value.** The Denmark figure comes from *omitting* `KOMMUNEDK`
  (elimination), or from `FRDK126`. A build that sums the 99 areas will silently include Christiansø
  (~90 people) — harmless, but say so.
- **Age detail:** single years of age, 0–99 plus `100-`, plus a `TOT`.
- **Horizon:** last year is **2050**, so 2040 sits comfortably inside it.
- **Sex:** split `M`/`K` with elimination, so both-sexes is available but only implicitly.

### 1.3 Query gotchas

- `format: "CSV"` honours elimination (omit a variable → it is summed away) but is capped at
  **1 000 000 cells**. The full `FRKM126` cube is 1 009 800 cells, i.e. just over — pull it in two
  halves by year, or use `format: "BULK"`.
- `format: "BULK"` streams without a cell cap but **requires every variable to be selected**, so it
  cannot sum sexes for you. `{"code":"KØN","values":["*"]}` returns both rows.
- `POST` body goes to `https://api.statbank.dk/v1/data`; the `s30` sub-database is
  `https://api.statbank.dk/v1/s30/data` (path form — the `?database=s30` query form returns
  `EXTRACT-NOTFOUND`).

### 1.4 Smoke test ✅

`POST /v1/data`, `FRKM126`, `ALDER=TOT`, sex eliminated:

| area | 2026 | 2031 | 2040 | 2026→2040 |
|---|---:|---:|---:|---:|
| København (`101`) | 671 714 | 689 101 | 711 011 | **+5.9 %** |
| Aarhus (`751`) | 378 361 | 399 885 | 431 031 | **+13.9 %** |
| Denmark (`KOMMUNEDK` eliminated) | 6 025 510 | 6 095 867 | 6 231 911 | **+3.4 %** |

Sex split checks out (København 2040: 347 548 M + 363 463 K = 711 011). Single-year ages work
(København 2040: age 0 = 10 099, age 30 = 16 681, `100-` = 82).

### 1.5 Reconciliation against the national table ✅

`FRDK126` with ancestry, sex and age all eliminated:

| year | `FRDK126` national | `FRKM126` summed | diff |
|---|---:|---:|---:|
| 2026 | 6 025 603 | 6 025 510 | −93 |
| 2031 | 6 095 842 | 6 095 867 | +25 |
| 2040 | 6 231 908 | 6 231 911 | +3 |

Agreement to within ±0.002 % — the residual is per-cell rounding, not a different projection. Use
`FRDK126` as the national control total and `FRKM126` for the map; they are the same run.

### 1.6 Components of change

`FRKM226` gives, per municipality per year, six `BEVÆGELSE` codes: `B01` population primo, `B02`
livebirths, `B03` deaths, `B05` internal migration in, `B06` internal migration out, `B11` population
increase. This is the cheap way to caption *why* a municipality grows (natural increase vs. net
internal migration) without re-deriving it from the age cube. Note it carries **no international
migration split** — that exists only nationally, in `FRDK226`.

---

## 2. Københavns Kommune — Befolkningsprognose 2026

### 2.1 Where it lives

The `s30` sub-database (`GET https://api.statbank.dk/v1/s30/tables?lang=da&format=JSON`, 51 tables —
this is the API behind `kk.statistikbank.dk`) carries **three** forecast tables, all updated
**2026-03-13**, all footnoted *"Kilde: Københavns Kommunes beregninger på baggrund af udtræk fra CPR"*
and contacted to *Københavns Kommunes Tværgående Analyseenhed*:

| table | text | vars | horizon |
|---|---|---|---|
| **`KKFR2026`** | Befolkningsfremskrivning 2026 | distrikt, køn, alder, tid | 2026–**2060** |
| `KKFRBEDI` | Fremskrivning af befolkningens bevægelser | distrikt, bevægelsesart, alder, tid | 2026–2059 |
| `KKFRBEV` | Fremskrivning af befolkningens bevægelser | bevægelsesart, køn, alder, tid | 2026–2059 |

**The table id carries the vintage** (`KKFR2026`; last year's `KKFR2025` is gone from the catalogue),
so like DST this must be resolved from the catalogue, not hard-coded. `KKFRBEDI`/`KKFRBEV` keep
stable names across vintages.

> **Correction (2026-09-23).** "Gone from the catalogue" is true of the *listing* only. The
> superseded ids are still served: `GET /v1/s30/tableinfo/KKFR2021` answers normally, as does a data
> request, and **eight vintages 2019–2026 are reachable today** with an identical schema and an
> identical 93-code `OMRKK` list. `scripts/build_cph_backtest.py` probes the ids directly for exactly
> this reason, and `docs/FORECAST.md` §9 backtests all of them. Resolution of the *current* vintage
> still goes through the catalogue, as above.

Nothing relevant is on **opendata.dk / admin.opendata.dk CKAN**: `package_search` for `prognose`
returns 4 datasets (a KK *air-quality* forecast, plus Vejle and Hedensted municipal population
forecasts); `fremskrivning` returns 0; `boligprogram` returns 1 (Hedensted). Copenhagen publishes its
forecast **only** through `s30` and through committee PDFs.

### 2.2 `KKFR2026` — variables and codes

| var | text | n | elimination | codes |
|---|---|---|---|---|
| `OMRKK` | distrikt | **93** | yes | see below |
| `KON` | køn | 3 | yes | `TOT`, `01` Mænd, `02` Kvinder — **note the explicit total**, unlike DST |
| `ALDER` | alder | 101 | yes | `TOT`, `00`, `01`, … `98`, `99` (= *99+*) — **zero-padded**, unlike DST |
| `Tid` | tid | 35 | — | `2026` … **`2060`** |

`OMRKK` breaks down as: `1000` city total · `1001–1010` **10 bydele** + `1099` unallocated ·
`2001–2012` **12 lokaludvalg** + `2099` unallocated · `20101–21211` **67 kvarterer** + `29999`
unallocated. Nothing finer than kvarter is published (no rode-level forecast).

**The code list is byte-identical to `KKBEF1`** — the observed-population table the dashboard's
existing kvarter layer is already built on (`scripts/build_cph.py`, `data/geo/cph_kvarterer.geojson`).
Verified: zero codes in one and not the other. Observed history and forecast therefore share one key.

### 2.3 Smoke test ✅ — and the levels are additive

| area | 2026 | 2031 | 2040 | 2026→2040 |
|---|---:|---:|---:|---:|
| `1000` København i alt | 671 672 | 693 344 | 727 141 | +8.3 % |
| `1001` Indre By | 57 366 | 56 393 | 58 683 | +2.3 % |
| `1004` Vesterbro/Kgs. Enghave | 84 925 | 91 134 | 103 569 | +22.0 % |
| `21210` Ørestad City | 11 599 | 16 462 | 17 251 | +48.7 % |
| `20101` Middelalderbyen | 8 842 | 8 556 | 8 293 | −6.2 % |

Sum of bydele = sum of lokaludvalg = sum of kvarterer = city total, to within ±1 per year (rounding).
**Caveat:** that only holds if the `…99` *"Uden for inddeling"* bucket is included — it is the same
3 713 people (2026) → 3 306 (2040) at all three levels, 0.55 % of the city, and dropping it leaves a
visible gap against the city total.

### 2.4 Reconciliation against DST — they disagree, and that matters

| year | DST `FRKM126` (101) | KK `KKFR2026` (1000) | diff |
|---|---:|---:|---:|
| 2026 | 671 714 | 671 672 | +42 (+0.01 %) |
| 2031 | 689 101 | 693 344 | −4 243 (−0.61 %) |
| 2040 | **711 011** | **727 141** | **−16 130 (−2.22 %)** |

Same starting stock, different runs: by 2040 Copenhagen's own forecast is **16 000 people higher**
than Statistics Denmark's. Do not mix the two in one series. The dashboard should show DST for the
national/municipal choropleth and KK for the Copenhagen drill-down, with the discrepancy stated.

### 2.5 Stated assumptions

Primary sources, both downloaded:

- *Orientering om befolkningsudviklingen i 2025 og befolkningsprognosen 2026*, ØKF Kontor for Analyse
  og Klima, dated **26-02-2026**, 7 pp. — the vintage note.
- *Beskrivelse af befolkningsprognosemodel*, ØKF Center for Økonomi, 27 May 2019, 4 pp. — the method.

**Headline.** 671 672 (primo 2026) → 677 721 (primo 2027) → **765 168 in 2060**, i.e. +93 000. The
2025 vintage had said 779 700, so 2060 is **revised down by ~14 000**, "dels en parallelforskydning
som følge af afvigelsen fra den forventede udvikling i 2025 (lavere vækst end forventet), dels den
langsigtede effekt af 2025-flytningerne på de fremtidige til- og fraflytningstilbøjeligheder"
— *"partly a parallel shift following the deviation from the expected 2025 development (lower growth
than expected), partly the long-run effect of the 2025 moves on future in- and out-migration
propensities."*

**Fertility.** 1.39 → 1.54 children per woman, anchored to DREAM's national trend: *"Fertiliteten
tager udgangspunkt i københavnernes fertilitet i 2025 kombineret med DREAM's forventninger til den
fremadrettede trend for landet som helhed"* — *"Fertility starts from Copenhageners' 2025 fertility
combined with DREAM's expectations for the forward trend for the country as a whole."*

**Mortality.** Average of 2024–2025, again on DREAM's national trend; life expectancy 83.2 → 87.6
(women) and 78.8 → 85.0 (men) by 2060.

**Migration — the base period.** *"Den mellemkommunale til- og fraflytning er på kort sigt baseret på
de seneste år … På lidt længere sigt baseres flytteadfærden på et gennemsnit af flytningerne i
perioden 2018-2019 samt 2023-2025. Dermed ses der, som hidtil, bort fra coronaårene og det
efterfølgende år."* — *"Inter-municipal in- and out-migration is based on the most recent years in the
short run … In the slightly longer run, moving behaviour is based on an average of the moves in
2018-2019 plus 2023-2025. As before, the corona years and the year after them are thus disregarded."*
International migration uses the same 2018-19 + 2023-25 window throughout, with net immigration
positive but declining.

**Ukrainians.** +1 050 during 2026; half assumed to leave in 2027 and half the remainder in 2028,
i.e. 25 % remain after 2028.

### 2.6 🔑 The housing-construction assumption — **the city total has none; the districts do**

This is the single most important finding for the kvarter model, and it is easy to get backwards.

*Orientering… 2026*, §"Kommuneplan og bolig- og distriktsprognosen":

> "Københavns Kommunes prognose for hele byen adskiller sig fra hovedparten af de øvrige danske
> kommuners prognoser ved, at **boligudbygningsplaner ikke indgår som en parameter** i beregningen af
> de fremtidige flyttebevægelser. Til- og fraflytninger, såvel mellemkommunale flytninger som
> vandringer til og fra udlandet, er udelukkende baseret på en fremskrivning af de historiske
> flyttemønstre."

> *"Copenhagen Municipality's forecast for the city as a whole differs from most other Danish
> municipalities' forecasts in that **housing development plans do not enter as a parameter** in the
> calculation of future migration flows. In- and out-moves, both inter-municipal moves and migration
> to and from abroad, are based exclusively on a projection of historical moving patterns."*

But *Beskrivelse af befolkningsprognosemodel*, §"Distriktsprognose":

> "Distriktsprognosen er dermed blot en fordeling af kommuneprognosens resultat på områder i byen.
> Fordelingen sker på baggrund af historiske flyttemønstre mellem distrikterne, distrikternes
> historiske fertilitet og dødelighed. **I distriktsprognosen inkluderes endvidere boligprognosen,
> dvs. forventningerne til den fremtidige boligudbygning og nedlagte boliger**, hvilket adskiller den
> fra kommuneprognosen."

> *"The district forecast is thus merely a distribution of the municipal forecast's result across
> areas of the city. The distribution is made on the basis of historical moving patterns between the
> districts and the districts' historical fertility and mortality. **The district forecast
> additionally includes the housing forecast, i.e. the expectations for future housing development
> and demolished dwellings**, which is what distinguishes it from the municipal forecast."*

So: **the city-wide total is pure demography; the split across kvarterer is driven by the housing
programme.** The model is explicitly top-down — *"der fremskrives først på det højeste geografiske
niveau, som derefter nedbrydes på mindre geografiske områder"* (*"the highest geographic level is
projected first, then broken down into smaller geographic areas"*) — with the national DST/DREAM
projection as the frame around the municipal forecast, and the municipal forecast as the frame around
the districts. That is exactly why §2.3 sums cleanly.

**Persons per new dwelling.** There is **no single such constant** in the model. Instead:

> "Indflytningen i nybyggeri er baseret på historiske erfaringer om, hvilke personer, opdelt på køn og
> et års aldre, der tilflytter nyopførte boliger af forskellige typer. For nedlagte boliger anvendes
> historiske erfaringer om fraflytterne."

> *"Move-in to new construction is based on historical experience about which persons, split by sex
> and single years of age, move into newly built dwellings of different types. For demolished
> dwellings, historical experience about the out-movers is used."*

New construction is split into four types — **Familieboliger, Ungdomsboliger, Specialboliger,
Sammenlagte boliger (tilgang)** — and demolitions into two (Sammenlagte boliger afgang, Nedrivninger),
with the note that *"Bolignedlæggelser er i dag meget sjældne"* (*"dwelling demolitions are very rare
today"*). Each type gets its own age×sex in-mover profile. A youth-housing block and a family-housing
block of the same dwelling count therefore produce very different population and age structures.

The model description is candid about the resulting uncertainty:

> "Ny prioritering af kommuneplanens rækkefølge for byudvikling, samt justeringer i forventningerne
> til det samlede årlige boligbyggeri, har stor betydning for fordelingen af befolkningen, da nye
> boliger trækker en stor del af et områdes udvikling. Og udbygningen er behæftet med relativ stor
> usikkerhed, både hvad angår udbygningstakt og boligtyper, da markedet i vid udstrækning er
> afgørende her for."

> *"A new prioritisation of the municipal plan's sequence for urban development, and adjustments to
> expectations for total annual housing construction, have great significance for the distribution of
> the population, since new dwellings drive a large part of an area's development. And the build-out
> is subject to relatively large uncertainty, both as regards build-out pace and dwelling types, since
> the market is to a large extent decisive here."*

**Read that as a warning label on the kvarter forecast.** A kvarter number is a *demographic total
allocated by a construction schedule*, and the schedule is the shaky part.

**Aggregate housing figures** from *Orientering… 2026* (2026 vintage): land is designated in
*Kommuneplan '24* for 40 000 dwellings to 2036, of which 5 500 are built and 34 500 remain (inclusive
of a 10 % "price-dampening" addition on top of demographic need); the 2026 vintage puts demographic
need to 2036 at **~27 000 dwellings** excluding that addition; remaining capacity across all
development and perspective areas is ~7 mio. m², against a demographic need to 2060 of ~5.5 mio. m²
= **64 000 dwellings**. Implied: **~1.45 persons and ~86 m² per new dwelling** — but that is a
*demographic-need* ratio (one dwelling per new family), not the model's in-mover assumption.

---

## 3. Does KK publish the housing programme behind the forecast? — **No**

Searched: `s30` catalogue (51 tables, no housing-programme table), opendata.dk / admin.opendata.dk
CKAN (`boligprogram`, `byggeri`, `boliger`, `fremskrivning` — nothing from KK), kk.dk's
Boligredegørelse series and the statistikbank documentation page.

The *Boligredegørelse 2025* (pp. 43–44) documents the model chain and confirms the boligprognose is a
distinct, named artefact:

> "**Boligprognose:** Boligprognosen er et scenarie for, hvordan det beregnede boligbehov kan dækkes.
> Den baseres på viden om byggeaktivitet og udlagte arealer til boligbyggeri."
> "**Distriktsprognose:** Befolkningsprognosen fordeles geografisk på byens distrikter. Beregningen
> tager højde for lokale flyttemønstre, fødsler og dødelighed samt **forventet boligbyggeri fra
> boligprognosen**. Dette gør det muligt at planlægge lokale servicebehov, f.eks. skoler og
> daginstitutioner."

> *"**Housing forecast:** The housing forecast is a scenario for how the calculated housing need can
> be covered. It is based on knowledge of building activity and land designated for housing
> construction."* · *"**District forecast:** The population forecast is distributed geographically
> across the city's districts. The calculation takes account of local moving patterns, births and
> mortality as well as **expected housing construction from the housing forecast**. This makes it
> possible to plan local service needs, e.g. schools and day-care institutions."*

And the model description says what feeds it: *"På kort sigt bygger boligprognosen på viden om tilladt
og påbegyndt byggeri samt dialog med ejendomsudviklere, mens det på længere sigt bygger på viden om
lokalplanlægning og kommuneplanens rækkefølge for byudvikling"* — *"In the short run the housing
forecast builds on knowledge of permitted and started construction plus dialogue with property
developers, while in the longer run it builds on knowledge of local planning and the municipal plan's
sequence for urban development."*

**But the boligprognose itself — planned dwellings by area and year — is not published anywhere I can
find.** Only its aggregate outputs appear, in prose, in the Boligredegørelse and the ØU orientering.
The statistikbank page directs documentation requests to `statistik@okf.kk.dk`; that is the route to
ask for it.

**Three usable substitutes, in order of preference:**

1. **Back out the implied construction** from `KKFR2026` itself. `KKFRBEDI` gives, per district per
   year, `01` livebirths, `02` deaths, `03` natural increase, `04` in-movers, `05` out-movers,
   `06` net in-migration, in 5-year age bands. Net in-migration per kvarter over and above the
   historical-pattern baseline *is* the housing programme's footprint — recoverable without the
   underlying schedule.
2. **Plandata.dk WFS** (already in the stack per `docs/DATA_MAP.md`): lokalplaner and
   kommuneplanrammer polygons carry designated residential capacity, which is the long-run input KK
   itself uses.
3. **BBR via Datafordeler** (already in the stack) for permitted/started/completed dwellings — the
   short-run input KK itself uses — plus DST `BYGV33` quarterly by municipality.

Aggregate demand figures for context, from *Boligredegørelse 2025* (built on the **2025** forecast
vintage, so one vintage behind §2.5): 113 000 more people to 2060 → **77 000 new dwellings**
(6.48 mio. m², a 23.5 % expansion of the stock), of which 37 500 by 2036 and 39 500 after. And a
spatial rule of thumb worth keeping: *"Baseret på historiske erfaringer forventes omkring 75 pct. af
de nye boliger at blive bygget i byudviklingsområderne, mens 25 pct. forventes at opstå i den
eksisterende by"* — *"Based on historical experience, around 75 % of the new dwellings are expected to
be built in the urban development areas, while 25 % are expected to arise in the existing city."*
Note this contradicts §2.5's 64 000/5.5 mio. m² only because of the vintage gap — Boligredegørelse
2025 (Dec 2025) predates the 2026 forecast (Feb 2026).

---

## 4. Skoleprognose — exists, not open (parked)

Copenhagen does forecast pupil numbers by **skoledistrikt** (57 districts), produced by
Økonomiforvaltningen as a cut of the same district forecast, and it drives the annual school-district
boundary changes decided by Børne- og Ungdomsudvalget. But:

- it is **not** in `s30` (no school-district geography in any of the 51 tables);
- it is **not** on opendata.dk;
- BUU agenda items cite it in prose and attach only *Forslag til distriktsændringer* and *Principper
  for skoledistriktsændringer* as PDFs — the forecast itself is not an annex.

For comparison, **Vejle Kommune** *does* publish `befolkningsprognose … fordelt på skoledistrikt` and
an `elevtalsprognose` as XLSX/CSV on opendata.dk — so the pattern exists in Denmark, just not in
Copenhagen. Parked; ask `statistik@okf.kk.dk` if it becomes worth pursuing.

---

## 5. Source table

| Source | URL | Licence | Format | Geography | Age detail | Horizon | Vintage | Refresh |
|---|---|---|---|---|---|---|---|---|
| DST `FRKM126` | `api.statbank.dk/v1/tableinfo/FRKM126` | free reuse incl. commercial, attribution "Danmarks Statistik" | REST → CSV / BULK / JSON-stat | 98 kommuner + Christiansø | single years 0–99, 100+; `TOT` | 2050 | 2026 (upd. 2026-06-12) | annual, May–June; **table id changes each vintage** |
| DST `FRDK126` | `api.statbank.dk/v1/tableinfo/FRDK126` | same | same | Denmark, by ancestry (5) | single years 0–104, 105+ | 2070 | 2026 | annual |
| DST `FRKM226` | `api.statbank.dk/v1/tableinfo/FRKM226` | same | same | 98 kommuner + Christiansø | — (6 movement types) | 2050 | 2026 | annual |
| DST `FRDK326/426/526` | `api.statbank.dk/v1/tableinfo/FRDK326` | same | same | Denmark | single years | 2069 | 2026 | annual — the published fertility / mortality / migration assumptions |
| KK `s30/KKFR2026` | `api.statbank.dk/v1/s30/tableinfo/KKFR2026` | free reuse with attribution "Københavns Kommune" | REST → CSV / BULK | city + 11 bydele + 13 lokaludvalg + 68 kvarterer | single years 0–98, 99+; `TOT` | 2060 | 2026 (upd. 2026-03-13) | annual, district cut mid-March; **table id changes each vintage** |
| KK `s30/KKFRBEDI` | `api.statbank.dk/v1/s30/tableinfo/KKFRBEDI` | same | same | same 92 districts | 5-year bands | 2059 | 2026 | annual |
| KK `s30/KKFRBEV` | `api.statbank.dk/v1/s30/tableinfo/KKFRBEV` | same | same | city only | 5-year bands | 2059 | 2026 | annual |
| KK *Orientering… prognosen 2026* | [kk.dk bilag-2 PDF](https://www.kk.dk/sites/default/files/agenda/aee3527d-5a1d-47ed-af09-f8228eab145e/9343d467-1f0d-41d4-ace3-640496ec3f9e-bilag-2.pdf) | public document | PDF, 7 pp. | city | age groups | 2060 | 26-02-2026 | annual, February |
| KK *Orientering… prognosen 2025* | [kk.dk bilag-8 PDF](https://www.kk.dk/sites/default/files/agenda/4d8b6d71-0e1f-408e-a574-9a1ef7daa1ea/8677cbfd-d3d9-4be3-83bd-04fc46c211f6-bilag-8.pdf) | public document | PDF, 4 pp. | city | age groups | 2060 | 21-02-2025 | superseded — kept for vintage-to-vintage comparison |
| KK *Beskrivelse af befolkningsprognosemodel* | [kk.dk PDF](https://www.kk.dk/sites/default/files/2021-11/Beskrivelse%20af%20befolkningsprognosemodel.pdf) | public document | PDF, 4 pp. | — | — | — | 27-05-2019 | static; the authoritative method description |
| KK *Boligredegørelse 2025* | [kk.dk PDF](https://www.kk.dk/sites/default/files/2025-12/Boligredeg%C3%B8relse%202025.pdf) | public document | PDF, ~120 pp., 11.7 MB | city + bydele | families | 2060 | Dec 2025 (on the **2025** forecast) | annual, December |
| KK statistikbank docs | [kk.dk statistikbanken](https://www.kk.dk/om-kommunen/fakta-og-statistik/statistikbanken) | — | HTML + PDF | — | — | — | — | contact `statistik@okf.kk.dk` for model docs |
| Boligprognose (dwellings by area × year) | — | **not published** | — | districts | — | — | — | request from `statistik@okf.kk.dk` |
| Skoleprognose (pupils by skoledistrikt) | — | **not published** | — | 57 skoledistrikter | — | — | — | internal; see §4 |

Earlier Boligredegørelser: [2024](https://www.kk.dk/sites/default/files/2025-12/Boligredeg%C3%B8relse%202024.pdf) ·
[2023](https://www.kk.dk/sites/default/files/2024-11/Boligredeg%C3%B8relse%202023.pdf) ·
[2022](https://www.kk.dk/sites/default/files/2022-08/Boligredeg%C3%B8relsen%202022.pdf).

### Downloaded to `data/raw/forecast/`

```
dst/  tableinfo_{FRKM126,FRKM226,FRLD126,FRDK126,FRDK226}.json
      FRKM126_muni_age_2026-2050.csv              252 450 rows, 4.1 MB
      FRDK126_national_ancestry_age_2026-2070.csv  23 850 rows
      FRKM226_components_2026-2050.csv             14 850 rows
cph/  tableinfo_{KKFR2026,KKFRBEDI,KKFRBEV}.json
      KKFR2026_distrikt_alder_2026-2060.csv       328 755 rows, 7.1 MB
      KKFRBEDI_distrikt_bevaegelse_2026-2059.csv  394 128 rows, 8.1 MB
      KKFRBEV_by_bevaegelse_2026-2059.csv          19 278 rows
      KK_OU_orientering_befolkningsprognose_2026.pdf
      KK_OU_orientering_befolkningsprognose_2025.pdf
      KK_befolkningsprognosemodel.pdf
      KK_statistikbank_dokumentation.pdf
      Boligredegoerelse_2025.pdf
```

The CSVs and PDFs are gitignored (same convention as `data/external/*.pdf`); the `tableinfo_*.json`
files are small and committed, since they are the schema the build would read labels from.

---

## 6. Conclusion — what is possible at kvarter level

**A 2026–2040 outlook is available at kvarter level today, for free, and it fits the existing map.**

1. **The geography is already built.** `KKFR2026`'s `OMRKK` code list is identical to `KKBEF1`'s,
   which `scripts/build_cph.py` and `data/geo/cph_kvarterer.geojson` already key on. The forecast
   attaches to the v1.2 kvarter layer with no crosswalk, no fuzzy matching, no new polygons — the
   observed 2016–2026 series and the 2026–2060 forecast are one continuous line per kvarter.
2. **The detail is generous.** 67 kvarterer × single years of age × sex × 35 years. Any age band the
   dashboard shows today (0–5 daycare, 6–15 school, 20–34 young adults, 65+, 80+) can be carried
   forward per kvarter, not just headline population.
3. **The signal is strong and it is a housing signal.** 2026→2040 by kvarter ranges from **+203 %
   (Vesterbro Syd)**, +176 % (Nordhavn), +107 % (Holmen og Refshaleøen), +101 % (Nordøstamager),
   +49 % (Ørestad City) down to **−15 % (Østerport)**, −12 % (Øster Farimagsgade, Rosenvænget) —
   against a city total of +8.3 %. That 218-point spread is the development pipeline made visible; it
   is precisely the thing a municipal-level forecast cannot show.
4. **It is internally consistent.** Kvarter, lokaludvalg and bydel sums all reproduce the city total
   to ±1, so the map can drill down without reconciliation logic — provided the `…99` unallocated
   bucket (~3 700 people) is carried.
5. **Two honest caveats to put in the UI.**
   - **KK ≠ DST.** Copenhagen's own 2040 figure is 727 141 against DST's 711 011, a 2.2 % gap. Pick
     one per view and label it; never splice them.
   - **A kvarter number is a construction schedule in disguise.** The city total is pure demography
     (housing plans explicitly excluded, §2.6); the *split* across kvarterer is driven by the
     unpublished boligprognose, which KK itself calls *"behæftet med relativ stor usikkerhed"*
     (*"subject to relatively large uncertainty"*) as to pace and dwelling type. Showing Nordhavn at
     +176 % without that caveat would overstate what the number is.
6. **What is still missing for a full kvarter model:** the boligprognose itself (planned dwellings by
   area and year). It is not published. Until it is, §3's three substitutes — implied net in-migration
   from `KKFRBEDI`, Plandata.dk designated capacity, and BBR/`BYGV33` permits and completions — cover
   the gap, and `KKFRBEDI` is the cheapest of the three because it is the same run as the forecast.
7. **Outside Copenhagen there is no kvarter equivalent.** `FRKM126` stops at the municipality; DST
   publishes no projection at postal-code, parish or urban-area level. Aarhus, Odense and Aalborg
   publish their own district forecasts, but not through `api.statbank.dk` — each would be a separate
   integration. For v2.4 the honest shape is: **DST municipal outlook for all 98, plus a Copenhagen
   kvarter outlook.**

**Operational note for whoever writes the fetcher:** both vintage table ids (`FRKM126`, `KKFR2026`)
change every year. Resolve them from `/v1/tables` and `/v1/s30/tables` by prefix and pick the highest
vintage, and record the resolved id plus `updated` in the `.meta.json` the way `scripts/fetch_statbank.py`
already does. DST refreshes in May–June, KK in mid-March, so the outlook is stale for about nine months
of the year unless both are re-pulled on their own cadence.
