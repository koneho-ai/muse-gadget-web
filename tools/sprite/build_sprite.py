#!/usr/bin/env python3
"""Hand-authored pixel-native Koneho sprite + animation frames.

The character is drawn from scratch in code (shapes + hand-placed feature
patches) at grid resolution -- NOT a downsampled photo. Every animation
frame is a full repaint of a fixed 48x58 grid of square pixels; only cell
colors change, the grid never moves.

Run:  python3 tools/sprite/build_sprite.py
Outputs: web/pixels.js, design/sprite-contact-sheet.png, design/koneho-anim.gif
"""
import json
import os
from PIL import Image

W, H = 48, 58          # grid
TOP = 4                # headroom rows above the character (for hop / Zzz)
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

# ---------------------------------------------------------------- character
def draw_tail(g):
    # curly tail: hand-written mini-map, right side of the body
    curl = [
        "..eee....",
        ".eLLLe...",
        "eLSSSe...",
        "eLS.ee...",
        ".eSLe....",
        "eLSe.....",
        "eLLe.....",
        ".ee......",
    ]
    ox, oy = 40, TOP + 11
    for j, row in enumerate(curl):
        for i, c in enumerate(row):
            if c != ".":
                px(g, ox + i, oy + j, c)

def draw_leg(g, top_x, bot_x, y0, tone_main, tone_side, paw_tone):
    """A 2px-wide leg from y0 to the feet, drifting top_x -> bot_x."""
    y1 = GROUND - 4
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, (y1 - y0))
        x = round(top_x + (bot_x - top_x) * t)
        px(g, x, y, tone_main)
        px(g, x + 1, y, tone_side)
    # paw: 6 wide, 4 tall, toe notches on the front rows
    cx = bot_x + 1
    paw = [
        ".FFFF.",
        "FFFFFF",
        "FFDFFD",
        "FFFFFF",
    ]
    for j, row in enumerate(paw):
        for i, c in enumerate(row):
            if c != ".":
                px(g, cx - 3 + i, GROUND - 3 + j, c if c != "F" else paw_tone)

def draw_ear(g, cx, droop=0):
    """Upright ear, rounded tip, orange inner. droop: tip rows lost."""
    profile = [3, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6]  # TOP .. TOP+14
    for j, wdt in enumerate(profile):
        if j < droop:
            continue
        y = TOP + j
        x0 = cx - wdt // 2
        for i in range(wdt):
            edge = i == 0 or i == wdt - 1
            px(g, x0 + i, y, "e" if edge else "F")
        # inner orange, inset by 1, from 2 rows below the tip
        if j >= 2:
            iw = wdt - 2
            ix0 = cx - iw // 2
            for i in range(iw):
                px(g, ix0 + i, y, "R" if j >= 12 else "r")

def body_fill(x, y, dx, dy, d2):
    if d2 < 0.30 and dx < -0.05 and dy < -0.05:
        c = "L"                       # round top-left sheen
    elif dy > 0.88:
        c = "D"                       # deepest bottom
    elif d2 > 0.62 and (dy > 0.55 or dx > 0.66):
        c = "S"                       # rim shade (follows the curve, no flat line)
    else:
        c = "F"
    return c

def draw_body(g):
    cx, cy, rx, ry = 23.5, TOP + 23, 17, 15
    ellipse(g, cx, cy, rx, ry, body_fill)
    # outline pass: filled pixel next to empty gets an edge tone
    snap = [row[:] for row in g]
    for y in range(H):
        for x in range(W):
            if snap[y][x] == ".":
                continue
            if TOP + 7 <= y <= TOP + 39 and 4 <= x <= 44:
                for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
                    if not is_filled(snap, nx, ny):
                        px(g, x, y, "o" if (ny > y or nx > x) else "e")
                        break

def draw_muzzle(g):
    cx, cy, rx, ry = 23.5, TOP + 28, 8, 7
    def fill(x, y, dx, dy, d2):
        if d2 > 0.82:
            return "F"
        if dy > 0.72:
            return "F"                # soft chin
        return "W"
    ellipse(g, cx, cy, rx, ry, fill)

EYE_L, EYE_R, EYE_Y = 19, 26, TOP + 22

def draw_eyes_open(g, dy=0, wide=False):
    # bead eyes: solid black with the sparkle at the top-inner corner
    for ex, inner_first in ((EYE_L, False), (EYE_R, True)):
        if wide:
            rows = [("k", "k"), ("k", "k"), ("k", "k")]
            spark = (0, 1 if inner_first else 0)
        else:
            rows = [("k", "k"), ("k", "k")]
            spark = (0, 1 if inner_first else 0)
        for j, row in enumerate(rows):
            for i, c in enumerate(row):
                px(g, ex + i, EYE_Y + dy + j - (1 if wide else 0), c)
        px(g, ex + spark[1], EYE_Y + dy + spark[0] - (1 if wide else 0), "W")

def draw_eyes_closed(g):
    for ex in (EYE_L, EYE_R):
        for i in range(2):
            px(g, ex + i, EYE_Y, "W" if False else "F")   # clear bead
            px(g, ex + i, EYE_Y + 1, "m")                  # lash line

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
                px(g, 21 + i, TOP + 25 + j, c)

def draw_smile(g):
    pts = [(18, 28), (27, 28), (19, 29), (26, 29),
           (20, 30), (25, 30), (21, 31), (22, 31), (23, 31), (24, 31)]
    for x, y in pts:
        px(g, x, TOP + y, "m")

def build_base():
    g = new_grid()
    draw_tail(g)
    # back + mid legs (behind body)
    draw_leg(g, 13, 9, TOP + 32, "S", "D", "S")
    draw_leg(g, 34, 38, TOP + 32, "S", "D", "S")
    draw_leg(g, 17, 14, TOP + 33, "F", "S", "F")
    draw_leg(g, 30, 33, TOP + 33, "F", "S", "F")
    draw_ear(g, 17)
    draw_ear(g, 30)
    draw_body(g)
    # front legs (emerge from under the body)
    draw_leg(g, 21, 20, TOP + 36, "F", "S", "F")
    draw_leg(g, 26, 27, TOP + 36, "F", "S", "F")
    draw_muzzle(g)
    draw_eyes_open(g)
    draw_nose(g)
    draw_smile(g)
    return g

# ---------------------------------------------------------------- variants
def clone(g):
    return [row[:] for row in g]

def clear_mouth(g):
    for y in range(TOP + 28, TOP + 32):
        for x in range(18, 29):
            if g[y][x] == "m":
                g[y][x] = "W"

def frame_blink(base):
    g = clone(base)
    # closed lashes over the muzzle
    for ex in (EYE_L, EYE_R):
        px(g, ex, EYE_Y, "W"); px(g, ex + 1, EYE_Y, "W")
        px(g, ex, EYE_Y + 1, "m"); px(g, ex + 1, EYE_Y + 1, "m")
    return g

def frame_talk(base, size):
    g = clone(base)
    clear_mouth(g)
    if size == 1:
        patch = [".MM.", "MMMM"]
        ox, oy = 22, TOP + 30
    else:
        patch = [".MMM.", "MMMMM", "MMpMM", ".MMM."]
        ox, oy = 21, TOP + 29
    for j, row in enumerate(patch):
        for i, c in enumerate(row):
            if c != ".":
                px(g, ox + i, oy + j, c)
    return g

def frame_think(base, dots):
    g = clone(base)
    # eyes look up
    for ex in (EYE_L, EYE_R):
        for j in range(2):
            for i in range(2):
                px(g, ex + i, EYE_Y + j, "W")
        px(g, ex, EYE_Y - 1, "k"); px(g, ex + 1, EYE_Y - 1, "k")
        px(g, ex, EYE_Y, "k"); px(g, ex + 1, EYE_Y, "W")
    # thought dots rising on the right
    spots = [(38, TOP + 2), (41, TOP - 1), (44, TOP - 3)]
    for i in range(dots):
        x, y = spots[i]
        r = i + 1
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    px(g, x + dx, y + dy, "S" if i < 2 else "F")
    return g

def frame_listen(base):
    g = clone(base)
    # perked ears: one extra tip row
    for cx in (17, 30):
        px(g, cx - 1, TOP - 1, "e"); px(g, cx, TOP - 1, "F"); px(g, cx + 1, TOP - 1, "e")
    draw_eyes_open(g, wide=True)
    return g

def frame_breathe(base):
    g = clone(base)
    # belly shading softens, chin shade warms: pure color change, no motion
    for y in range(TOP + 30, TOP + 39):
        for x in range(W):
            if g[y][x] == "D":
                g[y][x] = "S"
            elif g[y][x] == "R":
                g[y][x] = "r"
    return g

def squash(base, drop_rows, widen=True):
    """Compress toward the ground: remove body rows, feet stay planted."""
    g = clone(base)
    rows = sorted(drop_rows)
    out = [["."] * W for _ in range(len(rows))] + \
          [g[y] for y in range(H) if y not in rows]
    g = out[:H]
    if widen:
        for y in range(TOP + 14, TOP + 30):
            xs = [x for x in range(W) if g[y][x] != "."]
            if xs:
                if g[y][min(xs)] in "FSDeLo":
                    px(g, min(xs) - 1, y, "S")
                if g[y][max(xs)] in "FSDeLo":
                    px(g, max(xs) + 1, y, "S")
    return g

def shift_up(base, n, ear_droop=0, point_feet=False):
    g = [["."] * W for _ in range(n)] + [row[:] for row in base[:H - n]] \
        if n <= 0 else [row[:] for row in base[n:]] + [["."] * W for _ in range(n)]
    # NOTE: shifting the raster up = re-anchoring; feet leave the ground.
    g = [row[:] for row in base[n:]] + [["."] * W for _ in range(n)]
    if ear_droop:
        # redraw ears drooped: tips fold down by repainting tip rows as fur
        for cx in (17, 30):
            for j in range(ear_droop):
                y = TOP - n + j
                for x in range(cx - 2, cx + 3):
                    if 0 <= y < H and g[y][x] in "FErR":
                        g[y][x] = "F" if j else "."
    if point_feet:
        # toes point down: trim paw sides on the lowest rows
        for y in (GROUND - n - 1, GROUND - n):
            for x in range(W):
                pass
    return g

def frame_sleep(base, stage):
    g = clone(base)
    for ex in (EYE_L, EYE_R):
        px(g, ex, EYE_Y, "W"); px(g, ex + 1, EYE_Y, "W")
        px(g, ex, EYE_Y + 1, "m"); px(g, ex + 1, EYE_Y + 1, "m")
    clear_mouth(g)
    px(g, 23, TOP + 30, "M"); px(g, 24, TOP + 30, "M")
    px(g, 23, TOP + 31, "M"); px(g, 24, TOP + 31, "M")
    # Z letter, growing + rising per stage
    zmap = {0: (["zz.", ".z.", ".zz"], 37, TOP + 6),
            1: (["zzzz", "..z.", ".z..", "zzzz"], 39, TOP + 3),
            2: (["zzzzz", "...z.", "..z..", ".z...", "zzzzz"], 41, TOP - 1)}
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
        "squash": squash(base, [TOP + 19, TOP + 28]),
        "squash_deep": squash(base, [TOP + 17, TOP + 24, TOP + 30]),
        "air": shift_up(base, 4, ear_droop=2),
        "fall": shift_up(base, 2, ear_droop=0),
        "sleep0": frame_sleep(base, 0),
        "sleep1": frame_sleep(base, 1),
        "sleep2": frame_sleep(base, 2),
    }
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))

    # contact sheet
    names = list(frames)
    cols = 4
    rows_n = (len(names) + cols - 1) // cols
    cell_w, cell_h = W * 6 + 12, H * 6 + 12
    sheet = Image.new("RGB", (cols * cell_w, rows_n * cell_h), (24, 30, 38))
    for i, name in enumerate(names):
        im = render(frames[name], 6)
        sheet.paste(im, ((i % cols) * cell_w + 6, (i // cols) * cell_h + 6))
    sheet.save(os.path.join(root, "design", "sprite-contact-sheet.png"))

    # animated GIF: idle (breathe+blink) -> talk -> think -> hop -> sleep
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

    # pixels.js for the web player
    palette_js = [PALETTE[c] for c in
                  [".", "o", "e", "L", "F", "S", "D", "W", "r", "R", "p", "P", "k", "m", "M", "z"]]
    order = [".", "o", "e", "L", "F", "S", "D", "W", "r", "R", "p", "P", "k", "m", "M", "z"]
    idx_of = {c: i for i, c in enumerate(order)}
    frames_js = {}
    for name, g in frames.items():
        frames_js[name] = ["".join(str(idx_of[c]) if idx_of[c] < 10 else chr(87 + idx_of[c]) for c in row) for row in g]
    js = ("// Generated by tools/sprite/build_sprite.py -- hand-authored pixel Koneho.\n"
          "// Fixed grid; animation = repainting cell colors per frame. Do not edit by hand.\n"
          "window.PIXEL_SPRITE = " + json.dumps(
              {"width": W, "height": H, "palette": palette_js, "frames": frames_js}) + ";\n")
    with open(os.path.join(root, "web", "pixels.js"), "w") as f:
        f.write(js)
    print("frames:", len(frames), "| palette:", len(palette_js), "| sheet + gif + pixels.js written")

if __name__ == "__main__":
    main()
