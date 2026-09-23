#!/usr/bin/env python3
"""Build the Schools layer: STIL education statistics joined onto the BBR Grundskole buildings.

Inputs : data/raw/uddstat/*.jsonl              (scripts/fetch_uddstat.py --schools)
         data/external/institutionsregister.csv (coordinates, type, kommune, afdeling → institution)
         data/processed/public/<kommune>.json   (the BBR buildings to attach schools to)
         data/geo/postnumre.geojson, cph_kvarterer.geojson
Outputs: data/processed/schools.json            one record per school, with 3 years of measures
         data/processed/public/<kommune>.json   rewritten: matched buildings gain "school": "<nr>"
         data/processed/public_index.json       gains the per-area school aggregates

Run AFTER scripts/build_public.py — that script rewrites both the per-kommune files and the index,
so running it afterwards would drop the school references and the aggregates written here.

Join (docs/SCHOOLS.md §4): institutionsnummer → register coordinates → every BBR building with
anvendelse 421 within 150 m. A school with no 421 hit falls back to 420/429 at the same radius;
one with neither is kept without geometry. All buildings of a campus get the same school.

Usage: python3 scripts/build_schools.py [--quiet]
"""
import argparse
import collections
import datetime as dt
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from shapely.geometry import Point  # noqa: E402
import fetch_bbr as fb  # noqa: E402
import fetch_uddstat as fu  # noqa: E402
from build_bbr import index, lookup  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "uddstat"
PUB = ROOT / "data" / "processed" / "public"
IDX = ROOT / "data" / "processed" / "public_index.json"
OUT = ROOT / "data" / "processed" / "schools.json"

YEARS = fu.SCHOOL_YEARS
RADIUS_M = 150
PRIMARY = {"421"}                 # BBR Grundskole
FALLBACK = {"420", "429"}         # phased-out education code + "anden bygning til undervisning"
# the five trivsel indicators, cube label → our key
TRIVSEL = {"Generel trivsel": "trivsel_general", "Faglig trivsel": "trivsel_faglig",
           "Social trivsel": "trivsel_social", "Støtte og inspiration": "trivsel_stoette",
           "Ro og orden": "trivsel_ro"}
# the measures an area aggregate averages: school measure → (indicator key, the count that weights it).
# Each measure is weighted by its OWN denominator, not by the school's total roll: a grade average
# covers only the pupils who sat the exams and trivsel only those who answered the survey. Weighting
# all three by pupils_total pulled several municipalities 0.1–0.5 grade points off the figure STIL
# publishes for the same municipality.
AGG_KEYS = {"grade_avg": ("school_grade_avg", "grade_n"),
            "soc_ref_diff": ("school_socref_diff", "grade_n"),
            "trivsel_general": ("school_trivsel", "trivsel_n")}
# specialskoler are excluded from every area aggregate: their intake makes an average meaningless
AGG_TYPES = {"folkeskole", "fri grundskole"}


def rows(tag):
    p = RAW / f"{tag}.jsonl"
    if not p.exists():
        sys.exit(f"missing {p.relative_to(ROOT)} — run: python3 scripts/fetch_uddstat.py --schools")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l]


def num(r, m):
    return fu.dknum(r.get(m))


def hav(a, b):
    """Great-circle metres between two (lat, lon) pairs."""
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def wmean(pairs):
    """Weighted mean of (value, weight); None when nothing carries a value.

    A school with a value but no pupil count still counts, with weight 1 — dropping it would
    silently bias the mean toward the schools that happen to have an elevtal.
    """
    s = w = 0.0
    for v, k in pairs:
        if v is None:
            continue
        k = k if k and k > 0 else 1
        s += v * k
        w += k
    return round(s / w, 2) if w else None


def collect(reg):
    """Read every cached pull into {institutionsnummer: {skoleår: {measure: value}}}."""
    per = collections.defaultdict(lambda: collections.defaultdict(dict))
    # afdelingsnummer → institutionsnummer, via the register's Hovedinstitution column
    to_inst = {nr: (r["hoved"] if r["hoved"] and r["hoved"] in reg else nr) for nr, r in reg.items()}

    def put(nr, year, key, val):
        if nr in reg and val is not None:
            per[nr][year][key] = val

    for r in rows("KARA_KARAGNS_grades"):
        nr, y = fu.col(r, fu.INST), fu.col(r, fu.AAR)
        put(nr, y, "grade_avg", num(r, "Gennemsnit i bundne prøver"))
        put(nr, y, "grade_n", num(r, "Antal elever med alle bundne prøver"))
    for r in rows("KARA_KARADM_grades_dm"):
        nr, y = fu.col(r, fu.INST), fu.col(r, fu.AAR)
        put(nr, y, "grade_dansk", num(r, "Gennemsnit - Dansk bundne prøver"))
        put(nr, y, "grade_matematik", num(r, "Gennemsnit - Matematik bundne prøver"))
    for r in rows("ELEV_ELEVEX_pupils"):
        put(fu.col(r, fu.INST), fu.col(r, fu.AAR), "pupils_total", num(r, "Antal elever"))
    # herkomst: the cube splits Dansk / Indvandrer / Efterkommer / <uoplyst>; we keep the first
    # and the sum of the two minority categories, and leave <uoplyst> out of both
    herk = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))
    for r in rows("ELEV_ELEVEX_pupils_herkomst"):
        nr, y, h, v = fu.col(r, fu.INST), fu.col(r, fu.AAR), fu.col(r, fu.HERKOMST), num(r, "Antal elever")
        if v is None:
            continue
        slot = herk[nr][y]
        if h == "Dansk":
            slot[0] = (slot[0] or 0) + v
        elif h in ("Indvandrer", "Efterkommer"):
            slot[1] = (slot[1] or 0) + v
    for nr, ys in herk.items():
        for y, (da, iv) in ys.items():
            put(nr, y, "pupils_dansk", da)
            put(nr, y, "pupils_indv_efterk", iv)
    for r in rows("TRIV_TRIVIND_trivsel"):
        nr, y = fu.col(r, fu.INST), fu.col(r, fu.AAR)
        k = TRIVSEL.get(fu.col(r, fu.TRIV_IND))
        if k:
            put(nr, y, k, num(r, "Indikatorsvar"))
            if k == "trivsel_general":
                put(nr, y, "trivsel_n", num(r, "Totale antal elever - indikatorsvar"))

    # OVER/OVERSKO is published per afdeling. Roll it up to the institution: a school with several
    # afdelinger gets the pupil-weighted mean of klassekvotient and of the socioøkonomisk reference,
    # weighted by that afdeling's own Elevtal.
    afd = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows("OVER_OVERSKO_overblik"):
        a, y = fu.col(r, fu.AFD), fu.col(r, fu.AAR)
        nr = to_inst.get(a, a)
        if nr not in reg:
            continue
        afd[nr][y].append({
            "n": num(r, "Elevtal"),
            "klassekvotient": num(r, "Klassekvotient"),
            "soc_ref_grade": num(r, "SocRef Karaktergennemsnit"),
            "soc_ref_expected": num(r, "SocRef Socioøkonomisk reference"),
            "soc_ref_diff": num(r, "SocRef Forskel"),
            "sig": (r.get("SocRef Signifikant forskel") or "").strip() or None,
        })
    for nr, ys in afd.items():
        for y, parts in ys.items():
            for k in ("klassekvotient", "soc_ref_grade", "soc_ref_expected", "soc_ref_diff"):
                put(nr, y, k, wmean([(p[k], p["n"]) for p in parts]))
            put(nr, y, "afdelinger_n", len(parts))
            # the significance verdict does not average; keep it only when the school is one afdeling,
            # and otherwise only when every afdeling agrees
            sigs = {p["sig"] for p in parts if p["sig"]}
            if len(sigs) == 1:
                put(nr, y, "soc_ref_significant", sigs.pop())
    return per, to_inst


def bbr_match(reg, quiet=False):
    """school → the BBR buildings of its campus. Returns (links, stats)."""
    buildings = collections.defaultdict(list)     # kommunekode → rows
    for k in fb.METRO:
        p = PUB / f"{k}.json"
        if p.exists():
            buildings[k] = json.loads(p.read_text(encoding="utf-8"))["buildings"]
    pool = [b for rows_ in buildings.values() for b in rows_
            if b.get("lat") and b.get("lon") and b["code"] in (PRIMARY | FALLBACK)]
    cell = 0.0025
    grid = collections.defaultdict(list)
    for b in pool:
        grid[(int(b["lat"] / cell), int(b["lon"] / cell))].append(b)

    links, stats = {}, collections.Counter()
    for nr, s in reg.items():
        if not s["lat"]:
            stats["no_coord"] += 1
            links[nr] = ([], "none")
            continue
        here = (s["lat"], s["lon"])
        cand = [b for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                for b in grid.get((int(s["lat"] / cell) + dy, int(s["lon"] / cell) + dx), [])]
        near = [(hav(here, (b["lat"], b["lon"])), b) for b in cand]
        near = [(d, b) for d, b in near if d <= RADIUS_M]
        primary = [(d, b) for d, b in near if b["code"] in PRIMARY]
        if primary:
            hit, kind = primary, "421"
        else:
            fall = [(d, b) for d, b in near if b["code"] in FALLBACK]
            hit, kind = (fall, "fallback_42x") if fall else ([], "none")
        stats[kind] += 1
        links[nr] = ([b["id"] for _, b in sorted(hit, key=lambda t: t[0])], kind)
    return links, stats, buildings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    today = dt.date.today()
    retrieved = (json.loads((RAW / "KARA_KARAGNS_grades.meta.json").read_text(encoding="utf-8"))
                 .get("retrieved") if (RAW / "KARA_KARAGNS_grades.meta.json").exists() else today.isoformat())

    reg = fu.register_schools(fu.METRO_NAMES)
    per, _ = collect(reg)
    links, stats, buildings = bbr_match(reg)

    pn = index(ROOT / "data" / "geo" / "postnumre.geojson", lambda p: str(p.get("nr")))
    kv = index(ROOT / "data" / "geo" / "cph_kvarterer.geojson", lambda p: str(p.get("kvarternr")))

    # --- benchmarks -----------------------------------------------------------
    bench_kom, bench_dk = collections.defaultdict(dict), {}
    for r in rows("KARA_KARAGNS_bench_kommune"):
        v = num(r, "Gennemsnit i bundne prøver")
        if v is not None:
            bench_kom[fu.col(r, fu.KOM)][fu.col(r, fu.AAR)] = v
    for r in rows("KARA_KARAGNS_bench_land"):
        v = num(r, "Gennemsnit i bundne prøver")
        if v is not None:
            bench_dk[fu.col(r, fu.AAR)] = v

    # --- one record per school ------------------------------------------------
    schools = []
    for nr, s in sorted(reg.items()):
        ys = {y: per[nr][y] for y in YEARS if per[nr].get(y)}
        # `latest` is per measure, not one year for all: the socioøkonomisk reference lags the
        # grades by a year, so a single "latest year" would blank it out on every school
        latest, latest_year = {}, {}
        for y in YEARS:
            for k, v in (ys.get(y) or {}).items():
                latest[k] = v
                latest_year[k] = y
        ids, kind = links[nr]
        rec = {"nr": nr, "name": s["name"], "type": s["type"], "kommune": s["kommune"], "kom": (s["kom"] or "").lstrip("0"),
               "enhedsart": s["enhedsart"], "address": s["address"], "postnr": s["postnr"],
               "lat": s["lat"], "lon": s["lon"], "years": ys, "latest": latest, "latest_year": latest_year,
               "bbr_ids": ids, "bbr_match": kind}
        if s["lat"]:
            pt = Point(s["lon"], s["lat"])
            rec["postnr"] = s["postnr"] or lookup(pn, pt)
            rec["kvarter"] = lookup(kv, pt)
        schools.append(rec)
    by_nr = {s["nr"]: s for s in schools}

    # --- write the school reference back onto the buildings -------------------
    ref = {}
    for s in schools:
        for bid in s["bbr_ids"]:
            ref.setdefault(bid, s["nr"])              # first school wins; campuses rarely overlap
    touched = 0
    for k, rows_ in buildings.items():
        n = 0
        for b in rows_:
            if b["id"] in ref:
                b["school"] = ref[b["id"]]
                n += 1
            elif "school" in b:
                del b["school"]                        # a rebuild must not leave a stale reference
        p = PUB / f"{k}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["buildings"] = rows_
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        touched += n

    # --- area aggregates ------------------------------------------------------
    areas = collections.defaultdict(list)
    for s in schools:
        for key in (f"kommune:{s['kom']}", f"postnr:{s['postnr']}" if s.get("postnr") else None,
                    f"kvarter:{s['kvarter']}" if s.get("kvarter") else None):
            if key:
                areas[key].append(s)
    agg = {}
    for key, list_ in areas.items():
        keep = [s for s in list_ if s["type"] in AGG_TYPES]
        pupils = [s["latest"].get("pupils_total") for s in keep]
        e = {"schools_n": len(keep), "schools_all_n": len(list_),
             "school_pupils": round(sum(p for p in pupils if p)) or None}
        for measure, (out_key, weight) in AGG_KEYS.items():
            e[out_key] = wmean([(s["latest"].get(measure),
                                 s["latest"].get(weight) or s["latest"].get("pupils_total")) for s in keep])
        withgrade = sum(1 for s in keep if s["latest"].get("grade_avg") is not None)
        e["school_grade_share"] = round(100.0 * withgrade / len(keep), 1) if keep else None
        e["pupils_per_school"] = round(e["school_pupils"] / len(keep)) if keep and e["school_pupils"] else None
        agg[key] = e

    OUT.write_text(json.dumps({
        "built": today.isoformat(), "retrieved": retrieved, "years": YEARS,
        "source": "Uddannelsesstatistik.dk (STIL) — GS cubes KARA/KARAGNS, KARA/KARADM, OVER/OVERSKO, "
                  "TRIV/TRIVIND, ELEV/ELEVEX; institution register for coordinates and type",
        "attribution": "Kilde: Uddannelsesstatistik.dk",
        "benchmarks": {"kommune": bench_kom, "denmark": bench_dk},
        "n": len(schools), "schools": schools,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # --- merge the aggregates into public_index.json --------------------------
    if IDX.exists():
        idx = json.loads(IDX.read_text(encoding="utf-8"))
        for key, e in agg.items():
            idx["areas"].setdefault(key, {"counts": {}, "m2_existing": 0, "recent_cases": [], "stale_cases": 0})
            idx["areas"][key].update({k: v for k, v in e.items() if v is not None})
        idx["schools"] = {"built": today.isoformat(), "retrieved": retrieved, "years": YEARS,
                          "n": len(schools), "attribution": "Kilde: Uddannelsesstatistik.dk",
                          "benchmarks": {"kommune": bench_kom, "denmark": bench_dk}}
        IDX.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    if a.quiet:
        return
    n_grade = sum(1 for s in schools if s["latest"].get("grade_avg") is not None)
    n_soc = sum(1 for s in schools if s["latest"].get("soc_ref_diff") is not None)
    n_triv = sum(1 for s in schools if s["latest"].get("trivsel_general") is not None)
    n_kk = sum(1 for s in schools if s["latest"].get("klassekvotient") is not None)
    print(f"schools: {len(schools)} in {len(fb.METRO)} municipalities · register {fu.REGISTER.name}")
    print(f"  with a grade average  {n_grade:>4} ({n_grade/len(schools)*100:.0f} %)")
    print(f"  with socioøk. ref.    {n_soc:>4} ({n_soc/len(schools)*100:.0f} %)")
    print(f"  with trivsel          {n_triv:>4} ({n_triv/len(schools)*100:.0f} %)")
    print(f"  with klassekvotient   {n_kk:>4} ({n_kk/len(schools)*100:.0f} %)")
    print(f"BBR join (≤ {RADIUS_M} m): 421 {stats['421']} · fallback 420/429 {stats['fallback_42x']} · "
          f"none {stats['none']} · no coordinate {stats['no_coord']}")
    print(f"  {touched} buildings carry a school reference")
    print(f"area aggregates: {len(agg)} areas (kommune/postnr/kvarter) → {IDX.name}")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1e3:.0f} kB)")


if __name__ == "__main__":
    main()
