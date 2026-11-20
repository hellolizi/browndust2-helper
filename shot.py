"""游戏窗口截图：--list 列出窗口，默认抓取游戏客户区并存 PNG。"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from bd2 import imgio, win32


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--window", default="BrownDust")
    ap.add_argument("--class", dest="cls", default="")
    ap.add_argument("--out", default="debug/game.png")
    ap.add_argument("--scale", type=int, default=1, help="降采样倍数，减小图片体积")
    ap.add_argument("--crop", default="", help="裁剪 x,y,w,h（客户区坐标）")
    args = ap.parse_args()

    if args.list:
        for w in win32.list_windows(min_size=100):
            print(f"[{w['class']}] {w['title']!r} rect={w['rect']}")
        return

    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        print("没找到窗口: " + args.window)
        return
    x, y, w0, h0 = win32.client_rect(hwnd)
    print(f"窗口 {win32.title(hwnd)!r} 客户区 {w0}x{h0} @ ({x},{y})")
    if not win32.focus(hwnd):
        print("[警告] 无法把窗口切到前台，截图可能被遮挡")

    with win32.Grabber(hwnd) as g:
        frame = g.grab()
    if args.crop:
        cx, cy, cw, ch = (int(v) for v in args.crop.split(","))
        frame = frame[cy : cy + ch, cx : cx + cw]
    if args.scale > 1:
        k = args.scale
        h2, w2 = frame.shape[0] // k, frame.shape[1] // k
        frame = frame[: h2 * k, : w2 * k].reshape(h2, k, w2, k, 3).mean(axis=(1, 3)).astype(np.uint8)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    imgio.write_png(args.out, frame)
    print(f"已保存 {args.out}")


if __name__ == "__main__":
    main()
