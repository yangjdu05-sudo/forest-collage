# 元素速查

所有坐标、尺寸都是画布比例（0 到 1）。`colors` 里可以用颜色名：p1 到 p5、a1 到 a4（从本页照片自动提取）；mint、lime、pink、lilac、cream、sky、white（固定）；`palette` 里自定义的名字（例如 `"mango": [255, 220, 100]`）。

## 页面顶层

| 键 | 说明 |
| --- | --- |
| photo_dir | 照片文件夹（相对 JSON 所在目录） |
| canvas | 默认 [1320, 1760] |
| look | 整页滤镜：forest_light（默认，明亮清透）；fresh、fresh_teal、fresh_warm、fresh_soft、mist、sun、cream、film 只在用户要求时用 |
| grade | 每张照片的底色调整：clear（默认，不偏色不抬黑位）；forest、warm 只在用户要求时用 |
| match | 先把各张照片的偏色、亮度、饱和度往一起拉，默认 0.35，0 关闭 |
| vignette | 暗角，默认 0 |
| unify / bloom / grain | 默认 0 / 0.12 / 3 |
| glint | 装饰闪光强度，推荐 0.8；0.5 更收敛，1.5 更闪。单个元素可写 `"glint": 0` |
| beautify | true 时所有照片做美化（也可以只给单张照片写） |
| palette | 自定义颜色 |
| seed | 随机种子，换一个数装饰的随机分布就会变 |
| seconds / fps | 动态版时长和帧率 |
| background | 底图列表，见下 |
| layers | 图层列表，按顺序叠加 |

## background（底图）

每项：`src`、`focus`、`zoom`、`region`（[x0,y0,x1,y1]，拼接时这张图占的区域）、`feather`（软过渡宽度）、`opacity`（双重曝光用）、`blur`、`pad`、`straighten`、`beautify`。

## 照片类

| type | 用途 | 关键参数 |
| --- | --- | --- |
| photo | 小图 | src, box, shape, style(none/line/dash), color, focus, zoom, crop[x0,y0,x1,y1], pad, rotate, feather, opacity, straighten, beautify；`popout`（0.4–0.7，头和手伸出框上沿）；`blur_bg`（0.04–0.08，人物保持清晰、周围杂乱背景虚化）；`"bg": "none"`（框里只留人物，照片自己的背景完全去掉，框线保留）；`erase` [[x,y,r],...]（框内比例坐标，擦掉抠图带进来的杂物碎块）；`outline` [[颜色, 宽度], ...]（和 bg none + popout 一起用：给整个抠出的人描漫画出场式的边，由内到外，宽度是框宽比例，例如 [["white",0.012],[浅蓝,0.006]]，也能盖住抠图残边） |
| photo + isolate | 只取一个完整物体，透明底，物体轮廓就是边缘 | isolate("auto" 抠图 / "ellipse" 圆形物体被手指挡边时用), obj[x0,y0,x1,y1]（物体在原图里的范围，从 analyze 叠图读）, inset, fill（物体大小，默认 0.92）, offset, upright；bg 默认 "none"（透明），旧的底色渐变写颜色列表，用户不喜欢 |
| sticker | 抠出的人物或物体 | src, box([x,y,w]，高度按原比例), crop, flip, straighten, beautify；默认无描边无光晕，`shadow` 默认 0.2。下半身难抠干净时 crop 到腰，让人从画布底边升起来 |
| seam | 拼接处的发光分界线 | points[[x0,y0],[x1,y1]], wave, waves, width, alpha, colors |

形状：rect、rounded、scallop、arch、oval、circle、star、heart（规则家族）；blob、cloud、flower、clover（不规则家族）。
样式：**line**（细实线，推荐）、**dash**（虚线，推荐）、none（无边）；glow、stroke、card、polaroid 会在边缘铺一圈颜色或光晕，border 是硬白边，用户都不喜欢，避免。
line / dash 的参数：line_glow（0.4–0.7，细线带一点点柔光）、color（线色，默认白）、width（线宽，默认 0.009 倍框宽）、dash（虚线每段长度，默认 0.05）、gap（线离边缘的距离，0.02 左右像裁切线）、line_alpha。

## 装饰类

| type | 用途 | 关键参数 |
| --- | --- | --- |
| dots | 点阵小图案 | pattern, pos（左上角）, cell, alpha, colors |
| dotfield | CCD 点阵纹理 | region, step, alpha, columns, colors |
| doodle | 手绘描边小图形 | shape, pos（中心）, size, width, rotate, fill, colors |
| vine | 手绘藤蔓 | points, curls, width, alpha, colors |
| confetti | 彩色小圆点 | region, count, size[min,max], colors |
| sparkles | 四角闪光星 | region, count, size, alpha, colors |
| bubbles | 透明泡泡 | region, count, size[min,max], colors |
| symbols | 小符号串 | text, pos, size, colors |
| sunlight | 阳光氛围 | pos, angle, spread, rays, ray_alpha, glow, glow_alpha, reach |
| halo / leak | 柔光点、漏光 | pos, r, alpha, color |
| cutout | 负形镂空小卡 | box[x,y,w,h], shape, color, opacity |
| text | 文字 | text（\n 换行）, pos（中心 x, 顶部 y）, size, font（路径或 "LongCang" 这类名字）, style("bounce"), seed, line_height, color |

dots 的 pattern：flower2、flower、tulip、leaf、butterfly、mushroom、clover、cherry、sun、drop、bow、star、moon、cloud、heart2、heart、note、sparkle。

已下载的手写字体名：ZCOOLKuaiLe（默认）、LongCang、ZhiMangXing、MaShanZheng、LiuJianMaoCao、ZCOOLQingKeHuangYou。

## 喷枪光感元素

| type | 用途 | 关键参数 |
| --- | --- | --- |
| orb | 喷枪光球，中心到边缘渐变带颗粒 | pos, r, colors[中心,边缘], alpha, soft, grain, squash, solid, core, core_color |
| hang | 悬挂光滴：细线垂下，末端带高光的水滴 | pos（水滴中心）, r, length, colors[上,下], halo, alpha |
| rings | 喷枪同心光圈，可压扁成地面光环 | pos, r, colors（外到内）, squash, blur, alpha |
| threads | 从上方垂下的彩色发光细线 | lines[[x, y0, y1, "bead"/"curl"/"ring"/"none"], ...], colors, width, bead |
| loop | 小霓虹圈 | pos, r, color, fill, squash, width, rotate |
| sprayflower | 点彩喷漆小花 | pos, size, colors[花瓣,花心], petals, turn, stem, stem_color, rotate |
| pool | 地面彩虹光洼 | pos, w, h, colors, alpha, grain |
| fill | 盖住底图难看的部分（栏杆、杂物），保留好看的部分 | region；`edge` [[x,y],...] 上沿折线（栏杆是斜的就沿着斜线走，先在 analyze 网格上读几个点）；feather、wavy（上沿起伏，像灌木顶）；填充二选一：`src` + `crop` 用她自己照片里的草丛、树丛、水面当前景（推荐，可加 blur、flip），或 `colors` 渐变色块（不要用和天空相同的颜色，会像天空流下来）；或 `"paint": "waves"` 用代码原创画的海浪（colors [远处倒影, 近处, 深处, 浪花]，从照片取色）；`crest` [振幅, 周期]（上沿做成起伏的浪形，不是直线） |
| haze | 大片色雾 | region, colors, r, alpha（0.2 到 0.3） |
| sparkring | 碎钻光环，像星球环绕在物体外 | pos, r, tilt, rotate, colors, thick, density, back, band, flare, flares, spin |

用法：
- hang、threads 从伞沿、树冠、屋檐这类上方结构垂下最自然。
- rings、orb 放在人物手心或主体身后，做出捧着光的效果；放在小图图层前面就是光圈托底。
- sparkring 套在手里的小物件（水果）外面，一页最多一个；不要套饮料，用户觉得大光环套饮料很怪。
- pool 放在地面或画面最下沿。sprayflower 可以代替一部分点阵花，和点阵混用更有层次。
- 光感元素同样从照片取色，不能压在脸上。

## 动态版

会动的：sparkles 闪烁、sparkring 旋转闪光、hang 摆动、orb 和 rings 呼吸、loop 转动、dots 明暗、doodle 和 sprayflower 轻摇、bubbles 漂浮、pool 明暗。单个元素 `"anim": false` 不动；`speed`、`amp` 调快慢和幅度。照片和调色只算一次，不会抖。
