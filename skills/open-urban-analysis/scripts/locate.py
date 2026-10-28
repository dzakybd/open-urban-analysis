# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Turn an address, a latitude and longitude, or a bbox into an AOI file (a disc of --radius-m around the point).

    uv run locate.py "Menteng, Jakarta Pusat" --radius-m 1500 --out work/aoi.json
    uv run locate.py --lat -6.1957 --lng 106.8230 --radius-m 1500 --name Menteng --out work/aoi.json
    uv run locate.py --bbox 106.80,-6.21,106.84,-6.18 --out work/aoi.json

Geocoding uses OpenStreetMap Nominatim (no key). Its policy allows at most one request per second, so geocode
once and reuse aoi.json. Compare places on discs of the same radius so the areas are equal.
"""

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "open-urban-analysis/0.1 (https://github.com/dzakybd/open-urban-analysis)"


def bbox_of(lat, lng, radius_m):
    dlat = radius_m / 111320
    dlng = radius_m / (111320 * math.cos(math.radians(lat)))
    return [lng - dlng, lat - dlat, lng + dlng, lat + dlat]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help="address or place name")
    ap.add_argument("--lat", type=float, help="latitude in degrees, with --lng, instead of a query")
    ap.add_argument("--lng", type=float)
    ap.add_argument("--bbox", help="west,south,east,north in degrees, instead of a query")
    ap.add_argument("--radius-m", type=float, default=1500, help="radius of the disc around the point")
    ap.add_argument("--name", help="label for the place")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.bbox:
        w, s, e, n = (float(v) for v in args.bbox.split(","))
        aoi = {"name": args.name or args.query or "bbox", "lat": (s + n) / 2, "lng": (w + e) / 2, "bbox": [w, s, e, n]}
    elif args.lat is not None and args.lng is not None:
        aoi = {"name": args.name or f"{args.lat},{args.lng}", "lat": args.lat, "lng": args.lng}
    elif args.query:
        q = urllib.parse.urlencode({"q": args.query, "format": "jsonv2", "limit": 1})
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{q}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            hits = json.load(r)
        if not hits:
            sys.exit(f"no geocoding result for {args.query!r}; try a simpler place name or give --lat/--lng")
        aoi = {"name": args.name or hits[0]["display_name"], "lat": float(hits[0]["lat"]), "lng": float(hits[0]["lon"]),
               "source": "OpenStreetMap Nominatim"}  # fmt: skip
    else:
        sys.exit("give an address, --lat/--lng or --bbox")

    if "bbox" not in aoi:
        aoi["radius_m"] = args.radius_m
        aoi["bbox"] = bbox_of(aoi["lat"], aoi["lng"], args.radius_m)
    aoi["bbox"] = [round(v, 6) for v in aoi["bbox"]]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(aoi, indent=2, ensure_ascii=False))
    r = f"radius {aoi['radius_m']:.0f} m" if "radius_m" in aoi else "bbox"
    print(f"{aoi['name']}\nlat {aoi['lat']:.5f}, lng {aoi['lng']:.5f}  {r}  -> {args.out}")


if __name__ == "__main__":
    main()
