#!/usr/bin/env python3
"""DMI Klimaatlas → data/raw/klimaatlas/ (v2.5 climate layer).

Two ArcGIS Online feature services, pulled whole so the build step never has to go online:

  VandstandStormflodKyst_latest  layer 0  sea level and storm surge per coastal stretch (values)
                                 layer 1  Kystinddeling — the 34 stretches, with geometry
  NedboerKommuner_latest         layer 0  precipitation and cloudburst per kommune (values)

Only `aarstid = 1` (the annual season) is kept; every scenarie / periode / percentil is.
Each pull is paginated with resultOffset at the service's own maxRecordCount (2000), written
as both JSON (the full attribute records) and a flat CSV, with the services' own `version`
string and the fetch date recorded in meta.json.

    python3 scripts/fetch_klimaatlas.py            # everything
    python3 scripts/fetch_klimaatlas.py --only coast
"""
import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests missing: pip3 install requests")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "klimaatlas"
AGOL = "https://services9.arcgis.com/qH1Ysxh3VVYXbkQU/arcgis/rest/services"
UA = {"User-Agent": "am-dashboard-dk klimaatlas fetch (research; contact via repo)"}
PAGE = 2000
TIMEOUT = 120
AARSTID = 1                      # 1 = year (the annual figure); 2–5 are the seasons

PULLS = [
    # key              service                        layer  where                    geometry
    ("coast_values",   "VandstandStormflodKyst_latest", 0, f"aarstid={AARSTID}",      False),
    ("coast_stretches", "VandstandStormflodKyst_latest", 1, "1=1",                    True),
    ("precip_values",  "NedboerKommuner_latest",        0, f"aarstid={AARSTID}",      False),
]


def query(service, layer, where, offset, geometry, fmt="json"):
    p = {"where": where, "outFields": "*", "returnGeometry": str(geometry).lower(),
         "resultOffset": offset, "resultRecordCount": PAGE, "f": fmt,
         "orderByFields": "OBJECTID"}
    if geometry:
        p["outSR"] = 4326
    r = requests.get(f"{AGOL}/{service}/FeatureServer/{layer}/query", params=p,
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def pull(key, service, layer, where, geometry):
    """Every page of one layer. Geometry layers come back as geojson, value layers as ArcGIS json."""
    t0 = time.time()
    rows, feats, offset = [], [], 0
    while True:
        d = query(service, layer, where, offset, geometry, "geojson" if geometry else "json")
        page = d.get("features", [])
        if not page:
            break
        if geometry:
            feats.extend(page)
            rows.extend(f.get("properties", {}) for f in page)
        else:
            rows.extend(f["attributes"] for f in page)
        if len(page) < PAGE and not d.get("exceededTransferLimit"):
            break
        offset += len(page)
    secs = time.time() - t0
    versions = sorted({str(r.get("version")) for r in rows if r.get("version")})
    print(f"  {key}: {len(rows)} rows in {secs:.1f} s · version {', '.join(versions) or '—'}")
    return rows, feats, versions, secs


def write_csv(path, rows):
    if not rows:
        return 0
    cols = list(rows[0])
    for r in rows:                                  # a later row may carry a field the first lacks
        for c in r:
            if c not in cols:
                cols.append(c)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated keys: coast_values, coast_stretches, precip_values")
    a = ap.parse_args()
    want = {s.strip() for s in a.only.split(",") if s.strip()} or {p[0] for p in PULLS}
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"fetched": dt.date.today().isoformat(), "source": AGOL, "aarstid": AARSTID,
            "page_size": PAGE, "pulls": {}}
    print(f"Klimaatlas → {OUT.relative_to(ROOT)}")
    for key, service, layer, where, geometry in PULLS:
        if key not in want:
            continue
        rows, feats, versions, secs = pull(key, service, layer, where, geometry)
        if not rows:
            sys.exit(f"{key}: no rows came back — refusing to write an empty file")
        if geometry:
            gj = {"type": "FeatureCollection", "features": feats}
            (OUT / f"{key}.geojson").write_text(json.dumps(gj, ensure_ascii=False))
        else:
            (OUT / f"{key}.json").write_text(json.dumps(rows, ensure_ascii=False))
        write_csv(OUT / f"{key}.csv", rows)
        meta["pulls"][key] = {"service": service, "layer": layer, "where": where,
                              "rows": len(rows), "version": versions, "seconds": round(secs, 1),
                              "files": [f"{key}.geojson" if geometry else f"{key}.json",
                                        f"{key}.csv"]}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print(f"wrote {sum(p['rows'] for p in meta['pulls'].values())} rows + meta.json")


if __name__ == "__main__":
    main()
