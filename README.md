# open-urban-analysis

A skill you attach to an agent so it can answer a question about a city from free OpenStreetMap data (the same pattern as [open-satellite-analysis](https://github.com/dzakybd/open-satellite-analysis)). Give an address or coordinates and a question ("what share of this district is within a 15-minute walk of a hospital, school, park and market?", "what happens if this bridge closes?", "is this neighbourhood walkable?"). The skill builds the street graph and POIs with [OSMnx](https://github.com/gboeing/osmnx), computes every route, isochrone and metric with NetworkX, GeoPandas and momepy, and writes numbers, a Folium map and a figure. No account and no API key.

![Tebet, South Jakarta: walking isochrones to hospitals, schools, parks and markets, with the share of the area beyond 15 minutes](runs/tebet/access/figure.png)

Two versions:

1. **A skill for coding agents** (Claude Code, Codex and others that load `SKILL.md` skills): `npx skills add dzakybd/open-urban-analysis`
2. **A LangChain Deep Agents version** you can run in your own agent workflow (`agent/run.py`)

See all five cases without installing anything: the static Space under `space/` (upload instructions at the bottom), each with its interactive map, figure, numbers and sources.

## Five cases, each checked against an independent source

| Question | Place | Scripts | Result |
|---|---|---|---|
| Who is within a 15-minute walk of a hospital, school, park and market? | Tebet, South Jakarta, 1.5 km disc | `accessibility.py`, `network_stats.py`, `poi_coverage.py` | 65.4% of the area reaches all four; 44,245 residents (35.2%) miss at least one. Hospital is the binding gap: 70.8% |
| What if the bridge closes? | Jembatan Gondang I, Tulungagung–Trenggalek national road, closed 2 Jun 2026 | `closure.py` | Car: 20.5% of trips slower, median +3.6 min. Bus on classified roads: median +8.6 min, worst +37 min, detour through the same southern loop the police announced |
| Which neighbourhood is more walkable? | Menteng (1920s) vs BSD City (2000s), equal 1.5 km discs | `walkability.py` | Menteng: 400 intersections/km², 4.35 of 5 essentials within 10 min. BSD: 319/km², 1.66. No single score, on purpose |
| Is this a transit desert? | Jagakarsa vs Dukuh Atas (benchmark), 2 km discs | `accessibility.py` | Rail within 10 min: 0% vs 34.8%. TransJakarta-tagged stops (mostly Mikrotrans feeders): 93% vs 95% |
| Who lives beyond a 10-minute walk of a park? | Tambora, West Jakarta, 1.5 km disc | `accessibility.py --population` | 70.9% within 10 min; 54,350 people (30.0%) beyond it |

The independent sources for the closure are news reports of the announced diversion (detik, Kompas, Antara, links below); for the others it is what the data itself records, stated as such. Where a check is weak or absent, the text says so.

## What it adds over a plain OSMnx query

OSMnx already downloads graphs and POIs. This skill covers the steps around it, where agents tend to go wrong:

- **Network distance, not straight-line circles.** A 1,200 m circle around a rail station claims 91% of Tebet; along the streets it is 48% (`runs/tebet/coverage`), because rivers, rail corridors and the toll road are barriers.
- **One-way streets counted the right way round.** Accessibility runs the Dijkstra on the reversed graph (travel time *to* the POI), so one-way segments and turn restrictions do not fake symmetry.
- **Reproducible downloads.** Set `OUA_PBF` to a dated [Geofabrik](https://download.geofabrik.de) extract and the graph and POIs are clipped out of it with `osmium` — no shared Overpass server, no drift between runs. The published runs use `java-latest.osm.pbf` of 27 Oct 2026.
- **A bridge is not an edge.** OSM draws many bridges as `man_made=bridge` polygons with the road untagged underneath, and side alleys bypass a single-span closure. The closure script closes a radius, checks the removed edges, and verifies named routes actually change (`--landmark` distances against the announced diversion).
- **POIs are entered from their outline.** Parks and hospital campuses are reached from points along their perimeter, not from a centroid across a fence.
- **Weighted by who lives there, optionally.** `--population` adds GHSL GHS-POP 100 m counts to every coverage number: 35.2% of Tebet's residents, not 34.6% of its cells.
- **No walkability score.** The comparison script prints ten transparent metrics side by side. A single score would hide which assumption decided the ranking.
- **The tag is not the thing.** Every case states what OSM's tags can and cannot say (see Limits).

## Install the skill

```bash
npx skills add dzakybd/open-urban-analysis
```

Or copy `skills/open-urban-analysis/` into your harness's skills folder. The scripts run with `uv run` and install their own dependencies (OSMnx, GeoPandas, NetworkX, momepy, folium, matplotlib; `osmium-tool` and `rasterio` only for the offline backend and population weighting).

## The pipeline

| Step | Script | Output |
|---|---|---|
| 1. Pin the place | `locate.py` (Nominatim, or `--lat/--lng`) | `aoi.json` |
| 2. Street network | `network_stats.py` | street length/density, intersection density, dead ends, circuity, meshedness, gamma; `streets.geojson` |
| 3. Walking (or driving) access | `accessibility.py` | per-category % within 5/10/15 min, isochrones, cells beyond the limit, optional GHSL population; `isochrones.geojson` |
| 4. POI coverage | `poi_coverage.py` | counts and density per km², network vs straight-line reach |
| 5. Compare places | `walkability.py` | ten side-by-side metrics on equal discs, no score |
| 6. Closure simulation | `closure.py` | detours for random and named trips, `--landmark` check against the announced diversion, cells losing access |
| 7. Share a result | every script | `metrics.json`, `map.html` (Folium), `figure.png` (matplotlib) |

`cases.sh` runs the five showcase cases end to end; each step is skipped when its `metrics.json` exists, so reruns read the cache. The Overpass backend caches responses in `~/.cache/open-urban-analysis`; the offline backend caches `osmium` extracts there too (`OUA_CACHE` moves both).

## The cases

### 1. The 15-minute city: Tebet, South Jakarta

`runs/tebet/` — a 1.5 km disc, 7.07 km², 125,859 residents (GHSL 2020), walking at 4.8 km/h, 15-minute limit.

| Category | POIs mapped in area | ≤ 15 min | Median walk | People beyond |
|---|---|---|---|---|
| Hospital | 7 | 70.8% | 11.5 min | 37,258 |
| School | 79 | 99.7% | 3.1 min | 334 |
| Park | 23 | 97.2% | 7.3 min | 4,543 |
| Market | 5 | 89.7% | 9.2 min | 13,203 |

65.4% of the area reaches all four within 15 minutes; 0.1% reaches none. The hospital figure is the honest one *after* a fix: one dental clinic ("Ocean Dental Tebet") is tagged `amenity=hospital` in OSM, and counting it lifts coverage to 80.4% (`runs/tebet/access-raw` is the run without the exclusion, kept as the sensitivity check).

![Tebet hospital coverage](runs/tebet/access/figure.png)

`network_stats.py` on the same disc: 409.8 km of streets (58.0 km/km²), 532.6 intersections/km², 11.9% dead ends, circuity 1.093, meshedness 0.186. `poi_coverage.py`: 231 mapped POIs in 7 categories; the rail gap is the starkest straight-line overstatement (48% network vs 91% circle).

**Backend check.** `runs/tebet/access-overpass-check` is the same run against the live Overpass API instead of the dated PBF: identical POI counts, all-category coverage 61.6% vs 65.4%. The two graph builders disagree on a few short links (foot-access and service-street filtering), and Overpass is two days of edits ahead of the snapshot; read any single percentage with a ±4 pp band.

### 2. Bridge closure: Jembatan Gondang I

`runs/gondang/` — the bridge on the Tulungagung–Trenggalek national road (Desa Bendungan, Kecamatan Gondang) closed for rebuilding on 2 June 2026, announced until 11 December. Two simulations on the 8 km drive network around it, with the same closure (`--close-near=-8.0717,111.84665,150`: every road edge within 150 m — the OSM way is a `man_made=bridge` polygon with alley bridges beside it, so a tighter radius gets bypassed).

| Scenario | Trips slower > 1 min | Median extra | p90 | Max | Cut off |
|---|---|---|---|---|---|
| Car, every OSM road | 20.5% | +3.6 min | +4.0 min | +8.2 min | 0% |
| Bus, trunk/primary/secondary/tertiary only (`--classes`) | 14.7% | +8.6 min | +16.0 min | +37.2 min | 1.6% |

Named routes (Terminal Gayatri Tulungagung → Durenan, Trenggalek; Tulungagung → Trenggalek) gain 3.6–3.7 min by car and 8.1 min by bus. The bus detour swings 3.4–3.6 km away from the bridge and 1.0 km closer to Campurdarat: it runs south through the Campurdarat–Pakel loop.

**Against the announced diversion.** The police sent light vehicles through the small lanes around Mojoarum–Kalangbret and heavy vehicles (buses, six-wheel trucks) south via Simpang Tamanan–Campurdarat–Pakel–Bandung, about 10 km longer ([detik, 2 Jun 2026](https://www.detik.com/jatim/berita/d-8514918/jembatan-gondang-ditutup-total-6-bulan-ini-jalur-alternatifnya); [Antara, 2 Jun 2026](https://www.antaranews.com/berita/5591581/jalan-nasional-tulungagung-trenggalek-ditutup-total); [Kompas, 2 Jun 2026](https://surabaya.kompas.com/read/2026/06/02/220053378/jembatan-gondang-tulungagung-ditutup-hingga-desember-2026-ini-jalur); [Kompas on the bus rerouting, 9 Jun 2026](https://surabaya.kompas.com/read/2026/06/09/151706378/jalur-dialihkan-akibat-proyek-jembatan-gondang-tarif-bus-trenggalek)). The model reproduces the split without being told which roads are which: the car detour uses the same small lanes north of the river, and on classified roads only it finds the same southern loop. The bridge reopened to traffic on 24 Oct 2026 while finishing works continue ([Antara Jatim](https://jatim.antaranews.com/berita/1110811/jembatan-gondang-tulungagung-dibuka-untuk-umum)) — the simulation describes the closure period.

![Gondang bus detour](runs/gondang/closure-bus/figure.png)

**Failure cases that shaped the tool.** `--bridge-only` within 80 m removed four minor streets and changed no route (the road under the bridge polygon is untagged, so nothing matched the real span). Closing only the trunk road within 30 m was bypassed through the alley bridges within metres. Both are why the script closes a radius and prints the removed edges and `--landmark` distances for verification.

### 3. Walkability compared: Menteng vs BSD City

`runs/walkability/` — equal 1.5 km discs, one metric table, no score.

| Metric | Menteng | BSD City |
|---|---|---|
| Street density | 49.3 km/km² | 41.6 km/km² |
| Intersection density | 400.1 /km² | 318.9 /km² |
| Dead-end share | 10.8% | 11.1% |
| Circuity | 1.083 | 1.136 |
| Meshedness | 0.193 | 0.126 |
| Pedestrian-only ways | 9.5 km/km² | 7.7 km/km² |
| Mapped crossings | 26.4 /km² | 7.6 /km² |
| Mapped sidewalks | 4.9% of length | 2.7% |
| Essentials within 10 min | 4.35 of 5 | 1.66 of 5 |
| All 5 within 10 min | 49.6% | 2.8% |

![Menteng vs BSD walkability](runs/walkability/compare/figure.png)

The maps show why: Menteng is a fine-grained grid with schools and markets inside the blocks; BSD is cul-de-sac clusters feeding arterial loops, with big plotted blocks still undeveloped inside the disc. **What the check cannot say:** the sidewalk and crossing numbers measure mapper effort as much as pavement — Jakarta is far better mapped than a 2000s new town — and OSM records nothing about shade, width, traffic speed or safety. The essentials gap (4.35 vs 1.66) is the metric least affected by mapping effort, and it agrees with the street pattern.

### 4. Transit access: Jagakarsa vs Dukuh Atas

`runs/transit/` and `runs/transit-benchmark/` — equal 2 km discs, 10-minute walk limit, stops = OSM rail stations, stops tagged TransJakarta, and all bus stops.

| | Jagakarsa | Dukuh Atas (benchmark) |
|---|---|---|
| Rail | 0% (0 stops mapped) | 34.8% (10 stops, median 12.4 min) |
| TransJakarta-tagged stops | 93% (121) | 95.1% (185) |
| Any bus stop | 93% (126) | 95.6% (197) |

![Jagakarsa transit access](runs/transit/access/figure.png)

The pairing makes the tags visible: Jagakarsa has no rail in OSM and 93% "TransJakarta" coverage because **Mikrotrans feeder vans are tagged `network=TransJakarta`** — the category matches the network tag, so it measures the minibus feeder web, not BRT corridors. The desert is real but specific: no rapid transit within a 10-minute walk, while feeder stops are dense. The benchmark disc shows what the same measure reads at the city's main hub — and how high the bar is: even around Dukuh Atas, where four rail lines and the BRT corridors meet, only 34.8% of the disc is within a 10-minute walk of a rail stop, because a 2 km disc is big and stations are few. Cross-checked against [TransJakarta's published corridor map](https://transjakarta.co.id/peta-rute/) for the corridors — the feeder-stop counts are OSM-only and not independently checked.

### 5. Green space with population: Tambora

`runs/green/` — 1.5 km disc, 10-minute walk, parks weighted by the GHSL population grid.

Tambora packs about 181,000 people (GHSL 2020) into the 7.07 km² disc — roughly 25,600 per km², among the densest ground in Jakarta — and its mapped parks are small pocket greens clustered toward the disc's edge. 70.9% of the area is within a 10-minute walk of one; the 29.1% beyond is the white core on the figure, and it is where most of the people are: **54,350 residents (30.0%)** live farther than a 10-minute walk from any mapped park. Median walk 7.7 min, 90th percentile 12.8 min. Parks are entered from points along their outline, so a fenced or gated green counts where its gate is. No independent ground truth exists for park access here; the number is what OSM records, and small neighbourhood fields and RT-level open spaces are exactly what mappers most often leave out.

![Tambora park access](runs/green/access/figure.png)

## Deep Agents runner (ChatGPT sign-in)

```bash
uv sync
# once: sign in with your ChatGPT account (no API key)
uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"

uv run python agent/run.py runs/my-question \
  "What share of Tebet, South Jakarta is within a 15-minute walk of a hospital, school, park and market? Use -6.2345, 106.8560 with a 1.5 km radius."
```

The agent loads the same `SKILL.md`, runs the scripts in the work directory, and writes `answer.md` and `run.json` (time, tool calls, tokens).

## Limits of OSM data

- **A gap is not a missing facility.** The scripts measure access to POIs that OSM has. A school, clinic or market nobody mapped looks like a gap; one mapped in the wrong place looks like access. Markets and small clinics are the least complete; every answer says how many POIs were found and names them.
- **No sidewalk quality, shade, lighting, traffic speed or safety.** Mapped sidewalk share mostly measures mapper effort, as the Menteng–BSD comparison shows.
- **Walking time is network distance at 4.8 km/h.** No stairs, slope, crossing waits or flooding. Mapped barriers (rivers, rail, toll roads) are respected; unmapped ones are not.
- **Driving times are free-flow.** Closure detours on a busy day are longer than the minutes reported, and a missing back road in OSM makes detours look longer than they are.
- **Areas are discs on a 100 m grid.** Cells more than 200 m from any street are dropped and reported. It is area, not people, unless `--population` is used — and GHSL is a model, not a census.
- **The offline backend and Overpass agree to a few percentage points** (65.4% vs 61.6% on the Tebet all-category metric), from graph-filter differences and OSM edits between the snapshot and the live API.

## Data and licences

- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL, via OSMnx (Overpass API) and dated [Geofabrik](https://download.geofabrik.de) extracts.
- Geocoding: OpenStreetMap [Nominatim](https://nominatim.org).
- Population: [GHSL GHS-POP R2023A](https://ghsl.jrc.ec.europa.eu/ghs_pop.php) 100 m (JRC), 2020 epoch, a modelled grid.

Code: MIT.

## Built on

- [OSMnx](https://github.com/gboeing/osmnx), [NetworkX](https://networkx.org), [GeoPandas](https://geopandas.org), [momepy](https://github.com/urbangrammarai/momepy), [folium](https://github.com/python-visualization/folium), matplotlib.
- [osmium-tool](https://osmcode.org/osmium-tool/) for clipping the offline extracts.
- Copernicus GHSL population grid (European Commission, JRC).
- [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) and the [skills CLI](https://github.com/vercel-labs/skills).

## Space

The static showcase under `space/` is packed from the runs by:

```bash
uv run python space/build.py
```

which reads every number from the runs' own `metrics.json` into `space/data/`, then upload the folder to a Hugging Face static Space (`create_repo(repo_type="space", space_sdk="static")`, then `upload_folder`).
