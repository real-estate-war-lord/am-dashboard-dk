#!/usr/bin/env python3
"""Import Landsbyggefonden's Huslejestatistik basistabeller (xlsx) → data/external/rent_social.csv

Reads "Tabel 7" (Gennemsnitlig årlig husleje pr. m² by kommune), takes the
*familieboliger* column for the statistics year, and maps municipality names to
DST codes via data/geo/kommuner.geojson.

Usage: python scripts/import_lbf.py ~/Downloads/basistabeller-for-huslejestatistik-2026.xlsx
Needs: pip3 install openpyxl
"""
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "rent_social.csv"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
ALIASES = {"århus": "aarhus", "vesthimmerland": "vesthimmerlands", "lyngby-tårbæk": "lyngby-taarbæk",
           "brønderslev-dronninglund": "brønderslev", "høje taastrup": "høje-taastrup", "københavns": "københavn"}


def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    s = re.sub(r"\s+kommune$", "", s)
    return ALIASES.get(s, s)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    xlsx = pathlib.Path(sys.argv[1]).expanduser()
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["Tabel 7"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    # locate header row: contains 'Kommune'
    hi = next(i for i, r in enumerate(rows) if r and any(str(c).strip() == "Kommune" for c in r if c))
    header = [str(c).strip() if c else "" for c in rows[hi]]
    title = " ".join(str(c) for c in rows[1] if c)
    year = re.search(r"20\d\d", " ".join(header) + title)
    year = year.group(0) if year else "?"
    # familieboliger block = second occurrence of 'Husleje <year>'
    idx = [i for i, h in enumerate(header) if h.startswith("Husleje")]
    fam_col = idx[1] if len(idx) > 1 else idx[0]
    codes = {norm(f["properties"]["navn"]): f["properties"]["kode"].lstrip("0") for f in json.loads(GEO.read_text(encoding="utf-8"))["features"]}
    out, unmatched = [], []
    for r in rows[hi + 1:]:
        if not r or not r[0] or str(r[0]).strip().lower() in ("i alt", "kilde", "note"):
            continue
        name = str(r[0]).strip()
        if name.lower().startswith(("kilde", "note", "anm")):
            continue
        v = r[fam_col]
        if v is None or not isinstance(v, (int, float)):
            continue
        code = codes.get(norm(name))
        if not code:
            unmatched.append(name); continue
        out.append((code, name, float(v)))
    out.sort(key=lambda x: int(x[0]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("kommune;value;name\n" + "\n".join(f"{c};{v:.0f};{n}" for c, n, v in out) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} municipalities · familieboliger DKK/m²/yr {year} · header col {fam_col} '{header[fam_col]}'")
    if unmatched:
        print("  unmatched names:", unmatched)
    src = ROOT / "data" / "external" / "SOURCES.md"
    if src.exists():
        line = f"| `rent_social.csv` | Social housing rent DKK/m²/yr, family dwellings | Landsbyggefonden, Huslejestatistik {year}, basistabeller Tabel 7 | https://lbf.dk/viden/statistikker/huslejestatistik/ | 1 Jan {year} | {dt.date.today().isoformat()} | import_lbf.py |"
        txt = src.read_text(encoding="utf-8")
        txt = re.sub(r"^\| `rent_social\.csv` \|.*$", line, txt, flags=re.M)
        src.write_text(txt, encoding="utf-8")
        print("  SOURCES.md updated")


if __name__ == "__main__":
    main()
