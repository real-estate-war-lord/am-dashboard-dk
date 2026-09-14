#!/usr/bin/env python3
"""Build data/processed/makro.json from raw StatBank pulls + vendored geometry.

Inputs : config/indicators.json, data/raw/*.csv + *.meta.json, data/geo/*.geojson,
         optional data/external/rent_private.csv and rent_social.csv (kommune;value)
Output : data/processed/makro.json with meta, indicators, municipalities, areas

Every calc is driven by the `calc` field of an indicator (see docstrings below).
Run scripts/validate_config.py before the first build to confirm value codes.
"""
import datetime as dt
import json
import pathlib
import statistics
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statbank_common import ROOT, RAW, cfg, rows, labels, meta, area_col, muni_code, period_key  # noqa: E402

GEO = ROOT / "data" / "geo"
EXT = ROOT / "data" / "external"
OUT = ROOT / "data" / "processed" / "makro.json"
TOTAL_CODES = {"IALT", "TOT", "TOTAL", "000", "0", "I alt", "Total"}
NON_DIM = {"TID", "INDHOLD"}


def dims(r):
    return [k for k in r if k not in NON_DIM]


def norm_area(col, code):
    return muni_code(code) if col != "PNR20" else str(code).strip()[:4]


def latest_period(rs):
    return max((r["TID"] for r in rs), key=period_key) if rs else None


def periods_sorted(rs):
    return sorted({r["TID"] for r in rs}, key=period_key)


def apply_select(rs, select):
    if not select:
        return rs
    return [r for r in rs if all(r.get(k) == v for k, v in select.items())]


# ---------- calcs: each returns {area_code: value} ----------

def calc_passthrough(rs, src):
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); p = latest_period(rs)
    return {norm_area(col, r[col]): r["INDHOLD"] for r in rs if r["TID"] == p}, p


def calc_share_of_total(rs, src):
    """sum(parts)/total*100 where one var has several codes incl. a total code."""
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); p = latest_period(rs)
    rs = [r for r in rs if r["TID"] == p]
    part_var = None
    for v, vals in src["vars"].items():
        if v != "Tid" and v != col and len(vals) > 1:
            part_var = v
    if not part_var:
        raise ValueError(f"share_of_total: no multi-valued variable in {src['table']}")
    tot = [c for c in src["vars"][part_var] if c in TOTAL_CODES]
    parts = [c for c in src["vars"][part_var] if c not in TOTAL_CODES]
    if not tot:
        raise ValueError(f"share_of_total: no total code among {src['vars'][part_var]}")
    out = {}
    by = {}
    for r in rs:
        by.setdefault(norm_area(col, r[col]), {})[r[part_var]] = r["INDHOLD"]
    for a, d in by.items():
        t = d.get(tot[0]); s = [d.get(c) for c in parts]
        if t and all(x is not None for x in s):
            out[a] = sum(s) / t * 100
    return out, p


def calc_yoy_pct(rs, src):
    """Latest period vs the same period one year earlier."""
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); ps = periods_sorted(rs); p = ps[-1]
    y, n = period_key(p)
    prev = next((q for q in ps if period_key(q) == (y - 1, n)), None)
    if not prev:
        raise ValueError(f"yoy_pct: no period one year before {p} in {src['table']} (have {ps})")
    cur = {norm_area(col, r[col]): r["INDHOLD"] for r in rs if r["TID"] == p}
    old = {norm_area(col, r[col]): r["INDHOLD"] for r in rs if r["TID"] == prev}
    return {a: (v / old[a] - 1) * 100 for a, v in cur.items() if v and old.get(a)}, f"{prev}→{p}"


def calc_last4q_mean(rs, src):
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); ps = periods_sorted(rs)[-4:]
    by = {}
    for r in rs:
        if r["TID"] in ps and r["INDHOLD"]:
            by.setdefault(norm_area(col, r[col]), []).append(r["INDHOLD"])
    return {a: statistics.fmean(v) for a, v in by.items()}, f"{ps[0]}–{ps[-1]}"


def calc_discount_pct(rs, src):
    col = area_col(rs[0]); ps = periods_sorted(rs)[-4:]
    by = {}
    for r in rs:
        if r["TID"] in ps and r["INDHOLD"]:
            by.setdefault((norm_area(col, r[col]), r["TID"]), {})[r["PRIS20"]] = r["INDHOLD"]
    acc = {}
    for (a, _t), d in by.items():
        u, re_ = d.get("UDBUD"), d.get("REAL")
        if u and re_:
            acc.setdefault(a, []).append((u - re_) / u * 100)
    return {a: statistics.fmean(v) for a, v in acc.items()}, f"{ps[0]}–{ps[-1]}"


def dwellings():
    """Total dwellings per municipality from BOL101 (all-total rows)."""
    rs = rows("", "BOL101")
    col = area_col(rs[0]); p = latest_period(rs)
    out = {}
    for r in rs:
        if r["TID"] != p:
            continue
        if all(r[k] in TOTAL_CODES for k in dims(r) if k != col):
            out[norm_area(col, r[col])] = r["INDHOLD"]
    return out


def calc_per_1000_dwellings(rs, src):
    vals, p = calc_passthrough(rs, src)
    dw = dwellings()
    return {a: v / dw[a] * 1000 for a, v in vals.items() if v is not None and dw.get(a)}, p


def calc_sum4q_per_1000(rs, src):
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); ps = periods_sorted(rs)[-4:]
    by = {}
    for r in rs:
        if r["TID"] in ps and r["INDHOLD"] is not None:
            by[norm_area(col, r[col])] = by.get(norm_area(col, r[col]), 0) + r["INDHOLD"]
    dw = dwellings()
    return {a: v / dw[a] * 1000 for a, v in by.items() if dw.get(a)}, f"{ps[0]}–{ps[-1]}"


CALCS = {
    "passthrough": calc_passthrough, "value_div_1000": calc_passthrough,
    "share_of_total": calc_share_of_total, "yoy_pct": calc_yoy_pct,
    "last4q_mean": calc_last4q_mean, "discount_pct": calc_discount_pct,
    "per_1000_dwellings": calc_per_1000_dwellings, "sum4q_per_1000": calc_sum4q_per_1000,
}


def external_csv(name):
    p = EXT / f"{name}.csv"
    if not p.exists():
        return None
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines()[1:]:
        if ";" in line:
            k, v = line.split(";")[:2]
            try:
                out[muni_code(k)] = float(v.replace(",", "."))
            except ValueError:
                pass
    return out


def compute(ind):
    """Returns {geo: ({area: value}, period)} for one indicator."""
    res = {}
    srcs = ind["sources"]
    if ind["calc"] == "ratio_pct":
        numr, p = calc_passthrough(rows(srcs[0].get("db", ""), srcs[0]["table"]), srcs[0])
        den, _ = calc_passthrough(rows(srcs[1].get("db", ""), srcs[1]["table"]), srcs[1])
        res[srcs[0]["geo"]] = ({a: v / den[a] * 100 for a, v in numr.items() if v is not None and den.get(a)}, p)
        return res
    for s in srcs:
        if s.get("db") in ("boligstat", "lbf"):
            ext = external_csv(ind["key"])
            if ext:
                res[s["geo"]] = (ext, s.get("asof", "external file"))
            continue
        rs = rows(s.get("db", ""), s["table"])
        vals, p = CALCS[ind["calc"]](rs, s)
        res[s["geo"]] = (vals, p)
    return res


def load_geo(name):
    p = GEO / f"{name}.geojson"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def rings_of(geom):
    """GeoJSON (Multi)Polygon [lon,lat] -> list of outer rings [[lat,lon],...]."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [[[round(pt[1], 5), round(pt[0], 5)] for pt in poly[0]] for poly in polys if poly]


def main():
    c = cfg()
    warnings = []
    # municipalities: population from FOLK1A latest
    folk = rows("", "FOLK1A")
    col = area_col(folk[0]); p = latest_period(folk)
    names = labels("", "FOLK1A", col)
    kom_geo = load_geo("kommuner")
    geo_names = {muni_code(f["properties"]["kode"]): f["properties"]["navn"] for f in kom_geo["features"]} if kom_geo else {}
    munis = {}
    for r in folk:
        code = muni_code(r[col])
        if r["TID"] == p and code.isdigit() and int(code) >= 101 and all(r[k] in TOTAL_CODES for k in dims(r) if k != col):
            munis[code] = {"code": code, "name": geo_names.get(code) or names.get(r[col], code), "pop": r["INDHOLD"], "asof": {"pop": p}}
    # postal-code areas from geometry
    areas = {}
    pn_geo = load_geo("postnumre")
    if pn_geo:
        for f in pn_geo["features"]:
            pr = f["properties"]; nr = str(pr.get("nr"))
            koms = pr.get("kommuner") or []
            muni = muni_code(koms[0]) if koms else None
            if not nr or nr.startswith("0"):  # skip special/PO-box codes if any
                continue
            areas[nr] = {"nr": nr, "name": pr.get("navn"), "muni": muni, "rings": rings_of(f["geometry"])}
    else:
        warnings.append("data/geo/postnumre.geojson missing — run scripts/fetch_geo_dawa.py; areas will be empty")
    # postal-code population
    try:
        pn = rows("", "POSTNR1"); pp = latest_period(pn)
        for r in pn:
            if r["TID"] == pp and all(r[k] in TOTAL_CODES for k in dims(r) if k != "PNR20"):
                a = areas.get(str(r["PNR20"]).strip()[:4])
                if a:
                    a["pop"] = r["INDHOLD"]
    except FileNotFoundError as e:
        warnings.append(str(e))

    indicators_out = []
    for ind in c["indicators"]:
        try:
            res = compute(ind)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{ind['key']}: {e}")
            continue
        asof = {}
        for geo, (vals, per) in res.items():
            asof[geo] = per
            target = munis if geo == "kommune" else areas
            for a, v in vals.items():
                if a in target and v is not None:
                    target[a][ind["key"]] = round(v, 2)
        indicators_out.append({k: ind[k] for k in ("key", "label", "short", "unit", "level", "hue") if k in ind} |
                              {"fmt": ind.get("fmt", "pct1"), "desc": ind.get("desc", ""), "source": ind.get("source", ""),
                               "warn": ind.get("warn", ""), "table_only": ind.get("table_only", False), "asof": asof})

    sources = []
    seen = set()
    for ind in c["indicators"]:
        for s in ind["sources"]:
            key = (s.get("db", ""), s["table"])
            if key in seen or s.get("db") in ("boligstat", "lbf"):
                continue
            seen.add(key)
            m = meta(*key)
            sources.append({"key": f"{key[0] or 'dst'}/{key[1]}", "label": f"{'Finans Danmark' if key[0]=='s20' else 'Københavns Kommune' if key[0]=='s30' else 'Danmarks Statistik'} {key[1]}",
                            "tables": m.get("text", ""), "asof": m.get("updated", "")[:10], "url": f"https://api.statbank.dk/v1/{key[0] + '/' if key[0] else ''}tableinfo/{key[1]}",
                            "licence": "free reuse with attribution"})
    if (EXT / "rent_private.csv").exists():
        sources.append({"key": "boligstat", "label": "Social- og Boligstyrelsen, boligstat.dk — private rental rent DKK/m²", "url": "https://boligstat.dk", "licence": "public"})
    if (EXT / "rent_social.csv").exists():
        sources.append({"key": "lbf", "label": "Landsbyggefonden, Huslejestatistik — social housing rent DKK/m²", "url": "https://lbf.dk/viden/statistikker/huslejestatistik/", "licence": "public"})
    attribution = ["Danmarks Statistik", "Finans Danmark, Boligmarkedsstatistikken", "Social- og Boligstyrelsen", "Landsbyggefonden",
                   "Indeholder data fra Klimadatastyrelsen (DAGI)", "Danmarks Nationalbank"]
    out = {
        "meta": {"built": dt.date.today().isoformat(), "sources": sources, "attribution": attribution,
                 "note": "Postal codes take their dominant municipality. Cells with too few observations are suppressed by the source and shown as –.",
                 "warnings": warnings},
        "indicators": indicators_out,
        "municipalities": sorted(munis.values(), key=lambda m: -(m["pop"] or 0)),
        "areas": [a for a in areas.values() if a.get("muni") in munis],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT}: {len(out['municipalities'])} municipalities, {len(out['areas'])} areas, {len(indicators_out)} indicators")
    for w in warnings:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
