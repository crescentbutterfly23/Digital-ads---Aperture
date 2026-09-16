# Aperture digital ads

HTML5 display ad units for Aperture Global listings, and the builder that makes them.
**Opal tier and above** (list price ≥ $1,000,000).

> **This repository is public**, so that GitHub Pages can serve the ad indexes on a free
> account. Everything committed here is on the open web and indexable: Aperture logo art,
> the brand background plates, and client listing photography. Only add a property whose
> photography is cleared to be public, and take a set down when the listing closes.

The reference the whole routine is measured against is the Parque das Nações set
(`~/Downloads/ParqueDasNacoes-EN-PT-review`). Its README is the spec; this one describes how
the builder meets it.

**New property? Follow [`RUNBOOK.md`](RUNBOOK.md).** It is the end-to-end process,
written to be followed cold.

## Review a set

Open `index.html` at the root — it links every property in this repo. Each property's review
page plays all six sizes on one page, with play/pause, replay and a 15-second scrubber per
unit, plus **Replay all** and **Last frame**.

Each unit is inlined into the page with `srcdoc`, so the iframes are same-origin with the
review page and the controls work when the file is opened straight off the disk. No server.

| Property | Ad index |
|---|---|
| 3 Lambton House — Eton, Windsor | `previews/lambton-house/LambtonHouse-preview/index.html` |
| 11850 N 5th E — Idaho Falls, ID | `previews/11850-n-5th-e/11850N5thE-preview/index.html` |

Live, once Pages is enabled: <https://crescentbutterfly23.github.io/Digital-ads---Aperture/>

## Build a property

```bash
python3 build.py \
  --order "<Aperture Pack orders>/<order folder>" \
  --overrides overrides/<slug>.json \
  --video "<walkthrough master>.mp4" \
  --out "previews/<slug>"
```

Needs Python 3 with Pillow, fontTools and ffmpeg.

Output, matching the reference package:

```
<out>/
  README.md                       for whoever traffics the set
  run-report_<Slug>_<date>.md     copy, photo picks, weights, warnings
  <Slug>-preview/
    index.html                    the review page
    APERTURE_<Slug>_<size>_video_en_ad.html
    APERTURE_<Slug>_<size>_video_en_video.mp4
    APERTURE_<Slug>_<size>_video_en_bg.jpg
    APERTURE_<Slug>_<size>_video_en_photo1..4.jpg
    APERTURE_<Slug>_<size>_video_en_backup.jpg
  zips/                           one trafficable zip per unit
```

## What it makes

| | |
|---|---|
| Sizes | 768×1024, 1024×768, 480×320, 970×250, 320×480, 300×600 |
| Variant | **video** — one unit per size. The four photos sit underneath as the autoplay fallback. Pass `--variants video carousel` for both. |
| Loop | 15 s, two 7.5 s copy cycles |
| Weight | held under the 700 KB cap; the video is sized to whatever the html, background and photos leave |
| Click-through | the CTA only, never the whole ad. `clickTag` defaults to apertureglobal.com, overridable with `?clicktag=<url>` |
| Backup still | `*_backup.jpg` per unit |

**Copy is baked to vector outlines** (`outline.py`), as the reference does it. The units carry
no webfonts at all. That is not only about portability: with outlines there is no shaping
engine, so the browser and the Pillow still renderer cannot disagree about metrics — which was
the cause of a long run of size and baseline bugs. Outlined runs are cached in
`assets/outlines/`, keyed font+size+tracking+text, so repeat builds and the runs shared across
properties (the CTA, the eyebrow) cost nothing.

Faces: **Cormorant Garamond Light** headline, **Cormorant Garamond Medium Italic** eyebrow,
**Archivo Light** sublines, **Archivo Medium** CTA. Not Playfair.

## The walkthrough video

Generated in Google Flow from the listing stills, then assembled here with ffmpeg.
**`RUNBOOK.md` has the full step-by-step**, including the prompts and the ffmpeg commands.
Three points that matter:

- One clip **per room**, a subtle move inside that single space. Never "image A travelling to
  image B": we do not know the layouts, and the model invents architecture. It has produced a
  fly-through of a facade and an entirely fabricated building.
- Hold the source photograph's framing. When the frame matches the photo, anything invented is
  obvious; when the camera roams you cannot tell what is real.
- Cut the clips together with cross-dissolves. The reference is four scenes, ~3.75 s each,
  15 fps, 15.000 s.

## Copy model

From the newest `CSV/property_data_*.csv` in the order folder:

- **eyebrow** — always **"Exclusive Offer"**, house copy, *not* the CSV `tagline`. It opens the
  ad beside the aperture mark and hands over to the full logo.
- **headline** ← `street`
- **rotating sublines** ← location, spec, `Listed by <name>`
- **CTA** — "Schedule a viewing"

Override per property in `overrides/<slug>.json` rather than editing the CSV; the CSV belongs
to the Power Pack routine. Two fields need a decision on **every** order:

1. **`lines`** replaces the whole rotating set. Use it when the CSV's bedrooms/bathrooms/sqft
   do not describe the property the way a buyer reads it — 11850 N 5th E carries acreage and
   building sizes in those columns, so the generated spec line would read "25 br | 5000 bth".
2. **`photos`** takes exactly four images, order-relative. Auto-selection picks a *category* by
   filename slug, not a good picture. Always look at what it chose.

`cityState` is right for print and often wrong for an ad line: "Windsor, SL4 3TR" became
"Imperial Park, Windsor, SL4 3TR".

## Checks the builder runs

Printed under each size and written into the run report:

- a line that outgrows its column
- a line that lands on the photo band
- a CTA rule that falls outside the unit
- unit weight over the 700 KB cap

## Assets

`assets/` is brand furniture, not per-property, recovered from the reference set:

- `<size>/bg.jpg` — the dark ground
- `<size>/logo.png` + `logo.json` — flattened logo plate and origin, for the backup still
- `logo-master.svg` — the live logo art, placed per size by `spec.json`
- `mark-raw.svg` — the aperture mark that opens the eyebrow
- `fonts/` — Cormorant Garamond and Archivo, subset, with `lnum` kept so house numbers sit on
  the baseline
- `spec.json` — the measured geometry: band rect, keylines, logo transform, and per slot the
  face, size, tracking, baseline, anchor and x
- `outlines/` — the outline cache

## Known gaps

- **English only.** A second language means a second run with translated `lines` and a `_pt_`
  prefix, which the builder does not do yet.
- **Not in the Aperture order run routine.** Deliberate, until the above is settled.
