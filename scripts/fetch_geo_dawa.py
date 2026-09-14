#!/usr/bin/env python3
"""Vendor DAGI boundary polygons from DAWA as GeoJSON (WGS84).

RUN THIS BEFORE 2026-10-01 10:00 — Klimadatastyrelsen closes DAWA entirely
on that date. Afterwards use Datafordeler DAGI Fildownload (GPKG) and
`ogr2ogr -t_srs EPSG:4326 -f GeoJSON` instead (see docs/GEO.md).

Strategy: whole-country GeoJSON responses are large and DAWA streams them
slowly, so municipalities are fetched one by one and postal codes per
municipality (de-duplicated by id). Parishes (sogne) come in one request —
DAWA ignores kommunekode for that layer. landsdele/regioner are optional
(--layers landsdele,regioner): few features but huge coastline geometry.

Output: data/geo/raw/<layer>.geojson (full precision) and
        data/geo/<layer>.geojson (5-decimal coordinates, simplified if shapely
        is installed). Attribution string in data/geo/ATTRIBUTION.txt.

Usage:  python scripts/fetch_geo_dawa.py [--simplify 0.0005] [--layers kommuner,postnumre]
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.request

BASE = "https://api.dataforsyningen.dk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo"
UA = {"User-Agent": "am-dashboard-dk/0.1"}
KEEP = {"kommuner": ["kode", "navn", "regionskode"], "postnumre": ["nr", "navn", "kommuner"],
        "sogne": ["kode", "navn"], "landsdele": ["nuts3", "navn"], "regioner": ["kode", "navn"]}


def log(msg):
    print(msg, flush=True)


def fetch(url: str, tries: int = 3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log(f"    retry {i + 1} after error: {e}")
            time.sleep(2 * (i + 1))


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


def feature_id(layer, props):
    return props.get("kode") or props.get("nr") or props.get("nuts3")


def attach_municipalities(postnumre):
    """Fill properties.kommuner = [codes, dominant first] by area of overlap with
    data/geo/raw/kommuner.geojson (DAWA's GeoJSON output omits this link)."""
    komp = OUT / "raw" / "kommuner.geojson"
    if not komp.exists():
        log("    WARNING: raw/kommuner.geojson missing — cannot attach municipalities"); return
    try:
        from shapely.geometry import shape
        from shapely.strtree import STRtree
    except ImportError:
        log("    WARNING: shapely not installed — cannot attach municipalities (pip3 install shapely)"); return
    koms = json.loads(komp.read_text(encoding="utf-8"))["features"]
    kgeoms = [shape(k["geometry"]).buffer(0) for k in koms]
    kcodes = [k["properties"]["kode"] for k in koms]
    tree = STRtree(kgeoms)
    done = 0
    for f in postnumre:
        g = shape(f["geometry"]).buffer(0)
        shares = []
        for idx in tree.query(g):
            a = g.intersection(kgeoms[idx]).area
            if a > 0:
                shares.append((a, kcodes[idx]))
        shares.sort(reverse=True)
        f["properties"]["kommuner"] = [{"kode": c} for _, c in shares]
        done += bool(shares)
    log(f"    municipalities attached for {done}/{len(postnumre)} postal codes (dominant first, by overlap area)")


def collect(layer, kommunekoder):
    """Return list of raw features for a layer."""
    feats, seen = [], set()
    if layer in ("landsdele", "regioner", "sogne"):
        # one request: DAWA ignores kommunekode for sogne (returns all ~2,100 parishes);
        # landsdele/regioner are few features but full-precision coastline — slow, optional.
        fc = fetch(f"{BASE}/{layer}?format=geojson&srid=4326")
        log(f"    {len(fc['features'])} features received")
        return fc["features"]
    if layer == "kommuner":
        for i, k in enumerate(kommunekoder, 1):
            fc = fetch(f"{BASE}/kommuner/{k}?format=geojson&srid=4326")
            feats.append(fc if fc.get("type") == "Feature" else fc["features"][0])
            log(f"    kommune {k} ({i}/{len(kommunekoder)})")
        return feats
    # postnumre / sogne: per municipality, de-duplicated
    for i, k in enumerate(kommunekoder, 1):
        fc = fetch(f"{BASE}/{layer}?kommunekode={k}&format=geojson&srid=4326")
        n = 0
        for f in fc["features"]:
            fid = feature_id(layer, f["properties"])
            if fid in seen:
                continue
            seen.add(fid); feats.append(f); n += 1
        log(f"    kommune {k} ({i}/{len(kommunekoder)}): +{n} → {len(feats)}")
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simplify", type=float, default=0.0, help="tolerance in degrees (~0.0005 ≈ 50 m); needs shapely")
    ap.add_argument("--layers", default="kommuner,postnumre,sogne", help="default omits landsdele,regioner (slow, not needed for the map)")
    ap.add_argument("--from-raw", action="store_true", help="re-process data/geo/raw/*.geojson without fetching")
    args = ap.parse_args()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)

    koms = []
    if not args.from_raw:
        log("→ municipality list")
        koms = sorted(k["kode"] for k in fetch(f"{BASE}/kommuner"))
        log(f"  {len(koms)} municipalities")

    for layer in args.layers.split(","):
        layer = layer.strip()
        log(f"→ {layer}")
        rawp = OUT / "raw" / f"{layer}.geojson"
        if args.from_raw:
            if not rawp.exists():
                log(f"  FAILED: {rawp} missing"); continue
            raw = json.loads(rawp.read_text(encoding="utf-8"))["features"]
        else:
            try:
                raw = collect(layer, koms)
            except Exception as e:  # noqa: BLE001
                log(f"  FAILED: {e}")
                continue
            rawp.write_text(json.dumps({"type": "FeatureCollection", "features": raw}, ensure_ascii=False))
        if layer == "postnumre":
            attach_municipalities(raw)
        feats = []
        for f in raw:
            props = {k: f["properties"].get(k) for k in KEEP[layer]}
            if layer == "postnumre" and isinstance(props.get("kommuner"), list):
                props["kommuner"] = [k.get("kode") for k in props["kommuner"]]
            f = {"type": "Feature", "properties": props, "geometry": f["geometry"]}
            if args.simplify > 0:
                f = simplify_feature(f, args.simplify)
            f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"])
            feats.append(f)
        p = OUT / f"{layer}.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
        log(f"  {len(feats)} features written → {p.relative_to(ROOT)} ({p.stat().st_size / 1e6:.1f} MB)")

    (OUT / "ATTRIBUTION.txt").write_text(
        "Indeholder data fra Klimadatastyrelsen, Danmarks Administrative Geografiske "
        f"Inddeling (DAGI), hentet via DAWA {dt.date.today().isoformat()}.\n"
        "Terms: Vilkår for brug af frie geografiske data.\n")
    log("done")


if __name__ == "__main__":
    main()
