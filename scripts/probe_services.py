#!/usr/bin/env python3
"""Probe the candidate sources for a future "Services" layer — groceries,
restaurants/cafés, pharmacies and public-transport stops.

This is a *probe*, not a pipeline step: it answers "can we build this, from
what, at what size" and writes its findings to docs/SERVICES_PROBE.md by hand.
Nothing here is wired into `make build`, and nothing it downloads is committed.

Sources tested
  a) OSM Overpass API          — per-tag counts for kommune 101, timed
  b) Geofabrik Denmark extract — size, osmium availability, nationwide counts
  c) Rejseplanen GTFS          — stops.txt, routes.txt, route_type split
  d) Fødevarestyrelsen Smiley  — fields, coordinates?, branche split, 101 count

Cross-checks (§2 of the probe brief)
  - OSM grocery count vs Smiley "Dagligvareforretninger" count, kommune 101
  - OSM bus/metro stop count vs GTFS stops inside kommune 101

Usage
  python3 scripts/probe_services.py                      # everything
  python3 scripts/probe_services.py --only overpass,gtfs # a subset
  python3 scripts/probe_services.py --national           # + nationwide OSM counts (slow)
  python3 scripts/probe_services.py --pbf                # + download & scan the Geofabrik extract

Downloads are cached under data/raw/probe/ (gitignored) so a re-run is cheap.
"""
import argparse
import collections
import datetime as dt
import io
import json
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "probe"
OUT = CACHE / "probe_results.json"
UA = {"User-Agent": "am-dashboard-dk/probe (services layer feasibility; contact via github.com/real-estate-war-lord/am-dashboard-dk)"}

KOMMUNE = 101
# the OSM relation is named "Københavns Kommune" — "København" alone is the *city*
# node/relation and matches no admin_level=7 boundary.
KOMMUNE_NAME = "Københavns Kommune"
DENMARK_NAME = "Danmark"

# Overpass mirrors, tried in order. Both 504/429 intermittently under load, so
# `overpass()` retries in rounds.
#
# overpass.osm.ch is deliberately NOT in this list: it serves no areas database,
# so `area(3602192363)` matches nothing there and every count comes back a
# confident, wrong 0 with HTTP 200. A mirror that answers "none" to a question it
# cannot ask is worse than one that errors, which is also why `count_ok()` below
# refuses to believe a 0 from a single mirror.
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]

GEOFABRIK_PBF = "https://download.geofabrik.de/europe/denmark-latest.osm.pbf"
GTFS_URL = "https://www.rejseplanen.info/labs/GTFS.zip"
SMILEY_URL = "https://pub.fvst.dk/publikationer/Smileydata.xml"

# The tags the brief asks about, grouped the way the layer would group them.
# Each entry: (category, key, value) — value None means "any value of this key".
TAGS = [
    ("grocery",   "shop",    "supermarket"),
    ("grocery",   "shop",    "convenience"),
    ("grocery",   "shop",    "discount"),
    ("eating",    "amenity", "restaurant"),
    ("eating",    "amenity", "cafe"),
    ("eating",    "amenity", "bar"),
    ("eating",    "amenity", "fast_food"),
    ("pharmacy",  "amenity", "pharmacy"),
    ("transport", "highway", "bus_stop"),
    ("transport", "railway", "station"),
    ("transport", "railway", "halt"),
    ("transport", "station", "subway"),
    ("transport", "station", "light_rail"),
]

# Smiley `Smileybranche` values that are a grocery shop rather than a place that
# serves food. Read off the live feed's own distribution (see §d in the report).
SMILEY_GROCERY = {"Dagligvareforretninger"}
SMILEY_EATING = {"Restauranter, kantiner, takeaway, værtshuse m.fl.",
                 "Delikatesseforretninger og takeaway uden servering"}
# a grocery-ish specialist shop — kept separate because OSM would tag these
# shop=bakery / shop=butcher / shop=seafood, not shop=supermarket
SMILEY_FOOD_SPECIALIST = {"Bagere og bagerafdelinger",
                          "Slagtere og slagterafdelinger",
                          "Fiske- og vildtforretninger og fiskeafdelinger"}


def log(*a):
    print(*a, flush=True)


def fetch(url, dest=None, timeout=180):
    """GET with a local cache, so a re-run does not re-download 60 MB."""
    if dest is not None and dest.exists() and dest.stat().st_size > 0:
        log(f"  · cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest.read_bytes()
    t0 = time.time()
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    body = r.content
    log(f"  · {url.split('/')[2]} {r.status_code} {len(body)/1e6:.1f} MB in {time.time()-t0:.1f}s")
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return body


def head(url):
    """Size and last-modified without downloading."""
    r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
    return {"status": r.status_code,
            "bytes": int(r.headers.get("content-length") or 0),
            "content_type": r.headers.get("content-type", ""),
            "last_modified": r.headers.get("last-modified", ""),
            "needs_auth": r.status_code in (401, 403)}


# ---------------------------------------------------------------- a. Overpass
def overpass(query, label="", want=None, rounds=3, timeout=60):
    """Run one Overpass query against the first mirror that gives a usable answer.

    Both healthy mirrors return HTTP 504 intermittently under load — the *same*
    query succeeds seconds later — so a failure is retried in rounds with an
    exponential backoff rather than given up on after one pass. `timeout` is
    deliberately short: a mirror that has not answered a count query in 60 s is
    queueing, not computing, and waiting out its 300 s server-side budget only
    delays the next attempt.

    `want(json) -> bool` rejects an answer that parsed fine but is not what was
    asked for: overpass.osm.ch answers 200 with zero elements for queries it
    cannot serve, so a 200 alone is not evidence of an answer.
    """
    last = None
    for attempt in range(rounds):
        if attempt:
            wait = 5 * (2 ** (attempt - 1))                     # 5, 10, 20 s
            log(f"  · {label}: retrying in {wait}s (round {attempt + 1}/{rounds})")
            time.sleep(wait)
        for url in OVERPASS:
            host = url.split("/")[2]
            try:
                t0 = time.time()
                r = requests.post(url, data={"data": query}, headers=UA, timeout=timeout)
                if r.status_code in (429, 502, 503, 504):
                    last = f"{host} → HTTP {r.status_code}"
                    log(f"  · {label}: {last}")
                    continue
                r.raise_for_status()
                js = r.json()
                if want is not None and not want(js):
                    last = (f"{host} → 200 but no usable result "
                            f"({len(js.get('elements', []))} elements)")
                    log(f"  · {label}: {last}")
                    continue
                return js, time.time() - t0, host
            except Exception as e:                              # noqa: BLE001
                last = f"{host} → {type(e).__name__}: {e}"
                log(f"  · {label}: {last}")
    raise RuntimeError(f"every Overpass mirror failed after {rounds} rounds ({last})")


# Resolving a boundary by name means an unbounded search over every admin relation,
# which 504s on both healthy mirrors. Fetching a relation *by id* is instant (0.12 s),
# so the known ids are listed here and verified on use rather than trusted.
KNOWN_REL = {"Københavns Kommune": 2192363, "Danmark": 50046}


def overpass_area_id(name, admin_level=7):
    """The Overpass area id of a Danish kommune (admin_level 7) or of Denmark (2).

    Tries the known relation id first (cheap, and checked against its own tags);
    falls back to the name search, which is correct but frequently times out.
    """
    if name in KNOWN_REL:
        q = f'[out:json][timeout:60];\nrel({KNOWN_REL[name]});\nout ids tags;'
        try:
            res, secs, mirror = overpass(
                q, f"area by id {KNOWN_REL[name]}",
                want=lambda js: any(e.get("type") == "relation" for e in js.get("elements", [])))
            r = [e for e in res["elements"] if e.get("type") == "relation"][0]
            t = r.get("tags", {})
            if t.get("name") == name and t.get("admin_level") == str(admin_level):
                return 3600000000 + r["id"], r, secs, mirror, 1
            log(f"  · relation {KNOWN_REL[name]} is {t.get('name')!r} "
                f"al={t.get('admin_level')}, not {name!r} al={admin_level} — falling back to search")
        except Exception as e:                                  # noqa: BLE001
            log(f"  · id lookup failed ({e}) — falling back to the name search")

    q = (f'[out:json][timeout:120];\n'
         f'rel["boundary"="administrative"]["admin_level"="{admin_level}"]["name"="{name}"];\n'
         f'out ids tags;')
    res, secs, mirror = overpass(
        q, f"area lookup {name!r}",
        want=lambda js: any(e.get("type") == "relation" for e in js.get("elements", [])))
    rels = [e for e in res.get("elements", []) if e.get("type") == "relation"]
    if not rels:
        raise RuntimeError(f"no admin_level={admin_level} relation named {name!r}")
    # prefer the one that also carries a kommune code (ref:dagi / KOMKODE)
    def score(e):
        t = e.get("tags", {})
        return (("ref:dagi" in t or "KOMKODE" in t or "ref" in t), t.get("name", ""))
    rels.sort(key=score, reverse=True)
    r = rels[0]
    return 3600000000 + r["id"], r, secs, mirror, len(rels)


def tag_filter(key, value):
    return f'["{key}"]' if value is None else f'["{key}"="{value}"]'


def confirm_zero(query, key, value, first_mirror):
    """Ask a *different* mirror the same question. Returns "yes" (another mirror
    also says 0), "no: N" (it does not), or "unconfirmed" (nobody else answered)."""
    others = [u for u in OVERPASS if u.split("/")[2] != first_mirror]
    for url in others:
        host = url.split("/")[2]
        try:
            r = requests.post(url, data={"data": query}, headers=UA, timeout=60)
            if r.status_code != 200:
                continue
            js = r.json()
            counts = [int(e["tags"]["total"]) for e in js.get("elements", [])
                      if e.get("type") == "count"]
            if len(counts) < 2:
                continue
            total = sum(counts[:2])
            return "yes" if total == 0 else f"no: {host} says {total}"
        except Exception:                                       # noqa: BLE001
            continue
        finally:
            time.sleep(1.0)
    return "unconfirmed"


def probe_overpass(area_id=None, scope="kommune 101"):
    """Counts per tag, split node vs way, with the query time for each."""
    rows = []
    for cat, key, value in TAGS:
        f = tag_filter(key, value)
        area = f"(area.a)" if area_id else ""
        pre = f"area({area_id})->.a;\n" if area_id else ""
        q = (f'[out:json][timeout:280];\n{pre}'
             f'node{f}{area}->.n;\nway{f}{area}->.w;\n'
             f'.n out count;\n.w out count;')
        try:
            res, secs, mirror = overpass(
                q, f"{key}={value}",
                want=lambda js: sum(1 for e in js.get("elements", [])
                                    if e.get("type") == "count") >= 2)
            counts = [int(e["tags"]["total"]) for e in res.get("elements", [])
                      if e.get("type") == "count"]
            n_nodes, n_ways = (counts + [0, 0])[:2]
            row = {"category": cat, "key": key, "value": value, "scope": scope,
                   "nodes": n_nodes, "ways": n_ways, "total": n_nodes + n_ways,
                   "seconds": round(secs, 2), "mirror": mirror, "ok": True}
            # A zero is the one answer a flaky mirror produces for free, so it is
            # never taken on one mirror's word — confirm it somewhere else.
            if n_nodes + n_ways == 0:
                row["zero_confirmed"] = confirm_zero(q, key, value, mirror)
            rows.append(row)
            log(f"  {key}={value:<12} nodes {n_nodes:>6}  ways {n_ways:>5}  "
                f"total {n_nodes + n_ways:>6}  {secs:5.1f}s  [{mirror}]"
                + ("" if n_nodes + n_ways else
                   f"  zero confirmed: {row['zero_confirmed']}"))
        except Exception as e:                                  # noqa: BLE001
            rows.append({"category": cat, "key": key, "value": value, "scope": scope,
                         "ok": False, "error": f"{type(e).__name__}: {e}"})
            log(f"  {key}={value:<12} FAILED: {e}")
        time.sleep(1.0)                                         # be polite
    return rows


def overpass_points(area_id, key, value, out="center"):
    """The actual elements (nodes + way centroids) — used for the cross-checks."""
    f = tag_filter(key, value)
    q = (f'[out:json][timeout:280];\narea({area_id})->.a;\n'
         f'(node{f}(area.a);way{f}(area.a););\nout {out};')
    res, secs, mirror = overpass(q, f"points {key}={value}",
                                 want=lambda js: "elements" in js)
    pts = []
    for e in res.get("elements", []):
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is not None:
            pts.append({"type": e["type"], "id": e["id"], "lat": lat, "lon": lon,
                        "name": (e.get("tags") or {}).get("name", "")})
    return pts, secs


# -------------------------------------------------------------- b. Geofabrik
def probe_geofabrik(do_scan=False):
    info = {"url": GEOFABRIK_PBF}
    info.update(head(GEOFABRIK_PBF))
    log(f"  · pbf {info['bytes']/1e6:.0f} MB, last modified {info['last_modified']}")
    try:
        import importlib.metadata as _md
        import osmium                                           # noqa: F401
        # pyosmium exposes no __version__ attribute; the distribution is named "osmium"
        info["osmium"] = {"importable": True, "version": _md.version("osmium")}
    except ImportError:
        info["osmium"] = {"importable": False}
        # is it installable at all on this interpreter?
        import subprocess
        p = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "osmium"],
                           capture_output=True, text=True, timeout=300)
        info["osmium"]["pip_dry_run_rc"] = p.returncode
        info["osmium"]["pip_dry_run"] = (p.stdout + p.stderr).strip().splitlines()[-3:]
    if do_scan and info["osmium"]["importable"]:
        info["scan"] = scan_pbf()
    return info


def scan_pbf(pbf=None):
    """Count every probe tag straight out of the Geofabrik extract — nationwide and,
    by point-in-polygon against the kommune boundary the dashboard already ships,
    for kommune 101.

    This is the fallback that makes the probe independent of Overpass, which
    rate-limited us out during this session (see the report). It is also how a
    real build would do it: one 495 MB download, no API budget, reproducible.

    A way's position is the average of its node coordinates — the same
    approximation Overpass `out center` makes (it uses the bbox centre).
    """
    import osmium
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    dest = pathlib.Path(pbf) if pbf else CACHE / "denmark-latest.osm.pbf"
    if not dest.exists():
        log("  · downloading the Denmark extract (~495 MB)…")
        t0 = time.time()
        with requests.get(GEOFABRIK_PBF, headers=UA, timeout=2400, stream=True) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        log(f"  · downloaded {dest.stat().st_size/1e6:.0f} MB in {time.time()-t0:.0f}s")

    wanted = {(k, v) for _, k, v in TAGS}
    keys = {k for k, _ in wanted}

    # the kommune 101 polygon, from the file the dashboard already builds against
    gj = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text(encoding="utf-8"))
    geom = None
    for f in gj["features"]:
        pr = f.get("properties") or {}
        if str(pr.get("kode", "")).lstrip("0") == str(KOMMUNE):
            geom = shape(f["geometry"])
            break
    if geom is None:
        raise RuntimeError("kommune 101 not found in data/geo/kommuner.geojson")
    pg = prep(geom)
    minx, miny, maxx, maxy = geom.bounds

    nat_n, nat_w = collections.Counter(), collections.Counter()
    kbh_n, kbh_w = collections.Counter(), collections.Counter()
    kbh_points = collections.defaultdict(list)

    def hit(tags):
        """every (key, value) in `wanted` this object carries"""
        out = []
        for k in keys:
            if k in tags:
                v = tags[k]
                if (k, v) in wanted:
                    out.append(f"{k}={v}")
        return out

    def place(label, lat, lon, nat, kbh, kind, name=""):
        nat[label] += 1
        if lat is not None and minx <= lon <= maxx and miny <= lat <= maxy \
                and pg.contains(Point(lon, lat)):
            kbh[label] += 1
            kbh_points[label].append({"lat": lat, "lon": lon, "kind": kind, "name": name})

    t0 = time.time()
    fp = osmium.FileProcessor(str(dest)).with_locations()
    n_obj = 0
    for o in fp:
        n_obj += 1
        tags = o.tags
        labels = hit(tags)
        if not labels:
            continue
        name = tags.get("name", "")
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
            for lb in labels:
                place(lb, lat, lon, nat_n, kbh_n, "node", name)
        elif o.is_way():
            lats, lons = [], []
            for nd in o.nodes:
                if nd.location.valid():
                    lats.append(nd.location.lat)
                    lons.append(nd.location.lon)
            if not lats:
                for lb in labels:
                    nat_w[lb] += 1                       # counted, but unplaceable
                continue
            lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
            for lb in labels:
                place(lb, lat, lon, nat_w, kbh_w, "way", name)
    secs = time.time() - t0
    log(f"  · scanned {n_obj:,} objects in {secs:.0f}s")

    def rows(nc, wc):
        return {k: {"nodes": nc.get(k, 0), "ways": wc.get(k, 0),
                    "total": nc.get(k, 0) + wc.get(k, 0)}
                for k in sorted({f"{k}={v}" for k, v in wanted})}

    return {"file": dest.name, "file_bytes": dest.stat().st_size,
            "objects_scanned": n_obj, "seconds": round(secs, 1),
            "denmark": rows(nat_n, nat_w),
            "kommune_101": rows(kbh_n, kbh_w),
            "_kbh_points": {k: v for k, v in kbh_points.items()}}


# ------------------------------------------------------------------- c. GTFS
def probe_gtfs():
    info = {"url": GTFS_URL}
    info.update(head(GTFS_URL))
    log(f"  · zip {info['bytes']/1e6:.1f} MB, last modified {info['last_modified']}, "
        f"auth required: {info['needs_auth']}")
    blob = fetch(GTFS_URL, CACHE / "rejseplanen_gtfs.zip", timeout=600)
    z = zipfile.ZipFile(io.BytesIO(blob))
    info["members"] = [{"name": i.filename, "bytes": i.file_size} for i in z.infolist()]
    log("  · members: " + ", ".join(i.filename for i in z.infolist()))

    def table(name):
        with z.open(name) as fh:
            txt = io.TextIOWrapper(fh, encoding="utf-8-sig")
            import csv
            return list(csv.DictReader(txt))

    stops = table("stops.txt")
    info["stops_total"] = len(stops)
    info["stops_fields"] = list(stops[0].keys()) if stops else []
    loc = collections.Counter(s.get("location_type", "") or "0" for s in stops)
    info["stops_by_location_type"] = dict(loc)
    info["stops_with_parent"] = sum(1 for s in stops if s.get("parent_station"))
    log(f"  · stops.txt {len(stops)} rows, location_type {dict(loc)}")

    routes = table("routes.txt")
    rt = collections.Counter(r.get("route_type", "") for r in routes)
    info["routes_total"] = len(routes)
    info["routes_by_type"] = dict(rt)
    log(f"  · routes.txt {len(routes)} rows, route_type {dict(rt)}")

    # which stops are served by which route_type — that is what decides whether we
    # can split metro / rail / bus / light rail on the *stop*, not just the route.
    trips = table("trips.txt")
    trip_type = {}
    route_type = {r["route_id"]: r.get("route_type", "") for r in routes}
    for t in trips:
        trip_type[t["trip_id"]] = route_type.get(t["route_id"], "")
    # stop_times.txt is ~230 MB / millions of rows — csv.reader with column indexes,
    # not DictReader, or this one step dominates the whole probe.
    stop_types = collections.defaultdict(set)
    t0 = time.time()
    with z.open("stop_times.txt") as fh:
        import csv
        rdr = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
        header = next(rdr)
        i_trip, i_stop = header.index("trip_id"), header.index("stop_id")
        n = 0
        for row in rdr:
            n += 1
            tt = trip_type.get(row[i_trip])
            if tt is not None:
                stop_types[row[i_stop]].add(tt)
    info["stop_times_rows"] = n
    info["stop_times_seconds"] = round(time.time() - t0, 1)
    log(f"  · stop_times.txt {n} rows in {info['stop_times_seconds']}s")
    info["stops_with_a_route_type"] = len(stop_types)
    per_type = collections.Counter()
    for s, types in stop_types.items():
        for t in types:
            per_type[t] += 1
    info["stops_per_route_type"] = dict(per_type)
    info["stops_serving_more_than_one_type"] = sum(1 for t in stop_types.values() if len(t) > 1)
    log(f"  · stops per route_type {dict(per_type)}")

    info["_stops"] = [{"stop_id": s["stop_id"], "name": s.get("stop_name", ""),
                       "lat": float(s["stop_lat"]) if s.get("stop_lat") else None,
                       "lon": float(s["stop_lon"]) if s.get("stop_lon") else None,
                       "location_type": s.get("location_type", "") or "0",
                       "parent": s.get("parent_station", ""),
                       "types": sorted(stop_types.get(s["stop_id"], []))}
                      for s in stops]
    return info


# ----------------------------------------------------------------- d. Smiley
def probe_smiley():
    info = {"url": SMILEY_URL}
    info.update(head(SMILEY_URL))
    log(f"  · xml {info['bytes']/1e6:.1f} MB, last modified {info['last_modified']}")
    blob = fetch(SMILEY_URL, CACHE / "smileydata.xml", timeout=600)
    t0 = time.time()
    root = ET.fromstring(blob)
    rows = root.findall("Row")
    info["parse_seconds"] = round(time.time() - t0, 1)
    info["rows_total"] = len(rows)
    fields = collections.Counter()
    for r in rows:
        for c in r:
            fields[c.tag] += 1
    info["fields"] = {k: v for k, v in fields.most_common()}
    log(f"  · {len(rows)} rows, fields: {', '.join(list(fields)[:20])}")

    # coordinates? the brief asks explicitly.
    coord_tags = [t for t in fields if re.search(r"geo|lat|l[oa]ng|koord|x_|y_", t, re.I)]
    info["coordinate_fields"] = coord_tags
    info["has_coordinates"] = bool(coord_tags)

    branche = collections.Counter(
        (r.findtext("Smileybranche") or "").strip() for r in rows)
    info["smileybranche"] = dict(branche.most_common())
    vtype = collections.Counter((r.findtext("Virksomhedstype") or "").strip() for r in rows)
    info["virksomhedstype"] = dict(vtype.most_common())

    # København: the feed has no kommune field, so postal code is the only handle.
    kbh = [r for r in rows if (r.findtext("Postnummer") or "").strip().isdigit()
           and 1000 <= int((r.findtext("Postnummer") or "0").strip()) <= 2450]
    info["kbh_postnr_range"] = "1000-2450 (København K/V/N/S/Ø/NV/SV + Valby/Vanløse/Frederiksberg*)"
    info["kbh_rows"] = len(kbh)
    kbh_branche = collections.Counter((r.findtext("Smileybranche") or "").strip() for r in kbh)
    info["kbh_smileybranche"] = dict(kbh_branche.most_common())
    info["kbh_grocery"] = sum(v for k, v in kbh_branche.items() if k in SMILEY_GROCERY)
    info["kbh_eating"] = sum(v for k, v in kbh_branche.items() if k in SMILEY_EATING)
    info["kbh_food_specialist"] = sum(v for k, v in kbh_branche.items()
                                      if k in SMILEY_FOOD_SPECIALIST)
    info["national_grocery"] = sum(v for k, v in branche.items() if k in SMILEY_GROCERY)
    info["national_eating"] = sum(v for k, v in branche.items() if k in SMILEY_EATING)
    # "Engros" is a wholesaler/warehouse, never a place a resident walks into
    info["kbh_detail_rows"] = sum(1 for r in kbh
                                  if (r.findtext("Virksomhedstype") or "").strip() == "Detail")
    log(f"  · København (postnr 1000–2450): {len(kbh)} rows, "
        f"grocery {info['kbh_grocery']}, eating {info['kbh_eating']}")
    info["_kbh_sample"] = [{c.tag: c.text for c in r} for r in kbh[:3]]
    return info


# ------------------------------------------------------------ 2. cross-check
def in_kommune_101(points):
    """Point-in-polygon against the kommune boundary the dashboard already ships."""
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    gj = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text(encoding="utf-8"))
    geom = None
    for f in gj["features"]:
        p = f.get("properties") or {}
        if str(p.get("kode", "")).lstrip("0") == str(KOMMUNE) or p.get("navn") == KOMMUNE_NAME:
            geom = shape(f["geometry"])
            break
    if geom is None:
        raise RuntimeError("kommune 101 not found in data/geo/kommuner.geojson")
    pg = prep(geom)
    return [p for p in points if p.get("lat") is not None
            and pg.contains(Point(p["lon"], p["lat"]))], geom


def cross_checks(pbf_scan, gtfs, smiley):
    """§2 of the brief: OSM vs Smiley for groceries, OSM vs GTFS for stops.

    The OSM side comes from the Geofabrik extract, not from Overpass: the extract
    is one consistent snapshot, it needs no API budget, and it is what caught two
    wrong zeros the API handed back (see the report). Both sides are clipped to
    the *same* kommune 101 polygon wherever the data allows it.
    """
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    k101 = pbf_scan["kommune_101"]
    out = {"osm_source": "Geofabrik denmark-latest.osm.pbf, " + pbf_scan["file"]}

    # --- a. groceries: OSM vs Smiley
    osm_grocery = {k: k101[k]["total"] for k in
                   ("shop=supermarket", "shop=convenience", "shop=discount")}
    out["osm_grocery_101"] = sum(osm_grocery.values())
    out["osm_grocery_101_by_tag"] = osm_grocery
    out["smiley_grocery_kbh"] = smiley.get("kbh_grocery")
    out["smiley_food_specialist_kbh"] = smiley.get("kbh_food_specialist")
    out["grocery_ratio"] = round(
        (smiley.get("kbh_grocery") or 0) / max(1, sum(osm_grocery.values())), 2)
    out["grocery_note"] = (
        "Not the same geography and not the same question. Smiley is counted by "
        "postal code 1000–2450 (it carries no kommune field and no coordinates), "
        "which includes Frederiksberg's 2000 and part of 2450/2500; OSM is clipped "
        "to the kommune 101 polygon. And Smiley registers every food *business* — "
        "a kiosk, a petrol-station shop, a canteen, a wholesale depot — where OSM "
        "shop=supermarket|convenience is a shop a resident walks into. The gap is "
        "mostly definition, not missing OSM data.")

    # --- b. eating places, the same pair
    osm_eating = {k: k101[k]["total"] for k in
                  ("amenity=restaurant", "amenity=cafe", "amenity=bar", "amenity=fast_food")}
    out["osm_eating_101"] = sum(osm_eating.values())
    out["osm_eating_101_by_tag"] = osm_eating
    out["smiley_eating_kbh"] = smiley.get("kbh_eating")
    out["eating_ratio"] = round(
        (smiley.get("kbh_eating") or 0) / max(1, sum(osm_eating.values())), 2)

    # --- c. stops: OSM vs GTFS, both clipped to the kommune 101 polygon
    gj = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text(encoding="utf-8"))
    geom = next(shape(f["geometry"]) for f in gj["features"]
                if str((f.get("properties") or {}).get("kode", "")).lstrip("0") == str(KOMMUNE))
    pg = prep(geom)
    minx, miny, maxx, maxy = geom.bounds

    inside = [s_ for s_ in gtfs["_stops"]
              if s_["lat"] is not None and minx <= s_["lon"] <= maxx
              and miny <= s_["lat"] <= maxy and pg.contains(Point(s_["lon"], s_["lat"]))]
    out["gtfs_stops_101"] = len(inside)
    per_type = collections.Counter()
    for s_ in inside:
        for t in s_["types"]:
            per_type[t] += 1
    out["gtfs_stops_101_by_route_type"] = dict(sorted(per_type.items()))
    out["gtfs_stops_101_multi_type"] = sum(1 for s_ in inside if len(s_["types"]) > 1)

    out["osm_bus_stop_101"] = k101["highway=bus_stop"]["total"]
    out["osm_railway_station_101"] = k101["railway=station"]["total"]
    out["osm_railway_halt_101"] = k101["railway=halt"]["total"]
    out["osm_station_subway_101"] = k101["station=subway"]["total"]
    out["osm_station_light_rail_101"] = k101["station=light_rail"]["total"]
    out["stops_note"] = (
        "GTFS counts a *boarding point* per direction and per operator — this feed "
        "has location_type=0 for all 36 383 stops and not one parent_station, so a "
        "two-way bus stop is two rows and a metro station with two platforms is "
        "two rows. OSM highway=bus_stop is also per direction, which is why those "
        "two numbers are close; OSM railway=station is one node per station, which "
        "is why it is roughly half the GTFS rail figure.")
    log(f"  · groceries  OSM {out['osm_grocery_101']} vs Smiley {out['smiley_grocery_kbh']} "
        f"(ratio {out['grocery_ratio']})")
    log(f"  · eating     OSM {out['osm_eating_101']} vs Smiley {out['smiley_eating_kbh']} "
        f"(ratio {out['eating_ratio']})")
    log(f"  · stops      OSM bus {out['osm_bus_stop_101']} · GTFS all modes "
        f"{out['gtfs_stops_101']} {out['gtfs_stops_101_by_route_type']}")
    return out


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="overpass,geofabrik,gtfs,smiley,cross",
                    help="comma list: overpass, geofabrik, gtfs, smiley, cross")
    ap.add_argument("--national", action="store_true",
                    help="also count every tag over all of Denmark via Overpass (slow)")
    ap.add_argument("--pbf", action="store_true",
                    help="download the Geofabrik extract and count the tags in it")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    CACHE.mkdir(parents=True, exist_ok=True)
    res = {"probed": dt.datetime.now().isoformat(timespec="seconds"), "kommune": KOMMUNE}

    area_id = None
    if "overpass" in only:
        log("\n== a. OSM Overpass ==")
        area_id, rel, secs, mirror, n = overpass_area_id(KOMMUNE_NAME)
        res["overpass_area"] = {"area_id": area_id, "relation_id": rel["id"],
                                "tags": rel.get("tags", {}), "candidates": n,
                                "lookup_seconds": round(secs, 2), "mirror": mirror}
        log(f"  · area {area_id} (relation {rel['id']}, "
            f"{rel.get('tags', {}).get('name')}) in {secs:.1f}s via {mirror}")

    if "overpass" in only:
        res["overpass_kommune_101"] = probe_overpass(area_id, "kommune 101")
        if args.national:
            log("\n== a2. OSM Overpass, all of Denmark ==")
            dk, rel, secs, mirror, _ = overpass_area_id(DENMARK_NAME, admin_level=2)
            res["overpass_denmark"] = probe_overpass(dk, "Denmark")

    if "geofabrik" in only:
        log("\n== b. Geofabrik Denmark extract ==")
        res["geofabrik"] = probe_geofabrik(do_scan=args.pbf)

    if "gtfs" in only or "cross" in only:
        log("\n== c. Rejseplanen GTFS ==")
        res["gtfs"] = probe_gtfs()

    if "smiley" in only or "cross" in only:
        log("\n== d. Fødevarestyrelsen Smiley ==")
        res["smiley"] = probe_smiley()

    if "cross" in only:
        log("\n== 2. cross-checks ==")
        scan = (res.get("geofabrik") or {}).get("scan")
        if scan is None and OUT.exists():                       # reuse an earlier --pbf run
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            scan = (prev.get("geofabrik") or {}).get("scan")
        if scan is None:
            scan = scan_pbf()
            res.setdefault("geofabrik", {})["scan"] = scan
        res["cross_checks"] = cross_checks(scan, res["gtfs"], res["smiley"])

    # the per-stop dump is for the cross-check only — keep it out of the results file
    if "gtfs" in res:
        res["gtfs"].pop("_stops", None)
    # merge, so `--only gtfs` does not throw away an earlier `--only overpass` run
    merged = {}
    if OUT.exists():
        try:
            merged = json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            pass
    merged.update(res)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"\nwrote {OUT} ({OUT.stat().st_size/1024:.0f} kB) · sections: "
        + ", ".join(k for k in merged if not k.startswith("_")))


if __name__ == "__main__":
    main()
