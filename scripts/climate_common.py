#!/usr/bin/env python3
"""Climate indicators for build_makro.py — the `calc: "climate"` branch.

Kept out of build_makro.py so the v2.5 climate branch touches that shared file in three lines.
Reads data/processed/climate/index.json (scripts/build_climate.py), which holds every horizon;
the makro build takes the **Today** value, which is what the map, table and area pages show
until the horizon pill lands. The other horizons and the uncertainty ranges stay in the index
and are copied to dist/ by the dashboard build.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "processed" / "climate" / "index.json"
_IX = None


def climate_index():
    """data/processed/climate/index.json, or None when the climate build has not run."""
    global _IX
    if _IX is None:
        _IX = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    return _IX or None


def period(ix, key):
    """What the value is 'as of' — Klimaatlas version, F&P years or the designation year."""
    m = ix["meta"]
    if key == "weather_claims_1000":
        return "F&P 2023–2025"
    if key == "flood_risk_area":
        return "Floods Directive 2024"
    if key in ("surge_dw_pct", "cloudburst_dw_pct"):
        return f"BBR × Klimaatlas {','.join(m['klimaatlas']['version'])}"
    return f"Klimaatlas {','.join(m['klimaatlas']['version'])}"


def calc_climate(ind, year=None):
    """{geo: ({area: today value}, period)} for one Climate indicator.

    A snapshot, so there is no yearly history: a reference year returns nothing, exactly as the
    BBR, infra, public and schools calcs do. Kommuner whose value is null (not coastal, or not
    computed yet) are left out, so the map draws them as 'no data' and the reason stays readable
    in data/processed/climate/index.json."""
    ix = climate_index()
    if year or not ix:
        return {}
    key = ind["key"]
    vals = {}
    for code, rec in ix["kommune"].items():
        v = (rec.get(key) or {}).get("today")
        if v is not None:
            # the index keys kommuner zero-padded, as the per-kommune file names do; makro.json
            # keys them unpadded, as every StatBank pull does
            vals[str(int(code))] = v
    return {"kommune": (vals, period(ix, key))} if vals else {}
