# Services layer — source probe

**Status:** probe only, 2026-09-23 · branch `v2.x-services` · **nothing is built and nothing is wired into `make build`**
**Script:** `scripts/probe_services.py` (see §9 to reproduce)
**Raw output:** `data/raw/probe/probe_results.json` (gitignored)

The question: can we put groceries, restaurants/cafés, pharmacies and public-transport
stops on the map, from which source, nationwide or metro-only, and how many points is
that. This document answers it with measurements, not estimates.

## 0. Verdict

**Build the whole layer from the Geofabrik OSM extract, nationwide, plus GTFS for
transport. Do not call Overpass at runtime. Do not use Smiley for placement.**

| category | source | coverage | points (DK) | points (kommune 101) |
|---|---|---|---|---|
| Groceries | OSM extract — `shop=supermarket\|convenience` | national | **3 957** | 513 |
| Restaurants / cafés | OSM extract — `amenity=restaurant\|cafe\|bar\|fast_food` | national | **14 718** | 3 169 |
| Pharmacies | OSM extract — `amenity=pharmacy` | national | **545** | 41 |
| Transport stops | **Rejseplanen GTFS** (`stops.txt` + `route_type`) | national | **36 383** | 1 050 |

Three findings drove that:

1. **Overpass cannot be a runtime dependency.** During this probe both healthy mirrors
   returned HTTP 504/429 for minutes at a time, a single count query ranged from 0.7 s
   to over 200 s, and the query that resolves a kommune boundary by name timed out
   every time. Worse, two mirrors returned *confident wrong zeros* (§2).
2. **The 495 MB extract answers everything in 87 s, offline.** One download, one scan,
   both national and per-kommune counts, no API budget, reproducible. It is also what
   caught the wrong zeros.
3. **Smiley has no coordinates at all.** Every row is an address string. Using it would
   mean geocoding 58 718 rows through DAR before a single dot could be drawn, and it
   answers a different question than OSM does anyway (§4, §5).

## 1. Source summary

| source | works? | key / licence | size | counts | notes |
|---|---|---|---|---|---|
| **OSM Overpass API** | ⚠️ unreliable | none · ODbL 1.0 | per-query | ≤ 4 points from the extract on every tag (< 0.6 % where n > 100) | 504/429 for minutes; one mirror has no areas DB and returns 0; another is 4.5 months stale. See §2 |
| **Geofabrik Denmark extract** | ✅ | none · ODbL 1.0 | **494 761 880 B (495 MB)**, updated 2026-09-22 | 60 344 530 objects scanned in **87 s** | pyosmium 4.3.1 installs and works. The recommended source. §3 |
| **Rejseplanen GTFS** | ✅ | **no registration, no key** · attribution "Rejseplanen" | **54 971 494 B (55 MB)** zip, updated 2026-09-21 | **36 383 stops**, 1 609 routes, 4 214 818 stop_times | `route_type` splits the modes cleanly. §4 |
| **Fødevarestyrelsen Smiley** | ✅ downloads, ❌ unusable for a map | no key · attribution "Fødevarestyrelsen", logo forbidden | **59 810 770 B (60 MB)** XML, updated daily | **58 718 rows**, 8 285 in København postcodes | **no coordinates in any field.** §5 |

## 2. a. OSM Overpass API

Endpoint `https://overpass-api.de/api/interpreter` (+ mirrors), no key, ODbL 1.0.
Counts requested with `out count;` for nodes and ways separately, inside
`area(3602192363)` = relation 2192363, *Københavns Kommune* (`ref=101`, verified from
its own tags).

### Reliability — the headline result

| observation | detail |
|---|---|
| Resolving a boundary **by name** | timed out (504) on every attempt, on every mirror. An unbounded search over all admin relations is too expensive. Resolving the same boundary **by relation id** takes **0.12 s** |
| Same query, minutes apart | 504 → 200 in 5.8 s → 504 again. Not rate limiting of this client; server load |
| Slowest successful count | **196.9 s** (area lookup), **105.1 s** (`amenity=bar`) |
| Fastest successful count | **0.7 s** |
| `overpass.osm.ch` | serves **no areas database** — `area(...)` matches nothing, so every count came back **0 with HTTP 200**. Removed from the mirror list |
| `overpass.kumi.systems` | answers, but its database snapshot was **2026-05-06** — 4.5 months stale — against overpass-api.de's 2026-09-22 |

Two zeros from the first pass were wrong and were caught only by comparing against the
extract: `shop=convenience` came back 0 (truth: **252**) and `amenity=pharmacy` came back
0 (truth: **41**). The script now refuses to believe a zero from one mirror
(`confirm_zero()`), but the deeper lesson is that a silently-wrong 0 is the failure mode
of this API, and a layer built on it would show an empty map rather than an error.

### Counts, kommune 101

| tag | nodes | ways | **total** | query time | extract says | Δ |
|---|---|---|---|---|---|---|
| `shop=supermarket` | 247 | 14 | **261** | 3.1 s | 261 | — |
| `shop=convenience` | 244 | 7 | **251** | 1.8 s | 252 | -1 |
| `shop=discount` | 0 | 0 | **0** | 2.6 s | 0 | — |
| `amenity=restaurant` | 731 | 8 | **739** | 9.3 s | 737 | +2 |
| `amenity=cafe` | 772 | 8 | **780** | 0.9 s | 776 | +4 |
| `amenity=bar` | 489 | 4 | **493** | 3.2 s | 493 | — |
| `amenity=fast_food` | 1156 | 5 | **1161** | 4.0 s | 1163 | -2 |
| `amenity=pharmacy` | 41 | 0 | **41** | 0.9 s | 41 | — |
| `highway=bus_stop` | 1237 | 4 | **1241** | 4.2 s | 1239 | +2 |
| `railway=station` | 44 | 0 | **44** | 1.8 s * | 43 | +1 |
| `railway=halt` | 24 | 0 | **24** | 1.8 s | 25 | -1 |
| `station=subway` | 35 | 0 | **35** | 2.3 s | 34 | +1 |
| `station=light_rail` | 27 | 0 | **27** | 0.6 s | 28 | -1 |

All 13 tags answered on `overpass-api.de` once it was reachable, in **0.6 s to 9.3 s** —
but only after the retry loop had absorbed a 504 or a 60 s read timeout on most of them.
`railway=station` failed outright in the batch (DNS failure reaching the second mirror)
and was re-run on its own afterwards, marked `*`.

**Where Overpass answers, it agrees with the extract closely**: no tag differs by more
than **4 points**, and on every tag with more than 100 objects the gap is **under
0.6 %**. (The largest *relative* gap, 4 %, is one point on a 25-point tag.) The two
snapshots are a day apart, which accounts for most of the difference. Note also that `out count` is the cheap case: these are counts,
not geometry. Extracting 14 718 restaurant points nationwide over the API is a different
order of request, and the kind the API asks you not to make.


## 3. b. Geofabrik Denmark extract

`https://download.geofabrik.de/europe/denmark-latest.osm.pbf` — no key, **ODbL 1.0**
("Data processed by Geofabrik GmbH and created by OpenStreetMap Contributors").

| | |
|---|---|
| size | **494 761 880 B = 495 MB** |
| last modified | 2026-09-22 23:05 UTC (rebuilt daily) |
| `pyosmium` | **installs and works** — `pip install osmium` → **4.3.1**, wheels for macOS/Linux, no compiler needed |
| scan | **60 344 530 objects in 87 s** with `osmium.FileProcessor(...).with_locations()` |
| way positions | average of the way's node coordinates — the same approximation Overpass `out center` makes |

Nationwide counts, and kommune 101 by point-in-polygon against
`data/geo/kommuner.geojson` (the file the dashboard already ships):

| tag | DK nodes | DK ways | **DK total** | 101 nodes | 101 ways | **101 total** |
|---|---|---|---|---|---|---|
| `shop=supermarket` | 1 529 | 1 284 | **2 813** | 247 | 14 | **261** |
| `shop=convenience` | 1 058 | 86 | **1 144** | 245 | 7 | **252** |
| `shop=discount` | 0 | 0 | **0** | 0 | 0 | **0** |
| `amenity=restaurant` | 3 030 | 168 | **3 198** | 729 | 8 | **737** |
| `amenity=cafe` | 3 602 | 76 | **3 678** | 768 | 8 | **776** |
| `amenity=bar` | 1 617 | 17 | **1 634** | 489 | 4 | **493** |
| `amenity=fast_food` | 5 959 | 249 | **6 208** | 1 158 | 5 | **1 163** |
| `amenity=pharmacy` | 530 | 15 | **545** | 41 | 0 | **41** |
| `highway=bus_stop` | 18 396 | 43 | **18 439** | 1 235 | 4 | **1 239** |
| `railway=station` | 354 | 1 | **355** | 43 | 0 | **43** |
| `railway=halt` | 271 | 0 | **271** | 25 | 0 | **25** |
| `station=subway` | 46 | 0 | **46** | 34 | 0 | **34** |
| `station=light_rail` | 164 | 0 | **164** | 28 | 0 | **28** |

Three things to carry forward:

- **`shop=discount` is unused in Denmark — 0 nationwide.** Netto, Rema 1000, Lidl and
  Aldi are tagged `shop=supermarket`. Asking for it is harmless but it will never
  return anything; a "discount" split would have to come from `brand`/`operator`.
- **Ways matter for groceries.** 1 284 of 2 813 supermarkets (46 %) are mapped as
  building polygons, not nodes — a node-only query loses nearly half the stock.
- **The station tags overlap and must not be summed.** In kommune 101, **33 of 34**
  `station=subway` points are *also* `railway=station` (the 34th is a `railway=halt`),
  and all 28 `station=light_rail` points are also one or the other. Summing the five
  transport tags gives 1 369; the true count of distinct points is **1 307**
  (1 239 bus stops + **68** distinct rail/metro/light-rail points, not 130).
  Nationwide the same measurement gives **628 distinct** station points against a naive
  sum of 836 — `railway=station` 355 · `railway=halt` 271 · `station=light_rail` 164 ·
  `station=subway` 46.

## 4. c. Rejseplanen GTFS

**Download URL:** `https://www.rejseplanen.info/labs/GTFS.zip` — **direct, no registration
and no API key** (HTTP 200 on an anonymous HEAD). A Rejseplanen Labs account is needed
for their *live* APIs, not for this static file.

**Licence:** the feed carries its own `attributions.txt` — `is_producer=1`,
`organization_name=Rejseplanen`, `attribution_url=https://www.rejseplanen.dk`. Third-party
catalogues describe the feed as CC BY 4.0; **we could not confirm that wording on a
first-party page** (the Labs article returns 403 to a plain fetch), so treat
"attribution to Rejseplanen" as the confirmed requirement and check the licence text
before shipping.

| | |
|---|---|
| zip size | **54 971 494 B = 55 MB** (last modified 2026-09-21, refreshed roughly fortnightly) |
| largest members | `stop_times.txt` 231 MB, `shapes.txt` 112 MB, `trips.txt` 12 MB, `stops.txt` 3.6 MB |
| stops | **36 383** |
| routes | **1 609** |
| stop_times rows | 4 214 818 (scanned in 1.6 s with `csv.reader`) |
| operators | 20 agencies incl. DSB, DSB S-tog, Metroselskabet, Movia, Midttrafik, Skånetrafiken |

### Does `route_type` let us split the modes? **Yes.**

Every one of the 36 383 stops resolves to at least one `route_type` through
`stop_times → trips → routes`:

| `route_type` | meaning | routes | **stops** |
|---|---|---|---|
| `1` | **Metro** (Copenhagen M1–M4) | 4 | **44** |
| `109` | **S-train** (suburban rail, extended GTFS type) | 7 | **88** |
| `2` | **Rail** | 31 | **459** |
| `0` | **Tram / light rail** (Aarhus + Odense letbane) | 4 | **173** |
| `3` | **Bus** | 1 387 | **34 709** |
| `700` | Bus service (extended type) | 7 | **479** |
| `715` | Demand-responsive bus (flextur) | 156 | **3 077** |
| `4` | Ferry | 13 | **30** |

2 672 stops serve more than one `route_type` — an interchange must be allowed to carry
several mode badges rather than being forced into one.

**Two caveats that shape the schema:**

- **`location_type` is `0` for all 36 383 stops and `parent_station` is empty for every
  single one.** This feed has no station/platform hierarchy: a two-way bus stop is two
  rows and a metro station with two platforms is two rows. If we want "Nørreport" as one
  dot we must cluster by name + proximity ourselves.
- `route_type` 109, 700 and 715 are Google's *extended* types, not the GTFS base set, so
  a naive `route_type in (0,1,2,3,4)` filter silently drops the S-train, 479 bus stops
  and all 3 077 flextur stops.

## 5. d. Fødevarestyrelsen Smiley

**Download URL:** `https://pub.fvst.dk/publikationer/Smileydata.xml` (also `.xlsx`),
linked from *findsmiley.dk → Om smiley → Statistik og data → Hent smileydata*. **No
registration, no key.** Updated daily (we saw 2026-09-23 14:54 UTC).

**Licence:** the reuse terms on that page are the Danish public-data terms plus three
specific conditions, quoted: *"Du skal angive Fødevarestyrelsen som kilde"*, *"Du må ikke
anvende Fødevarestyrelsens logo"*, and if individual smileys are displayed they *"skal
til enhver tid svare til virksomhedens aktuelle smiley"* — i.e. showing a stale smiley is
a licence breach, which makes a cached snapshot a liability, not just stale data.

**Size:** 59 810 770 B = **60 MB** XML, **58 718 rows**, parses in 0.5 s.

### Fields — the complete list

`ID_nummer` · `CVR_nummer` · `P_nummer` · `Smileybranche` · `FVST_branchenummer` ·
`FVST_branche` · `Virksomhedstype` · `Virksomhed` · `Adresse` · `Postnummer` · `By` ·
`Seneste_kontrol_resultat` · `Seneste_kontrol_dato` · `Næstseneste_*` · `Tredjeseneste_*` ·
`Fjerdeseneste_*` · `URL`

### ❌ Coordinates: none

**There is no coordinate field of any kind** — no `Geo_lat`/`Geo_lng`, no UTM, nothing.
Older descriptions of this dataset mention geo columns; the current feed at `pub.fvst.dk`
does not have them. Placement would require geocoding `Adresse` + `Postnummer` through
DAR for all 58 718 rows — the pipeline already has a DAR client (`scripts/fetch_dar.py`),
so it is possible, but it is a real build, not a download.

### ✅ Business type: yes, cleanly

`Smileybranche` separates the categories we care about (national counts):

| `Smileybranche` | rows (DK) | rows (København postcodes) |
|---|---|---|
| Restauranter, kantiner, takeaway, værtshuse m.fl. | 23 363 | 4 595 |
| **Dagligvareforretninger** (groceries) | **11 732** | **1 424** |
| Hospitals- og institutionskøkkener | 8 837 | 854 |
| Delikatesseforretninger og takeaway uden servering | 1 523 | 153 |
| Bagere og bagerafdelinger | 1 160 | 170 |
| Slagtere og slagterafdelinger | 964 | — |
| …21 more incl. wholesale, packaging, offices | | |

`Virksomhedstype` additionally splits **Detail 48 730** from **Engros 9 988** — the
wholesalers are warehouses no resident visits and would have to be filtered out.

**København count:** the feed has **no kommune field**, so postal code is the only handle.
Postnumre 1000–2450 give **8 285 rows** (7 423 of them *Detail*), of which **1 424**
groceries and **4 748** restaurants/takeaway. That range is not kommune 101 — it pulls in
Frederiksberg's 2000 and parts of 2450/2500 — so it is an order-of-magnitude figure only.

## 6. Cross-checks (kommune 101)

The OSM side is the extract, clipped to the kommune 101 polygon. The Smiley side is
postcodes 1000–2450, because that is all the feed allows.

| | OSM | Smiley | ratio |
|---|---|---|---|
| Groceries | **513** (`supermarket` 261 + `convenience` 252) | **1 424** (Dagligvareforretninger) | **2.8 ×** |
| Restaurants / cafés / bars / takeaway | **3 169** | **4 748** | 1.5 × |

**The gap is definition, not missing OSM data.** Smiley registers every *food business*: a
kiosk, a petrol-station shop, a canteen, a bakery counter inside another shop, a hotel
minibar operation, a wholesale depot. OSM `shop=supermarket|convenience` is a shop a
resident walks into. The geographies also differ (postcode range vs kommune polygon). The
two are not measuring the same thing and neither is "wrong".

### Stops: OSM vs GTFS

| mode | OSM (extract, kommune 101) | GTFS (stops inside the same polygon) |
|---|---|---|
| Bus | `highway=bus_stop` **1 239** | `route_type` 3 + 700 = **1 061** |
| Metro | `station=subway` **34** | `route_type` 1 = **35** |
| S-train | — (not separable in OSM) | `route_type` 109 = **27** |
| Rail | `railway=station` 43 · `railway=halt` 25 (**68 distinct incl. metro/light rail**) | `route_type` 2 = **7** |
| Ferry | — | `route_type` 4 = **3** |
| **total stops** | 1 307 distinct | **1 050** |

The GTFS mode rows sum to 1 133, not 1 050, because **82 of those stops serve more than
one `route_type`** and are counted once per mode.

- **Metro agrees almost exactly** (34 vs 35) — a good sanity check on both sides.
- **OSM has ~17 % more bus stops than GTFS** (1 239 vs 1 061). Expected: OSM keeps stops
  that no current timetable serves (seasonal, school, replacement, or simply out of date);
  GTFS only contains stops in the live plan. For a "what can I actually catch here" layer
  that favours GTFS.
- **The rail rows are not comparable as listed**: OSM `railway=station` includes the metro
  stations (§3), while GTFS splits metro, S-train and rail into different `route_type`s.
  GTFS is the cleaner mode split; OSM is the cleaner "one dot per station".

## 7. Proposal

### Source per category

| category | source | why |
|---|---|---|
| **Groceries** | OSM extract, `shop=supermarket` + `shop=convenience` | the only source with coordinates; Smiley would need 58 718 geocodes and counts a different universe. Take `brand`/`operator` for the chain name |
| **Restaurants / cafés** | OSM extract, `amenity=restaurant\|cafe\|bar\|fast_food` | same reason. Keep the four as sub-types — `fast_food` alone is 42 % of the national total |
| **Pharmacies** | OSM extract, `amenity=pharmacy` | 545 nationally, small and stable |
| **Transport stops** | **Rejseplanen GTFS**, not OSM | it is the live timetable, it splits the modes through `route_type`, and it is 55 MB against a 495 MB extract. Cluster to stations ourselves (no `parent_station`) |
| *(optional later)* Smiley **rating** | Smiley, joined onto an OSM point | a smiley on a restaurant popup is a genuinely nice extra — but the licence says the smiley must always be current, so it would have to be fetched live or refreshed daily, and joined by address, not by coordinate |

### Nationwide or metro-only? **Nationwide.**

Unlike the public-buildings and schools layers, nothing here is gated behind a per-kommune
API pull. One 495 MB download plus one 55 MB zip produces every point in Denmark in about
90 seconds. There is no reason to restrict this layer to the Copenhagen metro set.

### Point counts, and what they imply for clustering

| category | DK | kommune 101 | drawing implication |
|---|---|---|---|
| Pharmacies | 545 | 41 | **draw always, all zooms** — trivial |
| Groceries | 3 957 | 513 | fine ungrouped from ~zoom 11; cluster below |
| Restaurants / cafés | **14 718** | **3 169** | **must cluster.** 3 169 in one kommune is already past what the public-buildings layer draws at zoom 13 (it thins at 2 542) |
| Transport stops | **36 383** | 1 050 | **must cluster, and must filter by mode.** Bus alone is 34 709 of the 36 383 |

Suggested thresholds, by analogy with the existing public-buildings zoom rule
(`PUBLIC_BUILDINGS.md` §4b) which thins at 2 542 buildings in one kommune:

| zoom | drawn |
|---|---|
| < 10 | rail/metro/light-rail stations only (**628** distinct nationally) + pharmacies |
| 10–12 | + groceries, + restaurant/café **clustered** |
| ≥ 13 | everything ungrouped, bus stops included |

### What this looks like in the Analysis sheet's 1 000 m ring

Measured from the extract for the two test properties the v2.4 verification already uses:

| within 1 000 m | Sluseholmen, 2450 SV | Nørrebro |
|---|---|---|
| Groceries | 18 | 48 |
| Restaurants / cafés / bars / takeaway | 46 | **309** |
| Pharmacies | 2 | 2 |
| Bus stops | 46 | 60 |

Groceries, pharmacies and stops fit a list card as they stand. **Eating places do not** —
309 rows is not a table anyone reads. That section should be a count per sub-type with the
five nearest each, exactly the shape `anPubCard` already uses for public buildings.

### Sizes to budget

The dashboard inlines its data into a 4.4 MB `index.html` and fetches per-kommune files
on demand. Services would follow the public-buildings pattern: `services/<kommune>.json`,
fetched when the layer is switched on. Rough budget at ~80 B per point after trimming to
`lat, lon, cat, name, brand`: **≈ 1.6 MB for all of Denmark**, of which transport is
~2.9 MB unclustered — so transport stops should ship pre-clustered to stations, or be
split into their own per-kommune file.

## 8. Open questions before building

1. **GTFS licence wording** — confirm CC BY 4.0 (or whatever it is) on a first-party
   Rejseplanen page before shipping. `attributions.txt` only gives the producer.
2. **Station clustering rule** — GTFS gives no `parent_station`. Cluster by
   `stop_name` + a radius? By `stop_code` prefix? This needs a measurement of its own.
3. **Refresh cadence** — the extract is daily, GTFS roughly fortnightly. Monthly with the
   existing refresh workflow is probably right; GTFS is a timetable and goes stale in a
   way BBR does not.
4. **Do we want the Smiley rating at all?** It is the only thing Smiley offers that OSM
   does not, and it carries a "must always be current" obligation.
5. **OSM freshness and completeness are not uniform.** Copenhagen is well mapped; rural
   Jutland is thinner. A count of 0 groceries in a rural postal code may mean "none
   mapped", not "none". Whatever we ship needs that caveat, as the BBR layers do.

## 9. Reproducing

```bash
python3 -m pip install requests osmium          # neither is currently a project dependency
python3 scripts/probe_services.py --only geofabrik --pbf   # 495 MB download, 87 s scan
python3 scripts/probe_services.py --only gtfs,smiley       # 55 MB + 60 MB
python3 scripts/probe_services.py --only overpass          # flaky, see §2
python3 scripts/probe_services.py --only cross             # the §6 comparisons
```

Downloads land in `data/raw/probe/` (gitignored) and are reused on a second run. The
merged findings are written to `data/raw/probe/probe_results.json`.

**`requests` is not used anywhere else in this repository** — every other script uses
stdlib `urllib.request`. If any of this graduates into the pipeline it should be ported
to `urllib`, or `requests` added as a declared dependency, rather than leaving one script
that silently needs a package the CI does not install.
