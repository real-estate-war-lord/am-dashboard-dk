#!/usr/bin/env python3
"""Vendor Copenhagen quarter (kvarter, 67) and district (bydel, 10) polygons from
Københavns Kommune's WFS (CC BY 4.0) → data/geo/cph_kvarterer.geojson, cph_bydele.geojson.

Usage: python scripts/fetch_geo_cph.py [--simplify 0.0002]
"""
import argparse
import datetime as dt
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo"
WFS = "https://wfs-kbhkort.kk.dk/k101/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=k101:{layer}&outputFormat=json&SRSNAME=EPSG:4326"
LAYERS = {"kvarter": ("cph_kvarterer", ["kvarternr", "kvarternavn"]), "bydel": ("cph_bydele", ["bydel_nr", "navn"])}


def round_coords(o, nd=5):
    if isinstance(o, list):
        if o and isinstance(o[0], (int, float)):
            return [round(o[0], nd), round(o[1], nd)]
        return [round_coords(x, nd) for x in o]
    return o


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--simplify", type=float, default=0.0002); a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for layer, (name, keep) in LAYERS.items():
        url = WFS.format(layer=layer)
        print(f"→ {layer}: {url}", flush=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "am-dashboard-dk/0.1"}), timeout=120) as r:
            fc = json.load(r)
        feats = []
        for f in fc["features"]:
            g = f["geometry"]
            if a.simplify > 0:
                try:
                    from shapely.geometry import shape, mapping
                    g = mapping(shape(g).simplify(a.simplify, preserve_topology=True))
                except ImportError:
                    pass
            g = dict(g); g["coordinates"] = round_coords(g["coordinates"])
            feats.append({"type": "Feature", "properties": {k: f["properties"].get(k) for k in keep}, "geometry": g})
        p = OUT / f"{name}.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
        print(f"  {len(feats)} features → {p.relative_to(ROOT)} ({p.stat().st_size/1e6:.2f} MB)")
    (OUT / "ATTRIBUTION_CPH.txt").write_text(f"Bydele og kvarterer: Københavns Kommune, opendata.dk (CC BY 4.0), hentet {dt.date.today().isoformat()}.\n")
    print("done")


if __name__ == "__main__":
    main()
