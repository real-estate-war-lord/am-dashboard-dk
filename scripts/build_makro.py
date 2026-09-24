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
import re
import statistics
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statbank_common import ROOT, RAW, cfg, rows, labels, meta, area_col, muni_code, period_key  # noqa: E402
from climate_common import calc_climate  # noqa: E402   (v2.5 climate layer)

GEO = ROOT / "data" / "geo"
EXT = ROOT / "data" / "external"
OUT = ROOT / "data" / "processed" / "makro.json"
TOTAL_CODES = {"IALT", "TOT", "TOTAL", "000", "0", "I alt", "Total"}
NON_DIM = {"TID", "INDHOLD"}


def dims(r):
    return [k for k in r if k not in NON_DIM]


def norm_area(col, code):
    if col == "PNR20":
        return str(code).strip()[:4]
    if col == "OMRKK":  # Copenhagen districts/quarters: keep the code as is
        return str(code).strip()
    return muni_code(code)


def latest_period(rs):
    return max((r["TID"] for r in rs), key=period_key) if rs else None


def periods_sorted(rs):
    return sorted({r["TID"] for r in rs}, key=period_key)


def period_parts(t):
    """'2026K3' -> (2026, 'K', 3); '2026M07' -> (2026, 'M', 7); '2026' -> (2026, None, 0)"""
    m = re.match(r"(\d{4})(?:([KQM])(\d{1,2}))?", t or "")
    return (int(m.group(1)), m.group(2), int(m.group(3) or 0)) if m else (0, None, 0)


SAME_SUB_CALCS = {"passthrough", "value_div_1000", "share_of_total", "yoy_pct", "per_1000_dwellings", "ratio_pct"}   # sum4q/last4q use the trailing window


def rows_for_year(rs, year, calc):
    """Rows usable for reference year `year`: everything up to the latest available
    sub-period (quarter/month) of the newest year. For point-in-time calcs only the
    same sub-period is kept so 2024 vs 2026 compare like with like."""
    if not rs:
        return rs
    latest = max((r["TID"] for r in rs), key=period_key)
    ly, kind, lsub = period_parts(latest)
    out = []
    for r in rs:
        y, k, sub = period_parts(r["TID"])
        if y > year or (y == year and kind and sub > lsub):
            continue
        if kind and calc in SAME_SUB_CALCS and sub != lsub:
            continue
        out.append(r)
    return out


def apply_select(rs, select):
    if not select:
        return rs
    # a list value selects several codes (their rows are summed by the calc)
    return [r for r in rs if all(r.get(k) in v if isinstance(v, list) else r.get(k) == v for k, v in select.items())]


# ---------- calcs: each returns {area_code: value} ----------

def sum_by_area(rs, col, period=None):
    """Sum INDHOLD per area (over every other dimension) for one period."""
    out = {}
    for r in rs:
        if period is not None and r["TID"] != period:
            continue
        if r["INDHOLD"] is None:
            continue
        a = norm_area(col, r[col])
        out[a] = out.get(a, 0) + r["INDHOLD"]
    return out


def calc_passthrough(rs, src):
    """Latest period; if several codes were fetched for a dimension they are summed."""
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); p = latest_period(rs)
    return sum_by_area(rs, col, p), p


def calc_share_of_total(rs, src):
    """src.share = {"var": V, "num": [codes], "den": [codes] (optional → all rows)}.
    Result = sum(num rows) / sum(den rows) * 100 per area, latest period."""
    rs = apply_select(rs, src.get("select"))
    sh = src.get("share")
    if not sh:
        raise ValueError(f"share_of_total: source {src['table']} has no 'share' spec")
    col = area_col(rs[0]); p = latest_period(rs)
    rs = [r for r in rs if r["TID"] == p]
    num = sum_by_area([r for r in rs if r[sh["var"]] in sh["num"]], col)
    den = sum_by_area([r for r in rs if r[sh["var"]] in sh["den"]], col) if sh.get("den") else sum_by_area(rs, col)
    return {a: v / den[a] * 100 for a, v in num.items() if den.get(a)}, p


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


CURRENT_YEAR = None  # set by main() while computing history


def dwellings():
    """Total dwellings per municipality: BOL101 rows summed over every fetched
    dimension (the 'flats' pull fetches all uses with BEBO=1000+2000)."""
    rs = rows("", "BOL101", "BOL101_stock")
    if CURRENT_YEAR:
        rs = rows_for_year(rs, CURRENT_YEAR, "passthrough")
    col = area_col(rs[0]); p = latest_period(rs)
    return sum_by_area(rs, col, p)


def calc_per_1000_dwellings(rs, src):
    vals, p = calc_passthrough(rs, src)
    dw = dwellings()
    return {a: v / dw[a] * 1000 for a, v in vals.items() if v is not None and dw.get(a)}, p


def calc_sum4q(rs, src):
    """Sum of the last 4 quarters per area (absolute count, e.g. dwellings completed)."""
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); ps = periods_sorted(rs)[-4:]
    by = {}
    for r in rs:
        if r["TID"] in ps and r["INDHOLD"] is not None:
            by[norm_area(col, r[col])] = by.get(norm_area(col, r[col]), 0) + r["INDHOLD"]
    return by, f"{ps[0]}–{ps[-1]}"


def calc_sum4q_per_1000(rs, src):
    rs = apply_select(rs, src.get("select"))
    col = area_col(rs[0]); ps = periods_sorted(rs)[-4:]
    by = {}
    for r in rs:
        if r["TID"] in ps and r["INDHOLD"] is not None:
            by[norm_area(col, r[col])] = by.get(norm_area(col, r[col]), 0) + r["INDHOLD"]
    dw = dwellings()
    return {a: v / dw[a] * 1000 for a, v in by.items() if dw.get(a)}, f"{ps[0]}–{ps[-1]}"


# ---------- rolling 4-quarter calcs (Safety: STRAF11 counts, not seasonally adjusted) ----------

def q_shift(t, n):
    """'2026K2' shifted by n quarters: q_shift('2026K2', 1) -> '2026K3'."""
    y, _, q = period_parts(t)
    i = y * 4 + q - 1 + n
    return f"{i // 4}K{i % 4 + 1}"


def rolling_window(rs, year=None, end=None):
    """The four quarters ending at `end`, at Q4 of `year` (yearly history) or at the latest
    quarter (live value); None when any of them is not in the data."""
    have = {r["TID"] for r in rs}
    end = end or (f"{year}K4" if year else max(have, key=period_key))
    win = [q_shift(end, -k) for k in (3, 2, 1, 0)]
    return win if set(win) <= have else None


def window_sums(rs, col, win):
    """{area: sum over the window}; an area with a suppressed ('..') or missing cell gets None — never imputed."""
    cells = {}
    for r in rs:
        if r["TID"] in win:
            cells.setdefault(norm_area(col, r[col]), {}).setdefault(r["TID"], []).append(r["INDHOLD"])
    return {a: None if set(d) != set(win) or any(v is None for vs in d.values() for v in vs) else sum(v for vs in d.values() for v in vs)
            for a, d in cells.items()}


def rolling4q(calc, num_rows, num_src, den_rows=None, year=None, end=None):
    """Returns ({area: value}, period), or ({}, None) when the window is incomplete.
    rolling4q_per_1000_pop       4Q sum ÷ population at the end of the window × 1000. FOLK1A counts
                                 the 1st day of a quarter, so the end of 2026K2 is FOLK1A 2026K3
                                 (falls back to the window's last quarter if not yet published).
    rolling4q_per_1000_dwellings 4Q sum ÷ BOL101 dwellings at the end of the window (1 Jan of the
                                 following year, else 1 Jan of the window's year) × 1000.
    rolling4q_yoy_pct            4Q sum vs the 4 quarters before, %."""
    rs = apply_select(num_rows, num_src.get("select"))
    col = area_col(rs[0])
    win = rolling_window(rs, year, end)
    if not win:
        return {}, None
    cur = window_sums(rs, col, win)
    per = f"{win[0]}→{win[-1]}"
    if calc == "rolling4q_yoy_pct":
        prev_win = [q_shift(t, -4) for t in win]
        if not set(prev_win) <= {r["TID"] for r in rs}:
            return {}, None
        prev = window_sums(rs, col, prev_win)
        # the label names only the current window: the history loop files a value under the last period it names
        return {a: (v / prev[a] - 1) * 100 if v is not None and prev.get(a) else None for a, v in cur.items()}, f"{per} vs 4Q before"
    dcol = area_col(den_rows[0]); dper = {r["TID"] for r in den_rows}
    if calc == "rolling4q_per_1000_pop":
        dp = next((p for p in (q_shift(win[-1], 1), win[-1]) if p in dper), None)
    elif calc == "rolling4q_per_1000_dwellings":
        ey = period_parts(win[-1])[0]
        dp = next((p for p in (str(ey + 1), str(ey)) if p in dper), None)
    else:
        raise ValueError(f"unknown rolling calc {calc}")
    if dp is None:
        return {}, None
    den = sum_by_area(den_rows, dcol, dp)
    return {a: v / den[a] * 1000 if v is not None and den.get(a) else None for a, v in cur.items()}, per


def rolling_inputs(ind):
    srcs = ind["sources"]; s = srcs[0]
    num = rows(s.get("db", ""), s["table"], s.get("pull"))
    den = rows(srcs[1].get("db", ""), srcs[1]["table"], srcs[1].get("pull")) if len(srcs) > 1 else None
    return num, s, den


def calc_rolling4q(ind, year=None):
    num, s, den = rolling_inputs(ind)
    return rolling4q(ind["calc"], num, s, den, year)


def rolling4q_series(ind, start):
    """Quarterly rolling-4Q series: [(end quarter, {area: value})] for every window end from
    `start` to the latest quarter that has a complete window and denominator."""
    num, s, den = rolling_inputs(ind)
    num = apply_select(num, s.get("select"))          # select once, not per quarter
    qs = sorted({r["TID"] for r in num}, key=period_key)
    out = []
    for q in qs:
        if period_key(q) < period_key(start):
            continue
        vals, per = rolling4q(ind["calc"], num, {}, den, end=q)
        if per:
            out.append((q, vals))
    return out


CALCS = {
    "passthrough": calc_passthrough, "value_div_1000": calc_passthrough,
    "share_of_total": calc_share_of_total, "yoy_pct": calc_yoy_pct,
    "last4q_mean": calc_last4q_mean, "discount_pct": calc_discount_pct,
    "per_1000_dwellings": calc_per_1000_dwellings, "sum4q_per_1000": calc_sum4q_per_1000, "sum4q": calc_sum4q,
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


_BBR = None


def load_bbr():
    """data/processed/bbr.json from scripts/build_bbr.py (housing stock per postal code / quarter / municipality), or None."""
    global _BBR
    if _BBR is None:
        p = ROOT / "data" / "processed" / "bbr.json"
        _BBR = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _BBR or None


_INFRA_IDX = None
_PUBLIC_IDX = None
POP = {}          # {geo: {code: population}} — set by main() so per-capita calcs can use it


def infra_index():
    """data/processed/infra_index.json from scripts/build_infra.py, or None."""
    global _INFRA_IDX
    if _INFRA_IDX is None:
        p = ROOT / "data" / "processed" / "infra_index.json"
        _INFRA_IDX = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _INFRA_IDX or None


_FORECAST = None
_NET_DWELL = None


def forecast_doc():
    """data/processed/forecast.json from scripts/build_forecast.py, or None."""
    global _FORECAST
    if _FORECAST is None:
        p = ROOT / "data" / "processed" / "forecast.json"
        _FORECAST = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _FORECAST or None


_FORECAST_VALS = None


def forecast_values():
    """{kommune: {fc_*: value}} — the Outlook arithmetic, computed once.

    indicators() is imported from scripts/build_forecast.py rather than reimplemented,
    so a municipal figure and a Copenhagen one cannot drift apart in how they are
    derived (docs/FORECAST.md §3, §8)."""
    global _FORECAST_VALS
    if _FORECAST_VALS is None:
        doc = forecast_doc()
        if not doc:
            _FORECAST_VALS = {}
        else:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
            from build_forecast import indicators as fc_indicators  # noqa: PLC0415
            _FORECAST_VALS = fc_indicators(doc)
    return _FORECAST_VALS


def net_dwellings():
    """data/processed/net_dwellings.json from scripts/build_net_dwellings.py, or None."""
    global _NET_DWELL
    if _NET_DWELL is None:
        p = ROOT / "data" / "processed" / "net_dwellings.json"
        _NET_DWELL = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _NET_DWELL or None


# The value forecast.json stores for fc_pop_rate_5y is persons per 1 000 inhabitants per year —
# the arithmetic docs/FORECAST.md §3 audits. The UI speaks in percent per year, which is the same
# number divided by 10, so the division happens here, once, on the way into makro.json. The audited
# file keeps the audited unit; nothing downstream has to remember a factor.
DISPLAY_DIV = {"fc_pop_rate_5y": 10}


# Where a non-StatBank indicator's figures actually come from. These have no per-area API query,
# so "Verify at source" sends the reader to the publisher's own page instead of nowhere.
SRC_PAGE = {
    "bbr": ("BBR via Datafordeler", "https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/"),
    "public": ("BBR via Datafordeler", "https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/"),
    "public_index": ("BBR via Datafordeler", "https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/"),
    "schools": ("Uddannelsesstatistik.dk (STIL)", "https://uddannelsesstatistik.dk/"),
    "infra_index": ("the curated infrastructure layer", "https://github.com/real-estate-war-lord/am-dashboard-dk/blob/main/docs/INFRA.md"),
    "boligstat": ("Social- og Boligstyrelsen, boligstat.dk", "https://boligstat.dk/"),
    "lbf": ("Landsbyggefonden", "https://lbf.dk/viden/statistikker/huslejestatistik/huslejestatistik-2026"),
}


def area_var(db, table):
    """The area variable's id for a table, read from its own cached tableinfo.

    Never hard-coded per vintage: KKFR2026 becomes KKFR2027 next March and the variable id
    (OMRKK) does not change, but the table id does — so the id is resolved from the file the
    fetch already wrote.
    """
    for cand in (RAW / f"{db + '_' if db else 'dst_'}{table}.meta.json",
                 ROOT / "data" / "raw" / "forecast" / "dst" / f"tableinfo_{table}.json",
                 ROOT / "data" / "raw" / "forecast" / "cph" / f"tableinfo_{table}.json",
                 ROOT / "data" / "raw" / "forecast" / "dst" / f"{table}.meta.json",
                 ROOT / "data" / "raw" / "forecast" / "cph" / f"{table}.meta.json"):
        if cand.exists():
            info = json.loads(cand.read_text(encoding="utf-8"))
            for v in info.get("variables", []):
                if v["id"] in ("KOMMUNEDK", "OMRKK", "OMRÅDE", "OMRADE", "PNR20", "BOPOMR", "OMR20"):
                    return v["id"]
    return None


def proj_mid(meta, offset=5):
    """The 5-year mark of a projection window. forecast.json records first_year and
    last_year; the mid year is first_year + the same offset indicators() uses."""
    return meta.get("mid_year") or str(int(meta["first_year"]) + offset)


def proj_end(meta, key):
    return proj_mid(meta) if key in FIVE_YEAR_KEYS else meta["last_year"]


def proj_period(doc, key):
    """The one line the year selector shows for an Outlook indicator."""
    m = doc["meta"]
    return f"Projection {m['first_year']}\u2192{proj_end(m, key)} \u00b7 DST {m['vintage']}"


FIVE_YEAR_KEYS = {"fc_growth_5y", "fc_pop_rate_5y"}


def public_index():
    """data/processed/public_index.json from scripts/build_public.py, or None."""
    global _PUBLIC_IDX
    if _PUBLIC_IDX is None:
        p = ROOT / "data" / "processed" / "public_index.json"
        _PUBLIC_IDX = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _PUBLIC_IDX or None


def calc_public_index(ind, year=None):
    """Counts and floor area from the public-buildings layer — a snapshot, so no history.
    Only municipalities whose BBR pull has been run have values (pilot: 101, 147)."""
    ix = public_index()
    if year or not ix:
        return {}
    per = f"BBR {ix['built']}"
    out = {}
    for geo in ("kommune", "postnr"):
        vals = {}
        for k, v in ix["areas"].items():
            if not k.startswith(geo + ":"):
                continue
            code = k.split(":", 1)[1]
            if ind["key"] == "public_recent_cases_n":
                vals[code] = len(v.get("recent_cases") or [])
            else:
                pop = (POP.get(geo) or {}).get(code)
                if pop:
                    vals[code] = v.get("m2_existing", 0) / pop * 1000
        out[geo] = (vals, per)
    return out


def calc_infra_index(ind, year=None):
    """Counts per area from the curated project layer — a snapshot, so no history."""
    ix = infra_index()
    if year or not ix:
        return {}
    per = f"projects {ix['built']}"
    out = {}
    for geo in ("kommune", "postnr"):
        vals = {k.split(":", 1)[1]: v.get(ind["key"]) for k, v in ix["areas"].items() if k.startswith(geo + ":")}
        out[geo] = ({a: v for a, v in vals.items() if v is not None}, per)
    return out


def calc_schools(ind, year=None):
    """School-quality aggregates, written into public_index.json by scripts/build_schools.py.

    A snapshot of the latest published school year, so no history. The values are pupil-weighted
    over folkeskoler and frie grundskoler that have a value; specialskoler are excluded and a
    suppressed school simply does not enter the mean (docs/SCHOOLS.md §3)."""
    ix = public_index()
    if year or not ix or not ix.get("schools"):
        return {}
    per = f"school year {ix['schools']['years'][-1]}"
    out = {}
    for geo in ("kommune", "postnr"):
        vals = {k.split(":", 1)[1]: v.get(ind["key"]) for k, v in ix["areas"].items() if k.startswith(geo + ":")}
        out[geo] = ({a: v for a, v in vals.items() if v is not None}, per)
    return out


def compute(ind, year=None):
    """Returns {geo: ({area: value}, period)} for one indicator, optionally for a
    reference year (rows after that year are dropped; see rows_for_year)."""
    res = {}
    srcs = ind["sources"]
    calc = ind["calc"]
    if calc == "bbr":
        b = load_bbr()
        if year or not b:
            return {}   # snapshot only, no history
        per = f"BBR {b['meta']['built']}"
        return {"kommune": ({k: v.get(ind["key"]) for k, v in b["kommune"].items()}, per),
                "postnr": ({k: v.get(ind["key"]) for k, v in b["postnr"].items()}, per)}
    if calc == "forecast":
        doc = forecast_doc()
        if year or not doc:
            return {}   # one vintage, not a per-year history — same rule as `bbr`
        vals = forecast_values()
        per = proj_period(doc, ind["key"])
        div = DISPLAY_DIV.get(ind["key"], 1)
        return {"kommune": ({k: round(v[ind["key"]] / div, 2) for k, v in vals.items()
                             if v.get(ind["key"]) is not None}, per)}
    if calc == "net_dwellings":
        nd = net_dwellings()
        if year or not nd:
            return {}   # measured snapshot over one window, no history
        m = nd["meta"]
        per = m.get("label_years") or f"{m.get('year_start','')}\u2013{m.get('year_end','')}"
        fld = ind["field"]
        return {"kommune": ({k: v.get(fld) for k, v in nd["kommuner"].items()
                             if v.get(fld) is not None}, per)}
    if calc == "public_index":
        return calc_public_index(ind, year)
    if calc == "infra_index":
        return calc_infra_index(ind, year)
    if calc == "schools":
        return calc_schools(ind, year)
    if calc == "climate":
        return calc_climate(ind, year)
    if calc.startswith("rolling4q"):
        vals, p = calc_rolling4q(ind, year)
        return {srcs[0]["geo"]: (vals, p)} if p else {}
    sel = (lambda rs: rows_for_year(rs, year, calc)) if year else (lambda rs: rs)
    if calc == "ratio_pct":
        numr, p = calc_passthrough(sel(rows(srcs[0].get("db", ""), srcs[0]["table"], srcs[0].get("pull"))), srcs[0])
        den, _ = calc_passthrough(sel(rows(srcs[1].get("db", ""), srcs[1]["table"], srcs[1].get("pull"))), srcs[1])
        res[srcs[0]["geo"]] = ({a: v / den[a] * 100 for a, v in numr.items() if v is not None and den.get(a)}, p)
        return res
    for s in srcs:
        if s.get("db") in ("boligstat", "lbf"):
            if year:
                continue  # external files: latest year only (add raw/<name>_<year> later)
            ext = external_csv(ind["key"])
            if ext:
                res[s["geo"]] = (ext, s.get("asof", "external file"))
            continue
        rs = sel(rows(s.get("db", ""), s["table"], s.get("pull")))
        if not rs:
            continue
        vals, p = CALCS[calc](rs, s)
        res[s["geo"]] = (vals, p)
    return res


def fetched(db, table):
    """Date of the newest raw pull of a table (from the file name, e.g. dst_STRAF11_offences_2026-09-22.csv)."""
    files = list(RAW.glob(f"{db or 'dst'}_{table}_20*.csv")) + list(RAW.glob(f"{db or 'dst'}_{table}_*_20*.csv"))
    return max((f.stem[-10:] for f in files), default="")


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
    REGIONS = {"1081": "Nordjylland", "1082": "Midtjylland", "1083": "Syddanmark", "1084": "Hovedstaden", "1085": "Sjælland"}
    geo_region = {muni_code(f["properties"]["kode"]): REGIONS.get(str(f["properties"].get("regionskode")), "") for f in kom_geo["features"]} if kom_geo else {}
    munis = {}
    for r in folk:
        code = muni_code(r[col])
        if r["TID"] == p and code.isdigit() and int(code) >= 101 and all(r[k] in TOTAL_CODES for k in dims(r) if k != col):
            munis[code] = {"code": code, "name": geo_names.get(code) or names.get(r[col], code), "region": geo_region.get(code, ""), "pop": r["INDHOLD"], "asof": {"pop": p}}
    # Population by year, actual and projected, for the area-page chart. The actual series is
    # FOLK1A's own Q1 cell per year; the projection is forecast.json's `total`, DST's published
    # ALDER=TOT. They are two different series and the chart draws them as such — solid to the
    # last observed year, dashed after it (docs/FORECAST.md §5.6). Never spliced into one line.
    for r in folk:
        code = muni_code(r[col])
        if code not in munis or not str(r["TID"]).endswith("K1"):
            continue
        if not all(r[k] in TOTAL_CODES for k in dims(r) if k != col):
            continue
        munis[code].setdefault("pop_hist", {})[str(r["TID"])[:4]] = r["INDHOLD"]
    fcd = forecast_doc()
    if fcd:
        for code, series in fcd["kommuner"].items():
            if code in munis:
                munis[code]["fc_pop"] = {y: v["total"] for y, v in series.items()}
                munis[code]["fc_groups"] = {y: {g: v[g] for g in fcd["meta"]["groups"] if g in v}
                                            for y, v in series.items()}
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
            areas[nr] = {"nr": nr, "name": pr.get("navn"), "muni": muni, "rings": rings_of(f["geometry"]),
                         "codes": pr.get("codes") or [nr]}
    else:
        warnings.append("data/geo/postnumre.geojson missing — run scripts/fetch_geo_dawa.py; areas will be empty")
    # postal-code population (summed over merged street-level codes)
    code2area = {c: a for a in areas.values() for c in a["codes"]}
    try:
        pn = rows("", "POSTNR1"); pp = latest_period(pn)
        for r in pn:
            if r["TID"] == pp and all(r[k] in TOTAL_CODES for k in dims(r) if k != "PNR20"):
                a = code2area.get(str(r["PNR20"]).strip()[:4])
                if a and r["INDHOLD"] is not None:
                    a["pop"] = (a.get("pop") or 0) + r["INDHOLD"]
    except FileNotFoundError as e:
        warnings.append(str(e))
    popof = {}
    try:
        for r in pn:
            if r["TID"] == pp and all(r[k] in TOTAL_CODES for k in dims(r) if k != "PNR20"):
                popof[str(r["PNR20"]).strip()[:4]] = r["INDHOLD"] or 0
    except NameError:
        pass
    MIN_POP_GROWTH = 300  # growth % on tiny postal codes is noise

    POP["kommune"] = {c: m.get("pop") for c, m in munis.items()}
    POP["postnr"] = {nr: a.get("pop") for nr, a in areas.items()}
    indicators_out = []
    global CURRENT_YEAR
    n_hist = int(c.get("history_years", 4))
    latest_year = period_parts(p)[0]
    years = list(range(latest_year - n_hist + 1, latest_year + 1))
    all_years = set(years)
    # Denmark as a whole (area code 000 → "0") where a calc yields it: the dashed reference line in Charts
    national = {"code": "0", "name": "Denmark", "hist": {}, "q": {}}
    for m in munis.values():
        m["hist"] = {}
    for a in areas.values():
        a["hist"] = {}
    for ind in c["indicators"]:
        # history: same calc, rows cut at each reference year
        hist_asof = {}
        # `history_from` extends one indicator's yearly history beyond history_years (Safety: STRAF11 from 2007)
        ind_years = list(range(min(int(ind.get("history_from", years[0])), years[0]), latest_year + 1))
        for y in ind_years:
            CURRENT_YEAR = y
            try:
                res_y = compute(ind, y)
            except Exception as e:  # noqa: BLE001
                continue
            for geo, (vals, per) in res_y.items():
                # file the value under the year the data actually refers to (a source whose
                # latest year is 2024 must not repeat 2024 under 2025/2026)
                ay = str(period_parts(str(per).replace("→", "–").split("–")[-1].strip())[0])
                if ay != str(y):
                    continue
                hist_asof.setdefault(ay, {})[geo] = per
                all_years.add(y)
                if geo == "kommune":
                    if vals.get("0") is not None:
                        national["hist"].setdefault(ind["key"], {})[ay] = round(vals["0"], 2)
                    for a_, v in vals.items():
                        if a_ in munis and v is not None:
                            munis[a_]["hist"].setdefault(ind["key"], {})[ay] = round(v, 2)
                else:
                    acc = {}
                    for code, v in vals.items():
                        ar = code2area.get(code)
                        if ar is None or v is None:
                            continue
                        w = popof.get(code, 0) or 1
                        s_, w_ = acc.get(ar["nr"], (0.0, 0.0)); acc[ar["nr"]] = (s_ + v * w, w_ + w)
                    for nr, (s_, w_) in acc.items():
                        if w_ and not (ind["key"] == "growth" and (areas[nr].get("pop") or 0) < MIN_POP_GROWTH):
                            areas[nr]["hist"].setdefault(ind["key"], {})[ay] = round(s_ / w_, 2)
        CURRENT_YEAR = None
        try:
            res = compute(ind)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{ind['key']}: {e}")
            continue
        asof = {}
        for geo, (vals, per) in res.items():
            asof[geo] = per
            if geo == "kommune":
                if vals.get("0") is not None:
                    national[ind["key"]] = round(vals["0"], 2)
                for a, v in vals.items():
                    if a in munis and v is not None:
                        munis[a][ind["key"]] = round(v, 2)
            else:
                # postal codes: population-weighted mean over an area's (merged) codes
                acc = {}
                for code, v in vals.items():
                    a = code2area.get(code)
                    if a is None or v is None:
                        continue
                    w = popof.get(code, 0) or 1
                    s_, w_ = acc.get(a["nr"], (0.0, 0.0))
                    acc[a["nr"]] = (s_ + v * w, w_ + w)
                for nr, (s_, w_) in acc.items():
                    if w_:
                        areas[nr][ind["key"]] = round(s_ / w_, 2)
                if ind["key"] == "growth":
                    for a in areas.values():
                        if (a.get("pop") or 0) < MIN_POP_GROWTH:
                            a.pop("growth", None)
        indicators_out.append({k: ind[k] for k in ("key", "label", "short", "unit", "level", "hue", "group", "direction", "note", "note_short", "chip",
                                                   "scale", "center", "hue_pos", "hue_neg", "field", "horizon", "chip_label",
                                                   "climate_src") if k in ind} |
                              {"fmt": ind.get("fmt", "pct1"), "desc": ind.get("desc", ""), "source": ind.get("source", ""),
                               "warn": ind.get("warn", ""), "table_only": ind.get("table_only", False), "asof": asof,
                               "hist_asof": hist_asof,
                               "tables": list(dict.fromkeys(f"{s.get('db') or 'dst'}/{s['table']}" for s in ind["sources"] if s.get("db", "") in ("", "s20", "s30")))} |
                              {k: ind[k] for k in ("history_from", "map_from", "breaks") if k in ind})
        # "Verify at source" for every StatBank-backed indicator: the area variable is resolved from
        # each table's own cached tableinfo, so a table whose id carries a vintage still links right.
        # Tables with no area variable (national-only macro series) get no link rather than a wrong one.
        vsrc = []
        for t in indicators_out[-1].get("tables", []):
            db, _, tb = t.partition("/")
            db = "" if db == "dst" else db
            av = area_var(db, tb)
            if not av:
                continue
            # The indicator's own variable selection goes into the link, so the query returns the
            # exact cells the figure is computed from rather than a different slice of the table.
            # It is also required: several tables (INDKP101's ENHED, IFOR22's DECILGR, BOL101's
            # BEBO) refuse a query that does not pick a value for them.
            sel = next((x.get("vars") or {} for x in ind["sources"]
                        if x.get("table") == tb and (x.get("db") or "") == db), {})
            extra = {k: v for k, v in sel.items()
                     if k not in (av, "Tid") and v and v != ["*"] and v != ["SUM"]}
            vsrc.append({"db": db, "table": tb, "area_var": av, "years": ["*"],
                         "vars": {k: ",".join(v) for k, v in extra.items()},
                         "publisher_label": "Finans Danmark via Statistikbanken" if db == "s20"
                         else "Københavns Kommune via Statistikbanken" if db == "s30"
                         else "Danmarks Statistik"})
        if vsrc:
            indicators_out[-1]["src_verify"] = vsrc
        else:
            # BBR, the curated infra layer, the school cubes, boligstat and LBF are not StatBank
            # tables, so there is no per-area query to build. They link to the page the Sources
            # view already lists for them — a real destination rather than a dead affordance.
            page = SRC_PAGE.get(ind["sources"][0].get("db") or ind["calc"]) or SRC_PAGE.get(ind["calc"])
            if page:
                indicators_out[-1]["src_page"] = page
        # the Outlook layer is one vintage, so the year selector shows its window instead of a year list
        if ind["calc"] == "forecast" and forecast_doc():
            fm = forecast_doc()["meta"]
            av = area_var("", fm["table"])
            indicators_out[-1]["proj"] = {"from": fm["first_year"], "to": proj_end(fm, ind["key"]),
                                          "vintage": str(fm["vintage"]), "publisher": "DST", "table": fm["table"],
                                          # everything "Verify at source" needs to rebuild the query
                                          "src": {"db": "", "table": fm["table"], "area_var": av,
                                                  "years": [fm["first_year"], proj_mid(fm), fm["last_year"]],
                                                  "publisher_label": "Danmarks Statistik"} if av else None,
                                          "actuals": {"db": "", "table": "FOLK1A", "area_var": area_var("", "FOLK1A"),
                                                      "years": ["*"], "publisher_label": "Danmarks Statistik"}}
        if ind["calc"] == "net_dwellings" and net_dwellings():
            nm_ = net_dwellings()["meta"]
            indicators_out[-1]["window"] = nm_.get("label_years", "")
            # its db is `net_dwellings`, so the generic loop above sees no tables — BOL101 is
            # still a published StatBank table and the figure is verifiable against it
            av = area_var("", "BOL101")
            if av:
                w_ = nm_.get("window") or []
                indicators_out[-1]["src_verify"] = [
                    {"db": "", "table": "BOL101", "area_var": av,
                     "years": [str(w_[0]), str(w_[-1])] if w_ else ["*"],
                     # BOL101 cannot eliminate BEBO, and the stock this indicator measures is
                     # "all resident types", so all three codes are selected — the same slice
                     # scripts/build_net_dwellings.py counts.
                     "vars": {"BEBO": "1000,2000,5000"},
                     "publisher_label": "Danmarks Statistik"}]
        # quarterly rolling series (municipalities + Denmark), from `map_from` Q1; one array per indicator aligned to q_periods
        if ind["calc"].startswith("rolling4q"):
            ser = rolling4q_series(ind, f"{ind.get('map_from', years[0])}K1")
            if len(ser) >= 2:
                indicators_out[-1]["q_periods"] = [q for q, _ in ser]
                for code, m in list(munis.items()) + [("0", national)]:
                    m.setdefault("q", {})[ind["key"]] = [None if vals.get(code) is None else round(vals[code], 2) for _, vals in ser]

    # BBR housing-stock distributions for the area pages
    bbr = load_bbr()
    if bbr:
        for code, m in munis.items():
            if code in bbr["kommune"]:
                m["bbr"] = {"n": bbr["kommune"][code]["n"], "n_bld": bbr["kommune"][code]["n_bld"], "dist": bbr["kommune"][code]["dist"]}
        for nr, a in areas.items():
            if nr in bbr["postnr"]:
                a["bbr"] = {"n": bbr["postnr"][nr]["n"], "n_bld": bbr["postnr"][nr]["n_bld"], "dist": bbr["postnr"][nr]["dist"]}
    sources = []
    seen = set()
    for ind in c["indicators"]:
        for s in ind["sources"]:
            key = (s.get("db", ""), s.get("table", ""))
            if key in seen or s.get("db") in ("boligstat", "lbf", "bbr", "infra", "public", "schools", "forecast", "net_dwellings"):
                continue
            seen.add(key)
            m = meta(*key)
            sources.append({"key": f"{key[0] or 'dst'}/{key[1]}", "label": f"{'Finans Danmark' if key[0]=='s20' else 'Københavns Kommune' if key[0]=='s30' else 'Danmarks Statistik'} {key[1]}",
                            "tables": m.get("text", ""), "asof": m.get("updated", "")[:10], "fetched": fetched(*key), "url": f"https://api.statbank.dk/v1/{key[0] + '/' if key[0] else ''}tableinfo/{key[1]}",
                            "licence": "free reuse with attribution"})
    if bbr:
        sources.append({"key": "bbr", "label": f"BBR via Datafordeler — housing stock ({len(bbr['meta']['municipalities'])} municipalities, {bbr['meta']['dwellings']:,} dwellings)".replace(",", " "),
                        "tables": "BBR_Enhed, BBR_Bygning (GraphQL v3)", "asof": bbr["meta"]["built"], "url": "https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/", "licence": "free (Klimadatastyrelsen)"})
    fc = forecast_doc()
    if fc:
        fm = fc["meta"]
        sources.append({"key": "forecast",
                        "label": f"Danmarks Statistik {fm['table']} / {fm['national_table']} \u2014 municipal population projection, {fm['vintage']} vintage",
                        "tables": f"{fm['table']} (per municipality, by age) \u00b7 {fm['national_table']} (national control total) \u00b7 projection {fm['first_year']}\u2013{fm['last_year']}",
                        "asof": fm.get("updated", "")[:10], "fetched": fm.get("fetched", ""),
                        "url": f"https://api.statbank.dk/v1/tableinfo/{fm['table']}",
                        "licence": fm.get("licence", "free reuse with attribution")})
    nd = net_dwellings()
    if nd:
        nm = nd["meta"]
        tabs = nm.get("tables") or {}
        asof = max([(t or {}).get("updated", "")[:10] for t in tabs.values()] or [""]) if isinstance(tabs, dict) else ""
        sources.append({"key": "net_dwellings",
                        "label": f"Danmarks Statistik BOL101 + FOLK1A \u2014 net dwelling additions {nm.get('label_years','')}",
                        "tables": f"BOL101 (dwelling stock, 1 January {nm.get('label_years','').replace('\u2013', ' and ')}) \u00b7 FOLK1A (population, {nm.get('pop_period','')})",
                        "asof": asof, "fetched": nm.get("fetched", ""),
                        "url": "https://api.statbank.dk/v1/tableinfo/BOL101",
                        "licence": nm.get("licence", "free reuse with attribution")})
    px = public_index()
    if px:
        sources.append({"key": "public", "label": f"Public buildings — BBR via Datafordeler (pilot: {', '.join(px['kommuner'])})",
                        "tables": "BBR_Bygning anvendelse 410–449 status 2/3/6 · BBR_BBRSag via BBR_Sagsniveau · DAR for addresses",
                        "asof": px["built"], "fetched": px["built"],
                        "url": "https://github.com/real-estate-war-lord/am-dashboard-dk/blob/main/docs/PUBLIC_BUILDINGS.md",
                        "licence": "free (Klimadatastyrelsen)"})
    ix = infra_index()
    if ix:
        sources.append({"key": "infra", "label": f"Infrastructure projects — curated layer ({len(ix['areas'])} areas with projects)",
                        "tables": "data/geo/infra_projects.geojson · Fingerplan 2019, Anlægsstatus, regions and agencies, OpenStreetMap",
                        "asof": ix["built"], "fetched": ix["built"], "url": "https://github.com/real-estate-war-lord/am-dashboard-dk/blob/main/docs/INFRA.md",
                        "licence": "see docs/INFRA.md"})
    sx = (px or {}).get("schools")
    if sx:
        sources.append({"key": "schools", "label": f"School quality — Uddannelsesstatistik.dk (STIL), {sx['n']} schools in the Copenhagen metro set",
                        "tables": "GS cubes KARA/KARAGNS, KARA/KARADM, OVER/OVERSKO, TRIV/TRIVIND, ELEV/ELEVEX · STIL institutionsregister",
                        "asof": sx["years"][-1], "fetched": sx["retrieved"],
                        "url": "https://github.com/real-estate-war-lord/am-dashboard-dk/blob/main/docs/SCHOOLS.md",
                        "licence": "free reuse incl. commercial — attribution \"Kilde: Uddannelsesstatistik.dk\""})
    if (EXT / "rent_private.csv").exists():
        sources.append({"key": "boligstat", "label": "Social- og Boligstyrelsen, boligstat.dk — private rental rent DKK/m²", "url": "https://boligstat.dk", "licence": "public"})
    if (EXT / "rent_social.csv").exists():
        sources.append({"key": "lbf", "label": "Landsbyggefonden, Huslejestatistik — social housing rent DKK/m²", "url": "https://lbf.dk/viden/statistikker/huslejestatistik/", "licence": "public"})
    attribution = ["Danmarks Statistik", "Finans Danmark, Boligmarkedsstatistikken", "Social- og Boligstyrelsen", "Landsbyggefonden",
                   "Indeholder data fra Klimadatastyrelsen (DAGI, BBR)", "Danmarks Nationalbank",
                   "Kilde: Uddannelsesstatistik.dk"]
    out = {
        "meta": {"built": dt.date.today().isoformat(), "sources": sources, "attribution": attribution, "years": [str(y) for y in sorted(all_years)], "latest_year": str(latest_year),
                 "note": "Postal codes take their dominant municipality. Cells with too few observations are suppressed by the source and shown as –.",
                 "warnings": warnings},
        "indicators": indicators_out,
        "national": national,
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
