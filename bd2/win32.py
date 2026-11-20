"""Win32 最小封装：窗口查找、客户区截图（BitBlt）、鼠标点击、热键。

只依赖 ctypes + numpy，不引入 pywin32 / mss / Pillow。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as w

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
GA_ROOT = 2

# 进程设为 DPI 感知，保证客户区坐标 == 物理像素
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", w.LONG),
        ("biHeight", w.LONG),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


# ---------- 窗口 ----------

user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsIconic.argtypes = [w.HWND]
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
user32.WindowFromPoint.argtypes = [w.POINT]
user32.WindowFromPoint.restype = w.HWND
user32.GetAncestor.argtypes = [w.HWND, w.UINT]
user32.GetAncestor.restype = w.HWND
user32.GetForegroundWindow.restype = w.HWND
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.BringWindowToTop.argtypes = [w.HWND]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]

gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateDIBSection.argtypes = [
    w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT,
    ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD,
]
gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.BitBlt.argtypes = [
    w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD,
]


def title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def list_windows(min_size: int = 200) -> list[dict]:
    out: list[dict] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        t = title(hwnd)
        if not t:
            return True
        r = w.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left < min_size or r.bottom - r.top < min_size:
            return True
        out.append({
            "hwnd": int(hwnd),
            "title": t,
            "class": class_name(hwnd),
            "rect": [r.left, r.top, r.right, r.bottom],
        })
        return True

    user32.EnumWindows(_cb, 0)
    return out


def find_window(title_sub: str = "", class_sub: str = "") -> int:
    for info in list_windows():
        if title_sub and title_sub.lower() not in info["title"].lower():
            continue
        if class_sub and class_sub.lower() not in info["class"].lower():
            continue
        return info["hwnd"]
    return 0


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """返回客户区 (x, y, w, h)，x/y 为屏幕坐标。"""
    cr = w.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    pt = w.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, cr.right, cr.bottom


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = w.POINT(int(x), int(y))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def window_root_at(x: int, y: int) -> int:
    hwnd = user32.WindowFromPoint(w.POINT(int(x), int(y)))
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, GA_ROOT))


def set_borderless(hwnd: int, width: int = 0, height: int = 0) -> tuple[int, int]:
    """去掉标题栏/边框并固定到左上角，返回新的客户区 (w, h)。

    游戏是 Unity 窗口，去掉 WS_CAPTION/WS_THICKFRAME 后窗口矩形就等于客户区，
    截图坐标和点击坐标从此完全一致，也不会被误拖动。
    """
    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU = 0x00080000
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    new_style = style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    if new_style != style:
        user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

    x, y, w0, h0 = client_rect(hwnd)
    if width <= 0:
        width = w0 or 1920
    if height <= 0:
        height = h0 or 1080
    user32.SetWindowPos(hwnd, 0, 0, 0, width, height, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    time.sleep(0.3)
    return client_rect(hwnd)[2:]


def is_borderless(hwnd: int) -> bool:
    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    return not (user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION)


def focus(hwnd: int, timeout: float = 0.3) -> bool:
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    ok = user32.SetForegroundWindow(hwnd)
    if not ok:
        fg = user32.GetForegroundWindow()
        tid_fg = user32.GetWindowThreadProcessId(fg, None)
        tid_me = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(tid_me, tid_fg, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(tid_me, tid_fg, False)
        ok = user32.GetForegroundWindow() == hwnd
    time.sleep(0.05)
    return bool(ok)


# ---------- 截图 ----------

class Grabber:
    """客户区截图，DIB Section 直写，避免 GetDIBits 拷贝。"""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.hdc_screen = user32.GetDC(None)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self._hbmp = None
        self._old = None
        self._buf = None
        self._arr = None
        self._size = (0, 0)

    def _resize(self, w0: int, h0: int) -> None:
        if self._hbmp:
            gdi32.SelectObject(self.hdc_mem, self._old)
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w0
        bmi.bmiHeader.biHeight = -h0  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self.hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        if not self._hbmp:
            raise RuntimeError("CreateDIBSection failed")
        self._old = gdi32.SelectObject(self.hdc_mem, self._hbmp)
        n = w0 * h0 * 4
        self._buf = (ctypes.c_ubyte * n).from_address(bits.value)
        self._arr = np.frombuffer(self._buf, dtype=np.uint8).reshape(h0, w0, 4)
        self._size = (w0, h0)

    def grab(self) -> np.ndarray:
        if user32.IsIconic(self.hwnd):
            raise RuntimeError("游戏窗口已最小化")
        x, y, w0, h0 = client_rect(self.hwnd)
        if w0 <= 0 or h0 <= 0:
            raise RuntimeError("客户区尺寸异常")
        if self._size != (w0, h0):
            self._resize(w0, h0)
        # 前台时 BitBlt 直接拷显存（~4ms）；被别的窗口挡住才退回 PrintWindow（~25ms，且偶发卡死）
        if user32.GetForegroundWindow() == self.hwnd:
            ok = gdi32.BitBlt(self.hdc_mem, 0, 0, w0, h0, self.hdc_screen, x, y, SRCCOPY)
            if ok and float(self._arr[::32, ::32, :3].mean()) > 3.0:
                return self._arr[:, :, :3].copy()
        ok = user32.PrintWindow(
            ctypes.c_void_p(int(self.hwnd)), ctypes.c_void_p(int(self.hdc_mem)), 2
        )  # PW_RENDERFULLCONTENT
        if not ok:
            ok = gdi32.BitBlt(self.hdc_mem, 0, 0, w0, h0, self.hdc_screen, x, y, SRCCOPY)
        if not ok:
            raise RuntimeError("抓图失败")
        # DIB 内存归 Grabber 所有，返回拷贝，避免调用方持有悬空指针
        return self._arr[:, :, :3].copy()

    def close(self) -> None:
        if self._hbmp:
            gdi32.SelectObject(self.hdc_mem, self._old)
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        if self.hdc_mem:
            gdi32.DeleteDC(self.hdc_mem)
            self.hdc_mem = None
        if self.hdc_screen:
            user32.ReleaseDC(None, self.hdc_screen)
            self.hdc_screen = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------- 鼠标 ----------

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def _send_mouse(flags: int) -> None:
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click_client(hwnd: int, x: int, y: int, settle: float = 0.02) -> None:
    sx, sy = client_to_screen(hwnd, x, y)
    user32.SetCursorPos(int(sx), int(sy))
    time.sleep(settle)
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.02)
    _send_mouse(MOUSEEVENTF_LEFTUP)


def cursor_pos() -> tuple[int, int]:
    pt = w.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)
