#!/usr/bin/env python3
"""ui_smoke.py — Playwright smoke test for the AM Dashboard (DK).

Visits every route at three viewports, fails on any pageerror / console.error, checks DOM
landmarks per route, and saves screenshots. Designed to be extended per phase: add a ROUTES
entry (hash, landmarks, optional `wait` selector) and it is covered at every viewport.

Usage:
  python3 tests/ui_smoke.py [--url http://localhost:8080/] [--out shots/] [--phase P1]
                            [--only map,area] [--viewports 1440x900,390x844] [--headed]
                            [--allow-errors]   # report but do not fail (for a diagnostic run)
                            [--no-network]     # block every host but the local server (no tiles/fonts)
                            [--full-page]      # also save a full-height screenshot
Exit code 1 on any failure. Prints a compact report and writes <out>/report.json.

The server is not started here — `make smoke` and `./overnight.sh gate` serve dist/ on :8080.
Needs: pip install playwright && python3 -m playwright install chromium  (see ENG_BRIEF_v3.md §6).

v3.0 rule: keep the OLD hashes in ROUTES. They are the redirect test — every link shared from
v2.6 must keep landing on the right view for as long as the dashboard exists.
"""
import argparse
import functools
import http.server
import json
import pathlib
import re
import socketserver
import sys
import threading
import time
import urllib.request

from playwright.sync_api import sync_playwright

TITLE = "Macro Dashboard · Denmark"
DIST = pathlib.Path(__file__).resolve().parent.parent / "dist"


def serve_dist(directory):
    """Serve `directory` on a free loopback port from this process. Returns the base URL."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}/"


def our_url(url, directory=DIST):
    """A URL that serves THIS repo's dist/ — the one given, or one we serve ourselves.

    The runner is normally handed a server someone else started (`make smoke`, `overnight.sh gate`,
    which serves dist/ on :8080 *only when nothing answers there*). On a shared machine another
    project can already own that port, and then every route reads as a catastrophic regression in
    this repo. That is an environment fault, not a code one, so the page's title is checked first and
    dist/ is served here when it belongs to someone else.
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            head = r.read(4096).decode("utf-8", "replace")
        if TITLE in head:
            return url
        got = re.search(r"<title>(.*?)</title>", head, re.S)
        why = f"it is serving {got.group(1).strip()!r}" if got else "its title is not this dashboard's"
    except Exception as ex:
        why = f"it did not answer ({type(ex).__name__})"
    if not (directory / "index.html").exists():
        raise SystemExit(f"{url}: {why}, and {directory}/index.html does not exist — run the build first.")
    here = serve_dist(directory)
    print(f"! {url}: {why} — serving {directory} on {here} instead")
    return here

# ---------------------------------------------------------------------------------------------
# Routes. `land` = CSS selectors that must exist (and be non-empty when suffixed with "!").
# `wait` = a selector to wait for before asserting (async loads: kommune rings, zone files).
# `state` = a JS expression on the app's own globals that must be truthy (classic script → the
#   top-level consts are lexical; page.evaluate runs in the page realm and sees them).
# v3.0 routes: keep the OLD hashes here too — they must redirect and land on the new view.
# ---------------------------------------------------------------------------------------------
ROUTES = [
    # --- map (v2.6 "makro") ---
    # __maps === 1 everywhere a view owns a map: the lifecycle invariant of v3.0 P1 — one live
    # Leaflet instance at a time, the previous one dropped before #body is replaced.
    # the shared IndicatorPicker + PeriodControl replaced #indsel / the year select in v3.0 P3.
    # the v3.0 toolbar is one row: [search][Layers ▾][Indicator ▾][Period], chips under it (P4).
    dict(id="map",            hash="map?ind=growth",                         land=["#lfmap .leaflet-pane", "[data-testid=legend]!", "[data-testid=search]", "[data-testid=layers-btn]!", "[data-testid=ind-picker-btn]!", "[data-testid=ind-chips]!", "[data-testid=period-year]", "[data-testid=map-full]", "#nav"], state="S.view==='makro' && !!LF.map && window.__maps.length===1 && document.querySelector('[data-testid=map-toolbar] [data-row]').children.length<=6"),
    dict(id="map_proj",       hash="map?ind=fc_growth",                      land=["#maplegend!", "[data-testid=period-proj]!"], state="curInd().key==='fc_growth' && !document.querySelector('[data-testid=period-year]')"),
    dict(id="map_muni",       hash="map/101?ind=growth",                     land=["#lfmap .leaflet-overlay-pane", "#mkstrip!"], state="MK.muni==='101' && !!LF.areaG"),
    dict(id="map_postnr",     hash="map/101/postnr?ind=renters",             land=["#lfmap"], state="MK.cphView==='postnr'"),
    # the three feature layers are one `lay=` list now; the v2.6 flags redirect onto it (P4)
    dict(id="map_layers",     hash="map/101?ind=growth&lay=infra,public,services", land=["[data-testid=legend-infra]!", "[data-testid=legend-public]!", "[data-testid=legend-services]!"], wait="#serviceslegend *", state="MK.infra && MK.pub && MK.srv"),
    dict(id="map_overlays",   hash="map/101?ind=growth&infra=1&public=1&services=1", land=["#infralegend!", "#publiclegend!", "#serviceslegend!"], wait="#serviceslegend *", state="MK.infra && MK.pub && MK.srv", redirect="map/101?lay=infra,public,services"),
    # Climate is an indicator family: `climate=1` becomes its indicator and the zones draw themselves
    dict(id="map_climate",    hash="map?ind=surge_dw_pct&hz=2070&climate=1", land=["[data-testid=legend-zones]!"], state="HZ.h==='2070' && curInd().key==='surge_dw_pct' && MK.zones && climOn()", redirect="map?ind=surge_dw_pct&hz=2070"),
    dict(id="map_climate_ind", hash="map?ind=sealevel_cm&hz=2120",           land=["#maplegend!", "[data-testid=legend-zones]!"], state="curInd().key==='sealevel_cm' && HZ.h==='2120'"),
    dict(id="map_zones_off",  hash="map?ind=surge_dw_pct&zones=0",           land=["#maplegend!"], state="!MK.zones && !climOn() && !document.querySelector('[data-testid=legend-zones]')"),
    dict(id="map_micro",      hash="map/101?ind=growth&micro=1&mind=rented_pct", land=["#lfmap", "#mindsel"], state="microMode()"),
    # the pin's radius filter moved into Layers ▾, where it only appears when there is a pin (P4)
    dict(id="map_pin",        hash="map?ind=growth&pin=55.64250,12.53850&pl=Sydhavn&rad=1000", land=["#lfmap", "[data-layer=radius]"], state="TP.lat!=null && TP.rad===1000"),
    # --- area pages (v3.0 P5: header → tiles → picker → study row → four <details>) ---
    dict(id="area_kommune",   hash="area/kommune/101?ind=growth",            land=[".arhead h2!", "#armap .leaflet-pane", "#arlegend!", "[data-testid=tiles]!", "[data-testid=study-row]!", "[data-testid=chart-panel]!", "[data-testid=minimap]!", "[data-testid=minimap-full]", "[data-testid=ind-picker-btn]!", "[data-testid=ind-chips]!", "[data-testid=sec-figures]!", "[data-testid=sec-info]!"], state="S.view==='area' && !!LF.amap && window.__maps.length===1 && LF.amap.dragging.enabled() && document.querySelector('[data-testid=sec-outlook]').open"),
    dict(id="area_postnr",    hash="area/postnr/2450?ind=growth",            land=[".arhead h2!", "#armap", "[data-testid=study-row]!", "[data-testid=tile-unemp].inh"], state="AR.type==='postnr' && !document.querySelector('[data-testid=sec-outlook]')"),
    dict(id="area_kvarter",   hash="area/kvarter/20602?ind=growth",          land=[".arhead h2!", "#armap", "[data-testid=chart-panel]!"], state="AR.type==='kvarter'"),
    # the four quarters where KK and BBR disagree by more than 15 pp get the ENG_BRIEF §3.4 caveat
    dict(id="area_kvarter_gap", hash="area/kvarter/20504?show=figures",      land=["[data-testid=sec-figures][open]", "[data-testid=newstock-note]!"], state="AR.code==='20504' && AR.show.has('figures')"),
    dict(id="area_snapshot",  hash="area/kommune/101?ind=renters_bbr",       land=["[data-testid=state-nohistory]!", "[data-testid=dist-strip]"], state="curInd().key==='renters_bbr'"),
    dict(id="area_clim",      hash="area/kommune/101?ind=surge_dw_pct&hz=2070", land=["[data-testid=clim-bars]", "[data-testid=period-hz]!"], state="HZ.h==='2070' && curInd().key==='surge_dw_pct'"),
    dict(id="area_outlook",   hash="area/kommune/101?ind=fc_growth",         land=["[data-testid=outlook-chart]!", "[data-testid=period-proj]!"], state="curInd().key==='fc_growth'"),
    # the v2.6 lower tab bar and tile groups became one show= key — the old link still opens the table
    dict(id="area_aarhus",    hash="area/kommune/751?ind=unemp&t=bbr&g=Rents", land=[".arhead h2!", "[data-testid=sec-figures][open]"], state="AR.code==='751'", redirect="area/kommune/751?ind=unemp&show=figures"),
    # --- Data section (v3.0 spellings) ---
    # `redirect` = the hash the app must end up on. A route with one is a redirect test: the OLD
    # spellings below never leave this list, they are how a link shared from v2.6 stays alive.
    dict(id="data_root",      hash="data",                                   land=["[data-testid=data-tabs]", "table tbody tr"], state="S.view==='table' && T.level==='kommune'", redirect="data/areas/kommune"),
    dict(id="data_areas",     hash="data/areas/kommune?ind=growth",           land=["[data-testid=data-tabs]", "[data-testid=areas-table] tbody tr", "#tq", "[data-testid=ind-picker-btn]!", "[data-testid=areas-table] th[data-col=growth].on"], state="S.view==='table' && T.level==='kommune'"),
    dict(id="data_areas_pn",  hash="data/areas/postnr?ind=growth",            land=["[data-testid=areas-table] tbody tr"], state="T.level==='postnr'"),
    dict(id="data_areas_kv",  hash="data/areas/kvarter?ind=growth",           land=["[data-testid=areas-table] tbody tr"], state="T.level==='kvarter'"),
    dict(id="data_projects",  hash="data/projects",                          land=["[data-testid=data-tabs]", "[data-testid=projects-table] tbody tr"], state="S.view==='pipeline'"),
    dict(id="data_proj_filt", hash="data/projects?ptype=metro&pstatus=construction", land=["[data-testid=projects-table]"], state="PIPE.type==='metro'"),
    dict(id="data_national",  hash="data/national",                          land=["[data-testid=data-tabs]", "[data-testid=national-table] tbody tr", ".hero"], state="S.view==='market' && !MKT.src"),
    dict(id="data_sources",   hash="data/sources",                           land=["[data-testid=data-tabs]", "[data-testid=sources-table] tbody tr"], state="S.view==='market' && MKT.src"),
    # --- the v2.6 spellings: these now redirect and must keep landing on the right tab ---
    dict(id="table_kommune",  hash="table/kommune?ind=growth",               land=["table tbody tr", "#tq"], state="S.view==='table'", redirect="data/areas/kommune"),
    dict(id="table_postnr",   hash="table/postnr?ind=growth",                land=["table tbody tr"], redirect="data/areas/postnr"),
    dict(id="table_kvarter",  hash="table/kvarter?ind=growth",               land=["table tbody tr"], redirect="data/areas/kvarter"),
    dict(id="market",         hash="market",                                 land=[".card"], state="S.view==='market'", redirect="data/national"),
    dict(id="sources",        hash="sources",                                land=[".card"], state="MKT.src", redirect="data/sources"),
    dict(id="market_src",     hash="market?src=1",                           land=["[data-testid=sources-table]"], redirect="data/sources"),
    dict(id="pipeline",       hash="pipeline",                               land=["table tbody tr"], state="S.view==='pipeline'", redirect="data/projects"),
    dict(id="pipeline_filt",  hash="pipeline?ptype=metro&pstatus=construction", land=["table"], redirect="data/projects?ptype=metro&pstatus=construction"),
    # --- charts / project sheet ---
    dict(id="charts",         hash="charts?ind=growth&a=kommune:101,kommune:751&y0=&y1=&med=1", land=["[data-testid=chart-svg]!", "[data-testid=ind-picker-btn]!", "[data-testid=ind-chips]!"], state="S.view==='charts' && CH.areas.length===2"),
    dict(id="charts_dist",    hash="charts?ind=growth&a=kommune:101&mode=dist&dist=size", land=["[data-testid=chart-svg]!"]),
    # Climate on Charts: the x axis is the horizon, not the year (spec §5.4, AC-C2)
    dict(id="charts_clim",    hash="charts?ind=surge_dw_pct&a=kommune:101,kommune:751", land=["[data-testid=chart-svg]!", "[data-hztick=today]!", "[data-hztick='2120']!"], state="S.view==='charts' && chartMode()==='clim'"),
    dict(id="project",        hash=None,                                     land=[".card h2, .card h3"], state="S.view==='project'", dynamic="project"),
    # --- test property / compare redirect / climate / public / school ---
    # --- test property (v3.0 P6: header + study row + eight <details>) ---
    dict(id="property_empty", hash="property",                               land=["#tpq", "[data-testid=state-empty]!", "[data-testid=prop-input]"], state="S.view==='analysis'"),
    dict(id="property",       hash="property?p=55.64250,12.53850:Sydhavn&lay=infra,public,climate&hz=2070", land=["#anmap .leaflet-pane", "#anlegend!", "#anpub!", "#anclim!", "[data-testid=study-row]!", "[data-testid=chart-panel]!", "[data-testid=minimap]!", "[data-testid=minimap-full]", "[data-testid=tiles]!", "[data-testid=prop-input]", "[data-testid=ind-picker-btn]!", "[data-testid=ind-chips]!", "[data-testid=layers-btn]!", "[data-testid=tp-radius]", "[data-testid=tp-sec-infra][open]", "[data-testid=tp-sec-sources]!"], wait="#anmap .leaflet-overlay-pane", state="S.view==='analysis' && !!LF.anmap && !!KOM.list && window.__maps.length===1 && AN.show.has('infra')", settle=2500, redirect="property?p=55.6425,12.5385:Sydhavn"),
    # the eight sections are one show= key, the same rule as the area page's four
    dict(id="property_show",  hash="property?p=55.64250,12.53850&ind=growth&show=profile,climate", land=["[data-testid=tp-sec-profile][open]", "[data-testid=tp-sec-climate][open]", "[data-testid=tp-sec-infra]:not([open])"], wait="#anmap .leaflet-pane", state="AN.show.has('profile') && !AN.show.has('infra')", settle=2200),
    # the radius drives the rings on the map and the ring the sections count inside
    dict(id="property_rad",   hash="property?p=55.64250,12.53850&ind=growth&rad=2000", land=["[data-testid=tp-radius]", "[data-testid=tp-sec-public]!"], wait="#anmap .leaflet-pane", state="AN.rad===2000 && anRing()===2000", settle=2200),
    # a pin outside Copenhagen: the entity is the postal code, so the picker offers the national list
    dict(id="property_postnr", hash="property?p=56.15700,10.21000:Aarhus C&ind=growth", land=["[data-testid=study-row]!", "[data-testid=chart-panel]!", "[data-testid=tiles]!", "[data-testid=tp-sec-profile]!"], wait="#anmap .leaflet-pane", state="S.view==='analysis' && anEntity().type==='postnr' && pickLevel()==='postnr' && curInds()===IND", settle=2400),
    dict(id="analysis_empty", hash="analysis",                               land=["#tpq", "[data-testid=state-empty]!"], state="S.view==='analysis'", redirect="property"),
    dict(id="analysis",       hash="analysis?a=55.64250,12.53850&la=Sydhavn&lay=infra,public,climate&hz=2070", land=["#anmap .leaflet-pane", "#anlegend!", "#anpub!", "#anclim!", "[data-testid=study-row]!"], wait="#anmap .leaflet-overlay-pane", state="S.view==='analysis' && !!LF.anmap && !!KOM.list && window.__maps.length===1 && LF.anmap.dragging.enabled()", settle=2500, redirect="property?p=55.6425,12.5385:Sydhavn"),
    # Compare is deleted (amendment A1): the old link lands on the first area's own page.
    dict(id="compare_redirect", hash="compare?a=kommune:101&b=kommune:751&hz=2070", land=[".arhead h2!", "#armap"], state="S.view==='area' && AR.type==='kommune' && AR.code==='101'", redirect="area/kommune/101"),
    dict(id="climate_sheet",  hash="climate/0167?hz=2070",                   land=[".climtbl, table"], state="S.view==='climate' && CS.code==='0167'", settle=2000),
    dict(id="publist",        hash="publist/kommune:101:education:existing", land=["table, .card"], state="S.view==='publist'", settle=2000),
    dict(id="schoollist",     hash="schoollist/kommune:101",                 land=["table, .card"], state="S.view==='schoollist'", settle=2000),
]

VIEWPORTS = {"1440x900": (1440, 900), "1366x768": (1366, 768), "390x844": (390, 844)}

# Horizontal overflow at phone width is a known v2.6 defect on every route (ENG_BRIEF §2.3): the
# 900 px media query keeps the desktop grid semantics and the cards stay wider than 390. P8 rebuilds
# the responsive shell and flips this to True; until then the finding is reported, not fatal.
OVERFLOW_FATAL = False
PHONE_W = 480


def assert_this_app(page, url):
    """Belt and braces after our_url(): the page the browser actually booted is this dashboard.
    One Danish municipality is enough to tell the two apart."""
    ok = page.evaluate("(() => { try { return !!(byCode && byCode['101']"
                       " && /K\\u00f8benhavn/.test(byCode['101'].name)); } catch (e) { return false; } })()")
    if not ok:
        title = page.evaluate("document.title")
        raise SystemExit(f"{url} is not serving this dashboard (title {title!r}, no Danish municipality data).")


def hash_mismatch(actual, expect):
    """'' when `actual` is the canonical spelling of `expect`: same path, and every query key the
    expectation names present with that value. The app adds its own keys (ind=, hz=…) on the way,
    so a redirect is checked on what it promises, not on the whole string."""
    a_path, _, a_qs = actual.lstrip("#").partition("?")
    e_path, _, e_qs = expect.lstrip("#").partition("?")
    if a_path != e_path:
        return f"redirect path {a_path!r}, expected {e_path!r}"
    aq = {}
    for part in a_qs.split("&"):
        k, _, v = part.partition("=")
        if k:
            aq[k] = v
    for part in e_qs.split("&"):
        if not part:
            continue
        k, _, v = part.partition("=")
        if aq.get(k) != v:
            return f"redirect {k}={aq.get(k)!r}, expected {v!r}"
    return ""


# Console noise that is not the app's fault (tile 404s when offline etc.). Everything else fails.
IGNORE = [
    re.compile(r"Failed to load resource.*(tile\.openstreetmap|fonts\.g(oogle|static))"),
    re.compile(r"net::ERR_(NAME_NOT_RESOLVED|INTERNET_DISCONNECTED|BLOCKED_BY_CLIENT|FAILED)"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--phase", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--viewports", default=",".join(VIEWPORTS))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--allow-errors", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--full-page", action="store_true", help="also save a full-height screenshot")
    args = ap.parse_args()
    args.url = our_url(args.url)

    out = pathlib.Path(args.out) / (args.phase or time.strftime("%Y%m%d-%H%M"))
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    routes = [r for r in ROUTES if not only or r["id"] in only]
    vps = [(v, VIEWPORTS[v]) for v in args.viewports.split(",") if v in VIEWPORTS]
    results, failures = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=["--disable-gpu"])
        for vname, (w, h) in vps:
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            if args.no_network:
                host = re.sub(r"^https?://", "", args.url).split("/")[0]
                ctx.route("**/*", lambda route: route.continue_() if host in route.request.url else route.abort())
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
            page.on("console", lambda m: errs.append(("console." + m.type, m.text)) if m.type in ("error",) and not any(rx.search(m.text) for rx in IGNORE) else None)
            page.goto(args.url + "#map?ind=growth", wait_until="load")
            page.wait_for_function("typeof render === 'function' && IND.length > 0", timeout=60000)
            page.wait_for_timeout(600)
            assert_this_app(page, args.url)
            errs.clear()
            for r in routes:
                t0 = time.time()
                hash_ = r["hash"]
                if r.get("dynamic") == "project":
                    hash_ = page.evaluate("'project/' + encodeURIComponent((INFRA_ALL[0]||{properties:{id:''}}).properties.id)")
                before = len(errs)
                page.evaluate(f"location.hash = {json.dumps('#' + hash_)}")
                page.wait_for_timeout(150)
                if r.get("wait"):
                    try:
                        # state="attached": the landmarks worth waiting for are Leaflet panes, and a
                        # pane has no size of its own — the default "visible" would always time out.
                        page.wait_for_selector(r["wait"], state="attached", timeout=15000)
                    except Exception:
                        pass
                page.wait_for_timeout(r.get("settle", 900))
                issues = []
                for sel in r.get("land", []):
                    nonempty = sel.endswith("!"); sel = sel.rstrip("!")
                    n = page.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); return e ? (e.innerHTML||'').trim().length : -1; }})()")
                    if n < 0: issues.append(f"missing landmark {sel}")
                    elif nonempty and n == 0: issues.append(f"empty landmark {sel}")
                if r.get("redirect"):
                    bad = hash_mismatch(page.evaluate("location.hash"), r["redirect"])
                    if bad:
                        issues.append(bad)
                if r.get("state"):
                    try:
                        ok = page.evaluate(f"!!({r['state']})")
                    except Exception as ex:
                        ok = False; issues.append(f"state threw: {str(ex).splitlines()[0][:120]}")
                    if not ok: issues.append(f"state false: {r['state']}")
                # layout sanity: no horizontal page scroll at phone width, body not empty
                hscroll = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2 || document.getElementById('main').scrollWidth > document.getElementById('main').clientWidth + 2")
                notes = []
                if hscroll and w <= PHONE_W:
                    (issues if OVERFLOW_FATAL else notes).append("horizontal overflow at phone width")
                page_errs = errs[before:]
                shot = out / f"{r['id']}_{vname}.png"
                page.screenshot(path=str(shot), full_page=False)
                if args.full_page:
                    page.screenshot(path=str(out / f"{r['id']}_{vname}_full.png"), full_page=True)
                rec = dict(route=r["id"], hash=hash_, viewport=vname, ms=int((time.time() - t0) * 1000), issues=issues, notes=notes, errors=page_errs, shot=str(shot))
                results.append(rec)
                if issues or (page_errs and not args.allow_errors):
                    failures.append(rec)
                mark = "✗" if (issues or page_errs) else "·" if notes else "✓"
                print(f" {mark} {vname:9} {r['id']:16} {rec['ms']:5} ms" + ("  " + "; ".join(issues) if issues else "")
                      + ("  (" + "; ".join(notes) + ")" if notes else "")
                      + (f"  [{len(page_errs)} js error(s): {page_errs[0][1][:90]}]" if page_errs else ""))
            ctx.close()
        browser.close()
    (out / "report.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    nerr = sum(len(r["errors"]) for r in results)
    nnote = sum(len(r.get("notes", [])) for r in results)
    print(f"\n{len(results) - len(failures)}/{len(results)} route×viewport checks passed · {nerr} js errors"
          + (f" · {nnote} non-fatal note(s)" if nnote else "") + f" · screenshots in {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
