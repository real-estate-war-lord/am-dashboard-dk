/* Routing — the pure parts, kept out of src/app.js so they can be unit-tested.
   Same arrangement as src/climate_core.js and src/testprop.js: no DOM, no globals, no fetch.
   `make test-js` runs tests/route.test.js against this file.

   What lives here is the v3.0 alias table. A hash has three spellings:

     old (v2.6, shared in emails and slide decks) …… table/kommune · pipeline · market · sources
                                                      analysis?a=55.6,12.5&la=X · compare?a=…&b=…
                                                      map/101?climate=1
     new (v3.0, what the app emits from P2 on) …….… data/areas/kommune · data/projects ·
                                                      data/national · data/sources ·
                                                      property?p=55.6,12.5:X · area/kommune/101 ·
                                                      map/101?ind=surge_dw_pct
     internal (S.view, unchanged so RENDER/nav keep working) … table · pipeline · market ·
                                                      analysis · area · makro

   `toV3()` maps old → new and is idempotent, so it can run on every hashchange without ever
   rewriting its own output. `toInternal()` maps either spelling → the view id and the parts the
   router needs. Nothing here decides *when* the rewrite happens — app.js does, behind ROUTE_V3.
*/
"use strict";
/* Wrapped in an IIFE: the build inlines this file and app.js as two classic <script> blocks in one
   global lexical scope, so a top-level const here would collide with app.js and blank the page. */
(function () {

/* the climate indicator a `climate=1` link lands on when it names no climate indicator of its own */
const CLIM_FALLBACK_IND = "surge_dw_pct";
/* used only when the caller passes no isClim(): the climate group's key shapes in the v2.6 registry */
const CLIM_KEY_RX = /^(surge_|sealevel|rain_|flood_|storm_|clim_)/;

/* ---------- hash ⇄ parts ---------- */
/* "#table/kommune?ind=growth&y=2024" → { path, parts, query } — the inverse of buildHash() */
function splitHash(hash) {
  let h = String(hash == null ? "" : hash);
  if (h.charAt(0) === "#") h = h.slice(1);
  const i = h.indexOf("?");
  const path = (i < 0 ? h : h.slice(0, i)).replace(/^\/+|\/+$/g, "");
  const qs = i < 0 ? "" : h.slice(i + 1);
  const query = {};
  qs.split("&").filter(Boolean).forEach(kv => {
    const j = kv.indexOf("=");
    const k = j < 0 ? kv : kv.slice(0, j), v = j < 0 ? "" : kv.slice(j + 1);
    query[dec(k)] = dec(v);
  });
  return { path, parts: path.split("/").filter(Boolean), query };
}
function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
/* `,` `:` `;` and `/` are legal in a fragment and are what makes a coordinate link readable
   ("p=55.6545,12.539:Test", not "p=55.6545%2C12.539%3ATest"), so they survive encoding */
function enc(s) { return encodeURIComponent(String(s)).replace(/%2C/g, ",").replace(/%3A/g, ":").replace(/%3B/g, ";").replace(/%2F/g, "/"); }
/* every key whose value is not null/undefined, in insertion order — "" is kept, it is a value */
function buildHash(path, query) {
  const q = [];
  Object.keys(query || {}).forEach(k => {
    const v = query[k];
    if (v === null || v === undefined) return;
    q.push(enc(k) + "=" + enc(v));
  });
  const p = String(path || "");
  return q.length ? p + "?" + q.join("&") : p;
}

/* ---------- coordinates ---------- */
/* five decimals is ~1 m — the precision the pin has always been serialised with */
const round5 = n => Number(Number(n).toFixed(5));
/* "55.65450,12.53900" → [55.6545, 12.539]; anything else → null */
function parseLatLon(s) {
  const m = String(s == null ? "" : s).trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = round5(m[1]), lon = round5(m[2]);
  if (!isFinite(lat) || !isFinite(lon)) return null;
  return [lat, lon];
}
/* the v3 property codec: "lat,lon[:label]", list-capable (";") so the LATER portfolio needs no
   second format — v3.0 reads and writes one item (owner amendment A2) */
function propSerialise(items) {
  return (items || []).map(p => {
    const ll = `${round5(p.lat)},${round5(p.lon)}`;
    return p.label ? `${ll}:${p.label}` : ll;
  }).join(";");
}
function propParse(s) {
  return String(s == null ? "" : s).split(";").map(part => {
    const i = part.indexOf(":");
    const ll = parseLatLon(i < 0 ? part : part.slice(0, i));
    if (!ll) return null;
    return { lat: ll[0], lon: ll[1], label: i < 0 ? "" : part.slice(i + 1) };
  }).filter(Boolean);
}

/* ---------- old → new ---------- */
const LEVELS = ["kommune", "postnr", "kvarter"];
const AREA_TYPES = ["kommune", "postnr", "kvarter"];

/* the table, one row per old path. `to` returns the new { path, query } or null for "leave it". */
const ALIASES = {
  table:    (parts, q) => ({ path: "data/areas/" + (LEVELS.indexOf(parts[1]) >= 0 ? parts[1] : "kommune"), query: q }),
  pipeline: (parts, q) => ({ path: "data/projects", query: q }),
  /* the Data section itself: `#data` and `#data/areas` are spelled out in full, so a bare link is
     already the canonical link and the tab bar never has to guess which level it is showing */
  data:     (parts, q) => {
    const tab = parts[1] || "areas";
    if (tab === "projects" || tab === "national" || tab === "sources") return { path: "data/" + tab, query: q };
    return { path: "data/areas/" + (LEVELS.indexOf(parts[2]) >= 0 ? parts[2] : "kommune"), query: q };
  },
  /* #sources was already an alias for "market with the sources panel open"; both land on the tab */
  market:   (parts, q) => { const src = q.src === "1"; const r = Object.assign({}, q); delete r.src;
                            return { path: src ? "data/sources" : "data/national", query: r }; },
  sources:  (parts, q) => { const r = Object.assign({}, q); delete r.src; return { path: "data/sources", query: r }; },
  /* the pin leads: a shared property link reads "property?p=55.6545,12.539:Vesterbro" first */
  analysis: (parts, q) => {
    const ll = parseLatLon(q.a), r = {};
    if (ll) r.p = propSerialise([{ lat: ll[0], lon: ll[1], label: q.la || "" }]);
    Object.keys(q).forEach(k => { if (k !== "a" && k !== "la" && k !== "p") r[k] = q[k]; });
    return { path: "property", query: r };
  },
  /* Compare is deleted (owner amendment A1): the link lands on the first area's own page */
  compare:  (parts, q) => {
    const r = Object.assign({}, q); delete r.a; delete r.b;
    const m = String(q.a || "").split(":");
    if (m.length === 2 && AREA_TYPES.indexOf(m[0]) >= 0 && m[1]) return { path: `area/${m[0]}/${m[1]}`, query: r };
    return { path: "map", query: r };
  },
};

/* `map…&climate=1`: the overlay becomes an indicator. An explicit climate indicator in the link
   wins — the flag only decides what to show when the link names a non-climate one. */
function climateFlag(query, isClim) {
  const q = Object.assign({}, query);
  if (q.climate !== "1") return q;
  delete q.climate;
  const test = typeof isClim === "function" ? isClim : (k => CLIM_KEY_RX.test(k));
  if (!q.ind || !test(q.ind)) q.ind = CLIM_FALLBACK_IND;
  return q;
}

/* The three map overlays became one `Layers ▾` menu (spec §4.4), so their three flags became one
   comma list: `infra=1&public=1&services=1` → `lay=infra,public,services`. A link that already
   spells `lay=` keeps what it names and the flags only add to it, so this stays idempotent. */
const LAY_FLAGS = [["infra", "infra"], ["public", "public"], ["services", "services"]];
function layerFlags(query) {
  const q = Object.assign({}, query);
  const on = String(q.lay == null ? "" : q.lay).split(",").filter(Boolean);
  let had = false;
  LAY_FLAGS.forEach(([flag, name]) => {
    if (!Object.prototype.hasOwnProperty.call(q, flag)) return;
    had = true;
    if (q[flag] === "1" && on.indexOf(name) < 0) on.push(name);
    delete q[flag];
  });
  if (!had) return q;
  if (on.length) q.lay = on.join(",");
  else delete q.lay;
  return q;
}

/* old hash → the canonical v3 hash. Idempotent: toV3(toV3(h)) === toV3(h) for every h. */
function toV3(hash, opts) {
  const o = opts || {};
  const { parts, query } = splitHash(hash);
  const head = parts[0] || "map";
  const fn = Object.prototype.hasOwnProperty.call(ALIASES, head) ? ALIASES[head] : null;
  if (fn) { const r = fn(parts, query); return buildHash(r.path, r.query); }
  if (head === "map") return buildHash(parts.join("/") || "map", layerFlags(climateFlag(query, o.isClim)));
  return buildHash(parts.join("/") || "map", query);
}

/* ---------- either spelling → the internal view ---------- */
/* Returns { view, parts, query }: `view` is an S.view id (unchanged from v2.6 on purpose),
   `parts` the path segments the router reads, `query` normalised to the keys app.js already
   knows (property `p=` is handed back as `a=` + `la=`, so parseHash needs no second branch). */
function toInternal(hash, opts) {
  const v3 = toV3(hash, opts);
  const { parts, query } = splitHash(v3);
  const q = Object.assign({}, query);
  const head = parts[0] || "map";
  if (head === "data") {
    const tab = parts[1] || "areas";
    if (tab === "projects") return { view: "pipeline", parts: ["pipeline"], query: q };
    if (tab === "national") return { view: "market", parts: ["market"], query: q };
    if (tab === "sources") { q.src = "1"; return { view: "market", parts: ["market"], query: q }; }
    const lvl = LEVELS.indexOf(parts[2]) >= 0 ? parts[2] : "kommune";
    return { view: "table", parts: ["table", lvl], query: q };
  }
  if (head === "property") {
    const items = propParse(q.p);
    delete q.p;
    if (items.length) { q.a = `${items[0].lat},${items[0].lon}`; if (items[0].label) q.la = items[0].label; }
    return { view: "analysis", parts: ["analysis"], query: q };
  }
  if (head === "area") return { view: "area", parts, query: q };
  if (head === "map") return { view: "makro", parts, query: q };
  return { view: head, parts, query: q };
}

const API = { CLIM_FALLBACK_IND, ALIASES, splitHash, buildHash, parseLatLon, round5,
              propParse, propSerialise, climateFlag, layerFlags, toV3, toInternal };
if (typeof window !== "undefined") window.ROUTE_CORE = API;
if (typeof module !== "undefined" && module.exports) module.exports = API;

})();
