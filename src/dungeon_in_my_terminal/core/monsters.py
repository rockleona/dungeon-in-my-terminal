"""Monster roster, split into three tiers that unlock as you descend.

Each monster carries the same ``Ability`` objects the heroes use, so combat
resolves both sides through one code path. What makes a monster feel different
is its ``AI`` behaviour plus which abilities it brings.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from .abilities import Ability, AbilityKind, TargetKind
from .entity import Entity, Stats, Status, Team


class AI(str, Enum):
    MELEE = "melee"  # close the distance, then swing
    RANGED = "ranged"  # keep a gap, shoot from it
    SUPPORT = "support"  # heal the most wounded ally, otherwise plink


@dataclass(frozen=True)
class MonsterDef:
    id: str
    name: str
    glyph: str
    max_hp: int
    armor_class: int
    speed: int
    ai: AI
    stats: Stats
    abilities: list[Ability]
    color: str = "white"
    min_depth: int = 1
    max_depth: int = 99
    is_boss: bool = False
    sight: int = 8
    score: int = 10

    def spawn(self, depth: int) -> Entity:
        # A little padding per floor so tier-1 trash doesn't melt instantly
        # once you have three floors of gear-free levelling behind you.
        bonus_hp = max(0, (depth - self.min_depth) // 2)
        monster = Entity(
            name=self.name,
            glyph=self.glyph,
            team=Team.MONSTER,
            max_hp=self.max_hp + bonus_hp,
            max_mp=0,
            armor_class=self.armor_class,
            speed=self.speed,
            stats=Stats(**vars(self.stats)),
            color=self.color,
            abilities=list(self.abilities),
            archetype=self,
        )
        return monster


def _strike(name: str, damage: str, reach: int = 1, stat: str = "strength", **kwargs) -> Ability:
    return Ability(
        id=name,
        name=name,
        description=f"{damage} 傷害",
        kind=AbilityKind.ATTACK,
        target=TargetKind.ENEMY,
        stat=stat,
        reach=reach,
        damage=damage,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Tier 1 — floors 1-3
# --------------------------------------------------------------------------- #

SLIME = MonsterDef(
    id="slime",
    name="史萊姆",
    glyph="s",
    max_hp=9,
    armor_class=11,
    speed=3,
    ai=AI.MELEE,
    stats=Stats(strength=12, dexterity=8, intellect=4, wisdom=8),
    abilities=[_strike("酸液拍擊", "1d4")],
    color="green",
    max_depth=4,
    score=8,
)

RAT = MonsterDef(
    id="rat",
    name="巨鼠",
    glyph="r",
    max_hp=6,
    armor_class=13,
    speed=5,
    ai=AI.MELEE,
    stats=Stats(strength=10, dexterity=14, intellect=4, wisdom=10),
    abilities=[_strike("啃咬", "1d4", stat="dexterity")],
    color="yellow",
    max_depth=4,
    score=6,
)

GOBLIN_SCOUT = MonsterDef(
    id="goblin_scout",
    name="哥布林斥候",
    glyph="g",
    max_hp=9,
    armor_class=12,
    speed=5,
    ai=AI.MELEE,
    stats=Stats(strength=11, dexterity=14, intellect=9, wisdom=9),
    abilities=[_strike("短刀", "1d6", stat="dexterity")],
    color="green",
    min_depth=2,
    max_depth=6,
    score=10,
)

# --------------------------------------------------------------------------- #
# Tier 2 — floors 4-7
# --------------------------------------------------------------------------- #

GOBLIN_WARRIOR = MonsterDef(
    id="goblin_warrior",
    name="哥布林戰士",
    glyph="G",
    max_hp=15,
    armor_class=14,
    speed=4,
    ai=AI.MELEE,
    stats=Stats(strength=14, dexterity=12, intellect=9, wisdom=10),
    abilities=[_strike("彎刀", "1d6+1")],
    color="red",
    min_depth=4,
    max_depth=9,
    score=16,
)

SKELETON_ARCHER = MonsterDef(
    id="skeleton_archer",
    name="骷髏弓手",
    glyph="a",
    max_hp=11,
    armor_class=12,
    speed=3,
    ai=AI.RANGED,
    stats=Stats(strength=10, dexterity=15, intellect=6, wisdom=10),
    abilities=[_strike("骨箭", "1d6", reach=5, stat="dexterity")],
    color="cyan",
    min_depth=4,
    max_depth=9,
    score=18,
)

GOBLIN_SHAMAN = MonsterDef(
    id="goblin_shaman",
    name="哥布林薩滿",
    glyph="S",
    max_hp=12,
    armor_class=12,
    speed=3,
    ai=AI.SUPPORT,
    stats=Stats(strength=9, dexterity=11, intellect=12, wisdom=15),
    abilities=[
        Ability(
            id="mend",
            name="縫合術",
            description="治療一名受傷的同伴",
            kind=AbilityKind.HEAL,
            target=TargetKind.ALLY,
            stat="wisdom",
            reach=4,
            healing="1d6+2",
        ),
        _strike("詛咒飛彈", "1d4", reach=4, stat="wisdom"),
    ],
    color="magenta",
    min_depth=4,
    max_depth=10,
    score=20,
)

# --------------------------------------------------------------------------- #
# Tier 3 — floors 8-10
# --------------------------------------------------------------------------- #

HELLHOUND = MonsterDef(
    id="hellhound",
    name="地獄犬",
    glyph="h",
    max_hp=17,
    armor_class=14,
    speed=6,
    ai=AI.MELEE,
    stats=Stats(strength=15, dexterity=15, intellect=5, wisdom=11),
    abilities=[_strike("灼熱撕咬", "1d8")],
    color="red",
    min_depth=7,
    score=24,
)

OGRE = MonsterDef(
    id="ogre",
    name="食人魔",
    glyph="O",
    max_hp=32,
    armor_class=14,
    speed=3,
    ai=AI.MELEE,
    stats=Stats(strength=18, dexterity=8, intellect=5, wisdom=9),
    abilities=[_strike("巨棒橫掃", "2d6")],
    color="yellow",
    min_depth=8,
    score=35,
)

SHADOW_MAGE = MonsterDef(
    id="shadow_mage",
    name="暗影法師",
    glyph="m",
    max_hp=18,
    armor_class=13,
    speed=3,
    ai=AI.RANGED,
    stats=Stats(strength=8, dexterity=12, intellect=17, wisdom=13),
    abilities=[_strike("暗影箭", "1d8", reach=6, stat="intellect")],
    color="magenta",
    min_depth=8,
    score=30,
)

# --------------------------------------------------------------------------- #
# Bosses
# --------------------------------------------------------------------------- #

GOBLIN_KING = MonsterDef(
    id="goblin_king",
    name="哥布林王 葛拉許",
    glyph="K",
    max_hp=68,
    armor_class=15,
    speed=4,
    ai=AI.MELEE,
    stats=Stats(strength=17, dexterity=12, intellect=11, wisdom=12),
    abilities=[
        _strike("戰斧劈砍", "2d6+2"),
        _strike("盾牌猛撞", "1d8", status=Status.STUNNED, status_rounds=1),
    ],
    color="red",
    min_depth=5,
    is_boss=True,
    sight=99,
    score=200,
)

ABYSS_LORD = MonsterDef(
    id="abyss_lord",
    name="深淵領主",
    glyph="D",
    max_hp=115,
    armor_class=17,
    speed=4,
    ai=AI.MELEE,
    stats=Stats(strength=19, dexterity=14, intellect=18, wisdom=16),
    abilities=[
        _strike("虛空之爪", "2d8"),
        Ability(
            id="shadow_burst",
            name="暗影爆發",
            description="半徑 2 的暗影爆炸",
            kind=AbilityKind.BURST,
            target=TargetKind.TILE,
            stat="intellect",
            reach=6,
            damage="2d6",
            radius=2,
        ),
    ],
    color="magenta",
    min_depth=10,
    is_boss=True,
    sight=99,
    score=500,
)

ROSTER: list[MonsterDef] = [
    SLIME,
    RAT,
    GOBLIN_SCOUT,
    GOBLIN_WARRIOR,
    SKELETON_ARCHER,
    GOBLIN_SHAMAN,
    HELLHOUND,
    OGRE,
    SHADOW_MAGE,
]
BOSSES: dict[int, MonsterDef] = {5: GOBLIN_KING, 10: ABYSS_LORD}


def available(depth: int) -> list[MonsterDef]:
    """Everything that can show up on this floor, bosses excluded."""
    pool = [m for m in ROSTER if m.min_depth <= depth <= m.max_depth]
    return pool or [m for m in ROSTER if m.min_depth <= depth]


def boss_for(depth: int) -> MonsterDef | None:
    return BOSSES.get(depth)


def pick(depth: int, rng: random.Random) -> MonsterDef:
    return rng.choice(available(depth))


def room_population(depth: int, rng: random.Random) -> int:
    """How many monsters a non-entrance room gets on this floor."""
    return min(4, rng.randint(1, 2) + depth // 4)
