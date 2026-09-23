#!/usr/bin/env python3
"""Download the two raw inputs of the Services layer.

  data/raw/services/denmark-latest.osm.pbf   OpenStreetMap, Geofabrik extract (~495 MB)
  data/raw/services/rejseplanen_gtfs.zip     Rejseplanen static GTFS (~55 MB)
  data/raw/services/manifest.json            what was fetched, when, from where, how big

Both are free and need no key. Neither is committed — `data/raw/services/` is
gitignored; the *processed* output of build_services.py is what ships.

A file younger than --max-age days (default 7) is left alone, so re-running this
before a build is cheap. `--force` downloads regardless.

Usage:
  python3 scripts/fetch_services.py                 # both, if stale
  python3 scripts/fetch_services.py --only gtfs     # one of osm|gtfs
  python3 scripts/fetch_services.py --force
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "services"
MANIFEST = RAW / "manifest.json"
UA = {"User-Agent": "am-dashboard-dk/services (+https://github.com/real-estate-war-lord/am-dashboard-dk)"}

SOURCES = {
    "osm": {
        "url": "https://download.geofabrik.de/europe/denmark-latest.osm.pbf",
        "file": "denmark-latest.osm.pbf",
        "name": "OpenStreetMap — Denmark extract (Geofabrik)",
        "licence": "ODbL 1.0 — © OpenStreetMap contributors, data processed by Geofabrik GmbH",
    },
    "gtfs": {
        "url": "https://www.rejseplanen.info/labs/GTFS.zip",
        "file": "rejseplanen_gtfs.zip",
        "name": "Rejseplanen — static GTFS",
        "licence": "Attribution: Rejseplanen (see docs/SERVICES.md — licence text unconfirmed)",
    },
}


def log(*a):
    print(*a, flush=True)


def load_manifest():
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except ValueError:
            log("  ⚠ manifest.json is unreadable — treating every file as unknown")
    return {"sources": {}}


def age_days(key, entry, path):
    """How old the local copy is, in days, or None when there is no local copy.

    The manifest's own `fetched` stamp wins; a file that is on disk without a
    manifest entry falls back to its mtime, so a copy placed there by hand is
    still recognised as fresh rather than re-downloaded."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    stamp = (entry or {}).get("fetched")
    if stamp:
        try:
            return (dt.datetime.now(dt.timezone.utc)
                    - dt.datetime.fromisoformat(stamp)).total_seconds() / 86400
        except ValueError:
            pass
    return (time.time() - path.stat().st_mtime) / 86400


def download(url, dest):
    """Stream to a .part file, then move into place — a killed run leaves no
    half-written pbf that the next run would mistake for a complete one."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("content-length") or 0)
        got = 0
        nxt = 10
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 / total
                if pct >= nxt:
                    log(f"    {pct:5.1f}%  {got/1e6:7.1f} / {total/1e6:.1f} MB")
                    nxt += 10
    if total and got != total:
        tmp.unlink(missing_ok=True)
        raise IOError(f"short read: {got} of {total} bytes")
    tmp.replace(dest)
    secs = time.time() - t0
    log(f"  · {dest.name}: {got/1e6:.1f} MB in {secs:.0f}s ({got/1e6/max(secs, 1e-9):.1f} MB/s)")
    return got, secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SOURCES), help="fetch just one source")
    ap.add_argument("--force", action="store_true", help="download even if the copy is fresh")
    ap.add_argument("--max-age", type=float, default=7.0,
                    help="days before a local copy counts as stale (default 7)")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    man = load_manifest()
    man.setdefault("sources", {})
    keys = [args.only] if args.only else list(SOURCES)
    failed = []

    for key in keys:
        src = SOURCES[key]
        dest = RAW / src["file"]
        entry = man["sources"].get(key)
        age = age_days(key, entry, dest)
        if age is not None and age < args.max_age and not args.force:
            log(f"{key}: {dest.name} is {age:.1f} days old (< {args.max_age:g}) — skipping "
                f"[--force to download anyway]")
            continue
        log(f"{key}: {src['url']}")
        if age is not None:
            log(f"  · local copy is {age:.1f} days old — refreshing")
        try:
            size, secs = download(src["url"], dest)
        except (urllib.error.URLError, IOError, TimeoutError) as e:
            log(f"  ✗ {key} failed: {type(e).__name__}: {e}")
            failed.append(key)
            continue
        man["sources"][key] = {
            "url": src["url"], "file": src["file"], "name": src["name"],
            "licence": src["licence"], "bytes": size,
            "fetched": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "seconds": round(secs, 1),
        }

    man["written"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"\nwrote {MANIFEST.relative_to(ROOT)}")
    for key in keys:
        e = man["sources"].get(key)
        if e:
            log(f"  {key:5} {e['bytes']/1e6:8.1f} MB  fetched {e['fetched']}")
        else:
            log(f"  {key:5} — never fetched")
    if failed:
        log(f"\n✗ {len(failed)} source(s) failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
