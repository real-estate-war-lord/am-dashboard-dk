/* The climate layer's pure logic (src/climate_core.js): the point-in-extent test that answers
   "is this address in the 100-year zone", the `hz=` / `clim=` hash round-trip, and the label that
   has to name both calendars. Run with `make test-js` or `node --test tests/`. */
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const C = require("../src/climate_core.js");

/* a 1° square with a 0.2° square hole punched in the middle of it */
const SQUARE = { type: "Polygon", coordinates: [
  [[12.0, 55.0], [13.0, 55.0], [13.0, 56.0], [12.0, 56.0], [12.0, 55.0]],
  [[12.4, 55.4], [12.6, 55.4], [12.6, 55.6], [12.4, 55.6], [12.4, 55.4]]] };
/* two disjoint squares, the second one far to the east — a kommune's extent is always many parts */
const MULTI = { type: "MultiPolygon", coordinates: [
  [[[12.0, 55.0], [12.2, 55.0], [12.2, 55.2], [12.0, 55.2], [12.0, 55.0]]],
  [[[14.0, 57.0], [14.2, 57.0], [14.2, 57.2], [14.0, 57.2], [14.0, 57.0]]]] };
const fc = (...geoms) => ({ type: "FeatureCollection", features: geoms.map(g => ({ type: "Feature", properties: {}, geometry: g })) });

test("inside the outer ring", () => {
  assert.strictEqual(C.gjHit(55.1, 12.1, SQUARE), true);
  assert.strictEqual(C.gjHit(55.9, 12.9, SQUARE), true);
});

test("outside the polygon altogether", () => {
  assert.strictEqual(C.gjHit(54.9, 12.5, SQUARE), false, "south of it");
  assert.strictEqual(C.gjHit(55.5, 11.9, SQUARE), false, "west of it");
  assert.strictEqual(C.gjHit(57.0, 20.0, SQUARE), false, "nowhere near it");
});

test("a hole is not in the zone — a polder inside a flood extent stays dry", () => {
  assert.strictEqual(C.gjHit(55.5, 12.5, SQUARE), false, "dead centre of the hole");
  assert.strictEqual(C.gjHit(55.45, 12.45, SQUARE), false, "inside the hole, off centre");
  assert.strictEqual(C.gjHit(55.35, 12.5, SQUARE), true, "just south of the hole, still in the zone");
});

test("multipolygon: every part counts, and the gap between them does not", () => {
  assert.strictEqual(C.gjHit(55.1, 12.1, MULTI), true, "first part");
  assert.strictEqual(C.gjHit(57.1, 14.1, MULTI), true, "second part");
  assert.strictEqual(C.gjHit(56.0, 13.0, MULTI), false, "between the two parts");
});

test("a point on the edge is decided by the half-open rule, not by luck", () => {
  /* Ray casting here uses the half-open convention: a vertex exactly at the test latitude counts
     as below it. That makes the south and west edges inside and the north and east edges outside —
     deterministic, total, and the reason two adjacent extents can never both claim the same point.
     A dwelling exactly on a zone boundary is counted once, by exactly one polygon. */
  const BOX = { type: "Polygon", coordinates: [[[12, 55], [13, 55], [13, 56], [12, 56], [12, 55]]] };
  assert.strictEqual(C.gjHit(55.0, 12.5, BOX), true, "south edge: inside");
  assert.strictEqual(C.gjHit(55.5, 12.0, BOX), true, "west edge: inside");
  assert.strictEqual(C.gjHit(56.0, 12.5, BOX), false, "north edge: outside");
  assert.strictEqual(C.gjHit(55.5, 13.0, BOX), false, "east edge: outside");
  assert.strictEqual(C.gjHit(55.0, 12.0, BOX), true, "SW corner: inside");
  assert.strictEqual(C.gjHit(56.0, 13.0, BOX), false, "NE corner: outside");
  /* the same point can only belong to one of two boxes that share an edge */
  const EAST = { type: "Polygon", coordinates: [[[13, 55], [14, 55], [14, 56], [13, 56], [13, 55]]] };
  assert.notStrictEqual(C.gjHit(55.5, 13.0, BOX), C.gjHit(55.5, 13.0, EAST),
    "a point on a shared edge belongs to exactly one of the two");
});

test("a geometry we do not draw is not a hit", () => {
  assert.strictEqual(C.gjHit(55.5, 12.5, null), false);
  assert.strictEqual(C.gjHit(55.5, 12.5, { type: "LineString", coordinates: [[12, 55], [13, 56]] }), false);
});

test("inZone: nothing loaded is null, not 'no'", () => {
  assert.strictEqual(C.inZone(55.1, 12.1, []), null, "no file yet — the sheet says '…', never 'no'");
  assert.strictEqual(C.inZone(55.1, 12.1, [null, undefined]), null);
  assert.strictEqual(C.inZone(55.1, 12.1, [fc(SQUARE)]), true);
  assert.strictEqual(C.inZone(54.0, 12.1, [fc(SQUARE)]), false);
  assert.strictEqual(C.inZone(57.1, 14.1, [fc(SQUARE), fc(MULTI)]), true, "any collection may hold it");
});

test("hz= parses the three published horizons", () => {
  assert.strictEqual(C.hzParse({ hz: "today" }), "today");
  assert.strictEqual(C.hzParse({ hz: "2070" }), "2070");
  assert.strictEqual(C.hzParse({ hz: "2120" }), "2120");
});

test("hz= falls back to today for anything else", () => {
  /* 2050 and 2100 were the ids before v2.6 renamed them to the Klimaatlas periods, so an old
     link is exactly the case this has to survive */
  ["2050", "2100", "banana", "", "TODAY", "20700"].forEach(v =>
    assert.strictEqual(C.hzParse({ hz: v }), "today", `hz=${v} should fall back`));
  assert.strictEqual(C.hzParse({}), "today", "no hz at all");
  assert.strictEqual(C.hzParse(undefined), "today", "no query at all");
});

test("hz= serialises only when it is not the default", () => {
  assert.deepStrictEqual(C.hzSerialise("today"), [], "the default stays out of the hash");
  assert.deepStrictEqual(C.hzSerialise("2070"), ["hz=2070"]);
  assert.deepStrictEqual(C.hzSerialise("2120"), ["hz=2120"]);
  assert.deepStrictEqual(C.hzSerialise("2050"), [], "an invalid value is never written out");
});

test("hz= round-trips through parse and serialise", () => {
  C.CLIM_HZ.forEach(h => {
    const parts = C.hzSerialise(h);
    const q = {}; parts.forEach(p => { const [k, v] = p.split("="); q[k] = v; });
    assert.strictEqual(C.hzParse(q), h, `${h} survives the round trip`);
  });
});

test("clim= parses, and clim=none is a state we keep", () => {
  assert.deepStrictEqual([...C.climFilterParse({})].sort(), ["areas", "surge"], "no parameter means both");
  assert.deepStrictEqual([...C.climFilterParse({ clim: "areas,surge" })].sort(), ["areas", "surge"]);
  assert.deepStrictEqual([...C.climFilterParse({ clim: "areas" })], ["areas"]);
  assert.deepStrictEqual([...C.climFilterParse({ clim: "none" })], [], "both switched off is not the default");
  assert.deepStrictEqual([...C.climFilterParse({ clim: "areas,banana" })], ["areas"], "an unknown layer is dropped");
});

test("clim= serialises an empty set as none, so it survives a reload", () => {
  assert.deepStrictEqual(C.climFilterSerialise(new Set()), ["clim=none"]);
  assert.deepStrictEqual(C.climFilterSerialise(new Set(["areas"])), ["clim=areas"]);
  const back = C.climFilterParse({ clim: C.climFilterSerialise(new Set())[0].split("=")[1] });
  assert.strictEqual(back.size, 0, "none round-trips to the empty set, not back to the default");
});

test("every horizon label names both calendars", () => {
  C.CLIM_HZ.forEach(h => {
    const l = C.hzLabel(h);
    assert.ok(l.includes("zones: Kystdirektoratet"), `${h} names the zone publisher`);
    assert.ok(l.includes(C.CLIM_ZONE_YEAR[h]), `${h} names the published extent year`);
    assert.ok(l.includes("figures: Klimaatlas"), `${h} names where the figures come from`);
  });
});

test("2120 says which Klimaatlas period it is, and that it is the latest one", () => {
  const l = C.hzLabel("2120");
  assert.ok(l.includes("2071–2100, latest Klimaatlas period"),
    `2120 must not silently claim to be a 2120 climate period — got: ${l}`);
  assert.ok(l.startsWith("2120 — zones: Kystdirektoratet 2120"));
});

test("the other two labels carry their own periods", () => {
  assert.ok(C.hzLabel("today").includes("1981–2010"), "today is the reference period");
  assert.ok(C.hzLabel("today").startsWith("Today — zones: Kystdirektoratet 2020"));
  assert.ok(C.hzLabel("2070").includes("2041–70"), "2070 is the 2041–70 period");
  assert.ok(C.hzLabel("2070").includes("SSP2-4.5 / RCP4.5"), "and names its scenarios");
});

test("an invalid horizon still gets a truthful label rather than 'undefined'", () => {
  assert.strictEqual(C.hzLabel("2050"), C.hzLabel("today"));
  assert.ok(!C.hzLabel("banana").includes("undefined"));
});
