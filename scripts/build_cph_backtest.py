#!/usr/bin/env python3
"""Build data/processed/cph_backtest.json — how well have Københavns Kommune's own
kvarter forecasts actually done?

§8 of docs/FORECAST.md shows KKFR2026 putting Vesterbro Syd at +203 % and Nordhavn at
+176 % by 2040, and warns that a kvarter number is the city's unpublished housing
programme in disguise. This script turns that warning into a measurement: it replays
every superseded vintage against what actually happened, per kvarter and per bydel.

    forecast   KKFR<V>(k, V+h)            the vintage-V projection for horizon h
    actual     KKBEF1(k, (V+h)K1)         the observed population at the same 1 January
    baseline   KKFR<V>(k, V) × KKFR<V>(city, V+h) / KKFR<V>(city, V)

The baseline is the point of the exercise. It is the *same* city-level projection —
the demographic part KK would produce anyway — applied pro rata to every kvarter with
no district detail at all. Beating it is what the boligprognose-driven split has to do
to be worth anything. It uses only information available at 1 January V, and it starts
from the vintage's own base year rather than from KKBEF1, so the comparison isolates
the split and not the base (which is measured separately, as horizon 0).

🔎 **The older vintages are not in the catalogue but they are still served.**
`GET /v1/s30/tables` lists only KKFR2026 — KK replaces the table each March — yet
`GET /v1/s30/tableinfo/KKFR2021` answers normally, and so does a data request. This
script therefore probes the ids directly over a window of years rather than reading the
catalogue, and records which ones answered. docs/FORECAST_SOURCES.md §2.1 said last
year's table was "gone from the catalogue", which is true of the listing only.

All seven vintages 2020–2026 share one schema and one 93-code OMRKK list, identical to
KKBEF1's, so no crosswalk is needed anywhere and a kvarter can be followed across
vintages by its code.

Hard-data rule (docs/FORECAST.md §0): every number here is a published KKFR or KKBEF1
cell, or a difference, ratio, mean or median of published cells. Nothing is modelled.

Inputs  (fetched unless --no-fetch)
  api.statbank.dk/v1/s30/tableinfo/KKFR<V>   probed per vintage; unlisted but served
  api.statbank.dk/v1/s30/data                KKFR<V> totals, and KKBEF1 actuals

Raw pulls (gitignored, re-downloadable)
  data/raw/forecast/cph/KKFR<V>_bt_<YYYY-MM-DD>.csv
  data/raw/forecast/cph/KKBEF1_bt_<YYYY-MM-DD>.csv

Output
  data/processed/cph_backtest.json
    {"meta": {...},
     "horizons": {"<h>": {"forecast": {...}, "baseline": {...}, "n": …}},
     "areas":   {"<code>": {"bt_mape", "bt_bias", "bt_medape", "bt_mae",
                            "bt_baseline_mape", "bt_n", "bt_mape_by_horizon",
                            "bt_mape_5y", "bt_over_5y", "bt_n_5y", "bt_line_eligible"}},
     "pairs":   [{"vintage", "horizon", "year", "code", "forecast", "actual", "baseline"}]}

Usage
  python scripts/build_cph_backtest.py                 # probe, pull, score, print
  python scripts/build_cph_backtest.py --no-fetch      # rebuild from cached CSVs
  python scripts/build_cph_backtest.py --back 10       # how many vintages to probe
  python scripts/build_cph_backtest.py --worst 10      # rows in the worst-kvarter table
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from build_cph_forecast import (API, CITY, DB, RAW, TOL_BYDEL, TOL_CITY, UA,  # noqa: E402
                                UNALLOCATED, level_of, names_of, parents,
                                post_csv, resolve, short_name)

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "cph_backtest.json"
HORIZONS = (1, 3, 5)     # years ahead to score; 0 is added as the base-year check

# ---- the one backtest figure that reaches the UI -----------------------------------
# docs/FORECAST.md §9.7: Copenhagen kvarter and bydel AREA PAGES carry a single factual
# line built from bt_mape_5y, bt_over_5y and bt_n_5y. Never on the map, never coloured.
# An area with fewer than BT_LINE_MIN vintages at h=5 shows nothing at all rather than a
# figure resting on one or two replays — a count, not a confidence interval, because the
# rule has to be checkable from the data.
BT_LINE_H = 5
BT_LINE_MIN = 3


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r)


def vintages(latest: int, back: int) -> list[int]:
    """Every KKFR<year> the API serves, newest first — probed, not read from the catalogue.

    `/v1/s30/tables` lists the current vintage only, but the superseded ones still answer
    on tableinfo. A 400 means the id is not served; anything else is a real error and is
    re-raised rather than silently shrinking the backtest.
    """
    out = []
    for y in range(latest, latest - back - 1, -1):
        try:
            get(f"{API}/{DB}/tableinfo/KKFR{y}?lang=en&format=JSON")
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                continue
            raise
        out.append(y)
    return out


def fetch(table: str, variables: dict, today: str, tag: str) -> pathlib.Path:
    RAW.mkdir(parents=True, exist_ok=True)
    text = post_csv({"table": table, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                     "valuePresentation": "Code",
                     "variables": [{"code": k, "values": v} for k, v in variables.items()]})
    if text.lstrip().startswith("{"):
        sys.exit(f"{table}: API returned an error instead of CSV:\n{text[:400]}")
    p = RAW / f"{table}{tag}_{today}.csv"
    p.write_text(text, encoding="utf-8")
    return p


def newest(table: str, tag: str) -> pathlib.Path:
    files = sorted(RAW.glob(f"{table}{tag}_20??-??-??.csv"))
    if not files:
        sys.exit(f"no cached pull for {table}{tag} in {RAW} — run without --no-fetch")
    return files[-1]


def read(path: pathlib.Path) -> dict[str, dict[str, int]]:
    """{period: {code: population}} from a semicolon CSV with OMRKK, TID and INDHOLD."""
    out: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            out.setdefault(r["TID"], {})[r["OMRKK"]] = int(r["INDHOLD"])
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def score(pairs: list[dict], key: str) -> dict:
    """MAPE, bias (mean percentage error), median APE and MAE in persons."""
    ape = [abs(p[key] - p["actual"]) / p["actual"] * 100 for p in pairs if p["actual"]]
    pe = [(p[key] - p["actual"]) / p["actual"] * 100 for p in pairs if p["actual"]]
    ae = [abs(p[key] - p["actual"]) for p in pairs]
    return {"mape": round(mean(ape), 2) if ape else None,
            "bias": round(mean(pe), 2) if pe else None,
            "medape": round(median(ape), 2) if ape else None,
            "mae": round(mean(ae), 1) if ae else None}


def additivity(stock: dict[str, dict[str, int]], levels: dict, label: str) -> list[str]:
    """Part 2's rounding-tolerance logic, reused on every vintage's own cells."""
    notes = []
    for period, cells in stock.items():
        kv = [k for k in levels["kvarter"] if k in cells]
        if CITY not in cells or not kv:
            continue
        gap = abs(sum(cells[k] for k in kv) - cells[CITY])
        if gap > TOL_CITY:
            notes.append(f"{label} {period}: Σ {len(kv)} kvarterer misses the city total by "
                         f"{gap} (> ±{TOL_CITY})")
        for b in [c for c in levels["bydel"] if c in cells]:
            kids = [k for k in kv if parents(k)[1] == b]
            g = abs(sum(cells[k] for k in kids) - cells[b])
            if kids and g > TOL_BYDEL:
                notes.append(f"{label} {period}: Σ kvarterer of bydel {b} misses it by "
                             f"{g} (> ±{TOL_BYDEL})")
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="rebuild from cached CSVs")
    ap.add_argument("--back", type=int, default=10, help="how many vintages back to probe")
    ap.add_argument("--worst", type=int, default=10, help="rows in the worst-kvarter table")
    args = ap.parse_args()
    today = dt.date.today().isoformat()

    cur_table, cur = resolve("KKFR")
    info = get(f"{API}/{DB}/tableinfo/{cur_table}?lang=en&format=JSON")
    names = names_of(info)
    codes = [x["id"] for v in info["variables"] if v["id"] == "OMRKK" for x in v["values"]]
    levels: dict[str, list[str]] = {}
    for c in sorted(codes, key=lambda x: (len(x), x)):
        levels.setdefault(level_of(c), []).append(c)

    if args.no_fetch:
        vs = sorted({int(p.name[4:8]) for p in RAW.glob("KKFR????_bt_20??-??-??.csv")},
                    reverse=True)
        if not vs:
            sys.exit(f"no cached backtest pulls in {RAW} — run without --no-fetch")
    else:
        vs = vintages(cur, args.back)
    print(f"→ {DB}/KKFR · vintages served: {', '.join(str(v) for v in vs)} "
          f"(catalogue lists {cur_table} only)")
    old = [v for v in vs if v < cur]
    if not old:
        print("\nNo superseded vintage is available — nothing to backtest against.")
        return

    # ---- actuals: KKBEF1 at 1 January of every year any vintage can be scored on ----
    want_years = sorted({v + h for v in old for h in (0, *HORIZONS)} | {v for v in old})
    periods = [f"{y}K1" for y in want_years]
    if args.no_fetch:
        p_act = newest("KKBEF1", "_bt")
        actual = read(p_act)
    else:
        info_b = get(f"{API}/{DB}/tableinfo/KKBEF1?lang=en&format=JSON")
        have = {x["id"] for v in info_b["variables"] if v["id"] == "Tid" for x in v["values"]}
        periods = [p for p in periods if p in have]
        p_act = fetch("KKBEF1", {"OMRKK": ["*"], "KON": ["TOT"], "ALDER": ["TOT"],
                                 "CIVILSTAND": ["TOT"], "Tid": periods}, today, "_bt")
        actual = read(p_act)
    print(f"  actuals KKBEF1 {min(actual)}–{max(actual)} · {p_act.name}")

    warnings = additivity(actual, levels, "KKBEF1")

    # ---- each superseded vintage, at the horizons that now have an actual ----
    pairs: list[dict] = []
    used: dict[int, list[int]] = {}
    for v in old:
        hs = [h for h in (0, *HORIZONS) if f"{v + h}K1" in actual]
        if not hs:
            continue
        years = [str(v)] + [str(v + h) for h in hs if h]
        if args.no_fetch:
            p = newest(f"KKFR{v}", "_bt")
        else:
            ti = get(f"{API}/{DB}/tableinfo/KKFR{v}?lang=en&format=JSON")
            has = {x["id"] for x in next(q for q in ti["variables"] if q["id"] == "Tid")["values"]}
            years = [y for y in years if y in has]
            hs = [h for h in hs if str(v + h) in years or h == 0]
            p = fetch(f"KKFR{v}", {"OMRKK": ["*"], "KON": ["TOT"], "ALDER": ["TOT"],
                                   "Tid": years}, today, "_bt")
        fc = read(p)
        warnings += additivity(fc, levels, f"KKFR{v}")
        used[v] = hs
        base_city = fc[str(v)][CITY]
        for h in hs:
            y = str(v + h)
            if y not in fc:
                continue
            ratio = fc[y][CITY] / base_city
            for k in codes:
                a = actual[f"{y}K1"].get(k)
                if not a or k not in fc[y] or k not in fc[str(v)]:
                    continue
                pairs.append({"vintage": v, "horizon": h, "year": y, "code": k,
                              "forecast": fc[y][k], "actual": a,
                              "baseline": fc[str(v)][k] * ratio})
        print(f"  KKFR{v} · horizons {', '.join(str(h) for h in hs)} · {p.name}")

    drawn_kv = [k for k in levels["kvarter"] if k != UNALLOCATED["kvarter"]]
    drawn_bd = [b for b in levels["bydel"] if b != UNALLOCATED["bydel"]]

    def summarise(sel: list[str]) -> dict:
        out = {}
        for h in (0, *HORIZONS):
            ps = [p for p in pairs if p["horizon"] == h and p["code"] in sel]
            if not ps:
                continue
            f_, b_ = score(ps, "forecast"), score(ps, "baseline")
            skill = (round((1 - f_["mape"] / b_["mape"]) * 100, 1)
                     if f_["mape"] and b_["mape"] else None)
            out[str(h)] = {"forecast": f_, "baseline": b_, "skill_pct": skill,
                           "n": len(ps), "vintages": sorted({p["vintage"] for p in ps})}
        return out

    # Per-area keys are prefixed bt_ so they are unambiguous wherever they are read, and
    # so docs/FORECAST.md §3's audit can name them. These are the figures a Phase B
    # reliability panel would show beside a forecast — see §9.
    per_area: dict[str, dict] = {}
    for k in drawn_kv + drawn_bd + [CITY]:
        ps = [p for p in pairs if p["code"] == k and p["horizon"]]
        if not ps:
            continue
        f_ = score(ps, "forecast")
        # the UI line: h=5 only, with the over-forecast count beside the error, so the
        # sentence can say "y of z vintages over-forecast" from stored figures alone
        at5 = [p for p in ps if p["horizon"] == BT_LINE_H]
        per_area[k] = {"bt_mape": f_["mape"], "bt_bias": f_["bias"],
                       "bt_medape": f_["medape"], "bt_mae": f_["mae"],
                       "bt_baseline_mape": score(ps, "baseline")["mape"],
                       "bt_n": len(ps),
                       "bt_mape_5y": score(at5, "forecast")["mape"] if at5 else None,
                       "bt_over_5y": sum(1 for p in at5 if p["forecast"] > p["actual"]),
                       "bt_n_5y": len(at5),
                       "bt_line_eligible": len(at5) >= BT_LINE_MIN,
                       "bt_mape_by_horizon": {
                           str(h): score([p for p in ps if p["horizon"] == h],
                                         "forecast")["mape"]
                           for h in HORIZONS if any(p["horizon"] == h for p in ps)}}

    meta = {
        "built": today, "fetched": today,
        "current_vintage": cur, "current_table": cur_table,
        "vintages_served": vs, "vintages_scored": used,
        "catalogue_note": "GET /v1/s30/tables lists the current vintage only; the "
                          "superseded ids are unlisted but still served, so they are "
                          "probed directly. See docs/FORECAST.md §9.",
        "horizons": list(HORIZONS),
        "actual_table": "KKBEF1", "actual_periods": sorted(actual),
        "baseline": "KKFR<V>(k, V) × KKFR<V>(city, V+h) / KKFR<V>(city, V) — the vintage's "
                    "own city-level projection applied pro rata to every kvarter, with no "
                    "district detail. Uses only information available at 1 January V.",
        "horizon_0_note": "Horizon 0 compares each vintage's own base year with KKBEF1's "
                          "observed population at the same 1 January. It is not a forecast "
                          "error: it is the gap between KK's cleaned CPR base and the "
                          "published (and since revised) observation. Forecast and baseline "
                          "are identical at h=0 by construction, so no skill is reported.",
        "metrics": "mape = mean |F−A|/A ×100; bias = mean (F−A)/A ×100; medape = median "
                   "|F−A|/A ×100; mae = mean |F−A| in persons; skill_pct = "
                   "(1 − mape_forecast / mape_baseline) × 100, positive = the district "
                   "split beats the pro-rata city baseline.",
        "tolerances": {"city": TOL_CITY, "bydel": TOL_BYDEL},
        "ui_line": {
            "horizon": BT_LINE_H, "min_vintages": BT_LINE_MIN,
            "keys": ["bt_mape_5y", "bt_over_5y", "bt_n_5y", "bt_line_eligible"],
            "where": "Copenhagen kvarter and bydel area pages only — never the map, never "
                     "coloured, never a ranking.",
            "text": "Past accuracy: KK's 5-year forecasts for this area were off by "
                    "{bt_mape_5y} % on average ({bt_over_5y} of {bt_n_5y} vintages "
                    "over-forecast).",
            "rule": f"Render only where bt_line_eligible is true, i.e. bt_n_5y >= "
                    f"{BT_LINE_MIN}. Below that, show nothing — not a hedged figure.",
            "note": "This is the ONLY backtest figure that reaches the UI. bt_mape, "
                    "bt_bias, bt_medape, bt_mae and bt_baseline_mape stay in this file "
                    "and in docs/FORECAST.md §9 as research.",
        },
        "additivity_warnings": warnings,
        "licence": "free reuse with attribution",
        "source": f"Københavns Kommune KKFR{min(old)}–KKFR{cur} and KKBEF1, "
                  f"via api.statbank.dk/v1/{DB}",
        "attribution": "Københavns Kommune statbank (s30)",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"meta": meta,
         "kvarter_summary": summarise(drawn_kv),
         "bydel_summary": summarise(drawn_bd),
         "city_summary": summarise([CITY]),
         "areas": per_area,
         "names": {k: short_name(names.get(k, "")) for k in per_area}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(pairs):,} forecast-actual pairs · "
          f"{len(per_area)} areas".replace(",", " "))
    for w in warnings[:5]:
        print(f"  ⚠ {w}")

    report(summarise(drawn_kv), summarise(drawn_bd), summarise([CITY]), per_area,
           names, drawn_kv, args.worst)


def report(kv, bd, city, per_area, names, drawn_kv, worst):
    for label, s in (("67 kvarterer", kv), ("10 bydele", bd), ("city total", city)):
        print(f"\n{label} — KK forecast vs the pro-rata city baseline")
        print(f"  {'h':>2} {'n':>5}  {'MAPE':>7} {'bias':>7} {'medAPE':>7} {'MAE':>7}   "
              f"{'base MAPE':>9} {'base bias':>9}   {'skill':>7}")
        for h, r in sorted(s.items(), key=lambda kv_: int(kv_[0])):
            f_, b_ = r["forecast"], r["baseline"]
            sk = "= fc" if h == "0" else (f"{r['skill_pct']:+.1f} %"
                                          if r["skill_pct"] is not None else "—")
            print(f"  {h:>2} {r['n']:>5}  {f_['mape']:>6.2f}% {f_['bias']:>6.2f}% "
                  f"{f_['medape']:>6.2f}% {f_['mae']:>7.1f}   {b_['mape']:>8.2f}% "
                  f"{b_['bias']:>8.2f}%   {sk:>7}")

    rank = sorted(((per_area[k]["bt_mape"], k) for k in drawn_kv if k in per_area), reverse=True)
    print(f"\nworst {worst} kvarterer by MAPE (all horizons ≥1 pooled)")
    print(f"  {'':3} {'code':>5} {'kvarter':<34} {'MAPE':>7} {'bias':>8} {'baseline':>9} {'n':>4}")
    for i, (m, k) in enumerate(rank[:worst], 1):
        a = per_area[k]
        print(f"  {i:>2}. {k:>5} {names.get(k, ''):<34} {m:>6.2f}% {a['bt_bias']:>+7.2f}% "
              f"{a['bt_baseline_mape']:>8.2f}% {a['bt_n']:>4}")
    print(f"\nbest {worst} kvarterer by MAPE")
    for i, (m, k) in enumerate(rank[::-1][:worst], 1):
        a = per_area[k]
        print(f"  {i:>2}. {k:>5} {names.get(k, ''):<34} {m:>6.2f}% {a['bt_bias']:>+7.2f}% "
              f"{a['bt_baseline_mape']:>8.2f}% {a['bt_n']:>4}")


if __name__ == "__main__":
    main()
