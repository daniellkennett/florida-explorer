"""Integrity checks over data/places.json. Exits non-zero on any failure so it
can gate a commit or a CI step."""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACES = ROOT / "data" / "places.json"
CREDITS = ROOT / "CREDITS.md"

FL_LAT = (24.4, 31.1)
FL_LNG = (-87.7, -79.9)
CITIES = {"Miami", "Orlando", "Fort Lauderdale"}
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
BUCKETS = {"Morning", "Afternoon", "Evening", "Night"}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-4]):[0-5]\d$")

REQUIRED = ("id", "city", "title", "description", "category", "tags", "price",
            "lat", "lng", "address", "hours", "times", "last_verified")


def main():
    places = json.loads(PLACES.read_text())
    errors, warnings = [], []
    seen_ids, seen_titles = set(), set()

    for p in places:
        pid = p.get("id", "<missing id>")

        for field in REQUIRED:
            if field not in p or p[field] in (None, "", [], {}):
                errors.append(f"{pid}: missing required field {field!r}")

        if pid in seen_ids:
            errors.append(f"{pid}: duplicate id")
        seen_ids.add(pid)

        key = (p.get("city"), p.get("title"))
        if key in seen_titles:
            errors.append(f"{pid}: duplicate title within {p.get('city')}")
        seen_titles.add(key)

        if p.get("city") not in CITIES:
            errors.append(f"{pid}: unexpected city {p.get('city')!r}")

        lat, lng = p.get("lat"), p.get("lng")
        if isinstance(lat, (int, float)) and not FL_LAT[0] <= lat <= FL_LAT[1]:
            errors.append(f"{pid}: latitude {lat} outside Florida")
        if isinstance(lng, (int, float)) and not FL_LNG[0] <= lng <= FL_LNG[1]:
            errors.append(f"{pid}: longitude {lng} outside Florida")

        price = p.get("price") or {}
        if "free" not in price or "level" not in price:
            errors.append(f"{pid}: price must carry 'free' and 'level'")
        elif price["free"] != (price["level"] == 0):
            errors.append(f"{pid}: price.free={price['free']} contradicts level={price['level']}")
        # The old schema duplicated free-ness in tags; keep the two consistent.
        if price.get("free") and "free" not in (p.get("tags") or []):
            warnings.append(f"{pid}: free place without a 'free' tag")
        if not price.get("free") and "free" in (p.get("tags") or []):
            errors.append(f"{pid}: tagged 'free' but price.level={price.get('level')}")

        hours = p.get("hours") or {}
        if set(hours) != DAYS:
            errors.append(f"{pid}: hours keys {sorted(set(hours) ^ DAYS)} wrong")
        open_any = False
        for day, ranges in hours.items():
            if ranges is None:
                continue
            if not isinstance(ranges, list):
                errors.append(f"{pid}: hours.{day} must be a list or null")
                continue
            for r in ranges:
                if not (isinstance(r, list) and len(r) == 2):
                    errors.append(f"{pid}: hours.{day} entry {r!r} is not a pair")
                    continue
                for t in r:
                    if not TIME_RE.match(str(t)):
                        errors.append(f"{pid}: hours.{day} bad time {t!r}")
                open_any = True
        if not open_any:
            errors.append(f"{pid}: never open on any day")

        times = p.get("times") or []
        if not times:
            errors.append(f"{pid}: no derived time buckets")
        if set(times) - BUCKETS:
            errors.append(f"{pid}: unknown buckets {set(times) - BUCKETS}")

        img = p.get("image") or {}
        if not img.get("file"):
            errors.append(f"{pid}: no image.file")
        else:
            if not (ROOT / img["file"]).exists():
                errors.append(f"{pid}: image file missing on disk: {img['file']}")
            if not img.get("representative") and not img.get("licence"):
                errors.append(f"{pid}: real photo without a licence recorded")
            if not img.get("alt"):
                warnings.append(f"{pid}: image has no alt text")

    # Every committed image must be attributed.
    credits_text = CREDITS.read_text() if CREDITS.exists() else ""
    for img_path in sorted((ROOT / "images").glob("*")):
        if img_path.name.startswith("."):
            continue
        if img_path.name not in credits_text:
            errors.append(f"images/{img_path.name}: not listed in CREDITS.md")

    print(f"checked {len(places)} places, {len(list((ROOT / 'images').glob('*')))} images")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
