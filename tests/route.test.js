/* The v3.0 alias table (src/route_core.js): old shared links must keep working for ever, so every
   redirect is pinned here rather than in a browser test. Run with `make test-js` or `node --test tests/`. */
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const R = require("../src/route_core.js");

/* the climate keys of the v2.6 registry, as app.js will pass them in */
const isClim = k => ["surge_dw_pct", "surge_pop_pct", "sealevel_cm", "rain_mm"].includes(k);

/* ---------- splitHash / buildHash ---------- */
test("splitHash reads path, parts and query", () => {
  const r = R.splitHash("#area/kommune/101?ind=growth&y=2024");
  assert.strictEqual(r.path, "area/kommune/101");
  assert.deepStrictEqual(r.parts, ["area", "kommune", "101"]);
  assert.deepStrictEqual(r.query, { ind: "growth", y: "2024" });
});
test("splitHash tolerates no hash, no query and stray slashes", () => {
  assert.deepStrictEqual(R.splitHash("map").parts, ["map"]);
  assert.deepStrictEqual(R.splitHash("/map/101/").parts, ["map", "101"]);
  assert.deepStrictEqual(R.splitHash("").parts, []);
  assert.deepStrictEqual(R.splitHash("#pipeline?").query, {});
});
test("splitHash decodes keys and values", () => {
  assert.strictEqual(R.splitHash("charts?a=kommune%3A101").query.a, "kommune:101");
});
test("buildHash omits the question mark when there is no query", () => {
  assert.strictEqual(R.buildHash("data/sources", {}), "data/sources");
  assert.strictEqual(R.buildHash("map", { ind: "growth" }), "map?ind=growth");
});
test("buildHash keeps , : ; / readable and drops null values", () => {
  assert.strictEqual(R.buildHash("property", { p: "55.6545,12.539:Test", la: null }), "property?p=55.6545,12.539:Test");
  assert.strictEqual(R.buildHash("charts", { a: "kommune:101,kommune:751" }), "charts?a=kommune:101,kommune:751");
  assert.strictEqual(R.buildHash("map", { q: "a b&c" }), "map?q=a%20b%26c");
});
test("buildHash and splitHash round-trip", () => {
  const q = { ind: "surge_dw_pct", p: "55.6545,12.539:Ø & Å", hz: "2070" };
  assert.deepStrictEqual(R.splitHash(R.buildHash("property", q)).query, q);
});

/* ---------- coordinates and the property codec ---------- */
test("parseLatLon accepts the serialised pin and rounds to five decimals", () => {
  assert.deepStrictEqual(R.parseLatLon("55.65450,12.53900"), [55.6545, 12.539]);
  assert.deepStrictEqual(R.parseLatLon(" 55.6545 , 12.539 "), [55.6545, 12.539]);
  assert.deepStrictEqual(R.parseLatLon("-55.1,-12.2"), [-55.1, -12.2]);
});
test("parseLatLon rejects anything that is not one coordinate pair", () => {
  ["", "kommune:101", "55.6545", "55.6545,12.539,15", "abc,def", null, undefined].forEach(s =>
    assert.strictEqual(R.parseLatLon(s), null, JSON.stringify(s)));
});
test("the property codec round-trips one pin with and without a label", () => {
  assert.strictEqual(R.propSerialise([{ lat: 55.65450, lon: 12.53900, label: "Test" }]), "55.6545,12.539:Test");
  assert.strictEqual(R.propSerialise([{ lat: 55.6545, lon: 12.539, label: "" }]), "55.6545,12.539");
  assert.deepStrictEqual(R.propParse("55.6545,12.539:Test"), [{ lat: 55.6545, lon: 12.539, label: "Test" }]);
  assert.deepStrictEqual(R.propParse("55.6545,12.539"), [{ lat: 55.6545, lon: 12.539, label: "" }]);
});
test("the property codec stays list-capable (the LATER portfolio needs no second format)", () => {
  const items = [{ lat: 55.6545, lon: 12.539, label: "A" }, { lat: 56.1, lon: 10.2, label: "" }];
  assert.strictEqual(R.propSerialise(items), "55.6545,12.539:A;56.1,10.2");
  assert.deepStrictEqual(R.propParse("55.6545,12.539:A;56.1,10.2"), items);
});
test("the property codec drops unparsable items instead of throwing", () => {
  assert.deepStrictEqual(R.propParse("nonsense"), []);
  assert.deepStrictEqual(R.propParse("nonsense;55.6545,12.539").length, 1);
});

/* ---------- old → new ---------- */
test("table → data/areas, per level, query kept", () => {
  assert.strictEqual(R.toV3("#table/kommune?ind=growth"), "data/areas/kommune?ind=growth");
  assert.strictEqual(R.toV3("#table/postnr?ind=growth"), "data/areas/postnr?ind=growth");
  assert.strictEqual(R.toV3("#table/kvarter"), "data/areas/kvarter");
  assert.strictEqual(R.toV3("#table"), "data/areas/kommune");
  assert.strictEqual(R.toV3("#table/nonsense"), "data/areas/kommune");
});
test("pipeline → data/projects, filters kept", () => {
  assert.strictEqual(R.toV3("#pipeline?ptype=metro&pstatus=construction"), "data/projects?ptype=metro&pstatus=construction");
});
test("market and sources → the right Data tab", () => {
  assert.strictEqual(R.toV3("#market"), "data/national");
  assert.strictEqual(R.toV3("#market?src=1"), "data/sources");
  assert.strictEqual(R.toV3("#sources"), "data/sources");
});
test("analysis → property, pin first, label after the colon", () => {
  assert.strictEqual(R.toV3("#analysis?a=55.65450,12.53900&la=Test"), "property?p=55.6545,12.539:Test");
  assert.strictEqual(R.toV3("#analysis?a=55.65450,12.53900"), "property?p=55.6545,12.539");
  assert.strictEqual(R.toV3("#analysis"), "property");
});
test("analysis keeps the keys that are not the pin", () => {
  assert.strictEqual(R.toV3("#analysis?a=55.6545,12.539&la=T&ind=growth&hz=2070"),
    "property?p=55.6545,12.539:T&ind=growth&hz=2070");
});
test("compare → the first area's own page (Compare is deleted, amendment A1)", () => {
  assert.strictEqual(R.toV3("#compare?a=kommune:101&b=kommune:751"), "area/kommune/101");
  assert.strictEqual(R.toV3("#compare?a=kvarter:20602&b=kommune:147&hz=2070"), "area/kvarter/20602?hz=2070");
  assert.strictEqual(R.toV3("#compare?a=postnr:2450"), "area/postnr/2450");
});
test("compare with no usable area lands on the map, not on a broken area page", () => {
  assert.strictEqual(R.toV3("#compare"), "map");
  assert.strictEqual(R.toV3("#compare?a=nonsense&b=kommune:101"), "map");
  assert.strictEqual(R.toV3("#compare?a=macro:1"), "map");
});
test("climate=1 becomes a climate indicator on the same map", () => {
  assert.strictEqual(R.toV3("#map?ind=growth&climate=1", { isClim }), "map?ind=surge_dw_pct");
  assert.strictEqual(R.toV3("#map/101?ind=growth&climate=1&hz=2070", { isClim }), "map/101?ind=surge_dw_pct&hz=2070");
});
test("climate=1 does not override a climate indicator the link already names", () => {
  assert.strictEqual(R.toV3("#map?ind=sealevel_cm&climate=1&hz=2120", { isClim }), "map?ind=sealevel_cm&hz=2120");
});
test("a map link without the flag is untouched", () => {
  assert.strictEqual(R.toV3("#map/101/postnr?ind=renters", { isClim }), "map/101/postnr?ind=renters");
});
test("routes with no alias pass through unchanged", () => {
  ["area/kommune/101?ind=growth", "charts?ind=growth&a=kommune:101", "project/m5-phase-1",
   "public/101/abc", "school/280657", "climate/0167?hz=2070", "data/areas/kommune?ind=growth",
   "property?p=55.6545,12.539"].forEach(h => assert.strictEqual(R.toV3("#" + h), h));
});
test("an empty hash is the map", () => {
  assert.strictEqual(R.toV3(""), "map");
  assert.strictEqual(R.toV3("#"), "map");
});
test("toV3 is idempotent — it can run on every hashchange", () => {
  ["#table/postnr?ind=growth", "#pipeline", "#market?src=1", "#sources", "#analysis?a=55.6545,12.539&la=T",
   "#compare?a=kommune:101&b=kommune:751", "#map?ind=growth&climate=1", "#map?ind=sealevel_cm&climate=1",
   "#area/kommune/101", "#charts?ind=growth&a=kommune:101,kommune:751", "#property?p=55.6545,12.539:T",
   "#", "#map/101"].forEach(h => {
    const once = R.toV3(h, { isClim });
    assert.strictEqual(R.toV3(once, { isClim }), once, h);
  });
});

/* ---------- either spelling → the internal view ---------- */
test("the Data tabs map onto the v2.6 view ids, which do not change", () => {
  assert.deepStrictEqual(R.toInternal("#data/areas/postnr?ind=growth"),
    { view: "table", parts: ["table", "postnr"], query: { ind: "growth" } });
  assert.strictEqual(R.toInternal("#data/projects").view, "pipeline");
  assert.strictEqual(R.toInternal("#data/national").view, "market");
  assert.strictEqual(R.toInternal("#data/sources").query.src, "1");
  assert.strictEqual(R.toInternal("#data/sources").view, "market");
  assert.strictEqual(R.toInternal("#data").parts[1], "kommune");
});
test("the old spelling reaches the same internal view as the new one", () => {
  ["#table/kvarter?ind=growth", "#pipeline?ptype=metro", "#market?src=1", "#sources",
   "#analysis?a=55.6545,12.539&la=T", "#compare?a=kommune:101&b=kommune:751", "#map/101"].forEach(h => {
    assert.deepStrictEqual(R.toInternal(h, { isClim }), R.toInternal("#" + R.toV3(h, { isClim }), { isClim }), h);
  });
});
test("property hands the pin back as the a= / la= app.js already parses", () => {
  const r = R.toInternal("#property?p=55.6545,12.539:Test&ind=growth");
  assert.strictEqual(r.view, "analysis");
  assert.strictEqual(r.query.a, "55.6545,12.539");
  assert.strictEqual(r.query.la, "Test");
  assert.strictEqual(r.query.ind, "growth");
  assert.ok(!("p" in r.query));
});
test("an empty property page has no pin and still routes", () => {
  const r = R.toInternal("#property");
  assert.strictEqual(r.view, "analysis");
  assert.ok(!("a" in r.query));
});
test("map, area and the sheets keep their own parts", () => {
  assert.deepStrictEqual(R.toInternal("#map/101/postnr").parts, ["map", "101", "postnr"]);
  assert.strictEqual(R.toInternal("#map/101/postnr").view, "makro");
  assert.deepStrictEqual(R.toInternal("#area/kvarter/20602").parts, ["area", "kvarter", "20602"]);
  assert.strictEqual(R.toInternal("#project/m5-phase-1").view, "project");
  assert.strictEqual(R.toInternal("#climate/0167").view, "climate");
  assert.strictEqual(R.toInternal("").view, "makro");
});
