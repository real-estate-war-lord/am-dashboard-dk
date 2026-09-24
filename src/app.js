/* AM Dashboard — Denmark Edition · app.js
   Design and interaction model ported from the Finnish edition; all data comes
   from window.DATA (built by scripts/build_dashboard.py from data/processed/*.json).

   DATA schema (see docs/DATA_MAP.md §4 and scripts/build_makro.py):
     meta          { built, sources:[{key,label,url,asof}], attribution:[...], note, years, latest_year }
     indicators    [ {key,label,short,unit,level:"kommune"|"postnr",hue:[r,g,b],fmt,desc,source,warn,group,asof,hist_asof} ]
     municipalities[ {code,name,region,pop, <indicator keys>..., hist:{key:{year:value}}} ]
     areas         [ {nr,name,muni,rings:[[[lat,lon],...],...],pop, <postnr-level keys>..., hist} ]
     cph           null | { meta, indicators, areas:[{code,name,bydel,bydel_code,muni,rings,pop,<keys>,hist}] }
     macro         { series:{key:[{t,v}]}, latest:{key:{t,v,label,unit,yoy}}, note }
     portfolio     null | { properties:[{name,address,muni,nr,lat,lon,units,vac,notice}] }

   Navigation is hash-based so every screen has a permalink and the browser back button works:
     #map            national map            #map/101         municipality drilled (postal codes)
     #map/101/postnr Copenhagen as postal codes (default: quarters)
     #table/kommune  table view (kommune | postnr | kvarter)
     #area/kommune/101 · #area/postnr/2100 · #area/kvarter/20101   area pages
     #market · #sources
   Query part: ?ind=<indicator>&y=<year>&g=<tile group>
*/
"use strict";
const D = window.DATA || {};
const IND = D.indicators || [];
const MUNI = D.municipalities || [];
const AREAS = D.areas || [];
const LOCALE = "da-DK";

/* ---------- helpers ---------- */
const nf = (n, d = 1) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = (n, f) => n == null || isNaN(n) ? "–" : (n > 0 ? "+" : "") + f(n);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const FMT = {
  pct0: v => nf(v, 0) + " %", pct1: v => nf(v, 1) + " %", signpct1: v => sign(v, x => nf(x, 1) + " %"),
  kdkk: v => nf(v / 1000, 0) + " kDKK", dkk0: v => nf(v, 0) + " DKK", dkk1: v => nf(v, 1) + " DKK",
  int: v => nf(v, 0), days: v => nf(v, 0) + " d", m2: v => nf(v, 0) + " m²", per1000: v => per1000(v) + " / 1,000", idx: v => nf(v, 1),
  /* grade points: signed, one decimal, no unit — the socioeconomic reference difference */
  signdec1: v => sign(v, x => nf(x, 1))
};
/* rates per 1,000 (crime, homes for sale): no % sign — the unit is in the label, the legend title and the column head.
   Whole numbers once the rate is large enough for a decimal to be noise. */
const per1000 = v => nf(v, Math.abs(v) >= 20 ? 0 : 1);
const FMT_TIGHT = { per1000 };                       /* map labels, legend bins, chart axis ticks: value only */
const fmtOf = i => FMT[i.fmt] || FMT.pct1;
const fmtTight = i => FMT_TIGHT[i.fmt] || fmtOf(i);
const isPct = i => (i.fmt || "").startsWith("pct") || i.fmt === "signpct1";
const median = arr => { const v = arr.filter(x => x != null && !isNaN(x)).sort((a, b) => a - b); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
const byCode = {}; MUNI.forEach(m => byCode[m.code] = m);
const byNr = {}; AREAS.forEach(a => byNr[a.nr] = a);
/* Copenhagen quarter layer (data/processed/cph.json): 67 kvarterer with their own indicator set */
const CPH = D.cph && D.cph.areas && D.cph.areas.length ? D.cph : null;
const IND_CPH = CPH ? CPH.indicators : [];
const CPH_MUNI = "101";
const byQ = {}; if (CPH) CPH.areas.forEach(a => byQ[a.code] = a);
/* Safety (STRAF11/STRAF22) exists per municipality only: postal codes and Copenhagen quarters show the municipality value (°) */
const SAFETY = IND.filter(i => i.group === "Safety");
const isSafety = i => !!i && i.group === "Safety";
const cphOwn = key => IND_CPH.some(i => i.key === key);
/* the quarter layer's own indicators plus the inherited Safety family */
const IND_Q = IND_CPH.concat(SAFETY.filter(i => !cphOwn(i.key)));
/* registry `direction`: for lower_better indicators rank #1 is the lowest value and a fall is the good change */
/* quarter-layer indicators that are published per district (bydel), not per quarter: the KK survey's crime and
   safety shares, and unemployment — their values carry ^ instead of the ° of a municipality value */
const bydelLevel = i => !!i && !!i.geo_level && i.geo_level !== "kvarter";
const bydelMark = i => bydelLevel(i) ? " ^" : "";
const indOf = key => IND.concat(IND_CPH).find(i => i.key === key) || null;
const lowerBetter = key => { const i = indOf(key); return !!i && i.direction === "lower_better"; };
/* `neutral` is a third direction beside higher_better / lower_better: neither end is better, so the
   indicator is never coloured good/bad, never carries the "↓ lower is better" note, and its rank is
   shown as a position without a better/worse judgement (docs/FORECAST.md §3 "Colour and direction"). */
const neutralDir = key => { const i = indOf(key); return !!i && i.direction === "neutral"; };
/* an Outlook indicator is one vintage of a projection, not a per-year series */
const projOf = key => { const i = indOf(key); return (i && i.proj) || null; };
/* ---------- Verify at source ----------
   Rebuilds the publisher's own CSV query from the pieces the build recorded: the sub-database,
   the table id (which carries the vintage), the area variable's id and the years. Nothing here is
   hard-coded per vintage — when KKFR2026 becomes KKFR2027 the link follows the data.
     https://api.statbank.dk/v1/s30/data/KKFR2026/CSV?lang=en&OMRKK=20104&Tid=2026,2031,2040 */
const STATBANK = "https://api.statbank.dk/v1";
function srcUrl(src, code) {
  if (!src || !src.table || !src.area_var || code == null) return "";
  const db = src.db ? `${src.db}/` : "";
  const years = (src.years || ["*"]).join(",");
  const extra = Object.entries(src.vars || {}).map(([k, v]) => `&${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("");
  return `${STATBANK}/${db}data/${encodeURIComponent(src.table)}/CSV?lang=en`
    + `&${encodeURIComponent(src.area_var)}=${encodeURIComponent(code)}${extra}&Tid=${encodeURIComponent(years)}`;
}
/* the link itself — always a new tab, always naming who publishes it */
function srcLink(src, code, label) {
  const u = srcUrl(src, code);
  if (!u) return "";
  const who = src.publisher_label || "the publisher";
  return `<a class="srclink" href="${esc(u)}" target="_blank" rel="noopener"
    title="Open the published figures for this area straight from ${esc(who)} — the same cells this value is computed from">${esc(label || "Verify at source")} ↗ <span class="dim">(${esc(who)})</span></a>`;
}
/* the code an area is known by in its own source table */
const srcCode = (o, level) => level === "kvarter" ? (o.code || "") : (o.code || o.muni || "");
/* any indicator, any area: the per-area query where the source is a StatBank table, otherwise the
   publisher's own page. Every indicator has one or the other — none is left without a destination. */
/* which published table a code belongs to — an indicator may list one per level, and sending a
   postal code to a municipal table is a 400 rather than a wrong answer */
const AREA_VAR_LEVEL = { KOMMUNEDK: "kommune", "OMRÅDE": "kommune", OMRADE: "kommune",
                         BOPOMR: "kommune", OMR20: "kommune", PNR20: "postnr", OMRKK: "kvarter" };
function pickSrc(i, level) {
  const list = i.src_verify || [];
  return list.find(q => AREA_VAR_LEVEL[q.area_var] === level) || list[0] || null;
}
function indSrcLink(i, code, label, level) {
  if (!i) return "";
  /* every Climate figure is published for a kommune or its coastal stretch, so a postal code or a
     quarter verifies against the kommune it sits in, never against a code its publisher has never seen */
  if (isClim(i.key)) {
    const lv = level || "kommune";
    const kom = lv === "postnr" ? ((byNr[code] || {}).muni) : lv === "kvarter" ? CPH_MUNI : code;
    return climSrcLink(i, kom || MK.muni || "", label);
  }
  const q = pickSrc(i, level || "kommune") || ((i.proj || {}).src);
  if (q && code != null && code !== "") return srcLink(q, code, label);
  if (i.src_page) return `<a class="srclink" href="${esc(i.src_page[1])}" target="_blank" rel="noopener"
    title="This figure does not come from a per-area StatBank query — open the publisher's own page">${esc(label || "Verify at source")} ↗ <span class="dim">(${esc(i.src_page[0])})</span></a>`;
  return "";
}
/* "Projected change 2026→2031: −492 residents (−1.3 %/yr)" — the absolute change in people first,
   because a rate on its own does not tell a reader how many. Both come from the same two published
   cells: the projected population in the first year and in the fifth. */
function projChangeLine(o, level) {
  const list = level === "kvarter" ? IND_CPH : IND;
  const ri = list.find(i => i.key === "fc_pop_rate_5y");
  if (!ri || !o || !o.fc_pop) return "";
  const from = (ri.proj && ri.proj.from) || "2026", to = (ri.proj && ri.proj.to) || "2031";
  const a = o.fc_pop[from], b = o.fc_pop[to];
  if (a == null || b == null) return "";
  const abs = b - a, rate = o.fc_pop_rate_5y;
  return `Projected change ${esc(from)}→${esc(to)}: <b>${sign(abs, x => nf(x, 0))} residents</b>`
    + (rate != null ? ` (${sign(rate, x => nf(x, 1))} %/yr)` : "");
}
/* "Projection, DST 2026" at kommune level, "Projection, Københavns Kommune 2026" at kvarter/bydel —
   the publisher is read from the data, never inferred from the view (docs/FORECAST.md §4, §8). */
const projLegendNote = ind => `Projection, ${(ind.proj && ind.proj.publisher) || "DST"} ${(ind.proj && ind.proj.vintage) || ""}`.trim();
/* the year selector's replacement line for a single-vintage indicator */
const projWindow = ind => ind && ind.proj ? `Projection ${ind.proj.from}→${ind.proj.to} · ${ind.proj.publisher} ${ind.proj.vintage}` : "";
/* fc_20_34_rel is "vs Denmark" on the municipal map and "vs København" on the quarter map. Which one
   is recorded in the data (meta.relative_baseline → proj.relative_label); never guessed from the key. */
const relLabel = ind => (ind && ind.proj && ind.proj.relative_label) || "vs Denmark";
const cphMode = () => !!(CPH && MK.muni === CPH_MUNI && MK.cphView !== "postnr");
const S = { view: "makro" };
const YEARS = [...new Set([...((D.meta && D.meta.years) || []), ...((D.cph && D.cph.meta && D.cph.meta.years) || [])])].sort();
const LATEST = (D.meta && D.meta.latest_year) || (YEARS[YEARS.length - 1] || "");
/* `zones` is the Climate context layer's override: it is on whenever a Climate indicator is active
   (spec §1 decision 3) and only "hidden" is worth a URL key (`zones=0`). */
const MK = { ind: (IND[0] || {}).key, muni: null, own: false, year: LATEST, cphView: "kvarter", micro: false, mind: "rented_pct", infra: false, pub: false, srv: false, zones: true };
/* Micro (building) layer: dist/micro/<kommune>.json, loaded on demand; D.micro = index {code: {file, n}} */
const MICRO_IDX = (D.micro && D.micro.municipalities) || {};
const MICRO = {};                                  /* code → {meta, b:[…]} once loaded */
const MICRO_INDS = [
  { key: "rented_pct", label: "Rented dwellings", short: "Rented", unit: "% of dwellings", fmt: "pct0", hue: [40, 84, 128], col: 3, breaks: [20, 40, 60, 80] },
  { key: "vacant_pct", label: "Unoccupied dwellings", short: "Unoccupied", unit: "% of dwellings", fmt: "pct0", hue: [166, 42, 22], col: 4, breaks: [2, 5, 10, 20] },
  { key: "avg_m2", label: "Average dwelling size", short: "Ø m²", unit: "m²", fmt: "m2", hue: [90, 60, 150], col: 5 },
  { key: "year", label: "Year built", short: "Built", unit: "year", fmt: "int", hue: [10, 88, 70], col: 6 },
  { key: "dwellings", label: "Dwellings in building", short: "Dwellings", unit: "dwellings", fmt: "int", hue: [150, 90, 30], col: 2 },
  { key: "small_pct", label: "Small dwellings < 50 m²", short: "< 50 m²", unit: "% of dwellings", fmt: "pct0", hue: [12, 94, 104], col: 13, breaks: [10, 25, 50, 75] },
  { key: "floors", label: "Floors", short: "Floors", unit: "floors", fmt: "int", hue: [92, 110, 140], col: 7 }];
const MTYPE = { 1: "house", 2: "row house", 3: "multi-dwelling", 4: "other / mixed" };
const MF = { minDw: 2, yFrom: "", yTo: "", type: "", rentMin: 0 };   /* building filters */
const microAvail = code => !!(code && MICRO_IDX[String(Number(code))]);
const microMode = () => !!(MK.micro && MK.muni && microAvail(MK.muni));
const curMind = () => MICRO_INDS.find(i => i.key === MK.mind) || MICRO_INDS[0];
/* area page (spec §5.2): the entity, which sub-level its Postal codes / Quarters table shows, and
   which of the four toggles are open — the last one is the `show=` key */
const AR_SECS = ["outlook", "figures", "sub", "info"];
const AR = { type: null, code: null, sub: "kvarter", show: new Set() };
/* Population outlook opens itself on a municipality page and nothing opens on a postal code or a
   quarter (spec §9, pushback on wish 5). `show=` is written only when the reader changed that. */
const arShowDefault = () => AR.type === "kommune" ? ["outlook"] : [];
/* fold states that survive a re-render. `xOpen` names *which* Export ▾ is open ("side" = the
   sidebar footer, "page" = the Data or test-property header): one menu at a time, two triggers. */
const UI = { indxOpen: false, mfOpen: false, layOpen: false, mmFull: false, xOpen: "", legOpen: false };
const MKT = { src: false };                                                        /* market: sources panel open */
const CH = { ind: (IND[0] || {}).key, areas: [], y0: "", y1: "", median: true, title: "", mode: "auto", dist: "size", fq: "year", ov: [], nat: true };   /* chart generator; fq = year | q, ov = overlay indicators, nat = Denmark line */
const PR = { id: null };                                                          /* project datasheet */
const PB = { kom: null, id: null };                                               /* public-building sheet */
const PL = { key: "" };                                                           /* public list panel: "<level>:<code>:<cat>:<kind>" */
const SC = { nr: null };                                                          /* school datasheet */
const SL = { key: "" };                                                           /* school list panel: "<level>:<code>" */
/* public-buildings filter, shared by the map, the legend and the area card. cats = null means all. */
const PF = { cats: null, kind: "both" };
const PF_NONE = "none";                                                           /* hash value for "every category off" */
const pubAllOff = () => !!(PF.cats && !PF.cats.size);
const PF_SHORT = { education: "edu", institutions: "inst", health: "health", culture: "culture" };
const PF_LONG = Object.fromEntries(Object.entries(PF_SHORT).map(([k, v]) => [v, k]));
const PIPE = { type: "", status: "" };                                            /* pipeline filters */
/* Test property (spec §5.5′, amendment A2): ONE pin, `#property?p=lat,lon[:label]`.
   `rad` is the ring the mini map draws and the "within the ring" sections count inside;
   `show` is the open set of the eight <details> sections, serialised as `show=`. */
const AN = { a: "", label: "", rad: 1000, show: new Set() };
const TP_SECS = ["outlook", "profile", "safety", "infra", "public", "schools", "climate", "sources"];
/* Infrastructure nearby opens itself — it is the section that most often changes what an address is
   worth, and the only one whose answer is usually short enough to read without scrolling. */
const anShowDefault = () => ["infra"];
/* Test property: which overlays the mini map draws — the same feature layers the Macro map offers,
   chosen through the same Layers ▾ menu (spec §4.4). Defaults: infra on, public buildings on where
   the BBR pull reaches the pin, buildings off (its micro/<kommune>.json is fetched only once the
   layer is switched on). The set lives in the hash as lay=. */
const ANL = { infra: true, pub: true, micro: false, climate: false };
const anLayerList = () => [ANL.infra ? "infra" : "", ANL.pub ? "public" : "", ANL.micro ? "buildings" : "", ANL.climate ? "climate" : ""].filter(Boolean);
function anParseLayers(q) {
  if (q.lay == null) { ANL.infra = true; ANL.pub = true; ANL.micro = false; ANL.climate = false; return; }
  const set = new Set(q.lay.split(",").filter(Boolean));
  ANL.infra = set.has("infra"); ANL.pub = set.has("public"); ANL.micro = set.has("buildings"); ANL.climate = set.has("climate");
}
/* Test property: one pin dropped from a pasted Google Maps link or a "lat, lon" pair (parseLocation, src/testprop.js).
   It lives in the map hash (pin=, pl=), so it survives a reload and every level change. */
const TP_LABEL = "Test property";
const TP_RINGS = [500, 1000, 1200];                                               /* metres — the dashed walk/bike rings */
const TP = { lat: null, lon: null, label: TP_LABEL, res: null, msg: "", fit: false, rad: 0 };
/* Radius filter for a selected test property: the overlay layers (infra, public buildings,
   services) are cut to what lies within `rad` metres of the pin. It is plain great-circle
   arithmetic on published coordinates, and it lives in the hash (rad=), so it survives a
   reload, a zoom and every rung of the area ladder. 0 means off. */
const TP_RADII = [0, 500, 1000, 2000, 5000];
const tpRadOn = () => TP.lat != null && TP.rad > 0;
const tpWithin = (lat, lon) => !tpRadOn() || (lat != null && lon != null && havM(TP.lat, TP.lon, lat, lon) <= TP.rad);
const tpRadLabel = m => m >= 1000 ? (m / 1000) + " km" : m + " m";
const KOM = { list: null, err: false, p: null };   /* dist/geo/kommuner_lookup.json, fetched the first time a pin is dropped */
const T = { q: "", level: "kommune", region: "", minPop: 0 };                     /* table view filters */
const REGIONS = ["Hovedstaden", "Sjælland", "Syddanmark", "Midtjylland", "Nordjylland"];
const LF = { map: null, center: [56.0, 10.5], zoom: 7 };
const MICRO_ZOOM = 10;
/* quarter indicators whose definition matches the national one closely enough to put København next to a quarter */
const CPH_CMP = new Set(["growth", "young", "higher_ed", "renters", "almene", "avg_m2"]);
const muniCmp = (e, key) => !!e.muni && (e.type !== "kvarter" || CPH_CMP.has(key) || !cphOwn(key));
/* headline figures (area page header, map popups, municipality strip) — the first five available, in this order */
const HL_KEYS = ["growth", "price_m2", "rent_private", "unemp", "renters", "income_med", "young", "almene", "supply"];
/* the municipality card on the map adds these after the first four headline figures */
const STRIP_EXTRA = ["crime_1000"];
/* quick-pick indicator chips next to the indicator select; registry entries with `chip: true` follow */
const QUICK_KEYS = ["growth", "price_m2", "rent_private", "unemp", "renters", "supply"].concat(IND.filter(i => i.chip).map(i => i.key));
/* link into the chart generator with one area pre-selected */
const chartLink = (key, type, code) => `charts?ind=${encodeURIComponent(key)}&a=${type}:${code}&y0=&y1=&med=1`;
/* link into the one-property Analysis sheet */
/* the Test property route (spec §5.5′, amendment A3): one pin, `p=lat,lon[:label]`. `,` and `:` are
   legal in a fragment and are what makes the link readable, so only the label is percent-encoded. */
const propLink = items => "property?p=" + encodeURIComponent(RC.propSerialise(items)).replace(/%2C/g, ",").replace(/%3A/g, ":");
const analysisLink = (lat, lon, label) => propLink([{ lat, lon, label: label || "" }]);
/* value of indicator k for municipality/area o in the selected year (latest = live field, else history) */
const V = (o, k, y) => { if (isClim(k)) return climValue(o, k); const yr = y || MK.year; if (!o) return null; if (!yr || yr === LATEST) return o[k] ?? null; const h = o.hist && o.hist[k]; return h && h[yr] != null ? h[yr] : null; };
/* first year a year selector offers (registry `map_from`; Safety: 2008, the first full rolling year) — Charts go further back */
const mapFrom = k => String((IND.find(i => i.key === k) || {}).map_from || "");
const yearsForPool = (k, pool) => YEARS.filter(y => y >= mapFrom(k)).filter(y => y === LATEST || pool.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
/* years with actual history for charts and sparklines — the lagging "latest" value is not repeated as a later year */
const histYears = (k, pool) => YEARS.filter(y => pool.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
function curPool() { if (S.view === "area") { const e = areaEntity(); return e ? e.peers : MUNI; }
  if (S.view === "analysis") { const e = anEntity(); return e ? e.peers : MUNI; }
  if (S.view === "table" && T.level === "kvarter") return CPH ? CPH.areas : MUNI; return cphMode() ? CPH.areas : MUNI; }
const yearsFor = k => projOf(k) ? [] : yearsForPool(k, curPool());
/* the indicators on offer: the entity's own list wherever a view is about one area — the test
   property reads its pin's finest area (spec §5.5′), so a Copenhagen pin gets the quarter registry */
const curInds = () => { if (S.view === "area") { const e = areaEntity(); return e ? e.inds : IND; }
  if (S.view === "analysis") { const e = anEntity(); return e ? e.inds : IND; }
  if (S.view === "table") return T.level === "kvarter" ? IND_Q : IND; return cphMode() ? IND_Q : IND; };
const curInd = () => { const L = curInds(); return L.find(i => i.key === MK.ind) || L[0] || { key: "", label: "", fmt: "pct1" }; };

/* ---------- routing (hash) ---------- */
/* The v3.0 alias table lives in src/route_core.js (pure, unit-tested in tests/route.test.js) and is
   wired in at the two points that own the hash: hashFor() writes the v3 spelling, parseHash() reads
   either one. Live since P2: every v2.6 link is redirected once, by replaceState, to its v3 hash.
   The internal view ids (`table`, `pipeline`, `market`, `analysis`) are unchanged on purpose — only
   the hash spelling and the nav labels moved. */
const RC = window.ROUTE_CORE;
/* The shared IndicatorPicker / PeriodControl logic (src/picker_core.js, inlined above this file):
   group order, the search predicate, the period mode and the row tag. Declared here because
   GROUP_ORDER below is a top-level const that reads from it at script-eval time. */
const PC = (typeof window !== "undefined" && window.PICKER_CORE) || {};
/* `climate=1` (the deleted overlay) becomes the Climate indicator it was showing, and the three
   overlay flags become one `lay=` list — both in the alias table, never here (spec §4.4). */
const rcOpts = () => ({ isClim });
/* the new spelling of a hash the app just built */
const routeOut = h => RC.toV3(h, rcOpts());
/* `hz=` belongs to the Climate family (spec §3.2, §4.3): it is written only when the horizon is the
   period actually on screen — a Climate indicator (whose zones and figures share it), the climate
   sheet, or the test property's climate card. Leaving the family therefore drops the key, which is
   what "switching family resets hz" means in the URL. */
const hzParts = () => (isClim(MK.ind) || S.view === "climate" || S.view === "analysis")
  ? CC.hzSerialise(HZ.h) : [];
/* `show=` (spec §3.2): the open toggles of the area page, written only when they differ from the
   level's default — and `none` when the reader closed the one that opens itself. */
function arShowParts() {
  const def = arShowDefault().join(",");
  const cur = AR_SECS.filter(k => AR.show.has(k)).join(",");
  return cur === def ? "" : (cur || "none");
}
/* the same key on the test property (spec §5.5′): the eight sections, `none` when the reader
   closed the one that opens itself */
function anShowParts() {
  const def = anShowDefault().join(",");
  const cur = TP_SECS.filter(k => AN.show.has(k)).join(",");
  return cur === def ? "" : (cur || "none");
}
function hashFor() {
  const q = [`ind=${encodeURIComponent(MK.ind || "")}`]; if (MK.year && MK.year !== LATEST) q.push(`y=${MK.year}`);
  q.push(...hzParts());   /* one horizon for the zones and the Climate figures alike */
  if (S.view === "makro" && MK.micro) { q.push("micro=1"); q.push(`mind=${MK.mind}`); }
  /* one key for the feature layers (spec §4.4) — they survive every level change */
  if (S.view === "makro") { const lay = mapLayers(); if (lay.length) q.push(`lay=${lay.join(",")}`); }
  if ((S.view === "makro" && MK.pub) || S.view === "publist") q.push(...pubHashParts());
  if (S.view === "makro" && MK.srv) q.push(...srvHashParts());
  /* the Climate context layer is on by default whenever a Climate indicator is, so only "off" is written */
  if (S.view === "makro" && climZonesAvail() && !MK.zones) q.push("zones=0");
  if (S.view === "makro" && MK.focus) q.push(`focus=${encodeURIComponent(MK.focus)}`);
  /* the test-property pin rides along with the map hash so the link opens on the same spot */
  if (S.view === "makro" && TP.lat != null) { q.push(`pin=${TP.lat.toFixed(5)},${TP.lon.toFixed(5)}`); if (TP.label && TP.label !== TP_LABEL) q.push(`pl=${encodeURIComponent(TP.label)}`); if (TP.rad) q.push(`rad=${TP.rad}`); }
  let p;
  if (S.view === "area") { p = `area/${AR.type}/${AR.code}`; if (AR.sub !== "kvarter") q.push(`sub=${AR.sub}`); const sh = arShowParts(); if (sh) q.push(`show=${sh}`); }
  else if (S.view === "table") p = `table/${T.level}`;
  else if (S.view === "charts") { p = "charts"; q.length = 0; q.push(`ind=${encodeURIComponent(CH.ind)}`, `a=${CH.areas.join(",")}`, `y0=${CH.y0}`, `y1=${CH.y1}`, `med=${CH.median ? 1 : 0}`); if (CH.mode !== "auto") q.push(`mode=${CH.mode}`); if (CH.mode === "dist") q.push(`dist=${CH.dist}`);
    if (CH.fq === "q") q.push("fq=q"); if (CH.ov.length) q.push(`ov=${CH.ov.join(",")}`); if (!CH.nat) q.push("nat=0"); }
  else if (S.view === "analysis") { p = "analysis"; q.length = 0; if (AN.a) q.push(`a=${AN.a}`); if (AN.label) q.push(`la=${encodeURIComponent(AN.label)}`);
    /* the mini map rides in the link too: the headline tile that colours it, the overlays, the public filter */
    q.push(`ind=${encodeURIComponent(MK.ind || "")}`); if (MK.year && MK.year !== LATEST) q.push(`y=${MK.year}`);
    q.push(`lay=${anLayerList().join(",") || "none"}`); if (ANL.pub) q.push(...pubHashParts());
    q.push(...hzParts());
    if (AN.rad !== AN_RING_M) q.push(`rad=${AN.rad}`);
    const ash = anShowParts(); if (ash) q.push(`show=${ash}`); }
  else if (S.view === "market") { p = "market"; if (MKT.src) q.push("src=1"); }
  else if (S.view === "project") { p = `project/${PR.id}`; }
  else if (S.view === "climate") { p = `climate/${CS.code}`; }
  else if (S.view === "public") { p = `public/${PB.kom}/${PB.id}`; }
  else if (S.view === "publist") { p = `publist/${PL.key}`; }
  else if (S.view === "school") { p = `school/${SC.nr}`; }
  else if (S.view === "schoollist") { p = `schoollist/${SL.key}`; }
  else if (S.view === "pipeline") { p = "pipeline"; if (PIPE.type) q.push(`ptype=${PIPE.type}`); if (PIPE.status) q.push(`pstatus=${PIPE.status}`); }
  else if (S.view === "makro") p = "map" + (MK.muni ? "/" + MK.muni + (MK.muni === CPH_MUNI && MK.cphView === "postnr" ? "/postnr" : "") : "");
  else p = S.view;
  return routeOut(p + "?" + q.join("&"));
}
function parseHash() {
  /* either spelling in, one set of internal parts out: `data/projects` and `pipeline` are the same
     view, `property?p=…` and `analysis?a=…&la=…` the same pin. The address bar is corrected at the
     end of this function, from hashFor(), so a shared v2.6 link redirects exactly once. */
  const t = RC.toInternal((location.hash || "#map").slice(1), rcOpts());
  const parts = t.parts, q = t.query;
  const prevView = S.view;
  if (q.ind) MK.ind = q.ind;
  climParseHz(q);
  MK.year = q.y && YEARS.includes(q.y) ? q.y : LATEST;
  const v = parts[0] || "map";
  if (v === "area" && parts[1] && parts[2]) { S.view = "area"; AR.type = parts[1]; AR.code = parts[2]; AR.sub = q.sub || "kvarter";
    AR.show = new Set(q.show == null ? arShowDefault() : q.show === "none" ? [] : q.show.split(",").filter(k => AR_SECS.includes(k))); }
  else if (v === "table") { S.view = "table"; if (["kommune", "postnr", "kvarter"].includes(parts[1])) T.level = parts[1]; }
  else if (v === "market") { S.view = "market"; MKT.src = q.src === "1"; }
  else if (v === "project" && parts[1]) { S.view = "project"; PR.id = decodeURIComponent(parts[1]); }
  else if (v === "public" && parts[2]) { S.view = "public"; PB.kom = parts[1]; PB.id = decodeURIComponent(parts[2]); }
  else if (v === "publist" && parts[1]) { S.view = "publist"; PL.key = decodeURIComponent(parts.slice(1).join(":")); pubParseFilter(q); }
  else if (v === "school" && parts[1]) { S.view = "school"; SC.nr = decodeURIComponent(parts[1]); schoolsLoad(); }
  else if (v === "schoollist" && parts[1]) { S.view = "schoollist"; SL.key = decodeURIComponent(parts.slice(1).join(":")); schoolsLoad(); }
  else if (v === "pipeline") { S.view = "pipeline"; PIPE.type = q.ptype || ""; PIPE.status = q.pstatus || ""; }
  else if (v === "analysis") { S.view = "analysis"; AN.a = q.a || ""; AN.label = q.la || ""; anParseLayers(q); pubParseFilter(q);
    AN.rad = TP_RADII.includes(Number(q.rad)) && Number(q.rad) > 0 ? Number(q.rad) : AN_RING_M;
    AN.show = new Set(q.show == null ? anShowDefault() : q.show === "none" ? [] : q.show.split(",").filter(k => TP_SECS.includes(k)));
    /* the sheet cannot say which kommune the point is in until the rings are there — chain once, not on every hashchange */
    if (!KOM.list && !KOM.err) komLoad().then(() => { if (S.view === "analysis") renderKeep(); }); }
  else if (v === "climate" && parts[1]) { S.view = "climate"; CS.code = pad4(parts[1]); climSheetLoad();
    /* the zone files land asynchronously; the sheet is redrawn once, when they do */ }
  else if (v === "charts") { S.view = "charts"; CH.ind = q.ind || CH.ind; CH.areas = q.a ? q.a.split(",").filter(Boolean) : CH.areas; CH.y0 = q.y0 || CH.y0; CH.y1 = q.y1 || CH.y1; CH.median = q.med !== "0"; CH.mode = q.mode || "auto"; CH.dist = q.dist || "size";
    CH.fq = q.fq === "q" ? "q" : "year"; CH.ov = q.ov ? q.ov.split(",").filter(Boolean) : []; CH.nat = q.nat !== "0"; }
  else { S.view = "makro"; MK.muni = parts[1] && byCode[parts[1]] ? parts[1] : null;
         MK.cphView = parts[2] === "postnr" ? "postnr" : "kvarter";
         /* `cph.json` publishes no Climate indicator, so drilling into København in quarter mode
            used to swap the indicator — and with it the storm-surge zones — away (the P4
            limitation). The quarters are the wrong level for this figure, not the reader's
            mistake: show the postal codes, which do publish it. */
         if (MK.muni === CPH_MUNI && MK.cphView !== "postnr" && isClim(MK.ind) && !IND_Q.some(i => i.key === MK.ind)) MK.cphView = "postnr";
         MK.micro = q.micro === "1" && microAvail(MK.muni); if (q.mind && MICRO_INDS.some(i => i.key === q.mind)) MK.mind = q.mind;
         /* one key for the three feature layers; the v2.6 flags are converted by the alias table */
         const lay = new Set((q.lay || "").split(",").filter(Boolean));
         MK.infra = lay.has("infra"); MK.pub = lay.has("public"); MK.srv = lay.has("services");
         MK.zones = q.zones !== "0";
         pubParseFilter(q); srvParseFilter(q);
         MK.focus = q.focus || null; if (MK.focus) MK.infra = true; tpParse(q); }
  if (!curInds().some(i => i.key === MK.ind)) MK.ind = (curInds()[0] || {}).key;
  if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST;
  if (S.view === "makro") {
    /* zoom to a municipality the first time it is shown; back to the national frame when it is cleared */
    if (MK.muni && MK.muni !== LF.shownMuni) LF.pendingFit = MK.muni;
    if (!MK.muni && LF.shownMuni) { LF.center = [56.0, 10.5]; LF.zoom = 7; }
    LF.shownMuni = MK.muni;
  }
  /* the URL is the state. After parsing, the address bar shows exactly what hashFor() would write,
     so an old link redirects once and parse → serialise is idempotent for every route (AC-U1).
     replaceState never fires hashchange, so this cannot loop. */
  const want = hashFor();
  if (location.hash.slice(1) !== want) history.replaceState(null, "", "#" + want);
  return { viewChanged: prevView !== S.view };
}
function go(hash) { if ("#" + hash === location.hash) { parseHash(); render(); } else location.hash = hash; }
function syncHash() { history.replaceState(null, "", "#" + hashFor()); }
window.addEventListener("hashchange", () => {
  /* a navigation closes the Layers menu. It survives a re-render on purpose — ticking two layers
     should not need two trips to the button — but it has no business following the reader to
     another municipality or another view. */
  UI.layOpen = false;
  /* and so does the mini map's full screen: it is a way of reading one page, not a mode of the app */
  UI.mmFull = false;
  const r = parseHash(); render(); if (r.viewChanged) { const m = document.getElementById("main"); if (m) m.scrollTop = 0; } });

/* ---------- views & navigation ---------- */
/* Four destinations (spec §3.1 with owner amendment A1): Market · Pipeline · Compare are gone —
   the first two became Data tabs, Compare was deleted. The internal view ids are unchanged. */
const VIEWS = [
  ["makro",   "Map",           "Demographics, income, housing and prices by municipality, postal code and Copenhagen quarter", "map"],
  ["table",   "Data",          "Every area, every project, the national series and the sources — one tab each", "data/areas/kommune"],
  ["charts",  "Charts",        "Pick an indicator, areas and years — export the chart as PNG or the data as CSV", "charts"],
  ["analysis", "Test property", "Drop a pin from a Google Maps link and read every layer against it", "property"]];
const NAV_GROUPS = [["Market intelligence", ["makro", "table", "charts"]], ["Analysis", ["analysis"]]];
const viewOf = id => VIEWS.find(v => v[0] === id) || VIEWS[0];
/* the views that live inside the Data section, and the tab each one is */
const DATA_VIEWS = ["table", "pipeline", "market"];
const isData = () => DATA_VIEWS.includes(S.view);

function renderNav() {
  const on = ["area", "public", "publist", "school", "schoollist", "climate"].includes(S.view) ? "makro"
    : S.view === "project" ? "table" : isData() ? "table" : S.view;
  document.getElementById("nav").innerHTML = NAV_GROUPS.map(([lab, ids]) => `<div class="nav-glab">${lab}</div>` +
    ids.map(id => { const v = viewOf(id), h = id === "analysis" ? anNavLink() : id === "table" ? dataHash() : v[3];
      return `<button class="nav-item ${on === id ? "on" : ""}" data-testid="nav-item" data-go="${esc(h)}" title="${esc(v[2])}"><b>${v[1]}</b></button>`; }).join("")).join("");
}
/* ---------- the Data section: four tabs over three existing views (spec §5.3) ---------- */
const DATA_TABS = [["areas", "Areas", "every municipality, postal code and quarter"],
                   ["projects", "Projects", "the infrastructure pipeline"],
                   ["national", "National series", "Denmark-wide rates, prices and construction"],
                   ["sources", "Sources", "publisher, tables, as of, licence"]];
const dataTab = () => S.view === "pipeline" ? "projects" : S.view === "market" ? (MKT.src ? "sources" : "national") : "areas";
const dataTabHash = tab => tab === "areas" ? `data/areas/${T.level}` : `data/${tab}`;
const dataHash = () => dataTabHash(isData() ? dataTab() : "areas");
const dataTabLabel = tab => (DATA_TABS.find(t => t[0] === tab) || DATA_TABS[0])[1];
function dataTabs() {
  const cur = dataTab();
  return `<div class="dtabs" data-testid="data-tabs" role="tablist" aria-label="Data">${DATA_TABS.map(([id, lab, hint]) =>
    `<button class="dtab ${cur === id ? "on" : ""}" role="tab" aria-selected="${cur === id}" data-testid="data-tab" data-go="${esc(dataTabHash(id))}" title="${esc(hint)}">${esc(lab)}</button>`).join("")}</div>`;
}

/* "<level>:<code>[:…]" — a public-building or school list key — → the municipality it belongs to */
function crumbMuni(key) {
  const [level, code] = String(key || "").split(":");
  const kom = level === "kommune" ? code : level === "postnr" ? (byNr[code] || {}).muni : CPH_MUNI;
  return byCode[String(Number(kom || 0))] || null;
}
/* the top bar is a breadcrumb: Denmark › municipality › area — every step is a link, the last one is where you are */
function crumbs() {
  const q = `?ind=${encodeURIComponent(MK.ind)}` + (MK.year !== LATEST ? `&y=${MK.year}` : "");
  const c = [["Denmark", "map" + q]]; let tail = "", kind = "";
  if (S.view === "area") { const e = areaEntity(); if (!e) return { c, tail: "Area", kind: "" };
    if (e.muni) c.push([e.muni.name, `area/kommune/${e.muni.code}` + q]); if (e.bydel) c.push([e.bydel, `map/${CPH_MUNI}` + q]); tail = e.name; kind = e.typeLabel; }
  else if (S.view === "makro") { const m = MK.muni ? byCode[MK.muni] : null;
    if (m) { if (microMode()) { c.push([m.name, `map/${m.code}` + q]); tail = "Buildings"; kind = "BBR register"; } else { tail = m.name; kind = cphMode() ? "quarters" : "postal codes"; } }
    else { tail = "Map"; kind = "municipalities and postal codes"; } }
  else if (S.view === "project") { const f = projectEntity(); c.push(["Data", "data/areas/" + T.level], ["Projects", "data/projects"]);
    tail = f ? f.properties.name : "Project"; kind = f ? (INFRA_TYPE[f.properties.type] || f.properties.type) : ""; }
  else if (S.view === "school") { const s = SCH_BY[SC.nr]; if (s && byCode[s.kom]) c.push([s.kommune, `area/kommune/${s.kom}` + q]); tail = s ? s.name : "School"; kind = s ? (SCH_TYPE[s.type] || s.type) : "Uddannelsesstatistik.dk"; }
  else if (S.view === "schoollist") { const m = crumbMuni(SL.key); if (m) c.push([m.name, `area/kommune/${m.code}` + q]); tail = "Schools"; kind = "sorted by FP9 grade"; }
  /* a sheet you arrived at from content: the breadcrumb names the municipality it is in, never the
     view you happened to come from (AC-SH3 — v2.6 showed "Macro map" here) */
  else if (S.view === "public") { const b = pubFind(PB.kom, PB.id), m = byCode[String(Number(PB.kom))];
    if (m) c.push([m.name, `area/kommune/${m.code}` + q]);
    tail = b ? pubName(b) : "Public building"; kind = b ? `${pubCat(b).label} · BBR ${b.code}` : "BBR via Datafordeler"; }
  else if (S.view === "publist") { const m = crumbMuni(PL.key); if (m) c.push([m.name, `area/kommune/${m.code}` + q]);
    tail = "Public buildings"; kind = "BBR via Datafordeler"; }
  else if (S.view === "analysis") { tail = AN.label || TP_LABEL; kind = "test property"; }
  else if (S.view === "climate") { const m = byCode[String(Number(CS.code || 0))];
    if (m) c.push([m.name, `area/kommune/${m.code}` + q]); tail = "Climate risk"; kind = "Kystdirektoratet · DMI Klimaatlas"; }
  else if (isData()) { const tab = dataTab(); c.push(["Data", "data/areas/" + T.level]); tail = dataTabLabel(tab);
    kind = { areas: `${tableRows().length} rows · ${T.level === "kvarter" ? "Copenhagen quarters" : T.level === "postnr" ? "postal codes" : "municipalities"}`,
             projects: `${INFRA_ALL.length} projects · budget, status, opening year`,
             national: "latest available period per series", sources: `built ${(D.meta && D.meta.built) || "–"}` }[tab] || ""; }
  else { tail = viewOf(S.view)[1]; kind = { charts: "PNG and CSV export" }[S.view] || ""; }
  return { c, tail, kind };
}
/* page-level actions, on the right of the top bar. Full screen belongs to the page, not to the map
   toolbar (spec §5.1) — which is also what brings the toolbar down to one row. The Data section and
   the test property carry the Export ▾ menu here (spec §4.9); the sidebar footer has the same one. */
function pageActions() {
  if (S.view === "makro") return `<button class="lk" data-fs data-testid="map-full" title="Full screen (Esc to exit)">${document.fullscreenElement ? "⤡ Exit full screen" : "⤢ Full screen"}</button>`;
  if (isData() || S.view === "analysis") return exportMenu("page");
  return "";
}
function renderTop() {
  const { c, tail, kind } = crumbs();
  const act = pageActions();
  document.getElementById("hd").innerHTML = `<nav class="crumbs" aria-label="Breadcrumb">${c.map(([l, h]) => `<button data-go="${esc(h)}">${esc(l)}</button><i aria-hidden="true">›</i>`).join("")}<b>${esc(tail)}</b>${kind ? `<span class="dim">${esc(kind)}</span>` : ""}</nav>${act ? `<div class="hd-act">${act}</div>` : ""}`;
  /* the 52 px mobile bar names the view, so "where am I" survives the sidebar being a drawer (§4.1) */
  const mv = document.getElementById("mview");
  if (mv) mv.textContent = viewOf(S.view === "area" || S.view === "public" || S.view === "publist"
    || S.view === "school" || S.view === "schoollist" || S.view === "climate" ? "makro"
    : S.view === "project" || isData() ? "table" : S.view)[1];
}

/* ---------- the ≤1024 px navigation drawer (spec §4.1, AC-S2) ----------
   One element is the sidebar and the drawer's panel: `.drawer` is `display:contents` on desktop, so
   <aside> is still the grid's first column, and a fixed off-canvas panel below 1025 px. Closed it is
   `visibility:hidden`, which is what keeps the sidebar out of the accessibility tree and out of the
   tab order on a phone (AC-S1 asserts it is not visible). Focus is trapped while it is open and
   handed back to ☰ on close. */
const NAVD = { open: false, from: null };
const navDrawerEl = () => document.getElementById("navdrawer");
function navFocusables() {
  const d = navDrawerEl(); if (!d) return [];
  return [...d.querySelectorAll("button:not([disabled]):not([tabindex='-1']),a[href],input,select")]
    .filter(el => el.offsetParent !== null || el === document.activeElement);
}
function navDrawer(open) {
  const d = navDrawerEl(), t = document.getElementById("navtog");
  if (!d || !t) return;
  NAVD.open = !!open;
  d.classList.toggle("open", NAVD.open);
  t.setAttribute("aria-expanded", NAVD.open ? "true" : "false");
  t.setAttribute("aria-label", NAVD.open ? "Close the navigation" : "Open the navigation");
  document.body.classList.toggle("nav-open", NAVD.open);
  if (NAVD.open) { NAVD.from = t; const f = navFocusables(); if (f[0]) f[0].focus(); }
  else if (NAVD.from) { const el = NAVD.from; NAVD.from = null; if (el.isConnected) el.focus(); }
}
const RENDER = { makro: vMakro, table: vTable, area: vArea, charts: vCharts, market: vMarket, pipeline: vPipeline, project: vProject,
                 public: vPublic, publist: vPubList, school: vSchool, schoollist: vSchoolList, analysis: vAnalysis,
                 climate: vClimate };
function render() {
  /* every live map goes before the DOM it lives in does — see dropMap() */
  dropMaps();
  /* a navigation closes the drawer, however it was triggered (a nav item, the back button, a link
     inside the page) — an open drawer over a page the reader has already left is a trap */
  if (NAVD.open) navDrawer(false);
  renderNav(); renderTop(); renderFoot();
  const body = document.getElementById("body");
  body.innerHTML = (RENDER[S.view] || vMakro)();
  enableSort(body);
}
function renderKeep() { const m = document.getElementById("main"), y = m.scrollTop; render(); m.scrollTop = y; }

document.addEventListener("click", e => {
  const g = sel => e.target.closest(sel);
  let el;
  if (g("[data-nav-toggle]")) { navDrawer(!NAVD.open); return; }
  if (g("[data-nav-close]")) { navDrawer(false); return; }
  /* §6: the legend pill folds the whole stack away on a phone. In place — a re-render would
     rebuild the map underneath it. */
  if ((el = g("[data-legtog]"))) { UI.legOpen = !UI.legOpen;
    const w = document.getElementById("maplegs");
    if (w) w.classList.toggle("open", UI.legOpen);
    el.setAttribute("aria-expanded", UI.legOpen ? "true" : "false");
    el.textContent = "Legend " + (UI.legOpen ? "▴" : "▾");
    lgFitSoon(); return; }
  if ((el = g("[data-go]"))) { if (NAVD.open) navDrawer(false); go(el.dataset.go); return; }
  if ((el = g("[data-tlevel]"))) { T.level = el.dataset.tlevel; if (!curInds().some(i => i.key === MK.ind)) MK.ind = curInds()[0].key; syncHash(); renderKeep(); return; }
  /* Export ▾ (spec §4.9): one menu, two triggers, one handler for every item in it */
  if ((el = g("[data-xpop]"))) { const w = el.closest(".xwrap"); xPopOpen(UI.xOpen === w.dataset.xat ? "" : w.dataset.xat, true); return; }
  if ((el = g("[data-export]"))) { exportGo(el.dataset.export); return; }
  if (g("[data-testid=export-menu]")) return;      /* a click inside the menu must not close it */
  if (g("[data-csv]")) { exportGo("view"); return; }
  if (g("[data-csv-pipe]")) { exportGo("projects"); return; }
  if (g("[data-back]")) { history.back(); return; }
  if ((el = g("[data-ancopy]"))) { tpAction("copy", el); return; }
  if ((el = g("[data-pipe]"))) { const f = INFRA_BY[el.dataset.pipe];
    go(f && f.properties.map !== false ? `map?ind=${encodeURIComponent(MK.ind)}&infra=1&focus=${encodeURIComponent(el.dataset.pipe)}` : `project/${el.dataset.pipe}`); return; }
  if ((el = g("[data-project]"))) { go(`project/${el.dataset.project}`); return; }
  if (g("[data-mkown]")) { MK.own = !MK.own; renderKeep(); return; }
  if ((el = g("[data-cphview]"))) { MK.cphView = el.dataset.cphview; go(hashFor()); return; }
  if (g("[data-fs]")) { toggleFullscreen(); return; }
  if ((el = g("[data-chmode]"))) { CH.mode = el.dataset.chmode; syncHash(); renderKeep(); return; }
  if ((el = g("[data-chfq]"))) { CH.fq = el.dataset.chfq; syncHash(); renderKeep(); return; }
  if ((el = g("[data-chov]"))) { const k = el.dataset.chov; CH.ov = CH.ov.includes(k) ? CH.ov.filter(x => x !== k) : CH.ov.concat(k); syncHash(); renderKeep(); return; }
  if ((el = g("[data-chadd]"))) { chartAddMany(el.dataset.chadd.split("|")); return; }
  if ((el = g("[data-chrm]"))) { CH.areas = CH.areas.filter(a => a !== el.dataset.chrm); syncHash(); renderKeep(); return; }
  if (g("[data-chpng]")) { chartPng(); return; }
  if (g("[data-chcsv]")) { chartCsv(); return; }
  if (g("[data-chclear]")) { CH.areas = []; syncHash(); renderKeep(); return; }
  if ((el = g("[data-mapjump]"))) { mapJump(el.dataset.mapjump); return; }
  if ((el = g("[data-tprad]"))) { TP.rad = TP_RADII.includes(Number(el.dataset.tprad)) ? Number(el.dataset.tprad) : 0;
    tpRadApply(); return; }
  if ((el = g("[data-micro]"))) { MK.micro = el.dataset.micro === "1"; syncHash(); renderKeep(); return; }
  /* Layers ▾ (spec §4.4): one button, one popover, one handler for every row in it */
  if (g("[data-laypop]")) { layPopOpen(!UI.layOpen, true); return; }
  if ((el = g("[data-layer]"))) { mapLayerToggle(el.dataset.layer); return; }
  /* the test property's paste box: Go does what Enter in the box does */
  if (g("[data-tpgo]")) { const q = document.getElementById("tpq"); if (q) tpGo(q.value); return; }
  if ((el = g("[data-hz]"))) { climSetHz(el.dataset.hz); return; }
  if ((el = g("[data-legfold]"))) { lgFold(el); return; }
  if ((el = g("[data-srvcat]"))) { const k = el.dataset.srvcat;
    if (e.shiftKey) { srvSetFilter(new Set([k])); return; }
    const cur = new Set(SF.cats); cur.has(k) ? cur.delete(k) : cur.add(k);
    srvSetFilter(cur); return; }
  if ((el = g("[data-srvmode]"))) { const k = el.dataset.srvmode;
    const cur = new Set(SF.tmodes); cur.has(k) ? cur.delete(k) : cur.add(k);
    /* the Transport chip follows its two sub-toggles: both off means the category is off */
    const cats = new Set(SF.cats); cur.size ? cats.add("transport") : cats.delete("transport");
    srvSetFilter(cats, cur); return; }
  if (g("[data-srvall]")) { srvSetFilter(new Set(Object.keys(SRV_CAT)), new Set(["rail", "bus"])); return; }
  if (g("[data-puball]")) { pubSetFilter({ cats: null, kind: "both" }); return; }
  if ((el = g("[data-pubcat]"))) { const k = el.dataset.pubcat;
    if (e.shiftKey) { pubSetFilter({ cats: new Set([k]) }); return; }
    const cur = PF.cats ? new Set(PF.cats) : new Set(Object.keys(PUB_CAT));
    cur.has(k) ? cur.delete(k) : cur.add(k);
    pubSetFilter({ cats: cur.size === Object.keys(PUB_CAT).length ? null : cur }); return; }
  if ((el = g("[data-pubkind]"))) { const k = el.dataset.pubkind;
    pubSetFilter({ kind: PF.kind === k ? "both" : k }); return; }
  if ((el = g("[data-publist]"))) {
    const f = el.dataset.pubfilter;      /* the card segments set the same filter the legend uses */
    if (f) { const [c, k] = f.split(":"); PF.cats = c ? new Set([c]) : null; PF.kind = k === "case" ? "open" : k === "existing" ? "existing" : "both"; }
    go(`publist/${el.dataset.publist}`); return; }
  if ((el = g("[data-school]"))) { go(`school/${encodeURIComponent(el.dataset.school)}`); return; }
  if ((el = g("[data-schoollist]"))) { go(`schoollist/${el.dataset.schoollist}`); return; }
  if ((el = g("[data-pubsheet]"))) { const row = el.closest("[data-pubkom]"); go(`public/${(row && row.dataset.pubkom) || (MK.muni || CPH_MUNI)}/${el.dataset.pubsheet}`); return; }
  if (g("[data-mcsv]")) { exportMicroCsv(); return; }
  /* Quarters ⇄ Postal codes in the sub-area table: a different set of areas, so the map refits */
  if ((el = g("[data-arsub]"))) { AR.sub = el.dataset.arsub; syncHash(); if (!areaRefresh({ fit: true })) renderKeep(); return; }
  if (g("[data-mmfull]")) { mmFull(); return; }
  /* the shared IndicatorPicker: the button toggles its popover, every row and every chip is a pick */
  if (g("[data-indpop]")) { const w = indPopEl(); indPopOpen(!(w && w.classList.contains("open")), true); return; }
  if ((el = g("[data-ind]"))) { pickInd(el.dataset.ind, pickTargetOf(el)); return; }
  if (g("[data-testid=ind-picker-pop]")) return;   /* a click inside the popover must not close it */
  if (g("[data-testid=layers-pop]") || g(".asrch")) return;   /* nor inside the Layers menu or the search box */
  if (g("[data-mftoggle]")) { UI.mfOpen = !UI.mfOpen; const p = document.getElementById("mfpanel"), b = g("[data-mftoggle]"); if (p) p.style.display = UI.mfOpen ? "" : "none"; if (b) b.classList.toggle("on", UI.mfOpen); return; }
  if ((el = g(".im"))) { tipToggle(el); return; }
  tipHide();
  /* a click anywhere else closes every popover, the way every other popover on the page behaves */
  const pk = indPopEl(); if (pk && pk.classList.contains("open")) indPopOpen(false, false);
  if (UI.layOpen) layPopOpen(false, false);
  if (UI.xOpen) xPopOpen("", false);
  asrchOpen(false);
});
document.addEventListener("change", e => {
  const el = e.target;
  if (el.id === "yearsel") { MK.year = el.value; syncHash(); if (!areaRefresh() && !tpRefresh()) renderKeep(); }
  /* the test property's radius: it draws a different ring and counts inside a different one, but
     the map itself does not move — so the page is updated in place, never rebuilt */
  if (el.id === "tpradsel") { AN.rad = TP_RADII.includes(Number(el.value)) ? Number(el.value) : AN_RING_M; syncHash(); if (!tpRefresh()) renderKeep(); }
  if (el.id === "mindsel") { MK.mind = el.value; syncHash(); renderKeep(); }
  if (el.id === "chnat") { CH.nat = el.checked; syncHash(); renderKeep(); }
  if (el.id === "chy0") { CH.y0 = el.value; syncHash(); renderKeep(); }
  if (el.id === "chy1") { CH.y1 = el.value; syncHash(); renderKeep(); }
  if (el.id === "chmed") { CH.median = el.checked; syncHash(); renderKeep(); }
  if (el.id === "chdist") { CH.dist = el.value; syncHash(); renderKeep(); }
  if (el.id === "chq") { chartAdd(null, el.value); }
  if (el.id === "chtitle") { CH.title = el.value; const t = document.getElementById("chsvgtitle"); if (t) t.textContent = CH.title || chartAutoTitle(); }
  if (el.id === "mf-type") { MF.type = el.value; lfLayers(); mfBtn(); }
  if (["mf-mindw", "mf-yfrom", "mf-yto", "mf-rent"].includes(el.id)) { MF.minDw = Number(document.getElementById("mf-mindw").value) || 1; MF.yFrom = document.getElementById("mf-yfrom").value; MF.yTo = document.getElementById("mf-yto").value; MF.rentMin = Number(document.getElementById("mf-rent").value) || 0; lfLayers(); mfBtn(); }
  if (el.id === "pptype") { PIPE.type = el.value; syncHash(); renderKeep(); }
  if (el.id === "ppstatus") { PIPE.status = el.value; syncHash(); renderKeep(); }
  if (el.id === "tregion") { T.region = el.value; renderTableBody(); }
  if (el.id === "tminpop") { T.minPop = Number(el.value) || 0; renderTableBody(); }
});
/* pasting is the normal way in: act on the pasted text straight away, no Enter needed */
document.addEventListener("paste", e => {
  if (!e.target || e.target.id !== "tpq") return;
  const t = ((e.clipboardData || window.clipboardData) || { getData: () => "" }).getData("text");
  if (!t) return;
  e.preventDefault(); e.target.value = t.trim(); tpGo(t);
});
document.addEventListener("input", e => {
  if (e.target.id === "tq") { T.q = e.target.value.trim().toLowerCase(); renderTableBody(); }
  if (e.target.id === "indsearch") indPickFilter(e.target.value);
  if (e.target.id === "areaq") asrchRender(e.target.value);
  if (e.target.id === "anlab") { AN.label = e.target.value.trim(); TP.label = AN.label || TP_LABEL; syncHash(); }
});
document.addEventListener("toggle", e => {
  if (!e.target.classList) return;
  if (e.target.classList.contains("indx")) UI.indxOpen = e.target.open;
  if (e.target.hasAttribute && e.target.hasAttribute("data-mstrip")) { mstripSet(e.target.open); if (LF.map) setTimeout(() => LF.map && LF.map.invalidateSize(), 60); }
  /* the area page's four toggles: the open set is in the URL, so a presenter can share either state */
  if (e.target.hasAttribute && e.target.hasAttribute("data-sec")) {
    const k = e.target.dataset.sec, open = e.target.open;
    /* a browser that fires `toggle` for a <details open> it has just parsed is reporting the state
       AR.show already holds — that is areaRefresh() rebuilding the sections, not a reader clicking */
    if (AR.show.has(k) === open) return;
    if (open) AR.show.add(k); else AR.show.delete(k);
    syncHash();
    /* opening All figures brings the row the panel above is showing into view (spec §5.2) */
    if (k === "figures" && open) {
      const row = e.target.querySelector("tr.on");
      if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
    }
  }
  /* the test property's eight sections, the same rule on its own key (spec §5.5′) */
  if (e.target.hasAttribute && e.target.hasAttribute("data-tpsec")) {
    const k = e.target.dataset.tpsec, open = e.target.open;
    if (AN.show.has(k) === open) return;
    if (open) AN.show.add(k); else AN.show.delete(k);
    syncHash();
  }
}, true);
/* the search dropdown opens on focus: the "Jump to" row at its top replaced two toolbar buttons and
   has to be reachable without typing (spec §5.1) */
document.addEventListener("focusin", e => { if (e.target && e.target.id === "areaq") asrchRender(e.target.value); });
/* …and leaving it closes the list again. The rows are `tabindex=-1` (they are a listbox, driven by
   ↑ ↓), so a Tab out of the box would otherwise leave the results standing over the toolbar. A
   click on a row focuses that row, which is inside the wrapper, so this never eats the click. */
document.addEventListener("focusout", e => {
  if (!e.target || e.target.id !== "areaq") return;
  setTimeout(() => { const w = asrchEl(); if (w && !w.contains(document.activeElement)) asrchOpen(false); }, 0);
});
document.addEventListener("keydown", e => {
  /* the drawer is modal (spec §4.1): Esc closes it and hands focus back to ☰, Tab cycles inside it */
  if (NAVD.open) {
    if (e.key === "Escape") { e.preventDefault(); navDrawer(false); return; }
    if (e.key === "Tab") {
      const f = navFocusables(); if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !navDrawerEl().contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      return;
    }
  }
  /* the picker's keyboard model (spec §4.2): ↑ ↓ move the active row, Enter takes it, Esc closes and
     hands focus back to the button. Handled before anything else so Esc never reaches the page. */
  const pk = indPopEl();
  if (pk && pk.classList.contains("open")) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); indPickMove(e.key === "ArrowDown" ? 1 : -1); return; }
    if (e.key === "Enter") { e.preventDefault(); const r = pk.querySelector(".indrow.act") || indPickRows()[0];
      if (r) pickInd(r.dataset.ind, pk.dataset.target); return; }
    if (e.key === "Escape") { e.preventDefault(); indPopOpen(false, true); return; }
  }
  if (e.key === "Escape" && UI.layOpen) { e.preventDefault(); layPopOpen(false, true); return; }
  if (e.key === "Escape" && UI.xOpen) { e.preventDefault(); xPopOpen("", true); return; }
  /* Esc leaves the mini map's full screen before it can mean "back" (spec §4.6, §7) */
  if (e.key === "Escape" && UI.mmFull) { e.preventDefault(); mmFull(false); return; }
  /* the unified search (spec §5.1): ↑ ↓ move the highlighted result, Enter takes it — the first one
     when nothing is highlighted, so a typed postal code still needs one key. Esc closes the list. */
  if (e.target.id === "areaq") {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); asrchOpen(true); asrchMove(e.key === "ArrowDown" ? 1 : -1); return; }
    if (e.key === "Enter") { e.preventDefault(); asrchEnter(e.target.value); return; }
    if (e.key === "Escape") { e.preventDefault(); asrchOpen(false); return; }
  }
  if (e.key === "Enter" && e.target.id === "chq") { chartAdd(null, e.target.value); return; }
  if (e.key === "Enter" && e.target.id === "mf-addr") { microFind(e.target.value); return; }
  if (e.key === "Enter" && e.target.id === "tpq") { tpGo(e.target.value); return; }
  if (e.key === "Escape" && S.view === "area") history.back();
  /* C / D jump the map view. Never while typing, and never with a modifier held, so they
     cannot shadow a browser shortcut or eat a character in the search box. */
  if (S.view !== "makro" || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
  const k = (e.key || "").toLowerCase();
  if (k === "c") mapJump("cph");
  else if (k === "d") mapJump("dk");
});

/* ---------- info tooltips (ⓘ) ---------- */
let TIPEL = null, TIPFOR = null;
function tipToggle(el) { if (TIPFOR === el) { tipHide(); return; } tipShow(el); }
function tipShow(el) {
  const i = IND.concat(IND_CPH).find(x => x.key === el.dataset.m); if (!i) return;
  if (!TIPEL) { TIPEL = document.createElement("div"); TIPEL.className = "imtip"; document.body.appendChild(TIPEL); }
  TIPEL.innerHTML = `<b>${esc(i.label)}</b>${lowerBetter(i.key) ? `<p class="dim">↓ lower is better</p>` : ""}${i.proj ? `<p class="dim">Projection ${esc(i.proj.from)}→${esc(i.proj.to)} · ${esc(i.proj.publisher)} ${esc(i.proj.vintage)} — not a measurement</p>` : ""}<p><em>Definition</em>${esc(i.desc || "")}</p>` + (i.source ? `<p><em>Source</em>${esc(i.source)}</p>` : "") +
    (i.note ? `<p><em>Note</em>${esc(i.note)}</p>` : "") + (i.warn ? `<p class="warn"><em>Caveat</em>${esc(i.warn)}</p>` : "");
  TIPEL.style.visibility = "hidden"; TIPEL.style.display = "block";
  const r = el.getBoundingClientRect(), t = TIPEL.getBoundingClientRect();
  let x = Math.max(8, Math.min(r.left + r.width / 2 - t.width / 2, window.innerWidth - t.width - 8));
  let y = r.bottom + 8; if (y + t.height > window.innerHeight - 8) y = Math.max(8, r.top - t.height - 8);
  TIPEL.style.left = x + "px"; TIPEL.style.top = y + "px"; TIPEL.style.visibility = "visible"; TIPFOR = el;
}
function tipHide() { if (TIPEL) TIPEL.style.display = "none"; TIPFOR = null; }

/* ---------- sortable tables ---------- */
function enableSort(root) {
  root.querySelectorAll("table[data-sortable]").forEach(tbl => {
    tbl.querySelectorAll("thead th").forEach((th, idx) => {
      if (th.hasAttribute("data-nosort")) return;   /* a sparkline or a link column has no order */
      th.classList.add("sth"); th.style.cursor = "pointer";
      th.addEventListener("click", () => {
        const tb = tbl.tBodies[0], rows = Array.from(tb.rows);
        /* the first click on an indicator column puts the best value on top (data-best), later clicks toggle */
        const dir = th.dataset.dir ? (th.dataset.dir === "asc" ? -1 : 1) : (th.dataset.best === "desc" ? -1 : 1); th.dataset.dir = dir === 1 ? "asc" : "desc";
        const val = r => { const c = r.cells[idx]; if (!c) return null; const v = parseFloat((c.dataset.v ?? c.textContent).replace(/\s/g, "").replace(",", ".")); return isNaN(v) ? null : v; };
        rows.sort((a, b) => { const x = val(a), y = val(b); if (x == null && y == null) return (a.cells[idx] ? a.cells[idx].textContent : "").localeCompare(b.cells[idx] ? b.cells[idx].textContent : ""); if (x == null) return 1; if (y == null) return -1; return (x - y) * dir; });
        rows.forEach(r => tb.appendChild(r));
      });
    });
  });
}

/* ---------- choropleth colour model (identical to the Finnish edition) ---------- */
const PAPER = [232, 237, 231];
const rampTo = (hue, s, k) => { const c = PAPER.map((x, j) => Math.round((x + (hue[j] - x) * s) * k)); return `rgb(${c[0]},${c[1]},${c[2]})`; };
/* Spec §2.1/§2.4: observed figures ramp green, Climate blue (already so in the registry) and the
   Outlook family purple — a projection must never be mistaken for an actual (AC-M4). The Outlook
   indicators are all diverging, so the family needs two hues: violet for the growing side, plum for
   the shrinking one. Both read as projection and the sign of the change stays legible. */
const RAMP_GROUP = { Outlook: { pos: [91, 74, 156], neg: [147, 63, 115] } };
function mkShade(t, key) {
  /* five steps from a light tint to the full hue, the top class deeper still — differences read at a glance */
  const i = key.startsWith("micro:") ? MICRO_INDS.find(x => x.key === key.slice(6)) : IND.concat(IND_CPH).find(x => x.key === key);
  const g = i && RAMP_GROUP[i.group];
  /* diverging (Outlook): hue_neg → paper → hue_pos about the centre. t is 0…1 with .5 at the centre,
     so the same distance either side gets the same strength in the two hues. `hue` stays equal to
     hue_pos, so a caller that does not know about `scale` still gets a plausible sequential ramp. */
  if (i && i.scale === "diverging") {
    const side = t < .5 ? (g ? g.neg : i.hue_neg || [166, 42, 22]) : (g ? g.pos : i.hue_pos || i.hue || [10, 88, 70]);
    const d = Math.min(1, Math.abs(t - .5) * 2);
    return rampTo(side, 0.08 + 0.92 * Math.pow(d, .9), d >= .99 ? .78 : 1);
  }
  const hue = (g && g.pos) || (i && i.hue) || [10, 88, 70];
  return rampTo(hue, 0.1 + 0.9 * Math.pow(Math.max(0, Math.min(1, t)), .9), t >= .99 ? .72 : 1);
}
/* quintile classes: each colour step holds a fifth of the areas, so a few outliers cannot flatten the map */
/* Diverging scale: breaks mirrored about `center`, so the same shade means the same magnitude on
   either side and the zero crossing is a class edge rather than the middle of a class. The three
   magnitudes are quantiles of |v − centre|, which is also the clamp: fc_abs runs from −4 617 to
   +52 670, and on a linear symmetric ramp every municipality but one would sit in the middle class. */
function divergingScale(vals, center) {
  const dev = vals.map(v => Math.abs(v - center)).sort((a, b) => a - b).filter(d => d > 0);
  if (!dev.length) return null;
  const dq = p => dev[Math.min(dev.length - 1, Math.floor(p * dev.length))];
  const mags = [dq(.34), dq(.67), dq(.90)].filter((m, i, a) => m > 0 && (i === 0 || m > a[i - 1]));
  if (!mags.length) return null;
  const breaks = mags.slice().reverse().map(m => center - m).concat(mags.map(m => center + m));
  const n = breaks.length + 1;
  const t = v => { if (v == null || isNaN(v)) return null; let c = 0; while (c < breaks.length && v > breaks[c]) c++; return c / (n - 1); };
  return { t, lo: vals[0], hi: vals[vals.length - 1], breaks, classes: n, n: vals.length, center, diverging: true,
           clamped: dev[dev.length - 1] > mags[mags.length - 1] };
}
function scaleOf(list, vk, fixed, ind) {
  const vals = list.map(vk).filter(v => v != null && !isNaN(v)).sort((a, b) => a - b);
  if (!vals.length) return { t: () => null, lo: null, hi: null, breaks: [] };
  if (ind && ind.scale === "diverging") {
    const d = divergingScale(vals, ind.center || 0);
    if (d) return d;
  }
  const q = p => vals[Math.min(vals.length - 1, Math.floor(p * vals.length))];
  /* fixed breaks where the scale has a natural meaning (shares of a building); otherwise quintiles —
     repeated quantiles (many identical values) collapse into fewer, non-empty classes */
  const breaks = (fixed || [q(.2), q(.4), q(.6), q(.8)]).filter((b, i, a) => (i === 0 || b > a[i - 1]) && b < vals[vals.length - 1]);
  const n = breaks.length + 1;
  const t = v => { if (v == null || isNaN(v)) return null; let c = 0; while (c < breaks.length && v > breaks[c]) c++; return n > 1 ? c / (n - 1) : .5; };
  return { t, lo: vals[0], hi: vals[vals.length - 1], breaks, classes: n, n: vals.length };
}
function legendHtml(sc, ind, key, note) {
  /* class-break legend drawn on top of the map (bottom right) */
  const f = fmtTight(ind); const b = sc.breaks || []; const n = sc.classes || 0;
  const lab = c => n === 1 ? f(sc.lo) : c === 0 ? `≤ ${f(b[0])}` : c === n - 1 ? `> ${f(b[c - 1])}` : `${f(b[c - 1])} – ${f(b[c])}`;
  const rows = []; for (let c = n - 1; c >= 0; c--) {
    /* the centre class of a diverging scale is marked, so the zero line is visible as a boundary
       rather than read off the numbers */
    const mid = sc.diverging && c === (n - 1) / 2;
    rows.push(`<div class="lgrow${mid ? " lgmid" : ""}"><i style="background:${mkShade(n > 1 ? c / (n - 1) : .5, key)}"></i>${lab(c)}${mid ? `<em class="lgctr">${f(sc.center || 0)}</em>` : ""}</div>`);
  }
  return `<div class="lgtitle">${esc(ind.short || ind.label)}<span>${esc(ind.unit || "")}</span></div>` +
    (n ? rows.join("") : `<div class="lgrow dim">no data</div>`) +
    `<div class="lgrow"><i style="background:#C4CBC4"></i>no data</div>` +
    /* same ramp for every direction: darkest = highest value, which is the worst end when lower is better */
    (lowerBetter(ind.key || "") ? `<div class="lgnote">↓ lower is better · darkest = highest</div>` : "") +
    /* an Outlook legend says what it is and whose projection it is, in place of a good/bad note */
    (neutralDir(ind.key || "") && ind.proj ? `<div class="lgnote">${esc(projLegendNote(ind))}</div>` : "") +
    (sc.diverging && sc.clamped ? `<div class="lgnote dim">top and bottom classes are open-ended</div>` : "") +
    `${note ? `<div class="lgnote">${note}</div>` : ""}`;
}
function setLegend(id, sc, ind, key, note) { const el = document.getElementById(id); if (el) el.innerHTML = legendHtml(sc, ind, key, note); setInfraLegend(); setPublicLegend(); setServicesLegend(); setClimateLegend(); lgFitSoon(); }
function setInfraLegend() {
  const el = document.getElementById("infralegend"); if (!el) return;
  const live = !!(MK.infra && INFRA.length);
  el.style.display = live ? "" : "none";
  el.innerHTML = live ? infraLegendHtml(INFRA.length) : "";
  lgApplyFold(el);
  lgFitSoon();
}
/* the one group order, defined once in src/picker_core.js and unit-tested there */
const GROUP_ORDER = PC.GROUP_ORDER;
/* "label · unit" for selects, leaving out unit parts the label already says ("Reported crime · per 1,000 inh." + "rolling 4Q") */
function optLabel(i) {
  const parts = (i.unit || "").split(" · ").filter(u => u && !i.label.includes(u) && !i.label.endsWith("· " + u.split(" ")[0]));
  return i.label + (parts.length ? " · " + parts.join(" · ") : "");
}

/* ---------- IndicatorPicker · chips · PeriodControl (spec §4.2, §4.3) ----------
   ONE picker for every view that chooses an indicator (spec §1 decision 2, amendment A4). The only
   thing that differs between call sites is `target`: which state the pick writes to and which list
   of indicators is on offer.

     target "ind"   → the global MK.ind — map, Data › Areas, area page, test property
     target "chind" → the chart generator's own CH.ind

   Markup, classes, test ids, keyboard model and the popover behaviour are identical everywhere.
   The popover is rendered with the view (hidden) and opened by toggling one class, so opening it
   never re-renders anything and the search keeps focus. */
const chartPool = () => IND.concat(IND_CPH.filter(i => !IND.some(x => x.key === i.key)));
/* the level whose figures the view on screen shows — it decides which rows read `muni` */
function pickLevel() {
  if (S.view === "table") return T.level;
  if (S.view === "area") return AR.type || "kommune";
  /* the test property is read at the level of the pin's finest area (spec §5.5′) */
  if (S.view === "analysis") { const e = anEntity(); return e ? e.type : "kommune"; }
  if (S.view === "makro") return cphMode() ? "kvarter" : MK.muni ? "postnr" : "kommune";
  return "kommune";
}
/* at this level the indicator has no figure of its own and the municipality's is shown (° in tables) */
function pickInherits(i, level) {
  if (!i) return false;
  if (level === "postnr") return i.level !== "postnr";
  if (level === "kvarter") return !cphOwn(i.key);
  return false;
}
const PICK_POOL = { kommune: () => MUNI, postnr: () => AREAS, kvarter: () => (CPH ? CPH.areas : MUNI) };
/* yearsForPool() over 63 indicators × 606 postal codes is ~0.7 M reads and the popover asks for all
   of them on every render. The data never changes, so each (level, indicator) pair is computed once. */
const PICK_YEARS = {};
function pickYears(key, level) {
  const ck = level + "|" + key;
  if (!(ck in PICK_YEARS)) PICK_YEARS[ck] = yearsForPool(key, (PICK_POOL[level] || PICK_POOL.kommune)());
  return PICK_YEARS[ck];
}
function pickCtx(target) {
  if (target === "chind") return { target: "chind", key: CH.ind, list: chartPool(), level: "kommune" };
  return { target: "ind", key: MK.ind, list: curInds(), level: pickLevel() };
}
const pickCur = c => c.list.find(i => i.key === c.key) || c.list[0] || { key: "", label: "–", unit: "" };
const PICK_LEVEL_LABEL = { kommune: "municipality", postnr: "postal code", kvarter: "quarter" };
function indPicker(target) {
  const c = pickCtx(target), cur = pickCur(c);
  const row = i => {
    const t = PC.availTag(i, { inherited: pickInherits(i, c.level), years: pickYears(i.key, c.level) });
    const on = i.key === cur.key;
    return `<button type="button" class="indrow${on ? " on" : ""}" role="option" id="indopt-${esc(i.key)}" data-ind="${esc(i.key)}" aria-selected="${on ? "true" : "false"}" title="${esc(i.desc || i.label)}">
      <span class="ir-l">${esc(i.label)}</span><span class="ir-u">${esc(i.unit || "")}</span>${lowerBetter(i.key) ? `<span class="ir-d">↓ lower is better</span>` : ""}<span class="ir-t ${t.cls}" title="${esc(t.title)}">${esc(t.text)}</span></button>`;
  };
  /* the button says what is selected and, when the figure is not native to the level on screen,
     whose figure it is — never a bare ° (spec §2.4, §4.2) */
  const inh = pickInherits(cur, c.level);
  return `<div class="indpick" data-testid="ind-picker" data-target="${esc(c.target)}">
    <button type="button" class="indpick-btn" data-testid="ind-picker-btn" data-indpop data-ind="${esc(cur.key)}" aria-expanded="false" aria-haspopup="listbox" title="Choose an indicator">
      <span class="ip-l">${esc(cur.label)}</span>${cur.unit ? `<span class="ip-u">${esc(cur.unit)}</span>` : ""}${inh ? `<span class="ip-t">municipality</span>` : ""}<em aria-hidden="true">▾</em></button>
    <div class="indpop" data-testid="ind-picker-pop" hidden>
      <div class="indpop-h"><input type="search" id="indsearch" data-testid="ind-search" class="indsearch" placeholder="Search indicators…" autocomplete="off" aria-label="Search indicators" aria-controls="indlist"><span class="indpop-esc">Esc</span></div>
      <div class="indlist" id="indlist" role="listbox" aria-label="Indicators">${PC.groupedLevel(c.list, GROUP_ORDER, i => pickInherits(i, c.level)).map(g =>
        `<div class="indsec" data-group="${esc(g.name)}"><div class="indgrp"><span>${esc(g.name)}</span>${g.pill ? `<em class="tag ${g.name === "Outlook" ? "proj" : "clim"}">${esc(g.pill)}</em>` : ""}</div>${g.inds.map(row).join("")}</div>`).join("")}
        <div class="indnone" hidden>No indicator matches — try one word, or a unit like <b>DKK</b>.</div></div>
      <div class="indpop-f">${c.list.length} indicators · ${esc(PICK_LEVEL_LABEL[c.level] || c.level)} level · ↑ ↓ to move, Enter to choose</div>
    </div></div>`;
}
/* the chips row: QUICK_KEYS ∩ available at this level, the active one filled (spec §4.2).
   `opts.testid` names the copy that lives inside the full-screen mini map — the page's own row is
   the one every AC reads, so the copy must not answer to `ind-chips` as well. */
function indChips(target, opts) {
  const c = pickCtx(target), o = opts || {};
  const ks = QUICK_KEYS.map(k => c.list.find(i => i.key === k)).filter(Boolean);
  if (ks.length < 2) return "";
  return `<div class="indchips${o.cls ? " " + o.cls : ""}" data-testid="${esc(o.testid || "ind-chips")}" data-target="${esc(c.target)}" role="group" aria-label="Quick indicators">${ks.map(i =>
    `<button type="button" class="chip ${c.key === i.key ? "on" : ""}" data-ind="${esc(i.key)}" title="${esc(i.label)}${i.unit ? " · " + esc(i.unit) : ""}">${esc(i.chip_label || i.short || i.label)}</button>`).join("")}</div>`;
}
/* ---- the popover: open / close / filter / keyboard ---- */
const indPopEl = () => document.querySelector("[data-testid=ind-picker]");
/* `refocus` puts the caret back on the button — right after Esc or a second click on the button,
   wrong after a click somewhere else on the page, which is a move away from the picker. */
function indPopOpen(open, refocus) {
  const wrap = indPopEl(); if (!wrap) return;
  const btn = wrap.querySelector("[data-testid=ind-picker-btn]"), pop = wrap.querySelector("[data-testid=ind-picker-pop]");
  if (!btn || !pop) return;
  wrap.classList.toggle("open", open);
  pop.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    const q = wrap.querySelector("[data-testid=ind-search]");
    if (q) { q.value = ""; indPickFilter(""); q.focus(); }
    indPickActive(wrap.querySelector(".indrow.on"));
  } else if (refocus) btn.focus();
}
/* hide the rows the query does not match, and the group headers left with no row (spec §4.2) */
function indPickFilter(q) {
  const wrap = indPopEl(); if (!wrap) return;
  const c = pickCtx(wrap.dataset.target);
  const keep = new Set(PC.filter(c.list, q).map(i => i.key));
  wrap.querySelectorAll(".indrow").forEach(r => { r.hidden = !keep.has(r.dataset.ind); });
  /* a group whose every row went is hidden with them — the rows live inside their group now */
  wrap.querySelectorAll(".indsec").forEach(sec => {
    sec.hidden = ![...sec.querySelectorAll(".indrow")].some(r => !r.hidden);
  });
  const none = wrap.querySelector(".indnone"); if (none) none.hidden = keep.size > 0;
  indPickActive(indPickRows()[0] || null);
}
const indPickRows = () => { const w = indPopEl(); return w ? [...w.querySelectorAll(".indrow")].filter(r => !r.hidden) : []; };
/* aria-activedescendant is how a screen reader follows ↑/↓ without moving focus off the search box */
function indPickActive(row) {
  const wrap = indPopEl(); if (!wrap) return;
  wrap.querySelectorAll(".indrow.act").forEach(r => r.classList.remove("act"));
  const list = wrap.querySelector("#indlist");
  if (!row) { if (list) list.removeAttribute("aria-activedescendant"); return; }
  row.classList.add("act");
  if (list) list.setAttribute("aria-activedescendant", row.id);
  if (row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
}
function indPickMove(delta) {
  const rows = indPickRows(); if (!rows.length) return;
  const cur = rows.findIndex(r => r.classList.contains("act"));
  indPickActive(rows[PC.step(cur, delta, rows.length)]);
}
/* the one place an indicator is chosen, from the popover, a chip, or a row of a table */
function pickInd(key, target) {
  if (target === "chind") { if (CH.ind === key) { indPopOpen(false); return; } CH.ind = key; CH.ov = []; syncHash(); renderKeep(); return; }
  MK.ind = key;
  if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST;
  syncHash();
  /* the area page and the test property update in place: the mini map, the scroll position and the
     full-screen overlay all survive an indicator change (AC-P4, AC-TP3). */
  if (areaRefresh() || tpRefresh()) return;
  renderKeep();
}
const pickTargetOf = el => { const w = el.closest("[data-target]"); return (w && w.dataset.target) || "ind"; };

/* ---- PeriodControl (spec §4.3): year select · horizon segments · projection badge ---- */
/* the PeriodControl in horizon mode on its own: the climate sheet's header is not driven by the
   picker's active indicator but shows the same control, with the same test ids (spec §5.7, AC-SH2) */
const periodHz = where => `<div class="period" data-testid="period" data-mode="horizon">${hzPill(where)}</div>`;
function periodControl(target) {
  const c = pickCtx(target), cur = pickCur(c);
  const mode = PC.periodMode(cur);
  const wrap = (m, inner) => `<div class="period" data-testid="period" data-mode="${m}">${inner}</div>`;
  if (mode === "horizon") return periodHz("tools");
  if (mode === "projection") return wrap("projection",
    `<span class="projwin" data-testid="period-proj" title="${esc((cur.proj.publisher || "") + " " + (cur.proj.table || "") + " — a single vintage, not a series")}">${esc(projWindow(cur))}${cur.proj.table ? " · " + esc(cur.proj.table) : ""}</span>`);
  const ys = yearsFor(cur.key);
  /* one published as-of and no series: say when it is from rather than offer a year that is not a choice */
  if (ys.length < 2) {
    const a = cur.asof || {};
    const at = a[c.level] || a.kommune || a.postnr || a.kvarter || "";
    return wrap("snapshot", `<span class="asofbadge" data-testid="period-asof" title="one published as-of — this indicator has no year series">${at ? "as of " + esc(at) : "one snapshot"}</span>`);
  }
  const hy = ys.filter(y => y !== LATEST); const lastHist = hy[hy.length - 1];
  const pool = (PICK_POOL[c.level] || PICK_POOL.kommune)();
  /* rolling indicators (Safety) have no calendar value for the latest year but their live window ends in it */
  const a = cur.asof || {}; const endYr = (String(a.kommune || a.postnr || a.kvarter || "").split("→").pop().split("–").pop().match(/\d{4}/) || [""])[0];
  const label = y => y === LATEST ? (lastHist && lastHist !== LATEST && endYr !== LATEST && !pool.some(m => m.hist && m.hist[cur.key] && m.hist[cur.key][LATEST] != null) ? `latest (${lastHist} data)` : `${y} (latest)`) : y;
  return wrap("year", `<select id="yearsel" class="indsel" data-testid="period-year" aria-label="Year">${ys.filter(y => !(y === lastHist && label(LATEST).startsWith("latest ("))).map(y =>
    `<option value="${y}" ${MK.year === y ? "selected" : ""}>${label(y)}</option>`).join("")}</select>`);
}
/* searchable area box: municipalities open on the map, postal codes and quarters open their page */
const AREA_OPTS = [{ t: "Denmark — whole country", h: "map", k: ["denmark", "danmark", "dk"] }];
MUNI.slice().sort((a, b) => a.name.localeCompare(b.name, LOCALE)).forEach(m => AREA_OPTS.push({ t: `${m.name} — municipality, ${m.region || ""}`, h: `map/${m.code}`, k: [m.name.toLowerCase(), m.code] }));
AREAS.slice().sort((a, b) => a.nr.localeCompare(b.nr)).forEach(a => AREA_OPTS.push({ t: `${a.nr} ${a.name} — postal code, ${(byCode[a.muni] || {}).name || ""}`, h: `area/postnr/${a.nr}`, k: [a.nr, (a.name || "").toLowerCase()] }));
if (CPH) CPH.areas.slice().sort((a, b) => (a.name || "").localeCompare(b.name || "", LOCALE)).forEach(q => AREA_OPTS.push({ t: `${q.name} — Copenhagen quarter, ${q.bydel || ""}`, h: `area/kvarter/${q.code}`, k: [(q.name || "").toLowerCase(), q.code] }));
/* ---------- the unified search (spec §5.1) ----------
   One combobox for two kinds of thing a reader has in the clipboard: the name or code of an area,
   and a location — a Google Maps link or a `lat, lon` pair, read by the same `parseLocation()` the
   test property uses. An area result opens its page (or drills the map for a municipality); a
   location becomes a `search-coord` row that opens it as a test property. The "Jump to" row at the
   top replaces the two toolbar buttons the v2.6 map carried (the C / D shortcuts still work). */
const ASRCH_MAX = 8;
const asrchQ = () => `?ind=${encodeURIComponent(MK.ind)}` + (MK.year !== LATEST ? `&y=${MK.year}` : "");
/* the area rows for a query: an exact code or name first, then the ones that start with it, then the
   ones that merely contain it — a reader typing "2450" wants the postal code, not Aarhus 8000 */
function asrchAreas(q) {
  const ql = q.toLowerCase().replace(/\s+—.*$/, "").trim();
  if (!ql) return [];
  const exact = [], starts = [], has = [];
  AREA_OPTS.forEach(o => {
    /* matched on the name and the code only — never on the " — municipality, Hovedstaden" tail, or
       a single letter would bring back half the country for the word "municipality" */
    if (o.t === q || o.k.some(k => k === ql)) exact.push(o);
    else if (o.k.some(k => k.startsWith(ql))) starts.push(o);
    else if (o.k.some(k => k.includes(ql))) has.push(o);
  });
  return exact.concat(starts, has).slice(0, ASRCH_MAX);
}
/* every row the dropdown shows for a query, in the order Enter takes them */
function asrchRows(q) {
  const rows = [];
  const txt = (q || "").trim();
  if (txt) {
    const r = parseLocation(txt);
    if (r.lat != null) rows.push({ kind: "coord", h: `property?p=${RC.propSerialise([{ lat: r.lat, lon: r.lon }])}`,
      main: "Open as test property", sub: `${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}` });
  }
  asrchAreas(txt).forEach(o => { const p = o.t.split(" — ");
    rows.push({ kind: "area", h: o.h + asrchQ(), main: p[0], sub: p.slice(1).join(" — ") }); });
  return rows;
}
function asrchHtml(q) {
  const rows = asrchRows(q);
  const txt = (q || "").trim();
  const err = txt && !rows.length ? parseLocation(txt) : null;
  /* the dropdown is a listbox, driven by ↑ ↓ and Enter from the input (spec §5.1, §7) — so its rows
     are `tabindex=-1`. Six hundred postal codes in the tab order would bury every control after it. */
  return `<div class="as-jump">Jump to:${Object.keys(MAP_JUMPS).map(id => {
      const j = MAP_JUMPS[id]; return `<button type="button" tabindex="-1" data-mapjump="${id}" title="Zoom to ${esc(j.label)} — the selection does not change (${j.key})">${esc(j.label)}</button>`; }).join("<i>·</i>")}</div>`
    + rows.map((r, n) => `<button type="button" tabindex="-1" class="as-row${r.kind === "coord" ? " as-coord" : ""}" role="option" aria-selected="false" data-go="${esc(r.h)}"${r.kind === "coord" ? ' data-testid="search-coord"' : ""}><b>${esc(r.main)}</b><span>${esc(r.sub)}</span></button>`).join("")
    + (!txt ? `<div class="as-hint">Type a municipality, postal code or quarter — or paste a Google Maps link or <b>55.67610, 12.56830</b>.</div>`
       : !rows.length ? `<div class="as-hint">${esc(err && err.error !== "no_match" && err.error !== "empty" ? err.message
           : `No area matches “${txt}” — try a postal code, a municipality, or a Google Maps link.`)}</div>` : "");
}
function areaSearch() {
  const m = MK.muni ? byCode[MK.muni] : null;
  return `<span class="asrch" data-testid="search-box">
    <input id="areaq" type="search" class="indsel" data-testid="search" role="combobox" aria-expanded="false" aria-autocomplete="list" aria-controls="asrchlist" autocomplete="off"
      placeholder="${m ? esc(m.name) + " — search area, link or coords…" : "Search area, postal code, link or coords…"}" aria-label="Search municipality, postal code, quarter, Google Maps link or coordinates">
    <span class="tptip" tabindex="0" role="note" aria-label="What the search takes, and where a location goes">?<span class="tptipc"><b>Accepted formats</b>${TP_FORMATS.map(([, ex, what]) => `<i>${esc(ex)}</i><span>${esc(what)}</span>`).join("")}<span class="tpwarn">${esc(TP_NOTE)}</span></span></span>
    <div class="asrchpop" id="asrchlist" role="listbox" aria-label="Search results" hidden></div></span>`;
}
const asrchEl = () => document.querySelector(".asrch");
function asrchOpen(open) {
  const w = asrchEl(); if (!w) return;
  const pop = w.querySelector(".asrchpop"), inp = w.querySelector("#areaq");
  if (!pop) return;
  if (open && !pop.innerHTML) pop.innerHTML = asrchHtml(inp ? inp.value : "");
  pop.hidden = !open;
  w.classList.toggle("open", !!open);
  if (inp) inp.setAttribute("aria-expanded", open ? "true" : "false");
}
function asrchRender(q) {
  const w = asrchEl(); if (!w) return;
  const pop = w.querySelector(".asrchpop"); if (!pop) return;
  pop.innerHTML = asrchHtml(q);
  asrchOpen(true);
}
const asrchRowEls = () => { const w = asrchEl(); return w ? [...w.querySelectorAll(".as-row")] : []; };
function asrchMove(delta) {
  const rows = asrchRowEls(); if (!rows.length) return;
  const cur = rows.findIndex(r => r.classList.contains("act"));
  const next = rows[PC.step(cur, delta, rows.length)];
  rows.forEach(r => { r.classList.remove("act"); r.setAttribute("aria-selected", "false"); });
  if (next) { next.classList.add("act"); next.setAttribute("aria-selected", "true"); if (next.scrollIntoView) next.scrollIntoView({ block: "nearest" }); }
}
/* Enter takes the highlighted row, or the first one — so a typed postal code is still one keystroke */
function asrchEnter(txt) {
  const rows = asrchRowEls();
  const pick = rows.find(r => r.classList.contains("act")) || rows[0];
  if (pick) { asrchOpen(false); go(pick.dataset.go); return; }
  areaSearchGo(txt);
}
function areaSearchGo(txt) {
  const rows = asrchRows(txt);
  if (rows.length) { asrchOpen(false); go(rows[0].h); }
}
function asofText(i) {
  const asofSrc = (MK.year !== LATEST && i.hist_asof && i.hist_asof[MK.year]) ? i.hist_asof[MK.year] : i.asof;
  return asofSrc ? Object.entries(asofSrc).map(([g, p]) => `${g === "postnr" ? "postal codes" : g === "kvarter" ? "quarters" : "municipalities"}: ${esc(p)}`).join(" · ") : "";
}
function indExplain(i) {
  const pool = curPool();
  const cov = i.level === "kvarter" ? `${CPH.areas.filter(a => a[i.key] != null).length}/${CPH.areas.length} quarters` : `${MUNI.filter(m => m[i.key] != null).length}/${MUNI.length} municipalities${i.level === "postnr" ? `, ${AREAS.filter(a => a[i.key] != null).length}/${AREAS.length} postal codes` : ""}`;
  const ys = yearsForPool(i.key, pool);
  const asof = asofText(i);
  /* one line by default — label, level, unit, period; the definition, source, coverage and caveat open on ⓘ */
  const asofShort = asofSrc => { const src = (MK.year !== LATEST && i.hist_asof && i.hist_asof[MK.year]) || i.asof || {}; return src.kommune || src.postnr || src.kvarter || ""; };
  const lb = lowerBetter(i.key);
  const src = srcLine(i, asofShort());
  return `<details class="indx" ${UI.indxOpen ? "open" : ""}>
    <summary><b>${esc(i.label)}</b><span class="tag">${esc(i.level_label || (i.level === "kvarter" ? "quarter level" : i.level === "postnr" ? "postal-code level" : "municipality level"))}</span><span class="tag">${esc(i.unit || "")}</span>${lb ? `<span class="tag">↓ lower is better</span>` : ""}${i.proj ? `<span class="tag proj">Projection ${esc(i.proj.from)}→${esc(i.proj.to)}</span><span class="tag">${esc(i.proj.publisher)} ${esc(i.proj.vintage)}</span>` : ""}${asofShort() ? `<span class="dim">as of ${esc(asofShort())}</span>` : ""}${i.warn ? `<span class="warnline">⚠</span>` : ""}<i class="more">ⓘ details</i></summary>
    <div class="indx-body"><p>${esc(i.desc || "")}${lb ? ` <b>↓ Lower is better</b> — rank #1 is the lowest value.` : ""}${neutralDir(i.key) ? ` <b>Neither end is better</b> — a shrinking area is not failing and a growing one is not succeeding, so this is ranked by size only, never good to bad.` : ""}</p>
    ${i.proj && i.proj.caveat ? `<p class="warnline">⚠ ${esc(i.proj.caveat)}</p>` : ""}
    ${i.note ? `<p class="dim"><em>Note</em> ${esc(i.note)}</p>` : ""}
    <p class="dim"><em>Source</em> ${esc(i.source || "–")}${asof ? ` · <em>As of</em> ${asof}` : ""} · <em>Coverage</em> ${cov}${ys.length > 1 ? ` · <em>History</em> ${ys[0]}–${LATEST}` : ""}</p>
    ${(() => { const e_ = S.view === "area" ? areaEntity() : null;
       const c_ = e_ ? (e_.type === "postnr" ? e_.o.nr : srcCode(e_.o, e_.type)) : (MK.muni || "");
       const l_ = indSrcLink(i, c_, null, e_ ? e_.type : "kommune"); return l_ ? `<p class="dim">${l_}</p>` : ""; })()}
    ${src ? `<p class="dim">${esc(src)}</p>` : ""}
    ${i.warn ? `<p class="warnline">⚠ ${esc(i.warn)}</p>` : ""}</div>
  </details>`;
}
/* "Danmarks Statistik, STRAF11 / FOLK1A, as of 2025K3→2026K2, fetched 2026-09-22" from the indicator's tables and the source stamps */
function srcLine(i, asof) {
  const S_ = {}; ((D.meta && D.meta.sources) || []).forEach(s => S_[s.key] = s);
  const PUB = { dst: "Danmarks Statistik", s20: "Finans Danmark", s30: "Københavns Kommune" };
  const by = {}; (i.tables || []).forEach(t => { const [db, tb] = t.split("/"); (by[db] = by[db] || []).push(tb); });
  const fetched = (i.tables || []).map(t => (S_[t] || {}).fetched).filter(Boolean).sort().pop();
  const pubs = Object.entries(by).map(([db, tbs]) => `${PUB[db] || db}, ${tbs.join(" / ")}`);
  return pubs.length ? `${pubs.join(" · ")}${asof ? `, as of ${asof}` : ""}${fetched ? `, fetched ${fetched}` : ""}` : "";
}
/* The period control is one component (periodControl(), spec §4.3). `yearSelect()` is the name the
   views that have not been rebuilt yet still call it by — the area page and the sheets adopt the
   full toolbar in P5/P6; until then they get the same control under the old name, so there is never
   a second implementation of "which period does this indicator have". */
const yearSelect = () => periodControl("ind");

/* geometry helpers: largest ring, centroid */
const mainRing = a => (a.rings || []).slice().sort((x, y) => y.length - x.length)[0] || [];
const centroid = ring => ring.reduce((o, p) => [o[0] + p[0] / ring.length, o[1] + p[1] / ring.length], [0, 0]);
function muniAreas(code) { return (cphMode() && code === CPH_MUNI) ? CPH.areas : AREAS.filter(a => a.muni === code); }
function boundsOf(list) { const pts = []; list.forEach(a => (a.rings || []).forEach(r => r.forEach(p => pts.push(p)))); return pts.length ? L.latLngBounds(pts) : null; }
function applyPendingFit() {
  if (!LF.map || !LF.pendingFit) return;
  const b = boundsOf(muniAreas(LF.pendingFit)); LF.pendingFit = null;
  if (b) LF.map.fitBounds(b, { padding: [12, 12] });
}
/* page links for the three entity types */
const pageOf = o => o.nr ? `area/postnr/${o.nr}` : o.bydel != null ? `area/kvarter/${o.code}` : `area/kommune/${o.code}`;
const withQ = h => h + `?ind=${encodeURIComponent(MK.ind)}` + (MK.year !== LATEST ? `&y=${MK.year}` : "");

/* ---------- Macro map view ---------- */
/* the catalogue line and the small print, without the <details> around it — the area page's own
   "Data information" toggle is that <details> (spec §5.2), so it uses this directly */
function srcNoteBody(extra = "") {
  const s = (D.meta && D.meta.sources) || [];
  const list = s.map(x => `${esc(x.label)}${x.asof ? " (" + esc(x.asof) + ")" : ""}`).join(" · ");
  return `<div class="note"><b>Open data.</b> ${list || "no sources recorded"}${CPH && CPH.meta && CPH.meta.attribution ? " · " + esc(CPH.meta.attribution) : ""}.
    Municipality-level indicators are shown on postal-code polygons with the municipality value (marked °) when no finer statistic exists.
    ${esc((D.meta && D.meta.note) || "")}</div>${extra}<p class="cap">Full definitions and table stamps under <button class="lk mini" data-go="data/sources">Data › Sources</button>. Built ${esc((D.meta && D.meta.built) || "–")}.</p>`;
}
function srcNote(extra = "") {
  /* collapsed by default — "Data information" opens the source list and the small print */
  return `<details class="dinfo"><summary>Data information</summary>${srcNoteBody(extra)}</details>`;
}
function rankOf(o, key, peers) {
  const v = V(o, key); if (v == null) return null;
  const vals = peers.map(p => V(p, key)).filter(x => x != null);
  const lb = lowerBetter(key);   /* #1 = best: the highest value, or the lowest where lower is better */
  /* a neutral indicator still has an order — highest first — but #1 is a position, not a verdict */
  return { r: 1 + vals.filter(x => lb ? x < v : x > v).length, n: vals.length, neutral: neutralDir(key) };
}
/* §2.4, one rank format everywhere: `#n of N`, N = the peers that publish a figure, and a `title`
   that names them ("of 77 municipalities with a figure"). Every surface goes through this — tiles,
   tables, the chart panel, the map popup, the sheets — so `#n / N` never reappears. */
function rankHtml(rk, label) {
  if (!rk) return "";
  return `<span class="rk" title="of ${esc(nf(rk.n, 0))} ${esc(label || "peers")} with a figure">#${rk.r} of ${rk.n}</span>`;
}
/* §2.4 missing values: `–` = the publisher has no figure here, `n/c` = not computed at this level.
   Never a bare 0, and the two are never the same glyph. */
const DASH = "–";
const NC = `<span class="nc" title="not computed at this level">n/c</span>`;
/* §2.4 small base: a projected % change on a base under 1 000 persons is read persons-first —
   "+9 persons" is the fact, "+1 030 %" is an artefact of the denominator. `projPersons` reads the
   projection's own window out of the registry, so the two numbers always describe the same years. */
const SMALL_BASE = 1000;
function projPersons(o, level) {
  const list = level === "kvarter" ? IND_CPH : IND;
  const pr = ((list.find(i => i.key === "fc_growth") || {}).proj) || {};
  const fp = o && o.fc_pop; if (!fp) return null;
  const a = fp[pr.from || "2026"], b = fp[pr.to || "2040"];
  if (a == null || b == null) return null;
  return { base: a, persons: b - a, small: a < SMALL_BASE, from: pr.from, to: pr.to };
}
/* the value of a projected % change, persons first when the base is small. Anything else is the
   ordinary formatter — one path, one decision, every surface. */
function projValueHtml(i, v, o, level) {
  const p = i && i.key === "fc_growth" && isPct(i) ? projPersons(o, level) : null;
  if (!p || !p.small) return fmtOf(i)(v);
  return `<span class="persons">${sign(p.persons, x => nf(x, 0))} persons</span> <span class="pctsecond">(${fmtOf(i)(v)})</span>`;
}
const smallBaseTag = (i, o, level) => {
  const p = i && i.key === "fc_growth" ? projPersons(o, level) : null;
  return p && p.small ? `<span class="tag smallbase" title="${nf(p.base, 0)} residents in ${esc(p.from || "")} — a percentage on a base this small moves on a handful of people">small base</span>` : "";
};
/* good/bad sense of a change d in indicator key: "up" = favourable (green), "dn" = unfavourable */
/* neutral: no favourable end, so a change gets no colour at all — growth is not success (docs/FORECAST.md §3) */
const cls = (d, key) => { if (neutralDir(key || "")) return ""; const s = lowerBetter(key || "") ? -d : d; return s > 0 ? "up" : s < 0 ? "dn" : ""; };
const goodBad = (d, key) => d == null ? "" : ({ up: "good", dn: "bad" })[cls(d, key)] || "";
function muniStrip(m) {
  /* the selected municipality in one line: population, region, four headline figures + crime with rank, link to its page.
     The figures are the municipality's own, so the national indicator list applies in quarter mode too. */
  const has = i => i && V(m, i.key) != null;
  const key = HL_KEYS.filter(k => !STRIP_EXTRA.includes(k)).map(k => IND.find(i => i.key === k)).filter(has).slice(0, 4)
    .concat(STRIP_EXTRA.map(k => IND.find(i => i.key === k)).filter(has));
  const cell = i => { const rk = rankOf(m, i.key, MUNI); return `<div><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(V(m, i.key))}</b><em>${rankHtml(rk, "municipalities")}</em></div>`; };
  /* Collapsible (spec §5.1): the facts block runs to some 400 px on a big municipality, which at
     1366×768 pushed the drilled map off the first screen. The identity line and the five headline
     figures stay in the summary; the projects, public buildings, climate and outlook blocks open on
     click. The fold is the reader's, so it is remembered in localStorage rather than in the URL. */
  return `<details class="mstrip" data-mstrip ${mstripOpen() ? "open" : ""}>
    <summary>
      <div class="mstrip-id"><b>${esc(m.name)}</b><span class="dim">${esc(m.region || "")} · ${m.pop != null ? nf(m.pop, 0) + " inhabitants" : ""} · ${muniAreas(m.code).length} ${cphMode() ? "quarters" : "postal codes"}</span></div>
      <div class="mstrip-k">${key.map(cell).join("")}</div>
      <i class="mstrip-more">projects · public · climate · outlook</i>
    </summary>
    <div class="mstrip-body">${upcomingLine("kommune", m.code)}${publicLine("kommune", m.code)}${climateLine("kommune", m.code)}${String(m.code) === CPH_MUNI_CODE && CPH_CITY_FC ? outlookBothHtml(m) : outlookLine(m, "kommune")}
      <div class="mstrip-act"><button class="lk primary" data-go="${withQ(pageOf(m))}">Open ${esc(m.name)} page ›</button><button class="lk" data-go="${chartLink(MK.ind, "kommune", m.code)}" title="Open the chart generator with this municipality">↗ Chart</button></div>
    </div>
  </details>`;
}
/* the municipality card's fold: cosmetic, so localStorage rather than the URL. Closed by default —
   what the reader came for is the map under it. */
function mstripOpen() {
  try { return localStorage.getItem("mstrip") === "1"; } catch (e) { return false; }
}
function mstripSet(open) {
  try { localStorage.setItem("mstrip", open ? "1" : "0"); } catch (e) { /* private mode: this session only */ }
}
/* ---------- Outlook lines (docs/FORECAST.md §5.7, §8) ---------- */
const CPH_MUNI_CODE = "101";
/* the one-line outlook under population: "Outlook 2040: +5.9 % (20–34: +0.3 pp vs Denmark)" */
function outlookLine(o, level) {
  if (!o) return "";
  const list = level === "kvarter" ? IND_CPH : IND;
  const g = list.find(i => i.key === "fc_growth"), r = list.find(i => i.key === "fc_20_34_rel");
  const gv = o.fc_growth, rv = o.fc_20_34_rel;
  if (gv == null || !g) return "";
  const to = (g.proj && g.proj.to) || "2040";
  const who = (g.proj && g.proj.publisher) || "DST";
  const rel = rv != null && r ? ` <span class="dim">(20–34: ${fmtOf(r)(rv)} ${esc(relLabel(r))})</span>` : "";
  const chg = projChangeLine(o, level);
  const link = srcLink((g.proj || {}).src, srcCode(o, level));
  return `<div class="olline"><span>Outlook ${esc(to)}</span><b>${fmtOf(g)(gv)}</b>${rel}<em class="dim">${esc(who)}</em></div>`
    + (chg ? `<div class="olchg">${chg}</div>` : "")
    + (link ? `<div class="olsrc">${link}</div>` : "");
}
/* §4: a DST figure and a KK figure may sit side by side only if the gap between them is stated.
   København is the one place both exist, so it is the one place this renders. */
function outlookBothHtml(m) {
  if (!m || String(m.code) !== CPH_MUNI_CODE || !CPH) return "";
  const kk = CPH_CITY_FC;
  const dst = m.fc_growth;
  if (dst == null || !kk || kk.fc_growth == null) return outlookLine(m, "kommune");
  const gap = Math.round((kk.fc_growth - dst) * 100) / 100;
  const g = IND.find(i => i.key === "fc_growth");
  const gq = IND_CPH.find(i => i.key === "fc_growth");
  return `<div class="olboth">
    <div class="olrow"><span>Outlook 2040 · <b class="olpub">DST</b></span><b>${fmtOf(g)(dst)}</b>
      ${srcLink((g.proj || {}).src, m.code, "Verify")}</div>
    <div class="olrow"><span>Outlook 2040 · <b class="olpub">Københavns Kommune</b></span><b>${fmtOf(g)(kk.fc_growth)}</b>
      ${srcLink((gq && gq.proj || {}).src, "1000", "Verify")}</div>
    ${projChangeLine(m, "kommune") ? `<div class="olchg">${projChangeLine(m, "kommune")} <span class="dim">· DST</span></div>` : ""}
    <p class="cap">Two different projections of the same city, ${nf(Math.abs(gap), 2)} pp apart — ${kk.fc_growth > dst ? "KK is the higher" : "DST is the higher"}. They are never combined: different runs, different assumptions (docs/FORECAST.md §4).</p>
  </div>`;
}
/* KK's own city total, for the comparison above — the projection file carries every OMRKK level */
const CPH_CITY_FC = (D.cph && D.cph.city_forecast) || null;
/* the caveat that has to reach the UI wherever a kvarter forecast is shown (§8 note 4) */
function cphFcCaveat(level) {
  if (level !== "kvarter") return "";
  const i = IND_CPH.find(x => x.proj && x.proj.caveat);
  return i ? `<p class="cap warnline">⚠ ${esc(i.proj.caveat)}</p>` : "";
}
/* §9.7: the one figure the backtest puts in front of a reader, on kvarter area pages only */
function pastAccuracyLine(a) {
  const bt = a && a.bt;
  if (!bt || bt.bt_mape_5y == null || !bt.bt_n_5y) return "";
  return `<p class="cap">Past accuracy: KK's 5-year forecasts for this area were off by <b>${nf(bt.bt_mape_5y, 1)} %</b> on average (<b>${bt.bt_over_5y}</b> of <b>${bt.bt_n_5y}</b> vintages over-forecast).</p>`;
}

/* The outlook of the areas something sits in — used by the infra datasheet and the Analysis sheet.
   DST and KK are listed as separate blocks, never averaged or merged into one figure (§4). */
function outlookFor(koms, kvas) {
  const gK = IND.find(i => i.key === "fc_growth"), yK = IND.find(i => i.key === "fc_20_34");
  const gQ = IND_CPH.find(i => i.key === "fc_growth"), yQ = IND_CPH.find(i => i.key === "fc_20_34");
  const blocks = [];
  const rows = (list, gi, yi, lvl) => list.filter(o => o && o[gi.key] != null).map(o =>
    `<tr><th>${esc(o.name || o.nr || o.code)}</th><td class="num">${fmtOf(gi)(o[gi.key])}</td><td class="num">${o[yi.key] != null ? fmtOf(yi)(o[yi.key]) : "–"}</td>
      <td class="num">${srcLink((gi.proj || {}).src, srcCode(o, lvl), "Verify")}</td></tr>`).join("");
  const table = (title, pr, body, caveat) => `<div class="olblock">
    <p class="cap"><b>${esc(title)}</b> · <span class="tag proj">Projection ${esc(pr.from)}→${esc(pr.to)}</span> ${esc(pr.publisher)} ${esc(pr.vintage)}${pr.table ? ` · ${esc(pr.table)}` : ""}</p>
    <table class="tbl compact"><thead><tr><th>Area</th><th class="num">Population ${esc(pr.to)}</th><th class="num">20–34</th><th class="num">Source</th></tr></thead><tbody>${body}</tbody></table>
    ${caveat ? `<p class="cap warnline">⚠ ${esc(caveat)}</p>` : ""}</div>`;
  const kr = gK && yK ? rows(koms || [], gK, yK, "kommune") : "";
  if (kr) blocks.push(table("Municipality", gK.proj || {}, kr, ""));
  const qr = gQ && yQ ? rows(kvas || [], gQ, yQ, "kvarter") : "";
  if (qr) blocks.push(table("Copenhagen quarter", gQ.proj || {}, qr, (gQ.proj || {}).caveat || ""));
  if (!blocks.length) return "";
  return `<div class="olfor">${blocks.join("")}
    ${blocks.length > 1 ? `<p class="cap dim">Two different projections, listed separately: DST's municipal run and Københavns Kommune's district run are never combined or averaged — they are 2.2 % apart for this city by 2040 (docs/FORECAST.md §4).</p>` : ""}</div>`;
}

/* "Upcoming: M5 phase 1 (2036) · Nordhavnstunnel (2028) · +3 more" — projects that have not opened */
function upcomingLine(level, code) {
  const up = infraOf(level, code).filter(p => p.status !== "opened");
  if (!up.length) return "";
  const show = up.slice(0, 3).map(p => `<button class="lk mini" data-project="${esc(p.id)}" title="${esc(p.name)}">${esc(p.label_short || p.name)}${p.open_year || p.open_window ? ` (${esc(openLabel(p))})` : ""}</button>`).join("");
  return `<span class="upcoming"><em>Upcoming</em>${show}${up.length > 3 ? `<button class="lk mini" data-go="pipeline">+${up.length - 3} more</button>` : ""}</span>`;
}
/* ---------- Layers ▾ (spec §4.4) ----------
   One menu in place of the five toolbar buttons v2.6 carried. Two sections:

     FEATURE LAYERS  points and lines from other publishers (infra projects, BBR public buildings,
                     OSM/Rejseplanen services) — they make sense over any fill, which is why they
                     are layers. Their category and kind filters live here now; the floating legend
                     cards on the map became pure keys (spec §4.5).
     CONTEXT         things that belong to what is already on screen: the storm-surge zones, which
                     are present only while a Climate indicator is (spec §1 decision 3), and the
                     radius around a test-property pin, only while there is one.

   The URL key is `lay=` for the feature layers, `zones=0` for hiding the context zones, and the
   sub-filters keep the names they have always had (`pub=`, `pubkind=`, `srv=`, `rad=`). */
const MAP_LAYERS = [
  { k: "infra", label: "Infra projects", on: () => MK.infra, avail: () => INFRA.length > 0,
    sub: () => `${INFRA.length} projects · Fingerplan, Anlægsstatus`,
    title: "Planned and ongoing infrastructure projects — lines, stations and corridors" },
  { k: "public", label: "Public buildings", on: () => MK.pub, avail: () => !!PUB,
    sub: () => `BBR ${(PUB || {}).built || ""} · ${((PUB || {}).kommuner || []).length} municipalities`,
    title: "Public buildings from BBR: schools, daycare, health and culture", filters: () => pubFilterRows() },
  { k: "services", label: "Services", on: () => MK.srv, avail: () => !!SRV,
    sub: () => `OSM & Rejseplanen ${(SRV || {}).asof || ""}`,
    title: "Shops, places to eat, pharmacies and public-transport stops", filters: () => srvFilterRows() },
];
/* the Climate context layer is offered only while a Climate indicator is the one being read */
const climZonesAvail = () => !!(CLIM && isClim(MK.ind));
const mapLayers = () => MAP_LAYERS.filter(l => l.avail() && l.on()).map(l => l.k);
const layCount = () => mapLayers().length + (climZonesAvail() && MK.zones ? 1 : 0) + (TP.lat != null && TP.rad ? 1 : 0);
/* the category / kind filters that used to live inside the floating legend cards */
function pubFilterRows() {
  const filtered = !!PF.cats || PF.kind !== "both";
  return `<div class="layfil">${Object.entries(PUB_CAT).map(([k, c]) => { const on = pubCatOn(k);
      return `<button type="button" class="layf ${on ? "" : "off"}" data-pubcat="${k}" aria-pressed="${on}" title="click to ${on ? "hide" : "show"} · shift-click for only this one"><i style="background:${on ? c.color : "transparent"};box-shadow:inset 0 0 0 2px ${c.color}"></i>${esc(c.label)}</button>`; }).join("")}
    <span class="layf-sep"></span>${[["existing", "existing"], ["open", "open case"]].map(([k, lab]) => {
      const on = pubKindOn(k === "open" ? "case" : "existing");
      return `<button type="button" class="layf ${on ? "" : "off"}" data-pubkind="${k}" aria-pressed="${on}">${esc(lab)}</button>`; }).join("")}
    ${filtered ? `<button type="button" class="layf all" data-puball>All</button>` : ""}</div>`;
}
function srvFilterRows() {
  const z = LF.map ? LF.map.getZoom() : 7;
  return `<div class="layfil">${Object.entries(SRV_CAT).map(([k, c]) => { const on = srvCatOn(k);
      return `<button type="button" class="layf ${on ? "" : "off"}" data-srvcat="${k}" aria-pressed="${on}" title="${esc(c.label)} — click to show or hide, shift-click to isolate"><i style="background:${on ? c.color : "transparent"};box-shadow:inset 0 0 0 2px ${c.color}"></i>${esc(c.label)}${on && z < srvCatZoom(k) ? `<em>zoom in</em>` : ""}</button>`; }).join("")}
    <span class="layf-sep"></span>${Object.entries(SRV_TGROUP).map(([g, t]) => { const on = SF.cats.has("transport") && SF.tmodes.has(g);
      return `<button type="button" class="layf ${on ? "" : "off"}" data-srvmode="${g}" aria-pressed="${on}" title="${esc(t.label)} stops">${esc(t.label)}</button>`; }).join("")}
    ${SF.cats.size < Object.keys(SRV_CAT).length || SF.tmodes.size < 2 ? `<button type="button" class="layf all" data-srvall>All</button>` : ""}</div>`;
}
function layRow(k, label, sub, on, title, filters, note) {
  return `<div class="layrow ${on ? "on" : ""}">
    <button type="button" class="laytog" role="switch" data-layer="${esc(k)}" aria-checked="${on ? "true" : "false"}" title="${esc(title || label)}">
      <i class="laybox" aria-hidden="true">${on ? "✓" : ""}</i><b>${esc(label)}</b><span>${esc(sub || "")}</span></button>
    ${on && filters ? filters : ""}${note ? `<p class="laynote">${note}</p>` : ""}</div>`;
}
/* The same menu on the test property (spec §5.5′): the pin's own feature layers, which are the
   Macro map's three read around one point plus the BBR building dots, and the storm-surge zones of
   its municipality as context. The state is `ANL` and the URL key is the same `lay=` — but its
   values differ (`infra,public,buildings,climate`), which is why this is a second list and not a
   flag on the first. `mapLayerToggle()` routes to `tpLayerToggle()` while this page is on screen. */
const TP_LAYERS = [
  { k: "infra", label: "Infra projects", on: () => ANL.infra, avail: () => INFRA.length > 0,
    sub: () => `within ${nf((AN_INFRA_M + 1500) / 1000, 1)} km of the pin · Fingerplan, Anlægsstatus`,
    title: "Every project in the layer around the pin, in its status tones" },
  { k: "public", label: "Public buildings", on: () => ANL.pub, avail: () => !!PUB,
    sub: () => `BBR · within ${nf(anPubMapM(), 0)} m of the pin`,
    title: "Schools, daycare, health and culture from BBR around the pin", filters: () => pubFilterRows(),
    note: () => anPubKoms(anLoc(), anRes()).length ? "" : "not covered yet: Copenhagen metro area only" },
  { k: "buildings", label: "Buildings (BBR)", on: () => ANL.micro, avail: () => true,
    sub: () => `dwellings per building · ${esc((anRes() && anRes().kommune || {}).name || "this municipality")}`,
    title: "BBR buildings with at least two dwellings — the file is fetched when you switch this on",
    note: () => microAvail(anKom()) ? "" : "no BBR building file for this municipality yet" },
];
const tpLayerCount = () => anLayerList().length + (AN.rad ? 1 : 0);
function layersMenu(kind) {
  const tp = kind === "tp";
  const feats = (tp ? TP_LAYERS : MAP_LAYERS).filter(l => l.avail());
  const zones = tp ? !!CLIM : climZonesAvail();
  const n = tp ? tpLayerCount() : layCount();
  const rad = !tp && TP.lat != null;
  return `<div class="layers${UI.layOpen ? " open" : ""}" data-testid="layers">
    <button type="button" class="lay-btn" data-testid="layers-btn" data-laypop aria-expanded="${UI.layOpen ? "true" : "false"}" aria-haspopup="dialog"
      title="Feature layers and context on top of the indicator fill">Layers${n ? `<b class="lay-n">· ${n}</b>` : ""}<em aria-hidden="true">▾</em></button>
    <div class="laypop" data-testid="layers-pop" role="dialog" aria-label="Map layers" ${UI.layOpen ? "" : "hidden"}>
      <div class="lay-h">Feature layers</div>
      ${feats.map(l => layRow(l.k, l.label, l.sub(), l.on(), l.title, l.on() && l.filters ? l.filters() : "",
          tp ? (l.note ? l.note() : "") : (l.k === "public" && MK.muni && !pubAvail(MK.muni) ? "no BBR pull for this municipality yet" : ""))).join("")}
      ${zones || rad || D.portfolio ? `<div class="lay-h">Context</div>` : ""}
      ${tp && zones ? layRow("climate", `Storm-surge zones ${CLIM_ZONE_YEAR[HZ.h] || ""}`, `Kystdirektoratet · 100-year extent`, ANL.climate,
          "The published flood extent for this municipality and the official risk areas", "",
          "the horizon is the one the period control names") : ""}
      ${!tp && zones ? layRow("zones", `Storm-surge zones ${CLIM_ZONE_YEAR[HZ.h] || ""}`, `Kystdirektoratet · zoom ${CLIM_ZOOM}+`, MK.zones,
          "The published flood extent and the official risk areas behind the Climate figures", "",
          `shown because a Climate indicator is active — ${esc(curInd().short || curInd().label)}`) : ""}
      ${rad ? `<div class="layrow ${TP.rad ? "on" : ""}">
        <button type="button" class="laytog" role="switch" data-layer="radius" aria-checked="${TP.rad ? "true" : "false"}" title="Keep only the features within a distance of the pin"><i class="laybox" aria-hidden="true">${TP.rad ? "✓" : ""}</i><b>Test-property radius</b><span>${esc(TP.label || TP_LABEL)}</span></button>
        <div class="layfil">${TP_RADII.filter(m => m).map(m => `<button type="button" class="layf ${TP.rad === m ? "" : "off"}" data-tprad="${m}" aria-pressed="${TP.rad === m}">${esc(tpRadLabel(m))}</button>`).join("")}</div></div>` : ""}
      ${D.portfolio ? `<div class="layrow ${MK.own ? "on" : ""}"><button type="button" class="laytog" role="switch" data-mkown aria-checked="${MK.own ? "true" : "false"}"><i class="laybox" aria-hidden="true">${MK.own ? "✓" : ""}</i><b>Own properties</b><span>${(D.portfolio.properties || []).length} pins</span></button></div>` : ""}
    </div></div>`;
}
function layPopOpen(open, refocus) {
  UI.layOpen = !!open;
  const w = document.querySelector("[data-testid=layers]"); if (!w) return;
  const btn = w.querySelector("[data-testid=layers-btn]"), pop = w.querySelector("[data-testid=layers-pop]");
  w.classList.toggle("open", UI.layOpen);
  if (pop) pop.hidden = !UI.layOpen;
  if (btn) { btn.setAttribute("aria-expanded", UI.layOpen ? "true" : "false"); if (!UI.layOpen && refocus) btn.focus(); }
}
/* one handler for every row: the three feature layers, the Climate context zones and the pin radius.
   The test property has its own state behind the same menu, so it branches out first. */
function mapLayerToggle(k) {
  if (S.view === "analysis") return tpLayerToggle(k);
  if (k === "infra") MK.infra = !MK.infra;
  else if (k === "public") { MK.pub = !MK.pub; LF.pubDrawn = null; }
  else if (k === "services") { MK.srv = !MK.srv; LF.srvDrawn = null; if (MK.srv) srvLoadVisible(); }
  else if (k === "zones") { MK.zones = !MK.zones; LF.climDrawn = null; lfDrop("climAreaG", "climZoneG");
    if (MK.zones) { climRiskLoad(); climLoadVisible(); } }
  else if (k === "radius") { TP.rad = TP.rad ? 0 : 1000; tpRadApply(); return; }
  else return;
  syncHash(); renderKeep();
}
/* the same rows on the test property. A layer never rebuilds the page: the overlays are redrawn on
   the map that is already there, so the reader's pan, zoom and full-screen overlay all survive. */
function tpLayerToggle(k) {
  if (k === "infra") ANL.infra = !ANL.infra;
  else if (k === "public") ANL.pub = !ANL.pub;
  else if (k === "buildings") ANL.micro = !ANL.micro;
  else if (k === "climate") { ANL.climate = !ANL.climate; const r = anRes(); if (ANL.climate && r && r.kommune) climSheetLoadFor(r.kommune.code); }
  else return;
  syncHash();
  const el = document.querySelector("[data-testid=layers]");
  if (el) el.outerHTML = layersMenu("tp");
  anMapOverlays();
}
/* the distance filter changes what the overlays draw, not the map — redraw those and leave it alone */
function tpRadApply() {
  syncHash(); mkRefreshTools();
  if (LF.map) { lfInfraLayers(); if (MK.pub) { lfPublicLayers(true); lfPublicLabels(); } if (MK.srv) lfServicesLayers(true); tpLayers(); }
}

/* The map toolbar, so the zoom ladder can refresh it in place. Re-rendering the whole view
   would re-run lfInit and tear the live map down in the middle of a zoom gesture.
   One row of controls at ≥ 1366 px (spec §5.1, AC-M1, AC-S3): the unified search, Layers ▾, the
   IndicatorPicker and the PeriodControl, plus the drilled-state segments. Chips go in row 2, and
   the full-screen button is a page action in the top bar. */
function mkSegs() {
  const muni = MK.muni ? byCode[MK.muni] : null;
  const s = [];
  if (muni && microAvail(muni.code)) s.push(`<div class="seg"><button class="sg ${!MK.micro ? "on" : ""}" data-micro="0">Areas</button><button class="sg ${MK.micro ? "on" : ""}" data-micro="1">Buildings (${nf(MICRO_IDX[String(Number(muni.code))].n, 0)})</button></div>`);
  if (muni && muni.code === CPH_MUNI && CPH && !microMode()) s.push(`<div class="seg"><button class="sg ${MK.cphView !== "postnr" ? "on" : ""}" data-cphview="kvarter">Quarters (${CPH.areas.length})</button><button class="sg ${MK.cphView === "postnr" ? "on" : ""}" data-cphview="postnr">Postal codes</button></div>`);
  return s.join("");
}
function mkTools() {
  return `<div class="trow" data-row="1">${areaSearch()}${layersMenu()}${microMode() ? mindSelect() : indPicker("ind") + periodControl("ind")}${mkSegs()}</div>
    <div class="trow chiprow" data-row="2" id="mkquick">${microMode() ? "" : indChips("ind")}</div>`;
}
function mkRefreshTools() {
  const el = document.querySelector("#mapcard .tools"); if (el) el.innerHTML = mkTools();
  const ex = document.getElementById("mkexplain");
  if (ex) ex.innerHTML = microMode() ? microExplain() : indExplain(curInd());
  const st = document.getElementById("mkstrip"), mu = MK.muni ? byCode[MK.muni] : null;
  if (st) st.innerHTML = mu && !microMode() ? muniStrip(mu) : "";
}
function vMakro() {
  if (!AREAS.length || !MUNI.length) return `<div class="card"><p class="empty">No macro data built yet — run <code>make fetch</code>, <code>make geo</code> and <code>make build</code>.</p></div>`;
  const ind = curInd();
  mapInit(lfInit);
  const muni = MK.muni ? byCode[MK.muni] : null;
  return `
  <div class="card accent" id="mapcard">
    <div class="card-head tools-only">
      <div class="tools" data-testid="map-toolbar">${mkTools()}</div></div>
    <div id="mkexplain">${microMode() ? microExplain() : indExplain(ind)}</div>
    <div id="mkstrip">${muni && !microMode() ? muniStrip(muni) : ""}</div>
    <div class="mapwrap"><div id="lfmap" data-testid="map"></div>
      <div class="maplegs${UI.legOpen ? " open" : ""}" id="maplegs">
        <!-- §6: on a phone the whole stack folds behind one pill, so the map keeps its screen -->
        <button type="button" class="lgtog" data-legtog data-testid="legend-toggle"
                aria-expanded="${UI.legOpen ? "true" : "false"}" aria-controls="maplegs">Legend ${UI.legOpen ? "▴" : "▾"}</button>
        <div class="maplegend" id="maplegend" data-testid="legend"></div>
        ${climZonesAvail() && MK.zones ? `<div class="maplegend climatelegend" id="climatelegend" data-testid="legend-zones"></div>` : ""}
        ${MK.infra && INFRA.length ? `<div class="maplegend infralegend" id="infralegend" data-testid="legend-infra"></div>` : ""}
        ${MK.pub && PUB ? `<div class="maplegend publiclegend" id="publiclegend" data-testid="legend-public"></div>` : ""}
        ${MK.srv && SRV ? `<div class="maplegend serviceslegend" id="serviceslegend" data-testid="legend-services"></div>` : ""}
      </div></div>
    ${srcNote(`<p class="cap">${muni ? "Click a polygon for its figures and a link to its page." : "Click a polygon for its figures; open a municipality with the search box above or from the popup. Table view lists everything side by side."} Colour classes: quintiles of the visible areas. Boundaries: DAGI, Klimadatastyrelsen (simplified); basemap OpenStreetMap.${MK.srv ? ` <b>Services:</b> ${esc(srvAttribLine())}.` : ""}</p>`)}
  </div>`;
}

/* ---------- Table view ---------- */
function fmtCell(i, v, fallback, mark) {
  if (v == null || isNaN(v)) return `<td class="num">–</td>`;
  return `<td class="num" data-v="${v}">${fmtOf(i)(v)}${fallback ? " °" : mark || ""}</td>`;
}
function deltaCell(o, i, pool) {
  const y0 = yearsForPool(i.key, pool || curPool())[0]; if (!y0 || y0 === MK.year) return `<td class="num dim">–</td>`;
  const a = V(o, i.key, y0), b = V(o, i.key); if (a == null || b == null) return `<td class="num dim">–</td>`;
  const d = isPct(i) ? b - a : (a ? (b / a - 1) * 100 : null); if (d == null) return `<td class="num dim">–</td>`;
  return `<td class="num ${goodBad(d, i.key)}" data-v="${d}">${sign(d, x => nf(x, 1))}${isPct(i) ? " pp" : " %"}</td>`;
}
function tableRows() {
  const q = T.q;
  if (T.level === "kvarter") return (CPH ? CPH.areas : []).filter(a => (a.pop || 0) >= T.minPop && (!q || (a.name || "").toLowerCase().includes(q) || (a.bydel || "").toLowerCase().includes(q) || a.code.includes(q)));
  if (T.level === "kommune") return MUNI.filter(m => (!T.region || m.region === T.region) && (m.pop || 0) >= T.minPop && (!q || m.name.toLowerCase().includes(q) || m.code.includes(q)));
  return AREAS.filter(a => { const m = byCode[a.muni] || {}; return (!T.region || m.region === T.region) && (a.pop || 0) >= T.minPop && (!q || (a.name || "").toLowerCase().includes(q) || a.nr.includes(q) || (m.name || "").toLowerCase().includes(q)); });
}
function tableCols(all) {
  const L = T.level === "kvarter" ? IND_Q : T.level === "postnr" ? IND.filter(i => i.level === "postnr").concat(IND.filter(i => i.level !== "postnr")) : IND;
  /* Safety columns only while a Safety indicator (group or Crime chip) is selected; the CSV export always has everything */
  return all || isSafety(curInd()) ? L : L.filter(i => !isSafety(i));
}
function tableBodyHtml() {
  const cols = tableCols(), ind = curInd(), pool = curPool(), y0 = yearsForPool(ind.key, pool)[0];
  const sv = r => V(r, ind.key) ?? V(byCode[r.muni], ind.key), lb = lowerBetter(ind.key);   /* best first; no value last */
  const rows = tableRows().slice().sort((a, b) => { const x = sv(a), y = sv(b); return x == null ? (y == null ? 0 : 1) : y == null ? -1 : lb ? x - y : y - x; });
  if (!rows.length) return `<tr><td colspan="${cols.length + 5}" class="empty">no rows match the filters</td></tr>`;
  return rows.map(r => {
    const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    const lead = `<tr class="clickrow" data-go="${withQ(pageOf(r))}"><th><span class="thn">${esc(r.name)} <span class="go">›</span></span><button class="tch" data-go="${chartLink(ind.key, T.level, T.level === "postnr" ? r.nr : r.code)}" title="Open in Charts">↗</button></th>`;
    if (T.level === "kvarter") return `${lead}<td class="dim">${esc(r.code)}</td><td class="dim">${esc(r.bydel || "")}</td><td class="num dim" data-v="${r.pop || 0}">${r.pop != null ? nf(r.pop, 0) : "–"}</td>
      ${qCell(r, ind)}${y0 && y0 !== MK.year ? deltaCell(r, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(i => qCell(r, i)).join("")}</tr>`;
    const cell = i => { const own = V(r, i.key); return own != null ? fmtCell(i, own, false) : (T.level === "postnr" ? fmtCell(i, V(m, i.key), true) : fmtCell(i, null, false)); };
    return `${lead}<td class="dim">${T.level === "postnr" ? esc(r.nr) : esc(r.code)}</td><td class="dim">${T.level === "postnr" ? esc(m.name || "") : esc(r.region || "")}</td>
      <td class="num dim" data-v="${r.pop || 0}">${r.pop != null ? nf(r.pop, 0) : "–"}</td>
      ${cell(ind)}${y0 && y0 !== MK.year ? deltaCell(r, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(cell).join("")}</tr>`; }).join("");
}
/* a quarter's own value, or København's for indicators the quarter layer does not have (°) */
function qCell(r, i) { const own = V(r, i.key); return own != null || cphOwn(i.key) ? fmtCell(i, own, false, bydelMark(i)) : fmtCell(i, V(byCode[CPH_MUNI], i.key), true); }
function renderTableBody() {
  const tb = document.getElementById("tbody"); if (!tb) return;
  tb.innerHTML = tableBodyHtml();
  const n = document.getElementById("tcount"); if (n) n.textContent = `${tableRows().length} rows`;
}
const best = i => lowerBetter(i.key) ? "asc" : "desc";
function vTable() {
  const ind = curInd(), cols = tableCols(), y0 = yearsFor(ind.key)[0];
  return `
  ${dataTabs()}
  <div class="card accent">
    <div class="card-head tools-only"><div class="tools">${indPicker("ind")}${periodControl("ind")}</div>${indChips("ind")}</div>
    ${indExplain(ind)}
    <div class="tfilters">
      <input id="tq" type="search" placeholder="Search municipality, postal code or name…" value="${esc(T.q)}">
      <div class="seg"><button class="sg ${T.level === "kommune" ? "on" : ""}" data-tlevel="kommune">Municipalities (${MUNI.length})</button><button class="sg ${T.level === "postnr" ? "on" : ""}" data-tlevel="postnr">Postal codes (${AREAS.length})</button>${CPH ? `<button class="sg ${T.level === "kvarter" ? "on" : ""}" data-tlevel="kvarter">Copenhagen quarters (${CPH.areas.length})</button>` : ""}</div>
      ${T.level !== "kvarter" ? `<select id="tregion" class="indsel"><option value="">All regions</option>${REGIONS.map(r => `<option value="${r}" ${T.region === r ? "selected" : ""}>${r}</option>`).join("")}</select>` : ""}
      <label class="hint">min. population <input id="tminpop" type="number" min="0" step="1000" value="${T.minPop}" style="width:90px"></label>
      <span class="hint" id="tcount">${tableRows().length} rows</span>
      <button class="lk mini" data-csv title="The table as it stands — every column with its table id and as-of in the header. Export ▾ has the long format and every other dataset.">⤓ This view (CSV)</button>
    </div>
    <div class="scrollx"><table class="tbl compact wraphead" data-testid="areas-table" data-sortable><thead><tr>
      <th>${T.level === "kvarter" ? "Quarter" : T.level === "postnr" ? "Area" : "Municipality"}</th><th>${T.level === "postnr" ? "Postal code" : "Code"}</th><th>${T.level === "kvarter" ? "District" : T.level === "postnr" ? "Municipality" : "Region"}</th><th class="num">Population</th>
      <th class="num hi on" data-col="${esc(ind.key)}" data-best="${best(ind)}">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${isPct(ind) ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num" data-col="${esc(i.key)}" data-best="${best(i)}">${esc(i.label)}${lowerBetter(i.key) ? " ↓" : ""}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
      <tbody id="tbody">${tableBodyHtml()}</tbody></table></div>
    <p class="cap">Sorted by the selected indicator, best first (↓ = lower is better); click a column header to re-sort, a row to open the area's page, ↗ to chart it. ° = municipality value shown on a postal code or quarter.${isSafety(curInd()) ? "" : " Safety columns appear when a Safety indicator is selected."} Rows: ${T.level === "postnr" ? "postal codes (street-level codes in central Copenhagen merged by name)" : T.level === "kvarter" ? "Copenhagen quarters (kvarterer), source Københavns Kommune statbank" : "municipalities"}.</p>
    ${srcNote()}
  </div>`;
}
function downloadCsv(lines, name) {
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
/* ---------- Export ▾ — one menu, one schema (spec §4.9, §5.5′) ----------
   The row builders, the column sets, the source columns and the unit fix live in
   src/export_core.js (pure, `node --test tests/export.test.js`). This side knows the data: which
   areas exist, which observations an indicator has, and where a value is read from when the area
   does not publish it itself. Every file the menu writes carries source, table id, verify URL,
   as of, fetched and licence — that is what keeps a figure traceable once it is in a spreadsheet. */
const EC = (typeof window !== "undefined" && window.EXPORT_CORE) || {};
const exBuilt = () => (D.meta && D.meta.built) || "data";
const exSrcList = () => ((D.meta && D.meta.sources) || []).concat((CPH && CPH.meta && CPH.meta.sources) || []);
let EX_CAT = null;
/* the catalogue, keyed exactly the way an indicator's `tables` list names it ("dst/FOLK1A") */
function exCat() { if (!EX_CAT) { EX_CAT = {}; exSrcList().forEach(s => EX_CAT[s.key] = s); } return EX_CAT; }
/* the stamp of one observation: the registry publishes one per level, and one per history year */
function exAsof(i, lvl, year) {
  const pick = x => typeof x === "string" ? x : (x && (x[lvl] || x.kommune || Object.values(x)[0])) || "";
  const h = (year && i.hist_asof && i.hist_asof[year]) || null;
  return String((h ? pick(h) : "") || pick(i.asof) || "").trim();
}
/* every period an indicator has for one area: its history, its projection window, or the one
   snapshot the publisher stamped. An inherited figure is written for the latest period only — the
   municipality's whole series is in the same file already, on its own rows. */
function exPeriods(i, o, lvl, inherited) {
  if (isClim(i.key)) return [];                      /* horizons are a pass of their own */
  const latest = o[i.key];
  if (i.proj) return latest == null ? [] : [{ period: `${i.proj.from}→${i.proj.to}`, kind: "projection", value: latest, asof: exAsof(i, lvl) }];
  const h = (o.hist || {})[i.key] || {};
  const ys = Object.keys(h).filter(y => h[y] != null);
  if (latest == null && !ys.length) return [];
  if (!ys.length) { const stamp = exAsof(i, lvl); return [{ period: stamp || LATEST, kind: "auto", value: latest, asof: stamp }]; }
  const all = [...new Set(latest == null ? ys : ys.concat(LATEST))].sort();
  const out = all.map(y => ({ period: y, kind: "year", value: y === LATEST && latest != null ? latest : h[y], asof: exAsof(i, lvl, y) }))
                 .filter(p => p.value != null);
  return inherited ? out.slice(-1) : out;
}
/* where a figure is read from when the area does not publish it: its municipality, marked
   `value_type=inherited` with `inherited_from` — the rule the tiles and the tables follow (§2.4) */
function exInherited(i, r) {
  if (!r.muni || isClim(i.key)) return null;
  if (r.o[i.key] != null || Object.keys((r.o.hist || {})[i.key] || {}).length) return null;
  return r.muni[i.key] == null ? null : { o: r.muni, code: r.muni.code };
}
/* one <level> block of the long export, from an area-page style entity */
function exEntityLevel(e, code) {
  const lvl = e.type === "kommune" ? "municipality" : e.type === "postnr" ? "postal_code" : "copenhagen_quarter";
  return { level: lvl, asofLevel: e.type, inds: e.inds || IND,
           rows: [{ o: e.o, muni: e.muni || null, code: code || e.code, name: e.name,
                    parent_code: e.muni ? e.muni.code : "", parent_name: e.muni ? e.muni.name : "Denmark",
                    region: e.region || (e.muni || {}).region || "", population: e.o.pop }] };
}
/* the three levels of areas_long: 99 municipalities, 606 postal codes, 67 Copenhagen quarters */
function exLevels() {
  const nm = c => (byCode[String(Number(c || 0))] || {}).name || "";
  const out = [{ level: "municipality", asofLevel: "kommune", inds: IND,
      rows: MUNI.map(m => ({ o: m, code: m.code, name: m.name, parent_code: "", parent_name: "Denmark", region: m.region || "", population: m.pop })) },
    { level: "postal_code", asofLevel: "postnr", inds: IND,
      rows: AREAS.map(a => ({ o: a, muni: byCode[a.muni] || null, code: a.nr, name: a.name, parent_code: a.muni || "",
                              parent_name: nm(a.muni), region: (byCode[a.muni] || {}).region || "", population: a.pop })) }];
  if (CPH) out.push({ level: "copenhagen_quarter", asofLevel: "kvarter", inds: IND_Q,
      rows: CPH.areas.map(q => ({ o: q, muni: byCode[CPH_MUNI] || null, code: q.code, name: q.name,
                                  parent_code: CPH_MUNI, parent_name: nm(CPH_MUNI), region: "Hovedstaden", population: q.pop })) });
  return out;
}
const exCtx = levels => ({ levels, cat: exCat(), built: exBuilt(), periods: exPeriods, inherited: exInherited });
/* the Climate family is published at three horizons, not in years — its own pass, so the period
   column says today / 2070 / 2120 and a future horizon is never labelled `actual` */
function exClimRows(levels) {
  if (!CLIM) return [];
  const out = [];
  levels.forEach(L => (L.inds || []).filter(i => isClim(i.key)).forEach(i => {
    const hs = i.horizon && i.horizon.length ? i.horizon : ["today"];
    L.rows.forEach(r => {
      /* only the zone exposure is published per postal code and per quarter; the Klimaatlas
         figures are the municipality's, and are written as inherited on the finer levels */
      const own = L.level === "municipality" || i.key === "surge_dw_pct";
      const inh = own ? null : (r.muni ? { o: r.muni, code: r.muni.code } : null);
      if (!own && !inh) return;
      hs.forEach(hz => { const v = climValue(own ? r.o : r.muni, i.key, hz);
        if (v == null) return;
        out.push(EC.areaRow({ level: L.level, row: r, ind: i, inherited: inh, cat: exCat(), built: exBuilt(),
          obs: { period: hz, kind: "horizon", horizon: hz, value: v, asof: exAsof(i, "kommune") } })); });
    });
  }));
  return out;
}
const exAreaRows = levels => { const L = levels || exLevels(); return EC.areaRows(exCtx(L)).concat(exClimRows(L)); };
const exProjectRows = () => EC.projectRows(INFRA_ALL.map(f => { const s = geomStats(f), p = f.properties;
  return { p, geometry_kind: p.schematic ? "schematic" : isPt(f) ? "point" : isArea(f) ? "area" : "line",
           length_km: s.km, stations: s.stations, municipalities: p.kommuner || [],
           postal_codes: infraAreas(p.id, "postnr"), quarters: infraAreas(p.id, "kvarter") }; }));
const exNationalRows = () => EC.nationalRows({ series: (D.macro || {}).series, latest: (D.macro || {}).latest, cat: exCat(), built: exBuilt() });
const exSrcCtx = () => ({ sources: exSrcList(), built: exBuilt(), usedFor: x => srcUsedFor(x).text });
const exSourceRecs = () => EC.sourceRecs(exSrcCtx());
/* dwellings inside the published storm-surge extent, per level × horizon. The inline payload keeps
   the municipal share and the zone area; the dwelling counts are published per postal code and per
   quarter, so those two columns are filled there and stay empty for a municipality. */
function exClimateRows() {
  if (!CLIM) return [];
  const ind = indOf("surge_dw_pct") || {}, as_of = exAsof(ind, "kommune"), rows = [];
  (CLIM_HZ || ["today"]).forEach(hz => {
    const z = climZones(hz), base = { horizon: hz, zone_year: CLIM_ZONE_YEAR[hz] || "", as_of };
    MUNI.forEach(m => { const km = climKom(m.code) || {}, pct = (km.surge_dw_pct || {})[hz], km2 = (z.kommune || {})[pad4(m.code)];
      if (pct == null && km2 == null) return;
      rows.push({ ...base, level: "municipality", code: m.code, name: m.name, parent_name: "Denmark", pct, zone_km2: km2 }); });
    Object.keys(z.postnr || {}).forEach(nr => { const e = z.postnr[nr], a = byNr[nr] || {}, m = byCode[a.muni] || {};
      rows.push({ ...base, level: "postal_code", code: nr, name: a.name || "", parent_code: a.muni || "", parent_name: m.name || "",
                  dwellings: e.dwellings, in_zone: e.dwellings_in_zone, pct: e.surge_dw_pct }); });
    Object.keys(z.kvarter || {}).forEach(c => { const e = z.kvarter[c], q = byQ[c] || {};
      rows.push({ ...base, level: "copenhagen_quarter", code: c, name: q.name || "", parent_code: CPH_MUNI,
                  parent_name: (byCode[CPH_MUNI] || {}).name || "", dwellings: e.dwellings, in_zone: e.dwellings_in_zone, pct: e.surge_dw_pct }); });
  });
  return EC.climateRows({ rows, ind, cat: exCat(), built: exBuilt() });
}
/* the test property (spec §5.5′): the pin's three columns in front of every figure its quarter,
   its postal code and its municipality publish — and a second file for what lies near it */
function exPinLevels(r) {
  const out = [];
  if (r.kommune) out.push(exEntityLevel({ type: "kommune", o: r.kommune, name: r.kommune.name, region: r.kommune.region, inds: IND }, r.kommune.code));
  if (r.postnr) out.push(exEntityLevel({ type: "postnr", o: r.postnr, name: r.postnr.name, inds: IND, muni: byCode[r.postnr.muni] || null }, r.postnr.nr));
  if (r.kvarter) out.push(exEntityLevel({ type: "kvarter", o: r.kvarter, name: r.kvarter.name, region: "Hovedstaden", inds: IND_Q, muni: byCode[CPH_MUNI] || null }, r.kvarter.code));
  return out;
}
function exNearbyRows(pt, r) {
  const list = [], ring = anRing();
  const bbrUrl = ((indOf("renters_bbr") || {}).src_page || [])[1] || "";
  anInfraRows(pt).forEach(x => list.push({ kind: "infra", name: x.p.name, type: INFRA_TYPE[x.p.type] || x.p.type,
    status: `${infraSt(x.p).label}${x.p.open_year || x.p.open_window ? " · opening " + openLabel(x.p) : ""}`,
    distance_m: x.d, source: x.p.source_doc || "Curated infrastructure layer (docs/INFRA.md)", source_url: x.p.source_url || "" }));
  const koms = anPubKoms(pt, r);
  koms.flatMap(k => ((PUB_FILES[k] || {}).buildings || [])).map(b => ({ b, d: havM(pt.lat, pt.lon, b.lat, b.lon) }))
    .filter(x => x.d <= ring && (x.b.kind === "existing" || x.b.recent)).sort((a, b) => a.d - b.d)
    .forEach(x => list.push({ kind: "public", name: pubName(x.b), type: `${x.b.code} ${x.b.label}`,
      status: x.b.kind === "existing" ? `existing${x.b.year ? " " + x.b.year : ""}` : `open case${x.b.permit ? " " + x.b.permit : ""}`,
      distance_m: x.d, source: `BBR via Datafordeler, ${(PUB && PUB.built) || exBuilt()}`, source_url: bbrUrl }));
  ((SCHOOLS || {}).schools || []).filter(s => koms.includes(s.kom) && s.lat != null)
    .map(s => ({ s, d: havM(pt.lat, pt.lon, s.lat, s.lon) })).filter(x => x.d <= ring).sort((a, b) => a.d - b.d)
    .forEach(x => list.push({ kind: "school", name: x.s.name, type: SCH_TYPE[x.s.type] || x.s.type,
      status: `FP9 ${schV(x.s, "grade_avg") ?? "not published"} · ${schY(x.s, "grade_avg") || SCH_LATEST}`,
      distance_m: x.d, source: `Uddannelsesstatistik.dk (STIL), retrieved ${(SCH_META || {}).retrieved || ""}`,
      source_url: "https://uddannelsesstatistik.dk/" }));
  return EC.nearbyRows(list);
}
/* the lazy files (public buildings, schools) arrive on demand, so an export waits for the ones its
   file needs rather than writing a short file the reader cannot tell is short */
function exWait(done, ms) {
  return new Promise(res => { const t0 = Date.now();
    (function tick() { if (done() || Date.now() - t0 > (ms || 6000)) return res(); setTimeout(tick, 120); })(); });
}
function exportProperty() {
  const pt = anLoc(); if (!pt) return exToast("Test property", 0, "no pin yet — paste a Google Maps link first");
  const r = anRes(); if (!r || r.error) return exToast("Test property", 0, (r && r.error) || "the pin is not located yet");
  const label = AN.label || TP_LABEL, lead = [label, pt.lat, pt.lon], levels = exPinLevels(r);
  const rows = EC.propertyRows({ ...exCtx(levels), label, lat: pt.lat, lon: pt.lon })
    .concat(exClimRows(levels).map(x => lead.concat(x)));
  exSave("test_property", EC.PROP_COLS, rows, `${esc(label)} · ${levels.length} level${levels.length === 1 ? "" : "s"}`);
  const koms = anPubKoms(pt, r);
  koms.forEach(pubLoad); schoolsLoad();
  exWait(() => koms.every(k => PUB_FILES[k] || PUB_FILES["_error_" + k]) && (!SCH_META || SCHOOLS))
    .then(() => exSave("test_property_nearby", EC.NEARBY_COLS, exNearbyRows(pt, r),
      `within ${nf(anRing(), 0)} m · projects within ${nf(AN_INFRA_M / 1000, 0)} km`));
}
/* "This view" is whatever is on screen: the wide Areas table, one area's figures, the plotted
   series, or the test property (spec §4.9) */
const EX_VIEW = () => S.view === "analysis" ? "the test property" : S.view === "charts" ? "the plotted series"
  : S.view === "area" ? "this area, long" : `${T.level === "kvarter" ? "Copenhagen quarters" : T.level === "postnr" ? "postal codes" : "municipalities"}, wide`;
function exportView() {
  if (S.view === "analysis") return exportProperty();
  if (S.view === "charts") return exportChartRows();
  if (S.view === "area") { const e = areaEntity();
    if (e) return exSave(`area_${e.type}_${e.code}`, EC.AREA_COLS, exAreaRows([exEntityLevel(e)]), e.name); }
  return exportWide();
}
/* the wide table keeps each column's provenance in its own header — a wide file has nowhere else to
   put it, and a number without its source is not a figure this dashboard ships */
function exWideHead(i) {
  const u = EC.unitValue(i, null).unit, asof = exAsof(i, T.level) || exBuilt();
  return `${i.key}${u ? ` (${u})` : ""} · ${EC.indSource(i, { cat: exCat(), built: exBuilt(), asof }).table_id} · as of ${asof}`;
}
function exportWide() {
  const lvl = T.level, cols = tableCols(true), rows = tableRows();
  const head = [lvl === "kvarter" ? "quarter" : lvl === "postnr" ? "area" : "municipality",
                lvl === "postnr" ? "postal_code" : "code",
                lvl === "kvarter" ? "district" : lvl === "postnr" ? "municipality" : "region",
                "population"].concat(cols.map(exWideHead));
  const out = rows.map(r => { const m = lvl === "postnr" ? (byCode[r.muni] || {}) : r;
    return [r.name, lvl === "postnr" ? r.nr : r.code,
            lvl === "kvarter" ? (r.bydel || "") : lvl === "postnr" ? (m.name || "") : (r.region || ""), r.pop]
      .concat(cols.map(i => { const own = V(r, i.key);
        const v = own != null ? own : lvl === "postnr" ? V(m, i.key) : lvl === "kvarter" && !cphOwn(i.key) ? V(byCode[CPH_MUNI], i.key) : null;
        return EC.unitValue(i, v).value; })); });
  return exSave(`areas_${lvl}_${MK.year}`, head, out, `${cols.length} indicators · wide`);
}
function exportChartRows() {
  const inds = chartInds();
  const levels = CH.areas.map(id => { const e = chEntity(id); return e ? exEntityLevel({ ...e, inds }, id.split(":")[1]) : null; }).filter(Boolean);
  if (!levels.length) return exToast("Chart", 0, "add an area first");
  return exSave(`chart_${chartInd().key}`, EC.AREA_COLS, exAreaRows(levels),
    `${levels.length} area${levels.length === 1 ? "" : "s"} · ${inds.length} indicator${inds.length === 1 ? "" : "s"}`);
}
/* the menu: one component, rendered in the sidebar footer, in the Data header and in the test
   property's header (spec §4.9). Every item downloads at once and says what it wrote. */
const EX_ITEMS = [["view", "This view", EX_VIEW],
                  ["areas", "All area data", () => "long · municipalities, postal codes, quarters"],
                  ["projects", "Projects", () => `${INFRA_ALL.length} projects · own schema`],
                  ["national", "National series", () => `${Object.keys((D.macro || {}).latest || {}).length} series · long`],
                  ["sources", "Sources catalogue", () => `${exSrcList().length} sources · what Data › Sources shows`],
                  ["climate", "Climate exposure", () => "dwellings in the surge zone · 3 horizons"],
                  ["property", "Test property", () => anLoc() ? "the pin's figures + what is near it" : "no pin yet"]];
const exAvail = k => k === "property" ? !!anLoc() : k === "climate" ? !!CLIM : true;
function exportMenu(at) {
  const open = UI.xOpen === at;
  return `<div class="xwrap${open ? " open" : ""}" data-xat="${at}">
    <button type="button" class="xbtn" data-testid="export-btn" data-xpop aria-expanded="${open}" aria-haspopup="dialog"
      title="Download what is on screen, or any dataset, with its sources">⤓ Export<em aria-hidden="true">▾</em></button>
    <div class="xpop" data-testid="export-menu" role="dialog" aria-label="Export data" ${open ? "" : "hidden"}>
      <div class="lay-h">Download as CSV</div>
      ${EX_ITEMS.map(([k, label, sub]) => `<button type="button" class="xitem" data-export="${k}"${exAvail(k) ? "" : " disabled"}>
        <b>${esc(label)}</b><span>${esc(sub())}</span></button>`).join("")}
      <p class="laynote">Every row carries its source, table id, as of and licence. Semicolon separated, <code>.</code> decimals, UTF-8 with BOM — Danish Excel opens it by double-click.</p>
    </div></div>`;
}
function xPopOpen(at, refocus) {
  const was = UI.xOpen;
  UI.xOpen = at || "";
  document.querySelectorAll(".xwrap").forEach(w => { const on = w.dataset.xat === UI.xOpen;
    w.classList.toggle("open", on);
    const b = w.querySelector("[data-testid=export-btn]"), p = w.querySelector("[data-testid=export-menu]");
    if (p) p.hidden = !on;
    if (b) { b.setAttribute("aria-expanded", on ? "true" : "false"); if (!on && refocus && w.dataset.xat === was) b.focus(); } });
}
/* the sidebar footer: the same menu, then what this build is (spec §4.1) */
const APP_VERSION = "v3.0";
function renderFoot() {
  const el = document.getElementById("xfoot"); if (!el) return;
  el.innerHTML = `${exportMenu("side")}<div class="xcap">built ${esc(exBuilt())} · ${APP_VERSION}</div>`;
}
let EX_T = 0;
/* one line, never a modal: what was written and how much of it (spec §4.9) */
function exToast(name, n, extra) {
  let el = document.getElementById("xtoast");
  if (!el) { el = document.createElement("div"); el.id = "xtoast"; el.className = "xtoast";
    el.setAttribute("data-testid", "export-toast"); el.setAttribute("role", "status"); document.body.appendChild(el); }
  el.innerHTML = `<b>${esc(name)}</b><span>${nf(n, 0)} row${n === 1 ? "" : "s"}${extra ? " · " + extra : ""}</span>`;
  el.classList.add("on");
  clearTimeout(EX_T); EX_T = setTimeout(() => { const t = document.getElementById("xtoast"); if (t) t.classList.remove("on"); }, 7000);
}
function exSave(stem, cols, rows, extra) {
  const name = EC.fileName(stem, exBuilt());
  downloadCsv(EC.csvLines(cols, rows), name);
  exToast(name, rows.length, extra);
  return rows.length;
}
function exportGo(kind) {
  xPopOpen("");
  if (kind === "view") return exportView();
  if (kind === "areas") return exSave("areas_long", EC.AREA_COLS, exAreaRows(), "3 levels · every published period");
  if (kind === "projects") return exSave("projects", EC.PROJECT_COLS, exProjectRows(), "Fingerplan, Anlægsstatus, agency documents");
  if (kind === "national") return exSave("national_series", EC.AREA_COLS, exNationalRows(), "Denmark · month, quarter or year");
  if (kind === "sources") return exSave("sources", EC.SOURCE_COLS, EC.sourceRows(exSrcCtx()), "publisher, tables, as of, licence");
  if (kind === "climate") return exSave("climate_exposure", EC.CLIMATE_COLS, exClimateRows(), "Kystdirektoratet 100-year extents × BBR");
  if (kind === "property") return exportProperty();
}

/* ---------- Area page (municipality · postal code · Copenhagen quarter) ---------- */
function areaEntity() {
  if (AR.type === "kommune") {
    const m = byCode[AR.code]; if (!m) return null;
    const isCph = CPH && m.code === CPH_MUNI;
    return { type: "kommune", typeLabel: "Municipality", o: m, name: m.name, code: m.code, muni: null, region: m.region, inds: IND, peers: MUNI, peerLabel: "municipalities",
             ctx: AREAS.filter(a => a.muni === m.code), own: AREAS.filter(a => a.muni === m.code), subs: isCph ? { kvarter: CPH.areas, postnr: AREAS.filter(a => a.muni === m.code) } : { postnr: AREAS.filter(a => a.muni === m.code) } };
  }
  if (AR.type === "postnr") {
    const a = byNr[AR.code]; if (!a) return null; const m = byCode[a.muni];
    return { type: "postnr", typeLabel: "Postal-code area", o: a, name: `${a.nr} ${a.name}`, code: a.nr, muni: m, region: m && m.region, inds: IND, peers: AREAS, peerLabel: "postal codes",
             ctx: AREAS.filter(x => x.muni === a.muni), own: [a], subs: null };
  }
  if (AR.type === "kvarter" && CPH) {
    const q = byQ[AR.code]; if (!q) return null; const m = byCode[CPH_MUNI];
    return { type: "kvarter", typeLabel: "Copenhagen quarter", o: q, name: q.name, code: q.code, muni: m, region: m && m.region, bydel: q.bydel, inds: IND_Q, peers: CPH.areas, peerLabel: "quarters",
             ctx: CPH.areas, own: [q], subs: null };
  }
  return null;
}
/* value for the entity: its own figure, or the municipality's (inherited, °) for postal codes — and for quarters
   on indicators the quarter layer does not have (Safety) */
const inherits = (e, k) => !!e.muni && (e.type === "postnr" || (e.type === "kvarter" && !cphOwn(k)));
function eVal(e, k, y) { const own = V(e.o, k, y); if (own != null) return { v: own, own: true }; if (inherits(e, k)) { const mv = V(e.muni, k, y); if (mv != null) return { v: mv, own: false }; } return { v: null, own: false }; }
/* the pool a figure belongs to: the areas of the page's own level, or the municipalities when the
   value on screen is the municipality's. Comparing a municipal figure against the median of 606
   postal codes that do not publish it is a comparison of nothing. */
const ePeers = (e, k) => (inherits(e, k) && V(e.o, k) == null) ? MUNI : e.peers;
const ePeerLabel = (e, k) => ePeers(e, k) === MUNI && e.type !== "kommune" ? "municipalities" : e.peerLabel;
function eYears(e, k) { return histYears(k, ePeers(e, k)); }
/* everything a tile, headline cell or popup needs about one indicator for one area */
function tileStats(e, i) {
  const cur = eVal(e, i.key); if (cur.v == null) return null;
  const ys = eYears(e, i.key), y0 = ys[0], pool = ePeers(e, i.key);
  const own = ys.map(y => eVal(e, i.key, y).v), med = ys.map(y => median(pool.map(p => V(p, i.key, y))));
  const dlt = (a, b) => a == null || b == null ? null : isPct(i) ? b - a : (a ? (b / a - 1) * 100 : null);
  const unit = isPct(i) ? " pp" : " %";
  const li = own.map((v, k) => v == null ? -1 : k).filter(k => k >= 0).pop(); const idx = MK.year === LATEST ? li : ys.indexOf(MK.year);
  const yoy = idx > 0 ? dlt(own[idx - 1], own[idx]) : null;
  const since = y0 && y0 !== MK.year ? dlt(own[0], cur.v) : null;
  const vsMed = dlt(median(pool.map(p => V(p, i.key))), cur.v);
  /* an inherited figure is not this area's, so it is never given this area's rank (spec §4.7) */
  const rk = cur.own ? rankOf(e.o, i.key, e.peers) : null;
  return { cur, ys, y0, own, med, yoy, since, vsMed, rk, unit };
}
/* ---------- HeadlineTiles (spec §4.7) ----------
   One tile: mono label, the figure, and a subline that is either `Δ y/y · #n of N` or — when the
   figure is the municipality's and not the area's own — the words that say so. Never a lone `°`
   (spec §1 decision 7, §2.4). Clicking a tile selects that indicator in the picker, which is why
   the tile is a real <button> carrying the picker's own `data-ind`. */
function tileHtml(e, i) {
  const s = tileStats(e, i); if (!s) return "";
  const inh = !s.cur.own;
  const sub = inh
    ? `<span class="inhlab">municipality figure</span>`
    : [s.yoy != null ? `<i class="${cls(s.yoy, i.key)}">${sign(s.yoy, x => nf(x, 1))}${s.unit}</i> y/y` : "",
       rankHtml(s.rk, e.peerLabel)]
      .filter(Boolean).join(" · ");
  return `<button type="button" class="hltile${i.key === MK.ind ? " on" : ""}${inh ? " inh" : ""}"
      data-testid="tile-${esc(i.key)}" data-ind="${esc(i.key)}"
      title="${esc(i.desc || i.label)}${inh ? ` — ${esc((e.muni || {}).name || "the municipality")}'s figure` : ""} — click to read it in the chart and on the map">
    <span class="tl">${esc(i.short || i.label)}${!inh && e.type === "kvarter" ? bydelMark(i) : ""}</span>
    <b class="${i.proj ? "proj" : ""}${inh ? " inh" : ""}">${projValueHtml(i, s.cur.v, e.o, e.type)}</b>
    <em>${sub}${smallBaseTag(i, e.o, e.type)}</em>${i.proj ? `<span class="tag proj tpill">Projection</span>` : ""}</button>`;
}
/* the five figures that answer "what kind of area is this". `opts.bare` leaves the test id off, for
   the copies that live inside a Leaflet popup — there is one `tiles` per page, not one per marker. */
function headlineHtml(e, opts) {
  const inds = HL_KEYS.map(k => e.inds.find(i => i.key === k)).filter(i => i && eVal(e, i.key).v != null).slice(0, 5);
  if (!inds.length) return "";
  return `<div class="tiles"${(opts || {}).bare ? "" : ` data-testid="tiles"`}>${inds.map(i => tileHtml(e, i)).join("")}</div>`;
}
/* §5.7 detail sheets: the same tile row as §4.7, without the picker behaviour — a sheet's tiles are
   facts about the thing on the page, not indicator switches. `[label, value, sub]`; a slot with no
   value is **not rendered**, which is what removes the grey slab a missing figure used to leave
   behind (AC-SH1). `value` and `sub` are markup (a suppressed figure, a rank span), so a caller
   passing data escapes it; `label` is text. `.tiles.wrap` is auto-fit, so the last row has no empty
   cell either. */
function sheetTiles(items) {
  const cells = (items || []).filter(t => t && t[1] != null && t[1] !== "")
    .map(([l, v, sub]) => `<div class="hltile"><span class="tl">${esc(l)}</span><b>${v}</b>${sub ? `<em>${sub}</em>` : ""}</div>`);
  return cells.length ? `<div class="tiles wrap" data-testid="tiles">${cells.join("")}</div>` : "";
}
/* §4.10 empty / loading / error: mono caption, one action, never a modal or a bare spinner. */
function stateCard(kind, title, note, action) {
  return `<div class="statecard" data-kind="${esc(kind)}" data-testid="state-${esc(kind)}"${kind === "loading" ? ` role="status" aria-live="polite"` : ""}>
    <b>${esc(title)}</b>${note ? `<p>${esc(note)}</p>` : ""}
    ${kind === "loading" ? `<span class="skel" aria-hidden="true"><i></i><i></i><i></i></span>` : ""}${action || ""}</div>`;
}
function multiLine(series, ind, ys) {
  const all = series.flatMap(s => s.pts.map(p => p.v)).filter(v => v != null);
  if (!all.length || ys.length < 2) return `<p class="empty">no history for this indicator</p>`;
  const W = 900, H = 240, L0 = 78, R = 16, T0 = 14, B = 26;
  const lo = Math.min(...all), hi = Math.max(...all), sp = (hi - lo) || 1;
  const x = i => L0 + i / (ys.length - 1) * (W - L0 - R), y = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const ticks = [lo, lo + sp / 2, hi];
  const paths = series.map(s => { const pts = s.pts.map((p, i) => p.v == null ? null : `${x(i).toFixed(1)},${y(p.v).toFixed(1)}`); let d = "", open = false;
    pts.forEach(p => { if (!p) { open = false; return; } d += (open ? "L" : "M") + p; open = true; });
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.w || 2}" ${s.dash ? 'stroke-dasharray="5 4"' : ""}/>` + s.pts.map((p, i) => p.v == null ? "" : `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${s.w ? 3 : 2.4}" fill="${s.color}"><title>${esc(s.name)} ${p.y}: ${fmtOf(ind)(p.v)}</title></circle>`).join(""); }).join("");
  const si = ys.indexOf(MK.year); const selX = si >= 0 ? `<line x1="${x(si).toFixed(1)}" x2="${x(si).toFixed(1)}" y1="${T0}" y2="${H - B}" class="splitline"/>` : "";
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
      ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(y(t) + 3).toFixed(1)}" text-anchor="end">${fmtTight(ind)(t)}</text>`).join("")}
      ${ys.map((yy, i) => `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${yy}</text>`).join("")}
      ${selX}${paths}</svg>
    <div class="bleg">${series.map(s => { const last = [...s.pts].reverse().find(p => p.v != null); return `<span><i style="background:${s.color}${s.dash ? ";height:2px" : ""}"></i>${esc(s.name)}${last ? ` <b>${fmtOf(ind)(last.v)}</b> <span class="dim">${last.y}</span>` : ""}</span>`; }).join("")}</div>`;
}
/* ---------- Population outlook chart (docs/FORECAST.md §5.6) ----------
   Two series, never one: the observed population (FOLK1A for kommuner, KKBEF1 for kvarterer) as a
   solid line, and the projection (FRKM / KKFR) as a dashed one that starts at the last observed
   year. A vertical marker separates them, the card carries a "Projection" badge, and every
   projected point says so in its own tooltip — a projected point must never read as an actual. */
const AGE_LABELS = { a0_5: "0–5", a6_16: "6–16", a17_19: "17–19", a20_34: "20–34", a35_64: "35–64", a65_79: "65–79", a80p: "80+" };
function popOutlookChart(o, opts) {
  const hist = o.pop_hist || {}, proj = o.fc_pop || {};
  const group = opts && opts.group;
  const gh = null, gp = o.fc_groups || {};
  const hy = Object.keys(hist).sort(), py = Object.keys(proj).sort();
  if (!py.length) return "";
  const cut = hy.length ? hy[hy.length - 1] : py[0];     /* the last observed year — the join */
  const ys = [...new Set(hy.concat(py))].sort();
  const av = y => group ? null : (hist[y] != null ? hist[y] : null);
  const pv = y => group ? ((gp[y] || {})[group] ?? null) : (proj[y] != null ? proj[y] : null);
  const vals = ys.map(y => av(y) ?? pv(y)).filter(v => v != null);
  if (vals.length < 2) return "";
  const W = 900, H = 236, L0 = 78, R = 16, T0 = 16, B = 26;
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals), pad = (hi0 - lo0) * .08 || 1;
  const lo = Math.max(0, lo0 - pad), hi = hi0 + pad, sp = (hi - lo) || 1;
  const x = y => L0 + ys.indexOf(y) / (ys.length - 1) * (W - L0 - R);
  const yy = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const fmtN = v => nf(Math.round(v), 0);
  const line = (getter, from, cls_, dash) => {
    let d = "", open = false, dots = "";
    ys.forEach(y => {
      if (from && y < from) { open = false; return; }
      const v = getter(y);
      if (v == null) { open = false; return; }
      d += (open ? "L" : "M") + `${x(y).toFixed(1)},${yy(v).toFixed(1)}`; open = true;
      dots += `<circle cx="${x(y).toFixed(1)}" cy="${yy(v).toFixed(1)}" r="${dash ? 2.2 : 2.6}" fill="${cls_}"><title>${y}: ${fmtN(v)}${dash ? " — projected" : ""}</title></circle>`;
    });
    return `<path d="${d}" fill="none" stroke="${cls_}" stroke-width="${dash ? 2.2 : 2.6}"${dash ? ' stroke-dasharray="6 4"' : ""}/>${dots}`;
  };
  const ticks = [lo, lo + sp / 2, hi];
  const every = ys.length > 14 ? 2 : 1;
  const cutX = x(cut).toFixed(1);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${yy(t).toFixed(1)}" y2="${yy(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(yy(t) + 3).toFixed(1)}" text-anchor="end">${fmtN(t)}</text>`).join("")}
    ${ys.map((y, i) => i % every ? "" : `<text class="ax" x="${x(y).toFixed(1)}" y="${H - 8}" text-anchor="middle">${y}</text>`).join("")}
    <line class="splitline" x1="${cutX}" x2="${cutX}" y1="${T0}" y2="${H - B}"/>
    <text class="ax projmark" x="${cutX}" y="${T0 - 4}" text-anchor="middle">${cut} · today</text>
    ${group ? "" : line(av, null, "#1C6B5C", false)}
    ${line(pv, cut, "#5A3C96", true)}
  </svg>
  <div class="bleg">${group ? "" : `<span><i style="background:#1C6B5C"></i>Observed${opts && opts.actualSource ? ` <span class="dim">${esc(opts.actualSource)}</span>` : ""} <b>${hist[cut] != null ? fmtN(hist[cut]) : "–"}</b> <span class="dim">${cut}</span></span>`}
    <span><i style="background:#5A3C96;height:2px"></i>Projected${opts && opts.projSource ? ` <span class="dim">${esc(opts.projSource)}</span>` : ""} <b>${pv(py[py.length - 1]) != null ? fmtN(pv(py[py.length - 1])) : "–"}</b> <span class="dim">${py[py.length - 1]}</span></span></div>`;
}
/* The Population outlook section (spec §5.2): the population chart, the age-group split, the
   projection's own caveat and — on Copenhagen quarters only — the single past-accuracy line of §9.7.
   Nothing else from §9. The card head is the <details> summary now, so this is the body only. */
function outlookBody(e) {
  const o = e.o;
  if (!o || !o.fc_pop) return "";
  const isQ = e.type === "kvarter";
  const list = isQ ? IND_CPH : IND;
  const g = list.find(i => i.key === "fc_growth");
  const pr = (g && g.proj) || {};
  const who = pr.publisher || "DST";
  const actualSrc = isQ ? "KKBEF1" : "FOLK1A";
  const tiles = ["fc_growth", "fc_20_34_rel", "fc_0_5", "fc_80p", "fc_pop_rate_5y"]
    .map(k => list.find(i => i.key === k)).filter(i => i && o[i.key] != null).slice(0, 5);
  const ageRows = ["a0_5", "a6_16", "a20_34", "a80p"].map(gk => {
    const a = (o.fc_groups || {})[pr.from || "2026"], b = (o.fc_groups || {})[pr.to || "2040"];
    if (!a || !b || a[gk] == null || !a[gk]) return "";
    const pct = (b[gk] - a[gk]) / a[gk] * 100;
    return `<div><span>${esc(AGE_LABELS[gk] || gk)}</span><b>${nf(b[gk] - a[gk], 0)}</b><em>${sign(pct, x => nf(x, 1))} %</em></div>`;
  }).join("");
  return `${projChangeLine(o, isQ ? "kvarter" : "kommune") ? `<p class="olchg big">${projChangeLine(o, isQ ? "kvarter" : "kommune")}</p>` : ""}
    ${popOutlookChart(o, { actualSource: actualSrc, projSource: pr.table || who })}
    <p class="cap srcrow">${srcLink(pr.src, srcCode(o, isQ ? "kvarter" : "kommune"), "Verify the projection at source")}
      ${srcLink(pr.actuals, srcCode(o, isQ ? "kvarter" : "kommune"), "Verify the observed population")}</p>
    ${tiles.length ? `<div class="tiles wrap">${tiles.map(i => `<button type="button" class="hltile ${MK.ind === i.key ? "on" : ""}" data-ind="${esc(i.key)}" title="${esc(i.desc || i.label)}">
      <span class="tl">${esc(i.short || i.label)}</span><b class="proj">${projValueHtml(i, o[i.key], o, isQ ? "kvarter" : "kommune")}</b><em class="dim">${i.key === "fc_20_34_rel" ? esc(relLabel(i)) : esc(i.unit || "")}${smallBaseTag(i, o, isQ ? "kvarter" : "kommune")}</em></button>`).join("")}</div>` : ""}
    ${ageRows ? `<div class="olages"><span class="lfsec">Age groups ${esc(pr.from || "")}→${esc(pr.to || "")} · persons</span><div class="mstrip-k">${ageRows}</div></div>` : ""}
    ${isQ ? pastAccuracyLine(o) : ""}
    ${isQ ? cphFcCaveat("kvarter") : `<p class="cap">${esc((g && g.warn) || "")}</p>`}
    <p class="cap dim">Observed population from ${esc(actualSrc)}; projection from ${esc(pr.table || "")}, ${esc(who)}. Two different series — the dashed line is a scenario, not a measurement, and the two are never spliced into one.</p>`;
}
/* the projection window a Population outlook section is showing, for its summary line */
function projSpan(e) {
  const g = (e.type === "kvarter" ? IND_CPH : IND).find(i => i.key === "fc_growth");
  const pr = (g && g.proj) || {};
  return `${pr.from || ""}→${pr.to || ""} · ${pr.publisher || "DST"} ${pr.vintage || ""}${pr.table ? " · " + pr.table : ""}`.trim();
}
/* the history line of the chart panel: this area solid, its municipality solid, the peer median
   dashed, and — on a municipality page — Denmark dashed green (spec §5.2) */
function areaChart(e, ind) {
  const ys = eYears(e, ind.key), pool = ePeers(e, ind.key);
  const series = [{ name: e.name, color: "#1C6B5C", w: 2.6, pts: ys.map(y => ({ y, v: eVal(e, ind.key, y).v })) }];
  if (muniCmp(e, ind.key) && V(e.o, ind.key) != null) series.push({ name: e.muni.name, color: "#B07A1E", pts: ys.map(y => ({ y, v: V(e.muni, ind.key, y) })) });
  const medLabel = pool === MUNI ? "Denmark, median of municipalities" : e.type === "kvarter" ? "Copenhagen, median of quarters" : "Denmark, median of postal codes";
  series.push({ name: medLabel, color: "#5C5F52", dash: true, pts: ys.map(y => ({ y, v: median(pool.map(p => V(p, ind.key, y))) })) });
  /* the national figure is published for the country, not computed from the 99 — it is a second
     reference beside the median, and only where the publisher has one */
  if (e.type === "kommune" && NAT && (NAT[ind.key] != null || (NAT.hist && NAT.hist[ind.key])))
    series.push({ name: "Denmark (national figure)", color: "#2F6B4A", dash: true, pts: ys.map(y => ({ y, v: V(NAT, ind.key, y) })) });
  return multiLine(series, ind, ys);
}
function areaCompareTable(e, gap) {
  const ind = curInd(), medLabel = e.type === "kommune" ? "DK median" : e.type === "kvarter" ? "CPH median" : "DK median (postal codes)";
  return `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Indicator</th><th class="num">${esc(e.type === "kommune" ? e.name : e.type === "kvarter" ? "Quarter" : "Postal code")}</th>${e.muni ? `<th class="num">${esc(e.muni.name)}</th>` : ""}<th class="num">${medLabel}</th><th class="num">Rank</th><th class="num">Δ since first year</th><th>As of</th></tr></thead>
    <tbody>${e.inds.map(i => { const cur = eVal(e, i.key); if (cur.v == null) return "";
      const ys = eYears(e, i.key), y0 = ys[0]; const first = y0 && y0 !== MK.year ? eVal(e, i.key, y0).v : null;
      const d = first == null ? null : isPct(i) ? cur.v - first : (first ? (cur.v / first - 1) * 100 : null);
      const rk = cur.own ? rankOf(e.o, i.key, e.peers) : null; const med = median(e.peers.map(p => V(p, i.key)));
      return `<tr class="clickrow${i.key === ind.key ? " hi on" : ""}${cur.own ? "" : " inh"}${i.proj ? " proj" : ""}" data-ind="${esc(i.key)}"><th><span class="thn">${esc(indLabel(i, gap))} <span class="dim">${esc(i.unit || "")}</span></span>${cur.own ? "" : `<span class="tag-muni" title="the municipality's figure, shown at this level">muni</span>`}${i.proj ? `<span class="tag proj">Projection</span>` : ""}<button class="tch" data-go="${chartLink(i.key, e.type, e.code)}" title="Open in Charts">↗</button></th>
        ${fmtCell(i, cur.v, false, e.type === "kvarter" && cur.own ? bydelMark(i) : "")}${e.muni ? (muniCmp(e, i.key) ? fmtCell(i, V(e.muni, i.key), false) : `<td class="num" title="different definition at municipality level">${NC}</td>`) : ""}${fmtCell(i, med, false)}
        <td class="num" data-v="${rk ? rk.r : ""}">${rk ? rankHtml(rk, ePeerLabel(e, i.key)) : (cur.own ? DASH : NC)}</td>
        <td class="num ${goodBad(d, i.key)}" data-v="${d ?? ""}">${d != null ? sign(d, x => nf(x, 1)) + (isPct(i) ? " pp" : " %") + ` <span class="dim">(${y0})</span>` : "–"}</td>
        <td class="dim">${asofText(i)}</td></tr>`; }).join("")}</tbody></table></div>`;
}
/* ENG_BRIEF §3.4 — two different definitions of "dwellings built 2010+": KK counts the dwelling's
   own commissioning year, our BBR pull the building's original construction year, so a converted
   brewery reads 2010+ in one and 1900s in the other. Where the two disagree by more than 15 pp on a
   quarter, the labels say which is which and a caveat says why. Labels only — no data is changed. */
const NEWSTOCK_GAP_PP = 15;
const NEWSTOCK_LABEL = { new_stock: "Dwellings commissioned 2010+ (KK, dwelling)",
                         new_stock_bbr: "Dwellings in buildings built 2010+ (BBR, building year)" };
function newStockGap(e) {
  if (!e || e.type !== "kvarter") return null;
  const a = V(e.o, "new_stock"), b = V(e.o, "new_stock_bbr");
  if (a == null || b == null || Math.abs(a - b) <= NEWSTOCK_GAP_PP) return null;
  return { kk: a, bbr: b, pp: a - b };
}
const indLabel = (i, gap) => (gap && NEWSTOCK_LABEL[i.key]) || i.label;
function newStockNote(e, gap) {
  if (!gap) return "";
  return `<p class="cap warnline" data-testid="newstock-note">⚠ The two "built 2010+" shares differ by
    ${nf(Math.abs(gap.pp), 1)} pp here (KK ${nf(gap.kk, 1)} %, BBR ${nf(gap.bbr, 1)} %). They count different things:
    Københavns Kommune records the <b>dwelling's</b> year of commissioning, our BBR pull the <b>building's</b>
    original construction year — so a dwelling created inside an older building counts as new in one and not in
    the other. Both are published as they stand; neither is corrected here.</p>`;
}
function areaSubTable(e) {
  if (!e.subs) return "";
  const keys = Object.keys(e.subs); const sub = keys.includes(AR.sub) ? AR.sub : keys[0]; const list = e.subs[sub];
  const cols = sub === "kvarter" ? IND_CPH : IND.filter(i => i.level === "postnr");
  const ind = cols.find(i => i.key === MK.ind) || cols[0];
  const pool = sub === "kvarter" ? CPH.areas : AREAS, y0 = yearsForPool(ind.key, pool)[0];
  const rows = list.slice().sort((a, b) => (V(b, ind.key) ?? -1e9) - (V(a, ind.key) ?? -1e9));
  return `<div class="tfilters">${keys.length > 1 ? `<div class="seg">${keys.map(k => `<button class="sg ${k === sub ? "on" : ""}" data-arsub="${k}">${k === "kvarter" ? `Quarters (${e.subs[k].length})` : `Postal codes (${e.subs[k].length})`}</button>`).join("")}</div>` : ""}<span class="hint">sorted by ${esc(ind.label.toLowerCase())} · click a row for its page, ↗ to chart it</span></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th>${sub === "kvarter" ? "Quarter" : "Area"}</th><th>${sub === "kvarter" ? "District" : "Postal code"}</th><th class="num">Population</th>
      <th class="num hi">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${isPct(ind) ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
    <tbody>${rows.map(a => `<tr class="clickrow" data-go="${withQ(pageOf(a))}"><th><span class="thn">${esc(a.name)} <span class="go">›</span></span><button class="tch" data-go="${chartLink(ind.key, sub, sub === "kvarter" ? a.code : a.nr)}" title="Open in Charts">↗</button></th><td class="dim">${esc(sub === "kvarter" ? a.bydel || "" : a.nr)}</td><td class="num dim" data-v="${a.pop || 0}">${a.pop != null ? nf(a.pop, 0) : "–"}</td>
      ${fmtCell(ind, V(a, ind.key), false)}${y0 && y0 !== MK.year ? deltaCell(a, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(i => fmtCell(i, V(a, i.key), false)).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="cap">${sub === "kvarter" ? `${list.length} quarters (kvarterer). ${esc((CPH.meta && CPH.meta.attribution) || "")}` : `${list.length} postal-code areas; only postal-code-level indicators are listed — the rest take the municipality value (see All indicators).`}</p>`;
}
/* Housing stock from BBR: four distributions as bars, parent (municipality) as a reference tick */
const BBR_DIST = [["rooms", "Rooms", ["1", "2", "3", "4+"]], ["size", "Dwelling size", ["< 50 m²", "50–79", "80–119", "120+ m²"]],
                  ["built", "Year built", ["before 1950", "1950–79", "1980–2009", "2010+"]], ["type", "Building type", ["houses", "row houses", "multi-dwelling", "other"]]];
function bbrCard(e) {
  const b = e.o.bbr; if (!b || !b.dist) return "";
  const ref = e.muni && e.muni.bbr ? e.muni.bbr.dist : null;
  const pct = (arr, i) => { const t = arr.reduce((x, y) => x + y, 0); return t ? arr[i] / t * 100 : 0; };
  const block = ([k, title, labels]) => `<div class="bbrblk"><h4>${title}</h4>${labels.map((l, i) => { const v = pct(b.dist[k], i), r = ref ? pct(ref[k], i) : null;
    return `<div class="bbrrow"><span>${esc(l)}</span><em><i style="width:${v.toFixed(1)}%"></i>${r != null ? `<u style="left:${r.toFixed(1)}%" title="${esc(e.muni.name)} ${nf(r, 0)} %"></u>` : ""}</em><b>${nf(v, 0)} %</b><span class="dim">${nf(b.dist[k][i], 0)}</span></div>`; }).join("")}</div>`;
  return `<p class="hint" style="margin:0 0 10px">${nf(b.n, 0)} dwellings in ${nf(b.n_bld, 0)} buildings${ref ? ` · tick = ${esc(e.muni.name)}` : ""}</p>
    <div class="bbrgrid">${BBR_DIST.map(block).join("")}</div>
    <p class="cap">Source: BBR (Bygnings- og Boligregistret) via Datafordeler, current dwellings (status 6, boligtype 1–5) placed by their building's coordinate. Register data as reported by owners.</p>`;
}
/* ---------- the study row (spec §5.2, §4.6) ----------
   `studyRow(entity, opts)` is the one implementation of "study this indicator here": the chart panel
   on the left (60 %), the mini map on the right (40 %), the same height. P6 hands it the finest area
   a test-property pin sits in, which is why nothing below reads AR or the hash directly.
     opts.gap        the KK vs BBR label swap for this entity (computed once by the caller)
     opts.mapId      the div the Leaflet map is built in       (default "armap")
     opts.legendId   the legend card inside the mini map       (default "arlegend")
     opts.mapKey     its key in LF / LF_MAPS                   (default "amap")
     opts.note       one line over the map saying what it shows
     opts.legends    extra legend cards inside the mini map, above the indicator one (P6's overlays) */
function studyRow(e, opts) {
  const o = opts || {};
  return `<div class="studyrow" data-testid="study-row">${chartPanel(e, o)}${miniMap(o)}</div>`;
}
/* which of the four things the panel draws. An Outlook indicator only counts as one while the
   projection it belongs to actually has a population path to draw. */
function panelMode(e, ind) {
  if (isClim(ind.key)) return "clim";
  if (ind.proj && e.o && e.o.fc_pop) return "outlook";
  return eYears(e, ind.key).length > 1 ? "history" : "snapshot";
}
const PANEL_HINT = { history: "yearly series · this area, its parent and the median of its peers",
                     snapshot: "published once — no year series, so the peers are the comparison",
                     outlook: "observed population solid, the projection dashed — never spliced into one series",
                     clim: "three published horizons, with the low–high scenario range" };
function chartPanel(e, opts) {
  const o = opts || {}, ind = curInd(), mode = panelMode(e, ind), s = tileStats(e, ind);
  return `<div class="card panel" data-testid="chart-panel" data-mode="${mode}">
    <div class="card-head"><h3 data-testid="panel-title">${esc(indLabel(ind, o.gap))}${ind.unit ? ` <span class="dim">${esc(ind.unit)}</span>` : ""}</h3>
      <span class="hint">${esc(PANEL_HINT[mode])}</span></div>
    ${panelHeadRow(e, ind, s)}
    <div class="panel-b">${panelBody(e, ind, mode)}</div>
    ${panelFoot(e, ind)}</div>`;
}
/* value · Δ y/y · rank · vs median — one row, the same four figures whatever the panel draws below */
function panelHeadRow(e, ind, s) {
  if (!s) return `<p class="panel-hd none">${esc(e.name)} has no published figure for ${esc(ind.short || ind.label)}
    <span class="dim">— ${esc(isClim(ind.key) ? climReason(e.o, ind.key) : "the publisher has none at this level")}</span></p>`;
  const inh = !s.cur.own;
  return `<div class="panel-hd">
    <b class="pv${ind.proj ? " proj" : ""}${inh ? " inh" : ""}">${projValueHtml(ind, s.cur.v, e.o, e.type)}</b>
    ${s.yoy != null ? `<span class="pk"><i class="${cls(s.yoy, ind.key)}">${sign(s.yoy, x => nf(x, 1))}${s.unit}</i> y/y</span>` : ""}
    ${s.rk ? `<span class="pk">${rankHtml(s.rk, e.peerLabel)}</span>` : ""}
    ${s.vsMed != null ? `<span class="pk"><i class="${cls(s.vsMed, ind.key)}">${sign(s.vsMed, x => nf(x, 1))}${s.unit}</i> vs median</span>` : ""}
    ${inh ? `<span class="pk inhlab">${esc((e.muni || {}).name || "municipality")} (municipality figure)</span>` : ""}
    ${ind.proj ? `<span class="tag proj">Projection</span>` : ""}${smallBaseTag(ind, e.o, e.type)}
    ${isClim(ind.key) ? `<span class="tag clim">${esc(hzShort(HZ.h))}</span>` : ""}</div>`;
}
function panelBody(e, ind, mode) {
  if (mode === "clim") return climBars(e, ind);
  if (mode === "outlook") return `<div data-testid="outlook-chart">${outlookChartFor(e)}</div>
    ${projChangeLine(e.o, e.type === "kvarter" ? "kvarter" : "kommune") ? `<p class="olchg">${projChangeLine(e.o, e.type === "kvarter" ? "kvarter" : "kommune")}</p>` : ""}
    <p class="cap">The whole projection, its age split and its caveat are in <b>Population outlook</b> below.</p>`;
  if (mode === "history") return areaChart(e, ind);
  /* snapshot: one published as-of, so the peers are the only comparison there is (spec §4.10) */
  const a = ind.asof || {};
  const at = a[e.type] || a.kommune || a.postnr || a.kvarter || "";
  return `<p class="statecard" data-testid="state-nohistory">Published once${at ? ` · ${esc(at)}` : ""}
    <span class="dim">— no year series, so there is no trend to draw. ${esc(e.name)} against the ${esc(ePeerLabel(e, ind.key))}:</span></p>
    ${distStrip(e, ind) || `<p class="empty">Fewer than three ${esc(ePeerLabel(e, ind.key))} have a figure — nothing to spread out.</p>`}`;
}
/* the Outlook panel draws the same two series the Population outlook section does */
function outlookChartFor(e) {
  const isQ = e.type === "kvarter";
  const pr = ((isQ ? IND_CPH : IND).find(i => i.key === "fc_growth") || {}).proj || {};
  return popOutlookChart(e.o, { actualSource: isQ ? "KKBEF1" : "FOLK1A", projSource: pr.table || pr.publisher || "DST" });
}
/* Distribution strip (spec §5.2): every peer with a figure as a tick, the median marked, this area
   as a labelled dot. Plain arithmetic on published values — no model, no bins, no score. */
function distStrip(e, ind) {
  const pool = ePeers(e, ind.key), label = ePeerLabel(e, ind.key);
  const vals = pool.map(p => V(p, ind.key)).filter(v => v != null);
  const v = eVal(e, ind.key).v;
  if (vals.length < 3 || v == null) return "";
  const all = vals.concat(v);
  const lo = Math.min(...all), hi = Math.max(...all), sp = (hi - lo) || 1;
  /* a 640-unit viewBox against a ~640 px panel keeps the labels at the size the CSS asks for */
  const W = 640, H = 124, L0 = 16, R = 16, AX = 62;
  const x = t => L0 + (t - lo) / sp * (W - L0 - R);
  /* a label at either end would run out of the box, so it anchors to the edge it is near */
  const anchor = t => x(t) > W * 0.82 ? "end" : x(t) < W * 0.18 ? "start" : "middle";
  const med = median(vals), f = fmtTight(ind);
  return `<svg class="chart diststrip" data-testid="dist-strip" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(e.name)} ${f(v)} against ${vals.length} ${esc(label)}, median ${f(med)}">
    <line class="grid" x1="${L0}" x2="${W - R}" y1="${AX}" y2="${AX}"/>
    ${vals.map(t => `<line class="dtick" x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="${AX - 9}" y2="${AX + 9}"/>`).join("")}
    <line class="dmed" x1="${x(med).toFixed(1)}" x2="${x(med).toFixed(1)}" y1="${AX - 16}" y2="${AX + 16}"/>
    <text class="ax" x="${x(med).toFixed(1)}" y="${AX + 32}" text-anchor="${anchor(med)}">median ${f(med)}</text>
    <circle class="ddot" cx="${x(v).toFixed(1)}" cy="${AX}" r="5.5"/>
    <text class="ax dlab" x="${x(v).toFixed(1)}" y="${AX - 24}" text-anchor="${anchor(v)}">${esc(e.name)} ${f(v)}</text>
    <text class="ax" x="${L0}" y="${H - 6}">${f(lo)}</text>
    <text class="ax" x="${W - R}" y="${H - 6}" text-anchor="end">${f(hi)}</text></svg>
    <p class="cap">One tick for each of the ${vals.length} ${esc(label)} with a published figure (of ${pool.length}); the dashed line is their median. No bins, no model — the published values on one axis.</p>`;
}
/* Climate (spec §5.2): the three published horizons as bars, each with the publisher's own low–high
   scenario range as a whisker and the median of the municipalities as a dashed tick. Nothing is
   drawn between the horizons — a line there would be an interpolation this layer does not make. */
function climBars(e, ind) {
  const kom = e.type === "kommune" ? e.code : e.type === "kvarter" ? CPH_MUNI : e.o.muni;
  const km = climKom(kom) || {};
  const rows = CLIM_HZ.map(h => ({ h, v: climValue(e.o, ind.key, h),
    r: ((km[ind.key] || {}).range || {})[h] || null,
    med: median(MUNI.map(m => climValue(m, ind.key, h))) }));
  const all = rows.flatMap(r => [r.v, r.med, r.r && r.r.low, r.r && r.r.high]).filter(v => v != null);
  const link = `<p class="cap"><button class="lk mini" data-go="climate/${esc(pad4(kom || ""))}">Climate sheet ›</button>
    ${esc(CLIM_FOOT)}</p>`;
  if (!all.length) return `<p class="empty">${esc(e.name)} has no published figure for this indicator at any horizon.</p>${link}`;
  const hi = Math.max(...all, 0), lo = Math.min(...all, 0), sp = (hi - lo) || 1;
  const W = 900, H = 250, L0 = 74, R = 18, T0 = 20, B = 52;
  const y = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const col = (W - L0 - R) / rows.length, bw = Math.min(104, col * 0.44);
  const cx = k => L0 + (k + 0.5) * col;
  const ticks = [lo, lo + sp / 2, hi];
  return `<svg class="chart climbars" data-testid="clim-bars" viewBox="0 0 ${W} ${H}">
    ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(y(t) + 3).toFixed(1)}" text-anchor="end">${fmtTight(ind)(t)}</text>`).join("")}
    ${rows.map((r, k) => {
      /* the horizon only — the Klimaatlas period each one covers is in the caption under the chart,
         where three of them fit; side by side on the axis they overwrite each other */
      const lab = `<text class="ax" x="${cx(k).toFixed(1)}" y="${H - B + 22}" text-anchor="middle"><title>${esc(hzLabel(r.h))}</title>${esc(hzShort(r.h))}</text>`;
      if (r.v == null) return lab + `<text class="ax dim" x="${cx(k).toFixed(1)}" y="${y(lo).toFixed(1)}" text-anchor="middle">–</text>`;
      const y0 = y(Math.max(0, lo)), yv = y(r.v);
      const whisk = r.r && r.r.low != null && r.r.high != null
        ? `<line class="whisk" x1="${cx(k).toFixed(1)}" x2="${cx(k).toFixed(1)}" y1="${y(r.r.high).toFixed(1)}" y2="${y(r.r.low).toFixed(1)}"/>
           <line class="whisk" x1="${(cx(k) - 12).toFixed(1)}" x2="${(cx(k) + 12).toFixed(1)}" y1="${y(r.r.high).toFixed(1)}" y2="${y(r.r.high).toFixed(1)}"/>
           <line class="whisk" x1="${(cx(k) - 12).toFixed(1)}" x2="${(cx(k) + 12).toFixed(1)}" y1="${y(r.r.low).toFixed(1)}" y2="${y(r.r.low).toFixed(1)}"/>` : "";
      const med = r.med != null ? `<line class="cmed" x1="${(cx(k) - bw / 2 - 10).toFixed(1)}" x2="${(cx(k) + bw / 2 + 10).toFixed(1)}" y1="${y(r.med).toFixed(1)}" y2="${y(r.med).toFixed(1)}"><title>median of the ${MUNI.length} municipalities: ${fmtOf(ind)(r.med)}</title></line>` : "";
      return `<rect data-bar data-hz="${esc(r.h)}" class="cbar${HZ.h === r.h ? " on" : ""}" x="${(cx(k) - bw / 2).toFixed(1)}" y="${Math.min(y0, yv).toFixed(1)}"
          width="${bw.toFixed(1)}" height="${Math.abs(y0 - yv).toFixed(1)}" fill="${CLIM_COL[r.h]}"><title>${esc(hzShort(r.h))}: ${fmtOf(ind)(r.v)}${r.r && r.r.low != null ? ` (range ${fmtTight(ind)(r.r.low)}–${fmtTight(ind)(r.r.high)})` : ""}</title></rect>
        <text class="ax cbv" x="${cx(k).toFixed(1)}" y="${(Math.min(y0, yv) - 6).toFixed(1)}" text-anchor="middle">${fmtOf(ind)(r.v)}</text>${whisk}${med}${lab}`;
    }).join("")}</svg>
    <div class="bleg"><span><i style="background:${CLIM_COL[HZ.h]}"></i>${esc(e.name)}</span><span><i class="lgdash"></i>median of the ${MUNI.length} municipalities</span><span><i class="lgwhisk"></i>low–high scenario range</span></div>
    <p class="cap">${CLIM_HZ.map(h => `${esc(hzShort(h))} ${esc(CLIM_FIG[h] || "")}`).join(" · ")}</p>
    ${link}`;
}
/* source · table · as of · Verify ↗, then the definition — every value surface carries them (§0) */
function panelFoot(e, ind) {
  const a = ind.asof || {};
  const at = a[e.type] || a.kommune || a.postnr || a.kvarter || "";
  const code = e.type === "postnr" ? e.o.nr : srcCode(e.o, e.type);
  const line = srcLine(ind, at) || [ind.source, at ? "as of " + at : ""].filter(Boolean).join(", ");
  const link = indSrcLink(ind, code, "Verify", e.type);
  /* the surge keys' registry `desc` names the default horizon inside the sentence (a data defect
     logged in P3), and the panel draws all three — so the horizon word comes out of this one line */
  const desc = isClim(ind.key) ? climDescNeutral(ind.desc) : (ind.desc || "");
  return `<p class="cap srcrow panel-foot">${esc(line)}${link ? " · " + link : ""}</p>
    <p class="cap panel-def">${esc(desc)}${ind.warn ? `<br><span class="warnline">⚠ ${esc(ind.warn)}</span>` : ""}</p>`;
}
/* ---------- MiniMap (spec §4.6) ---------- */
function miniMap(opts) {
  const o = opts || {};
  const full = !!UI.mmFull;
  return `<div class="minimap${full ? " is-full" : ""}" data-testid="minimap" data-mapkey="${esc(o.mapKey || "amap")}">
    <div class="mm-map" id="${esc(o.mapId || "armap")}"></div>
    ${o.note ? `<div class="mm-note">${o.note}</div>` : ""}
    <div class="maplegs"><div class="maplegend small mm-leg" id="${esc(o.legendId || "arlegend")}"></div>${o.legends || ""}</div>
    <div class="mm-chips">${full ? mmChips() : ""}</div>
    <button type="button" class="mm-full" data-mmfull data-testid="minimap-full"
      title="${full ? "Close full screen (Esc)" : "Full screen"}" aria-label="${full ? "Close full screen" : "Full screen"}"
      aria-pressed="${full ? "true" : "false"}">${full ? "✕" : "⤢"}</button></div>`;
}
/* The overlay covers the toolbar, so the chips come with it — otherwise the one thing a reader
   wants from a full-screen map (another indicator on the same frame) would need Esc first. */
const mmChips = () => indChips("ind", { testid: "minimap-chips", cls: "mm-chiprow" });
/* ⤢: a fixed overlay over the page, Esc to close, and the map told its new size after each
   transition. The flag lives in UI so that choosing another indicator inside full screen keeps it
   (AC-P4); a navigation closes it, the way every other popover on the page behaves. */
function mmFull(on) {
  const el = document.querySelector("[data-testid=minimap]"); if (!el) return;
  const want = on == null ? !el.classList.contains("is-full") : !!on;
  UI.mmFull = want;
  el.classList.toggle("is-full", want);
  const b = el.querySelector("[data-testid=minimap-full]");
  if (b) { b.textContent = want ? "✕" : "⤢"; b.title = want ? "Close full screen (Esc)" : "Full screen";
           b.setAttribute("aria-label", b.title); b.setAttribute("aria-pressed", want ? "true" : "false"); }
  const ch = el.querySelector(".mm-chips"); if (ch) ch.innerHTML = want ? mmChips() : "";
  const m = LF[el.dataset.mapkey || "amap"];
  if (m) { setTimeout(() => m.invalidateSize(), 40); setTimeout(() => m.invalidateSize(), 340); }
}
/* ---------- the four toggles (spec §5.2) ---------- */
function arSec(k, label, hint, body) {
  if (!body) return "";
  return `<details class="card arsec" data-testid="sec-${k}" data-sec="${k}"${AR.show.has(k) ? " open" : ""}>
    <summary><span class="arsec-t">${esc(label)}</span>${hint ? `<span class="hint">${hint}</span>` : ""}</summary>
    <div class="arsec-b">${body}</div></details>`;
}
/* All figures: the full indicator table, plus the blocks that used to be tabs or cards of their own —
   the BBR housing stock, and on a quarter page the Safety survey and the KK-vs-DST forecast note. */
function areaFigures(e, gap) {
  const parts = [areaCompareTable(e, gap), newStockNote(e, gap)];
  const bbr = bbrCard(e);
  if (bbr) parts.push(`<div class="arsub"><span class="lfsec">Housing stock (BBR)</span>${bbr}</div>`);
  if (e.type === "kvarter" && e.o.kk) parts.push(`<div class="arsub"><span class="lfsec">Safety survey — ${esc(e.o.kk.bydel)}</span>${kkBody(e)}</div>`);
  if (e.type === "kvarter" && cphFcCaveat("kvarter")) parts.push(`<div class="arsub"><span class="lfsec">Population forecast — Københavns Kommune, not DST</span>${cphFcCaveat("kvarter")}${pastAccuracyLine(e.o)}</div>`);
  return parts.filter(Boolean).join("");
}
const areaFigureCount = e => e.inds.filter(i => eVal(e, i.key).v != null).length;
const areaSubLabel = e => !e.subs ? "" : Object.keys(e.subs).map(k => k === "kvarter" ? `Quarters (${e.subs[k].length})` : `Postal codes (${e.subs[k].length})`).join(" / ");
function areaSections(e, gap) {
  const ind = curInd();
  const out = [];
  const ol = outlookBody(e);
  if (ol) out.push(arSec("outlook", "Population outlook",
    `${ind.proj ? `<span class="tag">shown above</span>` : ""}<span class="tag proj">Projection</span> <span class="dim">${esc(projSpan(e))}</span>`, ol));
  out.push(arSec("figures", `All figures (${areaFigureCount(e)})`,
    `<span class="dim">click a row to read it above, ↗ to chart it</span>`, areaFigures(e, gap)));
  out.push(arSec("sub", areaSubLabel(e), `<span class="dim">click a row for its page</span>`, areaSubTable(e)));
  out.push(arSec("info", "Data information", "", areaInfo(e)));
  return out.join("");
}
function areaInfo(e) {
  const ind = curInd(), lb = lowerBetter(ind.key);
  return `<p class="note"><b>${esc(indLabel(ind, newStockGap(e)))}.</b> ${esc(ind.desc || "")}
      ${lb ? "<b>↓ Lower is better</b> — rank #1 is the lowest value." : ""}
      ${neutralDir(ind.key) ? "<b>Neither end is better</b> — this one is ordered by size only, never good to bad." : ""}</p>
    <p class="cap">Rank is among the ${esc(e.peerLabel)} that have a figure. “vs median” is the difference to the median
      of those ${esc(e.peerLabel)} — pp for a share, % for a level. A dash is the publisher having no figure; n/c is a
      figure that is not comparable at the municipality level; <span class="tag-muni">muni</span> is the municipality's
      own figure shown at this level${e.type === "kvarter" ? "; ^ is a figure published for the whole bydel" : ""}.</p>
    ${srcNoteBody()}`;
}
/* one short line over the mini map: what it is showing. It has to fit the narrow half of the study
   row on one or two lines, so the invariant it used to spell out lives in the tooltip. */
function arMapNote(e) {
  const mm = arMapMode(e, curInd());
  const parent = (e.muni || {}).name || e.name;
  const what = mm.kommuneLevel ? `The ${MUNI.length} municipalities`
    : e.type === "kommune" ? `${esc(e.name)} by ${mm.useQ ? "quarter" : "postal code"}`
    : mm.useQ ? `Quarters of ${esc(parent)}` : `Postal codes of ${esc(parent)}`;
  return `<span title="Selecting is always a click, a search or a breadcrumb — panning and zooming this map never change which area the page is about.">${what} <span class="dim">· click one to open it</span></span>`;
}
function areaTop(e) {
  const mapHash = e.type === "kommune" ? `map/${e.code}` : e.type === "kvarter" ? `map/${CPH_MUNI}` : `map/${e.o.muni}/postnr`;
  const microCode = e.type === "kommune" ? e.code : e.type === "kvarter" ? CPH_MUNI : e.o.muni;
  return `<div class="card accent arhead">
    <div class="arid">
      <h2>${esc(e.name)}</h2>
      <div class="artags"><span class="tag">${esc(e.typeLabel)}</span><span class="tag">code ${esc(e.code)}</span>${e.o.pop != null ? `<span class="tag">${nf(e.o.pop, 0)} inhabitants</span>` : ""}${e.type === "kommune" ? `<span class="tag">${e.ctx.length} postal codes</span>` : ""}${e.type === "kvarter" && e.bydel ? `<span class="tag">${esc(e.bydel)}</span>` : ""}${e.type === "postnr" && e.o.codes && e.o.codes.length > 1 ? `<span class="tag">merged codes ${esc(e.o.codes.join(", "))}</span>` : ""}</div>
    </div>
    <div class="tools"><button class="lk" data-go="${withQ(mapHash)}">Show on map</button><button class="lk" data-go="${chartLink(MK.ind, e.type, e.code)}">↗ Chart</button>${microAvail(microCode) ? `<button class="lk primary" data-go="map/${microCode}?ind=${MK.ind}&micro=1&mind=${MK.mind}">Buildings ›</button>` : ""}</div>
    ${headlineHtml(e)}
  </div>
  <div class="artools" data-testid="area-toolbar">${indPicker("ind")}${periodControl("ind")}${indChips("ind")}</div>`;
}
function vArea() {
  const e = areaEntity();
  if (!e) return `<div class="back"><button data-go="map">‹ Macro map</button></div><div class="card"><p class="empty">Unknown area.</p></div>`;
  mapInit(arMapInit);
  const gap = newStockGap(e);
  return `<div id="artop">${areaTop(e)}</div>
    ${studyRow(e, { gap, note: arMapNote(e) })}
    <div id="arsecs">${areaSections(e, gap)}</div>`;
}
/* Choosing an indicator (or a horizon, or a year) on the area page updates the panel, the tiles, the
   toolbar and the map's colours **in place** (spec §4.2, AC-P4). render() would drop the mini map,
   lose the reader's scroll position and close the full-screen overlay; nothing about the page's
   shape changes, only what every part of it is showing. Returns false when this is not that page. */
function areaRefresh(opts) {
  if (S.view !== "area") return false;
  const e = areaEntity(); if (!e) return false;
  const row = document.querySelector("[data-testid=study-row]"); if (!row) return false;
  const gap = newStockGap(e);
  const top = document.getElementById("artop"); if (top) top.innerHTML = areaTop(e);
  const panel = row.querySelector("[data-testid=chart-panel]");
  if (panel) panel.outerHTML = chartPanel(e, { gap });
  const note = row.querySelector(".mm-note"); if (note) note.innerHTML = arMapNote(e);
  const ch = row.querySelector(".mm-chips"); if (ch && UI.mmFull) ch.innerHTML = mmChips();
  const secs = document.getElementById("arsecs");
  if (secs) { secs.innerHTML = areaSections(e, gap); enableSort(secs); }
  arMapPaint((opts || {}).fit);
  return true;
}
/* Copenhagen quarters: the figures the city's safety survey publishes for the whole bydel */
function kkBody(e) {
  const k = e.o.kk, tile = (l, v, sub) => v == null ? "" : `<div class="hltile"><span class="tl">${esc(l)}</span><b>${esc(v)}</b><em>${esc(sub)}</em></div>`;
  const i = e.inds.find(x => x.key === "crime_1000") || {};
  return `<p class="hint">Københavns Kommune ${esc(k.year)} · Københavns Politi ${esc(k.crime_year)} · p. ${esc(k.page || "–")} · published per bydel, so every quarter of ${esc(k.bydel)} shows the same figure</p>
    <div class="tiles wrap">
      ${tile("Reported offences", k.reports_n != null ? nf(k.reports_n, 0) : null, `${k.bydel}, ${k.crime_year}`)}
      ${tile("Violence", k.violence_1000inh != null ? nf(k.violence_1000inh, 0) : null, `per 1,000 inh., ${k.crime_year}`)}
      ${tile("Burglary", k.burglary_1000inh != null ? nf(k.burglary_1000inh, 0) : null, `per 1,000 inh., ${k.crime_year}`)}
    </div>
    <p class="cap">^ = figure published for the whole bydel, not the quarter. Burglary here is per 1,000 <b>inhabitants</b> as published — not the national indicator's per 1,000 dwellings. ${esc(k.note || "")} <span class="dim">${esc(i.source || "")}</span></p>`;
}
function arMapMode(e, ind) {
  /* what the small map shows: Copenhagen quarters, the municipality's postal codes, or (for a municipality-level
     indicator on a municipality page) the municipality among all others */
  const useQ = e.type === "kvarter" || (e.type === "kommune" && e.subs && e.subs.kvarter && AR.sub !== "postnr");
  /* an indicator the quarter layer does not have (Safety) is drawn with the municipality values */
  if (useQ && !cphOwn(ind.key) && IND.some(i => i.key === ind.key)) return { useQ: false, sind: IND.find(i => i.key === ind.key), kommuneLevel: true };
  const subInds = useQ ? IND_CPH : IND; const sind = subInds.find(i => i.key === ind.key) || null;
  const kommuneLevel = e.type === "kommune" && !useQ && !!sind && sind.level !== "postnr";
  return { useQ, sind, kommuneLevel };
}
/* The mini map is built once per render of the page and then only ever re-painted (arMapPaint) —
   choosing another indicator must not cost the reader the pan, the zoom or the full-screen overlay
   they are in (spec §4.6, AC-P4). Draggable and scroll-zoomable by spec; zooming never selects. */
function arMapInit() {
  if (S.view !== "area") return;                  /* a render for another view got in first */
  const el = document.getElementById("armap"); if (!el || typeof L === "undefined") return;
  const e = areaEntity(); if (!e) return;
  dropMap("amap");
  const map = L.map(el, { center: [56, 10.5], zoom: 7, dragging: true, scrollWheelZoom: true, zoomSnap: 0.5, zoomDelta: 1, wheelPxPerZoomLevel: 60, wheelDebounceTime: 20, attributionControl: false });
  LF.amap = map; syncMaps();
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap" }).addTo(map);
  arMapPaint(true);
  /* the overlay survives a re-render, and a map built inside it has to be told its real size */
  if (UI.mmFull) setTimeout(() => LF.amap && LF.amap.invalidateSize(), 60);
}
/* the polygons and the legend for the active indicator, on a map that already exists */
function arMapPaint(fit) {
  const map = LF.amap; if (!map) return;
  const e = areaEntity(); if (!e) return;
  if (LF.amAreaG) { try { map.removeLayer(LF.amAreaG); } catch (err) {} }
  const gm = L.layerGroup().addTo(map); LF.amAreaG = gm;
  const ind = curInd(); const { useQ, sind, kommuneLevel } = arMapMode(e, ind);
  const ctx = e.type === "kommune" ? (useQ ? CPH.areas : kommuneLevel ? AREAS : e.ctx) : e.ctx;
  const vk = a => { if (!sind) return null; if (kommuneLevel) return V(byCode[a.muni], sind.key); return V(a, sind.key) ?? (useQ ? null : V(byCode[a.muni], sind.key)); };
  const sc = kommuneLevel ? scaleOf(MUNI, m => V(m, sind.key), null, sind) : scaleOf(ctx.filter(a => sind && V(a, sind.key) != null), vk, null, sind);
  const own = e.type === "kommune" ? e.ctx : e.own;
  const outline = e.type !== "kommune";
  ctx.forEach(a => {
    const isOwn = own.includes(a); const t = sc.t(vk(a));
    const p = L.polygon(a.rings, { color: isOwn && (outline || kommuneLevel) ? "#141C18" : "#FFFFFF", weight: isOwn && outline ? 2.6 : isOwn && kommuneLevel ? 1.2 : kommuneLevel ? 0.6 : 1,
      fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: isOwn ? .85 : kommuneLevel ? .35 : .45 });
    const v = vk(a); const native = kommuneLevel || (sind && V(a, sind.key) != null);
    const label = kommuneLevel ? (byCode[a.muni] || {}).name : a.name;
    p.bindTooltip(`<b>${esc(label)}</b>${v != null ? `<br>${esc(sind.short || sind.label)}: ${fmtOf(sind)(v)}${native ? "" : " °"}` : ""}`);
    if (!isOwn) { p.on("click", () => go(withQ(kommuneLevel ? pageOf(byCode[a.muni]) : pageOf(a)))); p.on("mouseover", () => p.setStyle({ weight: 2.2, color: "#141C18" })); p.on("mouseout", () => p.setStyle({ weight: kommuneLevel ? 0.6 : 1, color: "#FFFFFF" })); }
    else if (e.type === "kommune" && !kommuneLevel) { p.on("click", () => go(withQ(pageOf(a)))); }
    p.addTo(gm);
  });
  const leg = document.getElementById("arlegend");
  if (sind) setLegend("arlegend", sc, sind, ind.key, kommuneLevel ? "municipalities" : useQ ? "quarters" : "postal codes");
  else if (leg) leg.innerHTML = `<div class="lgtitle">${esc(ind.short || ind.label)}<span>not published at this level</span></div>`;
  /* a quarter is small enough that maxZoom 13 would leave one neighbour on screen — the mini map is
     there to put the area among its peers (spec §4.6), so it stops one level short */
  if (fit) { const b = boundsOf(own); if (b) map.fitBounds(b, { padding: kommuneLevel ? [90, 90] : e.type === "kommune" ? [10, 10] : [70, 70], maxZoom: kommuneLevel ? 9 : e.type === "kvarter" ? 12 : 13 }); }
}


/* ---------- Infrastructure projects overlay (data/geo/infra_projects.geojson, see docs/INFRA.md) ---------- */
const INFRA_ALL = ((D.infra && D.infra.features) || []).filter(f => f.geometry);
/* the map layer leaves out projects flagged map:false (a nationwide programme with no alignment) */
const INFRA = INFRA_ALL.filter(f => f.properties.map !== false);
const INFRA_BY = {}; INFRA_ALL.forEach(f => INFRA_BY[f.properties.id] = f);
/* which projects serve an area: data/processed/infra_index.json, keyed "<level>:<code>" */
const INFRA_IDX = D.infra_index || {};
const infraOf = (level, code) => (INFRA_IDX[`${level}:${code}`] || {}).projects || [];
const openLabel = p => p.open_window || (p.open_year ? String(p.open_year) : "–");
/* metres per degree, scaled for longitude at the geometry's latitude — enough for lengths and areas */
function geomStats(f) {
  const g = f.geometry, K = 111320;
  const flat = c => Array.isArray(c) && typeof c[0] === "number" ? [c] : c.flatMap(flat);
  const pts = flat(g.coordinates); if (!pts.length) return {};
  const lat0 = pts.reduce((s, q) => s + q[1], 0) / pts.length, kx = Math.cos(lat0 * Math.PI / 180) * K;
  const lines = g.type === "MultiLineString" ? g.coordinates : g.type === "LineString" ? [g.coordinates] : [];
  let km = 0;
  lines.forEach(cs => cs.forEach((c, i) => { if (i) km += Math.hypot((c[0] - cs[i - 1][0]) * kx, (c[1] - cs[i - 1][1]) * K) / 1000; }));
  const rings = g.type === "MultiPolygon" ? g.coordinates.map(r => r[0]) : g.type === "Polygon" ? [g.coordinates[0]] : [];
  let m2 = 0;
  rings.forEach(r => { let a = 0; r.forEach((c, i) => { const n = r[(i + 1) % r.length]; a += (c[0] * kx) * (n[1] * K) - (n[0] * kx) * (c[1] * K); }); m2 += Math.abs(a) / 2; });
  const stations = INFRA_ALL.filter(x => x.properties.parent_id === f.properties.id).length;
  return { km: km || null, ha: m2 ? m2 / 10000 : null, stations: stations || null };
}
/* four tones of the map's own palette: the overlay must not compete with the choropleth underneath */
const INFRA_ST = {
  study:        { label: "Study",        color: "#8A8C81", dash: "2 5", weight: 2.2, fill: false },
  decided:      { label: "Decided",      color: "#5C5F52", dash: "8 5", weight: 2.6, fill: false },
  construction: { label: "Under construction", color: "#1C6B5C", dash: "", weight: 3.2, fill: true },
  opened:       { label: "Opened",       color: "#9A9D92", dash: "", weight: 1.6, fill: true },
};
const INFRA_TYPE = { metro: "Metro", letbane: "Light rail", brt: "BRT", rail: "Rail", road: "Road",
                     bridge_tunnel: "Bridge / tunnel", urban_dev: "Urban development", hospital: "Hospital", university: "University", public_building: "State building" };
const infraSt = p => INFRA_ST[p.status] || INFRA_ST.study;
const isPt = f => f.geometry.type === "Point";
const isArea = f => f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon";
/* "M5: København H" → "København H" for map labels */
const infraShort = p => (p.name || "").replace(/^[^:]{1,14}:\s*/, "");
function infraStyle(p) {
  const s = infraSt(p);
  return { color: s.color, weight: p.schematic ? Math.max(1.2, s.weight * .6) : s.weight,
           opacity: p.schematic ? .75 : .95, dashArray: s.dash || null, lineCap: "round", lineJoin: "round" };
}
function infraPopup(p) {
  const bn = p.budget_mdkk == null ? null : nf(p.budget_mdkk / 1000, 1) + " bn DKK" + (/2015 prices/i.test(p.notes || "") ? " (2015 prices)" : "");
  const row = (l, v) => v ? `<span class="lfrow"><span>${esc(l)}</span><b>${v}</b></span>` : "";
  const yr = p.open_year ? `${p.open_year}${p.open_year_original && p.open_year_original !== p.open_year ? ` <span class="dim">originally ${p.open_year_original}</span>` : ""}` : "–";
  const komm = (p.kommuner || []).map(c => byCode[c]).filter(Boolean);
  return `<div class="lfpop"><b>${esc(p.name)}</b>
    <span class="infrapills"><i class="ipill">${esc(INFRA_TYPE[p.type] || p.type)}</i><i class="ipill st-${esc(p.status)}">${esc(infraSt(p).label)}</i>${p.schematic ? `<i class="ipill dim">schematic corridor</i>` : ""}</span>
    <div class="lfrows">${row("Opening", yr)}${row("Budget", bn)}${row("Agency", esc(p.agency || ""))}
      ${row("Municipalities", komm.length ? komm.slice(0, 4).map(m => esc(m.name)).join(", ") + (komm.length > 4 ? ` +${komm.length - 4}` : "") : "")}</div>
    ${p.schematic ? `<p class="cap">Schematic corridor — not an official alignment. It shows where the project runs, not how it will be built.</p>` : ""}
    ${p.notes ? `<p class="cap">${esc(p.notes)}</p>` : ""}
    <span class="lfact"><button class="lk mini primary" data-go="project/${esc(p.id)}">Open project sheet ›</button>${komm.length === 1 ? `<button class="lk mini" data-go="${withQ(pageOf(komm[0]))}">${esc(komm[0].name)} ›</button>` : ""}
      <a class="lk mini" href="${esc(p.source_url)}" target="_blank" rel="noopener">Source ↗</a></span>
    <p class="cap dim">${esc(p.source_doc || "")}${p.source_doc ? " · " : ""}updated ${esc(p.updated || "")}</p></div>`;
}
/* hatched fill for development areas — an SVG pattern added once to the map's overlay pane */
function infraHatch() {
  const svg = LF.map.getPane("overlayPane").querySelector("svg");
  if (!svg || svg.querySelector("#infra-hatch")) return !!svg;
  const ns = "http://www.w3.org/2000/svg";
  const defs = document.createElementNS(ns, "defs"), pat = document.createElementNS(ns, "pattern");
  pat.setAttribute("id", "infra-hatch"); pat.setAttribute("width", "7"); pat.setAttribute("height", "7");
  pat.setAttribute("patternUnits", "userSpaceOnUse"); pat.setAttribute("patternTransform", "rotate(45)");
  const line = document.createElementNS(ns, "line");
  line.setAttribute("x1", "0"); line.setAttribute("y1", "0"); line.setAttribute("x2", "0"); line.setAttribute("y2", "7");
  line.setAttribute("stroke", "#1C6B5C"); line.setAttribute("stroke-width", "2"); line.setAttribute("opacity", ".45");
  pat.appendChild(line); defs.appendChild(pat); svg.insertBefore(defs, svg.firstChild);
  return true;
}
/* one popup opener for every way into a project: the shape, its wide hit line, its label */
function openInfra(p, latlng, map) {
  const m = map || LF.map;
  if (!m || !latlng) return;
  L.popup({ maxWidth: 440, autoPanPadding: [24, 24] }).setLatLng(latlng).setContent(infraPopup(p)).openOn(m);
}
function lfInfraLayers() {
  ["infraG", "infraHitG", "infraStG", "infraLabG"].forEach(k => { if (LF[k]) { LF.map.removeLayer(LF[k]); LF[k] = null; } });
  if (!LF.map || !MK.infra || !INFRA.length) return;
  const lines = [], hits = [], stations = [];
  INFRA.forEach(f => {
    const p = f.properties;
    /* a line or an area counts as within range when any part of it is */
    if (tpRadOn() && !((featDistM(f, TP.lat, TP.lon) ?? Infinity) <= TP.rad)) return;
    if (isPt(f)) { stations.push(f); return; }
    const area = isArea(f);
    const style = area ? { ...infraStyle(p), weight: 1.2, fillColor: infraSt(p).color, fillOpacity: .14 } : infraStyle(p);
    const layer = L.geoJSON(f, { style, interactive: area, className: "infra-shape" });
    layer._infra = p;
    lines.push(layer);
    if (area) {
      /* the whole area is clickable; hovering lifts the fill a little */
      layer.on("click", e => openInfra(p, e.latlng));
      layer.on("mouseover", () => layer.setStyle({ fillOpacity: .26 })).on("mouseout", () => layer.setStyle({ fillOpacity: .14 }));
    } else {
      /* a 14 px invisible line on top of a 2 px dotted one, so thin study corridors are easy to hit.
         Render-only: it is not in the legend, not in the GeoJSON and not in any export. */
      const hit = L.geoJSON(f, { style: { color: "#000000", weight: 14, opacity: 0, lineCap: "round", lineJoin: "round" }, className: "infra-hit" });
      hit._infra = p;
      hit.on("click", e => openInfra(p, e.latlng));
      hits.push(hit);
    }
  });
  LF.infraG = L.layerGroup(lines).addTo(LF.map);
  LF.infraHitG = L.layerGroup(hits).addTo(LF.map);
  if (infraHatch()) lines.forEach(l => { const f = l.toGeoJSON().features[0]; if (f && (f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon"))
    l.eachLayer(x => x._path && x._path.setAttribute("fill", "url(#infra-hatch)")); });
  /* stations sit above their line: a white halo under the status circle keeps them readable on any fill */
  const marks = [];
  stations.forEach(f => {
    const p = f.properties, s = infraSt(p), c = f.geometry.coordinates, ll = [c[1], c[0]];
    const halo = L.circleMarker(ll, { radius: 9, stroke: false, fillColor: "#FFFFFF", fillOpacity: .95, interactive: false });
    const m = L.circleMarker(ll, { radius: 7, color: s.color, weight: 2, opacity: .95,
      fillColor: s.fill ? s.color : "#FFFFFF", fillOpacity: s.fill ? .9 : 1, className: "infra-shape" });
    m.on("click", e => openInfra(p, e.latlng || ll));
    m.on("mouseover", () => { m.setRadius(9); halo.setRadius(11); }).on("mouseout", () => { m.setRadius(7); halo.setRadius(9); });
    m._infra = p; m._ll = ll;
    marks.push(halo, m);
  });
  LF.infraStG = L.layerGroup(marks).addTo(LF.map);
  lfInfraLabels();
  if (MK.focus) {
    const f = INFRA_BY[MK.focus], lay = lines.concat(marks).find(l => (l._infra || {}).id === MK.focus);
    if (f && lay) {
      const b = lay.getBounds ? lay.getBounds() : L.latLngBounds([lay.getLatLng()], [lay.getLatLng()]);
      LF.map.fitBounds(b, { padding: [60, 60], maxZoom: 14 });
      setTimeout(() => openInfra(f.properties, b.getCenter()), 400);
    }
    MK.focus = null; syncHash();
  }
}
function lfInfraLabels() {
  if (LF.infraLabG) { LF.map.removeLayer(LF.infraLabG); LF.infraLabG = null; }
  if (!LF.map || !MK.infra || !INFRA.length) return;
  const z = LF.map.getZoom(), labs = [], placed = [];
  const size = LF.map.getSize();
  /* full name once there is room for it, the short label further out */
  const text = p => z >= 11 ? infraShort(p) : (p.label_short || infraShort(p));
  const put = (ll, html, cls, p) => {
    const pt = LF.map.latLngToContainerPoint(ll);
    if (placed.some(q => Math.abs(q.x - pt.x) < 78 && Math.abs(q.y - pt.y) < 20)) return;
    placed.push(pt);
    /* keep the label inside the map: near an edge it hangs off the anchor the other way */
    const edge = pt.x > size.x - 95 ? " infralab-e" : pt.x < 95 ? " infralab-w" : "";
    const m = L.marker(ll, { interactive: true, keyboard: false, icon: L.divIcon({ className: "lflab infralab " + cls + edge, iconSize: null, html }) });
    m.on("click", () => openInfra(p, ll));
    labs.push(m);
  };
  if (z >= 12) INFRA.filter(isPt).forEach(f => {
    const p = f.properties, c = f.geometry.coordinates;
    put([c[1], c[0]], `<b>${esc(text(p))}</b>${p.open_year ? ` <i>· ${p.open_year}</i>` : ""}`, "infralab-st", p);
  });
  /* one label per line, at mid-zoom: national view is too crowded, close-up the station labels take over */
  if (z >= 8 && z < 12) INFRA.filter(f => !isPt(f) && !isArea(f)).forEach(f => {
    const p = f.properties;
    const cs = f.geometry.type === "MultiLineString" ? f.geometry.coordinates.flat() : f.geometry.coordinates;
    const c = cs[Math.floor(cs.length / 2)];
    put([c[1], c[0]], `<b>${esc(text(p))}</b>`, "infralab-line", p);
  });
  LF.infraLabG = L.layerGroup(labs).addTo(LF.map);
}
function infraLegendHtml(n) {
  const sw = s => `<div class="lgrow"><i class="ilg" style="border-color:${INFRA_ST[s].color};${INFRA_ST[s].dash ? `border-top-style:dashed` : ""};${INFRA_ST[s].fill ? `background:${INFRA_ST[s].color}22` : ""}"></i>${INFRA_ST[s].label}</div>`;
  return lgTitle("Infra projects", `${n == null ? INFRA.length : n} projects · Fingerplan, Anlægsstatus, OSM`) + `
    ${["study", "decided", "construction", "opened"].map(sw).join("")}
    <div class="lgrow gk"><i class="gk-line"></i>line<i class="gk-st"></i>station<i class="gk-area"></i>area</div>
    <div class="lgnote">dotted = schematic corridor, not an official alignment</div>`;
}

/* ---------- Leaflet layers (macro map) ---------- */
function lfPopup(a, muni) {
  /* two levels: the selected indicator big + four headline figures and the ways onward; every value behind "all values" */
  const row = (i, v, own) => `<span class="lfrow"><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(v)}${own ? (isQ ? bydelMark(i) : "") : " °"}</b></span>`;
  const LI = curInds(); const ind = curInd(); const isQ = a.bydel != null;
  const val = i => { const v = V(a, i.key); if (v != null) return { v, own: true }; if (muni && V(muni, i.key) != null) return { v: V(muni, i.key), own: false }; return null; };
  const peers = isQ ? CPH.areas : AREAS; const sel = val(ind);
  const rk = sel ? (sel.own ? rankOf(a, ind.key, peers) : (muni ? rankOf(muni, ind.key, MUNI) : null)) : null;
  const keys = HL_KEYS.filter(k => k !== ind.key).map(k => LI.find(i => i.key === k)).filter(Boolean).map(i => ({ i, x: val(i) })).filter(x => x.x).slice(0, 4);
  const native = LI.filter(i => !isSafety(i) && V(a, i.key) != null).map(i => row(i, V(a, i.key), true)).join("");
  const inherited = LI.filter(i => !isSafety(i) && V(a, i.key) == null && muni && V(muni, i.key) != null).map(i => row(i, V(muni, i.key), false)).join("");
  const safety = LI.filter(isSafety).map(i => ({ i, x: val(i) })).filter(o => o.x).map(({ i, x }) => row(i, x.v, x.own)).join("");
  const n = LI.filter(i => val(i)).length; const type = isQ ? "kvarter" : "postnr", code = isQ ? a.code : a.nr;
  return `<div class="lfpop"><b>${esc(a.nr || a.code)} ${esc(a.name)}</b>${MK.year !== LATEST ? ` <span class="tag">${MK.year}</span>` : ""}
    <span class="dim">${a.bydel ? esc(a.bydel) + " · " : ""}${muni ? esc(muni.name) : ""}${a.pop != null ? " · " + nf(a.pop, 0) + " inhabitants" : ""}</span>
    ${sel ? `<div class="lfbig"><span>${esc(ind.label)}${sel.own ? (isQ ? bydelMark(ind) : "") : " °"}</span><b>${fmtOf(ind)(sel.v)}</b><em>${rankHtml(rk, sel.own ? (isQ ? "quarters" : "postal codes") : "municipalities")}</em></div>` : `<div class="lfbig dim"><span>${esc(ind.label)}</span><b>${DASH}</b></div>`}
    ${ind.note_short ? `<p class="cap">${esc(ind.note_short)}</p>` : ""}
    ${outlookLine(a, isQ ? "kvarter" : "postnr") || (muni ? outlookLine(muni, "kommune") : "")}
    ${isQ && a.fc_growth != null ? cphFcCaveat("kvarter") : ""}
    ${keys.length ? `<div class="lfkey">${keys.map(({ i, x }) => `<div><span>${esc(i.short || i.label)}${x.own ? (isQ ? bydelMark(i) : "") : " °"}</span><b>${fmtOf(i)(x.v)}</b></div>`).join("")}</div>` : ""}
    <span class="lfact"><button class="lk mini primary" data-go="${withQ(pageOf(a))}">Open page ›</button>${muni && !MK.muni ? `<button class="lk mini" data-go="map/${muni.code}?ind=${MK.ind}">Zoom to ${esc(muni.name)}</button>` : ""}${muni && microAvail(muni.code) ? `<button class="lk mini" data-go="map/${muni.code}?ind=${MK.ind}&micro=1&mind=${MK.mind}">Buildings ›</button>` : ""}<button class="lk mini" data-go="${chartLink(ind.key, type, code)}">↗ Chart</button></span>
    <details class="lfmore"><summary>All ${n} values</summary>
    ${native ? `<span class="lfsec">${isQ ? "Quarter" : "Postal code"}</span><div class="lfrows">${native}</div>` : ""}
    ${inherited ? `<span class="lfsec">Municipality °</span><div class="lfrows">${inherited}</div>` : ""}
    ${safety ? `<span class="lfsec">Safety${muni ? " · municipality °" : ""}</span><div class="lfrows">${safety}</div>` : ""}
    ${isQ && a.kk ? `<span class="lfsec">KK survey · ${esc(a.kk.bydel)} ^</span><div class="lfrows">${kkRows(a.kk)}</div>` : ""}</details>
    ${climPopupBlock(a, muni)}</div>`;
}
/* figures the KK safety survey publishes per bydel but the dashboard does not map: counts and two offence groups */
function kkRows(kk) {
  const r = (l, v) => v == null ? "" : `<span class="lfrow"><span>${l}</span><b>${v}</b></span>`;
  return r(`Reported offences ${kk.crime_year}`, kk.reports_n != null ? nf(kk.reports_n, 0) : null) +
    r("Violence · per 1,000 inh.", kk.violence_1000inh != null ? nf(kk.violence_1000inh, 0) : null) +
    r("Burglary · per 1,000 inh.", kk.burglary_1000inh != null ? nf(kk.burglary_1000inh, 0) : null);
}
/* which sub-area (quarter / postal code) of the drilled municipality a point lies in — ray casting on the rings */
function pip(pt, ring) { let ins = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const yi = ring[i][0], xi = ring[i][1], yj = ring[j][0], xj = ring[j][1]; if ((yi > pt[0]) !== (yj > pt[0]) && pt[1] < (xj - xi) * (pt[0] - yi) / (yj - yi) + xi) ins = !ins; } return ins; }
function areaAt(lat, lon) { return muniAreas(MK.muni).find(a => (a.rings || []).some(r => pip([lat, lon], r))) || null; }

/* ---------- Test property: parse → locate → pin ---------- */
/* the map's own colour tokens live in :root so the marker, the rings and the CSS agree on one tone */
const cssVar = (name, fallback) => { try { const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v || fallback; } catch (e) { return fallback; } };
/* a polygon's [south, west, north, east] box, cached on the area — the prefilter before the ray casting */
function bboxOf(a) {
  if (a._bb) return a._bb;
  let s = 90, w = 180, n = -90, e = -180;
  (a.rings || []).forEach(r => r.forEach(q => { if (q[0] < s) s = q[0]; if (q[0] > n) n = q[0]; if (q[1] < w) w = q[1]; if (q[1] > e) e = q[1]; }));
  return (a._bb = [s, w, n, e]);
}
const inBox = (lat, lon, b) => lat >= b[0] && lat <= b[2] && lon >= b[1] && lon <= b[3];
/* which area of a list a point falls in — bbox first, ray casting only on the handful that survive */
function areaOf(list, lat, lon) { return (list || []).find(a => inBox(lat, lon, bboxOf(a)) && (a.rings || []).some(r => pip([lat, lon], r))) || null; }
/* a kommune polygon is outer ring minus its holes: Frederiksberg is a hole in København, and without
   the holes every Frederiksberg pin would land in København */
const inPoly = (pt, poly) => pip(pt, poly[0]) && !poly.slice(1).some(h => pip(pt, h));
function komLoad() {
  if (!KOM.p) KOM.p = fetch("geo/kommuner_lookup.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { KOM.list = d.kommuner || []; KOM.built = d.built || ""; KOM.source = d.source || ""; }).catch(() => { KOM.err = true; });
  return KOM.p;
}
function komAt(lat, lon) {
  if (!KOM.list) return null;
  const pt = [lat, lon];
  const hit = KOM.list.find(k => inBox(lat, lon, k.bb) && (k.polys || []).some(poly => inPoly(pt, poly)));
  return hit ? byCode[String(Number(hit.code))] || null : null;
}
/* where a point is, at every level the dashboard knows: kommune · postal code · Copenhagen quarter.
   `approx` means the kommune came from the postal code (the ring file had not loaded or failed) — a
   postal code can cross a kommune border, so that answer is a best guess, not the register's. */
function locate(lat, lon) {
  const postnr = areaOf(AREAS, lat, lon);
  let kommune = komAt(lat, lon), approx = false;
  if (!kommune && postnr) { kommune = byCode[postnr.muni] || null; approx = true; }
  if (!kommune && !postnr) return { error: "in water or outside Denmark" };
  const kvarter = CPH && kommune && kommune.code === CPH_MUNI ? areaOf(CPH.areas, lat, lon) : null;
  return { kommune, postnr, kvarter, approx };
}
/* the located result for the current pin, recomputed once the kommune ring file arrives */
function tpRes() {
  if (TP.lat == null) return null;
  const stamp = `${TP.lat},${TP.lon},${KOM.list ? 1 : 0}`;
  if (!TP.res || TP.res._stamp !== stamp) { const r = locate(TP.lat, TP.lon); r._stamp = stamp; TP.res = r; }
  return TP.res;
}
/* the pin's finest known area, dressed as an area-page entity so tileStats/headlineHtml work on it */
function tpEntity(r) {
  if (!r || r.error) return null;
  if (r.kvarter && CPH) return { type: "kvarter", typeLabel: "Copenhagen quarter", o: r.kvarter, name: r.kvarter.name, code: r.kvarter.code, muni: byCode[CPH_MUNI], bydel: r.kvarter.bydel, inds: IND_Q, peers: CPH.areas, peerLabel: "quarters" };
  if (r.postnr) return { type: "postnr", typeLabel: "Postal-code area", o: r.postnr, name: `${r.postnr.nr} ${r.postnr.name}`, code: r.postnr.nr, muni: byCode[r.postnr.muni], inds: IND, peers: AREAS, peerLabel: "postal codes" };
  if (r.kommune) return { type: "kommune", typeLabel: "Municipality", o: r.kommune, name: r.kommune.name, code: r.kommune.code, muni: null, inds: IND, peers: MUNI, peerLabel: "municipalities" };
  return null;
}
const tpWhere = r => [r.kommune ? r.kommune.name : null, r.postnr ? `${r.postnr.nr} ${r.postnr.name}` : null, r.kvarter ? r.kvarter.name : null].filter(Boolean).join(" · ");
/* The located result and the entity for the pin on the **test property page** (AN.a), memoised the
   same way tpRes() memoises the map's pin: curInds(), pickLevel() and every section ask for them on
   every render, and locate() walks 606 postal-code rings. The cache key carries whether the kommune
   ring file has landed, so the answer is recomputed once when it does. */
const ANC = { key: "", r: null, e: null };
function anRes() {
  const pt = anLoc();
  if (!pt) { ANC.key = ""; ANC.r = null; ANC.e = null; return null; }
  const k = `${pt.lat},${pt.lon},${KOM.list ? 1 : 0}`;
  if (ANC.key !== k) { ANC.key = k; ANC.r = locate(pt.lat, pt.lon); ANC.e = ANC.r && !ANC.r.error ? tpEntity(ANC.r) : null; }
  return ANC.r;
}
const anEntity = () => { anRes(); return ANC.e; };

/* the one paste box of the test property page (spec §5.5′): its "?" tooltip, a Go button and the
   inline error line under it. A link pasted here REPLACES the pin — v3.0 shows one property at a
   time (amendment A2), even though the URL codec is list-capable. */
function tpBox(opts) {
  const o = opts || {};
  return `<span class="tpbox"><input id="tpq" data-testid="prop-input" class="indsel tpq" type="search" placeholder="${esc(o.placeholder || "Paste Google Maps link or lat, lon — replaces the current pin")}" autocomplete="off" aria-label="Test property location">
    <span class="tptip" tabindex="0" role="note" aria-label="Accepted formats">?<span class="tptipc"><b>Accepted formats</b>${TP_FORMATS.map(([, ex, what]) => `<i>${esc(ex)}</i><span>${esc(what)}</span>`).join("")}<span class="tpwarn">Short maps.app.goo.gl links can't be read — open one and copy the full URL.</span></span></span>
    <button type="button" class="lk primary tpgo" data-tpgo>Go</button></span>`;
}
/* the privacy line under the input: the parsing is local, but the coordinates travel in the hash of any link shared */
const TP_NOTE = "Processed in your browser. The location is stored only in the page URL; don't paste confidential deal locations if you share the link.";
const tpNote = () => `<p class="cap tpnote">${TP_NOTE}</p>`;
function tpErrEl() { return document.getElementById("tperr"); }
function tpErr(msg) { TP.msg = msg || ""; const el = tpErrEl(); if (el) { el.textContent = TP.msg; el.style.display = TP.msg ? "" : "none"; } }
/* Enter or paste in the box: parse the text, then (once the kommune rings are there) drop the pin */
function tpGo(text) {
  const r = parseLocation(text);
  if (r.error) { tpErr(r.message); return; }
  tpErr("");
  komLoad().then(() => tpDrop(r.lat, r.lon));
}
function tpDrop(lat, lon) {
  const res = locate(lat, lon);
  if (res.error) { tpErr(`${lat.toFixed(5)}, ${lon.toFixed(5)} is ${res.error} — no municipality or postal code covers it.`); return; }
  /* dropped on the test property page: the new link REPLACES the pin, and with it the label — a
     different address is a different property, so it does not inherit the old one's name. */
  if (S.view === "analysis") { TP.lat = lat; TP.lon = lon; TP.res = null; TP.label = TP_LABEL; AN.label = "";
    go(propLink([{ lat, lon, label: "" }])); return; }
  if (!TP.label) TP.label = TP_LABEL;
  TP.fit = true;   /* the layer builder fits the map to the outer ring instead of the municipality */
  /* drill to the pin's municipality at postal-code level with the ordinary navigation */
  go(`map/${res.kommune.code}${res.kommune.code === CPH_MUNI ? "/postnr" : ""}?ind=${encodeURIComponent(MK.ind)}`
     + (MK.year !== LATEST ? `&y=${MK.year}` : "") + (MK.infra ? "&infra=1" : "") + (MK.pub ? "&public=1" : "")
     + `&pin=${lat.toFixed(5)},${lon.toFixed(5)}` + (TP.label !== TP_LABEL ? `&pl=${encodeURIComponent(TP.label)}` : ""));
}
function tpParse(q) {
  const m = (q.pin || "").match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/);
  if (!m) { TP.lat = TP.lon = null; TP.res = null; TP.rad = 0; return; }
  TP.lat = Number(m[1]); TP.lon = Number(m[2]); TP.label = q.pl || TP_LABEL;
  TP.rad = TP_RADII.includes(Number(q.rad)) ? Number(q.rad) : 0;
  /* the exact kommune needs the ring file; until it lands the popup says "approx." and then corrects itself */
  if (!KOM.list && !KOM.err) komLoad().then(() => { if (S.view === "makro" && LF.map) tpLayers(); });
}
function tpLayers() {
  if (!LF.map) return;
  if (LF.tpG) { LF.map.removeLayer(LF.tpG); LF.tpG = null; }
  if (TP.lat == null) return;
  const col = cssVar("--pin", "#33372C"), ll = [TP.lat, TP.lon];
  /* non-interactive rings, so a click still reaches the polygon underneath */
  const rings = TP_RINGS.map(m => L.circle(ll, { radius: m, color: col, weight: 1, opacity: .8, dashArray: "5 6", fill: false, interactive: false }));
  /* the active filter radius gets a solid ring of its own — the dashed ones stay as the scale */
  if (tpRadOn()) rings.push(L.circle(ll, { radius: TP.rad, color: col, weight: 1.6, opacity: .9, fill: true, fillOpacity: .05, interactive: false }));
  const mark = L.marker(ll, { icon: L.divIcon({ className: "tp-pin", iconSize: [22, 22], iconAnchor: [11, 11], html: "<i></i>" }), zIndexOffset: 1200, title: TP.label || TP_LABEL });
  mark.bindPopup(() => tpPopup(), { maxWidth: 520, maxHeight: 520, autoPanPadding: [24, 24] });
  LF.tpG = L.layerGroup(rings.concat([mark])).addTo(LF.map);
  LF.tpMark = mark;
  if (TP.fit) { TP.fit = false; LF.pendingFit = null; LF.map.fitBounds(rings[rings.length - 1].getBounds(), { padding: [18, 18] }); setTimeout(() => mark.openPopup(), 320); }
}
function tpPopup() {
  const r = tpRes(); if (!r) return "";
  if (r.error) return `<div class="lfpop tppop"><b>${esc(TP.label || TP_LABEL)}</b><span class="dim">${TP.lat.toFixed(5)}, ${TP.lon.toFixed(5)} — ${esc(r.error)}</span>
    <span class="lfact"><button class="lk mini" data-tp="remove">Remove</button></span></div>`;
  const e = tpEntity(r);
  return `<div class="lfpop tppop">
    <input id="tplab" class="tplab" value="${esc(TP.label || TP_LABEL)}" maxlength="60" aria-label="Test property label" title="Rename this pin — the name travels in the link">
    <span class="dim">${esc(tpWhere(r))}${r.approx ? ` <span class="tag">approx.</span>` : ""} · ${TP.lat.toFixed(5)}, ${TP.lon.toFixed(5)}</span>
    ${r.approx ? `<p class="cap">Municipality taken from the postal code — a postal code can cross a municipality border.</p>` : ""}
    ${e ? headlineHtml(e, { bare: true }) : ""}
    ${e ? `<span class="lfsec">${esc(e.typeLabel)} · ${esc(e.name)}</span>` : ""}
    <span class="dim">Rings: ${TP_RINGS.map(m => nf(m, 0) + " m").join(" · ")}</span>
    ${tpRadOn() ? `<span class="dim">Overlays filtered to ${esc(tpRadLabel(TP.rad))} around this pin.</span>` : ""}
    <span class="lfact"><button class="lk mini primary" data-go="${analysisLink(TP.lat, TP.lon, TP.label)}">Analyse ›</button>
      <button class="lk mini" data-tp="copy">Copy link</button><button class="lk mini" data-tp="remove">Remove</button></span></div>`;
}
function tpAction(kind, btn) {
  if (kind === "copy") {
    const url = location.origin + location.pathname + location.search + "#" + hashFor();
    const flash = txt => { if (!btn) return; const old = btn.textContent; btn.textContent = txt; setTimeout(() => { btn.textContent = old; }, 1600); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(() => flash("Link copied"), () => flash("Copy failed"));
    else flash("Copy failed");
    return;
  }
  if (kind === "remove") { TP.lat = TP.lon = null; TP.res = null; TP.label = TP_LABEL; TP.fit = false; if (LF.map) LF.map.closePopup(); tpErr(""); go(hashFor()); }
}

/* ---------- Analysis sheet (#analysis?a=<lat>,<lon>&la=<label>) ----------
   One property read against everything the dashboard already knows: the statistics of its finest-level
   area, the safety figures, the infrastructure pipeline around it, and the public buildings and schools
   within a kilometre. Nothing is fetched for the sheet alone — the kommune rings, the per-municipality
   building files and the school records are the same ones the map loads, so a sheet opened after a
   session on the map is instant. The sections that do wait for a file render a skeleton first. */
const AN_RING_M = 1000;            /* public buildings and schools are counted inside this radius */
const AN_INFRA_M = 3000;           /* infrastructure projects listed, nearest first */
const AN_CHIP_M = 1200;            /* a station this close that has not opened becomes a headline chip */
const AN_NEAREST = 5;              /* rows listed per public-building category */
const R_EARTH = 6371008.8;
/* great-circle distance in metres */
function havM(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180, dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(a)));
}
/* distance from the pin to a GeoJSON feature: a Point is the great-circle distance, a line or a ring the
   nearest point on its segments, and a point inside a polygon is 0 m. Degrees are converted to metres at
   the pin's own latitude — exact enough over the few kilometres this sheet looks at. */
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
const anDist = m => m == null ? "–" : m < 1000 ? `${nf(Math.round(m / 10) * 10, 0)} m` : `${nf(m / 1000, 1)} km`;
function anLoc() { const m = (AN.a || "").match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/); return m ? { lat: Number(m[1]), lon: Number(m[2]) } : null; }
/* --- Outlook for the pin's own area (docs/FORECAST.md §5.7) ---
   The finest area that has a projection: a Copenhagen quarter uses KK throughout, anything else uses
   DST's municipal run. The two are never shown as one figure. */
/* the object the projection belongs to: a Copenhagen quarter that has one, otherwise the municipality */
function anOutlookSrc(e, r) {
  if (!e) return null;
  const isQ = e.type === "kvarter" && e.o && e.o.fc_growth != null;
  const o = isQ ? e.o : (r && r.kommune ? byCode[r.kommune.code] : null);
  if (!o || o.fc_growth == null) return null;
  return { o, isQ, list: isQ ? IND_CPH : IND, where: isQ ? `${e.name} (quarter)` : `${(r.kommune || {}).name || ""} (municipality)` };
}
function anOutlookHint(s) {
  const pr = ((s.list.find(i => i.key === "fc_growth") || {}).proj) || {};
  return `<span class="tag proj">Projection</span> <span class="dim">${esc(pr.from || "")}→${esc(pr.to || "")} · ${esc(pr.publisher || "")} ${esc(pr.vintage || "")} · ${esc(s.where)}</span>`;
}
function anOutlookBody(s) {
  const src = s.o, isQ = s.isQ, list = s.list, level = isQ ? "kvarter" : "kommune";
  const pr = ((list.find(i => i.key === "fc_growth") || {}).proj) || {};
  const tiles = ["fc_growth", "fc_growth_5y", "fc_20_34", "fc_80p"].map(k => list.find(i => i.key === k)).filter(i => i && src[i.key] != null);
  return `${tiles.length ? `<div class="tiles wrap">${tiles.map(i => `<button type="button" class="hltile ${MK.ind === i.key ? "on" : ""}" data-ind="${esc(i.key)}" title="${esc(i.desc || i.label)}">
      <span class="tl">${esc(i.short || i.label)}</span><b class="proj">${fmtOf(i)(src[i.key])}</b><em class="dim">${esc(i.unit || "")}</em></button>`).join("")}</div>` : ""}
    ${projChangeLine(src, level) ? `<p class="olchg big">${projChangeLine(src, level)}</p>` : ""}
    ${popOutlookChart(src, { actualSource: isQ ? "KKBEF1" : "FOLK1A", projSource: pr.table || pr.publisher })}
    <p class="cap srcrow">${srcLink(pr.src, srcCode(src, level), "Verify the projection at source")}
      ${srcLink(pr.actuals, srcCode(src, level), "Verify the observed population")}</p>
    ${isQ ? pastAccuracyLine(src) : ""}
    ${isQ ? cphFcCaveat("kvarter") : `<p class="cap">${esc(((list.find(i => i.key === "fc_growth")) || {}).warn || "")}</p>`}
    <p class="cap dim">The projection is for the whole ${isQ ? "quarter" : "municipality"}, not for this address — it carries no housing programme, so a development on this plot is not in it. Observed population from ${esc(isQ ? "KKBEF1" : "FOLK1A")}; the dashed line is ${esc(pr.table || "")}, a scenario rather than a measurement.</p>`;
}

/* the nav item opens the pin that is on the map, if there is one — otherwise the empty state */
const anNavLink = () => TP.lat != null ? analysisLink(TP.lat, TP.lon, TP.label) : "property";
/* every municipality whose bounding box touches the circle of radius m around the pin, the pin's own first */
function anKomsNear(pt, own, m) {
  const dLat = m / 110540, dLon = m / (111320 * Math.cos(pt.lat * Math.PI / 180));
  const box = [pt.lat - dLat, pt.lon - dLon, pt.lat + dLat, pt.lon + dLon];
  const near = (KOM.list || []).filter(k => k.bb[0] <= box[2] && k.bb[2] >= box[0] && k.bb[1] <= box[3] && k.bb[3] >= box[1]);
  return [...new Set((own ? [String(Number(own))] : []).concat(near.map(k => String(Number(k.code)))))];
}
/* where a value sits among every area of the same level, as the share of peers it is at least as good as.
   Direction-aware: for a lower_better indicator a small value beats a large one, so the bar always fills
   toward "better" and two indicators of opposite direction can be read off the same column. */
function anPct(v, key, pool) {
  if (v == null) return null;
  const vals = pool.map(o => V(o, key)).filter(x => x != null);
  if (vals.length < 5) return null;
  /* neutral: no favourable end, so the bar is simply "how high among the peers" */
  const lb = !neutralDir(key) && lowerBetter(key);
  const beaten = vals.filter(x => lb ? x > v : x < v).length, tied = vals.filter(x => x === v).length;
  return { p: (beaten + tied / 2) / vals.length * 100, n: vals.length, neutral: neutralDir(key) };
}
function anRow(e, i, r) {
  const cur = eVal(e, i.key); if (cur.v == null) return "";
  /* an inherited figure is the municipality's, so it is ranked against municipalities, not against
     the postal codes or quarters that all copy the same number */
  const pool = cur.own ? e.peers : MUNI;
  const pc = anPct(cur.v, i.key, pool), lb = lowerBetter(i.key), nu = neutralDir(i.key);
  const peers = pool === MUNI ? "municipalities" : e.peerLabel;
  const kom = r.kommune ? V(byCode[r.kommune.code], i.key) : null;
  /* A neutral indicator gets the same bar, read as a position rather than a score: "higher than
     n % of the peers", no better/worse wording and no favourable-end fill (docs/FORECAST.md §3). */
  const barTitle = nu ? `higher than ${nf(pc ? pc.p : 0, 0)} % of the ${pc ? pc.n : 0} ${peers} — neither end is better`
    : `better than ${nf(pc ? pc.p : 0, 0)} % of the ${pc ? pc.n : 0} ${peers}${lb ? " — lower is better here" : ""}`;
  return `<tr${nu ? ' class="anneutral"' : ""}><th><span class="thn">${esc(i.label)} <span class="dim">${esc(i.unit || "")}</span></span>${i.proj ? `<span class="tag proj mini">${esc(i.proj.publisher)} ${esc(i.proj.vintage)}</span>` : ""}<button class="tch" data-go="${chartLink(i.key, e.type, e.code)}" title="Open in Charts">↗</button></th>
    ${fmtCell(i, cur.v, !cur.own, e.type === "kvarter" ? bydelMark(i) : "")}
    <td class="ansrc">${cur.own ? indSrcLink(i, e.type === "postnr" ? e.o.nr : srcCode(e.o, e.type), "Verify", e.type)
                                : indSrcLink(i, (r.kommune || {}).code, "Verify", "kommune")}</td>
    <td class="anbc" data-v="${pc ? pc.p.toFixed(1) : ""}">${pc
      ? `<span class="anbw" title="${esc(barTitle)}"><span class="anbar"><i style="width:${pc.p.toFixed(1)}%"></i></span><em>${nf(pc.p, 0)}</em></span>`
      : `<span class="dim">–</span>`}</td>
    ${fmtCell(i, kom, false)}${fmtCell(i, NAT ? V(NAT, i.key) : null, false)}</tr>`;
}
/* one indicator table: the rows grouped exactly as the indicator dropdown groups them */
function anIndTable(e, r, inds) {
  const groups = GROUP_ORDER.filter(g => inds.some(i => (i.group || "Other") === g))
    .concat(inds.some(i => !GROUP_ORDER.includes(i.group || "Other")) ? ["Other"] : []);
  const body = groups.map(g => {
    const rows = inds.filter(i => (i.group || "Other") === g).map(i => anRow(e, i, r)).join("");
    return rows ? `<tr class="angrp"><th colspan="6">${esc(g)}</th></tr>${rows}` : "";
  }).join("");
  if (!body) return `<p class="empty">no indicator has a value for this area</p>`;
  return `<div class="scrollx"><table class="tbl compact antbl"><thead><tr><th>Indicator</th>
    <th class="num">${esc(e.type === "kommune" ? e.name : e.type === "kvarter" ? "Quarter" : "Postal code")}</th>
    <th class="ansrc">Source</th>
    <th class="anbc">Percentile<br><span class="dim">vs all ${esc(e.peerLabel)}</span></th>
    <th class="num">${esc(r.kommune ? r.kommune.name : "Municipality")}</th><th class="num">Denmark</th></tr></thead>
    <tbody>${body}</tbody></table></div>`;
}
/* --- a. the header card: the paste box, the identity line, the links and the headline tiles ---
   Spec §5.5′ draws them in that order: what you can change, what the pin is, where to go from it,
   then the five figures. The tiles are the shared §4.7 component, so clicking one chooses the
   indicator that colours the mini map and fills the chart panel (AC-TP3). */
function tpTop(pt, r, e) {
  const back = withQ("map" + (r.kommune ? `/${r.kommune.code}${r.kommune.code === CPH_MUNI ? "/postnr" : ""}` : ""))
    + `&pin=${pt.lat.toFixed(5)},${pt.lon.toFixed(5)}` + (AN.label && AN.label !== TP_LABEL ? `&pl=${encodeURIComponent(AN.label)}` : "");
  /* one link per level the pin sits in — quarter, postal code, municipality (spec §5.5′ header) */
  const areaBtn = (o, label) => o ? `<button class="lk" data-go="${withQ(pageOf(o))}">${esc(label)} ›</button>` : "";
  return `<div class="card accent arhead anhead">
    <div class="tools tpinrow">${tpBox()}</div>
    <div class="tperr" id="tperr" role="status" ${TP.msg ? "" : `style="display:none"`}>${esc(TP.msg)}</div>
    ${tpNote()}
    <div class="arid">
      <input id="anlab" class="anlab" value="${esc(AN.label || TP_LABEL)}" maxlength="60" aria-label="Property label" title="Rename this property — the name travels in the link">
      <div class="artags">${r.kommune ? `<span class="tag">${esc(r.kommune.name)}</span>` : ""}${r.postnr ? `<span class="tag">${esc(r.postnr.nr)} ${esc(r.postnr.name)}</span>` : ""}${r.kvarter ? `<span class="tag">${esc(r.kvarter.name)}</span>` : ""}${r.approx ? `<span class="tag warn" title="Municipality taken from the postal code — a postal code can cross a municipality border.">approx.</span>` : ""}<span class="tag">${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</span>${e ? `<span class="tag" title="the finest level the dashboard publishes for this point — the chart panel and the figures below are its">read as ${esc(PICK_LEVEL_LABEL[e.type] || e.type)}</span>` : ""}</div>
    </div>
    <div class="tools"><button class="lk primary" data-go="${esc(back)}">Open on map ›</button><button class="lk" data-ancopy>Copy link</button>
      ${areaBtn(r.kvarter, r.kvarter ? r.kvarter.name : "")}${areaBtn(r.postnr, r.postnr ? r.postnr.nr : "")}${areaBtn(r.kommune, r.kommune ? r.kommune.name : "")}
      <a class="lk" target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${pt.lat}&mlon=${pt.lon}#map=17/${pt.lat}/${pt.lon}">OpenStreetMap ↗</a></div>
    ${e ? headlineHtml(e) : ""}
  </div>
  <div class="artools" data-testid="tp-toolbar">${indPicker("ind")}${periodControl("ind")}
    <span class="tp-right">${layersMenu("tp")}<label class="radsel"><span>radius</span><select id="tpradsel" data-testid="tp-radius" class="indsel" aria-label="Radius around the property">${TP_RADII.filter(m => m).map(m => `<option value="${m}"${AN.rad === m ? " selected" : ""}>${esc(tpRadLabel(m))}</option>`).join("")}</select></label></span>
    ${indChips("ind")}</div>`;
}
const AN_PUB_MAP_M = 2000;         /* public buildings drawn around the pin — at least twice the ring the sections count */
/* the ring the sections count inside and the mini map draws, from the radius select (spec §5.5′) */
const anRing = () => AN.rad || AN_RING_M;
const anPubMapM = () => Math.max(AN_PUB_MAP_M, 2 * anRing());
const anKom = () => { const r = anRes(); return r && r.kommune ? r.kommune.code : null; };
/* the municipalities near the pin whose BBR pull exists — the coverage rule for the Public buildings layer */
const anPubKoms = (pt, r) => (pt ? anKomsNear(pt, r && r.kommune && r.kommune.code, anRing()).filter(pubAvail) : []);
const anPubRows = (pt, koms) => koms.flatMap(k => ((PUB_FILES[k] || {}).buildings || []))
  .filter(b => pubCatOn(b.cat) && pubKindOn(b.kind) && (b.kind === "existing" || b.recent)
    && havM(pt.lat, pt.lon, b.lat, b.lon) <= anPubMapM());
/* Leaflet swallows clicks inside a popup, so the page links are wired when one opens — the same set the
   Macro map rewires, which is what makes "Open … sheet ›" work from a popup on this map too. */
function anPopupWire(popup) {
  const el = popup && popup.getElement(); if (!el) return;
  const on = (sel, fn) => el.querySelectorAll(sel).forEach(b => b.addEventListener("click", () => fn(b)));
  on("[data-go]", b => go(b.dataset.go));
  on("[data-project]", b => go(`project/${b.dataset.project}`));
  on("[data-school]", b => go(`school/${encodeURIComponent(b.dataset.school)}`));
  on("[data-pubsheet]", b => { const row = b.closest("[data-pubkom]"); go(`public/${(row && row.dataset.pubkom) || (LF.anKom || CPH_MUNI)}/${b.dataset.pubsheet}`); });
  el.querySelectorAll("details").forEach(d => d.addEventListener("toggle", () => {
    if (popup._updateLayout) { popup._updateLayout(); popup._updatePosition(); popup._adjustPan(); } }));
}
/* The three overlays on the mini map, redrawn in place (never a full re-render, so an open popup and the
   reader's zoom survive a file landing). Each one fills or hides its own legend box. */
function anMapOverlays() {
  const map = LF.anmap, pt = LF.anPt, r = LF.anR;
  if (!map || !pt || !document.getElementById("anmap")) return;
  ["anInfraG", "anInfraHitG", "anPubG", "anMicroG", "anClimG"].forEach(k => { if (LF[k]) { try { map.removeLayer(LF[k]); } catch (e) {} LF[k] = null; } });

  /* --- 0. the climate zone for the pin's kommune, under everything else and never clickable --- */
  if (ANL.climate && CLIM && r && r.kommune) {
    climSheetLoadFor(r.kommune.code);
    const fc = CZ[`${HZ.h}:${pad4(r.kommune.code)}`];
    const shapes = [];
    if (fc) shapes.push(L.geoJSON(fc, { interactive: false, style: { color: CLIM_COL[HZ.h], weight: .8, opacity: .7, fillColor: CLIM_COL[HZ.h], fillOpacity: .38 } }));
    if (CRA) shapes.push(L.geoJSON(CRA, { interactive: false, style: { color: "#16262E", weight: 1.2, opacity: .85, fill: false, dashArray: "5 3" } }));
    if (shapes.length) LF.anClimG = L.layerGroup(shapes).addTo(map);
  }

  /* --- a. infrastructure, in its status tones, with the project popup the Macro map opens --- */
  const inf = ANL.infra ? INFRA.map(f => ({ f, d: featDistM(f, pt.lat, pt.lon) })).filter(x => x.d != null && x.d <= AN_INFRA_M + 1500) : [];
  if (inf.length) {
    const lines = [], hits = [];
    inf.forEach(({ f, d }) => {
      const p = f.properties, st = infraSt(p);
      const tip = `<b>${esc(p.name)}</b><br>${esc(INFRA_TYPE[p.type] || p.type)} · ${esc(st.label)} · ${anDist(d)}`;
      if (isPt(f)) {
        const ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        lines.push(L.circleMarker(ll, { radius: 7, stroke: false, fillColor: "#FFFFFF", fillOpacity: .95, interactive: false }));
        const m = L.circleMarker(ll, { radius: 5, color: st.color, weight: 2, opacity: .95, className: "infra-shape",
          fillColor: st.fill ? st.color : "#FFFFFF", fillOpacity: st.fill ? .9 : 1 });
        m.bindTooltip(tip); m.on("click", e => openInfra(p, e.latlng || ll, map));
        lines.push(m); return;
      }
      const lay = L.geoJSON(f, { style: isArea(f) ? { ...infraStyle(p), weight: 1.2, fillColor: st.color, fillOpacity: .14 } : infraStyle(p) });
      lay.bindTooltip(tip); lay.on("click", e => openInfra(p, e.latlng, map));
      lines.push(lay);
      if (!isArea(f)) {   /* an invisible fat line so a thin study corridor is easy to hit */
        const hit = L.geoJSON(f, { style: { color: "#000000", weight: 12, opacity: 0, lineCap: "round", lineJoin: "round" }, className: "infra-hit" });
        hit.on("click", e => openInfra(p, e.latlng, map)); hits.push(hit);
      }
    });
    LF.anInfraG = L.layerGroup(lines).addTo(map);
    LF.anInfraHitG = L.layerGroup(hits).addTo(map);
  }
  const infLeg = document.getElementById("aninfralegend");
  if (infLeg) { const live = ANL.infra && inf.length > 0; infLeg.style.display = live ? "" : "none"; infLeg.innerHTML = live ? infraLegendHtml(inf.length) : ""; }

  /* --- b. public buildings, the same markers, popups and category filter as the Macro map --- */
  const koms = anPubKoms(pt, r), pubOn = ANL.pub && !!PUB && koms.length > 0;
  let pubRowsN = [];
  if (pubOn) {
    koms.forEach(pubLoad);
    pubRowsN = anPubRows(pt, koms);
    LF.anPubG = L.layerGroup(pubMarkers(pubRowsN, map, gradeMode(true))).addTo(map);
  }
  const waiting = pubOn ? koms.filter(k => !PUB_FILES[k] && !PUB_FILES["_error_" + k]).length : 0;
  setPubLegendIn("anpublegend", pubOn, pubRowsN,
    `${koms.length} municipality file${koms.length === 1 ? "" : "s"}`,
    waiting ? ` · loading ${waiting} more…` : ` · within ${nf(anPubMapM(), 0)} m of the pin`, gradeMode(true));

  /* --- c. BBR buildings, lazy: the micro file is only fetched once the pill is on --- */
  const kom = r && r.kommune ? r.kommune.code : null;
  const microOn = ANL.micro && microAvail(kom);
  const mLeg = document.getElementById("anmicrolegend");
  if (microOn) loadMicro(kom);
  const md = microOn ? MICRO[String(Number(kom))] : null;
  if (md) {
    const mind = curMind(), rows = microRows(kom), z = map.getZoom();
    const msc = scaleOf(rows, x => x[mind.col], mind.breaks);
    LF.anMicroG = L.layerGroup(rows.map(x => { const t = msc.t(x[mind.col]);
      const m = L.circleMarker([x[0], x[1]], { renderer: amOf(map).base, radius: microRadius(x[2], z), color: "#141C18", weight: .6, opacity: .7,
        fillColor: t == null ? "#C4CBC4" : mkShade(t, "micro:" + mind.key), fillOpacity: .85 });
      m.bindPopup(() => microPopup(x, kom), { maxWidth: 440, autoPanPadding: [24, 24] }); return m; })).addTo(map);
    if (mLeg) { mLeg.style.display = ""; mLeg.innerHTML = legendHtml(msc, mind, "micro:" + mind.key, `${nf(rows.length, 0)} buildings · dot size = dwellings`); }
  } else if (mLeg) {
    const loading = microOn && !MICRO["_error_" + String(Number(kom))];
    mLeg.style.display = loading ? "" : "none";
    mLeg.innerHTML = loading ? `<div class="lgtitle">Buildings<span>loading ${esc((byCode[kom] || {}).name || "")}…</span></div>` : "";
  }
  /* the pin and its rings stay on top of every overlay */
  if (LF.anPinG) LF.anPinG.eachLayer(l => { if (l.bringToFront) l.bringToFront(); });
  /* the legend stack must stay inside the mini map and inside 60 % of its height (spec §4.5) */
  lgFitSoon();
}
/* ⌖ — put the property back in the middle. The counterpart of making the mini map draggable:
   the pin is the whole point of the sheet, so getting back to it is one click, never a reload. */
function anRecentreControl(map, ll) {
  const c = L.control({ position: "topleft" });
  c.onAdd = () => {
    const d = L.DomUtil.create("div", "leaflet-bar am-recentre");
    d.innerHTML = `<a href="#" role="button" data-testid="minimap-recentre" title="Re-centre on the property" aria-label="Re-centre on the property">⌖</a>`;
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(d, "click", ev => { L.DomEvent.stop(ev); map.setView(ll, map.getZoom()); });
    return d;
  };
  c.addTo(map);
  return c;
}
/* The mini map is built once per render of the page and then only ever re-painted (anMapPaint) —
   choosing another indicator, another horizon or another layer must not cost the reader the pan,
   the zoom or the full-screen overlay they are in (spec §4.6, the P5 rule read on this page). */
function anMapInit() {
  if (S.view !== "analysis") return;              /* a render for another view got in first */
  const el = document.getElementById("anmap"); if (!el || typeof L === "undefined") return;
  const pt = anLoc(); if (!pt) return;
  const r = anRes(); if (!r || r.error) return;
  dropMap("anmap");
  /* draggable since v3.0: the reader wants to look at the next street over without leaving the
     sheet. What a drag used to lose — the pin in the middle — the ⌖ control below brings back,
     and the position is kept across re-renders (LF.anCenter / LF.anZoom) rather than re-fitted. */
  const map = L.map(el, { center: [pt.lat, pt.lon], zoom: 15, scrollWheelZoom: true, dragging: true, zoomSnap: .5, attributionControl: false });
  LF.anmap = map; LF.anPt = pt; LF.anR = r; LF.anKom = r.kommune ? r.kommune.code : null;
  mapPanes(map);   /* one pane + renderer set per map — a cached one redraws into a dead context */
  syncMaps();
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "basemap" }).addTo(map);
  map.on("popupopen", ev => anPopupWire(ev.popup));
  /* the public zoom rule and the building dot size both follow the zoom, as on the Macro map */
  map.on("zoomend", () => { LF.anZoom = map.getZoom(); anMapOverlays(); });
  /* a drag is a reading position, not a selection: it is remembered, and it changes nothing else */
  map.on("moveend", () => { const c = map.getCenter(); LF.anCenter = [c.lat, c.lng]; LF.anZoom = map.getZoom(); });
  anRecentreControl(map, [pt.lat, pt.lon]);
  const rings = anMapPaint();
  anMapOverlays();
  /* a re-render keeps the reader's own view rather than re-fitting; a new pin is fitted to its ring */
  const key = `${pt.lat},${pt.lon},${AN.rad}`;
  if (LF.anKey === key && LF.anZoom) map.setView(LF.anCenter || [pt.lat, pt.lon], LF.anZoom);
  else { map.fitBounds(rings.getBounds(), { padding: [14, 14] }); LF.anKey = key; LF.anZoom = map.getZoom(); LF.anCenter = null; }
  /* the overlay survives a re-render, and a map built inside it has to be told its real size */
  if (UI.mmFull) setTimeout(() => LF.anmap && LF.anmap.invalidateSize(), 60);
}
/* the choropleth, the pin, its rings and the indicator legend — on a map that already exists.
   Returns the outermost ring, which is what the initial fit is framed on. */
function anMapPaint() {
  const map = LF.anmap; if (!map) return null;
  const pt = anLoc(), r = anRes(); if (!pt || !r || r.error) return null;
  ["anAreaG", "anPinG"].forEach(k => { if (LF[k]) { try { map.removeLayer(LF[k]); } catch (err) {} LF[k] = null; } });
  /* the current choropleth underneath, at the finest level the indicator reaches */
  const ind = curInd();
  const useQ = !!(CPH && r.kvarter && cphOwn(ind.key));
  const areas = useQ ? CPH.areas : AREAS;
  const micro = !useQ && AREAS.some(a => V(a, ind.key) != null);
  const sc = useQ ? scaleOf(CPH.areas.filter(a => V(a, ind.key) != null), a => V(a, ind.key), null, ind)
    : micro ? scaleOf(AREAS.filter(a => V(a, ind.key) != null), a => V(a, ind.key), null, ind) : scaleOf(MUNI, m => V(m, ind.key), null, ind);
  const gm = L.layerGroup().addTo(map); LF.anAreaG = gm;
  areas.forEach(a => {
    /* an area with no figure of its own takes its municipality's, exactly as the macro map does */
    const own = V(a, ind.key);
    const t = sc.t(useQ ? own : micro && own != null ? own : V(byCode[a.muni], ind.key));
    L.polygon(a.rings, { color: "#FFFFFF", weight: .8, fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .5, interactive: false }).addTo(gm);
  });
  /* the walk/bike rings are the fixed scale; the radius the reader chose is the solid one */
  const col = cssVar("--pin", "#33372C"), ll = [pt.lat, pt.lon];
  const rings = TP_RINGS.map(m => L.circle(ll, { radius: m, color: col, weight: 1, opacity: .8, dashArray: "5 6", fill: false, interactive: false }));
  const sel = L.circle(ll, { radius: anRing(), color: col, weight: 1.8, opacity: .95, fill: true, fillOpacity: .05, interactive: false });
  LF.anPinG = L.layerGroup(rings.concat([sel,
    L.marker(ll, { icon: L.divIcon({ className: "tp-pin", iconSize: [22, 22], iconAnchor: [11, 11], html: "<i></i>" }), zIndexOffset: 1200, interactive: false })])).addTo(map);
  setLegend("anlegend", sc, ind, ind.key, useQ ? "quarters" : micro ? "postal codes" : "municipalities");
  return anRing() >= TP_RINGS[TP_RINGS.length - 1] ? sel : rings[rings.length - 1];
}
/* --- e. infrastructure nearby (the section that opens itself) --- */
const anInfraRows = pt => INFRA_ALL.map(f => ({ f, p: f.properties, d: featDistM(f, pt.lat, pt.lon) }))
  .filter(x => x.d != null && x.d <= AN_INFRA_M).sort((a, b) => a.d - b.d);
function anInfraBody(pt) {
  const rows = anInfraRows(pt);
  /* a station that has not opened yet and is inside the 1 200 m ring is the headline: it is the one
     thing in this layer that changes what the address is worth. Opened ones are listed, never flagged. */
  const chips = rows.filter(x => isPt(x.f) && x.d <= AN_CHIP_M && x.p.status !== "opened").map(x => {
    const par = INFRA_BY[x.p.parent_id];
    const line = (par && par.properties.label_short) || (x.p.name.match(/^([^:]{1,14}):/) || [])[1] || (INFRA_TYPE[x.p.type] || x.p.type);
    return `<button class="anchip st-${esc(x.p.status)}" data-project="${esc(x.p.id)}" title="${esc(x.p.name)} — ${esc(infraSt(x.p).label)}"><b>${esc(line)}</b><span>${esc(infraShort(x.p))}</span><em>${anDist(x.d)}${x.p.open_year || x.p.open_window ? ` · ${esc(openLabel(x.p))}` : ""}</em></button>`;
  }).join("");
  const body = rows.length ? `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Project</th><th>Type</th><th>Status</th><th class="num">Opening</th><th class="num">Distance</th></tr></thead>
    <tbody>${rows.map(x => `<tr class="clickrow" data-project="${esc(x.p.id)}"><th><span class="thn">${esc(x.p.name)} <span class="go">›</span></span></th>
      <td class="dim">${esc(INFRA_TYPE[x.p.type] || x.p.type)}</td><td><i class="ipill st-${esc(x.p.status)}">${esc(infraSt(x.p).label)}</i></td>
      <td class="num" data-v="${x.p.open_year || ""}">${esc(openLabel(x.p))}${x.p.open_year_original && x.p.open_year_original !== x.p.open_year ? `<br><span class="dim">originally ${esc(String(x.p.open_year_original))}</span>` : ""}</td>
      <td class="num" data-v="${Math.round(x.d)}">${anDist(x.d)}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="empty">no project in the layer within ${nf(AN_INFRA_M / 1000, 0)} km</p>`;
  return `${chips ? `<div class="anchips">${chips}</div>` : ""}
    ${body}
    <p class="cap">Distance is from the pin to the mapped geometry — a station point, the nearest point of a line, or 0 m inside a development area. A corridor flagged schematic is not an official alignment, so its distance is indicative. Click a row for the project sheet.</p>`;
}
/* a placeholder block while a file is in flight \u2014 the section keeps its height and says nothing it does not know */
const anSkel = n => `<div class="anskel">${Array.from({ length: n }, () => `<span></span>`).join("")}</div>`;
/* --- f. public buildings within the ring ---
   Spec §5.5′: rows that are the same building read twice — same name, same BBR use code, the same
   distance to within 20 m — become one row with a count. The BBR pull has a record per building
   body, so a school with four wings arrived as four identical lines. Nothing is dropped: the count
   says how many records the row stands for, and the distance is the nearest of them. */
const PUB_DUP_M = 20;
function anPubGroup(list) {
  const out = [], by = new Map();
  list.forEach(x => {
    const k = `${pubName(x.b)}|${x.b.code}|${Math.round(x.d / PUB_DUP_M)}`;
    const hit = by.get(k);
    if (hit) { hit.n++; return; }
    const row = { x, n: 1 }; by.set(k, row); out.push(row);
  });
  return out;
}
function anPubBody(pt, r) {
  if (!PUB) return `<p class="empty">The public-buildings layer is not in this build.</p>`;
  const ring = anRing();
  const covered = anKomsNear(pt, r.kommune && r.kommune.code, ring).filter(pubAvail);
  if (!covered.length) return `<p class="empty">Not covered yet: public buildings are available for the Copenhagen metro area (${PUB.kommuner.length} municipalities).</p>`;
  covered.forEach(pubLoad);
  const waiting = covered.filter(k => !PUB_FILES[k] && !PUB_FILES["_error_" + k]);
  if (waiting.length) return anSkel(4);
  const all = covered.flatMap(k => ((PUB_FILES[k] || {}).buildings || []))
    .map(b => ({ b, d: havM(pt.lat, pt.lon, b.lat, b.lon) }))
    .filter(x => x.d <= ring && (x.b.kind === "existing" || x.b.recent))
    .sort((a, b) => a.d - b.d);
  const cases = all.filter(x => x.b.kind === "case");
  const counts = Object.entries(PUB_CAT).map(([k, c]) => {
    const n = all.filter(x => x.b.cat === k && x.b.kind === "existing").length;
    return `<span class="hlc"><span>${esc(c.label)}</span><b>${nf(n, 0)}</b><em>${(() => { const near = all.find(x => x.b.cat === k); return near ? "nearest " + anDist(near.d) : "none in the ring"; })()}</em></span>`;
  }).join("");
  let grouped = 0;
  const blocks = Object.entries(PUB_CAT).map(([k, c]) => {
    const rows = anPubGroup(all.filter(x => x.b.cat === k));
    grouped += rows.reduce((s, g) => s + (g.n - 1), 0);
    const list = rows.slice(0, AN_NEAREST);
    if (!list.length) return "";
    return `<tr class="angrp"><th colspan="4" style="color:${c.color}">${esc(c.label)}</th></tr>` + list.map(({ x, n }) => `<tr class="clickrow" data-pubsheet="${esc(x.b.id)}" data-pubkom="${esc(x.b.kom)}">
      <th><span class="thn">${esc(pubName(x.b))} <span class="go">›</span></span>${n > 1 ? `<span class="tag pubn" title="${n} BBR records with the same name, use code and distance — one building registered in several bodies">×${n}</span>` : ""}</th><td class="dim">${esc(x.b.code)} ${esc(x.b.label)}</td>
      <td>${x.b.kind === "existing" ? `<span class="dim">Existing${x.b.year ? " · " + x.b.year : ""}</span>` : `<i class="ipill st-decided">Open case${x.b.permit ? " · " + esc(x.b.permit) : ""}</i>`}</td>
      <td class="num" data-v="${Math.round(x.d)}">${anDist(x.d)}</td></tr>`).join("");
  }).join("");
  const extra = covered.filter(k => k !== String(Number(r.kommune ? r.kommune.code : 0)));
  return `<div class="hl anhl4">${counts}</div>
    <div class="anfacts"><span><em>Total</em><b>${nf(all.length, 0)}</b> buildings in the ring</span>
      <span><em>Open building cases</em><b>${nf(cases.length, 0)}</b> permit ${PUB.recent_years} yrs or newer</span>
      ${extra.length ? `<span><em>Also read</em><b>${extra.map(k => esc((byCode[k] || {}).name || k)).join(", ")}</b>neighbouring municipality files</span>` : ""}</div>
    ${blocks ? `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Building</th><th>BBR use</th><th>Status</th><th class="num">Distance</th></tr></thead><tbody>${blocks}</tbody></table></div>`
      : `<p class="empty">no public building within ${nf(ring, 0)} m</p>`}
    <p class="cap">The ${AN_NEAREST} nearest per category${grouped ? `; ${nf(grouped, 0)} further BBR record${grouped === 1 ? " was" : "s were"} folded into the row it repeats (×n)` : ""}. BBR via Datafordeler, ${esc(PUB.built || "")}; names from OpenStreetMap where one lies within 60 m. An open case is owner-reported and is not a construction schedule. Click a row for the building sheet.</p>`;
}
/* --- g. schools within the ring --- */
function anSchBody(pt, r) {
  if (!SCH_META) return `<p class="empty">The school layer is not in this build.</p>`;
  const ring = anRing();
  const covered = anKomsNear(pt, r.kommune && r.kommune.code, ring).filter(pubAvail);
  if (!covered.length) return `<p class="empty">Not covered yet: school quality is available for the Copenhagen metro area (${PUB.kommuner.length} municipalities).</p>`;
  schoolsLoad();
  if (!SCHOOLS) return anSkel(3);
  const rows = (SCHOOLS.schools || []).filter(s => covered.includes(s.kom) && s.lat != null)
    .map(s => ({ s, d: havM(pt.lat, pt.lon, s.lat, s.lon) })).filter(x => x.d <= ring).sort((a, b) => a.d - b.d);
  const body = rows.length ? `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>School</th><th>Type</th><th class="num">Distance</th><th class="num">FP9 grade</th><th class="num">vs expected</th><th>School year</th></tr></thead>
    <tbody>${rows.map(x => { const s = x.s, d = schV(s, "soc_ref_diff"), sig = schSig(schV(s, "soc_ref_significant"));
      return `<tr class="clickrow" data-school="${esc(s.nr)}"><th><span class="thn">${esc(s.name)} <span class="go">\u203a</span></span></th>
        <td class="dim">${esc(SCH_TYPE[s.type] || s.type)}</td><td class="num" data-v="${Math.round(x.d)}">${anDist(x.d)}</td>
        <td class="num" data-v="${schV(s, "grade_avg") ?? ""}">${schCell(schV(s, "grade_avg"), schGrade)}</td>
        <td class="num" data-v="${d ?? ""}">${d == null ? `<span class="dim" title="${SUPPRESSED}">\u2013</span>` : schDiff(d) + (sig ? ` <em class="schsig">\u2713 ${esc(sig)}</em>` : ` <em class="dim">\u2248 as expected</em>`)}</td>
        <td class="dim">${esc(schY(s, "grade_avg") || schY(s, "pupils_total") || SCH_LATEST)}</td></tr>`; }).join("")}</tbody></table></div>`
    : `<p class="empty">no grundskole within ${nf(ring, 0)} m</p>`;
  return `${body}
    <p class="cap">Distance is to the school's register point, not to its gate. FP9 grade is the average of the bundne pr\u00f8ver across the pupils who sat them, not across the schools; "vs expected" is the grade minus the socioeconomic reference the ministry's model predicts from the pupils' background, \u2713 where the source calls the difference significant. A dash is suppressed by the source, not a zero. Kilde: Uddannelsesstatistik.dk, retrieved ${esc((SCH_META || {}).retrieved || "")}.</p>`;
}
/* --- h. sources and as-of stamps, from the same metadata the Sources view uses --- */
function anSources(e, r, inds, hasPub, hasSch) {
  const S_ = {}; ((D.meta && D.meta.sources) || []).concat((CPH && CPH.meta && CPH.meta.sources) || []).forEach(s => S_[s.key] = s);
  const seen = new Set(), rows = [];
  const add = (label, tables, asof, fetched, used) => { const k = label + "|" + tables; if (seen.has(k)) return; seen.add(k); rows.push({ label, tables, asof, fetched, used }); };
  inds.forEach(i => {
    const ts = i.tables || [];
    if (ts.length) ts.forEach(t => { const s = S_[t]; if (s) add(s.label, s.tables || "", s.asof || "", s.fetched || "", "Area profile"); });
    /* the quarter layer and the derived indicators carry their source as prose, not as a table code */
    else if (i.source) add(i.source, "", [...new Set(Object.values(i.asof || {}))].join(" · "), "", "Area profile");
  });
  add("DAGI administrative boundaries (Klimadatastyrelsen via DAWA)", "kommuner, postnumre" + (e && e.type === "kvarter" ? " · Københavns Kommune bydele og kvarterer" : ""),
    "", (KOM.built || (D.meta && D.meta.built) || ""), "Locating the pin");
  if (INFRA_ALL.length) add("Infrastructure projects layer", `${INFRA_ALL.length} curated projects · ${esc(((D.infra && D.infra.meta) || {}).source_csv || "data/external/infra_projects.csv")}`,
    INFRA_ALL.map(f => f.properties.updated).filter(Boolean).sort().pop() || "", ((D.infra && D.infra.meta) || {}).built || "", "Infrastructure nearby");
  if (hasPub) add("BBR via Datafordeler", "byg021BygningensAnvendelse 410–449 · open building cases", "", PUB.built || "", "Public buildings");
  if (hasSch) add("Uddannelsesstatistik.dk (STIL)", (SCH_META.years || []).join(" · "), (SCH_META.years || []).slice(-1)[0] || "", SCH_META.retrieved || "", "Schools");
  add("OpenStreetMap contributors (ODbL)", "basemap tiles · building names within 60 m", "", "", "Map and names");
  return `<div class="scrollx"><table class="tbl compact"><thead><tr><th>Source</th><th>Tables / files</th><th>As of</th><th>Fetched</th><th>Used for</th></tr></thead>
    <tbody>${rows.map(x => `<tr><th>${esc(x.label)}</th><td class="dim">${esc(x.tables)}</td><td>${esc(x.asof || "–")}</td><td class="dim">${esc(x.fetched || "–")}</td><td class="dim">${esc(x.used)}</td></tr>`).join("")}</tbody></table></div>
    <p class="cap">${((D.meta && D.meta.attribution) || []).map(esc).join(" · ")}${CPH && CPH.meta && CPH.meta.attribution ? " · " + esc(CPH.meta.attribution) : ""}. Full definitions and every table stamp under <button class="lk mini" data-go="data/sources">Data › Sources</button>.</p>`;
}
/* the three sections that wait for a file are refilled in place when it lands — no section blocks
   another, and a re-render is avoided so the mini map is not torn down and rebuilt under the reader */
function anFill() {
  if (S.view !== "analysis") return;
  const pt = anLoc(); if (!pt) return;
  const r = anRes(); if (!r || r.error) return;
  [["anpub", anPubBody], ["ansch", anSchBody], ["anclim", anClimBody]].forEach(([id, fn]) => {
    const el = document.getElementById(id); if (!el) return;
    el.innerHTML = fn(pt, r); enableSort(el);
  });
}
/* the empty state (spec §5.5′, AC-E1): the paste box with the caret already in it, the privacy line
   and one example link — nothing else on a page that has nothing to show yet. */
function anEmpty() {
  setTimeout(() => { const el = document.getElementById("tpq"); if (el && S.view === "analysis") el.focus(); }, 0);
  return `<div class="card accent" data-testid="state-empty"><div class="card-head"><h3>Test property</h3><span class="hint">one address, read against every layer</span></div>
    <div class="tools tpinrow">${tpBox()}</div>
    <div class="tperr" id="tperr" role="status" ${TP.msg ? "" : `style="display:none"`}>${esc(TP.msg)}</div>
    ${tpNote()}
    <p class="anlead">Paste a Google Maps link or <code>lat, lon</code> to read one address against every layer.</p>
    <p class="cap">For example <button class="lk mini" data-go="property?p=55.6545,12.539">https://www.google.com/maps/@55.6545,12.539,17z</button> — the page then reads the pin's area statistics, the safety figures, every infrastructure project within ${nf(AN_INFRA_M / 1000, 0)} km and the public buildings and schools inside the radius you choose. The map's search box takes the same links and coordinates.</p></div>`;
}
/* one short line over the mini map, the counterpart of the area page's arMapNote() */
function tpMapNote(r) {
  const ind = curInd();
  return `<span title="Panning and zooming this map never change which property the page is about — a new pin is a pasted link, nothing else.">${esc(ind.short || ind.label)} <span class="dim">· rings ${TP_RINGS.map(m => nf(m, 0) + " m").join(" · ")}, solid ${esc(tpRadLabel(anRing()))}${r && r.kommune ? ` · ${esc(r.kommune.name)}` : ""}</span></span>`;
}
/* the overlay legends that live inside the mini map, above the indicator one (spec §4.5, §4.6) */
const TP_MAP_LEGENDS = `<div class="maplegend small publiclegend" id="anpublegend"></div><div class="maplegend small infralegend" id="aninfralegend"></div><div class="maplegend small" id="anmicrolegend"></div>`;
/* --- the eight <details> of spec §5.5′, open state in show= --- */
function tpSec(k, label, hint, body) {
  if (!body) return "";
  return `<details class="card arsec" data-testid="tp-sec-${k}" data-tpsec="${k}"${AN.show.has(k) ? " open" : ""}>
    <summary><span class="arsec-t">${esc(label)}</span>${hint ? `<span class="hint">${hint}</span>` : ""}</summary>
    <div class="arsec-b">${body}</div></details>`;
}
function tpSections(pt, r, e) {
  const ring = anRing();
  const profile = e ? e.inds.filter(i => (i.group || "") !== "Safety" && eVal(e, i.key).v != null) : [];
  const safety = e ? e.inds.filter(i => (i.group || "") === "Safety" && eVal(e, i.key).v != null) : [];
  const koms = anPubKoms(pt, r);
  const hint = `° = municipality value where no finer statistic exists${e && e.type === "kvarter" ? " · ^ = figure published for the whole bydel" : ""} · the percentile bar fills toward "better", so a low value fills it where lower is better${profile.some(i => neutralDir(i.key)) ? "; Outlook rows are neutral and the bar simply reads as a position among peers" : ""} · ↗ opens the indicator in Charts.`;
  const ol = anOutlookSrc(e, r);
  const inf = anInfraRows(pt);
  const out = [];
  if (ol) out.push(tpSec("outlook", "Population outlook", anOutlookHint(ol), anOutlookBody(ol)));
  if (e) {
    out.push(tpSec("profile", `Area profile (${profile.length})`,
      `<span class="dim">${esc(e.typeLabel)} ${esc(e.name)}${MK.year !== LATEST ? " · " + MK.year : ""}</span> <span class="hq" title="${esc(hint)}">ⓘ</span>`,
      anIndTable(e, r, profile)));
    out.push(tpSec("safety", "Safety",
      `<span class="dim">${esc(SAFETY.length ? (SAFETY[0].unit || "") : "")} · municipality level${e.type === "kvarter" ? " plus the city's own bydel survey" : ""}</span>`,
      `${safety.length ? anIndTable(e, r, safety) : `<p class="empty">no safety figure for this area</p>`}
       <p class="cap">Reported crime comes from Danmarks Statistik per municipality over a rolling four quarters; a postal code or quarter shows its municipality's figure (°).${e.type === "kvarter" ? ` Københavns Kommune's own safety survey publishes per bydel (^), so every quarter of ${esc(e.bydel || "the district")} carries the same number — a different source, period and geography from the national one.` : ""}</p>`));
  } else {
    out.push(tpSec("profile", "Area profile", "", `<p class="empty">No area statistics cover this point.</p>`));
  }
  out.push(tpSec("infra", "Infrastructure nearby",
    `<span class="dim">${inf.length} project${inf.length === 1 ? "" : "s"} within ${nf(AN_INFRA_M / 1000, 0)} km · distance to the alignment, 0 m inside a development area</span>`,
    anInfraBody(pt)));
  out.push(tpSec("public", `Public buildings within ${nf(ring, 0)} m`,
    `<span class="dim">${koms.length} municipality file${koms.length === 1 ? "" : "s"} read · BBR via Datafordeler</span>`,
    `<div id="anpub">${anPubBody(pt, r)}</div>`));
  out.push(tpSec("schools", `Schools within ${nf(ring, 0)} m`,
    `<span class="dim">Uddannelsesstatistik.dk · FP9 and the socioeconomic reference</span>`,
    `<div id="ansch">${anSchBody(pt, r)}</div>`));
  const clim = anClimBody(pt, r);
  if (clim) out.push(tpSec("climate", "Climate",
    `<span class="tag clim">${esc(hzShort(HZ.h))}</span> <span class="dim">Kystdirektoratet 100-year extents${r.kommune ? " · " + esc(r.kommune.name) : ""}</span>`,
    `<div id="anclim">${clim}</div>`));
  out.push(tpSec("sources", "Sources &amp; as of",
    `<span class="dim">everything this page read · built ${esc((D.meta && D.meta.built) || "–")}</span>`,
    anSources(e, r, profile.concat(safety), koms.length > 0, koms.length > 0 && !!SCH_META)));
  return out.join("");
}
function vAnalysis() {
  const pt = anLoc();
  if (!pt) return anEmpty();
  /* the kommune rings answer which municipality the point is really in — everything else waits for them */
  if (!KOM.list && !KOM.err) return `<div class="card accent"><div class="card-head"><h3>${esc(AN.label || TP_LABEL)}</h3><span class="hint">${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</span></div>
    ${stateCard("loading", "Locating the property…", "reading geo/kommuner_lookup.json — the municipality boundaries decide which area's figures this pin is read against")}</div>`;
  if (KOM.err) return `<div class="card accent"><div class="card-head"><h3>${esc(AN.label || TP_LABEL)}</h3><span class="hint">${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</span></div>
    ${stateCard("error", "Could not load geo/kommuner_lookup.json.", "Reload the page, or open the dashboard over http rather than as a file.",
      `<button class="lk primary" data-go="${withQ("map")}">‹ Back to the map</button>`)}</div>`;
  const r = anRes();
  if (r.error) return `<div class="card accent"><div class="card-head"><h3>${esc(AN.label || TP_LABEL)}</h3><span class="hint">${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</span></div>
    <p class="empty">That point is ${esc(r.error)} — no municipality or postal code covers it.</p>
    <div class="tools tpinrow">${tpBox()}</div>
    <div class="tperr" id="tperr" role="status" ${TP.msg ? "" : `style="display:none"`}>${esc(TP.msg)}</div>
    <div class="tools"><button class="lk primary" data-go="${withQ("map")}">‹ Back to the map</button></div></div>`;
  const e = anEntity();
  mapInit(anMapInit);
  setTimeout(anFill, 0);
  /* the same study row the area page is built around (spec §5.5′), pointed at the pin's finest area */
  return `<div id="tptop">${tpTop(pt, r, e)}</div>
    ${e ? studyRow(e, { mapId: "anmap", legendId: "anlegend", mapKey: "anmap", note: tpMapNote(r), legends: TP_MAP_LEGENDS })
        : `<div class="studyrow" data-testid="study-row"><div class="card panel" data-testid="chart-panel"><p class="empty">No area statistics cover this point, so there is nothing to chart.</p></div>${miniMap({ mapId: "anmap", legendId: "anlegend", mapKey: "anmap", note: tpMapNote(r), legends: TP_MAP_LEGENDS })}</div>`}
    <div id="tpsecs">${tpSections(pt, r, e)}</div>`;
}
/* Choosing an indicator, a horizon, a year, a layer or a radius on the test property updates the
   header, the panel, the sections and the map's colours **in place** — the same rule the area page
   follows (spec §4.2, AC-P4): render() would drop the mini map and lose the reader's pan, zoom and
   full-screen overlay. Returns false anywhere else, so every call site still ends in renderKeep(). */
function tpRefresh() {
  if (S.view !== "analysis") return false;
  const pt = anLoc(); if (!pt) return false;
  const r = anRes(); if (!r || r.error) return false;
  const row = document.querySelector("[data-testid=study-row]"); if (!row) return false;
  const e = anEntity();
  const top = document.getElementById("tptop"); if (top) top.innerHTML = tpTop(pt, r, e);
  const panel = row.querySelector("[data-testid=chart-panel]");
  if (panel && e) panel.outerHTML = chartPanel(e, {});
  const note = row.querySelector(".mm-note"); if (note) note.innerHTML = tpMapNote(r);
  const ch = row.querySelector(".mm-chips"); if (ch && UI.mmFull) ch.innerHTML = mmChips();
  const secs = document.getElementById("tpsecs");
  if (secs) { secs.innerHTML = tpSections(pt, r, e); enableSort(secs); }
  anMapPaint(); anMapOverlays();
  return true;
}
function lfLabels() {
  /* labels are rebuilt on every zoom step: a name is shown only when its polygon is wide enough on screen */
  if (!LF.map || !LF.ctx) return;
  const { areas, munis, sc, micro, ind, vk } = LF.ctx; const zoom = LF.map.getZoom(); const labs = [];
  if (LF.labG) LF.map.removeLayer(LF.labG);
  if (MK.muni || zoom >= MICRO_ZOOM) {
    const px = ring => { const xs = [], ys = []; ring.forEach(q => { const c = LF.map.latLngToContainerPoint(q); xs.push(c.x); ys.push(c.y); }); return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)]; };
    const placed = [];   /* a label that would sit on top of one already placed is skipped */
    const put = (ll, html, dark) => {
      const pt = LF.map.latLngToContainerPoint(ll);
      if (placed.some(q => Math.abs(q.x - pt.x) < 70 && Math.abs(q.y - pt.y) < 26)) return;
      placed.push(pt);
      labs.push(L.marker(ll, { interactive: false, icon: L.divIcon({ className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null, html }) }));
    };
    if (micro && bydelLevel(ind)) {
      /* the figure is published per bydel, so label it once per bydel (the KK survey splits Nørrebro in two) */
      const g = {};
      areas.forEach(a => { const k = (a.kk && a.kk.bydel) || a.bydel || a.name; (g[k] = g[k] || []).push(a); });
      Object.entries(g).sort((x, y) => y[1].length - x[1].length).forEach(([name, list]) => {
        let la = 0, lo = 0, w_ = 0;
        list.forEach(a => { const c = centroid(mainRing(a)), ww = a.pop || 1; la += c[0] * ww; lo += c[1] * ww; w_ += ww; });
        const v = vk(list[0]); if (!w_ || v == null) return;
        const t = sc.t(v), dark = t != null && t > .55;
        put([la / w_, lo / w_], `<b>${esc(name)}</b><br>${fmtTight(ind)(v)}`, dark);
      });
    } else {
      /* sub-areas: a value only where the polygon is clearly wide enough, the name only when there is room for both */
      areas.slice().sort((x, y) => (y.pop || 0) - (x.pop || 0)).slice(0, 40).forEach(a => {
        const [w, h] = px(mainRing(a)); if (w < 64 || h < 26) return;
        const m = byCode[a.muni]; const own = micro && vk(a) != null; const v = own ? vk(a) : (m ? vk(m) : null);
        const t = sc.t(v), dark = t != null && t > .55; const val = v != null ? fmtTight(ind)(v) + (own ? "" : " °") : "–";
        const name = w >= 120 && h >= 36 ? `<b>${esc(a.name)}</b><br>` : "";
        put(centroid(mainRing(a)), name + val, dark);
      });
    }
  } else {
    /* municipalities: the 12 largest by name only at the national zoom; the 40 largest with values from zoom 8 */
    const big = MUNI.slice().sort((a, b) => (b.pop || 0) - (a.pop || 0)).slice(0, zoom < 8 ? 12 : 40).filter(m => munis.includes(m));
    const placed = [];   /* larger municipalities first; a label that would sit on top of one already placed is skipped */
    big.forEach(m => {
      const ma = muniAreas(m.code); let x = 0, y = 0, w = 0;
      ma.forEach(a => { const c = centroid(mainRing(a)); const ww = a.pop || 1; x += c[0] * ww; y += c[1] * ww; w += ww; });
      if (!w) return;
      const ll = [x / w, y / w], pt = LF.map.latLngToContainerPoint(ll);
      if (placed.some(q => Math.abs(q.x - pt.x) < 70 && Math.abs(q.y - pt.y) < 26)) return;
      placed.push(pt);
      const t = sc.t(vk(m)), dark = t != null && t > .55;
      labs.push(L.marker(ll, { interactive: false, icon: L.divIcon({ className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null, html: `<b>${esc(m.name)}</b>${zoom >= 8 ? `<br>${vk(m) != null ? fmtTight(ind)(vk(m)) : "–"}` : ""}` }) }));
    });
  }
  LF.labG = L.layerGroup(labs).addTo(LF.map);
}
/* ---------- Micro: buildings ---------- */
function mindSelect() {
  return `<select id="mindsel" class="indsel" aria-label="Building indicator">${MICRO_INDS.map(i => `<option value="${i.key}" ${MK.mind === i.key ? "selected" : ""}>${esc(i.label)} · ${esc(i.unit)}</option>`).join("")}</select>`;
}
function microExplain() {
  const i = curMind(), idx = MICRO_IDX[String(Number(MK.muni))] || {}; const m = byCode[MK.muni];
  const nAct = mfActive();
  return `<details class="indx" ${UI.indxOpen ? "open" : ""}>
    <summary><b>${esc(i.label)} — buildings</b><span class="tag">building level</span><span class="tag">${esc(i.unit)}</span><span class="dim">${nf(idx.n || 0, 0)} buildings in ${esc(m ? m.name : "")} · BBR ${esc((D.micro && D.micro.built) || "")}</span><i class="more">ⓘ details</i></summary>
    <div class="indx-body"><p>${{ rented_pct: "Dwellings registered as rented (incl. andel) as % of the building's dwellings with a known tenure.", vacant_pct: "Dwellings registered as 'not in use' as % of the building's dwellings — owner-reported, lags.",
      avg_m2: "Mean registered dwelling area in the building.", year: "Year of commissioning (byg026).", dwellings: "Number of current dwellings (boligtype 1–5) in the building.",
      small_pct: "Dwellings under 50 m² as % of the building's dwellings.", floors: "Number of floors (byg054)." }[i.key]}</p>
    <p class="dim"><em>Source</em> BBR via Datafordeler, buildings with ≥ ${idx.min_dwellings || (D.micro && D.micro.min_dwellings) || 2} dwellings · <em>Coverage</em> ${nf(idx.n || 0, 0)} buildings in ${esc(m ? m.name : "")} · <em>As of</em> ${esc((D.micro && D.micro.built) || "")}. Click a dot for the building's card; the address search jumps to a building and opens it.</p></div>
  </details>
  <div class="tfilters mfbar">
    <input id="mf-addr" type="search" placeholder="Find address… (Enter)" style="min-width:260px">
    <span class="hint" id="mcount"></span>
    <button class="lk mini ${UI.mfOpen ? "on" : ""}" data-mftoggle>Filters${nAct ? ` (${nAct} active)` : ""} ▾</button>
    <button class="lk mini" data-mcsv>⤓ Buildings CSV</button>
  </div>
  <div class="tfilters mfilters" id="mfpanel" ${UI.mfOpen ? "" : 'style="display:none"'}>
    <label class="hint">min. dwellings <input id="mf-mindw" type="number" min="1" step="1" value="${MF.minDw}" style="width:60px"></label>
    <label class="hint">built <input id="mf-yfrom" type="number" placeholder="from" value="${esc(MF.yFrom)}" style="width:64px"> – <input id="mf-yto" type="number" placeholder="to" value="${esc(MF.yTo)}" style="width:64px"></label>
    <select id="mf-type" class="indsel"><option value="">All building types</option>${Object.entries(MTYPE).map(([k, v]) => `<option value="${k}" ${MF.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <label class="hint">rented ≥ <input id="mf-rent" type="number" min="0" max="100" step="5" value="${MF.rentMin}" style="width:56px"> %</label>
  </div>`;
}
function mfActive() { return (MF.minDw > 2 ? 1 : 0) + (MF.yFrom ? 1 : 0) + (MF.yTo ? 1 : 0) + (MF.type ? 1 : 0) + (MF.rentMin > 0 ? 1 : 0); }
function mfBtn() { const b = document.querySelector("[data-mftoggle]"); if (b) { const n = mfActive(); b.textContent = `Filters${n ? ` (${n} active)` : ""} ▾`; } }
function microRows(code) {
  const d = MICRO[String(Number(code))]; if (!d) return [];
  /* r[0], r[1] are the building's lat/lon — the pin radius filters these like every other overlay */
  return d.b.filter(r => tpWithin(r[0], r[1]) && r[2] >= MF.minDw && (!MF.yFrom || (r[6] != null && r[6] >= Number(MF.yFrom))) && (!MF.yTo || (r[6] != null && r[6] <= Number(MF.yTo)))
    && (!MF.type || String(r[8]) === MF.type) && (!MF.rentMin || (r[3] != null && r[3] >= MF.rentMin)));
}
function loadMicro(code) {
  const k = String(Number(code)); const e = MICRO_IDX[k]; if (!e || MICRO[k] || MICRO["_loading_" + k]) return;
  MICRO["_loading_" + k] = true;
  fetch(e.file).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { MICRO[k] = d; delete MICRO["_loading_" + k]; if (microMode() && LF.map) lfLayers(); anMapOverlays(); })
    .catch(() => { MICRO["_error_" + k] = true; delete MICRO["_loading_" + k]; const el = document.getElementById("mcount"); if (el) el.textContent = "buildings could not be loaded — open the dashboard via make serve or the GitHub Pages link (not as a file)"; });
}
function microPopup(r, code) {
  const kom = code || MK.muni;
  const m = byCode[kom]; const rooms = r.slice(9, 13); const rt = rooms.reduce((a, b) => a + b, 0);
  const row = (l, v) => `<span class="lfrow"><span>${l}</span><b>${v}</b></span>`;
  const d = MICRO[String(Number(kom))]; const same = r[16] && d ? d.b.filter(x => x[16] === r[16]).length - 1 : 0;
  const area = areaAt(r[0], r[1]);
  return `<div class="lfpop"><b>${r[15] ? esc(r[15]) : (esc(MTYPE[r[8]] || "building") + " · " + r[2] + " dwellings")}</b><span class="dim">${r[15] ? esc(MTYPE[r[8]] || "building") + " · " : ""}${area ? esc(area.name) + " · " : ""}${m ? esc(m.name) : ""}${r[16] ? ` · BFE ${esc(r[16])}${same > 0 ? ` (+${same} more building${same > 1 ? "s" : ""} on this property)` : ""}` : ""} · BBR ${esc(r[14])}…</span>
    ${area ? `<span class="lfact"><button class="lk mini primary" data-go="${withQ(pageOf(area))}">${area.bydel != null ? "Quarter" : "Postal code"}: ${esc(area.name)} ›</button>${m ? `<button class="lk mini" data-go="${withQ(pageOf(m))}">${esc(m.name)} ›</button>` : ""}</span>` : ""}
    <span class="lfsec">Building</span>${row("Built", r[6] ?? "–")}${row("Floors", r[7] ?? "–")}${row("Dwellings", r[2])}
    <span class="lfsec">Dwellings</span>${row("Rented (incl. andel)", r[3] != null ? r[3] + " %" : "–")}${row("Unoccupied", r[4] != null ? r[4] + " %" : "–")}${row("Ø size", r[5] != null ? r[5] + " m²" : "–")}${row("< 50 m²", r[13] != null ? r[13] + " %" : "–")}
    ${rt ? row("Rooms 1 / 2 / 3 / 4+", rooms.map(x => nf(x / rt * 100, 0) + "%").join(" / ")) : ""}
    <span class="lfact"><a class="lk mini" target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${r[0]}&mlon=${r[1]}#map=18/${r[0]}/${r[1]}">Open in OpenStreetMap</a>${r[16] ? `<a class="lk mini" target="_blank" rel="noopener" href="https://ois.dk/">OIS (BFE ${esc(r[16])})</a>` : ""}</span></div>`;
}
function microFind(text) {
  /* zoom to the first building whose address contains the text and open its card; the filters are widened if it is filtered out */
  const q = (text || "").trim().toLowerCase(); const d = MICRO[String(Number(MK.muni))]; if (!q || !d || !LF.map) return;
  const norm = x => (x || "").toLowerCase().replace(/\s+/g, " ");
  const r = d.b.find(x => norm(x[15]).startsWith(q)) || d.b.find(x => norm(x[15]).includes(q));
  const cnt = document.getElementById("mcount");
  if (!r) { if (cnt) cnt.textContent = `no building matching "${text}" in ${(byCode[MK.muni] || {}).name || "this municipality"} (≥ ${d.meta.min_dwellings} dwellings)`; return; }
  let m = (LF.microMarks || []).find(mk => mk._row === r);
  if (!m) { MF.minDw = Math.min(MF.minDw, r[2]); MF.yFrom = ""; MF.yTo = ""; MF.type = ""; MF.rentMin = 0; ["mf-mindw", "mf-yfrom", "mf-yto", "mf-rent"].forEach((id, i) => { const el = document.getElementById(id); if (el) el.value = [MF.minDw, "", "", 0][i]; }); const t = document.getElementById("mf-type"); if (t) t.value = ""; lfLayers(); m = (LF.microMarks || []).find(mk => mk._row === r); }
  LF.map.setView([r[0], r[1]], Math.max(LF.map.getZoom(), 16));
  setTimeout(() => { if (m) m.openPopup(); }, 350);
}
function exportMicroCsv() {
  const d = MICRO[String(Number(MK.muni))]; if (!d) return;
  const rows = microRows(MK.muni); const cols = d.meta.cols;
  downloadCsv([["municipality"].concat(cols).join(";")].concat(rows.map(r => [(byCode[MK.muni] || {}).name || MK.muni].concat(r).map(v => String(v ?? "")).join(";"))), `macro-dashboard-dk_buildings_${MK.muni}_${d.meta.built}.csv`);
}
/* dot radius grows with zoom so buildings separate when zoomed in and do not blanket the municipality when zoomed out */
function microRadius(dw, zoom) { const z = zoom != null ? zoom : (LF.map ? LF.map.getZoom() : 12); const k = z < 12 ? .7 : z < 13.5 ? 1.0 : z < 15 ? 1.5 : 2.2; return Math.max(2, Math.min(16, k * Math.sqrt(dw) + 1)); }
function lfMicroLayers() {
  const code = MK.muni; const d = MICRO[String(Number(code))];
  lfDrop("areaG", "labG", "microG");
  LF.level = "micro-b" + code; LF.ctx = null;
  /* area outlines only, so the dots read against the basemap */
  LF.areaG = L.layerGroup(muniAreas(code).map(a => L.polygon(a.rings, { color: "#141C18", weight: 1, fill: false, opacity: .35, interactive: false }))).addTo(LF.map);
  const cnt = document.getElementById("mcount");
  if (!d) { loadMicro(code); if (cnt && !MICRO["_error_" + String(Number(code))]) cnt.textContent = "loading buildings…"; return; }
  const ind = curMind(), rows = microRows(code), c = ind.col;
  /* same quintile classes as the area maps, computed on the buildings that pass the filters */
  const sc = scaleOf(rows, r => r[c], ind.breaks, ind); const t = sc.t;
  const marks = rows.map(r => { const tt = t(r[c]);
    const m = L.circleMarker([r[0], r[1]], { renderer: amOf(LF.map).base, radius: microRadius(r[2]), color: "#141C18", weight: .6, opacity: .7, fillColor: tt == null ? "#C4CBC4" : mkShade(tt, "micro:" + ind.key), fillOpacity: .85 });
    m._dw = r[2]; m._row = r; m.bindPopup(() => microPopup(r, code), { maxWidth: 440, autoPanPadding: [24, 24] }); return m; });
  LF.microG = L.layerGroup(marks).addTo(LF.map); LF.microMarks = marks;
  tpLayers();
  setLegend("maplegend", sc, ind, "micro:" + ind.key, "buildings with ≥ 2 dwellings · dot size = dwellings");
  lfClimateLayers();
  lfInfraLayers();
  lfPublicLayers();
  lfServicesLayers();   /* buildings mode keeps every overlay, services and climate included */
  if (cnt) cnt.textContent = `${nf(rows.length, 0)} of ${nf(d.meta.n, 0)} buildings · ${nf(rows.reduce((s_, r) => s_ + r[2], 0), 0)} dwellings`;
}
function lfLayers() {
  if (LF.map && microMode()) { lfMicroLayers(); return; }
  lfDrop("microG");
  if (!LF.map) return;
  const zoom = LF.map.getZoom();
  const ind = curInd();
  /* a drilled-in municipality always shows its sub-areas, whatever the zoom (small screens fit it below zoom 10) */
  const fine = !!MK.muni || zoom >= MICRO_ZOOM;
  const micro = fine && (cphMode() ? cphOwn(ind.key) : ind.level === "postnr");
  LF.level = (fine ? "micro" : zoom < 8 ? "national" : "macro") + (cphMode() ? "-cph" : "") + (MK.muni || "");
  lfDrop("areaG", "labG");
  const areas = MK.muni ? muniAreas(MK.muni) : AREAS;
  const munis = MK.muni ? [byCode[MK.muni]].filter(Boolean) : MUNI;
  const vk = o => V(o, ind.key);
  const sc = scaleOf(micro ? areas.filter(a => vk(a) != null) : munis, vk, null, ind);
  const polys = [];
  areas.forEach(a => {
    const m = byCode[a.muni];
    const src = micro && vk(a) != null ? a : m;
    const t = src ? sc.t(vk(src)) : null;
    const w = fine ? 1.4 : 0.8;
    const p = L.polygon(a.rings, { color: "#FFFFFF", weight: w, fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .72, smoothFactor: 1 });
    /* registered before bindPopup, so the clicked point is known by the time the popup builds itself */
    p.on("click", ev => { LF.climPt = ev.latlng; });
    p.bindPopup(() => lfPopup(a, m), { maxWidth: 560, maxHeight: 560, autoPanPadding: [24, 24] });
    p.on("mouseover", () => p.setStyle({ weight: 2.2, color: "#141C18" })); p.on("mouseout", () => p.setStyle({ weight: w, color: "#FFFFFF" }));
    polys.push(p);
  });
  LF.areaG = L.layerGroup(polys).addTo(LF.map);
  LF.ctx = { areas, munis, sc, micro, ind, vk };
  lfClimateLayers();
  lfInfraLayers();
  lfPublicLayers();
  lfServicesLayers();
  lfLabels();
  setLegend("maplegend", sc, ind, ind.key, isClim(ind.key) ? climLegendNote(ind) : micro ? (cphMode() ? "quarters" + (bydelLevel(ind) ? " · ^ one figure per bydel" : "") : "postal codes") : (ind.level === "postnr" && !MK.muni ? "municipalities · zoom in for postal codes" : "municipalities" + (fine ? ` · ° ${cphMode() ? "quarters" : "postal codes"} take the municipality value` : "")));
  if (LF.ownG) { LF.map.removeLayer(LF.ownG); LF.ownG = null; }
  if (MK.own && D.portfolio) {
    const marks = D.portfolio.properties.filter(p => p.lat != null).map(p => {
      const units = p.units || 20, pressure = ((p.vac || 0) + (p.notice || 0)) / Math.max(1, units);
      const m = L.circleMarker([p.lat, p.lon], { radius: Math.max(5, Math.min(11, Math.sqrt(units) * 1.15)), color: "#141C18", weight: 2, fillColor: pressure > .12 ? "#B5391F" : pressure > .06 ? "#D9A32E" : "#1C6B5C", fillOpacity: .92 });
      m.bindTooltip(`<b>${esc(p.name)}</b><br>${esc(p.address || "")}<br>${units} units · ${p.vac || 0} vacant · ${p.notice || 0} under notice`);
      return m;
    });
    LF.ownG = L.layerGroup(marks).addTo(LF.map);
  }
  tpLayers();
}
/* Leaflet's canvas renderer draws into `this._ctx`, which exists only while the renderer is on
   a map. A redraw that lands just after a map is torn down — an async building/services/public
   file resolving, or a filter applied mid-rebuild — reaches an undefined context and throws
   "Cannot read properties of undefined (reading 'save')". Reproduced exactly by calling
   _redraw() on a renderer that was never added, or was removed. Guarded once at the prototype,
   so it holds for the macro map, the area map, the Analysis mini map and every future one. */
if (typeof L !== "undefined" && L.Canvas && L.Canvas.prototype && !L.Canvas.prototype._amGuarded) {
  const cp = L.Canvas.prototype, _redraw = cp._redraw, _update = cp._update;
  cp._amGuarded = true;
  cp._redraw = function () { if (!this._map || !this._ctx) return; return _redraw.apply(this, arguments); };
  cp._update = function () { if (!this._map) return; return _update.apply(this, arguments); };
}
/* The same medicine one level up. A zoom animation started by fitBounds/setView keeps running for
   ~250 ms after the map it belongs to was torn down (a route change is exactly that long), and the
   transition's end handler then asks a pane that no longer exists for its position:
   "Cannot read properties of undefined (reading '_leaflet_pos')". Leaflet has no teardown check of
   its own, so it gets one here — once, at the prototype, for every map this app ever builds. */
if (typeof L !== "undefined" && L.Map && L.Map.prototype && !L.Map.prototype._amGuarded) {
  const mp = L.Map.prototype, _end = mp._onZoomTransitionEnd, _move = mp._move, _pos = mp._getMapPanePos;
  mp._amGuarded = true;
  mp._onZoomTransitionEnd = function () { if (!this._mapPane) return; return _end.apply(this, arguments); };
  mp._move = function () { if (!this._mapPane) return this; return _move.apply(this, arguments); };
  mp._getMapPanePos = function () { if (!this._mapPane) return L.point(0, 0); return _pos.apply(this, arguments); };
}

/* ---------- map lifecycle: one owner for every Leaflet instance ---------- */
/* Every map this app builds lives under one of these keys in LF, together with the layer groups
   drawn on it. `render()` replaces the page body wholesale, so a map whose container has just been
   thrown away has to be told before its async callers reach it — the public, services, climate and
   micro files all resolve minutes later and all end with "if (LF.map) redraw". dropMap() is the one
   exit door: it stops the animations, removes the map and forgets every group that was on it. */
const LF_MAPS = {
  map:   ["areaG", "labG", "microG", "infraG", "infraHitG", "infraStG", "infraLabG",
          "pubG", "pubLabG", "srvG", "srvStG", "climAreaG", "climZoneG", "ownG", "tpG"],
  amap:  [],
  anmap: ["anInfraG", "anInfraHitG", "anPubG", "anMicroG", "anClimG", "anPinG"],
  pmap:  [],
};
const LF_MAP_KEYS = Object.keys(LF_MAPS);
/* the test hook (UI spec §10): every live Leaflet instance, in the order the keys are declared */
function syncMaps() { if (typeof window !== "undefined") window.__maps = LF_MAP_KEYS.map(k => LF[k]).filter(Boolean); }
function dropMap(key) {
  const m = LF[key];
  LF[key] = null;
  (LF_MAPS[key] || []).forEach(k => { LF[k] = null; });
  /* the macro map's caches describe what is drawn on it; with the map gone they describe nothing */
  if (key === "map") { LF.level = null; LF.ctx = null; LF.pubDrawn = null; LF.srvDrawn = null;
                       LF.climDrawn = null; LF.microMarks = null; LF.tpMark = null; }
  if (m) { try { m.off(); m.stop(); m.remove(); } catch (e) {} m._am = null; }
  syncMaps();
}
function dropMaps() { LF_MAP_KEYS.forEach(dropMap); }
syncMaps();   /* the hook exists from load on, empty until the first map is built */
/* Two renders can land inside one frame — a hashchange, then the re-render an async file triggers —
   and each schedules its own map init. Only the last one may build: an init that starts while the
   previous map is still animating is root cause 3 of ENG_BRIEF §2.4. One timer, last one wins. */
function mapInit(fn) {
  if (LF.initTimer) clearTimeout(LF.initTimer);
  LF.initTimer = setTimeout(() => { LF.initTimer = null; fn(); }, 0);
}
/* Panes and canvas renderers belong to one map, not to the app. A renderer built for the macro map
   draws into *that* map's pane; handing it to the mini map is what threw "Cannot read properties of
   undefined (reading 'appendChild')" in v2.6 (ENG_BRIEF §2.4, root cause 1), and the two follow-on
   errors ('intersects', 'lat') were the same renderer failing again afterwards. Each map now gets
   its own set, on `map._am`, and every builder reads the set of the map it is drawing on.
   Stacking, unchanged: services above the choropleth, public buildings one step lower, climate
   zones lowest and click-through — a zone fill must never swallow the click that opens a popup. */
function mapPanes(map) {
  if (!map) return null;
  if (map._am) return map._am;
  const pane = (name, z, noPointer) => {
    if (!map.getPane(name)) { map.createPane(name); const p = map.getPane(name); p.style.zIndex = z; if (noPointer) p.style.pointerEvents = "none"; }
  };
  pane("srvpane", 450); pane("pubpane", 440); pane("climpane", 430, true);
  map._am = { base: L.canvas({ padding: .3 }), srv: L.canvas({ pane: "srvpane", padding: .3 }),
              pub: L.canvas({ pane: "pubpane", padding: .3 }), clim: L.canvas({ pane: "climpane", padding: .3 }) };
  return map._am;
}
const amOf = map => (map ? mapPanes(map) : null);
/* Remove a layer group from the map and forget it in one step. A group left in LF after its
   map is gone is exactly what later hands a dead renderer a redraw, so the two always happen
   together and in this order. */
function lfDrop() {
  for (let i = 0; i < arguments.length; i++) {
    const k = arguments[i], g = LF[k];
    if (g && LF.map) { try { LF.map.removeLayer(g); } catch (e) {} }
    LF[k] = null;
  }
}
/* Quick view jumps. These move the camera and nothing else: no municipality is selected, the
   breadcrumb, level and indicator are untouched and no popup opens — zooming is not selecting.
   Copenhagen is København + Frederiksberg together, because the two read as one city. */
const MAP_JUMPS = {
  cph: { label: "Copenhagen", key: "C", codes: [CPH_MUNI, "147"] },
  dk:  { label: "Denmark",    key: "D", codes: null },
};
function mapJump(id) {
  const j = MAP_JUMPS[id]; if (!j) return;
  asrchOpen(false);                       /* the jumps live in the search dropdown now (spec §5.1) */
  if (!LF.map) return;
  const b = boundsOf(j.codes ? AREAS.filter(a => j.codes.includes(a.muni)) : AREAS);
  if (b) LF.map.fitBounds(b, { padding: [24, 24] });
}
function lfInit() {
  if (S.view !== "makro") return;                 /* a render for another view got in first */
  const el = document.getElementById("lfmap");
  if (!el || typeof L === "undefined") return;
  dropMap("map");
  const map = L.map(el, { center: LF.center, zoom: LF.zoom, scrollWheelZoom: true, zoomSnap: 0.5, zoomDelta: 1, wheelPxPerZoomLevel: 60, wheelDebounceTime: 20 });
  LF.map = map;
  /* this map's own panes and canvas renderers (services / public buildings / climate zones) */
  mapPanes(map);
  syncMaps();
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap",
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Boundaries: DAGI, Klimadatastyrelsen' }).addTo(map);
  map.on("moveend", () => { const c = map.getCenter(); LF.center = [c.lat, c.lng]; LF.zoom = map.getZoom();
    if (MK.pub) { lfPublicLayers(); lfPublicLabels(); }
    /* services draw only what is in the viewport, so a pan is a redraw, not just a load */
    if (MK.srv) lfServicesLayers();
    if (climOn()) lfClimateLayers(true); });
  /* Leaflet stops click propagation inside popups, so page links in popups are wired here */
  map.on("popupopen", ev => { const el = ev.popup.getElement(); if (!el) return;
    el.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
    el.querySelectorAll("[data-tp]").forEach(b => b.addEventListener("click", () => tpAction(b.dataset.tp, b)));
    el.querySelectorAll("[data-ind]").forEach(b => b.addEventListener("click", () => { MK.ind = b.dataset.ind; if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST; go(hashFor()); }));
    const lab = el.querySelector("#tplab");
    if (lab) { lab.addEventListener("input", () => { TP.label = lab.value.trim() || TP_LABEL; syncHash(); if (LF.tpMark) LF.tpMark.options.title = TP.label; });
               lab.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); lab.blur(); } }); }
    /* re-fit the popup when "all values" opens — popup.update() would rebuild the content and close the fold again */
    el.querySelectorAll("details").forEach(d => d.addEventListener("toggle", () => { const pp = ev.popup; if (pp._updateLayout) { pp._updateLayout(); pp._updatePosition(); pp._adjustPan(); } })); });
  map.on("zoomend", () => {
    /* rebuild polygons only when the display level changes — rebuilding on every pan would kill open popups */
    lfInfraLabels();
    if (MK.pub) lfPublicLayers(true);            /* the zoom rule changes which public rows are drawn */
    if (MK.srv) lfServicesLayers(true);          /* likewise: each services category has its own zoom floor */
    if (climOn()) lfClimateLayers(true);         /* the surge zones have a zoom floor of their own */
    if (microMode()) { (LF.microMarks || []).forEach(m => m.setRadius(microRadius(m._dw))); return; }
    const z = map.getZoom(), fine = !!MK.muni || z >= MICRO_ZOOM, lvl = (fine ? "micro" : z < 8 ? "national" : "macro") + (cphMode() ? "-cph" : "") + (MK.muni || "");
    if (lvl !== LF.level) lfLayers(); else if (fine) lfLabels();
  });
  lfLayers();
  applyPendingFit();
}

/* ---------- Full-screen map ---------- */
function toggleFullscreen() {
  const el = document.getElementById("mapcard"); if (!el) return;
  if (document.fullscreenElement) { document.exitFullscreen(); return; }
  if (el.requestFullscreen) el.requestFullscreen().catch(() => el.classList.toggle("fs-fallback"));
  else el.classList.toggle("fs-fallback");
  setTimeout(() => LF.map && LF.map.invalidateSize(), 300);
}
document.addEventListener("fullscreenchange", () => {
  const b = document.querySelector("[data-fs]"); if (b) b.textContent = document.fullscreenElement ? "⤡ Exit full screen" : "⤢ Full screen";
  setTimeout(() => LF.map && LF.map.invalidateSize(), 250);
});

/* ---------- Chart generator ---------- */
const CH_COLORS = ["#1C6B5C", "#B07A1E", "#40547F", "#B0331B", "#82346C", "#5C5F52", "#6E8C5E", "#C08A24"];
function chEntity(id) {
  const [t, c] = id.split(":");
  if (t === "kommune" && byCode[c]) return { id, type: t, o: byCode[c], name: byCode[c].name, inds: IND, peers: MUNI, peerLabel: "municipalities", publisher: "DST" };
  if (t === "postnr" && byNr[c]) return { id, type: t, o: byNr[c], name: `${c} ${byNr[c].name}`, inds: IND, peers: AREAS, peerLabel: "postal codes", muni: byCode[byNr[c].muni] };
  if (t === "kvarter" && byQ[c]) return { id, type: t, o: byQ[c], name: byQ[c].name + " (CPH)", inds: IND_Q, peers: CPH.areas, peerLabel: "quarters", muni: byCode[CPH_MUNI], publisher: "Københavns Kommune" };
  return null;
}
function chartAdd(id, text) {
  if (!id && text) { const q = text.trim(); const o = AREA_OPTS.find(x => x.t === q) || AREA_OPTS.find(x => x.k.some(k => k === q.toLowerCase())) || AREA_OPTS.find(x => x.k.some(k => k.startsWith(q.toLowerCase())));
    if (!o) return; id = o.h.startsWith("map/") ? "kommune:" + o.h.slice(4) : o.h.replace("area/", "").replace("/", ":"); }
  if (!id || CH.areas.includes(id) || CH.areas.length >= 8) return;
  CH.areas.push(id); syncHash(); renderKeep();
  const q = document.getElementById("chq"); if (q) { q.value = ""; q.focus(); }
}
function chartInd() { return chartPool().find(i => i.key === CH.ind) || IND[0]; }
/* Denmark as a whole (DST area 000) where the build has it — drawn as a dashed reference line */
const NAT = D.national || null;
/* quarterly series: indicator.q_periods + entity.q[key] (built for the rolling-4Q Safety calcs); any indicator
   that has one gets the Yearly | Quarterly toggle */
const qPeriods = i => (i && i.q_periods) || [];
const isQ = p => /K\d$/.test(p);
/* the charted indicators: the selected one plus overlays of the same group and unit format */
const overlayCands = main => IND.filter(i => i.key !== main.key && i.group === main.group && i.fmt === main.fmt);
function chartInds() { const main = chartInd(), c = overlayCands(main); return [main].concat(CH.ov.map(k => c.find(i => i.key === k)).filter(Boolean)); }
const chartQ = () => CH.fq === "q" && chartInds().every(i => qPeriods(i).length > 1);
/* value of indicator i for entity o at a year ("2025") or a quarter ("2025K3") */
function chVal(o, i, p) {
  if (!o) return null;
  if (!isQ(p)) return V(o, i.key, p);
  const k = qPeriods(i).indexOf(p), arr = o.q && o.q[i.key];
  return k >= 0 && arr ? arr[k] ?? null : null;
}
/* periods on the x axis: each indicator's own reach (min year in its series), years or quarters, cut to from/to */
function chartYears() {
  const ents = CH.areas.map(chEntity).filter(Boolean); const pool = (ents.length ? ents.map(e => e.o) : MUNI).concat(MUNI, NAT ? [NAT] : []);
  const inds = chartInds();
  const all = [...new Set(inds.flatMap(i => chartQ() ? qPeriods(i) : histYears(i.key, pool)))].sort();
  const ys = all.filter(y => (!CH.y0 || y.slice(0, 4) >= CH.y0) && (!CH.y1 || y.slice(0, 4) <= CH.y1)); return ys.length >= 2 ? ys : all;
}
function chartMode() {
  /* A Climate indicator has no year series at all: it is published at three horizons, so the x axis
     is the horizon and the mode segments do not apply (spec §5.4). Nothing the reader can pick would
     draw a line through Today · 2070 · 2120 — so the family decides, not the segment. */
  if (isClim(CH.ind)) return "clim";
  if (CH.mode !== "auto") return CH.mode;
  return chartYears().length >= 2 ? "line" : "bar";
}
function chartAutoTitle() {
  if (chartMode() === "dist") return `${(DIST_DEFS[CH.dist] || DIST_DEFS.size)[0]} — share of dwellings (BBR)`;
  const inds = chartInds(), i = inds[0];
  const lab = inds.length > 1 ? inds.map(x => x.short || x.label).join(", ") : i.label;
  const unit = optLabel(i).slice(i.label.length);   /* " · rolling 4Q", " · % / yr" — the unit parts the label does not already say */
  const mode = chartMode();
  return `${lab}${unit}${mode === "clim" ? " — by horizon" : mode === "bar" ? " — latest" : chartQ() ? " — quarterly" : ""}`;
}
function chartSeries() {
  const inds = chartInds(), ind = inds[0], ys = chartYears(); const ents = CH.areas.map(chEntity).filter(Boolean);
  const multi = inds.length > 1; const series = []; let k = 0;
  inds.forEach(i => {
    const first = k;
    ents.forEach(e => { const own = e.inds.some(x => x.key === i.key);
      /* postal codes, and quarters on indicators the quarter layer lacks, take the municipality's series (°) */
      const inh = !!e.muni && (e.type === "postnr" || !cphOwn(i.key));
      const val = y => { const v = chVal(e.o, i, y); return v != null ? v : inh ? chVal(e.muni, i, y) : null; };
      /* on a projection chart the series name carries its publisher, so two runs on one chart can
         never be mistaken for one series (docs/FORECAST.md §4) */
      const pubTag = i.proj && e.publisher ? ` · ${e.publisher}` : "";
      series.push({ name: (multi ? `${e.name} · ${i.short || i.label}` : e.name) + pubTag, kind: "area", color: CH_COLORS[k++ % CH_COLORS.length], pts: ys.map(y => ({ y, v: own ? val(y) : null })),
                    inherited: own && inh && V(e.o, i.key) == null && V(e.muni, i.key) != null });
    });
    if (CH.nat && NAT) series.push({ name: multi ? `Denmark · ${i.short || i.label}` : "Denmark", kind: "national", color: ents.length ? CH_COLORS[first % CH_COLORS.length] : "#16170F", dash: true, pts: ys.map(y => ({ y, v: chVal(NAT, i, y) })) });
  });
  if (CH.median) { const pool = ents.length && ents.every(e => e.type === "kvarter") && cphOwn(ind.key) ? CPH.areas : MUNI;
    series.push({ name: pool === MUNI ? "Denmark — median of municipalities" : "Copenhagen — median of quarters", kind: "median", color: "#8A8C81", dash: true, pts: ys.map(y => ({ y, v: median(pool.map(p => chVal(p, ind, y))) })) }); }
  return { ind, inds, ys, series: series.filter(s => s.pts.some(p => p.v != null)) };
}
/* series breaks from the registry (`breaks`), placed on the axis: "2013K3" → that quarter or year 2013, "2023" → 2023 / 2023K1 */
function chartBreaks(inds, ys) {
  const seen = new Map(); inds.forEach(i => (i.breaks || []).forEach(b => { if (!seen.has(b.at)) seen.set(b.at, b); }));
  return [...seen.values()].map(b => ({ ...b, idx: ys.indexOf(isQ(ys[0] || "") ? (isQ(b.at) ? b.at : b.at + "K1") : b.at.slice(0, 4)) })).filter(b => b.idx >= 0);
}
/* self-contained SVG (inline styles, title, legend) so the same markup renders on screen and rasterises to PNG */
function chartSvg(withTitle) {
  const mode = chartMode();
  if (mode === "dist") return chartSvgDist(withTitle);
  if (mode === "clim") return chartSvgClim(withTitle);
  if (mode === "bar") return chartSvgBar(withTitle);
  return chartSvgLine(withTitle);
}
const CH_FONT = "Inter, 'Helvetica Neue', Arial, sans-serif", CH_MONO = "'IBM Plex Mono', Menlo, monospace";
function chTitleBlock(withTitle, ind, L0, sub) {
  return withTitle ? `<text x="${L0}" y="40" font-family="${CH_FONT}" font-size="24" font-weight="600" fill="#16170F" id="chsvgtitle">${esc(CH.title || chartAutoTitle())}</text><text x="${L0}" y="64" font-family="${CH_MONO}" font-size="12" fill="#8A8C81">${esc(sub != null ? sub : (ind.desc || ""))}</text>` : "";
}
function chFoot(L0, H, ind, extra) {
  const src = (ind.source || ""); const short = src.length > 90 ? src.slice(0, 88) + "…" : src;
  return `<text x="${L0}" y="${H - 14}" font-family="${CH_MONO}" font-size="11" fill="#8A8C81">Source: ${esc(short)} · Macro Dashboard — Denmark, open data · built ${esc((D.meta && D.meta.built) || "")}${extra || ""}</text>`;
}
/* bars: latest value per selected area, sorted, median as a dashed marker */
function chartSvgBar(withTitle) {
  const ind = chartInd(); const ents = CH.areas.map(chEntity).filter(Boolean);
  const rows = ents.map((e, k) => { const own = e.inds.some(i => i.key === ind.key); const v = own ? (V(e.o, ind.key) ?? (e.type === "postnr" && e.muni ? V(e.muni, ind.key) : null)) : null;
    return { name: e.name, color: CH_COLORS[k % CH_COLORS.length], v, inh: own && V(e.o, ind.key) == null && v != null }; }).filter(r => r.v != null).sort((a, b) => b.v - a.v);
  const W = 1200, H = 640, L0 = 96, R = 170, T0 = withTitle ? 96 : 30, B = 70;
  if (!rows.length) return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/><text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${CH_FONT}" font-size="18" fill="#8A8C81">Add areas with the search box — nothing to plot yet</text></svg>`;
  const pool = ents.length && ents.every(e => e.type === "kvarter") ? CPH.areas : MUNI; const med = CH.median ? median(pool.map(p => V(p, ind.key))) : null;
  const vals = rows.map(r => r.v).concat(med != null ? [med] : []); const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1;
  const labW = 260; const x0 = L0 + labW, x1 = W - R; const x = v => x0 + (v - lo) / (hi - lo || 1) * (x1 - x0);
  const rowH = Math.min(52, (H - T0 - B) / rows.length), bh = rowH * .62;
  const bars = rows.map((r, i) => { const y = T0 + i * rowH + (rowH - bh) / 2; return `<text x="${x0 - 12}" y="${(y + bh / 2 + 5).toFixed(1)}" text-anchor="end" font-family="${CH_FONT}" font-size="15" fill="#16170F">${esc(r.name)}${r.inh ? " °" : ""}</text>
    <rect data-series="${esc(r.name)}" data-series-kind="area" x="${x(Math.min(0, r.v)).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.abs(x(r.v) - x(0)).toFixed(1)}" height="${bh.toFixed(1)}" fill="${r.color}" rx="3"/>
    <text x="${(x(Math.max(0, r.v)) + 8).toFixed(1)}" y="${(y + bh / 2 + 5).toFixed(1)}" font-family="${CH_MONO}" font-size="14" fill="#16170F">${esc(fmtOf(ind)(r.v))}</text>`; }).join("");
  const medLine = med != null ? `<line x1="${x(med).toFixed(1)}" x2="${x(med).toFixed(1)}" y1="${T0 - 8}" y2="${T0 + rows.length * rowH}" stroke="#5C5F52" stroke-width="2" stroke-dasharray="7 5"/><text x="${(x(med) + 6).toFixed(1)}" y="${T0 - 12}" font-family="${CH_MONO}" font-size="12" fill="#5C5F52">${pool === MUNI ? "DK median" : "CPH median"} ${esc(fmtOf(ind)(med))}</text>` : "";
  const asof = asofText(ind);
  return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, `${ind.desc || ""}${asof ? " · as of " + asof : ""}`)}
    <line x1="${x(0).toFixed(1)}" x2="${x(0).toFixed(1)}" y1="${T0}" y2="${T0 + rows.length * rowH}" stroke="#E6E6E0"/>${bars}${medLine}${chFoot(L0, H, ind, rows.some(r => r.inh) ? " · ° = municipality value" : "")}</svg>`;
}
/* ---- Climate indicators: the x axis is the horizon, not the year (spec §5.4, AC-C2) ----
   Klimaatlas and Kystdirektoratet publish three periods, so there are three grouped bars per area
   and nothing is drawn between them: an interpolated line would be a model, and this layer makes
   none. Where the publisher gives a low–high range for a horizon it is drawn as a whisker. */
const climRangeAt = (o, k, h) => {
  const km = climKom(o && (o.code || o.muni)); const e = km && km[k];
  const r = e && e.range && e.range[h];
  return r && r.low != null && r.high != null ? r : null;
};
/* The surge keys' registry `desc` was built with the default horizon baked into the sentence
   ("… inside the Today 100-year storm-surge zone"). On a chart that draws all three horizons that
   sentence is wrong, and this layer never edits data — so the horizon word is dropped here and the
   axis names the horizons instead. Data task logged in docs/v3/DECISIONS.md. */
const climDescNeutral = d => String(d || "").replace(/\bthe (?:Today|2070|2120) (\d)/g, "the $1");
function chartSvgClim(withTitle) {
  const ind = chartInd(); const ents = CH.areas.map(chEntity).filter(Boolean);
  const hz = CLIM_HZ || ["today", "2070", "2120"];
  const W = 1200, H = 640, L0 = 96, R = 30, T0 = withTitle ? 100 : 44, B = 150;
  const open = `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>`;
  const sub = `${climDescNeutral(ind.desc)} · three published horizons, nothing drawn between them`;
  if (!ents.length) return `${open}${chTitleBlock(withTitle, ind, L0, sub)}<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${CH_FONT}" font-size="18" fill="#8A8C81">Add areas with the search box — nothing to plot yet</text></svg>`;
  /* every area is read at every horizon: the climate index carries all three, whatever the pill says */
  const rows = ents.map((e, k) => ({ name: e.name, color: CH_COLORS[k % CH_COLORS.length],
    vals: hz.map(h => climValue(e.o, ind.key, h)), rng: hz.map(h => climRangeAt(e.o, ind.key, h)) }));
  const med = CH.median ? hz.map(h => median(MUNI.map(m => climValue(m, ind.key, h)))) : null;
  const all = rows.flatMap(r => r.vals).concat(rows.flatMap(r => r.rng.flatMap(x => x ? [x.low, x.high] : [])))
                  .concat(med || []).filter(v => v != null);
  const hi = all.length ? Math.max(0, ...all) || 1 : 1, lo = all.length ? Math.min(0, ...all) : 0;
  const y = v => T0 + (1 - (v - lo) / (hi - lo || 1)) * (H - T0 - B);
  const gw = (W - L0 - R) / hz.length;                       /* one group per horizon */
  const bw = Math.min(64, (gw * .72) / rows.length);
  const pad0 = (gw - bw * rows.length) / 2;                  /* the bars sit under their tick label */
  const ticks = [0, .25, .5, .75, 1].map(t => lo + t * (hi - lo || 1));
  /* the three x-axis tick labels — Today · 2070 · 2120, marked so a test can find exactly these */
  const xticks = hz.map((h, g) => `<text data-hztick="${esc(h)}" x="${(L0 + g * gw + gw / 2).toFixed(1)}" y="${H - B + 26}" text-anchor="middle" font-family="${CH_MONO}" font-size="13" fill="#4A4C43">${esc(hzShort(h))}</text>
    <text x="${(L0 + g * gw + gw / 2).toFixed(1)}" y="${H - B + 44}" text-anchor="middle" font-family="${CH_MONO}" font-size="10.5" fill="#8A8C81">${esc(CLIM_ZONE_YEAR[h] === "2020" ? "1981–2010" : h === "2070" ? "2041–70" : "2071–2100")}</text>`).join("");
  const bars = hz.map((h, g) => rows.map((r, k) => {
    const v = r.vals[g]; if (v == null) return `<text x="${(L0 + g * gw + pad0 + k * bw + bw / 2).toFixed(1)}" y="${(y(Math.max(lo, 0)) - 8).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="11" fill="#8A8C81">–</text>`;
    const x0 = L0 + g * gw + pad0 + k * bw, top = y(Math.max(v, 0)), base = y(Math.max(lo, 0));
    const rg = r.rng[g];
    return `<rect data-series="${esc(r.name)}" data-series-kind="area" data-hz="${esc(h)}" x="${x0.toFixed(1)}" y="${top.toFixed(1)}" width="${(bw * .82).toFixed(1)}" height="${Math.max(1, Math.abs(base - top)).toFixed(1)}" fill="${r.color}" rx="2"><title>${esc(r.name)} ${esc(hzShort(h))}: ${fmtOf(ind)(v)}</title></rect>`
      + (rg ? `<line x1="${(x0 + bw * .41).toFixed(1)}" x2="${(x0 + bw * .41).toFixed(1)}" y1="${y(rg.high).toFixed(1)}" y2="${y(rg.low).toFixed(1)}" stroke="#16170F" stroke-width="1.5"/>
              <line x1="${(x0 + bw * .2).toFixed(1)}" x2="${(x0 + bw * .62).toFixed(1)}" y1="${y(rg.high).toFixed(1)}" y2="${y(rg.high).toFixed(1)}" stroke="#16170F" stroke-width="1.5"><title>published range ${fmtOf(ind)(rg.low)} – ${fmtOf(ind)(rg.high)}</title></line>
              <line x1="${(x0 + bw * .2).toFixed(1)}" x2="${(x0 + bw * .62).toFixed(1)}" y1="${y(rg.low).toFixed(1)}" y2="${y(rg.low).toFixed(1)}" stroke="#16170F" stroke-width="1.5"/>` : "")
      + `<text x="${(x0 + bw * .41).toFixed(1)}" y="${(Math.min(top, rg ? y(rg.high) : top) - 6).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="11" fill="#4A4C43">${esc(fmtTight(ind)(v))}</text>`;
  }).join("")).join("");
  /* the median of all municipalities at each horizon: a tick, never a bar — it is a peer reference */
  const medTicks = med ? hz.map((h, g) => med[g] == null ? "" : `<line data-series="median" data-series-kind="median" x1="${(L0 + g * gw + gw * .08).toFixed(1)}" x2="${(L0 + (g + 1) * gw - gw * .08).toFixed(1)}" y1="${y(med[g]).toFixed(1)}" y2="${y(med[g]).toFixed(1)}" stroke="#5C5F52" stroke-width="2" stroke-dasharray="7 5"><title>median of municipalities ${esc(hzShort(h))}: ${fmtOf(ind)(med[g])}</title></line>`).join("") : "";
  const legY = H - B + 76; const perRow = 3, colW = (W - L0 - R) / perRow;
  const legend = rows.map((r, k) => { const lx = L0 + (k % perRow) * colW, ly = legY + Math.floor(k / perRow) * 24;
    return `<rect x="${lx}" y="${ly - 12}" width="14" height="14" fill="${r.color}" rx="2"/><text x="${lx + 22}" y="${ly}" font-family="${CH_FONT}" font-size="14" fill="#16170F">${esc(r.name)}</text>`; }).join("")
    + (med ? `<line x1="${L0 + (rows.length % perRow) * colW}" x2="${L0 + (rows.length % perRow) * colW + 20}" y1="${legY + Math.floor(rows.length / perRow) * 24 - 5}" y2="${legY + Math.floor(rows.length / perRow) * 24 - 5}" stroke="#5C5F52" stroke-width="2" stroke-dasharray="7 5"/><text x="${L0 + (rows.length % perRow) * colW + 28}" y="${legY + Math.floor(rows.length / perRow) * 24}" font-family="${CH_FONT}" font-size="14" fill="#16170F">median of municipalities</text>` : "");
  return `${open}${chTitleBlock(withTitle, ind, L0, sub)}
    ${ticks.map(t => `<line x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="#EFEFEA"/><text x="${L0 - 10}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" font-family="${CH_MONO}" font-size="12" fill="#8A8C81">${esc(fmtTight(ind)(t))}</text>`).join("")}
    ${hz.map((h, g) => g ? `<line x1="${(L0 + g * gw).toFixed(1)}" x2="${(L0 + g * gw).toFixed(1)}" y1="${T0}" y2="${H - B}" stroke="#EFEFEA"/>` : "").join("")}
    ${xticks}${bars}${medTicks}${legend}${chFoot(L0, H, ind)}</svg>`;
}
/* distributions from the BBR register: one donut per area */
const DIST_DEFS = { size: ["Dwelling size", ["< 50 m²", "50–79 m²", "80–119 m²", "120+ m²"]], rooms: ["Rooms", ["1 room", "2 rooms", "3 rooms", "4+ rooms"]],
                    built: ["Year built", ["before 1950", "1950–79", "1980–2009", "2010+"]], type: ["Building type", ["houses", "row houses", "multi-dwelling", "other"]] };
const DIST_COLORS = ["#C9DCD6", "#7FB0A4", "#3E8A78", "#1C6B5C"];
function chartSvgDist(withTitle) {
  const ents = CH.areas.map(chEntity).filter(Boolean).filter(e => e.o.bbr && e.o.bbr.dist); const [dl, labels] = DIST_DEFS[CH.dist] || DIST_DEFS.size;
  const W = 1200, H = 640, L0 = 96, T0 = withTitle ? 96 : 30;
  const ind = { label: `${dl} — share of dwellings (BBR)`, unit: "", desc: "Distribution of current dwellings from the BBR register, placed by building coordinate.", source: "BBR via Datafordeler (Klimadatastyrelsen)" };
  if (!ents.length) return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, "")}<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${CH_FONT}" font-size="18" fill="#8A8C81">Add areas with BBR data (municipalities, postal codes or quarters) to draw distributions</text></svg>`;
  const perRow = Math.min(4, ents.length), cw = (W - L0 * 2) / perRow, rows = Math.ceil(ents.length / perRow), avail = H - T0 - 110, rh = avail / rows, r0 = Math.min(cw, rh) * .34, r1 = r0 * .55;
  const arc = (cx, cy, a0, a1, R0, R1) => { const p = (a, r) => [cx + r * Math.cos(a), cy + r * Math.sin(a)]; const [x0, y0] = p(a0, R0), [x1, y1] = p(a1, R0), [x2, y2] = p(a1, R1), [x3, y3] = p(a0, R1); const big = a1 - a0 > Math.PI ? 1 : 0;
    return `M${x0.toFixed(1)},${y0.toFixed(1)}A${R0},${R0} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}A${R1},${R1} 0 ${big} 0 ${x3.toFixed(1)},${y3.toFixed(1)}Z`; };
  const donuts = ents.map((e, k) => { const cx = L0 + (k % perRow) * cw + cw / 2, cy = T0 + Math.floor(k / perRow) * rh + rh / 2 - 10; const d = e.o.bbr.dist[CH.dist] || [0, 0, 0, 0]; const tot = d.reduce((a, b) => a + b, 0) || 1; let a = -Math.PI / 2;
    const slices = d.map((v, i) => { const a1 = a + v / tot * 2 * Math.PI - 1e-6; const path = `<path d="${arc(cx, cy, a, a1, r0, r1)}" fill="${DIST_COLORS[i]}"><title>${esc(labels[i])}: ${nf(v / tot * 100, 0)} % (${nf(v, 0)})</title></path>`; const mid = (a + a1) / 2; const lab = v / tot >= .07 ? `<text x="${(cx + (r0 + r1) / 2 * Math.cos(mid)).toFixed(1)}" y="${(cy + (r0 + r1) / 2 * Math.sin(mid) + 5).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="13" font-weight="600" fill="${i >= 2 ? "#FFFFFF" : "#16170F"}">${nf(v / tot * 100, 0)} %</text>` : ""; a = a1 + 1e-6; return path + lab; }).join("");
    return slices + `<text x="${cx}" y="${(cy + r0 + 26).toFixed(1)}" text-anchor="middle" font-family="${CH_FONT}" font-size="15" font-weight="600" fill="#16170F">${esc(e.name)}</text><text x="${cx}" y="${(cy + r0 + 46).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="12" fill="#8A8C81">${nf(e.o.bbr.n, 0)} dwellings</text>`; }).join("");
  const legY = H - 52; const legend = labels.map((l, i) => `<rect x="${L0 + i * 220}" y="${legY - 12}" width="14" height="14" fill="${DIST_COLORS[i]}" rx="2"/><text x="${L0 + i * 220 + 22}" y="${legY}" font-family="${CH_FONT}" font-size="14" fill="#16170F">${esc(l)}</text>`).join("");
  return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, ind.desc)}${donuts}${legend}${chFoot(L0, H, ind)}</svg>`;
}
/* "2026K2" → "2026 Q2" for display; years pass through */
const fmtP = p => String(p).replace(/K(\d)$/, " Q$1");
function chartSvgLine(withTitle) {
  const { ind, inds, ys, series } = chartSeries(); const q = isQ(ys[0] || "");
  const W = 1200, H = 640, L0 = 96, R = 30, T0 = withTitle ? 84 : 24, B = 150;
  const all = series.flatMap(s_ => s_.pts.map(p => p.v)).filter(v => v != null);
  const F = "Inter, 'Helvetica Neue', Arial, sans-serif", M = "'IBM Plex Mono', Menlo, monospace";
  if (!all.length) return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"><rect width="${W}" height="${H}" fill="#FFFFFF"/><text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${F}" font-size="18" fill="#8A8C81">Add areas with the search box — nothing to plot yet</text></svg>`;
  /* padding never pushes an all-positive scale below zero (counts and rates) */
  const lo0 = Math.min(...all), hi0 = Math.max(...all), pad = (hi0 - lo0 || Math.abs(hi0) || 1) * .08; const lo = lo0 >= 0 ? Math.max(0, lo0 - pad) : lo0 - pad, hi = hi0 + pad, sp = hi - lo;
  const x = i => L0 + i / (ys.length - 1) * (W - L0 - R), y = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const ticks = [0, .25, .5, .75, 1].map(t => lo + t * sp);
  const paths = series.map(s_ => { let d = "", open = false; s_.pts.forEach((p, i) => { if (p.v == null) { open = false; return; } d += (open ? "L" : "M") + x(i).toFixed(1) + "," + y(p.v).toFixed(1); open = true; });
    return `<path data-series="${esc(s_.name)}" data-series-kind="${esc(s_.kind || "area")}" d="${d}" fill="none" stroke="${s_.color}" stroke-width="${s_.dash ? 2 : 3}" ${s_.dash ? 'stroke-dasharray="7 5"' : ""} stroke-linejoin="round"/>` +
      s_.pts.map((p, i) => p.v == null || s_.dash ? "" : `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${q ? 2.2 : 4}" fill="${s_.color}"><title>${esc(s_.name)} ${fmtP(p.y)}: ${fmtOf(ind)(p.v)}</title></circle>`).join(""); }).join("");
  /* series breaks: thin dotted marker, short label, the registry text as tooltip */
  const brks = chartBreaks(inds, ys).map(b => `<g><line x1="${x(b.idx).toFixed(1)}" x2="${x(b.idx).toFixed(1)}" y1="${T0}" y2="${H - B}" stroke="#8A8C81" stroke-width="1" stroke-dasharray="2 3"/>
    <text x="${(x(b.idx) + 5).toFixed(1)}" y="${T0 + 12}" font-family="${M}" font-size="11" fill="#8A8C81">break ${esc(fmtP(b.at))}</text>
    <line x1="${x(b.idx).toFixed(1)}" x2="${x(b.idx).toFixed(1)}" y1="${T0}" y2="${H - B}" stroke="transparent" stroke-width="12"><title>${esc(b.text)}</title></line></g>`).join("");
  const legY = H - B + 46; const perRow = 3, colW = (W - L0 - R) / perRow;
  const legend = series.map((s_, k) => { const lx = L0 + (k % perRow) * colW, ly = legY + Math.floor(k / perRow) * 24; const last = [...s_.pts].reverse().find(p => p.v != null);
    return `<line x1="${lx}" x2="${lx + 26}" y1="${ly - 4}" y2="${ly - 4}" stroke="${s_.color}" stroke-width="${s_.dash ? 2 : 3}" ${s_.dash ? 'stroke-dasharray="7 5"' : ""}/><text x="${lx + 34}" y="${ly}" font-family="${F}" font-size="14" fill="#16170F">${esc(s_.name)}${s_.inherited ? " °" : ""}${last ? ` <tspan font-family="${M}" fill="#4A4C43">${esc(fmtOf(ind)(last.v))} (${fmtP(last.y)})</tspan>` : ""}</text>`; }).join("");
  const title = withTitle ? `<text x="${L0}" y="40" font-family="${F}" font-size="24" font-weight="600" fill="#16170F" id="chsvgtitle">${esc(CH.title || chartAutoTitle())}</text><text x="${L0}" y="64" font-family="${M}" font-size="12" fill="#8A8C81">${esc(ind.desc || "")}</text>` : "";
  const foot = `<text x="${L0}" y="${H - 14}" font-family="${M}" font-size="11" fill="#8A8C81">Source: ${esc(ind.source || "")} · Macro Dashboard — Denmark, open data · built ${esc((D.meta && D.meta.built) || "")}${series.some(s_ => s_.inherited) ? " · ° = municipality value shown for a postal code or quarter" : ""}</text>`;
  return `<svg class="chart" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${title}
    ${ticks.map(t => `<line x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="#EFEFEA"/><text x="${L0 - 10}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" font-family="${M}" font-size="12" fill="#8A8C81">${esc(fmtTight(ind)(t))}</text>`).join("")}
    ${ys.map((yy, i) => q && !yy.endsWith("K1") ? "" : `<text x="${x(i).toFixed(1)}" y="${H - B + 22}" text-anchor="middle" font-family="${M}" font-size="12" fill="#8A8C81">${q ? yy.slice(0, 4) : yy}</text>`).join("")}
    ${brks}${paths}${legend}${foot}</svg>`;
}
function vCharts() {
  const ind = chartInd(), ys = chartYears(); const ents = CH.areas.map(chEntity).filter(Boolean);
  const clim = chartMode() === "clim";
  const quick = [["Top 5 municipalities", MUNI.slice().sort((a, b) => (b.pop || 0) - (a.pop || 0)).slice(0, 5).map(m => "kommune:" + m.code)],
                 ["Copenhagen metro", ["101", "147", "157", "159", "173", "230"].filter(c => byCode[c]).map(c => "kommune:" + c)],
                 ["Big four", ["101", "751", "461", "851"].filter(c => byCode[c]).map(c => "kommune:" + c)]];
  const { series } = chartSeries(); const q = isQ(ys[0] || "");
  const hasNat = !!NAT && (NAT[ind.key] != null || !!(NAT.hist && NAT.hist[ind.key]));
  /* §4: a Copenhagen quarter carries KK's projection and a municipality carries DST's. They may be
     read side by side — they must not be read as one series, and the gap has to be stated. */
  const pubs = ind.proj ? [...new Set(ents.map(e => e.type === "kvarter" ? "Københavns Kommune" : "DST"))] : [];
  const mixed = pubs.length > 1;
  const cands = overlayCands(ind);
  return `
  <div class="card accent">
    <div class="card-head tools-only"><div class="tools">
      ${indPicker("chind")}
      ${clim ? `<span class="projwin" title="A Climate indicator is published at three horizons, not per year — the x axis is the horizon">Horizons · Today · 2070 · 2120</span>`
             : `<select id="chy0" class="indsel"><option value="">from ${YEARS[0]}</option>${YEARS.map(y => `<option value="${y}" ${CH.y0 === y ? "selected" : ""}>${y}</option>`).join("")}</select>
      <select id="chy1" class="indsel"><option value="">to ${LATEST}</option>${YEARS.map(y => `<option value="${y}" ${CH.y1 === y ? "selected" : ""}>${y}</option>`).join("")}</select>
      ${qPeriods(ind).length > 1 ? `<div class="seg" title="Quarterly: each point is the rolling sum of the 4 quarters ending there">${[["year", "Yearly"], ["q", "Quarterly"]].map(([f, l]) => `<button class="sg ${CH.fq === f ? "on" : ""}" data-chfq="${f}">${l}</button>`).join("")}</div>` : ""}`}
      <label class="hint" style="display:flex;align-items:center;gap:5px"><input type="checkbox" id="chmed" ${CH.median ? "checked" : ""}> median</label>
      ${hasNat && !clim ? `<label class="hint" style="display:flex;align-items:center;gap:5px" title="Denmark as a whole (DST area 000), dashed"><input type="checkbox" id="chnat" ${CH.nat ? "checked" : ""}> Denmark</label>` : ""}
      ${clim ? "" : `<div class="seg">${[["auto", "Auto"], ["line", "Line"], ["bar", "Bars"], ["dist", "Distribution"]].map(([m, l]) => `<button class="sg ${CH.mode === m ? "on" : ""}" data-chmode="${m}">${l}</button>`).join("")}</div>`}
      ${chartMode() === "dist" ? `<select id="chdist" class="indsel">${Object.entries(DIST_DEFS).map(([k, v]) => `<option value="${k}" ${CH.dist === k ? "selected" : ""}>${v[0]}</option>`).join("")}</select>` : ""}</div>${indChips("chind")}</div>
    ${ents.length && CH.mode === "auto" && chartMode() === "bar" && chartYears().length < 2 ? `<p class="hint" style="margin:0 0 8px">This indicator is a single snapshot (no history) — shown as bars of the latest value. BBR distributions are under <b>Distribution</b>.</p>` : ""}
    ${ind.proj && ents.length ? `<p class="hint projnote" style="margin:0 0 8px"><span class="tag proj">Projection</span> ${esc(ind.proj.from)}→${esc(ind.proj.to)} · neither end is "better", so nothing here is coloured good or bad.${mixed ? ` <b>Two different runs are on this chart:</b> ${esc(pubs.join(" and "))}. They are not combined and must not be read as one series — for this city they are 2.2 % apart by 2040 (docs/FORECAST.md §4).` : ` Source: ${esc(pubs[0] === "Københavns Kommune" ? "Københavns Kommune" : "DST")} ${esc(ind.proj.vintage)}.`}</p>` : ""}
    <div class="tfilters">
      <span class="asrch"><input id="chq" list="arealist" class="indsel" placeholder="Add municipality, postal code or quarter… (Enter)" autocomplete="off"><datalist id="arealist">${AREA_OPTS.map(o => `<option value="${esc(o.t)}"></option>`).join("")}</datalist></span>
      ${quick.map(([l, ids]) => `<button class="lk mini" data-chadd="${ids.join("|")}">+ ${l}</button>`).join("")}
      ${CH.areas.length ? `<button class="lk mini" data-chclear>clear</button>` : ""}
    </div>
    ${cands.length && chartMode() === "line" ? `<div class="tfilters"><span class="hint">overlay</span>${cands.map(i => `<button class="lk mini ${CH.ov.includes(i.key) ? "primary" : ""}" data-chov="${i.key}" title="${esc(i.label)}">${CH.ov.includes(i.key) ? "✓" : "+"} ${esc(i.short || i.label)}</button>`).join("")}</div>` : ""}
    <div class="chips">${ents.map((e, k) => `<span class="chip" style="border-color:${CH_COLORS[k % CH_COLORS.length]}"><i style="background:${CH_COLORS[k % CH_COLORS.length]}"></i>${esc(e.name)}${!e.inds.some(i => i.key === ind.key) ? ' <em title="indicator not available at this level">n/a</em>' : ""}<button data-chrm="${esc(e.id)}" title="remove">×</button></span>`).join("")}</div>
    <div class="tfilters"><label class="hint" style="flex:1;display:flex;gap:8px;align-items:center">title <input id="chtitle" type="text" value="${esc(CH.title)}" placeholder="${esc(chartAutoTitle())}" style="flex:1;min-width:200px"></label>
      <button class="lk primary" data-chpng>⤓ Download PNG</button><button class="lk" data-chcsv>⤓ Data CSV</button><span class="hint">link: copy the address bar — it holds the whole setup</span></div>
    <div class="chartbox">${ents.length ? chartSvg(true) : `<div class="chempty"><b>Nothing to plot yet</b><p>Type a municipality, postal code or Copenhagen quarter in the box above (up to 8), or start with a set:</p>
      <div class="tools">${quick.map(([l, ids]) => `<button class="lk" data-chadd="${ids.join("|")}">+ ${l}</button>`).join("")}</div>
      <p class="dim">Tip: every area page and table row has a ↗ that opens it here with the indicator pre-selected.</p></div>`}</div>
    <p class="cap">${esc(clim ? climDescNeutral(ind.desc) : (ind.desc || ""))} ${ind.warn ? "⚠ " + esc(ind.warn) : ""} ${clim ? `One bar per published horizon: Today (Klimaatlas 1981–2010), 2070 (2041–70) and 2120 (2071–2100). Nothing is drawn between them — the publisher gives three periods, not a trend. Whiskers, where they appear, are the publisher's own low–high range. ${esc(CLIM_FOOT)}` : q ? "Quarterly: each point is the rolling sum of the 4 quarters ending in that quarter." : "Same sub-period each year (e.g. Q3 or July); values are those shown in the dashboard."}${hasNat && CH.nat && !clim ? " Dashed line in a series colour = Denmark as a whole." : ""}</p>
  </div>
  ${chartMode() === "line" && ents.length && series.length ? `<div class="card"><div class="card-head"><h3>Data</h3><span class="hint">${esc(ind.unit || "")}</span></div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>${q ? "Quarter" : "Year"}</th>${series.map(s_ => `<th class="num">${esc(s_.name)}</th>`).join("")}</tr></thead>
    <tbody>${ys.map((yy, i) => `<tr><th>${fmtP(yy)}</th>${series.map(s_ => fmtCell(ind, s_.pts[i].v, false)).join("")}</tr>`).join("")}</tbody></table></div></div>` : ""}
  ${chartMode() === "dist" && ents.some(e => e.o.bbr) ? `<div class="card"><div class="card-head"><h3>Data</h3><span class="hint">share of dwellings · count</span></div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Area</th><th class="num">Dwellings</th>${(DIST_DEFS[CH.dist] || DIST_DEFS.size)[1].map(l => `<th class="num">${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${ents.filter(e => e.o.bbr && e.o.bbr.dist).map(e => { const d = e.o.bbr.dist[CH.dist]; const t = d.reduce((a, b) => a + b, 0) || 1; return `<tr><th>${esc(e.name)}</th><td class="num">${nf(e.o.bbr.n, 0)}</td>${d.map(v => `<td class="num" data-v="${v / t * 100}">${nf(v / t * 100, 0)} % <span class="dim">${nf(v, 0)}</span></td>`).join("")}</tr>`; }).join("")}</tbody></table></div></div>` : ""}
  ${schoolsChartCard()}`;
}
function chartAddMany(ids) { ids.forEach(id => { if (!CH.areas.includes(id) && CH.areas.length < 8) CH.areas.push(id); }); syncHash(); renderKeep(); }
function chartPng() {
  const svg = chartSvg(true).replace('class="chart" ', 'width="1200" height="640" ').replace(' id="chsvg"', "");
  const img = new Image(); const scale = 2; const W = 1200, H = 640;
  img.onload = () => { const c = document.createElement("canvas"); c.width = W * scale; c.height = H * scale; const ctx = c.getContext("2d"); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, W, H);
    const ys_ = chartYears(); const span = chartMode() === "clim" ? "horizons" : ys_.length ? `${ys_[0]}-${ys_[ys_.length - 1]}` : "latest";
    c.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `chart_${CH.ind}_${span}.png`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }, "image/png"); };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}
function chartCsv() {
  if (chartMode() === "dist") { const ents = CH.areas.map(chEntity).filter(e => e && e.o.bbr && e.o.bbr.dist); const [dl, labels] = DIST_DEFS[CH.dist] || DIST_DEFS.size;
    downloadCsv([["area", "dwellings"].concat(labels).join(";")].concat(ents.map(e => [e.name, e.o.bbr.n].concat(e.o.bbr.dist[CH.dist]).join(";"))), `chart_${CH.dist}_distribution.csv`); return; }
  if (chartMode() === "bar") { const ind = chartInd(); const ents = CH.areas.map(chEntity).filter(Boolean);
    downloadCsv([["area", ind.key].join(";")].concat(ents.map(e => [e.name, V(e.o, ind.key) ?? (e.type === "postnr" && e.muni ? V(e.muni, ind.key) : "") ?? ""].join(";"))), `chart_${ind.key}_latest.csv`); return; }
  /* a Climate chart is area × horizon, with the publisher's range where there is one */
  if (chartMode() === "clim") { const ind = chartInd(); const ents = CH.areas.map(chEntity).filter(Boolean);
    const hz = CLIM_HZ || ["today", "2070", "2120"];
    const out = [["area", "level", "indicator", "unit", "horizon", "period", "value", "range_low", "range_high"].join(";")];
    ents.forEach(e => hz.forEach(h => { const v = climValue(e.o, ind.key, h), rg = climRangeAt(e.o, ind.key, h);
      out.push([e.name, e.type, ind.key, ind.unit || "", h, CLIM_ZONE_YEAR[h] || h, v ?? "", rg ? rg.low : "", rg ? rg.high : ""].map(x => String(x).replace(/;/g, ",")).join(";")); }));
    downloadCsv(out, `chart_${ind.key}_horizons.csv`); return; }
  const { ind, ys, series } = chartSeries();
  downloadCsv([[isQ(ys[0] || "") ? "quarter" : "year"].concat(series.map(s_ => s_.name)).join(";")].concat(ys.map((yy, i) => [yy].concat(series.map(s_ => s_.pts[i].v ?? "")).map(v => String(v).replace(/;/g, ",")).join(";"))), `chart_${ind.key}.csv`);
}



/* ---------- Public buildings overlay (BBR anvendelse 410–449, see docs/PUBLIC_BUILDINGS.md) ---------- */
const PUB = D.public || null;                       /* { areas, built, kommuner, recent_years } */
const PUB_FILES = {};                               /* kommune code → { buildings: [...] } once loaded */
const pubAvail = code => !!(PUB && code && PUB.kommuner.includes(String(Number(code))));
const pubOf = (level, code) => (PUB && PUB.areas[`${level}:${code}`]) || null;
/* four tones that do not collide with the infra status colours (grey-green/ochre/teal/brick) */
const PUB_CAT = {
  education:    { label: "Education", color: "#40547F" },
  institutions: { label: "Daycare / institutions", color: "#6E8C5E" },
  health:       { label: "Health", color: "#82346C" },
  culture:      { label: "Culture", color: "#B07A1E" },
};
const pubCat = b => PUB_CAT[b.cat] || PUB_CAT.culture;
const pubName = b => b.name || b.address || b.label;
function pubLoad(code) {
  schoolsLoad();
  const k = String(Number(code));
  if (!PUB || !pubAvail(k) || PUB_FILES[k] || PUB_FILES["_loading_" + k]) return;
  PUB_FILES["_loading_" + k] = true;
  fetch(`public/${String(k).padStart(4, "0")}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { PUB_FILES[k] = d; delete PUB_FILES["_loading_" + k]; if (MK.pub && LF.map) lfPublicLayers(true); anMapOverlays(); anFill(); })
    .catch(() => { delete PUB_FILES["_loading_" + k]; PUB_FILES["_error_" + k] = true; });
}
/* what to draw: the municipality in view, else every loaded file — and at national zoom only the open cases */
function pubParseFilter(q) {
  const raw = (q.pub || "").trim();
  /* "none" is a real state — every category off. An empty or unreadable value still means "all", so a
     hand-typed link cannot blank the map, but a link copied with everything hidden reopens hidden. */
  if (raw === PF_NONE) PF.cats = new Set();
  else if (!raw || raw === "all") PF.cats = null;
  else { const set = new Set(raw.split(",").map(c => PF_LONG[c]).filter(Boolean)); PF.cats = set.size ? set : null; }
  PF.kind = ["existing", "open"].includes(q.pubkind) ? q.pubkind : "both";
}
/* the filter as hash parameters — the map, the public list and the Analysis sheet write the same names */
function pubHashParts() {
  const q = [];
  if (PF.cats) q.push(`pub=${PF.cats.size ? [...PF.cats].map(c => PF_SHORT[c]).join(",") : PF_NONE}`);
  if (PF.kind !== "both") q.push(`pubkind=${PF.kind}`);
  return q;
}
const pubCatOn = c => !PF.cats || PF.cats.has(c);
const pubKindOn = kind => PF.kind === "both" || (PF.kind === "existing" ? kind === "existing" : kind === "case");
function pubSetFilter({ cats, kind }) {
  if (cats !== undefined) PF.cats = cats;
  if (kind !== undefined) PF.kind = kind;
  LF.pubDrawn = null;              /* the view did not move, but what belongs on it changed */
  syncHash(); renderKeep();
}
/* every loaded building that passes the filter, before the zoom rule */
function pubAll() {
  const loaded = Object.keys(PUB_FILES).filter(k => !k.startsWith("_"));
  const keys = MK.muni && pubAvail(MK.muni) ? [String(Number(MK.muni))] : loaded;
  return keys.flatMap(k => (PUB_FILES[k] || {}).buildings || [])
    .filter(b => pubCatOn(b.cat) && pubKindOn(b.kind) && (b.kind === "existing" || b.recent));
}
/* density rule — Copenhagen alone has 2.500 public buildings, so the national view would be a blob:
   < 9 open cases only · 9–12 open cases + buildings ≥ 1.000 m² · ≥ 13 everything */
const PUB_BIG_M2 = 1000;
function pubZoom() { return LF.map ? LF.map.getZoom() : 7; }
function pubRows() {
  const rows = tpRadOn() ? pubAll().filter(b => tpWithin(b.lat, b.lon)) : pubAll(), z = pubZoom();
  if (z < 9) return rows.filter(b => b.kind === "case");
  if (z < 13) return rows.filter(b => b.kind === "case" || (b.m2 || 0) >= PUB_BIG_M2);
  return rows;
}
/* load the per-municipality file for everything in view, and keep it for the session */
function pubLoadVisible() {
  if (!LF.map || !MK.pub || !PUB) return;
  if (MK.muni) { pubLoad(MK.muni); return; }
  if (!LF.muniBounds) {
    LF.muniBounds = {};
    PUB.kommuner.forEach(k => { const b = boundsOf(muniAreas(k)); if (b) LF.muniBounds[k] = b; });
  }
  const view = LF.map.getBounds();
  PUB.kommuner.forEach(k => { const b = LF.muniBounds[k]; if (b && view.intersects(b)) pubLoad(k); });
}
function pubPopup(b) {
  const c = pubCat(b), row = (l, v) => v == null || v === "" ? "" : `<span class="lfrow"><span>${esc(l)}</span><b>${v}</b></span>`;
  const area = [byNr[b.postnr], byQ[b.kvarter]].filter(Boolean);
  return `<div class="lfpop"><b>${esc(pubName(b))}</b>
    <span class="infrapills"><i class="ipill" style="color:${c.color};border-color:${c.color}55">${esc(c.label)}</i>
      <i class="ipill">${esc(b.label)} · ${esc(b.code)}</i>
      <i class="ipill ${b.kind === "case" ? "st-decided" : ""}">${b.kind === "existing" ? "Existing" : "Open building case"}</i></span>
    <div class="lfrows">
      ${row("Address", esc(b.address || ""))}${row("Floor area", b.m2 ? nf(b.m2, 0) + " m²" : "")}
      ${b.kind === "existing" ? row("Built", b.year || "") + row("Floors", b.floors || "") : ""}
      ${b.kind === "case" ? row("Permit", b.permit || "–") + row("Started", b.started || "") + row("Case age", b.age_yrs != null ? nf(b.age_yrs, 1) + " yr" : "") +
        row("Expected completion", b.expected || "not stated") + row("Owner", b.owner || "") + row("Case no.", b.case_no || "") : ""}
      ${row("Municipality", esc((byCode[b.kom] || {}).name || ""))}${row("Postal code", esc(b.postnr || ""))}</div>
    ${schoolPopupBlock(b)}
    ${b.kind === "case" ? `<p class="cap">⚠ Owner-reported BBR case — not a confirmed construction schedule.</p>` : ""}
    <span class="lfact"><button class="lk mini primary" data-pubsheet="${esc(b.id)}">Open sheet ›</button>
      ${area.length ? `<button class="lk mini" data-go="${withQ(pageOf(area[0]))}">${esc(area[0].name)} ›</button>` : ""}</span>
    <p class="cap dim">BBR ${esc(b.code)} · id ${esc(b.id.slice(0, 8))}… · BBR via Datafordeler, ${esc((PUB || {}).built || "")}</p></div>`;
}
/* ---------- Public buildings: what makes it fast ----------
   Measured before changing anything: at zoom 13 over Copenhagen the layer put **5 293 SVG paths**
   into the DOM (2 639 buildings × a halo and a marker each) and took 180 ms to rebuild. Filtering
   those rows took **1.2 ms** of that. So the cost was never the filter — it was constructing and
   inserting DOM nodes, and that is what the three changes below attack:

     · the plain dots move to the canvas renderer, in their own pane (the services layer already
       draws more markers than this in ~16 ms that way);
     · only what is inside the viewport is built, and only when the map leaves the padding;
     · past PUB_CLUSTER_MAX markers the rows are clustered into a grid, so the count on screen has
       a ceiling no matter how many buildings are loaded.

   A Web Worker for the filtering was considered and rejected on the measurement: moving a 1.2 ms
   array filter across a structured clone costs more than it saves. What did block the main thread
   was marker construction, and clustering plus the viewport bound is what removes it. */
const PUB_CLUSTER_MAX = 900;      /* more markers than this in view → draw a grid of clusters */
const PUB_PAD = 0.15;             /* viewport padding, as a share of the view */

function pubNeedsRedraw() {
  if (!LF.pubDrawn || LF.pubDrawn.zoom !== LF.map.getZoom()) return true;
  const v = LF.map.getBounds(), b = LF.pubDrawn.bounds;
  return !(b.contains(v.getNorthEast()) && b.contains(v.getSouthWest()));
}
/* rows inside the padded viewport — the rest cannot be seen and is not built */
function pubRowsInView() {
  const rows = pubRows();
  if (!LF.map) return rows;
  const v = LF.map.getBounds().pad(PUB_PAD);
  const s = v.getSouth(), n = v.getNorth(), w = v.getWest(), e = v.getEast();
  return rows.filter(b => b.lat >= s && b.lat <= n && b.lon >= w && b.lon <= e);
}
/* a grid of cells at roughly 44 screen pixels, so cluster density looks the same at every zoom */
function pubCluster(rows) {
  const z = LF.map.getZoom();
  /* 72 px cells, not 44: each cluster carries a permanent tooltip, which is a DOM node, so the
     cell size is really a budget for how many of those exist. 72 px keeps it near 100 on a full
     screen while still separating neighbourhoods. */
  const cell = 72 / (256 * Math.pow(2, z)) * 360;          /* degrees of longitude per cell */
  const latCell = cell * 0.62;                             /* roughly square on screen at DK latitudes */
  const g = new Map();
  rows.forEach(b => {
    const k = `${Math.floor(b.lat / latCell)}:${Math.floor(b.lon / cell)}`;
    let c = g.get(k);
    if (!c) { c = { n: 0, lat: 0, lon: 0, cats: {} }; g.set(k, c); }
    c.n++; c.lat += b.lat; c.lon += b.lon;
    c.cats[b.cat] = (c.cats[b.cat] || 0) + 1;
  });
  return [...g.values()].map(c => ({ ...c, lat: c.lat / c.n, lon: c.lon / c.n }));
}
function pubClusterMarkers(cells, map) {
  const marks = [];
  amOf(map);                                      /* make sure this map has a "pubpane" of its own */
  cells.forEach(c => {
    if (c.n === 1) return;                                  /* singletons stay real markers */
    const top = Object.entries(c.cats).sort((a, b) => b[1] - a[1])[0][0];
    const col = (PUB_CAT[top] || PUB_CAT.culture).color;
    const r = Math.min(20, 8 + Math.log2(c.n) * 2.4);
    const m = L.circleMarker([c.lat, c.lon], { pane: "pubpane", radius: r, color: "#FFFFFF", weight: 2,
      fillColor: col, fillOpacity: .88, className: "pubcluster" });
    /* only a cluster worth reading gets a number; the small ones are legible by size alone, and
       every label is a DOM node this layer exists to avoid */
    if (c.n >= 4) m.bindTooltip(String(c.n), { permanent: true, direction: "center", className: "pubclab" });
    m.on("click", () => map.setView([c.lat, c.lon], Math.min(18, map.getZoom() + 2)));
    marks.push(m);
  });
  return marks;
}
function lfPublicLayers(force) {
  if (!LF.map) return;
  if (MK.pub && PUB && !force && LF.pubG && !pubNeedsRedraw()) { pubLoadVisible(); return; }
  ["pubG", "pubLabG"].forEach(k => { if (LF[k] && LF.map) { LF.map.removeLayer(LF[k]); LF[k] = null; } });
  if (!MK.pub || !PUB) { LF.pubDrawn = null; setPublicLegend(); return; }
  pubLoadVisible();
  LF.pubDrawn = { zoom: LF.map.getZoom(), bounds: LF.map.getBounds().pad(PUB_PAD) };
  const rows = pubRowsInView();
  LF.pubN = rows.length;
  LF.pubClustered = rows.length > PUB_CLUSTER_MAX;
  if (LF.pubClustered) {
    const cells = pubCluster(rows);
    const singles = cells.filter(c => c.n === 1).length;
    LF.pubCells = cells.length;
    /* the singletons still deserve their popup, so they are drawn as ordinary markers */
    const singleRows = [];
    const cellOf = new Map(cells.filter(c => c.n === 1).map(c => [`${c.lat.toFixed(6)},${c.lon.toFixed(6)}`, true]));
    rows.forEach(b => { if (cellOf.has(`${b.lat.toFixed(6)},${b.lon.toFixed(6)}`)) singleRows.push(b); });
    LF.pubG = L.layerGroup(pubClusterMarkers(cells, LF.map)
      .concat(pubMarkers(singleRows, LF.map, gradeMode()))).addTo(LF.map);
    LF.pubSingles = singles;
  } else {
    LF.pubCells = 0;
    LF.pubG = L.layerGroup(pubMarkers(rows, LF.map, gradeMode())).addTo(LF.map);
  }
  lfPublicLabels();
  setPublicLegend();
}
/* the same circle markers on either map — grade mode: Education on its own carries the school's FP9
   grade instead of the category hue. No grade (0.–6. klasse, suppressed, special, or not a school at
   all) keeps the base hue, drawn hollow, so it reads as "not on this scale", never as a low grade. */
function pubMarkers(rows, map, gm) {
  const gsc = gm ? gradeScale() : null, marks = [];
  /* the renderer and pane of *this* map — the mini map has its own set, see mapPanes() */
  const am = amOf(map);
  rows.forEach(b => {
    const c = pubCat(b), existing = b.kind === "existing";
    let stroke = c.color, fill = existing ? c.color : "#FFFFFF", fop = existing ? .85 : 1, wt = 2;
    if (gm && b.cat === "education") {
      const gc = gradeColor(b, gsc);
      if (gc) { fill = gc; fop = .95; stroke = "#2F3B55"; wt = 1.4; }
      else { fill = c.color; fop = .18; stroke = c.color; wt = 1; }
    }
    /* one canvas marker instead of an SVG halo + SVG marker: half the objects and no DOM node each.
       The white ring that used to be a separate halo is now this marker's own stroke. */
    const halo = null;
    const m = L.circleMarker([b.lat, b.lon], { renderer: am ? am.pub : undefined, pane: am ? "pubpane" : undefined,
      radius: 6, color: existing ? "#FFFFFF" : stroke, weight: existing ? 1.6 : wt, opacity: .95,
      fillColor: fill, fillOpacity: fop, dashArray: existing ? null : "3 3" });
    m.on("click", e => L.popup({ maxWidth: 420, autoPanPadding: [24, 24] }).setLatLng(e.latlng || [b.lat, b.lon]).setContent(pubPopup(b)).openOn(map));
    m._pub = b;
    marks.push(m);
  });
  return marks;
}
function lfPublicLabels() {
  if (LF.pubLabG) { LF.map.removeLayer(LF.pubLabG); LF.pubLabG = null; }
  if (!LF.map || !MK.pub || !PUB || LF.map.getZoom() < 14) return;
  const placed = [], labs = [];
  pubRows().filter(b => b.name).forEach(b => {
    const pt = LF.map.latLngToContainerPoint([b.lat, b.lon]);
    if (placed.some(q => Math.abs(q.x - pt.x) < 80 && Math.abs(q.y - pt.y) < 18)) return;
    placed.push(pt);
    const m = L.marker([b.lat, b.lon], { interactive: true, keyboard: false,
      icon: L.divIcon({ className: "lflab infralab publab", iconSize: null, html: `<b>${esc(b.name)}</b>` }) });
    m.on("click", () => L.popup({ maxWidth: 420 }).setLatLng([b.lat, b.lon]).setContent(pubPopup(b)).openOn(LF.map));
    labs.push(m);
  });
  LF.pubLabG = L.layerGroup(labs).addTo(LF.map);
}
/* The public-buildings legend, shared by the Macro map and the Analysis mini map.

   It is built from the full category list, never from the active filter, so switching a category off
   greys its row instead of removing it — the way back on is always on screen. Grade mode adds the FP9
   ramp underneath the categories rather than replacing them. `rows` is what the caller actually drew,
   so the counts line always describes the markers in front of the reader. */
function pubLegendHtml(rows, note, zoomNote, gm) {
  const n = rows.length, cases = rows.filter(b => b.kind === "case").length;
  const allOff = pubAllOff();
  /* keys only: which colour is which category, and which shape is a permit case (spec §4.5).
     The filters themselves live in Layers ▾. */
  const catRow = (k, c) => `<div class="lgrow">
      <i style="background:${c.color};border-radius:50%"></i>${esc(c.label)}</div>`;
  const kindRow = `<div class="lgrow gk">
      ${pubKindOn("existing") ? `<span><i class="pk-exist"></i>existing</span>` : ""}
      ${pubKindOn("case") ? `<span><i class="pk-case"></i>open case</span>` : ""}</div>`;
  let grade = "";
  if (gm === undefined ? gradeMode() : gm) {
    const sc = gradeScale(), gn = sc.classes || 0, b = sc.breaks || [];
    const lab = i2 => gn === 1 ? nf(sc.lo, 1) : i2 === 0 ? `≤ ${nf(b[0], 1)}` : i2 === gn - 1 ? `> ${nf(b[i2 - 1], 1)}` : `${nf(b[i2 - 1], 1)} – ${nf(b[i2], 1)}`;
    const bins = []; for (let i2 = gn - 1; i2 >= 0; i2--) bins.push(`<div class="lgrow"><i style="background:${mkShade(gn > 1 ? i2 / (gn - 1) : .5, GRADE_KEY)}"></i>${lab(i2)}</div>`);
    grade = `<div class="lgsub">FP9 grade avg<span>bundne prøver · ${esc(SCH_LATEST)}</span></div>
      ${gn ? bins.join("") : `<div class="lgrow dim">no grades loaded</div>`}
      <div class="lgrow"><i style="background:${PUB_CAT.education.color};opacity:.18;border:1px solid ${PUB_CAT.education.color}"></i>no grade published</div>
      <div class="lgnote">${sc.n || 0} schools classed over the loaded municipalities. A school with no grade teaches no 9th grade, or the source suppressed it — never read it as a low grade. Kilde: Uddannelsesstatistik.dk</div>`;
  }
  const loading = Object.keys(PUB_FILES).filter(k => k.startsWith("_loading_")).length;
  return lgTitle("Public buildings", `BBR ${esc((PUB || {}).built || "")} · ${note || `${(PUB || {}).kommuner ? PUB.kommuner.length : 0} municipalities`}`) + `
    ${loading ? `<div class="lgrow pubload"><i class="skel"></i>loading ${loading} municipalit${loading === 1 ? "y" : "ies"}…</div>` : ""}
    ${Object.entries(PUB_CAT).filter(([k]) => pubCatOn(k)).map(([k, c]) => catRow(k, c)).join("")}
    ${kindRow}
    ${allOff ? `<div class="lgrow gk allhidden">All categories hidden — Layers ▾</div>` : ""}
    ${grade}
    <div class="lgnote">${allOff ? "nothing drawn"
      : `${nf(n - cases, 0)} existing · ${nf(cases, 0)} open cases (permit ≤ ${(PUB || {}).recent_years} yr) drawn${zoomNote || ""}`}</div>
    ${LF.pubClustered ? `<div class="lgnote">${nf(LF.pubN || 0, 0)} in view, grouped into ${nf(LF.pubCells || 0, 0)} clusters — zoom in or click a cluster to open it</div>` : ""}`;
}
/* Fill one legend box, or hide it when its layer is off. The box is never left as an empty white bar:
   either it has content or it is display:none (and `.maplegend:empty` catches any path that misses this). */
function setPubLegendIn(id, live, rows, note, zoomNote, gm) {
  const el = document.getElementById(id); if (!el) return;
  if (!live) { el.innerHTML = ""; el.style.display = "none"; return; }
  el.style.display = "";
  el.innerHTML = pubLegendHtml(rows || [], note, zoomNote, gm);
  lgApplyFold(el);
  lgFitSoon();
}
function setPublicLegend() {
  const live = !!(MK.pub && PUB && document.getElementById("lfmap"));
  setPubLegendIn("publiclegend", live, live ? pubRows() : [], null,
    !live ? "" : pubZoom() < 9 ? " · open cases only — zoom in for the stock"
    : pubZoom() < 13 ? ` · showing large buildings (≥ ${nf(PUB_BIG_M2, 0)} m²) — zoom in for all` : "");
}
/* the PUBLIC line on an area card */
function publicLine(level, code) {
  const e = pubOf(level, code); if (!e) return "";
  const sch = schoolLine(level, code);
  const seg = Object.entries(PUB_CAT).map(([k, c]) => { const v = (e.counts || {})[k] || {};
    return v.existing ? `<button class="lk mini" data-publist="${level}:${code}:${k}:existing" data-pubfilter="${k}:existing" style="border-color:${c.color}66">${nf(v.existing, 0)} ${esc(k === "institutions" ? "daycare/inst." : c.label.toLowerCase())}</button>` : ""; }).join("");
  const cases = Object.values(e.counts || {}).reduce((s, v) => s + (v.case || 0), 0);
  if (!seg && !cases && !sch) return "";
  return `<span class="upcoming"><em>Public</em>${seg}${cases ? `<button class="lk mini" data-publist="${level}:${code}::case" data-pubfilter=":case">${cases} open case${cases > 1 ? "s" : ""}</button>` : ""}${schoolLine(level, code)}</span>`;
}

/* ---------- Schools (Uddannelsesstatistik.dk / STIL) ----------
   The per-area aggregates ride along in public_index (PUB.areas); the school records themselves are
   a separate file, fetched once the public layer is on or a school page is opened. */

/* ---------- Services overlay (OpenStreetMap + Rejseplanen) ----------
   Same shape as the Public buildings layer: a toolbar toggle, a legend that doubles as the
   category filter, per-kommune files fetched on demand, popups in the same two-level style.
   Two things differ, both because this layer is 44.181 points against public buildings' 7.517:
     · only what is inside the viewport is drawn, not every loaded row;
     · every category has its own zoom floor, so the dense ones cannot be asked for at all
       until the viewport is small enough to hold them.
   Data: scripts/build_services.py · docs/SERVICES.md */
const SRV = D.services || null;                     /* index.json: {asof, categories, kommuner{code:{bbox,n,by_cat}}} */
const SRV_FILES = {};                               /* code → points[] once fetched */
/* Hues deliberately outside the choropleth's green ramp, the infra greys/teal and the four
   public-building tones (indigo/sage/plum/ochre). Every marker also carries a white halo, so
   it stays readable on the palest and the darkest quintile fill alike. */
const SRV_CAT = {
  grocery:   { label: "Groceries",    color: "#E8590C", zoom: 13 },
  food:      { label: "Food & drink", color: "#C2255C", zoom: 14 },
  pharmacy:  { label: "Pharmacy",     color: "#5F3DC4", zoom: 13 },
  transport: { label: "Transport",    color: "#1864AB", zoom: 10 },
};
const SRV_MODE = {
  metro:        { label: "Metro",      color: "#1864AB", group: "rail" },
  "s-train":    { label: "S-train",    color: "#0B7285", group: "rail" },
  rail:         { label: "Rail",       color: "#343A40", group: "rail" },
  "light-rail": { label: "Light rail", color: "#9C36B5", group: "rail" },
  bus:          { label: "Bus",        color: "#868E96", group: "bus" },
};
/* English sub-type names for the popup — the files carry the OSM/GTFS vocabulary */
const SRV_SUB = {
  supermarket: "Supermarket", convenience: "Convenience store",
  restaurant: "Restaurant", cafe: "Café", bar: "Bar", fast_food: "Takeaway",
  pharmacy: "Pharmacy",
  metro: "Metro station", "s-train": "S-train station", rail: "Railway station",
  "light-rail": "Light rail stop", bus: "Bus stop",
};
const SRV_RAIL_MODES = ["metro", "s-train", "rail", "light-rail"];
/* Transport is split in two because the two halves are three orders of magnitude apart:
   628 stations against 24.412 bus stops. Rail is on by default, bus is not. */
const SRV_TGROUP = { rail: { label: "Rail & metro", zoom: 10 }, bus: { label: "Bus", zoom: 14 } };
const SRV_DEFAULT_CATS = ["grocery", "pharmacy", "transport"];
const SRV_DEFAULT_MODES = ["rail"];
const SRV_MAX_MARKERS = 3000;                       /* the ceiling the zoom floors are there to keep */
/* a fingertip is not a mouse pointer: on a touch screen the dots and stations are drawn
   bigger, which is also their hit area — Leaflet tests the circle's own radius */
const srvCoarse = () => { try { return matchMedia("(pointer: coarse)").matches; } catch (e) { return false; } };
const SF = { cats: new Set(SRV_DEFAULT_CATS), tmodes: new Set(SRV_DEFAULT_MODES) };
const SRV_SHORT = { grocery: "g", food: "f", pharmacy: "p", transport: "t" };
const SRV_LONG = Object.fromEntries(Object.entries(SRV_SHORT).map(([k, v]) => [v, k]));

/* both sources the layer draws from, for the map footer and the Sources view */
const SRV_ATTRIB = ["© OpenStreetMap contributors, ODbL", "Rejseplanen, CC BY 4.0"];
const srvAttribLine = () => SRV_ATTRIB.join(" · ") + (SRV && SRV.asof ? ` · services data as of ${SRV.asof}` : "");

function srvParseFilter(q) {
  const raw = (q.srv || "").trim();
  if (!raw) { SF.cats = new Set(SRV_DEFAULT_CATS); SF.tmodes = new Set(SRV_DEFAULT_MODES); return; }
  const parts = raw.split(",").filter(Boolean);
  SF.cats = new Set(parts.map(c => SRV_LONG[c]).filter(Boolean));
  SF.tmodes = new Set(parts.filter(c => c === "rail" || c === "bus"));
  /* "transport on with neither half" cannot be drawn, so it is not a state we keep */
  if (!SF.tmodes.size) SF.cats.delete("transport");
}
function srvHashParts() {
  const cats = [...SF.cats].map(c => SRV_SHORT[c]).filter(Boolean);
  const modes = SF.cats.has("transport") ? [...SF.tmodes] : [];
  const v = cats.concat(modes).join(",");
  return v ? [`srv=${v}`] : ["srv=none"];
}
const srvCatOn = c => SF.cats.has(c);
const srvModeOn = m => SF.cats.has("transport") && SF.tmodes.has(SRV_MODE[m] ? SRV_MODE[m].group : "rail");
function srvSetFilter(cats, tmodes) {
  if (cats !== undefined) SF.cats = cats;
  if (tmodes !== undefined) SF.tmodes = tmodes;
  if (SF.cats.has("transport") && !SF.tmodes.size) SF.tmodes = new Set(SRV_DEFAULT_MODES);
  LF.srvDrawn = null;                     /* the viewport did not move, but what belongs on it changed */
  lfDrop("srvG", "srvStG");               /* drop before the rebuild, never leave a group behind */
  syncHash(); renderKeep();
}
/* the zoom a category needs before it is drawn at all */
function srvCatZoom(cat) {
  if (cat !== "transport") return SRV_CAT[cat].zoom;
  const gs = [...SF.tmodes].map(g => SRV_TGROUP[g].zoom);
  return gs.length ? Math.min(...gs) : SRV_TGROUP.rail.zoom;
}
const srvZoom = () => (LF.map ? LF.map.getZoom() : 7);

/* ---- loading: only the kommuner whose bbox meets the viewport, cached for the session ---- */
function srvLoad(code) {
  const k = String(Number(code));
  if (!SRV || !SRV.kommuner[k] || SRV_FILES[k] || SRV_FILES["_loading_" + k]) return;
  SRV_FILES["_loading_" + k] = true;
  fetch(`services/${k.padStart(4, "0")}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => {
      SRV_FILES[k] = (d.points || []).map(p => ({ cat: p[0], sub: p[1], lat: p[2], lon: p[3],
        name: p[4] || "", extra: p.length > 5 ? p[5] : null, kom: k }));
      delete SRV_FILES["_loading_" + k];
      if (MK.srv && LF.map) lfServicesLayers(true);
    })
    .catch(() => { delete SRV_FILES["_loading_" + k]; SRV_FILES["_error_" + k] = true; });
}
/* The lowest zoom at which *anything* enabled would be drawn. Below it nothing is
   fetched: the national view intersects all 99 bounding boxes, and loading 2,6 MB to
   draw nothing is exactly what this layer must not do. */
function srvMinZoom() {
  const zs = [...SF.cats].map(srvCatZoom);
  return zs.length ? Math.min(...zs) : Infinity;
}
const SRV_MAX_FILES = 24;                           /* a hard ceiling on one pass, whatever the viewport */
function srvLoadVisible() {
  if (!LF.map || !MK.srv || !SRV) return;
  if (LF.map.getZoom() < srvMinZoom()) return;
  const v = LF.map.getBounds(), c = v.getCenter();
  const hits = [];
  Object.entries(SRV.kommuner).forEach(([k, m]) => {
    const bb = m.bbox; if (!bb) return;                       /* [S, W, N, E] */
    if (v.getSouth() <= bb[2] && v.getNorth() >= bb[0] && v.getWest() <= bb[3] && v.getEast() >= bb[1])
      hits.push([k, Math.abs((bb[0] + bb[2]) / 2 - c.lat) + Math.abs((bb[1] + bb[3]) / 2 - c.lng)]);
  });
  /* nearest first, so a viewport that somehow spans half the country still starts with
     the municipalities the reader is actually looking at */
  hits.sort((a, b) => a[1] - b[1]).slice(0, SRV_MAX_FILES).forEach(([k]) => srvLoad(k));
}
/* what to draw: loaded points, passing the filter, inside the viewport, above their zoom floor */
function srvRows() {
  if (!SRV || !LF.map) return [];
  const z = srvZoom(), v = LF.map.getBounds().pad(0.15);
  const s_ = v.getSouth(), n_ = v.getNorth(), w_ = v.getWest(), e_ = v.getEast();
  const rows = [];
  Object.keys(SRV_FILES).forEach(k => {
    if (k.startsWith("_")) return;
    SRV_FILES[k].forEach(p => {
      if (!srvCatOn(p.cat)) return;
      if (!tpWithin(p.lat, p.lon)) return;
      if (p.cat === "transport") { if (!srvModeOn(p.sub) || z < SRV_TGROUP[SRV_MODE[p.sub].group].zoom) return; }
      else if (z < SRV_CAT[p.cat].zoom) return;
      if (p.lat < s_ || p.lat > n_ || p.lon < w_ || p.lon > e_) return;
      rows.push(p);
    });
  });
  return rows;
}
const srvColor = p => p.cat === "transport" ? (SRV_MODE[p.sub] || SRV_MODE.bus).color : SRV_CAT[p.cat].color;
const srvIsStation = p => p.cat === "transport" && p.sub !== "bus";
const srvSubLabel = p => SRV_SUB[p.sub] || p.sub;
const srvName = p => p.name || `Unnamed ${srvSubLabel(p).toLowerCase()}`;

function srvPopup(p) {
  const row = (l, v) => v == null || v === "" ? "" : `<span class="lfrow"><span>${esc(l)}</span><b>${v}</b></span>`;
  const col = srvColor(p);
  const transport = p.cat === "transport";
  const plats = transport && typeof p.extra === "number" ? p.extra : null;
  const brand = !transport && p.extra ? String(p.extra) : "";
  /* every mode this stop is listed under, across the loaded points at the same position */
  const modes = transport ? srvModesHere(p) : [];
  const src = transport
    ? `Rejseplanen, CC BY 4.0`
    : `© OpenStreetMap contributors, ODbL`;
  return `<div class="lfpop"><b>${esc(srvName(p))}</b>
    <span class="infrapills"><i class="ipill" style="color:${col};border-color:${col}55">${esc(SRV_CAT[p.cat].label)}</i>
      <i class="ipill">${esc(srvSubLabel(p))}</i>${brand ? `<i class="ipill">${esc(brand)}</i>` : ""}</span>
    <div class="lfrows">
      ${row("Type", esc(srvSubLabel(p)))}
      ${brand ? row("Brand", esc(brand)) : ""}
      ${transport && modes.length > 1 ? row("Also served by", modes.filter(m => m !== p.sub).map(m => esc(SRV_MODE[m].label)).join(" · ")) : ""}
      ${plats ? row("Platforms merged", plats) : ""}
      ${row("Municipality", esc((byCode[p.kom] || {}).name || ""))}
      ${row("Position", `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`)}</div>
    <p class="cap dim">${src} · data as of ${esc((SRV && SRV.asof) || "–")}</p></div>`;
}
/* the other transport points within 40 m — a station that serves several modes is one point per mode */
function srvModesHere(p) {
  const out = new Set([p.sub]);
  (SRV_FILES[p.kom] || []).forEach(q => {
    if (q.cat !== "transport" || q === p) return;
    if (Math.abs(q.lat - p.lat) < 0.0006 && Math.abs(q.lon - p.lon) < 0.0011) out.add(q.sub);
  });
  return [...out];
}

/* A redraw tears down and rebuilds every marker, so it is worth not doing on every pan.
   The rows are gathered for a viewport padded by 15 %, which means a small pan is still
   covered by what is already on the map; only a pan past that padding, a zoom, or a
   filter change needs new markers. `force` is what the filter and the file loader pass. */
function srvNeedsRedraw() {
  if (!LF.srvDrawn || LF.srvDrawn.zoom !== LF.map.getZoom()) return true;
  const v = LF.map.getBounds(), b = LF.srvDrawn.bounds;
  return !(b.contains(v.getNorthEast()) && b.contains(v.getSouthWest()));
}
function lfServicesLayers(force) {
  if (!LF.map) return;
  if (MK.srv && SRV && !force && LF.srvG && !srvNeedsRedraw()) { srvLoadVisible(); return; }
  ["srvG", "srvStG"].forEach(k => { if (LF[k] && LF.map) { LF.map.removeLayer(LF[k]); LF[k] = null; } });
  if (!MK.srv || !SRV) { LF.srvDrawn = null; setServicesLegend(); return; }
  srvLoadVisible();
  LF.srvDrawn = { zoom: LF.map.getZoom(), bounds: LF.map.getBounds().pad(0.15) };
  const rows = srvRows();
  LF.srvN = rows.length;
  const touch = srvCoarse(), rDot = touch ? 6.5 : 4.5, rSt = touch ? 9 : 7;
  const dots = [], stations = [];
  rows.forEach(p => {
    const col = srvColor(p);
    if (srvIsStation(p)) {
      /* a station is a click target first: the same radius as the infra station markers */
      const halo = L.circleMarker([p.lat, p.lon], { pane: "srvpane", radius: rSt + 2, stroke: false, fillColor: "#FFFFFF", fillOpacity: .95, interactive: false });
      const m = L.circleMarker([p.lat, p.lon], { pane: "srvpane", radius: rSt, color: col, weight: 2.2, opacity: .95,
        fillColor: col, fillOpacity: .9, className: "infra-shape srv-station" });
      m.on("mouseover", () => { m.setRadius(rSt + 2); halo.setRadius(rSt + 4); }).on("mouseout", () => { m.setRadius(rSt); halo.setRadius(rSt + 2); });
      m.on("click", e => L.popup({ maxWidth: 420, autoPanPadding: [24, 24] }).setLatLng(e.latlng || [p.lat, p.lon]).setContent(srvPopup(p)).openOn(LF.map));
      stations.push(halo, m);
    } else {
      /* the dense categories go on the canvas renderer — thousands of SVG paths would stall the pan */
      const m = L.circleMarker([p.lat, p.lon], { renderer: amOf(LF.map).srv, radius: rDot,
        color: "#FFFFFF", weight: 1.4, opacity: .95, fillColor: col, fillOpacity: 1 });
      m.on("click", e => L.popup({ maxWidth: 420, autoPanPadding: [24, 24] }).setLatLng(e.latlng || [p.lat, p.lon]).setContent(srvPopup(p)).openOn(LF.map));
      dots.push(m);
    }
  });
  LF.srvG = L.layerGroup(dots).addTo(LF.map);
  LF.srvStG = L.layerGroup(stations).addTo(LF.map);
  setServicesLegend();
}

/* ---- legend: the keys to what is drawn. The filters moved to Layers ▾ (spec §4.5) ---- */
function srvLegendHtml() {
  const z = srvZoom(), n = LF.srvN || 0;
  const catRow = (k, c) => {
    const below = z < srvCatZoom(k);
    return `<div class="lgrow srvcat">
      <i style="background:${c.color};border-radius:50%"></i>${esc(c.label)}
      ${below ? `<em class="srvzoom">zoom in</em>` : ""}</div>`;
  };
  const modes = [...SF.tmodes].filter(g => SRV_TGROUP[g]).map(g => SRV_TGROUP[g].label);
  /* Bus is a sub-toggle rather than a category, so it needs its own line: without it a
     reader who switched Bus on at zoom 13 sees nothing and is told nothing. */
  const hints = Object.entries(SRV_CAT).filter(([k]) => srvCatOn(k) && z < srvCatZoom(k))
    .map(([, c]) => c.label)
    /* …but only once: below Transport's own floor the category is already named, and
       adding "rail & metro stops, bus stops" after it just says the same thing twice */
    .concat(z < srvCatZoom("transport") ? [] : Object.entries(SRV_TGROUP)
      .filter(([g, t]) => SF.cats.has("transport") && SF.tmodes.has(g) && z < t.zoom)
      .map(([, t]) => t.label + " stops"));
  return lgTitle("Services", `OSM &amp; Rejseplanen ${esc((SRV && SRV.asof) || "")}`)
    + `${Object.entries(SRV_CAT).filter(([k]) => srvCatOn(k)).map(([k, c]) => catRow(k, c)).join("")}
    ${SF.cats.has("transport") && modes.length ? `<div class="lgrow gk">${esc(modes.join(" · "))}</div>` : ""}
    ${!SF.cats.size ? `<div class="lgrow gk allhidden">All categories hidden — Layers ▾</div>` : ""}
    ${hints.length ? `<div class="lgnote srvhint">Zoom in to see ${esc(hints.join(", ").toLowerCase())}</div>` : ""}
    <div class="lgnote">${!SF.cats.size ? "nothing drawn"
      : `${nf(LF.srvN || 0, 0)} drawn in view${n >= SRV_MAX_MARKERS ? " · at the drawing ceiling — zoom in" : ""}`}</div>`;
}
function setServicesLegend() {
  const el = document.getElementById("serviceslegend"); if (!el) return;
  const live = !!(MK.srv && SRV && document.getElementById("lfmap"));
  if (!live) { el.innerHTML = ""; el.style.display = "none"; return; }
  el.style.display = "";
  el.innerHTML = srvLegendHtml();
  lgApplyFold(el);
  lgFitSoon();
}

/* ---------- The legend stack ----------
   Up to five blocks stack bottom-right in #maplegs, which is more than a laptop screen gives away
   for free. Every block's own header folds it; the fold is remembered per legend box, so a
   re-render (a filter, a pan, a horizon change) never springs a legend the reader closed back open. */
const LEGC = new Set();                     /* the ids of the legends the reader folded shut */
const LEGO = new Set();                     /* …and of the ones the reader re-opened by hand */
function lgTitle(main, sub, extra) {
  return `<div class="lgtitle" data-legfold role="button" tabindex="0" title="Click to fold this legend away">${main}<span>${sub || ""}${extra || ""}</span></div>`;
}
function lgApplyFold(el) { if (el) el.classList.toggle("folded", LEGC.has(el.id)); }
function lgFold(el) {
  const box = el.closest(".maplegend"); if (!box || !box.id) return;
  /* a legend the stack folded to make room opens on the first click and stays open from then on */
  if (box.classList.contains("afold")) { box.classList.remove("afold"); LEGO.add(box.id); return; }
  LEGC.has(box.id) ? LEGC.delete(box.id) : LEGC.add(box.id);
  lgApplyFold(box);
  lgFitSoon();
}
/* Spec §4.5: the legends stack bottom-right, never overlap, and the stack stays inside 60 % of the
   map's height (AC-LG1). Flex column-reverse does the first two; this pass does the third — it folds
   the topmost feature-layer legend to its title until the stack fits, oldest-first from the top and
   never the indicator legend, which is the one that explains the fill. */
const LG_MAX_SHARE = 0.6;              /* of the map's height (spec §4.5) */
const LG_MAX_W = 460;                  /* two 220 px cards and the gap between them — never three */
const LG_FOLD_ORDER = ["serviceslegend", "publiclegend", "infralegend", "climatelegend"];
let LGFIT = 0;
function lgFitSoon() {
  if (typeof requestAnimationFrame !== "function") { lgFit(); return; }
  if (LGFIT) return;                        /* one pass per frame, however many legends were refilled */
  LGFIT = requestAnimationFrame(() => { LGFIT = 0; lgFit(); });
}
/* P6: the mini map carries the same stack (indicator legend first, the pin's overlays under it), so
   the 60 % rule is applied to it too — with its own fold order, widest layer first. */
const MM_FOLD_ORDER = ["anpublegend", "anmicrolegend", "aninfralegend"];
function lgFit() {
  lgFitIn(document.getElementById("maplegs"), document.getElementById("lfmap"), LG_FOLD_ORDER);
  const mm = document.querySelector(".minimap .maplegs");
  if (mm) lgFitIn(mm, mm.closest(".minimap"), MM_FOLD_ORDER);
}
function lgFitIn(wrap, map, order) {
  if (!wrap || !map) return;
  const live = () => [...wrap.children].filter(e => e.offsetWidth > 0 && e.offsetHeight > 0);
  live().forEach(e => e.classList.remove("afold"));
  const fits = () => {
    const m = map.getBoundingClientRect(), top = m.bottom - m.height * LG_MAX_SHARE;
    if (wrap.getBoundingClientRect().width > Math.min(LG_MAX_W, m.width - 24) + 1) return false;
    return live().every(e => { const r = e.getBoundingClientRect();
      return r.top >= top - 1 && r.bottom <= m.bottom + 1 && r.left >= m.left - 1 && r.right <= m.right + 1; });
  };
  for (let i = 0; i < order.length && !fits(); i++) {
    const el = document.getElementById(order[i]);
    if (el && !LEGO.has(el.id) && el.offsetHeight > 0) el.classList.add("afold");
  }
}

/* ---------- Climate: an indicator family with a context layer (Kystdirektoratet · DMI Klimaatlas) --
   v3.0, spec §1 decision 3: Climate is NOT an overlay you switch on. Choosing any Climate indicator
   (a) makes the period control a horizon (Today · 2070 · 2120, §4.3), and (b) draws the published
   storm-surge extent for that horizon plus the official risk areas as a *context layer* under the
   fill, with its own keys-only legend card and one row in Layers ▾ to hide it (`zones=0`). Choosing
   a non-Climate indicator removes both. The zones are the same source rendered geometrically, so
   they only make sense next to the figure they explain — which is why they are not a layer.
     · one horizon drives both the zones on the map and the value every Climate indicator shows, so
       the map and the choropleth can never disagree about the period;
     · the zones are drawn in their own pane with pointer events off, so a fill that covers half
       the country still cannot take a click away from the polygon underneath it.
   Data: data/processed/climate (scripts/build_kyst_zones.py, build_climate.py), docs/CLIMATE_BUILD_LOG.md */
const CLIM = D.climate || null;
/* the horizons, the labels and the point-in-extent test live in src/climate_core.js, which is
   inlined just above this file and unit-tested by tests/climate.test.js — one definition, not two */
const CC = (typeof window !== "undefined" && window.CLIMATE_CORE) || {};
const CLIM_HZ = CC.CLIM_HZ;
const HZ = { h: "today" };                                   /* the one horizon, hash hz= */
const CLIM_KEYS = new Set(IND.filter(i => i.group === "Climate").map(i => i.key));
const isClim = k => CLIM_KEYS.has(k);
/* the two things the context layer draws — the published extent and the official risk areas */
const CLIM_LAY = CC.CLIM_LAY;
const CLIM_ZOOM = 10;                       /* below this the zones are not fetched at all */
const CLIM_MAX_FILES = 12;                  /* a hard ceiling on one pass, whatever the viewport */
const CZ = {};                              /* "<horizon>:<kommune>" → FeatureCollection once fetched */
let CRA = null;                             /* climate/risk_areas.json once fetched */
const pad4 = c => String(Number(c)).padStart(4, "0");
/* the zones are drawn on the macro map whenever a Climate indicator is the one being read, unless
   the reader ticked them off in Layers ▾ (`zones=0`) — spec §1 decision 3, AC-L3 */
const climOn = () => !!(CLIM && S.view === "makro" && isClim(MK.ind) && MK.zones);
/* one blue per horizon — the surge indicators' own hue (registry hue [16,64,120]) darkened as the
   horizon moves out. No depth classes: Kystdirektoratet publishes an extent, not a depth we bin. */
const CLIM_COL = { today: "#6E9CC2", "2070": "#2F6FA8", "2120": "#123E66" };
const CLIM_ZONE_YEAR = CC.CLIM_ZONE_YEAR;
/* every label names both periods: the zones are Kystdirektoratet's published extents, the figures
   are Klimaatlas periods, and the two are not the same calendar */
const CLIM_FIG = CC.CLIM_FIG;
const hzShort = CC.hzShort;
const hzLabel = CC.hzLabel;
const CLIM_FOOT = "Official screening data for comparing areas — Kystdirektoratet flood zones (100-year event) and DMI Klimaatlas. Not a property-level assessment.";
const climZones = h => ((CLIM && CLIM.zones) || {})[h || HZ.h] || {};
const climZoneMeta = h => (climZones(h).meta) || {};
const climKom = code => ((CLIM && CLIM.kommune) || {})[pad4(code)] || null;
const climRiskNames = code => ((CLIM && CLIM.risk_names) || {})[pad4(code)] || [];

/* ---- the horizon: hash, pill, and the value every Climate indicator shows ---- */
function climParseHz(q) { HZ.h = CC.hzParse(q); }
function climSetHz(h) {
  if (!CLIM_HZ.includes(h) || h === HZ.h) return;
  HZ.h = h;
  /* the zones already on the map belong to the old horizon */
  lfDrop("climZoneG");
  LF.climDrawn = null;
  syncHash();
  /* the area page and the test property redraw their panel and map in place (AC-P4) */
  if (areaRefresh() || tpRefresh()) return;
  renderKeep();
}
/* the pill itself — in the legend and, when a Climate indicator is selected, beside the indicator */
function hzPill(where) {
  return `<div class="seg hzpill" data-testid="period-hz" role="group" aria-label="Climate horizon"><span class="segl">Horizon</span>${CLIM_HZ.map(h =>
    `<button class="sg ${HZ.h === h ? "on" : ""}" data-hz="${h}" title="${esc(hzLabel(h))}">${esc(hzShort(h))}</button>`).join("")}</div>`
    + (where === "tools" ? `<span class="hzlab dim" title="${esc(hzLabel(HZ.h))}">${esc(hzLabel(HZ.h))}</span>` : "");
}
/* A Climate indicator has no year series: its value for an area is read from the climate index at
   the selected horizon. surge_dw_pct is the one with a figure of its own below kommune level —
   postal codes and Copenhagen quarters carry their own share, so it is never marked °. */
/* `hz` is the horizon to read; the callers that follow the pill leave it out and get HZ.h. Charts
   pass all three, because a Climate chart puts the horizons on the x axis rather than the pill. */
function climValue(o, k, hz) {
  if (!CLIM || !o) return null;
  const h = (CLIM_HZ && CLIM_HZ.indexOf(hz) >= 0) ? hz : HZ.h;
  if (k === "surge_dw_pct") {
    const z = climZones(h);
    if (o.nr != null) { const e = (z.postnr || {})[o.nr]; if (e) return e.surge_dw_pct ?? null; }
    else if (o.bydel != null) { const e = (z.kvarter || {})[o.code]; if (e) return e.surge_dw_pct ?? null; }
    if (o.nr != null || o.bydel != null) {
      /* not listed = no dwelling of its own inside the published polygon, which is 0 % where the
         kommune has a zone at all, and no figure where it has none */
      const km = climKom(o.muni || CPH_MUNI);
      const kv = km && km.surge_dw_pct ? km.surge_dw_pct[h] : null;
      return kv == null ? null : 0;
    }
  }
  const km = climKom(o.code || o.muni);
  const e = km && km[k];
  if (!e) return null;
  /* Two Climate indicators have no horizon at all — the insurers' claim count and the official
     designation are one published figure, not a projection. They read the same at every horizon
     rather than going blank when the pill moves. */
  return e[climHzFor(k, h)] ?? null;
}
const climHzFor = (k, hz) => { const h = hz || HZ.h; const i = indOf(k); return (i && i.horizon && i.horizon.indexOf(h) >= 0) ? h : "today"; };
/* why a Climate value is missing, in the publisher's own terms — never a best rank, never a zero */
function climReason(o, k) {
  if (!CLIM || !o) return "";
  const km = climKom(o.code || o.muni || CPH_MUNI);
  const e = km && km[k];
  return (e && e.reason) || "not computed";
}

/* ---- loading: risk areas once, surge zones per kommune for the viewport ---- */
function climRiskLoad() {
  if (CRA || CZ._riskLoading || CZ._riskError) return;
  CZ._riskLoading = true;
  fetch("climate/risk_areas.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { CRA = d; delete CZ._riskLoading; if (climOn() && LF.map) lfClimateLayers(true); })
    .catch(() => { delete CZ._riskLoading; CZ._riskError = true; setClimateLegend(); });
}
function climLoad(h, code) {
  const c = pad4(code), k = `${h}:${c}`;
  if (CZ[k] || CZ["_l_" + k] || CZ["_e_" + k]) return;
  CZ["_l_" + k] = true;
  fetch(`climate/surge_${h}/${c}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { CZ[k] = d; delete CZ["_l_" + k];
      if (climOn() && LF.map && HZ.h === h) lfClimateLayers(true);
      if (S.view === "climate") renderKeep();
      else if (S.view === "analysis") { anFill(); anMapOverlays(); } })
    .catch(() => { delete CZ["_l_" + k]; CZ["_e_" + k] = true; });
}
/* every kommune's bounding box, from the postal-code rings already in the page — one pass, cached */
const CLIM_BB = {};
function climBboxes() {
  if (CLIM_BB._done) return CLIM_BB;
  AREAS.forEach(a => {
    const k = String(Number(a.muni)); let b = CLIM_BB[k];
    if (!b) b = CLIM_BB[k] = [90, 180, -90, -180];
    (a.rings || []).forEach(r => r.forEach(p => {
      if (p[0] < b[0]) b[0] = p[0]; if (p[1] < b[1]) b[1] = p[1];
      if (p[0] > b[2]) b[2] = p[0]; if (p[1] > b[3]) b[3] = p[1];
    }));
  });
  CLIM_BB._done = true;
  return CLIM_BB;
}
function climLoadVisible() {
  if (!LF.map || !climOn()) return;
  if (LF.map.getZoom() < CLIM_ZOOM) return;
  const bb = climBboxes(), v = LF.map.getBounds(), c = v.getCenter();
  const have = climZones().kommune || {};
  const hits = [];
  Object.keys(have).forEach(code => {
    const b = bb[String(Number(code))]; if (!b) return;
    if (v.getSouth() <= b[2] && v.getNorth() >= b[0] && v.getWest() <= b[3] && v.getEast() >= b[1])
      hits.push([code, Math.abs((b[0] + b[2]) / 2 - c.lat) + Math.abs((b[1] + b[3]) / 2 - c.lng)]);
  });
  hits.sort((a, b) => a[1] - b[1]).slice(0, CLIM_MAX_FILES).forEach(([code]) => climLoad(HZ.h, code));
}
const climLoaded = h => Object.keys(CZ).filter(k => !k.startsWith("_") && k.startsWith((h || HZ.h) + ":")).map(k => CZ[k]);

/* ---- point in zone: the one question a published extent can answer about a point ---- */
const pipLL = CC.pipLL, gjHit = CC.gjHit;
/* true / false when the kommune's file for that horizon is loaded, null while it is not */
function climInZone(lat, lon, h, kom) {
  const c = kom != null ? pad4(kom) : null;
  const key = c ? `${h}:${c}` : null;
  if (key) return CZ[key] ? CC.inZone(lat, lon, [CZ[key]]) : (CZ["_e_" + key] ? false : null);
  return CC.inZone(lat, lon, climLoaded(h));
}
/* which official risk area a point falls in, once risk_areas.json is loaded */
function climRiskAt(lat, lon) {
  if (!CRA) return null;
  const f = (CRA.features || []).find(x => gjHit(lat, lon, x.geometry));
  return f ? f.properties : null;
}

/* ---- the layer ---- */
function lfClimateLayers(force) {
  if (!LF.map) return;
  lfDrop("climAreaG", "climZoneG");
  if (!climOn()) { LF.climDrawn = null; setClimateLegend(); return; }
  const rend = amOf(LF.map).clim;
  if (!CRA) climRiskLoad();
  else LF.climAreaG = L.geoJSON(CRA, { pane: "climpane", renderer: rend, interactive: false,
    style: { color: "#16262E", weight: 1.3, opacity: .9, fill: false, dashArray: "5 3" } }).addTo(LF.map);
  if (LF.map.getZoom() >= CLIM_ZOOM) {
    climLoadVisible();
    const fcs = climLoaded();
    if (fcs.length) {
      const col = CLIM_COL[HZ.h];
      LF.climZoneG = L.geoJSON(fcs, { pane: "climpane", renderer: rend, interactive: false,
        style: { color: col, weight: .7, opacity: .6, fillColor: col, fillOpacity: .42 } }).addTo(LF.map);
    }
  }
  LF.climDrawn = { zoom: LF.map.getZoom(), h: HZ.h };
  setClimateLegend();
}
/* ---- legend: the keys to the context layer. The horizon is the PeriodControl in the toolbar and
        the on/off is the `zones` row in Layers ▾ — neither belongs in a legend (spec §4.5) ---- */
function climLegendHtml() {
  const z = LF.map ? LF.map.getZoom() : 7;
  const n = climLoaded().length;
  const zoomIn = z < CLIM_ZOOM;
  const row = (label, swatch, note) => `<div class="lgrow">${swatch}${esc(label)}${note ? `<em class="srvzoom">${esc(note)}</em>` : ""}</div>`;
  const areaSw = `<i style="background:transparent;border:1.3px dashed #16262E"></i>`;
  const zoneSw = `<i style="background:${CLIM_COL[HZ.h]}99;border-color:${CLIM_COL[HZ.h]}"></i>`;
  return lgTitle("Climate context", `${CLIM_LAY.surge} ${esc(CLIM_ZONE_YEAR[HZ.h])} · Kystdirektoratet &amp; DMI`)
    + row(`${CLIM_LAY.surge} ${esc(CLIM_ZONE_YEAR[HZ.h])}`, zoneSw, zoomIn ? "zoom in" : "")
    + row(CLIM_LAY.areas, areaSw, CRA ? "" : CZ._riskError ? "unavailable" : "loading…")
    /* the horizon's two calendars are the caption under the period control — not repeated here */
    + (zoomIn ? `<div class="lgnote srvhint">Zoom in to ${CLIM_ZOOM} to see the storm-surge zones</div>`
              : `<div class="lgnote">${nf(n, 0)} municipal zone file${n === 1 ? "" : "s"} drawn · 100-year event</div>`)
    + `<div class="lgnote">${esc(CLIM_FOOT)}</div>`;
}
function setClimateLegend() {
  const el = document.getElementById("climatelegend"); if (!el) return;
  const live = !!(climOn() && document.getElementById("lfmap"));
  if (!live) { el.innerHTML = ""; el.style.display = "none"; lgFitSoon(); return; }
  el.style.display = "";
  el.innerHTML = climLegendHtml();
  lgApplyFold(el);
  lgFitSoon();
}

/* ---- Verify at source, the climate layer's own kinds ----
   The recipe lives in the registry (`climate_src`), so this builds the publisher's own query
   rather than a hard-coded URL, and scripts/check_source_links.py builds the identical one from
   the same block — a drift between the page and the checker would show up there. */
function climSrcUrl(i, kom) {
  const q = i && i.climate_src; if (!q) return "";
  if (q.kind === "dataset" || q.kind === "service") return q.url || "";
  if (q.kind === "service_layer") return `${q.service}/${(q.layer || {})[HZ.h]}`;
  if (q.kind !== "arcgis" || !kom) return "";
  const km = climKom(kom);
  /* the sea indicators are published per coastal stretch, the rain ones per kommune */
  const area = q.area_field === "kystkode" ? (km && km.kystkode) : String(Number(kom));
  if (!area) return "";
  const h = (q.horizon || {})[HZ.h] || {};
  const where = Object.entries(Object.assign({}, q.where, h))
    .map(([k, v]) => `${k}=${v}`).concat(`${q.area_field}='${String(area).trim()}'`).join(" AND ");
  return `${q.service}?where=${encodeURIComponent(where)}`
    + `&outFields=${encodeURIComponent((q.out_fields || ["*"]).join(","))}&returnGeometry=false&f=html`;
}
function climSrcLink(i, kom, label) {
  const u = climSrcUrl(i, kom); if (!u) return "";
  const q = i.climate_src, who = q.publisher || "the publisher";
  const what = q.kind === "arcgis" ? `the published cells this value is read from, at the ${hzShort(HZ.h)} horizon`
    : q.kind === "service_layer" ? `the published ${CLIM_ZONE_YEAR[HZ.h]} flood-extent layer this share is counted inside`
    : q.kind === "dataset" ? "the publisher's own dataset behind this figure"
    : "the publisher's own service";
  return `<a class="srclink" href="${esc(u)}" target="_blank" rel="noopener"
    title="Open ${esc(what)} — straight from ${esc(who)}">${esc(label || "Verify at source")} ↗ <span class="dim">(${esc(who)})</span></a>`;
}
/* the legend's note for a Climate indicator: the horizon in full, and what a grey area means */
function climLegendNote(ind) {
  const pool = curPool();
  const miss = {};
  pool.forEach(o => { if (V(o, ind.key) == null) { const r = climReason(o, ind.key); miss[r] = (miss[r] || 0) + 1; } });
  const parts = Object.entries(miss).map(([r, n]) => `${n} ${esc(r)}`);
  return `${esc(hzShort(HZ.h))} · ${esc(CLIM_FIG[HZ.h])}` + (parts.length ? ` · no figure: ${parts.join(", ")}` : "");
}

/* ---- the popup block: what the climate layer knows about the area under the click ---- */
function climPopupBlock(a, muni) {
  if (!climOn()) return "";
  const kom = muni ? muni.code : a.muni;
  const km = climKom(kom); if (!km) return "";
  const pt = LF.climPt;
  const inZone = pt ? climInZone(pt.lat, pt.lng, HZ.h, kom) : null;
  const ra = pt ? climRiskAt(pt.lat, pt.lng) : null;
  const names = ra ? [ra.area_name] : climRiskNames(kom);
  const i = IND.find(x => x.key === "surge_dw_pct");
  const share = climValue(a, "surge_dw_pct");
  const zm = climZoneMeta();
  const row = (l, v) => v == null || v === "" ? "" : `<span class="lfrow"><span>${esc(l)}</span><b>${v}</b></span>`;
  return `<div class="lfclim"><span class="lfsec">Climate risk</span>
    <div class="lfrows">
      ${row("Hazard", `Storm surge · ${esc(zm.event || "100-årshændelse")}`)}
      ${row("Horizon", esc(hzLabel(HZ.h)))}
      ${pt && inZone !== null ? row("This point", inZone ? `<b class="climin">inside the ${esc(CLIM_ZONE_YEAR[HZ.h])} zone</b>` : "outside the zone") : ""}
      ${share != null && i ? row(`Dwellings in the zone${a.nr != null || a.bydel != null ? "" : " (municipality)"}`, `${fmtOf(i)(share)}`) : ""}
      ${names.length ? row("Official risk area", esc(names.join(" · "))) : row("Official risk area", "not designated")}
      ${row("Source", esc(zm.source || ""))}
      ${row("Fetched", esc(zm.built || (CLIM.meta && CLIM.meta.built) || ""))}
    </div>
    <span class="lfact"><button class="lk mini" data-go="climate/${esc(pad4(kom))}">Open climate sheet ›</button></span></div>`;
}

/* Compare (#compare?a=…&b=…) was deleted in v3.0 — owner amendment A1. There is no view, no state
   and no nav item; the old link redirects to the first area's own page (src/route_core.js ALIASES).
   What it did well — two areas, one row per indicator, no overall winner — is what the area page's
   All-figures table and Charts do without asking the reader to pick a second area first. */

/* ---------- Climate sheet (#climate/<kommune>), area-card line and the Analysis section ---------- */
const CS = { code: null };
const climInds = () => IND.filter(i => i.group === "Climate");
/* the three horizons of one indicator for one kommune, with the scenario range under each figure */
function climHzCells(i, km) {
  const e = km[i.key] || {};
  const fixed = !(i.horizon && i.horizon.length);     /* published once, not per horizon */
  return CLIM_HZ.map(h => {
    const v = e[fixed ? "today" : h];
    if (v == null) return `<td class="num dim" title="${esc(e.reason || "not computed")}">–</td>`;
    if (fixed && h !== "today") return `<td class="num dim" title="One published figure, the same at every horizon">${fmtOf(i)(v)} <em class="climrange">same</em></td>`;
    const r = (e.range || {})[h];
    return `<td class="num" data-v="${v}">${fmtOf(i)(v)}${r && r.low != null && r.high != null
      ? `<em class="climrange" title="Low scenario (sea SSP1-2.6 / rain RCP2.6) to high (SSP5-8.5 / RCP8.5), same percentile">${fmtTight(i)(r.low)}–${fmtTight(i)(r.high)}</em>` : ""}</td>`;
  }).join("");
}
function climSheetLoad() {
  if (!CS.code) return;
  CLIM_HZ.forEach(h => { if ((climZones(h).kommune || {})[CS.code]) climLoad(h, CS.code); });
  climRiskLoad();
}
function vClimate() {
  const km = climKom(CS.code), m = byCode[String(Number(CS.code))];
  if (!km || !m) return `<div class="back"><button data-go="map">‹ Macro map</button></div><div class="card"><p class="empty">No climate data for that municipality.</p></div>`;
  const zon = CLIM_HZ.map(h => (climZones(h).kommune || {})[CS.code] || 0);
  const dw = km.surge_dw_pct || {};
  const risk = climRiskNames(CS.code), marginal = (km.flood_risk_area || {}).marginal;
  const claims = IND.find(i => i.key === "weather_claims_1000");
  const crk = claims ? rankOf(m, "weather_claims_1000", MUNI) : null;
  const others = (km.other_kystkoder || []).map((c, n) => `${c}${(km.other_kystnavne || [])[n] ? ` (${String(km.other_kystnavne[n]).trim().replace(/_/g, " ")})` : ""}`);
  const hi = h => HZ.h === h ? ' class="hi"' : "";
  return `
  <div class="card accent arhead">
    <div class="arid"><h2>${esc(km.name)} — climate risk</h2>
      <div class="artags"><span class="tag">Municipality ${esc(CS.code)}</span>
        ${km.coastal ? `<span class="tag">Coast stretch ${esc(km.kystkode)} · ${esc(String(km.kystnavn || "").trim().replace(/_/g, " "))}</span>` : `<span class="tag">landlocked</span>`}
        <span class="tag">${risk.length ? `Official risk area: ${esc(risk.join(" · "))}` : marginal ? "Touches a risk area (under 1 km²)" : "No designated risk area"}</span></div>
    </div>
    <div class="tools"><button class="lk" data-back>‹ Back</button>
      <button class="lk primary" data-go="map/${esc(String(Number(CS.code)))}?ind=surge_dw_pct&hz=${HZ.h}">Show the zones on the map</button>
      <button class="lk" data-go="${withQ(`area/kommune/${String(Number(CS.code))}`)}">${esc(km.name)} page ›</button>${periodHz("sheet")}</div>
    ${sheetTiles([
      ["Dwellings in the surge zone", dw[HZ.h] != null ? fmtOf(IND.find(i => i.key === "surge_dw_pct"))(dw[HZ.h]) : DASH,
       (dw.dwellings_in_zone || {})[HZ.h] != null ? `${nf((dw.dwellings_in_zone || {})[HZ.h], 0)} of ${nf(dw.dwellings, 0)} dwellings` : esc(dw.reason || "")],
      ["Zone area", zon[CLIM_HZ.indexOf(HZ.h)] ? nf(zon[CLIM_HZ.indexOf(HZ.h)], 1) + " km²" : DASH, `Kystdirektoratet ${esc(CLIM_ZONE_YEAR[HZ.h])} · 100-year event`],
      claims ? ["Weather-damage claims", fmtOf(claims)(V(m, "weather_claims_1000")), rankHtml(crk, "municipalities")] : null])}
    <p class="cap">${esc(hzLabel(HZ.h))}</p>
  </div>
  <div class="card">
    <div class="card-head"><h3>Every climate figure, all three horizons</h3><span class="hint">small grey = the low–high scenario range at the same percentile</span></div>
    <div class="scrollx"><table class="tbl compact climtbl" data-sortable><thead><tr><th>Indicator</th>
      <th class="num"${hi("today")}>Today<br><span class="dim">1981–2010 · zones 2020</span></th>
      <th class="num"${hi("2070")}>2070<br><span class="dim">2041–70 · zones 2070</span></th>
      <th class="num"${hi("2120")}>2120<br><span class="dim">2071–2100 · zones 2120</span></th>
      <th class="num">Rank</th><th class="ansrc">Source</th></tr></thead>
    <tbody>${climInds().map(i => { const rk = rankOf(m, i.key, MUNI);
      return `<tr><th><span class="thn">${esc(i.label)} <span class="dim">${esc(i.unit || "")}</span></span><span class="im" data-m="${esc(i.key)}">ⓘ</span></th>
        ${climHzCells(i, km)}
        <td class="num">${rk ? rankHtml(rk, "municipalities") : DASH}</td>
        <td class="ansrc">${climSrcLink(i, String(Number(CS.code)), "Verify")}</td></tr>`; }).join("")}
    </tbody></table></div>
    <p class="cap">↓ lower is better throughout. A dash is the publisher having no figure for this municipality — a landlocked kommune has no sea level, which is not a zero. Rank is among the ${MUNI.length} municipalities at the selected horizon.</p>
  </div>
  <div class="grid-2">
    <div class="card"><div class="card-head"><h3>Dwellings in the storm-surge zone</h3><span class="hint">BBR dwelling points inside the published extent</span></div>
      <table class="tbl compact"><thead><tr><th>Horizon</th><th class="num">Zone</th><th class="num">Dwellings in it</th><th class="num">Share</th></tr></thead>
      <tbody>${CLIM_HZ.map((h, n) => `<tr${HZ.h === h ? ' class="hi"' : ""}><th>${esc(hzShort(h))} <span class="dim">· extent ${esc(CLIM_ZONE_YEAR[h])}</span></th>
        <td class="num">${zon[n] ? nf(zon[n], 1) + " km²" : "–"}</td>
        <td class="num">${(dw.dwellings_in_zone || {})[h] != null ? nf((dw.dwellings_in_zone || {})[h], 0) : "–"}</td>
        <td class="num">${dw[h] != null ? nf(dw[h], 2) + " %" : "–"}</td></tr>`).join("")}</tbody></table>
      <p class="cap">Denominator: ${dw.dwellings != null ? nf(dw.dwellings, 0) + " dwellings" : "–"} (BBR boligtype 1–5, status 6). A dwelling counts when its building point falls inside the published polygon, allowing 5 m — BBR gives a point, not a footprint. The three extents are Kystdirektoratet's own 100-year maps for 2020, 2070 and 2120; they are not a depth and not a property-level assessment.</p></div>
    <div class="card"><div class="card-head"><h3>Where the figures come from</h3><span class="hint">one stretch, named — never an average of several</span></div>
      <table class="tbl compact"><tbody>
        <tr><th>Coast stretch used</th><td>${km.coastal ? `${esc(km.kystkode)} — ${esc(String(km.kystnavn || "").trim().replace(/_/g, " "))}` : "none — landlocked"}</td></tr>
        <tr><th>Other stretches it touches</th><td>${others.length ? esc(others.join(" · ")) : `<span class="dim">none</span>`}</td></tr>
        <tr><th>Rule</th><td class="dim">${esc((CLIM.meta || {}).coastal_rule || "")}</td></tr>
        <tr><th>Official flood risk area</th><td>${risk.length ? `yes — ${esc(risk.join(" · "))}` : marginal ? "no — it clips a designated area by under 1 km²" : "no"}</td></tr>
        <tr><th>Klimaatlas version</th><td class="dim">${esc((((CLIM.meta || {}).klimaatlas || {}).version || []).join(" · "))} · fetched ${esc(((CLIM.meta || {}).klimaatlas || {}).fetched || "")}</td></tr>
        <tr><th>Zones</th><td class="dim">${esc(climZoneMeta().source || "")} · built ${esc(climZoneMeta().built || "")}</td></tr>
      </tbody></table>
      <p class="cap">Klimaatlas publishes the sea figures per coastal stretch, not per kommune. This municipality takes the stretch it shares the longest coastline with; every other stretch it touches is named above and never averaged into the figure. Rain and cloudbursts are published per kommune. Method: <code>docs/CLIMATE_BUILD_LOG.md</code>.</p></div>
  </div>
  ${srcNote()}`;
}
/* the CLIMATE line on an area card — only where there is something to say */
function climateLine(level, code) {
  if (!CLIM) return "";
  const kom = level === "kommune" ? code : level === "kvarter" ? CPH_MUNI : (byNr[code] || {}).muni;
  const km = climKom(kom); if (!km) return "";
  const o = level === "kommune" ? byCode[String(Number(code))] : level === "kvarter" ? byQ[code] : byNr[code];
  const v = o ? climValue(o, "surge_dw_pct") : null;
  const risk = climRiskNames(kom);
  if (v == null && !risk.length) return "";
  const i = IND.find(x => x.key === "surge_dw_pct");
  const bits = [];
  if (v != null && i) bits.push(`<button class="lk mini" data-go="climate/${esc(pad4(kom))}" title="${esc(hzLabel(HZ.h))}">${fmtOf(i)(v)} dwellings in storm-surge zone (${esc(hzShort(HZ.h))})</button>`);
  if (risk.length) bits.push(`<button class="lk mini" data-go="climate/${esc(pad4(kom))}" title="Designated under the Floods Directive, 2024 screening">official risk area</button>`);
  return `<span class="upcoming"><em>Climate</em>${bits.join("")}</span>`;
}
/* --- the test property's climate section: the pin against the published extents --- */
function anClimBody(pt, r) {
  if (!CLIM || !r || !r.kommune) return "";
  const kom = r.kommune.code, km = climKom(kom);
  if (!km) return "";
  climSheetLoadFor(kom);
  const zoneKom = h => (climZones(h).kommune || {})[pad4(kom)];
  const hits = CLIM_HZ.map(h => {
    if (!zoneKom(h)) return { h, v: false, known: true };     /* no zone at all in this kommune */
    const v = climInZone(pt.lat, pt.lon, h, kom);
    return { h, v, known: v !== null };
  });
  const line = hits.map(x => `<b class="${x.known ? (x.v ? "climyes" : "climno") : "dim"}">${esc(hzShort(x.h))} ${x.known ? (x.v ? "yes" : "no") : "…"}</b>`).join(" · ");
  const risk = climRiskAt(pt.lat, pt.lon) || (climRiskNames(kom).length ? { area_name: climRiskNames(kom).join(" · "), whole: true } : null);
  const inds = climInds();
  return `<p class="anlead">In storm-surge zone (100-yr): ${line}</p>
    <p class="cap">${risk ? `The pin ${risk.whole ? `is in a municipality with an official flood risk area (${esc(risk.area_name)})` : `falls inside the official flood risk area <b>${esc(risk.area_name)}</b>`}.` : "No official flood risk area covers this point."}
      A point inside a published extent is a screening result for the 100-year event, not a property-level assessment: the maps carry no depth we are entitled to read, and nothing here accounts for a dike, a pump or the building's own floor level.</p>
    <div class="scrollx"><table class="tbl compact climtbl"><thead><tr><th>Indicator</th><th class="num">Today</th><th class="num">2070</th><th class="num">2120</th><th class="ansrc">Source</th></tr></thead>
      <tbody>${inds.map(i => `<tr><th><span class="thn">${esc(i.label)} <span class="dim">${esc(i.unit || "")}</span></span></th>${climHzCells(i, km)}
        <td class="ansrc">${climSrcLink(i, String(Number(kom)), "Verify")}</td></tr>`).join("")}</tbody></table></div>
    <p class="cap"><button class="lk mini" data-go="climate/${esc(pad4(kom))}">Open the climate sheet for ${esc(r.kommune.name)} ›</button> Figures are the municipality's, not the address's. ${esc(hzLabel(HZ.h))}</p>`;
}
function climSheetLoadFor(kom) {
  CLIM_HZ.forEach(h => { if ((climZones(h).kommune || {})[pad4(kom)]) climLoad(h, kom); });
  climRiskLoad();
}

const SCH_META = (PUB && PUB.schools) || null;      /* {built, retrieved, years, n, benchmarks} */
const SCH_BY = {};                                  /* institutionsnummer → record */
let SCHOOLS = null, SCH_LOADING = false;
function schoolsLoad() {
  if (SCHOOLS || SCH_LOADING || !SCH_META) return;
  SCH_LOADING = true;
  fetch("schools.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { SCHOOLS = d; (d.schools || []).forEach(s => SCH_BY[s.nr] = s); SCH_LOADING = false;
      if (LF.map && MK.pub) lfPublicLayers();
      anMapOverlays();
      if (["school", "schoollist", "area", "charts"].includes(S.view)) renderKeep(); anFill(); })
    .catch(() => { SCH_LOADING = false; SCHOOLS = { schools: [] }; });
}
const schoolOf = b => (b && b.school && SCH_BY[b.school]) || null;
const SCH_YEARS = (SCH_META && SCH_META.years) || [];
const SCH_LATEST = SCH_YEARS[SCH_YEARS.length - 1] || "";
const SCH_TYPE = { "folkeskole": "Folkeskole", "fri grundskole": "Private / free school", "specialskole": "Special school" };
/* The source's own verdict on whether actual minus expected is more than noise. OVER/OVERSKO spells
   these "Over niveau" / "Under niveau" / "På niveau" — NOT the "Bedre/Dårligere end forventet" the
   SOCREFEX dimension uses. Only the first two are significant; "På niveau" means within the band. */
const SCH_SIG = { "Over niveau": "above expected", "Under niveau": "below expected" };
const schSig = v => SCH_SIG[v] || null;
const schBench = (kom, year) => ((SCH_META && SCH_META.benchmarks && SCH_META.benchmarks.kommune[kom]) || {})[year || SCH_LATEST];
const schBenchDK = year => ((SCH_META && SCH_META.benchmarks && SCH_META.benchmarks.denmark) || {})[year || SCH_LATEST];
/* a suppressed cell is absent, never zero — every reader of a school value goes through this */
const schV = (s, k) => (s && s.latest && s.latest[k] != null) ? s.latest[k] : null;
const schY = (s, k) => (s && s.latest_year && s.latest_year[k]) || "";
const SUPPRESSED = "suppressed by the source (under 3 observations; under 5 pupils for well-being and the socioeconomic reference) — not zero";
const schCell = (v, fmt) => v == null ? `<span class="dim" title="${SUPPRESSED}">–</span>` : fmt(v);
const schGrade = v => nf(v, 1);
const schDiff = v => sign(v, x => nf(x, 1));
function schoolsInView() {
  /* every school of the municipalities whose buildings are loaded — the pool the grade ramp classes */
  if (!SCHOOLS) return [];
  const loaded = new Set(Object.keys(PUB_FILES).filter(k => !k.startsWith("_")));
  const keys = MK.muni && pubAvail(MK.muni) ? new Set([String(Number(MK.muni))]) : loaded;
  return (SCHOOLS.schools || []).filter(s => keys.has(s.kom));
}
/* --- grade colouring: only when the public filter is showing Education and nothing else --- */
const GRADE_KEY = "school_grade_avg";
const gradeInd = () => IND.find(i => i.key === GRADE_KEY) || { key: GRADE_KEY, short: "FP9 grade", label: "FP9 grade average", unit: "grade 0–12", fmt: "idx" };
function gradeMode(on) {
  /* Education on its own: the Education markers carry the school's FP9 grade instead of the category
     hue. `on` is the layer state of the map asking — the Macro map's by default, the mini map's on the
     Analysis sheet. */
  return !!((on === undefined ? MK.pub : on) && SCH_META && PF.cats && PF.cats.size === 1 && PF.cats.has("education") && SCHOOLS);
}
function gradeScale() {
  return scaleOf(schoolsInView(), s => schV(s, "grade_avg"));
}
function gradeColor(b, sc) {
  const s = schoolOf(b); const v = schV(s, "grade_avg");
  if (v == null) return null;                       /* no grade → keep the base Education hue */
  const t = sc.t(v);
  return t == null ? null : mkShade(t, GRADE_KEY);
}
/* --- the school block inside a public-building popup --- */
function schoolPopupBlock(b) {
  const s = schoolOf(b); if (!s) return "";
  const row = (l, v, t) => `<span class="lfrow"><span${t ? ` title="${esc(t)}"` : ""}>${esc(l)}</span><b>${v}</b></span>`;
  const g = schV(s, "grade_avg"), kb = schBench(s.kommune, schY(s, "grade_avg")), dk = schBenchDK(schY(s, "grade_avg"));
  const d = schV(s, "soc_ref_diff"), sig = schSig(schV(s, "soc_ref_significant"));
  const socTxt = d == null ? `<span class="dim" title="${SUPPRESSED}">–</span>`
    : `${schDiff(d)}${sig ? ` <em class="schsig">✓ ${esc(sig)}</em>` : ` <em class="dim">≈ as expected</em>`}`;
  const bench = g == null ? "" : `<em class="dim">${kb != null ? `kommune ${schGrade(kb)}` : ""}${kb != null && dk != null ? " · " : ""}${dk != null ? `DK ${schGrade(dk)}` : ""}</em>`;
  return `<div class="schpop">
    <span class="schhead"><b>${esc(s.name)}</b><i class="ipill">${esc(SCH_TYPE[s.type] || s.type)}</i></span>
    <div class="lfrows">
      ${row("FP9 grade", `${schCell(g, schGrade)} ${bench}`, "average of the bundne prøver, 9th grade, across the pupils who sat them")}
      ${row("Socioeconomic reference", socTxt, "actual grade minus the grade the ministry's model expects from the pupils' background")}
      ${row("Well-being", schCell(schV(s, "trivsel_general"), v => nf(v, 1) + " / 5"), "Generel trivsel, national pupil survey")}
      ${row("Pupils", schCell(schV(s, "pupils_total"), v => nf(v, 0)))}
      ${row("Class size", schCell(schV(s, "klassekvotient"), v => nf(v, 1)))}
      ${row("School year", esc(schY(s, "grade_avg") || schY(s, "pupils_total") || SCH_LATEST))}
    </div>
    ${s.bbr_ids.length > 1 ? `<p class="cap dim">One of ${s.bbr_ids.length} buildings on this school's site — the figures belong to the school, not to this building.</p>` : ""}
    <span class="lfact"><button class="lk mini primary" data-school="${esc(s.nr)}">Open school sheet ›</button></span></div>`;
}
/* --- school datasheet (#school/<institutionsnummer>) --- */
function vSchool() {
  if (!SCHOOLS) { schoolsLoad(); return `<div class="card"><p class="empty">Loading the schools…</p></div>`; }
  const s = SCH_BY[SC.nr];
  if (!s) return `<div class="card"><p class="empty">No school with institutionsnummer ${esc(SC.nr)} in the layer.</p>
    <div class="tools"><button class="lk" data-back>‹ Back</button></div></div>`;
  const m = byCode[s.kom], area = [byNr[s.postnr], byQ[s.kvarter]].filter(Boolean);
  const gy = schY(s, "grade_avg"), kb = schBench(s.kommune, gy), dk = schBenchDK(gy);
  const g = schV(s, "grade_avg"), d = schV(s, "soc_ref_diff"), sig = schSig(schV(s, "soc_ref_significant"));
  const bld = (s.bbr_ids || []).map(id => (PUB_FILES[s.kom] || { buildings: [] }).buildings.find(b => b.id === id)).filter(Boolean);
  if (!bld.length && s.bbr_ids.length) { pubLoad(s.kom); setTimeout(() => renderKeep(), 700); }
  const yrow = (label, key, fmt) => `<tr><th>${esc(label)}</th>${SCH_YEARS.map(y => {
    const v = (s.years[y] || {})[key];
    return `<td class="num">${v == null ? `<span class="dim" title="${SUPPRESSED}">–</span>` : fmt(v)}</td>`; }).join("")}</tr>`;
  return `
  <div class="card accent arhead">
    <div class="arid"><h2>${esc(s.name)}</h2>
      <div class="artags"><span class="tag" style="color:${PUB_CAT.education.color};border-color:${PUB_CAT.education.color}55">${esc(SCH_TYPE[s.type] || s.type)}</span>
        <span class="tag">${esc(s.kommune)}</span><span class="tag">inst. no. ${esc(s.nr)}</span>
        ${s.address ? `<span class="tag">${esc(s.address)}</span>` : ""}
        ${s.enhedsart === "Afdeling (underordnet enhed)" ? `<span class="tag" title="a department of a larger school — the source may publish its figures under the parent">department</span>` : ""}</div>
    </div>
    <div class="tools"><button class="lk" data-back>‹ Back</button>
      <button class="lk primary" data-go="map/${esc(s.kom)}?ind=${encodeURIComponent(MK.ind)}&public=1&pub=edu">Show on map</button>
      ${m ? `<button class="lk" data-go="${withQ("area/kommune/" + s.kom)}">${esc(m.name)} ›</button>` : ""}
      ${area.length ? `<button class="lk" data-go="${withQ(pageOf(area[0]))}">${esc(area[0].name)} ›</button>` : ""}</div>
    ${sheetTiles([
      ["FP9 grade", schCell(g, schGrade), gy ? "bundne prøver · " + esc(gy) : "bundne prøver"],
      ["Expected", schCell(schV(s, "soc_ref_expected"), schGrade), "socioeconomic reference"],
      ["Difference", d == null ? `<span class="dim" title="${SUPPRESSED}">${DASH}</span>` : schDiff(d), sig ? "✓ " + esc(sig) : d == null ? "" : "not significant"],
      ["Well-being", schCell(schV(s, "trivsel_general"), v => nf(v, 1)), "generel trivsel · 1–5"],
      ["Pupils", schCell(schV(s, "pupils_total"), v => nf(v, 0)), schV(s, "pupils_indv_efterk") != null ? nf(schV(s, "pupils_indv_efterk"), 0) + " immigrant / descendant" : ""],
      ["Class size", schCell(schV(s, "klassekvotient"), v => nf(v, 1)), "klassekvotient"]])}
    <p class="cap srcrow">Every figure above: <a class="srclink" href="https://uddannelsesstatistik.dk/" target="_blank" rel="noopener">Verify ↗ Uddannelsesstatistik</a> · institution ${esc(s.nr)}${gy ? ` · school year ${esc(gy)}` : ""}</p>
  </div>
  <div class="grid-2">
    <div class="card"><div class="card-head"><h3>Three school years</h3><span class="hint">${esc(SCH_YEARS.join(" · "))}</span></div>
      <div class="scrollx"><table class="tbl compact"><thead><tr><th>Measure</th>${SCH_YEARS.map(y => `<th class="num">${esc(y)}</th>`).join("")}</tr></thead><tbody>
        ${yrow("FP9 grade, bundne prøver", "grade_avg", schGrade)}
        ${yrow("— dansk", "grade_dansk", schGrade)}
        ${yrow("— matematik", "grade_matematik", schGrade)}
        ${yrow("Socioeconomic reference", "soc_ref_expected", schGrade)}
        ${yrow("Difference", "soc_ref_diff", schDiff)}
        ${yrow("Well-being (generel trivsel)", "trivsel_general", v => nf(v, 1))}
        ${yrow("Pupils", "pupils_total", v => nf(v, 0))}
        ${yrow("Class size", "klassekvotient", v => nf(v, 1))}
      </tbody></table></div>
      <p class="cap">A dash is a cell the source suppressed, not a zero. The socioeconomic reference is published a year behind the grades, so the newest year usually has a grade and no reference.</p></div>
    <div class="card"><div class="card-head"><h3>Benchmarks</h3><span class="hint">FP9 grade, ${esc(gy || SCH_LATEST)}</span></div>
      <table class="tbl compact"><tbody>
        <tr><th>This school</th><td class="num"><b>${schCell(g, schGrade)}</b></td><td class="dim">${schV(s, "grade_n") != null ? nf(schV(s, "grade_n"), 0) + " pupils sat the exams" : ""}</td></tr>
        <tr><th>${esc(s.kommune)}</th><td class="num">${schCell(kb, schGrade)}</td><td class="dim">${g != null && kb != null ? schDiff(g - kb) + " vs kommune" : ""}</td></tr>
        <tr><th>Denmark</th><td class="num">${schCell(dk, schGrade)}</td><td class="dim">${g != null && dk != null ? schDiff(g - dk) + " vs Denmark" : ""}</td></tr>
      </tbody></table>
      <div class="card-head" style="margin-top:14px"><h3>Well-being, four sub-indicators</h3><span class="hint">1–5</span></div>
      <table class="tbl compact"><tbody>
        ${[["Faglig trivsel — academic", "trivsel_faglig"], ["Social trivsel — social", "trivsel_social"],
           ["Støtte og inspiration — support", "trivsel_stoette"], ["Ro og orden — calm and order", "trivsel_ro"]]
          .map(([l, k]) => `<tr><th>${esc(l)}</th><td class="num">${schCell(schV(s, k), v => nf(v, 1))}</td></tr>`).join("")}
        <tr><th class="dim">Responses</th><td class="num dim">${schCell(schV(s, "trivsel_n"), v => nf(v, 0))}</td></tr>
      </tbody></table></div>
  </div>
  <div class="card"><div class="card-head"><h3>Buildings on this site</h3>
      <span class="hint">${s.bbr_ids.length} BBR building${s.bbr_ids.length === 1 ? "" : "s"} · ${s.bbr_match === "421" ? "anvendelse 421 Grundskole" : s.bbr_match === "fallback_42x" ? "no 421 within 150 m — matched on 420/429" : "no education building within 150 m"}</span></div>
    ${bld.length ? `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Building</th><th>BBR use</th><th class="num">Floor area<br><span class="dim">m²</span></th><th class="num">Built</th><th class="num">Floors</th></tr></thead>
      <tbody>${bld.map(b => `<tr class="clickrow" data-pubsheet="${esc(b.id)}" data-pubkom="${esc(b.kom)}"><th><span class="thn">${esc(pubName(b))} <span class="go">›</span></span></th>
        <td class="dim">${esc(b.code)} ${esc(b.label)}</td><td class="num" data-v="${b.m2 || 0}">${b.m2 ? nf(b.m2, 0) : "–"}</td>
        <td class="num" data-v="${b.year || ""}">${b.year || "–"}</td><td class="num">${b.floors || "–"}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="empty">${s.bbr_ids.length ? "loading the municipality's buildings…" : "No BBR education building within 150 m of the register point — the school is listed without a footprint."}</p>`}
    <p class="cap">Campus rule: every BBR building within 150 m of the school's register point is attached to it, so the figures above describe the school and are repeated on each of its buildings.</p></div>
  <div class="card"><p class="cap"><b>Source:</b> Uddannelsesstatistik.dk, retrieved ${esc((SCH_META || {}).retrieved || "")} — <i>Kilde: Uddannelsesstatistik.dk</i>. Location, type and institution number from the STIL institutionsregister. Buildings from BBR via Datafordeler.
    A grade average mostly tracks intake; the socioeconomic reference is what the source publishes it against. Method and discretion rules: <code>docs/SCHOOLS.md</code>.</p></div>`;
}
/* --- the schools segment on an area card's PUBLIC line --- */
function schoolLine(level, code) {
  const e = pubOf(level, code); if (!e || e.school_grade_avg == null) return "";
  return `<button class="lk mini" data-schoollist="${level}:${code}" style="border-color:${PUB_CAT.education.color}66"
    title="FP9 grade of the ${e.schools_n} folkeskoler and frie grundskoler here that publish one, averaged across their pupils">schools ${nf(e.school_grade_avg, 1)} avg</button>`;
}
/* --- list panel: the schools of one area, sorted by grade --- */
function vSchoolList() {
  if (!SCHOOLS) { schoolsLoad(); return `<div class="card"><p class="empty">Loading the schools…</p></div>`; }
  const [level, code] = (SL.key || "").split(":");
  const e = pubOf(level, code) || {};
  const areaName = level === "kommune" ? (byCode[code] || {}).name : level === "postnr" ? (byNr[code] || {}).name : (byQ[code] || {}).name;
  const rows = (SCHOOLS.schools || []).filter(s => level === "kommune" ? s.kom === String(Number(code)) : level === "postnr" ? s.postnr === code : s.kvarter === code);
  const sorted = rows.slice().sort((a, b) => (schV(b, "grade_avg") ?? -1) - (schV(a, "grade_avg") ?? -1));
  return `
  <div class="card accent">
    <div class="card-head"><h3>Schools — ${esc(areaName || code)}</h3>
      <span class="hint">${rows.length} school${rows.length === 1 ? "" : "s"} · ${esc(SCH_LATEST)} · Uddannelsesstatistik.dk</span></div>
    <div class="tfilters"><button class="lk mini" data-back>‹ Back</button>
      ${e.school_grade_avg != null ? `<span class="hint">area average ${nf(e.school_grade_avg, 1)} · ${e.schools_n} folkeskoler and frie grundskoler · ${nf(e.school_pupils || 0, 0)} pupils</span>` : ""}</div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>School</th><th>Type</th><th class="num">FP9 grade</th><th class="num">vs expected</th><th class="num">Well-being</th><th class="num">Pupils</th><th class="num">Class size</th></tr></thead>
      <tbody>${sorted.map(s => { const d = schV(s, "soc_ref_diff"), sig = schSig(schV(s, "soc_ref_significant")); return `<tr class="clickrow" data-school="${esc(s.nr)}">
        <th><span class="thn">${esc(s.name)} <span class="go">\u203a</span></span></th>
        <td class="dim">${esc(SCH_TYPE[s.type] || s.type)}</td>
        <td class="num" data-v="${schV(s, "grade_avg") ?? ""}">${schCell(schV(s, "grade_avg"), schGrade)}</td>
        <td class="num" data-v="${d ?? ""}">${d == null ? `<span class="dim" title="${SUPPRESSED}">–</span>` : schDiff(d) + (sig ? ` <em class="schsig">✓</em>` : "")}</td>
        <td class="num" data-v="${schV(s, "trivsel_general") ?? ""}">${schCell(schV(s, "trivsel_general"), v => nf(v, 1))}</td>
        <td class="num" data-v="${schV(s, "pupils_total") ?? ""}">${schCell(schV(s, "pupils_total"), v => nf(v, 0))}</td>
        <td class="num" data-v="${schV(s, "klassekvotient") ?? ""}">${schCell(schV(s, "klassekvotient"), v => nf(v, 1))}</td></tr>`; }).join("")
        || `<tr><td colspan="7" class="empty">no schools in this area</td></tr>`}</tbody></table></div>
    <p class="cap">Sorted by FP9 grade. A dash is suppressed by the source, not a zero — ${sorted.filter(s => schV(s, "grade_avg") == null).length} of these schools publish no grade (no 9th grade, or too few pupils). Specialskoler are listed but never enter the area average. ✓ marks a difference the source calls statistically significant. Kilde: Uddannelsesstatistik.dk, retrieved ${esc((SCH_META || {}).retrieved || "")}.</p>
  </div>`;
}
/* --- a small grade trend for one municipality, used in the Charts view --- */
function schoolTrend(komName, komCode) {
  if (!SCHOOLS) return null;
  const rows = (SCHOOLS.schools || []).filter(s => s.kom === String(Number(komCode)) && ["folkeskole", "fri grundskole"].includes(s.type));
  const pts = SCH_YEARS.map(y => {
    let a = 0, w = 0;
    rows.forEach(s => { const o = s.years[y] || {}; if (o.grade_avg != null) { const k = o.grade_n || 1; a += o.grade_avg * k; w += k; } });
    return w ? a / w : null;
  });
  return pts.some(v => v != null) ? { name: komName, pts, dk: SCH_YEARS.map(y => schBenchDK(y) ?? null) } : null;
}
function schoolTrendSvg(t) {
  const W = 640, H = 200, P = { l: 40, r: 150, t: 14, b: 28 };
  const all = t.pts.concat(t.dk).filter(v => v != null);
  const lo = Math.floor(Math.min(...all) * 2) / 2 - .25, hi = Math.ceil(Math.max(...all) * 2) / 2 + .25;
  const x = i => P.l + (W - P.l - P.r) * (SCH_YEARS.length < 2 ? .5 : i / (SCH_YEARS.length - 1));
  const y = v => P.t + (H - P.t - P.b) * (1 - (v - lo) / (hi - lo || 1));
  const path = a => a.map((v, i) => v == null ? null : `${i && a[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean).join(" ");
  const grid = [lo, (lo + hi) / 2, hi].map(v => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="#E2E7E1"/><text x="${P.l - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" class="cax">${nf(v, 1)}</text>`).join("");
  const last = (a) => { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return i; return -1; };
  const li = last(t.pts), di = last(t.dk);
  return `<svg class="chart schchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="FP9 grade average by school year">
    ${grid}
    ${SCH_YEARS.map((yy, i) => `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="cax">${esc(yy.replace("/", "/").slice(2))}</text>`).join("")}
    <path d="${path(t.dk)}" fill="none" stroke="#8A9488" stroke-width="1.6" stroke-dasharray="4 3"/>
    <path d="${path(t.pts)}" fill="none" stroke="${PUB_CAT.education.color}" stroke-width="2.4"/>
    ${t.pts.map((v, i) => v == null ? "" : `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.2" fill="${PUB_CAT.education.color}"/>`).join("")}
    ${li >= 0 ? `<text x="${W - P.r + 8}" y="${(y(t.pts[li]) + 4).toFixed(1)}" class="cax" fill="${PUB_CAT.education.color}">${esc(t.name)} ${nf(t.pts[li], 1)}</text>` : ""}
    ${di >= 0 ? `<text x="${W - P.r + 8}" y="${(y(t.dk[di]) + 4).toFixed(1)}" class="cax" fill="#6B7469">Denmark ${nf(t.dk[di], 1)}</text>` : ""}
  </svg>`;
}
function schoolsChartCard() {
  if (!SCH_META) return "";
  if (!SCHOOLS) { schoolsLoad(); return ""; }
  const koms = CH.areas.filter(a => a.startsWith("kommune:")).map(a => a.split(":")[1]).filter(c => byCode[c]);
  const trends = koms.map(c => schoolTrend((byCode[c] || {}).name, c)).filter(Boolean);
  if (!trends.length) return "";
  return `<div class="card"><div class="card-head"><h3>Schools</h3>
      <span class="hint">FP9 grade average, bundne prøver · ${esc(SCH_YEARS[0])} → ${esc(SCH_LATEST)}</span></div>
    ${trends.map(t => `<div class="chartbox">${schoolTrendSvg(t)}</div>`).join("")}
    <p class="cap">Averaged over the folkeskoler and frie grundskoler of the municipality that publish a grade, across the pupils who sat the exams rather than across the schools; specialskoler excluded. Dashed = Denmark. This is a three-year snapshot, not the long series the chart above draws. Kilde: Uddannelsesstatistik.dk, retrieved ${esc((SCH_META || {}).retrieved || "")}.</p></div>`;
}

/* ---------- Project datasheet (#project/<id>) and Pipeline table (#pipeline) ---------- */
function projectEntity() { return INFRA_BY[PR.id] || null; }
/* the postal codes and quarters a project serves, from the spatial index */
function infraAreas(id, level) {
  return Object.entries(INFRA_IDX).filter(([k, v]) => k.startsWith(level + ":") && v.projects.some(p => p.id === id))
    .map(([k]) => k.split(":")[1]);
}
function vProject() {
  const f = projectEntity();
  if (!f) return `<div class="card"><p class="empty">Unknown project.</p></div>`;
  const p = f.properties, s = geomStats(f), st = infraSt(p);
  const bn = p.budget_mdkk == null ? null : nf(p.budget_mdkk / 1000, 1) + " bn DKK";
  const priceNote = /2015 prices|price level|PL\d|09PL|PL09/i.test(p.notes || "") ? "price basis — see the note below" : "";
  mapInit(prMapInit);
  const tile = (l, v, sub) => v == null || v === "" ? "" : `<div><span>${esc(l)}</span><b>${v}</b>${sub ? `<em>${esc(sub)}</em>` : ""}</div>`;
  const kom = (p.kommuner || []).map(c => byCode[c]).filter(Boolean);
  const pnr = infraAreas(p.id, "postnr").map(c => byNr[c]).filter(Boolean);
  const kva = infraAreas(p.id, "kvarter").map(c => byQ[c]).filter(Boolean);
  const chips = (list, href) => list.map(o => `<button class="lk mini" data-go="${withQ(href(o))}">${esc(o.name || o.nr)}</button>`).join("");
  return `
  <div class="card accent arhead">
    <div class="arid">
      <h2>${esc(p.name)}</h2>
      <div class="artags"><span class="tag">${esc(INFRA_TYPE[p.type] || p.type)}</span><span class="tag st-${esc(p.status)}">${esc(st.label)}</span>${p.agency ? `<span class="tag">${esc(p.agency)}</span>` : ""}${p.schematic ? `<span class="tag">schematic geometry</span>` : ""}</div>
    </div>
    <div class="tools"><button class="lk" data-back>‹ Back</button>${p.map !== false ? `<button class="lk primary" data-go="map?ind=${encodeURIComponent(MK.ind)}&infra=1&focus=${encodeURIComponent(p.id)}">Show on map</button>` : ""}<a class="lk" href="${esc(p.source_url)}" target="_blank" rel="noopener">Source ↗</a></div>
    ${sheetTiles([
      ["Opening", esc(openLabel(p)), p.open_year_original && p.open_year_original !== p.open_year ? `originally ${p.open_year_original}` : ""],
      ["Budget", bn || DASH, priceNote],
      s.km ? ["Length", nf(s.km, 1) + " km", p.schematic ? "schematic" : "as mapped"] : null,
      s.stations ? ["Stations", String(s.stations), "in this project"] : null,
      s.ha ? ["Area", nf(s.ha, 0) + " ha", p.schematic ? "schematic" : "as mapped"] : null])}
    <p class="cap srcrow"><a class="srclink" href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.source_doc || p.agency || "Source")} ↗</a>${p.updated ? ` · updated ${esc(p.updated)}` : ""}</p>
  </div>
  ${p.schematic ? `<div class="card"><p class="cap">⚠ Schematic corridor — not an official alignment. It shows where the project runs, not how it will be built, so the length above is indicative.</p></div>` : ""}
  <div class="grid-2">
    <div class="card">
      <div class="card-head"><h3>Where it runs</h3><span class="hint">over ${esc(curInd().short || curInd().label)}</span></div>
      <div class="mapwrap"><div id="prmap"></div><div class="maplegend small" id="prlegend"></div></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Areas served</h3><span class="hint">click to open it on the map</span></div>
      ${kom.length ? `<p class="cap">Municipalities</p><div class="tfilters">${chips(kom, o => "map/" + o.code)}</div>` : ""}
      ${pnr.length ? `<p class="cap">Postal codes (${pnr.length})</p><div class="tfilters">${chips(pnr.slice(0, 14), o => pageOf(o))}${pnr.length > 14 ? `<span class="hint">+${pnr.length - 14} more</span>` : ""}</div>` : ""}
      ${kva.length ? `<p class="cap">Copenhagen quarters (${kva.length})</p><div class="tfilters">${chips(kva.slice(0, 10), o => pageOf(o))}${kva.length > 10 ? `<span class="hint">+${kva.length - 10} more</span>` : ""}</div>` : ""}
      ${(() => { const ol = outlookFor(kom, kva.slice(0, 8)); return ol ? `<div class="olsec"><p class="cap"><b>Outlook around this project</b> — how the areas it serves are projected to change. A projection carries no housing programme, so this project is not in these numbers.</p>${ol}</div>` : ""; })()}
      <p class="cap">${esc(p.notes || "")}</p>
      <p class="cap dim">${esc(p.source_doc || "")}${p.source_doc ? " · " : ""}geometry: ${esc(p.geometry_source || "–")} · updated ${esc(p.updated || "")}</p>
    </div>
  </div>`;
}
function prMapInit() {
  if (S.view !== "project") return;               /* a render for another view got in first */
  const el = document.getElementById("prmap"); if (!el || typeof L === "undefined") return;
  const f = projectEntity(); if (!f) return;
  dropMap("pmap");
  const map = L.map(el, { center: [56, 10.5], zoom: 7, scrollWheelZoom: true, zoomSnap: .5, attributionControl: false });
  LF.pmap = map; syncMaps();
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap" }).addTo(map);
  /* the current choropleth underneath, so the project is read against the market picture */
  const ind = curInd(), sc = scaleOf(MUNI, m => V(m, ind.key), null, ind);
  MUNI.forEach(m => muniAreas(m.code).forEach(a => {
    const t = sc.t(V(m, ind.key));
    L.polygon(a.rings, { color: "#FFFFFF", weight: .5, fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .55, interactive: false }).addTo(map);
  }));
  const p = f.properties, style = infraStyle(p);
  const layer = f.geometry.type === "Point"
    ? L.circleMarker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { radius: 8, color: infraSt(p).color, weight: 3, fillColor: "#FFFFFF", fillOpacity: 1 })
    : L.geoJSON(f, { style: { ...style, weight: Math.max(style.weight, 4) } });
  layer.addTo(map);
  INFRA_ALL.filter(x => x.properties.parent_id === p.id && x.geometry.type === "Point").forEach(x =>
    L.circleMarker([x.geometry.coordinates[1], x.geometry.coordinates[0]], { radius: 5, color: infraSt(x.properties).color, weight: 2, fillColor: "#FFFFFF", fillOpacity: 1 })
      .bindTooltip(esc(infraShort(x.properties))).addTo(map));
  const b = layer.getBounds ? layer.getBounds() : L.latLngBounds([layer.getLatLng()], [layer.getLatLng()]);
  map.fitBounds(b, { padding: [40, 40], maxZoom: 13 });
  setLegend("prlegend", sc, ind, ind.key, "municipalities");
}
/* ---------- Pipeline ---------- */
function pipeRows() {
  return INFRA_ALL.filter(f => (!PIPE.type || f.properties.type === PIPE.type) && (!PIPE.status || f.properties.status === PIPE.status))
    .slice().sort((a, b) => (INFRA_ORDER[a.properties.status] - INFRA_ORDER[b.properties.status])
      || ((a.properties.open_year || 9999) - (b.properties.open_year || 9999)) || a.properties.name.localeCompare(b.properties.name));
}
const INFRA_ORDER = { construction: 0, decided: 1, study: 2, opened: 3 };
function vPipeline() {
  const rows = pipeRows();
  const types = [...new Set(INFRA_ALL.map(f => f.properties.type))].sort();
  const bn = v => v == null ? "–" : nf(v / 1000, 1);
  return `
  ${dataTabs()}
  <div class="card accent">
    <div class="card-head tools-only"><div class="tools">
      <select id="pptype" class="indsel"><option value="">All types</option>${types.map(x => `<option value="${x}" ${PIPE.type === x ? "selected" : ""}>${esc(INFRA_TYPE[x] || x)}</option>`).join("")}</select>
      <select id="ppstatus" class="indsel"><option value="">All statuses</option>${Object.keys(INFRA_ORDER).map(s => `<option value="${s}" ${PIPE.status === s ? "selected" : ""}>${esc(INFRA_ST[s].label)}</option>`).join("")}</select>
      <span class="hint">${rows.length} of ${INFRA_ALL.length} projects</span>
      <button class="lk mini" data-csv-pipe title="Every project in the layer, with the areas it serves and its source document — the same file Export ▾ › Projects writes">⤓ Projects (CSV)</button></div></div>
    <p class="cap">Sources: Fingerplan, Anlægsstatus and the agencies' own decision documents.</p>
    <div class="scrollx"><table class="tbl compact wraphead" data-testid="projects-table" data-sortable><thead><tr>
      <th>Project</th><th>Type</th><th>Status</th><th>Opening</th><th class="num">Budget<br><span class="dim">bn DKK</span></th><th>Agency</th><th>Municipalities</th></tr></thead>
      <tbody>${rows.map(f => { const p = f.properties; const kom = (p.kommuner || []).map(c => (byCode[c] || {}).name).filter(Boolean);
        return `<tr class="clickrow" data-pipe="${esc(p.id)}"><th><span class="thn">${esc(p.name)} <span class="go">›</span></span>${p.schematic ? ` <span class="dim">schematic</span>` : ""}</th>
          <td class="dim">${esc(INFRA_TYPE[p.type] || p.type)}</td><td><span class="ipill st-${esc(p.status)}">${esc(infraSt(p).label)}</span></td>
          <td data-v="${p.open_year || ""}">${esc(openLabel(p))}${p.open_year_original && p.open_year_original !== p.open_year ? ` <span class="dim">orig. ${p.open_year_original}</span>` : ""}</td>
          <td class="num" data-v="${p.budget_mdkk ?? ""}">${bn(p.budget_mdkk)}</td><td class="dim">${esc(p.agency || "")}</td>
          <td class="dim">${esc(kom.slice(0, 3).join(", "))}${kom.length > 3 ? ` +${kom.length - 3}` : ""}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="cap">Every project in the layer, including the ones kept off the map (a nationwide programme has no alignment). Click a row to see it on the map, or to open its sheet when it has no alignment. Budgets are in the price level each source states — open a project for the caveat. Sources and method: <code>docs/INFRA.md</code>.</p>
  </div>`;
}

/* ---------- Public building sheet (#public/<kommune>/<id>) and list panel (#publist/…) ---------- */
function pubFind(kom, id) {
  const f = PUB_FILES[String(Number(kom))];
  return f ? (f.buildings || []).find(b => b.id === id) || null : null;
}
function vPublic() {
  const b = pubFind(PB.kom, PB.id);
  if (!b) { pubLoad(PB.kom); setTimeout(() => { if (pubFind(PB.kom, PB.id)) renderKeep(); }, 700);
    const k = String(Number(PB.kom));
    return `<div class="card">${PUB_FILES["_error_" + k]
      ? stateCard("error", `Could not load public/${String(k).padStart(4, "0")}.json.`,
          "Reload, or open the BBR record at the source ↗.", `<button class="lk" data-back>‹ Back</button>`)
      : stateCard("loading", "Loading the building…", `public/${String(k).padStart(4, "0")}.json · BBR via Datafordeler`)}</div>`; }
  const c = pubCat(b), area = [byNr[b.postnr], byQ[b.kvarter]].filter(Boolean), m = byCode[b.kom];
  mapInit(() => pbMapInit(b));
  return `
  <div class="card accent arhead">
    <div class="arid"><h2>${esc(pubName(b))}</h2>
      <div class="artags"><span class="tag" style="color:${c.color};border-color:${c.color}55">${esc(c.label)}</span>
        <span class="tag">${esc(b.label)} · BBR ${esc(b.code)}</span>
        <span class="tag">${b.kind === "existing" ? "Existing" : "Open building case"}</span>${b.address ? `<span class="tag">${esc(b.address)}</span>` : ""}</div>
    </div>
    <div class="tools"><button class="lk" data-back>‹ Back</button>
      <button class="lk primary" data-go="map/${esc(b.kom)}?ind=${encodeURIComponent(MK.ind)}&public=1">Show on map</button>
      ${area.length ? `<button class="lk" data-go="${withQ(pageOf(area[0]))}">${esc(area[0].name)} ›</button>` : ""}</div>
    ${sheetTiles([
      ["Floor area", b.m2 ? nf(b.m2, 0) + " m²" : DASH, b.floors ? b.floors + " floors" : ""],
      b.kind === "existing" ? ["Built", String(b.year || DASH), "BBR opførelsesår"]
        : ["Permit", esc(b.permit || DASH), b.age_yrs != null ? nf(b.age_yrs, 1) + " years ago" : ""],
      b.kind === "case" ? ["Started", esc(b.started || "not stated"), "sag005"] : null,
      b.kind === "case" ? ["Expected completion", esc(b.expected || "not stated"), "sag009"] : null,
      ["Municipality", esc((m || {}).name || b.kom), b.postnr ? "postal code " + esc(b.postnr) : ""]])}
  </div>
  ${b.kind === "case" ? `<div class="card"><p class="cap">⚠ Owner-reported BBR case — not a confirmed construction schedule. In the pilot only 1 of 290 open cases carried an expected completion date and the median permit in København was 4.1 years old, so this says a case is open, not that the building opens soon.</p></div>` : ""}
  <div class="grid-2">
    <div class="card"><div class="card-head"><h3>Where it is</h3><span class="hint">over ${esc(curInd().short || curInd().label)}</span></div>
      <div class="mapwrap"><div id="prmap"></div><div class="maplegend small" id="prlegend"></div></div></div>
    <div class="card"><div class="card-head"><h3>Details</h3><span class="hint">BBR via Datafordeler</span></div>
      <table class="tbl compact"><tbody>
        <tr><th>BBR use code</th><td>${esc(b.code)} — ${esc(b.label)}</td></tr>
        <tr><th>Category</th><td>${esc(c.label)}</td></tr>
        <tr><th>Status</th><td>${b.kind === "existing" ? "6 Opført (existing)" : `${esc(b.bbr_status || "")} — open building case`}</td></tr>
        ${b.kind === "case" ? `<tr><th>Case number</th><td>${esc(b.case_no || "–")}</td></tr><tr><th>Owner type</th><td>${esc(b.owner || "not stated")}</td></tr>
        <tr><th>Case floor area</th><td>${b.case_m2 ? nf(b.case_m2, 0) + " m²" : "–"}</td></tr>` : ""}
        <tr><th>Postal code / quarter</th><td>${esc(area.map(a => a.name).join(" · ") || "–")}</td></tr>
        <tr><th>BBR id</th><td class="dim">${esc(b.id)}</td></tr>
        <tr><th>Name from</th><td class="dim">${b.name ? "OpenStreetMap, within 60 m (© OpenStreetMap contributors)" : "no OSM name within 60 m — address shown"}</td></tr>
      </tbody></table>
      <p class="cap">Source: BBR via Datafordeler, fetched ${esc((PUB || {}).built || "")}. Owner-reported register; the four phased-out use codes (410/420/430/440) are still in use alongside the finer ones. Method: <code>docs/PUBLIC_BUILDINGS.md</code>.</p></div>
  </div>`;
}
function pbMapInit(b) {
  if (S.view !== "public") return;                /* a render for another view got in first */
  const el = document.getElementById("prmap"); if (!el || typeof L === "undefined") return;
  dropMap("pmap");
  const map = L.map(el, { center: [b.lat, b.lon], zoom: 15, scrollWheelZoom: true, zoomSnap: .5, attributionControl: false });
  LF.pmap = map; syncMaps();
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "basemap" }).addTo(map);
  const ind = curInd(), sc = scaleOf(MUNI, m => V(m, ind.key), null, ind);
  (byCode[b.kom] ? muniAreas(b.kom) : []).forEach(a => {
    const t = sc.t(V(byCode[b.kom], ind.key));
    L.polygon(a.rings, { color: "#FFFFFF", weight: .6, fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .45, interactive: false }).addTo(map);
  });
  const c = pubCat(b);
  L.circleMarker([b.lat, b.lon], { radius: 9, color: c.color, weight: 3, fillColor: b.kind === "existing" ? c.color : "#FFFFFF",
    fillOpacity: b.kind === "existing" ? .85 : 1, dashArray: b.kind === "existing" ? null : "3 3" }).addTo(map);
  setLegend("prlegend", sc, ind, ind.key, "municipalities");
}
/* list panel: the public buildings of one area, filtered by category and kind */
function vPubList() {
  const [level, code, cat, kind] = (PL.key || "").split(":");
  const e = pubOf(level, code);
  const areaName = level === "kommune" ? (byCode[code] || {}).name : level === "postnr" ? (byNr[code] || {}).name : (byQ[code] || {}).name;
  const kom = level === "kommune" ? code : level === "postnr" ? (byNr[code] || {}).muni : CPH_MUNI;
  const file = PUB_FILES[String(Number(kom))];
  if (!file) { pubLoad(kom); setTimeout(() => { if (PUB_FILES[String(Number(kom))]) renderKeep(); }, 700); }
  const rows = ((file || {}).buildings || []).filter(b =>
    (level === "kommune" ? b.kom === String(Number(code)) : level === "postnr" ? b.postnr === code : b.kvarter === code)
    && (!cat || b.cat === cat) && (kind === "case" ? b.kind === "case" && b.recent : kind === "existing" ? b.kind === "existing" : true));
  const stale = (e || {}).stale_cases || 0;
  const sorted = rows.slice().sort((a, b) => (b.m2 || 0) - (a.m2 || 0));
  const btn = (label, c2, k2, on) => `<button class="lk mini ${on ? "primary" : ""}" data-publist="${esc(level)}:${esc(code)}:${c2}:${k2}">${esc(label)}</button>`;
  return `
  <div class="card accent">
    <div class="card-head"><h3>Public buildings — ${esc(areaName || code)}</h3>
      <span class="hint">${rows.length} shown · BBR ${esc((PUB || {}).built || "")}</span></div>
    <div class="tfilters"><button class="lk mini" data-back>‹ Back</button>
      ${btn("All categories", "", kind || "", !cat)}${Object.entries(PUB_CAT).map(([k, c]) => btn(c.label, k, kind || "", cat === k)).join("")}
      ${btn("Existing", cat || "", "existing", kind === "existing")}${btn("Open cases", cat || "", "case", kind === "case")}${btn("Both", cat || "", "", !kind)}</div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Building</th><th>Category</th><th>BBR use</th><th class="num">Floor area<br><span class="dim">m²</span></th><th class="num">Built</th><th>Status</th><th>Permit</th></tr></thead>
      <tbody>${sorted.map(b => `<tr class="clickrow" data-pubsheet="${esc(b.id)}" data-pubkom="${esc(b.kom)}"><th><span class="thn">${esc(pubName(b))} <span class="go">›</span></span></th>
        <td class="dim">${esc(pubCat(b).label)}</td><td class="dim">${esc(b.code)} ${esc(b.label)}</td>
        <td class="num" data-v="${b.m2 || 0}">${b.m2 ? nf(b.m2, 0) : "–"}</td><td class="num" data-v="${b.year || ""}">${b.year || "–"}</td>
        <td>${b.kind === "existing" ? "Existing" : "Open case"}</td><td class="dim">${esc(b.permit || "")}${b.age_yrs != null ? ` (${nf(b.age_yrs, 1)} yr)` : ""}</td></tr>`).join("")
        || `<tr><td colspan="7" class="empty">${file ? "nothing matches this filter" : "loading the municipality's buildings…"}</td></tr>`}</tbody></table></div>
    ${stale ? `<details class="dinfo"><summary>Stale open cases (permit > ${(PUB || {}).recent_years} yrs): ${stale}</summary>
      <div class="note">BBR cases that were never closed. They are counted here but never drawn on the map: an old open case says nothing about current construction — see <code>docs/PUBLIC_BUILDINGS.md</code>.</div></details>` : ""}
    <p class="cap">BBR via Datafordeler, ${esc((PUB || {}).built || "")}; names from OpenStreetMap where one lies within 60 m. An open case is owner-reported and is not a construction schedule.</p>
  </div>`;
}

/* ---------- Market view (Denmark-only panel) ---------- */
function spark(series, w = 160, h = 26) {
  const v = (series || []).map(p => p.v).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - 2 - (x - lo) / sp * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts}"/></svg>`;
}
/* a period label from the macro series: 2026M08 = month, 2026K2 = quarter, 2026 = year */
const NAT_PERIOD = t => /K\d$/.test(String(t)) ? "quarter" : /M\d\d$/.test(String(t)) ? "month" : "year";
/* the last five years of a series — enough to read the shape, short enough to stay a sparkline */
function natLast5(series) {
  const s = (series || []).filter(p => p.v != null);
  if (!s.length) return s;
  const last = Number(String(s[s.length - 1].t).slice(0, 4));
  return s.filter(p => Number(String(p.t).slice(0, 4)) >= last - 5);
}
/* Data › National series (spec §5.3): the four headline tiles as a compact row, then one row per
   series — value, period, y/y, source, sparkline. The four large charts are gone; Charts is where a
   series is studied at size. */
function vMarket() {
  if (MKT.src) return `${dataTabs()}${vSources()}`;
  const mac = D.macro || {}, lt = mac.latest || {};
  if (!Object.keys(lt).length) return `${dataTabs()}<div class="card"><p class="empty">No national series built yet — run the pipeline (see Sources).</p></div>`;
  const tile = key => { const o = lt[key]; if (!o) return ""; const yoy = o.yoy;
    return `<div data-testid="tile-${esc(key)}"><span>${esc(o.label || key)}</span><b>${nf(o.v, o.dec ?? 1)}<i class="u">${esc(o.unit || "")}</i></b>
      <em class="k ${yoy > 0 ? "up" : yoy < 0 ? "dn" : ""}">${yoy != null ? sign(yoy, x => nf(x, 1) + " %") + " y/y" : "no y/y"} · ${esc(o.t || "")}</em></div>`; };
  const heroKeys = mac.hero || ["rent_index", "hpi_flats", "supply_dk", "completions"];
  const tableKeys = mac.table || Object.keys(lt);
  const row = k => { const o = lt[k]; if (!o) return "";
    const pts = natLast5((mac.series || {})[k]);
    return `<tr><th><span class="thn">${esc(o.label || k)}</span></th>
      <td class="num" data-v="${o.v}">${nf(o.v, o.dec ?? 1)}${o.unit ? ` <span class="dim">${esc(o.unit)}</span>` : ""}</td>
      <td class="dim">${esc(o.t || "")} <span class="tag mini">${NAT_PERIOD(o.t)}</span></td>
      <td class="num ${o.yoy > 0 ? "good" : o.yoy < 0 ? "bad" : ""}" data-v="${o.yoy ?? ""}">${o.yoy != null ? sign(o.yoy, x => nf(x, 1) + " %") : "–"}</td>
      <td class="dim">${esc(o.src || "")}</td>
      <td class="sp">${pts.length > 1 ? `<span class="sparkbox" title="${esc(pts[0].t)} → ${esc(pts[pts.length - 1].t)}">${spark(pts)}</span>` : `<span class="dim">–</span>`}</td></tr>`; };
  return `
  ${dataTabs()}
  <div class="hero hero-nat">${heroKeys.map(tile).join("")}</div>
  <div class="card"><div class="card-head"><h3>National series</h3><span class="hint">${tableKeys.length} series · latest available period each</span></div>
    <div class="scrollx"><table class="tbl compact" data-testid="national-table" data-sortable><thead><tr>
      <th>Series</th><th class="num">Latest</th><th>Period</th><th class="num">y/y</th><th>Source</th><th data-nosort>Last 5 years</th></tr></thead>
      <tbody>${tableKeys.map(row).join("")}</tbody></table></div>
    <p class="cap">${esc(mac.note || "")} The sparkline shows the last five years of the same series; open Charts for the full history. Period tags: month, quarter or year as the publisher reports it.</p></div>`;
}

/* ---------- Data › Sources (spec §5.3) ----------
   The v2.6 accordion became a sortable table: Source · Publisher · Tables · As of · Fetched ·
   Licence · Used for · ↗. Nothing is invented — the publisher is read off the catalogue key, "used
   for" off the indicators that join to it, and an empty "Fetched" falls back to the build date with
   a `build` tag rather than leaving the reader with a blank cell (AC-D4).
   Since P7 the rows come from `EXPORT_CORE.sourceRecs()` — the very rows the Sources catalogue CSV
   writes, so the table and the file can never disagree (spec §4.9, P7 item 3).
   The register and curated sources carry no table id, so no indicator joins to them through
   `tables`. What they feed is documented in the repo (docs/PUBLIC_BUILDINGS.md, docs/INFRA.md,
   docs/SCHOOLS.md, config/indicators.json) — it is named here rather than left as a blank cell. */
const SRC_USED_EXTRA = {
  bbr: "Housing stock (BBR): dwellings, sizes, rooms, rented share",
  public: "Public buildings layer, public m² per 1,000, recent cases",
  infra: "Infrastructure pipeline, Upcoming projects, Planned stations",
  schools: "School indicators and the school sheets",
  boligstat: "Private rent (DKK/m²)",
  lbf: "Social housing rent (DKK/m²)",
  forecast: "Outlook indicators — DST municipal projection",
  cph_forecast: "Outlook indicators for Copenhagen quarters — KK projection",
  net_dwellings: "Net dwelling additions",
  kk_tryghed: "Safety survey, Copenhagen quarters",
  "climate/climate_index": "Climate indicators",
};
/* which indicators read this source — they join to the catalogue through their `tables` list */
function srcUsedFor(x) {
  const inds = IND.concat(IND_CPH).filter(i => (i.tables || []).includes(x.key));
  if (!inds.length) return { text: SRC_USED_EXTRA[x.key] || x.tables || "–", n: 0 };
  const names = inds.map(i => i.short || i.label);
  return { text: names.slice(0, 4).join(", ") + (names.length > 4 ? ` +${names.length - 4}` : ""), n: inds.length };
}
/* how many indicators join to this source — the count behind the "Used for" cell's title */
const srcUsedN = key => IND.concat(IND_CPH).filter(i => (i.tables || []).includes(key)).length;
function sourcesTable() {
  return `<div class="scrollx"><table class="tbl compact srctbl" data-testid="sources-table" data-sortable><thead><tr>
    <th>Source</th><th>Publisher</th><th>Tables</th><th>As of</th><th>Fetched</th><th>Licence</th><th>Used for</th><th data-nosort></th></tr></thead>
    <tbody>${exSourceRecs().map(x => { const n = srcUsedN(x.key);
      return `<tr><th title="${esc(x.label)}">${esc(x.label)}</th>
        <td class="dim">${esc(x.publisher || "–")}</td>
        <td class="dim"><code title="${esc(x.tables)}">${esc(x.table_id)}</code></td>
        <td data-v="${esc(x.as_of)}">${esc(x.as_of || "–")}</td>
        <td class="dim" data-v="${esc(x.fetched)}">${esc(x.fetched || "–")}${x.build_fetched ? ` <span class="tag mini" title="the publisher's own fetch date is not recorded for this source — the dashboard build date is shown instead">build</span>` : ""}</td>
        <td class="dim">${esc(x.licence || "–")}</td>
        <td class="dim" title="${esc(n ? `${n} indicator(s)` : "")}">${esc(x.used_for || "–")}</td>
        <td>${x.url ? `<a class="lk mini" href="${esc(x.url)}" target="_blank" rel="noopener" title="Open the publisher's table information">↗</a>` : ""}</td></tr>`; }).join("")
      || `<tr><td colspan="8" class="empty">no sources recorded</td></tr>`}</tbody></table></div>`;
}
function vSources() {
  const defs = (list, title) => `<div class="card"><div class="card-head"><h3>${title}</h3></div>
    <div class="scrollx"><table class="tbl compact"><thead><tr><th>Indicator</th><th>Unit</th><th>Level</th><th>Definition</th><th>Source</th><th>Caveat</th></tr></thead>
    <tbody>${list.map(i => `<tr><th>${esc(i.label)}</th><td class="dim">${esc(i.unit || "")}</td><td class="dim">${esc(i.level)}</td><td>${esc(i.desc || "")}</td><td class="dim">${esc(i.source || "")}</td><td class="dim">${esc(i.warn || "")}</td></tr>`).join("")}</tbody></table></div></div>`;
  return `<div class="card accent"><div class="card-head"><h3>Data sources and freshness</h3><span class="hint">built ${esc((D.meta && D.meta.built) || "–")} · click a column to sort</span></div>
    ${sourcesTable()}
    <p class="cap">${((D.meta && D.meta.attribution) || []).map(esc).join(" · ")}${CPH && CPH.meta && CPH.meta.attribution ? " · " + esc(CPH.meta.attribution) : ""}${SRV ? " · " + esc(SRV_ATTRIB.join(" · ")) : ""}</p>
    <p class="cap">A <b>build</b> tag in Fetched means the source file carries no fetch date of its own; the date shown is when this dashboard was built. "Used for" lists the indicators that read the table — the register and curated layers (BBR, schools, infrastructure) describe their own content instead. These are the rows <b>Export ▾ › Sources catalogue</b> writes, column for column.</p></div>
  ${IND.some(i => i.proj) ? `<div class="card"><div class="card-head"><h3>Population outlook</h3><span class="hint">projections \u2014 read the caveat</span></div>
    <table class="tbl compact"><thead><tr><th>Source</th><th>Table</th><th>Window</th><th>Vintage</th><th>Fetched</th><th>Licence</th></tr></thead><tbody>
      ${[["forecast", "Danmarks Statistik", IND.find(i => i.proj && i.proj.publisher === "DST")],
         ["cph_forecast", "K\u00f8benhavns Kommune", IND_CPH.find(i => i.proj && i.proj.table)]]
        .filter(([, , i]) => i).map(([k, pub, i]) => { const src = ((D.meta && D.meta.sources) || []).concat((D.cph && D.cph.meta && D.cph.meta.sources) || []).find(x => x.key === k) || {};
          return `<tr><th>${esc(pub)}</th><td class="dim">${esc(i.proj.table)}</td><td>${esc(i.proj.from)}\u2013${esc(IND.concat(IND_CPH).filter(z => z.proj && z.proj.table === i.proj.table).map(z => z.proj.to).sort().pop() || i.proj.to)}</td><td>${esc(i.proj.vintage)}</td><td class="dim">${esc(src.fetched || (D.meta && D.meta.built) || "\u2013")}</td><td class="dim">${esc(src.licence || "free reuse with attribution")}</td></tr>`; }).join("")}
      ${((D.meta && D.meta.sources) || []).filter(x => x.key === "net_dwellings").map(x => `<tr><th>Danmarks Statistik</th><td class="dim">BOL101 + FOLK1A</td><td>${esc((IND.find(i => i.key === "hist_net_dwell") || {}).window || "")}</td><td class="dim">measured, not projected</td><td class="dim">${esc(x.fetched || (D.meta && D.meta.built) || "–")}</td><td class="dim">${esc(x.licence || "")}</td></tr>`).join("")}
    </tbody></table>
    <p class="cap"><b>Projections are scenarios based on the publishers\u2019 assumptions about fertility, mortality and migration; Copenhagen\u2019s district forecast also reflects the city\u2019s housing plans. They are not guarantees.</b></p>
    <p class="cap">DST\u2019s municipal projection and K\u00f8benhavns Kommune\u2019s district projection are different runs and are never combined \u2014 where both exist for the same city, the gap between them is stated rather than averaged away. Every Outlook figure is a published cell or plain arithmetic on published cells; nothing here uses a fitted trend or a model of our own.</p></div>` : ""}
  ${SRV ? `<div class="card"><div class="card-head"><h3>Services layer</h3><span class="hint">${nf(Object.values(SRV.kommuner).reduce((a, k) => a + k.n, 0), 0)} points · as of ${esc(SRV.asof || "–")}</span></div>
    <table class="tbl compact"><thead><tr><th>Source</th><th>Used for</th><th>As of</th><th>Licence</th></tr></thead><tbody>
      <tr><th><a href="https://download.geofabrik.de/europe/denmark.html" target="_blank" rel="noopener">OpenStreetMap — Denmark extract (Geofabrik)</a></th>
        <td class="dim">Groceries, food &amp; drink, pharmacies</td><td>${esc(SRV.asof || "")}</td><td class="dim">ODbL 1.0 — © OpenStreetMap contributors</td></tr>
      <tr><th><a href="https://labs.rejseplanen.dk/" target="_blank" rel="noopener">Rejseplanen — static GTFS</a></th>
        <td class="dim">Metro, S-train, rail, light rail and bus stops</td><td>${esc(SRV.asof || "")}</td><td class="dim">CC BY 4.0 — Rejseplanen</td></tr>
    </tbody></table>
    <p class="cap">Stops are clustered into stations by name and mode; method and caveats in <code>docs/SERVICES.md</code>. OpenStreetMap coverage is not uniform — a rural area with no shop mapped is not the same as an area with no shop.</p></div>` : ""}
  ${defs(IND, "Indicator definitions — municipalities and postal codes")}
  ${CPH ? defs(IND_CPH, "Indicator definitions — Copenhagen quarters") : ""}`;
}

parseHash();
render();
