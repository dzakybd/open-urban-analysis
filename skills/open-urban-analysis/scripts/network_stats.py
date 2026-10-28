# /// script
# requires-python = ">=3.10"
# dependencies = ["osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "momepy>=0.9", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Street network connectivity of an area: street length and density, intersection density, node degree, dead ends,
circuity, meshedness and gamma.

    uv run network_stats.py work/aoi.json --mode walk --out work/network

Intersections within 10 m of each other are merged before counting (a dual carriageway crossing is one intersection).
Circuity is street length over straight-line distance between segment ends (1.0 = perfectly straight). Meshedness
and gamma (momepy) measure how many loops the network has against a tree: 0 = a tree, 1 = fully connected.
Writes metrics.json, streets.geojson, map.html and figure.png. Streets are only as complete as OSM: unmapped alleys
(gang) lower density and raise circuity.
"""

import argparse
import json

import common as c
import folium
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--mode", choices=["walk", "drive"], default="walk")
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    c.outdir(args.out)
    aoi = c.load_aoi(args.aoi)
    full = c.fetch_graph(aoi, args.mode, buffer_m=1500)  # same download as the other scripts, so it is cached
    G = ox.truncate.truncate_graph_polygon(
        full, c.project_polygon(aoi["polygon"], full.graph["crs"]), truncate_by_edge=True
    )
    metrics = {"place": aoi["name"], "mode": args.mode, **c.street_metrics(G, aoi)}
    metrics["caveat"] = "Computed from OpenStreetMap; unmapped streets and alleys lower density and raise circuity."
    nodes, edges = ox.graph_to_gdfs(G)
    keep = ["name", "highway", "length", "geometry"]
    edges = edges.reset_index(drop=True)
    edges["highway"] = edges["highway"].astype(str)
    edges["name"] = edges["name"].astype(str) if "name" in edges else ""
    edges["length"] = edges["length"].round(1)
    edges[keep].to_crs(4326).to_file(f"{args.out}/streets.geojson", driver="GeoJSON")
    c.save_json(metrics, f"{args.out}/metrics.json")

    title = args.title or f"{aoi['name']}: street network"
    m = c.base_map(aoi)
    folium.GeoJson(edges[keep].to_crs(4326).__geo_interface__, name="Streets",
                   style_function=lambda _: {"color": "#2b6cb0", "weight": 1.5},
                   tooltip=folium.GeoJsonTooltip(["name", "highway", "length"])).add_to(m)  # fmt: skip
    deg = dict(G.to_undirected().degree())
    inter = nodes[[deg[n] >= 3 for n in nodes.index]].to_crs(4326)
    fg = folium.FeatureGroup(name="Intersections (3+ streets)", show=False)
    for geom in inter.geometry:
        folium.CircleMarker([geom.y, geom.x], radius=2, color="#d73027", weight=0, fill=True, fill_opacity=0.8).add_to(
            fg
        )
    fg.add_to(m)
    c.finish_map(m, f"{args.out}/map.html", title)

    fig, (ax, tx) = plt.subplots(1, 2, figsize=(11, 6), dpi=160, gridspec_kw={"width_ratios": [1.6, 1]})
    c.draw_streets(ax, G, color="#555", lw=0.6)
    cols = np.array([deg[n] for n in nodes.index])
    big = cols >= 3
    ax.scatter(nodes.geometry.x[big], nodes.geometry.y[big], s=6, c="#d73027", lw=0, zorder=4)
    c.frame(
        ax, G, aoi, title, f"{metrics['intersections']} intersections · {metrics['street_length_km']} km of streets"
    )
    tx.axis("off")
    rows = [("Area", f"{metrics['area_km2']} km²"), ("Street length", f"{metrics['street_length_km']} km"),
            ("Street density", f"{metrics['street_density_km_per_km2']} km/km²"),
            ("Intersection density", f"{metrics['intersection_density_per_km2']} /km²"),
            ("Avg node degree", metrics["avg_node_degree"]), ("Dead ends", f"{metrics['dead_end_share_pct']}%"),
            ("Circuity", metrics["circuity"]), ("Meshedness", metrics["meshedness"]), ("Gamma", metrics["gamma"])]  # fmt: skip
    for i, (k, v) in enumerate(rows):
        y = 0.92 - i * 0.095
        tx.text(0, y, k, fontsize=11, color="#555", transform=tx.transAxes)
        tx.text(1, y, str(v), fontsize=12, fontweight="bold", ha="right", transform=tx.transAxes)
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. {args.mode} network.", ha="right", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"{args.out}/figure.png")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
