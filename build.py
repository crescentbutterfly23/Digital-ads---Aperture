#!/usr/bin/env python3
"""
Aperture Global - HTML5 display ad builder (carousel units).

Builds a full set of self-contained HTML5 carousel ad units for one property,
plus backup stills, a local preview page and per-unit zips.

Reproduces the layout, palette, motion and behaviour of the Parque das Nacoes
set, but sets the property copy as live text (embedded OFL webfonts) instead of
outlined Figma paths, so a set can be built for any order straight from its
Power Pack CSV.

  python3 build.py --order "<order folder>" [--out <dir>] [--overrides o.json]

See README.md for the full routine.
"""

import argparse, base64, csv, datetime, glob, io, json, os, re, shutil, sys, zipfile
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FONTS = os.path.join(ASSETS, "fonts")

# ---------------------------------------------------------------- brand ----

INK        = "#0b0f16"   # unit background
WHITE      = "#ffffff"
MUTED      = "#c8d4e2"   # subline
EYEBROW    = "#9fb4cc"
ACCENT     = "#4090EF"   # Aperture blue - dots, CTA rule, hover
CLICKTAG   = "https://www.apertureglobal.com/"
LOOP_S     = 7.5         # one copy cycle; the unit runs two per 15s loop
CTA_TEXT   = "Schedule a viewing"

# Logo master art lives in assets/logo-master.svg in this coordinate box.
LOGO_BBOX = (166.00, 49.39, 430.77, 96.46)   # x, y, w, h

# Per-size geometry. band = photo band rect. logo = (scale, tx, ty) applied to
# the logo master. The scale/translate pairs are lifted from the Parque units so
# the logo lands exactly where it did there; 970x250 is derived to match.
SIZES = {
    "300x600": dict(
        band=(0, 90, 300, 300), logo=(0.4200, -10.19, 4.01),
        mode="stack", col=(0, 390, 300, 210), pad=14,
        fs=dict(h=28, sub=11.5, eye=9.5, cta=13)),
    "320x480": dict(
        band=(0, 80, 320, 200), logo=(0.4200, -0.19, -0.99),
        mode="stack", col=(0, 280, 320, 200), pad=14,
        fs=dict(h=27, sub=11, eye=9.5, cta=12.5)),
    "768x1024": dict(
        band=(0, 194, 768, 473), logo=(1.0000, 2.60, 7.40),
        mode="stack", col=(0, 667, 768, 357), pad=36,
        fs=dict(h=60, sub=23, eye=19, cta=26)),
    "970x250": dict(
        band=(0, 0, 592, 250), logo=(0.4016, 627.33, 11.17),
        mode="stack", col=(592, 78, 378, 172), pad=20,
        fs=dict(h=30, sub=13, eye=10.5, cta=14)),
    "480x320": dict(
        band=(0, 0, 480, 256), logo=(0.3089, -35.27, 257.85),
        mode="bar", col=(0, 256, 480, 64), pad=12,
        fs=dict(h=17, sub=8.5, eye=8, cta=11)),
    "1024x768": dict(
        band=(0, 0, 1024, 634), logo=(0.6902, -74.57, 633.64),
        mode="bar", col=(0, 634, 1024, 134), pad=26,
        fs=dict(h=34, sub=15, eye=13, cta=20)),
}
SIZE_ORDER = ["768x1024", "1024x768", "480x320", "970x250", "320x480", "300x600"]

WEIGHT_CAP = 700 * 1024   # per unit, uncompressed payload

# ------------------------------------------------------------ copy model ----


def _money(v):
    try:
        n = int(float(str(v).replace(",", "").replace("$", "")))
    except (TypeError, ValueError):
        return ""
    return "${:,}".format(n)


def _num(v):
    s = str(v or "").strip()
    return s if s and s not in ("0", "0.0") else ""


def _bath(v):
    s = _num(v)
    if not s:
        return ""
    f = float(s)
    return str(int(f)) if f == int(f) else str(f)


def read_csv(order_dir):
    """Newest property_data_*.csv in the order's CSV folder."""
    hits = sorted(glob.glob(os.path.join(order_dir, "CSV", "property_data_*.csv")))
    if not hits:
        sys.exit("no property_data_*.csv under %s/CSV" % order_dir)

    def ver(p):
        m = re.search(r"_v(\d+)\.csv$", p)
        return int(m.group(1)) if m else 0
    path = max(hits, key=ver)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        row = next(csv.DictReader(fh))
    return path, row


def build_copy(row, ov):
    """Ad copy from the Power Pack row, with per-property overrides on top."""
    spec = " | ".join(x for x in [
        (_num(row.get("bedrooms")) + " br") if _num(row.get("bedrooms")) else "",
        (_bath(row.get("bathrooms")) + " bth") if _bath(row.get("bathrooms")) else "",
        ("{:,} sqft".format(int(float(row["sqft"]))) if _num(row.get("sqft")) else ""),
    ] if x)

    agent = (row.get("name") or "").strip()
    copy = dict(
        eyebrow=(row.get("tagline") or "Premier Offering").strip(),
        headline=(row.get("street") or "").strip(),
        location=(row.get("cityState") or "").strip(),
        spec=spec,
        agent=("Listed by " + agent) if agent else "",
        price=_money(row.get("price")),
        cta=CTA_TEXT,
        clicktag=CLICKTAG,
    )
    copy.update({k: v for k, v in ov.items() if k in copy})
    # the three rotating sublines, in order; overridable wholesale
    lines = ov.get("lines") or [copy["location"], copy["spec"], copy["agent"]]
    copy["lines"] = [re.sub(r"\s+", " ", l).strip() for l in lines if l] \
        or [copy["location"]]
    return copy


# --------------------------------------------------------------- layout ----

PHOTO_PRIORITY = ["exterior", "living", "kitchen", "master", "outdoor",
                  "dining", "entry", "amenities", "interior"]


def pick_photos(order_dir, given):
    if given:
        return given
    for sub in ("out/previews", "out/print", "out"):
        d = os.path.join(order_dir, sub)
        if not os.path.isdir(d):
            continue
        files = [os.path.join(d, f) for f in sorted(os.listdir(d))
                 if f.lower().endswith((".jpg", ".jpeg", ".png"))
                 and not f.startswith("floorplan")]
        if len(files) < 4:
            continue
        out, used = [], set()
        for slug in PHOTO_PRIORITY:                     # one per room type first
            for f in files:
                base = os.path.basename(f)
                if base.startswith(slug) and slug not in used:
                    out.append(f); used.add(slug); break
            if len(out) == 4:
                return out
        for f in files:
            if f not in out:
                out.append(f)
            if len(out) == 4:
                return out
    sys.exit("could not find four usable photos under %s" % order_dir)



def _pil(kind, size):
    name = {"serif": "playfair-display-500", "sans300": "archivo-300",
            "sans500": "archivo-500"}[kind]
    return ImageFont.truetype(os.path.join(FONTS, name + ".ttf"), max(1, int(round(size))))


def measure(text, kind, size, track=0.0):
    """Rendered width in px, tracking included."""
    if not text:
        return 0.0
    w = _pil(kind, size).getlength(text)
    return w + track * max(0, len(text) - 1)


def fit_size(text, kind, size, maxw, track=0.0, floor=0.68):
    """Largest size <= the design size whose line still fits maxw."""
    s = float(size)
    while s > size * floor and measure(text, kind, s, track * s / size) > maxw:
        s -= 0.5
    return round(s, 2)

def layout(size, copy):
    """Absolute draw list shared by the HTML unit and the backup still."""
    W, H = (int(n) for n in size.split("x"))
    cfg = SIZES[size]
    cx, cy, cw, ch = cfg["col"]
    fs, pad = cfg["fs"], cfg["pad"]
    items = []

    if cfg["mode"] == "stack":
        mid = cx + cw / 2
        eye_y = cy + ch * 0.09
        h_y = cy + ch * 0.19
        sub_y = h_y + fs["h"] * 1.72
        cta_y = cy + ch - ch * 0.26
        items.append(dict(id="eyebrow", text=copy["eyebrow"].upper(), font="sans",
                          weight=500, size=fs["eye"], color=EYEBROW, align="center",
                          x=mid, y=eye_y, track=0.18 * fs["eye"], maxw=cw - 2 * pad))
        items.append(dict(id="headline", text=copy["headline"], font="serif",
                          weight=500, size=fs["h"], color=WHITE, align="center",
                          x=mid, y=h_y, track=0, maxw=cw - 2 * pad))
        for i, line in enumerate(copy["lines"]):
            items.append(dict(id="line%d" % i, text=line, font="sans", weight=300,
                              size=fs["sub"], color=MUTED, align="center",
                              x=mid, y=sub_y, track=0, maxw=cw - 2 * pad))
        cta = dict(size=fs["cta"], align="center", x=mid, y=cta_y,
                   w=cw - 2 * pad, left=cx + pad, right=cx + cw - pad)
    else:  # bar: logo | rule | headline+subline | CTA
        s, tx, _ty = cfg["logo"]
        logo_right = tx + (LOGO_BBOX[0] + LOGO_BBOX[2]) * s
        gap = pad * 1.6
        rule_x = logo_right + gap
        text_x = rule_x + gap
        cta_w = fs["cta"] * 11
        cta_right = W - pad * 1.4
        cta_left = cta_right - cta_w
        h_y = cy + ch * 0.22
        sub_y = h_y + fs["h"] * 1.35
        items.append(dict(id="rule", kind="vrule", x=rule_x,
                          y=cy + ch * 0.22, y2=cy + ch * 0.78, color="#3a4657"))
        items.append(dict(id="headline", text=copy["headline"], font="serif",
                          weight=500, size=fs["h"], color=WHITE, align="left",
                          x=text_x, y=h_y, track=0, maxw=cta_left - text_x - gap))
        for i, line in enumerate(copy["lines"]):
            items.append(dict(id="line%d" % i, text=line, font="sans", weight=300,
                              size=fs["sub"], color=MUTED, align="left",
                              x=text_x, y=sub_y, track=0,
                              maxw=cta_left - text_x - gap))
        cta = dict(size=fs["cta"], align="center", x=(cta_left + cta_right) / 2,
                   y=cy + ch * 0.38, w=cta_w, left=cta_left, right=cta_right)
    for it in items:
        if it.get("kind"):
            continue
        kind = "serif" if it["font"] == "serif" else (
            "sans500" if it["weight"] >= 500 else "sans300")
        it["size"] = fit_size(it["text"], kind, it["size"], it["maxw"],
                              it.get("track", 0))
        it["w"] = measure(it["text"], kind, it["size"],
                          it.get("track", 0) * it["size"] / max(it["size"], 1))
    cta["text_w"] = measure(copy["cta"], "sans500", cta["size"])
    return dict(W=W, H=H, cfg=cfg, items=items, cta=cta)



def validate(size, copy, lay):
    """Warn about copy that outgrows its slot - the two things that actually
    break a unit are an overflowing line and a line landing on the photo band."""
    cfg = lay["cfg"]
    bx, by, bw, bh = cfg["band"]
    out = []
    for it in lay["items"]:
        if it.get("kind"):
            continue
        kind = "serif" if it["font"] == "serif" else (
            "sans500" if it["weight"] >= 500 else "sans300")
        w = measure(it["text"], kind, it["size"], it.get("track", 0))
        if w > it["maxw"] + 0.6:
            out.append("%s overflows its column (%.0f > %.0fpx)"
                       % (it["id"], w, it["maxw"]))
        left = {"center": it["x"] - w / 2, "left": it["x"],
                "right": it["x"] - w}[it["align"]]
        overlap_x = left < bx + bw and left + w > bx
        overlap_y = it["y"] < by + bh and it["y"] + it["size"] * 1.2 > by
        if overlap_x and overlap_y:
            out.append("%s sits on the photo band" % it["id"])
    if lay["cta"]["y"] + lay["cta"]["size"] * 2.2 > lay["H"]:
        out.append("the CTA rule falls outside the unit")
    return out

# ----------------------------------------------------------------- HTML ----

def b64font(name):
    with open(os.path.join(FONTS, name + ".woff2"), "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def text_css(it):
    align = {"center": "center", "left": "left", "right": "right"}[it["align"]]
    fam = "AGSerif" if it["font"] == "serif" else "AGSans"
    left = {"center": it["x"] - it["maxw"] / 2, "left": it["x"],
            "right": it["x"] - it["maxw"]}[it["align"]]
    return ("position:absolute;left:%.2fpx;top:%.2fpx;width:%.2fpx;"
            "font-family:%s;font-weight:%d;font-size:%.2fpx;line-height:1.12;"
            "color:%s;text-align:%s;letter-spacing:%.3fpx;white-space:nowrap;"
            % (left, it["y"], it["maxw"], fam, it["weight"], it["size"],
               it["color"], align, it.get("track", 0)))


def build_html(size, copy, lay, prefix, nphotos=4):
    W, H, cfg = lay["W"], lay["H"], lay["cfg"]
    bx, by, bw, bh = cfg["band"]
    s, tx, ty = cfg["logo"]
    logo = open(os.path.join(ASSETS, "logo-master.svg"), encoding="utf-8").read().strip()
    cta = lay["cta"]
    nlines = len(copy["lines"])
    seg = 100.0 / max(nlines, 1)

    # rotating subline keyframes: each line slides in, holds, slides out
    kf = []
    for i in range(nlines):
        a, b = i * seg, (i + 1) * seg
        fade = min(4.0, seg / 4)
        kf.append(
            "@keyframes kf_line%d{0%%,%.3f%%{opacity:0;transform:translateX(-24px)}"
            "%.3f%%{opacity:1;transform:translateX(0)}"
            "%.3f%%{opacity:1;transform:translateX(0)}"
            "%.3f%%,100%%{opacity:0;transform:translateX(24px)}}"
            % (i, a, min(a + fade, b), max(b - fade, a), b))

    texts = []
    li = 0
    for it in lay["items"]:
        if it.get("kind") == "vrule":
            texts.append('<div style="position:absolute;left:%.2fpx;top:%.2fpx;'
                         'width:1px;height:%.2fpx;background:%s"></div>'
                         % (it["x"], it["y"], it["y2"] - it["y"], it["color"]))
            continue
        anim = ""
        if it["id"] == "eyebrow":
            anim = "animation:kf_eyebrow %.3fs linear 1 forwards;opacity:0;" % LOOP_S
        elif it["id"].startswith("line"):
            anim = ("animation:kf_line%d %.3fs linear infinite;opacity:0;"
                    % (li, LOOP_S)); li += 1
        elif it["id"] == "headline":
            anim = "animation:kf_in .7s cubic-bezier(.5,0,.3,1) .55s 1 both;opacity:0;"
        texts.append('<div id="%s" style="%s%s">%s</div>'
                     % (it["id"], text_css(it), anim, esc(it["text"])))

    photos = "".join(
        '<img src="%s_photo%d.jpg" alt="%s %d">' % (prefix, i + 1,
                                                    esc(copy["headline"]), i + 1)
        for i in range(nphotos))
    dots = "".join('<button type="button" class="%s" aria-label="Image %d"></button>'
                   % ("on" if i == 0 else "", i + 1) for i in range(nphotos))

    return TEMPLATE % dict(
        W=W, H=H, size=size, title=esc(copy["headline"]), clicktag=copy["clicktag"],
        ink=INK, accent=ACCENT, bx=bx, by=by, bw=bw, bh=bh, prefix=prefix,
        serif=b64font("playfair-display-500"), sans300=b64font("archivo-300"),
        sans500=b64font("archivo-500"), loop=LOOP_S,
        logo_t="translate(%.2f %.2f) scale(%.4f)" % (tx, ty, s), logo=logo,
        kf="\n".join(kf), texts="\n  ".join(texts), photos=photos, dots=dots,
        cta_text=esc(copy["cta"]), cta_left=cta["left"], cta_right=cta["right"],
        cta_y=cta["y"], cta_size=cta["size"], cta_w=cta["w"],
        cta_mid=cta["x"], rule_w=cta["text_w"] + cta["size"] * 1.6,
        swipe=48 if W >= 480 else 34)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="ad.size" content="width=%(W)d,height=%(H)d">
<title>Aperture &middot; %(title)s &middot; %(size)s carousel</title>
<script type="text/javascript">
  var clickTag = "%(clicktag)s";
</script>
<script type="text/javascript">
  (function () { var m = /[?&]clicktag=([^&#]*)/i.exec(window.location.search); if (m) { try { clickTag = decodeURIComponent(m[1]); } catch (e) {} } })();
</script>
<style>
  @font-face { font-family:AGSerif; font-weight:500; font-display:block;
    src:url(data:font/woff2;base64,%(serif)s) format('woff2'); }
  @font-face { font-family:AGSans; font-weight:300; font-display:block;
    src:url(data:font/woff2;base64,%(sans300)s) format('woff2'); }
  @font-face { font-family:AGSans; font-weight:500; font-display:block;
    src:url(data:font/woff2;base64,%(sans500)s) format('woff2'); }
  :root { color-scheme: dark; }
  html, body { margin:0; padding:0; background:%(ink)s; overflow:hidden; }
  #ad { position:relative; width:%(W)dpx; height:%(H)dpx; overflow:hidden;
        background:%(ink)s url(%(prefix)s_bg.jpg) 0 0/%(W)dpx %(H)dpx no-repeat;
        font-family:AGSans, Helvetica, Arial, sans-serif; }
  #ad > svg.logo { position:absolute; inset:0; width:100%%; height:100%%; pointer-events:none;
        opacity:0; animation: kf_fade .8s linear .9s 1 forwards; }
  #band { position:absolute; left:%(bx)dpx; top:%(by)dpx; width:%(bw)dpx; height:%(bh)dpx;
        overflow:hidden; background:#000; opacity:0; animation: kf_fade .8s linear 1 forwards; }
  #track { position:absolute; left:0; top:0; height:%(bh)dpx; display:flex; will-change:transform;
        transition: transform .7s cubic-bezier(0.5,0,0.3,1); }
  #track img { width:%(bw)dpx; height:%(bh)dpx; object-fit:cover; flex:0 0 %(bw)dpx; display:block; }
  #band::before { content:""; position:absolute; inset:0; background:rgba(0,0,0,.2); pointer-events:none; z-index:2; }
  #band::after  { content:""; position:absolute; inset:0; box-shadow: inset 0 4px 4px rgba(0,0,0,.25); pointer-events:none; z-index:2; }
  .nav { position:absolute; top:50%%; width:30px; height:30px; margin-top:-15px; border:0; border-radius:50%%;
        background:rgba(11,15,22,.55); color:#fff; cursor:pointer; z-index:5; display:flex; align-items:center;
        justify-content:center; padding:0; transition: background .2s; }
  .nav:hover { background:rgba(64,144,239,.85); }
  .nav svg { width:12px; height:12px; display:block; }
  #prev { left:8px; } #next { right:8px; }
  #dots { position:absolute; left:0; right:0; bottom:8px; display:flex; justify-content:center; gap:6px; z-index:5; }
  #dots button { width:7px; height:7px; border-radius:50%%; border:1px solid rgba(255,255,255,.8);
        background:transparent; padding:0; cursor:pointer; transition: background .2s; }
  #dots button.on { background:%(accent)s; border-color:%(accent)s; }
  #swipe { position:absolute; left:50%%; top:50%%; width:128px; height:80px; margin:-40px 0 0 -64px; z-index:5;
        display:none; pointer-events:none; filter:drop-shadow(0 3px 8px rgba(0,0,0,.6)); opacity:.6; transition:opacity .4s; }
  #swipe svg { width:100%%; height:100%%; animation: kf_swipe 2.2s cubic-bezier(0.45,0,0.2,1) infinite; }
  #copy { position:absolute; inset:0; pointer-events:none; }
  #copy > div { transform-origin:0 0; }
  #cta { position:absolute; left:%(cta_left).2fpx; top:%(cta_y).2fpx; width:%(cta_w).2fpx;
        text-align:center; font-family:AGSans; font-weight:500; font-size:%(cta_size).2fpx;
        color:#fff; letter-spacing:.2px; white-space:nowrap;
        animation: kf_bob 1.9s ease-in-out infinite; }
  #cta i { display:block; height:1.5px; width:%(rule_w).2fpx; margin:.45em auto 0; background:%(accent)s; }
  #clickthrough { position:absolute; left:%(cta_left).2fpx; top:%(cta_y).2fpx; width:%(cta_w).2fpx;
        height:%(cta_size).2fpx; margin-top:-4px; padding:6px 0 10px; z-index:6; cursor:pointer;
        display:block; text-decoration:none; }
  @keyframes kf_fade { 0%% { opacity:0; } 100%% { opacity:1; } }
  @keyframes kf_in { 0%% { opacity:0; transform:translateX(-28px); } 100%% { opacity:1; transform:translateX(0); } }
  @keyframes kf_bob { 0%%,100%% { transform:translateY(0); } 50%% { transform:translateY(-2px); } }
  @keyframes kf_eyebrow { 0%% { opacity:0; } 8%% { opacity:1; } 30%% { opacity:1; } 40%%,100%% { opacity:0; } }
  @keyframes kf_swipe { 0%% { transform:translate(-%(swipe)dpx,6px) rotate(-10deg); } 22%% { transform:translate(0,-6px) rotate(0deg); }
        45%% { transform:translate(%(swipe)dpx,4px) rotate(9deg); } 60%% { transform:translate(%(swipe)dpx,4px) rotate(9deg); }
        100%% { transform:translate(-%(swipe)dpx,6px) rotate(-10deg); } }
%(kf)s
  @media (prefers-reduced-motion: reduce) {
    #copy > div, #cta, #swipe svg { animation:none !important; opacity:1 !important; transform:none !important; }
    #copy > div[id^="line"]:not(#line0) { display:none; }
  }
</style>
</head>
<body>
<div id="ad">
  <div id="band" aria-roledescription="carousel">
    <div id="track">%(photos)s</div>
    <button class="nav" id="prev" type="button" aria-label="Previous image"><svg viewBox="0 0 18 18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.5 3.5 6 9l5.5 5.5"/></svg></button>
    <button class="nav" id="next" type="button" aria-label="Next image"><svg viewBox="0 0 18 18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5 12 9l-5.5 5.5"/></svg></button>
    <div id="dots">%(dots)s</div>
    <div id="swipe" aria-hidden="true"><svg viewBox="0 0 64 40" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 20 3 14m0 6 6 6M3 20h10"/><path d="M55 20l6-6m0 6-6 6M61 20H51"/><path d="M27 32V13.5a2.5 2.5 0 0 1 5 0V22m0-3a2.5 2.5 0 0 1 5 0v3m0-2a2.5 2.5 0 0 1 5 0v2m0-1a2.5 2.5 0 0 1 5 0v6c0 4.5-3 8.5-8 8.5h-5c-3.5 0-5.5-1.5-7.5-4.5L23 25.5a2.4 2.4 0 0 1 4-2.5"/></svg></div>
  </div>
  <svg class="logo" viewBox="0 0 %(W)d %(H)d" fill="none" xmlns="http://www.w3.org/2000/svg"><g transform="%(logo_t)s">
%(logo)s
  </g></svg>
  <div id="copy">
  %(texts)s
  </div>
  <div id="cta">%(cta_text)s<i></i></div>
  <a id="clickthrough" href="javascript:window.open(window.clickTag)" aria-label="%(cta_text)s - Aperture Global Real Estate"></a>
</div>
<script>
(function () {
  var track = document.getElementById('track'),
      imgs  = track.getElementsByTagName('img'),
      dots  = document.getElementById('dots').getElementsByTagName('button'),
      swipe = document.getElementById('swipe'),
      w     = %(bw)d, n = imgs.length, i = 0, manual = false, timer;

  function go(k, byHand) {
    i = (k + n) %% n;
    track.style.transform = 'translateX(' + (-i * w) + 'px)';
    for (var d = 0; d < dots.length; d++) dots[d].className = (d === i ? 'on' : '');
    if (byHand) { manual = true; if (swipe) swipe.style.display = 'none'; restart(); }
  }
  function restart() { clearInterval(timer); timer = setInterval(function () { go(i + 1); }, %(loop)s * 1000 / n); }

  document.getElementById('prev').onclick = function (e) { e.stopPropagation(); go(i - 1, true); };
  document.getElementById('next').onclick = function (e) { e.stopPropagation(); go(i + 1, true); };
  for (var d = 0; d < dots.length; d++) (function (k) {
    dots[k].onclick = function (e) { e.stopPropagation(); go(k, true); };
  })(d);

  var x0 = null;
  track.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  track.addEventListener('touchend', function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 30) go(i + (dx < 0 ? 1 : -1), true);
    x0 = null;
  }, { passive: true });

  if (swipe && ('ontouchstart' in window)) {
    swipe.style.display = 'block';
    setTimeout(function () { if (!manual && swipe) swipe.style.display = 'none'; }, 6000);
  }
  restart();

  // Review hook. The preview page uses this to scrub the photo band in step with
  // the copy animations; it is inert in a live placement.
  window.__ad = {
    loop: %(loop)s * 1000,
    slides: n,
    setTime: function (ms) { go(Math.floor((ms %% this.loop) / (this.loop / n))); },
    pause: function () { clearInterval(timer); },
    play: function () { restart(); }
  };
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------- images ----

def fit(src, w, h, quality):
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    im = im.resize((max(w, int(sw * scale + .5)), max(h, int(sh * scale + .5))),
                   Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((l, t, l + w, t + h))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=False)
    return im, buf.getvalue()


def pil_font(kind, size):
    return _pil(kind, size)


def backup_still(size, copy, lay, band_photo, bg_path):
    """The unit's end frame, flattened - for placements that need a static."""
    W, H, cfg = lay["W"], lay["H"], lay["cfg"]
    im = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
    bx, by, bw, bh = cfg["band"]
    im.paste(band_photo, (bx, by))
    shade = Image.new("RGB", (bw, bh), (0, 0, 0))
    im.paste(Image.blend(band_photo, shade, 0.2), (bx, by))
    d = ImageDraw.Draw(im)

    # logo
    plate = os.path.join(ASSETS, size, "logo.png")
    meta = os.path.join(ASSETS, size, "logo.json")
    if os.path.exists(plate):
        # pre-rendered logo plate, cut from the reference set over this same
        # bg.jpg, so it drops straight back in at its recorded origin
        at = json.load(open(meta))
        im.paste(Image.open(plate).convert("RGB"), (at["x"], at["y"]))

    for it in lay["items"]:
        if it.get("kind") == "vrule":
            d.line([(it["x"], it["y"]), (it["x"], it["y2"])], fill="#3a4657", width=1)
            continue
        if it["id"] == "eyebrow" or it["id"] not in ("headline", "line0"):
            continue
        f = pil_font("serif" if it["font"] == "serif" else "sans300", it["size"])
        anchor = {"center": "ma", "left": "la", "right": "ra"}[it["align"]]
        d.text((it["x"], it["y"]), it["text"], font=f, fill=it["color"], anchor=anchor)

    cta = lay["cta"]
    f = pil_font("sans500", cta["size"])
    d.text((cta["x"], cta["y"]), copy["cta"], font=f, fill=WHITE, anchor="ma")
    ry = cta["y"] + cta["size"] * 1.55
    half = (cta["text_w"] + cta["size"] * 1.6) / 2
    d.line([(cta["x"] - half, ry), (cta["x"] + half, ry)], fill=ACCENT, width=2)

    # dots
    n = 4
    dr, gap = 3.5, 6
    total = n * dr * 2 + (n - 1) * gap
    x = bx + bw / 2 - total / 2 + dr
    yy = by + bh - 12
    for k in range(n):
        box = [x - dr, yy - dr, x + dr, yy + dr]
        if k == 0:
            d.ellipse(box, fill=ACCENT, outline=ACCENT)
        else:
            d.ellipse(box, outline="#e8eef6")
        x += dr * 2 + gap
    return im


# ---------------------------------------------------------------- build ----

def build_unit(size, copy, photos, outdir, slug):
    lay = layout(size, copy)
    warnings = validate(size, copy, lay)
    cfg = lay["cfg"]
    bw, bh = cfg["band"][2], cfg["band"][3]
    prefix = "APERTURE_%s_%s_carousel_en" % (slug, size)

    bg_src = os.path.join(ASSETS, size, "bg.jpg")
    bg_out = os.path.join(outdir, prefix + "_bg.jpg")
    shutil.copy(bg_src, bg_out)

    html = build_html(size, copy, lay, prefix, len(photos))
    budget = WEIGHT_CAP - len(html.encode("utf-8")) - os.path.getsize(bg_out) - 4096
    per = budget // len(photos)

    first = None
    for i, p in enumerate(photos):
        q = 82
        while True:
            im, data = fit(p, bw, bh, q)
            if len(data) <= per or q <= 40:
                break
            q -= 6
        with open(os.path.join(outdir, "%s_photo%d.jpg" % (prefix, i + 1)), "wb") as fh:
            fh.write(data)
        if i == 0:
            first = im

    hp = os.path.join(outdir, prefix + "_ad.html")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(html)

    backup_still(size, copy, lay, first, bg_out).save(
        os.path.join(outdir, prefix + "_backup.jpg"), "JPEG", quality=88, optimize=True)

    weight = sum(os.path.getsize(os.path.join(outdir, f))
                 for f in os.listdir(outdir)
                 if f.startswith(prefix) and not f.endswith("_backup.jpg"))
    return prefix, weight, warnings


def write_zips(outdir, prefixes, zipdir):
    os.makedirs(zipdir, exist_ok=True)
    for p in prefixes:
        with zipfile.ZipFile(os.path.join(zipdir, p + ".zip"), "w",
                             zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(outdir)):
                if f.startswith(p) and not f.endswith("_backup.jpg"):
                    z.write(os.path.join(outdir, f),
                            "index.html" if f.endswith("_ad.html") else f)


def write_index(outdir, copy, units):
    """The review page: every unit on one scrubbable page, no server needed."""
    cards = []
    for size, prefix, weight in units:
        w, h = size.split("x")
        cards.append(INDEX_CARD % dict(
            size=size, w=w, h=h, prefix=prefix, kb=weight // 1024,
            cap="under cap" if weight <= WEIGHT_CAP else "OVER CAP",
            capcls="ok" if weight <= WEIGHT_CAP else "err"))
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(INDEX % dict(
            title=esc(copy["headline"]), n=len(units),
            loop_ms=int(LOOP_S * 1000), loops=2,
            headline=esc(copy["headline"]),
            lines=esc("  \u00b7  ".join(copy["lines"])),
            eyebrow=esc(copy["eyebrow"]), cta=esc(copy["cta"]),
            cards="\n".join(cards)))


INDEX_CARD = """<article class="card" data-size="%(size)s">
  <div class="frame" style="width:%(w)spx;height:%(h)spx"><iframe src="%(prefix)s_ad.html" width="%(w)s" height="%(h)s" scrolling="no" frameborder="0" title="%(size)s carousel"></iframe></div>
  <div class="meta" style="max-width:%(w)spx">
    <div class="title">%(size)s<span class="tag">carousel</span><span class="tag lang">EN</span>
      <span class="weight %(capcls)s">%(kb)d KB &middot; %(cap)s</span></div>
    <div class="transport">
      <button class="play" type="button" title="play / pause">&#10074;&#10074;</button>
      <button class="replay" type="button" title="back to the start">&#8634;</button>
      <input class="scrub" type="range" min="0" max="15000" value="0" step="50" aria-label="timeline">
      <span class="time">0.0s</span><span class="loop">loop 1 / 2</span>
    </div>
    <p class="links"><a href="%(prefix)s_ad.html" target="_blank">open alone</a> &middot;
       <a href="%(prefix)s_backup.jpg" target="_blank">backup still</a> &middot;
       <a href="../zips/%(prefix)s.zip">zip</a></p>
  </div>
</article>"""


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Aperture &middot; %(title)s &middot; display ads</title>
<style>
  :root { --bg:#0b0f16; --panel:#131a26; --line:#25304a; --ink:#f0f3f8; --muted:#8d97ad; --blue:#4090EF; }
  html,body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif; }
  header { position:sticky; top:0; z-index:20; background:var(--bg); display:flex; align-items:flex-start;
    justify-content:space-between; gap:16px; padding:14px 28px 12px; flex-wrap:wrap;
    border-bottom:1px solid var(--line); box-shadow:0 6px 18px rgba(0,0,0,.35); }
  h1 { font-size:18px; font-weight:600; margin:0; } h1 span { color:var(--muted); font-weight:400; }
  .copy { color:var(--muted); font-size:12.5px; margin-top:5px; }
  .global { display:flex; gap:10px; align-items:center; color:var(--muted); font-size:13px; }
  button { background:var(--panel); color:var(--ink); border:1px solid var(--line); border-radius:8px;
    padding:6px 11px; font:inherit; cursor:pointer; } button:hover { border-color:var(--blue); }
  button.play { min-width:42px; } button:disabled { opacity:.4; cursor:default; }
  main { padding:16px 28px 56px; } .grid { display:flex; flex-direction:column; gap:26px; align-items:flex-start; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; width:max-content; max-width:100%%; }
  .frame { background:#000; border-radius:4px; overflow:hidden; box-shadow:0 0 0 1px #000; max-width:100%%; }
  iframe { display:block; border:0; max-width:100%%; }
  .meta { margin-top:12px; } .title { display:flex; gap:8px; align-items:center; font-weight:600; flex-wrap:wrap; }
  .tag { font-weight:400; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
    border:1px solid var(--line); border-radius:999px; padding:2px 8px; }
  .tag.lang { color:#c9a35a; border-color:rgba(201,163,90,.5); }
  .weight { margin-left:auto; font-weight:400; font-size:12px; color:var(--muted); }
  .weight.err { color:#ff8a7a; font-weight:600; }
  .transport { display:flex; align-items:center; gap:10px; margin-top:10px; }
  .transport .scrub { flex:1; min-width:120px; accent-color:var(--blue); }
  .time { font-variant-numeric:tabular-nums; color:var(--muted); font-size:12px; min-width:44px; }
  .loop { color:var(--muted); font-size:12px; } .loop.err { color:#ff8a7a; }
  .links { margin:9px 0 0; color:var(--muted); font-size:12.5px; } a { color:var(--blue); }
</style></head><body>
<header>
  <div><h1>%(headline)s <span>&middot; display ads</span></h1>
    <div class="copy">%(eyebrow)s &nbsp;&middot;&nbsp; %(lines)s &nbsp;&middot;&nbsp; %(cta)s</div>
    <div class="copy">%(n)d units &middot; carousel &middot; English &middot; 15s (two 7.5s cycles) &middot; 700 KB cap</div></div>
  <div class="global"><button id="allplay" type="button">pause all</button>
    <button id="allreplay" type="button">replay all</button></div>
</header>
<main><div class="grid">
%(cards)s
</div></main>
<script>
(function () {
  var LOOP = %(loop_ms)d, LOOPS = %(loops)d, TOTAL = LOOP * LOOPS, cards = [];

  function bind(card) {
    var frame = card.querySelector('iframe'), playBtn = card.querySelector('.play'),
        replayBtn = card.querySelector('.replay'), scrub = card.querySelector('.scrub'),
        timeEl = card.querySelector('.time'), loopEl = card.querySelector('.loop');
    var st = { anims: [], ok: false, scrubbing: false, playing: true };

    function win() { try { return frame.contentWindow; } catch (e) { return null; } }
    function doc() { try { return frame.contentDocument || (win() && win().document); } catch (e) { return null; } }
    function ad() { var w = win(); return w && w.__ad; }
    function fail(msg) {
      loopEl.textContent = msg; loopEl.className = 'loop err';
      [playBtn, replayBtn, scrub].forEach(function (el) { el.disabled = true; });
    }
    function collect() {
      var d = doc();
      if (!d || !d.getAnimations) { fail('controls unavailable in this browser'); return false; }
      st.anims = d.getAnimations();
      if (!st.anims.length) return false;   // still starting up - the poller retries
      loopEl.className = 'loop'; loopEl.textContent = 'loop 1 / ' + LOOPS;
      // run every looping animation for the full two cycles, then hold
      st.anims.forEach(function (a) {
        var t = a.effect.getTiming();
        if (t.iterations === Infinity && t.duration > 0) {
          a.effect.updateTiming({ iterations: Math.ceil(TOTAL / t.duration), fill: 'forwards' });
        }
      });
      st.ok = true;
      [playBtn, replayBtn, scrub].forEach(function (el) { el.disabled = false; });
      return true;
    }
    function main() {
      var best = null;
      st.anims.forEach(function (a) {
        var d = a.effect.getTiming().duration * (a.effect.getTiming().iterations || 1);
        if (!best || d > best._d) { best = a; best._d = d; }
      });
      return best || st.anims[0];
    }
    function setTime(ms) {
      st.anims.forEach(function (a) { try { a.currentTime = ms; } catch (e) {} });
      var A = ad(); if (A) A.setTime(ms);
    }
    function pause() {
      st.playing = false; st.anims.forEach(function (a) { a.pause(); });
      var A = ad(); if (A) A.pause(); playBtn.innerHTML = '&#9654;';
    }
    function play() {
      var m = main();
      if (m && m.currentTime >= TOTAL - 1) setTime(0);
      st.playing = true; st.anims.forEach(function (a) { a.play(); });
      var A = ad(); if (A) A.play(); playBtn.innerHTML = '&#10074;&#10074;';
    }
    function replay() { if (!st.ok) return; setTime(0); play(); }

    playBtn.onclick = function () { if (!st.ok) return; st.playing ? pause() : play(); };
    replayBtn.onclick = replay;
    scrub.addEventListener('input', function () {
      if (!st.ok) return;
      st.scrubbing = true; if (st.playing) pause();
      setTime(+scrub.value); paint(+scrub.value);
    });
    scrub.addEventListener('change', function () { st.scrubbing = false; });

    function paint(ms) {
      var inLoop = ms %% LOOP, n = Math.min(Math.floor(ms / LOOP) + 1, LOOPS);
      timeEl.textContent = (inLoop / 1000).toFixed(1) + 's';
      if (loopEl.className.indexOf('err') === -1) loopEl.textContent = 'loop ' + n + ' / ' + LOOPS;
    }
    function tick() {
      if (!st.ok) return;
      var m = main();
      if (m && !st.scrubbing) {
        var t = Math.min(m.currentTime || 0, TOTAL);
        scrub.value = t; paint(t);
        if (t >= TOTAL - 1 && st.playing) { pause(); }
      }
    }
    // The copy animations are delayed, so getAnimations() can come back empty for
    // the first few frames after load - poll until they exist, then give up.
    var tries = 0;
    (function ready() {
      if (st.ok) return;
      if (collect()) { play(); return; }
      if (++tries > 60) { fail('ad not ready'); return; }
      setTimeout(ready, 100);
    })();
    return { tick: tick, play: play, pause: pause, replay: replay,
             playing: function () { return st.playing; } };
  }

  [].forEach.call(document.querySelectorAll('.card'), function (c) { cards.push(bind(c)); });
  (function loop() { cards.forEach(function (c) { c.tick(); }); requestAnimationFrame(loop); })();

  var allBtn = document.getElementById('allplay');
  allBtn.onclick = function () {
    var anyPlaying = cards.some(function (c) { return c.playing(); });
    cards.forEach(function (c) { anyPlaying ? c.pause() : c.play(); });
    allBtn.textContent = anyPlaying ? 'play all' : 'pause all';
  };
  document.getElementById('allreplay').onclick = function () {
    cards.forEach(function (c) { c.replay(); });
    allBtn.textContent = 'pause all';
  };
})();
</script></body></html>"""



def write_report(outdir, order, csv_path, copy, photos, units, warnings, slug):
    """Audit trail for the run, alongside the CSV routine's run reports."""
    today = datetime.date.today().isoformat()

    def cell(v):                      # pipes in the copy would break the table
        return str(v).replace("|", "\\|")

    L = ["# Digital ads run report - %s" % cell(copy["headline"]), "",
         "- **Order**: `%s`" % order,
         "- **Source CSV**: `%s`" % os.path.basename(csv_path),
         "- **Built**: %s" % today,
         "- **Set**: %d units, carousel, English" % len(units), "",
         "## Copy", "",
         "| slot | text |", "|---|---|",
         "| eyebrow | %s |" % cell(copy["eyebrow"]),
         "| headline | %s |" % copy["headline"]]
    for i, line in enumerate(copy["lines"], 1):
        L.append("| subline %d | %s |" % (i, cell(line)))
    L += ["| CTA | %s |" % cell(copy["cta"]),
          "| clickTag | %s |" % copy["clicktag"], "",
          "## Photos", ""]
    for i, ph in enumerate(photos, 1):
        L.append("%d. `%s`" % (i, os.path.relpath(ph, order)))
    L += ["", "## Units", "",
          "| size | weight | cap | notes |", "|---|---|---|---|"]
    for size, prefix, weight in units:
        note = "; ".join(warnings.get(size, [])) or "-"
        L.append("| %s | %d KB | %s | %s |"
                 % (size, weight // 1024,
                    "ok" if weight <= WEIGHT_CAP else "**OVER**", note))
    L += ["", "Cap is 700 KB per unit, uncompressed.", "",
          "## Delivered", "",
          "- `Digital Ads/%s-preview/index.html` - the review page" % slug,
          "- `Digital Ads/%s-preview/` - units, backup stills, assets" % slug,
          "- `Digital Ads/zips/` - one trafficable zip per unit", ""]
    path = os.path.join(outdir, "run-report_%s_%s.md" % (slug, today))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True, help="Aperture Pack order folder")
    ap.add_argument("--out", help="output folder (default: <order>/Digital Ads)")
    ap.add_argument("--slug", help="file-name slug (default: from the street)")
    ap.add_argument("--overrides", help="JSON of copy overrides")
    ap.add_argument("--photos", nargs="*", help="exactly four image paths")
    ap.add_argument("--sizes", nargs="*", default=SIZE_ORDER)
    a = ap.parse_args()

    order = os.path.abspath(a.order)
    ov = json.load(open(a.overrides, encoding="utf-8")) if a.overrides else {}
    csv_path, row = read_csv(order)
    copy = build_copy(row, ov)
    slug = a.slug or ov.get("slug") or re.sub(
        r"[^A-Za-z0-9]", "", copy["headline"].title())
    given = a.photos or ov.get("photos")
    if given:
        given = [p if os.path.isabs(p) else os.path.join(order, p) for p in given]
    photos = pick_photos(order, given)
    outdir = a.out or os.path.join(order, "Digital Ads")
    preview = os.path.join(outdir, "%s-preview" % slug)
    os.makedirs(preview, exist_ok=True)

    print("CSV     :", os.path.basename(csv_path))
    print("headline:", copy["headline"], "|", copy["location"])
    print("lines   :", " / ".join(copy["lines"]))
    for p in photos:
        print("photo   :", os.path.basename(p))

    units, prefixes, warnings = [], [], {}
    for size in a.sizes:
        prefix, weight, warn = build_unit(size, copy, photos, preview, slug)
        units.append((size, prefix, weight))
        prefixes.append(prefix)
        if warn:
            warnings[size] = warn
        flag = "  OVER CAP" if weight > WEIGHT_CAP else ""
        print("%-9s %6d KB%s" % (size, weight // 1024, flag))
        for w in warn:
            print("          ! " + w)

    write_index(preview, copy, units)
    write_zips(preview, prefixes, os.path.join(outdir, "zips"))
    report = write_report(outdir, order, csv_path, copy, photos, units,
                          warnings, slug)
    print("\nreview  :", os.path.join(preview, "index.html"))
    print("report  :", report)
    print("zips    :", os.path.join(outdir, "zips"))


if __name__ == "__main__":
    main()
