"""灰度模板匹配：4 倍降采样粗搜 + 原分辨率精修，纯 numpy。

只做 NCC（归一化互相关），对亮度整体变化不敏感；搜索范围限定在配置的 ROI 内。
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv

# BGR 顺序
_GRAY_W = np.array([0.114, 0.587, 0.299], dtype=np.float32)
MIN_COARSE = 0.45


def gray(bgr: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(bgr[..., :3], dtype=np.float32) @ _GRAY_W


def downscale(img: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return img
    h, w = img.shape[:2]
    h2, w2 = h // k, w // k
    if h2 == 0 or w2 == 0:
        return img
    return img[: h2 * k, : w2 * k].reshape(h2, k, w2, k).mean(axis=(1, 3))


def ncc_best(img: np.ndarray, tpl: np.ndarray) -> tuple[float, int, int]:
    """返回 (最高 NCC 分数, 左上角 x, 左上角 y)。"""
    img = np.ascontiguousarray(img, dtype=np.float32)
    tpl = np.ascontiguousarray(tpl, dtype=np.float32)
    th, tw = tpl.shape
    if img.shape[0] < th or img.shape[1] < tw:
        return -1.0, 0, 0

    win = swv(img, (th, tw))
    n = float(th * tw)
    t = tpl - tpl.mean()
    tss = float((t * t).sum())

    if tss < 1e-6:
        # 纯色模板：退化为平均绝对差
        mad = np.abs(win - tpl.mean()).mean(axis=(-1, -2))
        i = int(np.argmin(mad))
        y, x = divmod(i, win.shape[1])
        return float(max(0.0, 1.0 - mad[y, x] / 64.0)), x, y

    wmean = win.mean(axis=(-1, -2))
    wvar = (win * win).mean(axis=(-1, -2)) - wmean * wmean
    num = (win * t).sum(axis=(-1, -2))
    denom = np.sqrt(n) * np.sqrt(np.maximum(wvar, 1e-3)) * np.sqrt(tss)
    score = num / denom

    i = int(np.argmax(score))
    y, x = divmod(i, score.shape[1])
    return float(score[y, x]), x, y


def find(
    frame: np.ndarray,
    tpl: np.ndarray,
    rect: tuple[int, int, int, int],
    k: int = 4,
) -> tuple[float, tuple[int, int] | None]:
    """在 frame 的 rect(x,y,w,h) 区域内找 tpl，返回 (分数, 模板中心坐标)。"""
    x0, y0, w, h = rect
    roi = frame[y0 : y0 + h, x0 : x0 + w]
    if roi.ndim == 3:
        roi = gray(roi)
    if tpl.ndim == 3:
        tpl = gray(tpl)
    th, tw = tpl.shape
    if roi.shape[0] < th or roi.shape[1] < tw:
        return -1.0, None

    cimg = downscale(roi, k)
    ctpl = downscale(tpl, k)
    s, cx, cy = ncc_best(cimg, ctpl)
    if s < MIN_COARSE:
        return s, None

    # 精修：在 1/2 尺度局部搜索，误差 <=2px，成本约为原分辨率的 1/4
    rk = 2 if k > 1 else 1
    rth, rtw = th // rk, tw // rk
    fx, fy = cx * k, cy * k
    pad = 3 * k
    rx0 = max(0, fx - pad)
    ry0 = max(0, fy - pad)
    rx1 = min(roi.shape[1], fx + pad + tw)
    ry1 = min(roi.shape[0], fy + pad + th)
    sub = downscale(roi[ry0:ry1, rx0:rx1], rk)
    stpl = downscale(tpl, rk)
    if sub.shape[0] >= rth and sub.shape[1] >= rtw:
        s2, x2, y2 = ncc_best(sub, stpl)
        if s2 >= s:
            return s2, (x0 + rx0 + x2 * rk + tw // 2, y0 + ry0 + y2 * rk + th // 2)
    return s, (x0 + fx + tw // 2, y0 + fy + th // 2)
