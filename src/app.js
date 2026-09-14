/* AM Dashboard — Denmark Edition · app.js
   Design and interaction model ported from the Finnish edition; all data comes
   from window.DATA (built by scripts/build_dashboard.py from data/processed/*.json).

   DATA schema (see docs/DATA_MAP.md §4 and scripts/build_makro.py):
     meta          { built, sources:[{key,label,url,asof}], attribution:[...], note }
     indicators    [ {key,label,short,unit,level:"kommune"|"postnr",hue:[r,g,b],fmt,desc,source,warn,table_only} ]
     municipalities[ {code,name,pop, <indicator keys>..., asof:{key:period}} ]
     areas         [ {nr,name,muni,rings:[[[lat,lon],...],...],pop, <postnr-level keys>...} ]
     macro         { series:{key:[{t,v}]}, latest:{key:{t,v,label,unit,yoy}}, note }
     portfolio     null | { properties:[{name,address,muni,nr,lat,lon,units,vac,notice}] }
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
const byCode = {}; MUNI.forEach(m => byCode[m.code] = m);
const S = { view: "makro", win: 0 };
const MK = { ind: (IND[0] || {}).key, muni: null, own: false, sortKey: null, sortDir: -1 };
const LF = { map: null, center: [56.0, 10.5], zoom: 7 };
const MICRO_ZOOM = 10;

/* ---------- views & navigation ---------- */
const VIEWS = [
  ["makro",   "Macro map",     "Demographics, income, housing and prices by municipality and postal code"],
  ["market",  "Market",        "Prices, rents, supply, construction and macro indicators"],
  ["sources", "Sources",       "Data sources, freshness and definitions"]];
const NAV_GROUPS = [["Market intelligence", ["makro", "market", "sources"]]];
const viewOf = id => VIEWS.find(v => v[0] === id) || VIEWS[0];

function renderNav() {
  document.getElementById("nav").innerHTML = NAV_GROUPS.map(([lab, ids]) => `<div class="nav-glab">${lab}</div>` +
    ids.map(id => { const v = viewOf(id); return `<button class="nav-item ${S.view === id ? "on" : ""}" data-view="${id}"><b>${v[1]}</b><em>${v[2]}</em></button>`; }).join("")).join("");
  const built = D.meta && D.meta.built ? D.meta.built : "no data";
  document.getElementById("brandsub").textContent = `Denmark · open data · built ${built}`;
}
function renderTop() {
  const v = viewOf(S.view);
  document.getElementById("hd").innerHTML = `<h1>${v[1]}</h1><p class="dim">${v[2]}</p>`;
}
const RENDER = { makro: vMakro, market: vMarket, sources: vSources };
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
  if ((el = g("[data-view]"))) { S.view = el.dataset.view; MK.muni = null; render(); return; }
  if ((el = g("[data-mkind]"))) { MK.ind = el.dataset.mkind; renderKeep(); return; }
  if (g("[data-mkown]")) { MK.own = !MK.own; renderKeep(); return; }
  if (g("[data-mkback]")) { MK.muni = null; renderKeep(); return; }
  if ((el = g("[data-mkmuni]"))) { MK.muni = el.dataset.mkmuni; zoomToMuni(MK.muni); renderKeep(); return; }
  if ((el = g(".im"))) { tipToggle(el); return; }
  tipHide();
});

/* ---------- info tooltips (ⓘ) ---------- */
let TIPEL = null, TIPFOR = null;
const M = key => IND.find(i => i.key === key) ? `<i class="im" data-m="${key}" tabindex="0" aria-label="How is this computed">i</i>` : "";
function tipToggle(el) { if (TIPFOR === el) { tipHide(); return; } tipShow(el); }
function tipShow(el) {
  const i = IND.find(x => x.key === el.dataset.m); if (!i) return;
  if (!TIPEL) { TIPEL = document.createElement("div"); TIPEL.className = "imtip"; document.body.appendChild(TIPEL); }
  TIPEL.innerHTML = `<b>${esc(i.label)}</b><p><em>Definition</em>${esc(i.desc || "")}</p>` +
    (i.source ? `<p><em>Source</em>${esc(i.source)}</p>` : "") +
    (i.warn ? `<p class="warn"><em>Caveat</em>${esc(i.warn)}</p>` : "");
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
        const val = r => { const c = r.cells[idx]; const v = parseFloat((c.dataset.v ?? c.textContent).replace(/\s/g, "").replace(",", ".")); return isNaN(v) ? null : v; };
        rows.sort((a, b) => { const x = val(a), y = val(b); if (x == null && y == null) return a.cells[idx].textContent.localeCompare(b.cells[idx].textContent); if (x == null) return 1; if (y == null) return -1; return (x - y) * dir; });
        rows.forEach(r => tb.appendChild(r));
      });
    });
  });
}

/* ---------- choropleth colour model (identical to the Finnish edition) ---------- */
function mkShade(t, key) {
  const i = IND.find(x => x.key === key); const hue = (i && i.hue) || [10, 88, 70];
  const a = [239, 242, 238]; const c = a.map((x, k) => Math.round(x + (hue[k] - x) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
function mkScale(list, key) {
  const vals = list.map(x => x[key]).filter(v => v != null && !isNaN(v));
  if (!vals.length) return { t: () => null, lo: null, hi: null };
  const lo = Math.min(...vals), hi = Math.max(...vals);
  return { t: v => v == null || isNaN(v) ? null : (hi > lo ? (v - lo) / (hi - lo) : .5), lo, hi };
}
const curInd = () => IND.find(i => i.key === MK.ind) || IND[0] || { key: "", label: "", fmt: "pct1" };
const chips = () => `<div class="seg">${IND.filter(i => !i.table_only).map(i =>
  `<button class="sg ${MK.ind === i.key ? "on" : ""}" data-mkind="${i.key}" title="${esc(i.label)}${i.unit ? ", " + esc(i.unit) : ""}${i.level === "postnr" ? " · postal-code level" : " · municipality level"}">${esc(i.short || i.label)}</button>`).join("")}</div>`;

/* geometry helpers: largest ring, centroid, bounds */
const mainRing = a => (a.rings || []).slice().sort((x, y) => y.length - x.length)[0] || [];
const centroid = ring => ring.reduce((o, p) => [o[0] + p[0] / ring.length, o[1] + p[1] / ring.length], [0, 0]);
function muniAreas(code) { return AREAS.filter(a => a.muni === code); }
function zoomToMuni(code) {
  if (!LF.map) return;
  const pts = []; muniAreas(code).forEach(a => (a.rings || []).forEach(r => r.forEach(p => pts.push(p))));
  if (pts.length) { LF.map.fitBounds(L.latLngBounds(pts), { padding: [12, 12] }); }
}

/* ---------- Macro map view ---------- */
function srcNote() {
  const s = (D.meta && D.meta.sources) || [];
  const list = s.map(x => `${esc(x.label)}${x.asof ? " (" + esc(x.asof) + ")" : ""}`).join(" · ");
  return `<div class="note"><b>Open data.</b> ${list || "no sources recorded"}.
    Municipality-level indicators are shown on postal-code polygons with the municipality value (marked °) when no finer statistic exists.
    ${esc((D.meta && D.meta.note) || "")}</div>`;
}
function vMakro() {
  if (!AREAS.length || !MUNI.length) return `<div class="card"><p class="empty">No macro data built yet — run <code>python scripts/fetch_statbank.py</code>, <code>python scripts/fetch_geo_dawa.py</code> and <code>python scripts/build_makro.py</code>, then <code>python scripts/build_dashboard.py</code>.</p></div>`;
  const ind = curInd();
  setTimeout(lfInit, 0);
  const legend = [0, .25, .5, .75, 1].map(x => `<i style="background:${mkShade(x, ind.key)}"></i>`).join("");
  const muni = MK.muni ? byCode[MK.muni] : null;
  return `
  ${muni ? `<div class="back"><button data-mkback>‹ All municipalities</button></div>` : ""}
  <div class="card accent">
    <div class="card-head"><h3>${muni ? esc(muni.name) + " — postal codes" : "Macro map"} ${M(ind.key)}</h3>
      <div class="tools">${D.portfolio ? `<button class="lk mini ${MK.own ? "primary" : ""}" data-mkown>● Own properties</button>` : ""}${chips()}</div></div>
    <div id="lfmap"></div>
    <div class="mklegend"><span>low</span>${legend}<span>high</span>
      <span class="dim">· ${esc(ind.label)}${ind.unit ? ", " + esc(ind.unit) : ""} · scaled to the visible level</span>
      <span style="margin-left:auto" class="dim">${ind.level === "postnr" ? "zoom in → postal-code values" : "municipality-level indicator — postal codes take the municipality value"}</span></div>
    ${srcNote()}
    <p class="cap">Boundaries: DAGI, Klimadatastyrelsen (simplified). Basemap loads from the network (CARTO / OpenStreetMap). Click a polygon for all its indicators.</p>
  </div>
  ${muni ? areaTable(muni) : muniTable()}`;
}
function fmtCell(i, v, fallback) {
  if (v == null || isNaN(v)) return `<td class="num">–</td>`;
  return `<td class="num" data-v="${v}">${fmtOf(i)(v)}${fallback ? " °" : ""}</td>`;
}
function muniTable() {
  const ind = curInd();
  const cols = IND;
  const rows = MUNI.slice().sort((a, b) => (b[ind.key] ?? -1e9) - (a[ind.key] ?? -1e9));
  const port = D.portfolio && D.portfolio.properties;
  return `<div class="card">
    <div class="card-head"><h3>Municipalities compared</h3><span class="hint">sorted by ${esc(ind.label.toLowerCase())} · click a row to drill into postal codes</span></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th>Municipality</th><th class="num">Population</th>
      ${cols.map(i => `<th class="num ${i.key === ind.key ? "hi" : ""}">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}
      ${port ? `<th class="num">Properties</th><th class="num">Units</th>` : ""}</tr></thead>
    <tbody>${rows.map(m => {
      const ps = port ? port.filter(p => p.muni === m.code) : [];
      return `<tr class="clickrow" data-mkmuni="${esc(m.code)}"><th>${esc(m.name)}</th><td class="num dim" data-v="${m.pop || 0}">${m.pop != null ? nf(m.pop / 1000, 0) + " k" : "–"}</td>
        ${cols.map(i => fmtCell(i, m[i.key], false)).join("")}
        ${port ? `<td class="num">${ps.length || "–"}</td><td class="num">${ps.reduce((s, p) => s + (p.units || 0), 0) || "–"}</td>` : ""}</tr>`; }).join("")}</tbody></table></div>
    ${srcNote()}
  </div>`;
}
function areaTable(muni) {
  const ind = curInd();
  const areas = muniAreas(muni.code).slice().sort((a, b) => ((b[ind.key] ?? muni[ind.key]) ?? -1e9) - ((a[ind.key] ?? muni[ind.key]) ?? -1e9));
  const cols = IND;
  return `<div class="card">
    <div class="card-head"><h3>${esc(muni.name)} by postal code</h3><span class="hint">sorted by ${esc(ind.label.toLowerCase())} · ° = municipality value (no postal-code statistic)</span></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th>Area</th><th>Postal code</th><th class="num">Population</th>
      ${cols.map(i => `<th class="num ${i.key === ind.key ? "hi" : ""}">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
    <tbody>${areas.map(a => `<tr><th>${esc(a.name)}</th><td class="dim">${esc(a.nr)}</td><td class="num dim" data-v="${a.pop || 0}">${a.pop != null ? nf(a.pop, 0) : "–"}</td>
      ${cols.map(i => { const own = a[i.key]; return own != null ? fmtCell(i, own, false) : fmtCell(i, muni[i.key], true); }).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="cap">${areas.length} postal-code areas. Postal codes that span several municipalities are attributed to their dominant municipality.</p>
  </div>`;
}

/* ---------- Leaflet layers ---------- */
function lfPopup(a, muni) {
  const rows = IND.map(i => {
    const own = a[i.key] != null, v = own ? a[i.key] : (muni ? muni[i.key] : null);
    if (v == null) return "";
    return `<span style="display:flex;justify-content:space-between;gap:14px"><span>${esc(i.label)}</span><b>${fmtOf(i)(v)}${own ? "" : " °"}</b></span>`;
  }).join("");
  return `<div class="lfpop"><b>${esc(a.nr)} ${esc(a.name)}</b>
    <span class="dim">${muni ? esc(muni.name) : ""}${a.pop != null ? " · " + nf(a.pop, 0) + " inhabitants" : ""}</span>${rows}
    <span class="dim" style="font-size:10px">° = municipality value</span></div>`;
}
function lfLayers() {
  if (!LF.map) return;
  const zoom = LF.map.getZoom();
  const ind = curInd();
  const micro = zoom >= MICRO_ZOOM && ind.level === "postnr";
  if (LF.areaG) LF.map.removeLayer(LF.areaG);
  if (LF.labG) LF.map.removeLayer(LF.labG);
  const areas = MK.muni ? muniAreas(MK.muni) : AREAS;
  const munis = MK.muni ? [byCode[MK.muni]].filter(Boolean) : MUNI;
  const sc = micro ? mkScale(areas.filter(a => a[ind.key] != null), ind.key) : mkScale(munis, ind.key);
  const polys = [], labs = [];
  areas.forEach(a => {
    const m = byCode[a.muni];
    const src = micro && a[ind.key] != null ? a : m;
    const t = src ? sc.t(src[ind.key]) : null;
    const p = L.polygon(a.rings, { color: "#FFFFFF", weight: zoom >= MICRO_ZOOM ? 1.4 : 0.8,
      fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .72, smoothFactor: 1 });
    p.bindPopup(lfPopup(a, m));
    polys.push(p);
  });
  if (zoom >= MICRO_ZOOM) {
    const big = areas.slice().sort((x, y) => (y.pop || 0) - (x.pop || 0)).slice(0, 40);
    big.forEach(a => {
      const m = byCode[a.muni]; const own = micro && a[ind.key] != null; const v = own ? a[ind.key] : (m ? m[ind.key] : null);
      const t = sc.t(v), dark = t != null && t > .55;
      labs.push(L.marker(centroid(mainRing(a)), { interactive: false, icon: L.divIcon({
        className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null,
        html: `<b>${esc(a.name)}</b><br>${v != null ? fmtOf(ind)(v) + (own ? "" : " °") : "–"}` }) }));
    });
  } else {
    munis.forEach(m => {
      const ma = muniAreas(m.code); let x = 0, y = 0, w = 0;
      ma.forEach(a => { const c = centroid(mainRing(a)); const ww = a.pop || 1; x += c[0] * ww; y += c[1] * ww; w += ww; });
      if (!w) return;
      const t = sc.t(m[ind.key]), dark = t != null && t > .55;
      if (zoom < 8 && (m.pop || 0) < 60000) return; /* declutter at national zoom */
      labs.push(L.marker([x / w, y / w], { interactive: false, icon: L.divIcon({
        className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null,
        html: `<b>${esc(m.name)}</b><br>${m[ind.key] != null ? fmtOf(ind)(m[ind.key]) : "–"}` }) }));
    });
  }
  LF.areaG = L.layerGroup(polys).addTo(LF.map);
  LF.labG = L.layerGroup(labs).addTo(LF.map);
  if (LF.ownG) { LF.map.removeLayer(LF.ownG); LF.ownG = null; }
  if (MK.own && D.portfolio) {
    const marks = D.portfolio.properties.filter(p => p.lat != null).map(p => {
      const units = p.units || 20, pressure = ((p.vac || 0) + (p.notice || 0)) / Math.max(1, units);
      const m = L.circleMarker([p.lat, p.lon], { radius: Math.max(5, Math.min(11, Math.sqrt(units) * 1.15)), color: "#141C18", weight: 2,
        fillColor: pressure > .12 ? "#B5391F" : pressure > .06 ? "#D9A32E" : "#1C6B5C", fillOpacity: .92 });
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
  const map = L.map(el, { center: LF.center, zoom: LF.zoom, scrollWheelZoom: true });
  LF.map = map;
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", { maxZoom: 18, attribution: "© OpenStreetMap, © CARTO · Boundaries: DAGI, Klimadatastyrelsen" }).addTo(map);
  map.on("moveend zoomend", () => { const c = map.getCenter(); LF.center = [c.lat, c.lng]; LF.zoom = map.getZoom(); lfLayers(); });
  lfLayers();
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
  const W = 640, H = 180, L0 = 44, R = 10, T = 10, B = 24;
  const v = pts.map(p => p.v), lo = opts.zero ? 0 : Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  const x = i => L0 + i / (pts.length - 1) * (W - L0 - R), y = val => T + (1 - (val - lo) / sp) * (H - T - B);
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
  const s = (D.meta && D.meta.sources) || [];
  return `<div class="card"><div class="card-head"><h3>Data sources and freshness</h3><span class="hint">built ${esc((D.meta && D.meta.built) || "–")}</span></div>
    <table class="tbl compact"><thead><tr><th>Source</th><th>Tables / files</th><th>As of</th><th>Fetched</th><th>Licence</th></tr></thead>
    <tbody>${s.map(x => `<tr><th>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>` : esc(x.label)}</th><td class="dim">${esc(x.tables || "")}</td><td>${esc(x.asof || "")}</td><td class="dim">${esc(x.fetched || "")}</td><td class="dim">${esc(x.licence || "")}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">no sources recorded</td></tr>`}</tbody></table>
    <p class="cap">${((D.meta && D.meta.attribution) || []).map(esc).join(" · ")}</p></div>
  <div class="card"><div class="card-head"><h3>Indicator definitions</h3></div>
    <table class="tbl compact"><thead><tr><th>Indicator</th><th>Unit</th><th>Level</th><th>Definition</th><th>Source</th><th>Caveat</th></tr></thead>
    <tbody>${IND.map(i => `<tr><th>${esc(i.label)}</th><td class="dim">${esc(i.unit || "")}</td><td class="dim">${esc(i.level)}</td><td>${esc(i.desc || "")}</td><td class="dim">${esc(i.source || "")}</td><td class="dim">${esc(i.warn || "")}</td></tr>`).join("")}</tbody></table></div>`;
}

render();
