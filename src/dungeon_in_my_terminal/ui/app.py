"""The curses application: menus, the play loop, and the run summary."""

from __future__ import annotations

import curses
import locale
import random

from .. import i18n
from ..core import classes as classes_mod, combat, items as items_mod
from ..core.abilities import Ability, TargetKind
from ..core.dungeon import MAX_DEPTH, distance
from ..core.entity import Entity, Team
from ..core.game import GameMode, Message, Phase, World
from . import render
from .render import colour, centre, write

MOVE_KEYS: dict[int, tuple[int, int]] = {
    curses.KEY_LEFT: (-1, 0),
    curses.KEY_RIGHT: (1, 0),
    curses.KEY_UP: (0, -1),
    curses.KEY_DOWN: (0, 1),
    ord("a"): (-1, 0),
    ord("d"): (1, 0),
    ord("w"): (0, -1),
    ord("s"): (0, 1),
}
"""Arrows and WASD. `hjkl` used to be here too, but `h` now opens the key list —
and half a vi set is worse than none, so the other three went with it."""

ESCAPE = 27
TAB = 9
ENTER_KEYS = (curses.KEY_ENTER, 10, 13)
ENEMY_TURN_DELAY_MS = 170
HIT_DELAY_MS = 110
DICE_SPIN_FRAMES = 7
DICE_SPIN_MS = 45
DICE_SETTLE_MS = 320

TITLE = [
    "██████╗ ██╗   ██╗███╗   ██╗ ██████╗ ███████╗ ██████╗ ███╗   ██╗",
    "██╔══██╗██║   ██║████╗  ██║██╔════╝ ██╔════╝██╔═══██╗████╗  ██║",
    "██║  ██║██║   ██║██╔██╗ ██║██║  ███╗█████╗  ██║   ██║██╔██╗ ██║",
    "██║  ██║██║   ██║██║╚██╗██║██║   ██║██╔══╝  ██║   ██║██║╚██╗██║",
    "██████╔╝╚██████╔╝██║ ╚████║╚██████╔╝███████╗╚██████╔╝██║ ╚████║",
    "╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝",
]


class App:
    def __init__(self, screen, seed: int | None = None) -> None:
        self.screen = screen
        self.seed = seed
        self.world: World | None = None
        self.seated: int | None = None
        """Which hotseat player is currently at the keyboard."""
        self._shown_roll = 0
        curses.curs_set(0)
        curses.set_escdelay(25)  # otherwise Esc takes a full second to register
        screen.keypad(True)
        render.setup_colors()

    # -- top level --------------------------------------------------------- #

    def run(self) -> None:
        while True:
            choice = self.main_menu()
            if choice == "quit":
                return
            if choice == "help":
                self.show_help()
                continue

            players = None
            if choice == "hotseat":
                players = self.choose_player_count()
                if players is None:
                    continue

            chosen = self.choose_party(players)
            if chosen is None:
                continue
            party, seats = chosen

            self.world = World(
                party,
                seed=self.seed,
                owners=seats,
                mode=GameMode.HOTSEAT if players else GameMode.SOLO,
            )
            self.world.observer = self._watch_roll
            self.seated = None
            self._shown_roll = 0
            self.play()
            if self.summary() == "quit":
                return

    def _too_small(self) -> bool:
        height, width = self.screen.getmaxyx()
        if height >= render.MIN_HEIGHT and width >= render.MIN_WIDTH:
            return False
        self.screen.erase()
        write(self.screen, 0, 0, i18n.t("終端機視窗太小了。"), colour("yellow", bold=True))
        write(
            self.screen,
            1,
            0,
            i18n.t("請放大到至少 {w} x {h}", w=render.MIN_WIDTH, h=render.MIN_HEIGHT),
            colour("white"),
        )
        write(self.screen, 2, 0, i18n.t("目前 {w} x {h}", w=width, h=height), colour("white", dim=True))
        self.screen.refresh()
        return True

    # -- menus ------------------------------------------------------------- #

    def main_menu(self) -> str:
        while True:
            if self._too_small():
                self.screen.getch()
                continue
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            top = max(0, height // 2 - 9)
            for index, line in enumerate(TITLE):
                if render.text_width(line) < width:
                    centre(self.screen, top + index, line, colour("magenta", bold=True))
            centre(self.screen, top + 7, i18n.t("終端機裡的地城 ‧ 骰子驅動的回合制探索"), colour("cyan"))
            centre(self.screen, top + 9, i18n.t("[1]  單人模式 — 一人指揮整支隊伍"), colour("white", bold=True))
            centre(self.screen, top + 10, i18n.t("[2]  多人 Hotseat — 2-4 人輪流用同一台電腦"), colour("white", bold=True))
            centre(self.screen, top + 11, i18n.t("[3]  操作說明"), colour("white"))
            centre(self.screen, top + 12, i18n.t("[q]  離開"), colour("white"))
            self.screen.refresh()

            key = self.screen.getch()
            if key in (ord("1"), *ENTER_KEYS):
                return "solo"
            if key == ord("2"):
                return "hotseat"
            if key in (ord("3"), ord("h"), ord("?")):
                return "help"
            if key in (ord("q"), ESCAPE):
                return "quit"

    def choose_player_count(self) -> int | None:
        while True:
            if self._too_small():
                self.screen.getch()
                continue
            self.screen.erase()
            height, _ = self.screen.getmaxyx()
            top = max(0, height // 2 - 5)
            centre(self.screen, top, i18n.t("多人 Hotseat"), colour("cyan", bold=True))
            centre(self.screen, top + 2, i18n.t("有幾個人要玩？"), colour("white", bold=True))
            for offset, count in enumerate((2, 3, 4)):
                centre(
                    self.screen,
                    top + 4 + offset,
                    i18n.t("[{count}]  {count} 人", count=count),
                    colour("white"),
                )
            centre(
                self.screen,
                top + 9,
                i18n.t("每個人至少操作一名角色，隊伍最多 4 人。"),
                colour("white", dim=True),
            )
            centre(self.screen, top + 10, i18n.t("Esc 返回"), colour("white", dim=True))
            self.screen.refresh()

            key = self.screen.getch()
            if key in (ord("2"), ord("3"), ord("4")):
                return key - ord("0")
            if key in (ESCAPE, ord("q")):
                return None

    def show_help(self) -> None:
        self.screen.erase()
        render.draw_help(self.screen)
        self.screen.refresh()
        self.screen.getch()

    def choose_party(
        self, players: int | None = None
    ) -> tuple[list[classes_mod.HeroClass], list[int] | None] | None:
        """Pick the party. In hotseat the seats take turns choosing."""
        picked: list[classes_mod.HeroClass] = []
        seats: list[int] = []

        while True:
            if self._too_small():
                self.screen.getch()
                continue
            turn_of = len(picked) % players if players else None
            enough = len(picked) >= (players or 1)

            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if players:
                centre(
                    self.screen,
                    1,
                    i18n.t(
                        "組隊 — 輪到 玩家 {n} 選擇（{players} 人，隊伍最多 4 人）",
                        n=turn_of + 1,
                        players=players,
                    ),
                    colour("cyan", bold=True),
                )
            else:
                centre(self.screen, 1, i18n.t("組隊 — 最多 4 人，職業可以重複"), colour("cyan", bold=True))

            for index, hero in enumerate(classes_mod.CLASSES):
                row = 3 + index * 3
                write(
                    self.screen,
                    row,
                    4,
                    f"[{index + 1}] {i18n.t(hero.name)}",
                    colour(hero.color, bold=True),
                )
                write(self.screen, row, 18, render.clip(i18n.t(hero.role), 17), colour("white"))
                write(
                    self.screen,
                    row,
                    36,
                    i18n.t(
                        "HP {hp}  MP {mp}  AC {ac}  移動 {speed}",
                        hp=hero.max_hp,
                        mp=hero.max_mp,
                        ac=hero.armor_class,
                        speed=hero.speed,
                    ),
                    colour("white", dim=True),
                )
                write(
                    self.screen,
                    row + 1,
                    8,
                    render.clip(i18n.t(hero.blurb), width - 12),
                    colour("white", dim=True),
                )

            if picked:
                roster = "  ".join(
                    (
                        i18n.t("玩家 {n}：{name}", n=seats[i] + 1, name=i18n.t(h.name))
                        if players
                        else f"{i + 1}. {i18n.t(h.name)}"
                    )
                    for i, h in enumerate(picked)
                )
            else:
                roster = i18n.t("（還沒有人）")
            roster_row = 3 + len(classes_mod.CLASSES) * 3
            write(self.screen, roster_row, 4, i18n.t("隊伍："), colour("yellow", bold=True))
            write(self.screen, roster_row, 12, render.clip(roster, width - 14), colour("yellow"))

            hints = [i18n.t("數字鍵加入"), i18n.t("Backspace 移除")]
            if enough:
                hints.append(i18n.t("Enter 出發"))
            elif players:
                hints.append(i18n.t("還有 {n} 人要選", n=players - len(picked)))
            hints.append(i18n.t("Esc 返回"))
            centre(
                self.screen,
                min(height - 2, roster_row + 2),
                " ‧ ".join(hints),
                colour("white", dim=True),
            )
            if players and len(picked) >= players:
                centre(
                    self.screen,
                    min(height - 3, roster_row + 1),
                    i18n.t("還可以再加角色，多出來的會輪流分給各位玩家。"),
                    colour("white", dim=True),
                )
            self.screen.refresh()

            key = self.screen.getch()
            if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                if len(picked) < 4:
                    picked.append(classes_mod.CLASSES[key - ord("1")])
                    if turn_of is not None:
                        seats.append(turn_of)
            elif key in (curses.KEY_BACKSPACE, 127, 8) and picked:
                picked.pop()
                if seats:
                    seats.pop()
            elif key in ENTER_KEYS and enough:
                return picked, (seats if players else None)
            elif key in (ESCAPE, ord("q")):
                return None

    # -- play loop --------------------------------------------------------- #

    def play(self) -> None:
        world = self.world
        assert world is not None
        while not world.is_over:
            if self._too_small():
                self.screen.getch()
                continue
            self.pass_the_keyboard()
            if world.is_over:
                return
            self.draw()
            key = self.screen.getch()

            if key == curses.KEY_RESIZE:
                continue
            if world.hero is None:
                world.end_turn()
                continue
            if self._handle_key(key) == "abort":
                return

    def pass_the_keyboard(self) -> None:
        """In hotseat, stop and announce whenever the seat changes hands.

        Without this the next player inherits a screen mid-turn and has no
        idea the previous one has finished.
        """
        world = self.world
        assert world is not None
        hero = world.hero
        if not world.is_hotseat or hero is None or hero.owner == self.seated:
            return

        previous = self.seated
        self.seated = hero.owner
        self.draw()
        render.draw_handoff(self.screen, world, hero, previous)
        self.screen.refresh()
        while True:
            key = self.screen.getch()
            if key not in (curses.KEY_RESIZE,):
                return
            self.draw()
            render.draw_handoff(self.screen, world, hero, previous)
            self.screen.refresh()

    def _handle_key(self, key: int) -> str | None:
        world = self.world
        assert world is not None
        hero = world.hero
        if hero is None:
            return None

        if key in MOVE_KEYS:
            world.move_hero(*MOVE_KEYS[key])
        elif ord("1") <= key <= ord("9"):
            index = key - ord("1")
            if index < len(hero.abilities):
                self.use_ability(hero, hero.abilities[index])
        elif key == ord("i"):
            self.item_menu()
        elif key == TAB:
            world.delay_turn()
        elif key in (ord("e"), ord(" ")):
            world.end_turn()
        elif key == ord(">"):
            self.try_descend()
        elif key == ord("m"):
            self.show_overlay(render.draw_monsters)
        elif key == ord("g"):
            self.show_overlay(render.draw_legend)
        elif key in (ord("h"), ord("?")):
            self.show_help()
        elif key == ord("q"):
            if self.confirm(i18n.t("要放棄這一局嗎？（這局的隊伍不會保留）")):
                world.phase = Phase.DEFEAT
                world.log(i18n.t("你們決定撤退 — 但地城不接受撤退。"), "system")
                return "abort"
        return None

    def show_overlay(self, draw) -> None:
        """Draw a read-only card over the map until any key dismisses it.

        These cost nothing — no turn, no action — so they stay outside the
        turn machinery entirely.
        """
        world = self.world
        assert world is not None
        while True:
            self.draw()
            draw(self.screen, world)
            self.screen.refresh()
            if self.screen.getch() != curses.KEY_RESIZE:
                return

    def try_descend(self) -> None:
        """Pressing ``>`` on the stairs: browse the merchant, then go down."""
        world = self.world
        assert world is not None
        hero = world.hero
        on_stairs = hero is not None and hero.position == world.dungeon.stairs
        if on_stairs and world.depth < MAX_DEPTH:
            if not self.visit_shop():
                return  # player backed out of the merchant — stay put
        world.descend()

    def visit_shop(self) -> bool:
        """Run the merchant screen. Returns True to descend, False to cancel."""
        world = self.world
        assert world is not None
        cursor = 0
        pending = None  # a Gear waiting for the player to name who wears it

        while True:
            offers = [("consumable", item, price) for item, price in world.shop_consumables()]
            offers += [("gear", gear, gear.price) for gear in world.shop_gear()]
            self.draw()
            render.draw_shop(self.screen, world, offers, cursor, pending)
            self.screen.refresh()
            key = self.screen.getch()

            if pending is not None:
                if key == ESCAPE:
                    pending = None
                elif ord("1") <= key <= ord("9"):
                    living = world.living(Team.PARTY)
                    index = key - ord("1")
                    if index < len(living):
                        world.buy_gear(pending, living[index])
                        pending = None
                continue

            if key == ESCAPE:
                return False
            if key in (ord("e"), ord(">"), ord(" ")):
                return True
            if key == curses.KEY_UP:
                cursor = (cursor - 1) % len(offers)
            elif key == curses.KEY_DOWN:
                cursor = (cursor + 1) % len(offers)
            elif key in ENTER_KEYS or ord("1") <= key <= ord("9"):
                if ord("1") <= key <= ord("9"):
                    cursor = key - ord("1")
                if not 0 <= cursor < len(offers):
                    continue
                kind, obj, price = offers[cursor]
                if kind == "consumable":
                    world.buy_consumable(obj)
                elif world.gold >= price:
                    pending = obj  # gear needs a wearer next
                else:
                    world.log(i18n.t("金幣不夠。"), "warn")

    def use_ability(self, hero: Entity, ability: Ability) -> None:
        world = self.world
        assert world is not None

        reason = combat.blocked_reason(world, hero, ability)
        if reason:
            world.log(
                i18n.t("{ability}：{reason}。", ability=i18n.t(ability.name), reason=reason),
                "warn",
            )
            return

        if ability.target is TargetKind.SELF and ability.radius > 0:
            if not self._confirm_burst(hero, ability):
                return
            world.use_ability(ability, hero)
            return

        target = self.pick_target(hero, ability)
        if target is None and ability.target is not TargetKind.SELF:
            return
        world.use_ability(ability, target)

    def item_menu(self) -> None:
        world = self.world
        assert world is not None
        entries = [(items_mod.BY_ID[key], count) for key, count in world.inventory.items() if count > 0]

        while True:
            self.draw()
            render.draw_item_menu(self.screen, world)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ESCAPE, ord("i"), ord("q")):
                return
            if ord("1") <= key <= ord("9"):
                index = key - ord("1")
                if index >= len(entries):
                    continue
                item = entries[index][0]
                hero = world.hero
                if hero is None:
                    return
                target: Entity | tuple[int, int] | None = hero
                if item.ability.target is not TargetKind.SELF:
                    target = self.pick_target(hero, item.ability)
                    if target is None:
                        return
                world.use_item(item, target)
                return

    # -- targeting --------------------------------------------------------- #

    def pick_target(self, hero: Entity, ability: Ability) -> Entity | tuple[int, int] | None:
        world = self.world
        assert world is not None

        if ability.target is TargetKind.SELF:
            return hero
        if ability.target is TargetKind.TILE:
            return self._pick_tile(hero, ability)
        return self._pick_entity(hero, ability)

    def _confirm_burst(self, hero: Entity, ability: Ability) -> bool:
        """Show a self-centred blast before it goes off.

        A nova has no target to pick, so it used to fire the instant the key
        was pressed — the only ability in the game that spent MP without
        showing what it would hit first. It now previews like everything else.
        """
        world = self.world
        assert world is not None
        splash = render.splash_tiles(world, ability, hero.position)
        caught = combat.burst_victims(world, hero, ability, hero.position)
        names = "、".join(i18n.t(e.name) for e in caught)
        preview = render.Forecast(
            ability=i18n.t(ability.name),
            target=i18n.t("以 {name} 為中心", name=i18n.t(hero.name)),
            hits_on=None,
            detail=i18n.t("波及 {names}", names=names) if caught else i18n.t("目前不會打到任何人"),
        )
        hint = i18n.t("Enter 施放 ‧ Esc 取消")
        while True:
            self.draw(cursor=hero.position, splash=splash, hint=hint, forecast=preview)
            key = self.screen.getch()
            if key in ENTER_KEYS:
                return True
            if key in (ESCAPE, ord("q")):
                return False

    def _pick_entity(self, hero: Entity, ability: Ability) -> Entity | None:
        world = self.world
        assert world is not None
        candidates = combat.valid_targets(world, hero, ability)
        if not candidates:
            world.log(
                i18n.t("{ability}：射程內沒有目標。", ability=i18n.t(ability.name)), "warn"
            )
            return None

        index = 0
        while True:
            target = candidates[index]
            odds = combat.forecast(world, hero, ability, target)
            preview = render.Forecast(
                ability=i18n.t(ability.name),
                target=i18n.t(target.name),
                hits_on=odds[0] if odds else None,
                crits_on=odds[1] if odds else 20,
                detail=f"HP {target.hp}/{target.max_hp} ‧ AC {target.armor_class}",
            )
            hint = i18n.t("Tab 換目標 ‧ Enter 確認 ‧ Esc 取消")
            self.draw(cursor=target.position, hint=hint, forecast=preview)
            key = self.screen.getch()
            if key in ENTER_KEYS:
                return target
            if key in (ESCAPE, ord("q")):
                return None
            if key in (TAB, curses.KEY_RIGHT, curses.KEY_DOWN, ord("d"), ord("s")):
                index = (index + 1) % len(candidates)
            elif key in (curses.KEY_LEFT, curses.KEY_UP, ord("a"), ord("w")):
                index = (index - 1) % len(candidates)

    def _pick_tile(self, hero: Entity, ability: Ability) -> tuple[int, int] | None:
        world = self.world
        assert world is not None
        cursor = hero.position
        enemies = [m for m in world.living(Team.MONSTER) if world.can_see(m)]
        if enemies:
            cursor = min(enemies, key=lambda m: distance(hero.position, m.position)).position

        while True:
            reachable = combat.in_range(world, hero, ability, cursor)
            splash = render.splash_tiles(world, ability, cursor) if reachable else set()
            caught = [
                i18n.t(e.name)
                for e in world.living()
                if e.position in splash and (ability.friendly_fire or e.team is not hero.team)
            ]
            preview = render.Forecast(
                ability=i18n.t(ability.name),
                target=i18n.t("這一格") if reachable else i18n.t("超出射程"),
                hits_on=None,
                detail=i18n.t("波及 {names}", names="、".join(caught))
                if caught
                else i18n.t("目前不會打到任何人"),
            )
            hint = i18n.t("方向鍵選格 ‧ Enter 引爆 ‧ Esc 取消")
            self.draw(cursor=cursor, splash=splash, hint=hint, forecast=preview)

            key = self.screen.getch()
            if key in ENTER_KEYS and reachable:
                return cursor
            if key in (ESCAPE, ord("q")):
                return None
            if key in MOVE_KEYS:
                dx, dy = MOVE_KEYS[key]
                spot = (cursor[0] + dx, cursor[1] + dy)
                if world.dungeon.in_bounds(*spot):
                    cursor = spot

    # -- drawing ----------------------------------------------------------- #

    def draw(
        self,
        cursor: tuple[int, int] | None = None,
        splash: set | None = None,
        hint: str = "",
        forecast: render.Forecast | None = None,
        face: int | None = None,
    ) -> None:
        world = self.world
        if world is None:
            return
        self.screen.erase()
        render.draw_initiative(self.screen, world)
        render.draw_map(self.screen, world, cursor=cursor, splash=splash)
        render.draw_panel(self.screen, world, hint=hint, forecast=forecast, face=face)
        self.screen.refresh()

    def _watch_roll(self, message: Message) -> None:
        """Play each roll out on screen instead of jumping to the aftermath.

        Fires for heroes and monsters alike — the die spins, settles on the
        number the engine actually rolled, then the damage lands.
        """
        world = self.world
        if world is None or not world.explored:
            return  # mid floor-change: there is nothing sensible to draw yet

        roll = world.last_roll
        if message.kind == "roll" and roll is not None and roll.serial != self._shown_roll:
            self._shown_roll = roll.serial
            for _ in range(DICE_SPIN_FRAMES):
                self.draw(face=random.randint(1, 20))
                curses.napms(DICE_SPIN_MS)
            self.draw()
            curses.napms(DICE_SETTLE_MS)
            return

        if message.kind in ("damage", "heal", "death"):
            self.draw()
            curses.napms(ENEMY_TURN_DELAY_MS if world.hero is None else HIT_DELAY_MS)
        elif message.kind == "warn" and world.hero is None:
            self.draw()
            curses.napms(ENEMY_TURN_DELAY_MS)

    # -- prompts and summary ------------------------------------------------ #

    def confirm(self, question: str) -> bool:
        height, width = self.screen.getmaxyx()
        box_w = min(60, width - 4)
        top, left = height // 2 - 2, max(0, (width - box_w) // 2)
        render.draw_box(self.screen, top, left, 5, box_w, i18n.t("確認"))
        write(self.screen, top + 2, left + 3, render.clip(question, box_w - 6), colour("yellow", bold=True))
        write(self.screen, top + 3, left + 3, i18n.t("[y] 是   [n] 否"), colour("white", dim=True))
        self.screen.refresh()
        while True:
            key = self.screen.getch()
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N"), ESCAPE):
                return False

    def _seat_scoreboard(self, world: World) -> list[tuple[str, str]]:
        """Per-player kills and survivors, best first. Empty outside hotseat."""
        if not world.is_hotseat:
            return []
        rows = []
        for seat in world.seats:
            kills = world.score.kills_by_seat.get(seat, 0)
            heroes = world.heroes_of(seat)
            survivors = [i18n.t(h.name) for h in heroes if h.is_alive]
            state = (
                i18n.t("生還：{names}", names="、".join(survivors))
                if survivors
                else i18n.t("全員陣亡")
            )
            rows.append((seat, kills, i18n.t("擊殺 {kills}　{state}", kills=kills, state=state)))
        rows.sort(key=lambda row: row[1], reverse=True)
        return [(world.seat_label(seat), detail) for seat, _, detail in rows]

    def summary(self) -> str:
        world = self.world
        assert world is not None
        score = world.score
        won = world.phase is Phase.VICTORY

        lines = [
            (i18n.t("到達層數"), f"{score.depth_reached} / {MAX_DEPTH}"),
            (i18n.t("隊伍等級"), f"Lv {world.level}"),
            (i18n.t("擊殺數"), str(score.kills)),
            (i18n.t("拾獲金幣"), str(score.gold)),
            (i18n.t("開啟寶箱"), str(score.chests_opened)),
            (i18n.t("總回合數"), str(score.rounds)),
            (
                i18n.t("陣亡"),
                "、".join(i18n.t(name) for name in score.fallen) or i18n.t("無"),
            ),
            (i18n.t("總分"), str(score.points)),
        ]
        seat_lines = self._seat_scoreboard(world)

        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            top = max(0, height // 2 - 8)
            if won:
                centre(self.screen, top, i18n.t("★  地 城 通 關  ★"), colour("yellow", bold=True))
                centre(self.screen, top + 2, i18n.t("王座空了，你們帶著戰利品走出地城。"), colour("green"))
            else:
                centre(self.screen, top, i18n.t("☠  全 隊 覆 滅  ☠"), colour("red", bold=True))
                centre(self.screen, top + 2, i18n.t("地城吞下了這支隊伍。下一支呢？"), colour("magenta"))

            for index, (label, value) in enumerate(lines):
                row = top + 4 + index
                left = max(0, width // 2 - 16)
                write(self.screen, row, left, label, colour("white", dim=True))
                write(self.screen, row, left + 14, value, colour("cyan", bold=True))

            row = top + 4 + len(lines)
            if seat_lines:
                row += 1
                centre(self.screen, row, i18n.t("各玩家戰績"), colour("yellow", bold=True))
                for offset, (label, detail) in enumerate(seat_lines, start=1):
                    left = max(0, width // 2 - 16)
                    write(self.screen, row + offset, left, label, colour("cyan", bold=True))
                    write(self.screen, row + offset, left + 14, detail, colour("white"))
                row += len(seat_lines)

            centre(self.screen, row + 2, i18n.t("種子碼 {seed}", seed=world.seed), colour("white", dim=True))
            centre(
                self.screen,
                row + 4,
                i18n.t("[r] 重新產生地城再戰一局    [q] 離開"),
                colour("white", bold=True),
            )
            self.screen.refresh()

            key = self.screen.getch()
            if key in (ord("r"), *ENTER_KEYS):
                return "again"
            if key in (ord("q"), ESCAPE):
                return "quit"


def launch(seed: int | None = None) -> None:
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(lambda screen: App(screen, seed=seed).run())
