#!/usr/bin/env python3
"""Build data/processed/cph.json — Copenhagen quarter (kvarter) layer.

Inputs : config/indicators.json (section `cph`), data/raw/s30_*.csv, data/geo/cph_kvarterer.geojson
Output : {"meta":{years,latest_year,sources}, "indicators":[...], "areas":[{code,name,bydel,rings,pop,<keys>,hist}]}
Reuses the calc engine of build_makro.py; history is computed per year like the national layer.
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import build_makro as bm  # noqa: E402
from statbank_common import ROOT, cfg, rows, meta, area_col, period_key  # noqa: E402

GEO = ROOT / "data" / "geo" / "cph_kvarterer.geojson"
OUT = ROOT / "data" / "processed" / "cph.json"
# kvarter code 2LLxx → lokaludvalg 20LL → bydel
LOK2BYDEL = {"01": ("1001", "Indre By"), "02": ("1001", "Indre By"), "03": ("1002", "Østerbro"), "04": ("1003", "Nørrebro"),
             "05": ("1004", "Vesterbro/Kongens Enghave"), "06": ("1004", "Vesterbro/Kongens Enghave"), "07": ("1005", "Valby"),
             "08": ("1006", "Vanløse"), "09": ("1007", "Brønshøj-Husum"), "10": ("1008", "Bispebjerg"), "11": ("1009", "Amager Øst"), "12": ("1010", "Amager Vest")}


def compute(ind, year=None):
    """Same as build_makro.compute but for the cph section (all sources are s30)."""
    calc = ind["calc"]; srcs = ind["sources"]
    sel = (lambda rs: bm.rows_for_year(rs, year, calc)) if year else (lambda rs: rs)
    if calc == "ratio_pct":
        numr, p = bm.calc_passthrough(sel(rows("s30", srcs[0]["table"], srcs[0].get("pull"))), srcs[0])
        # denominator from the numerator's own year (an annual count divided by that year's population, not today's)
        den_rows = bm.rows_for_year(rows("s30", srcs[1]["table"], srcs[1].get("pull")), bm.period_parts(p)[0], calc)
        den, _ = bm.calc_passthrough(den_rows, srcs[1])
        return {a: v / den[a] * 100 for a, v in numr.items() if v is not None and den.get(a)}, p
    s = srcs[0]
    rs = sel(rows("s30", s["table"], s.get("pull")))
    if not rs:
        return {}, None
    return bm.CALCS[calc](rs, s)


def main():
    c = cfg(); section = c.get("cph") or {}
    warnings = []
    if not GEO.exists():
        sys.exit("data/geo/cph_kvarterer.geojson missing — run scripts/fetch_geo_cph.py")
    areas = {}
    for f in json.loads(GEO.read_text(encoding="utf-8"))["features"]:
        pr = f["properties"]; code = str(pr.get("kvarternr"))
        lok = code[1:3] if len(code) == 5 else ""
        bcode, bname = LOK2BYDEL.get(lok, ("", ""))
        areas[code] = {"code": code, "name": pr.get("kvarternavn"), "bydel": bname, "bydel_code": bcode, "muni": "101",
                       "rings": bm.rings_of(f["geometry"]), "hist": {}}
    # population (latest) from KKBEF1_pop
    try:
        rs = rows("s30", "KKBEF1", "KKBEF1_pop"); p = bm.latest_period(rs)
        for a, v in bm.sum_by_area(rs, area_col(rs[0]), p).items():
            if a in areas:
                areas[a]["pop"] = v
        latest_year = bm.period_parts(p)[0]
    except FileNotFoundError as e:
        warnings.append(str(e)); latest_year = dt.date.today().year
    n_hist = int(c.get("history_years", 11))
    years = list(range(latest_year - n_hist + 1, latest_year + 1))
    inds = []
    for ind in section.get("indicators", []):
        if any("TODO" in v for s in ind["sources"] for vals in s.get("vars", {}).values() for v in vals):
            warnings.append(f"{ind['key']}: unresolved TODO codes — skipped"); continue
        hist_asof = {}
        # geo_level "bydel": the table only exists for the 10 districts → copy each district's value onto its quarters
        bydel = ind.get("geo_level") == "bydel"
        def spread(vals):
            if not bydel:
                return vals
            return {a["code"]: vals[a["bydel_code"]] for a in areas.values() if a.get("bydel_code") in vals}
        for y in years:
            try:
                vals, per = compute(ind, y)
            except Exception:  # noqa: BLE001
                continue
            if not vals:
                continue
            ay = str(bm.period_parts(str(per).replace("→", "–").split("–")[-1].strip())[0])
            if ay != str(y):
                continue
            hist_asof[ay] = per
            for a, v in spread(vals).items():
                if a in areas and v is not None:
                    areas[a]["hist"].setdefault(ind["key"], {})[ay] = round(v, 2)
        try:
            vals, per = compute(ind)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{ind['key']}: {e}"); continue
        for a, v in spread(vals).items():
            if a in areas and v is not None:
                areas[a][ind["key"]] = round(v, 2)
        inds.append({k: ind[k] for k in ("key", "label", "short", "unit", "hue", "group", "fmt") if k in ind} |
                    {"level": "kvarter", "geo_level": ind.get("geo_level", "kvarter"), "desc": ind.get("desc", ""), "source": ind.get("source", ""), "warn": ind.get("warn", ""), "asof": {"kvarter": per}, "hist_asof": hist_asof})
    tables = sorted({s["table"] for ind in section.get("indicators", []) for s in ind["sources"]})
    sources = [{"key": f"s30/{t}", "label": f"Københavns Kommune {t}", "tables": meta("s30", t).get("text", ""), "asof": meta("s30", t).get("updated", "")[:10],
                "url": f"https://api.statbank.dk/v1/s30/tableinfo/{t}", "licence": "free reuse with attribution"} for t in tables]
    out = {"meta": {"built": dt.date.today().isoformat(), "years": [str(y) for y in years], "latest_year": str(latest_year), "sources": sources,
                    "attribution": "Københavns Kommune statbank (s30) · Bydele og kvarterer: Københavns Kommune, opendata.dk (CC BY 4.0)", "warnings": warnings},
           "indicators": inds, "areas": sorted(areas.values(), key=lambda a: a["code"])}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['areas'])} quarters, {len(inds)} indicators, years {years[0]}–{years[-1]}")
    for w in warnings:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
