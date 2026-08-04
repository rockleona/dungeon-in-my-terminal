"""Consumables found in chests.

An item is just a wrapper around an ``Ability``, so using one goes through the
exact same resolution path as casting a spell — including the dice log.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .abilities import Ability, AbilityKind, TargetKind


@dataclass(frozen=True)
class ItemDef:
    id: str
    name: str
    description: str
    ability: Ability


HEALING_POTION = ItemDef(
    id="healing_potion",
    name="治療藥水",
    description="立刻回復 2d4+2 點生命。",
    ability=Ability(
        id="healing_potion",
        name="治療藥水",
        description="回復 2d4+2 點生命",
        kind=AbilityKind.HEAL,
        target=TargetKind.SELF,
        reach=0,
        healing="2d4+2",
    ),
)

MANA_POTION = ItemDef(
    id="mana_potion",
    name="魔力藥水",
    description="立刻回復 1d6+3 點魔力。",
    ability=Ability(
        id="mana_potion",
        name="魔力藥水",
        description="回復 1d6+3 點魔力",
        kind=AbilityKind.RESTORE,
        target=TargetKind.SELF,
        reach=0,
        healing="1d6+3",
    ),
)

BOMB = ItemDef(
    id="bomb",
    name="炸彈",
    description="扔向 4 格內一格，半徑 1 內全體受 2d6 傷害（含隊友）。",
    ability=Ability(
        id="bomb",
        name="炸彈",
        description="半徑 1 的爆炸，2d6 傷害",
        kind=AbilityKind.BURST,
        target=TargetKind.TILE,
        reach=4,
        damage="2d6",
        radius=1,
        friendly_fire=True,
    ),
)

ALL: list[ItemDef] = [HEALING_POTION, MANA_POTION, BOMB]
BY_ID: dict[str, ItemDef] = {item.id: item for item in ALL}

# Healing is what keeps a run alive, so it shows up most often.
LOOT_TABLE: list[tuple[ItemDef, int]] = [(HEALING_POTION, 5), (MANA_POTION, 3), (BOMB, 2)]


def roll_loot(rng: random.Random) -> ItemDef:
    population = [item for item, weight in LOOT_TABLE for _ in range(weight)]
    return rng.choice(population)
