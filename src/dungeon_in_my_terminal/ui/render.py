"""All curses drawing lives here.

The screen is two regions: the dungeon map on top and a fixed-height panel at
the bottom holding the party, the action menu and the dice log. Nothing in
this module mutates the world — it only reads it.
"""

from __future__ import annotations

import curses
import unicodedata
from dataclasses import dataclass

from .. import i18n
from ..core.abilities import Ability
from ..core.dungeon import MAX_DEPTH, TILE_GLYPHS, distance
from ..core.entity import Entity, Team
from ..core.game import World

PANEL_ROWS = 12
PANEL_HEIGHT = PANEL_ROWS + 1  # the divider line sits on top
MAP_TOP = 1
"""Row 0 belongs to the initiative strip, so the map starts one line down.
Kept out of the panel budget deliberately — the panel is already full."""
MIN_WIDTH = 72
MIN_HEIGHT = 20

COLOR_NAMES = ["white", "red", "green", "yellow", "blue", "magenta", "cyan"]
_PAIRS: dict[str, int] = {}

LOG_COLORS = {
    "roll": "cyan",
    "damage": "red",
    "heal": "green",
    "loot": "yellow",
    "level": "green",
    "death": "magenta",
    "system": "cyan",
    "warn": "yellow",
    "info": "white",
}


def setup_colors() -> None:
    """Allocate one pair per colour, plus a dim pair for remembered tiles."""
    curses.start_color()
    curses.use_default_colors()
    for index, name in enumerate(COLOR_NAMES, start=1):
        curses.init_pair(index, getattr(curses, f"COLOR_{name.upper()}"), -1)
        _PAIRS[name] = index


def colour(name: str, bold: bool = False, dim: bool = False, reverse: bool = False) -> int:
    attr = curses.color_pair(_PAIRS.get(name, _PAIRS.get("white", 0)))
    if bold:
        attr |= curses.A_BOLD
    if dim:
        attr |= curses.A_DIM
    if reverse:
        attr |= curses.A_REVERSE
    return attr


# --------------------------------------------------------------------------- #
# Wide-character aware output
# --------------------------------------------------------------------------- #


def char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def text_width(text: str) -> int:
    return sum(char_width(c) for c in text)


def clip(text: str, limit: int) -> str:
    """Trim text so it occupies at most ``limit`` terminal columns."""
    if limit <= 0:
        return ""
    out, used = [], 0
    for char in text:
        width = char_width(char)
        if used + width > limit:
            break
        out.append(char)
        used += width
    return "".join(out)


def pad(text: str, width: int) -> str:
    """Clip then pad to exactly ``width`` terminal columns."""
    text = clip(text, width)
    return text + " " * (width - text_width(text))


def write(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """``addstr`` that silently clips instead of raising at the screen edge."""
    height, width = win.getmaxyx()
    if not (0 <= y < height) or x >= width:
        return
    text = clip(text, width - x - 1)
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:  # pragma: no cover - bottom-right cell quirk
        pass


def centre(win, y: int, text: str, attr: int = 0) -> None:
    _, width = win.getmaxyx()
    write(win, y, max(0, (width - text_width(text)) // 2), text, attr)


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #


def viewport_size(win, world: World | None = None) -> tuple[int, int]:
    height, width = win.getmaxyx()
    return width, max(1, height - PANEL_HEIGHT - MAP_TOP)


def camera(world: World, view_w: int, view_h: int) -> tuple[int, int]:
    """Keep the acting hero centred, but never scroll past the map edges."""
    focus = world.current or world.party[0]
    left = focus.x - view_w // 2
    top = focus.y - view_h // 2
    left = max(0, min(left, world.dungeon.width - view_w))
    top = max(0, min(top, world.dungeon.height - view_h))
    return max(0, left), max(0, top)


def draw_map(win, world: World, cursor: tuple[int, int] | None = None, splash: set | None = None) -> None:
    view_w, view_h = viewport_size(win, world)
    left, top = camera(world, view_w, view_h)
    dungeon = world.dungeon
    splash = splash or set()

    for row in range(view_h):
        y = top + row
        for col in range(view_w - 1):
            x = left + col
            if not dungeon.in_bounds(x, y):
                continue
            spot = (x, y)
            if spot not in world.explored:
                continue
            lit = spot in world.visible
            glyph = TILE_GLYPHS[dungeon.tile(x, y)]
            attr = colour("white", dim=not lit)
            if glyph == ">":
                attr = colour("cyan", bold=lit, dim=not lit)
            write(win, MAP_TOP + row, col, glyph, attr)

    for chest in world.chests:
        if chest.opened or chest.position not in world.explored:
            continue
        _plot(win, chest.position, left, top, view_w, view_h, "$", colour("yellow", bold=True))

    for entity in world.living():
        if entity.team is Team.MONSTER and not world.can_see(entity):
            continue
        attr = colour(entity.color, bold=True)
        if entity is world.current:
            attr |= curses.A_REVERSE
        _plot(win, entity.position, left, top, view_w, view_h, entity.glyph, attr)

    for spot in splash:
        if spot in world.explored:
            _plot(win, spot, left, top, view_w, view_h, None, colour("red", reverse=True))

    if cursor is not None:
        _plot(win, cursor, left, top, view_w, view_h, None, colour("yellow", reverse=True, bold=True))


def _plot(win, spot, left, top, view_w, view_h, glyph, attr) -> None:
    col, row = spot[0] - left, spot[1] - top
    if not (0 <= col < view_w - 1 and 0 <= row < view_h):
        return
    if glyph is None:
        try:  # keep whatever is underneath, just repaint it highlighted
            glyph = chr(win.inch(MAP_TOP + row, col) & 0xFF)
        except curses.error:  # pragma: no cover
            glyph = " "
    write(win, MAP_TOP + row, col, glyph, attr)


# --------------------------------------------------------------------------- #
# Initiative strip
# --------------------------------------------------------------------------- #


def initiative_label(world: World, entity: Entity) -> str:
    """How a unit is named in the turn strip.

    Monsters the party cannot currently see stay anonymous — the strip should
    tell you the shape of the round, not where the sleeping ogre is.
    """
    if entity.team is Team.MONSTER and not world.can_see(entity):
        return "?"
    return f"{entity.glyph} {i18n.t(entity.name)}"


def draw_initiative(win, world: World) -> None:
    """Row 0: who is acting now and who comes next, in queue order."""
    _, width = win.getmaxyx()
    write(win, 0, 0, " " * (width - 1))

    current = world.current
    if current is None:
        return

    label = i18n.t("行動順序")
    write(win, 0, 0, label, colour("blue", bold=True))
    x = text_width(label) + 1
    entries = [(current, True)] + [(e, False) for e in world.upcoming(6)]
    for index, (entity, is_current) in enumerate(entries):
        label = initiative_label(world, entity)
        chunk = ("▶" if is_current else "") + label
        if x + text_width(chunk) + 2 >= width:
            write(win, 0, x, "…", colour("white", dim=True))
            break
        if index:
            write(win, 0, x - 2, "›", colour("blue", dim=True))
        hidden = label.startswith("?")
        tone = "white" if hidden else entity.color
        write(win, 0, x, chunk, colour(tone, bold=is_current, dim=hidden and not is_current))
        x += text_width(chunk) + 3


# --------------------------------------------------------------------------- #
# Bottom panel
# --------------------------------------------------------------------------- #


def bar(current: int, maximum: int, width: int = 10) -> str:
    filled = 0 if maximum <= 0 else max(0, min(width, round(current / maximum * width)))
    return "█" * filled + "░" * (width - filled)


def hp_colour(entity: Entity) -> str:
    ratio = entity.hp / entity.max_hp
    if ratio <= 0.25:
        return "red"
    if ratio <= 0.6:
        return "yellow"
    return "green"


def columns(width: int) -> list[tuple[int, int]]:
    """Split the panel into three equal columns with a divider between each."""
    usable = max(3, width - 1)
    each = (usable - 2) // 3
    return [
        (0, each),
        (each + 1, each),
        (2 * each + 2, usable - 2 * each - 2),
    ]


def draw_panel(win, world: World, hint: str = "", forecast: "Forecast | None" = None, face: int | None = None) -> None:
    """The bottom panel: party, actions and dice, combat log — one per column.

    ``face`` overrides the die number while a roll is being animated; ``forecast``
    previews the numbers a pending attack needs.
    """
    height, width = win.getmaxyx()
    top = height - PANEL_HEIGHT
    if top < 1:
        return

    header = i18n.t(
        " 第 {depth}/{max_depth} 層 ‧ 第 {round} 回合 ‧ Lv {level} ‧ 金幣 {gold} ‧ 擊殺 {kills} ",
        depth=world.depth,
        max_depth=MAX_DEPTH,
        round=world.round,
        level=world.level,
        gold=world.gold,
        kills=world.score.kills,
    )
    write(win, top, 0, "─" * (width - 1), colour("blue"))
    write(win, top, 2, header, colour("cyan", bold=True))

    # The one hint that has to be visible without already knowing the keys. It
    # rides the divider because the action column is full at 76 columns.
    prompt = i18n.t(" [h] 操作說明 ")
    prompt_x = width - 1 - text_width(prompt)
    if prompt_x > 2 + text_width(header):
        write(win, top, prompt_x, prompt, colour("yellow", bold=True))

    layout = columns(width)
    for x, _ in layout[1:]:
        for row in range(1, PANEL_HEIGHT):
            write(win, top + row, x - 1, "│", colour("blue"))

    _draw_party_column(win, top + 1, *layout[0], world)
    _draw_action_column(win, top + 1, *layout[1], world, hint, forecast, face)
    _draw_log_column(win, top + 1, *layout[2], world)


# -- column 1: the party ---------------------------------------------------- #


def _draw_party_column(win, top: int, x: int, width: int, world: World) -> None:
    row = top
    plan = gauge_plan(width - 3, world.party[:4])
    for member in world.party[:4]:
        _draw_member(win, row, x, width, member, world, plan)
        row += 2

    row = top + 9
    stock = [(items_id, count) for items_id, count in world.inventory.items() if count > 0]
    if stock:
        write(win, row, x + 1, i18n.t("背包"), colour("white", dim=True))
        for offset, (item_id, count) in enumerate(stock[:2], start=1):
            from ..core import items as items_mod

            name = i18n.t(items_mod.BY_ID[item_id].name)
            write(win, row + offset, x + 1, clip(f"{name} x{count}", width - 2), colour("yellow"))
    else:
        write(win, row, x + 1, i18n.t("背包是空的"), colour("white", dim=True))


def _draw_member(win, row: int, x: int, width: int, member: Entity, world: World, plan: "GaugePlan") -> None:
    active = member is world.current
    attr = colour(member.color, bold=active, dim=not member.is_alive)

    write(win, row, x, "▶" if active else " ", colour("yellow", bold=True))
    tag = f"P{member.owner + 1} " if world.is_hotseat and member.owner is not None else ""
    name = f"{tag}{member.glyph} {i18n.t(member.name)}"

    if not member.is_alive:
        write(win, row, x + 1, clip(name, width - 8), attr)
        write(win, row, x + width - 7, i18n.t("已陣亡"), colour("white", dim=True))
        return

    # Name row: the name, and any status right-aligned. The name clips to what
    # is left, so a long status shortens the name rather than colliding with it.
    status = member.status_summary()
    write(win, row, x + 1, clip(name, width - 2 - text_width(status)), attr)
    if status:
        write(win, row, x + width - text_width(status) - 1, status, colour("magenta"))

    # Gauge row: each resource reads bar-then-number, so HP and MP scan the same.
    x += 2
    if plan.caption:
        write(win, row + 1, x, "HP", colour("white", dim=True))
    write(win, row + 1, x + plan.caption * 3, bar(member.hp, member.max_hp, plan.hp_bar),
          colour(hp_colour(member)))
    write(win, row + 1, x + plan.hp_number, f"{member.hp}/{member.max_hp}".rjust(plan.hp_digits),
          colour(hp_colour(member), bold=active))
    if member.max_mp:
        # The MP number matters as much as the bar — a mage needs to know
        # whether the next nova is affordable, not roughly how blue the bar is.
        if plan.caption:
            write(win, row + 1, x + plan.mp_start, "MP", colour("white", dim=True))
        write(win, row + 1, x + plan.mp_start + plan.caption * 3,
              bar(member.mp, member.max_mp, plan.mp_bar), colour("blue"))
        write(win, row + 1, x + plan.mp_number, f"{member.mp}/{member.max_mp}".rjust(plan.mp_digits),
              colour("blue", bold=active))


# Preferred bar lengths; a cramped column shrinks them in this proportion.
HP_BAR, MP_BAR = 8, 5


@dataclass(frozen=True)
class GaugePlan:
    """Where every piece of `HP ████ 26/26 MP ███ 12/12` sits, party-wide."""

    caption: bool
    hp_bar: int
    mp_bar: int
    hp_digits: int
    mp_digits: int

    @property
    def hp_number(self) -> int:
        return self.caption * 3 + self.hp_bar + 1

    @property
    def mp_start(self) -> int:
        return self.hp_number + self.hp_digits + 1

    @property
    def mp_number(self) -> int:
        return self.mp_start + self.caption * 3 + self.mp_bar + 1


def gauge_plan(avail: int, party: list[Entity]) -> GaugePlan:
    """Size the gauge row once for the whole party, not once per hero.

    Numbers are budgeted first and the bars take what is left — a truncated
    number is a lie, a shorter bar is merely coarser. The widths come from the
    widest hero on screen so all four rows line up; sizing each row to its own
    numbers made the column look ragged, which reads as a bug. Below the width
    where each bar would drop under three cells the captions go too, since the
    colours already say which gauge is which.
    """
    hp_digits = max((len(f"{m.hp}/{m.max_hp}") for m in party), default=5)
    mp_digits = max((len(f"{m.mp}/{m.max_mp}") for m in party if m.max_mp), default=0)
    spare = avail - hp_digits - (mp_digits + 1 if mp_digits else 0)

    def bars(caption: bool) -> tuple[int, int]:
        room = spare - (4 if caption else 1) * (2 if mp_digits else 1)
        total = HP_BAR + (MP_BAR if mp_digits else 0)
        return (
            max(0, min(HP_BAR, room * HP_BAR // total)),
            max(0, min(MP_BAR, room * MP_BAR // total)) if mp_digits else 0,
        )

    hp_bar, mp_bar = bars(True)
    caption = hp_bar >= 3 and (not mp_digits or mp_bar >= 3)
    if not caption:
        hp_bar, mp_bar = bars(False)

    plan = GaugePlan(caption, hp_bar, mp_bar, hp_digits, mp_digits)
    leftover = avail - (plan.mp_number + mp_digits if mp_digits else plan.hp_number + hp_digits)
    return GaugePlan(caption, min(HP_BAR, hp_bar + max(0, leftover)), mp_bar, hp_digits, mp_digits)


# -- column 2: actions and dice --------------------------------------------- #


def _draw_action_column(
    win,
    top: int,
    x: int,
    width: int,
    world: World,
    hint: str,
    forecast: "Forecast | None",
    face: int | None,
) -> None:
    hero = world.hero
    if hero is None:
        write(win, top, x + 1, i18n.t("敵方行動中…"), colour("magenta", bold=True))
    else:
        seat = world.seat_label(hero.owner)
        name = i18n.t(hero.name)
        title = (
            i18n.t("{seat} ‧ {name} 的回合", seat=seat, name=name)
            if seat
            else i18n.t("{name} 的回合", name=name)
        )
        write(win, top, x + 1, clip(title, width - 2), colour(hero.color, bold=True))

        moves = i18n.t(
            "移動 {left}/{speed}", left=world.turn.moves_left, speed=hero.effective_speed
        )
        action = i18n.t("主要行動 已用") if world.turn.action_used else i18n.t("主要行動 可用")
        write(win, top + 1, x + 1, moves, colour("yellow" if world.turn.moves_left else "white", dim=not world.turn.moves_left))
        write(win, top + 1, x + 2 + text_width(moves), action,
              colour("white" if world.turn.action_used else "yellow", dim=world.turn.action_used))

        for index, ability in enumerate(hero.abilities[:3]):
            affordable = hero.mp >= ability.mp_cost
            label = f"[{index + 1}] {i18n.t(ability.name)}"
            write(win, top + 2 + index, x + 1, clip(label, width - 8),
                  colour("white", bold=affordable, dim=not affordable))
            cost = ability.cost_label()
            write(win, top + 2 + index, x + width - text_width(cost) - 1, cost,
                  colour("blue" if affordable else "white", dim=not affordable))

        if world.turn_spent:
            write(win, top + 5, x + 1, clip(i18n.t("這回合沒事做了 — 按 e 換下一位"), width - 2),
                  colour("yellow", bold=True))
        else:
            write(win, top + 5, x + 1, clip(i18n.t("[i]道具 [Tab]換人 [e]結束"), width - 2), colour("cyan"))

    _draw_dice(win, top + 6, x, width, world, hint, forecast, face)


@dataclass(frozen=True)
class Forecast:
    """What a pending attack needs to roll, shown while choosing a target."""

    ability: str
    target: str
    hits_on: int | None = None
    crits_on: int = 20
    detail: str = ""


def _draw_dice(
    win,
    top: int,
    x: int,
    width: int,
    world: World,
    hint: str,
    forecast: "Forecast | None",
    face: int | None,
) -> None:
    write(win, top, x, "─" * width, colour("blue", dim=True))

    roll = world.last_roll
    if forecast is not None:
        write(win, top + 1, x + 1, clip(f"{forecast.ability} → {forecast.target}", width - 2),
              colour("white", bold=True))
        write(win, top + 2, x + 1, clip(_odds_text(forecast.hits_on, forecast.crits_on), width - 2),
              colour("cyan"))
        _draw_die(win, top + 3, x + 1, face, "yellow")
        side = [forecast.detail] if forecast.detail else []
        side += wrap(hint, width - 10) if hint else []
        for offset, line in enumerate(side[:3]):
            write(win, top + 3 + offset, x + 9, clip(line, width - 10), colour("white", dim=offset > 0))
        return

    if hint:
        write(win, top + 1, x + 1, clip(hint, width - 2), colour("yellow", bold=True))

    if roll is None:
        if not hint:
            write(win, top + 1, x + 1, i18n.t("還沒擲過骰子"), colour("white", dim=True))
        _draw_die(win, top + 3, x + 1, None, "white")
        return

    title = i18n.t(
        "{name} 的 {ability}", name=i18n.t(roll.actor), ability=i18n.t(roll.ability)
    )
    if roll.target:
        title += i18n.t(" → {target}", target=i18n.t(roll.target))
    write(win, top + 1, x + 1, clip(title, width - 2), colour(roll.actor_color, bold=True))

    if roll.needed is not None:
        write(win, top + 2, x + 1, clip(_odds_text(roll.needed, 20), width - 2), colour("cyan"))
    elif roll.damage is not None:
        write(win, top + 2, x + 1, clip(i18n.t("自動命中，直接算傷害"), width - 2), colour("cyan"))
    elif roll.healing is not None:
        write(win, top + 2, x + 1, clip(i18n.t("治療"), width - 2), colour("cyan"))

    shown = face if face is not None else _die_value(roll)
    tone = "yellow" if face is not None else _die_colour(roll)
    _draw_die(win, top + 3, x + 1, shown, tone)

    if face is None:
        _draw_result(win, top + 3, x + 9, width - 10, roll)


def _odds_text(hits_on: int | None, crits_on: int) -> str:
    if hits_on is None:
        return i18n.t("自動命中，不需擲骰")
    if hits_on > 20:
        return i18n.t("只有 {crits} 才打得中", crits=crits_on)
    return i18n.t("{hits} 以上命中 ‧ {crits} 爆擊", hits=hits_on, crits=crits_on)


def _die_value(roll) -> int | None:
    if roll.check is not None:
        return roll.check.natural
    if roll.damage is not None:
        return roll.damage.total
    if roll.healing is not None:
        return roll.healing.total
    return None


def _die_colour(roll) -> str:
    if roll.check is None:
        return "green" if roll.healing is not None else "red"
    if roll.check.critical:
        return "yellow"
    if roll.check.fumble or not roll.check.success:
        return "white"
    return "green"


def _draw_die(win, row: int, x: int, value: int | None, tone: str) -> None:
    face = "??" if value is None else f"{value:>2}"
    attr = colour(tone, bold=True)
    write(win, row, x, "╭────╮", attr)
    write(win, row + 1, x, "│", attr)
    write(win, row + 1, x + 1, f" {face} ", colour(tone, bold=True, reverse=True))
    write(win, row + 1, x + 5, "│", attr)
    write(win, row + 2, x, "╰────╯", attr)


def _draw_result(win, row: int, x: int, width: int, roll) -> None:
    if roll.check is not None:
        total = f"{roll.check.natural}{roll.check.modifier:+d} = {roll.check.total}"
        write(win, row, x, clip(total, width), colour("white"))
        write(win, row + 1, x, clip(f"vs {roll.check.target}", width), colour("white", dim=True))
        write(win, row + 2, x, clip(roll.outcome, width), colour(_die_colour(roll), bold=True))
    if roll.damage is not None:
        write(win, row + (2 if roll.check is None else 1), x,
              clip(i18n.t("傷害 {n}", n=roll.damage.total), width), colour("red", bold=True))
    if roll.healing is not None:
        write(win, row + 2, x, clip(i18n.t("治療 {n}", n=roll.healing.total), width), colour("green", bold=True))


# -- column 3: the log ------------------------------------------------------- #


def wrap(text: str, width: int) -> list[str]:
    """Wrap by display width, preferring to break at spaces."""
    if width <= 1:
        return [text]
    lines: list[str] = []
    current = ""
    for chunk in _chunks(text):
        if text_width(current + chunk) <= width:
            current += chunk
        else:
            if current.strip():
                lines.append(current.rstrip())
            while text_width(chunk) > width:
                lines.append(clip(chunk, width))
                chunk = chunk[len(clip(chunk, width)):]
            current = chunk.lstrip() if not chunk.strip() else chunk
    if current.strip():
        lines.append(current.rstrip())
    return lines or [""]


def _chunks(text: str) -> list[str]:
    """Split into wrappable pieces at spaces, keeping runs of text together.

    A run that is too long for the column still gets split mid-word by the
    caller, but short phrases stay whole instead of breaking between two
    characters of the same word.
    """
    out: list[str] = []
    buffer = ""
    for char in text:
        if char == " ":
            if buffer:
                out.append(buffer)
                buffer = ""
            out.append(char)
        else:
            buffer += char
    if buffer:
        out.append(buffer)
    return out


def _draw_log_column(win, top: int, x: int, width: int, world: World) -> None:
    rendered: list[tuple[str, str]] = []
    for message in world.recent(20):
        # Wrapped to leave room for the two-space continuation indent, so the
        # indent never pushes the tail of a line off the column.
        for index, line in enumerate(wrap(message.display, width - 4)):
            rendered.append((("  " if index else "") + line, message.kind))

    # Bottom-aligned, so the newest line is always on the same row.
    visible = rendered[-PANEL_ROWS:]
    first = top + PANEL_ROWS - len(visible)
    for offset, (line, kind) in enumerate(visible):
        attr = colour(LOG_COLORS.get(kind, "white"), bold=kind in ("system", "death"))
        write(win, first + offset, x + 1, clip(line, width - 2), attr)


# --------------------------------------------------------------------------- #
# Overlays and full-screen views
# --------------------------------------------------------------------------- #


def draw_box(win, top: int, left: int, height: int, width: int, title: str = "") -> None:
    write(win, top, left, "┌" + "─" * (width - 2) + "┐", colour("blue"))
    for row in range(1, height - 1):
        write(win, top + row, left, "│" + " " * (width - 2) + "│", colour("blue"))
    write(win, top + height - 1, left, "└" + "─" * (width - 2) + "┘", colour("blue"))
    if title:
        write(win, top, left + 2, f" {title} ", colour("cyan", bold=True))


def draw_item_menu(win, world: World) -> None:
    from ..core import items as items_mod

    height, width = win.getmaxyx()
    entries = [(items_mod.BY_ID[key], count) for key, count in world.inventory.items() if count > 0]
    box_h = max(5, len(entries) + 4)
    box_w = min(56, width - 4)
    top, left = max(0, height // 2 - box_h - 2), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("道具"))

    if not entries:
        write(win, top + 2, left + 3, i18n.t("背包是空的 — 去開幾個寶箱吧。"), colour("white", dim=True))
    for index, (item, count) in enumerate(entries, start=1):
        label = clip(f"[{index}] {i18n.t(item.name)} x{count}", 22)
        write(win, top + 1 + index, left + 3, label, colour("yellow", bold=True))
        write(win, top + 1 + index, left + 25, clip(i18n.t(item.description), box_w - 28), colour("white"))
    write(win, top + box_h - 2, left + 3, i18n.t("數字鍵使用 ‧ Esc 取消"), colour("white", dim=True))


def draw_handoff(win, world: World, hero: Entity, previous: int | None) -> None:
    """The "pass the laptop" card shown when a new player is up."""
    height, width = win.getmaxyx()
    box_w = min(52, width - 4)
    box_h = 9
    top, left = max(0, height // 2 - box_h), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("換人"))

    seat = world.seat_label(hero.owner)
    centre_in_box(win, top + 2, left, box_w, i18n.t("輪到 {seat}", seat=seat), colour("cyan", bold=True))
    centre_in_box(
        win, top + 3, left, box_w, f"{hero.glyph} {i18n.t(hero.name)}", colour(hero.color, bold=True)
    )
    centre_in_box(
        win,
        top + 4,
        left,
        box_w,
        f"HP {hero.hp}/{hero.max_hp}" + (f"  MP {hero.mp}/{hero.max_mp}" if hero.max_mp else ""),
        colour(hp_colour(hero)),
    )

    if previous is not None:
        centre_in_box(
            win,
            top + 6,
            left,
            box_w,
            i18n.t("（{seat} 的回合結束）", seat=world.seat_label(previous)),
            colour("white", dim=True),
        )
    centre_in_box(win, top + 7, left, box_w, i18n.t("準備好就按任意鍵"), colour("yellow", bold=True))


def _gear_tags(gear) -> str:
    parts = []
    if gear.bonus_hit:
        parts.append(i18n.t("命中+{n}", n=gear.bonus_hit))
    if gear.bonus_damage:
        parts.append(i18n.t("傷害+{n}", n=gear.bonus_damage))
    if gear.bonus_ac:
        parts.append(i18n.t("護甲+{n}", n=gear.bonus_ac))
    return " ".join(parts)


def draw_shop(win, world: World, offers: list, cursor: int, pending_gear=None) -> None:
    """The between-floors merchant. ``offers`` is a list of
    ``(kind, obj, price)``; ``pending_gear`` is set while the player is choosing
    which hero should wear a just-picked piece of gear.
    """
    height, width = win.getmaxyx()
    box_w = min(60, width - 4)
    box_h = min(height - 2, len(offers) + 6)
    top, left = max(0, (height - box_h) // 2), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("商人"))

    write(
        win,
        top + 1,
        left + 3,
        clip(i18n.t("第 {depth} 層樓梯口 ‧ 下一層之前補給一下", depth=world.depth), box_w - 19),
        colour("white", dim=True),
    )
    write(win, top + 1, left + box_w - 16, i18n.t("金幣 {n}", n=world.gold), colour("yellow", bold=True))

    for index, (kind, obj, price) in enumerate(offers):
        row = top + 3 + index
        if row >= top + box_h - 2:
            break
        selected = index == cursor and pending_gear is None
        marker = "›" if selected else " "
        afford = world.gold >= price
        if kind == "consumable":
            owned = world.inventory.get(obj.id, 0)
            name = i18n.t(obj.name) + (i18n.t("（有 {n}）", n=owned) if owned else "")
            detail = i18n.t(obj.description)
        else:
            name = i18n.t(obj.name)
            detail = _gear_tags(obj)
        base = colour("yellow" if afford else "white", bold=selected, dim=not afford)
        write(win, row, left + 3, f"{marker} {name}", base)
        write(win, row, left + 26, clip(detail, box_w - 38), colour("white", dim=not afford))
        write(win, row, left + box_w - 9, i18n.t("{price:>4} 金", price=price), colour("yellow", dim=not afford))

    footer = top + box_h - 2
    if pending_gear is not None:
        picks = "  ".join(
            f"{i + 1} {i18n.t(h.name)}" for i, h in enumerate(world.living(Team.PARTY))
        )
        text = clip(i18n.t("裝備給誰？ {picks} ‧ Esc", picks=picks), box_w - 6)
        write(win, footer, left + 3, text, colour("cyan", bold=True))
    else:
        text = clip(i18n.t("↑↓ 選擇 ‧ Enter/數字 購買 ‧ e/> 下樓 ‧ Esc 離開"), box_w - 6)
        write(win, footer, left + 3, text, colour("white", dim=True))


def visible_monsters(world: World) -> list[Entity]:
    """Monsters the party can see right now, nearest to the acting unit first."""
    focus = world.current or world.party[0]
    seen = [m for m in world.living(Team.MONSTER) if world.can_see(m)]
    return sorted(seen, key=lambda m: distance(focus.position, m.position))


def draw_monsters(win, world: World) -> None:
    """A roll-call of what is on screen: health, armour, distance, state."""
    height, width = win.getmaxyx()
    monsters = visible_monsters(world)
    box_w = min(72, width - 4)
    box_h = min(height - 2, max(7, len(monsters) + 5))
    top, left = max(0, (height - box_h) // 2), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("怪物"))

    if not monsters:
        write(win, top + 2, left + 3, i18n.t("視線內沒有怪物。"), colour("white", dim=True))
    else:
        write(win, top + 1, left + 3, i18n.t("名稱"), colour("white", dim=True))
        write(win, top + 1, left + 24, i18n.t("生命"), colour("white", dim=True))
        write(win, top + 1, left + 44, i18n.t("護甲"), colour("white", dim=True))
        write(win, top + 1, left + 50, i18n.t("距離"), colour("white", dim=True))
        write(win, top + 1, left + 56, i18n.t("狀態"), colour("white", dim=True))

    focus = world.current or world.party[0]
    for index, monster in enumerate(monsters):
        row = top + 2 + index
        if row >= top + box_h - 2:
            write(
                win,
                row,
                left + 3,
                i18n.t("…另外還有 {n} 隻", n=len(monsters) - index),
                colour("white", dim=True),
            )
            break
        tone = hp_colour(monster)
        write(win, row, left + 3, clip(f"{monster.glyph} {i18n.t(monster.name)}", 20), colour(monster.color, bold=True))
        write(win, row, left + 24, f"{monster.hp}/{monster.max_hp}", colour(tone))
        write(win, row, left + 32, bar(monster.hp, monster.max_hp, 8), colour(tone))
        write(win, row, left + 44, str(monster.effective_ac), colour("white"))
        write(
            win,
            row,
            left + 50,
            clip(i18n.t("{n} 格", n=distance(focus.position, monster.position)), 5),
            colour("cyan"),
        )
        status = monster.status_summary()
        state = status or (i18n.t("警戒") if monster.awake else i18n.t("睡著"))
        write(win, row, left + 56, clip(state, box_w - 59),
              colour("magenta" if status else ("yellow" if monster.awake else "white"),
                     dim=not status and not monster.awake))

    write(win, top + box_h - 2, left + 3, i18n.t("按任意鍵返回"), colour("white", dim=True))


def legend_rows(world: World) -> list[tuple[str, str, str]]:
    """``(glyph, colour, meaning)`` for everything currently drawable.

    Built from the live world rather than hard-coded, so a new class or a new
    monster shows up here without anyone remembering to edit a list. Only
    monsters the party has actually met are listed — the legend explains the
    map, it does not leak the bestiary.
    """
    rows = [
        ("#", "white", i18n.t("牆壁 — 擋路，也擋住視線")),
        (".", "white", i18n.t("地板 — 走得過去")),
        (">", "cyan", i18n.t("往下一層的樓梯（站上去按 > 找商人）")),
        ("$", "yellow", i18n.t("寶箱 — 走上去自動開啟")),
    ]
    for hero in world.party:
        state = "" if hero.is_alive else i18n.t("（已陣亡）")
        rows.append((hero.glyph, hero.color, f"{i18n.t(hero.name)}{state}"))
    seen: dict[str, tuple[str, str]] = {}
    for monster in world.living(Team.MONSTER):
        if world.can_see(monster) and monster.glyph not in seen:
            seen[monster.glyph] = (monster.color, monster.name)
    for glyph, (tone, name) in seen.items():
        rows.append((glyph, tone, i18n.t("{name} — 敵人", name=i18n.t(name))))
    return rows


def draw_legend(win, world: World) -> None:
    """What every glyph and highlight on the map means."""
    height, width = win.getmaxyx()
    rows = legend_rows(world)
    notes = [
        i18n.t("反白黃底 = 游標所在的格子"),
        i18n.t("反白紅底 = 範圍技能會波及的格子"),
        i18n.t("反白單位 = 現在輪到它行動"),
        i18n.t("暗色      = 走過但目前看不到的地方"),
    ]
    box_w = min(60, width - 4)
    box_h = min(height - 2, len(rows) + len(notes) + 4)
    top, left = max(0, (height - box_h) // 2), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("圖例"))

    row = top + 1
    limit = top + box_h - 2
    for glyph, tone, meaning in rows:
        if row >= limit:
            break
        write(win, row, left + 4, glyph, colour(tone, bold=True))
        write(win, row, left + 8, clip(meaning, box_w - 12), colour("white"))
        row += 1
    if row < limit:
        row += 1
    for note in notes:
        if row >= limit:
            break
        write(win, row, left + 4, clip(note, box_w - 8), colour("white", dim=True))
        row += 1
    write(win, top + box_h - 2, left + 3, i18n.t("按任意鍵返回"), colour("white", dim=True))


def centre_in_box(win, row: int, left: int, box_w: int, text: str, attr: int = 0) -> None:
    write(win, row, left + max(1, (box_w - text_width(text)) // 2), text, attr)


def draw_help(win) -> None:
    lines = [
        i18n.t("移動        ← ↑ ↓ → 或 WASD（剩餘移動點數見中間欄）"),
        i18n.t("主要行動    1-3 使用技能，i 使用道具（每回合限一次）"),
        i18n.t("選擇目標    ← ↑ ↓ → 移動游標，Tab 切換目標，Enter 確認，Esc 取消"),
        i18n.t("換人        Tab（尚未行動時可讓下一位隊友先動）"),
        i18n.t("多人模式    輪到別人時會跳出交接畫面，按任意鍵接手；左欄 P1-P4 是各角色的主人"),
        i18n.t("結束回合    e 或空白鍵 — 回合不會自己結束，移動與行動可以任意順序使用"),
        i18n.t("下樓        > （需站在樓梯上，先開商人補給，再擲一次下樓）"),
        i18n.t("查看怪物    m — 列出視線內每隻怪物的生命、護甲、距離與狀態"),
        i18n.t("圖例        g — 地圖上每個符號與反白顏色的意思"),
        i18n.t("說明        h（或 ?）— 就是這一頁，隨時可以按"),
        i18n.t("其他        q 離開這一局"),
        "",
        i18n.t("行動順序    最上面一列由左至右就是接下來的出手順序，▶ 是現在輪到的"),
        i18n.t("            看不到的怪物只顯示 ? — 順序是真的，位置不會洩漏"),
        i18n.t("骰子        中間欄會先告訴你「幾點以上命中、幾點爆擊」，再擲給你看"),
        i18n.t("            20 必中且傷害骰翻倍，1 必失手"),
    ]
    height, width = win.getmaxyx()
    box_w = min(74, width - 2)
    box_h = len(lines) + 4
    top, left = max(0, (height - box_h) // 2), max(0, (width - box_w) // 2)
    draw_box(win, top, left, box_h, box_w, i18n.t("操作說明"))
    for index, text in enumerate(lines):
        write(win, top + 2 + index, left + 3, clip(text, box_w - 6), colour("white"))
    write(win, top + box_h - 2, left + 3, i18n.t("按任意鍵返回"), colour("white", dim=True))


def splash_tiles(world: World, ability: Ability, centre_spot: tuple[int, int]) -> set[tuple[int, int]]:
    if ability.radius <= 0:
        return {centre_spot}
    return {
        (x, y)
        for x, y in world.dungeon.walkable_tiles()
        if distance((x, y), centre_spot) <= ability.radius
    }
