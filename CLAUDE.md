# Working in this repo

Builder for Aperture Global HTML5 display ad units.

**Building a property's ads? Follow [`RUNBOOK.md`](RUNBOOK.md) start to finish.** It is the
end-to-end process — photo choice, overrides, Flow prompts, ffmpeg assembly, build, the
verification sweep, delivery — and it lists the traps that have actually bitten. Do not
improvise around it.

`README.md` describes what the builder makes and how it is put together.

## The one rule

The Parque das Nações set in `~/Downloads/ParqueDasNacoes-EN-PT-review/` is the reference, and
its `README.md` is the spec. **Reproduce it. Do not redesign it.** Every visual decision in the
units is measured off that set and lives in `assets/spec.json`. If something looks wrong,
measure the reference and compare — do not adjust by eye.

## Build

```bash
python3 build.py --order "<Aperture Pack orders>/<order folder>" \
                 --overrides overrides/<slug>.json \
                 --video <master>.mp4 \
                 --out "previews/<slug>"
```

Needs Python 3 + Pillow + fontTools + ffmpeg.

## House rules

- **Cormorant Garamond** (headline, and Medium Italic for the eyebrow) and **Archivo**
  (sublines, CTA). Never Playfair, never Poppins.
- **The eyebrow is always "Exclusive Offer"**, not the CSV `tagline`.
- Copy is **baked to vector outlines** — the units carry no webfonts. Do not reintroduce
  `@font-face`; it brings back the metric-mismatch bugs.
- Copy comes from the order's Power Pack CSV. Change it in `overrides/<slug>.json`, never by
  editing the CSV.
- Review `lines` and `photos` on every order — both defaults produce output that looks fine in
  the run log and wrong in the unit.
- **A photo with no clip yet goes in the carousel, not the video.** Never pad the master with a
  still standing in for a clip that has not been generated — build it from the scenes you have.
- Every unit stays under the 700 KB cap.
- Verify **all six sizes at three moments** before showing anyone. Every layout bug so far was
  caught by the client, not by the build.

## Pushing

`git push` from the shell fails — no credential helper. Commit here, push from GitHub Desktop.
