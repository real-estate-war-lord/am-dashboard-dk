"""Climate layer (v2.5) — the figures the whole layer is anchored on.

Run: python3 -m unittest discover -s tests -v

The value tests read the committed pulls under data/raw/klimaatlas and data/raw/fp; they are
skipped when those have not been fetched (they are gitignored). The registry and mapping tests
need nothing but the repo.
"""
import csv
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

RAW = ROOT / "data" / "raw"
KL = RAW / "klimaatlas"
PROC = ROOT / "data" / "processed" / "climate"
IND = {i["key"]: i for i in json.loads(
    (ROOT / "config" / "indicators.json").read_text(encoding="utf-8"))["indicators"]}

P50, ABS, AARSTID = 50, 1, 1


def jload(p):
    return json.loads(p.read_text(encoding="utf-8"))


def pick(rows, key, code, scenarie, periode, col):
    """One Klimaatlas cell at percentile 50, absolute change, annual."""
    for r in rows:
        if (str(r.get(key)) == code and r["scenarie"] == scenarie and r["periode"] == periode
                and r["percentil"] == P50 and r["absolutaendring"] == ABS
                and r["aarstid"] == AARSTID):
            return r[col]
    return None


@unittest.skipUnless((KL / "coast_values.json").exists(), "no Klimaatlas pull on disk")
class KlimaatlasCoast(unittest.TestCase):
    """Sjælland Nord/Øresund (SJ7) — the stretch København and Gentofte sit on."""

    @classmethod
    def setUpClass(cls):
        cls.rows = jload(KL / "coast_values.json")

    def cell(self, scenarie, periode, col):
        return pick(self.rows, "kystkode", "SJ7", scenarie, periode, col)

    def test_historic_100yr_surge(self):
        """Today = scenarie 0, periode 1: the observed 100-year surge level."""
        self.assertAlmostEqual(self.cell(0, 1, "Stormfl100Aarsh"), 156.85, places=2)

    def test_historic_sea_level_is_the_baseline(self):
        self.assertEqual(self.cell(0, 1, "Middelvandstand"), 0)

    def test_historic_frequency_multiplier_is_one(self):
        self.assertEqual(self.cell(0, 1, "StormflNuvaerende100Aarsh"), 1)

    def test_ssp245_mean_sea_level(self):
        """SSP2-4.5, p50: +24.89 cm for 2041–2070 and +39.44 cm for 2071–2100."""
        self.assertAlmostEqual(self.cell(245, 3, "Middelvandstand"), 24.89, places=2)
        self.assertAlmostEqual(self.cell(245, 4, "Middelvandstand"), 39.44, places=2)

    def test_ssp245_100yr_surge(self):
        self.assertAlmostEqual(self.cell(245, 3, "Stormfl100Aarsh"), 181.74, places=2)
        self.assertAlmostEqual(self.cell(245, 4, "Stormfl100Aarsh"), 196.29, places=2)

    def test_surge_is_sea_level_plus_the_historic_surge(self):
        """The two are consistent: the future surge level is the baseline plus the rise."""
        for per in (3, 4):
            self.assertAlmostEqual(self.cell(245, per, "Stormfl100Aarsh"),
                                   self.cell(0, 1, "Stormfl100Aarsh")
                                   + self.cell(245, per, "Middelvandstand"), places=2)

    def test_thirty_four_stretches(self):
        self.assertEqual(len({r["kystkode"] for r in self.rows}), 34)


@unittest.skipUnless((KL / "precip_values.json").exists(), "no Klimaatlas pull on disk")
class KlimaatlasPrecip(unittest.TestCase):
    """København (komkode 101) — RCP4.5, p50."""

    @classmethod
    def setUpClass(cls):
        cls.rows = jload(KL / "precip_values.json")

    def test_rcp45_100yr_hourly_rain(self):
        self.assertAlmostEqual(pick(self.rows, "komkode", "101", 45, 3, "Time100Aarsh"),
                               51.31, places=2)
        self.assertAlmostEqual(pick(self.rows, "komkode", "101", 45, 4, "Time100Aarsh"),
                               52.73, places=2)

    def test_every_kommune_has_a_row(self):
        self.assertEqual(len({r["komkode"] for r in self.rows}), 98)


@unittest.skipUnless((RAW / "fp" / "fp_claims.csv").exists(), "no F&P pull on disk")
class FPClaims(unittest.TestCase):
    def test_row_count(self):
        with (RAW / "fp" / "fp_claims.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 98)

    def test_every_row_matched_a_kommune_code(self):
        with (RAW / "fp" / "fp_claims.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(all(len(r["kommune_kode"]) == 4 and r["kommune_kode"].isdigit()
                            for r in rows))
        self.assertEqual(len({r["kommune_kode"] for r in rows}), 98)


@unittest.skipUnless((PROC / "risk_areas.json").exists(), "risk areas not built")
class SurgeZones(unittest.TestCase):
    """The published Kystdirektoratet extents — nothing modelled, so the only checks are that
    the three horizons exist, carry no depth class, and name their source."""

    HZ = ("today", "2070", "2120")

    def test_every_horizon_has_an_index(self):
        for hz in self.HZ:
            p = PROC / f"surge_{hz}" / "index.json"
            if not p.exists():
                self.skipTest(f"surge_{hz} not built")
            m = jload(p)["meta"]
            self.assertIsNone(m["depth_class"])
            self.assertIn("Kystdirektoratet", m["source"])
            self.assertEqual(m["event"], "100-årshændelse")

    def test_horizon_ids_are_the_klimaatlas_periods(self):
        p = PROC / "surge_2120" / "index.json"
        if not p.exists():
            self.skipTest("surge_2120 not built")
        self.assertIn("2071", jload(p)["meta"]["period"])


class RiskAreas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = jload(PROC / "risk_areas.json")

    def test_twenty_six_areas(self):
        """The 2024 designation publishes 26 risk areas — the brief's 25 was one short."""
        self.assertEqual(len(self.d["features"]), 26)

    def test_designation_count_matches_the_official_51(self):
        self.assertEqual(len(self.d["meta"]["kommuner"]), 51)

    def test_koege_bugt_area(self):
        a = next(f for f in self.d["features"]
                 if f["properties"]["area_name"] == "Køge Bugt/København")
        self.assertAlmostEqual(a["properties"]["area_km2"], 101.5, delta=0.6)
        self.assertIn("0101", a["properties"]["kommuner"])


class CoastMap(unittest.TestCase):
    """data/external/klimaatlas_coast_kommune.csv — generated, committed."""

    @classmethod
    def setUpClass(cls):
        with (ROOT / "data" / "external" / "klimaatlas_coast_kommune.csv").open() as fh:
            cls.rows = {r["kommune_kode"]: r for r in csv.DictReader(fh)}

    def test_copenhagen_takes_sj7_and_lists_sj8(self):
        """København's coastline is longest against SJ7; SJ8 is named, never averaged in."""
        self.assertEqual(self.rows["0101"]["kystkode"], "SJ7")
        self.assertEqual(self.rows["0101"]["other_kystkoder"], "SJ8")

    def test_koege_bugt_kommuner_are_on_sj8(self):
        for code in ("0167", "0153", "0183"):          # Hvidovre, Brøndby, Ishøj
            self.assertEqual(self.rows[code]["kystkode"], "SJ8")
            self.assertEqual(self.rows[code]["other_kystkoder"], "")

    def test_vallensbaek_is_coastal_by_the_2km_rule(self):
        """376 m of shore, 0 m from SJ8 — short, but real coast."""
        self.assertIn("0187", self.rows)
        self.assertEqual(self.rows["0187"]["kystkode"], "SJ8")

    def test_the_rule_is_recorded_in_every_row(self):
        self.assertTrue(all(r["rule"] == "longest_shared_coastline" for r in self.rows.values()))

    def test_landlocked_kommuner_have_no_row(self):
        for code in ("0657", "0151", "0147"):          # Herning, Ballerup, Frederiksberg
            self.assertNotIn(code, self.rows)


class Registry(unittest.TestCase):
    CLIMATE = ["sealevel_cm", "surge100_cm", "surge_freq_x", "rain100_1h_mm", "cloudbursts_yr",
               "weather_claims_1000", "flood_risk_area", "surge_dw_pct"]
    HORIZONS = ["today", "2070", "2120"]

    def test_every_climate_indicator_is_registered(self):
        for k in self.CLIMATE:
            self.assertIn(k, IND, k)
            self.assertEqual(IND[k]["group"], "Climate", k)
            self.assertEqual(IND[k]["level"], "kommune", k)
            self.assertEqual(IND[k]["direction"], "lower_better", k)
            self.assertTrue(IND[k].get("note"), k)
            self.assertTrue(IND[k].get("source"), k)
            self.assertEqual(IND[k]["calc"], "climate", k)

    def test_cloudburst_zones_are_out_of_this_release(self):
        """Dropped with the bluespot raster: no source, so no indicator."""
        self.assertNotIn("cloudburst_dw_pct", IND)

    def test_horizons_where_they_apply(self):
        for k in self.CLIMATE:
            if k in ("weather_claims_1000", "flood_risk_area"):
                self.assertNotIn("horizon", IND[k], k)
            else:
                self.assertEqual(IND[k]["horizon"], self.HORIZONS, k)


@unittest.skipUnless((PROC / "index.json").exists(), "climate index not built")
class ClimateIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = jload(PROC / "index.json")

    def test_every_kommune_present(self):
        self.assertEqual(len(self.d["kommune"]), 99)

    def test_landlocked_is_null_with_a_reason(self):
        h = self.d["kommune"]["0657"]["surge100_cm"]       # Herning
        self.assertIsNone(h["today"])
        self.assertEqual(h["reason"], "not coastal")

    def test_copenhagen_uses_one_published_stretch(self):
        """No arithmetic across stretches: the value is SJ7's own published figure."""
        k = self.d["kommune"]["0101"]
        self.assertEqual(k["kystkode"], "SJ7")
        self.assertEqual(k["other_kystkoder"], ["SJ8"])
        self.assertAlmostEqual(k["surge100_cm"]["today"], 156.85, places=1)

    def test_no_cloudburst_zone_field_left_in_the_index(self):
        self.assertFalse(any("cloudburst_dw_pct" in r for r in self.d["kommune"].values()))

    def test_rain_reaches_every_kommune(self):
        missing = [c for c, r in self.d["kommune"].items()
                   if r["rain100_1h_mm"]["today"] is None]
        self.assertLessEqual(len(missing), 1, f"only Christiansø may miss a row: {missing}")

    def test_ranges_carry_percentiles_and_scenarios(self):
        r = self.d["kommune"]["0101"]["surge100_cm"]["range"]["2070"]
        for k in ("p10", "p90", "low", "high"):
            self.assertIn(k, r)
        self.assertLess(r["p10"], r["p90"])


if __name__ == "__main__":
    unittest.main()
