#!/usr/bin/env python3
"""Check that every "Verify at source" link works — and that it shows the same number the UI does.

A link that 200s but returns a different figure is worse than no link: it invites a reader to check
and then quietly disagrees with them. So this script does not just fetch. For every Outlook area —
**98 municipalities and 67 Copenhagen quarters** — it rebuilds the URL the page builds, fetches it,
and recomputes the displayed indicator from the returned cells. Other indicators get a sample of 5
links each, checked for reachability and for the area appearing in the response.

The URL is assembled exactly as src/app.js assembles it, from the `src_verify` / `proj.src` blocks
that build_makro.py and build_cph.py wrote — so a drift between the two would show up here.

Usage:
  python3 scripts/check_source_links.py              # everything
  python3 scripts/check_source_links.py --sample 5   # non-Outlook links per indicator
  python3 scripts/check_source_links.py --quick      # skip the per-area Outlook sweep
"""
import argparse
import collections
import csv
import io
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
STATBANK = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/link-check"}
TIMEOUT = 120


def log(*a):
    print(*a, flush=True)


def src_url(src, code):
    """The same string src/app.js builds — kept deliberately literal so the two can be compared."""
    if not src or not src.get("table") or not src.get("area_var") or code in (None, ""):
        return ""
    db = f"{src['db']}/" if src.get("db") else ""
    years = ",".join(src.get("years") or ["*"])
    extra = "".join(f"&{urllib.parse.quote(k)}={urllib.parse.quote(str(v))}"
                    for k, v in (src.get("vars") or {}).items())
    return (f"{STATBANK}/{db}data/{urllib.parse.quote(src['table'])}/CSV?lang=en"
            f"&{urllib.parse.quote(src['area_var'])}={urllib.parse.quote(str(code))}{extra}"
            f"&Tid={urllib.parse.quote(years)}")


def get(url, tries=3):
    """One retry: a publisher's first response can time out without the link being broken."""
    req = urllib.request.Request(url, headers=UA)
    last = (0, "")
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                # some publishers serve legacy encodings; a decode slip is not a dead link
                return r.status, r.read().decode("utf-8-sig", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            # 5xx and 429 are the publisher having a moment, not a broken link: one bad gateway in
            # a 1 300-request sweep would otherwise fail a release over nothing
            if e.code in (429, 500, 502, 503, 504) and n + 1 < tries:
                time.sleep(3 * (n + 1))
                last = (e.code, body)
                continue
            return e.code, body
        except Exception as e:                                  # noqa: BLE001
            last = (0, f"{type(e).__name__}: {e}")
            if n + 1 < tries:
                time.sleep(2)
    return last


def cells(text):
    """{year: value} from a CSV whose last two columns are TID and INDHOLD."""
    out = collections.Counter()
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        k = {c.upper(): c for c in r}
        t, v = k.get("TID"), k.get("INDHOLD")
        if not t or not v or r[v] in ("", ".."):
            continue
        out[str(r[t])] += int(float(r[v]))
    return out


def check_outlook(areas, ind, level, label):
    """Every area of one level: fetch its link and recompute what the page shows from the response."""
    src = (ind.get("proj") or {}).get("src")
    if not src:
        return {"label": label, "n": 0, "skipped": "no src block"}
    y0 = src["years"][0]
    ymid = src["years"][1] if len(src["years"]) > 2 else src["years"][-1]
    y1 = src["years"][-1]
    bad, http_bad, checked = [], [], 0
    t0 = time.time()
    for a in areas:
        code = a.get("code")
        if a.get("fc_growth") is None:
            continue
        url = src_url(src, code)
        st, body = get(url)
        if st != 200:
            http_bad.append((code, st, body[:80]))
            continue
        c = cells(body)
        if not {y0, y1} <= set(c):
            bad.append((code, "years missing from the response", sorted(c), None))
            continue
        checked += 1
        # the three figures the page shows, recomputed from the cells the reader would see
        want = {
            "fc_growth": round((c[y1] - c[y0]) / c[y0] * 100, 2),
            "fc_growth_5y": round((c[ymid] - c[y0]) / c[y0] * 100, 2) if ymid in c else None,
            # the UI speaks in percent per year: the audited per-1 000 value divided by 10
            "fc_pop_rate_5y": round((c[ymid] - c[y0]) / 5 / c[y0] * 100, 2) if ymid in c else None,
            "fc_abs": c[y1] - c[y0],
        }
        for k, v in want.items():
            if v is None or a.get(k) is None:
                continue
            if abs(a[k] - v) > 0.011:
                bad.append((code, k, a[k], v))
    return {"label": label, "n": checked, "bad": bad, "http_bad": http_bad,
            "secs": round(time.time() - t0, 1), "url_example": src_url(src, (areas[0] or {}).get("code"))}


AREA_VAR_LEVEL = {"KOMMUNEDK": "kommune", "OMRÅDE": "kommune", "OMRADE": "kommune",
                  "BOPOMR": "kommune", "OMR20": "kommune", "PNR20": "postnr", "OMRKK": "kvarter"}


def pick_src(ind, level):
    """The query for the level the area actually is.

    An indicator can list several tables — `growth` is FOLK1A (municipal) *and* POSTNR1 (postal) —
    and sending a postal code to the municipal table is a 400. The area variable names the level.
    """
    for q in ind.get("src_verify") or []:
        if AREA_VAR_LEVEL.get(q.get("area_var")) == level:
            return q
    return (ind.get("src_verify") or [None])[0]


AREA_VAR_LEVEL = {"KOMMUNEDK": "kommune", "OMRÅDE": "kommune", "OMRADE": "kommune",
                  "BOPOMR": "kommune", "OMR20": "kommune", "PNR20": "postnr", "OMRKK": "kvarter"}


def pick_src(ind, level):
    """The query for the level the area actually is.

    An indicator can list several tables — `growth` is FOLK1A (municipal) *and* POSTNR1 (postal) —
    and sending a postal code to the municipal table is a 400, not a wrong answer. The area
    variable's id names the level, so the right table is chosen rather than the first one.
    """
    for q in ind.get("src_verify") or []:
        if AREA_VAR_LEVEL.get(q.get("area_var")) == level:
            return q
    return (ind.get("src_verify") or [None])[0]


def check_sample(inds, areas_by_level, n):
    """Reachability for every other indicator's link, on a sample of areas."""
    rows, bad = [], []
    for i in inds:
        q = (i.get("src_verify") or [None])[0]
        if not q:
            if i.get("src_page"):
                st, _ = get(i["src_page"][1])
                # urlopen follows redirects, so a 3xx here means it could not; 403 is a
                # publisher refusing a bare script UA, which is not a broken link
                ok = st in (200, 301, 302, 307, 308, 403)
                rows.append((i["key"], "page", i["src_page"][1][:52], st, ok))
                if not ok:
                    bad.append((i["key"], "page", st))
            continue
        lvl = i.get("level") if i.get("level") in areas_by_level else "kommune"
        q = pick_src(i, lvl) or q
        pool = areas_by_level[lvl]
        seen = 0
        for a in pool:
            if seen >= n:
                break
            code = a.get("code") or a.get("nr")
            if code is None or a.get(i["key"]) is None:
                continue
            seen += 1
            url = src_url(q, code)
            st, body = get(url)
            ok = st == 200 and bool(cells(body))
            if not ok:
                bad.append((i["key"], code, st))
        rows.append((i["key"], f"{q['db'] or 'dst'}/{q['table']}", f"{seen} areas", 200, True)
                    if seen else (i["key"], f"{q['db'] or 'dst'}/{q['table']}", "no area with a value", 0, True))
    return rows, bad


# ---------------------------------------------------------------- climate
CLIM_P = PROC / "climate" / "index.json"


def clim_url(q, area, horizon):
    """The same string src/app.js builds from `climate_src` — kept literal so the two can be compared."""
    kind = q.get("kind")
    if kind in ("dataset", "service"):
        return q.get("url", "")
    if kind == "service_layer":
        return f"{q['service']}/{(q.get('layer') or {}).get(horizon)}"
    if kind != "arcgis" or not area:
        return ""
    where = dict(q.get("where") or {})
    where.update((q.get("horizon") or {}).get(horizon) or {})
    clauses = [f"{k}={v}" for k, v in where.items()] + [f"{q['area_field']}='{str(area).strip()}'"]
    return (f"{q['service']}?where={urllib.parse.quote(' AND '.join(clauses))}"
            f"&outFields={urllib.parse.quote(','.join(q.get('out_fields') or ['*']))}"
            "&returnGeometry=false&f=json")


def check_climate(inds, full, sample):
    """Every Climate indicator, at all three horizons: the link is fetched and — where the publisher
    answers with the cell itself — the displayed figure is recomputed from the response."""
    idx = json.loads(CLIM_P.read_text(encoding="utf-8")) if CLIM_P.exists() else None
    if not idx:
        log("   · no data/processed/climate/index.json — skipped")
        return 0
    kom = idx["kommune"]
    rows, bad = [], []
    for i in inds:
        q = i.get("climate_src")
        if not q:
            bad.append((i["key"], "no climate_src block", 0))
            continue
        kind = q["kind"]
        if kind in ("service", "service_layer", "dataset"):
            # a layer or a dataset, not a per-area cell: reachability, and for the dataset the value
            urls = ([clim_url(q, None, h) for h in ("today", "2070", "2120")]
                    if kind == "service_layer" else [clim_url(q, None, "today")])
            ok_all, note = True, ""
            for u in dict.fromkeys(urls):
                # an ArcGIS endpoint with no query part answers HTML to a browser and 400 to a
                # bare request — ask it for json, which is the same resource the link opens
                st, body = get(u + ("?f=json" if "?" not in u and kind != "dataset" else ""))
                if st not in (200, 301, 302, 307, 308):
                    ok_all = False
                    bad.append((i["key"], u[:60], st))
                elif kind == "dataset":
                    hit = miss = 0
                    for r in csv.DictReader(io.StringIO(body)):
                        name = (r.get(q["match"]) or "").strip()
                        code = next((c for c, v in kom.items() if v["name"].strip().lower() == name.lower()), None)
                        cell = (kom.get(code) or {}).get(i["key"]) if code else None
                        if cell is None or cell.get("today") is None:
                            continue
                        try:
                            v = round(float((r.get(q["column"]) or "").replace(",", ".")), q.get("round", 1))
                        except ValueError:
                            continue
                        if abs(cell["today"] - v) <= 0.011:
                            hit += 1
                        else:
                            miss += 1
                            bad.append((i["key"], code, cell["today"], v))
                    note = f"{hit} values agree, {miss} differ"
            rows.append((i["key"], kind, note or f"{len(set(urls))} URL(s)", 200, ok_all))
            continue
        # arcgis: the published cell, per coastal stretch or per kommune, at all three horizons
        pool = [(c, v) for c, v in kom.items() if (v.get(i["key"]) or {}).get("today") is not None]
        if not full:
            pool = pool[:sample]
        seen, agree = 0, 0
        for code, v in pool:
            area = v.get("kystkode") if q["area_field"] == "kystkode" else str(int(code))
            if not area:
                continue
            for h in ("today", "2070", "2120"):
                want = (v.get(i["key"]) or {}).get(h)
                if want is None:
                    continue
                st, body = get(clim_url(q, area, h))
                seen += 1
                if st != 200:
                    bad.append((i["key"], code, h, st))
                    continue
                try:
                    feats = json.loads(body).get("features") or []
                    got = round(float(feats[0]["attributes"][q["field"]]), q.get("round", 1))
                except Exception:                                    # noqa: BLE001
                    bad.append((i["key"], code, h, "no cell in the response"))
                    continue
                if abs(want - got) > 0.011:
                    bad.append((i["key"], code, h, want, got))
                else:
                    agree += 1
        rows.append((i["key"], f"klimaatlas/{q['field']}", f"{agree}/{seen} cells agree", 200, agree == seen))
    for key, what, detail, st, ok in rows:
        log(f"   {'✓' if ok else '✗'} {key:<24} {what:<28} {detail}")
    for b in bad:
        log(f"      ✗ {b}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--quick", action="store_true", help="skip the per-area Outlook sweep")
    ap.add_argument("--climate-only", action="store_true",
                    help="run only the Climate section, at full coverage")
    args = ap.parse_args()

    mk = json.loads((PROC / "makro.json").read_text(encoding="utf-8"))
    cp_p = PROC / "cph.json"
    cp = json.loads(cp_p.read_text(encoding="utf-8")) if cp_p.exists() else {"indicators": [], "areas": []}
    mind = {i["key"]: i for i in mk["indicators"]}
    cind = {i["key"]: i for i in cp["indicators"]}
    fails = 0

    log("Verify-at-source links\n")
    api = [i for i in mk["indicators"] if i.get("src_verify") or (i.get("proj") or {}).get("src")]
    page = [i for i in mk["indicators"] if i.get("src_page")]
    none = [i for i in mk["indicators"] if not i.get("src_verify") and not i.get("src_page")
            and not (i.get("proj") or {}).get("src") and not i.get("climate_src")]
    log(f"  {len(api)} indicators link to a per-area StatBank query")
    log(f"  {len(page)} link to the publisher's page (no per-area API)")
    log(f"  {len(none)} have no link" + (f" — {', '.join(i['key'] for i in none)}" if none else ""))

    if args.climate_only:
        clim = [i for i in mk["indicators"] if i.get("group") == "Climate"]
        log(f"\nClimate only — {len(clim)} indicators, all three horizons, every area")
        fails += check_climate(clim, True, args.sample)
        log("\n" + ("✗ link check FAILED" if fails else "✓ every climate link resolves and agrees with the page"))
        return 1 if fails else 0

    if not args.quick:
        log("\n1. Outlook — every area, link fetched and the shown value recomputed from it")
        for areas, ind, level, label in (
                (mk["municipalities"], mind.get("fc_growth"), "kommune", "98 municipalities (FRKM)"),
                (cp["areas"], cind.get("fc_growth"), "kvarter", "67 Copenhagen quarters (KKFR)")):
            if not ind:
                continue
            r = check_outlook(areas, ind, level, label)
            n_bad = len(r.get("bad", [])) + len(r.get("http_bad", []))
            fails += bool(n_bad)
            log(f"   {'✓' if not n_bad else '✗'} {r['label']}: {r['n']} areas, "
                f"{len(r.get('http_bad', []))} bad responses, {len(r.get('bad', []))} value mismatches "
                f"({r.get('secs', 0)} s)")
            log(f"      example: {r['url_example']}")
            for row in (r.get("http_bad") or [])[:5] + (r.get("bad") or [])[:10]:
                log(f"      ✗ {row}")

    log(f"\n2. Every other indicator — {args.sample} links each")
    rows, bad = check_sample([i for i in mk["indicators"] if i["key"] not in
                              {k for k in mind if (mind[k].get("proj") or {}).get("src")}
                              and not i.get("climate_src")],
                             {"kommune": mk["municipalities"], "postnr": mk["areas"]}, args.sample)
    for key, what, detail, st, ok in rows:
        log(f"   {'✓' if ok else '✗'} {key:<24} {what:<16} {detail}")
    fails += bool(bad)
    for b in bad:
        log(f"      ✗ {b}")

    clim = [i for i in mk["indicators"] if i.get("group") == "Climate"]
    if clim:
        log(f"\n3. Climate — {len(clim)} indicators, all three horizons"
            + ("" if not args.quick else f" (sample of {args.sample} areas)"))
        fails += check_climate(clim, not args.quick, args.sample)

    log("\n" + ("✗ link check FAILED" if fails else "✓ every link resolves and agrees with the page"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
