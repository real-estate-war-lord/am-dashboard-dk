#!/usr/bin/env python3
"""Read the per-project figures out of Transportministeriet's Anlægsstatus (PDF).

Input : data/external/anlaegsstatus_<edition>.pdf   (gitignored; see docs/INFRA.md)
Output: prints `project | totaludgift (mio. kr.) | åbningsår | page` for every chapter overview
        table ("Økonomioversigt"), and writes the same as CSV next to the PDF when --csv is given.

The overview tables are the reliable part of the report: one row per project with the approved total
budget in the edition's price level and the current opening year. Values the report withholds
("[fortroligt]") or has not settled ("Under afklaring") come back empty — they are never guessed.
The per-project detail blocks add "Oprindeligt/nuværende åbningsår"; that field is free text
("2018 (bane)/2026 (vej) 2027 (bane)") and is reported as-is for a human to read, not parsed.

Usage: python3 scripts/parse_anlaegsstatus.py [--pdf data/external/anlaegsstatus_1h2026.pdf] [--csv]
"""
import argparse
import csv
import pathlib
import re

import pdfplumber

ROOT = pathlib.Path(__file__).resolve().parents[1]
NUM = re.compile(r"^\[?\d{1,3}(?:\.\d{3})*,\d+\]?$")          # 4.495,2
YEAR = re.compile(r"(19|20)\d{2}")


def clean(c):
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def num(s):
    s = clean(s)
    return float(s.replace(".", "").replace(",", ".")) if NUM.match(s) else None


def rows_of(page):
    """(name, budget, opening year text) for every data row of an overview table on this page."""
    out = []
    for tb in page.extract_tables():
        for row in tb:
            cells = [clean(c) for c in row]
            if len(cells) < 3:
                continue
            name = next((c for c in cells if c and not NUM.match(c) and len(c) > 8 and not c.lower().startswith(
                ("projekt", "total", "overhol", "væsent", "dispone", "forbrug", "åb", "hjemmel", "godkendt", "bevilling", "prognose", "difference", "kunde"))), "")
            budget = next((num(c) for c in cells if num(c) is not None), None)
            last = cells[-1]
            year = last if (YEAR.search(last) or "afklaring" in last.lower() or "bero" in last.lower()) else ""
            if name and (budget is not None or year):
                out.append((name, budget, year))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=str(ROOT / "data" / "external" / "anlaegsstatus_1h2026.pdf"))
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()
    pdf = pdfplumber.open(args.pdf)
    found = []
    for i, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        if "Økonomioversigt" not in text and "Oversigt over byggeprojekter" not in text:
            continue
        for name, budget, year in rows_of(page):
            found.append({"project": name, "budget_mdkk": budget, "open_year": year, "page": i})
    w = max(len(f["project"]) for f in found) if found else 10
    for f in found:
        print(f'{f["project"]:{w}} | {"" if f["budget_mdkk"] is None else f"{f['budget_mdkk']:>9,.1f}"} | {f["open_year"]:<24} | p.{f["page"]}')
    print(f"\n{len(found)} project rows from {len({f['page'] for f in found})} overview tables")
    if args.csv:
        dst = pathlib.Path(args.pdf).with_suffix(".csv")
        with dst.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=["project", "budget_mdkk", "open_year", "page"], delimiter=";")
            wr.writeheader(); wr.writerows(found)
        print("wrote", dst)


if __name__ == "__main__":
    main()
