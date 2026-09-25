/* pin_core.js — the pure logic behind one pin: where it is, and what it can be read as.
   node --test tests/pin.test.js */
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const P = require("../src/pin_core.js");

/* a 1° square with a hole in the middle, in Leaflet order ([lat, lon]) */
const OUTER = [[0, 0], [0, 1], [1, 1], [1, 0]];
const HOLE = [[.4, .4], [.4, .6], [.6, .6], [.6, .4]];

test("pip: inside, outside, and the hole is still inside the outer ring", () => {
  assert.equal(P.pip([.5, .5], OUTER), true);
  assert.equal(P.pip([1.5, .5], OUTER), false);
  assert.equal(P.pip([.5, .5], HOLE), true);
});

test("inPoly: a hole is not part of the polygon (Frederiksberg in København)", () => {
  assert.equal(P.inPoly([.2, .2], [OUTER, HOLE]), true);
  assert.equal(P.inPoly([.5, .5], [OUTER, HOLE]), false);
});

test("bboxOf caches [south, west, north, east] on the area", () => {
  const a = { rings: [OUTER] };
  assert.deepEqual(P.bboxOf(a), [0, 0, 1, 1]);
  assert.ok(a._bb, "the box is cached on the area");
  assert.equal(P.inBox(.5, .5, a._bb), true);
  assert.equal(P.inBox(2, .5, a._bb), false);
});

test("areaOf picks the ring the point is in, and null outside every one", () => {
  const list = [{ nr: "1000", rings: [OUTER] }, { nr: "2000", rings: [[[5, 5], [5, 6], [6, 6], [6, 5]]] }];
  assert.equal(P.areaOf(list, .5, .5).nr, "1000");
  assert.equal(P.areaOf(list, 5.5, 5.5).nr, "2000");
  assert.equal(P.areaOf(list, 3, 3), null);
});

test("havM: a known Copenhagen distance, and zero for the same point", () => {
  assert.equal(Math.round(P.havM(55.6545, 12.539, 55.6545, 12.539)), 0);
  /* Rådhuspladsen → Nørreport, ~1.2 km on the ground */
  const d = P.havM(55.67594, 12.56553, 55.68326, 12.57138);
  assert.ok(d > 850 && d < 1000, `got ${d} m`);
});

test("featDistM: point, line, and 0 m inside an area", () => {
  const pt = { geometry: { type: "Point", coordinates: [12.539, 55.6545] } };
  assert.equal(Math.round(P.featDistM(pt, 55.6545, 12.539)), 0);
  const line = { geometry: { type: "LineString", coordinates: [[12.5, 55.6], [12.6, 55.6]] } };
  const d = P.featDistM(line, 55.61, 12.55);
  assert.ok(d > 1000 && d < 1300, `got ${d} m`);
  /* GeoJSON is [lon, lat]; the pin is inside the square */
  const area = { geometry: { type: "Polygon", coordinates: [[[12.5, 55.6], [12.6, 55.6], [12.6, 55.7], [12.5, 55.7], [12.5, 55.6]]] } };
  assert.equal(P.featDistM(area, 55.65, 12.55), 0);
  assert.equal(P.featDistM({ geometry: null }, 55, 12), null);
});

/* ---------- what it can be read as ---------- */
const I = (key, level, group) => ({ key, level, group: group || "Demographics" });

test("mergeInds: union by key, the first list wins", () => {
  const own = [I("growth", "kvarter"), I("new_stock", "kvarter")];
  const all = [I("growth", "kommune"), I("price_m2", "postnr"), I("unemp", "kommune")];
  const out = P.mergeInds(own, all);
  assert.deepEqual(out.map(i => i.key), ["growth", "new_stock", "price_m2", "unemp"]);
  assert.equal(out[0].level, "kvarter", "the quarter's own registry entry survived");
  assert.deepEqual(P.mergeInds(null, undefined, [I("a", "kommune")]).map(i => i.key), ["a"]);
});

test("inhFrom: the area page's inheritance rule, one rung further for a quarter", () => {
  /* a municipality pin owns everything */
  assert.equal(P.inhFrom("kommune", false, "kommune", false), "");
  /* a postal code owns the postnr-level figures and inherits the rest */
  assert.equal(P.inhFrom("postnr", false, "postnr", false), "");
  assert.equal(P.inhFrom("postnr", false, "kommune", false), "muni");
  /* a quarter owns what the quarter registry publishes */
  assert.equal(P.inhFrom("kvarter", true, "kvarter", true), "");
  /* …takes a postal-code figure from the postal code it sits in… */
  assert.equal(P.inhFrom("kvarter", false, "postnr", true), "postnr");
  /* …and everything else from the municipality */
  assert.equal(P.inhFrom("kvarter", false, "kommune", true), "muni");
  assert.equal(P.inhFrom("kvarter", false, "postnr", false), "muni", "no postal code → the municipality");
});

test("pinPath is finest first and drops the levels a pin has none of", () => {
  assert.equal(P.pinPath(["Vesterbro syd", "2450 København SV", "København"]),
               "Vesterbro syd › 2450 København SV › København");
  assert.equal(P.pinPath([null, "8000 Aarhus C", "Aarhus"]), "8000 Aarhus C › Aarhus");
  assert.equal(P.pinPath([]), "");
});

test("komsNear: the pin's own municipality first, then every box the circle touches", () => {
  const list = [{ code: "0101", bb: [55.6, 12.4, 55.8, 12.7] }, { code: "0147", bb: [55.66, 12.5, 55.7, 12.56] },
                { code: "0751", bb: [56.0, 10.0, 56.3, 10.4] }];
  const out = P.komsNear(list, 55.68, 12.55, "101", 1000);
  assert.deepEqual(out, ["101", "147"], "Aarhus is 250 km away and must not be in the list");
  assert.deepEqual(P.komsNear(list, 55.68, 12.55, null, 1000), ["101", "147"]);
  assert.deepEqual(P.komsNear([], 55.68, 12.55, "101", 1000), ["101"], "the pin's own is there without a list");
});

test("pctOf: direction-aware, and null under five peers", () => {
  const vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  assert.equal(Math.round(P.pctOf(9, vals, { lower: false }).p), 85);
  /* lower is better: the same value is near the bad end */
  assert.equal(Math.round(P.pctOf(9, vals, { lower: true }).p), 15);
  /* neutral has no favourable end — it reads as a position, whatever the direction flag says */
  assert.equal(Math.round(P.pctOf(9, vals, { lower: true, neutral: true }).p), 85);
  assert.equal(P.pctOf(null, vals, {}), null);
  assert.equal(P.pctOf(2, [1, 2, 3], {}), null, "three peers is not a distribution");
  assert.equal(P.pctOf(5, vals, {}).n, 10);
});

test("dupGroup folds identical rows within the distance tolerance and counts them", () => {
  const rows = [{ name: "Skole", d: 100 }, { name: "Skole", d: 108 }, { name: "Skole", d: 400 },
                { name: "Hal", d: 100 }];
  const out = P.dupGroup(rows, x => x.name, 20);
  assert.deepEqual(out.map(r => [r.x.name, r.x.d, r.n]), [["Skole", 100, 2], ["Skole", 400, 1], ["Hal", 100, 1]]);
  assert.deepEqual(P.dupGroup(null, x => x.name, 20), []);
});

test("srvNear: category, mode, zoom floor and the ring", () => {
  const pts = [
    { cat: "grocery", sub: "supermarket", lat: 55.6545, lon: 12.539 },
    { cat: "food", sub: "cafe", lat: 55.6546, lon: 12.539 },
    { cat: "transport", sub: "bus", lat: 55.6547, lon: 12.539 },
    { cat: "grocery", sub: "supermarket", lat: 55.9, lon: 12.539 },     /* 27 km away */
  ];
  const o = { zoom: 15, max: 2000, catOn: c => c !== "food", modeOn: m => m !== "bus",
              zoomOf: p => (p.cat === "transport" ? 10 : 13) };
  const out = P.srvNear(pts, 55.6545, 12.539, o);
  assert.deepEqual(out.map(p => p.cat), ["grocery"], "food is filtered out, the bus stop too, and 27 km is outside the ring");
  /* below the category's floor nothing is drawn */
  assert.equal(P.srvNear(pts, 55.6545, 12.539, { ...o, zoom: 11 }).length, 0);
  /* no ring = no distance filter */
  assert.equal(P.srvNear(pts, 55.6545, 12.539, { ...o, max: 0 }).length, 2);
});
