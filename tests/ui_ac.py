#!/usr/bin/env python3
"""ui_ac.py — the acceptance suite for the v3.0 UI spec.

One function per acceptance criterion (AC) from docs/v3/UI_SPEC_v3.md, registered with the phase
that delivered it. A phase adds its MUST ACs here and never deletes or weakens an earlier phase's
— the suite only ever grows, so a later phase cannot quietly undo an earlier one.

    @ac("AC-M9", phase="P1", viewport="1440x900")
    def ac_m9(page, base):
        ...                       # raise AssertionError to fail

Usage:
  python3 tests/ui_ac.py [--url http://localhost:8080/] [--phase-upto P1] [--only AC-M9,AC-MM3]
                         [--viewports 1440x900] [--out logs/ac] [--headed] [--network]

Runs every AC whose phase is at or before --phase-upto. Boots the page once per viewport, exactly
as tests/ui_smoke.py does, and blocks every host but the local server unless --network is given.
Writes <out>/report.json. Exit code 1 if any AC fails.

The server is not started here — `make ac` and `./overnight.sh gate` serve dist/ on :8080.
"""
import argparse
import json
import pathlib
import re
import sys
import time
import traceback

from playwright.sync_api import sync_playwright

PHASES = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]
VIEWPORTS = {"1440x900": (1440, 900), "1366x768": (1366, 768), "390x844": (390, 844)}
DEFAULT_VP = "1440x900"

# Console noise that is not the app's fault (tile/font requests fail when the network is blocked).
IGNORE = [
    re.compile(r"Failed to load resource.*(tile\.openstreetmap|fonts\.g(oogle|static))"),
    re.compile(r"net::ERR_(NAME_NOT_RESOLVED|INTERNET_DISCONNECTED|BLOCKED_BY_CLIENT|FAILED)"),
]

AC = {}       # id -> dict(id, phase, viewport, doc, fn)
ERRORS = []   # live pageerror / console.error list for the page the current AC is running on


def ac(ac_id, phase, viewport=DEFAULT_VP):
    """Register one acceptance criterion. `fn(page, base_url)` raises AssertionError to fail."""
    def deco(fn):
        assert ac_id not in AC, f"duplicate AC id {ac_id}"
        assert phase in PHASES, f"unknown phase {phase}"
        assert viewport in VIEWPORTS, f"unknown viewport {viewport}"
        AC[ac_id] = dict(id=ac_id, phase=phase, viewport=viewport, doc=(fn.__doc__ or "").strip(), fn=fn)
        return fn
    return deco


# ---------------------------------------------------------------------------------------------
# helpers shared by the ACs
# ---------------------------------------------------------------------------------------------
def goto(page, hash_, settle=900, wait=None):
    """Drive the SPA by its hash, the way a reader's link does, and let the render settle."""
    page.evaluate("h => { location.hash = h; }", "#" + hash_.lstrip("#"))
    page.wait_for_timeout(150)
    if wait:
        try:
            page.wait_for_selector(wait, timeout=15000)
        except Exception:
            pass
    page.wait_for_timeout(settle)


def boot(page, base):
    """A clean starting point for every AC: the map, fully loaded, errors cleared by the caller."""
    goto(page, "map?ind=growth", settle=600)


def cur_hash(page):
    """The hash the app settled on — parseHash() rewrites an old link to its canonical v3 spelling."""
    return page.evaluate("location.hash").lstrip("#")


def cur_path(page):
    return cur_hash(page).split("?")[0]


def texts(page, selector):
    return page.eval_on_selector_all(selector, "els => els.map(e => (e.textContent || '').trim())")


def map_center(page, i=0):
    return page.evaluate("i => { const c = window.__maps[i].getCenter(); return [c.lat, c.lng]; }", i)


def drag(page, selector, dx, dy):
    """A real pointer drag across an element — Leaflet listens to the pointer, not to JS. The grab
    point sits off-centre so the drag never starts on the pin or on a marker."""
    box = page.locator(selector).first.bounding_box()
    assert box, f"no bounding box for {selector}"
    x, y = box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.25
    page.mouse.move(x, y)
    page.mouse.down()
    # several steps: one jump is below Leaflet's drag threshold on some builds
    for k in range(1, 7):
        page.mouse.move(x + dx * k / 6, y + dy * k / 6)
        page.wait_for_timeout(20)
    page.mouse.up()
    page.wait_for_timeout(500)


# =============================================================================================
# P1 — foundation: map lifecycle, zoom never selects, the mini map drags
# =============================================================================================
@ac("AC-MM3", phase="P1")
def ac_mm3(page, base):
    """Navigating map → area → test property → map produces zero pageerror events, and fast
    switching (50 ms apart) does not either — a torn-down map must not still be animating."""
    errs = ERRORS
    route = ["map?ind=growth", "area/kommune/101?ind=growth",
             "analysis?a=55.65450,12.53900&la=Test&lay=infra,public", "map?ind=growth"]
    del errs[:]
    for h in route:
        goto(page, h, settle=1200, wait=None)
    slow = list(errs)
    assert not slow, f"pageerror during the slow walk: {slow[:3]}"

    # the same walk with 50 ms between hops: two map inits inside one frame is root cause 3
    del errs[:]
    for _ in range(3):
        for h in route:
            page.evaluate("h => { location.hash = h; }", "#" + h)
            page.wait_for_timeout(50)
    page.wait_for_timeout(2500)
    fast = list(errs)
    assert not fast, f"pageerror during fast switching: {fast[:3]}"
    # and the app is still alive and owns exactly one map
    n = page.evaluate("window.__maps.length")
    assert n == 1, f"expected exactly one live map after the walk, got {n}"


@ac("AC-M9", phase="P1")
def ac_m9(page, base):
    """On #map/101 zooming never changes the selection: the hash path, the drilled municipality
    and the selected outline are the same after setZoom(12) → setZoom(9)."""
    goto(page, "map/101?ind=growth", settle=1500)
    before = page.evaluate("[location.hash.split('?')[0], MK.muni, MK.cphView, LF.level]")
    assert before[1] == "101", f"expected to be drilled into 101, got {before[1]}"
    page.evaluate("window.__maps[0].setZoom(12)")
    page.wait_for_timeout(900)
    page.evaluate("window.__maps[0].setZoom(9)")
    page.wait_for_timeout(900)
    after = page.evaluate("[location.hash.split('?')[0], MK.muni, MK.cphView, LF.level]")
    assert before[0] == after[0], f"the hash path changed on zoom: {before[0]} → {after[0]}"
    assert before[1] == after[1], f"the selected municipality changed on zoom: {before[1]} → {after[1]}"
    assert before[2] == after[2], f"the sub-area level changed on zoom: {before[2]} → {after[2]}"
    assert before[3] == after[3], f"the drawn layer level changed on zoom: {before[3]} → {after[3]}"


@ac("AC-P1MM", phase="P1")
def ac_p1_minimap_drag(page, base):
    """P1-local: on #analysis?a=55.6545,12.539 the test-property mini map is draggable — a 120 px
    drag moves its centre, and the ⌖ control brings the pin back."""
    goto(page, "analysis?a=55.65450,12.53900&la=Test", settle=1200, wait="#anmap .leaflet-pane")
    page.wait_for_timeout(1500)
    assert page.evaluate("window.__maps.length") == 1, "the test property owns exactly one map"
    assert page.evaluate("LF.anmap.dragging.enabled()"), "the mini map must be draggable (v2.6 had dragging:false)"
    # the pin and its three walk/bike rings survive the overlays that used to throw before them
    rings = page.evaluate("LF.anPinG ? LF.anPinG.getLayers().length : 0")
    assert rings == len([500, 1000, 1200]) + 1, f"expected 3 rings + the pin on the map, got {rings} layer(s)"
    before = map_center(page)
    drag(page, "#anmap", 120, 0)
    after = map_center(page)
    moved = abs(after[1] - before[1]) + abs(after[0] - before[0])
    assert moved > 1e-5, f"a 120 px drag did not move the centre: {before} → {after}"
    # ⌖ puts the property back in the middle
    page.click("[data-testid=minimap-recentre]")
    page.wait_for_timeout(700)
    back = map_center(page)
    assert abs(back[0] - 55.6545) < 1e-3 and abs(back[1] - 12.539) < 1e-3, f"⌖ did not re-centre on the pin: {back}"


# =============================================================================================
# P2 — navigation, the Data section, Compare removed, the redirects live
# =============================================================================================
@ac("AC-D1", phase="P2")
def ac_d1(page, base):
    """#data redirects to #data/areas/kommune, the Data tab bar has four tabs, and every v2.6
    tabular link (#table/*, #pipeline, #market, #sources) redirects to its #data/… hash."""
    goto(page, "data")
    assert cur_path(page) == "data/areas/kommune", f"#data landed on {cur_hash(page)!r}"
    tabs = texts(page, "[data-testid=data-tabs] [data-testid=data-tab]")
    assert tabs == ["Areas", "Projects", "National series", "Sources"], f"tabs are {tabs}"
    for old, new in [("table/kommune", "data/areas/kommune"), ("table/postnr", "data/areas/postnr"),
                     ("table/kvarter", "data/areas/kvarter"), ("pipeline", "data/projects"),
                     ("market", "data/national"), ("market?src=1", "data/sources"),
                     ("sources", "data/sources"), ("data", "data/areas/kommune")]:
        goto(page, old, settle=500)
        assert cur_path(page) == new, f"#{old} landed on {cur_hash(page)!r}, expected #{new}"
        assert page.locator("[data-testid=data-tabs]").count() == 1, f"no tab bar on #{old}"


@ac("AC-D2", phase="P2")
def ac_d2(page, base):
    """The sidebar has exactly four nav items: Map, Data, Charts, Test property (amendment A1 —
    Market, Pipeline and Compare are gone)."""
    items = texts(page, "[data-testid=sidebar] [data-testid=nav-item]")
    assert items == ["Map", "Data", "Charts", "Test property"], f"nav items are {items}"
    assert page.locator("[data-testid=nav-item]").count() == 4


@ac("AC-D3", phase="P2")
def ac_d3(page, base):
    """#data/national is a table of at least 13 series, every row carrying a source, and the four
    large charts are gone — nothing on the page draws wider than 300 px."""
    goto(page, "data/national", settle=1100)
    rows = page.locator("[data-testid=national-table] tbody tr")
    n = rows.count()
    assert n >= 13, f"only {n} series rows"
    srcs = texts(page, "[data-testid=national-table] tbody tr td:nth-child(5)")
    assert len(srcs) == n, f"{len(srcs)} source cells for {n} rows"
    blank = [i for i, s in enumerate(srcs) if not s]
    assert not blank, f"rows {blank} have an empty Source cell"
    wide = page.evaluate("[...document.querySelectorAll('svg,canvas')]"
                         ".map(e => Math.round(e.getBoundingClientRect().width)).filter(w => w > 300)")
    assert not wide, f"a chart {wide} px wide survived on the National series tab"


@ac("AC-D4", phase="P2")
def ac_d4(page, base):
    """#data/sources is a table with no empty cell in the Fetched column — a source that records no
    fetch date of its own shows the build date with a `build` tag."""
    goto(page, "data/sources", settle=900)
    head = texts(page, "[data-testid=sources-table] thead th")
    assert "Fetched" in head, f"no Fetched column in {head}"
    i = head.index("Fetched") + 1
    cells = texts(page, f"[data-testid=sources-table] tbody tr td:nth-child({i})")
    assert len(cells) >= 20, f"only {len(cells)} source rows"
    blank = [k for k, c in enumerate(cells) if not c or c == "–"]
    assert not blank, f"rows {blank} have an empty Fetched cell"


@ac("AC-SH3", phase="P2")
def ac_sh3(page, base):
    """The breadcrumb on a public-building sheet names the municipality the building is in, not the
    view the reader came from (v2.6 showed "Macro map")."""
    goto(page, "publist/kommune:101:education:existing", settle=2200)
    first = page.locator("[data-pubsheet]").first
    bid = first.get_attribute("data-pubsheet")
    kom = first.get_attribute("data-pubkom") or "101"
    assert bid, "no public building to open"
    goto(page, f"public/{kom}/{bid}", settle=1600)
    crumb = page.locator(".crumbs").inner_text()
    assert "Macro map" not in crumb, f"breadcrumb still says Macro map: {crumb!r}"
    assert "København" in crumb, f"breadcrumb does not name the municipality: {crumb!r}"


@ac("AC-TP1", phase="P2")
def ac_tp1(page, base):
    """An #analysis link redirects to the Test property route: #property?p=lat,lon[:label]."""
    goto(page, "analysis?a=55.65450,12.53900&la=Test", settle=1200)
    h = cur_hash(page)
    assert h.startswith("property?p=55.6545,12.539"), f"redirected to {h!r}"
    assert page.evaluate("S.view === 'analysis' && AN.a === '55.6545,12.539' && AN.label === 'Test'"), \
        "the pin did not survive the redirect"


@ac("AC-TP6", phase="P2")
def ac_tp6(page, base):
    """Compare is gone (amendment A1): no route shows the word, and the old link lands on the first
    area's own page."""
    for h in ["map?ind=growth", "area/kommune/101?ind=growth", "area/postnr/2450?ind=growth",
              "data/areas/kommune", "data/projects", "data/national", "data/sources",
              "charts?ind=growth&a=kommune:101", "property?p=55.6545,12.539"]:
        goto(page, h, settle=700)
        hits = page.evaluate("""() => {
          const out = [];
          const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          for (let n = w.nextNode(); n; n = w.nextNode()) {
            const p = n.parentElement;
            if (!p || /^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(p.tagName)) continue;
            if (!p.offsetParent && p.tagName !== 'BODY') continue;   /* not rendered = not shown */
            if (/\\bcompare\\b/i.test(n.nodeValue || '')) out.push((n.nodeValue || '').trim().slice(0, 60));
          }
          return out;
        }""")
        assert not hits, f"'Compare' is still on #{h}: {hits[:3]}"
    goto(page, "compare?a=kommune:101&b=kommune:751", settle=1200)
    assert cur_path(page) == "area/kommune/101", f"#compare landed on {cur_hash(page)!r}"
    assert page.evaluate("S.view === 'area' && AR.code === '101'")


@ac("AC-U1", phase="P2")
def ac_u1(page, base):
    """Every route that exists now round-trips through parseHash() → hashFor() unchanged: the hash
    in the address bar is exactly what the app would serialise, after load, after one interaction
    and after history.back()."""
    pid = page.evaluate("(INFRA_ALL[0] || {properties:{id:''}}).properties.id")
    routes = ["map", "map/101?ind=growth", "map/101/postnr?ind=renters",
              "area/kommune/101?ind=growth", "area/postnr/2450?ind=growth", "area/kvarter/20602?ind=growth",
              "data/areas/kommune?ind=unemp", "data/areas/postnr", "data/areas/kvarter",
              "data/projects?ptype=metro", "data/national", "data/sources",
              "charts?ind=growth&a=kommune:101,kommune:751", "property?p=55.6545,12.539:Test",
              "climate/0167?hz=2070", "school/280657", "publist/kommune:101:education:existing"]
    if pid:
        routes.append("project/" + pid)
    for h in routes:
        goto(page, h, settle=700)
        a, b = page.evaluate("[location.hash.slice(1), hashFor()]")
        assert a == b, f"#{h}: the bar says {a!r}, hashFor() writes {b!r}"
        # one interaction: the indicator chips are the control every view with a picker shares
        chip = page.locator("[data-indq]").first
        if chip.count():
            chip.click()
            page.wait_for_timeout(700)
            a, b = page.evaluate("[location.hash.slice(1), hashFor()]")
            assert a == b, f"#{h} after a chip click: bar {a!r}, hashFor() {b!r}"
    page.evaluate("history.back()")
    page.wait_for_timeout(900)
    a, b = page.evaluate("[location.hash.slice(1), hashFor()]")
    assert a == b, f"after history.back(): bar {a!r}, hashFor() {b!r}"


# ---------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/")
    ap.add_argument("--phase-upto", default=PHASES[-1])
    ap.add_argument("--only", default="")
    ap.add_argument("--viewports", default="")
    ap.add_argument("--out", default="logs/ac")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--network", action="store_true", help="allow external hosts (tiles, fonts)")
    args = ap.parse_args()

    upto = args.phase_upto if args.phase_upto in PHASES else PHASES[-1]
    limit = PHASES.index(upto)
    only = set(filter(None, args.only.split(",")))
    picked = [a for a in AC.values() if PHASES.index(a["phase"]) <= limit and (not only or a["id"] in only)]
    picked.sort(key=lambda a: (PHASES.index(a["phase"]), a["id"]))
    want_vps = [v for v in args.viewports.split(",") if v in VIEWPORTS] or \
               sorted({a["viewport"] for a in picked}) or [DEFAULT_VP]
    picked = [a for a in picked if a["viewport"] in want_vps]

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"acceptance suite · phases ≤ {upto} · {len(picked)} AC(s) · {args.url}")
    results, failures = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=["--disable-gpu"])
        for vname in want_vps:
            here = [a for a in picked if a["viewport"] == vname]
            if not here:
                continue
            w, h = VIEWPORTS[vname]
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            if not args.network:
                host = re.sub(r"^https?://", "", args.url).split("/")[0]
                ctx.route("**/*", lambda route: route.continue_() if host in route.request.url else route.abort())
            errs = ERRORS
            del errs[:]                # one live list per context; the ACs read it as ERRORS
            page = ctx.new_page()
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console", lambda m: errs.append("console.error: " + m.text)
                    if m.type == "error" and not any(rx.search(m.text) for rx in IGNORE) else None)
            page.goto(args.url + "#map?ind=growth", wait_until="load")
            page.wait_for_function("typeof render === 'function' && IND.length > 0", timeout=60000)
            page.wait_for_timeout(600)
            for a in here:
                t0 = time.time()
                err = ""
                try:
                    boot(page, args.url)
                    del errs[:]
                    a["fn"](page, args.url)
                except AssertionError as ex:
                    err = str(ex) or "assertion failed"
                except Exception:
                    err = traceback.format_exc(limit=3).strip().splitlines()[-1]
                rec = dict(id=a["id"], phase=a["phase"], viewport=vname, doc=a["doc"],
                           ms=int((time.time() - t0) * 1000), error=err)
                results.append(rec)
                if err:
                    failures.append(rec)
                try:
                    page.screenshot(path=str(out / f"{a['id']}_{vname}.png"), full_page=False)
                except Exception:
                    pass
                print(f" {'✗' if err else '✓'} {a['phase']} {a['id']:10} {vname:9} {rec['ms']:5} ms" + (f"  {err}" if err else ""))
            ctx.close()
        browser.close()

    (out / "report.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(results) - len(failures)}/{len(results)} acceptance criteria passed · report {out / 'report.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
