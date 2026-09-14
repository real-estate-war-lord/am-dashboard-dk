#!/usr/bin/env python3
"""Discover the BBR GraphQL v3 schema on Datafordeler (needs DATAFORDELER_API_KEY in .env).

Prints the root query fields and, for the dwelling-related types, their fields and
arguments — the input for writing scripts/fetch_bbr.py. Nothing is written to disk
except bbr_schema.json in data/raw/ (no data, just the schema).

Usage: python scripts/bbr_introspect.py
"""
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENDPOINT = "https://graphql.datafordeler.dk/BBR/v3"


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def gql(query, variables=None):
    key = os.environ.get("DATAFORDELER_API_KEY")
    if not key:
        sys.exit("DATAFORDELER_API_KEY missing — put it in .env")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(f"{ENDPOINT}?apiKey={key}", data=body, headers={"Content-Type": "application/json", "User-Agent": "am-dashboard-dk/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


INTROSPECT = """
query { __schema { queryType { name fields { name description args { name type { name kind ofType { name kind ofType { name kind } } } } type { name kind ofType { name kind ofType { name kind } } } } } } }
"""
TYPE_Q = """
query($n: String!) { __type(name: $n) { name kind fields { name description type { name kind ofType { name kind ofType { name kind } } } } inputFields { name type { name kind ofType { name kind ofType { name kind } } } } enumValues { name } } }
"""


def tname(t):
    while t and not t.get("name"):
        t = t.get("ofType")
    return (t or {}).get("name", "?")


def main():
    load_env()
    r = gql(INTROSPECT)
    if "errors" in r:
        print("ERROR:", json.dumps(r["errors"], ensure_ascii=False)[:800]); sys.exit(1)
    fields = r["data"]["__schema"]["queryType"]["fields"]
    print(f"root query fields ({len(fields)}):")
    for f in fields:
        print(f"  {f['name']:32} → {tname(f['type']):32} args: {', '.join(a['name'] + ':' + tname(a['type']) for a in f['args'])}")
    interesting = [f for f in fields if any(k in f["name"].lower() for k in ("bygning", "enhed", "ejendomsrelation", "grund", "opgang"))]
    out = {"root": fields, "types": {}}
    seen = set()
    for f in interesting[:8]:
        tn = tname(f["type"])
        for cand in (tn, f["name"]):
            if cand in seen:
                continue
            t = gql(TYPE_Q, {"n": cand}).get("data", {}).get("__type")
            if not t:
                continue
            seen.add(cand); out["types"][cand] = t
            print(f"\n=== type {t['name']} ({t['kind']})")
            for fl in (t.get("fields") or [])[:80]:
                print(f"    {fl['name']:40} {tname(fl['type'])}")
            for fl in (t.get("inputFields") or [])[:60]:
                print(f"    [in] {fl['name']:36} {tname(fl['type'])}")
            if t.get("enumValues"):
                print("    enum:", ", ".join(e["name"] for e in t["enumValues"][:40]))
        # also dump the args' input types (filters)
        for a in f["args"]:
            an = tname(a["type"])
            if an in seen or an in ("Int", "String", "Boolean", "Float", "ID"):
                continue
            t = gql(TYPE_Q, {"n": an}).get("data", {}).get("__type")
            if not t:
                continue
            seen.add(an); out["types"][an] = t
            print(f"\n=== input {t['name']} ({t['kind']})")
            for fl in (t.get("inputFields") or [])[:60]:
                print(f"    [in] {fl['name']:36} {tname(fl['type'])}")
            if t.get("enumValues"):
                print("    enum:", ", ".join(e["name"] for e in t["enumValues"][:40]))
    (ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "raw" / "bbr_schema.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nschema saved → data/raw/bbr_schema.json")


if __name__ == "__main__":
    main()
