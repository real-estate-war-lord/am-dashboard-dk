#!/usr/bin/env python3
"""Pull public-use buildings (BBR anvendelse 410–449) and their building cases from Datafordeler.

Reuses scripts/fetch_bbr.py for the GraphQL client, the API key (.env) and the paging.

  data/raw/public/<kommune>_bygning.jsonl   buildings, status 2 (projekteret), 3 (under opførelse), 6 (opført)
  data/raw/public/<kommune>_sag.jsonl       the building cases behind the status 2/3 buildings, with their link row
  data/raw/dar/public_adresse.jsonl         DAR address + coordinate for buildings whose BBR row has no
                                            byg404Koordinat (most open-case buildings do not have one)

Status (BBR "Livscyklus" code list, teknik.bbr.dk/kodelister/0/1/0/Livscyklus):
  2 Projekteret · 3 Under opførelse · 6 Opført. Statuses 9/10/11/13/14 are closed versions — a building
  that was re-coded (e.g. 440 → 441) keeps an old row in one of those. Only status 6 counts as existing.

A building carries no case reference; the link runs building ← BBR_Sagsniveau (sagsdataBygning /
stamdataBygning) → BBR_BBRSag. Of the cases found for a building we keep the newest open one
(no sag010FuldfoerelseAfByggeri, status not 9 Afsluttet / 14 Henlagt).

Usage:
  python3 scripts/fetch_public_buildings.py --kommune 0101,0147      # named municipalities
  python3 scripts/fetch_public_buildings.py --metro                  # Copenhagen + 18 suburban municipalities
  python3 scripts/fetch_public_buildings.py --all                    # every municipality
  python3 scripts/fetch_public_buildings.py --kommune 0147 --measure # print the case-coverage measurement only
Finished municipalities are skipped unless --refresh is given, so a run can be resumed.
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_bbr as fb  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "public"
CODES = [str(c) for c in range(410, 450)]
LIVE = ["2", "3", "6"]
CHUNK = 100                      # the API caps an `in` list at 100

BYG_FIELDS = ("id_lokalId status kommunekode byg021BygningensAnvendelse byg026Opfoerelsesaar "
              "byg027OmTilbygningsaar byg038SamletBygningsareal byg039BygningensSamledeBoligAreal "
              "byg041BebyggetAreal byg054AntalEtager husnummer grund byg404Koordinat { wkt crs }")
SAG_FIELDS = ("id_lokalId status kommunekode sag001Byggesagsnummer sag012Byggesagskode sag002Byggesagsdato "
              "sag003Byggetilladelsesdato sag004ForventetPaabegyndelsesdato sag005Paabegyndelsesdato "
              "sag009ForventetFuldfoertDato sag010FuldfoerelseAfByggeri sag008FaerdigtBygningsareal sag019Bygherreforhold")
CASE_CLOSED = {"9", "14"}        # Afsluttet, Henlagt
RECENT_CUT = (dt.date.today() - dt.timedelta(days=3 * 365 + 1)).isoformat()   # permit this new = a recent case


def byname(code):
    """Municipality name for the log line, from the vendored boundaries."""
    global _NAMES
    if _NAMES is None:
        p = ROOT / "data" / "geo" / "kommuner.geojson"
        _NAMES = {f["properties"]["kode"]: f["properties"]["navn"] for f in json.loads(p.read_text(encoding="utf-8"))["features"]} if p.exists() else {}
    return _NAMES.get(code, code)


_NAMES = None


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def page(entity, where, fields, variables):
    """Cursor-paged query. `where` is GraphQL text, `variables` the values it refers to."""
    out, after, t = [], None, now()
    while True:
        q = (f"query($first:Int!,$after:String,$t:DafDateTime!"
             + "".join(f",${k}:{v[0]}" for k, v in variables.items()) + ") {"
             + f" {entity}(first:$first, after:$after, virkningstid:$t, registreringstid:$t, where:{{ {where} }})"
             + f" {{ pageInfo {{ endCursor hasNextPage }} nodes {{ {fields} }} }} }}")
        r = fb.gql("v3", q, {"first": 1000, "after": after, "t": t} | {k: v[1] for k, v in variables.items()})
        if "errors" in r:
            sys.exit(f"{entity}: {json.dumps(r['errors'], ensure_ascii=False)[:500]}")
        p = r["data"][entity]
        out += p["nodes"]
        if not p["pageInfo"]["hasNextPage"]:
            return out
        after = p["pageInfo"]["endCursor"]


def chunks(seq, n=CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def buildings(kommune):
    return page("BBR_Bygning",
                "kommunekode:{ eq:$kom }, byg021BygningensAnvendelse:{ in:$codes }, status:{ in:$st }", BYG_FIELDS,
                {"kom": ("String!", kommune), "codes": ("[String!]", CODES), "st": ("[String!]", LIVE)})


def cases_for(building_ids):
    """{building id: [case, …]} via BBR_Sagsniveau. Both link fields are checked, so a case attached
    as sagsdata (the case's own data) or as stamdata (the object it concerns) is found."""
    links = []
    for field in ("sagsdataBygning", "stamdataBygning"):
        for c in chunks(building_ids):
            links += page("BBR_Sagsniveau", f"{field}:{{ in:$ids }}",
                          "id_lokalId status byggesag sagstype niveautype sagsdataBygning stamdataBygning",
                          {"ids": ("[String!]", c)})
    case_ids = sorted({l["byggesag"] for l in links if l.get("byggesag")})
    cases = {}
    for c in chunks(case_ids):
        for s in page("BBR_BBRSag", "id_lokalId:{ in:$ids }", SAG_FIELDS, {"ids": ("[String!]", c)}):
            cases[s["id_lokalId"]] = s
    by_building = collections.defaultdict(list)
    for l in links:
        s = cases.get(l.get("byggesag"))
        if not s:
            continue
        for b in (l.get("sagsdataBygning"), l.get("stamdataBygning")):
            if b in set(building_ids):
                by_building[b].append(s)
    return by_building, links, cases


def is_recent(case):
    """A case counts as recent while its permit — or, failing that, its case date — is within RECENT_CUT."""
    d = (case or {}).get("sag003Byggetilladelsesdato") or (case or {}).get("sag002Byggesagsdato")
    return bool(d) and d[:10] >= RECENT_CUT


def open_case(cases):
    """The newest case that is still open: no completion date and not closed/shelved."""
    live = [c for c in cases if not c.get("sag010FuldfoerelseAfByggeri") and c.get("status") not in CASE_CLOSED]
    if not live:
        return None
    return sorted(live, key=lambda c: (c.get("sag009ForventetFuldfoertDato") or "",
                                       c.get("sag003Byggetilladelsesdato") or "",
                                       c.get("sag002Byggesagsdato") or ""))[-1]


# ---------- DAR: address and coordinate for buildings BBR has not placed ----------
DAR = "https://graphql.datafordeler.dk/DAR/v3"
DAR_OUT = ROOT / "data" / "raw" / "dar" / "public_adresse.jsonl"


def dar_page(entity, fields, ids):
    """Look up DAR objects by id (100 per request)."""
    out, t = [], now()
    for c in chunks(ids):
        after = None
        while True:
            q = (f"query($first:Int!,$after:String,$t:DafDateTime!,$ids:[String!]) {{ {entity}"
                 f"(first:$first, after:$after, virkningstid:$t, registreringstid:$t, where:{{ id_lokalId:{{ in:$ids }} }})"
                 f" {{ pageInfo {{ endCursor hasNextPage }} nodes {{ {fields} }} }} }}")
            body = json.dumps({"query": q, "variables": {"first": 1000, "after": after, "t": t, "ids": c}}).encode()
            r = json.loads(fb.http(f"{DAR}?apiKey={fb.key()}", body))
            if "errors" in r:
                sys.exit(f"{entity}: {json.dumps(r['errors'], ensure_ascii=False)[:400]}")
            p = r["data"][entity]
            out += p["nodes"]
            if not p["pageInfo"]["hasNextPage"]:
                break
            after = p["pageInfo"]["endCursor"]
    return out


def geocode(buildings):
    """{building id: {address, wkt}} for buildings without a BBR coordinate, via
    BBR husnummer → DAR_Husnummer → DAR_Adressepunkt.position (EPSG:25832)."""
    need = [b for b in buildings if not (b.get("byg404Koordinat") or {}).get("wkt") and b.get("husnummer")]
    if not need:
        return {}
    hn_ids = sorted({b["husnummer"] for b in need})
    hn = {h["id_lokalId"]: h for h in dar_page("DAR_Husnummer", "id_lokalId husnummertekst adgangspunkt navngivenVej postnummer", hn_ids)}
    pts = {p["id_lokalId"]: p for p in dar_page("DAR_Adressepunkt", "id_lokalId position { wkt crs }",
                                                sorted({h["adgangspunkt"] for h in hn.values() if h.get("adgangspunkt")}))}
    veje = {v["id_lokalId"]: v for v in dar_page("DAR_NavngivenVej", "id_lokalId vejnavn",
                                                 sorted({h["navngivenVej"] for h in hn.values() if h.get("navngivenVej")}))}
    post = {p["id_lokalId"]: p for p in dar_page("DAR_Postnummer", "id_lokalId postnr navn",
                                                 sorted({h["postnummer"] for h in hn.values() if h.get("postnummer")}))}
    out = {}
    for b in need:
        h = hn.get(b["husnummer"])
        if not h:
            continue
        pt = pts.get(h.get("adgangspunkt")) or {}
        v = veje.get(h.get("navngivenVej")) or {}
        pn = post.get(h.get("postnummer")) or {}
        out[b["id_lokalId"]] = {"husnummer": b["husnummer"],
                                "address": " ".join(x for x in [v.get("vejnavn"), h.get("husnummertekst")] if x) or None,
                                "postnr": pn.get("postnr"), "postnr_navn": pn.get("navn"),
                                "wkt": (pt.get("position") or {}).get("wkt")}
    DAR_OUT.parent.mkdir(parents=True, exist_ok=True)
    have = {}
    if DAR_OUT.exists():
        for line in DAR_OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line); have[r["id"]] = r
    for bid, r in out.items():
        have[bid] = {"id": bid} | r
    DAR_OUT.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in have.values()), encoding="utf-8")
    return out


def run(kommune, measure_only=False):
    RAW.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bygs = buildings(kommune)
    pending = [b for b in bygs if b["status"] in ("2", "3")]
    by_building, links, cases = cases_for([b["id_lokalId"] for b in pending]) if pending else ({}, [], {})
    geo = {} if measure_only else geocode(bygs)
    if not measure_only:
        (RAW / f"{kommune}_bygning.jsonl").write_text("".join(json.dumps(b, ensure_ascii=False) + "\n" for b in bygs), encoding="utf-8")
        (RAW / f"{kommune}_sag.jsonl").write_text("".join(
            json.dumps({"bygning": b, "case": c}, ensure_ascii=False) + "\n" for b, cs in by_building.items() for c in cs), encoding="utf-8")
    with_any = sum(1 for b in pending if by_building.get(b["id_lokalId"]))
    with_open = sum(1 for b in pending if open_case(by_building.get(b["id_lokalId"], [])))
    with_eta = sum(1 for b in pending if (open_case(by_building.get(b["id_lokalId"], [])) or {}).get("sag009ForventetFuldfoertDato"))
    with_permit = sum(1 for b in pending if (open_case(by_building.get(b["id_lokalId"], [])) or {}).get("sag003Byggetilladelsesdato"))
    return {"kommune": kommune, "buildings": len(bygs),
            "existing": sum(1 for b in bygs if b["status"] == "6"),
            "planned": sum(1 for b in bygs if b["status"] == "2"),
            "under_construction": sum(1 for b in bygs if b["status"] == "3"),
            "pending": len(pending), "with_any_case": with_any, "with_open_case": with_open,
            "with_expected_completion": with_eta, "with_permit_date": with_permit,
            "link_rows": len(links), "cases": len(cases),
            "seconds": round(time.time() - t0),
            "recent_cases": sum(1 for b in pending if is_recent(open_case(by_building.get(b["id_lokalId"], [])))),
            "no_bbr_coordinate": sum(1 for b in pending if not (b.get("byg404Koordinat") or {}).get("wkt")),
            "geocoded_via_dar": sum(1 for b in pending if geo.get(b["id_lokalId"], {}).get("wkt"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kommune", help="0147 or 0101,0147")
    ap.add_argument("--metro", action="store_true", help="Copenhagen + 18 suburban municipalities (fetch_bbr.METRO)")
    ap.add_argument("--all", action="store_true", help="every municipality")
    ap.add_argument("--measure", action="store_true", help="print the case-coverage measurement only, write nothing")
    ap.add_argument("--refresh", action="store_true", help="refetch municipalities that already have a file")
    ap.add_argument("--workers", type=int, default=3, help="municipalities fetched in parallel; 3–4 is polite")
    args = ap.parse_args()
    fb.load_env()
    if args.kommune:
        codes = [k.strip() for k in args.kommune.split(",")]
    elif args.metro:
        codes = list(fb.METRO)
    elif args.all:
        codes = [f"{c:04d}" for c in fb.all_kommuner()] if hasattr(fb, "all_kommuner") else sorted(
            {f["properties"]["kode"] for f in json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text(encoding="utf-8"))["features"]})
    else:
        ap.error("give --kommune, --metro or --all")
    todo = [k for k in codes if args.measure or args.refresh or not (RAW / f"{k}_bygning.jsonl").exists()]
    skipped = len(codes) - len(todo)
    if skipped:
        print(f"{skipped} municipalities already fetched — skipping (use --refresh to redo them)")
    tot = collections.Counter()
    results = {}
    if args.workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for k, r in zip(todo, ex.map(lambda k: run(k, args.measure), todo)):
                results[k] = r
    else:
        for k in todo:
            results[k] = run(k, args.measure)
    for k in todo:
        r = results[k]
        print(f"{r['kommune']} {(byname(r['kommune']) + ':'):18} {r['buildings']:>5} buildings · existing {r['existing']:>5} · open cases {r['pending']:>4} (recent {r['recent_cases']:>3})")
        print(f"    of the {r['pending']} open-case buildings: {r['with_any_case']} have a case row, "
              f"{r['with_open_case']} an open case, {r['with_expected_completion']} an expected completion date (sag009), "
              f"{r['with_permit_date']} a permit date (sag003)")
        if not args.measure:
            print(f"    coordinates: {r['pending'] - r['no_bbr_coordinate']} from BBR · {r['geocoded_via_dar']} geocoded via DAR "
                  f"· {r['no_bbr_coordinate'] - r['geocoded_via_dar']} still without a point · {r['seconds']} s")
        for key, v in r.items():
            if isinstance(v, int):
                tot[key] += v
    if len(todo) > 1:
        print(f"\npilot total: {tot['pending']} planned/under-construction · {tot['with_expected_completion']} with an expected completion date "
              f"({(tot['with_expected_completion'] / tot['pending'] * 100 if tot['pending'] else 0):.0f} %) · "
              f"{tot['with_permit_date']} with a permit date ({(tot['with_permit_date'] / tot['pending'] * 100 if tot['pending'] else 0):.0f} %)")


if __name__ == "__main__":
    main()
