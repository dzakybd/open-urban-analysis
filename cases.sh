#!/usr/bin/env bash
# Re-run every showcase case. Each step is skipped when its metrics.json exists (delete it to redo).
# Overpass is a shared service: the first run of a case downloads for a few minutes, later runs read the cache.
set -euo pipefail
# Data: a dated Geofabrik extract read through osmium, not the live Overpass API (shared, often at capacity, and it
# changes daily). `pbf <region>` points OUA_PBF at one region's extract, downloaded once (one at a time: they are large).
# Snapshots used for the published runs: java-latest.osm.pbf of 27 Oct 2026, 23:46 UTC; sulawesi-latest and
# nusa-tenggara-latest of 30 Oct 2026, 21:24 UTC (replication timestamp, written into each metrics.json `sources`).
pbf() {
  export OUA_PBF=$HOME/.cache/open-urban-analysis/pbf/$1-latest.osm.pbf
  export OUA_PBF_URL=https://download.geofabrik.de/asia/indonesia/$1-latest.osm.pbf
  [ -f "$OUA_PBF" ] || { mkdir -p "$(dirname "$OUA_PBF")"; curl -L -o "$OUA_PBF" "$OUA_PBF_URL"; }
}
S=skills/open-urban-analysis/scripts
run() { local out=$1; shift; [ -f "$out/metrics.json" ] || { echo "== $out"; uv run python "$@" --out "$out"; }; }
loc() { [ -f "$1/aoi.json" ] || uv run python $S/locate.py "${@:2}" --out "$1/aoi.json"; }
# An admin relation cut from the extract as a one-feature GeoJSON (osmium also exports member islets; jq drops them).
boundary() { local B=$1/boundary.geojson; [ -f "$B" ] || { mkdir -p "$1"; osmium getid -r -O -o "$1/b.osm.pbf" "$OUA_PBF" "$2"
  osmium export -O -f geojson --geometry-types=polygon "$1/b.osm.pbf" | jq -c '.features |= map(select(.properties.boundary=="administrative"))' > "$B"
  rm "$1/b.osm.pbf"; }; }

# Cases 1-4 read the Java extract (5 and 6 switch OUA_PBF to other islands below).
pbf java

# 1. Store finder: central Surabaya (Tegalsari, Genteng, Gubeng), 2 km disc. Where would a new minimarket reach the most
#    people per mapped competitor within a 10-minute walk? No public register of minimarkets exists, and OSM maps
#    only a fraction of them: a site with no mapped competitor is a place to survey, not free ground.
loc runs/surabaya --lat -7.27 --lng 112.745 --radius-m 2000 --name "Central Surabaya (Tegalsari, Genteng, Gubeng)"
run runs/surabaya/store $S/store.py runs/surabaya/aoi.json --shop convenience --minutes 10 --k 5 --title "Central Surabaya: where would a new minimarket reach the most people per competitor?"

# 2. House report card: Perumnas Minomartani, Sleman (Yogyakarta), commuting to UGM. One row per category, never a score.
loc runs/sleman --lat -7.7474 --lng 110.4044 --radius-m 4000 --name "Perumnas Minomartani, Ngaglik, Sleman"
run runs/sleman/report $S/report.py runs/sleman/aoi.json --work "UGM campus|-7.7705,110.3778" --exclude-name "puskesmas|klinik|gigi|bersalin|pijat|bekam" --title "Perumnas Minomartani, Sleman: house report card"

# 3. Facility siting for a regency: Kabupaten Demak, Central Java. The whole regency (OSM admin relation 17241173,
#    exported from the same extract), not a disc: a disc wide enough for Mranggen and Wedung takes in east Semarang city,
#    and the official facility and population counts are per regency. Facilities up to 5 km outside the border count.
boundary runs/demak r17241173
loc runs/demak --boundary runs/demak/boundary.geojson --name "Kabupaten Demak, Jawa Tengah"
# amenity=hospital also holds four of the six OSM puskesmas, a clinic, a dental hospital, a maternity home and a massage
# (bekam) parlour in and around Demak; they are dropped from the hospital run by name
run runs/demak/access-hospital $S/accessibility.py runs/demak/aoi.json --mode drive --categories hospital --minutes 30 --buffer-m 5000 --population --exclude-name "puskesmas|klinik|gigi|bersalin|pijat|bekam" --title "Kabupaten Demak: who is beyond a 30-minute drive to a hospital?"
run runs/demak/access-primary $S/accessibility.py runs/demak/aoi.json --mode drive --categories puskesmas,clinic --minutes 15 --buffer-m 5000 --population --title "Kabupaten Demak: who is beyond a 15-minute drive to primary care?"
run runs/demak/coverage $S/poi_coverage.py runs/demak/aoi.json --categories hospital,puskesmas,clinic --title "Kabupaten Demak: health facilities in OSM"
run runs/demak/siting $S/siting.py runs/demak/aoi.json --poi puskesmas --mode drive --threshold-min 15 --k 3 --buffer-m 5000 --population --title "Kabupaten Demak: where would 3 new puskesmas reach the most people?"

# 4. Flood and evacuation: Kota Pekalongan, Central Java (OSM relation 9686826), a subsiding north-coast city. Water
#    at 0.5, 1.0 and 1.5 m above the EGM2008 geoid on the Copernicus GLO-30 surface model (DeltaDTM, the terrain model
#    made for coasts, is hosted on data.4tu.nl; pass a tile with --dem when it is reachable). Bathtub model.
boundary runs/pekalongan r9686826
loc runs/pekalongan --boundary runs/pekalongan/boundary.geojson --name "Kota Pekalongan, Jawa Tengah"
run runs/pekalongan/flood $S/flood.py runs/pekalongan/aoi.json --levels 0.5,1.0,1.5 --shelters school,mosque,hospital --title "Kota Pekalongan: who loses a dry route to a shelter as the water rises?"

# 5. Ambulance coverage: Kota Makassar, South Sulawesi (OSM relation 11243159, mainland only: no road reaches its 13
#    islands in the Spermonde archipelago, which are served by boat and island puskesmas). Travel time FROM the
#    nearest hospital (--from-poi, forward graph), free-flow: in traffic an ambulance reaches less. Hospitals up to 5 km
#    outside the city count. amenity=hospital also holds pharmacies, puskesmas, posyandu, clinics, the PSC 119 dispatch
#    post, maternity homes and mother-and-child, eye, dental and psychiatric (Dadi) hospitals, and 9 unnamed features;
#    they are dropped by name, keeping general hospitals and the ones mappers also tag healthcare=hospital.
pbf sulawesi
boundary runs/makassar r11243159
loc runs/makassar --boundary runs/makassar/boundary.geojson --mainland --name "Kota Makassar (mainland), Sulawesi Selatan"
run runs/makassar/ambulance $S/accessibility.py runs/makassar/aoi.json --mode drive --from-poi --categories hospital --minutes 15 --buffer-m 5000 --population --exclude-name "^$|apote?k|apotik|puskesmas|posyandu|klinik|panti|safety|bersalin|\brsb\b|ibu ?(&|dan) ?anak|\brsia\b|gigi|\bmata\b|dadi" --title "Kota Makassar: who can an ambulance reach in 10 or 15 min?"

# 6. Underserved by age: Kabupaten Sumba Barat Daya, East Nusa Tenggara (OSM relation 11225333). WorldPop 2025 age
#    groups: children 5-14 to the nearest primary or junior school (SMA, SMU, SMK, MA, TK, PAUD dropped by name), people
#    60+ to the nearest puskesmas or hospital (drive) and to any mapped health post (walk; posyandu dropped). OSM has a
#    fraction of the official schools (Dapodik: 432 SD and SMP); no public puskesmas count was found. Unmapped ones look like gaps.
#    Over a third of the people live more than 200 m from any mapped road: they count as neither reached nor beyond.
pbf nusa-tenggara
boundary runs/sumba-barat-daya r11225333
loc runs/sumba-barat-daya --boundary runs/sumba-barat-daya/boundary.geojson --name "Kabupaten Sumba Barat Daya, NTT"
run runs/sumba-barat-daya/school-walk $S/accessibility.py runs/sumba-barat-daya/aoi.json --mode walk --categories school --minutes 30 --buffer-m 5000 --population worldpop --age 5-14 --exclude-name "\bsma|\bsmk|\bsmu|\bma\b|aliyah|perhotelan|\btk\b|paud|kanak|mess|perpustakaan|ruang kelas|asrama|pesantren|ketrampilan|keterampilan|\bskb\b|sanggar|rumah belajar|pkbm" --title "Sumba Barat Daya: children 5-14 beyond a 30-minute walk to a mapped school"
# sensitivity: the same run keeping only named schools (the unnamed amenity=school features may be buildings or SMA)
run runs/sumba-barat-daya/school-walk-named $S/accessibility.py runs/sumba-barat-daya/aoi.json --mode walk --categories school --minutes 30 --buffer-m 5000 --population worldpop --age 5-14 --exclude-name "^$|\bsma|\bsmk|\bsmu|\bma\b|aliyah|perhotelan|\btk\b|paud|kanak|mess|perpustakaan|ruang kelas|asrama|pesantren|ketrampilan|keterampilan|\bskb\b|sanggar|rumah belajar|pkbm" --title "Sumba Barat Daya: children 5-14 beyond a 30-minute walk to a named school"
run runs/sumba-barat-daya/health-drive $S/accessibility.py runs/sumba-barat-daya/aoi.json --mode drive --categories health --minutes 30 --buffer-m 5000 --population worldpop --age 60+ --exclude-name "^$|posyandu|pustu|pembantu|polindes|poskesdes|puskesdes|jabatan" --title "Sumba Barat Daya: age 60+ beyond a 30-min drive to a puskesmas or hospital"
run runs/sumba-barat-daya/health-walk $S/accessibility.py runs/sumba-barat-daya/aoi.json --mode walk --categories health --minutes 30 --buffer-m 5000 --population worldpop --age 60+ --exclude-name "posyandu|jabatan" --title "Sumba Barat Daya: age 60+ beyond a 30-min walk to any health post"
