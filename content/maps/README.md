# Maps

Maps are made in [Tiled](https://www.mapeditor.org/) and saved as **JSON maps (`.tmj`)**.
The loader lives in `coderogue/world/loader.py`.

## Map settings

| Setting | Value |
|---|---|
| Orientation | Orthogonal |
| Tile size | 16 x 16 |
| Tile layer format | **CSV** (Map > Map Properties). Base64/compressed layers are rejected. |
| Infinite | Off |

## Tilesets

Either embed the tileset in the map or reference an external **JSON** tileset (`.tsj`).
Image paths are relative to the file that declares them. From `content/maps/` the Kenney
sheets are:

- `../../assets/kenney/tiny-dungeon/Tilemap/tilemap_packed.png` (12 columns, no spacing)
- `../../assets/kenney/tiny-town/Tilemap/tilemap_packed.png` (12 columns, no spacing)

Use the `tilemap_packed.png` sheets (no spacing). A tile id is `row * 12 + col`; in the
map data a tile is stored as `firstgid + id` (0 means empty).

## Layers

Tile layers are drawn in Tiled order, under the characters:

| Layer name | Purpose |
|---|---|
| `ground` | Floor. Never solid. |
| `walls` | **Every non-empty tile here is solid.** Collision is built only from this layer. |
| `decor` | Optional. Non-solid details (rugs, cracks, bones). |
| `above` | Optional. Drawn *over* characters (archways, tree canopies). Not solid. |

Other tile layers are drawn but have no special meaning. Group layers are flattened.

## Objects

Put objects on an object layer named `objects`. Set the object's **Type** (Tiled 1.10+,
called *Class* in Tiled 1.9) to one of the values below. Rectangles or tile objects both
work; the object's centre is used for placement.

| Type | Meaning | Custom properties |
|---|---|---|
| `player_spawn` | Where the hero starts. Use one per map. | |
| `altar` | A Terminal shard; `i`/`Enter` opens the puzzle. | `puzzle` (string, e.g. `P-01`) |
| `enemy` | A wandering bug. | `hp` (int, default 3), `speed` (float px/s, default 30), `tile` (int sprite id, default 110) |
| `npc` | A character (static for now). | `tile` (int, default 96) |
| `chest` | A chest (static for now). | `tile` (int, default 89) |
| `door` | A door / exit (static for now). | `tile` (int, optional), later `target` |

Give objects a `name` so scripts and puzzles can refer to them.

## Testing a map

```
.venv/bin/python -m coderogue --map content/maps/your_map.tmj
.venv/bin/python -m coderogue --headless-frames 60 --map content/maps/your_map.tmj
```

`test_room.tmj` is the reference example.
