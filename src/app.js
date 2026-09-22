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
  int: v => nf(v, 0), days: v => nf(v, 0) + " d", m2: v => nf(v, 0) + " m²", per1000: v => per1000(v) + " / 1,000", idx: v => nf(v, 1)
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
const lowerBetter = key => IND.concat(IND_CPH).some(i => i.key === key && i.direction === "lower_better");
const cphMode = () => !!(CPH && MK.muni === CPH_MUNI && MK.cphView !== "postnr");
const S = { view: "makro" };
const YEARS = [...new Set([...((D.meta && D.meta.years) || []), ...((D.cph && D.cph.meta && D.cph.meta.years) || [])])].sort();
const LATEST = (D.meta && D.meta.latest_year) || (YEARS[YEARS.length - 1] || "");
const MK = { ind: (IND[0] || {}).key, muni: null, own: false, year: LATEST, cphView: "kvarter", micro: false, mind: "rented_pct" };
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
const AR = { type: null, code: null, group: "", ind: null, sub: "kvarter", tab: "ind" };   /* area page: group = tile group, tab = lower panel */
const UI = { indxOpen: false, mfOpen: false };                                    /* fold states that survive a re-render */
const MKT = { src: false };                                                        /* market: sources panel open */
const CH = { ind: (IND[0] || {}).key, areas: [], y0: "", y1: "", median: true, title: "", mode: "auto", dist: "size", fq: "year", ov: [], nat: true };   /* chart generator; fq = year | q, ov = overlay indicators, nat = Denmark line */
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
/* value of indicator k for municipality/area o in the selected year (latest = live field, else history) */
const V = (o, k, y) => { const yr = y || MK.year; if (!o) return null; if (!yr || yr === LATEST) return o[k] ?? null; const h = o.hist && o.hist[k]; return h && h[yr] != null ? h[yr] : null; };
/* first year a year selector offers (registry `map_from`; Safety: 2008, the first full rolling year) — Charts go further back */
const mapFrom = k => String((IND.find(i => i.key === k) || {}).map_from || "");
const yearsForPool = (k, pool) => YEARS.filter(y => y >= mapFrom(k)).filter(y => y === LATEST || pool.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
/* years with actual history for charts and sparklines — the lagging "latest" value is not repeated as a later year */
const histYears = (k, pool) => YEARS.filter(y => pool.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
function curPool() { if (S.view === "area") { const e = areaEntity(); return e ? e.peers : MUNI; } if (S.view === "table" && T.level === "kvarter") return CPH ? CPH.areas : MUNI; return cphMode() ? CPH.areas : MUNI; }
const yearsFor = k => yearsForPool(k, curPool());
const curInds = () => { if (S.view === "area") { const e = areaEntity(); return e ? e.inds : IND; } if (S.view === "table") return T.level === "kvarter" ? IND_Q : IND; return cphMode() ? IND_Q : IND; };
const curInd = () => { const L = curInds(); return L.find(i => i.key === MK.ind) || L[0] || { key: "", label: "", fmt: "pct1" }; };

/* ---------- routing (hash) ---------- */
function hashFor() {
  const q = [`ind=${encodeURIComponent(MK.ind || "")}`]; if (MK.year && MK.year !== LATEST) q.push(`y=${MK.year}`);
  if (S.view === "makro" && MK.micro) { q.push("micro=1"); q.push(`mind=${MK.mind}`); }
  let p;
  if (S.view === "area") { p = `area/${AR.type}/${AR.code}`; if (AR.group) q.push(`g=${encodeURIComponent(AR.group)}`); if (AR.sub !== "kvarter") q.push(`sub=${AR.sub}`); if (AR.tab !== "ind") q.push(`t=${AR.tab}`); }
  else if (S.view === "table") p = `table/${T.level}`;
  else if (S.view === "charts") { p = "charts"; q.length = 0; q.push(`ind=${encodeURIComponent(CH.ind)}`, `a=${CH.areas.join(",")}`, `y0=${CH.y0}`, `y1=${CH.y1}`, `med=${CH.median ? 1 : 0}`); if (CH.mode !== "auto") q.push(`mode=${CH.mode}`); if (CH.mode === "dist") q.push(`dist=${CH.dist}`);
    if (CH.fq === "q") q.push("fq=q"); if (CH.ov.length) q.push(`ov=${CH.ov.join(",")}`); if (!CH.nat) q.push("nat=0"); }
  else if (S.view === "market") { p = "market"; if (MKT.src) q.push("src=1"); }
  else if (S.view === "makro") p = "map" + (MK.muni ? "/" + MK.muni + (MK.muni === CPH_MUNI && MK.cphView === "postnr" ? "/postnr" : "") : "");
  else p = S.view;
  return p + "?" + q.join("&");
}
function parseHash() {
  const h = (location.hash || "#map").slice(1);
  const [path, qs] = h.split("?"); const parts = path.split("/").filter(Boolean);
  const q = {}; (qs || "").split("&").filter(Boolean).forEach(kv => { const [k, v] = kv.split("="); q[decodeURIComponent(k)] = decodeURIComponent(v || ""); });
  const prevView = S.view;
  if (q.ind) MK.ind = q.ind;
  MK.year = q.y && YEARS.includes(q.y) ? q.y : LATEST;
  const v = parts[0] || "map";
  if (v === "area" && parts[1] && parts[2]) { S.view = "area"; AR.type = parts[1]; AR.code = parts[2]; AR.group = q.g === "key" ? "" : (q.g || ""); AR.sub = q.sub || "kvarter"; AR.tab = ["ind", "bbr", "sub"].includes(q.t) ? q.t : "ind"; }
  else if (v === "table") { S.view = "table"; if (["kommune", "postnr", "kvarter"].includes(parts[1])) T.level = parts[1]; }
  else if (v === "sources") { S.view = "market"; MKT.src = true; }
  else if (v === "market") { S.view = "market"; MKT.src = q.src === "1"; }
  else if (v === "charts") { S.view = "charts"; CH.ind = q.ind || CH.ind; CH.areas = q.a ? q.a.split(",").filter(Boolean) : CH.areas; CH.y0 = q.y0 || CH.y0; CH.y1 = q.y1 || CH.y1; CH.median = q.med !== "0"; CH.mode = q.mode || "auto"; CH.dist = q.dist || "size";
    CH.fq = q.fq === "q" ? "q" : "year"; CH.ov = q.ov ? q.ov.split(",").filter(Boolean) : []; CH.nat = q.nat !== "0"; }
  else { S.view = "makro"; MK.muni = parts[1] && byCode[parts[1]] ? parts[1] : null; MK.cphView = parts[2] === "postnr" ? "postnr" : "kvarter";
         MK.micro = q.micro === "1" && microAvail(MK.muni); if (q.mind && MICRO_INDS.some(i => i.key === q.mind)) MK.mind = q.mind; }
  if (!curInds().some(i => i.key === MK.ind)) MK.ind = (curInds()[0] || {}).key;
  if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST;
  if (S.view === "makro") {
    /* zoom to a municipality the first time it is shown; back to the national frame when it is cleared */
    if (MK.muni && MK.muni !== LF.shownMuni) LF.pendingFit = MK.muni;
    if (!MK.muni && LF.shownMuni) { LF.center = [56.0, 10.5]; LF.zoom = 7; }
    LF.shownMuni = MK.muni;
  }
  return { viewChanged: prevView !== S.view };
}
function go(hash) { if ("#" + hash === location.hash) { parseHash(); render(); } else location.hash = hash; }
function syncHash() { history.replaceState(null, "", "#" + hashFor()); }
window.addEventListener("hashchange", () => { const r = parseHash(); render(); if (r.viewChanged) { const m = document.getElementById("main"); if (m) m.scrollTop = 0; } });

/* ---------- views & navigation ---------- */
const VIEWS = [
  ["makro",   "Macro map",     "Demographics, income, housing and prices by municipality, postal code and Copenhagen quarter", "map"],
  ["table",   "Table",         "Every municipality, postal code and quarter side by side — filter, sort, export", "table"],
  ["charts",  "Charts",        "Pick an indicator, areas and years — export the chart as PNG or the data as CSV", "charts"],
  ["market",  "Market",        "Prices, rents, supply, construction, macro indicators — and the data sources", "market"]];
const NAV_GROUPS = [["Market intelligence", ["makro", "table", "charts", "market"]]];
const viewOf = id => VIEWS.find(v => v[0] === id) || VIEWS[0];

function renderNav() {
  const on = S.view === "area" ? "makro" : S.view;
  document.getElementById("nav").innerHTML = NAV_GROUPS.map(([lab, ids]) => `<div class="nav-glab">${lab}</div>` +
    ids.map(id => { const v = viewOf(id); return `<button class="nav-item ${on === id ? "on" : ""}" data-go="${v[3]}" title="${esc(v[2])}"><b>${v[1]}</b></button>`; }).join("")).join("");
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
  else { tail = viewOf(S.view)[1]; kind = { table: "every area side by side", charts: "PNG and CSV export", market: "national series and sources" }[S.view] || ""; }
  return { c, tail, kind };
}
function renderTop() {
  const { c, tail, kind } = crumbs();
  document.getElementById("hd").innerHTML = `<nav class="crumbs">${c.map(([l, h]) => `<button data-go="${esc(h)}">${esc(l)}</button><i>›</i>`).join("")}<b>${esc(tail)}</b>${kind ? `<span class="dim">${esc(kind)}</span>` : ""}</nav>`;
}
const RENDER = { makro: vMakro, table: vTable, area: vArea, charts: vCharts, market: vMarket };
function render() {
  renderNav(); renderTop();
  const body = document.getElementById("body");
  body.innerHTML = (RENDER[S.view] || vMakro)();
  enableSort(body);
}
function renderKeep() { const m = document.getElementById("main"), y = m.scrollTop; render(); m.scrollTop = y; }

document.addEventListener("click", e => {
  const g = sel => e.target.closest(sel);
  let el;
  if ((el = g("[data-go]"))) { go(el.dataset.go); return; }
  if ((el = g("[data-tlevel]"))) { T.level = el.dataset.tlevel; if (!curInds().some(i => i.key === MK.ind)) MK.ind = curInds()[0].key; syncHash(); renderKeep(); return; }
  if (g("[data-csv]")) { exportCsv(); return; }
  if (g("[data-xall]")) { exportAll(); return; }
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
  if ((el = g("[data-micro]"))) { MK.micro = el.dataset.micro === "1"; syncHash(); renderKeep(); return; }
  if (g("[data-mcsv]")) { exportMicroCsv(); return; }
  if ((el = g("[data-argroup]"))) { AR.group = el.dataset.argroup; syncHash(); renderKeep(); return; }
  if ((el = g("[data-artab]"))) { AR.tab = el.dataset.artab; syncHash(); renderKeep(); return; }
  if ((el = g("[data-arsub]"))) { AR.sub = el.dataset.arsub; syncHash(); renderKeep(); return; }
  if ((el = g("[data-indq]"))) { MK.ind = el.dataset.indq; if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST; syncHash(); renderKeep(); return; }
  if (g("[data-mftoggle]")) { UI.mfOpen = !UI.mfOpen; const p = document.getElementById("mfpanel"), b = g("[data-mftoggle]"); if (p) p.style.display = UI.mfOpen ? "" : "none"; if (b) b.classList.toggle("on", UI.mfOpen); return; }
  if ((el = g("[data-arind]"))) { MK.ind = el.dataset.arind; if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST; syncHash(); renderKeep(); return; }
  if ((el = g(".im"))) { tipToggle(el); return; }
  tipHide();
});
document.addEventListener("change", e => {
  const el = e.target;
  if (el.id === "indsel") { MK.ind = el.value; if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST; syncHash(); renderKeep(); }
  if (el.id === "yearsel") { MK.year = el.value; syncHash(); renderKeep(); }
  if (el.id === "areaq") areaSearchGo(el.value);
  if (el.id === "mindsel") { MK.mind = el.value; syncHash(); renderKeep(); }
  if (el.id === "chind") { CH.ind = el.value; CH.ov = []; syncHash(); renderKeep(); }
  if (el.id === "chnat") { CH.nat = el.checked; syncHash(); renderKeep(); }
  if (el.id === "chy0") { CH.y0 = el.value; syncHash(); renderKeep(); }
  if (el.id === "chy1") { CH.y1 = el.value; syncHash(); renderKeep(); }
  if (el.id === "chmed") { CH.median = el.checked; syncHash(); renderKeep(); }
  if (el.id === "chdist") { CH.dist = el.value; syncHash(); renderKeep(); }
  if (el.id === "chq") { chartAdd(null, el.value); }
  if (el.id === "chtitle") { CH.title = el.value; const t = document.getElementById("chsvgtitle"); if (t) t.textContent = CH.title || chartAutoTitle(); }
  if (el.id === "mf-type") { MF.type = el.value; lfLayers(); mfBtn(); }
  if (["mf-mindw", "mf-yfrom", "mf-yto", "mf-rent"].includes(el.id)) { MF.minDw = Number(document.getElementById("mf-mindw").value) || 1; MF.yFrom = document.getElementById("mf-yfrom").value; MF.yTo = document.getElementById("mf-yto").value; MF.rentMin = Number(document.getElementById("mf-rent").value) || 0; lfLayers(); mfBtn(); }
  if (el.id === "tregion") { T.region = el.value; renderTableBody(); }
  if (el.id === "tminpop") { T.minPop = Number(el.value) || 0; renderTableBody(); }
});
document.addEventListener("input", e => { if (e.target.id === "tq") { T.q = e.target.value.trim().toLowerCase(); renderTableBody(); } });
document.addEventListener("toggle", e => { if (e.target.classList && e.target.classList.contains("indx")) UI.indxOpen = e.target.open; }, true);
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.id === "areaq") { areaSearchGo(e.target.value); return; }
  if (e.key === "Enter" && e.target.id === "chq") { chartAdd(null, e.target.value); return; }
  if (e.key === "Enter" && e.target.id === "mf-addr") { microFind(e.target.value); return; }
  if (e.key === "Escape" && S.view === "area") history.back();
});

/* ---------- info tooltips (ⓘ) ---------- */
let TIPEL = null, TIPFOR = null;
function tipToggle(el) { if (TIPFOR === el) { tipHide(); return; } tipShow(el); }
function tipShow(el) {
  const i = IND.concat(IND_CPH).find(x => x.key === el.dataset.m); if (!i) return;
  if (!TIPEL) { TIPEL = document.createElement("div"); TIPEL.className = "imtip"; document.body.appendChild(TIPEL); }
  TIPEL.innerHTML = `<b>${esc(i.label)}</b>${lowerBetter(i.key) ? `<p class="dim">↓ lower is better</p>` : ""}<p><em>Definition</em>${esc(i.desc || "")}</p>` + (i.source ? `<p><em>Source</em>${esc(i.source)}</p>` : "") +
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
function mkShade(t, key) {
  /* five steps from a light tint to the full hue, the top class deeper still — differences read at a glance */
  const i = key.startsWith("micro:") ? MICRO_INDS.find(x => x.key === key.slice(6)) : IND.concat(IND_CPH).find(x => x.key === key); const hue = (i && i.hue) || [10, 88, 70];
  const a = [232, 237, 231]; const s = 0.1 + 0.9 * Math.pow(Math.max(0, Math.min(1, t)), .9); const k = t >= .99 ? .72 : 1;
  const c = a.map((x, j) => Math.round((x + (hue[j] - x) * s) * k));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
/* quintile classes: each colour step holds a fifth of the areas, so a few outliers cannot flatten the map */
function scaleOf(list, vk, fixed) {
  const vals = list.map(vk).filter(v => v != null && !isNaN(v)).sort((a, b) => a - b);
  if (!vals.length) return { t: () => null, lo: null, hi: null, breaks: [] };
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
  const rows = []; for (let c = n - 1; c >= 0; c--) rows.push(`<div class="lgrow"><i style="background:${mkShade(n > 1 ? c / (n - 1) : .5, key)}"></i>${lab(c)}</div>`);
  return `<div class="lgtitle">${esc(ind.short || ind.label)}<span>${esc(ind.unit || "")}</span></div>` +
    (n ? rows.join("") : `<div class="lgrow dim">no data</div>`) +
    `<div class="lgrow"><i style="background:#C4CBC4"></i>no data</div>` +
    /* same ramp for every direction: darkest = highest value, which is the worst end when lower is better */
    (lowerBetter(ind.key || "") ? `<div class="lgnote">↓ lower is better · darkest = highest</div>` : "") +
    `${note ? `<div class="lgnote">${note}</div>` : ""}`;
}
function setLegend(id, sc, ind, key, note) { const el = document.getElementById(id); if (el) el.innerHTML = legendHtml(sc, ind, key, note); }
const GROUP_ORDER = ["Demographics", "Income & jobs", "Housing stock", "Housing stock (BBR)", "Rents", "Prices & market", "Construction", "Safety"];
/* "label · unit" for selects, leaving out unit parts the label already says ("Reported crime · per 1,000 inh." + "rolling 4Q") */
function optLabel(i) {
  const parts = (i.unit || "").split(" · ").filter(u => u && !i.label.includes(u) && !i.label.endsWith("· " + u.split(" ")[0]));
  return i.label + (parts.length ? " · " + parts.join(" · ") : "");
}
function indSelect() {
  const L = curInds();
  const groups = GROUP_ORDER.filter(gname => L.some(i => (i.group || "Other") === gname)).concat(L.some(i => !GROUP_ORDER.includes(i.group || "Other")) ? ["Other"] : []);
  return `<select id="indsel" class="indsel" aria-label="Indicator">${groups.map(gname => `<optgroup label="${esc(gname)}">${L.filter(i => (i.group || "Other") === gname).map(i =>
    `<option value="${i.key}" ${MK.ind === i.key ? "selected" : ""}>${esc(optLabel(i))}</option>`).join("")}</optgroup>`).join("")}</select>`;
}
function indQuick() {
  /* the six figures people ask for first, one click each */
  const L = curInds(); const ks = QUICK_KEYS.map(k => L.find(i => i.key === k)).filter(Boolean);
  return ks.length > 1 ? `<div class="iq">${ks.map(i => `<button class="iqb ${MK.ind === i.key ? "on" : ""}" data-indq="${i.key}" title="${esc(i.label)}">${esc(i.short || i.label)}</button>`).join("")}</div>` : "";
}
/* searchable area box: municipalities open on the map, postal codes and quarters open their page */
const AREA_OPTS = [{ t: "Denmark — whole country", h: "map", k: ["denmark", "danmark", "dk"] }];
MUNI.slice().sort((a, b) => a.name.localeCompare(b.name, LOCALE)).forEach(m => AREA_OPTS.push({ t: `${m.name} — municipality, ${m.region || ""}`, h: `map/${m.code}`, k: [m.name.toLowerCase(), m.code] }));
AREAS.slice().sort((a, b) => a.nr.localeCompare(b.nr)).forEach(a => AREA_OPTS.push({ t: `${a.nr} ${a.name} — postal code, ${(byCode[a.muni] || {}).name || ""}`, h: `area/postnr/${a.nr}`, k: [a.nr, (a.name || "").toLowerCase()] }));
if (CPH) CPH.areas.slice().sort((a, b) => (a.name || "").localeCompare(b.name || "", LOCALE)).forEach(q => AREA_OPTS.push({ t: `${q.name} — Copenhagen quarter, ${q.bydel || ""}`, h: `area/kvarter/${q.code}`, k: [(q.name || "").toLowerCase(), q.code] }));
function areaSearch() {
  const m = MK.muni ? byCode[MK.muni] : null;
  return `<span class="asrch"><input id="areaq" list="arealist" class="indsel" placeholder="${m ? esc(m.name) + " — search another area…" : "Search municipality, postal code or quarter…"}" autocomplete="off" aria-label="Area">
    <datalist id="arealist">${AREA_OPTS.map(o => `<option value="${esc(o.t)}"></option>`).join("")}</datalist></span>`;
}
function areaSearchGo(txt) {
  const q = (txt || "").trim(); if (!q) return;
  let o = AREA_OPTS.find(x => x.t === q);
  if (!o) { const ql = q.toLowerCase().replace(/\s+—.*$/, ""); o = AREA_OPTS.find(x => x.k.some(k => k === ql)) || AREA_OPTS.find(x => x.k.some(k => k.startsWith(ql))); }
  if (o) go(o.h + `?ind=${encodeURIComponent(MK.ind)}` + (MK.year !== LATEST ? `&y=${MK.year}` : ""));
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
    <summary><b>${esc(i.label)}</b><span class="tag">${esc(i.level_label || (i.level === "kvarter" ? "quarter level" : i.level === "postnr" ? "postal-code level" : "municipality level"))}</span><span class="tag">${esc(i.unit || "")}</span>${lb ? `<span class="tag">↓ lower is better</span>` : ""}${asofShort() ? `<span class="dim">as of ${esc(asofShort())}</span>` : ""}${i.warn ? `<span class="warnline">⚠</span>` : ""}<i class="more">ⓘ details</i></summary>
    <div class="indx-body"><p>${esc(i.desc || "")}${lb ? ` <b>↓ Lower is better</b> — rank #1 is the lowest value.` : ""}</p>
    ${i.note ? `<p class="dim"><em>Note</em> ${esc(i.note)}</p>` : ""}
    <p class="dim"><em>Source</em> ${esc(i.source || "–")}${asof ? ` · <em>As of</em> ${asof}` : ""} · <em>Coverage</em> ${cov}${ys.length > 1 ? ` · <em>History</em> ${ys[0]}–${LATEST}` : ""}</p>
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
function yearSelect() {
  const ys = yearsFor(MK.ind);
  if (ys.length < 2) return "";
  const hy = ys.filter(y => y !== LATEST); const lastHist = hy[hy.length - 1];
  const pool = curPool();
  /* rolling indicators (Safety) have no calendar value for the latest year but their live window ends in it */
  const a = curInd().asof || {}; const endYr = (String(a.kommune || a.postnr || a.kvarter || "").split("→").pop().split("–").pop().match(/\d{4}/) || [""])[0];
  const label = y => y === LATEST ? (lastHist && lastHist !== LATEST && endYr !== LATEST && !pool.some(m => m.hist && m.hist[MK.ind] && m.hist[MK.ind][LATEST] != null) ? `latest (${lastHist} data)` : `${y} (latest)`) : y;
  return `<select id="yearsel" class="indsel" aria-label="Year">${ys.filter(y => !(y === lastHist && label(LATEST).startsWith("latest ("))).map(y => `<option value="${y}" ${MK.year === y ? "selected" : ""}>${label(y)}</option>`).join("")}</select>`;
}

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
function srcNote(extra = "") {
  /* collapsed by default — "Data information" opens the source list and the small print */
  const s = (D.meta && D.meta.sources) || [];
  const list = s.map(x => `${esc(x.label)}${x.asof ? " (" + esc(x.asof) + ")" : ""}`).join(" · ");
  return `<details class="dinfo"><summary>Data information</summary><div class="note"><b>Open data.</b> ${list || "no sources recorded"}${CPH && CPH.meta && CPH.meta.attribution ? " · " + esc(CPH.meta.attribution) : ""}.
    Municipality-level indicators are shown on postal-code polygons with the municipality value (marked °) when no finer statistic exists.
    ${esc((D.meta && D.meta.note) || "")}</div>${extra}<p class="cap">Full definitions and table stamps under <button class="lk mini" data-go="market?src=1">Market › Sources</button>. Built ${esc((D.meta && D.meta.built) || "–")}.</p></details>`;
}
function rankOf(o, key, peers) {
  const v = V(o, key); if (v == null) return null;
  const vals = peers.map(p => V(p, key)).filter(x => x != null);
  const lb = lowerBetter(key);   /* #1 = best: the highest value, or the lowest where lower is better */
  return { r: 1 + vals.filter(x => lb ? x < v : x > v).length, n: vals.length };
}
/* good/bad sense of a change d in indicator key: "up" = favourable (green), "dn" = unfavourable */
const cls = (d, key) => { const s = lowerBetter(key || "") ? -d : d; return s > 0 ? "up" : s < 0 ? "dn" : ""; };
const goodBad = (d, key) => d == null ? "" : ({ up: "good", dn: "bad" })[cls(d, key)] || "";
function muniStrip(m) {
  /* the selected municipality in one line: population, region, four headline figures + crime with rank, link to its page.
     The figures are the municipality's own, so the national indicator list applies in quarter mode too. */
  const has = i => i && V(m, i.key) != null;
  const key = HL_KEYS.filter(k => !STRIP_EXTRA.includes(k)).map(k => IND.find(i => i.key === k)).filter(has).slice(0, 4)
    .concat(STRIP_EXTRA.map(k => IND.find(i => i.key === k)).filter(has));
  const cell = i => { const rk = rankOf(m, i.key, MUNI); return `<div><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(V(m, i.key))}</b><em>${rk ? `#${rk.r} of ${rk.n}` : ""}</em></div>`; };
  return `<div class="mstrip">
    <div class="mstrip-id"><b>${esc(m.name)}</b><span class="dim">${esc(m.region || "")} · ${m.pop != null ? nf(m.pop, 0) + " inhabitants" : ""} · ${muniAreas(m.code).length} ${cphMode() ? "quarters" : "postal codes"}</span></div>
    <div class="mstrip-k">${key.map(cell).join("")}</div>
    <div class="mstrip-act"><button class="lk primary" data-go="${withQ(pageOf(m))}">Open ${esc(m.name)} page ›</button><button class="lk" data-go="${chartLink(MK.ind, "kommune", m.code)}" title="Open the chart generator with this municipality">↗ Chart</button></div>
  </div>`;
}
function vMakro() {
  if (!AREAS.length || !MUNI.length) return `<div class="card"><p class="empty">No macro data built yet — run <code>make fetch</code>, <code>make geo</code> and <code>make build</code>.</p></div>`;
  const ind = curInd();
  setTimeout(lfInit, 0);
  const muni = MK.muni ? byCode[MK.muni] : null;
  return `
  <div class="card accent" id="mapcard">
    <div class="card-head tools-only">
      <div class="tools">${areaSearch()}${muni && microAvail(muni.code) ? `<div class="seg"><button class="sg ${!MK.micro ? "on" : ""}" data-micro="0">Areas</button><button class="sg ${MK.micro ? "on" : ""}" data-micro="1">Buildings (${nf(MICRO_IDX[String(Number(muni.code))].n, 0)})</button></div>` : ""}${muni && muni.code === CPH_MUNI && CPH && !microMode() ? `<div class="seg"><button class="sg ${MK.cphView !== "postnr" ? "on" : ""}" data-cphview="kvarter">Quarters (${CPH.areas.length})</button><button class="sg ${MK.cphView === "postnr" ? "on" : ""}" data-cphview="postnr">Postal codes</button></div>` : ""}${microMode() ? mindSelect() : indSelect() + yearSelect()}${D.portfolio ? `<button class="lk mini ${MK.own ? "primary" : ""}" data-mkown>● Own properties</button>` : ""}<button class="lk" data-fs title="Full screen (Esc to exit)">⤢ Full screen</button></div>
      ${microMode() ? "" : indQuick()}</div>
    ${microMode() ? microExplain() : indExplain(ind)}
    ${muni && !microMode() ? muniStrip(muni) : ""}
    <div class="mapwrap"><div id="lfmap"></div><div class="maplegend" id="maplegend"></div></div>
    ${srcNote(`<p class="cap">${muni ? "Click a polygon for its figures and a link to its page." : "Click a polygon for its figures; open a municipality with the search box above or from the popup. Table view lists everything side by side."} Colour classes: quintiles of the visible areas. Boundaries: DAGI, Klimadatastyrelsen (simplified); basemap OpenStreetMap.</p>`)}
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
  <div class="card accent">
    <div class="card-head tools-only"><div class="tools">${indSelect()}${yearSelect()}</div>${indQuick()}</div>
    ${indExplain(ind)}
    <div class="tfilters">
      <input id="tq" type="search" placeholder="Search municipality, postal code or name…" value="${esc(T.q)}">
      <div class="seg"><button class="sg ${T.level === "kommune" ? "on" : ""}" data-tlevel="kommune">Municipalities (${MUNI.length})</button><button class="sg ${T.level === "postnr" ? "on" : ""}" data-tlevel="postnr">Postal codes (${AREAS.length})</button>${CPH ? `<button class="sg ${T.level === "kvarter" ? "on" : ""}" data-tlevel="kvarter">Copenhagen quarters (${CPH.areas.length})</button>` : ""}</div>
      ${T.level !== "kvarter" ? `<select id="tregion" class="indsel"><option value="">All regions</option>${REGIONS.map(r => `<option value="${r}" ${T.region === r ? "selected" : ""}>${r}</option>`).join("")}</select>` : ""}
      <label class="hint">min. population <input id="tminpop" type="number" min="0" step="1000" value="${T.minPop}" style="width:90px"></label>
      <span class="hint" id="tcount">${tableRows().length} rows</span>
      <button class="lk mini" data-csv>⤓ Export CSV</button>
    </div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr>
      <th>${T.level === "kvarter" ? "Quarter" : T.level === "postnr" ? "Area" : "Municipality"}</th><th>${T.level === "postnr" ? "Postal code" : "Code"}</th><th>${T.level === "kvarter" ? "District" : T.level === "postnr" ? "Municipality" : "Region"}</th><th class="num">Population</th>
      <th class="num hi" data-best="${best(ind)}">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${isPct(ind) ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num" data-best="${best(i)}">${esc(i.label)}${lowerBetter(i.key) ? " ↓" : ""}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
      <tbody id="tbody">${tableBodyHtml()}</tbody></table></div>
    <p class="cap">Sorted by the selected indicator, best first (↓ = lower is better); click a column header to re-sort, a row to open the area's page, ↗ to chart it. ° = municipality value shown on a postal code or quarter.${isSafety(curInd()) ? "" : " Safety columns appear when a Safety indicator is selected."} Rows: ${T.level === "postnr" ? "postal codes (street-level codes in central Copenhagen merged by name)" : T.level === "kvarter" ? "Copenhagen quarters (kvarterer), source Københavns Kommune statbank" : "municipalities"}.</p>
    ${srcNote()}
  </div>`;
}
function exportCsv() {
  const cols = tableCols(true), rows = tableRows();
  const head = [T.level === "kvarter" ? "quarter" : T.level === "postnr" ? "area" : "municipality", T.level === "postnr" ? "postal_code" : "code", T.level === "kvarter" ? "district" : T.level === "postnr" ? "municipality" : "region", "population"].concat(cols.map(i => i.key));
  const lines = [head.join(";")].concat(rows.map(r => { const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    return [r.name, T.level === "postnr" ? r.nr : r.code, T.level === "kvarter" ? (r.bydel || "") : T.level === "postnr" ? (m.name || "") : (r.region || ""), r.pop ?? ""].concat(cols.map(i => V(r, i.key) ?? (T.level === "postnr" || (T.level === "kvarter" && !cphOwn(i.key)) ? (V(T.level === "kvarter" ? byCode[CPH_MUNI] : m, i.key) ?? "") : ""))).map(v => String(v).replace(/;/g, ",")).join(";"); }));
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = `am-dashboard-dk_${T.level}_${MK.year}_${(D.meta && D.meta.built) || "data"}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function downloadCsv(lines, name) {
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function exportAll() {
  /* one long-format CSV of everything the dashboard holds: every level, every indicator, every year, plus the macro series */
  const cl = v => String(v == null ? "" : v).replace(/;/g, ",").replace(/\r?\n/g, " ");
  const out = ["level;code;name;parent;region;population;year;indicator;label;unit;value;as_of"];
  const emit = (level, o, code, name, parent, region, inds, asofOf) => {
    inds.forEach(i => {
      const yrs = new Set(Object.keys((o.hist && o.hist[i.key]) || {})); if (o[i.key] != null) yrs.add(LATEST);
      [...yrs].sort().forEach(y => { const v = y === LATEST ? o[i.key] : o.hist[i.key][y]; if (v == null) return;
        out.push([level, code, name, parent, region, o.pop ?? "", y, i.key, i.label, i.unit || "", v, asofOf(i, y)].map(cl).join(";")); });
    });
  };
  const asofNat = lvl => (i, y) => { const src = (y !== LATEST && i.hist_asof && i.hist_asof[y]) || i.asof || {}; return src[lvl] || src.kommune || ""; };
  MUNI.forEach(m => emit("municipality", m, m.code, m.name, "Denmark", m.region || "", IND, asofNat("kommune")));
  AREAS.forEach(a => { const m = byCode[a.muni] || {}; emit("postal_code", a, a.nr, a.name, m.name || "", m.region || "", IND.filter(i => i.level === "postnr"), asofNat("postnr")); });
  if (CPH) CPH.areas.forEach(q => emit("copenhagen_quarter", q, q.code, q.name, q.bydel || "", "Hovedstaden", IND_CPH, (i, y) => (y !== LATEST && i.hist_asof && i.hist_asof[y]) || (i.asof && i.asof.kvarter) || ""));
  const mac = D.macro || {}; Object.entries(mac.series || {}).forEach(([k, ser]) => { const lt = (mac.latest || {})[k] || {};
    ser.forEach(pt => { if (pt.v != null) out.push(["macro", k, lt.label || k, "Denmark", "", "", pt.t, k, lt.label || k, lt.unit || "", pt.v, lt.src || ""].map(cl).join(";")); }); });
  downloadCsv(out, `macro-dashboard-dk_all_${(D.meta && D.meta.built) || "data"}.csv`);
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
function eYears(e, k) { return histYears(k, inherits(e, k) && V(e.o, k) == null ? MUNI : e.peers); }
function tileSpark(ys, own, med, i) {
  /* area (solid) against the median of its peers (dashed), last point marked, first/last year on the axis */
  const all = own.concat(med).filter(v => v != null); if (own.filter(v => v != null).length < 2) return "";
  const W = 220, H = 60, T0 = 6, B = 14, L0 = 4, R = 8;
  const lo = Math.min(...all), hi = Math.max(...all), sp = hi - lo || 1;
  const x = k => L0 + k / (ys.length - 1) * (W - L0 - R), y = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const path = arr => { let d = "", open = false; arr.forEach((v, k) => { if (v == null) { open = false; return; } d += (open ? "L" : "M") + x(k).toFixed(1) + "," + y(v).toFixed(1); open = true; }); return d; };
  const li = own.map((v, k) => v == null ? -1 : k).filter(k => k >= 0).pop();
  return `<svg class="tspark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${path(med)}" fill="none" stroke="#9A9D92" stroke-width="1.2" stroke-dasharray="3 3"/>
    <path d="${path(own)}" fill="none" stroke="#1C6B5C" stroke-width="2"/>
    ${li != null ? `<circle cx="${x(li).toFixed(1)}" cy="${y(own[li]).toFixed(1)}" r="2.8" fill="#1C6B5C"/>` : ""}
    <text class="ax" x="${L0}" y="${H - 3}">${ys[0]}</text><text class="ax" x="${W - R}" y="${H - 3}" text-anchor="end">${ys[ys.length - 1]}</text>
    ${own.map((v, k) => v == null ? "" : `<circle cx="${x(k).toFixed(1)}" cy="${y(v).toFixed(1)}" r="6" fill="transparent"><title>${ys[k]}: ${fmtOf(i)(v)}${med[k] != null ? " · median " + fmtOf(i)(med[k]) : ""}</title></circle>`).join("")}</svg>`;
}
/* everything a tile, headline cell or popup needs about one indicator for one area */
function tileStats(e, i) {
  const cur = eVal(e, i.key); if (cur.v == null) return null;
  const ys = eYears(e, i.key), y0 = ys[0];
  const own = ys.map(y => eVal(e, i.key, y).v), med = ys.map(y => median(e.peers.map(p => V(p, i.key, y))));
  const dlt = (a, b) => a == null || b == null ? null : isPct(i) ? b - a : (a ? (b / a - 1) * 100 : null);
  const unit = isPct(i) ? " pp" : " %";
  const li = own.map((v, k) => v == null ? -1 : k).filter(k => k >= 0).pop(); const idx = MK.year === LATEST ? li : ys.indexOf(MK.year);
  const yoy = idx > 0 ? dlt(own[idx - 1], own[idx]) : null;
  const since = y0 && y0 !== MK.year ? dlt(own[0], cur.v) : null;
  const vsMed = dlt(median(e.peers.map(p => V(p, i.key))), cur.v);
  const rk = cur.own ? rankOf(e.o, i.key, e.peers) : null;
  return { cur, ys, y0, own, med, yoy, since, vsMed, rk, unit };
}
function tileHtml(e, i, on) {
  const s = tileStats(e, i); if (!s) return "";
  return `<div class="tile ${on ? "on" : ""}" data-arind="${esc(i.key)}" title="${esc(i.desc || i.label)} — click to focus the chart and map">
    <button class="tch" data-go="${chartLink(i.key, e.type, e.code)}" title="Open in Charts">↗</button>
    <span class="tl">${esc(i.label)}${s.cur.own ? (e.type === "kvarter" ? bydelMark(i) : "") : " °"}</span>
    <div class="tv"><b>${fmtOf(i)(s.cur.v)}</b>${s.yoy != null ? `<i class="${cls(s.yoy, i.key)}">${sign(s.yoy, x => nf(x, 1))}${s.unit} y/y</i>` : ""}</div>
    ${tileSpark(s.ys, s.own, s.med, i)}
    <div class="tm">${s.rk ? `<span>#${s.rk.r} of ${s.rk.n}</span>` : `<span class="dim">municipality value</span>`}${s.vsMed != null ? `<span><i class="${cls(s.vsMed, i.key)}">${sign(s.vsMed, x => nf(x, 1))}${s.unit}</i> vs median</span>` : ""}</div>
  </div>`;
}
/* headline row under the area title: the five figures that answer "what kind of area is this" */
function headlineHtml(e) {
  const inds = HL_KEYS.map(k => e.inds.find(i => i.key === k)).filter(i => i && eVal(e, i.key).v != null).slice(0, 5);
  if (!inds.length) return "";
  return `<div class="hl">${inds.map(i => { const s = tileStats(e, i); return `<button class="hlc ${MK.ind === i.key ? "on" : ""}" data-arind="${esc(i.key)}" title="${esc(i.desc || i.label)} — click to focus the chart and map">
    <span>${esc(i.short || i.label)}${s.cur.own ? (e.type === "kvarter" ? bydelMark(i) : "") : " °"}</span><b>${fmtOf(i)(s.cur.v)}</b>
    <em>${s.yoy != null ? `<i class="${cls(s.yoy, i.key)}">${sign(s.yoy, x => nf(x, 1))}${s.unit}</i> y/y` : ""}${s.rk ? `${s.yoy != null ? " · " : ""}#${s.rk.r} of ${s.rk.n}` : ""}</em></button>`; }).join("")}</div>`;
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
function areaChart(e, ind) {
  const ys = eYears(e, ind.key);
  const series = [{ name: e.name, color: "#1C6B5C", w: 2.6, pts: ys.map(y => ({ y, v: eVal(e, ind.key, y).v })) }];
  if (muniCmp(e, ind.key) && V(e.o, ind.key) != null) series.push({ name: e.muni.name, color: "#B07A1E", pts: ys.map(y => ({ y, v: V(e.muni, ind.key, y) })) });
  const medLabel = e.type === "kommune" ? "Denmark, median of municipalities" : e.type === "kvarter" ? "Copenhagen, median of quarters" : "Denmark, median of postal codes";
  series.push({ name: medLabel, color: "#5C5F52", dash: true, pts: ys.map(y => ({ y, v: median(e.peers.map(p => V(p, ind.key, y))) })) });
  return multiLine(series, ind, ys);
}
function areaCompareTable(e) {
  const ind = curInd(), medLabel = e.type === "kommune" ? "DK median" : e.type === "kvarter" ? "CPH median" : "DK median (postal codes)";
  return `<div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Indicator</th><th class="num">${esc(e.type === "kommune" ? e.name : e.type === "kvarter" ? "Quarter" : "Postal code")}</th>${e.muni ? `<th class="num">${esc(e.muni.name)}</th>` : ""}<th class="num">${medLabel}</th><th class="num">Rank</th><th class="num">Δ since first year</th><th>As of</th></tr></thead>
    <tbody>${e.inds.map(i => { const cur = eVal(e, i.key); if (cur.v == null) return "";
      const ys = eYears(e, i.key), y0 = ys[0]; const first = y0 && y0 !== MK.year ? eVal(e, i.key, y0).v : null;
      const d = first == null ? null : isPct(i) ? cur.v - first : (first ? (cur.v / first - 1) * 100 : null);
      const rk = cur.own ? rankOf(e.o, i.key, e.peers) : null; const med = median(e.peers.map(p => V(p, i.key)));
      return `<tr class="clickrow ${i.key === ind.key ? "hi" : ""}" data-arind="${esc(i.key)}"><th><span class="thn">${esc(i.label)} <span class="dim">${esc(i.unit || "")}</span></span><button class="tch" data-go="${chartLink(i.key, e.type, e.code)}" title="Open in Charts">↗</button></th>
        ${fmtCell(i, cur.v, !cur.own, e.type === "kvarter" ? bydelMark(i) : "")}${e.muni ? (muniCmp(e, i.key) ? fmtCell(i, V(e.muni, i.key), false) : `<td class="num dim" title="different definition at municipality level">n/c</td>`) : ""}${fmtCell(i, med, false)}
        <td class="num" data-v="${rk ? rk.r : ""}">${rk ? `#${rk.r} / ${rk.n}` : "–"}</td>
        <td class="num ${goodBad(d, i.key)}" data-v="${d ?? ""}">${d != null ? sign(d, x => nf(x, 1)) + (isPct(i) ? " pp" : " %") + ` <span class="dim">(${y0})</span>` : "–"}</td>
        <td class="dim">${asofText(i)}</td></tr>`; }).join("")}</tbody></table></div>`;
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
function vArea() {
  const e = areaEntity();
  if (!e) return `<div class="back"><button data-go="map">‹ Macro map</button></div><div class="card"><p class="empty">Unknown area.</p></div>`;
  const ind = curInd();
  setTimeout(arMapInit, 0);
  const groups = GROUP_ORDER.filter(gn => e.inds.some(i => (i.group || "Other") === gn && eVal(e, i.key).v != null));
  const grp = groups.includes(AR.group) ? AR.group : groups[0];
  const tiles = e.inds.filter(i => (i.group || "Other") === grp && eVal(e, i.key).v != null);
  const mapHash = e.type === "kommune" ? `map/${e.code}` : e.type === "kvarter" ? `map/${CPH_MUNI}` : `map/${e.o.muni}/postnr`;
  const microCode = e.type === "kommune" ? e.code : e.type === "kvarter" ? CPH_MUNI : e.o.muni;
  /* lower panel: the full indicator list, the BBR housing stock and the sub-areas as tabs of one card */
  const tabs = [["ind", "All indicators"]].concat(e.o.bbr && e.o.bbr.dist ? [["bbr", "Housing stock (BBR)"]] : []).concat(e.subs ? [["sub", e.subs.kvarter ? "Quarters & postal codes" : "Postal codes"]] : []);
  const tab = tabs.some(t => t[0] === AR.tab) ? AR.tab : "ind";
  const hint = `y/y = change from the previous year · "vs median" = against the median of ${e.peerLabel} (pp for shares, % otherwise) · #rank among ${e.peerLabel}, #1 = highest value (lowest where ↓ lower is better) · ° = municipality value where no ${e.type === "postnr" ? "postal-code" : "finer"} statistic exists${e.type === "kvarter" ? " · ^ = figure published for the whole bydel" : ""}${e.type === "kvarter" ? " · n/c = not comparable (different definition at municipality level)" : ""}. Solid line = ${e.name}, dashed = median of ${e.peerLabel}. Click a tile to focus the chart and map, ↗ to open it in Charts.`;
  return `
  <div class="card accent arhead">
    <div class="arid">
      <h2>${esc(e.name)}</h2>
      <div class="artags"><span class="tag">${esc(e.typeLabel)}</span><span class="tag">code ${esc(e.code)}</span>${e.o.pop != null ? `<span class="tag">${nf(e.o.pop, 0)} inhabitants</span>` : ""}${e.type === "kommune" ? `<span class="tag">${e.ctx.length} postal codes</span>` : ""}${e.type === "postnr" && e.o.codes && e.o.codes.length > 1 ? `<span class="tag">merged codes ${esc(e.o.codes.join(", "))}</span>` : ""}</div>
    </div>
    <div class="tools">${yearSelect()}<button class="lk" data-go="${withQ(mapHash)}">Show on map</button><button class="lk" data-go="${chartLink(MK.ind, e.type, e.code)}">↗ Chart</button>${microAvail(microCode) ? `<button class="lk primary" data-go="map/${microCode}?ind=${MK.ind}&micro=1&mind=${MK.mind}">Buildings ›</button>` : ""}</div>
    ${headlineHtml(e)}
  </div>
  <div class="card">
    <div class="card-head"><h3>Key figures${MK.year !== LATEST ? " · " + MK.year : ""} <span class="hq" title="${esc(hint)}">ⓘ</span></h3>
      <div class="seg">${groups.map(g => `<button class="sg ${g === grp ? "on" : ""}" data-argroup="${esc(g)}">${esc(g)}</button>`).join("")}</div></div>
    <div class="hero wrap">${tiles.map(i => tileHtml(e, i, i.key === ind.key)).join("") || `<div><span>no data</span></div>`}</div>
  </div>
  ${e.type === "kvarter" && e.o.kk ? kkCard(e) : ""}
  <div class="grid-2">
    <div class="card">
      <div class="card-head"><h3>Trend — ${esc(ind.label)}</h3><span class="hint">${esc(ind.unit || "")} · same sub-period each year</span></div>
      ${areaChart(e, ind)}
      <p class="cap">${esc(ind.desc || "")} <span class="dim">${esc(ind.source || "")}</span>${ind.warn ? `<br>⚠ ${esc(ind.warn)}` : ""}</p>
    </div>
    <div class="card">
      <div class="card-head"><h3>${esc(ind.short || ind.label)} — ${(() => { const mm = arMapMode(e, ind); return e.type === "kommune" ? (mm.kommuneLevel ? esc(e.name) + " among municipalities" : esc(e.name) + " by " + (mm.useQ ? "quarter" : "postal code")) : "neighbours"; })()}</h3><span class="hint">${(() => { const mm = arMapMode(e, ind); return mm.kommuneLevel ? "municipality-level indicator · click a neighbour to open it" : e.type === "kommune" ? "click an area to open it" : "click a neighbour to open it"; })()}</span></div>
      <div class="mapwrap"><div id="armap"></div><div class="maplegend small" id="arlegend"></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-head"><div class="seg tabs">${tabs.map(([k, l]) => `<button class="sg ${k === tab ? "on" : ""}" data-artab="${k}">${esc(l)}</button>`).join("")}</div><span class="hint">${tab === "ind" ? "click a row to focus the chart, ↗ to chart it" : tab === "bbr" ? "current dwellings from the building register" : "click a row for its page"}</span></div>
    ${tab === "ind" ? areaCompareTable(e) : tab === "bbr" ? bbrCard(e) : areaSubTable(e)}
  </div>
  ${srcNote()}`;
}
/* Copenhagen quarters: the figures the city's safety survey publishes for the whole bydel */
function kkCard(e) {
  const k = e.o.kk, tile = (l, v, sub) => v == null ? "" : `<div><span>${esc(l)}</span><b>${esc(v)}</b><em>${esc(sub)}</em></div>`;
  const i = e.inds.find(x => x.key === "crime_1000") || {};
  return `<div class="card">
    <div class="card-head"><h3>Safety survey — ${esc(k.bydel)} <span class="hq" title="Published per bydel; every quarter of ${esc(k.bydel)} shows the same figure.">ⓘ</span></h3><span class="hint">Københavns Kommune ${esc(k.year)} · Københavns Politi ${esc(k.crime_year)} · p. ${esc(k.page || "–")}</span></div>
    <div class="hero wrap">
      ${tile("Reported offences", k.reports_n != null ? nf(k.reports_n, 0) : null, `${k.bydel}, ${k.crime_year}`)}
      ${tile("Violence", k.violence_1000inh != null ? nf(k.violence_1000inh, 0) : null, `per 1,000 inh., ${k.crime_year}`)}
      ${tile("Burglary", k.burglary_1000inh != null ? nf(k.burglary_1000inh, 0) : null, `per 1,000 inh., ${k.crime_year}`)}
    </div>
    <p class="cap">^ = figure published for the whole bydel, not the quarter. Burglary here is per 1,000 <b>inhabitants</b> as published — not the national indicator's per 1,000 dwellings. ${esc(k.note || "")} <span class="dim">${esc(i.source || "")}</span></p>
  </div>`;
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
function arMapInit() {
  const el = document.getElementById("armap"); if (!el || typeof L === "undefined") return;
  const e = areaEntity(); if (!e) return;
  if (LF.amap) { try { LF.amap.remove(); } catch (x) {} LF.amap = null; }
  const map = L.map(el, { center: [56, 10.5], zoom: 7, scrollWheelZoom: true, zoomSnap: 0.5, zoomDelta: 1, wheelPxPerZoomLevel: 30, wheelDebounceTime: 20, attributionControl: false });
  LF.amap = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap" }).addTo(map);
  const ind = curInd(); const { useQ, sind, kommuneLevel } = arMapMode(e, ind);
  const ctx = e.type === "kommune" ? (useQ ? CPH.areas : kommuneLevel ? AREAS : e.ctx) : e.ctx;
  const vk = a => { if (!sind) return null; if (kommuneLevel) return V(byCode[a.muni], sind.key); return V(a, sind.key) ?? (useQ ? null : V(byCode[a.muni], sind.key)); };
  const sc = kommuneLevel ? scaleOf(MUNI, m => V(m, sind.key)) : scaleOf(ctx.filter(a => sind && V(a, sind.key) != null), vk);
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
    p.addTo(map);
  });
  if (sind) setLegend("arlegend", sc, sind, ind.key, kommuneLevel ? "municipalities" : useQ ? "quarters" : "postal codes");
  const b = boundsOf(own); if (b) map.fitBounds(b, { padding: kommuneLevel ? [90, 90] : e.type === "kommune" ? [10, 10] : [70, 70], maxZoom: kommuneLevel ? 9 : 13 });
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
    ${sel ? `<div class="lfbig"><span>${esc(ind.label)}${sel.own ? (isQ ? bydelMark(ind) : "") : " °"}</span><b>${fmtOf(ind)(sel.v)}</b><em>${rk ? `#${rk.r} of ${rk.n} ${sel.own ? (isQ ? "quarters" : "postal codes") : "municipalities"}` : ""}</em></div>` : `<div class="lfbig dim"><span>${esc(ind.label)}</span><b>–</b></div>`}
    ${ind.note_short ? `<p class="cap">${esc(ind.note_short)}</p>` : ""}
    ${keys.length ? `<div class="lfkey">${keys.map(({ i, x }) => `<div><span>${esc(i.short || i.label)}${x.own ? (isQ ? bydelMark(i) : "") : " °"}</span><b>${fmtOf(i)(x.v)}</b></div>`).join("")}</div>` : ""}
    <span class="lfact"><button class="lk mini primary" data-go="${withQ(pageOf(a))}">Open page ›</button>${muni && !MK.muni ? `<button class="lk mini" data-go="map/${muni.code}?ind=${MK.ind}">Zoom to ${esc(muni.name)}</button>` : ""}${muni && microAvail(muni.code) ? `<button class="lk mini" data-go="map/${muni.code}?ind=${MK.ind}&micro=1&mind=${MK.mind}">Buildings ›</button>` : ""}<button class="lk mini" data-go="${chartLink(ind.key, type, code)}">↗ Chart</button></span>
    <details class="lfmore"><summary>All ${n} values</summary>
    ${native ? `<span class="lfsec">${isQ ? "Quarter" : "Postal code"}</span><div class="lfrows">${native}</div>` : ""}
    ${inherited ? `<span class="lfsec">Municipality °</span><div class="lfrows">${inherited}</div>` : ""}
    ${safety ? `<span class="lfsec">Safety${muni ? " · municipality °" : ""}</span><div class="lfrows">${safety}</div>` : ""}
    ${isQ && a.kk ? `<span class="lfsec">KK survey · ${esc(a.kk.bydel)} ^</span><div class="lfrows">${kkRows(a.kk)}</div>` : ""}</details></div>`;
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
  return d.b.filter(r => r[2] >= MF.minDw && (!MF.yFrom || (r[6] != null && r[6] >= Number(MF.yFrom))) && (!MF.yTo || (r[6] != null && r[6] <= Number(MF.yTo)))
    && (!MF.type || String(r[8]) === MF.type) && (!MF.rentMin || (r[3] != null && r[3] >= MF.rentMin)));
}
function loadMicro(code) {
  const k = String(Number(code)); const e = MICRO_IDX[k]; if (!e || MICRO[k] || MICRO["_loading_" + k]) return;
  MICRO["_loading_" + k] = true;
  fetch(e.file).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { MICRO[k] = d; delete MICRO["_loading_" + k]; if (microMode() && LF.map) lfLayers(); })
    .catch(() => { MICRO["_error_" + k] = true; delete MICRO["_loading_" + k]; const el = document.getElementById("mcount"); if (el) el.textContent = "buildings could not be loaded — open the dashboard via make serve or the GitHub Pages link (not as a file)"; });
}
function microPopup(r) {
  const m = byCode[MK.muni]; const rooms = r.slice(9, 13); const rt = rooms.reduce((a, b) => a + b, 0);
  const row = (l, v) => `<span class="lfrow"><span>${l}</span><b>${v}</b></span>`;
  const d = MICRO[String(Number(MK.muni))]; const same = r[16] && d ? d.b.filter(x => x[16] === r[16]).length - 1 : 0;
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
function microRadius(dw) { const z = LF.map ? LF.map.getZoom() : 12; const k = z < 12 ? .7 : z < 13.5 ? 1.0 : z < 15 ? 1.5 : 2.2; return Math.max(2, Math.min(16, k * Math.sqrt(dw) + 1)); }
function lfMicroLayers() {
  const code = MK.muni; const d = MICRO[String(Number(code))];
  if (LF.areaG) LF.map.removeLayer(LF.areaG);
  if (LF.labG) LF.map.removeLayer(LF.labG);
  if (LF.microG) { LF.map.removeLayer(LF.microG); LF.microG = null; }
  LF.level = "micro-b" + code; LF.ctx = null;
  /* area outlines only, so the dots read against the basemap */
  LF.areaG = L.layerGroup(muniAreas(code).map(a => L.polygon(a.rings, { color: "#141C18", weight: 1, fill: false, opacity: .35, interactive: false }))).addTo(LF.map);
  const cnt = document.getElementById("mcount");
  if (!d) { loadMicro(code); if (cnt && !MICRO["_error_" + String(Number(code))]) cnt.textContent = "loading buildings…"; return; }
  const ind = curMind(), rows = microRows(code), c = ind.col;
  /* same quintile classes as the area maps, computed on the buildings that pass the filters */
  const sc = scaleOf(rows, r => r[c], ind.breaks); const t = sc.t;
  if (!LF.canvas) LF.canvas = L.canvas({ padding: .3 });
  const marks = rows.map(r => { const tt = t(r[c]);
    const m = L.circleMarker([r[0], r[1]], { renderer: LF.canvas, radius: microRadius(r[2]), color: "#141C18", weight: .6, opacity: .7, fillColor: tt == null ? "#C4CBC4" : mkShade(tt, "micro:" + ind.key), fillOpacity: .85 });
    m._dw = r[2]; m._row = r; m.bindPopup(() => microPopup(r), { maxWidth: 440, autoPanPadding: [24, 24] }); return m; });
  LF.microG = L.layerGroup(marks).addTo(LF.map); LF.microMarks = marks;
  setLegend("maplegend", sc, ind, "micro:" + ind.key, "buildings with ≥ 2 dwellings · dot size = dwellings");
  if (cnt) cnt.textContent = `${nf(rows.length, 0)} of ${nf(d.meta.n, 0)} buildings · ${nf(rows.reduce((s_, r) => s_ + r[2], 0), 0)} dwellings`;
}
function lfLayers() {
  if (LF.map && microMode()) { lfMicroLayers(); return; }
  if (LF.microG && LF.map) { LF.map.removeLayer(LF.microG); LF.microG = null; }
  if (!LF.map) return;
  const zoom = LF.map.getZoom();
  const ind = curInd();
  /* a drilled-in municipality always shows its sub-areas, whatever the zoom (small screens fit it below zoom 10) */
  const fine = !!MK.muni || zoom >= MICRO_ZOOM;
  const micro = fine && (cphMode() ? cphOwn(ind.key) : ind.level === "postnr");
  LF.level = (fine ? "micro" : zoom < 8 ? "national" : "macro") + (cphMode() ? "-cph" : "") + (MK.muni || "");
  if (LF.areaG) LF.map.removeLayer(LF.areaG);
  if (LF.labG) LF.map.removeLayer(LF.labG);
  const areas = MK.muni ? muniAreas(MK.muni) : AREAS;
  const munis = MK.muni ? [byCode[MK.muni]].filter(Boolean) : MUNI;
  const vk = o => V(o, ind.key);
  const sc = scaleOf(micro ? areas.filter(a => vk(a) != null) : munis, vk);
  const polys = [];
  areas.forEach(a => {
    const m = byCode[a.muni];
    const src = micro && vk(a) != null ? a : m;
    const t = src ? sc.t(vk(src)) : null;
    const w = fine ? 1.4 : 0.8;
    const p = L.polygon(a.rings, { color: "#FFFFFF", weight: w, fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .72, smoothFactor: 1 });
    p.bindPopup(() => lfPopup(a, m), { maxWidth: 560, maxHeight: 560, autoPanPadding: [24, 24] });
    p.on("mouseover", () => p.setStyle({ weight: 2.2, color: "#141C18" })); p.on("mouseout", () => p.setStyle({ weight: w, color: "#FFFFFF" }));
    polys.push(p);
  });
  LF.areaG = L.layerGroup(polys).addTo(LF.map);
  LF.ctx = { areas, munis, sc, micro, ind, vk };
  lfLabels();
  setLegend("maplegend", sc, ind, ind.key, micro ? (cphMode() ? "quarters" + (bydelLevel(ind) ? " · ^ one figure per bydel" : "") : "postal codes") : (ind.level === "postnr" && !MK.muni ? "municipalities · zoom in for postal codes" : "municipalities" + (fine ? ` · ° ${cphMode() ? "quarters" : "postal codes"} take the municipality value` : "")));
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
}
function lfInit() {
  const el = document.getElementById("lfmap");
  if (!el || typeof L === "undefined") return;
  if (LF.map) { try { LF.map.remove(); } catch (e) {} LF.map = null; }
  const map = L.map(el, { center: LF.center, zoom: LF.zoom, scrollWheelZoom: true, zoomSnap: 0.5, zoomDelta: 1, wheelPxPerZoomLevel: 30, wheelDebounceTime: 20 });
  LF.map = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap",
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Boundaries: DAGI, Klimadatastyrelsen' }).addTo(map);
  map.on("moveend", () => { const c = map.getCenter(); LF.center = [c.lat, c.lng]; LF.zoom = map.getZoom(); });
  /* Leaflet stops click propagation inside popups, so page links in popups are wired here */
  map.on("popupopen", ev => { const el = ev.popup.getElement(); if (!el) return;
    el.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
    /* re-fit the popup when "all values" opens — popup.update() would rebuild the content and close the fold again */
    el.querySelectorAll("details").forEach(d => d.addEventListener("toggle", () => { const pp = ev.popup; if (pp._updateLayout) { pp._updateLayout(); pp._updatePosition(); pp._adjustPan(); } })); });
  map.on("zoomend", () => {
    /* rebuild polygons only when the display level changes — rebuilding on every pan would kill open popups */
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
  if (t === "kommune" && byCode[c]) return { id, type: t, o: byCode[c], name: byCode[c].name, inds: IND, peers: MUNI, peerLabel: "municipalities" };
  if (t === "postnr" && byNr[c]) return { id, type: t, o: byNr[c], name: `${c} ${byNr[c].name}`, inds: IND, peers: AREAS, peerLabel: "postal codes", muni: byCode[byNr[c].muni] };
  if (t === "kvarter" && byQ[c]) return { id, type: t, o: byQ[c], name: byQ[c].name + " (CPH)", inds: IND_Q, peers: CPH.areas, peerLabel: "quarters", muni: byCode[CPH_MUNI] };
  return null;
}
function chartAdd(id, text) {
  if (!id && text) { const q = text.trim(); const o = AREA_OPTS.find(x => x.t === q) || AREA_OPTS.find(x => x.k.some(k => k === q.toLowerCase())) || AREA_OPTS.find(x => x.k.some(k => k.startsWith(q.toLowerCase())));
    if (!o) return; id = o.h.startsWith("map/") ? "kommune:" + o.h.slice(4) : o.h.replace("area/", "").replace("/", ":"); }
  if (!id || CH.areas.includes(id) || CH.areas.length >= 8) return;
  CH.areas.push(id); syncHash(); renderKeep();
  const q = document.getElementById("chq"); if (q) { q.value = ""; q.focus(); }
}
function chartInd() { return IND.concat(IND_CPH.filter(i => !IND.some(x => x.key === i.key))).find(i => i.key === CH.ind) || IND[0]; }
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
  if (CH.mode !== "auto") return CH.mode;
  return chartYears().length >= 2 ? "line" : "bar";
}
function chartAutoTitle() {
  if (chartMode() === "dist") return `${(DIST_DEFS[CH.dist] || DIST_DEFS.size)[0]} — share of dwellings (BBR)`;
  const inds = chartInds(), i = inds[0];
  const lab = inds.length > 1 ? inds.map(x => x.short || x.label).join(", ") : i.label;
  const unit = optLabel(i).slice(i.label.length);   /* " · rolling 4Q", " · % / yr" — the unit parts the label does not already say */
  return `${lab}${unit}${chartMode() === "bar" ? " — latest" : chartQ() ? " — quarterly" : ""}`;
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
      series.push({ name: multi ? `${e.name} · ${i.short || i.label}` : e.name, color: CH_COLORS[k++ % CH_COLORS.length], pts: ys.map(y => ({ y, v: own ? val(y) : null })),
                    inherited: own && inh && V(e.o, i.key) == null && V(e.muni, i.key) != null });
    });
    if (CH.nat && NAT) series.push({ name: multi ? `Denmark · ${i.short || i.label}` : "Denmark", color: ents.length ? CH_COLORS[first % CH_COLORS.length] : "#16170F", dash: true, pts: ys.map(y => ({ y, v: chVal(NAT, i, y) })) });
  });
  if (CH.median) { const pool = ents.length && ents.every(e => e.type === "kvarter") && cphOwn(ind.key) ? CPH.areas : MUNI;
    series.push({ name: pool === MUNI ? "Denmark — median of municipalities" : "Copenhagen — median of quarters", color: "#8A8C81", dash: true, pts: ys.map(y => ({ y, v: median(pool.map(p => chVal(p, ind, y))) })) }); }
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
  if (!rows.length) return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/><text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${CH_FONT}" font-size="18" fill="#8A8C81">Add areas with the search box — nothing to plot yet</text></svg>`;
  const pool = ents.length && ents.every(e => e.type === "kvarter") ? CPH.areas : MUNI; const med = CH.median ? median(pool.map(p => V(p, ind.key))) : null;
  const vals = rows.map(r => r.v).concat(med != null ? [med] : []); const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1;
  const labW = 260; const x0 = L0 + labW, x1 = W - R; const x = v => x0 + (v - lo) / (hi - lo || 1) * (x1 - x0);
  const rowH = Math.min(52, (H - T0 - B) / rows.length), bh = rowH * .62;
  const bars = rows.map((r, i) => { const y = T0 + i * rowH + (rowH - bh) / 2; return `<text x="${x0 - 12}" y="${(y + bh / 2 + 5).toFixed(1)}" text-anchor="end" font-family="${CH_FONT}" font-size="15" fill="#16170F">${esc(r.name)}${r.inh ? " °" : ""}</text>
    <rect x="${x(Math.min(0, r.v)).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.abs(x(r.v) - x(0)).toFixed(1)}" height="${bh.toFixed(1)}" fill="${r.color}" rx="3"/>
    <text x="${(x(Math.max(0, r.v)) + 8).toFixed(1)}" y="${(y + bh / 2 + 5).toFixed(1)}" font-family="${CH_MONO}" font-size="14" fill="#16170F">${esc(fmtOf(ind)(r.v))}</text>`; }).join("");
  const medLine = med != null ? `<line x1="${x(med).toFixed(1)}" x2="${x(med).toFixed(1)}" y1="${T0 - 8}" y2="${T0 + rows.length * rowH}" stroke="#5C5F52" stroke-width="2" stroke-dasharray="7 5"/><text x="${(x(med) + 6).toFixed(1)}" y="${T0 - 12}" font-family="${CH_MONO}" font-size="12" fill="#5C5F52">${pool === MUNI ? "DK median" : "CPH median"} ${esc(fmtOf(ind)(med))}</text>` : "";
  const asof = asofText(ind);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, `${ind.desc || ""}${asof ? " · as of " + asof : ""}`)}
    <line x1="${x(0).toFixed(1)}" x2="${x(0).toFixed(1)}" y1="${T0}" y2="${T0 + rows.length * rowH}" stroke="#E6E6E0"/>${bars}${medLine}${chFoot(L0, H, ind, rows.some(r => r.inh) ? " · ° = municipality value" : "")}</svg>`;
}
/* distributions from the BBR register: one donut per area */
const DIST_DEFS = { size: ["Dwelling size", ["< 50 m²", "50–79 m²", "80–119 m²", "120+ m²"]], rooms: ["Rooms", ["1 room", "2 rooms", "3 rooms", "4+ rooms"]],
                    built: ["Year built", ["before 1950", "1950–79", "1980–2009", "2010+"]], type: ["Building type", ["houses", "row houses", "multi-dwelling", "other"]] };
const DIST_COLORS = ["#C9DCD6", "#7FB0A4", "#3E8A78", "#1C6B5C"];
function chartSvgDist(withTitle) {
  const ents = CH.areas.map(chEntity).filter(Boolean).filter(e => e.o.bbr && e.o.bbr.dist); const [dl, labels] = DIST_DEFS[CH.dist] || DIST_DEFS.size;
  const W = 1200, H = 640, L0 = 96, T0 = withTitle ? 96 : 30;
  const ind = { label: `${dl} — share of dwellings (BBR)`, unit: "", desc: "Distribution of current dwellings from the BBR register, placed by building coordinate.", source: "BBR via Datafordeler (Klimadatastyrelsen)" };
  if (!ents.length) return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, "")}<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${CH_FONT}" font-size="18" fill="#8A8C81">Add areas with BBR data (municipalities, postal codes or quarters) to draw distributions</text></svg>`;
  const perRow = Math.min(4, ents.length), cw = (W - L0 * 2) / perRow, rows = Math.ceil(ents.length / perRow), avail = H - T0 - 110, rh = avail / rows, r0 = Math.min(cw, rh) * .34, r1 = r0 * .55;
  const arc = (cx, cy, a0, a1, R0, R1) => { const p = (a, r) => [cx + r * Math.cos(a), cy + r * Math.sin(a)]; const [x0, y0] = p(a0, R0), [x1, y1] = p(a1, R0), [x2, y2] = p(a1, R1), [x3, y3] = p(a0, R1); const big = a1 - a0 > Math.PI ? 1 : 0;
    return `M${x0.toFixed(1)},${y0.toFixed(1)}A${R0},${R0} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}A${R1},${R1} 0 ${big} 0 ${x3.toFixed(1)},${y3.toFixed(1)}Z`; };
  const donuts = ents.map((e, k) => { const cx = L0 + (k % perRow) * cw + cw / 2, cy = T0 + Math.floor(k / perRow) * rh + rh / 2 - 10; const d = e.o.bbr.dist[CH.dist] || [0, 0, 0, 0]; const tot = d.reduce((a, b) => a + b, 0) || 1; let a = -Math.PI / 2;
    const slices = d.map((v, i) => { const a1 = a + v / tot * 2 * Math.PI - 1e-6; const path = `<path d="${arc(cx, cy, a, a1, r0, r1)}" fill="${DIST_COLORS[i]}"><title>${esc(labels[i])}: ${nf(v / tot * 100, 0)} % (${nf(v, 0)})</title></path>`; const mid = (a + a1) / 2; const lab = v / tot >= .07 ? `<text x="${(cx + (r0 + r1) / 2 * Math.cos(mid)).toFixed(1)}" y="${(cy + (r0 + r1) / 2 * Math.sin(mid) + 5).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="13" font-weight="600" fill="${i >= 2 ? "#FFFFFF" : "#16170F"}">${nf(v / tot * 100, 0)} %</text>` : ""; a = a1 + 1e-6; return path + lab; }).join("");
    return slices + `<text x="${cx}" y="${(cy + r0 + 26).toFixed(1)}" text-anchor="middle" font-family="${CH_FONT}" font-size="15" font-weight="600" fill="#16170F">${esc(e.name)}</text><text x="${cx}" y="${(cy + r0 + 46).toFixed(1)}" text-anchor="middle" font-family="${CH_MONO}" font-size="12" fill="#8A8C81">${nf(e.o.bbr.n, 0)} dwellings</text>`; }).join("");
  const legY = H - 52; const legend = labels.map((l, i) => `<rect x="${L0 + i * 220}" y="${legY - 12}" width="14" height="14" fill="${DIST_COLORS[i]}" rx="2"/><text x="${L0 + i * 220 + 22}" y="${legY}" font-family="${CH_FONT}" font-size="14" fill="#16170F">${esc(l)}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${chTitleBlock(withTitle, ind, L0, ind.desc)}${donuts}${legend}${chFoot(L0, H, ind)}</svg>`;
}
/* "2026K2" → "2026 Q2" for display; years pass through */
const fmtP = p => String(p).replace(/K(\d)$/, " Q$1");
function chartSvgLine(withTitle) {
  const { ind, inds, ys, series } = chartSeries(); const q = isQ(ys[0] || "");
  const W = 1200, H = 640, L0 = 96, R = 30, T0 = withTitle ? 84 : 24, B = 150;
  const all = series.flatMap(s_ => s_.pts.map(p => p.v)).filter(v => v != null);
  const F = "Inter, 'Helvetica Neue', Arial, sans-serif", M = "'IBM Plex Mono', Menlo, monospace";
  if (!all.length) return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"><rect width="${W}" height="${H}" fill="#FFFFFF"/><text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-family="${F}" font-size="18" fill="#8A8C81">Add areas with the search box — nothing to plot yet</text></svg>`;
  /* padding never pushes an all-positive scale below zero (counts and rates) */
  const lo0 = Math.min(...all), hi0 = Math.max(...all), pad = (hi0 - lo0 || Math.abs(hi0) || 1) * .08; const lo = lo0 >= 0 ? Math.max(0, lo0 - pad) : lo0 - pad, hi = hi0 + pad, sp = hi - lo;
  const x = i => L0 + i / (ys.length - 1) * (W - L0 - R), y = v => T0 + (1 - (v - lo) / sp) * (H - T0 - B);
  const ticks = [0, .25, .5, .75, 1].map(t => lo + t * sp);
  const paths = series.map(s_ => { let d = "", open = false; s_.pts.forEach((p, i) => { if (p.v == null) { open = false; return; } d += (open ? "L" : "M") + x(i).toFixed(1) + "," + y(p.v).toFixed(1); open = true; });
    return `<path d="${d}" fill="none" stroke="${s_.color}" stroke-width="${s_.dash ? 2 : 3}" ${s_.dash ? 'stroke-dasharray="7 5"' : ""} stroke-linejoin="round"/>` +
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
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" id="chsvg"><rect width="${W}" height="${H}" fill="#FFFFFF"/>${title}
    ${ticks.map(t => `<line x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="#EFEFEA"/><text x="${L0 - 10}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end" font-family="${M}" font-size="12" fill="#8A8C81">${esc(fmtTight(ind)(t))}</text>`).join("")}
    ${ys.map((yy, i) => q && !yy.endsWith("K1") ? "" : `<text x="${x(i).toFixed(1)}" y="${H - B + 22}" text-anchor="middle" font-family="${M}" font-size="12" fill="#8A8C81">${q ? yy.slice(0, 4) : yy}</text>`).join("")}
    ${brks}${paths}${legend}${foot}</svg>`;
}
function vCharts() {
  const ind = chartInd(), ys = chartYears(); const ents = CH.areas.map(chEntity).filter(Boolean);
  const L = IND.concat(IND_CPH.filter(i => !IND.some(x => x.key === i.key)));
  const groups = GROUP_ORDER.filter(gn => L.some(i => (i.group || "Other") === gn)).concat(L.some(i => !GROUP_ORDER.includes(i.group || "Other")) ? ["Other"] : []);
  const quick = [["Top 5 municipalities", MUNI.slice().sort((a, b) => (b.pop || 0) - (a.pop || 0)).slice(0, 5).map(m => "kommune:" + m.code)],
                 ["Copenhagen metro", ["101", "147", "157", "159", "173", "230"].filter(c => byCode[c]).map(c => "kommune:" + c)],
                 ["Big four", ["101", "751", "461", "851"].filter(c => byCode[c]).map(c => "kommune:" + c)]];
  const { series } = chartSeries(); const q = isQ(ys[0] || "");
  const hasNat = !!NAT && (NAT[ind.key] != null || !!(NAT.hist && NAT.hist[ind.key]));
  const cands = overlayCands(ind);
  return `
  <div class="card accent">
    <div class="card-head tools-only"><div class="tools">
      <select id="chind" class="indsel">${groups.map(gn => `<optgroup label="${esc(gn)}">${L.filter(i => (i.group || "Other") === gn).map(i => `<option value="${i.key}" ${CH.ind === i.key ? "selected" : ""}>${esc(optLabel(i))}</option>`).join("")}</optgroup>`).join("")}</select>
      <select id="chy0" class="indsel"><option value="">from ${YEARS[0]}</option>${YEARS.map(y => `<option value="${y}" ${CH.y0 === y ? "selected" : ""}>${y}</option>`).join("")}</select>
      <select id="chy1" class="indsel"><option value="">to ${LATEST}</option>${YEARS.map(y => `<option value="${y}" ${CH.y1 === y ? "selected" : ""}>${y}</option>`).join("")}</select>
      ${qPeriods(ind).length > 1 ? `<div class="seg" title="Quarterly: each point is the rolling sum of the 4 quarters ending there">${[["year", "Yearly"], ["q", "Quarterly"]].map(([f, l]) => `<button class="sg ${CH.fq === f ? "on" : ""}" data-chfq="${f}">${l}</button>`).join("")}</div>` : ""}
      <label class="hint" style="display:flex;align-items:center;gap:5px"><input type="checkbox" id="chmed" ${CH.median ? "checked" : ""}> median</label>
      ${hasNat ? `<label class="hint" style="display:flex;align-items:center;gap:5px" title="Denmark as a whole (DST area 000), dashed"><input type="checkbox" id="chnat" ${CH.nat ? "checked" : ""}> Denmark</label>` : ""}
      <div class="seg">${[["auto", "Auto"], ["line", "Line"], ["bar", "Bars"], ["dist", "Distribution"]].map(([m, l]) => `<button class="sg ${CH.mode === m ? "on" : ""}" data-chmode="${m}">${l}</button>`).join("")}</div>
      ${chartMode() === "dist" ? `<select id="chdist" class="indsel">${Object.entries(DIST_DEFS).map(([k, v]) => `<option value="${k}" ${CH.dist === k ? "selected" : ""}>${v[0]}</option>`).join("")}</select>` : ""}</div></div>
    ${ents.length && CH.mode === "auto" && chartMode() === "bar" && chartYears().length < 2 ? `<p class="hint" style="margin:0 0 8px">This indicator is a single snapshot (no history) — shown as bars of the latest value. BBR distributions are under <b>Distribution</b>.</p>` : ""}
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
    <p class="cap">${esc(ind.desc || "")} ${ind.warn ? "⚠ " + esc(ind.warn) : ""} ${q ? "Quarterly: each point is the rolling sum of the 4 quarters ending in that quarter." : "Same sub-period each year (e.g. Q3 or July); values are those shown in the dashboard."}${hasNat && CH.nat ? " Dashed line in a series colour = Denmark as a whole." : ""}</p>
  </div>
  ${chartMode() === "line" && ents.length && series.length ? `<div class="card"><div class="card-head"><h3>Data</h3><span class="hint">${esc(ind.unit || "")}</span></div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>${q ? "Quarter" : "Year"}</th>${series.map(s_ => `<th class="num">${esc(s_.name)}</th>`).join("")}</tr></thead>
    <tbody>${ys.map((yy, i) => `<tr><th>${fmtP(yy)}</th>${series.map(s_ => fmtCell(ind, s_.pts[i].v, false)).join("")}</tr>`).join("")}</tbody></table></div></div>` : ""}
  ${chartMode() === "dist" && ents.some(e => e.o.bbr) ? `<div class="card"><div class="card-head"><h3>Data</h3><span class="hint">share of dwellings · count</span></div>
    <div class="scrollx"><table class="tbl compact" data-sortable><thead><tr><th>Area</th><th class="num">Dwellings</th>${(DIST_DEFS[CH.dist] || DIST_DEFS.size)[1].map(l => `<th class="num">${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${ents.filter(e => e.o.bbr && e.o.bbr.dist).map(e => { const d = e.o.bbr.dist[CH.dist]; const t = d.reduce((a, b) => a + b, 0) || 1; return `<tr><th>${esc(e.name)}</th><td class="num">${nf(e.o.bbr.n, 0)}</td>${d.map(v => `<td class="num" data-v="${v / t * 100}">${nf(v / t * 100, 0)} % <span class="dim">${nf(v, 0)}</span></td>`).join("")}</tr>`; }).join("")}</tbody></table></div></div>` : ""}`;
}
function chartAddMany(ids) { ids.forEach(id => { if (!CH.areas.includes(id) && CH.areas.length < 8) CH.areas.push(id); }); syncHash(); renderKeep(); }
function chartPng() {
  const svg = chartSvg(true).replace('class="chart" ', 'width="1200" height="640" ').replace(' id="chsvg"', "");
  const img = new Image(); const scale = 2; const W = 1200, H = 640;
  img.onload = () => { const c = document.createElement("canvas"); c.width = W * scale; c.height = H * scale; const ctx = c.getContext("2d"); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, W, H);
    c.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `chart_${CH.ind}_${chartYears()[0]}-${chartYears().slice(-1)[0]}.png`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }, "image/png"); };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}
function chartCsv() {
  if (chartMode() === "dist") { const ents = CH.areas.map(chEntity).filter(e => e && e.o.bbr && e.o.bbr.dist); const [dl, labels] = DIST_DEFS[CH.dist] || DIST_DEFS.size;
    downloadCsv([["area", "dwellings"].concat(labels).join(";")].concat(ents.map(e => [e.name, e.o.bbr.n].concat(e.o.bbr.dist[CH.dist]).join(";"))), `chart_${CH.dist}_distribution.csv`); return; }
  if (chartMode() === "bar") { const ind = chartInd(); const ents = CH.areas.map(chEntity).filter(Boolean);
    downloadCsv([["area", ind.key].join(";")].concat(ents.map(e => [e.name, V(e.o, ind.key) ?? (e.type === "postnr" && e.muni ? V(e.muni, ind.key) : "") ?? ""].join(";"))), `chart_${ind.key}_latest.csv`); return; }
  const { ind, ys, series } = chartSeries();
  downloadCsv([[isQ(ys[0] || "") ? "quarter" : "year"].concat(series.map(s_ => s_.name)).join(";")].concat(ys.map((yy, i) => [yy].concat(series.map(s_ => s_.pts[i].v ?? "")).map(v => String(v).replace(/;/g, ",")).join(";"))), `chart_${ind.key}.csv`);
}

/* ---------- Market view (Denmark-only panel) ---------- */
function spark(series, w = 160, h = 26) {
  const v = (series || []).map(p => p.v).filter(x => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - 2 - (x - lo) / sp * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts}"/></svg>`;
}
function lineChart(key, opts = {}) {
  const s = ((D.macro && D.macro.series) || {})[key] || [];
  const pts = s.filter(p => p.v != null);
  if (pts.length < 2) return `<p class="empty">no series for ${esc(key)}</p>`;
  const W = 640, H = 180, L0 = 44, R = 10, T0 = 10, B = 24;
  const v = pts.map(p => p.v), lo = opts.zero ? 0 : Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const x = i => L0 + i / (pts.length - 1) * (W - L0 - R), y = val => T0 + (1 - (val - lo) / sp) * (H - T0 - B);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const ticks = [lo, lo + sp / 2, hi];
  const xl = [0, Math.floor(pts.length / 2), pts.length - 1];
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(y(t) + 3).toFixed(1)}" text-anchor="end">${nf(t, opts.dec ?? 1)}</text>`).join("")}
    ${xl.map(i => `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}">${esc(pts[i].t)}</text>`).join("")}
    <path d="${path}" fill="none" stroke="${opts.color || "#1C6B5C"}" stroke-width="2"/></svg>`;
}
function vMarket() {
  const mac = D.macro || {}, lt = mac.latest || {};
  if (!Object.keys(lt).length) return `<div class="card"><p class="empty">No macro series built yet — run the pipeline (see Sources).</p></div>`;
  const tile = (key, label) => { const o = lt[key]; if (!o) return ""; const yoy = o.yoy;
    return `<div><span>${esc(label)}</span><b>${nf(o.v, o.dec ?? 1)}<i class="u">${esc(o.unit || "")}</i></b>
      ${yoy != null ? `<em class="k ${yoy > 0 ? "up" : yoy < 0 ? "dn" : ""}">${sign(yoy, x => nf(x, 1) + " %")} y/y</em>` : ""}<em>${esc(o.label || "")} · ${esc(o.t || "")}</em>${spark((mac.series || {})[key])}</div>`; };
  const heroKeys = (mac.hero || ["rent_index", "hpi_flats", "supply_dk", "completions"]);
  const tableKeys = mac.table || Object.keys(lt);
  return `
  <div class="hero">${heroKeys.map(k => tile(k, (lt[k] || {}).label || k)).join("")}</div>
  <div class="grid-2">
    <div class="card"><div class="card-head"><h3>Rent index, private rental (2021 = 100)</h3><span class="hint">DST HUS1</span></div>${lineChart("rent_index")}</div>
    <div class="card"><div class="card-head"><h3>House price index, owner-occupied flats</h3><span class="hint">DST EJ56</span></div>${lineChart("hpi_flats")}</div>
    <div class="card"><div class="card-head"><h3>Homes for sale, Denmark</h3><span class="hint">Finans Danmark UDB010</span></div>${lineChart("supply_dk", { dec: 0, color: "#B07A1E" })}</div>
    <div class="card"><div class="card-head"><h3>Interest rates</h3><span class="hint">Danmarks Nationalbank via DST</span></div>${lineChart("rate_policy", { dec: 2, color: "#5C5F52" })}</div>
  </div>
  <div class="card"><div class="card-head"><h3>Macro indicators</h3><span class="hint">latest available period per series</span></div>
    <table class="tbl compact" data-sortable><thead><tr><th>Indicator</th><th class="num">Value</th><th class="num">y/y</th><th>Period</th><th>Source</th></tr></thead>
    <tbody>${tableKeys.map(k => { const o = lt[k]; if (!o) return ""; return `<tr><th>${esc(o.label || k)}</th><td class="num" data-v="${o.v}">${nf(o.v, o.dec ?? 1)} ${esc(o.unit || "")}</td>
      <td class="num ${o.yoy > 0 ? "good" : o.yoy < 0 ? "bad" : ""}">${o.yoy != null ? sign(o.yoy, x => nf(x, 1) + " %") : "–"}</td><td class="dim">${esc(o.t || "")}</td><td class="dim">${esc(o.src || "")}</td></tr>`; }).join("")}</tbody></table>
    <p class="cap">${esc(mac.note || "")}</p></div>
  <details class="dinfo srcfold" ${MKT.src ? "open" : ""} id="srcfold"><summary>Sources, freshness and indicator definitions</summary>${vSources()}</details>`;
}

/* ---------- Sources (folded under Market) ---------- */
function vSources() {
  const s = ((D.meta && D.meta.sources) || []).concat(CPH && CPH.meta ? CPH.meta.sources || [] : []);
  const defs = (list, title) => `<div class="card"><div class="card-head"><h3>${title}</h3></div>
    <table class="tbl compact"><thead><tr><th>Indicator</th><th>Unit</th><th>Level</th><th>Definition</th><th>Source</th><th>Caveat</th></tr></thead>
    <tbody>${list.map(i => `<tr><th>${esc(i.label)}</th><td class="dim">${esc(i.unit || "")}</td><td class="dim">${esc(i.level)}</td><td>${esc(i.desc || "")}</td><td class="dim">${esc(i.source || "")}</td><td class="dim">${esc(i.warn || "")}</td></tr>`).join("")}</tbody></table></div>`;
  return `<div class="card"><div class="card-head"><h3>Data sources and freshness</h3><span class="hint">built ${esc((D.meta && D.meta.built) || "–")}</span></div>
    <table class="tbl compact"><thead><tr><th>Source</th><th>Tables / files</th><th>As of</th><th>Fetched</th><th>Licence</th></tr></thead>
    <tbody>${s.map(x => `<tr><th>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>` : esc(x.label)}</th><td class="dim">${esc(x.tables || "")}</td><td>${esc(x.asof || "")}</td><td class="dim">${esc(x.fetched || "")}</td><td class="dim">${esc(x.licence || "")}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">no sources recorded</td></tr>`}</tbody></table>
    <p class="cap">${((D.meta && D.meta.attribution) || []).map(esc).join(" · ")}${CPH && CPH.meta && CPH.meta.attribution ? " · " + esc(CPH.meta.attribution) : ""}</p></div>
  ${defs(IND, "Indicator definitions — municipalities and postal codes")}
  ${CPH ? defs(IND_CPH, "Indicator definitions — Copenhagen quarters") : ""}`;
}

parseHash();
render();
