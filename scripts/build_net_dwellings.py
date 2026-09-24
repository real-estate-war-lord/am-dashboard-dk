#!/usr/bin/env python3
"""Build data/processed/net_dwellings.json — how many dwellings each municipality's
housing stock actually gained per year over the latest published BOL101 window.

    net_per_year   = (stock_<base> − stock_<start>) / span_years
    hist_net_dwell = net_per_year / population × 1000

Nothing else. Both terms are published cells — BOL101's dwelling stock at 1 January and
FOLK1A's population at the latest quarter — and the operations between them are a
difference, a division by the number of years the difference spans, a division by
population and a multiplication by 1 000. There is no trend, no cap, no projection and no
assumption of any kind, which is the whole point: this is the **measured** building pace,
the historical counterpart to the Outlook layer's projections, and it belongs in the
housing group rather than in Outlook. See docs/FORECAST.md §3.

It is deliberately *not* compared with anything. `data/processed/housing_gap.json` does
make that comparison and is kept as research only — it needs a household-size assumption,
so it is not allowed into the UI (docs/FORECAST.md §0).

**The window is not always five years.** DST publishes no BOL101 for 2021 or 2022 — both
closed "due to errors in data from the Building and Housing Register" — so the newest
published year at or before `base − 5` is taken as the start and the change is annualised
over the span that actually separates the two. Today that is 2020 → 2026, six years. The
years are resolved from the live table, never hard-coded, and `meta` records them so the
label can name the real window.

The BOL101 selection (`BEBO`, `ANVENDELSE`) and the CSV/area plumbing are imported from
`scripts/build_housing_gap.py` so the two builds read exactly the same stock; none of that
script's modelling is used or imported here.

Inputs  (fetched unless --no-fetch)
  DST BOL101    dwelling stock at 1 January, all uses and all resident types
  DST FOLK1A    population, latest published quarter

Raw pulls (gitignored, re-downloadable) — shared with scripts/build_housing_gap.py
  data/raw/forecast/housing/BOL101_stock_<date>.csv
  data/raw/forecast/housing/FOLK1A_latest_<date>.csv

Output
  data/processed/net_dwellings.json
    {"meta": {...},
     "kommuner": {"<code>": {"stock_start", "stock_end", "span_years", "net_total",
                             "net_per_year", "pop", "pop_period", "hist_net_dwell"}},
     "national": {...}}

Usage
  python scripts/build_net_dwellings.py                # fetch (or reuse) + build
  python scripts/build_net_dwellings.py --no-fetch     # build from cached CSVs only
  python scripts/build_net_dwellings.py --rank 15      # rows at each end of the ranking
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import build_housing_gap as hg  # noqa: E402  — CSV plumbing and the BOL101 selection only
from statbank_common import period_key  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "net_dwellings.json"
WINDOW = 5      # the window we ask for; the span actually published may be longer
# Christiansø: in DST's area list, not a municipality. BOL101 reports 0 dwellings for it —
# the islands are administered by the Ministry of Defence and their housing is outside the
# Building and Housing Register — so a net-additions figure for it would read 0.00 without
# meaning it. forecast.json excludes the same code, for its own reason.
EXCLUDE = {"411"}


def tableinfo(table: str) -> dict:
    """The cached tableinfo, ours first, then the repo's committed copy."""
    for p in (hg.RAW / f"{table}.meta.json", ROOT / "data" / "raw" / f"dst_{table}.meta.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def updated(table: str) -> str | None:
    return (tableinfo(table).get("updated") or "")[:10] or None


def kommune_names() -> dict[str, str]:
    """code -> name, from BOL101's cached tableinfo (English labels)."""
    return {x["id"]: x["text"] for v in tableinfo("BOL101").get("variables", [])
            if v["id"] == "OMRÅDE" for x in v["values"] if hg.is_kommune(x["id"])}


def stock_window(avail: list[str]) -> tuple[str, str, int]:
    """(start, base, span) — the newest published year, the newest published year at or
    before `base − WINDOW`, and the number of years between them."""
    base = max(avail, key=int)
    target = int(base) - WINDOW
    start = max((y for y in avail if int(y) <= target), default=None)
    if start is None:
        sys.exit(f"BOL101 has no year at or before {target} — the stock window has no start")
    return start, base, int(base) - int(start)


def bol101(today: str, no_fetch: bool) -> tuple[list[dict], pathlib.Path, str, list[str]]:
    """The dwelling stock, preferring a cached pull that already covers the window.

    Shares `BOL101_stock_<date>.csv` with scripts/build_housing_gap.py, so whichever of the
    two runs first pays for the pull. BEBO cannot be eliminated on BOL101, so a cached file
    with a different BEBO selection is a different stock — the check below rejects it
    rather than silently summing the wrong thing.
    """
    def usable(rs):
        return set(hg.BEBO_ALL) <= {r["BEBO"] for r in rs} and len(
            [y for y in hg.periods(rs) if y.isdigit()]) >= 2

    for p in sorted(hg.RAW.glob("BOL101_stock_20*.csv"))[::-1]:
        rs = hg.read(p)
        if usable(rs):
            return rs, p, "cached", sorted(y for y in hg.periods(rs) if y.isdigit())
    if no_fetch:
        sys.exit("no cached BOL101 pull in data/raw/forecast/housing — run without --no-fetch")
    years = [y for y in hg.tid_codes("BOL101") if y.isdigit()]
    p = hg.fetch("BOL101", {"OMRÅDE": ["*"], "BEBO": hg.BEBO_ALL,
                            "ANVENDELSE": hg.BOL101_USES, "Tid": years}, today, "_stock")
    rs = hg.read(p)
    if not usable(rs):
        sys.exit("BOL101: the fresh pull does not cover the stock window — check the selection")
    return rs, p, "fetched", sorted(y for y in hg.periods(rs) if y.isdigit())


def folk1a(today: str, no_fetch: bool) -> tuple[dict[str, int], str, pathlib.Path, str]:
    """Population per municipality at the latest published FOLK1A quarter."""
    want = None if no_fetch else hg.tid_codes("FOLK1A")[-1]

    def covers(rs):
        nonlocal want
        ps = hg.periods(rs)
        if want is None:                       # --no-fetch: take whatever the cache holds
            want = max(ps, key=period_key, default=None)
        return bool(want) and want in ps

    rs, p, how = hg.source("FOLK1A", {"OMRÅDE": ["*"], "Tid": ["(-n+1)"]},
                           "_latest", covers, today, no_fetch)
    return hg.fold(rs, {want})[want], want, p, how


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="build from cached CSVs only")
    ap.add_argument("--rank", type=int, default=10, help="rows at each end of the printed ranking")
    args = ap.parse_args()
    today = dt.date.today().isoformat()

    bol, p_bol, how_bol, avail = bol101(today, args.no_fetch)
    start, base, span = stock_window(avail)
    stock = hg.fold(bol, {start, base})
    print(f"  BOL101 {', '.join(avail)} · {how_bol} · {p_bol.name}\n"
          f"    net additions over {start}–{base}, {span} years"
          + ("" if span == WINDOW else "  (DST publishes no 2021 or 2022)"))

    pop, pop_period, p_folk, how_folk = folk1a(today, args.no_fetch)
    print(f"  FOLK1A {pop_period} · {how_folk} · {p_folk.name}")

    out, missing = {}, []
    codes = (set(stock[base]) & set(stock[start]) & set(pop)) - EXCLUDE
    for code in sorted(codes, key=int):
        a, b, p = stock[start].get(code), stock[base].get(code), pop.get(code)
        if a is None or b is None or not p:
            missing.append(code)
            continue
        per_year = (b - a) / span
        out[code] = {
            "stock_start": a, "stock_end": b, "span_years": span,
            "net_total": b - a, "net_per_year": round(per_year, 1),
            "pop": p, "pop_period": pop_period,
            "hist_net_dwell": round(per_year / p * 1000, 2),
        }
    if missing:
        sys.exit(f"{len(missing)} kommuner lack a stock or population figure: {missing[:5]}")
    if len(out) != 98:
        sys.exit(f"expected 98 kommuner, got {len(out)} — check the OMRÅDE filter")

    # Denmark as the Σ of the same 98 municipalities, computed the same way — the same
    # rule the Outlook layer follows, so the two are comparable.
    tot = lambda f: sum(v[f] for v in out.values())  # noqa: E731
    dk_per_year = (tot("stock_end") - tot("stock_start")) / span
    national = {
        "stock_start": tot("stock_start"), "stock_end": tot("stock_end"),
        "span_years": span, "net_total": tot("net_total"),
        "net_per_year": round(dk_per_year, 1), "pop": tot("pop"),
        "hist_net_dwell": round(dk_per_year / tot("pop") * 1000, 2),
    }

    meta = {
        "built": today, "fetched": today,
        "kommuner": len(out),
        "excluded": sorted(EXCLUDE),
        "window": [start, base], "span_years": span,
        "label_years": f"{start}–{base}",
        "pop_period": pop_period,
        "formula": f"hist_net_dwell = (stock_{base} − stock_{start}) / {span} / "
                   f"population_{pop_period} × 1000",
        "arithmetic_only": "a difference, a division by the span in years, a division by "
                           "population and × 1000 — no trend, no cap, no projection",
        "tables": {
            "BOL101": {"what": "dwelling stock, 1 January, all uses and all resident types",
                       "years_published": avail, "window": [start, base],
                       "span_years": span,
                       "closed_years": [y for y in
                                        (str(x) for x in range(int(start) + 1, int(base)))
                                        if y not in avail],
                       "closed_note": "DST publishes no BOL101 for the years listed in "
                                      "closed_years — closed due to errors in the Building "
                                      "and Housing Register — so the window is annualised "
                                      "over the span that actually separates its two ends",
                       "updated": updated("BOL101"),
                       "pull": p_bol.name, "how": how_bol},
            "FOLK1A": {"what": "population, latest published quarter",
                       "period": pop_period, "updated": updated("FOLK1A"),
                       "pull": p_folk.name, "how": how_folk},
        },
        "national": national,
        "sign": "positive = the dwelling stock grew; negative = it shrank. This is the net "
                "change, so demolitions, mergers and conversions out of housing are already "
                "netted off, unlike gross completions (BYGV33).",
        "caveats": "BOL101 counts dwellings that exist, not dwellings that are available — "
                   "vacancy, second homes and student housing are not distinguished. The "
                   "denominator is the population, not the dwelling stock, so this is "
                   "dwellings added per 1 000 people rather than a growth rate of the stock.",
        "licence": "free reuse with attribution",
        "source": f"Danmarks Statistik BOL101 (dwelling stock 1 January {start} and {base}) "
                  f"and FOLK1A (population {pop_period})",
        "url": "https://api.statbank.dk/v1/tableinfo/BOL101",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "kommuner": out, "national": national},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)} · {len(out)} kommuner · "
          f"Denmark {national['net_per_year']:,.0f} dwellings/yr = "
          f"{national['hist_net_dwell']:+.2f} per 1 000 inhabitants".replace(",", " "))

    names = kommune_names()
    rank = sorted((v["hist_net_dwell"], c) for c, v in out.items())
    for title, part in ((f"\ntop {args.rank}", rank[::-1][:args.rank]),
                        (f"\nbottom {args.rank}", rank[:args.rank])):
        print(title)
        for i, (v, c) in enumerate(part, 1):
            k = out[c]
            print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {v:+7.2f}   "
                  f"{k['stock_start']:>8,} → {k['stock_end']:>8,} "
                  f"({k['net_per_year']:+,.0f}/yr, pop {k['pop']:,})".replace(",", " "))


if __name__ == "__main__":
    main()
