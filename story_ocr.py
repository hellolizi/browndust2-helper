"""剧情画面 → 台词文本（内存 OCR，不落截图） + 可选 API 梗概。"""
from __future__ import annotations

import json
import re
import urllib.request

import numpy as np
from PIL import Image

NOISE = (
    "fps", "gpu", "cpu", "延迟", "browndust", "n/a", "×3", "f2", "f3",
    "q搜发", "未解锁", "查看下一话", "主线播放", "集数列表", "游戏卡",
    "赛季活动", "日常剧情", "年代记", "术语", "原作", "自动", "倍速",
    "主线", "集数", "继续", "播放", "赛季", "资讯", "商店",
)
UI_TIME = re.compile(r"^(下?年|下?午)\s?\d{1,4}$")
HAS_CJK = re.compile(r"[\u4e00-\u9fff]")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        # ONNX 默认吃满所有核心；限到 2 线程，CPU 从 3.5 核降到 ~0.6 核
        try:
            import rapidocr_onnxruntime.utils as _u
            _orig = _u.SessionOptions

            def _so(*a, **kw):
                so = _orig(*a, **kw)
                so.intra_op_num_threads = 2
                so.inter_op_num_threads = 1
                return so

            _u.SessionOptions = _so
        except Exception:
            pass
        from rapidocr_onnxruntime import RapidOCR
        # 关掉方向分类/膨胀，检测边长压到 640：同一帧 OCR 从 ~2.2s 降到 ~0.4s
        try:
            _engine = RapidOCR(use_angle_cls=False, use_dilation=False, limit_side_len=640)
        except Exception:
            _engine = RapidOCR()
    return _engine


def lines_from_frame(frame: np.ndarray) -> list[str]:
    """只 OCR 下部台词区（y>=400），半分辨率；比整帧快 3~5 倍。
    只收 y>=740 的文字：那才是对话框/人名，卡面简介、按钮字都在上面，不会再混进台词。"""
    im = Image.fromarray(frame[400:]).convert("RGB")
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    out, _ = _get_engine()(np.array(im))
    if not out:
        return []
    lines = []
    # 整屏是剧情卡面（有「集数列表/游戏卡/主线00」）就直接当没有台词，卡面简介不算剧情
    if any(
        any(k in str(r[1]) for k in ("集数列表", "游戏卡", "主线00", "年代记"))
        for r in out
    ):
        return []
    for item in out:
        text = re.sub(r"\s+", " ", str(item[1]).strip())
        if len(text) < 2 or not HAS_CJK.search(text):
            continue
        if any(n in text.lower() for n in NOISE) or UI_TIME.match(text):
            continue
        ys = [p[1] * 2 + 400 for p in item[0]]
        if min(ys) < 440:  # 顶部 FPS/菜单文字
            continue
        lines.append(text)
    return lines


_cache: dict = {"k": None, "v": None}


def _boxes(frame: np.ndarray, y0: int = 0) -> list[tuple[str, int, int, int, int]]:
    """OCR 画面（可只认 y0 以下区域）。同帧复用缓存，避免 locate/locate_exact 重复识别。"""
    key = (y0, frame.shape, hash(frame[::48, ::48].tobytes()))
    if _cache["k"] == key:
        return _cache["v"]
    im = Image.fromarray(frame[y0:]).convert("RGB")
    im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    out, _ = _get_engine()(np.array(im))
    items = []
    for r in out or []:
        box, text = r[0], str(r[1]).strip()
        xs = [p[0] * 2 for p in box]
        ys = [p[1] * 2 + y0 for p in box]
        items.append((text, int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
    _cache["k"], _cache["v"] = key, items
    return items


def locate(frame: np.ndarray, keywords: list[str], y_min: int = 0) -> tuple[int, int, str] | None:
    """在画面里找含关键词的文字块，返回中心点与命中的文本。"""
    for text, x1, y1, x2, y2 in _boxes(frame):
        if y1 < y_min:
            continue
        if any(k in text for k in keywords):
            return (x1 + x2) // 2, (y1 + y2) // 2, text
    return None


class AsyncReader:
    """后台线程做 OCR，主循环只丢帧，不阻塞点击。"""

    def __init__(self, collector: "Collector") -> None:
        import queue
        import threading
        self.collector = collector
        self.q: queue.Queue = queue.Queue(maxsize=4)
        self.added = 0
        self._stop = False
        self._sig = None
        self._last = 0.0
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()

    def submit(self, frame: np.ndarray) -> None:
        # 画面基本没变就不重复 OCR；再限最小间隔，避免动画场景把 CPU 打满
        import time as _t
        now = _t.time()
        if now - self._last < 1.2:
            return
        sig = hash(frame[400::24, ::24].tobytes())
        if sig == self._sig:
            return
        self._sig = sig
        self._last = now
        try:
            self.q.put_nowait(frame.copy())
        except Exception:
            try:
                self.q.get_nowait()
                self.q.put_nowait(frame.copy())
            except Exception:
                pass

    def _loop(self) -> None:
        while not self._stop:
            try:
                frame = self.q.get(timeout=0.5)
            except Exception:
                continue
            try:
                self.added += self.collector.add(lines_from_frame(frame))
            except Exception:
                pass

    def close(self) -> None:
        self._stop = True


def locate_exact(frame: np.ndarray, labels: list[str]) -> tuple[int, int, str] | None:
    """只认短标签（整串相等），避免把公告正文里的“确认”当按钮。"""
    for text, x1, y1, x2, y2 in _boxes(frame):
        clean = text.replace(" ", "")
        if clean in labels:
            return (x1 + x2) // 2, (y1 + y2) // 2, clean
    return None


class Collector:

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, new_lines: list[str]) -> int:
        added = 0
        for line in new_lines:
            if self.lines and (line == self.lines[-1] or line in self.lines[-3:]):
                continue
            if any(line == old for old in self.lines[-20:]):
                continue
            # 近似重复（气泡残句/滚动中的半句）：与近期任一行的公共字符占比过高就丢
            for old in self.lines[-6:]:
                common = sum(1 for ch in set(line) if ch in old)
                if len(line) >= 4 and common / len(set(line)) > 0.75:
                    break
            else:
                self.lines.append(line)
                added += 1
        return added

    def text(self) -> str:
        return "\n".join(f"- {s}" for s in self.lines)


def summarize(lines: list[str], api: dict, out_path: str) -> str:
    """调 OpenAI 兼容接口生成梗概，返回写出的文件路径。"""
    if not api.get("key"):
        raise RuntimeError("没有填 API Key")
    prompt = (
        "下面是一段游戏主线剧情的逐句 OCR 台词，可能有错字、断句和重复。"
        "请整理成中文剧情梗概：按场景/章节分段，保留人物名与关键事件，"
        "去掉 OCR 噪音，最后给 100 字以内总述。只输出正文。\n\n"
        + "\n".join(lines)
    )
    data = json.dumps({
        "model": api.get("model", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        api["base_url"].rstrip("/") + "/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api["key"],
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    text = resp["choices"][0]["message"]["content"]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 剧情梗概（AI 生成）\n\n" + text + "\n")
    return out_path
