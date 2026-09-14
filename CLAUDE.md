# Working in this repo

Builder for Aperture Global HTML5 display ad units. `README.md` is the routine — read it
before changing anything.

## Build

```bash
python3 build.py --order "<Aperture Pack orders>/<order folder>" \
                 --overrides overrides/<slug>.json \
                 --out "previews/<slug>"
```

Needs Python 3 + Pillow. Nothing else; no node, no build step, no server.

## House rules

- **Archivo** is the Aperture sans and **Playfair Display** the display serif. Never
  substitute another face — Poppins in particular is not an Aperture font.
- Copy comes from the order's Power Pack CSV. Change it in `overrides/<slug>.json`, never by
  editing the CSV — that belongs to the Power Pack routine.
- Review `lines` and `photos` on every order. Both defaults produce output that looks
  plausible in the run log and wrong in the unit; the README says why.
- Every unit must stay under the 700 KB cap. The builder prints the weight and flags
  breaches; do not ship a flagged unit.
- `assets/` is brand furniture recovered from the Parque das Nações reference set. Treat it
  as fixed — regenerating it is not possible from this repo alone.
- After adding a property, add its card to the root `index.html`.

## Verifying a change

Open `previews/<slug>/<Slug>-preview/index.html` and scrub a unit. The review page drives
both the CSS copy animations and the photo band through each unit's `window.__ad` hook; if
a card reads "ad not ready", the hook or the animation set-up is broken.
