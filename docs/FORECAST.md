# Outlook layer — population projection 2026–2040

**Status:** v2.4 Phase A · 2026-09-23 · data pipeline only, nothing wired into the app yet
**Source research:** [`docs/FORECAST_SOURCES.md`](FORECAST_SOURCES.md)
**Build:** `scripts/build_forecast.py` · **Check:** `scripts/validate_forecast.py`
**Output:** `data/processed/forecast.json`
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
| `fc_80p` | Projected change, 80 and over | as above on `a80p` | % | `signpct1` |

`fc_growth` and `fc_20_34` carry `chip: true` — the growth headline and the demand signal.

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

Hues reuse the existing palette rather than inventing colours: rust `[166, 42, 22]` for the negative
end throughout; green `[10, 88, 70]` for total-population growth, blue `[40, 84, 128]` for the child
cohorts, purple `[90, 60, 150]` for 20–34 and 80+.

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

Phase A added files only. The one shared file it edited is `config/indicators.json`, and it appended
a **new top-level `forecast` key** rather than adding to `indicators[]`. That was deliberate:

> `scripts/build_makro.py:400 compute()` dispatches on `calc`. An unknown `calc` falls through to the
> generic loop at the end, which calls `rows(db, table)` → `statbank_common.latest_raw()` → returns
> `None` → **`FileNotFoundError`**. Putting `calc: "forecast"` into `indicators[]` today would break
> `build_makro.py` for everyone, including the other worktree. Under its own key the block is inert:
> every existing consumer iterates `indicators`, `macro`, `macro_hero` or `cph.indicators`, and none
> reads `forecast`. Verified — `fetch_statbank.py` and `validate_config.py` also skip it, since both
> filter on `db in ("", "s20", "s30")` and require a `vars` block.

So Phase B's first job is to move the block and teach the pipeline about it:

1. **`config/indicators.json`** — move the seven entries from `forecast.indicators` into
   `indicators[]`, keeping `_doc`, `first_year`, `last_year` and `mid_year` wherever they are still
   useful. Extend the top-level `_doc` to document `calc: forecast`, `db: forecast`, `field`,
   `scale`, `center`, `hue_pos`/`hue_neg` and `direction: neutral`.
2. **`scripts/build_makro.py`**
   - `compute()` (~line 400): add a `calc == "forecast"` branch, next to `infra_index` /
     `public_index` / `schools`. It should read `data/processed/forecast.json` and call
     `indicators()` from `scripts/build_forecast.py` — do not reimplement the arithmetic.
     The layer is snapshot-like (a single vintage, not a per-year history), so it should return `{}`
     when `year` is set, exactly as the `bbr` branch does.
   - the indicator-output block (~line 594): add `"scale"`, `"center"`, `"hue_pos"`, `"hue_neg"` and
     `"field"` to the key list copied into `makro.json`, or the app never sees them.
   - the source-list loop (~line 622): add `"forecast"` to the `db` skip set
     (`"boligstat", "lbf", "bbr", "infra", "public", "schools"`), then append a source entry for it
     from `forecast.json`'s `meta` (label, `asof` = `meta.updated`, `fetched`, `url`, `licence`) the
     way `infra_index` and `public_index` already do.
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
4. **`Makefile`** — add `build_forecast` before `build_makro`, and `validate_forecast` alongside the
   other checks. `build_forecast.py` needs network unless run with `--no-fetch`.
5. **`README.md` / `CHANGELOG.md`** — the Outlook layer, its sources and the §4 splicing rule.
6. **Data-layer follow-ups** (not blocking Phase B):
   - Split the fetch out of `build_forecast.py` into `scripts/fetch_forecast.py` if the repo's
     `fetch_*` / `build_*` separation matters more than the script staying self-contained.
   - `FRKM226` (components of change per municipality: births, deaths, internal migration in/out)
     is already documented in `docs/FORECAST_SOURCES.md` §1.6 and would let the area panel say *why*
     a municipality grows. One extra pull, no new source.
   - The Copenhagen kvarter outlook (`s30/KKFR2026`) is a separate build with its own splicing rule;
     it keys straight onto the existing `OMRKK` kvarter geometry.

---

## 6. Running it

```bash
python3 scripts/build_forecast.py                 # resolve vintage, pull, build forecast.json
python3 scripts/build_forecast.py --no-fetch      # rebuild from the newest cached CSV
python3 scripts/validate_forecast.py              # four checks; non-zero exit on failure
python3 scripts/build_forecast.py --indicators fc_20_34 --top 10
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
