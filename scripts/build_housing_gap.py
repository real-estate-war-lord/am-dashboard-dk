#!/usr/bin/env python3
"""Build data/processed/housing_gap.json — is enough housing being built for the
population growth DST projects over the next five years?

The question the indicator answers, per municipality:

    demand_5y  = (P₂₀₃₁ − P₂₀₂₆) / persons_per_hh      dwellings the projection implies
    supply_5y  = mean yearly completions, last 5 full years × 5
    gap        = demand_5y − supply_5y                  positive = undersupply
    gap_per_1000 = gap / P₂₀₂₆ × 1000                   comparable across sizes

`persons_per_hh` is FOLK1A population ÷ FAM55N households at the same 1 January, so it
is the municipality's own household size rather than a national average. See
docs/FORECAST.md §7 for the assumptions and what is deliberately not modelled.

Inputs
  data/processed/forecast.json             P₂₀₂₆ and P₂₀₃₁ (build_forecast.py)
  DST FOLK1A                               population, 1 January
  DST FAM55N                               households, 1 January
  DST BYGV33                               dwellings by phase of construction, quarterly

Raw pulls are reused before they are fetched: if `fetch_statbank.py` has already left a
usable `data/raw/dst_<TABLE>_<date>.csv` this script reads it, and only pulls its own copy
into `data/raw/forecast/housing/` when the cached selection does not cover what it needs.
BYGV33 always needs its own pull — the repo's cached selection is `BYGFASE=3` (completed)
only, and the permitted-not-started pipeline needs phases 1 and 2 as well. The tableinfo is only
cached here when it differs from the committed `data/raw/dst_<TABLE>.meta.json`; see tableinfo().

Output
  data/processed/housing_gap.json
    {"meta": {...},
     "kommuner": {"<code>": {"pop", "households", "persons_per_hh", "p_base", "p_mid",
                             "demand_5y", "supply_5y", "completions_by_year", "gap",
                             "gap_per_1000", "permits_4q", "starts_4q",
                             "pipeline_permitted"}}}

Usage
  python scripts/build_housing_gap.py                 # reuse/fetch, build, print the ranking
  python scripts/build_housing_gap.py --no-fetch      # build from cached CSVs only
  python scripts/build_housing_gap.py --rank 20       # rows at each end of the ranking
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statbank_common import latest_raw  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "forecast" / "housing"
FORECAST = ROOT / "data" / "processed" / "forecast.json"
OUT = ROOT / "data" / "processed" / "housing_gap.json"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

MID_OFFSET = 5          # the projection year the demand side stops at: 2026 + 5 = 2031
FULL_YEARS = 5          # completions are averaged over this many complete calendar years
PIPE_Q = 4              # quarters in the permitted-not-started context figure
BYGV33_QUARTERS = 28    # quarters to pull — 7 years, enough for FULL_YEARS + PIPE_Q

# BYGV33 BYGFASE codes (see data/raw/dst_BYGV33.meta.json)
PERMITS, STARTED, COMPLETED = "1", "2", "3"

# A reused pull may carry breakdown columns this build does not want. Rows are summed, so
# any column broken down below its total would double-count — keep only the total codes.
# HUSTYP is deliberately absent: FAM55N's household types are summed back to all households.
TOTALS = {"KØN": {"TOT"}, "ALDER": {"IALT"}, "CIVILSTAND": {"TOT"},
          "HUSSTØR": {"SUM", "TOT"}, "ANTBORNH": {"SUM", "TOT"},
          "ANVEND": {"SUM"}, "BYGHERRE": {"SUM"}}


def totals_only(r: dict) -> bool:
    return all(r[k] in v for k, v in TOTALS.items() if k in r)


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r)


def post_csv(body: dict) -> str:
    req = urllib.request.Request(f"{API}/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read().decode("utf-8-sig")


def tableinfo(table: str) -> pathlib.Path:
    """Cache one tableinfo beside our pulls — but only when it differs from the committed
    `data/raw/dst_<TABLE>.meta.json`. These three tables are already in the repo's own
    registry, so a byte-identical second copy would be committed for nothing; a copy
    appears here exactly when DST has revised the table since that one was taken."""
    info = json.dumps(get(f"{API}/tableinfo/{table}?lang=en&format=JSON"),
                      ensure_ascii=False, indent=1)
    shared = ROOT / "data" / "raw" / f"dst_{table}.meta.json"
    if shared.exists() and shared.read_text(encoding="utf-8") == info:
        return shared
    RAW.mkdir(parents=True, exist_ok=True)
    own = RAW / f"{table}.meta.json"
    own.write_text(info, encoding="utf-8")
    return own


def fetch(table: str, variables: dict, today: str, tag: str = "") -> pathlib.Path:
    """Pull one table into data/raw/forecast/housing/, tableinfo cached beside it."""
    tableinfo(table)
    RAW.mkdir(parents=True, exist_ok=True)
    body = {"table": table, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
            "valuePresentation": "Code",
            # a variable left out of `variables` is eliminated, i.e. summed to its total
            "variables": [{"code": k, "values": v} for k, v in variables.items()]}
    text = post_csv(body)
    if text.lstrip().startswith("{"):
        sys.exit(f"{table}: API returned an error instead of CSV:\n{text[:400]}")
    p = RAW / f"{table}{tag}_{today}.csv"
    p.write_text(text, encoding="utf-8")
    return p


def read(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(f, delimiter=";")]


def is_kommune(code: str) -> bool:
    """DST area codes: 000 is Denmark, 08x the regions, 01..11 the provinces."""
    return len(code) == 3 and code.isdigit() and 100 < int(code) < 900 and not code.startswith("08")


def periods(rs: list[dict]) -> set[str]:
    return {r["TID"] for r in rs}


def source(table: str, variables: dict, tag: str, covers, today: str, no_fetch: bool,
           reuse: bool = True) -> tuple[list[dict], pathlib.Path, str]:
    """Rows for one table, preferring cached pulls. `covers(rows)` decides whether a
    candidate file actually holds the periods and codes this build needs."""
    if reuse:
        shared = latest_raw("", table)
        if shared:
            rs = read(shared)
            if covers(rs):
                return rs, shared, "reused"
            print(f"  {shared.name} does not cover what the gap needs — pulling our own")
    own = sorted(RAW.glob(f"{table}{tag}_20*.csv"))
    if own:
        rs = read(own[-1])
        if covers(rs):
            return rs, own[-1], "cached"
    if no_fetch:
        sys.exit(f"no cached pull of {table} covering what the gap needs — run without --no-fetch")
    p = fetch(table, variables, today, tag)
    rs = read(p)
    if not covers(rs):
        sys.exit(f"{table}: the fresh pull does not cover what the gap needs — check the selection")
    return rs, p, "fetched"


def tid_codes(table: str) -> list[str]:
    return [x["id"] for v in get(f"{API}/tableinfo/{table}?lang=en&format=JSON")["variables"]
            if v["id"] == "Tid" for x in v["values"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="build from cached CSVs only")
    ap.add_argument("--rank", type=int, default=10, help="rows at each end of the printed ranking")
    args = ap.parse_args()
    today = dt.date.today().isoformat()

    if not FORECAST.exists():
        sys.exit(f"{FORECAST.relative_to(ROOT)} not found — run scripts/build_forecast.py first")
    doc = json.loads(FORECAST.read_text(encoding="utf-8"))
    kom_fc, fmeta = doc["kommuner"], doc["meta"]
    y_base = fmeta["first_year"]
    y_mid = str(int(y_base) + MID_OFFSET)
    if y_mid not in fmeta["years"]:
        sys.exit(f"the projection window stops at {fmeta['last_year']} — it must reach {y_mid}")
    print(f"→ demand from {fmeta['table']} {y_base}→{y_mid} · {len(kom_fc)} kommuner")

    # ---- households (FAM55N) sets the reference year; every other input follows it ----
    hh_year = None if args.no_fetch else tid_codes("FAM55N")[-1]

    def hh_ok(rs):
        nonlocal hh_year
        yrs = {r["TID"] for r in rs if r["TID"].isdigit() and totals_only(r)}
        if hh_year is None:                      # --no-fetch: take whatever the cache holds
            hh_year = max(yrs, default=None)
        return bool(hh_year) and hh_year in yrs

    fam, p_fam, how_fam = source(
        "FAM55N", {"OMRÅDE": ["*"], "Tid": [hh_year] if hh_year else ["*"]},
        "", hh_ok, today, args.no_fetch)
    print(f"  FAM55N {hh_year} · {how_fam} · {p_fam.name}")

    pop_period = f"{hh_year}K1"                  # 1 January of the household year
    folk, p_folk, how_folk = source(
        "FOLK1A", {"OMRÅDE": ["*"], "Tid": [pop_period]},
        "", lambda rs: any(r["TID"] == pop_period and totals_only(r) for r in rs),
        today, args.no_fetch)
    print(f"  FOLK1A {pop_period} · {how_folk} · {p_folk.name}")

    # BYGV33 needs phases 1 and 2 as well, which the repo's cached BYGFASE=3 pull lacks.
    byg, p_byg, how_byg = source(
        "BYGV33", {"OMRÅDE": ["*"], "BYGFASE": [PERMITS, STARTED, COMPLETED],
                   "Tid": [f"(-n+{BYGV33_QUARTERS})"]},
        "_phases", lambda rs: {PERMITS, STARTED, COMPLETED} <= {r["BYGFASE"] for r in rs},
        today, args.no_fetch, reuse=False)

    # ---- fold the inputs into per-kommune numbers ----
    households, population = {}, {}
    for r in fam:                                # household types summed → all households
        if is_kommune(r["OMRÅDE"]) and r["TID"] == hh_year and totals_only(r):
            households[r["OMRÅDE"]] = households.get(r["OMRÅDE"], 0) + int(r["INDHOLD"])
    for r in folk:
        if is_kommune(r["OMRÅDE"]) and r["TID"] == pop_period and totals_only(r):
            population[r["OMRÅDE"]] = population.get(r["OMRÅDE"], 0) + int(r["INDHOLD"])

    quarters = sorted(periods(byg))
    by_year = {}
    for q in quarters:
        by_year.setdefault(q[:4], []).append(q)
    full = sorted(y for y, qs in by_year.items() if len(qs) == 4)[-FULL_YEARS:]
    if len(full) < FULL_YEARS:
        sys.exit(f"BYGV33 has only {len(full)} complete years in the pull — widen BYGV33_QUARTERS")
    pipe_q = quarters[-PIPE_Q:]
    print(f"  BYGV33 {quarters[0]}–{quarters[-1]} · {how_byg} · {p_byg.name}\n"
          f"    completions averaged over {full[0]}–{full[-1]}; "
          f"pipeline over {pipe_q[0]}–{pipe_q[-1]}")

    done: dict[str, dict[str, int]] = {}         # code -> year -> dwellings completed
    permits: dict[str, int] = {}
    starts: dict[str, int] = {}
    for r in byg:
        code, q, n = r["OMRÅDE"], r["TID"], int(r["INDHOLD"])
        if not is_kommune(code) or not totals_only(r):
            continue
        if r["BYGFASE"] == COMPLETED and q[:4] in full:
            d = done.setdefault(code, {y: 0 for y in full})
            d[q[:4]] += n
        elif q in pipe_q and r["BYGFASE"] in (PERMITS, STARTED):
            tgt = permits if r["BYGFASE"] == PERMITS else starts
            tgt[code] = tgt.get(code, 0) + n

    # ---- compute ----
    out, missing = {}, []
    for code in sorted(kom_fc, key=int):
        pop, hh = population.get(code), households.get(code)
        if not pop or not hh or code not in done:
            missing.append(code)
            continue
        pph = pop / hh
        p0, p1 = kom_fc[code][y_base]["total"], kom_fc[code][y_mid]["total"]
        demand = (p1 - p0) / pph
        supply = sum(done[code][y] for y in full) / FULL_YEARS * FULL_YEARS
        gap = demand - supply
        out[code] = {
            "pop": pop, "households": hh, "persons_per_hh": round(pph, 4),
            "p_base": p0, "p_mid": p1,
            "demand_5y": round(demand, 1),
            "supply_5y": round(supply, 1),
            "completions_by_year": {y: done[code][y] for y in full},
            "gap": round(gap, 1),
            "gap_per_1000": round(gap / p0 * 1000, 2),
            "permits_4q": permits.get(code, 0),
            "starts_4q": starts.get(code, 0),
            "pipeline_permitted": permits.get(code, 0) - starts.get(code, 0),
        }
    if missing:
        sys.exit(f"{len(missing)} kommuner have no household, population or completion "
                 f"figure: {missing[:5]} — a pull is incomplete")

    # Denmark as a whole — the headline the per-kommune map cannot show, and the reason
    # every municipality lands on the same side of zero (see docs/FORECAST.md §7).
    dk_pop = sum(v["pop"] for v in out.values())
    dk_hh = sum(v["households"] for v in out.values())
    dk_p0 = sum(v["p_base"] for v in out.values())
    dk_demand = (sum(v["p_mid"] for v in out.values()) - dk_p0) / (dk_pop / dk_hh)
    dk_supply = sum(v["supply_5y"] for v in out.values())
    national = {"pop": dk_pop, "households": dk_hh,
                "persons_per_hh": round(dk_pop / dk_hh, 4),
                "p_base": dk_p0, "p_mid": sum(v["p_mid"] for v in out.values()),
                "demand_5y": round(dk_demand, 1), "supply_5y": round(dk_supply, 1),
                "gap": round(dk_demand - dk_supply, 1),
                "gap_per_1000": round((dk_demand - dk_supply) / dk_p0 * 1000, 2),
                "pipeline_permitted": sum(v["pipeline_permitted"] for v in out.values())}

    def updated(table: str, own: pathlib.Path) -> str | None:
        for p in (RAW / f"{table}.meta.json", ROOT / "data" / "raw" / f"dst_{table}.meta.json"):
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))["updated"][:10]
        return None

    meta = {
        "built": today,
        "fetched": max(p.stem[-10:] for p in (p_fam, p_folk, p_byg)),
        "kommuner": len(out),
        "national": national,
        "projection": {"table": fmeta["table"], "vintage": fmeta["vintage"],
                       "base_year": y_base, "mid_year": y_mid, "horizon_years": MID_OFFSET},
        "tables": {
            "FAM55N": {"what": "households, 1 January", "period": hh_year,
                       "updated": updated("FAM55N", p_fam), "pull": p_fam.name, "how": how_fam},
            "FOLK1A": {"what": "population, 1 January", "period": pop_period,
                       "updated": updated("FOLK1A", p_folk), "pull": p_folk.name, "how": how_folk},
            "BYGV33": {"what": "dwellings by phase of construction, quarterly, all uses and "
                               "all builder types",
                       "completions_years": full, "pipeline_quarters": pipe_q,
                       "updated": updated("BYGV33", p_byg), "pull": p_byg.name, "how": how_byg},
        },
        "formula": ("demand_5y = (P_mid − P_base) / persons_per_hh; "
                    f"supply_5y = mean yearly BYGV33 completions {full[0]}–{full[-1]} × {FULL_YEARS}; "
                    "gap = demand_5y − supply_5y; gap_per_1000 = gap / P_base × 1000"),
        "sign": "positive gap = the projection implies more dwellings than the recent building "
                "pace delivers (undersupply); negative = oversupply, including where the "
                "projection shrinks and any completions are surplus",
        "pipeline_note": f"pipeline_permitted = permits − starts over {pipe_q[0]}–{pipe_q[-1]}, "
                         "a four-quarter flow difference and not a stock; it is context only "
                         "and enters no other figure. BYGV33 is not adjusted for reporting "
                         "delays, so the most recent quarters are revised upward later.",
        "caveats": "constant household size; demolitions, vacancy, second homes and conversions "
                   "are not modelled; DST's projection is not housing-driven, so it does not "
                   "respond to the supply side it is compared with. See docs/FORECAST.md §7.",
        "licence": "free reuse with attribution",
        "source": "Danmarks Statistik FOLK1A, FAM55N, BYGV33 and "
                  f"{fmeta['table']} ({fmeta['vintage']} municipal population projection)",
        "url": "https://api.statbank.dk/v1/tableinfo/BYGV33",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "kommuner": out}, ensure_ascii=False,
                              separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(out)} kommuner")

    # ---- the ranking ----
    names = {}
    for p in (RAW / "BYGV33.meta.json", ROOT / "data" / "raw" / "dst_BYGV33.meta.json"):
        if p.exists():
            names = {x["id"]: x["text"] for v in json.loads(p.read_text())["variables"]
                     if v["id"] == "OMRÅDE" for x in v["values"]}
            break
    pos = sum(1 for v in out.values() if v["gap"] > 0)
    print(f"\nDenmark · demand {national['demand_5y']:,.0f} dwellings, "
          f"supply {national['supply_5y']:,.0f} → gap {national['gap']:+,.0f} "
          f"({national['gap_per_1000']:+.2f} per 1 000) · {pos} of {len(out)} kommuner "
          f"undersupplied".replace(",", " "))
    rank = sorted((v["gap_per_1000"], c) for c, v in out.items())
    hdr = (f"\ngap per 1 000 inhabitants · {y_base}→{y_mid} · positive = undersupply "
           f"· {len(rank)} kommuner\n"
           f"  {'':3} {'':22} {'gap/1k':>7} {'gap':>8} {'demand':>8} {'supply':>8} "
           f"{'p/hh':>5} {'pipe':>7}")

    def show(rows, title):
        print(hdr if title.startswith("Highest") else "")
        print(title)
        for i, (v, c) in enumerate(rows, 1):
            r = out[c]
            print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {v:>7.2f} {r['gap']:>8,.0f} "
                  f"{r['demand_5y']:>8,.0f} {r['supply_5y']:>8,.0f} {r['persons_per_hh']:>5.2f} "
                  f"{r['pipeline_permitted']:>+7,}".replace(",", " "))
    show(rank[::-1][:args.rank], f"Highest {args.rank} — building least for the projected growth")
    show(rank[:args.rank], f"Lowest {args.rank} — building most relative to it")


if __name__ == "__main__":
    main()
