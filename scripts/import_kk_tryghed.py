#!/usr/bin/env python3
"""Extract per-bydel safety and crime figures from Københavns Kommunes Tryghedsundersøgelse (PDF).

Input : data/external/kk_tryghed_<year>.pdf  (see data/external/SOURCES.md)
Output: data/external/cph_crime_bydele.csv
        (year;crime_year;bydel_pdf;safe_pct;crime_1000;reports_n;violence_1000inh;burglary_1000inh;source_page;note)

Per bydel chapter (first page has "Bydelsfakta"; pages have two text columns, so each column is read on its own):
  safe_pct   — results page (chapter p. 2, left column): "I 2026 angiver NN % … at de er trygge i deres nabolag" (survey year).
               Cross-checked against the fact box on p. 1 ("andelen af trygge i nabolaget NN %"); the 2026 edition's
               Bispebjerg fact box repeats Brønshøj-Husum's 76 % — the results page and the p. 7 map say 80 %.
  crime_1000 — fact box: "svarer til NN anmeldelser pr. 1000 indbyggere" (Københavns Politi, the latest full year =
               survey year − 1), cross-checked against the p. 28 chart of all bydele
  reports_n  — fact box: "I 2025 blev der i/på X anmeldt N tilfælde af straffelovskriminalitet"; crime_year = that year
  violence_1000inh, burglary_1000inh — bar labels of the chapter's "Udvalgte kriminalitetstyper" figure (2015 · 2024 ·
               2025 bars per group, read by x position; a page without exactly 15 labels is reported, not guessed).
               Per 1,000 INHABITANTS as published — not comparable with the national burglary_1000dw (per dwelling).
               Property crime is not published in the report.
  note       — set when the report publishes one figure for two measures or contradicts itself
The city-wide row ("Hele København") comes from the p. 28/29 overview. Needs: pip3 install pdfplumber
Usage: python3 scripts/import_kk_tryghed.py [--year 2026]
"""
import argparse
import csv
import pathlib
import re
import sys

import pdfplumber

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
GROUPS = ["Indbrud", "Lov", "Tyveri", "Vold", "Økonomisk"]   # burglary · drugs · theft from person · violence · economic


def fig_labels(page):
    """{group: [v2015, v2024, v2025]} from the right-hand 'Udvalgte kriminalitetstyper' bar chart, or None."""
    W = page.extract_words()
    title = [w for w in W if w["text"] == "Figur" and w["x0"] > page.width / 2]
    cats = [w for w in W if w["text"] in GROUPS and title and w["x0"] > title[0]["x0"] - 5]
    if not title or len(cats) != 5:
        return None
    ybot = min(c["top"] for c in cats)
    nums = sorted((w for w in W if re.fullmatch(r"\d{1,3}", w["text"]) and w["x0"] > title[0]["x0"] - 5 and title[0]["top"] < w["top"] < ybot), key=lambda w: w["x0"])
    if len(nums) != 15:
        return None
    return {c["text"]: [int(w["text"]) for w in nums[3 * k:3 * k + 3]] for k, c in enumerate(sorted(cats, key=lambda c: c["x0"]))}


def column(page, k):
    """Text of the left (k=0) or right (k=1) half of a page, whitespace collapsed — the report is set in two columns."""
    w = page.width / 2
    return re.sub(r"\s+", " ", page.crop((k * w, 0, (k + 1) * w, page.height)).extract_text() or "")


OVERVIEW_ORDER = ["Hele København", "Indre By", "Vesterbro", "Christianshavn", "Amager Vest", "Indre Nørrebro", "Ydre Nørrebro", "Amager Øst",
                  "Kgs. Enghave", "Bispebjerg", "Østerbro", "Valby", "Vanløse", "Brønshøj-Husum"]   # x-axis of the p. 28 chart


def overview_crime(page):
    """{area: 2025 value} from the p. 28 chart 'Straffelovsovertrædelser pr. 1000 indbyggere fordelt på bydele'
    (2015 · 2024 · 2025 bars per area, labels read by x position) — the cross-check for crime_1000."""
    W = page.extract_words()
    title = next((w for w in W if w["text"] == "Figur"), None)
    axis = next((w for w in W if w["text"] == "KBH" and title and w["top"] > title["top"]), None)
    if not (title and axis):
        return {}
    nums = sorted((w for w in W if re.fullmatch(r"\d{1,3}", w["text"]) and title["top"] < w["top"] < axis["top"]), key=lambda w: w["x0"])
    if len(nums) != 3 * len(OVERVIEW_ORDER):
        return {}
    return {a: int(nums[3 * k + 2]["text"]) for k, a in enumerate(OVERVIEW_ORDER)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--year", type=int, default=2026); args = ap.parse_args()
    pdf = pdfplumber.open(EXT / f"kk_tryghed_{args.year}.pdf")
    texts = [p.extract_text() or "" for p in pdf.pages]
    out, problems, checks = [], [], []
    # bydel chapters open with "Bydelsfakta"; the three social-housing "Partnerskab" chapters are not bydele
    starts = [i for i, t in enumerate(texts) if "Bydelsfakta" in t and "Partnerskab" not in t.splitlines()[0]]
    ov = overview_crime(pdf.pages[27])
    for i in starts:
        name = texts[i].splitlines()[0].strip()
        left, right = column(pdf.pages[i], 0), column(pdf.pages[i], 1)
        crime = re.search(r"svarer til\s*(\d+)\s*anmeldelser pr\.\s*1\.?000", left)
        # "I 2025 blev der i Valby anmeldt 2.849 tilfælde" / "I 2025 blev der anmeldt 6.558tilfælde … på Amager Vest"
        count = re.search(r"I (\d{4}) blev der (?:(?:i|på) .{0,40}?)?anmeldt\s*([\d.]+)\s*tilfælde", left)
        # fact box: "andelen af trygge i nabolaget 89 %" — Valby: "… i nabolaget og i aften-og nattetimerne 79%" (one figure for both)
        box = re.search(r"trygge i nabolaget(?: og i aften-og nattetimerne)?\s*(\d+)\s*%", right)
        safe = re.search(r"angiver\s*(\d+)\s*% af de københavnere, der er bosat[^,]*, at de er trygge i\s*(?:deres|sit) nabolag", column(pdf.pages[i + 1], 0))
        notes = []
        if box and "aften-og" in box.group(0):
            notes.append("single figure published for neighbourhood and evening/night safety")
        if safe and box and safe.group(1) != box.group(1):
            problems.append(f"{name}: safe_pct {safe.group(1)} on the results page (p.{i + 2}, used) ≠ {box.group(1)} in the fact box (p.{i + 1})")
            notes.append(f"fact box p. {i + 1} says {box.group(1)} % (and a different evening/night share) — results page p. {i + 2} and the p. 7 map say {safe.group(1)} %; results page used")
        if crime and name in ov and int(crime.group(1)) != ov[name]:
            problems.append(f"{name}: crime_1000 {crime.group(1)} (p.{i + 1}) ≠ {ov[name]} (p.28 chart)")
        checks.append((name, box and box.group(1), ov.get(name)))
        # the chapter's crime page: next page titled "Udviklingen i straffelovskriminalitet (2015-2025)"
        j = next((k for k in range(i + 1, min(i + 8, len(texts))) if "Udviklingen i straffelovskriminalitet (" in texts[k]), None)
        figs = fig_labels(pdf.pages[j]) if j is not None else None
        if not (safe and crime and count):
            problems.append(f"{name} p.{i + 1}/{i + 2}: safe/crime text not found")
        if figs is None:
            problems.append(f"{name} p.{(j or i) + 1}: offence-type figure not read (labels ≠ 15)")
        out.append({"year": args.year, "crime_year": count and count.group(1), "bydel_pdf": name, "safe_pct": safe and safe.group(1),
                    "crime_1000": crime and crime.group(1), "reports_n": count and count.group(2).replace(".", ""),
                    "violence_1000inh": figs and figs["Vold"][2], "burglary_1000inh": figs and figs["Indbrud"][2],
                    "source_page": f"{i + 1}-{i + 2}" + (f"/{j + 1}" if j is not None else ""), "note": "; ".join(notes)})
    # city-wide sanity row
    t2, t29 = re.sub(r"\s+", " ", texts[1]), re.sub(r"\s+", " ", texts[28])
    kbh_safe = re.search(r"(\d+)\s*% af københavnerne trygge i deres nabolag", t2)
    kbh_crime = re.search(r"svarende til\s*(\d+)\s*anmeldelser pr\.\s*1\.?000", t29)
    kbh_n = re.search(r"I (\d{4}) blev der i hele København anmeldt\s*([\d.]+)\s*tilfælde", t29)
    out.insert(0, {"year": args.year, "crime_year": kbh_n and kbh_n.group(1), "bydel_pdf": "Hele København", "safe_pct": kbh_safe and kbh_safe.group(1),
                   "crime_1000": kbh_crime and kbh_crime.group(1), "reports_n": kbh_n and kbh_n.group(2).replace(".", ""),
                   "violence_1000inh": "", "burglary_1000inh": "", "source_page": "2/29",
                   "note": "city total; includes reports not placed in any bydel, so it is above the population-weighted mean of the bydele"})
    dst = EXT / "cph_crime_bydele.csv"
    with dst.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), delimiter=";"); w.writeheader()
        for r in out:
            w.writerow({k: ("" if v in (None, False) else v) for k, v in r.items()})
    print(f"wrote {dst.relative_to(ROOT)}: {len(out) - 1} bydele + city row")
    print("cross-checks (safe_pct in the fact box · crime_1000 on the p.28 chart):", "; ".join(f"{n} {s}/{c}" for n, s, c in checks))
    if ov.get("Hele København") is not None and kbh_crime and int(kbh_crime.group(1)) != ov["Hele København"]:
        problems.append(f"Hele København: crime {kbh_crime.group(1)} (p.29) ≠ {ov['Hele København']} (p.28 chart)")
    for p in problems:
        print("  ⚠", p)
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
