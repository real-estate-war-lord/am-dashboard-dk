"""Shared helpers: locate raw pulls, parse StatBank CSV, read tableinfo labels."""
import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CFG = ROOT / "config" / "indicators.json"
AREA_VARS = {"OMRÅDE", "BOPOMR", "REGION", "KOMMUNE", "KOMMUNEDK", "OMR20", "PNR20", "SOGN", "BYER"}


def cfg() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def tag(db: str, table: str, pull: str | None = None) -> str:
    return f"{db or 'dst'}_{pull or table}"


def latest_raw(db: str, table: str, pull: str | None = None) -> pathlib.Path | None:
    files = sorted(RAW.glob(f"{tag(db, table, pull)}_20*.csv"))
    return files[-1] if files else None


def meta(db: str, table: str) -> dict:
    p = RAW / f"{tag(db, table)}.meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def labels(db: str, table: str, var: str) -> dict:
    """code -> text for one variable, from tableinfo."""
    for v in meta(db, table).get("variables", []):
        if v.get("id") == var:
            return {x["id"]: x["text"] for x in v.get("values", [])}
    return {}


def num(s):
    s = (s or "").strip().replace(" ", "")
    if s in ("", "..", "...", "-", "–", "."):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def rows(db: str, table: str, pull: str | None = None) -> list[dict]:
    """Parse the latest raw CSV (semicolon, valuePresentation=Code) into dicts.
    Keys = variable codes as in the header, plus TID and INDHOLD (float|None)."""
    p = latest_raw(db, table, pull)
    if not p:
        raise FileNotFoundError(f"no raw pull for {tag(db, table, pull)} — run scripts/fetch_statbank.py --table {table}")
    out = []
    with p.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            r = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            r["INDHOLD"] = num(r.get("INDHOLD"))
            out.append(r)
    return out


def area_col(r: dict) -> str | None:
    for k in r:
        if k in AREA_VARS:
            return k
    return None


def muni_code(code: str) -> str:
    """Normalise municipality codes: '0101' -> '101', '101' -> '101'."""
    c = re.sub(r"\D", "", str(code))
    return c.lstrip("0") or "0"


def period_key(t: str):
    """Sortable key for DST periods: 2026, 2026K1, 2026Q1, 2026M07."""
    m = re.match(r"(\d{4})(?:([KQM])(\d{1,2}))?", t or "")
    if not m:
        return (0, 0)
    y, kind, n = int(m.group(1)), m.group(2), int(m.group(3) or 0)
    return (y, n * (3 if kind in ("K", "Q") else 1))
