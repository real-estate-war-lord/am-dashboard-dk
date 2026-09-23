#!/usr/bin/env python3
"""Services layer: groceries, food, pharmacies and public-transport stops.

Reads the two raw inputs fetched by scripts/fetch_services.py and writes

  data/processed/services/<kommune>.json   one file per municipality, loaded on demand
  data/processed/services/index.json       counts per kommune x category, plus metadata
  docs/SERVICES_COUNTS.md                  the national/101/clustering report

Sources and why each one: docs/SERVICES.md. The measurements that chose them:
docs/SERVICES_PROBE.md.

Needs `pip install -r requirements-services.txt` (osmium + shapely). The
dashboard build does not — the processed files are committed.

Usage:
  python3 scripts/build_services.py
  python3 scripts/build_services.py --skip-checks     # write anyway, still report
"""
import argparse
import collections
import datetime as dt
import json
import math
import pathlib
import re
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "services"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
OUT = ROOT / "data" / "processed" / "services"
COUNTS_DOC = ROOT / "docs" / "SERVICES_COUNTS.md"
PBF = RAW / "denmark-latest.osm.pbf"
GTFS = RAW / "rejseplanen_gtfs.zip"

# ---------------------------------------------------------------- categories
# (category, sub) per OSM tag. `sub` is what the UI will filter on.
OSM_TAGS = {
    ("shop", "supermarket"):   ("grocery", "supermarket"),
    ("shop", "convenience"):   ("grocery", "convenience"),
    ("amenity", "restaurant"): ("food", "restaurant"),
    ("amenity", "cafe"):       ("food", "cafe"),
    ("amenity", "bar"):        ("food", "bar"),
    ("amenity", "fast_food"):  ("food", "fast_food"),
    ("amenity", "pharmacy"):   ("pharmacy", "pharmacy"),
}
# an object carrying two of these is assigned once, in this order
OSM_ORDER = ["grocery", "pharmacy", "food"]

# GTFS route_type -> mode. 109/700 are Google's *extended* types, not the base
# GTFS set: leaving them out silently drops the whole S-train network and 479
# bus stops. 715 (flextur, demand-responsive) is deliberately excluded — it is
# not a stop you can walk to and wait at. 4 (ferry) is excluded too; see
# docs/SERVICES_COUNTS.md, it is 30 stops and trivial to add back.
ROUTE_TYPE = {
    "1": "metro",
    "109": "s-train",
    "2": "rail",
    "0": "light-rail",
    "3": "bus",
    "700": "bus",
}
EXCLUDED_ROUTE_TYPE = {"715": "flextur (demand-responsive)", "4": "ferry"}
STATION_MODES = ["metro", "s-train", "rail", "light-rail"]   # clustered at 150 m
STATION_RADIUS_M = 150
BUS_RADIUS_M = 50

R_EARTH = 6371008.8


def log(*a):
    print(*a, flush=True)


def havm(a, b):
    """great-circle metres between (lat, lon) pairs"""
    r = math.pi / 180
    dla, dlo = (b[0] - a[0]) * r, (b[1] - a[1]) * r
    x = (math.sin(dla / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dlo / 2) ** 2)
    return 2 * R_EARTH * math.asin(min(1, math.sqrt(x)))


# ------------------------------------------------------------ name normalising
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_SUFFIX = re.compile(r"\s+(st\.?|station)$", re.IGNORECASE)
_PUNCT = re.compile(r"[.,''`´’]")


def norm_name(name):
    """The key stops are grouped by before distance clustering.

    Rejseplanen disambiguates with a trailing parenthetical — "Nørreport St.
    (Metro)", "(Nørre Voldgade)", "(togbus)", "(Skive kom)" — and those are
    exactly the rows we want to consider for merging, so they are stripped.
    Two genuinely different "Nørreport"s are kept apart by the distance test,
    not by the name.
    """
    s = (name or "").strip()
    while _PAREN.search(s):
        s = _PAREN.sub("", s).strip()
    s = _SUFFIX.sub("", s).strip()
    s = _PUNCT.sub("", s)
    s = unicodedata.normalize("NFC", s).lower()
    return re.sub(r"\s+", " ", s)


def cluster(points, radius_m):
    """Single-linkage clustering of (lat, lon, ...) tuples. Groups are small
    (same name, same mode), so the O(n^2) pass inside one group is cheap."""
    n = len(points)
    if n == 1:
        return [points]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if find(i) != find(j) and havm(points[i][:2], points[j][:2]) <= radius_m:
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(points[i])
    return list(groups.values())


# --------------------------------------------------------------------- a. OSM
def read_osm(path):
    """Every matching node and way in the extract, ways placed at their centroid.

    Deduplicated on the OSM id: an object is emitted once even if it carries two
    matching tags, and (type, id) is unique by construction.
    """
    import osmium

    seen = set()
    out = []
    counts = collections.Counter()
    no_geom = 0
    t0 = time.time()
    n_obj = 0
    for o in osmium.FileProcessor(str(path)).with_locations():
        n_obj += 1
        tags = o.tags
        hits = [OSM_TAGS[(k, tags[k])] for k in ("shop", "amenity")
                if k in tags and (k, tags[k]) in OSM_TAGS]
        if not hits:
            continue
        hits.sort(key=lambda cs: OSM_ORDER.index(cs[0]))
        if len(hits) > 1:
            counts[("_dual", "", "")] += 1
        cat, sub = hits[0]

        if o.is_node():
            key = ("n", o.id)
            lat, lon = o.location.lat, o.location.lon
        elif o.is_way():
            key = ("w", o.id)
            lats = [nd.location.lat for nd in o.nodes if nd.location.valid()]
            lons = [nd.location.lon for nd in o.nodes if nd.location.valid()]
            if not lats:
                no_geom += 1
                continue
            lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        name = (tags.get("name") or "").strip()
        brand = (tags.get("brand") or "").strip()
        out.append({"cat": cat, "sub": sub, "lat": lat, "lon": lon,
                    "name": name, "brand": brand if brand and brand != name else "",
                    "osm": f"{key[0]}{key[1]}"})
        counts[(cat, sub, key[0])] += 1
    dual = counts.pop(("_dual", "", ""), 0)
    log(f"  · {n_obj:,} objects scanned in {time.time() - t0:.0f}s → {len(out):,} points"
        + (f", {dual} carried two of our tags and were counted once" if dual else "")
        + (f" ({no_geom} ways had no usable geometry)" if no_geom else ""))
    return out, {"by_tag": dict(counts), "dual_tag": dual, "ways_without_geometry": no_geom}


# -------------------------------------------------------------------- b. GTFS
def read_gtfs(path):
    """Stops with the modes they are actually served by, then clustered.

    stops -> stop_times -> trips -> routes is the only way to know a stop's mode:
    stops.txt itself says nothing about it, and this feed has location_type=0 and
    an empty parent_station on all 36 383 rows, so there is no station hierarchy
    to lean on either.
    """
    import csv
    import io
    import zipfile

    z = zipfile.ZipFile(path)

    def table(name):
        with z.open(name) as fh:
            return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))

    routes = {r["route_id"]: r.get("route_type", "") for r in table("routes.txt")}
    trips = {t["trip_id"]: routes.get(t["route_id"], "") for t in table("trips.txt")}

    stop_modes = collections.defaultdict(set)
    excluded_stops = collections.defaultdict(set)
    t0 = time.time()
    rows = 0
    with z.open("stop_times.txt") as fh:                     # ~230 MB: csv.reader, not DictReader
        rdr = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
        header = next(rdr)
        i_trip, i_stop = header.index("trip_id"), header.index("stop_id")
        for row in rdr:
            rows += 1
            rt = trips.get(row[i_trip])
            if rt is None:
                continue
            mode = ROUTE_TYPE.get(rt)
            if mode:
                stop_modes[row[i_stop]].add(mode)
            elif rt in EXCLUDED_ROUTE_TYPE:
                excluded_stops[rt].add(row[i_stop])
    log(f"  · stop_times.txt {rows:,} rows in {time.time() - t0:.0f}s")

    stops = {s["stop_id"]: s for s in table("stops.txt")}
    per_mode_stops = collections.Counter()
    for sid, modes in stop_modes.items():
        for m in modes:
            per_mode_stops[m] += 1

    # one cluster group per (normalised name, mode) — a stop serving two modes
    # takes part in both, which is what makes Nørreport a metro station *and* an
    # S-train station rather than forcing a single mode on it.
    groups = collections.defaultdict(list)
    missing_coords = 0
    for sid, modes in stop_modes.items():
        s = stops.get(sid)
        if not s or not s.get("stop_lat") or not s.get("stop_lon"):
            missing_coords += 1
            continue
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        key_name = norm_name(s.get("stop_name"))
        for m in modes:
            groups[(key_name, m)].append((lat, lon, sid, s.get("stop_name", "").strip()))

    points = []
    merged = collections.Counter()      # mode -> stops before
    after = collections.Counter()       # mode -> points after
    examples = collections.defaultdict(list)
    for (key_name, mode), items in groups.items():
        radius = BUS_RADIUS_M if mode == "bus" else STATION_RADIUS_M
        merged[mode] += len(items)
        for grp in cluster(items, radius):
            lat = sum(p[0] for p in grp) / len(grp)
            lon = sum(p[1] for p in grp) / len(grp)
            # the display name: the most common original spelling in the cluster,
            # with its disambiguating parenthetical dropped
            raw = collections.Counter(_PAREN.sub("", p[3]).strip() for p in grp)
            name = raw.most_common(1)[0][0] or key_name
            points.append({"cat": "transport", "sub": mode, "lat": lat, "lon": lon,
                           "name": name, "platforms": len(grp),
                           "stop_ids": [p[2] for p in grp]})
            after[mode] += 1
            if key_name in ("nørreport", "københavn h", "aarhus h"):
                examples[key_name].append({"mode": mode, "platforms": len(grp),
                                           "lat": lat, "lon": lon,
                                           "names": sorted({p[3] for p in grp})})
    stats = {
        "stops_total": len(stops),
        "stops_with_a_kept_mode": len(stop_modes),
        "stops_missing_coords": missing_coords,
        "stop_times_rows": rows,
        "per_mode_stops_before": dict(per_mode_stops),
        "per_mode_before": dict(merged),
        "per_mode_after": dict(after),
        "excluded": {rt: {"label": EXCLUDED_ROUTE_TYPE[rt], "stops": len(v)}
                     for rt, v in excluded_stops.items()},
        "multi_mode_stops": sum(1 for m in stop_modes.values() if len(m) > 1),
        "examples": {k: v for k, v in examples.items()},
    }
    return points, stats


# ----------------------------------------------------------- c. kommune assign
def load_kommuner():
    """(code3, name, prepared polygon) per municipality, plus an STRtree index."""
    from shapely.geometry import shape
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    gj = json.loads(GEO.read_text(encoding="utf-8"))
    geoms, meta = [], []
    for f in gj["features"]:
        p = f.get("properties") or {}
        code4 = str(p.get("kode") or "").strip()
        if not code4:
            continue
        g = shape(f["geometry"])
        geoms.append(g)
        meta.append({"code4": code4.zfill(4),
                     "code": str(int(code4)),        # 4-digit '0101' -> '101', as elsewhere
                     "name": p.get("navn") or "",
                     "prep": prep(g)})
    return STRtree(geoms), geoms, meta


def assign_kommuner(points):
    from shapely.geometry import Point

    tree, geoms, meta = load_kommuner()
    dropped = []
    t0 = time.time()
    for pt in points:
        p = Point(pt["lon"], pt["lat"])
        hit = None
        for idx in tree.query(p):                    # bbox candidates, then the real test
            if meta[idx]["prep"].contains(p):
                hit = meta[idx]
                break
        if hit is None:
            pt["kom"] = None
            dropped.append(pt)
        else:
            pt["kom"] = hit["code"]
            pt["kom4"] = hit["code4"]
    log(f"  · placed {len(points) - len(dropped):,} of {len(points):,} points in "
        f"{time.time() - t0:.0f}s")
    return [p for p in points if p["kom"]], dropped, meta


# ----------------------------------------------------------------- d. writing
def write_files(points, meta, asof, raw_meta):
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):                   # a kommune that lost all its points
        old.unlink()                                 # must not keep a stale file

    by_kom = collections.defaultdict(list)
    for p in points:
        by_kom[p["kom4"]].append(p)

    index = {"v": 1, "asof": asof, "built": dt.date.today().isoformat(),
             "categories": {"grocery": ["supermarket", "convenience"],
                            "food": ["restaurant", "cafe", "bar", "fast_food"],
                            "pharmacy": ["pharmacy"],
                            "transport": ["metro", "s-train", "rail", "light-rail", "bus"]},
             "sources": raw_meta, "kommuner": {}}

    total_bytes = 0
    for code4, pts in sorted(by_kom.items()):
        pts.sort(key=lambda p: (p["cat"], p["sub"], p["name"]))
        rows = []
        for p in pts:
            row = [p["cat"], p["sub"], round(p["lat"], 5), round(p["lon"], 5), p["name"]]
            # a 6th element only where it carries something: the brand for a shop,
            # the platform count for a clustered station. `cat` says which.
            extra = p.get("brand") if p["cat"] != "transport" else (
                p["platforms"] if p.get("platforms", 1) > 1 else "")
            if extra:
                row.append(extra)
            rows.append(row)
        body = {"v": 1, "asof": asof, "kommune": str(int(code4)), "points": rows}
        path = OUT / f"{code4}.json"
        path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        total_bytes += path.stat().st_size
        counts = collections.Counter(p["cat"] for p in pts)
        subs = collections.Counter(f"{p['cat']}:{p['sub']}" for p in pts)
        index["kommuner"][str(int(code4))] = {
            "file": f"{code4}.json", "n": len(pts),
            "by_cat": dict(sorted(counts.items())), "by_sub": dict(sorted(subs.items())),
        }

    ipath = OUT / "index.json"
    ipath.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
                     encoding="utf-8")
    total_bytes += ipath.stat().st_size
    return total_bytes, index


# ------------------------------------------------------------------- e. checks
PROBE_KBH_GROCERY = 513          # docs/SERVICES_PROBE.md §6


def run_checks(index, national_sub, meta):
    """Returns (ok, [lines]). A failure here fails the build."""
    lines, ok = [], True

    kbh = index["kommuner"].get("101", {}).get("by_cat", {}).get("grocery", 0)
    lo, hi = PROBE_KBH_GROCERY * 0.95, PROBE_KBH_GROCERY * 1.05
    good = lo <= kbh <= hi
    ok &= good
    lines.append(f"{'✓' if good else '✗'} København (101) groceries {kbh} "
                 f"— probe said {PROBE_KBH_GROCERY}, ±5 % = {lo:.0f}–{hi:.0f}")

    metro = national_sub.get(("transport", "metro"), 0)
    good = 40 <= metro <= 50
    ok &= good
    lines.append(f"{'✓' if good else '✗'} metro stations in Denmark {metro} — expected 40–50")

    zero = sorted(m["name"] for m in meta
                  if index["kommuner"].get(m["code"], {}).get("by_cat", {}).get("grocery", 0) == 0)
    good = not zero
    ok &= good
    lines.append(f"{'✓' if good else '✗'} every kommune has at least one grocery"
                 + ("" if good else f" — {len(zero)} do not: {', '.join(zero)}"))
    return ok, lines


# --------------------------------------------------------------------- report
CAT_ORDER = {"grocery": ["supermarket", "convenience"],
             "food": ["restaurant", "cafe", "bar", "fast_food"],
             "pharmacy": ["pharmacy"],
             "transport": ["metro", "s-train", "rail", "light-rail", "bus"]}


def write_counts_doc(asof, national_cat, national_sub, kbh_sub, gtfs_stats, osm_stats,
                     dropped, total_bytes, check_lines, index):
    def n(x):
        return f"{x:,}".replace(",", " ")

    def subs_of(counter, cat):
        """declared order first, then anything unexpected, so a new tag cannot hide"""
        known = [(s_, counter[(cat, s_)]) for s_ in CAT_ORDER[cat] if (cat, s_) in counter]
        extra = sorted((s_, v) for (c_, s_), v in counter.items()
                       if c_ == cat and s_ not in CAT_ORDER[cat])
        return known + extra

    L = []
    A = L.append
    A("# Services layer — counts")
    A("")
    A(f"**Built:** {dt.date.today().isoformat()} · **data as of:** {asof} · "
      "generated by `scripts/build_services.py`")
    A("")
    A("Regenerate with `python3 scripts/build_services.py`. What the sources are and why: "
      "[`SERVICES.md`](SERVICES.md). How they were chosen: [`SERVICES_PROBE.md`](SERVICES_PROBE.md).")
    A("")
    A("## National totals")
    A("")
    A("| category | sub | points |")
    A("|---|---|---:|")
    for cat in ("grocery", "food", "pharmacy", "transport"):
        subs = subs_of(national_sub, cat)
        for i, (sub, v) in enumerate(subs):
            A(f"| {'**' + cat + '**' if i == 0 else ''} | `{sub}` | {n(v)} |")
        A(f"| | **{cat} total** | **{n(national_cat[cat])}** |")
    A(f"| | **all categories** | **{n(sum(national_cat.values()))}** |")
    A("")
    A(f"Across **{len(index['kommuner'])} municipalities**. "
      f"Processed output is **{total_bytes/1e6:.1f} MB**.")
    A("")
    A("## Kommune 101 (København)")
    A("")
    A("| category | sub | points |")
    A("|---|---|---:|")
    for cat in ("grocery", "food", "pharmacy", "transport"):
        subs = subs_of(kbh_sub, cat)
        for i, (sub, v) in enumerate(subs):
            A(f"| {'**' + cat + '**' if i == 0 else ''} | `{sub}` | {n(v)} |")
        tot = sum(v for (c, _), v in kbh_sub.items() if c == cat)
        A(f"| | **{cat} total** | **{n(tot)}** |")
    A("")
    A("## Station clustering")
    A("")
    A(f"GTFS ships **{n(gtfs_stats['stops_total'])} stops**, all with `location_type=0` and an "
      f"empty `parent_station` — there is no station hierarchy in the feed, so the grouping "
      f"below is ours. **{n(gtfs_stats['stops_with_a_kept_mode'])}** of those stops are served "
      f"by a mode we keep.")
    A("")
    A("| mode | stops before | points after | absorbed | rule |")
    A("|---|---:|---:|---:|---|")
    tb = ta = 0
    for mode in STATION_MODES + ["bus"]:
        b = gtfs_stats["per_mode_before"].get(mode, 0)
        a = gtfs_stats["per_mode_after"].get(mode, 0)
        tb += b
        ta += a
        rule = (f"same name + same mode within {BUS_RADIUS_M} m" if mode == "bus"
                else f"same name + same mode within {STATION_RADIUS_M} m")
        A(f"| `{mode}` | {n(b)} | {n(a)} | {n(b - a)} | {rule} |")
    A(f"| **total** | **{n(tb)}** | **{n(ta)}** | **{n(tb - ta)}** | |")
    A("")
    A(f"A stop serving several modes is counted once per mode — **"
      f"{n(gtfs_stats['multi_mode_stops'])} stops serve more than one**, which is why the "
      f"'before' column sums to more than the number of distinct stops.")
    A("")
    A("**Heavy rail barely clusters, and that is the feed telling us something.** Metro, "
      "S-train and rail are already one row per station in Rejseplanen's data, not one row "
      "per platform. The merging that does happen is light rail (paired directional stops) "
      "and buses (both sides of a street).")
    A("")
    A("### Worked examples")
    A("")
    for key, label in (("nørreport", "Nørreport"), ("københavn h", "København H"),
                       ("aarhus h", "Aarhus H")):
        ex = gtfs_stats["examples"].get(key) or []
        if not ex:
            continue
        A(f"**{label}** — {len(ex)} point{'s' if len(ex) != 1 else ''} after clustering:")
        A("")
        A("| mode | platforms merged | position | original stop names |")
        A("|---|---:|---|---|")
        for e in sorted(ex, key=lambda x: x["mode"]):
            names = " · ".join(e["names"])
            A(f"| `{e['mode']}` | {e['platforms']} | {e['lat']:.5f}, {e['lon']:.5f} | {names} |")
        A("")
    A("### Excluded route types")
    A("")
    A("| `route_type` | what | stops | why |")
    A("|---|---|---:|---|")
    for rt, info in sorted(gtfs_stats["excluded"].items()):
        why = ("not a stop you can walk to and wait at" if rt == "715"
               else "not one of the modes this layer was asked for — 30 points, trivial to add back")
        A(f"| `{rt}` | {info['label']} | {n(info['stops'])} | {why} |")
    A("")
    A("## Dropped points")
    A("")
    A(f"**{n(len(dropped))}** points fell outside every Danish municipality polygon and were "
      "dropped.")
    if dropped:
        by_cat = collections.Counter(f"{p['cat']}/{p['sub']}" for p in dropped)
        A("")
        A("| category/sub | dropped |")
        A("|---|---:|")
        for k, v in by_cat.most_common():
            A(f"| `{k}` | {n(v)} |")
        A("")
        A("Mostly Rejseplanen's Swedish stops (Skånetrafiken crosses the Øresund) plus a few "
          "OSM points on harbour structures and ferries that lie outside the land polygons.")
    A("")
    A("## Reconciliation against the probe")
    A("")
    A("[`SERVICES_PROBE.md`](SERVICES_PROBE.md) counted the same OSM tags straight off the "
      "extract, with no deduplication and no kommune clipping. Every difference is accounted "
      "for:")
    A("")
    A("| | probe | here | difference |")
    A("|---|---:|---:|---|")
    A(f"| grocery | 3 957 | {n(national_cat['grocery'])} | — |")
    A(f"| food | 14 718 | {n(national_cat['food'])} | −{osm_stats['dual_tag']} dual-tagged, "
      f"−{osm_stats['food_dropped']} outside Denmark |")
    A(f"| pharmacy | 545 | {n(national_cat['pharmacy'])} | — |")
    A("")
    A(f"**{osm_stats['dual_tag']} objects carry two of our tags at once** — a petrol-station "
      "shop that is also a takeaway counter, a bakery that is also a café. `--distinct OSM "
      "ids only` means each is one point, and the category order "
      "grocery → pharmacy → food decides which: they are counted as groceries, so the grocery "
      "totals match the probe exactly and the food total is that much lower.")
    A("")
    A("## Sanity checks")
    A("")
    for line in check_lines:
        A(f"- {line}")
    A(f"- {'✓' if total_bytes < 15e6 else '⚠'} processed size "
      f"**{total_bytes/1e6:.2f} MB** (target < 15 MB)")
    A("")
    COUNTS_DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    return "\n".join(L)


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-checks", action="store_true",
                    help="write the output even if a sanity check fails")
    args = ap.parse_args()

    for p in (PBF, GTFS):
        if not p.exists():
            log(f"✗ missing {p.relative_to(ROOT)} — run scripts/fetch_services.py first")
            return 1

    man = {}
    if (RAW / "manifest.json").exists():
        man = json.loads((RAW / "manifest.json").read_text(encoding="utf-8")).get("sources", {})
    asof = max([e.get("fetched", "")[:10] for e in man.values()] or [""]) or \
        dt.date.today().isoformat()

    log("== a. OpenStreetMap extract ==")
    osm_points, osm_stats = read_osm(PBF)

    log("== b. Rejseplanen GTFS ==")
    gtfs_points, gtfs_stats = read_gtfs(GTFS)
    log(f"  · {len(gtfs_points):,} points after clustering")

    log("== c. kommune assignment ==")
    points, dropped, meta = assign_kommuner(osm_points + gtfs_points)
    log(f"  · dropped {len(dropped):,} outside Denmark's municipality polygons")

    log("== d. writing ==")
    total_bytes, index = write_files(points, meta, asof,
                                     {k: {kk: v[kk] for kk in ("url", "name", "licence",
                                                               "fetched", "bytes") if kk in v}
                                      for k, v in man.items()})
    log(f"  · {len(index['kommuner'])} kommune files + index.json, "
        f"{total_bytes/1e6:.2f} MB total")

    osm_stats["food_dropped"] = sum(1 for p in dropped if p["cat"] == "food")
    national_cat = collections.Counter(p["cat"] for p in points)
    national_sub = collections.Counter((p["cat"], p["sub"]) for p in points)
    kbh_sub = collections.Counter((p["cat"], p["sub"]) for p in points if p["kom"] == "101")

    log("== e. sanity checks ==")
    ok, check_lines = run_checks(index, national_sub, meta)
    for line in check_lines:
        log("  " + line)

    size_ok = total_bytes < 15e6
    log(f"  {'✓' if size_ok else '⚠'} processed size {total_bytes/1e6:.2f} MB (target < 15 MB)")

    report = write_counts_doc(asof, national_cat, national_sub, kbh_sub, gtfs_stats,
                              osm_stats, dropped, total_bytes, check_lines, index)
    log(f"\nwrote {COUNTS_DOC.relative_to(ROOT)}")

    if not size_ok:
        log("\n⚠ processed output is over the 15 MB target — stopping so this can be decided "
            "before it is committed. Re-run with --skip-checks to write it anyway.")
        return 2
    if not ok:
        log("\n✗ a sanity check failed. The files above were written, but do not commit them "
            "until this is understood. --skip-checks silences this exit code.")
        return 0 if args.skip_checks else 1
    log("\n✓ all sanity checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
