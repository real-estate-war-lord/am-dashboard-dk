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
const YEARS = (D.meta && D.meta.years) || [];
const LATEST = (D.meta && D.meta.latest_year) || (YEARS[YEARS.length - 1] || "");
const MK = { ind: (IND[0] || {}).key, muni: null, own: false, mode: "map", year: LATEST, pins: [] };
/* value of indicator k for municipality/area o in the selected year (latest = live field, else history) */
const V = (o, k, y) => { const yr = y || MK.year; if (!o) return null; if (!yr || yr === LATEST) return o[k] ?? null; const h = o.hist && o.hist[k]; return h && h[yr] != null ? h[yr] : null; };
const yearsFor = k => YEARS.filter(y => y === LATEST || MUNI.some(m => m.hist && m.hist[k] && m.hist[k][y] != null));
const T = { q: "", level: "kommune", region: "", minPop: 0 };   /* table-mode filters */
const REGIONS = ["Hovedstaden", "Sjælland", "Syddanmark", "Midtjylland", "Nordjylland"];
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
  if ((el = g("[data-mkmode]"))) { MK.mode = el.dataset.mkmode; renderKeep(); return; }
  if ((el = g("[data-tlevel]"))) { T.level = el.dataset.tlevel; renderKeep(); return; }
  if (g("[data-csv]")) { exportCsv(); return; }
  if (g("[data-mkown]")) { MK.own = !MK.own; renderKeep(); return; }
  if (g("[data-mkback]")) { MK.muni = null; renderKeep(); return; }
  if ((el = g("[data-pin]"))) { const c = el.dataset.pin; MK.pins = MK.pins.includes(c) ? MK.pins.filter(x => x !== c) : MK.pins.concat(c).slice(-6); renderKeep(); return; }
  if ((el = g("[data-mkmuni]"))) { MK.muni = el.dataset.mkmuni; zoomToMuni(MK.muni); renderKeep(); return; }
  if ((el = g(".im"))) { tipToggle(el); return; }
  tipHide();
});

document.addEventListener("change", e => {
  const el = e.target;
  if (el.id === "indsel") { MK.ind = el.value; if (!yearsFor(MK.ind).includes(MK.year)) MK.year = LATEST; renderKeep(); }
  if (el.id === "yearsel") { MK.year = el.value; renderKeep(); }
  if (el.id === "tregion") { T.region = el.value; renderTableBody(); }
  if (el.id === "tminpop") { T.minPop = Number(el.value) || 0; renderTableBody(); }
});
document.addEventListener("input", e => {
  if (e.target.id === "tq") { T.q = e.target.value.trim().toLowerCase(); renderTableBody(); }
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
const GROUP_ORDER = ["Demographics", "Income & jobs", "Housing stock", "Rents", "Prices & market", "Construction"];
function indSelect() {
  const groups = GROUP_ORDER.filter(gname => IND.some(i => (i.group || "Other") === gname)).concat(IND.some(i => !GROUP_ORDER.includes(i.group || "Other")) ? ["Other"] : []);
  return `<select id="indsel" class="indsel" aria-label="Indicator">${groups.map(gname => `<optgroup label="${esc(gname)}">${IND.filter(i => (i.group || "Other") === gname).map(i =>
    `<option value="${i.key}" ${MK.ind === i.key ? "selected" : ""}>${esc(i.label)}${i.unit ? " · " + esc(i.unit) : ""}</option>`).join("")}</optgroup>`).join("")}</select>`;
}
function indExplain(i) {
  const asofSrc = (MK.year !== LATEST && i.hist_asof && i.hist_asof[MK.year]) ? i.hist_asof[MK.year] : i.asof;
  const asof = asofSrc ? Object.entries(asofSrc).map(([g, p]) => `${g === "postnr" ? "postal codes" : "municipalities"}: ${esc(p)}`).join(" · ") : "";
  const has = MUNI.filter(m => m[i.key] != null).length;
  return `<div class="indx">
    <div class="indx-head"><b>${esc(i.label)}</b><span class="tag">${i.level === "postnr" ? "postal-code level" : "municipality level"}</span><span class="tag">${esc(i.unit || "")}</span></div>
    <p>${esc(i.desc || "")}</p>
    <p class="dim"><em>Source</em> ${esc(i.source || "–")}${asof ? ` · <em>As of</em> ${asof}` : ""} · <em>Coverage</em> ${has}/${MUNI.length} municipalities${i.level === "postnr" ? `, ${AREAS.filter(a => a[i.key] != null).length}/${AREAS.length} postal codes` : ""}${yearsFor(i.key).length > 1 ? ` · <em>History</em> ${yearsFor(i.key)[0]}–${LATEST}` : ""}</p>
    ${i.warn ? `<p class="warnline">⚠ ${esc(i.warn)}</p>` : ""}
  </div>`;
}
function yearSelect() {
  const ys = yearsFor(MK.ind);
  if (ys.length < 2) return "";
  const hy = ys.filter(y => y !== LATEST); const lastHist = hy[hy.length - 1];
  /* the live value is always the newest available period; if the source lags (e.g. income 2024) say so */
  const label = y => y === LATEST ? (lastHist && lastHist !== LATEST && !MUNI.some(m => m.hist && m.hist[MK.ind] && m.hist[MK.ind][LATEST] != null) ? `latest (${lastHist} data)` : `${y} (latest)`) : y;
  return `<select id="yearsel" class="indsel" aria-label="Year">${ys.filter(y => !(y === lastHist && label(LATEST).startsWith("latest ("))).map(y => `<option value="${y}" ${MK.year === y ? "selected" : ""}>${label(y)}</option>`).join("")}</select>`;
}
const modeSeg = () => `<div class="seg"><button class="sg ${MK.mode === "map" ? "on" : ""}" data-mkmode="map">Map</button><button class="sg ${MK.mode === "table" ? "on" : ""}" data-mkmode="table">Table</button></div>`;

/* geometry helpers: largest ring, centroid, bounds */
const mainRing = a => (a.rings || []).slice().sort((x, y) => y.length - x.length)[0] || [];
const centroid = ring => ring.reduce((o, p) => [o[0] + p[0] / ring.length, o[1] + p[1] / ring.length], [0, 0]);
function muniAreas(code) { return AREAS.filter(a => a.muni === code); }
function zoomToMuni(code) { LF.pendingFit = code; }
function applyPendingFit() {
  if (!LF.map || !LF.pendingFit) return;
  const pts = []; muniAreas(LF.pendingFit).forEach(a => (a.rings || []).forEach(r => r.forEach(p => pts.push(p))));
  LF.pendingFit = null;
  if (pts.length) LF.map.fitBounds(L.latLngBounds(pts), { padding: [12, 12] });
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
  if (MK.mode === "table") return vTable(ind);
  setTimeout(lfInit, 0);
  const legend = [0, .25, .5, .75, 1].map(x => `<i style="background:${mkShade(x, ind.key)}"></i>`).join("");
  const muni = MK.muni ? byCode[MK.muni] : null;
  return `
  ${muni ? `<div class="back"><button data-mkback>‹ All municipalities</button></div>` : ""}
  <div class="card accent">
    <div class="card-head"><h3>${muni ? esc(muni.name) + " — postal codes" : "Macro map"}</h3>
      <div class="tools">${modeSeg()}${indSelect()}${yearSelect()}${D.portfolio ? `<button class="lk mini ${MK.own ? "primary" : ""}" data-mkown>● Own properties</button>` : ""}</div></div>
    ${indExplain(ind)}
    <div id="lfmap"></div>
    <div class="mklegend"><span>low</span>${legend}<span>high</span>
      <span class="dim">· ${esc(ind.label)}${ind.unit ? ", " + esc(ind.unit) : ""} · scaled to the visible level</span>
      <span style="margin-left:auto" class="dim">${ind.level === "postnr" ? "zoom in → postal-code values" : "municipality-level indicator — postal codes take the municipality value"}</span></div>
    ${srcNote()}
    <p class="cap">Boundaries: DAGI, Klimadatastyrelsen (simplified). Basemap loads from the network (CARTO / OpenStreetMap). Click a polygon for all its indicators.</p>
  </div>
  ${trendCard(ind)}
  ${muni ? areaTable(muni) : muniTable()}`;
}

/* ---------- Trend card: selected indicator over the years for pinned / largest municipalities ---------- */
const SERIES_COLORS = ["#1C6B5C", "#B07A1E", "#5C5F52", "#B0331B", "#40547F", "#82346C", "#6E8C5E"];
function trendCard(ind) {
  const ys = yearsFor(ind.key);
  if (ys.length < 2) return "";
  const pick = MK.pins.length ? MK.pins.map(c => byCode[c]).filter(Boolean)
    : (MK.muni && byCode[MK.muni] ? [byCode[MK.muni]] : MUNI.slice().sort((a, b) => (b.pop || 0) - (a.pop || 0)).slice(0, 5));
  const series = pick.map((m, k) => ({ name: m.name, code: m.code, color: SERIES_COLORS[k % SERIES_COLORS.length], pts: ys.map(y => ({ y, v: V(m, ind.key, y) })) }));
  const all = series.flatMap(s => s.pts.map(p => p.v)).filter(v => v != null);
  if (!all.length) return "";
  const W = 900, H = 220, L0 = 78, R = 16, T = 14, B = 26;
  const lo = Math.min(...all), hi = Math.max(...all), sp = (hi - lo) || 1;
  const x = i => L0 + i / (ys.length - 1) * (W - L0 - R), y = v => T + (1 - (v - lo) / sp) * (H - T - B);
  const ticks = [lo, lo + sp / 2, hi];
  const paths = series.map(s => { const pts = s.pts.map((p, i) => p.v == null ? null : `${x(i).toFixed(1)},${y(p.v).toFixed(1)}`); let d = "", open = false;
    pts.forEach(p => { if (!p) { open = false; return; } d += (open ? "L" : "M") + p; open = true; });
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>` + s.pts.map((p, i) => p.v == null ? "" : `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2.6" fill="${s.color}"><title>${esc(s.name)} ${p.y}: ${fmtOf(ind)(p.v)}</title></circle>`).join(""); }).join("");
  const selX = ys.indexOf(MK.year) >= 0 ? `<line x1="${x(ys.indexOf(MK.year)).toFixed(1)}" x2="${x(ys.indexOf(MK.year)).toFixed(1)}" y1="${T}" y2="${H - B}" class="splitline"/>` : "";
  return `<div class="card">
    <div class="card-head"><h3>Trend — ${esc(ind.label)}</h3><span class="hint">${ys[0]}–${ys[ys.length - 1]} · ${MK.pins.length ? "pinned municipalities (☆ in the table)" : MK.muni ? "selected municipality" : "five largest municipalities — pin others with ☆"}</span></div>
    <svg class="chart" viewBox="0 0 ${W} ${H}">
      ${ticks.map(t => `<line class="grid" x1="${L0}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/><text class="ax" x="${L0 - 6}" y="${(y(t) + 3).toFixed(1)}" text-anchor="end">${fmtOf(ind)(t)}</text>`).join("")}
      ${ys.map((yy, i) => `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${yy}</text>`).join("")}
      ${selX}${paths}</svg>
    <div class="bleg">${series.map(s => `<span><i style="display:inline-block;width:10px;height:10px;background:${s.color};margin-right:5px;border-radius:2px"></i>${esc(s.name)}${s.pts[s.pts.length - 1].v != null ? ` <b>${fmtOf(ind)(s.pts[s.pts.length - 1].v)}</b>` : ""}${MK.pins.includes(s.code) ? ` <button class="lk mini" data-pin="${esc(s.code)}">✕</button>` : ""}</span>`).join("")}</div>
    <p class="cap">Same sub-period each year (e.g. Q3 or July) so years compare like with like; rolling 4-quarter means for prices and days on market. Hover a point for the value.</p>
  </div>`;
}
function fmtCell(i, v, fallback) {
  if (v == null || isNaN(v)) return `<td class="num">–</td>`;
  return `<td class="num" data-v="${v}">${fmtOf(i)(v)}${fallback ? " °" : ""}</td>`;
}
const firstYear = k => yearsFor(k)[0];
function deltaCell(o, i) {
  const y0 = firstYear(i.key); if (!y0 || y0 === MK.year) return `<td class="num dim">–</td>`;
  const a = V(o, i.key, y0), b = V(o, i.key); if (a == null || b == null) return `<td class="num dim">–</td>`;
  const pct = i.fmt.startsWith("pct") || i.fmt === "signpct1";
  const d = pct ? b - a : (a ? (b / a - 1) * 100 : null); if (d == null) return `<td class="num dim">–</td>`;
  return `<td class="num ${d > 0 ? "good" : d < 0 ? "bad" : ""}" data-v="${d}">${sign(d, x => nf(x, 1))}${pct ? " pp" : " %"}</td>`;
}
function muniTable() {
  const ind = curInd();
  const cols = IND;
  const rows = MUNI.slice().sort((a, b) => (V(b, ind.key) ?? -1e9) - (V(a, ind.key) ?? -1e9));
  const port = D.portfolio && D.portfolio.properties;
  const y0 = firstYear(ind.key);
  return `<div class="card">
    <div class="card-head"><h3>Municipalities compared${MK.year !== LATEST ? " · " + MK.year : ""}</h3><span class="hint">sorted by ${esc(ind.label.toLowerCase())} · click a row to drill into postal codes · ☆ pins a municipality in the trend chart</span></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th></th><th>Municipality</th><th class="num">Population</th>
      <th class="num hi">${esc(ind.label)}<br><span class="dim">${esc(ind.unit || "")}</span></th>${y0 && y0 !== MK.year ? `<th class="num">Δ since ${y0}<br><span class="dim">${ind.fmt.startsWith("pct") || ind.fmt === "signpct1" ? "pp" : "%"}</span></th>` : ""}
      ${cols.filter(i => i.key !== ind.key).map(i => `<th class="num">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}
      ${port ? `<th class="num">Properties</th><th class="num">Units</th>` : ""}</tr></thead>
    <tbody>${rows.map(m => {
      const ps = port ? port.filter(p => p.muni === m.code) : [];
      return `<tr class="clickrow" data-mkmuni="${esc(m.code)}"><td class="pin ${MK.pins.includes(m.code) ? "on" : ""}" data-pin="${esc(m.code)}" title="pin in trend chart">${MK.pins.includes(m.code) ? "★" : "☆"}</td><th>${esc(m.name)}</th><td class="num dim" data-v="${m.pop || 0}">${m.pop != null ? nf(m.pop / 1000, 0) + " k" : "–"}</td>
        ${fmtCell(ind, V(m, ind.key), false)}${y0 && y0 !== MK.year ? deltaCell(m, ind) : ""}
        ${cols.filter(i => i.key !== ind.key).map(i => fmtCell(i, V(m, i.key), false)).join("")}
        ${port ? `<td class="num">${ps.length || "–"}</td><td class="num">${ps.reduce((s, p) => s + (p.units || 0), 0) || "–"}</td>` : ""}</tr>`; }).join("")}</tbody></table></div>
    ${srcNote()}
  </div>`;
}
function areaTable(muni) {
  const ind = curInd();
  const areas = muniAreas(muni.code).slice().sort((a, b) => ((V(b, ind.key) ?? V(muni, ind.key)) ?? -1e9) - ((V(a, ind.key) ?? V(muni, ind.key)) ?? -1e9));
  const cols = IND.filter(i => i.level === "postnr").concat(IND.filter(i => i.level !== "postnr"));
  return `<div class="card">
    <div class="card-head"><h3>${esc(muni.name)} by postal code</h3><span class="hint">sorted by ${esc(ind.label.toLowerCase())} · ° = municipality value (no postal-code statistic)</span></div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr><th>Area</th><th>Postal code</th><th class="num">Population</th>
      ${cols.map(i => `<th class="num ${i.key === ind.key ? "hi" : ""}">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
    <tbody>${areas.map(a => `<tr><th>${esc(a.name)}</th><td class="dim">${esc(a.nr)}</td><td class="num dim" data-v="${a.pop || 0}">${a.pop != null ? nf(a.pop, 0) : "–"}</td>
      ${cols.map(i => { const own = V(a, i.key); return own != null ? fmtCell(i, own, false) : fmtCell(i, V(muni, i.key), true); }).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="cap">${areas.length} postal-code areas. Postal codes that span several municipalities are attributed to their dominant municipality.</p>
  </div>`;
}

/* ---------- Table mode ---------- */
function tableRows() {
  const q = T.q;
  if (T.level === "kommune") {
    return MUNI.filter(m => (!T.region || m.region === T.region) && (m.pop || 0) >= T.minPop &&
      (!q || m.name.toLowerCase().includes(q) || m.code.includes(q)));
  }
  return AREAS.filter(a => { const m = byCode[a.muni] || {};
    return (!T.region || m.region === T.region) && (a.pop || 0) >= T.minPop &&
      (!q || (a.name || "").toLowerCase().includes(q) || a.nr.includes(q) || (m.name || "").toLowerCase().includes(q)); });
}
function tableCols() { return T.level === "postnr" ? IND.filter(i => i.level === "postnr").concat(IND.filter(i => i.level !== "postnr")) : IND; }
function tableBodyHtml() {
  const ind = curInd(), cols = tableCols();
  const rows = tableRows().slice().sort((a, b) => ((V(b, ind.key) ?? V(byCode[b.muni], ind.key)) ?? -1e9) - ((V(a, ind.key) ?? V(byCode[a.muni], ind.key)) ?? -1e9));
  if (!rows.length) return `<tr><td colspan="${cols.length + 4}" class="empty">no rows match the filters</td></tr>`;
  return rows.map(r => {
    const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    return `<tr ${T.level === "kommune" ? `class="clickrow" data-mkmuni="${esc(r.code)}"` : ""}>
      <th>${esc(r.name)}</th><td class="dim">${T.level === "postnr" ? esc(r.nr) : esc(r.code)}</td><td class="dim">${T.level === "postnr" ? esc(m.name || "") : esc(r.region || "")}</td>
      <td class="num dim" data-v="${r.pop || 0}">${r.pop != null ? nf(r.pop, 0) : "–"}</td>
      ${cols.map(i => { const own = V(r, i.key); return own != null ? fmtCell(i, own, false) : (T.level === "postnr" ? fmtCell(i, V(m, i.key), true) : fmtCell(i, null, false)); }).join("")}</tr>`; }).join("");
}
function renderTableBody() {
  const tb = document.getElementById("tbody"); if (!tb) return;
  tb.innerHTML = tableBodyHtml();
  const n = document.getElementById("tcount"); if (n) n.textContent = `${tableRows().length} rows`;
}
function vTable(ind) {
  const cols = tableCols();
  return `
  <div class="card accent">
    <div class="card-head"><h3>Macro table</h3>
      <div class="tools">${modeSeg()}${indSelect()}${yearSelect()}</div></div>
    ${indExplain(ind)}
    <div class="tfilters">
      <input id="tq" type="search" placeholder="Search municipality, postal code or name…" value="${esc(T.q)}">
      <div class="seg"><button class="sg ${T.level === "kommune" ? "on" : ""}" data-tlevel="kommune">Municipalities (${MUNI.length})</button><button class="sg ${T.level === "postnr" ? "on" : ""}" data-tlevel="postnr">Postal codes (${AREAS.length})</button></div>
      <select id="tregion" class="indsel"><option value="">All regions</option>${REGIONS.map(r => `<option value="${r}" ${T.region === r ? "selected" : ""}>${r}</option>`).join("")}</select>
      <label class="hint">min. population <input id="tminpop" type="number" min="0" step="1000" value="${T.minPop}" style="width:90px"></label>
      <span class="hint" id="tcount">${tableRows().length} rows</span>
      <button class="lk mini" data-csv>⤓ Export CSV</button>
    </div>
    <div class="scrollx"><table class="tbl compact wraphead" data-sortable><thead><tr>
      <th>${T.level === "postnr" ? "Area" : "Municipality"}</th><th>${T.level === "postnr" ? "Postal code" : "Code"}</th><th>${T.level === "postnr" ? "Municipality" : "Region"}</th><th class="num">Population</th>
      ${cols.map(i => `<th class="num ${i.key === ind.key ? "hi" : ""}">${esc(i.label)}<br><span class="dim">${esc(i.unit || "")}</span></th>`).join("")}</tr></thead>
      <tbody id="tbody">${tableBodyHtml()}</tbody></table></div>
    <p class="cap">Sorted by the selected indicator; click any column header to re-sort. ° = municipality value shown on a postal code. Rows: ${T.level === "postnr" ? "postal codes (street-level codes in central Copenhagen merged by name)" : "municipalities"}.</p>
    ${srcNote()}
  </div>`;
}
function exportCsv() {
  const cols = tableCols(), rows = tableRows();
  const head = [T.level === "postnr" ? "area" : "municipality", T.level === "postnr" ? "postal_code" : "code", T.level === "postnr" ? "municipality" : "region", "population"].concat(cols.map(i => i.key));
  const lines = [head.join(";")].concat(rows.map(r => { const m = T.level === "postnr" ? (byCode[r.muni] || {}) : r;
    return [r.name, T.level === "postnr" ? r.nr : r.code, T.level === "postnr" ? (m.name || "") : (r.region || ""), r.pop ?? ""].concat(cols.map(i => V(r, i.key) ?? (T.level === "postnr" ? (V(m, i.key) ?? "") : ""))).map(v => String(v).replace(/;/g, ",")).join(";"); }));
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = `am-dashboard-dk_${T.level}_${(D.meta && D.meta.built) || "data"}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ---------- Leaflet layers ---------- */
function lfPopup(a, muni) {
  const row = (i, v, own) => `<span class="lfrow"><span>${esc(i.short || i.label)}</span><b>${fmtOf(i)(v)}${own ? "" : " °"}</b></span>`;
  const native = IND.filter(i => V(a, i.key) != null).map(i => row(i, V(a, i.key), true)).join("");
  const inherited = IND.filter(i => V(a, i.key) == null && muni && V(muni, i.key) != null).map(i => row(i, V(muni, i.key), false)).join("");
  return `<div class="lfpop"><b>${esc(a.nr)} ${esc(a.name)}</b>${MK.year !== LATEST ? ` <span class="tag">${MK.year}</span>` : ""}
    <span class="dim">${muni ? esc(muni.name) : ""}${a.pop != null ? " · " + nf(a.pop, 0) + " inhabitants" : ""}</span>
    ${native ? `<span class="lfsec">Postal code</span>${native}` : ""}
    ${inherited ? `<span class="lfsec">Municipality °</span>${inherited}` : ""}</div>`;
}
function lfLayers() {
  if (!LF.map) return;
  const zoom = LF.map.getZoom();
  const ind = curInd();
  const micro = zoom >= MICRO_ZOOM && ind.level === "postnr";
  LF.level = zoom >= MICRO_ZOOM ? "micro" : zoom < 8 ? "national" : "macro";
  if (LF.areaG) LF.map.removeLayer(LF.areaG);
  if (LF.labG) LF.map.removeLayer(LF.labG);
  const areas = MK.muni ? muniAreas(MK.muni) : AREAS;
  const munis = MK.muni ? [byCode[MK.muni]].filter(Boolean) : MUNI;
  const vk = o => V(o, ind.key);
  const sc = (list => { const vals = list.map(vk).filter(v => v != null && !isNaN(v)); if (!vals.length) return { t: () => null, lo: null, hi: null }; const lo = Math.min(...vals), hi = Math.max(...vals); return { t: v => v == null || isNaN(v) ? null : (hi > lo ? (v - lo) / (hi - lo) : .5), lo, hi }; })(micro ? areas.filter(a => vk(a) != null) : munis);
  const polys = [], labs = [];
  areas.forEach(a => {
    const m = byCode[a.muni];
    const src = micro && vk(a) != null ? a : m;
    const t = src ? sc.t(vk(src)) : null;
    const p = L.polygon(a.rings, { color: "#FFFFFF", weight: zoom >= MICRO_ZOOM ? 1.4 : 0.8,
      fillColor: t == null ? "#C4CBC4" : mkShade(t, ind.key), fillOpacity: .72, smoothFactor: 1 });
    p.bindPopup(lfPopup(a, m), { maxWidth: 300, maxHeight: 340, autoPanPadding: [24, 24] });
    polys.push(p);
  });
  if (zoom >= MICRO_ZOOM) {
    const big = areas.slice().sort((x, y) => (y.pop || 0) - (x.pop || 0)).slice(0, 40);
    big.forEach(a => {
      const m = byCode[a.muni]; const own = micro && vk(a) != null; const v = own ? vk(a) : (m ? vk(m) : null);
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
      const t = sc.t(vk(m)), dark = t != null && t > .55;
      if (zoom < 8 && (m.pop || 0) < 90000) return; /* declutter at national zoom */
      labs.push(L.marker([x / w, y / w], { interactive: false, icon: L.divIcon({
        className: "lflab" + (dark ? " lflab-dark" : ""), iconSize: null,
        html: `<b>${esc(m.name)}</b><br>${vk(m) != null ? fmtOf(ind)(vk(m)) : "–"}` }) }));
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
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, className: "basemap",
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Boundaries: DAGI, Klimadatastyrelsen' }).addTo(map);
  map.on("moveend", () => { const c = map.getCenter(); LF.center = [c.lat, c.lng]; LF.zoom = map.getZoom(); });
  map.on("zoomend", () => {
    /* rebuild polygons only when the display level changes — rebuilding on every pan would kill open popups */
    const z = map.getZoom(), lvl = z >= MICRO_ZOOM ? "micro" : z < 8 ? "national" : "macro";
    if (lvl !== LF.level) lfLayers();
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
