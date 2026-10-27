"""Monster roster, loaded from ``data/monsters.toml``.

Each monster carries the same ``Ability`` objects the heroes use, so combat
resolves both sides through one code path. What makes a monster feel
different is its ``AI`` behaviour plus which abilities it brings — both are
data, so the whole bestiary lives in TOML. Call ``reload()`` to point the
registry at a different file (``cli.py``'s ``--content-dir`` does this
before the game starts).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import content
from .abilities import Ability
from .entity import Entity, Stats, Team

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "monsters.toml"


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
    abilities: list[Ability] = field(default_factory=list)
    color: str = "white"
    min_depth: int = 1
    max_depth: int = 99
    is_boss: bool = False
    boss_floor: int | None = None
    """Which floor spawns this instead of the regular per-room roll. Only
    meaningful when ``is_boss`` is set."""
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


def _build(monster_id: str, raw: dict) -> MonsterDef:
    ctx = f"monster {monster_id!r}"
    is_boss = raw.get("is_boss", False)
    boss_floor = raw.get("boss_floor")
    if is_boss and boss_floor is None:
        raise content.ContentError(f"{ctx}: is_boss = true requires boss_floor")
    ai_raw = content.require(raw, "ai", ctx)
    try:
        ai = AI(ai_raw)
    except ValueError:
        valid = ", ".join(repr(m.value) for m in AI)
        raise content.ContentError(
            f"{ctx}: ai = {ai_raw!r} is not valid; choose one of {valid}"
        ) from None
    try:
        return MonsterDef(
            id=monster_id,
            name=content.require(raw, "name", ctx),
            glyph=content.require(raw, "glyph", ctx),
            max_hp=content.require(raw, "max_hp", ctx),
            armor_class=content.require(raw, "armor_class", ctx),
            speed=content.require(raw, "speed", ctx),
            ai=ai,
            stats=content.build_stats(raw.get("stats", {}), ctx),
            abilities=[content.build_ability(a, ctx) for a in raw.get("abilities", [])],
            color=raw.get("color", "white"),
            min_depth=raw.get("min_depth", 1),
            max_depth=raw.get("max_depth", 99),
            is_boss=is_boss,
            boss_floor=boss_floor,
            sight=raw.get("sight", 8),
            score=raw.get("score", 10),
        )
    except TypeError as exc:
        raise content.ContentError(f"{ctx}: {exc}") from exc


def load(path: Path = DEFAULT_FILE) -> list[MonsterDef]:
    data = content.load_toml(path)
    return [_build(monster_id, raw) for monster_id, raw in data.items()]


def reload(content_dir: Path | str | None = None) -> None:
    """Rebuild the registry, optionally from a ``monsters.toml`` in
    ``content_dir``. Falls back to the built-in file if that override
    doesn't exist, so a content dir only needs to carry the files it means
    to change."""
    global ALL, ROSTER, BY_ID, BOSSES
    global SLIME, RAT, GOBLIN_SCOUT, GOBLIN_WARRIOR, SKELETON_ARCHER, GOBLIN_SHAMAN
    global HELLHOUND, OGRE, SHADOW_MAGE, GOBLIN_KING, ABYSS_LORD
    path = DEFAULT_FILE
    if content_dir is not None:
        override = Path(content_dir) / "monsters.toml"
        if override.exists():
            path = override
    ALL = load(path)
    BY_ID = {monster.id: monster for monster in ALL}
    ROSTER = [monster for monster in ALL if not monster.is_boss]
    BOSSES = {monster.boss_floor: monster for monster in ALL if monster.is_boss}
    SLIME = BY_ID.get("slime")
    RAT = BY_ID.get("rat")
    GOBLIN_SCOUT = BY_ID.get("goblin_scout")
    GOBLIN_WARRIOR = BY_ID.get("goblin_warrior")
    SKELETON_ARCHER = BY_ID.get("skeleton_archer")
    GOBLIN_SHAMAN = BY_ID.get("goblin_shaman")
    HELLHOUND = BY_ID.get("hellhound")
    OGRE = BY_ID.get("ogre")
    SHADOW_MAGE = BY_ID.get("shadow_mage")
    GOBLIN_KING = BY_ID.get("goblin_king")
    ABYSS_LORD = BY_ID.get("abyss_lord")


ALL: list[MonsterDef]
ROSTER: list[MonsterDef]
BY_ID: dict[str, MonsterDef]
BOSSES: dict[int, MonsterDef]
SLIME: MonsterDef | None
RAT: MonsterDef | None
GOBLIN_SCOUT: MonsterDef | None
GOBLIN_WARRIOR: MonsterDef | None
SKELETON_ARCHER: MonsterDef | None
GOBLIN_SHAMAN: MonsterDef | None
HELLHOUND: MonsterDef | None
OGRE: MonsterDef | None
SHADOW_MAGE: MonsterDef | None
GOBLIN_KING: MonsterDef | None
ABYSS_LORD: MonsterDef | None
reload()


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
