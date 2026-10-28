# /// script
# requires-python = ">=3.10"
# dependencies = ["osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""POI coverage: how many hospitals, schools, parks, markets, transit stops an area has in OpenStreetMap, their
density, how far people are from the nearest one, and how a straight-line circle misjudges that.

    uv run poi_coverage.py work/aoi.json --categories hospital,school,park,market,bus_stop,rail --out work/coverage

For each category: count and density per km², the median and 90th-percentile minutes from the area's cells to the
nearest one along the street network, the share of cells within --minutes by network, and the share a straight
circle of the same reach would claim (the gap is what barriers such as rivers, rail and missing streets remove).
Writes metrics.json, pois.geojson, map.html and figure.png.

OSM completeness varies by city and by category: markets and small clinics are the least mapped. A count of zero is
not proof that no facility exists.
"""

import argparse
import json

import common as c
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--categories", default="hospital,school,park,market,bus_stop,rail")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--speed-kmh", type=float, default=c.WALK_KMH)
    ap.add_argument("--buffer-m", type=float, default=1500)
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    c.outdir(args.out)
    aoi = c.load_aoi(args.aoi)
    cats = c.parse_categories(args.categories)
    res = c.compute_access(aoi, cats, "walk", args.buffer_m, args.speed_kmh)
    G, grid = res["G"], res["grid"]
    on = grid["on_network"]
    area = c.area_km2(G, aoi)
    reach_m = args.speed_kmh * 1000 / 60 * args.minutes
    xy = np.c_[grid["x"], grid["y"]][on]

    out = {
        "place": aoi["name"],
        "area_km2": round(area, 2),
        "limit_min": args.minutes,
        "straight_line_radius_m": round(reach_m),
        "categories": {},
    }
    for cat, r in res["cats"].items():
        counts = c.poi_counts(aoi, r["pois"])
        mins = r["minutes"][on]
        ax_, ay_, _ = c.access_points(r["pois"], G.graph["crs"])
        straight = float((cKDTree(np.c_[ax_, ay_]).query(xy)[0] <= reach_m).mean() * 100) if len(ax_) else 0.0
        fin = np.isfinite(mins)
        out["categories"][cat] = {
            **counts,
            "per_km2": round(counts["in_area"] / area, 2),
            "median_min": round(float(np.median(mins[fin])), 1) if fin.any() else None,
            "p90_min": round(float(np.percentile(mins, 90)), 1) if np.isfinite(np.percentile(mins, 90)) else None,
            "network_within_pct": round(c.share_within(r["minutes"], on, args.minutes), 1),
            "straight_line_within_pct": round(straight, 1),
        }
    out["caveat"] = "OSM may lack POIs that exist; zero mapped is not zero real."
    c.save_json(out, f"{args.out}/metrics.json")
    pois = gpd.GeoDataFrame(pd.concat([r["pois"] for r in res["cats"].values()]), crs=4326)
    pois["geometry"] = [g.representative_point() for g in pois.geometry]
    pois.to_file(f"{args.out}/pois.geojson", driver="GeoJSON")

    title = args.title or f"{aoi['name']}: POI coverage"
    m = c.base_map(aoi)
    for cat in cats:
        c.add_pois(m, pois[pois.category == cat], c.COLORS.get(cat, "#333"), cat)
    c.finish_map(m, f"{args.out}/map.html", title)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 6.2), dpi=160, gridspec_kw={"width_ratios": [1.2, 1]})
    c.draw_streets(ax, G)
    crs = G.graph["crs"]
    for cat in cats:
        p = res["cats"][cat]["pois"].to_crs(crs)
        pts = [g.representative_point() for g in p.geometry]
        ax.scatter(
            [q.x for q in pts],
            [q.y for q in pts],
            s=26,
            c=c.COLORS.get(cat, "#333"),
            edgecolor="white",
            lw=0.5,
            zorder=5,
            label=cat.replace("_", " "),
        )
    c.frame(
        ax,
        G,
        aoi,
        title,
        f"{sum(v['in_area'] for v in out['categories'].values())} mapped POIs in {out['area_km2']} km²",
    )
    ax.legend(loc="lower left", fontsize=8, frameon=True, ncol=2)
    y = np.arange(len(cats))
    net = [out["categories"][k]["network_within_pct"] for k in cats]
    st = [out["categories"][k]["straight_line_within_pct"] for k in cats]
    bx.barh(y - 0.2, st, 0.4, color="#bbbbbb", label=f"straight circle ({reach_m:.0f} m)")
    bx.barh(y + 0.2, net, 0.4, color="#2b6cb0", label=f"along streets ({args.minutes:.0f} min)")
    bx.set_yticks(y, [k.replace("_", " ") for k in cats])
    bx.invert_yaxis()
    bx.set_xlim(0, 105)
    bx.set_xlabel("% of the area reached")
    for i, (a, b) in enumerate(zip(st, net)):
        bx.text(max(a, b) + 1.5, i, f"{b:.0f}% vs {a:.0f}%", va="center", fontsize=8)
    bx.legend(loc="lower right", fontsize=8, frameon=False)
    for s in ("top", "right"):
        bx.spines[s].set_visible(False)
    bx.set_title("Street network vs straight-line reach", loc="left", fontsize=12, fontweight="bold")
    fig.text(0.99, 0.01, f"{c.ATTRIBUTION}. OSM may lack POIs that exist.", ha="right", fontsize=7.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(f"{args.out}/figure.png")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
