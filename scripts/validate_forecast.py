#!/usr/bin/env python3
"""Check data/processed/forecast.json and data/processed/housing_gap.json against their
own sources. Runnable on its own.

Seven checks, in order:
  1. coverage        — every kommune × every year present, nothing missing or null
  2. reconciliation  — Σ kommuner vs the national projection (FRDK) per year   [FAILS > 0.1 %]
  3. base year       — the projection's first year vs the latest actual FOLK1A, per kommune,
                       five largest deviations                                 [information only]
  4. smoke test      — København and Aarhus against the figures in docs/FORECAST_SOURCES.md §1.4
  5. 20–34 baseline  — the Denmark figure fc_20_34_rel is measured against, checked against
                       FRDK's own age detail, and the two identities that define the pair
                       fc_20_34_rel / fc_20_34_abs                             [FAILS]
  6. housing gap     — 98 kommuner with every component present and non-null, and the two
                       identities that define gap_per_1000_rel                 [FAILS]
  7. gap by hand     — gap_per_1000 recomputed for five kommuner straight from the raw
                       FOLK1A / FAM55N / BOL101 cells, household-size trend, cap and all
                       — a second implementation of the formula                [FAILS]

Checks 6 and 7 are skipped, not failed, when housing_gap.json has not been built.
Exit status is non-zero if a check marked FAIL does not pass.

Usage
  python scripts/validate_forecast.py
  python scripts/validate_forecast.py --tolerance 0.05
  python scripts/validate_forecast.py --top 10        # longer 20–34 rankings
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "processed" / "forecast.json"
GAP = ROOT / "data" / "processed" / "housing_gap.json"
HOUSING_RAW = ROOT / "data" / "raw" / "forecast" / "housing"
FORECAST_RAW = ROOT / "data" / "raw" / "forecast" / "dst"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

# docs/FORECAST_SOURCES.md §1.4 — the Phase 1 smoke test, pulled straight from the API.
EXPECTED = {"101": {"2026": 671714, "2031": 689101, "2040": 711011},
            "751": {"2026": 378361, "2031": 399885, "2040": 431031}}
NAMES = {"101": "København", "751": "Aarhus", "153": "Brøndby", "665": "Lemvig",
         "147": "Frederiksberg"}
# check 7 — a spread of sizes and directions: two big cities, a suburb that grows, a
# shrinking rural kommune, and the densest kommune in the country
BY_HAND = ["101", "751", "153", "665", "147"]
FIELDS = ("total", "a0_5", "a6_16", "a17_19", "a20_34", "a35_64", "a65_79", "a80p")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=0.1, help="max Σ-vs-national deviation, %%")
    ap.add_argument("--top", type=int, default=10, help="rows at each end of the 20–34 rankings")
    args = ap.parse_args()
    if not SRC.exists():
        sys.exit(f"{SRC.relative_to(ROOT)} not found — run scripts/build_forecast.py first")
    d = json.loads(SRC.read_text())
    meta, kom, nat = d["meta"], d["kommuner"], d["national"]
    years = meta["years"]
    fails = []

    print(f"forecast.json · {meta['table']} vintage {meta['vintage']} "
          f"(updated {meta['updated']}, fetched {meta['fetched']}) · {years[0]}–{years[-1]}\n")

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

    # ---- 6 & 7. the housing gap ----
    if not GAP.exists():
        print(f"\n6/7. housing gap — {GAP.relative_to(ROOT)} not built, skipped "
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
        print(f"\n6. housing gap — {len(gk)} kommuner × {len(parts)} components, "
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

        print(f"\n7. gap_per_1000 recomputed from the raw cells, {len(BY_HAND)} kommuner")
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

    print()
    if fails:
        print(f"FAILED: {', '.join(sorted(set(fails)))}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
