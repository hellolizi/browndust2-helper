"""局部放大截图：用于辨认小图标/按钮。

用法:
  python zoom.py --crop "1420,260,100,70" --k 4 --out debug/zoom.png
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from bd2 import imgio, win32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    ap.add_argument("--crop", required=True, help="x,y,w,h")
    ap.add_argument("--k", type=int, default=4, help="整数放大倍数")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        print("没找到窗口: " + args.window)
        return
    with win32.Grabber(hwnd) as g:
        frame = g.grab()
    cx, cy, cw, ch = (int(v) for v in args.crop.split(","))
    sub = frame[cy : cy + ch, cx : cx + cw]
    z = np.repeat(np.repeat(sub, args.k, axis=0), args.k, axis=1)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    imgio.write_png(args.out, z)
    print(f"已保存 {args.out} ({z.shape[1]}x{z.shape[0]})")


if __name__ == "__main__":
    main()
