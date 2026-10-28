---
name: open-urban-analysis
description: Answer questions about a city or neighbourhood from free OpenStreetMap data, with every route, distance and metric computed by OSMnx, NetworkX, GeoPandas and momepy. Walking accessibility (network-distance isochrones to hospitals, schools, parks, markets, transit; the 15-minute city), POI coverage, street-network connectivity (intersection density, circuity, node degree), walkability comparison between places as a set of transparent metrics, and road or bridge closure simulation (detour, lost access). No account or API key. Use when asked how walkable a place is, what is within 15 minutes on foot, who lacks access to a hospital, school, park, market or transit stop, how two neighbourhoods compare, or what happens if a road or bridge closes.
---

# Urban analysis from OpenStreetMap

Turn a question about a place ("what share of Tebet is within 15 minutes' walk of a hospital, school, park and market?", "what changes if this bridge closes?") into numbers, maps and a figure. The agent only orchestrates: every route, distance and metric comes from the scripts, so a result can be reproduced.

- **Data:** OpenStreetMap through [OSMnx](https://github.com/gboeing/osmnx) (Overpass API). No key. Overpass is a shared volunteer service: the scripts wait for a free slot and cache every response in `~/.cache/open-urban-analysis` (set `OUA_CACHE` to move it), so run a place once and reuse it. A first download of a 2 km area takes a few minutes. Do not loop over many places.
- **Routing:** NetworkX on the OSM street graph. Walking is 4.8 km/h (80 m a minute); driving uses free-flow speeds by road class (no traffic).
- **Metrics:** OSMnx (`basic_stats`) and momepy (meshedness, gamma).
- **Geocoding:** OpenStreetMap Nominatim (at most one request per second; geocode once and reuse `aoi.json`).
- **Licence:** map data (c) OpenStreetMap contributors, ODbL. Keep the attribution on every map and figure; the scripts add it.

Scripts live next to this file in `scripts/`. Run them with `uv run` (installs their dependencies on the fly). `SKILL_DIR` below means the directory containing this file, and `WORK` your work directory. Every analysis script writes `metrics.json`, GeoJSON, an interactive `map.html` (Folium) and a static `figure.png` into `--out`.

## What OSM can and cannot say

State these when you answer:

- **A gap is not a missing facility.** The scripts measure access to POIs that OSM has. A school, clinic or market that nobody mapped looks like a gap; one mapped in the wrong place looks like access. Markets and small clinics are the least complete categories. Say how many POIs were found and name them.
- **No sidewalk quality, shade, lighting, traffic speed or safety.** OSM has street geometry and tags. A street the map shows is not necessarily pleasant or safe to walk, and a street the map lacks (an alley, a gang) may exist.
- **Walking time is network distance at a fixed speed.** No stairs, no slope, no waiting to cross a road, no flooding. Barriers that are mapped (rivers, rail, toll roads) are respected; barriers that are not are not.
- **Driving times are free-flow.** A detour on a busy day is longer than the minutes reported.
- **Areas are discs on a 100 m grid.** "Share of the area" counts grid cells; cells more than 200 m from any street (water, rail yards) are left out and reported. It is area, not population: a dense kampung and an empty golf course weigh the same.

## 1. Pin the place: `locate.py`

```bash
uv run SKILL_DIR/scripts/locate.py "Menteng, Jakarta Pusat" --radius-m 1500 --out WORK/aoi.json
uv run SKILL_DIR/scripts/locate.py --lat -6.2615 --lng 106.8106 --radius-m 2000 --name Tebet --out WORK/aoi.json
```

The area is a disc around the point; geocoding a district returns its centroid. Use `--lat/--lng` for coordinates (a negative latitude written as `"-6.2,106.8"` is read as a flag). Compare places on discs of the same radius, so the areas are equal. 1.5-2 km is a good size for walking questions; larger areas are slow to download.

## 2. Pick the capability

| Question | Script | Output |
|---|---|---|
| How connected is the street network? | `network_stats.py` | street length and density, intersection density, node degree, dead ends, circuity, meshedness, gamma |
| How many minutes to the nearest hospital, school, park, market? What share of the area is beyond 15? | `accessibility.py` | per-category and combined shares at 5/10/15 min, isochrones, cells beyond the limit |
| How many POIs does the area have, and does a straight circle overstate reach? | `poi_coverage.py` | counts, density, median and p90 minutes, network vs straight-line reach |
| Which of two places is more walkable? | `walkability.py` | side-by-side metrics, no single score |
| What if this road or bridge closes? | `closure.py` | pairs slower or cut off, named-route detour with street names, cells losing access to a POI |

POI categories: `hospital`, `clinic`, `school`, `park`, `market`, `bus_stop`, `rail`, `transjakarta` (stops whose name, network, operator or brand mentions TransJakarta — in practice mostly Mikrotrans feeder vans, not BRT corridors). Add a category in `scripts/common.py` (`CATEGORIES`, an OSM tag filter; `CATEGORY_MATCH` narrows it by a regex over the name) when a question needs another.

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

## 5. POI coverage: `poi_coverage.py`

```bash
uv run SKILL_DIR/scripts/poi_coverage.py WORK/aoi.json --categories hospital,school,park,market,bus_stop,rail --out WORK/coverage
```

Counts and density per km², and `network_within_pct` against `straight_line_within_pct`: the share of the area a plain circle of the same reach would claim. The gap is what rivers, rail and missing streets remove.

## 6. Compare places: `walkability.py`

```bash
uv run SKILL_DIR/scripts/walkability.py WORK/menteng/aoi.json WORK/bsd/aoi.json --out WORK/walkability
```

Street density, intersection density, dead-end share, circuity, meshedness, pedestrian-only ways per km², mapped crossings per km², mapped sidewalk share of street length, and access to a school, market, park, clinic or hospital and transit stop within 5 and 10 minutes. **There is no combined score, on purpose:** a score hides which assumption decided the ranking. Tell the reader which metrics differ and which do not. The mapped-sidewalk share measures what mappers recorded: a low share often means unmapped, not absent.

## 7. Road or bridge closure: `closure.py`

```bash
uv run SKILL_DIR/scripts/closure.py WORK/aoi.json --mode drive --close-near=-8.0717,111.84665,150 \
  --od "Tulungagung|-8.0654,111.9030|Trenggalek|-8.0505,111.7090" --poi hospital --out WORK/closure
```

Find the bridge's coordinates first (the news names it; look it up in Nominatim, then check the closed edge in `closed.geojson` and on `map.html`: a wrong match closes the wrong road). OSM often draws a bridge as a separate `man_made=bridge` polygon and leaves the road under it untagged, so `--bridge-only` can find nothing or the wrong span; close everything within a radius of the point instead (`--only-highway` narrows it to a road class). Check that routes actually change: in the Gondang run `--bridge-only` within 80 m removed four minor streets and changed nothing, and closing only the trunk road within 30 m was bypassed through alley bridges beside it; 150 m on every road cut the crossing. Use `--classes trunk,primary,secondary,tertiary` to simulate a bus or truck that cannot use small streets. It removes the edges, then reports the share of random trips that got slower, the median, 90th-percentile and maximum extra minutes, how many are cut off, each named route before and after with the streets the detour uses, and the cells that lose access to the nearest POI of a category. **Compare the detour streets with the diversion the authorities announced.** If they disagree, say so: either OSM lacks a road they use, or the announced route avoids roads the model thinks are fine (width, weight limits, traffic).

## Answering

Give the number, the place and radius, the categories and how many POIs OSM had for each, and the pictures that support it (`figure.png`, `map.html`). State the limits that apply (the section above), and never turn a mapped gap into a claim that a facility does not exist. For a closure, say the minutes are free-flow. Check a result against an independent source (an official facility list, a published diversion, a planning report) and say how well it matched; if the check is weak, say that too.
