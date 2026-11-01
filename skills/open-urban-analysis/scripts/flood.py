# /// script
# requires-python = ">=3.10"
# dependencies = ["rasterio>=1.4", "osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Flood and evacuation: if the water rises to a level, which roads go under, and who loses a dry route to a shelter?

    uv run flood.py work/aoi.json --levels 0.5,1.0,1.5 --shelters school,mosque,hospital --out work/flood

1. Elevation from a 30 m DEM: Copernicus GLO-30 (streamed from the public AWS bucket, only the window needed), or
   --dem, any GeoTIFF in degrees (for example a DeltaDTM tile). Heights are metres above the EGM2008 geoid.
2. For each water level (metres above the geoid): a walking-network edge is under water when any point along it
   (every 30 m) is below the level (a bridge takes the height of its lower end, not the river under it); a 100 m
   cell is flooded when its centre is.
3. Shelters are the --shelters POIs OSM has (public buildings people go to: schools, mosques, hospitals) whose street
   node is above the level. Each dry cell is timed to the nearest dry shelter over dry roads only. A dry cell that had
   a route with no water and has none now is cut off.
4. People per cell from GHSL; each cell is labelled with the nearest OSM place=village (or suburb, quarter) point.

Writes metrics.json (people flooded and cut off per level, by village), cells.geojson, flooded_roads.geojson,
shelters.geojson, map.html and figure.png.

A bathtub model: water fills everything below the level at once, with no tide timing, drainage, sea walls, pumps or
embankments, and no rainfall-runoff. A 30 m DEM misses kerbs, raised roads and small dykes. Copernicus GLO-30 is a
surface model (roofs and trees raise it), so in built-up areas it overstates the ground and understates the flood.
"""

import argparse
import json
import math

import common as c
import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import shapely
from matplotlib.lines import Line2D
from pyproj import Transformer

COP_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)
STATUS_COLORS = {"flooded": "#3182bd", "cut off": "#d7301f", "dry route": "#d9d9d9"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--levels", default="0.5,1.0,1.5", help="water levels, metres above the EGM2008 geoid")
    ap.add_argument("--shelters", default="school,mosque,hospital")
    ap.add_argument("--dem", help="a GeoTIFF in degrees instead of Copernicus GLO-30 (for example a DeltaDTM tile)")
    ap.add_argument("--buffer-m", type=float, default=1000)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    levels = sorted(float(v) for v in args.levels.split(","))
    cats = c.parse_categories(args.shelters)
    c.outdir(args.out)

    aoi = c.load_aoi(args.aoi)
    G = c.fetch_graph(aoi, "walk", args.buffer_m)
    crs = G.graph["crs"]
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True).transform

    # elevations: nodes, edges (lowest point every 30 m), cells
    node_ids = list(G.nodes)
    node_z = dict(zip(node_ids, elevation(*to_ll([G.nodes[n]["x"] for n in node_ids], [G.nodes[n]["y"] for n in node_ids]), args.dem)))  # fmt: skip
    edges = ox.graph_to_gdfs(G, nodes=False)
    pts, owner = [], []
    for i, g in enumerate(edges.geometry):
        for d in np.append(np.arange(0, g.length, 30), g.length):
            p = g.interpolate(d)
            pts.append((p.x, p.y))
            owner.append(i)
    z = elevation(*to_ll(*np.array(pts).T), args.dem)
    edge_z = np.full(len(edges), np.inf)
    np.minimum.at(edge_z, np.array(owner), z)
    # under a bridge the DEM is the river, so a bridge takes the height of its lower end (its approaches decide)
    bridge = edges["bridge"].notna() & (edges["bridge"] != "no") if "bridge" in edges else np.zeros(len(edges), bool)
    edge_z = np.where(bridge, [min(node_z[u], node_z[v]) for u, v, _ in edges.index], edge_z)
    grid = c.make_grid(G, aoi, 100)
    on = grid["on_network"]
    cell_z = elevation(*to_ll(grid["x"], grid["y"]), args.dem)
    pop = c.ghsl_population(grid["x"], grid["y"], crs)
    snap_min = grid["snap_m"] / (c.WALK_KMH * 1000 / 60)

    shelters = gpd.GeoDataFrame(__import__("pandas").concat([c.fetch_pois(aoi, k, args.buffer_m) for k in cats]), crs=4326).reset_index(drop=True)  # fmt: skip
    sx, sy, sidx = c.access_points(shelters, crs)
    snodes, sdist = ox.distance.nearest_nodes(G, sx, sy, return_dist=True)
    near = sdist <= 250
    snodes, sidx = np.asarray(snodes)[near], sidx[near]

    village = nearest_place(aoi, args.buffer_m, grid, crs)

    def minutes_to_shelter(level):
        """Minutes from each cell to the nearest dry shelter over dry edges (inf when none); level None = no water."""
        keep = [e for e, ez in zip(edges.index, edge_z) if level is None or ez >= level]
        H = G.edge_subgraph(keep).copy()
        src = {int(n) for n in snodes if n in H and (level is None or node_z[n] >= level)}
        surface = c.time_surface(H, src)
        return np.array([surface.get(int(n), np.inf) for n in grid["node"]]) + snap_min, src

    base, base_src = minutes_to_shelter(None)
    reach0 = on & np.isfinite(base)
    status = {}
    metrics = {
        "place": aoi["name"],
        "dem": args.dem or "Copernicus GLO-30 DSM (surface model), 30 m, heights above EGM2008",
        "levels_m_above_egm2008": levels,
        "shelter_categories": cats,
        "shelters_in_osm": {k: c.poi_counts(aoi, c.fetch_pois(aoi, k, args.buffer_m)) for k in cats},
        "dem_nodata_points": int(np.isnan(z).sum() + np.isnan(cell_z).sum() + np.isnan(list(node_z.values())).sum()),
        "population_in_area": round(float(pop.sum())),
        "population_on_network": round(float(pop[on].sum())),
        "cell_elevation_m": {q: round(float(np.percentile(cell_z, int(q[1:]))), 2) for q in ("p10", "p25", "p50")},
        "no_water": {
            "people_with_route_to_shelter": round(float(pop[reach0].sum())),
            "median_min": round(float(np.median(base[reach0])), 1),
            "p90_min": round(float(np.percentile(base[reach0], 90)), 1),
        },
        "levels": [],
    }
    road_km = edges["length"].sum() / 1000
    for h in levels:
        t, src = minutes_to_shelter(h)
        flooded = cell_z < h
        ok = ~flooded & on & np.isfinite(t)
        cut = ~flooded & reach0 & ~np.isfinite(t)
        # every cut-off cell must sit near a road that is under water: distance from the cell to the nearest one
        wet = shapely.STRtree(edges.geometry[edge_z < h].to_numpy())
        near_wet = wet.query_nearest(shapely.points(grid["x"][cut], grid["y"][cut]), return_distance=True)[1] if cut.any() and len(wet) else np.array([])  # fmt: skip
        status[h] = np.where(flooded, "flooded", np.where(cut, "cut off", np.where(ok, "dry route", "")))
        metrics["levels"].append({
            "level_m": h,
            "road_km_under_water": round(float(edges["length"][edge_z < h].sum() / 1000), 1),
            "road_under_water_pct": round(float(edges["length"][edge_z < h].sum() / 1000 / road_km * 100), 1),
            "dry_shelter_nodes": len(src),
            "dry_shelter_nodes_no_water": len(base_src),
            "people_flooded": round(float(pop[flooded].sum())),
            "people_flooded_pct": round(float(pop[flooded].sum() / pop.sum() * 100), 1),
            "people_dry_but_cut_off": round(float(pop[cut].sum())),
            "people_dry_but_cut_off_pct": round(float(pop[cut].sum() / pop.sum() * 100), 1),
            "cut_off_cells": int(cut.sum()),
            "cut_off_p90_m_to_road_under_water": round(float(np.percentile(near_wet, 90))) if len(near_wet) else None,
            "cut_off_max_m_to_road_under_water": round(float(near_wet.max())) if len(near_wet) else None,
            "people_with_dry_route": round(float(pop[ok].sum())),
            "median_min_dry_route": round(float(np.median(t[ok])), 1) if ok.any() else None,
            "p90_min_dry_route": round(float(np.percentile(t[ok], 90)), 1) if ok.any() else None,
        })  # fmt: skip
    hi = levels[-1]
    by_v = []
    for v in sorted(set(village)):
        m = village == v
        row = {"village": v, "people": round(float(pop[m].sum()))}
        for h in levels:
            row[f"flooded_{h}"] = round(float(pop[m & (status[h] == "flooded")].sum()))
            row[f"cut_off_{h}"] = round(float(pop[m & (status[h] == "cut off")].sum()))
        by_v.append(row)
    by_v.sort(key=lambda r: -(r[f"flooded_{hi}"] + r[f"cut_off_{hi}"]))
    metrics["villages"] = [r for r in by_v if r[f"flooded_{hi}"] + r[f"cut_off_{hi}"] > 0]
    metrics["village_rule"] = "each cell takes the name of the nearest OSM place=village/suburb/quarter point"
    metrics["caveat"] = (
        "Bathtub model on a 30 m DEM: no tide timing, drainage, sea walls, pumps, embankments or rainfall. Copernicus "
        "GLO-30 is a surface model (roofs, trees), so built-up ground reads high and the flood is understated. Heights "
        "are above the EGM2008 geoid, which is not local mean sea level, and the DEM dates from 2011-2015: where land is "
        "sinking (the Java north coast) today's ground is lower than it reads. Roads are dropped when any point along "
        "them is below the level, so a road crossing an unmapped culvert or ford counts as under water. Shelters are "
        "the ones OSM has."
    )
    metrics["sources"] = [
        {"name": "OpenStreetMap, Geofabrik java-latest.osm.pbf", "url": "https://download.geofabrik.de/asia/indonesia/java.html",
         "version": "snapshot of 27 Oct 2026", "licence": "ODbL 1.0"},
        {"name": "GHSL GHS-POP R2023A, 2020 epoch, 100 m (JRC)", "url": "https://ghsl.jrc.ec.europa.eu/ghs_pop2023.php",
         "version": "R2023A", "licence": "CC BY 4.0"},
        {"name": "Copernicus DEM GLO-30 (ESA), public AWS bucket copernicus-dem-30m", "url": "https://registry.opendata.aws/copernicus-dem/",
         "version": "GLO-30 public release on AWS, read 1 Nov 2026 (source acquisition 2011-2015)", "licence": "Copernicus DEM licence (free use with attribution): "
         "(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the "
         "European Union and ESA; all rights reserved"} if not args.dem else {"name": args.dem},
    ]  # fmt: skip
    c.save_json(metrics, f"{args.out}/metrics.json")

    cells = gpd.GeoDataFrame({"elev_m": np.round(cell_z, 2), "population": np.round(pop, 1), "village": village,
                              **{f"status_{h}": status[h] for h in levels}},
                             geometry=gpd.points_from_xy(grid["x"], grid["y"]), crs=crs).to_crs(4326)  # fmt: skip
    cells.to_file(f"{args.out}/cells.geojson", driver="GeoJSON")
    fr = edges.assign(min_elev_m=np.round(edge_z, 2))[edge_z < hi][["min_elev_m", "geometry"]].to_crs(4326)
    fr.to_file(f"{args.out}/flooded_roads.geojson", driver="GeoJSON")
    shelters["geometry"] = [g.representative_point() for g in shelters.geometry]
    shelters.to_file(f"{args.out}/shelters.geojson", driver="GeoJSON")

    title = args.title or f"{aoi['name']}: who loses a dry route to a shelter as the water rises?"
    make_map(aoi, cells, edges.assign(z=edge_z).to_crs(4326), shelters, levels, args, title)
    make_figure(aoi, G, grid, status, pop, edges.assign(z=edge_z), shelters, levels, metrics, title, args)
    print(json.dumps({k: v for k, v in metrics.items() if k != "villages"}, indent=2, ensure_ascii=False))


def elevation(lons, lats, dem=None):
    """Metres at each lon/lat (nearest pixel): from --dem, or the Copernicus GLO-30 1-degree tiles that hold the points,
    reading only the window around them over HTTP."""
    import rasterio
    from rasterio.windows import from_bounds

    lons, lats = np.asarray(lons, float), np.asarray(lats, float)
    out = np.full(len(lons), np.nan)
    tiles = {(math.floor(y), math.floor(x)) for x, y in zip(lons, lats)} if not dem else {None}
    for tile in tiles:
        if tile is None:
            path, pick = dem, np.ones(len(lons), bool)
        else:
            la, lo = tile
            path = "/vsicurl/" + COP_URL.format(lat=f"{'N' if la >= 0 else 'S'}{abs(la):02d}", lon=f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}")  # fmt: skip
            pick = (np.floor(lats) == la) & (np.floor(lons) == lo)
        with rasterio.open(path) as src:
            w = from_bounds(lons[pick].min() - 0.001, lats[pick].min() - 0.001, lons[pick].max() + 0.001,
                            lats[pick].max() + 0.001, src.transform).round_offsets().round_lengths()  # fmt: skip
            a = src.read(1, window=w, boundless=True, fill_value=np.nan).astype(float)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
            r, col = rasterio.transform.rowcol(src.window_transform(w), lons[pick], lats[pick])
            out[pick] = a[np.clip(r, 0, a.shape[0] - 1), np.clip(col, 0, a.shape[1] - 1)]
    return out


def nearest_place(aoi, buffer_m, grid, crs):
    """Name of the nearest OSM place=village/suburb/quarter point to each cell."""
    poly = c.buffered(aoi, buffer_m)
    tags = {"place": ["village", "suburb", "quarter"]}
    if c.local_pbf():
        p = ox.features_from_xml(c._local_xml(poly), polygon=poly, tags=tags)
    else:
        p = c.with_retry(ox.features_from_polygon, poly, tags)
    p = p[p["name"].notna()].to_crs(crs)
    xy = np.array([(g.representative_point().x, g.representative_point().y) for g in p.geometry])
    d = (grid["x"][:, None] - xy[:, 0]) ** 2 + (grid["y"][:, None] - xy[:, 1]) ** 2
    return p["name"].to_numpy()[d.argmin(axis=1)]


def make_map(aoi, cells, edges, shelters, levels, args, title):
    m = c.base_map(aoi, zoom=13)
    for h in levels:
        fg = folium.FeatureGroup(name=f"{h} m: flooded and cut-off cells", show=h == levels[-1])
        for _, r in cells[cells[f"status_{h}"].isin(["flooded", "cut off"]) & (cells.population > 0)].iterrows():
            st = r[f"status_{h}"]
            folium.CircleMarker([r.geometry.y, r.geometry.x], radius=3, color=STATUS_COLORS[st], weight=0, fill=True,
                                fill_opacity=0.6, tooltip=f"{st} at {h} m: {r.population:.0f} people, ground {r.elev_m} m, {r.village}").add_to(fg)  # fmt: skip
        fg.add_to(m)
        folium.GeoJson(edges[edges.z < h][["geometry"]].__geo_interface__, name=f"{h} m: roads under water", show=h == levels[-1],
                       style_function=lambda _: {"color": "#08519c", "weight": 2}).add_to(m)  # fmt: skip
    c.add_pois(m, shelters, "#111", "shelters (OSM schools, mosques, hospitals)")
    c.finish_map(m, f"{args.out}/map.html", title)


def make_figure(aoi, G, grid, status, pop, edges, shelters, levels, metrics, title, args):
    crs = G.graph["crs"]
    n = len(levels)
    fig, axes = plt.subplots(1, n + 1, figsize=(5.2 * (n + 1), 6.4), dpi=160)
    pts = [g.representative_point() for g in shelters.to_crs(crs).geometry]
    for ax, h, lv in zip(axes, levels, metrics["levels"]):
        c.draw_streets(ax, G, color="#c8c8c3", lw=0.3)
        wet = edges[edges.z < h]
        for g in wet.geometry:
            ax.plot(*g.xy, color="#08519c", lw=0.8, zorder=4)
        live = pop > 0.5
        for st, col in STATUS_COLORS.items():
            k = (status[h] == st) & live
            ax.scatter(grid["x"][k], grid["y"][k], s=3, c=col, marker="s", lw=0, zorder=3)
        ax.scatter([p.x for p in pts], [p.y for p in pts], s=4, c="#111", lw=0, zorder=5)
        c.frame(ax, G, aoi, f"Water at {h:g} m", f"{lv['people_flooded']:,} flooded, {lv['people_dry_but_cut_off']:,} cut off; "
                f"{lv['road_under_water_pct']}% of road under")  # fmt: skip
    bx = axes[-1]
    x = np.arange(n)
    fl = [lv["people_flooded"] for lv in metrics["levels"]]
    cu = [lv["people_dry_but_cut_off"] for lv in metrics["levels"]]
    bx.bar(x, fl, color=STATUS_COLORS["flooded"], width=0.55, label="ground below the water")
    bx.bar(x, cu, bottom=fl, color=STATUS_COLORS["cut off"], width=0.55, label="dry, but no dry road to a shelter")
    for i in x:
        bx.text(i, fl[i] + cu[i], f"{fl[i] + cu[i]:,}", ha="center", va="bottom", fontsize=9)
    bx.set_xticks(x, [f"{h:g} m" for h in levels])
    bx.set_ylabel("people (GHSL 2020)")
    bx.set_title("People affected per water level", loc="left", fontsize=12, fontweight="bold")
    bx.legend(fontsize=8, loc="upper left", frameon=False)
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    handles = [Line2D([0], [0], marker="s", ls="", color=col, label=st) for st, col in STATUS_COLORS.items()]
    handles += [Line2D([0], [0], color="#08519c", label="road under water"),
                Line2D([0], [0], marker="o", ls="", color="#111", markersize=4, label="shelter (OSM)")]  # fmt: skip
    fig.legend(handles=handles, loc="lower left", ncol=5, frameon=False, fontsize=8.5, bbox_to_anchor=(0.01, 0.0))
    dem = "Copernicus GLO-30 DSM (a surface model)" if not args.dem else args.dem
    fig.text(0.99, 0.005, f"{c.ATTRIBUTION}. Elevation: {dem}, metres above EGM2008. Population: GHSL GHS-POP R2023A. "
             "Bathtub model: no drainage, sea walls or pumps.", ha="right", fontsize=7.5, color="#555")  # fmt: skip
    fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(f"{args.out}/figure.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
