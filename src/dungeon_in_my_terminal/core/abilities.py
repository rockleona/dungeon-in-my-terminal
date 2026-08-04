"""The vocabulary every class and monster action is written in.

An ability is pure data: what it targets, how far it reaches, what it rolls.
``combat.py`` knows how to resolve each ``AbilityKind``, so adding a class
means adding rows here — not branching logic there.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .entity import Status


class AbilityKind(str, Enum):
    ATTACK = "attack"  # roll to hit one target, then roll damage
    BURST = "burst"  # damage everything in a radius, no to-hit roll
    HEAL = "heal"  # restore hp to one ally
    RESTORE = "restore"  # restore mp to one ally
    BUFF = "buff"  # apply a friendly status
    TAUNT = "taunt"  # force nearby enemies to come at the caster


class TargetKind(str, Enum):
    ENEMY = "enemy"
    ALLY = "ally"
    SELF = "self"
    TILE = "tile"


@dataclass(frozen=True)
class Ability:
    id: str
    name: str
    description: str
    kind: AbilityKind
    target: TargetKind
    stat: str = "strength"
    reach: int = 1
    mp_cost: int = 0
    damage: str | None = None
    healing: str | None = None
    radius: int = 0
    hits: int = 1
    advantage: bool = False
    status: Status | None = None
    status_rounds: int = 0
    friendly_fire: bool = False
    """Whether a burst also catches the caster's own side."""

    @property
    def needs_target(self) -> bool:
        return self.target is not TargetKind.SELF

    def cost_label(self) -> str:
        return f"{self.mp_cost}MP" if self.mp_cost else "免費"
