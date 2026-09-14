# Runbook — step by step, with what to expect

Each step: the command, what "good" looks like, what to do if not. Steps are numbered so a chat message like "step 3 failed, here is the output" is unambiguous. Run everything from the repo root:

```bash
cd ~/Desktop/"Denmark dashboard, funny project"/am-dashboard-dk
```

Requirements: macOS Terminal, Python 3.10+ (`python3 --version`), git. No packages needed; `pip3 install shapely` makes `make geo` produce smaller files.

---

## Step 0 — Design check (no network)

```bash
make fixture && open dist/fixture.html
```
**Good:** the dashboard opens with sidebar *Macro map / Market / Sources*, a chip row, a map (basemap needs internet), tables. Numbers are labelled SYNTHETIC.
**If not:** paste the Terminal output.

## Step 1 — Boundaries (network, before 2026-10-01)

```bash
make geo
```
**Good:** five lines like `kommuner: 98 features written`, `postnumre: ~600 features written`, `sogne: ~2150 features written`; folder `data/geo/` has the `.geojson` files and `ATTRIBUTION.txt`.
**Check:** `ls -la data/geo` — `postnumre.geojson` a few MB, not 0 bytes.
**Commit:** `git add data/geo && git commit -m "data: vendor DAGI boundaries (DAWA, $(date +%F))"`
**If not:** `FAILED: <error>` per layer — paste it. If DAWA is already closed, follow `docs/GEO.md` (Datafordeler).

## Step 2 — Validate the registry (network)

```bash
make validate > validate.txt; grep -c "✗" validate.txt; grep "✗" validate.txt
```
**Good:** the count is 0.
**Expected the first time:** several ✗ lines for the codes marked `TODO_*` in `config/indicators.json` (EJ56, DNRENTM, BYGV33, UDB010, IFOR22, FOLK1E, INDKP101). Paste `validate.txt` in the chat — the fix is a config edit, then re-run until 0.

## Step 3 — Fetch (network, ~2 minutes)

```bash
make fetch
```
**Good:** one `ok · updated <date> · <n> rows` line per table, no `FAILED:` block, and `ls data/raw | wc -l` ≈ 80 (CSV + meta per table).
**If not:** the script prints the failing table and the API's error text; paste it.

## Step 3b — History window

`config/indicators.json` → `history_years` (default 11 = 2016–2026) controls how many years `make fetch` pulls and `build_makro.py` computes. Fetch windows per table type are set in the same file (`Tid`: quarterly `(-n+45)`, monthly `(-n+121)`, annual `(-n+11)`). Values are filed under the year the data refers to, so a source whose latest year is 2024 shows 2014–2024.

## Step 4 — Build (no network)

```bash
make build
```
**Good:** `wrote data/processed/makro.json: 98 municipalities, ~600 areas, 20 indicators`, then `wrote data/processed/market.json: 13 series`, then `wrote dist/index.html (x MB)`.
**Warnings (⚠)** name an indicator and the reason — paste them; the dashboard still builds with that indicator missing.

## Step 5 — Look at it

```bash
make serve      # then open http://localhost:8080
```
**Check list (write results into docs/DATA_MAP.md §7):**
- national zoom shows 98 coloured municipalities, labels on the large ones;
- switching chips recolours the map and re-sorts the table;
- clicking a municipality row zooms in and shows its postal codes;
- *Sources* lists every table with an "as of" date.
- spot-check 3 values against https://www.statistikbanken.dk (e.g. København population 2026Q3, Aarhus unemployment latest month, 2100 København Ø price/m² 2026K1 = 79 842 DKK).

## Step 6 — Rents (manual, yearly)

Fill `data/external/rent_private.csv` (boligstat.dk) and `rent_social.csv` (LBF basistabeller) as `kommune;value`, note the source in `data/external/SOURCES.md`, run `make build` again.

## Step 7 — Publish

```bash
git add -A && git commit -m "data: first full build $(date +%F)" && git push
```
GitHub → Settings → Pages → Source *GitHub Actions*. The workflow in `.github/workflows/refresh.yml` deploys `dist/` and re-runs monthly. Tag: `git tag v1.0 && git push --tags`.

---

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `HTTP 400` with a message naming a variable | wrong value code | `make validate`, fix `config/indicators.json` |
| `HTTP 403/000` from Terminal | corporate proxy/VPN | run on home network |
| `no raw pull for dst_X` | fetch failed or skipped | `python3 scripts/fetch_statbank.py --table X` |
| map is grey, no polygons | `data/geo/postnumre.geojson` missing | step 1 |
| indicator column all `–` | calc warning in step 4 | paste the ⚠ line |
| `git commit` complains about lock files | folder mounted through Cowork | run git from Terminal, not through Claude |
