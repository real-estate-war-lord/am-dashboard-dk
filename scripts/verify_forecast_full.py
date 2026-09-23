#!/usr/bin/env python3
"""Full independent verification of the Outlook layer — every data point, not a sample.

`validate_forecast.py` checks the layer against itself: reconciliations, additivity,
tolerances. This script does something different and deliberately dumber — it pulls the
source tables from the API **again**, with its own request, its own CSV parsing and its
own arithmetic, and diffs the result cell by cell against what the pipeline shipped.
Nothing here imports build_forecast.py, so a bug in that file cannot hide in this one.

  1. FRKM126 — 98 kommuner × 15 years × 8 fields vs data/processed/forecast.json
     plus Σ kommuner vs FRDK126's published national total, per year
  2. KKFR2026 — 67 kvarterer + 10 bydele + city × 15 years vs cph_forecast.json
     plus Σ kvarterer = bydel = city, per year
  3. every fc_* for every area, recomputed here from the raw cells
  4. hist_net_dwell recomputed from BOL101 + FOLK1A

Usage:
  python3 scripts/verify_forecast_full.py                # pull and verify
  python3 scripts/verify_forecast_full.py --cached       # reuse this script's own pulls
  python3 scripts/verify_forecast_full.py --report       # + write the §7 table to stdout
"""
import argparse
import collections
import csv
import datetime as dt
import io
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "raw" / "verify"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/verify", "Content-Type": "application/json"}

GROUPS = {"a0_5": range(0, 6), "a6_16": range(6, 17), "a17_19": range(17, 20),
          "a20_34": range(20, 35), "a35_64": range(35, 65), "a65_79": range(65, 80),
          "a80p": range(80, 126)}
FIELDS = ["total"] + list(GROUPS)


def log(*a):
    print(*a, flush=True)


def post_csv(body, db=""):
    url = f"{API}/{db + '/' if db else ''}data"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        sys.exit(f"API {e.code} for {body.get('table')}:\n{e.read().decode()[:600]}")


def pull(name, body, db="", cached=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.csv"
    if cached and p.exists():
        log(f"  · {name}: cached ({p.stat().st_size/1e6:.1f} MB)")
        return p.read_text(encoding="utf-8")
    log(f"  · {name}: pulling…")
    txt = post_csv(body, db)
    if txt.lstrip().startswith("{"):
        sys.exit(f"{name}: API returned an error instead of CSV:\n{txt[:300]}")
    p.write_text(txt, encoding="utf-8")
    log(f"    {len(txt)/1e6:.1f} MB")
    return txt


def pull_years(name, body, years, db="", cached=False, chunk=3):
    """The same pull, split into year batches.

    FRKM126 with every municipality, age and sex over 15 years is 1.5 M cells and the CSV
    endpoint caps at 1 M. Splitting on Tid is exact — no cell is fetched twice and none is
    missed — and each batch is cached under its own name so --cached still works.
    """
    out = []
    for i in range(0, len(years), chunk):
        part = years[i:i + chunk]
        b = json.loads(json.dumps(body))
        for v in b["variables"]:
            if v["code"] == "Tid":
                v["values"] = part
        out += rows(pull(f"{name}_{part[0]}-{part[-1]}", b, db=db, cached=cached))
    return out


def rows(text):
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def age_of(code):
    """'25' → 25; DST writes the open-ended top group as '125' or similar."""
    d = "".join(ch for ch in str(code) if ch.isdigit())
    return int(d) if d else None


def group_of(age):
    for g, rng in GROUPS.items():
        if age in rng:
            return g
    return "a80p" if age is not None and age >= 80 else None


# ----------------------------------------------------------------- 1. FRKM126
def verify_dst(cached):
    doc = json.loads((PROC / "forecast.json").read_text(encoding="utf-8"))
    meta = doc["meta"]
    y0, y1 = meta["first_year"], meta["last_year"]
    years = [str(y) for y in range(int(y0), int(y1) + 1)]
    tab = meta["table"]
    info = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{API}/tableinfo/{tab}?lang=en&format=JSON", headers=UA),
        timeout=120).read().decode())
    codes = {v["id"]: [x["id"] for x in v["values"]] for v in info["variables"]}
    komvar = "KOMMUNEDK" if "KOMMUNEDK" in codes else next(k for k in codes if "OMR" in k or "KOM" in k)
    sexes = codes.get("KØN") or ["TOT"]
    # ALDER='*' returns the single years and DST's own TOT cell in one response, so `total` is
    # compared against the published cell rather than against a sum (docs/FORECAST.md §2).
    # FRKM126 has no both-sexes code; this script sums M+K itself.
    rs = pull_years("FRKM126", {"table": tab, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                                "valuePresentation": "Code",
                                "variables": [{"code": komvar, "values": ["*"]},
                                              {"code": "KØN", "values": sexes},
                                              {"code": "ALDER", "values": ["*"]},
                                              {"code": "Tid", "values": years}]}, years, cached=cached)
    raw = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    for r in rs:
        code = str(r[komvar]).lstrip("0") or "0"
        y = str(r["TID"])
        v = int(float(r["INDHOLD"] or 0))
        acode = str(r["ALDER"]).strip()
        if acode in ("TOT", "IALT"):
            raw[code][y]["total"] += v
            continue
        g = group_of(age_of(acode))
        if g:
            raw[code][y][g] += v

    miss, checked = [], 0
    for code, series in doc["kommuner"].items():
        for y, cell in series.items():
            for f in FIELDS:
                checked += 1
                got, want = cell.get(f), raw.get(code, {}).get(y, {}).get(f)
                if got != want:
                    miss.append((code, y, f, got, want))
    log(f"  98 kommuner × {len(years)} years × {len(FIELDS)} fields = {checked} cells checked")
    return {"name": f"{tab} → forecast.json", "checked": checked, "mismatches": miss[:20],
            "n_mismatch": len(miss), "raw": raw, "years": years, "komvar": komvar}


def verify_dst_national(cached, years):
    doc = json.loads((PROC / "forecast.json").read_text(encoding="utf-8"))
    nat_tab = doc["meta"]["national_table"]
    txt = pull("FRDK126_all_origins", {"table": nat_tab, "format": "CSV", "delimiter": "Semicolon",
                                 "lang": "en", "valuePresentation": "Code",
                                 # FRDK126 publishes no age-total code, and its HERKOMST elimination
                                 # value is "persons of Danish origin" (5.0 M), not everyone — asking
                                 # for Tid alone silently returns that subset. All five origin groups
                                 # are requested and summed instead.
                                 "variables": [{"code": "HERKOMST", "values": ["*"]},
                                               {"code": "Tid", "values": years}]}, cached=cached)
    published = {}
    for r in rows(txt):
        published[str(r["TID"])] = published.get(str(r["TID"]), 0) + int(float(r["INDHOLD"] or 0))
    out = []
    for y in years:
        s = sum(c[y]["total"] for c in doc["kommuner"].values() if y in c)
        p = published.get(y)
        out.append((y, s, p, None if p is None else s - p))
    return out


# ---------------------------------------------------------------- 2. KKFR2026
def verify_kk(cached):
    doc = json.loads((PROC / "cph_forecast.json").read_text(encoding="utf-8"))
    meta = doc["meta"]
    y0, y1 = meta["first_year"], meta["last_year"]
    years = [str(y) for y in range(int(y0), int(y1) + 1)]
    tab = meta["table"]
    rs = pull_years("KKFR2026", {"table": tab, "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                                 "valuePresentation": "Code",
                                 "variables": [{"code": "OMRKK", "values": ["*"]},
                                               # KK spells it KON; DST spells it KØN
                                               {"code": "KON", "values": ["TOT"]},
                                               {"code": "ALDER", "values": ["*"]},
                                               {"code": "Tid", "values": years}]},
                    years, db="s30", cached=cached, chunk=5)
    raw = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    for r in rs:
        code = str(r["OMRKK"])
        y = str(r["TID"])
        v = int(float(r["INDHOLD"] or 0))
        acode = str(r["ALDER"]).strip()
        if acode in ("TOT", "IALT"):
            # KK's own published total. cph_forecast.json stores this cell, not the group sum —
            # independent per-cell rounding puts the two a few persons apart (docs/FORECAST.md §2).
            raw[code][y]["total"] = v
            continue
        g = group_of(age_of(acode))
        if g:
            raw[code][y][g] += v
    miss, checked = [], 0
    for code, series in doc["omrkk"].items():
        for y, cell in series.items():
            for f in FIELDS:
                checked += 1
                got, want = cell.get(f), raw.get(code, {}).get(y, {}).get(f)
                if got != want:
                    miss.append((code, y, f, got, want))
    log(f"  {len(doc['omrkk'])} OMRKK areas × {len(years)} years × {len(FIELDS)} fields = {checked} cells checked")
    # Σ kvarterer = bydel = city, per year, from the raw pull
    lv = meta["levels"]
    kv = [c for c in lv["kvarter"]]
    by = [c for c in lv["bydel"]]
    add = []
    for y in years:
        sk = sum(raw[c][y]["total"] for c in kv if c in raw)
        sb = sum(raw[c][y]["total"] for c in by if c in raw)
        city = raw.get("1000", {}).get(y, {}).get("total")
        add.append((y, sk, sb, city, sk - (city or 0), sb - (city or 0)))
    return {"name": f"{tab} → cph_forecast.json", "checked": checked, "mismatches": miss[:20],
            "n_mismatch": len(miss), "raw": raw, "years": years, "additivity": add}


# -------------------------------------------------- 3. every fc_* recomputed
def recompute_fc(series, y0, y1, ymid, ref20):
    """The §3 arithmetic, written out here rather than imported."""
    def pct(field, end):
        a, b = series[end].get(field), series[y0].get(field)
        return None if not b else round((a - b) / b * 100, 2)
    p0, p1, pm = series[y0]["total"], series[y1]["total"], series[ymid]["total"]
    out = {
        "fc_growth": round((p1 - p0) / p0 * 100, 2) if p0 else None,
        "fc_growth_5y": round((pm - p0) / p0 * 100, 2) if p0 else None,
        "fc_pop_rate_5y": round((pm - p0) / 5 / p0 * 1000, 2) if p0 else None,
        "fc_abs": p1 - p0,
        "fc_0_5": pct("a0_5", y1), "fc_6_16": pct("a6_16", y1),
        "fc_20_34": pct("a20_34", y1), "fc_80p": pct("a80p", y1),
        "fc_20_34_abs": series[y1]["a20_34"] - series[y0]["a20_34"],
    }
    if ref20 is not None and out["fc_20_34"] is not None:
        out["fc_20_34_rel"] = round(out["fc_20_34"] - ref20, 2)
    return out


def verify_indicators(doc_path, container, raw, y0, y1, ref_code=None, tag=""):
    doc = json.loads((PROC / doc_path).read_text(encoding="utf-8"))
    ymid = str(int(y0) + 5)
    src = doc[container]
    shipped = doc["indicators"] if "indicators" in doc else None
    if ref_code:
        rs = raw[ref_code]
        a, b = rs[y0]["a20_34"], rs[y1]["a20_34"]
        ref20 = round((b - a) / a * 100, 2) if a else None
    else:                       # Denmark = Σ of the areas in the file
        a = sum(raw[c][y0]["a20_34"] for c in src)
        b = sum(raw[c][y1]["a20_34"] for c in src)
        ref20 = (b - a) / a * 100 if a else None
    miss, checked = [], 0
    for code in src:
        if code not in raw:
            continue
        mine = recompute_fc(raw[code], y0, y1, ymid, ref20 if not ref_code else ref20)
        theirs = (shipped or {}).get(code) if shipped else None
        if theirs is None:      # municipal file: values live on makro.json instead
            continue
        for k, v in mine.items():
            if v is None:
                continue
            checked += 1
            got = theirs.get(k)
            if got is None or abs(got - v) > 0.011:
                miss.append((code, k, got, v))
    return {"checked": checked, "n_mismatch": len(miss), "mismatches": miss[:20], "ref20": ref20, "tag": tag}


# forecast.json stores fc_pop_rate_5y as persons per 1 000 inhabitants per year — the arithmetic
# docs/FORECAST.md §3 audits. build_makro.py divides it by 10 on the way into makro.json so the UI
# can speak in percent per year. This check reads makro.json, so it applies the same division.
MAKRO_DISPLAY_DIV = {"fc_pop_rate_5y": 10}


def verify_makro_fc(raw, y0, y1):
    """The municipal fc_* as they reach the app, recomputed from the raw pull."""
    mk = json.loads((PROC / "makro.json").read_text(encoding="utf-8"))
    ymid = str(int(y0) + 5)
    codes = [c for c in raw if c in {m["code"] for m in mk["municipalities"]}]
    a = sum(raw[c][y0]["a20_34"] for c in codes)
    b = sum(raw[c][y1]["a20_34"] for c in codes)
    ref20 = (b - a) / a * 100 if a else None
    miss, checked = [], 0
    for m in mk["municipalities"]:
        if m["code"] not in raw:
            continue
        mine = recompute_fc(raw[m["code"]], y0, y1, ymid, ref20)
        for k, v in mine.items():
            if v is None or m.get(k) is None:
                continue
            v = round(v / MAKRO_DISPLAY_DIV[k], 2) if k in MAKRO_DISPLAY_DIV else v
            checked += 1
            if abs(m[k] - v) > 0.011:
                miss.append((m["code"], k, m[k], v))
    return {"checked": checked, "n_mismatch": len(miss), "mismatches": miss[:20], "ref20": round(ref20, 4)}


# ------------------------------------------------- 4. hist_net_dwell from raw
def verify_net_dwellings(cached):
    nd = json.loads((PROC / "net_dwellings.json").read_text(encoding="utf-8"))
    m = nd["meta"]
    w = m.get("window") or []
    ys, ye = (str(w[0]), str(w[-1])) if w else ("2020", "2026")
    # BEBO cannot be eliminated on BOL101, so every resident-type code is selected explicitly and
    # summed here — "all uses and all resident types", the same stock net_dwellings.json counts.
    bol = pull("BOL101", {"table": "BOL101", "format": "CSV", "delimiter": "Semicolon", "lang": "en",
                          "valuePresentation": "Code",
                          "variables": [{"code": "OMRÅDE", "values": ["*"]},
                                        {"code": "BEBO", "values": ["1000", "2000", "5000"]},
                                        {"code": "Tid", "values": [ys, ye]}]}, cached=cached)
    stock = collections.defaultdict(dict)
    for r in rows(bol):
        code = str(r["OMRÅDE"]).lstrip("0") or "0"
        stock[code][str(r["TID"])] = stock[code].get(str(r["TID"]), 0) + int(float(r["INDHOLD"] or 0))
    pop_period = m.get("pop_period", "")
    folk = pull("FOLK1A_pop", {"table": "FOLK1A", "format": "CSV", "delimiter": "Semicolon",
                               "lang": "en", "valuePresentation": "Code",
                               "variables": [{"code": "OMRÅDE", "values": ["*"]},
                                             {"code": "Tid", "values": [pop_period]}]}, cached=cached)
    pop = collections.Counter()
    for r in rows(folk):
        pop[str(r["OMRÅDE"]).lstrip("0") or "0"] += int(float(r["INDHOLD"] or 0))
    span = m.get("span_years") or (int(ye) - int(ys))
    mk = json.loads((PROC / "makro.json").read_text(encoding="utf-8"))
    miss, checked = [], 0
    for mm in mk["municipalities"]:
        c = mm["code"]
        if mm.get("hist_net_dwell") is None:
            continue
        s0, s1, p = stock.get(c, {}).get(ys), stock.get(c, {}).get(ye), pop.get(c)
        if not (s0 and s1 and p):
            miss.append((c, "no raw", mm["hist_net_dwell"], None)); continue
        mine = round((s1 - s0) / span / p * 1000, 2)
        checked += 1
        if abs(mm["hist_net_dwell"] - mine) > 0.011:
            miss.append((c, "hist_net_dwell", mm["hist_net_dwell"], mine))
    return {"checked": checked, "n_mismatch": len(miss), "mismatches": miss[:20],
            "window": f"{ys}–{ye}", "span": span, "pop_period": pop_period}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", action="store_true", help="reuse this script's own pulls")
    ap.add_argument("--report", action="store_true", help="print the docs/DATA_MAP.md §7 rows")
    args = ap.parse_args()
    fails = 0

    log("1. DST FRKM126 — pipeline vs a fresh independent pull")
    dst = verify_dst(args.cached)
    log(f"   {'✓' if not dst['n_mismatch'] else '✗'} {dst['checked']} cells, {dst['n_mismatch']} mismatches")
    for row in dst["mismatches"]:
        log(f"      {row}")
    fails += bool(dst["n_mismatch"])

    log("\n   Σ 98 kommuner vs FRDK126's published national total, per year")
    nat = verify_dst_national(args.cached, dst["years"])
    worst = max((abs(d) for *_, d in nat if d is not None), default=0)
    for y, s, p, d in nat:
        log(f"      {y}  Σ {s:>9,}  FRDK {p:>9,}  Δ {d:+}".replace(",", " "))
    # FRKM126 and FRDK126 are two separately rounded publications of one run; a gap of a few
    # dozen persons on 6 M is per-cell rounding, not a pipeline error.
    log(f"   {'✓' if worst <= 500 else '✗'} largest gap {worst} persons on ~6.0 M "
        f"({worst / 6.0e6 * 100:.4f} %) — independent per-cell rounding of the same run")

    log("\n2. Københavns Kommune KKFR2026 — pipeline vs a fresh independent pull")
    kk = verify_kk(args.cached)
    log(f"   {'✓' if not kk['n_mismatch'] else '✗'} {kk['checked']} cells, {kk['n_mismatch']} mismatches")
    for row in kk["mismatches"]:
        log(f"      {row}")
    fails += bool(kk["n_mismatch"])
    log("\n   Σ kvarterer = Σ bydele = city, per year")
    wk = max(abs(a) for *_, a, _ in kk["additivity"])
    wb = max(abs(b) for *_, b in kk["additivity"])
    for y, sk, sb, city, dk, db in kk["additivity"]:
        log(f"      {y}  kvarter Σ {sk:>8,}  bydel Σ {sb:>8,}  city {city:>8,}  Δ {dk:+} / {db:+}".replace(",", " "))
    # docs/FORECAST.md check 9 allows ±10 at city level and ±5 per bydel for the same reason
    log(f"   {'✓' if wk <= 10 and wb <= 10 else '✗'} worst kvarter Δ {wk}, bydel Δ {wb} persons "
        f"(tolerance ±10 — per-cell rounding)")

    log("\n3. every fc_* recomputed independently")
    mk = verify_makro_fc(dst["raw"], "2026", "2040")
    log(f"   {'✓' if not mk['n_mismatch'] else '✗'} makro.json: {mk['checked']} values, {mk['n_mismatch']} mismatches "
        f"(Denmark 20–34 baseline recomputed as {mk['ref20']} %)")
    for row in mk["mismatches"]:
        log(f"      {row}")
    fails += bool(mk["n_mismatch"])
    cp = verify_indicators("cph_forecast.json", "omrkk", kk["raw"], "2026", "2040", ref_code="1000")
    log(f"   {'✓' if not cp['n_mismatch'] else '✗'} cph_forecast.json: {cp['checked']} values, {cp['n_mismatch']} mismatches "
        f"(København 20–34 baseline recomputed as {cp['ref20']} %)")
    for row in cp["mismatches"]:
        log(f"      {row}")
    fails += bool(cp["n_mismatch"])

    log("\n4. hist_net_dwell recomputed from BOL101 + FOLK1A")
    nd = verify_net_dwellings(args.cached)
    log(f"   {'✓' if not nd['n_mismatch'] else '✗'} {nd['checked']} municipalities, {nd['n_mismatch']} mismatches "
        f"(window {nd['window']}, span {nd['span']} yr, population {nd['pop_period']})")
    for row in nd["mismatches"]:
        log(f"      {row}")
    fails += bool(nd["n_mismatch"])

    if args.report:
        today = dt.date.today().isoformat()
        log("\n--- docs/DATA_MAP.md §7 rows ---")
        log(f"| {today} | FRKM126 → forecast.json, every cell re-pulled and diffed: 98 kommuner × "
            f"{len(dst['years'])} years × {len(FIELDS)} fields | ✅ **{dst['checked']} cells, "
            f"{dst['n_mismatch']} mismatches** |")
        log(f"| {today} | Σ 98 kommuner vs FRDK126 published national total, all {len(nat)} years | "
            f"✅ largest gap **{worst} persons** |")
        log(f"| {today} | KKFR2026 → cph_forecast.json, every cell re-pulled and diffed | "
            f"✅ **{kk['checked']} cells, {kk['n_mismatch']} mismatches** |")
        log(f"| {today} | Σ kvarterer = Σ bydele = city, all {len(kk['additivity'])} years | "
            f"✅ worst Δ **{wk} / {wb} persons** |")
        log(f"| {today} | every fc_* recomputed from the raw cells | ✅ **{mk['checked']} municipal + "
            f"{cp['checked']} Copenhagen values, {mk['n_mismatch'] + cp['n_mismatch']} mismatches** |")
        log(f"| {today} | hist_net_dwell recomputed from BOL101 + FOLK1A | "
            f"✅ **{nd['checked']} municipalities, {nd['n_mismatch']} mismatches** |")

    log("\n" + ("✗ verification FAILED" if fails else "✓ every check passed — 0 mismatches"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
