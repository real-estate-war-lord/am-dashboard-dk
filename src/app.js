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
  int: v => nf(v, 0), days: v => nf(v, 0) + " d", m2: v => nf(v, 0) + " m²", per1000: v => nf(v, 1) + " ‰", idx: v => nf(v, 1)
};
const fmtOf = i => FMT[i.fmt] || FMT.pct1;
const isPct = i => (i.fmt || "").startsWith("pct") || i.fmt === "signpct1";
const median = arr => { const v = arr.filter(x => x != null && !isNaN(x)).sort((a, b) => a - b); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
const byCode = {}; MUNI.forEach(m => byCode[m.code] = m);
const byNr = {}; AREAS.forEach(a => byNr[a.nr] = a);
/* Copenhagen quarter layer (data/processed/cph.json): 67 kvarterer with their own indicator set */
const CPH = D.cph && D.cph.areas && D.cph.areas.length ? D.cph : null;
const IND_CPH = CPH ? CPH.indicators : [];
const CPH_MUNI = "101";
const byQ = {}; if (CPH) CPH.areas.forEach(a => byQ[a.code] = a);
const cphMode = () => !!(CPH && MK.muni === CPH_MUNI && MK.cphView !== "postnr");
const S = { view: "makro" };
const YEARS = [...new Set([...((D.meta && D.meta.years) || []), ...((D.cph && D.cph.meta && D.cph.meta.years) || [])])].sort();
const LATEST = (D.meta && D.meta.latest_year) || (YEARS[YEARS.length - 1] || "");
const MK = { ind: (IND[0] || {}).key, muni: null, own: false, year: LATEST, cphView: "kvarter", micro: false, mind: "rented_pct" };
/* Micro (building) layer: dist/micro/<kommune>.json, loaded on demand; D.micro = index {code: {file, n}} */
const MICRO_IDX = (D.micro && D.micro.municipalities) || {};
const MICRO = {};                                  /* code → {meta, b:[…]} once loaded */
const MICRO_INDS = [
  { key: "rented_pct", label: "Rented dwellings", short: "Rented", unit: "% of dwellings", fmt: "pct0", hue: [40, 84, 128], col: 3 },
  { key: "vacant_pct", label: "Unoccupied dwellings", short: "Unoccupied", unit: "% of dwellings", fmt: "pct0", hue: [166, 42, 22], col: 4 },
  { key: "avg_m2", label: "Average dwelling size", short: "Ø m²", unit: "m²", fmt: "m2", hue: [90, 60, 150], col: 5 },
  { key: "year", label: "Year built", short: "Built", unit: "year", fmt: "int", hue: [10, 88, 70], col: 6 },
  { key: "dwellings", label: "Dwellings in building", short: "Dwellings", unit: "dwellings", fmt: "int", hue: [150, 90, 30], col: 2 },
  { key: "small_pct", label: "Small dwellings < 50 m²", short: "< 50 m²", unit: "% of dwellings", fmt: "pct0", hue: [12, 94, 104], col: 13 },
  { key: "floors", label: "Floors", short: "Floors", unit: "floors", fmt: "int", hue: [92, 110, 140], col: 7 }];
const MTYPE = { 1: "house", 2: "row house", 3: "multi-dwelling", 4: "other / mixed" };
const MF = { minDw: 2, yFrom: "", yTo: "", type: "", rentMin: 0 };   /* building filters */
const microAvail = code => !!(code && MICRO_IDX[String(Number(code))]);
const microMode = () => !!(MK.micro && MK.muni && microAvail(MK.muni));
const curMind = () => MICRO_INDS.find(i => i.key === MK.mind) || MICRO_INDS[0];
const AR = { type: null, code: null, group: "key", ind: null, sub: "kvarter" };   /* area page */
const T = { q: "", level: "kommune", region: "", minPop: 0 };                     /* table view filters */
const REGIONS = ["Hovedstaden", "Sjælland", "Syddanmark", "Midtjylland", "Nordjylland"];
const LF = { map: null, center: [56.0, 10.5], zoom: 7 };
const MICRO_ZOOM = 10;
/* quarter indicators whose definition matches the national one closely enough to put København next to a quarter */
const CPH_CMP = new Set(["growth", "young", "higher_ed", "renters", "almene", "avg_m2"]);
const muniCmp = (e, key) => !!e.muni && (e.type !== "kvarter" || CPH_CMP.has(key));
/* "All figures" tab: at most 14 tiles (7 × 2), in this order; the group tabs hold everything else */
const KEY_INDS = ["growth", "young", "income_med", "unemp", "higher_ed", "renters", "almene", "price_m2", "discount", "dom", "rent_private", "rent_social", "supply", "pipeline", "avg_m2", "new_stock", "private_rental", "andel", "single"];
const MAX_TILES = 14;
/* value of indicator k for municipality/area o in the selected year (latest = live field, else history) */
const V = (o, k, y) => { const yr = y || MK.year; if (!o) return null; if (!yr || yr === LATEST) return o[k] ?? null; const h = o.hist && o.hist[k]; return h && h[yr] != null ? h[yr] : null; };
const yearsForPool = (k, pool) => YEARS.filter(y => y === LATEST || pool.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
function curPool() { if (S.view === "area") { const e = areaEntity(); return e ? e.peers : MUNI; } if (S.view === "table" && T.level === "kvarter") return CPH ? CPH.areas : MUNI; return cphMode() ? CPH.areas : MUNI; }
const yearsFor = k => yearsForPool(k, curPool());
const curInds = () => { if (S.view === "area") { const e = areaEntity(); return e ? e.inds : IND; } if (S.view === "table") return T.level === "kvarter" ? IND_CPH : IND; return cphMode() ? IND_CPH : IND; };
const curInd = () => { const L = curInds(); return L.find(i => i.key === MK.ind) || L[0] || { key: "", label: "", fmt: "pct1" }; };

/* ---------- routing (hash) ---------- */
function hashFor() {
  const q = [`ind=${encodeURIComponent(MK.ind || "")}`]; if (MK.year && MK.year !== LATEST) q.push(`y=${MK.year}`);
  if (S.view === "makro" && MK.micro) { q.push("micro=1"); q.push(`mind=${MK.mind}`); }
  let p;
  if (S.view === "area") { p = `area/${AR.type}/${AR.code}`; if (AR.group !== "key") q.push(`g=${encodeURIComponent(AR.group)}`); if (AR.sub !== "kvarter") q.push(`sub=${AR.sub}`); }
  else if (S.view === "table") p = `table/${T.level}`;
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
  if (v === "area" && parts[1] && parts[2]) { S.view = "area"; AR.type = parts[1]; AR.code = parts[2]; AR.group = q.g || "key"; AR.sub = q.sub || "kvarter"; }
  else if (v === "table") { S.view = "table"; if (["kommune", "postnr", "kvarter"].includes(parts[1])) T.level = parts[1]; }
  else if (v === "market" || v === "sources") S.view = v;
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
  ["market",  "Market",        "Prices, rents, supply, construction and macro indicators", "market"],
  ["sources", "Sources",       "Data sources, freshness and definitions", "sources"]];
const NAV_GROUPS = [["Market intelligence", ["makro", "table", "market", "sources"]]];
const viewOf = id => VIEWS.find(v => v[0] === id) || VIEWS[0];

function renderNav() {
  const on = S.view === "area" ? "makro" : S.view;
  document.getElementById("nav").innerHTML = NAV_GROUPS.map(([lab, ids]) => `<div class="nav-glab">${lab}</div>` +
    ids.map(id => { const v = viewOf(id); return `<button class="nav-item ${on === id ? "on" : ""}" data-go="${v[3]}"><b>${v[1]}</b><em>${v[2]}</em></button>`; }).join("")).join("");
}
function renderTop() {
  if (S.view === "area") { const e = areaEntity(); document.getElementById("hd").innerHTML = e ? `<h1>${esc(e.name)}</h1><p class="dim">${esc(e.typeLabel)} · ${crumbText(e)}</p>` : `<h1>Area</h1>`; return; }
  const v = viewOf(S.view);
  document.getElementById("hd").innerHTML = `<h1>${v[1]}</h1><p class="dim">${v[2]}</p>`;
}
const RENDER = { makro: vMakro, table: vTable, area: vArea, market: vMarket, sources: vSources };
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
  if ((el = g("[data-micro]"))) { MK.micro = el.dataset.micro === "1"; syncHash(); renderKeep(); return; }
  if (g("[data-mcsv]")) { exportMicroCsv(); return; }
  if ((el = g("[data-argroup]"))) { AR.group = el.dataset.argroup; syncHash(); renderKeep(); return; }
  if ((el = g("[data-arsub]"))) { AR.sub = el.dataset.arsub; syncHash(); renderKeep(); return; }
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
  if (el.id === "mf-type") { MF.type = el.value; lfLayers(); }
  if (["mf-mindw", "mf-yfrom", "mf-yto", "mf-rent"].includes(el.id)) { MF.minDw = Number(document.getElementById("mf-mindw").value) || 1; MF.yFrom = document.getElementById("mf-yfrom").value; MF.yTo = document.getElementById("mf-yto").value; MF.rentMin = Number(document.getElementById("mf-rent").value) || 0; lfLayers(); }
  if (el.id === "tregion") { T.region = el.value; renderTableBody(); }
  if (el.id === "tminpop") { T.minPop = Number(el.value) || 0; renderTableBody(); }
});
document.addEventListener("input", e => { if (e.target.id === "tq") { T.q = e.target.value.trim().toLowerCase(); renderTableBody(); } });
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.id === "areaq") { areaSearchGo(e.target.value); return; }
  if (e.key === "Escape" && S.view === "area") history.back();
});

/* ---------- info tooltips (ⓘ) ---------- */
let TIPEL = null, TIPFOR = null;
function tipToggle(el) { if (TIPFOR === el) { tipHide(); return; } tipShow(el); }
function tipShow(el) {
  const i = IND.concat(IND_CPH).find(x => x.key === el.dataset.m); if (!i) return;
  if (!TIPEL) { TIPEL = document.createElement("div"); TIPEL.className = "imtip"; document.body.appendChild(TIPEL); }
  TIPEL.innerHTML = `<b>${esc(i.label)}</b><p><em>Definition</em>${esc(i.desc || "")}</p>` + (i.source ? `<p><em>Source</em>${esc(i.source)}</p>` : "") + (i.warn ? `<p class="warn"><em>Caveat</em>${esc(i.warn)}</p>` : "");
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
        const dir = th.dataset.dir === "asc" ? -1 : 1; th.dataset.dir = dir === 1 ? "asc" : "desc";
        const val = r => { const c = r.cells[idx]; if (!c) return null; const v = parseFloat((c.dataset.v ?? c.textContent).replace(/\s/g, "").replace(",", ".")); return isNaN(v) ? null : v; };
        rows.sort((a, b) => { const x = val(a), y = val(b); if (x == null && y == null) return (a.cells[idx] ? a.cells[idx].textContent : "").localeCompare(b.cells[idx] ? b.cells[idx].textContent : ""); if (x == null) return 1; if (y == null) return -1; return (x - y) * dir; });
        rows.forEach(r => tb.appendChild(r));
      });
    });
  });
}

/* ---------- choropleth colour model (identical to the Finnish edition) ---------- */
function mkShade(t, key) {
  const i = key.startsWith("micro:") ? MICRO_INDS.find(x => x.key === key.slice(6)) : IND.concat(IND_CPH).find(x => x.key === key); const hue = (i && i.hue) || [10, 88, 70];
  const a = [239, 242, 238]; const c = a.map((x, k) => Math.round(x + (hue[k] - x) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
function scaleOf(list, vk) {
  const vals = list.map(vk).filter(v => v != null && !isNaN(v));
  if (!vals.length) return { t: () => null, lo: null, hi: null };
  const lo = Math.min(...vals), hi = Math.max(...vals);
  return { t: v => v == null || isNaN(v) ? null : (hi > lo ? (v - lo) / (hi - lo) : .5), lo, hi };
}
const GROUP_ORDER = ["Demographics", "Income & jobs", "Housing stock", "Housing stock (BBR)", "Rents", "Prices & market", "Construction"];
function indSelect() {
  const L = curInds();
  const groups = GROUP_ORDER.filter(gname => L.some(i => (i.group || "Other") === gname)).concat(L.some(i => !GROUP_ORDER.includes(i.group || "Other")) ? ["Other"] : []);
  return `<select id="indsel" class="indsel" aria-label="Indicator">${groups.map(gname => `<optgroup label="${esc(gname)}">${L.filter(i => (i.group || "Other") === gname).map(i =>
    `<option value="${i.key}" ${MK.ind === i.key ? "selected" : ""}>${esc(i.label)}${i.unit ? " · " + esc(i.unit) : ""}</option>`).join("")}</optgroup>`).join("")}</select>`;
}
/* searchable area box: municipalities open on the map, postal codes and quarters open their page */
const AREA_OPTS = [];
MUNI.slice().sort((a, b) => a.name.localeCompare(b.name, LOCALE)).forEach(m => AREA_OPTS.push({ t: `${m.name} — municipality, ${m.region || ""}`, h: `map/${m.code}`, k: [m.name.toLowerCase(), m.code] }));
AREAS.slice().sort((a, b) => a.nr.localeCompare(b.nr)).forEach(a => AREA_OPTS.push({ t: `${a.nr} ${a.name} — postal code, ${(byCode[a.muni] || {}).name || ""}`, h: `area/postnr/${a.nr}`, k: [a.nr, (a.name || "").toLowerCase()] }));
if (CPH) CPH.areas.slice().sort((a, b) => (a.name || "").localeCompare(b.name || "", LOCALE)).forEach(q => AREA_OPTS.push({ t: `${q.name} — Copenhagen quarter, ${q.bydel || ""}`, h: `area/kvarter/${q.code}`, k: [(q.name || "").toLowerCase(), q.code] }));
function areaSearch() {
  const m = MK.muni ? byCode[MK.muni] : null;
  return `<span class="asrch"><input id="areaq" list="arealist" class="indsel" placeholder="${m ? esc(m.name) + " — search another area…" : "Search municipality, postal code or quarter…"}" autocomplete="off" aria-label="Area">
    <datalist id="arealist">${AREA_OPTS.map(o => `<option value="${esc(o.t)}"></option>`).join("")}</datalist>${m ? `<button class="lk mini" data-go="map?ind=${MK.ind}" title="Back to the whole country">× Denmark</button>` : ""}</span>`;
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
  return `<div class="indx">
    <div class="indx-head"><b>${esc(i.label)}</b><span class="tag">${i.level === "kvarter" ? "Copenhagen quarter level" : i.level === "postnr" ? "postal-code level" : "municipality level"}</span><span class="tag">${esc(i.unit || "")}</span></div>
    <p>${esc(i.desc || "")}</p>
    <p class="dim"><em>Source</em> ${esc(i.source || "–")}${asof ? ` · <em>As of</em> ${asof}` : ""} · <em>Coverage</em> ${cov}${ys.length > 1 ? ` · <em>History</em> ${ys[0]}–${LATEST}` : ""}</p>
    ${i.warn ? `<p class="warnline">⚠ ${esc(i.warn)}</p>` : ""}
  </div>`;
}
function yearSelect() {
  const ys = yearsFor(MK.ind);
  if (ys.length < 2) return "";
  const hy = ys.filter(y => y !== LATEST); const lastHist = hy[hy.length - 1];
  const pool = curPool();
  const label = y => y === LATEST ? (lastHist && lastHist !== LATEST && !pool.some(m => m.hist && m.hist[MK.ind] && m.hist[MK.ind][LATEST] != null) ? `latest (${lastHist} data)` : `${y} (latest)`) : y;
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
    ${esc((D.meta && D.meta.note) || "")}</div>${extra}<p class="cap">Full definitions and table stamps under <button class="lk mini" data-go="sources">Sources</button>. Built ${esc((D.meta && D.meta.built) || "–")}.</p></details>`;
}
function rankOf(o, key, peers) {
  const v = V(o, key); if (v == null) return null;
  const vals = peers.map(p => V(p, key)).filter(x => x != null);
  return { r: 1 + vals.filter(x => x > v).length, n: vals.length };
}
function muniStrip(m) {
  /* the selected municipality in one line: population, region, selected indicator + rank, link to its page */
  const ind = curInd(); const inds = cphMode() ? IND_CPH : IND;
  const key = ["growth", "price_m2", "rent_private", "unemp", "renters"].map(k => inds.find(i => i.key === k)).filter(i => i && V(m, i.key) != null).slice(0, 4);
  const cell = i => { const rk = rankOf(m, i.key, MUNI); return `<div><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(V(m, i.key))}</b><em>${rk ? `#${rk.r} of ${rk.n}` : ""}</em></div>`; };
  return `<div class="mstrip">
    <div class="mstrip-id"><b>${esc(m.name)}</b><span class="dim">${esc(m.region || "")} · ${m.pop != null ? nf(m.pop, 0) + " inhabitants" : ""} · ${muniAreas(m.code).length} ${cphMode() ? "quarters" : "postal codes"}</span></div>
    <div class="mstrip-k">${key.map(cell).join("")}</div>
    <div class="mstrip-act"><button class="lk primary" data-go="${withQ(pageOf(m))}">Open ${esc(m.name)} page ›</button><button class="lk" data-go="map?ind=${MK.ind}">‹ Denmark</button></div>
  </div>`;
}
function vMakro() {
  if (!AREAS.length || !MUNI.length) return `<div class="card"><p class="empty">No macro data built yet — run <code>make fetch</code>, <code>make geo</code> and <code>make build</code>.</p></div>`;
  const ind = curInd();
  setTimeout(lfInit, 0);
  const legend = [0, .25, .5, .75, 1].map(x => `<i style="background:${mkShade(x, microMode() ? "micro:" + curMind().key : ind.key)}"></i>`).join("");
  const muni = MK.muni ? byCode[MK.muni] : null;
  return `
  <div class="card accent">
    <div class="card-head"><h3>${muni ? esc(muni.name) + (microMode() ? " — buildings" : cphMode() ? " — quarters" : " — postal codes") : "Macro map — Denmark"}</h3>
      <div class="tools">${areaSearch()}${muni && microAvail(muni.code) ? `<div class="seg"><button class="sg ${!MK.micro ? "on" : ""}" data-micro="0">Areas</button><button class="sg ${MK.micro ? "on" : ""}" data-micro="1">Buildings (${nf(MICRO_IDX[String(Number(muni.code))].n, 0)})</button></div>` : ""}${muni && muni.code === CPH_MUNI && CPH && !microMode() ? `<div class="seg"><button class="sg ${MK.cphView !== "postnr" ? "on" : ""}" data-cphview="kvarter">Quarters (${CPH.areas.length})</button><button class="sg ${MK.cphView === "postnr" ? "on" : ""}" data-cphview="postnr">Postal codes</button></div>` : ""}${microMode() ? mindSelect() : indSelect() + yearSelect()}${D.portfolio ? `<button class="lk mini ${MK.own ? "primary" : ""}" data-mkown>● Own properties</button>` : ""}</div></div>
    ${microMode() ? microExplain() : indExplain(ind)}
    ${muni && !microMode() ? muniStrip(muni) : ""}
    <div id="lfmap"></div>
    <div class="mklegend"><span>low</span><span id="lglo" class="lgv"></span>${legend}<span id="lghi" class="lgv"></span><span>high</span>
      <span class="dim">· ${microMode() ? esc(curMind().label) + ", " + esc(curMind().unit) + " · dot size = dwellings" : esc(ind.label) + (ind.unit ? ", " + esc(ind.unit) : "") + " · scaled to the visible level"}</span>
      <span style="margin-left:auto" class="dim">${microMode() ? "buildings — BBR register" : cphMode() ? "Copenhagen quarters — Københavns Kommune statbank" : ind.level === "postnr" ? "zoom in → postal-code values" : "municipality-level indicator — postal codes take the municipality value"}</span></div>
    ${srcNote(`<p class="cap">${muni ? "Click a polygon for its figures and a link to its page." : "Click a polygon for its figures; open a municipality with the search box above or from the popup. Table view lists everything side by side."} Boundaries: DAGI, Klimadatastyrelsen (simplified); basemap OpenStreetMap.</p>`)}
  </div>`;
}

/* ---------- Table view ---------- */
function fmtCell(i, v, fallback) {
  if (v == null || isNaN(v)) return `<td class="num">–</td>`;
  return `<td class="num" data-v="${v}">${fmtOf(i)(v)}${fallback ? " °" : ""}</td>`;
}
function deltaCell(o, i, pool) {
  const y0 = yearsForPool(i.key, pool || curPool())[0]; if (!y0 || y0 === MK.year) return `<td class="num dim">–</td>`;
  const a = V(o, i.key, y0), b = V(o, i.key); if (a == null || b == null) return `<td class="num dim">–</td>`;
  const d = isPct(i) ? b - a : (a ? (b / a - 1) * 100 : null); if (d == null) return `<td class="num dim">–</td>`;
  return `<td class="num ${d > 0 ? "good" : d < 0 ? "bad" : ""}" data-v="${d}">${sign(d, x => nf(x, 1))}${isPct(i) ? " pp" : " %"}</td>`;
}
function tableRows() {
  const q = T.q;
  if (T.level === "kvarter") return (CPH ? CPH.areas : []).filter(a => (a.pop || 0) >= T.minPop && (!q || (a.name || "").toLowerCase().includes(q) || (a.bydel || "").toLowerCase().includes(q) || a.code.includes(q)));
  if (T.level === "kommune") return MUNI.filter(m => (!T.region || m.region === T.region) && (m.pop || 0) >= T.minPop && (!q || m.name.toLowerCase().includes(q) || m.code.includes(q)));
  return AREAS.filter(a => { const m = byCode[a.muni] || {}; return (!T.region || m.region === T.region) && (a.pop || 0) >= T.minPop && (!q || (a.name || "").toLowerCase().includes(q) || a.nr.includes(q) || (m.name || "").toLowerCase().includes(q)); });
}
function tableCols() { return T.level === "kvarter" ? IND_CPH : T.level === "postnr" ? IND.filter(i => i.level === "postnr").concat(IND.filter(i => i.level !== "postnr")) : IND; }
function tableBodyHtml() {
  const cols = tableCols(), ind = curInd(), pool = curPool(), y0 = yearsForPool(ind.key, pool)[0];
  const rows = tableRows().slice().sort((a, b) => ((V(b, ind.key) ?? V(byCode[b.muni], ind.key)) ?? -1e9) - ((V(a, ind.key) ?? V(byCode[a.muni], ind.key)) ?? -1e9));
  if (!rows.length) return `<tr><td colspan="${cols.length + 5}" class="empty">no rows match the filters</td></tr>`;
  return rows.map(r => {
    const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    const lead = `<tr class="clickrow" data-go="${withQ(pageOf(r))}"><th>${esc(r.name)} <span class="go">›</span></th>`;
    if (T.level === "kvarter") return `${lead}<td class="dim">${esc(r.code)}</td><td class="dim">${esc(r.bydel || "")}</td><td class="num dim" data-v="${r.pop || 0}">${r.pop != null ? nf(r.pop, 0) : "–"}</td>
      ${fmtCell(ind, V(r, ind.key), false)}${y0 && y0 !== MK.year ? deltaCell(r, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(i => fmtCell(i, V(r, i.key), false)).join("")}</tr>`;
    const cell = i => { const own = V(r, i.key); return own != null ? fmtCell(i, own, false) : (T.level === "postnr" ? fmtCell(i, V(m, i.key), true) : fmtCell(i, null, false)); };
    return `${lead}<td class="dim">${T.level === "postnr" ? esc(r.nr) : esc(r.code)}</td><td class="dim">${T.level === "postnr" ? esc(m.name || "") : esc(r.region || "")}</td>
      <td class="num dim" data-v="${r.pop || 0}">${r.pop != null ? nf(r.pop, 0) : "–"}</td>
      ${cell(ind)}${y0 && y0 !== MK.year ? deltaCell(r, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(cell).join("")}</tr>`; }).join("");
}
function renderTableBody() {
  const tb = document.getElementById("tbody"); if (!tb) return;
  tb.innerHTML = tableBodyHtml();
  const n = document.getElementById("tcount"); if (n) n.textContent = `${tableRows().length} rows`;
}
function vTable() {
  const ind = curInd(), cols = tableCols(), y0 = yearsFor(ind.key)[0];
  return `
  <div class="card accent">
    <div class="card-head"><h3>Table${MK.year !== LATEST ? " · " + MK.year : ""}</h3>
      <div class="tools">${indSelect()}${yearSelect()}</div></div>
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
      <th class="num hi">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${isPct(ind) ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
      <tbody id="tbody">${tableBodyHtml()}</tbody></table></div>
    <p class="cap">Sorted by the selected indicator; click a column header to re-sort, a row to open the area's page. ° = municipality value shown on a postal code. Rows: ${T.level === "postnr" ? "postal codes (street-level codes in central Copenhagen merged by name)" : T.level === "kvarter" ? "Copenhagen quarters (kvarterer), source Københavns Kommune statbank" : "municipalities"}.</p>
    ${srcNote()}
  </div>`;
}
function exportCsv() {
  const cols = tableCols(), rows = tableRows();
  const head = [T.level === "kvarter" ? "quarter" : T.level === "postnr" ? "area" : "municipality", T.level === "postnr" ? "postal_code" : "code", T.level === "kvarter" ? "district" : T.level === "postnr" ? "municipality" : "region", "population"].concat(cols.map(i => i.key));
  const lines = [head.join(";")].concat(rows.map(r => { const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    return [r.name, T.level === "postnr" ? r.nr : r.code, T.level === "kvarter" ? (r.bydel || "") : T.level === "postnr" ? (m.name || "") : (r.region || ""), r.pop ?? ""].concat(cols.map(i => V(r, i.key) ?? (T.level === "postnr" ? (V(m, i.key) ?? "") : ""))).map(v => String(v).replace(/;/g, ",")).join(";"); }));
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
    return { type: "kvarter", typeLabel: "Copenhagen quarter", o: q, name: q.name, code: q.code, muni: m, region: m && m.region, bydel: q.bydel, inds: IND_CPH, peers: CPH.areas, peerLabel: "quarters",
             ctx: CPH.areas, own: [q], subs: null };
  }
  return null;
}
function crumbText(e) { return ["Denmark", e.region, e.muni ? e.muni.name : null, e.bydel].filter(Boolean).map(esc).join(" › "); }
/* value for the entity: its own figure, or the municipality's (inherited, °) for postal codes */
function eVal(e, k, y) { const own = V(e.o, k, y); if (own != null) return { v: own, own: true }; if (e.type === "postnr" && e.muni) { const mv = V(e.muni, k, y); if (mv != null) return { v: mv, own: false }; } return { v: null, own: false }; }
function eYears(e, k) { return yearsForPool(k, e.type === "postnr" && V(e.o, k) == null ? MUNI : e.peers); }
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
function tileHtml(e, i, on) {
  const cur = eVal(e, i.key); if (cur.v == null) return "";
  const ys = eYears(e, i.key), y0 = ys[0];
  const own = ys.map(y => eVal(e, i.key, y).v), med = ys.map(y => median(e.peers.map(p => V(p, i.key, y))));
  const dlt = (a, b) => a == null || b == null ? null : isPct(i) ? b - a : (a ? (b / a - 1) * 100 : null);
  const unit = isPct(i) ? " pp" : " %";
  const idx = ys.indexOf(MK.year); const yoy = idx > 0 ? dlt(own[idx - 1], cur.v) : null;
  const since = y0 && y0 !== MK.year ? dlt(own[0], cur.v) : null;
  const medNow = median(e.peers.map(p => V(p, i.key))); const vsMed = dlt(medNow, cur.v);
  const rk = cur.own ? rankOf(e.o, i.key, e.peers) : null; const pct = rk ? (rk.n > 1 ? 1 - (rk.r - 1) / (rk.n - 1) : 1) : null;
  const cls = d => d > 0 ? "up" : d < 0 ? "dn" : "";
  return `<div class="tile ${on ? "on" : ""}" data-arind="${esc(i.key)}" title="${esc(i.desc || i.label)} — click to focus the chart and map">
    <span class="tl">${esc(i.label)}${cur.own ? "" : " °"}</span>
    <div class="tv"><b>${fmtOf(i)(cur.v)}</b>${yoy != null ? `<i class="${cls(yoy)}">${sign(yoy, x => nf(x, 1))}${unit} y/y</i>` : ""}</div>
    ${tileSpark(ys, own, med, i)}
    <div class="tm">${rk ? `<span class="rk"><em class="rkbar"><i style="left:${(pct * 100).toFixed(0)}%"></i></em>#${rk.r} of ${rk.n}</span>` : `<span class="rk dim">municipality value</span>`}
      <span>${since != null ? `<i class="${cls(since)}">${sign(since, x => nf(x, 1))}${unit}</i> since ${y0}` : ""}</span>
      <span>${vsMed != null ? `<i class="${cls(vsMed)}">${sign(vsMed, x => nf(x, 1))}${unit}</i> vs median` : ""}</span></div>
  </div>`;
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
      ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(y(t) + 3).toFixed(1)}" text-anchor="end">${fmtOf(ind)(t)}</text>`).join("")}
      ${ys.map((yy, i) => `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${yy}</text>`).join("")}
      ${selX}${paths}</svg>
    <div class="bleg">${series.map(s => `<span><i style="background:${s.color}${s.dash ? ";height:2px" : ""}"></i>${esc(s.name)}${s.pts[s.pts.length - 1].v != null ? ` <b>${fmtOf(ind)(s.pts[s.pts.length - 1].v)}</b>` : ""}</span>`).join("")}</div>`;
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
      return `<tr class="clickrow ${i.key === ind.key ? "hi" : ""}" data-arind="${esc(i.key)}"><th>${esc(i.label)} <span class="dim">${esc(i.unit || "")}</span></th>
        ${fmtCell(i, cur.v, !cur.own)}${e.muni ? (muniCmp(e, i.key) ? fmtCell(i, V(e.muni, i.key), false) : `<td class="num dim" title="different definition at municipality level">n/c</td>`) : ""}${fmtCell(i, med, false)}
        <td class="num" data-v="${rk ? rk.r : ""}">${rk ? `#${rk.r} / ${rk.n}` : "–"}</td>
        <td class="num ${d > 0 ? "good" : d < 0 ? "bad" : ""}" data-v="${d ?? ""}">${d != null ? sign(d, x => nf(x, 1)) + (isPct(i) ? " pp" : " %") + ` <span class="dim">(${y0})</span>` : "–"}</td>
        <td class="dim">${asofText(i)}</td></tr>`; }).join("")}</tbody></table></div>`;
}
function areaSubTable(e) {
  if (!e.subs) return "";
  const keys = Object.keys(e.subs); const sub = keys.includes(AR.sub) ? AR.sub : keys[0]; const list = e.subs[sub];
  const cols = sub === "kvarter" ? IND_CPH : IND.filter(i => i.level === "postnr");
  const ind = cols.find(i => i.key === MK.ind) || cols[0];
  const pool = sub === "kvarter" ? CPH.areas : AREAS, y0 = yearsForPool(ind.key, pool)[0];
  const rows = list.slice().sort((a, b) => (V(b, ind.key) ?? -1e9) - (V(a, ind.key) ?? -1e9));
  return `<div class="card">
    <div class="card-head"><h3>${esc(e.name)} by ${sub === "kvarter" ? "quarter" : "postal code"}</h3>
      <div class="tools">${keys.length > 1 ? `<div class="seg">${keys.map(k => `<button class="sg ${k === sub ? "on" : ""}" data-arsub="${k}">${k === "kvarter" ? `Quarters (${e.subs[k].length})` : `Postal codes (${e.subs[k].length})`}</button>`).join("")}</div>` : ""}<span class="hint">sorted by ${esc(ind.label.toLowerCase())} · click a row for its page</span></div></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th>${sub === "kvarter" ? "Quarter" : "Area"}</th><th>${sub === "kvarter" ? "District" : "Postal code"}</th><th class="num">Population</th>
      <th class="num hi">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${isPct(ind) ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
    <tbody>${rows.map(a => `<tr class="clickrow" data-go="${withQ(pageOf(a))}"><th>${esc(a.name)} <span class="go">›</span></th><td class="dim">${esc(sub === "kvarter" ? a.bydel || "" : a.nr)}</td><td class="num dim" data-v="${a.pop || 0}">${a.pop != null ? nf(a.pop, 0) : "–"}</td>
      ${fmtCell(ind, V(a, ind.key), false)}${y0 && y0 !== MK.year ? deltaCell(a, ind, pool) : ""}${cols.filter(i => i.key !== ind.key).map(i => fmtCell(i, V(a, i.key), false)).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="cap">${sub === "kvarter" ? `${list.length} quarters (kvarterer). ${esc((CPH.meta && CPH.meta.attribution) || "")}` : `${list.length} postal-code areas; only postal-code-level indicators are listed — the rest take the municipality value (see the comparison table).`}</p>
  </div>`;
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
  return `<div class="card">
    <div class="card-head"><h3>Housing stock — BBR register</h3><span class="hint">${nf(b.n, 0)} dwellings in ${nf(b.n_bld, 0)} buildings${ref ? ` · tick = ${esc(e.muni.name)}` : ""}</span></div>
    <div class="bbrgrid">${BBR_DIST.map(block).join("")}</div>
    <p class="cap">Source: BBR (Bygnings- og Boligregistret) via Datafordeler, current dwellings (status 6, boligtype 1–5) placed by their building's coordinate. Register data as reported by owners.</p>
  </div>`;
}
function vArea() {
  const e = areaEntity();
  if (!e) return `<div class="back"><button data-go="map">‹ Macro map</button></div><div class="card"><p class="empty">Unknown area.</p></div>`;
  const ind = curInd();
  setTimeout(arMapInit, 0);
  const groups = ["key"].concat(GROUP_ORDER.filter(gn => e.inds.some(i => (i.group || "Other") === gn && eVal(e, i.key).v != null)));
  const grp = groups.includes(AR.group) ? AR.group : "key";
  const tiles = (grp === "key" ? KEY_INDS.map(k => e.inds.find(i => i.key === k)).filter(i => i && eVal(e, i.key).v != null).slice(0, MAX_TILES) : e.inds.filter(i => (i.group || "Other") === grp));
  const glabel = g => g === "key" ? "All figures" : g;
  const mapHash = e.type === "kommune" ? `map/${e.code}` : e.type === "kvarter" ? `map/${CPH_MUNI}` : `map/${e.o.muni}/postnr`;
  return `
  <div class="back"><button data-go="${withQ(mapHash)}">‹ Back to the map</button> <span class="dim"> · </span> <button data-go="table/${e.type}?ind=${MK.ind}">Table</button>${e.muni ? ` <span class="dim"> · </span> <button data-go="${withQ(pageOf(e.muni))}">${esc(e.muni.name)} page</button>` : ""}</div>
  <div class="card accent arhead">
    <div class="arid">
      <div class="crumb">${crumbText(e)}</div>
      <h2>${esc(e.name)}</h2>
      <div class="artags"><span class="tag">${esc(e.typeLabel)}</span><span class="tag">code ${esc(e.code)}</span>${e.o.pop != null ? `<span class="tag">${nf(e.o.pop, 0)} inhabitants</span>` : ""}${e.type === "kommune" ? `<span class="tag">${e.ctx.length} postal codes</span>` : ""}${e.type === "postnr" && e.o.codes && e.o.codes.length > 1 ? `<span class="tag">merged codes ${esc(e.o.codes.join(", "))}</span>` : ""}</div>
    </div>
    <div class="tools">${yearSelect()}<button class="lk" data-go="${withQ(mapHash)}">Show on map</button>${microAvail(e.type === "kommune" ? e.code : e.type === "kvarter" ? CPH_MUNI : e.o.muni) ? `<button class="lk primary" data-go="map/${e.type === "kommune" ? e.code : e.type === "kvarter" ? CPH_MUNI : e.o.muni}?ind=${MK.ind}&micro=1&mind=${MK.mind}">Buildings map ›</button>` : ""}</div>
  </div>
  <div class="card">
    <div class="card-head"><h3>Key figures${MK.year !== LATEST ? " · " + MK.year : ""}</h3><span class="hint">solid = ${esc(e.name)} · dashed = median of ${e.peerLabel} · hover a line for values</span>
      <div class="seg">${groups.map(g => `<button class="sg ${g === grp ? "on" : ""}" data-argroup="${esc(g)}">${esc(glabel(g))}</button>`).join("")}</div></div>
    <div class="hero wrap">${tiles.map(i => tileHtml(e, i, i.key === ind.key)).join("") || `<div><span>no data</span></div>`}</div>
    <p class="cap">y/y = change from the previous year; "since ${YEARS[0]}" = change over the whole series; "vs median" = against the median of ${e.peerLabel} (pp for shares, % otherwise). Rank bar: position among ${e.peerLabel}, right = highest value.${e.type === "kvarter" ? " n/c = not comparable: the municipality figure uses a different definition (national tables)." : ""} ° = municipality value (no ${e.type === "postnr" ? "postal-code" : "finer"} statistic). Click a tile to focus the chart and map on it.</p>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-head"><h3>Trend — ${esc(ind.label)}</h3><span class="hint">${esc(ind.unit || "")} · same sub-period each year</span></div>
      ${areaChart(e, ind)}
      <p class="cap">${esc(ind.desc || "")} <span class="dim">${esc(ind.source || "")}</span>${ind.warn ? `<br>⚠ ${esc(ind.warn)}` : ""}</p>
    </div>
    <div class="card">
      <div class="card-head"><h3>${esc(ind.short || ind.label)} — ${(() => { const mm = arMapMode(e, ind); return e.type === "kommune" ? (mm.kommuneLevel ? esc(e.name) + " among municipalities" : esc(e.name) + " by " + (mm.useQ ? "quarter" : "postal code")) : "neighbours"; })()}</h3><span class="hint">${(() => { const mm = arMapMode(e, ind); return mm.kommuneLevel ? "municipality-level indicator · click a neighbour to open it" : e.type === "kommune" ? "click an area to open it" : "click a neighbour to open it"; })()}</span></div>
      <div id="armap"></div>
      <div class="mklegend"><span>low</span><span id="aglo" class="lgv"></span>${[0, .25, .5, .75, 1].map(x => `<i style="background:${mkShade(x, ind.key)}"></i>`).join("")}<span id="aghi" class="lgv"></span><span>high</span></div>
    </div>
  </div>
  <div class="card">
    <div class="card-head"><h3>All indicators — ${esc(e.name)} in context</h3><span class="hint">click a row to focus the chart</span></div>
    ${areaCompareTable(e)}
  </div>
  ${bbrCard(e)}
  ${areaSubTable(e)}
  ${srcNote()}`;
}
function arMapMode(e, ind) {
  /* what the small map shows: Copenhagen quarters, the municipality's postal codes, or (for a municipality-level
     indicator on a municipality page) the municipality among all others */
  const useQ = e.type === "kvarter" || (e.type === "kommune" && e.subs && e.subs.kvarter && AR.sub !== "postnr");
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
  const lo = document.getElementById("aglo"), hi = document.getElementById("aghi");
  if (lo && hi && sind) { lo.textContent = sc.lo != null ? fmtOf(sind)(sc.lo) : ""; hi.textContent = sc.hi != null ? fmtOf(sind)(sc.hi) : ""; }
  const b = boundsOf(own); if (b) map.fitBounds(b, { padding: kommuneLevel ? [90, 90] : e.type === "kommune" ? [10, 10] : [70, 70], maxZoom: kommuneLevel ? 9 : 13 });
}

/* ---------- Leaflet layers (macro map) ---------- */
function lfPopup(a, muni) {
  const row = (i, v, own) => `<span class="lfrow"><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(v)}${own ? "" : " °"}</b></span>`;
  const LI = curInds();
  const native = LI.filter(i => V(a, i.key) != null).map(i => row(i, V(a, i.key), true)).join("");
  const inherited = LI.filter(i => V(a, i.key) == null && muni && V(muni, i.key) != null).map(i => row(i, V(muni, i.key), false)).join("");
  return `<div class="lfpop"><b>${esc(a.nr || a.code)} ${esc(a.name)}</b>${MK.year !== LATEST ? ` <span class="tag">${MK.year}</span>` : ""}
    <span class="dim">${a.bydel ? esc(a.bydel) + " · " : ""}${muni ? esc(muni.name) : ""}${a.pop != null ? " · " + nf(a.pop, 0) + " inhabitants" : ""}</span>
    <span class="lfact"><button class="lk mini primary" data-go="${withQ(pageOf(a))}">${a.bydel ? "Quarter" : "Postal code"} page ›</button>${muni ? `<button class="lk mini" data-go="${withQ(pageOf(muni))}">${esc(muni.name)} ›</button>` : ""}${!MK.muni && muni ? `<button class="lk mini" data-go="map/${muni.code}?ind=${MK.ind}">Zoom in</button>` : ""}</span>
    ${native ? `<span class="lfsec">${a.bydel ? "Quarter" : "Postal code"}</span>${native}` : ""}
    ${inherited ? `<span class="lfsec">Municipality °</span>${inherited}` : ""}</div>`;
}
function lfLabels() {
  /* labels are rebuilt on every zoom step: a name is shown only when its polygon is wide enough on screen */
  if (!LF.map || !LF.ctx) return;
  const { areas, munis, sc, micro, ind, vk } = LF.ctx; const zoom = LF.map.getZoom(); const labs = [];
  if (LF.labG) LF.map.removeLayer(LF.labG);
  if (MK.muni || zoom >= MICRO_ZOOM) {
    const px = ring => { const xs = [], ys = []; ring.forEach(q => { const c = LF.map.latLngToContainerPoint(q); xs.push(c.x); ys.push(c.y); }); return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)]; };
    areas.slice().sort((x, y) => (y.pop || 0) - (x.pop || 0)).slice(0, 60).forEach(a => {
      const [w, h] = px(mainRing(a)); if (w < 44 || h < 20) return;
      const m = byCode[a.muni]; const own = micro && vk(a) != null; const v = own ? vk(a) : (m ? vk(m) : null);
      const t = sc.t(v), dark = t != null && t > .55; const val = v != null ? fmtOf(ind)(v) + (own ? "" : " °") : "–";
      const name = w >= 96 && h >= 30 ? `<b>${esc(a.name)}</b><br>` : "";
      labs.push(L.marker(centroid(mainRing(a)), { interactive: false, icon: L.divIcon({ className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null, html: name + val }) }));
    });
  } else {
    munis.forEach(m => {
      const ma = muniAreas(m.code); let x = 0, y = 0, w = 0;
      ma.forEach(a => { const c = centroid(mainRing(a)); const ww = a.pop || 1; x += c[0] * ww; y += c[1] * ww; w += ww; });
      if (!w) return;
      const t = sc.t(vk(m)), dark = t != null && t > .55;
      if (zoom < 8 && (m.pop || 0) < 90000) return; /* declutter at national zoom */
      labs.push(L.marker([x / w, y / w], { interactive: false, icon: L.divIcon({ className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null, html: `<b>${esc(m.name)}</b><br>${vk(m) != null ? fmtOf(ind)(vk(m)) : "–"}` }) }));
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
  return `<div class="indx">
    <div class="indx-head"><b>${esc(i.label)} — buildings</b><span class="tag">building level</span><span class="tag">${esc(i.unit)}</span></div>
    <p>${{ rented_pct: "Dwellings registered as rented (incl. andel) as % of the building's dwellings with a known tenure.", vacant_pct: "Dwellings registered as 'not in use' as % of the building's dwellings — owner-reported, lags.",
      avg_m2: "Mean registered dwelling area in the building.", year: "Year of commissioning (byg026).", dwellings: "Number of current dwellings (boligtype 1–5) in the building.",
      small_pct: "Dwellings under 50 m² as % of the building's dwellings.", floors: "Number of floors (byg054)." }[i.key]}</p>
    <p class="dim"><em>Source</em> BBR via Datafordeler, buildings with ≥ ${idx.min_dwellings || (D.micro && D.micro.min_dwellings) || 2} dwellings · <em>Coverage</em> ${nf(idx.n || 0, 0)} buildings in ${esc(m ? m.name : "")} · <em>As of</em> ${esc((D.micro && D.micro.built) || "")}</p>
    <div class="tfilters mfilters">
      <label class="hint">min. dwellings <input id="mf-mindw" type="number" min="1" step="1" value="${MF.minDw}" style="width:60px"></label>
      <label class="hint">built <input id="mf-yfrom" type="number" placeholder="from" value="${esc(MF.yFrom)}" style="width:64px"> – <input id="mf-yto" type="number" placeholder="to" value="${esc(MF.yTo)}" style="width:64px"></label>
      <select id="mf-type" class="indsel"><option value="">All building types</option>${Object.entries(MTYPE).map(([k, v]) => `<option value="${k}" ${MF.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
      <label class="hint">rented ≥ <input id="mf-rent" type="number" min="0" max="100" step="5" value="${MF.rentMin}" style="width:56px"> %</label>
      <span class="hint" id="mcount"></span>
      <button class="lk mini" data-mcsv>⤓ Export buildings CSV</button>
    </div>
  </div>`;
}
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
  return `<div class="lfpop"><b>${esc(MTYPE[r[8]] || "building")} · ${r[2]} dwellings</b><span class="dim">${m ? esc(m.name) : ""} · ${r[0]}, ${r[1]} · BBR ${esc(r[14])}…</span>
    <span class="lfsec">Building</span>${row("Built", r[6] ?? "–")}${row("Floors", r[7] ?? "–")}${row("Dwellings", r[2])}
    <span class="lfsec">Dwellings</span>${row("Rented (incl. andel)", r[3] != null ? r[3] + " %" : "–")}${row("Unoccupied", r[4] != null ? r[4] + " %" : "–")}${row("Ø size", r[5] != null ? r[5] + " m²" : "–")}${row("< 50 m²", r[13] != null ? r[13] + " %" : "–")}
    ${rt ? row("Rooms 1 / 2 / 3 / 4+", rooms.map(x => nf(x / rt * 100, 0) + "%").join(" / ")) : ""}
    <span class="lfact"><a class="lk mini" target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${r[0]}&mlon=${r[1]}#map=18/${r[0]}/${r[1]}">Open in OpenStreetMap</a></span></div>`;
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
  const vals = rows.map(r => r[c]).filter(v => v != null);
  /* colour scale on the 5th–95th percentile so a few outliers do not flatten the ramp */
  const sorted = vals.slice().sort((a, b) => a - b); const lo = sorted[Math.floor(sorted.length * .05)] ?? null, hi = sorted[Math.floor(sorted.length * .95)] ?? null;
  const t = v => v == null || lo == null ? null : hi > lo ? Math.max(0, Math.min(1, (v - lo) / (hi - lo))) : .5;
  if (!LF.canvas) LF.canvas = L.canvas({ padding: .3 });
  const marks = rows.map(r => { const tt = t(r[c]);
    const m = L.circleMarker([r[0], r[1]], { renderer: LF.canvas, radius: microRadius(r[2]), color: "#141C18", weight: .6, opacity: .7, fillColor: tt == null ? "#C4CBC4" : mkShade(tt, "micro:" + ind.key), fillOpacity: .85 });
    m._dw = r[2]; m.bindPopup(() => microPopup(r), { maxWidth: 300, autoPanPadding: [24, 24] }); return m; });
  LF.microG = L.layerGroup(marks).addTo(LF.map); LF.microMarks = marks;
  const lg = document.getElementById("lglo"), hg = document.getElementById("lghi");
  if (lg && hg) { lg.textContent = lo != null ? fmtOf(ind)(lo) : ""; hg.textContent = hi != null ? fmtOf(ind)(hi) : ""; }
  if (cnt) cnt.textContent = `${nf(rows.length, 0)} of ${nf(d.meta.n, 0)} buildings · ${nf(rows.reduce((s_, r) => s_ + r[2], 0), 0)} dwellings shown`;
}
function lfLayers() {
  if (LF.map && microMode()) { lfMicroLayers(); return; }
  if (LF.microG && LF.map) { LF.map.removeLayer(LF.microG); LF.microG = null; }
  if (!LF.map) return;
  const zoom = LF.map.getZoom();
  const ind = curInd();
  /* a drilled-in municipality always shows its sub-areas, whatever the zoom (small screens fit it below zoom 10) */
  const fine = !!MK.muni || zoom >= MICRO_ZOOM;
  const micro = fine && (cphMode() || ind.level === "postnr");
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
    p.bindPopup(() => lfPopup(a, m), { maxWidth: 300, maxHeight: 360, autoPanPadding: [24, 24] });
    p.on("mouseover", () => p.setStyle({ weight: 2.2, color: "#141C18" })); p.on("mouseout", () => p.setStyle({ weight: w, color: "#FFFFFF" }));
    polys.push(p);
  });
  LF.areaG = L.layerGroup(polys).addTo(LF.map);
  LF.ctx = { areas, munis, sc, micro, ind, vk };
  lfLabels();
  const lo = document.getElementById("lglo"), hi = document.getElementById("lghi");
  if (lo && hi) { lo.textContent = sc.lo != null ? fmtOf(ind)(sc.lo) : ""; hi.textContent = sc.hi != null ? fmtOf(ind)(sc.hi) : ""; }
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
  map.on("popupopen", ev => { const el = ev.popup.getElement(); if (el) el.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go))); });
  map.on("zoomend", () => {
    /* rebuild polygons only when the display level changes — rebuilding on every pan would kill open popups */
    if (microMode()) { (LF.microMarks || []).forEach(m => m.setRadius(microRadius(m._dw))); return; }
    const z = map.getZoom(), fine = !!MK.muni || z >= MICRO_ZOOM, lvl = (fine ? "micro" : z < 8 ? "national" : "macro") + (cphMode() ? "-cph" : "") + (MK.muni || "");
    if (lvl !== LF.level) lfLayers(); else if (fine) lfLabels();
  });
  lfLayers();
  applyPendingFit();
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
    <p class="cap">${esc(mac.note || "")}</p></div>`;
}

/* ---------- Sources view ---------- */
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
