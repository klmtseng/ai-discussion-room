#!/usr/bin/env python3
"""
sprite_forge.py — Parametric pixel-art character sprite generator
Outputs: static/assets/sprites/<id>.png  (16×16 × 4 frames, horizontal strip)
         static/assets/sprites/manifest.json

License: CC0 1.0 Universal — Public Domain
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

VERSION = "1.0.0"
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

OUTLINE_COLOR = (20, 15, 10, 255)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c*2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgba(r, g, b, a=255):
    return (r, g, b, a)


def blend_accent(accent_rgb: tuple, amount: float = 0.9) -> tuple[int,int,int,int]:
    """Return accent colour as RGBA."""
    r, g, b = accent_rgb
    return (r, g, b, 255)


# ─── Frame painter (Pillow) ───────────────────────────────────────────────────

class FramePainter:
    """Draws a single 16×16 character frame using Pillow."""

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
        return img

    # ── outline (filled silhouette one pixel larger, drawn first) ──
    def _draw_outline(self, d):
        c = OUTLINE_COLOR
        # body silhouette outline expanded by 1px
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                # head
                d.rectangle([4+dx, 2+dy, 11+dx, 9+dy], fill=c)
                # torso
                d.rectangle([4+dx, 9+dy, 11+dx, 13+dy], fill=c)

    def _draw_body(self, d):
        # Torso / outfit: rows 9-12, cols 4-11
        oc = rgba(*self.accent_rgb)
        # shoulder darker
        dark = tuple(max(0, v - 40) for v in self.accent_rgb) + (255,)
        d.rectangle([4, 9, 11, 10], fill=dark)   # shoulder band
        d.rectangle([4, 10, 11, 13], fill=oc)    # main torso

        # Outfit details
        if self.outfit == "robe":
            # Wide flowing robe — extend sides slightly
            d.rectangle([3, 9, 12, 13], fill=oc)
            # robe hem accent
            lighter = tuple(min(255, v + 50) for v in self.accent_rgb) + (255,)
            d.line([(3, 13), (12, 13)], fill=lighter, width=1)
        elif self.outfit == "suit":
            # Suit: dark lapels + white shirt strip
            lapel = (50, 50, 60, 255)
            d.line([(7, 9), (7, 13)], fill=lapel, width=1)
            d.rectangle([7, 9, 8, 13], fill=(230, 225, 215, 255))  # shirt
            d.rectangle([4, 9, 6, 13], fill=oc)    # left jacket
            d.rectangle([9, 9, 11, 13], fill=oc)   # right jacket
        elif self.outfit == "hoodie":
            # Hoodie: main body + pocket
            d.rectangle([4, 9, 11, 13], fill=oc)
            pock = tuple(max(0, v - 30) for v in self.accent_rgb) + (255,)
            d.rectangle([6, 11, 9, 13], fill=pock)  # front pocket

        # Arms (skin)
        sk = rgba(*self.skin_rgb)
        d.rectangle([3, 10, 3, 12], fill=sk)   # left arm
        d.rectangle([12, 10, 12, 12], fill=sk)  # right arm

    def _draw_legs(self, d):
        # Legs at rows 13-15 (bottom 3 rows)
        sk = rgba(*self.skin_rgb)
        # pants slightly darker than outfit
        pant = tuple(max(0, v - 60) for v in self.accent_rgb) + (255,)
        wp   = self.walk_phase

        # Left leg col 5-6, right leg col 8-9
        ll_y = 14  # left leg y base
        rl_y = 14  # right leg y base
        if wp == 1:   # step-left: left foot forward (higher = lower pixel row)
            ll_y = 13
            rl_y = 15
        elif wp == 3:  # step-right: right foot forward
            ll_y = 15
            rl_y = 13

        # Thigh
        d.rectangle([5, 13, 6, 13], fill=pant)
        d.rectangle([8, 13, 9, 13], fill=pant)
        # Shin/foot
        d.rectangle([5, ll_y, 6, 15], fill=pant)
        d.rectangle([8, rl_y, 9, 15], fill=pant)
        # Shoes (dark)
        shoe = (50, 40, 35, 255)
        if ll_y <= 15:
            d.rectangle([5, 15, 6, 15], fill=shoe)
        if rl_y <= 15:
            d.rectangle([8, 15, 9, 15], fill=shoe)

    def _draw_head(self, d):
        sk = rgba(*self.skin_rgb)
        # Head: 8×8 centred at cols 4-11, rows 2-9
        d.rectangle([4, 2, 11, 9], fill=sk)

    def _draw_hair(self, d):
        hc = rgba(*self.hair_rgb)
        hs = self.hair_style

        if hs == "short":
            # Short — top 2 rows of head
            d.rectangle([4, 2, 11, 3], fill=hc)
            d.point([(4, 4), (11, 4)], fill=hc)  # sideburn dots
        elif hs == "long":
            # Long — top + sides flow past face
            d.rectangle([4, 2, 11, 3], fill=hc)
            d.rectangle([3, 3, 4, 8], fill=hc)   # left drape
            d.rectangle([11, 3, 12, 8], fill=hc)  # right drape
        elif hs == "curly":
            # Curly — bumpy top
            d.rectangle([4, 2, 11, 3], fill=hc)
            for cx in [4, 6, 8, 10]:
                d.rectangle([cx, 1, cx+1, 2], fill=hc)
        elif hs == "bald":
            # Bald — just a small fringe
            pass  # no hair drawn
        elif hs == "bun":
            # Bun — short sides, small circle on top
            d.rectangle([5, 3, 10, 3], fill=hc)  # sides
            d.rectangle([7, 1, 9, 2], fill=hc)   # bun
        elif hs == "mohawk":
            # Mohawk — strip down centre
            d.rectangle([7, 0, 8, 3], fill=hc)
        else:
            # fallback = short
            d.rectangle([4, 2, 11, 3], fill=hc)

    def _draw_face(self, d):
        # Eyes: two dots at row 5, cols 6 and 9
        eye_col = (30, 25, 20, 255)
        d.point([(6, 5), (9, 5)], fill=eye_col)
        # Pupils highlight
        d.point([(6, 4), (9, 4)], fill=(255, 255, 255, 180))
        # Simple mouth: one pixel at row 7, col 7-8
        d.point([(7, 7), (8, 7)], fill=(180, 100, 80, 200))

    def _draw_accessory(self, d, img):
        if not self.accessory or self.accessory == "none":
            return
        a = self.accessory
        if a == "glasses":
            gc = (60, 60, 70, 220)
            # Two small squares around eyes
            d.rectangle([5, 4, 7, 6], outline=gc)
            d.rectangle([8, 4, 10, 6], outline=gc)
            d.line([(7, 5), (8, 5)], fill=gc, width=1)  # bridge
        elif a == "headphones":
            hc = (80, 80, 200, 255)
            # Arc over head
            d.arc([4, 1, 11, 6], start=200, end=340, fill=hc, width=2)
            # Ear cups
            d.rectangle([3, 4, 4, 6], fill=hc)
            d.rectangle([11, 4, 12, 6], fill=hc)
        elif a == "tie":
            tc = (180, 30, 30, 255)
            # Tie strip from chin to mid-torso
            d.line([(7, 8), (7, 12)], fill=tc, width=1)
            d.rectangle([6, 9, 8, 10], fill=tc)  # knot
        elif a == "bow":
            bc = (220, 60, 120, 255)
            # Bow at chin/collar
            d.rectangle([5, 8, 6, 9], fill=bc)
            d.rectangle([9, 8, 10, 9], fill=bc)
            d.point([(7, 8), (8, 8)], fill=bc)
        elif a == "antenna":
            # Single-side antenna (left side of head)
            ac = (100, 200, 100, 255)
            d.line([(5, 2), (3, 0)], fill=ac, width=1)
            d.point([(3, 0)], fill=(255, 80, 80, 255))  # red tip


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
        # Save preview
        prev = make_preview(strip, 8)
        prev.save(f"/tmp/preview_{cid}.png", "PNG")
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


# ─── Self-test ────────────────────────────────────────────────────────────────

def selftest(out_dir: Path):
    import tempfile, io
    errors = []

    # 1. Generate a test sprite
    accent = (200, 80, 40)
    strip  = make_sprite("tan", "short", "brown", "hoodie", accent, "glasses")

    # 2. Check size
    assert strip.size == (FRAME_W * FRAMES, FRAME_H), \
        f"Bad size: {strip.size} expected {(FRAME_W * FRAMES, FRAME_H)}"

    # 3. Check transparent background (corner pixels)
    corners = [(0, 0), (FRAME_W * FRAMES - 1, 0), (0, FRAME_H - 1)]
    for px in corners:
        pv = strip.getpixel(px)
        assert pv[3] == 0, f"Corner {px} not transparent: {pv}"

    # 4. Check walk frames differ (leg pixels should differ between phase 0 and phase 1)
    frame0 = strip.crop((0, 0, FRAME_W, FRAME_H))
    frame1 = strip.crop((FRAME_W, 0, FRAME_W * 2, FRAME_H))
    assert frame0.tobytes() != frame1.tobytes(), "Idle and walk-1 frames are identical!"

    # 5. Skin pixels must NOT equal the accent colour
    accent_rgba = accent + (255,)
    pixels = list(strip.getdata())
    skin_rgb = SKIN_TONES["tan"]
    skin_conflict = [p for p in pixels if p == accent_rgba and
                     abs(p[0] - skin_rgb[0]) + abs(p[1] - skin_rgb[1]) + abs(p[2] - skin_rgb[2]) < 30]
    # We test that the skin region doesn't contain accent colour:
    # Skin zone = head cols 4-11, rows 2-9 in frame 0
    skin_zone_cols = range(4, 12)
    skin_zone_rows = range(2, 10)
    for row in skin_zone_rows:
        for col in skin_zone_cols:
            px = frame0.getpixel((col, row))
            if px[3] > 0:
                assert px[:3] != accent, \
                    f"Skin zone pixel at ({col},{row}) has accent colour {px}"

    # 6. Check 4 frames
    assert strip.width == FRAME_W * FRAMES, "Wrong number of frames"

    # 7. Write to temp file and reload
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        strip.save(tf.name, "PNG")
        reloaded = Image.open(tf.name)
        assert reloaded.mode == "RGBA"
        assert reloaded.size == strip.size

    print("selftest PASS — size OK, transparent BG OK, frames differ, skin != accent, 4 frames")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parametric pixel-art sprite generator")
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
        print("Generating preset batch…")
        records = generate_preset_batch(out_dir)
        save_manifest(manifest_path, records)
        return

    # Single character mode
    if not args.id:
        parser.error("--id is required for single-character mode")

    hair_style, hair_color = parse_hair(args.hair)
    outfit_name, accent    = parse_outfit(args.outfit)
    acc = args.accessory if args.accessory and args.accessory != "none" else None

    strip   = make_sprite(args.skin, hair_style, hair_color, outfit_name, accent, acc)
    out_path = out_dir / f"{args.id}.png"
    strip.save(str(out_path), "PNG")
    prev = make_preview(strip, 8)
    prev.save(f"/tmp/preview_{args.id}.png", "PNG")
    print(f"Saved: {out_path}")
    print(f"Preview: /tmp/preview_{args.id}.png")

    # Update manifest
    records = load_manifest(manifest_path)
    # Remove old entry if exists
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
