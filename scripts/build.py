"""Merge seeded editorial data with geocoding + OSM hours into data/places.json,
the single file the app fetches at runtime."""

import datetime
import json
import pathlib
import sys

import osm_hours

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed.json"
OUT = ROOT / "data" / "places.json"

# Time-of-day buckets, derived from hours so the two can never drift.
BUCKETS = {"Morning": (5, 12), "Afternoon": (12, 17), "Evening": (17, 21), "Night": (21, 29)}


def to_minutes(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m


def covered_buckets(hours):
    """Which coarse time-of-day buckets this place is open for, on any day."""
    found = set()
    for ranges in hours.values():
        for start, end in ranges or []:
            s, e = to_minutes(start), to_minutes(end)
            if e <= s:                 # crosses midnight
                e += 24 * 60
            for name, (bh, eh) in BUCKETS.items():
                bs, be = bh * 60, eh * 60
                # Overlap test, also against the span shifted a day earlier so
                # a 23:00-12:00 range still registers as Morning.
                if (s < be and e > bs) or (s - 1440 < be and e - 1440 > bs):
                    found.add(name)
    order = ["Morning", "Afternoon", "Evening", "Night"]
    return [b for b in order if b in found]


def main():
    places = json.loads(SEED.read_text())
    today = datetime.date.today().isoformat()
    stats = {"osm": 0, "curated": 0, "override": 0}
    out = []

    for p in places:
        if "lat" not in p:
            print(f"SKIP (no coordinates): {p['id']}", file=sys.stderr)
            continue

        tag = p.get("osm_opening_hours")
        prefer_curated = p.get("hours_prefer") == "curated"
        if tag and not prefer_curated:
            try:
                p["hours"] = osm_hours.parse(tag)
                p["hours_source"] = f"OpenStreetMap ({tag})"
                stats["osm"] += 1
            except ValueError as exc:
                print(f"WARN unparsed OSM hours for {p['id']}: {exc}", file=sys.stderr)
                p["hours_source"] = "Curated (OSM tag unparsed)"
                stats["curated"] += 1
        elif tag and prefer_curated:
            p["hours_source"] = "Curated (OSM tag less accurate)"
            stats["override"] += 1
        else:
            p["hours_source"] = "Curated"
            stats["curated"] += 1

        p["times"] = covered_buckets(p["hours"])
        p["last_verified"] = today
        p.pop("osm_opening_hours", None)
        p.pop("hours_prefer", None)
        p.pop("query", None)
        out.append(p)

    OUT.write_text(json.dumps(out, indent=1))
    print(f"built {len(out)} places -> {OUT.relative_to(ROOT)}")
    print(f"  hours from OSM        : {stats['osm']}")
    print(f"  hours curated         : {stats['curated']}")
    print(f"  curated over OSM      : {stats['override']}")
    missing = [p["id"] for p in out if not p["times"]]
    if missing:
        print(f"  WARN no time buckets  : {missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
