#!/usr/bin/env python3
"""Official Danish flood data (Miljøstyrelsen) → data/raw/flood_hazard/.

Two unrelated pulls behind one script, because they are the same source and the same cycle:

  --areas   the 26 risk areas designated for the EU Floods Directive cycle 2022-2027
            ("plantrin 1", published 2024), from the OD_risikoomraader_2024 MapServer, group
            layer 16. Each sub-layer is one area. Reprojected to EPSG:4326 and joined against
            data/geo/kommuner.geojson so every area carries the kommuner it touches.

  --bulk    Oversvømmelsesfare.zip (3.41 GB) from the Miljøstyrelsen drop on sftp.statens-it.dk.
            The drop is a Cerberus web client: POST /public/op/<id>/get_dir lists it and
            POST /public/op/<id>/zip/<name> streams it. The download resumes with a Range header,
            so an interrupted run can simply be repeated.

    python3 scripts/fetch_flood_official.py --areas
    python3 scripts/fetch_flood_official.py --bulk            # 3.4 GB, resumable
    python3 scripts/fetch_flood_official.py --bulk --list     # list the zip already on disk
    python3 scripts/fetch_flood_official.py --bulk --extract  # pull out the sea 100-yr depth raster
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests missing: pip3 install requests")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "flood_hazard"
GEO = ROOT / "data" / "geo" / "kommuner.geojson"
UA = {"User-Agent": "am-dashboard-dk flood fetch (research; contact via repo)"}

MST = "https://gisportal.mst.dk/server/rest/services/ekstern"
RISK_SERVICE = "OD_risikoomraader_2024"
RISK_GROUP = 16                                   # "Risikoområder 2024"
DESIGNATION = "Floods Directive 2024"
EXPECT_AREAS = 26
DESIGNATION_KOMMUNER = 51                         # the figure the designation text states
# A kommune counts as designated when it holds at least this much of a risk area. Any touch at all
# gives 56 kommuner; five of them (Rødovre 0.05, Albertslund 0.06, Høje-Taastrup 0.27, Egedal 0.33,
# Brøndby 0.71 km²) only clip an edge. Excluding them reproduces the designation's 51 exactly, and
# the cut sits in a real gap in the distribution — the next kommune up holds 1.82 km².
MIN_AREA_KM2 = 1.0

SFTP_HOST = "https://sftp.statens-it.dk"
SFTP_FID = "sudeyofd-echpkegqfxhbg"
BULK_NAME = "Oversvømmelsesfare.zip"
BULK_INNER = "Oversvømmelsesfare.data.zip"   # the Cerberus zip route wraps the file in a zip
BULK_BYTES = 3_410_619_711
CHUNK = 8 << 20


# ---------- a. risk areas ----------
def sub_layers():
    d = requests.get(f"{MST}/{RISK_SERVICE}/MapServer", params={"f": "json"},
                     headers=UA, timeout=120).json()
    byid = {L["id"]: L for L in d["layers"]}
    group = byid.get(RISK_GROUP) or {}
    return [(i, byid[i]["name"]) for i in group.get("subLayerIds", []) if i in byid]


def fetch_area(layer_id):
    r = requests.get(f"{MST}/{RISK_SERVICE}/MapServer/{layer_id}/query",
                     params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson"},
                     headers=UA, timeout=300)
    r.raise_for_status()
    return r.json().get("features", [])


def load_kommuner():
    from shapely.geometry import shape
    gj = json.loads(GEO.read_text())
    out = []
    for f in gj["features"]:
        p = f["properties"]
        out.append((str(p.get("kode") or p.get("kommunekode") or "").zfill(4),
                    p.get("navn") or p.get("name") or "", shape(f["geometry"]).buffer(0)))
    return out


def do_areas(write=True):
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union
        from shapely.strtree import STRtree
    except ImportError:
        sys.exit("shapely missing: pip3 install shapely")
    layers = sub_layers()
    print(f"{RISK_SERVICE} group {RISK_GROUP}: {len(layers)} sub-layers "
          f"(expected {EXPECT_AREAS})")
    if len(layers) != EXPECT_AREAS:
        print(f"  note: the service now publishes {len(layers)}, not {EXPECT_AREAS}")
    koms = load_kommuner()
    kgeoms = [g for _, _, g in koms]
    tree = STRtree(kgeoms)
    feats, rows = [], []
    for lid, name in layers:
        got = fetch_area(lid)
        if not got:
            print(f"  ! layer {lid} {name}: no features")
            continue
        geom = unary_union([shape(f["geometry"]).buffer(0) for f in got if f.get("geometry")])
        area_id = f"OD2024-{lid}"
        area_name = re.sub(r"^Risikoområde\s+", "", name).strip()
        shares = {}
        for j in tree.query(geom):
            if not kgeoms[j].intersects(geom):
                continue
            inter = kgeoms[j].intersection(geom)
            if not inter.is_empty:
                shares[koms[j][0]] = round(_utm_area_km2(inter), 3)
        hits = sorted(c for c, a in shares.items() if a >= MIN_AREA_KM2)
        marginal = sorted(c for c, a in shares.items() if a < MIN_AREA_KM2)
        props = {"area_id": area_id, "area_name": area_name, "designation": DESIGNATION,
                 "layer_id": lid, "parts": len(got), "kommuner": hits,
                 "kommuner_marginal": marginal, "kommune_km2": shares,
                 "area_km2": round(_utm_area_km2(geom), 2)}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": json.loads(json.dumps(geom.__geo_interface__))})
        rows.append(props)
        print(f"  {area_id:<12} {area_name:<26} {props['area_km2']:>8,.1f} km²  "
              f"{len(hits):>2} kommuner  {','.join(hits)}"
              + (f"  (+{len(marginal)} marginal)" if marginal else ""))
    all_koms = sorted({c for r in rows for c in r["kommuner"]})
    marg = sorted({c for r in rows for c in r["kommuner_marginal"]} - set(all_koms))
    byc = {c: n for c, n, _ in koms}
    print(f"\n{len(rows)} areas · {sum(r['area_km2'] for r in rows):,.1f} km² total · "
          f"flood_risk_area = true for {len(all_koms)} kommuner "
          f"(≥ {MIN_AREA_KM2} km² inside a designated area)")
    print("  " + ", ".join(f"{byc.get(c, c)} ({c})" for c in all_koms))
    if marg:
        mk = {}
        for r in rows:
            for c, a in r["kommune_km2"].items():
                if c in marg:
                    mk[c] = mk.get(c, 0) + a
        print(f"\n  {len(marg)} kommuner touch a risk area but hold less than {MIN_AREA_KM2} km² "
              "of it — flagged false, listed for the record:")
        print("  " + ", ".join(f"{byc.get(c, c)} ({c}) {mk[c]:.2f} km²" for c in marg))
    total = len(all_koms) + len(marg)
    if len(all_koms) == DESIGNATION_KOMMUNER:
        print(f"\n  ✓ {len(all_koms)} matches the designation text; any-touch would give {total}")
    else:
        print(f"\n  ⚠ the designation text states {DESIGNATION_KOMMUNER} kommuner, this join gives "
              f"{len(all_koms)} ({total} on any touch) — see docs/CLIMATE_BUILD_LOG.md")
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "risk_areas_2024.geojson").write_text(json.dumps(
            {"type": "FeatureCollection",
             "meta": {"fetched": dt.date.today().isoformat(), "service": RISK_SERVICE,
                      "group": RISK_GROUP, "designation": DESIGNATION, "areas": len(rows),
                      "kommuner": all_koms, "kommuner_marginal": marg,
                      "min_area_km2": MIN_AREA_KM2,
                      "crs": "EPSG:4326 (from EPSG:3044/25832)"},
             "features": feats}, ensure_ascii=False))
        print(f"wrote {(OUT / 'risk_areas_2024.geojson').relative_to(ROOT)} "
              f"({(OUT / 'risk_areas_2024.geojson').stat().st_size / 1e6:.1f} MB)")
    return rows, all_koms


_A, _F, _K0, _LON0 = 6378137.0, 1 / 298.257222101, 0.9996, math.radians(9.0)


def wgs84_to_utm32(lon, lat, z=None):
    e2 = _F * (2 - _F); ep2 = e2 / (1 - e2)
    phi, lam = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2; c = ep2 * math.cos(phi) ** 2
    a1 = (lam - _LON0) * math.cos(phi)
    m = _A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
              - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
              + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
              - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = _K0 * n * (a1 + (1 - t + c) * a1 ** 3 / 6
                   + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * a1 ** 5 / 120) + 500000.0
    y = _K0 * (m + n * math.tan(phi) * (a1 ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a1 ** 4 / 24
               + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * a1 ** 6 / 720))
    return x, y


def _utm_area_km2(geom):
    from shapely.ops import transform
    return transform(wgs84_to_utm32, geom).area / 1e6


# ---------- b. the bulk hazard drop ----------
def bulk_session():
    s = requests.Session()
    folder = f"{SFTP_HOST}/public/folder/{SFTP_FID}/"
    h = s.get(folder, headers=UA, timeout=120)
    tok = (re.search(r'name="csrftoken" content="([^"]+)"', h.text) or [None, ""])[1]
    return s, folder, tok


def bulk_listing(s, folder, tok):
    r = s.post(f"{SFTP_HOST}/public/op/{SFTP_FID}/get_dir",
               data={"sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 1000, "cd": "/",
                     "csrftoken": tok},
               headers={**UA, "X-Requested-With": "XMLHttpRequest", "Referer": folder}, timeout=120)
    r.raise_for_status()
    return r.json().get("aaData", [])


def do_bulk_download():
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / BULK_NAME
    s, folder, tok = bulk_session()
    files = bulk_listing(s, folder, tok)
    want = next((f for f in files if f["name"] == BULK_NAME), None)
    if not want:
        sys.exit(f"{BULK_NAME} is not in the drop any more; it holds: "
                 + ", ".join(f['name'] for f in files))
    size = want["size"]
    print(f"{BULK_NAME}: {size:,} B on the server (expected {BULK_BYTES:,})")
    if size != BULK_BYTES:
        print(f"  ⚠ size differs from the probed {BULK_BYTES:,} — the drop was republished")
    have = dest.stat().st_size if dest.exists() else 0
    if have >= size:
        print(f"  already complete on disk: {have:,} B")
        return dest
    t0 = time.time()
    print(f"  resuming from {have:,} B ({100 * have / size:.1f} %)")
    r = s.post(f"{SFTP_HOST}/public/op/{SFTP_FID}/zip/{BULK_NAME}",
               data={"cd": "/", "ID": BULK_NAME, "zipname": BULK_NAME, "csrftoken": tok},
               headers={**UA, "Referer": folder, **({"Range": f"bytes={have}-"} if have else {})},
               timeout=600, stream=True)
    if have and r.status_code != 206:
        print(f"  server ignored the Range request (HTTP {r.status_code}) — restarting from 0")
        have, mode = 0, "wb"
    else:
        mode = "ab" if have else "wb"
    last = time.time()
    with dest.open(mode) as fh:
        for chunk in r.iter_content(CHUNK):
            fh.write(chunk)
            have += len(chunk)
            if time.time() - last > 20:
                el = time.time() - t0
                print(f"    {have:,} / {size:,} B  ({100 * have / size:5.1f} %)  "
                      f"{have / 1e6 / max(el, 1):.1f} MB/s", flush=True)
                last = time.time()
    got = dest.stat().st_size
    print(f"  {got:,} B in {time.time() - t0:.0f} s")
    return unwrap(dest, size)


def unwrap(dest, listed_size):
    """The /zip/ route returns an archive *containing* the file, so unwrap it once.

    The outer archive is a few MB smaller than the listing says, because it deflates the inner
    zip a little — so the download is verified by reading the central directory and comparing the
    *inner* entry's size, not by counting the bytes that came down the wire."""
    inner = OUT / BULK_INNER
    if inner.exists() and inner.stat().st_size == BULK_BYTES:
        print(f"  {BULK_INNER}: already unwrapped, {inner.stat().st_size:,} B")
        return inner
    try:
        with zipfile.ZipFile(dest) as z:
            names = z.infolist()
    except zipfile.BadZipFile:
        sys.exit(f"{dest.name} is not a readable zip — the download is incomplete, rerun to resume")
    if len(names) == 1 and names[0].filename.lower().endswith(".zip"):
        e = names[0]
        print(f"  unwrapping: the outer archive holds one entry, {e.filename} ({e.file_size:,} B)")
        with zipfile.ZipFile(dest) as z, z.open(e) as src, inner.open("wb") as fh:
            while True:
                b = src.read(CHUNK)
                if not b:
                    break
                fh.write(b)
        got = inner.stat().st_size
        print(f"  {BULK_INNER}: {got:,} B — "
              + ("matches the published size" if got == BULK_BYTES
                 else f"⚠ expected {BULK_BYTES:,}"))
        dest.unlink()                       # 3.4 GB of wrapper, no reason to keep it
        print(f"  removed the wrapper {dest.name}")
        return inner
    print(f"  the archive holds {len(names)} entries — using it directly")
    return dest


def _tiff_info(path_or_fh, name):
    """CRS / pixel size / extent / nodata from the GeoTIFF tags, without reading the pixels."""
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(path_or_fh)
        t = im.tag_v2
        scale = t.get(33550)                       # ModelPixelScale
        tie = t.get(33922)                         # ModelTiepoint
        keys = t.get(34735)                        # GeoKeyDirectory
        nodata = t.get(42113)
        epsg = None
        if keys:
            for i in range(4, len(keys), 4):
                if keys[i] in (3072, 2048):        # Projected / Geographic CS
                    epsg = keys[i + 3]
        info = {"file": name, "size_px": im.size, "mode": im.mode,
                "pixel_size_m": tuple(round(v, 4) for v in scale[:2]) if scale else None,
                "epsg": epsg, "nodata": nodata,
                "compression": t.get(259)}
        if scale and tie:
            x0, y0 = tie[3], tie[4]
            info["extent"] = (round(x0), round(y0 - im.size[1] * scale[1]),
                              round(x0 + im.size[0] * scale[0]), round(y0))
        return info
    except Exception as e:                                             # noqa: BLE001
        return {"file": name, "error": f"{type(e).__name__}: {e}"}


# the sea 100-year depth raster, and only it: _hav_1000år and _hav_10000år must not match
SEA100 = re.compile(r"[/_]hav[/_].*[_]100\s*år\.tif$|[/_]H100[^0-9]", re.I)


def do_bulk_list(extract=False):
    dest = OUT / BULK_INNER
    if not dest.exists():
        dest = OUT / BULK_NAME
        if not dest.exists():
            sys.exit(f"{(OUT / BULK_NAME).relative_to(ROOT)} is not on disk — run --bulk first")
        dest = unwrap(dest, BULK_BYTES)
    with zipfile.ZipFile(dest) as z:
        names = z.infolist()
        print(f"{dest.name}: {len(names)} entries, "
              f"{sum(i.file_size for i in names) / 1e9:.2f} GB uncompressed")
        for i in sorted(names, key=lambda i: -i.file_size)[:40]:
            print(f"  {i.file_size / 1e6:>10,.1f} MB  {i.filename}")
        sea = [i for i in names if SEA100.search(i.filename) and i.filename.lower().endswith((".tif", ".tiff"))]
        print(f"\nsea 100-year depth raster(s): {len(sea)}")
        for i in sea:
            print(f"  {i.file_size / 1e6:,.1f} MB  {i.filename}")
        if extract and sea:
            meta = []
            for i in sea:
                target = OUT / Path(i.filename).name
                if not target.exists() or target.stat().st_size != i.file_size:
                    print(f"  extracting {i.filename} → {target.relative_to(ROOT)}")
                    with z.open(i) as src, target.open("wb") as fh:
                        while True:
                            b = src.read(CHUNK)
                            if not b:
                                break
                            fh.write(b)
                info = _tiff_info(target, target.name)
                info["bytes"] = target.stat().st_size
                meta.append(info)
                print("   ", json.dumps(info, ensure_ascii=False))
            (OUT / "sea100_meta.json").write_text(json.dumps(
                {"fetched": dt.date.today().isoformat(), "zip": BULK_NAME, "rasters": meta},
                ensure_ascii=False, indent=1))
            print(f"wrote {(OUT / 'sea100_meta.json').relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--areas", action="store_true", help="the 26 designated risk areas")
    ap.add_argument("--bulk", action="store_true", help="download Oversvømmelsesfare.zip (3.4 GB)")
    ap.add_argument("--list", action="store_true", help="with --bulk: list the zip on disk")
    ap.add_argument("--extract", action="store_true", help="with --bulk: extract the sea 100-yr raster")
    ap.add_argument("--check", action="store_true", help="with --areas: print, write nothing")
    a = ap.parse_args()
    if not (a.areas or a.bulk):
        ap.error("pick --areas and/or --bulk")
    if a.areas:
        do_areas(write=not a.check)
    if a.bulk:
        if not (a.list or a.extract):
            do_bulk_download()
        do_bulk_list(extract=a.extract)


if __name__ == "__main__":
    main()
