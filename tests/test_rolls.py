"""The roll record the dice panel reads, and the odds shown before rolling."""

from __future__ import annotations

import pytest
from conftest import ScriptedRandom

from dungeon_in_my_terminal.core import combat, monsters
from dungeon_in_my_terminal.core.entity import PROFICIENCY


@pytest.fixture
def duel(world):
    """A hero and a monster standing next to each other."""
    hero = world.party[0]
    monster = monsters.RAT.spawn(1)
    monster.position = (hero.x + 1, hero.y)
    monster.awake = True
    world.entities.append(monster)
    return world, hero, monster


def test_nothing_is_recorded_before_the_first_roll(world):
    assert world.last_roll is None


def test_an_attack_records_what_the_panel_needs(duel):
    world, hero, monster = duel
    world.rng = ScriptedRandom([14, 5])
    combat.resolve(world, hero, hero.abilities[0], monster)

    roll = world.last_roll
    assert roll is not None
    assert roll.actor == hero.name
    assert roll.target == monster.name
    assert roll.ability == hero.abilities[0].name
    assert roll.check is not None and roll.check.natural == 14
    assert roll.damage is not None
    assert not roll.hostile


def test_the_needed_number_matches_the_forecast(duel):
    world, hero, monster = duel
    ability = hero.abilities[0]
    hits_on, crits_on = combat.forecast(world, hero, ability, monster)
    assert crits_on == 20
    assert hits_on == monster.armor_class - (PROFICIENCY + hero.modifier(ability.stat))

    world.rng = ScriptedRandom([hits_on, 3])
    combat.resolve(world, hero, ability, monster)
    assert world.last_roll.needed == hits_on
    assert world.last_roll.check.success, "剛好擲到門檻應該要命中"


def test_one_below_the_forecast_misses(duel):
    world, hero, monster = duel
    ability = hero.abilities[0]
    hits_on, _ = combat.forecast(world, hero, ability, monster)
    world.rng = ScriptedRandom([hits_on - 1])
    combat.resolve(world, hero, ability, monster)
    assert not world.last_roll.check.success
    assert world.last_roll.outcome == "落空"


def test_outcomes_are_named_for_the_panel(duel):
    world, hero, monster = duel
    world.rng = ScriptedRandom([20, 4, 4])
    combat.resolve(world, hero, hero.abilities[0], monster)
    assert world.last_roll.outcome == "重擊！"

    monster.hp = monster.max_hp
    world.rng = ScriptedRandom([1])
    combat.resolve(world, hero, hero.abilities[0], monster)
    assert world.last_roll.outcome == "大失敗"


def test_the_needed_number_never_drops_below_two(duel):
    world, hero, monster = duel
    monster.armor_class = -5  # a modifier so large it would beat any roll
    world.rng = ScriptedRandom([7])
    combat.resolve(world, hero, hero.abilities[0], monster)
    assert world.last_roll.needed == 2, "自然 1 永遠失手，所以門檻最低是 2"


def test_monster_rolls_are_flagged_as_hostile(duel):
    world, hero, monster = duel
    combat.take_monster_turn(world, monster)
    assert world.last_roll is not None
    assert world.last_roll.hostile


def test_healing_is_recorded_without_a_check(world):
    cleric = world.party[3]
    warrior = world.party[0]
    warrior.hp = 1
    warrior.position = (cleric.x, cleric.y + 1) if cleric.y + 1 < world.dungeon.height else warrior.position
    heal = next(a for a in cleric.abilities if a.id == "heal")
    combat.resolve(world, cleric, heal, warrior)

    roll = world.last_roll
    assert roll.check is None
    assert roll.needed is None
    assert roll.healing is not None
    assert roll.outcome == ""


def test_bursts_do_not_forecast_a_to_hit_number(world):
    mage = world.party[2]
    fireball = next(a for a in mage.abilities if a.id == "fireball")
    monster = monsters.RAT.spawn(1)
    monster.position = mage.position
    assert combat.forecast(world, mage, fireball, monster) is None


def test_every_roll_gets_a_fresh_serial(duel):
    world, hero, monster = duel
    seen = []
    for _ in range(3):
        monster.hp = monster.max_hp
        combat.resolve(world, hero, hero.abilities[0], monster)
        seen.append(world.last_roll.serial)
    assert seen == sorted(set(seen)), "序號要遞增，UI 才知道是不是同一次擲骰"


def test_repeated_messages_collapse_instead_of_flooding(world):
    world.log("同一件事", "warn")
    world.log("同一件事", "warn")
    world.log("同一件事", "warn")
    assert world.messages[-1].repeats == 3
    assert world.messages[-1].display == "同一件事 ×3"

    world.log("換一件事", "warn")
    assert world.messages[-1].repeats == 1
    assert world.messages[-1].display == "換一件事"
