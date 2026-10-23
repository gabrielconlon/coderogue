# CodeRogue: Story & Curriculum Bible (Draft 0.1)

> Working title: **CodeRogue**. 2D top-down real-time action, Python + Pygame-CE, Kenney 16px art. Movement and combat use VIM keys. Puzzles are solved with real code, in Python or bash. Audience: teens and up, no prior coding. MVP: Prologue + 3 chapters, 27 puzzles, 3-4 hours.

---

## 1. World & Lore

### The Kingdom of Shellmarch

Shellmarch is a small, stubborn kingdom built on top of **the Source**, the text the world is written in. Every river, door, and goat has a line of Source somewhere. Most people never see it. A few learn to read it, and fewer still learn to write it. Those few are called **scribes**, and what they write are **spells**. A spell is a script. Run it at an altar and the world does exactly what it says, which is rarely what the scribe meant.

Geography for the MVP, roughly in travel order:

- **Little Tilde**: the hero's home village, a cluster of cottages around a scriptorium. (Every journey starts at `~`.)
- **Echo Vale** and the town of **Murmurby**: a valley where anything spoken is repeated back. It is the birthplace of output.
- **Branchwood**: a forest where every path forks, and the gates open only if certain conditions are true.
- **The Looping Mire**: a swamp where travelers walk in circles forever. Some have been there for years and are very polite about it.
- **The Grand Directory**: a library-city of nested halls (rooms are folders, doors are paths) kept by an archivist.
- **Rootholm** (post-MVP): the capital, where the Terminal waits.

### The Null

The Null is a grey, quiet corruption. It does not burn or explode. It *empties*. Signposts go blank, prices vanish from shop boards, bells forget how to count, and people forget their own names. Touched objects become `None`, `""`, `0`. Colour drains to a flat grey palette swap, which makes it cheap to render and creepy to look at.

The Null pours out of a pit far below Rootholm called **the Hollow**. Old scribes call it `/dev/null`: whatever goes in never comes back. Someone is feeding the world into it on purpose.

### The Terminal

At the heart of Rootholm stands **the Terminal**, a black monolith with a single blinking cursor. It is the oldest thing in Shellmarch, and it is an oracle with one virtue: it is perfectly honest and perfectly literal. Give it a spell and it runs it, then tells you exactly what happened: the output, the error, the exit code. It never guesses what you meant. Shards of the Terminal, called **altars** (lowercase *terminals* in scribe slang), are scattered across the kingdom. Every coding puzzle happens at one.

The Terminal understands two living tongues: **the Serpent Tongue (Python)** and **the Shell Tongue (bash)**. Old inscriptions mention other tongues that are "sleeping", which is our hook for adding languages later. **The UI always shows the real names, Python and bash.** The fiction dresses them up, but players must know they are learning real, transferable languages.

### Bugs

Mistakes in the Source come alive as **bugs**: Typo-mites, Off-by-Ones (two-headed beetles that always land one tile from where you aimed), Loopers (snakes chasing their tails), Leaks (slimes that split if ignored), and Null-wisps. Most are killed by striking them out with `x`, because a bug is a stray character in the Source and `x` deletes characters.

### Why the hero moves with VIM keys: the Modal Way

Centuries ago, an order of scribes called the **Modal Order** found that the Source responds best to people who never take their hands off the home row. They codified **the Four Stances**:

| Stance | In the world | At an altar |
|---|---|---|
| **NORMAL** | Walk, dash, fight, read. "To move through the world is to read it." | Move the cursor, delete, yank |
| **INSERT** | (only at altars) | Write the spell |
| **VISUAL** | Lock on to and select targets | Select text |
| **COMMAND** | Speak to the world itself: `:map`, `:save`, `:help` | `:w` casts, `:q` leaves |

The Order's first proverb: **"When in doubt, Escape."** `Esc` always returns you to NORMAL, in both the world and the editor. That is our universal panic button, and the fiction says so explicitly.

Wren was raised in a scriptorium by one of the last Modal teachers, which is why the hero walks with `hjkl` and why it feels natural in-world.

**Your output is the world.** When a spell succeeds, its stdout literally appears in the game: on the signpost, from the bell, in the ferryman's mouth. Players see their own text become part of Shellmarch.

---

## 2. Cast

### Hero

**Wren** (they/them by default; the pronoun choice is offered once, at the scriptorium ledger). A seventeen-ish apprentice copyist in Little Tilde. Dry, curious, and allergic to being told "that's impossible". Wren mostly stays silent but gets occasional short reply choices, which are always flavour and never branch the story. **Motivation:** in the Prologue the Null takes the name and memories of Wren's teacher, Pell. Folk wisdom says only the Terminal can write a name back into the Source, so Wren walks to Rootholm.

### Mentors and NPCs

| Name | Role | Tied to | Notes |
|---|---|---|---|
| **Pell** | Wren's teacher, now nulled into a grey outline called "None" | NORMAL mode, reading before writing | Appears at waystones. Each chapter restores a few of Pell's words: Prologue "...", Ch1 "...Wren.", Ch2 "Morrow. The Blank.", Ch3 full sentences. Pell's catchphrase: "Read it twice. Write it once." |
| **Quill** | Altar-keeper of Echo Vale's chapel | INSERT mode, print, variables | Fussy and delighted, and keeps trying to end sentences with semicolons. Teaches `i`, `A`, `o`, `Esc`. |
| **Tally** | Innkeeper and shopkeeper at the Crossroads | Arithmetic, counts, loops | Counts everything out loud. Runs the shop where coins buy potions and cosmetics. Teaches count prefixes (`3j`, `2x`): "Count before you act." |
| **Sable** | Ranger of Branchwood | VISUAL mode, conditionals | "Every fork in the wood is a question. Answer it before you walk." Gives Wren the Spyglass (the `v` lock-on). |
| **Dex** | Archivist of the Grand Directory | Dictionaries, files, `/` search, yank/put | Talks in key: value pairs when stressed. Has catalogued 40,000 books and lost one pencil. |
| **Cole** | Herald of the Waystones | COMMAND mode | Only speaks after clearing their throat with a colon (":ahem"). Teaches `:help`, `:save`, `:map`, `:marks`. Running gag: Cole is very proud of `:q` and sad whenever anyone uses it. |
| **Moth** | A reformed bug and Wren's companion | Errors, debugging, the hint system | The first bug Wren meets that `x` won't delete ("I'm not a mistake, I'm *misunderstood*"). Moth is the voice of every error translation and hint. A nod to computing folklore's first "bug". |

### Antagonists

- **Archscribe Morrow, the Blank**: once the head of the Modal Order and a brilliant perfectionist. After a lifetime of fixing bugs, Morrow concluded that every program with lines has bugs, so the only flawless program is the empty one. Morrow is "fixing" Shellmarch by deleting it, one line at a time, into the Hollow. Morrow is not cackling evil. They are tired, sincere, and wrong. Morrow is seen only in echoes until the post-MVP finale.
- **Chapter bosses** (Morrow's lieutenants, born from the Null):
  - **Grubble, the Typo King** (Ch1): a bloated beetle crowned with misspelled letters.
  - **The Ouroboros** (Ch2): a worm eating its own tail. It regrows every lap, so it is unkillable by damage.
  - **The Hollow Archivist** (Ch3): an echo of Morrow made of torn index cards, eating the Directory's records.

---

## 3. MVP Story Outline

**Pacing rule:** areas alternate in a rhythm of *explore/fight → altar → explore/fight → altar*, with roughly 60% of the critical path spent on action and 40% on authored puzzle content (see the budget note in §4). **Time stops in INSERT mode.** Coding is never timed, not even during boss fights.

### Prologue: "Little Tilde" (~20 min, 3 puzzles)

**Area:** Little Tilde. The scriptorium, its garden, the village square, and the gate.

**Beats**
1. Wren wakes at the copy desk. Pell asks them to fetch ink from the shelf. A tutorial overlay teaches **`h j k l`** (held to keep walking). Pell: "j hangs low like a hook. k climbs."
2. Typo-mites are chewing the herb garden. Pell teaches **`x`**, which strikes out a bug. One mite won't die. It is Moth, who begs, jokes, and tags along.
3. The Null rolls in as a grey tide. Pell shoves Wren into the vault and is caught. When Wren comes out, Pell is a grey outline that answers only "None."
4. The village altar is dark. Quill's voice, carried on an echo from the next valley, teaches **`i`** (INSERT), **`Esc`**, and **`:w`** (cast). **P-01** lights the lantern with Wren's first `print`/`echo`.
5. **P-02:** the gate opens only to a three-line chant.
6. **P-03:** Pell's ward-spell has typos. Wren fixes them with **`x` inside the editor**: the same key as the attack, now aimed at a character. The ward pushes the Null out of the square.
7. Cole appears at the waystone, unlocks **`:help`** and **`:q`**, and points the way to Rootholm. Quest begins.

**Mechanics introduced:** `hjkl`, `x`, `i`, `Esc`, `:w`, `:q`, `:help`.

### Chapter 1: "Echo Vale" (~60 min, 8 puzzles)

**Area:** a green valley with a river, the town of Murmurby, Tally's Crossroads Inn, an orchard, and a ferry. The Null has wiped every name and number, so signs are blank and the bell cannot count.

**Beats**
1. Entering the vale, Wren finds the river cut by **word-stones**: stepping stones separated by gaps. Quill's apprentice explains the Runner's Stride: **`w`** leaps to the start of the next stone, **`b`** leaps back, and **`e`** lands on the far edge. In combat, `w`/`b` are i-frame dashes. In the editor they hop between words. *This is the core "same key, two meanings" moment.*
2. **1-01:** re-carve Murmurby's name-stone using a variable.
3. Open field: Typo-mites and the first Off-by-Ones. Cole's waystone unlocks **`:save`** and **`:map`**.
4. **1-02 (optional):** the lamplighter's tally.
5. **1-03:** the toll bridge charges per cart, so you compute the toll.
6. The orchard is crawling with Leaks that you must clear before they split. **1-04:** share apples into baskets.
7. **1-05:** the ferryman asks your name. **1-06:** the town crier has lost their voice.
8. Tally's Inn: the shop opens. **1-07:** write Tally's receipt spell. Quill teaches editor moves **`A`** (append at end of line), **`o`** (open a new line), and **`0`**/**`$`**.
9. **Boss: Grubble, the Typo King** in the Hall of Echoes.

**Boss design.** The arena has three lecterns. Grubble spawns waves of Typo-mites and charges in straight lines (dodge with `w`/`b`). Striking the glowing letters on his crown with `x` stuns him. While he is stunned, step onto a lectern and press `i`; time freezes. Each lectern is one phase of **1-B**:
- (a) unscramble Grubble's garbled proclamation (debug 3 errors);
- (b) take the census: read three household counts and print the total and average;
- (c) write the banner, a formatted shout that uses the census.

**Payoff:** the hall's banner displays the player's own output and Grubble deflates into a pile of letters. Every sign in Echo Vale relights with its name. Pell, at the waystone, says their first word: "...Wren." Quill joins as the voice of future altars.

**Mechanics introduced:** `w`, `b`, `e` (world and editor), `A`, `o`, `0`, `$`, `:save`, `:map`.

### Chapter 2: "Branchwood & the Looping Mire" (~75 min, 8 puzzles)

**Area:** Branchwood, a forest of forking paths and condition-gates, leads into the Looping Mire, a swamp of circular causeways ringing with bells.

**Beats**
1. Branchwood's first fork: a bridge that holds only so much weight. **2-01** teaches `if/else`.
2. Ranger Sable's lodge. Sable gives Wren the Spyglass, unlocking **VISUAL mode (`v`)**: hold `v` to lock on, and cycle targets with `hjkl`. Null-wisps can only be hit while locked on. **2-02 (optional):** Sable's bestiary needs an `elif` classifier.
3. Tally sends a letter by crow that teaches **counts**: `3j` dashes three tiles, `3x` does a triple strike, and the same counts work in the editor.
4. The Mire. Loopers coil in rows, and Wren learns the **Cleave (`dd`)**, which hits a whole row of enemies. In the editor, `dd` deletes a line. **2-03:** silence the bells with a countdown loop.
5. Wren finds Ono's Hourglass in a sunken shrine. **`u`** rewinds the last 3 seconds of movement (3 charges, which refill at waystones). In the editor it undoes the last change. The fiction for undo is a respectful time-hermit's relic.
6. **2-04:** light the causeway lanterns (accumulator loop). **2-05:** the herbalist's list (arrays). **2-06:** sort the swarm (filtering stdin). **2-07 (optional):** the firefly rhythm.
7. Lost travelers walking in circles reveal the Ouroboros at the Mire's heart.
8. **Boss: The Ouroboros.**

**Boss design.** The arena is a ring. The worm circles and regrows segments every lap, so damage alone never wins, which is the point. Three loop-stones sit around the ring. Lock on to a glowing segment with `v` and cleave it with `dd` to open a stone's window. Phases of **2-B**:
- (a) find the weakest segment (min value and position);
- (b) repair the worm's own loop: the starter code never ends, and the player must make it terminate;
- (c) apply a damage list to every segment and report the survivors.

**Payoff:** the worm's tail slips from its mouth and it simply unwinds, harmless, into a long sleepy river serpent. The Mire drains. The looping travelers walk out, and one is Dex's courier, carrying the key to the Grand Directory. Pell: "Morrow. The Blank. Do not let them... empty..."

**Mechanics introduced:** `v`, counts, `dd`, `u`.

### Chapter 3: "The Grand Directory" (~80 min, 8 puzzles)

**Area:** a library-city of nested halls. Doors are labelled like paths (`/stacks/maps/old`), and the Null is eating the catalogues.

**Beats**
1. Dex greets Wren in a panic: the inventory is half blank. **3-01** introduces dictionaries.
2. Dex teaches **`yy`/`p`** (yank and put). Wren can yank a world object (a bookshelf, a plank, a lit brazier) and put it elsewhere. Gap-bridging and pressure-plate rooms become copy-paste puzzles. In the editor it is copy and paste.
3. The Gossip Gallery is a wall of shouting words. **3-02:** count every word.
4. Stamp-golems block the Reading Room and accept only a greeting rite. **3-03** teaches functions. **3-04 (optional):** the toll function.
5. Dex teaches **`/` search** and **`n`**: type `/atlas` and every matching book in the hall glows, then cycle with `n`. The same works in the editor. Cole teaches **`m{a-z}`** to set a mark at a waystone and **`'a`** to fast-travel there, which pays off in the backtracking-heavy Directory.
6. **3-05:** write the ledger file. **3-06:** read the singed scroll. **3-07:** build the pipe-aqueduct that carries water to the fire-damaged stacks.
7. In the Census Hall, the Hollow Archivist is eating name cards.
8. **Boss: The Hollow Archivist.**

**Boss design.** The Archivist teleports between shelves and throws card-storms. Yank its own shield-cards with `yy` and put them (`p`) back into the catalogue slots to expose it. Use `/` to find the hidden real catalogue among decoys. Set marks before each phase so you can retreat to a lectern. Phases of **3-B**:
- (a) parse `census.csv` into records;
- (b) a function that decides whether a record is nulled;
- (c) a dictionary of village → nulled count;
- (d) write `restored.txt` with every nulled name, sorted.

**Payoff:** `restored.txt` is the Directory's new register. One of the names the player's code wrote is **Pell**. At the waystone, Pell regains colour and full speech: "You wrote me back." Pell names Morrow, the former Archscribe, and reveals that Morrow has "commented out" the road to Rootholm. MVP ends with Wren, Moth, and Pell at the Directory's top gate, looking at a road made of greyed-out `#` marks. *To be continued.*

**Mechanics introduced:** `yy`, `p`, `/`, `n`, `m{a-z}` / `'{a-z}` marks.

---

## 4. Curriculum Map (27 puzzles)

**Ramp logic.** Output → sequencing → reading errors → variables → arithmetic → input → strings → type conversion → compose (boss) → branching → loops → lists → filtering streams → compose (boss) → dictionaries → functions → files → pipelines → compose (boss). This follows a standard CS0/CS1 order, with "read an error" introduced in the Prologue so that failure is normal from minute ten.

**Validation key:** **OUT** = stdout match after normalization; **OUT×n** = n stdin test cases; **RX** = regex on stdout; **SRC** = regex on the player's source (e.g. "you must use a variable"); **FILE** = expected file exists with expected content; **EXIT** = exit code; **T/O** = timeout guard. ★ = optional side altar, never required by a boss.

| ID | Ch | In-world framing | Concept | Python task | bash task | Validation | Min | VIM skill |
|---|---|---|---|---|---|---|---|---|
| P-01 | 0 | Light Tilde's lantern with its first word | Output, string literals | `print("Hello, Tilde.")` | `echo "Hello, Tilde."` | OUT | 3 | `i`, `Esc`, `:w` |
| P-02 | 0 | Chant the three-line gate verse | Sequencing, one statement per line | Line 1 is given; add lines 2-3 in order | Same with `echo` | OUT | 3 | `j`/`k` between lines |
| P-03 | 0 | Mend Pell's broken ward | Reading errors, fixing typos | Fix `prnt(` and a missing closing quote | Fix `ehco` and an unmatched quote | OUT + EXIT 0 | 4 | `x` on a character |
| 1-01 | 1 | Re-carve the blank name-stone | Variables, assignment | `village = "Murmurby"`; print `Welcome to Murmurby` using it | `village="Murmurby"` (no spaces around `=`); `echo "Welcome to $village"` | OUT + SRC (variable used) | 4 | `w`/`b` in editor |
| 1-02★ | 1 | The lamplighter counts as they go | Reassignment, updating state | `lamps = 3`, add 2, print; add 4, print | `lamps=$((lamps + 2))`, echo twice | OUT | 4 | `e` |
| 1-03 | 1 | Pay the toll bridge: 4 carts × 7 coins + 5 fee | Arithmetic, precedence | Use `carts`, `price`, `fee` variables; print `33` | `echo $((carts * price + fee))` | OUT + SRC (no literal `33`) | 4 | `A` (append) |
| 1-04 | 1 | Share 47 apples among 5 baskets | Integer division, remainder | `//` and `%` → `9 each, 2 left over` | `$((47 / 5))`, `$((47 % 5))` | OUT | 5 | `o` (open line) |
| 1-05 | 1 | The ferryman asks who rides | Reading stdin | `name = input()`; greet | `read -r name`; greet | OUT×3 | 5 | `0`, `$` |
| 1-06 | 1 | The town crier has lost their voice | String operations | Read a name; print it uppercase and its length | `${name^^}`, `${#name}` | OUT×3 | 5 | `w` dash (world) |
| 1-07 | 1 | Tally's receipt: potions at 12 coins each | Type conversion, formatted output | `qty = int(input())`; f-string `3 potions cost 36 coins.` | `read -r qty`; `echo "$qty potions cost $((qty * 12)) coins."` | OUT×3 | 6 | `A` + `o` together |
| 1-B | 1 | **Boss: Grubble, the Typo King** | Compose Ch1 | (a) fix a 5-line garbled script; (b) read 3 counts, print total and integer average; (c) print `HEAR YE, <NAME>! <total> SOULS COUNTED.` | Same three phases in bash | OUT×n per phase + EXIT 0 | 12 | `w`/`b` dodge, `x` stun |
| 2-01 | 2 | Branchwood bridge holds 100 stone | `if/else`, comparison | Read weight; print `PASS` or `TOO HEAVY` | `if [ "$w" -le 100 ]` | OUT×3 (incl. boundary 100) | 5 | counts (`3j`) |
| 2-02★ | 2 | Sable's bestiary sorts monsters by HP | `elif` chains, boundaries | `brute` ≥50, `skirmisher` ≥20, else `pest` | `if/elif/else` with `-ge` | OUT×4 (each boundary) | 6 | `v` lock-on |
| 2-03 | 2 | Silence the Mire bells | `while` loop, termination | Read n; print n down to 1, then `Silence.` | `while [ "$n" -gt 0 ]` | OUT×3 (incl. n=0) + T/O | 6 | `u` (undo) |
| 2-04 | 2 | Light the causeway lanterns 1..n | `for` over a range, accumulator | `for i in range(1, n + 1)`; print the sum | `for ((i=1; i<=n; i++))` | OUT×3 + SRC (loop used) | 6 | `dd` |
| 2-05 | 2 | The herbalist's list | Lists/arrays, index, length | Print `1. sage` …, then the count and the last herb | `herbs=(sage rue mint)`, `"${herbs[@]}"`, `${#herbs[@]}` | OUT | 5 | `3j`, `2dd` |
| 2-06 | 2 | Sort the swarm: only the big bugs | Loop over stdin until EOF, filter + count | `for line in sys.stdin:` print sizes > 10, then the count | `while read -r size` … `-gt 10` | OUT×3 (incl. empty input) | 7 | `dd` (cleave rows) |
| 2-07★ | 2 | The firefly rhythm | Modulo + order of conditions | 1..n: `Glow` (÷3), `Hum` (÷5), `GlowHum` (both), else the number | Same with `$(( i % 15 ))` etc. | OUT×2 | 8 | `u` |
| 2-B | 2 | **Boss: The Ouroboros** | Compose Ch2; termination | (a) read segment HPs, print weakest and its position; (b) fix a never-ending loop; (c) subtract 7 from each, print survivors and count | Same in bash | OUT×n + T/O 2s + EXIT 0 | 15 | `v` + `dd` + `u` in combat |
| 3-01 | 3 | Dex's half-blank inventory | Dicts / associative arrays | Build `inv`, print `inv["potion"]`, add `lantern`, print key count | `declare -A inv=([potion]=3 …)`, `${inv[potion]}`, `${#inv[@]}` | OUT | 6 | `yy`/`p` |
| 3-02 | 3 | The Gossip Gallery: count every word | Dict as counter, sorted output | Count words from stdin; print `word count` alphabetically | Assoc-array counter; `for k in "${!c[@]}"` … `\| sort` | OUT×2 | 8 | `/` search |
| 3-03 | 3 | Stamp-golems need a greeting rite | Defining/calling functions, parameters | `def greet(name):` return `Hail, <name>!`; call 3× | `greet() { echo "Hail, $1!"; }`; call 3× | OUT + SRC (function defined) | 6 | `n` (next match) |
| 3-04★ | 3 | The toll function | Return values, multiple params, composing calls | `toll(carts, heavy)` returns 7×carts (+10 if heavy); print sum of 3 calls | Function echoes value; `total=$(( $(toll 3 yes) + … ))` | OUT | 7 | marks `ma` / `'a` |
| 3-05 | 3 | Write Dex's new ledger | Writing files | `open("ledger.txt", "w")`; write 3 lines | `echo … > ledger.txt`, then `>>` | FILE + EXIT 0 | 5 | `:w` vs file writes |
| 3-06 | 3 | Read the singed scroll | Reading files, searching lines | Open `scroll.txt`; print the line count and the line containing `Null` | `wc -l < scroll.txt`; `grep "Null" scroll.txt` | RX (tolerates `wc` padding) | 7 | `/` in editor |
| 3-07 | 3 | Build the pipe-aqueduct | Composition: pipelines / chained transforms | From `bugs.txt`, skip `#` lines, print unique names sorted, then their count | `grep -v '^#' bugs.txt \| sort -u`; then `… \| wc -l` | RX | 8 | `yy`/`p` lines |
| 3-B | 3 | **Boss: The Hollow Archivist** | Compose Ch3: files + dicts + functions | Parse `census.csv`; `is_nulled()`; print village→count sorted; write sorted `restored.txt`; print `Restored N names.` | `while IFS=, read -r name village status`, `declare -A`, function, `sort > restored.txt` | OUT + FILE + EXIT 0 | 18 | everything; marks between phases |

**Budget note (honest math).** The estimates are *median first-time-coder* minutes, including reading the lore and one retry. They sum to **~178 min** across all 27, and **~153 min** on the critical path (excluding the four ★ puzzles). At a strict 60/40 split that would be a ~6-hour game for a true beginner, and roughly 3.5 hours for a player with a little prior exposure. Recommendations:

1. Treat 3-4 hours as the target for a confident beginner on the critical path.
2. Size *authored action content* to the 60%.
3. Accept that wall-clock time will skew toward coding for slower learners. That is fine because time freezes in INSERT mode, so it isn't stressful.
4. If playtests run long, cut ★ altars first, then compress Ch3's 3-04/3-07 into the boss.

**Platform note.** bash puzzles assume **bash ≥ 4** (associative arrays, `${x^^}`). macOS ships bash 3.2. The runner must find a bash 4+ at startup or tell the player how to get one. The puzzle schema carries `requires.bash`.

---

## 5. Puzzle Format Spec

One YAML file per puzzle: `puzzles/<chapter>/<id>.yaml`. YAML is chosen because multi-line starter code reads cleanly in it. The loader converts it to the same structure as JSON, so JSON files are also accepted.

### Schema (annotated)

```yaml
id: ch1-05                 # unique, stable; save files reference it
title: The Ferryman's Question
chapter: 1                 # 0 = Prologue
order: 5                   # position on the chapter's critical path
optional: false            # true = side altar; bosses must not depend on it
concepts: [input, variables]        # tags for the progress journal (:help concepts)
vim_skill: "0 and $"       # shown on the altar's tooltip
lore: |                    # shown above the editor; 2-5 lines, written in-world
  ...
requires:                  # optional runtime constraints
  bash: ">=4"
  python: ">=3.10"
limits:
  timeout_s: 2             # per test; exceeded → "the Terminal cut the chant short"
  max_stdout_kb: 16
fixtures:                  # files copied into the sandbox temp dir before EVERY test
  - path: scroll.txt
    content: |
      ...
languages:                 # one block per language; new languages = new keys
  python:
    starter: |             # pre-filled editor contents; may contain ___ blanks
      ...
    hints: [ "...", "...", "..." ]   # EXACTLY 3: nudge → pointer → near-solution
    solution: |            # reference solution; CI runs it against tests. Shown after skip.
      ...
    source_checks:         # optional regex on the player's code
      - pattern: '\bvillage\s*='
        message: "Store the name in a variable called village first."
  bash:
    starter: |
      ...
    hints: [ ... ]
    solution: |
      ...
tests:                     # ALL must pass; run in order; first failure is reported
  - name: "human-readable label, shown on failure"
    stdin: "Wren\n"        # optional; runner guarantees a trailing newline
    expect:
      stdout: "exact text\n"          # compared after normalization (below)
      stdout_regex: '^\s*4\s*$'       # alternative to stdout (multiline mode)
      exit_code: 0                    # default 0
      files:                          # checked in the sandbox after the run
        - path: ledger.txt
          content: "...\n"            # or: regex: '...'
    match: normalized      # normalized (default) | exact
phases: []                 # bosses only: a list of nested puzzle bodies
                           # (lore, languages, tests), solved in order
reward:
  xp: 30
  items: [ferry_token]
  unlocks: []              # e.g. ["vim:w", "cmd:map"]
  world_effect: "free text for the level designer"
```

**Runner contract.**
- Each test runs in a fresh temp dir with fixtures copied in, the temp dir as cwd, a minimal environment (`PATH`, `HOME=$TMP`, `LANG=C.UTF-8`), and no network.
- Python runs as `python -I main.py`. bash runs as `bash --noprofile --norc main.sh`.
- **Normalized match** converts CRLF to LF, strips trailing whitespace on every line, and strips trailing blank lines from both sides before comparing.
- CI lints every puzzle by running each `solution` against its own tests and running each `starter` to confirm it *fails*. An unsolved starter that already passes is a bug.

### Example A: Chapter 1, puzzle 1-05

```yaml
id: ch1-05
title: The Ferryman's Question
chapter: 1
order: 5
optional: false
concepts: [input, variables, string-concatenation]
vim_skill: "0 and $ (jump to start/end of a line)"
lore: |
  A hooded ferryman poles the Murmur, but the Null has taken every
  name it ever knew. It will not push off until it hears one.
  "WHO RIDES?" it booms, and waits for your spell to answer.
limits: {timeout_s: 2, max_stdout_kb: 16}
languages:
  python:
    starter: |
      # The ferryman's words arrive through input().
      # Catch them in a variable, then greet the rider.
      name = ___
      print("Welcome aboard, " + ___ + ". Mind the Null.")
    hints:
      - &ferry_h1 "The ferryman speaks first. Your spell has to listen before it answers. Which line should do the listening?"
      - "input() waits for one line of text and hands it back. Put it on the right-hand side of name = ..."
      - "First blank: input()   Second blank: name   (Notice \"Welcome aboard, \" already ends with a space.)"
    solution: |
      name = input()
      print("Welcome aboard, " + name + ". Mind the Null.")
  bash:
    starter: |
      # The ferryman's words arrive on stdin.
      # read catches one line into a variable.
      ___ -r name
      echo "Welcome aboard, ___. Mind the Null."
    hints:
      - *ferry_h1
      - "read -r name waits for one line and stores it in name. To use a variable's value, put a $ in front of it."
      - "First blank: read   Second blank: $name   Keep the double quotes so a name with a space survives."
    solution: |
      read -r name
      echo "Welcome aboard, $name. Mind the Null."
tests:
  - name: "Wren rides"
    stdin: "Wren\n"
    expect: {stdout: "Welcome aboard, Wren. Mind the Null.\n", exit_code: 0}
  - name: "A different rider"
    stdin: "Pell\n"
    expect: {stdout: "Welcome aboard, Pell. Mind the Null.\n"}
  - name: "A rider with two names"
    stdin: "Mara Fen\n"
    expect: {stdout: "Welcome aboard, Mara Fen. Mind the Null.\n"}
reward:
  xp: 30
  items: [ferry_token]
  world_effect: "The ferryman speaks the player's stdout aloud; the route to the Crossroads opens."
```

### Example B: Chapter 2, puzzle 2-06

```yaml
id: ch2-06
title: Sort the Swarm
chapter: 2
order: 6
optional: false
concepts: [loops, conditionals, stdin-until-eof, counting]
vim_skill: "dd (cleave a whole line)"
lore: |
  A swarm boils out of the reeds. Sable's spyglass reads each bug's size,
  one per line, but the Mire's lanterns can only spare light for the big
  ones. Name every bug larger than 10, then report how many there were.
  Bugs of exactly 10 are "medium", says Sable, "and medium is not big."
limits: {timeout_s: 2, max_stdout_kb: 16}
languages:
  python:
    starter: |
      import sys

      big = 0
      for line in sys.stdin:
          size = int(line)
          # Your spell here: print the size if it is a big bug,
          # and count it.

      print("Big bugs:", big)
    hints:
      - &swarm_h1 "You already visit every bug, one per lap of the loop. On each lap, ask one question: is this bug bigger than 10?"
      - "Inside the loop, use `if size > 10:` and indent the lines that should only happen for big bugs. Two things happen: print it, and add 1 to big."
      - "if size > 10:\n        print(size)\n        big = big + ___"
    solution: |
      import sys

      big = 0
      for line in sys.stdin:
          size = int(line)
          if size > 10:
              print(size)
              big = big + 1

      print("Big bugs:", big)
  bash:
    starter: |
      big=0
      while read -r size; do
        # Your spell here: echo the size if it is a big bug,
        # and count it.
        :
      done
      echo "Big bugs: $big"
    hints:
      - *swarm_h1
      - "In bash, compare numbers with [ \"$size\" -gt 10 ]. -gt means 'greater than'. Wrap it in if ...; then ... fi."
      - "if [ \"$size\" -gt 10 ]; then\n    echo \"$size\"\n    big=$((big + ___))\n  fi"
    solution: |
      big=0
      while read -r size; do
        if [ "$size" -gt 10 ]; then
          echo "$size"
          big=$((big + 1))
        fi
      done
      echo "Big bugs: $big"
tests:
  - name: "A mixed swarm"
    stdin: "4\n12\n9\n31\n11\n"
    expect: {stdout: "12\n31\n11\nBig bugs: 3\n", exit_code: 0}
  - name: "Two medium bugs (exactly 10 is not big)"
    stdin: "10\n10\n"
    expect: {stdout: "Big bugs: 0\n"}
  - name: "No bugs at all"
    stdin: ""
    expect: {stdout: "Big bugs: 0\n"}
reward:
  xp: 60
  items: [lantern_oil]
  unlocks: []
  world_effect: "Big bugs in the next room glow and become lockable with v; small ones flee."
```

---

## 6. Hint & Failure Design

**Principles:** failure is information, not punishment. Coding is never timed. Nothing you've earned is ever taken away.

**When a spell is wrong**
1. **The Null pushes back, cosmetically.** The altar flickers, grey tendrils creep a few pixels onto its rim, and a single Null-mite wobbles in at the edge of the room once you leave INSERT. It is weak, optional, and good for venting. After the third failed cast in a row the Null "gets bored" and stops sending them. There is no damage, no lost coins, and no reset.
2. **The Terminal shows a precise diff.** The failure panel shows the failing test's name and its stdin, then *Expected* and *Your spell said* side by side, with the first differing line highlighted. Invisible differences are made visible: trailing spaces show as `·` and a missing final newline as `⏎`. If several tests fail, only the first one is shown, to keep cognitive load low.
3. **Source checks speak plainly:** "The output is right, but the Terminal wants to see a variable called `village` do the work."

**The 3-rung hint ladder** (the `?` key in NORMAL mode at the altar, or `:hint`)
- **Rung 1, Nudge:** restates the goal and points at the right idea, with no syntax. Usually shared across languages.
- **Rung 2, Pointer:** names the language feature and shows its shape (`if size > 10:`).
- **Rung 3, Near-solution:** almost the full code with one or two `___` blanks, so the player still types the final piece.

Hints are always available and never cost anything. Moth *offers* rung 1 (as a speech bubble, not a forced popup) after two failed casts or 3 minutes idle. The `:journal` remembers which rung you needed, purely for the player's own reflection.

**Syntax and runtime errors, shown kindly.** Moth translates the error, then the line number lights up in the editor gutter.
- A catalogue of ~30 common errors maps the raw message to plain words. Examples:
  - `NameError: name 'nme' is not defined` → "Line 2 mentions `nme`, but nothing by that name exists yet. A typo of `name`?"
  - `[: : integer expression expected` → "The `[` test expected a number but got an empty value. Is the variable spelled the same everywhere?"
  - `syntax error near unexpected token 'fi'` → "bash reached `fi` without a `then`. Every `if` needs `; then`."
- **Blank detection:** if the code still contains `___`, Moth just says "You still have a blank on line 3" instead of showing a scary NameError or "command not found".
- **The raw error is always one keypress away** ("Show the Terminal's exact words"). Over the chapters Moth's translations get shorter. That fading scaffold sets up Ch6, where reading raw errors *is* the lesson.
- **Infinite loops:** after the timeout, the Terminal cuts the chant short with "Your spell was still chanting after 2 seconds. Does your loop ever stop?"

**Skipping when stuck**
- After rung 3 has been viewed, or after 10 minutes at an altar, Cole offers **`:skip`**. A ghostly Pell-bridge spans the obstacle and the altar is marked *unlit* on `:map`.
- After a skip, the reference solution is shown with a line-by-line annotation by Pell. The player can leave it or retype it ("trace it") for half XP.
- Skipped altars can be relit any time. Lighting all of them in a chapter gives a cosmetic (a lantern hat). The story never locks.
- **Bosses:** each phase can be skipped the same way. The boss fight still concludes, and the payoff scene plays in full. Nobody misses the ending because of one tricky loop.

**Mastery without pressure.** Solving an altar in *both* languages earns a Bilingual star. Both drafts are saved per language, so switching tabs never loses work.

---

## 7. Post-MVP Outline (Chapters 4-7)

**Ch4 - The Foundry of Calls.** In a forge-city of nested workshops, Wren learns functions in depth: parameters and defaults, return values vs printing, scope, `local` and return codes in bash, and a gentle taste of recursion. **Boss: the Echo Hydra.** Each head calls another head, and you must find the base case before the stack overflows the arena.

**Ch5 - The Stream Sea.** An archipelago linked by flowing text-currents. The topics are line-by-line processing, `split`/`join`, CSV, string methods, and the bash text toolkit: `cut`, `tr`, `sed`, `awk`, here-docs. **Boss: the Leviathan of Logs.** Parse and summarize a 2,000-line log while the beast surfaces between phases.

**Ch6 - The Stacktrace Caverns.** Moth's homeland, and Moth's chapter. Moth's translations fall away and Wren reads raw tracebacks. The topics are `try/except`, raising errors, exit codes, `set -euo pipefail`, `set -x`, print-debugging, and assertions. **Boss: the Heisenbug.** It changes behaviour when observed, so you beat it by adding logging rather than by staring.

**Ch7 - Rootholm.** The capital, and the Terminal itself. The topics are classes and objects, modules, `sys.argv`/`argparse`, bash scripts with `$1`/`$@` and shebangs, and building small tools that compose with pipes. **Boss: the Clockwork Herald,** a bureaucratic automaton defeated by writing a real CLI tool that its own clerks then use.

**Final boss - Archscribe Morrow at the Hollow (`/dev/null`).** A multi-stage finale that reuses every chapter's skill. Morrow's argument is "every program with lines has bugs." The last phase answers it: Wren writes a **test suite** that proves the restoration spell works. It is not perfect, but it is *tested and good enough*. Morrow, shown that code can be trusted without being empty, lays down the delete key. Pell's full name, and Shellmarch's, are written back into the Source. Wren becomes the first new Keeper of the Modal Order in a century.

---

## 8. Alternative Title Candidates

1. **Home Row**
2. **The Blinking Oracle**
3. **Hello, Null**
4. **Spellcursor**
5. **Escape the Hollow**

*(Working title remains **CodeRogue**.)*
