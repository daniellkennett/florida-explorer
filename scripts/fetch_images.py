"""Find a real, freely-licensed photograph of each place on Wikimedia Commons,
download it, and record its attribution.

Only licences that permit redistribution are accepted. Places with no
acceptable match are left for the stock fallback and flagged
`representative: true` so the UI never implies a stock photo shows the venue.
"""

import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACES = ROOT / "data" / "places.json"
IMG_DIR = ROOT / "images"
CACHE = ROOT / "data" / ".commons-cache.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = ("FloridaExplorer/0.1 (+https://github.com/daniellkennett/florida-explorer; "
      "daniel.kennett@databricks.com)")

# Substrings that indicate a redistributable licence.
MAX_IMAGE_WIDTH = 800

LICENCE_OK = ("cc0", "cc-by", "cc by", "public domain", "pd-", "attribution")
LICENCE_BAD = ("non-free", "fair use", "nc", "noncommercial", "nd", "noderiv")

# Search terms that drag in irrelevant imagery (maps, logos, diagrams).
FILE_REJECT = re.compile(r"\.(svg|ogv|webm|pdf|tif)$|\blogo\b|\bmap\b|\bdiagram\b|"
                         r"\bseal\b|\bsign\b|\blocator\b|\bchart\b|\bplaque\b",
                         re.IGNORECASE)

# Ephemera rather than a photograph of the place. A 1960 place mat for a
# same-named diner in another state is a convincing-looking wrong answer.
EPHEMERA = re.compile(r"\b(menu|place ?mat|postcard|matchbook|advertisement|poster|"
                      r"brochure|ticket|stamp|label|drawing|painting|print|timetable)\b",
                      re.IGNORECASE)

# Venue names are not unique across the country: "The Floridian" is also an
# Amtrak service, and "Peter Pan Diner" also exists in Pennsylvania. Reject any
# candidate whose title names a place outside Florida.
ELSEWHERE = re.compile(
    r"\b(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    r"Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|"
    r"Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|"
    r"Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|"
    r"Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
    r"Tennessee|Texas|Utah|Vermont|Virginia|Washington|Wisconsin|Wyoming|"
    r"Chicago|Boston|Brooklyn|Manhattan|Philadelphia|Allentown|Detroit|Seattle|"
    r"Denver|Phoenix|Atlanta|Nashville|Houston|Dallas|Portland|"
    r"PA|NJ|NY|CA|TX|OH|IL|MA|MI|GA|NC|VA|WA)\b")


def plausible_title(title):
    """Reject ephemera and anything explicitly located outside Florida."""
    name = title[5:] if title.startswith("File:") else title
    if EPHEMERA.search(name):
        return False
    # An explicit Florida mention outweighs an incidental state abbreviation.
    if re.search(r"\b(Florida|FL|Miami|Orlando|Fort Lauderdale|Ft\.? Lauderdale)\b", name):
        return True
    return not ELSEWHERE.search(name)


def api(params):
    params = {**params, "format": "json"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as exc:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt + 1)      # back off on rate limiting
            print(f"    retry {attempt + 1}: {exc}", file=sys.stderr)
    return {}


def search(term, limit=12):
    d = api({"action": "query", "list": "search", "srnamespace": 6,
             "srlimit": limit, "srsearch": term})
    return [r["title"] for r in d.get("query", {}).get("search", [])]


def image_info(titles):
    """Fetch url + licence metadata for a batch of File: titles."""
    if not titles:
        return {}
    d = api({"action": "query", "titles": "|".join(titles[:20]),
             "prop": "imageinfo", "iiprop": "url|size|extmetadata",
             "iiurlwidth": 1200})
    out = {}
    for page in d.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info:
            continue
        meta = info.get("extmetadata", {})

        def field(key):
            return (meta.get(key, {}).get("value") or "").strip()

        out[page["title"]] = {
            "url": info.get("thumburl") or info.get("url"),
            "descriptionurl": info.get("descriptionurl", ""),
            "licence": re.sub(r"<[^>]+>", "", field("LicenseShortName")),
            "artist": re.sub(r"<[^>]+>", "", field("Artist")) or "Unknown",
            "width": info.get("width", 0),
        }
    return out


def acceptable(meta):
    lic = meta["licence"].lower()
    if not lic or any(b in lic.split() for b in ("nc", "nd")):
        return False
    if any(b in lic for b in LICENCE_BAD):
        return False
    return any(ok in lic for ok in LICENCE_OK)


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    # Cards display at roughly 400px, so 800px covers retina at a fraction of
    # the weight. Without this the repository grows to ~18MB of images.
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "62",
                    "--resampleWidth", str(MAX_IMAGE_WIDTH), str(dest)],
                   check=False, capture_output=True)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    places = json.loads(PLACES.read_text())
    IMG_DIR.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    hits = misses = 0

    for p in places:
        if only and p["id"] != only:
            continue
        if p["id"] in cache:
            if cache[p["id"]]:
                hits += 1
            else:
                misses += 1
            continue

        # Try the venue name, then the name with its city, then the neighbourhood.
        terms = [p["title"], f"{p['title']} {p['city']}",
                 f"{p['neighborhood']} {p['city']} Florida"]
        chosen = None
        for term in terms:
            titles = [t for t in search(term)
                      if not FILE_REJECT.search(t) and plausible_title(t)]
            infos = image_info(titles)
            for t in titles:
                meta = infos.get(t)
                if meta and meta["url"] and acceptable(meta) and meta["width"] >= 800:
                    chosen = (t, meta, term)
                    break
            if chosen:
                break
            time.sleep(1.0)

        if not chosen:
            print(f"  no free image: {p['id']}")
            cache[p["id"]] = None
            misses += 1
            CACHE.write_text(json.dumps(cache, indent=1))
            continue

        title, meta, term = chosen
        ext = pathlib.Path(urllib.parse.urlparse(meta["url"]).path).suffix or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png"):
            ext = ".jpg"
        dest = IMG_DIR / f"{p['id']}{ext}"
        try:
            download(meta["url"], dest)
        except Exception as exc:
            print(f"  download failed {p['id']}: {exc}", file=sys.stderr)
            cache[p["id"]] = None
            misses += 1
            continue

        cache[p["id"]] = {
            "file": f"images/{dest.name}",
            "commons_title": title,
            "artist": meta["artist"][:160],
            "licence": meta["licence"],
            "sourceUrl": meta["descriptionurl"],
            "matched_term": term,
        }
        hits += 1
        print(f"  ok {p['id']:38} {meta['licence'][:18]:20} {title[5:60]}")
        CACHE.write_text(json.dumps(cache, indent=1))
        time.sleep(1.0)

    CACHE.write_text(json.dumps(cache, indent=1))
    print(f"\nreal photos: {hits}   needing stock: {misses}")


if __name__ == "__main__":
    main()
