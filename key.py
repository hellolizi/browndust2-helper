"""发送按键：python key.py --vk 27  (27=ESC)"""
from __future__ import annotations

import argparse
import sys
import time

import ctypes

from bd2 import win32

user32 = win32.user32
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_ulong]


def press(vk: int, hold: float = 0.05) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, 2, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vk", type=lambda s: int(s, 0), required=True, help="虚拟键码，如 27 / 0x1B")
    ap.add_argument("--window", default="BrownDust II")
    ap.add_argument("--class", dest="cls", default="UnityWndClass")
    args = ap.parse_args()
    hwnd = win32.find_window(args.window, args.cls)
    if not hwnd:
        sys.exit("没找到游戏窗口")
    if not win32.focus(hwnd):
        sys.exit("无法激活游戏窗口")
    press(args.vk)
    print(f"已发送 VK={args.vk}")


if __name__ == "__main__":
    main()
