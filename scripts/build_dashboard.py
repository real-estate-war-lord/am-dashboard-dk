#!/usr/bin/env python3
"""Assemble the self-contained dashboard: dist/index.html.

Inlines src/style.css, vendored Leaflet, src/testprop.js, src/app.js and the data
(data/processed/makro.json + market.json, optional portfolio.json) into the
template src/index.html — one file that opens from disk or GitHub Pages.

Usage: python scripts/build_dashboard.py [--data path/to/makro.json] [--out dist/index.html]
"""
import argparse
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PROC = ROOT / "data" / "processed"


def load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def kommuner_lookup(out_dir: pathlib.Path):
    """dist/geo/kommuner_lookup.json — simplified kommune rings for the test-property pin.

    Postal codes can cross a kommune border, so the pin asks these polygons which
    municipality a point is really in. Holes are kept: Frederiksberg is a hole in
    København, and dropping it would put every Frederiksberg pin in København.
    The page fetches this lazily, the first time a pin is dropped.
    """
    src = ROOT / "data" / "geo" / "kommuner.geojson"
    if not src.exists():
        print("  ⚠ data/geo/kommuner.geojson missing — no kommune lookup (pins fall back to the postal code)")
        return
    gj = load(src)
    try:
        from shapely.geometry import mapping, shape
        simplify = 0.0005
    except ImportError:
        shape = None
        simplify = None
        print("  · shapely not installed — kommune rings shipped unsimplified")
    rows = []
    for f in gj.get("features", []):
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        if shape is not None:
            g = shape(geom).simplify(simplify, preserve_topology=True)
            if not g.is_empty:
                geom = mapping(g)
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        out, s_, w_, n_, e_ = [], 90.0, 180.0, -90.0, -180.0
        for poly in polys:
            rings = []
            for ring in poly:                      # [outer, hole, hole, ...]
                pts = [[round(y, 5), round(x, 5)] for x, y in ring]
                if len(pts) >= 4:
                    rings.append(pts)
            if not rings:
                continue
            for lat, lon in rings[0]:
                s_, n_ = min(s_, lat), max(n_, lat)
                w_, e_ = min(w_, lon), max(e_, lon)
            out.append(rings)
        if out:
            rows.append({"code": props.get("kode"), "name": props.get("navn"),
                         "bb": [s_, w_, n_, e_], "polys": out})
    gd = out_dir / "geo"
    gd.mkdir(parents=True, exist_ok=True)
    dest = gd / "kommuner_lookup.json"
    dest.write_text(json.dumps({"built": dt.date.today().isoformat(), "source": "DAGI kommuner (DAWA), simplified",
                                "kommuner": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size/1024:.0f} kB) · {len(rows)} kommuner"
          + (f" · simplified {simplify}" if simplify else " · not simplified"))


def check_js(paths):
    """Refuse to inline JavaScript that does not parse.

    Without this `make build` happily writes a dist/index.html whose app.js has a syntax
    error — the page then renders nothing and the build still says it succeeded. node is
    optional: if it is not installed the check is skipped rather than failing the build.
    """
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("  · node not found — skipping the JavaScript syntax check")
        return
    for p in paths:
        if not p.exists():
            continue
        r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"✗ {p.name} does not parse:\n{(r.stderr or r.stdout).strip()}")
    print(f"  · JavaScript parses ({', '.join(p.name for p in paths if p.exists())})")


def climate_payload():
    """What the page needs inline: the indicator index, the per-horizon exposure tables and the
    risk-area names. The zone polygons stay on disk and are fetched per kommune for the viewport.
    `kommune` in `zones` carries only zone_km2, which is what tells the page a file exists."""
    idx = load(PROC / "climate" / "index.json")
    if not idx:
        return None
    zones = {}
    for h in ("today", "2070", "2120"):
        zi = load(PROC / "climate" / f"surge_{h}" / "index.json") or {}
        km = zi.get("kommune") or {}
        zones[h] = {
            "kommune": {k: v.get("zone_km2") for k, v in km.items() if v.get("zone_km2")},
            "postnr": zi.get("postnr") or {},
            "kvarter": zi.get("kvarter") or {},
            "meta": {k: (zi.get("meta") or {}).get(k) for k in
                     ("year", "period", "event", "source", "depth_class", "built", "zone_km2_national")},
        }
    ra = load(PROC / "climate" / "risk_areas.json") or {}
    names, areas = {}, []
    for f in ra.get("features", []):
        pr = f.get("properties") or {}
        areas.append({"id": pr.get("area_id"), "name": pr.get("area_name"), "km2": pr.get("area_km2"),
                      "kommuner": pr.get("kommuner") or []})
        for k in (pr.get("kommuner") or []):
            names.setdefault(k, []).append(pr.get("area_name"))
    return {"meta": idx.get("meta") or {}, "kommune": idx.get("kommune") or {},
            "zones": zones, "risk_names": names, "risk_areas": areas,
            "risk_meta": ra.get("meta") or {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(PROC / "makro.json"))
    ap.add_argument("--market", default=str(PROC / "market.json"))
    ap.add_argument("--portfolio", default=str(PROC / "portfolio.json"))
    ap.add_argument("--cph", default=str(PROC / "cph.json"))
    ap.add_argument("--out", default=str(ROOT / "dist" / "index.html"))
    args = ap.parse_args()

    check_js([SRC / "app.js", SRC / "testprop.js", SRC / "climate_core.js"])
    makro = load(pathlib.Path(args.data)) or {}
    market = load(pathlib.Path(args.market)) or {}
    portfolio = load(pathlib.Path(args.portfolio))
    cph = load(pathlib.Path(args.cph))
    micro_idx = load(PROC / "micro" / "index.json")
    infra = load(ROOT / "data" / "geo" / "infra_projects.geojson")
    infra_index = load(PROC / "infra_index.json")
    public_index = load(PROC / "public_index.json")
    services_index = load(PROC / "services" / "index.json")
    climate = climate_payload()
    built = (makro.get("meta") or {}).get("built") or dt.date.today().isoformat()
    data = {
        "meta": makro.get("meta", {"built": built, "sources": [], "attribution": []}),
        "indicators": makro.get("indicators", []),
        "municipalities": makro.get("municipalities", []),
        "areas": makro.get("areas", []),
        "national": makro.get("national"),
        "macro": market,
        "portfolio": portfolio,
        "cph": cph,
        "micro": micro_idx,
        # infrastructure overlay: only the features meant for the map (scripts/build_infra.py, docs/INFRA.md)
        # every project: the map layer filters on `map`, the Pipeline table lists them all
        "infra": {"features": (infra or {}).get("features", []), "meta": (infra or {}).get("meta")} if infra else None,
        "infra_index": (infra_index or {}).get("areas") if infra_index else None,
        # public buildings: counts per area inline, the buildings themselves loaded on demand (dist/public/<kommune>.json)
        # public buildings: counts per area inline; the school aggregates ride along in the same areas
        # dict (scripts/build_schools.py), while the school records load on demand from schools.json
        "public": {"areas": public_index["areas"], "built": public_index["built"], "kommuner": public_index["kommuner"],
                   "recent_years": public_index["recent_years"],
                   "schools": public_index.get("schools")} if public_index else None,
        # services: the index only (as-of, vocabulary, per-kommune counts + bbox). The points
        # themselves load on demand from dist/services/<kommune>.json for whatever is in view.
        "services": services_index,
        # climate: the indicator index (every indicator x horizon), the per-horizon exposure for
        # kommuner, postal codes and quarters, and the risk-area names. The zone polygons themselves
        # load on demand from dist/climate/surge_<horizon>/<kommune>.json, like services and micro.
        "climate": climate,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</script", "<\\/script")
    html = (SRC / "index.html").read_text(encoding="utf-8")
    html = (html.replace("{{LEAFLET_CSS}}", (SRC / "vendor" / "leaflet.css").read_text(encoding="utf-8"))
                .replace("{{APP_CSS}}", (SRC / "style.css").read_text(encoding="utf-8"))
                .replace("{{LEAFLET_JS}}", (SRC / "vendor" / "leaflet.js").read_text(encoding="utf-8"))
                .replace("{{TESTPROP_JS}}", (SRC / "testprop.js").read_text(encoding="utf-8"))
                .replace("{{CLIMATE_JS}}", (SRC / "climate_core.js").read_text(encoding="utf-8"))
                .replace("{{APP_JS}}", (SRC / "app.js").read_text(encoding="utf-8"))
                .replace("{{DATA}}", payload)
                .replace("{{BUILT}}", built))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    # the infrastructure layer is inlined in the page, and also served as files so it can be reused
    for src in (ROOT / "data" / "geo" / "infra_projects.geojson", PROC / "infra_index.json", PROC / "public_index.json",
                PROC / "schools.json"):
        if src.exists():
            import shutil
            shutil.copy(src, out.parent / src.name)
            print(f"copied {src.name} → {out.parent}")
    # building-level files are loaded on demand by the page (dist/micro/<kommune>.json)
    pub = PROC / "public"
    if pub.exists():
        import shutil
        pd_ = out.parent / "public"; pd_.mkdir(exist_ok=True)
        for f in pub.glob("*.json"):
            shutil.copy(f, pd_ / f.name)
        print(f"copied {len(list(pd_.glob('*.json')))} public-building files → {pd_}")
    srv = PROC / "services"
    if srv.exists():
        import shutil
        sd = out.parent / "services"; sd.mkdir(exist_ok=True)
        for f in srv.glob("*.json"):
            shutil.copy(f, sd / f.name)
        print(f"copied {len(list(sd.glob('*.json')))} services files → {sd}")
    if micro_idx:
        import shutil
        md = out.parent / "micro"; md.mkdir(exist_ok=True)
        for f in (PROC / "micro").glob("*.json"):
            shutil.copy(f, md / f.name)
        print(f"copied {len(list(md.glob('*.json')))} micro files → {md}")
    # climate zones and the climate index, served as files (v2.5 — dist/climate/)
    clim = PROC / "climate"
    if clim.exists():
        import shutil
        cd = out.parent / "climate"; cd.mkdir(exist_ok=True)
        n = 0
        for f in clim.rglob("*.json"):
            t = cd / f.relative_to(clim)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, t)
            n += 1
        print(f"copied {n} climate files → {cd}")
    kommuner_lookup(out.parent)
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB) · {len(data['municipalities'])} municipalities · {len(data['areas'])} areas")


if __name__ == "__main__":
    main()
