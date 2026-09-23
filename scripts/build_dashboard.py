#!/usr/bin/env python3
"""Assemble the self-contained dashboard: dist/index.html.

Inlines src/style.css, vendored Leaflet, src/app.js and the processed data
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(PROC / "makro.json"))
    ap.add_argument("--market", default=str(PROC / "market.json"))
    ap.add_argument("--portfolio", default=str(PROC / "portfolio.json"))
    ap.add_argument("--cph", default=str(PROC / "cph.json"))
    ap.add_argument("--out", default=str(ROOT / "dist" / "index.html"))
    args = ap.parse_args()

    makro = load(pathlib.Path(args.data)) or {}
    market = load(pathlib.Path(args.market)) or {}
    portfolio = load(pathlib.Path(args.portfolio))
    cph = load(pathlib.Path(args.cph))
    micro_idx = load(PROC / "micro" / "index.json")
    infra = load(ROOT / "data" / "geo" / "infra_projects.geojson")
    infra_index = load(PROC / "infra_index.json")
    public_index = load(PROC / "public_index.json")
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
        "public": {"areas": public_index["areas"], "built": public_index["built"], "kommuner": public_index["kommuner"],
                   "recent_years": public_index["recent_years"]} if public_index else None,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</script", "<\\/script")
    html = (SRC / "index.html").read_text(encoding="utf-8")
    html = (html.replace("{{LEAFLET_CSS}}", (SRC / "vendor" / "leaflet.css").read_text(encoding="utf-8"))
                .replace("{{APP_CSS}}", (SRC / "style.css").read_text(encoding="utf-8"))
                .replace("{{LEAFLET_JS}}", (SRC / "vendor" / "leaflet.js").read_text(encoding="utf-8"))
                .replace("{{APP_JS}}", (SRC / "app.js").read_text(encoding="utf-8"))
                .replace("{{DATA}}", payload)
                .replace("{{BUILT}}", built))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    # the infrastructure layer is inlined in the page, and also served as files so it can be reused
    for src in (ROOT / "data" / "geo" / "infra_projects.geojson", PROC / "infra_index.json"):
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
    if micro_idx:
        import shutil
        md = out.parent / "micro"; md.mkdir(exist_ok=True)
        for f in (PROC / "micro").glob("*.json"):
            shutil.copy(f, md / f.name)
        print(f"copied {len(list(md.glob('*.json')))} micro files → {md}")
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB) · {len(data['municipalities'])} municipalities · {len(data['areas'])} areas")


if __name__ == "__main__":
    main()
