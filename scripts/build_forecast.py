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
  api.statbank.dk/v1/data                  the projection itself

Raw pulls (gitignored, re-downloadable)
  data/raw/forecast/dst/<TABLE>[_<sex>]_<YYYY-MM-DD>.csv   semicolon CSV, value CODES
  data/raw/forecast/dst/<TABLE>.meta.json                  tableinfo

Output
  data/processed/forecast.json
    {"meta": {...},
     "kommuner": {"<code>": {"<year>": {"total": n, "a0_5": n, ... "a80p": n}}},
     "national": {"<year>": n}}

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
  python scripts/build_forecast.py --indicators fc_20_34 --top 10
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
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}

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
    """'0'..'99' -> the group holding that age; '100-' -> a80p; 'TOT' -> None."""
    if code == "TOT":
        return None
    n = int(code.rstrip("-"))
    for key, lo, hi in GROUPS:
        if lo <= n <= hi:
            return key
    return None


# key -> (field in forecast.json, end year) ; "growth_5y" uses the mid year instead
FIELDS = {"growth": "total", "growth_5y": "total", "abs": "total",
          "a0_5": "a0_5", "a6_16": "a6_16", "a17_19": "a17_19",
          "a20_34": "a20_34", "a35_64": "a35_64", "a65_79": "a65_79", "a80p": "a80p"}


def indicators(doc: dict, mid_offset: int = 5) -> dict[str, dict[str, float | int | None]]:
    """Outlook values per kommune: {code: {"fc_growth": %, ..., "fc_abs": persons}}.

    Every percentage is the change from the vintage year to the last year of the window,
    except fc_growth_5y which stops `mid_offset` years in. fc_abs is persons, not a rate.
    """
    kom, meta = doc["kommuner"], doc["meta"]
    y0, y1 = meta["first_year"], meta["last_year"]
    ymid = str(int(y0) + mid_offset)
    out = {}
    for code, series in kom.items():
        def pct(field, end):
            a, b = series[end][field], series[y0][field]
            return None if not b else round((a - b) / b * 100, 2)
        out[code] = {
            "fc_growth": pct("total", y1),
            "fc_growth_5y": pct("total", ymid) if ymid in series else None,
            "fc_abs": series[y1]["total"] - series[y0]["total"],
            "fc_0_5": pct("a0_5", y1),
            "fc_6_16": pct("a6_16", y1),
            "fc_20_34": pct("a20_34", y1),
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
        rank = sorted((v[key], c) for c, v in vals.items() if v.get(key) is not None)
        unit = "persons" if key == "fc_abs" else "%"
        print(f"{key} · {y0}→{y1} · {len(rank)} kommuner · {unit}\n")
        def show(rows, head):
            print(head)
            for i, (v, c) in enumerate(rows, 1):
                pop0, pop1 = doc["kommuner"][c][y0]["total"], doc["kommuner"][c][y1]["total"]
                fmt = f"{v:+,.0f}" if key == "fc_abs" else f"{v:+.1f} %"
                print(f"  {i:>2}. {c:>3} {names.get(c, ''):<22} {fmt:>10}   "
                      f"pop {pop0:>9,} → {pop1:>9,}".replace(",", " "))
        show(rank[::-1][:args.top], f"Top {args.top}")
        print()
        show(rank[:args.top], f"Bottom {args.top}")
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
        print("  cached " + " · ".join(p.name for p in [*p_sex.values(), p_frdk]))
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
    OUT.write_text(json.dumps({"meta": meta, "kommuner": kom, "national": national},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dev = max(abs(sum(kom[c][y]["total"] for c in kom) / national[y] - 1) for y in years) * 100
    print(f"  wrote {OUT.relative_to(ROOT)} · {len(kom)} kommuner × {len(years)} years "
          f"· max deviation vs {frdk}: {dev:.3f} % · age groups within {gap} of ALDER=TOT")


if __name__ == "__main__":
    main()
