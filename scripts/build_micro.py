#!/usr/bin/env python3
"""Building-level ("Micro") layer from the BBR pulls: one compact JSON per municipality.

Input : data/raw/bbr/<kommune>_{bygning,enhed}.jsonl (scripts/fetch_bbr.py)
Output: data/processed/micro/<kommune>.json  (copied to dist/micro/ by build_dashboard.py, loaded on demand)
  {"meta": {"kommune": "0101", "built": "...", "n": 12345, "min_dwellings": 2, "cols": [...]},
   "b": [[lat, lon, dwellings, rented_pct, vacant_pct, avg_m2, year, floors, type, rooms1, rooms2, rooms3, rooms4p, small_pct, id], ...]}

Only buildings with at least MIN_DW dwellings (boligtype 1–5) are kept — single-family houses would
dominate the file (≈ 1.2 M nationally) without adding much for a portfolio view.
type: 1 house, 2 row house, 3 multi-dwelling (byg021 = 140), 4 other residential/mixed.
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_bbr import RAW, ROOT, parse_wkt_point, utm32_to_wgs84  # noqa: E402

OUT = ROOT / "data" / "processed" / "micro"
MIN_DW = 2
COLS = ["lat", "lon", "dwellings", "rented_pct", "vacant_pct", "avg_m2", "year", "floors", "type", "rooms1", "rooms2", "rooms3", "rooms4p", "small_pct", "id", "address", "bfe"]
DAR = ROOT / "data" / "raw" / "dar"


def load_lookups():
    """Address per husnummer id and BFE per building id from fetch_dar.py pulls (optional)."""
    def jl(name):
        p = DAR / name
        return [json.loads(l) for l in p.open(encoding="utf-8")] if p.exists() else []
    vej = {r["id_lokalId"]: (r.get("vejnavn") or r.get("vejadresseringsnavn") or "") for r in jl("vej.jsonl")}
    pn = {r["id_lokalId"]: (r.get("postnr") or "", r.get("navn") or "") for r in jl("postnr.jsonl")}
    addr = {}
    for r in jl("husnummer.jsonl"):
        v = vej.get(r.get("navngivenVej"), ""); p_ = pn.get(r.get("postnummer"), ("", ""))
        if v or p_[0]:
            addr[r["id_lokalId"]] = f"{v} {r.get('husnummertekst') or ''}".strip() + (f", {p_[0]} {p_[1]}".rstrip() if p_[0] else "")
    ejd = {r["id_lokalId"]: r.get("bfeNummer") for r in jl("ejd.jsonl")}
    grund = {r["id_lokalId"]: ejd.get(r.get("bestemtFastEjendom")) for r in jl("grund.jsonl")}
    bfe = {r["id_lokalId"]: grund.get(r.get("grund")) for r in jl("bygning_grund.jsonl") if grund.get(r.get("grund"))}
    return addr, bfe


def btype(code):
    c = str(code or "")
    return 1 if c in ("110", "120", "121", "122") else 2 if c in ("130", "131", "132") else 3 if c == "140" else 4


def build_one(kom, addr=None, bfe=None):
    addr = addr or {}; bfe = bfe or {}
    bf, ef = RAW / f"{kom}_bygning.jsonl", RAW / f"{kom}_enhed.jsonl"
    if not (bf.exists() and ef.exists()):
        return None
    blds = {}
    for line in bf.open(encoding="utf-8"):
        b = json.loads(line); c = (b.get("byg404Koordinat") or {}).get("wkt")
        xy = parse_wkt_point(c) if c else None
        if not xy:
            continue
        lon, lat = utm32_to_wgs84(*xy)
        blds[b["id_lokalId"]] = {"lat": round(lat, 5), "lon": round(lon, 5), "year": b.get("byg026Opfoerelsesaar"), "floors": b.get("byg054AntalEtager"), "hus": b.get("husnummer"),
                                 "type": btype(b.get("byg021BygningensAnvendelse")), "n": 0, "rent": 0, "vac": 0, "ten": 0, "m2": 0.0, "m2n": 0, "small": 0, "rooms": [0, 0, 0, 0]}
    for line in ef.open(encoding="utf-8"):
        u = json.loads(line)
        if u.get("enh023Boligtype") not in ("1", "2", "3", "4", "5"):
            continue
        b = blds.get(u.get("bygning"))
        if not b:
            continue
        b["n"] += 1
        t = u.get("enh045Udlejningsforhold")
        if t in ("1", "2", "3"):
            b["ten"] += 1; b["rent"] += t == "1"; b["vac"] += t == "3"
        m2 = u.get("enh026EnhedensSamledeAreal")
        if m2 and m2 > 0:
            b["m2"] += m2; b["m2n"] += 1; b["small"] += m2 < 50
        r = u.get("enh031AntalVaerelser")
        if r and r > 0:
            b["rooms"][min(int(r), 4) - 1] += 1
    rows = []
    for bid, b in blds.items():
        if b["n"] < MIN_DW:
            continue
        pct = lambda a, n: round(a / n * 100) if n else None
        y = b["year"] if b["year"] and 1000 < b["year"] <= 2100 else None
        rows.append([b["lat"], b["lon"], b["n"], pct(b["rent"], b["ten"]), pct(b["vac"], b["ten"]), round(b["m2"] / b["m2n"]) if b["m2n"] else None,
                     y, b["floors"], b["type"], *b["rooms"], pct(b["small"], b["m2n"]), bid[:8], addr.get(b["hus"]) or None, bfe.get(bid)])
    rows.sort(key=lambda r: -r[2])
    return {"meta": {"kommune": kom, "built": dt.date.today().isoformat(), "n": len(rows), "min_dwellings": MIN_DW, "cols": COLS,
                     "source": "BBR via Datafordeler (Klimadatastyrelsen), status 6, boligtype 1–5"}, "b": rows}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    koms = sorted({p.name[:4] for p in RAW.glob("*_enhed.jsonl")})
    addr, bfe = load_lookups(); print(f"  lookups: {len(addr)} addresses, {len(bfe)} property numbers (fetch_dar.py)")
    total = 0; index = {}; n_addr = 0
    for kom in koms:
        d = build_one(kom, addr, bfe)
        if not d:
            continue
        p = OUT / f"{kom}.json"; p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index[str(int(kom))] = {"file": f"micro/{kom}.json", "n": d["meta"]["n"], "kb": p.stat().st_size // 1000}
        total += d["meta"]["n"]; n_addr += sum(1 for r in d["b"] if r[15]); print(f"  {kom}: {d['meta']['n']} buildings · {p.stat().st_size//1000} kB")
    (OUT / "index.json").write_text(json.dumps({"built": dt.date.today().isoformat(), "min_dwellings": MIN_DW, "municipalities": index}, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}/: {len(index)} municipalities · {total} buildings with ≥{MIN_DW} dwellings · {n_addr} with address")


if __name__ == "__main__":
    main()
