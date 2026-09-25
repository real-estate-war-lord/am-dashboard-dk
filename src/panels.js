/* panels.js — the four bodies the chart panel draws (spec §5.2): a history line, the population
   outlook, a distribution strip and the Climate horizons.

   This is NOT a pure core module like src/climate_core.js or src/pin_core.js — it is app.js's
   chart-drawing half, moved into a file of its own so `src/app.js` stays inside its 450 KB budget
   (the remedy the P7/P8 notes name). The build inlines every src/*.js as a classic script into one
   global lexical scope, so these functions still read app.js's own helpers (`esc`, `nf`, `fmtOf`,
   `V`, `median`, `climValue`, the CLIM_* tables …) exactly as they did when they lived there; they
   are resolved when the function runs, long after app.js has finished evaluating.

   Nothing here holds state. Each function takes the entity and the indicator and returns markup.
*/
"use strict";
/* IIFE for the same reason every other src file has one: a top-level const here would collide with
   app.js in the shared global scope and blank the page. */
(function () {

/* the history line of the chart panel: one <path> per series, dots with the value in their title,
   a vertical marker on the year the period control names */
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
function popOutlookChart(o, opts) {
  const hist = o.pop_hist || {}, proj = o.fc_pop || {};
  const group = opts && opts.group;
  const gp = o.fc_groups || {};
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

if (typeof window !== "undefined") window.PANELS = { multiLine, popOutlookChart, distStrip, climBars };

})();
