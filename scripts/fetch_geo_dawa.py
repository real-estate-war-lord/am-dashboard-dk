#!/usr/bin/env python3
"""Vendor DAGI boundary polygons from DAWA as GeoJSON (WGS84).

RUN THIS BEFORE 2026-10-01 10:00 — Klimadatastyrelsen closes DAWA entirely
on that date. Afterwards use Datafordeler DAGI Fildownload (GPKG) and
`ogr2ogr -t_srs EPSG:4326 -f GeoJSON` instead (see docs/GEO.md).

Output: data/geo/raw/<layer>.geojson (untouched) and
        data/geo/<layer>.geojson (coordinates rounded to 5 decimals, optional
        simplification if shapely is installed).

Licence: "Vilkår for brug af frie geografiske data" (Klimadatastyrelsen) —
free reuse and redistribution with attribution. Attribution string written to
data/geo/ATTRIBUTION.txt.

Usage:  python scripts/fetch_geo_dawa.py [--simplify 0.0005]
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.request

BASE = "https://api.dataforsyningen.dk"
LAYERS = {
    # layer name : (DAWA path, property keys to keep)
    "kommuner": ("/kommuner", ["kode", "navn", "regionskode"]),
    "postnumre": ("/postnumre", ["nr", "navn", "kommuner"]),
    "sogne": ("/sogne", ["kode", "navn"]),
    "landsdele": ("/landsdele", ["nuts3", "navn"]),
    "regioner": ("/regioner", ["kode", "navn"]),
}
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo"


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "am-dashboard-dk/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def round_coords(obj, nd=5):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(obj[0], nd), round(obj[1], nd)]
        return [round_coords(x, nd) for x in obj]
    return obj


def simplify_feature(feat, tol):
    try:
        from shapely.geometry import shape, mapping
    except ImportError:
        return feat
    geom = shape(feat["geometry"]).simplify(tol, preserve_topology=True)
    feat["geometry"] = mapping(geom)
    return feat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simplify", type=float, default=0.0,
                    help="Douglas-Peucker tolerance in degrees (~0.0005 ≈ 50 m). Needs shapely.")
    args = ap.parse_args()

    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    for name, (path, keep) in LAYERS.items():
        url = f"{BASE}{path}?format=geojson&srid=4326"
        print(f"→ {name}: {url}")
        try:
            fc = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}", file=sys.stderr)
            continue
        (OUT / "raw" / f"{name}.geojson").write_text(json.dumps(fc, ensure_ascii=False))
        feats = []
        for f in fc["features"]:
            props = {k: f["properties"].get(k) for k in keep}
            if name == "postnumre" and isinstance(props.get("kommuner"), list):
                # keep only municipality codes; first = dominant by DAWA ordering
                props["kommuner"] = [k.get("kode") for k in props["kommuner"]]
            f["properties"] = props
            f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
            if args.simplify > 0:
                f = simplify_feature(f, args.simplify)
            feats.append(f)
        fc["features"] = feats
        (OUT / f"{name}.geojson").write_text(json.dumps(fc, ensure_ascii=False))
        print(f"  {len(feats)} features written")

    (OUT / "ATTRIBUTION.txt").write_text(
        "Indeholder data fra Klimadatastyrelsen, Danmarks Administrative Geografiske "
        f"Inddeling (DAGI), hentet via DAWA {today}.\n"
        "Terms: Vilkår for brug af frie geografiske data.\n"
    )
    print("done")


if __name__ == "__main__":
    main()
