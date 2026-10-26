#!/usr/bin/env bash
# One-time environment setup for forest-collage. Safe to re-run: everything already present is skipped.
# Anything that fails to download only degrades a feature (see SKILL.md), it never blocks a render.
SK=~/.forest_collage; mkdir -p $SK/models $SK/fonts $SK/cache
python3 -c "import PIL, numpy" 2>/dev/null || pip install pillow numpy --break-system-packages -q
# OpenCV with the face module (landmarks for gentle beautify), in its own folder so it can't clash with another opencv
# (OpenCV 5 dropped the Caffe face detector, so it must be 4.x)
python3 -c "import sys; sys.path.insert(0,'$SK/models/cvc'); import cv2; cv2.face.createFacemarkLBF; cv2.dnn.readNetFromCaffe" 2>/dev/null || \
  pip install --no-deps --target $SK/models/cvc "opencv-contrib-python-headless>=4.8,<5" -q
cd $SK/models
[ -s lbfmodel.yaml ] || curl -sSL -o lbfmodel.yaml https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml
[ -s deploy.prototxt ] || curl -sSL -o deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt
[ -s res10.caffemodel ] || curl -sSL -o res10.caffemodel https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel
# cut-outs (sticker, isolate, subject box in analyze.py); falls back to OpenCV GrabCut when missing
python3 -c "import rembg" 2>/dev/null || pip install "rembg[cpu]" --break-system-packages -q
# animated version needs ffmpeg
which ffmpeg >/dev/null || (sudo apt-get install -y -q ffmpeg 2>/dev/null || apt-get install -y -q ffmpeg)
# handwritten fonts (Google Fonts, OFL)
cd $SK/fonts
for f in zcoolkuaile/ZCOOLKuaiLe longcang/LongCang zhimangxing/ZhiMangXing mashanzheng/MaShanZheng liujianmaocao/LiuJianMaoCao zcoolqingkehuangyou/ZCOOLQingKeHuangYou; do
  n=$(basename $f)-Regular.ttf
  # a failed download can leave an HTML/JSON error page behind: only keep real font files
  python3 -c "from PIL import ImageFont; ImageFont.truetype('$n', 20)" 2>/dev/null && continue
  curl -sSL -o $n https://raw.githubusercontent.com/google/fonts/main/ofl/${f%%/*}/$n
  python3 -c "from PIL import ImageFont; ImageFont.truetype('$n', 20)" 2>/dev/null || rm -f $n
done
echo "--- forest-collage setup status"
for f in $SK/models/res10.caffemodel $SK/models/lbfmodel.yaml $SK/fonts/ZCOOLKuaiLe-Regular.ttf $SK/fonts/LongCang-Regular.ttf; do
  [ -s $f ] && echo "ok      $(basename $f)" || echo "MISSING $(basename $f)"
done
python3 -c "import rembg" 2>/dev/null && echo "ok      rembg" || echo "MISSING rembg (cut-outs use GrabCut)"
which ffmpeg >/dev/null && echo "ok      ffmpeg" || echo "MISSING ffmpeg (no animated version)"
