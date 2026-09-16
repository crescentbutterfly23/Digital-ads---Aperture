#!/usr/bin/env python3
"""
Text -> vector outlines, the way the reference set does it.

The reference bakes every line of copy to paths so the units carry no webfonts
and render identically everywhere. That also removes the failure mode that cost
this build several rounds: with outlines there is no shaping engine, so the
browser and the still renderer cannot disagree about metrics.

Outlined runs are cached in assets/outlines/, keyed by font+size+tracking+text,
so re-running a property - or building the next one, which reuses the same CTA
and eyebrow - costs nothing.
"""

import hashlib, json, os
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "assets", "fonts")
CACHE_DIR = os.path.join(HERE, "assets", "outlines")

_fonts = {}


def _font(name):
    if name not in _fonts:
        f = TTFont(os.path.join(FONTS, name + ".ttf"))
        _fonts[name] = (f, f.getGlyphSet(), f["head"].unitsPerEm,
                        f.getBestCmap(), f["hmtx"])
    return _fonts[name]


class _SvgPen(BasePen):
    """Emits SVG path data, scaled and offset into unit coordinates."""

    def __init__(self, glyphSet, scale, dx, dy):
        BasePen.__init__(self, glyphSet)
        self.s, self.dx, self.dy, self.d = scale, dx, dy, []

    def _pt(self, p):
        return (p[0] * self.s + self.dx, -p[1] * self.s + self.dy)

    def _moveTo(self, p):
        x, y = self._pt(p); self.d.append("M%.2f %.2f" % (x, y))

    def _lineTo(self, p):
        x, y = self._pt(p); self.d.append("L%.2f %.2f" % (x, y))

    def _curveToOne(self, a, b, c):
        (ax, ay), (bx, by), (cx, cy) = self._pt(a), self._pt(b), self._pt(c)
        self.d.append("C%.2f %.2f %.2f %.2f %.2f %.2f" % (ax, ay, bx, by, cx, cy))

    def _closePath(self):
        self.d.append("Z")


class _PolyPen(BasePen):
    """Flattens the same outlines to polygons, for the backup still."""

    def __init__(self, glyphSet, scale, dx, dy, steps=12):
        BasePen.__init__(self, glyphSet)
        self.s, self.dx, self.dy, self.steps = scale, dx, dy, steps
        self.polys, self.cur, self.last = [], [], (0, 0)

    def _pt(self, p):
        return (p[0] * self.s + self.dx, -p[1] * self.s + self.dy)

    def _moveTo(self, p):
        if len(self.cur) > 2:
            self.polys.append(self.cur)
        self.cur = [self._pt(p)]; self.last = p

    def _lineTo(self, p):
        self.cur.append(self._pt(p)); self.last = p

    def _curveToOne(self, a, b, c):
        p0 = self.last
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            x = (u ** 3 * p0[0] + 3 * u * u * t * a[0] + 3 * u * t * t * b[0] + t ** 3 * c[0])
            y = (u ** 3 * p0[1] + 3 * u * u * t * a[1] + 3 * u * t * t * b[1] + t ** 3 * c[1])
            self.cur.append(self._pt((x, y)))
        self.last = c

    def _closePath(self):
        if len(self.cur) > 2:
            self.polys.append(self.cur)
        self.cur = []

    def done(self):
        if len(self.cur) > 2:
            self.polys.append(self.cur)
        return self.polys


def advances(text, name, size, track=0.0):
    """Pen positions for each character, and the run's total advance width."""
    f, gs, upem, cmap, hmtx = _font(name)
    k = size / upem
    xs, x = [], 0.0
    for ch in text:
        g = cmap.get(ord(ch))
        xs.append((g, x))
        if g:
            x += hmtx[g][0] * k
        x += track
    if text:
        x -= track
    return xs, x


def run_width(text, name, size, track=0.0):
    return advances(text, name, size, track)[1]


def ink_box(text, name, size, track=0.0):
    """Ink bounds of the run relative to its origin (x, baseline)."""
    f, gs, upem, cmap, hmtx = _font(name)
    k = size / upem
    x0 = y0 = 1e9
    x1 = y1 = -1e9
    for g, ox in advances(text, name, size, track)[0]:
        if not g or g not in gs:
            continue
        pen = _PolyPen(gs, k, ox, 0.0)
        gs[g].draw(pen)
        for poly in pen.done():
            for px, py in poly:
                x0, y0 = min(x0, px), min(y0, py)
                x1, y1 = max(x1, px), max(y1, py)
    if x0 > x1:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0, y0, x1 - x0, y1 - y0)


def _key(text, name, size, track):
    return hashlib.sha1(("%s|%.3f|%.4f|%s" % (name, size, track, text))
                        .encode("utf-8")).hexdigest()[:16]


def svg_path(text, name, size, track=0.0, x=0.0, baseline=0.0, cache=True):
    """One <path> d-string for the whole run, positioned in unit coordinates."""
    ck = _key(text, name, size, track)
    path = os.path.join(CACHE_DIR, ck + ".json")
    if cache and os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))["d"]
    else:
        f, gs, upem, cmap, hmtx = _font(name)
        k = size / upem
        out = []
        for g, ox in advances(text, name, size, track)[0]:
            if not g or g not in gs:
                continue
            pen = _SvgPen(gs, k, ox, 0.0)
            gs[g].draw(pen)
            out.extend(pen.d)
        d = "".join(out)
        if cache:
            os.makedirs(CACHE_DIR, exist_ok=True)
            json.dump(dict(font=name, size=size, track=track, text=text, d=d),
                      open(path, "w", encoding="utf-8"))
    return d, x, baseline


def polygons(text, name, size, track=0.0, x=0.0, baseline=0.0):
    """The same outlines as filled polygons, for the backup still."""
    f, gs, upem, cmap, hmtx = _font(name)
    k = size / upem
    polys = []
    for g, ox in advances(text, name, size, track)[0]:
        if not g or g not in gs:
            continue
        pen = _PolyPen(gs, k, x + ox, baseline)
        gs[g].draw(pen)
        polys.extend(pen.done())
    return polys
