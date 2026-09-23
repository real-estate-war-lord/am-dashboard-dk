#!/usr/bin/env python3
"""Thin client for the STIL education-statistics API (api.uddannelsesstatistik.dk).

Needs UDDSTAT_API_KEY in .env (free key, self-service at api.uddannelsesstatistik.dk/GetStarted).
Licence: free reuse including commercial. Attribution "Kilde: Uddannelsesstatistik.dk" + retrieval date.

Two endpoints, both POST, both Bearer-authenticated (the OpenAPI spec lives at /swagger/v1/swagger.json):

  /Api/v1/skema      the cube catalogue. Send progressively more of {område, emne, underemne} and it
                     drills down: {} → områder, {område} → emner, {område,emne} → underemner,
                     {område,emne,underemne} → that cube's detaljer (dimensions, with member counts),
                     nøgletal (measures) and rapporter. Adding {detalje:"<dimension>"} lists its members.
  /Api/v1/statistik  the data. Paged on "side"; "side_størrelse" caps at 100000 rows.

Two things to know about the returned rows:
  * numbers are Danish-formatted strings — "2.351" is 2351, "7,3" is 7.3. Use dknum().
  * suppressed cells are OMITTED, not nulled: a cube drops any cell under 3 observations (under 5
    pupils for trivsel and socioøkonomisk reference). An absent row is "too small to publish",
    never "zero" — see docs/SCHOOLS.md.

Usage:
  python3 scripts/fetch_uddstat.py --example                 # documented ELEV/ELEVEX call, København
  python3 scripts/fetch_uddstat.py --skema                   # list områder
  python3 scripts/fetch_uddstat.py --skema GS/KARA           # list that emne's underemner
  python3 scripts/fetch_uddstat.py --skema GS/KARA/KARAGNS   # that cube's dimensions + measures
  python3 scripts/fetch_uddstat.py --skema GS/KARA/KARAGNS --detalje "[Skoleår].[Skoleår]"
  python3 scripts/fetch_uddstat.py --map                     # the GS cubes this project wants
  python3 scripts/fetch_uddstat.py --query q.json            # run a saved query body, cache the rows
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "uddstat"
BASE = "https://api.uddannelsesstatistik.dk"
PAGE = 50000                     # rows per request; the API allows up to 100000

# The 19 metro municipalities, as the cubes spell them in [Institution].[Beliggenhedskommune].
# Same set as fetch_bbr.METRO, which holds the kommunekoder.
METRO_NAMES = ["København", "Frederiksberg", "Ballerup", "Brøndby", "Dragør", "Gentofte", "Gladsaxe",
               "Glostrup", "Herlev", "Albertslund", "Hvidovre", "Høje-Taastrup", "Lyngby-Taarbæk",
               "Rødovre", "Ishøj", "Tårnby", "Vallensbæk", "Furesø", "Rudersdal"]


def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def key():
    load_env()
    k = os.environ.get("UDDSTAT_API_KEY")
    if not k:
        sys.exit("UDDSTAT_API_KEY missing — put it in .env (key from api.uddannelsesstatistik.dk/GetStarted)")
    return k


def post(path, body, timeout=300):
    """POST JSON, with a retry on the transient statuses. Returns the decoded body."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = BASE + urllib.parse.quote(path)
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {key()}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "am-dashboard-dk/0.1",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            hint = ""
            if e.code in (401, 403):
                hint = "\n→ the key was rejected. Check UDDSTAT_API_KEY in .env has no spaces or quotes."
            if e.code == 400:
                hint = "\n→ the API rejected the query body. Check the codes with --skema."
            sys.exit(f"HTTP {e.code} from {path}: {msg}{hint}")
        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    return None


def skema(område=None, emne=None, underemne=None, detalje=None):
    """Catalogue lookup. Omit everything for the områder, then drill down."""
    body = {k: v for k, v in (("område", område), ("emne", emne),
                              ("underemne", underemne), ("detalje", detalje)) if v}
    return post("/Api/v1/skema", body)


def fetch(område, emne, underemne, nøgletal, detaljering, filtre=None, tomme_rækker=True):
    """All rows of one cube query, following "side" until a short page comes back."""
    rows, side = [], 0
    while True:
        body = {"område": område, "emne": emne, "underemne": underemne,
                "nøgletal": list(nøgletal), "detaljering": list(detaljering),
                "indlejret": False, "tomme_rækker": tomme_rækker, "formattering": "json",
                "side": side, "side_størrelse": PAGE}
        if filtre:
            body["filtre"] = filtre
        page = post("/Api/v1/statistik", body)
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE:
            break
        side += 1
    return rows


def cached(område, emne, underemne, nøgletal, detaljering, filtre=None,
           tomme_rækker=True, refresh=False, tag=None):
    """fetch(), cached to data/raw/uddstat/<emne>_<underemne>[_<tag>].jsonl.

    The sidecar .meta.json records the query that produced the file, so changing the measures or
    the detaljering refetches instead of quietly reusing rows with different columns. `tag`
    separates two cuts of the same cube (ELEVEX total vs by herkomst, KARAGNS school vs kommune).
    """
    RAW.mkdir(parents=True, exist_ok=True)
    stem = f"{emne}_{underemne}" + (f"_{tag}" if tag else "")
    jsonl, meta_p = RAW / f"{stem}.jsonl", RAW / f"{stem}.meta.json"
    query = {"område": område, "emne": emne, "underemne": underemne, "nøgletal": list(nøgletal),
             "detaljering": list(detaljering), "filtre": filtre, "tomme_rækker": tomme_rækker}
    stamp = hashlib.sha256(json.dumps(query, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]

    if jsonl.exists() and meta_p.exists() and not refresh:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if meta.get("query_hash") == stamp:
            return [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l]

    rows = fetch(område, emne, underemne, nøgletal, detaljering, filtre, tomme_rækker)
    jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    meta_p.write_text(json.dumps({
        "source": "Uddannelsesstatistik.dk (STIL)",
        "retrieved": dt.date.today().isoformat(),
        "attribution": "Kilde: Uddannelsesstatistik.dk",
        "endpoint": f"{BASE}/Api/v1/statistik",
        "query": query, "query_hash": stamp, "rows": len(rows),
        "note": "suppressed cells (<3 obs; <5 pupils for trivsel/socioøkonomisk reference) are omitted, not nulled",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows


def dknum(s):
    """Danish-formatted cube value → float.

    '2.351' → 2351.0, '7,3' → 7.3, '100,0 %' → 100.0 (the percentage cubes return the sign).
    Empty or a suppression marker → None; never 0, because an absent value means "not published".
    """
    if s is None:
        return None
    s = str(s).replace("\xa0", " ").strip().rstrip("%").strip()
    if not s or s in {"-", "..", "*"}:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# --- commands ---------------------------------------------------------------

def cmd_example():
    """The documented ELEV/ELEVEX call, proving the key works. Filtered to kommune København."""
    dim_inst = "[Institution].[Institution]"
    dim_num = "[Institution].[Institutionsnummer]"
    dim_kom = "[Institution].[Beliggenhedskommune]"
    dim_år = "[Skoleår].[Skoleår]"
    rows = fetch("GS", "ELEV", "ELEVEX", ["Antal elever"],
                 [dim_inst, dim_num, dim_kom, dim_år],
                 filtre={dim_kom: ["København"]})
    print(f"GS/ELEV/ELEVEX, filtre {dim_kom}=København → {len(rows)} rows")
    for r in rows[:3]:
        print("  " + json.dumps(r, ensure_ascii=False))
    if rows:
        tot = sum(dknum(r.get("Antal elever")) or 0 for r in rows)
        print(f"  (Antal elever summed over the returned rows: {tot:,.0f})")
    return rows


def cmd_skema(path, detalje):
    parts = [p for p in (path or "").split("/") if p]
    res = skema(*(parts + [None] * (3 - len(parts))), detalje=detalje) if parts else skema()
    if isinstance(res, list):
        for e in res:
            if isinstance(e, dict):
                print(f"  {e.get('ID', ''):<14} {e.get('Name', '')}")
            else:
                print(f"  {e}")
    elif isinstance(res, dict):
        for d in res.get("detaljer", []):
            print(f"  dim  {d['name']:<58} {d.get('count', '')} members")
        for m in res.get("nøgletal", []):
            print(f"  m    {m}")
        for r in res.get("rapporter", []) or []:
            print(f"  rap  {r}")
    else:
        print(res)


WANTED = [("GS", "KARA", "KARAGNS", "FP9 gennemsnit, bundne prøver"),
          ("GS", "KARA", "KARADM", "FP9 dansk og matematik"),
          ("GS", "KARA", "KARAFF", "FP9 per fag/fagdisciplin"),
          ("GS", "SOCR", "SOCREFEX", "socioøkonomisk reference, 1-årig"),
          ("GS", "SOCR", "SOCREF3ÅR", "socioøkonomisk reference, 3-årig"),
          ("GS", "TRIV", "TRIVIND", "elevtrivsel, indikatorer"),
          ("GS", "ELEV", "ELEVEX", "elevtal"),
          ("GS", "OVER", "OVERSKO", "skoleoverblik (klassekvotient?)")]


def cmd_map():
    """Print the dimensions and measures of every cube this project wants."""
    for omr, emne, ue, what in WANTED:
        print(f"\n=== {omr}/{emne}/{ue} — {what} ===")
        cmd_skema(f"{omr}/{emne}/{ue}", None)


# --- the Schools layer pull (docs/SCHOOLS.md) --------------------------------

SCHOOL_YEARS = ["2023/2024", "2024/2025", "2025/2026"]
INST = "[Institution].[Institutionsnummer]"
AFD = "[Institution].[Afdelingsnummer]"
KOM = "[Institution].[Beliggenhedskommune]"
AAR = "[Skoleår].[Skoleår]"
TRIV_IND = "[Trivselsindikator].[Trivselsindikator]"
HERKOMST = "[Herkomst].[Herkomst]"

# One entry per cube pull. `key` is the cache tag and the name printed in the coverage report;
# `unit` says which column carries the school identity, so the coverage count knows what to count.
SCHOOL_PULLS = [
    {"key": "grades", "emne": "KARA", "underemne": "KARAGNS", "unit": INST,
     "nøgletal": ["Gennemsnit i bundne prøver", "Antal elever med alle bundne prøver"],
     "detaljering": [INST, AAR], "what": "FP9 grade average, bundne prøver"},
    {"key": "grades_dm", "emne": "KARA", "underemne": "KARADM", "unit": INST,
     "nøgletal": ["Gennemsnit - Dansk bundne prøver", "Gennemsnit - Matematik bundne prøver"],
     "detaljering": [INST, AAR], "what": "FP9 dansk and matematik"},
    {"key": "overblik", "emne": "OVER", "underemne": "OVERSKO", "unit": AFD,
     "nøgletal": ["SocRef Karaktergennemsnit", "SocRef Socioøkonomisk reference", "SocRef Forskel",
                  "SocRef Signifikant forskel", "Klassekvotient", "Elevtal", "Karaktergennemsnit",
                  "Andel med højest trivsel"],
     "detaljering": [AFD, AAR], "what": "socioøkonomisk reference + klassekvotient (afdeling level)"},
    {"key": "trivsel", "emne": "TRIV", "underemne": "TRIVIND", "unit": INST,
     "nøgletal": ["Indikatorsvar", "Totale antal elever - indikatorsvar"],
     "detaljering": [INST, TRIV_IND, AAR], "what": "elevtrivsel, 5 indicators"},
    {"key": "pupils", "emne": "ELEV", "underemne": "ELEVEX", "unit": INST,
     "nøgletal": ["Antal elever"], "detaljering": [INST, AAR], "what": "elevtal, total"},
    {"key": "pupils_herkomst", "emne": "ELEV", "underemne": "ELEVEX", "unit": INST,
     "nøgletal": ["Antal elever"], "detaljering": [INST, HERKOMST, AAR], "what": "elevtal by herkomst"},
]
# Benchmarks: the same grade measure one and two levels up. No kommune filter — every municipality,
# so a school can be compared with its own kommune and with Denmark.
BENCH_PULLS = [
    {"key": "bench_kommune", "emne": "KARA", "underemne": "KARAGNS", "unit": KOM,
     "nøgletal": ["Gennemsnit i bundne prøver"], "detaljering": [KOM, AAR], "national": True,
     "what": "benchmark: grade average per kommune"},
    {"key": "bench_land", "emne": "KARA", "underemne": "KARAGNS", "unit": None,
     "nøgletal": ["Gennemsnit i bundne prøver"], "detaljering": [AAR], "national": True,
     "what": "benchmark: grade average, Denmark"},
]


def col(row, dim):
    """The value of a detaljering column. The API echoes '[A].[B]' back as '[A].[B].[B]'."""
    return row.get(f"{dim}.[{dim.rsplit('.', 1)[1].strip('[]')}]")


# The register's own names for the grundskole types we keep. Efterskoler, specialskoler for voksne,
# ungdomsskoler, FGU and gymnasier are deliberately out — see docs/SCHOOLS.md §4.
GRUNDSKOLE_TYPES = {"Folkeskoler": "folkeskole", "Friskoler og private grundskoler": "fri grundskole",
                    "Specialskoler for børn": "specialskole", "Kommunale internationale skoler": "fri grundskole"}
REGISTER = ROOT / "data" / "external" / "institutionsregister.csv"
# The register writes "<name> Kommune"; for København alone it uses the genitive, "Københavns
# Kommune", while the cubes and data/geo/kommuner.geojson both say "København". Stripping a
# trailing "s" is NOT a safe general rule — Assens, Horsens, Randers, Aarhus and five others
# really do end in one — so the one exception is spelled out here.
KOMMUNE_ALIAS = {"Københavns": "København"}
_KOM_CODE = None


def kommune_code(name):
    """Canonical kommune name → 4-digit kommunekode, from the vendored DAGI boundaries."""
    global _KOM_CODE
    if _KOM_CODE is None:
        p = ROOT / "data" / "geo" / "kommuner.geojson"
        _KOM_CODE = {f["properties"]["navn"]: f["properties"]["kode"]
                     for f in json.loads(p.read_text(encoding="utf-8"))["features"]} if p.exists() else {}
    return _KOM_CODE.get(name)


def register_kommune(raw):
    """The register's Beliggenhedskommune cell → the canonical kommune name."""
    n = raw.replace(" Kommune", "").strip()
    return KOMMUNE_ALIAS.get(n, n)


def register_schools(kommune_names=None):
    """Grundskole rows of the institution register, keyed by institutionsnummer.

    Semicolon-separated and UTF-8 *with BOM*, so the encoding has to be utf-8-sig. Returns
    {institutionsnummer: {...}}; `kommune_names` filters on Beliggenhedskommune ("København").
    """
    import csv
    want = set(kommune_names) if kommune_names else None
    out = {}
    with open(REGISTER, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            kind = GRUNDSKOLE_TYPES.get(r["Institutionstype, navn"])
            if not kind:
                continue
            kom = register_kommune(r["Beliggenhedskommune"])
            if want and kom not in want:
                continue
            try:
                lat, lon = float(r["Geokode: Breddegrad"]), float(r["Geokode: Længdegrad"])
            except ValueError:
                lat = lon = None
            out[r["Institutionsnummer"]] = {
                "nr": r["Institutionsnummer"], "name": r["Institutionsnavn"].strip(), "type": kind,
                "type_raw": r["Institutionstype, navn"], "kommune": kom, "kom": kommune_code(kom),
                "enhedsart": r["Enhedsart"],
                "hoved": r["Hovedinstitution"].strip() or None, "postnr": r["Postnummer"].strip() or None,
                "address": r["Adresse"].strip() or None,
                "lat": round(lat, 6) if lat else None, "lon": round(lon, 6) if lon else None,
            }
    return out


def cmd_schools(refresh=False):
    """Pull every cube the Schools layer needs, for the 19 metro kommuner and the latest 3 years."""
    reg = register_schools(METRO_NAMES)
    # afdelingsnummer → institutionsnummer, so the afdeling-level cube can be counted against schools
    to_inst = {nr: (r["hoved"] if r["hoved"] and r["hoved"] in reg else nr) for nr, r in reg.items()}
    print(f"metro kommuner: {len(METRO_NAMES)} · school years: {', '.join(SCHOOL_YEARS)}")
    print(f"register: {len(reg)} grundskoler in the 19 metro kommuner\n")
    for p in SCHOOL_PULLS + BENCH_PULLS:
        filtre = {AAR: SCHOOL_YEARS}
        if not p.get("national"):
            filtre[KOM] = METRO_NAMES
        rows = cached("GS", p["emne"], p["underemne"], p["nøgletal"], p["detaljering"],
                      filtre=filtre, tomme_rækker=False, refresh=refresh, tag=p["key"])
        measures = [m for m in p["nøgletal"]]
        # a row "covers" a school only if at least one measure actually carries a value —
        # suppressed cells come back as an empty string, not as an absent column
        units, with_val = set(), set()
        per_year = collections.defaultdict(set)
        for r in rows:
            u = col(r, p["unit"]) if p["unit"] else "DK"
            if u is None:
                continue
            units.add(u)
            if any(dknum(r.get(m)) is not None or (r.get(m) or "").strip() for m in measures):
                with_val.add(u)
                per_year[col(r, AAR)].add(u)
        print(f"{p['key']:<16} {p['emne']}/{p['underemne']:<8} {len(rows):>6} rows · "
              f"{len(with_val):>4} {'schools' if p['unit'] else 'rows'} with a value")
        print(f"{'':<16} {p['what']}")
        if p.get("national") or not p["unit"]:
            continue
        # coverage is measured against the register, not against the response: a suppressed school
        # is simply absent from the response, so "missing" can only be counted from the outside
        seen = {to_inst.get(u, u) for u in with_val}
        covered = seen & set(reg)
        missing = set(reg) - seen
        print(f"{'':<16} register coverage: {len(covered)}/{len(reg)} schools · {len(missing)} missing "
              f"(suppressed, no 9th grade, or not in this cube)")
        if missing:
            by_type = collections.Counter(reg[n]["type"] for n in missing)
            print(f"{'':<16} missing by type: " + " · ".join(f"{t} {n}" for t, n in by_type.most_common()))
        if per_year:
            print(f"{'':<16} by year: " + " · ".join(f"{y} {len(v)}" for y, v in sorted(per_year.items())))
    print("\ncached → data/raw/uddstat/  (one .jsonl + .meta.json per pull)")
    print("note: GS/SOCR/SOCREFEX and GS/SOCR/SOCREF3ÅR return 0 rows through the API at every\n"
          "      detaljering tried — the socioøkonomisk reference comes from OVER/OVERSKO instead.\n"
          "      See docs/SCHOOLS.md §2.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", action="store_true", help="run the documented ELEV/ELEVEX call for København")
    ap.add_argument("--skema", nargs="?", const="", metavar="OMRÅDE[/EMNE[/UNDEREMNE]]", help="catalogue lookup")
    ap.add_argument("--detalje", metavar="DIM", help="with --skema OMR/EMNE/UE: list that dimension's members")
    ap.add_argument("--map", action="store_true", help="dimensions + measures of the GS cubes this project wants")
    ap.add_argument("--schools", action="store_true", help="pull every cube the Schools layer needs (19 metro kommuner, latest 3 years)")
    ap.add_argument("--query", metavar="FILE", help="run a JSON query body and cache the rows")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    a = ap.parse_args()

    if a.example:
        cmd_example()
    elif a.skema is not None:
        cmd_skema(a.skema, a.detalje)
    elif a.map:
        cmd_map()
    elif a.schools:
        cmd_schools(refresh=a.refresh)
    elif a.query:
        q = json.loads(pathlib.Path(a.query).read_text(encoding="utf-8"))
        rows = cached(q["område"], q["emne"], q["underemne"], q["nøgletal"], q["detaljering"],
                      q.get("filtre"), q.get("tomme_rækker", True), refresh=a.refresh)
        print(f"{q['emne']}/{q['underemne']} → {len(rows)} rows → data/raw/uddstat/{q['emne']}_{q['underemne']}.jsonl")
        for r in rows[:3]:
            print("  " + json.dumps(r, ensure_ascii=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
