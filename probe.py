"""在实时画面上测试模板匹配分。

用法:
  python probe.py --tpl templates/story_hud.bmp --roi "1480,20,420,80"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bd2 import imgio, vision, win32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    ap.add_argument("--tpl", required=True)
    ap.add_argument("--roi", required=True, help="x,y,w,h")
    ap.add_argument("--k", type=int, default=4)
    args = ap.parse_args()

    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        sys.exit("没找到游戏窗口")
    tpl = imgio.read_bmp(args.tpl)
    x, y, w, h = (int(v) for v in args.roi.split(","))
    with win32.Grabber(hwnd) as g:
        frame = g.grab()
    s, loc = vision.find(frame, tpl, (x, y, w, h), args.k)
    print(f"{os.path.basename(args.tpl)} 分数={s:.3f} 位置={loc} 模板={tpl.shape[1]}x{tpl.shape[0]}")


if __name__ == "__main__":
    main()
