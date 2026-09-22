# Hand-collected files in this folder

Format for every CSV: header `kommune;value`, municipality code as 3-digit DST code (`101` København), decimal point or comma, one row per municipality. Add a line here every time a file is (re)filled.

| file | indicator | source | URL | period | copied on | by |
|---|---|---|---|---|---|---|
| `rent_private.csv` | Private rental rent DKK/m²/yr (Private udlejningsboliger i alt, opførelsesår i alt) | Social- og Boligstyrelsen, boligstat.dk Huslejestatistik (Boligstøtteregister × BBR) | https://boligstat.dk/boligstat/dokumenter/huslejeudvikling_intro.html | 2026 | 2026-09-14 | import_boligstat.py from raw/boligstat_private_2026.txt |
| `rent_social.csv` | Social housing rent DKK/m²/yr, family dwellings | Landsbyggefonden, Huslejestatistik 2026, basistabeller Tabel 7 | https://lbf.dk/viden/statistikker/huslejestatistik/ | 1 Jan 2026 | 2026-09-14 | import_lbf.py |
| `cph_crime_bydele.csv` | Copenhagen quarters: reported crime per 1,000 inhabitants (Københavns Politi) and the share feeling safe in their own neighbourhood (survey) | Københavns Kommune, Tryghedsundersøgelsen 2026 (Epinion) | https://www.kk.dk/tryghedsundersoegelsen (PDF: `data/external/kk_tryghed_2026.pdf`, not committed) | survey 2026 · police figures 2025 | 2026-09-22 | `scripts/import_kk_tryghed.py` |
| `cph_bydel_map.csv` | Mapping: the report's 13 areas → the 67 quarters (kvarterer) | hand-made from the lokaludvalg codes; checked against each area's population in the report | — | 2026 | 2026-09-22 | hand-written, `population_check` column |

## Københavns Kommunes Tryghedsundersøgelse — yearly refresh

The report is published each spring (the 2026 edition covers the 2026 survey and police figures for 2025).

1. Download this year's PDF to `data/external/kk_tryghed_<year>.pdf` (the file itself is gitignored; the CSVs are committed):
   `curl -L -o data/external/kk_tryghed_<year>.pdf "<URL from kk.dk>"`
2. `pip3 install pdfplumber` (once), then `python3 scripts/import_kk_tryghed.py --year <year>` → rewrites `cph_crime_bydele.csv`.
   The script prints a cross-check per area: safety share against the chapter's fact box, crime rate against the chart of all bydele on p. 28. Read every ⚠ line before using the file.
3. Check the report's area list. If it changes (2026: 13 areas — Indre By and Christianshavn separate, Nørrebro split into Indre and Ydre, Vesterbro and Kgs. Enghave separate), update `cph_bydel_map.csv`; the quarter populations in `data/processed/cph.json` must stay within about 1 % of each area's population in the report.
4. `make build` → the quarter layer picks the figures up (`scripts/build_cph.py`, `load_kk()`).

**Known error in the 2026 edition:** the Bispebjerg fact box (p. 49) prints 76 % safe in the neighbourhood and 64 % in the evening/night — those are Brønshøj-Husum's figures. Bispebjerg's own results page (p. 50) and the map on p. 7 both give 80 % and 70 %. The CSV uses 80 %, and the `note` column records the discrepancy.

**Two years in one file:** `safe_pct` is from the survey year, `crime_1000` / `reports_n` / the offence groups are police figures for `crime_year` (the previous year). The dashboard labels them "2026 (survey)" and "2025 (Københavns Politi)".

**Not comparable with the national crime indicators:** these are Københavns Politi's reports for a calendar year per bydel, while the national Safety family is DST STRAF11 over a rolling four quarters per municipality. `burglary_1000inh` is per 1,000 inhabitants, not per 1,000 dwellings, so it is deliberately not mapped onto `burglary_1000dw`. About 8 % of the city's reports (4 242 of 50 337 in 2025) cannot be placed in a bydel, so the city figure (75) is above the population-weighted mean of the bydele (69).
