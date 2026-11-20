"""钻石护栏：任务前后各读一次顶栏货币，钻石/付费钻只要变少就报错并中止。

BD2 大厅顶栏（1920x1080）实测坐标：
    钻石    (1090,46)-(1160,72)
    金币    (1214,46)-(1338,70)
    付费钻石 (1350,46)-(1468,70)
只盯钻石与付费钻石；金币允许变化（任务里花金币正常）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bd2 import win32  # noqa: E402
from story_ocr import _get_engine  # noqa: E402

BOXES = {
    "diamond": (1090, 46, 1160, 72),
    "gold": (1214, 46, 1338, 70),
    "paid": (1350, 46, 1468, 70),
}


def _ocr_num(frame: np.ndarray, box: tuple[int, int, int, int]) -> int | None:
    x1, y1, x2, y2 = box
    im = Image.fromarray(frame[max(0, y1 - 8): y2 + 8, max(0, x1 - 8): x2 + 8]).convert("RGB")
    im = im.resize((im.width * 3, im.height * 3), Image.LANCZOS)
    out, _ = _get_engine()(np.array(im))
    if not out:
        return None
    text = "".join(str(r[1]) for r in out)
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def read_currency(hwnd: int) -> dict:
    with win32.Grabber(hwnd) as g:
        frame = g.grab()
    cur = {k: _ocr_num(frame, box) for k, box in BOXES.items()}
    # 数字框偶尔会粘进隔壁图标/分隔符，出现离谱位数就当没读到，别污染比对基线
    LIMITS = {"diamond": 10_000_000, "gold": 999_999_999, "paid": 99_999_999}
    for k, v in list(cur.items()):
        if v is not None and v > LIMITS[k]:
            cur[k] = None
    return cur


def check(before: dict, after: dict) -> tuple[bool, str]:
    msgs, bad = [], False
    for key, label in (("diamond", "钻石"), ("paid", "付费钻石")):
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            msgs.append(f"{label} 未识别（{b}->{a}）")
            continue
        if a < b:
            bad = True
            msgs.append(f"{label} 变少 {b}->{a}")
        else:
            msgs.append(f"{label} {b}->{a}")
    gold_b, gold_a = before.get("gold"), after.get("gold")
    if gold_b is not None and gold_a is not None:
        msgs.append(f"金币 {gold_b}->{gold_a}")
    return (not bad), "; ".join(msgs)


def main() -> int:
    hwnd = win32.find_window("BrownDust II", "UnityWndClass")
    if not hwnd:
        print("游戏未运行")
        return 2
    win32.focus(hwnd)
    time.sleep(0.4)
    snap = read_currency(hwnd)
    print(json.dumps(snap, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
