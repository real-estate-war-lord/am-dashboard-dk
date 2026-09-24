/* Climate layer — the pure parts, kept out of src/app.js so they can be unit-tested.
   Same arrangement as src/testprop.js: no DOM, no globals, no fetch. Everything here is a
   function of its arguments, and src/app.js is the only caller. `make test-js` runs
   tests/climate.test.js against this file.

   Two families live here:
     · geometry — is a point inside a published flood extent (GeoJSON, [lon, lat] order,
       Polygon or MultiPolygon, holes honoured);
     · the horizon — parsing and serialising `hz=` and `clim=`, and the label that has to name
       both calendars at once, because Kystdirektoratet's extent year and the Klimaatlas period
       behind the figures are not the same thing.
*/
"use strict";
/* Wrapped in an IIFE on purpose. The build inlines this file and app.js as two <script> blocks,
   and classic scripts share one global lexical scope: a top-level `const hzShort` here and the
   `const hzShort = CC.hzShort` in app.js would be a redeclaration, which is a SyntaxError that
   takes the whole page down. Nothing leaks but the one export below. */
(function () {

/* the three horizons, in order; `today` is the default and the fallback for anything unknown */
const CLIM_HZ = ["today", "2070", "2120"];
const CLIM_ZONE_YEAR = { today: "2020", "2070": "2070", "2120": "2120" };
/* the Klimaatlas period behind the figures at each horizon — the other half of every label */
const CLIM_FIG = {
  today: "Klimaatlas 1981–2010 reference period",
  "2070": "Klimaatlas 2041–70 (SSP2-4.5 / RCP4.5 for rain)",
  "2120": "Klimaatlas 2071–2100, latest Klimaatlas period (SSP2-4.5 / RCP4.5 for rain)",
};
const CLIM_LAY = { areas: "Official risk areas", surge: "Storm-surge zones" };

/* ---------- geometry ---------- */
/* Ray casting on one GeoJSON ring ([lon, lat] pairs). A point exactly on an edge is inside for
   one of the two rings that share that edge and outside for the other, which is what keeps two
   neighbouring polygons from both claiming it; for a single polygon the answer on the edge is
   deterministic but not meaningful, and the callers never depend on it. */
function pipLL(lat, lon, ring) {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const yi = ring[i][1], xi = ring[i][0], yj = ring[j][1], xj = ring[j][0];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
/* inside the outer ring and outside every hole */
function gjHit(lat, lon, g) {
  if (!g) return false;
  const polys = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : [];
  return polys.some(poly => pipLL(lat, lon, poly[0]) && !poly.slice(1).some(h => pipLL(lat, lon, h)));
}
/* Is the point inside any feature of these collections? `null` when there is nothing to answer
   from — a missing file is not a dry point, and the UI says "…" rather than "no". */
function inZone(lat, lon, collections) {
  const fcs = (collections || []).filter(Boolean);
  if (!fcs.length) return null;
  return fcs.some(fc => (fc.features || []).some(f => gjHit(lat, lon, f.geometry)));
}

/* ---------- the horizon in the hash ---------- */
const hzValid = h => CLIM_HZ.indexOf(h) >= 0;
/* anything that is not one of the three published horizons is today — a link with hz=2050 or
   hz=banana opens on the baseline rather than on nothing */
const hzParse = q => hzValid((q || {}).hz) ? q.hz : "today";
/* today is the default, so it stays out of the hash; the other two are carried */
const hzSerialise = h => (hzValid(h) && h !== "today") ? [`hz=${h}`] : [];
const hzShort = h => h === "today" ? "Today" : h;
/* "2070 — zones: Kystdirektoratet 2070 · figures: Klimaatlas 2041–70 (SSP2-4.5 / RCP4.5 for rain)" */
function hzLabel(h) {
  const k = hzValid(h) ? h : "today";
  return `${hzShort(k)} — zones: Kystdirektoratet ${CLIM_ZONE_YEAR[k]} · figures: ${CLIM_FIG[k]}`;
}

/* v3.0 P4: `clim=` (which half of the overlay was drawn) is gone with the overlay itself. The two
   parts are one context layer now, on whenever a Climate indicator is and hidden with `zones=0`
   (spec §1 decision 3, §4.4) — so there is one thing to switch, not two. */

/* the page gets it as a global (the build inlines this file straight above app.js); node gets it
   as a module. One file, two consumers, no second copy of any of it. */
const API = { CLIM_HZ, CLIM_ZONE_YEAR, CLIM_FIG, CLIM_LAY, pipLL, gjHit, inZone,
              hzValid, hzParse, hzSerialise, hzShort, hzLabel };
if (typeof window !== "undefined") window.CLIMATE_CORE = API;
if (typeof module !== "undefined" && module.exports) module.exports = API;

})();
