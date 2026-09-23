#!/usr/bin/env python3
"""Check data/processed/forecast.json against its own sources. Runnable on its own.

Four checks, in order:
  1. coverage        — every kommune × every year present, nothing missing or null
  2. reconciliation  — Σ kommuner vs the national projection (FRDK) per year   [FAILS > 0.1 %]
  3. base year       — the projection's first year vs the latest actual FOLK1A, per kommune,
                       five largest deviations                                 [information only]
  4. smoke test      — København and Aarhus against the figures in docs/FORECAST_SOURCES.md §1.4

Exit status is non-zero if a check marked FAIL does not pass.

Usage
  python scripts/validate_forecast.py
  python scripts/validate_forecast.py --tolerance 0.05
"""
import argparse
import csv
import io
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "processed" / "forecast.json"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

# docs/FORECAST_SOURCES.md §1.4 — the Phase 1 smoke test, pulled straight from the API.
EXPECTED = {"101": {"2026": 671714, "2031": 689101, "2040": 711011},
            "751": {"2026": 378361, "2031": 399885, "2040": 431031}}
NAMES = {"101": "København", "751": "Aarhus"}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=0.1, help="max Σ-vs-national deviation, %%")
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

    print()
    if fails:
        print(f"FAILED: {', '.join(sorted(set(fails)))}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
