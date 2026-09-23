#!/usr/bin/env python3
"""Build data/processed/housing_gap.json — is enough housing being built for the
population growth DST projects over the next five years?

The question the indicator answers, per municipality:

    pph₂₀₃₁    = persons_per_hh₂₀₂₆ + 5 × its recent yearly change   (capped, see below)
    demand_5y  = P₂₀₃₁ / pph₂₀₃₁ − P₂₀₂₆ / pph₂₀₂₆     households the projection implies
    supply_5y  = mean yearly change in the BOL101 dwelling stock, last 5 years × 5
    gap        = demand_5y − supply_5y                  positive = undersupply
    gap_per_1000 = gap / P₂₀₂₆ × 1000                   comparable across sizes
    gap_per_1000_rel = gap_per_1000 − Denmark's         the map indicator

Two things separate this from the first version of the indicator, both of which pushed
every municipality onto the same side of zero (see docs/FORECAST.md §7):

  * **Household size is projected, not frozen.** Danish household size falls steadily, and
    holding it at its base-year value missed ~28 % of the household formation the last five
    years actually produced. `persons_per_hh` is now read for six years and carried forward
    at its own average yearly change, with the total five-year move capped at ±5 % and a
    hard floor of 1.6 persons so an extrapolated trend cannot run away.
  * **Supply is the net change in the dwelling stock**, from BOL101 at 1 January, rather
    than BYGV33 gross completions. Demolitions, mergers and conversions out of housing are
    then netted off, which gross completions cannot do. The completions and the permitted
    pipeline stay in the output as context.

Both older variants are kept alongside — `demand_5y_const` and `supply_5y_gross` — so the
effect of each fix stays visible, and `--backtest` scores the old and the new formula
against what actually happened over the last complete five-year window.

`persons_per_hh` is FOLK1A population ÷ FAM55N households at the same 1 January, so it is
the municipality's own household size rather than a national average. See docs/FORECAST.md
§7 for the assumptions and what is deliberately not modelled.

Inputs
  data/processed/forecast.json             P₂₀₂₆ and P₂₀₃₁ (build_forecast.py)
  DST FOLK1A                               population, 1 January
  DST FAM55N                               households, 1 January
  DST BOL101                               dwelling stock, 1 January
  DST BYGV33                               dwellings by phase of construction, quarterly
  DST FRKM1<vv>                            the base-year vintage of the municipal
                                           projection, for the backtest only

Raw pulls are reused before they are fetched: if `fetch_statbank.py` has already left a
usable `data/raw/dst_<TABLE>_<date>.csv` this script reads it, and only pulls its own copy
into `data/raw/forecast/housing/` when the cached selection does not cover what it needs.
BYGV33 and BOL101 always need their own pull — the repo's cached BYGV33 selection is
`BYGFASE=3` (completed) only, while the permitted-not-started pipeline needs phases 1 and
2, and BOL101's `BEBO` cannot be eliminated, so the stock has to be selected explicitly.
The tableinfo is only cached here when it differs from the committed
`data/raw/dst_<TABLE>.meta.json`; see tableinfo().

Output
  data/processed/housing_gap.json
    {"meta": {...},
     "kommuner": {"<code>": {"pop", "households", "persons_per_hh",
                             "persons_per_hh_by_year", "pph_change_per_year",
                             "persons_per_hh_mid", "pph_capped",
                             "p_base", "p_mid", "households_base", "households_mid",
                             "demand_5y", "demand_5y_const",
                             "stock_base", "stock_prev", "supply_5y",
                             "supply_5y_excl_cottages", "supply_5y_gross",
                             "completions_by_year", "gap", "gap_per_1000",
                             "gap_per_1000_rel", "gap_const_gross",
                             "gap_per_1000_const_gross", "permits_4q", "starts_4q",
                             "pipeline_permitted"}}}

Usage
  python scripts/build_housing_gap.py                 # reuse/fetch, build, backtest, rank
  python scripts/build_housing_gap.py --no-fetch      # build from cached CSVs only
  python scripts/build_housing_gap.py --no-backtest   # skip the 2020→2025 scoring
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
TREND_YEARS = 5         # first differences averaged for both the pph trend and the stock
PPH_CAP = 0.05          # max total move of persons_per_hh over the window, ±5 %
PPH_FLOOR = 1.6         # projected persons_per_hh is never taken below this
FULL_YEARS = 5          # gross completions are averaged over this many complete years
PIPE_Q = 4              # quarters in the permitted-not-started context figure
BYGV33_QUARTERS = 48    # quarters to pull — 12 years, enough for the build and the backtest

# BYGV33 BYGFASE codes (see data/raw/dst_BYGV33.meta.json)
PERMITS, STARTED, COMPLETED = "1", "2", "3"
# BOL101 BEBO codes — the variable cannot be eliminated, so "all dwellings" is named
BEBO_ALL = ["1000", "2000", "5000"]
BOL101_USES = ["125", "130", "140", "150", "160", "565", "570"]
COTTAGE = "565"

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
    `data/raw/dst_<TABLE>.meta.json`. Most of these tables are already in the repo's own
    registry, so a byte-identical second copy would be committed for nothing; a copy
    appears here exactly when DST has revised the table since that one was taken, or when
    the table has no committed counterpart at all (the backtest's projection vintage)."""
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


def project_pph(series: list[float]) -> tuple[float, float, bool]:
    """Carry persons-per-household forward `MID_OFFSET` years from its own recent trend.

    `series` is the last TREND_YEARS + 1 observations, oldest first. The trend is the mean
    first difference — (last − first) / TREND_YEARS — and the projection is capped both
    ways: the total move may not exceed ±PPH_CAP of the base value, and the result may not
    fall below PPH_FLOOR. Returns (projected, yearly change, whether a cap bound)."""
    base, step = series[-1], (series[-1] - series[0]) / (len(series) - 1)
    raw = base + step * MID_OFFSET
    capped = min(max(raw, base * (1 - PPH_CAP)), base * (1 + PPH_CAP))
    capped = max(capped, PPH_FLOOR)
    return capped, step, abs(capped - raw) > 1e-12


def stock_window(avail: list[str], base: str) -> tuple[str, int]:
    """The start year of the net-additions window, and its length in years.

    BOL101 publishes no 2021 or 2022 — DST closed both years "due to errors in data from
    the Building and Housing Register" — so the natural `base − 5` start is not always on
    offer. Take the newest published year at or before it and annualise over the span that
    actually separates the two, rather than silently comparing a six-year change with a
    five-year one."""
    target = int(base) - TREND_YEARS
    start = max((y for y in avail if int(y) <= target), default=None)
    if start is None:
        sys.exit(f"BOL101 has no year at or before {target} — the stock window has no start")
    return start, int(base) - int(start)


def net_stock(stock: dict, code: str, base: str, start: str, span: int) -> float:
    """Mean yearly change in the dwelling stock over the window, × TREND_YEARS."""
    return (stock[base][code] - stock[start][code]) / span * TREND_YEARS


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, ties given their average rank. No third-party dependency."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out, i = [0.0] * len(v), 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out
    rx, ry, n = ranks(xs), ranks(ys), len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def fold(rs: list[dict], want: set[str], key=lambda r: r["TID"],
         keep=lambda r: True) -> dict[str, dict[str, int]]:
    """rows → {period: {kommune: Σ INDHOLD}}, over the periods in `want`."""
    out: dict[str, dict[str, int]] = {p: {} for p in want}
    for r in rs:
        k = key(r)
        if k in want and is_kommune(r["OMRÅDE"]) and totals_only(r) and keep(r):
            out[k][r["OMRÅDE"]] = out[k].get(r["OMRÅDE"], 0) + int(r["INDHOLD"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="build from cached CSVs only")
    ap.add_argument("--no-backtest", action="store_true", help="skip the backtest")
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

    # The backtest replays the most recent window that has fully played out: it stands at
    # 1 January `bt_base`, predicts `bt_base`→`bt_mid`, and is scored against the actuals.
    def windows(hh: str) -> tuple[str, str, list[str]]:
        bt_mid = str(int(hh) - 1)
        bt_base = str(int(bt_mid) - MID_OFFSET)
        first = str(int(bt_base) - TREND_YEARS)
        return bt_base, bt_mid, [str(y) for y in range(int(first), int(hh) + 1)]

    def hh_ok(rs):
        nonlocal hh_year
        yrs = {r["TID"] for r in rs if r["TID"].isdigit() and totals_only(r)}
        if hh_year is None:                      # --no-fetch: take whatever the cache holds
            hh_year = max(yrs, default=None)
        return bool(hh_year) and set(windows(hh_year)[2]) <= yrs

    fam, p_fam, how_fam = source(
        "FAM55N", {"OMRÅDE": ["*"], "Tid": windows(hh_year)[2] if hh_year else ["*"]},
        "_hist", hh_ok, today, args.no_fetch)
    bt_base, bt_mid, years = windows(hh_year)
    if hh_year != y_base:
        print(f"  ⚠ FAM55N's latest year is {hh_year}, the projection's base is {y_base} — "
              f"persons_per_hh is read one step away from the population it divides")
    print(f"  FAM55N {years[0]}–{years[-1]} · {how_fam} · {p_fam.name}")

    pph_years = years[-(TREND_YEARS + 1):]       # six observations, the trend's window
    pop_periods = {f"{y}K1" for y in years}      # 1 January of each year
    pop_period = f"{hh_year}K1"
    folk, p_folk, how_folk = source(
        "FOLK1A", {"OMRÅDE": ["*"], "Tid": sorted(pop_periods)},
        "_hist", lambda rs: pop_periods <= {r["TID"] for r in rs if totals_only(r)},
        today, args.no_fetch)
    print(f"  FOLK1A {min(pop_periods)}–{max(pop_periods)} · {how_folk} · {p_folk.name}")

    # BOL101's BEBO cannot be eliminated, so the stock is selected explicitly and a cached
    # pull with another BEBO selection would silently be a different stock — never reuse.
    # BOL101 has no 2021 or 2022 (closed by DST), so the selection is intersected with
    # what the table actually publishes; the years the build cannot do without are the
    # base, the two ends of the backtest window and the start of its trend.
    bol_years = years if args.no_fetch else [y for y in tid_codes("BOL101") if y in years]
    need_stock = {hh_year, bt_base, bt_mid, years[0]}
    bol, p_bol, how_bol = source(
        "BOL101", {"OMRÅDE": ["*"], "BEBO": BEBO_ALL, "ANVENDELSE": BOL101_USES,
                   "Tid": bol_years},
        "_stock",
        lambda rs: need_stock <= periods(rs) and set(BEBO_ALL) <= {r["BEBO"] for r in rs},
        today, args.no_fetch, reuse=False)

    # BYGV33 needs phases 1 and 2 as well, which the repo's cached BYGFASE=3 pull lacks,
    # and it has to reach back far enough for the backtest's own five completion years.
    byg_from = f"{int(bt_base) - FULL_YEARS}K1"
    byg, p_byg, how_byg = source(
        "BYGV33", {"OMRÅDE": ["*"], "BYGFASE": [PERMITS, STARTED, COMPLETED],
                   "Tid": [f"(-n+{BYGV33_QUARTERS})"]},
        "_phases", lambda rs: {PERMITS, STARTED, COMPLETED} <= {r["BYGFASE"] for r in rs}
        and min(periods(rs)) <= byg_from,
        today, args.no_fetch, reuse=False)

    # ---- fold the inputs into per-kommune numbers ----
    households = fold(fam, set(years))                       # household types summed
    population = fold(folk, pop_periods)
    have = {y for y in years if y in periods(bol)}
    stock = fold(bol, have)
    stock_nc = fold(bol, have, keep=lambda r: r["ANVENDELSE"] != COTTAGE)
    avail = sorted(have)
    y_prev, span = stock_window(avail, hh_year)
    print(f"  BOL101 {', '.join(avail)} · {how_bol} · {p_bol.name}\n"
          f"    net additions over {y_prev}–{hh_year}, {span} years, annualised × {TREND_YEARS}"
          + ("" if span == TREND_YEARS else "  (2021 and 2022 are closed by DST)"))

    quarters = sorted(periods(byg))
    by_year = {}
    for q in quarters:
        by_year.setdefault(q[:4], []).append(q)
    complete = sorted(y for y, qs in by_year.items() if len(qs) == 4)
    full = complete[-FULL_YEARS:]
    if len(full) < FULL_YEARS:
        sys.exit(f"BYGV33 has only {len(full)} complete years in the pull — widen BYGV33_QUARTERS")
    pipe_q = quarters[-PIPE_Q:]
    print(f"  BYGV33 {quarters[0]}–{quarters[-1]} · {how_byg} · {p_byg.name}\n"
          f"    gross completions averaged over {full[0]}–{full[-1]}; "
          f"pipeline over {pipe_q[0]}–{pipe_q[-1]}")

    done: dict[str, dict[str, int]] = {}         # code -> year -> dwellings completed
    permits: dict[str, int] = {}
    starts: dict[str, int] = {}
    for r in byg:
        code, q, n = r["OMRÅDE"], r["TID"], int(r["INDHOLD"])
        if not is_kommune(code) or not totals_only(r):
            continue
        if r["BYGFASE"] == COMPLETED and q[:4] in complete:
            d = done.setdefault(code, {y: 0 for y in complete})
            d[q[:4]] += n
        if q in pipe_q and r["BYGFASE"] in (PERMITS, STARTED):
            tgt = permits if r["BYGFASE"] == PERMITS else starts
            tgt[code] = tgt.get(code, 0) + n

    # ---- compute ----
    out, missing = {}, []
    for code in sorted(kom_fc, key=int):
        series = [population[f"{y}K1"].get(code, 0) / households[y][code]
                  for y in pph_years if households.get(y, {}).get(code)]
        if len(series) != len(pph_years) or code not in done \
                or not stock.get(y_prev, {}).get(code) or not stock.get(hh_year, {}).get(code):
            missing.append(code)
            continue
        pph, (pph_mid, step, capped) = series[-1], project_pph(series)
        p0, p1 = kom_fc[code][y_base]["total"], kom_fc[code][y_mid]["total"]
        hh0, hh1 = p0 / pph, p1 / pph_mid
        demand = hh1 - hh0
        demand_const = (p1 - p0) / pph
        supply = net_stock(stock, code, hh_year, y_prev, span)
        supply_nc = net_stock(stock_nc, code, hh_year, y_prev, span)
        supply_gross = sum(done[code][y] for y in full) / FULL_YEARS * FULL_YEARS
        gap = demand - supply
        gap_old = demand_const - supply_gross
        out[code] = {
            "pop": population[pop_period][code], "households": households[hh_year][code],
            "persons_per_hh": round(pph, 4),
            "persons_per_hh_by_year": {y: round(v, 4) for y, v in zip(pph_years, series)},
            "pph_change_per_year": round(step, 5),
            "persons_per_hh_mid": round(pph_mid, 4), "pph_capped": capped,
            "p_base": p0, "p_mid": p1,
            "households_base": round(hh0, 1), "households_mid": round(hh1, 1),
            "demand_5y": round(demand, 1),
            "demand_5y_const": round(demand_const, 1),
            "stock_prev": stock[y_prev][code], "stock_base": stock[hh_year][code],
            "supply_5y": round(supply, 1),
            "supply_5y_excl_cottages": round(supply_nc, 1),
            "supply_5y_gross": round(supply_gross, 1),
            "completions_by_year": {y: done[code][y] for y in full},
            "gap": round(gap, 1),
            "gap_per_1000": round(gap / p0 * 1000, 2),
            "gap_const_gross": round(gap_old, 1),
            "gap_per_1000_const_gross": round(gap_old / p0 * 1000, 2),
            "permits_4q": permits.get(code, 0),
            "starts_4q": starts.get(code, 0),
            "pipeline_permitted": permits.get(code, 0) - starts.get(code, 0),
        }
    if missing:
        sys.exit(f"{len(missing)} kommuner have no household, population, stock or completion "
                 f"figure: {missing[:5]} — a pull is incomplete")

    # Denmark is the Σ of the same 98 municipalities, each computed with its own household
    # size — not a separately averaged national ratio. gap_per_1000_rel is measured
    # against this figure, so the two have to be built the same way.
    def total(f):
        return sum(v[f] for v in out.values())
    dk_p0 = total("p_base")
    nat_per_1000 = (total("demand_5y") - total("supply_5y")) / dk_p0 * 1000
    for v in out.values():
        v["gap_per_1000_rel"] = round(v["gap_per_1000"] - nat_per_1000, 2)
    national = {
        "pop": total("pop"), "households": total("households"),
        "persons_per_hh": round(total("pop") / total("households"), 4),
        "p_base": dk_p0, "p_mid": total("p_mid"),
        "demand_5y": round(total("demand_5y"), 1),
        "demand_5y_const": round(total("demand_5y_const"), 1),
        "supply_5y": round(total("supply_5y"), 1),
        "supply_5y_excl_cottages": round(total("supply_5y_excl_cottages"), 1),
        "supply_5y_gross": round(total("supply_5y_gross"), 1),
        "gap": round(total("demand_5y") - total("supply_5y"), 1),
        "gap_per_1000": round(nat_per_1000, 2),
        "gap_const_gross": round(total("demand_5y_const") - total("supply_5y_gross"), 1),
        "gap_per_1000_const_gross": round(
            (total("demand_5y_const") - total("supply_5y_gross")) / dk_p0 * 1000, 2),
        "pipeline_permitted": total("pipeline_permitted"),
    }

    # ---- backtest: stand at 1 January bt_base, predict bt_base→bt_mid, score it ----
    backtest = None
    if not args.no_backtest:
        backtest = run_backtest(out, households, population, stock, avail, done, complete,
                                bt_base, bt_mid, today, args.no_fetch)

    def updated(table: str) -> str | None:
        for p in (RAW / f"{table}.meta.json", ROOT / "data" / "raw" / f"dst_{table}.meta.json"):
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))["updated"][:10]
        return None

    meta = {
        "built": today,
        "fetched": max(p.stem[-10:] for p in (p_fam, p_folk, p_bol, p_byg)),
        "kommuner": len(out),
        "national": national,
        "projection": {"table": fmeta["table"], "vintage": fmeta["vintage"],
                       "base_year": y_base, "mid_year": y_mid, "horizon_years": MID_OFFSET},
        "tables": {
            "FAM55N": {"what": "households, 1 January", "period": hh_year,
                       "trend_years": pph_years,
                       "updated": updated("FAM55N"), "pull": p_fam.name, "how": how_fam},
            "FOLK1A": {"what": "population, 1 January", "period": pop_period,
                       "trend_periods": [f"{y}K1" for y in pph_years],
                       "updated": updated("FOLK1A"), "pull": p_folk.name, "how": how_folk},
            "BOL101": {"what": "dwelling stock, 1 January, all uses and all resident types",
                       "stock_years": [y_prev, hh_year], "span_years": span,
                       "closed_years": [y for y in years
                                        if int(y_prev) < int(y) < int(hh_year) and y not in avail],
                       "closed_note": "DST publishes no 2021 or 2022 for BOL101 — both years are "
                                      "closed due to errors in the Building and Housing Register, "
                                      "so the net-additions window spans "
                                      f"{span} years and is annualised over that span",
                       "updated": updated("BOL101"), "pull": p_bol.name, "how": how_bol},
            "BYGV33": {"what": "dwellings by phase of construction, quarterly, all uses and "
                               "all builder types — context only",
                       "completions_years": full, "pipeline_quarters": pipe_q,
                       "updated": updated("BYGV33"), "pull": p_byg.name, "how": how_byg},
        },
        "formula": (f"persons_per_hh_mid = persons_per_hh + {MID_OFFSET} × its mean yearly change "
                    f"over {pph_years[0]}–{pph_years[-1]}, total move capped at ±{PPH_CAP:.0%} and "
                    f"never below {PPH_FLOOR}; demand_5y = P_mid / persons_per_hh_mid − "
                    f"P_base / persons_per_hh; supply_5y = mean yearly change in the BOL101 "
                    f"dwelling stock {y_prev}–{hh_year} ({span} years) × {TREND_YEARS}; gap = demand_5y − "
                    "supply_5y; gap_per_1000 = gap / P_base × 1000; gap_per_1000_rel = "
                    "gap_per_1000 − Denmark's own"),
        "variants": ("demand_5y_const holds persons_per_hh at its base-year value (the first "
                     "version of this indicator); supply_5y_gross is BYGV33 completions with no "
                     "demolitions or mergers netted off. gap_const_gross combines the two and is "
                     "kept so the effect of each fix stays visible."),
        "sign": "positive gap = the projection implies more households than the recent change in "
                "the dwelling stock delivers (undersupply); negative = oversupply, including "
                "where the projection shrinks and any net additions are surplus. "
                "gap_per_1000_rel re-centres this on Denmark: positive = tighter than the "
                "country, negative = looser.",
        "pipeline_note": f"pipeline_permitted = permits − starts over {pipe_q[0]}–{pipe_q[-1]}, "
                         "a four-quarter flow difference and not a stock; it is context only "
                         "and enters no other figure. BYGV33 is not adjusted for reporting "
                         "delays, so the most recent quarters are revised upward later.",
        "caveats": "the household-size trend is linear and capped, not modelled; vacancy, second "
                   "homes and tenure are not modelled (supply_5y_excl_cottages is carried as a "
                   "check); BOL101 counts dwellings that exist, not dwellings that are available; "
                   "DST's projection is not housing-driven, so it does not respond to the supply "
                   "side it is compared with. See docs/FORECAST.md §7.",
        "licence": "free reuse with attribution",
        "source": "Danmarks Statistik FOLK1A, FAM55N, BOL101, BYGV33 and "
                  f"{fmeta['table']} ({fmeta['vintage']} municipal population projection)",
        "url": "https://api.statbank.dk/v1/tableinfo/BOL101",
    }
    if backtest:
        meta["backtest"] = backtest["meta"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "kommuner": out}, ensure_ascii=False,
                              separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(out)} kommuner")

    names = kommune_names()
    if backtest:
        report_backtest(backtest, names, args.rank)
    report(out, national, names, y_base, y_mid, args.rank)


def kommune_names() -> dict[str, str]:
    for p in (RAW / "BYGV33.meta.json", ROOT / "data" / "raw" / "dst_BYGV33.meta.json"):
        if p.exists():
            return {x["id"]: x["text"] for v in json.loads(p.read_text())["variables"]
                    if v["id"] == "OMRÅDE" for x in v["values"]}
    return {}


def run_backtest(out, households, population, stock, avail, done, complete, bt_base, bt_mid,
                 today, no_fetch):
    """Replay the formula at 1 January `bt_base` and score it against what happened.

    The population input is the projection vintage that was actually published that year
    (`FRKM1<vv>`), so this is the whole indicator out of sample, not just its arithmetic.
    A second scoring substitutes the realised population for the projection, which
    separates the formula's error from the projection's.

    The truth it is scored against is the same quantity the live indicator predicts:
    actual household growth (FAM55N) minus actual net stock change (BOL101)."""
    vintage = f"FRKM1{bt_base[-2:]}"
    trend = [str(y) for y in range(int(bt_base) - TREND_YEARS, int(bt_base) + 1)]
    old_years = [str(y) for y in range(int(bt_base) - FULL_YEARS, int(bt_base))]
    if not set(old_years) <= set(complete):
        print(f"\n  ⚠ BYGV33 lacks {old_years[0]}–{old_years[-1]} — backtest skipped")
        return None
    try:
        proj, p_proj, how_proj = source(
            vintage, {"OMRÅDE": ["*"], "ALDER": ["TOT"], "Tid": [bt_base, bt_mid]},
            "", lambda rs: {bt_base, bt_mid} <= periods(rs), today, no_fetch, reuse=False)
    except (SystemExit, OSError) as e:  # noqa: BLE001
        print(f"\n  ⚠ {vintage} not available ({e}) — backtest runs on realised population only")
        proj, p_proj, how_proj = [], None, "unavailable"
    projected = {r["OMRÅDE"]: int(r["INDHOLD"]) for r in proj if r["TID"] == bt_mid
                 and is_kommune(r["OMRÅDE"])}

    bt_start, bt_span = stock_window(avail, bt_base)
    rows = {}
    for code in out:
        series = [population[f"{y}K1"][code] / households[y][code] for y in trend]
        pph = series[-1]
        pph_mid, _, _ = project_pph(series)
        p0 = population[f"{bt_base}K1"][code]
        actual_p1 = population[f"{bt_mid}K1"][code]
        supply_new = net_stock(stock, code, bt_base, bt_start, bt_span)
        supply_old = sum(done[code][y] for y in old_years)
        truth = ((households[bt_mid][code] - households[bt_base][code])
                 - (stock[bt_mid][code] - stock[bt_base][code]))
        r = {"actual": truth / p0 * 1000,
             "actual_demand": households[bt_mid][code] - households[bt_base][code],
             "actual_supply": stock[bt_mid][code] - stock[bt_base][code],
             "p_base": p0, "supply_old": supply_old, "supply_new": supply_new,
             "demand_old": (actual_p1 - p0) / pph, "demand_new": actual_p1 / pph_mid - p0 / pph}
        for tag, p1 in (("proj", projected.get(code)), ("real", actual_p1)):
            if p1 is None:
                continue
            d_old, d_new = (p1 - p0) / pph, p1 / pph_mid - p0 / pph
            r[f"old_{tag}"] = (d_old - supply_old) / p0 * 1000
            r[f"new_{tag}"] = (d_new - supply_new) / p0 * 1000
            r[f"mix_demand_{tag}"] = (d_new - supply_old) / p0 * 1000   # new demand only
            r[f"mix_supply_{tag}"] = (d_old - supply_new) / p0 * 1000   # new supply only
        rows[code] = r

    codes = sorted(rows)
    truth = [rows[c]["actual"] for c in codes]
    scores = {}
    for tag, label in (("proj", f"{vintage} projection"), ("real", "realised population")):
        if not all(f"old_{tag}" in rows[c] for c in codes):
            continue
        scores[tag] = {"population_input": label, **{
            k: round(spearman([rows[c][f"{k}_{tag}"] for c in codes], truth), 4)
            for k in ("old", "new", "mix_demand", "mix_supply")}}
    # Why the combined verdict lands where it does: each side scored against its own truth,
    # on ranks and on the size of the miss. The gap is a small difference between two large
    # and nearly equal flows, so a formula can predict both sides better and still rank the
    # residual worse when the old errors happened to cancel.
    def med(v):
        v = sorted(v)
        return (v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2)

    parts = {}
    for side, truth_key, variants in (("demand", "actual_demand", ("demand_old", "demand_new")),
                                      ("supply", "actual_supply", ("supply_old", "supply_new"))):
        t = [rows[c][truth_key] for c in codes]
        parts[side] = {
            v.split("_")[1]: {
                "spearman": round(spearman([rows[c][v] for c in codes], t), 4),
                "median_abs_error_per_1000": round(
                    med([abs(rows[c][v] - rows[c][truth_key]) / rows[c]["p_base"] * 1000
                         for c in codes]), 2),
                "denmark": round(sum(rows[c][v] for c in codes)),
            } for v in variants}
        parts[side]["denmark_actual"] = round(sum(t))

    dk_p0 = sum(rows[c]["p_base"] for c in codes)
    dk = {k: round(sum(rows[c][k] for c in codes) / dk_p0 * 1000, 2)
          for k in ("actual_demand", "actual_supply")}
    dk["actual_gap"] = round(dk["actual_demand"] - dk["actual_supply"], 2)
    spread = sorted(rows[c]["actual"] for c in codes)
    dk["actual_spread"] = [round(spread[0], 2), round(med(spread), 2), round(spread[-1], 2)]
    return {"rows": rows, "codes": codes, "vintage": vintage,
            "meta": {"window": f"{bt_base}→{bt_mid}",
                     "trend_years": trend, "gross_years": old_years,
                     "projection": vintage if projected else None,
                     "how": how_proj, "pull": p_proj.name if p_proj else None,
                     "truth": "actual household growth (FAM55N) − actual net dwelling-stock "
                              "change (BOL101), per 1 000 inhabitants at the base year",
                     "spearman": scores, "components": parts,
                     "denmark_actual_per_1000": dk}}


def report_backtest(bt, names, rank):
    rows, codes, m = bt["rows"], bt["codes"], bt["meta"]
    w = m["window"]
    print(f"\nBacktest {w} — the formula applied to {m['trend_years'][0]}–"
          f"{m['trend_years'][-1]} inputs, scored against what happened")
    print(f"  truth: {m['truth']}")
    for tag, s in m["spearman"].items():
        print(f"\n  Spearman ρ against the actual gap per 1 000, population input = "
              f"{s['population_input']} ({len(codes)} kommuner)")
        print(f"    old  — constant household size, gross completions   ρ = {s['old']:+.3f}")
        print(f"    new  — household-size trend, net stock change       ρ = {s['new']:+.3f}")
        print(f"    …trend demand only, gross completions               ρ = {s['mix_demand']:+.3f}")
        print(f"    …constant size, net stock change only               ρ = {s['mix_supply']:+.3f}")
        d = s["new"] - s["old"]
        verdict = ("the new method ranks municipalities better" if d > 0.02 else
                   "the new method ranks municipalities WORSE — the fix does not pay off here"
                   if d < -0.02 else "the two methods rank municipalities equally well")
        print(f"    → {d:+.3f} — {verdict}")
    lo, mid, hi = m["denmark_actual_per_1000"]["actual_spread"]
    print(f"\n  Each side against its own truth — {w}, realised population, "
          f"{len(codes)} kommuner")
    for side, label in (("demand", "households formed"), ("supply", "net dwellings added")):
        c = m["components"][side]
        old, new = ("old", "new")
        print(f"    {label:<20} ρ  old {c[old]['spearman']:+.3f} → new {c[new]['spearman']:+.3f}"
              f"   median miss per 1 000  {c[old]['median_abs_error_per_1000']:.2f} → "
              f"{c[new]['median_abs_error_per_1000']:.2f}"
              f"   Denmark {c[old]['denmark']:+,} / {c[new]['denmark']:+,} vs "
              f"{c['denmark_actual']:+,} actual".replace(",", " "))
    print(f"    the gap is the difference of the two, and Denmark's actual gap is only "
          f"{m['denmark_actual_per_1000']['actual_gap']:+.2f} per 1 000 "
          f"(kommuner span {lo:+.1f} … {mid:+.1f} … {hi:+.1f}) — a small residual between two "
          f"large flows, which is why either formula scores low on it")

    tag = "proj" if "proj" in m["spearman"] else "real"
    print(f"\n  Top {rank} by actual tightness {w} — households formed minus net dwellings added, "
          f"per 1 000; old/new use the {m['spearman'][tag]['population_input']}\n"
          f"  {'':3} {'':22} {'actual':>7} {'hh +':>8} {'stock +':>8} {'old':>7} {'new':>7}")
    for i, c in enumerate(sorted(codes, key=lambda c: -rows[c]["actual"])[:rank], 1):
        r = rows[c]
        print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {r['actual']:>7.2f} "
              f"{r['actual_demand']:>+8,.0f} {r['actual_supply']:>+8,.0f} "
              f"{r[f'old_{tag}']:>+7.1f} {r[f'new_{tag}']:>+7.1f}".replace(",", " "))


def report(out, national, names, y_base, y_mid, rank):
    pos = sum(1 for v in out.values() if v["gap"] > 0)
    print(f"\nDenmark {y_base}→{y_mid}".replace(",", " "))
    print(f"  demand   trend household size {national['demand_5y']:>10,.0f}   "
          f"constant {national['demand_5y_const']:>10,.0f}   "
          f"({national['demand_5y'] - national['demand_5y_const']:+,.0f})".replace(",", " "))
    print(f"  supply   net stock change     {national['supply_5y']:>10,.0f}   "
          f"gross    {national['supply_5y_gross']:>10,.0f}   "
          f"({national['supply_5y'] - national['supply_5y_gross']:+,.0f})".replace(",", " "))
    print(f"  gap      new                  {national['gap']:>+10,.0f}   "
          f"old      {national['gap_const_gross']:>+10,.0f}   "
          f"→ {national['gap_per_1000']:+.2f} per 1 000 "
          f"(was {national['gap_per_1000_const_gross']:+.2f})".replace(",", " "))
    print(f"  {pos} of {len(out)} kommuner undersupplied (was "
          f"{sum(1 for v in out.values() if v['gap_const_gross'] > 0)})")

    rk = sorted((v["gap_per_1000_rel"], c) for c, v in out.items())
    hdr = (f"\ngap vs Denmark, per 1 000 inhabitants · {y_base}→{y_mid} · positive = tighter "
           f"than the country · {len(rk)} kommuner\n"
           f"  {'':3} {'':22} {'vs DK':>6} {'gap/1k':>7} {'gap':>8} {'demand':>8} "
           f"{'(const)':>8} {'supply':>8} {'(gross)':>8} {'p/hh':>11} {'pipe':>7}")

    def show(rows, title, first):
        print(hdr if first else "")
        print(title)
        for i, (v, c) in enumerate(rows, 1):
            r = out[c]
            print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {v:>+6.1f} {r['gap_per_1000']:>7.2f} "
                  f"{r['gap']:>8,.0f} {r['demand_5y']:>8,.0f} {r['demand_5y_const']:>8,.0f} "
                  f"{r['supply_5y']:>8,.0f} {r['supply_5y_gross']:>8,.0f} "
                  f"{r['persons_per_hh']:>5.2f}→{r['persons_per_hh_mid']:<5.2f} "
                  f"{r['pipeline_permitted']:>+7,}".replace(",", " "))
    show(rk[::-1][:rank], f"Highest {rank} — tightest against the country", True)
    show(rk[:rank], f"Lowest {rank} — loosest against the country", False)


if __name__ == "__main__":
    main()
