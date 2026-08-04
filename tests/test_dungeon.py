import random

import pytest

from dungeon_in_my_terminal.core import dungeon as D


@pytest.mark.parametrize("seed", range(30))
def test_every_floor_is_fully_connected(seed):
    floor = D.generate(depth=1 + seed % 9, rng=random.Random(seed))
    assert D.is_connected(floor), "地城出現了走不到的區域"


@pytest.mark.parametrize("seed", range(15))
def test_entrance_and_stairs_are_reachable_from_each_other(seed):
    floor = D.generate(depth=1 + seed % 4, rng=random.Random(seed))
    assert floor.is_walkable(*floor.entrance)
    assert floor.is_walkable(*floor.stairs)
    assert D.find_path(floor, floor.entrance, floor.stairs)


def test_stairs_are_not_placed_in_the_entrance_room():
    for seed in range(20):
        floor = D.generate(depth=2, rng=random.Random(seed))
        entrance_room = floor.room_at(*floor.entrance)
        assert entrance_room is not None
        assert not entrance_room.contains(*floor.stairs)


def test_the_final_floor_is_an_arena():
    floor = D.generate(depth=D.MAX_DEPTH, rng=random.Random(3))
    assert floor.is_boss_floor
    assert any(room.is_boss for room in floor.rooms)
    assert D.is_connected(floor)


@pytest.mark.parametrize("seed", range(5))
def test_the_arena_approach_is_wide_enough_to_walk_past_someone(seed):
    """A single-file hall lets one big monster wall the whole party out."""
    floor = D.generate(depth=D.MAX_DEPTH, rng=random.Random(seed))
    arena = next(room for room in floor.rooms if room.is_boss)
    entry = next(room for room in floor.rooms if not room.is_boss)
    hall_x = (entry.x + entry.width + arena.x) // 2
    open_tiles = [y for y in range(floor.height) if floor.is_walkable(hall_x, y)]
    assert len(open_tiles) >= 3, f"通道只有 {len(open_tiles)} 格寬"


def test_the_last_floor_has_no_way_down():
    floor = D.generate(depth=D.MAX_DEPTH, rng=random.Random(3))
    assert floor.stairs == (-1, -1)


def test_rooms_do_not_overlap():
    floor = D.generate(depth=1, rng=random.Random(11))
    for index, room in enumerate(floor.rooms):
        for other in floor.rooms[index + 1 :]:
            overlap = set(room.tiles()) & set(other.tiles())
            assert not overlap, "房間互相重疊了"


def test_line_of_sight_is_blocked_by_walls():
    floor = D.generate(depth=1, rng=random.Random(5))
    wall = next(
        (x, y)
        for y in range(1, floor.height - 1)
        for x in range(1, floor.width - 1)
        if not floor.is_walkable(x, y)
        and floor.is_walkable(x - 1, y)
        and floor.is_walkable(x + 1, y)
    )
    left = (wall[0] - 1, wall[1])
    right = (wall[0] + 1, wall[1])
    assert not D.has_line_of_sight(floor, left, right)
    assert D.has_line_of_sight(floor, left, left)


def test_find_path_respects_blocked_tiles():
    floor = D.generate(depth=1, rng=random.Random(2))
    start = floor.entrance
    goal = floor.stairs
    open_path = D.find_path(floor, start, goal)
    assert open_path
    # Walling off the very first step forces a different (or no) route.
    detour = D.find_path(floor, start, goal, blocked={open_path[0]})
    assert detour != open_path


def test_distance_is_manhattan():
    assert D.distance((0, 0), (3, 4)) == 7
