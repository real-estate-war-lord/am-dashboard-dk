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

1. **`config/indicators.json`** — move the eleven entries from `forecast.indicators` into
   `indicators[]`, keeping `_doc`, `first_year`, `last_year` and `mid_year` wherever they are still
   useful. Extend the top-level `_doc` to document `calc: forecast`, `calc: housing_gap`,
   `db: forecast`, `db: housing_gap`, `field`, `scale`, `center`, `hue_pos`/`hue_neg` and
   `direction: neutral`. Consider moving `chip: true` from `fc_20_34` to `fc_20_34_rel` — the
   relative version is the one that reads as a map (§3). **`fc_hh_gap_rel` is the default of the
   two housing-gap entries** and is listed before `fc_hh_gap` for that reason; whatever mechanism
   Phase B uses to pick a group's opening indicator must land on it, because `fc_hh_gap` renders
   one-sided on a diverging ramp (§7).
2. **`scripts/build_makro.py`**
   - `compute()` (~line 400): add a `calc == "forecast"` branch, next to `infra_index` /
     `public_index` / `schools`. It should read `data/processed/forecast.json` and call
     `indicators()` from `scripts/build_forecast.py` — do not reimplement the arithmetic.
     The layer is snapshot-like (a single vintage, not a per-year history), so it should return `{}`
     when `year` is set, exactly as the `bbr` branch does. Entries are looked up by `key`:
     `indicators()` returns one dict per kommune keyed by exactly the registry keys, so the branch
     is a lookup, not a dispatch on `field`.
   - a second branch for `calc == "housing_gap"`, reading `data/processed/housing_gap.json` and
     returning `kommuner[code][ind["field"]]` — `gap_per_1000_rel` for `fc_hh_gap_rel` and
     `gap_per_1000` for `fc_hh_gap`, so the branch is a `field` lookup rather than one hard-coded
     name. Same snapshot rule: `{}` when `year` is set.
   - the indicator-output block (~line 594): add `"scale"`, `"center"`, `"hue_pos"`, `"hue_neg"` and
     `"field"` to the key list copied into `makro.json`, or the app never sees them.
   - the source-list loop (~line 622): add `"forecast"` **and `"housing_gap"`** to the `db` skip set
     (`"boligstat", "lbf", "bbr", "infra", "public", "schools"`), then append a source entry for each
     from the respective `meta` (label, `asof` = `meta.updated`, `fetched`, `url`, `licence`) the
     way `infra_index` and `public_index` already do. `housing_gap.json`'s `meta.tables` carries a
     per-table `updated` stamp, so its source entry should name FOLK1A, FAM55N, BOL101 and BYGV33
     rather than one table.
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
   - `fc_hh_gap` with an **official household projection** rather than a fitted household-size
     trend. DST publishes one (`FRHUS1xx`); using it would replace the extrapolation and its ±5 %
     cap — the largest remaining modelling choice in §7 — with a published figure, and would make
     the demand side directly comparable with the projection's own assumptions.
   - **Rerun the §7 backtest on the next vintage.** It currently says the new formula ranks
     municipalities *worse* than the superseded one on the 2020→2025 window, while both of its
     components score better in isolation (§7). One window is not a verdict; the code is already
     written, so a second one costs a rerun.

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

## 7. The housing gap — `fc_hh_gap_rel` and `fc_hh_gap`

**Build:** `scripts/build_housing_gap.py` · **Output:** `data/processed/housing_gap.json`
**Check:** `scripts/validate_forecast.py` checks 6 and 7

> *Are enough dwellings being built for the growth DST projects?*

The first version of this indicator answered that with two shortcuts that both pushed the answer the
same way: household size was frozen, which **understates demand**, and supply was gross completions,
which **overstates net additions**. Every one of the 98 municipalities came out negative, so the sign
carried no information at all. Both shortcuts are now gone, and the map indicator is the **relative**
variant. The absolute one is kept as the second indicator, because the level is still worth reading —
it is simply not what a diverging ramp can show.

### Formula

Per municipality, over the **first five years of the projection window, 2026 → 2031** — the near end,
where the projection is least uncertain:

```
persons_per_hh(y) = FOLK1A population yK1  ÷  FAM55N households y        6 years, 2021…2026
step              = (persons_per_hh₂₀₂₆ − persons_per_hh₂₀₂₁) / 5        mean yearly change
pph₂₀₃₁           = persons_per_hh₂₀₂₆ + 5 × step                        capped, see below
demand_5y         = P₂₀₃₁ / pph₂₀₃₁  −  P₂₀₂₆ / persons_per_hh₂₀₂₆       households, not people
supply_5y         = (BOL101 stock₂₀₂₆ − stock₂₀₂₀) / 6 × 5               net additions
gap               = demand_5y − supply_5y                     ← positive = undersupply
gap_per_1000      = gap / P₂₀₂₆ × 1000                        ← `fc_hh_gap`
gap_per_1000_rel  = gap_per_1000 − Denmark's own              ← `fc_hh_gap_rel`, the map
```

**The household-size cap.** An extrapolated trend runs away if nothing stops it, and the six
observations behind `step` include the 2020–2022 pandemic years, when Danish household size fell
unusually fast. So the *total* five-year move is capped at **±5 %** of the base value and the result
is floored at **1.6** persons per household — below the smallest figure any Danish municipality has
ever recorded. In this vintage **neither bound binds for any of the 98 municipalities**: the widest
move is Gribskov's −0.0189 per year, which is −4.31 % over five years. The cap is insurance for a
future vintage, not a live term.

`persons_per_hh` is each municipality's **own** household size, not a national average — it ranges
from **1.71 (Læsø) to 2.55 (Vallensbæk)** against a national 2.09, and substituting the national
figure would cut Læsø's demand by 18 % and raise Vallensbæk's by 22 %. Population and households are
read at the **same 1 January**, so the ratio is a real snapshot rather than two dates divided. It is
falling in **85 of 98** municipalities and rising in 13, mostly the western Copenhagen suburbs
(Glostrup +0.0149 a year, Ishøj +0.0118, Vallensbæk +0.0110).

`P₂₀₂₆` and `P₂₀₃₁` are DST's `ALDER=TOT` cells from `forecast.json`, so the demand side is exactly
the projection §2 describes. Note that `demand_5y` is now a difference of **two household counts**,
not a population change divided by one household size — the second term is `P₂₀₂₆ / persons_per_hh₂₀₂₆`,
which is the municipality's actual household count, so the whole of the household-formation effect
lands in the first term.

**Why the supply window is six years, not five.** `BOL101` publishes no **2021** and no **2022** —
DST closed both years *"due to errors in data from the Building and Housing Register"* (a mandatory
footnote on the table). The natural 2021 → 2026 window therefore has no start, so the build takes the
newest published year at or before it (**2020**) and annualises over the span that actually separates
the two: `(stock₂₀₂₆ − stock₂₀₂₀) / 6 × 5`. `stock_window()` derives this from whatever the table
offers, so the window closes back to five years on its own if DST ever reopens the two years.

### Sources and periods

| what | table | selection | period used |
|---|---|---|---|
| population | `FOLK1A` | all areas, sex/age/marital status eliminated | **2021Q1–2026Q1**, 1 January each year |
| households | `FAM55N` | all areas, household types summed, size/children eliminated | **2021–2026**, 1 January |
| dwelling stock | `BOL101` | all areas, `BEBO` all three, `ANVENDELSE` all seven, tenure/ownership/construction year eliminated | **2020 and 2026**, 1 January |
| completions *(context)* | `BYGV33` | `BYGFASE=3`, all uses, all builder types | **2021–2025**, five full calendar years |
| pipeline *(context)* | `BYGV33` | `BYGFASE=1` and `2`, same selection | **2025Q3–2026Q2**, latest four quarters |
| projection | `FRKM126` | via `forecast.json` | **2026 and 2031** |
| backtest projection | `FRKM120` | all areas, `ALDER=TOT` | **2020 and 2025** |

`BOL101`'s `BEBO` (type of resident) **cannot be eliminated**, so "all dwellings" has to be named:
dwellings with registered population, dwellings without, and cottages without. `ANVENDELSE` is listed
rather than eliminated for one reason only — it makes `supply_5y_excl_cottages` available as a check
on how much of a municipality's net additions are summer houses. Nationally that is **4 590 of
152 985**, or 3 %; it is concentrated exactly where it would be (Odsherred, Ringkøbing-Skjern).

**Raw pulls are reused before they are fetched.** If `scripts/fetch_statbank.py` has already left a
`data/raw/dst_<TABLE>_<date>.csv` that covers the periods, the build reads it and says `reused`;
otherwise it pulls its own copy into `data/raw/forecast/housing/` (gitignored, same rule as the
projection pulls). A cached pull is only accepted if every breakdown column it carries is the
variable's total code — `TOTALS` in the script — because rows are summed and a pull that broke
`ALDER` or `HUSSTØR` down would double-count. `BYGV33` and `BOL101` never reuse: the repo's cached
`BYGV33` selection is `BYGFASE=3` only while the pipeline needs phases 1 and 2, and `BOL101`'s stock
depends on a `BEBO` selection a cached pull could silently have made differently.

The tableinfo JSON is **not** duplicated. FOLK1A, FAM55N, BOL101 and BYGV33 are already in the repo's
own registry, so `data/raw/dst_<TABLE>.meta.json` is committed and the build writes a copy under
`data/raw/forecast/housing/` only when the live tableinfo differs from it, i.e. exactly when DST has
revised the table since that copy was taken. The one file that *is* written there on every clean run
is **`FRKM120.meta.json`** — the backtest's projection vintage has no committed counterpart, the same
situation as the projection tables in `data/raw/forecast/dst/`, and it is what records that vintage's
`updated` stamp.

### Output

```jsonc
{
  "meta": {
    "built": "2026-09-23", "fetched": "2026-09-23", "kommuner": 98,
    "national": { "demand_5y": 69382.8, "demand_5y_const": 32535.7,
                  "supply_5y": 152985.0, "supply_5y_gross": 168072.0,
                  "gap": -83602.2, "gap_per_1000": -13.87,
                  "gap_const_gross": -135536.3, "gap_per_1000_const_gross": -22.49, … },
    "projection": { "table": "FRKM126", "vintage": 2026,
                    "base_year": "2026", "mid_year": "2031", "horizon_years": 5 },
    "tables": { "FAM55N": {…}, "FOLK1A": {…}, "BOL101": {…}, "BYGV33": {…} },
    "backtest": { "window": "2020→2025", "spearman": {…}, "components": {…}, … },
    "formula": "…", "variants": "…", "sign": "…", "pipeline_note": "…", "caveats": "…",
    "licence": "free reuse with attribution", "source": "…", "url": "…"
  },
  "kommuner": {
    "665": { "pop": 18596, "households": 9151, "persons_per_hh": 2.0321,
             "persons_per_hh_by_year": {"2021": 2.0788, "2022": 2.0643, "2023": 2.0724,
                                        "2024": 2.0546, "2025": 2.0457, "2026": 2.0321},
             "pph_change_per_year": -0.00933,
             "persons_per_hh_mid": 1.9855, "pph_capped": false,
             "p_base": 18596, "p_mid": 17688,
             "households_base": 9151.0, "households_mid": 8908.7,
             "demand_5y": -242.3, "demand_5y_const": -446.8,
             "stock_prev": 13259, "stock_base": 13312,
             "supply_5y": 44.2, "supply_5y_excl_cottages": -31.7, "supply_5y_gross": 147.0,
             "completions_by_year": {"2021": 17, …, "2025": 29},
             "gap": -286.5, "gap_per_1000": -15.41, "gap_per_1000_rel": -1.54,
             "gap_const_gross": -593.8, "gap_per_1000_const_gross": -31.93,
             "permits_4q": 7, "starts_4q": 6, "pipeline_permitted": 1 }
  }
}
```

Every component is stored, not just the answer, so the popup can show the working and check 7 can
recompute it. **Both superseded variants are stored too** — `demand_5y_const` (household size frozen)
and `supply_5y_gross` (gross completions), combined in `gap_const_gross` — so the effect of each fix
stays visible in the data rather than only in this document. The stored numbers are rounded for
display; the chain itself is computed unrounded.

**`pipeline_permitted` is context and enters no figure.** It is permits **minus** starts over the
latest four quarters — a four-quarter **flow difference**, not a stock of permitted-not-started
dwellings, which `BYGV33` does not publish. Positive means more was permitted than begun in the year,
so the not-yet-started backlog grew; negative means starts drew an earlier backlog down. `BYGV33` is
explicitly *not adjusted for reporting delays*, so the most recent quarters are revised upward later
and a slightly negative reading is not evidence of a stall. Vejle's +452 over 2025Q3–2026Q2 is the
largest build-up in the country; København's −559 the largest drawdown.

### What the two fixes did

| Denmark 2026→2031 | demand | supply | gap | per 1 000 |
|---|---:|---:|---:|---:|
| old — constant household size, gross completions | 32 536 | 168 072 | −135 536 | **−22.49** |
| **new — household-size trend, net stock change** | **69 383** | **152 985** | **−83 602** | **−13.87** |
| effect of the fix | **+36 847** | **−15 087** | +51 934 | +8.62 |

Projecting household size **more than doubles** national demand, because Denmark's persons per
household fell from 2.147 in 2015 to 2.094 in 2026 and the projection carries that on. Netting
demolitions, mergers and conversions off the supply side removes 15 087 dwellings, 9 % of gross
completions; net additions come in below gross completions in **77 of 98** municipalities (København
−915, Herning −668, Odense −665) and above them in 21, led by Aalborg at +840, where conversions into
housing and BYGV33's reporting delay both push the same way.

It is not enough to flip the sign. **0 of 98 municipalities still have a positive gap**, and the
absolute range is **−1.1 (Tårnby) to −47.0 (Læsø)**. But the gap that remains is much closer to what
actually happened last time: over 2020→2025 Denmark really did form 129 169 households while adding
164 763 dwellings, an actual gap of **−6.12 per 1 000**. The new formula's −13.87 for the next five
years sits far nearer that than the old −22.49 did.

The ranking moves too, and not by a little. Aarhus goes from −18.0 to −4.9 per 1 000 and from
mid-table to third tightest, because its household size is falling fast (2.07 → 2.03 over five years,
projected to 1.98) while its net additions are below its completions. Lemvig goes from −31.9 to
−15.4: netting the stock leaves it +44 dwellings over five years against 147 completed, and its
demand is −242 rather than −447. Gladsaxe, top of the old ranking, falls to 31st.

### 🚩 `fc_hh_gap_rel` is the map; `fc_hh_gap` is the number

Because every municipality is still negative, a diverging ramp centred on 0 renders one-sided —
exactly the problem `fc_20_34_rel` solves for §3, and solved the same way. `fc_hh_gap_rel` subtracts
**Denmark's own −13.87**, where Denmark is the Σ of the same 98 municipalities computed the same way
(check 6 asserts both the identity and the sum). That puts **41 of 98 above the line and 57 below**,
and the reading is *tighter or looser than the country*, not *undersupplied or oversupplied*.

| | tightest against the country | vs DK | per 1 000 | | loosest against the country | vs DK | per 1 000 |
|---|---|---:|---:|---|---|---:|---:|
| 1 | Tårnby | +12.8 | −1.1 | 1 | Læsø | −33.1 | −47.0 |
| 2 | Hvidovre | +10.5 | −3.4 | 2 | Samsø | −24.9 | −38.8 |
| 3 | Aarhus | +9.0 | −4.9 | 3 | Odsherred | −21.5 | −35.3 |
| 4 | Hedensted | +7.8 | −6.0 | 4 | Fanø | −21.0 | −34.9 |
| 5 | Halsnæs | +7.5 | −6.4 | 5 | Høje-Taastrup | −19.0 | −32.8 |
| 6 | Odense | +6.7 | −7.2 | 6 | Glostrup | −18.9 | −32.7 |
| 7 | Helsingør | +6.0 | −7.9 | 7 | Ringkøbing-Skjern | −15.3 | −29.1 |
| 8 | Vejen | +5.6 | −8.3 | 8 | Bornholm | −12.1 | −26.0 |
| 9 | Skanderborg | +5.4 | −8.4 | 9 | Lyngby-Taarbæk | −11.5 | −25.4 |
| 10 | Thisted | +5.4 | −8.4 | 10 | Brøndby | −10.0 | −23.9 |

The two ends still mean different things, which is the trap this indicator sets and which no
re-centring removes:

- **Top**: built-out municipalities whose projected household growth is nearly matched by their net
  additions — Tårnby needs 314 dwellings and adds 362. Genuinely the tightest markets.
- **Bottom**: two different stories mixed together. Læsø, Samsø, Odsherred, Fanø and Ringkøbing-Skjern
  are **shrinking**, so `demand_5y` is *negative* and every net addition counts as oversupply;
  several are also summer-house municipalities, which is what `supply_5y_excl_cottages` is for.
  Høje-Taastrup and Brøndby are the opposite — real projected household growth (1 812 and 1 381) with
  a building programme twice the size. The indicator cannot tell them apart on its own, which is why
  the popup must show `demand_5y` alongside the gap.

### Backtest — and it does not say what the fix hoped

`build_housing_gap.py` replays the whole formula on the last window that has fully played out. It
stands at 1 January **2020**, uses only 2015–2020 inputs, predicts 2020→2025, and scores the result
against what happened: **actual household growth (FAM55N 2020→2025) minus actual net dwelling-stock
change (BOL101 2020→2025)**, per 1 000 inhabitants. The population input is `FRKM120`, the projection
vintage actually published in 2020, so this is the indicator out of sample and not just its
arithmetic; a second scoring substitutes the realised population, which separates the formula's error
from the projection's.

Spearman rank correlation across the 98 municipalities, predicted `gap_per_1000` against actual:

| population input | old (constant size, gross completions) | **new (trend, net stock)** | trend demand only | net stock only |
|---|---:|---:|---:|---:|
| `FRKM120` projection | **+0.199** | −0.171 | −0.082 | +0.178 |
| realised population | **+0.389** | +0.215 | +0.229 | +0.373 |

**Stated plainly: on this backtest the new method ranks municipalities worse than the old one, by
−0.37 with the 2020 projection and −0.17 with the realised population. The fix does not pay off on
the measure it was tested against.** Each fix scored on its own side does better, which is what makes
the combined result worth spelling out:

| side, 2020→2025 | ρ old → new | median miss per 1 000 | Denmark old / new vs actual |
|---|---:|---:|---:|
| households formed | +0.919 → **+0.960** | 8.46 → **4.57** | +78 154 / **+93 793** vs +129 169 |
| net dwellings added | +0.780 → **+0.799** | 8.73 → 10.75 | +125 708 / +111 871 vs **+164 763** |

Both sides rank better under the new formula and the demand side's typical miss is roughly halved.
The combined gap nevertheless ranks worse because **it is a small residual between two large, nearly
equal flows**: Denmark's actual 2020→2025 gap was −6.12 per 1 000 out of a demand of +22.2 and a
supply of +28.3, and across municipalities the actual gap spans only −42.5 to +4.1 with a median of
−5.8. Both formulas under-predict both sides — 2020–2025 was an acceleration in household formation
*and* in building that neither could see from 2015–2020 data — and the old formula's two errors
happened to **cancel**: −51 015 on demand against −39 055 on supply leaves a gap error of −11 960,
while the new formula's smaller demand error (−35 376) sits against a larger supply error (−52 892)
and leaves +17 516. Better components, worse cancellation.

What that justifies and what it does not:

- It does **not** justify calling the new method more accurate. One window, one country, 98 points,
  and the headline test says the opposite.
- It does justify keeping it. The quantity the map is asked to show is *the balance between household
  formation and net additions*, and the new formula estimates both of those quantities better and
  measures the second one as the thing it claims to be. The old formula got the residual's ranking
  slightly less wrong through an error cancellation that has no reason to repeat.
- It does mean the **absolute** gap should not be read as a forecast of anything. That was already
  true and the backtest quantifies it: neither method explains much of the between-municipality
  variation in the realised gap.

The ten municipalities that actually tightened most over 2020→2025 are worth keeping next to the
ranking above, because only two of them are anywhere near the top of it:

| | | actual per 1 000 | households formed | net dwellings | old predicted | new predicted |
|---|---|---:|---:|---:|---:|---:|
| 1 | Tårnby | +4.12 | +585 | +408 | −5.0 | −16.5 |
| 2 | Frederiksberg | +2.94 | +1 635 | +1 328 | −14.4 | −11.7 |
| 3 | Næstved | +1.37 | +1 479 | +1 365 | −13.1 | −5.4 |
| 4 | København | +1.15 | +20 263 | +19 535 | −10.3 | −20.7 |
| 5 | Dragør | +0.28 | +48 | +44 | −10.3 | −12.3 |
| 6 | Frederikssund | +0.07 | +1 525 | +1 522 | −7.2 | −3.3 |
| 7 | Gentofte | +0.01 | +703 | +702 | −11.4 | −5.7 |
| 8 | Stevns | 0.00 | +504 | +504 | −8.7 | −7.2 |
| 9 | Favrskov | −0.62 | +606 | +636 | −11.7 | −4.9 |
| 10 | Tønder | −1.50 | −92 | −36 | −10.6 | +9.3 |

Only **seven municipalities in the whole country** actually formed more households than they added
dwellings over 2020→2025, and the largest margin was 4.12 per 1 000 — Tårnby, Frederiksberg, Næstved,
København, Dragør, Frederikssund and Gentofte, in that order. Both formulas predicted large negative
gaps for every one of them. Of the ten above, **only Tårnby is also in the current relative top ten**;
Næstved is 13th, Frederikssund 12th, Favrskov 14th and Tønder 16th, while Stevns is 72nd and Dragør
64th. That overlap is the visible form of the ρ ≈ +0.2 to +0.4 in the table: a weak signal, not none.

`--no-backtest` skips the whole block; the results are stored in `meta.backtest` either way, so
`validate_forecast.py` can print them without rerunning anything.

### Assumptions

1. **Household size follows its own recent linear trend**, capped at ±5 % over five years and floored
   at 1.6 persons. No cohort structure, no ageing effect, no price or tenure response.
2. **The building pace is the flat net-additions pace** of the 2020–2026 stock change, with no trend,
   no cycle and no response to prices, rates or the projection itself.
3. **The projection is exogenous.** DST's municipal projection carries no housing programme (§1), so
   a municipality that builds 5 000 dwellings does not thereby gain the population to fill them in
   this arithmetic. Demand and supply are measured independently and then compared.
4. **A dwelling in the BOL101 stock is available to the projected population** — it is not vacant,
   not a second home, not a student hall counted against households that do not exist.

### Caveats — what is deliberately not modelled

- **The household-size trend is a straight line through six years, two of which are pandemic years.**
  It is the largest remaining modelling choice and the cap exists to bound it. The backtest shows the
  trend under-predicted the actual 2020–2025 fall nationally (Denmark's persons per household went
  2.134 → 2.097, against a trend extrapolation of 2.122), so if anything this still understates
  household formation.
- **DST publishes a household projection** (`FRHUS1xx`) which would replace the whole demand side
  with an official figure. Using it is the obvious next step and is listed in §5.
- **`BOL101` has no 2021 or 2022.** The supply window spans six years and is annualised; if the true
  pace within the closed years differed sharply from the rest of the window, that is invisible here.
- **Vacancy and second homes.** A dwelling in the stock may be empty or a summer house.
  `supply_5y_excl_cottages` is carried for the cottage part of this — 3 % nationally — but vacancy is
  not modelled at all, and `BOL101`'s `UDLFORH=IB` (unoccupied) is summed into the total rather than
  removed.
- **Student housing and institutions.** All `ANVENDELSE` codes are summed, so halls of residence
  count as dwellings while their residents may not form FAM55N households.
- **In shrinking municipalities `demand_5y` is negative**, so any positive supply reads as oversupply
  and the value is driven by the stock change alone. 31 of 98 municipalities are in this position —
  down from 45 under the constant-household-size formula, because falling household size keeps demand
  positive in 14 municipalities whose population shrinks.
- **The projection is not housing-driven**, so this compares two series that do not talk to each
  other. It is a consistency check on a municipality's building programme against its official
  demographic outlook, not a market forecast — and the backtest above is the evidence for how weak a
  forecast it would be.

### Validation

`scripts/validate_forecast.py` check 6 asserts 98 municipalities with all twenty components present
and non-null, plus the two identities `fc_hh_gap_rel` depends on: `gap_per_1000_rel = gap_per_1000 −
Denmark's`, for all 98, and `Σ kommuner = Denmark` for `demand_5y`, `supply_5y` and `p_base`. Check 7
recomputes `gap_per_1000` for **København, Aarhus, Brøndby, Lemvig and Frederiksberg** from the raw
CSV cells — a second implementation reading the pulls directly, with its own copy of the trend, the
cap and the annualised stock window, not the build's numbers — and prints every step:

```
✓ 751 Aarhus        p/hh 2021 2.0723 → 2026 2.0256 (-0.00934/yr) → 2031 1.9789
    demand 399 885 / 1.9789 − 378 361 / 2.0256 =    15 283   supply (197 117 − 176 562) / 6 × 5 =    17 129
    gap     -1 846 / 378 361 × 1000 = -4.88   stored -4.88   vs Denmark +8.99
✓ 665 Lemvig        p/hh 2021 2.0788 → 2026 2.0321 (-0.00933/yr) → 2031 1.9855
    demand 17 688 / 1.9855 − 18 596 / 2.0321 =      -242   supply (13 312 − 13 259) / 6 × 5 =        44
    gap       -286 / 18 596 × 1000 = -15.41   stored -15.41   vs Denmark -1.54
```

Lemvig is the shrinking case: 908 fewer people over five years is 242 fewer households once falling
household size is allowed for — not the 447 the constant-size formula gave — and 44 net dwellings
push the gap negative. Frederiksberg is the same shape at city scale: −82 households of demand
against 1 178 net additions. Brøndby is the one municipality that gains 20–34-year-olds outright
(§3), and it is the one case here where household size **rises** (2.29 → 2.32), so its demand falls
from 1 669 to 1 381 while its net additions, 2 359, are 274 below its completions.

### Popup text — Phase B

> *Projection implies ~N more households, recent pace adds ~M dwellings → gap K*

with `N` = `demand_5y`, `M` = `supply_5y`, `K` = `gap`, and — because of everything above — the
sentence must survive **N being negative**. "Implies ~−242 more households" is wrong; the shrinking
case wants its own wording ("projection implies 242 fewer households; 44 dwellings added"). The popup
should also carry `persons_per_hh` → `persons_per_hh_mid` (the working behind the demand side),
`stock_prev` → `stock_base`, and `pipeline_permitted`; `note_short` should reach the map so the
"measured against Denmark, not against zero" caveat travels with the number, exactly as it does for
`fc_20_34_rel`.
