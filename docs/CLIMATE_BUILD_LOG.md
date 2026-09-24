# Climate branch (v2.5-climate) — build log

Worktree: `am-dashboard-dk-climate`, branch `v2.5-climate`, parallel to `../am-dashboard-dk`
(never edited from here). Serve on port **8081** so the other session keeps 8080.

## Shared files touched

Files shared with other branches (`config/indicators.json`, `src/app.js`, `src/index.html`,
`Makefile`, `.github/workflows/refresh.yml`, `README.md`, `CHANGELOG.md`, `docs/DATA_MAP.md`)
must be edited only in small, additive ways, and every edit listed here for the merge.

| Date | File | Edit | Why |
|---|---|---|---|
| 2026-09-23 | `.gitignore` | +6 lines: `data/raw/{klimaatlas,flood_hazard,fp,dhm,bluespot}/` | the new raw pulls and the 3.4 GB hazard zip must never be committed |
| 2026-09-23 | `config/indicators.json` | +9 indicators in a new `"Climate"` group; one sentence appended to `_doc` describing `calc: climate` and `horizon` | the layer's registry entries — additive, no existing indicator touched |
| 2026-09-23 | `scripts/build_makro.py` | +2 lines: import `calc_climate`, and one `if calc == "climate"` branch beside the existing `bbr` / `infra_index` / `public_index` / `schools` branches | the calc itself lives in the new `scripts/climate_common.py`, so this file stays a two-line diff |
| 2026-09-23 | `scripts/build_dashboard.py` | +11 lines: copy `data/processed/climate/**.json` → `dist/climate/` | the page loads the zones on demand, exactly as it does `dist/micro/` and `dist/public/` |

Nothing else shared has been touched: `src/app.js`, `src/index.html`, the `Makefile`,
`.github/workflows/refresh.yml`, `README.md`, `CHANGELOG.md` and `docs/DATA_MAP.md` are all
untouched on this branch so far.

## Climate-only files (free to change)

`scripts/*climate*`, `scripts/fetch_klimaatlas.py`, `data/raw/{klimaatlas,flood_hazard,dhm,bluespot,fp}/`,
`data/processed/climate/`, `docs/CLIMATE*.md`.

## Worktree environment (2026-09-23)

* `.env` copied from `../am-dashboard-dk` (gitignored, not committed).
* Symlinks to the main folder's gitignored caches (read-only use, no GBs duplicated):
  `data/raw/bbr` (4.0 GB), `data/raw/dar` (78 MB), `data/raw/public`, `data/raw/uddstat`,
  `data/geo/raw` (148 MB). These show as `??` in `git status` — a `.gitignore` entry ends in
  `/` and does not match a symlink. **Never `git add -A` here**; add paths explicitly.
* `data/raw/*.csv` StatBank pulls (25 MB) copied, not symlinked, so a `make fetch` here cannot
  write into the main folder.
* New climate data dirs created as real local dirs (never symlinks):
  `data/raw/klimaatlas`, `data/raw/flood_hazard`, `data/raw/dhm`, `data/raw/bluespot`,
  `data/raw/fp`, `data/processed/climate`.
* Verified: `make validate` and `make build` both exit 0 here (dist/index.html 4.4 MB,
  99 municipalities, 606 areas).

## Probe step (2026-09-23)

`scripts/probe_climate.py` → `docs/CLIMATE_PROBE.md`. Read-only; writes nothing but that one doc.
11 of 12 expected values reproduce. What it changes about the plan:

* **Klimaatlas is the backbone.** Storm surge per coastal stretch (34 with geometry) and cloudburst
  per kommune, sub-second, every expected figure matching, with `periode`/`scenarie` columns that map
  straight onto a Today / 2050 / 2100 horizon pill. No raster work needed for the first layer.
* **MST `OD_fare_2024` cannot give a depth grid over REST** — it is a MapServer, `/exportImage` is
  absent and `/export` returns a rendered PNG. `/identify` does return the modelled depth per point
  (da-DK decimal comma), which is enough for a test-property score.
* **The MST bulk drop is scriptable** — the Cerberus client at sftp.statens-it.dk answers a plain
  HTTP client: `POST /public/op/<id>/get_dir` lists (8 files, 3.49 GB) and `POST /public/op/<id>/zip/`
  downloads. `Oversvømmelsesfare.zip` (3.41 GB) is the depth-raster route if we ever need the grid.
* **Blocked on credentials:** DHM WCS and the bluespot tiles both need a Datafordeler key or service
  user; `.env` carries only `UDDSTAT_API_KEY`. The legacy `ftp.dataforsyningen.dk` /
  `download.dataforsyningen.dk` hosts no longer resolve. Nothing else waits on this.
* **Correction to the brief:** the 2024 risk-area group holds **26** sub-layers, not 25. Layer 33
  (Køge Bugt/København) is a single feature of 101.53 km², which does match.
* **Coast flag is free:** 76 of 99 kommuner are coastal, 9 of the metro 19, computed from
  `data/geo/kommuner.geojson` alone. Borderline cases are listed in the probe doc.

---

# v2.5 build — 2026-09-23

## 0a · Datafordeler credentials — not found

Searched, without ever printing a value: the shell environment (`env | grep -i datafordeler` → 0
matches); `~/.zprofile` (the only shell rc that exists — no `.zshrc`, `.zshenv`, `.bash_profile`,
`.bashrc` or `.profile`); every `.env*` under `../am-dashboard-dk`, `../am-dashboard-dk-forecast`,
`~/Desktop/Sweden dashboard/am-dashboard-se` and this worktree; the login keychain
(`security find-generic-password -s datafordeler` → not found); `data/raw/bbr/fetch_log.txt`,
`fetch.txt` and `validate.txt`; and the git history of the main repo.

Every hit for the string `DATAFORDELER` is source code or documentation naming the variable —
`scripts/fetch_bbr.py`, `scripts/fetch_dar.py`, `scripts/bbr_introspect.py`, `docs/RUNBOOK.md`
step 8, `docs/GEO.md`. **No key or service user exists on this machine.** The four `.env` files in
the family all carry exactly one key, `UDDSTAT_API_KEY`.

Consequences, both already flagged in `docs/CLIMATE_PROBE.md`:

* probe §5 (DHM WCS) stays at HTTP 401 — coverage list and the two GetCoverage timings unmeasured;
* the Bluespot_ekstremregn tile size stays an estimate, so `cloudburst_dw_pct` is declared in the
  registry and returns null with reason `not computed yet`.

Nothing else in the layer depends on it: Klimaatlas, F&P and the Miljøstyrelsen sources are all
open.

## 0b · Kystdirektoratet Kystplanlægger — see `docs/CLIMATE_PROBE.md` §9

Reconnaissance only, nothing built on it. Headlines:

* `Kystplanlaegger_Oversvommelsesfare_2` publishes **3 horizons × 4 return periods × 2
  representations** — an extent polygon (Feature Layer) and a depth raster (Raster Layer) for
  2020 / 2070 / 2120 at 50, 100, 1 000 and 10 000 years. 27 layers in all.
* **Coverage is national**, not a handful of stretches: extent 441 503–893 022 E, 6 049 784–
  6 402 264 N in EPSG:25832, against `OD_fare_2024`, which only covers the designated risk areas.
  Painted share of a 2 × 2 km box: Sydhavn 51 % / 79 % / 86 % across the three horizons, against
  1.9 % for `OD_fare_2024`; Esbjerg 36/46/47 % against 15 %; Aalborg 31/38/49 % against 8 %.
* **Vector yes, raster no.** `capabilities` includes `Data`, so the extent polygons come out as
  geojson (5 features = 7.9 MB; 42 polygons for 2020 · 100 yr), but they carry no depth, level or
  scenario — the horizon lives in the layer name. `format=tiff&pixelType=F32` returns PNG, and
  there is no ImageServer, WCS or bulk route, so raw depth is only readable through `/identify`,
  one point per request.
* **Climate basis, verbatim:** *"Viser oversvømmesesfare og oversvømmelsesdybde i 2020, 2070 og
  2120 for en 100, 1.000 og 10.000 års hændelse."* — "Shows flood hazard and flood depth in 2020,
  2070 and 2120 for a 100-, 1 000- and 10 000-year event." That is all of it: **no scenario, no
  percentile, no sea-level figure.** The rise is baked in and unlabelled, which is why the
  indicators are built on Klimaatlas (explicit `scenarie` + `percentil`) and this service is kept
  as a map-side illustration only.
* `/identify` depth, 100-year event, metres (the service formats in da-DK):

| point | KDI 2020 | KDI 2070 | KDI 2120 | MST `OD_fare_2024` 100 yr |
|---|---|---|---|---|
| Copenhagen Sydhavn 55.650, 12.545 | NoData | NoData | NoData | NoData |
| Hvidovre Avedøre Holme 55.625, 12.460 | NoData | NoData | NoData | NoData |
| Køge harbour 55.455, 12.195 | 0,122646 | 0,371910 | 0,964475 | NoData |

  `NoData` is a real answer — dry at that return period, not missing. The Sydhavn point is dry
  while a cell **150 m away** carries 0,187538 m, so a point-in-raster read is not a safe property
  score on its own; a ring around the pin has to be sampled.

## 1 · `scripts/fetch_klimaatlas.py` → `data/raw/klimaatlas/`

| pull | service · layer | rows | version | seconds |
|---|---|---|---|---|
| `coast_values` | `VandstandStormflodKyst_latest` · 0 | 3 162 | v2025a | 1.6 |
| `coast_stretches` | `VandstandStormflodKyst_latest` · 1 | 34 | v2025a | 1.1 |
| `precip_values` | `NedboerKommuner_latest` · 0 | 5 586 | v2025a | 3.8 |

`aarstid = 1` (annual); every `scenarie` (coast 0/119/126/245/370/585, rain 0/26/45/85), every
`periode` 1–4 and every `percentil` 10/50/90 kept. Paginated at the services' own
`maxRecordCount` of 2 000 with `resultOffset`. JSON + flat CSV + `meta.json` with the version
string and fetch date. Stretch geometry in EPSG:4326.

## 2 · `data/external/klimaatlas_coast_kommune.csv` (generated, committed)

`scripts/build_climate_coast_map.py`. A kommune's coastline is what is left of its boundary after
subtracting every neighbour's (60 m tolerance, EPSG:25832); over 100 m of it makes it a candidate,
and the candidate is coastal when that coastline runs within **2 km** of a Klimaatlas stretch.

**77 of 99 kommuner coastal, 22 landlocked. 43 touch more than one stretch → value = MAX.**

| code | metro kommune | kystkoder | coastline | nearest stretch |
|---|---|---|---|---|
| 0101 | København | SJ7;SJ8 | 115 731 m | 0 m |
| 0147 | Frederiksberg | — | 136 m | 3 782 m → landlocked |
| 0151 | Ballerup | — | 0 m | — |
| 0153 | Brøndby | SJ8 | 2 988 m | 0 m |
| 0155 | Dragør | SJ7;SJ8 | 17 388 m | 0 m |
| 0157 | Gentofte | SJ7 | 11 327 m | 0 m |
| 0159 | Gladsaxe | — | 0 m | — |
| 0161 | Glostrup | — | 0 m | — |
| 0163 | Herlev | — | 0 m | — |
| 0165 | Albertslund | — | 0 m | — |
| 0167 | Hvidovre | SJ8 | 10 279 m | 0 m |
| 0169 | Høje-Taastrup | — | 0 m | — |
| 0173 | Lyngby-Taarbæk | SJ7 | 3 645 m | 0 m |
| 0175 | Rødovre | — | 0 m | — |
| 0183 | Ishøj | SJ8 | 3 735 m | 0 m |
| 0185 | Tårnby | SJ7;SJ8 | 90 416 m | 0 m |
| 0187 | **Vallensbæk** | **SJ8** | **376 m** | **0 m** |
| 0190 | Furesø | — | 0 m | — |
| 0230 | Rudersdal | SJ7 | 7 585 m | 0 m |

København → SJ7 ✓ · Hvidovre, Brøndby, Ishøj → SJ8 ✓. **Vallensbæk decided by the 2 km rule:
coastal.** It has only 376 m of free boundary — under the 1 km threshold the probe used for the
coastal count — but that boundary sits *on* the SJ8 polygon (0 m). Frederiksberg is the control:
136 m of free boundary, but the nearest stretch is 3.8 km away, so its sliver is an enclave
artifact and it stays landlocked. This is why the 2 km rule replaced the length threshold, and why
this map has 77 coastal kommuner where probe §8 reported 76.

## 3 · `scripts/fetch_fp_claims.py` → `data/raw/fp/`

| chart | version | column | rows | matched |
|---|---|---|---|---|
| `TUJ9b` | 4 | `komnavn`, `antal` | 98 | 98 |
| `z0zEO` | 4 | `komnavn`, `antal skader pr 1000 indbygger` | 98 | 98 |

Names trimmed and normalised with the same convention as `scripts/import_lbf.py` /
`import_boligstat.py` (NFKC, lower-case, strip a trailing " kommune", then an `ALIASES` map).
**98 / 98 resolved, no aliases needed beyond the inherited ones.** An unmatched name exits
non-zero rather than dropping a kommune.

## 4a · `scripts/fetch_flood_official.py --areas`

**26 risk areas**, 1 309.9 km² in total, EPSG:3044 → 4326, joined to DAGI kommune polygons.

> **The designation says 51, an any-touch join says 56.** Five kommuner only clip the edge of
> Køge Bugt/København or Roskildefjord: **Rødovre 0.05 km², Albertslund 0.06, Høje-Taastrup 0.27,
> Egedal 0.33, Brøndby 0.71**. Requiring **≥ 1 km² inside a designated area** drops exactly those
> five and reproduces the official 51. The cut sits in a real gap in the distribution — the next
> kommune up holds 1.82 km² — so it is not a fitted constant. The five are kept in the file as
> `kommuner_marginal` and flagged `flood_risk_area = 0`.

Largest areas: Østlig Limfjord 295.9 km², Vestlig Limfjord 259.7, Køge Bugt/København 101.5
(14 kommuner touched, 10 designated), RandersFjord 87.9, Rømø 82.8.

## 4b · The bulk hazard drop

`scripts/fetch_flood_official.py --bulk` · 3 410 619 711 B, resumable, ~25 min at 2.2 MB/s.

> **The Cerberus `/zip/` route wraps the file in another zip.** The stream that comes down is
> 3 391 479 270 B — *smaller* than the listing says — because the outer archive deflates the inner
> zip a little. A byte-count check against the listed size therefore fails on a perfectly good
> download. The script now unwraps the single entry, checks **that** against 3 410 619 711 B
> (exact match), and deletes the 3.4 GB wrapper.

Contents — 29 entries, 7.86 GB uncompressed, 13 rasters in `Hav/` and `Vandløb/`:

| raster | size |
|---|---|
| `Hav/Oversvømmelsesfare_hav_10000år.tif` | 680.1 MB |
| `Vandløb/Oversvømmelsesfare_vandløb_100år.tif` | 678.4 MB |
| `Hav/Oversvømmelsesfare_hav_1000år.tif` | 626.6 MB |
| … | … |
| **`Hav/Oversvømmelsesfare_hav_100år.tif`** | **551.8 MB** ← extracted |

Extracted raster, from its own GeoTIFF tags:

| property | value |
|---|---|
| size | 90 287 × 70 503 px (6.37 G pixels) |
| pixel size | 5 m × 5 m |
| CRS | EPSG:25832 |
| extent | 441 585 – 893 020 E, 6 049 785 – 6 402 300 N |
| nodata | −3.40282306073709653e+38 |
| datatype | float32, LZW (compression 5), **tiled 128 × 128** |

## 5 · `scripts/build_surge_zones.py`

### Reading a 6.4 G-pixel raster with no GDAL

Pillow can only decode this TIFF in one piece — 25 GB of float32. Two facts made it tractable:
the tile index is in the header, and **371 707 of the 389 006 tiles are the identical all-nodata
tile, compressing to exactly 875 bytes each**. Skipping every tile of that modal byte count leaves
**17 299 tiles, 213 MB — the entire flooded extent of Denmark**. Each is decoded by wrapping its
raw LZW bytes in a minimal one-strip TIFF header and handing that to the same libtiff Pillow
already links. The whole raster reads in **62 s**.

### Output

`data/processed/climate/surge_today/<kommune>.json` — **80 files** + `index.json`.
**1 255.2 km² flooded** at the 100-year sea level nationally; 1 196.0 km² after the zones are cut
to kommune boundaries and cleaned.

> **Two deviations from the brief, both for the size budget.** The brief asked for a 2 m
> simplification; the source is 5 m max-pooled to 10 m, so every vertex is already a 10 m cell
> corner and a 2 m tolerance removes nothing — it just stores the staircase, and the folder came
> to **90.4 MB against a 60 MB budget** with six files over 3 MB. Simplifying at **8 m** (still
> inside one cell) and filling pinholes under **2 000 m²** — the same problem as the risk areas,
> a vectorised flood model is riddled with them — brings it to **45.8 MB, no file over 3 MB**, at
> the cost of **+0.6 % area**. Parts under 200 m² are dropped as specified, coordinates are
> EPSG:4326 at 6 decimals as specified.

Every climate zone file carries the shared header: `hazard`, `horizon`, `depth_class` (or
`threshold_mm`), `method`, `source`, `level_cm`, `updated`.

| | |
|---|---|
| climate folder | 45.8 MB (limit 60 MB) |
| largest file | 2.12 MB `surge_today/0760.json` (limit 3 MB) |
| `risk_areas.json` | 1.24 MB, from 90 MB raw |
| `index.json` | 113 kB |

Highest Today `surge_dw_pct` (BBR boligtype 1–5, status 6, at the building's coordinate):

| code | kommune | zone km² | dwellings | in the zone | % |
|---|---|---|---|---|---|
| 0665 | Lemvig | 39.40 | 13 510 | 1 281 | 9.48 |
| 0440 | Kerteminde | 19.27 | 14 173 | 954 | 6.73 |
| 0480 | Nordfyns | 42.00 | 18 170 | 1 083 | 5.96 |
| 0615 | Horsens | 9.10 | 49 620 | 2 596 | 5.23 |
| 0250 | Frederikssund | 17.36 | 27 785 | 1 314 | 4.73 |
| 0482 | Langeland | 22.59 | 11 486 | 538 | 4.68 |
| 0155 | Dragør | 2.36 | 7 222 | 309 | 4.28 |
| 0326 | Kalundborg | 34.65 | 34 566 | 1 473 | 4.26 |
| 0760 | Ringkøbing-Skjern | 103.28 | 40 190 | 1 662 | 4.14 |
| 0390 | Vordingborg | 39.85 | 30 185 | 1 233 | 4.08 |

## 6 · `config/indicators.json` — group "Climate"

Nine indicators, all `level: kommune`, `direction: lower_better`, `calc: climate`, each with
`note` and `source`. `horizon: ["today","2050","2100"]` on the seven where it applies;
`weather_claims_1000` and `flood_risk_area` carry none.

`sealevel_cm` · `surge100_cm` · `surge_freq_x` · `rain100_1h_mm` · `cloudbursts_yr` ·
`weather_claims_1000` · `flood_risk_area` · `surge_dw_pct` · `cloudburst_dw_pct`

Mapping, as specified: today = scenarie 0 / periode 1 · 2050 = periode 3 · 2100 = periode 4 ·
sea scenarie 245, rain 45 · percentil 50 · absolutaendring 1. `range` carries p10/p90 at the same
scenario plus the low/high scenarios (sea 126/585, rain 26/85). Coastal indicators are null for
landlocked kommuner with `reason: "not coastal"`; nothing computed yet is null with
`reason: "not computed yet"`. Postal codes and quarters inherit the kommune figure with `°`,
which they get for free from `level: kommune`.

**All three horizons live in `data/processed/climate/index.json`; `makro.json` carries the Today
value.** The horizon pill (`hz=`) is app-side work and is deliberately not in this step — no line
of `src/app.js` has been touched on this branch.

## 7 · Tests — `tests/test_climate.py`, 25 tests, all pass

| check | expected | got |
|---|---|---|
| SJ7 historic `Stormfl100Aarsh` | 156.85 | 156.85 ✓ |
| SJ7 SSP2-4.5 p50 `Middelvandstand` 2050 / 2100 | 24.89 / 39.44 | 24.89 / 39.44 ✓ |
| SJ7 SSP2-4.5 p50 `Stormfl100Aarsh` 2050 / 2100 | 181.74 / 196.29 | 181.74 / 196.29 ✓ |
| komkode 101 RCP4.5 p50 `Time100Aarsh` 2050 / 2100 | 51.31 / 52.73 | 51.31 / 52.73 ✓ |
| F&P rows | 98 | 98 ✓ |
| risk areas | 26 | 26 ✓ |
| designated kommuner | 51 | 51 ✓ |
| coastal stretches | 34 | 34 ✓ |

Plus: the historic baseline is 0 cm and the frequency multiplier is 1; future surge = historic
surge + sea-level rise (an internal-consistency check on Klimaatlas itself); every registry entry
has the right group, level, direction, note, source and horizons; landlocked kommuner are null
with a reason; København takes the MAX of SJ7 and SJ8; Vallensbæk is coastal on SJ8.

`make test` overall: **37 Python tests + 15 JS tests, all pass.**

## 8 · `make validate && make build`

`make validate` → exit 0, **no `✗` lines**. `make build` → exit 0, **no `⚠`**.
`dist/index.html` 4.4 MB · 99 municipalities · 606 areas · 53 indicators ·
83 climate files copied to `dist/climate/`.
`data/processed/cph.json` was again rewritten with a new `fetched` stamp only, and reverted.

### Check table — every Climate indicator, Today / 2050 / 2100

| area | Sea level cm | Surge100 cm | Surge freq × | Rain100 mm/h | Cloudbursts/yr | Claims/1000 | Risk area | Surge dw % | Cloudburst dw % | zone km² | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| København (0101) | 0 / 26.1 / 41.3 | 158.9 / 185 / 200.2 | 1 / 15.4 / 45.9 | 44.5 / 51.3 / 52.7 | 0.33 / 0.42 / 0.42 | 11 | 1 | 0.17 / — / — | — / — / — | 1.921 |  |
| Frederiksberg (0147) | — / — / — | — / — / — | — / — / — | 44.4 / 51.3 / 52.7 | 0.33 / 0.42 / 0.42 | 19 | 0 | — / — / — | — / — / — | 0 | not coastal |
| Hvidovre (0167) | 0 / 26.1 / 41.3 | 158.9 / 185 / 200.2 | 1 / 15.4 / 45.9 | 44.4 / 51.4 / 52.1 | 0.33 / 0.42 / 0.42 | 17 | 1 | 1.28 / — / — | — / — / — | 0.638 |  |
| Brøndby (0153) | 0 / 26.1 / 41.3 | 158.9 / 185 / 200.2 | 1 / 15.4 / 45.9 | 44.1 / 51.3 / 52.4 | 0.33 / 0.42 / 0.42 | 11 | 0 | 0 / — / — | — / — / — | 0.094 |  |
| Køge (0259) | 0 / 26.1 / 41.3 | 158.9 / 185 / 200.2 | 1 / 15.4 / 45.9 | 44.1 / 52.8 / 53.3 | 0.33 / 0.44 / 0.44 | 24 | 1 | 2.02 / — / — | — / — / — | 3.64 |  |
| Roskilde (0265) | 0 / 25.4 / 40.3 | 205.9 / 231.3 / 246.2 | 1 / 3.1 / 5.9 | 43.6 / 52.5 / 53.8 | 0.32 / 0.43 / 0.44 | 17 | 1 | 0.66 / — / — | — / — / — | 3.364 |  |
| Aarhus (0751) | 0 / 25 / 39.9 | 160.9 / 185.9 / 200.8 | 1 / 8.6 / 25.2 | 45 / 53.3 / 56.1 | 0.33 / 0.44 / 0.45 | 19 | 1 | 0.17 / — / — | — / — / — | 2.801 |  |
| Odense (0461) | 0 / 27.9 / 44.1 | 170.1 / 198 / 214.2 | 1 / 9.1 / 22.8 | 44.6 / 50.3 / 56.3 | 0.33 / 0.4 / 0.48 | 25 | 1 | 0.16 / — / — | — / — / — | 11.548 |  |
| Esbjerg (0561) | 0 / 31.5 / 49.4 | 488.4 / 519.9 / 537.8 | 1 / 3.9 / 6.7 | 45.8 / 56.3 / 59.2 | 0.33 / 0.47 / 0.49 | 46 | 1 | 0.12 / — / — | — / — / — | 21.924 |  |
| Vejle (0630) | 0 / 27.7 / 43.7 | 171.1 / 198.8 / 214.8 | 1 / 9.4 / 25.2 | 46 / 56.4 / 58.9 | 0.34 / 0.47 / 0.47 | 24 | 1 | 4.07 / — / — | — / — / — | 5.822 |  |
| Herning (0657) | — / — / — | — / — / — | — / — / — | 45.7 / 56 / 60.5 | 0.32 / 0.47 / 0.48 | 26 | 0 | — / — / — | — / — / — | 0 | not coastal |
| **Denmark (mean of kommuner)** | 0.00 / 27.12 / 42.87 | 194.62 / 221.60 / 237.27 | 1.00 / 12.50 / 36.12 | 44.65 / 52.61 / 55.67 | 0.33 / 0.43 / 0.45 | 29.1 | 0.5 | 1.50 / — / — | — / — / — | 1,196.0 | 80 kommuner with a zone |

Reading it: sea level is 0 today by definition and the surge level is what actually matters —
Esbjerg's 488 cm is the North Sea tide plus surge, against 159 cm in Øresund. The frequency
multiplier is the sharpest number on the page: **today's 1-in-100-year level would be reached
about 15 times as often by 2050 and 46 times as often by 2100 in Øresund**. Frederiksberg and
Herning show the landlocked case — no sea figures at all, but full rain figures. Brøndby is the
marginal risk-area case: it touches Køge Bugt/København with 0.71 km², under the 1 km² rule, so
`flood_risk_area = 0` while Køge next door is 1.

---

# v2.6 · step 2 — scope to official data only (2026-09-24)

## Removed: cloudburst zones

`cloudburst_dw_pct` is gone from `config/indicators.json` and from `data/processed/climate/index.json`. It could only ever have been filled from the DHM Bluespot_ekstremregn raster, which sits behind a Datafordeler login this repo does not hold (`docs/CLIMATE_PROBE.md` §5–6), and an indicator that can only be estimated has no place in a branch that shows published figures. **Kept:** `rain100_1h_mm`, `cloudbursts_yr` and `weather_claims_1000` — all three are published numbers, not modelled exposure. The Climate group is now eight indicators.

## Changed: coast → kommune is the longest shared coastline, not MAX

The old rule took the highest figure across every Klimaatlas stretch a kommune touched. A maximum of two published figures is a figure nobody published, so it breaks the branch's data principle. The new rule samples the kommune's coastline every 25 m, assigns each sample to its nearest stretch within 2 km, and gives the kommune the stretch holding the most samples. Every other touching stretch is kept in `other_kystkoder` for display and never combined into a number.

**42 of 77 coastal kommuner touch more than one stretch. 36 of them change at least one value; 21 change `surge100_cm`.** The rest touched several stretches that publish the same figures, so only the label moved.

| code | kommune | touched | now uses | also touches | `sealevel_cm` 2070 | `surge100_cm` today | `surge_freq_x` 2120 |
|---|---|---|---|---|---|---|---|
| 0101 | København | SJ7;SJ8 | **SJ7** | SJ8 | 26.1 → **24.9** | 158.9 → **156.8** | 45.9 → **20.5** |
| 0185 | Tårnby | SJ7;SJ8 | **SJ7** | SJ8 | 26.1 → **24.9** | 158.9 → **156.8** | 45.9 → **20.5** |
| 0217 | Helsingør | SJ4;SJ7 | **SJ4** | SJ7 | 24.9 → **22.9** | = | 20.5 → **14.2** |
| 0250 | Frederikssund | SJ5;SJ6 | **SJ6** | SJ5 | 26.1 → **25.4** | = | 13.6 → **5.9** |
| 0260 | Halsnæs | SJ4;SJ5;SJ6 | **SJ6** | SJ4;SJ5 | 26.1 → **25.4** | = | 14.2 → **5.9** |
| 0306 | Odsherred | SJ3;SJ4;SJ5 | **SJ3** | SJ5;SJ4 | = | 188.9 → **163.9** | = |
| 0326 | Kalundborg | SJ2;SJ3 | **SJ2** | SJ3 | = | = | 32.6 → **17.9** |
| 0330 | Slagelse | SD3;SD5;SJ1;SJ2 | **SD5** | SJ2;SD3;SJ1 | 28 → **27.3** | 170.1 → **162.1** | 30 → **21.7** |
| 0336 | Stevns | SD7;SJ8 | **SJ8** | SD7 | 26.7 → **26.1** | 165 → **158.9** | = |
| 0350 | Lejre | SJ5;SJ6 | **SJ6** | SJ5 | 26.1 → **25.4** | = | 13.6 → **5.9** |
| 0370 | Næstved | SD5;SD7 | **SD5** | SD7 | = | 165 → **162.1** | 30.8 → **21.7** |
| 0376 | Guldborgsund | SD4;SD5;SD6 | **SD4** | SD5;SD6 | = | 191.1 → **178.2** | = |
| 0390 | Vordingborg | SD5;SD6;SD7 | **SD7** | SD6;SD5 | 28.2 → **26.7** | 191.1 → **165** | = |
| 0410 | Middelfart | OJ6;OJ7;SD1 | **SD1** | OJ7;OJ6 | = | = | 43.1 → **30.2** |
| 0430 | Faaborg-Midtfyn | SD1;SD2 | **SD2** | SD1 | 30.5 → **29.5** | = | 30.2 → **10.5** |
| 0450 | Nyborg | SD3;SJ1 | **SD3** | SJ1 | = | 170.1 → **154.1** | = |
| 0479 | Svendborg | SD2;SD3 | **SD2** | SD3 | = | = | 30 → **10.5** |
| 0480 | Nordfyns | OJ6;SJ1 | **SJ1** | OJ6 | = | 171.1 → **170.1** | 25.2 → **22.8** |
| 0482 | Langeland | SD2;SD3;SD4 | **SD2** | SD4;SD3 | 29.6 → **29.5** | = | 30 → **10.5** |
| 0550 | Tønder | VH1;VH2 | **VH1** | VH2 | = | 488.4 → **459.4** | = |
| 0561 | Esbjerg | VH2;VH3 | **VH2** | VH3 | = | = | 6.7 → **3.5** |
| 0563 | Fanø | VH2;VH3 | **VH3** | VH2 | 31.5 → **30.8** | 488.4 → **399.4** | = |
| 0573 | Varde | VH3;VK1 | **VH3** | VK1 | = | = | 18.1 → **6.7** |
| 0607 | Fredericia | OJ6;OJ7;SD1 | **OJ7** | OJ6;SD1 | 30.5 → **29** | 186.3 → **149.2** | = |
| 0621 | Kolding | SD1;OJ7 | **SD1** | — | = | = | 43.1 → **30.2** |
| 0661 | Holstebro | VK1;LF3 | **VK1** | LF3 | = | = | 37.9 → **18.1** |
| 0665 | Lemvig | VK1;VK4;LF3 | **LF3** | VK1;VK4 | 30 → **28.5** | 298.3 → **194.2** | = |
| 0706 | Syddjurs | OJ4;OJ5 | **OJ5** | OJ4 | = | 176.8 → **160.9** | = |
| 0707 | Norddjurs | OJ2;OJ3;OJ4 | **OJ4** | OJ2;OJ3 | 24.3 → **23.9** | = | 21.9 → **16.1** |
| 0741 | Samsø | OJ5;SJ1;SJ3 | **SJ3** | OJ5;SJ1 | 27.9 → **26.1** | 170.1 → **163.9** | = |
| 0773 | Morsø | LF2;LF3;LF4 | **LF4** | LF3;LF2 | 28.5 → **25.4** | 194.2 → **166.9** | 49 → **48.2** |
| 0779 | Skive | LF2;LF3 | **LF2** | LF3 | 28.5 → **26** | 194.2 → **184** | = |
| 0787 | Thisted | VK4;VK5;LF3;LF4 | **LF4** | VK5;LF3;VK4 | 28.5 → **25.4** | 255.2 → **166.9** | = |
| 0813 | Frederikshavn | VK6;OJ1 | **OJ1** | VK6 | = | = | 34.4 → **22.8** |
| 0849 | Jammerbugt | VK5;VK6;LF1;LF4;LF2 | **LF1** | VK6;VK5;LF4 | 26 → **23.4** | 184 → **148.8** | 49 → **28.9** |
| 0851 | Aalborg | LF1;OJ1;OJ2 | **LF1** | OJ2;OJ1 | = | 160.7 → **148.8** | = |

The largest moves are where a kommune reaches around a headland into a much more exposed stretch: Thisted 255.2 → 166.9 cm, Lemvig 298.3 → 194.2, Fanø 488.4 → 399.4, Jammerbugt 184.0 → 148.8, Fredericia 186.3 → 149.2. In each case the old value came from a stretch the kommune barely touches. København moves 158.9 → 156.85 — off SJ8 (Køge Bugt) and onto SJ7 (Øresund), where almost all of its 116 km of coastline lies; SJ8 is still named in `other_kystkoder`.

`make validate` and `make build` exit 0; 40 Python + 15 JS tests pass.
