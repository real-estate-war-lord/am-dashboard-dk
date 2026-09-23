#!/usr/bin/env python3
"""Vendor the Fingerplan 2019 transport layers as GeoJSON (WGS84).

Source : Plan- og Landdistriktsstyrelsen, Fingerplan 2019 WFS (no key)
         https://gisp.bpst.dk/fingerplan19/wfs  — layers are named `fingerplan19:theme-<layer>`
Output : data/raw/fingerplan/<layer>.geojson (WGS84, attributes kept as they come)
Scope  : Greater Copenhagen only — the Fingerplan covers the capital region. Everything outside it
         (Fyn, Jylland, Femern) needs OSM or a manual geometry; see docs/INFRA.md.

The service delivers EPSG:25832 (ETRS89 / UTM 32N). pyproj is not a dependency of this repo, so the
inverse transverse-Mercator series below does the conversion (centimetre accuracy; ETRS89 and WGS84
differ by well under a metre in Denmark).

Usage: python3 scripts/fetch_infra_fingerplan.py [--layer fp19vo_metro] [--dry-run]
"""
import argparse
import json
import math
import pathlib
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "fingerplan"
WFS = "https://gisp.bpst.dk/fingerplan19/wfs"
UA = {"User-Agent": "am-dashboard-dk/2.1 (+https://github.com/real-estate-war-lord/am-dashboard-dk)"}

LAYERS = [
    "fp19vo_metro",                     # metro lines (existing + planned)
    "fp19vo_letbane_line",              # light rail, overview map
    "fp19vh_letbane_line",              # light rail alignment (Ring 3)
    "fp19vh_letbane_station",           # light rail stations
    "fp19vo_regionaltog_dobbeltspor",   # regional rail double-track projects
    "fp19vo_kbh_ringsted_centerl",      # København–Ringsted centre line
    "fp19vf_stationer",                 # stations
    "fp19vf_stationer_ovr",             # other stations
    "fp19vp_motorvejanlaeg_udv",        # motorway projects / widenings
    "fp19vp_igangvaerende_undersoeg",   # corridors under study
    "fp19vk_kbh_til_bz",                # Copenhagen: areas for urban development
]

# --- EPSG:25832 (ETRS89 / UTM zone 32N) -> WGS84 lon/lat ---------------------------------------
A, F = 6378137.0, 1 / 298.257222101      # GRS80
K0, E0, N0, LON0 = 0.9996, 500000.0, 0.0, math.radians(9.0)


def utm32_to_wgs84(x, y):
    e2 = F * (2 - F); e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    m = (y - N0) / K0
    mu = m / (A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    ep2 = e2 / (1 - e2)
    c1, t1 = ep2 * math.cos(phi1) ** 2, math.tan(phi1) ** 2
    n1 = A / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = A * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - E0) / (n1 * K0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                               + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return [round(math.degrees(lon), 7), round(math.degrees(lat), 7)]


def reproject(node):
    """Rewrite every coordinate pair in a GeoJSON coordinates tree."""
    if isinstance(node, list) and node and isinstance(node[0], (int, float)):
        return utm32_to_wgs84(node[0], node[1])
    return [reproject(n) for n in node] if isinstance(node, list) else node


def fetch(layer):
    url = WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"fingerplan19:theme-{layer}", "outputFormat": "application/json", "srsName": "EPSG:25832"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", help="one layer instead of all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    for layer in ([args.layer] if args.layer else LAYERS):
        print(f"→ {layer}")
        if args.dry_run:
            continue
        try:
            gj = fetch(layer)
            feats = gj.get("features", [])
            kinds, attrs = {}, []
            for f in feats:
                g = f.get("geometry") or {}
                kinds[g.get("type")] = kinds.get(g.get("type"), 0) + 1
                if g.get("coordinates") is not None:
                    g["coordinates"] = reproject(g["coordinates"])
                if not attrs:
                    attrs = [k for k in (f.get("properties") or {}) if k not in ("bbox",)]
            gj["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}
            (OUT / f"{layer}.geojson").write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
            print(f"  ok · {len(feats)} features · {kinds} · attributes: {', '.join(attrs[:8])}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}", file=sys.stderr)
            failures.append(layer)
    if failures:
        print("\nFAILED:", ", ".join(failures), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
