# Marie's Florida Explorer

A static guide to Miami, Orlando and Fort Lauderdale that answers one question:
**what should I do, right now, from where I am?**

Pick a city (or share your location), set the time, choose a vibe, and get places that are
actually open, sorted by how far away they really are.

→ **https://daniellkennett.github.io/florida-explorer/**

## What it does

- **Distance from you.** Optional browser geolocation, great-circle distance per place,
  automatic nearest-city selection, and a clean fallback to manual city picking if location
  is declined or unavailable.
- **Genuinely open now.** Opening hours are evaluated in `America/New_York`, so the answer is
  correct even when you are browsing from another timezone. Handles venues that close after
  midnight and venues open 24 hours.
- **Honest data.** Every place carries a real geocoded address, a researched price, a source
  for its opening hours, and a `last_verified` date, all shown in the detail view.
- **Working details and directions.** Full hours table, price, address, website, and a Google
  Maps (or Apple Maps) deep link that lands on the right venue.
- **Saved trips and shareable views.** Favourites persist in `localStorage`; the full filter
  state lives in the URL, so any view can be shared as a link.
- **Keyboard accessible.** Every control is reachable and visibly focused, the detail dialog
  traps and restores focus, and result counts are announced to screen readers.

## Running locally

The page fetches `data/places.json`, which browsers block over `file://`, so serve the folder:

```bash
python3 -m http.server 8765
# then open http://localhost:8765/
```

## Project layout

```
index.html           markup, Tailwind config, favicon
assets/app.js        filtering, geolocation, hours, modal, storage, URL state
assets/styles.css    custom styling on top of Tailwind
data/places.json     the dataset the app loads at runtime  <- generated, do not hand-edit
data/seed.json       intermediate build artefact
images/              committed, freely-licensed photographs
CREDITS.md           per-image author and licence
scripts/             the data pipeline (see below)
tests/hours.test.cjs tests for the hours, distance and link logic
```

## The data pipeline

`data/places.json` is generated. Edit `scripts/seed.py` — the editorial source — and rebuild:

```bash
cd scripts
python3 seed.py             # editorial data        -> data/seed.json
python3 enrich.py           # Nominatim geocoding   -> coordinates, addresses, OSM hours
python3 build.py            # merge + derive        -> data/places.json
python3 wikidata_images.py  # tier 1: coordinate-confirmed photos
python3 tier2_images.py     # tier 2: name + location match for the remainder
python3 apply_images.py     # choose best source, prune, write CREDITS.md
python3 validate.py         # integrity gate
```

The order matters: `build.py` rewrites `data/places.json` from the seed, so it must run
*before* the image stages annotate it, and the image stages need the coordinates it emits.

Both network stages cache their responses in `data/.*-cache.json`, so re-running is cheap and
offline-friendly. Delete a cache file to force a refetch.

### How places are verified

- **Coordinates and addresses** come from OpenStreetMap via Nominatim, and every result is
  rejected unless it falls inside Florida's bounding box.
- **Opening hours** prefer OpenStreetMap's `opening_hours` tag where one exists, parsed by
  `scripts/osm_hours.py`. Unparseable tags fail loudly and fall back to curated hours rather
  than silently producing wrong times. Each place records which source was used.
- **Photographs** are resolved through Wikidata, not Commons text search. A candidate is only
  accepted if the Wikidata entity's coordinates are within two miles of the geocoded location,
  which is what stops a search for "El Camino" returning a bar in Brussels or "Coconuts"
  returning actual coconuts. Places with no verifiable photograph get a clearly-labelled
  **representative image** instead, and the UI says so on the card.

### Known limitations

Prices and hours are researched snapshots committed to the repository, not a live feed. They
drift as venues change them, which is why each place shows a `last_verified` date and the
detail view advises confirming with the venue. There is no backend and no API key.

## Tests

```bash
node tests/hours.test.cjs                      # 32 assertions
TZ=Asia/Tokyo node tests/hours.test.cjs        # must pass from any timezone
cd scripts && python3 validate.py              # dataset integrity
```

## Rebranding

Everything user-facing that names the operator is in the `BRAND` object at the top of
`assets/app.js` — name, tagline, hero copy, the curator badge shown on recommended places, and
the logo glyph. Change it there; the only other places a name appears are the static
`<title>`, the meta description and the nav fallback text in `index.html`, which exist for
link previews and for the moment before JavaScript runs.

### Colour

The palette is a pastel tan defined once in the Tailwind config in `index.html` (`brand`,
plus `sage` and `blush` companions), with warm `stone` neutrals in place of grey. Note that
`brand-700` is the lightest tan that holds WCAG AA for normal-size text and for white text on
a filled background, so interactive fills and body-size accents use 700 or darker — the
lighter steps are for backgrounds and large display text only.

### Recommendations

The gold "Daniel Recommended" badge is driven by `recommended: true` in `scripts/seed.py`.
It is currently set on the three Miami places that have actually been visited: Bayside
Marketplace, Ocean Drive and Calle Ocho / Domino Park.
