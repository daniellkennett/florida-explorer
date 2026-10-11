"""Merge fetched Commons photos into places.json, download freely-licensed
stock for the places that have no real photo, and regenerate CREDITS.md.

Stock images are marked `representative: true` so the card can say so. A stock
photo is never presented as a picture of the actual venue.
"""

import json
import pathlib
import sys

import fetch_images as fi

# Venues where Commons has no genuine photograph, verified by inspecting the
# candidates by hand. Searching their names returns confident-looking wrong
# answers (an Amtrak service also called "The Floridian"; a same-named diner in
# Pennsylvania and a Disneyland one), so they are pinned to labelled stock
# rather than left to the matcher.
NO_REAL_PHOTO = {
    "ftl-floridian",          # an Amtrak service shares the name
    "ftl-peter-pan-diner",    # same-named diners in PA and at Disneyland
    "orl-hourglass-brewing",  # matches Disney's Pop Century "Hourglass Lake"
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACES = ROOT / "data" / "places.json"
WD_CACHE = ROOT / "data" / ".wikidata-cache.json"
TIER2_CACHE = ROOT / "data" / ".tier2-cache.json"
STOCK_CACHE = ROOT / "data" / ".stock-cache.json"
IMG_DIR = ROOT / "images"

# Generic, licence-clean imagery per fallback theme. Chosen by tag/category so
# a club gets a club and a diner gets a diner.
STOCK_THEMES = {
    "diner": "Florida diner restaurant exterior",
    "restaurant": "Florida restaurant outdoor dining",
    "nightlife": "Miami Beach bar night neon",
    "brewery": "Florida brewery taproom beer",
    "park": "Florida public park palm trees",
    "beach": "Florida beach ocean palm",
    "art": "Florida art gallery mural",
    "street": "Miami Florida street scene",
}


def theme_for(place):
    tags, cat, title = place["tags"], place["category"], place["title"].lower()
    if "diner" in title or "house" in title:
        return "diner"
    if cat == "nightlife":
        return "brewery" if "brew" in title or "hourglass" in title else "nightlife"
    if cat == "food":
        return "restaurant"
    if "beach" in tags:
        return "beach"
    if "art" in tags:
        return "art"
    if "nature" in tags or "outdoors" in tags:
        return "park"
    return "street"


def alt_for(place, representative):
    if representative:
        return (f"A representative photograph of a {theme_for(place)} scene, "
                f"standing in for {place['title']}")
    return f"{place['title']} in {place['neighborhood']}, {place['city']}, Florida"


def get_stock(theme, stock_cache):
    """Download one free image per theme, reused across places."""
    if theme in stock_cache:
        return stock_cache[theme]

    for term in (STOCK_THEMES[theme], theme):
        titles = [t for t in fi.search(term, 15) if not fi.FILE_REJECT.search(t)]
        infos = fi.image_info(titles)
        for t in titles:
            meta = infos.get(t)
            if meta and meta["url"] and fi.acceptable(meta) and meta["width"] >= 1000:
                dest = IMG_DIR / f"stock-{theme}.jpg"
                try:
                    fi.download(meta["url"], dest)
                except Exception as exc:
                    print(f"  stock download failed {theme}: {exc}", file=sys.stderr)
                    continue
                stock_cache[theme] = {
                    "file": f"images/{dest.name}",
                    "commons_title": t,
                    "artist": meta["artist"][:160],
                    "licence": meta["licence"],
                    "sourceUrl": meta["descriptionurl"],
                }
                STOCK_CACHE.write_text(json.dumps(stock_cache, indent=1))
                print(f"  stock {theme:12} {meta['licence'][:16]:18} {t[5:58]}")
                return stock_cache[theme]
    stock_cache[theme] = None
    return None


def main():
    places = json.loads(PLACES.read_text())
    # Image sources in descending order of confidence:
    #  1. Wikidata  - the entity's own P18 photo, confirmed by coordinates.
    #  2. Tier 2    - Commons filename carrying both the venue name and an
    #                 independent Florida geographic token.
    #  3. Stock     - themed placeholder, labelled in the UI.
    wd = json.loads(WD_CACHE.read_text()) if WD_CACHE.exists() else {}
    tier2 = json.loads(TIER2_CACHE.read_text()) if TIER2_CACHE.exists() else {}
    stock_cache = json.loads(STOCK_CACHE.read_text()) if STOCK_CACHE.exists() else {}
    real = rep = none = 0

    for p in places:
        hit = wd.get(p["id"]) or tier2.get(p["id"])
        provenance = ("Wikidata P18, confirmed by coordinates"
                      if wd.get(p["id"]) else "Commons name + location match")
        if hit and p["id"] in NO_REAL_PHOTO:
            print(f"  pinned to stock (no genuine photo exists): {p['id']}")
            hit = None
        if hit:
            p["image"] = {
                "file": hit["file"],
                "artist": hit["artist"],
                "licence": hit["licence"],
                "sourceUrl": hit["sourceUrl"],
                "commonsTitle": hit["commons_title"],
                "representative": False,
                "verifiedBy": provenance,
                "alt": alt_for(p, False),
            }
            real += 1
            continue

        stock = get_stock(theme_for(p), stock_cache)
        if stock:
            p["image"] = {
                "file": stock["file"],
                "artist": stock["artist"],
                "licence": stock["licence"],
                "sourceUrl": stock["sourceUrl"],
                "commonsTitle": stock["commons_title"],
                "representative": True,
                "alt": alt_for(p, True),
            }
            rep += 1
        else:
            p["image"] = {"file": "", "representative": True, "alt": alt_for(p, True)}
            none += 1

    PLACES.write_text(json.dumps(places, indent=1))

    # CREDITS.md: one row per distinct committed image.
    rows, seen = [], set()
    for p in places:
        img = p["image"]
        if not img.get("file") or img["file"] in seen:
            continue
        seen.add(img["file"])
        name = pathlib.Path(img["file"]).name
        kind = "representative" if img["representative"] else "the venue"
        rows.append(f"| `{name}` | {kind} | {img.get('artist', '?')} | "
                    f"{img.get('licence', '?')} | [Commons]({img.get('sourceUrl', '')}) |")

    (ROOT / "CREDITS.md").write_text(
        "# Image credits\n\n"
        "Every image below comes from [Wikimedia Commons](https://commons.wikimedia.org) "
        "under a licence permitting redistribution, and is committed to this repository "
        "rather than hot-linked.\n\n"
        "Images marked **representative** do not depict the venue they illustrate; they "
        "stand in for places with no freely-licensed photograph, and the interface labels "
        "them as such.\n\n"
        "| File | Shows | Author | Licence | Source |\n"
        "| --- | --- | --- | --- | --- |\n"
        + "\n".join(sorted(rows)) + "\n")

    # Earlier pipeline runs leave behind images no longer referenced (a match
    # that was later rejected). Prune them so the repository only carries
    # images that are actually used and attributed.
    referenced = {p["image"]["file"] for p in places if p["image"].get("file")}
    # Also treat every file named by a cache as referenced. Without this, a
    # prune run while an image stage is mid-flight (or before this script has
    # consumed its cache) deletes images that are about to be needed.
    for c in (wd, tier2, stock_cache):
        referenced |= {v["file"] for k, v in c.items()
                       if v and v.get("file") and k not in NO_REAL_PHOTO}
    pruned = 0
    for path in sorted(IMG_DIR.glob("*")):
        if path.name.startswith("."):
            continue
        if f"images/{path.name}" not in referenced:
            path.unlink()
            pruned += 1
    if pruned:
        print(f"pruned {pruned} unreferenced image(s)")

    print(f"\nreal venue photos : {real}")
    print(f"representative    : {rep}")
    print(f"no image at all   : {none}")
    print(f"credits rows      : {len(rows)}")


if __name__ == "__main__":
    main()
