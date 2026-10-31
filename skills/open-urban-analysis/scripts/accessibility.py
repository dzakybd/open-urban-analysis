# /// script
# requires-python = ">=3.10"
# dependencies = ["rasterio>=1.4", "osmnx>=2.0", "geopandas>=1.0", "networkx>=3.3", "shapely>=2.0", "folium>=0.19", "matplotlib>=3.9", "numpy>=2.0", "scipy", "scikit-learn"]
# ///
"""Walking (or driving) accessibility: how many minutes along the street network from each part of an area to the
nearest hospital, school, park, market or any other POI category, and the share of the area beyond a time limit.

    uv run accessibility.py work/aoi.json --categories hospital,school,park,market --minutes 15 --out work/access

Network distance, not a straight-line radius: a river, a rail line or a missing street lengthens the walk. The area is
a 100 m grid; each cell is snapped to its street node (cells more than 200 m from any street are left out and
reported). POIs up to --buffer-m outside the area count, so the edge is not penalised. Writes metrics.json,
isochrones.geojson, cells.geojson, pois.geojson, map.html and figure.png.

Missing OSM POIs are not missing facilities: a school or market nobody mapped shows up here as a gap.
"""

import argparse
import json

import common as c
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aoi")
    ap.add_argument("--categories", default="hospital,school,park,market")
    ap.add_argument("--mode", choices=["walk", "drive"], default="walk")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--speed-kmh", type=float, default=c.WALK_KMH)
    ap.add_argument("--buffer-m", type=float, default=1500)
    ap.add_argument("--spacing-m", type=float, default=100)
    ap.add_argument(
        "--population", action="store_true", help="weight cells by GHSL population (downloads a ~20 MB tile once)"
    )
    ap.add_argument(
        "--exclude-name", help="regex: drop POIs whose OSM name matches (for example 'dental' among hospitals)"
    )
    ap.add_argument("--title")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    c.outdir(args.out)
    aoi = c.load_aoi(args.aoi)
    cats = c.parse_categories(args.categories)
    res = c.compute_access(
        aoi, cats, args.mode, args.buffer_m, args.speed_kmh, args.spacing_m, exclude_name=args.exclude_name
    )
    G, grid = res["G"], res["grid"]
    on, lim = grid["on_network"], args.minutes
    limits = sorted({5, 10, lim})

    metrics = {
        "place": aoi["name"],
        "mode": args.mode,
        "speed_kmh": args.speed_kmh,
        "limit_min": lim,
        "area_km2": round(c.area_km2(G, aoi), 2),
        "cells": len(on),
        "cells_on_network": int(on.sum()),
        "off_network_pct": round(float((~on).mean() * 100), 1),
        "categories": {},
    }
    pop = c.ghsl_population(grid["x"], grid["y"], G.graph["crs"]) if args.population else None
    if pop is not None:
        metrics["population"] = {
            "source": "GHSL GHS-POP R2023A, 2020, 100 m (modelled, not a census)",
            "total_on_network": round(float(pop[on].sum())),
            "total_in_area": round(float(pop.sum())),
        }
    iso_all, pois_all = [], []
    reach_all = np.ones(on.sum(), bool)
    reach_none = np.ones(on.sum(), bool)
    for cat, r in res["cats"].items():
        m = r["minutes"][on]
        metrics["categories"][cat] = {
            **c.poi_counts(aoi, r["pois"]),
            "reachable_nodes": len(r["nodes"]),
            **{f"within_{int(t)}_min_pct": round(c.share_within(r["minutes"], on, t), 1) for t in limits},
            "beyond_limit_pct": round(100 - c.share_within(r["minutes"], on, lim), 1),
            "median_min": round(float(np.median(m)), 1) if np.isfinite(np.median(m)) else None,
            "p90_min": round(float(np.percentile(m, 90)), 1) if np.isfinite(np.percentile(m, 90)) else None,
            "unreachable_pct": round(float((~np.isfinite(m)).mean() * 100), 1),
        }
        if pop is not None:
            w = pop[on]
            metrics["categories"][cat]["beyond_limit_population"] = round(float(w[~(m <= lim)].sum()))
            metrics["categories"][cat]["beyond_limit_population_pct"] = round(
                float(w[~(m <= lim)].sum() / w.sum() * 100), 1
            )
        reach_all &= m <= lim
        reach_none &= ~(m <= lim)
        iso = c.isochrones(G, r["surface"], limits)
        iso["category"] = cat
        iso_all.append(iso)
        pois_all.append(r["pois"])
    metrics["all_categories_within_limit_pct"] = round(float(reach_all.mean() * 100), 1)
    metrics["no_category_within_limit_pct"] = round(float(reach_none.mean() * 100), 1)
    metrics["beyond_limit_for_at_least_one_pct"] = round(100 - metrics["all_categories_within_limit_pct"], 1)
    if pop is not None:
        w = pop[on]
        metrics["beyond_limit_for_at_least_one_population"] = round(float(w[~reach_all].sum()))
        metrics["beyond_limit_for_at_least_one_population_pct"] = round(float(w[~reach_all].sum() / w.sum() * 100), 1)
    metrics["caveat"] = "OSM may lack POIs that exist; a gap here means 'not mapped within reach', not 'no facility'."

    # files
    out = args.out
    gdf_iso = gpd.GeoDataFrame(__import__("pandas").concat(iso_all), crs=4326)
    gdf_iso.to_file(f"{out}/isochrones.geojson", driver="GeoJSON")
    pois = gpd.GeoDataFrame(__import__("pandas").concat(pois_all), crs=4326)
    pois["geometry"] = [g.representative_point() for g in pois.geometry]
    pois.to_file(f"{out}/pois.geojson", driver="GeoJSON")
    cells = gpd.GeoDataFrame(
        {f"min_{k}": np.round(v["minutes"], 1) for k, v in res["cats"].items()},
        geometry=gpd.points_from_xy(grid["x"], grid["y"]),
        crs=G.graph["crs"],
    ).to_crs(4326)
    cells["on_network"] = on
    if pop is not None:
        cells["population"] = np.round(pop, 1)
    cells = cells.replace([np.inf], np.nan)
    cells.to_file(f"{out}/cells.geojson", driver="GeoJSON")
    c.save_json(metrics, f"{out}/metrics.json")

    make_map(aoi, res, gdf_iso, pois, cells, args, f"{out}/map.html")
    make_figure(aoi, res, metrics, args, f"{out}/figure.png")
    print(json.dumps(metrics, indent=2))


def make_map(aoi, res, iso, pois, cells, args, path):
    import folium

    m = c.base_map(aoi)
    lim = args.minutes
    for cat in res["cats"]:
        sub = iso[(iso.category == cat) & (iso.minutes == lim)]
        folium.GeoJson(
            sub.__geo_interface__, name=f"{cat}: within {lim:.0f} min",
            style_function=lambda _, col=c.COLORS[cat]: {"color": col, "weight": 1, "fillColor": col, "fillOpacity": 0.18},
            show=cat == next(iter(res["cats"])),
        ).add_to(m)  # fmt: skip
        c.add_pois(m, pois[pois.category == cat], c.COLORS[cat], cat)
    far = folium.FeatureGroup(name=f"Cells beyond {lim:.0f} min from at least one category")
    cols = [f"min_{k}" for k in res["cats"]]
    for _, r in cells[cells.on_network].iterrows():
        vals = r[cols]
        if (vals.isna() | (vals > lim)).any():
            missing = [k.removeprefix("min_") for k in cols if np.isnan(r[k]) or r[k] > lim]
            folium.CircleMarker([r.geometry.y, r.geometry.x], radius=2, color="#d73027", weight=0, fill=True,
                                fill_opacity=0.5, tooltip=f"beyond {lim:.0f} min: {', '.join(missing)}").add_to(far)  # fmt: skip
    far.add_to(m)
    c.finish_map(m, path, args.title or f"{aoi['name']}: {args.mode} access within {lim:.0f} min")


def make_figure(aoi, res, metrics, args, path):
    G, cats, lim = res["G"], list(res["cats"]), args.minutes
    # With a single category the "all categories" panel repeats the category panel, so it is left out.
    combined = len(cats) > 1
    n = len(cats) + 1 + combined
    ncol = 3 if n > 4 else 2
    nrow = -(-n // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 5.4 * nrow + 0.8), dpi=160)
    axes = np.atleast_1d(axes).ravel()
    crs = G.graph["crs"]
    for ax, cat in zip(axes, cats):
        r = res["cats"][cat]
        c.draw_streets(ax, G)
        iso = c.isochrones(G, r["surface"], sorted({5, 10, lim})).to_crs(crs)
        for _, row in iso.sort_values("minutes", ascending=False).iterrows():
            col = c.ISO_COLORS.get(int(row.minutes), "#f2aaa4")
            for g in getattr(row.geometry, "geoms", [row.geometry]):
                ax.fill(*g.exterior.xy, color=col, lw=0, zorder=2)
        p = r["pois"].to_crs(crs)
        pts = [g.representative_point() for g in p.geometry]
        ax.scatter([q.x for q in pts], [q.y for q in pts], s=28, c=c.COLORS[cat], edgecolor="white", lw=0.6, zorder=5)
        mm = metrics["categories"][cat]
        c.frame(
            ax,
            G,
            aoi,
            cat.replace("_", " ").title(),
            f"{mm[f'within_{int(lim)}_min_pct']}% within {lim:.0f} min · "
            f"{mm['in_area']} mapped in area, {mm['in_buffer']} in buffer",
        )
    # all categories reached
    if combined:
        ax = axes[len(cats)]
        c.draw_streets(ax, G)
        on = res["grid"]["on_network"]
        allmin = np.max([res["cats"][k]["minutes"] for k in cats], axis=0)
        ok = (allmin <= lim) & on
        bad = (allmin > lim) & on
        ax.scatter(res["grid"]["x"][ok], res["grid"]["y"][ok], s=7, c="#1a9850", marker="s", lw=0, zorder=3)
        ax.scatter(res["grid"]["x"][bad], res["grid"]["y"][bad], s=7, c="#d73027", marker="s", lw=0, zorder=3)
        c.frame(ax, G, aoi, f"All {len(cats)} within {lim:.0f} min",
                f"{metrics['all_categories_within_limit_pct']}% of the area; {metrics['beyond_limit_for_at_least_one_pct']}% misses at least one")  # fmt: skip
    # bars
    if len(cats) == 1:
        # A single bar leaves most of the panel empty; the same numbers read better as a small table.
        ax = axes[1]
        ax.axis("off")
        mm = metrics["categories"][cats[0]]
        rows = [
            ("within 5 min", f"{mm['within_5_min_pct']:.0f}%"),
            (f"within {lim:.0f} min", f"{mm[f'within_{int(lim)}_min_pct']:.0f}%"),
            (f"beyond {lim:.0f} min", f"{mm['beyond_limit_pct']:.0f}%"),
            (f"median {args.mode}", f"{mm['median_min']:.1f} min"),
            ("90th percentile", f"{mm['p90_min']:.1f} min"),
        ]
        if "beyond_limit_population" in mm:
            rows += [
                ("people beyond reach", f"{mm['beyond_limit_population']:,.0f}"),
                ("of the population", f"{mm['beyond_limit_population_pct']:.0f}%"),
            ]
        ax.set_title("Coverage", loc="left", fontsize=13, fontweight="bold")
        for i, (k, v) in enumerate(rows):
            y = 0.86 - i * 0.105
            ax.text(0.02, y, k, transform=ax.transAxes, fontsize=11.5, color="#555", va="top")
            ax.text(0.98, y, v, transform=ax.transAxes, fontsize=14, fontweight="bold", ha="right", va="top")
    else:
        ax = axes[len(cats) + 1]
        vals = [metrics["categories"][k][f"within_{int(lim)}_min_pct"] for k in cats]
        ax.barh(range(len(cats)), vals, height=0.55, color=[c.COLORS[k] for k in cats])
        ax.set_yticks(range(len(cats)), [k.replace("_", " ") for k in cats])
        ax.set_ylim(-0.5, len(cats) - 0.5)
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_xlabel(f"% of area within {lim:.0f} min ({args.mode})")
        for i, v in enumerate(vals):
            ax.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=10)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_title("Coverage", loc="left", fontsize=13, fontweight="bold")
    for ax in axes[n:]:
        ax.axis("off")
    handles = [
        Line2D([0], [0], marker="s", ls="", color=c.ISO_COLORS.get(t, "#f2aaa4"), markersize=9, label=f"≤ {t:g} min")
        for t in sorted({5, 10, lim})
    ]
    fig.legend(handles=handles, loc="lower left", ncol=3, frameon=False, bbox_to_anchor=(0.01, 0.0))
    fig.suptitle(
        args.title or f"{aoi['name']}: {args.mode} access within {lim:.0f} min",
        x=0.01,
        ha="left",
        fontsize=16,
        fontweight="bold",
    )
    fig.text(
        0.99,
        0.005,
        f"{c.ATTRIBUTION}. "
        + (
            f"Network distance at {args.speed_kmh} km/h"
            if args.mode == "walk"
            else "Free-flow drive times by road class"
        )
        + "; a gap may be an unmapped POI.",
        ha="right",
        fontsize=7.5,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
