# /// script
# requires-python = ">=3.10"
# dependencies = ["osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "momepy>=0.9", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Compare the walkability of two or more places as a transparent set of metrics. There is no single score: each
number says what it measures, and you decide what matters.

    uv run walkability.py work/menteng/aoi.json work/bsd/aoi.json --out work/walkability

Per place, on discs of equal radius: street density, intersection density, dead-end share, circuity and meshedness of
the walking network; pedestrian-only ways per km²; mapped crossings per km²; the share of drivable street length
with a mapped sidewalk; and the share of the area within 5 and 10 minutes' walk of a school, a market, a park, a
clinic or hospital, and a transit stop. Writes metrics.json, one map per place, streets.geojson per place and a
side-by-side figure.png.

Limits that matter: OpenStreetMap has no sidewalk quality, width, shade, traffic speed, lighting or safety, and
sidewalks and crossings are only as complete as local mappers made them (a low mapped-sidewalk share often means
unmapped, not absent). Read the numbers as 'what the map shows', not 'how pleasant it is to walk'.
"""

import argparse
import json
import re

import common as c
import folium
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox

ESSENTIALS = ["school", "market", "park", "clinic", "transit"]
PED_WAYS = ("footway", "pedestrian", "path", "steps", "living_street")


def has(v, *words):
    s = str(v)
    return any(w in s for w in words)


def sidewalk_share(edges):
    """Share of drivable-street length (not footways) that has any sidewalk tag other than 'no'/'none'."""
    drive = edges[~edges.highway.map(lambda h: has(h, *PED_WAYS))]
    tagged = np.zeros(len(drive), bool)
    for col in ("sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"):
        if col in drive:
            tagged |= drive[col].map(lambda v: str(v) not in ("nan", "None", "no", "none", "['no']")).to_numpy()
    total = drive.length.sum()
    return float(drive.length[tagged].sum() / total * 100) if total else float("nan")


def analyse(aoi_path, out):
    aoi = c.load_aoi(aoi_path)
    slug = re.sub(r"[^a-z0-9]+", "-", aoi["name"].lower()).strip("-")[:40]
    G = c.fetch_graph(aoi, "walk", buffer_m=1500)
    inside = c.project_polygon(aoi["polygon"], G.graph["crs"])
    nodes, edges = ox.graph_to_gdfs(G)
    # network metrics on the part of the graph inside the area
    Gi = ox.truncate.truncate_graph_polygon(G, inside, truncate_by_edge=True)
    sm = c.street_metrics(Gi, aoi)
    area = sm["area_km2"]
    e_in = edges[edges.intersects(inside)].copy()
    ped_km = float(e_in[e_in.highway.map(lambda h: has(h, *PED_WAYS))].length.sum() / 1000)
    crossings = int(
        sum(
            1
            for n, d in G.nodes(data=True)
            if d.get("highway") == "crossing" and inside.contains(nodes.loc[n].geometry)
        )
    )
    # access
    cat_map = {
        "school": ["school"],
        "market": ["market"],
        "park": ["park"],
        "clinic": ["hospital", "clinic"],
        "transit": ["bus_stop", "rail"],
    }
    needed = sorted({x for v in cat_map.values() for x in v})
    res = c.compute_access(aoi, needed, "walk", 1500, c.WALK_KMH, 100, G=G)
    on = res["grid"]["on_network"]
    access = {}
    per_cell = []
    for name, members in cat_map.items():
        mins = np.min([res["cats"][k]["minutes"] for k in members], axis=0)
        per_cell.append(mins[on])
        access[name] = {
            "within_5_min_pct": round(c.share_within(mins, on, 5), 1),
            "within_10_min_pct": round(c.share_within(mins, on, 10), 1),
            "mapped_in_area": sum(c.poi_counts(aoi, res["cats"][k]["pois"])["in_area"] for k in members),
        }
    n10 = (np.array(per_cell) <= 10).sum(axis=0)
    metrics = {
        "place": aoi["name"],
        "slug": slug,
        **sm,
        "pedestrian_ways_km_per_km2": round(ped_km / area, 1),
        "mapped_crossings_per_km2": round(crossings / area, 1),
        "mapped_sidewalk_share_of_street_length_pct": round(sidewalk_share(e_in), 1),
        "mean_essentials_within_10_min": round(float(n10.mean()), 2),
        "essentials_listed": ESSENTIALS,
        "cells_with_all_5_within_10_min_pct": round(float((n10 == len(ESSENTIALS)).mean() * 100), 1),
        "cells_with_none_within_10_min_pct": round(float((n10 == 0).mean() * 100), 1),
        "access": access,
    }
    keep = ["name", "highway", "length", "geometry"]
    e_out = e_in.reset_index(drop=True)
    e_out["highway"] = e_out["highway"].astype(str)
    e_out["name"] = e_out["name"].astype(str) if "name" in e_out else ""
    e_out[keep].to_crs(4326).to_file(f"{out}/{slug}-streets.geojson", driver="GeoJSON")
    m = c.base_map(aoi)
    folium.GeoJson(e_out[keep].to_crs(4326).__geo_interface__, name="Walking network", style_function=lambda _: {"color": "#2b6cb0", "weight": 1.3},
                   tooltip=folium.GeoJsonTooltip(["name", "highway", "length"])).add_to(m)  # fmt: skip
    for cat in needed:
        c.add_pois(m, res["cats"][cat]["pois"], c.COLORS[cat], cat)
    c.finish_map(m, f"{out}/{slug}-map.html", f"{aoi['name']}: walking network and POIs")
    return aoi, G, res, metrics


ROWS = [
    ("Street density", "street_density_km_per_km2", "km/km²"),
    ("Intersection density", "intersection_density_per_km2", "/km²"),
    ("Dead-end share", "dead_end_share_pct", "%"),
    ("Circuity", "circuity", ""),
    ("Meshedness", "meshedness", ""),
    ("Pedestrian-only ways", "pedestrian_ways_km_per_km2", "km/km²"),
    ("Mapped crossings", "mapped_crossings_per_km2", "/km²"),
    ("Mapped sidewalks", "mapped_sidewalk_share_of_street_length_pct", "% of street length"),
    ("Essentials within 10 min", "mean_essentials_within_10_min", "of 5 types"),
    ("All 5 within 10 min", "cells_with_all_5_within_10_min_pct", "% of area"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi", nargs="+")
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    c.outdir(args.out)

    runs = [analyse(p, args.out) for p in args.aoi]
    areas = [r[3]["area_km2"] for r in runs]
    doc = {"places": [r[3] for r in runs],
           "caveat": "OSM has no sidewalk quality, width, shade, lighting, traffic speed or safety; mapped sidewalks and crossings are only as complete as local mappers made them. No single score is computed on purpose.",
           "area_km2": areas}  # fmt: skip
    c.save_json(doc, f"{args.out}/metrics.json")

    n = len(runs)
    fig = plt.figure(figsize=(6.2 * n, 11), dpi=160)
    gs = fig.add_gridspec(2, n, height_ratios=[1.15, 1])
    for i, (aoi, G, res, mt) in enumerate(runs):
        ax = fig.add_subplot(gs[0, i])
        c.draw_streets(ax, G, color="#555", lw=0.6)
        c.frame(
            ax,
            G,
            aoi,
            aoi["name"].split(",")[0],
            f"{mt['area_km2']} km² · {mt['intersections']} intersections · {mt['street_length_km']} km",
        )
    tx = fig.add_subplot(gs[1, :])
    tx.axis("off")
    tx.set_xlim(0, 1)
    tx.set_ylim(0, 1)
    names = [r[0]["name"].split(",")[0] for r in runs]
    xs = np.linspace(0.46, 0.92, n)
    for x, nm in zip(xs, names):
        tx.text(x, 0.98, nm, ha="right", fontsize=12, fontweight="bold")
    for j, (label, key, unit) in enumerate(ROWS):
        y = 0.90 - j * 0.082
        tx.text(0.0, y, label, fontsize=11)
        for x, r in zip(xs, runs):
            tx.text(x, y, str(r[3][key]), ha="right", fontsize=12, fontweight="bold")
        tx.text(0.95, y, unit, fontsize=9, color="#666")
        tx.plot([0, 1], [y - 0.025, y - 0.025], color="#ddd", lw=0.6)
    fig.suptitle(
        args.title or "Walkability compared: " + " vs ".join(names), x=0.01, ha="left", fontsize=16, fontweight="bold"
    )
    fig.text(
        0.01,
        0.012,
        "No single score. OSM has no sidewalk quality or safety; mapped sidewalks and crossings may be incomplete. "
        + c.ATTRIBUTION
        + ".",
        fontsize=7.5,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(f"{args.out}/figure.png")
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
