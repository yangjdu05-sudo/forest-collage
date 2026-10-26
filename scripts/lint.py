#!/usr/bin/env python3
"""Check a layout against the user's rules with measurements instead of eyeballing.

Usage:  python3 lint.py layout.json [rendered.jpg]

Uses PHOTO_DIR/_analysis.json from analyze.py (measures missing photos itself). Prints ERROR lines (rule broken,
must fix) and WARN lines (look at it and decide). With rendered.jpg it also writes rendered_lint.jpg: faces red,
inserts white, decorations yellow, so overlaps are visible. Exit code 1 when there are errors.
"""
import json, os, sys
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collage as C  # noqa: E402
import analyze as A  # noqa: E402

REGULAR = {"rect", "rounded", "scallop", "arch", "oval", "circle", "star", "heart"}
IRREGULAR = {"blob", "cloud", "flower", "clover"}
ATMOSPHERE = {"sunlight", "haze", "fill", "leak", "halo", "dotfield", "seam", "cutout"}  # may pass over a face softly
SCATTER = {"confetti", "sparkles", "bubbles"}                                      # random inside a region
AIRBRUSH = {"orb", "hang", "rings", "threads", "loop", "sprayflower", "pool", "haze", "sparkring"}
DECOR = {"dots", "doodle", "vine", "symbols", "confetti", "sparkles", "bubbles", "orb", "hang", "rings", "threads",
         "loop", "sprayflower", "pool", "sparkring", "cutout"}


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def insert_hw(it, CW, CH):
    """Insert box as canvas fractions [x0, y0, x1, y1]."""
    b = it["box"]; w = b[2]; h = b[2] * CW / CH if len(b) == 3 else b[3]
    return [b[0], b[1], b[0] + w, b[1] + h]


def photo_to_canvas(pt_box, src_size, it, target, CW, CH, card=False):
    """Map a box given in photo fractions to canvas fractions, following crop / pad / focus / zoom (cover crop).
    target = [x0, y0, x1, y1] in canvas fractions where the photo is shown."""
    x0, y0, x1, y1 = pt_box
    if it.get("crop") and "region" not in it:
        c = it["crop"]; sx, sy = c[2] - c[0], c[3] - c[1]
        x0, x1 = (x0 - c[0]) / sx, (x1 - c[0]) / sx; y0, y1 = (y0 - c[1]) / sy, (y1 - c[1]) / sy
        src_size = (src_size[0] * sx, src_size[1] * sy)
    f = it.get("pad") or 1
    if f > 1:
        x0, x1, y0, y1 = [0.5 + (v - 0.5) / f for v in (x0, x1, y0, y1)]
        src_size = (src_size[0] * f, src_size[1] * f)
    W = (target[2] - target[0]) * CW; H = (target[3] - target[1]) * CH
    if card:
        p = min(W, H) * 0.035; W -= 2 * p; H -= 2 * p
    iw, ih = src_size
    cx, cy, cw, ch = C.crop_rect(type("S", (), {"size": (iw, ih)})(), W, H, it.get("focus", [0.5, 0.5]), it.get("zoom", 1.0))
    tw, th = target[2] - target[0], target[3] - target[1]
    m = lambda px, py: (target[0] + (px * iw - cx) / cw * tw, target[1] + (py * ih - cy) / ch * th)  # noqa: E731
    a, b = m(x0, y0); c, d = m(x1, y1)
    return [a, b, c, d]


def bbox(it, CW, CH):
    """Approximate canvas-fraction box of any layer (None when it has no sensible footprint)."""
    t = it["type"]; r_ = CW / CH
    if t == "photo":
        return insert_hw(it, CW, CH)
    if t == "sticker":
        b = it["box"]; return [b[0], b[1], b[0] + b[2], b[1] + b[2] * r_ * 1.3]  # height unknown until cut out
    if t in SCATTER or t in ("dotfield", "haze", "fill"):
        return list(it["region"])
    if t == "cutout":
        b = it["box"]; return [b[0], b[1], b[0] + b[2], b[1] + b[3]]
    if t == "dots":
        p = C.PIXEL.get(it.get("pattern", "flower2"), ["#"]); c = it.get("cell", 0.008)
        return [it["pos"][0], it["pos"][1], it["pos"][0] + len(p[0]) * c, it["pos"][1] + len(p) * c * r_]
    if t == "doodle":
        s = it.get("size", 0.08) / 2; return [it["pos"][0] - s, it["pos"][1] - s * r_, it["pos"][0] + s, it["pos"][1] + s * r_]
    if t == "sprayflower":
        s = it.get("size", 0.05) * 1.1
        return [it["pos"][0] - s, it["pos"][1] - s * r_, it["pos"][0] + s, it["pos"][1] + s * r_ + it.get("stem", 0)]
    if t in ("orb", "rings", "loop"):
        s = it.get("r", {"orb": 0.06, "rings": 0.08, "loop": 0.02}[t]); q = it.get("squash", 1.25 if t == "loop" else 1.0)
        return [it["pos"][0] - s, it["pos"][1] - s * q * r_, it["pos"][0] + s, it["pos"][1] + s * q * r_]
    if t == "sparkring":
        s = it.get("r", 0.2); return [it["pos"][0] - s, it["pos"][1] - s * 0.5 * r_, it["pos"][0] + s, it["pos"][1] + s * 0.5 * r_]
    if t == "hang":
        s = it.get("r", 0.022)
        return [it["pos"][0] - s, it["pos"][1] - it.get("length", 0.15), it["pos"][0] + s, it["pos"][1] + s * r_]
    if t == "pool":
        return [it["pos"][0] - it.get("w", 0.3) / 2, it["pos"][1] - it.get("h", 0.05) / 2,
                it["pos"][0] + it.get("w", 0.3) / 2, it["pos"][1] + it.get("h", 0.05) / 2]
    if t == "vine":
        xs = [p[0] for p in it["points"]]; ys = [p[1] for p in it["points"]]
        return [min(xs) - 0.03, min(ys), max(xs) + 0.03, max(ys)]
    if t == "threads":
        ls = it["lines"]; return [min(l[0] for l in ls) - 0.01, min(l[1] for l in ls), max(l[0] for l in ls) + 0.01, max(l[2] for l in ls) + 0.01]
    if t == "symbols":
        s = it.get("size", 0.024); n = len(it.get("text", "1234567")); return [it["pos"][0], it["pos"][1], it["pos"][0] + s * n * 0.9, it["pos"][1] + s * r_ * 1.3]
    if t == "text":
        s = it.get("size", 0.06 if it.get("style") == "bounce" else 0.034); lines = it["text"].split("\n")
        w = max(len(l) for l in lines) * s; return [it["pos"][0] - w / 2, it["pos"][1], it["pos"][0] + w / 2, it["pos"][1] + len(lines) * s * r_ * 1.6]
    return None


def lint(layout_path, rendered=None):
    layout = json.load(open(layout_path))
    CW, CH = layout.get("canvas", [1320, 1760])
    base = os.path.join(os.path.dirname(os.path.abspath(layout_path)), layout.get("photo_dir", "."))
    layers = layout.get("layers", [])
    bgs = layout.get("background", [])
    srcs = sorted({b["src"] for b in bgs} | {it["src"] for it in layers if it["type"] in ("photo", "sticker")})
    an = A.load_or_run(base, srcs)
    E, W = [], []
    err = lambda m: E.append(m)  # noqa: E731
    warn = lambda m: W.append(m)  # noqa: E731
    inserts = [(i, it) for i, it in enumerate(layers) if it["type"] == "photo"]

    # ---- faces / subjects / empty areas of the background(s) on the canvas
    bg_faces, bg_subj, bg_empty = [], [], []
    for bg in bgs:
        info = an.get(bg["src"]); tgt = bg.get("region") or [0, bg.get("band", [0, 1])[0], 1, bg.get("band", [0, 1])[1]]
        if not info:
            warn("背景 %s 没有测量数据（文件找不到？）" % bg["src"]); continue
        for fb in info["faces"]:
            cb = photo_to_canvas(fb, info["size"], bg, tgt, CW, CH)
            if _inter(cb, tgt) < _area(cb) * 0.6:
                warn("背景 %s 的一张脸有一半以上在画面外，检查 focus/zoom" % bg["src"])
            bg_faces.append((bg["src"], cb))
        for eb in info.get("empty", []):
            bg_empty.append(photo_to_canvas(eb, info["size"], bg, tgt, CW, CH))
        s = info.get("subject")
        if s and s["area"] < 0.6:
            bg_subj.append((bg["src"], photo_to_canvas(s["box"], info["size"], bg, tgt, CW, CH)))
        if info.get("tilt_conf") == "sure" and abs(info.get("tilt", 0)) >= 1 and not bg.get("straighten"):
            warn("背景 %s 可能拍歪了：建议 \"straighten\": %s" % (bg["src"], info["tilt"]))

    # ---- inserts
    bg_srcs = {b["src"] for b in bgs}
    kinds, shapes, big = set(), set(), []
    for i, it in inserts:
        name = "小图 #%d (%s)" % (i, it["src"])
        box = insert_hw(it, CW, CH)
        shape, style = it.get("shape", "rect"), it.get("style", "none")
        kinds.add((shape, style)); shapes.add(shape)
        if it["src"] in bg_srcs:
            err("%s 和底图是同一张照片：小图只能用另一张照片整张放进去，不能从底图里截细节" % name)
        if style == "border":
            err("%s 用了 border 硬白边：用户觉得死板、不融合，边缘用 line 或 dash" % name)
        elif style in ("glow", "card", "polaroid", "stroke"):
            err("%s 的 %s 会在边缘铺一圈颜色或光晕：用户只要线状或虚线边缘，用 line 或 dash" % (name, style))
        if it.get("isolate") and isinstance(it.get("bg"), list):
            err("%s 的 isolate 垫了底色 bg：用户不要色块，删掉 bg 让它透明" % name)
        if box[2] - box[0] > 0.26:
            big.append(name)
        if not (-0.02 <= box[0] and box[2] <= 1.02 and -0.02 <= box[1] and box[3] <= 1.02):
            warn("%s 超出画布" % name)
        info = an.get(it["src"])
        if info and info.get("tilt_conf") == "sure" and abs(info.get("tilt", 0)) >= 1 and not it.get("straighten"):
            warn("%s 可能拍歪了：建议 \"straighten\": %s" % (name, info["tilt"]))
        if info and not it.get("isolate") and not it.get("popout"):
            f = C.SAFE.get(shape, 0.6); w, h = box[2] - box[0], box[3] - box[1]
            safe = [box[0] + w * (1 - f) / 2, box[1] + h * (1 - f) / 2, box[2] - w * (1 - f) / 2, box[3] - h * (1 - f) / 2]
            for fb in info["faces"]:
                cb = photo_to_canvas(fb, info["size"], it, box, CW, CH, card=style in ("card", "polaroid"))
                if _inter(cb, safe) < _area(cb) * 0.9:
                    err("%s 的人脸没有完整落在 %s 框的安全区里，会被框切到：调 focus/zoom、换安全区大的形状或把框做大" % (name, shape))
                if (cb[3] - cb[1]) / h > 0.5:
                    warn("%s 脸占了框高的一半以上，像只剩一张大头：zoom 调小或换 arch/oval 留到肩膀" % name)
            if info["faces"] and not it.get("popout") and (box[1] + box[3]) / 2 > 0.62:  # a popout frame is the main figure, not a face insert
                err("%s 是人像小图却放在画面下部：人脸特写要放在和底图人物头部差不多高或更高" % name)
            s = info.get("subject")
            if not info["faces"] and s and s["area"] < 0.8:
                cb = photo_to_canvas(s["box"], info["size"], it, box, CW, CH, card=style in ("card", "polaroid"))
                if _inter(cb, safe) < _area(cb) * 0.85:
                    warn("%s 的主体可能被框切掉一部分（框里要放一个完整的东西）：看 _check.jpg 确认，必要时用 pad 或 isolate" % name)
                if s["touches_edge"] and not it.get("pad"):
                    warn("%s 的主体在原图里贴着%s边，可能本来就不完整，考虑 pad 或换图" % (name, "/".join(s["touches_edge"])))
        for src, fb in bg_faces:
            if _inter(box, fb) > _area(fb) * 0.05:
                err("%s 挡住了底图 %s 里的脸" % (name, src))
        for src, sb in bg_subj:
            if _inter(box, sb) > _area(box) * 0.3:
                warn("%s 压在底图主体上，确认没挡住要看的东西" % name)
    if len(kinds) > 3:
        err("小图边框有 %d 种（形状+样式），最多 3 种：%s" % (len(kinds), sorted(kinds)))
    if shapes & REGULAR and shapes & IRREGULAR:
        warn("一页里规则形状 %s 和不规则形状 %s 混用：同一页用同一家族" % (sorted(shapes & REGULAR), sorted(shapes & IRREGULAR)))
    if len(big) > 1:
        warn("较大的小图（宽 > 0.26）有 %d 张，一页最多一张主小图：%s" % (len(big), ", ".join(big)))
    if len(inserts) > 4:
        warn("小图有 %d 张，偏多：留白不够时 2 到 3 张就够" % len(inserts))
    # inserts overlapping each other a lot
    for a in range(len(inserts)):
        for b in range(a + 1, len(inserts)):
            ba, bb = insert_hw(inserts[a][1], CW, CH), insert_hw(inserts[b][1], CW, CH)
            if _inter(ba, bb) > 0.35 * min(_area(ba), _area(bb)):
                warn("小图 #%d 和 #%d 重叠超过三分之一，确认是有意错位叠放" % (inserts[a][0], inserts[b][0]))

    # ---- decorations
    for i, it in enumerate(layers):
        t = it["type"]
        if t in ("photo",) or t in ATMOSPHERE:
            continue
        bb = bbox(it, CW, CH)
        if not bb:
            continue
        for src, fb in bg_faces:
            if _inter(bb, fb) > _area(fb) * 0.05:
                (warn if t in SCATTER else err)("#%d %s 压到了底图 %s 里的脸" % (i, t, src))
            elif t not in SCATTER and _inter(bb, [fb[0] - 0.03, fb[1] - 0.03 * CW / CH, fb[2] + 0.03, fb[3] + 0.03 * CW / CH]) > 0:
                warn("#%d %s 离底图 %s 里的脸不到画布宽的 3%%，给人物留点呼吸空间" % (i, t, src))
        for _, it2 in inserts:
            info = an.get(it2["src"])
            if t in DECOR and info and info["faces"] and not it2.get("isolate"):
                ib = insert_hw(it2, CW, CH)
                for fb in info["faces"]:
                    cb = photo_to_canvas(fb, info["size"], it2, ib, CW, CH)
                    if _inter(bb, cb) > _area(cb) * 0.08:
                        (warn if t in SCATTER else err)("#%d %s 压到了小图 %s 里的脸" % (i, t, it2["src"]))
    deco = [it for it in layers if it["type"] in DECOR]
    n = len(deco)
    # No minimum decoration count or mandatory decoration families: these checks
    # encouraged filling empty space with unrelated ornaments. Keep only a gentle
    # warning for genuinely dense layouts.
    if n > 18:
        warn("装饰元素较多（%d 个）；检查是否有元素只是在填空，优先删除无明确作用的装饰" % n)
    if sum(it["type"] == "sparkring" for it in layers) > 1:
        warn("碎钻光环超过 1 个；另外用户觉得大光环套在饮料上很怪，只套小物件")
    for it in layers:
        if it["type"] == "sticker":
            warn("抠图 %s：确认光线方向、色温和比例和放进去的场景对得上，不像硬贴；饮料、食物不要抠了贴在风景上" % it["src"])
            if it.get("outline", 0) > 0:
                warn("sticker %s 带奶白描边，硬边容易显得死板，考虑 \"outline\": 0" % it["src"])
        if it["type"] == "text":
            warn("有文字 %r：确认是用户要的、写的是用户给的内容（不要自己编标题）" % it["text"][:12])
            tb = bbox(it, CW, CH)
            if bg_empty and sum(_inter(tb, e) for e in bg_empty) < 0.5 * _area(tb):
                warn("文字 %r 大部分不在底图的留白里（看 analyze 叠图的蓝格），可能压在人物或杂乱处" % it["text"][:12])
        if it["type"] in ("photo", "sticker") and it.get("pad") and it.get("pad") > 1.6:
            warn("%s pad 太大，扩展出的模糊边会很明显" % it["src"])
    # ---- artistic techniques: every page needs at least 2, never just photos side by side in boxes
    boxes = [bbox(it, CW, CH) for it in layers if it["type"] in ("photo", "sticker")]
    regions = [b.get("region", [0, 0, 1, 1]) for b in bgs]
    tech = set()
    if any(b.get("opacity", 1) < 1 or b.get("feather") for b in bgs[1:]) or any(it.get("opacity", 1) < 1 for it in layers if it["type"] == "photo"):
        tech.add("双重曝光/叠印过渡")
    if any(it["type"] == "sticker" or it.get("isolate") or it.get("popout") for it in layers):
        tech.add("抠图/出框")
    if any(it["type"] == "fill" and (it.get("src") or it.get("paint")) for it in layers):
        tech.add("重构底图（照片纹理或手绘填充）")
    if any(it["type"] == "threads" for it in layers) and boxes:
        tech.add("悬挂连接")
    areas = boxes + [list(r) for r in regions if r != [0, 0, 1, 1]]
    def hits(pt):
        return sum(1 for a in areas if a[0] <= pt[0] <= a[2] and a[1] <= pt[1] <= a[3])
    for it in layers:
        if it["type"] in ("vine", "threads") and it.get("points"):
            touched = {i for p_ in it["points"] for i, a in enumerate(areas) if a[0] <= p_[0] <= a[2] and a[1] <= p_[1] <= a[3]}
            if len(touched) >= 2:
                tech.add("跨图连接")
    for i, a in enumerate(boxes):
        if any(j != i and _inter(a, b) > 0.002 for j, b in enumerate(boxes)) or any(_inter(a, list(r)) > 0.002 and _inter(a, list(r)) < _area(a) - 0.002 for r in regions if r != [0, 0, 1, 1]):
            tech.add("互相压叠/跨接缝")
    if len(tech) < 2:
        err("只用了 %d 种艺术手法（%s）：每页至少 2 种——双重曝光/叠印过渡、抠图/出框、跨图连接、互相压叠/跨接缝；不要只是几张照片各占一格"
            % (len(tech), "、".join(sorted(tech)) or "无"))

    # ---- photo count / repetition / hierarchy (bad_ examples: too few photos, near-duplicates, object bigger than the person)
    if len(srcs) < 3:
        err("整页只用了 %d 张不同的照片，至少要 3 张" % len(srcs))
    used = [b["src"] for b in bgs] + [it["src"] for it in layers if it["type"] in ("photo", "sticker")]
    for s_ in sorted({u for u in used if used.count(u) > 1}):
        warn("%s 在页面里用了不止一次；同一张照片重复出现会显得凑数（叠印同一张除外）" % s_)
    people = any(an.get(x) and an[x]["faces"] for x in srcs)
    for i, it in enumerate(layers):
        if it["type"] != "photo" or not an.get(it["src"]) or an[it["src"]]["faces"]:
            continue
        bb = bbox(it, CW, CH)
        if people and _area(bb) > 0.16:
            warn("#%d %s 是没有人物的物件或风景小图，却占了画面 %.0f%%：细节图不要比人物主图还抢眼" % (i, it["src"], _area(bb) * 100))

    # ---- decorations bunched into one corner (bad_ example: everything piled on the bottom-right)
    if n >= 5:
        quad = [0, 0, 0, 0]
        for it in deco:
            bb = bbox(it, CW, CH); cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            quad[(cx > 0.5) + 2 * (cy > 0.5)] += 1
        if max(quad) > 0.6 * n:
            warn("%d 个装饰里有 %d 个挤在同一个四分之一画面里；装饰要跟着锚点走，不要堆在一个角" % (n, max(quad)))

    # ---- colour: default is bright & clear (Fuji straight-out-of-camera)
    look = layout.get("look", "forest_light")
    if look != "forest_light":
        warn("look 是 %r：默认是 forest_light（明亮清透），其他滤镜只在用户要求时用" % look)
    if layout.get("grade", "clear") != "clear":
        warn("grade 是 %r：默认是 clear；forest、warm 会抬黑位或偏色，画面容易发灰发黄" % layout.get("grade"))
    if layout.get("unify", 0.0) > 0.05:
        warn("unify %.2f：会把整页染成同一种绿，失去真实感；默认 0" % layout.get("unify", 0.0))
    if layout.get("bloom", 0.12) > 0.18:
        warn("bloom %.2f 偏高，高光会糊成一片雾，细节不清楚；默认 0.12" % layout.get("bloom"))
    if layout.get("vignette", 0.0) > 0.05:
        warn("vignette 暗角会让画面发闷；默认 0")
    if layout.get("match", 0.35) < 0.15:
        warn("match %.2f 偏低，几张照片的亮度和偏色可能对不上；默认 0.35" % layout.get("match", 0.35))

    # ---- report
    for m in E:
        print("ERROR ", m)
    for m in W:
        print("WARN  ", m)
    print("—— %d 个错误，%d 个提醒" % (len(E), len(W)) if E or W else "—— 全部通过")

    if rendered and os.path.exists(rendered):
        im = Image.open(rendered).convert("RGB"); d = ImageDraw.Draw(im); w, h = im.size
        R = lambda b: [b[0] * w, b[1] * h, b[2] * w, b[3] * h]  # noqa: E731
        for i, it in enumerate(layers):
            bb = bbox(it, CW, CH)
            if bb and it["type"] not in ATMOSPHERE:
                d.rectangle(R(bb), outline=(255, 255, 255) if it["type"] == "photo" else (255, 220, 0), width=2)
                d.text((bb[0] * w + 3, bb[1] * h + 2), "#%d" % i, fill=(255, 255, 0))
        for _, fb in bg_faces:
            d.rectangle(R(fb), outline=(255, 40, 40), width=4)
        out = os.path.splitext(rendered)[0] + "_lint.jpg"; im.save(out, quality=85)
        print("lint overlay:", out)
    return len(E)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(1 if lint(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None) else 0)
