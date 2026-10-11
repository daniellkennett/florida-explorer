"""Find venue photographs via Wikidata instead of Commons text search.

Commons full-text search cannot verify identity: searching "Coconuts" returns
coconuts, "El Camino" returns a Brussels bar, "Old Town Kissimmee" returns
Corfu. Wikidata entities carry coordinates (P625) and a curated depicting
image (P18), so a candidate can be confirmed to be the *physical place we
geocoded* before its photo is trusted.

Acceptance requires the entity's coordinates to be within MAX_MILES of the
Nominatim fix for that place. That single check eliminates every wrong-city and
wrong-country match.
"""

import json
import math
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import fetch_images as fi

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACES = ROOT / "data" / "places.json"
CACHE = ROOT / "data" / ".wikidata-cache.json"
IMG_DIR = ROOT / "images"

WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = ("FloridaExplorer/0.1 (+https://github.com/daniellkennett/florida-explorer; "
      "daniel.kennett@databricks.com)")

# A venue and its Wikidata point can differ by a few hundred metres; a park
# centroid rather more. Two miles is generous enough for large parks while
# still rejecting another city entirely.
MAX_MILES = 2.0


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return {}


def miles(lat1, lng1, lat2, lng2):
    r = math.pi / 180
    d_lat = (lat2 - lat1) * r
    d_lng = (lng2 - lng1) * r
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(d_lng / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def search_entities(term, limit=8):
    q = urllib.parse.urlencode({
        "action": "wbsearchentities", "search": term, "language": "en",
        "format": "json", "limit": limit, "type": "item",
    })
    data = fetch(f"{WD_API}?{q}")
    return [r["id"] for r in data.get("search", [])]


def entity_claims(ids):
    if not ids:
        return {}
    q = urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(ids[:25]),
        "props": "claims|labels", "languages": "en", "format": "json",
    })
    return fetch(f"{WD_API}?{q}").get("entities", {})


def claim_value(entity, prop):
    for c in entity.get("claims", {}).get(prop, []):
        val = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if val is not None:
            return val
    return None


def commons_file_info(filename):
    q = urllib.parse.urlencode({
        "action": "query", "titles": f"File:{filename}",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata",
        "iiurlwidth": 1200, "format": "json",
    })
    pages = fetch(f"{COMMONS_API}?{q}").get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info:
            continue
        meta = info.get("extmetadata", {})

        def field(key):
            import re
            return re.sub(r"<[^>]+>", "",
                          (meta.get(key, {}).get("value") or "")).strip()

        return {
            "url": info.get("thumburl") or info.get("url"),
            "descriptionurl": info.get("descriptionurl", ""),
            "licence": field("LicenseShortName"),
            "artist": field("Artist") or "Unknown",
            "width": info.get("width", 0),
        }
    return None


def main():
    places = json.loads(PLACES.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    IMG_DIR.mkdir(exist_ok=True)
    confirmed = rejected = no_entity = no_image = 0

    for p in places:
        pid = p["id"]
        if pid in cache:
            if cache[pid]:
                confirmed += 1
            continue

        terms = [p["title"], p["title"].split("(")[0].strip(),
                 f"{p['title']} {p['city']}"]
        found = None
        checked = []

        for term in terms:
            ids = search_entities(term)
            time.sleep(0.4)
            if not ids:
                continue
            for qid, ent in entity_claims(ids).items():
                coord = claim_value(ent, "P625")
                if not coord:
                    continue
                d = miles(p["lat"], p["lng"], coord["latitude"], coord["longitude"])
                label = ent.get("labels", {}).get("en", {}).get("value", qid)
                checked.append((label, round(d, 1)))
                if d > MAX_MILES:
                    continue
                img = claim_value(ent, "P18")
                if not img:
                    continue
                found = {"qid": qid, "label": label, "file": img, "distance": round(d, 2)}
                break
            time.sleep(0.4)
            if found:
                break

        if not found:
            near = [c for c in checked if c[1] <= MAX_MILES]
            if near:
                print(f"  no P18 image: {pid:34} (matched {near[0][0]!r} at {near[0][1]} mi)")
                no_image += 1
            elif checked:
                nearest = min(checked, key=lambda c: c[1])
                print(f"  too far      : {pid:34} nearest {nearest[0]!r} {nearest[1]} mi")
                rejected += 1
            else:
                print(f"  no entity    : {pid}")
                no_entity += 1
            cache[pid] = None
            CACHE.write_text(json.dumps(cache, indent=1))
            continue

        info = commons_file_info(found["file"])
        time.sleep(0.4)
        if not info or not info["url"]:
            cache[pid] = None
            no_image += 1
            CACHE.write_text(json.dumps(cache, indent=1))
            continue

        ext = pathlib.Path(urllib.parse.urlparse(info["url"]).path).suffix or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png"):
            ext = ".jpg"
        dest = IMG_DIR / f"{pid}{ext}"
        try:
            req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                dest.write_bytes(r.read())
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "62",
                            "--resampleWidth", str(fi.MAX_IMAGE_WIDTH), str(dest)],
                           check=False, capture_output=True)
        except Exception as exc:
            print(f"  download failed {pid}: {exc}", file=sys.stderr)
            cache[pid] = None
            CACHE.write_text(json.dumps(cache, indent=1))
            continue

        cache[pid] = {
            "file": f"images/{dest.name}",
            "commons_title": f"File:{found['file']}",
            "artist": info["artist"][:160],
            "licence": info["licence"],
            "sourceUrl": info["descriptionurl"],
            "wikidata": found["qid"],
            "wikidata_label": found["label"],
            "distance_miles": found["distance"],
        }
        confirmed += 1
        print(f"  CONFIRMED {pid:32} {found['label'][:26]:28} "
              f"{found['distance']:4.1f} mi  {found['file'][:40]}")
        CACHE.write_text(json.dumps(cache, indent=1))
        time.sleep(0.3)

    print(f"\nconfirmed by coordinates : {confirmed}")
    print(f"entity too far away      : {rejected}")
    print(f"entity found, no photo   : {no_image}")
    print(f"no wikidata entity       : {no_entity}")


if __name__ == "__main__":
    main()
