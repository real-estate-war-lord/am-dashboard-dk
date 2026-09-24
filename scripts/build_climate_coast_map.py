#!/usr/bin/env python3
"""Coastal kommune → Klimaatlas coastal stretch → data/external/klimaatlas_coast_kommune.csv.

Klimaatlas publishes sea level and storm surge per *coastal stretch* (34 of them, `kystkode`),
not per kommune, so the dashboard needs a map from one to the other. It is generated here and
committed, because it changes only when DAGI boundaries or the Klimaatlas stretch division do.

Method, in EPSG:25832 throughout:
  1. dissolve neighbours away — what is left of a kommune's own boundary after subtracting every
     other kommune's boundary (60 m tolerance, absorbing the 0.0005 deg simplification sliver) is
     its coastline. Over 100 m of it is a candidate; less is a polygon artifact.
  2. a candidate is coastal when its coastline runs within 2 km of a Klimaatlas stretch polygon.
     This is what separates a real short shore (Vallensbaek, 376 m, touching SJ8) from an enclave
     sliver (Frederiksberg, 136 m, nearest stretch 3.8 km away).
  3. the kommune takes the stretch it shares the LONGEST coastline with. The coastline is sampled
     every 25 m and each sample is assigned to its nearest stretch within 2 km; the stretch
     holding the most samples wins. Every other stretch the coastline touches is kept in
     `other_kystkoder` so the UI can name them, but no number is ever combined across stretches.
     This replaces the earlier MAX-across-stretches rule: a maximum of two published figures is a
     figure nobody published, and this branch shows official figures only.
  4. landlocked kommuner get no row at all; the build renders their coastal indicators as null
     with reason "not coastal".

    python3 scripts/build_climate_coast_map.py
"""

import argparse
import csv
import datetime as dt
import json
import math
import sys
from pathlib import Path

try:
    from shapely.geometry import Point, shape
    from shapely.ops import transform, unary_union
    from shapely.strtree import STRtree
except ImportError:
    sys.exit("shapely missing: pip3 install shapely")

ROOT = Path(__file__).resolve().parents[1]
KOMMUNER = ROOT / "data" / "geo" / "kommuner.geojson"
STRETCHES = ROOT / "data" / "raw" / "klimaatlas" / "coast_stretches.geojson"
OUT = ROOT / "data" / "external" / "klimaatlas_coast_kommune.csv"

NEIGHBOUR_TOL_M = 60          # absorbs the sliver between two simplified neighbours
MIN_COAST_M = 100             # below this the free boundary is a polygon artifact
STRETCH_MAX_M = 2000          # the 2 km rule
SAMPLE_M = 25                 # coastline sampling step when ranking stretches by shared length
METRO19 = ["0101", "0147", "0151", "0153", "0155", "0157", "0159", "0161", "0163", "0165",
           "0167", "0169", "0173", "0175", "0183", "0185", "0187", "0190", "0230"]

_A, _F, _K0, _LON0 = 6378137.0, 1 / 298.257222101, 0.9996, math.radians(9.0)


def wgs84_to_utm32(lon, lat, z=None):
    e2 = _F * (2 - _F); ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2; c = ep2 * math.cos(phi) ** 2
    a1 = (lam - _LON0) * math.cos(phi)
    m = _A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
              - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
              + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
              - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = _K0 * n * (a1 + (1 - t + c) * a1 ** 3 / 6
                   + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * a1 ** 5 / 120) + 500000.0
    y = _K0 * (m + n * math.tan(phi) * (a1 ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a1 ** 4 / 24
               + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * a1 ** 6 / 720))
    return x, y


def kommune_code(props):
    return str(props.get("kode") or props.get("kommunekode") or props.get("KOMKODE") or "").zfill(4)


def load_kommuner():
    gj = json.loads(KOMMUNER.read_text())
    out = []
    for f in gj["features"]:
        p = f["properties"]
        out.append({"code": kommune_code(p),
                    "name": p.get("navn") or p.get("name") or p.get("NAVN") or "",
                    "geom": transform(wgs84_to_utm32, shape(f["geometry"])).buffer(0)})
    return out


def load_stretches():
    gj = json.loads(STRETCHES.read_text())
    return [{"kystkode": f["properties"]["kystkode"],
             "kystnavn": f["properties"].get("kystnavn") or "",
             "name_en": f["properties"].get("Name_EN") or "",
             "geom": transform(wgs84_to_utm32, shape(f["geometry"])).buffer(0)}
            for f in gj["features"]]


def build():
    koms = load_kommuner()
    stretches = load_stretches()
    kgeoms = [k["geom"] for k in koms]
    sgeoms = [s["geom"] for s in stretches]
    ktree, stree = STRtree(kgeoms), STRtree(sgeoms)

    rows, skipped = [], []
    for i, k in enumerate(koms):
        near = [j for j in ktree.query(k["geom"].buffer(NEIGHBOUR_TOL_M)) if j != i]
        shared = unary_union([kgeoms[j].boundary.buffer(NEIGHBOUR_TOL_M) for j in near]) if near else None
        free = k["geom"].boundary.difference(shared) if shared is not None else k["geom"].boundary
        coast_m = free.length
        if coast_m <= MIN_COAST_M:
            skipped.append((k["code"], k["name"], coast_m, None, "no free boundary"))
            continue
        hits = sorted(((sgeoms[j].distance(free), j) for j in stree.query(free.buffer(STRETCH_MAX_M))
                       if sgeoms[j].distance(free) <= STRETCH_MAX_M))
        if not hits:
            near_any = min((sgeoms[j].distance(free) for j in range(len(sgeoms))), default=None)
            skipped.append((k["code"], k["name"], coast_m, near_any,
                            "no Klimaatlas stretch within 2 km"))
            continue
        # rank the touching stretches by how much of this coastline is nearest to each of them
        shared = {j: 0.0 for _, j in hits}
        dense = free.segmentize(SAMPLE_M) if hasattr(free, "segmentize") else free
        pts = [Point(c) for g in getattr(dense, "geoms", [dense]) for c in g.coords]
        for pt in pts:
            best = min(((sgeoms[j].distance(pt), j) for _, j in hits))
            if best[0] <= STRETCH_MAX_M:
                shared[best[1]] += SAMPLE_M
        order = sorted(shared, key=lambda j: (-shared[j], stretches[j]["kystkode"]))
        first = order[0]
        others = [j for j in order[1:] if shared[j] > 0]
        rows.append({"kommune_kode": k["code"], "kommune_navn": k["name"],
                     "kystkode": stretches[first]["kystkode"],
                     "kystnavn": stretches[first]["kystnavn"],
                     "shared_coast_m": round(shared[first]),
                     "other_kystkoder": ";".join(stretches[j]["kystkode"] for j in others),
                     "other_kystnavne": ";".join(stretches[j]["kystnavn"] for j in others),
                     "other_shared_coast_m": ";".join(str(round(shared[j])) for j in others),
                     "n_stretches": len(hits),
                     "coast_m": round(coast_m),
                     "nearest_stretch_m": round(hits[0][0]),
                     "rule": "longest_shared_coastline"})
    rows.sort(key=lambda r: r["kommune_kode"])
    return rows, skipped, len(koms), len(stretches)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print the table, write nothing")
    a = ap.parse_args()
    rows, skipped, n_kom, n_str = build()
    print(f"{len(rows)} coastal of {n_kom} kommuner · {n_str} Klimaatlas stretches · "
          f"{len(skipped)} landlocked")
    multi = [r for r in rows if r["other_kystkoder"]]
    print(f"{len(multi)} kommuner touch more than one stretch — the longest shared coastline wins, "
          "the rest go to other_kystkoder")
    byc = {r["kommune_kode"]: r for r in rows}
    sk = {s[0]: s for s in skipped}
    print("\nmetro 19:")
    print(f"  {'code':<6}{'kommune':<18}{'coast':<7}{'other':<10}{'shared m':>10}{'coast m':>10}  note")
    for c in METRO19:
        if c in byc:
            r = byc[c]
            print(f"  {c:<6}{r['kommune_navn']:<18}{r['kystkode']:<7}"
                  f"{r['other_kystkoder'] or '—':<10}{r['shared_coast_m']:>10,}"
                  f"{r['coast_m']:>10,}")
        else:
            s = sk.get(c)
            near = f"{s[3]:,.0f}" if s and s[3] else "—"
            print(f"  {c:<6}{(s[1] if s else '?'):<18}{'—':<7}{'—':<10}{0:>10}"
                  f"{(round(s[2]) if s else 0):>10,}  landlocked — {s[4] if s else ''}")
    if not a.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {OUT.relative_to(ROOT)} ({len(rows)} rows, generated "
              f"{dt.date.today().isoformat()})")


if __name__ == "__main__":
    main()
