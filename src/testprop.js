/* AM Dashboard — Denmark Edition · testprop.js
   Reads a location out of a pasted Google Maps link or a plain "lat, lon" pair.
   Browser only: nothing is fetched and no link is followed, so a short share link
   (maps.app.goo.gl) cannot be resolved here — the user is asked for the long URL.

   Inlined into dist/index.html by scripts/build_dashboard.py, and required by
   tests/testprop.test.js (`make test-js`), so it stays free of DOM and window.
*/
"use strict";

/* coarse Denmark box — a first sanity check on the numbers (catches a swapped
   lon/lat pair). The real "is this in Denmark" answer comes from locate() in app.js. */
const TP_BOUNDS = { lat: [54, 58], lon: [7, 16] };
const TP_SHORT_RE = /\b(?:maps\.app\.goo\.gl|goo\.gl|g\.co\/kgs)\b/i;
const TP_SHORT_MSG = "Short share links can't be read in the browser. Open the link and copy the full URL from the address bar, or right-click the spot in Google Maps and paste the coordinates.";
/* the formats the input accepts, in the order parseLocation tries them — also shown in the "?" tooltip */
const TP_FORMATS = [
  ["place", "…/place/Name/@55.6,12.5,17z/data=…!3d55.67610!4d12.56830", "a Google Maps place URL (the !3d/!4d pin wins over the @ viewport)"],
  ["at", "…/maps/@55.67610,12.56830,17z", "a Google Maps view URL"],
  ["param", "…/maps?q=55.67610,12.56830", "a q= / ll= / query= parameter"],
  ["search", "…/maps/search/55.67610,12.56830", "a Google Maps search URL"],
  ["plain", "55.67610, 12.56830", "plain coordinates — comma, semicolon or space"]];

const tpNum = s => { const v = parseFloat(s); return isNaN(v) ? null : v; };
const TP_D = "(-?\\d{1,3}(?:\\.\\d+)?)";                 /* a signed decimal degree */
const TP_SEP = "\\s*[,;]\\s*";                           /* the separator once "+" and %2C are decoded */

function tpPair(lat, lon, source) {
  if (lat == null || lon == null) return null;
  if (lat < TP_BOUNDS.lat[0] || lat > TP_BOUNDS.lat[1] || lon < TP_BOUNDS.lon[0] || lon > TP_BOUNDS.lon[1])
    return { error: "outside_dk", message: `${lat}, ${lon} is outside Denmark (latitude ${TP_BOUNDS.lat[0]}–${TP_BOUNDS.lat[1]} N, longitude ${TP_BOUNDS.lon[0]}–${TP_BOUNDS.lon[1]} E). Latitude comes first — check the order.` };
  return { lat, lon, source };
}

/* text → {lat, lon, source} | {error, message} */
function parseLocation(text) {
  const raw = String(text == null ? "" : text).trim();
  if (!raw) return { error: "empty", message: "Paste a Google Maps link, or coordinates as \"55.67610, 12.56830\"." };
  /* "+" is a space in a query string and %2C a comma — decode once so every pattern below sees plain text */
  let s = raw;
  try { s = decodeURIComponent(raw.replace(/\+/g, " ")); } catch (e) { /* a stray % — read the text as it stands */ }

  if (TP_SHORT_RE.test(s)) return { error: "short_link", message: TP_SHORT_MSG };

  let m;
  /* 1. the place pin (!3d lat !4d lon) — the actual spot, so it wins over the @ viewport centre */
  if ((m = s.match(new RegExp("!3d" + TP_D + "!4d" + TP_D)))) return tpPair(tpNum(m[1]), tpNum(m[2]), "place");
  /* 2. the viewport centre: @lat,lon,17z */
  if ((m = s.match(new RegExp("@" + TP_D + TP_SEP + TP_D)))) return tpPair(tpNum(m[1]), tpNum(m[2]), "at");
  /* 3. a coordinate parameter: q= / ll= / query= / daddr= / center= */
  if ((m = s.match(new RegExp("(?:^|[?&#])(?:q|ll|query|daddr|center)=" + TP_D + TP_SEP + TP_D, "i")))) return tpPair(tpNum(m[1]), tpNum(m[2]), "param");
  /* 4. /search/<lat>,<lon> */
  if ((m = s.match(new RegExp("/search/" + TP_D + TP_SEP + TP_D)))) return tpPair(tpNum(m[1]), tpNum(m[2]), "search");
  /* 5. the coordinates on their own — comma, semicolon or whitespace */
  if ((m = s.match(new RegExp("^" + TP_D + "(?:" + TP_SEP + "|\\s+)" + TP_D + "$")))) return tpPair(tpNum(m[1]), tpNum(m[2]), "plain");

  return { error: "no_match", message: "No coordinates in that text. Paste the full Google Maps URL from the address bar, or right-click the spot in Google Maps and copy the \"55.67610, 12.56830\" pair it offers." };
}

if (typeof module !== "undefined" && module.exports) module.exports = { parseLocation, TP_BOUNDS, TP_FORMATS, TP_SHORT_MSG };
