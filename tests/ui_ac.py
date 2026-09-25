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

PHASES = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12"]
VIEWPORTS = {"1440x900": (1440, 900), "1536x864": (1536, 864), "1366x768": (1366, 768), "390x844": (390, 844)}
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
            # state="attached", as tests/ui_smoke.py does: a Leaflet pane has no size of its own, so
            # the default "visible" wait always burns its full 15 s and then passes anyway.
            page.wait_for_selector(wait, state="attached", timeout=15000)
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


# --- exports (P7) ---------------------------------------------------------------------------
# One parse per file per viewport run: the areas_long build is ~100 000 rows and four ACs read it.
CSV_CACHE = {}


def open_export(page):
    """Open the Export ▾ menu. The sidebar footer's copy is the first one in the DOM, and it is on
    every route; a Data or test-property header adds a second trigger onto the same state."""
    menu = page.locator("[data-testid=export-menu]").first
    if not menu.is_visible():           # idempotent: the trigger toggles, so never click it twice
        page.locator("[data-testid=export-btn]").first.click()
        page.wait_for_timeout(250)
    if not menu.is_visible():
        why = page.evaluate("""() => ({ xOpen: UI.xOpen,
          wraps: [...document.querySelectorAll('.xwrap')].map(w => w.dataset.xat + (w.classList.contains('open') ? ':open' : '')),
          pops: [...document.querySelectorAll('[data-testid=export-menu]')].map(p => (p.hidden ? 'hidden ' : '') + getComputedStyle(p).display + ' ' + Math.round(p.getBoundingClientRect().width) + 'x' + Math.round(p.getBoundingClientRect().height)) })""")
        raise AssertionError(f"clicking Export ▾ did not open [data-testid=export-menu]: {why}")
    return menu


def export_csv(page, kind, timeout=120000):
    """Trigger one export and read the file back: (filename, [lines]). The app writes a Blob and
    clicks an <a>, so the browser really downloads it and Playwright hands us the file."""
    if kind in CSV_CACHE:
        return CSV_CACHE[kind]
    open_export(page)
    with page.expect_download(timeout=timeout) as dl:
        page.locator(f"[data-export={kind}]").first.click()
    d = dl.value
    raw = pathlib.Path(d.path()).read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", f"{d.suggested_filename} does not start with a UTF-8 BOM"
    lines = [ln for ln in raw.decode("utf-8-sig").split("\n") if ln.strip()]
    out = (d.suggested_filename, lines)
    CSV_CACHE[kind] = out
    return out


def csv_rows(lines):
    """Header + rows as dicts. `;` never appears inside a cell, so no quoting to unpick."""
    head = lines[0].split(";")
    return head, [dict(zip(head, ln.split(";"))) for ln in lines[1:]]


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
    # the pin and its rings survive the overlays that used to throw before them. P6 added the ring
    # the radius select names (spec §5.5′) beside the three dashed walk/bike ones, so it is 3 + 1 + 1.
    rings = page.evaluate("LF.anPinG ? LF.anPinG.getLayers().length : 0")
    assert rings == len([500, 1000, 1200]) + 2, f"expected 3 scale rings + the radius ring + the pin, got {rings} layer(s)"
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
# Every route that has adopted the shared picker. P3 brought the map, Data › Areas and Charts;
# P5 added the area page. The test property keeps its v2.6 selectors until P6, which extends this.
PICKER_ROUTES = ["map?ind=growth", "data/areas/kommune?ind=growth", "charts?ind=growth&a=kommune:101",
                 "area/kommune/101?ind=growth", "property?p=55.6545,12.539&ind=growth"]


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


# =============================================================================================
# P4 — Map: Climate as an indicator family, Layers ▾, the unified search, the legend stack
# =============================================================================================
def rects(page, selector):
    """The visible boxes for a selector — a display:none legend reports a zero box at 0,0 and would
    otherwise read as "outside the map"."""
    return page.evaluate("""sel => [...document.querySelectorAll(sel)]
        .filter(e => e.getClientRects().length > 0)
        .map(e => { const r = e.getBoundingClientRect();
          return { id: e.dataset.testid || e.id, x: r.x, y: r.y, w: r.width, h: r.height,
                   right: r.right, bottom: r.bottom }; })""", selector)


def lay_open(page):
    """Open the Layers menu and leave it open (it survives a re-render through UI.layOpen)."""
    if not page.locator("[data-testid=layers-pop]").is_visible():
        page.click("[data-testid=layers-btn]")
        page.wait_for_timeout(250)
    assert page.locator("[data-testid=layers-pop]").is_visible(), "the Layers menu did not open"


@ac("AC-L1", phase="P4")
def ac_l1(page, base):
    """The Climate risk button is gone, Layers ▾ is there in its place, and the toolbar's first row
    holds no more than six controls (spec §4.4, §5.1)."""
    goto(page, "map?ind=growth", settle=1100)
    for label in ["Climate risk", "Infra projects", "Public buildings", "Services"]:
        n = page.evaluate("""t => [...document.querySelectorAll('#body button, #body .sg, #hd button')]
            .filter(e => !e.closest('[data-testid=layers-pop]') && (e.textContent || '').trim() === t).length""", label)
        assert n == 0, f"{label!r} is still a control outside the Layers menu ({n} found)"
    assert page.locator("[data-testid=layers-btn]").count() == 1, "there is no Layers button"
    row1 = page.locator("[data-testid=map-toolbar] [data-row='1']")
    assert row1.count() == 1, "the toolbar has no first row"
    n = page.evaluate("document.querySelector('[data-testid=map-toolbar] [data-row=\"1\"]').children.length")
    assert n <= 6, f"the toolbar's first row has {n} children, the spec allows 6"
    # …and the toolbar is two rows in all: controls, then the chips
    rows = page.locator("[data-testid=map-toolbar] [data-row]").count()
    assert rows == 2, f"the toolbar has {rows} rows, expected 2 (controls + chips)"


@ac("AC-L2", phase="P4")
def ac_l2(page, base):
    """Ticking a feature layer in the menu writes it into lay= and its legend appears on the map."""
    goto(page, "map/101?ind=growth", settle=1200)
    assert "lay=" not in cur_hash(page), f"a fresh map has no layers on: {cur_hash(page)!r}"
    assert page.locator("[data-testid=legend-infra]").count() == 0
    lay_open(page)
    box = page.locator("[data-layer=infra]")
    assert box.count() == 1, "the menu has no infra row"
    assert box.first.get_attribute("aria-checked") == "false"
    box.first.click()
    page.wait_for_timeout(1200)
    assert "lay=infra" in cur_hash(page), f"the tick did not reach the hash: {cur_hash(page)!r}"
    leg = page.locator("[data-testid=legend-infra]")
    assert leg.count() == 1 and leg.first.is_visible(), "the infra legend did not appear"
    # the menu stayed open and now says what it is showing
    assert page.locator("[data-layer=infra]").first.get_attribute("aria-checked") == "true"
    assert "1" in (page.locator("[data-testid=layers-btn]").inner_text() or ""), "the count badge does not say 1"
    # …and ticking it off takes both away again
    page.click("[data-layer=infra]")
    page.wait_for_timeout(1000)
    assert "lay=" not in cur_hash(page), f"the layer survived being switched off: {cur_hash(page)!r}"
    assert page.locator("[data-testid=legend-infra]").count() == 0


@ac("AC-L3", phase="P4")
def ac_l3(page, base):
    """A Climate indicator brings the storm-surge zones with it as a context layer, with their own
    legend and a ticked row in the menu. A non-Climate indicator has neither (spec §1 decision 3)."""
    goto(page, "map?ind=surge_dw_pct", settle=1500)
    leg = page.locator("[data-testid=legend-zones]")
    assert leg.count() == 1 and leg.first.is_visible(), "no zones legend for a Climate indicator"
    assert page.evaluate("climOn()"), "the zones are not being drawn"
    lay_open(page)
    row = page.locator("[data-layer=zones]")
    assert row.count() == 1, "the menu has no zones row"
    assert row.first.get_attribute("aria-checked") == "true", "the zones row is not ticked"
    # ticking it off writes zones=0 and takes the legend away, without leaving the Climate family
    row.first.click()
    page.wait_for_timeout(1100)
    assert "zones=0" in cur_hash(page), f"hiding the zones is not in the hash: {cur_hash(page)!r}"
    assert page.locator("[data-testid=legend-zones]").count() == 0
    assert page.evaluate("curInd().key") == "surge_dw_pct", "hiding the zones changed the indicator"
    # a non-Climate indicator has neither the legend nor the row
    goto(page, "map?ind=growth", settle=1300)
    assert page.locator("[data-testid=legend-zones]").count() == 0, "a growth map still shows a zones legend"
    lay_open(page)
    assert page.locator("[data-layer=zones]").count() == 0, "a growth map still offers the zones row"
    # the v2.6 overlay link lands on the Climate indicator instead (route_core)
    goto(page, "map?ind=growth&climate=1", settle=1400)
    assert page.evaluate("curInd().key") == "surge_dw_pct", f"climate=1 did not convert: {cur_hash(page)!r}"
    assert page.locator("[data-testid=legend-zones]").first.is_visible()


@ac("AC-LG1", phase="P4")
def ac_lg1(page, base):
    """Every legend card sits inside the map, none overlaps another, and the stack keeps to the
    bottom 60 % of the map's height (spec §4.5)."""
    # Aarhus, not Copenhagen: in quarter mode the registry has no Climate keys, so curInds() would
    # swap the indicator out from under the test (v2.6 behaviour — see docs/v3/DECISIONS.md).
    goto(page, "map/751?ind=surge_dw_pct&lay=infra,public,services", settle=2500, wait="#serviceslegend *")
    boxes = rects(page, "[data-testid^=legend]")
    ids = sorted(b["id"] for b in boxes)
    assert ids == ["legend", "legend-infra", "legend-public", "legend-services", "legend-zones"], \
        f"the five legends are not all on the map: {ids}"
    m = rects(page, "[data-testid=map]")
    assert len(m) == 1, "no map box"
    m = m[0]
    top = m["bottom"] - m["h"] * 0.6
    for b in boxes:
        assert b["x"] >= m["x"] - 1 and b["right"] <= m["right"] + 1 and \
               b["y"] >= m["y"] - 1 and b["bottom"] <= m["bottom"] + 1, f"{b['id']} is outside the map: {b} vs {m}"
        assert b["y"] >= top - 1, f"{b['id']} reaches above 60 % of the map height ({b['y']:.0f} < {top:.0f})"
    for i, a in enumerate(boxes):
        for c in boxes[i + 1:]:
            over = not (a["right"] <= c["x"] + 1 or c["right"] <= a["x"] + 1
                        or a["bottom"] <= c["y"] + 1 or c["bottom"] <= a["y"] + 1)
            assert not over, f"{a['id']} overlaps {c['id']}: {a} / {c}"
    # keys only: the filters moved to Layers ▾, so no legend carries a toggle any more
    assert page.evaluate("""!document.querySelector('[data-testid^=legend] [data-pubcat],'
        + '[data-testid^=legend] [data-srvcat], [data-testid^=legend] [data-climlay]')"""), \
        "a legend still carries its filter buttons"


@ac("AC-M1", phase="P4")
def ac_m1(page, base):
    """The toolbar's first row is search, Layers ▾, the picker and the period control, in that
    order, and the second search box and the privacy paragraph are gone (spec §5.1)."""
    goto(page, "map?ind=growth", settle=1200)
    order = page.evaluate("""() => {
      const kids = [...document.querySelector('[data-testid=map-toolbar] [data-row="1"]').children];
      const at = sel => kids.findIndex(k => k.matches(sel) || k.querySelector(sel));
      return ['[data-testid=search]', '[data-testid=layers-btn]', '[data-testid=ind-picker]', '[data-testid=period]'].map(at);
    }""")
    assert order == [0, 1, 2, 3], f"the first row's controls are in the order {order}, expected [0, 1, 2, 3]"
    # one search box, and no paste box or privacy sentence left on the map
    assert page.locator("[data-testid=search]").count() == 1
    assert page.locator("#body #tpq").count() == 0, "the second 'Paste Google Maps link' box is still there"
    body = page.locator("#body").inner_text()
    for gone in ["Paste Google Maps link", "Processed in your browser"]:
        assert gone not in body, f"{gone!r} is still visible on the map"
    # the privacy sentence lives in the search box's ? tooltip instead
    assert "Processed in your browser" in page.evaluate(
        "document.querySelector('.asrch .tptipc').textContent"), "the privacy note is not in the tooltip"
    # full screen is a page action in the top bar, not a toolbar control
    assert page.locator("#hd [data-testid=map-full]").count() == 1, "the full-screen button is not in the top bar"


@ac("AC-M2", phase="P4")
def ac_m2(page, base):
    """A postal code typed into the search and taken with Enter opens its page — the v2.6 behaviour,
    through the new combobox."""
    goto(page, "map?ind=growth", settle=1000)
    page.fill("[data-testid=search]", "2450")
    page.wait_for_timeout(400)
    rows = texts(page, ".asrch .as-row")
    assert rows and "2450" in rows[0], f"the first result for 2450 is {rows[:2]}"
    page.press("[data-testid=search]", "Enter")
    page.wait_for_timeout(1200)
    assert cur_path(page) == "area/postnr/2450", f"Enter landed on {cur_hash(page)!r}"
    # a name works the same way
    goto(page, "map?ind=growth", settle=900)
    page.fill("[data-testid=search]", "Aarhus")
    page.wait_for_timeout(400)
    page.press("[data-testid=search]", "Enter")
    page.wait_for_timeout(1200)
    assert cur_path(page) == "map/751", f"a municipality name landed on {cur_hash(page)!r}"
    assert page.evaluate("MK.muni") == "751"


@ac("AC-M3", phase="P4")
def ac_m3(page, base):
    """Coordinates typed into the same box drop a pin on the map and keep the reader there: the hash
    gains pin=, the pin card names the place, and that card is the way on to the test property
    (spec §5.1 as amended by the owner review — P10 item 1; it used to navigate away at once)."""
    goto(page, "map?ind=growth", settle=1000)
    page.fill("[data-testid=search]", "55.6545, 12.539")
    page.wait_for_timeout(400)
    coord = page.locator("[data-testid=search-coord]")
    assert coord.count() == 1, "coordinates produced no search-coord result"
    assert "drop a pin" in coord.first.inner_text().lower(), coord.first.inner_text()
    coord.first.click()
    page.wait_for_timeout(1800)
    h = cur_hash(page)
    assert h.startswith("map"), f"the coord result left the map: {h!r}"
    assert "pin=55.65450,12.53900" in h, f"no pin in the hash: {h!r}"
    assert page.evaluate("S.view === 'makro'"), "the coord result changed the view"
    card = page.locator("[data-testid=pin-card]")
    assert card.count() == 1 and card.is_visible(), "no pin card under the toolbar"
    txt = card.inner_text()
    for want in ["55.65450, 12.53900", "København"]:
        assert want in txt, f"the pin card does not say {want!r}: {txt!r}"
    # the rings are drawn at the default 1 km and the camera went to the pin
    assert page.evaluate("TP.rad") == 1000, "the pin was dropped without the default radius"
    assert page.evaluate("window.__maps[0].getZoom()") >= 12, "the map did not go to the pin"
    # …and the card is the step on to the test property
    page.click("[data-testid=pin-open]")
    page.wait_for_timeout(1600)
    assert cur_hash(page).startswith("property?p=55.6545,12.539"), f"View test property went to {cur_hash(page)!r}"
    # a Google Maps link is read by the same box, and Enter does what the click does
    goto(page, "map?ind=growth", settle=900)
    page.fill("[data-testid=search]", "https://www.google.com/maps/@55.6761,12.5683,15z")
    page.wait_for_timeout(400)
    assert page.locator("[data-testid=search-coord]").count() == 1, "a Maps link produced no coord result"
    page.press("[data-testid=search]", "Enter")
    page.wait_for_timeout(1600)
    h = cur_hash(page)
    assert h.startswith("map") and "pin=55.67610,12.56830" in h, f"the link landed on {h!r}"
    # and ✕ takes the pin away again
    page.click("[data-testid=pin-card] [data-tp=remove]")
    page.wait_for_timeout(900)
    assert "pin=" not in cur_hash(page), f"removing the pin left {cur_hash(page)!r}"
    assert page.locator("[data-testid=pin-card]").count() == 0, "the card outlived its pin"


@ac("AC-P4SR", phase="P4")
def ac_p4sr(page, base):
    """P4-local: the two jump buttons moved into the search dropdown and still only move the camera —
    zooming is not selecting (spec §5.1, §0). The C / D shortcuts are unchanged."""
    goto(page, "map?ind=growth", settle=1200)
    assert page.locator(".asrch .as-jump").count() == 0 or not page.locator(".asrchpop").is_visible(), \
        "the dropdown starts closed"
    page.click("[data-testid=search]")
    page.wait_for_timeout(400)
    jumps = texts(page, ".asrch .as-jump button")
    assert jumps == ["Copenhagen", "Denmark"], f"the Jump to row offers {jumps}"
    before = cur_hash(page)
    z0 = page.evaluate("window.__maps[0].getZoom()")
    page.click(".asrch .as-jump button[data-mapjump=cph]")
    page.wait_for_timeout(900)
    assert page.evaluate("window.__maps[0].getZoom()") > z0, "the Copenhagen jump did not move the camera"
    assert cur_hash(page) == before, f"a jump changed the selection: {before!r} → {cur_hash(page)!r}"
    assert page.evaluate("MK.muni") is None, "a jump selected a municipality"
    # the keyboard shortcut does the same thing, and does not type into the search box
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("d")
    page.wait_for_timeout(800)
    assert page.evaluate("window.__maps[0].getZoom()") <= z0 + 0.5, "the D shortcut did not go back to Denmark"
    assert cur_hash(page) == before
    # …and it leaves the dropdown alone when the caret is in it
    page.click("[data-testid=search]")
    page.type("[data-testid=search]", "c")
    page.wait_for_timeout(400)
    assert page.eval_on_selector("[data-testid=search]", "e => e.value") == "c", \
        "a letter typed into the search box was eaten by the map shortcut"


@ac("AC-M4", phase="P4")
def ac_m4(page, base):
    """An Outlook indicator draws in purple and says it is a projection; Climate draws in blue. A
    projection must never be mistaken for an observed figure (spec §2.1, §2.4)."""
    goto(page, "map?ind=fc_growth", settle=1500)
    bins = page.evaluate("""() => [...document.querySelectorAll('[data-testid=legend] .lgrow i')]
        .map(e => getComputedStyle(e).backgroundColor)
        .map(s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number))
        .filter(c => c.length === 3)""")
    assert len(bins) >= 4, f"the legend has too few swatches to read: {bins}"
    r, g, b = bins[0]          # the darkest class is the first row of the legend
    assert b > r and b > g, f"the darkest Outlook bin is not purple: rgb({r},{g},{b})"
    strip = page.locator("#mkexplain").inner_text()
    assert "Projection" in strip, f"the info strip does not say Projection: {strip[:160]!r}"
    # Climate keeps the blue ramp
    goto(page, "map?ind=sealevel_cm", settle=1500)
    cb = page.evaluate("""() => { const e = document.querySelector('[data-testid=legend] .lgrow i');
        return (getComputedStyle(e).backgroundColor.match(/[\\d.]+/g) || []).slice(0, 3).map(Number); }""")
    assert cb[2] > cb[0] and cb[2] > cb[1], f"the darkest Climate bin is not blue: {cb}"


@ac("AC-S3", phase="P4", viewport="1366x768")
def ac_s3(page, base):
    """At 1366×768 the map itself starts inside the first screen and keeps its height — one toolbar
    row is what buys the ~70 px this needs (spec §4.1, §5.1)."""
    goto(page, "map?ind=growth", settle=1600)
    box = page.locator("[data-testid=map]").bounding_box()
    assert box, "no map box"
    assert box["y"] <= 200, f"the map starts {box['y']:.0f} px down, the spec allows 200"
    assert box["height"] >= 480, f"the map is only {box['height']:.0f} px tall, the spec wants 480"
    # and the drilled state keeps its extra segments and its municipality card without pushing the
    # map off the first screen — the card is collapsed by default (spec §5.1)
    goto(page, "map/101?ind=growth", settle=1600)
    box = page.locator("[data-testid=map]").bounding_box()
    assert box["y"] <= 320, f"the drilled map starts {box['y']:.0f} px down"
    assert box["y"] + 300 <= 768, f"less than 300 px of the drilled map is on the first screen (top {box['y']:.0f})"


# =============================================================================================
# P5 — the area page rebuilt around the study row
# =============================================================================================
AREA = "area/kommune/101?ind=growth"


def box_of(page, selector):
    b = page.locator(selector).first.bounding_box()
    assert b, f"no bounding box for {selector}"
    return b


@ac("AC-P1", phase="P5")
def ac_p1(page, base):
    """The study row is the chart panel and the mini map, side by side, the same height — and the
    v2.6 KEY FIGURES block is gone (spec §5.2, §8)."""
    goto(page, AREA, settle=1800, wait="#armap .leaflet-pane")
    body = page.inner_text("#body")
    assert "KEY FIGURES" not in body.upper(), "the KEY FIGURES block is still on the page"
    # siblings inside the row, panel first
    kids = page.evaluate("""() => [...document.querySelector('[data-testid=study-row]').children]
        .map(e => e.dataset.testid || e.tagName)""")
    assert kids == ["chart-panel", "minimap"], f"the study row's children are {kids}"
    row, panel, mm = box_of(page, "[data-testid=study-row]"), box_of(page, "[data-testid=chart-panel]"), box_of(page, "[data-testid=minimap]")
    assert abs(panel["height"] - mm["height"]) <= 2, \
        f"panel {panel['height']:.1f} px vs mini map {mm['height']:.1f} px — the spec wants ±2"
    assert panel["x"] + panel["width"] <= mm["x"] + 1, "the panel is not left of the map"
    pw, mw = panel["width"] / row["width"] * 100, mm["width"] / row["width"] * 100
    assert 55 <= pw <= 65, f"the panel is {pw:.1f} % of the row, the spec wants 55–65"
    assert 35 <= mw <= 45, f"the mini map is {mw:.1f} % of the row, the spec wants 35–45"
    # the separate Trend and Neighbours cards are gone with it — one panel, one map
    assert page.locator("[data-testid=chart-panel]").count() == 1
    assert page.locator("[data-testid=minimap]").count() == 1


@ac("AC-P2", phase="P5")
def ac_p2(page, base):
    """Population outlook opens itself on a municipality page and not on a postal code; toggling a
    section writes show=, and a link carrying show= opens what it names (spec §5.2, §3.2)."""
    goto(page, AREA, settle=1500)
    assert page.evaluate("document.querySelector('[data-testid=sec-outlook]').open"), \
        "Population outlook is closed on a municipality page"
    assert not page.evaluate("document.querySelector('[data-testid=sec-figures]').open")
    # opening a second one writes it into the hash
    page.click("[data-testid=sec-figures] summary")
    page.wait_for_timeout(500)
    h = cur_hash(page)
    assert "show=" in h and "figures" in h.split("show=")[1].split("&")[0], f"toggling did not reach the hash: {h!r}"
    # closing the one that opens itself is a state of its own, not "the default"
    page.click("[data-testid=sec-outlook] summary")
    page.click("[data-testid=sec-figures] summary")
    page.wait_for_timeout(500)
    assert "show=none" in cur_hash(page), f"closing every section gave {cur_hash(page)!r}"

    goto(page, "area/postnr/2450?ind=growth", settle=1500)
    assert page.locator("[data-testid=sec-outlook]").count() == 0 or \
        not page.evaluate("document.querySelector('[data-testid=sec-outlook]').open"), \
        "Population outlook opened itself on a postal-code page"
    goto(page, "area/postnr/2450?ind=growth&show=figures", settle=1500)
    assert page.evaluate("document.querySelector('[data-testid=sec-figures]').open"), \
        "?show=figures did not open All figures"


@ac("AC-P3", phase="P5")
def ac_p3(page, base):
    """The panel draws what the indicator family has: three horizon bars for Climate (with the
    horizon control beside it), the outlook chart for a projection (spec §5.2)."""
    goto(page, "area/kommune/101?ind=surge_dw_pct", settle=1800)
    bars = page.locator("[data-testid=chart-panel] [data-testid=clim-bars] [data-bar]")
    assert bars.count() == 3, f"expected 3 horizon bars, got {bars.count()}"
    hz = page.evaluate("""[...document.querySelectorAll('[data-testid=clim-bars] [data-bar]')].map(e => e.dataset.hz)""")
    assert hz == ["today", "2070", "2120"], f"the bars are {hz}"
    assert page.locator("[data-testid=period-hz]").first.is_visible(), "no horizon control beside a Climate indicator"
    assert page.locator("[data-testid=period-year]").count() == 0, "a year selector next to a Climate indicator"
    assert "Climate sheet" in page.inner_text("[data-testid=chart-panel]")

    goto(page, "area/kommune/101?ind=fc_growth", settle=1800)
    assert page.locator("[data-testid=chart-panel] [data-testid=outlook-chart]").count() == 1, \
        "an Outlook indicator does not draw the outlook chart"
    assert page.locator("[data-testid=period-proj]").count() == 1, "no projection badge"
    assert page.locator("[data-testid=clim-bars]").count() == 0


@ac("AC-P4", phase="P5")
def ac_p4(page, base):
    """Choosing an indicator updates the panel and the mini map in place: the heading and the legend
    title change, the scroll position does not, and it works inside the full-screen map too."""
    goto(page, AREA, settle=1800, wait="#armap .leaflet-pane")
    page.evaluate("document.getElementById('main').scrollTop = 220")
    page.wait_for_timeout(200)
    before = dict(top=page.evaluate("document.getElementById('main').scrollTop"),
                  title=page.inner_text("[data-testid=panel-title]"),
                  leg=page.inner_text("[data-testid=minimap] .lgtitle"),
                  map=page.evaluate("window.__maps.length"))
    del ERRORS[:]
    page.click("[data-testid=ind-chips] .chip[data-ind=unemp]")
    page.wait_for_timeout(900)
    after = dict(top=page.evaluate("document.getElementById('main').scrollTop"),
                 title=page.inner_text("[data-testid=panel-title]"),
                 leg=page.inner_text("[data-testid=minimap] .lgtitle"))
    assert after["title"] != before["title"], f"the panel heading did not change: {after['title']!r}"
    assert after["leg"] != before["leg"], f"the mini-map legend title did not change: {after['leg']!r}"
    assert abs(after["top"] - before["top"]) <= 2, \
        f"the page scrolled {abs(after['top'] - before['top'])} px — this must be an update in place"
    assert "ind=unemp" in cur_hash(page)
    # in place means the map was never rebuilt
    assert page.evaluate("window.__maps.length") == before["map"] == 1
    assert not ERRORS, f"pageerror while updating in place: {ERRORS[:2]}"

    # …and the same while the mini map is full screen (spec §5.2 item 4). The overlay covers the
    # page's own toolbar, so the chips it needs come with it — [data-testid=minimap-chips].
    page.click("[data-testid=minimap-full]")
    page.wait_for_timeout(500)
    assert page.evaluate("document.querySelector('[data-testid=minimap]').classList.contains('is-full')")
    t1 = page.inner_text("[data-testid=minimap] .lgtitle")
    chip = page.locator("[data-testid=minimap-chips] .chip[data-ind=renters]")
    assert chip.count() == 1, "the full-screen map offers no way to choose another indicator"
    chip.click()
    page.wait_for_timeout(900)
    assert page.evaluate("document.querySelector('[data-testid=minimap]').classList.contains('is-full')"), \
        "picking an indicator dropped out of full screen"
    assert page.inner_text("[data-testid=minimap] .lgtitle") != t1, "the full-screen map did not follow the pick"
    assert "ind=renters" in cur_hash(page)
    assert page.evaluate("window.__maps.length") == 1, "the map was rebuilt inside full screen"
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert not page.evaluate("document.querySelector('[data-testid=minimap]').classList.contains('is-full')")


@ac("AC-P5", phase="P5", viewport="390x844")
def ac_p5(page, base):
    """At phone width the panel stacks above the map, each keeps its height, and nothing in the study
    row is wider than the column it sits in (spec §6).

    The page-level "no horizontal overflow at 390" of AC-R1 is the app shell's, not this row's: the
    ≤900 px media query still gives the sidebar a full-width grid column, which is P8's rebuild. What
    is checked here is that the study row adds none of its own. (A Leaflet container always reports
    scrollWidth > clientWidth — it paints tiles past its edges — so the map is judged on its wrapper,
    which clips them.)
    """
    goto(page, AREA, settle=2000, wait="#armap .leaflet-pane")
    panel, mm = box_of(page, "[data-testid=chart-panel]"), box_of(page, "[data-testid=minimap]")
    assert panel["y"] + panel["height"] <= mm["y"] + 2, "the panel is not above the map"
    assert panel["height"] >= 300, f"the panel is {panel['height']:.0f} px tall, the spec wants 300"
    assert mm["height"] >= 300, f"the mini map is {mm['height']:.0f} px tall, the spec wants 300"
    over = page.evaluate("""() => {
      const row = document.querySelector('[data-testid=study-row]');
      const els = [row, ...row.children].filter(e => e.scrollWidth > e.clientWidth + 2);
      return { bad: els.map(e => (e.dataset.testid || e.tagName) + ' ' + e.scrollWidth + '>' + e.clientWidth),
               rowW: row.getBoundingClientRect().width,
               hostW: document.getElementById('body').clientWidth }; }""")
    assert not over["bad"], f"the study row or one of its two halves scrolls sideways: {over['bad']}"
    assert over["rowW"] <= over["hostW"] + 2, \
        f"the study row is {over['rowW']:.0f} px inside a {over['hostW']:.0f} px column"


@ac("AC-H1", phase="P5")
def ac_h1(page, base):
    """On a postal-code page the tiles whose figure is the municipality's say so, and the ones with
    a figure of their own do not (spec §4.7, §1 decision 7)."""
    goto(page, "area/postnr/2450?ind=growth", settle=1500)
    for key in ["rent_private", "unemp", "renters"]:
        t = page.locator(f"[data-testid=tile-{key}]")
        assert t.count() == 1, f"no tile for {key}"
        cls = t.first.get_attribute("class") or ""
        assert "inh" in cls.split(), f"tile-{key} is not marked inherited: class={cls!r}"
        assert "municipality figure" in t.first.inner_text(), f"tile-{key} does not say whose figure it is"
    own = page.locator("[data-testid=tile-growth]")
    assert own.count() == 1
    assert "inh" not in (own.first.get_attribute("class") or "").split(), "the area's own figure is marked inherited"
    assert "municipality figure" not in own.first.inner_text()
    # a lone ° is never the whole explanation any more (spec §1 decision 7)
    assert "°" not in page.inner_text("[data-testid=tiles]")


@ac("AC-H2", phase="P5")
def ac_h2(page, base):
    """A tile is a way of choosing an indicator: clicking it writes ind= and moves the picker."""
    goto(page, AREA, settle=1500)
    page.click("[data-testid=tile-unemp]")
    page.wait_for_timeout(800)
    assert "ind=unemp" in cur_hash(page), f"the tile did not write ind=unemp: {cur_hash(page)!r}"
    btn = page.inner_text("[data-testid=ind-picker-btn]").strip()
    assert btn.startswith("Unemployment"), f"the picker button says {btn!r}"
    assert "on" in (page.get_attribute("[data-testid=tile-unemp]", "class") or "").split(), \
        "the chosen tile is not marked active"


@ac("AC-I5", phase="P5")
def ac_i5(page, base):
    """On a postal-code page the municipality's indicators are listed under one sub-heading in the
    picker, each carrying the muni tag — never scattered through the twelve groups (spec §4.2)."""
    goto(page, "area/postnr/2450?ind=growth", settle=1500)
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(300)
    sec = page.locator('[data-testid=ind-picker-pop] [data-group="From the municipality"]')
    assert sec.count() == 1, "there is no 'From the municipality' group on a postal-code page"
    keys = page.evaluate("""() => [...document.querySelectorAll('[data-group="From the municipality"] .indrow')]
        .map(r => ({ key: r.dataset.ind, tag: !!r.querySelector('.tag-muni') }))""")
    assert keys, "the group is empty"
    for r in keys:
        assert r["tag"], f"row {r['key']!r} is in the municipality group without a .tag-muni"
    inside = {r["key"] for r in keys}
    for k in ["unemp", "rent_private", "renters"]:
        assert k in inside, f"{k} is a municipality-level figure here but is not in the group"
    # and an indicator the postal code publishes itself stays where it belongs
    grp = page.evaluate("""() => { const r = document.querySelector('.indrow[data-ind=growth]');
        return r ? r.closest('[data-group]').dataset.group : null; }""")
    assert grp == "Demographics", f"growth is a postal-code figure but sits under {grp!r}"
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # on a municipality page nothing is inherited, so the sub-heading is not there at all
    goto(page, AREA, settle=1200)
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(300)
    assert page.locator('[data-testid=ind-picker-pop] [data-group="From the municipality"]').count() == 0
    page.keyboard.press("Escape")


@ac("AC-E2", phase="P5")
def ac_e2(page, base):
    """An indicator published once has no trend to draw: the panel says so and puts the area on a
    distribution strip against its peers instead (spec §4.10, §5.2)."""
    goto(page, "area/kommune/101?ind=renters_bbr", settle=1800)
    assert page.locator("[data-testid=chart-panel] [data-testid=state-nohistory]").count() == 1, \
        "no state-nohistory in the panel"
    assert page.locator("[data-testid=chart-panel] [data-testid=dist-strip]").count() == 1, \
        "no distribution strip"
    txt = page.inner_text("[data-testid=state-nohistory]")
    assert "BBR" in txt, f"the state card does not name the as-of: {txt!r}"
    # nothing is drawn as a trend
    assert page.locator("[data-testid=chart-panel] svg.chart:not(.diststrip)").count() == 0, \
        "a line chart was drawn for an indicator with no history"


@ac("AC-MM1", phase="P5")
def ac_mm1(page, base):
    """The area page's mini map drags — 120 px of pointer moves its centre (spec §4.6)."""
    goto(page, AREA, settle=1800, wait="#armap .leaflet-pane")
    assert page.evaluate("LF.amap.dragging.enabled()"), "the mini map is not draggable"
    before = map_center(page)
    drag(page, "[data-testid=minimap] .leaflet-container", 120, 0)
    after = map_center(page)
    assert abs(after[0] - before[0]) + abs(after[1] - before[1]) > 1e-5, \
        f"a 120 px drag did not move the centre: {before} → {after}"
    # and it is still the same page: a drag or a zoom never changes the selection
    assert cur_path(page) == "area/kommune/101", f"dragging navigated to {cur_hash(page)!r}"
    page.evaluate("window.__maps[0].setZoom(11)")
    page.wait_for_timeout(700)
    assert cur_path(page) == "area/kommune/101" and page.evaluate("AR.code") == "101", \
        "zooming the mini map changed the selection"


@ac("AC-MM2", phase="P5")
def ac_mm2(page, base):
    """⤢ makes the mini map a full-screen overlay and Escape gives the page back (spec §4.6)."""
    goto(page, AREA, settle=1800, wait="#armap .leaflet-pane")
    small = box_of(page, "[data-testid=minimap]")
    page.click("[data-testid=minimap-full]")
    page.wait_for_timeout(600)
    cls = page.get_attribute("[data-testid=minimap]", "class") or ""
    assert "is-full" in cls.split(), f"⤢ did not put the map full screen: class={cls!r}"
    full = box_of(page, "[data-testid=minimap]")
    vw, vh = page.evaluate("[window.innerWidth, window.innerHeight]")
    assert full["width"] >= vw * 0.9 and full["height"] >= vh * 0.9, \
        f"full screen is {full['width']:.0f}×{full['height']:.0f} of {vw}×{vh}"
    # the map itself was told about its new size, not just the box around it
    size = page.evaluate("() => { const s = LF.amap.getSize(); return [s.x, s.y]; }")
    assert size[0] >= vw * 0.9 and size[1] >= vh * 0.9, f"invalidateSize() did not run: map is {size}"
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    back = box_of(page, "[data-testid=minimap]")
    assert "is-full" not in (page.get_attribute("[data-testid=minimap]", "class") or "").split()
    assert abs(back["width"] - small["width"]) <= 2, f"Escape did not restore the box: {back['width']} vs {small['width']}"


@ac("AC-R2", phase="P5", viewport="1366x768")
def ac_r2(page, base):
    """At 1366×768 the chart | map row starts inside the first screen — the header, the tiles and one
    toolbar row are all that may come before it (spec §6)."""
    goto(page, AREA, settle=1800, wait="#armap .leaflet-pane")
    row = box_of(page, "[data-testid=study-row]")
    assert row["y"] < 768, f"the study row starts {row['y']:.0f} px down, below the fold"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"), \
        "the area page scrolls sideways at 1366"


# =============================================================================================
# P6 — the test property rebuilt around the study row (spec §5.5′, amendments A2/A3)
# =============================================================================================
TP = "property?p=55.6545,12.539&ind=growth"


@ac("AC-TP2", phase="P6")
def ac_tp2(page, base):
    """The test property is the area page's study row pointed at the pin's finest area: the chart
    panel and the mini map side by side, the map drags, ⤢ works, and nothing throws (spec §5.5′)."""
    goto(page, TP, settle=2200, wait="#anmap .leaflet-pane")
    del ERRORS[:]
    kids = page.evaluate("""() => [...document.querySelector('[data-testid=study-row]').children]
        .map(e => e.dataset.testid || e.tagName)""")
    assert kids == ["chart-panel", "minimap"], f"the study row's children are {kids}"
    assert page.locator("[data-testid=chart-panel]").count() == 1
    assert page.locator("[data-testid=minimap]").count() == 1
    assert page.evaluate("window.__maps.length") == 1, "the test property owns exactly one map"
    # the entity is the pin's finest area, and it is named as such
    lvl = page.evaluate("(() => { const e = anEntity(); return e && e.type; })()")
    assert lvl == "kvarter", f"55.6545,12.539 is a Copenhagen quarter, the page read it as {lvl!r}"
    # dragging moves the centre — and never changes which property the page is about
    before = map_center(page)
    drag(page, "[data-testid=minimap] .leaflet-container", 120, 0)
    after = map_center(page)
    assert abs(after[0] - before[0]) + abs(after[1] - before[1]) > 1e-5, \
        f"a 120 px drag did not move the centre: {before} → {after}"
    assert cur_hash(page).startswith("property?p=55.6545,12.539"), f"dragging navigated to {cur_hash(page)!r}"
    # ⤢ full screen and back
    page.click("[data-testid=minimap-full]")
    page.wait_for_timeout(600)
    assert "is-full" in (page.get_attribute("[data-testid=minimap]", "class") or "").split()
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    assert "is-full" not in (page.get_attribute("[data-testid=minimap]", "class") or "").split()
    assert not ERRORS, f"pageerror on the test property: {ERRORS[:2]}"


@ac("AC-TP3", phase="P6")
def ac_tp3(page, base):
    """A headline tile is a way of choosing an indicator here too: it writes ind= and the mini map's
    legend follows — in place, without rebuilding the map (spec §5.5′ item 2)."""
    goto(page, TP, settle=2200, wait="#anmap .leaflet-pane")
    del ERRORS[:]
    # the indicator legend is the first card of the mini map's stack; the overlays have their own
    before = page.inner_text("[data-testid=minimap] .mm-leg .lgtitle")
    maps = page.evaluate("window.__maps.length")
    tile = page.locator("[data-testid=tile-unemp]")
    assert tile.count() == 1, "no unemployment tile on the test property"
    tile.click()
    page.wait_for_timeout(900)
    assert "ind=unemp" in cur_hash(page), f"the tile did not write ind=unemp: {cur_hash(page)!r}"
    assert page.inner_text("[data-testid=minimap] .mm-leg .lgtitle") != before, \
        "the mini-map legend title did not follow the tile"
    # the picker follows too. The label is the registry's for the level on screen — a Copenhagen
    # quarter reads KK's "Unemployed (Nov.)", not DST's "Unemployment rate" — so the key is checked.
    assert page.evaluate("document.querySelector('[data-testid=ind-picker-btn]').dataset.ind") == "unemp", \
        f"the picker button says {page.inner_text('[data-testid=ind-picker-btn]')!r}"
    assert "on" in (page.get_attribute("[data-testid=tile-unemp]", "class") or "").split(), \
        "the chosen tile is not marked active"
    assert page.evaluate("window.__maps.length") == maps == 1, "the map was rebuilt instead of repainted"
    assert not ERRORS, f"pageerror while choosing an indicator: {ERRORS[:2]}"


@ac("AC-TP5", phase="P6")
def ac_tp5(page, base):
    """A Google Maps link pasted into the box REPLACES the pin — one property at a time (A2)."""
    goto(page, TP, settle=2000, wait="#anmap .leaflet-pane")
    box = page.locator("[data-testid=prop-input]")
    assert box.count() == 1, "there is not exactly one paste box"
    box.fill("https://www.google.com/maps/@55.6761,12.5683,15z")
    box.press("Enter")
    page.wait_for_timeout(1400)
    h = cur_hash(page)
    assert h.startswith("property?p=55.6761,12.5683"), f"the pasted link landed on {h!r}"
    p = h.split("p=")[1].split("&")[0]
    assert ";" not in p, f"more than one pin in p={p!r} — a new link replaces, it does not append"
    assert page.evaluate("AN.a") == "55.6761,12.5683"
    # and the Go button does the same thing as Enter
    box = page.locator("[data-testid=prop-input]")
    box.fill("55.6545, 12.539")
    page.click("[data-tpgo]")
    page.wait_for_timeout(1400)
    assert cur_hash(page).startswith("property?p=55.6545,12.539"), f"Go landed on {cur_hash(page)!r}"


@ac("AC-E1", phase="P6")
def ac_e1(page, base):
    """#property with no p= is the empty state, with the caret already in the box (spec §4.10)."""
    goto(page, "property", settle=900)
    assert page.locator("[data-testid=state-empty]").count() == 1, "no state-empty card"
    box = page.locator("[data-testid=state-empty] [data-testid=prop-input]")
    assert box.count() == 1, "the empty state has no text input"
    assert page.evaluate("document.activeElement === document.querySelector('[data-testid=prop-input]')"), \
        "the input must have focus on the empty state"
    # one example link, and it opens a property
    ex = page.locator("[data-testid=state-empty] [data-go^='property?p=']")
    assert ex.count() == 1, "the empty state offers no example link"
    assert not page.locator("[data-testid=study-row]").count(), "an empty page drew a study row"


@ac("AC-MM1TP", phase="P6")
def ac_mm1_tp(page, base):
    """AC-MM1 on the test property: the mini map is draggable and zooming it never re-selects."""
    goto(page, TP, settle=2200, wait="#anmap .leaflet-pane")
    assert page.evaluate("LF.anmap.dragging.enabled()"), "the mini map is not draggable"
    before = map_center(page)
    drag(page, "[data-testid=minimap] .leaflet-container", 0, 120)
    assert abs(map_center(page)[0] - before[0]) > 1e-5, "a 120 px drag did not move the centre"
    page.evaluate("() => { window.__maps[0].setZoom(12); }")   # setZoom returns the map; do not serialise it
    page.wait_for_timeout(700)
    assert page.evaluate("AN.a") == "55.6545,12.539", "zooming the mini map changed the property"
    assert cur_path(page) == "property", f"zooming navigated to {cur_hash(page)!r}"
    # ⌖ brings the property back to the middle
    page.click("[data-testid=minimap-recentre]")
    page.wait_for_timeout(700)
    back = map_center(page)
    assert abs(back[0] - 55.6545) < 1e-3 and abs(back[1] - 12.539) < 1e-3, f"⌖ did not re-centre: {back}"


@ac("AC-MM2TP", phase="P6")
def ac_mm2_tp(page, base):
    """AC-MM2 on the test property: ⤢ fills the viewport and the map is told its new size."""
    goto(page, TP, settle=2200, wait="#anmap .leaflet-pane")
    small = box_of(page, "[data-testid=minimap]")
    page.click("[data-testid=minimap-full]")
    page.wait_for_timeout(700)
    full = box_of(page, "[data-testid=minimap]")
    vw, vh = page.evaluate("[window.innerWidth, window.innerHeight]")
    assert full["width"] >= vw * 0.9 and full["height"] >= vh * 0.9, \
        f"full screen is {full['width']:.0f}×{full['height']:.0f} of {vw}×{vh}"
    size = page.evaluate("() => { const s = LF.anmap.getSize(); return [s.x, s.y]; }")
    assert size[0] >= vw * 0.9 and size[1] >= vh * 0.9, f"invalidateSize() did not run: map is {size}"
    # the overlay covers the toolbar, so it carries the chips — and a pick keeps full screen
    chip = page.locator("[data-testid=minimap-chips] .chip[data-ind=renters]")
    assert chip.count() == 1, "the full-screen map offers no way to choose another indicator"
    chip.click()
    page.wait_for_timeout(900)
    assert page.evaluate("document.querySelector('[data-testid=minimap]').classList.contains('is-full')"), \
        "picking an indicator dropped out of full screen"
    assert "ind=renters" in cur_hash(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    back = box_of(page, "[data-testid=minimap]")
    assert "is-full" not in (page.get_attribute("[data-testid=minimap]", "class") or "").split()
    assert abs(back["width"] - small["width"]) <= 2, f"Escape did not restore the box: {back['width']} vs {small['width']}"


@ac("AC-TPSEC", phase="P6")
def ac_tpsec(page, base):
    """P6-local: the eight sections are <details> whose open set is the one show= key (spec §5.5′
    item 4), Infrastructure nearby opens itself, and identical BBR rows are folded with a count."""
    goto(page, TP, settle=2400, wait="#anmap .leaflet-pane")
    names = ["outlook", "profile", "safety", "infra", "public", "schools", "climate", "sources"]
    for k in names:
        assert page.locator(f"[data-testid=tp-sec-{k}]").count() == 1, f"no tp-sec-{k} section"
    assert page.evaluate("document.querySelector('[data-testid=tp-sec-infra]').open"), \
        "Infrastructure nearby does not open itself"
    for k in ["outlook", "profile", "safety", "public", "schools", "climate", "sources"]:
        assert not page.evaluate(f"document.querySelector('[data-testid=tp-sec-{k}]').open"), \
            f"tp-sec-{k} opened itself — only infra does"
    # opening one writes it into the hash; closing every one is a state of its own
    page.click("[data-testid=tp-sec-profile] summary")
    page.wait_for_timeout(500)
    show = cur_hash(page).split("show=")[1].split("&")[0] if "show=" in cur_hash(page) else ""
    assert "profile" in show and "infra" in show, f"toggling did not reach the hash: {cur_hash(page)!r}"
    page.click("[data-testid=tp-sec-profile] summary")
    page.click("[data-testid=tp-sec-infra] summary")
    page.wait_for_timeout(500)
    assert "show=none" in cur_hash(page), f"closing every section gave {cur_hash(page)!r}"
    # and a link carrying show= opens what it names
    goto(page, "property?p=55.6545,12.539&ind=growth&show=public", settle=2400, wait="#anmap .leaflet-pane")
    assert page.evaluate("document.querySelector('[data-testid=tp-sec-public]').open")
    assert not page.evaluate("document.querySelector('[data-testid=tp-sec-infra]').open")
    # duplicate BBR records are one row with a count, never several identical lines
    dupes = page.evaluate("""() => {
      const seen = {}, out = [];
      document.querySelectorAll('[data-testid=tp-sec-public] tbody tr[data-pubsheet]').forEach(tr => {
        const k = tr.querySelector('.thn').textContent.trim() + '|' + tr.children[1].textContent.trim()
                + '|' + tr.children[3].textContent.trim();
        if (seen[k]) out.push(k); else seen[k] = 1;
      });
      return out; }""")
    assert not dupes, f"identical public-building rows were not grouped: {dupes[:3]}"


# =============================================================================================
# P7 — one export model, with sources on every row (spec §4.9, §5.5′)
# =============================================================================================
LONG_HEADER = ("level;code;name;parent_code;parent_name;region;population;indicator;label;unit;"
               "period;period_type;value;value_type;inherited_from;direction;source;table_id;"
               "source_url;as_of;fetched;licence")


@ac("AC-X1", phase="P7")
def ac_x1(page, base):
    """Clicking [data-testid=export-btn] opens [data-testid=export-menu] with at least six
    [data-export] items; triggering [data-export=areas] downloads a file whose first line is the
    long schema of spec §4.9, and a one-line toast says what was written."""
    goto(page, "data/areas/kommune?ind=growth", settle=700)
    menu = open_export(page)
    n = menu.locator("[data-export]").count()
    assert n >= 6, f"the menu has {n} [data-export] item(s), spec §4.9 lists at least six"
    for k in ["view", "areas", "projects", "national", "sources", "climate", "property"]:
        assert menu.locator(f"[data-export={k}]").count() == 1, f"no [data-export={k}] item"
    assert page.locator("[data-testid=export-menu]").first.get_attribute("role") == "dialog"
    name, lines = export_csv(page, "areas")
    assert lines[0] == LONG_HEADER, f"areas_long header:\n{lines[0]}\nexpected:\n{LONG_HEADER}"
    assert name.startswith("areas_long_") and name.endswith(".csv"), name
    assert len(lines) > 1000, f"areas_long has only {len(lines) - 1} row(s)"
    toast = page.locator("[data-testid=export-toast]")
    assert toast.count() == 1, "no export toast"
    txt = (toast.inner_text() or "").replace("\n", " ")
    assert name in txt and "row" in txt, f"the toast says {txt!r}, expected {name} and a row count"


@ac("AC-X2", phase="P7")
def ac_x2(page, base):
    """In areas_long every row whose unit contains kDKK has |value| < 10 000 — the v2.6 export
    labelled DKK values as kDKK (engineering brief §3.3). Adapted per the P7 phase file: an income
    row is written in DKK, losslessly. Every `income` row on a municipality is `actual`."""
    goto(page, "data/areas/kommune?ind=growth", settle=700)
    _, lines = export_csv(page, "areas")
    head, rows = csv_rows(lines)
    bad = [r for r in rows if "kDKK" in r["unit"] and abs(float(r["value"] or 0)) >= 10000]
    assert not bad, f"{len(bad)} kDKK row(s) with a DKK-sized value, e.g. {bad[0]}"
    inc = [r for r in rows if r["indicator"] == "income" and r["level"] == "municipality"]
    assert inc, "no income rows on municipalities"
    for r in inc:
        assert r["value_type"] == "actual", f"income is a published cell, not {r['value_type']}"
        assert r["unit"].startswith("DKK"), f"income unit {r['unit']!r} — the values are stored in DKK"
        assert abs(float(r["value"])) > 10000, "an income in DKK is a five- or six-figure number"


@ac("AC-X3", phase="P7")
def ac_x3(page, base):
    """The projects file has no `indicator` column (its own schema, never an indicator row), and
    areas_long has no `project` or `macro` level — the v2.6 export jammed both into one file."""
    goto(page, "data/projects", settle=700)
    name, plines = export_csv(page, "projects")
    phead = plines[0].split(";")
    assert name.startswith("projects_"), name
    for c in ["indicator", "value", "unit", "period"]:
        assert c not in phead, f"the projects file has an indicator column: {c}"
    for c in ["id", "name", "type", "status", "opening", "budget_mdkk", "municipalities",
              "postal_codes", "quarters", "geometry_kind", "source_url", "updated"]:
        assert c in phead, f"the projects file is missing {c}"
    assert len(plines) - 1 == page.evaluate("INFRA_ALL.length"), "one row per project in the layer"
    _, alines = export_csv(page, "areas")
    _, arows = csv_rows(alines)
    levels = sorted({r["level"] for r in arows})
    assert "project" not in levels and "macro" not in levels, levels
    assert levels == ["copenhagen_quarter", "municipality", "postal_code"], levels


@ac("AC-X4", phase="P7")
def ac_x4(page, base):
    """Every areas_long row has a non-empty source and as_of; every row on a postal code or a
    quarter whose indicator is a municipality-level one is `inherited` and names the municipality
    it was read from."""
    goto(page, "data/areas/kommune?ind=growth", settle=700)
    _, lines = export_csv(page, "areas")
    head, rows = csv_rows(lines)
    for c in ["source", "as_of", "table_id", "fetched"]:
        blank = [r for r in rows if not (r[c] or "").strip()]
        assert not blank, f"{len(blank)} row(s) with a blank {c}, e.g. {blank[0]}"
    muni_keys = set(page.evaluate("IND.filter(i => i.level === 'kommune').map(i => i.key)"))
    q_muni_keys = set(page.evaluate("IND_Q.filter(i => i.level === 'kommune').map(i => i.key)"))
    # the one Climate figure that is published per postal code and per quarter, not inherited
    zone_key = "surge_dw_pct"
    fine = {"postal_code": muni_keys, "copenhagen_quarter": q_muni_keys}
    for r in rows:
        keys = fine.get(r["level"])
        if keys and r["indicator"] in keys and r["indicator"] != zone_key:
            assert r["value_type"] == "inherited", f"{r['level']} {r['code']} {r['indicator']} is {r['value_type']}"
            assert r["inherited_from"], f"{r['level']} {r['code']} {r['indicator']} has no inherited_from"
        if r["value_type"] == "inherited":
            assert r["inherited_from"], f"inherited row without inherited_from: {r}"
    inh = [r for r in rows if r["value_type"] == "inherited"]
    assert len(inh) > 1000, f"only {len(inh)} inherited rows — the postal codes read 40-odd of them"
    assert sorted({r["period_type"] for r in rows}) and \
        {"year", "projection", "horizon", "snapshot"} <= {r["period_type"] for r in rows}, \
        sorted({r["period_type"] for r in rows})


@ac("AC-TP4", phase="P7")
def ac_tp4(page, base):
    """On #property?p=… the [data-export=property] download starts property_label;lat;lon;level;
    code; and every row has a non-empty source (spec §5.5′)."""
    goto(page, "property?p=55.6545,12.539:Test&ind=growth", settle=2400, wait="#anmap .leaflet-pane")
    # two files: the pin's figures now, and what lies near it once the lazy layers have landed
    got = []
    page.on("download", lambda d: got.append(d))
    open_export(page)
    page.locator("[data-export=property]").first.click()
    for _ in range(80):
        page.wait_for_timeout(250)
        if len(got) >= 2:
            break
    assert got, "[data-export=property] downloaded nothing"
    main_dl = next(d for d in got if "nearby" not in d.suggested_filename)
    name = main_dl.suggested_filename
    raw = pathlib.Path(main_dl.path()).read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", f"{name} does not start with a UTF-8 BOM"
    lines = [ln for ln in raw.decode("utf-8-sig").split("\n") if ln.strip()]
    assert name.startswith("test_property_"), name
    assert lines[0].startswith("property_label;lat;lon;level;code;"), lines[0][:80]
    assert lines[0] == "property_label;lat;lon;" + LONG_HEADER, lines[0]
    head, rows = csv_rows(lines)
    assert len(rows) > 50, f"only {len(rows)} row(s) for a Copenhagen pin"
    for r in rows:
        assert (r["source"] or "").strip(), f"blank source: {r}"
        assert (r["as_of"] or "").strip(), f"blank as_of: {r}"
        assert r["property_label"] == "Test", r["property_label"]
        assert r["lat"] == "55.6545" and r["lon"] == "12.539", (r["lat"], r["lon"])
    levels = {r["level"] for r in rows}
    assert levels == {"municipality", "postal_code", "copenhagen_quarter"}, levels
    # the quarter and the postal code read the municipality's figures as inherited
    inh = [r for r in rows if r["value_type"] == "inherited"]
    assert inh and all(r["inherited_from"] for r in inh)
    # and the second file: what lies near the pin, one row per feature, each with its source
    near = next((d for d in got if "nearby" in d.suggested_filename), None)
    assert near is not None, f"no test_property_nearby file, only {[d.suggested_filename for d in got]}"
    lines2 = [ln for ln in pathlib.Path(near.path()).read_bytes().decode("utf-8-sig").split("\n") if ln.strip()]
    assert lines2[0] == "kind;name;type;status;distance_m;source;source_url", lines2[0]
    kinds = {ln.split(";")[0] for ln in lines2[1:]}
    assert "infra" in kinds, kinds
    for ln in lines2[1:]:
        c = ln.split(";")
        assert c[5].strip(), f"a nearby row without a source: {ln}"


@ac("AC-XMENU", phase="P7")
def ac_xmenu(page, base):
    """P7-local: one menu, three places to open it from, one open at a time; Esc closes it; the
    v2.6 single-CSV sidebar button and its four-line explanation are gone; and Data › Sources shows
    exactly the rows the Sources catalogue file writes (P7 item 3)."""
    # 1. the sidebar footer has the menu and the build line on every route, and nothing else
    goto(page, "map?ind=growth", settle=600)
    assert page.locator("[data-xall]").count() == 0, "the v2.6 single-CSV export button is still there"
    foot = (page.locator("#xfoot").inner_text() or "")
    assert "Everything in one CSV" not in foot, "the four-line sidebar explanation is still there"
    assert page.evaluate("(D.meta && D.meta.built) || ''") in foot, f"the footer does not name the build: {foot!r}"
    assert page.locator("#xfoot [data-testid=export-btn]").count() == 1
    # 2. Esc closes it and hands focus back to the trigger
    open_export(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert not page.locator("[data-testid=export-menu]").first.is_visible(), "Escape did not close the menu"
    assert page.evaluate("document.activeElement === document.querySelector('#xfoot [data-testid=export-btn]')"), \
        "Escape did not return focus to the Export ▾ button"
    # 3. the Data header and the test-property header carry the same menu, and only one opens
    goto(page, "data/areas/kommune?ind=growth", settle=700)
    assert page.locator(".hd-act [data-testid=export-btn]").count() == 1, "no Export ▾ in the Data header"
    page.locator(".hd-act [data-testid=export-btn]").click()
    page.wait_for_timeout(250)
    vis = page.eval_on_selector_all("[data-testid=export-menu]", "els => els.filter(e => !e.hidden).length")
    assert vis == 1, f"{vis} menus open at once — one trigger, one menu"
    # 4. Sources: the table and the file are the same catalogue
    goto(page, "data/sources", settle=800)
    shown = page.locator("[data-testid=sources-table] tbody tr").count()
    name, lines = export_csv(page, "sources")
    assert name.startswith("sources_"), name
    assert lines[0] == "key;label;publisher;tables;as_of;fetched;url;licence;used_for", lines[0]
    assert len(lines) - 1 == shown, f"the table shows {shown} sources, the file writes {len(lines) - 1}"
    head, rows = csv_rows(lines)
    for r in rows:
        assert (r["publisher"] or "").strip() and (r["fetched"] or "").strip(), f"blank publisher or fetched: {r}"
    # 5. the other two files exist and carry their sources
    _, nat = export_csv(page, "national")
    assert nat[0] == LONG_HEADER, nat[0]
    nhead, nrows = csv_rows(nat)
    assert {r["period_type"] for r in nrows} <= {"month", "quarter", "year"}, {r["period_type"] for r in nrows}
    for r in nrows[:200]:
        assert (r["source"] or "").strip() and (r["as_of"] or "").strip()
    _, clim = export_csv(page, "climate")
    assert clim[0].startswith("level;code;name;parent_code;parent_name;horizon;zone_year;dwellings;"), clim[0]
    chead, crows = csv_rows(clim)
    assert {r["horizon"] for r in crows} == {"today", "2070", "2120"}, {r["horizon"] for r in crows}
    for r in crows:
        assert (r["source"] or "").strip() and (r["as_of"] or "").strip(), f"blank source: {r}"
        assert r["value_type"] in ("derived", "projection"), r["value_type"]


# =============================================================================================
# P8 — the responsive shell, the sheets, the number rules and accessibility
#      (spec §4.1, §6, §2.4, §5.7, §4.10, §7)
# =============================================================================================

# Every MUST route, as AC-R1 and AC-G1 read them (Compare is deleted — amendment A1 — and
# #properties is the single-pin #property — amendment A2).
MUST_ROUTES = [
    "map?ind=growth",
    "area/kommune/101?ind=growth",
    "area/postnr/2450?ind=growth",
    "data/areas/kommune?ind=growth",
    "data/projects",
    "data/national",
    "data/sources",
    "charts?ind=growth&a=kommune:101",
    "property?p=55.6545,12.539",
]

# The one expression that decides "this page scrolls sideways", shared with tests/ui_smoke.py so a
# regression cannot pass one runner and fail the other.
from ui_smoke import OVERFLOW_JS  # noqa: E402


@ac("AC-S1", phase="P8", viewport="390x844")
def ac_s1(page, base):
    """At 390×844 the sidebar is gone, the 52 px bar is there, the page does not scroll sideways
    and the map still fills the column."""
    goto(page, "map?ind=growth", settle=900, wait="#lfmap .leaflet-pane")
    assert not page.locator("[data-testid=sidebar]").is_visible(), "the sidebar is still visible at 390 px"
    assert page.locator("[data-testid=topbar-mobile]").is_visible(), "no 52 px top bar at 390 px"
    sw = page.evaluate("document.body.scrollWidth")
    assert sw <= 390, f"document.body.scrollWidth is {sw}, the viewport is 390"
    box = page.locator("[data-testid=map]").bounding_box()
    assert box and box["width"] >= 350, f"the map is {box and box['width']} px wide"
    assert box["x"] >= -1 and box["x"] + box["width"] <= 391, f"the map sticks out: {box}"
    bar = page.locator("[data-testid=topbar-mobile]").bounding_box()
    assert 48 <= bar["height"] <= 56, f"the mobile bar is {bar['height']} px tall, spec says 52"
    # the card clips (`overflow-x:clip`), so a control wider than its column never reaches the
    # page-level overflow check — it just loses its right-hand end. Check it here instead.
    # A row that scrolls sideways on purpose (the chips, the level segments) is exempt: its
    # children are *supposed* to run past the card, that is what makes them reachable.
    over = page.evaluate("""(() => {
      const card = document.getElementById('mapcard'); if (!card) return 'no #mapcard';
      const c = card.getBoundingClientRect(), out = [];
      const scrolls = e => { for (let p = e.parentElement; p && p !== card; p = p.parentElement) {
        if (/auto|scroll/.test(getComputedStyle(p).overflowX)) return true; } return false; };
      for (const e of card.querySelectorAll('[data-testid=map-toolbar] *, #mkexplain *')) {
        const r = e.getBoundingClientRect();
        if (r.width > 0 && r.right > c.right - 1 && !scrolls(e)) {
          out.push((e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className
            ? '.' + e.className.trim().split(/\\s+/).join('.') : '')).slice(0, 40)
            + ' ' + Math.round(r.left) + '..' + Math.round(r.right) + ' of ' + Math.round(c.right));
        }
      }
      return out.slice(0, 4).join(' · ');
    })()""")
    assert not over, f"a toolbar control runs past the map card: {over}"


@ac("AC-S2", phase="P8", viewport="390x844")
def ac_s2(page, base):
    """☰ opens the drawer, Escape closes it, focus goes back to the toggle — and while it is open
    Tab stays inside it."""
    goto(page, "map?ind=growth", settle=700)
    tog = page.locator("[data-testid=nav-toggle]")
    assert tog.get_attribute("aria-expanded") == "false", "the toggle does not start collapsed"
    assert not page.locator("[data-testid=nav-drawer]").is_visible(), "the drawer starts open"
    tog.click()
    page.wait_for_timeout(350)
    assert page.locator("[data-testid=nav-drawer]").is_visible(), "☰ did not open the drawer"
    assert page.locator("[data-testid=sidebar]").is_visible(), "the drawer is open but its panel is not"
    assert tog.get_attribute("aria-expanded") == "true", "aria-expanded did not follow the drawer"
    assert page.evaluate("document.querySelector('[data-testid=nav-drawer]').contains(document.activeElement)"), \
        "focus did not move into the drawer"
    # the trap: Tab twenty times and focus is still inside
    for _ in range(20):
        page.keyboard.press("Tab")
    assert page.evaluate("document.querySelector('[data-testid=nav-drawer]').contains(document.activeElement)"), \
        "Tab escaped the open drawer"
    page.keyboard.press("Escape")
    page.wait_for_timeout(350)
    assert not page.locator("[data-testid=nav-drawer]").is_visible(), "Escape did not close the drawer"
    assert page.evaluate("document.activeElement === document.querySelector('[data-testid=nav-toggle]')"), \
        "focus did not return to ☰"


@ac("AC-R1", phase="P8")
def ac_r1(page, base):
    """No route makes the document wider than the viewport at 1366×768, 1536×864, 1440×900 or
    390×844, and none of them throws."""
    bad = []
    try:
        for w, h in [(1366, 768), (1536, 864), (1440, 900), (390, 844)]:
            page.set_viewport_size({"width": w, "height": h})
            for r in MUST_ROUTES:
                goto(page, r, settle=900)
                over = page.evaluate(OVERFLOW_JS)
                if over:
                    bad.append(f"{w}x{h} {r}: {over}")
    finally:
        page.set_viewport_size({"width": 1440, "height": 900})
    assert not bad, "horizontal overflow — " + " | ".join(bad[:6])
    assert not ERRORS, f"pageerror(s) while walking the routes: {ERRORS[:3]}"


@ac("AC-SH1", phase="P8")
def ac_sh1(page, base):
    """The four detail sheets render a §4.7 tile row and no empty grey filler tile."""
    pid = page.evaluate("(INFRA_ALL[0] || {properties:{id:''}}).properties.id")
    bid = page.evaluate("""(() => { const f = PUB_FILES['101']; if (!f) return '';
        const b = (f.buildings || [])[0]; return b ? String(b.id) : ''; })()""")
    if not bid:
        page.evaluate("pubLoad('101')")
        page.wait_for_timeout(1500)
        bid = page.evaluate("""(() => { const f = PUB_FILES['101'];
            const b = f && (f.buildings || [])[0]; return b ? String(b.id) : ''; })()""")
    assert bid, "no public building loaded for København — cannot check the sheet"
    nr = page.evaluate("Object.keys(SCH_BY || {})[0] || ''")
    routes = [f"project/{pid}", f"public/101/{bid}", "climate/0101"] + ([f"school/{nr}"] if nr else [])
    for r in routes:
        goto(page, r, settle=1400)
        n = page.locator("[data-testid=tiles]").count()
        assert n == 1, f"{r}: {n} tile rows, expected exactly one (spec §5.7)"
        cells = page.eval_on_selector_all("[data-testid=tiles] > *",
                                          "els => els.map(e => (e.textContent || '').trim())")
        assert cells, f"{r}: the tile row is empty"
        assert all(c for c in cells), f"{r}: an empty filler tile is still rendered — {cells}"
        assert page.locator(".tile.empty, .hlc:empty, .hltile:empty").count() == 0, f"{r}: empty tile element"


@ac("AC-SH2", phase="P8")
def ac_sh2(page, base):
    """The climate sheet uses the shared PeriodControl, and "Show the zones on the map" lands on
    the municipality's map with the surge indicator at the horizon that was showing."""
    goto(page, "climate/0101?hz=2070", settle=1600)
    assert page.locator("[data-testid=period][data-mode=horizon]").count() == 1, \
        "the climate sheet does not render the shared PeriodControl"
    assert page.locator("[data-testid=period-hz]").count() == 1, "no horizon segments on the climate sheet"
    btn = page.get_by_role("button", name=re.compile("Show the zones on the map"))
    assert btn.count() == 1, "no 'Show the zones on the map' button"
    btn.first.click()
    page.wait_for_timeout(900)
    h = cur_hash(page)
    assert h.startswith("map/101"), f"landed on {h!r}, expected a hash starting map/101"
    assert "ind=surge_dw_pct" in h, f"the surge indicator is not in {h!r}"
    assert "hz=2070" in h, f"the horizon did not travel with the link: {h!r}"
    assert page.locator("[data-testid=legend-zones]").count() == 1, "the zones are not on the map"


@ac("AC-A1", phase="P8")
def ac_a1(page, base):
    """Offline stand-in for axe-core (no network installs during the run, and
    src/vendor/axe.min.js is not in the repo): every visible control has an accessible name, every
    popover trigger carries aria-expanded, and no icon is a bare glyph without a text alternative."""
    js = """(() => {
      const bad = [];
      const vis = e => { const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
      const id = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
        (e.getAttribute('data-testid') ? '[' + e.getAttribute('data-testid') + ']' : '') +
        (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/)[0] : '');
      const name = e => {
        const lb = e.getAttribute('aria-labelledby');
        const byId = lb && lb.split(/\\s+/).map(i => (document.getElementById(i) || {}).textContent || '').join(' ');
        return (e.getAttribute('aria-label') || byId || e.title ||
                (e.labels && e.labels.length ? [...e.labels].map(l => l.textContent).join(' ') : '') ||
                e.placeholder || e.textContent || e.value || '').trim();
      };
      for (const e of document.querySelectorAll('button,input,select,textarea,a[href],[role=button]')) {
        if (!vis(e) || e.disabled) continue;
        if (e.closest('.leaflet-container')) continue;      /* Leaflet's own controls */
        if (!name(e)) bad.push('no accessible name: ' + id(e));
      }
      for (const e of document.querySelectorAll('[aria-haspopup],[aria-controls]')) {
        if (!vis(e) || e.tagName === 'DIV') continue;
        if (!e.hasAttribute('aria-expanded')) bad.push('no aria-expanded: ' + id(e));
      }
      for (const e of document.querySelectorAll('img')) {
        if (!vis(e)) continue;
        if (e.alt == null || (!e.alt && e.getAttribute('alt') === null)) bad.push('img without alt: ' + id(e));
      }
      for (const e of document.querySelectorAll('svg[role=img]')) {
        if (vis(e) && !e.querySelector('title') && !e.getAttribute('aria-label')) bad.push('svg role=img without a title: ' + id(e));
      }
      return bad;
    })()"""
    triggers = ["[data-testid=ind-picker-btn]", "[data-testid=layers-btn]", "[data-testid=export-btn]"]
    for r in ["map?ind=growth", "area/kommune/101?ind=growth", "data/areas/kommune?ind=growth",
              "property?p=55.6545,12.539"]:
        goto(page, r, settle=1400)
        bad = page.evaluate(js)
        assert not bad, f"{r}: {bad[:6]}"
        for t in triggers:
            if page.locator(t).count():
                got = page.eval_on_selector_all(t, "els => els.map(e => e.getAttribute('aria-expanded'))")
                assert all(v in ("true", "false") for v in got), f"{r}: {t} aria-expanded = {got}"


@ac("AC-A2", phase="P8")
def ac_a2(page, base):
    """Tab from the page start reaches the indicator picker within 12 tabs on #map; Enter opens the
    popover and Escape closes it again."""
    goto(page, "map?ind=growth", settle=900)
    page.evaluate("document.body.focus(); if (document.activeElement) document.activeElement.blur();")
    seen = []
    for n in range(12):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("""(() => { const e = document.activeElement; if (!e) return '';
            return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
              (e.getAttribute('data-testid') ? '[' + e.getAttribute('data-testid') + ']' : '') +
              (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).join('.') : ''); })()"""))
        if page.evaluate("document.activeElement === document.querySelector('[data-testid=ind-picker-btn]')"):
            break
    else:
        raise AssertionError(f"the picker was not reached in 12 tabs — the path was {seen}")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.locator("[data-testid=ind-picker-pop]").is_visible(), "Enter did not open the picker"
    assert page.locator("[data-testid=ind-picker-btn]").get_attribute("aria-expanded") == "true"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not page.locator("[data-testid=ind-picker-pop]").is_visible(), "Escape did not close the picker"
    assert page.evaluate("document.activeElement === document.querySelector('[data-testid=ind-picker-btn]')"), \
        "Escape did not hand focus back to the picker button"


G1_RX = re.compile(r"\b(score|weighted|index of)\b", re.I)


# The UI's own vocabulary: what the app writes rather than what a publisher wrote. Everything here
# is chrome — if one of the G1 words turns up in it, the dashboard has invented a score or a weight.
G1_CHROME = ("button, h1, h2, h3, h4, th, .tl, .tag, .lgtitle, .pk, .chip, .dtab, .segl, .sg, "
             "[data-testid=nav-item], [data-testid=ind-picker-btn], .panel-hd, .inhlab, .xitem b")


@ac("AC-G1", phase="P8")
def ac_g1(page, base):
    """No score, no weighting, no "index of" anywhere the dashboard speaks for itself — and every
    remaining occurrence is the publisher's own prose, verbatim out of the built data.

    Checked in two halves, because the data is out of this run's reach and must be: (1) no control,
    heading, table header, tile label, tag, chip or legend title matches the phrase; (2) any visible
    text that does match is a substring of the built registry — so the app never wrote it, it only
    quoted a publisher ("pupil-weighted", which is how Uddannelsesstatistik publishes the FP9 grade,
    and "…score high", a verb in two DST indicator descriptions). See docs/v3/DECISIONS.md."""
    js = """(() => {
      const out = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const p = n.parentElement;
        if (!p || p.closest('script,style,title')) continue;
        const r = p.getBoundingClientRect();
        if (r.width < 1 && r.height < 1) continue;
        if (getComputedStyle(p).visibility === 'hidden') continue;
        const t = (n.nodeValue || '').trim();
        if (t) out.push(t);
      }
      return out;
    })()"""
    chrome_js = ("sel => [...document.querySelectorAll(sel)]"
                 ".filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })"
                 ".map(e => (e.textContent || '').trim())")
    hits, quoted = [], []
    for r in MUST_ROUTES:
        goto(page, r, settle=900)
        for t in page.evaluate(chrome_js, G1_CHROME):
            if G1_RX.search(t):
                hits.append(f"{r}: chrome says {t[:90]!r}")
        for t in page.evaluate(js):
            if G1_RX.search(t):
                quoted.append((r, t))
    assert not hits, "the dashboard's own words say score / weighted / index of — " + " | ".join(hits[:6])
    if quoted:
        blob = page.evaluate("JSON.stringify(D)")
        strayed = [f"{r}: {t[:90]!r}" for r, t in quoted if t not in blob]
        assert not strayed, ("text the app wrote itself says score / weighted / index of — "
                             + " | ".join(strayed[:6]))


# =============================================================================================
# P9 — final QA: the defects the fresh-eyes pass found, each one pinned so it cannot come back
# =============================================================================================
@ac("AC-Q1", phase="P9")
def ac_q1(page, base):
    """A legend never sits on top of the map's attribution. The OpenStreetMap / DAGI credit is a
    licence condition and it lives in the same bottom-right corner as the legend stack, so the two
    boxes must not intersect — on the macro map or on a mini map with tiles under it."""
    for route, stack in [("map?ind=growth", "#maplegs"),
                         ("property?p=55.6545,12.539", ".minimap .maplegs")]:
        goto(page, route, settle=1600, wait=".leaflet-container")
        page.wait_for_timeout(700)
        legs = rects(page, stack + " .maplegend")
        attr = rects(page, ".leaflet-control-attribution")
        assert legs, f"{route}: no legend card inside {stack}"
        if not attr:
            continue                                    # a map with no tile layer credits nobody
        a = attr[0]
        for lg in legs:
            overlap = (min(lg["right"], a["right"]) - max(lg["x"], a["x"]) > 1
                       and min(lg["bottom"], a["bottom"]) - max(lg["y"], a["y"]) > 1)
            assert not overlap, (f"{route}: the legend {lg['id']!r} covers the map attribution "
                                 f"(legend {lg['y']:.0f}–{lg['bottom']:.0f}, attribution "
                                 f"{a['y']:.0f}–{a['bottom']:.0f})")


@ac("AC-Q2", phase="P9", viewport="1536x864")
def ac_q2(page, base):
    """The test-property header is one column at every width. `.tpnote` above the identity block is
    capped at 760 px, so a narrow flex basis on the identity block let the two share a line from
    ~1500 px up: the title floated to the right of the privacy sentence, away from its own action
    row, with a hole between them. Title, actions and tiles all start at the same x."""
    goto(page, "property?p=55.6545,12.539", settle=1800, wait="[data-testid=tiles]")
    page.wait_for_timeout(500)
    lefts = {}
    for name, sel in [("title", ".anhead .arid"), ("actions", ".anhead .arid ~ .tools"),
                      ("tiles", ".anhead [data-testid=tiles]")]:
        b = page.locator(sel).first.bounding_box()
        assert b, f"no {name} block in the test-property header ({sel})"
        lefts[name] = b["x"]
    spread = max(lefts.values()) - min(lefts.values())
    assert spread <= 2, f"the header is not one column — left edges {lefts}"
    card = box_of(page, ".anhead")
    idb = box_of(page, ".anhead .arid")
    assert idb["width"] >= card["width"] * .8, (
        f"the identity block takes {idb['width']:.0f} of {card['width']:.0f} px — it is sharing its "
        "line with the privacy note again")


@ac("AC-Q3", phase="P9", viewport="390x844")
def ac_q3(page, base):
    """No tile row leaves a bare grid cell showing the separator colour through. The 1 px gaps are
    the card's background, so an unfilled cell reads as a grey slab — P8 fixed that for the five
    headline tiles and this extends it to `.tiles.wrap` (the sheet and Population-outlook rows),
    which is `auto-fit` and leaves a hole whenever an odd last tile lands in a two-column row."""
    for route, opener in [("area/kommune/101?ind=growth&show=outlook", None),
                          ("climate/0167?hz=2070", None),
                          ("project/m5-phase-1", None)]:
        goto(page, route, settle=1800, wait="[data-testid=tiles]")
        if opener:
            page.click(opener)
            page.wait_for_timeout(300)
        page.wait_for_timeout(400)
        bad = page.evaluate("""() => {
          const out = [];
          for (const g of document.querySelectorAll('.tiles')) {
            const r = g.getBoundingClientRect();
            if (r.width < 1) continue;
            const kids = [...g.children].filter(e => e.getClientRects().length > 0);
            if (!kids.length) continue;
            const last = kids[kids.length - 1].getBoundingClientRect();
            /* the last tile must either share its row with a tile to its right, or reach the end */
            const sameRow = kids.some(e => e !== kids[kids.length - 1] &&
              Math.abs(e.getBoundingClientRect().top - last.top) < 2 &&
              e.getBoundingClientRect().left > last.left);
            if (!sameRow && last.right < r.right - 2)
              out.push(`${g.dataset.testid || g.className} last tile ends at ${Math.round(last.right)} of ${Math.round(r.right)}`);
          }
          return out;
        }""")
        assert not bad, f"{route}: a tile row has an empty cell — " + " | ".join(bad)


@ac("AC-Q4", phase="P9")
def ac_q4(page, base):
    """An inherited figure is marked the same way on every row-per-indicator table: `.inh` on the
    row and a `muni` tag that says whose figure it is (spec §4.8, §2.4 "never a lone °"). The test
    property's Area profile still used the v2.6 ° while the area page's All figures used the tag.

    The pin is in Aarhus, so its finest published area is a postal code and the municipality-level
    indicators (unemployment, tenure, crime) are read down onto it — a Copenhagen quarter publishes
    its own figure for nearly everything and would have nothing inherited to check."""
    goto(page, "property?p=56.15700,10.21000&show=profile", settle=2600, wait="[data-testid=tp-sec-profile]")
    page.wait_for_timeout(900)
    rows = page.evaluate("""() => {
      const t = document.querySelector('[data-testid=tp-sec-profile] table');
      if (!t) return null;
      return [...t.querySelectorAll('tbody tr')].map(tr => ({
        inh: tr.classList.contains('inh'),
        tag: !!tr.querySelector('.tag-muni'),
        val: (tr.querySelector('td.num') || {}).textContent || '' }));
    }""")
    assert rows, "no Area profile table on the test property"
    assert any(r["inh"] for r in rows), "no inherited row on a Copenhagen quarter's Area profile"
    for r in rows:
        assert r["inh"] == r["tag"], f"an inherited row without its muni tag (or the reverse): {r}"
        assert "°" not in r["val"], f"a value cell still carries a bare ° : {r['val']!r}"


@ac("AC-Q5", phase="P9")
def ac_q5(page, base):
    """No double-escaped HTML entity reaches the reader. `Sources &amp; as of` shipped as the test
    property's last section heading because the label was escaped twice; one grep over the visible
    text of every MUST route is cheaper than remembering not to do it again."""
    rx = re.compile(r"&(amp|lt|gt|quot|#\d+);")
    js = """(() => {
      const out = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const p = n.parentElement;
        if (!p || p.closest('script,style,title')) continue;
        const r = p.getBoundingClientRect();
        if (r.width < 1 && r.height < 1) continue;
        const t = (n.nodeValue || '').trim();
        if (t) out.push(t);
      }
      return out;
    })()"""
    hits = []
    for route in MUST_ROUTES + ["climate/0167", "project/m5-phase-1", "property?p=55.6545,12.539&show=sources"]:
        goto(page, route, settle=1200)
        for t in page.evaluate(js):
            if rx.search(t):
                hits.append(f"{route}: {t[:90]!r}")
    assert not hits, "escaped HTML shown as text — " + " | ".join(hits[:6])


@ac("AC-Q6", phase="P9", viewport="390x844")
def ac_q6(page, base):
    """A chip never breaks its own label in two. The chips row scrolls sideways below 1025 px, so a
    wrapping chip ("Rent (priv.)") made the row ragged and broke the 24 px chip height of §2.2."""
    for route in ["map?ind=growth", "area/kommune/101?ind=growth",
                  "data/areas/kommune?ind=growth", "charts?ind=growth&a=kommune:101"]:
        goto(page, route, settle=1200, wait="[data-testid=ind-chips]")
        tall = page.evaluate("""() => [...document.querySelectorAll('[data-testid=ind-chips] .chip')]
          .filter(c => c.getClientRects().length > 1 || c.getBoundingClientRect().height > 30)
          .map(c => `${(c.textContent || '').trim()} ${Math.round(c.getBoundingClientRect().height)}px`)""")
        assert not tall, f"{route}: a chip wrapped onto two lines — " + " | ".join(tall)


# =============================================================================================
# P10 — the owner's review: the pin stays on the map, services and every switch on the test
#       property, and the pin's full indicator list (docs/v3/phases/P10.md)
# =============================================================================================
TP10 = "property?p=55.69711,12.58399"       # the owner's pin: Østerport, 2100 København Ø


def open_layers(page):
    """Open Layers ▾ if it is not already open — the trigger toggles, so never click it twice."""
    pop = page.locator("[data-testid=layers-pop]").first
    if not pop.is_visible():
        page.locator("[data-testid=layers-btn]").first.click()
        page.wait_for_timeout(300)
    assert pop.is_visible(), "clicking Layers ▾ did not open [data-testid=layers-pop]"
    return pop


def mm_legend(page, kind):
    """The state of one legend card inside the mini map: visible / hidden / missing."""
    return page.evaluate("""k => { const z = document.querySelector(
        `[data-testid=minimap] [data-testid=legend-${k}]`);
      return z ? (getComputedStyle(z).display === 'none' ? 'hidden' : 'visible') : 'missing'; }""", kind)


@ac("AC-TP7", phase="P10")
def ac_tp7(page, base):
    """Services are a layer of the test-property map too — the same four categories, the same
    filters, drawn around the pin with a legend of their own (P10 item 2). `lay=services` on the
    property route switches them on, and switching them off removes markers and legend at once."""
    goto(page, TP10 + "&lay=services", settle=3200, wait="#anmap .leaflet-pane")
    del ERRORS[:]
    box = open_layers(page).locator("[data-layer=services]")
    assert box.count() == 1, "the test property's Layers ▾ has no Services row"
    assert box.first.get_attribute("aria-checked") == "true", "lay=services did not tick the row"
    assert mm_legend(page, "services") == "visible", "no services legend inside the mini map"
    drawn = page.evaluate("""() => { let n = 0; ["anSrvG", "anSrvStG"].forEach(k =>
        { if (LF[k]) LF[k].eachLayer(() => n++); }); return n; }""")
    assert drawn > 0, "the services layer is on but nothing was drawn around the pin"
    # the filters of Layers ▾ reach this map too
    assert page.locator("[data-testid=layers-pop] [data-srvcat]").count() >= 4, \
        "the Services row offers no category filters"
    # off → no markers, no legend, and the hash says so
    page.click("[data-layer=services]")
    page.wait_for_timeout(900)
    assert page.evaluate("""() => { let n = 0; ["anSrvG", "anSrvStG"].forEach(k =>
        { if (LF[k]) LF[k].eachLayer(() => n++); }); return n; }""") == 0, "service markers survived the switch"
    assert mm_legend(page, "services") == "hidden", "the services legend survived the switch"
    assert "services" not in cur_hash(page).split("lay=")[1].split("&")[0], \
        f"lay= still names services: {cur_hash(page)!r}"
    assert not ERRORS, f"pageerror on the services layer: {ERRORS[:2]}"


@ac("AC-TP8", phase="P10")
def ac_tp8(page, base):
    """Every layer the test-property map draws has exactly one switch in Layers ▾, switching it off
    removes its markers *and* its legend at once, and the state survives a reload (P10 item 3)."""
    goto(page, TP10, settle=2800, wait="#anmap .leaflet-pane")
    del ERRORS[:]
    pop = open_layers(page)
    rows = page.evaluate("""() => [...document.querySelectorAll('[data-testid=layers-pop] [data-layer]')]
        .map(b => b.dataset.layer)""")
    assert len(rows) == len(set(rows)), f"a layer has two switches: {rows}"
    for k in ["infra", "public", "services", "buildings", "rings"]:
        assert k in rows, f"no switch for the {k} layer: {rows}"
    # Public buildings: drawn, then switched off
    assert page.evaluate("ANL.pub") is True and mm_legend(page, "public") == "visible"
    assert page.evaluate("""() => { let n = 0; LF.anmap.eachLayer(l => { if (l._pub) n++; }); return n; }""") > 0, \
        "the public layer is on but no building was drawn"
    pop.locator("[data-layer=public]").click()
    page.wait_for_timeout(1000)
    left = page.evaluate("""() => ({
        markers: (() => { let n = 0; LF.anmap.eachLayer(l => { if (l._pub) n++; }); return n; })(),
        icons: document.querySelectorAll('[data-testid=minimap] .leaflet-marker-icon.pub-marker').length })""")
    assert left["markers"] == 0 and left["icons"] == 0, f"public buildings survived the switch: {left}"
    assert mm_legend(page, "public") == "hidden", "the Public buildings legend survived the switch"
    # …and it stays off after an async file load and after a reload of the resulting hash
    page.wait_for_timeout(2000)
    assert page.evaluate("""() => { let n = 0; LF.anmap.eachLayer(l => { if (l._pub) n++; }); return n; }""") == 0, \
        "a late public/<kom>.json put the layer back"
    h = cur_hash(page)
    page.goto(base + "#" + h, wait_until="load")
    page.wait_for_function("typeof render === 'function' && IND.length > 0", timeout=60000)
    page.wait_for_timeout(2600)
    assert page.evaluate("ANL.pub") is False, f"the reloaded link turned the layer back on: {h!r}"
    assert mm_legend(page, "public") == "hidden", "the legend came back on reload"
    # the rings are a layer of their own, and the pin itself is never switched off
    open_layers(page).locator("[data-layer=rings]").click()
    page.wait_for_timeout(800)
    assert "rings=0" in cur_hash(page), f"the rings switch did not reach the hash: {cur_hash(page)!r}"
    assert page.evaluate("""() => { let n = 0; if (LF.anPinG) LF.anPinG.eachLayer(() => n++); return n; }""") == 1, \
        "switching the rings off left something other than the pin behind"
    assert not ERRORS, f"pageerror while switching layers: {ERRORS[:2]}"


@ac("AC-TP9", phase="P10")
def ac_tp9(page, base):
    """A pin is read against every level it sits in: the picker offers the quarter's own figures
    first and then what the postal code and the municipality publish — Climate included, with the
    horizon control and the zones in the mini map (P10 item 4, spec §4.2 AC-I5)."""
    goto(page, TP10, settle=2800, wait="#anmap .leaflet-pane")
    del ERRORS[:]
    page.click("[data-testid=ind-picker-btn]")
    page.wait_for_timeout(400)
    rows = page.locator("[data-testid=ind-picker-pop] [data-ind]").count()
    assert rows >= 55, f"the picker offers {rows} indicators on a Copenhagen pin — the pin's own level only?"
    groups = page.evaluate("""() => [...document.querySelectorAll('[data-testid=ind-picker-pop] [data-group]')]
        .map(g => g.dataset.group)""")
    assert "Climate" in groups, f"no Climate group on the test property: {groups}"
    assert "From the municipality" in groups, f"nothing is marked as inherited: {groups}"
    # an inherited row says where its figure comes from
    tags = page.evaluate("""() => [...document.querySelectorAll('[data-group="From the municipality"] .indrow')]
        .map(r => ({ key: r.dataset.ind, tag: !!r.querySelector('.tag-muni') }))""")
    assert tags and all(t["tag"] for t in tags), f"an inherited row carries no muni tag: {tags[:3]}"
    page.keyboard.press("Escape")
    # …and choosing a Climate indicator brings the horizon control, the bars and the zones
    goto(page, TP10 + "&ind=surge_dw_pct", settle=3200, wait="#anmap .leaflet-pane")
    assert page.locator("[data-testid=period-hz]").count() >= 1, "no horizon control for a Climate indicator"
    assert page.locator("[data-testid=chart-panel] [data-testid=clim-bars]").count() == 1, \
        "the chart panel does not draw the three horizons"
    assert mm_legend(page, "zones") == "visible", "the storm-surge zones are not in the mini map's legend stack"
    assert not ERRORS, f"pageerror reading a Climate indicator on the test property: {ERRORS[:2]}"


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
            # accept_downloads: the export ACs read the files the menu writes (P7)
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                      accept_downloads=True)
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
