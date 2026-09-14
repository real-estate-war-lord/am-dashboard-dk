#!/usr/bin/env python3
"""boligstat.dk private-rental rent by municipality → data/external/rent_private.csv

Input: data/external/raw/boligstat_private_<year>.txt — lines "Kommune|1.637" copied from the
result table of boligstat.dk › Huslejestatistik › Statistik (Opgørelsesår <year>, Alle kommuner,
Opførelsesår i alt, Private udlejningsboliger i alt). 0 = suppressed by the source → dropped.
Names are mapped to DST codes via data/geo/kommuner.geojson.

Usage: python scripts/import_boligstat.py 2026
"""
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
OUT = ROOT / "data" / "external" / "rent_private.csv"
ALIASES = {"århus": "aarhus", "vesthimmerland": "vesthimmerlands", "nordfyn": "nordfyns", "lyngby-tårbæk": "lyngby-taarbæk"}


def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return ALIASES.get(s, s)


def main():
    year = sys.argv[1] if len(sys.argv) > 1 else "2026"
    src = ROOT / "data" / "external" / "raw" / f"boligstat_private_{year}.txt"
    codes = {norm(f["properties"]["navn"]): f["properties"]["kode"].lstrip("0") for f in json.loads(GEO.read_text(encoding="utf-8"))["features"]}
    out, unmatched, national = [], [], None
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or "|" not in line:
            continue
        name, val = [x.strip() for x in line.split("|", 1)]
        v = float(val.replace(".", "").replace(",", "."))
        if norm(name) == "hele landet":
            national = v; continue
        code = codes.get(norm(name))
        if not code:
            unmatched.append(name); continue
        if v <= 0:
            continue  # suppressed
        out.append((code, name, v))
    out.sort(key=lambda x: int(x[0]))
    OUT.write_text("kommune;value;name\n" + "\n".join(f"{c};{v:.0f};{n}" for c, n, v in out) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} municipalities · private rental DKK/m²/yr {year} · national {national}")
    if unmatched:
        print("  unmatched names:", unmatched)
    smd = ROOT / "data" / "external" / "SOURCES.md"
    if smd.exists():
        line = (f"| `rent_private.csv` | Private rental rent DKK/m²/yr (Private udlejningsboliger i alt, opførelsesår i alt) | "
                f"Social- og Boligstyrelsen, boligstat.dk Huslejestatistik (Boligstøtteregister × BBR) | https://boligstat.dk/boligstat/dokumenter/huslejeudvikling_intro.html | {year} | {dt.date.today().isoformat()} | import_boligstat.py from raw/boligstat_private_{year}.txt |")
        txt = smd.read_text(encoding="utf-8")
        smd.write_text(re.sub(r"^\| `rent_private\.csv` \|.*$", line, txt, flags=re.M), encoding="utf-8")
        print("  SOURCES.md updated")


if __name__ == "__main__":
    main()
