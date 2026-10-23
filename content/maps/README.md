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
| `water` | Optional. **Every non-empty tile here is water**: solid, and tinted blue-teal with a slow two-frame ripple (drawn after ground/walls, before `decor`). May be hidden (a mask); any tile layer with a `water` bool property set to true counts too. |
| `decor` | Optional. Non-solid details (rugs, cracks, bones). |
| `above` | Optional. Drawn *over* characters (archways, tree canopies). Not solid. |

Other tile layers are drawn but have no special meaning. Group layers are flattened.

## Map properties

| Property | Meaning |
|---|---|
| `area` | Area name shown in the HUD and as a big title card on entry (falls back to `name`, then the file stem). |
| `enter_flag` | Progress flag set whenever the map is loaded (e.g. `entered:echo_vale`). |

## Objects

Put objects on an object layer named `objects`. Set the object's **Type** (Tiled 1.10+,
called *Class* in Tiled 1.9) to one of the values below. Rectangles or tile objects both
work; the object's centre is used for placement. Any object can override its sprite with
`tile` (int id) and `sheet` (`dungeon`, the default, or `town`).

| Type | Meaning | Custom properties |
|---|---|---|
| `player_spawn` | Where the hero appears. The first one is the default; doors name others. | |
| `altar` | A Terminal shard; `i`/`Enter` opens the puzzle. | `puzzle` (e.g. `P-01`, `ch1-b`), `phase` (boss lecterns: `a`/`b`/`c` or 0-based int) |
| `enemy` | A bug (see `coderogue/entities/enemies.py`). | `kind` (`typo_mite`, `off_by_one`, `leak`, `looper`, `null_wisp`, `stamp_golem`; default wanderer; `kind=boss` + `boss=grubble/ouroboros/hollow_archivist`), `hp`, `speed`, `tile` |
| `npc` | A character you talk to. | `dialogue` (key, default the lower-cased name), `tile` (default 96) |
| `door` | An exit to another map, or a gate. | `target` (map stem, e.g. `echo_vale`; omit for a gate), `spawn` (name of a `player_spawn` in the target, default `spawn`), `locked_by` (progress flag), `requires_solved` (puzzle id), `plate` (name of a `plate`), `tile` (default 45) |
| `waystone` | Respawn point and save spot; `i` opens the waystone menu (seal, Ledger, rest). `m{a-z}` marks it. | `tile` (default Tiny Town 83, the signpost) |
| `chest` | Opens once with `i`. | `coins` (int), `item` (string), `tile` (default 89; opened 91) |
| `potion` | Heals on touch (not at full health). | `heal` (hp, default 2 = one heart), `tile` (default 115) |
| `coin` | Adds coins on touch. | `value` (default 1), `tile` (default Tiny Town 93) |
| `liftable` | A crate: solid on the ground, lifted with `yy`, put down with `p`. | `tile` (default 63) |
| `plate` | Pressure plate, pressed while a liftable rests on it. | `tile` (optional; drawn as a slab otherwise) |
| `prop` | Plain decoration. | `tile` |

Give objects a `name`: doors, marks, saves and `/` search refer to them by name.

### Doors, locks and transitions

- Walking onto an open door with a `target` fades out (0.25 s), loads the target map in
  place, puts the hero at the `spawn` and fades in. Arriving on top of a door does not
  trigger it until the hero steps off.
- A door is **locked** while its `locked_by` flag is missing, its `requires_solved` puzzle
  is unsolved, or its `plate` is not pressed. Locked doors are solid, greyed with a Null-wash
  and say "The Null holds this door" on touch.
- A door without `target` is a **gate**: solid while locked, passable once open.
- Taken pickups and opened chests are remembered as progress flags
  (`taken:<map>#<id>`, `opened:<map>#<id>`).

## Testing a map

```
.venv/bin/python -m coderogue --map content/maps/your_map.tmj
.venv/bin/python -m coderogue --headless-frames 60 --map content/maps/your_map.tmj
```

`test_room.tmj` is the reference example; `test_room2.tmj` (linked by doors both ways)
shows a waystone, chest, potion, coin, crate + plate + plate gate, and a Null-locked door.

## Authoring with mapgen

The story maps are generated from readable ASCII sources in `content/maps/src/*.map` by
`tools/mapgen.py`. Edit the `.map`, then regenerate; never hand-edit a generated `.tmj`.

```
.venv/bin/python tools/mapgen.py                    # regenerate every src/*.map
.venv/bin/python tools/mapgen.py content/maps/src/echo_vale.map
.venv/bin/python tools/mapgen.py --check            # CI: fail if a .tmj is stale
```

A source has four parts:

```
# comments start with '#' (in the legend, use '##' since '#' is a valid tile char)
name: echo_vale                  # output stem: content/maps/echo_vale.tmj
area: Echo Vale                  # every other header key becomes a map property
chapter: 1                       #   (ints/floats/true/false are typed)
enter_flag: entered:echo_vale
tilesets: town dungeon           # town firstgid 1, dungeon firstgid 133; first is default
seed: 3                          # optional; random picks default to crc32(name)
legend:
  . ground=town:0,0,0,1,2        # comma list = seeded random pick per cell
  T ground=town:0 wall=town:16,4 # wall= goes on the solid `walls` layer
  ~ ground=dungeon:0 wall=dungeon:0,12 water=1  # bare ids reuse the previous sheet;
                                 # water=1 marks the cell as water (tinted, solid)
  D ground=town:25 decor=town:85 # decor= / above= for the optional layers
grid:
TTTTTDTTTT                       # one char per tile; rows must be equal width
T........T
objects:
player_spawn spawn 4 1           # type name x y (tile coords) key=value ...
altar namestone @A puzzle=ch1-01 # @A = the single cell holding legend char A
door to_tilde @D target=little_tilde spawn=from_vale requires_solved=ch0-03
npc Mara 7 7 tile=99 dialogue=villager_mara
waystone murmurby 15 9 tile=83 sheet=town
```

Conventions used by the story maps:

- The first `player_spawn` must be named `spawn` (the scene uses the first one); add one
  `from_<map>` spawn per door that leads here, next to (not on) the door.
- A door that must stay shut until a puzzle is solved also needs the far side to be
  physically unreachable (water, a broken bridge span, a wall); the door teleports.
- NPC `tile`/enemy `tile` are Tiny Dungeon ids unless the object sets `sheet=town`.
- Water: add `water=1` to a legend entry to mark its cells as water. mapgen emits a hidden
  `water` mask layer (each cell repeats its own top tile), the loader lists those cells in
  `MapData.water`, and the renderer tints them and makes them solid. `water=sheet:id[,id]`
  instead puts a real tile on a visible `water` layer (drawn above `walls`). Keep a `wall=`
  on water cells anyway so the map still reads as blocked in Tiled. Bridges and word-stones
  (`=`, `_`) are plain ground and stay walkable.
- `tests/test_mapgen.py` checks door targets and spawns, altar puzzle ids, NPC dialogue
  keys, enemy kinds, that objects are not inside walls, and that `--check` is clean.
