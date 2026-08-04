# CLAUDE.md

A terminal roguelike: procedurally generated dungeon, turn-based grid combat,
d20 checks, permadeath. Solo or 2-4 player hotseat. Python + stdlib `curses`,
managed with `uv`.

## Commands

```bash
uv run dungeon                  # play
uv run dungeon --seed 4242      # replay one dungeon; the summary screen shows the seed
uv run pytest                   # full suite (181 tests, ~30s)
uv run python tools/tui_drive.py --last 3   # screenshot the real TUI (see Verifying below)
uv build                        # wheel + sdist in dist/ (pure Python, py3-none-any)
```

Not on PyPI, and no plan to be — players install straight from git
(`uvx --from git+<repo> dungeon`). The README carries those commands; if the
entry point or the package name ever changes, they need changing there too.

## Layout

```
src/dungeon_in_my_terminal/
├── cli.py         entry point and flags
├── core/          rules — never imports curses
│   ├── dice.py       d20 checks, "2d6+3" parsing; every random result comes from here
│   ├── dungeon.py    BSP generation, line of sight, BFS pathing, grid helpers
│   ├── entity.py     one type for heroes and monsters; stats, statuses, ownership
│   ├── abilities.py  the data shape every class and monster action is written in
│   ├── classes.py    the four hero classes (a registry, not code paths)
│   ├── monsters.py   the bestiary and AI behaviour tags
│   ├── items.py      consumables, each wrapping an Ability
│   ├── shop.py       the between-floors merchant: gear + prices (data only)
│   ├── combat.py     to-hit and damage resolution, monster turns
│   └── game.py       World: floors, turn queue, seats, scoring, permadeath, XP
└── ui/            curses only
    ├── render.py     map, three-column panel, dice, overlays
    └── app.py        menus, play loop, targeting, handoff, summary
```

## Invariants worth protecting

**`core/` must never import curses.** That is what lets a whole run be played
headlessly in a test. If a rule needs to "show" something, it either logs
(`world.log`) or records state the UI reads (`world.last_roll`); it does not
draw.

**All randomness flows through `world.rng`** (a seeded `random.Random`) and
`core/dice.py`. Do not call the `random` module directly in core — a seed must
reproduce a whole run. `tests/conftest.py` has `ScriptedRandom` for pinning
specific rolls.

**Classes, monsters and items are registries, not branches.** Adding a fifth
class means appending a `HeroClass` to `classes.CLASSES`; combat resolves
whatever `AbilityKind` the data names. Only a genuinely new *kind* of effect
should touch `abilities.AbilityKind` and `combat.resolve`.

**One initiative queue holds every unit**, heroes and monsters interleaved
(`d20 + dexterity`). There is no separate "player phase". This is why the
ranger's dexterity matters and why `Tab` (delay) is useful.

**Turns only end on `e`.** Movement and the main action are spent in any order;
nothing auto-ends. `world.turn_spent` tells the UI when to nudge the player.
Do not reintroduce auto-ending — it was removed after playtesting.

**Hotseat exists only as `Entity.owner`.** No rule anywhere branches on game
mode; the UI decides who may press keys and shows a handoff card when the seat
changes (`App.pass_the_keyboard`). Keep it that way.

**Bosses are leashed** via `Entity.home_room`. Before that, a boss could walk
into the corridor and wedge the party behind it. Movement helpers in `combat`
honour the leash through `off_limits`.

## The UI contract

`World.observer` is a callback the UI installs; it fires on every log line.
That is how enemy turns animate and how the die spins — the engine calls
`world.note_roll(...)` *before* logging, so by the time the observer sees a
`"roll"` message the result is already readable at `world.last_roll`.

Drawing text: always use `render.write` / `clip` / `pad` / `text_width`, never
`addstr` directly. Chinese characters are two columns wide and every layout
here depends on that arithmetic. `write` also clips instead of raising at the
screen edge.

The bottom panel is a fixed `render.PANEL_HEIGHT` split into three equal
columns by `render.columns(width)`: party, actions + dice, log. Anything added
to the panel must fit that budget rather than growing it.

Row 0 is the initiative strip (`render.MAP_TOP`), which is why the map is
drawn one row down — `draw_map` and `_plot` add `MAP_TOP` and `viewport_size`
subtracts it. It sits outside the panel precisely because the panel had no
room left. The strip reads `world.upcoming(n)`; monsters the party cannot see
render as `?` (`render.initiative_label`) so the order stays honest without
leaking positions.

The party column's gauge row is sized once for the whole party by
`render.gauge_plan`, not once per hero — every hero's bars must start and end
in the same place or the column reads as broken. Numbers are budgeted before
bars (a truncated number lies, a short bar is only coarse), and the `HP`/`MP`
captions are what drop first when the column is narrow.

New keys go in the `h` help card and the README, **not** in the action
column's hint line — `[i]道具 [Tab]換人 [e]結束` already clips at 76 columns.
The one always-visible pointer is `[h] 操作說明` on the panel header rule.

Every area effect previews before it fires, self-centred ones included —
`combat.burst_victims` is shared by the preview and `_resolve_burst` so the
two cannot drift. Spending MP on something the player has not seen the shape
of is the bug this closed.

## Verifying changes

Three layers, in increasing cost:

1. `uv run pytest` — rules, generation, and layout maths.
2. `tests/autoplay.py` — a deliberately dumb agent that plays whole runs. It
   guards flow (nothing wedges) and difficulty (`test_playthrough.py` asserts
   it still averages 2.5 floors, i.e. floor 1 has not become unplayable). It
   shops and levels like a player would, so **how deep it gets is the balance
   signal** — re-read it after touching depth, tiers, `room_population`, or
   anything under Progression. The suite only checks the floor; the average
   and the floor-10 count come from running it over ~30 seeds yourself.
3. `tools/tui_drive.py` — runs the real binary in a pty and prints the screen.
   **Use this for any layout or animation change**; nothing else catches
   misaligned wide characters or a clipped panel. Check `--cols 76` and the
   documented minimum `--cols 72 --rows 20`, not just your own terminal.

## Conventions

- Code, comments and commit messages in English; everything the player sees is
  Traditional Chinese.
- Conventional Commits, no AI attribution trailer.
- Comments explain *why*; the codebase is deliberately light on restating what
  the code says.

## Balance knobs

Party of 4, ten floors, boss on floor 5 (goblin king) and floor 10 (Abyss
Lord, ends the run). Tuning lives in data, not logic: `classes.py` stats and
per-class `hp_per_level` / `mp_per_level` / `primary_stat`, `monsters.py` tiers
and `room_population`, `shop.py` gear tiers and prices, and in `game.py`
`REST_HP_FRACTION` / `REST_MP_FRACTION` / `EMPTY_ROOM_CHANCE` /
`XP_PER_LEVEL` / `STAT_UP_EVERY` / `STAT_UP_AMOUNT`. Change these and re-run the
autoplay numbers before deciding it feels right — `tests/autoplay.py` now shops
and levels, so its depth is a signal for how far growth actually carries a
party. Current reading over 30 seeds: **depth 8.1 average, 4/30 reach floor
10.** Anything that puts the dumb agent at floor 10 more than a handful of
times has made the run too easy, whatever it did for the curve.

## Progression

Two things grow a party over ten floors, both party-wide so a support cleric is
never left behind:

- **XP → one shared party level.** Every kill feeds `world.gain_xp`; crossing
  `XP_PER_LEVEL * level` bumps every living hero's HP/MP and, every
  `STAT_UP_EVERY` levels, their `primary_stat` by `STAT_UP_AMOUNT`. The fallen
  do not level.

  `STAT_UP_AMOUNT` is 2 on purpose. Modifiers are `(score - 10) // 2`, so a
  one-point stat-up is invisible half the time — that, not the size of the
  gains, is what made the curve read as flat. `_level_up` also logs what each
  hero got (`戰士 HP+8 MP+1 力量+2`); a level the player cannot itemise does
  not feel like one.
- **Gold → gear at the merchant.** `score.gold` is the lifetime total for
  scoring; `world.gold` is the spendable purse (both credited on earn, only the
  purse spent) so shopping never costs you points. Gear is flat
  `bonus_hit` / `bonus_damage` / `bonus_ac` on the `Entity`, so combat reads a
  total and never branches on what a hero wears. The shop opens on `>` at the
  stairs (`App.visit_shop`).

### To tune (playtest 2026-07-29)

- **Gold is a touch stingy** — hand out a bit more (chest amounts in
  `_open_chest`, and/or `definition.score // 5` per kill in `kill`).

The flat-levelling complaint from the same playtest is addressed above. Worth
knowing what it cost: every version that made growth *felt* also made the run
easier, because the party's to-hit is the thing that grows. Autoplay went 7.3 →
8.1 floors. Cheaper feel — bigger visible steps on a slower cadence, plus the
itemised log — was preferred over simply handing out more; the versions that
levelled fastest put the dumb agent at floor 10 in half its runs.

## Known gaps

- No tutorial floor yet — planned last, after the rest of the roster/depth
  work.
- Gear only comes from the merchant; chests still drop consumables, not
  equipment. Fine for now, but a deeper loot table is the obvious next step.
- **The repo has no remote yet.** The README's install commands point at
  `github.com/rockleona/dungeon-in-my-terminal`, which does not exist until
  someone pushes. The mechanism is proven (`uvx --from . dungeon` walks the
  same build-then-run path), but that URL is unverified — say so rather than
  claiming the one-liner works.
