# Hand-collected files in this folder

Format for every CSV: header `kommune;value`, municipality code as 3-digit DST code (`101` København), decimal point or comma, one row per municipality. Add a line here every time a file is (re)filled.

| file | indicator | source | URL | period | copied on | by |
|---|---|---|---|---|---|---|
| `rent_private.csv` | Private rental rent DKK/m²/yr (Private udlejningsboliger i alt, opførelsesår i alt) | Social- og Boligstyrelsen, boligstat.dk Huslejestatistik (Boligstøtteregister × BBR) | https://boligstat.dk/boligstat/dokumenter/huslejeudvikling_intro.html | 2026 | 2026-09-14 | import_boligstat.py from raw/boligstat_private_2026.txt |
| `rent_social.csv` | Social housing rent DKK/m²/yr, family dwellings | Landsbyggefonden, Huslejestatistik 2026, basistabeller Tabel 7 | https://lbf.dk/viden/statistikker/huslejestatistik/ | 1 Jan 2026 | 2026-09-14 | import_lbf.py |
