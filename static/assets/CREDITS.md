# Asset Credits

## Tilesets

### Kenney Tiny Dungeon
- **File**: tilemap_dungeon.png (packed, 192×176, 16×16 tiles, 12×11 grid)
- **Source**: https://kenney.nl/assets/tiny-dungeon
- **Author**: Kenney (www.kenney.nl)
- **License**: CC0 1.0 Universal — Public Domain
- **Downloaded**: 2026-07-08
- **Usage**: Character sprites (tiles 84–95: knight/player, priest/chair, mage/members)
  and dungeon tiles. Used with `setTint()` for per-AI color identity.

### Kenney Tiny Town
- **File**: tilemap_town.png (packed, 192×176, 16×16 tiles, 12×11 grid)
- **Source**: https://kenney.nl/assets/tiny-town
- **Author**: Kenney (www.kenney.nl)
- **License**: CC0 1.0 Universal — Public Domain
- **Downloaded**: 2026-07-08
- **Usage**: Interior floor/wall tiles (currently unused in favor of programmatic room).

### Kenney RPG Urban Pack
- **File**: tilemap_urban.png (432×288)
- **Source**: https://kenney.nl/assets/rpg-urban-pack
- **Author**: Kenney (www.kenney.nl)
- **License**: CC0 1.0 Universal — Public Domain
- **Downloaded**: 2026-07-08
- **Usage**: Reserved for future outdoor/hallway scenes.

## Programmatic Assets

### AI Identity Emblems
- 8×8 pixel badges drawn with Phaser Graphics API (no external files)
- Three emblem types:
  - **star** (✳ pattern): Claude — terracotta/orange tint
  - **knot** (rope-loop): ChatGPT — teal tint
  - **quad** (four-pointed star): Gemini — blue-purple tint
- Colors specified in config.json `members[].color`; shapes in `members[].emblem`
- No official logos used — abstract pixel badges only (trademark-safe)

### Room, Furniture, Plants
- Drawn programmatically with Phaser Graphics API

## Engine

### Phaser 3
- **File**: /vendor/phaser.min.js (v3.80.1)
- **Source**: https://github.com/phaserjs/phaser
- **License**: MIT
- **Downloaded**: 2026-07-08
