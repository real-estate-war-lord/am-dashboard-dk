#!/usr/bin/env python3
"""Build data/processed/market.json (national macro series) from raw pulls.

Each entry in config `macro` yields one series {t, v} (sorted by period) and a
`latest` record with y/y change when `yoy` is true. Entries whose codes still
contain 'TODO' are skipped with a warning — fix them via validate_config.py.
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statbank_common import ROOT, cfg, rows, period_key  # noqa: E402

OUT = ROOT / "data" / "processed" / "market.json"


def main():
    c = cfg()
    series, latest, warnings = {}, {}, []
    for m in c["macro"]:
        if any("TODO" in v for vals in m["vars"].values() for v in vals):
            warnings.append(f"{m['key']}: unresolved TODO codes — skipped")
            continue
        try:
            rs = rows(m.get("db", ""), m["table"])
        except FileNotFoundError as e:
            warnings.append(str(e)); continue
        # keep rows matching all single-valued selections
        sel = {k: v[0] for k, v in m["vars"].items() if k != "Tid" and len(v) == 1 and v[0] != "*"}
        rs = [r for r in rs if all(r.get(k) == v for k, v in sel.items())]
        s = sorted(({"t": r["TID"], "v": r["INDHOLD"]} for r in rs if r["INDHOLD"] is not None), key=lambda p: period_key(p["t"]))
        if not s:
            warnings.append(f"{m['key']}: no rows after selection {sel}"); continue
        series[m["key"]] = s
        last = s[-1]; y, n = period_key(last["t"])
        prev = next((p for p in s if period_key(p["t"]) == (y - 1, n)), None)
        yoy = (last["v"] / prev["v"] - 1) * 100 if (m.get("yoy") and prev and prev["v"]) else None
        latest[m["key"]] = {"t": last["t"], "v": last["v"], "yoy": yoy, "label": m["label"], "unit": m.get("unit", ""),
                            "dec": m.get("dec", 1), "src": m.get("src", "")}
    out = {"series": series, "latest": latest, "hero": c.get("macro_hero", []), "table": [m["key"] for m in c["macro"]],
           "built": dt.date.today().isoformat(), "note": "National series unless stated. y/y = change vs the same period one year earlier.",
           "warnings": warnings}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT}: {len(series)} series")
    for w in warnings:
        print("  ⚠", w)


if __name__ == "__main__":
    main()
