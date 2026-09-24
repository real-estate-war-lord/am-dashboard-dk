# AM Dashboard — Denmark Edition · one command per pipeline step
PY ?= python3

validate:   ## check every table/value code in config against the live API, plus a sample of source links
	$(PY) scripts/validate_config.py && $(PY) scripts/check_source_links.py --quick --sample 2
links:      ## the full source-link sweep: all 165 Outlook links fetched and their values recomputed (slow, ~15 min)
	$(PY) scripts/check_source_links.py
validate-links: links   ## deprecated alias for `make links`
geo:        ## vendor DAGI boundaries (DAWA — before 2026-10-01!)
	$(PY) scripts/fetch_geo_dawa.py --simplify 0.0005
fetch:      ## pull all StatBank / Finans Danmark tables to data/raw
	$(PY) scripts/fetch_statbank.py
bbr:        ## aggregate BBR pulls (data/raw/bbr) into data/processed/bbr.json + micro/<kommune>.json
	$(PY) scripts/build_bbr.py && $(PY) scripts/build_micro.py
schools:    ## STIL education statistics -> data/processed/schools.json (run after build_public.py)
	$(PY) scripts/fetch_uddstat.py --schools && $(PY) scripts/build_schools.py
forecast:   ## DST + KK population projections and the measured building pace -> data/processed
	$(PY) scripts/build_forecast.py && $(PY) scripts/build_net_dwellings.py && $(PY) scripts/build_cph_forecast.py && ($(PY) scripts/build_cph_backtest.py || true)
build:      ## raw -> processed -> dist/index.html
	($(PY) scripts/build_schools.py --quiet || true) && ($(PY) scripts/build_forecast.py --no-fetch || true) && ($(PY) scripts/build_net_dwellings.py --no-fetch || true) && ($(PY) scripts/build_cph_forecast.py --no-fetch || true) && ($(PY) scripts/build_cph_backtest.py --no-fetch || true) && $(PY) scripts/build_makro.py && $(PY) scripts/build_market.py && ($(PY) scripts/build_cph.py || true) && $(PY) scripts/build_dashboard.py
geo-cph:    ## vendor Copenhagen quarter/district polygons (Københavns Kommune WFS)
	$(PY) scripts/fetch_geo_cph.py
serve:      ## open the dashboard locally
	cd dist && $(PY) -m http.server 8080
test-js:    ## parser unit tests (node --test)
	node --test tests/*.test.js
test:       ## every unit test (python + js)
	$(PY) -m unittest discover -s tests -p 'test_*.py' && $(MAKE) test-js
ui-check:   ## drive dist/index.html headless and assert on the app's own state (needs Chrome)
	$(PY) scripts/ui_check.py
validate-forecast: ## the Outlook layer's own checks (hard-data audit, reconciliations, backtest)
	$(PY) scripts/validate_forecast.py
fixture:    ## synthetic render check (never ship)
	$(PY) tests/make_fixture.py && $(PY) scripts/build_dashboard.py --data tests/fixture_makro.json --market tests/fixture_market.json --cph tests/fixture_cph.json --out dist/fixture.html
refresh: fetch build
.PHONY: validate links validate-links validate-forecast geo geo-cph bbr fetch build serve fixture refresh schools forecast test test-js ui-check

# scripts/build_housing_gap.py is deliberately NOT a target: it needs a fitted household-size
# trend, which the hard-data rule forbids in the UI (docs/FORECAST.md §0, §7). It stays in the
# repo as research and is run by hand, after build_forecast.py.
