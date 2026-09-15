#!/usr/bin/env python3
"""Aggregate BBR units + buildings (data/raw/bbr/*.jsonl from fetch_bbr.py) into
housing-stock indicators per postal code, Copenhagen quarter and municipality.

Output: data/processed/bbr.json
  {"meta": {built, municipalities:[...], units, assigned_pct, source},
   "postnr":  {"2100": {n, renters_bbr, avg_m2_bbr, new_stock_bbr, flats_bbr, small_bbr, vacant_bbr, dw_per_bld,
                        dist: {rooms:[1,2,3,4+], built:[<1950,1950–79,1980–2009,2010+], size:[<50,50–79,80–119,120+], type:[single,row,multi,other]}}},
   "kvarter": {...}, "kommune": {...}}

Method: dwelling (BBR Enhed, boligtype 1–5, status 6) → its building's coordinate (EPSG:25832 → WGS84)
→ point-in-polygon into data/geo/postnumre.geojson and cph_kvarterer.geojson (shapely STRtree).
Municipality comes from the unit's own kommunekode. Units whose building has no coordinate are
counted in `n_total` but not assigned to a polygon (share reported in meta).
"""
import datetime as dt
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "bbr"
GEO = ROOT / "data" / "geo"
OUT = ROOT / "data" / "processed" / "bbr.json"

try:
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree
except ImportError:
    sys.exit("shapely missing: pip3 install shapely")


# ---------- EPSG:25832 (UTM 32N, GRS80) → WGS84, no pyproj needed ----------
def utm32_to_wgs84(x, y):
    a = 6378137.0; f = 1 / 298.257222101; k0 = 0.9996; lon0 = math.radians(9.0)
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x -= 500000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2); t1 = math.tan(phi1) ** 2; c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5; d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                              + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lon), math.degrees(lat)


def parse_wkt_point(w):
    try:
        s = w[w.index("(") + 1:w.index(")")].split()
        return float(s[0]), float(s[1])
    except Exception:  # noqa: BLE001
        return None


def index(geojson_path, key_fn):
    """STRtree of polygons → (tree, keys) for point lookup."""
    if not geojson_path.exists():
        return None
    g = json.loads(geojson_path.read_text(encoding="utf-8"))
    geoms, keys = [], []
    for f in g["features"]:
        k = key_fn(f["properties"])
        if k is None:
            continue
        geoms.append(shape(f["geometry"])); keys.append(k)
    return STRtree(geoms), geoms, keys


def lookup(idx, pt):
    if not idx:
        return None
    tree, geoms, keys = idx
    for i in tree.query(pt, predicate="within"):
        return keys[i]
    return None


def new_acc():
    return {"n": 0, "n_bld": set(), "rent": 0, "own": 0, "vac": 0, "ten": 0, "m2sum": 0.0, "m2n": 0, "small": 0, "new": 0, "yearn": 0,
            "flats": 0, "typen": 0, "rooms": [0, 0, 0, 0], "built": [0, 0, 0, 0], "size": [0, 0, 0, 0], "type": [0, 0, 0, 0]}


def add(acc, u, b):
    acc["n"] += 1
    if b:
        acc["n_bld"].add(b["id_lokalId"])
    t = u.get("enh045Udlejningsforhold")
    if t in ("1", "2", "3"):
        acc["ten"] += 1; acc["rent"] += t == "1"; acc["own"] += t == "2"; acc["vac"] += t == "3"
    m2 = u.get("enh026EnhedensSamledeAreal")
    if m2 and m2 > 0:
        acc["m2sum"] += m2; acc["m2n"] += 1; acc["small"] += m2 < 50
        acc["size"][0 if m2 < 50 else 1 if m2 < 80 else 2 if m2 < 120 else 3] += 1
    r = u.get("enh031AntalVaerelser")
    if r and r > 0:
        acc["rooms"][min(int(r), 4) - 1] += 1
    y = b.get("byg026Opfoerelsesaar") if b else None
    if y and 1000 < y <= 2100:
        acc["yearn"] += 1; acc["new"] += y >= 2010
        acc["built"][0 if y < 1950 else 1 if y < 1980 else 2 if y < 2010 else 3] += 1
    use = (b or {}).get("byg021BygningensAnvendelse")
    if use:
        acc["typen"] += 1
        code = str(use)
        acc["type"][0 if code in ("110", "120", "121", "122") else 1 if code in ("130", "131", "132") else 2 if code == "140" else 3] += 1
        acc["flats"] += code == "140"


def finish(acc):
    pct = lambda a, b: round(a / b * 100, 1) if b else None
    return {"n": acc["n"], "n_bld": len(acc["n_bld"]),
            "renters_bbr": pct(acc["rent"], acc["ten"]), "vacant_bbr": pct(acc["vac"], acc["ten"]),
            "avg_m2_bbr": round(acc["m2sum"] / acc["m2n"], 1) if acc["m2n"] else None, "small_bbr": pct(acc["small"], acc["m2n"]),
            "new_stock_bbr": pct(acc["new"], acc["yearn"]), "flats_bbr": pct(acc["flats"], acc["typen"]),
            "dw_per_bld": round(acc["n"] / len(acc["n_bld"]), 1) if acc["n_bld"] else None,
            "dist": {"rooms": acc["rooms"], "built": acc["built"], "size": acc["size"], "type": acc["type"]}}


def main():
    files = sorted(RAW.glob("*_enhed.jsonl"))
    if not files:
        sys.exit("no data/raw/bbr/*_enhed.jsonl — run scripts/fetch_bbr.py first")
    pn_idx = index(GEO / "postnumre.geojson", lambda p: str(p.get("nr") or p.get("postnr") or ""))
    kv_idx = index(GEO / "cph_kvarterer.geojson", lambda p: str(p.get("kvarternr")))
    acc = {"postnr": {}, "kvarter": {}, "kommune": {}}
    munis, n_units, n_assigned, n_nocoord = [], 0, 0, 0
    for ef in files:
        kom = ef.name[:4]; bf = RAW / f"{kom}_bygning.jsonl"
        if not bf.exists():
            print(f"  {kom}: bygning file missing — skipped"); continue
        blds = {}
        for line in bf.open(encoding="utf-8"):
            b = json.loads(line); c = (b.get("byg404Koordinat") or {}).get("wkt")
            xy = parse_wkt_point(c) if c else None
            if xy:
                lon, lat = utm32_to_wgs84(*xy); b["_pt"] = Point(lon, lat)
                b["_pn"] = lookup(pn_idx, b["_pt"]); b["_kv"] = lookup(kv_idx, b["_pt"]) if kv_idx and kom == "0101" else None
            blds[b["id_lokalId"]] = b
        k = 0
        for line in ef.open(encoding="utf-8"):
            u = json.loads(line)
            if u.get("enh023Boligtype") not in ("1", "2", "3", "4", "5"):
                continue
            n_units += 1; k += 1
            b = blds.get(u.get("bygning"))
            kc = str(int(kom))
            add(acc["kommune"].setdefault(kc, new_acc()), u, b)
            if not b or "_pt" not in b:
                n_nocoord += 1; continue
            if b.get("_pn"):
                add(acc["postnr"].setdefault(b["_pn"], new_acc()), u, b); n_assigned += 1
            if b.get("_kv"):
                add(acc["kvarter"].setdefault(b["_kv"], new_acc()), u, b)
        munis.append(kom); print(f"  {kom}: {k} dwellings, {len(blds)} buildings")
    out = {"meta": {"built": dt.date.today().isoformat(), "municipalities": munis, "dwellings": n_units,
                    "assigned_pct": round(n_assigned / n_units * 100, 1) if n_units else 0, "no_coordinate": n_nocoord,
                    "source": "BBR (Bygnings- og Boligregistret) via Datafordeler GraphQL, Klimadatastyrelsen — status 6 (current), boligtype 1–5",
                    "definitions": {"renters_bbr": "enh045Udlejningsforhold = 1 (rented, incl. andel) of units with a known tenure",
                                    "vacant_bbr": "enh045Udlejningsforhold = 3 (not in use) of units with a known tenure — owner-reported, lags",
                                    "avg_m2_bbr": "mean enh026EnhedensSamledeAreal", "small_bbr": "units < 50 m²",
                                    "new_stock_bbr": "building byg026Opfoerelsesaar >= 2010", "flats_bbr": "units in buildings with byg021 = 140 (multi-dwelling)",
                                    "dw_per_bld": "dwellings per residential building"}},
           **{lvl: {k: finish(a) for k, a in d.items()} for lvl, d in acc.items()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(munis)} municipalities · {n_units} dwellings · {out['meta']['assigned_pct']}% placed in a postal code · "
          f"{len(out['postnr'])} postal codes · {len(out['kvarter'])} quarters")


if __name__ == "__main__":
    main()
