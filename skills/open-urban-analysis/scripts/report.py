# /// script
# requires-python = ">=3.10"
# dependencies = ["osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""House report card: from one address, how far is each everyday facility on foot, by bike and by car, and how long is
the commute?

    uv run report.py work/aoi.json --work "UGM|-7.7705,110.3778" --out work/report

The home is the AOI's point (geocode it with locate.py); the disc around it sets how far the street graphs reach.
For each category: minutes to the nearest mapped facility walking (4.8 km/h), cycling (15 km/h on the walking network)
and driving (free-flow speeds by road class, one-way streets respected), the facility's name, and how many are within
--minutes on foot. With --work, the commute by each mode. One row per category, never a combined score: which
category matters depends on the household.

Writes metrics.json, pois.geojson, routes.geojson, map.html and figure.png. A facility nobody mapped looks missing.
Bus and rail are stops OSM has, not a timetable: the commute is walk, bike or car only, not public transport.
"""

import argparse
import json
from itertools import pairwise

import common as c
import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from matplotlib.lines import Line2D
from shapely.geometry import LineString

BIKE_KMH = 15
MODES = ("walk", "bike", "drive")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument(
        "--categories", default="school,puskesmas,clinic,hospital,marketplace,convenience,park,bus_stop,rail"
    )
    ap.add_argument("--work", help="'Name|lat,lng' of the workplace, for the commute")
    ap.add_argument("--minutes", type=float, default=15, help="count facilities within this walk")
    ap.add_argument("--exclude-name", help="regex: drop hospitals whose OSM name matches (puskesmas, clinics)")
    ap.add_argument("--buffer-m", type=float, default=1000)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cats = c.parse_categories(args.categories)
    c.outdir(args.out)
    aoi = c.load_aoi(args.aoi)
    home = (aoi["lat"], aoi["lng"])

    graphs = {"walk": c.fetch_graph(aoi, "walk", args.buffer_m), "drive": c.fetch_graph(aoi, "drive", args.buffer_m)}
    crs = graphs["walk"].graph["crs"]
    hx, hy = project([home], crs)[0]
    # minutes from home to every node, per mode (cycling = the walking network at bike speed)
    reach = {}
    for mode, G in graphs.items():
        n, d = ox.distance.nearest_nodes(G, hx, hy, return_dist=True)
        t = nx.single_source_dijkstra_path_length(G, n, weight="travel_time")
        reach[mode] = (n, {k: v / 60 + d / (c.WALK_KMH * 1000 / 60) for k, v in t.items()})
    walk_t = reach["walk"][1]
    reach["bike"] = (reach["walk"][0], {k: v * c.WALK_KMH / BIKE_KMH for k, v in walk_t.items()})

    rows, pois_all = {}, []
    for cat in cats:
        pois = c.fetch_pois(aoi, cat, args.buffer_m)
        if cat == "hospital" and args.exclude_name:
            pois = pois[~pois["name"].fillna("").str.contains(args.exclude_name, case=False, regex=True)]
        pois = pois.reset_index(drop=True)
        mins = {m: poi_minutes(graphs["drive" if m == "drive" else "walk"], pois, reach[m][1]) for m in MODES}
        row = {"in_osm_within_reach": len(pois)}
        for m in MODES:
            i = int(np.argmin(mins[m])) if len(pois) and np.isfinite(mins[m]).any() else None
            row[f"nearest_{m}_min"] = round(float(mins[m][i]), 1) if i is not None else None
            if m == "walk":
                row["nearest_name"] = (pois["name"][i] if isinstance(pois["name"][i], str) else "(unnamed in OSM)") if i is not None else None  # fmt: skip
        row[f"within_{args.minutes:.0f}_min_walk"] = int((mins["walk"] <= args.minutes).sum())
        rows[cat] = row
        pois_all.append(pois.assign(walk_min=np.round(mins["walk"], 1)))

    commute, routes = None, []
    if args.work:
        name, ll = args.work.split("|")
        wlat, wlng = (float(v) for v in ll.split(","))
        wx, wy = project([(wlat, wlng)], crs)[0]
        commute = {
            "to": name,
            "lat": wlat,
            "lng": wlng,
            "straight_km": round(float(np.hypot(wx - hx, wy - hy)) / 1000, 2),
        }
        for mode, G in graphs.items():
            w, d = ox.distance.nearest_nodes(G, wx, wy, return_dist=True)
            path = nx.shortest_path(G, reach[mode][0], w, weight="travel_time")
            km = sum(min(G[u][v].values(), key=lambda e: e["travel_time"])["length"] for u, v in pairwise(path)) / 1000
            mins = reach[mode][1][w] + d / (c.WALK_KMH * 1000 / 60)
            commute[f"{mode}_min"] = round(mins, 1)
            commute[f"{mode}_km"] = round(km, 2)
            if mode == "walk":
                commute["bike_min"] = round(reach["bike"][1][w] + d / (c.WALK_KMH * 1000 / 60), 1)
            routes.append({"mode": mode, "km": round(km, 2), "geometry": LineString([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in path])})  # fmt: skip

    metrics = {
        "place": aoi["name"],
        "home": {"lat": home[0], "lng": home[1]},
        "reach_radius_m": aoi.get("radius_m"),
        "speeds": f"walk {c.WALK_KMH} km/h; bike {BIKE_KMH} km/h on the walking network; drive free-flow by OSM road class",
        "walk_limit_min": args.minutes,
        "categories": rows,
        "commute": commute,
        "hospital_exclude_name": args.exclude_name,
        "caveat": "Facilities are the ones OSM has: an unmapped school or clinic looks missing. Bus and rail rows are "
        "mapped stops, not service; the commute is modelled walk, bike or free-flow car, not public transport or traffic.",
        "sources": [
            {
                "name": "OpenStreetMap, Geofabrik java-latest.osm.pbf",
                "url": "https://download.geofabrik.de/asia/indonesia/java.html",
                "version": "snapshot of 27 Oct 2026",
                "licence": "ODbL 1.0",
            },
        ],
    }
    c.save_json(metrics, f"{args.out}/metrics.json")
    pois = gpd.GeoDataFrame(pd.concat(pois_all), crs=4326)
    pois["geometry"] = [g.representative_point() for g in pois.geometry]
    pois.replace([np.inf], np.nan).to_file(f"{args.out}/pois.geojson", driver="GeoJSON")
    routes = gpd.GeoDataFrame(routes, crs=crs).to_crs(4326) if routes else None
    if routes is not None:
        routes.to_file(f"{args.out}/routes.geojson", driver="GeoJSON")
    iso = c.isochrones(graphs["walk"], walk_t, [args.minutes])

    title = args.title or f"{aoi['name']}: house report card"
    make_map(aoi, pois, iso, routes, commute, args, title)
    make_figure(aoi, graphs["walk"], pois, iso, routes, metrics, args, title)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


def project(latlngs, crs):
    g = gpd.GeoSeries(gpd.points_from_xy([p[1] for p in latlngs], [p[0] for p in latlngs]), crs=4326).to_crs(crs)
    return [(p.x, p.y) for p in g]


def poi_minutes(G, pois, t, max_snap_m=250):
    """Minutes from home to each POI: the best of its entrances (outline points for an area) that lie near a street."""
    out = np.full(len(pois), np.inf)
    xs, ys, idx = c.access_points(pois, G.graph["crs"])
    if len(xs):
        nodes, dist = ox.distance.nearest_nodes(G, xs, ys, return_dist=True)
        for n, d, i in zip(nodes, dist, idx):
            if d <= max_snap_m:
                out[i] = min(out[i], t.get(int(n), np.inf))
    return out


def make_map(aoi, pois, iso, routes, commute, args, title):
    m = c.base_map(aoi, zoom=14)
    folium.GeoJson(iso.__geo_interface__, name=f"Within a {args.minutes:.0f}-min walk",
                   style_function=lambda _: {"color": "#2c7fb8", "weight": 1, "fillColor": "#2c7fb8", "fillOpacity": 0.12}).add_to(m)  # fmt: skip
    if routes is not None:
        for _, r in routes.iterrows():
            folium.GeoJson(r.geometry.__geo_interface__, name=f"Commute, {r['mode']} route ({r.km} km)",
                           style_function=lambda _, d=r["mode"] == "drive": {"color": "#111" if d else "#e6550d", "weight": 4, "dashArray": None if d else "6 6"}).add_to(m)  # fmt: skip
    for cat in pois["category"].unique():
        c.add_pois(m, pois[pois.category == cat], c.COLORS[cat], cat)
    folium.Marker([aoi["lat"], aoi["lng"]], tooltip="Home", icon=folium.Icon(color="red", icon="home")).add_to(m)
    if commute:
        folium.Marker([commute["lat"], commute["lng"]], tooltip=f"Work: {commute['to']}", icon=folium.Icon(color="black", icon="briefcase")).add_to(m)  # fmt: skip
    c.finish_map(m, f"{args.out}/map.html", title)


def fmt(v):
    return "–" if v is None else "<1 min" if v < 1 else f"{v:.0f} min"


def grade(v, ok, meh):
    return "#eeeeee" if v is None else "#c7e9c0" if v <= ok else "#fdd49e" if v <= meh else "#fcbba1"


def make_figure(aoi, G, pois, iso, routes, metrics, args, title):
    crs = G.graph["crs"]
    fig, (tx, ax) = plt.subplots(1, 2, figsize=(15, 8), dpi=160, gridspec_kw={"width_ratios": [1.15, 1]})
    lim = args.minutes
    cols = ["category", "walk", "bike", "drive", f"≤{lim:.0f} min walk", "nearest (on foot)"]
    cells, colors = [], []
    for cat, r in metrics["categories"].items():
        vals = [r[f"nearest_{m}_min"] for m in MODES]
        name = r["nearest_name"] or "none mapped"
        cells.append([cat.replace("_", " "), *[fmt(v) for v in vals],
                      str(r[f"within_{lim:.0f}_min_walk"]), name[:30]])  # fmt: skip
        colors.append(["#ffffff", grade(vals[0], lim, 2 * lim), grade(vals[1], lim, 2 * lim),
                       grade(vals[2], lim, 2 * lim), "#ffffff", "#ffffff"])  # fmt: skip
    cm = metrics["commute"]
    if cm:
        cells.append([f"to {cm['to']}", *[fmt(cm[f"{m}_min"]) for m in MODES],
                      f"{cm['walk_km']} km walk", f"{cm['drive_km']} km by car"])  # fmt: skip
        colors.append(["#f0f0f0"] * 6)
    tx.axis("off")
    tb = tx.table(cellText=cells, colLabels=cols, cellColours=colors, loc="upper left", cellLoc="left",
                  colWidths=[0.21, 0.1, 0.1, 0.1, 0.13, 0.36])  # fmt: skip
    tb.auto_set_font_size(False)
    tb.set_fontsize(9.5)
    tb.scale(1, 1.9)
    for (i, _), cell in tb.get_celld().items():
        cell.set_edgecolor("#ccc")
        if i == 0:
            cell.set_text_props(fontweight="bold")
    tx.set_title(f"Nearest mapped facility, minutes from home (green ≤ {lim:.0f}, amber ≤ {2 * lim:.0f}, red more)",
                 loc="left", fontsize=11, fontweight="bold")  # fmt: skip

    c.draw_streets(ax, G, color="#d0d0cb", lw=0.3)
    for g in iso.to_crs(crs).geometry:
        for part in getattr(g, "geoms", [g]):
            ax.fill(*part.exterior.xy, color="#2c7fb8", alpha=0.15, lw=0, zorder=2)
    if routes is not None:
        for _, r in routes.to_crs(crs).iterrows():
            d = r["mode"] == "drive"
            ax.plot(
                *r.geometry.xy, color="#111" if d else "#e6550d", lw=2 if d else 1.6, ls="-" if d else "--", zorder=4
            )
    p = pois.to_crs(crs)
    handles = []
    for cat in metrics["categories"]:
        q = p[p.category == cat]
        ax.scatter(q.geometry.x, q.geometry.y, s=12, c=c.COLORS[cat], edgecolor="white", lw=0.3, zorder=5)
        handles.append(Line2D([0], [0], marker="o", ls="", color=c.COLORS[cat], label=cat.replace("_", " ")))
    (hx, hy), *rest = project([(aoi["lat"], aoi["lng"])] + ([(cm["lat"], cm["lng"])] if cm else []), crs)
    ax.scatter(hx, hy, s=260, marker="*", c="#d7301f", edgecolor="white", lw=1, zorder=7)
    for wx, wy in rest:
        ax.scatter(wx, wy, s=150, marker="s", c="#111", edgecolor="white", lw=1, zorder=7)
    handles += [Line2D([0], [0], marker="*", ls="", color="#d7301f", markersize=12, label="home"),
                Line2D([0], [0], marker="s", ls="", color="#111", label="work"),
                Line2D([0], [0], color="#111", lw=2, label="car route"),
                Line2D([0], [0], color="#e6550d", ls="--", label="walk / bike route")]  # fmt: skip
    c.frame(ax, G, aoi, "", f"Blue: within a {lim:.0f}-min walk of home")
    tx.legend(handles=handles, loc="lower left", fontsize=8.5, ncol=3, frameon=False)
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. Walk {c.WALK_KMH} km/h, bike {BIKE_KMH} km/h, car free-flow by road class; "
             "not public transport. A facility nobody mapped looks missing.", ha="right", fontsize=7.5, color="#555")  # fmt: skip
    fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(f"{args.out}/figure.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
