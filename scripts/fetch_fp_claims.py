#!/usr/bin/env python3
"""Forsikring & Pension — realised weather damage per kommune → data/raw/fp/.

F&P publish the claim counts as two Datawrapper charts rather than as a dataset, so the numbers
are read from the charts' own `dataset.csv`:

  TUJ9b   antal skader                          (claim count)
  z0zEO   antal skader pr 1000 indbygger        (claims per 1 000 inhabitants)

Both are keyed by kommune *name*, space-padded, with no kommune code, so the names are matched
against data/geo/kommuner.geojson with the same normalise-and-alias convention the other
importers use (scripts/import_lbf.py, scripts/import_boligstat.py). An unmatched name is fatal:
a silently dropped kommune would read as a missing indicator rather than as a broken join.

    python3 scripts/fetch_fp_claims.py
    python3 scripts/fetch_fp_claims.py --check     # fetch and verify, write nothing
"""
import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import re
import sys
import unicodedata

try:
    import requests
except ImportError:
    sys.exit("requests missing: pip3 install requests")

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "fp"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
UA = {"User-Agent": "am-dashboard-dk F&P fetch (research; contact via repo)"}
CDN = "https://datawrapper.dwcdn.net"
EXPECT_ROWS = 98

CHARTS = [
    ("claims", "TUJ9b", "antal", "weather-damage claims"),
    ("claims_per_1000", "z0zEO", "antal skader pr 1000 indbygger", "claims per 1 000 inhabitants"),
]

# same convention as scripts/import_lbf.py — spelling variants that are not simple case/space
ALIASES = {"århus": "aarhus", "vesthimmerland": "vesthimmerlands", "nordfyn": "nordfyns",
           "lyngby-tårbæk": "lyngby-taarbæk", "brønderslev-dronninglund": "brønderslev",
           "høje taastrup": "høje-taastrup", "københavns": "københavn", "faaborg-midtfyn": "faaborg-midtfyn"}


def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    s = re.sub(r"\s+kommune$", "", s)
    s = re.sub(r"\s+", " ", s)
    return ALIASES.get(s, s)


def kommune_table():
    gj = json.loads(GEO.read_text())
    by = {}
    for f in gj["features"]:
        p = f["properties"]
        code = str(p.get("kode") or p.get("kommunekode") or p.get("KOMKODE") or "").zfill(4)
        name = p.get("navn") or p.get("name") or p.get("NAVN") or ""
        by[norm(name)] = (code, name)
    return by


def latest_version(chart):
    """Datawrapper serves /<id>/ as a stub that names the published version."""
    r = requests.get(f"{CDN}/{chart}/", headers=UA, timeout=60)
    vs = [int(v) for v in re.findall(rf"{chart}/(\d+)/", r.text)] if r.ok else []
    if vs:
        return max(vs)
    for v in range(30, 0, -1):                       # fall back to walking versions down
        if requests.get(f"{CDN}/{chart}/{v}/dataset.csv", headers=UA, timeout=60).ok:
            return v
    sys.exit(f"{chart}: no published version answers")


def fetch(chart, value_col):
    v = latest_version(chart)
    url = f"{CDN}/{chart}/{v}/dataset.csv"
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    txt = r.content.decode("utf-8-sig", "replace")
    sep = "\t" if txt.count("\t") > txt.count(",") else ","
    rows = [x for x in csv.reader(io.StringIO(txt), delimiter=sep) if any(c.strip() for c in x)]
    header = [c.strip() for c in rows[0]]
    if value_col not in header:
        sys.exit(f"{chart}: expected a '{value_col}' column, got {header}")
    ni, vi = header.index("komnavn"), header.index(value_col)
    out = [(r[ni].strip(), r[vi].strip()) for r in rows[1:]]
    return v, url, header, out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fetch and verify, write nothing")
    a = ap.parse_args()
    koms = kommune_table()
    merged, meta = {}, {"fetched": dt.date.today().isoformat(), "source": "Forsikring & Pension",
                        "charts": {}}
    unmatched = []
    for key, chart, col, label in CHARTS:
        v, url, header, rows = fetch(chart, col)
        print(f"{chart} v{v}: {len(rows)} rows · columns {header}")
        if len(rows) != EXPECT_ROWS:
            sys.exit(f"{chart}: expected {EXPECT_ROWS} rows, got {len(rows)} — the chart changed")
        for name, value in rows:
            hit = koms.get(norm(name))
            if not hit:
                unmatched.append((chart, name))
                continue
            code, geo_name = hit
            rec = merged.setdefault(code, {"kommune_kode": code, "kommune_navn": geo_name,
                                           "fp_navn": name.strip()})
            rec[key] = value
        meta["charts"][key] = {"chart": chart, "version": v, "url": url, "column": col,
                               "label": label, "rows": len(rows)}
    if unmatched:
        for chart, name in unmatched:
            print(f"  UNMATCHED {chart}: {name!r} → {norm(name)!r}", file=sys.stderr)
        sys.exit(f"{len(unmatched)} kommune name(s) did not match data/geo/kommuner.geojson — "
                 "add them to ALIASES rather than dropping them")
    rows = [merged[c] for c in sorted(merged)]
    missing = [r["kommune_kode"] for r in rows if any(k not in r for k, *_ in CHARTS)]
    print(f"matched {len(rows)}/{EXPECT_ROWS} kommuner, all names resolved"
          + (f" · {len(missing)} missing a value: {missing}" if missing else ""))
    if len(rows) != EXPECT_ROWS:
        sys.exit(f"expected {EXPECT_ROWS} matched kommuner, got {len(rows)}")
    meta["kommuner"] = len(rows)
    if not a.check:
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "fp_claims.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["kommune_kode", "kommune_navn", "fp_navn",
                                               "claims", "claims_per_1000"])
            w.writeheader()
            w.writerows(rows)
        (OUT / "fp_claims.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        print(f"wrote {(OUT / 'fp_claims.csv').relative_to(ROOT)} + .json + meta.json")


if __name__ == "__main__":
    main()
