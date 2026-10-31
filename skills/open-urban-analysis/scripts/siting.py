# /// script
# requires-python = ">=3.10"
# dependencies = ["rasterio>=1.4", "osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Facility siting: where should the next K facilities go to reach the most people now beyond a travel-time limit?

    uv run siting.py work/aoi.json --poi puskesmas --mode drive --threshold-min 15 --k 3 --population --out work/siting

1. Minutes from every 100 m cell of the area to the nearest existing facility of --poi (multi-source Dijkstra on the
   reversed street graph, plus the walk from the cell to its street node). Cells beyond --threshold-min are unserved.
2. Candidate sites are street nodes inside the area on a trunk, primary, secondary or tertiary road (where a public
   facility is usually built), thinned to one per 500 m square. Each candidate's catchment is the unserved cells that
   could reach it within the limit.
3. Greedy maximum coverage: pick the candidate whose catchment holds the most still-unserved people (GHSL population
   with --population, otherwise cells), mark them served, repeat K times. Greedy reaches at least 63% (1 - 1/e) of the
   best possible coverage, and every pick can be explained by its own number.

Writes metrics.json (each pick: location, people newly covered, cumulative share), picks.geojson, unserved.geojson
(the unserved area, split into what each pick covers and what is left), map.html and figure.png.

Existing facilities come from OSM: an unmapped facility looks like a missing one, so a pick may land on a facility that
exists but nobody mapped. Check each pick against an official facility list before reading it as a plan.
"""

import argparse
import json

import common as c
import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
from matplotlib.lines import Line2D
from shapely.geometry import box
from shapely.ops import unary_union

ROADS = {"trunk", "primary", "secondary", "tertiary"}
CANDIDATE_SPACING_M = 500
PICK_COLORS = ["#1b9e77", "#7570b3", "#e6ab02", "#66a61e", "#a6761d"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--poi", required=True, help="the facility category (see CATEGORIES in common.py)")
    ap.add_argument("--mode", choices=["walk", "drive"], default="drive")
    ap.add_argument("--threshold-min", type=float, default=15)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--population", action="store_true", help="weight cells by GHSL population (else by area)")
    ap.add_argument("--buffer-m", type=float, default=3000)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    c.parse_categories(args.poi)
    c.outdir(args.out)
    thr = args.threshold_min

    # 1. who is beyond the limit today
    aoi = c.load_aoi(args.aoi)
    G = c.fetch_graph(aoi, args.mode, args.buffer_m)
    crs = G.graph["crs"]
    grid = c.make_grid(G, aoi, 100)
    on = grid["on_network"]
    pois = c.fetch_pois(aoi, args.poi, args.buffer_m)
    minutes = c.grid_minutes(grid, c.time_surface(G, c.poi_nodes(G, pois)))
    w = c.ghsl_population(grid["x"], grid["y"], crs) if args.population else np.ones(len(on))
    w = np.where(on, w, 0)
    unserved = np.flatnonzero(on & ~(minutes <= thr))
    snap_min = grid["snap_m"] / (c.WALK_KMH * 1000 / 60)
    by_node = {}
    for i in unserved:
        by_node.setdefault(int(grid["node"][i]), []).append(i)

    # 2. candidates and their catchments (time TO the candidate, so on the reversed graph)
    nodes = ox.graph_to_gdfs(G, edges=False)
    poly = c.project_polygon(aoi["polygon"], crs)
    on_road = {n for u, v, d in G.edges(data=True) if ROADS & set(as_list(d["highway"])) for n in (u, v)}
    cand = nodes[nodes.index.isin(on_road) & nodes.within(poly)]
    cand = cand.groupby([(cand.x // CANDIDATE_SPACING_M), (cand.y // CANDIDATE_SPACING_M)]).head(1)
    R = G.reverse(copy=False)
    catch = {}
    for n in cand.index:
        t = nx.single_source_dijkstra_path_length(R, n, cutoff=thr * 60, weight="travel_time")
        cells = [i for m, s in t.items() for i in by_node.get(m, ()) if s / 60 + snap_min[i] <= thr]
        catch[n] = np.array(cells, int)

    # 3. greedy maximum coverage
    served = np.zeros(len(on), bool)
    total, beyond = float(w[on].sum()), float(w[unserved].sum())
    picks, covered_by = [], np.full(len(on), -1)
    for k in range(args.k):
        gain = {n: w[cs[~served[cs]]].sum() for n, cs in catch.items()}
        best = max(gain, key=gain.get)
        if gain[best] <= 0:
            break
        new = catch[best][~served[catch[best]]]
        served[new] = True
        covered_by[new] = k
        lat, lng = gpd.GeoSeries([nodes.geometry[best]], crs=crs).to_crs(4326).iloc[0].coords[0][::-1]
        picks.append({"rank": k + 1, "lat": round(lat, 5), "lng": round(lng, 5), "osm_node": int(best),
                      "newly_covered": round(float(w[new].sum())),
                      "cumulative_covered": round(float(w[served].sum())),
                      "cumulative_share_of_unserved_pct": round(float(w[served].sum() / beyond * 100), 1),
                      "within_limit_after_pct": round(float((total - beyond + w[served].sum()) / total * 100), 1)})  # fmt: skip

    unit = "people" if args.population else "cells"
    metrics = {
        "place": aoi["name"],
        "mode": args.mode,
        "poi": args.poi,
        "threshold_min": thr,
        "existing": {**c.poi_counts(aoi, pois), "names": sorted({n for n in pois["name"] if isinstance(n, str)})},
        "weight": "GHSL GHS-POP R2023A, 2020, 100 m (modelled, not a census)" if args.population else "100 m cells",
        f"total_{unit}": round(total),
        f"beyond_limit_{unit}": round(beyond),
        "beyond_limit_pct": round(beyond / total * 100, 1),
        "candidates": len(catch),
        "candidate_rule": f"street nodes on {'/'.join(sorted(ROADS))} roads inside the area, one per {CANDIDATE_SPACING_M} m square",
        "method": "greedy maximum coverage of the unserved weight within the limit (free-flow drive times by OSM road class)"
        if args.mode == "drive"
        else "greedy maximum coverage of the unserved weight within the limit (walking at 4.8 km/h)",
        "picks": picks,
        "caveat": "Existing facilities are the ones OSM has. An unmapped facility looks like a missing one, so a pick may "
        "fall where a facility exists but is not mapped: check every pick against an official list.",
    }
    c.save_json(metrics, f"{args.out}/metrics.json")

    # files
    half = grid["spacing_m"] / 2
    rows = []
    for k in [*range(len(picks)), -1]:
        idx = np.flatnonzero((covered_by == k) & np.isin(np.arange(len(on)), unserved))
        if len(idx):
            geom = unary_union(
                [box(grid["x"][i] - half, grid["y"][i] - half, grid["x"][i] + half, grid["y"][i] + half) for i in idx]
            )
            rows.append({"status": f"covered by pick {k + 1}" if k >= 0 else "still unserved", unit: round(float(w[idx].sum())), "geometry": geom})  # fmt: skip
    areas = gpd.GeoDataFrame(rows, crs=crs).to_crs(4326)
    areas.to_file(f"{args.out}/unserved.geojson", driver="GeoJSON")
    pk = gpd.GeoDataFrame(
        picks, geometry=gpd.points_from_xy([p["lng"] for p in picks], [p["lat"] for p in picks]), crs=4326
    )
    pk.to_file(f"{args.out}/picks.geojson", driver="GeoJSON")

    title = args.title or f"{aoi['name']}: where {args.k} new {args.poi} reach the most people beyond {thr:.0f} min"
    make_map(aoi, pois, areas, picks, metrics, args, title, unit)
    make_figure(aoi, G, grid, unserved, covered_by, pois, picks, metrics, args, title, unit)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


def as_list(v):
    return v if isinstance(v, list) else [v]


def make_map(aoi, pois, areas, picks, metrics, args, title, unit):
    m = c.base_map(aoi, zoom=11)
    for _, r in areas.iterrows():
        k = r.status.removeprefix("covered by pick ")
        col = PICK_COLORS[(int(k) - 1) % len(PICK_COLORS)] if k.isdigit() else "#d73027"
        folium.GeoJson(r.geometry.__geo_interface__, name=f"{r.status} ({r[unit]:,} {unit})",
                       style_function=lambda _, col=col: {"color": col, "weight": 0, "fillColor": col, "fillOpacity": 0.45}).add_to(m)  # fmt: skip
    c.add_pois(m, pois, c.COLORS.get(args.poi, "#333"), f"existing {args.poi} (OSM)")
    fg = folium.FeatureGroup(name="Proposed sites")
    for p in picks:
        folium.Marker([p["lat"], p["lng"]], icon=folium.DivIcon(html=f'<div style="font:bold 14px sans-serif;color:#fff;background:#111;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px">{p["rank"]}</div>'),
                      tooltip=f"Pick {p['rank']}: +{p['newly_covered']:,} {unit}; {p['within_limit_after_pct']}% within {args.threshold_min:.0f} min after").add_to(fg)  # fmt: skip
    fg.add_to(m)
    c.finish_map(m, f"{args.out}/map.html", title)


def make_figure(aoi, G, grid, unserved, covered_by, pois, picks, metrics, args, title, unit):
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 7.6), dpi=160, gridspec_kw={"width_ratios": [1.5, 1]})
    c.draw_streets(ax, G, color="#c8c8c3", lw=0.3)
    x, y, s = grid["x"], grid["y"], 4
    left = unserved[covered_by[unserved] < 0]
    ax.scatter(x[left], y[left], s=s, c="#d73027", marker="s", lw=0, zorder=2)
    for k in range(len(picks)):
        idx = unserved[covered_by[unserved] == k]
        col = PICK_COLORS[k % len(PICK_COLORS)]
        ax.scatter(x[idx], y[idx], s=s, c=col, marker="s", lw=0, zorder=2)
    crs = G.graph["crs"]
    pts = [g.representative_point() for g in pois.to_crs(crs).geometry]
    ax.scatter(
        [q.x for q in pts],
        [q.y for q in pts],
        s=34,
        c=c.COLORS.get(args.poi, "#333"),
        edgecolor="white",
        lw=0.7,
        zorder=5,
    )
    pp = gpd.GeoSeries(gpd.points_from_xy([p["lng"] for p in picks], [p["lat"] for p in picks]), crs=4326).to_crs(crs)
    for p, g in zip(picks, pp):
        ax.scatter(g.x, g.y, s=260, c="#111", edgecolor="white", lw=1.2, zorder=6)
        ax.text(
            g.x, g.y, str(p["rank"]), color="white", fontsize=10, fontweight="bold", ha="center", va="center", zorder=7
        )
    c.frame(ax, G, aoi, "", f"{metrics['beyond_limit_pct']}% of {unit} beyond {args.threshold_min:.0f} min ({args.mode}) "
            f"from the {metrics['existing']['in_area']} {args.poi} OSM has inside "
            f"(+{metrics['existing']['in_buffer'] - metrics['existing']['in_area']} just outside count as served)")  # fmt: skip

    def sq(col, lbl):
        return Line2D([0], [0], marker="s", ls="", color=col, markersize=7, label=lbl)

    handles = [sq("#d73027", f"beyond {args.threshold_min:.0f} min")]
    handles += [sq(PICK_COLORS[k % len(PICK_COLORS)], f"reached by pick {k + 1}") for k in range(len(picks))]
    handles += [
        Line2D(
            [0],
            [0],
            marker="o",
            ls="",
            color=c.COLORS.get(args.poi, "#333"),
            markersize=7,
            label=f"{args.poi} in OSM ({metrics['existing']['in_area']} inside, {len(pois) - metrics['existing']['in_area']} nearby)",
        )
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=8, frameon=True)

    within = [100 - metrics["beyond_limit_pct"]] + [p["within_limit_after_pct"] for p in picks]
    labels = ["today"] + [f"+ pick {p['rank']}" for p in picks]
    bx.bar(range(len(within)), within, color=["#999"] + PICK_COLORS[: len(picks)], width=0.6)
    for i, v in enumerate(within):
        add = f"\n+{picks[i - 1]['newly_covered']:,}" if i else ""
        bx.text(i, v + 1, f"{v:.1f}%{add}", ha="center", va="bottom", fontsize=9)
    bx.set_xticks(range(len(within)), labels)
    bx.set_ylim(0, 105)
    bx.set_ylabel(f"% of {unit} within {args.threshold_min:.0f} min")
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    bx.set_title("Coverage after each pick (greedy)", loc="left", fontsize=12, fontweight="bold")
    speed = "Free-flow drive times by road class" if args.mode == "drive" else f"Walking at {c.WALK_KMH} km/h"
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. Existing sites are those OSM has; an unmapped one looks missing. {speed}.",
             ha="right", fontsize=7.5, color="#555")  # fmt: skip
    fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(f"{args.out}/figure.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
