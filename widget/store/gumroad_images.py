#!/usr/bin/env python3
"""Make the square Gumroad images exactly 600x600.

    python3 widget/store/gumroad_images.py

Gumroad shows the product image (Library and Discover) and the profile picture
as 600x600 squares, so those three files are emitted at exactly that size:

    store/thumbnail-600.png   from store/thumbnail.png (1200x1200)
    store/avatar-600.png      from store/avatar.png    (1024x1024)

The cover stays 1280x720 (store/cover.png); it is the wide card, not a square.
Downscaling is an area average, so a light logo keeps clean edges. Stdlib only.
"""

import pathlib

from render import read_png, write_png

STORE = pathlib.Path(__file__).resolve().parent


def area_average(rows, w: int, h: int, bpp: int, size: int):
    """Shrink an image to size x size by averaging the pixels each cell covers."""
    out = []
    for y in range(size):
        y0, y1 = y * h / size, (y + 1) * h / size
        line = bytearray(size * bpp)
        for x in range(size):
            x0, x1 = x * w / size, (x + 1) * w / size
            acc = [0.0] * bpp
            weight = 0.0
            for sy in range(int(y0), min(int(y1) + 1, h)):
                wy = min(y1, sy + 1) - max(y0, sy)
                if wy <= 0:
                    continue
                row = rows[sy]
                for sx in range(int(x0), min(int(x1) + 1, w)):
                    wx = min(x1, sx + 1) - max(x0, sx)
                    if wx <= 0:
                        continue
                    k = wx * wy
                    weight += k
                    base = sx * bpp
                    for c in range(bpp):
                        acc[c] += row[base + c] * k
            if weight:
                for c in range(bpp):
                    line[x * bpp + c] = round(acc[c] / weight)
        out.append(line)
    return out


def square(src: pathlib.Path, dst: pathlib.Path, size: int = 600) -> None:
    w, h, bpp, rows = read_png(src.read_bytes())
    assert w == h, f"{src.name} is not square ({w}x{h})"
    write_png(dst, size, size, bpp, area_average(rows, w, h, bpp, size))
    print(f"wrote {dst.name} ({size}x{size})")


if __name__ == "__main__":
    square(STORE / "thumbnail.png", STORE / "thumbnail-600.png")
    square(STORE / "avatar.png", STORE / "avatar-600.png")
