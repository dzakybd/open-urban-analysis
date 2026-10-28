#!/usr/bin/env bash
# Re-run every showcase case. Each step is skipped when its metrics.json exists (delete it to redo).
# Overpass is a shared service: the first run of a case downloads for a few minutes, later runs read the cache.
set -euo pipefail
S=skills/open-urban-analysis/scripts
run() { local out=$1; shift; [ -f "$out/metrics.json" ] || { echo "== $out"; uv run python "$@" --out "$out"; }; }
loc() { [ -f "$1/aoi.json" ] || uv run python $S/locate.py "${@:2}" --out "$1/aoi.json"; }

# 1. 15-minute city: Tebet, South Jakarta (and its street network)
loc runs/tebet --lat -6.2345 --lng 106.8560 --radius-m 1500 --name "Tebet, Jakarta Selatan"
run runs/tebet/access $S/accessibility.py runs/tebet/aoi.json --categories hospital,school,park,market --minutes 15 --population --exclude-name dental --title "Tebet, South Jakarta: what is within a 15-minute walk?"
# sensitivity: the same run without the exclusion (one dental clinic is tagged amenity=hospital in OSM)
run runs/tebet/access-raw $S/accessibility.py runs/tebet/aoi.json --categories hospital,school,park,market --minutes 15 --population --title "Tebet, South Jakarta: all OSM-tagged hospitals counted"
run runs/tebet/network $S/network_stats.py runs/tebet/aoi.json --mode walk
run runs/tebet/coverage $S/poi_coverage.py runs/tebet/aoi.json --categories hospital,clinic,school,park,market,bus_stop,rail

# 2. Bridge closure: Jembatan Gondang I, Tulungagung-Trenggalek (closed from 2 June 2026)
loc runs/gondang --lat -8.07176 --lng 111.8466 --radius-m 8000 --name "Gondang, Tulungagung"
run runs/gondang/closure $S/closure.py runs/gondang/aoi.json --mode drive --close-near=-8.07176,111.8466,80 --bridge-only --buffer-m 8000 \
  --od "Terminal Gayatri Tulungagung|-8.07267,111.89685|Durenan Trenggalek|-8.11973,111.80384" \
  --od "Tulungagung|-8.0661,111.9009|Trenggalek|-8.0491,111.7091" --poi hospital --threshold-min 30 \
  --title "Jembatan Gondang I closed: Tulungagung to Trenggalek"

# 3. Walkability: Menteng vs BSD City, equal 1.5 km discs
loc runs/walkability/menteng --lat -6.1995 --lng 106.8330 --radius-m 1500 --name "Menteng, Jakarta"
loc runs/walkability/bsd --lat -6.2995 --lng 106.6480 --radius-m 1500 --name "BSD City, Tangerang Selatan"
run runs/walkability/compare $S/walkability.py runs/walkability/menteng/aoi.json runs/walkability/bsd/aoi.json

# 4. Transit desert: Jagakarsa, South Jakarta
loc runs/transit --lat -6.3350 --lng 106.8150 --radius-m 2000 --name "Jagakarsa, Jakarta Selatan"
run runs/transit/access $S/accessibility.py runs/transit/aoi.json --categories rail,bus_stop --minutes 10 --title "Jagakarsa, South Jakarta: walking access to rail and bus stops"

# 5. Green space with population: Tambora, North/West Jakarta
loc runs/green --lat -6.1450 --lng 106.8000 --radius-m 1500 --name "Tambora, Jakarta Barat"
run runs/green/access $S/accessibility.py runs/green/aoi.json --categories park --minutes 10 --population --title "Tambora, Jakarta: who lives within a 10-minute walk of a park?"
