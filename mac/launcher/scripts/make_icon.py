#!/usr/bin/env python3
# Regenerate the placeholder icon: python3 scripts/make_icon.py src-tauri/icons/app-icon.png
# then: npx tauri icon src-tauri/icons/app-icon.png
# An original placeholder, with no game art and nothing from the game's logo or
# lettering: a small pale flame (a soul, drawn as a plain teardrop with a brighter
# core and a soft glow) inside a thin warm ring, on a near-black rounded square.
# Standard library only.
import math, struct, sys, zlib

N = 1024
C = N / 2


def rr(px, py, r=200, m=40):
    x0, y0, x1, y1 = m, m, N - m, N - m
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r and x0 <= px <= x1 and y0 <= py <= y1


def drop(px, py, cx, cy, r, h):
    """A teardrop: a circle of radius r at (cx, cy) whose top is drawn up to a point h above it.
    Returns a signed distance-like value (< 0 inside)."""
    dx, dy = px - cx, py - cy
    if dy >= 0:
        return math.hypot(dx, dy) - r
    # above the centre: the width narrows from r to 0 over the height h (a curved taper)
    t = min(1.0, -dy / h)
    w = r * (1 - t) ** 1.6 * math.sqrt(1 - (t * 0.35) ** 2)
    return abs(dx) - w if -dy <= h else math.hypot(dx, -dy - h)


S = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
rows = []
for y in range(N):
    row = bytearray([0])
    for x in range(N):
        a = 0
        col = [0.0, 0.0, 0.0]
        for sx, sy in S:
            px, py = x + sx, y + sy
            if not rr(px, py):
                continue
            a += 1
            d = math.hypot(px - C, py - C)
            t = y / N
            # near-black, a little warmer towards the middle
            v = max(0.0, 1 - d / 620)
            c = [14 + 16 * v - 4 * t, 13 + 11 * v - 4 * t, 12 + 6 * v - 4 * t]
            # the ring
            ring = abs(d - 360)
            if ring < 9:
                k = 1 - ring / 9
                c = [c[0] + (196 - c[0]) * k, c[1] + (160 - c[1]) * k, c[2] + (98 - c[2]) * k]
            # the flame: glow, body, core
            f = drop(px, py, C, C + 90, 120, 300)
            if f < 90:
                g = max(0.0, 1 - max(f, 0) / 90) ** 2 * 0.45
                c = [c[0] + (230 - c[0]) * g, c[1] + (196 - c[1]) * g, c[2] + (140 - c[2]) * g]
            if f < 0:
                k = min(1.0, -f / 6)
                c = [c[0] + (232 - c[0]) * k, c[1] + (214 - c[1]) * k, c[2] + (178 - c[2]) * k]
            fc = drop(px, py, C, C + 120, 52, 120)
            if fc < 0:
                k = min(1.0, -fc / 6)
                c = [c[0] + (255 - c[0]) * k, c[1] + (250 - c[1]) * k, c[2] + (236 - c[2]) * k]
            for i in range(3):
                col[i] += c[i]
        if a == 0:
            row += b"\0\0\0\0"
            continue
        row += bytes([min(255, int(col[0] / a)), min(255, int(col[1] / a)), min(255, int(col[2] / a)), int(255 * a / 4)])
    rows.append(bytes(row))


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(png)
