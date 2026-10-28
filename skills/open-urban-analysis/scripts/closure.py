# /// script
# requires-python = ">=3.10"
# dependencies = ["osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Road or bridge closure simulation: remove street edges from the network and measure what changes.

    uv run closure.py work/aoi.json --mode drive --close-near=-8.0717,111.84665,30 --only-highway trunk \
        --od "Tulungagung|-8.0654,111.9030|Trenggalek|-8.0505,111.7090" --poi hospital --out work/closure

--close-near=LAT,LNG,M removes every edge within M metres of the point (--bridge-only keeps it to edges tagged as
bridges); --close-osmid=ID,ID removes ways by OSM id. For the closure it reports:
- origin-destination pairs (random street nodes in the area, --pairs of them) whose fastest trip got longer, by how
  many minutes (median, 90th percentile, max) and how many are cut off entirely;
- for each named --od pair, the route before and after: km, minutes, and the street names the detour uses (compare
  these with the detour the authorities announced);
- with --poi, the cells that lose access to the nearest POI of that category: minutes before and after, and the cells
  pushed past --threshold-min or cut off.

Travel times are free-flow estimates from OSM road class (no traffic), so detour minutes are a lower bound on a busy
day. The graph is only as complete as OSM: a missing back road makes a detour look longer than it is.
Writes metrics.json, closed.geojson, routes.geojson, cells.geojson, map.html and figure.png.
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
from shapely.geometry import LineString, Point


def as_list(v):
    return v if isinstance(v, list) else [v]


def parse_od(text):
    name1, p1, name2, p2 = text.split("|")
    a = [float(v) for v in p1.split(",")]
    b = [float(v) for v in p2.split(",")]
    return name1, a, name2, b


def route_info(G, orig, dest):
    try:
        path = nx.shortest_path(G, orig, dest, weight="travel_time")
    except nx.NetworkXNoPath:
        return None
    edges = ox.routing.route_to_gdf(G, path, weight="travel_time")
    names = []
    for n in edges.get("name", []):
        for s in n if isinstance(n, list) else [n]:
            if isinstance(s, str) and s not in names:
                names.append(s)
    return {
        "km": round(float(edges.length.sum() / 1000), 2),
        "minutes": round(float(edges["travel_time"].sum() / 60), 1),
        "streets": names,
        "geometry": LineString([pt for g in edges.geometry for pt in g.coords]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--mode", choices=["walk", "drive"], default="drive")
    ap.add_argument("--close-near", help="LAT,LNG,METRES (write with = when the latitude is negative)")
    ap.add_argument("--close-osmid", help="comma-separated OSM way ids")
    ap.add_argument("--bridge-only", action="store_true", help="with --close-near, remove only edges tagged bridge")
    ap.add_argument(
        "--only-highway", help="with --close-near, remove only these OSM highway classes (for example trunk,primary)"
    )
    ap.add_argument("--od", action="append", default=[], help='"NameA|lat,lng|NameB|lat,lng" (repeatable)')
    ap.add_argument(
        "--classes",
        help="keep only these OSM highway classes before simulating (heavy vehicles: trunk,primary,secondary,tertiary)",
    )
    ap.add_argument(
        "--landmark",
        action="append",
        default=[],
        help='"Name|lat,lng" (repeatable): how close each named route passes, before and after, to places the authorities named',
    )
    ap.add_argument("--poi", help="a POI category whose access is measured before and after")
    ap.add_argument("--threshold-min", type=float, default=30)
    ap.add_argument("--pairs", type=int, default=250, help="random origin nodes for the pairwise detour sample")
    ap.add_argument("--buffer-m", type=float, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    c.outdir(args.out)

    aoi = c.load_aoi(args.aoi)
    G = c.fetch_graph(aoi, args.mode, args.buffer_m)
    crs = G.graph["crs"]
    if args.classes:
        keep = set(args.classes.split(","))
        drop = [(u, v, k) for u, v, k, d in G.edges(keys=True, data=True) if not keep & set(as_list(d["highway"]))]
        G.remove_edges_from(drop)
        G = ox.truncate.largest_component(G, strongly=True)
    nodes, edges = ox.graph_to_gdfs(G)

    # which edges close
    hit = np.zeros(len(edges), bool)
    if args.close_near:
        lat, lng, rad = (float(v) for v in args.close_near.split(","))
        disc = gpd.GeoSeries([Point(lng, lat)], crs=4326).to_crs(crs).iloc[0].buffer(rad)
        near = np.array(edges.intersects(disc))
        if args.bridge_only:
            is_bridge = (
                edges["bridge"].map(lambda v: str(v) not in ("nan", "None", "no")) if "bridge" in edges else False
            )
            near = near & np.array(is_bridge)
        if args.only_highway:
            wanted = set(args.only_highway.split(","))
            near = near & np.array(
                edges["highway"].map(lambda h: bool(wanted & set(h if isinstance(h, list) else [h])))
            )
        hit = hit | near
    if args.close_osmid:
        ids = {int(v) for v in args.close_osmid.split(",")}
        hit = hit | np.array(edges["osmid"].map(lambda v: bool(ids & set(v if isinstance(v, list) else [v]))))
    if not hit.any():
        raise SystemExit("no edge matched the closure; widen --close-near or drop --bridge-only")
    removed = edges[hit]
    G2 = G.copy()
    G2.remove_edges_from(list(removed.index))
    closed = {
        "edges_removed": int(hit.sum()),
        "length_m": round(float(removed.length.sum())),
        "names": sorted(
            {s for n in removed.get("name", []) for s in (n if isinstance(n, list) else [n]) if isinstance(s, str)}
        ),
        "osmids": sorted({int(o) for v in removed["osmid"] for o in (v if isinstance(v, list) else [v])}),
        "highway": sorted({str(h) for h in removed["highway"]}),
    }

    # pairwise detour on a random sample of street nodes inside the area
    rng = np.random.default_rng(args.seed)
    inside = c.project_polygon(aoi["polygon"], crs)
    cand = [n for n, g in zip(nodes.index, nodes.geometry) if inside.contains(g)]
    giant = max(nx.strongly_connected_components(G), key=len)
    cand = [n for n in cand if n in giant]
    sample = list(rng.choice(cand, size=min(args.pairs, len(cand)), replace=False))
    sset = set(sample)
    inc, lost, total = [], 0, 0
    for o in sample:
        t0 = nx.single_source_dijkstra_path_length(G, o, weight="travel_time")
        t1 = nx.single_source_dijkstra_path_length(G2, o, weight="travel_time")
        for d in sset:
            if d == o:
                continue
            total += 1
            if d not in t1:
                lost += 1
            else:
                inc.append((t1[d] - t0[d]) / 60)
    inc = np.array(inc)
    affected = inc[inc > 1.0]
    pairs = {
        "pairs": total,
        "affected_over_1_min_pct": round(float(len(affected) / total * 100), 1),
        "cut_off_pct": round(lost / total * 100, 2),
        "extra_min_median_of_affected": round(float(np.median(affected)), 1) if len(affected) else 0,
        "extra_min_p90_of_affected": round(float(np.percentile(affected, 90)), 1) if len(affected) else 0,
        "extra_min_max": round(float(inc.max()), 1) if len(inc) else 0,
        "note": "random street nodes in the area; free-flow minutes",
    }

    # named routes
    routes, route_rows = [], []
    for spec in args.od:
        n1, a, n2, b = parse_od(spec)
        xy = gpd.GeoSeries([Point(a[1], a[0]), Point(b[1], b[0])], crs=4326).to_crs(crs)
        o, d = ox.distance.nearest_nodes(G, xy.x.to_numpy(), xy.y.to_numpy())
        before, after = route_info(G, o, d), route_info(G2, o, d)
        row = {
            "from": n1,
            "to": n2,
            "before": {k: v for k, v in (before or {}).items() if k != "geometry"},
            "after": {k: v for k, v in (after or {}).items() if k != "geometry"} if after else "no route",
        }
        if args.landmark:
            row["landmarks_min_distance_m"] = {}
            for lm in args.landmark:
                name, ll = lm.split("|")
                la, ln = (float(v) for v in ll.split(","))
                p = gpd.GeoSeries([Point(ln, la)], crs=4326).to_crs(crs).iloc[0]
                row["landmarks_min_distance_m"][name] = {
                    "before": round(before["geometry"].distance(p)) if before else None,
                    "after": round(after["geometry"].distance(p)) if after else None,
                }
        if before and after:
            row["extra_km"] = round(after["km"] - before["km"], 2)
            row["extra_min"] = round(after["minutes"] - before["minutes"], 1)
            row["detour_only_streets"] = [s for s in after["streets"] if s not in before["streets"]]
        route_rows.append(row)
        for kind, r in (("before", before), ("after", after)):
            if r:
                routes.append(
                    {
                        "od": f"{n1} - {n2}",
                        "kind": kind,
                        "km": r["km"],
                        "minutes": r["minutes"],
                        "geometry": r["geometry"],
                    }
                )

    # access to a POI category
    access, cells = None, None
    grid = c.make_grid(G, aoi, 100 if args.mode == "walk" else 250)
    on = grid["on_network"]
    if args.poi:
        pois = c.fetch_pois(aoi, args.poi, args.buffer_m)
        src = c.poi_nodes(G, pois)
        s0, s1 = c.time_surface(G, src), c.time_surface(G2, src)
        sp = c.WALK_KMH if args.mode == "walk" else 25
        m0, m1 = c.grid_minutes(grid, s0, sp), c.grid_minutes(grid, s1, sp)
        d = (m1 - m0)[on]
        thr = args.threshold_min
        access = {
            "poi": args.poi,
            "mapped_pois_in_area_and_buffer": len(pois),
            "threshold_min": thr,
            "cells": int(on.sum()),
            "median_min_before": round(float(np.median(m0[on])), 1),
            "median_min_after": round(float(np.median(m1[on])), 1),
            "cells_slower_over_1_min_pct": round(float((d > 1).mean() * 100), 1),
            "within_threshold_before_pct": round(c.share_within(m0, on, thr), 1),
            "within_threshold_after_pct": round(c.share_within(m1, on, thr), 1),
            "lost_access_pct": round(float(((m0[on] <= thr) & ~(m1[on] <= thr)).mean() * 100), 1),
            "cut_off_pct": round(float((~np.isfinite(m1[on]) & np.isfinite(m0[on])).mean() * 100), 1),
            "max_extra_min": round(float(np.nanmax(d[np.isfinite(d)])), 1) if np.isfinite(d).any() else 0,
            "pois_mapped_note": "access is to POIs that OSM has; an unmapped hospital is invisible here",
        }
        cells = gpd.GeoDataFrame({"min_before": np.round(m0, 1), "min_after": np.round(m1, 1), "extra_min": np.round(m1 - m0, 1), "on_network": on},
                                 geometry=gpd.points_from_xy(grid["x"], grid["y"]), crs=crs).replace([np.inf], np.nan)  # fmt: skip
        cells.to_crs(4326).to_file(f"{args.out}/cells.geojson", driver="GeoJSON")

    metrics = {"place": aoi["name"], "mode": args.mode, "closure": closed, "pairs": pairs, "routes": route_rows, "access": access,
               "caveat": "Free-flow travel times from OSM road classes, no traffic. Missing back roads in OSM make detours look longer."}  # fmt: skip
    c.save_json(metrics, f"{args.out}/metrics.json")
    removed.reset_index(drop=True).assign(highway=lambda d: d.highway.astype(str))[
        ["name", "highway", "geometry"]
    ].astype({"name": str}).to_crs(4326).to_file(f"{args.out}/closed.geojson", driver="GeoJSON")
    if routes:
        gpd.GeoDataFrame(routes, crs=crs).to_crs(4326).to_file(f"{args.out}/routes.geojson", driver="GeoJSON")

    title = args.title or f"{aoi['name']}: closure simulation"
    make_map(aoi, G, removed, routes, cells, args, title)
    make_figure(aoi, G, removed, routes, cells, metrics, args, title)
    print(json.dumps(metrics, indent=2))


def make_map(aoi, G, removed, routes, cells, args, title):
    m = c.base_map(aoi, zoom=12)
    for r in routes:
        col = "#2b6cb0" if r["kind"] == "before" else "#d73027"
        gj = gpd.GeoSeries([r["geometry"]], crs=G.graph["crs"]).to_crs(4326)
        folium.GeoJson(gj.__geo_interface__, name=f"{r['od']}: {r['kind']} ({r['km']} km, {r['minutes']} min)",
                       style_function=lambda _, col=col, k=r["kind"]: {"color": col, "weight": 4, "dashArray": None if k == "before" else "8 6"}).add_to(m)  # fmt: skip
    folium.GeoJson(removed.to_crs(4326).reset_index(drop=True)[["geometry"]].__geo_interface__, name="Closed edges",
                   style_function=lambda _: {"color": "#000", "weight": 7}).add_to(m)  # fmt: skip
    if cells is not None:
        fg = folium.FeatureGroup(name="Cells slower after closure (> 1 min)", show=False)
        for _, r in cells.to_crs(4326)[lambda d: d.extra_min > 1].iterrows():
            folium.CircleMarker([r.geometry.y, r.geometry.x], radius=3, color="#d73027", weight=0, fill=True, fill_opacity=0.6,
                                tooltip=f"+{r.extra_min:.1f} min to nearest {args.poi}").add_to(fg)  # fmt: skip
        fg.add_to(m)
    c.finish_map(m, f"{args.out}/map.html", title)


def make_figure(aoi, G, removed, routes, cells, metrics, args, title):
    fig, ax = plt.subplots(figsize=(11, 8), dpi=160)
    c.draw_streets(ax, G, color="#d0d0cb", lw=0.4)
    if cells is not None:
        cc = cells[cells.on_network & (cells.extra_min > 1)]
        sc = ax.scatter(
            cc.geometry.x,
            cc.geometry.y,
            c=cc.extra_min.clip(upper=cc.extra_min.quantile(0.98)),
            s=14,
            cmap="YlOrRd",
            marker="s",
            lw=0,
            zorder=2,
        )
        fig.colorbar(sc, ax=ax, shrink=0.5, label=f"extra minutes to the nearest {args.poi}", pad=0.01)
        ax.scatter(cells[cells.on_network].geometry.x, cells[cells.on_network].geometry.y, s=1.5, c="#999", zorder=1)
    for r in routes:
        x, y = r["geometry"].xy
        ax.plot(x, y, color="#2b6cb0" if r["kind"] == "before" else "#d73027", lw=2.2, ls="-" if r["kind"] == "before" else "--", zorder=5,
                label=f"{r['od']}, {r['kind']}: {r['km']} km, {r['minutes']} min")  # fmt: skip
    for g in removed.geometry:
        ax.plot(*g.xy, color="black", lw=5, zorder=6, solid_capstyle="round")
    centre = removed.geometry.union_all().centroid
    ax.annotate(
        "closed",
        (centre.x, centre.y),
        xytext=(12, 12),
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
        zorder=7,
    )
    c.frame(
        ax,
        G,
        aoi,
        title,
        f"{metrics['closure']['edges_removed']} edges removed · {metrics['pairs']['affected_over_1_min_pct']}% of trips slower by over 1 min",
    )
    ax.legend(loc="lower left", fontsize=8, frameon=True)
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. Free-flow estimates, no traffic.", ha="right", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(f"{args.out}/figure.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
