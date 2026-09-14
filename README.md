# Aperture digital ads

HTML5 display ad units for Aperture Global listings, and the builder that makes them.
**Opal tier and above** (list price ≥ $1,000,000).

> **Keep this repository private.** It carries Aperture logo art, the brand background
> plates and client listing photography.

## Review a set

Open `index.html` at the root — it links every property in this repo. From there each
property's review page plays all six sizes on one page, with play/pause, replay and a
15-second scrubber per unit (the scrubber drives the photo band as well as the copy).

No server needed: double-click `index.html`, or browse it on GitHub Pages (below).

### Live links

**All properties** → <https://crescentbutterfly23.github.io/Digital-ads---Aperture/>

| Property | Ad index |
|---|---|
| 3 Lambton House — Eton, Windsor | https://crescentbutterfly23.github.io/Digital-ads---Aperture/previews/lambton-house/LambtonHouse-preview/index.html |
| 11850 N 5th E — Idaho Falls, ID | https://crescentbutterfly23.github.io/Digital-ads---Aperture/previews/11850-n-5th-e/11850N5thE-preview/index.html |

These are the links to send to an agent. **They only work once GitHub Pages is switched on**
for this repository — see the next section. Until then they return 404.

### Same pages in a local clone

| Property | Ad index |
|---|---|
| 3 Lambton House — Eton, Windsor | [`previews/lambton-house/LambtonHouse-preview/index.html`](previews/lambton-house/LambtonHouse-preview/index.html) |
| 11850 N 5th E — Idaho Falls, ID | [`previews/11850-n-5th-e/11850N5thE-preview/index.html`](previews/11850-n-5th-e/11850N5thE-preview/index.html) |

Opening those from github.com's file viewer shows the HTML source, not the ads — the viewer
never runs a page. Use the live links above, or clone the repo and open the file.

Each property folder also holds its run report and zips:

| Property | Run report | Zips |
|---|---|---|
| 3 Lambton House | [run report](previews/lambton-house/run-report_LambtonHouse_2026-09-14.md) | [`previews/lambton-house/zips/`](previews/lambton-house/zips/) |
| 11850 N 5th E | [run report](previews/11850-n-5th-e/run-report_11850N5thE_2026-09-14.md) | [`previews/11850-n-5th-e/zips/`](previews/11850-n-5th-e/zips/) |

## Share it with the agents

In this repository: **Settings → Pages → Build and deployment → Deploy from a branch →
`main` / `/ (root)` → Save.** Give it a minute, then the links in the section above go live at:

```
https://crescentbutterfly23.github.io/Digital-ads---Aperture/
```

A `.nojekyll` file is already in place so Pages serves the folders as-is.

Two things that catch this out:

- **Pages on a private repository needs a paid plan.** On a free account the Pages option is
  only available once the repo is public. This repo carries Aperture logo art and client
  photography, so going public to get a link is a real decision, not a formality.
- **Pages sites are public even when the repository is private.** Anyone with the URL can
  open the ads; the link is not access-controlled.

If neither is acceptable, share the set without Pages: add the reviewer as a collaborator and
have them clone and open `index.html`, or zip a `previews/<slug>/` folder and send it — every
unit is self-contained, so it plays from any folder with no server.

## Build a new property

```bash
python3 build.py \
  --order "<Aperture Pack orders>/<order folder>" \
  --overrides overrides/<slug>.json \
  --out "previews/<slug>"
```

Requires Python 3 with Pillow:

```bash
pip3 install --user pillow
```

The two sets in this repo were produced with exactly:

```bash
python3 build.py --order ".../3 Lambton House, Imperial Park, Windsor, SL4 3TR" --overrides overrides/lambton.json     --out previews/lambton-house
python3 build.py --order ".../11850 N 5th E, Idaho Falls, ID"                   --overrides overrides/idaho-falls.json --out previews/11850-n-5th-e
```

After adding a property, add a card for it in the root `index.html`.

## What it makes

| | |
|---|---|
| Sizes | 768×1024, 1024×768, 480×320, 970×250, 320×480, 300×600 |
| Variant | carousel — four photos with arrows, dots, swipe and auto-advance |
| Loop | 7.5 s copy cycle, running continuously |
| Weight | held under the 700 KB cap; the builder prints each unit's weight and flags anything over |
| Click-through | the CTA only, not the whole ad |
| Backup still | `*_backup.jpg` per unit, for placements that need a static |

Units are self-contained: no webfonts fetched, no CDN, no server. Copy is set in embedded
subset webfonts — **Playfair Display 500** for the headline, **Archivo 300/500** for
everything else.

## Copy model

Read from the newest `CSV/property_data_*.csv` in the order folder:

- **eyebrow** ← `tagline`, uppercased, shown on the first pass then retired
- **headline** ← `street`
- **rotating sublines** ← location, spec (`br | bth | sqft`), `Listed by <name>`
- **CTA** — "Schedule a viewing"

Anything there can be replaced per property in `overrides/<slug>.json`. Override rather than
edit the CSV; the CSV belongs to the Power Pack.

Two fields need a decision on **every** order:

1. **`lines`** replaces the whole rotating set. Use it whenever the CSV's
   bedrooms/bathrooms/sqft do not describe the property the way a buyer reads it — 11850 N 5th E
   carries acreage and building sizes in those columns, so the generated spec line would have
   read "25 br | 5000 bth".
2. **`photos`** takes exactly four images, order-relative. Left unset, the builder picks one
   per room type from `out/previews`, then `out/print`, then `out/`, in the order exterior →
   living → kitchen → master → outdoor → dining → entry → amenities → interior. **Always look
   at the four it picked** — slug order picks a category, not a good picture.

`cityState` is right for print and often wrong for an ad line: "Windsor, SL4 3TR" became
"Eton, Windsor".

## Checks the builder runs

Problems print under the size in the run log and land in the run report:

- a line that outgrows its column (it is auto-shrunk to 68% of the design size first; a
  warning means even that did not fit)
- a line that lands on the photo band
- a CTA rule that falls outside the unit
- unit weight over the 700 KB cap

## Repository layout

```
index.html              landing page — links every property
build.py                the builder
overrides/              per-property copy and photo choices
assets/
  <size>/bg.jpg         brand ground, one per size
  <size>/logo.png       flattened logo plate for the backup still
  logo-master.svg       live logo art, placed per size by SIZES in build.py
  fonts/                Playfair Display + Archivo, subset (woff2 embedded, ttf for stills)
previews/<slug>/
  <Slug>-preview/       the review page and the units
  zips/                 one trafficable zip per unit
  run-report_*.md
```

## Known gaps

- **Carousel only.** No video variant. Orders with footage still need that built.
- **English only.** A second language means a second run with translated `lines` and a
  `_pt_` prefix, which the builder does not do yet.
- **Not wired into the Aperture order run routine** — deliberate, until the two gaps above
  are settled.
- The reference Parque das Nações units baked copy to outlined vector paths. These set live
  text instead: visually near-identical, not path-identical.

## Fonts

Playfair Display and Archivo are both under the SIL Open Font License 1.1, which is why they
can be subset and embedded in the units. See `assets/fonts/NOTICE.md`.
