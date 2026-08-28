# Catan Game Project Gen3  
## Technical Overview Addendum — Functionality Added in v037  
### Take 2 (draft for review)

**Anthony van Tilburg**  
**Codebase line:** `catan_game_v037` (continues from Gen3 **v035** / Overview **v6**)  
**Document status:** Draft take 2 (operator notes: `Main activities A-G.txt` including material after `##### ADDED AFTER THIS #####`; lab digs and plans under `docs/`)  
**Date:** August 2026  

This addendum does **not** replace Technical Overview v6 (`docs/Overview_v6.pdf`). Overview v6 describes the playable base inherited at the start of v037. This document summarizes what was **added or substantially changed** during the v037 cycle: unattended multi-game lab tooling, Strategy-Engine performance and refresh policy, offline probes, LA/LR give-up and salvage, Multi-Game logging and Replay, the Sidestep / S142 research path, and—later in the cycle—L2 transparency / sync-first work, opponent RCard memory, a Victory-Way resource-need façade, and Gen2-style per-player reachability maps.

Usage remains educational and experimental under the repository MIT License. Gen3 is not affiliated with Catan GmbH.

**Take 2 note.** The first draft of this addendum (`Overview_v037_added_functionality.md`) reflected the operator log **above** the marker `##### ADDED AFTER THIS #####` in `Main activities A-G.txt`. Take 2 keeps that narrative and adds §§13–16 for themes recorded **after** that marker.

---

## Contents

1. Introduction and how to read this addendum  
2. High-level summary  
3. Relation to Overview v6 and the v035 baseline  
4. Unattended multi-game path (Phases A–C, E)  
5. Performance and Strategy refresh policy (Phase D / P0–P5)  
6. Change-Strategy (CS) probe and matched way-reassess lab (Phase F / C2)  
7. LA/LR probe, give-up, escape, and partial-way salvage (Phase G / Phase L)  
8. Players-view ambition and public give-up proxies (L4–L5)  
9. Multi-Game log (MGlog), statistics, and Replay dig tooling  
10. Sidestep ETA and S142 (research / lab drive)  
11. Layer discipline and what did *not* move into product  
12. Known limitations and suggested next steps  
13. L2 transparency, sync-first, and SE dig follow-ons  
14. Opponent RCard memory (`RCARD_MEMORY_OPPONENTS`)  
15. Victory-Way resource need façade (`way_resource_need`)  
16. Per-player reachability maps (Gen2-style)  

Annex A. Operator entry points  
Annex B. Primary modules and scripts  

---

## 1. Introduction and how to read this addendum

Version 6 of the Gen3 overview documented a **playable** mixed human/AI game: Initial Placement, Execution, Board Settings, Trade with Bank and Player, development cards, mid-game load, and a Victory-Way Strategy-Engine with Turns-Estimator and Best-Action. That product spine still runs from `main.py`.

The v037 cycle kept that spine and invested heavily in **lab and Strategy-Engine quality**: run many games without a window, measure when and why strategy changes, decide when Largest Army (LA) and Longest Road (LR) ambitions should be abandoned, log enough state to **replay and dig**, and explore a lighter Sidestep timing estimate (Side / S142) without immediately replacing live Expected-Hand (EH) planning. Later work asked the same honesty of **L2 itself** (who was invited into the top-K, board-sync first), tightened **public opponent resource belief**, centralized **mid-game RCard need** toward Victory, and restored **per-player road-distance maps** so geometry consumers share one cache.

**Plain-English summary.**  
Overview v6 answered: “Can we play Catan with AI guidance end to end?”  
This addendum answers: “Can we *measure*, *batch*, and *improve* that AI’s strategy behaviour—and under what flags do those improvements affect live play?” Take 2 also asks: “Can we see *why* L2 chose a way, believe opponent hands with a limited memory window, cost a Victory-Way mid-game the Player One way, and avoid re-BFS-ing empty-road distance on every planner call?”

Two products remain distinct:

| | **`main.py`** | **`run_headless.py`** |
|--|----------------|------------------------|
| Role | Interactive session | Lab runner (no play window) |
| Typical seats | Human + AI (default P3) | Four AI (`HUMAN_PLAYER=False`) |
| Advance | Clicks (Play / Continue / …) | Automatic IP + Continue loop |
| Batch N games | No | Yes (`--games N`) |
| Artifacts | Saves / screenshots | `batch_runs/…/result.json`, `batch_summary.json`, CS, MGlog |

Flags and recipes: repository root `MANUAL.md` and `AGENTS.md`. Restart after changing `core/constants.py`.

---

## 2. High-level summary

The following paragraphs mirror the operator’s high-level notes and expand them into Overview-style claims.

**Unattended multi-game path.**  
We built a batch runner (`run_headless.py`, `HeadlessGameRunner`, `GameManager`) that plays multiple full games back-to-back under `NO_GUI_AT_ALL_TF=True` with four AI seats. Each game writes structured results; the batch writes a summary (wins, stuck/error, rounds/steps, dice metadata, give-up/salvage dig fields, and related probes).

**CS probe (Change Strategy).**  
After a batch, it is impractical to hand-review every game. The CS probe is an **offline** analyzer over strategy samples (CS JSONL). It surfaces ETA setbacks, Victory-Way changes, sticky-target changes, and policy anomalies so attention goes to interesting games. The probe itself does **not** change the Strategy-Engine; digs from it *did* inform when to re-plan (product sticky / explicit-recalc policy).

**LA/LR probe.**  
A parallel probe family examines races for Largest Army and Longest Road. Unlike CS-only instrumentation, this line **did** produce live Strategy-Engine behaviour: give-up thresholds (θ), escape (do not re-lock a dead special), partial Victory-Way salvage (T1/T2), thrash control (one fire per episode), and related specials kills/diverts—under operator flags.

**Performance.**  
Early headless games were far too slow for science-scale batches. Work on Strategy refresh policy (when to run “heavy” L2 / portfolio / Turns-Estimator work) and related paths moved typical product-scale headless cost from roughly **1–2 minutes per game** toward roughly **~30 seconds per game** on recent control-style runs (machine- and flag-dependent). Sidestep/S142 treat arms remain much slower when drive is on.

**MGlog and Replay.**  
Each lab game can emit a dedicated Multi-Game log (MGlog CSV). That log enables a separate **Replay** tool (`scripts/replay_catan_game.py`) to step a finished game without re-running the Strategy-Engine. A second Replay mode digs CS-enriched detail to validate SE behaviour. Substantial effort went into the Replay **Data panel**; where possible, enrichment is applied **offline** so live play stays lighter.

**Heavy calculation cadence.**  
Heavy work remains centered on `core/resource_time_estimator.py` (Expected-Hand feasibility / timing). v037 optimized *when* that work runs (true-light L0 vs L2 explore gates, dirty flags, explicit per-seat recalc schedules such as product AI `[2,[4,4]]`—setback plus every four own turns).

**Sidestep / S142.**  
A research sidestep asked whether a simpler timing estimate (Side) and a way-picker over fit Victory-Ways (S142) could complement or eventually simplify heavy EH loops. Side and S142 were developed observe-first; an optional **lab drive** arm can adopt S142 picks into sticky for matched A/B. Early evidence on rounds-to-win is **mixed** across board/dice libraries; wall time under drive remains roughly **2–3×** control even with pruning. Product default still keeps S142 drive **off**.

**L2 transparency / sync-first (late cycle).**  
Operator conviction: keep L2’s speed, but borrow S142’s honesty—show which ways were evaluated Early/Mid/End (K = 3/6/9), prefer board-sync **before** spending scarce K slots, and prove with shadow digs that the capped winner is not leaving ≥1 turn on the table. Live work landed **sync-first capping**, **adaptive K**, dossier/CS fields, and cap-miss instrumentation; full “retire S142 live” remains gated on shadow evidence (see §13).

**Opponent RCard memory.**  
`RCARD_MEMORY_OPPONENTS` (`"all"` or `1…4`) defines how much public production evidence AI/SE may treat as remembered opponent hands. Dashboard lag rings plus `core/rcard_view_memory.py` feed beat-risk / race ETAs when the window is limited (see §14).

**Victory-Way resource need.**  
Mid-game RCard accounting for a Victory-Way (structure residual, optional hand subtract, min-road cover, per-target `settlement_Nr`) is centralized in `core/way_resource_need.py` so Dig residual and portfolio costing share Player One–style rules (see §15).

**Per-player reachability maps.**  
Gen2-style `path_map` / `pathlength_map` / `real_distance_map` on each `Player` are rebuilt and queried via `core/player_reachability.py`, wired into outlook/risk/portfolio/planners and Dig Show—with BFS fallback and a Missing_S rule that maps never hard-exclude settlement candidacy (see §16).

**SE dig packs v6 / v7.**  
Alongside those façades, Replay dig themes (PLN1 forward Target, sticky/repath, dual-tip LR roads, TFR path fill, knight-before-build touchpoints, …) were tracked in `docs/improving_SE_v6.txt` / `improving_SE_v7.txt` and landed as many small WPs; §13 notes the pack without duplicating every dig ticket.

---

## 3. Relation to Overview v6 and the v035 baseline

| Item | Meaning |
|------|---------|
| Overview **v6** | Document revision describing the v035-era playable product |
| Code **v035** | Published Gen3 line; GitHub `Catan_Gen3_v035` |
| Code **v037** | Local continuation; starting point was the v035 end state |

Architecture layers from Overview v6 still apply and must not be blurred:

1. **Core rules / state** — only place for real board mutations.  
2. **Scan** — legal actions now.  
3. **Strategy** — Victory-Way, sticky targets, Turns-Estimator, portfolio, TwP/TwB support, DCard choosers, probes’ *live* hooks.  
4. **GUI / Replay** — draw, clicks, panels; route into core; no hidden rules engines.

Terminology stays: **Strategy-Engine**, **Victory-Way**, **Turns-Estimator**, **Best-Action (BA)**, **Check-Mode** (`CHECK_MODE`) — not legacy DEBUG_MODE / BN names.

---

## 4. Unattended multi-game path (Phases A–C, E)

### 4.1 Intent

Phase A–C of the operator roadmap asked for a Gen2-style **game manager**: many games in one batch, statistics per game and for the batch, minimal GUI, and room for offline “sniffers” on logs.

### 4.2 Delivered behaviour

- **NullGui** and guards so Execution can run without a pygame play window.  
- **HeadlessGameRunner** — one game: IP through Game Over / max-round / stuck.  
- **GameManager** — N games, folder layout under `batch_runs/<id>/`, per-game `g00N/`, `result.json`, `batch_summary.json`.  
- **CLI** — `run_headless.py` (`--games`, `--batch-dir`, `--seed-base`, `--dice-from-batch`, `--arm`, …).  
- **Sound** — with `NO_GUI_AT_ALL_TF=True`, sounds off as well as the window.  
- **Console hygiene** — `core/console.py` and quieter terminal output under headless.  
- **Tidiness** — saves directed to `saved_games/`; Phase0 dig captures to `saved_phase0_files/` (Phase E).

### 4.3 What a batch records (conceptually)

Per game: status (won / max_round / stuck / error), winner, rounds, steps, duration, seed, dice count/hash when recorded, playboard pointer, optional CS path, MGlog path, and—once Phase L landed—give-up / salvage dig aggregates.

Per batch: completion counts, win histogram, mean rounds/steps/duration, wall time.

### 4.4 Success criterion (roadmap)

Headless 4-AI games finish without window clicks; N-game batches produce reviewable summaries and artifact folders suitable for probes.

---

## 5. Performance and Strategy refresh policy (Phase D / P0–P5)

### 5.1 Problem

Early TO digs showed multi-minute games: Markov IP cost, frequent Strategy refreshes, dig/Phase0 I/O under Check-Mode, and repeated heavy EH work. Science batches at N=25–100 were only credible after cutting cost per game.

### 5.2 Policy idea (operator framing)

Heavy recalculation (L2-class explore) should not run merely because the hand changed. Prefer:

- **L0 / light** when only resources in hand moved.  
- **L2 / explore** when the plan needs a next target, the board threatens the plan, LA/LR races shock the seat, or an off-way affordable settlement/city appears (Q1)—not for opportunistic off-way DCard alone (Q2).

Dirty flags are **per player**, accumulate over opponents’ turns, and ideally coalesce into **one** explore at the seat’s next planning gate.

### 5.3 Practical roadmap implemented in spirit

| Phase | Theme |
|-------|--------|
| **P0** | Check-Mode off ⇒ no Phase0 spam; thinner auto-save cadence |
| **P1** | True-light L0 on hand-only changes |
| **P1+Q1/Q2** | Off-way structure may force one L2; off-way DCard buy without L2 under race/starvation guards |
| **P2** | Dirty flags / coalesce |
| **P3** | Closed L2 reason table and single gate (`should_run_l2_explore`-class discipline) |
| **P4/P5** | Cheaper portfolio / NumPy EH — partial / ongoing research themes |

Product AI default explicit recalc (Phase C2 lineage): **`[2,[4,4]]`** — reassess after ETA setback and every four own turns—so sticky is no longer “first lock forever” without scheduled re-check. Humans default to no explicit recalc (`[0]`).

### 5.4 Outcome

Control-style headless games on the order of **~20–30 s** mean duration appeared in large batches (example scale: 100 games, wall ~40 minutes). Absolute numbers depend on CPU, Check-Mode, arms (especially S142 drive), and map length.

---

## 6. Change-Strategy (CS) probe and matched way-reassess lab (Phase F / C2)

### 6.1 CS probe — offline instrumentation

**Intent.** ETA toward 10 VP should generally improve; setbacks are expected (robber, discard-on-7, Monopoly, lost races, estimator jumps, …). Classify them; also classify Victory-Way and sticky-target changes; flag anomalies (e.g. way change on achieve).

**Families reported** (see `docs/PhaseC_cs_eta_setback_analyzer_plan.md` and `scripts/analyze_cs_setbacks.py`):

| Family | Detects |
|--------|---------|
| Setbacks (C-ETA) | ΔETA above threshold + class |
| Way changes (C-WAY) | First lock / switches + class |
| Target changes (C-TGT) | Sticky target churn + achieve/block/race classes |
| Anomalies | Policy smells (thrash, way-on-achieve, …) |

Events carry dig identity: game, seat, round, turn, evidence. Output: console one-pager + `strategy_probe_report.json` under the batch directory.

**Important.** Running the CS probe does not mutate play. Dig *findings* (e.g. suspicious total stickiness of first way) motivated **Phase C2**.

### 6.2 Phase C2 — matched dice and explicit way reassess

**Problem.** “Same seed” is not “same game.” Matched science needs recorded **dice sequences**, fixed boards, and clear per-seat reassess policy.

**Delivered lab stack (conceptually):**

- Export / replay **`dice_rolls`** sequences; `--dice-from-batch` + `--seed-base`.  
- Per-seat **`explicit_142_recalc`** schedules and arm configs (`core/batch/arm_config.py`).  
- Way-reassess compare logging and analyzers (`scripts/analyze_way_reassess.py`, related JSONL).  
- First-way fit metrics and product vs control arms documented in `MANUAL.md` / Phase C2 plan.

**Product default** after this work: AI seats use scheduled sticky reassess `[2,[4,4]]`; pure sticky remains available as a **lab control** arm.

---

## 7. LA/LR probe, give-up, escape, and partial-way salvage (Phase G / Phase L)

### 7.1 Two views

| View | Role |
|------|------|
| **God-view** | Observer sees locked ways and true race progress; fit θ and dig races offline |
| **Players-view** | Public features / ambition labels; map toward give-up without private hands (L4–L5) |

### 7.2 Live behaviour that *does* change games (when enabled)

Operator notes correctly distinguish probe reporting from SE impact. The following affect Execution when the LA/LR stack and escape/salvage flags are on:

1. **Give-up LA/LR ambition (L6 θ)** — abandon a hopeless special race.  
2. **Escape** — after give-up, do **not** sticky-re-lock a way that still needs the dead special (episode memory, portfolio filter, sticky gates, force divert).  
3. **T1 salvage** — prefer another Victory-Way that never required the dead special.  
4. **T2 salvage** — if none, strip dead components and rank residual need by least own-turns.  
5. **Clear LA/LR project state** so Best-Action stops chasing a dead special project.  
6. **One fire per episode** — prevent give-up thrash loops.  
7. **S5b / S5.5-class kills and diverts** — rule-based “already hopeless” cousins integrated with the same sub-engine.  
8. **Operator freezes** — θ / dwell profiles, `GIVEUP_ESCAPE_ENABLED`, salvage expand flags, etc.

**Core product insight:** after give-up, the engine must not re-lock a dead LA/LR forever. Escape + partial salvage (S0–S7 lineage, digs D0–D7 / G0–G6) implement that. **S8** (VP scrape when T1/T2 empty) remains reserved until digs show need. A separate “permanent give-up forever” plan was drafted and **not** implemented as a hard product default beyond episode/escape semantics.

### 7.3 Matched A/B (ops/science)

Product-scale matched libraries (e.g. shared dice `product_lib_n100`, control escape off vs treat escape on) measure stability, fires, salvage/switches, and wins under identical chance inputs. Hard WdB stress maps were frozen earlier and reused offline; optional re-stress remains open.

---

## 8. Players-view ambition and public give-up proxies (L4–L5)

After god-view θ work, pillar B addressed what a seat can infer **publicly**:

- **L4** — public feature builder, LA/LR ambition labels (L/M/H), offline agreement digs vs god-view (L4-0…L4-5).  
- **L5** — map θ-like decisions onto public proxies; precision/FGU-style offline reports; gate whether to promote players-view give-up into live L6 (L5-0…L5-5).

Live nesting of players-view columns on every probe row was optional and not required for the offline gate. Product LA/LR give-up in Execution remains primarily the **god-view / specials sub-engine** stack unless a later release promotes L5 proxies.

---

## 9. Multi-Game log (MGlog), statistics, and Replay dig tooling

### 9.1 MGlog

**Intent.** A per-game event CSV capturing board-visible and action history sufficient to rebuild a timeline offline—without requiring a full Saved_Game for every dig.

Work packages (M0–M9 lineage) cover header/append, snapshots, hooks (turns, dice, builds, robber, trades, DCards, LA/LR holders, game over), batch path stamping, and MANUAL notes. Batch games typically expose `g00N/mglog.csv` plus a pointer on `result.json`.

### 9.2 Statistics from MGlog

Offline aggregators rebuild endgame-style tables (dice, resources, structures, activity) from MGlog + thin playboard load (`scripts/mglog_stats.py` / `core/mglog_statistics.py` lineage), reducing dependence on interactive Game Over alone.

### 9.3 Replay product

`replay_catan_game.py` (repository root; thin shim still at `scripts/replay_catan_game.py`) loads an MGlog, validates completeness, and steps with a small control set (board + scoreboard paint, Game Over / statistics toggles, screenshots). **Replay does not re-plan**; it visualizes what was logged.

**CS dig mode.** Offline annotation can attach CS categories onto MGlog columns (`cs_tf`, `cs_cat1`, `cs_cat2` family) so Replay’s Data panel can highlight setbacks, way changes, target changes, and anomalies without mutating the original batch’s raw CS file. Feeding the panel drove some SE fixes, but the design preference is **offline enrichment**.

---

## 10. Sidestep ETA and S142 (research / lab drive)

### 10.1 Motivation

EH / L2 remain correct but expensive. Sidestep asks for a faster observe-only Side estimate for PLN2-style targets, and whether minimizing Side over board-fit Victory-Ways (**S142**) yields fewer rounds to win if evaluated more often.

### 10.2 Side vs S142 (roles)

| | **Side** | **S142** |
|--|----------|----------|
| Kind | Scalar timing estimate | Chosen Victory-Way id |
| Question | How many own turns for this RemTR @ this RP? | Which sync-fit way has least min-Side over PLN2 targets? |
| Shared math | `side_with_confidence` in `core/sidestep_eta_matrix.py` | Uses the same Side walk |
| Live SE | Observe / compare when enabled | Optional **drive** adopt via external preferred way |

Board sync for S142 uses the same `can_realize_way` family as live board-fit, **inside** Sidestep modules, without rewriting L2 by default.

### 10.3 Pruning and performance profile

S142 matrix search added Pareto / dedupe / mass lower-bound / walk-abort pruning. Matched n=3 showed **~7–8%** wall reduction vs unpruned S142 with **identical** rounds/steps—Side-safe, not always way-id-identical (tie breaks). Live profiles showed **fit (`can_realize_way`) and RemTR residual** dominate wall (~45–70% each depending on stage); Side walks are **≪1%**. Further NumPy batching of walks alone will not fix treat-arm cost; caching fit/RemTR and reducing fire rate will.

### 10.4 Matched A/B evidence (honest)

Across operator-facing experiments (n=3 plus several matched n=10 control vs `s142-drive`+prune):

- Some libraries show fewer mean rounds under S142; others are flat or mixed (medians near zero).  
- Wall ratio treat/control typically **~2–3×**.  
- S142 recommendation logs often **oscillate among 2–3 way_ids** (e.g. 38/66/88) at equal Side; sticky switches are fewer but real.

**Product posture at draft time:** `SIDESTEP_S142_DRIVE` default **False**; enable via `--arm s142-drive` for lab. Live EH Strategy-Engine remains the product core until a deliberate adopt decision with tie-break / performance gates.

Primary modules: `sidestep_eta_matrix.py`, `sidestep_compare.py`, `sidestep_board_sync.py`, `sidestep_s142_prune.py`, `sidestep_s142_drive.py`; Q&A in `docs/Sidestep_v2_QA.md`.

---

## 11. Layer discipline and what did *not* move into product

| Kept as lab / offline | Live product impact when flags on |
|------------------------|-----------------------------------|
| CS setback analyzer | Explicit recalc schedules; dig-informed policy |
| Many Phase L dig CLIs | Give-up θ, escape, salvage, S5b/S5.5 family |
| MGlog stats / CS annotate | MGlog append during games; Replay separate |
| Sidestep compare tables | Optional; compare flag default off |
| S142 drive A/B | Off unless arm/flag |
| L2 shadow full-fit proof (Idea B) | Sync-first / adaptive K / dossier fields when enabled |
| Reachability Show **road overlays** | Map rebuild + Show circle `map_dist` / soft radius |

Permanent-specials-give-up-as-lifetime-ban and S8 VP-scrape were explicitly **parked**. TwP/TwB probe Phase H remains on the original A–H roadmap as a later sniffer theme. Monopoly and most TwP callers still use truth hands by default until deliberately pointed at `get_rcard_player_view_memory()`.

---

## 12. Known limitations and suggested next steps

**Limitations**

- Headless science still confounds policy with residual RNG unless dice (and ideally decks) are matched.  
- CS “first_lock only” eras taught that L2 frequency ≠ way openness; switch gates matter.  
- Escape/salvage improve correctness under dead specials but add complexity and dig surface area.  
- S142 is not yet a proven drop-in replacement for EH on rounds **and** wall.  
- Replay script path still noted for relocation to repo root.  
- Interactive GUI has no first-class Sidestep panel; dig is file/Replay oriented.  
- Aspirational headless budget (**~15 s/game**, ~240 games/hour) is **not** yet met; late-cycle geometry maps currently use full-rebuild stubs and can lengthen wall until incremental amend lands.  
- L2 “retire S142 live” still wants shadow digs that missed_gain outside K is rare under sync-first + adaptive K.

**Suggested next steps (non-binding)**

1. Decide product adopt vs hold for S142: require deterministic Side tie-break, wall budget, and larger matched n—or retire live S142 once L2 dossier + shadow proofs convince.  
2. Perf: cache board-fit and RemTR across S142 fires; reduce a/b/c cadence or add hysteresis; pursue **true incremental** reachability amend (today’s notify path is correctness-first full rebuild).  
3. Finish or close product matched escape A/B reporting.  
4. Promote Replay packaging and CS-annotate recipes in MANUAL.  
5. Resume TwP/TwB efficiency probes (Phase H) once SE specials/S142 posture is stable; optionally point TwP/Monopoly at RCard memory belief.  
6. Keep Overview v6 chapters as the playable base; prefer this **take 2** addendum when describing post-marker themes (§§13–16).

---

## 13. L2 transparency, sync-first, and SE dig follow-ons

### 13.1 Operator conviction

Performance remains a first-class goal (batch science wants ~15 s/game). The operator also valued **S142’s transparency** (portfolio × fit ways) and **board sync**, while preferring L2’s wall time and lower fire rate. The question became: can L2 show *which* way-ids were considered Early/Mid/End and *why*, and apply sync like S142, without paying S142’s full matrix every time?

Brainstorm ideas (recorded in `Main activities A-G.txt`):

| Idea | Intent |
|------|--------|
| **A — Dossier** | On every L2 fire, emit stage/K, ranked_in, always_include, scored, dropped_before_score, winner/runner-up |
| **B — Shadow proof** | Cheap full-fit rank vs L2 winner; log `missed_gain` to prove K is safe |
| **C — Adaptive K** | Cap K against `n_fit` (score all fit when the set is small) |
| **D — Sync-first** | Fit filter → cheap rank → top K → existing EH / portfolio audits |
| **E — Reject log** | Unfit/demoted ways carry `can_realize_way` reasons |

Suggested path to *retire* live S142: dossier → sync-first + reject reasons → shadow proof on batches → adaptive K from miss rate → optional a/b/c cadence for L2. Keep S142 as an **offline oracle** for those digs until conviction is earned.

### 13.2 What landed in code (honest)

Live portfolio / L2 paths gained **sync-first capping** and **adaptive K** switches (with lab arms / `perf_mode` notes), **L2 dossier / CS fields**, and **cap-miss** instrumentation for digs. Product EH L2 remains the deep scorer inside the capped set. Shadow “full-fit every a/b/c” as a permanent live gate is still a **lab / dig** theme rather than a claimed product default.

### 13.3 SE dig packs v6 / v7 (summary)

Operator digs after sticky/PLN Replay work produced `improving_SE_v6.txt` / `improving_SE_v7.txt`: forward Target / Hot overrides, Dig ETA table polish, dual-tip / dead-edge LR roads, force L2 after LR grow, TFR free-road path fill, sticky hold vs thrash, risk refresh after own road, and related BA touchpoints. Many items are **Done** or **Partial**; residual tickets (e.g. TwP accept quality, some Dig polish) remain on those lists. They do not replace §§4–10; they harden Execution behaviour observed in Replay.

---

## 14. Opponent RCard memory (`RCARD_MEMORY_OPPONENTS`)

### 14.1 Intent

Knowing opponents’ hands is central to Catan. Gen3 already accumulates **public** production evidence on `ResourceCardDashboard.resource_production_game_player_view`. The operator asked for a limited memory window: remember only the last *N* completed rounds (at four seats, `N=2` ≈ eight player-turns), not necessarily the entire game.

### 14.2 Delivered behaviour

| Piece | Role |
|-------|------|
| Constant `RCARD_MEMORY_OPPONENTS` | `"all"` (default = full cumulative view) or `1…4` |
| Dashboard lag ring | Up to four end-of-round snapshots; belief = now − lag[N] |
| `core/rcard_view_memory.py` | Pure helpers; `opponent_belief_hand5` |
| Game wiring | End-of-round snapshot; save/load lag; `get_rcard_player_view_memory()` |

**Dig / Check-Mode truth** on `Player.rcards` is unchanged. Limited memory is an **AI/SE belief** policy.

### 14.3 Beat-risk wiring

When `RCARD_MEMORY_OPPONENTS` is `1…4`, opponent Expected-Hand ETAs for settlement race/spoiler threats (and a contested-road helper) use the **belief hand**, not god-view. Own-seat ETA still uses the evaluating player’s real hand. Threat rows can carry Dig-facing `eta_hand_source` / `eta_memory_rounds`. Call sites include risk enrichment, portfolio timing, sticky settle refresh after own road, and road-planner settle-path scoring.

Monopoly / TwP and similar are **not** wholesale switched to belief yet—the infrastructure is ready when those policies want limited memory.

Plan / MANUAL: `MANUAL.md` (`RCARD_MEMORY_OPPONENTS`); tests under `tests/test_rcard_view_memory.py`.

---

## 15. Victory-Way resource need façade (`way_resource_need`)

### 15.1 Intent

EH and Dig need mid-game RCard bills per Victory-Way that match **Player One–style** component costing: subtract settled/cities/roads/DCards already on the board (and optionally hand), and treat road mass carefully when the next settle is distance 2 vs 3+. Logic had been spread across residual Dig tags, portfolio helpers, and CSV absolute costs.

### 15.2 Locked policy (Proposal A)

- **Whole-way** remaining roads: playboard **min empty-road cover** (not a naive CSV ± (d−2) rewrite).  
- **Per-target** EH: raw path distance feeds `settlement_Nr` / `path_distance_for_next_settle` without rewriting whole-way `n_R`.  
- **`consider_hand=False`** (default): structure residual only—Dig / whole-way mass.  
- **`consider_hand=True`**: subtract hand; **self = truth**, **opponent = RCard memory belief**.

### 15.3 Delivered module

`core/way_resource_need.py` wraps remaining-need / `strategy_cost_from_components`, optional min-cover + shared TFR road credit, hand resolution, and caller migration for Dig residual / portfolio costing (behaviour-preserving at `consider_hand=False`). Docs: `docs/way_resource_need_plan.md` (WP0–WP6 Done); MANUAL / AGENTS pointers.

Callers must not double-subtract hand (use need-before-hand with EH’s hand, **or** need-after-hand with an empty hand vector).

---

## 16. Per-player reachability maps (Gen2-style)

### 16.1 Intent

Gen2 kept per-seat matrices so empty-road distance and paths were a workbook, not a fresh BFS on every planner call. Gen3 `Player` already allocated `path_map` / `pathlength_map` / `real_distance_map` (and min vectors) with save/load—but had **no live writers**. Restoring that lifecycle aims at shared geometry for road planning, min-cover, race distance, and Dig Show—without reintroducing the Missing_S bug of hard-prefiltering candidacy from a stale `min_pathlength` map.

Inspiration: Gen2 `Catan_Gen2_v045` / local `_ref_Catan_Gen2_v045` (`update_distance_*`, `update_other_maps`, `all_tws_for_player`).

### 16.2 Semantics (product)

| Axis / field | Meaning |
|--------------|---------|
| Rows (starts) | Own S/C **and** endpoints of own roads |
| Columns (ends) | Still-legal settle intersections for that seat |
| Horizon | Distance ≥ **5** → sentinel `99` / empty path |
| `real_distance` | Roads **still to build** on the best free path (primary EH/race metric) |
| `pathlength` / S/C hop | Dig / PLN2 ∈{2,3} prefers hop from buildings, not only road tips |

Flag: `REACHABILITY_MAPS` (default **True**). BFS remains the safety net on miss/stale/flag-off.

### 16.3 Lifecycle and consumers

- **Seed** at first Execution turn (`rebuild_all_maintained_seats`); **`load_game`** dirties seats and rebuilds if already in Execution.  
- **Updates** after committed roads/settles via sticky notify (paid and free TFR); city upgrades do not rewrite maps. AI seats always maintained; humans via Dig `ensure_dig_seat_maps` / Check-Mode.  
- **v1 incremental** notify bodies are **full rebuild stubs** (correctness-first; selective cell amend is residual).  
- **Tier H/M** readers: outlook, risk, min-cover, portfolio, plan geometry/Show, road planner/optimizer, sticky tip/repath, way_need sticky path distance, first-way-fit hints.  
- **Dig Show:** seat-matrix radii remain base; optional soft +2px when `path_distance=3`; stamps `map_dist`; **no road path overlays** yet.

Plan: `docs/player_reachability_maps_plan.md` (WP-R0–R6 Done). Smoke: headless games complete with maps enabled; wall cost may rise until incremental amend lands.

---

## Annex A. Operator entry points

| Task | Entry |
|------|--------|
| Interactive play | `python main.py` / `py -3.13 main.py` |
| Headless batch | `py -3.13 run_headless.py --games N --batch-dir …` |
| CS probe | `py -3.13 scripts/analyze_cs_setbacks.py --batch-dir …` |
| Way-reassess A/B | Phase C2 scripts + `--dice-from-batch` / `--arm` |
| Replay | `py -3.13 replay_catan_game.py` (see MANUAL) |
| S142 lab arm | `--arm s142-drive` |
| RCard memory window | `RCARD_MEMORY_OPPONENTS` in `core/constants.py` |
| Reachability maps | `REACHABILITY_MAPS`; plan `docs/player_reachability_maps_plan.md` |
| Way RCard need | `core/way_resource_need.py`; plan `docs/way_resource_need_plan.md` |
| Flags / seats | `core/constants.py`, `MANUAL.md`, `AGENTS.md` |

---

## Annex B. Primary modules and scripts (v037 additions / focus)

| Area | Modules / scripts (indicative) |
|------|--------------------------------|
| Batch | `run_headless.py`, `core/batch/headless_runner.py`, `game_manager.py`, `null_gui.py`, `arm_config.py`, `perf_mode.py` |
| Console | `core/console.py` |
| CS probe | `core/batch/cs_setback_analyzer.py`, `scripts/analyze_cs_setbacks.py` |
| C2 reassess | `core/explicit_142_recalc.py`, `strategy_explicit_recalc.py`, `scripts/analyze_way_reassess.py` |
| LA/LR / salvage | Phase L plans under `docs/PhaseL_*`, give-up/salvage modules, dig scripts |
| L4/L5 | Players-view / public give-up modules and offline reports |
| MGlog | `core/mglog.py`, `mglog_statistics.py`, `scripts/mglog_stats.py` |
| Replay | `replay_catan_game.py`, `gui/gui_replay_*.py` |
| Sidestep | `core/sidestep_*.py`, `scripts/analyze_s142_ab.py`, `docs/Sidestep_v2_QA.md` |
| L2 sync / dossier | Portfolio L2 sync-first / adaptive K; `l2_cap_miss` / dossier CS fields; `docs/L2_*` |
| RCard memory | `core/rcard_view_memory.py`; dashboard lag; `RCARD_MEMORY_OPPONENTS` |
| Way need | `core/way_resource_need.py`; `docs/way_resource_need_plan.md` |
| Reachability | `core/player_reachability.py`; `docs/player_reachability_maps_plan.md` |
| SE dig packs | `docs/improving_SE_v6.txt`, `docs/improving_SE_v7.txt`, `docs/SE_improvement_plan_v6.md` |

---

## Document control

| Field | Value |
|-------|--------|
| Title | Technical Overview Addendum — Functionality Added in v037 (take 2) |
| Status | **Draft for author review** |
| Prior draft | `docs/Overview_v037_added_functionality.md` (pre–`ADDED AFTER THIS` scope) |
| Sources | `Main activities A-G.txt` (incl. after `##### ADDED AFTER THIS #####`); `docs/Overview_v6.pdf` (tone/baseline); `AGENTS.md` / `MANUAL.md`; Phase C / C2 / L / MGlog / Sidestep / L2 / way_need / reachability plans under `docs/` |
| Not claims | Commercial completeness; affiliation with official Catan products |

*End of draft take 2.*
