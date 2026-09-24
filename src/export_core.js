/* The export model — the pure parts, kept out of src/app.js so they can be unit-tested. Same
   arrangement as src/climate_core.js, src/route_core.js and src/picker_core.js: no DOM, no globals,
   no fetch. `node --test tests/export.test.js` runs against this file.

   What lives here is everything about an export file that is a function of the registry and the
   source catalogue alone (spec §4.9, engineering brief §3):

     · the column sets — one long schema for areas, national series and the test property, and an
       own schema for projects, the sources catalogue, the climate exposure and the nearby file;
     · the source columns of one row (publisher, table id, verify URL, as of, fetched, licence),
       filled from `tables` → `proj` → `climate_src` → `src_page` → the table id inside the source
       string (the Copenhagen quarter registry carries it nowhere else), and never left blank;
     · the unit fix: a `fmt: kdkk` indicator is stored in DKK, so the file says DKK and writes the
       raw number — a kDKK label on a DKK value was the v2.6 export bug (AC-X2);
     · `period_type` and `value_type`, derived from the registry rather than guessed per view;
     · the CSV rules: `;` separator, `.` decimal, no grouping, no separator inside a cell.

   app.js owns which areas and which observations go in — it is the side that knows the data.
*/
"use strict";
/* Wrapped in an IIFE: the build inlines this file and app.js as classic <script> blocks in one
   global lexical scope, so a top-level const here would collide with app.js and blank the page. */
(function () {

/* ---------- column sets (spec §4.9) ---------- */
const AREA_COLS = ["level", "code", "name", "parent_code", "parent_name", "region", "population",
                   "indicator", "label", "unit", "period", "period_type", "value", "value_type",
                   "inherited_from", "direction", "source", "table_id", "source_url", "as_of",
                   "fetched", "licence"];
/* the test property's file is the long schema behind the three columns that say which pin it is */
const PROP_LEAD = ["property_label", "lat", "lon"];
const PROP_COLS = PROP_LEAD.concat(AREA_COLS);
const PROJECT_COLS = ["id", "name", "type", "status", "status_note", "opening", "opening_original",
                      "budget_mdkk", "agency", "municipalities", "postal_codes", "quarters",
                      "geometry_kind", "length_km", "stations", "source_doc", "source_url", "updated"];
const SOURCE_COLS = ["key", "label", "publisher", "tables", "as_of", "fetched", "url", "licence", "used_for"];
const CLIMATE_COLS = ["level", "code", "name", "parent_code", "parent_name", "horizon", "zone_year",
                      "dwellings", "dwellings_in_zone", "surge_dw_pct", "zone_km2", "value_type",
                      "source", "table_id", "source_url", "as_of", "fetched", "licence"];
const NEARBY_COLS = ["kind", "name", "type", "status", "distance_m", "source", "source_url"];

/* ---------- CSV (spec §4.9: UTF-8 BOM, `;`, `.` decimal, no grouping, one comment-free file) ----------
   The separator can never appear inside a cell, so no quoting is needed and Danish Excel opens the
   file by double-click. A newline or a tab inside a publisher's note becomes one space. */
const SEP = ";";
function cell(v) {
  if (v == null) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  return String(v).replace(/\s+/g, " ").replace(/;/g, ",").trim();
}
function line(vals) { return (vals || []).map(cell).join(SEP); }
function csvLines(cols, rows) { return [line(cols)].concat((rows || []).map(line)); }

/* ---------- publishers, table ids and verify links (engineering brief §3.2) ---------- */
const STATBANK = "https://api.statbank.dk/v1";
/* every column can be filled for every row, but a table id cannot be invented: 19 indicators come
   from a register or a curated layer and have none. The cell says so rather than being blank. */
const NO_TABLE = "n/a (register/curated)";
const PUBLISHERS = { dst: "Danmarks Statistik", s20: "Finans Danmark", s30: "Københavns Kommune",
  climate: "Danmarks Statistik", forecast: "Danmarks Statistik", net_dwellings: "Danmarks Statistik",
  bbr: "BBR via Datafordeler", public: "BBR via Datafordeler", infra: "Curated layer (docs/INFRA.md)",
  schools: "Uddannelsesstatistik.dk (STIL)", boligstat: "Social- og Boligstyrelsen",
  lbf: "Landsbyggefonden", kk_tryghed: "Københavns Kommune", cph_forecast: "Københavns Kommune",
  cph_backtest: "Københavns Kommune" };
/* an indicator whose source is only a publisher's page still joins to the catalogue row that
   carries the licence and the fetch date — the page string is the key the registry gives us */
const PAGE_CAT = { "Social- og Boligstyrelsen, boligstat.dk": "boligstat", "Landsbyggefonden": "lbf",
  "BBR via Datafordeler": "bbr", "the curated infrastructure layer": "infra",
  "Uddannelsesstatistik.dk (STIL)": "schools" };
const KK_RX = /\b(KK[A-Z0-9]{2,})\b/;                    /* "Københavns Kommune, KKBOL3" → KKBOL3 */
const DST_RX = /\b([A-ZÆØÅ]{2,}\d+[A-Z0-9]*)\b/;         /* "DST PRIS01" → PRIS01 */
const SB_DB = { "": 1, dst: 1, s20: 1, s30: 1 };         /* the databases a tableinfo URL exists in */

function catKey(key) { const p = String(key == null ? "" : key).split("/"); return p.length > 1 ? { db: p[0], table: p.slice(1).join("/") } : { db: "", table: p[0] }; }
const tableIdOf = key => catKey(key).table;
function publisherOf(key, label) {
  const k = catKey(key);
  return PUBLISHERS[k.db || k.table] || String(label == null ? "" : label).split(/[,—]/)[0].trim() || "";
}
/* the publisher's own description of the table — the only per-table URL that exists for every
   StatBank database the dashboard reads (dst has no database segment in its path) */
function tableInfoUrl(key) {
  const { db, table } = catKey(key);
  if (!table || !SB_DB[db] || !/^[A-ZÆØÅ0-9_]+$/.test(table)) return "";
  return `${STATBANK}/${db && db !== "dst" ? db + "/" : ""}tableinfo/${table}`;
}
const kkTableOf = s => { const m = KK_RX.exec(String(s == null ? "" : s)); return m ? m[1] : ""; };
const dstTableOf = s => { const m = DST_RX.exec(String(s == null ? "" : s)); return m ? m[1] : ""; };

/* the six source columns of one indicator row. `opts.asof` is the stamp of this observation (the
   registry publishes one per level and per history year); everything else is the registry's. */
function indSource(i, opts) {
  i = i || {}; opts = opts || {};
  const cat = opts.cat || {}, built = opts.built || "";
  const tables = (i.tables || []).filter(Boolean);
  let table_id = "", url = "", c0 = {};
  if (tables.length) {
    table_id = tables.map(tableIdOf).join(" ");
    c0 = cat[tables[0]] || {};
    url = c0.url || tableInfoUrl(tables[0]);
  } else if (i.proj && i.proj.table) {
    table_id = i.proj.table;
    c0 = cat[i.proj.publisher === "DST" ? "forecast" : "cph_forecast"] || {};
    const db = (i.proj.src && i.proj.src.db) || (/^KK/.test(i.proj.table) ? "s30" : "");
    url = tableInfoUrl(`${db}/${i.proj.table}`) || c0.url || "";
  } else if (i.climate_src) {
    table_id = NO_TABLE;
    c0 = cat["climate/climate_index"] || {};
    url = i.climate_src.service || i.climate_src.url || c0.url || "";
  } else if (kkTableOf(i.source)) {
    table_id = kkTableOf(i.source);
    c0 = cat["s30/" + table_id] || {};
    url = c0.url || tableInfoUrl("s30/" + table_id);
  } else if (i.src_page) {
    table_id = NO_TABLE;
    c0 = cat[PAGE_CAT[i.src_page[0]] || ""] || {};
    url = i.src_page[1] || c0.url || "";
  } else if (dstTableOf(i.source)) {
    /* named in prose only — "BOL101 and FOLK1A" — which is still a published table id */
    table_id = dstTableOf(i.source);
    c0 = cat["dst/" + table_id] || {};
    url = c0.url || tableInfoUrl("dst/" + table_id);
  }
  const source = String(i.source || c0.label || publisherOf("", i.source) || "").trim() || "see Data › Sources";
  return { source,
           table_id: table_id || NO_TABLE,
           source_url: url || "",
           as_of: String(opts.asof || "").trim() || c0.asof || built,
           fetched: c0.fetched || built,
           licence: c0.licence || "" };
}

/* ---------- units, periods, value types ----------
   `income` and `income_med` are declared kDKK but stored in DKK (engineering brief §3.3). The file
   writes the number it holds and labels it DKK: lossless, and no reader multiplies by a thousand
   twice. Any other row whose unit says kDKK is converted, so the label always matches (AC-X2). */
const KDKK_MAX = 10000;
function unitValue(i, v) {
  i = i || {};
  const unit = String(i.unit || "");
  if (i.fmt === "kdkk") return { unit: unit.replace(/kDKK/g, "DKK") || "DKK", value: v };
  if (/kDKK/.test(unit) && typeof v === "number" && Math.abs(v) >= KDKK_MAX) return { unit, value: v / 1000 };
  return { unit, value: v };
}
/* Plain arithmetic on published figures, not a published cell of its own: a per-1,000 rate, and a
   climate exposure share — the publisher gives a polygon (`climate_src.kind = service_layer`) and
   the count of dwellings inside it is ours. Both are named in the indicator's own label. */
const isDerived = i => !!i && (i.fmt === "per1000" || /per 1,000|\/\s*1,000/.test(i.unit || "")
                               || !!(i.climate_src && i.climate_src.kind === "service_layer"));
/* `period` is the publisher's own label; its type is read off the label unless the caller knows
   better (a horizon and a projection window are not periods you can sniff) */
function periodType(period, kind) {
  if (kind === "horizon" || kind === "projection" || kind === "snapshot") return kind;
  const p = String(period == null ? "" : period).trim();
  if (/^\d{4}$/.test(p)) return "year";
  if (/^\d{4}K\d$/.test(p)) return "quarter";
  if (/^\d{4}M\d{2}$/.test(p)) return "month";
  if (/\d{4}\s*\/\s*\d{4}/.test(p)) return "school_year";
  /* the dash a publisher uses varies: hyphen, en dash, em dash or the arrow of a rolling window */
  if (/\d{4}(K\d)?\s*[-–—→]\s*\d{4}/.test(p)) return "window";
  if (/^\d{4}-\d{2}-\d{2}$/.test(p)) return "snapshot";
  return "snapshot";
}
function valueType(i, o) {
  i = i || {}; o = o || {};
  if (o.inherited) return "inherited";
  if (o.kind === "horizon") return o.horizon && o.horizon !== "today" ? "projection" : (isDerived(i) ? "derived" : "actual");
  if (i.proj || o.kind === "projection") return "projection";
  return isDerived(i) ? "derived" : "actual";
}

/* ---------- the long schema: one row per area × indicator × period ----------
   `spec.row` is the area (code, name, parents, region, population), `spec.obs` one observation
   ({period, kind, value, asof}) and `spec.inherited` the municipality a value was read from. */
function areaRow(spec) {
  const s = spec || {}, i = s.ind || {}, r = s.row || {}, o = s.obs || {};
  const u = unitValue(i, o.value);
  const src = indSource(i, { cat: s.cat, built: s.built, asof: o.asof });
  return [s.level, r.code, r.name, r.parent_code, r.parent_name, r.region, r.population,
          i.key, i.label, u.unit, o.period, periodType(o.period, o.kind), u.value,
          valueType(i, { inherited: !!s.inherited, kind: o.kind, horizon: o.horizon }),
          s.inherited ? s.inherited.code : "", i.direction || "",
          src.source, src.table_id, src.source_url, src.as_of, src.fetched, src.licence];
}
/* every level × every area × every indicator × every published period. The caller supplies the
   areas (`levels`), which observations an indicator has (`periods`) and where a value is read from
   when the area does not publish it itself (`inherited`). */
function areaRows(ctx) {
  const c = ctx || {}, out = [];
  (c.levels || []).forEach(L => (L.rows || []).forEach(r => (L.inds || []).forEach(i => {
    const inh = c.inherited ? c.inherited(i, r, L) : null;
    const from = inh ? inh.o : r.o;
    if (!from) return;
    (c.periods(i, from, inh ? "kommune" : L.asofLevel, !!inh) || []).forEach(p => {
      if (p.value == null) return;
      out.push(areaRow({ level: L.level, row: r, ind: i, obs: p, inherited: inh, cat: c.cat, built: c.built }));
    });
  })));
  return out;
}
/* the test property (spec §5.5′): the pin's three columns in front of the same long schema */
function propertyRows(ctx) {
  const c = ctx || {}, lead = [c.label || "Test property", c.lat, c.lon];
  return areaRows(c).map(r => lead.concat(r));
}

/* ---------- the national series (long, `period_type` month / quarter / year) ---------- */
function nationalRows(ctx) {
  const c = ctx || {}, out = [];
  Object.keys(c.series || {}).forEach(k => {
    const lt = (c.latest || {})[k] || {}, table = dstTableOf(lt.src);
    const c0 = (c.cat || {})["dst/" + table] || {};
    (c.series[k] || []).forEach(pt => {
      if (!pt || pt.v == null) return;
      out.push(["denmark", "DK", "Denmark", "", "", "", "",
                k, lt.label || k, lt.unit || "", pt.t, periodType(pt.t), pt.v, "actual", "", "",
                lt.src || "Danmarks Statistik", table || NO_TABLE,
                c0.url || tableInfoUrl("dst/" + table), pt.t, c0.fetched || c.built, c0.licence || ""]);
    });
  });
  return out;
}

/* ---------- projects — its own schema, never an indicator column (AC-X3) ---------- */
function projectRow(x) {
  const p = (x && x.p) || {};
  return [p.id, p.name, p.type, p.status, p.notes || "",
          p.open_window || (p.open_year == null ? "" : p.open_year), p.open_year_original == null ? "" : p.open_year_original,
          p.budget_mdkk == null ? "" : p.budget_mdkk, p.agency || "",
          ((x && x.municipalities) || []).join(" "), ((x && x.postal_codes) || []).join(" "),
          ((x && x.quarters) || []).join(" "), (x && x.geometry_kind) || "",
          x && x.length_km != null ? Math.round(x.length_km * 100) / 100 : "",
          x && x.stations != null ? x.stations : "",
          p.source_doc || "", p.source_url || "", p.updated || ""];
}
const projectRows = list => (list || []).map(projectRow);

/* ---------- the sources catalogue — the same rows Data › Sources shows ----------
   An empty "fetched" falls back to the build date, the way the table does: the source file carries
   no fetch date of its own, and a blank cell says less than the date the dashboard was built. */
function sourceRecs(ctx) {
  const c = ctx || {};
  return (c.sources || []).map(x => ({
    key: x.key || "", label: x.label || "", publisher: publisherOf(x.key, x.label),
    table_id: tableIdOf(x.key), tables: x.tables || "", as_of: x.asof || "",
    fetched: x.fetched || c.built, build_fetched: !x.fetched,
    url: x.url || tableInfoUrl(x.key), licence: x.licence || "",
    used_for: (c.usedFor && c.usedFor(x)) || "" }));
}
const sourceRows = ctx => sourceRecs(ctx).map(r => SOURCE_COLS.map(k => r[k]));

/* ---------- climate exposure: dwellings inside the published zone, per level × horizon ---------- */
function climateRow(r, ctx) {
  const c = ctx || {}, row = r || {};
  const src = indSource(c.ind, { cat: c.cat, built: c.built, asof: row.as_of });
  return [row.level, row.code, row.name, row.parent_code || "", row.parent_name || "",
          row.horizon, row.zone_year || "", row.dwellings == null ? "" : row.dwellings,
          row.in_zone == null ? "" : row.in_zone, row.pct == null ? "" : row.pct,
          row.zone_km2 == null ? "" : row.zone_km2,
          row.horizon && row.horizon !== "today" ? "projection" : "derived",
          src.source, src.table_id, src.source_url, src.as_of, src.fetched, src.licence];
}
const climateRows = ctx => ((ctx && ctx.rows) || []).map(r => climateRow(r, ctx));

/* ---------- the test property's second file: what lies near the pin (spec §5.5′) ---------- */
const nearbyRows = list => (list || []).map(x => [x.kind, x.name, x.type || "", x.status || "",
  x.distance_m == null ? "" : Math.round(x.distance_m), x.source || "", x.source_url || ""]);

/* `areas_long_2026-09-24.csv` — the data's own build date, not the reader's clock */
const fileName = (stem, date) => `${stem}_${date || "data"}.csv`;

const API = { AREA_COLS, PROP_LEAD, PROP_COLS, PROJECT_COLS, SOURCE_COLS, CLIMATE_COLS, NEARBY_COLS,
              SEP, NO_TABLE, PUBLISHERS, STATBANK, KDKK_MAX,
              cell, line, csvLines, catKey, tableIdOf, publisherOf, tableInfoUrl, kkTableOf, dstTableOf,
              indSource, unitValue, isDerived, periodType, valueType,
              areaRow, areaRows, propertyRows, nationalRows, projectRow, projectRows,
              sourceRecs, sourceRows, climateRow, climateRows, nearbyRows, fileName };
if (typeof window !== "undefined") window.EXPORT_CORE = API;
if (typeof module !== "undefined" && module.exports) module.exports = API;

})();
