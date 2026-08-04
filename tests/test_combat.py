"""Combat rules, exercised on a hand-built floor so positions are predictable."""

from __future__ import annotations

import random

import pytest
from conftest import ScriptedRandom

from dungeon_in_my_terminal.core import combat, dungeon as D, monsters
from dungeon_in_my_terminal.core.abilities import Ability, AbilityKind, TargetKind
from dungeon_in_my_terminal.core.entity import Entity, Status
from dungeon_in_my_terminal.core.game import World


@pytest.fixture
def arena(party):
    """One open room, party at a known spot, no other monsters in the way."""
    world = World(party, seed=7)
    width, height = 20, 11
    grid = [[D.WALL] * width for _ in range(height)]
    room = D.Room(x=1, y=1, width=width - 2, height=height - 2)
    for x, y in room.tiles():
        grid[y][x] = D.FLOOR
    world.dungeon = D.Dungeon(width=width, height=height, depth=1, grid=grid, rooms=[room])
    world.dungeon.entrance = (2, 5)
    world.dungeon.stairs = (17, 5)
    world.chests = []
    world.entities = list(world.party)
    for index, hero in enumerate(world.party):
        hero.position = (2, 2 + index)
    world.order = list(world.party)
    world.turn_index = 0
    world.refresh_vision()
    return world


def spawn(world: World, definition, spot: tuple[int, int]) -> Entity:
    monster = definition.spawn(world.depth)
    monster.position = spot
    monster.awake = True
    world.entities.append(monster)
    return monster


def test_a_hit_deals_damage_and_a_miss_does_not(arena):
    warrior = arena.party[0]
    rat = spawn(arena, monsters.RAT, (3, 2))
    cleave = warrior.abilities[0]

    arena.rng = ScriptedRandom([20, 5, 5])  # crit, then two damage dice
    combat.resolve(arena, warrior, cleave, rat)
    assert rat.hp < rat.max_hp

    rat.hp = rat.max_hp
    arena.rng = ScriptedRandom([1])  # natural 1 always misses
    combat.resolve(arena, warrior, cleave, rat)
    assert rat.hp == rat.max_hp


def test_killing_a_monster_scores_it(arena):
    warrior = arena.party[0]
    rat = spawn(arena, monsters.RAT, (3, 2))
    rat.hp = 1
    arena.rng = ScriptedRandom([20, 8, 8])
    combat.resolve(arena, warrior, warrior.abilities[0], rat)
    assert not rat.is_alive
    assert arena.score.kills == 1


def test_out_of_range_targets_are_not_offered(arena):
    ranger = arena.party[1]
    far = spawn(arena, monsters.RAT, (17, 9))
    near = spawn(arena, monsters.RAT, (4, 3))
    shot = ranger.abilities[0]
    assert near in combat.valid_targets(arena, ranger, shot)
    assert far not in combat.valid_targets(arena, ranger, shot)


def test_abilities_cost_mana_and_are_refused_without_it(arena):
    mage = arena.party[2]
    spawn(arena, monsters.RAT, (5, 4))
    fireball = next(a for a in mage.abilities if a.id == "fireball")

    mage.mp = 0
    assert combat.blocked_reason(arena, mage, fireball)
    assert not combat.resolve(arena, mage, fireball, (5, 4))

    mage.mp = mage.max_mp
    assert combat.resolve(arena, mage, fireball, (5, 4))
    assert mage.mp == mage.max_mp - fireball.mp_cost


def test_fireball_catches_allies_but_frost_nova_does_not(arena):
    mage = arena.party[2]
    mage.position = (6, 5)
    cleric = arena.party[3]
    cleric.position = (6, 6)
    rat = spawn(arena, monsters.RAT, (6, 4))

    fireball = next(a for a in mage.abilities if a.id == "fireball")
    arena.rng = random.Random(3)
    combat.resolve(arena, mage, fireball, (6, 5))
    assert cleric.hp < cleric.max_hp, "火球應該會波及隊友"

    cleric.hp = cleric.max_hp
    rat.hp = rat.max_hp
    nova = next(a for a in mage.abilities if a.id == "frost_nova")
    mage.mp = mage.max_mp
    combat.resolve(arena, mage, nova, None)
    assert cleric.hp == cleric.max_hp, "冰霜新星不該打到隊友"
    assert rat.hp < rat.max_hp
    assert rat.has(Status.SLOWED)


def test_healing_is_capped_at_max_hp(arena):
    cleric = arena.party[3]
    warrior = arena.party[0]
    warrior.hp = warrior.max_hp - 1
    warrior.position = (2, 3)
    cleric.position = (2, 4)
    heal = next(a for a in cleric.abilities if a.id == "heal")
    combat.resolve(arena, cleric, heal, warrior)
    assert warrior.hp == warrior.max_hp


def test_taunt_pulls_nearby_monsters_onto_the_warrior(arena):
    warrior = arena.party[0]
    warrior.position = (5, 5)
    close = spawn(arena, monsters.RAT, (6, 5))
    far = spawn(arena, monsters.RAT, (15, 9))
    taunt = next(a for a in warrior.abilities if a.id == "taunt")

    combat.resolve(arena, warrior, taunt, None)
    assert close.taunted_by is warrior
    assert far.taunted_by is None
    assert combat.choose_target(arena, close) is warrior


def test_stun_makes_a_monster_skip_its_turn(arena):
    rat = spawn(arena, monsters.RAT, (5, 5))
    rat.apply(Status.STUNNED, 1)
    before = rat.position
    combat.take_monster_turn(arena, rat)
    assert rat.position == before


def test_sleeping_monsters_stay_put_until_they_see_the_party(arena):
    rat = spawn(arena, monsters.RAT, (17, 9))
    rat.awake = False
    for hero in arena.party:
        hero.position = (2, 2)
    # Out of sight range on a map this size, so it should not stir.
    rat.archetype = monsters.MonsterDef(**{**vars(monsters.RAT), "sight": 1})
    before = rat.position
    combat.take_monster_turn(arena, rat)
    assert rat.position == before
    assert not rat.awake


def test_melee_monsters_close_the_distance(arena):
    warrior = arena.party[0]
    warrior.position = (10, 5)
    for other in arena.party[1:]:
        other.position = (2, 1)
    rat = spawn(arena, monsters.RAT, (16, 5))

    combat.take_monster_turn(arena, rat)
    assert D.distance(rat.position, warrior.position) < 6


def test_ranged_monsters_back_off_when_you_get_close(arena):
    warrior = arena.party[0]
    warrior.position = (5, 5)
    for other in arena.party[1:]:
        other.position = (2, 1)
    archer = spawn(arena, monsters.SKELETON_ARCHER, (6, 5))

    combat.take_monster_turn(arena, archer)
    assert D.distance(archer.position, warrior.position) > 1


def test_support_monsters_heal_their_wounded_friends(arena):
    shaman = spawn(arena, monsters.GOBLIN_SHAMAN, (10, 5))
    hurt = spawn(arena, monsters.GOBLIN_WARRIOR, (11, 5))
    hurt.hp = 2
    combat.take_monster_turn(arena, shaman)
    assert hurt.hp > 2


def test_being_hit_wakes_a_monster_up(arena):
    ranger = arena.party[1]
    ranger.position = (5, 5)
    rat = spawn(arena, monsters.RAT, (8, 5))
    rat.awake = False
    arena.rng = ScriptedRandom([20, 4, 4])
    combat.resolve(arena, ranger, ranger.abilities[0], rat)
    assert rat.awake


def test_multi_hit_abilities_roll_each_swing_separately(arena):
    ranger = arena.party[1]
    ranger.position = (5, 5)
    rat = spawn(arena, monsters.SLIME, (7, 5))
    twin = next(a for a in ranger.abilities if a.id == "twin_shot")
    arena.rng = ScriptedRandom([18, 3, 18, 3])
    combat.resolve(arena, ranger, twin, rat)
    rolls = [m for m in arena.messages if m.kind == "roll"]
    assert len(rolls) == 2


def test_initiative_favours_dexterity_on_average(world):
    ranger_first = 0
    for seed in range(200):
        world.rng = random.Random(seed)
        order = combat.roll_initiative(world, list(world.party))
        if order[0] is world.party[1]:
            ranger_first += 1
    assert ranger_first > 200 / 4, "遊俠的敏捷應該讓它比較常先攻"


def test_blessed_heroes_hit_more_often(arena):
    warrior = arena.party[0]
    plain = warrior.attack_modifier("strength")
    warrior.apply(Status.BLESSED, 3)
    assert warrior.attack_modifier("strength") == plain + 2


def test_burst_needs_line_of_sight_to_the_centre(arena):
    mage = arena.party[2]
    mage.position = (5, 5)
    arena.dungeon.grid[5][7] = D.WALL
    victim = spawn(arena, monsters.RAT, (9, 5))
    fireball = next(a for a in mage.abilities if a.id == "fireball")
    assert not combat.in_range(arena, mage, fireball, victim.position)


def test_average_damage_matches_the_dice():
    assert combat.average_damage("2d6+3") == pytest.approx(10.0)
    assert combat.average_damage(None) == 0.0


def test_unknown_ability_kinds_do_not_crash(arena):
    warrior = arena.party[0]
    odd = Ability(
        id="odd",
        name="測試",
        description="",
        kind=AbilityKind.BUFF,
        target=TargetKind.SELF,
        status=Status.BLESSED,
        status_rounds=2,
    )
    assert combat.resolve(arena, warrior, odd, None)
    assert warrior.has(Status.BLESSED)
