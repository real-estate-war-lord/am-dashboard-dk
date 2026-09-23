#!/usr/bin/env python3
"""Build data/geo/infra_projects.geojson — major upcoming infrastructure projects in Denmark.

Inputs
  data/external/infra_projects.csv      hand-maintained project list (the list of record; see docs/INFRA.md)
  data/raw/fingerplan/<layer>.geojson   scripts/fetch_infra_fingerplan.py (Greater Copenhagen)
  Overpass API                          geometry outside the Fingerplan's area (cached in data/raw/osm/)
  data/geo/kommuner.geojson             to compute which municipalities a project touches

Output
  data/geo/infra_projects.geojson       FeatureCollection, WGS84, one feature per CSV row
  data/processed/infra_index.json       which projects touch each municipality, postal code and
                                        Copenhagen quarter (+ points within 1.2 km of the polygon)

`geometry_source` in the CSV decides where a geometry comes from:
  fingerplan:<layer>:all | fingerplan:<layer>:<attr>=<value>   vendored Fingerplan 2019 features
  osm:<Overpass QL fragment>                                   e.g. osm:way["name"="Storstrømsbroen"](bbox)
  manual:<lon>,<lat> | manual:wkt:<WKT>                        a coordinate or geometry written by hand — a
                                                               schematic corridor, never an official alignment
  stations                                                     a line through this project's own stations
  (empty)                                                      no geometry — the feature still carries its data

`map: false` in the CSV keeps a project out of the map layer (a nationwide systems programme has no
alignment); it is still in the file, for the pipeline table.

A row whose source yields nothing keeps `"geometry": null`; nothing is invented to fill a gap.
Lines are simplified to ~20 m. Needs: pip3 install shapely (pdfplumber only for the PDF parser).

Usage: python3 scripts/build_infra.py [--no-osm]
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import math
import urllib.error
import urllib.parse
import urllib.request

from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, Polygon, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union
from shapely import wkt as shapely_wkt

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "external" / "infra_projects.csv"
FP = ROOT / "data" / "raw" / "fingerplan"
OSM_CACHE = ROOT / "data" / "raw" / "osm"
OUT = ROOT / "data" / "geo" / "infra_projects.geojson"
IDX = ROOT / "data" / "processed" / "infra_index.json"
NEAR_M = 1200                        # a station or site this close still serves the area
STATUS_ORDER = {"construction": 0, "decided": 1, "study": 2, "opened": 3}
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "am-dashboard-dk/2.1 (+https://github.com/real-estate-war-lord/am-dashboard-dk)"}
SIMPLIFY_DEG = 20 / 111_320          # ~20 m at this latitude, in degrees
TYPES = {"metro", "letbane", "brt", "rail", "road", "bridge_tunnel", "urban_dev", "hospital", "university", "public_building"}
STATUSES = {"study", "decided", "construction", "opened"}


def short_label(row):
    """Map label for zoomed-out views: the CSV's `label_short`, else the first three words of the name."""
    s = (row.get("label_short") or "").strip()
    return s or " ".join((row["name"] or "").split()[:3])


def num(v, cast=float):
    v = (v or "").strip()
    return cast(v) if v else None


# ---------- geometry sources ----------

def fingerplan(spec):
    """fingerplan:<layer>:all | fingerplan:<layer>:<attr>=<value> → merged shapely geometry."""
    layer, _, flt = spec.partition(":")
    path = FP / f"{layer}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(ROOT)} — run scripts/fetch_infra_fingerplan.py")
    feats = json.loads(path.read_text(encoding="utf-8"))["features"]
    if flt and flt != "all":
        key, _, want = flt.partition("=")
        feats = [f for f in feats if str((f.get("properties") or {}).get(key)) == want]
    geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
    return unary_union(geoms) if geoms else None


def overpass(ql, offline=False):
    """Overpass QL fragment → shapely geometry (cached per query in data/raw/osm/)."""
    OSM_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OSM_CACHE / (hashlib.sha1(ql.encode("utf-8")).hexdigest()[:16] + ".json")
    if not cache.exists():
        if offline:
            return None
        body = f"[out:json][timeout:90];({ql};);out geom;"          # the ; inside the group is required
        for attempt in range(4):
            try:
                req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": body}).encode(), headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r:
                    cache.write_bytes(r.read())
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                if attempt == 3:
                    print(f"    overpass failed after 4 tries: {e}", file=sys.stderr)
                    return None
                time.sleep(15 * (attempt + 1))         # Overpass rate-limits hard (429) and times out (504)
        time.sleep(5)
    els = json.loads(cache.read_text(encoding="utf-8")).get("elements", [])
    lines = [LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in els
             if e.get("type") == "way" and len(e.get("geometry") or []) > 1]
    pts = [Point(e["lon"], e["lat"]) for e in els if e.get("type") == "node" and e.get("lon") is not None]
    if lines:
        return unary_union(lines)
    if pts:
        return unary_union(pts)
    return None


def manual(spec):
    if spec.startswith("wkt:"):
        return shapely_wkt.loads(spec[4:])
    lon, _, lat = spec.partition(",")
    return Point(float(lon), float(lat))


SITE_TYPES = {"hospital", "university", "public_building"}   # a place, not a corridor


def want_kind(row):
    """What shape the project should end up as: stations and single sites are points, development
    areas polygons, everything else a corridor."""
    if row["parent_id"] or row["type"] in SITE_TYPES:
        return "point"
    return "polygon" if row["type"] == "urban_dev" else "line"


def coerce(geom, kind):
    """A source may hand back more (or less) than the project needs: a way for a station point, a
    bundle of lines for a corridor. Reduce it to the kind the project wants, without inventing shape."""
    if geom is None or geom.is_empty:
        return None
    if kind == "point":
        return geom if isinstance(geom, Point) else geom.representative_point()
    if kind == "polygon":
        if isinstance(geom, (Polygon,)) or geom.geom_type in ("MultiPolygon",):
            return geom
        if isinstance(geom, (LineString, MultiLineString)):
            closed = [Polygon(g.coords) for g in (geom.geoms if isinstance(geom, MultiLineString) else [geom])
                      if len(g.coords) > 3 and g.is_closed]
            if closed:
                return unary_union(closed)
        return geom                     # keep what we have; reported as a kind mismatch
    if isinstance(geom, (MultiPoint, Point)):
        return geom
    return geom.simplify(SIMPLIFY_DEG, preserve_topology=False)


# ---------- municipalities ----------

def load_kommuner():
    p = ROOT / "data" / "geo" / "kommuner.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
        code = str(f["properties"].get("kode") or "").lstrip("0")
        out.append((code, f["properties"].get("navn"), shape(f["geometry"])))
    return out


def kommuner_of(geom, komm, override=""):
    """Municipalities the geometry touches. `kommuner_override` in the CSV fills in the cases the
    spatial join cannot answer — reclaimed land (Lynetteholm) is outside every DAGI polygon."""
    hits = [code for code, _name, poly in komm if geom is not None and poly.intersects(geom)]
    if not hits and override:
        return [c.strip() for c in override.split(",") if c.strip()]
    return sorted(set(hits), key=int)


# ---------- which projects serve which area ----------

def metric(geom, lat0):
    """Local equal-distance projection (metres) — good to a few metres over Denmark, and it keeps the
    build free of pyproj. Used for the 1.2 km search radius and for lengths and areas."""
    k = math.cos(math.radians(lat0)) * 111_320.0
    return shapely_transform(lambda x, y, z=None: (x * k, y * 111_320.0), geom)


def polygons_of(path, code_key, name_key=None):
    if not path.exists():
        return []
    out = []
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        pr = f["properties"]
        code = str(pr.get(code_key) or "")
        if code:
            out.append((code.lstrip("0") if code_key == "kode" else code, pr.get(name_key) if name_key else None, shape(f["geometry"])))
    return out


def build_index(feats):
    """{"<level>:<code>": {projects: [...], projects_upcoming, stations_planned_1200m}}.
    A project counts for an area when its geometry touches the polygon, and a station or site point
    also counts when it lies within 1.2 km of it."""
    geo = ROOT / "data" / "geo"
    levels = [("kommune", polygons_of(geo / "kommuner.geojson", "kode", "navn")),
              ("postnr", polygons_of(geo / "postnumre.geojson", "nr", "navn")),
              ("kvarter", polygons_of(geo / "cph_kvarterer.geojson", "kvarternr", "kvarternavn"))]
    projects = [(f["properties"], shape(f["geometry"])) for f in feats if f.get("geometry")]
    idx = {}
    for level, polys in levels:
        for code, _name, poly in polys:
            lat0 = poly.centroid.y
            pm = metric(poly, lat0)
            hits = []
            for pr, g in projects:
                point_like = g.geom_type == "Point"
                if poly.intersects(g):
                    dist = 0.0
                elif point_like:
                    dist = pm.distance(metric(g, lat0))
                    if dist > NEAR_M:
                        continue
                else:
                    continue
                hits.append({"id": pr["id"], "name": pr["name"], "label_short": pr["label_short"], "type": pr["type"],
                             "status": pr["status"], "open_year": pr["open_year"], "open_window": pr["open_window"],
                             "distance_m": round(dist)})
            hits.sort(key=lambda h: (STATUS_ORDER.get(h["status"], 9), h["open_year"] or 9999, h["name"]))
            if hits:
                idx[f"{level}:{code}"] = {
                    "projects": hits,
                    "projects_upcoming": sum(1 for h in hits if h["status"] != "opened"),
                    "stations_planned_1200m": sum(1 for h in hits if h["status"] != "opened"
                                                  and next(p for p, _g in projects if p["id"] == h["id"])["parent_id"]),
                }
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-osm", action="store_true", help="use only cached Overpass answers")
    args = ap.parse_args()
    rows = list(csv.DictReader(SRC.open(encoding="utf-8"), delimiter=";"))
    komm = load_kommuner()
    today = dt.date.today().isoformat()
    geoms, problems = {}, []

    for row in rows:                                   # pass 1: everything except the station lines
        src = (row["geometry_source"] or "").strip()
        if row["type"] not in TYPES:
            problems.append(f'{row["id"]}: unknown type {row["type"]!r}')
        if row["status"] not in STATUSES:
            problems.append(f'{row["id"]}: unknown status {row["status"]!r}')
        if src == "stations" or not src:
            continue
        kind, tag = want_kind(row), src.split(":", 1)[0]
        try:
            raw = (fingerplan(src.split(":", 1)[1]) if tag == "fingerplan"
                   else overpass(src.split(":", 1)[1], args.no_osm) if tag == "osm"
                   else manual(src.split(":", 1)[1]) if tag == "manual" else None)
        except Exception as e:                          # noqa: BLE001
            problems.append(f'{row["id"]}: {tag} failed: {e}'); raw = None
        g = coerce(raw, kind)
        if g is None:
            problems.append(f'{row["id"]}: no geometry from {src[:60]}')
        geoms[row["id"]] = g

    for row in rows:                                   # pass 2: a line through this project's stations
        if (row["geometry_source"] or "").strip() != "stations":
            continue
        pts = [geoms[r["id"]] for r in rows if r["parent_id"] == row["id"] and geoms.get(r["id"]) is not None]
        pts = [p.representative_point() if not isinstance(p, Point) else p for p in pts]
        if len(pts) < 2:
            problems.append(f'{row["id"]}: fewer than two stations with a location — no line drawn')
            geoms[row["id"]] = None
        else:
            geoms[row["id"]] = LineString([(p.x, p.y) for p in pts])

    feats = []
    for row in rows:
        g = geoms.get(row["id"])
        feats.append({
            "type": "Feature",
            "properties": {
                "id": row["id"], "name": row["name"], "label_short": short_label(row), "type": row["type"], "status": row["status"],
                "open_year": num(row["open_year"], int), "open_window": row.get("open_window") or None,
                "open_year_original": num(row["open_year_original"], int),
                "budget_mdkk": num(row["budget_mdkk"]), "agency": row["agency"] or None,
                "kommuner": kommuner_of(g, komm, row.get("kommuner_override", "")), "parent_id": row["parent_id"] or None,
                "schematic": (row["geometry_source"] or "").startswith("manual") or row["geometry_source"] == "stations",
                "map": (row.get("map") or "true").strip().lower() != "false",
                "source_url": row["source_url"], "source_doc": row["source_doc"] or None,
                "geometry_source": row["geometry_source"] or None, "updated": today, "notes": row["notes"] or None,
            },
            "geometry": mapping(g) if g is not None else None,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection",
                               "meta": {"built": today, "source_csv": str(SRC.relative_to(ROOT)),
                                        "attribution": ["Plan- og Landdistriktsstyrelsen, Fingerplan 2019",
                                                        "Transportministeriet, Status for anlægs- og byggeprojekter",
                                                        "© OpenStreetMap contributors (ODbL)"]},
                               "features": feats}, ensure_ascii=False), encoding="utf-8")

    idx = build_index(feats)
    IDX.parent.mkdir(parents=True, exist_ok=True)
    IDX.write_text(json.dumps({"built": today, "near_m": NEAR_M, "areas": idx}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    lv = {}
    for k in idx:
        lv[k.split(":")[0]] = lv.get(k.split(":")[0], 0) + 1
    print(f'wrote {IDX.relative_to(ROOT)}: {len(idx)} areas with projects ({", ".join(f"{k} {v}" for k, v in lv.items())})')

    n_geo = sum(1 for f in feats if f["geometry"])
    print(f'wrote {OUT.relative_to(ROOT)}: {len(feats)} features, {n_geo} with geometry, {len(feats) - n_geo} without')
    print(f'{"id":34} {"type":13} {"status":13} {"open":5} {"budget":>9} {"geometry":16} {"schem":5} kommuner')
    for f in feats:
        p = f["properties"]
        print(f'{p["id"]:34} {p["type"]:13} {p["status"]:13} {str(p["open_year"] or "–"):5} '
              f'{("–" if p["budget_mdkk"] is None else f"{p['budget_mdkk']:,.1f}"):>9} '
              f'{(f["geometry"]["type"] if f["geometry"] else "NONE"):16} {("yes" if p["schematic"] else "no"):5} '
              f'{",".join(p["kommuner"]) or "–"}')
    for pr in problems:
        print("  ⚠", pr)


if __name__ == "__main__":
    main()
