#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 README 横幅 docs/banner.png（1200x630，纯标准库）。"""

import math
import os
import struct
import zlib

W, H = 1200, 630


def lerp(a, b, t):
    return int(a + (b - a) * t)


def mix(c1, c2, t):
    return (lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t))


def in_star(x, y, cx, cy, r_outer, r_inner, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(n * 2):
        r = r_outer if i % 2 == 0 else r_inner
        a = rot + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_round_rect(x, y, rx, ry, rw, rh, radius):
    if x < rx or x > rx + rw or y < ry or y > ry + rh:
        return False
    cx = min(max(x, rx + radius), rx + rw - radius)
    cy = min(max(y, ry + radius), ry + rh - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def make_png():
    top = (0x4F, 0x6E, 0xF7)
    mid = (0x8B, 0x7C, 0xF8)
    bot = (0x9F, 0x7A, 0xEA)
    cards = [
        (540, 90, 560, 88, 18, 46),
        (540, 200, 560, 88, 18, 30),
        (540, 310, 560, 88, 18, 30),
        (540, 420, 560, 88, 18, 30),
    ]
    rows = []
    for y in range(H):
        row = bytearray([0])
        for x in range(W):
            t = (x / W) * 0.55 + (y / H) * 0.45
            base = mix(top, mid, t)
            base = mix(base, bot, y / H)
            if in_star(x + 0.5, y + 0.5, 250, 315, 150, 62):
                r, g, b = 255, 255, 255
            else:
                r, g, b = base
            a = 255
            for rx, ry, rw, rh, rad, alpha in cards:
                if in_round_rect(x + 0.5, y + 0.5, rx, ry, rw, rh, rad):
                    r = lerp(r, 255, alpha / 255)
                    g = lerp(g, 255, alpha / 255)
                    b = lerp(b, 255, alpha / 255)
                    break
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "banner.png")
    with open(out, "wb") as f:
        f.write(make_png())
    print("banner generated:", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
