"""Shared helpers for the open-urban-analysis scripts: OSM downloads with a cache, the AOI file, travel-time
surfaces over the street network, and the map and figure outputs.

Everything comes from OpenStreetMap through OSMnx (Overpass API) and is free without a key. Overpass is a shared
volunteer service: OSMnx waits for a free slot and caches every response in OUA_CACHE (default
~/.cache/open-urban-analysis), so a place is downloaded once. Map data (c) OpenStreetMap contributors (ODbL).
"""

import json
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import Point, box
from shapely.ops import unary_union

USER_AGENT = "open-urban-analysis/0.1 (https://github.com/dzakybd/open-urban-analysis)"
ATTRIBUTION = "Map data (c) OpenStreetMap contributors, ODbL"

WALK_KMH = 4.8  # a common planning speed for a 15-minute city: 80 m per minute
# Typical urban driving speeds in km/h by OSM highway class, used where maxspeed is not tagged. They are
# assumptions for ranking routes, not measured traffic.
DRIVE_KMH = {
    "motorway": 70, "trunk": 45, "primary": 35, "secondary": 30, "tertiary": 25,
    "residential": 20, "unclassified": 25, "living_street": 10, "service": 10,
}  # fmt: skip

# POI categories as OSM tag filters (OSMnx ORs the values). Missing OSM tags are not missing facilities.
CATEGORIES = {
    "hospital": {"amenity": ["hospital"]},
    "clinic": {"amenity": ["clinic", "doctors"], "healthcare": ["clinic", "centre"]},
    "school": {"amenity": ["school"]},
    "park": {"leisure": ["park", "garden", "playground"]},
    "market": {"amenity": ["marketplace"], "shop": ["supermarket"]},
    "bus_stop": {"highway": ["bus_stop"], "public_transport": ["platform"]},
    "rail": {"railway": ["station", "halt", "tram_stop"], "station": ["subway", "light_rail"]},
    "transjakarta": {"highway": ["bus_stop"], "public_transport": ["platform"]},
}
# Categories that are a subset of a tag filter, picked by a regex over the stop's name, network, operator or brand.
CATEGORY_MATCH = {"transjakarta": r"trans ?jakarta|busway|\btj\b"}


# Public Overpass servers, tried in turn when one is at capacity. All are volunteer-run: back off, do not hammer.
# Set OUA_OVERPASS to a comma-separated list (for example your own instance) to replace them. On 28 Oct 2026 the main
# server answered slowly and the mirrors timed out, so the main server comes first.
OVERPASS = os.environ.get(
    "OUA_OVERPASS", "https://overpass-api.de/api,https://overpass.private.coffee/api,https://overpass.kumi.systems/api"
).split(",")


def setup_osm():
    ox.settings.use_cache = True
    ox.settings.cache_folder = os.environ.get("OUA_CACHE", str(Path.home() / ".cache" / "open-urban-analysis"))
    ox.settings.requests_timeout = 300
    ox.settings.log_console = False
    ox.settings.http_user_agent = USER_AGENT
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + [
        "sidewalk",
        "sidewalk:left",
        "sidewalk:right",
        "sidewalk:both",
        "footway",
        "lit",
    ]


setup_osm()


def save_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    def default(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return None if np.isnan(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    Path(path).write_text(json.dumps(obj, indent=2, default=default, allow_nan=False, ensure_ascii=False))


def load_json(path):
    return json.loads(Path(path).read_text())


# ---- the AOI -------------------------------------------------------------------------------------------------


def circle(lat, lng, radius_m):
    """A WGS84 disc: buffered in a local UTM zone so the radius is in metres."""
    g = gpd.GeoSeries([Point(lng, lat)], crs=4326)
    return g.to_crs(g.estimate_utm_crs()).buffer(radius_m, 64).to_crs(4326).iloc[0]


def load_aoi(path):
    """aoi.json -> dict with a shapely WGS84 `polygon` (a disc around lat/lng, or the bbox)."""
    aoi = load_json(path)
    if aoi.get("radius_m"):
        aoi["polygon"] = circle(aoi["lat"], aoi["lng"], aoi["radius_m"])
    else:
        aoi["polygon"] = box(*aoi["bbox"])
    return aoi


def project_polygon(poly, crs):
    return gpd.GeoSeries([poly], crs=4326).to_crs(crs).iloc[0]


def area_km2(G, aoi):
    return project_polygon(aoi["polygon"], G.graph["crs"]).area / 1e6


# ---- OSM downloads -------------------------------------------------------------------------------------------


def buffered(aoi, buffer_m):
    """The AOI grown by buffer_m, so routes and POIs just outside it still count (no edge effect)."""
    g = gpd.GeoSeries([aoi["polygon"]], crs=4326)
    utm = g.estimate_utm_crs()
    return g.to_crs(utm).buffer(buffer_m).to_crs(4326).iloc[0]


# ---- offline backend: a Geofabrik extract clipped with osmium ------------------------------------------------
# Set OUA_PBF to a .osm.pbf (for example https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf) and the
# graph and POIs come from it instead of Overpass: same OSMnx code, no shared server, reproducible for a given file.
# Needs the `osmium` command (brew install osmium-tool). The clipped region is cached next to the OSMnx cache.

# The same exclusions OSMnx applies to its "walk" and "drive" network types, so the offline graph matches the Overpass one.
WALK_DROP = {"abandoned", "bus_guideway", "construction", "cycleway", "motor", "no", "planned", "platform", "proposed",
             "raceway", "razed", "steps"}  # fmt: skip
DRIVE_KEEP = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
              "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street"}  # fmt: skip


def local_pbf():
    p = os.environ.get("OUA_PBF")
    return Path(p).expanduser() if p else None


def _local_xml(poly):
    """Clip the OUA_PBF extract to the polygon's bounding box and write it as OSM XML (cached by box)."""
    import hashlib
    import subprocess

    bbox = ",".join(f"{v:.5f}" for v in poly.bounds)
    key = hashlib.sha1(f"{local_pbf().name}{bbox}".encode()).hexdigest()[:16]
    out = Path(ox.settings.cache_folder) / f"extract-{key}.osm"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        tmp = out.with_suffix(".pbf")
        subprocess.run(["osmium", "extract", "-b", bbox, "-O", "-o", str(tmp), str(local_pbf())], check=True)
        subprocess.run(["osmium", "cat", "-O", "-f", "osm", "-o", str(out), str(tmp)], check=True)
        tmp.unlink()
    return out


def _local_graph(poly, mode):
    """The OSMnx graph for `mode` from the local extract: highways of the right classes, simplified, largest component."""
    G = ox.graph_from_xml(_local_xml(poly), bidirectional=(mode == "walk"), simplify=False, retain_all=True)
    drop = []
    for u, v, k, d in G.edges(keys=True, data=True):
        hw = d.get("highway")
        hw = hw[0] if isinstance(hw, list) else hw
        if d.get("area") == "yes":
            bad = True
        elif mode == "walk":
            bad = (
                hw in WALK_DROP
                or d.get("foot") == "no"
                or d.get("service") == "private"
                or d.get("access") == "private"
            )
        else:
            bad = (
                hw not in DRIVE_KEEP
                or d.get("motor_vehicle") == "no"
                or d.get("motorcar") == "no"
                or d.get("access") == "private"
            )
        if bad:
            drop.append((u, v, k))
    G.remove_edges_from(drop)
    G.remove_nodes_from(list(nx.isolates(G)))
    G = ox.truncate.truncate_graph_polygon(G, poly, truncate_by_edge=True)
    G = ox.truncate.largest_component(ox.simplification.simplify_graph(G), strongly=True)
    nx.set_node_attributes(G, ox.stats.count_streets_per_node(G), "street_count")
    return G


def with_retry(fn, *args, tries=12, **kwargs):
    """Call an OSMnx download, and when Overpass is busy (502/504/429, timeout) wait with exponential backoff and move to
    the next public server. Responses are cached, so a retry after a crash costs nothing for finished queries."""
    wait = 20
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if isinstance(e, ox._errors.InsufficientResponseError) or i == tries - 1:
                raise
            ox.settings.overpass_url = OVERPASS[(i + 1) % len(OVERPASS)]
            print(
                f"Overpass busy ({type(e).__name__}); waiting {wait}s, then trying {ox.settings.overpass_url}",
                file=sys.stderr,
            )
            time.sleep(wait)
            wait = min(wait * 2, 240)


def fetch_graph(aoi, mode="walk", buffer_m=1500, speed_kmh=WALK_KMH):
    """Street network around the AOI, projected to UTM, with `travel_time` (seconds) on every edge."""
    poly = buffered(aoi, buffer_m)
    if local_pbf():
        G = _local_graph(poly, mode)
    else:
        G = with_retry(ox.graph_from_polygon, poly, network_type=mode, simplify=True)
    G = ox.project_graph(G)
    if mode == "walk":
        for _, _, d in G.edges(data=True):
            d["travel_time"] = d["length"] / (speed_kmh * 1000 / 3600)
    else:
        G = ox.routing.add_edge_speeds(G, hwy_speeds=DRIVE_KMH, fallback=25)
        G = ox.routing.add_edge_travel_times(G)
    return G


_poi_cache = {}


def _all_pois(aoi, buffer_m):
    """One Overpass request for every category's tags at once (a single query is kinder to the shared servers than seven)."""
    key = (aoi["polygon"].wkt, buffer_m)
    if key not in _poi_cache:
        tags = {}
        for spec in CATEGORIES.values():
            for k, v in spec.items():
                tags.setdefault(k, [])
                tags[k] += [x for x in v if x not in tags[k]]
        poly = buffered(aoi, buffer_m)
        try:
            if local_pbf():
                gdf = ox.features_from_xml(_local_xml(poly), polygon=poly, tags=tags).reset_index(drop=True)
            else:
                gdf = with_retry(ox.features_from_polygon, poly, tags).reset_index(drop=True)
        except ox._errors.InsufficientResponseError:
            gdf = gpd.GeoDataFrame({"name": []}, geometry=[], crs=4326)
        if "name" not in gdf:
            gdf["name"] = None
        _poi_cache[key] = gdf
    return _poi_cache[key]


def fetch_pois(aoi, category, buffer_m=1500, tags=None):
    """OSM features of one category inside the buffered AOI, as a GeoDataFrame in WGS84 with a `name` column."""
    gdf = _all_pois(aoi, buffer_m)
    mask = np.zeros(len(gdf), bool)
    for key, values in (tags or CATEGORIES[category]).items():
        if key in gdf:
            mask |= gdf[key].isin(values).to_numpy()
    if category in CATEGORY_MATCH:
        cols = [c_ for c_ in ("name", "network", "operator", "brand") if c_ in gdf]
        text = gdf[cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        mask &= text.str.contains(CATEGORY_MATCH[category], regex=True).to_numpy()
    return gdf[mask][["name", "geometry"]].reset_index(drop=True).assign(category=category)


def access_points(pois, crs, step_m=100):
    """Points a person can enter a POI from: the point itself, or for an area (a park, a hospital campus) points along its
    outline every step_m metres. Returns projected x, y arrays and the index of the POI each came from."""
    p = pois.to_crs(crs)
    xs, ys, idx = [], [], []
    for i, geom in enumerate(p.geometry):
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "Point":
            pts = [geom]
        else:
            line = geom.boundary if geom.geom_type in ("Polygon", "MultiPolygon") else geom
            parts = list(line.geoms) if hasattr(line, "geoms") else [line]
            pts = [pt for part in parts for pt in (part.interpolate(d) for d in np.arange(0, part.length, step_m))]
            pts = pts or [geom.representative_point()]
        for pt in pts:
            xs.append(pt.x)
            ys.append(pt.y)
            idx.append(i)
    return np.array(xs), np.array(ys), np.array(idx)


def poi_nodes(G, pois, max_snap_m=250):
    """Street-network nodes nearest to a POI's entrances, dropping those more than max_snap_m from any street."""
    xs, ys, _ = access_points(pois, G.graph["crs"])
    if len(xs) == 0:
        return set()
    nodes, dist = ox.distance.nearest_nodes(G, xs, ys, return_dist=True)
    return {int(n) for n, d in zip(nodes, dist) if d <= max_snap_m}


# ---- travel times --------------------------------------------------------------------------------------------


def make_grid(G, aoi, spacing_m=100, max_snap_m=200):
    """Regular grid of points inside the AOI, each snapped to its nearest street node. Cells farther than max_snap_m from
    a street are marked off-network (water, rail yards, big estates) and left out of shares."""
    poly = project_polygon(aoi["polygon"], G.graph["crs"])
    minx, miny, maxx, maxy = poly.bounds
    gx, gy = np.meshgrid(
        np.arange(minx + spacing_m / 2, maxx, spacing_m), np.arange(miny + spacing_m / 2, maxy, spacing_m)
    )
    pts = gpd.GeoSeries(gpd.points_from_xy(gx.ravel(), gy.ravel()))
    inside = pts.within(poly).to_numpy()
    x, y = gx.ravel()[inside], gy.ravel()[inside]
    nodes, dist = ox.distance.nearest_nodes(G, x, y, return_dist=True)
    return {"x": x, "y": y, "node": np.asarray(nodes), "snap_m": np.asarray(dist), "on_network": np.asarray(dist) <= max_snap_m,
            "spacing_m": spacing_m, "cell_ha": spacing_m**2 / 1e4}  # fmt: skip


def time_surface(G, sources, cutoff_min=None):
    """Minutes of travel from every node TO the nearest source node (multi-source Dijkstra on the reversed graph, so
    one-way streets count the right way round)."""
    if not sources:
        return {}
    cutoff = cutoff_min * 60 if cutoff_min else None
    t = nx.multi_source_dijkstra_path_length(G.reverse(copy=False), sources, cutoff=cutoff, weight="travel_time")
    return {n: s / 60 for n, s in t.items()}


def grid_minutes(grid, surface, speed_kmh=WALK_KMH):
    """Minutes from each grid cell to the nearest source: network time plus the walk from the cell to its street node."""
    node_min = np.array([surface.get(int(n), np.inf) for n in grid["node"]])
    return node_min + grid["snap_m"] / (speed_kmh * 1000 / 60)


def share_within(minutes, on_network, limit):
    """Share (0-100) of on-network cells reached within `limit` minutes."""
    m = minutes[on_network]
    return float((m <= limit).mean() * 100) if len(m) else float("nan")


def isochrones(G, surface, limits, buffer_m=40):
    """Network isochrones: the streets reachable within each limit (minutes), buffered a little, as polygons in WGS84."""
    edges = ox.graph_to_gdfs(G, nodes=False)
    rows = []
    for lim in sorted(limits, reverse=True):
        ok = {n for n, t in surface.items() if t <= lim}
        e = edges[[u in ok and v in ok for u, v, _ in edges.index]]
        if e.empty:
            continue
        rows.append({"minutes": lim, "geometry": unary_union(e.geometry.buffer(buffer_m)).simplify(10)})
    return gpd.GeoDataFrame(rows, crs=G.graph["crs"]).to_crs(4326)


# ---- outputs -------------------------------------------------------------------------------------------------

COLORS = {"hospital": "#d62728", "clinic": "#e377c2", "school": "#1f77b4", "park": "#2ca02c", "market": "#ff7f0e",
          "bus_stop": "#9467bd", "rail": "#8c564b", "transjakarta": "#17becf"}  # fmt: skip
ISO_COLORS = {5: "#8fcca6", 10: "#fbd3a0", 15: "#f2aaa4"}  # opaque tints, drawn widest first


def base_map(aoi, zoom=14):
    import folium

    m = folium.Map(location=[aoi["lat"], aoi["lng"]], zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    folium.GeoJson(
        gpd.GeoSeries([aoi["polygon"]], crs=4326).__geo_interface__,
        name="Area analysed",
        style_function=lambda _: {"color": "#444", "weight": 2, "fill": False, "dashArray": "6 4"},
    ).add_to(m)
    return m


def add_pois(m, pois, color, label):
    import folium

    fg = folium.FeatureGroup(name=label)
    for _, r in pois.iterrows():
        c = r.geometry.representative_point()
        folium.CircleMarker(
            [c.y, c.x], radius=5, color="#fff", weight=1, fill=True, fill_color=color, fill_opacity=0.95,
            tooltip=f"{label}: {r['name'] or '(unnamed in OSM)'}",
        ).add_to(fg)  # fmt: skip
    fg.add_to(m)


def finish_map(m, path, title):
    import folium

    m.get_root().html.add_child(
        folium.Element(
            f'<div style="position:fixed;bottom:6px;left:6px;z-index:9999;background:#fffc;padding:3px 7px;font:11px sans-serif">'
            f"{title}. {ATTRIBUTION}.</div>"
        )
    )
    folium.LayerControl(collapsed=False).add_to(m)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    m.save(path)


def draw_streets(ax, G, color="#b5b5b0", lw=0.5):
    from matplotlib.collections import LineCollection

    edges = ox.graph_to_gdfs(G, nodes=False)
    segs = [np.array(g.coords) for g in edges.geometry]
    ax.add_collection(LineCollection(segs, colors=color, linewidths=lw, zorder=3))


def frame(ax, G, aoi, title, subtitle=""):
    poly = project_polygon(aoi["polygon"], G.graph["crs"])
    x, y = poly.exterior.xy
    ax.plot(x, y, color="#333", lw=1.2, ls="--", zorder=6)
    minx, miny, maxx, maxy = poly.bounds
    pad = (maxx - minx) * 0.03
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    if subtitle:
        ax.text(0, 1.005, subtitle, transform=ax.transAxes, fontsize=9, color="#555", va="bottom")


# ---- one analysis step used by several scripts ---------------------------------------------------------------


def parse_categories(text):
    """'hospital,school,park' -> list; each must be a known category (see CATEGORIES)."""
    cats = [c.strip() for c in text.split(",") if c.strip()]
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        raise SystemExit(f"unknown category {bad}; known: {', '.join(CATEGORIES)}")
    return cats


def compute_access(
    aoi, categories, mode="walk", buffer_m=1500, speed_kmh=WALK_KMH, spacing_m=100, G=None, exclude_name=None
):
    """Download the street network and the POIs, then give every grid cell its travel time to the nearest POI of each
    category. Returns a dict with the graph G, the grid and, per category, the POIs and the minutes per cell."""
    G = G or fetch_graph(aoi, mode, buffer_m, speed_kmh)
    grid = make_grid(G, aoi, spacing_m)
    out = {"G": G, "grid": grid, "cats": {}}
    for cat in categories:
        pois = fetch_pois(aoi, cat, buffer_m)
        if exclude_name:
            pois = pois[~pois["name"].fillna("").str.contains(exclude_name, case=False, regex=True)]
        nodes = poi_nodes(G, pois)
        surface = time_surface(G, nodes)
        out["cats"][cat] = {
            "pois": pois,
            "nodes": nodes,
            "surface": surface,
            "minutes": grid_minutes(grid, surface, speed_kmh),
        }
    return out


def poi_counts(aoi, pois):
    """POIs whose representative point falls inside the AOI, against the whole buffered download."""
    inside = sum(aoi["polygon"].contains(g.representative_point()) for g in pois.geometry)
    return {"in_area": int(inside), "in_buffer": len(pois)}


def street_metrics(G, aoi):
    """Connectivity metrics of a street graph over the AOI: OSMnx basic stats with intersections within 10 m merged
    (one crossroads drawn as two nodes counts once), plus momepy meshedness and gamma."""
    import momepy
    import osmnx as ox

    area_m2 = project_polygon(aoi["polygon"], G.graph["crs"]).area
    s = ox.stats.basic_stats(G, area=area_m2, clean_int_tol=10)
    u = nx.Graph(ox.convert.to_undirected(G))
    for _, _, d in u.edges(data=True):
        d.pop("geometry", None)
    spn = s["streets_per_node_proportions"]
    km = s["street_length_total"] / 1000
    return {
        "area_km2": round(area_m2 / 1e6, 2),
        "street_length_km": round(km, 1),
        "street_density_km_per_km2": round(km / (area_m2 / 1e6), 1),
        "intersections": int(s["intersection_count"]),
        "intersection_density_per_km2": round(s["intersection_density_km"], 1),
        "avg_node_degree": round(
            2 * u.number_of_edges() / u.number_of_nodes(), 2
        ),  # streets meeting at a node, each counted once
        "dead_end_share_pct": round(spn.get(1, 0) * 100, 1),
        "circuity": round(s["circuity_avg"], 3),
        "meshedness": round(float(momepy.meshedness(u, radius=None)), 3),
        "gamma": round(float(momepy.gamma(u, radius=None)), 3),
    }


def outdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return str(path)


# ---- optional population (GHSL) ------------------------------------------------------------------------------

GHSL_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/"
    "V1-0/tiles/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}.zip"
)


def ghsl_population(xs, ys, crs):
    """People per 100 m cell at each projected point, from the Global Human Settlement Layer GHS-POP R2023A (2020 epoch,
    100 m, World Mollweide), downloaded once per 1,000 km tile into the cache folder. A modelled grid, not a census:
    it spreads census counts over built-up area, so a single cell can be off by a lot; totals over a few km² are better."""
    import io
    import urllib.request
    import zipfile

    import rasterio
    from pyproj import Transformer

    mx, my = Transformer.from_crs(crs, "ESRI:54009", always_xy=True).transform(np.asarray(xs), np.asarray(ys))
    cols = ((mx + 18041000) // 1_000_000).astype(int) + 1
    rows = ((9000000 - my) // 1_000_000).astype(int) + 1
    out = np.zeros(len(mx))
    cache = Path(ox.settings.cache_folder) / "ghsl"
    cache.mkdir(parents=True, exist_ok=True)
    for row, col in sorted({(int(r), int(c_)) for r, c_ in zip(rows, cols)}):
        tif = cache / f"GHS_POP_E2020_R{row}_C{col}.tif"
        if not tif.exists():
            req = urllib.request.Request(GHSL_URL.format(row=row, col=col), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            name = next(n for n in z.namelist() if n.endswith(".tif"))
            tif.write_bytes(z.read(name))
        pick = (rows == row) & (cols == col)
        with rasterio.open(tif) as src:
            vals = np.array([v[0] for v in src.sample(zip(mx[pick], my[pick]))], dtype=float)
        out[pick] = np.where(vals > 0, vals, 0)
    return out
