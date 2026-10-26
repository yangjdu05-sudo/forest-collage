# 示例

## 水果摊页（用户认可的方向）

构图：人物居中站在水果摊前，两张小图在右上错位叠放，阳光从左上照下来，伞沿垂下几颗光滴，右手的橘子外面套一圈碎钻光环，（原版脚下有一洼彩虹光，现已去掉）。整页明亮清透，装饰带闪光边缘。这页试过在左下放四样水果的四叶草，用户觉得不协调，所以去掉了。

注意：这页最初两张小图用的是 `"style": "border"` 白边卡片；之后用户说硬白边死板、边缘铺一圈颜色也不好看，只要线或虚线，所以下面改成了 dash。之后又按现行规则改为 forest_light 调色、去掉脚下光洼 pool 和实心 doodle。

```json
{
  "photo_dir": "photos", "canvas": [1320, 1760], "grade": "clear", "look": "forest_light", "match": 0.35, "unify": 0, "bloom": 0.12, "grain": 3, "glint": 0.8, "seed": 81,
  "palette": {"apple": [250, 150, 150], "orange": [255, 186, 110], "mango": [255, 220, 100], "rice": [196, 176, 250], "teal": [170, 236, 226]},
  "background": [{"src": "stall.jpg", "focus": [0.5, 0.5]}],
  "layers": [
    {"type": "sunlight", "pos": [0.02, 0.0], "angle": 58, "spread": 34, "rays": 6, "ray_alpha": 0.18, "glow": 0.18, "glow_alpha": 0.45, "reach": 0.7},
    {"type": "haze", "region": [0.05, 0.05, 0.45, 0.25], "colors": ["mango", "teal"], "r": 0.16, "alpha": 0.25},
    {"type": "dotfield", "region": [0.04, 0.03, 0.36, 0.17], "alpha": 0.5, "colors": ["a2", "cream"]},
    {"type": "photo", "src": "orange.jpg", "box": [0.575, 0.035, 0.25, 0.26], "focus": [0.53, 0.33], "zoom": 1.05, "shape": "rounded", "style": "dash", "color": "white"},
    {"type": "photo", "src": "apple.jpg", "box": [0.735, 0.2, 0.22, 0.225], "focus": [0.45, 0.33], "zoom": 1.05, "shape": "rounded", "style": "dash", "color": "white"},
    {"type": "vine", "points": [[0.02, 0.99], [0.07, 0.88], [0.03, 0.76], [0.08, 0.66]], "curls": 3, "width": 2.4, "alpha": 0.85, "colors": ["teal", "cream"]},
    {"type": "sparkring", "pos": [0.69, 0.54], "r": 0.085, "tilt": 0.3, "rotate": -12, "colors": ["white", "cream"], "flare": 0.03},
    {"type": "dots", "pattern": "sun", "pos": [0.43, 0.06], "cell": 0.009, "alpha": 0.95, "colors": ["mango", "orange"]},
    {"type": "dots", "pattern": "butterfly", "pos": [0.64, 0.475], "cell": 0.007, "alpha": 0.9, "colors": ["rice", "sky"]},
    {"type": "dots", "pattern": "cherry", "pos": [0.27, 0.27], "cell": 0.0075, "alpha": 0.95, "colors": ["apple", "a2"]},
    {"type": "hang", "pos": [0.14, 0.34], "r": 0.02, "length": 0.1, "colors": ["teal", "rice"]},
    {"type": "hang", "pos": [0.47, 0.27], "r": 0.018, "length": 0.09, "colors": ["apple", "rice"]},
    {"type": "sprayflower", "pos": [0.06, 0.575], "size": 0.04, "colors": ["apple", "mango"], "petals": 5},
    {"type": "sprayflower", "pos": [0.92, 0.72], "size": 0.045, "colors": ["rice", "cream"], "stem": 0.08, "stem_color": "teal"},
    {"type": "loop", "pos": [0.555, 0.2], "r": 0.014, "color": "apple"},
    {"type": "bubbles", "region": [0.68, 0.83, 0.76, 0.92], "count": 3, "size": [0.012, 0.022], "colors": ["orange", "rice", "sky"]},
    {"type": "confetti", "region": [0.06, 0.18, 0.5, 0.25], "count": 16, "size": [0.0025, 0.006], "colors": ["apple", "orange", "mango", "sky", "rice"]},
    {"type": "sparkles", "region": [0.05, 0.02, 0.5, 0.14], "count": 6, "size": [0.006, 0.013], "colors": ["mango", "apple"]}
  ]
}
```

## 一个完整物体放进框里（isolate）

橘子被手指挡住边缘，用 ellipse 只取橘子本身，透明底，沿轮廓一圈白色虚线；`obj` 从 analyze 叠图的网格上读。

```json
{"type": "photo", "src": "orange.jpg", "box": [0.06, 0.62, 0.18], "style": "dash", "gap": 0.02, "color": "white",
 "isolate": "ellipse", "obj": [0.276, 0.217, 0.495, 0.383], "inset": 0.03}
```

## 风铃悬挂片段

```json
{"type": "threads", "lines": [[0.12, 0, 0.115, "none"], [0.335, 0, 0.135, "none"]], "colors": ["mango", "apple"], "width": 3},
{"type": "photo", "src": "mango.jpg", "box": [0.035, 0.11, 0.17], "shape": "circle", "zoom": 1.2, "style": "line", "color": "white"},
{"type": "photo", "src": "selfie.jpg", "box": [0.235, 0.13, 0.2, 0.235], "shape": "arch", "focus": [0.53, 0.36], "style": "line", "color": "white", "rotate": -4}
```

## 光圈托举片段（人物左手心在画布 (0.245, 0.545)）

```json
{"type": "rings", "pos": [0.245, 0.545], "r": 0.07, "alpha": 0.55, "colors": ["mango", "apple", "rice", "teal", "cream"]}
```

## 上下软拼接片段（两张同地点的远景和近景）

```json
"background": [
  {"src": "far.jpg", "region": [0, 0, 1, 0.56], "focus": [0.5, 0.4], "feather": 0.04},
  {"src": "near.jpg", "region": [0, 0.52, 1, 1], "focus": [0.5, 0.5], "feather": 0.04}
],
"layers": [{"type": "seam", "points": [[0, 0.54], [1, 0.54]], "wave": 0.006, "waves": 2, "colors": ["cream", "a1"]}]
```

## 物体双重曝光片段（第二张底图半透明叠上）

```json
"background": [
  {"src": "forest.jpg"},
  {"src": "leaf_closeup.jpg", "opacity": 0.28, "focus": [0.5, 0.4]}
]
```
