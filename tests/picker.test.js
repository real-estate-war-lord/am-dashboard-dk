/* The shared IndicatorPicker / PeriodControl logic (src/picker_core.js). The picker is the one
   control every view uses (spec §4.2, owner amendment A4 "consistency"), so the rules it applies —
   group order, what the search matches, which period control an indicator needs, what the row tag
   says — are pinned here rather than only in a browser test.
   Run with `make test-js` or `node --test tests/`. */
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const P = require("../src/picker_core.js");

/* a few registry rows, shaped exactly as makro.json builds them */
const GROWTH = { key: "growth", label: "Population growth", short: "Growth", unit: "% / yr", group: "Demographics" };
const UNEMP = { key: "unemp", label: "Unemployment rate", short: "Unemp.", unit: "%", group: "Income & jobs", direction: "lower_better" };
const RENT = { key: "rent_private", label: "Private rental rent", short: "Rent", unit: "DKK / m² / yr", group: "Rents" };
const FC = { key: "fc_growth", label: "Projected population growth 2026→2040", short: "Outlook 2040", unit: "%",
             group: "Outlook", proj: { from: "2026", to: "2040", publisher: "DST", vintage: "2026", table: "FRKM126" } };
const SURGE = { key: "surge_dw_pct", label: "Dwellings in the surge zone", short: "Dwellings at surge risk",
                unit: "% of dwellings", group: "Climate", direction: "lower_better", horizon: ["today", "2070", "2120"] };
const SEA = { key: "sealevel_cm", label: "Mean sea level rise", short: "Sea level", unit: "cm", group: "Climate" };
const ODD = { key: "odd", label: "Something new", unit: "n" };            /* no group at all */
const ALL = [SURGE, GROWTH, FC, UNEMP, SEA, RENT, ODD];

/* ---------- groups ---------- */
test("GROUP_ORDER is the spec's twelve groups, Climate last", () => {
  assert.strictEqual(P.GROUP_ORDER.length, 12);
  assert.strictEqual(P.GROUP_ORDER[0], "Demographics");
  assert.strictEqual(P.GROUP_ORDER[P.GROUP_ORDER.length - 1], "Climate");
});
test("grouped() returns GROUP_ORDER, skips empty groups and puts the unknown ones in Other", () => {
  const g = P.grouped(ALL);
  assert.deepStrictEqual(g.map(x => x.name),
    ["Demographics", "Income & jobs", "Rents", "Outlook", "Climate", "Other"]);
  assert.deepStrictEqual(g[4].inds.map(i => i.key), ["surge_dw_pct", "sealevel_cm"]);
  assert.deepStrictEqual(g[5].inds.map(i => i.key), ["odd"]);
});
test("grouped() keeps every indicator exactly once", () => {
  const out = P.grouped(ALL).flatMap(g => g.inds.map(i => i.key)).sort();
  assert.deepStrictEqual(out, ALL.map(i => i.key).sort());
});
test("only Outlook and Climate carry a group pill", () => {
  const pills = {};
  P.grouped(ALL).forEach(g => { if (g.pill) pills[g.name] = g.pill; });
  assert.deepStrictEqual(pills, { Outlook: "Projection", Climate: "Horizon" });
});
test("grouped() tolerates an empty list and a custom order", () => {
  assert.deepStrictEqual(P.grouped([]), []);
  assert.deepStrictEqual(P.grouped([GROWTH, UNEMP], ["Income & jobs", "Demographics"]).map(g => g.name),
    ["Income & jobs", "Demographics"]);
});

/* ---------- search ---------- */
test("an empty query matches everything", () => {
  assert.strictEqual(P.filter(ALL, "").length, ALL.length);
  assert.strictEqual(P.filter(ALL, "   ").length, ALL.length);
  assert.strictEqual(P.filter(ALL, null).length, ALL.length);
});
test("'surge' matches exactly the rows whose own text says surge (AC-I3)", () => {
  assert.deepStrictEqual(P.filter(ALL, "surge").map(i => i.key), ["surge_dw_pct"]);
  assert.deepStrictEqual(P.filter(ALL, "SuRgE").map(i => i.key), ["surge_dw_pct"]);
});
test("search covers label, short, group and unit", () => {
  assert.deepStrictEqual(P.filter(ALL, "unemp").map(i => i.key), ["unemp"]);          /* short */
  assert.deepStrictEqual(P.filter(ALL, "climate").map(i => i.key), ["surge_dw_pct", "sealevel_cm"]);  /* group */
  assert.deepStrictEqual(P.filter(ALL, "dkk").map(i => i.key), ["rent_private"]);     /* unit */
});
test("every word has to hit, so a second word narrows", () => {
  assert.deepStrictEqual(P.filter(ALL, "surge dwellings").map(i => i.key), ["surge_dw_pct"]);
  assert.deepStrictEqual(P.filter(ALL, "surge sea").map(i => i.key), []);
  assert.deepStrictEqual(P.filter(ALL, "population growth").map(i => i.key), ["growth", "fc_growth"]);
});
test("a query that matches nothing returns nothing rather than everything", () => {
  assert.deepStrictEqual(P.filter(ALL, "xyzzy"), []);
});

/* ---------- period mode (spec §4.3) ---------- */
test("periodMode: Climate → horizon, Outlook → projection, everything else → year", () => {
  assert.strictEqual(P.periodMode(SURGE), "horizon");
  assert.strictEqual(P.periodMode(SEA), "horizon");
  assert.strictEqual(P.periodMode(FC), "projection");
  assert.strictEqual(P.periodMode(GROWTH), "year");
  assert.strictEqual(P.periodMode(UNEMP), "year");
  assert.strictEqual(P.periodMode(ODD), "year");
  assert.strictEqual(P.periodMode(null), "year");
});
test("each mode owns one URL key; the projection badge owns none", () => {
  assert.strictEqual(P.PERIOD_KEY[P.periodMode(GROWTH)], "y");
  assert.strictEqual(P.PERIOD_KEY[P.periodMode(SURGE)], "hz");
  assert.strictEqual(P.PERIOD_KEY[P.periodMode(FC)], "");
});
test("Climate wins over proj — a climate indicator with a vintage is still a horizon", () => {
  assert.strictEqual(P.periodMode({ group: "Climate", proj: { from: "2026", to: "2040" } }), "horizon");
});

/* ---------- availability tag ---------- */
test("availTag: an inherited row says muni, whatever else it is", () => {
  assert.strictEqual(P.availTag(UNEMP, { inherited: true, years: ["2016", "2017"] }).text, "muni");
  assert.strictEqual(P.availTag(UNEMP, { inherited: true }).cls, "tag-muni");
});
test("availTag: history shows its first year, a single as-of says snapshot", () => {
  assert.strictEqual(P.availTag(GROWTH, { years: ["2016", "2017", "2026"] }).text, "2016–");
  assert.strictEqual(P.availTag(GROWTH, { years: ["2026"] }).text, "snapshot");
  assert.strictEqual(P.availTag(GROWTH, {}).text, "snapshot");
  assert.strictEqual(P.availTag(GROWTH, { years: [] }).text, "snapshot");
});
test("availTag: Climate says horizons and Outlook says its window", () => {
  assert.strictEqual(P.availTag(SURGE, { years: ["2026"] }).text, "horizons");
  assert.strictEqual(P.availTag(FC, {}).text, "2026→2040");
  assert.match(P.availTag(FC, {}).title, /DST 2026/);
});
test("availTag always returns a non-empty text and a class", () => {
  ALL.forEach(i => {
    const t = P.availTag(i, {});
    assert.ok(t.text, `${i.key} has no tag text`);
    assert.match(t.cls, /^tag-/, `${i.key} tag class is ${t.cls}`);
  });
});

/* ---------- keyboard ---------- */
test("step() moves one row and clamps at both ends", () => {
  assert.strictEqual(P.step(0, 1, 5), 1);
  assert.strictEqual(P.step(4, 1, 5), 4);
  assert.strictEqual(P.step(0, -1, 5), 0);
  assert.strictEqual(P.step(3, -1, 5), 2);
});
test("step() from nothing active lands on the first row going down, the last going up", () => {
  assert.strictEqual(P.step(-1, 1, 5), 0);
  assert.strictEqual(P.step(null, 1, 5), 0);
  assert.strictEqual(P.step(-1, -1, 5), 4);
});
test("step() on an empty list stays at nothing active", () => {
  assert.strictEqual(P.step(-1, 1, 0), -1);
  assert.strictEqual(P.step(2, -1, 0), -1);
});
