#!/usr/bin/env python3
"""Hand-authored pixel-native Koneho sprite + animation frames.

Drawn from scratch in code at grid resolution -- NOT a downsampled photo.
Proportions measured from the character reference: a near-perfect round
ball body (38% of height), long slim ears above it (18%), a lighter oval
muzzle plate centred on the ball, six very long thin legs (44%), curly
tail on the right.

Every animation frame is a full repaint of a fixed 48x58 grid of square
pixels; only cell colors change, the grid never moves.

Run:  python3 tools/sprite/build_sprite.py
Outputs: web/pixels.js, design/sprite-contact-sheet.png, design/koneho-anim.gif
"""
import json
import os
from PIL import Image

W, H = 48, 58          # grid
TOP = 4                # headroom rows above the character (hop / Zzz)
GROUND = H - 1         # feet bottom row

PALETTE = {
    ".": None,                 # transparent
    "o": "#57504a",            # outline (bottom/right)
    "e": "#8d857a",            # edge (top/left, softer)
    "L": "#f4f1ec",            # fur light
    "F": "#e4dfd7",            # fur main
    "S": "#c9c2b8",            # fur shade
    "D": "#a79e90",            # fur deep
    "W": "#fdfbf7",            # muzzle white
    "r": "#f26d21",            # ear orange
    "R": "#cf4e12",            # ear orange deep
    "p": "#f6aebe",            # nose pink
    "P": "#e5839a",            # nose deep pink
    "k": "#2a2521",            # bead eye black
    "m": "#7a7268",            # stitch
    "M": "#4a4038",            # mouth dark
    "z": "#93a7bd",            # sleep Z blue-grey
}
ORDER = [".", "o", "e", "L", "F", "S", "D", "W", "r", "R", "p", "P", "k", "m", "M", "z"]

# anatomy (character rows; add TOP for absolute grid rows)
BODY_CX, BODY_CY, BODY_R = 23.5, 21, 11.5      # the round ball
EAR_L, EAR_R = 19, 28
EYE_L, EYE_R, EYE_Y = 20, 26, 19

def new_grid():
    return [["."] * W for _ in range(H)]

def px(g, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        g[y][x] = c

def ellipse(g, cx, cy, rx, ry, fill_fn):
    for y in range(H):
        for x in range(W):
            dx, dy = (x - cx) / rx, (y - cy) / ry
            d2 = dx * dx + dy * dy
            if d2 <= 1.0:
                px(g, x, y, fill_fn(x, y, dx, dy, d2))

def is_filled(g, x, y):
    return 0 <= x < W and 0 <= y < H and g[y][x] != "."

def clone(g):
    return [row[:] for row in g]

# ---------------------------------------------------------------- character
def draw_tail(g):
    # tight curly pompom hugging the ball's right side
    curl = [
        ".eee...",
        "eFLFLe.",
        "eLFLFLe",
        "eFLFLLe",
        "eLFLLe.",
        ".eLLe..",
        "..ee...",
    ]
    ox, oy = 33, TOP + 15
    for j, row in enumerate(curl):
        for i, c in enumerate(row):
            if c != ".":
                px(g, ox + i, oy + j, c)

def draw_leg(g, top_x, bot_x, y0, tone_main, tone_side, paw_tone):
    y1 = GROUND - 4
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, (y1 - y0))
        x = round(top_x + (bot_x - top_x) * t)
        px(g, x, y, tone_main)
        px(g, x + 1, y, tone_side)
    cx = bot_x + 1
    paw = [
        ".FFF..",
        "FFFFF.",
        "FFDFD.",
        "FFFFF.",
    ]
    for j, row in enumerate(paw):
        for i, c in enumerate(row):
            if c != ".":
                px(g, cx - 2 + i, GROUND - 3 + j, c if c != "F" else paw_tone)

def draw_ear(g, cx):
    """Long slim ear, rounded tip, slim orange teardrop inner."""
    profile = [2, 3, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]   # TOP..TOP+15
    for j, wdt in enumerate(profile):
        y = TOP + j
        x0 = cx - wdt // 2
        for i in range(wdt):
            edge = i == 0 or i == wdt - 1
            px(g, x0 + i, y, "e" if edge else "F")
        if j >= 3:  # inner teardrop, inset 1, fur margin at the tip
            iw = wdt - 2
            ix0 = cx - iw // 2
            for i in range(iw):
                px(g, ix0 + i, y, "R" if j >= 13 else "r")

def body_fill(x, y, dx, dy, d2):
    if d2 < 0.30 and dx < -0.05 and dy < -0.05:
        return "L"                    # round top-left sheen
    if dy > 0.88:
        return "D"                    # deepest bottom
    if d2 > 0.62 and (dy > 0.55 or dx > 0.66):
        return "S"                    # rim shade, follows the curve
    return "F"

def draw_body(g):
    ellipse(g, BODY_CX, TOP + BODY_CY, BODY_R, BODY_R, body_fill)
    snap = [row[:] for row in g]
    for y in range(H):
        for x in range(W):
            if snap[y][x] == ".":
                continue
            if TOP + 8 <= y <= TOP + 34 and 10 <= x <= 38:
                for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
                    if not is_filled(snap, nx, ny):
                        px(g, x, y, "o" if (ny > y or nx > x) else "e")
                        break

def draw_muzzle(g):
    def fill(x, y, dx, dy, d2):
        if d2 > 0.82:
            return "F"
        if dy > 0.72:
            return "F"                # soft chin
        return "W"
    ellipse(g, BODY_CX, TOP + BODY_CY, 5.5, 6.5, fill)

def draw_eyes_open(g, dy=0, wide=False):
    for ex, inner_first in ((EYE_L, False), (EYE_R, True)):
        rows = 3 if wide else 2
        for j in range(rows):
            for i in range(2):
                px(g, ex + i, TOP + EYE_Y + dy + j - (1 if wide else 0), "k")
        sx = ex + (1 if inner_first else 0)
        px(g, sx, TOP + EYE_Y + dy - (1 if wide else 0), "W")

def draw_eyes_closed(g):
    for ex in (EYE_L, EYE_R):
        px(g, ex, TOP + EYE_Y, "W"); px(g, ex + 1, TOP + EYE_Y, "W")
        px(g, ex, TOP + EYE_Y + 1, "m"); px(g, ex + 1, TOP + EYE_Y + 1, "m")

def draw_nose(g):
    heart = [
        "pp.pp",
        "pPppp",
        ".ppp.",
        "..p..",
    ]
    for j, row in enumerate(heart):
        for i, c in enumerate(row):
            if c != ".":
                px(g, 21 + i, TOP + 22 + j, c)

def draw_smile(g):
    pts = [(20, 25), (27, 25), (21, 26), (26, 26),
           (22, 27), (23, 27), (24, 27), (25, 27)]
    for x, y in pts:
        px(g, x, TOP + y, "m")

def build_base():
    g = new_grid()
    draw_tail(g)
    draw_leg(g, 15, 7, TOP + 27, "S", "D", "S")    # back pair
    draw_leg(g, 32, 39, TOP + 27, "S", "D", "S")
    draw_leg(g, 19, 13, TOP + 28, "F", "S", "F")   # mid pair
    draw_leg(g, 28, 33, TOP + 28, "F", "S", "F")
    draw_ear(g, EAR_L)
    draw_ear(g, EAR_R)
    draw_body(g)
    draw_leg(g, 22, 19, TOP + 30, "F", "S", "F")   # front pair
    draw_leg(g, 25, 26, TOP + 30, "F", "S", "F")
    draw_muzzle(g)
    draw_eyes_open(g)
    draw_nose(g)
    draw_smile(g)
    return g

# ---------------------------------------------------------------- variants
def clear_mouth(g):
    for y in range(TOP + 25, TOP + 29):
        for x in range(19, 29):
            if g[y][x] == "m":
                g[y][x] = "W"

def frame_blink(base):
    g = clone(base)
    draw_eyes_closed(g)
    return g

def frame_talk(base, size):
    g = clone(base)
    clear_mouth(g)
    if size == 1:
        patch = [".MM.", "MMMM"]
        ox, oy = 22, TOP + 27
    else:
        patch = [".MMM.", "MMMMM", ".MpM."]
        ox, oy = 21, TOP + 26
    for j, row in enumerate(patch):
        for i, c in enumerate(row):
            if c != ".":
                px(g, ox + i, oy + j, c)
    return g

def frame_think(base, dots):
    g = clone(base)
    for ex in (EYE_L, EYE_R):  # eyes look up
        for j in range(2):
            for i in range(2):
                px(g, ex + i, TOP + EYE_Y + j, "W")
        px(g, ex, TOP + EYE_Y - 1, "k"); px(g, ex + 1, TOP + EYE_Y - 1, "k")
        px(g, ex, TOP + EYE_Y, "k"); px(g, ex + 1, TOP + EYE_Y, "W")
    spots = [(34, TOP + 3), (37, TOP + 1), (40, TOP - 1)]
    for i in range(dots):
        x, y = spots[i]
        r = 1 if i < 2 else 2
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    px(g, x + dx, y + dy, "S" if i < 2 else "F")
    return g

def frame_listen(base):
    g = clone(base)
    for cx in (EAR_L, EAR_R):  # one extra perked tip row
        px(g, cx - 1, TOP - 1, "e"); px(g, cx, TOP - 1, "F"); px(g, cx + 1, TOP - 1, "e")
    draw_eyes_open(g, wide=True)
    return g

def frame_breathe(base):
    g = clone(base)
    for y in range(TOP + 26, TOP + 34):
        for x in range(W):
            if g[y][x] == "D":
                g[y][x] = "S"
            elif g[y][x] == "R":
                g[y][x] = "r"
    return g

def squash(base, drop_rows, widen=True):
    rows = sorted(drop_rows)
    g = [["."] * W for _ in range(len(rows))] + \
        [base[y] for y in range(H) if y not in rows]
    g = [row[:] for row in g[:H]]
    if widen:
        for y in range(TOP + 13, TOP + 28):
            xs = [x for x in range(W) if g[y][x] != "."]
            if xs:
                if g[y][min(xs)] in "FSDeLo":
                    px(g, min(xs) - 1, y, "S")
                if g[y][max(xs)] in "FSDeLo":
                    px(g, max(xs) + 1, y, "S")
    return g

def shift_up(base, n, ear_droop=0):
    g = [row[:] for row in base[n:]] + [["."] * W for _ in range(n)]
    if ear_droop:
        for cx in (EAR_L, EAR_R):
            for j in range(ear_droop):
                y = TOP - n + j
                for x in range(cx - 2, cx + 3):
                    if 0 <= y < H and g[y][x] in "FErR":
                        g[y][x] = "F" if j else "."
    return g

def frame_sleep(base, stage):
    g = clone(base)
    draw_eyes_closed(g)
    clear_mouth(g)
    px(g, 23, TOP + 27, "M"); px(g, 24, TOP + 27, "M")
    px(g, 23, TOP + 28, "M"); px(g, 24, TOP + 28, "M")
    zmap = {0: (["zz.", ".z.", ".zz"], 33, TOP + 5),
            1: (["zzzz", "..z.", ".z..", "zzzz"], 35, TOP + 2),
            2: (["zzzzz", "...z.", "..z..", ".z...", "zzzzz"], 37, TOP - 1)}
    rows, ox, oy = zmap[stage]
    for j, row in enumerate(rows):
        for i, c in enumerate(row):
            if c == "z":
                px(g, ox + i, oy + j, "z")
    return g

# ---------------------------------------------------------------- outputs
def render(g, scale=9):
    img = Image.new("RGB", (W * scale, H * scale), (13, 18, 24))
    ip = img.load()
    for y in range(H):
        for x in range(W):
            c = PALETTE[g[y][x]]
            if c:
                rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
                for dy in range(scale):
                    for dx in range(scale):
                        ip[x * scale + dx, y * scale + dy] = rgb
    return img

def main():
    base = build_base()
    frames = {
        "base": base,
        "breathe": frame_breathe(base),
        "blink": frame_blink(base),
        "talk1": frame_talk(base, 1),
        "talk2": frame_talk(base, 2),
        "think1": frame_think(base, 1),
        "think2": frame_think(base, 2),
        "think3": frame_think(base, 3),
        "listen": frame_listen(base),
        "squash": squash(base, [TOP + 16, TOP + 24]),
        "squash_deep": squash(base, [TOP + 14, TOP + 20, TOP + 26]),
        "air": shift_up(base, 4, ear_droop=2),
        "fall": shift_up(base, 2, ear_droop=0),
        "sleep0": frame_sleep(base, 0),
        "sleep1": frame_sleep(base, 1),
        "sleep2": frame_sleep(base, 2),
    }
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))

    names = list(frames)
    cols = 4
    rows_n = (len(names) + cols - 1) // cols
    cell_w, cell_h = W * 6 + 12, H * 6 + 12
    sheet = Image.new("RGB", (cols * cell_w, rows_n * cell_h), (24, 30, 38))
    for i, name in enumerate(names):
        im = render(frames[name], 6)
        sheet.paste(im, ((i % cols) * cell_w + 6, (i // cols) * cell_h + 6))
    sheet.save(os.path.join(root, "design", "sprite-contact-sheet.png"))

    seq = []
    def add(name, ms):
        seq.append((render(frames[name], 7), ms))
    for i in range(2):
        add("base", 1300); add("breathe", 1300)
    add("blink", 130); add("base", 900)
    for i in range(3):
        add("talk1", 110); add("talk2", 110); add("talk1", 110); add("base", 160)
    add("think1", 350); add("think2", 350); add("think3", 600); add("base", 500)
    add("listen", 700); add("base", 300)
    add("squash", 120); add("air", 110); add("fall", 90); add("squash_deep", 110); add("base", 600)
    add("sleep0", 500); add("sleep1", 500); add("sleep2", 700); add("sleep0", 500)
    imgs = [s[0] for s in seq]
    imgs[0].save(os.path.join(root, "design", "koneho-anim.gif"), save_all=True,
                 append_images=imgs[1:], duration=[s[1] for s in seq], loop=0)

    palette_js = [PALETTE[c] for c in ORDER]
    idx_of = {c: i for i, c in enumerate(ORDER)}
    frames_js = {}
    for name, g in frames.items():
        frames_js[name] = ["".join(str(idx_of[c]) if idx_of[c] < 10 else chr(87 + idx_of[c]) for c in row) for row in g]
    js = ("// Generated by tools/sprite/build_sprite.py -- hand-authored pixel Koneho.\n"
          "// Fixed grid; animation = repainting cell colors per frame. Do not edit by hand.\n"
          "window.PIXEL_SPRITE = " + json.dumps(
              {"width": W, "height": H, "palette": palette_js, "frames": frames_js}) + ";\n")
    with open(os.path.join(root, "web", "pixels.js"), "w") as f:
        f.write(js)
    print("frames:", len(frames), "| sheet + gif + pixels.js written")

if __name__ == "__main__":
    main()
