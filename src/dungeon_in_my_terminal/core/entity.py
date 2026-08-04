"""Anything that stands on a tile and takes a turn.

Heroes and monsters share one ``Entity`` type; what differs between them is
the data hanging off it (a class definition vs a monster definition) and who
decides its actions, never the rules that resolve those actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - avoids an abilities <-> entity import cycle
    from .abilities import Ability
    from .dungeon import Room

PROFICIENCY = 2
"""Flat to-hit bonus everyone gets, so a level-1 hero isn't missing constantly."""


class Team(str, Enum):
    PARTY = "party"
    MONSTER = "monster"


class Status(str, Enum):
    STUNNED = "stunned"  # loses its next turn entirely
    SLOWED = "slowed"  # movement halved
    BLESSED = "blessed"  # +2 to attack rolls
    TAUNTED = "taunted"  # must go for whoever taunted it

    @property
    def label(self) -> str:
        return {
            Status.STUNNED: "暈眩",
            Status.SLOWED: "緩速",
            Status.BLESSED: "祝福",
            Status.TAUNTED: "被挑釁",
        }[self]


@dataclass
class Stats:
    strength: int = 10
    dexterity: int = 10
    intellect: int = 10
    wisdom: int = 10

    def modifier(self, name: str) -> int:
        """Classic ``(score - 10) // 2`` — no lookup table needed at the table."""
        return (getattr(self, name) - 10) // 2


STAT_NAMES = {
    "strength": "力量",
    "dexterity": "敏捷",
    "intellect": "智力",
    "wisdom": "意志",
}


@dataclass
class Entity:
    name: str
    glyph: str
    team: Team
    max_hp: int
    armor_class: int
    speed: int
    stats: Stats = field(default_factory=Stats)
    max_mp: int = 0
    x: int = 0
    y: int = 0
    hp: int = field(default=0)
    mp: int = field(default=0)
    statuses: dict[Status, int] = field(default_factory=dict)
    taunted_by: "Entity | None" = None
    awake: bool = False
    color: str = "white"
    abilities: list["Ability"] = field(default_factory=list)
    archetype: object | None = None
    """The ``HeroClass`` or ``MonsterDef`` this entity was spawned from."""
    owner: int | None = None
    """Which seat commands this hero in hotseat play. ``None`` means whoever
    is at the keyboard — that is, single-player."""
    home_room: "Room | None" = None
    """A room this entity will not step outside of. Bosses are pinned to their
    arena so they cannot wander into a passage and wall the party in."""
    bonus_ac: int = 0
    bonus_hit: int = 0
    bonus_damage: int = 0
    """Flat bonuses from equipped gear. Kept as plain numbers so combat never
    has to branch on what a hero is wearing — it just reads the total."""
    equipped: dict[str, str] = field(default_factory=dict)
    """Slot name -> item id, so a bought weapon replaces the old one instead of
    stacking. Purely for display and re-purchase; the numbers live above."""

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.max_hp
        if self.mp <= 0:
            self.mp = self.max_mp

    # -- position ---------------------------------------------------------- #

    @property
    def position(self) -> tuple[int, int]:
        return self.x, self.y

    @position.setter
    def position(self, value: tuple[int, int]) -> None:
        self.x, self.y = value

    # -- state ------------------------------------------------------------- #

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def effective_ac(self) -> int:
        """Armour class after gear — what an attacker actually rolls against."""
        return self.armor_class + self.bonus_ac

    @property
    def effective_speed(self) -> int:
        if self.has(Status.SLOWED):
            return max(1, self.speed // 2)
        return self.speed

    def has(self, status: Status) -> bool:
        return self.statuses.get(status, 0) > 0

    def apply(self, status: Status, rounds: int) -> None:
        self.statuses[status] = max(self.statuses.get(status, 0), rounds)

    def tick_statuses(self) -> list[Status]:
        """Count down every status at the start of this entity's turn."""
        expired = []
        for status in list(self.statuses):
            self.statuses[status] -= 1
            if self.statuses[status] <= 0:
                del self.statuses[status]
                expired.append(status)
                if status is Status.TAUNTED:
                    self.taunted_by = None
        return expired

    def modifier(self, stat: str) -> int:
        return self.stats.modifier(stat)

    def attack_modifier(self, stat: str) -> int:
        bonus = PROFICIENCY + self.modifier(stat) + self.bonus_hit
        if self.has(Status.BLESSED):
            bonus += 2
        return bonus

    def take_damage(self, amount: int) -> int:
        dealt = min(self.hp, max(0, amount))
        self.hp -= dealt
        return dealt

    def restore(self, amount: int) -> int:
        healed = min(self.max_hp - self.hp, max(0, amount))
        self.hp += healed
        return healed

    def spend_mp(self, amount: int) -> bool:
        if self.mp < amount:
            return False
        self.mp -= amount
        return True

    def status_summary(self) -> str:
        return " ".join(f"{s.label}{n}" for s, n in self.statuses.items())
