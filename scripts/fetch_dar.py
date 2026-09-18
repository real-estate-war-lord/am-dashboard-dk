#!/usr/bin/env python3
"""Addresses and property numbers for the building layer.

For every residential building with >= 2 dwellings (the Micro layer) this pulls
  • its access address from DAR (Danmarks Adresseregister):  BBR Bygning.husnummer → DAR_Husnummer
    → DAR_NavngivenVej (street name) + DAR_Postnummer (postal code)  →  "Vejnavn 12, 2100 København Ø"
  • its property (BFE number) from BBR:  BBR_Bygning.grund → BBR_Grund.bestemtFastEjendom → BBR_Ejendomsrelation.bfeNummer
Same free Datafordeler API key as fetch_bbr.py (DATAFORDELER_API_KEY in .env). Lookups are by id
lists (100 per request), so no municipality filter is needed and everything is resumable.

Outputs (gitignored): data/raw/dar/husnummer.jsonl, vej.jsonl, postnr.jsonl, bygning_grund.jsonl, grund.jsonl, ejd.jsonl
build_micro.py joins them into data/processed/micro/<kommune>.json (address, bfe columns).

Usage:
  python scripts/fetch_dar.py --schema        # save DAR schema, list entities (once)
  python scripts/fetch_dar.py --check         # verify the field names below against BBR + DAR schemas
  python scripts/fetch_dar.py --kommune 0147  # pilot
  python scripts/fetch_dar.py --all           # whole country (~20–40 min), resumable
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fetch_bbr import RAW as BBR_RAW, ROOT, load_env, key  # noqa: E402

OUT = ROOT / "data" / "raw" / "dar"
GQL = {"BBR": "https://graphql.datafordeler.dk/BBR/v3", "DAR": "https://graphql.datafordeler.dk/DAR/v3"}
BATCH = 100
MIN_DW = 2
# --- field names (verified by --check; adjust here if the schema differs) ---
F = {
    "DAR_Husnummer": ["id_lokalId", "status", "husnummertekst", "navngivenVej", "postnummer"],
    "DAR_NavngivenVej": ["id_lokalId", "vejnavn", "vejadresseringsnavn"],
    "DAR_Postnummer": ["id_lokalId", "postnr", "navn"],
    "BBR_Bygning": ["id_lokalId", "grund"],
    "BBR_Grund": ["id_lokalId", "bestemtFastEjendom"],
    "BBR_Ejendomsrelation": ["id_lokalId", "bfeNummer", "ejendomsnummer", "ejendomstype"],
}


def http(url, body=None, timeout=180):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "am-dashboard-dk/0.1"}, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def gql(reg, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(5):
        try:
            r = json.loads(http(f"{GQL[reg]}?apiKey={key()}", body))
            if "errors" in r:
                sys.exit(f"{reg} error: {json.dumps(r['errors'], ensure_ascii=False)[:700]}")
            return r["data"]
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(4 * (attempt + 1)); continue
            sys.exit(f"HTTP {e.code} from {reg}: {msg}")
        except urllib.error.URLError:
            if attempt < 4:
                time.sleep(4 * (attempt + 1)); continue
            raise


def schema_path(reg):
    return ROOT / "data" / "raw" / f"{reg.lower()}_schema.graphql"


def cmd_schema():
    for reg in ("DAR",):
        txt = http(f"{GQL[reg]}/schema?apiKey={key()}")
        schema_path(reg).write_text(txt)
        ents = sorted(set(re.findall(r"^type (DAR_\w+)(?!Connection|Edge)", txt, re.M)))
        print(f"{reg}: schema saved → {schema_path(reg).relative_to(ROOT)} ({len(txt)//1000} kB)")
        print("  entities:", ", ".join(e for e in ents if not e.endswith(("Connection", "Edge"))))


def schema_fields(reg, entity):
    p = schema_path(reg)
    if not p.exists():
        sys.exit(f"run --schema first ({p.name} missing)" if reg == "DAR" else "run fetch_bbr.py --schema first")
    m = re.search(rf"(?:type|input) {entity}\b[^{{]*\{{(.*?)\n\}}", p.read_text(), re.S)
    return None if not m else {re.split(r"[\s(:]", l.strip())[0] for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith("#")}


def cmd_check():
    ok_all = True
    for ent, want in F.items():
        reg = ent.split("_")[0]; have = schema_fields(reg, ent)
        if have is None:
            print(f"✗ {ent}: not in {reg} schema"); ok_all = False; continue
        missing = [f for f in want if f not in have]
        flt = schema_fields(reg, ent + "FilterInput") or set()
        print(f"{'✓' if not missing else '✗'} {ent}: {len(want) - len(missing)}/{len(want)} fields" + (f" · MISSING {missing}" if missing else "") + f" · filter id_lokalId: {'id_lokalId' in flt}")
        if missing:
            ok_all = False; print("    fields available:", sorted(have)[:60])
    print("all field names verified" if ok_all else "fix the names in F = {...} at the top of fetch_dar.py, then re-run --check")


def id_type(reg, entity, field):
    """GraphQL list type for the `in` filter of <field>: [UUID!] or [String!], read from the schema."""
    p = schema_path(reg)
    m = re.search(rf"input {entity}FilterInput\b[^{{]*\{{(.*?)\n\}}", p.read_text(), re.S) if p.exists() else None
    if m:
        f = re.search(rf"^\s*{field}:\s*(\w+)", m.group(1), re.M)
        if f and "Uuid" in f.group(1):
            return "[UUID!]"
    return "[String!]"


def by_ids(reg, entity, fields, filt_field, ids, out, done):
    """Fetch entity rows whose <filt_field> is in the id list, 100 per request, appending JSONL; skips ids already in `done`."""
    todo = [i for i in ids if i not in done]; n = 0; t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"""query($ids:{id_type(reg, entity, filt_field)},$t:DafDateTime!) {{ {entity}(first:1000, virkningstid:$t, registreringstid:$t, where:{{ {filt_field}:{{ in:$ids }} }}) {{ nodes {{ {' '.join(fields)} }} }} }}"""
    with out.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            d = gql(reg, q, {"ids": chunk, "t": now})
            for node in d[entity]["nodes"]:
                f.write(json.dumps(node, ensure_ascii=False) + "\n"); n += 1
            for c in chunk:
                done.add(c)
            if (i // BATCH) % 20 == 0:
                print(f"\r  {entity}: {min(i + BATCH, len(todo))}/{len(todo)} ids · {n} rows · {time.time()-t0:.0f}s", end="", flush=True)
    print(f"\r  {entity}: {len(todo)} ids → {n} rows · {time.time()-t0:.0f}s ✓            ")
    return n


def load_jsonl(p):
    return [json.loads(l) for l in p.open(encoding="utf-8")] if p.exists() else []


def needed_buildings(koms):
    """Building ids with >= MIN_DW dwellings, and their husnummer ids, from the BBR raw pulls."""
    blds = {}
    for kom in koms:
        bf, ef = BBR_RAW / f"{kom}_bygning.jsonl", BBR_RAW / f"{kom}_enhed.jsonl"
        if not (bf.exists() and ef.exists()):
            print(f"  {kom}: BBR pull missing — skipped"); continue
        cnt = {}
        for line in ef.open(encoding="utf-8"):
            u = json.loads(line)
            if u.get("enh023Boligtype") in ("1", "2", "3", "4", "5") and u.get("bygning"):
                cnt[u["bygning"]] = cnt.get(u["bygning"], 0) + 1
        for line in bf.open(encoding="utf-8"):
            b = json.loads(line)
            if cnt.get(b["id_lokalId"], 0) >= MIN_DW:
                blds[b["id_lokalId"]] = b.get("husnummer")
    return blds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", action="store_true"); ap.add_argument("--check", action="store_true")
    ap.add_argument("--kommune"); ap.add_argument("--all", action="store_true")
    a = ap.parse_args(); load_env()
    if a.schema:
        cmd_schema(); return
    if a.check:
        cmd_check(); return
    koms = sorted({p.name[:4] for p in BBR_RAW.glob("*_enhed.jsonl")}) if a.all else ([c.strip().zfill(4) for c in a.kommune.split(",")] if a.kommune else ap.error("--kommune 0147, --all, --schema or --check"))
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"collecting buildings with ≥{MIN_DW} dwellings from {len(koms)} municipalities…")
    blds = needed_buildings(koms)
    hus_ids = sorted({h for h in blds.values() if h})
    print(f"  {len(blds)} buildings · {len(hus_ids)} distinct husnummer ids")
    # 1. DAR husnummer
    hus_out = OUT / "husnummer.jsonl"; done = {r["id_lokalId"] for r in load_jsonl(hus_out)}
    by_ids("DAR", "DAR_Husnummer", F["DAR_Husnummer"], "id_lokalId", hus_ids, hus_out, done)
    hus = load_jsonl(hus_out)
    # 2. street names + postal codes referenced by those husnumre
    vej_ids = sorted({r["navngivenVej"] for r in hus if r.get("navngivenVej")}); pn_ids = sorted({r["postnummer"] for r in hus if r.get("postnummer")})
    vej_out = OUT / "vej.jsonl"; by_ids("DAR", "DAR_NavngivenVej", F["DAR_NavngivenVej"], "id_lokalId", vej_ids, vej_out, {r["id_lokalId"] for r in load_jsonl(vej_out)})
    pn_out = OUT / "postnr.jsonl"; by_ids("DAR", "DAR_Postnummer", F["DAR_Postnummer"], "id_lokalId", pn_ids, pn_out, {r["id_lokalId"] for r in load_jsonl(pn_out)})
    # 3. property (BFE): building → grund → ejendomsrelation
    bg_out = OUT / "bygning_grund.jsonl"; by_ids("BBR", "BBR_Bygning", F["BBR_Bygning"], "id_lokalId", sorted(blds), bg_out, {r["id_lokalId"] for r in load_jsonl(bg_out)})
    grund_ids = sorted({r["grund"] for r in load_jsonl(bg_out) if r.get("grund")})
    gr_out = OUT / "grund.jsonl"; by_ids("BBR", "BBR_Grund", F["BBR_Grund"], "id_lokalId", grund_ids, gr_out, {r["id_lokalId"] for r in load_jsonl(gr_out)})
    ejd_ids = sorted({r["bestemtFastEjendom"] for r in load_jsonl(gr_out) if r.get("bestemtFastEjendom")})
    ejd_out = OUT / "ejd.jsonl"; by_ids("BBR", "BBR_Ejendomsrelation", F["BBR_Ejendomsrelation"], "id_lokalId", ejd_ids, ejd_out, {r["id_lokalId"] for r in load_jsonl(ejd_out)})
    print(f"done → {OUT.relative_to(ROOT)}  (now: make bbr && make build)")


if __name__ == "__main__":
    main()
