# AM Dashboard — Denmark Edition · one command per pipeline step
PY ?= python3

validate:   ## check every table/value code in config against the live API
	$(PY) scripts/validate_config.py
geo:        ## vendor DAGI boundaries (DAWA — before 2026-10-01!)
	$(PY) scripts/fetch_geo_dawa.py --simplify 0.0005
fetch:      ## pull all StatBank / Finans Danmark tables to data/raw
	$(PY) scripts/fetch_statbank.py
build:      ## raw -> processed -> dist/index.html
	$(PY) scripts/build_makro.py && $(PY) scripts/build_market.py && $(PY) scripts/build_dashboard.py
serve:      ## open the dashboard locally
	cd dist && $(PY) -m http.server 8080
fixture:    ## synthetic render check (never ship)
	$(PY) tests/make_fixture.py && $(PY) scripts/build_dashboard.py --data tests/fixture_makro.json --market tests/fixture_market.json --out dist/fixture.html
refresh: fetch build
.PHONY: validate geo fetch build serve fixture refresh
