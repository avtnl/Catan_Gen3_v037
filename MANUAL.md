# Configuration manual (Gen3 v035)

Most day-to-day experiments are controlled in two places:

1. **`core/constants.py`** — global flags (load save/map, human seats, victory points, dig-in UI, …)
2. **`Game._initialize_players()`** in **`core/game.py`** — who sits where and which **initial placement algorithm** each AI uses

After editing either file, **restart the game** (`python main.py`). Constants are read at import / game construction time.

Also see the short project overview in [README.md](README.md) (or [README_NEW.md](README_NEW.md) if you have not promoted it yet).

---

## Quick start recipes

| Goal | What to set |
|------|-------------|
| Normal new game | `LOAD_GAME = False`, `LOAD_PLAYBOARD = False` |
| Resume a mid-game save | `LOAD_GAME = True`, set `SAVED_GAME = "…"` to a file in the project folder |
| Fixed map every run | `LOAD_PLAYBOARD = True`, set `SAVED_PLAYBOARD` to a `PlayBoard…` / `Playboard…` file |
| Fair play (hide AI dig-in) | `CHECK_MODE = False` |
| Dig-in / debug panels | `CHECK_MODE = True` |
| Human is White (seat 3) | `HUMAN_PLAYER = True`, `HP_ID = [3]` |
| All AI (no human) | `HUMAN_PLAYER = False` (and usually `HP_ID = []`) |
| Win at 10 VP | `VICTORY = 10` (default) |

---

## `core/constants.py` — flags that matter now

### Board and game start

#### `LOAD_PLAYBOARD` / `SAVED_PLAYBOARD`

- **When `LOAD_PLAYBOARD` is `True`:** the board is loaded from `SAVED_PLAYBOARD` at board creation (fixed tiles/ports), instead of a pure random base board.
- File is typically a playboard text file in the project root (e.g. `PlayBoard 08_Apr_2026_13_33_06.txt`).
- This is **map only**, not a full mid-game resume (no settlements/hands from a Saved_Game).
- Board Settings in the UI can still change boards after start.

#### `LOAD_GAME` / `SAVED_GAME`

- **Cold boot only** (`python main.py`): if `LOAD_GAME` is `True`, Gen3 loads the full save named by `SAVED_GAME`, **skips Initial Placement**, and continues at the saved round/turn.
- File must be a Gen3 **`CatanSavedGame`** JSON (`.txt` created by `Game.save_game()`, e.g. `Saved_Game_…_EndRound8.txt` or `…_R1T1.txt`).
- Put the file in the project folder (or pass a path that can be found from the working directory / project root).
- If the file is missing or invalid, the game **falls back to Initial Placement** and prints a warning.
- **New Game** and Settings “end session” always start a **fresh** game and **ignore** `LOAD_GAME` (so you do not get stuck reloading the same save).
- Do **not** set both “I want a random new IP” and `LOAD_GAME=True` unless you intend to resume.

**Practical tip:** for a normal play session use  
`LOAD_GAME = False` and `LOAD_PLAYBOARD = False` (or True only if you want a fixed map).

---

### Human player

#### `HUMAN_PLAYER`

- `True`: at least one seat is human (controlled by `HP_ID`).
- `False`: all seats are treated as AI for human-input routing.

#### `HP_ID`

- List of player ids that are human, e.g. `[3]` → player 3 (White with the default seat table).
- Must match an `id_` used in `_initialize_players()` (see below).
- Multi-human is reserved for the future; today one id is the usual setup.

---

### Rules / dig-in

#### `VICTORY`

- Points required to win (standard **10**).
- Used by the victory logic (`core/victory.py` and related checks).

#### `CHECK_MODE`

- `False` (**fair play**): hide dig-in chrome (e.g. Execution Debug panel, AI hand leaks, detailed opponent DCard dig-in, some Event detail).
- `True` (**dig-in**): full debug UI for development and analysis.
- Human still sees their own information appropriately either way.

---

### Player count (used, but not fully flexible yet)

#### `NUM_PLAYERS`

- **Used** (Initial Placement sequencing and some timing helpers).
- Intended range: **2–4**.
- **Important:** `_initialize_players()` currently always creates **four** seats (Blue/Red/White/Orange). Changing `NUM_PLAYERS` alone does **not** automatically resize that list. Keep `NUM_PLAYERS = 4` unless you also edit player construction.

---

## Reserved constants (defined for future use — not fully wired)

These exist in `core/constants.py` so future features can plug in without inventing new names. **Changing them today has little or no effect on live play:**

| Constant | Intended future role |
|----------|----------------------|
| `INIT_HP` | Extra human-init / operator flow |
| `GAME_MAX_ROUND` | Cap game length / forced stop |
| `DICEROLL_SET_TF` | Use a fixed dice-roll script instead of random dice |
| `NAME_DR_FILE` | Filename for that dice-roll script |
| `NO_GUI_AT_ALL_TF` | Headless / no-window batch runs (log names already anticipate this) |

Do not rely on them for experiments until they are documented as “active.”

---

## Player seats and initial placement AI — `core/game.py`

### Where to edit

Open **`core/game.py`** and find:

```text
def _initialize_players(self) -> List[Player]:
```

Each seat is created roughly like:

```python
Player(
    id_=2,
    color=PlayerColor.RED.color_name,
    sequence=2,
    is_human=(HUMAN_PLAYER and 2 in HP_ID),
    initial_placement_algorithm=3,
    human_like_placement=False,
)
```

### Main knob for AI placement: `initial_placement_algorithm`

| Id | Meaning (Gen3) |
|----|----------------|
| **1** | Max pips (no port preference) |
| **2** | Max pips + ports |
| **3** | Five weighted strategies (balanced, wood/brick, wheat/ore, …) |
| **4** | Markov-style placement evaluator |
| **5** | Expected-Hand feasibility timing |

Only non-human seats use this for **Initial Placement**. The human seat’s algorithm id is largely irrelevant for placement clicks.

Optional: `human_like_placement=True` → pick randomly among strong top spots (less “always perfect”).

Implementations live in `core/algorithms_initial_placement.py`.

### `id_`, `color`, and `sequence` — keep them consistent

Today these three should stay **aligned** for each seat, for example:

| `id_` | Default color | `sequence` |
|-------|----------------|------------|
| 1 | Blue | 1 |
| 2 | Red | 2 |
| 3 | White | 3 |
| 4 | Orange | 4 |

**The code does not fully validate** that `id_`, color, and `sequence` form a perfect circle (e.g. you could theoretically set mismatched values). For predictable play and correct `HP_ID` targeting:

- Keep **`id_ == sequence`** for standard 4-player setup.
- Keep **colors unique** and matching the seat you mean on the scoreboard.
- Point **`HP_ID`** at the correct **`id_`**, not “third in the list” if you reorder constructors.

Changing only the algorithm ids (1–5) is the usual experiment; leave id/color/sequence alone unless you know you need a custom seat map.

### Interaction with `LOAD_GAME`

If you load a **Saved_Game**, player types, colors, and algorithms come from the **save file**, not from a re-run of a customized `_initialize_players()` for that session’s mid-game state. Seat setup in `_initialize_players()` mainly affects **new** games (and the shell created before load). For resume testing, edit **`SAVED_GAME`**, not only algorithms.

---

## Suggested experiment workflow

1. Set `LOAD_GAME = False` for a clean start (or `True` + a known save for resume tests).
2. Set `HUMAN_PLAYER` / `HP_ID` for who you control.
3. Set each AI’s `initial_placement_algorithm` in `_initialize_players()`.
4. Optionally set `CHECK_MODE` for dig-in.
5. Restart: `python main.py`.

---

## Related files

| Topic | Location |
|-------|----------|
| Constants | `core/constants.py` |
| Seat / IP algorithm | `core/game.py` → `_initialize_players()` |
| IP algorithm implementations | `core/algorithms_initial_placement.py` |
| Boot load path | `main.py` (`try_load_game_at_boot`, `_start_session`) |
| Fair-play dig-in gates | `core/debug_mode.py` |
| Victory points | `core/victory.py` |
| Project overview | `README.md` / `README_NEW.md` |
