#!/usr/bin/env python3
"""Render the Gumroad cover (1280x720) and thumbnail (1200x1200) from cover.html.

    python3 widget/store/render.py

Serves the widget folder on 127.0.0.1, screenshots the page with Moli, crops
the PNGs to size (stdlib only), then stops the server.
"""

import http.server
import os
import pathlib
import struct
import subprocess
import threading
import zlib

STORE = pathlib.Path(__file__).resolve().parent
WIDGET = STORE.parent
MOLI = os.path.expanduser("~/.local/bin/moli")


def read_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and ctype in (2, 6) and lace == 0, "unsupported PNG"
            bpp = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw, stride, rows, prev = zlib.decompress(idat), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return w, h, bpp, rows


def write_png(path: pathlib.Path, w: int, h: int, bpp: int, rows) -> None:
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    ctype = 6 if bpp == 4 else 2
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def shoot(url: str, out: pathlib.Path, width: int, height: int) -> None:
    png = subprocess.run([MOLI, "fetch", "--layout", "--dump", "screenshot_full",
                          "--wait-until", "networkidle", "--delay-ms", "2000", url],
                         capture_output=True, check=True).stdout
    w, h, bpp, rows = read_png(png)
    assert w >= width and h >= height, f"screenshot too small: {w}x{h}"
    write_png(out, width, height, bpp, [r[:width * bpp] for r in rows[:height]])
    print(f"wrote {out.name} ({width}x{height})")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WIDGET), **k)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/store/cover.html"
    try:
        shoot(base, STORE / "cover.png", 1280, 720)
        shoot(base + "?thumb", STORE / "thumbnail.png", 1200, 1200)
    finally:
        server.shutdown()
