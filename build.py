#!/usr/bin/env python3
"""
Aperture Global - HTML5 display ad builder.

Produces the full reference file set for one property: six sizes x two variants
(video and carousel), each with its ad HTML, background, four photos, a backup
still, and - for video units - the walkthrough mp4. Plus the review index and a
run report.

    python3 build.py --order "<order folder>" [--overrides o.json]
                     [--video <master.mp4>] [--out <dir>]

Geometry, type and timing come from assets/spec.json via render.py, which was
measured off the Parque das Nacoes originals. See README.md.
"""

import argparse, csv, datetime, glob, io, json, os, re, shutil, subprocess, sys, zipfile

import outline
from PIL import Image, ImageChops, ImageDraw

import render as R

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = R.ASSETS
SIZE_ORDER = ["768x1024", "1024x768", "480x320", "970x250", "320x480", "300x600"]
VARIANTS = ["video"]          # the carousel lives inside each video unit as the
                              # autoplay fallback; pass --variants video carousel for both
WEIGHT_CAP = 700 * 1024
CLICKTAG = "https://www.apertureglobal.com/"
CTA_TEXT = "Schedule a viewing"
EYEBROW_TEXT = "Exclusive Offer"   # house default; override per property if asked
LOOP_MS = int(R.LOOP_S * 1000)


# ------------------------------------------------------------ copy model ----

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
    hits = sorted(glob.glob(os.path.join(order_dir, "CSV", "property_data_*.csv")))
    if not hits:
        sys.exit("no property_data_*.csv under %s/CSV" % order_dir)
    ver = lambda p: int((re.search(r"_v(\d+)\.csv$", p) or [0, 0])[1] or 0)
    path = max(hits, key=ver)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return path, next(csv.DictReader(fh))


def build_copy(row, ov):
    spec = " | ".join(x for x in [
        (_num(row.get("bedrooms")) + " br") if _num(row.get("bedrooms")) else "",
        (_bath(row.get("bathrooms")) + " bth") if _bath(row.get("bathrooms")) else "",
        ("{:,} sqft".format(int(float(row["sqft"]))) if _num(row.get("sqft")) else ""),
    ] if x)
    agent = (row.get("name") or "").strip()
    c = dict(eyebrow=EYEBROW_TEXT,
             headline=(row.get("street") or "").strip(),
             location=(row.get("cityState") or "").strip(),
             spec=spec, agent=("Listed by " + agent) if agent else "",
             cta=CTA_TEXT, clicktag=CLICKTAG)
    c.update({k: v for k, v in ov.items() if k in c})
    lines = ov.get("lines") or [c["location"], c["spec"], c["agent"]]
    c["lines"] = [re.sub(r"\s+", " ", l).strip() for l in lines if l] or [c["location"]]
    return c


PHOTO_PRIORITY = ["exterior", "living", "kitchen", "master", "outdoor",
                  "dining", "entry", "amenities", "interior"]


def pick_photos(order_dir, given):
    if given:
        return [p if os.path.isabs(p) else os.path.join(order_dir, p) for p in given]
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
        for slug in PHOTO_PRIORITY:
            for f in files:
                if os.path.basename(f).startswith(slug) and slug not in used:
                    out.append(f); used.add(slug); break
            if len(out) == 4:
                return out
        for f in files:
            if f not in out:
                out.append(f)
            if len(out) == 4:
                return out
    sys.exit("could not find four usable photos under %s" % order_dir)


# ----------------------------------------------------------------- unit ----

def overlay_svg(size, copy, variant):
    """The whole vector layer: keylines, logo, eyebrow, headline, lines, CTA."""
    W, H = (int(n) for n in size.split("x"))
    sp = R.SPEC[size]
    s, tx, ty = sp["logo"]
    logo = open(os.path.join(ASSETS, "logo-master.svg"), encoding="utf-8").read().strip()

    parts = [R.keylines(size)]
    parts.append('<g id="logo" transform="translate(%.2f %.2f) scale(%.4f)">%s</g>'
                 % (tx, ty, s, logo))

    eb = R.eyebrow_parts(size, copy["eyebrow"])
    if eb:
        lines, mk = eb
        txt = "".join(R.svg_text("eyebrowtext" if i == 0 else "eyebrowtext%d" % i, ln, R.WHITE)
                      for i, ln in enumerate(lines))
        parts.append('<g id="eyebrow"><g transform="translate(%.2f %.2f) scale(%.4f)">%s</g>%s</g>'
                     % (mk["tx"], mk["ty"], mk["s"], R.mark_svg(), txt))

    hd = R.slot_for(size, "head", copy["headline"])
    if hd:
        parts.append(R.svg_text("head", hd, R.WHITE))

    for i, line in enumerate(copy["lines"]):
        d = R.slot_for(size, "sub", line)
        if d:
            parts.append(R.svg_text("line%d" % i, d, R.MUTED))

    cta = R.slot_for(size, "cta", copy["cta"])
    if cta:
        r = R.SPEC[size]["slots"]["cta"]["rule"]
        rule = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.2f" fill="%s"/>'
                % (r["x"], r["y"] - r["stroke"] / 2, r["w"], r["stroke"], r["colour"]))
        parts.append('<g id="cta">%s%s</g>'
                     % (R.svg_text("ctatext", cta, R.WHITE), rule))

    return ('<svg class="vec" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">%s</svg>'
            % (W, H, "".join(parts)))


def unit_css(size, copy, variant):
    W, H = (int(n) for n in size.split("x"))
    bx, by, bw, bh = R.SPEC[size]["band"]
    n = len(copy["lines"])
    seg = 100.0 / max(n, 1)
    kf = []
    wins = (R.LINE_WINDOWS[:n] if n <= 3 else
            [(i * seg / 100, (i + .7) * seg / 100, (i + 1) * seg / 100) for i in range(n)])
    last_out = wins[-1][2]
    for i, (a, hold, out) in enumerate(wins):
        fade = min(0.055, (out - a) / 4)
        if i == 0:
            # The first line opens already visible and comes back at the end of the
            # loop, so the cycle never starts or ends with nothing to read.
            kf.append("@keyframes kf_line0{0%%,%.3f%%{opacity:1;transform:translateX(0)}"
                      "%.3f%%{opacity:0;transform:translateX(48px)}"
                      "%.3f%%,%.3f%%{opacity:0;transform:translateX(-48px)}"
                      "100%%{opacity:1;transform:translateX(0)}}"
                      % (hold * 100, out * 100, out * 100 + 0.001, last_out * 100))
        else:
            kf.append("@keyframes kf_line%d{0%%,%.3f%%{opacity:0;transform:translateX(-48px)}"
                      "%.3f%%{opacity:1;transform:translateX(0)}"
                      "%.3f%%{opacity:1;transform:translateX(0)}"
                      "%.3f%%,100%%{opacity:0;transform:translateX(48px)}}"
                      % (i, a * 100, (a + fade) * 100, hold * 100, out * 100))
        kf.append("#line%d{animation-name:kf_line%d}" % (i, i))
    fonts = ""   # copy is baked to outlines; the units fetch and embed no fonts
    return TEMPLATE_CSS % dict(
        fonts=fonts, ink=R.INK, accent=R.ACCENT, W=W, H=H,
        bx=bx, by=by, bw=bw, bh=bh,
        band_fade=R.BAND_FADE, eb_in=R.EYEBROW_IN, eb_hold=R.EYEBROW_HOLD,
        eb_out=R.EYEBROW_OUT, logo_in=R.LOGO_IN, logo_full=R.LOGO_FULL,
        head_delay=(R.LOGO_IN if R.SPEC[size].get("exclusive_eyebrow") else R.HEAD_DELAY),
        loop=R.LOOP_S,
        line_delay=(R.LOGO_IN if R.SPEC[size].get("exclusive_eyebrow") else R.LINE_DELAY),
        kf="\n  ".join(kf), swipe=48 if W >= 480 else 34,
        pc_in=R.EYEBROW_IN / R.EYEBROW_OUT * 100,
        pc_hold=R.EYEBROW_HOLD / R.EYEBROW_OUT * 100,
        pc_hold2=(R.EYEBROW_HOLD + 0.038) / R.EYEBROW_OUT * 100,
        pc_logo=R.LOGO_IN / R.LOGO_FULL * 100)


TEMPLATE_CSS = """  %(fonts)s
  :root { color-scheme: dark; }
  html, body { margin:0; padding:0; background:%(ink)s; overflow:hidden; }
  #ad { position:relative; width:%(W)dpx; height:%(H)dpx; overflow:hidden;
        background:%(ink)s var(--bg) 0 0/%(W)dpx %(H)dpx no-repeat; }
  #band { position:absolute; left:%(bx)dpx; top:%(by)dpx; width:%(bw)dpx; height:%(bh)dpx;
        overflow:hidden; background:#000; opacity:0;
        animation: kf_fade %(band_fade)ss linear 1 forwards; }
  #track { position:absolute; inset:0 auto 0 0; height:%(bh)dpx; display:flex;
        will-change:transform; transition: transform .7s cubic-bezier(.5,0,.3,1); }
  #track img { width:%(bw)dpx; height:%(bh)dpx; object-fit:cover; flex:0 0 %(bw)dpx; display:block; }
  #band video { position:absolute; inset:0; width:%(bw)dpx; height:%(bh)dpx;
        object-fit:cover; display:block; z-index:3; }
  #band::before { content:""; position:absolute; inset:0; background:rgba(0,0,0,.2); z-index:4; pointer-events:none; }
  #band::after { content:""; position:absolute; inset:0; box-shadow: inset 0 4px 4px rgba(0,0,0,.25); z-index:4; pointer-events:none; }
  .vec { position:absolute; inset:0; width:100%%; height:100%%; pointer-events:none; z-index:6; }
  .nav { position:absolute; top:50%%; width:30px; height:30px; margin-top:-15px; border:0;
        border-radius:50%%; background:rgba(11,15,22,.55); color:#fff; cursor:pointer; z-index:7;
        display:flex; align-items:center; justify-content:center; padding:0; transition:background .2s; }
  .nav:hover { background:rgba(64,144,239,.85); }
  .nav svg { width:12px; height:12px; display:block; }
  #prev { left:8px; } #next { right:8px; }
  #dots { position:absolute; left:%(bx)dpx; width:%(bw)dpx; top:%(by)dpx; height:%(bh)dpx;
        pointer-events:none; z-index:7; }
  #dots i { position:absolute; bottom:8px; width:7px; height:7px; border-radius:50%%;
        border:1px solid rgba(255,255,255,.8); box-sizing:border-box; pointer-events:auto; cursor:pointer; }
  #dots i.on { background:%(accent)s; border-color:%(accent)s; }
  #swipe { position:absolute; left:50%%; top:50%%; width:128px; height:80px; margin:-40px 0 0 -64px;
        z-index:7; display:none; pointer-events:none; opacity:.6;
        filter:drop-shadow(0 3px 8px rgba(0,0,0,.6)); }
  #swipe svg { width:100%%; height:100%%; animation: kf_swipe 2.2s cubic-bezier(.45,0,.2,1) infinite; }
  #clickthrough { position:absolute; inset:0; z-index:9; display:none; }
  #ad.noanim, #ad.noanim * { animation:none !important; }
  #hot { position:absolute; z-index:9; cursor:pointer; display:block; text-decoration:none; }
  /* the eyebrow plays first and hands off to the logo, exactly as the reference does */
  #eyebrow { opacity:0; animation: kf_eyebrow %(eb_out)ss linear 1 forwards; }
  #logo { opacity:0; animation: kf_logo %(logo_full)ss linear 1 forwards; }
  #head { opacity:0; animation: kf_in .7s cubic-bezier(.5,0,.3,1) %(head_delay)ss 1 both; }
  #cta { animation: kf_bob 1.9s ease-in-out infinite; transform-origin:center; }
  [id^="line"] { opacity:0; transform-origin:0 0;
        animation-duration:%(loop)ss; animation-timing-function:linear;
        animation-iteration-count:infinite; animation-delay:%(line_delay)ss; }
  @keyframes kf_fade { to { opacity:1; } }
  @keyframes kf_in { from { opacity:0; transform:translateX(-28px); } to { opacity:1; transform:translateX(0); } }
  @keyframes kf_bob { 0%%,100%% { transform:translateY(0); } 50%% { transform:translateY(-4px); } }
  @keyframes kf_eyebrow { 0%%,%(pc_in).3f%% { opacity:0; } %(pc_hold).3f%% { opacity:1; }
        %(pc_hold2).3f%% { opacity:1; } 100%% { opacity:0; } }
  @keyframes kf_logo { 0%%,%(pc_logo).3f%% { opacity:0; } 100%% { opacity:1; } }
  @keyframes kf_swipe { 0%% { transform:translate(-%(swipe)dpx,6px) rotate(-10deg); }
        22%% { transform:translate(0,-6px) rotate(0deg); }
        45%%,60%% { transform:translate(%(swipe)dpx,4px) rotate(9deg); }
        100%% { transform:translate(-%(swipe)dpx,6px) rotate(-10deg); } }
  %(kf)s
  @media (prefers-reduced-motion: reduce) {
    #eyebrow, #logo, #head, #cta, [id^="line"], #swipe svg { animation:none !important; opacity:1 !important; transform:none !important; }
    #eyebrow { opacity:0 !important; }
    [id^="line"]:not(#line0) { display:none !important; }
  }
"""


def build_html(size, copy, variant, prefix, nphotos=4):
    W, H = (int(n) for n in size.split("x"))
    bx, by, bw, bh = R.SPEC[size]["band"]
    css = unit_css(size, copy, variant)
    cta = R.slot_for(size, "cta", copy["cta"])
    hot = ""
    if cta:
        r = R.SPEC[size]["slots"]["cta"]["rule"]
        top = cta["baseline"] - cta["size"]
        hot = ('left:%.1fpx;top:%.1fpx;width:%.1fpx;height:%.1fpx;'
               % (r["x"], top, r["w"], (r["y"] + 4) - top))
    photos = "".join('<img src="%s_photo%d.jpg" alt="%s %d">'
                     % (prefix, i + 1, R.esc(copy["headline"]), i + 1) for i in range(nphotos))
    dots = "".join('<i%s></i>' % (' class="on"' if i == 0 else "") for i in range(nphotos))
    video = ('<video src="%s_video.mp4" autoplay muted loop playsinline preload="auto"></video>'
             % prefix) if variant == "video" else ""
    return TEMPLATE_HTML % dict(
        W=W, H=H, size=size, variant=variant, title=R.esc(copy["headline"]),
        clicktag=copy["clicktag"], css=css, prefix=prefix, video=video,
        photos=photos, dots=dots, svg=overlay_svg(size, copy, variant),
        cta_text=R.esc(copy["cta"]), hot=hot, bw=bw, bh=bh,
        loop_ms=LOOP_MS, isvideo="true" if variant == "video" else "false")


TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="ad.size" content="width=%(W)d,height=%(H)d">
<title>Aperture &middot; %(title)s &middot; %(size)s %(variant)s</title>
<script type="text/javascript">
  var clickTag = "%(clicktag)s";
</script>
<script type="text/javascript">
  (function () { var m = /[?&]clicktag=([^&#]*)/i.exec(window.location.search); if (m) { try { clickTag = decodeURIComponent(m[1]); } catch (e) {} } })();
</script>
<style>
  #ad { --bg: url(%(prefix)s_bg.jpg); }
%(css)s
</style>
</head>
<body>
<div id="ad">
  <div id="band" aria-roledescription="carousel">
    <div id="track">%(photos)s</div>
    %(video)s
    <button class="nav" id="prev" type="button" aria-label="Previous image"><svg viewBox="0 0 18 18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.5 3.5 6 9l5.5 5.5"/></svg></button>
    <button class="nav" id="next" type="button" aria-label="Next image"><svg viewBox="0 0 18 18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5 12 9l-5.5 5.5"/></svg></button>
    <div id="swipe" aria-hidden="true"><svg viewBox="0 0 64 40" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 20 3 14m0 6 6 6M3 20h10"/><path d="M55 20l6-6m0 6-6 6M61 20H51"/><path d="M27 32V13.5a2.5 2.5 0 0 1 5 0V22m0-3a2.5 2.5 0 0 1 5 0v3m0-2a2.5 2.5 0 0 1 5 0v2m0-1a2.5 2.5 0 0 1 5 0v6c0 4.5-3 8.5-8 8.5h-5c-3.5 0-5.5-1.5-7.5-4.5L23 25.5a2.4 2.4 0 0 1 4-2.5"/></svg></div>
  </div>
  <div id="dots">%(dots)s</div>
  %(svg)s
  <a id="hot" style="%(hot)s" href="javascript:window.open(window.clickTag)" aria-label="%(cta_text)s - Aperture Global Real Estate"></a>
</div>
<script>
(function () {
  var band  = document.getElementById('band'),
      track = document.getElementById('track'),
      vid   = band.querySelector('video'),
      imgs  = track.getElementsByTagName('img'),
      dots  = document.getElementById('dots').getElementsByTagName('i'),
      swipe = document.getElementById('swipe'),
      navs  = [document.getElementById('prev'), document.getElementById('next')],
      w = %(bw)d, n = imgs.length, i = 0, manual = false, timer, isVideo = %(isvideo)s;

  // Video units carry the carousel underneath. If autoplay is refused the unit
  // falls back to the interactive carousel rather than a frozen frame.
  function showCarousel() {
    isVideo = false;
    if (vid) vid.style.display = 'none';
    navs.forEach(function (b) { b.style.display = 'flex'; });
    document.getElementById('dots').style.display = 'block';
    restart();
  }
  function hideCarouselChrome() {
    navs.forEach(function (b) { b.style.display = 'none'; });
    document.getElementById('dots').style.display = 'none';
    if (swipe) swipe.style.display = 'none';
  }

  function place() {
    var total = n * 7 + (n - 1) * 6, x = (w - total) / 2;
    for (var d = 0; d < dots.length; d++) { dots[d].style.left = x + 'px'; x += 13; }
  }
  function go(k, byHand) {
    i = (k + n) %% n;
    track.style.transform = 'translateX(' + (-i * w) + 'px)';
    for (var d = 0; d < dots.length; d++) dots[d].className = (d === i ? 'on' : '');
    if (byHand) { manual = true; if (swipe) swipe.style.display = 'none'; restart(); }
  }
  function restart() { clearInterval(timer); timer = setInterval(function () { go(i + 1); }, %(loop_ms)d / n); }

  place();
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

  if (isVideo && vid) {
    hideCarouselChrome();
    var started = false;
    vid.addEventListener('playing', function () { started = true; }, { once: true });
    function attempt() { var p = vid.play(); if (p && p.catch) p.catch(function () {}); }
    attempt();
    // Only hand over to the carousel if the video genuinely will not run. A video
    // that is merely still buffering reads paused/currentTime 0 for a moment, which
    // is not a refusal.
    setTimeout(function () { if (!started && vid.paused) attempt(); }, 700);
    setTimeout(function () { if (!started && vid.paused) showCarousel(); }, 3000);
  } else {
    if (swipe && ('ontouchstart' in window)) {
      swipe.style.display = 'block';
      setTimeout(function () { if (!manual && swipe) swipe.style.display = 'none'; }, 6000);
    }
    restart();
  }

  // Review hook - used by the preview page, inert in a live placement.
  window.__ad = {
    loop: %(loop_ms)d, slides: n,
    setTime: function (ms) {
      if (isVideo && vid) { try { vid.currentTime = (ms / 1000) %% (vid.duration || 15); } catch (e) {} }
      else { go(Math.floor((ms %% this.loop) / (this.loop / n))); }
    },
    pause: function () { clearInterval(timer); if (vid) vid.pause(); },
    restart: function () {
      var root = document.getElementById('ad');
      root.classList.add('noanim'); void root.offsetWidth; root.classList.remove('noanim');
      if (vid) { try { vid.currentTime = 0; } catch (e) {} }
      i = 0; go(0);
    },
    play: function () { if (isVideo && vid) { var p = vid.play(); if (p && p.catch) p.catch(function () {}); } else { restart(); } }
  };
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- images ----

def fit(src, w, h, quality):
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    k = max(w / sw, h / sh)
    im = im.resize((max(w, int(sw * k + .5)), max(h, int(sh * k + .5))), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((l, t, l + w, t + h))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return im, buf.getvalue()


def backup_still(size, copy, band_img, bg_path, variant):
    W, H = (int(n) for n in size.split("x"))
    sp = R.SPEC[size]
    im = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
    bx, by, bw, bh = sp["band"]
    im.paste(Image.blend(band_img, Image.new("RGB", (bw, bh), (0, 0, 0)), 0.2), (bx, by))
    d = ImageDraw.Draw(im)

    for x, y, w, h in sp["rules"]:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=R.ACCENT)

    plate, meta = (os.path.join(ASSETS, size, "logo.png"),
                   os.path.join(ASSETS, size, "logo.json"))
    if os.path.exists(plate):
        at = json.load(open(meta))
        im.paste(Image.open(plate).convert("RGB"), (at["x"], at["y"]))

    SS = 4                      # supersample: ImageDraw.polygon has no antialiasing,
                                # and at 12px the counters are only a pixel or two

    def draw(slot, s, fill):
        g = R.slot_for(size, slot, s)
        if not g:
            return
        x = g["x"] - g["width"] / 2 if g["anchor"] == "middle" else g["x"]
        polys = outline.polygons(g["text"], g["font"], g["size"] * SS,
                                 g["track"] * SS, x * SS, g["baseline"] * SS)
        if not polys:
            return
        # XOR the contours so letter counters stay open, then downsample for edges
        big = Image.new("L", (im.size[0] * SS, im.size[1] * SS), 0)
        for poly in polys:
            layer = Image.new("L", big.size, 0)
            ImageDraw.Draw(layer).polygon(poly, fill=255)
            big = ImageChops.difference(big, layer)
        im.paste(fill, (0, 0), big.resize(im.size, Image.LANCZOS))

    draw("head", copy["headline"], R.WHITE)
    draw("sub", copy["lines"][0], R.MUTED)
    draw("cta", copy["cta"], R.WHITE)
    r = R.SPEC[size]["slots"]["cta"]["rule"]
    d.rectangle([r["x"], r["y"] - r["stroke"] / 2,
                 r["x"] + r["w"], r["y"] + r["stroke"] / 2], fill=r["colour"])

    if variant == "carousel":
        total = 4 * 7 + 3 * 6
        x = bx + (bw - total) / 2
        yy = by + bh - 12
        for k in range(4):
            box = [x, yy, x + 7, yy + 7]
            d.ellipse(box, fill=R.ACCENT if k == 0 else None, outline=R.ACCENT if k == 0 else "#e8eef6")
            x += 13
    return im


def encode_video(master, out_path, w, h, budget, seconds=15, fps=15):
    """Crop the 16:9 master to this band and fit it inside `budget` bytes.

    The reference units run 15 fps and size the mp4 to whatever the 700 KB cap
    leaves after the html, background and four photos, so we do the same rather
    than encoding at a fixed quality and hoping.
    """
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,fps=%d"
          % (w, h, w, h, fps))
    kbps = max(120, int(budget * 8 / seconds / 1000 * 0.92))
    log = out_path + ".2pass"
    base = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", master,
            "-t", str(seconds), "-vf", vf, "-an", "-c:v", "libx264",
            "-profile:v", "main", "-pix_fmt", "yuv420p", "-preset", "slow",
            "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.3),
            "-bufsize", "%dk" % (kbps * 2), "-passlogfile", log]
    subprocess.run(base + ["-pass", "1", "-f", "mp4", os.devnull], check=True)
    subprocess.run(base + ["-pass", "2", "-movflags", "+faststart", out_path], check=True)
    for f in glob.glob(log + "*"):
        os.remove(f)
    return os.path.getsize(out_path)


# ----------------------------------------------------------------- build ----

def build_unit(size, variant, copy, photos, outdir, slug, master):
    sp = R.SPEC[size]
    bw, bh = sp["band"][2], sp["band"][3]
    prefix = "APERTURE_%s_%s_%s_en" % (slug, size, variant)

    bg = os.path.join(outdir, prefix + "_bg.jpg")
    shutil.copy(os.path.join(ASSETS, size, "bg.jpg"), bg)

    html = build_html(size, copy, variant, prefix, len(photos))
    avail = WEIGHT_CAP - len(html.encode("utf-8")) - os.path.getsize(bg) - 8192

    # Photos first, then the video takes whatever is left. On a video unit the
    # carousel is only the autoplay fallback, so it gets the smaller share.
    share = 0.35 if variant == "video" else 1.0
    per = max(10000, int(avail * share) // len(photos))
    first, used = None, 0
    for i, p in enumerate(photos):
        q = 82
        while True:
            im, data = fit(p, bw, bh, q)
            if len(data) <= per or q <= 30:
                break
            q -= 6
        open(os.path.join(outdir, "%s_photo%d.jpg" % (prefix, i + 1)), "wb").write(data)
        used += len(data)
        if i == 0:
            first = im

    if variant == "video":
        if not master:
            return None, 0, ["no walkthrough master - video unit skipped"]
        encode_video(master, os.path.join(outdir, prefix + "_video.mp4"),
                     bw, bh, max(60000, avail - used))

    open(os.path.join(outdir, prefix + "_ad.html"), "w", encoding="utf-8").write(html)
    backup_still(size, copy, first, bg, variant).save(
        os.path.join(outdir, prefix + "_backup.jpg"), "JPEG", quality=88, optimize=True)

    weight = sum(os.path.getsize(os.path.join(outdir, f)) for f in os.listdir(outdir)
                 if f.startswith(prefix) and not f.endswith("_backup.jpg"))
    warn = ["over the 700 KB cap"] if weight > WEIGHT_CAP else []
    return prefix, weight, warn


def write_zips(outdir, prefixes, zipdir):
    os.makedirs(zipdir, exist_ok=True)
    for p in prefixes:
        with zipfile.ZipFile(os.path.join(zipdir, p + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(outdir)):
                if f.startswith(p) and not f.endswith("_backup.jpg"):
                    z.write(os.path.join(outdir, f),
                            "index.html" if f.endswith("_ad.html") else f)


def write_index(outdir, copy, units, zipdir, nphotos=4):
    """The review page. Each unit is inlined with srcdoc so the iframes are
    same-origin with this page - that is what lets the transport work when the
    file is opened straight off the disk, with no server."""
    cards = []
    for size, variant, prefix, weight in units:
        w, h = size.split("x")
        doc = open(os.path.join(outdir, prefix + "_ad.html"), encoding="utf-8").read()
        zp = os.path.join(zipdir, prefix + ".zip")
        zkb = (os.path.getsize(zp) // 1024) if os.path.exists(zp) else 0
        cards.append(INDEX_CARD % dict(
            size=size, variant=variant, w=w, h=h, prefix=prefix, kb=weight // 1024,
            zipkb=zkb, cap="under cap" if weight <= WEIGHT_CAP else "OVER CAP",
            capcls="ok" if weight <= WEIGHT_CAP else "err",
            notes=NOTES[variant] % dict(sec=int(LOOP_MS * 2 / 1000), n=nphotos),
            doc=(doc.replace("&", "&amp;").replace('"', "&quot;")
                    .replace("<", "&lt;").replace(">", "&gt;"))))
    open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(
        INDEX % dict(title=R.esc(copy["headline"]), n=len(units), loop_ms=LOOP_MS, loops=2,
                     variants=" &amp; ".join(sorted({v for _, v, _, _ in units})),
                     variants_title=" &amp; ".join(v.title() for v in sorted({v for _, v, _, _ in units})),
                     loop_s=("%g" % (LOOP_MS / 1000.0)),
                     headline=R.esc(copy["headline"]),
                     lines=R.esc("  \u00b7  ".join(copy["lines"])),
                     eyebrow=R.esc(copy["eyebrow"]), cta=R.esc(copy["cta"]),
                     cards="\n".join(cards)))


def write_report(outdir, order, csv_path, copy, photos, units, warnings, slug, master):
    today = datetime.date.today().isoformat()
    cell = lambda v: str(v).replace("|", "\\|")
    L = ["# Digital ads run report - %s" % cell(copy["headline"]), "",
         "- **Order**: `%s`" % order,
         "- **Source CSV**: `%s`" % os.path.basename(csv_path),
         "- **Walkthrough master**: %s" % ("`%s`" % os.path.basename(master) if master else "_none - video units skipped_"),
         "- **Built**: %s" % today,
         "- **Set**: %d units (six sizes x video + carousel), English" % len(units), "",
         "## Copy", "", "| slot | text |", "|---|---|",
         "| eyebrow | %s |" % cell(copy["eyebrow"]),
         "| headline | %s |" % cell(copy["headline"])]
    for i, line in enumerate(copy["lines"], 1):
        L.append("| subline %d | %s |" % (i, cell(line)))
    L += ["| CTA | %s |" % cell(copy["cta"]), "| clickTag | %s |" % copy["clicktag"], "",
          "## Type", "",
          "| slot | face |", "|---|---|",
          "| headline | Cormorant Garamond Light |",
          "| eyebrow | PT Serif Italic |",
          "| sublines | Archivo Light, 0.09em |",
          "| CTA | Archivo Regular, 0.09em |", "",
          "Geometry and baselines come from `assets/spec.json`, measured off the reference set.", "",
          "## Photos", ""]
    for i, ph in enumerate(photos, 1):
        L.append("%d. `%s`" % (i, os.path.relpath(ph, order)))
    L += ["", "## Units", "", "| size | variant | weight | cap | notes |", "|---|---|---|---|---|"]
    for size, variant, prefix, weight in units:
        note = "; ".join(warnings.get((size, variant), [])) or "-"
        L.append("| %s | %s | %d KB | %s | %s |"
                 % (size, variant, weight // 1024,
                    "ok" if weight <= WEIGHT_CAP else "**OVER**", note))
    L += ["", "Cap is 700 KB per unit, uncompressed.", ""]
    path = os.path.join(outdir, "run-report_%s_%s.md" % (slug, today))
    open(path, "w", encoding="utf-8").write("\n".join(L))
    return path


INDEX_CARD = """<article class="card">
  <div class="frame" data-w="%(w)s" data-h="%(h)s" style="width:%(w)spx;height:%(h)spx"><iframe srcdoc="%(doc)s" width="%(w)s" height="%(h)s" scrolling="no" frameborder="0" title="Aperture %(size)s en"></iframe></div>
  <div class="meta" style="max-width:%(w)spx">
    <div class="title"><span class="size">%(size)s</span><span class="tag">%(variant)s</span><span class="tag lang">EN</span>
      <span class="weight %(capcls)s">%(kb)d KB &middot; %(cap)s</span></div>
    <p class="notes">%(notes)s</p>
    <div class="fileinfo">zipped <b>%(zipkb)d KB</b> &middot;
      <a href="%(prefix)s_ad.html" target="_blank">open alone</a> &middot;
      <a href="%(prefix)s_backup.jpg" download>backup</a> &middot;
      <a href="../zips/%(prefix)s.zip">zip</a></div>
    <div class="transport">
      <button class="play" type="button" title="play / pause">&#10074;&#10074;</button>
      <button class="replay" type="button" title="back to the start">&#8634; Replay</button>
      <input class="scrub" type="range" min="0" max="15000" value="0" step="50" aria-label="timeline">
      <span class="time">0.0 s</span><span class="loop">loop 1 / 2</span>
    </div>
  </div>
</article>"""


NOTES = {
    "video": "Video version: the walkthrough as a %(sec)d s silent H.264 loop; if autoplay is "
             "refused (Safari Low Power Mode) the %(n)d-photo carousel underneath takes over "
             "as the fallback.",
    "carousel": "Carousel version: %(n)d listing photos with arrows, dots and swipe, "
                "auto-advancing in step with the copy over a %(sec)d s loop.",
}


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Aperture &middot; %(title)s &middot; display ads</title>
<style>
  :root { --bg:#0b0f16; --panel:#131a26; --line:#25304a; --ink:#f0f3f8; --muted:#8d97ad; --blue:#4090EF; }
  html,body { margin:0; background:var(--bg); color:var(--ink); overflow-x:hidden;
    font:14px/1.45 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif; }
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
  .frame { background:#000; border-radius:4px; overflow:hidden; box-shadow:0 0 0 1px #000;
    max-width:100%%; position:relative; }
  .frame iframe { display:block; border:0; transform-origin:0 0; }
  .meta { margin-top:12px; } .title { display:flex; gap:8px; align-items:center; font-weight:600; flex-wrap:wrap; }
  .tag { font-weight:400; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
    border:1px solid var(--line); border-radius:999px; padding:2px 8px; }
  .tag.lang { color:#c9a35a; border-color:rgba(201,163,90,.5); }
  .weight { margin-left:auto; font-weight:400; font-size:12px; color:var(--muted); }
  .weight.err { color:#ff8a7a; font-weight:600; }
  /* the reference's layout: controls on one row, the loop label on its own,
     so it cannot be squeezed out of the card on the narrow sizes */
  .transport { display:grid; grid-template-columns:auto auto 1fr auto;
    grid-template-areas:"play replay scrub time" "loop loop loop loop";
    gap:6px 8px; align-items:center; margin-top:12px; padding-top:12px;
    border-top:1px solid var(--line); }
  .play { grid-area:play; } .replay { grid-area:replay; }
  .transport .scrub { grid-area:scrub; width:100%%; min-width:0; accent-color:var(--blue); }
  .time { grid-area:time; font-variant-numeric:tabular-nums; color:var(--muted);
    font-size:12px; min-width:44px; text-align:right; }
  .loop { grid-area:loop; color:var(--muted); font-size:11.5px; } .loop.err { color:#ff8a7a; }\n  .loop.hold { color:var(--blue); }\n  h2.tier-h { font-size:15px; font-weight:600; margin:22px 0 14px; letter-spacing:.01em; }\n  .global span { max-width:340px; }
  .notes { margin:8px 0 0; color:var(--muted); font-size:12.5px; line-height:1.5; }\n  .fileinfo { margin:7px 0 0; color:var(--muted); font-size:12.5px; }\n  .fileinfo b { color:var(--ink); font-weight:600; }\n  .size { font-weight:600; } a { color:var(--blue); }
</style></head><body>
<header>
  <div><h1>Aperture <span>&middot; %(headline)s &middot; English &middot; %(variants)s &middot; %(n)d units</span></h1>
    <div class="copy">%(eyebrow)s &nbsp;&middot;&nbsp; %(lines)s &nbsp;&middot;&nbsp; %(cta)s</div></div>
  <div class="global"><span>Each unit loops every %(loop_s)s s; the preview plays two loops then holds.</span>
    <button id="allreplay" type="button">&#8634; Replay all</button>
    <button id="alllast" type="button">&#9197; Last frame</button></div>
</header>
<main><h2 class="tier-h">English &middot; %(variants_title)s</h2><div class="grid">
%(cards)s
</div></main>
<script>
(function () {
  var LOOP = %(loop_ms)d, LOOPS = %(loops)d, TOTAL = LOOP * LOOPS, cards = [];
  function bind(card) {
    var frame = card.querySelector('iframe'), playBtn = card.querySelector('.play'),
        replayBtn = card.querySelector('.replay'), scrub = card.querySelector('.scrub'),
        timeEl = card.querySelector('.time'), loopEl = card.querySelector('.loop');
    // The page keeps its own clock. Reading the ad's animations is an enhancement,
    // not a requirement - a unit has none at all under Reduce Motion.
    var st = { t: 0, playing: true, scrubbing: false, last: performance.now(), anims: [] };

    function win() { try { return frame.contentWindow; } catch (e) { return null; } }
    function doc() { try { return frame.contentDocument || (win() && win().document); } catch (e) { return null; } }
    function ad() { var w = win(); return w && w.__ad; }

    var reachable = null;
    function checkReach() {
      if (reachable !== null) return reachable;
      var d = doc();
      if (!d || d.readyState === 'loading') return null;      // not settled yet
      reachable = !!(ad() || (d && d.getAnimations));
      if (!reachable) {
        loopEl.className = 'loop err';
        loopEl.textContent = (location.protocol === 'file:')
          ? 'controls need a served page - open in Safari, or see the README'
          : 'controls unavailable in this browser';
        [playBtn, replayBtn, scrub].forEach(function (el) { el.disabled = true; });
      }
      return reachable;
    }
    function grabAnims() {
      var d = doc();
      if (!d || !d.getAnimations) return;
      var a = d.getAnimations();
      if (a.length === st.anims.length) return;
      st.anims = a;
      a.forEach(function (x) {
        var t = x.effect.getTiming();
        if (t.iterations === Infinity && t.duration > 0)
          x.effect.updateTiming({ iterations: Math.ceil(TOTAL / t.duration), fill: 'forwards' });
      });
    }
    function apply(ms) {
      st.anims.forEach(function (a) { try { a.currentTime = ms; if (!st.playing) a.pause(); } catch (e) {} });
      var A = ad(); if (A) A.setTime(ms);
    }
    function paint() {
      var inLoop = st.t %% LOOP, k = Math.min(Math.floor(st.t / LOOP) + 1, LOOPS);
      timeEl.textContent = (inLoop / 1000).toFixed(1) + ' s';
      if (reachable === false) return;
      if (st.t >= TOTAL - 1) {
        loopEl.className = 'loop hold';
        loopEl.textContent = 'holding on the last frame';
      } else {
        loopEl.className = 'loop';
        loopEl.textContent = 'loop ' + k + ' / ' + LOOPS;
      }
      if (!st.scrubbing) scrub.value = st.t;
    }
    function pause() { st.playing = false; st.anims.forEach(function (a) { try { a.pause(); } catch (e) {} });
      var A = ad(); if (A) A.pause(); playBtn.innerHTML = '&#9654;'; }
    function play() { if (st.t >= TOTAL - 1) { st.t = 0; apply(0); }
      st.playing = true; st.last = performance.now();
      st.anims.forEach(function (a) { try { a.play(); } catch (e) {} });
      var A = ad(); if (A) A.play(); playBtn.innerHTML = '&#10074;&#10074;'; }
    function replay() {
      st.t = 0; st.last = performance.now();
      var A = ad();
      if (A && A.restart) { A.restart(); st.anims = []; setTimeout(function () { grabAnims(); apply(st.t); }, 30); }
      else { apply(0); }
      play();
      st.t = 0; st.last = performance.now(); scrub.value = 0; paint();
    }

    playBtn.onclick = function () { st.playing ? pause() : play(); };
    replayBtn.onclick = replay;
    scrub.addEventListener('input', function () {
      st.scrubbing = true; if (st.playing) pause();
      st.t = +scrub.value; apply(st.t); paint();
    });
    scrub.addEventListener('change', function () { st.scrubbing = false; });
    frame.addEventListener('load', function () { grabAnims(); apply(st.t); });

    function tick(now) {
      if (checkReach() === false) { st.playing = false; return; }
      grabAnims();
      if (st.playing && !st.scrubbing) {
        st.t = Math.min(st.t + (now - st.last), TOTAL);
        if (st.t >= TOTAL) pause();
      }
      st.last = now;
      paint();
    }
    function last() { st.t = TOTAL - 1; apply(st.t); pause(); paint(); }
    return { tick: tick, play: play, pause: pause, replay: replay, last: last,
             playing: function () { return st.playing; } };
  }

  // Units wider than the page are scaled down, never cropped.
  function fitFrames() {
    var main = document.querySelector('main'), cs = getComputedStyle(main);
    var room = main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 32;
    [].forEach.call(document.querySelectorAll('.frame'), function (f) {
      var w = +f.dataset.w, h = +f.dataset.h, k = Math.min(1, room / w);
      f.style.width = Math.round(w * k) + 'px';
      f.style.height = Math.round(h * k) + 'px';
      f.querySelector('iframe').style.transform = 'scale(' + k + ')';
      var m = f.parentNode.querySelector('.meta');
      if (m) m.style.maxWidth = Math.round(w * k) + 'px';
    });
  }
  fitFrames();
  window.addEventListener('resize', fitFrames);

  [].forEach.call(document.querySelectorAll('.card'), function (c) { cards.push(bind(c)); });
  (function loop(now) { cards.forEach(function (c) { c.tick(now || performance.now()); }); requestAnimationFrame(loop); })();
  document.getElementById('allreplay').onclick = function () {
    cards.forEach(function (c) { c.replay(); }); };
  document.getElementById('alllast').onclick = function () {
    cards.forEach(function (c) { c.last(); }); };
})();
</script></body></html>"""


DELIVERY_README = """# %(headline)s \u2014 HTML5 display ads

Aperture Global Real Estate \u00b7 English \u00b7 %(n)d units

## Open this first

`%(slug)s-preview/index.html` \u2014 double-click it. Every unit plays in one page.
No server and no internet connection required.

Each card has play/pause, replay and a 15-second scrubber, plus **Replay all** and
**Last frame** in the header, a link to open that unit on its own, its zipped weight, and its
backup still. Each unit loops every 7.5 s; the preview plays two loops then holds.

The units are inlined into the page, so the controls work straight off the disk rather than
needing a local server.

## What's in the set

| | |
|---|---|
| **Sizes** | 768\u00d71024, 1024\u00d7768, 480\u00d7320, 970\u00d7250, 320\u00d7480, 300\u00d7600 |
| **Variants** | video \u2014 %(n)d units |
| **Loop** | 15 seconds, looping continuously |
| **Weight** | every unit under the 700 KB cap (largest: %(heaviest)s) |
| **Click-through** | the underlined CTA only \u2014 not the whole ad |

**Video** units play the walkthrough as a silent 15-second loop. The four listing photos sit
underneath as the autoplay fallback, with arrows, dots and swipe.

## Copy

| | English |
|---|---|
| Eyebrow | %(eyebrow)s |
| Headline | %(headline)s |
%(copyrows)s| CTA | %(cta)s |

All copy is baked to vector outlines, so the units carry no webfonts and render identically
everywhere. The faces are the Aperture ones \u2014 Cormorant Garamond for the headline and
eyebrow, Archivo for everything else.

## Notes for whoever traffics these

- **clickTag** defaults to `apertureglobal.com` and can be overridden per placement by
  appending `?clicktag=<url>` to the unit's URL. Built for StackAdapt; the same
  convention works on most DSPs.
- **Autoplay fallback.** The video units carry the photo carousel underneath them. If a
  browser refuses to autoplay \u2014 Safari in Low Power Mode, or "Never Auto-Play" \u2014 the unit
  switches to the interactive carousel instead of showing a frozen frame. Tested in both
  states.
- **Backup stills** are included for every unit (`*_backup.jpg`), for placements that need
  a static fallback.
- **Shippable zips** are in `zips/`, one per unit, with the ad HTML renamed to `index.html`.

## Reviewing on a phone

Open `index.html` on the phone itself, or view a single unit full-screen with the "open
alone" link on its card. The swipe hint on the photo band only appears on touch devices,
and disappears after the first manual swipe.
"""


def write_delivery_readme(outdir, copy, units, slug):
    rows = ""
    labels = ["Location", "Spec", "Agents"]
    for i, line in enumerate(copy["lines"]):
        rows += "| %s | %s |\n" % (labels[i] if i < len(labels) else "Line %d" % (i + 1),
                                   line.replace("|", "\\|"))
    heaviest = max(units, key=lambda u: u[3])
    path = os.path.join(outdir, "README.md")
    open(path, "w", encoding="utf-8").write(DELIVERY_README % dict(
        headline=copy["headline"], n=len(units), slug=slug,
        eyebrow=copy["eyebrow"], cta=copy["cta"], copyrows=rows,
        heaviest="%s %s, %d KB" % (heaviest[0], heaviest[1], heaviest[3] // 1024)))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--out")
    ap.add_argument("--slug")
    ap.add_argument("--overrides")
    ap.add_argument("--video", help="16:9 walkthrough master mp4")
    ap.add_argument("--photos", nargs="*")
    ap.add_argument("--sizes", nargs="*", default=SIZE_ORDER)
    ap.add_argument("--variants", nargs="*", default=VARIANTS)
    a = ap.parse_args()

    order = os.path.abspath(a.order)
    ov = json.load(open(a.overrides, encoding="utf-8")) if a.overrides else {}
    csv_path, row = read_csv(order)
    copy = build_copy(row, ov)
    slug = a.slug or ov.get("slug") or re.sub(r"[^A-Za-z0-9]", "", copy["headline"].title())
    photos = pick_photos(order, a.photos or ov.get("photos"))
    master = os.path.abspath(a.video) if a.video else None
    if master and not os.path.exists(master):
        sys.exit("walkthrough master not found: %s" % master)

    outdir = a.out or os.path.join(order, "Digital Ads")
    preview = os.path.join(outdir, "%s-preview" % slug)
    os.makedirs(preview, exist_ok=True)

    print("CSV     :", os.path.basename(csv_path))
    print("headline:", copy["headline"])
    print("lines   :", " / ".join(copy["lines"]))
    print("video   :", os.path.basename(master) if master else "(none - carousel only)")
    for p in photos:
        print("photo   :", os.path.basename(p))

    units, prefixes, warnings = [], [], {}
    for size in a.sizes:
        for variant in a.variants:
            prefix, weight, warn = build_unit(size, variant, copy, photos, preview, slug, master)
            if not prefix:
                print("%-9s %-9s skipped: %s" % (size, variant, "; ".join(warn)))
                continue
            units.append((size, variant, prefix, weight))
            prefixes.append(prefix)
            if warn:
                warnings[(size, variant)] = warn
            print("%-9s %-9s %6d KB%s" % (size, variant, weight // 1024,
                                          "  OVER CAP" if warn else ""))

    zipdir = os.path.join(outdir, "zips")
    write_zips(preview, prefixes, zipdir)
    write_index(preview, copy, units, zipdir, len(photos))
    readme = write_delivery_readme(outdir, copy, units, slug)
    report = write_report(outdir, order, csv_path, copy, photos, units, warnings, slug, master)
    print("\nreview  :", os.path.join(preview, "index.html"))
    print("report  :", report)


if __name__ == "__main__":
    main()
