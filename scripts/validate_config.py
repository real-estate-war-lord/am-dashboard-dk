#!/usr/bin/env python3
"""Check every table/variable/value code in config/indicators.json against the
live StatBank tableinfo. Run this FIRST — it tells you which codes to fix before
pulling data. Needs network access to api.statbank.dk (no key).

Usage: python scripts/validate_config.py [--show 20]
"""
import argparse
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statbank_common import cfg  # noqa: E402

API = "https://api.statbank.dk/v1"


def tableinfo(db, table):
    url = f"{API}/{db + '/' if db else ''}tableinfo/{table}?lang=en&format=JSON"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "am-dashboard-dk/0.1"}), timeout=60) as r:
        return json.load(r)


def check(db, table, variables, show, cache):
    key = (db, table)
    if key not in cache:
        try:
            cache[key] = tableinfo(db, table)
        except Exception as e:  # noqa: BLE001
            print(f"✗ {db or 'dst'}/{table}: tableinfo failed: {e}")
            cache[key] = None
    info = cache[key]
    if not info:
        return
    vars_ = {v["id"]: v for v in info.get("variables", [])}
    print(f"• {db or 'dst'}/{table} — updated {info.get('updated')} · vars: {', '.join(vars_)}")
    for var, values in variables.items():
        if var not in vars_:
            print(f"    ✗ variable {var!r} not in table; available: {list(vars_)}")
            continue
        codes = {x["id"]: x["text"] for x in vars_[var]["values"]}
        for val in values:
            if val == "*" or val.startswith("(") or val.startswith("*"):
                continue
            if val not in codes:
                print(f"    ✗ {var}={val!r} not found. First {show} codes:")
                for cid, txt in list(codes.items())[:show]:
                    print(f"        {cid!r:14} {txt}")
            else:
                print(f"    ✓ {var}={val!r} → {codes[val]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()
    c = cfg()
    cache = {}
    for ind in c["indicators"]:
        for s in ind["sources"]:
            if s.get("db") in ("", "s20", "s30") and "vars" in s:
                check(s.get("db", ""), s["table"], s["vars"], args.show, cache)
    for m in c["macro"]:
        check(m.get("db", ""), m["table"], m["vars"], args.show, cache)


if __name__ == "__main__":
    main()
