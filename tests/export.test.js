/* src/export_core.js — the export model (spec §4.9, engineering brief §3).
   One test per builder: the header, the column count, no separator inside a cell, a source and an
   as-of on every row, and the kDKK rule (AC-X2). The registry objects here are the shapes
   data/processed/makro.json and cph.json really carry — the odd ones (a kDKK unit on a DKK value, a
   Copenhagen table id that only exists inside the source string) are the ones worth testing. */
const { test } = require("node:test");
const assert = require("node:assert");
const EC = require("../src/export_core.js");

const BUILT = "2026-09-24";
const CAT = {
  "dst/FOLK1A": { key: "dst/FOLK1A", label: "Danmarks Statistik FOLK1A", tables: "Population at the first day of the quarter",
                  asof: "2026-08-10", fetched: "2026-09-22", url: "https://api.statbank.dk/v1/tableinfo/FOLK1A",
                  licence: "free reuse with attribution" },
  "dst/INDKP101": { key: "dst/INDKP101", label: "Danmarks Statistik INDKP101", asof: "2025-12-01", fetched: "2026-09-22",
                    url: "https://api.statbank.dk/v1/tableinfo/INDKP101", licence: "free reuse with attribution" },
  "dst/BOL101": { key: "dst/BOL101", label: "Danmarks Statistik BOL101", asof: "2026-04-08", fetched: "2026-09-23",
                  url: "https://api.statbank.dk/v1/tableinfo/BOL101", licence: "free reuse with attribution" },
  "s30/KKBEF1": { key: "s30/KKBEF1", label: "Københavns Kommune KKBEF1", asof: "2026-08-06",
                  url: "https://api.statbank.dk/v1/s30/tableinfo/KKBEF1", licence: "free reuse with attribution" },
  bbr: { key: "bbr", label: "BBR via Datafordeler — housing stock", asof: "2026-09-15", licence: "free (Klimadatastyrelsen)",
         url: "https://datafordeler.dk/dataoversigt/bygnings-og-boligregistret-bbr/bbr-graphql/" },
  forecast: { key: "forecast", label: "Danmarks Statistik FRKM126 / FRDK126", asof: "2026-06-12", fetched: "2026-09-23",
              url: "https://api.statbank.dk/v1/tableinfo/FRKM126", licence: "free reuse with attribution" },
  "climate/climate_index": { key: "climate/climate_index", label: "Danmarks Statistik climate_index", asof: "",
                             fetched: "", licence: "free reuse with attribution" },
};
const GROWTH = { key: "growth", label: "Population growth", unit: "% / yr", fmt: "signpct1", level: "postnr",
                 direction: "higher_better", source: "DST FOLK1A (municipality, quarterly) · POSTNR1 (postal code, 1 Jan)",
                 tables: ["dst/FOLK1A"], asof: { kommune: "2025K3→2026K3", postnr: "2025→2026" } };
const INCOME = { key: "income", label: "Disposable income, average", unit: "kDKK / yr", fmt: "kdkk", level: "kommune",
                 direction: "higher_better", source: "DST INDKP101", tables: ["dst/INDKP101"], asof: { kommune: "2024" } };
const BBR = { key: "renters_bbr", label: "Rented dwellings (BBR)", unit: "% of dwellings", fmt: "pct0", level: "postnr",
              direction: "higher_better", source: "BBR via Datafordeler (Klimadatastyrelsen)",
              src_page: ["BBR via Datafordeler", "https://datafordeler.dk/bbr"], asof: { postnr: "BBR 2026-09-15" } };
const FC = { key: "fc_growth", label: "Projected population change 2026→2040", unit: "%", fmt: "signpct1",
             level: "kommune", direction: "neutral", source: "Danmarks Statistik FRKM126", asof: { kommune: "Projection 2026→2040 · DST 2026" },
             proj: { from: "2026", to: "2040", vintage: "2026", publisher: "DST", table: "FRKM126", src: { db: "", table: "FRKM126" } } };
const KK = { key: "new_stock", label: "Dwellings commissioned 2010+", unit: "% of dwellings", fmt: "pct0", level: "kvarter",
             direction: "neutral", source: "Københavns Kommune, KKBOL3", asof: { kvarter: "2026K1" } };
const SURGE = { key: "surge_dw_pct", label: "Dwellings in the storm-surge zone", unit: "% of dwellings", fmt: "pct1",
                level: "kommune", direction: "lower_better", group: "Climate", horizon: ["today", "2070", "2120"],
                source: "Kystdirektoratet, Kystplanlægger oversvømmelsesfare × BBR", asof: { kommune: "BBR × Klimaatlas v2025a" },
                climate_src: { publisher: "Kystdirektoratet", kind: "service_layer",
                               service: "https://gisportal.mst.dk/server/rest/services/x/MapServer" } };
const CRIME = { key: "crime_1000", label: "Reported offences", unit: "per 1,000 inh. · rolling 4Q", fmt: "per1000",
                level: "kommune", direction: "lower_better", source: "DST STRAF11 · FOLK1A", tables: ["dst/STRAF11", "dst/FOLK1A"],
                asof: { kommune: "2025K3→2026K2" } };
const NETDW = { key: "hist_net_dwell", label: "Net dwellings added", unit: "dwellings / 1,000 inh. / yr · 2020–2026",
                fmt: "signdec1", level: "kommune", direction: "neutral",
                source: "Danmarks Statistik BOL101 (dwelling stock, 1 January 2020 and 2026) and FOLK1A", asof: { kommune: "2020–2026" } };

const KOM = { code: "101", name: "København", pop: 660842, growth: 0.42, income: 291834, crime_1000: 89.93,
              fc_growth: 8.1, hist_net_dwell: 5.2, hist: { growth: { 2024: 0.93, 2025: 0.87, 2026: 0.42 }, income: { 2024: 291834 } } };
const POST = { nr: "2450", name: "København SV", muni: "101", pop: 39452, growth: -0.1, renters_bbr: 61,
               hist: { growth: { 2025: 5.8, 2026: -0.1 } } };
const LEVELS = [
  { level: "municipality", asofLevel: "kommune", inds: [GROWTH, INCOME, CRIME, FC, NETDW],
    rows: [{ o: KOM, code: "101", name: "København", parent_code: "", parent_name: "Denmark", region: "Hovedstaden", population: 660842 }] },
  { level: "postal_code", asofLevel: "postnr", inds: [GROWTH, INCOME, BBR],
    rows: [{ o: POST, muni: KOM, code: "2450", name: "København SV", parent_code: "101", parent_name: "København",
             region: "Hovedstaden", population: 39452 }] },
];

/* the same two accessors app.js passes in: which periods an observation has, and where a value is
   read from when the area does not publish it (spec §2.4, §4.9) */
const LATEST = "2026";
function periods(i, o, lvl, inherited) {
  const latest = o[i.key];
  if (i.proj) return latest == null ? [] : [{ period: `${i.proj.from}→${i.proj.to}`, kind: "projection", value: latest, asof: (i.asof || {})[lvl] || "" }];
  const h = (o.hist || {})[i.key] || {};
  const ys = Object.keys(h);
  if (latest == null && !ys.length) return [];
  if (!ys.length) return [{ period: (i.asof || {})[lvl] || LATEST, kind: "auto", value: latest, asof: (i.asof || {})[lvl] || "" }];
  const all = [...new Set(latest == null ? ys : ys.concat(LATEST))].sort();
  const out = all.map(y => ({ period: y, kind: "year", value: y === LATEST && latest != null ? latest : h[y], asof: (i.asof || {})[lvl] || "" }))
                 .filter(p => p.value != null);
  return inherited ? out.slice(-1) : out;
}
function inherited(i, r) {
  if (!r.muni) return null;
  if (r.o[i.key] != null || Object.keys((r.o.hist || {})[i.key] || {}).length) return null;
  return r.muni[i.key] == null ? null : { o: r.muni, code: r.muni.code };
}
const ctx = (levels) => ({ levels, cat: CAT, built: BUILT, periods, inherited });
const col = (row, name, cols) => row[(cols || EC.AREA_COLS).indexOf(name)];

/* ---------- CSV rules ---------- */
test("csv: header first, `;` separated, no separator or newline inside a cell", () => {
  const lines = EC.csvLines(["a", "b"], [["x;y", "line\nbreak"], [1.5, null]]);
  assert.strictEqual(lines[0], "a;b");
  assert.strictEqual(lines[1], "x,y;line break");
  assert.strictEqual(lines[2], "1.5;");
  lines.forEach(l => assert.strictEqual(l.split(";").length, 2, `wrong cell count in ${l}`));
});

test("csv: `.` decimals, no grouping, no NaN or Infinity", () => {
  assert.strictEqual(EC.cell(1234567.89), "1234567.89");
  assert.strictEqual(EC.cell(NaN), "");
  assert.strictEqual(EC.cell(Infinity), "");
  assert.strictEqual(EC.cell(0), "0");
});

/* ---------- the unit fix (AC-X2) ---------- */
test("kDKK: a kdkk indicator is written in DKK, losslessly", () => {
  const u = EC.unitValue(INCOME, 291834);
  assert.strictEqual(u.unit, "DKK / yr");
  assert.strictEqual(u.value, 291834);
});

test("kDKK: a value left in kDKK units is converted, so the label always matches", () => {
  const u = EC.unitValue({ key: "x", unit: "kDKK / yr", fmt: "int" }, 291834);
  assert.strictEqual(u.value, 291.834);
  assert.ok(Math.abs(u.value) < EC.KDKK_MAX);
  assert.strictEqual(EC.unitValue({ key: "x", unit: "kDKK / yr", fmt: "int" }, 296).value, 296);
});

test("kDKK: no row of any builder says kDKK with a value of 10 000 or more (AC-X2)", () => {
  const rows = EC.areaRows(ctx(LEVELS));
  rows.forEach(r => { const u = col(r, "unit"), v = col(r, "value");
    if (/kDKK/.test(String(u))) assert.ok(Math.abs(Number(v)) < EC.KDKK_MAX, `${col(r, "indicator")} ${u} ${v}`); });
  const inc = rows.filter(r => col(r, "indicator") === "income");
  assert.ok(inc.length, "no income rows");
  inc.forEach(r => assert.ok(/^DKK/.test(col(r, "unit")), col(r, "unit")));
});

/* ---------- the source columns (engineering brief §3.2) ---------- */
test("source columns: a StatBank indicator joins to the catalogue", () => {
  const s = EC.indSource(GROWTH, { cat: CAT, built: BUILT, asof: "2025→2026" });
  assert.strictEqual(s.table_id, "FOLK1A");
  assert.strictEqual(s.source_url, "https://api.statbank.dk/v1/tableinfo/FOLK1A");
  assert.strictEqual(s.as_of, "2025→2026");
  assert.strictEqual(s.fetched, "2026-09-22");
  assert.strictEqual(s.licence, "free reuse with attribution");
  assert.match(s.source, /FOLK1A/);
});

test("source columns: several tables are all named", () => {
  assert.strictEqual(EC.indSource(CRIME, { cat: CAT, built: BUILT }).table_id, "STRAF11 FOLK1A");
});

test("source columns: a projection names its own table and vintage table", () => {
  const s = EC.indSource(FC, { cat: CAT, built: BUILT, asof: "Projection 2026→2040 · DST 2026" });
  assert.strictEqual(s.table_id, "FRKM126");
  assert.strictEqual(s.source_url, "https://api.statbank.dk/v1/tableinfo/FRKM126");
  assert.strictEqual(s.fetched, "2026-09-23");
});

test("source columns: a register or curated layer says so instead of leaving the cell blank", () => {
  const s = EC.indSource(BBR, { cat: CAT, built: BUILT, asof: "BBR 2026-09-15" });
  assert.strictEqual(s.table_id, EC.NO_TABLE);
  assert.strictEqual(s.source_url, "https://datafordeler.dk/bbr");
  assert.strictEqual(s.licence, "free (Klimadatastyrelsen)");   /* joined through the page name */
});

test("source columns: a Copenhagen table id is parsed out of the source string", () => {
  const s = EC.indSource({ key: "growth", source: "Københavns Kommune, KKBEF1", asof: { kvarter: "2026K3" } }, { cat: CAT, built: BUILT, asof: "2026K3" });
  assert.strictEqual(s.table_id, "KKBEF1");
  assert.strictEqual(s.source_url, "https://api.statbank.dk/v1/s30/tableinfo/KKBEF1");
  /* KKBOL3 is not in this catalogue at all — the URL is still built from the id */
  assert.strictEqual(EC.indSource(KK, { cat: CAT, built: BUILT }).source_url, "https://api.statbank.dk/v1/s30/tableinfo/KKBOL3");
});

test("source columns: a table named only in prose is still found", () => {
  const s = EC.indSource(NETDW, { cat: CAT, built: BUILT, asof: "2020–2026" });
  assert.strictEqual(s.table_id, "BOL101");
  assert.strictEqual(s.source_url, "https://api.statbank.dk/v1/tableinfo/BOL101");
});

test("source columns: a climate indicator carries the publisher's service", () => {
  const s = EC.indSource(SURGE, { cat: CAT, built: BUILT, asof: "BBR × Klimaatlas v2025a" });
  assert.strictEqual(s.table_id, EC.NO_TABLE);
  assert.match(s.source_url, /^https:\/\/gisportal\.mst\.dk\//);
  assert.strictEqual(s.as_of, "BBR × Klimaatlas v2025a");
  assert.strictEqual(s.fetched, BUILT, "an empty catalogue fetch date falls back to the build date");
});

test("source columns: as_of and source are never blank", () => {
  const s = EC.indSource({ key: "mystery" }, { cat: CAT, built: BUILT });
  assert.ok(s.source.length, "blank source");
  assert.strictEqual(s.as_of, BUILT);
  assert.strictEqual(s.table_id, EC.NO_TABLE);
});

/* ---------- period_type and value_type ---------- */
test("period_type reads the publisher's own label", () => {
  assert.strictEqual(EC.periodType("2024"), "year");
  assert.strictEqual(EC.periodType("2024K3"), "quarter");
  assert.strictEqual(EC.periodType("2026M08"), "month");
  assert.strictEqual(EC.periodType("2025/2026"), "school_year");
  assert.strictEqual(EC.periodType("school year 2025/2026"), "school_year");
  assert.strictEqual(EC.periodType("2025K3→2026K3"), "window");
  assert.strictEqual(EC.periodType("2020–2026"), "window");
  assert.strictEqual(EC.periodType("2026-09-15"), "snapshot");
  assert.strictEqual(EC.periodType("BBR 2026-09-15"), "snapshot");
  assert.strictEqual(EC.periodType("2070", "horizon"), "horizon");
  assert.strictEqual(EC.periodType("2026→2040", "projection"), "projection");
});

test("value_type: actual, projection, inherited, derived", () => {
  assert.strictEqual(EC.valueType(GROWTH, {}), "actual");
  assert.strictEqual(EC.valueType(FC, {}), "projection");
  assert.strictEqual(EC.valueType(GROWTH, { inherited: true }), "inherited");
  assert.strictEqual(EC.valueType(CRIME, {}), "derived", "a per-1,000 rate is arithmetic on two published counts");
  assert.strictEqual(EC.valueType(NETDW, {}), "derived");
  assert.strictEqual(EC.valueType(SURGE, { kind: "horizon", horizon: "today" }), "derived");
  assert.strictEqual(EC.valueType(SURGE, { kind: "horizon", horizon: "2120" }), "projection");
  assert.strictEqual(EC.valueType(INCOME, {}), "actual", "AC-X2: income is a published cell");
});

/* ---------- areas_long (AC-X1, AC-X3, AC-X4) ---------- */
test("areas_long: the header is the long schema of spec §4.9, and every row matches it", () => {
  assert.deepStrictEqual(EC.AREA_COLS, ["level", "code", "name", "parent_code", "parent_name", "region",
    "population", "indicator", "label", "unit", "period", "period_type", "value", "value_type",
    "inherited_from", "direction", "source", "table_id", "source_url", "as_of", "fetched", "licence"]);
  const lines = EC.csvLines(EC.AREA_COLS, EC.areaRows(ctx(LEVELS)));
  assert.strictEqual(lines[0], "level;code;name;parent_code;parent_name;region;population;indicator;label;unit;period;period_type;value;value_type;inherited_from;direction;source;table_id;source_url;as_of;fetched;licence");
  lines.forEach(l => assert.strictEqual(l.split(";").length, EC.AREA_COLS.length, l.slice(0, 120)));
});

test("areas_long: every row has a source and an as_of (AC-X4)", () => {
  const rows = EC.areaRows(ctx(LEVELS));
  assert.ok(rows.length > 10);
  rows.forEach(r => {
    assert.ok(String(col(r, "source")).trim().length, `blank source: ${r}`);
    assert.ok(String(col(r, "as_of")).trim().length, `blank as_of: ${r}`);
    assert.ok(String(col(r, "table_id")).trim().length, `blank table_id: ${r}`);
  });
});

test("areas_long: a municipality figure on a postal code is inherited and names where from (AC-X4)", () => {
  const rows = EC.areaRows(ctx(LEVELS)).filter(r => col(r, "level") === "postal_code");
  const inc = rows.filter(r => col(r, "indicator") === "income");
  assert.strictEqual(inc.length, 1, "an inherited figure is written once, for the latest period");
  assert.strictEqual(col(inc[0], "value_type"), "inherited");
  assert.strictEqual(col(inc[0], "inherited_from"), "101");
  assert.strictEqual(col(inc[0], "value"), 291834);
  /* the postal code's own history stays its own */
  const own = rows.filter(r => col(r, "indicator") === "growth");
  assert.strictEqual(own.length, 2);
  own.forEach(r => { assert.strictEqual(col(r, "value_type"), "actual"); assert.strictEqual(col(r, "inherited_from"), ""); });
});

test("areas_long: no level is `project` or `macro` (AC-X3)", () => {
  const levels = new Set(EC.areaRows(ctx(LEVELS)).map(r => col(r, "level")));
  assert.ok(!levels.has("project") && !levels.has("macro"), [...levels].join(","));
  assert.deepStrictEqual([...levels].sort(), ["municipality", "postal_code"]);
});

test("areas_long: a projection carries its window and is never labelled actual", () => {
  const r = EC.areaRows(ctx(LEVELS)).find(x => col(x, "indicator") === "fc_growth");
  assert.strictEqual(col(r, "period"), "2026→2040");
  assert.strictEqual(col(r, "period_type"), "projection");
  assert.strictEqual(col(r, "value_type"), "projection");
});

test("areas_long: a snapshot carries the publisher's own stamp as its period", () => {
  const r = EC.areaRows(ctx(LEVELS)).find(x => col(x, "indicator") === "renters_bbr");
  assert.strictEqual(col(r, "period"), "BBR 2026-09-15");
  assert.strictEqual(col(r, "period_type"), "snapshot");
});

/* ---------- the test property (AC-TP4) ---------- */
test("test property: the pin's three columns come first and every row has a source (AC-TP4)", () => {
  const rows = EC.propertyRows({ ...ctx(LEVELS), label: "Test property", lat: 55.6545, lon: 12.539 });
  const lines = EC.csvLines(EC.PROP_COLS, rows);
  assert.ok(lines[0].startsWith("property_label;lat;lon;level;code;"), lines[0].slice(0, 60));
  rows.forEach(r => {
    assert.strictEqual(r.length, EC.PROP_COLS.length);
    assert.strictEqual(r[0], "Test property");
    assert.strictEqual(r[1], 55.6545);
    assert.ok(String(col(r, "source", EC.PROP_COLS)).trim().length, "blank source");
    assert.ok(String(col(r, "as_of", EC.PROP_COLS)).trim().length, "blank as_of");
  });
});

test("nearby: kind, name, distance and a source per row", () => {
  const rows = EC.nearbyRows([
    { kind: "infra", name: "Metro M5, phase 1", type: "Metro", status: "Decided", distance_m: 412.7,
      source: "Anlægsstatus 1H 2026", source_url: "https://metroselskabet.dk/m5/" },
    { kind: "school", name: "Skolen på Islands Brygge", type: "Folkeskole", distance_m: 980,
      source: "Uddannelsesstatistik.dk (STIL)" }]);
  assert.strictEqual(EC.NEARBY_COLS.join(";"), "kind;name;type;status;distance_m;source;source_url");
  assert.strictEqual(rows[0][4], 413, "distance is whole metres");
  rows.forEach(r => { assert.strictEqual(r.length, EC.NEARBY_COLS.length); assert.ok(String(r[5]).length, "blank source"); });
});

/* ---------- projects (AC-X3) ---------- */
test("projects: its own schema, no indicator column, one row per project (AC-X3)", () => {
  const rows = EC.projectRows([{ p: { id: "m5-phase-1", name: "Metro M5, phase 1", type: "metro", status: "decided",
      notes: "Alignment is not published; the line is drawn through the stations.", open_year: 2036, budget_mdkk: null,
      agency: "Metroselskabet", kommuner: ["101"], schematic: true, source_url: "https://metroselskabet.dk/m5/", updated: "2026-09-23" },
    geometry_kind: "schematic", length_km: 7.123, stations: 5, municipalities: ["101"], postal_codes: ["2300", "2450"], quarters: [] }]);
  assert.ok(!EC.PROJECT_COLS.includes("indicator"));
  assert.ok(!EC.PROJECT_COLS.includes("value"));
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].length, EC.PROJECT_COLS.length);
  const c = n => rows[0][EC.PROJECT_COLS.indexOf(n)];
  assert.strictEqual(c("opening"), 2036);
  assert.strictEqual(c("length_km"), 7.12);
  assert.strictEqual(c("postal_codes"), "2300 2450");
  assert.strictEqual(c("budget_mdkk"), "");
  const lines = EC.csvLines(EC.PROJECT_COLS, rows);
  lines.forEach(l => assert.strictEqual(l.split(";").length, EC.PROJECT_COLS.length, l));
});

/* ---------- the national series ---------- */
test("national series: long schema, period_type month or quarter, source on every row", () => {
  const rows = EC.nationalRows({ cat: CAT, built: BUILT,
    latest: { cpi: { t: "2026M08", v: 102.58, label: "Consumer price index", unit: "idx", src: "DST PRIS01" },
              rate_policy: { t: "2026K2", v: 1.6, label: "Policy rate", unit: "%", src: "Nationalbanken" } },
    series: { cpi: [{ t: "2026M07", v: 102.3 }, { t: "2026M08", v: 102.58 }, { t: "2026M09", v: null }],
              rate_policy: [{ t: "2026K2", v: 1.6 }] } });
  assert.strictEqual(rows.length, 3, "a null value is not a row");
  rows.forEach(r => {
    assert.strictEqual(r.length, EC.AREA_COLS.length);
    assert.strictEqual(col(r, "level"), "denmark");
    assert.ok(String(col(r, "source")).length && String(col(r, "as_of")).length);
    assert.strictEqual(col(r, "value_type"), "actual");
  });
  assert.strictEqual(col(rows[0], "period_type"), "month");
  assert.strictEqual(col(rows[0], "table_id"), "PRIS01");
  assert.strictEqual(col(rows[2], "period_type"), "quarter");
  assert.strictEqual(col(rows[2], "table_id"), EC.NO_TABLE, "a publisher with no StatBank table says so");
});

/* ---------- the sources catalogue ---------- */
test("sources: the spec's nine columns, an empty fetch date falls back to the build date", () => {
  assert.deepStrictEqual(EC.SOURCE_COLS, ["key", "label", "publisher", "tables", "as_of", "fetched", "url", "licence", "used_for"]);
  const c = { sources: [CAT["dst/FOLK1A"], CAT.bbr, CAT["s30/KKBEF1"]], built: BUILT, usedFor: x => `used by ${x.key}` };
  const recs = EC.sourceRecs(c), rows = EC.sourceRows(c);
  assert.strictEqual(recs[0].publisher, "Danmarks Statistik");
  assert.strictEqual(recs[1].publisher, "BBR via Datafordeler");
  assert.strictEqual(recs[2].publisher, "Københavns Kommune");
  assert.strictEqual(recs[1].fetched, BUILT);
  assert.strictEqual(recs[1].build_fetched, true);
  assert.strictEqual(recs[0].build_fetched, false);
  assert.strictEqual(recs[0].table_id, "FOLK1A");
  rows.forEach(r => assert.strictEqual(r.length, EC.SOURCE_COLS.length));
  assert.strictEqual(rows[0][EC.SOURCE_COLS.indexOf("used_for")], "used by dst/FOLK1A");
  EC.csvLines(EC.SOURCE_COLS, rows).forEach(l => assert.strictEqual(l.split(";").length, EC.SOURCE_COLS.length, l));
});

/* ---------- climate exposure ---------- */
test("climate exposure: one row per level × horizon, a future horizon is a projection", () => {
  const rows = EC.climateRows({ ind: SURGE, cat: CAT, built: BUILT, rows: [
    { level: "municipality", code: "101", name: "København", parent_name: "Denmark", horizon: "today",
      zone_year: "2020", pct: 3.64, zone_km2: 11.579, as_of: "BBR × Klimaatlas v2025a" },
    { level: "postal_code", code: "1050", name: "København K", parent_code: "101", parent_name: "København",
      horizon: "2120", zone_year: "2120", dwellings: 24950, in_zone: 888, pct: 3.56, as_of: "BBR × Klimaatlas v2025a" }] });
  assert.strictEqual(EC.CLIMATE_COLS[0], "level");
  assert.ok(EC.CLIMATE_COLS.includes("dwellings_in_zone") && EC.CLIMATE_COLS.includes("horizon"));
  rows.forEach(r => {
    assert.strictEqual(r.length, EC.CLIMATE_COLS.length);
    const c = n => r[EC.CLIMATE_COLS.indexOf(n)];
    assert.ok(String(c("source")).length && String(c("as_of")).length, "blank source or as_of");
    assert.match(String(c("source_url")), /^https:/);
  });
  const vt = n => rows[n][EC.CLIMATE_COLS.indexOf("value_type")];
  assert.strictEqual(vt(0), "derived");
  assert.strictEqual(vt(1), "projection");
  assert.strictEqual(rows[1][EC.CLIMATE_COLS.indexOf("dwellings_in_zone")], 888);
});

/* ---------- file names ---------- */
test("file names carry the data's build date", () => {
  assert.strictEqual(EC.fileName("areas_long", BUILT), "areas_long_2026-09-24.csv");
  assert.strictEqual(EC.fileName("projects"), "projects_data.csv");
});
