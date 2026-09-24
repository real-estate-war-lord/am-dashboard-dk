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

# Serving dist/ ourselves when the URL we were handed belongs to another project — see ui_smoke.py.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ui_smoke import our_url  # noqa: E402

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
    """A clean starting point for every AC: the map, fully loaded, errors cleared by the caller.

    The hop through Data is not decoration. `go()` only re-renders when the hash actually changes,
    so an AC that ends on `#map?ind=growth` would hand the next one the very same DOM — including
    a popover or a fold the previous AC left open. One route in between guarantees a fresh render.
    """
    goto(page, "data/areas/kommune", settle=250)
    goto(page, "map?ind=growth", settle=600)


def assert_this_app(page, url):
    """Belt and braces after our_url(): the page the browser actually booted is this dashboard.
    One Danish municipality tells it and a sibling project apart."""
    ok = page.evaluate("(() => { try { return !!(byCode && byCode['101']"
                       " && /K\\u00f8benhavn/.test(byCode['101'].name)); } catch (e) { return false; } })()")
    if not ok:
        title = page.evaluate("document.title")
        raise SystemExit(f"{url} is not serving this dashboard (title {title!r}, no Danish municipality data).")


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
        # one interaction: the indicator chips are the control every view with a picker shares.
        # P3 replaced the v2.6 `[data-indq]` chips with the shared `ind-chips` row — same click, and
        # now also on Charts, so this exercises one more route than it did before.
        chip = page.locator("[data-testid=ind-chips] .chip").first
        if chip.count():
            chip.click()
            page.wait_for_timeout(700)
            a, b = page.evaluate("[location.hash.slice(1), hashFor()]")
            assert a == b, f"#{h} after a chip click: bar {a!r}, hashFor() {b!r}"
    page.evaluate("history.back()")
    page.wait_for_timeout(900)
    a, b = page.evaluate("[location.hash.slice(1), hashFor()]")
    assert a == b, f"after history.back(): bar {a!r}, hashFor() {b!r}"


# =============================================================================================
# P3 — the shared IndicatorPicker, the chips row and the PeriodControl
# =============================================================================================
# The three routes that had adopted the shared picker when P3 landed. The area page and the test
# property keep their own selectors until P5/P6 and are added to this list by those phases.
PICKER_ROUTES = ["map?ind=growth", "data/areas/kommune?ind=growth", "charts?ind=growth&a=kommune:101"]


def pick_rows(page):
    """Every row of the open popover: key, the text the reader sees, and whether it is on screen."""
    return page.evaluate("""() => [...document.querySelectorAll('[data-testid=ind-picker-pop] .indrow')]
        .map(r => ({ key: r.dataset.ind, text: (r.textContent || '').trim(),
                     shown: r.getClientRects().length > 0 }))""")


@ac("AC-I1", phase="P3")
def ac_i1(page, base):
    """On every route that has adopted it, the IndicatorPicker exists exactly once and carries its
    button — one component, not one per view (spec §4.2, amendment A4)."""
    for h in PICKER_ROUTES:
        goto(page, h, settle=900)
        n = page.locator("[data-testid=ind-picker]").count()
        assert n == 1, f"#{h} has {n} ind-picker(s), expected exactly 1"
        assert page.locator("[data-testid=ind-picker] [data-testid=ind-picker-btn]").count() == 1, \
            f"#{h}: the picker has no button inside it"
        # and the picker button names the indicator the URL asked for
        assert page.evaluate("document.querySelector('[data-testid=ind-picker-btn]').dataset.ind") == "growth", \
            f"#{h}: the button does not name the active indicator"


@ac("AC-I2", phase="P3")
def ac_i2(page, base):
    """Clicking the button opens the popover with the search box focused and all twelve indicator
    groups listed as [data-group] headers."""
    goto(page, "map?ind=growth", settle=900)
    assert page.locator("[data-testid=ind-picker-pop]").is_visible() is False, "the popover starts closed"
    assert page.get_attribute("[data-testid=ind-picker-btn]", "aria-expanded") == "false"
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(250)
    assert page.locator("[data-testid=ind-picker-pop]").is_visible(), "the popover did not open"
    assert page.get_attribute("[data-testid=ind-picker-btn]", "aria-expanded") == "true"
    assert page.locator("[data-testid=ind-picker-pop] [data-testid=ind-search]").count() == 1
    assert page.evaluate("document.activeElement === document.querySelector('[data-testid=ind-search]')"), \
        "the search box must have focus when the popover opens"
    groups = texts(page, "[data-testid=ind-picker-pop] [data-group]")
    assert len(groups) >= 12, f"only {len(groups)} group headers: {groups}"
    # role=listbox + aria-activedescendant is the picker's accessibility contract (spec §7)
    assert page.locator("[data-testid=ind-picker-pop] [role=listbox]").count() == 1
    assert page.evaluate("!!document.querySelector('#indlist').getAttribute('aria-activedescendant')"), \
        "the listbox names no active row"
    assert not ERRORS, f"pageerror while opening the picker: {ERRORS[:2]}"


@ac("AC-I3", phase="P3")
def ac_i3(page, base):
    """Typing in the search leaves exactly the rows whose own text matches, and Enter takes the
    first one — the hash then names that indicator."""
    goto(page, "map?ind=growth", settle=900)
    assert page.locator("[data-testid=ind-picker-pop]").is_visible() is False, \
        "the popover is already open — this AC opens it itself, so it would have closed it"
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(200)
    page.fill("[data-testid=ind-search]", "surge")
    page.wait_for_timeout(250)
    rows = pick_rows(page)
    shown = [r for r in rows if r["shown"]]
    assert shown, "the search hid every row"
    for r in shown:
        assert "surge" in r["text"].lower(), f"row {r['key']!r} is visible but does not say surge: {r['text']!r}"
    for r in rows:
        if not r["shown"]:
            assert "surge" not in r["text"].lower(), f"row {r['key']!r} says surge but was hidden"
    first = shown[0]["key"]
    page.keyboard.press("Enter")
    page.wait_for_timeout(700)
    assert f"ind={first}" in cur_hash(page), f"Enter on {first!r} gave {cur_hash(page)!r}"
    assert page.evaluate("MK.ind") == first
    assert page.locator("[data-testid=ind-picker-pop]").is_visible() is False, "the popover stayed open after a pick"
    # a query that matches nothing says so instead of showing everything
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(200)
    page.fill("[data-testid=ind-search]", "zzzz")
    page.wait_for_timeout(250)
    assert not [r for r in pick_rows(page) if r["shown"]], "a query with no hit left rows on screen"
    assert page.locator("[data-testid=ind-picker-pop] .indnone").is_visible(), "no empty-state line for a search with no hit"
    # Esc closes it and hands focus back to the button, so the next AC starts where this one did
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator("[data-testid=ind-picker-pop]").is_visible() is False, "Escape did not close the popover"
    assert page.evaluate("document.activeElement === document.querySelector('[data-testid=ind-picker-btn]')"), \
        "Escape did not return focus to the picker button"


@ac("AC-I4", phase="P3")
def ac_i4(page, base):
    """The chips row marks the active indicator, and the chip agrees with the picker button: same
    key, and the chip's text is that indicator's short form."""
    for h in PICKER_ROUTES:
        goto(page, h, settle=900)
        on = page.locator("[data-testid=ind-chips] .chip.on")
        assert on.count() == 1, f"#{h} has {on.count()} active chips, expected 1"
        key = on.first.get_attribute("data-ind")
        assert key == page.evaluate("document.querySelector('[data-testid=ind-picker-btn]').dataset.ind"), \
            f"#{h}: the filled chip and the picker button disagree"
        assert f"ind={key}" in cur_hash(page), f"#{h}: the filled chip is not the indicator in the hash"
        short = page.evaluate("k => { const i = IND.concat(IND_CPH).find(x => x.key === k) || {};"
                              " return i.chip_label || i.short || i.label || ''; }", key)
        assert on.first.inner_text().strip() == short, \
            f"#{h}: chip says {on.first.inner_text().strip()!r}, the short form is {short!r}"
        # clicking another chip moves both the URL and the button
        other = page.locator("[data-testid=ind-chips] .chip:not(.on)").first
        k2 = other.get_attribute("data-ind")
        other.click()
        page.wait_for_timeout(800)
        assert f"ind={k2}" in cur_hash(page), f"#{h}: a chip click did not write ind={k2}"
        assert page.evaluate("document.querySelector('[data-testid=ind-picker-btn]').dataset.ind") == k2


@ac("AC-T1", phase="P3")
def ac_t1(page, base):
    """The PeriodControl renders the one mode the active indicator has, and never a second one: a
    year selector for a series, horizon segments for Climate, a static badge for Outlook."""
    cases = [("map?ind=growth", "period-year", ["period-hz", "period-proj"]),
             ("map?ind=surge_dw_pct", "period-hz", ["period-year", "period-proj"]),
             ("map?ind=fc_growth", "period-proj", ["period-year", "period-hz"])]
    for h, want, absent in cases:
        goto(page, h, settle=1100)
        assert page.locator(f"[data-testid={want}]").count() >= 1, f"#{h} shows no {want}"
        assert page.locator(f"[data-testid={want}]").first.is_visible(), f"#{h}: {want} is not visible"
        for a in absent:
            assert page.locator(f"[data-testid={a}]").count() == 0, f"#{h} also shows {a}"
        assert page.locator("[data-testid=period]").count() == 1, f"#{h} has more than one period control"
    # leaving the Climate family drops hz= from the URL (spec §3.2, §4.3)
    goto(page, "map?ind=surge_dw_pct&hz=2120", settle=1100)
    assert "hz=2120" in cur_hash(page)
    page.click("[data-testid=ind-chips] .chip[data-ind=growth]")
    page.wait_for_timeout(900)
    assert "hz=" not in cur_hash(page), f"hz survived the move out of Climate: {cur_hash(page)!r}"


@ac("AC-T2", phase="P3")
def ac_t2(page, base):
    """Clicking a horizon writes hz= and the map legend says which horizon its figures are from."""
    goto(page, "map?ind=surge_dw_pct", settle=1400)
    assert "hz=" not in cur_hash(page), "today is the default and stays out of the hash"
    page.click("[data-testid=period-hz] [data-hz='2070']")
    page.wait_for_timeout(1200)
    assert "hz=2070" in cur_hash(page), f"the horizon did not reach the hash: {cur_hash(page)!r}"
    assert page.evaluate("HZ.h") == "2070"
    leg = page.locator("#maplegend").inner_text()
    assert "2070" in leg, f"the legend does not name the horizon: {leg!r}"
    assert page.evaluate("document.querySelector('[data-testid=period-hz] [data-hz=\\'2070\\']').classList.contains('on')"), \
        "the clicked horizon is not marked as the active one"


@ac("AC-D5", phase="P3")
def ac_d5(page, base):
    """Data › Areas highlights the active indicator's column and sorts the table by it, in the
    direction the header advertises (best first: ↓ lower is better sorts up)."""
    for key in ["unemp", "growth"]:
        goto(page, f"data/areas/kommune?ind={key}", settle=1200)
        th = page.locator(f"[data-testid=areas-table] th[data-col={key}]")
        assert th.count() == 1, f"no single th[data-col={key}]"
        cls = th.first.get_attribute("class") or ""
        assert "on" in cls.split(), f"th[data-col={key}] is not marked active: class={cls!r}"
        # exactly one column is the active one
        assert page.locator("[data-testid=areas-table] thead th.on").count() == 1
        best = th.first.get_attribute("data-best")
        vals = page.evaluate("""k => {
          const head = [...document.querySelectorAll('[data-testid=areas-table] thead th')];
          const ix = head.findIndex(h => h.dataset.col === k);
          return [...document.querySelectorAll('[data-testid=areas-table] tbody tr')].slice(0, 4)
            .map(tr => { const c = tr.children[ix]; return c && c.dataset.v != null ? Number(c.dataset.v) : null; });
        }""", key)
        got = [v for v in vals if v is not None]
        assert len(got) >= 2, f"could not read two values from the {key} column: {vals}"
        if best == "asc":
            assert got == sorted(got), f"{key} (lower is better) is not sorted best first: {got}"
        else:
            assert got == sorted(got, reverse=True), f"{key} is not sorted best first: {got}"


@ac("AC-C1", phase="P3")
def ac_c1(page, base):
    """Charts draws one path per selected area plus the median and Denmark, and uses the shared
    picker."""
    goto(page, "charts?ind=growth&a=kommune:101,kommune:751&y0=&y1=&med=1", settle=1400)
    assert page.locator("[data-testid=ind-picker]").count() == 1, "Charts does not use the shared picker"
    assert page.locator("[data-testid=chart-svg]").count() == 1
    kinds = page.evaluate("""[...document.querySelectorAll('[data-testid=chart-svg] [data-series]')]
        .map(e => e.dataset.seriesKind)""")
    assert kinds.count("area") == 2, f"expected 2 area series, got {kinds}"
    assert "median" in kinds, f"the peer median is missing: {kinds}"
    assert "national" in kinds, f"the Denmark line is missing: {kinds}"
    names = page.evaluate("""[...document.querySelectorAll('[data-testid=chart-svg] [data-series]')]
        .map(e => e.dataset.series)""")
    assert any("København" in n for n in names) and any("Aarhus" in n for n in names), f"series are {names}"


@ac("AC-C2", phase="P3")
def ac_c2(page, base):
    """A Climate indicator on Charts puts the three published horizons on the x axis — Today, 2070,
    2120 — with a bar per area at each, and nothing drawn between them."""
    goto(page, "charts?ind=surge_dw_pct&a=kommune:101,kommune:751", settle=1500)
    ticks = page.evaluate("""[...document.querySelectorAll('[data-testid=chart-svg] [data-hztick]')]
        .map(e => (e.textContent || '').trim())""")
    assert ticks == ["Today", "2070", "2120"], f"x-axis ticks are {ticks}"
    bars = page.evaluate("""[...document.querySelectorAll('[data-testid=chart-svg] [data-series][data-hz]')]
        .map(e => e.dataset.series + '@' + e.dataset.hz)""")
    assert len(bars) == 6, f"expected 2 areas × 3 horizons = 6 bars, got {len(bars)}: {bars}"
    # a horizon chart is bars, never a line through the horizons
    assert page.evaluate("document.querySelectorAll('[data-testid=chart-svg] path[data-series]').length") == 0, \
        "a path was drawn through the horizons — that would be an interpolation, not published data"
    assert not ERRORS, f"pageerror on a Climate chart: {ERRORS[:2]}"


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
    args.url = our_url(args.url)

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
            assert_this_app(page, args.url)
            for a in here:
                t0 = time.time()
                err = ""
                try:
                    boot(page, args.url)
                    del errs[:]
                    a["fn"](page, args.url)
                except AssertionError as ex:
                    err = str(ex) or "assertion failed"
                except Exception as ex:
                    # A Playwright timeout says everything useful in the first lines of its own
                    # message (the call and the locator it waited for) — the last line of the
                    # traceback is "- waiting 500ms", which names neither.
                    msg = " · ".join([ln.strip() for ln in str(ex).splitlines() if ln.strip()][:4])
                    frames = traceback.format_exc().strip().splitlines()
                    where = next((ln.strip() for ln in reversed(frames) if ln.strip().startswith("File ")), "")
                    err = f"{type(ex).__name__}: {msg} [{where}]"[:400]
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
