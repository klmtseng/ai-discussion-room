#!/usr/bin/env python3
"""
sprite_forge.py — Parametric pixel-art character sprite generator  v2.0.0
Outputs: static/assets/sprites/<id>.png  (16×16 × 4 frames, horizontal strip)
         static/assets/sprites/manifest.json

License: CC0 1.0 Universal — Public Domain

v2 art improvements
-------------------
1. Head de-blocked: rounded corners (4 corner pixels cut), 1px margin each side,
   body narrower (5-10) vs head (4-11) → chibi head-big-body-small rhythm.
2. Warm dark-brown outline (#2a1a10); hair-face border uses darkened hair colour.
3. Hair hairstyles: bangs reach forehead row 3; mohawk 3px tall ×2px wide;
   bun has distinct circle; long drapes to shoulder row.
4. Face: eyes at (6,5)+(9,5) same row, 2px gap; mouth 1px mid-colour dot;
   glasses = 1px dark frame + skin-colour fill (not solid grey).
5. Outfit two-tone: main + shadow shade on lower/sides; collar accent dot.
6. Walk bob: phases 1 & 3 body shifted up 1px; leg swing ≥2px Y delta.
7. Accessories repositioned to new head shape.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# ─── try Pillow first ──────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

VERSION = "2.0.0"
FRAME_W = 16
FRAME_H = 16
FRAMES  = 4   # idle + 3 walk (facing down)

# ─── Colour palettes ──────────────────────────────────────────────────────────
SKIN_TONES = {
    "light":  (255, 218, 185),
    "tan":    (205, 160, 112),
    "brown":  (160, 110,  70),
    "olive":  (175, 150, 100),
    "dark":   (110,  70,  40),
    "deep":   ( 75,  45,  25),
}

HAIR_COLORS = {
    "black":    ( 30,  20,  15),
    "brown":    (100,  60,  30),
    "blonde":   (220, 185,  80),
    "red":      (180,  60,  30),
    "grey":     (150, 150, 150),
    "white":    (240, 235, 225),
    "blue":     ( 50,  80, 200),
    "purple":   (140,  60, 190),
}

# v2: warm dark-brown outline instead of pure black
OUTLINE_COLOR = (42, 26, 16, 255)   # #2a1a10


# ─── Helpers ──────────────────────────────────────────────────────────────────

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c*2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgba(r, g, b, a=255):
    return (r, g, b, a)


def darken(rgb: tuple, amount: int = 40) -> tuple[int, int, int, int]:
    return tuple(max(0, v - amount) for v in rgb) + (255,)


def lighten(rgb: tuple, amount: int = 40) -> tuple[int, int, int, int]:
    return tuple(min(255, v + amount) for v in rgb) + (255,)


# ─── Frame painter (Pillow) ───────────────────────────────────────────────────

class FramePainter:
    """Draws a single 16×16 character frame using Pillow (v2 art quality)."""

    # Head occupies cols 4-11, rows 2-9  (8×8 block before rounding)
    # Body occupies cols 5-10, rows 9-12 (narrower = chibi rhythm)
    HEAD_L, HEAD_R = 4, 11   # inclusive
    HEAD_T, HEAD_B = 2, 9    # inclusive
    BODY_L, BODY_R = 5, 10   # 1px narrower each side vs head

    def __init__(self, skin: str, hair_style: str, hair_color: str,
                 outfit: str, accent: tuple[int,int,int],
                 accessory: str | None, walk_phase: int):
        self.skin_rgb   = SKIN_TONES.get(skin, SKIN_TONES["tan"])
        self.hair_rgb   = HAIR_COLORS.get(hair_color, HAIR_COLORS["brown"])
        self.outfit     = outfit
        self.accent_rgb = accent
        self.accessory  = accessory
        self.walk_phase = walk_phase  # 0=idle 1=step-L 2=mid 3=step-R
        self.hair_style = hair_style
        # Bob: frames 1 & 3 shift upper body UP 1px (y−1 in pixel coords)
        self.bob = -1 if walk_phase in (1, 3) else 0

    def render(self) -> "Image.Image":
        img = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        self._draw_outline(d)
        self._draw_body(d)
        self._draw_legs(d)
        self._draw_head(d)
        self._draw_hair(d)
        self._draw_face(d)
        self._draw_accessory(d, img)
        self._enforce_rounded_corners(img)
        return img

    def _enforce_rounded_corners(self, img: "Image.Image"):
        """Post-process: force the 4 head corner pixels to be transparent."""
        b  = self.bob
        corners = [
            (self.HEAD_L, self.HEAD_T + b),
            (self.HEAD_R, self.HEAD_T + b),
            (self.HEAD_L, self.HEAD_B + b),
            (self.HEAD_R, self.HEAD_B + b),
        ]
        for px in corners:
            x, y = px
            if 0 <= x < FRAME_W and 0 <= y < FRAME_H:
                img.putpixel((x, y), (0, 0, 0, 0))

    # ── v2: outline using warm brown, expanded silhouette only on exterior ──
    def _draw_outline(self, d):
        c = OUTLINE_COLOR
        b = self.bob
        # Head outline (rounded corner version: rectangle then clear corners)
        d.rectangle([self.HEAD_L-1, self.HEAD_T-1+b, self.HEAD_R+1, self.HEAD_B+b], fill=c)
        # Clear the four corner pixels of the outline to round it
        corners_out = [
            (self.HEAD_L-1, self.HEAD_T-1+b),
            (self.HEAD_R+1, self.HEAD_T-1+b),
            (self.HEAD_L-1, self.HEAD_B+b),
            (self.HEAD_R+1, self.HEAD_B+b),
        ]
        for px in corners_out:
            if 0 <= px[0] < FRAME_W and 0 <= px[1] < FRAME_H:
                d.point([px], fill=(0, 0, 0, 0))
        # Body outline (narrower than head)
        d.rectangle([self.BODY_L-1, self.HEAD_B+b, self.BODY_R+1, 13], fill=c)

    def _draw_body(self, d):
        b = self.bob
        oc   = rgba(*self.accent_rgb)
        dark = darken(self.accent_rgb, 50)
        lit  = lighten(self.accent_rgb, 30)

        # Two-tone torso: top/sides darker, main lighter
        body_t = self.HEAD_B + b   # row 9 (or 8 with bob)
        body_b = 12 + b            # row 12 (or 11 with bob) — clamp at 13
        body_b = min(body_b, 13)

        # Main body fill
        d.rectangle([self.BODY_L, body_t, self.BODY_R, body_b], fill=oc)
        # Shadow: bottom row + right column darker
        d.rectangle([self.BODY_L, body_b, self.BODY_R, body_b], fill=dark)
        d.rectangle([self.BODY_R, body_t, self.BODY_R, body_b], fill=dark)

        # Collar: 1px contrast dot at neck centre
        collar = lighten(self.accent_rgb, 70)
        d.point([(7+b, body_t), (8+b, body_t)], fill=collar)

        # Outfit-specific details
        if self.outfit == "robe":
            d.rectangle([self.BODY_L-1, body_t, self.BODY_R+1, body_b], fill=oc)
            d.rectangle([self.BODY_L-1, body_b, self.BODY_R+1, body_b], fill=dark)
            d.line([(self.BODY_L-1, body_b), (self.BODY_R+1, body_b)], fill=lit, width=1)
        elif self.outfit == "suit":
            lapel = (50, 50, 60, 255)
            d.rectangle([7, body_t, 8, body_b], fill=(230, 225, 215, 255))
            d.rectangle([self.BODY_L, body_t, 6, body_b], fill=oc)
            d.rectangle([9, body_t, self.BODY_R, body_b], fill=oc)
            d.line([(7, body_t), (7, body_b)], fill=lapel, width=1)
        elif self.outfit == "hoodie":
            d.rectangle([self.BODY_L, body_t, self.BODY_R, body_b], fill=oc)
            pock = darken(self.accent_rgb, 30)
            pock_t = min(body_t + 2, body_b)
            d.rectangle([6, pock_t, 9, body_b], fill=pock)

        # Arms (skin) — follow bob
        sk = rgba(*self.skin_rgb)
        arm_t = body_t + 1
        arm_b = min(body_t + 3, 13)
        d.rectangle([self.BODY_L-1, arm_t, self.BODY_L-1, arm_b], fill=sk)
        d.rectangle([self.BODY_R+1, arm_t, self.BODY_R+1, arm_b], fill=sk)

    def _draw_legs(self, d):
        pant = darken(self.accent_rgb, 60)
        shoe = (50, 40, 35, 255)
        wp   = self.walk_phase
        # Legs do NOT follow bob — they stay fixed to ground
        thigh_y = 13

        # Stride: each leg alternates ±1 row for foot position (total 2px delta = visible)
        ll_y = thigh_y   # left leg foot base
        rl_y = thigh_y   # right leg foot base
        if wp == 1:       # step-left: left foot raised (−1), right extended (+1)
            ll_y = thigh_y - 1
            rl_y = thigh_y + 1
        elif wp == 3:     # step-right: right foot raised, left extended
            ll_y = thigh_y + 1
            rl_y = thigh_y - 1
        # wp==0 (idle) and wp==2 (mid) keep both at thigh_y

        # Clamp to frame bounds
        ll_y = max(thigh_y - 1, min(ll_y, 15))
        rl_y = max(thigh_y - 1, min(rl_y, 15))

        # Thigh (always at row 13)
        d.rectangle([5, thigh_y, 6, thigh_y], fill=pant)
        d.rectangle([8, thigh_y, 9, thigh_y], fill=pant)
        # Shin/calf
        if ll_y > thigh_y:
            d.rectangle([5, thigh_y + 1, 6, ll_y], fill=pant)
        if rl_y > thigh_y:
            d.rectangle([8, thigh_y + 1, 9, rl_y], fill=pant)
        # Shoes — clamped to frame bottom
        shoe_ll = min(ll_y + 1, 15)
        shoe_rl = min(rl_y + 1, 15)
        d.rectangle([5, shoe_ll, 6, shoe_ll], fill=shoe)
        d.rectangle([8, shoe_rl, 9, shoe_rl], fill=shoe)

    def _draw_head(self, d):
        sk = rgba(*self.skin_rgb)
        b  = self.bob
        # Draw filled head rect
        d.rectangle([self.HEAD_L, self.HEAD_T+b, self.HEAD_R, self.HEAD_B+b], fill=sk)
        # v2: cut the 4 corner pixels → rounded silhouette
        corners = [
            (self.HEAD_L, self.HEAD_T+b),
            (self.HEAD_R, self.HEAD_T+b),
            (self.HEAD_L, self.HEAD_B+b),
            (self.HEAD_R, self.HEAD_B+b),
        ]
        for px in corners:
            if 0 <= px[0] < FRAME_W and 0 <= px[1] < FRAME_H:
                d.point([px], fill=(0, 0, 0, 0))

    def _draw_hair(self, d):
        hc      = rgba(*self.hair_rgb)
        hc_dark = darken(self.hair_rgb, 35)   # hair-face border shade
        hs      = self.hair_style
        b       = self.bob

        # Head geometry (with bob offset)
        ht = self.HEAD_T + b   # top of head
        hb = self.HEAD_B + b   # bottom of head

        if hs == "short":
            # Top 2 rows of head (rows ht, ht+1) = fringe reaching row ht+1
            d.rectangle([self.HEAD_L, ht, self.HEAD_R, ht+1], fill=hc)
            # Hair-skin boundary: row ht+2 sidecols use dark hair shade
            d.point([(self.HEAD_L, ht+2), (self.HEAD_R, ht+2)], fill=hc_dark)
            # Sideburn dots at ear rows
            d.point([(self.HEAD_L, ht+3), (self.HEAD_R, ht+3)], fill=hc_dark)

        elif hs == "long":
            # Top 2 rows + side curtains reaching shoulder
            d.rectangle([self.HEAD_L, ht, self.HEAD_R, ht+1], fill=hc)
            # Bangs: row ht+2 fully to show fringe over forehead
            d.rectangle([self.HEAD_L+1, ht+2, self.HEAD_R-1, ht+2], fill=hc)
            d.point([(self.HEAD_L, ht+2), (self.HEAD_R, ht+2)], fill=hc_dark)
            # Side drapes: 2px wide, reaching row hb+1 (shoulder)
            d.rectangle([self.HEAD_L-1, ht+1, self.HEAD_L, hb+1], fill=hc)
            d.rectangle([self.HEAD_R, ht+1, self.HEAD_R+1, hb+1], fill=hc)

        elif hs == "curly":
            # Bumpy top — top row + bumps at ht-1
            d.rectangle([self.HEAD_L, ht, self.HEAD_R, ht+1], fill=hc)
            for cx in [4, 6, 8, 10]:
                if 0 <= ht-1 < FRAME_H:
                    d.rectangle([cx, ht-1, cx+1, ht], fill=hc)
            d.point([(self.HEAD_L, ht+2), (self.HEAD_R, ht+2)], fill=hc_dark)

        elif hs == "bald":
            # Subtle highlight — no drawn hair
            pass

        elif hs == "bun":
            # Short back-sides + distinct circle bun on top
            d.rectangle([self.HEAD_L+1, ht+1, self.HEAD_R-1, ht+1], fill=hc)
            # Bun: 3×2 solid rectangle sitting above head top
            bun_row = max(ht - 2, 0)
            d.rectangle([6, bun_row, 9, ht], fill=hc)
            d.point([(self.HEAD_L, ht+2), (self.HEAD_R, ht+2)], fill=hc_dark)

        elif hs == "mohawk":
            # v2: centre strip 2px wide, 3px tall above head top
            for row in range(max(ht-3, 0), ht+1):
                d.rectangle([7, row, 8, row], fill=hc)
            d.point([(self.HEAD_L, ht+1), (self.HEAD_R, ht+1)], fill=hc_dark)

        else:
            # fallback = short
            d.rectangle([self.HEAD_L, ht, self.HEAD_R, ht+1], fill=hc)
            d.point([(self.HEAD_L, ht+2), (self.HEAD_R, ht+2)], fill=hc_dark)

    def _draw_face(self, d):
        b    = self.bob
        ht   = self.HEAD_T + b   # top of head row

        # Eyes: 1px dark dots at same row (row ht+3), cols 6 & 9, separated by 2px
        eye_row = ht + 3
        eye_col = (30, 25, 20, 255)
        d.point([(6, eye_row), (9, eye_row)], fill=eye_col)
        # Subtle highlight pixel above each eye
        if eye_row - 1 >= 0:
            d.point([(6, eye_row-1), (9, eye_row-1)], fill=(255, 255, 255, 100))

        # Mouth: 1px, lighter tone (not black) at row ht+5
        mouth_row = ht + 5
        sk  = self.skin_rgb
        # mid-tone between skin and a warm brown — visually subtle
        mouth_col = (
            max(0, sk[0] - 30),
            max(0, sk[1] - 40),
            max(0, sk[2] - 30),
            200,
        )
        if 0 <= mouth_row < FRAME_H:
            d.point([(7, mouth_row), (8, mouth_row)], fill=mouth_col)

    def _draw_accessory(self, d, img):
        if not self.accessory or self.accessory == "none":
            return
        a  = self.accessory
        b  = self.bob
        ht = self.HEAD_T + b
        hb = self.HEAD_B + b

        if a == "glasses":
            # v2: 1px dark frame around eye positions, skin-coloured fill
            gc = (60, 40, 20, 230)    # warm dark frame
            sk = rgba(*self.skin_rgb)
            eye_row = ht + 3
            # Left lens frame
            d.rectangle([5, eye_row-1, 7, eye_row+1], outline=gc)
            # Left lens fill (skin inside — eye will be overdrawn on top)
            d.rectangle([6, eye_row, 6, eye_row], fill=sk)
            # Right lens frame
            d.rectangle([8, eye_row-1, 10, eye_row+1], outline=gc)
            d.rectangle([9, eye_row, 9, eye_row], fill=sk)
            # Bridge connecting lenses
            d.point([(7, eye_row), (8, eye_row)], fill=gc)
            # Re-draw eyes on top of glasses fill
            d.point([(6, eye_row), (9, eye_row)], fill=(30, 25, 20, 255))

        elif a == "headphones":
            hpc = (80, 80, 200, 255)
            # Arc over head
            d.arc([self.HEAD_L, ht-1, self.HEAD_R, ht+4+b], start=200, end=340,
                  fill=hpc, width=2)
            # Ear cups at side of head
            d.rectangle([self.HEAD_L-1, ht+2, self.HEAD_L, ht+4], fill=hpc)
            d.rectangle([self.HEAD_R,   ht+2, self.HEAD_R+1, ht+4], fill=hpc)

        elif a == "tie":
            tc = (180, 30, 30, 255)
            neck_row = hb + b
            d.line([(7, neck_row), (7, 12)], fill=tc, width=1)
            d.rectangle([6, neck_row, 8, neck_row+1], fill=tc)  # knot

        elif a == "bow":
            bc = (220, 60, 120, 255)
            neck_row = hb + b
            d.rectangle([5, neck_row, 6, neck_row+1], fill=bc)
            d.rectangle([9, neck_row, 10, neck_row+1], fill=bc)
            d.point([(7, neck_row), (8, neck_row)], fill=bc)

        elif a == "antenna":
            ac = (100, 200, 100, 255)
            # Antenna from top of head diagonally upward — stays in frame
            base_x, base_y = self.HEAD_L + 1, ht
            tip_x  = max(0, base_x - 1)
            tip_y  = max(0, base_y - 2)
            d.line([(base_x, base_y), (tip_x, tip_y)], fill=ac, width=1)
            # Red tip dot — one more step up if room
            rt_x = max(0, tip_x - 1)
            rt_y = max(0, tip_y - 1)
            d.point([(rt_x, rt_y)], fill=(255, 80, 80, 255))


# ─── Sprite assembler ─────────────────────────────────────────────────────────

def make_sprite(
    skin: str,
    hair_style: str,
    hair_color: str,
    outfit: str,
    accent: tuple[int, int, int],
    accessory: str | None,
) -> "Image.Image":
    """Assemble a 64×16 (4 frames × 16px) spritesheet, facing down."""
    strip = Image.new("RGBA", (FRAME_W * FRAMES, FRAME_H), (0, 0, 0, 0))
    for phase in range(FRAMES):
        fp = FramePainter(skin, hair_style, hair_color, outfit, accent,
                          accessory, phase)
        frame = fp.render()
        strip.paste(frame, (phase * FRAME_W, 0), frame)
    return strip


def make_preview(strip: "Image.Image", scale: int = 8) -> "Image.Image":
    w, h = strip.size
    return strip.resize((w * scale, h * scale), Image.NEAREST)


# ─── CLI helpers ──────────────────────────────────────────────────────────────

def parse_hair(s: str) -> tuple[str, str]:
    """'short:brown' → ('short', 'brown')"""
    parts = s.split(":", 1)
    style = parts[0].lower()
    color = parts[1].lower() if len(parts) > 1 else "brown"
    return style, color


def parse_outfit(s: str) -> tuple[str, tuple[int,int,int]]:
    """'robe:#e07830' → ('robe', (224,120,48))"""
    parts = s.split(":", 1)
    name  = parts[0].lower()
    color = hex_to_rgb(parts[1]) if len(parts) > 1 else (100, 120, 200)
    return name, color


# ─── Batch presets ────────────────────────────────────────────────────────────

PRESET_BATCH = [
    # (id,        skin,    hair_spec,          outfit_spec,        accessory)
    ("player",    "tan",   "short:brown",      "hoodie:#3a7bd5",   "none"),
    ("chair",     "dark",  "short:grey",       "robe:#1a1a2e",     "glasses"),
    ("comm1",     "light", "long:blonde",      "robe:#e07830",     "none"),
    ("comm2",     "olive", "curly:black",      "robe:#10b8a0",     "headphones"),
    ("comm3",     "brown", "bun:brown",        "robe:#8060e8",     "bow"),
    ("spare",     "tan",   "mohawk:red",       "suit:#2d6a4f",     "antenna"),
]


def generate_preset_batch(out_dir: Path) -> list[dict]:
    records = []
    for (cid, skin, hair_spec, outfit_spec, acc) in PRESET_BATCH:
        hair_style, hair_color = parse_hair(hair_spec)
        outfit_name, accent    = parse_outfit(outfit_spec)
        strip   = make_sprite(skin, hair_style, hair_color, outfit_name, accent,
                              acc if acc != "none" else None)
        # Save sprite
        out_path = out_dir / f"{cid}.png"
        strip.save(str(out_path), "PNG")
        # Save preview (v2 tag)
        prev = make_preview(strip, 8)
        prev.save(f"/tmp/preview2_{cid}.png", "PNG")
        records.append({
            "id":          cid,
            "file":        f"sprites/{cid}.png",
            "frame_w":     FRAME_W,
            "frame_h":     FRAME_H,
            "frames":      FRAMES,
            "rows":        1,
            "facing":      "down",
            "skin":        skin,
            "hair":        hair_spec,
            "outfit":      outfit_spec,
            "accessory":   acc,
            "license":     "CC0 1.0 Universal",
            "generator":   f"sprite_forge.py v{VERSION}",
        })
        print(f"  {cid}.png  skin={skin} hair={hair_spec} outfit={outfit_spec} acc={acc}")
    return records


# ─── Manifest writer ──────────────────────────────────────────────────────────

def load_manifest(path: Path) -> list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_manifest(path: Path, records: list):
    with open(path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  manifest saved → {path}")


# ─── Self-test (v2 extended) ──────────────────────────────────────────────────

def selftest(out_dir: Path):
    import tempfile
    errors = []

    accent = (200, 80, 40)
    strip  = make_sprite("tan", "short", "brown", "hoodie", accent, "glasses")

    # 1. Size
    assert strip.size == (FRAME_W * FRAMES, FRAME_H), \
        f"Bad size: {strip.size}"

    # 2. Transparent corners (top-left of frame 0, top-right of frame 3, bottom-left)
    corner_checks = [
        (0, 0),
        (FRAME_W * FRAMES - 1, 0),
        (0, FRAME_H - 1),
        (1, 0),                          # near-corner also transparent
        (FRAME_W * FRAMES - 2, 0),
    ]
    for px in corner_checks:
        pv = strip.getpixel(px)
        assert pv[3] == 0, f"Corner-region {px} not transparent: {pv}"

    # 3. Frames differ (idle vs walk-1)
    frame0 = strip.crop((0, 0, FRAME_W, FRAME_H))
    frame1 = strip.crop((FRAME_W, 0, FRAME_W * 2, FRAME_H))
    assert frame0.tobytes() != frame1.tobytes(), "Idle and walk-1 frames are identical!"

    # 4. Skin zone does not contain accent colour
    accent_rgba = accent + (255,)
    skin_rgb = SKIN_TONES["tan"]
    for row in range(3, 9):        # rows 3-8 = inner face rows (below hair)
        for col in range(5, 11):   # inner head columns (inside corners)
            px = frame0.getpixel((col, row))
            if px[3] > 0:
                assert px[:3] != accent, \
                    f"Skin zone ({col},{row}) has accent colour {px}"

    # 5. Four frames
    assert strip.width == FRAME_W * FRAMES

    # 6. v2: Head rounded corners are transparent (frame 0)
    head_corners = [(4, 2), (11, 2), (4, 9), (11, 9)]
    for px in head_corners:
        pv = frame0.getpixel(px)
        assert pv[3] == 0, f"Head corner {px} should be transparent (rounded): {pv}"

    # 7. v2: Walk-phase 1 and 3 have body shifted (bob) — they differ from phase 2
    frame2 = strip.crop((FRAME_W*2, 0, FRAME_W*3, FRAME_H))
    frame3 = strip.crop((FRAME_W*3, 0, FRAME_W*4, FRAME_H))
    assert frame1.tobytes() != frame2.tobytes(), "Walk frames 1 and 2 must differ (bob)"
    assert frame3.tobytes() != frame2.tobytes(), "Walk frames 3 and 2 must differ (bob)"

    # 8. v2: Leg y-positions differ between phase 1 and phase 3 (stride swing)
    # Check lower half for differences
    leg_row_1 = [frame1.getpixel((c, r)) for r in range(12, 16) for c in range(5, 10)]
    leg_row_3 = [frame3.getpixel((c, r)) for r in range(12, 16) for c in range(5, 10)]
    assert leg_row_1 != leg_row_3, "Phase 1 and phase 3 leg pixels must differ (stride)"

    # 9. Reload from disk
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        strip.save(tf.name, "PNG")
        reloaded = Image.open(tf.name)
        assert reloaded.mode == "RGBA"
        assert reloaded.size == strip.size

    print("selftest PASS — size OK, transparent BG OK, rounded corners OK, "
          "frames differ, bob OK, stride swing OK, skin != accent, 4 frames")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parametric pixel-art sprite generator v2")
    parser.add_argument("--id",          default=None, help="Output ID (filename stem)")
    parser.add_argument("--skin",        default="tan",
                        choices=list(SKIN_TONES.keys()), help="Skin tone")
    parser.add_argument("--hair",        default="short:brown",
                        help="style:color e.g. short:brown")
    parser.add_argument("--outfit",      default="hoodie:#3a7bd5",
                        help="type:hex e.g. robe:#e07830")
    parser.add_argument("--accessory",   default=None,
                        choices=["glasses","headphones","tie","bow","antenna","none"],
                        help="Optional accessory")
    parser.add_argument("--preset-batch", action="store_true",
                        help="Generate 6 preset characters")
    parser.add_argument("--selftest",    action="store_true",
                        help="Run self-tests and exit")
    parser.add_argument("--out-dir",     default=None,
                        help="Output directory (default: static/assets/sprites/ relative to script)")

    args = parser.parse_args()

    # Resolve output directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    default_out = project_root / "static" / "assets" / "sprites"
    out_dir = Path(args.out_dir) if args.out_dir else default_out
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    if args.selftest:
        selftest(out_dir)
        return

    if args.preset_batch:
        print("Generating preset batch (v2)…")
        records = generate_preset_batch(out_dir)
        save_manifest(manifest_path, records)
        return

    # Single character mode
    if not args.id:
        parser.error("--id is required for single-character mode")

    hair_style, hair_color = parse_hair(args.hair)
    outfit_name, accent    = parse_outfit(args.outfit)
    acc = args.accessory if args.accessory and args.accessory != "none" else None

    strip    = make_sprite(args.skin, hair_style, hair_color, outfit_name, accent, acc)
    out_path = out_dir / f"{args.id}.png"
    strip.save(str(out_path), "PNG")
    prev = make_preview(strip, 8)
    prev.save(f"/tmp/preview2_{args.id}.png", "PNG")
    print(f"Saved: {out_path}")
    print(f"Preview: /tmp/preview2_{args.id}.png")

    # Update manifest
    records = load_manifest(manifest_path)
    records = [r for r in records if r.get("id") != args.id]
    records.append({
        "id":          args.id,
        "file":        f"sprites/{args.id}.png",
        "frame_w":     FRAME_W,
        "frame_h":     FRAME_H,
        "frames":      FRAMES,
        "rows":        1,
        "facing":      "down",
        "skin":        args.skin,
        "hair":        args.hair,
        "outfit":      args.outfit,
        "accessory":   args.accessory or "none",
        "license":     "CC0 1.0 Universal",
        "generator":   f"sprite_forge.py v{VERSION}",
    })
    save_manifest(manifest_path, records)


if __name__ == "__main__":
    main()
