#!/usr/bin/env python3
"""Storm-surge depth raster → per-kommune zone polygons (build_surge_zones.py --horizon).

Kept apart from build_surge_zones.py because this is the only part of the climate layer that
touches a multi-gigabyte raster, and the part most likely to be rewritten when the 2050 and 2100
horizons arrive.

Reading a 90 287 × 70 503 px float32 GeoTIFF without GDAL or rasterio
---------------------------------------------------------------------
The Miljøstyrelsen raster is LZW-compressed and *tiled* at 128 × 128 px, and Pillow can only
decode it in one piece — 25 GB of float32. Two facts make it tractable anyway:

  1. the tile index (TileOffsets / TileByteCounts) is in the header, so each tile's bytes can be
     read on their own;
  2. 371 707 of the 389 006 tiles are the identical all-nodata tile and compress to exactly the
     same 875 bytes. Skipping every tile of the modal byte count leaves **17 299 tiles, 213 MB**,
     which is the entire flooded extent of Denmark.

Each of those tiles is decoded by wrapping its raw LZW bytes in a minimal one-strip TIFF header
and handing that to Pillow, which is the same libtiff that could not be aimed at a single tile
directly. It costs a few microseconds per tile.

Vectorising: each tile is max-pooled from 5 m to 10 m (max, not nearest — a thin flooded strip
must survive), thresholded per depth class, run-length encoded into rectangles row by row and
dissolved. Tile polygons are then cut against the kommune they fall in and dissolved again, so
shapely never sees more than a few hundred boxes at a time.
"""
import collections
import datetime as dt
import io
import json
import re
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "flood_hazard"
OUT = ROOT / "data" / "processed" / "climate"
BBR = ROOT / "data" / "raw" / "bbr"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_surge_zones import (COORD_DP, DEPTH_CLASSES, DWELLING_BOLIGTYPER,  # noqa: E402
                               DWELLING_STATUS, MIN_PART_M2, SCHEMA, SIMPLIFY_M,
                               SURGE_MIN_HOLE_M2, budget, clean, load_kommuner)

POOL = 2                     # 5 m → 10 m cells, by max
NODATA_FLOOR = -1e30


# ---------- tiled-TIFF reader ----------
def mini_tiff(raw, w, h):
    """One LZW tile wrapped in a one-strip little-endian TIFF, for Pillow to decode."""
    tags = [(256, 3, 1, w), (257, 3, 1, h), (258, 3, 1, 32), (259, 3, 1, 5), (262, 3, 1, 1),
            (273, 4, 1, 0), (277, 3, 1, 1), (278, 4, 1, h), (279, 4, 1, len(raw)),
            (284, 3, 1, 1), (339, 3, 1, 3)]
    n = len(tags)
    data = 8 + 2 + n * 12 + 4
    out = bytearray(struct.pack("<2sHI", b"II", 42, 8))
    out += struct.pack("<H", n)
    for tag, typ, cnt, val in tags:
        if tag == 273:
            val = data
        out += struct.pack("<HHI", tag, typ, cnt)
        out += struct.pack("<I", val) if typ == 4 else struct.pack("<HH", val, 0)
    out += struct.pack("<I", 0)
    out += raw
    return bytes(out)


class TiledFloatTiff:
    def __init__(self, path):
        self.path = path
        im = Image.open(path)
        t = im.tag_v2
        self.w, self.h = im.size
        self.tw, self.th = t[322], t[323]
        self.offsets, self.counts = list(t[324]), list(t[325])
        self.px, self.py = t[33550][0], t[33550][1]
        self.ox, self.oy = t[33922][3], t[33922][4]
        nd = t.get(42113)
        self.nodata = float(str(nd).split(",")[0]) if nd is not None else None
        self.across = -(-self.w // self.tw)
        self.modal = collections.Counter(self.counts).most_common(1)[0][0]
        self.data_tiles = [i for i, c in enumerate(self.counts) if c != self.modal]
        self.fp = open(path, "rb")

    def tile(self, i):
        self.fp.seek(self.offsets[i])
        raw = self.fp.read(self.counts[i])
        a = np.asarray(Image.open(io.BytesIO(mini_tiff(raw, self.tw, self.th))), dtype="float32")
        a = np.where(np.isfinite(a), a, 0.0)
        a[a < NODATA_FLOOR] = 0.0
        if self.nodata is not None and self.nodata > NODATA_FLOOR:
            a[np.isclose(a, self.nodata)] = 0.0
        return a

    def tile_origin(self, i):
        """map coordinates of the tile's top-left corner"""
        r, c = divmod(i, self.across)
        return self.ox + c * self.tw * self.px, self.oy - r * self.th * self.py


def runs(row):
    """[(a, b)] index pairs of True runs in a 1-D boolean row."""
    d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
    return zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0])


def tile_polygons(a, x0, ytop, cell):
    """{depth class: polygon} for one pooled tile."""
    out = {}
    for lo, hi, name in DEPTH_CLASSES:
        m = a > lo
        if hi is not None:
            m &= a <= hi
        if not m.any():
            continue
        boxes = []
        for r in np.nonzero(m.any(axis=1))[0]:
            yt = ytop - r * cell
            for p, q in runs(m[r]):
                boxes.append(box(x0 + p * cell, yt - cell, x0 + q * cell, yt))
        if boxes:
            out[name] = unary_union(boxes)
    return out


# ---------- BBR dwellings ----------
_WKT = re.compile(r"\(([-\d.]+)\s+([-\d.]+)\)")


def dwelling_points(kom):
    """[(x, y)] in EPSG:25832 — BBR dwellings at their building's coordinate.

    The v1.4 definition: Enhed with boligtype 1–5 and status 6 (scripts/build_bbr.py)."""
    bfile, efile = BBR / f"{kom}_bygning.jsonl", BBR / f"{kom}_enhed.jsonl"
    if not (bfile.exists() and efile.exists()):
        return None
    coords = {}
    with bfile.open() as fh:
        for line in fh:
            b = json.loads(line)
            c = (b.get("byg404Koordinat") or {}).get("wkt")
            if c:
                m = _WKT.search(c)
                if m:
                    coords[b["id_lokalId"]] = (float(m.group(1)), float(m.group(2)))
    pts = []
    with efile.open() as fh:
        for line in fh:
            u = json.loads(line)
            if u.get("status") != DWELLING_STATUS:
                continue
            if str(u.get("enh023Boligtype")) not in DWELLING_BOLIGTYPER:
                continue
            p = coords.get(u.get("bygning"))
            if p:
                pts.append(p)
    return pts


# ---------- the build ----------
def do_surge(horizon):
    if horizon != "today":
        sys.exit(f"horizon {horizon!r}: only the Today raster is on disk. The 2050/2100 depth "
                 "grids exist only as rendered layers on the Kystdirektoratet MapServer, which "
                 "cannot hand out a raster (docs/CLIMATE_PROBE.md §9).")
    meta_p = RAW / "sea100_meta.json"
    if not meta_p.exists():
        sys.exit("run scripts/fetch_flood_official.py --bulk --extract first")
    rasters = [r for r in json.loads(meta_p.read_text())["rasters"] if not r.get("error")]
    if not rasters:
        sys.exit(f"no readable raster named in {meta_p.name}")

    koms = load_kommuner()
    bycode = {k["code"]: k for k in koms}
    tree = STRtree([k["geom"] for k in koms])
    prepared = {k["code"]: prep(k["geom"]) for k in koms}
    acc = {k["code"]: collections.defaultdict(list) for k in koms}
    flooded_m2 = 0.0

    for r in rasters:
        t0 = time.time()
        tif = TiledFloatTiff(RAW / r["file"])
        cell = tif.px * POOL
        print(f"  {r['file']}: {tif.w:,} × {tif.h:,} px · {tif.px:g} m · "
              f"{len(tif.counts):,} tiles, {len(tif.data_tiles):,} carry data "
              f"({100 * len(tif.data_tiles) / len(tif.counts):.1f} %) · pooling to {cell:g} m",
              flush=True)
        for n, i in enumerate(tif.data_tiles, 1):
            a = tif.tile(i)
            if not (a > 0).any():
                continue
            hh, ww = a.shape[0] // POOL * POOL, a.shape[1] // POOL * POOL
            a = a[:hh, :ww].reshape(hh // POOL, POOL, ww // POOL, POOL).max(axis=(1, 3))
            flooded_m2 += float((a > 0).sum()) * cell * cell
            x0, ytop = tif.tile_origin(i)
            polys = tile_polygons(a, x0, ytop, cell)
            if not polys:
                continue
            bb = box(x0, ytop - tif.th * tif.py, x0 + tif.tw * tif.px, ytop)
            cand = [koms[j]["code"] for j in tree.query(bb)]
            for name, g in polys.items():
                for code in cand:
                    if not prepared[code].intersects(g):
                        continue
                    cut = g.intersection(bycode[code]["geom"])
                    if not cut.is_empty:
                        acc[code][name].append(cut)
            if n % 4000 == 0:
                print(f"    {n:,}/{len(tif.data_tiles):,} tiles · {time.time() - t0:.0f} s",
                      flush=True)
        print(f"  raster read in {time.time() - t0:.0f} s · "
              f"{flooded_m2 / 1e6:,.1f} km² flooded at 100-year sea level", flush=True)

    zdir = OUT / f"surge_{horizon}"
    zdir.mkdir(parents=True, exist_ok=True)
    for old in zdir.glob("*.json"):
        old.unlink()

    print("  dwellings (BBR boligtype 1–5, status 6) for kommuner with a zone:", flush=True)
    index, written, over = {}, 0, []
    for k in koms:
        code, feats, zone_m2 = k["code"], [], 0.0
        merged = {}
        for lo, hi, name in DEPTH_CLASSES:
            parts = acc[code].get(name)
            if not parts:
                continue
            g = unary_union(parts)
            merged[name] = g
            zone_m2 += g.area
            geom = clean(g, SIMPLIFY_M, min_part_m2=MIN_PART_M2,
                         min_hole_m2=SURGE_MIN_HOLE_M2)
            if geom is not None:
                feats.append({"type": "Feature",
                              "properties": {"depth_class": name, "depth_min_m": lo,
                                             "depth_max_m": hi,
                                             "area_km2": round(g.area / 1e6, 3)},
                              "geometry": geom})
        rec = {"kommune": code, "name": k["name"], "zone_km2": round(zone_m2 / 1e6, 3),
               "dwellings": None, "dwellings_at_risk": None, "surge_dw_pct": None}
        if merged:
            pts = dwelling_points(code)
            if pts is None:
                rec["dwellings_note"] = "no BBR pull for this kommune"
            else:
                z = prep(unary_union(list(merged.values())))
                from shapely.geometry import Point
                at = sum(1 for x, y in pts if z.intersects(Point(x, y)))
                pct = round(100 * at / len(pts), 2) if pts else None
                rec.update(dwellings=len(pts) or None, dwellings_at_risk=at if pts else None,
                           surge_dw_pct=pct)
                if not pts:
                    rec["dwellings_note"] = "BBR pull holds no dwelling for this kommune"
                print(f"    {code} {k['name']:<18} {len(pts):>7,} dwellings · {at:>6,} in the zone "
                      + (f"({pct:.2f} %)" if pct is not None else "(no dwellings)"), flush=True)
        index[code] = rec
        if not feats:
            continue
        doc = {"type": "FeatureCollection",
               "meta": {"hazard": "storm_surge", "horizon": horizon, "kommune": code,
                        "kommune_name": k["name"], "level_cm": None,
                        "depth_class": [c[2] for c in DEPTH_CLASSES],
                        "method": f"Miljøstyrelsen sea 100-year depth raster at {tif.px:g} m, "
                                  f"max-pooled to {cell:g} m, run-length vectorised per depth "
                                  f"class, dissolved, simplified {SIMPLIFY_M:g} m in EPSG:25832, "
                                  f"parts under {MIN_PART_M2} m² and holes under "
                                  f"{SURGE_MIN_HOLE_M2} m² dropped (+0.6 % area), EPSG:4326 at "
                                  f"{COORD_DP} decimals",
                        "source": "Miljøstyrelsen — EU Floods Directive 2022-2027 plantrin 1, "
                                  "Oversvømmelsesfare.zip (Hav, 100 år)",
                        "zone_km2": rec["zone_km2"], "schema": SCHEMA,
                        "updated": dt.date.today().isoformat()},
               "features": feats}
        p = zdir / f"{code}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        written += 1
        if p.stat().st_size / 1e6 > 3.0:
            over.append((code, k["name"], p.stat().st_size / 1e6))

    (zdir / "index.json").write_text(json.dumps(
        {"meta": {"hazard": "storm_surge", "horizon": horizon, "level_cm": None,
                  "depth_class": [c[2] for c in DEPTH_CLASSES], "schema": SCHEMA,
                  "built": dt.date.today().isoformat(),
                  "flooded_km2_total": round(flooded_m2 / 1e6, 1),
                  "dwellings": "BBR Enhed boligtype 1–5 status 6, at the building's coordinate",
                  "method": "point in the dissolved 100-year sea flood zone",
                  "source": "Miljøstyrelsen OD 2022-2027 plantrin 1 × BBR via Datafordeler"},
         "kommune": index}, ensure_ascii=False, separators=(",", ":")))
    print(f"\nwrote {written} kommune zone files + index.json → {zdir.relative_to(ROOT)}")
    top = sorted((r for r in index.values() if r["surge_dw_pct"]),
                 key=lambda r: -r["surge_dw_pct"])[:12]
    print(f"  {'code':<6}{'kommune':<18}{'zone km²':>10}{'dwellings':>11}{'at risk':>9}{'%':>7}")
    for r in top:
        print(f"  {r['kommune']:<6}{r['name']:<18}{r['zone_km2']:>10,.2f}{r['dwellings']:>11,}"
              f"{r['dwellings_at_risk']:>9,}{r['surge_dw_pct']:>7.2f}")
    for code, name, mb in over:
        print(f"  ⚠ {code} {name}: {mb:.2f} MB — over the 3 MB per-file budget")
    budget()
