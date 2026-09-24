# v3.0 — final QA (P9)

A fresh-eyes pass over the finished build: the full gate, then every route screenshot at
**1440×900 · 1536×864 · 1366×768 · 390×844** read one by one, then a consistency audit of the
labels, units, number formats and sources across the map legend, the picker, the chart panel, the
Data tables, the test property and the export.

**Method.** `./overnight.sh gate P9` (build · 116 node tests · 42 python tests · 150/150
route×viewport smoke · 63/63 ACs · budgets), then
`tests/ui_smoke.py --full-page --viewports 1440x900,1536x864,1366x768,390x844` — 38 routes × 4
viewports × 2 shots. Desktop "full page" is the viewport: `#main` is the scroll container above
1024 px, so everything below the fold was read at 390, where the page scrolls natively and the same
content is stacked.

**Baseline before any P9 change: the gate was already green** — 63/63 ACs, 150/150 smoke, budgets
inside. Everything below is a *visual* or *consistency* defect that no test was looking for, which
is the point of the phase. The six that a test can state cheaply and unambiguously now carry one
(AC-Q1…AC-Q6); the rest were re-shot and read again.

Status: **no open item is marked `blocker`.**

---

## Fixed in P9

| # | Severity | Where | Defect | Fix | Pinned by |
|---|---|---|---|---|---|
| Q1 | high | `#map`, `#map/*`, `#property` mini map — every desktop width | The legend stack sat on top of Leaflet's attribution control. "© OpenStreetMap · Boundaries: DAGI, Klimadatastyrelsen" ran through the legend card's foot and was unreadable — and that credit is a licence condition, not decoration. | `#maplegs` `bottom:12px → 26px`, `.minimap .maplegs` `10px → 24px`. | AC-Q1 |
| Q2 | high | `#property`, ≥ ~1500 px | The header broke into two columns: the privacy sentence on the left, the title and its tags floated to the right of it, and the `Open on map / Copy link / …` row left alone underneath with a hole between them. `.tpnote` is capped at 760 px, so a 420 px basis on the identity block let the two share a flex line once the card was wide enough. Invisible at 1366 and 1440; ugly at 1536. | `.anhead .arid{flex:1 1 100%}` — the identity block always claims its own line, as §5.5′ draws it. | AC-Q2 |
| Q3 | medium | `#property` sections, every width | The last section heading read **"SOURCES &AMP; AS OF"** — the label was HTML-escaped twice. | the literal is `"Sources & as of"`; `tpSec()` escapes it once. | AC-Q5 (a general sweep for escaped entities on every MUST route) |
| Q4 | medium | Population-outlook tiles and every sheet tile row, ≤ 800 px | An odd last tile in a two-column row left a bare grid cell showing the separator colour through — the grey slab P6 logged and P8 fixed for `.tiles`, still there on `.tiles.wrap` (which is `auto-fit`, so it collapses an unused *track* but not a hole in the last row). | at ≤ 800 px `.tiles.wrap` is pinned to two columns and the fill rule applies to `.tiles` rather than `.tiles:not(.wrap)`. | AC-Q3 |
| Q5 | medium | test property › Area profile | An inherited figure was marked with a lone `°`, while the area page's *All figures* marks the same thing `.inh` + a `muni` tag. Spec §4.8 and §2.4 ("never a lone °") ask for one treatment; two tables of the same shape had two. | the profile row now carries `.inh` and the `muni` tag; the section's ⓘ hint and the Safety caption say `muni` instead of `°`. | AC-Q4 |
| Q6 | medium | Data › National series hero tiles, every desktop width | Two of the four labels take two lines, so the four figures in one row sat on two different baselines and the row read as broken. | `.hero-nat b{margin-top:auto}` — the figure is anchored to the foot of the tile. | (visual; re-shot) |
| Q7 | medium | chips row, ≤ 1024 px | `Rent (priv.)` broke onto two lines, so the row was ragged and the chip was taller than the 24 px of §2.2. The row scrolls sideways at that width, so there was never a reason to wrap. | `white-space:nowrap` on `.indchips .chip`. | AC-Q6 |
| Q8 | low | test property mini map, all widths | The note over the map spelled out all four rings (`rings 500 m · 1.000 m · 1.200 m, solid 1 km · København`) and wrapped onto two lines at every width. | the line now names the fill, the radius and the place; the ring scale is in its tooltip. | (visual) |
| Q9 | low | area page and test-property sections | The `▸` marker is a flex item of the summary row, so a long section name wrapped and left the triangle alone on line 1 ("QUARTERS (67) / POSTAL CODES (12)" at 390). | the marker is now `.arsec-t::before` — it belongs to the title and travels with it. | (visual) |
| Q10 | low | test property mini map, ≤ 900 px | Raising the legend stack for Q1 pushed it into the `+ − ⌖` control column, which clips the legend's title at phone width. | `@media (max-width:900px){.minimap .maplegs{left:52px}}`. | (visual) |
| Q11 | low | project sheet › *Outlook around this project*, and both school lists | A `<table>` with no intrinsic width shrinks to its container by wrapping cells, so at 390 a short categorical column was squeezed into ~20 px and wrapped one word per line: the project table's per-area verify link, and the school lists' `Private / free school` — three lines on every one of 135 rows. | the project table went into a `.scrollx` (it was the only one without), and below 1025 px — where §6 already says tables scroll inside their card — those two columns keep their width. The table then has to be wider than the card, which is when `.scrollx` does its job. | (visual) |
| Q12 | low | quarter pages and pins | The `^` that marks "published for the whole bydel, not this quarter" was a bare glyph on the headline tiles, with its explanation only in the tables further down. | it is an `<abbr title=…>` now, so it explains itself on hover and to a screen reader. | (visual) |
| Q13 | low | test property, radius labels | `tpRadLabel(1200)` rendered `1.2 km` — a `.` decimal under a da-DK UI (§2.4), where `.` reads as a thousands separator. | `1,2 km`. | (unit test territory; reachable from the mini-map tooltip) |
| Q14 | housekeeping | `src/style.css` | Two more contiguous v2.6 legacy blocks were dead: the `.tg / .tgi / .tgb / .tghead / .tgmore` toggle list and `.card.fold / .foldb`. Not one of those class names occurs in any `src/*.js` or in `src/index.html`. | deleted (≈ 2.1 KB). | the gate re-renders every route |

## Checked and correct — no change

- **Redirects.** Every old link in the route table was loaded at all four viewports and lands where
  it should: `#table/<level>`, `#pipeline` (with filters), `#market`, `#market?src=1`, `#sources`,
  `#data`, `#analysis` (with and without a pin), `#compare`, `#map?…&infra=1&public=1&services=1`,
  `#map?…&climate=1`, `#area/…?t=&g=`. They are `redirect=` routes in `tests/ui_smoke.py`, so this
  is checked on every run, not once.
- **Leftover v2.6 code paths.** `indsel`, `data-climate`, `vCompare`/`cmpRow`/`CMP`, `exportAll`,
  `exportCsv`, `exportPipelineCsv`, `lineChart`, `tileSpark`, `indQuick`/`data-indq`, `AR.group`,
  `AR.tab`, `SRC_PUB`, `data-anlay`, `data-xall`, "KEY FIGURES", the `Climate risk` toolbar button:
  **none of them exists.** (`.indsel` survives as a CSS class — it is the shared `<select>` skin,
  not the deleted `#indsel` element. "Climate risk" survives as the title of the climate *sheet*,
  which is what it is.)
- **Consistency of one indicator across surfaces.** Growth, Unemployment, Rented (BBR), Dwellings in
  the surge zone and Projected growth 2026→2040 were read on the map legend, the picker button, the
  chips row, the chart panel heading, Data › Areas' column header, the test property and the export
  header. Same label, same short form, same unit, same `#n of N` rank, same `as of`, same source
  string. The legend title is the registry's `short` and the picker button its `label` — by design
  (§4.5 "title (short label)").
- **Number rules.** One `fmt()` path; da-DK on screen and `.` decimals in CSV; `+0,4 pp` vs `-5,9 %`
  used correctly (change of a share vs change of a level); `–` for "the publisher has no figure" and
  `n/c` for "not computed at this level", never a `0`; `#n of N` everywhere including the climate
  sheet; projections purple with a `Projection` pill; `kDKK` labels match their magnitudes.
- **Empty states.** `#property` with no pin, `#area/kommune/101?ind=renters_bbr` (no history), the
  public-building sheet before its file lands — all render a `state-*` card, never a bare spinner.
- **Budgets.** `src/app.js` 446 KiB / 450 · `src/style.css` 136 KiB / 140.

## Open — not blockers

| # | Severity | Item | Why it is not fixed here |
|---|---|---|---|
| O1 | low | The **Housing stock (BBR)** indicator group draws a blue ramp (`hue [40,84,128]`) that is within a few points of the Climate group's blue (`--clim #2F4E8C`). Spec §2.1 says observed ramps are green and climate ramps blue. | The hue is per-indicator in `config/indicators.json`, which this run may not touch, and the two are never in one legend (one fill at a time), so the spec's actual rule — "never mixed in one legend" — holds. Changing 20 indicators' colours unreviewed on the last night is the worse risk. **Daytime data task.** |
| O2 | low | `#publist` still lists many identical `Anden bygning til undervisning og forskning` rows; §5.7 wants them grouped by (name, use code) with a count. | **SHOULD**, listed in §9's follow-up list, not MUST. The same grouping *is* implemented on the test property's "Public buildings within the ring" (P6). |
| O3 | low | Data › Sources shows `–` in **As of** for the `climate_index` row. | The source is a build artefact with no publisher as-of; `–` is the §2.4 spelling for that and **Fetched** is filled, which is what AC-D4 requires. |
| O4 | low | Data › Areas marks an inherited *cell* with `°` rather than a `muni` tag. | That table is one row per area and one column per indicator: only the cell is inherited, so a per-row tag cannot say it, and 60 inline tags would be unreadable. The `°` is explained in the caption under the table and in the map legend footer. The row-per-indicator tables (area page, test property) all use the tag. |
| O5 | low | At 390 the `PRICE/M²` tile breaks `70.156 DKK` between the number and its unit. | It is the unit that moves to the second line, the grid row stays even, and shrinking the tile figure would break the §2.3 type scale. |
| O6 | low | The project sheet's "Where it runs" legend covers roughly half of the map at 390. P8's `Legend ▾` pill folds `#maplegs` only. | Cosmetic, one route, and the fold control would have to be generalised to the sheets' own legend — more surface than a QA pass should change. |
| O7 | housekeeping | More v2.6 legacy CSS is provably dead: `.pcard`, `.vbanner`, `.chwrap`, `.tgdone`, `.tgstale`, `.worst`, `.cbox`, `.hcard`, `.act` (verified: none occurs in any `src/*.js` or `src/index.html`). ≈ 2 KB. | They are scattered across shared selector lists (`.worst,.pcard,.cbox,.act,.hcard{…}`), so removing them means rewriting selectors rather than deleting lines. There is budget headroom; a daytime pass can do it with a real review. |
| O8 | — | Two data tasks carried from earlier phases: the KK vs BBR "dwellings built 2010+" definition gap (surfaced with a caveat on the four quarters where it exceeds 15 pp), and the surge indicators' registry `desc`, which names the default horizon inside the sentence. | `data/` and `config/` are out of this run's reach by design. Both are surfaced in the UI rather than papered over. |
| O10 | low | A few indicators' `short` is a **rephrasing** rather than a shortening of their `label`: the map legend says *Dwellings at surge risk* where the picker and the info strip say *Dwellings in the surge zone*. §4.5 does ask the legend for the short label, so the mechanism is right — but a reader could read the two as two indicators. | Both strings come from `config/indicators.json`, which this run may not touch. Found on `surge_dw_pct`; every other indicator checked (growth, unemp, renters_bbr, fc_growth, price_m2, rent_private) has a `short` that is plainly the `label` abbreviated. **Daytime data task: one word each.** |
| O9 | — | AC-A1 is a DOM accessibility check, not axe-core (`src/vendor/axe.min.js` is not vendored and the run installs nothing). | P8's documented deviation. A daytime follow-up should run real axe-core on the four routes §7 names. |

## Deferred by the owner amendments (not defects)

- **Portfolio / multi-pin test property** (§5.5, AC-PR1/PR2/PR5/PR6) — amendment A2 moved it to
  LATER. The URL codec is already list-capable (`p=a;b` parses), so the owner's "paste several
  Google Maps links and they all appear on the map" needs a view that loops, not a format change.
- **Compare** — amendment A1 deleted it. `#compare?a=&b=` redirects to the **a** side's area page.
- **Pinned chips** (localStorage, the `+` chip of §4.2), `Columns ▾` on Data › Areas, the national
  series as a Charts entity (AC-C3), the sub-areas sparkline column, the `/` keyboard shortcut,
  full-screen on the main map card — all SHOULD in §9, queued not dropped.
- **Everything (.zip) export**, PNG export of the study row, a print stylesheet, saved portfolios —
  LATER in §9.
