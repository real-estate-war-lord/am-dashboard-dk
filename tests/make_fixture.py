#!/usr/bin/env python3
"""SYNTHETIC development fixture — random numbers on box-shaped polygons.
Only for checking that the template renders; never ship dist/ built from this.
Writes tests/fixture_makro.json and tests/fixture_market.json."""
import json
import math
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from statbank_common import cfg  # noqa: E402

random.seed(7)
HERE = pathlib.Path(__file__).resolve().parent
c = cfg()
inds = [{k: i[k] for k in ("key", "label", "short", "unit", "level", "hue", "fmt", "desc", "source") if k in i} | {"warn": i.get("warn", ""), "table_only": i.get("table_only", False)} for i in c["indicators"]]
RANGES = {"growth": (-1, 2.5), "income": (200000, 320000), "income_med": (220000, 300000), "young": (12, 32), "single": (35, 60), "benefit": (8, 25),
          "rent_private": (700, 1500), "rent_social": (800, 1100), "renters": (30, 75), "unemp": (2, 6), "higher_ed": (25, 60), "flats": (10, 85),
          "foreign": (5, 25), "price_m2": (15000, 80000), "discount": (1, 8), "dom": (30, 200), "supply": (5, 30), "pipeline": (2, 20), "almene": (5, 35), "avg_m2": (80, 130)}
munis = [("101", "SYN-Copenhagen", 55.68, 12.57), ("147", "SYN-Frederiksberg", 55.68, 12.53), ("751", "SYN-Aarhus", 56.16, 10.20),
         ("461", "SYN-Odense", 55.40, 10.39), ("851", "SYN-Aalborg", 57.05, 9.92), ("157", "SYN-Gentofte", 55.75, 12.55)]
M, A = [], []
for code, name, lat, lon in munis:
    m = {"code": code, "name": name, "pop": random.randint(40000, 650000)}
    for i in inds:
        lo, hi = RANGES[i["key"]]; m[i["key"]] = round(random.uniform(lo, hi), 2)
    M.append(m)
    for j in range(4):
        cx, cy = lat + (j // 2) * 0.03, lon + (j % 2) * 0.05
        ring = [[round(cx + 0.03 * math.sin(t), 5), round(cy + 0.05 * math.cos(t), 5)] for t in [k * math.pi / 3 for k in range(6)]]
        a = {"nr": f"{int(code)*10 + j}", "name": f"{name} {j+1}", "muni": code, "rings": [ring], "pop": random.randint(3000, 40000)}
        for i in inds:
            if i["level"] == "postnr":
                lo, hi = RANGES[i["key"]]; a[i["key"]] = round(random.uniform(lo, hi), 2)
        A.append(a)
makro = {"meta": {"built": "SYNTHETIC", "sources": [{"label": "SYNTHETIC FIXTURE — not real data", "asof": "n/a"}], "attribution": ["synthetic"], "note": "SYNTHETIC numbers."},
         "indicators": inds, "municipalities": M, "areas": A}
(HERE / "fixture_makro.json").write_text(json.dumps(makro, ensure_ascii=False))
series, latest = {}, {}
for m in c["macro"]:
    base = random.uniform(50, 150); s = []
    for k in range(24):
        s.append({"t": f"{2024 + k // 12}M{k % 12 + 1:02d}", "v": round(base * (1 + 0.004 * k + random.uniform(-0.01, 0.01)), 2)})
    series[m["key"]] = s
    latest[m["key"]] = {"t": s[-1]["t"], "v": s[-1]["v"], "yoy": round((s[-1]["v"] / s[-13]["v"] - 1) * 100, 2), "label": m["label"], "unit": m.get("unit", ""), "dec": m.get("dec", 1), "src": m.get("src", "")}
market = {"series": series, "latest": latest, "hero": c["macro_hero"], "table": [m["key"] for m in c["macro"]], "note": "SYNTHETIC fixture."}
(HERE / "fixture_market.json").write_text(json.dumps(market, ensure_ascii=False))
print("fixture written")
