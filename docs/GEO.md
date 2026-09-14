# Boundary geometry pipeline

## Levels used

| level | file | id field | joins to |
|---|---|---|---|
| Municipality (kommune) | `data/geo/kommuner.geojson` | `kode` (4-digit, `0101`) | DST `OMRÅDE` = `kode` without leading zero (`101`) |
| Postal code (postnummer) | `data/geo/postnumre.geojson` | `nr` (`2100`) | DST `PNR20`, Finans Danmark `PNR20`; `kommuner[0]` = dominant municipality |
| Parish (sogn) | `data/geo/sogne.geojson` | `kode` (`7002`) | DST `SOGN` |
| Landsdel (NUTS3) | `data/geo/landsdele.geojson` | `nuts3` (`DK011`) | Eurostat, Finans Danmark BM010 `OMRÅDE` |

## Until 2026-10-01 — DAWA

`scripts/fetch_geo_dawa.py` pulls `https://api.dataforsyningen.dk/{kommuner,postnumre,sogne,landsdele,regioner}?format=geojson&srid=4326`. Coordinates are rounded to 5 decimals (~1 m) and optionally simplified (`--simplify 0.0005` ≈ 50 m, keeps the browser payload small; the Finnish edition carries ~220 rings inline — Denmark has ~600 postal codes and ~2,150 parishes, so simplification matters).

## After 2026-10-01 — Datafordeler

1. Create a user at Datafordeler Administration (email + password is enough for open data), an *IT-system*, and an API key (valid 2 years). Put it in `.env` as `DATAFORDELER_API_KEY`; never commit it.
2. Download DAGI *Fildownload* as GPKG (EPSG:25832).
3. Convert: `ogr2ogr -f GeoJSON -t_srs EPSG:4326 data/geo/raw/kommuner.geojson dagi.gpkg kommuneinddeling` (same for `postnummerinddeling`, `sogneinddeling`, `landsdele`).
4. Re-run the rounding/simplification step (`scripts/fetch_geo_dawa.py --from-raw`, to add).

Note Datafordeler's legacy REST/WFS and username/password access close **2027-01-15**; only API-key / OAuth access remains.

## QGIS

QGIS is handy for inspecting layers, checking that postal-code polygons nest inside municipalities, and one-off simplification (Vector → Geometry tools → Simplify), but the repo must rebuild geometry from code so a GitHub Action can refresh it. Treat QGIS as an optional review step, not part of the pipeline.

## Licence

DAGI is "frie geografiske data": free reuse and redistribution with attribution. `data/geo/ATTRIBUTION.txt` holds the required string; the dashboard's map footer shows it.
