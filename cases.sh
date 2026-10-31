#!/usr/bin/env bash
# Re-run every showcase case. Each step is skipped when its metrics.json exists (delete it to redo).
# Overpass is a shared service: the first run of a case downloads for a few minutes, later runs read the cache.
set -euo pipefail
# Data: a dated Geofabrik extract read through osmium, not the live Overpass API (shared, often at capacity, and it
# changes daily). Snapshot used for the published runs: java-latest.osm.pbf of 27 Oct 2026, 23:46 UTC.
export OUA_PBF="${OUA_PBF:-$HOME/.cache/open-urban-analysis/pbf/java-latest.osm.pbf}"
[ -f "$OUA_PBF" ] || { mkdir -p "$(dirname "$OUA_PBF")"; curl -L -o "$OUA_PBF" https://download.geofabrik.de/asia/indonesia/java-latest.osm.pbf; }
S=skills/open-urban-analysis/scripts
run() { local out=$1; shift; [ -f "$out/metrics.json" ] || { echo "== $out"; uv run python "$@" --out "$out"; }; }
loc() { [ -f "$1/aoi.json" ] || uv run python $S/locate.py "${@:2}" --out "$1/aoi.json"; }

# 1. 15-minute city: Tebet, South Jakarta (and its street network)
# runs/tebet/access-overpass-check was made once with the live Overpass API (OUA_PBF unset) as a cross-check of the offline backend
loc runs/tebet --lat -6.2345 --lng 106.8560 --radius-m 1500 --name "Tebet, Jakarta Selatan"
run runs/tebet/access $S/accessibility.py runs/tebet/aoi.json --categories hospital,school,park,market --minutes 15 --population --exclude-name dental --title "Tebet, South Jakarta: what is within a 15-minute walk?"
# sensitivity: the same run without the exclusion (one dental clinic is tagged amenity=hospital in OSM)
run runs/tebet/access-raw $S/accessibility.py runs/tebet/aoi.json --categories hospital,school,park,market --minutes 15 --population --title "Tebet, South Jakarta: all OSM-tagged hospitals counted"
run runs/tebet/network $S/network_stats.py runs/tebet/aoi.json --mode walk
run runs/tebet/coverage $S/poi_coverage.py runs/tebet/aoi.json --categories hospital,clinic,school,park,market,bus_stop,rail

# 2. Bridge closure: Jembatan Gondang I, Tulungagung-Trenggalek (closed from 2 June 2026). OSM maps the bridge as a small
#    man_made=bridge polygon (way 1519056049) on the trunk road ref 21 with small alley bridges beside it, so every edge
#    within 150 m of the bridge is removed (closing only the trunk road within 30 m is bypassed through those alleys).
loc runs/gondang --lat -8.07176 --lng 111.8466 --radius-m 8000 --name "Gondang, Tulungagung"
COMMON_G="--mode drive --close-near=-8.0717,111.84665,150 --buffer-m 8000 --poi hospital --threshold-min 30"
LM_G=(--landmark "Mojoarum|-8.0686,111.8441" --landmark "Bendungan|-8.0724,111.8443" --landmark "Kalangbret|-8.0548,111.8657"
  --landmark "Tamanan|-8.0706,111.9038" --landmark "Campurdarat|-8.1654,111.8529" --landmark "Pakel|-8.1546,111.8261")
OD_G=(--od "Terminal Gayatri Tulungagung|-8.07267,111.89685|Durenan Trenggalek|-8.11973,111.80384"
  --od "Tulungagung|-8.0661,111.9009|Trenggalek|-8.0491,111.7091")
# every road in OSM (a car)
run runs/gondang/closure-car $S/closure.py runs/gondang/aoi.json $COMMON_G "${OD_G[@]}" "${LM_G[@]}" --title "Jembatan Gondang I closed: a car, every OSM road"
# classified roads only (a bus or truck, which the police sent on a long loop)
run runs/gondang/closure-bus $S/closure.py runs/gondang/aoi.json $COMMON_G "${OD_G[@]}" "${LM_G[@]}" --classes trunk,primary,secondary,tertiary --title "Jembatan Gondang I closed: a bus, classified roads only"

# 3. Walkability: Menteng vs BSD City, equal 1.5 km discs
loc runs/walkability/menteng --lat -6.1995 --lng 106.8330 --radius-m 1500 --name "Menteng, Jakarta"
loc runs/walkability/bsd --lat -6.3025 --lng 106.6560 --radius-m 1500 --name "BSD City, Tangerang Selatan"
run runs/walkability/compare $S/walkability.py runs/walkability/menteng/aoi.json runs/walkability/bsd/aoi.json

# 4. Transit desert: Jagakarsa, South Jakarta, against a central benchmark (Dukuh Atas)
loc runs/transit --lat -6.3350 --lng 106.8150 --radius-m 2000 --name "Jagakarsa, Jakarta Selatan"
run runs/transit/access $S/accessibility.py runs/transit/aoi.json --categories rail,transjakarta,bus_stop --minutes 10 --title "Jagakarsa, South Jakarta: walking access to rail and bus stops"
loc runs/transit-benchmark --lat -6.2010 --lng 106.8230 --radius-m 2000 --name "Dukuh Atas, Jakarta Pusat"
run runs/transit-benchmark/access $S/accessibility.py runs/transit-benchmark/aoi.json --categories rail,transjakarta,bus_stop --minutes 10 --title "Dukuh Atas, Central Jakarta: walking access to rail and bus stops"

# 5. Green space with population: Tambora, North/West Jakarta
loc runs/green --lat -6.1450 --lng 106.8000 --radius-m 1500 --name "Tambora, Jakarta Barat"
run runs/green/access $S/accessibility.py runs/green/aoi.json --categories park --minutes 10 --population --title "Tambora, Jakarta: who lives within a 10-minute walk of a park?"

# 6. Facility siting for a regency: Kabupaten Demak, Central Java. The whole regency (OSM admin relation 17241173,
#    exported from the same extract), not a disc: a disc wide enough for Mranggen and Wedung takes in east Semarang city,
#    and the official facility and population counts are per regency. Facilities up to 5 km outside the border count.
B=runs/demak/boundary.geojson
[ -f $B ] || { mkdir -p runs/demak; osmium getid -r -O -o runs/demak/boundary.osm.pbf "$OUA_PBF" r17241173
  osmium export -O --geometry-types=polygon -o $B runs/demak/boundary.osm.pbf; rm runs/demak/boundary.osm.pbf; }
loc runs/demak --boundary $B --name "Kabupaten Demak, Jawa Tengah"
# amenity=hospital also holds four of the six OSM puskesmas, a clinic, a dental hospital, a maternity home and a massage
# (bekam) parlour in and around Demak; they are dropped from the hospital run by name
run runs/demak/access-hospital $S/accessibility.py runs/demak/aoi.json --mode drive --categories hospital --minutes 30 --buffer-m 5000 --population --exclude-name "puskesmas|klinik|gigi|bersalin|pijat|bekam" --title "Kabupaten Demak: who is beyond a 30-minute drive to a hospital?"
run runs/demak/access-primary $S/accessibility.py runs/demak/aoi.json --mode drive --categories puskesmas,clinic --minutes 15 --buffer-m 5000 --population --title "Kabupaten Demak: who is beyond a 15-minute drive to primary care?"
run runs/demak/coverage $S/poi_coverage.py runs/demak/aoi.json --categories hospital,puskesmas,clinic --title "Kabupaten Demak: health facilities in OSM"
run runs/demak/siting $S/siting.py runs/demak/aoi.json --poi puskesmas --mode drive --threshold-min 15 --k 3 --buffer-m 5000 --population --title "Kabupaten Demak: where would 3 new puskesmas reach the most people?"
