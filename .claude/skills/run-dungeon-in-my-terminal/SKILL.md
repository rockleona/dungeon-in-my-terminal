---
name: run-dungeon-in-my-terminal
description: Build, run, and drive dungeon-in-my-terminal (a curses TUI roguelike). Use when asked to start the game, take a screenshot of the TUI, verify a layout/animation change, check game balance/depth numbers, run its tests, or build the package.
---

A single-project repo: a `curses` terminal roguelike, managed with `uv`. It
cannot be driven by a plain bash tool call (curses takes over the terminal),
so the project ships its own pty-based driver — `tools/tui_drive.py` — which
runs the real binary inside a pty, feeds it keystrokes, and renders the
resulting screen as plain text via `pyte`. That driver, not `tmux`, is the
harness: use it first. All paths below are relative to the repo root.

## Prerequisites

None beyond `uv` — Python 3.12 is fetched by `uv` itself, and `curses` is
part of the stdlib on macOS/Linux. Verified on macOS with `uv 0.6.10`.

## Setup

```bash
uv sync
```

Dev dependencies (`pyte`, `pytest`) install automatically — `tools/tui_drive.py`
depends on `pyte` from the `dev` group in `pyproject.toml`.

## Run (agent path) — drive the real TUI

`tools/tui_drive.py` exposes a `drive(keys, seed=..., settle=..., cols=..., rows=...)`
function: it forks the real `dungeon` entry point into a pty, writes each key,
and snapshots the screen after each one. Use it directly from a scratch script
rather than trying to script raw keystrokes over a bash pipe.

CLI form (walks through the bundled `demo_script()` — menu, full party, walk
south, attack):

```bash
uv run python tools/tui_drive.py --seed 30 --last 3      # only the final 3 frames
uv run python tools/tui_drive.py --cols 76                # narrow-terminal check
uv run python tools/tui_drive.py --cols 72 --rows 20      # documented minimum size
```

For your own key sequence, import `drive` and script it (verified working —
this reaches the main menu, creates a solo warrior, opens the help card, and
closes it):

```python
import sys
sys.path.insert(0, "tools")
from tui_drive import drive

keys = [("solo", b"1"), ("warrior", b"1"), ("start", b"\r"),
        ("help", b"h"), ("close help", b" ")]
frames = drive(keys, seed=30, settle=0.4)
for label, frame in frames:
    print("=" * 40, label)
    print(frame)
```

Run it with `uv run python <script>.py`. Each frame is `(label, screen_text)`
— print or diff whichever frames matter. Raise `settle` if a frame looks like
it lags a keypress behind (the dice-roll animation and `Esc` handling both
take a moment to finish drawing).

Key reference (also in the in-game `h` card):

| Key | Action |
|---|---|
| `1`/`2`/`3`/`4` | party menu picks; in-game: use ability slot |
| `↑↓←→` / `wasd` | move |
| `i` | items | `Tab` | delay turn / cycle target | `e` / space | end turn |
| `>` | shop (on stairs) | `m` | monster list | `g` | legend | `h`/`?` | help |
| `Enter` | confirm target | `Esc` | cancel targeting | `q` | quit run |

## Direct invocation — headless balance runs

Most changes to `core/` (drop rates, XP, monster tiers, shop prices) are
verified without any TUI at all, via `tests/autoplay.py`'s scripted player.
This is the balance signal CLAUDE.md references — depth reached over many
seeds, not just "does it crash":

```bash
uv run python -c "
import sys
sys.path.insert(0, 'tests'); sys.path.insert(0, 'src')
from autoplay import play
depths = [play(seed).score.depth_reached for seed in range(30)]
print('avg:', sum(depths) / len(depths))
print('floor10 count:', sum(1 for d in depths if d >= 10))
"
```

Verified this session: `avg: 8.1`, `floor10 count: 4` over seeds `0..29` —
matches the figures already recorded in CLAUDE.md's Balance knobs section.
Re-run this after touching `room_population`, monster tiers, shop prices, or
`XP_PER_LEVEL`/`STAT_UP_*`/`REST_*` in `game.py`.

## Run (human path)

```bash
uv run dungeon                  # play interactively
uv run dungeon --seed 4242      # replay a specific dungeon
```

Needs a real terminal, at least 72x20 (80x30 recommended). `q` quits from
the main loop; `Ctrl-C` if it's ever stuck.

## Test

```bash
uv run pytest                              # 181 tests, ~28s, all layers except the real TUI
uv run python tools/tui_drive.py --last 3  # the one layer pytest can't cover: real layout/animation
```

## Build

```bash
uv build      # → dist/*.whl, dist/*.tar.gz (pure Python, py3-none-any)
```

Verified: builds cleanly, produces `dungeon_in_my_terminal-0.1.0-py3-none-any.whl`.

---

## Gotchas

- **`timeout` is not on macOS by default** — `tools/tui_drive.py` doesn't need
  it (the pty driver has its own `settle`-based pump loop with a bounded
  deadline), so don't wrap it in `timeout ...` on a Mac; it'll fail with
  `command not found` before the driver even starts.
- **`drive()` needs `sys.path` set up manually** when imported from a script
  outside `tools/` — it isn't a package, just add `tools/` (and `src/`, if you
  also want to import `dungeon_in_my_terminal.*` directly) to `sys.path`.
- **The CLI form only replays `demo_script()`** — a fixed solo-party, walk
  south, attack sequence. To check anything else (shop screen, multiplayer
  handoff, a specific ability), import `drive` and write a custom key list
  rather than reaching for CLI flags that don't exist.
