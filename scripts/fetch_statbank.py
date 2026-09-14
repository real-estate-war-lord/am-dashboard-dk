#!/usr/bin/env python3
"""Generic fetcher for Statistics Denmark's StatBank API and its hosted
sub-databases (s20 = Finans Danmark Boligmarkedsstatistik, s30 = Københavns
Kommune). No API key needed.

Reads config/indicators.json, pulls every table listed under `indicators[].sources`
(db in "", "s20", "s30") and `macro[]`, and writes:
  data/raw/<db>_<TABLE>_<YYYY-MM-DD>.csv   (semicolon CSV, value CODES; labels live in the .meta.json)
  data/raw/<db>_<TABLE>.meta.json          (tableinfo: variables, updated, latest period)

Usage:
  python scripts/fetch_statbank.py                 # everything
  python scripts/fetch_statbank.py --table BM011   # one table
  python scripts/fetch_statbank.py --dry-run       # print requests only
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
CFG = ROOT / "config" / "indicators.json"
RAW = ROOT / "data" / "raw"
API = "https://api.statbank.dk/v1"
UA = {"User-Agent": "am-dashboard-dk/0.1", "Content-Type": "application/json"}


def base(db: str) -> str:
    return f"{API}/{db}" if db else API


def tableinfo(db: str, table: str) -> dict:
    url = f"{base(db)}/tableinfo/{table}?lang=en&format=JSON"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def data(db: str, table: str, variables: dict, fmt: str = "CSV") -> str:
    body = {
        "table": table,
        "format": fmt,
        "lang": "en",
        "valuePresentation": "Code",
        # "SUM" = leave the variable out so the API returns its total (needs elimination=true)
        "variables": [{"code": k, "values": v} for k, v in variables.items() if v != ["SUM"]],
    }
    req = urllib.request.Request(f"{base(db)}/data", data=json.dumps(body).encode("utf-8"),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode("utf-8-sig")


def jobs(cfg: dict):
    for ind in cfg["indicators"]:
        for s in ind["sources"]:
            if s.get("db") in ("", "s20", "s30") and "vars" in s:
                yield s.get("db", ""), s["table"], s["vars"], ind["key"], s.get("pull")
    for m in cfg["macro"]:
        yield m.get("db", ""), m["table"], m["vars"], m["key"], m.get("pull")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CFG.read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    seen = set()
    failures = []
    for db, table, variables, key, pull in jobs(cfg):
        if args.table and table != args.table:
            continue
        sig = (db, table, json.dumps(variables, sort_keys=True))
        if sig in seen:
            continue
        seen.add(sig)
        tag = f"{db or 'dst'}_{pull or table}"
        if any(v.startswith("TODO") for vals in variables.values() for v in vals):
            print(f"→ {tag} ({key}) skipped — unresolved TODO codes"); continue
        print(f"→ {tag} ({key}) vars={variables}")
        if args.dry_run:
            continue
        try:
            meta = tableinfo(db, table)
            (RAW / f"{db or 'dst'}_{table}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            csv = data(db, table, variables)
            (RAW / f"{tag}_{today}.csv").write_text(csv)
            print(f"  ok · updated {meta.get('updated')} · {csv.count(chr(10))} rows")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            print(f"  HTTP {e.code}: {msg}", file=sys.stderr)
            failures.append((tag, e.code, msg))
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}", file=sys.stderr)
            failures.append((tag, None, str(e)))
        time.sleep(0.3)
    if failures:
        print("\nFAILED:", file=sys.stderr)
        for f in failures:
            print("  ", f, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
