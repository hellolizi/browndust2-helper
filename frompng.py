"""从 PNG 截图裁一块出来存成 BMP 模板（离线用，不需要游戏在前台）。

用法：
    python frompng.py --src debug/pack_btn.png --rect "109,65,241,50" --out templates/play_btn.bmp
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image

from bd2 import imgio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--rect", required=True, help="x,y,w,h（相对源图）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    x, y, w, h = (int(v) for v in args.rect.split(","))
    im = Image.open(args.src).convert("RGB")
    if x < 0 or y < 0 or x + w > im.width or y + h > im.height:
        sys.exit(f"裁剪越界：图 {im.width}x{im.height}，请求 {x},{y},{w},{h}")
    crop = np.array(im.crop((x, y, x + w, y + h)))
    bgr = crop[:, :, ::-1].copy()  # RGB -> BGR
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    imgio.write_bmp(args.out, bgr)
    print(f"已写出 {args.out} ({w}x{h})")


if __name__ == "__main__":
    main()
