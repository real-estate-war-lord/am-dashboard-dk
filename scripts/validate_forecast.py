#!/usr/bin/env python3
"""Check the v2.4 Outlook data files against their own sources. Runnable on its own.

  data/processed/forecast.json        DST municipal projection            [map]
  data/processed/net_dwellings.json   BOL101 net additions per year       [map]
  data/processed/housing_gap.json     demand-vs-supply comparison         [research only]

**The hard-data rule.** Every indicator the map shows must be an official published figure
or plain arithmetic on official figures — a difference, a share, a per-1,000, a sum.
Nothing shown in the UI may contain an assumption, a trend, a cap or a model of our own.
Check 0 audits the registry against that rule; it is why `housing_gap.json`, which needs a
household-size trend, is validated here but is no longer a registry entry. See
docs/FORECAST.md §0.

Checks, in order:
  0. registry audit  — every entry in config/indicators.json's `forecast` key against the
                       source tables and the exact arithmetic recorded below, and against
                       the keys indicators() actually produces  [FAILS on any mismatch]
  1. coverage        — every kommune × every year present, nothing missing or null
  2. reconciliation  — Σ kommuner vs the national projection (FRDK) per year   [FAILS > 0.1 %]
  3. base year       — the projection's first year vs the latest actual FOLK1A, per kommune,
                       five largest deviations                                 [information only]
  4. smoke test      — København and Aarhus against the figures in docs/FORECAST_SOURCES.md §1.4
  5. 20–34 baseline  — the Denmark figure fc_20_34_rel is measured against, checked against
                       FRDK's own age detail, the two identities that define the pair
                       fc_20_34_rel / fc_20_34_abs, and fc_pop_rate_5y recomputed from the
                       two projection cells it is made of                      [FAILS]
  6. net dwellings   — 98 kommuner with every component present, and hist_net_dwell
                       recomputed for five kommuner straight from the raw BOL101 and
                       FOLK1A cells                                            [FAILS]
  7. housing gap     — research only. 98 kommuner with every component present and non-null,
                       and the two identities that define gap_per_1000_rel     [FAILS]
  8. gap by hand     — research only. gap_per_1000 recomputed for five kommuner straight
                       from the raw FOLK1A / FAM55N / BOL101 cells, household-size trend,
                       cap and all — a second implementation of the formula    [FAILS]
  9. Copenhagen      — the KK kvarter forecast: coverage, the three additivity identities,
                       KKFR vs the latest KKBEF1 actual and KK vs DST          [FAILS on 1-3]

Checks 6, 7/8 and 9 are skipped, not failed, when their file has not been built.
Exit status is non-zero if a check marked FAIL does not pass.

Usage
  python scripts/validate_forecast.py
  python scripts/validate_forecast.py --tolerance 0.05
  python scripts/validate_forecast.py --top 10        # longer 20–34 rankings
  python scripts/validate_forecast.py --audit         # check 0 on its own
"""
import argparse
import csv
import io
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from build_forecast import indicators, national_pct  # noqa: E402
from statbank_common import latest_raw, period_key  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "indicators.json"
SRC = ROOT / "data" / "processed" / "forecast.json"
NET = ROOT / "data" / "processed" / "net_dwellings.json"
GAP = ROOT / "data" / "processed" / "housing_gap.json"
CPH = ROOT / "data" / "processed" / "cph_forecast.json"
HOUSING_RAW = ROOT / "data" / "raw" / "forecast" / "housing"
FORECAST_RAW = ROOT / "data" / "raw" / "forecast" / "dst"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

# docs/FORECAST_SOURCES.md §1.4 — the Phase 1 smoke test, pulled straight from the API.
EXPECTED = {"101": {"2026": 671714, "2031": 689101, "2040": 711011},
            "751": {"2026": 378361, "2031": 399885, "2040": 431031}}
NAMES = {"101": "København", "751": "Aarhus", "153": "Brøndby", "665": "Lemvig",
         "147": "Frederiksberg"}
# checks 6 and 8 — a spread of sizes and directions: two big cities, a suburb that grows,
# a shrinking rural kommune, and the densest kommune in the country
BY_HAND = ["101", "751", "153", "665", "147"]
FIELDS = ("total", "a0_5", "a6_16", "a17_19", "a20_34", "a35_64", "a65_79", "a80p")

# ---- check 0: the hard-data audit -------------------------------------------------
# One row per entry in config/indicators.json's `forecast` key. `arith` is the exact
# arithmetic, written out; `assumption` is what the entry assumes beyond the published
# cells it reads. Under the hard-data rule every `assumption` must be None. Adding an
# indicator to the registry without adding it here fails the check, which is the point:
# the audit cannot fall silently out of date.
#
# P = forecast.json `total`, a<group> = that age group's count, y0/y5/y1 = the first,
# mid (y0+5) and last year of the window.
AUDIT = {
 "fc_growth":      ("FRKM1xx", "(P_y1 − P_y0) / P_y0 × 100", None),
 "fc_growth_5y":   ("FRKM1xx", "(P_y5 − P_y0) / P_y0 × 100", None),
 "fc_pop_rate_5y": ("FRKM1xx", "(P_y5 − P_y0) / 5 / P_y0 × 1000", None),
 "fc_abs":         ("FRKM1xx", "P_y1 − P_y0", None),
 "fc_0_5":         ("FRKM1xx", "(a0_5_y1 − a0_5_y0) / a0_5_y0 × 100", None),
 "fc_6_16":        ("FRKM1xx", "(a6_16_y1 − a6_16_y0) / a6_16_y0 × 100", None),
 "fc_20_34":       ("FRKM1xx", "(a20_34_y1 − a20_34_y0) / a20_34_y0 × 100", None),
 "fc_20_34_rel":   ("FRKM1xx", "fc_20_34 − the same expression on Σ of the 98 kommuner", None),
 "fc_20_34_abs":   ("FRKM1xx", "a20_34_y1 − a20_34_y0", None),
 "fc_80p":         ("FRKM1xx", "(a80p_y1 − a80p_y0) / a80p_y0 × 100", None),
 "hist_net_dwell": ("BOL101 + FOLK1A",
                    "(stock_end − stock_start) / span_years / population × 1000", None),
}
# indicators() returns these and only these; hist_net_dwell comes from the other build.
FROM_FORECAST_JSON = {k for k in AUDIT if k.startswith("fc_")}
FROM_NET_DWELLINGS = {"hist_net_dwell"}

# ---- check 9: how far the Copenhagen levels may miss the city total ----------------
# KK rounds every published cell independently, so a sum of N of them drifts from the
# published total by a few persons and the drift grows with N. Measured on the 2026
# vintage: Σ 68 kvarterer is within 5 of the city in the worst year (2038), Σ 11 bydele
# within 2, and Σ kvarterer of one bydel within 2. The tolerances are set just above
# those, not at them, so ordinary rounding does not fail the check — and far below the
# smallest kvarter (Metropolzonen, 2 882 people in 2026), so a dropped or misparented
# area still cannot hide inside the slack. Raise these only with a note saying why.
TOL_CITY = 10       # Σ all kvarterer (68 cells) vs the published city total
TOL_BYDEL = 5       # Σ the kvarterer of one bydel (≤10 cells) vs that bydel's own value


def folk1a_latest() -> tuple[str, dict[str, int]]:
    """Actual population per municipality at the newest FOLK1A quarter."""
    info = json.load(urllib.request.urlopen(
        urllib.request.Request(f"{API}/tableinfo/FOLK1A?lang=en&format=JSON", headers=UA), timeout=120))
    period = [v for v in info["variables"] if v["id"] == "Tid"][-1]["values"][-1]["id"]
    body = {"table": "FOLK1A", "format": "CSV", "delimiter": "Semicolon", "lang": "en",
            "valuePresentation": "Code",
            "variables": [{"code": "OMRÅDE", "values": ["*"]}, {"code": "Tid", "values": [period]}]}
    req = urllib.request.Request(f"{API}/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    text = urllib.request.urlopen(req, timeout=300).read().decode("utf-8-sig")
    out = {}
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        code = r["OMRÅDE"]
        # OMRÅDE also carries All Denmark (000), regions (08x) and provinces — keep municipalities
        if code.isdigit() and 100 < int(code) < 900 and not code.startswith("08"):
            out[code] = int(r["INDHOLD"])
    return period, out


def read_csv(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(f, delimiter=";")]


def raw_path(name: str) -> pathlib.Path | None:
    """Find a pull by the filename housing_gap.json's meta recorded."""
    for p in (HOUSING_RAW / name, ROOT / "data" / "raw" / name):
        if p.exists():
            return p
    return None


def in_20_34(code: str) -> bool:
    """ALDER codes are single years plus a '105-' top bucket; 'TOT' is the total."""
    return code != "TOT" and 20 <= int(code.rstrip("-")) <= 34


def frdk_20_34(table: str, y0: str, y1: str) -> tuple[float, str]:
    """Denmark's own 20–34 change y0→y1, %, from FRDK's published age detail.

    Prefers a cached age-detailed pull (the research snapshot in data/raw/forecast/dst),
    otherwise asks the API for the two years — 106 ages × 2 years, a trivial request.
    """
    cached = sorted(FORECAST_RAW.glob(f"{table}*age*.csv"))
    if cached:
        rs, origin = read_csv(cached[-1]), cached[-1].name
    else:
        body = {"table": table, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                "valuePresentation": "Code",
                "variables": [{"code": "ALDER", "values": ["*"]},
                              {"code": "Tid", "values": [y0, y1]}]}
        req = urllib.request.Request(f"{API}/data", data=json.dumps(body).encode("utf-8"),
                                     headers=UA, method="POST")
        text = urllib.request.urlopen(req, timeout=300).read().decode("utf-8-sig")
        rs, origin = list(csv.DictReader(io.StringIO(text), delimiter=";")), f"{table} via API"
    tot = {y0: 0, y1: 0}
    for r in rs:
        if r["TID"] in tot and in_20_34(r["ALDER"]):
            tot[r["TID"]] += int(r["INDHOLD"])
    if not tot[y0]:
        raise ValueError(f"no 20–34 cells for {y0} in {origin}")
    return (tot[y1] - tot[y0]) / tot[y0] * 100, origin


def audit(doc: dict) -> list[str]:
    """Check 0 — every map indicator against the hard-data rule (docs/FORECAST.md §0).

    Three ways this fails, all of them the same failure: an indicator reaching the UI
    without anyone having written down what it is made of.
      · an entry in the registry that AUDIT does not describe, or the reverse
      · an entry whose AUDIT row records an assumption
      · a key the registry expects from indicators() that indicators() does not return
    """
    fails = []
    reg = json.loads(CFG.read_text(encoding="utf-8")).get("forecast", {}).get("indicators", [])
    keys = [i["key"] for i in reg]
    print(f"0. registry audit — config/indicators.json `forecast` key, "
          f"{len(keys)} indicators, hard-data rule\n")
    w = max((len(k) for k in set(keys) | set(AUDIT)), default=14)
    for k in keys:
        row = AUDIT.get(k)
        if row is None:
            print(f"   ✗ {k:<{w}}  not in the audit table — add it to AUDIT in this script")
            fails.append("registry audit")
            continue
        table, arith, assumption = row
        ind = next(i for i in reg if i["key"] == k)
        flag = "✗" if assumption else "✓"
        print(f"   {flag} {k:<{w}}  {table:<17}  {arith}")
        print(f"     {'':<{w}}  {ind['unit']} · group {ind['group']} · calc {ind['calc']}"
              + (f"  ⚠ ASSUMPTION: {assumption}" if assumption else ""))
        if assumption:
            fails.append("registry audit")
    stale = sorted(set(AUDIT) - set(keys))
    if stale:
        print(f"   ✗ audited but no longer in the registry: {', '.join(stale)}")
        fails.append("registry audit")
    produced = set(next(iter(indicators(doc).values()), {}))
    want = {k for k in keys if k in FROM_FORECAST_JSON}
    if want - produced:
        print(f"   ✗ indicators() does not return {', '.join(sorted(want - produced))}")
        fails.append("registry audit")
    orphan = sorted(k for k in keys if k not in FROM_FORECAST_JSON | FROM_NET_DWELLINGS)
    if orphan:
        print(f"   ✗ no build produces {', '.join(orphan)}")
        fails.append("registry audit")
    if not fails:
        print(f"\n   ✓ {len(keys)} of {len(keys)} indicators are published figures or plain "
              f"arithmetic on them — 0 assumptions")
    return fails


def kkbef1_latest() -> tuple[str, dict[str, int]]:
    """Observed population per OMRKK district at the newest KKBEF1 period.

    93 districts × 1 period with every other variable eliminated — a trivial request, so it
    is pulled live rather than depending on a cached selection. Falls back to the repo's own
    `KKBEF1_pop` pull when one is on disk, which makes the check work offline.
    """
    cached = latest_raw("s30", "KKBEF1", "KKBEF1_pop")
    if cached:
        rs = read_csv(cached)
        period = max((r["TID"] for r in rs), key=period_key)
        return period, {r["OMRKK"]: int(r["INDHOLD"]) for r in rs if r["TID"] == period}
    info = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{API}/s30/tableinfo/KKBEF1?lang=en&format=JSON", headers=UA), timeout=120))
    period = [v for v in info["variables"] if v["id"] == "Tid"][-1]["values"][-1]["id"]
    body = {"table": "KKBEF1", "format": "CSV", "delimiter": "Semicolon", "lang": "en",
            "valuePresentation": "Code",
            "variables": [{"code": "OMRKK", "values": ["*"]}, {"code": "Tid", "values": [period]}]}
    req = urllib.request.Request(f"{API}/s30/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    text = urllib.request.urlopen(req, timeout=300).read().decode("utf-8-sig")
    return period, {r["OMRKK"]: int(r["INDHOLD"])
                    for r in csv.DictReader(io.StringIO(text), delimiter=";")}


def copenhagen(kom: dict, years: list[str], dst_table: str, top: int) -> list[str]:
    """Check 9 — the Copenhagen kvarter forecast (KK KKFR).

    Four parts. The first three are identities that must hold inside KK's own run and are
    hard failures; the last two are cross-source comparisons that are *information*, because
    a difference there is a real difference between two published runs, not a bug:

      a. coverage        67 kvarterer × every year, nothing missing
      b. additivity      Σ kvarterer (with the unallocated bucket) = the city total, ±2
      c. additivity      Σ kvarterer of each bydel = that bydel's own value, ±2 — which also
                         proves the kvarter → lokaludvalg → bydel mapping, since a wrong
                         parent would move people between bydele
      d. base year       KKFR's first year vs the newest observed KKBEF1, per kvarter
      e. 🚫 KK vs DST    the city total against DST's kommune 101, per year — the splicing
                         rule (docs/FORECAST.md §4) made numeric
    """
    if not CPH.exists():
        print(f"\n9. Copenhagen kvarter forecast — {CPH.relative_to(ROOT)} not built, "
              f"skipped (run scripts/build_cph_forecast.py)")
        return []
    fails = []
    c = json.loads(CPH.read_text(encoding="utf-8"))
    cmeta, area, names = c["meta"], c["omrkk"], c["short_names"]
    cy, city = cmeta["years"], cmeta["relative_baseline"]
    unalloc = cmeta["unallocated"]
    kvart = cmeta["levels"]["kvarter"]
    bydele = cmeta["levels"]["bydel"]
    drawn = [k for k in kvart if k != unalloc["kvarter"]]
    print(f"\n9. Copenhagen kvarter forecast — {cmeta['db']}/{cmeta['table']} vintage "
          f"{cmeta['vintage']} (updated {cmeta['updated']}) · {cy[0]}–{cy[-1]}")

    # ---- a. coverage ----
    holes = [(k, y) for k in kvart for y in cy
             if any(area.get(k, {}).get(y, {}).get(f) is None for f in FIELDS)]
    ok = len(drawn) == 67 and len(cy) == 15 and not holes
    print(f"   {'✓' if ok else '✗'} {len(drawn)} kvarterer (+{len(kvart) - len(drawn)} "
          f"unallocated) × {len(cy)} years, {len(holes)} missing")
    if not ok:
        print(f"     expected 67 × 15; {holes[:3]}")
        fails.append("cph coverage")

    # ---- b & c. the levels have to re-sum ----
    def worst_gap(codes, want):
        return max(((abs(sum(area[k][y]["total"] for k in codes) - want(y)), y) for y in cy),
                   default=(0, cy[0]))

    gap, gy = worst_gap(kvart, lambda y: area[city][y]["total"])
    ok = gap <= TOL_CITY
    print(f"   {'✓' if ok else '✗'} Σ kvarterer (incl. the unallocated bucket) = the city "
          f"total — worst {gap} persons ({gy}), tolerance ±{TOL_CITY}")
    if not ok:
        fails.append("cph additivity")
    gap, gy = worst_gap(cmeta["levels"]["lokaludvalg"], lambda y: area[city][y]["total"])
    ok = gap <= TOL_CITY
    print(f"   {'✓' if ok else '✗'} Σ lokaludvalg = the city total — worst {gap} persons "
          f"({gy}), tolerance ±{TOL_CITY}")
    if not ok:
        fails.append("cph additivity")
    bad_bydel, worst_b = [], 0
    for b in bydele:
        kids = [k for k in kvart if cmeta["hierarchy"].get(k, {}).get("bydel") == b]
        gap = max((abs(sum(area[k][y]["total"] for k in kids) - area[b][y]["total"])
                   for y in cy), default=10 ** 9)
        worst_b = max(worst_b, gap if kids else 0)
        if gap > TOL_BYDEL or not kids:
            bad_bydel.append((b, names.get(b, ""), gap, len(kids)))
    print(f"   {'✓' if not bad_bydel else '✗'} Σ kvarterer of each bydel = that bydel, "
          f"{len(bydele) - len(bad_bydel)}/{len(bydele)} within ±{TOL_BYDEL} (worst "
          f"{worst_b}) — this is also what proves the kvarter → lokaludvalg → bydel mapping")
    if bad_bydel:
        for b, nm, w, n_ in bad_bydel:
            print(f"     ✗ {b} {nm}: off by {w:,} over {n_} kvarterer".replace(",", " "))
        fails.append("cph additivity")

    # ---- d. the base year against the observed population ----
    print(f"   base year {cy[0]} vs the newest observed KKBEF1 — {top if top < 6 else 5} "
          f"largest deviations (information only)")
    try:
        period, actual = kkbef1_latest()
    except Exception as e:  # noqa: BLE001
        print(f"     ⚠ could not read KKBEF1: {e}")
    else:
        rows_ = [(abs((area[k][cy[0]]["total"] - actual[k]) / actual[k] * 100), k)
                 for k in drawn if actual.get(k)]
        print(f"     observed period {period}; KKFR's base is 1 January {cy[0]}, so part of "
              f"each gap is real change since then")
        for _, k in sorted(rows_, reverse=True)[:5]:
            p_, a_ = area[k][cy[0]]["total"], actual[k]
            print(f"     {k} {names.get(k, ''):<34} forecast {p_:>7,}  observed {a_:>7,}  "
                  f"{p_ - a_:+6,}  {(p_ - a_) / a_ * 100:+.2f} %".replace(",", " "))
        print(f"     ({len(rows_)} of {len(drawn)} kvarterer matched in KKBEF1)")

    # ---- e. the splicing rule, made numeric ----
    print(f"   🚫 KK city total vs DST {dst_table} kommune 101 — never splice these "
          f"(information only)")
    overlap = [y for y in cy if y in years]
    for y in (overlap[0], overlap[len(overlap) // 3], overlap[-1]):
        kk, dst = area[city][y]["total"], kom["101"][y]["total"]
        print(f"     {y}  KK {kk:>9,}  DST {dst:>9,}  {kk - dst:+7,}  "
              f"{(kk - dst) / dst * 100:+.2f} %".replace(",", " "))
    widest = max(overlap, key=lambda y: abs(area[city][y]["total"] - kom["101"][y]["total"]))
    kk, dst = area[city][widest]["total"], kom["101"][widest]["total"]
    print(f"     widest {widest}: {kk - dst:+,} ({(kk - dst) / dst * 100:+.2f} %) over "
          f"{len(overlap)} shared years".replace(",", " "))
    return fails


def net_dwellings(kom: dict, base_year: str) -> list[str]:
    """Check 6 — net_dwellings.json, and hist_net_dwell recomputed from the raw cells.

    The second computation reads the BOL101 and FOLK1A CSVs the build recorded and does the
    four operations by hand, so a bug in the build's folding or in its area filter shows up
    as a mismatch rather than as two copies of the same wrong number.
    """
    if not NET.exists():
        print(f"\n6. net dwellings — {NET.relative_to(ROOT)} not built, skipped "
              f"(run scripts/build_net_dwellings.py)")
        return []
    fails = []
    n = json.loads(NET.read_text(encoding="utf-8"))
    nmeta, nk = n["meta"], n["kommuner"]
    parts = ("stock_start", "stock_end", "span_years", "net_total", "net_per_year",
             "pop", "hist_net_dwell")
    holes = [(c, f) for c in nk for f in parts if nk[c].get(f) is None]
    absent = sorted(set(kom) - set(nk))
    start, base = nmeta["window"]
    span, period = nmeta["span_years"], nmeta["pop_period"]
    print(f"\n6. net dwellings — {len(nk)} kommuner × {len(parts)} components, "
          f"{len(holes)} null, {len(absent)} kommuner absent")
    if len(nk) != 98 or holes or absent:
        print(f"   ✗ FAIL {holes[:3]} {absent[:3]}")
        fails.append("net dwellings")
    else:
        dk = nmeta["national"]
        print(f"   ✓ complete; BOL101 stock {start} → {base} ({span} years"
              + (f", DST publishes no {', '.join(nmeta['tables']['BOL101']['closed_years'])}"
                 if nmeta["tables"]["BOL101"].get("closed_years") else "")
              + f"), population {period}")
        print(f"   Denmark: {dk['stock_start']:,} → {dk['stock_end']:,} dwellings, "
              f"{dk['net_per_year']:+,.0f}/yr over {dk['pop']:,} inhabitants = "
              f"{dk['hist_net_dwell']:+.2f} per 1 000".replace(",", " "))

    # Σ kommuner = Denmark, the same identity the Outlook layer asserts
    sums = {f: sum(nk[c][f] for c in nk) for f in ("stock_start", "stock_end", "pop")}
    bad_sum = [f for f in sums if sums[f] != nmeta["national"][f]]
    print(f"   {'✓' if not bad_sum else '✗'} Σ kommuner = Denmark for "
          f"{', '.join(sorted(set(sums) - set(bad_sum)))}")
    if bad_sum:
        fails.append("net dwellings")

    print(f"   hist_net_dwell recomputed from the raw cells, {len(BY_HAND)} kommuner")
    pulls = {t: raw_path(nmeta["tables"][t]["pull"]) for t in ("BOL101", "FOLK1A")}
    if any(v is None for v in pulls.values()):
        gone = [t for t, v in pulls.items() if v is None]
        print(f"   ⚠ raw pulls for {', '.join(gone)} are not on disk (gitignored) — "
              f"rerun scripts/build_net_dwellings.py to restore them")
        return fails
    raw = {k: read_csv(pulls[k]) for k in pulls}

    def cells(table, code, period_, **eq):
        return sum(int(r["INDHOLD"]) for r in raw[table]
                   if r["OMRÅDE"] == code and r["TID"] == period_
                   and all(r.get(k) == v for k, v in eq.items()))

    for c in BY_HAND:
        a, b = cells("BOL101", c, start), cells("BOL101", c, base)
        pop = cells("FOLK1A", c, period)
        per1000 = (b - a) / span / pop * 1000
        stored = nk[c]["hist_net_dwell"]
        ok = abs(per1000 - stored) < 0.01
        if not ok:
            fails.append("net dwellings by hand")
        print(f"   {'✓' if ok else '✗'} {c} {NAMES.get(c, ''):<13} "
              f"({b:,} − {a:,}) / {span} = {(b - a) / span:>+8,.0f} dwellings/yr   "
              f"/ {pop:,} × 1000 = {per1000:+.2f}   stored {stored:+.2f}".replace(",", " "))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=0.1, help="max Σ-vs-national deviation, %%")
    ap.add_argument("--top", type=int, default=10, help="rows at each end of the 20–34 rankings")
    ap.add_argument("--audit", action="store_true", help="run check 0 on its own and stop")
    args = ap.parse_args()
    if not SRC.exists():
        sys.exit(f"{SRC.relative_to(ROOT)} not found — run scripts/build_forecast.py first")
    d = json.loads(SRC.read_text())
    meta, kom, nat = d["meta"], d["kommuner"], d["national"]
    years = meta["years"]
    fails = []

    print(f"forecast.json · {meta['table']} vintage {meta['vintage']} "
          f"(updated {meta['updated']}, fetched {meta['fetched']}) · {years[0]}–{years[-1]}\n")

    # ---- 0. the hard-data audit ----
    fails += audit(d)
    if args.audit:
        print()
        if fails:
            print(f"FAILED: {', '.join(sorted(set(fails)))}")
            sys.exit(1)
        print("audit passed")
        return
    print()

    # ---- 1. coverage ----
    missing_years = [(c, y) for c in kom for y in years if y not in kom[c]]
    missing_field = [(c, y, f) for c in kom for y in kom[c] for f in FIELDS
                     if kom[c].get(y, {}).get(f) is None]
    extra = [c for c in kom if c in meta["excluded"]]
    n_missing = len(missing_years) + len(missing_field) + len(extra)
    print(f"1. coverage — {len(kom)} kommuner × {len(years)} years, {n_missing} missing")
    if len(kom) != 98:
        print(f"   ✗ expected 98 kommuner, got {len(kom)}"); fails.append("coverage")
    if n_missing:
        print(f"   ✗ {missing_years[:3]} {missing_field[:3]} {extra[:3]}"); fails.append("coverage")
    else:
        print(f"   ✓ complete; Christiansø ({', '.join(meta['excluded'])}) excluded as intended")

    # ---- 2. reconciliation against the national projection ----
    print(f"\n2. Σ kommuner vs {meta['national_table']} — per year")
    worst_y, worst_d = None, 0.0
    for y in years:
        s, n = sum(kom[c][y]["total"] for c in kom), nat[y]
        dev = (s - n) / n * 100
        if abs(dev) > abs(worst_d):
            worst_y, worst_d = y, dev
    for y in (years[0], worst_y, years[-1]):
        s, n = sum(kom[c][y]["total"] for c in kom), nat[y]
        mark = "  ← max" if y == worst_y else ""
        print(f"   {y}  Σ {s:>10,}  national {n:>10,}  {(s - n):+6,}  {(s - n) / n * 100:+.4f} %{mark}"
              .replace(",", " "))
    if abs(worst_d) > args.tolerance:
        print(f"   ✗ FAIL max deviation {worst_d:+.4f} % exceeds ±{args.tolerance} %"); fails.append("reconciliation")
    else:
        print(f"   ✓ max deviation {worst_d:+.4f} % (tolerance ±{args.tolerance} %) — cell rounding, same run")

    # ---- 3. base year vs the latest actual ----
    print(f"\n3. {years[0]} projection vs latest actual FOLK1A — 5 largest deviations "
          f"(information only)")
    try:
        period, actual = folk1a_latest()
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠ could not reach the StatBank API: {e}")
    else:
        rows = [(abs((kom[c][years[0]]["total"] - actual[c]) / actual[c] * 100), c) for c in kom if c in actual]
        print(f"   actual period {period}; the projection's base is 1 January {years[0]}, so part of "
              f"each gap is real change since then")
        for _, c in sorted(rows, reverse=True)[:5]:
            p, a = kom[c][years[0]]["total"], actual[c]
            print(f"   {c}  {NAMES.get(c, ''):10s} projected {p:>9,}  actual {a:>9,}  "
                  f"{p - a:+7,}  {(p - a) / a * 100:+.2f} %".replace(",", " "))
        covered = len(rows)
        print(f"   ({covered} of {len(kom)} kommuner matched in FOLK1A)")

    # ---- 4. smoke test ----
    print("\n4. smoke test vs docs/FORECAST_SOURCES.md §1.4")
    for c, want in EXPECTED.items():
        got = {y: kom.get(c, {}).get(y, {}).get("total") for y in want}
        ok = got == want
        print(f"   {'✓' if ok else '✗'} {c} {NAMES[c]:10s} " +
              "  ".join(f"{y}: {got[y]:,}".replace(",", " ") for y in want))
        if not ok:
            print(f"     expected {want}, got {got}"); fails.append("smoke")

    # ---- 5. the 20–34 relative baseline ----
    y0, y1 = years[0], years[-1]
    vals = indicators(d)
    nat = national_pct(kom, "a20_34", y0, y1)
    nat_abs = sum(kom[c][y1]["a20_34"] - kom[c][y0]["a20_34"] for c in kom)
    print(f"\n5. 20–34 baseline — Denmark {y0}→{y1}: {nat:+.4f} % ({nat_abs:+,} persons), "
          f"Σ of {len(kom)} kommuner".replace(",", " "))
    try:
        pub, origin = frdk_20_34(meta["national_table"], y0, y1)
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠ could not read {meta['national_table']} age detail: {e}")
    else:
        diff = nat - pub
        ok = abs(diff) <= 0.01
        print(f"   {'✓' if ok else '✗'} {meta['national_table']} published age detail "
              f"{pub:+.4f} % ({origin}) — {diff:+.4f} pp apart")
        if not ok:
            print("     ✗ FAIL the kommune sum and the national table disagree on 20–34")
            fails.append("20-34 baseline")
    # the two identities the pair is defined by
    bad_rel = [c for c in kom if vals[c]["fc_20_34_rel"] is not None
               and abs(vals[c]["fc_20_34_rel"] - (vals[c]["fc_20_34"] - nat)) > 0.011]
    sum_abs = sum(vals[c]["fc_20_34_abs"] for c in kom)
    print(f"   {'✓' if not bad_rel else '✗'} fc_20_34_rel = fc_20_34 − Denmark for "
          f"{len(kom) - len(bad_rel)}/{len(kom)} kommuner")
    print(f"   {'✓' if sum_abs == nat_abs else '✗'} Σ fc_20_34_abs = {sum_abs:+,} = "
          f"Denmark's own change".replace(",", " "))
    if bad_rel or sum_abs != nat_abs:
        fails.append("20-34 baseline")

    # fc_pop_rate_5y recomputed from the two projection cells, here rather than by calling
    # indicators() again — the whole value of the check is that it is a second expression.
    y5 = str(int(y0) + 5)
    bad_rate = [c for c in kom
                if abs(vals[c]["fc_pop_rate_5y"]
                       - (kom[c][y5]["total"] - kom[c][y0]["total"]) / 5
                       / kom[c][y0]["total"] * 1000) > 0.011]
    dk_rate = (sum(kom[c][y5]["total"] for c in kom) - sum(kom[c][y0]["total"] for c in kom)) \
        / 5 / sum(kom[c][y0]["total"] for c in kom) * 1000
    print(f"   {'✓' if not bad_rate else '✗'} fc_pop_rate_5y = (P{y5} − P{y0}) / 5 / P{y0} "
          f"× 1000 for {len(kom) - len(bad_rate)}/{len(kom)} kommuner "
          f"(Denmark {dk_rate:+.2f} persons / 1 000 / yr)")
    if bad_rate:
        fails.append("20-34 baseline")
    info = FORECAST_RAW / f"{meta['table']}.meta.json"
    names = {x["id"]: x["text"] for v in json.loads(info.read_text())["variables"]
             if v["id"] == "KOMMUNEDK" for x in v["values"]} if info.exists() else {}

    def rank(key, unit, hi, lo):
        r = sorted((vals[c][key], c) for c in kom if vals[c][key] is not None)
        for title, part in ((hi, r[::-1][:args.top]), (lo, r[:args.top])):
            print(f"   {title}")
            for i, (v, c) in enumerate(part, 1):
                a, b = kom[c][y0]["a20_34"], kom[c][y1]["a20_34"]
                fmt = f"{v:+,.0f}" if unit == "persons" else f"{v:+.1f} {unit}"
                print(f"     {i:>2}. {c:>3} {names.get(c, ''):<22} {fmt:>10}   "
                      f"20–34 {a:>8,} → {b:>8,}".replace(",", " "))
    print(f"\n   fc_20_34_rel — percentage points against Denmark's {nat:+.2f} %")
    rank("fc_20_34_rel", "pp", f"top {args.top}", f"bottom {args.top}")
    print("\n   fc_20_34_abs — persons")
    rank("fc_20_34_abs", "persons", f"largest gains {args.top}", f"largest losses {args.top}")

    # ---- 6. net dwelling additions ----
    fails += net_dwellings(kom, years[0])

    # ---- 7 & 8. the housing gap — research only, not a map indicator ----
    if not GAP.exists():
        print(f"\n7/8. housing gap — {GAP.relative_to(ROOT)} not built, skipped "
              f"(run scripts/build_housing_gap.py)")
    else:
        g = json.loads(GAP.read_text())
        gmeta, gk = g["meta"], g["kommuner"]
        parts = ("pop", "households", "persons_per_hh", "persons_per_hh_mid",
                 "pph_change_per_year", "p_base", "p_mid", "households_base",
                 "households_mid", "demand_5y", "demand_5y_const", "stock_prev",
                 "stock_base", "supply_5y", "supply_5y_gross", "gap", "gap_per_1000",
                 "gap_per_1000_rel", "gap_const_gross", "pipeline_permitted")
        holes = [(c, f) for c in gk for f in parts if gk[c].get(f) is None]
        absent = sorted(set(kom) - set(gk))
        print(f"\n7. housing gap — research only, not shown on the map "
              f"(docs/FORECAST.md §7)\n   {len(gk)} kommuner × {len(parts)} components, "
              f"{len(holes)} null, {len(absent)} kommuner absent")
        if len(gk) != 98 or holes or absent:
            print(f"   ✗ FAIL {holes[:3]} {absent[:3]}"); fails.append("housing gap coverage")
        else:
            t = gmeta["tables"]
            print(f"   ✓ complete; households {t['FAM55N']['trend_years'][0]}–"
                  f"{t['FAM55N']['period']}, population {t['FOLK1A']['trend_periods'][0]}–"
                  f"{t['FOLK1A']['period']}, dwelling stock "
                  f"{t['BOL101']['stock_years'][0]}–{t['BOL101']['stock_years'][1]} "
                  f"({t['BOL101']['span_years']} years)")
            n = gmeta["national"]
            print(f"   Denmark: demand {n['demand_5y']:,.0f} (constant size "
                  f"{n['demand_5y_const']:,.0f})  supply {n['supply_5y']:,.0f} (gross "
                  f"{n['supply_5y_gross']:,.0f})  gap {n['gap']:+,.0f}  "
                  f"{n['gap_per_1000']:+.2f} per 1 000".replace(",", " "))

        # gap_per_1000_rel is only meaningful if Denmark is the Σ of the same kommuner
        n = gmeta["national"]
        bad_rel = [c for c in gk
                   if abs(gk[c]["gap_per_1000_rel"]
                          - (gk[c]["gap_per_1000"] - n["gap_per_1000"])) > 0.011]
        sums = {f: sum(gk[c][f] for c in gk) for f in ("demand_5y", "supply_5y", "p_base")}
        bad_sum = [f for f in sums if abs(sums[f] - n[f]) > 1]
        print(f"   {'✓' if not bad_rel else '✗'} gap_per_1000_rel = gap_per_1000 − Denmark's "
              f"{n['gap_per_1000']:+.2f} for {len(gk) - len(bad_rel)}/{len(gk)} kommuner")
        print(f"   {'✓' if not bad_sum else '✗'} Σ kommuner = Denmark for "
              f"{', '.join(sorted(set(sums) - set(bad_sum)))}")
        if bad_rel or bad_sum:
            fails.append("housing gap coverage")

        print(f"\n8. gap_per_1000 recomputed from the raw cells, {len(BY_HAND)} kommuner")
        pulls = {t: raw_path(gmeta["tables"][t]["pull"]) for t in ("FOLK1A", "FAM55N", "BOL101")}
        if any(v is None for v in pulls.values()):
            gone = [t for t, v in pulls.items() if v is None]
            print(f"   ⚠ raw pulls for {', '.join(gone)} are not on disk "
                  f"(gitignored) — rerun scripts/build_housing_gap.py to restore them")
        else:
            t = gmeta["tables"]
            pph_years = t["FAM55N"]["trend_years"]
            pop_periods = t["FOLK1A"]["trend_periods"]
            y_prev, y_now = t["BOL101"]["stock_years"]
            span = t["BOL101"]["span_years"]
            horizon = gmeta["projection"]["horizon_years"]
            ymid = gmeta["projection"]["mid_year"]
            raw = {k: read_csv(pulls[k]) for k in pulls}

            def cells(table, code, period):
                return sum(int(r["INDHOLD"]) for r in raw[table]
                           if r["OMRÅDE"] == code and r["TID"] == period)

            for c in BY_HAND:
                pph = [cells("FOLK1A", c, p) / cells("FAM55N", c, y)
                       for y, p in zip(pph_years, pop_periods)]
                base, step = pph[-1], (pph[-1] - pph[0]) / (len(pph) - 1)
                # the cap, written out rather than imported: ±5 % of the base over the whole
                # window, then a hard floor of 1.6 persons per household
                mid = min(max(base + step * horizon, base * 0.95), base * 1.05)
                mid = max(mid, 1.6)
                p0, p1 = kom[c][years[0]]["total"], kom[c][ymid]["total"]
                demand = p1 / mid - p0 / base
                supply = (cells("BOL101", c, y_now) - cells("BOL101", c, y_prev)) / span * horizon
                per1000 = (demand - supply) / p0 * 1000
                stored = gk[c]["gap_per_1000"]
                ok = abs(per1000 - stored) < 0.01
                if not ok:
                    fails.append("gap by hand")
                print(f"   {'✓' if ok else '✗'} {c} {NAMES.get(c, ''):<13} "
                      f"p/hh {pph_years[0]} {base - step * (len(pph) - 1):.4f} → "
                      f"{pph_years[-1]} {base:.4f} ({step:+.5f}/yr) → {ymid} {mid:.4f}"
                      f"{'  capped' if abs(mid - (base + step * horizon)) > 1e-9 else ''}")
                print(f"       demand {p1:,} / {mid:.4f} − {p0:,} / {base:.4f} = "
                      f"{demand:>9,.0f}   supply ({cells('BOL101', c, y_now):,} − "
                      f"{cells('BOL101', c, y_prev):,}) / {span} × {horizon} = {supply:>9,.0f}"
                      .replace(",", " "))
                print(f"       gap {demand - supply:>+10,.0f} / {p0:,} × 1000 = "
                      f"{per1000:+.2f}   stored {stored:+.2f}   vs Denmark "
                      f"{gk[c]['gap_per_1000_rel']:+.2f}".replace(",", " "))

        bt = gmeta.get("backtest")
        if bt:
            print(f"\n   backtest {bt['window']} (scripts/build_housing_gap.py): Spearman ρ "
                  f"against the actual gap")
            for s_ in bt["spearman"].values():
                print(f"     {s_['population_input']:<22} old {s_['old']:+.3f}  "
                      f"new {s_['new']:+.3f}  → {s_['new'] - s_['old']:+.3f}")

    # ---- 9. the Copenhagen kvarter forecast ----
    fails += copenhagen(kom, years, meta["table"], args.top)

    print()
    if fails:
        print(f"FAILED: {', '.join(sorted(set(fails)))}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
