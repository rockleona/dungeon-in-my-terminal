"""The four starting hero classes.

Adding a fifth class means appending one ``HeroClass`` to ``CLASSES`` — the
menu, the action bar and combat all read from this registry, so nothing else
needs to change unless the class needs a brand new ``AbilityKind``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .abilities import Ability, AbilityKind, TargetKind
from .entity import Entity, Stats, Status, Team


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


WARRIOR = HeroClass(
    id="warrior",
    name="戰士",
    glyph="W",
    role="坦克 / 近戰主力",
    blurb="站在最前面挨打的人。血厚、甲厚，能把怪物的注意力從隊友身上拉過來。",
    max_hp=32,
    max_mp=6,
    armor_class=16,
    speed=4,
    stats=Stats(strength=16, dexterity=11, intellect=8, wisdom=10),
    color="red",
    primary_stat="strength",
    hp_per_level=8,
    mp_per_level=1,
    abilities=[
        Ability(
            id="cleave",
            name="揮砍",
            description="近戰重擊，1d8+力量。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="strength",
            reach=1,
            damage="1d8",
        ),
        Ability(
            id="shield_bash",
            name="盾擊",
            description="1d6+力量傷害，命中則使目標暈眩 1 回合。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="strength",
            reach=1,
            mp_cost=3,
            damage="1d6",
            status=Status.STUNNED,
            status_rounds=1,
        ),
        Ability(
            id="taunt",
            name="挑釁",
            description="半徑 3 內的敵人接下來 3 回合都會優先衝著你來。",
            kind=AbilityKind.TAUNT,
            target=TargetKind.SELF,
            stat="strength",
            reach=0,
            mp_cost=2,
            radius=3,
            status=Status.TAUNTED,
            status_rounds=3,
        ),
    ],
)

RANGER = HeroClass(
    id="ranger",
    name="遊俠",
    glyph="R",
    role="遠程輸出",
    blurb="敏捷高、先攻快，能在怪物走到面前之前就先開火。",
    max_hp=24,
    max_mp=8,
    armor_class=14,
    speed=5,
    stats=Stats(strength=11, dexterity=16, intellect=11, wisdom=12),
    color="green",
    primary_stat="dexterity",
    hp_per_level=5,
    mp_per_level=2,
    abilities=[
        Ability(
            id="shot",
            name="射擊",
            description="6 格內遠程攻擊，1d8+敏捷。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="dexterity",
            reach=6,
            damage="1d8",
        ),
        Ability(
            id="aimed_shot",
            name="瞄準射擊",
            description="7 格內以優勢擲骰（兩顆 d20 取高），1d10+敏捷。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="dexterity",
            reach=7,
            mp_cost=3,
            damage="1d10",
            advantage=True,
        ),
        Ability(
            id="twin_shot",
            name="雙重射擊",
            description="6 格內連射兩箭，每箭各自判定 1d6+敏捷。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="dexterity",
            reach=6,
            mp_cost=4,
            damage="1d6",
            hits=2,
        ),
    ],
)

MAGE = HeroClass(
    id="mage",
    name="法師",
    glyph="M",
    role="範圍法術",
    blurb="血最少但爆發最高，一發火球能清掉整個房間，但站錯位置也會炸到隊友。",
    max_hp=18,
    max_mp=14,
    armor_class=12,
    speed=4,
    stats=Stats(strength=8, dexterity=12, intellect=16, wisdom=12),
    color="magenta",
    primary_stat="intellect",
    hp_per_level=4,
    mp_per_level=4,
    abilities=[
        Ability(
            id="bolt",
            name="奧術飛彈",
            description="5 格內遠程攻擊，1d6+智力。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="intellect",
            reach=5,
            damage="1d6",
        ),
        Ability(
            id="fireball",
            name="火球術",
            description="指定 6 格內一格引爆，半徑 2 內所有單位受 2d6 傷害（含隊友）。",
            kind=AbilityKind.BURST,
            target=TargetKind.TILE,
            stat="intellect",
            reach=6,
            mp_cost=5,
            damage="2d6",
            radius=2,
            friendly_fire=True,
        ),
        Ability(
            id="frost_nova",
            name="冰霜新星",
            description="以自身為中心半徑 2 爆開，敵人受 1d6 傷害並緩速 2 回合。",
            kind=AbilityKind.BURST,
            target=TargetKind.SELF,
            stat="intellect",
            reach=0,
            mp_cost=4,
            damage="1d6",
            radius=2,
            status=Status.SLOWED,
            status_rounds=2,
        ),
    ],
)

CLERIC = HeroClass(
    id="cleric",
    name="牧師",
    glyph="C",
    role="治療支援",
    blurb="讓隊伍活過第 5 層的關鍵。治療、增益，必要時也能掄起釘頭錘。",
    max_hp=26,
    max_mp=12,
    armor_class=14,
    speed=4,
    stats=Stats(strength=12, dexterity=10, intellect=11, wisdom=16),
    color="yellow",
    primary_stat="wisdom",
    hp_per_level=6,
    mp_per_level=3,
    abilities=[
        Ability(
            id="smite",
            name="錘擊",
            description="近戰攻擊，1d6+意志。",
            kind=AbilityKind.ATTACK,
            target=TargetKind.ENEMY,
            stat="wisdom",
            reach=1,
            damage="1d6",
        ),
        Ability(
            id="heal",
            name="治療術",
            description="治療 4 格內一名隊友 2d4+意志點生命。",
            kind=AbilityKind.HEAL,
            target=TargetKind.ALLY,
            stat="wisdom",
            reach=4,
            mp_cost=3,
            healing="2d4",
        ),
        Ability(
            id="bless",
            name="祝福",
            description="4 格內一名隊友接下來 3 回合攻擊擲骰 +2。",
            kind=AbilityKind.BUFF,
            target=TargetKind.ALLY,
            stat="wisdom",
            reach=4,
            mp_cost=4,
            status=Status.BLESSED,
            status_rounds=3,
        ),
    ],
)

CLASSES: list[HeroClass] = [WARRIOR, RANGER, MAGE, CLERIC]
BY_ID: dict[str, HeroClass] = {hero.id: hero for hero in CLASSES}


def get(class_id: str) -> HeroClass:
    return BY_ID[class_id]
