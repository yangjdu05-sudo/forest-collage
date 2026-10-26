#!/usr/bin/env python3
"""Measure every photo before any layout is designed, so placement is based on numbers, not guesses.

Usage:  python3 analyze.py PHOTO_DIR [--out OUT_DIR]

For each photo it finds (all coordinates are fractions 0..1 of that photo, [x0, y0, x1, y1]):
  faces    face boxes
  subject  bounding box of the main subject (person / object), with its share of the photo
  empty    low-detail cells where small inserts, text and decorations can go
  tilt     suggested "straighten" value in degrees (0 = level enough) + tilt_conf: sure / unsure / level.
           "unsure" means perspective may be fooling it: look at the photo before straightening
  colors   the photo's main colours
Writes PHOTO_DIR/_analysis.json (lint.py reads it) and one overlay per photo in OUT_DIR (default
PHOTO_DIR/_analysis/): 0.1 grid with labels, faces red, subject green, empty cells blue. Open the overlays
with Read before designing; read positions off the grid instead of estimating them.
"""
import json, os, sys, glob, math
import numpy as np
from PIL import Image, ImageOps, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collage as C  # noqa: E402

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".JPG", ".JPEG", ".PNG")


def faces_of(img):
    try:
        boxes, _ = C.find_faces(np.asarray(img))
    except Exception:
        return []
    W, H = img.size
    out = []
    for x, y, w, h in boxes:
        x0, y0, x1, y1 = max(0, x) / W, max(0, y) / H, min(W, x + w) / W, min(H, y + h) / H
        if x1 > x0 and y1 > y0:
            out.append([round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)])
    return out


_RB = {}


def subject_of(img, key):
    """Main-subject box from a cut-out mask (rembg). None when no cut-out tool or nothing clear was found."""
    cache = os.path.join(C.HOME, "cache"); os.makedirs(cache, exist_ok=True)
    import hashlib
    mp = os.path.join(cache, "an_" + hashlib.md5(key.encode()).hexdigest() + ".png")
    if os.path.exists(mp):
        m = Image.open(mp).convert("L")
    else:
        try:
            from rembg import remove, new_session
            if "s" not in _RB:
                _RB["s"] = new_session("isnet-general-use")
            small = img.copy(); small.thumbnail((640, 640))
            m = remove(small, session=_RB["s"], only_mask=True)
            m.save(mp)
        except Exception:
            return None
    a = np.asarray(m) > 128
    area = float(a.mean())
    if area < 0.01:
        return None
    ys, xs = np.nonzero(a); H, W = a.shape
    box = [float(xs.min() / W), float(ys.min() / H), float((xs.max() + 1) / W), float((ys.max() + 1) / H)]
    edge = [n for n, v in zip(("left", "top", "right", "bottom"), (box[0] < 0.01, box[1] < 0.01, box[2] > 0.99, box[3] > 0.99)) if v]
    return {"box": [round(v, 3) for v in box], "area": round(area, 3), "touches_edge": edge}


def empty_cells(img, keep_out, cols=None):
    """Grid cells with little detail (sky, wall, canopy, lawn), excluding faces and subject."""
    g = img.convert("L"); g.thumbnail((240, 240)); a = np.asarray(g).astype(np.float32)
    gy, gx = np.gradient(a); mag = np.hypot(gx, gy)
    H, W = a.shape
    cols = cols or (6 if W <= H else 8); rows = max(4, round(cols * H / W))
    score = np.zeros((rows, cols))
    for r in range(rows):
        for c in range(cols):
            score[r, c] = mag[int(r * H / rows):int((r + 1) * H / rows), int(c * W / cols):int((c + 1) * W / cols)].mean()
    thr = min(np.percentile(score, 40), np.median(score) * 0.8)
    out = []
    for r in range(rows):
        for c in range(cols):
            cell = [c / cols, r / rows, (c + 1) / cols, (r + 1) / rows]
            if score[r, c] <= thr and not any(_overlap(cell, k) > 0.15 * _area(cell) for k in keep_out):
                out.append([round(v, 3) for v in cell])
    return out


def tilt_of(img):
    """Suggested straighten angle from long near-horizontal / near-vertical lines (horizon, trunks, walls)."""
    try:
        cv2 = C._cv()["cv2"]
    except Exception:
        return 0.0, "unknown"
    g = img.convert("L"); g.thumbnail((800, 800)); a = np.asarray(g)
    edges = cv2.Canny(a, 60, 160)
    L = min(a.shape) * 0.25
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, 80, minLineLength=L, maxLineGap=8)
    if lines is None:
        return 0.0, "unknown"
    groups = {"h": ([], []), "v": ([], [])}
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4).tolist():
        if y1 < y0 or (y1 == y0 and x1 < x0):
            x0, y0, x1, y1 = x1, y1, x0, y0
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))  # 0..180, y down
        for axis, k in ((0, "h"), (90, "v"), (180, "h")):
            if abs(ang - axis) < 12:
                groups[k][0].append(ang - axis); groups[k][1].append(math.hypot(x1 - x0, y1 - y0))

    def wmed(devs, wts):
        if len(devs) < 2:
            return None
        o = np.argsort(devs); d = np.array(devs)[o]; w = np.cumsum(np.array(wts)[o])
        return float(d[np.searchsorted(w, w[-1] / 2)])
    h, v = wmed(*groups["h"]), wmed(*groups["v"])
    # low-angle / perspective shots make verticals converge and horizontals slant, so only trust a tilt when
    # horizontals and verticals agree; a single family alone is reported as unsure
    if h is not None and v is not None:
        if abs(h - v) <= 1.5:
            m = (h + v) / 2
            return (round(m, 1), "sure") if abs(m) >= 1.0 else (0.0, "level")
        return (0.0, "level") if abs(h) < 1 and abs(v) < 1 else (round(h if abs(h) < abs(v) else v, 1), "unsure")
    m = h if h is not None else v
    if m is None:
        return 0.0, "unknown"
    return (round(m, 1), "unsure") if abs(m) >= 1.0 else (0.0, "level")


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _overlap(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def overlay(img, info, path):
    t = img.copy(); t.thumbnail((900, 900)); W, H = t.size
    t = t.convert("RGBA"); lay = Image.new("RGBA", t.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for b in info["empty"]:
        d.rectangle([b[0] * W + 2, b[1] * H + 2, b[2] * W - 2, b[3] * H - 2], fill=(40, 120, 255, 95), outline=(140, 220, 255, 230), width=2)
    for i in range(1, 10):
        d.line([(i * W / 10, 0), (i * W / 10, H)], fill=(255, 255, 255, 110), width=1)
        d.line([(0, i * H / 10), (W, i * H / 10)], fill=(255, 255, 255, 110), width=1)
        d.text((i * W / 10 + 2, 2), "%.1f" % (i / 10), fill=(255, 255, 0, 255))
        d.text((2, i * H / 10 + 2), "%.1f" % (i / 10), fill=(255, 255, 0, 255))
    if info.get("subject"):
        b = info["subject"]["box"]; d.rectangle([b[0] * W, b[1] * H, b[2] * W, b[3] * H], outline=(60, 230, 90, 255), width=3)
    for b in info["faces"]:
        d.rectangle([b[0] * W, b[1] * H, b[2] * W, b[3] * H], outline=(255, 50, 50, 255), width=3)
    if info["tilt"]:
        d.text((8, H - 20), "tilt (%s): straighten %+.1f" % (info["tilt_conf"], info["tilt"]), fill=(255, 80, 80, 255))
    t.alpha_composite(lay); t.convert("RGB").save(path, quality=88)


def analyze_photo(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    W, H = img.size
    info = {"size": [W, H], "orientation": "portrait" if H > W * 1.05 else ("landscape" if W > H * 1.05 else "square")}
    info["faces"] = faces_of(img)
    info["subject"] = subject_of(img, "%s|%d" % (os.path.abspath(path), os.path.getmtime(path)))
    keep = info["faces"] + ([info["subject"]["box"]] if info["subject"] and info["subject"]["area"] < 0.6 else [])
    info["empty"] = empty_cells(img, keep)
    info["tilt"], info["tilt_conf"] = tilt_of(img)
    pal = C.page_palette([img])
    info["colors"] = ["#%02x%02x%02x" % tuple(v) for k, v in sorted(pal.items()) if k.startswith("p")]
    return img, info


def load_or_run(photo_dir, files=None):
    """Used by lint.py: reuse _analysis.json, measuring only photos that are missing from it."""
    jp = os.path.join(photo_dir, "_analysis.json")
    data = json.load(open(jp)) if os.path.exists(jp) else {}
    todo = [f for f in (files or []) if f not in data and os.path.exists(os.path.join(photo_dir, f))]
    for f in todo:
        data[f] = analyze_photo(os.path.join(photo_dir, f))[1]
    if todo:
        json.dump(data, open(jp, "w"), ensure_ascii=False, indent=1)
    return data


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    d = sys.argv[1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(d, "_analysis")
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in os.listdir(d) if f.endswith(EXTS) and not f.startswith("_"))
    data = {}
    for f in files:
        img, info = analyze_photo(os.path.join(d, f))
        data[f] = info
        overlay(img, info, os.path.join(out, os.path.splitext(f)[0] + "_an.jpg"))
        sub = info["subject"]
        print("%-22s %-9s faces=%d subject=%s%s tilt=%s empty=%d colors=%s" % (
            f, info["orientation"], len(info["faces"]),
            sub["box"] if sub else "-", (" EDGE:" + ",".join(sub["touches_edge"])) if sub and sub["touches_edge"] else "",
            "%s(%s)" % (info["tilt"], info["tilt_conf"]), len(info["empty"]), " ".join(info["colors"][:3])))
    json.dump(data, open(os.path.join(d, "_analysis.json"), "w"), ensure_ascii=False, indent=1)
    print("wrote", os.path.join(d, "_analysis.json"), "and overlays in", out)


if __name__ == "__main__":
    main()
