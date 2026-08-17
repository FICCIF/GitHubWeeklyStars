#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用纯标准库生成 app 图标 icon.ico（256x256 渐变底 + 白色五角星）。"""

import math
import os
import struct
import zlib

W = H = 256


def lerp(a, b, t):
    return int(a + (b - a) * t)


def star_points(cx, cy, r_outer, r_inner, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(n * 2):
        r = r_outer if i % 2 == 0 else r_inner
        a = rot + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def in_poly(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def make_png():
    star = star_points(W / 2, H / 2, 94, 38)
    rows = []
    for y in range(H):
        row = bytearray([0])  # filter type 0
        for x in range(W):
            t = y / H
            if in_poly(x + 0.5, y + 0.5, star) or in_poly(x + 0.5, y + 0.5, star_points(W / 2, H / 2, 30, 12)):
                r, g, b, a = 255, 255, 255, 255
            else:
                r = lerp(0x4F, 0x9F, t)
                g = lerp(0x6E, 0x8A, t)
                b = lerp(0xF7, 0xEA, t)
                a = 255
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    idat = zlib.compress(raw, 9)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b""))


def make_ico():
    png = make_png()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    with open(out, "wb") as f:
        f.write(make_ico())
    print("icon.ico generated:", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
