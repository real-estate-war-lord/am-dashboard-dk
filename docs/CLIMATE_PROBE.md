# Climate endpoint probe — 2026-09-23

What every source the v2.5 climate layer would read answers today, measured by `scripts/probe_climate.py` (read-only; re-run it to refresh this file). Everything below is that run's output — no hand-written numbers.

## What it means for the layer

* **Storm surge and cloudburst statistics are ready to use.** DMI's Klimaatlas answers in under half a second, every expected figure matches, and it is already keyed the way the dashboard is — 34 coastal stretches with geometry and per-kommune precipitation — so it can drive both a coastal and an inland indicator without any raster work. It also carries its own horizons (`periode`) and scenarios (`scenarie`), which is exactly what a Today / 2050 / 2100 pill needs (§4).
* **The MST hazard rasters cannot be read as a grid over REST.** `OD_fare_2024` is a MapServer: `/exportImage` does not exist, `/export` ignores `format=tiff` and returns a rendered PNG. Depth *is* readable one point at a time through `/identify`, which covers a test-property score but not a map layer (§2).
* **The bulk drop is scriptable after all.** The Cerberus web client at sftp.statens-it.dk exposes a JSON listing and a zip route to a plain HTTP client — 8 files, 3.49 GB, with `Oversvømmelsesfare.zip` (3.41 GB) holding the depth rasters (§3).
* **`OD_fare_2024` never states its climate basis.** No layer or service description mentions present-day or future climate or a sea-level-rise allowance. The Kystdirektoratet service next to it does, and names 2020 / 2070 / 2120 (§2).
* **Two sources are blocked on credentials.** The DHM WCS and the bluespot tiles both need a Datafordeler key or service user, and `.env` carries only `UDDSTAT_API_KEY` (§5, §6). Nothing else waits on this.
* **The coast question is already answerable offline** from the boundaries the repo vendors — 76 of 99 kommuner are coastal, 9 of the metro 19 (§8).

## Summary

| name | HTTP | seconds | bytes | note |
|---|---|---|---|---|
| 1a MST risk MapServer | 200 | 0.11 | 17,757 | 42 layers |
| 1b risk layer 33 (4326) | 200 | 7.87 | 11,381,076 | 1 features |
| 1c risk layer 33 (25832) | 200 | 1.25 | 4,877,985 | 101.53 km² |
| 2a MST hazard MapServer | 200 | 0.11 | 5,093 | 15 layers |
| 2b hazard layer 21 | 200 | 0.15 | 2,241 | Hav_Fare_100år |
| 2b2 layer 21 metadata XML | 200 | 0.13 | 5,655 | H100_DK_KOR.tif |
| 2c hazard /exportImage | 400 | 0.10 | 655 | 400 Error: Invalid URL ArcGIS REST Framework |
| 2c hazard /export | 200 | 0.12 | 2,133 | PNG RGBA uint8 — rendered, not raw |
| 2d hazard /identify | 200 | 0.14 | 156 | {'Classify.Pixel Value': '1.612748', 'Classify.Cla |
| 3a MST bulk folder page | 200 | 0.10 | 7,105 | Cerberus Web Client · csrftoken yes |
| 3b bulk get_dir (listing) | 200 | 0.10 | 2,387 | 8 entries |
| 3c bulk zip/Farveskala.zip | 206 | 0.03 | 2,048 | real ZIP bytes |
| 4a Klimaatlas coast service | 200 | 0.34 | 3,290 | 2 layers / 0 tables |
| 4b coast SJ7 p50 | 200 | 0.27 | 12,051 | 16 rows |
| 4c precip kom 101 p50 | 200 | 0.35 | 15,404 | 10 rows |
| 4d distinct kystkode | 200 | 0.56 | 1,525 | 34 stretches |
| 5a DHM WCS GetCapabilities | 401 | 0.13 | 0 | NO API KEY in .env |
| 6 Datafordeler selfservice | 200 | 0.18 | 2,134 | selfservice.datafordeler.dk |
| 6 Datafordeler API root | 401 | 1.13 | 0 | api.datafordeler.dk |
| 6 Datafordeler DHM Fildownload (Raster)  | 200 | 0.17 | 34,237 | datafordeler.dk |
| 6 Dataforsyningen download (legacy) | ERR | 0.00 | 0 | host does not resolve |
| 6 Dataforsyningen FTP (legacy) | ERR | 0.03 | 0 | connection refused / no route |
| 6 Kortforsyningen FTP (legacy) | ERR | 0.00 | 0 | host does not resolve |
| 6 Dataforsyningen API (legacy) | 404 | 0.11 | 604 | api.dataforsyningen.dk |
| 7a F&P TUJ9b index | 200 | 0.10 | 239 | follow to latest version |
| 7b F&P TUJ9b dataset.csv | 200 | 0.11 | 1,566 | v4 · 98 data rows |
| 7a F&P z0zEO index | 200 | 0.26 | 239 | follow to latest version |
| 7b F&P z0zEO dataset.csv | 200 | 0.09 | 1,433 | v4 · 98 data rows |
| 8 coastal kommuner (local) | — | 2.61 | 0 | 76/99 coastal |
| 9a KDI Kystplanlægger service | 200 | 0.10 | 8,533 | 27 layers · Map,Query,Data |
| 9b KDI extent polygons | 200 | 0.15 | 12 | 42 polygons |
| 9c KDI polygons as geojson | 200 | 4.38 | 7,897,845 | 5 feats, 7.9 MB |
| 9d KDI depth as tiff | 200 | 0.30 | 1,326 | PNG — rendered |
| 9e identify Copenhagen Sydhavn | 200 | — | — | NoData / NoData / NoData |
| 9e identify Hvidovre Avedøre H | 200 | — | — | NoData / NoData / NoData |
| 9e identify Køge harbour | 200 | — | — | 0.122646 / 0.371910 / 0.964475 |

## Expected values

| check | got | expected | |
|---|---|---|---|
| group 16 sub-layers (risk areas) | 26 | 25 | ✗ |
| layer 33 area km² (EPSG:25832) | 101.5 | 101.5 | ✓ |
| SJ7 scen 0 per 1 Stormfl100Aarsh | 156.85 | 156.85 | ✓ |
| SJ7 scen 245 per 3 Middelvandstand | 24.89 | 24.89 | ✓ |
| SJ7 scen 245 per 3 Stormfl100Aarsh | 181.74 | 181.74 | ✓ |
| SJ7 scen 245 per 4 Middelvandstand | 39.44 | 39.44 | ✓ |
| SJ7 scen 245 per 4 Stormfl100Aarsh | 196.29 | 196.29 | ✓ |
| kom 101 scen 45 per 3 Time100Aarsh | 51.31 | 51.3 | ✓ |
| kom 101 scen 45 per 4 Time100Aarsh | 52.73 | 52.73 | ✓ |
| coastal stretches with geometry (Kystinddeling) | 34 | 34 | ✓ |
| F&P TUJ9b row count ≈ 98 | 98 | 98 | ✓ |
| F&P z0zEO row count ≈ 98 | 98 | 98 | ✓ |

**11/12 pass.**

## 1 · MST risk areas — OD_risikoomraader_2024

`OD_risikoomraader_2024` · 42 layers, 0 tables · spatialReference 3044

| id | name | type | parent | sub-layers |
|---|---|---|---|---|
| 16 | Risikoområder 2024 | Group Layer |  | 26 |
| 17 | Risikoområde Aarhus | Feature Layer | 16 | 0 |
| 18 | Risikoområde Aabenraa | Feature Layer | 16 | 0 |
| 19 | Risikoområde Vordingborg | Feature Layer | 16 | 0 |
| 20 | Risikoområde Vejle | Feature Layer | 16 | 0 |
| 21 | Risikoområde Vestlig Limfjord | Feature Layer | 16 | 0 |
| 46 | Risikoområde Skærbæk/Fredericia | Feature Layer | 16 | 0 |
| 23 | Risikoområde Sydlolland | Feature Layer | 16 | 0 |
| 24 | Risikoområde Roskildefjord | Feature Layer | 16 | 0 |
| 25 | Risikoområde Rømø | Feature Layer | 16 | 0 |
| 26 | Risikoområde RandersFjord | Feature Layer | 16 | 0 |
| 27 | Risikoområde Østlig Limfjord | Feature Layer | 16 | 0 |
| 28 | Risikoområde OdenseFjord | Feature Layer | 16 | 0 |
| 29 | Risikoområde Nyborg | Feature Layer | 16 | 0 |
| 30 | Risikoområde MariagerFjord | Feature Layer | 16 | 0 |
| 32 | Risikoområde Kolding | Feature Layer | 16 | 0 |
| 52 | Risikoområde Korsør | Feature Layer | 16 | 0 |
| 33 | Risikoområde Køge Bugt/København | Feature Layer | 16 | 0 |
| 34 | Risikoområde Juelsminde | Feature Layer | 16 | 0 |
| 35 | Risikoområde Horsens | Feature Layer | 16 | 0 |
| 36 | Risikoområde Holstebro | Feature Layer | 16 | 0 |
| 37 | Risikoområde Hjerting | Feature Layer | 16 | 0 |
| 38 | Risikoområde Himmelbjergsøerne | Feature Layer | 16 | 0 |
| 39 | Risikoområde Gråsten | Feature Layer | 16 | 0 |
| 40 | Risikoområde Grenaa | Feature Layer | 16 | 0 |
| 41 | Risikoområde Fanø/Esbjerg | Feature Layer | 16 | 0 |
| 42 | Risikoområde Arresø | Feature Layer | 16 | 0 |
| 0 | Risikoområder 2018 | Group Layer |  | 14 |
| 1 | Risikoområde Aabenraa | Feature Layer | 0 | 0 |
| 2 | Risikoområde Vordingborg | Feature Layer | 0 | 0 |
| 3 | Risikoområde Vejle | Feature Layer | 0 | 0 |
| 4 | Risikoområde Sydlolland | Feature Layer | 0 | 0 |
| 5 | Risikoområde Randers Fjord | Feature Layer | 0 | 0 |
| 6 | Risikoområde Odense Fjord | Feature Layer | 0 | 0 |
| 7 | Risikoområde Nyborg | Feature Layer | 0 | 0 |
| 8 | Risikoområde Korsør | Feature Layer | 0 | 0 |
| 10 | Risikoområde Kolding | Feature Layer | 0 | 0 |
| 11 | Risikoområde Køge Bugt/København | Feature Layer | 0 | 0 |
| 12 | Risikoområde Juelsminde | Feature Layer | 0 | 0 |
| 13 | Risikoområde Holstebro | Feature Layer | 0 | 0 |
| 14 | Risikoområde Fredericia | Feature Layer | 0 | 0 |
| 15 | Risikoområde Esbjerg | Feature Layer | 0 | 0 |

Group **16 · Risikoområder 2024** holds **26** sub-layers (ids 17–52), each a single risk area: Aabenraa, Aarhus, Arresø, Fanø/Esbjerg, Grenaa, Gråsten, Himmelbjergsøerne, Hjerting, Holstebro, Horsens, Juelsminde, Kolding, Korsør, Køge Bugt/København, MariagerFjord, Nyborg, OdenseFjord, RandersFjord, Roskildefjord, Rømø, Skærbæk/Fredericia, Sydlolland, Vejle, Vestlig Limfjord, Vordingborg, Østlig Limfjord.

Layer 33 returns **1 features** (EPSG:4326 geojson, 11,381,076 bytes).

Layer 33 attributes: `OBJECTID`, `Shape_Length`, `Shape_Area`

First feature: OBJECTID=1, Shape_Length=1941970.8690389255, Shape_Area=101528735.36470653

Dissolved area in EPSG:25832: **101.53 km²** (expected ≈ 101.5).

## 2 · MST hazard rasters — OD_fare_2024

`OD_fare_2024` · 15 layers · capabilities `Map,Query,Data` · image formats `PNG32,PNG24,PNG,JPG,DIB,TIFF,EMF,PS,PDF,GIF,SVG,SVGZ,BMP`

| id | name | type | parent |
|---|---|---|---|
| 2 | Hav | Group Layer |  |
| 22 | Hav_Fare_10år | Raster Layer | 2 |
| 24 | Hav_Fare_20år | Raster Layer | 2 |
| 27 | Hav_Fare_50år | Raster Layer | 2 |
| 21 | Hav_Fare_100år | Raster Layer | 2 |
| 23 | Hav_Fare_200år | Raster Layer | 2 |
| 26 | Hav_Fare_500år | Raster Layer | 2 |
| 20 | Hav_Fare_1000år | Raster Layer | 2 |
| 25 | Hav_Fare_5000år | Raster Layer | 2 |
| 19 | Hav_Fare_10000år | Raster Layer | 2 |
| 3 | Vandløb | Group Layer |  |
| 28 | Vandløb_Fare_10år | Raster Layer | 3 |
| 29 | Vandløb_Fare_20år | Raster Layer | 3 |
| 30 | Vandløb_Fare_50år | Raster Layer | 3 |
| 31 | Vandløb_Fare_100år | Raster Layer | 3 |

Two group layers — **Hav** (sea, 9 return periods from 10 to 10 000 years) and **Vandløb** (watercourse, 10–100 years). Every leaf is a *Raster Layer*.

### Layer 21 — Hav_Fare_100år

* type `Raster Layer` · capabilities `Map,Query`
* `description` and `copyrightText` are both empty
* `pixelSizeX` = absent — a MapServer raster layer does not publish it
* `pixelSizeY` = absent — a MapServer raster layer does not publish it
* `minScale` = 0
* `maxScale` = 0
* extent (EPSG:3044): 441,585 – 893,020 E, 6,049,785 – 6,402,300 N (451 × 353 km — all of Denmark)
* source raster, from the layer's ISO record: **`H100_DK_KOR.tif`**

### exportImage — 500 × 500 m box in Copenhagen harbour

Centre 55.68, 12.599 → 726,259 E, 6,176,338 N in EPSG:3044; `bbox=726008.7,6176087.5,726508.7,6176587.5`, `size=250,250` (2 m pixels), `format=tiff`, `pixelType=F32`, `layers=show:21`.

* `/exportImage` → HTTP 400, 655 bytes, `text/html; charset=utf-8` — rejected — `Error: Invalid URL ArcGIS REST Framework Home Error: Invalid URL Code: 400`
* `/export` → HTTP 200, 2,133 bytes, `(none)` — **PNG, not TIFF** — mode `RGBA`, 250×250, dtype uint8. The `format=tiff` and `pixelType=F32` parameters are ignored: this is a rendered, symbolised picture, so **no raw depth values come back**.

* 9.8% of a 2 × 2 km render around the harbour is painted; `/identify` below is aimed at one of those pixels (726,964 E, 6,176,093 N).

`/identify` at that pixel returns `{'Classify.Pixel Value': '1.612748', 'Classify.Class value': '3'}` — **`Classify.Pixel Value` is the modelled flood depth in metres (1.612748 m — the service formats numbers in da-DK, so the decimal separator is a comma), not a class index**; `Classify.Class value` is the renderer's bin alongside it.

**Verdict:** `OD_fare_2024` is a *MapServer*, not an *ImageServer*. `/exportImage` does not exist on it (HTTP 400) and `/export` ignores `format=tiff` and `pixelType=F32`, returning a rendered PNG — **no depth grid comes back over REST**. Raw depth *is* readable one point at a time through `/identify`, which is enough to score a single test property but not to build a layer. For the layer, the depth rasters have to come from the bulk drop in §3 (`Oversvømmelsesfare.zip`, 3.41 GB).

### Climate basis, as the services state it

* **`OD_fare_2024`** — “Fare for oversvømmelse fra hav og vandløb til OD 2022-2027 plantrin 1. Opdateret 21-05-2025 af Morten Uldal Hansen”
* **`OD_Vandstand_Støttepunkter`** — “Støttepunkter som er brugt til at beregne oversvømmelse til OD plantrin 1 2022-2027. Oprettede af Morten Uldal”
* **`Forslaaet_Scenarier`** — “Forslået scenariere for oversvømmlese KBH. Publisheret af Morten U”
* **`Kystplanlaegger_Oversvommelsesfare_2`** — “Viser oversvømmesesfare og oversvømmelsesdybde i 2020, 2070 og 2120 for en 100, 1.000 og 10.000 års hændelse.”
* **`Kystplanlaegger_Oversvommelsesskade`** — “Total økonomiskskade for oversvømmelse i 2020, 2070 og 2120. Skaden er beregnet for en 100, 1.000 og 10.000 års hændelse. Publisheret af Morten U”
* **`Kystplanlaegger_Erosionsskade`** — “Total økonomiskskade for erosion i 2020, 2070 og 2120. Skaden er beregnet for en 100, 1.000 og 10.000 års hændelse. Publisheret af Morten U”
* **`Kystplanlaegger_Strategiforslag`** — “Strategiforslag for reduktion af oversvømmelse og erosion i 2020, 2070 og 2120. Publisheret af Morten U”

Read together: **`OD_fare_2024` never states a climate basis.** Its own item info says only *“Fare for oversvømmelse fra hav og vandløb til OD 2022-2027 plantrin 1”* — “Flood hazard from sea and watercourse for the flood-directive cycle 2022-2027, planning step 1” — with no mention of *nutidigt* (present-day) or *fremtidigt* (future) climate and no sea-level rise (*havspejlsstigning*) allowance. The EU-flood-directive hazard maps are present-climate maps by construction, but this service does not say so, so the dashboard must not claim a horizon for them.

The neighbouring Kystdirektoratet service is the one that does state horizons: **`Kystplanlaegger_Oversvommelsesfare_2`** — *“Viser oversvømmesesfare og oversvømmelsesdybde i 2020, 2070 og 2120 for en 100, 1.000 og 10.000 års hændelse.”* — “Shows flood hazard and flood depth in 2020, 2070 and 2120 for a 100-, 1 000- and 10 000-year event.” That is a present-day plus two future horizons, i.e. the sea-level-rise allowance sits in the 2070/2120 layers. It is the better fit for a Today / 2050 / 2100 horizon pill than `OD_fare_2024`, and it is worth probing in its own right before the layer is designed.

## 3 · MST bulk drop (Plantrin 1 National data 2024)

`GET https://sftp.statens-it.dk/public/folder/sudeyofd-echpkegqfxhbg/` → HTTP 200, 7,105 bytes — `Cerberus Web Client`. The HTML carries no file names; the listing is a DataTables ajax source.

`POST /public/op/sudeyofd-echpkegqfxhbg/get_dir` (form: `cd=/`, `csrftoken`, DataTables paging) returns the listing as JSON — **8 files, 3.49 GB in total**:

| file | size | MB | modified |
|---|---|---|---|
| `Oversvømmelsesfare.zip` | 3,410,619,711 | 3,410.6 | 2024-08-20 |
| `Økonomiskskade_Risiko.zip` | 53,100,998 | 53.1 | 2024-08-20 |
| `Social_Sarbarheds_Index.zip` | 15,736,762 | 15.7 | 2024-08-20 |
| `Risikoområder.zip` | 5,208,909 | 5.2 | 2024-09-08 |
| `Oversvømmede_personer.zip` | 1,488,185 | 1.5 | 2024-08-20 |
| `SocialRisiko_Konsekvens.zip` | 1,197,725 | 1.2 | 2024-08-20 |
| `SocialRisiko_Årsag.zip` | 632,864 | 0.6 | 2024-08-20 |
| `Farveskala.zip` | 28,748 | 0.0 | 2024-08-22 |

`POST /public/op/sudeyofd-echpkegqfxhbg/zip/<name>.zip` (form: `cd`, one `ID` per selected file, `zipname`, `csrftoken`) streams the files back. Probed with a `Range: bytes=0-2047` on `Farveskala.zip` → HTTP 206, first bytes `b'PK\x03\x04'` — a real ZIP. **The drop is scriptable; no browser needed.**

## 4 · DMI Klimaatlas (ArcGIS Online)

| id | name | kind | geometry |
|---|---|---|---|
| 0 | VandstandStormflodKyst | Feature Layer | esriGeometryPoint |
| 1 | Kystinddeling | Feature Layer | esriGeometryPolygon |

`kystkode='SJ7'` p50 → **16 rows**; fields: `OBJECTID`, `coastid`, `kystnavn`, `kystkode`, `percentil`, `scenarie`, `aarstid`, `periode`, `absolutaendring`, `Middelvandstand`, `Stormfl20Aarsh`, `Stormfl50Aarsh`, `Stormfl100Aarsh`, `Vandst1Aarsh`, `Vandst5Aarsh`, `StormflNuvaerende20Aarsh`, `StormflNuvaerende100Aarsh`, `version`

| scenarie | periode | field | got | expected |
|---|---|---|---|---|
| 0 | 1 | Stormfl100Aarsh | 156.85 | 156.85 ✓ |
| 245 | 3 | Middelvandstand | 24.89 | 24.89 ✓ |
| 245 | 3 | Stormfl100Aarsh | 181.74 | 181.74 ✓ |
| 245 | 4 | Middelvandstand | 39.44 | 39.44 ✓ |
| 245 | 4 | Stormfl100Aarsh | 196.29 | 196.29 ✓ |

`komkode=101` p50 → **10 rows**; fields: `OBJECTID`, `komnavn`, `region`, `komkode`, `percentil`, `scenarie`, `aarstid`, `periode`, `absolutaendring`, `Gennemsnitsnedboer`, `MaksimalDoegn`, `Maksimal5Doegn`, `Maksimal14Doegn`, `Doegn10mm`, `Doegn20mm`, `Skybrud`, `ToerreDage`, `ToerreperioderMaks`, `VaadeAar`, `SnefaldDage`, `Time2Aarsh`, `Time5Aarsh`, `Time10Aarsh`, `Time20Aarsh`, `Time50Aarsh`, `Time100Aarsh`, `Doegn2Aarsh`, `Doegn5Aarsh`, `Doegn10Aarsh`, `Doegn20Aarsh`, `Doegn50Aarsh`, `Doegn100Aarsh`, `version`

| scenarie | periode | field | got | expected |
|---|---|---|---|---|
| 45 | 3 | Time100Aarsh | 51.31 | 51.3 | ✓ |
| 45 | 4 | Time100Aarsh | 52.73 | 52.73 | ✓ |

Distinct `kystkode` values on the value layer: **34** — LF1, LF2, LF3, LF4, OJ1, OJ2, OJ3, OJ4, OJ5, OJ6, OJ7, SD1, SD2, SD3, SD4, SD5, SD6, SD7, SJ1, SJ2, SJ3, SJ4, SJ5, SJ6, SJ7, SJ8, SJ9, VH1, VH2, VH3, VK1, VK4, VK5, VK6
* layer 0 `VandstandStormflodKyst` · esriGeometryPoint · 3162 features
* layer 1 `Kystinddeling` · esriGeometryPolygon · 34 features

## 5 · Datafordeler DHM (WCS)

**No `DATAFORDELER_API_KEY` in `.env`** — the only key the repo carries is `UDDSTAT_API_KEY`. The BBR pull in `scripts/fetch_bbr.py` reads `DATAFORDELER_API_KEY` (or `DATAFORDELER_USER`/`DATAFORDELER_PASS`), so the existing BBR cache was fetched with a key that is no longer on disk. Probed unauthenticated to record what the service answers.

`GET https://wcs.datafordeler.dk/DHMNedboer/dhm_wcs/1.0.0/WCS?service=WCS&request=GetCapabilities` → HTTP 401, 0 bytes

**HTTP 401 with an empty body** — the endpoint is alive and simply refuses an unauthenticated caller, so the coverage list (terrain? bluespot?) cannot be read from here. Same blocker as §6.

GetCoverage not attempted: it needs the same key.

## 6 · Bluespot (ekstremregn) raster — download route

Every candidate route, probed with a plain GET (redirects followed):

* **Datafordeler selfservice** — `https://selfservice.datafordeler.dk/` → HTTP 200, 2,134 bytes, `text/html; charset=utf-8`
* **Datafordeler API root** — `https://api.datafordeler.dk/` → HTTP 401, 0 bytes, `(none)`
* **Datafordeler DHM Fildownload (Raster) product page** — `https://datafordeler.dk/dataoversigt/danmarks-hoejdemodel-dhm/dhm-fildownload-raster/` → HTTP 200, 34,237 bytes, `text/html; charset=utf-8` — `DHM Fildownload (Raster) | Datafordeler`
* **Dataforsyningen download (legacy)** — `https://download.dataforsyningen.dk/` → **host does not resolve / refuses the connection**
* **Dataforsyningen FTP (legacy)** — `https://ftp.dataforsyningen.dk/` → **host does not resolve / refuses the connection**
* **Kortforsyningen FTP (legacy)** — `https://ftp.kortforsyningen.dk/` → **host does not resolve / refuses the connection**
* **Dataforsyningen API (legacy)** — `https://api.dataforsyningen.dk/` → HTTP 404, 604 bytes, `text/html` — `Dataforsyningen API Gateway`

### Where the product lives now

* The product is **DHM/Bluespot_ekstremregn** — how much rain has to fall before a given depression (a *bluespot*) fills and floods — published as **10 × 10 km GeoTIFF tiles on the Danish square grid (DDKN)**, alongside `Terraen`, `Overflade`, `Bluespot2007`, `Terraen2015` and `Overflade2015`.
* The two legacy hosts named in the Dataforsyningen closure note — `ftp.dataforsyningen.dk` and `download.dataforsyningen.dk` — **no longer resolve**, so that route is gone.
* The live route is **Datafordeler**: the pre-generated raster file downloads are pulled through Datafordeler's REST API / *Fildownload*, and the older *Filudtræk (DHM)* is being retired — its own documentation says to move to *Fildownload på Datafordeleren* after **15 January 2027**.
* Both need credentials: the raster file download wants an **API key** from an IT-system on Datafordeler Administration, and Filudtræk wants a **service user (username + password)**. `api.datafordeler.dk` answers **401** unauthenticated, which matches.
* **Blocker for this branch:** the repo has no Datafordeler credentials (`.env` holds only `UDDSTAT_API_KEY`), so neither the bluespot tiles nor the DHM WCS in §5 can be fetched until a key is put back. Nothing else in the climate layer is blocked on it.

### Tile arithmetic (DDKN 10 km)

A DDKN 10 km tile is named `10km_<N>_<E>` after the kilometre-grid index of its south-west corner in EPSG:25832 (e.g. `10km_617_72` covers Copenhagen). Counted by intersecting the vendored kommune polygons with that grid:

* **653** tiles cover all 99 kommuner (Denmark)
* **19** tiles cover the 19 metro kommuner

At the 0.4 m DHM resolution a 10 km tile is 25 000 × 25 000 px = 2.5 GB raw as float32; published bluespot tiles compress far below that because most of the raster is no-data. Taking 150–400 MB per tile as the working range: **3–8 GB for the metro 19** and **98–261 GB for Denmark**. One real tile has to be measured before either number is trusted — which needs the credentials above.

Metro tiles: `10km_616_69`, `10km_616_70`, `10km_616_71`, `10km_616_72`, `10km_616_73`, `10km_616_74`, `10km_617_69`, `10km_617_70`, `10km_617_71`, `10km_617_72`, `10km_617_73`, `10km_617_74`, `10km_618_70`, `10km_618_71`, `10km_618_72`, `10km_618_73`, `10km_619_70`, `10km_619_71`, `10km_619_72`

## 7 · Forsikring & Pension — realised weather damage

### `TUJ9b` → version 4 · 98 data rows · separator `,`

`https://datawrapper.dwcdn.net/TUJ9b/4/dataset.csv`

```
komnavn,antal
 Aabenraa ,1582
 Aalborg ,5111
 Albertslund ,190
 Allerød ,514
 Assens ,1176
… (98 data rows total)
```

Join key is the kommune **name** (`komnavn`), padded with spaces and with no kommune code — it has to be trimmed and matched against `data/geo/kommuner.geojson` names before it can be indexed by code, and 98 rows against 98 kommuner means the split kommuner need checking.

### `z0zEO` → version 4 · 98 data rows · separator `,`

`https://datawrapper.dwcdn.net/z0zEO/4/dataset.csv`

```
komnavn,antal skader pr 1000 indbygger
 Aabenraa ,27
 Aalborg ,23
 Albertslund ,7
 Allerød ,20
 Assens ,29
… (98 data rows total)
```

Join key is the kommune **name** (`komnavn`), padded with spaces and with no kommune code — it has to be trimmed and matched against `data/geo/kommuner.geojson` names before it can be indexed by code, and 98 rows against 98 kommuner means the split kommuner need checking.

## 8 · Coastal kommuner (from the vendored boundaries)

Method: take the 99 kommune polygons from `data/geo/kommuner.geojson` — the same land mask `scripts/fetch_geo_dawa.py` clips the postal codes to — reproject them to EPSG:25832, and subtract every neighbour's boundary (60 m tolerance, which absorbs the sliver left by the 0.0005° simplification). What is left of a kommune's own boundary is coast; over 1,000 m of it makes the kommune coastal.

**76 of 99 kommuner are coastal**, 23 landlocked.

Landlocked (23): Albertslund (0165), Allerød (0201), Ballerup (0151), Billund (0530), Egedal (0240), Favrskov (0710), Frederiksberg (0147), Furesø (0190), Gladsaxe (0159), Glostrup (0161), Herlev (0163), Herning (0657), Hillerød (0219), Høje-Taastrup (0169), Ikast-Brande (0756), Rebild (0840), Ringsted (0329), Rødovre (0175), Silkeborg (0740), Skanderborg (0746), Sorø (0340), Vallensbæk (0187), Vejen (0575)

Of the 19 metro kommuner (`scripts/fetch_bbr.py: METRO`), **9 are coastal**; landlocked: Frederiksberg (0147), Ballerup (0151), Gladsaxe (0159), Glostrup (0161), Herlev (0163), Albertslund (0165), Høje-Taastrup (0169), Rødovre (0175), Vallensbæk (0187), Furesø (0190).

| code | metro kommune | free boundary (km) | coastal |
|---|---|---|---|
| 0101 | København | 115.7 | yes |
| 0147 | Frederiksberg | 0.1 | no |
| 0151 | Ballerup | 0.0 | no |
| 0153 | Brøndby | 3.0 | yes |
| 0155 | Dragør | 17.4 | yes |
| 0157 | Gentofte | 11.3 | yes |
| 0159 | Gladsaxe | 0.0 | no |
| 0161 | Glostrup | 0.0 | no |
| 0163 | Herlev | 0.0 | no |
| 0165 | Albertslund | 0.0 | no |
| 0167 | Hvidovre | 10.3 | yes |
| 0169 | Høje-Taastrup | 0.0 | no |
| 0173 | Lyngby-Taarbæk | 3.6 | yes |
| 0175 | Rødovre | 0.0 | no |
| 0183 | Ishøj | 3.7 | yes |
| 0185 | Tårnby | 90.4 | yes |
| 0187 | Vallensbæk | 0.4 | no |
| 0190 | Furesø | 0.0 | no |
| 0230 | Rudersdal | 7.6 | yes |

Borderline (under 4 km of free boundary — check these by eye before using the flag as a filter): Frederiksberg 0.1 km, Vallensbæk 0.4 km, Brøndby 3.0 km, Lyngby-Taarbæk 3.6 km, Ishøj 3.7 km.

Longest coastlines: Vordingborg 360 km, Guldborgsund 306 km, Lolland 294 km, Thisted 245 km, Sønderborg 245 km, Ringkøbing-Skjern 223 km, Aalborg 212 km, Slagelse 204 km, Skive 194 km, Morsø 187 km

## 9 · Kystdirektoratet Kystplanlægger — flood hazard at 2020 / 2070 / 2120

`Kystplanlaegger_Oversvommelsesfare_2` · **27 layers** · capabilities `Map,Query,Data` · full extent EPSG:25832 441,000–894,000 E, 6,049,000–6,403,000 N

Three horizon groups × four return periods × two representations:

| horizon | return period | extent polygon (Feature Layer) | depth raster (Raster Layer) |
|---|---|---|---|
| 2020 | 50 yr | 1 | 2 |
| 2020 | 100 yr | 3 | 4 |
| 2020 | 1.000 yr | 5 | 6 |
| 2020 | 10.000 yr | 7 | 8 |
| 2070 | 50 yr | 10 | 11 |
| 2070 | 100 yr | 12 | 13 |
| 2070 | 1.000 yr | 14 | 15 |
| 2070 | 10.000 yr | 16 | 17 |
| 2120 | 50 yr | 19 | 20 |
| 2120 | 100 yr | 21 | 22 |
| 2120 | 1.000 yr | 23 | 24 |
| 2120 | 10.000 yr | 25 | 26 |

### Coverage — national, not a few stretches

The 2020 · 100-year extent layer holds **42 polygons** spanning 441,503–893,022 E and 6,049,784–6,402,264 N in EPSG:25832 — the full width and height of Denmark, unlike `OD_fare_2024`, which only covers the designated flood-directive risk areas. Rendered coverage at six points, as the painted share of a 2 × 2 km box:

| point | KDI 2020 | KDI 2070 | KDI 2120 | MST OD 100 yr |
|---|---|---|---|---|
| Copenhagen Sydhavn | 51.4 % | 78.8 % | 85.5 % | 1.9 % |
| Hvidovre Avedøre Holme | 33.1 % | 39.2 % | 43.8 % | 0.0 % |
| Køge harbour | 43.0 % | 59.4 % | 67.2 % | 8.8 % |
| Esbjerg | 36.2 % | 45.8 % | 47.4 % | 15.4 % |
| Aalborg | 30.5 % | 38.4 % | 49.2 % | 7.9 % |
| Aarhus | 38.3 % | 50.1 % | 59.9 % | 1.7 % |

### Raster or vector, and what can be downloaded

* **Extent polygons are downloadable.** `capabilities` includes `Data`, so `/3/query?f=geojson&outSR=4326` returns real geometry — 5 features came back as 7.9 MB, so all 42 polygons are a large but fetchable pull, paginated with `resultOffset`. Attributes are geometry bookkeeping only (`OBJECTID`, `Id`, `Shape_Leng`, `InPoly_FID`, `SimPgnFlag`, `MaxSimpTol`) — **no depth, no water level, no scenario field**: the horizon and return period live in the *layer*, not in the data.
* **Depth rasters are not downloadable here.** Same MapServer limit as `OD_fare_2024`: `format=tiff&pixelType=F32` comes back as PNG. There is no ImageServer, WCS or bulk/ZIP route on this server; the only per-pixel read is `/identify`, one point per request.
* Sibling services in the same folder (`Kystplanlaegger_*`, 13 of them, plus 15 `KDI_*`) carry the same 2020/2070/2120 structure for damage and strategy: `Kystplanlaegger_Oversvommelsesskade`, `Kystplanlaegger_Erosionsfare`, `Kystplanlaegger_Erosionsskade`, `Kystplanlaegger_Oversvommesesrisiko`, `Kystplanlaegger_Strategiforslag`.

### Stated climate basis

> Viser oversvømmesesfare og oversvømmelsesdybde i 2020, 2070 og 2120 for en 100, 1.000 og 10.000 års hændelse.

> *Shows flood hazard and flood depth in 2020, 2070 and 2120 for a 100-, 1 000- and 10 000-year event.*

That is the whole of it: the service names **three horizons — 2020, 2070 and 2120 — and states no scenario, no percentile and no sea-level-rise figure**. It does not say which RCP/SSP pathway the 2070 and 2120 layers assume, so the rise is baked in and unlabelled. Klimaatlas (§4), by contrast, publishes the rise itself with an explicit `scenarie` and `percentil` — which is why the indicators should be built on Klimaatlas and this service kept as the map-side illustration.

### `/identify` depth, 100-year event (metres; the service formats in da-DK)

| point | KDI 2020 | KDI 2070 | KDI 2120 | MST OD 100 yr | nearest painted KDI-2020 cell |
|---|---|---|---|---|---|
| Copenhagen Sydhavn (55.65, 12.545) | NoData | NoData | NoData | NoData | 0.187538 m at 156 m |
| Hvidovre Avedøre Holme (55.625, 12.46) | NoData | NoData | NoData | NoData | 0.431653 m at 663 m |
| Køge harbour (55.455, 12.195) | 0.122646 | 0.371910 | 0.964475 | NoData | 0.378921 m at 1,020 m |

`NoData` is a real answer — the cell is dry at that return period, not missing. Køge harbour shows the horizon effect cleanly, and the nearest-painted-cell column shows how sharp the edge is: a point can be dry while a cell 150 m away carries 0.2 m. **A point-in-raster read is therefore not a safe property score on its own** — a small ring around the pin has to be sampled. `OD_fare_2024` is `NoData` at all three, which is the coverage difference above, not a contradiction.

**Not built on yet** — this section is reconnaissance for a later step.

