#!/usr/bin/env python3
"""Climate indicators per kommune → data/processed/climate/index.json.

Reads the raw pulls (none of which are committed) and writes one small committed index that the
dashboard build and the Climate indicators in config/indicators.json both read:

  data/raw/klimaatlas/coast_values.json    sea level + storm surge per coastal stretch
  data/raw/klimaatlas/precip_values.json   rain + cloudburst per kommune
  data/external/klimaatlas_coast_kommune.csv   which stretch(es) each coastal kommune belongs to
  data/raw/fp/fp_claims.csv                realised weather damage per kommune (F&P)
  data/processed/climate/risk_areas.json   the designated flood-risk areas (build_surge_zones.py)
  data/processed/climate/surge_today/      Today storm-surge zones, for surge_dw_pct

Horizon mapping (docs/CLIMATE_BUILD_LOG.md):
    today = scenarie 0  · periode 1      the observed baseline
    2050  = periode 3                    sea scenarie 245 (SSP2-4.5), rain scenarie 45 (RCP4.5)
    2100  = periode 4                    same scenarios
percentil 50 and absolutaendring 1 throughout. `range` carries p10/p90 at the same scenario and
the low/high scenario at p50 — sea 126/585 (SSP1-2.6/SSP5-8.5), rain 26/85 (RCP2.6/RCP8.5).

A kommune that touches more than one coastal stretch takes the MAX across them: the conservative
reading for a risk indicator. A landlocked kommune gets null with reason "not coastal".

    python3 scripts/build_climate.py
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "climate"
COAST_MAP = ROOT / "data" / "external" / "klimaatlas_coast_kommune.csv"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"

P50, ABS = 50, 1
BASE = (0, 1)                                   # scenarie, periode — the observed baseline
HORIZONS = {"today": BASE, "2050": (None, 3), "2100": (None, 4)}
SEA_SCEN = {"mid": 245, "low": 126, "high": 585}     # SSP2-4.5 / SSP1-2.6 / SSP5-8.5
RAIN_SCEN = {"mid": 45, "low": 26, "high": 85}       # RCP4.5 / RCP2.6 / RCP8.5

# indicator key -> (source, Klimaatlas column, rounding, today-is-a-constant)
COAST_INDS = {
    "sealevel_cm":   ("coast", "Middelvandstand", 1, 0),          # today = baseline, 0 cm by definition
    "surge100_cm":   ("coast", "Stormfl100Aarsh", 1, None),
    "surge_freq_x":  ("coast", "StormflNuvaerende100Aarsh", 1, 1),  # today = 1 by definition
}
RAIN_INDS = {
    "rain100_1h_mm": ("precip", "Time100Aarsh", 1, None),
    "cloudbursts_yr": ("precip", "Skybrud", 2, None),
}
NOT_COASTAL = "not coastal"
NOT_COMPUTED = "not computed yet"


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def kommune_names():
    gj = jload(GEO)
    out = {}
    for f in gj["features"]:
        p = f["properties"]
        code = str(p.get("kode") or p.get("kommunekode") or "").zfill(4)
        out[code] = p.get("navn") or p.get("name") or ""
    return out


def index_rows(rows, key):
    """{key value: {(scenarie, periode, percentil): row}} for the absolutaendring=1 rows."""
    out = {}
    for r in rows:
        if r.get("absolutaendring") != ABS:
            continue
        out.setdefault(str(r[key]), {})[(r["scenarie"], r["periode"], r["percentil"])] = r
    return out


def pick(idx, scen, per, pct, col):
    r = idx.get((scen, per, pct))
    return None if r is None else r.get(col)


def series(idx, col, scens, const_today, nd):
    """One indicator across the three horizons, with its uncertainty range."""
    out, rng = {}, {}
    for hz, (scen, per) in HORIZONS.items():
        if hz == "today":
            v = const_today if const_today is not None else pick(idx, 0, 1, P50, col)
        else:
            v = pick(idx, scens["mid"], per, P50, col)
        out[hz] = None if v is None else round(float(v), nd)
        if hz == "today":
            continue
        band = {"p10": pick(idx, scens["mid"], per, 10, col),
                "p90": pick(idx, scens["mid"], per, 90, col),
                "low": pick(idx, scens["low"], per, P50, col),
                "high": pick(idx, scens["high"], per, P50, col)}
        band = {k: round(float(v), nd) for k, v in band.items() if v is not None}
        if band:
            rng[hz] = band
    if rng:
        out["range"] = rng
    return out


def build():
    names = kommune_names()
    coast_rows = jload(RAW / "klimaatlas" / "coast_values.json")
    precip_rows = jload(RAW / "klimaatlas" / "precip_values.json")
    meta_kl = jload(RAW / "klimaatlas" / "meta.json")
    by_stretch = index_rows(coast_rows, "kystkode")
    by_kom_rain = index_rows(precip_rows, "komkode")

    coast_map = {}
    if COAST_MAP.exists():
        with COAST_MAP.open() as fh:
            for r in csv.DictReader(fh):
                coast_map[r["kommune_kode"]] = {
                    "kystkode": r["kystkode"], "kystnavn": r["kystnavn"],
                    "other": [x for x in (r.get("other_kystkoder") or "").split(";") if x],
                    "other_navne": [x for x in (r.get("other_kystnavne") or "").split(";") if x],
                    "shared_coast_m": int(r["shared_coast_m"])}
    else:
        sys.exit(f"{COAST_MAP.relative_to(ROOT)} missing — run scripts/build_climate_coast_map.py")

    claims = {}
    fp_meta = {}
    fp = RAW / "fp" / "fp_claims.csv"
    if fp.exists():
        with fp.open() as fh:
            for r in csv.DictReader(fh):
                claims[r["kommune_kode"]] = r
        fp_meta = jload(RAW / "fp" / "meta.json")

    risk = {}
    rp = OUT / "risk_areas.json"
    if rp.exists():
        d = jload(rp)
        risk = {"kommuner": set(d["meta"]["kommuner"]),
                "marginal": set(d["meta"].get("kommuner_marginal") or []),
                "built": d["meta"].get("built") or d["meta"].get("fetched")}

    surge = {}
    sp = OUT / "surge_today" / "index.json"
    if sp.exists():
        surge = jload(sp).get("kommune", {})

    out = {}
    for code, name in sorted(names.items()):
        nkey = str(int(code))                       # Klimaatlas keys kommuner unpadded
        cm = coast_map.get(code)
        rec = {"name": name, "coastal": cm is not None}
        if cm:
            rec["kystkode"] = cm["kystkode"]
            rec["kystnavn"] = cm["kystnavn"]
            if cm["other"]:
                rec["other_kystkoder"] = cm["other"]
                rec["other_kystnavne"] = cm["other_navne"]
        for key, (_src, col, nd, const) in COAST_INDS.items():
            if not cm:
                rec[key] = {"today": None, "2050": None, "2100": None, "reason": NOT_COASTAL}
                continue
            idx = by_stretch.get(cm["kystkode"])
            rec[key] = (series(idx, col, SEA_SCEN, const, nd) if idx
                        else {"today": None, "2050": None, "2100": None,
                              "reason": "no Klimaatlas stretch"})
        for key, (_src, col, nd, const) in RAIN_INDS.items():
            idx = by_kom_rain.get(nkey, {})
            rec[key] = (series(idx, col, RAIN_SCEN, const, nd) if idx
                        else {"today": None, "2050": None, "2100": None,
                              "reason": "no Klimaatlas kommune row"})
        c = claims.get(code)
        rec["weather_claims_1000"] = ({"today": round(float(c["claims_per_1000"]), 1),
                                       "claims": int(c["claims"])} if c
                                      else {"today": None, "reason": NOT_COMPUTED})
        rec["flood_risk_area"] = ({"today": 1 if code in risk["kommuner"] else 0,
                                   "marginal": code in risk["marginal"]} if risk
                                  else {"today": None, "reason": NOT_COMPUTED})
        s = surge.get(code) or surge.get(str(int(code)))
        if s and s.get("surge_dw_pct") is not None:
            rec["surge_dw_pct"] = {"today": s["surge_dw_pct"], "2050": None, "2100": None,
                                   "dwellings": s.get("dwellings"),
                                   "dwellings_at_risk": s.get("dwellings_at_risk"),
                                   "zone_km2": s.get("zone_km2")}
        else:
            # no zone at all (inland, or the coast stays dry at the 100-year level), or no BBR pull
            why = (NOT_COASTAL if not cm
                   else "no surge zone at the 100-year level" if s and not s.get("zone_km2")
                   else s.get("dwellings_note") if s and s.get("dwellings_note")
                   else NOT_COMPUTED)
            rec["surge_dw_pct"] = {"today": None, "2050": None, "2100": None, "reason": why,
                                   "zone_km2": (s or {}).get("zone_km2")}
        out[code] = rec

    meta = {"built": dt.date.today().isoformat(),
            "klimaatlas": {"version": sorted({v for p in meta_kl["pulls"].values()
                                              for v in p["version"]}),
                           "fetched": meta_kl["fetched"]},
            "horizons": {"today": "scenarie 0 · periode 1 (observed baseline)",
                         "2050": "periode 3 · sea SSP2-4.5 (245), rain RCP4.5 (45)",
                         "2100": "periode 4 · sea SSP2-4.5 (245), rain RCP4.5 (45)"},
            "percentil": P50, "absolutaendring": ABS,
            "range": {"p10/p90": "same scenario, 10th and 90th percentile",
                      "low/high": "sea SSP1-2.6 (126) / SSP5-8.5 (585); rain RCP2.6 (26) / RCP8.5 (85)"},
            "coastal_rule": "the Klimaatlas stretch the kommune shares the longest coastline "
                            "with; other touching stretches are listed in other_kystkoder and "
                            "never combined into a number",
            "coastal_kommuner": sum(1 for r in out.values() if r["coastal"]),
            "fp": fp_meta.get("charts", {}),
            "risk_areas": {"kommuner": len(risk.get("kommuner") or []),
                           "marginal": len(risk.get("marginal") or []),
                           "built": risk.get("built")} if risk else None,
            "surge_today": {"kommuner": len(surge)} if surge else None}
    return {"meta": meta, "kommune": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print a summary, write nothing")
    a = ap.parse_args()
    d = build()
    OUT.mkdir(parents=True, exist_ok=True)
    k = d["kommune"]
    print(f"climate index: {len(k)} kommuner · {d['meta']['coastal_kommuner']} coastal · "
          f"Klimaatlas {','.join(d['meta']['klimaatlas']['version'])}")
    for code in ("0101", "0167", "0259", "0657"):
        r = k.get(code, {})
        print(f"  {code} {r.get('name', '?'):<14} surge100 {r.get('surge100_cm', {})} ")
    if not a.check:
        p = OUT / "index.json"
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
