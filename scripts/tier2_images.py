"""Second-tier image matching for places with no Wikidata-confirmed photo.

Wikidata coverage is high-precision but only reaches notable venues. This tier
recovers diners, bars and markets by requiring *two* independent signals in the
Commons filename:

  1. enough of the venue's own distinctive words, and
  2. an explicit Florida geographic token (Florida, FL, or the city/neighbourhood).

Requiring both is what separates "Miami Beach - Joe's Stone Crab Restaurant 02"
(accepted) from "Coconuts - single and cracked open" or "El Camino, Brussels"
(rejected). Anything that fails still falls back to labelled stock.
"""

import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import fetch_images as fi

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACES = ROOT / "data" / "places.json"
WD_CACHE = ROOT / "data" / ".wikidata-cache.json"
CACHE = ROOT / "data" / ".tier2-cache.json"
IMG_DIR = ROOT / "images"

STOPWORDS = {"the", "and", "of", "at", "in", "a", "museum", "park", "state", "center",
             "centre", "house", "district", "garden", "gardens", "restaurant", "diner",
             "market", "marketplace", "bar", "club", "company", "art", "beach", "city"}


def venue_words(title):
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9']{3,}", title)]
    distinctive = [w for w in words if w not in STOPWORDS]
    return distinctive or words


def florida_tokens(place):
    """Geographic tokens that are NOT part of the venue's own name.

    The two signals must be independent. "Mills 50 District" sits in the Mills
    50 neighbourhood, so without this exclusion the word "Mills" would satisfy
    both tests at once and admit "Ellicott's Mills Historic District" in
    Maryland. Likewise "Universal CityWalk" in the Universal neighbourhood
    would admit the Hollywood one."""
    toks = {"florida", "fl", place["city"].lower(), place["neighborhood"].lower()}
    toks |= {w.lower() for w in re.findall(r"[A-Za-z]{4,}", place["city"])}
    toks |= {w.lower() for w in re.findall(r"[A-Za-z]{4,}", place["neighborhood"])}
    name_words = {w.lower() for w in re.findall(r"[A-Za-z0-9']+", place["title"])}
    return {t for t in toks if t and t not in name_words}


def strong_match(place, commons_title):
    name = commons_title[5:] if commons_title.startswith("File:") else commons_title
    stem = re.sub(r"\.(jpe?g|png)$", "", name, flags=re.IGNORECASE).lower()
    tokens = set(re.findall(r"[a-z0-9']+", stem))

    words = venue_words(place["title"])
    matched = sum(1 for w in words if w in tokens)
    name_ok = matched >= max(1, min(2, len(words)))     # at least two, or all if fewer

    geo_ok = bool(florida_tokens(place) & tokens)
    return name_ok and geo_ok, matched, len(words), geo_ok


def main():
    places = json.loads(PLACES.read_text())
    wd = json.loads(WD_CACHE.read_text()) if WD_CACHE.exists() else {}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    accepted = 0

    for p in places:
        pid = p["id"]
        if wd.get(pid):          # already confirmed via Wikidata
            continue
        if pid in cache:
            if cache[pid]:
                accepted += 1
            continue

        best = None
        for term in (p["title"], f"{p['title']} {p['city']} Florida"):
            titles = [t for t in fi.search(term, 15)
                      if not fi.FILE_REJECT.search(t) and fi.plausible_title(t)]
            infos = fi.image_info(titles)
            for t in titles:
                meta = infos.get(t)
                if not (meta and meta["url"] and fi.acceptable(meta)
                        and meta["width"] >= 800):
                    continue
                ok, matched, total, geo = strong_match(p, t)
                if ok:
                    best = (t, meta, matched, total)
                    break
            time.sleep(0.8)
            if best:
                break

        if not best:
            cache[pid] = None
            CACHE.write_text(json.dumps(cache, indent=1))
            continue

        title, meta, matched, total = best
        ext = pathlib.Path(urllib.parse.urlparse(meta["url"]).path).suffix or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png"):
            ext = ".jpg"
        dest = IMG_DIR / f"{pid}{ext}"
        try:
            req = urllib.request.Request(meta["url"], headers={"User-Agent": fi.UA})
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
            "commons_title": title,
            "artist": meta["artist"][:160],
            "licence": meta["licence"],
            "sourceUrl": meta["descriptionurl"],
            "name_words_matched": f"{matched}/{total}",
        }
        accepted += 1
        print(f"  tier2 {pid:32} {matched}/{total} words + geo  {title[5:58]}")
        CACHE.write_text(json.dumps(cache, indent=1))
        time.sleep(0.5)

    print(f"\ntier-2 accepted: {accepted}")


if __name__ == "__main__":
    main()
