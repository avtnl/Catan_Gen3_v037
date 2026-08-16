![Catan Game Screenshot](docs/screenshot.png)

# Catan Game Project (Gen3_v035)

Python/Pygame implementation of a **Catan-style board game**, developed as an educational AI and game-engine project.

**Repository:** https://github.com/avtnl/Catan_Gen3_v035

> Not affiliated with official Catan products.

**[📄 Project Status, Acknowledgements, and Technical Overview (PDF)](docs/Overview_v6.pdf)**

**Gen3 v035** is a modular rewrite/evolution of earlier Gen3 builds. Gameplay is split into:

1. **Initial Placement** — human guidance + several AI placement algorithms
2. **Execution** — full turn loop for human and AI players

This project covers most Catan features and is playable. It is not a finished product; new releases will follow as development continues.

## Features

- Hexagonal board (19 land + 26 sea tiles)
- Dynamic scoreboard and action buttons
- Pulsing highlights, animations, and confirmation system
- Events feed
- Development and debug support
- Board Settings: random playboard generation, load/edit playboards, CIBI balance metrics
- Code split into core/ (rules/AI) and gui/ (Pygame UI)

## Initial Placement Phase Features

- Fully interactive **human Initial Placement** with visual guidance
- Multiple advanced AI placement algorithms

## Placement Algorithms

The project includes several sophisticated Initial Placement strategies:

- **Max Pips** — highest probability intersections
- **Max Pips + Ports** — considers both resources and port access
- **5 Weighted Strategic Strategies** — balanced, Wood/Brick, Wheat/Ore, etc.
- **Markov Chain Evaluator** — advanced probability-based evaluator inspired by academic research

## Execution Phase Features

- Human Execution-phase interaction
- Trade with Bank
- Trade with Player and TwP Mode
- Buy Development Card
- Build Road / Settlement / City
- Robber movement and steal flow
- Strategy-Engine which provides "Intelligence" to AI players (IMPROVED)
- Expected-Hand timing and strategy continuation analysis
- Playing Development Cards (NEW)
- Load/ resume a full **Saved_Game** at startup (NEW)
- Game Over and Statistics surfaces (NEW)

## How the AI decides what to do (Strategy-Engine)

The AI follows a long-term plan chosen from a big list of possible win strategies (about 142 different “ways” to get to 10 victory points — for example “build cities and get Largest Army,” or “expand for Longest Road”).

For the plan it picks, it looks at what is actually on the board (open spots, roads, who is racing for the same places) and estimates how many turns that plan might take.

It then sticks with a concrete next target — like “road toward this intersection, then settle there” — so it doesn’t flip plans every single click.

It only does a full rethink of its plan when something important changes, for example:

- an opponent blocks its spot or makes a race much harder
- someone takes (or is close to) Longest Road or Largest Army
- it finishes its current target and needs a new one
- it can suddenly build something useful that wasn’t part of the targeted plan

If only its hand of cards changed (for example after a player trade), it usually doesn’t redo the whole plan. It just updates the timing estimate for the plan it already has. That keeps the game from freezing for a long time after small moves.

## Project layout

```text
main.py                 # Entry: pygame loop, hotkeys, phase managers
run_headless.py         # Lab: all-AI headless / multi-game batch (Phase A/B/C2)
scripts/analyze_cs_setbacks.py      # Lab: Phase C CS strategy probe (offline)
scripts/analyze_way_reassess.py     # Lab: Phase C2 matched control vs treat
scripts/run_phase_c2_tests.py       # Lab: Phase C2 unit suite (R0–R8)
core/                   # Rules, AI, strategy, TwP, Phase0, batch, logging
gui/                    # Pygame UI, panels (TwB/TwP/DCard/discard/…)
assets/                 # Images & sounds
catan_142_ways_…csv     # Victory-Way / resource requirement table
MANUAL.md               # Configuration: constants, headless, Phase C / C2 lab
docs/                   # Notes & design docs (incl. PhaseC2 plan)
```

Local-only reference (not required to run Gen3): `_ref_Catan_Gen2_v045/` — ignore / do not treat as part of the published Gen3 source.

## Requirements

- **Python 3.10+** (3.12 or 3.13 recommended)
- **pygame** (game UI)

Optional for development:

- `pytest` (unit tests under `tests/`)

## Install & run

```bash
git clone https://github.com/avtnl/Catan_Gen3_v035.git
cd Catan_Gen3_v035

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

pip install pygame
python main.py
```

On first run, focus the **game window** (not only the terminal/IDE) so keyboard shortcuts work.

## Configuration

Tunable flags live in [`core/constants.py`](core/constants.py) (load save/map, human seats, victory points, `CHECK_MODE`, …).

Player seats and each AI’s **initial placement algorithm** are set in [`core/game.py`](core/game.py) inside `_initialize_players()`.

**Full explanations** (what each flag does, reserved/future flags, seat `id_` / color / `sequence` notes):

→ **[MANUAL.md](MANUAL.md)**

Quick examples:

| Goal | Setting |
|------|---------|
| Normal new game | `LOAD_GAME = False` |
| Resume a save | `LOAD_GAME = True` + `SAVED_GAME = "…"` |
| Fair play UI | `CHECK_MODE = False` |
| Human on White (seat 3) | `HUMAN_PLAYER = True`, `HP_ID = [3]` |

Restart the app after changing constants or `_initialize_players()`.

## Useful controls / debugging

| Input | Role |
|--------|------|
| Mouse | Board, buttons, TwB / TwP / DCard / discard panels |
| **F9** | Save Phase0 AI baseline for the **current** player (if hooks installed) |
| **F8** | Same as F9 (fallback when the IDE steals F9) |

CHECK_MODE, which is an Analysis-oriented UI: extra strategy/card detail and debug chrome (e.g. Execution Debug). Off = normal play privacy. Controlled by the master flag (in `core/constants.py`).

For normal play: Set CHECK_MODE=False and you only need the mouse. F8/F9 are for developers capturing AI diagnostics.

Strategy / log basenames are configured in `core/constants.py` (see [MANUAL.md](MANUAL.md)).

Slow performance (pipeline) steps can auto-write `Phase0_AI_Baseline_auto_slow_*.json` under **`saved_phase0_files/`** (often gitignored). Full session saves go to **`saved_games/`**.

## Tools

This Gen3 codebase was developed and refactored with help from AI coding assistants:

- Early porting and design discussions: **OpenAI ChatGPT**
- Later implementation and dig-in work: **xAI Grok** — Grok Build (4.5)

The game itself runs on **Python** and **Pygame**. Optional developer tooling includes **pytest** (local tests) and in-game diagnostics (F8/F9 Phase0 captures).

## Acknowledgements and external inspiration

This project was developed as an educational AI/game-engine project and builds on several sources of inspiration.

First, I would like to acknowledge Lauren Nagel’s work, *Analysis of “The Settlers of Catan” Using Markov Chains*. That paper helped inspire the project’s early exploration of Markov-style evaluation for Initial Placement. In this project, that idea was adapted into a practical placement-evaluation approach suitable for a Python/Pygame implementation.

Second, I would like to acknowledge the strategy articles published by Player One on BoardGameAnalysis.com, especially the series *The 102/143 Ways to Win at Catan*, Parts I, II and III. This project uses a 142-way requirements table based on that work. Player One also wrote *What is a balanced Catan board*, which describes the CIBI index, also implemented in the code.

The implementation in this repository is my own educational adaptation. The referenced works served as inspiration for strategic thinking, probability-based evaluation, and the organization of possible paths to victory; they are not copied code or direct implementations.

## License

MIT — see [LICENSE](LICENSE).  
Copyright (c) 2026 Anthony van Tilburg.

## Disclaimer

This is an independent educational project inspired by the rules of Catan.  
It is **not** an official product of Catan GmbH / Kosmos / Asmodee.
