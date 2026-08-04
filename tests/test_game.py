"""Run-level rules: floors, turns, loot, permadeath and victory."""

from __future__ import annotations

import pytest

from dungeon_in_my_terminal.core import classes, combat, dungeon as D, items, monsters
from dungeon_in_my_terminal.core.entity import Status, Team
from dungeon_in_my_terminal.core.game import Chest, Phase, World


def force_turn(world: World, hero) -> None:
    """Put ``hero`` at the front of the queue with a fresh turn."""
    world.order = [hero] + [e for e in world.order if e is not hero]
    world.turn_index = 0
    world.turn.moves_left = hero.effective_speed
    world.turn.action_used = False


def test_a_new_run_starts_on_floor_one_with_everyone_alive(world):
    assert world.depth == 1
    assert world.phase is Phase.PLAYING
    assert len(world.living(Team.PARTY)) == 4
    assert world.hero is not None, "第一回合應該輪到某個隊員"


def test_party_starts_on_walkable_tiles_without_stacking(world):
    spots = [hero.position for hero in world.party]
    assert len(set(spots)) == len(spots)
    assert all(world.dungeon.is_walkable(*spot) for spot in spots)


def test_moving_spends_movement_and_walls_stop_you(world):
    hero = world.hero
    start = hero.position
    budget = world.turn.moves_left

    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if world.dungeon.is_walkable(hero.x + dx, hero.y + dy) and not world.entity_at(
            (hero.x + dx, hero.y + dy)
        ):
            assert world.move_hero(dx, dy)
            assert world.turn.moves_left == budget - 1
            assert hero.position != start
            return
    pytest.skip("這個種子開局四面都被擋住")


def test_you_cannot_walk_out_of_the_map(world):
    hero = world.hero
    hero.position = (0, 0)
    assert not world.move_hero(-1, 0)


def test_opening_a_chest_pays_gold_and_loot(world):
    hero = world.hero
    world.chests = [Chest(*hero.position)]
    world._open_chest(hero, world.chests[0])
    assert world.score.gold > 0
    assert world.score.chests_opened == 1
    assert sum(world.inventory.values()) == 1


def test_using_a_potion_consumes_it(world):
    hero = world.hero
    hero.hp = 1
    world.inventory["healing_potion"] = 1
    assert world.use_item(items.HEALING_POTION, hero)
    assert hero.hp > 1
    assert "healing_potion" not in world.inventory


def test_you_cannot_use_an_item_you_do_not_have(world):
    assert not world.use_item(items.HEALING_POTION, world.hero)


def test_only_one_main_action_per_turn(world):
    hero = world.hero
    world.turn.action_used = True
    world.inventory["healing_potion"] = 1
    assert not world.use_item(items.HEALING_POTION, hero)
    assert world.inventory["healing_potion"] == 1


def test_descending_needs_the_stairs(world):
    hero = world.hero
    hero.position = world.dungeon.entrance
    if hero.position == world.dungeon.stairs:
        pytest.skip("入口剛好就是樓梯")
    assert not world.descend()
    assert world.depth == 1


def test_descending_moves_the_party_down_and_patches_them_up(world):
    hero = world.hero
    hero.position = world.dungeon.stairs
    for member in world.party:
        member.hp = 5
        member.mp = 0
    assert world.descend()
    assert world.depth == 2
    assert world.score.depth_reached == 2
    assert all(m.hp > 5 for m in world.living(Team.PARTY))
    assert all(m.mp > 0 for m in world.living(Team.PARTY) if m.max_mp)


def test_each_floor_gets_a_brand_new_layout(world):
    first = [row[:] for row in world.dungeon.grid]
    world.enter_floor(2)
    assert world.dungeon.grid != first


def test_monsters_only_spawn_away_from_the_entrance_room(world):
    entrance_room = world.dungeon.room_at(*world.dungeon.entrance)
    for monster in world.living(Team.MONSTER):
        assert not entrance_room.contains(*monster.position)


def test_delay_hands_the_turn_to_another_hero(world):
    first = world.hero
    assert world.delay_turn()
    assert world.hero is not first
    assert world.turn.moves_left == world.hero.effective_speed


def test_delay_is_refused_once_you_have_moved(world):
    world.turn.moves_left -= 1
    assert not world.delay_turn()


def test_statuses_tick_once_per_round_even_when_delaying(world):
    hero = world.hero
    hero.apply(Status.BLESSED, 2)
    world.delay_turn()
    assert hero.statuses[Status.BLESSED] == 2, "換人不該多消耗一層狀態"


def test_the_turn_never_ends_by_itself(world):
    """Only `e` ends a turn — being cut off mid-thought is worse than a keypress."""
    hero = world.hero
    world.turn.moves_left = 0
    world.turn.action_used = True
    assert world.turn_spent
    assert world.hero is hero

    world.end_turn()
    assert world.hero is not hero


def test_acting_first_still_leaves_the_movement(world):
    hero = world.hero
    budget = world.turn.moves_left
    world.turn.action_used = True  # as if a skill had been used
    assert world.turn.moves_left == budget
    assert world.hero is hero


def test_a_wipe_ends_the_run(world):
    for hero in list(world.party):
        world.kill(hero)
    assert world.phase is Phase.DEFEAT
    assert world.is_over
    assert len(world.score.fallen) == 4


def test_killing_the_final_boss_wins_the_run(party):
    world = World(party, seed=99)
    world.enter_floor(D.MAX_DEPTH)
    boss = next(
        entity
        for entity in world.living(Team.MONSTER)
        if isinstance(entity.archetype, monsters.MonsterDef) and entity.archetype.is_boss
    )
    world.kill(boss, world.party[0])
    assert world.phase is Phase.VICTORY
    assert world.score.victory
    assert world.score.points > 1000


def test_earlier_floors_have_no_boss(party):
    world = World(party, seed=99)
    for depth in range(1, D.BOSS_EVERY):
        world.enter_floor(depth)
        assert not world.dungeon.is_boss_floor
        assert not any(
            isinstance(e.archetype, monsters.MonsterDef) and e.archetype.is_boss
            for e in world.living(Team.MONSTER)
        )


def test_the_last_floor_carries_exactly_one_boss(party):
    world = World(party, seed=5)
    world.enter_floor(D.MAX_DEPTH)
    bosses = [
        e
        for e in world.living(Team.MONSTER)
        if isinstance(e.archetype, monsters.MonsterDef) and e.archetype.is_boss
    ]
    assert len(bosses) == 1
    assert world.dungeon.is_boss_floor


def test_the_boss_is_pinned_to_its_arena(party):
    world = World(party, seed=5)
    world.enter_floor(D.MAX_DEPTH)
    arena = next(room for room in world.dungeon.rooms if room.is_boss)
    boss = next(
        e
        for e in world.living(Team.MONSTER)
        if isinstance(e.archetype, monsters.MonsterDef) and e.archetype.is_boss
    )
    assert boss.home_room is arena

    # Park the party out in the hall; the boss must not follow them into it.
    for index, hero in enumerate(world.party):
        hero.position = (arena.x - 4, arena.center[1] - 1 + index % 3)
    for _ in range(30):
        combat.take_monster_turn(world, boss)
        assert arena.contains(*boss.position), "王走出王房了，會把隊伍卡在走道裡"


def test_same_seed_produces_the_same_dungeon(party):
    first = World(party, seed=4242)
    second = World(party, seed=4242)
    assert first.dungeon.grid == second.dungeon.grid
    assert [m.name for m in first.living(Team.MONSTER)] == [
        m.name for m in second.living(Team.MONSTER)
    ]


def test_duplicate_classes_are_allowed():
    world = World([classes.WARRIOR] * 4, seed=1)
    assert len(world.party) == 4
    assert len({id(hero) for hero in world.party}) == 4, "同職業也要是各自獨立的角色"
    world.party[0].hp = 1
    assert world.party[1].hp == world.party[1].max_hp


def test_vision_remembers_where_you_have_been(world):
    world.refresh_vision()
    seen = set(world.explored)
    assert seen
    world.enter_floor(2)
    assert world.explored != seen, "新的一層應該重新開始探索"
