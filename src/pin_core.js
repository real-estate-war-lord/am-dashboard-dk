/* pin_core.js — everything about a point on the map that is a function of geometry and of the
   indicator registry alone. Same arrangement as src/climate_core.js, src/route_core.js and
   src/picker_core.js: no DOM, no globals, no fetch, so `node --test tests/pin.test.js` runs it.

   Two halves, both of them about one pin:

     · WHERE IT IS — ray casting into a polygon (`pip`, `inPoly`), the bounding box prefilter
       (`bboxOf`, `inBox`, `areaOf`), great-circle distance (`havM`) and the distance from a point
       to any GeoJSON geometry (`featDistM`). The map's own click handling uses the same functions,
       which is why a pin and a polygon click can never disagree about which area a point is in.

     · WHAT IT CAN BE READ AS — the pin is read against published areas, so it inherits the way a
       postal-code or quarter page does (spec §4.2 AC-I5, §5.5′): `mergeInds` is the union of the
       levels it sits in, finest registry first, and `inhFrom` says which level each figure will
       actually come from ("" = its own, "postnr", "muni"). `pinPath` is the finest-first area line.

   Nothing here knows which view is on screen or what the app's state objects are called.
*/
"use strict";
/* IIFE: the build inlines this file and app.js as classic <script> blocks in one global lexical
   scope, so a top-level const here would collide with app.js and blank the page. */
(function () {

/* ---------- where it is ---------- */
/* ray casting over one ring of [lat, lon] pairs (Leaflet order) */
function pip(pt, ring) {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const yi = ring[i][0], xi = ring[i][1], yj = ring[j][0], xj = ring[j][1];
    if ((yi > pt[0]) !== (yj > pt[0]) && pt[1] < (xj - xi) * (pt[0] - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
/* a polygon is its outer ring minus its holes: Frederiksberg is a hole in København, and without
   the holes every Frederiksberg pin would land in København */
const inPoly = (pt, poly) => pip(pt, poly[0]) && !poly.slice(1).some(h => pip(pt, h));
/* an area's [south, west, north, east] box, cached on the area itself — the prefilter before the
   ray casting, which is what keeps `locate()` off 606 postal-code rings per render */
function bboxOf(a) {
  if (a._bb) return a._bb;
  let s = 90, w = 180, n = -90, e = -180;
  (a.rings || []).forEach(r => r.forEach(q => { if (q[0] < s) s = q[0]; if (q[0] > n) n = q[0]; if (q[1] < w) w = q[1]; if (q[1] > e) e = q[1]; }));
  return (a._bb = [s, w, n, e]);
}
const inBox = (lat, lon, b) => lat >= b[0] && lat <= b[2] && lon >= b[1] && lon <= b[3];
const areaOf = (list, lat, lon) => (list || []).find(a => inBox(lat, lon, bboxOf(a)) && (a.rings || []).some(r => pip([lat, lon], r))) || null;

const R_EARTH = 6371008.8;
/* great-circle distance in metres */
function havM(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180, dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(a)));
}
/* distance from the pin to a GeoJSON feature: a Point is the great-circle distance, a line or a ring
   the nearest point on its segments, and a point inside a polygon is 0 m. Degrees are converted to
   metres at the pin's own latitude — exact enough over the few kilometres this page looks at. */
function featDistM(f, lat, lon) {
  const g = f && f.geometry; if (!g || !g.coordinates) return null;
  if (g.type === "Point") return havM(lat, lon, g.coordinates[1], g.coordinates[0]);
  const rad = Math.PI / 180, kx = 111320 * Math.cos(lat * rad), ky = 110540;
  /* nearest point on the segment a→b, both in metres relative to the pin */
  const segD = (a, b) => {
    const ax = (a[0] - lon) * kx, ay = (a[1] - lat) * ky, dx = (b[0] - a[0]) * kx, dy = (b[1] - a[1]) * ky;
    const l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
    return Math.hypot(ax + t * dx, ay + t * dy);
  };
  const ringD = r => { let m = Infinity; for (let i = 1; i < r.length; i++) { const d = segD(r[i - 1], r[i]); if (d < m) m = d; } return m; };
  const polys = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : null;
  if (polys) {
    /* inside the outer ring and outside every hole → the pin is in the area */
    if (polys.some(poly => inPoly([lat, lon], poly.map(r => r.map(c => [c[1], c[0]]))))) return 0;
    return Math.min(...polys.map(poly => Math.min(...poly.map(ringD))));
  }
  const lines = g.type === "MultiLineString" ? g.coordinates : g.type === "LineString" ? [g.coordinates] : null;
  return lines ? Math.min(...lines.map(ringD)) : null;
}

/* ---------- what it can be read as ---------- */
/* The indicators a pin may be read against: its finest level's own registry first, then everything
   the coarser levels publish that the finest one does not (spec §5.5′, owner review P10 item 4).
   Union by key, first list wins — the quarter's own "Unemployed (Nov.)" is not replaced by DST's
   "Unemployment rate" just because both are keyed `unemp`. */
function mergeInds() {
  const out = [], seen = new Set();
  for (let n = 0; n < arguments.length; n++) {
    (arguments[n] || []).forEach(i => { if (!i || seen.has(i.key)) return; seen.add(i.key); out.push(i); });
  }
  return out;
}
/* Which level a figure on this pin actually comes from — "" (the pin's own area publishes it),
   "postnr" (the postal code it sits in does) or "muni" (only the municipality does).

     type    the pin's finest level: kommune | postnr | kvarter
     ownKey  does that level's own registry publish this key (cphOwn for a quarter)
     level   the indicator's own level from the registry (kommune | postnr | kvarter)
     hasPn   the pin also sits in a postal code (a Copenhagen quarter always does)

   The rule is the area page's `inherits()` read one rung further: a quarter that does not publish
   a figure takes the postal code's where the postal code is the publisher, and the municipality's
   otherwise. */
function inhFrom(type, ownKey, level, hasPn) {
  if (type === "kommune" || ownKey) return "";
  if (type === "postnr") return level === "postnr" ? "" : "muni";
  if (type === "kvarter") return hasPn && level === "postnr" ? "postnr" : "muni";
  return "";
}
/* the pin's area line, finest first: "Vesterbro syd › 2450 København SV › København" */
const pinPath = parts => (parts || []).filter(Boolean).join(" › ");

/* Which service points belong on a mini map centred on the pin: the category has to be on, a
   transport stop's mode too, the zoom has to be past the category's own floor (the same floors the
   Macro map uses — a bus stop at zoom 11 is a blot, not a service), and the point has to be inside
   the ring the map draws. `o.catOn` / `o.modeOn` / `o.zoomOf` are the caller's filter state. */
function srvNear(points, lat, lon, o) {
  const out = [], z = o.zoom == null ? 99 : o.zoom, max = o.max || 0;
  (points || []).forEach(p => {
    if (!o.catOn(p.cat)) return;
    if (p.cat === "transport" && !o.modeOn(p.sub)) return;
    if (z < o.zoomOf(p)) return;
    if (max && havM(lat, lon, p.lat, p.lon) > max) return;
    out.push(p);
  });
  return out;
}

/* every municipality whose bounding box touches the circle of radius m around the pin, the pin's
   own first — the prefilter that decides which per-municipality files a pin needs at all */
function komsNear(list, lat, lon, own, m) {
  const dLat = m / 110540, dLon = m / (111320 * Math.cos(lat * Math.PI / 180));
  const box = [lat - dLat, lon - dLon, lat + dLat, lon + dLon];
  const near = (list || []).filter(k => k.bb[0] <= box[2] && k.bb[2] >= box[0] && k.bb[1] <= box[3] && k.bb[3] >= box[1]);
  return [...new Set((own ? [String(Number(own))] : []).concat(near.map(k => String(Number(k.code)))))];
}
/* Where a value sits among the peers that have one, as the share it is at least as good as.
   Direction-aware: for a lower-is-better indicator a small value beats a large one, so the bar
   always fills toward "better" and two indicators of opposite direction read off one column.
   A neutral indicator has no favourable end, so it is simply "how high among the peers". */
function pctOf(v, vals, opts) {
  const o = opts || {}, xs = (vals || []).filter(x => x != null);
  if (v == null || xs.length < 5) return null;
  const lb = !o.neutral && o.lower;
  const beaten = xs.filter(x => lb ? x > v : x < v).length, tied = xs.filter(x => x === v).length;
  return { p: (beaten + tied / 2) / xs.length * 100, n: xs.length, neutral: !!o.neutral };
}
/* BBR registers one building as several bodies, so a school with four wings arrives as four
   identical rows: same name, same use code, the same distance to within `m`. They become one row
   with a count — nothing is dropped, and the distance shown is the nearest of them (spec §5.5′). */
function dupGroup(list, key, m) {
  const out = [], by = new Map();
  (list || []).forEach(x => {
    const k = `${key(x)}|${Math.round(x.d / m)}`, hit = by.get(k);
    if (hit) { hit.n++; return; }
    const row = { x, n: 1 }; by.set(k, row); out.push(row);
  });
  return out;
}

const API = { pip, inPoly, bboxOf, inBox, areaOf, havM, featDistM, R_EARTH,
              mergeInds, inhFrom, pinPath, srvNear, komsNear, pctOf, dupGroup };
if (typeof window !== "undefined") window.PIN_CORE = API;
if (typeof module !== "undefined" && module.exports) module.exports = API;

})();
