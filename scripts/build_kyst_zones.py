#!/usr/bin/env python3
"""Kystdirektoratet surge extents → per-kommune zones + exposure (v2.6 climate layer).

Input  : data/raw/kyst_surge/kyst_100yr_{2020,2070,2120}.geojson (EPSG:25832, scripts/fetch_kyst_surge.py)
Output : data/processed/climate/surge_{today,2070,2120}/<kommune>.json  — the published extent,
                                                          cut to the kommune, nothing else
         data/processed/climate/surge_{today,2070,2120}/index.json      — exposure per kommune,
                                                          postal code and Copenhagen quarter

The polygons are the authority's own 100-year flood extents, so there is no depth and no class:
`depth_class` is null everywhere. Exposure is a count, not a model — a BBR dwelling is in the zone
when its building's coordinate falls inside the published polygon, allowing 5 m for the fact that
BBR gives a point rather than a footprint.

    python3 scripts/build_kyst_zones.py              # all three horizons
    python3 scripts/build_kyst_zones.py --only today
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    from shapely.geometry import Point, shape
    from shapely.ops import transform, unary_union
    from shapely.prepared import prep
    from shapely.strtree import STRtree
except ImportError:
    sys.exit("shapely missing: pip3 install shapely")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "kyst_surge"
OUT = ROOT / "data" / "processed" / "climate"
GEO = ROOT / "data" / "geo"
BBR = ROOT / "data" / "raw" / "bbr"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_surge_zones import (COORD_DP, DWELLING_BOLIGTYPER, DWELLING_STATUS,  # noqa: E402
                               MIN_PART_M2, SCHEMA, SIMPLIFY_M, SURGE_MIN_HOLE_M2, budget, clean,
                               wgs84_to_utm32)

HORIZONS = [("today", "2020", "Klimaatlas reference period 1981–2010"),
            ("2070", "2070", "Klimaatlas period 2041–2070"),
            ("2120", "2120", "Klimaatlas period 2071–2100 — the latest Klimaatlas period")]
SOURCE = "Kystdirektoratet, Kystplanlægger oversvømmelsesfare (gisportal.mst.dk)"
POINT_TOL_M = 5           # BBR gives a building point, not a footprint
_WKT = re.compile(r"\(([-\d.]+)\s+([-\d.]+)\)")


def load_areas(name, code_keys, extra=()):
    gj = json.loads((GEO / f"{name}.geojson").read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        code = next((str(p[k]) for k in code_keys if p.get(k) not in (None, "")), None)
        if code is None:
            continue
        rec = {"code": code.zfill(4) if name == "kommuner" else code,
               "name": p.get("navn") or p.get("name") or p.get("kvarternavn") or "",
               "geom": transform(wgs84_to_utm32, shape(f["geometry"])).buffer(0)}
        for k in extra:
            rec[k] = p.get(k)
        out.append(rec)
    return out


def dwelling_points(kom):
    """[(x, y)] EPSG:25832 — BBR dwellings at their building's coordinate (v1.4 definition)."""
    bfile, efile = BBR / f"{kom}_bygning.jsonl", BBR / f"{kom}_enhed.jsonl"
    if not (bfile.exists() and efile.exists()):
        return None
    coords = {}
    with bfile.open() as fh:
        for line in fh:
            b = json.loads(line)
            c = (b.get("byg404Koordinat") or {}).get("wkt")
            if c:
                m = _WKT.search(c)
                if m:
                    coords[b["id_lokalId"]] = (float(m.group(1)), float(m.group(2)))
    pts = []
    with efile.open() as fh:
        for line in fh:
            u = json.loads(line)
            if u.get("status") != DWELLING_STATUS:
                continue
            if str(u.get("enh023Boligtype")) not in DWELLING_BOLIGTYPER:
                continue
            p = coords.get(u.get("bygning"))
            if p:
                pts.append(p)
    return pts


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated horizon ids")
    a = ap.parse_args()
    want = {s.strip() for s in a.only.split(",") if s.strip()} or {h for h, _, _ in HORIZONS}

    koms = load_areas("kommuner", ("kode", "kommunekode", "KOMKODE"))
    posts = load_areas("postnumre", ("nr", "postnr", "POSTNR"))
    kvs = load_areas("cph_kvarterer", ("kvarternr", "kvarter", "kode"))
    print(f"{len(koms)} kommuner · {len(posts)} postal codes · {len(kvs)} Copenhagen quarters")
    bbr = json.loads((ROOT / "data" / "processed" / "bbr.json").read_text(encoding="utf-8"))

    # the zone per kommune, per horizon
    zones = {}          # {hz: {kommune: geom}}
    national = {}       # {hz: geom}
    ktree = STRtree([k["geom"] for k in koms])
    for hz, year, _period in HORIZONS:
        if hz not in want:
            continue
        p = RAW / f"kyst_100yr_{year}.geojson"
        if not p.exists():
            sys.exit(f"{p.relative_to(ROOT)} missing — run scripts/fetch_kyst_surge.py")
        t0 = time.time()
        gj = json.loads(p.read_text(encoding="utf-8"))
        g = unary_union([shape(f["geometry"]).buffer(0) for f in gj["features"]
                         if f.get("geometry")])
        national[hz] = g
        per = {}
        for j in ktree.query(g):
            cut = g.intersection(koms[j]["geom"])
            if not cut.is_empty:
                per[koms[j]["code"]] = cut
        zones[hz] = per
        print(f"  {year}: {len(gj['features'])} features · {g.area / 1e6:,.1f} km² · "
              f"{len(per)} kommuner · {time.time() - t0:.0f} s", flush=True)

    # exposure — every dwelling is read once and tested against all three horizons
    ptree, pprep = STRtree([x["geom"] for x in posts]), [prep(x["geom"]) for x in posts]
    qtree, qprep = STRtree([x["geom"] for x in kvs]), [prep(x["geom"]) for x in kvs]
    expo = {hz: {"kommune": {}, "postnr": collections.Counter(), "kvarter": collections.Counter()}
            for hz in zones}
    touched = sorted({c for hz in zones for c in zones[hz]})
    print(f"  dwellings in {len(touched)} kommuner with a zone:", flush=True)
    for code in touched:
        pts = dwelling_points(code)
        if pts is None:
            for hz in zones:
                if code in zones[hz]:
                    expo[hz]["kommune"][code] = {"dwellings": None, "dwellings_in_zone": None,
                                                 "surge_dw_pct": None,
                                                 "note": "no BBR pull for this kommune"}
            continue
        line = [f"    {code}: {len(pts):>7,} dwellings"]
        for hz in zones:
            z = zones[hz].get(code)
            if z is None:
                continue
            pz = prep(z.buffer(POINT_TOL_M))
            inzone = [(x, y) for x, y in pts if pz.contains(Point(x, y))]
            expo[hz]["kommune"][code] = {
                "dwellings": len(pts), "dwellings_in_zone": len(inzone),
                "surge_dw_pct": round(100 * len(inzone) / len(pts), 2) if pts else None}
            for x, y in inzone:
                pt = Point(x, y)
                for j in ptree.query(pt):
                    if pprep[j].contains(pt):
                        expo[hz]["postnr"][posts[j]["code"]] += 1
                        break
                for j in qtree.query(pt):
                    if qprep[j].contains(pt):
                        expo[hz]["kvarter"][kvs[j]["code"]] += 1
                        break
            line.append(f"{hz} {len(inzone):,}")
        print(" · ".join(line), flush=True)

    # write
    built = dt.date.today().isoformat()
    for hz, year, period in HORIZONS:
        if hz not in zones:
            continue
        zdir = OUT / f"surge_{hz}"
        zdir.mkdir(parents=True, exist_ok=True)
        for old in zdir.glob("*.json"):
            old.unlink()
        method = (f"Kystdirektoratet, Kystplanlægger oversvømmelsesfare, 100-årshændelse {year}; "
                  f"published extent cut to the kommune, simplified {SIMPLIFY_M:g} m in EPSG:25832, "
                  f"holes under {SURGE_MIN_HOLE_M2} m² filled, parts under {MIN_PART_M2} m² dropped, "
                  f"EPSG:4326 at {COORD_DP} decimals")
        idx = {"kommune": {}, "postnr": {}, "kvarter": {}}
        written, over = 0, []
        for k in koms:
            code = k["code"]
            g = zones[hz].get(code)
            e = expo[hz]["kommune"].get(code, {})
            rec = {"kommune": code, "name": k["name"],
                   "zone_km2": round(g.area / 1e6, 3) if g is not None else 0.0,
                   "dwellings": e.get("dwellings"), "dwellings_in_zone": e.get("dwellings_in_zone"),
                   "surge_dw_pct": e.get("surge_dw_pct")}
            if e.get("note"):
                rec["note"] = e["note"]
            idx["kommune"][code] = rec
            if g is None:
                continue
            geom = clean(g, SIMPLIFY_M, min_part_m2=MIN_PART_M2, min_hole_m2=SURGE_MIN_HOLE_M2)
            if geom is None:
                continue
            doc = {"type": "FeatureCollection",
                   "meta": {"hazard": "storm_surge", "horizon": hz, "year": year,
                            "period": period, "kommune": code, "kommune_name": k["name"],
                            "depth_class": None, "level_cm": None, "event": "100-årshændelse",
                            "method": method, "source": SOURCE,
                            "zone_km2": rec["zone_km2"], "schema": SCHEMA, "updated": built},
                   "features": [{"type": "Feature",
                                 "properties": {"depth_class": None, "horizon": hz, "year": year},
                                 "geometry": geom}]}
            p = zdir / f"{code}.json"
            p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
            written += 1
            if p.stat().st_size / 1e6 > 3.0:
                over.append((code, k["name"], p.stat().st_size / 1e6))
        for level, counter, denom in (("postnr", expo[hz]["postnr"], bbr["postnr"]),
                                      ("kvarter", expo[hz]["kvarter"], bbr["kvarter"])):
            for c, n in counter.items():
                tot = (denom.get(c) or {}).get("n")
                idx[level][c] = {"dwellings": tot, "dwellings_in_zone": n,
                                 "surge_dw_pct": round(100 * n / tot, 2) if tot else None}
        (zdir / "index.json").write_text(json.dumps(
            {"meta": {"hazard": "storm_surge", "horizon": hz, "year": year, "period": period,
                      "depth_class": None, "level_cm": None, "event": "100-årshændelse",
                      "built": built, "schema": SCHEMA, "source": SOURCE, "method": method,
                      "zone_km2_national": round(national[hz].area / 1e6, 1),
                      "dwellings": f"BBR Enhed boligtype 1–5 status 6 at the building's "
                                   f"coordinate, inside the zone allowing {POINT_TOL_M} m",
                      "denominator": "data/processed/bbr.json (same dwelling definition)"},
             **idx}, ensure_ascii=False, separators=(",", ":")))
        print(f"  {hz}: {written} kommune files · {len(idx['postnr'])} postal codes · "
              f"{len(idx['kvarter'])} quarters")
        for code, name, mb in over:
            print(f"    ⚠ {code} {name} {mb:.2f} MB over the 3 MB per-file budget")

    # invariants
    print("\ninvariants (2120 ≥ 2070 ≥ today), violations only:")
    bad = 0
    for k in koms:
        c = k["code"]
        a_ = [(OUT / f"surge_{h}" / "index.json") for h, _, _ in HORIZONS]
        vals = {}
        for h, _, _ in HORIZONS:
            p = OUT / f"surge_{h}" / "index.json"
            if p.exists():
                vals[h] = json.loads(p.read_text())["kommune"].get(c, {})
        if len(vals) < 3:
            continue
        for what in ("zone_km2", "dwellings_in_zone"):
            s = [vals[h].get(what) for h, _, _ in HORIZONS]
            if any(v is None for v in s):
                continue
            if not (s[2] >= s[1] >= s[0]):
                print(f"  ⚠ {c} {k['name']:<18} {what}: today {s[0]} · 2070 {s[1]} · 2120 {s[2]}")
                bad += 1
    print(f"  {bad} violation(s) — logged, not corrected: these are the published extents as they are")
    budget()


if __name__ == "__main__":
    main()
