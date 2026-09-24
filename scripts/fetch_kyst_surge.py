#!/usr/bin/env python3
"""Kystdirektoratet storm-surge extents → data/raw/kyst_surge/ (v2.6 climate layer).

Kystplanlægger (`Kystplanlaegger_Oversvommelsesfare_2` on gisportal.mst.dk) publishes the
100-year flood extent for three horizons — 2020, 2070 and 2120 — as polygon feature layers, over
the whole country. These are the authority's own published extents; nothing here is modelled.

  2020  layer 3   42 features   →  horizon "today"
  2070  layer 12  35 features   →  horizon "2070"
  2120  layer 21  42 features   →  horizon "2120"

Few features, but each is a nationwide multipolygon of tens of MB, so the pull is paginated with
`resultOffset` a handful of features at a time and written in EPSG:25832 — the CRS everything
downstream measures in, so no reprojection happens before the areas are computed.

    python3 scripts/fetch_kyst_surge.py
    python3 scripts/fetch_kyst_surge.py --only 2070
"""
import argparse
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
OUT = ROOT / "data" / "raw" / "kyst_surge"
SVC = ("https://gisportal.mst.dk/server/rest/services/ekstern/"
       "Kystplanlaegger_Oversvommelsesfare_2/MapServer")
UA = {"User-Agent": "am-dashboard-dk kyst surge fetch (research; contact via repo)"}
PAGE = 1                      # one feature per request — some are tens of MB
RETRIES = 4                   # the service answers 500 on a big page; back off and retry
PRECISION = 1                 # coordinate decimals in metres — 0.1 m, lossless for our purpose
TIMEOUT = 600
HORIZONS = [("today", "2020", 3), ("2070", "2070", 12), ("2120", "2120", 21)]


def ids(layer):
    r = requests.get(f"{SVC}/{layer}/query", headers=UA, timeout=TIMEOUT,
                     params={"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    r.raise_for_status()
    d = r.json()
    return sorted(d.get("objectIds") or [])


def feature(layer, oid):
    """One feature, with backoff. The service answers 500 on the largest geometries, so the
    retries also step the coordinate precision down — 0.1 m, then 1 m — which shrinks the
    payload without generalising the shape."""
    last = None
    for attempt in range(RETRIES):
        prec = PRECISION if attempt < 2 else 0
        try:
            r = requests.get(f"{SVC}/{layer}/query", headers=UA, timeout=TIMEOUT,
                             params={"where": f"OBJECTID={oid}", "outFields": "*",
                                     "returnGeometry": "true", "outSR": 25832, "f": "geojson",
                                     "geometryPrecision": prec})
            r.raise_for_status()
            d = r.json()
            if d.get("features"):
                return d["features"], len(r.content), prec
            last = "empty response"
        except Exception as e:                                         # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(2 * (attempt + 1))
    raise SystemExit(f"OBJECTID {oid} on layer {layer} failed after {RETRIES} tries: {last}")


def count(layer):
    r = requests.get(f"{SVC}/{layer}/query", headers=UA, timeout=TIMEOUT,
                     params={"where": "1=1", "returnCountOnly": "true", "f": "json"})
    return r.json().get("count")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated horizon ids: today, 2070, 2120")
    a = ap.parse_args()
    want = {s.strip() for s in a.only.split(",") if s.strip()} or {h for h, _, _ in HORIZONS}
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"fetched": dt.date.today().isoformat(), "service": SVC, "crs": "EPSG:25832",
            "event": "100-årshændelse", "horizons": {}}
    mp = OUT / "meta.json"
    if mp.exists():
        meta["horizons"] = json.loads(mp.read_text()).get("horizons", {})
    for hz, year, layer in HORIZONS:
        if hz not in want:
            continue
        t0 = time.time()
        n = count(layer)
        oids = ids(layer)
        feats, bytes_, coarse = [], 0, []
        for i, oid in enumerate(oids, 1):
            got, b, prec = feature(layer, oid)
            feats.extend(got)
            bytes_ += b
            if prec != PRECISION:
                coarse.append(oid)
            if i % 5 == 0 or i == len(oids):
                print(f"  {year}: {i}/{n} features, {bytes_ / 1e6:,.1f} MB", flush=True)
        if len(feats) != n:
            sys.exit(f"{year}: got {len(feats)} of {n} features — refusing to write a partial pull")
        p = OUT / f"kyst_100yr_{year}.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                ensure_ascii=False, separators=(",", ":")))
        secs = time.time() - t0
        meta["horizons"][hz] = {"year": year, "layer": layer, "features": n,
                                "coordinate_precision_m": 10 ** -PRECISION,
                                "objectids_at_1m": coarse,
                                "file": p.name, "mb": round(p.stat().st_size / 1e6, 1),
                                "seconds": round(secs, 1)}
        print(f"  wrote {p.relative_to(ROOT)} · {n} features · "
              f"{p.stat().st_size / 1e6:,.1f} MB · {secs:.0f} s", flush=True)
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print("wrote", mp.relative_to(ROOT))


if __name__ == "__main__":
    main()
