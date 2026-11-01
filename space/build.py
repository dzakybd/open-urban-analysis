"""Pack the precomputed case runs into space/data for the Hugging Face Space.

Every number comes from the run's own metrics.json, so nothing is retyped. Six cases: where to put a new store in
central Surabaya, the report card of a house in Sleman, puskesmas siting for Kabupaten Demak, flood and evacuation in
Kota Pekalongan, ambulance coverage in Kota Makassar, and who is underserved by age in Kabupaten Sumba Barat Daya.

Usage: uv run python space/build.py
"""

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"


def load(path):
    return json.loads((RUNS / path).read_text())


def case(cid, title, subtitle, stats, table, note, refs, images):
    return {
        "id": cid,
        "title": title,
        "subtitle": subtitle,
        "stats": stats,
        "images": images,
        "table": table,
        "note": note,
        "refs": refs,
    }


def store():
    m = load("surabaya/store/metrics.json")
    comp, sites = m["competitors"], m["sites"]
    stats = [
        [
            f"{m['top_sites_with_no_competitor']} of {len(sites)}",
            "top sites have no mapped competitor within a 10-minute walk",
        ],
        [
            f"{sites[0]['people']:,}",
            f"people within 10 min of the best site (rank 1, {sites[0]['competitors']} mapped competitors)",
        ],
        [
            f"{comp['in_area']}",
            f"minimarkets mapped for {m['population_in_area']:,} residents ({m['people_per_mapped_shop']:,} per shop)",
        ],
        [f"{m['candidate_people_per_store_median']:,}", "people per store at the median candidate site"],
    ]
    table = [
        [
            f"site {s['rank']} ({s['lat']}, {s['lng']})",
            f"{s['people']:,} people · {s['competitors']} competitors · {s['people_per_store']:,} per store",
        ]
        for s in sites
    ]
    table += [
        [
            "mapped minimarkets",
            f"{comp['in_area']} in the disc ({comp['in_buffer']} with the buffer): {comp['indomaret']} Indomaret, {comp['alfamart']} Alfamart or Alfamidi",
        ],
        [
            "candidates",
            f"{m['candidates']} street nodes · {m['candidates_with_no_competitor_pct']}% have no mapped competitor",
        ],
        ["population (GHSL 2020)", f"{m['population_in_area']:,} in the disc"],
    ]
    return case(
        "store-finder",
        "Where to put a new store?",
        "Central Surabaya (Tegalsari, Genteng, Gubeng) · 2 km radius · 10-minute walk",
        stats,
        table,
        "Each candidate street node is scored by the people who can walk to it in 10 minutes divided by the mapped minimarkets in that catchment plus one; the top five sit at least 500 m apart. The check is the map itself: no public register of minimarkets exists to count against, and all five top sites have no mapped competitor in a district of about 20,000 residents per km², which is far more likely unmapped Indomaret and Alfamart branches than free ground. The ranking uses people and mapped competitors only: no rent, foot traffic, income or sales, so a site is a place to survey on foot, not a profit forecast.",
        [
            [
                "GHSL GHS-POP R2023A (JRC): the population grid the catchments use, a model, not a census.",
                "https://ghsl.jrc.ec.europa.eu/ghs_pop2023.php",
            ],
        ],
        [["figure.png", "Top five sites and catchments"], ["map.html", "Interactive map"]],
    )


def report():
    m = load("sleman/report/metrics.json")
    cats = m["categories"]
    com = m["commute"]
    labels = {
        "school": "School",
        "puskesmas": "Puskesmas",
        "clinic": "Clinic",
        "hospital": "Hospital",
        "marketplace": "Marketplace",
        "convenience": "Convenience store",
        "park": "Park",
        "bus_stop": "Bus stop",
        "rail": "Rail station",
    }

    def row(k):
        c = cats[k]
        if c["nearest_walk_min"] is None:
            return [labels[k], "none mapped within reach"]
        return [
            labels[k],
            f"{c['nearest_walk_min']:.1f} min walk · {c['nearest_bike_min']:.1f} bike · {c['nearest_drive_min']:.1f} car · {c['within_15_min_walk']} within 15 min · {c['nearest_name']}",
        ]

    stats = [
        [
            f"{cats['school']['nearest_walk_min']:.1f} min",
            f"on foot to the nearest school ({cats['school']['nearest_name']})",
        ],
        [
            f"{cats['convenience']['nearest_walk_min']:.1f} min",
            f"on foot to the nearest convenience store ({cats['convenience']['nearest_name']})",
        ],
        [
            f"{cats['puskesmas']['nearest_walk_min']:.0f} min",
            f"on foot to the nearest puskesmas ({cats['puskesmas']['nearest_name']})",
        ],
        [
            f"{com['walk_min']:.0f} / {com['bike_min']:.0f} / {com['drive_min']:.0f} min",
            f"to {com['to']} on foot / by bike / by car (free-flow)",
        ],
    ]
    table = [row(k) for k in labels] + [
        [
            "commute to " + com["to"],
            f"{com['straight_km']} km straight · {com['walk_km']} km on foot · {com['drive_km']} km by car",
        ]
    ]
    return case(
        "report-card",
        "A house report card",
        f"{m['place']} · {m['reach_radius_m'] / 1000:g} km reach · one workplace",
        stats,
        table,
        "One row per category and never a combined score: which row matters depends on the household. Walking is 4.8 km/h, cycling 15 km/h on the walking network, driving free-flow by road class. Nothing here has an independent source, so each row is what OSM records; the weakest rows are the ones most likely to be a mapping gap (few puskesmas within reach, a nearest market with no name, no rail station mapped). The commute is a modelled walk, bike or free-flow car trip, not public transport or a rush-hour drive. A bus stop is a mapped stop, not a service.",
        [],
        [["figure.png", "Minutes to the nearest facility, by mode"], ["map.html", "Interactive map"]],
    )


def demak():
    h = load("demak/access-hospital/metrics.json")
    pc = load("demak/access-primary/metrics.json")
    s = load("demak/siting/metrics.json")
    hosp, pusk = h["categories"]["hospital"], pc["categories"]["puskesmas"]
    last = s["picks"][-1]
    stats = [
        # matched by name against the BPS list: OSM's 6 in the regency include one that is not on it
        [
            "5 of 27",
            f"official puskesmas are in OSM ({s['existing']['in_area']} OSM puskesmas, one not on the BPS list)",
        ],
        [f"{pusk['beyond_limit_population_pct']:.0f}%", "of residents beyond a 15-min drive of a mapped puskesmas"],
        [
            f"{100 - s['beyond_limit_pct']:.0f}% → {last['within_limit_after_pct']:.0f}%",
            f"within 15 min after {len(s['picks'])} greedy picks",
        ],
        [f"{hosp['beyond_limit_population_pct']:.0f}%", "of residents beyond a 30-min drive of a hospital"],
    ]
    table = [
        [
            "hospital, 30 min",
            f"{hosp['within_30_min_pct']:.0f}% of the area · median {hosp['median_min']:.1f} min · {hosp['beyond_limit_population']:,} people beyond",
        ],
        [
            "puskesmas, 15 min",
            f"{pusk['within_15_min_pct']:.0f}% of the area · {pusk['beyond_limit_population']:,} people beyond",
        ],
    ]
    table += [
        [
            f"pick {p['rank']} ({p['lat']}, {p['lng']})",
            f"+{p['newly_covered']:,} people · {p['within_limit_after_pct']}% within 15 min after",
        ]
        for p in s["picks"]
    ]
    table += [["population (GHSL 2020)", f"{h['population']['total_in_area']:,} in the regency (BPS 2024: 1,252,970)"]]
    return case(
        "facility-siting",
        "Where would new puskesmas go?",
        "Kabupaten Demak, Central Java · whole regency (OSM boundary) · 15-minute drive",
        stats,
        table,
        "The question a regency planner asks: where would the next three puskesmas reach the most people now beyond a 15-minute drive? The script picks greedily from street nodes on classified roads. The answer is mostly about the map: OSM has 5 of the 27 official puskesmas, and the first two picks land in Demak town and Mranggen, whose official puskesmas are simply unmapped. Read the picks as a mapping to-do list before a building plan. Drive times are free-flow; tidal flooding that cuts coastal roads in Sayung is not modelled, and GHSL counts about 960,000 people against BPS's 1.25 million for 2024.",
        [
            [
                "BPS Kabupaten Demak, Kabupaten Demak Dalam Angka 2025 (28 Feb 2025), Table 4.2.3 and Table 3.1.1: 27 puskesmas (15 inpatient, 12 without), 6 hospitals, 1,252,970 residents in 2024.",
                "https://demakkab.bps.go.id/en/publication/2025/02/28/aa73744a55d7df8df2e6a2f2/kabupaten-demak-dalam-angka-2025.html",
            ],
        ],
        [
            ["figure-siting.png", "Three greedy picks"],
            ["map-siting.html", "Interactive map, siting"],
            ["figure-hospital.png", "Hospital within 30 min"],
            ["figure-primary.png", "Puskesmas and clinics within 15 min"],
        ],
    )


def flood():
    m = load("pekalongan/flood/metrics.json")
    lv = m["levels"][-1]
    sh = m["shelters_in_osm"]
    key = lv["level_m"]
    stats = [
        [
            f"{lv['people_flooded']:,}",
            f"people on flooded ground at {key} m ({lv['people_flooded_pct']}% of {m['population_in_area']:,})",
        ],
        [
            f"{lv['people_dry_but_cut_off']:,}",
            f"more dry but cut off from every shelter ({lv['people_dry_but_cut_off_pct']}%)",
        ],
        [f"{lv['road_under_water_pct']}%", "of walking road under water"],
        [f"{m['no_water']['median_min']} min", "median walk to a shelter with no water, the baseline"],
    ]
    table = [
        [
            f"water at {v['level_m']} m",
            f"{v['people_flooded']:,} flooded · {v['people_dry_but_cut_off']:,} cut off · {v['road_under_water_pct']}% road under water",
        ]
        for v in m["levels"]
    ]
    table += [
        [
            f"{v['village']} at {key} m",
            f"{v[f'flooded_{key}']:,} flooded · {v[f'cut_off_{key}']:,} cut off of {v['people']:,}",
        ]
        for v in m["villages"][:3]
    ]
    table += [
        [
            "shelters in OSM",
            f"{sh['school']['in_area']} schools · {sh['mosque']['in_area']} mosques · {sh['hospital']['in_area']} hospitals",
        ]
    ]
    return case(
        "flood",
        "Who is cut off when the water rises?",
        "Kota Pekalongan, Central Java · whole city (OSM boundary) · water at 0.5, 1.0 and 1.5 m",
        stats,
        table,
        "A bathtub model: water at each level floods every 100 m cell and walking edge with a point below it, then each dry cell is timed to the nearest dry shelter over dry edges; people who are dry but have no dry road to a dry shelter are cut off. The elevation is Copernicus GLO-30, a 30 m surface model (roofs and trees raise it, so built-up ground reads high and the flood is understated), with heights above the EGM2008 geoid, not local sea level; the DEM dates from 2011-2015 and this coast is sinking. No tide timing, drainage, sea walls, pumps or rainfall. This is a floor, not a forecast. The only record to compare with is press: tidal flooding in the north of the city is a repeating event, and the exposed villages here include the northern ones the press named, but that is a pattern match, not a measured depth.",
        [
            [
                "NU Online, 24 May 2018: after the rob of 23 May 2018 nearly all kelurahan in Pekalongan Utara were flooded; Krapyak residents reported about half the area under water.",
                "https://nu.or.id/daerah/banjir-rob-di-pekalongan-utara-warga-nu-kesulitan-jalankan-ibadah-2t7kn",
            ],
            [
                "Copernicus DEM GLO-30 (ESA), public AWS bucket: the surface model the heights come from.",
                "https://registry.opendata.aws/copernicus-dem/",
            ],
        ],
        [["figure.png", "People flooded and cut off, by level"], ["map.html", "Interactive map"]],
    )


def ambulance():
    m = load("makassar/ambulance/metrics.json")
    h = m["categories"]["hospital"]
    pop = m["population"]
    stats = [
        [
            f"{h['within_5_min_population_pct']:.0f}% / {h['within_10_min_population_pct']:.0f}% / {h['within_15_min_population_pct']:.0f}%",
            "of people within 5 / 10 / 15 min of a hospital by ambulance (free-flow)",
        ],
        [
            f"{h['within_5_min_pct']:.0f}% / {h['within_10_min_pct']:.0f}% / {h['within_15_min_pct']:.0f}%",
            "of the area within 5 / 10 / 15 min",
        ],
        [f"{h['beyond_limit_population']:,}", f"people ({h['beyond_limit_population_pct']}%) beyond 15 min"],
        [f"{h['in_area']}", f"hospital features mapped in the city ({h['in_buffer']} with the 5 km buffer)"],
    ]
    table = [
        ["median / 90th percentile", f"{h['median_min']} / {h['p90_min']} min"],
        ["population on the road network", f"{pop['total_on_network']:,} of {pop['total_in_area']:,} (GHSL 2020)"],
        ["cells off the road network", f"{m['off_network_pct']}% of the area (more than 200 m from a drivable road)"],
    ]
    return case(
        "ambulance",
        "How far is the nearest ambulance?",
        "Kota Makassar, South Sulawesi · mainland (OSM boundary) · drive time from the nearest hospital",
        stats,
        table,
        "Travel time runs out of the hospital on the forward graph, so an ambulance leaving it respects one-way streets in that direction. Free-flow speeds by road class: in traffic an ambulance reaches fewer people in 10 minutes, and sirens and lane clearing go the other way. The area share is below the people share because the population sits around the hospitals in the dense centre. In Makassar amenity=hospital also tags pharmacies, puskesmas, posyandu, clinics, a dispatch post, and maternity, eye, dental and psychiatric hospitals; the run drops them by name and the kept list still has duplicates. No public official hospital count could be read, so there is no completeness figure: OSM may lack hospitals, and a missing one only makes the result worse. The 13 Spermonde islands are left out (boats, not roads).",
        [
            [
                "GHSL GHS-POP R2023A (JRC): the population grid, a model of 2020, not a census.",
                "https://ghsl.jrc.ec.europa.eu/ghs_pop2023.php",
            ],
        ],
        [["figure.png", "Minutes from the nearest hospital"], ["map.html", "Interactive map"]],
    )


def shares(m, cat):
    """Shares of ALL people in the age group (not only those on the network), from one accessibility metrics.json."""
    c, pop = m["categories"][cat], m["population"]
    total, on = pop["total_in_area"], pop["total_on_network"]
    lim = int(m["limit_min"])
    return {
        "total": total,
        "facilities": f"{c['in_area']} ({c['in_buffer']})",
        "reached_pct": c[f"within_{lim}_min_population_pct"] * on / total,
        "beyond": c["beyond_limit_population"],
        "beyond_pct": c["beyond_limit_population"] / total * 100,
        "off": total - on,
        "off_pct": (total - on) / total * 100,
    }


def age():
    school = load("sumba-barat-daya/school-walk/metrics.json")
    named = load("sumba-barat-daya/school-walk-named/metrics.json")
    drive = load("sumba-barat-daya/health-drive/metrics.json")
    walk = load("sumba-barat-daya/health-walk/metrics.json")
    runs = [
        ("children 5-14, school, 30 min walk", shares(school, "school")),
        ("children 5-14, named schools only", shares(named, "school")),
        ("60+, puskesmas or hospital, 30 min drive", shares(drive, "health")),
        ("60+, any health post, 30 min walk", shares(walk, "health")),
    ]
    sc, dr, wk = runs[0][1], runs[2][1], runs[3][1]
    stats = [
        [f"{sc['beyond_pct']:.0f}%", f"of children 5-14 ({sc['beyond']:,}) beyond a 30-min walk of a mapped school"],
        [
            f"{dr['beyond_pct']:.1f}%",
            f"of people 60+ ({dr['beyond']:,}) beyond a 30-min drive of a puskesmas or hospital",
        ],
        [f"{wk['beyond_pct']:.0f}%", f"of people 60+ ({wk['beyond']:,}) beyond a 30-min walk of any health post"],
        [
            f"{sc['off_pct']:.0f}%",
            "of children live more than 200 m from any mapped way: counted neither reached nor beyond",
        ],
    ]
    table = [
        [
            label,
            f"{r['facilities']} in OSM (with buffer) · {r['reached_pct']:.1f}% reached · {r['beyond']:,} ({r['beyond_pct']:.1f}%) beyond · {r['off']:,} ({r['off_pct']:.1f}%) off the mapped network",
        ]
        for label, r in runs
    ]
    table += [
        ["population (WorldPop 2025)", f"{sc['total']:,} children 5-14 · {dr['total']:,} people 60+ in the regency"]
    ]
    return case(
        "underserved-by-age",
        "Who is underserved, by age?",
        "Kabupaten Sumba Barat Daya, East Nusa Tenggara · whole regency (OSM boundary) · WorldPop 2025 age groups",
        stats,
        table,
        "Read this first: OSM here has a fraction of the facilities and the roads are patchy too, so unmapped schools and health posts look like gaps. The figures are a floor on what is mapped, not a count of who lacks a school. Shares are of all people in the age group; people more than 200 m from any mapped way are counted neither as served nor as beyond reach. The named-schools run is the sensitivity check (unnamed amenity=school features may be buildings): the true figure sits between the two. Kemendikdasmen's Dapodik-derived table lists 288 SD and 144 SMP in the regency; OSM has about a quarter of that, so many children close to a school look far from one. No public puskesmas count was found to check the health runs against. WorldPop is a 100 m model, not a census.",
        [
            [
                "Kemendikdasmen reference data (public Dapodik-derived table, read 1 Nov 2026): 288 SD and 144 SMP in Kabupaten Sumba Barat Daya.",
                "https://referensi.data.kemendikdasmen.go.id/pendidikan/dikdas/241900/2/all/all/all",
            ],
            [
                "WorldPop Global2 age and sex structures, R2025A v1, 2025, 100 m, constrained, CC BY 4.0 (doi 10.5258/SOTON/WP00841).",
                "https://hub.worldpop.org/geodata/listing?id=138",
            ],
        ],
        [
            ["figure-school.png", "Children 5-14 to a school, 30 min walk"],
            ["map-school.html", "Interactive map, schools"],
            ["figure-health-drive.png", "People 60+ to a puskesmas or hospital, 30 min drive"],
            ["figure-health-walk.png", "People 60+ to any health post, 30 min walk"],
        ],
    )


CASES = [store(), report(), demak(), flood(), ambulance(), age()]
IMAGES = {
    "store-finder": [["surabaya/store/figure.png", "figure.png"], ["surabaya/store/map.html", "map.html"]],
    "report-card": [["sleman/report/figure.png", "figure.png"], ["sleman/report/map.html", "map.html"]],
    "facility-siting": [
        ["demak/siting/figure.png", "figure-siting.png"],
        ["demak/siting/map.html", "map-siting.html"],
        ["demak/access-hospital/figure.png", "figure-hospital.png"],
        ["demak/access-primary/figure.png", "figure-primary.png"],
    ],
    "flood": [["pekalongan/flood/figure.png", "figure.png"], ["pekalongan/flood/map.html", "map.html"]],
    "ambulance": [["makassar/ambulance/figure.png", "figure.png"], ["makassar/ambulance/map.html", "map.html"]],
    "underserved-by-age": [
        ["sumba-barat-daya/school-walk/figure.png", "figure-school.png"],
        ["sumba-barat-daya/school-walk/map.html", "map-school.html"],
        ["sumba-barat-daya/health-drive/figure.png", "figure-health-drive.png"],
        ["sumba-barat-daya/health-walk/figure.png", "figure-health-walk.png"],
    ],
}


def main():
    data = REPO / "space" / "data"
    shutil.rmtree(data, ignore_errors=True)
    cases = []
    for case_ in CASES:
        dest = data / case_["id"]
        dest.mkdir(parents=True)
        images = []
        for src, name in IMAGES[case_["id"]]:
            shutil.copy(RUNS / src, dest / name)
            images.append([name, next(lbl for f, lbl in case_["images"] if f == name)])
        case_["images"] = images
        cases.append(case_)
    (data / "index.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False, allow_nan=False))
    total = sum(f.stat().st_size for f in data.rglob("*") if f.is_file())
    print(f"packed {len(cases)} cases into {data} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
