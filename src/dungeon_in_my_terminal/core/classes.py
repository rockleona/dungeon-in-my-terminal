"""The starting hero classes, loaded from ``data/classes.toml``.

The registry lives in TOML so anyone can add or edit a class without
touching Python — the menu, the action bar and combat all read ``CLASSES``,
so nothing else needs to change unless a class needs a brand new
``AbilityKind``. Call ``reload()`` to point the registry at a different file
(``cli.py``'s ``--content-dir`` does this before the game starts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import content
from .abilities import Ability
from .entity import Entity, Stats, Team

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "classes.toml"


@dataclass(frozen=True)
class HeroClass:
    id: str
    name: str
    glyph: str
    role: str
    blurb: str
    max_hp: int
    max_mp: int
    armor_class: int
    speed: int
    stats: Stats
    color: str
    abilities: list[Ability] = field(default_factory=list)
    primary_stat: str = "strength"
    """The stat a level-up nudges — a warrior grows stronger, a mage smarter."""
    hp_per_level: int = 5
    mp_per_level: int = 2
    """How much max HP/MP each party level grants this hero. Front-liners gain
    more body, casters more fuel; tuning lives here, not in the level-up code."""

    def spawn(self, name: str | None = None) -> Entity:
        return Entity(
            name=name or self.name,
            glyph=self.glyph,
            team=Team.PARTY,
            max_hp=self.max_hp,
            max_mp=self.max_mp,
            armor_class=self.armor_class,
            speed=self.speed,
            stats=Stats(**vars(self.stats)),
            color=self.color,
            abilities=list(self.abilities),
            archetype=self,
            awake=True,
        )


def _build(class_id: str, raw: dict) -> HeroClass:
    ctx = f"class {class_id!r}"
    try:
        return HeroClass(
            id=class_id,
            name=content.require(raw, "name", ctx),
            glyph=content.require(raw, "glyph", ctx),
            role=content.require(raw, "role", ctx),
            blurb=content.require(raw, "blurb", ctx),
            max_hp=content.require(raw, "max_hp", ctx),
            max_mp=content.require(raw, "max_mp", ctx),
            armor_class=content.require(raw, "armor_class", ctx),
            speed=content.require(raw, "speed", ctx),
            stats=content.build_stats(raw.get("stats", {}), ctx),
            color=content.require(raw, "color", ctx),
            abilities=[content.build_ability(a, ctx) for a in raw.get("abilities", [])],
            primary_stat=raw.get("primary_stat", "strength"),
            hp_per_level=raw.get("hp_per_level", 5),
            mp_per_level=raw.get("mp_per_level", 2),
        )
    except TypeError as exc:
        raise content.ContentError(f"{ctx}: {exc}") from exc


def load(path: Path = DEFAULT_FILE) -> list[HeroClass]:
    data = content.load_toml(path)
    return [_build(class_id, raw) for class_id, raw in data.items()]


def reload(content_dir: Path | str | None = None) -> None:
    """Rebuild the registry, optionally from a ``classes.toml`` in
    ``content_dir``. Falls back to the built-in file if that override
    doesn't exist, so a content dir only needs to carry the files it means
    to change."""
    global CLASSES, BY_ID, WARRIOR, RANGER, MAGE, CLERIC
    path = DEFAULT_FILE
    if content_dir is not None:
        override = Path(content_dir) / "classes.toml"
        if override.exists():
            path = override
    CLASSES = load(path)
    BY_ID = {hero.id: hero for hero in CLASSES}
    WARRIOR = BY_ID.get("warrior")
    RANGER = BY_ID.get("ranger")
    MAGE = BY_ID.get("mage")
    CLERIC = BY_ID.get("cleric")


CLASSES: list[HeroClass]
BY_ID: dict[str, HeroClass]
WARRIOR: HeroClass | None
RANGER: HeroClass | None
MAGE: HeroClass | None
CLERIC: HeroClass | None
reload()


def get(class_id: str) -> HeroClass:
    return BY_ID[class_id]
