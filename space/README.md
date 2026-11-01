---
title: open-urban-analysis
emoji: 🏙️
colorFrom: blue
colorTo: gray
sdk: static
pinned: false
license: mit
short_description: "Store siting, flood, ambulance, age access in Indonesia"
---

# open-urban-analysis showcase

Ask a question about a city, get an answer from free OpenStreetMap data. Street networks, walking isochrones and routing computed with OSMnx, NetworkX, GeoPandas and momepy, with Folium maps. No account and no API key.

Six cases in Indonesia: where to put a new store (Surabaya), a house report card (Sleman), where the next puskesmas goes (Demak), flood and evacuation (Pekalongan), ambulance coverage (Makassar) and who is underserved by age (Sumba Barat Daya). The Demak siting case is checked against Statistics Indonesia's (BPS) published puskesmas count and the Sumba schools against the Kemendikdasmen/Dapodik reference table; the other cases are what OSM itself records, and each view says where a check is missing or only partial. Each view has the interactive map, the numbers, the figure and the sources. The page calls no model.

Two versions: a skill for coding agents (`npx skills add dzakybd/open-urban-analysis`) and a LangChain Deep Agents version for your own agent workflow. Code: [github.com/dzakybd/open-urban-analysis](https://github.com/dzakybd/open-urban-analysis).

OpenStreetMap can lack facilities that exist: a gap in a map is not proof that a facility is missing. Map data © OpenStreetMap contributors (ODbL). Population: GHSL GHS-POP R2023A (JRC) and WorldPop R2025A (CC BY 4.0). Elevation: Copernicus DEM GLO-30. Code: MIT.
