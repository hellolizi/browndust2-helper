"""在游戏客户区坐标点一下：python click.py --x 960 --y 730"""
from __future__ import annotations

import argparse
import sys

from bd2 import win32


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", type=int, required=True)
    ap.add_argument("--y", type=int, required=True)
    ap.add_argument("--window", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    ap.add_argument("--no-focus", action="store_true")
    args = ap.parse_args()

    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        sys.exit("没找到游戏窗口")
    if not args.no_focus and not win32.focus(hwnd):
        sys.exit("无法激活游戏窗口")
    x, y, w0, h0 = win32.client_rect(hwnd)
    if not (0 <= args.x < w0 and 0 <= args.y < h0):
        sys.exit(f"坐标超出客户区 {w0}x{h0}")
    win32.click_client(hwnd, args.x, args.y)
    print(f"已点击 ({args.x},{args.y}) 窗口 {w0}x{h0}")


if __name__ == "__main__":
    main()
