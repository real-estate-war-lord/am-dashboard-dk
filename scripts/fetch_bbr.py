#!/usr/bin/env python3
"""Pull BBR (Bygnings- og Boligregistret) units and buildings from Datafordeler's GraphQL
service, one municipality at a time, into data/raw/bbr/<kommunekode>_{bygning,enhed}.jsonl.

Needs DATAFORDELER_API_KEY in .env (free key from portal.datafordeler.dk → IT-systemer).
Field names follow the BBR data model (byg…/enh… attributes); `--check` compares them with
the live schema before anything is fetched, so a renamed field is caught up front.

Usage:
  python scripts/fetch_bbr.py --schema               # save the schema (data/raw/bbr_schema.graphql) and list entities
  python scripts/fetch_bbr.py --check                # which of our fields exist on BBR_Enhed / BBR_Bygning
  python scripts/fetch_bbr.py --kommune 0147         # pilot: one municipality (Frederiksberg)
  python scripts/fetch_bbr.py --all                  # every municipality, resumable (skips finished files)
  python scripts/fetch_bbr.py --kommune 0101 --version v1   # try the older entity endpoint
  python scripts/fetch_bbr.py --rest --kommune 0147         # fallback: BBRPublic REST with a tjenestebruger
                                                            # (DATAFORDELER_USER / DATAFORDELER_PASS in .env)
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "bbr"
BASE = "https://graphql.datafordeler.dk/BBR"
REST = "https://services.datafordeler.dk/BBR/BBRPublic/1/rest"
PAGE = 1000
REST_PAGE = 1000
# Hovedstadsområdet: Copenhagen and the contiguous suburban municipalities (19)
METRO = ["0101", "0147", "0151", "0153", "0155", "0157", "0159", "0161", "0163", "0165", "0167", "0169", "0173", "0175", "0183", "0185", "0187", "0190", "0230"]
# --- fields we want (BBR attribute names; verified against the schema by --check) ---
ENHED_FIELDS = ["id_lokalId", "status", "kommunekode", "opgang", "bygning", "adresseIdentificerer",
                "enh020EnhedensAnvendelse", "enh023Boligtype", "enh024KondemneretBoligenhed",
                "enh026EnhedensSamledeAreal", "enh027ArealTilBeboelse", "enh031AntalVaerelser",
                "enh045Udlejningsforhold", "enh048GodkendtTomBolig"]
BYGNING_FIELDS = ["id_lokalId", "status", "kommunekode", "husnummer", "byg007Bygningsnummer",
                  "byg021BygningensAnvendelse", "byg026Opfoerelsesaar", "byg027OmTilbygningsaar",
                  "byg038SamletBygningsareal", "byg039BygningensSamledeBoligAreal",
                  "byg041BebyggetAreal", "byg054AntalEtager", "byg404Koordinat { wkt crs }"]


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def key():
    k = os.environ.get("DATAFORDELER_API_KEY")
    if not k:
        sys.exit("DATAFORDELER_API_KEY missing — put it in .env")
    return k


def http(url, body=None, timeout=180):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "am-dashboard-dk/0.1"}, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def gql(version, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(4):
        try:
            return json.loads(http(f"{BASE}/{version}?apiKey={key()}", body))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(3 * (attempt + 1)); continue
            sys.exit(f"HTTP {e.code} from Datafordeler: {msg}\n"
                     + ("→ 401: the API key is not accepted. Check portal.datafordeler.dk → IT-systemer → your system → API-nøgle is Aktiv, and that the key in .env has no spaces." if e.code == 401 else ""))
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(3 * (attempt + 1)); continue
            raise
    return None


def cmd_schema(version):
    txt = http(f"{BASE}/{version}/schema?apiKey={key()}")
    out = ROOT / "data" / "raw" / "bbr_schema.graphql"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(txt)
    ents = re.findall(r"^type (BBR_\w+)", txt, re.M)
    print(f"schema saved → {out.relative_to(ROOT)} ({len(txt)//1000} kB)")
    print("entities:", ", ".join(sorted(set(ents))) or "(none matched 'type BBR_…' — open the file)")
    q = re.search(r"type Query \{(.*?)\n\}", txt, re.S)
    if q:
        print("query fields:\n " + "\n ".join(l.strip() for l in q.group(1).strip().splitlines()[:60]))


def schema_fields(entity):
    p = ROOT / "data" / "raw" / "bbr_schema.graphql"
    if not p.exists():
        sys.exit("run --schema first")
    m = re.search(rf"(?:type|input) {entity}\b[^{{]*\{{(.*?)\n\}}", p.read_text(), re.S)
    if not m:
        return None
    return {re.split(r"[\s(:]", l.strip())[0] for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith("#")}


def cmd_check():
    for ent, want in (("BBR_Enhed", ENHED_FIELDS), ("BBR_Bygning", BYGNING_FIELDS)):
        have = schema_fields(ent)
        if have is None:
            print(f"{ent}: not in schema"); continue
        ok = [f for f in want if f.split(' ')[0] in have]; missing = [f for f in want if f.split(' ')[0] not in have]
        print(f"{ent}: {len(ok)}/{len(want)} fields ok" + (f" · MISSING: {missing}" if missing else ""))
        if missing:
            cand = sorted(h for h in have if any(x.lower()[:6] in h.lower() for x in missing))[:40]
            print("   candidates in schema:", cand)
        flt = schema_fields(ent + "FilterInput") or set()
        print(f"   filter has kommunekode: {'kommunekode' in flt} · status: {'status' in flt} · {len(flt)} filterable fields")


STATUS = ["6"]   # BBR livscyklus: 6 = gældende/opført; 2–3 planned/under construction, 9–11 demolished/historic, 14 cancelled


def fetch_entity(version, entity, fields, kommune, out, limit=None, quiet=False):
    """Cursor-paged pull of one entity for one municipality → JSONL (one node per line). Only current objects (status 6)."""
    tmp = out.with_suffix(".part"); n = 0; after = None; t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tmp.open("w", encoding="utf-8") as f:
        while True:
            q = f"""query($first:Int!,$after:String,$kom:String!,$st:[String!],$t:DafDateTime!) {{
              {entity}(first:$first, after:$after, virkningstid:$t, registreringstid:$t, where:{{ kommunekode:{{ eq:$kom }}, status:{{ in:$st }} }}) {{
                pageInfo {{ endCursor hasNextPage }} nodes {{ {' '.join(fields)} }} }} }}"""
            r = gql(version, q, {"first": PAGE, "after": after, "kom": kommune, "st": STATUS, "t": now})
            if not r or "errors" in r:
                sys.exit(f"{entity} {kommune}: {json.dumps((r or {}).get('errors'), ensure_ascii=False)[:800]}")
            page = r["data"][entity]
            for node in page["nodes"]:
                f.write(json.dumps(node, ensure_ascii=False) + "\n"); n += 1
            if not quiet:
                print(f"\r  {entity} {kommune}: {n} rows · {time.time()-t0:.0f}s", end="", flush=True)
            if not page["pageInfo"]["hasNextPage"] or (limit and n >= limit):
                break
            after = page["pageInfo"]["endCursor"]
    tmp.rename(out)
    print(f"{'' if quiet else chr(10)}  {entity} {kommune}: {n} rows · {time.time()-t0:.0f}s ✓")
    return n


def rest_creds():
    u, pw = os.environ.get("DATAFORDELER_USER"), os.environ.get("DATAFORDELER_PASS")
    if not (u and pw):
        sys.exit("DATAFORDELER_USER / DATAFORDELER_PASS missing in .env (portal.datafordeler.dk → Brugeroplysninger → Tjenestebrugere)")
    return u, pw


def fetch_entity_rest(resource, fields, kommune, out, limit=None):
    """Page-numbered pull from BBRPublic REST (username/password tjenestebruger) → JSONL with the same fields."""
    import urllib.parse
    u, pw = rest_creds(); tmp = out.with_suffix(".part"); n = 0; page = 1; t0 = time.time(); size = REST_PAGE
    with tmp.open("w", encoding="utf-8") as f:
        while True:
            q = urllib.parse.urlencode({"kommunekode": kommune, "format": "json", "pagesize": size, "page": page, "username": u, "password": pw})
            try:
                txt = http(f"{REST}/{resource}?{q}", timeout=300)
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:300]
                if size > 100 and e.code in (400, 500):
                    size = 100; print(f"\n  page size {REST_PAGE} refused, using 100"); continue
                sys.exit(f"HTTP {e.code} from BBRPublic: {msg}")
            rows = json.loads(txt)
            for node in rows:
                f.write(json.dumps({k: node.get(k) for k in fields} | {"_id": node.get("id_lokalId")}, ensure_ascii=False) + "\n"); n += 1
            print(f"\r  {resource} {kommune}: {n} rows · page {page} · {time.time()-t0:.0f}s", end="", flush=True)
            if len(rows) < size or (limit and n >= limit):
                break
            page += 1
    tmp.rename(out); print()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", action="store_true"); ap.add_argument("--check", action="store_true")
    ap.add_argument("--kommune", help="one code (0147) or a comma list (0101,0157)")
    ap.add_argument("--metro", action="store_true", help="Copenhagen + 18 suburban municipalities")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--version", default="v3"); ap.add_argument("--limit", type=int, help="stop after n rows (pilot)")
    ap.add_argument("--entity", choices=["enhed", "bygning", "both"], default="both")
    ap.add_argument("--rest", action="store_true", help="use BBRPublic REST (tjenestebruger) instead of GraphQL")
    ap.add_argument("--workers", type=int, default=1, help="municipalities fetched in parallel (--all); 3–4 is polite")
    a = ap.parse_args(); load_env()
    if a.schema:
        cmd_schema(a.version); return
    if a.check:
        cmd_check(); return
    RAW.mkdir(parents=True, exist_ok=True)
    if a.all:
        geo = json.loads((ROOT / "data" / "geo" / "kommuner.geojson").read_text(encoding="utf-8"))
        codes = sorted({str(f["properties"].get("kode") or f["properties"].get("kommunekode")).zfill(4) for f in geo["features"]})
    elif a.metro:
        codes = METRO
    elif a.kommune:
        codes = [c.strip().zfill(4) for c in a.kommune.split(",") if c.strip()]
    else:
        ap.error("give --kommune 0147, --metro, --all, --schema or --check")
    log = RAW / "fetch_log.txt"
    def one(k):
        for ent, fields, name in (("BBR_Bygning", BYGNING_FIELDS, "bygning"), ("BBR_Enhed", ENHED_FIELDS, "enhed")):
            if a.entity != "both" and a.entity != name:
                continue
            out = RAW / f"{k}_{name}.jsonl"
            if out.exists() and not a.limit:
                print(f"  {out.name} exists — skip"); continue
            n = fetch_entity_rest(name, fields, k, out, a.limit) if a.rest else fetch_entity(a.version, ent, fields, k, out, a.limit, quiet=a.workers > 1)
            with log.open("a") as lf:
                lf.write(f"{dt.datetime.now():%Y-%m-%d %H:%M} {k} {name} {n}\n")
    if a.workers > 1 and len(codes) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(one, codes))
    else:
        for k in codes:
            one(k)
    print("done →", RAW.relative_to(ROOT))


if __name__ == "__main__":
    main()
