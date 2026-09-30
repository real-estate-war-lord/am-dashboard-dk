#!/usr/bin/env python3
"""Build data/processed/forecast.json — Statistics Denmark's municipal population
projection, aggregated into the age groups the Outlook view shows.

The projection tables carry their vintage in the table id (FRKM1 + '26' = the 2026
vintage) and DST replaces them every spring rather than keeping a history, so the id
is resolved from the live catalogue on every run — never hard-coded. See
docs/FORECAST_SOURCES.md §1.1.

Inputs  (fetched unless --no-fetch)
  api.statbank.dk/v1/tables                catalogue → latest FRKM1xx and FRDK1xx
  api.statbank.dk/v1/tableinfo/<table>     variables, codes, `updated`
  api.statbank.dk/v1/data                  the projection itself, and FOLK1A by age
                                           for the observed years before it

Raw pulls (gitignored, re-downloadable)
  data/raw/forecast/dst/<TABLE>[_<sex>]_<YYYY-MM-DD>.csv   semicolon CSV, value CODES
  data/raw/forecast/dst/<TABLE>.meta.json                  tableinfo
  data/raw/forecast/dst/FOLK1A_ages_<YYYY-MM-DD>.csv       the observed age detail

Output
  data/processed/forecast.json
    {"meta": {...},
     "kommuner": {"<code>": {"<year>": {"total": n, "a0_5": n, ... "a80p": n}}},
     "observed": {"<code>": {"<year>": {"total": n, "a0_5": n, ... "a80p": n}}},
     "national": {"<year>": n}}

`observed` is the measured counterpart of `kommuner`, in the same seven groups: FOLK1A's
1 January (Q1) cell per year, folded by the same `age_bucket`. It is what an age-band chart
draws solid before the dashed projection starts, so the two are comparable by construction,
and they meet: the projection's first year *is* an observed year, published by both tables
and rounded by both, so they agree to `meta.join_gap` persons (1 on the 2026 vintage). Still
two series, never spliced into one (§4).

Notes
  · Christiansø (411) is excluded — it is in KOMMUNEDK but is not a municipality, so the
    98 kommuner sum to the national total without it. The app's own municipality list has
    99 entries; 411 simply carries no Outlook value.
  · FRKM126 has no both-sexes code, so M and K are pulled as two requests and summed
    here. One request naming both would be 299,880 cells, but the API's pre-flight
    counter scores that selection at 1,499,400 and rejects it against the 1,000,000-cell
    CSV cap; per sex it is 149,940 and passes. Keeping the two pulls separate also leaves
    the sex dimension in the raw files for later use.

`indicators()` derives the seven Outlook values from that file. It lives here rather than in
build_makro.py so Phase B has one definition to import instead of a second implementation;
the registry entries are in config/indicators.json under the top-level `forecast` key.

Usage
  python scripts/build_forecast.py                    # fetch + build
  python scripts/build_forecast.py --no-fetch         # rebuild from the newest cached CSV
  python scripts/build_forecast.py --years 20         # a longer window (may need BULK)
  python scripts/build_forecast.py --indicators       # print the derived Outlook values
  python scripts/build_forecast.py --indicators fc_20_34_rel --top 10
"""
import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "forecast" / "dst"
OUT = ROOT / "data" / "processed" / "forecast.json"
CFG = ROOT / "config" / "indicators.json"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

# The observed population, by single year of age. The same table build_makro.py reads for
# `pop_hist`, so the solid part of an age-band chart and the solid part of a total-population
# chart come from one source and one period (1 January, i.e. Q1).
ACTUALS = "FOLK1A"
ACTUALS_TAG = "_ages"
Q1 = "K1"
CELL_CAP = 1_000_000     # the API's pre-flight limit for a CSV selection

# Christiansø: in KOMMUNEDK, not a municipality.
EXCLUDE = {"411"}
# Contiguous and exhaustive over 0..100+, so the groups re-sum to the total.
GROUPS = [("a0_5", 0, 5), ("a6_16", 6, 16), ("a17_19", 17, 19), ("a20_34", 20, 34),
          ("a35_64", 35, 64), ("a65_79", 65, 79), ("a80p", 80, 999)]


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r)


def post_csv(body: dict) -> str:
    req = urllib.request.Request(f"{API}/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read().decode("utf-8-sig")


def resolve(prefix: str) -> tuple[str, int]:
    """Latest vintage of a projection table family, e.g. 'FRKM1' -> ('FRKM126', 2026).

    The catalogue normally holds a single vintage; take the highest anyway so a year in
    which DST leaves the old one up still resolves forward.
    """
    pat = re.compile(rf"^{prefix}(\d{{2}})$")
    hits = []
    for t in get(f"{API}/tables?lang=en&format=JSON"):
        m = pat.match(t["id"])
        if m:
            vv = int(m.group(1))
            hits.append((2000 + vv if vv < 70 else 1900 + vv, t["id"]))
    if not hits:
        sys.exit(f"no table matching {prefix}xx in the StatBank catalogue — has DST renamed the family?")
    year, table = max(hits)
    return table, year


def age_bucket(code: str) -> str | None:
    """'0'..'125' -> the group holding that age; '100-' -> a80p; a total code -> None.

    The total code is spelled differently per table — 'TOT' in FRKM/KKFR/KKBEF1, 'IALT' in
    FOLK1A — so anything that is not a number is a total rather than an age.
    """
    digits = code.rstrip("-")
    if not digits.isdigit():
        return None
    n = int(digits)
    for key, lo, hi in GROUPS:
        if lo <= n <= hi:
            return key
    return None


# indicator key -> the field in forecast.json it is derived from. Documentation only —
# the arithmetic lives in indicators(); "growth_5y" uses the mid year, the "_rel" and
# "_abs" pair are a pp difference against Denmark and a person count respectively.
FIELDS = {"fc_growth": "total", "fc_growth_5y": "total", "fc_pop_rate_5y": "total",
          "fc_abs": "total", "fc_0_5": "a0_5", "fc_6_16": "a6_16", "fc_20_34": "a20_34",
          "fc_20_34_rel": "a20_34", "fc_20_34_abs": "a20_34", "fc_80p": "a80p"}

# how --indicators KEY prints a value
UNITS = {"fc_abs": "persons", "fc_20_34_abs": "persons", "fc_20_34_rel": "pp",
         "fc_pop_rate_5y": "persons / 1 000 inh. / yr"}
# keys whose window stops at the mid year rather than the last year of the projection
MID_KEYS = {"fc_growth_5y", "fc_pop_rate_5y"}


def national_pct(kom: dict, field: str, y0: str, y1: str) -> float | None:
    """Denmark's own change in `field`, y0→y1, as Σ of the 98 kommuner in this file.

    Deliberately summed from the same cells the per-kommune percentages come from, so
    fc_20_34_rel is measured against its own aggregate rather than against a separately
    rounded national table. validate_forecast.py check 5 reconciles it with FRDK's
    published age detail — they agree to 0.001 pp.
    """
    a = sum(s[y0][field] for s in kom.values())
    b = sum(s[y1][field] for s in kom.values())
    return None if not a else (b - a) / a * 100


def indicators(doc: dict, mid_offset: int = 5,
               ref: dict | None = None) -> dict[str, dict[str, float | int | None]]:
    """Outlook values per area: {code: {"fc_growth": %, ..., "fc_abs": persons}}.

    Every percentage is the change from the vintage year to the last year of the window,
    except fc_growth_5y and fc_pop_rate_5y, which stop `mid_offset` years in. fc_abs and
    fc_20_34_abs are persons, not rates; fc_20_34_rel is percentage points against the
    baseline; fc_pop_rate_5y is persons per 1 000 inhabitants per year, the unit that makes
    the projection directly readable beside the measured building pace (hist_net_dwell).

    `ref` is the series fc_20_34_rel is measured against — {year: {field: n}}. Left None it
    is Σ of the areas in `doc`, which is the right baseline when they partition the whole:
    the 98 kommuner *are* Denmark. build_cph_forecast.py passes the KK city series instead,
    because its 93 OMRKK codes are four nested levels of one city and summing them would
    count every resident four times.
    """
    kom, meta = doc["kommuner"], doc["meta"]
    y0, y1 = meta["first_year"], meta["last_year"]
    ymid = str(int(y0) + mid_offset)
    # The 20–34 cohort shrinks almost everywhere in this vintage, so the absolute fc_20_34
    # map is nearly uniformly negative and unreadable. fc_20_34_rel re-centres it.
    if ref is None:
        nat_20_34 = national_pct(kom, "a20_34", y0, y1)
    else:
        a, b = ref[y0]["a20_34"], ref[y1]["a20_34"]
        nat_20_34 = None if not a else (b - a) / a * 100
    out = {}
    for code, series in kom.items():
        def raw(field, end):
            a, b = series[end][field], series[y0][field]
            return None if not b else (a - b) / b * 100

        def pct(field, end):
            v = raw(field, end)
            return None if v is None else round(v, 2)

        r20 = raw("a20_34", y1)
        # persons per 1 000 inhabitants per year over the first `mid_offset` years —
        # the same two published cells as fc_growth_5y, divided by the years they span
        # and by the base population instead of being expressed as a percentage.
        p0 = series[y0]["total"]
        rate = None if not p0 or ymid not in series else \
            (series[ymid]["total"] - p0) / mid_offset / p0 * 1000
        out[code] = {
            "fc_growth": pct("total", y1),
            "fc_growth_5y": pct("total", ymid) if ymid in series else None,
            "fc_pop_rate_5y": None if rate is None else round(rate, 2),
            "fc_abs": series[y1]["total"] - series[y0]["total"],
            "fc_0_5": pct("a0_5", y1),
            "fc_6_16": pct("a6_16", y1),
            "fc_20_34": pct("a20_34", y1),
            "fc_20_34_rel": None if r20 is None or nat_20_34 is None else round(r20 - nat_20_34, 2),
            "fc_20_34_abs": series[y1]["a20_34"] - series[y0]["a20_34"],
            "fc_80p": pct("a80p", y1),
        }
    return out


def newest_raw(table: str, tag: str = "") -> pathlib.Path:
    files = sorted(RAW.glob(f"{table}{tag}_20*.csv"))
    if not files:
        sys.exit(f"no cached pull for {table}{tag} in {RAW} — run without --no-fetch")
    return files[-1]


def fetch(table: str, variables: dict, today: str, tag: str = "") -> pathlib.Path:
    info = get(f"{API}/tableinfo/{table}?lang=en&format=JSON")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{table}.meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    body = {"table": table, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
            "valuePresentation": "Code",
            # a variable left out of `variables` is eliminated, i.e. the API returns its total
            "variables": [{"code": k, "values": v} for k, v in variables.items()]}
    text = post_csv(body)
    if text.lstrip().startswith("{"):
        sys.exit(f"{table}: API returned an error instead of CSV:\n{text[:400]}")
    p = RAW / f"{table}{tag}_{today}.csv"
    p.write_text(text, encoding="utf-8")
    return p


def hist_years_default() -> int:
    """`history_years` from config/indicators.json — the window the observed series on an
    area page already shows, so the age bands cover exactly the same years. Falls back to
    11 if the config cannot be read; this script is otherwise config-free."""
    try:
        return int(json.loads(CFG.read_text(encoding="utf-8")).get("history_years", 11))
    except Exception:                                        # noqa: BLE001
        return 11


def q1_periods(codes: list[str], n: int) -> list[str]:
    """The newest `n` 1-January periods of a quarterly Tid list: ['2016K1', … '2026K1'].

    Read from the table's own codes, never generated — a year DST has not published yet
    must not end up in the selection.
    """
    q1 = [c for c in codes if c.endswith(Q1)]
    return q1[-n:] if n else q1


def age_bands(path: pathlib.Path, area_var: str, periods: list[str],
              keep=lambda code: True) -> tuple[dict, int]:
    """A by-age pull -> ({code: {year: {total, a0_5, …}}}, the worst group-vs-total gap).

    `total` is the publisher's own age-total cell, exactly as `aggregate()` keeps it for the
    projection; the groups are summed from the single-year cells, so they re-sum to within a
    rounding crumb of it rather than exactly. A large gap means an unmapped age code.
    """
    want = set(periods)
    out: dict[str, dict[str, dict[str, int]]] = {}
    checksum: dict[tuple[str, str], int] = {}
    for r in rows(path):
        code, period = str(r[area_var]).strip(), r["TID"]
        if period not in want or not keep(code):
            continue
        year = period[:4]
        n = int(r["INDHOLD"])
        slot = out.setdefault(code, {}).setdefault(year, {k: 0 for k, _, _ in GROUPS})
        g = age_bucket(r["ALDER"])
        if g is None:
            slot["total"] = n
        else:
            slot[g] += n
            checksum[(code, year)] = checksum.get((code, year), 0) + n
    missing = [(c, y) for c in out for y in out[c] if "total" not in out[c][y]]
    if missing:
        sys.exit(f"{len(missing)} area-years have no age-total cell, e.g. {missing[:3]} "
                 f"— the {path.name} pull is incomplete")
    gaps = {k: abs(v - out[k[0]][k[1]]["total"]) for k, v in checksum.items()}
    worst, gap = max(gaps.items(), key=lambda kv: kv[1]) if gaps else ((None, None), 0)
    rel = gap / max(1, out[worst[0]][worst[1]]["total"]) if worst[0] else 0
    if gap > 100 and rel > 0.001:
        sys.exit(f"observed age groups miss the age total by {gap} ({rel:.2%}) at {worst} "
                 f"— an age code is unmapped")
    for c in out:
        for y in out[c]:
            out[c][y] = {"total": out[c][y]["total"],
                         **{k: out[c][y][k] for k, _, _ in GROUPS}}
    return out, gap


def kommune_names(table: str) -> dict[str, str]:
    """code -> name, from the cached tableinfo (English labels)."""
    p = RAW / f"{table}.meta.json"
    if not p.exists():
        return {}
    info = json.loads(p.read_text())
    return {x["id"]: x["text"] for v in info["variables"] if v["id"] == "KOMMUNEDK" for x in v["values"]}


def rows(path: pathlib.Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter=";")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="rebuild from the newest cached CSV")
    ap.add_argument("--years", type=int, default=15, help="length of the window, first year included")
    ap.add_argument("--hist-years", type=int, default=hist_years_default(),
                    help="observed years of age detail to pull (default: config history_years)")
    ap.add_argument("--indicators", nargs="?", const="", metavar="KEY",
                    help="print the derived Outlook values instead of rebuilding; "
                         "with a key, rank the kommuner by it")
    ap.add_argument("--top", type=int, default=10, help="rows at each end of --indicators KEY")
    args = ap.parse_args()

    if args.indicators is not None:
        if not OUT.exists():
            sys.exit(f"{OUT.relative_to(ROOT)} not found — build it first")
        doc = json.loads(OUT.read_text())
        vals = indicators(doc)
        names = kommune_names(doc["meta"]["table"])
        y0, y1 = doc["meta"]["first_year"], doc["meta"]["last_year"]
        if not args.indicators:
            print(json.dumps(vals, ensure_ascii=False, indent=1))
            return
        key = args.indicators
        known = sorted(next(iter(vals.values())))
        if key not in known:
            sys.exit(f"unknown key {key!r} — one of {', '.join(known)}")
        rank = sorted((v[key], c) for c, v in vals.items() if v.get(key) is not None)
        unit = UNITS.get(key, "%")
        # the 20–34 keys are about the cohort, so show the cohort rather than the headcount
        field = FIELDS.get(key, "total")
        # the 5-year keys stop at the mid year — print the cells they actually compare
        y_end = str(int(y0) + 5) if key in MID_KEYS else y1
        nat = national_pct(doc["kommuner"], "a20_34", y0, y1)
        head = f"{key} · {y0}→{y_end} · {len(rank)} kommuner · {unit}"
        if key == "fc_20_34_rel":
            head += f" vs Denmark {nat:+.2f} %"
        print(head + "\n")

        def show(rows, title):
            print(title)
            for i, (v, c) in enumerate(rows, 1):
                a, b = doc["kommuner"][c][y0][field], doc["kommuner"][c][y_end][field]
                fmt = f"{v:+,.0f}" if unit == "persons" else f"{v:+.1f} {unit}"
                print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {fmt:>11}   "
                      f"{field} {a:>9,} → {b:>9,}".replace(",", " "))
        hi, lo = ("Largest gains", "Largest losses") if unit == "persons" else ("Top", "Bottom")
        show(rank[::-1][:args.top], f"{hi} {args.top}")
        print()
        show(rank[:args.top], f"{lo} {args.top}")
        return
    today = dt.date.today().isoformat()

    frkm, vintage = resolve("FRKM1")
    frdk, vintage_dk = resolve("FRDK1")
    if vintage_dk != vintage:
        print(f"! {frkm} is the {vintage} vintage but {frdk} is {vintage_dk} — reconciliation will not hold",
              file=sys.stderr)
    years = [str(y) for y in range(vintage, vintage + args.years)]
    print(f"→ {frkm} (vintage {vintage}) · {frdk} · {years[0]}–{years[-1]}")

    if args.no_fetch:
        info = json.loads((RAW / f"{frkm}.meta.json").read_text())
        sexes = [x["id"] for v in info["variables"] if v["id"] == "KØN" for x in v["values"]]
        p_sex = {s: newest_raw(frkm, f"_{s}") for s in sexes}
        p_frdk = newest_raw(frdk)
        p_obs = newest_raw(ACTUALS, ACTUALS_TAG)
        obs_periods = q1_periods(sorted({r["TID"] for r in rows(p_obs)}), args.hist_years)
        print("  cached " + " · ".join(p.name for p in [*p_sex.values(), p_frdk, p_obs]))
    else:
        info = get(f"{API}/tableinfo/{frkm}?lang=en&format=JSON")
        codes = {v["id"]: [x["id"] for x in v["values"]] for v in info["variables"]}
        missing = [y for y in years if y not in codes["Tid"]]
        if missing:
            sys.exit(f"{frkm} does not reach {missing[-1]} (last year {codes['Tid'][-1]})")
        komm = [c for c in codes["KOMMUNEDK"] if c not in EXCLUDE]
        sexes = codes["KØN"]
        cells = len(komm) * len(codes["ALDER"]) * len(years)
        print(f"  {len(komm)} kommuner × {len(codes['ALDER'])} ages × {len(years)} years "
              f"= {cells:,} cells per sex, {len(sexes)} pulls".replace(",", " "))
        if cells > 1_000_000:
            sys.exit("over the 1,000,000-cell CSV cap — shorten --years or switch this pull to BULK")
        p_sex = {s: fetch(frkm, {"KOMMUNEDK": komm, "ALDER": ["*"], "KØN": [s], "Tid": years},
                          today, f"_{s}") for s in sexes}
        # every other variable eliminated → the national total
        p_frdk = fetch(frdk, {"Tid": years}, today)
        # The observed years, by single year of age, so an age-band chart has a measured
        # series to draw before the projection starts. Only the 1 January cells: `pop_hist`
        # is a Q1 series, and mixing quarters into a yearly line would invent a trend.
        # KØN and CIVILSTAND are named explicitly rather than eliminated — the API's
        # pre-flight counter scores an eliminated variable at its full value list and would
        # reject the selection against the 1,000,000-cell cap.
        a_info = get(f"{API}/tableinfo/{ACTUALS}?lang=en&format=JSON")
        a_codes = {v["id"]: [x["id"] for x in v["values"]] for v in a_info["variables"]}
        obs_periods = q1_periods(a_codes["Tid"], args.hist_years)
        if not obs_periods:
            sys.exit(f"{ACTUALS} has no Q1 period — has DST changed its time codes?")
        a_cells = len(a_codes["OMRÅDE"]) * len(a_codes["ALDER"]) * len(obs_periods)
        print(f"  {ACTUALS} {obs_periods[0][:4]}–{obs_periods[-1][:4]} · "
              f"{len(a_codes['OMRÅDE'])} areas × {len(a_codes['ALDER'])} ages × "
              f"{len(obs_periods)} years = {a_cells:,} cells".replace(",", " "))
        if a_cells > CELL_CAP:
            sys.exit(f"the {ACTUALS} pull is over the {CELL_CAP:,} cell cap — "
                     "shorten --hist-years".replace(",", " "))
        p_obs = fetch(ACTUALS, {"OMRÅDE": ["*"], "KØN": ["TOT"], "ALDER": ["*"],
                                "CIVILSTAND": ["TOT"], "Tid": obs_periods},
                      today, ACTUALS_TAG)

    # ---- aggregate: sum the sexes, fold single-year ages into the groups ----
    kom: dict[str, dict[str, dict[str, int]]] = {}
    checksum: dict[tuple[str, str], int] = {}
    seen_sex: dict[tuple[str, str], set] = {}
    for sex, path in p_sex.items():
        for r in rows(path):
            code, age, year = r["KOMMUNEDK"], r["ALDER"], r["TID"]
            if code in EXCLUDE or year not in years:
                continue
            n = int(r["INDHOLD"])
            slot = kom.setdefault(code, {}).setdefault(year, {k: 0 for k, _, _ in GROUPS})
            if age == "TOT":
                slot["total"] = slot.get("total", 0) + n
                seen_sex.setdefault((code, year), set()).add(sex)
            else:
                slot[age_bucket(age)] += n
                checksum[(code, year)] = checksum.get((code, year), 0) + n

    short = [k for k, v in seen_sex.items() if len(v) != len(p_sex)]
    if short:
        sys.exit(f"{len(short)} kommune-years are missing a sex, e.g. {short[:3]} — a pull is incomplete")

    # `total` is DST's own ALDER=TOT cell, so it reproduces the StatBank figure exactly.
    # The single-year cells are rounded independently, so the age groups re-sum to within a
    # few dozen persons of it rather than exactly — real, published, and far below anything
    # the Outlook indicators can see. A large gap would mean a dropped age code, so guard it.
    gaps = {(c, y): abs(v - kom[c][y]["total"]) for (c, y), v in checksum.items()}
    worst, gap = max(gaps.items(), key=lambda kv: kv[1])
    rel = gap / max(1, kom[worst[0]][worst[1]]["total"])
    if gap > 100 and rel > 0.001:
        sys.exit(f"age groups miss ALDER=TOT by {gap} ({rel:.2%}) at {worst} — an age code is unmapped")

    # ---- the measured series: the same seven groups, the observed years ----
    # Only the municipalities: FOLK1A's OMRÅDE also carries the country ('000') and the five
    # regions, which no area page reads. Christiansø is kept here — it has an observed
    # population even though it has no projection — so `pop_hist` and its age split cover
    # the same 99 areas.
    observed, obs_gap = age_bands(p_obs, "OMRÅDE", obs_periods,
                                  keep=lambda c: c.isdigit() and int(c) >= 101)
    obs_years = sorted({p[:4] for p in obs_periods})
    # The projection's first year is an observed year, published by both tables, so the two
    # series meet at one point rather than being stitched across a gap. Prove it rather than
    # assume it. The two tables round independently, so a person or two apart is ordinary and
    # is recorded rather than flagged; a real gap would mean the vintages have drifted apart.
    joins = [(c, kom[c][years[0]][g] - observed[c][years[0]][g])
             for c in kom if years[0] in observed.get(c, {})
             for g in ("total", *(k for k, _, _ in GROUPS))]
    join_gap = max((abs(d) for _, d in joins), default=0)
    if join_gap > 10:
        off = sorted({c for c, d in joins if abs(d) > 10})
        print(f"  ⚠ {frkm} and {ACTUALS} disagree by up to {join_gap} persons in {years[0]} "
              f"({len(off)} kommuner, e.g. {off[:3]}) — the observed line will not meet the "
              f"projection", file=sys.stderr)

    national = {}
    for r in rows(p_frdk):
        if r["TID"] in years:
            national[r["TID"]] = int(r["INDHOLD"])

    for code in kom:
        for year in kom[code]:
            kom[code][year] = {"total": kom[code][year]["total"],
                               **{k: kom[code][year][k] for k, _, _ in GROUPS}}

    meta = {
        "table": frkm, "national_table": frdk, "vintage": vintage,
        "updated": json.loads((RAW / f"{frkm}.meta.json").read_text())["updated"][:10]
        if (RAW / f"{frkm}.meta.json").exists() else None,
        "fetched": next(iter(p_sex.values())).name.rsplit("_", 1)[1][:-4],
        "built": today,
        "years": years,
        "first_year": years[0], "last_year": years[-1],
        "groups": {k: (f"{lo}+" if hi > 900 else f"{lo}–{hi}") for k, lo, hi in GROUPS},
        "actual_table": ACTUALS,
        "observed_years": obs_years,
        "observed_period": "Q1 (1 January), the same cell pop_hist reads",
        "observed_note": f"`observed` is {ACTUALS}'s measured population in the same seven "
                         f"age groups, {obs_years[0]}–{obs_years[-1]}. It is the solid half of "
                         "an age-band chart; the projection is the dashed half. They meet at "
                         f"{years[0]}, which both tables publish, and are never spliced into "
                         "one series (docs/FORECAST.md §4, §5.6).",
        "max_observed_group_gap": obs_gap,
        "join_gap": join_gap,
        "join_note": f"At {years[0]} the projection's base year and {ACTUALS}'s observed cell "
                     f"are the same population, published twice and rounded twice: they agree "
                     f"to within {join_gap} person(s) over every municipality and age group, "
                     "which is why an observed line and a projected line meet at that year "
                     "instead of jumping.",
        "kommuner": len(kom),
        "excluded": sorted(EXCLUDE),
        "max_group_gap": gap,
        "group_gap_note": "DST rounds each cell independently, so the age groups re-sum to "
                          f"within {gap} persons of the published ALDER=TOT, which is what `total` holds",
        "licence": "free reuse with attribution",
        "source": f"Danmarks Statistik {frkm} (municipal population projection {vintage}), "
                  f"national control total {frdk}",
        "url": f"https://api.statbank.dk/v1/tableinfo/{frkm}",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "kommuner": kom, "observed": observed,
                               "national": national},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dev = max(abs(sum(kom[c][y]["total"] for c in kom) / national[y] - 1) for y in years) * 100
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(kom)} kommuner × {len(years)} years "
          f"· max deviation vs {frdk}: {dev:.3f} % · age groups within {gap} of ALDER=TOT")
    print(f"  observed {ACTUALS} {obs_years[0]}–{obs_years[-1]} · {len(observed)} areas "
          f"· age groups within {obs_gap} of the published age total")


if __name__ == "__main__":
    main()
