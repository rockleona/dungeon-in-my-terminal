"""The run: floors, turn order, and the state the UI draws.

``World`` owns everything mutable about a single run and exposes the handful
of verbs the interface needs — move, act, end turn, descend. It never imports
curses, so a whole run can be played headlessly in a test.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from . import (
    combat,
    dice,
    dungeon as dungeon_mod,
    items as items_mod,
    monsters as monsters_mod,
    shop as shop_mod,
)
from .abilities import Ability, TargetKind
from .classes import HeroClass
from .dungeon import Dungeon, distance, has_line_of_sight
from .entity import STAT_NAMES, Entity, Status, Team
from .items import ItemDef
from .shop import Gear

VISION_RADIUS = 7
LOG_LIMIT = 400
REST_HP_FRACTION = 0.35
REST_MP_FRACTION = 0.6
EMPTY_ROOM_CHANCE = 0.3
"""Not every room holds a fight — quiet rooms give the party room to breathe."""

XP_PER_LEVEL = 55
"""Party XP needed for the ``n``-th level-up is ``XP_PER_LEVEL * n`` — the cost
climbs so late floors' fatter monsters don't trivialise levelling."""
STAT_UP_EVERY = 3
"""Every this-many levels, each hero's primary stat goes up by ``STAT_UP_AMOUNT``."""
STAT_UP_AMOUNT = 2
"""Two points, not one. Modifiers are ``(score - 10) // 2``, so an odd point
buys nothing you can see — a stat-up that does not move to-hit or damage is
exactly the flat levelling this was tuned away from."""


class Phase(str, Enum):
    PLAYING = "playing"
    VICTORY = "victory"
    DEFEAT = "defeat"


class GameMode(str, Enum):
    SOLO = "solo"  # one person drives the whole party
    HOTSEAT = "hotseat"  # several people share the keyboard, one seat each


@dataclass
class Message:
    text: str
    kind: str = "info"
    repeats: int = 1

    @property
    def display(self) -> str:
        return self.text if self.repeats == 1 else f"{self.text} ×{self.repeats}"


@dataclass
class Chest:
    x: int
    y: int
    opened: bool = False

    @property
    def position(self) -> tuple[int, int]:
        return self.x, self.y


@dataclass
class Score:
    depth_reached: int = 1
    kills: int = 0
    gold: int = 0
    rounds: int = 0
    chests_opened: int = 0
    fallen: list[str] = field(default_factory=list)
    victory: bool = False
    kills_by_seat: dict[int, int] = field(default_factory=dict)
    """Kills credited per hotseat seat — the bragging rights table."""

    @property
    def points(self) -> int:
        return self.depth_reached * 100 + self.gold + self.kills * 10 + (1000 if self.victory else 0)


def _default_names(hero_classes: list[HeroClass]) -> list[str]:
    """Number repeated classes so a party of four warriors is still readable."""
    totals: dict[str, int] = {}
    for hero in hero_classes:
        totals[hero.id] = totals.get(hero.id, 0) + 1

    seen: dict[str, int] = {}
    names = []
    for hero in hero_classes:
        seen[hero.id] = seen.get(hero.id, 0) + 1
        names.append(hero.name if totals[hero.id] == 1 else f"{hero.name} {seen[hero.id]}")
    return names


@dataclass
class TurnState:
    """What the unit currently taking its turn has left to spend."""

    moves_left: int = 0
    action_used: bool = False


@dataclass
class RollReport:
    """The most recent dice roll, kept around so the interface can show it.

    The rules do not read this back — it exists purely so the dice panel can
    display (and animate) what the engine just rolled.
    """

    serial: int
    actor: str
    actor_color: str
    ability: str
    target: str | None = None
    check: "dice.Check | None" = None
    damage: "dice.Roll | None" = None
    healing: "dice.Roll | None" = None
    hostile: bool = False
    """True when a monster rolled it — the panel tints those differently."""

    @property
    def needed(self) -> int | None:
        """The natural d20 this roll had to beat, or None if it wasn't a check."""
        if self.check is None:
            return None
        # A natural 1 always misses, so 2 is the lowest number that can matter;
        # anything above 20 means only a critical connects.
        return max(2, self.check.target - self.check.modifier)

    @property
    def outcome(self) -> str:
        if self.check is None:
            return ""
        if self.check.critical:
            return "重擊！"
        if self.check.fumble:
            return "大失敗"
        return "命中" if self.check.success else "落空"


class World:
    """A single run, from the first floor to the wipe (or the Abyss Lord)."""

    def __init__(
        self,
        hero_classes: list[HeroClass],
        seed: int | None = None,
        names: list[str] | None = None,
        owners: list[int] | None = None,
        mode: GameMode = GameMode.SOLO,
    ):
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.depth = 0
        self.phase = Phase.PLAYING
        self.messages: list[Message] = []
        self.score = Score()
        self.inventory: dict[str, int] = {}
        self.gold = 0
        """Spendable purse. ``score.gold`` is the lifetime total for scoring;
        this is what is actually left to hand the merchant."""
        self.xp = 0
        self.level = 1
        """One party-wide level: everyone grows together, so a support cleric is
        never left behind a kill-hungry warrior."""
        self.round = 1
        self.observer: Callable[[Message], None] | None = None
        self.mode = mode
        self.last_roll: RollReport | None = None
        self._roll_serial = 0

        names = names or _default_names(hero_classes)
        self.party: list[Entity] = [
            hero.spawn(names[i] if i < len(names) else None) for i, hero in enumerate(hero_classes)
        ]
        if owners is not None:
            for hero, seat in zip(self.party, owners):
                hero.owner = seat
        self.entities: list[Entity] = list(self.party)
        self.chests: list[Chest] = []
        self.order: list[Entity] = []
        self.turn_index = 0
        self.turn = TurnState()
        self._ticked: set[int] = set()
        self.explored: set[tuple[int, int]] = set()
        self.visible: set[tuple[int, int]] = set()
        self.dungeon: Dungeon = dungeon_mod.generate(1, self.rng)

        self.enter_floor(1)

    # -- logging ----------------------------------------------------------- #

    def log(self, text: str, kind: str = "info") -> None:
        # Bumping into the same wall five times should read as one line, not
        # five — otherwise a stray key press scrolls the whole log away.
        if self.messages and self.messages[-1].text == text:
            message = self.messages[-1]
            message.repeats += 1
        else:
            message = Message(text, kind)
            self.messages.append(message)
            del self.messages[:-LOG_LIMIT]
        if self.observer is not None:
            # Lets the UI animate enemy turns instead of dumping the whole
            # monster phase on screen at once.
            self.observer(message)

    def recent(self, count: int) -> list[Message]:
        return self.messages[-count:]

    # -- dice, for the interface to display --------------------------------- #

    def note_roll(
        self,
        actor: Entity,
        ability_name: str,
        target: Entity | None = None,
        check: "dice.Check | None" = None,
    ) -> RollReport:
        """Record a roll before it is logged, so the UI can animate it."""
        self._roll_serial += 1
        self.last_roll = RollReport(
            serial=self._roll_serial,
            actor=actor.name,
            actor_color=actor.color,
            ability=ability_name,
            target=target.name if target is not None else None,
            check=check,
            hostile=actor.team is Team.MONSTER,
        )
        return self.last_roll

    # -- entity queries ---------------------------------------------------- #

    def living(self, team: Team | None = None) -> list[Entity]:
        return [e for e in self.entities if e.is_alive and (team is None or e.team is team)]

    def entity_at(self, spot: tuple[int, int]) -> Entity | None:
        return next((e for e in self.living() if e.position == spot), None)

    def chest_at(self, spot: tuple[int, int]) -> Chest | None:
        return next((c for c in self.chests if not c.opened and c.position == spot), None)

    @property
    def hero(self) -> Entity | None:
        """The hero whose turn it is, or ``None`` while monsters are acting."""
        current = self.current
        return current if current is not None and current.team is Team.PARTY else None

    @property
    def current(self) -> Entity | None:
        if not self.order:
            return None
        return self.order[self.turn_index % len(self.order)]

    def upcoming(self, count: int = 6) -> list[Entity]:
        """Who acts after the current unit, in queue order.

        One interleaved queue holds heroes and monsters alike, so "whose turn
        is next" is not guessable from the party list — the UI shows this as a
        strip. Walks each slot at most once, so the fallen drop out and the
        list wraps into the next round without repeating anyone.
        """
        if not self.order:
            return []
        ahead: list[Entity] = []
        for step in range(1, len(self.order) + 1):
            actor = self.order[(self.turn_index + step) % len(self.order)]
            if actor.is_alive:
                ahead.append(actor)
            if len(ahead) >= count:
                break
        return ahead

    # -- seats (hotseat play) ---------------------------------------------- #

    @property
    def is_hotseat(self) -> bool:
        return self.mode is GameMode.HOTSEAT

    @property
    def seats(self) -> list[int]:
        """Seat numbers in play, in the order the players sat down."""
        return sorted({hero.owner for hero in self.party if hero.owner is not None})

    def seat_label(self, seat: int | None) -> str:
        return "" if seat is None else f"玩家 {seat + 1}"

    def heroes_of(self, seat: int | None) -> list[Entity]:
        return [hero for hero in self.party if hero.owner == seat]

    def seat_is_out(self, seat: int) -> bool:
        """True once every hero this player commands has fallen."""
        return all(not hero.is_alive for hero in self.heroes_of(seat))

    # -- floor setup ------------------------------------------------------- #

    def enter_floor(self, depth: int) -> None:
        self.depth = depth
        self.score.depth_reached = max(self.score.depth_reached, depth)
        self.dungeon = dungeon_mod.generate(depth, self.rng)
        self.explored = set()
        self.visible = set()
        self.chests = [Chest(x, y) for x, y in self.dungeon.chest_spots]

        self.entities = [hero for hero in self.party if hero.is_alive]
        self._place_party()
        self._populate()

        self.order = combat.roll_initiative(self, self.living())
        self.turn_index = 0
        self.round = 1
        self._ticked = set()

        headline = "王房" if self.dungeon.is_boss_floor else "第 %d 層" % depth
        self.log(f"── 進入{headline}（深度 {depth}） ──", "system")
        if self.dungeon.is_boss_floor:
            self.log("空氣變得沉重，前方傳來腳步聲。", "warn")
        self._begin_turn()
        self._run_monster_turns()

    def _place_party(self) -> None:
        spots = self._free_spots_near(self.dungeon.entrance, len(self.entities))
        for hero, spot in zip(self.entities, spots):
            hero.position = spot
            hero.awake = True

    def _free_spots_near(self, origin: tuple[int, int], count: int) -> list[tuple[int, int]]:
        found: list[tuple[int, int]] = []
        seen = {origin}
        frontier = [origin]
        while frontier and len(found) < count:
            current = frontier.pop(0)
            if self.dungeon.is_walkable(*current):
                found.append(current)
            for step in dungeon_mod.neighbours(*current):
                if step not in seen and self.dungeon.is_walkable(*step):
                    seen.add(step)
                    frontier.append(step)
        return found

    def _populate(self) -> None:
        if self.dungeon.is_boss_floor:
            self._populate_boss()
            return

        entrance_room = self.dungeon.room_at(*self.dungeon.entrance)
        for room in self.dungeon.rooms:
            if room is entrance_room:
                continue
            if self.rng.random() < EMPTY_ROOM_CHANCE:
                continue
            count = monsters_mod.room_population(self.depth, self.rng)
            for spot in dungeon_mod.spawn_tiles(self.dungeon, room, count, self.rng):
                if self.entity_at(spot):
                    continue
                monster = monsters_mod.pick(self.depth, self.rng).spawn(self.depth)
                monster.position = spot
                self.entities.append(monster)

    def _populate_boss(self) -> None:
        arena = next(room for room in self.dungeon.rooms if room.is_boss)
        definition = monsters_mod.boss_for(self.depth)
        if definition is not None:
            boss = definition.spawn(self.depth)
            boss.position = arena.center
            boss.awake = True
            boss.home_room = arena
            self.entities.append(boss)

        escorts = 2 + self.depth // 5
        for spot in dungeon_mod.spawn_tiles(self.dungeon, arena, escorts + 4, self.rng):
            if len([e for e in self.entities if e.team is Team.MONSTER]) > escorts:
                break
            if self.entity_at(spot) or distance(spot, arena.center) < 2:
                continue
            minion = monsters_mod.pick(max(1, self.depth - 1), self.rng).spawn(self.depth)
            minion.position = spot
            self.entities.append(minion)

    # -- vision ------------------------------------------------------------ #

    def refresh_vision(self) -> None:
        visible: set[tuple[int, int]] = set()
        for hero in self.living(Team.PARTY):
            hx, hy = hero.position
            for y in range(hy - VISION_RADIUS, hy + VISION_RADIUS + 1):
                for x in range(hx - VISION_RADIUS, hx + VISION_RADIUS + 1):
                    if not self.dungeon.in_bounds(x, y):
                        continue
                    if distance((x, y), hero.position) > VISION_RADIUS:
                        continue
                    if has_line_of_sight(self.dungeon, hero.position, (x, y)):
                        visible.add((x, y))
            # Standing inside a room lights the whole room, which reads much
            # better on an ASCII map than a ragged circle of lit tiles.
            room = self.dungeon.room_at(hx, hy)
            if room is not None:
                visible.update(room.tiles())
        self.visible = visible
        self.explored |= visible

    def can_see(self, entity: Entity) -> bool:
        return entity.position in self.visible

    # -- turn flow --------------------------------------------------------- #

    def _begin_turn(self) -> None:
        actor = self.current
        self.refresh_vision()
        if actor is None or self.phase is not Phase.PLAYING:
            return

        # Delaying (Tab) reshuffles the queue, so tie status ticks to the round
        # rather than to the queue slot — nobody gets ticked twice.
        if id(actor) not in self._ticked:
            self._ticked.add(id(actor))
            for status in actor.tick_statuses():
                if actor.team is Team.PARTY or self.can_see(actor):
                    self.log(f"{actor.name} 的{status.label}結束了。", "info")

        self.turn = TurnState(moves_left=actor.effective_speed, action_used=False)

        if actor.team is Team.PARTY and actor.has(Status.STUNNED):
            self.log(f"{actor.name} 暈眩中，跳過這個回合。", "warn")
            self.end_turn()

    def end_turn(self) -> None:
        """Finish the current unit's turn and run monsters until a hero is up."""
        if self.phase is not Phase.PLAYING:
            return
        self._advance_index()
        self._begin_turn()
        self._run_monster_turns()

    def _advance_index(self) -> None:
        if not self.order:
            return
        for _ in range(len(self.order) + 1):
            self.turn_index += 1
            if self.turn_index >= len(self.order):
                self.turn_index = 0
                self.round += 1
                self.score.rounds += 1
                self._ticked.clear()
            if self.order[self.turn_index].is_alive:
                return

    def _run_monster_turns(self) -> None:
        guard = 0
        while self.phase is Phase.PLAYING and self.hero is None and self.order:
            actor = self.current
            if actor is None:
                return
            guard += 1
            if guard > len(self.order) * 4:  # paranoia against a stuck queue
                return
            if actor.is_alive:
                combat.take_monster_turn(self, actor)
            self._check_defeat()
            if self.phase is not Phase.PLAYING:
                return
            self._advance_index()
            self._begin_turn()

    # -- player verbs ------------------------------------------------------ #

    def move_hero(self, dx: int, dy: int) -> bool:
        hero = self.hero
        if hero is None:
            return False
        if self.turn.moves_left <= 0:
            self.log("這回合的移動力用完了（按 e 結束回合）。", "warn")
            return False

        spot = (hero.x + dx, hero.y + dy)
        if not self.dungeon.is_walkable(*spot):
            return False
        blocker = self.entity_at(spot)
        if blocker is not None:
            if blocker.team is Team.MONSTER:
                self.log(f"{blocker.name} 擋在那裡 — 用攻擊而不是走過去。", "warn")
            else:
                self.log(f"{blocker.name} 站在那裡，繞過去或請他先動（Tab）。", "warn")
            return False

        hero.position = spot
        self.turn.moves_left -= 1
        self._on_hero_entered(hero)
        self.refresh_vision()
        return True

    def _on_hero_entered(self, hero: Entity) -> None:
        chest = self.chest_at(hero.position)
        if chest is not None:
            self._open_chest(hero, chest)
        if hero.position == self.dungeon.stairs:
            self.log("這裡有往下的樓梯（按 > 帶隊下樓）。", "info")

    def _open_chest(self, hero: Entity, chest: Chest) -> None:
        chest.opened = True
        gold = self.rng.randint(10, 30) + self.depth * 5
        self.gain_gold(gold)
        self.score.chests_opened += 1
        loot = items_mod.roll_loot(self.rng)
        self.inventory[loot.id] = self.inventory.get(loot.id, 0) + 1
        self.log(f"{hero.name} 打開了寶箱：{gold} 金幣、{loot.name} x1。", "loot")

    # -- gold, experience and the merchant --------------------------------- #

    def gain_gold(self, amount: int) -> None:
        """Credit gold to both the lifetime score and the spendable purse."""
        if amount <= 0:
            return
        self.score.gold += amount
        self.gold += amount

    @property
    def xp_to_next(self) -> int:
        """Party XP still owed before the next level-up."""
        return XP_PER_LEVEL * self.level

    def gain_xp(self, amount: int) -> None:
        if amount <= 0:
            return
        self.xp += amount
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self._level_up()

    def _level_up(self) -> None:
        self.level += 1
        bump_stat = self.level % STAT_UP_EVERY == 0
        self.log(f"隊伍升到了 {self.level} 級！", "level")
        for hero in self.party:
            if not hero.is_alive:
                continue  # the fallen do not come back to level up
            cls = hero.archetype
            hp_gain = getattr(cls, "hp_per_level", 5)
            mp_gain = getattr(cls, "mp_per_level", 2)
            hero.max_hp += hp_gain
            hero.hp += hp_gain
            hero.max_mp += mp_gain
            hero.mp += mp_gain

            # Spell out what each hero got. "大家都更強壯了" told the player a
            # level happened; it never told them what changed, which is why the
            # curve read as flat even while the numbers moved.
            gains = [f"HP+{hp_gain}"]
            if mp_gain and hero.max_mp:
                gains.append(f"MP+{mp_gain}")
            if bump_stat and isinstance(cls, HeroClass):
                stat = cls.primary_stat
                setattr(hero.stats, stat, getattr(hero.stats, stat) + STAT_UP_AMOUNT)
                gains.append(f"{STAT_NAMES[stat]}+{STAT_UP_AMOUNT}")
            self.log(f"{hero.name} {' '.join(gains)}", "level")

    def shop_gear(self) -> list[Gear]:
        """Gear the merchant offers at the current depth."""
        return shop_mod.gear_for(self.depth)

    def shop_consumables(self) -> list[tuple[ItemDef, int]]:
        return shop_mod.consumables_for()

    def buy_consumable(self, item: ItemDef) -> bool:
        price = shop_mod.CONSUMABLE_PRICES.get(item.id)
        if price is None:
            return False
        if self.gold < price:
            self.log("金幣不夠。", "warn")
            return False
        self.gold -= price
        self.inventory[item.id] = self.inventory.get(item.id, 0) + 1
        self.log(f"買下了{item.name}（-{price} 金幣）。", "loot")
        return True

    def buy_gear(self, gear: Gear, hero: Entity) -> bool:
        if self.gold < gear.price:
            self.log("金幣不夠。", "warn")
            return False
        self.gold -= gear.price
        self._equip(hero, gear)
        self.log(f"{hero.name} 裝備了{gear.name}（-{gear.price} 金幣）。", "loot")
        return True

    def _equip(self, hero: Entity, gear: Gear) -> None:
        """Fit ``gear`` into its slot, first shedding whatever filled it."""
        old_id = hero.equipped.get(gear.slot)
        if old_id is not None:
            old = shop_mod.BY_ID.get(old_id)
            if old is not None:
                hero.bonus_hit -= old.bonus_hit
                hero.bonus_damage -= old.bonus_damage
                hero.bonus_ac -= old.bonus_ac
        hero.bonus_hit += gear.bonus_hit
        hero.bonus_damage += gear.bonus_damage
        hero.bonus_ac += gear.bonus_ac
        hero.equipped[gear.slot] = gear.id

    def usable_abilities(self, hero: Entity) -> list[Ability]:
        return list(hero.abilities)

    def use_ability(self, ability: Ability, target: Entity | tuple[int, int] | None = None) -> bool:
        hero = self.hero
        if hero is None:
            return False
        if self.turn.action_used:
            self.log("這回合的主要行動已經用過了（按 e 結束回合）。", "warn")
            return False

        if not combat.resolve(self, hero, ability, target):
            return False

        self.turn.action_used = True
        self.refresh_vision()
        self._check_victory()
        return True

    def use_item(self, item: ItemDef, target: Entity | tuple[int, int] | None = None) -> bool:
        hero = self.hero
        if hero is None:
            return False
        if self.inventory.get(item.id, 0) <= 0:
            self.log(f"沒有{item.name}了。", "warn")
            return False
        if self.turn.action_used:
            self.log("這回合的主要行動已經用過了（按 e 結束回合）。", "warn")
            return False

        if item.ability.target is TargetKind.SELF:
            target = hero
        if not combat.resolve(self, hero, item.ability, target):
            return False

        self.inventory[item.id] -= 1
        if self.inventory[item.id] <= 0:
            del self.inventory[item.id]
        self.turn.action_used = True
        self.refresh_vision()
        self._check_victory()
        return True

    def descend(self) -> bool:
        hero = self.hero
        if hero is None:
            return False
        if hero.position != self.dungeon.stairs:
            self.log("要站在樓梯 ( > ) 上才能下樓。", "warn")
            return False
        if self.depth >= dungeon_mod.MAX_DEPTH:
            self.log("這裡已經是最深的一層了。", "warn")
            return False

        for member in self.living(Team.PARTY):
            member.restore(int(member.max_hp * REST_HP_FRACTION))
            member.mp = min(member.max_mp, member.mp + int(member.max_mp * REST_MP_FRACTION))
            member.statuses.clear()
            member.taunted_by = None
        self.log("隊伍在樓梯口稍作休息，恢復了一些狀態。", "heal")
        self.enter_floor(self.depth + 1)
        return True

    def delay_turn(self) -> bool:
        """Hand the turn to the next hero in the queue (the ``Tab`` key).

        Only allowed before the hero has spent anything, otherwise delaying
        would hand out a second helping of movement.
        """
        hero = self.hero
        if hero is None:
            return False
        if self.turn.action_used or self.turn.moves_left < hero.effective_speed:
            self.log("已經開始行動了，這回合不能再換人。", "warn")
            return False

        for index in range(self.turn_index + 1, len(self.order)):
            other = self.order[index]
            if other.is_alive and other.team is Team.PARTY:
                self.order[self.turn_index], self.order[index] = other, hero
                self.turn = TurnState(moves_left=other.effective_speed, action_used=False)
                self.log(f"{hero.name} 讓 {other.name} 先行動。", "info")
                self._begin_turn()
                return True

        self.log("本回合已經沒有其他還沒行動的隊友了。", "warn")
        return False

    def wait(self) -> None:
        hero = self.hero
        if hero is not None:
            self.log(f"{hero.name} 原地戒備。", "info")
        self.end_turn()

    @property
    def turn_spent(self) -> bool:
        """Nothing left to do this turn — the UI nudges the player to press e.

        The turn still does not end on its own: acting and then moving is a
        normal thing to want, and having the keyboard taken away mid-thought
        is worse than one extra keypress.
        """
        return self.turn.action_used and self.turn.moves_left <= 0

    # -- deaths, win and loss ---------------------------------------------- #

    def kill(self, victim: Entity, killer: Entity | None = None) -> None:
        victim.hp = 0
        if victim.team is Team.MONSTER:
            self.score.kills += 1
            definition = victim.archetype
            if isinstance(definition, monsters_mod.MonsterDef):
                self.gain_gold(definition.score // 5)
                self.gain_xp(definition.score)
            if killer is not None and killer.owner is not None:
                self.score.kills_by_seat[killer.owner] = (
                    self.score.kills_by_seat.get(killer.owner, 0) + 1
                )
            self.log(f"{victim.name} 倒下了！", "death")
        else:
            self.score.fallen.append(victim.name)
            self.log(f"{victim.name} 倒下了 — 這趟旅程到此為止。", "death")
            if victim.owner is not None and self.seat_is_out(victim.owner):
                self.log(f"{self.seat_label(victim.owner)} 已經出局，剩下的路交給隊友了。", "system")
        for other in self.entities:
            if other.taunted_by is victim:
                other.taunted_by = None
        self._check_victory()
        self._check_defeat()

    def _check_defeat(self) -> None:
        if self.phase is Phase.PLAYING and not self.living(Team.PARTY):
            self.phase = Phase.DEFEAT
            self.log("全隊覆滅。地城重歸寂靜。", "system")

    def _check_victory(self) -> None:
        if self.phase is not Phase.PLAYING or self.depth < dungeon_mod.MAX_DEPTH:
            return
        boss = monsters_mod.boss_for(self.depth)
        if boss is None:
            return
        if any(
            e.is_alive and isinstance(e.archetype, monsters_mod.MonsterDef) and e.archetype.is_boss
            for e in self.entities
        ):
            return
        self.phase = Phase.VICTORY
        self.score.victory = True
        self.log(f"{boss.name} 倒下了。你們活著走出了地城！", "system")

    @property
    def is_over(self) -> bool:
        return self.phase is not Phase.PLAYING
