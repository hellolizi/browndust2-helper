"""自检：BMP 读写、模板匹配正确性与耗时、窗口枚举（可选真实窗口截图）。"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

from bd2 import imgio, vision, win32


def test_bmp(tmp: str = "debug/selftest.bmp") -> None:
    os.makedirs("debug", exist_ok=True)
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    imgio.write_bmp(tmp, img)
    back = imgio.read_bmp(tmp)
    assert back.shape == img.shape, (back.shape, img.shape)
    assert np.array_equal(back, img), "BMP 往返不一致"
    print("[ok] BMP 读写")


def test_match() -> None:
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    tpl = frame[80:144, 120:184].copy()
    gray = vision.gray(frame)
    tgray = vision.gray(tpl)

    for k in (1, 4):
        t0 = time.perf_counter()
        s, loc = vision.find(gray, tgray, (0, 0, 320, 240), k=k)
        dt = (time.perf_counter() - t0) * 1000
        assert s > 0.95, f"k={k} 分数过低 {s}"
        assert loc is not None
        assert abs(loc[0] - 152) <= 2 and abs(loc[1] - 112) <= 2, (k, loc)
        print(f"[ok] 匹配 k={k}: 分数={s:.3f} 位置={loc} 耗时={dt:.1f}ms")

    # 负样本
    other = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    s2, _ = vision.find(vision.gray(other), tgray, (0, 0, 320, 240), k=4)
    assert s2 < 0.75, f"负样本分数异常高 {s2}"
    print(f"[ok] 负样本分数={s2:.3f}")


def test_grabber() -> None:
    wins = win32.list_windows()
    print(f"[ok] 枚举到 {len(wins)} 个可见窗口")
    target = None
    for name in ("记事本", "Notepad", "Untitled"):
        for w in wins:
            if name.lower() in w["title"].lower():
                target = w
                break
        if target:
            break
    if not target:
        print("[skip] 没有找到记事本窗口，跳过真实截图测试（可用 notepad 打开一个窗口再跑）")
        return
    with win32.Grabber(target["hwnd"]) as g:
        t0 = time.perf_counter()
        frame = g.grab()
        dt = (time.perf_counter() - t0) * 1000
    x, y, w0, h0 = win32.client_rect(target["hwnd"])
    assert frame.shape[:2] == (h0, w0), (frame.shape, (h0, w0))
    assert frame.mean() > 1, "截图全黑"
    print(f"[ok] 截图 {target['title']!r} {w0}x{h0} 均值={frame.mean():.1f} 耗时={dt:.1f}ms")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    test_bmp()
    test_match()
    test_grabber()
    print("全部通过")
