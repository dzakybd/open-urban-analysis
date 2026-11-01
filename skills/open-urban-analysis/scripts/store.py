# /// script
# requires-python = ">=3.10"
# dependencies = ["rasterio>=1.4", "osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Store finder: where would a new shop reach the most people with the fewest competitors?

    uv run store.py work/aoi.json --shop convenience --minutes 10 --k 5 --out work/store

1. Every 100 m cell of the area and its buffer gets its GHSL population (people per cell, 2020) and its street node.
2. Candidate sites are street nodes inside the area, thinned to one per 200 m square. A candidate's catchment is the
   cells that can reach it within --minutes (walk, or free-flow drive), on the reversed graph so one-way streets count.
3. Competitors are the --shop POIs OSM has whose street node lies inside that catchment.
4. Score = people in the catchment / (competitors + 1): the people per store if the new shop shared its catchment
   evenly with the competitors. The top --k are ranked, each at least 500 m from a better one.

Writes metrics.json, sites.geojson (top sites), candidates.geojson (every candidate's score), map.html and figure.png.

It ranks people against competitors, nothing else: there is no rent, foot traffic, income or sales data, so a top
site is a place to look at, not a forecast of profit. A competitor nobody mapped makes a site look emptier than it is.
"""

import argparse
import json

import common as c
import folium
import geopandas as gpd
import matplotlib.colors
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
from matplotlib.lines import Line2D
from shapely import contains_xy

CANDIDATE_SPACING_M = 200
MIN_GAP_M = 500
SITE_COLORS = ["#1b9e77", "#7570b3", "#e6ab02", "#e7298a", "#66a61e", "#a6761d", "#1f78b4", "#666666"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--shop", default="convenience", help="the competitor category (see CATEGORIES in common.py)")
    ap.add_argument("--mode", choices=["walk", "drive"], default="walk")
    ap.add_argument("--minutes", type=float, default=10, help="catchment: travel time to the shop")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--buffer-m", type=float, default=1500)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    c.parse_categories(args.shop)
    c.outdir(args.out)
    lim = args.minutes

    aoi = c.load_aoi(args.aoi)
    G = c.fetch_graph(aoi, args.mode, args.buffer_m)
    crs = G.graph["crs"]
    # people are counted over the whole buffered download, so a candidate near the edge keeps its outside catchment
    grid = c.make_grid(G, {"polygon": c.buffered(aoi, args.buffer_m)}, 100)
    on = grid["on_network"]
    pop = np.where(on, c.ghsl_population(grid["x"], grid["y"], crs), 0)
    snap_min = grid["snap_m"] / (c.WALK_KMH * 1000 / 60)
    by_node = {}
    for i in np.flatnonzero(on):
        by_node.setdefault(int(grid["node"][i]), []).append(i)

    # competitors: one street node per mapped shop (shops more than 250 m from a street are left out)
    shops = c.fetch_pois(aoi, args.shop, args.buffer_m)
    pts = [g.representative_point() for g in shops.to_crs(crs).geometry]
    snode, sdist = ox.distance.nearest_nodes(G, [p.x for p in pts], [p.y for p in pts], return_dist=True)
    shop_nodes = [int(n) for n, d in zip(snode, sdist) if d <= 250]

    # candidates and their catchments
    nodes = ox.graph_to_gdfs(G, edges=False)
    cand = nodes[nodes.within(c.project_polygon(aoi["polygon"], crs))]
    cand = cand.groupby([cand.x // CANDIDATE_SPACING_M, cand.y // CANDIDATE_SPACING_M]).head(1)
    R = G.reverse(copy=False)
    rows = []
    for n in cand.index:
        t = nx.single_source_dijkstra_path_length(R, n, cutoff=lim * 60, weight="travel_time")
        cells = [i for m, s in t.items() for i in by_node.get(m, ()) if s / 60 + snap_min[i] <= lim]
        people = float(pop[cells].sum())
        rivals = sum(m in t for m in shop_nodes)
        rows.append({"osm_node": int(n), "people": round(people), "competitors": rivals,
                     "people_per_store": round(people / (rivals + 1))})  # fmt: skip
    cands = gpd.GeoDataFrame(rows, geometry=list(cand.geometry), crs=crs).sort_values(
        "people_per_store", ascending=False
    )

    # top sites, spread out
    picked = []
    for i, r in cands.iterrows():
        if all(r.geometry.distance(cands.geometry[j]) >= MIN_GAP_M for j in picked):
            picked.append(i)
        if len(picked) == args.k:
            break
    sites = cands.loc[picked].reset_index(drop=True)
    sites.insert(0, "rank", range(1, len(sites) + 1))
    ll = sites.to_crs(4326).geometry
    sites["lat"], sites["lng"] = ll.y.round(5).to_numpy(), ll.x.round(5).to_numpy()

    inside = np.array([aoi["polygon"].contains(g.representative_point()) for g in shops.geometry], dtype=bool)
    names = shops["name"].fillna("").str.lower()[inside]
    people_in_area = round(float(pop[contains_xy(c.project_polygon(aoi["polygon"], crs), grid["x"], grid["y"])].sum()))
    metrics = {
        "place": aoi["name"],
        "mode": args.mode,
        "shop": args.shop,
        "catchment_min": lim,
        "competitors": {
            **c.poi_counts(aoi, shops),
            "snapped_to_street": len(shop_nodes),
            "indomaret": int(names.str.contains("indomaret").sum()),
            "alfamart": int(names.str.contains("alfamart|alfamidi").sum()),
        },
        "population_in_area": people_in_area,
        "people_per_mapped_shop": round(people_in_area / max(int(inside.sum()), 1)),
        "top_sites_with_no_competitor": int((sites["competitors"] == 0).sum()),
        "candidates": len(cands),
        "candidate_rule": f"street nodes inside the area, one per {CANDIDATE_SPACING_M} m square",
        "score": "people within the catchment / (competitors within it + 1)",
        "candidate_people_per_store_median": round(float(cands["people_per_store"].median())),
        "candidate_people_per_store_p90": round(float(cands["people_per_store"].quantile(0.9))),
        "candidates_with_no_competitor_pct": round(float((cands["competitors"] == 0).mean() * 100), 1),
        "sites": sites.drop(columns="geometry").to_dict("records"),
        "method": f"{'walking at 4.8 km/h' if args.mode == 'walk' else 'free-flow drive times by OSM road class'}; "
        f"top {args.k} by score, each at least {MIN_GAP_M} m from a better one",
        "caveat": "Ranks people against mapped competitors only: no rent, foot traffic, income or sales data, so it is "
        "not a profit forecast. OSM is incomplete and no public register of minimarkets exists to check it against: an "
        "unmapped competitor makes a site look emptier than it is, and a site with no competitor in a dense district "
        "is more likely a mapping gap than free ground. Minimarkets tagged shop=supermarket are not counted.",
        "sources": [
            {
                "name": "OpenStreetMap, Geofabrik java-latest.osm.pbf",
                "url": "https://download.geofabrik.de/asia/indonesia/java.html",
                "version": "snapshot of 27 Oct 2026",
                "licence": "ODbL 1.0",
            },
            {
                "name": "GHSL GHS-POP R2023A, 2020 epoch, 100 m (JRC)",
                "url": "https://ghsl.jrc.ec.europa.eu/ghs_pop2023.php",
                "version": "R2023A",
                "licence": "CC BY 4.0",
            },
        ],
    }
    c.save_json(metrics, f"{args.out}/metrics.json")
    sites.to_crs(4326).to_file(f"{args.out}/sites.geojson", driver="GeoJSON")
    cands.to_crs(4326).to_file(f"{args.out}/candidates.geojson", driver="GeoJSON")

    surfaces = [
        {
            m: s / 60
            for m, s in nx.single_source_dijkstra_path_length(R, n, cutoff=lim * 60, weight="travel_time").items()
        }
        for n in sites["osm_node"]
    ]
    catch = [c.isochrones(G, s, [lim]) for s in surfaces]
    title = args.title or f"{aoi['name']}: where would a new {args.shop} shop reach the most people per store?"
    make_map(aoi, shops, cands, sites, catch, args, title)
    make_figure(aoi, G, shops, cands, sites, catch, metrics, args, title)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


def make_map(aoi, shops, cands, sites, catch, args, title):
    m = c.base_map(aoi, zoom=14)
    cc = cands.to_crs(4326)
    top = cc["people_per_store"].quantile(0.95)
    cmap = plt.get_cmap("viridis")
    fg = folium.FeatureGroup(name="Candidate sites (people per store)", show=False)
    for _, r in cc.iterrows():
        col = matplotlib.colors.to_hex(cmap(min(r.people_per_store / top, 1)))
        folium.CircleMarker([r.geometry.y, r.geometry.x], radius=3, color=col, weight=0, fill=True, fill_opacity=0.8,
                            tooltip=f"{r.people:,} people, {r.competitors} competitors, {r.people_per_store:,} per store").add_to(fg)  # fmt: skip
    fg.add_to(m)
    for k, (_, s) in enumerate(sites.iterrows()):
        col = SITE_COLORS[k % len(SITE_COLORS)]
        if not catch[k].empty:
            folium.GeoJson(catch[k].__geo_interface__, name=f"Site {s['rank']}: {args.minutes:.0f}-min catchment",
                           style_function=lambda _, col=col: {"color": col, "weight": 2, "fillColor": col, "fillOpacity": 0.12}).add_to(m)  # fmt: skip
    c.add_pois(m, shops, "#222", f"{args.shop} in OSM (competitors)")
    fg = folium.FeatureGroup(name="Top sites")
    for _, s in sites.iterrows():
        folium.Marker([s.lat, s.lng], icon=folium.DivIcon(html=f'<div style="font:bold 14px sans-serif;color:#fff;background:#111;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px">{s["rank"]}</div>'),
                      tooltip=f"Site {s['rank']}: {s.people:,} people, {s.competitors} competitors within {args.minutes:.0f} min, {s.people_per_store:,} per store").add_to(fg)  # fmt: skip
    fg.add_to(m)
    c.finish_map(m, f"{args.out}/map.html", title)


def make_figure(aoi, G, shops, cands, sites, catch, metrics, args, title):
    crs = G.graph["crs"]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 7.6), dpi=160, gridspec_kw={"width_ratios": [1.4, 1]})
    c.draw_streets(ax, G, color="#d0d0cb", lw=0.3)
    top = cands["people_per_store"].quantile(0.95)
    sc = ax.scatter(cands.geometry.x, cands.geometry.y, c=cands["people_per_store"], cmap="viridis", vmin=0, vmax=top,
                    s=9, lw=0, zorder=4)  # fmt: skip
    for k, iso in enumerate(catch):
        for g in iso.to_crs(crs).geometry:
            for part in getattr(g, "geoms", [g]):
                ax.plot(*part.exterior.xy, color=SITE_COLORS[k % len(SITE_COLORS)], lw=1.4, zorder=5)
    pts = [g.representative_point() for g in shops.to_crs(crs).geometry]
    ax.scatter([p.x for p in pts], [p.y for p in pts], s=14, c="#111", marker="x", lw=0.9, zorder=6)
    for k, s in sites.iterrows():
        ax.scatter(s.geometry.x, s.geometry.y, s=260, c=SITE_COLORS[k % len(SITE_COLORS)], edgecolor="white", lw=1.2,
                   zorder=7)  # fmt: skip
        ax.text(s.geometry.x, s.geometry.y, str(s["rank"]), color="white", fontsize=10, fontweight="bold",
                ha="center", va="center", zorder=8)  # fmt: skip
    cm = metrics["competitors"]
    c.frame(ax, G, aoi, "", f"{cm['in_area']} {args.shop} shops in OSM inside ({cm['indomaret']} Indomaret, "
            f"{cm['alfamart']} Alfamart/Alfamidi), {metrics['people_per_mapped_shop']:,} people per mapped shop; "
            f"{len(cands)} candidate sites")  # fmt: skip
    fig.colorbar(sc, ax=ax, shrink=0.5, pad=0.01, label=f"people per store within {args.minutes:.0f} min")
    ax.legend(handles=[Line2D([0], [0], marker="x", ls="", color="#111", label=f"{args.shop} in OSM (competitor)"),
                       Line2D([0], [0], color="#555", lw=1.4, label=f"{args.minutes:.0f}-min catchment of a top site")],
              loc="lower left", fontsize=8)  # fmt: skip

    y = np.arange(len(sites))
    bx.barh(y, sites["people_per_store"], color=[SITE_COLORS[k % len(SITE_COLORS)] for k in range(len(sites))])
    bx.axvline(metrics["candidate_people_per_store_median"], color="#999", ls="--", lw=1)
    bx.text(metrics["candidate_people_per_store_median"], len(sites) - 0.4, " median candidate", color="#777",
            fontsize=8, va="bottom")  # fmt: skip
    for k, s in sites.iterrows():
        bx.text(s.people_per_store, k, f"  {s.people_per_store:,} per store\n  ({s.people:,} people, {s.competitors} competitors)",
                va="center", fontsize=8.5)  # fmt: skip
    bx.set_yticks(y, [f"site {r}" for r in sites["rank"]])
    bx.invert_yaxis()
    bx.set_xlim(0, sites["people_per_store"].max() * 1.6)
    bx.set_xlabel(f"people per store within a {args.minutes:.0f}-min {args.mode} (GHSL 2020)")
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    bx.set_title("Top sites: people / (competitors + 1)", loc="left", fontsize=12, fontweight="bold")
    if metrics["top_sites_with_no_competitor"] == len(sites):
        bx.text(0, -0.09, "No mapped competitor within reach of any top site: in a dense city that is more\n"
                "likely unmapped shops than free ground. Survey before reading a site as a gap.",
                transform=bx.transAxes, fontsize=8.5, color="#a50f15", va="top")  # fmt: skip
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. Population: GHSL GHS-POP R2023A. No rent, foot traffic or sales data: "
             "this ranks people against mapped competitors, not profit.", ha="right", fontsize=7.5, color="#555")  # fmt: skip
    fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(f"{args.out}/figure.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
