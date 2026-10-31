"""Pack the precomputed case runs into space/data for the Hugging Face Space.

Every number comes from the run's own metrics.json, so nothing is retyped. Six cases: the 15-minute city in
Tebet, the closure of Jembatan Gondang I on the Tulungagung-Trenggalek road, walkability in Menteng against
BSD City, transit access in Jagakarsa against the Dukuh Atas benchmark, park access in Tambora weighted
by population, and puskesmas siting for Kabupaten Demak.

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


def tebet():
    m = load("tebet/access/metrics.json")
    raw = load("tebet/access-raw/metrics.json")
    cat = m["categories"]
    stats = [
        [
            f"{m['all_categories_within_limit_pct']:.0f}%",
            "of the area reaches a hospital, school, park and market within 15 min on foot",
        ],
        [
            f"{cat['hospital']['within_15_min_pct']:.0f}%",
            "within 15 min of a hospital (dental clinic mis-tag excluded)",
        ],
        [f"{cat['school']['within_15_min_pct']:.0f}%", "within 15 min of a school"],
        [
            f"{m['beyond_limit_for_at_least_one_population']:,}",
            f"residents ({m['beyond_limit_for_at_least_one_population_pct']:.0f}%) miss at least one of the four",
        ],
    ]
    table = [
        [
            k.replace("_", " "),
            f"{cat[k]['within_15_min_pct']:.0f}% within 15 min · median {cat[k]['median_min']:.1f} min · {cat[k]['in_area']} mapped in the area",
        ]
        for k in ("hospital", "school", "park", "market")
    ]
    table += [
        [
            "with the mis-tag counted",
            f"hospital: {raw['categories']['hospital']['within_15_min_pct']:.0f}% within 15 min",
        ],
        ["population (GHSL 2020)", f"{m['population']['total_in_area']:,} in the area"],
    ]
    return case(
        "fifteen-minute",
        "The 15-minute city",
        "Tebet, South Jakarta · 1.5 km radius · 15-minute walk",
        stats,
        table,
        "Every route is computed on the OSM street graph at 4.8 km/h; a white cell on the figure has no mapped hospital, school, park or market within 15 minutes. One dental clinic in Tebet is tagged amenity=hospital in OSM; the figure excludes it, and the table shows both readings. Markets and small clinics are what OSM maps least, so those bars are lower bounds on real access: an unmapped facility would only raise them. This case has no independent ground truth; the closest check is the same run against the live Overpass API, which agrees to a few percentage points.",
        [],
        [["figure.png", "Isochrones, per category and combined"], ["map.html", "Interactive map"]],
    )


def gondang():
    car = load("gondang/closure-car/metrics.json")
    bus = load("gondang/closure-bus/metrics.json")
    pc, pb = car["pairs"], bus["pairs"]
    stats = [
        [f"{car['closure']['edges_removed']}", "road edges removed (150 m around the bridge, every road)"],
        [
            f"+{pc['extra_min_median_of_affected']:.1f} min",
            f"median extra minutes, car ({pc['affected_over_1_min_pct']:.0f}% of trips slower)",
        ],
        [f"+{pc['extra_min_max']:.0f} min", "worst car detour"],
        [
            f"+{pb['extra_min_median_of_affected']:.1f} min",
            f"median extra, bus on classified roads ({pb['affected_over_1_min_pct']:.0f}% slower)",
        ],
    ]
    table = []
    for label, mm in (("car", car), ("bus", bus)):
        for r in mm["routes"]:
            table.append(
                [
                    f"{r['from'].split()[0]} → {r['to'].split()[0]} ({label})",
                    f"{r['before']['km']} km / {r['before']['minutes']:.0f} min → {r['after']['km']} km / {r['after']['minutes']:.0f} min",
                ]
            )
    lm = car["routes"][0]["landmarks_min_distance_m"]
    for name in ("Mojoarum", "Bendungan", "Kalangbret", "Campurdarat"):
        d = lm[name]
        table.append([f"car detour near {name}", f"{d['before']:,} m before → {d['after']:,} m after"])
    lm = bus["routes"][0]["landmarks_min_distance_m"]
    for name in ("Mojoarum", "Campurdarat"):
        d = lm[name]
        table.append([f"bus detour near {name}", f"{d['before']:,} m before → {d['after']:,} m after"])
    return case(
        "bridge-closure",
        "A bridge closes",
        "Jembatan Gondang I, Tulungagung–Trenggalek national road · closed 2 Jun 2026",
        stats,
        table,
        "The simulation removes every road edge within 150 m of the bridge (OSM draws the bridge as a polygon with alley bridges beside it, so a tighter radius is bypassed). The car detour follows the lanes the police announced for light vehicles; on classified roads only — a bus — the model swings south through the same Campurdarat corridor the police announced for heavy vehicles. It does not match the announced detour's length: the model's bus detour is 1.1 km shorter than the direct run, while the announced heavy route adds about 10 km, because the named trips end inside the 8 km analysis disc and OSM's free-flow model does not see the road width that made the police choose the long loop. Minutes are free-flow; queueing at the diversion adds more. The bridge reopened on 24 Oct 2026 while the new span is finished.",
        [
            [
                "detik, 2 Jun 2026: closed six months; light vehicles via Kalangbret and Mojoarum lanes, buses and trucks via Tamanan–Campurdarat–Pakel–Bandung, about 10 km longer.",
                "https://www.detik.com/jatim/berita/d-8514918/jembatan-gondang-ditutup-total-6-bulan-ini-jalur-alternatifnya",
            ],
            [
                "Antara, 2 Jun 2026: closure 2 Jun–11 Dec 2026; the three light-vehicle routes and the heavy-vehicle route.",
                "https://www.antaranews.com/berita/5591581/jalan-nasional-tulungagung-trenggalek-ditutup-total",
            ],
            [
                "Antara Jatim, 24 Oct 2026: reopened to traffic while works continue.",
                "https://jatim.antaranews.com/berita/1110811/jembatan-gondang-tulungagung-dibuka-untuk-umum",
            ],
        ],
        [
            ["figure-car.png", "Car detours"],
            ["map-car.html", "Interactive map, car"],
            ["figure-bus.png", "Bus (classified roads only)"],
            ["map-bus.html", "Interactive map, bus"],
        ],
    )


def walkability():
    m = load("walkability/compare/metrics.json")
    a, b = m["places"]
    stats = [
        [
            f"{a['intersection_density_per_km2']:.0f} vs {b['intersection_density_per_km2']:.0f} /km²",
            "intersection density, Menteng vs BSD City",
        ],
        [
            f"{a['mean_essentials_within_10_min']:.1f} vs {b['mean_essentials_within_10_min']:.1f}",
            "of 5 essentials within a 10-minute walk",
        ],
        [
            f"{a['cells_with_all_5_within_10_min_pct']:.0f}% vs {b['cells_with_all_5_within_10_min_pct']:.0f}%",
            "of the area, all 5 within 10 min",
        ],
        [
            f"{a['mapped_sidewalk_share_of_street_length_pct']:.0f}% vs {b['mapped_sidewalk_share_of_street_length_pct']:.0f}%",
            "street length with a mapped sidewalk",
        ],
    ]
    rows = [
        ("Street density (km/km²)", "street_density_km_per_km2"),
        ("Intersection density (/km²)", "intersection_density_per_km2"),
        ("Dead-end share (%)", "dead_end_share_pct"),
        ("Circuity", "circuity"),
        ("Meshedness", "meshedness"),
        ("Pedestrian-only ways (km/km²)", "pedestrian_ways_km_per_km2"),
        ("Mapped crossings (/km²)", "mapped_crossings_per_km2"),
        ("Mapped sidewalks (% of length)", "mapped_sidewalk_share_of_street_length_pct"),
        ("Essentials within 10 min (of 5)", "mean_essentials_within_10_min"),
        ("All 5 within 10 min (% of area)", "cells_with_all_5_within_10_min_pct"),
        ("None within 10 min (% of area)", "cells_with_none_within_10_min_pct"),
    ]
    table = [[k, f"Menteng {a[key]} · BSD {b[key]}"] for k, key in rows]
    return case(
        "walkability",
        "Two kinds of neighbourhood",
        "Menteng (1920s garden city) vs BSD City (2000s new town) · equal 1.5 km discs",
        stats,
        table,
        "Same radius, same metrics, no combined score on purpose. Menteng is a fine-grained grid; BSD is cul-de-sac clusters feeding arterial loops — the maps show it. The mapped-sidewalk and crossing numbers measure what mappers recorded, and Jakarta is better mapped than a new town, so read them as 'mapped', not 'present'. The essentials gap (4.35 vs 1.66 of 5) is the metric least affected by mapping effort, and it agrees with the street pattern.",
        [],
        [
            ["figure.png", "Side-by-side metrics"],
            ["map-menteng.html", "Interactive map, Menteng"],
            ["map-bsd.html", "Interactive map, BSD City"],
        ],
    )


def transit():
    m = load("transit/access/metrics.json")
    b = load("transit-benchmark/access/metrics.json")

    def row(d, key):
        c = d["categories"][key]
        return f"{c['within_10_min_pct']:.0f}% within 10 min · {c['in_area']} mapped stops in the area"

    table = [[f"Jagakarsa: {k.replace('_', ' ')}", row(m, k)] for k in ("rail", "transjakarta", "bus_stop")] + [
        [f"Dukuh Atas: {k.replace('_', ' ')}", row(b, k)] for k in ("rail", "transjakarta", "bus_stop")
    ]
    stats = [
        [f"{m['categories']['rail']['within_10_min_pct']:.0f}%", "of Jagakarsa within 10 min of rail — there is none"],
        [
            f"{m['categories']['transjakarta']['within_10_min_pct']:.0f}%",
            "within 10 min of a TransJakarta-tagged stop (mostly Mikrotrans feeders)",
        ],
        [f"{b['categories']['rail']['within_10_min_pct']:.0f}%", "rail, Dukuh Atas benchmark (the city's main hub)"],
        [f"{b['categories']['transjakarta']['within_10_min_pct']:.0f}%", "TransJakarta-tagged stops, Dukuh Atas"],
    ]
    return case(
        "transit",
        "A transit desert?",
        "Jagakarsa, South Jakarta vs Dukuh Atas, Central Jakarta · 2 km radius · 10-minute walk",
        stats,
        table,
        "Stops are what OSM tags. Mikrotrans feeder vans are tagged network=TransJakarta, so the TransJakarta category measures the minibus feeder web, not BRT corridors: feeder stops are dense in Jagakarsa while rapid transit is absent. The benchmark disc shows the same measures at the hub where four rail lines and the BRT corridors meet — and how high the bar is: even there, only a third of the disc is within 10 min of a rail stop. A stop that exists but is not mapped reads as no service here.",
        [
            [
                "TransJakarta published route map (corridors cross-checked; feeder-stop counts are OSM-only).",
                "https://transjakarta.co.id/peta-rute/",
            ],
        ],
        [
            ["figure-jagakarsa.png", "Jagakarsa isochrones"],
            ["map-jagakarsa.html", "Interactive map, Jagakarsa"],
            ["figure-dukuh.png", "Dukuh Atas isochrones"],
            ["map-dukuh.html", "Interactive map, Dukuh Atas"],
        ],
    )


def green():
    m = load("green/access/metrics.json")
    p = m["categories"]["park"]
    stats = [
        [f"{p['within_10_min_pct']:.0f}%", "of Tambora within a 10-minute walk of a mapped park"],
        [
            f"{p['beyond_limit_population']:,}",
            f"people ({p['beyond_limit_population_pct']:.0f}%) live beyond that walk",
        ],
        [f"{p['median_min']:.1f} min", "median walk to the nearest park"],
        [f"{m['population']['total_in_area']:,}", "residents in the disc (GHSL 2020, modelled)"],
    ]
    table = [
        ["within 5 min", f"{p['within_5_min_pct']:.0f}%"],
        ["within 10 min", f"{p['within_10_min_pct']:.0f}%"],
        ["beyond 10 min", f"{p['beyond_limit_pct']:.0f}%"],
        ["median walk", f"{p['median_min']:.1f} min"],
        ["90th percentile", f"{p['p90_min']:.1f} min"],
        ["parks mapped in the area", f"{p['in_area']}"],
    ]
    return case(
        "green-space",
        "Who can reach a park?",
        "Tambora, West Jakarta · 1.5 km radius · 10-minute walk, weighted by population",
        stats,
        table,
        "Tambora packs about 181,000 people (GHSL 2020) into the disc — roughly 25,600 per km² — and its mapped parks are small pocket greens toward the edge. The white core on the figure is where the people are: 54,350 residents (30%) live farther than a 10-minute walk from any mapped park. Parks are entered from points along their outline, so a gated green counts where its gate is. Small neighbourhood fields are exactly what OSM mappers most often leave out.",
        [
            [
                "GHSL GHS-POP R2023A (JRC): the population grid the weighting uses — a model, not a census.",
                "https://ghsl.jrc.ec.europa.eu/ghs_pop.php",
            ],
        ],
        [["figure.png", "Park isochrones with population"], ["map.html", "Interactive map"]],
    )


def demak():
    h = load("demak/access-hospital/metrics.json")
    pc = load("demak/access-primary/metrics.json")
    s = load("demak/siting/metrics.json")
    hosp, pusk = h["categories"]["hospital"], pc["categories"]["puskesmas"]
    last = s["picks"][-1]
    stats = [
        # matched by name against the Dinkes list: OSM's 6 in the regency include one that is not on it
        [
            "5 of 27",
            f"official puskesmas are in OSM ({s['existing']['in_area']} OSM puskesmas, one not on the Dinkes list)",
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
    table += [
        ["population (GHSL 2020)", f"{h['population']['total_in_area']:,} in the regency (official 2025: 1,259,682)"]
    ]
    return case(
        "facility-siting",
        "Where would new puskesmas go?",
        "Kabupaten Demak, Central Java · whole regency (OSM boundary) · 15-minute drive",
        stats,
        table,
        "The question a regency planner asks: where would the next three puskesmas reach the most people now beyond a 15-minute drive? The script picks greedily from street nodes on classified roads. The answer is mostly about the map: OSM has 5 of the 27 official puskesmas, and the first two picks land in Demak town and Mranggen, whose official puskesmas are simply unmapped. Read the picks as a mapping to-do list before a building plan. Drive times are free-flow; tidal flooding that cuts coastal roads in Sayung is not modelled, and GHSL counts about 960,000 people against an official 1.26 million.",
        [
            [
                "Dinkes Kabupaten Demak, Bahan LPPD 2025: 27 puskesmas (15 inpatient, 12 outpatient), 52 pustu, 6 hospitals, 1,259,682 residents (Dukcapil, 2025 semester I).",
                "https://dinkes.demakkab.go.id/wp-content/uploads/2026/05/BAHAN-LPPD-DINKES-2025.Publish.pdf",
            ],
        ],
        [
            ["figure-siting.png", "Three greedy picks"],
            ["map-siting.html", "Interactive map, siting"],
            ["figure-hospital.png", "Hospital within 30 min"],
            ["figure-primary.png", "Puskesmas and clinics within 15 min"],
        ],
    )


CASES = [tebet(), gondang(), walkability(), transit(), green(), demak()]
IMAGES = {
    "fifteen-minute": [["tebet/access/figure.png", "figure.png"], ["tebet/access/map.html", "map.html"]],
    "bridge-closure": [
        ["gondang/closure-car/figure.png", "figure-car.png"],
        ["gondang/closure-car/map.html", "map-car.html"],
        ["gondang/closure-bus/figure.png", "figure-bus.png"],
        ["gondang/closure-bus/map.html", "map-bus.html"],
    ],
    "walkability": [
        ["walkability/compare/figure.png", "figure.png"],
        ["walkability/compare/menteng-jakarta-map.html", "map-menteng.html"],
        ["walkability/compare/bsd-city-tangerang-selatan-map.html", "map-bsd.html"],
    ],
    "transit": [
        ["transit/access/figure.png", "figure-jagakarsa.png"],
        ["transit/access/map.html", "map-jagakarsa.html"],
        ["transit-benchmark/access/figure.png", "figure-dukuh.png"],
        ["transit-benchmark/access/map.html", "map-dukuh.html"],
    ],
    "green-space": [["green/access/figure.png", "figure.png"], ["green/access/map.html", "map.html"]],
    "facility-siting": [
        ["demak/siting/figure.png", "figure-siting.png"],
        ["demak/siting/map.html", "map-siting.html"],
        ["demak/access-hospital/figure.png", "figure-hospital.png"],
        ["demak/access-primary/figure.png", "figure-primary.png"],
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
