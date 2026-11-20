"""从当前游戏画面裁一个矩形，存成 BMP 模板。

用法:
  python mktpl.py --rect "720,240,480,80" --out templates/skip_title.bmp
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bd2 import imgio, win32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    ap.add_argument("--rect", required=True, help="x,y,w,h")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        sys.exit("没找到游戏窗口")
    x, y, w, h = (int(v) for v in args.rect.split(","))
    with win32.Grabber(hwnd) as g:
        frame = g.grab()
    crop = frame[y : y + h, x : x + w]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    imgio.write_bmp(args.out, crop)
    print(f"已保存 {args.out} ({w}x{h})")


if __name__ == "__main__":
    main()
