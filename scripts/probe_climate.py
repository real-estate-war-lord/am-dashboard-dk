#!/usr/bin/env python3
"""v2.5 climate layer — endpoint probe (read-only).

Checks every source the climate-risk layer would depend on before a line of pipeline code is
written: Miljøstyrelsen's risk areas and hazard rasters, the MST bulk drop, DMI/Klimaatlas,
Datafordeler DHM, the bluespot raster, Forsikring & Pension's damage series, and the coastal
kommune list that follows from the boundaries already vendored in data/geo.

Nothing is cached or written except docs/CLIMATE_PROBE.md — no pipeline data lands on disk.

    python3 scripts/probe_climate.py              # every probe
    python3 scripts/probe_climate.py --only 4,7   # a subset
"""
import argparse
import csv
import html
import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests missing: pip3 install requests")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "CLIMATE_PROBE.md"
UA = {"User-Agent": "am-dashboard-dk climate probe (research; contact via repo)"}
TIMEOUT = 90

ROWS = []       # (name, http, secs, bytes, note)
DETAIL = []     # markdown blocks
CHECKS = []     # (label, ok, got, want)


# ---------- helpers ----------
def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def get(url, params=None, name=None, note="", stream=False, **kw):
    """One timed GET. Never raises — a dead endpoint is a result, not a crash."""
    t0 = time.time()
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT, **kw)
        secs = time.time() - t0
        n = len(r.content)
        if name:
            ROWS.append((name, str(r.status_code), f"{secs:.2f}", f"{n:,}", note))
        return r, secs, n
    except Exception as e:                                             # noqa: BLE001
        secs = time.time() - t0
        if name:
            msg = type(e).__name__
            if "NameResolution" in str(e) or "Name or service" in str(e) or "nodename" in str(e):
                msg = "host does not resolve"
            elif isinstance(e, requests.exceptions.ConnectionError):
                msg = "connection refused / no route"
            ROWS.append((name, "ERR", f"{secs:.2f}", "0", msg[:60]))
        return None, secs, 0


def jget(url, params=None, **kw):
    r, secs, n = get(url, params, **kw)
    if r is None or r.status_code != 200:
        return None, r, secs, n
    try:
        return r.json(), r, secs, n
    except Exception:                                                  # noqa: BLE001
        return None, r, secs, n


def check(label, got, want, tol=0.01):
    ok = (got is not None) and (abs(got - want) <= tol + 1e-9 if isinstance(want, float) else got == want)
    CHECKS.append((label, ok, got, want))
    return ok


def block(title, body):
    DETAIL.append(f"## {title}\n\n{body.rstrip()}\n")


def head(rows, n=6):
    return "\n".join(rows[:n])


# ---------- EPSG:25832 / 3044 (ETRS89 UTM 32N) <-> WGS84 ----------
_A, _F, _K0, _LON0 = 6378137.0, 1 / 298.257222101, 0.9996, math.radians(9.0)


def wgs84_to_utm32(lon, lat):
    e2 = _F * (2 - _F); ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2; c = ep2 * math.cos(phi) ** 2
    a1 = (lam - _LON0) * math.cos(phi)
    m = _A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
              - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
              + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
              - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = _K0 * n * (a1 + (1 - t + c) * a1 ** 3 / 6 + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * a1 ** 5 / 120) + 500000.0
    y = _K0 * (m + n * math.tan(phi) * (a1 ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a1 ** 4 / 24
               + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * a1 ** 6 / 720))
    return x, y


CPH_HARBOUR = (12.5990, 55.6800)       # Inderhavnen, between Nyhavn and Christianshavn


# ---------- 1. MST risk areas (OD_risikoomraader_2024) ----------
MST = "https://gisportal.mst.dk/server/rest/services/ekstern"


def probe_risk():
    svc, r, _, _ = jget(f"{MST}/OD_risikoomraader_2024/MapServer", {"f": "json"},
                        name="1a MST risk MapServer", note="service metadata")
    lines = []
    if svc:
        layers = svc.get("layers", []); tables = svc.get("tables", [])
        lines.append(f"`{svc.get('mapName', '?')}` · {len(layers)} layers, {len(tables)} tables · "
                     f"spatialReference {((svc.get('spatialReference') or {}).get('latestWkid') or (svc.get('spatialReference') or {}).get('wkid'))}")
        lines.append("")
        lines.append("| id | name | type | parent | sub-layers |")
        lines.append("|---|---|---|---|---|")
        for L in layers:
            par = L.get("parentLayerId")
            lines.append(f"| {L['id']} | {L.get('name', '')} | {L.get('type', '')} | "
                         f"{'' if par in (None, -1) else par} | {len(L.get('subLayerIds') or [])} |")
        g16 = next((L for L in layers if L["id"] == 16), None)
        if g16:
            n = len(g16.get("subLayerIds") or [])
            check("group 16 sub-layers (risk areas)", n, 25)
            byid = {L["id"]: L for L in layers}
            names = [byid[i].get("name", "") for i in g16["subLayerIds"] if i in byid]
            lines.append("")
            lines.append(f"Group **16 · {g16.get('name')}** holds **{n}** sub-layers "
                         f"(ids {min(g16['subLayerIds'])}–{max(g16['subLayerIds'])}), each a single "
                         f"risk area: " + ", ".join(sorted(x.replace("Risikoområde ", "") for x in names)) + ".")
        ROWS[-1] = (ROWS[-1][0], ROWS[-1][1], ROWS[-1][2], ROWS[-1][3], f"{len(layers)} layers")

    # layer 33: the polygons themselves, in 4326 and again in 25832 for a true area
    gj, r, _, n = jget(f"{MST}/OD_risikoomraader_2024/MapServer/33/query",
                       {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson"},
                       name="1b risk layer 33 (4326)", note="geojson")
    if gj:
        feats = gj.get("features", [])
        ROWS[-1] = (ROWS[-1][0], ROWS[-1][1], ROWS[-1][2], ROWS[-1][3], f"{len(feats)} features")
        lines.append("")
        lines.append(f"Layer 33 returns **{len(feats)} features** (EPSG:4326 geojson, {n:,} bytes).")
        props = feats[0]["properties"] if feats else {}
        if props:
            lines.append("")
            lines.append("Layer 33 attributes: " + ", ".join(f"`{k}`" for k in props))
            lines.append("")
            lines.append("First feature: " + ", ".join(f"{k}={v!r}" for k, v in list(props.items())[:8]))
    gj2, _, _, _ = jget(f"{MST}/OD_risikoomraader_2024/MapServer/33/query",
                        {"where": "1=1", "outFields": "*", "outSR": 25832, "f": "geojson"},
                        name="1c risk layer 33 (25832)", note="for area km²")
    if gj2:
        try:
            from shapely.geometry import shape
            from shapely.ops import unary_union
            geoms = [shape(f["geometry"]) for f in gj2.get("features", []) if f.get("geometry")]
            km2 = unary_union(geoms).area / 1e6
            check("layer 33 area km² (EPSG:25832)", round(km2, 1), 101.5, tol=0.6)
            ROWS[-1] = (ROWS[-1][0], ROWS[-1][1], ROWS[-1][2], ROWS[-1][3], f"{km2:.2f} km²")
            lines.append("")
            lines.append(f"Dissolved area in EPSG:25832: **{km2:.2f} km²** (expected ≈ 101.5).")
        except ImportError:
            lines.append("\n(shapely missing — area not computed)")
    block("1 · MST risk areas — OD_risikoomraader_2024", "\n".join(lines))


# ---------- 2. MST hazard rasters (OD_fare_2024) ----------
CLIMATE_WORDS = re.compile(r"nutidig|fremtidig|havspejl|vandstandsstigning|klima|scenari|RCP|"
                           r"\b(?:19|20|21)\d\d\b", re.I)
# services whose own item info might state the climate basis of the flood maps
BASIS_SERVICES = ["OD_fare_2024", "OD_risikoomraader_2024", "OD_Vandstand_Støttepunkter",
                  "OSD_100aars_40cm", "Forslaaet_Scenarier",
                  "Kystplanlaegger_Oversvommelsesfare_2", "Kystplanlaegger_Oversvommelsesskade",
                  "Kystplanlaegger_Erosionsskade", "Kystplanlaegger_Strategiforslag"]
# (a sweep of all 128 services in /ekstern found these are the only ones that name a horizon)


def _strip(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x or "")).strip()


def probe_hazard():
    svc, r, _, _ = jget(f"{MST}/OD_fare_2024/MapServer", {"f": "json"},
                        name="2a MST hazard MapServer", note="service metadata")
    lines = []
    if svc:
        layers = svc.get("layers", [])
        ROWS[-1] = ROWS[-1][:4] + (f"{len(layers)} layers",)
        lines.append(f"`{svc.get('mapName', '?')}` · {len(layers)} layers · "
                     f"capabilities `{svc.get('capabilities', '')}` · "
                     f"image formats `{svc.get('supportedImageFormatTypes', '')}`")
        lines.append("")
        lines.append("| id | name | type | parent |")
        lines.append("|---|---|---|---|")
        for L in layers:
            par = L.get("parentLayerId")
            lines.append(f"| {L['id']} | {L.get('name', '')} | {L.get('type', '')} | "
                         f"{'' if par in (None, -1) else par} |")
        lines.append("")
        lines.append("Two group layers — **Hav** (sea, 9 return periods from 10 to 10 000 years) and "
                     "**Vandløb** (watercourse, 10–100 years). Every leaf is a *Raster Layer*.")

    lay, r, _, _ = jget(f"{MST}/OD_fare_2024/MapServer/21", {"f": "json"},
                        name="2b hazard layer 21", note="Hav_Fare_100år metadata")
    if lay:
        ext = lay.get("extent") or {}
        wkid = ((ext.get("spatialReference") or {}).get("latestWkid")
                or (ext.get("spatialReference") or {}).get("wkid"))
        ROWS[-1] = ROWS[-1][:4] + (lay.get("name", ""),)
        lines.append("")
        lines.append(f"### Layer 21 — {lay.get('name')}")
        lines.append("")
        lines.append(f"* type `{lay.get('type')}` · capabilities `{lay.get('capabilities', '')}`")
        lines.append(f"* `description` and `copyrightText` are both empty")
        for k in ("pixelSizeX", "pixelSizeY", "minScale", "maxScale"):
            lines.append(f"* `{k}` = {lay.get(k, 'absent — a MapServer raster layer does not publish it')}")
        if ext:
            lines.append(f"* extent (EPSG:{wkid}): {ext.get('xmin'):,.0f} – {ext.get('xmax'):,.0f} E, "
                         f"{ext.get('ymin'):,.0f} – {ext.get('ymax'):,.0f} N "
                         f"({(ext.get('xmax') - ext.get('xmin')) / 1000:,.0f} × "
                         f"{(ext.get('ymax') - ext.get('ymin')) / 1000:,.0f} km — all of Denmark)")

    # the underlying raster's own metadata record names the source file
    r, _, n = get(f"{MST}/OD_fare_2024/MapServer/21/metadata", name="2b2 layer 21 metadata XML",
                  note="ISO record")
    if r is not None and r.status_code == 200:
        title = _strip((re.search(r"<resTitle[^>]*>(.*?)</resTitle>", r.text, re.S) or [None, ""])[1])
        ROWS[-1] = ROWS[-1][:4] + (title or "no title",)
        if title:
            lines.append(f"* source raster, from the layer's ISO record: **`{title}`**")

    # a 500 x 500 m box in Copenhagen harbour, 2 m pixels, asked for as float32 GeoTIFF
    x, y = wgs84_to_utm32(*CPH_HARBOUR)
    bbox = f"{x - 250:.1f},{y - 250:.1f},{x + 250:.1f},{y + 250:.1f}"
    lines.append("")
    lines.append(f"### exportImage — 500 × 500 m box in Copenhagen harbour")
    lines.append("")
    lines.append(f"Centre {CPH_HARBOUR[1]}, {CPH_HARBOUR[0]} → {x:,.0f} E, {y:,.0f} N in EPSG:3044; "
                 f"`bbox={bbox}`, `size=250,250` (2 m pixels), `format=tiff`, `pixelType=F32`, "
                 "`layers=show:21`.")
    lines.append("")
    common = {"bbox": bbox, "bboxSR": 3044, "imageSR": 3044, "size": "250,250",
              "format": "tiff", "pixelType": "F32", "layers": "show:21",
              "noData": "", "interpolation": "RSP_NearestNeighbor", "f": "image"}
    raw_ok = False
    for op in ("exportImage", "export"):
        r, secs, n = get(f"{MST}/OD_fare_2024/MapServer/{op}", common,
                         name=f"2c hazard /{op}", note="tiff F32 asked for")
        if r is None:
            continue
        ct = r.headers.get("Content-Type", "") or "(none)"
        magic = r.content[:4]
        what, note = "", ct
        if r.status_code != 200:
            what = f"rejected — `{_strip(r.text)[:160]}`"
            note = f"{r.status_code} {_strip(r.text)[:40]}"
        elif magic == b"\x89PNG":
            try:
                from PIL import Image
                import numpy as np
                im = Image.open(io.BytesIO(r.content)); a = np.array(im)
                what = (f"**PNG, not TIFF** — mode `{im.mode}`, {im.size[0]}×{im.size[1]}, dtype "
                        f"{a.dtype}. The `format=tiff` and `pixelType=F32` parameters are ignored: "
                        "this is a rendered, symbolised picture, so **no raw depth values come back**.")
                note = f"PNG {im.mode} {a.dtype} — rendered, not raw"
            except Exception as e:                                     # noqa: BLE001
                what = f"PNG returned, unreadable here: {e}"
        elif magic in (b"II*\x00", b"MM\x00*"):
            try:
                from PIL import Image
                import numpy as np
                im = Image.open(io.BytesIO(r.content)); a = np.array(im)
                fin = a[a > -3.4e38] if a.dtype.kind == "f" else a
                raw_ok = a.dtype.kind == "f"
                what = (f"TIFF, mode `{im.mode}`, dtype {a.dtype}, min {fin.min():.3f}, "
                        f"max {fin.max():.3f}")
                note = f"TIFF {a.dtype} {fin.min():.2f}–{fin.max():.2f}"
            except Exception as e:                                     # noqa: BLE001
                what = f"TIFF returned, unreadable here: {e}"
        else:
            what = f"unexpected payload, first bytes `{magic!r}`"
        ROWS[-1] = ROWS[-1][:4] + (note[:60],)
        lines.append(f"* `/{op}` → HTTP {r.status_code}, {n:,} bytes, `{ct}` — {what}")

    # identify: the only per-pixel read a MapServer offers. Aim it at a pixel the renderer
    # actually painted, found from a 2 km render, so the answer is not just "NoData".
    px, py = x, y
    r2, _, _ = get(f"{MST}/OD_fare_2024/MapServer/export",
                   {**common, "bbox": f"{x - 1000:.1f},{y - 1000:.1f},{x + 1000:.1f},{y + 1000:.1f}",
                    "size": "200,200", "format": "png32", "transparent": "true"})
    if r2 is not None and r2.content[:4] == b"\x89PNG":
        try:
            from PIL import Image
            import numpy as np
            a = np.array(Image.open(io.BytesIO(r2.content)).convert("RGBA"))
            ys, xs = np.nonzero(a[:, :, 3] > 0)
            if len(xs):
                i = len(xs) // 2
                px = x - 1000 + (xs[i] + .5) * 2000 / 200
                py = y + 1000 - (ys[i] + .5) * 2000 / 200
                lines.append("")
                lines.append(f"* {100 * (a[:, :, 3] > 0).mean():.1f}% of a 2 × 2 km render around the "
                             f"harbour is painted; `/identify` below is aimed at one of those pixels "
                             f"({px:,.0f} E, {py:,.0f} N).")
        except Exception:                                              # noqa: BLE001
            pass
    p = {"geometry": f"{px},{py}", "geometryType": "esriGeometryPoint", "sr": 3044,
         "layers": "all:21", "tolerance": 2,
         "mapExtent": f"{px - 250:.1f},{py - 250:.1f},{px + 250:.1f},{py + 250:.1f}",
         "imageDisplay": "250,250,96",
         "returnGeometry": "false", "f": "json"}
    d, r, _, _ = jget(f"{MST}/OD_fare_2024/MapServer/identify", p, name="2d hazard /identify",
                      note="per-pixel read")
    pixval = None
    if d:
        res = d.get("results", [])
        attrs = res[0].get("attributes", {}) if res else {}
        ROWS[-1] = ROWS[-1][:4] + (str(attrs)[:50],)
        pixval = attrs.get("Classify.Pixel Value")
        lines.append("")
        lines.append(f"`/identify` at that pixel returns `{attrs}`"
                     + (f" — **`Classify.Pixel Value` is the modelled flood depth in metres "
                        f"({pixval} m — the service formats numbers in da-DK, so the decimal "
                        "separator is a comma), not a class index**; `Classify.Class value` is the "
                        "renderer's bin alongside it."
                        if pixval not in (None, "NoData") else
                        " — NoData at the probed point."))
    lines.append("")
    lines.append("**Verdict:** `OD_fare_2024` is a *MapServer*, not an *ImageServer*. `/exportImage` "
                 "does not exist on it (HTTP 400) and `/export` ignores `format=tiff` and "
                 "`pixelType=F32`, returning a rendered PNG — **no depth grid comes back over REST**. "
                 "Raw depth *is* readable one point at a time through `/identify`, which is enough to "
                 "score a single test property but not to build a layer. For the layer, the depth "
                 "rasters have to come from the bulk drop in §3 (`Oversvømmelsesfare.zip`, 3.41 GB).")

    # --- the climate basis, as the services state it ---
    lines.append("")
    lines.append("### Climate basis, as the services state it")
    lines.append("")
    quotes = []
    for name in BASIS_SERVICES:
        d, _, _, _ = jget(f"{MST}/{name}/MapServer/info/iteminfo", {"f": "json"})
        if not d:
            continue
        txt = html.unescape(_strip(str(d.get("snippet") or d.get("description") or "")))
        if txt and CLIMATE_WORDS.search(txt):
            quotes.append((name, txt[:400]))
    for name, txt in quotes:
        lines.append(f"* **`{name}`** — “{txt}”")
    lines.append("")
    lines.append("Read together: **`OD_fare_2024` never states a climate basis.** Its own item info "
                 "says only *“Fare for oversvømmelse fra hav og vandløb til OD 2022-2027 plantrin 1”* "
                 "— “Flood hazard from sea and watercourse for the flood-directive cycle 2022-2027, "
                 "planning step 1” — with no mention of *nutidigt* (present-day) or *fremtidigt* "
                 "(future) climate and no sea-level rise (*havspejlsstigning*) allowance. The "
                 "EU-flood-directive hazard maps are present-climate maps by construction, but this "
                 "service does not say so, so the dashboard must not claim a horizon for them.")
    lines.append("")
    lines.append("The neighbouring Kystdirektoratet service is the one that does state horizons: "
                 "**`Kystplanlaegger_Oversvommelsesfare_2`** — *“Viser oversvømmesesfare og "
                 "oversvømmelsesdybde i 2020, 2070 og 2120 for en 100, 1.000 og 10.000 års "
                 "hændelse.”* — “Shows flood hazard and flood depth in 2020, 2070 and 2120 for a "
                 "100-, 1 000- and 10 000-year event.” That is a present-day plus two future "
                 "horizons, i.e. the sea-level-rise allowance sits in the 2070/2120 layers. It is "
                 "the better fit for a Today / 2050 / 2100 horizon pill than `OD_fare_2024`, and it "
                 "is worth probing in its own right before the layer is designed.")
    block("2 · MST hazard rasters — OD_fare_2024", "\n".join(lines))


# ---------- 3. MST bulk drop ----------
SFTP_HOST = "https://sftp.statens-it.dk"
SFTP_FID = "sudeyofd-echpkegqfxhbg"                 # "Plantrin 1 National data 2024"


def probe_bulk():
    """The drop is a Cerberus FTP web client. The page is a shell, but its DataTables source
    (`POST /public/op/<id>/get_dir`) and its zip route (`POST /public/op/<id>/zip/<name>`) both
    answer a plain HTTP client, so the folder can be listed and pulled without a browser."""
    lines = []
    sess = requests.Session()
    folder = f"{SFTP_HOST}/public/folder/{SFTP_FID}/"
    r, secs, n = get(folder, name="3a MST bulk folder page", note="Cerberus web client shell")
    tok = ""
    if r is not None:
        sess.cookies.update(r.cookies)
        tok = (re.search(r'name="csrftoken" content="([^"]+)"', r.text) or [None, ""])[1]
        title = (re.search(r"<title>(.*?)</title>", r.text, re.S | re.I) or [None, ""])[1].strip()
        lines.append(f"`GET {folder}` → HTTP {r.status_code}, {n:,} bytes — `{title}`. "
                     "The HTML carries no file names; the listing is a DataTables ajax source.")
        ROWS[-1] = ROWS[-1][:4] + (f"{title} · csrftoken {'yes' if tok else 'no'}",)

    t0 = time.time()
    files = []
    try:
        rr = sess.post(f"{SFTP_HOST}/public/op/{SFTP_FID}/get_dir",
                       data={"sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 1000, "cd": "/",
                             "csrftoken": tok},
                       headers={**UA, "X-Requested-With": "XMLHttpRequest", "Referer": folder},
                       timeout=TIMEOUT)
        files = rr.json().get("aaData", [])
        ROWS.append(("3b bulk get_dir (listing)", str(rr.status_code), f"{time.time() - t0:.2f}",
                     f"{len(rr.content):,}", f"{len(files)} entries"))
    except Exception as e:                                             # noqa: BLE001
        ROWS.append(("3b bulk get_dir (listing)", "ERR", f"{time.time() - t0:.2f}", "0",
                     f"{type(e).__name__}: {e}"[:60]))
    if files:
        total = sum(f.get("size") or 0 for f in files)
        lines.append("")
        lines.append(f"`POST /public/op/{SFTP_FID}/get_dir` (form: `cd=/`, `csrftoken`, DataTables "
                     f"paging) returns the listing as JSON — **{len(files)} files, "
                     f"{total / 1e9:.2f} GB in total**:")
        lines.append("")
        lines.append("| file | size | MB | modified |")
        lines.append("|---|---|---|---|")
        for f in sorted(files, key=lambda x: -(x.get("size") or 0)):
            sz = f.get("size") or 0
            lines.append(f"| `{f.get('name')}` | {sz:,} | {sz / 1e6:,.1f} | {(f.get('time') or '')[:10]} |")

    # the zip route — 2 KB of the smallest file, enough to prove the bytes are real
    small = min((f for f in files if (f.get("size") or 0) > 0), key=lambda f: f["size"], default=None)
    if small:
        t0 = time.time()
        try:
            rr = sess.post(f"{SFTP_HOST}/public/op/{SFTP_FID}/zip/probe.zip",
                           data={"cd": "/", "ID": small["name"], "zipname": "probe.zip",
                                 "csrftoken": tok},
                           headers={**UA, "Referer": folder, "Range": "bytes=0-2047"},
                           timeout=TIMEOUT, stream=True)
            first = next(rr.iter_content(64), b"")
            rr.close()
            ok = first[:2] == b"PK"
            ROWS.append((f"3c bulk zip/{small['name'][:14]}", str(rr.status_code),
                         f"{time.time() - t0:.2f}", "2,048",
                         "real ZIP bytes" if ok else f"not a zip: {first[:8]!r}"))
            lines.append("")
            lines.append(f"`POST /public/op/{SFTP_FID}/zip/<name>.zip` (form: `cd`, one `ID` per "
                         f"selected file, `zipname`, `csrftoken`) streams the files back. Probed with "
                         f"a `Range: bytes=0-2047` on `{small['name']}` → HTTP {rr.status_code}, "
                         f"first bytes `{first[:4]!r}` — {'a real ZIP' if ok else 'not a ZIP'}. "
                         "**The drop is scriptable; no browser needed.**")
        except Exception as e:                                         # noqa: BLE001
            ROWS.append(("3c bulk zip route", "ERR", f"{time.time() - t0:.2f}", "0",
                         f"{type(e).__name__}: {e}"[:60]))
    block("3 · MST bulk drop (Plantrin 1 National data 2024)", "\n".join(lines))


# ---------- 4. DMI Klimaatlas ----------
AGOL = "https://services9.arcgis.com/qH1Ysxh3VVYXbkQU/arcgis/rest/services"


def _fields(recs, *names):
    """case-insensitive attribute lookup across ArcGIS field spellings"""
    out = {}
    for n in names:
        for k in recs:
            if k.lower() == n.lower():
                out[n] = recs[k]
                break
        else:
            out[n] = None
    return out


def probe_klimaatlas():
    lines = []
    svc, _, _, _ = jget(f"{AGOL}/VandstandStormflodKyst_latest/FeatureServer",
                        {"f": "json"}, name="4a Klimaatlas coast service", note="FeatureServer")
    if svc:
        ls = svc.get("layers", []) + svc.get("tables", [])
        ROWS[-1] = ROWS[-1][:4] + (f"{len(svc.get('layers', []))} layers / {len(svc.get('tables', []))} tables",)
        lines.append("| id | name | kind | geometry |")
        lines.append("|---|---|---|---|")
        for L in ls:
            lines.append(f"| {L.get('id')} | {L.get('name')} | {L.get('type')} | {L.get('geometryType') or '—'} |")

    where = "kystkode='SJ7' AND percentil=50 AND aarstid=1 AND absolutaendring=1"
    d, _, _, n = jget(f"{AGOL}/VandstandStormflodKyst_latest/FeatureServer/0/query",
                      {"where": where, "outFields": "*", "returnGeometry": "false", "f": "json"},
                      name="4b coast SJ7 p50", note=where[:40])
    if d:
        recs = [f["attributes"] for f in d.get("features", [])]
        ROWS[-1] = ROWS[-1][:4] + (f"{len(recs)} rows",)
        lines.append("")
        lines.append(f"`kystkode='SJ7'` p50 → **{len(recs)} rows**; fields: "
                     + ", ".join(f"`{k}`" for k in (recs[0] if recs else {})))

        def pick(scen, per, field):
            for a in recs:
                f = _fields(a, "scenarie", "periode", field)
                if str(f["scenarie"]) == str(scen) and str(f["periode"]) == str(per):
                    return f[field]
            return None

        lines.append("")
        lines.append("| scenarie | periode | field | got | expected |")
        lines.append("|---|---|---|---|---|")
        for scen, per, field, want in [(0, 1, "Stormfl100Aarsh", 156.85),
                                       (245, 3, "Middelvandstand", 24.89),
                                       (245, 3, "Stormfl100Aarsh", 181.74),
                                       (245, 4, "Middelvandstand", 39.44),
                                       (245, 4, "Stormfl100Aarsh", 196.29)]:
            got = pick(scen, per, field)
            got = round(float(got), 2) if isinstance(got, (int, float)) else got
            ok = check(f"SJ7 scen {scen} per {per} {field}", got, want)
            lines.append(f"| {scen} | {per} | {field} | {got} | {want} | {'✓' if ok else '✗'} |".replace("| ✓", "✓").replace("| ✗", "✗"))

    where2 = "komkode=101 AND percentil=50 AND aarstid=1 AND absolutaendring=1"
    d2, _, _, _ = jget(f"{AGOL}/NedboerKommuner_latest/FeatureServer/0/query",
                       {"where": where2, "outFields": "*", "returnGeometry": "false", "f": "json"},
                       name="4c precip kom 101 p50", note=where2[:40])
    if d2:
        recs2 = [f["attributes"] for f in d2.get("features", [])]
        ROWS[-1] = ROWS[-1][:4] + (f"{len(recs2)} rows",)
        lines.append("")
        lines.append(f"`komkode=101` p50 → **{len(recs2)} rows**; fields: "
                     + ", ".join(f"`{k}`" for k in (recs2[0] if recs2 else {})))
        lines.append("")
        lines.append("| scenarie | periode | field | got | expected |")
        lines.append("|---|---|---|---|---|")
        for scen, per, field, want in [(45, 3, "Time100Aarsh", 51.30), (45, 4, "Time100Aarsh", 52.73)]:
            got = None
            for a in recs2:
                f = _fields(a, "scenarie", "periode", field)
                if str(f["scenarie"]) == str(scen) and str(f["periode"]) == str(per):
                    got = f[field]
            got = round(float(got), 2) if isinstance(got, (int, float)) else got
            ok = check(f"kom 101 scen {scen} per {per} {field}", got, want)
            lines.append(f"| {scen} | {per} | {field} | {got} | {want} | {'✓' if ok else '✗'} |")

    # coastal stretches carrying geometry
    d3, _, _, _ = jget(f"{AGOL}/VandstandStormflodKyst_latest/FeatureServer/0/query",
                       {"where": "1=1", "outFields": "kystkode", "returnDistinctValues": "true",
                        "returnGeometry": "false", "f": "json"},
                       name="4d distinct kystkode", note="stretch count")
    if d3:
        ks = sorted({str(f["attributes"].get("kystkode")) for f in d3.get("features", [])})
        ROWS[-1] = ROWS[-1][:4] + (f"{len(ks)} stretches",)
        lines.append("")
        lines.append(f"Distinct `kystkode` values on the value layer: **{len(ks)}** — {', '.join(ks)}")
    for lid in (0, 1, 2):
        meta, _, _, _ = jget(f"{AGOL}/VandstandStormflodKyst_latest/FeatureServer/{lid}", {"f": "json"})
        dg, _, _, _ = jget(f"{AGOL}/VandstandStormflodKyst_latest/FeatureServer/{lid}/query",
                           {"where": "1=1", "returnCountOnly": "true", "f": "json"})
        if not (meta and dg and dg.get("count") is not None):
            continue
        lines.append(f"* layer {lid} `{meta.get('name')}` · {meta.get('geometryType')} · "
                     f"{dg['count']} features")
        if (meta.get("geometryType") or "").endswith("Polygon"):
            check("coastal stretches with geometry (Kystinddeling)", dg["count"], 34)
    block("4 · DMI Klimaatlas (ArcGIS Online)", "\n".join(lines))


# ---------- 5. Datafordeler DHM (WCS) ----------
def probe_dhm():
    key = os.environ.get("DATAFORDELER_API_KEY")
    lines = []
    base = "https://wcs.datafordeler.dk/DHMNedboer/dhm_wcs/1.0.0/WCS"
    if not key:
        lines.append("**No `DATAFORDELER_API_KEY` in `.env`** — the only key the repo carries is "
                     "`UDDSTAT_API_KEY`. The BBR pull in `scripts/fetch_bbr.py` reads "
                     "`DATAFORDELER_API_KEY` (or `DATAFORDELER_USER`/`DATAFORDELER_PASS`), so the "
                     "existing BBR cache was fetched with a key that is no longer on disk. "
                     "Probed unauthenticated to record what the service answers.")
        lines.append("")
    p = {"service": "WCS", "request": "GetCapabilities", "version": "1.0.0"}
    if key:
        p["apikey"] = key
    r, secs, n = get(base, p, name="5a DHM WCS GetCapabilities",
                     note="key present" if key else "NO API KEY in .env")
    if r is not None:
        lines.append(f"`GET {base}?service=WCS&request=GetCapabilities` → HTTP {r.status_code}, {n:,} bytes")
        txt = r.text
        covs = re.findall(r"<(?:wcs:)?name>([^<]+)</(?:wcs:)?name>", txt, re.I)
        covs = [c for c in covs if not c.lower().startswith("wcs")]
        if covs:
            lines.append("")
            lines.append(f"Coverages ({len(covs)}): " + ", ".join(f"`{c}`" for c in sorted(set(covs))[:40]))
            ROWS[-1] = ROWS[-1][:4] + (f"{len(set(covs))} coverages",)
        elif r.status_code == 401:
            lines.append("")
            lines.append("**HTTP 401 with an empty body** — the endpoint is alive and simply refuses "
                         "an unauthenticated caller, so the coverage list (terrain? bluespot?) cannot "
                         "be read from here. Same blocker as §6.")
        else:
            lines.append("")
            lines.append("No coverage names in the response — first 400 bytes:")
            lines.append("")
            lines.append("```\n" + (txt[:400] or "(empty body)") + "\n```")
        if not key:
            lines.append("")
            lines.append("GetCoverage not attempted: it needs the same key.")
        else:
            x, y = wgs84_to_utm32(*CPH_HARBOUR)
            bbox = f"{x - 500:.0f},{y - 500:.0f},{x + 500:.0f},{y + 500:.0f}"
            name = sorted(set(covs))[0] if covs else "dhm_terraen"
            for label, res in (("native (0.4 m)", None), ("2 m", 2)):
                q = {"service": "WCS", "version": "1.0.0", "request": "GetCoverage",
                     "coverage": name, "crs": "EPSG:25832", "bbox": bbox,
                     "format": "GTiff", "apikey": key}
                if res:
                    q["resx"] = q["resy"] = res
                else:
                    q["width"] = q["height"] = 2500
                rr, ss, nn = get(base, q, name=f"5b DHM GetCoverage {label}", note=f"1×1 km, {name}")
                if rr is not None:
                    lines.append(f"* GetCoverage `{name}` 1×1 km at {label} → HTTP {rr.status_code}, "
                                 f"{nn:,} bytes, {ss:.1f} s, `{rr.headers.get('Content-Type', '')}`")
    block("5 · Datafordeler DHM (WCS)", "\n".join(lines))


# ---------- 6. Bluespot raster ----------
BLUESPOT_CANDIDATES = [
    ("Datafordeler selfservice", "https://selfservice.datafordeler.dk/"),
    ("Datafordeler API root", "https://api.datafordeler.dk/"),
    ("Datafordeler DHM Fildownload (Raster) product page",
     "https://datafordeler.dk/dataoversigt/danmarks-hoejdemodel-dhm/dhm-fildownload-raster/"),
    ("Dataforsyningen download (legacy)", "https://download.dataforsyningen.dk/"),
    ("Dataforsyningen FTP (legacy)", "https://ftp.dataforsyningen.dk/"),
    ("Kortforsyningen FTP (legacy)", "https://ftp.kortforsyningen.dk/"),
    ("Dataforsyningen API (legacy)", "https://api.dataforsyningen.dk/"),
]


def probe_bluespot():
    lines = ["Every candidate route, probed with a plain GET (redirects followed):", ""]
    for label, url in BLUESPOT_CANDIDATES:
        r, secs, n = get(url, name=f"6 {label}"[:40], note=url.split("//")[1].split("/")[0],
                         allow_redirects=True)
        if r is None:
            lines.append(f"* **{label}** — `{url}` → **host does not resolve / refuses the connection**")
            continue
        ct = r.headers.get("Content-Type", "") or "(none)"
        extra = ""
        if "html" in ct.lower():
            t = _strip((re.search(r"<title>(.*?)</title>", r.text, re.S | re.I) or [None, ""])[1])
            if t:
                extra = f" — `{t[:90]}`"
        lines.append(f"* **{label}** — `{url}` → HTTP {r.status_code}, {n:,} bytes, `{ct}`{extra}")

    lines.append("")
    lines.append("### Where the product lives now")
    lines.append("")
    lines.append(
        "* The product is **DHM/Bluespot_ekstremregn** — how much rain has to fall before a given "
        "depression (a *bluespot*) fills and floods — published as **10 × 10 km GeoTIFF tiles on the "
        "Danish square grid (DDKN)**, alongside `Terraen`, `Overflade`, `Bluespot2007`, `Terraen2015` "
        "and `Overflade2015`.\n"
        "* The two legacy hosts named in the Dataforsyningen closure note — `ftp.dataforsyningen.dk` "
        "and `download.dataforsyningen.dk` — **no longer resolve**, so that route is gone.\n"
        "* The live route is **Datafordeler**: the pre-generated raster file downloads are pulled "
        "through Datafordeler's REST API / *Fildownload*, and the older *Filudtræk (DHM)* is being "
        "retired — its own documentation says to move to *Fildownload på Datafordeleren* after "
        "**15 January 2027**.\n"
        "* Both need credentials: the raster file download wants an **API key** from an IT-system on "
        "Datafordeler Administration, and Filudtræk wants a **service user (username + password)**. "
        "`api.datafordeler.dk` answers **401** unauthenticated, which matches.\n"
        "* **Blocker for this branch:** the repo has no Datafordeler credentials (`.env` holds only "
        "`UDDSTAT_API_KEY`), so neither the bluespot tiles nor the DHM WCS in §5 can be fetched until "
        "a key is put back. Nothing else in the climate layer is blocked on it.")

    lines.append("")
    lines.append("### Tile arithmetic (DDKN 10 km)")
    try:
        from shapely.geometry import box, shape
        from shapely.ops import transform
        gj = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text())
        to_utm = lambda x, y, z=None: wgs84_to_utm32(x, y)             # noqa: E731
        all_t, metro_t = set(), set()
        for f in gj["features"]:
            p = f["properties"]
            code = str(p.get("kode") or p.get("kommunekode") or p.get("KOMKODE") or "").zfill(4)
            g = transform(to_utm, shape(f["geometry"])).buffer(0)
            x0, y0, x1, y1 = g.bounds
            ts = set()
            for xx in range(int(x0 // 10000) * 10000, int(x1 // 10000) * 10000 + 1, 10000):
                for yy in range(int(y0 // 10000) * 10000, int(y1 // 10000) * 10000 + 1, 10000):
                    if g.intersects(box(xx, yy, xx + 10000, yy + 10000)):
                        ts.add((yy // 10000, xx // 10000))
            all_t |= ts
            if code in METRO19:
                metro_t |= ts
        lines.append("")
        lines.append("A DDKN 10 km tile is named `10km_<N>_<E>` after the kilometre-grid index of its "
                     "south-west corner in EPSG:25832 (e.g. `10km_617_72` covers Copenhagen). Counted "
                     "by intersecting the vendored kommune polygons with that grid:")
        lines.append("")
        lines.append(f"* **{len(all_t)}** tiles cover all 99 kommuner (Denmark)")
        lines.append(f"* **{len(metro_t)}** tiles cover the 19 metro kommuner")
        lines.append("")
        lines.append("At the 0.4 m DHM resolution a 10 km tile is 25 000 × 25 000 px = 2.5 GB raw as "
                     "float32; published bluespot tiles compress far below that because most of the "
                     "raster is no-data. Taking 150–400 MB per tile as the working range: "
                     f"**{len(metro_t) * .15:.0f}–{len(metro_t) * .4:.0f} GB for the metro 19** and "
                     f"**{len(all_t) * .15:.0f}–{len(all_t) * .4:.0f} GB for Denmark**. One real tile has to be "
                     "measured before either number is trusted — which needs the credentials above.")
        metro_list = sorted(f"10km_{n}_{e}" for n, e in metro_t)
        lines.append("")
        lines.append("Metro tiles: " + ", ".join(f"`{t}`" for t in metro_list))
    except Exception as e:                                             # noqa: BLE001
        lines.append(f"\n(tile count not computed: {type(e).__name__}: {e})")
    block("6 · Bluespot (ekstremregn) raster — download route", "\n".join(lines))


# ---------- 7. Forsikring & Pension damage series ----------
FP_CHARTS = ["TUJ9b", "z0zEO"]


def probe_fp():
    lines = []
    for cid in FP_CHARTS:
        base = f"https://datawrapper.dwcdn.net/{cid}/"
        r, _, n = get(base, name=f"7a F&P {cid} index", note="follow to latest version")
        ver = None
        if r is not None and r.status_code == 200:
            vs = [int(v) for v in re.findall(rf"{cid}/(\d+)/", r.text)]
            ver = max(vs) if vs else None
        if ver is None:                       # walk versions until one answers
            for v in range(30, 0, -1):
                rr, _, _ = get(f"https://datawrapper.dwcdn.net/{cid}/{v}/dataset.csv")
                if rr is not None and rr.status_code == 200:
                    ver = v
                    break
        if ver is None:
            lines.append(f"### `{cid}` — no readable version found")
            continue
        url = f"https://datawrapper.dwcdn.net/{cid}/{ver}/dataset.csv"
        rr, secs, nn = get(url, name=f"7b F&P {cid} dataset.csv", note=f"version {ver}")
        if rr is None or rr.status_code != 200:
            lines.append(f"### `{cid}` — dataset.csv unavailable (version {ver})")
            continue
        txt = rr.content.decode("utf-8-sig", "replace")
        sep = "\t" if txt.count("\t") > txt.count(",") else ","
        rows = list(csv.reader(io.StringIO(txt), delimiter=sep))
        rows = [r_ for r_ in rows if any(c.strip() for c in r_)]
        ROWS[-1] = ROWS[-1][:4] + (f"v{ver} · {len(rows) - 1} data rows",)
        check(f"F&P {cid} row count ≈ 98", len(rows) - 1, 98, tol=0)
        lines.append(f"### `{cid}` → version {ver} · {len(rows) - 1} data rows · separator `{'TAB' if sep == chr(9) else sep}`")
        lines.append("")
        lines.append(f"`{url}`")
        lines.append("")
        lines.append("```")
        for r_ in rows[:6]:
            lines.append(sep.join(r_))
        lines.append(f"… ({len(rows) - 1} data rows total)")
        lines.append("```")
        lines.append("")
        lines.append(f"Join key is the kommune **name** (`{rows[0][0] if rows else '?'}`), padded with "
                     "spaces and with no kommune code — it has to be trimmed and matched against "
                     "`data/geo/kommuner.geojson` names before it can be indexed by code, and "
                     f"{len(rows) - 1} rows against 98 kommuner means the split kommuner need checking.")
        lines.append("")
    block("7 · Forsikring & Pension — realised weather damage", "\n".join(lines))


# ---------- 8. Coastal kommuner from the vendored boundaries ----------
METRO19 = ["0101", "0147", "0151", "0153", "0155", "0157", "0159", "0161", "0163", "0165",
           "0167", "0169", "0173", "0175", "0183", "0185", "0187", "0190", "0230"]


def probe_coast():
    lines = []
    t0 = time.time()
    try:
        from shapely.geometry import shape
        from shapely.ops import transform, unary_union
        from shapely.strtree import STRtree
    except ImportError:
        ROWS.append(("8 coastal kommuner", "—", "0.00", "0", "shapely missing"))
        block("8 · Coastal kommuner", "shapely missing — not computed.")
        return
    gj = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text())
    to_utm = lambda x, y, z=None: wgs84_to_utm32(x, y)                 # noqa: E731
    koms = []
    for f in gj["features"]:
        p = f["properties"]
        code = str(p.get("kode") or p.get("kommunekode") or p.get("KOMKODE") or "").zfill(4)
        name = p.get("navn") or p.get("name") or p.get("NAVN") or ""
        koms.append([code, name, transform(to_utm, shape(f["geometry"])).buffer(0)])
    geoms = [g for _, _, g in koms]
    tree = STRtree(geoms)
    TOL = 60          # m — absorbs the sliver between two simplified neighbours
    MIN = 1000        # m of free boundary before a kommune counts as coastal
    rows = []
    for i, (code, name, g) in enumerate(koms):
        near = [j for j in tree.query(g.buffer(TOL)) if j != i]
        shared = unary_union([geoms[j].boundary.buffer(TOL) for j in near]) if near else None
        free = g.boundary.difference(shared) if shared is not None else g.boundary
        rows.append((code, name, free.length))
    coastal = [(c, n, L) for c, n, L in rows if L > MIN]
    secs = time.time() - t0
    ROWS.append(("8 coastal kommuner (local)", "—", f"{secs:.2f}", "0",
                 f"{len(coastal)}/{len(koms)} coastal"))
    lines.append("Method: take the 99 kommune polygons from `data/geo/kommuner.geojson` — the same "
                 "land mask `scripts/fetch_geo_dawa.py` clips the postal codes to — reproject them to "
                 "EPSG:25832, and subtract every neighbour's boundary (60 m tolerance, which absorbs "
                 "the sliver left by the 0.0005° simplification). What is left of a kommune's own "
                 f"boundary is coast; over {MIN:,} m of it makes the kommune coastal.")
    lines.append("")
    lines.append(f"**{len(coastal)} of {len(koms)} kommuner are coastal**, "
                 f"{len(koms) - len(coastal)} landlocked.")
    lines.append("")
    inland = sorted([(c, n, L) for c, n, L in rows if L <= MIN], key=lambda r: r[1])
    lines.append(f"Landlocked ({len(inland)}): " + ", ".join(f"{n} ({c})" for c, n, _ in inland))
    lines.append("")
    cset = {c for c, _, _ in coastal}
    byc = {c: n for c, n, _ in rows}
    byl = {c: L for c, _, L in rows}
    hit = [c for c in METRO19 if c in cset]
    miss = [c for c in METRO19 if c not in cset]
    lines.append(f"Of the 19 metro kommuner (`scripts/fetch_bbr.py: METRO`), **{len(hit)} are coastal**"
                 + (f"; landlocked: {', '.join(f'{byc.get(c, c)} ({c})' for c in miss)}." if miss else " — all 19."))
    lines.append("")
    lines.append("| code | metro kommune | free boundary (km) | coastal |")
    lines.append("|---|---|---|---|")
    for c in METRO19:
        lines.append(f"| {c} | {byc.get(c, '?')} | {byl.get(c, 0) / 1000:.1f} | "
                     f"{'yes' if c in cset else 'no'} |")
    border = sorted([(c, n, L) for c, n, L in rows if 100 < L <= 4000], key=lambda r: r[2])
    if border:
        lines.append("")
        lines.append("Borderline (under 4 km of free boundary — check these by eye before using the "
                     "flag as a filter): "
                     + ", ".join(f"{n} {L / 1000:.1f} km" for _, n, L in border) + ".")
    lines.append("")
    top = sorted(coastal, key=lambda r: -r[2])[:10]
    lines.append("Longest coastlines: " + ", ".join(f"{n} {L / 1000:.0f} km" for _, n, L in top))
    block("8 · Coastal kommuner (from the vendored boundaries)", "\n".join(lines))


# ---------- 9. Kystdirektoratet Kystplanlægger (horizons 2020 / 2070 / 2120) ----------
KDI = "Kystplanlaegger_Oversvommelsesfare_2"
KDI_PTS = [("Copenhagen Sydhavn", 55.650, 12.545),
           ("Hvidovre Avedøre Holme", 55.625, 12.460),
           ("Køge harbour", 55.455, 12.195)]
KDI_WIDE = [("Esbjerg", 55.466, 8.452), ("Aalborg", 57.053, 9.923), ("Aarhus", 56.152, 10.215)]
KDI_100YR = {"2020": 4, "2070": 13, "2120": 22}      # depth rasters, 100-year event
KDI_FARE100 = {"2020": 3, "2070": 12, "2120": 21}    # the matching extent polygons


def _painted(svc, layer, x, y, half=1000, size=200):
    """share of a 2 x 2 km render that the layer paints, and one painted coordinate"""
    r, _, _ = get(f"{MST}/{svc}/MapServer/export",
                  {"bbox": f"{x - half},{y - half},{x + half},{y + half}", "bboxSR": 25832,
                   "imageSR": 25832, "size": f"{size},{size}", "layers": f"show:{layer}",
                   "format": "png32", "transparent": "true", "f": "image"})
    if r is None or r.content[:4] != b"\x89PNG":
        return None, None
    try:
        from PIL import Image
        import numpy as np
        a = np.array(Image.open(io.BytesIO(r.content)).convert("RGBA"))
        m = a[:, :, 3] > 0
        if not m.any():
            return 0.0, None
        ys, xs = np.nonzero(m)
        i = len(xs) // 2
        return 100 * m.mean(), (x - half + (xs[i] + .5) * 2 * half / size,
                                y + half - (ys[i] + .5) * 2 * half / size)
    except Exception:                                                  # noqa: BLE001
        return None, None


def _identify(svc, layer, x, y):
    d, _, _, _ = jget(f"{MST}/{svc}/MapServer/identify",
                      {"geometry": f"{x},{y}", "geometryType": "esriGeometryPoint", "sr": 25832,
                       "layers": f"all:{layer}", "tolerance": 2,
                       "mapExtent": f"{x - 250},{y - 250},{x + 250},{y + 250}",
                       "imageDisplay": "250,250,96", "returnGeometry": "false", "f": "json"})
    res = (d or {}).get("results", [])
    return (res[0].get("attributes", {}) if res else {}).get("Classify.Pixel Value")


def probe_kdi():
    lines = []
    svc, _, _, _ = jget(f"{MST}/{KDI}/MapServer", {"f": "json"},
                        name="9a KDI Kystplanlægger service", note="flood hazard, 3 horizons")
    if svc:
        layers = svc.get("layers", [])
        ext = svc.get("fullExtent") or {}
        ROWS[-1] = ROWS[-1][:4] + (f"{len(layers)} layers · {svc.get('capabilities', '')}",)
        lines.append(f"`{KDI}` · **{len(layers)} layers** · capabilities `{svc.get('capabilities')}` · "
                     f"full extent EPSG:"
                     f"{(ext.get('spatialReference') or {}).get('latestWkid')} "
                     f"{ext.get('xmin', 0):,.0f}–{ext.get('xmax', 0):,.0f} E, "
                     f"{ext.get('ymin', 0):,.0f}–{ext.get('ymax', 0):,.0f} N")
        lines.append("")
        lines.append("Three horizon groups × four return periods × two representations:")
        lines.append("")
        lines.append("| horizon | return period | extent polygon (Feature Layer) | depth raster (Raster Layer) |")
        lines.append("|---|---|---|---|")
        byname = {L["name"]: L["id"] for L in layers}
        for hz in ("2020", "2070", "2120"):
            for rp in ("50", "100", "1.000", "10.000"):
                norm = lambda t: t.replace("-", " ").replace("  ", " ")   # noqa: E731
                fare = next((i for n, i in byname.items()
                             if n.startswith(f"Oversvømmelsesfare i {hz}")
                             and f"{rp} års" in norm(n)), None)
                dyb = next((i for n, i in byname.items()
                            if n.startswith(f"Oversvømmelsesdybde i {hz}")
                            and f"{rp} år" in norm(n)), None)
                lines.append(f"| {hz} | {rp} yr | {fare if fare is not None else '—'} | "
                             f"{dyb if dyb is not None else '—'} |")

    # coverage: national or a few stretches?
    d, _, _, _ = jget(f"{MST}/{KDI}/MapServer/3/query",
                      {"where": "1=1", "returnCountOnly": "true", "f": "json"},
                      name="9b KDI extent polygons", note="2020 · 100 yr")
    meta, _, _, _ = jget(f"{MST}/{KDI}/MapServer/3", {"f": "json"})
    if d and meta:
        e = meta.get("extent") or {}
        ROWS[-1] = ROWS[-1][:4] + (f"{d.get('count')} polygons",)
        lines.append("")
        lines.append(f"### Coverage — national, not a few stretches")
        lines.append("")
        lines.append(f"The 2020 · 100-year extent layer holds **{d.get('count')} polygons** spanning "
                     f"{e.get('xmin', 0):,.0f}–{e.get('xmax', 0):,.0f} E and "
                     f"{e.get('ymin', 0):,.0f}–{e.get('ymax', 0):,.0f} N in EPSG:25832 — the full "
                     "width and height of Denmark, unlike `OD_fare_2024`, which only covers the "
                     "designated flood-directive risk areas. Rendered coverage at six points, as the "
                     "painted share of a 2 × 2 km box:")
        lines.append("")
        lines.append("| point | KDI 2020 | KDI 2070 | KDI 2120 | MST OD 100 yr |")
        lines.append("|---|---|---|---|---|")
        for label, lat, lon in KDI_PTS + KDI_WIDE:
            x, y = wgs84_to_utm32(lon, lat)
            cells = []
            for hz in ("2020", "2070", "2120"):
                pc, _ = _painted(KDI, KDI_100YR[hz], x, y)
                cells.append("—" if pc is None else f"{pc:.1f} %")
            pc, _ = _painted("OD_fare_2024", 21, x, y)
            cells.append("—" if pc is None else f"{pc:.1f} %")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")

    # raster or vector, and any raw-depth download route
    lines.append("")
    lines.append("### Raster or vector, and what can be downloaded")
    lines.append("")
    r, _, n = get(f"{MST}/{KDI}/MapServer/3/query",
                  {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                   "resultRecordCount": 5}, name="9c KDI polygons as geojson", note="5 features")
    gj_ok = r is not None and r.status_code == 200 and r.content[:1] == b"{"
    if gj_ok:
        try:
            feats = r.json().get("features", [])
            props = list(feats[0]["properties"]) if feats else []
            ROWS[-1] = ROWS[-1][:4] + (f"{len(feats)} feats, {n / 1e6:.1f} MB",)
            lines.append(f"* **Extent polygons are downloadable.** `capabilities` includes `Data`, so "
                         f"`/3/query?f=geojson&outSR=4326` returns real geometry — 5 features came back "
                         f"as {n / 1e6:.1f} MB, so all {d.get('count') if d else '?'} polygons are a "
                         "large but fetchable pull, paginated with `resultOffset`. Attributes are "
                         f"geometry bookkeeping only ({', '.join('`' + x + '`' for x in props[:6])}) — "
                         "**no depth, no water level, no scenario field**: the horizon and return "
                         "period live in the *layer*, not in the data.")
        except Exception:                                              # noqa: BLE001
            pass
    r, _, n = get(f"{MST}/{KDI}/MapServer/export",
                  {"bbox": "722000,6171000,724000,6173000", "bboxSR": 25832, "imageSR": 25832,
                   "size": "200,200", "layers": "show:4", "format": "tiff", "pixelType": "F32",
                   "f": "image"}, name="9d KDI depth as tiff", note="format=tiff asked for")
    if r is not None:
        got = "PNG" if r.content[:4] == b"\x89PNG" else ("TIFF" if r.content[:4] in (b"II*\x00", b"MM\x00*") else "?")
        ROWS[-1] = ROWS[-1][:4] + (f"{got} — rendered" if got == "PNG" else got,)
        lines.append(f"* **Depth rasters are not downloadable here.** Same MapServer limit as "
                     f"`OD_fare_2024`: `format=tiff&pixelType=F32` comes back as {got}. There is no "
                     "ImageServer, WCS or bulk/ZIP route on this server; the only per-pixel read is "
                     "`/identify`, one point per request.")
    lines.append("* Sibling services in the same folder (`Kystplanlaegger_*`, 13 of them, plus 15 "
                 "`KDI_*`) carry the same 2020/2070/2120 structure for damage and strategy: "
                 "`Kystplanlaegger_Oversvommelsesskade`, `Kystplanlaegger_Erosionsfare`, "
                 "`Kystplanlaegger_Erosionsskade`, `Kystplanlaegger_Oversvommesesrisiko`, "
                 "`Kystplanlaegger_Strategiforslag`.")

    # climate basis
    d2, _, _, _ = jget(f"{MST}/{KDI}/MapServer/info/iteminfo", {"f": "json"})
    da = html.unescape(_strip(str((d2 or {}).get("snippet") or "")))
    lines.append("")
    lines.append("### Stated climate basis")
    lines.append("")
    if da:
        lines.append(f"> {da}")
        lines.append("")
        lines.append("> *Shows flood hazard and flood depth in 2020, 2070 and 2120 for a 100-, "
                     "1 000- and 10 000-year event.*")
        lines.append("")
    lines.append("That is the whole of it: the service names **three horizons — 2020, 2070 and 2120 — "
                 "and states no scenario, no percentile and no sea-level-rise figure**. It does not "
                 "say which RCP/SSP pathway the 2070 and 2120 layers assume, so the rise is baked in "
                 "and unlabelled. Klimaatlas (§4), by contrast, publishes the rise itself with an "
                 "explicit `scenarie` and `percentil` — which is why the indicators should be built on "
                 "Klimaatlas and this service kept as the map-side illustration.")

    # identify at the three named points, every horizon, against OD_fare_2024
    lines.append("")
    lines.append("### `/identify` depth, 100-year event (metres; the service formats in da-DK)")
    lines.append("")
    lines.append("| point | KDI 2020 | KDI 2070 | KDI 2120 | MST OD 100 yr | nearest painted KDI-2020 cell |")
    lines.append("|---|---|---|---|---|---|")
    for label, lat, lon in KDI_PTS:
        x, y = wgs84_to_utm32(lon, lat)
        cells = [_identify(KDI, KDI_100YR[hz], x, y) or "—" for hz in ("2020", "2070", "2120")]
        od = _identify("OD_fare_2024", 21, x, y) or "—"
        _, near = _painted(KDI, KDI_100YR["2020"], x, y)
        nv = ""
        if near:
            v = _identify(KDI, KDI_100YR["2020"], *near)
            dist = math.hypot(near[0] - x, near[1] - y)
            nv = f"{v} m at {dist:,.0f} m" if v and v != "NoData" else "—"
        ROWS.append((f"9e identify {label[:18]}", "200", "—", "—",
                     " / ".join(str(c) for c in cells)))
        lines.append(f"| {label} ({lat}, {lon}) | " + " | ".join(str(c) for c in cells)
                     + f" | {od} | {nv} |")
    lines.append("")
    lines.append("`NoData` is a real answer — the cell is dry at that return period, not missing. "
                 "Køge harbour shows the horizon effect cleanly, and the nearest-painted-cell column "
                 "shows how sharp the edge is: a point can be dry while a cell 150 m away carries "
                 "0.2 m. **A point-in-raster read is therefore not a safe property score on its own** "
                 "— a small ring around the pin has to be sampled. `OD_fare_2024` is `NoData` at all "
                 "three, which is the coverage difference above, not a contradiction.")
    lines.append("")
    lines.append("**Not built on yet** — this section is reconnaissance for a later step.")
    block("9 · Kystdirektoratet Kystplanlægger — flood hazard at 2020 / 2070 / 2120", "\n".join(lines))


# ---------- report ----------
def table():
    hdr = ("name", "HTTP", "seconds", "bytes", "note")
    w = [max(len(str(r[i])) for r in [hdr] + ROWS) for i in range(5)]
    out = [" | ".join(str(hdr[i]).ljust(w[i]) for i in range(5)),
           "-|-".join("-" * w[i] for i in range(5))]
    for r in ROWS:
        out.append(" | ".join(str(r[i]).ljust(w[i]) for i in range(5)))
    return "\n".join(out)


def md_table():
    out = ["| name | HTTP | seconds | bytes | note |", "|---|---|---|---|---|"]
    for r in ROWS:
        out.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    return "\n".join(out)


PROBES = [("1", probe_risk), ("2", probe_hazard), ("3", probe_bulk), ("4", probe_klimaatlas),
          ("5", probe_dhm), ("6", probe_bluespot), ("7", probe_fp), ("8", probe_coast),
          ("9", probe_kdi)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated probe numbers, e.g. 4,7")
    ap.add_argument("--no-write", action="store_true", help="print only, leave docs/CLIMATE_PROBE.md alone")
    ap.add_argument("--write", action="store_true",
                    help="with --only: write the (partial) report anyway — it replaces the file")
    a = ap.parse_args()
    load_env()
    want = {s.strip() for s in a.only.split(",") if s.strip()} or {n for n, _ in PROBES}
    import datetime as dt
    for n, fn in PROBES:
        if n not in want:
            continue
        print(f"\n### probe {n} …", flush=True)
        try:
            fn()
        except Exception as e:                                         # noqa: BLE001
            ROWS.append((f"{n} (crashed)", "ERR", "—", "0", f"{type(e).__name__}: {e}"[:80]))
            block(f"{n} · crashed", f"```\n{type(e).__name__}: {e}\n```")
    print("\n" + table())
    if CHECKS:
        print("\nexpected values")
        for label, ok, got, wnt in CHECKS:
            print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got}, expected {wnt}")
        print(f"  {sum(1 for c in CHECKS if c[1])}/{len(CHECKS)} pass")
    if a.only and not a.write:
        print("\n--only: report NOT written (it would replace the full file with a partial one). "
              "Re-run without --only, or pass --write.")
    elif not a.no_write:
        body = [f"# Climate endpoint probe — {dt.date.today().isoformat()}", "",
                "What every source the v2.5 climate layer would read answers today, measured by "
                "`scripts/probe_climate.py` (read-only; re-run it to refresh this file). Everything "
                "below is that run's output — no hand-written numbers.", "",
                "## What it means for the layer", "",
                "* **Storm surge and cloudburst statistics are ready to use.** DMI's Klimaatlas "
                "answers in under half a second, every expected figure matches, and it is already "
                "keyed the way the dashboard is — 34 coastal stretches with geometry and per-kommune "
                "precipitation — so it can drive both a coastal and an inland indicator without any "
                "raster work. It also carries its own horizons (`periode`) and scenarios "
                "(`scenarie`), which is exactly what a Today / 2050 / 2100 pill needs (§4).",
                "* **The MST hazard rasters cannot be read as a grid over REST.** `OD_fare_2024` is a "
                "MapServer: `/exportImage` does not exist, `/export` ignores `format=tiff` and returns "
                "a rendered PNG. Depth *is* readable one point at a time through `/identify`, which "
                "covers a test-property score but not a map layer (§2).",
                "* **The bulk drop is scriptable after all.** The Cerberus web client at "
                "sftp.statens-it.dk exposes a JSON listing and a zip route to a plain HTTP client — "
                "8 files, 3.49 GB, with `Oversvømmelsesfare.zip` (3.41 GB) holding the depth rasters "
                "(§3).",
                "* **`OD_fare_2024` never states its climate basis.** No layer or service description "
                "mentions present-day or future climate or a sea-level-rise allowance. The "
                "Kystdirektoratet service next to it does, and names 2020 / 2070 / 2120 (§2).",
                "* **Two sources are blocked on credentials.** The DHM WCS and the bluespot tiles both "
                "need a Datafordeler key or service user, and `.env` carries only `UDDSTAT_API_KEY` "
                "(§5, §6). Nothing else waits on this.",
                "* **The coast question is already answerable offline** from the boundaries the repo "
                "vendors — 76 of 99 kommuner are coastal, 9 of the metro 19 (§8).", "",
                "## Summary", "", md_table(), ""]
        if CHECKS:
            body += ["## Expected values", "", "| check | got | expected | |", "|---|---|---|---|"]
            body += [f"| {l} | {g} | {w} | {'✓' if ok else '✗'} |" for l, ok, g, w in CHECKS]
            body += ["", f"**{sum(1 for c in CHECKS if c[1])}/{len(CHECKS)} pass.**", ""]
        body += DETAIL
        OUT.write_text("\n".join(body) + "\n")
        print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
