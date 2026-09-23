# Outlook layer — population projection 2026–2040

**Status:** v2.4 Phase A · 2026-09-23 · data pipeline only, nothing wired into the app yet
**Source research:** [`docs/FORECAST_SOURCES.md`](FORECAST_SOURCES.md)
**Build:** `scripts/build_forecast.py`, `scripts/build_housing_gap.py` · **Check:** `scripts/validate_forecast.py`
**Output:** `data/processed/forecast.json`, `data/processed/housing_gap.json`
**Registry:** `config/indicators.json` → top-level `forecast` key (see §5 for why not `indicators[]`)

The Outlook layer projects each Danish municipality forward from Statistics Denmark's official
municipal population projection. Phase A ends with a checked `forecast.json` and a registry entry;
Phase B renders it.

---

## 1. Sources

| what | where | licence | geography | horizon | vintage |
|---|---|---|---|---|---|
| Municipal projection | DST **`FRKM126`** via `api.statbank.dk/v1` | free reuse incl. commercial, attribution *Danmarks Statistik* | 98 kommuner (+ Christiansø, excluded) | 2050 | 2026, updated 2026-06-12 |
| National control total | DST **`FRDK126`** | same | Denmark | 2070 | 2026 |
| Base-year check | DST `FOLK1A` | same | 98 kommuner, quarterly | actual | 2026Q3 |

**The table id carries the vintage** — `FRKM1` + `26`, and DST replaces the table each spring rather
than keeping a history. `build_forecast.py` resolves it from the live catalogue on every run
(`resolve("FRKM1")`, highest vintage wins) and never hard-codes it. The same applies to `FRDK1xx`.
If DST renames the family the script exits with a message rather than silently building nothing.

**Window.** The vintage year through vintage + 14 — **2026–2040** today. Derived from the resolved
vintage, so it rolls forward on its own. `--years` widens it; the script refuses a window that would
exceed the API's cell cap.

**Why two pulls per table.** `FRKM126` has no both-sexes code (`KØN` is `M`/`K` only, with
elimination), so the sexes are pulled separately and summed in the build. One request naming both
sexes is 299 880 cells, but the API's pre-flight counter scores that selection at 1 499 400 and
rejects it against the 1 000 000-cell CSV cap; per sex it is 149 940 and passes. Keeping the pulls
separate also leaves the sex dimension in the raw files for later use.

Raw pulls land in `data/raw/forecast/dst/` (gitignored, re-downloadable); the `tableinfo` JSON beside
them is committed, because the build reads municipality labels from it. That directory holds two
naming conventions on purpose: `<TABLE>.meta.json` is what `build_forecast.py` writes and reads
(matching `fetch_statbank.py`), while `tableinfo_<TABLE>.json` are the frozen research snapshots
behind `docs/FORECAST_SOURCES.md`.

---

## 2. `data/processed/forecast.json`

```jsonc
{
  "meta": {
    "table": "FRKM126", "national_table": "FRDK126", "vintage": 2026,
    "updated": "2026-06-12",          // DST's own last-updated stamp
    "fetched": "2026-09-23", "built": "2026-09-23",
    "years": ["2026", …, "2040"], "first_year": "2026", "last_year": "2040",
    "groups": {"a0_5": "0–5", …, "a80p": "80+"},
    "kommuner": 98, "excluded": ["411"],
    "max_group_gap": 14, "group_gap_note": "…",
    "licence": "free reuse with attribution", "source": "…", "url": "…"
  },
  "kommuner": {
    "101": { "2026": { "total": 671714, "a0_5": 43517, "a6_16": 61399, "a17_19": 17614,
                       "a20_34": 234826, "a35_64": 240495, "a65_79": 56403, "a80p": 17460 }, … }
  },
  "national": { "2026": 6025603, … }      // FRDK126, for the reconciliation check
}
```

Municipality codes are the plain three-digit DST codes (`101`, `751`, …) — the same keys
`data/processed/makro.json` uses, so no crosswalk is needed.

**Age groups** are contiguous and exhaustive over 0…100+: `a0_5` 0–5, `a6_16` 6–16, `a17_19` 17–19,
`a20_34` 20–34, `a35_64` 35–64, `a65_79` 65–79, `a80p` 80 and over (including the `100-` code).

**Two caveats baked into the file.**

- **Christiansø (`411`) is excluded.** It appears in `KOMMUNEDK` but is not a municipality (~90
  people). The app's own municipality list has 99 entries, so `411` simply carries no Outlook value.
- **`total` is DST's published `ALDER=TOT` cell**, not the sum of the age groups. DST rounds every
  cell independently, so the groups re-sum to within **14 persons** of it (recorded as
  `max_group_gap`). Using `TOT` means `forecast.json` reproduces the StatBank figure exactly — which
  is what the smoke test in `validate_forecast.py` checks. A stacked age chart should therefore
  normalise to the group sum, not to `total`, or it will be off by a rounding crumb.

---

## 3. Indicator definitions

Seven indicators, all municipality-level, all derived by `indicators()` in `scripts/build_forecast.py`
(one definition, so Phase B imports it rather than reimplementing it). *P* is `total`; a group name
means that group's count. *y₀* = first year (2026), *y₁* = last year (2040), *y₅* = y₀ + 5 (2031).

| key | label | definition | unit | fmt |
|---|---|---|---|---|
| `fc_growth` | Projected population growth 2026→2040 | (P₂₀₄₀ − P₂₀₂₆) / P₂₀₂₆ × 100 | % | `signpct1` |
| `fc_growth_5y` | Projected population growth 2026→2031 | (P₂₀₃₁ − P₂₀₂₆) / P₂₀₂₆ × 100 | % | `signpct1` |
| `fc_abs` | Projected population change 2026→2040 | P₂₀₄₀ − P₂₀₂₆ | persons | `int` |
| `fc_0_5` | Projected change, children 0–5 | (a0_5₂₀₄₀ − a0_5₂₀₂₆) / a0_5₂₀₂₆ × 100 | % | `signpct1` |
| `fc_6_16` | Projected change, children 6–16 | as above on `a6_16` | % | `signpct1` |
| `fc_20_34` | Projected change, young adults 20–34 | as above on `a20_34` | % | `signpct1` |
| `fc_20_34_rel` | Young adults 20–34 vs Denmark 2026→2040 | `fc_20_34` − Denmark's own 20–34 change | pp | `signdec1` |
| `fc_20_34_abs` | Projected change, young adults 20–34 (persons) | a20_34₂₀₄₀ − a20_34₂₀₂₆ | persons | `int` |
| `fc_80p` | Projected change, 80 and over | as above on `a80p` | % | `signpct1` |
| `fc_hh_gap` | Housing gap next 5 yrs, dwellings per 1,000 inh. | see **§7** | dwellings / 1 000 inh. | `signdec1` |

`fc_growth` and `fc_20_34` carry `chip: true` — the growth headline and the demand signal.
`fc_hh_gap` comes from a second build and a second file; the other nine are `indicators()` in
`scripts/build_forecast.py`.

### The 20–34 pair — why an absolute map of `fc_20_34` is unreadable

**Denmark's own 20–34 population falls 7.11 % between 2026 and 2040**, so only 7 of 98
municipalities gain any at all and a map of `fc_20_34` is a wall of red with the story buried in
the last two shades. `fc_20_34_rel` re-centres it:

> `fc_20_34_rel` = `fc_20_34` − Denmark's 20–34 change 2026→2040, in percentage points.

**Denmark is the Σ of the 98 municipalities in `forecast.json`**, deliberately — the same cells the
per-municipality percentages come from, so the indicator is measured against its own aggregate
rather than against a separately rounded national table. Check 5 in `validate_forecast.py`
reconciles that sum with `FRDK126`'s published age detail: **−7.1092 % against −7.1096 %, 0.0004 pp
apart**, which is per-cell rounding. `national_pct()` in `build_forecast.py` is the one definition.

A positive `fc_20_34_rel` therefore usually still means a **shrinking** cohort, just one shrinking
more slowly than the country: **34 municipalities beat Denmark, and 27 of them still lose
20–34-year-olds.** Only Brøndby, Høje-Taastrup, Rødovre, Ballerup, Vallensbæk, Herlev and Tårnby
gain any outright. Phase B must not let the legend imply otherwise — the zero line is Denmark's
path, not stability.

`fc_20_34_abs` is the same change in persons. It exists for the same reason `fc_abs` does: the
percentage ranks Fanø (−54 people) above København (−15 978), and for anything volume-driven that is
backwards. The 98 values sum to Denmark's own −85 641, which check 5 also asserts. It is heavily
skewed — København alone is a fifth of the national loss — so its diverging ramp needs clamping.

### Colour and direction

Every Outlook indicator is **`direction: "neutral"`**. Neither end is "better": a shrinking
municipality is not failing and a growing one is not succeeding, so these must never be ranked
good-to-bad or coloured with the good/bad ramp the other groups use. The registry's existing
`direction` vocabulary is `higher_better` / `lower_better` only, so `neutral` is new — see §5.

Every Outlook indicator uses a **diverging scale centred on 0** (`scale: "diverging"`, `center: 0`),
from `hue_neg` through the paper tint to `hue_pos`. Zero is a real boundary here — growth and decline
are different phenomena, not two ends of one quantity — and the 2026 vintage puts municipalities on
both sides of it for five of the seven indicators.

**`fc_abs`: diverging centred on 0, not sequential by absolute size.** The prompt allowed either.
Diverging wins because **42 of 98 municipalities have a negative `fc_abs`** (range −4 617 to
+52 670): a sequential ramp on |value| would paint Lolland losing 4 600 people the same shade as a
town gaining 4 600, which is the one distinction the indicator exists to make.

**`fc_80p` never goes negative** in this vintage (+6.9 % to +63.4 %, all 98 positive), so its
diverging ramp renders one-sided. That is truthful rather than wrong — the spread between
municipalities is the story — but it is worth knowing before wondering why half the legend is unused.

**`fc_hh_gap` is one-sided too, and for a bigger reason** — all 98 municipalities are negative in
this vintage, Denmark included. §7 explains why; the ramp is left centred on 0 because zero is the
real boundary of the question ("is enough being built?"), not because the data straddles it.

Hues reuse the existing palette rather than inventing colours: rust `[166, 42, 22]` for the negative
end throughout; green `[10, 88, 70]` for total-population growth, blue `[40, 84, 128]` for the child
cohorts, purple `[90, 60, 150]` for 20–34 and 80+ (and for both new 20–34 indicators), teal
`[12, 94, 104]` for the undersupply end of `fc_hh_gap`.

---

## 4. 🚫 The splicing rule — DST and Københavns Kommune are never mixed

Copenhagen publishes its **own** population forecast (`s30/KKFR2026`, to 2060, down to kvarter level
— see `docs/FORECAST_SOURCES.md` §2). It is a different run with different assumptions, and it does
not agree with DST:

| year | DST `FRKM126` (kommune 101) | KK `KKFR2026` (distrikt 1000) | gap |
|---|---:|---:|---:|
| 2026 | 671 714 | 671 672 | +42 (+0.01 %) |
| 2031 | 689 101 | 693 344 | −4 243 (−0.61 %) |
| 2040 | **711 011** | **727 141** | **−16 130 (−2.22 %)** |

Same starting stock, **2.2 % apart by 2040**. So:

- **Never** splice them into one series, and never let a Copenhagen kvarter figure roll up into a
  DST municipal figure or vice versa.
- The municipal choropleth uses DST for all 98 municipalities, **including Copenhagen** — one source
  across the map, or the map is not comparable.
- A Copenhagen kvarter view, when it is built, uses KK throughout and says so on the panel.
- Wherever both could be read at once, state the gap rather than hiding it.

The reason they differ is structural, not a data error. DST projects all 98 municipalities on one
national frame from each municipality's own historical rates. Copenhagen projects its own city from
CPR microdata, anchored to DST/DREAM's national projection, and — critically — its **city total
excludes housing plans by design** while its **district split is driven by an unpublished housing
programme** (`docs/FORECAST_SOURCES.md` §2.6). Neither is more correct; they answer slightly
different questions.

---

## 5. Phase B notes — what has to change in files Phase A did not touch

Phase A added files only — `scripts/build_forecast.py`, `scripts/build_housing_gap.py`,
`scripts/validate_forecast.py` and this document. The one shared file it edited is
`config/indicators.json`, and it appended a **new top-level `forecast` key** rather than adding to
`indicators[]`. That was deliberate:

> `scripts/build_makro.py:400 compute()` dispatches on `calc`. An unknown `calc` falls through to the
> generic loop at the end, which calls `rows(db, table)` → `statbank_common.latest_raw()` → returns
> `None` → **`FileNotFoundError`**. Putting `calc: "forecast"` into `indicators[]` today would break
> `build_makro.py` for everyone, including the other worktree. Under its own key the block is inert:
> every existing consumer iterates `indicators`, `macro`, `macro_hero` or `cph.indicators`, and none
> reads `forecast`. Verified — `fetch_statbank.py` and `validate_config.py` also skip it, since both
> filter on `db in ("", "s20", "s30")` and require a `vars` block.

So Phase B's first job is to move the block and teach the pipeline about it:

1. **`config/indicators.json`** — move the ten entries from `forecast.indicators` into
   `indicators[]`, keeping `_doc`, `first_year`, `last_year` and `mid_year` wherever they are still
   useful. Extend the top-level `_doc` to document `calc: forecast`, `calc: housing_gap`,
   `db: forecast`, `db: housing_gap`, `field`, `scale`, `center`, `hue_pos`/`hue_neg` and
   `direction: neutral`. Consider moving `chip: true` from `fc_20_34` to `fc_20_34_rel` — the
   relative version is the one that reads as a map (§3).
2. **`scripts/build_makro.py`**
   - `compute()` (~line 400): add a `calc == "forecast"` branch, next to `infra_index` /
     `public_index` / `schools`. It should read `data/processed/forecast.json` and call
     `indicators()` from `scripts/build_forecast.py` — do not reimplement the arithmetic.
     The layer is snapshot-like (a single vintage, not a per-year history), so it should return `{}`
     when `year` is set, exactly as the `bbr` branch does. Entries are looked up by `key`:
     `indicators()` returns one dict per kommune keyed by exactly the registry keys, so the branch
     is a lookup, not a dispatch on `field`.
   - a second branch for `calc == "housing_gap"`, reading `data/processed/housing_gap.json` and
     returning `kommuner[code]["gap_per_1000"]`. Same snapshot rule: `{}` when `year` is set.
   - the indicator-output block (~line 594): add `"scale"`, `"center"`, `"hue_pos"`, `"hue_neg"` and
     `"field"` to the key list copied into `makro.json`, or the app never sees them.
   - the source-list loop (~line 622): add `"forecast"` **and `"housing_gap"`** to the `db` skip set
     (`"boligstat", "lbf", "bbr", "infra", "public", "schools"`), then append a source entry for each
     from the respective `meta` (label, `asof` = `meta.updated`, `fetched`, `url`, `licence`) the
     way `infra_index` and `public_index` already do. `housing_gap.json`'s `meta.tables` carries a
     per-table `updated` stamp, so its source entry should name FOLK1A, FAM55N and BYGV33 rather
     than one table.
3. **`src/app.js`**
   - `mkShade()` (~line 399) builds a **single-ended** ramp from the paper tint to `hue`. It needs a
     diverging variant: when `ind.scale === "diverging"`, ramp `hue_neg` → paper → `hue_pos` about
     `ind.center`. `hue` is deliberately set equal to `hue_pos` so that until this lands the map
     degrades to a plausible sequential ramp instead of throwing.
   - `scaleOf()` (~line 406) classes by **quintiles**, which ignore the centre and would put the zero
     crossing in the middle of a class. A diverging indicator needs breaks symmetric about `center`
     (e.g. quantiles of |v| mirrored, so the same shade means the same magnitude either side).
     `fc_abs` in particular is heavily skewed — København +52 670 against a median of +488 — so a
     linear symmetric scale must be clamped or the map goes flat.
   - `lowerBetter()` (~line 66) tests `direction === "lower_better"`; anything else, including
     `"neutral"`, is currently treated as higher-is-better for ranking and good/bad colouring. Add a
     `neutral` case that suppresses good/bad colouring and the "↓ lower is better" legend note, and
     leaves ranking unsigned.
   - `legendHtml()` (~line 420) should show the centre tick for a diverging scale.
4. **`Makefile`** — add `build_forecast` then `build_housing_gap` before `build_makro`, and
   `validate_forecast` alongside the other checks. Both builds need network unless run with
   `--no-fetch`, and `build_housing_gap.py` must run **after** `build_forecast.py` — it reads
   `forecast.json` for P₂₀₂₆ and P₂₀₃₁.
5. **`README.md` / `CHANGELOG.md`** — the Outlook layer, its sources, the §4 splicing rule and the
   §7 housing gap.
6. **Data-layer follow-ups** (not blocking Phase B):
   - Split the fetch out of `build_forecast.py` into `scripts/fetch_forecast.py` if the repo's
     `fetch_*` / `build_*` separation matters more than the script staying self-contained.
   - `FRKM226` (components of change per municipality: births, deaths, internal migration in/out)
     is already documented in `docs/FORECAST_SOURCES.md` §1.6 and would let the area panel say *why*
     a municipality grows. One extra pull, no new source.
   - The Copenhagen kvarter outlook (`s30/KKFR2026`) is a separate build with its own splicing rule;
     it keys straight onto the existing `OMRKK` kvarter geometry.
   - A **relative** housing gap — `fc_hh_gap` minus Denmark's −22.3 — would do for §7 what
     `fc_20_34_rel` does for §3, and for exactly the same reason: every municipality sits on one
     side of zero, so the sign carries no information and the spread carries all of it. Not added
     here because it was not asked for, but it is the variant worth mapping.
   - `fc_hh_gap` with **household** rather than population demand. DST publishes a household
     projection (`FRHUS1xx`); using it would drop the constant-household-size assumption, which §7
     shows is the single largest term the current formula omits.

---

## 6. Running it

```bash
python3 scripts/build_forecast.py                 # resolve vintage, pull, build forecast.json
python3 scripts/build_forecast.py --no-fetch      # rebuild from the newest cached CSV
python3 scripts/build_housing_gap.py              # needs forecast.json; writes housing_gap.json
python3 scripts/build_housing_gap.py --no-fetch   # rebuild from cached CSVs only
python3 scripts/validate_forecast.py              # seven checks; non-zero exit on failure
python3 scripts/build_forecast.py --indicators fc_20_34_rel --top 10
python3 scripts/build_forecast.py --indicators fc_20_34_abs --top 10
```

`validate_forecast.py` prints, in order:

1. **coverage** — 98 kommuner × 15 years, 0 missing, Christiansø excluded as intended.
2. **reconciliation** — Σ kommuner vs `FRDK126` per year. **Fails above ±0.1 %.** Current max
   deviation **−0.0021 %** (2027), which is per-cell rounding in the same projection run.
3. **base year** — 2026 projection vs the latest actual `FOLK1A` per municipality, five largest
   deviations, *information only*. Currently ±1.7 % at worst (Læsø, population 1 655); the projection
   is based on 1 January 2026 while the actual is 2026Q3, so part of each gap is real change since
   then, not projection error.
4. **smoke test** — København and Aarhus against `docs/FORECAST_SOURCES.md` §1.4
   (671 714 / 689 101 / 711 011 and 378 361 / 399 885 / 431 031). ✅ exact.
5. **20–34 baseline** — Denmark's 20–34 change as Σ of the 98 municipalities against `FRDK126`'s
   published age detail (**fails** if they disagree by more than 0.01 pp; currently 0.0004 pp), plus
   the two identities `fc_20_34_rel = fc_20_34 − Denmark` (98/98) and `Σ fc_20_34_abs = −85 641`.
   Then the rankings for both. The `FRDK126` age detail is read from the cached research snapshot
   when present and pulled from the API otherwise — 106 ages × 2 years.
6. **housing gap coverage** — 98 municipalities × 10 components, 0 null, none absent.
7. **housing gap by hand** — `gap_per_1000` recomputed for København, Aarhus, Brøndby, Lemvig and
   Frederiksberg straight from the raw `FOLK1A` / `FAM55N` / `BYGV33` cells and printed cell by
   cell, then compared with the stored value.

Checks 6 and 7 are **skipped, not failed**, when `housing_gap.json` has not been built, and check 7
reports politely if the raw pulls it names have been cleaned away (they are gitignored).

### Sanity check — `fc_20_34`, 2026→2040

| | top | | | bottom | |
|---|---|---:|---|---|---:|
| 1 | Brøndby | +8.5 % | 1 | Fanø | −23.0 % |
| 2 | Vallensbæk | +4.4 % | 2 | Lemvig | −18.6 % |
| 3 | Høje-Taastrup | +4.1 % | 3 | Læsø | −17.4 % |
| 4 | Rødovre | +3.9 % | 4 | Ærø | −17.3 % |
| 5 | Ballerup | +2.5 % | 5 | Morsø | −16.9 % |
| 6 | Herlev | +2.1 % | 6 | Odsherred | −16.8 % |
| 7 | Tårnby | +0.5 % | 7 | Struer | −16.6 % |
| 8 | Greve | −0.3 % | 8 | Langeland | −16.3 % |
| 9 | Ishøj | −0.5 % | 9 | Skive | −15.8 % |
| 10 | Aarhus | −1.7 % | 10 | Ringkøbing-Skjern | −14.6 % |

Reads correctly: the top is the western Copenhagen suburb ring, the bottom is small islands and rural
West Jutland. Note that **only 7 of 98 municipalities gain 20–34-year-olds at all** — the national
20–34 population is falling, so this indicator is mostly a map of where the decline is slowest.
København itself is **not** in the top ten: its total grows +5.9 % while its 20–34 cohort falls
6.8 %, as the large young cohorts of the 2010s age into their thirties. That is the single most
useful thing the Outlook layer says, and it is invisible in the headline growth number.

### Sanity check — `fc_20_34_rel` and `fc_20_34_abs`

Same ordering as `fc_20_34` (a constant is subtracted, so the rank cannot change) — but the numbers
now say how far from Denmark, and the absolute column says how many people.

| | `fc_20_34_rel` top | | | `fc_20_34_rel` bottom | |
|---|---|---:|---|---|---:|
| 1 | Brøndby | +15.6 pp | 1 | Fanø | −15.9 pp |
| 2 | Vallensbæk | +11.5 pp | 2 | Lemvig | −11.5 pp |
| 3 | Høje-Taastrup | +11.2 pp | 3 | Læsø | −10.3 pp |
| 4 | Rødovre | +11.0 pp | 4 | Ærø | −10.2 pp |
| 5 | Ballerup | +9.6 pp | 5 | Morsø | −9.7 pp |
| 6 | Herlev | +9.2 pp | 6 | Odsherred | −9.7 pp |
| 7 | Tårnby | +7.7 pp | 7 | Struer | −9.5 pp |
| 8 | Greve | +6.8 pp | 8 | Langeland | −9.2 pp |
| 9 | Ishøj | +6.6 pp | 9 | Skive | −8.7 pp |
| 10 | Aarhus | +5.4 pp | 10 | Ringkøbing-Skjern | −7.5 pp |

Aarhus is the reading that only the relative version gives: it **loses** 1.7 % of its 20–34 cohort,
which the absolute map paints as decline, and it is still 5.4 pp better than Denmark — tenth best in
the country. København is +0.3 pp, almost exactly the national path.

| | `fc_20_34_abs` largest gains | | | `fc_20_34_abs` largest losses | |
|---|---|---:|---|---|---:|
| 1 | Brøndby | +775 | 1 | København | −15 978 |
| 2 | Høje-Taastrup | +557 | 2 | Aalborg | −6 850 |
| 3 | Rødovre | +337 | 3 | Odense | −4 856 |
| 4 | Ballerup | +252 | 4 | Esbjerg | −2 508 |
| 5 | Vallensbæk | +161 | 5 | Aarhus | −2 230 |
| 6 | Herlev | +134 | 6 | Frederiksberg | −2 152 |
| 7 | Tårnby | +35 | 7 | Herning | −1 860 |
| 8 | Samsø | −15 | 8 | Viborg | −1 767 |
| 9 | Ishøj | −26 | 9 | Slagelse | −1 707 |
| 10 | Læsø | −27 | 10 | Vejle | −1 705 |

The gains column runs out after seven municipalities — everything below that is the least-bad loss,
which is the honest shape of a nationally shrinking cohort. The losses column is the student-city
list, in size order: the 2010s youth bulge ageing out of the age band it was counted in.

---

## 7. The housing gap — `fc_hh_gap`

**Build:** `scripts/build_housing_gap.py` · **Output:** `data/processed/housing_gap.json`
**Check:** `scripts/validate_forecast.py` checks 6 and 7

> *Are enough dwellings being built for the growth DST projects?*

### Formula

Per municipality, over the **first five years of the projection window, 2026 → 2031** — the near end,
where the projection is least uncertain:

```
persons_per_hh = FOLK1A population 2026K1  ÷  FAM55N households 2026
demand_5y      = (P₂₀₃₁ − P₂₀₂₆) / persons_per_hh
supply_5y      = mean yearly BYGV33 completions 2021–2025  ×  5
gap            = demand_5y − supply_5y                      ← positive = undersupply
gap_per_1000   = gap / P₂₀₂₆ × 1000                         ← the indicator
```

`persons_per_hh` is each municipality's **own** household size, not a national average — it ranges
from **1.71 (Læsø) to 2.55 (Vallensbæk)** against a national 2.09, and substituting the national
figure would cut Læsø's demand by 18 % and raise Vallensbæk's by 22 %. Population and households are read at the **same 1 January**, so the ratio is a real
snapshot rather than two dates divided.

`P₂₀₂₆` and `P₂₀₃₁` are DST's `ALDER=TOT` cells from `forecast.json`, so the demand side is exactly
the projection §2 describes. `supply_5y` is written as *mean × 5* rather than as a plain sum because
the mean is the thing being assumed to continue; the two are arithmetically identical for five full
years and differ the moment the window is not five years.

### Sources and periods

| what | table | selection | period used |
|---|---|---|---|
| population | `FOLK1A` | all areas, sex/age/marital status eliminated | **2026Q1** (1 January 2026) |
| households | `FAM55N` | all areas, household types summed, size/children eliminated | **2026** (1 January) |
| completions | `BYGV33` | `BYGFASE=3`, all uses, all builder types | **2021–2025**, five full calendar years |
| pipeline | `BYGV33` | `BYGFASE=1` and `2`, same selection | **2025Q3–2026Q2**, latest four quarters |
| projection | `FRKM126` | via `forecast.json` | **2026 and 2031** |

**Raw pulls are reused before they are fetched.** If `scripts/fetch_statbank.py` has already left a
`data/raw/dst_<TABLE>_<date>.csv` that covers the period, the build reads it and says `reused`;
otherwise it pulls its own copy into `data/raw/forecast/housing/` (gitignored, same rule as the
projection pulls). A cached pull is only accepted if every breakdown column it carries is the
variable's total code — `TOTALS` in the script — because rows are summed and a pull that broke
`ALDER` or `HUSSTØR` down would double-count. `BYGV33` never reuses: the repo's cached selection is
`BYGFASE=3` only, and the pipeline needs phases 1 and 2.

The tableinfo JSON is **not** duplicated. All three tables are already in the repo's own registry,
so `data/raw/dst_<TABLE>.meta.json` is committed; the build writes a copy under
`data/raw/forecast/housing/` only when the live tableinfo differs from it, i.e. exactly when DST has
revised the table since that copy was taken. `data/raw/forecast/housing/` therefore holds nothing
but gitignored CSVs on a clean run — unlike `data/raw/forecast/dst/`, whose projection tables have
no committed counterpart.

### Output

```jsonc
{
  "meta": {
    "built": "2026-09-23", "fetched": "2026-09-23", "kommuner": 98,
    "national": { "demand_5y": 33606.0, "supply_5y": 168072.0,
                  "gap": -134466.0, "gap_per_1000": -22.32, … },
    "projection": { "table": "FRKM126", "vintage": 2026,
                    "base_year": "2026", "mid_year": "2031", "horizon_years": 5 },
    "tables": { "FAM55N": {…}, "FOLK1A": {…}, "BYGV33": {…} },   // period, updated, pull, how
    "formula": "…", "sign": "…", "pipeline_note": "…", "caveats": "…",
    "licence": "free reuse with attribution", "source": "…", "url": "…"
  },
  "kommuner": {
    "101": { "pop": 671714, "households": 332181, "persons_per_hh": 2.0221,
             "p_base": 671714, "p_mid": 689101,
             "demand_5y": 8598.3, "supply_5y": 19012.0,
             "completions_by_year": {"2021": 5530, "2022": 3531, "2023": 3869,
                                     "2024": 3162, "2025": 2920},
             "gap": -10413.7, "gap_per_1000": -15.5,
             "permits_4q": 850, "starts_4q": 1409, "pipeline_permitted": -559 }
  }
}
```

Every component is stored, not just the answer, so the popup can show the working and check 7 can
recompute it. The stored numbers are rounded for display; the chain itself is computed unrounded, so
`demand_5y` is not `p_mid − p_base` divided by the *rounded* `persons_per_hh`.

**`pipeline_permitted` is context and enters no figure.** It is permits **minus** starts over the
latest four quarters — a four-quarter **flow difference**, not a stock of permitted-not-started
dwellings, which `BYGV33` does not publish. Positive means more was permitted than begun in the
year, so the not-yet-started backlog grew; negative means starts drew an earlier backlog down.
`BYGV33` is explicitly *not adjusted for reporting delays*, so the most recent quarters are revised
upward later and a slightly negative reading is not evidence of a stall. København's −559 over
2025Q3–2026Q2 is the largest drawdown in the country; Vejle's +452 the largest build-up.

### 🚩 Every municipality is negative — read the spread, not the sign

| | demand 5y | supply 5y | gap | per 1 000 |
|---|---:|---:|---:|---:|
| **Denmark** | 33 606 | 168 072 | **−134 466** | **−22.32** |

**0 of 98 municipalities have a positive gap.** Denmark's projected population growth 2026→2031 is
70 357 people, which at 2.09 persons per household is ~33 600 dwellings; completions averaged
**33 614 a year** over 2021–2025, so the country builds in one year what this arithmetic says it
needs in five. The indicator still separates municipalities cleanly — the range is **−7.6 (Gladsaxe)
to −42.2 (Fanø)**, a factor of five — but the *sign* carries no information in this vintage. A
diverging ramp centred on 0 will therefore render one-sided, exactly as `fc_80p` does (§3), and the
Phase B note proposes the relative variant that would fix the map.

| | highest — building least for the projected growth | | | lowest — building most relative to it | |
|---|---|---:|---|---|---:|
| 1 | Gladsaxe | −7.6 | 1 | Fanø | −42.2 |
| 2 | Hvidovre | −8.6 | 2 | Odsherred | −40.1 |
| 3 | Tårnby | −8.6 | 3 | Lolland | −39.6 |
| 4 | Ishøj | −10.9 | 4 | Læsø | −39.3 |
| 5 | Fredensborg | −12.1 | 5 | Høje-Taastrup | −38.7 |
| 6 | Rødovre | −12.9 | 6 | Gribskov | −38.1 |
| 7 | Køge | −13.2 | 7 | Morsø | −38.1 |
| 8 | Herlev | −13.5 | 8 | Struer | −36.3 |
| 9 | Svendborg | −14.3 | 9 | Samsø | −36.1 |
| 10 | Allerød | −14.6 | 10 | Hillerød | −35.5 |

The two ends mean different things, which is the trap this indicator sets:

- **Top**: dense, built-out Copenhagen suburbs with real projected growth and little room to build —
  Gladsaxe adds 345 dwellings' worth of people and completes 888. Genuinely the tightest market.
- **Bottom**: two different stories mixed together. Fanø, Odsherred, Lolland, Læsø, Morsø and Struer
  are **shrinking**, so `demand_5y` is *negative* and every completed dwelling counts as oversupply.
  Høje-Taastrup and Hillerød are the opposite — large projected growth (1 984 and 536 dwellings) with
  a building programme several times larger. The indicator cannot tell them apart on its own, which
  is why the popup must show `demand_5y` alongside the gap.

### Assumptions

1. **Household size is constant** at its 1 January 2026 value for the whole five years.
2. **The building pace is flat** at the 2021–2025 mean, with no trend, no cycle and no response to
   prices, rates or the projection itself.
3. **The projection is exogenous.** DST's municipal projection carries no housing programme (§1), so
   a municipality that builds 5 000 dwellings does not thereby gain the population to fill them in
   this arithmetic. Demand and supply are measured independently and then compared.
4. **Every dwelling completed is a net addition to the stock** available to the projected population.

### Caveats — what is deliberately not modelled

- **The constant-household-size assumption is the largest omitted term, and it understates demand.**
  Danish household size has fallen steadily — 2.150 persons per household in 2016, 2.118 in 2021,
  2.094 in 2026. Over 2021→2026 Denmark actually gained **120 983 households**; the same population
  growth at a *constant* 2021 household size implies only **87 604**. The formula would therefore
  have missed about **28 %** of the last five years' real household formation.
- **Demolitions and conversions.** `BYGV33` counts completions, not net stock change. Dwellings
  demolished, merged or converted to other uses are not subtracted, so `supply_5y` overstates the
  net addition.
- **Vacancy and second homes.** A completed dwelling in Odsherred or on Fanø may be a summer house
  and never house a projected resident. Neither vacancy nor holiday-home status is modelled, which
  biases exactly the municipalities at the bottom of the ranking.
- **Student housing and institutions.** `ANVEND` is summed over all uses, so halls of residence
  count as dwellings while their residents may not form FAM55N households.
- **Reporting delay.** `BYGV33` is the unadjusted table; recent quarters are revised upward, so the
  2025 completion figure — and hence `supply_5y` — is a slight undercount that will grow.
- **In shrinking municipalities `demand_5y` is negative**, so any positive supply reads as
  oversupply and the value is driven by the completion count alone. 45 of 98 municipalities are in
  this position.
- **The projection is not housing-driven**, so this compares two series that do not talk to each
  other. It is a consistency check on a municipality's building programme against its official
  demographic outlook, not a market forecast.

Even against *actual* household formation the picture holds: Denmark completed 168 072 dwellings
over 2021–2025 against 120 983 new households, ~39 % more. The negative national gap is not purely
an artefact of assumption 1.

### Validation

`scripts/validate_forecast.py` check 6 asserts 98 municipalities with all ten components present and
non-null. Check 7 recomputes `gap_per_1000` for **København, Aarhus, Brøndby, Lemvig and
Frederiksberg** from the raw CSV cells — a second implementation reading the pulls directly, not the
build's own numbers — and prints every step:

```
✓ 101 København     pop  671 714 ÷ hh  332 181 = 2.0221 p/hh
    demand (689 101 − 671 714) / 2.0221 =     8 598   supply 19 012 / 5 × 5 =    19 012
    gap    -10 414 / 671 714 × 1000 = -15.50   stored -15.50
✓ 665 Lemvig        pop   18 596 ÷ hh    9 151 = 2.0321 p/hh
    demand (17 688 − 18 596) / 2.0321 =      -447   supply 147 / 5 × 5 =       147
    gap       -594 / 18 596 × 1000 = -31.93   stored -31.93
```

Lemvig is the shrinking case: −908 people over five years is −447 dwellings of demand, and 147
completions push the gap further negative. Frederiksberg is the same shape at city scale. Brøndby is
the one municipality that gains 20–34-year-olds outright (§3) and still comes out at −23.5, because
3 818 more people at 2.29 per household is 1 669 dwellings against 2 633 completed.

### Popup text — Phase B

> *Forecast needs ~N dwellings, recent pace ~M → gap K*

with `N` = `demand_5y`, `M` = `supply_5y`, `K` = `gap`, and — because of everything above — the
sentence must survive **N being negative**. "Forecast needs ~−447 dwellings" is wrong; the shrinking
case wants its own wording ("projection implies 447 fewer households; 147 completed"). The popup
should also carry `persons_per_hh`, the completion years and `pipeline_permitted`, and `note_short`
should reach the map so the constant-household-size caveat travels with the number.
