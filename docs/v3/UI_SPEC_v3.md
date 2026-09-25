# Macro Dashboard — Denmark · UI SPECIFICATION v3.0

Source of truth for the overnight build. Written against v2.6 (screenshots in `scratchpad/v26/`, extra states `x_*.png`).
Repo: `/home/claude/am-dashboard-dk` — `src/app.js` (single-file SPA, hash routing, Leaflet), `src/style.css`.

Reading order for the coding agent: §0 (contract) → §1 (decisions) → §3 (IA & URLs) → §4 (shared components) → §5 (views) → §9 (priorities) → §10 (test-id contract). Acceptance criteria (AC) are written as observable Playwright checks; every AC refers to a `data-testid` from §10. Priorities: **MUST** = v3.0 overnight, **SHOULD** = next, **LATER** = backlog.

---

## ⚠ OWNER AMENDMENTS — these OVERRIDE anything below that conflicts (decided 2026-09-24)

- **A1 — Compare is removed entirely.** No nav item, no view, no "Compare" button anywhere (area page header, sheets). `#compare?a=<type>:<code>&b=…` redirects to `#area/<type>/<code>` of `a` (or `#map` if unparsable). Delete `vCompare`, `cmpRow`, `cmpZoneRow`, `CMP`, their handlers (`cmpa/cmpb`) and CSS. Every AC below that mentions Compare (AC-I1, AC-D2, AC-R1, AC-CM1–2, §5.6) is void or read without the compare route. The sidebar has **4** items: `Map · Data · Charts · Test property`.
- **A2 — Test property stays ONE property at a time.** The portfolio (§5.5 multi-pin, portfolio table, median/min/max, 30-pin cap, prop chips, AC-PR1/PR2/PR5/PR6) moves to **LATER**. The owner's later idea is "paste several Google Maps links and they all appear on the map" — do NOT build it now, but keep the URL codec list-capable. v3.0 Test property is specified in **§5.5′** (below, replaces §5.5).
- **A3 — Nav label** is `Test property` (not "Properties"). Route `#property?p=lat,lon[:label]` (one item). `#analysis?a=…&la=…` redirects to it.
- **A4 — Quality bar.** The owner wants this to be the best analytical UI he has seen. Consistency (one picker, one period control, one study row, one export schema, one number format) and zero visual glitches at 1366/1440/1536/390 matter more than extra features.

### 5.5′ Test property — `#property?p=55.6545,12.539[:label]`
Purpose: one address, read against every layer — the same study pattern as the area page, anchored on a pin.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Denmark › Test property                         [Export ▾][Copy link]  │
├────────────────────────────────────────────────────────────────────────┤
│ [Paste Google Maps link or lat, lon — replaces the current pin ][Go]   │
│ ⓘ processed in your browser · stored only in this page's URL           │
│ Test property  · København · 2450 København SV · Vesterbro syd · 55.65450, 12.53900 │
│ [Open on map] [Vesterbro syd ›] [2450 ›] [København ›] [OpenStreetMap ↗]│
│ ┌────────┬────────┬────────┬────────┬────────┐  ← tiles (clickable = select indicator)│
├────────────────────────────────────────────────────────────────────────┤
│ [Indicator ▾][Period]  chips…                 [Layers ▾] radius [1 km ▾]│
│ ┌──────────────────────────────────┬───────────────────────────────┐   │
│ │ CHART PANEL (same component as    │ + mini map, pin + rings    ⤢  │   │
│ │ area page) for the pin's finest   │ − DRAGGABLE, scroll-zoom       │   │
│ │ area: quarter > postal > muni,    │   fill = active indicator      │   │
│ │ level tag shown                   │   legend inside                │   │
│ └──────────────────────────────────┴───────────────────────────────┘   │
├────────────────────────────────────────────────────────────────────────┤
│ ▸ Population outlook   ▸ Area profile (all figures)   ▸ Safety          │
│ ▸ Infrastructure nearby  ▸ Public buildings within ring  ▸ Schools      │
│ ▸ Climate  ▸ Sources & as of                                           │
└────────────────────────────────────────────────────────────────────────┘
```
- Reuse the area page's study-row component (chart panel + minimap) with the pin's area as the entity; do not build a second implementation.
- Mini-map: `dragging:true`, scroll zoom, `⌖ re-centre` control, `⤢` full screen (§4.6); rings from the radius select; feature layers via `Layers ▾`; public/service markers use per-map panes/renderers (engineering brief §2.4 root cause 1).
- Sections are `<details>` (`data-testid=tp-sec-<name>`), state in `show=`; default open: `infra`. Existing card content (anIndTable, anOutlookCard, anInfraCard, anPubCard, anSchCard, anClimCard, anSources) moves into them unchanged apart from the shared number rules; public-building rows with identical (name, use code, distance ±20 m) are grouped with a count.
- Empty state (no `p=`): `state-empty` card with the input focused and one example link.
- Export ▾ adds `Test property (CSV)`: long schema (§4.9) + leading columns `property_label, lat, lon` — every figure for the pin's quarter/postal code/municipality (value_type inherited where so), then a second file `test_property_nearby_<date>.csv`: `kind(infra|public|school|service), name, type, status, distance_m, source, source_url`.
- The unified map search (§5.1) turns a pasted link/coords into `#property?p=…`.

AC-TP1 (MUST): `#analysis?a=55.65450,12.53900&la=Test` redirects to a hash starting `property?p=55.6545,12.539`.
AC-TP2 (MUST): on `#property?p=55.6545,12.539`, `[data-testid=study-row]` contains `chart-panel` and `minimap`; dragging the minimap 120 px changes its center (`window.__maps`); `minimap-full` works; zero pageerror.
AC-TP3 (MUST): clicking `[data-testid=tile-unemp]` sets `ind=unemp` and changes the minimap legend title.
AC-TP4 (MUST): `[data-export=property]` download header starts `property_label;lat;lon;level;code;` and every row has non-empty `source`.
AC-TP5 (MUST): pasting `https://www.google.com/maps/@55.6761,12.5683,15z` into `[data-testid=prop-input]` + Enter → hash `p=55.6761,12.5683` (replaces, one pin only).
AC-TP6 (MUST): no element with text "Compare" exists on any route; `#compare?a=kommune:101&b=kommune:751` lands on `#area/kommune/101`.

---

## 0. Contract with the hard principles

| Principle | How v3.0 honours it (and what is checked) |
|---|---|
| Hard data only, no scores/weights | Portfolio aggregates are median / min / max only. Compare has no winner. No "index" fields are ever introduced. The word *score* must not appear in the UI (AC-G1). |
| Every figure traceable | Every value surface (tile, table row, chart, tooltip, export row) carries `source`, `table_id`, `as_of`, and a verify link where one exists. Export files carry them as columns (§4.9). |
| Projections never look like actuals | Projection ramps are purple (`--proj`), lines dashed, tiles carry a `Projection` pill, table cells carry class `.proj`. Observed ramps are green, climate ramps are blue. Never mixed in one legend. |
| Zooming never changes selection | Unchanged; AC-M9 re-verifies it. |
| English UI, shareable state in URL | Every control below lists its URL key. Nothing user-set lives only in memory except pinned chips (localStorage, cosmetic). |
| Evolve, don't replace, the look | Same tokens (dark side panel, paper background, mono labels, green sequential ramps). New: consistent spacing scale, one picker, fewer toolbar rows. |

---

## 1. The ten design decisions (and pushbacks)

1. **Five destinations, not seven.** Sidebar = `Map · Data · Charts · Properties · Compare`. *Market* and *Pipeline* become tabs inside Data (`National series`, `Projects`). Sources becomes the fourth Data tab. Sheets (project, public building, school, climate) are not destinations; they are pages you arrive at from content.
2. **One IndicatorPicker everywhere.** A single component (`<ind-picker>` markup, §4.2) used on Map, Area page, Data › Areas, Charts, Properties and Compare. Button + popover with search, 12 groups, quick chips, level tags. Same keyboard model everywhere.
3. **Climate is an indicator family, not an overlay.** The *Climate risk* button is deleted. Choosing any Climate indicator (a) swaps the Period control from *Year* to *Horizon* (Today · 2070 · 2120), (b) turns on the *context layer* "storm-surge zones + official risk areas" for that horizon at zoom ≥ 10, shown as a dashed outline that lives in the legend with its own on/off. Choosing a non-Climate indicator removes both. Reason: the zones are the same source rendered geometrically; they only make sense next to the figure they explain. Infra / Public buildings / Services are *independent feature layers* (points and lines from other publishers) that make sense over any fill — that is why they are layers and Climate is not.
4. **Period is one control with three modes.** `Year ▾` (historical indicators), `Horizon` segmented (Climate), `Projection 2026→2040 · DST 2026` static badge (Outlook). The control renders whichever mode the active indicator needs; the URL key changes accordingly (`y=`, `hz=`, none).
5. **One `Layers ▾` menu replaces five toolbar buttons.** Map toolbar becomes one row of five controls plus one row of chips; at 1366 px the map starts ≤ 150 px below the top bar (was ~270).
6. **Area page = header → tiles → picker → chart | mini-map → three toggles.** The 12-tab "Key figures" block (48 cards) is removed. The chart panel is the single place to study any indicator: value, y/y, rank, vs median, history line with parent + median, or a peer distribution strip when there is no history, or the three-horizon bars for Climate.
7. **Inherited values are visibly inherited.** On postal-code and quarter pages, municipality-level values render dimmed with a `municipality figure` label in tiles, a `muni` tag in tables, and are listed under a "From the municipality" sub-heading in the picker. Never a lone `°`.
8. **Properties is a portfolio.** 1–30 pins in the URL, numbered on the map, one row each in a table driven by the picker, aggregate row = median · min · max only (labelled "no weighting"). Export includes sources. Mini-map drags.
9. **One Export model.** An `Export ▾` menu (Data page header and sidebar footer) with: *This view (CSV)*, *All area data*, *Projects*, *National series*, *Properties portfolio*, *Sources catalogue*, *Everything (zip of the above)* LATER. Every file has `source, table_id, source_url, as_of, period, period_type, value_type` columns. Unit bug (`kDKK` label on DKK values) fixed at the export boundary by validation.
10. **Responsive is a first-class layout, not a media-query patch.** ≤ 1024 px: sidebar becomes a 52 px top bar with a drawer; controls stack; chart and mini-map stack; tables scroll horizontally inside their card. At 1366×768 every primary view shows its main object (map / chart / table header) inside the first screen.

### Pushbacks on owner wishes
- **Wish 3, "remove Market".** Half-agree. The section goes, the series stay: they become Data › National series (table with sparklines) and are chartable in Charts (a "Denmark (national)" entity). Deleting them would lose the only national context (rates, CPI, HPI) an investment committee asks for. Cost: nil — the data is already loaded.
- **Wish 5, "outlook and table as toggles".** Agree on toggles, but default *All figures* to **collapsed** and *Population outlook* to **expanded on municipality pages** (it is the one chart that answers "is this place growing", and it is the only place projections are fully explained). Both states are in the URL (`show=`), so a presenter can share either.
- **Wish 7, horizon replaces year selector.** Agree — and the same replacement must apply to Outlook indicators (no year; a projection vintage badge). Otherwise the year select shows "2026 (latest)" next to a 2040 figure, which reads as an actual.
- **Wish 1, portfolio.** Agree; but no weighting, no "portfolio score", no averages of ranks. Median/min/max of the published figures only, and the count of properties sharing one municipality is shown so nobody reads three pins in Vesterbro as three independent observations.
- **Wish 8, "best in the world, overnight".** The MUST list (§9) is what a single agent can ship reliably in 10–15 h on a 358 KB file. Best-in-class comes from *consistency* (one picker, one period control, one export schema, one number-format ruleset) more than from feature count. SHOULD items are queued, not dropped.
- **Numbers in da-DK format under an English UI** (`70.156 DKK`, `+0,4 %`). Keep — the readers are Danish/Nordic and the figures match Statistikbanken screens they will cross-check. Exports use `.` decimal and no thousands separator (machine-readable), stated in the export dialog.

---

## 2. Design tokens, typography, number formatting, microcopy

### 2.1 Colour tokens (add to `:root`, keep existing ones)
```
--proj:#5B4A9C; --proj-2:#8A7CC2; --proj-bg:#F1EEF8;   /* projections: purple */
--clim:#2F4E8C; --clim-2:#6E86B8; --clim-bg:#EDF1F8;   /* climate: blue */
--inh:#8A8C81;  --inh-bg:#F3F3EF;                       /* inherited (municipality) values */
--focus:#1C6B5C; --focus-ring:0 0 0 3px rgba(28,107,92,.28);
--danger-bg:#FBEFEC; --warn-bg:#FBF4E6;
```
Ramps (5 bins, quantile, unchanged method): observed = green 5-step (existing), Outlook group = purple 5-step, Climate group = blue 5-step (existing). `no data` = `#D9DAD3`. Lower-is-better indicators keep "darkest = highest value" and say so in the legend footer (existing behaviour); do not invert ramps.

### 2.2 Spacing scale
`--s1:4px --s2:8px --s3:12px --s4:16px --s5:24px --s6:32px`. Card padding 16 px (desktop) / 12 px (mobile). Gap between cards 16 px. Page gutter 26 px desktop, 16 px mobile. Toolbar control height 32 px, chip height 24 px, tile height 84 px.

### 2.3 Typography
- Display (`--disp`): page title 26/1.2, card title 13 px mono uppercase tracking .12em (existing "KEY FIGURES" style — keep for card heads).
- Body (`--body`): 14/1.5. Table body 13 px. Captions/hints 11.5 px mono `--muted`.
- Numbers: always `--mono`, tabular-nums. Tile value 26 px, table value 13 px, legend 11 px.
- Line length for prose ≤ 78 ch (`max-width:78ch` on `.note`, `.cap`).

### 2.4 Number formatting rules (single `fmt()` path — every surface uses it)
| Case | Rule | Example |
|---|---|---|
| Locale | `da-DK` on screen; `.` decimal, no grouping in CSV | `70.156 DKK` / `70156` |
| Signed change | Always signed, unit after | `+0,4 pp`, `-5,9 %` |
| Percent vs pp | Change of a share = `pp`; change of a level = `%` | tile subline `+0,3 pp y/y` |
| Money | `kDKK / yr` only when the value is in thousands; the label must match the number (AC-X2) | `296 kDKK` |
| Per 1,000 | `90 / 1,000` in tables; tight `90` in legend bins | |
| Days / m² / cm | integer, unit after with thin space | `55 d`, `82 m²`, `157 cm` |
| Rank | `#n of N` everywhere; N = peers *with a value*; `title` attribute explains ("of 77 municipalities with a figure") | `#47 of 99` |
| Small base | Projected % change where base < 1,000 persons: persons first, percent second in muted, plus a `small base` tag | `+9.2k persons (+1,030 %) [small base]` |
| Projection | Value gets `.proj` class, purple, `Projection` pill in the row/tile; never in bold green/red | |
| Inherited | `.inh` class: colour `--inh`, italics off, label `municipality figure` (tile) / `muni` tag (table) | |
| Missing | `–` for "publisher has no figure"; `n/c` for "not computed at this level"; never `0` | |
| As-of | mono muted; `2025K3→2026K3` for windows; `2026M08` for months; `2025/2026` for school years | |

### 2.5 Microcopy tone
Short, declarative, lower-case after the first word, no exclamation marks, no marketing. Say what a thing *is*, then the source. Patterns:
- Empty: "No properties yet. Paste a Google Maps link or coordinates, or click the map."
- Loading: "Loading zones…" (never a spinner alone; always a noun).
- Error: "Could not load `climate/0101.json`. Reload, or open the source ↗." (name the file).
- Caveat: one sentence, mono, `--muted`, under the figure it caveats, never in a modal.
- Buttons: verb first — `Export ▾`, `Add property`, `Open København page ›`, `Show on map`, `Full screen ⤢`.

---

## 3. Information architecture & URL state

### 3.1 Navigation
```
MACRO DASHBOARD
 MARKET INTELLIGENCE
  Map          #map[/<kommune>[/postnr]]
  Data         #data/areas/<level> · #data/projects · #data/national · #data/sources
  Charts       #charts?…
 ANALYSIS
  Properties   #properties?p=…
  Compare      #compare?a=…&b=…
 ── footer ──
  Export ▾  (same menu as Data header)   · built 2026-09-24 · v3.0
```
Redirects (MUST): `#table/*` → `#data/areas/*`, `#pipeline` → `#data/projects`, `#market` → `#data/national`, `#sources` → `#data/sources`, `#analysis?…` → `#properties?p=…` (single property converted to one pin). Old links keep working.

### 3.2 Global query keys (shared by all views that show them)
| Key | Meaning | Values |
|---|---|---|
| `ind` | active indicator key | registry key |
| `y` | year (only when indicator has years and ≠ latest) | `2007…2026` |
| `hz` | climate horizon (only when `ind` ∈ Climate) | `today|2070|2120` |
| `lay` | feature layers on | comma list of `infra,public,services` |
| `pub`, `srv…` | layer sub-filters (existing keys kept) | |
| `zones` | climate context layer override | `0` to hide (default on when Climate ind) |
| `p` | properties | `lat,lon[:label]` items separated by `;` (≤ 30) |
| `show` | area-page sections open | comma list of `outlook,figures,sub` |
| `focus` | focused project id on map | |

Rule: a key is written only when its value differs from the default (keeps links short). `hashFor()` becomes the only serialiser; `parseHash()` the only parser; both cover the new keys (AC-U1).

---

## 4. Shared components

### 4.1 App shell
Desktop ≥ 1025 px: grid `240px 1fr` (was 268; 240 recovers 28 px for 1366 laptops). Sidebar: brand, two nav groups, footer with `Export ▾` and build/version line. Top bar (sticky): breadcrumb + page title + page-level actions on the right.

≤ 1024 px (tablet & mobile): grid becomes one column. Sidebar → 52 px top bar: `☰  MACRO DASHBOARD          [view title]`. `☰` opens a drawer (left, 280 px, scrim, Esc closes, focus trapped). The breadcrumb bar sits under it. `body{overflow:hidden}` is removed on mobile so the page scrolls natively.

```
DESKTOP                                   MOBILE 390
┌─────────┬──────────────────────────┐    ┌──────────────────────┐
│ brand   │ Denmark › Map            │    │ ☰ MACRO DASHBOARD    │
│ Map     │──────────────────────────│    ├──────────────────────┤
│ Data    │                          │    │ Denmark › Map        │
│ Charts  │      content             │    ├──────────────────────┤
│ Props   │                          │    │ [Search…         ▾]  │
│ Compare │                          │    │ [Indicator ▾][Yr▾][⋯]│
│         │                          │    │ chips ————————→      │
│ Export▾ │                          │    │ ┌──────────────────┐ │
│ v3.0    │                          │    │ │ map 60vh         │ │
└─────────┴──────────────────────────┘    │ └──────────────────┘ │
                                          └──────────────────────┘
```
AC-S1 (MUST): at 390×844, `[data-testid=sidebar]` is not visible, `[data-testid=topbar-mobile]` is visible, `document.body.scrollWidth <= 390`, and `[data-testid=map]` bounding box has width ≥ 350 and is within the viewport horizontally.
AC-S2 (MUST): clicking `[data-testid=nav-toggle]` shows `[data-testid=nav-drawer]`; pressing Escape hides it; focus returns to the toggle.
AC-S3 (MUST): at 1366×768 on `#map`, `[data-testid=map]` top ≤ 200 px and height ≥ 480 px.

### 4.2 IndicatorPicker (`data-testid=ind-picker`)
One component, one markup, one behaviour. Renders in the toolbar of Map, Area page, Data › Areas, Charts, Properties, Compare.

```
[ Population growth · % / yr                              ▾ ]   ← button, shows label · unit, level tag when not native
 chips:  (Growth) (Price/m²) (Rent) (Unemp.) (Rented) (Supply) (Crime) (Outlook 2040) (Surge dwellings) (+ pin…)
```
Popover (opens below the button, width 420 px desktop / full width mobile, max-height 70vh, scroll inside):
```
┌──────────────────────────────────────────────┐
│ 🔍 Search indicators…                    Esc │
│──────────────────────────────────────────────│
│ PINNED   Growth · Price/m² · Unemp. · …      │
│──────────────────────────────────────────────│
│ DEMOGRAPHICS                                 │
│   ● Population growth        % / yr    2016– │
│     Young adults 20–34       % of pop  2016– │
│ INCOME & JOBS                                │
│     Disposable income, avg   kDKK/yr   muni  │
│ …                                            │
│ OUTLOOK                     [Projection]     │
│     Projected growth 2026→2040   %           │
│ CLIMATE                     [Horizon]        │
│     Dwellings in the surge zone  % · ↓ lower │
│ FROM THE MUNICIPALITY (postal-code pages)    │
│     Unemployment rate            % · muni    │
└──────────────────────────────────────────────┘
```
Rules:
- Groups in `GROUP_ORDER`; each row = label, unit, `↓ lower is better` when `direction=lower_better`, and a right-aligned availability tag: `2016–` (history span), `muni` (inherited on this page), `snapshot` (single as-of, e.g. BBR).
- Group headers for *Outlook* and *Climate* carry a `Projection` / `Horizon` pill so the user knows the period control will change.
- Search filters across label, short, group, unit; ↑/↓ moves, Enter selects, Esc closes; typing `/` anywhere on a page with a picker focuses its search (SHOULD).
- Chips row: the first 8 = `QUICK_KEYS` ∩ available at this level (existing logic) — the active one is filled. A `+` chip at the end pins the current indicator (localStorage `pins`, max 12, SHOULD). Pinned chips get a small `×` on hover.
- Selecting an indicator updates `ind=` and re-renders only the dependent parts (map fill/legend, chart panel, table column highlight) — no full page rebuild on the area page (keeps scroll position, AC-P4).
- The button shows a level tag when the value shown is not native to the page level: `Unemployment rate · % · municipality`.
- On Compare the picker is multi-select with checkboxes (SHOULD); MUST is the single-select used only for "chart this row".

AC-I1 (MUST): on `#map`, `#area/kommune/101`, `#data/areas/kommune`, `#charts`, `#properties`, `#compare` the element `[data-testid=ind-picker]` exists exactly once and contains `[data-testid=ind-picker-btn]`.
AC-I2 (MUST): clicking the button opens `[data-testid=ind-picker-pop]` containing `[data-testid=ind-search]` (focused) and ≥ 12 `[data-group]` headers on `#map`.
AC-I3 (MUST): typing `surge` in the search leaves exactly the rows whose text contains "surge" (case-insensitive) visible; Enter selects the first and the URL contains `ind=surge_dw_pct` (or the first match).
AC-I4 (MUST): `[data-testid=ind-chips] .chip.on` has text matching the picker button label's short form.
AC-I5 (MUST): on `#area/postnr/2450`, rows for kommune-level indicators are inside `[data-group="From the municipality"]` and carry `.tag-muni`.
AC-I6 (SHOULD): Escape closes the popover and returns focus to the button; ↓ ↓ Enter selects the second visible row.

### 4.3 PeriodControl (`data-testid=period`)
Renders one of three modes from the active indicator:
- `mode=year`: `<select data-testid=period-year>` with years from `map_from` to latest, label `2026 (latest)`.
- `mode=horizon`: segmented `[Today][2070][2120]` (`data-testid=period-hz`, buttons `data-hz=today|2070|2120`), caption under it: "Today — zones: Kystdirektoratet 2020 · figures: Klimaatlas 1981–2010 reference period".
- `mode=projection`: static badge `Projection 2026→2040 · DST 2026 · FRKM126` (`data-testid=period-proj`), no control.
Switching indicator families resets the URL keys (`y` removed when leaving year mode, `hz` removed when leaving Climate).

AC-T1 (MUST): `#map?ind=growth` shows `period-year` and not `period-hz`; `#map?ind=surge_dw_pct` shows `period-hz` and not `period-year`; `#map?ind=fc_growth` shows `period-proj` only.
AC-T2 (MUST): clicking `[data-hz=2070]` sets `hz=2070` in the hash and the legend title footer contains "2070".

### 4.4 LayersMenu (`data-testid=layers`)
One button `Layers ▾` (shows a count badge when any layer is on: `Layers · 2`). Popover:
```
FEATURE LAYERS
 ☐ Infra projects        50 projects · Fingerplan, Anlægsstatus
 ☐ Public buildings      BBR · 19 municipalities        [Education ✓][Daycare ✓][Health ✓][Culture ✓]  existing/open
 ☐ Services              OSM & Rejseplanen             [Groceries][Food][Pharmacy][Transport ▸ rail·bus]
CONTEXT
 ☑ Storm-surge zones (Today)   shown because a Climate indicator is active   [hide]
 ☐ Test-property radius       500 m · 1 km · 2 km · 5 km  (only when properties exist)
```
- The sub-filters that today live inside each floating legend card move here; the floating cards on the map become pure legends (§4.5), 30 % smaller.
- The Context section is informational: the zones row is present only when a Climate indicator is active; ticking it off writes `zones=0`.
- Menu closes on Esc / outside click; state is written to `lay=`.

AC-L1 (MUST): on `#map` there is no button with text "Climate risk"; `[data-testid=layers-btn]` exists; the toolbar `[data-testid=map-toolbar]` contains ≤ 6 direct children in its first row (`[data-row=1]`).
AC-L2 (MUST): opening the menu and ticking `[data-layer=infra]` adds `lay=infra` to the hash and `[data-testid=legend-infra]` becomes visible.
AC-L3 (MUST): `#map?ind=surge_dw_pct` → `[data-testid=legend-zones]` visible and the menu shows `[data-layer=zones]` checked; `#map?ind=growth` → neither exists.

### 4.5 Legend (`data-testid=legend`)
Bottom-right stack, max 2 cards wide, 16 px from edges, each card ≤ 220 px wide:
1. **Indicator legend** (always): title (short label), unit, 5 bins with values, `no data`, footer `municipalities · zoom in for postal codes` (existing), plus for lower-is-better: `↓ lower is better · darkest = highest`.
2. **Zones legend** (Climate): dashed swatch `Storm-surge zone <horizon>`, dotted `Official risk area`, hint `zoom in to 10 to see the zones`.
3. **Feature-layer legends** (one per active layer): colour keys only — no filter buttons (moved to Layers menu), collapsible with `–`.
Legends must never overlap each other (flex column with gap) and the stack must not exceed 60 % of the map height; when it would, the oldest layer legend collapses to its title.

AC-LG1 (MUST): with `lay=infra,public,services` and `ind=surge_dw_pct`, all `[data-testid^=legend]` bounding boxes are inside `[data-testid=map]` and pairwise non-overlapping.

### 4.6 MiniMap (`data-testid=minimap`)
Used on Area page, Properties, Compare (SHOULD), sheets. Leaflet with `dragging:true`, scroll-wheel zoom on, `zoomSnap:.5`. Controls: `+ −` top-left, `⤢` top-right (`data-testid=minimap-full`) which toggles a fixed full-screen overlay (`position:fixed; inset:0; z-index:100`) with `✕`/Esc to close and `map.invalidateSize()` after each transition. Fill = active indicator ramp at the page's level; selected area has a 2 px `--ink` outline; clicking a neighbour navigates to its page (existing). Legend card inside (same component as §4.5, indicator only).
Teardown: every view that creates a Leaflet map registers it in `LF.maps[]`; `render()` calls `map.remove()` on each before replacing `#main` innerHTML (fixes `appendChild / intersects / _leaflet_pos` errors).

AC-MM1 (MUST): on `#area/kommune/101` and `#properties?p=55.6545,12.539`, dragging `[data-testid=minimap] .leaflet-container` by 120 px changes `map.getCenter()` (expose `window.__maps` with current Leaflet instances for tests).
AC-MM2 (MUST): clicking `[data-testid=minimap-full]` sets `[data-testid=minimap]` to `.is-full` with bounding box ≥ 90 % of the viewport; Escape restores it.
AC-MM3 (MUST): navigating `#map → #area/kommune/101 → #properties → #map` produces zero `pageerror` events.

### 4.7 HeadlineTiles (`data-testid=tiles`)
Five tiles (existing `HL_KEYS`), 84 px tall, each: mono label, big value, subline `Δ y/y · #n of N`. New: clicking a tile selects that indicator in the picker (tile gets `.on`); inherited tiles get `.inh` + `municipality figure` label instead of the rank; projection tiles get a `Projection` pill. Tiles wrap 5 → 3+2 at ≤ 1250 px, 2 columns at ≤ 800 px.

AC-H1 (MUST): on `#area/postnr/2450`, the tiles for `rent_private`, `unemp`, `renters` have class `.inh` and contain text "municipality figure"; the tile for `growth` does not.
AC-H2 (MUST): clicking `[data-testid=tile-unemp]` sets `ind=unemp` in the hash and `[data-testid=ind-picker-btn]` text starts with "Unemployment".

### 4.8 Data tables (all views)
- Sticky header row; first column sticky on horizontal scroll; row hover; sortable columns with `aria-sort`.
- Column set for indicator tables: `Indicator · Value · Parent · Median · Rank · Δ since first year · As of · Source` (source = table id, `title` = publisher, verify link on hover).
- Inherited rows `.inh` + `muni` tag; projection rows `.proj` + pill; climate rows show the active horizon in the header.
- Row click = select in picker (highlight + chart); `↗` = open in Charts.
- Number cells right-aligned, mono, tabular.

### 4.9 Export model (`data-testid=export-menu`)
Trigger: `Export ▾` in the sidebar footer and in the Data page header. Menu items (each downloads immediately; a one-line status toast "areas_long.csv · 68,771 rows"):

| Item | File | Rows | Notes |
|---|---|---|---|
| This view (CSV) | `<view>_<date>.csv` | what is on screen (wide) | Data › Areas: current level & columns; Properties: portfolio table; Compare: the two columns |
| All area data | `areas_long_<date>.csv` | long format, 3 levels | see schema |
| Projects | `projects_<date>.csv` | one row per project | own schema, never mixed into indicator columns |
| National series | `national_series_<date>.csv` | long format | `period_type` month/quarter |
| Properties portfolio | `properties_<date>.csv` | rows = property × indicator | includes `property_id, label, lat, lon, kommune, postnr, kvarter, distance-based counts` |
| Sources catalogue | `sources_<date>.csv` | one row per source | `key,label,publisher,tables,as_of,fetched,url,licence,used_for` |
| Everything (.zip) | LATER | | |

**Long schema (areas, national, properties):**
`level, code, name, parent_code, parent_name, region, population, indicator, label, unit, period, period_type, value, value_type, inherited_from, direction, source, table_id, source_url, as_of, fetched, licence`
- `period_type` ∈ `year | quarter | month | school_year | window | snapshot | horizon | projection`; `period` is the raw label (`2024`, `2024K3`, `2024M08`, `2025/2026`, `2025K3→2026K3`, `2026-09-15`, `2070`, `2026→2040`).
- `value_type` ∈ `actual | projection | inherited | derived` (`derived` = plain arithmetic such as per-1,000 rates; the arithmetic is named in `label`).
- `inherited_from` = municipality code when `value_type=inherited`, else empty.
- Units: the exporter asserts that `unit` and value magnitude agree for `kdkk` (value < 10,000) — on failure it converts and logs; the on-screen kDKK bug is fixed at source too (AC-X2).
- CSV: UTF-8 with BOM, `;` separator (Danish Excel), `.` decimal, no thousands grouping, header row first, one comment-free file.

**Projects schema:** `id, name, type, status, status_note, opening, opening_original, budget_mdkk, agency, municipalities, postal_codes, quarters, geometry_kind (line|point|area|schematic), length_km, stations, source_doc, source_url, updated`.

AC-X1 (MUST): clicking `[data-testid=export-btn]` opens `[data-testid=export-menu]` with ≥ 6 `[data-export]` items; triggering `[data-export=areas]` produces a download whose first line equals the long-schema header above.
AC-X2 (MUST): in `areas_long`, every row with `unit` containing `kDKK` has `|value| < 10000`; every row with `indicator=income` on level `municipality` has `value_type=actual`.
AC-X3 (MUST): `projects` file has no `indicator` column; `areas_long` has no rows with `level=project` or `level=macro`.
AC-X4 (MUST): every `areas_long` row has non-empty `source` and `as_of`; every row on `postal_code`/`copenhagen_quarter` level whose indicator is municipality-level has `value_type=inherited` and `inherited_from` set.

### 4.10 Empty / loading / error states
Component `<state-card kind="empty|loading|error">`: icon-less, mono caption + one action. Used for: no properties, no history for an indicator, layer file failed, zones not yet loaded, no peers with a value, search with zero hits ("No area matches 'xyz' — try a postal code or municipality"). Loading never blocks the rest of the page; skeleton = grey bar 3 lines in the card, max 1 s before text appears.

AC-E1 (MUST): `#properties` with no `p=` shows `[data-testid=state-empty]` with a text input focused.
AC-E2 (MUST): `#area/kommune/101?ind=renters_bbr` shows `[data-testid=chart-panel] [data-testid=state-nohistory]` and a distribution strip `[data-testid=dist-strip]`.

---

## 5. Views

### 5.1 Map — `#map[/<kommune>[/postnr]]`
Purpose: choose an indicator, see it across Denmark or inside one municipality, drill by click.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Denmark › Map   municipalities and postal codes          [⤢ Full screen]│
├────────────────────────────────────────────────────────────────────────┤
│ [🔍 Search area, postal code, link or coords ▾] [Layers ▾] [Indicator ▾][2026 ▾]│  row 1
│ (Growth)(Price/m²)(Rent)(Unemp.)(Rented)(Supply)(Crime)(Outlook)(Surge)(+)│  row 2
│ Population growth · postal-code level · % / yr · as of 2025K3→2026K3  ⓘ │  strip
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ +                                                                  │ │
│ │ −                              map                                  │ │
│ │                                                       ┌──────────┐ │ │
│ │                                                       │ legend   │ │ │
│ │                                                       └──────────┘ │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```
- Search combobox is unified: municipality / postal code / quarter names and codes **and** Google Maps links or `lat, lon` (detected by regex). A coordinate result reads "Add as property → Properties" and one click goes to `#properties?p=lat,lon`. The privacy sentence moves to a `?` tooltip on the search box and to the Properties page (once, not on every map).
- `Copenhagen` / `Denmark` quick jumps go into the search dropdown's top ("Jump to: Denmark · Copenhagen") and out of the toolbar.
- Drilled state (`#map/101`): the toolbar's row 1 gains a segmented `[Quarters (67)][Postal codes]` for Copenhagen only, and `[Areas][Buildings (14 575)]` when micro data exists — these replace the search box's left half, keeping one row. The municipality card (existing, with upcoming/public/climate facts) stays but becomes collapsible (`–`) and remembers state in `localStorage`.
- Full screen button moves to the top bar right (page-level action).
- Info strip (existing black-left-border line) stays: label, level tag, unit, as-of, `ⓘ details` opens the indicator definition popover (definition, source, table id, verify link, direction).
- Clicking an area: existing behaviour (popup with headline figures + "Open page ›"). Zooming never selects (AC-M9).

URL: `ind, y|hz, lay, pub…, srv…, zones, focus, p` (properties pins shown as numbered markers when present — context, not selection).

AC-M1 (MUST): `#map` toolbar `[data-testid=map-toolbar] [data-row=1]` children: `search, layers-btn, ind-picker, period` in that order; no element with text "Paste Google Maps link", "Infra projects", "Public buildings", "Services", "Climate risk" outside the Layers popover.
AC-M2 (MUST): typing `2450` in `[data-testid=search]` and pressing Enter navigates to `#area/postnr/2450` (existing behaviour kept).
AC-M3 (MUST): typing `55.6545, 12.539` shows a result `[data-testid=search-coord]` whose click navigates to `#properties?p=55.6545,12.539`.
AC-M4 (MUST): `#map?ind=fc_growth` legend swatches have purple hues (computed `background-color` where `b > r` and `b > g` for the darkest bin) and the info strip contains "Projection".
AC-M9 (MUST): on `#map/101`, `window.__maps[0].setZoom(12)` then `setZoom(9)` leaves `location.hash` path unchanged and the selected outline unchanged.
AC-M5 (SHOULD): Full-screen button `[data-testid=map-full]` toggles `.is-full` on the map card.

### 5.2 Area page — `#area/kommune/101` · `#area/postnr/2450` · `#area/kvarter/20101`
Purpose: everything known about one area, studied one indicator at a time, with the map and the trend side by side.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Denmark › København › 2450 København SV   Postal-code area             │
├────────────────────────────────────────────────────────────────────────┤
│ 2450 København SV                       [Show on map][↗ Chart][Compare][Buildings ›]│
│ Postal-code area · code 2450 · 39 452 inhabitants                       │
│ ┌────────┬────────┬────────┬────────┬────────┐                          │
│ │GROWTH  │PRICE/M²│RENT °  │UNEMP ° │RENTED °│  ← tiles; ° tiles dimmed + "municipality figure"│
│ └────────┴────────┴────────┴────────┴────────┘                          │
├────────────────────────────────────────────────────────────────────────┤
│ [Indicator: Population growth · % / yr ▾] [2026 ▾]   chips ………        │
│ ┌──────────────────────────────────┬───────────────────────────────┐   │
│ │ -0,1 %  -5,9 pp y/y  #333 of 590 │ +  mini map (draggable)   ⤢   │   │
│ │ vs median -0,2 pp                │ −                             │   │
│ │  ── 2450  ── København  ┄ median │        ┌────────┐             │   │
│ │  line chart 2016–2026            │        │ legend │             │   │
│ │ Source · FOLK1A · as of · Verify↗│        └────────┘             │   │
│ └──────────────────────────────────┴───────────────────────────────┘   │
│   60 %                               40 %   (both 380 px tall)         │
├────────────────────────────────────────────────────────────────────────┤
│ ▸ Population outlook          Projection 2026→2040 · DST 2026          │
│ ▸ All figures (63)                                                     │
│ ▸ Postal codes (12) / Quarters (67)                                    │
│ ▸ Data information                                                     │
└────────────────────────────────────────────────────────────────────────┘
```
Chart panel (`data-testid=chart-panel`) content by indicator kind:
- **History** (has `hist`): headline row (value, Δ y/y, rank, vs peer median), line chart: this area (solid, `--k1`), parent (solid, `--k2`, only if different entity), peer median (dashed grey), Denmark (dashed green, municipalities only). Hover tooltip with all series. Footer: source/table/as-of/verify. Same as today's "Trend" card, moved up and driven by the picker.
- **Snapshot** (BBR, Growth signals, Schools): headline row + `state-nohistory` caption ("published once · BBR 2026-09-15") + **distribution strip**: peers as small ticks on a horizontal axis, this area as a labelled dot, median marked. Plain arithmetic, no model.
- **Outlook**: headline row + the existing outlook chart (observed solid → projected dashed purple) — so the Outlook toggle below is *not* needed when an Outlook indicator is selected; the toggle then reads "shown above".
- **Climate**: three bars Today / 2070 / 2120 with low–high range whiskers, peers' median as ticks; caption on zones/figures sources; button `Climate sheet ›` (`#climate/<kommune>`).
Mini-map (`§4.6`): peers of this level around the area, coloured by the active indicator, selected area outlined, click a neighbour to open it.

Toggles (`data-testid=sec-outlook|sec-figures|sec-sub`): `<details>` elements; `open` state serialised into `show=`. Defaults: kommune → `outlook` open; postnr/kvarter → nothing open. *All figures* = existing full table (§4.8), with the active indicator row highlighted and scrolled into view when opened. *Sub-areas* = existing quarters/postal codes table with a sparkline column (SHOULD).

Removed: KEY FIGURES block (12 tabs × cards), the separate "Trend" and "Neighbours" cards (merged into the panel), the horizon segmented control in the header (now in PeriodControl), duplicated `Show on map` in two places.

Postal code & quarter specifics: inherited tiles/rows as §2.4; the picker groups inherited indicators under "From the municipality"; when such an indicator is selected the chart panel plots the municipality series and the headline row is labelled "København (municipality figure)". Quarter pages keep the KK vs DST outlook note and the Safety-survey block inside *All figures* as a sub-heading.

URL: `ind, y|hz, show, sub (kvarter|postnr), t (kept for table tab)`.

AC-P1 (MUST): on `#area/kommune/101` there is no element with text "KEY FIGURES"; `[data-testid=chart-panel]` and `[data-testid=minimap]` are siblings inside `[data-testid=study-row]`, and at 1440 px their bounding boxes have equal height (±2 px), panel left of map, widths within 55–65 % / 35–45 % of the row.
AC-P2 (MUST): `[data-testid=sec-outlook]` is `open` on `#area/kommune/101` and closed on `#area/postnr/2450`; toggling it updates `show=` in the hash; loading `#area/postnr/2450?show=figures` opens `sec-figures`.
AC-P3 (MUST): `#area/kommune/101?ind=surge_dw_pct` → `chart-panel` contains `[data-testid=clim-bars]` with 3 bars and `period-hz` is visible; `?ind=fc_growth` → `chart-panel` contains the outlook chart `[data-testid=outlook-chart]`.
AC-P4 (MUST): selecting a chip changes `chart-panel` heading text and the mini-map legend title without changing `#main.scrollTop` by more than 2 px.
AC-P5 (MUST): at 390 px, `chart-panel` is above `minimap` (stacked), each ≥ 300 px tall, no horizontal overflow.
AC-P6 (SHOULD): row click in *All figures* selects that indicator; the row has `.on`.

### 5.3 Data — `#data/areas/<level>` · `#data/projects` · `#data/national` · `#data/sources`
Purpose: the tabular home of every dataset, with export.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Denmark › Data                                        [Export ▾]       │
│ [Areas] [Projects] [National series] [Sources]                         │
├────────────────────────────────────────────────────────────────────────┤
│ AREAS                                                                  │
│ [Indicator ▾][2026 ▾]  chips…      [Municipalities (99)][Postal codes (606)][Quarters (67)]│
│ [🔍 filter] [All regions ▾] min. population [0]   99 rows · Columns ▾  │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ MUNICIPALITY  CODE REGION  POP  ▮ ACTIVE INDICATOR ▮ Δ  …columns… │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```
- **Areas** = old Table. The active indicator's column is highlighted and sorted by default; `Columns ▾` (SHOULD) picks which indicator groups are shown (default: headline 9 + active). Row click opens the area page. Header cell hover shows source/as-of.
- **Projects** = old Pipeline, unchanged table + filters; header carries `51 projects · Fingerplan, Anlægsstatus`; row click → project sheet.
- **National series** = old Market, rebuilt as a table: `Series · Latest · Period · y/y · Source · sparkline (last 5 y) · ↗ Chart`. The four big charts go; the four headline tiles stay as a compact row above the table (they are the national context). `↗ Chart` opens Charts with the series as the entity (SHOULD; MUST is the table).
- **Sources** = old sources accordion as a proper table: `Source · Publisher · Tables · As of · Fetched · Licence · Used for · ↗`. Empty Fetched cells get the build date with a `build` tag rather than blank.
- Tab state in the path; filters in the query (`q, region, minpop, ptype, pstatus`).

AC-D1 (MUST): `#data` redirects to `#data/areas/kommune`; `[data-testid=data-tabs]` has 4 tabs; `#table/postnr`, `#pipeline`, `#market`, `#sources` redirect to the corresponding `#data/...` hash (check `location.hash` after load).
AC-D2 (MUST): the sidebar has exactly 5 `[data-testid=nav-item]` elements with texts Map, Data, Charts, Properties, Compare.
AC-D3 (MUST): `#data/national` shows `[data-testid=national-table]` with ≥ 13 rows, each with non-empty Source cell; no `<canvas>`/`<svg>` larger than 300 px wide (the big charts are gone).
AC-D4 (MUST): `#data/sources` table has no empty cell in the "Fetched" column.
AC-D5 (MUST): `#data/areas/kommune?ind=unemp` → header cell `[data-col=unemp]` has `.on` and rows are sorted by it (first row value ≤ second for lower_better? no — sort descending by value regardless; check first two values monotone).

### 5.4 Charts — `#charts?ind=…&a=…`
Purpose: build a presentable line/bar/distribution chart of any indicator for any areas (and national series), export PNG/CSV.

Layout unchanged in structure; changes:
- Uses the shared IndicatorPicker (with an extra group **National series** listing the 13 macro series; picking one clears areas and plots Denmark — SHOULD).
- Toolbar → two rows: `[Indicator ▾][from ▾][to ▾] ☑ median ☑ Denmark [Auto|Line|Bars|Distribution]` and `[Add area ▾] (+Top 5)(+Copenhagen metro)(+Big four)(clear)` then entity chips. Title input + `Download PNG` + `Data CSV` move to the card header right.
- Climate indicators: x-axis = horizons (Today/2070/2120), bars per area with range whiskers. Outlook: dashed purple after `today` line (existing style). PNG footer keeps source line.
- Chart CSV uses the long schema (§4.9).

AC-C1 (MUST): `#charts?ind=growth&a=kommune:101,kommune:751` renders `[data-testid=chart-svg]` with 2 series paths `[data-series]` + median + Denmark; `[data-testid=ind-picker]` present.
AC-C2 (MUST): `#charts?ind=surge_dw_pct&a=kommune:101,kommune:751` renders 3 x-axis tick labels `Today, 2070, 2120`.
AC-C3 (SHOULD): picking `National series › Rent index` plots one series labelled "Denmark".

### 5.5 Properties (portfolio) — `#properties?p=lat,lon[:label];lat,lon[:label]…`
Purpose: assess one or many test properties as a set — where they sit, what their areas publish, exported with sources.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Denmark › Properties   3 properties                    [Export ▾][Copy link]│
├────────────────────────────────────────────────────────────────────────┤
│ [Paste Google Maps link or lat, lon        ] [label] [+ Add]   or click the map│
│ ⓘ processed in your browser · stored only in this page's URL · ≤ 30    │
│ ┌ 1 Test Vesterbro ×  ┐┌ 2 Ørestad ×  ┐┌ 3 Aarhus C ×  ┐               │
├────────────────────────────────────────────────────────────────────────┤
│ [Indicator ▾][2026 ▾] chips…                      [Layers ▾] radius [1 km ▾]│
│ ┌──────────────────────────────────┬───────────────────────────────┐   │
│ │ PORTFOLIO TABLE                  │ + mini map, numbered pins  ⤢  │   │
│ │ # Property   Area      Value Rank│ − draggable, fits all pins    │   │
│ │ 1 Vesterbro  Vesterbro syd -1,3% │                               │   │
│ │ 2 Ørestad    2300 …              │                               │   │
│ │ 3 Aarhus C   8000 …              │                               │   │
│ │ ── median  · min · max  (no weighting) ──                        │   │
│ └──────────────────────────────────┴───────────────────────────────┘   │
├────────────────────────────────────────────────────────────────────────┤
│ ▸ Property 1 — Vesterbro syd   (headline tiles · area profile · infra nearby · public buildings · schools · climate)│
│ ▸ Property 2 — …                                                       │
└────────────────────────────────────────────────────────────────────────┘
```
- Add: paste box accepts Google Maps URLs (`@lat,lon`, `q=lat,lon`, `!3d…!4d…`), `lat, lon`, or `lat lon`; label optional (defaults `Property n`). Clicking the mini-map in *add mode* (`[+ Add on map]` toggle) drops a pin. Max 30; the 31st shows "30 is the limit — the address list lives in the URL".
- Property chips: numbered, colour `--pin`, `×` removes, click = scroll to its section and highlight its row.
- Portfolio table columns: `# · Property · Municipality · Postal code · Quarter · <active indicator value> · rank · Δ y/y · source`. Header dropdown `Columns ▾` (SHOULD) adds up to 6 more indicators as columns (MUST: active indicator only + the 5 headline figures as fixed columns). Aggregate footer: median, min, max across properties with a value; caption "n of m properties share a municipality → same published figure" when applicable.
- Mini-map: draggable (fix `dragging:false`), fits all pins on load, pin number labels, active indicator fill at the finest level available per pin (quarter > postal code > municipality), radius rings from the `radius` select (0/500/1000/2000/5000), feature layers via Layers ▾.
- Per-property sections = the existing analysis sheet content (headline tiles, area profile, safety, infra nearby, public buildings within ring, schools, climate), each as a `<details>` (`data-testid=prop-<n>`), first one open by default. The existing headline-tile → map colouring stays but is driven by the shared picker.
- Export ▾ → *Properties portfolio* (§4.9) and *This view*.

URL: `p` (≤ 30 items), `ind, y|hz, lay, rad, show`.

AC-PR1 (MUST): `#properties?p=55.6545,12.539:Test;55.63,12.58:Two` → `[data-testid=prop-chip]` count 2, `[data-testid=portfolio-table] tbody tr[data-prop]` count 2, footer row `[data-testid=portfolio-agg]` contains "median" and does not contain "weighted"/"score"; mini-map has 2 `.pin-n` markers.
AC-PR2 (MUST): pasting `https://www.google.com/maps/@55.6761,12.5683,15z` into `[data-testid=prop-input]` and clicking `[data-testid=prop-add]` appends `;55.6761,12.5683` (5-dec rounding) to `p=` and adds a third row.
AC-PR3 (MUST): `#analysis?a=55.65450,12.53900&la=Test` redirects to `#properties?p=55.6545,12.539:Test`.
AC-PR4 (MUST): the mini-map drags (AC-MM1) and `[data-testid=minimap-full]` works (AC-MM2).
AC-PR5 (MUST): `[data-export=properties]` download's header contains `property_id;label;lat;lon;` and the long-schema columns `source;table_id;as_of`.
AC-PR6 (MUST): with 31 items in `p=`, only 30 are rendered and `[data-testid=state-limit]` is visible.

### 5.6 Compare — `#compare?a=kommune:101&b=kommune:751`
Purpose: two areas, every indicator, no winner.

Changes (MUST are small): shared PeriodControl for the climate rows (horizon segmented moves next to the area selects), `↗ Chart` per row via the shared picker semantics (row click → Charts with both areas), sticky group headers, "better side shaded" keeps its footnote. SHOULD: 3rd column (`c=`), and a `+ Add to Properties` for coordinate compare. LATER: mini-map pair.

AC-CM1 (MUST): `#compare?a=kommune:101&b=kommune:751` shows `[data-testid=period-hz]` once; clicking `[data-hz=2120]` updates the climate group header text to contain "2120" and the hash to `hz=2120`.
AC-CM2 (MUST): no cell text contains "winner"/"score"; the page footer text contains "No overall winner".

### 5.7 Detail sheets
Common frame: breadcrumb → title + tag pills → actions `[‹ Back][Show on map][<parent> ›]` → tiles → two-column body (map | facts) → sections. Common rules: mini-map §4.6 (draggable, ⤢), tiles §4.7, empty tile slots are not rendered (today a grey slab fills the row: remove it — AC-SH1).

- **Project** `#project/<id>`: tiles `Opening · Budget · Length · Stations`; "Where it runs" map over the active indicator (fill uses `ind=` from URL; default growth); "Areas served" chips; "Outlook around this project" table (kept). Add `Source ↗` and `updated` in the facts column.
- **Public building** `#public/<kommune>/<id>`: tiles `Floor area · Built · Municipality`; group duplicates: the list views (`#publist`) group rows by (name, use code) with a count badge and generic BBR names ("Anden bygning til…") get the OSM name when within 60 m (existing rule) else the address as title. Breadcrumb must be `Denmark › København › <building>` (today it shows "Macro map").
- **School** `#school/<nr>`: unchanged content; tiles wrap without the grey slab; add `Verify ↗ Uddannelsesstatistik` on every tile.
- **Climate** `#climate/<kommune>`: stays as the deep-dive sheet. Header gets the shared PeriodControl (horizon) instead of its own; the "Show the zones on the map" button navigates to `#map/<kommune>?ind=surge_dw_pct&hz=<hz>` (zones appear automatically per §4.4). Reachable from the area page chart panel (Climate indicators) and from the `ⓘ details` popover of any Climate indicator.

AC-SH1 (MUST): on `#project/m5-phase-1`, `#public/101/<id>`, `#school/280657`, `#climate/0101` there is no `.tile.empty`/grey filler element (`[data-testid=tiles] > *` all have non-empty text).
AC-SH2 (MUST): `#climate/0101` shows `[data-testid=period-hz]`; clicking "Show the zones on the map" navigates to a hash starting with `map/101` containing `ind=surge_dw_pct`.
AC-SH3 (MUST): breadcrumb on a public-building sheet contains the municipality name, not "Macro map".

---

## 6. Responsive behaviour

| Width | Sidebar | Toolbars | Area page study row | Tables | Tiles |
|---|---|---|---|---|---|
| ≥ 1440 | 240 px | 1 row + chips | 60/40, 380 px | full | 5 |
| 1366×768, 1536×864 | 240 px | 1 row + chips (chips may wrap to 2) | 58/42, 340 px | full | 5 |
| 1025–1250 | 240 px | 2 rows | 55/45, 320 px | horizontal scroll | 3+2 |
| ≤ 1024 (tablet) | top bar + drawer | stacked, chips scroll-x | stacked, 320 px each | scroll-x | 3+2 |
| ≤ 600 (mobile 390) | top bar + drawer | stacked; picker popover full width; period below | stacked, 300 px each; map 55vh on `#map` | scroll-x, first column sticky | 2 |

Rules: no element may cause `document.documentElement.scrollWidth > innerWidth` at any listed width (AC-R1). Legends on mobile collapse to a single-line "Legend ▾" pill at bottom-left of the map. Sticky top bar height ≤ 96 px on mobile.

AC-R1 (MUST): for each of `1366×768, 1536×864, 1440×900, 390×844` and each route `#map, #area/kommune/101, #area/postnr/2450, #data/areas/kommune, #charts?ind=growth&a=kommune:101, #properties?p=55.6545,12.539, #compare?a=kommune:101&b=kommune:751`: `scrollWidth <= innerWidth` and zero `pageerror`.
AC-R2 (MUST): at 1366×768 `#area/kommune/101`: `[data-testid=study-row]` top < 768 (the chart|map row starts inside the first screen).

---

## 7. Keyboard & accessibility
- All controls are real `<button>`/`<select>`/`<input>`; popovers use `role=dialog` (Layers, Export) or `role=listbox` + `aria-activedescendant` (picker). `aria-expanded` on every trigger.
- Focus visible everywhere: `outline:none; box-shadow:var(--focus-ring)` on `:focus-visible`.
- Shortcuts (SHOULD): `/` focus search or picker search; `Esc` closes any popover/full-screen; `[`/`]` previous/next chip; `g m / g d / g c / g p` go to Map/Data/Charts/Properties.
- Colour is never the only carrier: legend bins have values; tiles have `▲/▼` glyph plus colour for Δ; projection has pill + dash; inherited has label.
- Contrast: text on paper ≥ 4.5:1 (`--muted #8A8C81` on `#F6F6F3` is 3.4:1 → use it only for ≥ 12 px mono captions, and darken to `#6F7168` for 11 px text — MUST sweep on `.cap,.hint`).
- Map: keyboard users can select areas through search; drilled municipality has `aria-live=polite` announcement "Showing København, 67 quarters".

AC-A1 (MUST): axe-core (via Playwright `@axe-core/playwright` or injected `axe.min.js` from cdnjs) on `#map`, `#area/kommune/101`, `#data/areas/kommune`, `#properties?p=55.6545,12.539` reports zero `serious`/`critical` violations.
AC-A2 (MUST): Tab from the page start reaches `ind-picker-btn` within 12 tabs on `#map`; Enter opens it; Esc closes it.

---

## 8. Remove or merge

| Remove / merge | Why |
|---|---|
| `Market` nav item and its 4 large charts | → Data › National series table + Charts |
| `Pipeline` nav item | → Data › Projects |
| `Climate risk` overlay button and its floating filter card | → Climate indicators + context zones + legend |
| `Infra projects`, `Public buildings`, `Services` toolbar buttons | → Layers ▾ |
| `Copenhagen`, `Denmark` jump buttons | → search dropdown "Jump to" |
| `Paste Google Maps link…` second search box on the map | → unified search + Properties page |
| Area page KEY FIGURES (12 tabs × cards) | → picker + chart panel |
| Area page separate Trend + Neighbours cards | → merged into the study row |
| Horizon segmented control in area/compare/climate headers | → PeriodControl |
| Privacy sentence on every map | → tooltip + Properties page |
| Empty grey tile filler on sheets | visual noise |
| Sidebar "Export data" single-CSV button + 4-line explanation | → Export ▾ menu |
| Both rank formats (`#n / N`, `#n of N`) | one format |
| Legend filter buttons (`ONLY`, `ZOOM IN` chips inside legends) | → Layers menu; legends show keys only |
| `#analysis` route (kept only as redirect) | → `#properties` |

---

## 9. Priorities and effort (single agent, one app.js)

> Amended by A1/A2: item 6 is replaced by "Test property rebuild (§5.5′, AC-TP1–TP6)" ≈ 1.5 h; item 11 (Compare) becomes "delete Compare + redirect" ≈ 0.25 h. Portfolio items move to LATER.

**MUST — v3.0 overnight (≈ 14 h)**
1. Navigation & routing: 5 nav items, Data tabs, redirects, `hashFor/parseHash` for new keys (§3) — 1.5 h — AC-D1, D2, U1
2. IndicatorPicker + chips + PeriodControl (year/horizon/projection) — 2.5 h — AC-I1–I5, T1–T2
3. Climate as indicator family: delete overlay button, context zones bound to Climate indicators, legends stack — 1.5 h — AC-L3, LG1, M4
4. Layers ▾ menu, toolbar consolidation, unified search with coordinates — 1.5 h — AC-L1, L2, M1–M3
5. Area page rebuild (study row, chart panel modes, toggles, inherited marking, tiles clickable) — 3 h — AC-P1–P5, H1–H2, E2
6. Properties portfolio (multi-pin URL, chips, table + median/min/max, draggable mini-map, full screen, analysis redirect) — 2.5 h — AC-PR1–PR6, MM1–MM2
7. Export ▾ + long schema + unit validation + projects/national/sources/properties files — 1.5 h — AC-X1–X4
8. Data › National series table, Sources table with Fetched fill — 0.75 h — AC-D3, D4
9. Responsive shell (mobile top bar + drawer, stacked rows, no overflow) + 1366 layout — 1.25 h — AC-S1–S3, R1–R2, P5
10. Leaflet teardown registry, number-format sweep (rank format, small base, kDKK), sheets filler removal, breadcrumb fix — 1 h — AC-MM3, SH1–SH3, G1
11. Compare: shared horizon control — 0.25 h — AC-CM1–CM2

**SHOULD — first follow-up**
Pinned chips (localStorage) · `/` shortcut and full keyboard model (AC-I6, A2 full) · Columns ▾ on Data › Areas and portfolio table · Charts: national series entity (AC-C3) · Sub-areas sparkline column · Compare multi-select picker + 3rd column · Full-screen on the main map card · Legend collapse on mobile · Public-building list grouping.

**LATER**
Everything (.zip) export · PNG export of the area page study row · Compare mini-maps · Saved portfolios (named, in URL) · Print stylesheet for presentations · Investigate the KK vs BBR "Dwellings built 2010+" gaps (data task; UI shows both with a caveat until resolved).

---

## 10. `data-testid` contract (agent must add these exactly)

| testid | Element |
|---|---|
| `sidebar`, `nav-item`, `nav-toggle`, `nav-drawer`, `topbar-mobile` | shell |
| `export-btn`, `export-menu`, `[data-export=view|areas|projects|national|properties|sources]` | export |
| `ind-picker`, `ind-picker-btn`, `ind-picker-pop`, `ind-search`, `ind-chips`, `[data-group=<name>]`, `[data-ind=<key>]` | picker |
| `period`, `period-year`, `period-hz`, `[data-hz=…]`, `period-proj` | period control |
| `layers-btn`, `layers-pop`, `[data-layer=infra|public|services|zones|radius]` | layers |
| `map`, `map-toolbar` (`[data-row=1|2]`), `search`, `search-coord`, `map-full`, `legend`, `legend-zones`, `legend-infra`, `legend-public`, `legend-services` | map |
| `tiles`, `tile-<key>`, `study-row`, `chart-panel`, `state-nohistory`, `dist-strip`, `clim-bars`, `outlook-chart`, `minimap`, `minimap-full`, `sec-outlook`, `sec-figures`, `sec-sub` | area page |
| `data-tabs`, `areas-table` (`th[data-col=<key>]`), `projects-table`, `national-table`, `sources-table` | data |
| `chart-svg`, `[data-series]` | charts |
| `prop-input`, `prop-add`, `prop-chip`, `portfolio-table`, `portfolio-agg`, `prop-<n>`, `state-empty`, `state-limit` | properties |
| `state-empty`, `state-loading`, `state-error` | states |
| `window.__maps` | array of live Leaflet instances (test hook) |

Global AC-G1 (MUST): no visible text node in any MUST route matches `/\b(score|weighted|index of)\b/i` except the existing series names containing "index" (CPI, HPI, rent index) inside Data › National series and Charts.
Global AC-U1 (MUST): for each MUST route, `location.hash` after load, after one interaction, and after `history.back()` round-trips through `parseHash()` → `hashFor()` unchanged (idempotent serialisation).

---

## 11. Notes for the coding agent
- Keep existing module boundaries in `app.js`; add the picker/period/layers/export as small functions returning markup + one delegated click handler each (the file already uses delegated `data-*` handlers).
- Do not touch data build scripts except the export unit assertion; all data issues (KK vs BBR gaps, kDKK) are surfaced with caveats, not "fixed" by picking a source.
- Ship the redirects first so old links never break during the night.
- Run the AC list as one Playwright spec (`tests/v3.spec.py`) and keep it green before each commit; capture `x_v3_*.png` for the same set of states as `v26/` for the morning review.
