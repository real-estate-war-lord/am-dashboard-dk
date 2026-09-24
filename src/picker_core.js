/* IndicatorPicker and PeriodControl — the pure parts, kept out of src/app.js so they can be
   unit-tested. Same arrangement as src/climate_core.js, src/route_core.js and src/testprop.js:
   no DOM, no globals, no fetch. `node --test tests/picker.test.js` runs against this file.

   What lives here is everything about the picker that is a function of the registry alone:

     · the group order and the two group pills (spec §4.2) — one definition, used by the picker
       popover, by the Charts indicator list and by anything else that groups indicators;
     · the search predicate, so "surge" means the same thing in every picker;
     · which of the three PeriodControl modes an indicator needs (spec §4.3);
     · the right-aligned availability tag of a row (`muni`, `2016–`, `snapshot`, …);
     · the ↑/↓ step over the visible rows.

   Nothing here knows which view is on screen or which state object the picker writes to — app.js
   owns that. An indicator is just `{key, label, short, unit, group, proj, ...}` from the registry.
*/
"use strict";
/* Wrapped in an IIFE: the build inlines this file and app.js as classic <script> blocks in one
   global lexical scope, so a top-level const here would collide with app.js and blank the page. */
(function () {

/* The optgroup / popover order (spec §4.2). Anything whose group is not in the list falls into
   "Other" at the end, so a registry addition is visible rather than silently dropped. */
const GROUP_ORDER = ["Demographics", "Income & jobs", "Housing stock", "Housing stock (BBR)", "Rents",
                     "Prices & market", "Construction", "Safety", "Schools", "Growth signals",
                     "Outlook", "Climate"];
const OTHER = "Other";
/* The two families whose period control is not a year selector. The group header says so before
   the reader picks, so the toolbar changing shape under them is never a surprise (spec §4.2). */
const GROUP_PILL = { Outlook: "Projection", Climate: "Horizon" };

const groupOf = i => (i && i.group) || OTHER;

/* Inherited values are visibly inherited (spec §1 decision 7): on a postal-code or quarter page the
   indicators whose figure is the municipality's are listed under one sub-heading at the end of the
   popover rather than scattered, dimmed, through the twelve groups. */
const MUNI_GROUP = "From the municipality";

/* [{name, pill, inds}] in GROUP_ORDER, groups with no indicator left out, "Other" last. */
function grouped(list, order) {
  const L = list || [], ord = order || GROUP_ORDER;
  const known = i => ord.indexOf(groupOf(i)) >= 0;
  const names = ord.filter(g => L.some(i => groupOf(i) === g));
  if (L.some(i => !known(i))) names.push(OTHER);
  return names.map(name => ({
    name,
    pill: GROUP_PILL[name] || "",
    inds: L.filter(i => name === OTHER ? !known(i) : groupOf(i) === name),
  }));
}

/* grouped(), plus the "From the municipality" sub-heading for the rows whose figure is inherited at
   the level on screen (spec §4.2, AC-I5). `isInherited(i)` is the caller's level test — picker_core
   knows nothing about which view is on screen. Without it this is exactly grouped(). */
function groupedLevel(list, order, isInherited) {
  const L = list || [];
  if (typeof isInherited !== "function") return grouped(L, order);
  const inh = L.filter(i => isInherited(i));
  if (!inh.length) return grouped(L, order);
  const gs = grouped(L.filter(i => !isInherited(i)), order);
  gs.push({ name: MUNI_GROUP, pill: "", inds: inh });
  return gs;
}

/* ---------- search ---------- */
/* label, short, group and unit (spec §4.2). Every word of the query has to hit, so "surge zone"
   narrows rather than widens, and the order the reader types them in does not matter. */
const blob = i => [i && i.label, i && i.short, i && i.group, i && i.unit].filter(Boolean).join(" ").toLowerCase();
function matches(i, q) {
  const s = String(q == null ? "" : q).trim().toLowerCase();
  if (!s) return true;
  const b = blob(i);
  return s.split(/\s+/).every(w => b.indexOf(w) >= 0);
}
const filter = (list, q) => (list || []).filter(i => matches(i, q));

/* ---------- the period control's mode (spec §4.3) ---------- */
/* A Climate indicator is published per horizon and an Outlook indicator is one projection vintage;
   neither has a year series, so neither may be shown next to a year selector. */
function periodMode(i) {
  if (!i) return "year";
  if (groupOf(i) === "Climate") return "horizon";
  if (i.proj) return "projection";
  return "year";
}
/* the URL key that mode owns — the other one is dropped when the family changes (spec §3.2) */
const PERIOD_KEY = { year: "y", horizon: "hz", projection: "" };

/* ---------- the availability tag on a row ---------- */
/* Where the figure on that row comes from, in three words at most. `opts.inherited` = the value at
   the level on screen is the municipality's own figure; `opts.years` = the years a year selector
   would offer for it at that level. */
function availTag(i, opts) {
  const o = opts || {};
  if (o.inherited) return { text: "muni", cls: "tag-muni", title: "municipality figure shown at this level" };
  if (groupOf(i) === "Climate") return { text: "horizons", cls: "tag-hz", title: "published per horizon: Today · 2070 · 2120" };
  if (i && i.proj) return { text: `${i.proj.from || ""}→${i.proj.to || ""}`, cls: "tag-proj",
                            title: `projection, ${i.proj.publisher || ""} ${i.proj.vintage || ""}`.trim() };
  const ys = (o.years || []).filter(Boolean);
  if (ys.length > 1) return { text: ys[0] + "–", cls: "tag-hist", title: `history from ${ys[0]}` };
  return { text: "snapshot", cls: "tag-snap", title: "one published as-of, no year series" };
}

/* ---------- keyboard ---------- */
/* ↑/↓ over the n visible rows. Clamped, never wrapping past either end: from "nothing active"
   (-1) a ↓ lands on the first row and a ↑ on the last. */
function step(cur, delta, n) {
  if (!n) return -1;
  const c = (cur == null || cur < 0) ? (delta > 0 ? -1 : n) : cur;
  return Math.max(0, Math.min(n - 1, c + delta));
}

const API = { GROUP_ORDER, GROUP_PILL, OTHER, MUNI_GROUP, PERIOD_KEY, groupOf, grouped, groupedLevel,
              matches, filter, periodMode, availTag, step };
if (typeof window !== "undefined") window.PICKER_CORE = API;
if (typeof module !== "undefined" && module.exports) module.exports = API;

})();
