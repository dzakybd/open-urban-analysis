# open-urban-analysis

Address or coordinates + question -> OpenStreetMap street graph and POIs (OSMnx) -> routing and metrics (NetworkX, GeoPandas, momepy) -> numbers, Folium map, figure. Agent skill + Deep Agents runner. Free data, no keys.

## Stack
- Python >= 3.12, uv. Skill scripts are standalone (PEP 723, `uv run`), sharing `scripts/common.py`.
- Data: OpenStreetMap via OSMnx — set `OUA_PBF` to a dated Geofabrik `.osm.pbf` for the offline backend (clipped with `osmium`, cached in `~/.cache/open-urban-analysis`), otherwise the live Overpass API (cached in `~/.cache/open-urban-analysis`, override with `OUA_CACHE`), Nominatim for geocoding, optional GHSL GHS-POP R2023A 100 m population tiles (JRC, one ~20 MB tile per 1,000 km).
- Deep Agents (`deepagents`) on `_ChatOpenAICodex` from `langchain-openai==1.7.2` (ChatGPT sign-in, no API key).

## Commands
- Install: `uv sync`
- Format / lint: `uvx ruff format . && uvx ruff check .`
- Manual chain: see README "The pipeline"; every case's exact commands are in `cases.sh`.
- Agent: `uv run python agent/run.py runs/<name> "<question>" --effort low`
- Showcase Space: `uv run python space/build.py`, then upload `space/` (see below).

## Layout
- `skills/open-urban-analysis/`: the published skill. Dependencies: osmnx, geopandas, networkx, shapely, momepy, folium, matplotlib, numpy (+ rasterio only for `--population`). Add a library only when a case needs it.
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
