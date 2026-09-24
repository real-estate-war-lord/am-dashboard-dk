#!/usr/bin/env python3
"""Build data/processed/cph_forecast.json — Københavns Kommune's own population
projection, at kvarter level, aggregated into the age groups the Outlook view shows.

This is the Copenhagen counterpart of scripts/build_forecast.py, and it obeys the same
hard-data rule (docs/FORECAST.md §0): every value is either a published KKFR cell or plain
arithmetic on published KKFR cells. The indicators are computed by `indicators()` imported
from build_forecast.py — one definition of the arithmetic for both geographies, so a
kvarter figure and a municipal figure can never drift apart in how they are derived.

🚫 **The splicing rule still holds** (docs/FORECAST.md §4). KKFR is a different run from
DST's FRKM with different assumptions, and by 2040 it is ~16 000 people above DST for the
same city. Never mix the two in one series, never let a kvarter figure roll up into a DST
municipal figure. The municipal choropleth uses DST for all 98 kommuner *including*
Copenhagen; this file drives the Copenhagen drill-down and nothing else. Check 9 in
validate_forecast.py prints the gap per year so it stays visible rather than implicit.

`fc_20_34_rel` here is measured against **the KK city total (OMRKK 1000)**, not Denmark —
`indicators()` takes the baseline series as `ref` for exactly this reason. It must be
labelled "vs København", or it will be read as the national comparison it is not.

The table id carries the vintage (`KKFR` + `2026`) and KK replaces the table each March
rather than keeping a history, so the id is resolved from the live s30 catalogue on every
run — never hard-coded. See docs/FORECAST_SOURCES.md §2.1.

Geography. `OMRKK` holds four nested levels at once — the city (`1000`), 10 bydele
(`1001`–`1010`), 12 lokaludvalg (`2001`–`2012`) and 67 kvarterer (`2LLxx`) — plus one
"Uden for inddeling" bucket per level (`1099`, `2099`, `29999`, ~3 700 people, 0.55 % of
the city). **The buckets are kept in this file** — without them the levels do not re-sum to
the city total — **but they are not map areas**; `meta.levels.unallocated` names them so a
consumer can skip them. The code list is byte-identical to `KKBEF1`'s, which the v1.2
kvarter layer (`scripts/build_cph.py`, `data/geo/cph_kvarterer.geojson`) already keys on,
so no crosswalk is needed anywhere. The kvarter → lokaludvalg step is the code structure
itself (`2LLxx` → `20LL`); the lokaludvalg → bydel step reuses `LOK2BYDEL` from
`build_cph.py` rather than restating it, and check 9 proves the mapping by summing.

Inputs  (fetched unless --no-fetch)
  api.statbank.dk/v1/s30/tables                catalogue → latest KKFRxxxx
  api.statbank.dk/v1/s30/tableinfo/<table>     variables, codes, `updated`
  api.statbank.dk/v1/s30/data                  the projection itself

Raw pulls (gitignored, re-downloadable)
  data/raw/forecast/cph/<TABLE>_dist_age[_<from>-<to>]_<YYYY-MM-DD>.csv
  data/raw/forecast/cph/<TABLE>.meta.json

Output
  data/processed/cph_forecast.json
    {"meta": {...},
     "omrkk": {"<code>": {"<year>": {"total": n, "a0_5": n, ... "a80p": n}}},
     "indicators": {"<code>": {"fc_growth": …, "fc_20_34_rel": …}},
     "names": {"<code>": "…"}}

Usage
  python scripts/build_cph_forecast.py                  # resolve vintage, pull, build
  python scripts/build_cph_forecast.py --no-fetch       # rebuild from the newest cached CSV
  python scripts/build_cph_forecast.py --years 20       # a longer window
  python scripts/build_cph_forecast.py --rank 10        # the kvarter rankings
  python scripts/build_cph_forecast.py --rank 0         # build quietly, no rankings
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from build_forecast import GROUPS, age_bucket, indicators  # noqa: E402
from build_cph import LOK2BYDEL  # noqa: E402  — lokaludvalg → bydel, one definition

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "forecast" / "cph"
OUT = ROOT / "data" / "processed" / "cph_forecast.json"
API = "https://api.statbank.dk/v1"
DB = "s30"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

CITY = "1000"
# ---- how far a sum of districts may miss the published total -----------------------
# KK rounds every published cell independently, so a sum of N of them drifts from the
# published total by a few persons and the drift grows with N. Measured on the 2026
# vintage: Σ 68 kvarterer is within 5 of the city in the worst year (2038), Σ 13
# lokaludvalg within 3, and Σ kvarterer of one bydel within 2. The tolerances are set
# just above those, not at them, so ordinary rounding does not fail a check — and far
# below the smallest kvarter (Metropolzonen, 2 882 people in 2026), so a dropped or
# misparented area still cannot hide inside the slack. Raise these only with a note
# saying why. validate_forecast.py and build_cph_backtest.py import them from here.
TOL_CITY = 10       # Σ all kvarterer (68 cells) vs the published city total
TOL_BYDEL = 5       # Σ the kvarterer of one bydel (≤10 cells) vs that bydel's own value
# One "Uden for inddeling" bucket per level. Kept in the file so each level re-sums to the
# city total; never drawn, because they have no geometry.
UNALLOCATED = {"bydel": "1099", "lokaludvalg": "2099", "kvarter": "29999"}
CELL_CAP = 1_000_000     # the API's pre-flight limit for a CSV selection

# KKFRBEDI — the movement side of the same run. Its name carries no vintage (unlike
# KKFR<YYYY>), so it is named directly; `updated` is checked against the projection's so a
# mismatched pair cannot be built silently. BEVÆGELSE codes, from its own Danish metadata:
MOVES = {"01": "levendefoedte", "02": "doede", "03": "foedselsoverskud",
         "04": "tilflyttede", "05": "fraflyttede", "06": "nettotilflytning"}
NETMIG, MOVED_IN, MOVED_OUT, NAT_INCR = "06", "04", "05", "03"
BEDI = "KKFRBEDI"
NETMIG_5Y = 5            # the short window, in movement years

# ---- when does fc_netmig fail to reconcile with the stock table? -------------------
# Over a window, ΔP should equal (natural increase + net migration). Three things make it
# not exactly equal, and only the third is worth flagging:
#   · per-cell rounding, ±1 per summed cell per year, so it accumulates with the window —
#     hence NETMIG_TOL_YEAR × the number of movement years rather than a flat figure;
#   · a small systematic difference between KKFRBEDI's district totals and the stock
#     table's, about 36 persons a year city-wide (0.006 % of the city) — proportional to
#     size, hence the relative term;
#   · 🚩 KK's district split moving projected population between two adjacent kvarterer
#     without booking it as a move. That one is structural, runs to thousands of persons,
#     and would make fc_netmig read backwards for the affected areas.
# Measured on the 2026 vintage the two populations are far apart — every rounding/residual
# gap is ≤ 26 persons, every structural one ≥ 412 — so the threshold is not delicate.
NETMIG_TOL_YEAR = TOL_BYDEL     # accumulated rounding allowance, per movement year
NETMIG_TOL_REL = 0.01           # …or 1 % of the area's base population, whichever is larger


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r)


def post_csv(body: dict) -> str:
    # the sub-database has its own /data endpoint — /v1/data does not know s30's tables
    req = urllib.request.Request(f"{API}/{DB}/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read().decode("utf-8-sig")


def resolve(prefix: str) -> tuple[str, int]:
    """Latest vintage of the KK projection family, e.g. 'KKFR' -> ('KKFR2026', 2026).

    The four-digit year in the pattern matters: `KKFRBEV` and `KKFRBEDI` share the prefix
    but carry stable names across vintages and are different tables.
    """
    pat = re.compile(rf"^{prefix}(\d{{4}})$")
    hits = [(int(m.group(1)), t["id"])
            for t in get(f"{API}/{DB}/tables?lang=en&format=JSON")
            if (m := pat.match(t["id"]))]
    if not hits:
        sys.exit(f"no table matching {prefix}YYYY in the {DB} catalogue — "
                 f"has Københavns Kommune renamed the family?")
    year, table = max(hits)
    return table, year


def level_of(code: str) -> str:
    if code == CITY:
        return "city"
    if len(code) == 5:
        return "kvarter"
    return "bydel" if code.startswith("1") else "lokaludvalg"


def parents(code: str) -> tuple[str | None, str | None]:
    """(lokaludvalg, bydel) for a kvarter code; (None, None) for anything else.

    `2LLxx` -> lokaludvalg `20LL` is the code structure, not a mapping. The lokaludvalg ->
    bydel step is `LOK2BYDEL` from build_cph.py — the same table the v1.2 kvarter layer
    uses — and the unallocated kvarter rolls into the unallocated lokaludvalg and bydel.
    """
    if level_of(code) != "kvarter":
        return None, None
    if code == UNALLOCATED["kvarter"]:
        return UNALLOCATED["lokaludvalg"], UNALLOCATED["bydel"]
    lok = code[1:3]
    if lok not in LOK2BYDEL:
        sys.exit(f"kvarter {code} has lokaludvalg {lok}, which build_cph.LOK2BYDEL does not "
                 f"know — has Københavns Kommune redistricted?")
    return f"20{lok}", LOK2BYDEL[lok][0]


def tableinfo(table: str) -> dict:
    p = RAW / f"{table}.meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def meta_updated(info: dict) -> str | None:
    return (info.get("updated") or "")[:10] or None


def codes_of(info: dict, var: str) -> list[str]:
    return [x["id"] for v in info["variables"] if v["id"] == var for x in v["values"]]


def names_of(info: dict) -> dict[str, str]:
    return {x["id"]: x["text"].strip() for v in info["variables"] if v["id"] == "OMRKK"
            for x in v["values"]}


def short_name(text: str) -> str:
    """'Indre By - Middelalderbyen' -> 'Middelalderbyen'; leaves one-part labels alone."""
    return text.rsplit(" - ", 1)[-1].strip()


def newest_raw(table: str) -> list[pathlib.Path]:
    """Every chunk of the newest cached pull, oldest year range first.

    Every pull carries its year range in the filename, split or not, so the chunks of one
    run are exactly the files sharing its date. Two runs with different `--years` on the
    same day would still both match; `aggregate()` catches that as a duplicate cell rather
    than silently adding the overlap twice.
    """
    files = sorted(RAW.glob(f"{table}_dist_age_*_20??-??-??.csv"))
    if not files:
        sys.exit(f"no cached pull for {table} in {RAW} — run without --no-fetch")
    newest = files[-1].stem[-10:]
    return sorted(q for q in files if q.stem.endswith(newest))


def fetch(table: str, years: list[str], omrkk: list[str], today: str) -> list[pathlib.Path]:
    """Pull the projection, splitting into year chunks if the selection exceeds the cap."""
    info = get(f"{API}/{DB}/tableinfo/{table}?lang=en&format=JSON")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{table}.meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    # Today's pull replaces today's pull. Without this, re-running with a different window
    # or a different cap leaves yesterday's chunk set beside the new one, and --no-fetch
    # then finds overlapping year ranges (aggregate() refuses them, but only after the fact).
    for stale in RAW.glob(f"{table}_dist_age_*_{today}.csv"):
        stale.unlink()
    ages = codes_of(info, "ALDER")
    per_year = len(omrkk) * len(ages)
    chunk = max(1, CELL_CAP // per_year)
    batches = [years[i:i + chunk] for i in range(0, len(years), chunk)]
    n_cells, cap = f"{per_year * len(years):,}".replace(",", " "), f"{CELL_CAP:,}".replace(",", " ")
    print(f"  {len(omrkk)} districts × {len(ages)} ages × {len(years)} years = {n_cells} cells"
          + (f" — over the {cap} cap, split into {len(batches)} pulls of ≤{chunk} years"
             if len(batches) > 1 else ", one pull"))
    out = []
    for b in batches:
        # the range is always in the name, split or not, so --no-fetch can tell the chunks
        # of one run from a differently-windowed pull taken the same day
        tag = f"_{b[0]}-{b[-1]}"
        body = {"table": table, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                "valuePresentation": "Code",
                # KON=TOT is KK's own published both-sexes cell — nothing is summed here.
                "variables": [{"code": "OMRKK", "values": omrkk},
                              {"code": "KON", "values": ["TOT"]},
                              {"code": "ALDER", "values": ["*"]},
                              {"code": "Tid", "values": b}]}
        text = post_csv(body)
        if text.lstrip().startswith("{"):
            sys.exit(f"{table}: API returned an error instead of CSV:\n{text[:400]}")
        p = RAW / f"{table}_dist_age{tag}_{today}.csv"
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out


def fetch_moves(years: list[str], today: str) -> pathlib.Path:
    """Pull KKFRBEDI: 92 districts × 6 movement types × ALDER=TOT × the window.

    ~7 700 cells, so never split. ALDER here is 5-year bands (`01` = 0–4 … `20` = 95+)
    plus `TOT`, which is the only one this build wants.
    """
    info = get(f"{API}/{DB}/tableinfo/{BEDI}?lang=da&format=JSON")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{BEDI}.meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    for stale in RAW.glob(f"{BEDI}_moves_*_{today}.csv"):
        stale.unlink()
    have = {x["id"] for v in info["variables"] if v["id"] == "Tid" for x in v["values"]}
    use = [y for y in years if y in have]
    text = post_csv({"table": BEDI, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                     "valuePresentation": "Code",
                     "variables": [{"code": "OMRKK", "values": ["*"]},
                                   {"code": "BEVÆGELSE", "values": ["*"]},
                                   {"code": "ALDER", "values": ["TOT"]},
                                   {"code": "Tid", "values": use}]})
    if text.lstrip().startswith("{"):
        sys.exit(f"{BEDI}: API returned an error instead of CSV:\n{text[:400]}")
    p = RAW / f"{BEDI}_moves_{use[0]}-{use[-1]}_{today}.csv"
    p.write_text(text, encoding="utf-8")
    return p


def newest_moves() -> pathlib.Path:
    files = sorted(RAW.glob(f"{BEDI}_moves_*_20??-??-??.csv"))
    if not files:
        sys.exit(f"no cached {BEDI} pull in {RAW} — run without --no-fetch")
    return files[-1]


def read_moves(path: pathlib.Path) -> dict[str, dict[str, dict[str, int]]]:
    """{code: {year: {BEVÆGELSE: n}}} — KKFRBEDI has no city row, by design (see §9)."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["ALDER"] != "TOT":
                continue
            out.setdefault(r["OMRKK"], {}).setdefault(r["TID"], {})[r["BEVÆGELSE"]] = \
                int(r["INDHOLD"])
    return out


def netmig(mv: dict, omrkk: dict, years: list[str], kvarterer: list[str]) -> dict[str, dict]:
    """fc_netmig per code: Σ KKFRBEDI `06 Nettotilflytning` over each window.

    A movement year Y is the flow *during* Y, bridging the 1 January stocks of Y and Y+1,
    so the 2026→2031 window sums movement years 2026…2030 and the 2026→2040 window sums
    2026…2039. Only published cells are added; the per-1 000 figure divides by the base
    year's published population.

    The city has no KKFRBEDI row — at city level the moves between two Copenhagen districts
    cancel and KK publishes that split in KKFRBEV instead — so its value is Σ of the kvarter
    level. That sum is what cancels the internal moves, and `meta` records that it is a sum
    rather than a published cell.

    🚩 **`fc_netmig_reconciles` is not decoration.** The two tables should satisfy
    ΔP = natural increase + net migration over the window, and for 62 of 68 kvarterer they
    do, to a handful of persons. For four they do not, in two adjacent pairs inside one
    bydel each — KK's district split moves projected population between neighbouring
    kvarterer without booking it as a move, so Nordøstamager's stock grows by 10 414 while
    its net migration is −1 053 and neighbouring Amagerbro Øst carries the inflow instead.
    The flag is per code; anything showing fc_netmig must respect it (docs/FORECAST.md §9).
    """
    y0 = years[0]
    win5 = [y for y in years[:NETMIG_5Y] if y in next(iter(mv.values()))]
    win_all = [y for y in years[:-1] if y in next(iter(mv.values()))]
    out = {}
    for code in omrkk:
        src = kvarterer if code == CITY else [code]
        if any(k not in mv for k in src):
            continue
        p0 = omrkk[code][y0]["total"]
        vals = {}
        for key, win in (("fc_netmig_5y", win5), ("fc_netmig", win_all)):
            n = sum(mv[k][y][NETMIG] for k in src for y in win)
            vals[key] = n
            vals[f"{key}_per1000"] = None if not p0 else round(n / p0 * 1000, 1)
        # ΔP over the window vs (natural increase + net migration) from the movement table.
        # win_all's last movement year bridges into the following 1 January stock, so the
        # stock end is win_all[-1] + 1, not win_all[-1].
        moved = sum(mv[k][y][NAT_INCR] + mv[k][y][NETMIG] for k in src for y in win_all)
        stock_end = omrkk[code][str(int(win_all[-1]) + 1)]["total"]
        gap = stock_end - omrkk[code][y0]["total"] - moved
        tol = max(NETMIG_TOL_YEAR * len(win_all), NETMIG_TOL_REL * p0)
        vals["fc_netmig_gap"] = gap
        vals["fc_netmig_gap_per1000"] = None if not p0 else round(gap / p0 * 1000, 1)
        vals["fc_netmig_reconciles"] = abs(gap) <= tol
        out[code] = vals
    return {"values": out, "window_5y": win5, "window_full": win_all}


def rows(paths: list[pathlib.Path]):
    for p in paths:
        with p.open(encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f, delimiter=";")


def aggregate(paths: list[pathlib.Path], years: list[str]) -> tuple[dict, int]:
    """CSV rows -> {code: {year: {total, a0_5, …}}}, and the worst group-vs-TOT gap."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    checksum: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, str]] = set()
    for r in rows(paths):
        code, age, year = r["OMRKK"], r["ALDER"], r["TID"]
        if year not in years:
            continue
        # Two pulls covering overlapping years would add the same people twice, and the
        # result would look plausible. Refuse instead of guessing which file to drop.
        if (code, age, year) in seen:
            sys.exit(f"cell {code}/{age}/{year} appears in more than one of the cached pulls "
                     f"({', '.join(q.name for q in paths)}) — their year ranges overlap; "
                     f"delete the stale ones or re-run without --no-fetch")
        seen.add((code, age, year))
        if r.get("KON") not in (None, "", "TOT"):
            sys.exit(f"the pull carries KON={r['KON']} — summing sexes here would "
                     f"double-count KK's published TOT; re-pull with KON=TOT only")
        n = int(r["INDHOLD"])
        slot = out.setdefault(code, {}).setdefault(year, {k: 0 for k, _, _ in GROUPS})
        if age == "TOT":
            slot["total"] = n
        else:
            # KKFR's ALDER codes are zero-padded ('00'…'98') with '99' as 99+; age_bucket
            # strips the padding via int() and folds 99 into a80p, which is where it belongs.
            slot[age_bucket(age)] += n
            checksum[(code, year)] = checksum.get((code, year), 0) + n

    missing = [(c, y) for c in out for y in years
               if "total" not in out[c].get(y, {})]
    if missing:
        sys.exit(f"{len(missing)} district-years have no ALDER=TOT cell, e.g. {missing[:3]} "
                 f"— a pull is incomplete")
    gaps = {k: abs(v - out[k[0]][k[1]]["total"]) for k, v in checksum.items()}
    worst, gap = max(gaps.items(), key=lambda kv: kv[1])
    rel = gap / max(1, out[worst[0]][worst[1]]["total"])
    if gap > 100 and rel > 0.001:
        sys.exit(f"age groups miss ALDER=TOT by {gap} ({rel:.2%}) at {worst} — "
                 f"an age code is unmapped")
    for c in out:
        for y in out[c]:
            out[c][y] = {"total": out[c][y]["total"],
                         **{k: out[c][y][k] for k, _, _ in GROUPS}}
    return out, gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="rebuild from the newest cached CSV")
    ap.add_argument("--years", type=int, default=15, help="length of the window, first year included")
    ap.add_argument("--rank", type=int, default=10, help="rows at each end of the kvarter rankings")
    args = ap.parse_args()
    today = dt.date.today().isoformat()

    table, vintage = resolve("KKFR")
    years = [str(y) for y in range(vintage, vintage + args.years)]
    print(f"→ {DB}/{table} (vintage {vintage}) · {years[0]}–{years[-1]}")

    if args.no_fetch:
        paths = newest_raw(table)
        info = tableinfo(table)
        if not info:
            sys.exit(f"{RAW / f'{table}.meta.json'} missing — run without --no-fetch")
        print("  cached " + " · ".join(p.name for p in paths))
    else:
        info = get(f"{API}/{DB}/tableinfo/{table}?lang=en&format=JSON")
        short = [y for y in years if y not in codes_of(info, "Tid")]
        if short:
            sys.exit(f"{table} does not reach {short[-1]} "
                     f"(last year {codes_of(info, 'Tid')[-1]})")
        paths = fetch(table, years, codes_of(info, "OMRKK"), today)

    omrkk, gap = aggregate(paths, years)
    names = names_of(info)

    by_level: dict[str, list[str]] = {}
    for c in sorted(omrkk, key=lambda x: (len(x), x)):
        by_level.setdefault(level_of(c), []).append(c)
    counts = {k: len(v) for k, v in by_level.items()}
    if counts.get("kvarter", 0) - 1 != 67 or counts.get("bydel", 0) - 1 != 10:
        print(f"  ⚠ expected 67 kvarterer + 1 bucket and 10 bydele + 1 bucket, got {counts}",
              file=sys.stderr)
    print(f"  {counts} · age groups within {gap} of ALDER=TOT")

    # fc_20_34_rel is measured against the city, not Denmark — the 93 codes are four nested
    # levels of the same city, so their Σ would treble-count and mean nothing.
    vals = indicators({"meta": {"first_year": years[0], "last_year": years[-1]},
                       "kommuner": omrkk}, ref=omrkk[CITY])

    # ---- the build-out signal: net in-migration per district, from the same run ----
    if args.no_fetch:
        p_mv = newest_moves()
        bedi_info = tableinfo(BEDI)
        print(f"  cached {p_mv.name}")
    else:
        p_mv = fetch_moves(years, today)
        bedi_info = tableinfo(BEDI)
    bedi_updated = (bedi_info.get("updated") or "")[:10] or None
    if bedi_updated and meta_updated(info) and bedi_updated != meta_updated(info):
        print(f"  ⚠ {BEDI} was updated {bedi_updated} but {table} {meta_updated(info)} — "
              f"the movement and stock tables may not be the same run", file=sys.stderr)
    mv = read_moves(p_mv)
    nm = netmig(mv, omrkk, years, by_level["kvarter"])
    for code, v in nm["values"].items():
        vals[code].update(v)
    missing_nm = sorted(set(omrkk) - set(nm["values"]))
    print(f"  {BEDI} {nm['window_full'][0]}–{nm['window_full'][-1]} · "
          f"{len(nm['values'])} districts with fc_netmig"
          + (f" · no movement row for {', '.join(missing_nm)}" if missing_nm else ""))

    meta = {
        "table": table, "db": DB, "vintage": vintage,
        "updated": meta_updated(info),
        "fetched": paths[0].stem[-10:], "built": today,
        "years": years, "first_year": years[0], "last_year": years[-1],
        "mid_year": str(vintage + 5),
        "groups": {k: (f"{lo}+" if hi > 900 else f"{lo}–{hi}") for k, lo, hi in GROUPS},
        "max_group_gap": gap,
        "group_gap_note": "KK rounds each cell independently, so the age groups re-sum to "
                          f"within {gap} persons of the published ALDER=TOT, which is what "
                          "`total` holds",
        "sex": "KON=TOT — Københavns Kommune's own published both-sexes cell, not a sum of "
               "the two sexes taken here",
        "levels": {k: v for k, v in by_level.items()},
        "unallocated": UNALLOCATED,
        "unallocated_note": "One 'Uden for inddeling' bucket per level. They are kept here "
                            "because without them the levels do not re-sum to the city "
                            "total (~3 700 people, 0.55 % of the city), but they have no "
                            "geometry and must not be drawn on the map.",
        "hierarchy": {c: {"lokaludvalg": lok, "bydel": byd}
                      for c in by_level.get("kvarter", [])
                      for lok, byd in [parents(c)]},
        "netmig": {
            "table": BEDI, "updated": bedi_updated,
            "movement_code": NETMIG, "movement_label": "Nettotilflytning / Netmigration",
            "window_5y": [nm["window_5y"][0], nm["window_5y"][-1]],
            "window_full": [nm["window_full"][0], nm["window_full"][-1]],
            "keys": ["fc_netmig_5y", "fc_netmig_5y_per1000", "fc_netmig",
                     "fc_netmig_per1000"],
            "definition": "Σ of KKFRBEDI's published `06 Nettotilflytning` over the "
                          "movement years of each window. A movement year Y is the flow "
                          "during Y, bridging the 1 January stocks of Y and Y+1, so the "
                          f"{years[0]}→{str(int(years[0]) + NETMIG_5Y)} window sums "
                          f"{nm['window_5y'][0]}–{nm['window_5y'][-1]} and the "
                          f"{years[0]}→{years[-1]} window sums "
                          f"{nm['window_full'][0]}–{nm['window_full'][-1]}. The per-1 000 "
                          f"figure divides by the published {years[0]} population; it is "
                          "the total over the window, not a yearly rate.",
            "scope": "🔑 At district level KKFRBEDI's Tilflyttede/Fraflyttede count EVERY "
                     "move across the district boundary, INCLUDING moves between two "
                     "Copenhagen districts. Σ districts' in-moves is roughly twice the "
                     "city's own in-moves for that reason. So fc_netmig is net migration "
                     "into the kvarter from anywhere — the rest of Copenhagen included — "
                     "which is exactly what a new development produces. See "
                     "docs/FORECAST.md §9.",
            "city_is_a_sum": "KKFRBEDI publishes no city row (OMRKK 1000 is absent): at "
                             "city level the internal moves cancel and KK publishes that "
                             "split in KKFRBEV instead, with different categories. The "
                             "city figure here is Σ of the kvarter level — summing net "
                             "migration across districts is what cancels the internal "
                             "moves — and is a sum, not a published cell.",
            "no_city_row": CITY not in mv,
        },
        "relative_baseline": CITY,
        "relative_note": "fc_20_34_rel is measured against the KK city total (OMRKK 1000), "
                         "NOT against Denmark — label it 'vs København'. The 93 OMRKK codes "
                         "are four nested levels of one city, so their sum is not a baseline.",
        "splicing_rule": "Københavns Kommune's projection is a different run from DST's "
                         "FRKM and disagrees with it by ~2.2 % on the city total by 2040. "
                         "Never splice the two, and never let a kvarter figure roll up into "
                         "a DST municipal figure. See docs/FORECAST.md §4 and §8.",
        "caveat": "The city total is pure demography — Københavns Kommune excludes housing "
                  "development plans from it by design — but the SPLIT across kvarterer is "
                  "driven by the city's unpublished boligprognose, which KK itself calls "
                  "'behæftet med relativ stor usikkerhed'. A kvarter number is a "
                  "construction schedule in disguise; see docs/FORECAST_SOURCES.md §2.6.",
        "licence": "free reuse with attribution",
        "source": f"Københavns Kommune {table} (Befolkningsfremskrivning {vintage}), "
                  f"via api.statbank.dk/v1/{DB}",
        "url": f"https://api.statbank.dk/v1/{DB}/tableinfo/{table}",
        "attribution": "Københavns Kommune statbank (s30)",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"meta": meta, "omrkk": omrkk, "indicators": vals,
         "names": {c: names.get(c, "") for c in omrkk},
         "short_names": {c: short_name(names.get(c, "")) for c in omrkk}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    city = omrkk[CITY]
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(omrkk)} districts × {len(years)} years "
          f"· city {city[years[0]]['total']:,} → {city[years[-1]]['total']:,} "
          f"({vals[CITY]['fc_growth']:+.1f} %)".replace(",", " "))

    if args.rank:
        report(omrkk, vals, names, by_level["kvarter"], years, args.rank, nm)


def report(omrkk, vals, names, kvarterer, years, n, nm):
    """Top/bottom n kvarterer by fc_growth, fc_abs, fc_20_34_abs and fc_netmig_per1000."""
    y0, y1 = years[0], years[-1]
    drawn = [c for c in kvarterer if c != UNALLOCATED["kvarter"]]
    for key, unit, field, hi, lo in (
            ("fc_growth", "%", "total", "fastest growing", "fastest shrinking"),
            ("fc_abs", "persons", "total", "largest gains", "largest losses"),
            ("fc_20_34_abs", "persons", "a20_34", "largest gains", "largest losses")):
        rank = sorted((vals[c][key], c) for c in drawn if vals[c].get(key) is not None)
        print(f"\n{key} · {y0}→{y1} · {len(rank)} kvarterer · {unit}")
        for title, part in ((hi, rank[::-1][:n]), (lo, rank[:n])):
            print(f"  {title} {n}")
            for i, (v, c) in enumerate(part, 1):
                a, b = omrkk[c][y0][field], omrkk[c][y1][field]
                fmt = f"{v:+,.0f}" if unit == "persons" else f"{v:+.1f} %"
                print(f"   {i:>2}. {c} {names.get(c, ''):<38} {fmt:>9}   "
                      f"{field} {a:>7,} → {b:>7,}".replace(",", " "))

    w = nm["window_full"]
    rank = sorted((vals[c]["fc_netmig_per1000"], c) for c in drawn
                  if vals[c].get("fc_netmig_per1000") is not None)
    print(f"\nfc_netmig_per1000 · movement years {w[0]}–{w[-1]} · {len(rank)} kvarterer "
          f"· net in-migration per 1 000 inhabitants of {y0}, over the whole window")
    for title, part in (("largest net inflow", rank[::-1][:n]),
                        ("largest net outflow", rank[:n])):
        print(f"  {title} {n}")
        for i, (v, c) in enumerate(part, 1):
            print(f"   {i:>2}. {c} {names.get(c, ''):<38} {v:>+9.1f}   "
                  f"persons {vals[c]['fc_netmig']:>+7,}  5-yr "
                  f"{vals[c]['fc_netmig_5y_per1000']:>+7.1f}  pop {y0} "
                  f"{omrkk[c][y0]['total']:>7,}".replace(",", " "))


if __name__ == "__main__":
    main()
