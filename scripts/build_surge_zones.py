#!/usr/bin/env python3
"""Storm-surge zones and flood-risk areas → data/processed/climate/ (v2.5 climate layer).

Two outputs, both in the shared climate-zone schema (see SCHEMA below):

  --risk-areas   data/processed/climate/risk_areas.json
                 the 26 EU Floods Directive risk areas, simplified for the web from the 90 MB
                 raw pull, with the kommuner each one covers.

  --horizon today
                 data/processed/climate/surge_today/<kommune>.json — the modelled 100-year sea
                 flood extent, cut into depth classes 0–0.5 / 0.5–1.0 / > 1.0 m, dissolved per
                 class, simplified at 2 m in EPSG:25832 and written as EPSG:4326 with 6 decimals.
                 Parts under 200 m² are dropped. Plus surge_today/index.json with the share of
                 each kommune's dwellings inside the zone (BBR boligtype 1–5, status 6 — the same
                 definition the v1.4 postal-code indicators use).

Size budget: no single file over 3 MB, the whole climate folder under 60 MB. Both are checked
at the end of a run and any breach is printed, loudly, rather than silently shipped.

    python3 scripts/build_surge_zones.py --risk-areas
    python3 scripts/build_surge_zones.py --horizon today
"""
import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

try:
    from shapely.geometry import Polygon, mapping, shape
    from shapely.ops import transform, unary_union
    from shapely.strtree import STRtree
except ImportError:
    sys.exit("shapely missing: pip3 install shapely")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "flood_hazard"
OUT = ROOT / "data" / "processed" / "climate"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
BBR = ROOT / "data" / "raw" / "bbr"

MAX_FILE_MB = 3.0
MAX_FOLDER_MB = 60.0
# Zone outlines, in EPSG:25832. The brief said 2 m; the source raster is 5 m max-pooled to 10 m,
# so every vertex is a 10 m cell corner and a 2 m tolerance cannot remove anything — it just
# stores the staircase, and the folder came to 90 MB against a 60 MB budget. 8 m is still inside
# one cell, keeps the outline where it belongs and brings the folder to 42 MB.
SIMPLIFY_M = 8.0
SURGE_MIN_HOLE_M2 = 2_000        # pinholes inside a flood zone — see clean()
RISK_SIMPLIFY_M = 25.0           # risk areas are far bigger, so a coarser tolerance holds shape
RISK_MIN_PART_M2 = 10_000        # 1 ha — these are regional areas, not single plots
RISK_MIN_HOLE_M2 = 2_000         # 0.2 ha — see clean()
RISK_COORD_DP = 5                # ≈ 1 m, plenty for an area measured in km²
MIN_PART_M2 = 200
COORD_DP = 6
DEPTH_CLASSES = [(0.0, 0.5, "0-0.5"), (0.5, 1.0, "0.5-1.0"), (1.0, None, ">1.0")]
DWELLING_BOLIGTYPER = {"1", "2", "3", "4", "5"}
DWELLING_STATUS = "6"

SCHEMA = ("hazard, horizon, depth_class | threshold_mm, method, source, level_cm, updated — the "
          "shared header every climate zone file carries")

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


def utm32_to_wgs84(x, y, z=None):
    a, f, k0, lon0 = _A, _F, _K0, _LON0
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x -= 500000.0
    mm = y / k0
    mu = mm / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2); t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2
          - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
          + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
          + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lon), math.degrees(lat)


def round_coords(obj, dp=COORD_DP):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), dp) for v in obj]
        return [round_coords(o, dp) for o in obj]
    return obj


def clean(geom, simplify_m, min_part_m2=MIN_PART_M2, min_hole_m2=None, dp=COORD_DP):
    """Simplify in metres, drop crumbs and pinholes, hand back EPSG:4326, rounded.

    Dropping the pinholes is what keeps these files small: a raster vectorised straight out of a
    flood model is riddled with them — the 26 risk areas carry 92 690 interior rings against 2 444
    outer ones, and they are most of the file. Filling the ones below `min_hole_m2` cuts
    risk_areas.json from 9.7 MB to 1.2 MB and overstates the covered area by 0.7 %, which is well
    inside the model's own resolution."""
    if geom.is_empty:
        return None
    hole = min_part_m2 if min_hole_m2 is None else min_hole_m2
    parts = []
    for p in getattr(geom, "geoms", [geom]):
        if p.area < min_part_m2:
            continue
        keep = [r for r in p.interiors if Polygon(r).area >= hole]
        parts.append(Polygon(p.exterior, keep) if len(keep) != len(p.interiors) else p)
    if not parts:
        return None
    g = unary_union(parts).simplify(simplify_m, preserve_topology=True).buffer(0)
    if g.is_empty:
        return None
    gj = mapping(transform(utm32_to_wgs84, g))
    return {"type": gj["type"], "coordinates": round_coords(gj["coordinates"], dp)}


def load_kommuner():
    gj = json.loads(GEO.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        out.append({"code": str(p.get("kode") or p.get("kommunekode") or "").zfill(4),
                    "name": p.get("navn") or p.get("name") or "",
                    "geom": transform(wgs84_to_utm32, shape(f["geometry"])).buffer(0)})
    return out


def budget(paths_root=OUT):
    over = []
    total = 0
    for p in sorted(paths_root.rglob("*.json")):
        mb = p.stat().st_size / 1e6
        total += mb
        if mb > MAX_FILE_MB:
            over.append((p.relative_to(ROOT), mb))
    print(f"\nsize budget: climate folder {total:.1f} MB (limit {MAX_FOLDER_MB:.0f} MB) · "
          f"{len(over)} file(s) over {MAX_FILE_MB:.0f} MB")
    for p, mb in over:
        print(f"  ⚠ {p} {mb:.2f} MB — raise the per-file tolerance for it and log the reason")
    if total > MAX_FOLDER_MB:
        print(f"  ⚠ folder over budget by {total - MAX_FOLDER_MB:.1f} MB")
    return total, over


# ---------- risk areas ----------
def do_risk_areas():
    src = RAW / "risk_areas_2024.geojson"
    if not src.exists():
        sys.exit(f"{src.relative_to(ROOT)} missing — run "
                 "scripts/fetch_flood_official.py --areas")
    d = json.loads(src.read_text(encoding="utf-8"))
    feats = []
    for f in d["features"]:
        g = transform(wgs84_to_utm32, shape(f["geometry"])).buffer(0)
        geom = clean(g, RISK_SIMPLIFY_M, min_part_m2=RISK_MIN_PART_M2,
                     min_hole_m2=RISK_MIN_HOLE_M2, dp=RISK_COORD_DP)
        if geom is None:
            continue
        p = f["properties"]
        feats.append({"type": "Feature",
                      "properties": {"area_id": p["area_id"], "area_name": p["area_name"],
                                     "designation": p["designation"],
                                     "kommuner": p["kommuner"],
                                     "kommuner_marginal": p.get("kommuner_marginal") or [],
                                     "area_km2": p["area_km2"]},
                      "geometry": geom})
    meta = dict(d.get("meta") or {})
    meta.update({"built": dt.date.today().isoformat(), "hazard": "risk_area", "horizon": "today",
                 "method": f"OD_risikoomraader_2024 group 16, dissolved per area, simplified "
                           f"{RISK_SIMPLIFY_M:.0f} m in EPSG:25832, parts under "
                           f"{RISK_MIN_PART_M2 / 10000:.0f} ha and holes under "
                           f"{RISK_MIN_HOLE_M2 / 10000:.1f} ha dropped (+0.7 % area), "
                           f"EPSG:4326 at {RISK_COORD_DP} decimals",
                 "source": "Miljøstyrelsen — EU Floods Directive cycle 2022-2027, plantrin 1 (2024)",
                 "level_cm": None, "schema": SCHEMA, "updated": meta.get("fetched")})
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "risk_areas.json"
    p.write_text(json.dumps({"type": "FeatureCollection", "meta": meta, "features": feats},
                            ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {p.relative_to(ROOT)}: {len(feats)} areas, {p.stat().st_size / 1e6:.2f} MB "
          f"(from {src.stat().st_size / 1e6:.0f} MB raw)")
    budget()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--risk-areas", action="store_true")
    ap.add_argument("--horizon", choices=["today", "2050", "2100"])
    a = ap.parse_args()
    if not (a.risk_areas or a.horizon):
        ap.error("pick --risk-areas and/or --horizon")
    if a.risk_areas:
        do_risk_areas()
    if a.horizon:
        from climate_surge import do_surge          # noqa: PLC0415 — keeps the raster code apart
        do_surge(a.horizon)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
