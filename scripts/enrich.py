"""Enrich seed.json with real coordinates, addresses, websites and OSM-tagged
opening hours from Nominatim. Caches responses so reruns cost no API calls.

Nominatim's usage policy requires an identifying User-Agent and at most 1 req/s.
"""

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed.json"
CACHE = ROOT / "data" / ".nominatim-cache.json"
UA = ("FloridaExplorer/0.1 (+https://github.com/daniellkennett/florida-explorer; "
      "daniel.kennett@databricks.com)")
ENDPOINT = "https://nominatim.openstreetmap.org/search"

# Florida bounding box, used to reject bad geocodes (e.g. a same-named place
# in another state) rather than silently shipping a wrong pin.
FL_BOX = dict(lat=(24.4, 31.1), lng=(-87.7, -79.9))


def load_cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def geocode(query, cache):
    if query in cache:
        return cache[query]
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1,
        "addressdetails": 1, "extratags": 1, "countrycodes": "us",
    })
    req = urllib.request.Request(f"{ENDPOINT}?{params}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    cache[query] = data[0] if data else None
    time.sleep(1.1)   # policy: max 1 request/second
    return cache[query]


def format_address(raw):
    a = raw.get("address", {})
    house = a.get("house_number", "")
    road = a.get("road", "")
    street = f"{house} {road}".strip()
    city = a.get("city") or a.get("town") or a.get("village") or a.get("suburb", "")
    parts = [p for p in (street, city, a.get("state", ""), a.get("postcode", "")) if p]
    return ", ".join(parts)


def main():
    places = json.loads(SEED.read_text())
    cache = load_cache()
    failures, out_of_box, osm_hours = [], [], []

    try:
        for p in places:
            raw = geocode(p["query"], cache)
            if not raw:
                failures.append(p["id"])
                continue

            lat, lng = float(raw["lat"]), float(raw["lon"])
            if not (FL_BOX["lat"][0] <= lat <= FL_BOX["lat"][1]
                    and FL_BOX["lng"][0] <= lng <= FL_BOX["lng"][1]):
                out_of_box.append((p["id"], lat, lng))
                continue

            p["lat"], p["lng"] = round(lat, 5), round(lng, 5)
            p["address"] = format_address(raw)
            p["geo_source"] = "OpenStreetMap/Nominatim"

            extra = raw.get("extratags") or {}
            if extra.get("website"):
                p.setdefault("website", extra["website"])
            if extra.get("opening_hours"):
                p["osm_opening_hours"] = extra["opening_hours"]
                osm_hours.append(p["id"])
    finally:
        CACHE.write_text(json.dumps(cache, indent=1))

    SEED.write_text(json.dumps(places, indent=1))

    located = sum(1 for p in places if "lat" in p)
    print(f"geocoded     : {located}/{len(places)}")
    print(f"osm hours    : {len(osm_hours)}")
    if failures:
        print(f"NO MATCH ({len(failures)}): {', '.join(failures)}", file=sys.stderr)
    if out_of_box:
        print(f"OUT OF FLORIDA ({len(out_of_box)}): {out_of_box}", file=sys.stderr)


if __name__ == "__main__":
    main()
