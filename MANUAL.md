# Configuration manual (Gen3 v037)

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
- New saves go under **`saved_games/`**. For `SAVED_GAME`, a bare basename is resolved there first, then the project root (legacy), then cwd / `SAVE_PATH`.
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

#### `RCARD_MEMORY_OPPONENTS`

- Controls how much **public opponent RCard evidence** the AI / Strategy-Engine may treat as remembered (belief), via `ResourceCardDashboard.resource_production_game_player_view`.
- **`"all"`** (default): full cumulative viewer→viewed table (previous behaviour).
- **`1` … `4`**: belief = **current view − view from N completed rounds ago** (lag ring updated at each end-of-round). With 4 seats, `2` ≈ last 8 player-turns of public production evidence.
- Dig / `CHECK_MODE` still use **truth** hands on `Player.rcards`; this flag does not redact Check-Mode.
- Helpers: `Game.get_rcard_player_view_memory()`, `core/rcard_view_memory.py`.
- **Beat-risk (settle / contested road):** when `1..4`, opponent Expected-Hand ETAs for race/spoiler threats use the **memory belief hand** (not god-view). Wired in portfolio timing, sticky settle-risk refresh, road-path scoring, and `risk_assessment.opponent_contested_road_eta`. `"all"` keeps truth hands for those EH calls.

#### `REACHABILITY_MAPS` / `core/player_reachability.py`

Per-player Gen2-style **path / pathlength / real_distance** matrices (67×67 on `Player`, horizon ≥5 → sentinel `99`). Plan: **`docs/player_reachability_maps_plan.md`** (**WP-R0–R6 Done**).

| Flag / behaviour | Meaning |
|------------------|---------|
| **`REACHABILITY_MAPS=True`** (default) | Maintain maps for AI seats; Dig can rebuild human seats via `ensure_dig_seat_maps` |
| Seed | Once at `Game.begin_execution_turn` (post-IP); **`load_game`** dirties seats and rebuilds if already in Execution |
| Updates | `notify_road_built` / `notify_settlement_built` via sticky structure/road flags (paid + free TFR; v1 = full rebuild) |
| Queries | `remaining_roads_to_target`, `path_to_target`, `sc_hop_distance` — map-first in outlook/risk/min-cover/portfolio/sticky/planner with BFS fallback |
| Dig / Show | Scrub / Show-on call `ensure_dig_row_reachability`; Show keeps seat-matrix radii, optional d=3 **+2px** via `path_distance`; stamps `map_dist`; **no road overlay yet** |
| Constraint | Maps never hard-exclude `new_settlement_spots` candidacy (Missing_S) |
| Tests | `tests/test_player_reachability_*.py` (+ `test_pln_show_radius_p1`, Missing_S) |

#### `WAY_NEED_CONSIDER_HAND_DEFAULT` / `core/way_resource_need.py`

Façade for **Player One–style** mid-game Victory-Way RCard need (CSV → residual S/C/R/DC → need vector). Plan: **`docs/way_resource_need_plan.md`** (WP0–WP6 Done).

| Flag / arg | Meaning |
|------------|---------|
| **`WAY_NEED_CONSIDER_HAND_DEFAULT`** | Default when `consider_hand` omitted (**`False`**) |
| **`consider_hand=False`** | Structure residual only (ignore hand) — Dig / whole-way mass |
| **`consider_hand=True`** | Subtract hand: **self = truth**; **opponent = `RCARD_MEMORY_OPPONENTS` belief** |
| **`memory_rounds=`** | Optional override of memory window for opponent belief |
| **`path_distance_for_next_settle=d`** | Attaches per-target `settlement_Nr` need in `meta["next_settle"]`; does **not** rewrite whole-way `req_roads` |

- Whole-way roads: **Proposal A** (playboard min-road cover). Per-target: `next_settle_path_need_vector(d)` ≡ EH `settlement_Nr` (d=3 = d=2 + one road package).
- Dig residual (`strategy_way_residual`) and portfolio costing call this façade; EH search stays in `resource_time_estimator` / `strategy_timing`.
- **Do not** feed `need_after_hand` into EH together with a non-empty `current_hand` (double-subtract).

#### `MG` vs `MGLOG` (do not confuse)

| Constant | Default | Purpose | Output |
|----------|---------|---------|--------|
| **`MG`** | **`False`** | Verbose **debug / code analysis** (Gen2-style diagnostic lines). Not for re-play. Keep off in normal play and batch. | `FILENAME_MG` (`*_MG.txt`) and related sinks under the usual log location |
| **`MGLOG`** | **`True`** | Ordered **CSV event timeline** for analysis and **GUI re-play** (no Strategy-Engine). Same hooks for GUI and headless. | Single game: `FILENAME_MGLOG` (`*_MGlog.csv`). Batch: **`batch_dir/g00N/mglog.csv`**, path also in that game’s **`result.json`** as **`mglog_path`** |

**Re-play contract:** rebuild board/scoreboard/DCards from **playboard file + full `mglog.csv` from game start (IP→end)** — **not** from a mid-game `Saved_Game`. No fair-play redaction in MGlog (hands, steal types, exact DCard types). Logging: `docs/MGlog_implementation_plan.md`. Offline endgame tables: `py -3.13 scripts/mglog_stats.py --mglog …`. Operator smoke: `py -3.13 scripts/smoke_mglog_m8.py`. Optional live Game Over panel from MGlog: **`MGLOG_STATS_ON_GAME_OVER = True`** (default **False** = live ledger stats; falls back to live if the CSV is missing). **GUI re-play:** see **[MGlog re-play GUI](#mglog-re-play-gui--replay_catan_gamepy)** below.

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
| `DICEROLL_SET_TF` | Use a fixed dice-roll script instead of random dice |
| `NAME_DR_FILE` | Filename for that dice-roll script |

---

## Headless single game (Phase A) — `run_headless.py`

Lab mode: run **one** all-AI match without the interactive pygame loop (Initial Placement → Execution → terminal). Uses the same core APIs as Play / Continue (`ai_roll_to_preview`, `continue_ai_execution_turn`) with a `NullGui`.

### Required / recommended flags in `core/constants.py`

| Constant | Headless recipe |
|----------|-----------------|
| `HUMAN_PLAYER` | **`False`** |
| `HP_ID` | **`[]`** |
| `NO_GUI_AT_ALL_TF` | **Operator-owned (no in-process override).** **`True`** → `run_headless` only (mute + quiet digin); **exits 2** if False. **`False`** → `main.py` / `replay_catan_game.py` (GUI + sounds); both **exit 2** if True (red error). Flip the flag when switching lab ↔ interactive. |
| `GAME_MAX_ROUND` | Cap when no winner (e.g. `50`); CLI can override |
| `LOAD_PLAYBOARD` / `SAVED_PLAYBOARD` | Optional fixed map for reproducibility |
| `LOAD_GAME` | **`False`** for a fresh game |

Interactive product path remains:

```bash
python main.py
```

### Run

```bash
# From project root (Windows: py -3.13 recommended)
py -3.13 run_headless.py

# Smoke / short lab run
py -3.13 run_headless.py --max-round 3 --max-steps 80

# Custom result path, quieter logs
py -3.13 run_headless.py --result-path batch_runs/smoke/result.json -q
```

Useful CLI flags: `--sequence`, `--max-round`, `--max-steps`, `--result-path`, `--no-result-file`, `--allow-human` (not recommended).

**Phase C2 lab flags** (matched dice / reassess arms — see below): `--seed`, `--seed-base`, `--dice-from-batch`, `--explicit-recalc`, `--arm`, `--arm-name`, **`--perf on|off`**.

**Phase L LA soft bias** (lab only; product default `LA_SOFT_BIAS_MODE=off`): `--la-soft-bias off|early|mid|late`. Soft-boosts LA Victory-Way rank + tips knight hold→play when the timing gate is open. Experiment runner: `scripts/run_la_soft_bias_experiment.py` (n=25×3 early/mid/late on `lib_ip2` dice; **reuse** `batch_runs/product_244` as control — no new n=25 baseline). See `docs/PhaseL_la_soft_bias_experiment.md`.

**Phase L L3b LR backtest** (offline, no SE change): after a batch with `la_lr_probe.jsonl`,  
`py -3.13 scripts/analyze_la_lr_backtest.py --batch-dir batch_runs/<probe_batch>`  
writes `la_lr_backtest_lr_report.json` (sample-time give-up vs claim; θ curve + operating point). Use `--special la` for L3a.

**Phase L L6 LA give-up → L2** (flag-gated):  
`LA_GIVEUP_L2_ENABLED` + profile `safe` θ=0.6 D=1 latch. Wired via `core/la_giveup_l2.py`.  
**Domain A:** `Playboard_LA_lab_WhOSh_07_Aug_2026.txt`.  
Freeze: `docs/PhaseL_LA_theta_lock.md`.  
`py -3.13 scripts/verify_la_theta_freeze.py --batch-dir batch_runs/la_lab_whosh_n100`.

**Phase L L6 LR give-up → L2** (lab default **on**):  
`LR_GIVEUP_L2_ENABLED=True`, profile `safe` θ=0.75 D=1 latch. Wired via `core/lr_giveup_l2.py`.  
**Domain C:** `Playboard_LR_lab_WdB_07_Aug_2026.txt`.  
Freeze: `docs/PhaseL_LR_theta_lock.md`.  
`py -3.13 scripts/verify_lr_theta_freeze.py --batch-dir batch_runs/lr_lab_wdb_n100`.

**Live give-up fire logging** (when L6 fires):  
- Probe JSONL row with `event=la_giveup_fire` or `lr_giveup_fire` + `giveup` block (score, θ, way_id, …).  
- Offline L2/L3 (`iter_probe_rows`) **skips** fire rows by default so samples are not double-counted.  
- Per-game `result.json`: `la_giveup_fires_total`, `lr_giveup_fires_total`, `*_by_seat`, `giveup_fires` list.  
- `batch_summary.json`: batch totals + `games_with_*_giveup_fire`.

**Give-up escape (WP0–WP3)** (`GIVEUP_ESCAPE_ENABLED=True`, `GIVEUP_FORCE_DIVERT=True` lab defaults):  
After LA/LR give-up fire, set `player.specials_dead_episode` and **filter portfolio** away from ways that still need the dead special (hard filter; soft demote if none left).  
**WP2.1:** forced adopt of filtered winner (`reason=specials_dead_escape`) so keep-abstract cannot restore the dead-special way.  
**WP3:** sticky gate (no re-lock of dead-special ways) + force S5.5 divert with episode kill flags (works even when S5.5 assess is soft).  
Module: `core/specials_dead_episode.py`. Plan: `docs/PhaseL_giveup_escape_plan.md`.  
Set both flags **False** for matched control that only measures raw L6 re-lock.

**Partial Victory-Way salvage (S0–S3):**  
`GIVEUP_SALVAGE_PARTIAL=False` (default; escape path still runs T1/T2 when `GIVEUP_ESCAPE_ENABLED`).  
S1: `strip_components` / `rescore_way_residual`. S2: T1 eval expand (`GIVEUP_SALVAGE_T1_EXPAND_N`).  
**S3:** after specials-dead filter, T1 tag or T2 residual rank + force adopt (`salvage_t1_nonspecial` / `salvage_t2_residual`); direction gets `partial_plan` / `ignored_components` on T2.  
**S4 sticky/partial (implemented):** direction + sticky carry `partial_plan` / `ignored_components`; LR/LA projects are not re-armed while those components are ignored.  
If a seat escapes dead specials then re-acquires LR/LA need under the same episode, **bounce-guard** hardens direction, clears blocked sticky, and logs once:  
`S4_APPLIED bounce_guard: …` (`maybe_apply_s4_bounce_guard` / alias `maybe_signal_s4_needed`).  
**S5:** no legal road/settle *targets* (geometry, not hand) → `roads_expand` / `settles_expand` dead; salvage T1/T2 treat them like other dead components (`roads_expand` also kills LR for salvage).  
**S5b:** `settles_expand` is **not** dead merely because there is no settle target *now* while roads can still expand (`settles_reason=deferred_need_roads`). Dead only on settlement piece cap or (no settle **and** roads closed: `no_settle_and_roads_closed`). Dig: `settles_raw_empty`, `roads_closed`. Impl `PARTIAL_WAY_SALVAGE_S5b_v1`. Plan: `docs/PhaseL_S5b_settles_expand_gate_plan.md`.  
**G5 validated** (mild n=20): `batch_runs/lr_lab_mild_s5b_g5_n20` — r1 settles-only adopts 80→0; salvage volume −68%; LR fires still present; dig in plan §6.1 / `TO_11Aug_Smoke2.txt`.  
**G6 dig:** `result.json` tracks `settles_deferred_scans` vs `settles_dead_scans` (+ first-per-seat events); `scripts/dig_salvage_s7.py` prints **S5b G6 expansion settles dig**.  
**S6:** VP-DCard component dead if DCard **deck empty** (public stack length 0) or sticky/preferred way’s VP-card need already met by own held VPs — **never** god-view deck composition.  
**S7 dig fields:** each T1/T2 (or specials-dead escape) force-adopt is counted once (deduped by seat/tier/way/dead set):  
- Probe JSONL: `event=salvage_adopt` + `salvage` block (`salvage_mode`, `template_way_id`, `ignored_specials`, `residual_eta`, `partial_plan`, …). Offline L2/L3 iterators **skip** these dig rows by default.  
- `result.json`: `salvage_t1_adopts_total`, `salvage_t2_adopts_total`, `salvage_adopts_total`, `*_by_seat`, `salvage_adopts` event list.  
- `batch_summary.json`: seat/game aggregates + `salvage_dig` (fire→adopt rates; go flag `go_criterion_salvage_ge_60pct_of_fire`).  
- Dig CLI: `py -3.13 scripts/dig_salvage_s7.py batch_runs/<batch_dir>`.  

**S7a dig correctness** (pre-adopt way + switch kind; plan `docs/PhaseL_S7a_abstract_way_before_plan.md`):  
- **Before-id resolution** (first hit wins): sticky `locked_way_id` → `strategic_direction.preferred_way_id` / `way_id` → report preferred → last direction → `ways_used_this_game[-1]` → none.  
- Per adopt: `abstract_way_before`, `abstract_way_before_source`, `way_change_kind` (`first_lock` \| `same` \| `switch` \| `unknown`), `way_changed` (**True only for `switch`**).  
- Dig KPIs / CLI: use **`games_with_salvage_switch`** / **`switch_rate_given_fire`** for real way changes; `games_with_salvage_way_change` is an alias of switch. Do **not** treat all salvage adopts as switches (`first_lock` is common when no prior way).  
- Impl: `resolve_pre_adopt_way_id`, `classify_way_change_kind` in `core/partial_way_salvage.py`; force-adopt wire in `ai_way_portfolio`.  
- **D7 validated** (mild n=5): `batch_runs/lr_lab_mild_s7a_d7_n5` — switch/same/first_lock split live; snapshot `docs/PhaseL_S7a_D7_validation.md`.  

Module: `core/partial_way_salvage.py`. Spec: `docs/PhaseL_partial_way_salvage_plan.md`.

**Console verbosity** (`core.console`, headless only for now):

| Flag | Level | What you see |
|------|--------|----------------|
| `-q` / `--quiet` | WARN | Warnings + errors (+ stuck/error finish) |
| (default) | INFO | Flags, start, IP done, progress every N steps, result |
| `-v` / `--verbose` | DEBUG | + IP steps, roll tags |
| `--trace` | TRACE | + every continue tag |
| `--log-level LEVEL` | override | `TRACE\|DEBUG\|INFO\|WARN\|ERROR` |
| env `HEADLESS_LOG_LEVEL` | override | same names (or numeric) |

**Dig-in dumps under headless** (`core.console.digin`): with `NO_GUI_AT_ALL_TF=True` (required by `run_headless`), the worst offenders are level-gated instead of always printing:

| Message | Level (headless) |
|---------|------------------|
| `game.advance_turn executed` | DEBUG (`-v`) |
| `[Slice A/B] …` header | DEBUG; body lines TRACE (`--trace`) |
| Markov INIT candidate lines | TRACE |
| Markov precompute banners | DEBUG |
| `Loading gui_constants.py …` (import-time) | DEBUG only when headless; silent for interactive |
| `AI DCard choice/execute`, Knight/YOP/TFR/Monopoly plan+EXECUTE | DEBUG (`-v`); still needs `game.execution_debug_print_tf` |

Interactive dig-in (`advance_turn`, Slice A/B, Markov, DCard when flag on) still prints as before when `NO_GUI_AT_ALL_TF=False` (use that only for `main.py`, not headless).

### Exit codes

| Code | Meaning |
|------|---------|
| **0** | `status` is `won` or `max_round` |
| **1** | `stuck`, `error`, or runner crash |
| **2** | Misconfiguration (`NO_GUI_AT_ALL_TF=False`, or human seats without `--allow-human`) |

### Artifacts

- **`result.json`** — under `batch_runs/<timestamp>_gNNN/` by default (schema in `core/batch/result.py`)
- **CS log** — Change Strategy JSONL: global `FILENAME_CS` for single runs; see Phase C / WP-C4 for batch `cs.jsonl`
- Interactive **New Game** / Settings still ignore headless; this entry does not replace `main.py`

### Multi-game batch (Phase B) — GameManager

```bash
# N games (overrides constants.GAMES_TO_PLAY)
py -3.13 run_headless.py --games 10

# Capped games for lab smokes
py -3.13 run_headless.py --games 5 --max-round 20

# Explicit batch folder
py -3.13 run_headless.py --games 3 --batch-dir batch_runs/my_experiment
```

| Output | Location |
|--------|----------|
| Per-game `result.json` | `batch_runs/<ts>_batch/g001/result.json`, `g002/`, … |
| Per-game **MGlog** (`MGLOG=True`) | `batch_runs/<ts>_batch/g001/mglog.csv`, …; pointer **`mglog_path`** in that `result.json` |
| Per-game **playboard** (map snapshot) | `batch_runs/…/g00N/Playboard_g00N.txt` — written for **random and fixed** maps so re-play is self-contained; pointer **`playboard_path`** in `result.json` |
| Batch summary | `batch_runs/<ts>_batch/batch_summary.json` |
| **Batch CS log** (WP-C4) | `batch_runs/<ts>_batch/cs.jsonl` |
| **CS-annotated MGlog** (offline) | `batch_runs/<ts>_batch/cs_annot/g00N/mglog_cs.csv` + `manifest.json` (originals untouched) |
| **Way reassess log** (Phase C2) | `batch_runs/<ts>_batch/way_reassess.jsonl` |

**Re-play a batch game** (e.g. game 3) after a headless run:

```text
py -3.13 replay_catan_game.py --game-dir batch_runs/<run>/g003
```

`--game-dir` resolves **`mglog.csv`** and **`Playboard_g003.txt`** (or `playboard_path` / `mglog_path` from `result.json`).

Summary includes `status_counts`, `wins_by_player`, mean duration/rounds/steps, compact per-game rows, **`batch_id`**, **`cs_log_path`**, **`mglog_path`** (when present), and (Phase C2) **`arm`** / **`dice_hash`** compact fields when present.

Batch exit code **0** only if no game finished `stuck` or `error` (wins and `max_round` are OK).

Constant: **`GAMES_TO_PLAY`** in `core/constants.py` (default `1`); CLI `--games` overrides.

### Strategy probe (Phase C) — CS setbacks / way / target

Offline lab tool: read the **Change-Strategy (CS)** JSONL stream and report **ETA setbacks**, **Victory-Way changes**, **sticky target changes**, and **policy anomalies**. Does **not** change Best-Action or the live game.

**Plan / taxonomy:** `docs/PhaseC_cs_eta_setback_analyzer_plan.md`  
**Code:** `core/batch/strategy_change_taxonomy.py`, `core/batch/cs_setback_analyzer.py`, `scripts/analyze_cs_setbacks.py`

#### Run after a batch

```bash
# Prefer batch folder (uses batch cs.jsonl + game_id filter)
py -3.13 scripts/analyze_cs_setbacks.py --batch-dir batch_runs/<ts>_batch

# Explicit CS file
py -3.13 scripts/analyze_cs_setbacks.py --cs Catan01Aug2026_v1_CS.txt -o report.json

# Summary only (no JSON write)
py -3.13 scripts/analyze_cs_setbacks.py --batch-dir batch_runs/<ts>_batch --no-write
```

| Flag | Meaning |
|------|---------|
| `--batch-dir` | Scope to that batch’s `game_id`s; default out = `…/strategy_probe_report.json`; prefer `cs.jsonl` |
| `--cs` | CS JSONL path (default: `FILENAME_CS` in `constants.py`, unless batch overrides) |
| `--threshold` | Setback when `delta_turns ≥ thr` (default **1.0**) |
| `--game-ids` | Comma-separated filter (optional) |
| `--max-events` | Cap events per probe list in the JSON report |
| `-o` / `--out` | Report path |
| `--no-write` | Console one-pager only |
| `-q` | Quiet (still writes report unless `--no-write`) |

#### What the report contains

| Probe | Detects | Class examples |
|-------|---------|----------------|
| **SETBACK** | ETA rose (`delta_turns ≥ thr`) | `robber`, `discard_7`, `monopoly`, `way_switch`, `trade_reprice`, `build_spent`, `estimator_jump`, `unknown` |
| **WAY** | Victory-Way / sticky way change | `first_lock`, `target_blocked`, `race_settle` / `race_road`, `offway_opportunity`, `way_kill`, `specials_shock`, `soft_eta_switch`, `hard_invalid`, `unknown` |
| **TARGET** | Sticky rec-target change | `achieve_settle` / `achieve_city` / `achieve_component`, block/race, `same_way_rerank`, `way_switch_cascade`, … |
| **ANOMALY** | Policy smells | `anomaly_way_change_on_achieve`, `anomaly_way_change_hand_only`, `anomaly_q2_way_change`, `anomaly_target_thrash` |

**Policy expectation:** successfully completing a target/component **should** change sticky target; it **should not by itself** change Victory-Way → counted as `anomaly_way_change_on_achieve`.

Console prints counts + top classes + worst game. Full detail: **`strategy_probe_report.json`** (`events_setback` / `events_way` / `events_target` / `events_anomaly`, `per_game`, `summary`).

#### CS log locations

| Mode | CS file |
|------|---------|
| Interactive / single headless (no batch override) | Project root `FILENAME_CS` (e.g. `Catan01Aug2026_v1_CS.txt`) |
| **GameManager batch** (`--games N`) | **`batch_runs/<ts>_batch/cs.jsonl`** (all games in that batch) |

CS schema **v2** (additive): sticky snapshot fields (`sticky_way_id`, `sticky_target_id`, `way_changed`, `target_changed`, `way_switch_cause`, `target_switch_cause`, `achieve_kind`, `batch_id`, …). Older v1 lines still load; classes then use heuristics with lower confidence.

Writer: every strategy history sample still appends a CS line (`core/strategy_cs_log.py`); sticky apply publishes `player.last_sticky_meta` for high-confidence causes.

#### Related tests

```bash
py -3.13 -m pytest tests/test_strategy_change_taxonomy_c0.py tests/test_strategy_cs_schema_v2_c1.py tests/test_cs_strategy_probe_c2.py tests/test_analyze_cs_setbacks_cli_c3.py tests/test_batch_cs_path_c4.py -q
```

#### Validation snapshot (WP-C6)

Example lab run (2026-08-05): 3-game batch → 805 CS v2 rows → probe  
`batch_runs/phase_c_wp_c6_validation/`. Write-up: **`docs/PhaseC_wp_c6_validation.md`**.

### CS → MGlog annotation (offline dig labels)

After a batch with **CS** (`cs.jsonl`) **and** per-game **MGlog** (`g00N/mglog.csv`), you can stamp **annotated copies** with multi-label CS-probe codes for later dig / re-play filters. **Original batch files stay read-only.**

**Plan:** `docs/CS_mglog_annotate_plan.md`  
**Code:** `core/batch/cs_mglog_codes.py`, `core/batch/cs_interest.py`, `core/batch/cs_mglog_annotate.py`, `scripts/annotate_mglog_cs.py`

#### Columns (on annotated CSV only)

| Column | Meaning |
|--------|---------|
| **`cs_tf`** | `1` if this row has any CS interest tag (else empty) |
| **`cs_cat1`** | Coarse multi-label ints, `;`-joined (e.g. `2;3`) — first_lock / setback / way_change / target_change / anomaly |
| **`cs_cat2`** | Fine multi-label ints (setback/way/target/anomaly class codes; **11** = way/target first_lock only) |

Attachment **Policy B:** codes land on the **last MGlog event** of that seat-turn `(round, turn, player_id)`. Same classifiers as `analyze_cs_setbacks.py` (setback threshold default **1.0**, thrash default **3**).

#### Run

```bash
# Default out: batch_runs/<ts>_batch/cs_annot/
py -3.13 scripts/annotate_mglog_cs.py --batch-dir batch_runs/<ts>_batch

py -3.13 scripts/annotate_mglog_cs.py --batch-dir batch_runs/<ts>_batch --out-dir path/to/cs_annot
py -3.13 scripts/annotate_mglog_cs.py --batch-dir batch_runs/<ts>_batch --game-ids <id1>,<id2> -q
```

| Output | Path |
|--------|------|
| Manifest | `…/cs_annot/manifest.json` (thresholds, games annotated/skipped, paths) |
| Annotated MGlog | `…/cs_annot/g00N/mglog_cs.csv` |

Games without `mglog.csv` are **skipped** (listed in the manifest); CS-only batches produce a valid empty annotate. Requires **`MGLOG=True`** during the batch if you want dig labels later.

**Need both artifacts:** batch `cs.jsonl` (always for GameManager) + per-game MGlog (`mglog_path` in `result.json` when `MGLOG` on).

#### Related tests

```bash
py -3.13 -m pytest tests/test_cs_mglog_codes_w0.py tests/test_cs_interest_w1.py tests/test_cs_mglog_annotate_w2w3.py tests/test_annotate_mglog_cs_cli_w4.py tests/test_cs_mglog_annotate_w5_smoke.py -q
```

Lab smoke batch with CS + MGlog: `batch_runs/mglog_replay_n5` (optional; test skips if absent).

#### SE Dig (re-play enriched MGlog)

After annotate (`cs_annot/g00N/mglog_cs.csv` dense). Attach prefers CS `reason`→MGlog event (e.g. buy → `buy_dcard`); same-seat-turn PLN backfill so Dig before the attach row still shows plan:



```bash
py -3.13 replay_catan_game.py --playboard <PlayBoard.txt> --dig \
  --mglog-cs batch_runs/<batch>/cs_annot/g001/mglog_cs.csv --cat2 311,312

# Or with game-dir (prefers cs_annot when --dig):
py -3.13 replay_catan_game.py --dig --game-dir batch_runs/<batch>/g001 --cat1 2,3
```

| Control | Role |
|---------|------|
| **cat1 / cat2** (above dice) | XOR filter lists; typing one clears the other |
| **Previous / Next** (below dice) | Jump to previous/next probe hit |
| **SE Dig panel** (right) | **STR · PLN1 · PLN2 · ACT · WHY1 · MORE** (WHY2 removed) |
| **PLN1** | Way residual + Now/Word + DC `L\|M\|H · focus LA\|VP\|LA/VP\|LR` |
| **PLN2** | S/C catalog table (New/target/ETA/Dist/Risk/Δt/Why); SE pick in **red** |
| **Show** (above MORE, PLN2 only) | Circles: turn-player S d=2/3; opp rings if risk M/H; radii own **8** then **12/16/20** (port-dot base 5) |
| **Continue** (`>`) | Step rows; field colors red/blue (this row / earlier same seat-turn) |
| Other nav | Black text; optional `(*)` R/T last-update refs |

Normal re-play (no `--dig`) still uses original `mglog.csv` only.

**PLN1/PLN2 need a fresh batch** (old `mglog_replay_n5` lacks `plan_catalog` / `pln1_*`). After code with `PLAN_SNAPSHOT=on` (default):

```bash
py -3.13 -m pytest tests/test_pln1_pln2_dig.py tests/test_pln1_p5.py tests/test_pln2_catalog_p2.py tests/test_pln2_table_p4.py tests/test_pln_show_p3.py tests/test_pln_show_radius_p1.py tests/test_pln_words_p6.py tests/test_strategy_plan_snapshot_wp5.py -q

py -3.13 run_headless.py --games 5 --batch-dir batch_runs/mglog_replay_n5_pln --arm product
py -3.13 scripts/annotate_mglog_cs.py --batch-dir batch_runs/mglog_replay_n5_pln
# Then set NO_GUI_AT_ALL_TF=False in core/constants.py before dig GUI:
py -3.13 replay_catan_game.py --dig --game-dir batch_runs/mglog_replay_n5_pln/g001
```

Design: `docs/changes_PLAN_v1_impl.md` · coding: `docs/changes_PLAN_v2_coding.md`.

### Matched dice + Victory-Way reassess (Phase C2)

Lab experiment: replay the **same playboard + same ordered dice sequence** under different **per-seat L2 / way-reassess policies**, log alt-way compares, and measure first-way fit.

**Product default (new games):** AI + human seats **`[0]`** — L2 only via closed-table **a/b/c** gates (same lean posture as S142 triggers off). Way pick: **`EXPLICIT_WAY_PICK=sticky`**. Opt-in schedule **`[2, [4, 4]]`**: **`--arm product`** / **`setback_every4`** / constant `EXPLICIT_142_RECALC_SCHEDULE_SETBACK_EVERY4`. Lab a/b/c baseline: **`--arm control`** (or **`abc`**).

**Plan:** `docs/PhaseC2_way_reassess_experiment_plan.md`  
**Code spine:** `core/explicit_142_recalc.py`, `core/strategy_explicit_recalc.py`, `core/dice_script.py`, `core/way_reassess_log.py`, `core/first_way_fit.py`, `core/batch/arm_config.py`, `core/batch/way_reassess_analyzer.py`

#### Constants (`core/constants.py`)

| Constant | Role | Default |
|----------|------|---------|
| `EXPLICIT_142_RECALC_PRODUCT_AI` | AI product policy | `[0]` (a/b/c only) |
| `EXPLICIT_142_RECALC_PRODUCT_HUMAN` | Human product policy | `[0]` |
| `EXPLICIT_142_RECALC_SCHEDULE_SETBACK_EVERY4` | Opt-in setback + every-4 | `[2, [4, 4]]` |
| `EXPLICIT_142_RECALC_BY_SEAT` | All-AI template (live init uses `is_human` when no CLI map) | all `[0]` |
| `EXPLICIT_RECALC_SETBACK_THR` | Code **2** ETA rise threshold (own turns) | `1.0` |
| `EXPLICIT_RECALC_EVERY_N_DEFAULT` | Bare code **4** → period n | `2` |
| `EXPLICIT_RECALC_MILESTONE_VPS` | Code **5** VP milestones | `(2, 4, 6, 8)` |
| `EXPLICIT_WAY_PICK` | `sticky` = product min-ETA-gain; `best` = lab always rank-1 | `"sticky"` |
| `LOG_WAY_COMPARE` | Write WayReassessCompare on L2 for all seats | `True` |

**Trigger codes** (OR’d; empty / `[0]` = no extra L2 beyond product P1–P3 gates):

| Code | Name | When |
|-----:|------|------|
| 0 | none | No explicit extra recalc |
| 1 | on_vp_gain | Own effective VP increased |
| 2 | on_eta_setback | Sticky ETA rose by ≥ setback thr |
| 3 | on_target_hard_invalid | Sticky target hard-invalid / blocked |
| 4 | every_n_own_turns | Form **`[4, n]`** (bare `4` → default n) |
| 5 | milestones | First cross of milestone VPs |

Examples: product **`[0]`** (a/b/c); opt-in schedule **`[2, [4, 4]]`**; dense explore **`[1, 2, 3, [4, 2]]`**.

CLI **`--explicit-recalc`** / **`--arm`** override product defaults for a run (do not require editing constants for A/B arms).

#### CLI recipes

```bash
# Record a/b/c-only library (product default / lab baseline)
py -3.13 run_headless.py --games 100 --batch-dir batch_runs/lib_ip2 --seed-base 1000 --arm control

# Opt-in [2,[4,4]] schedule on all seats (former product AI)
py -3.13 run_headless.py --games 100 --batch-dir batch_runs/product_244 --arm product

# Phase G: a/b/c vs schedule on matched dice
#   --arm control  (or abc)  vs  --arm product  (or setback_every4)

# Dual perf pack (same seat arm / dice; digs lean vs full) — ditch-S142 wall evidence
#   --perf on  = shadow/MGLOG/probes/snapshot/target-screen OFF (lean wall)
#   --perf off = digs ON (transparency). S142 drive stays off in both packs.
py -3.13 run_headless.py --games 3 --batch-dir batch_runs/ctrl_perf_off_n3 --seed-base 24082501 --arm control --perf off
py -3.13 run_headless.py --games 3 --batch-dir batch_runs/ctrl_perf_on_n3 --seed-base 24082501 --dice-from-batch batch_runs/ctrl_perf_off_n3 --arm control --perf on
# Aliases: --arm control+perf   |  --arm control+perf-off  |  --arm perf

# WP-P9: [2,[4,4]] vs sticky control on matched dice (long; ~50+ min)
py -3.13 scripts/run_wp_p9_validation.py --games 100
# Re-analyze only:
py -3.13 scripts/analyze_wp_p9.py --control batch_runs/lib_ip2 --product batch_runs/product_244

# Treat P2: replay dice library; seat 2 dense reassess
py -3.13 run_headless.py --games 100 --batch-dir batch_runs/treat_p2 \
  --dice-from-batch batch_runs/lib_ip2 --arm treat-p2

# Manual seat map (equivalent dense P2)
py -3.13 run_headless.py --games 10 --explicit-recalc 2=1,2,3,[4,2] --arm-name my_p2

# Single game with fixed seed + dice replay for sequence 1
py -3.13 run_headless.py --sequence 1 --seed 1000 \
  --dice-from-batch batch_runs/lib_ip2 --explicit-recalc 2=dense
```

| Flag | Meaning |
|------|---------|
| `--seed N` | Master RNG seed (single game, or same seed every batch game if no `--seed-base`) |
| `--seed-base N` | Batch: game *i* uses seed `N+i-1` |
| `--dice-from-batch DIR` | Replay `DIR/g00N/result.json` → `dice_rolls` (extend with true rolls past end) |
| `--explicit-recalc SEAT=SPEC` | Repeatable. SPEC: `dense`, `1,2,3,[4,2]`, `vp`, `every2`, `0`, … |
| `--arm NAME` | Preset map: `control` (all sticky), `product` / `product_ai` (`[2,[4,4]]` all seats), `treat-p2`, `treat-p3`, `treat-all` |
| `--arm-name LABEL` | Free-form label on `batch_summary` / `result.json` |

#### Batch / result artifacts (additive)

| Artifact | Content |
|----------|---------|
| `g00N/result.json` | `seed`, `dice_rolls`, `dice_count`, `dice_hash`, `explicit_142_recalc_by_seat`, `ways_used_by_seat`, `unique_ways_count_by_seat`, `way_switch_count_by_seat`, `first_way_fit_by_seat`, `arm_name` |
| `batch_summary.json` | `arm` block (name, seat map, dice_from_batch, seed_base), compact `dice_hash` / way counts |
| `way_reassess.jsonl` | Per-L2 compare: locked vs best way, ETAs, `switched`, trigger codes |
| CS row fields | `locked_way`, `best_alt_way`, `eta_locked` / `eta_alt`, `way_switched`, `first_way_fit_*` |
| `wp_p9_validation_report.json` | WP-P9 product vs sticky: wins, McNemar, renew quality, WR (from `analyze_wp_p9.py`) |
| `la_lr_probe.jsonl` | Phase L god-view LA/LR samples + live `*_giveup_fire` + S7 `salvage_adopt` dig rows (`LOG_LA_LR_PROBE`) |
| `result.json` give-up KPIs | `la_giveup_fires_total`, `lr_giveup_fires_total`, `*_by_seat`, `giveup_fires` |
| `result.json` salvage KPIs (S7) | `salvage_t1_adopts_total`, `salvage_t2_adopts_total`, `salvage_adopts_total`, `*_by_seat`, `salvage_adopts` (events include S7a `way_change_kind`, `abstract_way_before_source`) |
| `batch_summary.json` salvage dig | `salvage_dig` (fire→T1/T2 rates; S7a `games_with_salvage_switch` / `first_lock` / `switch_rate_*`), `games_with_salvage_*` |
| `la_lr_godview_la_report.json` | L2a: LA episode labels + global θ_LA (`scripts/analyze_la_lr_godview.py --special la`) |

#### WP-P9 product validation

Matched check that **shipped product** (all AI `[2,[4,4]]`, sticky way pick) beats / differs from **pure sticky** on the same dice library (`lib_ip2`).

| Step | Command / artifact |
|------|---------------------|
| Control (sticky) | Existing `batch_runs/lib_ip2` or re-record with `--arm control` |
| Product treat | `scripts/run_wp_p9_validation.py` → `batch_runs/product_244` |
| Report | `batch_runs/product_244/wp_p9_validation_report.json` + console summary |

Metrics: per-seat wins, P2 McNemar vs control, target-renew benef%/harm, way_reassess volume (all seats), policy map check, context vs prior isolations (every4, dense, …).

Dice modes: **record** (default) appends true rolls; **replay** consumes script then true-random; **finalize** truncates export to rolls actually used.

#### Analyze matched control vs treat

```bash
py -3.13 scripts/analyze_way_reassess.py \
  --control batch_runs/lib_ip2 \
  --treat batch_runs/treat_p2

# Options
#   --seat 2,3          treated seats (default: inferred from arm, else 2)
#   --match auto|dice_hash|sequence
#   -o report.json      default: <treat>/way_reassess_matched_report.json
#   --no-write          console only
```

**Primary explore metric:** treated seat `unique_ways` median often **≥ 2** (plan `explore_signal`). Secondary: switch counts, win rate, VP, `eta_gain` distribution, first-way fit.

Also still useful: `scripts/analyze_cs_setbacks.py --batch-dir batch_runs/treat_p2` for setback/thrash probes.

#### Unit tests (no 100-game run)

```bash
py -3.13 scripts/run_phase_c2_tests.py -q
# Acceptance map only (plan §9 A1–A8):
py -3.13 scripts/run_phase_c2_tests.py --acceptance -q
```

#### Dig tools (offline, after a batch)

```bash
# Dig1: locked vs best way (portfolio #1)
py -3.13 scripts/dig1_way_compare.py --control batch_runs/lib_ip2 --treat batch_runs/treat_p2

# Dig2: sticky target/roads on treat-only wins
py -3.13 scripts/dig2_sticky_path.py --control batch_runs/lib_ip2 --treat batch_runs/treat_p2

# Target renewals × explicit/product L2 triggers (join CS + way_reassess)
py -3.13 scripts/dig_target_renew_triggers.py --batch-dir batch_runs/treat_p2 --compare batch_runs/lib_ip2 --seat 2

# Explicit code volume vs wins (observational)
py -3.13 scripts/dig_trigger_attribution.py --treat batch_runs/treat_p2 --control batch_runs/lib_ip2
```

**CS schema 3** (new runs): additive fields `refresh_mode`, `refresh_mode_detail`, `l2_gate`, `explicit_trigger` / `explicit_codes`, compact `ba_action` / `ba_target_id` / `ba_label` (BA is last `current_best_action` at CS write — may lag one rescan). Older schema-2 batches still analyze via `way_reassess` join.

### Save / Phase0 cadence (lab vs dig-in)

| When | Save game | Screenshot | Phase0 auto (`auto_slow_*.json`) |
|------|-----------|------------|-----------------------------------|
| After **Initial Placement** | Yes (always) | Yes (best-effort) | — |
| After Execution rounds (mid-game) | Only if **`CHECK_MODE=True`** (every round) | With that save | — |
| **`CHECK_MODE=False`** mid-game | **No** EndRound saves (not every 5 either) | — | — |
| **Game over** | Yes (always: GUI **and** `NO_GUI_AT_ALL_TF` / headless) | Best-effort | — |
| Slow AI pipeline (≥2 s span) | — | — | Only if **`CHECK_MODE=True`** |

**Where files land (project-relative):**

| Kind | Directory | Constant |
|------|-----------|----------|
| **Saved_Game_*.txt** | `saved_games/` | `SAVED_GAMES_DIR` |
| **Phase0_AI_Baseline_*.json** | `saved_phase0_files/` | `SAVED_PHASE0_DIR` |
| Screenshots / verbose **MG** debug (`MG=True`) | `SAVE_PATH` (Documents Logs) | `SAVE_PATH` / `FILENAME_MG` |
| **MGlog** re-play CSV (`MGLOG=True`) | Project / batch `g00N/` (not mid-game Saved_Game) | `FILENAME_MGLOG` / `mglog_path` |

With **`CHECK_MODE=False`** (typical headless batch): no per-round spam, no Phase0 dumps; snapshots at **IP end** and **game over** only (`Saved_Game_*_GameOver_P*.txt`).

### Strategy refresh roadmap (performance + Q1/Q2)

Practical order (build on sticky / L0–L2; do not re-plan on pure hand noise):

| Phase | Action | Notes |
|-------|--------|--------|
| **P0** | `CHECK_MODE=False` → no Phase0 auto; **no** mid-game EndRound saves; always **IP + game over** (incl. headless) | Implemented; cuts IO |
| **P1** | **True-light L0**: only RCards/hand changed → **no L2**; single sticky-way ETA only | **WP1–WP5 done** (`build_l0_hand_strategy_report`, call-site audit, tests, spans); plan: `docs/P1_true_light_L0_plan.md`. Perf: `l0_strategy_update` + `summarize_strategy_refresh_perf` (L0 vs L2) |
| **P1+Q1** | After scan: if player can afford **settlement or city** that is **not** a component of selected Victory-Way / sticky → **L2 once** (before BA this turn is OK) | **Implemented** (`core/strategy_offway_q1.py`); plan: `docs/P1Q1_offway_structure_l2_plan.md`. Off-way **structure** only; once/turn latch |
| **P1+Q2** | Affordable **DCard** not on way: may **buy**, **no L2**; do not starve sticky city/settle or active **races** (specific road, specific settle, LA, LR, last DCards). Drawn DCard not playable same turn | **Implemented** (`core/strategy_offway_q2.py`); plan: `docs/P1Q2_offway_dcard_buy_plan.md`. Soft BA permission; never L2 |
| **P2** | Coalesce dirty flags; **one** heavy job per seat when possible | **Implemented** (`core/strategy_dirty.py` + gated flaggers). Plan: `docs/P2_turn_start_l2_dirty_flags_plan.md`. Turn-start **L0 default**; L2 only on **plan-relevant** dirt. Own Q2 alone → no L2 |
| **P3** | L2 only on: (a) need next target, (b) target blocked / race worse, (c) LA/LR shock, (d) Q1 off-way settle/city; never L2 for pure TwP/TwB/hand or off-way DCard alone | **Implemented** (`build_l2_policy_status`, reason map). Plan: `docs/P3_l2_policy_closed_table_plan.md`. Dig-in: `l2_policy.bucket` |
| **P4** | Filter 142 → top K before EH; thin fast explore | **Implemented** (`core/l2_profile.py`, prefilter in `strategy_timing`). Plan: `docs/P4_cheap_l2_top_k_plan.md`. Fast L2: abstract prefilter K=12, portfolio **stage Early3/Mid6/End9** (flat-3 retired), no Stage3/risk; full for phase0/F9. Sync/adaptive: `docs/L2_sync_transparency_shadow_plan.md` |
| **P5** | NumPy EH core; profile; optional batch/GPU later | **Implemented (v1)** `core/eh_numpy.py` + `USE_NUMPY_EH`. Plan: `docs/P5_numpy_eh_performance_plan.md`. Batch EH in rank; fallback pure Python; bench: `scripts/bench_eh.py` |

### L2 sync-first / transparency / shadow overlook (v037)

Plan: **`docs/L2_sync_transparency_shadow_plan.md`**. Target-screen research: **`docs/L2_target_screen_research_R.md`**.

| Flag (`core/constants.py`) | Role |
|----------------------------|------|
| `L2_SYNC_FIRST` | `on`/`off` — sync-fit filter before deep L2 score |
| `L2_DOSSIER` | `off`/`cs`/`full` — candidate dossier on `game._last_l2_way_dossier` |
| `L2_SHADOW_MISS` | Observe-only abstract rank of all sync-fit vs L2 winner (analyzer WP) |
| `L2_ADAPTIVE_K` | Score all fit when `n_fit ≤ L2_SCORE_ALL_FIT_MAX` (default 12) |
| `L2_TARGET_SCREEN` | `off`/`mark_only`/`prune` — C/S inferior screen (product default **`mark_only`**; `prune` lab) |

Shared fit API: `strategy_board_fit.select_fit_ways` (Sidestep S142 reuses it).

**Shadow overlook dig (Phase E):** after each L2 (when `L2_SHADOW_MISS=on`), abstract-rank all sync-fit ways vs the L2 eval set; append `batch_dir/l2_cap_miss.jsonl`. Analyze:

```bash
py -3.13 scripts/analyze_l2_cap_miss.py --batch-dir batch_runs/<batch>
```

**Race** (for Q2 guards) = contest for: **specific road**, **specific settlement**, **LA**, **LR**, or **last DCards**.

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

## MGlog re-play GUI — `replay_catan_game.py`

View-only **timeline re-play** of a finished (or truncated) game from **playboard + MGlog**. No Strategy-Engine, no Best-Action, no TwB/TwP/Discard/Play-DCard modals, no Execution Debug.

### Operator flag: audio / `NO_GUI_AT_ALL_TF`

| Flag | Required for re-play GUI |
|------|--------------------------|
| **`NO_GUI_AT_ALL_TF`** in `core/constants.py` | **`False`** (`replay_catan_game.py` **exits 2** with a red error if True) |

- **`False`** → GUI + sounds (Continue SFX; same as interactive `main.py`).
- **`True`** → headless / `run_headless` only. Do **not** leave True for re-play or dig GUI — set False yourself after the batch.

Also use **`False`** when running **`py -3.13 main.py`** if you want game audio.

| Plan / code | Path |
|-------------|------|
| Product plan | `docs/MGlog_replay_gui_plan.md` |
| UX v1 (nav/layout) | `docs/MGlog_replay_gui_v1_plan.md` |
| Continue live-feel | `docs/MGlog_replay_continue_parity_plan.md` (C1–C8) |
| Logging parent | `docs/MGlog_implementation_plan.md` §5 |
| Entry | `replay_catan_game.py` |
| Core apply | `core/mglog_replay.py` |
| Paint / nav / GO / Events / FX | `gui/gui_replay_*.py` |
| Offline stats (GO view) | `core/mglog_statistics.py`, `scripts/mglog_stats.py` |
| Tests | `tests/test_mglog_replay_g*.py`, `r*.py`, `c_continue_parity.py`, `r10_manual_contract.py` |

### Inputs (required)

| Input | Role |
|-------|------|
| **Playboard** | Map only (`PlayBoard_*.txt` / `Playboard_*.txt`) — same map the game used |
| **MGlog CSV** | Ordered events from IP start (e.g. `batch_runs/…/g067/mglog.csv`) |

**Not an input:** mid-game `Saved_Game_*.txt`.

### CLI

```text
# Explicit paths
py -3.13 replay_catan_game.py --playboard "PlayBoard ….txt" --mglog path/to/mglog.csv

# Batch game folder (resolves mglog.csv + Playboard_gNNN.txt from that folder)
py -3.13 replay_catan_game.py --game-dir batch_runs/<run>/g001

# Validate only (no window): exit 0 complete, 1 incomplete, 2 missing/invalid
py -3.13 replay_catan_game.py --playboard "…" --mglog "…" --check-only

# Jump cursor to last event after load
py -3.13 replay_catan_game.py --playboard "…" --mglog "…" --start-at-end
```

If `--playboard` is omitted, the script may fall back to **`constants.SAVED_PLAYBOARD`** when that file exists. Both playboard and mglog must resolve or the tool **exits with code 2** (no re-play window).

### Completeness banner

Gen3 IP starts at **round = −2**, **turn = 1** (“**R-2T1**”).

| Status | Meaning |
|--------|---------|
| **Complete** | Starts at R-2T1 **and** log contains `game_over` |
| **Incomplete** | Truncated start and/or missing `game_over` — amber/red banner |

**Forward nav policy when incomplete:**

- Does **not** start at R-2T1 → **Continue / Next Turn / Next Round / >>** disabled with **red border**; message: no R-2T1.
- Starts OK but **no further rows** (e.g. no `game_over` and already at end) → same four buttons red-bordered/disabled; message: no further data.
- **`<<` / Previous** stay available when `cursor > 0` even if the log is incomplete.

### What you see

| Surface | Notes |
|---------|--------|
| **Playboard + scoreboard + DCards** | Rebuilt from events 0…cursor |
| **Dice images** | Last `dice_roll` at or before cursor (left panel) |
| **Nav (mouse)** | 3 large (`<<` / Continue / `>>`, **Font.LARGE**) + 4 small (Prev/Next Turn/Round); panel **LGRAY** + black border (live HP panel); enabled **green** border + **white** text; disabled **gray** border + **gray** text; **no keyboard** (v1 Q1) |
| **Statistics view** | Hides nav button panel + dice + Events so M-stats use full left area; GO strip stays |
| **Events strip** | Live Events fonts; title inside panel; scroll hint (**↑N older · wheel · total**) **below** the panel bottom border |
| **Bottom banner** | Completeness **left**, cursor chip **right** (same row; no overlapping text) |
| **“?” turn details** | Derived from MGlog for the **current R/T** (RP, buy, steal, discard, TwP/TwB, dcard). RP Corr (blocked production) usually empty — not logged |
| **Events strip** | Synthetic lines from MGlog (“Re-play events (from MGlog)”); **not** full live Twitter/DBG parity |
| **Game Over strip** | **Playboard** / **Statistics** / **Save** — only when `game_over` is applied |

**Statistics** = full-log offline M-stats (whole CSV), **not** cursor-truncated. Completeness banner is **hidden** on Statistics view.

### Sound & animation: Normal game vs re-play (R10)

Three modes operators confuse:

| Mode | Cadence | Sounds | Animations / board cues |
|------|---------|--------|-------------------------|
| **A. Normal game** (`main.py` + GUI) | Real rules: human clicks / AI **Continue** = one legal action (or forced 7-step), then rescan | Full live SFX (dice, danger, builds, DCards, steal, TwB/TwP **DEAL**, panel BUTTON/ERROR, etc.) | Interactive choice highlights (legal robber tiles, steal targets), then result cues; production green; build pulse; DCard **header play pulse** full seat-turn; scoreboard updates live |
| **B. Re-play · Continue only** | One **MGlog event** per click | **Only** the Continue event map below (if any) | **Same visual family** as live *results* for that seat-turn **up to cursor** (highlight grows); no interactive picking |
| **C. Re-play · Next Turn / Next Round** (also Prev Turn/Round, `>>`) | Jump to **end of a seat-turn** (or last event for `>>`) | **None** (jumps never play sound) | **Full seat-turn summary** at land: all builds, production (if not cleared), robber, steals, DCard header pulse for plays in that turn — **no step-by-step SFX** |

**Nav landings (B/C):** Next/Previous **Turn** = end of next/previous seat-turn in **MGlog chronological order** (IP reverse is T4→T3→T2→T1). Next/Previous **Round** = **same seat** (player_id), next/prev **existing** round — **skips missing R0** (R−1→R1). `>>` = last log event.

**Reverse IP label (R=−1):** MGlog keeps `turn = player_id`. Top-left **Turn:** shows sequence `display = (n_players+1) − mglog_turn` (4p: log T1 → show **4**). Color follows acting **player_id**, not the remapped number.

---

#### Sounds compared

| Event / action | **A. Normal game** | **B. Re-play Continue** | **C. Re-play Next Turn / Round** |
|----------------|--------------------|-------------------------|----------------------------------|
| `dice_roll` ≠7 | `DICEROLL` | `DICEROLL` | — (silent) |
| `dice_roll` =7 | Live often **`DICEROLL` then `DANGER`**; re-play product choice is **`DANGER` only** | **`DANGER` only** | — |
| Build road (Execution) | `BUILDROAD` | `BUILDROAD` | — |
| Build settlement / city (Execution) | `FANFARE` | `FANFARE` | — |
| IP place road / settlement | `BUTTON` (live guidance confirm) | `BUTTON` | — |
| Buy DCard | `BUYDCARD` | `BUYDCARD` | — |
| Play DCard (any type) | `PLAYDCARD` (human panel after Confirm; AI path may be quieter if mark-only) | `PLAYDCARD` on `play_*` row | — |
| Steal | `STEAL` (on successful steal) | **`STEAL`** on `steal` row | — |
| Place robber (`set_robber`) | Human often **BUTTON** on tile OKY (UI click) | **Silent** (no UI confirm) | — |
| Discard on 7 | Panel / button noise | **Silent** | — |
| TwB / TwP success | `DEAL` (CashRegister family) | **Silent** | — |
| LA / LR change | Often scoreboard-only (no dedicated fanfare on all paths) | **`FANFARE`** when row is `largest_army_change` / `longest_road_change` | — |
| Turn / meta / production rows | Varies / twitter | **Silent** | — |

**Re-play silent always (B and C):** TwB, TwP, `discard_7`, `set_robber`, `resource_production`, `turn_start` / `turn_end`, `game_start`, `activate_dcard` (unless a row is in the sound map above).

---

#### Animations / board cues compared

| Cue | **A. Normal game** | **B. Re-play Continue** | **C. Re-play Next Turn / Round** |
|-----|--------------------|-------------------------|----------------------------------|
| **Cadence** | Per real action; choice UI then result | After each Continue: rebuild FX for highlight **≤ cursor** (same turn **accumulates**) | On land: rebuild FX for **entire** landed seat-turn (all rows of that R/T ≤ land cursor) |
| **Structures** (road/settle/city/IP) | Pulse latest build (structure color) | Pulse **all** builds in highlight ≤ cursor | Pulse **all** builds in that seat-turn |
| **Production green** | Green on producing tiles after non-7 roll; often cleared when guidance continues | Green for latest non-7 dice in highlight **until** first later `build_*` / `buy_dcard` / `twb` in that turn | Same rule applied to full turn at land (if build already later in turn → greens cleared) |
| **Dice =7** | DANGER; no production green; forced discard/robber UI | DANGER sound (Continue only); no production green | No sound; no production green |
| **Robber after move** | Choice: seat-color legal tiles; result: **white** ring on new tile + sprite | **White** on **last** `set_robber` dest only (prior path cleared) | Same white-on-final-dest (no green/black/red multi-path) |
| **Steal victims** | Choice targets then **red** on victim buildings adjacent to robber; may clear when next guidance starts | **Red** only on victim settle/city **adjacent to the robber tile** (F4); not all of the victim’s buildings | Same adjacency rule at land |
| **DCard buy** | Immature `x` in triplets (usually black) | **No** buy-red (live-like) | **No** buy-red |
| **DCard play** | After successful play: **header icon pulse** (structure color) for **full seat-turn** + red type text on actor row | Same header pulse when highlight includes `play_*` + red type text | Header pulse if any play in landed seat-turn |
| **Interactive 7 / knight** | Human multi-click tile → victim | **Not interactive** — only log results | **Not interactive** |
| **Strategy / BA / TwP AI** | Full Strategy-Engine | **None** | **None** |

---

#### Operator cheat-sheet

| Goal | Use |
|------|-----|
| Closest to “watching the game” with SFX | Re-play **Continue** only (mode **B**) |
| Fast scan of a seat’s whole turn (no audio) | **Next Turn** / **Next Round** (mode **C**) |
| Real play with interactive robber/steal | **Normal game** (mode **A**) |
| One DCard already played this seat-turn | Header icon still pulsing (A/B/C once play is in state/highlight) |

### Reverse IP turn label (R=−1)

MGlog stores reverse-placement **turn = player_id** (chrono order T4→T3→T2→T1). The top-left **Turn:** label for **round = −1** shows the reverse **sequence** number:

`display_turn = (n_players + 1) − mglog_turn` (4p: log T1 → show **4**, log T4 → show **1**).

Seat **color** still follows the acting player (player_id), not the remapped number. Navigation lands use raw MGlog (round, turn).

### DCard play header pulse (live + re-play)

After a **successful** play (human: Play-DCard panel **Confirm** + execute ok; AI: after execute), the **shared** scoreboard DCard header icon for that type pulses in the **player’s structure color** (Blue/Red/**White**/Orange — same RGB as roads/settlements/cities; F5) for the **full remaining seat-turn**. This emphasizes **one DCard play per turn**. Clears only when the next seat-turn starts — not when robber/build animations clear. Re-play: pulse when the highlight seat-turn contains a `play_*` (Continue grows into it; Next Turn/Round show it if the landed turn already includes the play). **Not** a ring on per-player type-cell numbers.

### Keyboard

**None** for re-play nav (mouse only). Window close ends the tool.

Mouse: nav buttons, GO strip, per-seat **?**, mouse wheel on Events.

### Save screenshots

**Save** / **F5** writes under the mglog parent’s **`replay_shots/`** (or a project-relative fallback):

```text
ReplayShot_<playboard_stem>__<mglog_stem>__playboard_<ts>.png
ReplayShot_<playboard_stem>__<mglog_stem>__statistics_<ts>.png
…_manifest.txt   # absolute playboard + mglog paths + cursor
```

### Operator tips

1. Set **`NO_GUI_AT_ALL_TF = False`** in `core/constants.py` before re-play / dig GUI (and before `main.py` if you want live game sounds). If it is still True after a headless batch, the re-play script exits 2 with a red error.
2. Prefer batch games with **`MGLOG=True`** so `g00N/mglog.csv` + `result.json` → `mglog_path` exist.
3. Headless writes **`g00N/Playboard_g00N.txt`** (and `playboard_path` in `result.json`) for random **or** fixed maps — use that file (or `--game-dir g00N`) for re-play.
4. Use **`--check-only`** first on incomplete batch arms.
5. For offline tables without GUI: `py -3.13 scripts/mglog_stats.py --playboard "…" --mglog "…"`.

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
| **MGlog** (event timeline) | `core/mglog.py`; plan `docs/MGlog_implementation_plan.md`; smoke `scripts/smoke_mglog_m8.py` |
| **MGlog offline stats** | `core/mglog_statistics.py`; plan `docs/MGlog_statistics_plan.md`; CLI `scripts/mglog_stats.py` |
| **MGlog re-play GUI** | `replay_catan_game.py`; plans `docs/MGlog_replay_gui_plan.md`, `MGlog_replay_gui_v1_plan.md` (R10 MANUAL), `MGlog_replay_continue_parity_plan.md`; core `core/mglog_replay.py`; FX `gui/gui_replay_fx.py`; this MANUAL § sound/anim three-mode table |
| Project overview | `README.md` / `README_NEW.md` |
