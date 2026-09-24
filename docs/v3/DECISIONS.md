# v3.0 — decisions taken during the unattended build

One line per decision, prefixed with the phase that took it. Written when the spec left a choice
open and nobody was awake to make it.

- P1: `dropMap()` also clears the macro map's draw caches (`LF.level/ctx/pubDrawn/srvDrawn/climDrawn/microMarks/tpMark`). They describe what is drawn on a map that no longer exists, and a stale `pubDrawn` would skip the first redraw after the map is rebuilt.
- P1: the per-map renderer set is `map._am = {base, srv, pub, clim}`, created lazily by `mapPanes(map)`. Lazily rather than at every `L.map()` call site, so a builder that is handed a map built elsewhere (`pubMarkers`, `pubClusterMarkers`) can still ask for the panes it needs and never reaches for another map's.
- P1: one shared `LF.initTimer` for every map init, not one per view. Only one view is on screen at a time, so a shared timer is what "the last render wins" actually means.
- P1: `L.Map.prototype._getMapPanePos` returns `L.point(0, 0)` when the pane is gone, rather than `undefined`. Callers do arithmetic on the result; a zero offset is the only answer that cannot throw one frame later.
- P1: the alias table maps `#compare?a=…&b=…` to the **a** side's area page, and to `#map` when `a` is missing or unparsable — owner amendment A1 says Compare is deleted but not which side survives; the first one named is the one the reader chose first.
- P1: `#market?src=1` (and the existing `#sources` alias) land on `data/sources`, plain `#market` on `data/national`. The v2.6 `src=1` was "market with the sources panel open", which is exactly the new Sources tab.
- P1: `route_core.buildHash()` leaves `,` `:` `;` `/` unescaped. They are legal in a fragment and are what makes `property?p=55.6545,12.539:Test` readable; AC-TP1 checks that literal spelling.
- P1: the property codec (`propParse`/`propSerialise`) is list-capable (`;` separated) although v3.0 shows one pin — owner amendment A2 asks for the URL codec to stay list-capable for the LATER portfolio.
- P1: `tests/ui_smoke.py` waits for a landmark with Playwright `state="attached"`, not the default `"visible"`. Leaflet panes have no size of their own, so the visible wait always timed out — 15 s × 3 viewports per run, for nothing.
- P1: `OVERFLOW_FATAL = False` in `tests/ui_smoke.py`. Phone-width overflow is a v2.6 defect on all 28 routes; it is reported as a note until P8 rebuilds the responsive shell.
- P1: design tokens go in a third `:root` block at the end of `style.css` rather than into the two existing ones. Nothing above is edited, and the cascade puts the v3 values last.
