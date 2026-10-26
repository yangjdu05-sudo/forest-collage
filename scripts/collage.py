#!/usr/bin/env python3
"""Forest-scrapbook collage renderer.
Usage:
  python3 collage.py layout.json out.jpg [--check]     render (+ crop-check sheet out_check.jpg)
  python3 collage.py layout.json out.mp4 --animate     looping MP4 + GIF
  python3 collage.py --compare sheet.jpg A.jpg B.jpg C.jpg
Positions are fractions of the canvas: Claude decides WHERE things go, this script decides HOW they look."""
import json, math, random, sys, os
import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFilter, ImageChops, ImageEnhance, ImageFont

HOME = os.path.expanduser("~/.forest_collage")
MODEL_DIR = os.environ.get("COLLAGE_MODELS", os.path.join(HOME, "models"))
FONTS = ["/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/System/Library/Fonts/PingFang.ttc", "C:/Windows/Fonts/msyh.ttc"]
def _font_ok(f):
    try:
        ImageFont.truetype(f, 12); return True
    except Exception:
        return False


FALLBACK_FONT = next((f for f in [os.path.join(HOME, "fonts", "ZCOOLKuaiLe-Regular.ttf")] + FONTS if os.path.exists(f) and _font_ok(f)), None)
SYMBOL_FONT = next((f for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] + FONTS if os.path.exists(f) and _font_ok(f)), None)


def font_path(name):
    """Font for captions: a path, or a short name like "LongCang" for one of the downloaded handwritten fonts."""
    if name and not os.path.exists(name):
        name = os.path.join(HOME, "fonts", name if name.endswith(".ttf") else name + "-Regular.ttf")
    if name and os.path.exists(name) and _font_ok(name):
        return name
    env = os.environ.get("COLLAGE_FONT")
    return env if env and _font_ok(env) else FALLBACK_FONT
SS = 4
BEAUTIFY = False

PALETTE = {"mint": [178, 238, 214], "lime": [214, 242, 168], "pink": [246, 186, 204], "lilac": [206, 190, 242],
           "cream": [255, 250, 232], "sky": [184, 222, 246], "white": [255, 255, 255]}


PAGE = {}  # p1..p5: colours sampled from this page's photos (filled in render)


def _col(c):
    if isinstance(c, str):
        return PAGE.get(c) or PALETTE.get(c) or PALETTE["white"]
    return c


def _accents(n):
    a = [k for k in ("a1", "a2", "a3", "a4") if k in PAGE][:n]
    return a or ["cream", "white"][:max(1, n)]


def page_palette(imgs, k=5):
    """Pick the page's main hues from its photos (weighted by saturation x brightness), returned as soft, light
    versions so decorations echo the photos instead of defaulting to pink. p1 = most dominant hue."""
    import colorsys
    px = []
    for im in imgs:
        t = im.copy(); t.thumbnail((160, 160))
        px.append(np.asarray(t.convert("HSV")).reshape(-1, 3).astype(np.float32))
    a = np.vstack(px)
    a = a[(a[:, 1] > 75) & (a[:, 2] > 90)]
    if len(a) < 50:
        return {}
    wts = a[:, 1] * a[:, 2] / 65025.0
    hist, _ = np.histogram(a[:, 0], bins=24, range=(0, 256), weights=wts)
    order = np.argsort(-hist)
    chosen = []
    for b in order:
        if hist[b] < hist[order[0]] * 0.02 or len(chosen) >= k:
            break
        if all(min(abs(b - c), 24 - abs(b - c)) >= 2 for c in chosen):
            chosen.append(b)
    out = {}
    for i, b in enumerate(chosen):
        sel = a[(a[:, 0] >= b * 256 / 24) & (a[:, 0] < (b + 1) * 256 / 24)]
        h = float(np.median(sel[:, 0])) / 255
        sat = min(float(np.median(sel[:, 1])) / 255, 0.62)
        r, g, bb = colorsys.hsv_to_rgb(h, max(0.38, sat * 0.85), 0.98)
        out["p%d" % (i + 1)] = [int(255 * (0.85 * c + 0.15)) for c in (r, g, bb)]
    # accents a1..: the page's colours other than the dominant one (usually the background green),
    # so decorations echo the photos AND still stand out
    for i in range(1, len(chosen)):
        out["a%d" % i] = out["p%d" % (i + 1)]
    if "a1" not in out and "p1" in out:
        out["a1"] = out["p1"]
    return out


# ------------------------------------------------------------------ photo helpers
def load(path, base, pad=None):
    p = path if os.path.isabs(path) else os.path.join(base, path)
    img = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    return pad_image(img, pad) if pad else img


def cover(img, w, h, focus=(0.5, 0.5), zoom=1.0):
    if zoom < 1:  # zooming out past the photo's edge would show black: extend it softly instead
        img = pad_image(img, 1 / zoom); zoom = 1.0
    iw, ih = img.size
    if iw / ih > w / h:
        ch = ih / zoom; cw = ch * w / h
    else:
        cw = iw / zoom; ch = cw * h / w
    x0 = min(max(focus[0] * iw - cw / 2, 0), iw - cw)
    y0 = min(max(focus[1] * ih - ch / 2, 0), ih - ch)
    return img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((w, h), Image.LANCZOS)


def straighten(img, deg):
    """Rotate by deg (positive = counter-clockwise) and crop to the largest upright rectangle."""
    w, h = img.size
    r = img.rotate(deg, resample=Image.BICUBIC, expand=True)
    a = math.radians(abs(deg)); sin_a, cos_a = math.sin(a), math.cos(a)
    long_, short = (h, w) if w <= h else (w, h)
    if short <= 2 * sin_a * cos_a * long_ or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * short
        wr, hr = (x / sin_a, x / cos_a) if w >= h else (x / cos_a, x / sin_a)
    else:
        c2 = cos_a * cos_a - sin_a * sin_a
        wr, hr = (w * cos_a - h * sin_a) / c2, (h * cos_a - w * sin_a) / c2
    cx, cy = r.width / 2, r.height / 2
    return r.crop((int(cx - wr / 2), int(cy - hr / 2), int(cx + wr / 2), int(cy + hr / 2)))


# ------------------------------------------------------------------ grading
PRESETS = {
    "forest": dict(lift=0.04, gain=0.97, rgb=(0.93, 1.03, 0.97), sat=1.12, bright=1.03,
                   shadow_tint=(-0.01, 0.025, 0.02), hi_tint=(0.0, 0.015, 0.012)),
    "warm": dict(lift=0.045, gain=0.97, rgb=(1.00, 1.035, 0.90), sat=1.22, bright=1.03,
                 shadow_tint=(0.00, 0.025, 0.01), hi_tint=(0.03, 0.02, -0.02)),
    # default: true to life like Fuji straight-out-of-camera. No black lift (lifted blacks read as grey haze), no colour cast.
    "clear": dict(lift=0.0, gain=1.0, rgb=(1.0, 1.0, 1.0), sat=1.04, bright=1.02,
                  shadow_tint=(0.0, 0.0, 0.0), hi_tint=(0.0, 0.0, 0.0)),
}
MATCH = {}  # per-page targets for "match": photos are pulled toward each other before the shared look is applied


def _stats(img):
    a = np.asarray(img.convert("RGB").resize((96, 96))).astype(np.float32) / 255
    m = a.reshape(-1, 3).mean(0)
    mx, mn = a.max(2), a.min(2)
    sat = float(((mx - mn) / np.maximum(mx, 1e-3)).mean())
    return m, float((a * np.array([0.3, 0.59, 0.11], np.float32)).sum(2).mean()), sat


def set_match(images, strength):
    """Page targets: neutral white balance, the page's median brightness (never darker than 0.48) and median saturation."""
    MATCH.clear()
    if not strength or not images:
        return
    st = [_stats(i) for i in images]
    MATCH.update(k=float(strength), lum=max(0.48, float(np.median([s[1] for s in st]))), sat=float(np.median([s[2] for s in st])))


def match_photo(img):
    """Coordinate one photo with the rest of the page: soften its colour cast, nudge brightness and saturation toward
    the page targets. Small, capped moves only so each photo still looks like itself."""
    if not MATCH:
        return img
    k = MATCH["k"]; m, lum, sat = _stats(img)
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255
    gain = np.clip((m.mean() / np.maximum(m, 1e-3)) ** (0.25 * k), 0.965, 1.035)  # gentle grey-world: soften a cast, keep a sunset pink
    a = a * gain
    if 0.02 < lum < 0.98:
        target = lum + (MATCH["lum"] - lum) * k * 0.5  # half-way only: a sunset silhouette is meant to be dark
        g = np.clip(np.log(max(target, 0.02)) / np.log(lum), 0.9, 1.1)
        a = np.clip(a, 0, 1) ** g
    s = np.clip((MATCH["sat"] / max(sat, 1e-3)) ** k, 0.96, 1.1)  # lift dull photos more than we mute vivid ones
    l = (a * np.array([0.3, 0.59, 0.11], np.float32)).sum(2, keepdims=True)
    a = l + (a - l) * s
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
TINT = [0.64, 0.86, 0.74]  # fresh forest green


def grade(img, preset="clear"):
    p = PRESETS[preset]
    img = match_photo(img)
    img = ImageEnhance.Brightness(ImageEnhance.Color(img).enhance(p["sat"])).enhance(p["bright"])
    a = np.asarray(img).astype(np.float32) / 255.0 * np.array(p["rgb"], np.float32)
    lum = a.mean(axis=2, keepdims=True)
    a = a + (1 - lum) * np.array(p["shadow_tint"], np.float32) + lum * np.array(p["hi_tint"], np.float32)
    a = p["lift"] + a * p["gain"]
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def finish(img, bloom=0.32, grain=7, seed=1, unify=0.35, vig=0.0):
    """Highlight bloom + one-palette soft-light tint + light vignette + CCD grain."""
    a = np.asarray(img).astype(np.float32) / 255.0
    lum = a.mean(axis=2)
    hi = np.clip((lum - 0.62) / 0.38, 0, 1)[..., None] * a
    b = np.asarray(Image.fromarray((hi * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(img.width / 40))).astype(np.float32) / 255 * bloom
    a = 1 - (1 - a) * (1 - b)
    t = np.array(TINT, np.float32)
    soft = np.where(t < 0.5, 2 * a * t + a * a * (1 - 2 * t), 2 * a * (1 - t) + np.sqrt(np.clip(a, 0, 1)) * (2 * t - 1))
    a = a * (1 - unify) + soft * unify
    h, w = lum.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    a = a * (1 - vig * np.clip(d - 0.6, 0, 1))[..., None]
    a = a + np.random.default_rng(seed).normal(0, grain / 255.0, (h, w))[..., None]
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


# ------------------------------------------------------------------ gentle beautify (never reshapes faces)
_CV = {}


def _cv():
    """Load OpenCV + face detector + 68-point landmarks once; any missing piece degrades gracefully."""
    if _CV:
        return _CV
    cvc = os.path.join(MODEL_DIR, "cvc")
    if os.path.isdir(cvc) and cvc not in sys.path:
        sys.path.insert(0, cvc)
    import cv2
    net = fm = None
    caffe = os.path.join(MODEL_DIR, "res10.caffemodel")
    try:
        if os.path.exists(caffe):
            net = cv2.dnn.readNetFromCaffe(os.path.join(MODEL_DIR, "deploy.prototxt"), caffe)
    except Exception:
        net = None
    lbf = os.path.join(MODEL_DIR, "lbfmodel.yaml")
    try:
        if os.path.exists(lbf):
            fm = cv2.face.createFacemarkLBF(); fm.loadModel(lbf)
    except Exception:
        fm = None
    _CV.update(cv2=cv2, net=net, fm=fm)
    return _CV


def find_faces(rgb):
    C = _cv(); cv2 = C["cv2"]
    H, W = rgb.shape[:2]
    if C["net"] is not None:
        C["net"].setInput(cv2.dnn.blobFromImage(cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (300, 300)), 1.0, (300, 300), (104, 177, 123)))
        det = C["net"].forward()[0, 0]
        boxes = [[int(d[3] * W), int(d[4] * H), int((d[5] - d[3]) * W), int((d[6] - d[4]) * H)] for d in det if d[2] > 0.6]
    else:
        xml = [os.path.join(d, "haarcascade_frontalface_default.xml") for d in
               (getattr(getattr(cv2, "data", None), "haarcascades", ""), os.path.join(os.path.dirname(cv2.__file__), "data"))]
        xml = next((x for x in xml if os.path.exists(x)), None)
        if not xml:
            return [], []
        casc = cv2.CascadeClassifier(xml)
        boxes = [list(map(int, b)) for b in casc.detectMultiScale(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 1.08, 8, minSize=(int(max(24, 0.04 * min(W, H))),) * 2)]
    # small faces matter too (a person standing further away in a forest shot): keep anything above ~2% of the photo
    mn = max(14, 0.02 * min(W, H))
    boxes = [b for b in boxes if b[2] > mn and b[3] > mn and b[0] < W and b[1] < H]
    lms = []
    if boxes and C["fm"] is not None:
        ok, res = C["fm"].fit(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), np.array(boxes))
        if ok:
            lms = [r[0].astype(np.float32) for r in res]
    return boxes, lms


def _poly(shape, pts, blur):
    cv2 = _cv()["cv2"]
    m = np.zeros(shape, np.float32)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 1.0)
    return cv2.GaussianBlur(m, (0, 0), max(1, blur)) if blur else m


def beautify(img, smooth=0.45, makeup="auto"):
    """Faces only: moderate skin smoothing that keeps texture; blush + lip colour only when the face looks bare.
    Face shape is NEVER changed. Returns the photo unchanged if no face is found."""
    try:
        C = _cv()
    except Exception:
        return img
    cv2 = C["cv2"]
    rgb = np.asarray(img).copy(); H, W = rgb.shape[:2]
    boxes, lms = find_faces(rgb)
    if not boxes:
        return img
    out = rgb.astype(np.float32)
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = ((ycc[..., 1] > 130) & (ycc[..., 1] < 178) & (ycc[..., 2] > 75) & (ycc[..., 2] < 135)).astype(np.float32)
    for k, b in enumerate(boxes):
        p = lms[k] if k < len(lms) else None
        fw = b[2]
        if p is not None:
            face = np.vstack([p[0:17], (p[17:27] - (p[30] - p[27]) * 0.6)[::-1]])
            m = _poly((H, W), cv2.convexHull(face.astype(np.float32)).reshape(-1, 2), fw * 0.03)
            for idx in (range(36, 42), range(42, 48), range(48, 60), range(17, 22), range(22, 27)):
                hole = p[list(idx)]; c = hole.mean(0); hole = c + (hole - c) * 1.35
                m = m * (1 - _poly((H, W), cv2.convexHull(hole).reshape(-1, 2), fw * 0.015))
        else:
            m = np.zeros((H, W), np.float32)
            cv2.ellipse(m, (b[0] + b[2] // 2, b[1] + int(b[3] * 0.55)), (int(b[2] * 0.45), int(b[3] * 0.55)), 0, 0, 360, 1, -1)
            m = cv2.GaussianBlur(m, (0, 0), fw * 0.04)
        m = (m * cv2.GaussianBlur(skin, (0, 0), 3))[..., None]
        kd = max(5, int(fw / 28)) | 1
        sm = cv2.bilateralFilter(rgb, kd, 35, kd).astype(np.float32)
        detail = out - cv2.GaussianBlur(out, (0, 0), 1.5)
        ret = (sm + detail * 0.5) * 1.035 + np.array([3, 1, 0], np.float32)
        out = out * (1 - m * smooth) + ret * (m * smooth)
        if p is None or makeup is False:
            continue
        hsv = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        lip = _poly((H, W), p[48:60], 0) * (1 - _poly((H, W), p[60:68], 0))
        lip_sat = float((hsv[..., 1] * lip).sum() / (lip.sum() + 1)) / 255
        r = fw * 0.13
        cm = np.zeros((H, W), np.float32)
        for c in (p[1] * 0.3 + p[31] * 0.3 + p[40] * 0.4, p[15] * 0.3 + p[35] * 0.3 + p[47] * 0.4):
            cv2.ellipse(cm, (int(c[0]), int(c[1] + r * 0.2)), (int(r * 1.1), int(r * 0.8)), 0, 0, 360, 1, -1)
        cm = cv2.GaussianBlur(cm, (0, 0), r * 0.55)
        cheek_red = float(((ycc[..., 1].astype(np.float32) - 128) * cm).sum() / (cm.sum() + 1))
        if makeup is True or lip_sat < 0.36:
            lm_ = cv2.GaussianBlur(lip, (0, 0), fw * 0.008)[..., None]
            out = out * (1 - lm_ * 0.38) + out * (np.array([196, 82, 96], np.float32) / 255 * 1.25) * (lm_ * 0.38)
        if makeup is True or cheek_red < 24:
            out = out * (1 - cm[..., None] * 0.16) + np.array([244, 150, 160], np.float32) * (cm[..., None] * 0.16)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# ------------------------------------------------------------------ shapes
def heart_pts(w, h):
    pts = []
    for i in range(240):
        t = 2 * math.pi * i / 240
        pts.append((16 * math.sin(t) ** 3, -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))))
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    return [((x - min(xs)) / (max(xs) - min(xs)) * w, (y - min(ys)) / (max(ys) - min(ys)) * h) for x, y in pts]


def shape_mask(shape, w, h):
    W, H = w * SS, h * SS
    m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    if shape == "rect":
        d.rectangle([0, 0, W, H], fill=255)
    elif shape == "rounded":
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(min(W, H) * 0.08), fill=255)
    elif shape == "circle":
        d.ellipse([0, 0, W - 1, H - 1], fill=255)
    elif shape == "heart":
        d.polygon(heart_pts(W - 1, H - 1), fill=255)
    elif shape == "clover":
        r, off, cx, cy = min(W, H) * 0.27, min(W, H) * 0.225, W / 2, H / 2
        for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
            d.ellipse([cx + dx * off - r, cy + dy * off - r, cx + dx * off + r, cy + dy * off + r], fill=255)
        d.rectangle([cx - off, cy - off, cx + off, cy + off], fill=255)
    elif shape == "flower":
        R = min(W, H) / 2; r = R * 0.42
        for i in range(5):
            a = math.radians(-90 + i * 72)
            x, y = W / 2 + (R - r) * math.cos(a), H / 2 + (R - r) * math.sin(a)
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        d.ellipse([W / 2 - R * 0.6, H / 2 - R * 0.6, W / 2 + R * 0.6, H / 2 + R * 0.6], fill=255)
    elif shape == "star":
        ro, ri, cx, cy = min(W, H) / 2, min(W, H) / 4.6, W / 2, H / 2 + H * 0.04
        d.polygon([(cx + (ro if i % 2 == 0 else ri) * math.cos(math.radians(-90 + i * 36)),
                    cy + (ro if i % 2 == 0 else ri) * math.sin(math.radians(-90 + i * 36))) for i in range(10)], fill=255)
    elif shape == "oval":
        d.ellipse([0, 0, W - 1, H - 1], fill=255)
    elif shape == "arch":
        r = W / 2
        d.ellipse([0, 0, W - 1, min(H, W) - 1], fill=255)
        d.rectangle([0, r, W, H], fill=255)
    elif shape == "scallop":  # stamp-like scalloped edge
        r = min(W, H) * 0.045
        d.rectangle([r, r, W - r, H - r], fill=255)
        for x in np.arange(r, W - r + 1, 2 * r * 0.95):
            d.ellipse([x - r, 0, x + r, 2 * r], fill=255); d.ellipse([x - r, H - 2 * r, x + r, H], fill=255)
        for y in np.arange(r, H - r + 1, 2 * r * 0.95):
            d.ellipse([0, y - r, 2 * r, y + r], fill=255); d.ellipse([W - 2 * r, y - r, W, y + r], fill=255)
    elif shape == "cloud":
        for cx, cy, rx, ry in [(0.28, 0.62, 0.26, 0.30), (0.50, 0.40, 0.30, 0.36), (0.74, 0.58, 0.26, 0.30), (0.50, 0.70, 0.40, 0.26)]:
            d.ellipse([(cx - rx) * W, (cy - ry) * H, (cx + rx) * W, (cy + ry) * H], fill=255)
    elif shape == "blob":
        pts = []
        for i in range(180):
            t = 2 * math.pi * i / 180
            rr = 0.46 * (1 + 0.07 * math.sin(3 * t + 0.6) + 0.05 * math.sin(5 * t + 1.7) + 0.03 * math.sin(2 * t))
            pts.append((W / 2 + rr * W * math.cos(t), H / 2 + rr * H * math.sin(t)))
        d.polygon(pts, fill=255)
    else:
        raise ValueError(shape)
    return m.resize((w, h), Image.LANCZOS)


# fraction of the frame (centred) that every shape is guaranteed to show; keep the subject inside it
SAFE = {"rect": 0.94, "rounded": 0.9, "scallop": 0.86, "arch": 0.8, "oval": 0.68, "circle": 0.68, "blob": 0.62,
        "cloud": 0.5, "clover": 0.6, "flower": 0.58, "heart": 0.5, "star": 0.4}


def colored(mask, color, alpha=1.0):
    lay = Image.new("RGBA", mask.size, tuple(color) + (0,))
    lay.putalpha(mask.point(lambda v: int(v * alpha)))
    return lay


def colorize(lay, colors, direction="v"):
    """Recolour a white-drawn layer with a gradient across its drawn area."""
    if not colors:
        return lay
    cols = np.stack([np.array(_col(c), np.float32) for c in colors])
    a = np.asarray(lay.getchannel("A")); ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return lay
    H, W = a.shape
    tx = np.clip((np.arange(W) - xs.min()) / max(1, xs.max() - xs.min()), 0, 1)[None, :]
    ty = np.clip((np.arange(H) - ys.min()) / max(1, ys.max() - ys.min()), 0, 1)[:, None]
    t = np.broadcast_to(tx, (H, W)) if direction == "h" else ((tx + ty) / 2 if direction == "d" else np.broadcast_to(ty, (H, W)))
    n = len(cols) - 1
    if n == 0:
        rgb = np.broadcast_to(cols[0], (H, W, 3))
    else:
        seg = np.minimum((t * n).astype(int), n - 1); f = (t * n - seg)[..., None]
        rgb = cols[seg] * (1 - f) + cols[seg + 1] * f
    return Image.fromarray(np.dstack([rgb, a.astype(np.float32)]).astype(np.uint8), "RGBA")


def glow_on(canvas, lay, blur):
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(lay)


# ------------------------------------------------------------------ inset photos

def isolate_object(src, spec, w, h, shape):
    """One complete object and nothing else: take the object out of the photo (no fingers, plates, spoons, other
    fruit) and set it, whole, on a soft clean background inside the frame. spec["obj"] = [x0,y0,x1,y1] (fractions of
    the photo) around the object; spec["isolate"] = "auto" (AI cut-out) or "ellipse" (for round things like an orange
    partly covered by fingers: keeps the ellipse, trims inward by spec["inset"])."""
    iw, ih = src.size; x0, y0, x1, y1 = spec.get("obj", [0, 0, 1, 1])
    sub = src.crop((int(x0 * iw), int(y0 * ih), int(x1 * iw), int(y1 * ih)))
    if spec["isolate"] == "ellipse":
        k = spec.get("inset", 0.04); m = Image.new("L", sub.size, 0)
        ImageDraw.Draw(m).ellipse([sub.width * k, sub.height * k, sub.width * (1 - k), sub.height * (1 - k)], fill=255)
        cut = sub.convert("RGBA"); cut.putalpha(m.filter(ImageFilter.GaussianBlur(max(1, sub.width * 0.006))))
    else:
        cut = cutout_rgba(sub, "%s|obj|%s" % (spec["src"], spec.get("obj")))
    cols = spec.get("bg", "none")
    f = SAFE.get(shape, 0.6) * spec.get("fill", 0.98)
    if cols == "none":  # default: just the object itself, no colour disc behind it; its own outline becomes the edge
        f = spec.get("fill", 0.92)
        sc = min(w * f / cut.width, h * f / cut.height); cw, chh = max(1, int(cut.width * sc)), max(1, int(cut.height * sc))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0)); off = spec.get("offset", [0, 0])
        out.alpha_composite(cut.resize((cw, chh), Image.LANCZOS), ((w - cw) // 2 + int(off[0] * w), (h - chh) // 2 + int(off[1] * h)))
        return out
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.clip(np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / 1.2, 0, 1)
    bg = Image.fromarray(np.clip(_grad_rgb(cols, t), 0, 255).astype(np.uint8)).convert("RGBA")
    sc = min(w * f / cut.width, h * f / cut.height); cw, chh = max(1, int(cut.width * sc)), max(1, int(cut.height * sc))
    cut = cut.resize((cw, chh), Image.LANCZOS)
    off = spec.get("offset", [0, 0])
    sh = Image.new("RGBA", bg.size, (0, 0, 0, 0)); a = cut.getchannel("A")
    sh.paste(Image.new("RGBA", cut.size, (30, 50, 35, 70)), ((w - cw) // 2 + 3 + int(off[0] * w), (h - chh) // 2 + 5 + int(off[1] * h)), a)
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(2, w * 0.02))))
    bg.alpha_composite(cut, ((w - cw) // 2 + int(off[0] * w), (h - chh) // 2 + int(off[1] * h)))
    return bg.convert("RGB")


def edge_line(mask, color, width, dashed=False, gap=0, dash=20.0, alpha=0.95):
    """Thin line (solid or dashed) following the outline of a binary mask, drawn on a transparent layer."""
    out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    m = mask.filter(ImageFilter.MaxFilter(2 * gap + 1)) if gap > 0 else mask
    S = 2  # supersample for smooth lines
    big = m.resize((m.width * S, m.height * S), Image.NEAREST)
    try:
        cv2 = _cv()["cv2"]
        cs, _ = cv2.findContours((np.asarray(big) > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        contours = [c.reshape(-1, 2).astype(np.float32) for c in cs if len(c) > 8]
    except Exception:
        contours = None
    col = tuple(color[:3]) + (int(255 * alpha),)
    if contours is None:  # no OpenCV: solid ring from the mask
        ring = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(2 * (width // 2) + 1)), m)
        out.alpha_composite(colored(ring.filter(ImageFilter.GaussianBlur(0.7)), color[:3], alpha))
        return out
    lay = Image.new("RGBA", big.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay); w2 = max(2, int(width * S))
    on, off = dash * S, dash * S * 0.6
    for c in contours:
        c = np.vstack([c, c[:1]])
        if len(c) > 30:  # smooth pixel stair-steps
            k = 5; pad_ = np.vstack([c[-k:], c, c[:k]])
            c = np.stack([np.convolve(pad_[:, i], np.ones(k) / k, mode="same")[k:-k] for i in (0, 1)], 1)
        if not dashed:
            d.line([tuple(p) for p in c], fill=col, width=w2, joint="curve")
            continue
        seg = np.hypot(*np.diff(c, axis=0).T); s_ = np.concatenate([[0], np.cumsum(seg)])
        period = on + off
        cur = []
        for p, dist in zip(c, s_):
            if (dist % period) < on:
                cur.append(tuple(p))
            elif cur:
                if len(cur) > 1:
                    d.line(cur, fill=col, width=w2, joint="curve")
                cur = []
        if len(cur) > 1:
            d.line(cur, fill=col, width=w2, joint="curve")
        if not dashed:
            continue
    lay = lay.resize(mask.size, Image.LANCZOS)
    out.alpha_composite(lay)
    return out


def defringe(rgb, alpha):
    """Remove the light/dark halo a cut-out picks up from its old background: every semi-transparent edge pixel
    takes the colour of the nearest solid pixels of the subject instead of the background mixed in."""
    a = np.asarray(alpha).astype(np.float32) / 255
    c = np.asarray(rgb.convert("RGB")).astype(np.float32)
    solid = (a > 0.97).astype(np.float32)
    r = max(2, int(min(alpha.size) * 0.006))
    num = np.asarray(Image.fromarray((c * solid[..., None]).clip(0, 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(r))).astype(np.float32)
    den = np.asarray(Image.fromarray((solid * 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(r))).astype(np.float32)[..., None] / 255
    inner = np.where(den > 0.02, num / np.maximum(den, 1e-3), c)
    edge = ((a > 0.01) & (a < 0.97))[..., None]
    return Image.fromarray(np.where(edge, inner, c).clip(0, 255).astype(np.uint8))


def subject_alpha(src, spec, w, h):
    """Cut-out mask computed on the whole photo (more context = cleaner edges than cutting a tight crop), then
    cover-cropped exactly like the frame so it lines up pixel for pixel."""
    cut = cutout_rgba(src, "full|%s|%s|%s|%s" % (spec["src"], spec.get("crop"), spec.get("straighten"), src.size), trim=False)
    a = cover(cut, w, h, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0)).getchannel("A")
    return solid_mask(a)


def solid_mask(alpha):
    """Turn a soft AI mask into a clean cut: no half-transparent ghosts, no holes where white clothes met a white wall,
    no stray specks. Keep the main subject (and big pieces touching it), close small gaps, fill holes, pull the edge in
    about a pixel so no old-background rim is left, then soften just enough to avoid jaggies."""
    cv2 = _cv()["cv2"]
    a = np.asarray(alpha)
    b = (a > 110).astype(np.uint8)
    k = max(3, int(min(a.shape) * 0.02) | 1)
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n > 1:
        big = st[1:, cv2.CC_STAT_AREA].max()
        keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.06 * big]
        b = np.isin(lab, keep).astype(np.uint8)
    flood = b.copy(); hgt, wid = b.shape
    ff = np.zeros((hgt + 2, wid + 2), np.uint8)
    for seed in [(0, 0), (wid - 1, 0), (0, hgt - 1), (wid - 1, hgt - 1)]:
        if flood[seed[1], seed[0]] == 0:
            cv2.floodFill(flood, ff, seed, 1)
    holes = (flood == 0)
    b = (b.astype(bool) | holes).astype(np.uint8) * 255
    m = Image.fromarray(b).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.9))
    return m


def render_inset(canvas, spec, base, preset):
    CW, CH = canvas.size
    box = spec["box"]
    X, Y, W = int(box[0] * CW), int(box[1] * CH), int(box[2] * CW)
    H = W if len(box) == 3 else int(box[3] * CH)
    shape, style = spec.get("shape", "rect"), spec.get("style", "none")
    if style == "polaroid":
        shape = "rect"

    color = tuple(_col(spec.get("color", [255, 255, 255])))
    pad = int(min(W, H) * 0.035) if style in ("card", "polaroid") else 0
    padb = int(min(W, H) * 0.16) if style == "polaroid" else pad
    src = load(spec["src"], base)
    if spec.get("beautify", BEAUTIFY):
        src = beautify(src)
    if spec.get("straighten"):
        src = straighten(src, spec["straighten"])
    if spec.get("crop"):
        cx0, cy0, cx1, cy1 = spec["crop"]; iw, ih = src.size
        src = src.crop((int(cx0 * iw), int(cy0 * ih), int(cx1 * iw), int(cy1 * ih)))
    src = pad_image(src, spec.get("pad"))
    obj_alpha = None
    if spec.get("isolate"):
        iso = isolate_object(src, spec, W - 2 * pad, H - pad - padb, shape)
        if iso.mode == "RGBA":  # transparent background: the object's own outline is the frame
            obj_alpha = iso.getchannel("A"); photo = grade(iso.convert("RGB"), preset)
        else:
            photo = grade(iso, preset)
        if spec.get("rotate") and spec.get("upright", True):  # frame may be rotated (clover hearts); the object stays upright
            photo = photo.rotate(-spec["rotate"], resample=Image.BICUBIC)
            if obj_alpha is not None:
                obj_alpha = obj_alpha.rotate(-spec["rotate"], resample=Image.BICUBIC)
    elif spec.get("popout"):  # the photo continues above the frame; the person's head and arms are cut out there
        E = int(H * spec["popout"])
        ext = cover(src, W, H + E, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0))
        photo = grade(ext.crop((0, E, W, E + H)), preset)
    else:
        photo = grade(cover(src, W - 2 * pad, H - pad - padb, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0)), preset)
    if spec.get("blur_bg") and obj_alpha is None:  # messy room behind the person: keep the person sharp, blur the rest
        fullsrc = ext if spec.get("popout") else cover(src, W - 2 * pad, H - pad - padb, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0))
        alpha_ = subject_alpha(src, spec, *fullsrc.size)
        soft = grade(fullsrc, preset).filter(ImageFilter.GaussianBlur(min(W, H) * spec["blur_bg"]))
        sharp_ = grade(fullsrc, preset).convert("RGBA"); sharp_.putalpha(alpha_)
        soft = soft.convert("RGBA"); soft.alpha_composite(sharp_); soft = soft.convert("RGB")
        if spec.get("popout"):
            ext = soft; photo = soft.crop((0, E, W, E + H))
        else:
            photo = soft
    mask = shape_mask(shape, W - 2 * pad, H - pad - padb).filter(ImageFilter.GaussianBlur(max(1.5, min(W, H) * 0.004)))
    frame_mask = mask
    if spec.get("bg") == "none" and obj_alpha is None:  # remove the photo's own background: only the person stays in the frame
        if spec.get("popout"):
            full_a = subject_alpha(src, spec, W, H + E)
            ext = defringe(ext, full_a)
            photo = grade(ext.crop((0, E, W, E + H)), preset)
            sub_a = full_a.crop((0, E, W, E + H))
        else:
            raw = cover(src, W, H, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0))
            sub_a = subject_alpha(src, spec, W, H)
            photo = grade(defringe(raw, sub_a), preset)
        mask = ImageChops.multiply(mask, sub_a)
    if spec.get("erase"):  # [[x, y, r], ...] in frame fractions: wipe stray bits a cut-out picked up
        er = Image.new("L", mask.size, 255); de = ImageDraw.Draw(er)
        for ex_, ey_, er_ in spec["erase"]:
            R_ = er_ * mask.size[0]; de.ellipse([ex_ * mask.size[0] - R_, ey_ * mask.size[1] - R_, ex_ * mask.size[0] + R_, ey_ * mask.size[1] + R_], fill=0)
        mask = ImageChops.multiply(mask, er.filter(ImageFilter.GaussianBlur(1.5)))
    if obj_alpha is not None:
        mask = obj_alpha
    if spec.get("feather"):
        k = int(min(W, H) * spec["feather"]); mw, mh = mask.size  # noqa
        mask = Image.new("L", (mw, mh), 0); mask.paste(shape_mask(shape, max(8, mw - 2 * k), max(8, mh - 2 * k)), (k, k))
        mask = mask.filter(ImageFilter.GaussianBlur(k * 0.7))
    M = int(min(W, H) * 0.12)
    layer = Image.new("RGBA", (W + 2 * M, H + 2 * M), (0, 0, 0, 0))
    if style in ("card", "stroke", "glow", "polaroid"):
        bm = Image.new("L", layer.size, 0); bm.paste(mask, (M + pad, M + pad))
        layer.alpha_composite(colored(bm.filter(ImageFilter.GaussianBlur(min(W, H) * (0.05 if style == "glow" else 0.03))), color, 0.75 if style == "glow" else 0.5))
    if style == "card":
        card = shape_mask("rounded" if shape in ("rect", "rounded") else shape, W, H).filter(ImageFilter.GaussianBlur(1.5))
        layer.alpha_composite(colored(card, (250, 252, 245), 0.45), (M, M))
    if style == "polaroid":
        card = shape_mask("rect", W, H).filter(ImageFilter.GaussianBlur(1.2))
        layer.alpha_composite(colored(card, (252, 252, 246), 0.82), (M, M))
    ph = photo.convert("RGBA"); ph.putalpha(mask.point(lambda v: int(v * spec.get("opacity", 1.0))))
    layer.alpha_composite(ph, (M + pad, M + pad))
    if style == "border":
        bw = max(3, int(min(W, H) * spec.get("rim", 0.022)))
        big = Image.new("L", layer.size, 0); big.paste(mask.point(lambda v: 255 if v > 127 else 0), (M + pad, M + pad))
        rim = big.filter(ImageFilter.MaxFilter(2 * bw + 1)).filter(ImageFilter.GaussianBlur(1))
        sh = colored(rim.filter(ImageFilter.GaussianBlur(bw * 2.5)), (15, 30, 20), spec.get("shadow", 0.35))
        base_l = Image.new("RGBA", layer.size, (0, 0, 0, 0)); base_l.alpha_composite(sh, (int(bw * 0.6), int(bw)))
        base_l.alpha_composite(colored(rim, tuple(_col(spec.get("color", "white"))), 0.96))
        base_l.alpha_composite(layer); layer = base_l
    if style in ("stroke", "glow"):
        sw = spec.get("stroke", max(2, int(min(W, H) * 0.006)))
        big = Image.new("L", layer.size, 0); big.paste(mask.point(lambda v: 255 if v > 127 else 0), (M + pad, M + pad))
        ring = ImageChops.subtract(big.filter(ImageFilter.MaxFilter(2 * sw + 1)), big)
        layer.alpha_composite(colored(ring.filter(ImageFilter.GaussianBlur(4)), color, 0.8))
        layer.alpha_composite(colored(ring.filter(ImageFilter.GaussianBlur(0.8)), color, 0.7))
    if style in ("line", "dash"):  # outline only: a thin solid or dashed line on the edge, no colour fill or halo
        big = Image.new("L", layer.size, 0); big.paste((frame_mask if spec.get("bg") == "none" else mask).point(lambda v: 255 if v > 127 else 0), (M + pad, M + pad))
        lw = spec.get("stroke", max(2, int(min(W, H) * spec.get("width", 0.009))))
        gap = spec.get("gap", 0.0)  # >0: line sits slightly outside the edge, like a cut line around a sticker
        ln = edge_line(big, color, lw, dashed=style == "dash", gap=int(min(W, H) * gap),
                       dash=spec.get("dash", 0.05) * min(W, H), alpha=spec.get("line_alpha", 0.95))
        if spec.get("line_glow"):  # a faint soft glow hugging the line (user asked for it explicitly)
            g_ = ln.filter(ImageFilter.GaussianBlur(lw * 2.5)); ga = g_.getchannel("A").point(lambda v: min(255, int(v * 2.2 * spec["line_glow"])))
            g_.putalpha(ga); layer.alpha_composite(g_)
        layer.alpha_composite(ln)
    dx = dy = 0
    if spec.get("rotate"):
        old = layer.size
        layer = layer.rotate(spec["rotate"], resample=Image.BICUBIC, expand=True)
        dx, dy = (layer.width - old[0]) / 2, (layer.height - old[1]) / 2
    canvas.alpha_composite(layer, (int(X - M - dx), int(Y - M - dy)))
    if spec.get("popout") and not spec.get("isolate"):
        keep = E + int(H * 0.25)  # also redraw the top of the body inside the frame, so the person sits in front of the line
        pa = subject_alpha(src, spec, W, H + E)
        if not spec.get("blur_bg"):
            ext = defringe(ext, pa) if spec.get("bg") != "none" else ext
        a = np.asarray(pa).astype(np.float32)
        ramp = np.ones(a.shape[0], np.float32); ramp[keep:] = 0
        fade = int(H * 0.06); ramp[keep - fade:keep] = np.linspace(1, 0, fade)
        a = a * ramp[:, None]
        rgb = (ext if spec.get("blur_bg") else grade(ext, preset)).convert("RGBA"); rgb.putalpha(Image.fromarray(a.astype(np.uint8)))
        canvas.alpha_composite(rgb, (X, Y - E))
    if spec.get("outline") and spec.get("bg") == "none" and spec.get("popout"):
        # comic-style stroke around the whole cut-out person (inside the frame + the part popping out above it);
        # also hides any leftover rim from the old background. outline: [[colour, width], ...] inner to outer,
        # width as a fraction of the frame width.
        full_a = subject_alpha(src, spec, W, H + E)
        if spec.get("erase"):
            er = Image.new("L", full_a.size, 255); de = ImageDraw.Draw(er)
            for ex_, ey_, er_ in spec["erase"]:
                R_ = er_ * W; de.ellipse([ex_ * W - R_, E + ey_ * H - R_, ex_ * W + R_, E + ey_ * H + R_], fill=0)
            full_a = ImageChops.multiply(full_a, er)
        vis = Image.new("L", full_a.size, 0); vis.paste(full_a.crop((0, 0, W, keep)), (0, 0))
        inner = full_a.crop((0, E, W, E + H)); vis.paste(ImageChops.lighter(vis.crop((0, E, W, E + H)), inner), (0, E))
        Mo = int(W * 0.06); base_m = Image.new("L", (W + 2 * Mo, H + E + 2 * Mo), 0); base_m.paste(vis, (Mo, Mo))
        prev = base_m; rings = []
        for col_, wid_ in spec["outline"]:
            k = max(3, int(W * wid_) * 2 + 1)
            grown = prev.filter(ImageFilter.MaxFilter(k if k < 60 else 59))
            rings.append((ImageChops.subtract(grown, prev).filter(ImageFilter.GaussianBlur(0.8)), col_)); prev = grown
        for ring_, col_ in rings:
            canvas.alpha_composite(colored(ring_, tuple(_col(col_)[:3]), 1.0), (X - Mo, Y - E - Mo))


def render_cutout(canvas, spec):
    """Translucent card with a shape cut out of it, cross-stitch grid texture."""
    CW, CH = canvas.size
    x, y, w, h = spec["box"]
    X, Y, W, H = int(x * CW), int(y * CH), int(w * CW), int(h * CH)
    card = Image.new("L", (W, H), 255)
    hole = shape_mask(spec.get("shape", "flower"), int(W * 0.7), int(W * 0.7) if H > W * 0.7 else int(H * 0.8))
    card.paste(0, (int((W - hole.width) / 2), int((H - hole.height) / 2)), hole)
    lay = colored(card, tuple(_col(spec.get("color", "pink"))), spec.get("opacity", 0.6)); d = ImageDraw.Draw(lay)
    step = max(6, W // 28)
    for g in range(0, W, step):
        d.line([(g, 0), (g, H)], fill=(255, 255, 255, 40))
    for g in range(0, H, step):
        d.line([(0, g), (W, g)], fill=(255, 255, 255, 40))
    lay.putalpha(ImageChops.multiply(lay.getchannel("A"), card.filter(ImageFilter.GaussianBlur(max(2, W * 0.012)))))
    canvas.alpha_composite(lay, (X, Y))


# ------------------------------------------------------------------ decorations
def render_sparkles(canvas, spec, rng):
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"]
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    al = int(255 * spec.get("alpha", 0.85))
    for _ in range(spec.get("count", 8)):
        cx, cy = rng.uniform(x0, x1) * CW, rng.uniform(y0, y1) * CH
        r = rng.uniform(*spec.get("size", [0.008, 0.022])) * CW
        d.polygon([(cx, cy - r), (cx + r * .16, cy - r * .16), (cx + r, cy), (cx + r * .16, cy + r * .16),
                   (cx, cy + r), (cx - r * .16, cy + r * .16), (cx - r, cy), (cx - r * .16, cy - r * .16)], fill=(255, 255, 255, al))
    lay = colorize(lay, spec.get("colors"), spec.get("dir", "v"))
    g = lay.filter(ImageFilter.GaussianBlur(CW / 120))
    canvas.alpha_composite(g); canvas.alpha_composite(g); canvas.alpha_composite(lay)


def render_halo(canvas, spec):
    CW, CH = canvas.size
    cx, cy, r = spec["pos"][0] * CW, spec["pos"][1] * CH, spec.get("r", 0.12) * CW
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(_col(spec.get("color", "cream"))) + (int(255 * spec.get("alpha", 0.5)),))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(r * 0.6)))


def bezier(p0, p1, p2, p3, n=60):
    return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0],
             (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1])
            for t in [i / n for i in range(n + 1)]]


def render_vine(canvas, spec, rng):
    CW, CH = canvas.size; S = 2
    lay = Image.new("RGBA", (CW * S, CH * S), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    col = (255, 255, 255, int(255 * spec.get("alpha", 0.75)))
    lw = int(spec.get("width", 3.0) * S)
    pts = [(q[0] * CW * S, q[1] * CH * S) for q in spec["points"]]
    stem = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        nx, ny = -(b[1] - a[1]), (b[0] - a[0])
        bend = rng.uniform(0.18, 0.32) * (1 if i % 2 else -1)
        c1 = (a[0] + (mx - a[0]) * 0.7 + nx * bend, a[1] + (my - a[1]) * 0.7 + ny * bend)
        c2 = (b[0] - (b[0] - mx) * 0.7 + nx * bend, b[1] - (b[1] - my) * 0.7 + ny * bend)
        stem += bezier(a, c1, c2, b)
    d.line(stem, fill=col, width=lw, joint="curve")
    n = spec.get("curls", 4)
    for k in range(1, n + 1):
        i = int(len(stem) * k / (n + 1))
        px, py = stem[i]; qx, qy = stem[min(i + 1, len(stem) - 1)]
        side = 1 if k % 2 else -1
        ang = math.atan2(qy - py, qx - px) + side * math.pi / 2
        R = rng.uniform(0.022, 0.036) * CW * S
        cx, cy = px + math.cos(ang) * R, py + math.sin(ang) * R
        turns = rng.uniform(1.2, 1.7)
        d.line([(cx + R * (1 - 0.78 * t) * math.cos(ang + math.pi - side * t * turns * 2 * math.pi),
                 cy + R * (1 - 0.78 * t) * math.sin(ang + math.pi - side * t * turns * 2 * math.pi)) for t in [j / 119 for j in range(120)]],
               fill=col, width=max(2, int(lw * 0.8)), joint="curve")
        for t in range(3):
            dr = (2.2 - t * 0.5) * S * 1.4
            ox, oy = px + math.cos(ang + 0.9) * (R * 1.7 + t * dr * 4), py + math.sin(ang + 0.9) * (R * 1.7 + t * dr * 4)
            d.ellipse([ox - dr, oy - dr, ox + dr, oy + dr], outline=col, width=max(1, S))
    glow_on(canvas, colorize(lay.resize((CW, CH), Image.LANCZOS), spec.get("colors"), spec.get("dir", "v")), CW / 260)


PIXEL = {
    "flower2": ["....##.##....", "...#..#..#...", "...#.....#...", "....#...#....", ".##..###..##.", "#..#.#.#.#..#", "#....###....#",
                ".##.#...#.##.", "...#.....#...", "...#..#..#...", "....##.##....", "......#......", "......#......", ".....###....."],
    "flower": ["..##.##..", ".#..#..#.", ".#.....#.", "..#.#.#..", ".#..#..#.", ".#.....#.", "..##.##..", "....#....", "...###..."],
    "heart": [".##...##.", "#..#.#..#", "#...#...#", "#.......#", ".#.....#.", "..#...#..", "...#.#...", "....#...."],
    "heart2": [".##...##.", "####.####", "#########", "#########", ".#######.", "..#####..", "...###...", "....#...."],
    "sparkle": ["....#....", "....#....", "...###...", "#########", "...###...", "....#....", "....#...."],
    "butterfly": ["#.......#", "##.....##", "###.#.###", "####.####", ".###.###.", "..##.##..", ".###.###.", "###...###", ".#.....#."],
    "mushroom": ["...#####...", ".##.###.##.", "#.#######.#", "###.###.###", "###########", "....###....", "....###....", "...#####..."],
    "clover": [".##...##.", "####.####", "####.####", ".###.###.", "....#....", ".###.###.", "####.####", "####.####", ".##.#.##.", "....#....", "...#....."],
    "note": ["...####", "...#..#", "...#..#", "...#..#", ".###.##", "####...", ".##...."],
    "star": ["....#....", "....#....", "...###...", "#########", ".#######.", "..#####..", "..##.##..", ".##...##.", ".#.....#."],
    "moon": ["...####..", "..###....", ".###.....", ".##......", "###......", "###......", "###......", ".##......", ".###.....", "..###....", "...####.."],
    "cloud": ["....###.......", "...#####.##...", ".##########...", "#############.", "##############", ".############."],
    "sun": ["....#....", ".#..#..#.", "..#####..", ".#######.", "#########", ".#######.", "..#####..", ".#..#..#.", "....#...."],
    "leaf": ["......###", "....#####", "...######", "..######.", ".######..", ".#####...", "#.###....", "#........"],
    "cherry": ["......##.", ".....#...", "....#.#..", "...#...#.", ".##....##", "####..###", "####..###", ".##....#."],
    "bow": ["##.....##", "###...###", "####.####", "#########", "####.####", "###...###", "##.....##"],
    "tulip": ["#.#.#", "#####", "#####", ".###.", "..#..", "#.#.#", ".###.", "..#.."],
    "drop": ["...#...", "..###..", ".#####.", "#######", "#######", ".#####.", "..###.."],
}


def render_dots(canvas, spec):
    """Pixel icon made of tiny dots (2x2 dots per pixel)."""
    CW, CH = canvas.size
    cell = spec.get("cell", 0.008) * CW
    x0, y0 = spec["pos"][0] * CW, spec["pos"][1] * CH
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    r, al = cell / 2 * 0.32, int(255 * spec.get("alpha", 0.7))
    for j, row in enumerate(PIXEL[spec.get("pattern", "flower2")]):
        for i, ch in enumerate(row):
            if ch == "#":
                for a in range(2):
                    for b in range(2):
                        cx, cy = x0 + i * cell + (a + 0.5) * cell / 2, y0 + j * cell + (b + 0.5) * cell / 2
                        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, al))
    glow_on(canvas, colorize(lay, spec.get("colors", _accents(2)), spec.get("dir", "v")), cell * 0.6)


def render_dotfield(canvas, spec, rng):
    """CCD dot-matrix texture: columns of tiny dots fading in and out."""
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"][0] * CW, spec["region"][1] * CH, spec["region"][2] * CW, spec["region"][3] * CH
    step = spec.get("step", 0.0075) * CW; r = step * 0.22
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    nx, ny = max(1, int((x1 - x0) / step)), max(1, int((y1 - y0) / step))
    field = np.asarray(Image.fromarray((np.array([[rng.random() for _ in range(6)] for _ in range(8)]) * 255).astype(np.uint8))
                       .resize((nx, ny), Image.BICUBIC)).astype(np.float32) / 255
    al = int(255 * spec.get("alpha", 0.55))
    for i in range(nx):
        if rng.random() >= spec.get("columns", 0.55):
            continue
        for j in range(ny):
            fx, fy = i / max(nx - 1, 1), j / max(ny - 1, 1)
            if rng.random() < field[j, i] * min(1, min(fx, 1 - fx, fy, 1 - fy) * 4) * spec.get("density", 1.1):
                cx, cy = x0 + i * step, y0 + j * step
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, al))
    glow_on(canvas, colorize(lay, spec.get("colors"), spec.get("dir", "v")), step * 0.5)


def render_confetti(canvas, spec, rng):
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"]
    cols = [_col(c) for c in spec.get("colors", _accents(3) + ["cream"])]
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for _ in range(spec.get("count", 12)):
        cx, cy = rng.uniform(x0, x1) * CW, rng.uniform(y0, y1) * CH
        r = rng.uniform(*spec.get("size", [0.0022, 0.006])) * CW
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(cols[rng.randrange(len(cols))]) + (int(255 * spec.get("alpha", 0.85)),))
    glow_on(canvas, lay, CW / 220)


def render_symbols(canvas, spec):
    CW, CH = canvas.size
    size = int(spec.get("size", 0.024) * CW)
    font = ImageFont.truetype(spec.get("font") or SYMBOL_FONT, size)
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    x, y = spec["pos"][0] * CW, spec["pos"][1] * CH
    for k, ch in enumerate(spec.get("text", "• ⁺ ♪ ✦ ⁺ ° ☆")):
        d.text((x, y + (k % 3 - 1) * size * 0.18), ch, font=font, fill=(255, 255, 255, int(255 * spec.get("alpha", 0.9))))
        x += d.textlength(ch, font=font) + size * 0.12
    glow_on(canvas, colorize(lay, spec.get("colors"), spec.get("dir", "h")), size * 0.18)


def render_leak(canvas, spec):
    CW, CH = canvas.size
    cx, cy, r = spec["pos"][0] * CW, spec["pos"][1] * CH, spec.get("r", 0.35) * CW
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=tuple(_col(spec.get("color", [255, 214, 160]))) + (int(255 * spec.get("alpha", 0.3)),))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(r * 0.45)))


def render_sunlight(canvas, spec):
    """Sunlight atmosphere: glow at the source plus soft rays that fade with distance."""
    CW, CH = canvas.size
    sx, sy = spec.get("pos", [0.9, 0.0]); sx, sy = sx * CW, sy * CH
    col = tuple(_col(spec.get("color", [255, 246, 214])))
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    base, spread = math.radians(spec.get("angle", 125)), math.radians(spec.get("spread", 45))
    L, n, rnd = math.hypot(CW, CH) * 1.1, spec.get("rays", 7), random.Random(4)
    for i in range(n):
        a = base - spread / 2 + spread * (i + rnd.uniform(-0.3, 0.3)) / max(1, n - 1)
        w = math.radians(rnd.uniform(1.5, 4.0))
        d.polygon([(sx, sy), (sx + L * math.cos(a - w), sy + L * math.sin(a - w)), (sx + L * math.cos(a + w), sy + L * math.sin(a + w))],
                  fill=col + (int(255 * spec.get("ray_alpha", 0.3) * rnd.uniform(0.6, 1.0)),))
    lay = lay.filter(ImageFilter.GaussianBlur(CW / 45))
    yy, xx = np.mgrid[0:CH, 0:CW]
    fade = np.clip(1 - np.hypot(xx - sx, yy - sy) / (L * spec.get("reach", 0.9)), 0, 1)
    lay.putalpha(Image.fromarray((np.asarray(lay.getchannel("A")).astype(np.float32) * fade).astype(np.uint8)))
    canvas.alpha_composite(lay)
    r = spec.get("glow", 0.22) * CW
    g = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([sx - r, sy - r, sx + r, sy + r], fill=col + (int(255 * spec.get("glow_alpha", 0.6)),))
    canvas.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * 0.6)))




def render_doodle(canvas, spec):
    """Hand-drawn style outline of a shape (heart/star/flower/clover/cloud/circle/blob/arch), glowing, in page colours."""
    CW, CH = canvas.size
    size = int(spec.get("size", 0.08) * CW)
    m = shape_mask(spec.get("shape", "heart"), size, size).point(lambda v: 255 if v > 127 else 0)
    M = size // 4
    big = Image.new("L", (size + 2 * M, size + 2 * M), 0); big.paste(m, (M, M))
    wpx = max(2, int(size * spec.get("width", 0.035)))
    ring = ImageChops.subtract(big.filter(ImageFilter.MaxFilter(2 * (wpx // 2) + 1)), big.filter(ImageFilter.MinFilter(2 * (wpx // 2) + 1)))
    lay = colored(ring.filter(ImageFilter.GaussianBlur(0.8)), (255, 255, 255), spec.get("alpha", 0.85))
    if spec.get("fill"):
        lay.alpha_composite(colored(big.filter(ImageFilter.GaussianBlur(1)), (255, 255, 255), spec["fill"]))
    if spec.get("rotate"):
        lay = lay.rotate(spec["rotate"], resample=Image.BICUBIC, expand=True)
    full = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    full.alpha_composite(lay, (int(spec["pos"][0] * CW - lay.width / 2), int(spec["pos"][1] * CH - lay.height / 2)))
    glow_on(canvas, colorize(full, spec.get("colors", _accents(2)), spec.get("dir", "d")), size * 0.06)


def render_bubbles(canvas, spec, rng):
    """Translucent soap-bubble circles with a thin rim and a highlight."""
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"]
    cols = [_col(c) for c in spec.get("colors", _accents(3))]
    for i in range(spec.get("count", 4)):
        r = int(rng.uniform(*spec.get("size", [0.02, 0.05])) * CW)
        cx, cy = int(rng.uniform(x0, x1) * CW), int(rng.uniform(y0, y1) * CH)
        c = tuple(cols[i % len(cols)])
        lay = Image.new("RGBA", (4 * r, 4 * r), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        d.ellipse([r, r, 3 * r, 3 * r], fill=c + (40,), outline=c + (170,), width=max(2, r // 14))
        d.ellipse([int(1.45 * r), int(1.35 * r), int(1.9 * r), int(1.7 * r)], fill=(255, 255, 255, 170))
        canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(0.8)), (cx - 2 * r, cy - 2 * r))


def render_text(canvas, spec):
    """Caption: one white font, short centred lines, no outline or box (a barely visible soft shadow for legibility)."""
    CW, CH = canvas.size
    size = int(spec.get("size", 0.034) * CW)
    font = ImageFont.truetype(font_path(spec.get("font")), size)
    lh = size * spec.get("line_height", 1.75)
    cx, y = spec["pos"][0] * CW, spec["pos"][1] * CH
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    for i, line in enumerate(spec["text"].split("\n")):
        x = cx - d.textlength(line, font=font) / 2 if spec.get("align", "center") == "center" else cx
        d.text((x, y + i * lh), line, font=font, fill=tuple(_col(spec.get("color", "white"))) + (245,))
        ds.text((x, y + i * lh), line, font=font, fill=(20, 40, 30, 90))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(size * 0.18)))
    canvas.alpha_composite(lay)




# ------------------------------------------------------------------ v3: padding, split panels, seams, cutout stickers, playful text
def pad_image(img, f):
    """Extend a photo outward by factor f with a blurred copy of itself, so a whole subject that touches the
    edge (a full plate, a whole fruit) still fits inside an irregular frame."""
    if not f or f <= 1:
        return img
    w, h = img.size; W, H = int(w * f), int(h * f)
    bg = img.resize((W, H)).filter(ImageFilter.GaussianBlur(max(W, H) / 40))
    k = int(min(w, h) * 0.04)
    m = Image.new("L", (w, h), 0); m.paste(255, (k, k, w - k, h - k)); m = m.filter(ImageFilter.GaussianBlur(k * 0.8))
    bg.paste(img, ((W - w) // 2, (H - h) // 2), m)
    return bg


_REMBG = {}


def _refine_alpha(mask):
    """Conservatively clean a cut-out alpha mask without inventing missing background.

    Suppress isolated specks, soften jagged edges and preserve partial transparency for hair/fine details.
    This is edge cleanup only, not semantic inpainting; inspect the result when the background is complex.
    """
    m = mask.convert("L")
    # Remove tiny isolated foreground/background speckles when OpenCV is available.
    try:
        cv2 = _cv()["cv2"]
        a = np.asarray(m)
        # Median filtering is conservative and keeps antialiasing after a final slight blur.
        a = cv2.medianBlur(a, 3)
        m = Image.fromarray(a.astype(np.uint8))
    except Exception:
        pass
    return m.filter(ImageFilter.GaussianBlur(0.6))


def _fill_holes(mask):
    """Light clothes on a light background often come out semi-transparent inside the body: make everything
    enclosed by the silhouette solid, keeping the soft edge only in a thin band at the outline."""
    try:
        cv2 = _cv()["cv2"]
        m = np.asarray(mask.convert("L"))
        solid = (m > 25).astype(np.uint8) * 255
        h, w = solid.shape; ff = solid.copy()
        cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
        filled = solid | cv2.bitwise_not(ff)
        core = cv2.erode(filled, np.ones((9, 9), np.uint8))
        return Image.fromarray(np.where(core > 0, 255, np.where(filled > 0, m, 0)).astype(np.uint8))
    except Exception:
        return mask


def cutout_rgba(img, key, trim=True):
    """Cut the main subject out of a photo. Uses rembg when installed, otherwise OpenCV GrabCut.
    Refines mask edges conservatively. Complex hair, transparent objects and cluttered backgrounds still need review.
    Masks are cached by key."""
    cache = os.path.join(HOME, "cache"); os.makedirs(cache, exist_ok=True)
    import hashlib
    mp = os.path.join(cache, hashlib.md5(key.encode()).hexdigest() + ".png")
    if os.path.exists(mp):
        mask = Image.open(mp).convert("L")
    else:
        try:
            from rembg import remove, new_session
            if "s" not in _REMBG:
                _REMBG["s"] = new_session("isnet-general-use")
            small = img.copy(); small.thumbnail((1280, 1280))
            mask = remove(small, session=_REMBG["s"], only_mask=True).resize(img.size, Image.LANCZOS)
        except Exception:
            cv2 = _cv()["cv2"]
            small = img.copy(); small.thumbnail((800, 800)); a = np.asarray(small)
            m = np.zeros(a.shape[:2], np.uint8); bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
            h, w = m.shape; cv2.grabCut(cv2.cvtColor(a, cv2.COLOR_RGB2BGR), m, (int(w * .06), int(h * .04), int(w * .88), int(h * .92)), bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
            mask = Image.fromarray(np.where((m == 1) | (m == 3), 255, 0).astype(np.uint8)).resize(img.size).filter(ImageFilter.GaussianBlur(2))
        mask = _refine_alpha(mask)
        mask = _fill_holes(mask)
        mask.save(mp)
    rgba = img.convert("RGBA"); rgba.putalpha(mask)
    if not trim:
        return rgba
    bb = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
    return rgba.crop(bb) if bb else rgba


def render_sticker(canvas, spec, base, preset):
    """A cut-out subject pasted like a sticker: cream outline + soft coloured glow + light shadow, no frame."""
    CW, CH = canvas.size
    img = load(spec["src"], base)
    if spec.get("straighten"):
        img = straighten(img, spec["straighten"])
    if spec.get("crop"):
        x0, y0, x1, y1 = spec["crop"]; iw, ih = img.size
        img = img.crop((int(x0 * iw), int(y0 * ih), int(x1 * iw), int(y1 * ih)))
    if spec.get("beautify", BEAUTIFY):
        img = beautify(img)
    cut = cutout_rgba(img, "%s|%s|%s" % (spec["src"], spec.get("crop"), spec.get("straighten")))
    W = int(spec["box"][2] * CW); H = int(cut.height * W / cut.width)
    cut = cut.resize((W, H), Image.LANCZOS)
    rgb = grade(cut.convert("RGB"), preset).convert("RGBA"); rgb.putalpha(cut.getchannel("A"))
    if spec.get("flip"):
        rgb = ImageOps.mirror(rgb)
    ow = max(2, int(W * (spec.get("outline") or 0.012)))
    M = ow * 4
    a = Image.new("L", (W + 2 * M, H + 2 * M), 0); a.paste(rgb.getchannel("A").point(lambda v: 255 if v > 110 else 0), (M, M))
    ring = a.filter(ImageFilter.MaxFilter(2 * ow + 1)).filter(ImageFilter.GaussianBlur(1.2))
    lay = Image.new("RGBA", a.size, (0, 0, 0, 0))
    if spec.get("glow", 0):  # off by default: the user dislikes coloured halos around cut-outs
        lay.alpha_composite(colored(ring.filter(ImageFilter.GaussianBlur(ow * 2.2)), tuple(_col(spec.get("color", "cream"))), spec["glow"]))
    if spec.get("outline", 0) > 0:
        lay.alpha_composite(colored(ring, (253, 252, 244), 0.95))
    lay.alpha_composite(rgb, (M, M))
    full_sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    X, Y = int(spec["box"][0] * CW) - M, int(spec["box"][1] * CH) - M
    full_sh.alpha_composite(colored(ring, (20, 40, 25), spec.get("shadow", 0.2)), (X + ow, Y + int(ow * 1.4)))
    canvas.alpha_composite(full_sh.filter(ImageFilter.GaussianBlur(ow * 1.3)))
    canvas.alpha_composite(lay, (X, Y))


def render_seam(canvas, spec):
    """Light, glowing divider between split panels (straight or gently wavy), like a strip of washi light."""
    CW, CH = canvas.size
    (x0, y0), (x1, y1) = spec["points"]
    amp, n = spec.get("wave", 0.0), 200
    L = math.hypot((x1 - x0) * CW, (y1 - y0) * CH)
    nx, ny = -(y1 - y0) * CH / L, (x1 - x0) * CW / L
    pts = []
    for i in range(n + 1):
        t = i / n
        o = amp * CW * math.sin(t * math.pi * 2 * spec.get("waves", 3))
        pts.append(((x0 + (x1 - x0) * t) * CW + nx * o, (y0 + (y1 - y0) * t) * CH + ny * o))
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    w = max(3, int(spec.get("width", 0.012) * CW))
    d.line(pts, fill=(255, 255, 255, int(255 * spec.get("alpha", 0.9))), width=w, joint="curve")
    lay = colorize(lay, spec.get("colors", ["cream", "white"]), spec.get("dir", "d"))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(w * 1.6)))
    canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(w * 0.3)))


def render_text_bounce(canvas, spec):
    """Playful caption: each character tilted, bouncing up and down and slightly varied in size; white with a soft shadow."""
    CW, CH = canvas.size
    px = int(spec.get("size", 0.06) * CW)
    font = font_path(spec.get("font"))
    rng = random.Random(spec.get("seed", 5))
    lh = px * spec.get("line_height", 1.5)
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    for li, line in enumerate(spec["text"].split("\n")):
        gl = []
        for i, ch in enumerate(line):
            s = int(px * (1.12, 0.96, 1.05)[i % 3])
            t = Image.new("RGBA", (s * 2, s * 2), (0, 0, 0, 0))
            ImageDraw.Draw(t).text((s // 2, s // 3), ch, font=ImageFont.truetype(font, s), fill=tuple(_col(spec.get("color", "white"))) + (250,))
            gl.append((t.rotate(rng.uniform(5, 11) * (1 if i % 2 else -1), resample=Image.BICUBIC), s, (-1) ** i * px * 0.1))
        x = spec["pos"][0] * CW - sum(s * 0.92 for _, s, _ in gl) / 2
        for t, s, dy in gl:
            lay.alpha_composite(t, (int(x - s // 2), int(spec["pos"][1] * CH + li * lh + dy - s // 3)))
            x += s * 0.92
    sh = Image.new("RGBA", canvas.size, (20, 45, 30, 0)); sh.putalpha(lay.getchannel("A").point(lambda v: int(v * 0.75)))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(px * 0.12)), (3, 4))
    canvas.alpha_composite(lay)


def crop_rect(img, w, h, focus=(0.5, 0.5), zoom=1.0):
    iw, ih = img.size
    if iw / ih > w / h:
        ch = ih / zoom; cw = ch * w / h
    else:
        cw = iw / zoom; ch = cw * h / w
    x0 = min(max(focus[0] * iw - cw / 2, 0), iw - cw)
    y0 = min(max(focus[1] * ih - ch / 2, 0), ih - ch)
    return x0, y0, cw, ch


# ------------------------------------------------------------------ dreamy airbrush elements
# Original designs inspired only by *techniques* (airbrush grain, glow, stipple) — never copy concrete motifs from references.
def _grain_alpha(a, g, amount=0.35):
    """Break a smooth alpha map with fine grain so it reads as airbrush / spray paint, not vector."""
    n = g.random(a.shape).astype(np.float32)
    return np.clip(a * (1 - amount + amount * 2 * n), 0, 1)


def _grad_rgb(cols, t):
    cols = np.stack([np.array(_col(c)[:3], np.float32) for c in cols])
    n = len(cols) - 1
    if n == 0:
        return np.broadcast_to(cols[0], t.shape + (3,)).copy()
    t = np.clip(t, 0, 1)
    seg = np.minimum((t * n).astype(int), n - 1); f = (t * n - seg)[..., None]
    return cols[seg] * (1 - f) + cols[seg + 1] * f


def _paste_rgba(canvas, rgb, a, x0, y0):
    lay = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.clip(a, 0, 1) * 255]).astype(np.uint8), "RGBA")
    canvas.alpha_composite(lay, (int(x0), int(y0))) if x0 >= 0 and y0 >= 0 else _paste_any(canvas, lay, int(x0), int(y0))


def _paste_any(canvas, lay, x, y):
    """alpha_composite that tolerates negative offsets / overhang."""
    CW, CH = canvas.size
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(lay.width, CW - x), min(lay.height, CH - y)
    if ex <= sx or ey <= sy:
        return
    canvas.alpha_composite(lay.crop((sx, sy, ex, ey)), (x + sx, y + sy))


def _rng_np(rng):
    return np.random.default_rng(rng.randrange(1 << 30))


def render_orb(canvas, spec, rng):
    """Airbrushed glowing orb: soft radial gradient centre->edge colour, grainy; optional dark core (eye/seed)."""
    CW, CH = canvas.size
    r = spec.get("r", 0.06) * CW; cx, cy = spec["pos"][0] * CW, spec["pos"][1] * CH
    R = int(r * 1.1) + 2; yy, xx = np.mgrid[-R:R, -R:R].astype(np.float32)
    d = np.hypot(xx, yy / spec.get("squash", 1.0)) / r
    a = np.clip(1 - d, 0, 1) ** spec.get("soft", 1.0) * spec.get("alpha", 0.85)
    if spec.get("solid"):  # firmer edge: a planet / pebble rather than a glow
        a = np.clip((1 - d) * 6, 0, 1) * spec.get("alpha", 0.9)
    g = _rng_np(rng)
    a = _grain_alpha(a, g, spec.get("grain", 0.3))
    rgb = _grad_rgb(spec.get("colors", ["cream", "a1"]), d)
    if spec.get("core"):
        m = np.clip(1 - np.hypot(xx, yy) / (spec["core"] * r), 0, 1) ** 0.5
        rgb = rgb * (1 - m[..., None]) + np.array(_col(spec.get("core_color", [60, 40, 70]))[:3], np.float32) * m[..., None]
        a = np.maximum(a, m * 0.95)
    _paste_rgba(canvas, rgb, a, cx - R, cy - R)


def render_hang(canvas, spec, rng):
    """Hanging light drop: thin glowing thread from above ending in a soft grainy teardrop + faint halo."""
    CW, CH = canvas.size
    x, y = spec["pos"][0] * CW, spec["pos"][1] * CH; r = spec.get("r", 0.022) * CW
    L = spec.get("length", 0.15) * CH; cols = spec.get("colors", ["a1", "apple"])
    if spec.get("halo", True):
        render_orb(canvas, {"pos": spec["pos"], "r": spec.get("r", 0.022) * 2.6, "colors": [cols[-1], cols[0]],
                            "alpha": 0.4, "grain": 0.45}, rng)
    W = int(r * 6); H = int(L + r * 3)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    ox, oy = W // 2, int(L)  # drop centre
    d.line([(ox, 0), (ox, oy - r * 1.6)], fill=tuple(_col(cols[0])[:3]) + (230,), width=max(2, int(CW / 600)))
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(body).polygon(
        [(ox, oy - r * 2.1)] + [(ox + r * math.cos(t), oy + r * math.sin(t)) for t in np.linspace(-math.pi * 0.25, math.pi * 1.25, 60)], fill=(255, 255, 255, 255))
    # colour the drop body top->bottom and give it a highlight
    a = np.asarray(body.getchannel("A")).astype(np.float32) / 255
    yy = np.linspace(0, 1, H)[:, None] * np.ones((1, W)); t = np.clip((yy * H - (oy - r * 2.1)) / (r * 3.1), 0, 1)
    rgb = _grad_rgb([cols[0], cols[-1]], t)
    hx, hy = ox - r * 0.35, oy - r * 0.3
    Y, X = np.mgrid[0:H, 0:W]; hl = np.clip(1 - np.hypot(X - hx, Y - hy) / (r * 0.45), 0, 1) ** 1.5
    rgb = rgb * (1 - hl[..., None] * 0.8) + 255 * hl[..., None] * 0.8
    a = _grain_alpha(a, _rng_np(rng), 0.18) * spec.get("alpha", 0.92)
    drop = Image.fromarray(np.dstack([rgb, a * 255]).astype(np.uint8), "RGBA")
    thread = lay
    X0, Y0 = int(x - ox), int(y - oy)
    _paste_any(canvas, drop.filter(ImageFilter.GaussianBlur(r * 0.5)), X0, Y0)
    _paste_any(canvas, thread.filter(ImageFilter.GaussianBlur(2)), X0, Y0)
    _paste_any(canvas, thread, X0, Y0)
    _paste_any(canvas, drop, X0, Y0)


def render_pool(canvas, spec, rng):
    """Rainbow light pool lying on the ground: flat wobbly ellipse, colour drifting across, grainy."""
    CW, CH = canvas.size
    cx, cy = spec["pos"][0] * CW, spec["pos"][1] * CH
    w, h = spec.get("w", 0.3) * CW, spec.get("h", 0.05) * CH
    W2, H2 = int(w * 0.6), int(h * 0.75)
    yy, xx = np.mgrid[-H2:H2, -W2:W2].astype(np.float32)
    g = _rng_np(rng)
    wob = np.asarray(Image.fromarray((g.random((5, 9)) * 255).astype(np.uint8)).resize((2 * W2, 2 * H2), Image.BICUBIC)).astype(np.float32) / 255
    d = np.hypot(xx / (w / 2), yy / (h / 2)) + (wob - 0.5) * 0.45
    a = np.clip(1 - d, 0, 1) ** 0.9 * spec.get("alpha", 0.75)
    a = _grain_alpha(a, g, spec.get("grain", 0.3))
    t = (xx / w + 0.5) * 0.85 + wob * 0.2
    rgb = _grad_rgb(spec.get("colors", ["apple", "mango", "a2", "sky", "rice"]), t)
    _paste_rgba(canvas, rgb, a, cx - W2, cy - H2)


def render_rings(canvas, spec, rng):
    """Airbrushed concentric rings (outer->inner colours), soft and grainy, like a painted target of light."""
    CW, CH = canvas.size
    r = spec.get("r", 0.08) * CW; cx, cy = spec["pos"][0] * CW, spec["pos"][1] * CH
    cols = spec.get("colors", ["mango", "apple", "rice", "sky", "cream"]); sq = spec.get("squash", 1.0)
    R = int(r * 1.25); lay = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for i, c in enumerate(cols):
        rr = r * (1 - i / (len(cols) + 0.4))
        d.ellipse([R - rr, R - rr * sq, R + rr, R + rr * sq], fill=tuple(_col(c)[:3]) + (255,))
    lay = lay.filter(ImageFilter.GaussianBlur(r * spec.get("blur", 0.05)))
    a = np.asarray(lay.getchannel("A")).astype(np.float32) / 255
    a = _grain_alpha(a, _rng_np(rng), 0.28) * spec.get("alpha", 0.8)
    lay.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    _paste_any(canvas, lay, int(cx - R), int(cy - R))


def render_threads(canvas, spec, rng):
    """Thin glowing coloured threads hanging from above, each ending in a bead or a small curl."""
    CW, CH = canvas.size; S = 2
    lay = Image.new("RGBA", (CW * S, CH * S), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    cols = spec.get("colors", ["apple", "mango", "a2", "sky", "rice"]); wd = max(2, int(spec.get("width", 1.8) * S))
    for i, ln in enumerate(spec["lines"]):
        x, y0, y1 = ln[0] * CW * S, ln[1] * CH * S, ln[2] * CH * S
        c = tuple(_col(cols[i % len(cols)])[:3]) + (240,)
        sway = (rng.random() - 0.5) * 0.02 * CW * S
        pts = [(x + sway * math.sin(t * math.pi), y0 + (y1 - y0) * t) for t in np.linspace(0, 1, 40)]
        d.line(pts, fill=c, width=wd, joint="curve")
        ex, ey = pts[-1]; end = ln[3] if len(ln) > 3 else spec.get("end", "bead")
        if end == "bead":
            br = spec.get("bead", 0.006) * CW * S; d.ellipse([ex - br, ey - br, ex + br, ey + br], fill=c)
        elif end == "curl":
            R = 0.012 * CW * S; side = 1 if i % 2 else -1
            d.line([(ex + side * R * (1 - math.cos(t)), ey + R * math.sin(t)) for t in np.linspace(0, math.pi * 1.5, 30)], fill=c, width=wd)
        elif end == "ring":
            br = 0.01 * CW * S; d.ellipse([ex - br, ey, ex + br, ey + 2.4 * br], outline=c, width=wd)
    lay = lay.resize((CW, CH), Image.LANCZOS)
    glow_on(canvas, lay, CW / 260)


def render_loop(canvas, spec, rng):
    """Small neon loop: glowing outlined ellipse, optional soft fill."""
    CW, CH = canvas.size
    cx, cy = spec["pos"][0] * CW, spec["pos"][1] * CH; rx = spec.get("r", 0.02) * CW; ry = rx * spec.get("squash", 1.25)
    c = tuple(_col(spec.get("color", "apple"))[:3])
    M = int(max(rx, ry) * 2.5); lay = Image.new("RGBA", (2 * M, 2 * M), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    if spec.get("fill"):
        d.ellipse([M - rx, M - ry, M + rx, M + ry], fill=tuple(_col(spec["fill"])[:3]) + (220,))
    d.ellipse([M - rx, M - ry, M + rx, M + ry], outline=c + (255,), width=max(2, int(rx * spec.get("width", 0.2))))
    if spec.get("rotate"):
        lay = lay.rotate(spec["rotate"], resample=Image.BICUBIC)
    _paste_any(canvas, lay.filter(ImageFilter.GaussianBlur(rx * 0.45)), int(cx - M), int(cy - M))
    _paste_any(canvas, lay.filter(ImageFilter.GaussianBlur(0.7)), int(cx - M), int(cy - M))


def render_sprayflower(canvas, spec, rng):
    """Stippled spray-paint flower: soft blurred petals overlaid with thousands of tiny dots, airbrushed core, optional stem."""
    CW, CH = canvas.size
    g = _rng_np(rng)
    cx, cy = spec["pos"][0] * CW, spec["pos"][1] * CH; R = spec.get("size", 0.05) * CW
    cl = spec.get("colors", ["apple", "mango"]); pet_c, core_c = _col(cl[0])[:3], _col(cl[-1])[:3]
    n = spec.get("petals", 6); stem = spec.get("stem", 0.0) * CH; turn = spec.get("turn", 0.3)
    M = int(R * 1.3); W = 2 * M; H = 2 * M + int(stem)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if stem > 0:
        sl = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ds = ImageDraw.Draw(sl)
        sc = tuple(_col(spec.get("stem_color", "a2"))[:3])
        ds.line([(M, M), (M + R * 0.12, M + stem)], fill=sc + (230,), width=max(2, int(R * 0.06)))
        for k, side in ((0.45, 1), (0.72, -1)):
            lx, ly = M + R * 0.12 * k, M + stem * k
            ds.ellipse([lx + (0 if side > 0 else -R * 0.6), ly - R * 0.14, lx + (R * 0.6 if side > 0 else 0), ly + R * 0.14], fill=sc + (200,))
        out.alpha_composite(sl.filter(ImageFilter.GaussianBlur(R * 0.03)))
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0)); db = ImageDraw.Draw(base)
    cen = [(M + math.cos(2 * math.pi * i / n + turn) * R * 0.55, M + math.sin(2 * math.pi * i / n + turn) * R * 0.55) for i in range(n)]
    for px, py in cen:
        db.ellipse([px - R * 0.42, py - R * 0.42, px + R * 0.42, py + R * 0.42], fill=tuple(pet_c) + (170,))
    out.alpha_composite(base.filter(ImageFilter.GaussianBlur(R * 0.1)))
    k = int(R * R * 1.2); idx = g.integers(0, n, k); rr = R * 0.44 * np.sqrt(g.random(k)); th = g.random(k) * 2 * np.pi
    cxs = np.array([c[0] for c in cen])[idx] + rr * np.cos(th); cys = np.array([c[1] for c in cen])[idx] + rr * np.sin(th)
    dots = np.zeros((H, W, 4), np.float32)
    xi, yi = np.clip(cxs.astype(int), 0, W - 1), np.clip(cys.astype(int), 0, H - 1)
    sh = (0.7 + 0.6 * g.random(k))[:, None] * np.array(pet_c, np.float32)[None]
    dots[yi, xi, :3] = np.minimum(sh, 255); dots[yi, xi, 3] = 235
    out.alpha_composite(Image.fromarray(dots.astype(np.uint8), "RGBA"))
    cr = R * 0.3
    core = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(core).ellipse([M - cr, M - cr, M + cr, M + cr], fill=tuple(core_c) + (255,))
    out.alpha_composite(core.filter(ImageFilter.GaussianBlur(cr * 0.3)))
    if spec.get("rotate"):
        out = out.rotate(spec["rotate"], resample=Image.BICUBIC, center=(M, M))
    _paste_any(canvas, out, int(cx - M), int(cy - M))


def paint_waves(w, h, colors=None, seed=4):
    """An original painted sea, soft gouache feel: sunset-tinted water near the horizon, rolling swells that grow toward
    the viewer, each lit on its crest and shaded in its trough, broken foam along the crests and glitter on the water.
    colors: [far (sky reflection), near, deep, foam] — take them from the page's photos."""
    rng = np.random.default_rng(seed)
    far, near, deep, foam = [np.array(_col(c)[:3], np.float32) for c in (colors or [[232, 196, 204], [150, 186, 226], [62, 104, 160], [252, 250, 244]])]
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]; xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    def noise(sc, n=1):
        g = rng.random((int(h / sc) + 2, int(w / sc) + 2)).astype(np.float32)
        return np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255
    t = yy ** 0.9
    wf = np.clip(1 - yy / 0.42, 0, 1)[..., None] ** 1.4  # sunset reflection fades out over the top ~40%
    water = near * (1 - t[..., None]) + deep * t[..., None]
    base = far * wf + water * (1 - wf)
    img = np.broadcast_to(base, (h, w, 3)).copy()
    shade = np.zeros((h, w), np.float32); crestmap = np.zeros((h, w), np.float32)
    rows = 6
    for r in range(rows):
        tr = (r + 0.6) / rows
        y0 = 0.03 + 0.97 * tr ** 1.35
        amp = 0.012 + 0.07 * tr ** 1.5; per = 0.22 + 0.5 * tr
        ph = rng.uniform(0, 6.28)
        wav = y0 - amp * (0.65 * np.sin(xx / per * 6.28 + ph) + 0.35 * np.sin(xx / per * 15.7 + ph * 2.1)) + (noise(40) - 0.5) * amp * 0.5
        dist = yy - wav  # >0 below this crest
        band = 0.06 + 0.12 * tr
        lit = np.clip(1 - np.abs(dist + band * 0.15) / (band * 0.35), 0, 1) * (dist > -band * 0.5)
        trough = np.clip(dist / band, 0, 1) * np.clip(1 - dist / (band * 1.6), 0, 1)
        shade = np.maximum(shade, trough * (0.55 + 0.45 * tr))
        crestmap = np.maximum(crestmap, np.clip(1 - np.abs(dist) / (0.003 + 0.004 * tr), 0, 1) * (noise(18 + 30 * tr) > 0.38))
        img = img + lit[..., None] * (foam - img) * (0.02 + 0.2 * tr)  # far swells stay sunset-tinted, near ones catch more light
    img = img * (1 - 0.32 * shade[..., None]) + deep * 0.18 * shade[..., None]
    img = img + crestmap[..., None] * (foam - img) * 0.9
    glit = (noise(3) > 0.94) * (yy < 0.5) * (1 - yy / 0.5) * 0.55  # sparkle on the water near the horizon
    img = img + glit[..., None] * (foam - img)
    img = img + (noise(2) - 0.5)[..., None] * 10 + (noise(60) - 0.5)[..., None] * 14  # brush / paper grain
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    return out


def render_fill(canvas, spec, base=None, preset="clear"):
    """Cover an ugly part of a background photo (railings, clutter) and keep the good part.
    region [x0,y0,x1,y1]; edge = [[x,y],...] top boundary across the region (follows slanted railings; default flat);
    feather = fade height at that edge. Fill with either a soft gradient (colors [top, bottom]) or a texture cut from
    one of the user's own photos (src + crop [+ blur, flip]) such as bushes, grass or water, which reads as an
    out-of-focus foreground instead of a flat colour block."""
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"]
    X0, Y0, X1, Y1 = int(x0 * CW), int(y0 * CH), int(x1 * CW), int(y1 * CH)
    w, h = X1 - X0, Y1 - Y0
    if spec.get("paint") == "waves":
        rgb = np.asarray(paint_waves(w, h, spec.get("colors"), spec.get("seed", 4))).astype(np.float32)
    elif spec.get("src"):
        img = load(spec["src"], base)
        if spec.get("crop"):
            cx0, cy0, cx1, cy1 = spec["crop"]; iw, ih = img.size
            img = img.crop((int(cx0 * iw), int(cy0 * ih), int(cx1 * iw), int(cy1 * ih)))
        if spec.get("flip"):
            img = ImageOps.mirror(img)
        tex = grade(cover(img, w, h, spec.get("focus", [0.5, 0.5]), spec.get("zoom", 1.0)), preset)
        if spec.get("blur"):
            tex = tex.filter(ImageFilter.GaussianBlur(spec["blur"] * CW))
        rgb = np.asarray(tex.convert("RGB")).astype(np.float32)
    else:
        top, bot = np.array(_col(spec["colors"][0])[:3], np.float32), np.array(_col(spec["colors"][-1])[:3], np.float32)
        t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        rgb = np.broadcast_to(top * (1 - t) + bot * t, (h, w, 3)).copy()
        if spec.get("grain", 4):
            rgb = rgb + np.random.default_rng(3).normal(0, spec.get("grain", 4), (h, w, 1))
    edge = spec.get("edge") or [[x0, y0], [x1, y0]]
    ex = np.array([p[0] for p in edge]) * CW - X0; ey = np.array([p[1] for p in edge]) * CH - Y0
    top_y = np.interp(np.arange(w), ex, ey)  # boundary height for every column
    if spec.get("crest"):  # rolling wave-shaped top instead of a straight line: [amplitude, period] in canvas fractions
        ca, cp = spec["crest"]; xs_ = np.arange(w) / CW
        top_y = top_y - ca * CH * (0.6 * np.sin(xs_ / cp * 6.28 + 1.3) + 0.4 * np.sin(xs_ / cp * 14.1 + 0.4))
    f = max(1, spec.get("feather", 0.04) * CH)
    yy = np.arange(h)[:, None]
    al = np.clip((yy - top_y[None, :]) / f, 0, 1) ** 1.2
    if spec.get("wavy", 0):  # irregular top, like the tops of bushes
        rng_ = np.random.default_rng(7); wv = np.convolve(rng_.normal(0, 1, w + 60), np.ones(30) / 30, "same")[30:30 + w]
        al = np.clip((yy - top_y[None, :] - wv[None, :] * spec["wavy"] * CH) / f, 0, 1) ** 1.2
    A = (al * 255 * spec.get("alpha", 1.0)).astype(np.uint8)
    lay = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).convert("RGBA")
    lay.putalpha(Image.fromarray(A))
    canvas.alpha_composite(lay, (X0, Y0))


def render_haze(canvas, spec, rng):
    """Big soft airbrushed colour haze: several overlapping blurred grainy blobs in a region."""
    x0, y0, x1, y1 = spec["region"]
    for c in spec.get("colors", ["apple", "mango", "sky"]):
        render_orb(canvas, {"pos": [rng.uniform(x0, x1), rng.uniform(y0, y1)], "r": spec.get("r", 0.18) * rng.uniform(0.75, 1.2),
                            "colors": [c, c], "alpha": spec.get("alpha", 0.3), "soft": 1.6, "grain": 0.45}, rng)


def check_sheet(layout, base, out_path):
    """Contact sheet: every photo used, with its crop (white box) and the shape's safe area (pink box).
    The subject (faces, hands, the whole fruit/flower/statue) must sit inside the pink box."""
    CW, CH = layout.get("canvas", [1320, 1760])
    def _bgbox(bg):
        if bg.get("region"):
            x0, y0, x1, y1 = bg["region"]; return [x0, y0, x1 - x0, y1 - y0]
        b = bg.get("band", [0, 1]); return [0, b[0], 1, b[1] - b[0]]
    items = [dict(bg, type="photo", shape="rect", box=_bgbox(bg)) for bg in layout["background"]]
    items += [it for it in layout.get("layers", []) if it["type"] == "photo"]
    stickers = [it for it in layout.get("layers", []) if it["type"] == "sticker"]
    tiles = []
    for it in items:
        img = load(it["src"], base)
        if it.get("straighten"):
            img = straighten(img, it["straighten"])
        if it.get("crop") and it.get("type") == "photo" and "region" not in it:
            cx0, cy0, cx1, cy1 = it["crop"]; iw, ih = img.size
            img = img.crop((int(cx0 * iw), int(cy0 * ih), int(cx1 * iw), int(cy1 * ih)))
        img = pad_image(img, it.get("pad"))
        box = it["box"]; W = box[2] * CW; H = W if len(box) == 3 else box[3] * CH
        st = it.get("style", "none")
        pad = min(W, H) * 0.035 if st in ("card", "polaroid") else 0
        padb = min(W, H) * 0.16 if st == "polaroid" else pad
        W, H = W - 2 * pad, H - pad - padb
        x0, y0, cw, ch = crop_rect(img, W, H, it.get("focus", [0.5, 0.5]), it.get("zoom", 1.0))
        t = img.copy(); sc = 420 / max(t.size); t = t.resize((int(t.width * sc), int(t.height * sc)))
        d = ImageDraw.Draw(t)
        d.rectangle([x0 * sc, y0 * sc, (x0 + cw) * sc, (y0 + ch) * sc], outline=(255, 255, 255), width=3)
        f = SAFE.get(it.get("shape", "rect"), 0.6)
        sx, sy = x0 + cw * (1 - f) / 2, y0 + ch * (1 - f) / 2
        d.rectangle([sx * sc, sy * sc, (sx + cw * f) * sc, (sy + ch * f) * sc], outline=(255, 80, 160), width=3)
        d.text((6, 6), "%s  [%s]" % (os.path.basename(it["src"]), it.get("shape", "rect")), fill=(255, 255, 0))
        tiles.append(t)
    for it in stickers:  # show the cut-out on green so missing hands / held objects are easy to spot
        img = load(it["src"], base)
        if it.get("straighten"):
            img = straighten(img, it["straighten"])
        if it.get("crop"):
            x0, y0, x1, y1 = it["crop"]; iw, ih = img.size
            img = img.crop((int(x0 * iw), int(y0 * ih), int(x1 * iw), int(y1 * ih)))
        cut = cutout_rgba(img, "%s|%s|%s" % (it["src"], it.get("crop"), it.get("straighten")))
        cut.thumbnail((420, 420)); t = Image.new("RGBA", (420, 420), (60, 150, 90, 255)); t.alpha_composite(cut, ((420 - cut.width) // 2, (420 - cut.height) // 2))
        ImageDraw.Draw(t).text((6, 6), "%s  [sticker]" % os.path.basename(it["src"]), fill=(255, 255, 0)); tiles.append(t.convert("RGB"))
    cols = 3; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 430, rows * 430), (30, 30, 30))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 430 + 5, (i // cols) * 430 + 5))
    sheet.save(out_path)
    return out_path


# ------------------------------------------------------------------ whole-page looks (filters): applied once over the finished page so
# every photo AND every decoration share one colour mood
LOOKS = {
    # 1 misty morning forest (like the big-tree page): milky haze, lifted blacks, everything pulled toward soft green-cyan
    "mist":   dict(exp=1.06, con=0.74, sat=0.78, fade=0.12, shadow=(-0.02, 0.06, 0.05), high=(-0.01, 0.03, 0.02), haze=0.45, warm=-0.02, vig=0.0,
                   tint=(0.80, 1.0, 0.90), tint_amt=0.22, leak=None),
    # 2 retro strong sunlight (like the temple page): golden highlights, faded film blacks, warm light leaking from a top corner
    "sun":    dict(exp=1.07, con=0.9, sat=1.0, fade=0.08, shadow=(0.02, 0.025, -0.01), high=(0.07, 0.04, -0.06), haze=0.3, warm=0.07, vig=0.16,
                   tint=(1.0, 0.92, 0.70), tint_amt=0.18, leak=((1.0, 0.0), (255, 226, 160), 0.55)),
    # 3 airy cream: bright, very low contrast, pastel, creamy whites
    "cream":  dict(exp=1.14, con=0.72, sat=0.72, fade=0.14, shadow=(0.04, 0.04, 0.03), high=(0.04, 0.03, 0.0), haze=0.4, warm=0.03, vig=0.0,
                   tint=(1.0, 0.97, 0.88), tint_amt=0.2, leak=None),
    # 4 rich film: deeper contrast, teal shadows + warm highlights, fuller colour, darker corners
    "film":   dict(exp=1.0, con=1.15, sat=1.2, fade=0.05, shadow=(-0.04, 0.03, 0.06), high=(0.06, 0.025, -0.04), haze=0.1, warm=0.03, vig=0.25,
                   tint=(0.95, 1.0, 0.95), tint_amt=0.0, leak=None),
}

# subtle, true-to-life looks (fresh & clear, Fuji-like): small moves only, details must survive. Use these by default.
LOOKS.update({
    # default: bright, clear, fresh (Fuji straight-out-of-camera). Slightly brighter, a touch fresher greens, highlights
    # protected, crisp detail. No haze, no fade, no vignette, no warm or yellow cast.
    "forest_light": dict(exp=1.04, con=1.03, sat=1.02, fade=0.0, shadow=(0.0, 0.004, 0.006), high=(0.0, 0.002, 0.004), haze=0.0,
                       warm=0.0, vig=0.0, hue_green=6, green_sat=0.94, rolloff=0.3, sharp=0.7),
    "fresh":      dict(exp=1.03, con=1.03, sat=0.98, fade=0.0, shadow=(-0.005, 0.008, 0.012), high=(0.0, 0.004, 0.006), haze=0.0, warm=0.0, vig=0.0,
                       hue_green=7, green_sat=0.88, rolloff=0.25, sharp=0.6),
    "fresh_warm": dict(exp=1.03, con=1.02, sat=1.0, fade=0.0, shadow=(0.0, 0.006, 0.004), high=(0.012, 0.006, -0.008), haze=0.0, warm=0.012, vig=0.0,
                       hue_green=5, green_sat=0.9, rolloff=0.25, sharp=0.6),
    "fresh_soft": dict(exp=1.04, con=0.95, sat=0.96, fade=0.02, shadow=(0.0, 0.01, 0.012), high=(0.004, 0.004, 0.004), haze=0.06, warm=0.0, vig=0.0,
                       hue_green=6, green_sat=0.88, rolloff=0.35, sharp=0.5),
    "fresh_teal": dict(exp=1.03, con=1.04, sat=0.97, fade=0.0, shadow=(-0.012, 0.012, 0.022), high=(0.006, 0.004, 0.0), haze=0.0, warm=0.0, vig=0.04,
                       hue_green=11, green_sat=0.85, rolloff=0.25, sharp=0.6),
})


def apply_look(img, name):
    p = LOOKS[name] if isinstance(name, str) else name
    if p.get("hue_green") or p.get("green_sat", 1) != 1:  # Fuji-ish greens: nudge yellow-greens toward cyan, calm neon greens
        hsv = np.asarray(img.convert("RGB").convert("HSV")).astype(np.float32)
        h = hsv[..., 0] * 360 / 255
        wgt = np.exp(-((h - 95) / 40) ** 2) * np.clip(hsv[..., 1] / 255 * 2, 0, 1)
        hsv[..., 0] = ((h + p.get("hue_green", 0) * wgt) % 360) * 255 / 360
        hsv[..., 1] = hsv[..., 1] * (1 - (1 - p.get("green_sat", 1)) * wgt)
        img = Image.fromarray(np.clip(hsv, 0, 255).astype(np.uint8), "HSV").convert("RGB")
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255
    a = a * p["exp"]
    if p.get("rolloff"):  # protect highlights so bright skies / white clothes keep their detail
        k = p["rolloff"]; a = np.where(a > 0.8, 0.8 + (a - 0.8) * (1 - k * (a - 0.8) / 0.4), a)
    lum = (a * np.array([0.3, 0.59, 0.11], np.float32)).sum(2, keepdims=True)
    a = lum + (a - lum) * p["sat"]
    a = 0.5 + (a - 0.5) * p["con"]
    lum = np.clip((a * np.array([0.3, 0.59, 0.11], np.float32)).sum(2, keepdims=True), 0, 1)
    a = a + (1 - lum) ** 2 * np.array(p["shadow"], np.float32) + lum ** 2 * np.array(p["high"], np.float32)
    a = a + p["warm"] * np.array([1, 0.35, -0.8], np.float32) * lum
    if p.get("tint_amt"):  # soft-light toward one colour so every photo and sticker sits in the same mood
        t = np.array(p["tint"], np.float32); a = np.clip(a, 0, 1)
        soft = np.where(t < 0.5, 2 * a * t + a * a * (1 - 2 * t), 2 * a * (1 - t) + np.sqrt(a) * (2 * t - 1))
        a = a * (1 - p["tint_amt"]) + soft * p["tint_amt"]
    a = p["fade"] + a * (1 - p["fade"])
    a = np.clip(a, 0, 1)
    if p.get("leak"):
        (lx, ly), lc, la = p["leak"]; h, w = a.shape[:2]; yy, xx = np.mgrid[0:h, 0:w]
        m = np.clip(1 - np.hypot(xx / w - lx, (yy / h - ly) * h / w) / 0.85, 0, 1) ** 1.6 * la
        a = 1 - (1 - a) * (1 - m[..., None] * np.array(lc, np.float32) / 255)
    if p["haze"]:
        hi = np.clip((a.mean(2, keepdims=True) - 0.55) / 0.45, 0, 1) * a
        b = np.asarray(Image.fromarray((hi * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(img.width / 30))).astype(np.float32) / 255
        a = 1 - (1 - a) * (1 - b * p["haze"] * 1.6)
    if p["vig"]:
        h, w = a.shape[:2]; yy, xx = np.mgrid[0:h, 0:w]
        d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        a = a * (1 - p["vig"] * np.clip(d - 0.55, 0, 1))[..., None]
    out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    if p.get("sharp"):
        out = out.filter(ImageFilter.UnsharpMask(radius=1.6, percent=int(80 * p["sharp"]), threshold=2))
    return out


# ------------------------------------------------------------------ glint: dreamy sparkly edges (like sun glittering on water)
GLINT_TYPES = {"dots", "doodle", "sparkles", "sparkring", "hang", "orb", "rings", "loop", "sprayflower", "bubbles", "vine",
               "threads", "symbols", "pool"}


def add_glint(lay, strength=1.0, seed=0, t=None):
    """Make a decoration layer glitter: brighten its rim toward white, scatter tiny specular specks along the edges and
    over the body, a few 4-point star flares, plus a soft halation. With t (0..1) the specks twinkle (for animation)."""
    bb = lay.getbbox()
    if not bb or strength <= 0:
        return lay
    CW, CH = lay.size; P = 24
    x0, y0, x1, y1 = max(0, bb[0] - P), max(0, bb[1] - P), min(CW, bb[2] + P), min(CH, bb[3] + P)
    sub = lay.crop((x0, y0, x1, y1)); arr = np.asarray(sub).astype(np.float32)
    A = arr[..., 3] / 255
    Ai = Image.fromarray((A * 255).astype(np.uint8))
    inner = np.asarray(Ai.filter(ImageFilter.MinFilter(5))).astype(np.float32) / 255
    rim = np.clip(A - inner, 0, 1)
    rim = np.asarray(Image.fromarray((rim * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32) / 255
    rgb = arr[..., :3] + (255 - arr[..., :3]) * np.clip(rim * 0.4 * strength, 0, 0.7)[..., None]  # bright rim
    out = Image.fromarray(np.dstack([rgb, A * 255]).astype(np.uint8), "RGBA")
    g = np.random.default_rng(seed)
    sp = Image.new("RGBA", out.size, (0, 0, 0, 0)); d = ImageDraw.Draw(sp)
    ey, ex = np.nonzero(rim > 0.25); by, bx = np.nonzero(A > 0.5)
    pts = []
    if len(ex):
        k = min(len(ex), int(len(ex) * 0.018 * strength) + 1); idx = g.choice(len(ex), k, replace=False)
        pts += [(ex[i], ey[i]) for i in idx]
    if len(bx):
        k = min(len(bx), int(len(bx) * 0.004 * strength) + 1); idx = g.choice(len(bx), k, replace=False)
        pts += [(bx[i], by[i]) for i in idx]
    ph = g.random(len(pts)); sz = g.random(len(pts))
    for j, (x, y) in enumerate(pts):
        tw = 1.0 if t is None else 0.5 + 0.5 * math.sin(2 * math.pi * (t * 2 + ph[j]))
        if t is None and ph[j] < 0.35:  # still image: some specks dimmer, like a frozen shimmer
            tw = 0.45
        r = (0.7 + sz[j] * 1.6) * (CW / 1320)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 250, int(250 * tw)))
        if sz[j] > 0.975 and tw > 0.6:  # occasional star flare
            L = r * (4 + 4 * sz[j]) * tw
            _star4(d, x, y, L, (255, 255, 255, int(235 * tw)), 0.07)
    halo = sp.filter(ImageFilter.GaussianBlur(2.2 * CW / 1320))
    out.alpha_composite(halo); out.alpha_composite(halo); out.alpha_composite(sp)
    glow = out.filter(ImageFilter.GaussianBlur(5 * CW / 1320)); ga = np.asarray(glow.getchannel("A")).astype(np.float32) * 0.35 * min(1, strength)
    glow.putalpha(Image.fromarray(ga.astype(np.uint8)))
    res = Image.new("RGBA", lay.size, (0, 0, 0, 0)); res.alpha_composite(glow, (x0, y0)); res.alpha_composite(out, (x0, y0))
    return res


# ------------------------------------------------------------------ main
def render(layout, base):
    global BEAUTIFY
    CW, CH = layout.get("canvas", [1320, 1760])
    preset = layout.get("grade", "clear")
    BEAUTIFY = bool(layout.get("beautify", False))
    rng = random.Random(layout.get("seed", 7))
    canvas = Image.new("RGBA", (CW, CH), (30, 40, 30, 255))
    PAGE.clear()
    srcs = [bg["src"] for bg in layout["background"]] + [it["src"] for it in layout.get("layers", []) if it["type"] in ("photo", "sticker")]
    PAGE.update(page_palette([load(x, base) for x in srcs]))
    set_match([load(x, base) for x in srcs], layout.get("match", 0.35))
    PAGE.update({k: v for k, v in layout.get("palette", {}).items()})
    for bg in layout["background"]:
        y0, y1 = bg.get("band", [0, 1])
        x0, x1 = 0, 1
        if bg.get("region"):
            x0, y0, x1, y1 = bg["region"]
        src = load(bg["src"], base)
        if bg.get("beautify", BEAUTIFY):
            src = beautify(src)
        if bg.get("straighten"):
            src = straighten(src, bg["straighten"])
        src = pad_image(src, bg.get("pad"))
        rw, rh = int(round((x1 - x0) * CW)), int(round((y1 - y0) * CH))
        tile = grade(cover(src, rw, rh, bg.get("focus", [0.5, 0.5]), bg.get("zoom", 1.0)), preset)
        if bg.get("blur"):
            tile = tile.filter(ImageFilter.GaussianBlur(bg["blur"] * CW))
        m = None
        if bg.get("feather"):  # soft fade on the edges that sit inside the canvas, so panels melt into each other
            f = max(2, int(bg["feather"] * CW)); a = np.ones((rh, rw), np.float32); ramp = np.linspace(0, 1, f, dtype=np.float32)
            if y0 > 0.001: a[:f, :] *= ramp[:, None][:rh]
            if y1 < 0.999: a[-f:, :] *= ramp[::-1][:, None][:rh]
            if x0 > 0.001: a[:, :f] *= ramp[None, :][:, :rw]
            if x1 < 0.999: a[:, -f:] *= ramp[::-1][None, :][:, :rw]
            m = Image.fromarray((a * 255 * bg.get("opacity", 1.0)).astype(np.uint8))
        elif bg.get("opacity", 1.0) < 1:
            m = Image.new("L", (rw, rh), int(255 * bg["opacity"]))
        canvas.paste(tile, (int(round(x0 * CW)), int(round(y0 * CH))), m)
    texts = []
    draw = {"photo": lambda it: render_inset(canvas, it, base, preset), "cutout": lambda it: render_cutout(canvas, it),
            "sparkles": lambda it: render_sparkles(canvas, it, rng), "halo": lambda it: render_halo(canvas, it),
            "vine": lambda it: render_vine(canvas, it, rng), "dots": lambda it: render_dots(canvas, it),
            "dotfield": lambda it: render_dotfield(canvas, it, rng), "symbols": lambda it: render_symbols(canvas, it),
            "leak": lambda it: render_leak(canvas, it), "confetti": lambda it: render_confetti(canvas, it, rng),
            "sunlight": lambda it: render_sunlight(canvas, it), "doodle": lambda it: render_doodle(canvas, it),
            "bubbles": lambda it: render_bubbles(canvas, it, rng), "text": texts.append,
            "sticker": lambda it: render_sticker(canvas, it, base, preset), "seam": lambda it: render_seam(canvas, it),
            "orb": lambda it: render_orb(canvas, it, rng), "hang": lambda it: render_hang(canvas, it, rng),
            "pool": lambda it: render_pool(canvas, it, rng), "rings": lambda it: render_rings(canvas, it, rng),
            "threads": lambda it: render_threads(canvas, it, rng), "loop": lambda it: render_loop(canvas, it, rng),
            "sprayflower": lambda it: render_sprayflower(canvas, it, rng), "haze": lambda it: render_haze(canvas, it, rng), "fill": lambda it: render_fill(canvas, it, base, preset),
            "sparkring": lambda it: render_sparkring(canvas, it, rng)}
    gl = layout.get("glint", 0)
    for n_, item in enumerate(layout.get("layers", [])):
        g_ = item.get("glint", gl) if item["type"] in GLINT_TYPES else 0
        if g_:  # draw on its own layer, make it glitter, then lay it down
            real = canvas; canvas = Image.new("RGBA", real.size, (0, 0, 0, 0))
            draw[item["type"]](item)
            real.alpha_composite(add_glint(canvas, g_, seed=layout.get("seed", 7) * 100 + n_)); canvas = real
        else:
            draw[item["type"]](item)
    out = finish(canvas.convert("RGB"), layout.get("bloom", 0.12), layout.get("grain", 3), unify=layout.get("unify", 0.0), vig=layout.get("vignette", 0.0))
    out = apply_look(out, layout.get("look", "forest_light"))
    out = out.convert("RGBA")
    for item in texts:
        (render_text_bounce if item.get("style") == "bounce" else render_text)(out, item)
    return out.convert("RGB")


# ------------------------------------------------------------------ glitter ring + animation (looping MP4 / GIF)
def _star4(d, cx, cy, r, fill, thin=0.12):
    d.polygon([(cx, cy - r), (cx + r * thin, cy - r * thin), (cx + r, cy), (cx + r * thin, cy + r * thin),
               (cx, cy + r), (cx - r * thin, cy + r * thin), (cx - r, cy), (cx - r * thin, cy - r * thin)], fill=fill)


def render_sparkring(canvas, spec, rng, t=0.0):
    """Glitter ring: an ellipse of tiny glittering dots with a few star flares, tilted around a subject like a
    planet ring. The back half is dimmer so it reads as going behind. t (0..1) moves the shimmer around the ring."""
    CW, CH = canvas.size; S = 2
    cx, cy = spec["pos"][0] * CW * S, spec["pos"][1] * CH * S
    rx = spec.get("r", 0.2) * CW * S; ry = rx * spec.get("tilt", 0.28)
    ang = math.radians(spec.get("rotate", -8)); ca, sa = math.cos(ang), math.sin(ang)
    cols = [tuple(_col(c)[:3]) for c in spec.get("colors", ["white", "cream"])]
    g = np.random.default_rng(spec.get("seed", 3))
    n = int(spec.get("density", 1.0) * rx * 5)
    th0 = g.random(n) * 2 * math.pi; jit = (g.random(n) - 0.5) * spec.get("thick", 0.07) * rx
    ph = g.random(n); size = (0.8 + g.random(n) ** 3 * 3.2) * S * spec.get("grain", 1.0)
    lay = Image.new("RGBA", (CW * S, CH * S), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    back = spec.get("back", 0.35); spin = spec.get("spin", 1)
    band = Image.new("RGBA", lay.size, (0, 0, 0, 0)); db = ImageDraw.Draw(band)  # soft tube of light under the glitter
    pts = []
    for j in range(241):
        th = 2 * math.pi * j / 240; ex, ey = rx * math.cos(th), ry * math.sin(th)
        pts.append((cx + ex * ca - ey * sa, cy + ex * sa + ey * ca, math.sin(th) > 0))
    for j in range(240):
        a = int(255 * spec.get("band", 0.55) * (1 if pts[j][2] else back))
        db.line([pts[j][:2], pts[j + 1][:2]], fill=cols[-1] + (a,), width=max(2, int(spec.get("thick", 0.07) * rx * 0.8)))
    lay.alpha_composite(band.filter(ImageFilter.GaussianBlur(spec.get("thick", 0.07) * rx * 0.5)))
    for i in range(n):
        th = th0[i] + 2 * math.pi * t * spin * 0.25
        ex, ey = (rx + jit[i]) * math.cos(th), (ry + jit[i] * 0.4) * math.sin(th)
        x, y = cx + ex * ca - ey * sa, cy + ex * sa + ey * ca
        depth = 1.0 if math.sin(th) > 0 else back  # lower half of the ellipse is the front
        tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(2 * math.pi * (t * 2 + ph[i])))
        c = cols[i % len(cols)]; a = int(255 * depth * tw * spec.get("alpha", 0.95)); s = size[i]
        d.ellipse([x - s, y - s, x + s, y + s], fill=c + (a,))
    for k in range(spec.get("flares", 2)):  # bright 4-point stars riding on the ring
        th = 2 * math.pi * (k / max(1, spec.get("flares", 2)) + t * spin * 0.25 + 0.1)
        ex, ey = rx * math.cos(th), ry * math.sin(th)
        x, y = cx + ex * ca - ey * sa, cy + ex * sa + ey * ca
        if math.sin(th) < 0:
            continue
        r = spec.get("flare", 0.035) * CW * S * (0.75 + 0.25 * math.sin(2 * math.pi * (t * 2 + k * 0.4)))
        _star4(d, x, y, r, (255, 255, 255, 250), 0.06)
    lay = lay.resize((CW, CH), Image.LANCZOS)
    glow = lay.filter(ImageFilter.GaussianBlur(CW / 160))
    canvas.alpha_composite(glow); canvas.alpha_composite(glow); canvas.alpha_composite(lay)


def render_twinkle(canvas, spec, rng, t=0.0):
    """Sparkles that twinkle: same layout as 'sparkles', each star pulsing on its own phase."""
    CW, CH = canvas.size
    x0, y0, x1, y1 = spec["region"]
    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for _ in range(spec.get("count", 8)):
        cx, cy = rng.uniform(x0, x1) * CW, rng.uniform(y0, y1) * CH
        r = rng.uniform(*spec.get("size", [0.008, 0.022])) * CW; p = rng.random()
        k = 0.5 + 0.5 * math.sin(2 * math.pi * (t * spec.get("speed", 2) + p))
        _star4(d, cx, cy, r * (0.35 + 0.75 * k), (255, 255, 255, int(255 * spec.get("alpha", 0.9) * (0.25 + 0.75 * k))), 0.16)
    lay = colorize(lay, spec.get("colors"), spec.get("dir", "v"))
    gl = lay.filter(ImageFilter.GaussianBlur(CW / 120))
    canvas.alpha_composite(gl); canvas.alpha_composite(gl); canvas.alpha_composite(lay)


ANIMATED = {"sparkles", "sparkring", "hang", "orb", "rings", "loop", "dots", "doodle", "sprayflower", "bubbles", "pool"}


def _anim_spec(it, t, idx):
    """Return a per-frame copy of a layer spec. Every motion is periodic in t so the clip loops seamlessly."""
    s = dict(it); w = 2 * math.pi * t; ph = idx * 0.37 * 2 * math.pi; sp = it.get("speed", 1)
    k = math.sin(w * sp + ph); amp = it.get("amp", 1.0)
    ty = it["type"]
    if ty == "hang":
        s["pos"] = [it["pos"][0] + 0.004 * amp * k, it["pos"][1]]
        s["alpha"] = it.get("alpha", 0.92) * (0.85 + 0.15 * math.sin(2 * w + ph))
    elif ty in ("orb", "rings"):
        s["r"] = it.get("r", 0.06 if ty == "orb" else 0.08) * (1 + 0.06 * amp * k)
        s["alpha"] = it.get("alpha", 0.85) * (0.82 + 0.18 * math.sin(w * sp + ph + 1))
    elif ty == "loop":
        s["rotate"] = it.get("rotate", 0) + 25 * amp * k
        s["alpha"] = 1
    elif ty == "dots":
        s["alpha"] = it.get("alpha", 0.7) * (0.6 + 0.4 * (0.5 + 0.5 * k))
    elif ty in ("doodle", "sprayflower"):
        s["rotate"] = it.get("rotate", 0) + 8 * amp * k
    elif ty == "bubbles":
        x0, y0, x1, y1 = it["region"]; dy = -0.012 * amp * k
        s["region"] = [x0, y0 + dy, x1, y1 + dy]
    elif ty == "pool":
        s["alpha"] = it.get("alpha", 0.75) * (0.8 + 0.2 * k)
    return s


def render_frames(layout, base, out_path, seconds=3.0, fps=12, gif=True):
    """Looping clip: everything static is rendered once (photos, grade, grain); layers in ANIMATED (unless
    "anim": false) are redrawn every frame on top: sparkles twinkle, glitter rings shimmer around, light drops
    sway, orbs and rings breathe, pixel icons pulse, doodles and spray flowers rock, bubbles float."""
    import subprocess, tempfile, shutil, copy
    lay = copy.deepcopy(layout)
    moving = [(i, it) for i, it in enumerate(lay.get("layers", [])) if it["type"] in ANIMATED and it.get("anim", True)]
    texts = [it for it in lay.get("layers", []) if it["type"] == "text"]
    ids = {i for i, _ in moving}
    lay["layers"] = [it for i, it in enumerate(lay.get("layers", [])) if i not in ids and it["type"] != "text"]
    still = render(lay, base).convert("RGBA")
    CW, CH = still.size; preset = layout.get("grade", "clear")
    n = max(2, int(seconds * fps)); tmp = tempfile.mkdtemp()
    for f in range(n):
        t = f / n; cv = still.copy()
        for i, it in moving:
            r = random.Random(layout.get("seed", 7) * 1000 + i); s = _anim_spec(it, t, i)
            ty = it["type"]
            g_ = it.get("glint", layout.get("glint", 0)) if ty in GLINT_TYPES else 0
            if g_:
                frame = cv; cv = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            if ty == "sparkles": render_twinkle(cv, s, r, t)
            elif ty == "sparkring": render_sparkring(cv, s, r, t)
            elif ty == "hang": render_hang(cv, s, r)
            elif ty == "orb": render_orb(cv, s, r)
            elif ty == "rings": render_rings(cv, s, r)
            elif ty == "loop": render_loop(cv, s, r)
            elif ty == "dots": render_dots(cv, s)
            elif ty == "doodle": render_doodle(cv, s)
            elif ty == "sprayflower": render_sprayflower(cv, s, r)
            elif ty == "bubbles": render_bubbles(cv, s, r)
            elif ty == "pool": render_pool(cv, s, r)
            if g_:
                frame.alpha_composite(add_glint(cv, g_, seed=layout.get("seed", 7) * 100 + i, t=t)); cv = frame
        for it in texts:
            (render_text_bounce if it.get("style") == "bounce" else render_text)(cv, it)
        cv.convert("RGB").save(os.path.join(tmp, "f%04d.png" % f))
    W2, H2 = CW // 2 * 2, CH // 2 * 2
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%04d.png"),
                    "-vf", "scale=%d:%d,loop=2:%d:0" % (W2, H2, n), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out_path], check=True)
    outs = [out_path]
    if gif:
        gp = os.path.splitext(out_path)[0] + ".gif"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%04d.png"),
                        "-vf", "scale=600:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=200[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                        "-loop", "0", gp], check=True)
        outs.append(gp)
    shutil.rmtree(tmp)
    return outs


def compare_sheet(out_path, paths, labels=None):
    """Side-by-side thumbnails of several finished versions (labelled A, B, C...) so the user can pick one."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    h = 900; ths = [im.resize((int(im.width * h / im.height), h), Image.LANCZOS) for im in ims]
    gap = 30; top = 70
    W = sum(t.width for t in ths) + gap * (len(ths) + 1)
    sheet = Image.new("RGB", (W, h + top + gap), (248, 248, 244)); d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FALLBACK_FONT, 40) if FALLBACK_FONT else None
    x = gap
    for i, t in enumerate(ths):
        sheet.paste(t, (x, top))
        d.text((x, 14), (labels[i] if labels else "方案 " + "ABCDEFGH"[i]), fill=(40, 70, 50), font=font)
        x += t.width + gap
    sheet.save(out_path, quality=90)
    return out_path


KNOWN_TYPES = {"photo", "cutout", "sparkles", "halo", "vine", "dots", "dotfield", "symbols", "leak", "confetti", "sunlight",
               "doodle", "bubbles", "text", "sticker", "seam", "fill", "orb", "hang", "pool", "rings", "threads", "loop",
               "sprayflower", "haze", "sparkring"}


def validate(layout):
    """Fail early with a readable message instead of a KeyError deep inside a renderer."""
    errs = []
    if not layout.get("background"):
        errs.append("layout has no background")
    for i, it in enumerate(layout.get("layers", [])):
        t = it.get("type")
        if t not in KNOWN_TYPES:
            errs.append("layer %d: unknown type %r" % (i, t))
        if t == "dots" and it.get("pattern", "flower2") not in PIXEL:
            errs.append("layer %d: unknown dots pattern %r (have: %s)" % (i, it.get("pattern"), ", ".join(PIXEL)))
        if t == "photo" and it.get("shape", "rect") not in SAFE:
            errs.append("layer %d: unknown shape %r" % (i, it.get("shape")))
    if layout.get("look") and layout["look"] not in LOOKS:
        errs.append("unknown look %r (have: %s)" % (layout["look"], ", ".join(LOOKS)))
    if layout.get("grade", "clear") not in PRESETS:
        errs.append("unknown grade %r (have: %s)" % (layout.get("grade"), ", ".join(PRESETS)))
    if errs:
        sys.exit("layout errors:\n  " + "\n  ".join(errs))


def draft_preview(layout, base, out_path):
    """Layout sketch to confirm with the user before decorating: only the photos (crop, size, position, frame shape),
    default colour, no decorations / bloom / grain / text, half size, each photo labelled with its file name."""
    lay = json.loads(json.dumps(layout))
    lay["layers"] = [it for it in lay.get("layers", []) if it["type"] in ("photo", "sticker", "seam", "vine", "threads", "fill")]
    lay.update(bloom=0, grain=0, glint=0)
    img = render(lay, base)
    CW, CH = img.size
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FALLBACK_FONT, 34)
    except Exception:
        font = ImageFont.load_default()
    def tag(x, y, text):
        x, y = int(x * CW) + 14, int(y * CH) + 12
        tb = d.textbbox((x, y), text, font=font)
        d.rectangle([tb[0] - 8, tb[1] - 6, tb[2] + 8, tb[3] + 6], fill=(255, 255, 255))
        d.text((x, y), text, fill=(40, 60, 50), font=font)
    for bg in lay["background"]:
        r = bg.get("region", [0, 0, 1, 1]); tag(r[0], r[1], "底 " + os.path.splitext(bg["src"])[0])
    for it in lay["layers"]:
        if it["type"] in ("photo", "sticker"):
            b = it["box"]; tag(b[0], b[1], os.path.splitext(it["src"])[0])
    img = img.resize((CW // 2, CH // 2))
    img.save(out_path, quality=85)
    return out_path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if "--compare" in flags:
        print("compare sheet:", compare_sheet(args[0], args[1:]))
        sys.exit(0)
    if len(args) < 2:
        sys.exit(__doc__)
    lay_path, out_path = args[0], args[1]
    layout = json.load(open(lay_path))
    validate(layout)
    base = os.path.join(os.path.dirname(os.path.abspath(lay_path)), layout.get("photo_dir", "."))
    if "--animate" in flags:  # out_path should end in .mp4; a .gif is written next to it
        print("animated:", render_frames(layout, base, out_path, layout.get("seconds", 3.0), layout.get("fps", 12)))
        sys.exit(0)
    if "--draft" in flags:
        print("draft:", draft_preview(layout, base, out_path))
        sys.exit(0)
    if "--check" in flags:
        print("check sheet:", check_sheet(layout, base, os.path.splitext(out_path)[0] + "_check.jpg"))
    render(layout, base).save(out_path, quality=93)
    print("saved", out_path)
    print("page palette:", PAGE)
