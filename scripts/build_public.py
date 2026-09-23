#!/usr/bin/env python3
"""Build the public-buildings layer from the BBR pulls.

Inputs : data/raw/public/<kommune>_{bygning,sag}.jsonl  (scripts/fetch_public_buildings.py)
         data/raw/dar/public_adresse.jsonl              (address + coordinate where BBR has none)
         data/geo/postnumre.geojson, cph_kvarterer.geojson, kommuner.geojson
         Overpass (cached in data/raw/osm/) for names, optional: --no-osm skips it
Outputs: data/processed/public/<kommune>.json           one file per municipality, loaded on demand
         data/processed/public_index.json               per-polygon counts and the open cases

Two kinds of record (see docs/PUBLIC_BUILDINGS.md):
  existing  — BBR status 6 "Opført": the standing public building stock, with area and year built
  case      — BBR status 2/3 with an open building case. These carry no reliable completion date
              (1 of 290 in the pilot), so they are shown as *open building cases* with their permit
              date and age, and only the recent ones (permit ≤ 3 years) go on the map.

Usage: python3 scripts/build_public.py [--kommune 0101,0147] [--no-osm]
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from shapely.geometry import Point  # noqa: E402
from build_bbr import index, lookup, parse_wkt_point, utm32_to_wgs84  # noqa: E402
from fetch_public_buildings import open_case  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "public"
DAR = ROOT / "data" / "raw" / "dar" / "public_adresse.jsonl"
OSM_CACHE = ROOT / "data" / "raw" / "osm"
OUT = ROOT / "data" / "processed" / "public"
IDX = ROOT / "data" / "processed" / "public_index.json"
RECENT_YEARS = 3                      # a building case counts as recent while its permit is this new
NAME_M = 60                           # OSM feature this close lends the building its name

# BBR building-use codes (teknik.bbr.dk/kodelister/0/1/0/BygAnvendelse), 410–449
LABEL = {"410": "Kultur (udfases)", "411": "Biograf, teater, koncertsted", "412": "Museum", "413": "Bibliotek",
         "414": "Kirke eller anden bygning til trosudøvelse", "415": "Forsamlingshus", "416": "Forlystelsespark",
         "419": "Anden bygning til kulturelle formål",
         "420": "Undervisning og forskning (udfases)", "421": "Grundskole", "422": "Universitet",
         "429": "Anden bygning til undervisning og forskning",
         "430": "Hospital (udfases)", "431": "Hospital og sygehus", "432": "Hospice, behandlingshjem mv.",
         "433": "Sundhedscenter, lægehus, fødeklinik mv.", "439": "Anden bygning til sundhedsformål",
         "440": "Daginstitution (udfases)", "441": "Daginstitution", "442": "Servicefunktion på døgninstitution",
         "443": "Kaserne", "444": "Fængsel, arresthus mv.", "449": "Anden bygning til institutionsformål"}
CAT = {**{c: "education" for c in ("420", "421", "422", "429")},
       **{c: "institutions" for c in ("440", "441", "442", "443", "444", "449")},
       **{c: "health" for c in ("430", "431", "432", "433", "439")},
       **{c: "culture" for c in ("410", "411", "412", "413", "414", "415", "416", "419")}}
# sag019Bygherreforhold (BBR code list)
BYGHERRE = {"1": "Private", "2": "Almennyttigt boligselskab", "3": "Kommune", "4": "Region", "5": "Stat", "6": "Andet"}
OSM_AMENITY = ["school", "kindergarten", "university", "college", "hospital", "clinic", "doctors", "library", "theatre", "museum"]


def load_jsonl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def years_since(iso, today):
    return round((today - dt.date.fromisoformat(iso[:10])).days / 365.25, 1) if iso else None


def osm_names(kommune, bbox, offline=False):
    """Named public facilities from OpenStreetMap, for labelling a BBR building that has no name of its own."""
    ql = "".join(f'nwr["amenity"="{a}"]["name"]({bbox});' for a in OSM_AMENITY)
    OSM_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OSM_CACHE / f"public_{kommune}_{hashlib.sha1(ql.encode()).hexdigest()[:8]}.json"
    if not cache.exists():
        if offline:
            return []
        body = f"[out:json][timeout:120];({ql});out center;"
        req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                     data=urllib.parse.urlencode({"data": body}).encode(),
                                     headers={"User-Agent": "am-dashboard-dk/2.2"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=200) as r:
                    cache.write_bytes(r.read())
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    print(f"  ⚠ OSM names for {kommune}: {e}", file=sys.stderr)
                    return []
                time.sleep(15 * (attempt + 1))
        time.sleep(3)
    out = []
    for e in json.loads(cache.read_text(encoding="utf-8")).get("elements", []):
        c = e.get("center") or ({"lat": e.get("lat"), "lon": e.get("lon")} if e.get("lat") else None)
        if c and (e.get("tags") or {}).get("name"):
            out.append((c["lat"], c["lon"], e["tags"]["name"], e["tags"]["amenity"]))
    return out


def nearest_name(lat, lon, names):
    """Name of the closest OSM facility within NAME_M metres, else None."""
    best, bestd = None, NAME_M
    for nlat, nlon, name, _a in names:
        d = ((nlat - lat) * 111320) ** 2 + ((nlon - lon) * 111320 * 0.57) ** 2   # cos(55.7°) ≈ 0.563
        d **= .5
        if d < bestd:
            best, bestd = name, d
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kommune", help="0101,0147 (default: every municipality with a raw pull)")
    ap.add_argument("--no-osm", action="store_true", help="skip the OSM name join (use cached answers only)")
    args = ap.parse_args()
    today = dt.date.today()
    koms = [k.strip() for k in args.kommune.split(",")] if args.kommune else \
        sorted({p.name.split("_")[0] for p in RAW.glob("*_bygning.jsonl")})
    if not koms:
        sys.exit("no pulls in data/raw/public — run scripts/fetch_public_buildings.py --kommune 0101,0147")
    pn = index(ROOT / "data" / "geo" / "postnumre.geojson", lambda p: str(p.get("nr")))
    kv = index(ROOT / "data" / "geo" / "cph_kvarterer.geojson", lambda p: str(p.get("kvarternr")))
    dar = {r["id"]: r for r in load_jsonl(DAR)}
    OUT.mkdir(parents=True, exist_ok=True)
    idx, files = collections.defaultdict(lambda: {"counts": collections.defaultdict(collections.Counter),
                                                 "m2_existing": 0, "recent_cases": [], "stale_cases": 0}), {}
    for kom in koms:
        bygs = load_jsonl(RAW / f"{kom}_bygning.jsonl")
        cases = collections.defaultdict(list)
        for r in load_jsonl(RAW / f"{kom}_sag.jsonl"):
            cases[r["bygning"]].append(r["case"])
        pts = [(b, parse_wkt_point((b.get("byg404Koordinat") or {}).get("wkt") or (dar.get(b["id_lokalId"], {}).get("wkt") or ""))) for b in bygs]
        latlon = {}
        for b, xy in pts:
            if xy:
                lon, lat = utm32_to_wgs84(*xy)
                latlon[b["id_lokalId"]] = (round(lat, 6), round(lon, 6))
        names = []
        if latlon:
            lats = [v[0] for v in latlon.values()]; lons = [v[1] for v in latlon.values()]
            bbox = f"{min(lats) - .01:.4f},{min(lons) - .01:.4f},{max(lats) + .01:.4f},{max(lons) + .01:.4f}"
            names = osm_names(kom, bbox, args.no_osm)
        rows, skipped = [], 0
        for b in bygs:
            ll = latlon.get(b["id_lokalId"])
            if not ll:
                skipped += 1
                continue
            code = b["byg021BygningensAnvendelse"]
            cat = CAT.get(code)
            if not cat:
                continue
            d = dar.get(b["id_lokalId"], {})
            rec = {"id": b["id_lokalId"], "lat": ll[0], "lon": ll[1], "code": code, "label": LABEL.get(code, code),
                   "cat": cat, "kom": kom.lstrip("0"), "m2": b.get("byg038SamletBygningsareal"),
                   "year": b.get("byg026Opfoerelsesaar"), "floors": b.get("byg054AntalEtager"),
                   "name": nearest_name(ll[0], ll[1], names) if names else None,
                   "address": d.get("address"), "postnr": d.get("postnr") or lookup(pn, Point(ll[1], ll[0])),
                   "kvarter": lookup(kv, Point(ll[1], ll[0]))}
            if b["status"] == "6":
                rec["kind"] = "existing"
            else:
                c = open_case(cases.get(b["id_lokalId"], [])) or {}
                permit = c.get("sag003Byggetilladelsesdato") or c.get("sag002Byggesagsdato")
                rec |= {"kind": "case", "bbr_status": b["status"], "permit": (permit or "")[:10] or None,
                        "started": (c.get("sag005Paabegyndelsesdato") or "")[:10] or None,
                        "expected": (c.get("sag009ForventetFuldfoertDato") or "")[:10] or None,
                        "case_no": c.get("sag001Byggesagsnummer"), "case_m2": c.get("sag008FaerdigtBygningsareal"),
                        "owner": BYGHERRE.get(c.get("sag019Bygherreforhold") or ""),
                        "age_yrs": years_since(permit, today)}
                rec["recent"] = rec["age_yrs"] is not None and rec["age_yrs"] <= RECENT_YEARS
            rows.append(rec)
            for key in (f"kommune:{rec['kom']}", f"postnr:{rec['postnr']}" if rec["postnr"] else None,
                        f"kvarter:{rec['kvarter']}" if rec["kvarter"] else None):
                if not key:
                    continue
                e = idx[key]
                if rec["kind"] == "existing":
                    e["counts"][cat]["existing"] += 1
                    e["m2_existing"] += rec["m2"] or 0
                elif rec.get("recent"):
                    e["counts"][cat]["case"] += 1
                    e["recent_cases"].append({"id": rec["id"], "name": rec["name"], "cat": cat, "label": rec["label"],
                                              "permit": rec["permit"], "expected": rec["expected"], "age_yrs": rec["age_yrs"]})
                else:
                    e["stale_cases"] += 1
        files[kom] = rows
        (OUT / f"{kom}.json").write_text(json.dumps(
            {"kommune": kom, "built": today.isoformat(), "recent_years": RECENT_YEARS, "n": len(rows),
             "source": "BBR via Datafordeler (anvendelse 410–449, status 2/3/6); addresses and missing coordinates from DAR",
             "buildings": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        ex = sum(1 for r in rows if r["kind"] == "existing")
        rc = sum(1 for r in rows if r.get("recent"))
        print(f"{kom}: {len(rows)} buildings · existing {ex} · open cases {len(rows) - ex} (recent {rc}, stale {len(rows) - ex - rc})"
              f" · named from OSM {sum(1 for r in rows if r['name'])}" + (f" · {skipped} without a coordinate" if skipped else ""))
    out = {k: {"counts": {c: dict(v) for c, v in e["counts"].items()}, "m2_existing": e["m2_existing"],
               "recent_cases": sorted(e["recent_cases"], key=lambda r: r["permit"] or "", reverse=True),
               "stale_cases": e["stale_cases"]} for k, e in idx.items()}
    IDX.write_text(json.dumps({"built": today.isoformat(), "recent_years": RECENT_YEARS,
                               "kommuner": [k.lstrip("0") for k in koms], "areas": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {IDX.relative_to(ROOT)}: {len(out)} areas · {sum(len(v) for v in files.values())} buildings in {len(files)} municipalities")


if __name__ == "__main__":
    main()
