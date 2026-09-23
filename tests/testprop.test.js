/* parseLocation — the test-property input on the macro map (src/testprop.js).
   Run with `make test-js` or `node --test tests/`. */
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { parseLocation } = require("../src/testprop.js");

const near = (a, b) => Math.abs(a - b) < 1e-6;
function ok(t, text, lat, lon, source) {
  const r = parseLocation(text);
  assert.strictEqual(r.error, undefined, `expected a hit, got ${r.error}: ${r.message}`);
  assert.ok(near(r.lat, lat) && near(r.lon, lon), `expected ${lat}, ${lon} — got ${r.lat}, ${r.lon}`);
  if (source) assert.strictEqual(r.source, source);
  return r;
}
function err(text, code) {
  const r = parseLocation(text);
  assert.strictEqual(r.error, code, `expected error "${code}", got ${r.error ? r.error : `${r.lat}, ${r.lon}`}`);
  assert.ok(r.message && r.message.length > 10, "an error carries a message the user can act on");
  return r;
}

test("place URL: !3d/!4d wins over the @ viewport centre", () => {
  /* the @ pair is the map centre (12.5655), the !3d/!4d pair the pin itself (12.56830) */
  const url = "https://www.google.com/maps/place/R%C3%A5dhuspladsen,+1550+K%C3%B8benhavn/@55.6750,12.5655,17z/data=!3m1!4b1!4m6!3m5!1s0x4652531f1a0b6e3d:0x1!8m2!3d55.67610!4d12.56830!16s%2Fg%2F11abc";
  ok(0, url, 55.67610, 12.56830, "place");
});

test("place URL without !3d falls back to @", () => {
  ok(0, "https://www.google.com/maps/place/Aarhus+C/@56.15280,10.20390,15z/data=!3m1!4b1", 56.15280, 10.20390, "at");
});

test("bare @ view URL", () => {
  ok(0, "https://www.google.com/maps/@55.68000,12.57000,14z", 55.68000, 12.57000, "at");
});

test("q= parameter with a URL-encoded comma", () => {
  ok(0, "https://maps.google.com/?q=55.67610%2C12.56830", 55.67610, 12.56830, "param");
});

test("q= parameter with a + for the space", () => {
  ok(0, "https://www.google.com/maps?q=56.15280,+10.20390&z=16", 56.15280, 10.20390, "param");
});

test("ll= parameter", () => {
  ok(0, "https://www.google.com/maps?ll=57.04880,9.92170&z=15", 57.04880, 9.92170, "param");
});

test("query= parameter", () => {
  ok(0, "https://www.google.com/maps/search/?api=1&query=55.40380%2C10.40240", 55.40380, 10.40240, "param");
});

test("/search/<lat>,<lon> path", () => {
  ok(0, "https://www.google.com/maps/search/55.40380,10.40240", 55.40380, 10.40240, "search");
});

test("plain coordinates — comma, space and semicolon", () => {
  ok(0, "55.67610, 12.56830", 55.67610, 12.56830, "plain");
  ok(0, "55.67610 12.56830", 55.67610, 12.56830, "plain");
  ok(0, "55.67610;12.56830", 55.67610, 12.56830, "plain");
  ok(0, "  56.15280,10.20390  ", 56.15280, 10.20390, "plain");
});

test("short share links cannot be read in the browser", () => {
  const r = err("https://maps.app.goo.gl/abc123XYZ", "short_link");
  assert.match(r.message, /address bar/);
  err("https://goo.gl/maps/abc123", "short_link");
});

test("garbage text has no coordinates", () => {
  err("hello world", "no_match");
  err("Rådhuspladsen 1, 1550 København", "no_match");
  err("", "empty");
});

test("swapped lon/lat is rejected by the Denmark box", () => {
  /* Copenhagen written lon-first: 12.6 is not a Danish latitude */
  err("12.56830, 55.67610", "outside_dk");
});

test("clearly foreign coordinates are rejected", () => {
  err("https://www.google.com/maps/@48.85840,2.29450,17z", "outside_dk");   // Paris
  err("60.16980, 24.93840", "outside_dk");                                  // Helsinki
});

test("Malmö passes the coarse box — locate() is what rejects it", () => {
  /* the box is deliberately generous (54–58 N, 7–16 E); Skåne sits inside it,
     so the point-in-polygon lookup in app.js is what reports "outside Denmark" */
  const r = ok(0, "55.60500, 13.00380", 55.60500, 13.00380, "plain");
  assert.strictEqual(r.source, "plain");
});

test("a negative or out-of-range number never becomes a silent hit", () => {
  err("-55.67610, 12.56830", "outside_dk");
  err("55.67610, -12.56830", "outside_dk");
});
