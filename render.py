#!/usr/bin/env python3
"""
Geometry-accurate renderer for the Aperture display ad units.

Everything positional comes from assets/spec.json, which was measured off the
Parque das Nacoes originals in a browser (getBoundingClientRect with the
animations cancelled, so the boxes are resting positions). Type is set on the
measured baselines in the measured faces:

    headline   Cormorant Garamond Light
    eyebrow    PT Serif Italic
    sublines   Archivo Light, 0.09em tracking
    CTA        Archivo Regular, 0.09em tracking

The HTML unit and the backup still both consume this module, so they cannot
drift apart.
"""

import base64, json, os
from PIL import ImageFont

import outline as O

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FONTS = os.path.join(ASSETS, "fonts")
SPEC = json.load(open(os.path.join(ASSETS, "spec.json"), encoding="utf-8"))

ACCENT = "#4090EF"          # keylines, dots, CTA rule
INK = "#0b0f16"
WHITE = "#ffffff"
MUTED = "#c8d4e2"

# Timeline, lifted from the originals' keyframes (300x600 carousel).
BAND_FADE = 0.8
EYEBROW_IN, EYEBROW_HOLD, EYEBROW_OUT = 0.65, 1.85, 2.6875
LOGO_IN, LOGO_FULL = 2.6875, 3.8875
HEAD_DELAY = 0.65
LOOP_S = 7.5
LINE_DELAY = 0.5
# per-line windows inside the loop, as fractions - the originals' f1/s3/s4 rhythm
LINE_WINDOWS = [(0.0, 0.23833, 0.29167), (0.29167, 0.51, 0.56333), (0.56333, 0.92, 0.97333)]


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name + ".ttf"), max(1, int(round(size))))


def text_width(s, name, size, track_em=0.0):
    if not s:
        return 0.0
    return O.run_width(s, name, size, track_em * size)


def fit(s, name, size, maxw, track_em=0.0, floor=0.62):
    """Shrink only if the copy is wider than the slot the original used."""
    if not maxw:
        return size
    x = float(size)
    while x > size * floor and text_width(s, name, x, track_em) > maxw:
        x -= 0.5
    return round(x, 2)


def slot_for(size_key, slot, s):
    """Resolved draw instructions for one text slot with this property's copy."""
    sp = SPEC[size_key]["slots"].get(slot)
    if not sp or not s:
        return None
    size = fit(s, sp["font"], sp["size"], sp.get("maxw", 0), sp.get("track_em", 0.0))
    return dict(text=s, font=sp["font"], size=size, track=sp.get("track_em", 0.0) * size,
                baseline=sp["baseline"], anchor=sp["anchor"], x=sp["x"],
                width=text_width(s, sp["font"], size, sp.get("track_em", 0.0)))


def b64(name):
    with open(os.path.join(FONTS, name + ".woff2"), "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


FAMILY = {"cormorant-300": ("AGDisplay", 300, "normal"),
          "cormorant-italic": ("AGDisplay", 500, "italic"),
          "archivo-300": ("AGSans", 300, "normal"),
          "archivo-400": ("AGSans", 400, "normal"),
          "archivo-500": ("AGSans", 500, "normal"),
          "archivo-700": ("AGSans", 700, "normal")}

# Cormorant defaults to old-style figures, so a leading house number drops below
# the baseline. The reference sets lining figures.
LINING = {"cormorant-300", "cormorant-italic"}

# The aperture mark that opens the eyebrow, before the full logo replaces it.
# Bbox measured off the reference's own hd1 group, in the mark's own coordinates.
MARK_BBOX = (116.78, 65.43, 73.00, 79.05)   # measured from the rendered mark


def mark_svg():
    return open(os.path.join(ASSETS, "mark-raw.svg"), encoding="utf-8").read().strip()


def eyebrow_parts(size_key, text):
    """Mark + italic text, sized and centred as one unit the way the reference is.

    970x250 is its own shape: an oversized mark with the text set on two lines
    beside it, rather than one line sharing the logo's strip.
    """
    d = slot_for(size_key, "eyebrow", text)
    if not d:
        return None
    sp = SPEC[size_key]["slots"]["eyebrow"]
    m = sp.get("mark") or {}
    f = font(d["font"], d["size"])

    if sp.get("wrap", 1) > 1:
        words = text.split()
        cut = max(1, len(words) // 2)
        lines = [" ".join(words[:cut]), " ".join(words[cut:])] if len(words) > 1 else [text, ""]
        # a wrapped slot is constrained by its longest line, not the whole string
        size = min(fit(ln, sp["font"], sp["size"], sp.get("maxw", 0), sp.get("track_em", 0.0))
                   for ln in lines if ln)
        d = dict(d, size=size)
        f = font(d["font"], size)
        tops = sp["line_top"]
        parts = []
        for i, ln in enumerate(lines):
            if not ln:
                continue
            ink = O.ink_box(ln, d["font"], size, sp.get("track_em", 0.0) * size)
            parts.append(dict(d, text=ln, anchor="start", x=sp["x"],
                              baseline=tops[i] - ink[1],
                              width=text_width(ln, d["font"], size, sp.get("track_em", 0.0))))
        mb = sp["mark_box"]
        return parts, dict(tx=mb[0] - MARK_BBOX[0] * (mb[3] / MARK_BBOX[3]),
                           ty=mb[1] - MARK_BBOX[1] * (mb[3] / MARK_BBOX[3]),
                           s=mb[3] / MARK_BBOX[3])

    # where the eyebrow shares a row with the divider, the whole assembly - mark,
    # gap and text - has to fit the space before it, not just the text
    limit = sp.get("assembly_maxw")
    if limit:
        size = d["size"]
        while size > sp["size"] * 0.55:
            sc = (size * m.get("h_ratio", 1.0)) / MARK_BBOX[3]
            w = (MARK_BBOX[2] * sc + m.get("gap_em", 0.355) * size
                 + text_width(text, d["font"], size, sp.get("track_em", 0.0)))
            if w <= limit:
                break
            size -= 0.5
        d = dict(d, size=round(size, 2),
                 width=text_width(text, d["font"], size, sp.get("track_em", 0.0)))
        f = font(d["font"], d["size"])

    ink = O.ink_box(text, d["font"], d["size"], d["track"])
    top = d["baseline"] + ink[1]          # the mark's top sits on the text's ink top
    scale = (d["size"] * m.get("h_ratio", 1.0)) / MARK_BBOX[3]
    mw = MARK_BBOX[2] * scale
    gap = m.get("gap_em", 0.355) * d["size"]
    total = mw + gap + d["width"]
    left = d["x"] - total / 2 if d["anchor"] == "middle" else d["x"]
    d = dict(d, anchor="start", x=left + mw + gap)
    return [d], dict(tx=left - MARK_BBOX[0] * scale, ty=top - MARK_BBOX[1] * scale, s=scale)


def font_faces(names):
    out = []
    for n in sorted(set(names)):
        fam, wt, style = FAMILY[n]
        out.append("@font-face{font-family:%s;font-weight:%d;font-style:%s;font-display:block;"
                   "src:url(data:font/woff2;base64,%s) format('woff2')}" % (fam, wt, style, b64(n)))
    return "\n  ".join(out)


def svg_text(el_id, d, fill, extra=""):
    """A run baked to outlines - no webfont, nothing for a shaping engine to change.

    The id'd wrapper carries no transform of its own: the CSS animations set
    `transform`, which would replace an SVG transform attribute on the same
    element and drop the run to the unit's top-left corner. Positioning lives on
    an inner group the animations never touch.
    """
    x = d["x"] - d["width"] / 2 if d["anchor"] == "middle" else d["x"]
    path, _, _ = O.svg_path(d["text"], d["font"], d["size"], d["track"])
    return ('<g id="%s"><g transform="translate(%.2f %.2f)">'
            '<path d="%s" fill="%s"/></g></g>'
            % (el_id, x, d["baseline"], path, fill))


def keylines(size_key):
    return "".join('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                   % (x, y, w, h, ACCENT) for x, y, w, h in SPEC[size_key]["rules"])


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
