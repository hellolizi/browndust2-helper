"""24/32 位 BMP 读写，零第三方依赖（模板与调试截图都用 BMP）。"""
from __future__ import annotations

import struct

import numpy as np


def write_bmp(path: str, bgr: np.ndarray) -> None:
    h, w = bgr.shape[:2]
    rows = bytearray()
    for y in range(h - 1, -1, -1):
        rows += bgr[y].tobytes()
        pad = (-(w * 3)) % 4
        if pad:
            rows += b"\x00" * pad
    data = bytes(rows)
    filesize = 14 + 40 + len(data)
    header = b"BM" + struct.pack("<IHHI", filesize, 0, 0, 54)
    info = struct.pack(
        "<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0
    )
    with open(path, "wb") as f:
        f.write(header + info + data)


def read_bmp(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:2] != b"BM":
        raise ValueError("不是 BMP 文件: " + path)
    offset = struct.unpack_from("<I", buf, 10)[0]
    w0 = struct.unpack_from("<i", buf, 18)[0]
    h0 = struct.unpack_from("<i", buf, 22)[0]
    bpp = struct.unpack_from("<H", buf, 28)[0]
    comp = struct.unpack_from("<I", buf, 30)[0]
    if comp != 0 or bpp not in (24, 32):
        raise ValueError(f"不支持的 BMP 格式 bpp={bpp} comp={comp}")
    top_down = h0 < 0
    h = abs(h0)
    w = w0
    stride = ((w * bpp // 8) + 3) // 4 * 4
    raw = np.frombuffer(buf, dtype=np.uint8, count=stride * h, offset=offset).reshape(h, stride)
    if bpp == 24:
        img = raw[:, : w * 3].reshape(h, w, 3)
    else:
        img = raw[:, : w * 4].reshape(h, w, 4)[:, :, :3]
    if not top_down:
        img = img[::-1]
    return np.ascontiguousarray(img)


def write_png(path: str, bgr: np.ndarray) -> None:
    """24 位 PNG 写出，zlib 压缩，零第三方依赖。"""
    import zlib

    h, w = bgr.shape[:2]
    rgb = bgr[:, :, ::-1]
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    out = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(out)
