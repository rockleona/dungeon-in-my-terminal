"""The between-floors merchant: what gold buys and for how much.

Data only, like every other registry here. ``game.World.buy`` applies a
purchase and ``World.shop_stock`` decides what is on the shelf this visit; the
UI just lists offers and calls buy. Two kinds of thing are sold:

* consumables — the same ``ItemDef`` objects chests drop, going into the shared
  bag, priced by :data:`CONSUMABLE_PRICES`;
* gear — a ``Gear`` equipped on one hero, adding flat combat bonuses.

Adding a new weapon or a new potion to the shop is a line of data, never a code
path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import items
from .items import ItemDef


@dataclass(frozen=True)
class Gear:
    id: str
    name: str
    slot: str  # "weapon" | "armor" | "trinket" — one worn per slot, newest wins
    description: str
    price: int
    tier: int = 1  # gates when it appears; deeper floors unlock stronger gear
    bonus_hit: int = 0
    bonus_damage: int = 0
    bonus_ac: int = 0


# --------------------------------------------------------------------------- #
# Gear on offer, grouped by slot and escalating in tier.
# --------------------------------------------------------------------------- #

GEAR: list[Gear] = [
    # weapons — to-hit and damage
    Gear("keen_dagger", "銳利短刃", "weapon", "攻擊擲骰 +1、傷害 +1。", 40, 1, bonus_hit=1, bonus_damage=1),
    Gear("steel_sword", "精鋼長劍", "weapon", "攻擊擲骰 +1、傷害 +2。", 90, 2, bonus_hit=1, bonus_damage=2),
    Gear("rune_blade", "符文巨刃", "weapon", "攻擊擲骰 +2、傷害 +3。", 160, 3, bonus_hit=2, bonus_damage=3),
    # armour — armour class
    Gear("leather_armor", "皮甲", "armor", "護甲 +1。", 35, 1, bonus_ac=1),
    Gear("chain_mail", "鎖子甲", "armor", "護甲 +2。", 85, 2, bonus_ac=2),
    Gear("plate_armor", "板甲", "armor", "護甲 +3。", 150, 3, bonus_ac=3),
    # trinkets — a small edge, cheaper
    Gear("hit_charm", "命中護符", "trinket", "攻擊擲骰 +1。", 55, 2, bonus_hit=1),
    Gear("power_ring", "蠻力指環", "trinket", "傷害 +2。", 70, 2, bonus_damage=2),
]

BY_ID: dict[str, Gear] = {gear.id: gear for gear in GEAR}

CONSUMABLE_PRICES: dict[str, int] = {
    items.HEALING_POTION.id: 20,
    items.MANA_POTION.id: 18,
    items.BOMB.id: 30,
}


def _gear_tier_for(depth: int) -> int:
    """Which gear tier the merchant is stocking by the time you reach ``depth``."""
    if depth >= 7:
        return 3
    if depth >= 4:
        return 2
    return 1


def gear_for(depth: int) -> list[Gear]:
    """Every piece of gear the merchant will show on a floor at this depth."""
    ceiling = _gear_tier_for(depth)
    return [g for g in GEAR if g.tier <= ceiling]


def consumables_for() -> list[tuple[ItemDef, int]]:
    """The consumables always on the shelf, with their prices."""
    return [(items.BY_ID[item_id], price) for item_id, price in CONSUMABLE_PRICES.items()]
