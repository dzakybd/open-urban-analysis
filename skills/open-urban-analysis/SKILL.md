---
name: open-urban-analysis
description: Answer questions about a city or neighbourhood from free OpenStreetMap data, with every route, distance and metric computed by OSMnx, NetworkX, GeoPandas and momepy. Walking and driving accessibility (network-distance isochrones to hospitals, schools, parks, markets, transit; who is beyond a travel-time limit, optionally weighted by population or by age group), POI coverage, street-network connectivity, walkability comparison as transparent metrics, road or bridge closure simulation, facility siting (where K new clinics or schools would reach the most people), store finding (people per mapped competitor), flood and evacuation (who is flooded or cut off from a dry shelter as the water rises) and a house report card (minutes to the nearest school, clinic, market and so on). No account or API key. Use when asked what is within 15 minutes on foot, who lacks access to a hospital, school, park, market or transit stop, where to put a new shop or clinic, how a flood or a closed road changes access, or how far everything is from a given house.
---

# Urban analysis from OpenStreetMap

Turn a question about a place ("where would a new minimarket reach the most people?", "who loses a dry road to a shelter if the water rises 1.5 m?") into numbers, maps and a figure. The agent only orchestrates: every route, distance and metric comes from the scripts, so a result can be reproduced.

- **Data:** OpenStreetMap through [OSMnx](https://github.com/gboeing/osmnx). Two backends, no key. A dated Geofabrik `.osm.pbf` (set `OUA_PBF`, clipped with `osmium`) for anything published, large (a whole regency) or that must reproduce. The live Overpass API for a quick ad hoc question on a small area: it is a shared volunteer service that is often at capacity, so the scripts wait for a free slot and cache every response in `~/.cache/open-urban-analysis` (set `OUA_CACHE` to move it). A first download of a 2 km area takes a few minutes. Do not loop over many places.
- **Population (optional):** GHSL GHS-POP R2023A, 100 m, 2020 (`--population`, the default) for all ages; WorldPop R2025A, 100 m, 2025, Indonesia only, for an age group (`--population worldpop --age 5-14`). Both are models, not censuses.
- **Elevation (flood only):** Copernicus DEM GLO-30 (30 m surface model) by default, or a DeltaDTM tile with `--dem`.
- **Routing:** NetworkX on the OSM street graph. Walking is 4.8 km/h (80 m a minute); driving uses free-flow speeds by road class (no traffic).
- **Metrics:** OSMnx (`basic_stats`) and momepy (meshedness, gamma).
- **Geocoding:** OpenStreetMap Nominatim (at most one request per second; geocode once and reuse `aoi.json`).
- **Licence:** map data (c) OpenStreetMap contributors, ODbL. Keep the attribution on every map and figure; the scripts add it.

Scripts live next to this file in `scripts/`. Run them with `uv run` (installs their dependencies on the fly). `SKILL_DIR` below means the directory containing this file, and `WORK` your work directory. Every analysis script writes `metrics.json`, GeoJSON, an interactive `map.html` (Folium) and a static `figure.png` into `--out`.

## What OSM can and cannot say

State these when you answer:

- **A gap is not a missing facility.** The scripts measure access to POIs that OSM has. A school, clinic or market that nobody mapped looks like a gap; one mapped in the wrong place looks like access. Markets and small clinics are the least complete categories. Say how many POIs were found and name them.
- **No sidewalk quality, shade, lighting, traffic speed or safety.** OSM has street geometry and tags. A street the map shows is not necessarily pleasant or safe to walk, and a street the map lacks (an alley, a gang) may exist.
- **Walking time is network distance at a fixed speed.** No stairs, no slope, no waiting to cross a road. Barriers that are mapped (rivers, rail, toll roads) are respected; barriers that are not are not.
- **Driving times are free-flow.** A trip on a busy day is longer than the minutes reported.
- **Areas are discs (or a boundary) on a 100 m grid.** "Share of the area" counts grid cells; cells more than 200 m from any street (water, rail yards) are left out and reported. It is area, not population, unless a population grid is used: a dense kampung and an empty golf course weigh the same.
- **Population is modelled.** GHSL and WorldPop are 100 m model grids, not censuses (GHSL counted about a quarter fewer people than the official figure in Demak). Where OSM has few roads, people more than 200 m from any mapped way are counted neither reached nor beyond: report shares of all people.
- **The elevation is a surface model, not terrain.** Copernicus GLO-30 includes roofs and trees, so built-up ground reads high and a flood is understated; heights are above the EGM2008 geoid, not local sea level.

## The six showcase cases (examples to copy)

`cases.sh` has the exact commands; each case is one script run on one place.

| # | Place and question | Script |
|---|---|---|
| 1 | Central Surabaya: where would a new minimarket reach the most people per mapped competitor? | `store.py` |
| 2 | Perumnas Minomartani, Sleman: minutes to school, clinic, market and the commute to UGM from one house | `report.py` |
| 3 | Kabupaten Demak: where would the next three puskesmas reach the most people? (plus `accessibility.py --mode drive` and `poi_coverage.py`) | `siting.py` |
| 4 | Kota Pekalongan: who is flooded or cut off from a dry shelter at 0.5, 1.0 and 1.5 m? | `flood.py` |
| 5 | Kota Makassar: who can an ambulance reach in 10 or 15 min? | `accessibility.py --mode drive --from-poi --population` |
| 6 | Kabupaten Sumba Barat Daya: which children 5-14 and people 60+ are beyond a 30-minute walk or drive of a school or health facility? | `accessibility.py --population worldpop --age` |

`network_stats.py`, `poi_coverage.py`, `walkability.py` and `closure.py` are capabilities of the skill that the showcase does not use as cases (except `poi_coverage.py` in Demak); they are documented below.

## 1. Pin the place: `locate.py`

```bash
uv run SKILL_DIR/scripts/locate.py "Kecamatan Gubeng, Surabaya" --radius-m 1500 --out WORK/aoi.json
uv run SKILL_DIR/scripts/locate.py --lat -7.27 --lng 112.745 --radius-m 2000 --name "Central Surabaya" --out WORK/aoi.json
uv run SKILL_DIR/scripts/locate.py --boundary WORK/demak.geojson --name "Kabupaten Demak" --out WORK/aoi.json
```

The area is a disc around the point; geocoding a district returns its centroid. For a whole regency or city, pass `--boundary` a GeoJSON polygon, for example the OSM admin relation cut from the extract with `osmium getid -r "$OUA_PBF" r<ID> -o b.osm.pbf && osmium export --geometry-types=polygon b.osm.pbf -o b.geojson` (`cases.sh` case 3 does this for Demak): official facility and population counts are per regency, so a boundary makes them comparable. `osmium export` also writes member islets as features: keep only the `boundary=administrative` one (`cases.sh` `boundary()`), and add `--mainland` to drop islands no road reaches. Use `--lat/--lng` for coordinates (a negative latitude written as `"-6.2,106.8"` is read as a flag). Compare places on discs of the same radius, so the areas are equal. 1.5-2 km is a good size for walking questions; larger areas are slow to download.

## 2. Pick the capability

| Question | Script | Output |
|---|---|---|
| How connected is the street network? | `network_stats.py` | street length and density, intersection density, node degree, dead ends, circuity, meshedness, gamma |
| How many minutes to the nearest hospital, school, park, market? What share of the area is beyond 15? | `accessibility.py` | per-category and combined shares at 5/10/15 min, isochrones, cells beyond the limit |
| How many POIs does the area have, and does a straight circle overstate reach? | `poi_coverage.py` | counts, density, median and p90 minutes, network vs straight-line reach |
| Which of two places is more walkable? | `walkability.py` | side-by-side metrics, no single score |
| What if this road or bridge closes? | `closure.py` | pairs slower or cut off, named-route detour with street names, cells losing access to a POI |
| Where should the next K facilities go? | `siting.py` | people beyond the limit today, K picks by greedy maximum coverage, people each pick adds |
| Where would a new shop reach the most people per competitor? | `store.py` | people within a walk of each candidate site, mapped competitors in that catchment, top K sites by people per store |
| If the water rises to a level, who loses a dry road to a shelter? | `flood.py` | people flooded and cut off at each water level, roads under water, by village |
| How far is everything from this house, and the commute? | `report.py` | per category minutes on foot, by bike and by car, nearest name, the commute by mode |

POI categories: `hospital`, `clinic`, `school`, `park`, `market`, `bus_stop`, `rail`, `transjakarta` (stops whose name, network, operator or brand mentions TransJakarta — in practice mostly Mikrotrans feeder vans, not BRT corridors), `puskesmas` (Indonesian public primary-care centres: any hospital, clinic or healthcare tag whose name says Puskesmas, because mappers tag them `amenity=clinic`, `amenity=hospital` or `healthcare=centre`; Puskesmas Pembantu sub-posts are left out). `hospital` is `amenity=hospital`, which in Indonesia also catches puskesmas, clinics, dental hospitals and maternity homes: drop them with `--exclude-name` and list what remains. Add a category in `scripts/common.py` (`CATEGORIES`, an OSM tag filter; `CATEGORY_MATCH` narrows it by a regex over the name) when a question needs another.

## 3. Street network: `network_stats.py`

```bash
uv run SKILL_DIR/scripts/network_stats.py WORK/aoi.json --mode walk --out WORK/network
```

Intersections within 10 m are merged before counting. Circuity is street length over straight-line distance between segment ends (1.0 is straight). Meshedness and gamma run from 0 (a tree) to 1 (every possible link). Walk networks include footways and paths; `--mode drive` gives the road network only.

## 4. Accessibility: `accessibility.py`

```bash
uv run SKILL_DIR/scripts/accessibility.py WORK/aoi.json --categories hospital,school,park,market --minutes 15 --out WORK/access
uv run SKILL_DIR/scripts/accessibility.py WORK/aoi.json --categories rail,bus_stop --minutes 10 --out WORK/transit
```

Multi-source Dijkstra from every POI over the street graph, run backwards so one-way streets count correctly. POIs up to 1,500 m outside the disc count, so the edge of the area is not penalised. Parks and hospital campuses are entered from points along their outline. Read `beyond_limit_pct` per category, `all_categories_within_limit_pct` (cells that reach every category in time), and the median and 90th-percentile minutes. `--mode drive` measures car access.

```bash
uv run SKILL_DIR/scripts/accessibility.py WORK/aoi.json --mode drive --from-poi --categories hospital --minutes 15 --population --out WORK/ambulance
uv run SKILL_DIR/scripts/accessibility.py WORK/aoi.json --categories school --minutes 30 --population worldpop --age 5-14 --out WORK/school
```

`--from-poi` times the trip out of the facility (an ambulance leaving a hospital) on the forward graph. `--population` weights cells by GHSL (all ages, 2020); `--population worldpop --age 5-14` (or `60+`; ages must fall on WorldPop's 0, 1-4, 5-9, ..., 90+ groups) by WorldPop R2025A 2025 people of that age, Indonesia only as written, about 160 MB downloaded once per five-year group. With a population, `within_<t>_min_population_pct` gives the share of people reached. The `health` category is any mapped health facility (hospital, puskesmas, pustu, clinic, village post): drop posyandu or sub-posts with `--exclude-name`. Every `metrics.json` lists its data `sources` (the OSM extract and snapshot, the population grid, licences).

## 5. POI coverage: `poi_coverage.py`

```bash
uv run SKILL_DIR/scripts/poi_coverage.py WORK/aoi.json --categories hospital,school,park,market,bus_stop,rail --out WORK/coverage
```

Counts and density per km², and `network_within_pct` against `straight_line_within_pct`: the share of the area a plain circle of the same reach would claim. The gap is what rivers, rail and missing streets remove.

## 6. Compare places: `walkability.py`

```bash
uv run SKILL_DIR/scripts/walkability.py WORK/place-a/aoi.json WORK/place-b/aoi.json --out WORK/walkability
```

Street density, intersection density, dead-end share, circuity, meshedness, pedestrian-only ways per km², mapped crossings per km², mapped sidewalk share of street length, and access to a school, market, park, clinic or hospital and transit stop within 5 and 10 minutes. **There is no combined score, on purpose:** a score hides which assumption decided the ranking. Tell the reader which metrics differ and which do not. The mapped-sidewalk share measures what mappers recorded: a low share often means unmapped, not absent.

## 7. Road or bridge closure: `closure.py`

```bash
uv run SKILL_DIR/scripts/closure.py WORK/aoi.json --mode drive --close-near=LAT,LNG,150 \
  --od "Town A|LAT,LNG|Town B|LAT,LNG" --poi hospital --out WORK/closure
```

Find the bridge's coordinates first (the news names it; look it up in Nominatim, then check the closed edge in `closed.geojson` and on `map.html`: a wrong match closes the wrong road). OSM often draws a bridge as a separate `man_made=bridge` polygon and leaves the road under it untagged, so `--bridge-only` can find nothing or the wrong span; close everything within a radius of the point instead (`--only-highway` narrows it to a road class). Check that routes actually change: a tight radius or `--bridge-only` can remove a few minor streets and change nothing, because alley bridges beside the span bypass it; a radius of about 150 m on every road is what cut the crossing in the case this was built on. Use `--classes trunk,primary,secondary,tertiary` to simulate a bus or truck that cannot use small streets. It removes the edges, then reports the share of random trips that got slower, the median, 90th-percentile and maximum extra minutes, how many are cut off, each named route before and after with the streets the detour uses, and the cells that lose access to the nearest POI of a category. **Compare the detour streets with the diversion the authorities announced.** If they disagree, say so: either OSM lacks a road they use, or the announced route avoids roads the model thinks are fine (width, weight limits, traffic).

## 8. Facility siting: `siting.py`

```bash
uv run SKILL_DIR/scripts/siting.py WORK/aoi.json --poi puskesmas --mode drive --threshold-min 15 --k 3 --population --out WORK/siting
```

Answers "where should the next K facilities go to reach the most people now beyond --threshold-min?". It times every 100 m cell to the nearest existing facility (reversed graph, like `accessibility.py`), takes as candidates the street nodes on trunk, primary, secondary or tertiary roads inside the area (one per 500 m square), and picks greedily: each pick is the candidate whose catchment holds the most still-unserved people (GHSL with `--population`, else cells). Read `beyond_limit_pct` and, per pick, `newly_covered`, `cumulative_share_of_unserved_pct` and `within_limit_after_pct`. **The existing facilities are the ones OSM has, so before reading a pick as a plan, check it against an official facility list:** in Demak OSM has 5 of the 27 official puskesmas, and the first two picks landed in Demak town and Mranggen, whose official puskesmas are simply not mapped. A pick there is a mapping to-do before it is a building site. Drive times are free-flow, and flooding that cuts roads is not modelled.

## 9. Store finder: `store.py`

```bash
uv run SKILL_DIR/scripts/store.py WORK/aoi.json --shop convenience --minutes 10 --k 5 --out WORK/store
```

Candidates are street nodes inside the area (one per 200 m square); a candidate's catchment is the cells that reach it within `--minutes` (reversed graph); competitors are the `--shop` POIs OSM has in that catchment; the score is people (GHSL) / (competitors + 1), top K at least 500 m apart. **It ranks people against mapped competitors, nothing else:** no rent, foot traffic, income or sales, and no public register of minimarkets to check OSM against. In central Surabaya OSM has 54 minimarkets for 251,522 people and every top site has none mapped nearby, which is more likely unmapped Indomaret and Alfamart branches than free ground. Say so, and say a site is a place to survey, not a profit forecast.

## 10. Flood and evacuation: `flood.py`

```bash
uv run SKILL_DIR/scripts/flood.py WORK/aoi.json --levels 0.5,1.0,1.5 --shelters school,mosque,hospital --out WORK/flood
```

A bathtub model: water at each level (metres above the EGM2008 geoid) floods every cell and every walking edge with a point below it (a bridge takes the height of its lower end), then each dry cell is timed to the nearest dry shelter over dry edges. Read `people_flooded`, `people_dry_but_cut_off` and, for each level, `cut_off_max_m_to_road_under_water` (every cut-off cell must sit near a road under water). Elevation is Copernicus GLO-30, a 30 m surface model (roofs and trees raise it, so the flood is understated); DeltaDTM (4TU.ResearchData, doi 10.4121/21997565, CC BY 4.0) is the terrain model made for coasts: pass a tile with `--dem` when you can download it. State the limits: no tide timing, drainage, sea walls, pumps or rainfall, a vertical datum that is not local sea level, a 2011-2015 DEM on a sinking coast, and shelters limited to what OSM has.

## 11. House report card: `report.py`

```bash
uv run SKILL_DIR/scripts/report.py WORK/aoi.json --work "UGM campus|-7.7705,110.3778" --exclude-name "puskesmas|klinik|gigi|bersalin|pijat|bekam" --out WORK/report
```

One row per category (never a combined score): minutes to the nearest mapped facility on foot, by bike (15 km/h on the walking network) and by car (free-flow), its OSM name, and how many are within `--minutes` on foot; with `--work`, the commute by each mode. Facilities are the ones OSM has, bus and rail rows are mapped stops, not service, and the commute is not public transport or traffic.

## Answering

Give the number, the place and radius, the categories and how many POIs OSM had for each, and the pictures that support it (`figure.png`, `map.html`). State the limits that apply (the section above), and never turn a mapped gap into a claim that a facility does not exist. For a closure, say the minutes are free-flow. Check a result against an independent source (an official facility list, a published diversion, a planning report) and say how well it matched; if the check is weak, say that too.
