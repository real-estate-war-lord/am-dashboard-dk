"""Safety indicators (STRAF11 / STRAF22) — calc checks on real cells.

Run: python3 -m unittest discover -s tests -v
The fixture tests use cells copied from the 2026-09-22 pulls; the raw-data tests
re-read data/raw and are skipped when the pulls are not present.
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_makro as bm  # noqa: E402
from statbank_common import latest_raw  # noqa: E402

IND = {i["key"]: i for i in json.loads((ROOT / "config" / "indicators.json").read_text(encoding="utf-8"))["indicators"]}

# STRAF11 OVERTRÆD=1 (penal code total), København, as published 2026-07-16
CPH_Q = {"2025K3": 15323, "2025K4": 14713, "2026K1": 15205, "2026K2": 15045}
CPH_POP_2026K3 = 670389      # FOLK1A København 2026K3 (1 July 2026)


def straf11(cells, code="1", area="101"):
    return [{"OMRÅDE": area, "OVERTRÆD": code, "TID": t, "INDHOLD": v} for t, v in cells.items()]


def folk1a(cells, area="101"):
    return [{"OMRÅDE": area, "KØN": "TOT", "ALDER": "IALT", "TID": t, "INDHOLD": v} for t, v in cells.items()]


class RollingFixture(unittest.TestCase):
    cells = CPH_Q

    def test_crime_1000_copenhagen(self):
        vals, per = bm.rolling4q("rolling4q_per_1000_pop", straf11(self.cells), {"select": {"OVERTRÆD": "1"}},
                                 folk1a({"2026K2": 1, "2026K3": CPH_POP_2026K3}))
        s = 15323 + 14713 + 15205 + 15045
        self.assertEqual(per, "2025K3→2026K2")
        self.assertAlmostEqual(vals["101"], s / 670.389, places=9)
        self.assertTrue(80 <= vals["101"] <= 95, vals["101"])          # 2026K2 alone is 15045 → ≈ 22 × 4

    def test_population_falls_back_to_last_quarter(self):
        vals, _ = bm.rolling4q("rolling4q_per_1000_pop", straf11(self.cells), {"select": {"OVERTRÆD": "1"}}, folk1a({"2026K2": 670000}))
        self.assertAlmostEqual(vals["101"], 60286 / 670.0)

    def test_suppressed_quarter_is_null_not_imputed(self):
        cells = dict(self.cells, **{"2026K1": None})
        vals, _ = bm.rolling4q("rolling4q_per_1000_pop", straf11(cells), {"select": {"OVERTRÆD": "1"}}, folk1a({"2026K3": CPH_POP_2026K3}))
        self.assertIsNone(vals["101"])

    def test_incomplete_window_gives_nothing(self):
        cells = {k: v for k, v in self.cells.items() if k != "2025K4"}
        self.assertEqual(bm.rolling4q("rolling4q_per_1000_pop", straf11(cells), {"select": {"OVERTRÆD": "1"}}, folk1a({"2026K3": 1})), ({}, None))

    def test_multi_code_select_sums_codes(self):
        rows = straf11({t: 10 for t in self.cells}, "3210") + straf11({t: 5 for t in self.cells}, "3410") + straf11({t: 999 for t in self.cells}, "1")
        vals, _ = bm.rolling4q("rolling4q_per_1000_pop", rows, {"select": {"OVERTRÆD": ["3210", "3410"]}}, folk1a({"2026K3": 1000}))
        self.assertAlmostEqual(vals["101"], 60.0)

    def test_history_year_is_q1_to_q4(self):
        cells = {f"2025K{q}": 100 * q for q in (1, 2, 3, 4)} | {"2026K1": 7}
        vals, per = bm.rolling4q("rolling4q_per_1000_pop", straf11(cells), {"select": {"OVERTRÆD": "1"}}, folk1a({"2025K4": 1, "2026K1": 2000}), year=2025)
        self.assertEqual(per, "2025K1→2025K4")
        self.assertAlmostEqual(vals["101"], 1000 / 2000 * 1000)       # ÷ population at the end of Q4 (FOLK1A 2026K1)

    def test_yoy_and_filing_year(self):
        cells = {f"{y}K{q}": (100 if y == 2024 else 110) for y in (2024, 2025) for q in (1, 2, 3, 4)}
        vals, per = bm.rolling4q("rolling4q_yoy_pct", straf11(cells), {"select": {"OVERTRÆD": "1"}})
        self.assertAlmostEqual(vals["101"], 10.0)
        # the history loop files a value under the year of the last period in the label
        self.assertEqual(bm.period_parts(per.replace("→", "–").split("–")[-1].strip())[0], 2025)

    def test_burglary_per_dwelling_stock_at_end_of_window(self):
        bol = [{"OMRÅDE": "101", "BEBO": "1000", "ANVENDELSE": "140", "TID": y, "INDHOLD": v} for y, v in (("2025", 900), ("2026", 1000))]
        vals, _ = bm.rolling4q("rolling4q_per_1000_dwellings", straf11(self.cells, "1320"), {"select": {"OVERTRÆD": "1320"}}, bol)
        self.assertAlmostEqual(vals["101"], 60286 / 1000 * 1000)        # window ends 2026 → latest stock 1 Jan 2026

    def test_q_shift(self):
        self.assertEqual(bm.q_shift("2026K2", 1), "2026K3")
        self.assertEqual(bm.q_shift("2026K4", 1), "2027K1")
        self.assertEqual(bm.q_shift("2026K1", -4), "2025K1")


@unittest.skipUnless(latest_raw("", "STRAF11", "STRAF11_offences") and latest_raw("", "STRAF22", "STRAF22_charges"), "raw STRAF pulls not present")
class RawData(unittest.TestCase):
    def test_crime_1000_copenhagen_from_raw(self):
        rows = bm.rows("", "STRAF11", "STRAF11_offences")
        cells = {r["TID"]: r["INDHOLD"] for r in rows if r["OMRÅDE"] == "101" and r["OVERTRÆD"] == "1"}
        self.assertEqual([cells[t] for t in ("2025K3", "2025K4", "2026K1", "2026K2")], [15323, 14713, 15205, 15045])
        res = bm.compute(IND["crime_1000"])
        vals, per = res["kommune"]
        self.assertEqual(per, "2025K3→2026K2")
        self.assertAlmostEqual(vals["101"], sum(cells[t] for t in ("2025K3", "2025K4", "2026K1", "2026K2")) / 670.389, places=9)

    def test_quarterly_series_and_long_history(self):
        ind = IND["crime_1000"]
        ser = bm.rolling4q_series(ind, "2008K1")
        self.assertEqual(ser[0][0], "2008K1")
        live, per = bm.compute(ind)["kommune"]
        self.assertEqual(ser[-1][0], per.split("→")[-1])                  # last quarterly point = the live value
        self.assertAlmostEqual(ser[-1][1]["101"], live["101"], places=9)
        y2007, per2007 = bm.compute(ind, 2007)["kommune"]                   # yearly history reaches STRAF11's first year
        self.assertEqual(per2007, "2007K1→2007K4")
        self.assertIsNotNone(y2007["101"])

    def test_clearance_copenhagen_2025(self):
        vals, per = bm.compute(IND["clearance_pct"])["kommune"]
        self.assertEqual(per, "2025")
        self.assertAlmostEqual(vals["101"], 11763 / 68802 * 100, places=9)
        self.assertEqual(round(vals["101"], 1), 17.1)


if __name__ == "__main__":
    unittest.main()
