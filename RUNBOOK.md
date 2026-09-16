# Runbook — building a property's digital ads

End-to-end process for one property. Written to be followed without any prior context.

> The working copy of this runbook and the builder live in
> `~/Documents/Claude/aperture-digital-ads/`. This repo is a showcase copy.


The reference set every unit is measured against is
`~/Downloads/ParqueDasNacoes-EN-PT-review/` (Parque das Nações). Its `README.md` is the spec.
**Read it before starting.** Do not redesign anything — the job is to reproduce that template
with this property's copy, photos and walkthrough.

---

## 0. Before you start

**Tier check.** Digital ads are **Opal and above** — list price ≥ $1,000,000. Below that, stop.

**Tools:** Python 3 with `pillow` and `fonttools`, plus `ffmpeg`. Check:

```bash
python3 -c "import PIL, fontTools; print('ok')" && ffmpeg -version | head -1
```

**Inputs**, all in the order folder under
`~/Documents/LPT Realty/Aperture/Aperture Pack orders/<order>/`:

- `CSV/property_data_<slug>_v<N>.csv` — the Power Pack CSV (highest `v` wins)
- `out/previews/` or `out/print/` — photos already run through photo intake/selects

If the CSV or the photo selects are missing, those routines come first.

---

## 1. Choose the four photos

The builder can pick them, but it picks a *category* by filename slug, not a good picture. Look
at the candidates yourself — build a contact sheet if there are many:

```bash
python3 - <<'PY'
from PIL import Image, ImageDraw
import os
d = "<order>/out/previews"            # or out/print
fs = [f for f in sorted(os.listdir(d)) if f.lower().endswith((".jpg", ".png"))]
cols, tw, th = 5, 300, 200
sheet = Image.new("RGB", (cols*tw, ((len(fs)+cols-1)//cols)*(th+16)), (18, 22, 30))
dr = ImageDraw.Draw(sheet)
for i, f in enumerate(fs):
    im = Image.open(os.path.join(d, f)).convert("RGB"); im.thumbnail((tw, th))
    x, y = (i % cols)*tw, (i//cols)*(th+16)
    sheet.paste(im, (x, y)); dr.text((x+4, y+th+2), f, fill=(210, 220, 235))
sheet.save("/tmp/sheet.jpg", quality=82)
PY
```

Pick four that read as a walkthrough: **exterior hero → interior → detail → outdoor**. The
lead photo carries the unit. Avoid construction, dirt, empty rooms and anything with signage.

---

## 2. Write the overrides

`overrides/<slug>.json`:

```json
{
  "slug": "LambtonHouse",
  "headline": "3 Lambton House",
  "lines": [
    "Imperial Park, Windsor, SL4 3TR",
    "3 bed | 3.5 bath | 1,887 sq ft",
    "Listed by Toby Madden"
  ],
  "photos": [
    "out/print/exterior-01.png",
    "out/print/living-01.png",
    "out/print/kitchen-01.png",
    "out/print/master-01.png"
  ]
}
```

- **Do not set `eyebrow`** — it is always "Exclusive Offer" unless Natalie says otherwise.
- **Always set `lines`** if the CSV's bedrooms/bathrooms/sqft are not what a buyer reads. On
  11850 N 5th E those columns hold acreage and building sizes, so the generated spec line would
  say "25 br | 5000 bth".
- **`cityState` is print copy.** For an ad line it is often wrong: "Windsor, SL4 3TR" became
  "Imperial Park, Windsor, SL4 3TR".
- Never edit the CSV. It belongs to the Power Pack routine.

---

## 3. Generate the walkthrough clips (Google Flow)

**What the video actually is** — measured off the reference master, not guessed: four scenes,
each a *subtle camera move inside one room*, cross-dissolved, 15 fps, 15.000 s total.

**The rule that matters: one clip per room.** Never prompt "image A travelling to image B". We
do not know the properties' layouts, so the model invents architecture — it has produced a
fly-through of a building's facade and an entirely fabricated house that was not the property.

### Credits

Flow charges **15 credits per 10 s clip**. An account with 50 credits affords three. One
property needs three or four scenes, so **one account per property**.

### Steps

1. Open <https://flow.google.com> and **create a new project**. (A project that has been used
   heavily can wedge the page; a fresh one behaves.)
2. Upload the four photos. If a native file picker appears and you cannot drive it, put the
   images somewhere easy and select them by hand.
3. For each photo: hover its tile → **⋮ → Animate**.
   **This step is not optional.** Naming a file in the prompt text does *not* attach it — Flow
   will accept the prompt, quote it, charge for it, and generate from something else entirely.
   A thumbnail chip must be visible above the prompt box before you send.
4. Prompt, per clip:

   ```
   Generate exactly ONE video clip and no more - 16:9, 10 seconds, 15 credits.
   Animate this single image only. Hold the photograph's framing: a very subtle
   camera move inside this one space. Do NOT travel out of the room, do not move
   to any other space, do not invent any architecture.
   Photorealistic, steady, no shake. No people, no text, no titles.
   ```

5. **Check the quoted cost on every confirmation.** Flow's instinct is one clip per *transition*
   and it will happily plan more than you asked. If it quotes more than one generation, reject
   and re-prompt. Click **Approve**, never **Always approve**.
6. When each clip finishes: **⋮ → Download → 720p (Original size)**.
7. **Check every clip against its source photo before using it** — compare frame 0 and the last
   frame to the photograph. Wrong furniture, a window that does not exist, or a different room
   means discard it.

Put the downloads in `~/Desktop/Aperture-Flow-videos/<Slug>/`.

### Settings

In Agent settings: video **16:9**, count **x1**, and leave "Confirm before generating" on
**Always**. Every unit's photo band is landscape or square, so one 16:9 master crops to all six
sizes — you never need a portrait render.

---

## 4. Assemble the 15-second master

Trim each clip to the part that still holds the photograph's framing — in practice the opening
seconds — then cross-dissolve. For **four** scenes at 4.125 s each with 0.5 s dissolves:

```bash
SEG=/tmp/seg; mkdir -p $SEG
OUT=~/Desktop/Aperture-Flow-videos/<Slug>

# one per scene: -ss picks the usable window, setpts stretches it to 4.125 s
ffmpeg -y -ss 0 -t 3.0 -i clip1.mp4 -vf "setpts=1.375*PTS,fps=15,scale=1280:720" -an $SEG/a.mp4
ffmpeg -y -ss 0 -t 3.0 -i clip2.mp4 -vf "setpts=1.375*PTS,fps=15,scale=1280:720" -an $SEG/b.mp4
ffmpeg -y -ss 0 -t 3.0 -i clip3.mp4 -vf "setpts=1.375*PTS,fps=15,scale=1280:720" -an $SEG/c.mp4
ffmpeg -y -ss 0 -t 3.0 -i clip4.mp4 -vf "setpts=1.375*PTS,fps=15,scale=1280:720" -an $SEG/d.mp4

ffmpeg -y -i $SEG/a.mp4 -i $SEG/b.mp4 -i $SEG/c.mp4 -i $SEG/d.mp4 -filter_complex \
"[0:v][1:v]xfade=transition=fade:duration=0.5:offset=3.625[x1];\
 [x1][2:v]xfade=transition=fade:duration=0.5:offset=7.25[x2];\
 [x2][3:v]xfade=transition=fade:duration=0.5:offset=10.875,fps=15[v]" \
-map "[v]" -t 15 -c:v libx264 -crf 20 -pix_fmt yuv420p -preset slow "$OUT/master.mp4"
```

For **three** scenes: 5.333 s each (`setpts=1.778*PTS`), dissolve offsets 4.83 and 9.66.

A scene that only needs a gentle move can come from the **real photograph** instead of a
generated clip — truer to the property and free:

```bash
ffmpeg -y -loop 1 -i photo.jpg -t 4.125 \
  -vf "scale=3840:-1,zoompan=z='min(1.0+0.00035*on,1.03)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps=15,format=yuv420p" \
  -an /tmp/seg/b.mp4
```

Confirm the result: `ffprobe -v error -show_entries stream=width,height,r_frame_rate,duration -select_streams v:0 master.mp4`
→ must be 15 fps and 15.000 s.

---

## 5. Build

```bash
cd "<repo>"
python3 build.py \
  --order "~/Documents/LPT Realty/Aperture/Aperture Pack orders/<order>" \
  --overrides overrides/<slug>.json \
  --video ~/Desktop/Aperture-Flow-videos/<Slug>/master.mp4 \
  --out "previews/<slug>"
```

Also build into the order folder itself (drop `--out`) so the delivery lives with the order.

Every unit must print **under cap**. If one is over, the video budget is being squeezed — check
the photos are not oversized.

---

## 6. Verify before showing anyone

This is the step that has cost the most rework. Check **all six sizes at three moments**, not
just the one you changed.

Serve the preview (the review page works from disk, but scripted checks need a server):

```bash
cd previews/<slug>/<Slug>-preview && python3 -m http.server 8000
```

**a. Geometry against the reference.** Because the eyebrow and CTA strings are identical to the
reference's, their measurements should land on the reference's own numbers. Cancel the
animations, then compare `getBoundingClientRect` of the eyebrow mark and text per size against:

| size | mark (x, y, w, h) | eyebrow text |
|---|---|---|
| 300×600 | 37.8, 28.4, 30.7, 33.2 | 80.3, 27.9, 182.2, 33.6 |
| 320×480 | 47.8, 23.4, 30.7, 33.2 | 90.3, 22.9, 182.2, 33.6 |
| 480×320 | 16, 278.2, 18.2, 19.7 | 41.2, 277.9, 108, 19.9 |
| 970×250 | 632.3, 46, 87.7, 95 | 749.5, 45.5, 180.2, 40.2 (line 1 of 2) |
| 768×1024 | 116.8, 65.5, 73, 79.1 | 217.9, 64.3, 433.7, 80.1 |
| 1024×768 | 40, 679, 40.6, 44 | 96.3, 678.4, 241.3, 44.5 |

Anything over ~1.5px out is a bug, not rounding.

**b. The three moments**, at every size:

- **~1.5 s** — eyebrow with the mark, logo not yet in. On 970×250 the headline must *not* be
  visible (that size's beats are exclusive; they overlap otherwise). On 480×320 and 1024×768 the
  eyebrow must clear the blue divider.
- **~4.2 s** — logo in, eyebrow gone, headline and the second subline showing.
- **rest** — headline plus a subline plus the CTA, as in the backup still.

**c. Nothing blank.** Sample the line opacities across a loop; there must be no moment where all
are near zero.

**d. The video is actually playing** — `document.querySelector('video').paused === false`. If
the carousel is showing instead, autoplay was refused *or* the fallback fired early.

**e. Backup stills** — check one at full size. Letter counters must be open, not filled.

**f. Weights** — every unit under 700 KB, excluding `_backup.jpg`.

Compare a backup still side by side with the reference's equivalent before you show anything.
**Copy length is the variable**: every layout bug found so far was invisible with the
reference's short strings and only appeared with real property copy.

---

## 7. Deliver

The order folder gets the full set — `README.md`, `run-report_*.md`, `<Slug>-preview/`, `zips/`.

For the repo: build into `previews/<slug>/`, add a card to the root `index.html`, then commit.

```bash
git add -A && git commit -m "Add <property> digital ads"
```

**Push from GitHub Desktop.** `git push` from the shell fails here with
`could not read Username for 'https://github.com'` — there is no credential helper.

Delete any `_cal.html` / `_m.html` / `_eb.html` harness files before committing.

---

## Traps index

Each of these cost real time. They are all still possible.

| Trap | What happens |
|---|---|
| Naming a file in a Flow prompt | Not attached. Generates something else, charges anyway. Use ⋮ → Animate. |
| "Image A to image B" prompts | Invents architecture between the rooms. One clip per room. |
| Flow quoting extra generations | It plans one clip per transition. Read every quote; never "Always approve". |
| Calibrating type in Pillow | Runs ~17% large. Calibrate against the reference's own strings. |
| `getBoundingClientRect` on SVG `<text>` | Returns the layout box, not the ink. Pixel-scan the stills for vertical checks. |
| A wrapped slot (970×250 eyebrow) | Calibrate against one *line*, not the whole string. |
| CSS `transform` on a positioned SVG group | Replaces the transform attribute; the run jumps to the corner. Keep position on an inner `<g>`. |
| `ImageDraw.polygon` | No winding rule — letter counters fill. XOR the contours, supersample 4×. |
| Autoplay fallback firing early | `currentTime === 0` is not a refusal. Wait for `playing`, retry, allow ~3 s. |
| `<iframe src=>` in the review page | Different origin from `file://`; controls die silently. Use `srcdoc`. |
| Checking only the size you changed | Every layout bug so far was found by the client, not by me. Sweep all six. |
