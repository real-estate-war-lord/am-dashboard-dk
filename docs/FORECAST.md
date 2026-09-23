# Outlook layer — population projection 2026–2040

**Status:** v2.4 Phase A · 2026-09-23 · data pipeline only, nothing wired into the app yet
**Source research:** [`docs/FORECAST_SOURCES.md`](FORECAST_SOURCES.md)
**Build:** `scripts/build_forecast.py`, `scripts/build_net_dwellings.py`, `scripts/build_cph_forecast.py`, `scripts/build_cph_backtest.py` · **Check:** `scripts/validate_forecast.py`
**Output:** `data/processed/forecast.json`, `data/processed/net_dwellings.json`, `data/processed/cph_forecast.json` (§8), `data/processed/cph_backtest.json` (§9)
**Research only, not in the UI:** `scripts/build_housing_gap.py` → `data/processed/housing_gap.json` (§7)
**Registry:** `config/indicators.json` → top-level `forecast` key (see §5 for why not `indicators[]`)

The Outlook layer projects each Danish municipality forward from Statistics Denmark's official
municipal population projection, and each Copenhagen kvarter forward from Københavns Kommune's own
(§8 — a different run, never spliced with DST's, see §4). §9 backtests that Copenhagen forecast
against eight superseded vintages and adds the net-migration signal behind it. Phase A ends with
checked data files and a registry entry; Phase B renders them.

---

## 0. 🚫 The hard-data rule

> **Every indicator the map shows must be either an official published figure or plain arithmetic
> on official figures — a difference, a share, a per-1,000, a sum. Nothing shown in the UI may
> contain an assumption, a trend, a cap or a model of our own.**

The rule is not a style preference. This dashboard's value is that a number on it can be traced to a
cell in a published table and reproduced by anyone with the table id. The moment an indicator needs a
parameter we chose — a household size carried forward, a cap on how far it may move, a share assumed
constant — the number stops being a fact about Denmark and becomes a fact about our choices, and the
user has no way to tell the two apart on a choropleth.

**What the rule allows.** DST's population projection is itself a model, and a large one. That is
fine: it is *their* published model, cited by table id and vintage, and the user can read its
assumptions (`docs/FORECAST_SOURCES.md` §1). What we do to it is subtract two of its cells and divide
by a third. The same goes for Københavns Kommune's own forecast (§4, §8). The line the rule draws is
between **arithmetic on someone else's published figures** and **modelling of our own**.

**What it cost.** `fc_hh_gap` and `fc_hh_gap_rel` — the housing gap — were removed from the registry
in this pass. They compared projected household formation with the recent pace of net dwelling
additions, and the demand side needed household size carried forward on a fitted, capped trend. Its
own backtest could not show the trend helped (§7). The build and the file are kept as research, and
`validate_forecast.py` still checks them, but no Phase B note puts them on the map or in a popup.

**What replaced them.** Two indicators, neither of which needs an assumption, and which are meant to
be read **side by side without anything computed between them**:

| | | |
|---|---|---|
| `fc_pop_rate_5y` | projected population change 2026→2031 | **persons** per 1,000 inhabitants per year |
| `hist_net_dwell` | measured net dwelling additions 2020–2026 | **dwellings** per 1,000 inhabitants per year |

The units are different on purpose. Turning persons into dwellings requires a household size, which
is exactly the assumption the rule forbids, so **the two are never differenced, divided or netted**.
The popup shows both with their units and lets the reader do what only the reader can do.

§3's audit table lists every registry entry with its source table and its exact arithmetic;
`validate_forecast.py` check 0 enforces it and fails if an indicator reaches the registry without a
row there.

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

## 3. Indicator definitions — and the audit

Eleven indicators, all municipality-level. Ten are `indicators()` in `scripts/build_forecast.py`
(one definition, so Phase B imports it rather than reimplementing it); `hist_net_dwell` comes from
`scripts/build_net_dwellings.py` and a second file. *P* is `total`; a group name means that group's
count. *y₀* = first year (2026), *y₁* = last year (2040), *y₅* = y₀ + 5 (2031).

| key | label | definition | unit | fmt | group |
|---|---|---|---|---|---|
| `fc_growth` | Projected population growth 2026→2040 | (P₂₀₄₀ − P₂₀₂₆) / P₂₀₂₆ × 100 | % | `signpct1` | Outlook |
| `fc_growth_5y` | Projected population growth 2026→2031 | (P₂₀₃₁ − P₂₀₂₆) / P₂₀₂₆ × 100 | % | `signpct1` | Outlook |
| `fc_pop_rate_5y` | Projected population change 2026→2031, per 1,000 inh. per year | (P₂₀₃₁ − P₂₀₂₆) / 5 / P₂₀₂₆ × 1000 | persons / 1 000 inh. / yr | `signdec1` | Outlook |
| `fc_abs` | Projected population change 2026→2040 | P₂₀₄₀ − P₂₀₂₆ | persons | `int` | Outlook |
| `fc_0_5` | Projected change, children 0–5 | (a0_5₂₀₄₀ − a0_5₂₀₂₆) / a0_5₂₀₂₆ × 100 | % | `signpct1` | Outlook |
| `fc_6_16` | Projected change, children 6–16 | as above on `a6_16` | % | `signpct1` | Outlook |
| `fc_20_34` | Projected change, young adults 20–34 | as above on `a20_34` | % | `signpct1` | Outlook |
| `fc_20_34_rel` | Young adults 20–34 vs Denmark 2026→2040 | `fc_20_34` − Denmark's own 20–34 change | pp | `signdec1` | Outlook |
| `fc_20_34_abs` | Projected change, young adults 20–34 (persons) | a20_34₂₀₄₀ − a20_34₂₀₂₆ | persons | `int` | Outlook |
| `fc_80p` | Projected change, 80 and over | as above on `a80p` | % | `signpct1` | Outlook |
| `hist_net_dwell` | Net dwelling additions per year 2020–2026, per 1,000 inh. | (stock₂₀₂₆ − stock₂₀₂₀) / 6 / pop × 1000 | dwellings / 1 000 inh. / yr | `signdec1` | **Housing stock** |

`fc_growth` and `fc_20_34` carry `chip: true` — the growth headline and the demand signal.

**`hist_net_dwell` is not in Outlook, on purpose.** It is a measurement, not a projection: what the
dwelling stock actually did over the last published window. Putting it under Outlook would imply it
says something about the future, which it does not. It belongs beside the other BOL101 indicators in
**Housing stock**, and it is staged in the `forecast` key only because its `calc` is new (§5).
Its window is **six years, not five** — DST publishes no BOL101 for 2021 or 2022, both closed over
errors in the Building and Housing Register — so the change is annualised over the span that actually
separates its two ends. The years are resolved from the table on every run and recorded in
`meta.label_years`; the label must be rendered from that, never hard-coded.

### The audit — every indicator, its source table and its exact arithmetic

Required by §0 and enforced by `validate_forecast.py` check 0, which fails if an entry appears in the
registry without a row in its `AUDIT` table, if a row records an assumption, or if no build produces
the key. **`assumption` is `None` for all eleven.**

| key | source table(s) | exact arithmetic | assumption |
|---|---|---|---|
| `fc_growth` | `FRKM1xx` | (P_y1 − P_y0) / P_y0 × 100 | none |
| `fc_growth_5y` | `FRKM1xx` | (P_y5 − P_y0) / P_y0 × 100 | none |
| `fc_pop_rate_5y` | `FRKM1xx` | (P_y5 − P_y0) / 5 / P_y0 × 1000 | none |
| `fc_abs` | `FRKM1xx` | P_y1 − P_y0 | none |
| `fc_0_5` | `FRKM1xx` | (a0_5_y1 − a0_5_y0) / a0_5_y0 × 100 | none |
| `fc_6_16` | `FRKM1xx` | (a6_16_y1 − a6_16_y0) / a6_16_y0 × 100 | none |
| `fc_20_34` | `FRKM1xx` | (a20_34_y1 − a20_34_y0) / a20_34_y0 × 100 | none |
| `fc_20_34_rel` | `FRKM1xx` | `fc_20_34` − the same expression evaluated on Σ of the 98 kommuner | none |
| `fc_20_34_abs` | `FRKM1xx` | a20_34_y1 − a20_34_y0 | none |
| `fc_80p` | `FRKM1xx` | (a80p_y1 − a80p_y0) / a80p_y0 × 100 | none |
| `hist_net_dwell` | `BOL101` + `FOLK1A` | (stock_end − stock_start) / span_years / population × 1000 | none |

Three things are worth stating explicitly, because each *looks* like it might be an assumption:

- **The age-group boundaries** (0–5, 6–16, 17–19, 20–34, 35–64, 65–79, 80+) are a choice, but they
  are a choice of **which published single-year cells to add up**, not a choice about a value. The
  groups are contiguous and exhaustive, so nothing is dropped or imputed, and `total` is DST's own
  `ALDER=TOT` cell rather than the sum (§2).
- **"Denmark" in `fc_20_34_rel`** is Σ of the same 98 municipalities from the same file, not a
  separately rounded national table and not an average of ratios. Check 5 reconciles it against
  `FRDK126`'s published age detail to 0.0004 pp.
- **`hist_net_dwell`'s six-year span** is read from the table, not assumed. BOL101's published years
  determine the window; if DST reopens 2021 and 2022 the window becomes five years on the next run
  with no code change.

What is *not* in the table — the things the source itself assumes — belongs in each entry's `warn`
and is stated at the source, not hidden: DST's projection carries each municipality's recent
fertility, mortality and migration behaviour forward and contains **no housing programme**; BOL101
counts dwellings that exist, not dwellings that are available.

### The audit, part b — the Copenhagen-only keys

These live in `cph_forecast.json` and `cph_backtest.json` and are **deliberately not in
`config/indicators.json`**: Phase A's rule is that Copenhagen-only indicators stay out of the
registry and are added under the `cph` key by Phase B (§8, §9). The hard-data rule applies to them
exactly the same, so `validate_forecast.py` check 0 audits them here — and also asserts that none of
them has leaked into the registry.

Most of them are **research: computed, checked, documented and never rendered.** Passing §0 is a
floor, not a warrant; §9.7 gives the reason for each. The `ui` column is enforced, not descriptive —
`validate_forecast.py --ui` builds the UI inventory from it.

*y₀* = the vintage year (2026); the movement windows are defined in §9.4.

| key | ui | source table(s) | exact arithmetic | assumption |
|---|---|---|---|---|
| `fc_netmig_5y` | 🚫 | `KKFRBEDI` | Σ `06 Nettotilflytning` over movement years y₀…y₀+4 | none |
| `fc_netmig_5y_per1000` | 🚫 | `KKFRBEDI` + `KKFR<V>` | `fc_netmig_5y` / P_y₀ × 1000 | none |
| `fc_netmig` | 🚫 | `KKFRBEDI` | Σ `06 Nettotilflytning` over movement years y₀…y_last−1 | none |
| `fc_netmig_per1000` | 🚫 | `KKFRBEDI` + `KKFR<V>` | `fc_netmig` / P_y₀ × 1000 | none |
| `fc_netmig_gap` | 🚫 | `KKFRBEDI` + `KKFR<V>` | (P_y_last − P_y₀) − Σ(`03 Fødselsoverskud` + `06 Nettotilflytning`) over the window | none |
| `fc_netmig_gap_per1000` | 🚫 | `KKFRBEDI` + `KKFR<V>` | `fc_netmig_gap` / P_y₀ × 1000 | none |
| `fc_netmig_reconciles` | 🚫 | `KKFRBEDI` + `KKFR<V>` | \|`fc_netmig_gap`\| ≤ max(5 × window years, 1 % of P_y₀) | none — a threshold, see below |
| `bt_mape` | 🚫 | `KKFR<V>` + `KKBEF1` | mean over (vintage, horizon ≥ 1) of \|F − A\| / A × 100 | none |
| `bt_bias` | 🚫 | `KKFR<V>` + `KKBEF1` | mean over (vintage, horizon ≥ 1) of (F − A) / A × 100 | none |
| `bt_medape` | 🚫 | `KKFR<V>` + `KKBEF1` | median over (vintage, horizon ≥ 1) of \|F − A\| / A × 100 | none |
| `bt_mae` | 🚫 | `KKFR<V>` + `KKBEF1` | mean over (vintage, horizon ≥ 1) of \|F − A\|, in persons | none |
| `bt_baseline_mape` | 🚫 | `KKFR<V>` + `KKBEF1` | `bt_mape` with F = `KKFR<V>`(k, V) × `KKFR<V>`(city, V+h) / `KKFR<V>`(city, V) | none |
| `bt_mape_5y` | **✅** | `KKFR<V>` + `KKBEF1` | mean over the vintages scoreable at horizon 5 of \|F − A\| / A × 100 | none |
| `bt_over_5y` | **✅** | `KKFR<V>` + `KKBEF1` | count of those vintages with F > A | none |
| `bt_n_5y` | **✅** | `KKFR<V>` + `KKBEF1` | count of those vintages | none |
| `bt_line_eligible` | **✅** | `KKFR<V>` + `KKBEF1` | `bt_n_5y` ≥ 3 — below that the area shows no line at all | none — a threshold |

The four ✅ keys are the whole of §9.7's past-accuracy line, on Copenhagen kvarter and bydel **area
pages only**. Nothing else from `cph_backtest.json` is rendered, and **`fc_netmig` is not rendered at
all** — §9.7 note 2 explains why a signal that passes §0 can still be wrong to show.

**`fc_netmig_reconciles` is a threshold, not an assumption, and the distinction is worth stating.**
An assumption changes a displayed value; this changes nothing — it is a QA flag over two published
series, in the same family as check 9's `TOL_CITY`. It is also not doing any real work: on the 2026
vintage every gap it passes is ≤ 26 persons and every gap it catches is ≥ 412, a 16× separation, so
any threshold in a wide band gives the same five kvarterer (§9). If a future vintage puts a value in
that band, the flag has become load-bearing and the rule needs revisiting rather than retuning.

**The ten `fc_*` keys of §3 are produced for Copenhagen too**, by the same `indicators()`. They need
no second audit row: the arithmetic is identical and only the source table (`KKFR<V>` instead of
`FRKM1xx`) and `fc_20_34_rel`'s baseline (the city, not Denmark — §8) differ. They do appear twice in
the UI inventory, once per level. `hist_net_dwell` has no Copenhagen counterpart, because BOL101 does
not publish a dwelling stock below the municipality.

### The UI inventory

```bash
python3 scripts/validate_forecast.py --ui
```

prints **every indicator this branch puts in front of a user and nothing else** — 25 entries: the 11
registry indicators at kommune level, the same ten `fc_*` again at bydel and kvarter level from
`KKFR<V>`, and the four keys behind the past-accuracy line. It is assembled from the two audit tables
above, so it cannot drift from what check 0 allows, and it ends by naming what is deliberately
excluded: the housing gap (§7) and the twelve Copenhagen research keys (§9).

### The pair that must not be combined

`fc_pop_rate_5y` and `hist_net_dwell` share a denominator (per 1 000 inhabitants) and a period basis
(per year), which makes them directly readable against each other — and makes it tempting to subtract
one from the other. **Do not.** Denmark is +2.34 persons and +5.07 dwellings per 1 000 per year; the
difference of those two numbers is not a surplus of 2.73 dwellings, because a person is not a
household. Converting between them needs an average household size, and a *projected* household size
at that — which is precisely the assumption §0 forbids and §7 is the record of.

Phase B shows them **side by side, each labelled with its own unit**, and computes nothing between
them.

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

Every indicator staged in the `forecast` key is **`direction: "neutral"`**, `hist_net_dwell`
included. Neither end is "better": a shrinking municipality is not failing and a growing one is not
succeeding, and a municipality that built a lot is not thereby doing well — so these must never be
ranked good-to-bad or coloured with the good/bad ramp the other groups use. The registry's existing
`direction` vocabulary is `higher_better` / `lower_better` only, so `neutral` is new — see §5.

Every one of them uses a **diverging scale centred on 0** (`scale: "diverging"`, `center: 0`),
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

**`hist_net_dwell` is effectively one-sided as well** — 97 of 98 municipalities added dwellings over
2020–2026, and the exception (Ærø, −0.44 per 1 000 per year) is barely below the line. The ramp stays
centred on 0 because zero is a real boundary for a *net* change: it separates a stock that grew from
one that shrank, which no amount of spread makes equivalent.

Hues reuse the existing palette rather than inventing colours: rust `[166, 42, 22]` for the negative
end throughout; green `[10, 88, 70]` for total-population growth (including `fc_pop_rate_5y`), blue
`[40, 84, 128]` for the child cohorts, purple `[90, 60, 150]` for 20–34 and 80+ (and for both 20–34
sub-indicators), teal `[12, 94, 104]` for the positive end of `hist_net_dwell`.

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
- A Copenhagen kvarter view uses KK throughout and says so on the panel. It is built — **§8** —
  and lives in its own file, `data/processed/cph_forecast.json`, for exactly this reason.
- Wherever both could be read at once, state the gap rather than hiding it. `validate_forecast.py`
  check 9 prints it per year so it cannot quietly stop being true; §8 has the full table, including
  the **2028 crossover**, where DST has the city falling and KK has it rising.

The reason they differ is structural, not a data error. DST projects all 98 municipalities on one
national frame from each municipality's own historical rates. Copenhagen projects its own city from
CPR microdata, anchored to DST/DREAM's national projection, and — critically — its **city total
excludes housing plans by design** while its **district split is driven by an unpublished housing
programme** (`docs/FORECAST_SOURCES.md` §2.6). Neither is more correct; they answer slightly
different questions.

---

## 5. Phase B notes — what has to change in files Phase A did not touch

Phase A added files only — `scripts/build_forecast.py`, `scripts/build_net_dwellings.py`,
`scripts/build_cph_forecast.py`, `scripts/build_housing_gap.py`, `scripts/validate_forecast.py` and
this document. The one shared file
it edited is `config/indicators.json`, and it appended a **new top-level `forecast` key** rather than
adding to `indicators[]`. That was deliberate:

> `scripts/build_makro.py:400 compute()` dispatches on `calc`. An unknown `calc` falls through to the
> generic loop at the end, which calls `rows(db, table)` → `statbank_common.latest_raw()` → returns
> `None` → **`FileNotFoundError`**. Putting `calc: "forecast"` into `indicators[]` today would break
> `build_makro.py` for everyone, including the other worktree. Under its own key the block is inert:
> every existing consumer iterates `indicators`, `macro`, `macro_hero` or `cph.indicators`, and none
> reads `forecast`. Verified — `fetch_statbank.py` and `validate_config.py` also skip it, since both
> filter on `db in ("", "s20", "s30")` and require a `vars` block.

So Phase B's first job is to move the block and teach the pipeline about it:

1. **`config/indicators.json`** — move the eleven entries from `forecast.indicators` into
   `indicators[]`, keeping `first_year`, `last_year` and `mid_year` wherever they are still useful.
   **The ten `fc_*` entries go to the `Outlook` group; `hist_net_dwell` goes to `Housing stock`**,
   beside the other BOL101 indicators — it is a measurement, not a projection (§3). Extend the
   top-level `_doc` to document `calc: forecast`, `calc: net_dwellings`, `db: forecast`,
   `db: net_dwellings`, `field`, `scale`, `center`, `hue_pos`/`hue_neg` and `direction: neutral`,
   and carry the hard-data rule (§0) into it. Consider moving `chip: true` from `fc_20_34` to
   `fc_20_34_rel` — the relative version is the one that reads as a map (§3).
   **Nothing from `housing_gap.json` goes into `indicators[]`.** It was removed in this pass and
   stays research (§0, §7).
2. **`scripts/build_makro.py`**
   - `compute()` (~line 400): add a `calc == "forecast"` branch, next to `infra_index` /
     `public_index` / `schools`. It should read `data/processed/forecast.json` and call
     `indicators()` from `scripts/build_forecast.py` — do not reimplement the arithmetic.
     The layer is snapshot-like (a single vintage, not a per-year history), so it should return `{}`
     when `year` is set, exactly as the `bbr` branch does. Entries are looked up by `key`:
     `indicators()` returns one dict per kommune keyed by exactly the registry keys, so the branch
     is a lookup, not a dispatch on `field`.
   - a second branch for `calc == "net_dwellings"`, reading `data/processed/net_dwellings.json` and
     returning `kommuner[code][ind["field"]]`, so the branch is a `field` lookup rather than one
     hard-coded name. Same snapshot rule: `{}` when `year` is set. `net_dwellings.json` holds every
     component (`stock_start`, `stock_end`, `span_years`, `net_per_year`, `pop`), so the popup can
     show the working without a second read.
   - the indicator-output block (~line 594): add `"scale"`, `"center"`, `"hue_pos"`, `"hue_neg"` and
     `"field"` to the key list copied into `makro.json`, or the app never sees them.
   - the source-list loop (~line 622): add `"forecast"` **and `"net_dwellings"`** to the `db` skip
     set (`"boligstat", "lbf", "bbr", "infra", "public", "schools"`), then append a source entry for
     each from the respective `meta` (label, `asof` = `meta.updated`, `fetched`, `url`, `licence`)
     the way `infra_index` and `public_index` already do. `net_dwellings.json`'s `meta.tables`
     carries a per-table `updated` stamp, so its source entry should name **BOL101 and FOLK1A**
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
4. **`Makefile`** — add `build_forecast` and `build_net_dwellings` before `build_makro`, and
   `build_cph_forecast` before `build_cph`; `validate_forecast` alongside the other checks. All three
   need network unless run with `--no-fetch`; they are independent of each other, so the order between
   them does not matter.
   `build_housing_gap.py` is **not** part of the build — it is research, run by hand, and must run
   after `build_forecast.py` because it reads `forecast.json` for P₂₀₂₆ and P₂₀₃₁.
5. **`README.md` / `CHANGELOG.md`** — the Outlook layer, its sources, the §0 hard-data rule and the
   §4 splicing rule.
6. **The Copenhagen drill-down** — its own five notes, in **§8**. In short: the registry entries go
   under the `cph` key (which Phase A did not touch), the panel must name KK as its source and state
   the gap against DST, `fc_20_34_rel` must be labelled *vs København*, and `meta.caveat` — that a
   kvarter number is the city's unpublished housing programme in disguise — has to reach the UI.
7. **The popup and the area page** — show `fc_pop_rate_5y` and `hist_net_dwell` **side by side, each
   with its own unit** (persons per 1 000 per year, dwellings per 1 000 per year), and compute
   **nothing** between them: no difference, no ratio, no "surplus" or "shortfall" wording. §0 and §3
   say why. `hist_net_dwell`'s label carries its real years, read from `meta.label_years`, and its
   working (`stock_start` → `stock_end` over `span_years`) belongs in the popup so the six-year
   window is visible rather than surprising.
8. **Data-layer follow-ups** (not blocking Phase B):
   - Split the fetch out of `build_forecast.py` into `scripts/fetch_forecast.py` if the repo's
     `fetch_*` / `build_*` separation matters more than the script staying self-contained.
   - `FRKM226` (components of change per municipality: births, deaths, internal migration in/out)
     is already documented in `docs/FORECAST_SOURCES.md` §1.6 and would let the area panel say *why*
     a municipality grows. One extra pull, no new source.
   - ~~The Copenhagen kvarter outlook (`s30/KKFR2026`)~~ — **done, §8.** It keyed straight onto the
     existing `OMRKK` kvarter geometry with no crosswalk, as the research predicted.
   - `KKBOL3` (dwellings per kvarter) would give Copenhagen its own `hist_net_dwell`, the one
     indicator §8 is missing. Same four operations, same rule, one extra pull.
   - `FRKM226`-equivalent for Copenhagen: `KKFRBEDI` holds the projected movements (births, deaths,
     migration) per district from the same run, and would let a kvarter panel say *why* it grows.
   - **The one route back for a housing-balance indicator.** DST publishes an official household
     projection (`FRHUS1xx`). Built on that, the demand side would be a published figure rather than
     our fitted, capped household-size trend, and the whole indicator would become arithmetic on two
     official projections — which §0 allows. That, not a better-tuned trend, is what would make it
     admissible; §7 is the record of why the fitted version is not.
   - **Rerun the §7 backtest on the next vintage.** It currently says the fitted formula ranks
     municipalities *worse* than the superseded one on the 2020→2025 window, while both of its
     components score better in isolation (§7). One window is not a verdict, and the code is already
     written — but until it says otherwise the indicator stays out of the UI regardless, because §0
     rules it out on its inputs, not on its score.

---

## 6. Running it

```bash
python3 scripts/build_forecast.py                 # resolve vintage, pull, build forecast.json
python3 scripts/build_forecast.py --no-fetch      # rebuild from the newest cached CSV
python3 scripts/build_net_dwellings.py            # BOL101 + FOLK1A → net_dwellings.json
python3 scripts/build_net_dwellings.py --no-fetch # rebuild from cached CSVs only
python3 scripts/validate_forecast.py              # the checks below; non-zero exit on failure
python3 scripts/validate_forecast.py --audit      # check 0 on its own — the hard-data audit
python3 scripts/validate_forecast.py --ui         # every indicator that reaches the UI, and nothing else
python3 scripts/build_forecast.py --indicators fc_20_34_rel --top 10
python3 scripts/build_forecast.py --indicators fc_pop_rate_5y --top 10

python3 scripts/build_cph_forecast.py             # s30/KKFRxxxx + KKFRBEDI → cph_forecast.json (§8, §9)
python3 scripts/build_cph_forecast.py --no-fetch  # rebuild from the newest cached CSV
python3 scripts/build_cph_forecast.py --rank 0    # build without the kvarter rankings

python3 scripts/build_cph_backtest.py             # replay every served vintage → cph_backtest.json (§9)
python3 scripts/build_cph_backtest.py --no-fetch  # rebuild from cached CSVs
python3 scripts/build_cph_backtest.py --back 10   # how many vintage ids to probe

# research only, not part of the build and not in the UI (§0, §7)
python3 scripts/build_housing_gap.py              # needs forecast.json; writes housing_gap.json
```

`build_net_dwellings.py` shares its BOL101 and FOLK1A pulls with `build_housing_gap.py` in
`data/raw/forecast/housing/`, so whichever runs first pays for the download.

`validate_forecast.py` prints, in order:

0. **registry audit** — every entry in `config/indicators.json`'s `forecast` key against its source
   table and its exact arithmetic (the §3 table), against the keys `indicators()` actually returns,
   and against the hard-data rule. **Fails** if an entry has no audit row, if a row records an
   assumption, if an audited key has left the registry, or if no build produces a key. Currently
   **11 of 11 indicators, 0 assumptions**.
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
   the identities `fc_20_34_rel = fc_20_34 − Denmark` (98/98), `Σ fc_20_34_abs = −85 641` and
   `fc_pop_rate_5y = (P₂₀₃₁ − P₂₀₂₆) / 5 / P₂₀₂₆ × 1000` (98/98, written out a second time rather
   than by calling `indicators()` again — Denmark is **+2.34** persons per 1 000 per year). Then the
   rankings. The `FRDK126` age detail is read from the cached research snapshot when present and
   pulled from the API otherwise — 106 ages × 2 years.
6. **net dwellings** — 98 municipalities × 7 components, 0 null, none absent; `Σ kommuner = Denmark`
   for `stock_start`, `stock_end` and `pop`; then `hist_net_dwell` recomputed for København, Aarhus,
   Brøndby, Lemvig and Frederiksberg straight from the raw `BOL101` and `FOLK1A` cells and printed
   cell by cell. Denmark: 3 113 345 → 3 296 927 dwellings, **+30 597 a year over 6 031 608
   inhabitants = +5.07 per 1 000**.
7. **housing gap coverage** — *research only, not a map indicator.* 98 municipalities × 20
   components, 0 null, none absent.
8. **housing gap by hand** — *research only.* `gap_per_1000` recomputed for the same five
   municipalities straight from the raw `FOLK1A` / `FAM55N` / `BOL101` cells and printed cell by
   cell, then compared with the stored value.

9. **Copenhagen** — the KK kvarter forecast: coverage (67 kvarterer × 15 years), the three
   additivity identities, `KKFR` 2026 vs the newest observed `KKBEF1` per kvarter, and the KK-vs-DST
   city total per year. Parts 1–3 **fail**; parts 4–5 are information, because a difference between
   two published runs is not a bug. **§8** has the numbers. Part **9f** adds the build-out signal:
   `fc_netmig` present for all 68 kvarterer, 11 bydele and the city, and additive at every level
   (**fails**), then the five kvarterer where `fc_netmig` does not reconcile with the stock table
   (information — **§9.5**).
10. **KK forecast backtest** — every served vintage replayed against `KKBEF1`: MAPE, bias and skill
    against a pro-rata city baseline at horizons 1, 3 and 5, plus the worst kvarterer. Mostly
    **information** — it measures Københavns Kommune's record, not this build. Two things do fail:
    an internally inconsistent summary, and a broken **past-accuracy line** (§9.7), whose four keys
    are the only backtest figures the UI may show. The line's own rule — `bt_n_5y ≥ 3` or show
    nothing — is asserted here against every area. **§9** has the numbers.

Checks 6, 7/8, 9 and 10 are **skipped, not failed**, when their file has not been built, and 6 and 8
report politely if the raw pulls they name have been cleaned away (they are gitignored). 7 and 8 still
run against `housing_gap.json` even though nothing renders it — a research file that has quietly gone
wrong is still worth knowing about.

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

## 7. The housing gap — 🚫 **research only, removed from the UI**

**Build:** `scripts/build_housing_gap.py` · **Output:** `data/processed/housing_gap.json`
**Check:** `scripts/validate_forecast.py` checks 7 and 8 · **Registry:** none

> **This indicator is not on the map and has no Phase B note that would put it there.**
> `fc_hh_gap` and `fc_hh_gap_rel` were removed from `config/indicators.json` under the hard-data rule
> (§0): the demand side needs household size carried forward on a fitted, capped trend, which is an
> assumption of ours rather than a published figure. The build, the file and the backtest are kept
> because the question is a good one and the working is worth preserving — but nothing below is a
> plan to render it. The measured half of the question now lives in `hist_net_dwell` (§3), which
> needs no assumption at all.
>
> The one route back is DST's **official** household projection (`FRHUS1xx`), which would make the
> demand side a published figure; see §5 note 7. Everything from "Formula" on is the record of the
> version that was built, kept as it was written.

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

Every component is stored, not just the answer, so the working is on record and check 8 can
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
(check 7 asserts both the identity and the sum). That puts **41 of 98 above the line and 57 below**,
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

`scripts/validate_forecast.py` check 7 asserts 98 municipalities with all twenty components present
and non-null, plus the two identities `fc_hh_gap_rel` depends on: `gap_per_1000_rel = gap_per_1000 −
Denmark's`, for all 98, and `Σ kommuner = Denmark` for `demand_5y`, `supply_5y` and `p_base`. Check 8
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

### Why the sentence could not be written — the reason the indicator is out

The popup this indicator needed would have read:

> *Projection implies ~N more households, recent pace adds ~M dwellings → gap K*

Three things went wrong with it, and together they are the case for §0.

1. **"Implies ~N more households" is our claim, not DST's.** DST projects *people*. The step from
   people to households is `persons_per_hh` carried forward five years on a fitted trend and capped
   at ±5 %, and the whole sentence hangs on it. A reader has no way to see that from the map.
2. **The sentence breaks on the shrinking case.** N is negative for 14 municipalities, where
   "implies ~−242 more households" is nonsense and the wording has to fork. That is a symptom: the
   quantity is not one thing.
3. **The backtest could not defend the trend.** On 2020→2025 the fitted version ranks municipalities
   *worse* than the frozen-household-size version it replaced. A modelling choice that cannot beat
   its own null has no business colouring 98 polygons.

What survives is the half that needs no model: `hist_net_dwell` (§3) shows M — the measured net
additions — on its own, and `fc_pop_rate_5y` shows the projected population change in persons beside
it. The reader sees both official figures and is not handed a conversion nobody published.

---

## 8. The Copenhagen kvarter forecast — `cph_forecast.json`

**Build:** `scripts/build_cph_forecast.py` · **Output:** `data/processed/cph_forecast.json`
**Check:** `scripts/validate_forecast.py` check 9 · **Source research:** `docs/FORECAST_SOURCES.md` §2

Københavns Kommune publishes its **own** population projection down to kvarter level, through the
`s30` sub-database of the same API. It is a different run from DST's (§4), so it is a separate file,
a separate build and a separate view — never a splice. It obeys the same hard-data rule as everything
else (§0): every value is a published `KKFR` cell or plain arithmetic on published `KKFR` cells.

### Source

| what | where | licence | geography | horizon | vintage |
|---|---|---|---|---|---|
| KK projection | **`KKFR2026`** via `api.statbank.dk/v1/**s30**` | free reuse with attribution *Københavns Kommune* | 93 `OMRKK` districts | 2060 | 2026, updated 2026-03-13 |

**The table id carries the vintage**, like DST's, and KK replaces it each March rather than keeping a
history — so it is resolved from the live `s30` catalogue on every run. The pattern is `^KKFR(\d{4})$`
and the four digits matter: `KKFRBEV` and `KKFRBEDI` share the prefix, keep stable names across
vintages, and are different tables entirely.

**The sub-database has its own data endpoint.** `POST /v1/data` returns `400 Bad Request` for an
`s30` table; the pull goes to `POST /v1/s30/data`. Same for `tables` and `tableinfo`.

**Sex is not summed here.** Unlike `FRKM126`, `KKFR` publishes an explicit `KON=TOT`, so the pull asks
for that cell and nothing is added up on our side. (`FRKM126` has no both-sexes code, which is why
`build_forecast.py` makes two pulls and sums them — §1.)

**One pull, not four.** 93 districts × 101 ages × 15 years = **140 895 cells**, well under the
1 000 000-cell CSV cap. `fetch()` computes the per-year cell cost anyway and splits the request into
year batches if a longer `--years` window would exceed the cap, so the script does not need editing
to reach 2060. Every pull carries its year range in the filename (`KKFR2026_dist_age_2026-2040_<date>.csv`)
whether it was split or not, so `--no-fetch` can tell one run's chunks from another's; a re-pull
clears the same day's older chunks first, and `aggregate()` refuses overlapping year ranges outright
rather than adding the overlap twice. The split path was exercised against the live API by forcing a
60 000-cell cap: three pulls, byte-identical result.

### Geography — four nested levels in one variable

`OMRKK` carries the city, the bydele, the lokaludvalg and the kvarterer **at once**, plus one
*"Uden for inddeling"* bucket per level:

| level | codes | n | bucket |
|---|---|---:|---|
| city | `1000` | 1 | — |
| bydel | `1001`–`1010` | 10 | `1099` |
| lokaludvalg | `2001`–`2012` | 12 | `2099` |
| kvarter | `2LLxx` | 67 | `29999` |

**The buckets stay in the file and stay off the map.** They are the same ~3 700 people (0.55 % of the
city) at all three levels, and without them no level re-sums to the city total. They have no geometry,
so `meta.unallocated` names them and any consumer drawing polygons must skip them.

**No crosswalk anywhere.** `KKFR2026`'s `OMRKK` code list is byte-identical to `KKBEF1`'s, which
`scripts/build_cph.py` and `data/geo/cph_kvarterer.geojson` already key on — so the observed 2016–2026
series and the 2026–2040 projection are one continuous line per kvarter, with no matching step.
The kvarter → lokaludvalg step is the code structure itself (`2LLxx` → `20LL`); the lokaludvalg →
bydel step reuses `LOK2BYDEL` from `build_cph.py` rather than restating it, and check 9 proves the
result by summing (11/11 bydele, worst 2 persons).

### Indicators — the same ten, computed by the same function

`indicators()` is **imported from `build_forecast.py`**, not reimplemented, so a kvarter figure and a
municipal figure cannot drift apart in how they are derived. Every key in §3 except `hist_net_dwell`
is produced for every `OMRKK` code — city, bydele, lokaludvalg and kvarterer alike: `fc_growth`,
`fc_growth_5y`, `fc_pop_rate_5y`, `fc_abs`, `fc_0_5`, `fc_6_16`, `fc_20_34`, `fc_20_34_rel`,
`fc_20_34_abs`, `fc_80p`.

**No housing indicator at this level.** `hist_net_dwell` needs a dwelling stock per area, which
BOL101 does not publish below the municipality. KK's `KKBOL3` does publish dwellings per kvarter and
would make the same arithmetic possible — that is a separate build, and it is not in this one.

> ### 🚩 `fc_20_34_rel` here is measured against **København**, not Denmark
>
> The 93 `OMRKK` codes are four nested levels of one city, so their sum counts every resident four
> times and is not a baseline. `indicators()` therefore takes an explicit `ref` — the city series
> (`OMRKK 1000`) — added in this pass for exactly this case. The default (Σ of the areas) is still
> right for the municipal file, where the 98 kommuner *are* Denmark.
>
> The number the city subtracts is its own **−3.1 %** 20–34 change, against Denmark's −7.1 %. The two
> variants of `fc_20_34_rel` are therefore **not comparable and must never share a legend**: the same
> `+5 pp` means "5 points better than Denmark" on the municipal map and "5 points better than
> Copenhagen" here. `meta.relative_baseline` records which, and the label must say *vs København*.

### The bydele, 2026 → 2040

| code | bydel | 2026 | 2040 | `fc_growth` | `fc_abs` | `fc_pop_rate_5y` | `fc_0_5` | `fc_6_16` | `fc_20_34` | `fc_20_34_rel` | `fc_80p` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1004` | Vesterbro/Kongens Enghave | 84 925 | 103 569 | +21.9 % | +18 644 | +14.6 | +26.4 % | +18.4 % | +15.4 % | +18.5 pp | +108.3 % |
| `1009` | Amager Øst | 63 942 | 76 992 | +20.4 % | +13 050 | +7.8 | +28.7 % | +20.1 % | +11.6 % | +14.7 pp | +54.1 % |
| `1002` | Østerbro | 82 153 | 93 442 | +13.7 % | +11 289 | +6.7 | +28.8 % | +7.2 % | +10.6 % | +13.7 pp | +53.0 % |
| `1010` | Amager Vest | 91 678 | 99 852 | +8.9 % | +8 174 | +16.4 | +16.5 % | −0.0 % | −1.7 % | +1.5 pp | +59.1 % |
| `1005` | Valby | 66 391 | 71 262 | +7.3 % | +4 871 | +6.4 | +13.1 % | +1.3 % | −6.2 % | −3.1 pp | +51.4 % |
| `1007` | Brønshøj-Husum | 45 076 | 46 318 | +2.8 % | +1 242 | +3.8 | +3.1 % | −7.9 % | −7.8 % | −4.6 pp | +39.3 % |
| `1001` | Indre By | 57 366 | 58 683 | +2.3 % | +1 317 | −3.4 | +25.9 % | +1.1 % | −7.5 % | −4.3 pp | +34.6 % |
| `1003` | Nørrebro | 79 895 | 80 453 | +0.7 % | +558 | +2.7 | +8.4 % | +5.5 % | −18.2 % | −15.1 pp | +58.5 % |
| `1006` | Vanløse | 40 803 | 39 844 | −2.4 % | −959 | +1.3 | −0.4 % | −12.6 % | −16.7 % | −13.6 pp | +60.0 % |
| `1008` | Bispebjerg | 55 730 | 53 419 | −4.2 % | −2 311 | −1.6 | +2.0 % | −1.1 % | −24.0 % | −20.9 pp | +32.2 % |
| | **København i alt** | **671 672** | **727 141** | **+8.3 %** | **+55 469** | **+6.5** | **+16.4 %** | **+3.8 %** | **−3.1 %** | **±0.0 pp** | **+53.0 %** |

Two things worth reading off it. **Amager Vest's `fc_pop_rate_5y` (+16.4) is the highest in the city
while its `fc_growth` (+8.9 %) is mid-table** — Ørestad's growth is front-loaded into the first five
years and then stops, which is precisely the difference between a rate over the near window and a
change over fourteen years; both are in the file and the popup should not show only one.
**`fc_20_34` splits the city almost in half** — Vesterbro +15.4 % against Bispebjerg −24.0 %, a
39-point spread inside one municipality that the DST map necessarily shows as a single −6.8 %.

### Kvarter rankings, 2026 → 2040

Printed by `build_cph_forecast.py` after every build (`--rank 0` to suppress). The `29999` bucket is
excluded from the rankings; 67 kvarterer are ranked.

**`fc_growth` — fastest growing / fastest shrinking**

| | kvarter | | | kvarter | |
|---|---|---:|---|---|---:|
| 1 | Vesterbro – Syd | +203.0 % | 1 | Indre By – Østerport | −14.7 % |
| 2 | Østerbro – Nordhavn | +176.0 % | 2 | Indre By – Øster Farimagsgade | −12.5 % |
| 3 | Christianshavn – Holmen og Refshaleøen | +107.3 % | 3 | Østerbro – Rosenvænget | −11.9 % |
| 4 | Amager Øst – Nordøstamager | +101.1 % | 4 | Østerbro – Nord/Komponistkvarteret | −10.5 % |
| 5 | Amager Vest – Ørestad City | +48.7 % | 5 | Amager Vest – Sundbyvester | −9.3 % |
| 6 | Kgs. Enghave – Gl. Sydhavn | +46.0 % | 6 | Østerbro – Århusgade Syd | −9.2 % |
| 7 | Østerbro – Ny Ryvang | +35.3 % | 7 | Brønshøj-Husum – Brønshøj | −8.6 % |
| 8 | Amager Vest – Grønjordssøen | +28.9 % | 8 | Vanløse – Jyllingevej Kvarter | −8.4 % |
| 9 | Valby – Vigerslev | +25.4 % | 9 | Brønshøj-Husum – Husum | −8.4 % |
| 10 | Brønshøj-Husum – Husum Nord | +23.7 % | 10 | Bispebjerg – Utterslev | −8.4 % |

✅ **This is the expected shape.** Vesterbro Syd, Nordhavn and Nordøstamager are at the top and
Østerport at the bottom, matching `docs/FORECAST_SOURCES.md` §6.3 exactly. A future vintage that does
*not* put the big development sites at the top is a signal to check the pull before believing it.

**`fc_abs` — the same story in people rather than percent**

| | kvarter | | | kvarter | |
|---|---|---:|---|---|---:|
| 1 | Østerbro – Nordhavn | +11 500 | 1 | Brønshøj-Husum – Husum | −1 337 |
| 2 | Amager Øst – Nordøstamager | +10 414 | 2 | Amager Vest – Sundbyvester | −1 252 |
| 3 | Vesterbro – Syd | +9 660 | 3 | Østerbro – Rosenvænget | −1 198 |
| 4 | Kgs. Enghave – Gl. Sydhavn | +6 552 | 4 | Bispebjerg – Nordvest | −1 121 |
| 5 | Amager Vest – Ørestad City | +5 652 | 5 | Østerbro – Århusgade Syd | −1 094 |

The ordering changes at the top — Nordhavn's +11 500 people outrank Vesterbro Syd's +203 % — and
**Østerport leaves the bottom five entirely**: −14.7 % of 4 607 people is −675, while Husum loses
1 337 at −8.4 %. Both columns belong in the UI for the same reason `fc_abs` exists nationally (§3).

**`fc_20_34_abs` — where the young adults actually move**

| | kvarter | | | kvarter | |
|---|---|---:|---|---|---:|
| 1 | Østerbro – Nordhavn | +6 441 | 1 | Bispebjerg – Nordvest | −4 332 |
| 2 | Amager Øst – Nordøstamager | +5 067 | 2 | Nørrebro – Mimersgade/Nørrebro St. | −2 528 |
| 3 | Vesterbro – Syd | +4 225 | 3 | Nørrebro – Guldbergskvarteret/Panum | −1 655 |
| 4 | Kgs. Enghave – Gl. Sydhavn | +2 714 | 4 | Valby – Valby Sydvest | −1 501 |
| 5 | Christianshavn – Holmen og Refshaleøen | +1 930 | 5 | Vanløse – Jernbane Allé Kvarter | −1 497 |

**This is the single most useful thing the layer says, and it is invisible at municipal level.** The
city's 20–34 population falls 3.1 % overall, but the projection moves roughly 20 000 young adults from
the existing 20–34 heartlands — Nordvest, inner Nørrebro — into the five development sites. DST's map
can only show København as one −6.8 % polygon.

### Validation — check 9

Five parts. The first three are identities inside KK's own run and **fail** the script; the last two
are cross-source comparisons and are **information**, because a difference there is a real difference
between two published runs rather than a bug.

1. **coverage** — 67 kvarterer (+1 bucket) × 15 years, 0 missing.
2. **additivity** — Σ kvarterer and Σ lokaludvalg against the city total, per year. **Worst 5 persons
   (2038) and 3 persons (2028) out of ~720 000.** KK rounds every published cell independently, so a
   sum of 68 of them drifts by a few people and the drift grows with the number of cells; the
   tolerances (`TOL_CITY = 10`, `TOL_BYDEL = 5`) sit just above the observed maxima and far below the
   smallest kvarter (Metropolzonen, 2 882 people), so rounding passes but a dropped area cannot hide.
3. **additivity by bydel** — Σ the kvarterer of each bydel against that bydel's own value: **11/11
   within ±2**. This is also what proves the `2LLxx` → `20LL` → bydel mapping, since a wrong parent
   would move people between bydele and show up here.
4. **base year vs observed** — `KKFR` 2026 against the newest `KKBEF1` actual, per kvarter, five
   largest deviations. Worst **−6.6 % (Metropolzonen, 2 882 people)**, then −2.9 %, +2.3 %, −1.9 %,
   −1.7 %; 67 of 67 matched. The projection's base is 1 January 2026 and the observation is 2026K3,
   so part of every gap is real change since then rather than projection error — and the largest gaps
   are in the smallest kvarterer, as they should be.
5. **🚫 KK vs DST** — the city total against DST's kommune 101, per year, the splicing rule made
   numeric. The two runs start 42 people apart and end **16 130 apart (+2.27 %)**:

| year | KK `KKFR2026` (`1000`) | DST `FRKM126` (`101`) | diff | |
|---|---:|---:|---:|---:|
| 2026 | 671 672 | 671 714 | −42 | −0.01 % |
| 2027 | 677 721 | 678 375 | −654 | −0.10 % |
| 2028 | 679 539 | 675 921 | +3 618 | +0.54 % |
| 2029 | 682 710 | 680 560 | +2 150 | +0.32 % |
| 2030 | 688 084 | 684 972 | +3 112 | +0.45 % |
| 2031 | 693 344 | 689 101 | +4 243 | +0.62 % |
| 2032 | 698 496 | 692 862 | +5 634 | +0.81 % |
| 2033 | 703 600 | 696 199 | +7 401 | +1.06 % |
| 2034 | 708 130 | 699 061 | +9 069 | +1.30 % |
| 2035 | 712 080 | 701 509 | +10 571 | +1.51 % |
| 2036 | 715 536 | 703 660 | +11 876 | +1.69 % |
| 2037 | 718 642 | 705 619 | +13 023 | +1.85 % |
| 2038 | 721 558 | 707 492 | +14 066 | +1.99 % |
| 2039 | 724 396 | 709 293 | +15 103 | +2.13 % |
| 2040 | **727 141** | **711 011** | **+16 130** | **+2.27 %** |

Note the **crossover in 2028**: DST has Copenhagen *falling* from 2027 to 2028 (678 375 → 675 921)
while KK has it rising. That is not a rounding artefact — it is two genuinely different views of the
same city, and it is the clearest possible argument for never plotting them on one line.

### Phase B notes — the Copenhagen drill-down

1. **Registry.** These indicators are **not** in `config/indicators.json` yet. They belong under the
   `cph` key, which Phase A did not touch (its rule was `forecast` only), so Phase B adds them there
   together with a `calc: cph_forecast` branch in `scripts/build_cph.py`. `build_cph.py` already
   spreads bydel-level figures onto their kvarterer via `geo_level: "bydel"`; the forecast needs the
   opposite handling — it is natively kvarter-level, so it needs no spreading at all.
2. **The panel must name its source.** A Copenhagen kvarter view uses KK throughout and says so.
   The same panel must never show a DST figure beside a KK one without stating the gap (§4). The
   `+2.27 % by 2040` line from check 9 is the honest one-liner.
3. **`fc_20_34_rel` needs a different label here** — *vs København*, not *vs Denmark* — and must not
   reuse the municipal legend. `meta.relative_baseline` says which baseline a file used; render from
   it rather than from the indicator key.
4. **The caveat that has to reach the UI.** The city total is pure demography — KK excludes housing
   development plans from it *by design* — but the **split across kvarterer is driven by the city's
   unpublished boligprognose**, which KK itself calls *"behæftet med relativ stor usikkerhed"*
   (*"subject to relatively large uncertainty"*). Showing Nordhavn at +176 % without that sentence
   overstates what the number is. It is in `meta.caveat`, ready to render.
5. **`hist_net_dwell` has a Copenhagen counterpart** if it is wanted: KK's `KKBOL3` publishes
   dwellings per kvarter, which would make the same four operations possible at this level. Separate
   build, same rule, not in this pass.
6. **Read §9 before rendering any of this.** It backtests these forecasts against eight superseded
   vintages — the district split beats a no-detail baseline by 20–36 %, but it runs about +2 % hot at
   five years, and the two kvarterer §8 leads with (Vesterbro Syd, Nordhavn) are the two least
   reliable in the city. §9 adds exactly **one** thing to the UI: the per-area past-accuracy line
   (§9.7). Its other output, `fc_netmig`, is research and is not rendered anywhere.

---

## 9. Does the kvarter forecast work? — the backtest and the build-out signal

**Build:** `scripts/build_cph_backtest.py`, `scripts/build_cph_forecast.py`
**Output:** `data/processed/cph_backtest.json`, `fc_netmig*` in `data/processed/cph_forecast.json`
**Check:** `scripts/validate_forecast.py` checks 9f and 10 · **Audit:** §3 part b

§8 ends on a warning: a kvarter number is the city's unpublished housing programme in disguise, and
showing Nordhavn at +176 % without saying so overstates what the number is. This section replaces
the warning with two measurements — **how well those forecasts have actually done**, and **what is
driving them**.

Of the two, only the first reaches the UI, as a single line on Copenhagen area pages (§9.7). The
second, `fc_netmig`, is research: §9.5 shows it reversing sign on the city's two biggest development
sites, which is disqualifying for a map however clean its provenance.

---

### 9.1 🔎 The superseded vintages are unlisted, but they are still served

`GET /v1/s30/tables` returns `KKFR2026` and nothing else. That is what
`docs/FORECAST_SOURCES.md` §2.1 recorded — *"last year's `KKFR2025` is gone from the catalogue"* —
and it is true of **the listing**. It is not true of the API:

```
GET /v1/s30/tableinfo/KKFR2021   →  200, "Befolkningsfremskrivning 2021", updated 2021-03-26
GET /v1/s30/tables               →  KKFR2026 only
```

`scripts/build_cph_backtest.py` therefore **probes the ids directly** over a window of years instead
of reading the catalogue, and records in `meta.vintages_served` which ones answered. Today that is
**eight vintages, 2019 through 2026**; `KKFR2018` and earlier return `400`.

All eight share one schema and one **93-code `OMRKK` list, identical to `KKBEF1`'s**, so a kvarter
can be followed across vintages by its code with no crosswalk — the same property §8 relies on.

> **Operational note.** This is a windfall and it may not last: KK is under no obligation to keep
> serving an unlisted table, and the catalogue says they are not supporting it. If a future run finds
> fewer vintages, `meta.vintages_served` will say so and the backtest will simply narrow. Do not
> build anything that *requires* a five-year horizon to be scoreable.

### 9.2 Method

| | |
|---|---|
| forecast | `KKFR<V>`(k, V+h) — the vintage-V projection for horizon h |
| actual | `KKBEF1`(k, (V+h)K1) — the observed population at the same 1 January |
| baseline | `KKFR<V>`(k, V) × `KKFR<V>`(city, V+h) / `KKFR<V>`(city, V) |

**The baseline is the whole point.** It is the *same* city-level projection — the demographic part KK
would produce anyway, with housing plans explicitly excluded (`FORECAST_SOURCES.md` §2.6) — applied
**pro rata to every kvarter with no district detail at all**. Beating it is what the
boligprognose-driven split has to do to be worth anything. It uses only information available at
1 January V, and it starts from the vintage's own base year rather than from `KKBEF1`, so the
comparison isolates **the split** and not the base.

**Horizon 0 measures the base separately.** Each vintage's own base year is not exactly `KKBEF1`'s
observed population at that date — KK projects from a cleaned CPR extract, and `KKBEF1` has since
been revised. Scoring h=0 puts a number on that gap so it is not silently charged to the forecast:
**kvarter MAPE 0.15 %, 10 persons on average**. Small, and worth knowing rather than assuming.

Metrics, all on published cells: `MAPE` = mean |F−A|/A × 100, `bias` = mean (F−A)/A × 100,
`medAPE` = median |F−A|/A × 100, `MAE` = mean |F−A| in persons, and
`skill` = (1 − MAPE_forecast / MAPE_baseline) × 100, positive when the split beats pro rata.
Every vintage's own cells are re-checked against §8's ±10 / ±5 additivity tolerances before use —
all eight pass.

**Which (vintage, horizon) pairs are scoreable** is set by `KKBEF1` reaching 2026K1:

| vintage | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| horizons scored | 0,1,3,5 | 0,1,3,5 | 0,1,3,5 | 0,1,3 | 0,1,3 | 0,1 | 0,1 |

That gives **2 046 forecast–actual pairs**: 469 kvarter-observations at h=1, 335 at h=3, 201 at h=5.

### 9.3 Results — the split earns its keep, and it over-forecasts

| level | h | n | MAPE | bias | medAPE | MAE | baseline MAPE | baseline bias | **skill** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 67 kvarterer | 0 | 469 | 0.15 % | −0.09 % | 0.00 % | 10 | 0.15 % | −0.09 % | — |
| 67 kvarterer | 1 | 469 | 1.96 % | +0.29 % | 1.36 % | 167 | 2.44 % | +0.03 % | **+19.7 %** |
| 67 kvarterer | 3 | 335 | 4.07 % | +1.01 % | 3.03 % | 361 | 6.14 % | +0.52 % | **+33.7 %** |
| 67 kvarterer | 5 | 201 | 6.22 % | +2.23 % | 4.41 % | 518 | 9.65 % | +1.53 % | **+35.5 %** |
| 10 bydele | 1 | 70 | 0.63 % | +0.29 % | 0.52 % | 413 | 1.22 % | +0.34 % | **+48.4 %** |
| 10 bydele | 3 | 50 | 1.40 % | +0.69 % | 1.10 % | 926 | 3.36 % | +1.07 % | **+58.3 %** |
| 10 bydele | 5 | 30 | 1.82 % | +1.41 % | 1.31 % | 1 286 | 5.62 % | +2.29 % | **+67.6 %** |
| city | 1 | 7 | 0.28 % | +0.18 % | 0.28 % | 1 845 | 0.28 % | +0.18 % | ±0 % |
| city | 3 | 5 | 0.54 % | +0.54 % | 0.11 % | 3 529 | 0.54 % | +0.54 % | ±0 % |
| city | 5 | 3 | 1.36 % | +1.36 % | 1.41 % | 9 033 | 1.36 % | +1.36 % | ±0 % |

Four things this says, in order of how much they should change what the UI does.

1. **The district split is real information.** It cuts kvarter error by **a fifth at one year and a
   third at five** against a baseline that has the same city total and no district detail. The
   boligprognose is doing work. §8's caveat stands — it is an unpublished construction schedule —
   but "unverifiable" and "worthless" are different claims, and the second one is now refuted.
2. **The city skill of exactly ±0 % is the control.** At city level the forecast *is* the baseline by
   construction, so any number other than zero would mean the baseline was implemented wrong. It is
   zero at all three horizons.
3. **🚩 The forecast runs hot, and increasingly so with horizon** — bias +0.29 % → +1.01 % → +2.23 %
   at kvarter level, +1.41 % for bydele and **+1.36 % for the city itself** at five years. Part of
   this is the city total (KK's 2020 and 2021 vintages projected through the pandemic, which
   suppressed migration into Copenhagen), and part is the split. Either way, **a KKFR number is more
   likely to be too high than too low**, and the UI should not present it as unbiased.
4. **Aggregation helps a lot.** Bydel MAPE at five years is 1.82 % against the kvarter's 6.22 %.
   A bydel figure is roughly three times as reliable as a kvarter figure. Where a panel can show
   either, the bydel one carries far more weight.

**Worst and best kvarterer**, all horizons ≥ 1 pooled (`bt_mape`, `bt_baseline_mape`):

| | kvarter | MAPE | baseline | bias | | kvarter | MAPE | baseline |
|---|---|---:|---:|---:|---|---|---:|---:|
| 1 | Vesterbro – **Syd** | 15.12 % | 28.78 % | +6.81 % | 1 | Østerbro – Nord/Komponistkvarteret | 1.08 % | 4.06 % |
| 2 | Brønshøj-Husum – Bellahøj | 10.65 % | 14.30 % | +10.36 % | 2 | Amager Vest – Amagerbro Vest | 1.11 % | 3.43 % |
| 3 | Bispebjerg – **Utterslev** | 9.02 % | 4.26 % | +9.02 % | 3 | Amager Øst – Amagerbro Øst | 1.20 % | 3.44 % |
| 4 | Amager Vest – Faste Batteri | 8.32 % | 8.67 % | +6.70 % | 4 | Vanløse – Jyllingevej Kvarter | 1.25 % | 3.53 % |
| 5 | Østerbro – **Nordhavn** | 8.17 % | 11.00 % | +7.23 % | 5 | … | | |
| 6 | Valby – **Vigerslev** | 8.06 % | 5.65 % | +8.06 % | | | | |
| 7 | Kgs. Enghave – Holmene | 7.34 % | 8.52 % | −7.10 % | | | | |
| 8 | Christianshavn – Holmen og Refshaleøen | 6.97 % | 1.54 % | −6.02 % | | | | |

**The two kvarterer §8 leads with are the two least reliable.** Vesterbro Syd — the +203 % headline —
has by far the worst record at 15.12 %, and Nordhavn is fifth at 8.17 %; both over-forecast. The
split still beats pro rata for both (28.78 % and 11.00 %), so the district detail is helping even
there — it is just helping from a much worse starting point, because a kvarter whose population is
scheduled to triple is genuinely hard.

**Three kvarterer where the split is *worse* than pro rata** — Utterslev (9.02 % vs 4.26 %),
Vigerslev (8.06 % vs 5.65 %) and Holmen og Refshaleøen (6.97 % vs 1.54 %). Those are the cases where
KK's housing programme said something would happen and it did not.

The skill comparison is the most useful thing in this table and it is **not** shown in the UI: it
cannot be read without the baseline being explained, and a number that needs a paragraph does not
belong on an area page. What is shown is the plain error at five years — §9.7.

---

### 9.4 The build-out signal — `fc_netmig` 🚫 *research only, not shown in the UI (§9.7)*

`KKFRBEDI` carries the **movement** side of the same run as `KKFR2026`: who is born, who dies, who
moves in and who moves out of each district, per year. Its Danish metadata, quoted in full:

> **`KKFRBEDI` — "Fremskrivning af befolkningens bevægelser efter distrikt, bevægelsesart, alder og
> tid"**
> *"Projection of the population's movements by district, type of movement, age and time."*
>
> `BEVÆGELSE` ("bevægelsesart" / *"type of movement"*):
> `01` **Levendefødte** *(live births)* · `02` **Døde** *(deaths)* · `03` **Fødselsoverskud**
> *(natural increase — literally "birth surplus")* · `04` **Tilflyttede** *(persons moved in —
> KK's English label: "Migration to district")* · `05` **Fraflyttede** *(persons moved out —
> "Migration from district")* · `06` **Nettotilflytning** *(net in-migration — "Netmigration")*
>
> Footnote: *"Kilde: Københavns Kommunes beregninger på baggrund af udtræk fra CPR"* —
> *"Source: Københavns Kommune's own calculations based on an extract from the CPR."*

So `fc_netmig` = Σ of the published `06 Nettotilflytning`. But **the label alone does not say what
"net move" counts**, and the answer matters enormously, so it was checked arithmetically rather than
read off:

> ### 🔑 At district level, a "move" includes moves between two Copenhagen districts
>
> In 2026 the 68 kvarter rows report **104 317 Tilflyttede** between them. The city's own total
> in-moves for the same year, from `KKFRBEV`, are **55 225** (36 348 from other Danish municipalities
> + 18 877 immigrated). The ~49 000 difference is **internal Copenhagen moves**, which appear once as
> an out-move in one kvarter and once as an in-move in another.
>
> That is also why **`OMRKK = 1000` does not exist in `KKFRBEDI`**: at city level the internal moves
> cancel and the concept changes, so KK publishes the city split in `KKFRBEV` instead, with different
> categories (`08 Nettotilflytning fra andre kommuner`, `09 Nettoindvandring`).

This is exactly the right quantity for a build-out signal. A kvarter that opens 2 000 new dwellings
fills them from the rest of Copenhagen as much as from outside it, and `06` captures both.

**The city figure is a sum, not a published cell.** `meta.netmig.city_is_a_sum` records this. Summing
net migration across districts is precisely what cancels the internal moves, so Σ kvarterer is the
correct city-level quantity — and it agrees with Σ lokaludvalg and Σ bydele to ≤ 8 persons over the
five-year window and ≤ 2 over the full one (check 9f, ±10 tolerance).

**Windows.** A movement year Y is the flow *during* Y, bridging the 1 January stocks of Y and Y+1.
`KKFRBEDI` runs 2026–2059 against `KKFR2026`'s 2026–2060 stocks, which lines up exactly. So

- `fc_netmig_5y` sums movement years **2026–2030** (the 2026 → 2031 stock window)
- `fc_netmig` sums movement years **2026–2039** (the 2026 → 2040 stock window)

The per-1 000 variants divide by the published 2026 population. **They are totals over the window,
not yearly rates** — divide by 5 or 14 for a rate.

#### The bydele

| code | bydel | `fc_netmig_5y` | / 1 000 | `fc_netmig` | / 1 000 | `fc_abs` |
|---|---|---:|---:|---:|---:|---:|
| `1010` | Amager Vest | +2 552 | +27.8 | −6 094 | −66.5 | +8 174 |
| `1004` | Vesterbro/Kongens Enghave | +101 | +1.2 | +491 | +5.8 | +18 644 |
| `1007` | Brønshøj-Husum | −357 | −7.9 | −2 226 | −49.4 | +1 242 |
| `1009` | Amager Øst | −621 | −9.7 | +3 566 | +55.8 | +13 050 |
| `1005` | Valby | −1 097 | −16.5 | −4 444 | −66.9 | +4 871 |
| `1002` | Østerbro | −1 198 | −14.6 | −573 | −7.0 | +11 289 |
| `1006` | Vanløse | −1 186 | −29.1 | −4 779 | −117.1 | −959 |
| `1001` | Indre By | −2 686 | −46.8 | −3 511 | −61.2 | +1 317 |
| `1008` | Bispebjerg | −3 222 | −57.8 | −9 802 | −175.9 | −2 311 |
| `1003` | Nørrebro | −3 734 | −46.7 | −12 769 | −159.8 | +558 |
| | **København i alt** | **−11 657** | **−17.4** | **−40 626** | **−60.5** | **+55 469** |

**Copenhagen grows on births, not migration.** The city's net migration is **−40 626 over
2026–2039** while its population rises +55 469. Every bydel but two is negative over the full window.
This is not a quirk of the projection: `KKFRBEV` has net inter-municipal migration at about
−6 100 a year throughout, partly offset by positive net immigration. On its own the figure reads as a
city in decline, which is not what the same run says about its population — one of several reasons
`fc_netmig` stays in this document and out of the UI (§9.7).

#### Kvarter rankings — `fc_netmig_per1000`, 2026–2039

| | largest net inflow | / 1 000 | persons | 5-yr / 1 000 | | largest net outflow | / 1 000 |
|---|---|---:|---:|---:|---|---|---:|
| 1 | Østerbro – **Nordhavn** | **+1 424.3** | +9 308 | +339.1 | 1 | Nørrebro – Mimersgade/Nørrebro St. | −247.3 |
| 2 | Christianshavn – Holmen og Refshaleøen | +943.8 | +3 328 | −100.7 | 2 | Vesterbro – Vest | −241.3 |
| 3 | Amager Øst – Amagerbro Øst | +349.2 | +8 208 | +10.5 | 3 | Østerbro – Rosenvænget | −239.8 |
| 4 | Kgs. Enghave – Gl. Sydhavn | +282.6 | +4 022 | +96.0 | 4 | Østerbro – Nord/Komponistkvarteret | −228.8 |
| 5 | Amager Vest – Ørestad City | +246.3 | +2 857 | +327.3 | 5 | Bispebjerg – Nordvest | −226.4 |
| 6 | Østerbro – Ny Ryvang | +223.6 | +735 | +140.9 | 6 | Nørrebro – Stefansgade/Nørrebroparken | −221.7 |
| 7 | Vesterbro – **Syd** | +173.4 | +825 | **+336.6** | 7 | Østerbro – Århusgade Syd | −218.6 |
| 8 | Brønshøj-Husum – Husum Nord | +140.7 | +1 258 | +68.7 | 8 | Amager Vest – Bryggen Syd | −209.8 |
| 9 | Vesterbro – Central | +90.0 | +2 091 | −29.7 | 9 | Bispebjerg – Utterslev | −203.3 |
| 10 | Amager Vest – Urbanplanen | +72.1 | +324 | +76.7 | 10 | Østerbro – Århusgade Nord | −197.8 |

✅ Nordhavn and Vesterbro Syd are where they were expected. **The 5-year column reorders the table
sharply** and should be shown beside the 14-year one: Vesterbro Syd is 7th over the full window but
**2nd on the near window** (+336.6), while Holmen og Refshaleøen is 2nd overall yet **negative
(−100.7) over the first five years** — its construction starts later. Amagerbro Øst is 3rd overall
on +10.5 in the near window for the same reason. A single horizon hides the schedule.

---

### 9.5 🚩 Five kvarterer where `fc_netmig` and the stock table disagree

Over a window, ΔP should equal natural increase + net migration. For 62 of 67 kvarterer, all 12
lokaludvalg, all 10 bydele and the city, it does. **For five kvarterer it does not**, and the failure
is not small:

| kvarter | `fc_abs` | `fc_netmig` | gap | bydel |
|---|---:|---:|---:|---|
| Amager Øst – Amagerbro Øst | +2 416 | **+8 208** | −10 465 | `1009` |
| Amager Øst – **Nordøstamager** | **+10 414** | **−1 053** | +10 095 | `1009` |
| Vesterbro – **Syd** | +9 660 | +825 | +7 633 | `1004` |
| Vesterbro – Central | −71 | +2 091 | −7 605 | `1004` |
| Amager Øst – Sundbyøster | +793 | −1 459 | +412 | `1009` |

They come in **adjacent pairs inside one bydel**, and they cancel there. What KK's district split is
doing is moving projected population between neighbouring kvarterer without booking it as a move —
almost certainly the boligprognose assigning a development across a kvarter boundary.

**The consequence is severe if ignored.** Nordøstamager's population grows by 10 414, the third
largest gain in the city, while its net migration reads **−1 053**. A panel that showed
`fc_netmig_per1000` on a choropleth would paint the city's fastest-building kvarter as an outflow
area, and the inflow would appear next door in Amagerbro Øst, whose population barely moves.

`fc_netmig_reconciles` is stored **per code** for exactly this reason, alongside `fc_netmig_gap` and
`fc_netmig_gap_per1000`. **This is also why `fc_netmig` is not shown anywhere** (§9.7): a signal that
reverses sign on the two biggest development sites in the city cannot be put on a choropleth, and
neither of the fixes — hide the five, or flag them — survives contact with a map legend. Check 9f
prints the five every run so the situation stays visible in the data even though the UI ignores it.

The threshold is `|gap| ≤ max(5 × window years, 1 % of P₂₀₂₆)` and it is **not delicate**: every gap
it passes is ≤ 26 persons and every gap it catches is ≥ 412. See §3 part b for why that makes it a
threshold rather than an assumption.

---

### 9.6 One further finding — `KKFRBEV`'s `07 Fødselsoverskud` does not reconcile

Not used by anything here, but recorded so the next person does not lose an afternoon to it.
At city level the population change reconciles exactly as

    ΔP = (01 Levendefødte − 02 Døde) + 08 Nettotilflytning fra andre kommuner + 09 Nettoindvandring

— to ≤ 4 persons in every year of the window. It does **not** reconcile using `07 Fødselsoverskud`,
which is published as 10 068 for 2026 where `01 − 02` is 10 078 − 3 526 = **6 552**, a difference of
3 516 that grows to 4 120 by 2039. Whatever `07` is, it is not births minus deaths, and the label
says it should be. **Use `01 − 02`.** `KKFRBEDI`'s own `03 Fødselsoverskud` is fine — it equals
`01 − 02` to ±1 — so this is specific to `KKFRBEV`.

---

### 9.7 Phase B notes — one line, and nothing else

Of everything in this section, **exactly one figure reaches the UI**. The rest is research: computed,
checked, documented, and never rendered. `validate_forecast.py --ui` prints the full inventory from
the same audit tables check 0 enforces, so the list cannot drift from what is allowed.

1. **Nothing here goes into `config/indicators.json`.** Same rule as §8: Copenhagen-only keys stay
   out of the registry in Phase A and are added under the `cph` key by Phase B. Check 0 part b
   asserts they have not leaked in, so this is enforced rather than hoped for.

2. ### 🚫 `fc_netmig` is research only — it is not shown anywhere
   Not on the map, not in a popup, not on an area page. `fc_netmig`, `fc_netmig_5y`, their per-1 000
   variants, `fc_netmig_gap`, `fc_netmig_gap_per1000` and `fc_netmig_reconciles` stay in
   `cph_forecast.json` and in this document, and nothing renders them.

   **Why, given it is hard data.** §0 permits it — every value is a published `KKFRBEDI` cell — but
   passing §0 is a floor, not a warrant. §9.5 is the reason: for five kvarterer the signal disagrees
   with the stock table badly enough to **reverse its sign**, and two of those are the city's biggest
   development sites. A figure that says Nordøstamager is losing people while its population grows by
   10 414 is worse than no figure, and the alternatives are both bad — suppress the five and the map
   has holes exactly where the story is, or show them flagged and the flag has to carry more weight
   than a map legend can. Keeping it in the file costs nothing and loses nothing, because §9.4 is
   where its value actually is: it explains *why* `fc_growth` looks the way it does, which is a
   sentence in this document, not a layer.

3. ### ✅ The past-accuracy line — the one thing that is shown
   **Where:** Copenhagen **kvarter and bydel area pages only**. Never on the map, never coloured,
   never a ranking, never a chip.

   **Text:**
   > Past accuracy: KK's 5-year forecasts for this area were off by **{`bt_mape_5y`} %** on average
   > (**{`bt_over_5y`}** of **{`bt_n_5y`}** vintages over-forecast).

   **Rule:** render only where `bt_line_eligible` is true, i.e. `bt_n_5y` ≥ 3. Below that show
   **nothing** — not a hedged figure, not "insufficient data". Today every area has exactly 3
   vintages at h=5 (2019, 2020, 2021), so all 78 qualify; that is a property of how far `KKBEF1`
   reaches and will change. Round `bt_mape_5y` to one decimal at render time; it is stored at two.

   **Everything else the backtest computes stays here.** `bt_mape`, `bt_bias`, `bt_medape`, `bt_mae`
   and `bt_baseline_mape` are research. In particular the skill-against-baseline comparison — the
   most interesting result in §9.3 — is *not* shown: it needs the baseline explained to mean
   anything, and a number that needs a paragraph does not belong on an area page.

   The line is worth its space because it is specific and it cuts both ways. Vesterbro Syd's is
   **33.53 %**, against the city's **1.36 %** — the reader sees that the +203 % headline sits on the
   least reliable forecast in Copenhagen, from the same source that produced the headline.

4. **Do not state the upward bias as a separate UI figure.** It is real (§9.3) but it is a second
   backtest number, and decision 3 allows one. The per-area line already carries it in the
   `{`bt_over_5y`} of {`bt_n_5y`}` clause, which is the same fact in a form that needs no footnote.

5. **Do not require the backtest to exist.** `cph_backtest.json` depends on KK continuing to serve
   unlisted tables (§9.1). Checks 9f and 10 skip rather than fail when a file is missing, and the UI
   must degrade the same way: no file, no line, no error.
