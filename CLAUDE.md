# open-urban-analysis

Address or coordinates + question -> OpenStreetMap street graph and POIs (OSMnx) -> routing and metrics (NetworkX, GeoPandas, momepy) -> numbers, Folium map, figure. Agent skill + Deep Agents runner. Free data, no keys.

## Stack
- Python >= 3.12, uv. Skill scripts are standalone (PEP 723, `uv run`), sharing `scripts/common.py`.
- Data: OpenStreetMap via OSMnx — set `OUA_PBF` to a dated Geofabrik `.osm.pbf` for the offline backend (clipped with `osmium`, cached in `~/.cache/open-urban-analysis`), otherwise the live Overpass API (cached in `~/.cache/open-urban-analysis`, override with `OUA_CACHE`), Nominatim for geocoding, optional GHSL GHS-POP R2023A 100 m population tiles (JRC, one ~20 MB tile per 1,000 km) or WorldPop R2025A 100 m age groups for Indonesia (`--population worldpop --age`, ~160 MB per five-year group, cached in `worldpop/`), Copernicus DEM GLO-30 tiles from the public AWS bucket for `flood.py` (or a DeltaDTM tile via `--dem`).
- Deep Agents (`deepagents`) on `_ChatOpenAICodex` from `langchain-openai==1.7.2` (ChatGPT sign-in, no API key).

## Commands
- Install: `uv sync`
- Format / lint: `uvx ruff format . && uvx ruff check .`
- Manual chain: see README "The pipeline"; the exact commands of the six showcase cases are in `cases.sh` (Surabaya store, Sleman report, Demak siting, Pekalongan flood, Makassar ambulance, Sumba Barat Daya by age).
- Agent: `uv run python agent/run.py runs/<name> "<question>" --effort low`
- Showcase Space: `uv run python space/build.py`, then upload `space/` (see below).

## Layout
- `skills/open-urban-analysis/`: the published skill. Dependencies: osmnx, geopandas, networkx, shapely, momepy, folium, matplotlib, numpy (+ rasterio only for `--population` and `flood.py`). Add a library only when a case needs it.
- `agent/run.py`: Deep Agents runner. `runs/`: outputs per case (map.html, metrics.json, GeoJSON, figure.png). `docs/`: references and figures. `space/`: static Hugging Face Space.

## Publishing
- GitHub: the `gh` / HTTPS credential is the work account. Push with `git push git@github-dzaky:dzakybd/open-urban-analysis.git main`.
- Space: run HF commands with `env -u HF_TOKEN` (stale token); the Homebrew `huggingface-cli` is broken, use `uvx --from huggingface_hub hf` or the Python API. Create the Space first with `create_repo(repo_type="space", space_sdk="static", exist_ok=True)`, then `upload_folder`.

## Project Learnings
- Overpass is a shared volunteer service and often answers 502 "at capacity". `common.with_retry` backs off and rotates mirrors; responses are cached, so rerun after a failure instead of looping. Never run several heavy downloads at once.
- A gap in OSM is not a gap on the ground: say how many POIs were found and that unmapped facilities look like missing ones. Markets and small clinics are the least complete.
- Compare places on discs of the same radius, and never fold walkability into one score: OSM has no sidewalk quality, shade or safety, and mapped sidewalk share mostly measures mapper effort.
- Run accessibility on the reversed graph (travel time TO the POI), so one-way streets count the right way round.
- argparse reads `"-8.06,111.88"` as a flag: write `--close-near=-8.06,111.88,60` with the `=`.
- Look at the rendered figure.png and map.html before reporting a result.
- In Indonesia `amenity=hospital` also tags puskesmas, clinics, dental hospitals and even massage parlours: list the hospital POIs and drop non-hospitals with `--exclude-name`; use the `puskesmas` category (name match) for primary care.
- `ghsl_population` returns people per 100 m cell at each point, so population totals are only right on the 100 m grid: keep `--spacing-m 100` with `--population`.
- A regency is compared with official counts on its boundary (`locate.py --boundary`), not a disc. A regency-wide drive run takes about 6 min per script (graph built from the clipped XML each time).
- `osmium export` of an admin relation also writes its member islets as features: keep only the `boundary=administrative` feature (`cases.sh` `boundary()`), or `locate.py --boundary` takes an islet.
- data.worldpop.org refuses HTTP range requests, so a WorldPop GeoTIFF cannot be windowed over `/vsicurl/`: download each age group whole (once, cached).
- In a sparsely mapped regency (Sumba Barat Daya) 38-43% of the people live more than 200 m from any mapped way and are counted neither reached nor beyond: report shares of all people (`total_in_area`), not only of `total_on_network`.
- A run's outputs go stale when its script changes: Pekalongan's road-under-water figure fell from 126 km to 11 km after the bridge fix. Delete the run directory and rerun before reading or quoting a `metrics.json`.
- `data.4tu.nl` (DeltaDTM) timed out from this machine on 1 Nov 2026: flood runs use Copernicus GLO-30 and say so; pass a DeltaDTM tile with `--dem` when reachable.
