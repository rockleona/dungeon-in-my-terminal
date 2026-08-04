"""Procedural dungeon generation.

Rooms come from a BSP split: the map is recursively cut in two, a room is
carved inside every leaf, and each split is stitched back together with an
L-shaped corridor. Connecting along the tree means the result is connected by
construction — there is no "regenerate until it works" loop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

WALL = 0
FLOOR = 1
STAIRS = 2

TILE_GLYPHS = {WALL: "#", FLOOR: ".", STAIRS: ">"}

DEFAULT_WIDTH = 68
DEFAULT_HEIGHT = 20
MIN_LEAF = 9
BOSS_EVERY = 5
MAX_DEPTH = 10
"""How deep a run goes. Floors 5 and 10 are boss floors; 10 ends the run."""
HALL_WIDTH = 3
HALL_LENGTH = 6


@dataclass
class Room:
    x: int
    y: int
    width: int
    height: int
    is_boss: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def tiles(self) -> list[tuple[int, int]]:
        return [
            (x, y)
            for y in range(self.y, self.y + self.height)
            for x in range(self.x, self.x + self.width)
        ]


@dataclass
class Dungeon:
    width: int
    height: int
    depth: int
    grid: list[list[int]]
    rooms: list[Room] = field(default_factory=list)
    entrance: tuple[int, int] = (0, 0)
    stairs: tuple[int, int] = (0, 0)
    chest_spots: list[tuple[int, int]] = field(default_factory=list)
    is_boss_floor: bool = False

    def tile(self, x: int, y: int) -> int:
        if not self.in_bounds(x, y):
            return WALL
        return self.grid[y][x]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        return self.tile(x, y) != WALL

    def room_at(self, x: int, y: int) -> Room | None:
        for room in self.rooms:
            if room.contains(x, y):
                return room
        return None

    def walkable_tiles(self) -> list[tuple[int, int]]:
        return [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if self.grid[y][x] != WALL
        ]


# --------------------------------------------------------------------------- #
# BSP layout
# --------------------------------------------------------------------------- #


@dataclass
class _Node:
    x: int
    y: int
    width: int
    height: int
    left: "_Node | None" = None
    right: "_Node | None" = None
    room: Room | None = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


def _split(node: _Node, rng: random.Random, budget: int) -> None:
    if budget <= 0:
        return

    can_split_h = node.height >= MIN_LEAF * 2
    can_split_v = node.width >= MIN_LEAF * 2
    if not can_split_h and not can_split_v:
        return

    if can_split_h and can_split_v:
        # Split the longer axis so rooms stay reasonably square.
        if node.width > node.height * 1.25:
            horizontal = False
        elif node.height > node.width * 1.25:
            horizontal = True
        else:
            horizontal = rng.random() < 0.5
    else:
        horizontal = can_split_h

    if horizontal:
        cut = rng.randint(MIN_LEAF, node.height - MIN_LEAF)
        node.left = _Node(node.x, node.y, node.width, cut)
        node.right = _Node(node.x, node.y + cut, node.width, node.height - cut)
    else:
        cut = rng.randint(MIN_LEAF, node.width - MIN_LEAF)
        node.left = _Node(node.x, node.y, cut, node.height)
        node.right = _Node(node.x + cut, node.y, node.width - cut, node.height)

    _split(node.left, rng, budget - 1)
    _split(node.right, rng, budget - 1)


def _carve_rooms(node: _Node, grid: list[list[int]], rng: random.Random, rooms: list[Room]) -> None:
    if not node.is_leaf:
        for child in (node.left, node.right):
            if child is not None:
                _carve_rooms(child, grid, rng, rooms)
        return

    # Leave a one-tile wall border inside the partition so rooms never touch.
    max_w = max(4, node.width - 3)
    max_h = max(3, node.height - 3)
    width = rng.randint(min(5, max_w), max_w)
    height = rng.randint(min(4, max_h), max_h)
    x = node.x + rng.randint(1, max(1, node.width - width - 1))
    y = node.y + rng.randint(1, max(1, node.height - height - 1))

    room = Room(x=x, y=y, width=width, height=height)
    node.room = room
    rooms.append(room)
    _fill(grid, room, FLOOR)


def _fill(grid: list[list[int]], room: Room, tile: int) -> None:
    for x, y in room.tiles():
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            grid[y][x] = tile


def _pick_room(node: _Node, rng: random.Random) -> Room:
    """Any room from this subtree — used as a corridor endpoint."""
    if node.room is not None:
        return node.room
    children = [child for child in (node.left, node.right) if child is not None]
    return _pick_room(rng.choice(children), rng)


def _carve_corridor(grid: list[list[int]], a: tuple[int, int], b: tuple[int, int], rng: random.Random) -> None:
    (ax, ay), (bx, by) = a, b
    if rng.random() < 0.5:
        _carve_h(grid, ax, bx, ay)
        _carve_v(grid, ay, by, bx)
    else:
        _carve_v(grid, ay, by, ax)
        _carve_h(grid, ax, bx, by)


def _carve_h(grid: list[list[int]], x1: int, x2: int, y: int) -> None:
    for x in range(min(x1, x2), max(x1, x2) + 1):
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            grid[y][x] = max(grid[y][x], FLOOR)


def _carve_v(grid: list[list[int]], y1: int, y2: int, x: int) -> None:
    for y in range(min(y1, y2), max(y1, y2) + 1):
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            grid[y][x] = max(grid[y][x], FLOOR)


def _carve_hall(grid: list[list[int]], left_room: Room, right_room: Room) -> None:
    """Join two rooms with a hall wide enough that nobody can cork it."""
    y = left_room.center[1]
    x1 = left_room.x + left_room.width - 1
    x2 = right_room.x
    for offset in range(-(HALL_WIDTH // 2), HALL_WIDTH // 2 + 1):
        _carve_h(grid, x1, x2, y + offset)


def _connect(node: _Node, grid: list[list[int]], rng: random.Random) -> None:
    if node.is_leaf:
        return
    left, right = node.left, node.right
    if left is None or right is None:
        return
    _connect(left, grid, rng)
    _connect(right, grid, rng)
    _carve_corridor(grid, _pick_room(left, rng).center, _pick_room(right, rng).center, rng)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def generate(
    depth: int,
    rng: random.Random,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> Dungeon:
    """Build the floor for ``depth``. Every 5th floor is a boss arena."""
    if depth % BOSS_EVERY == 0:
        return _generate_boss(depth, rng, width, height)

    grid = [[WALL] * width for _ in range(height)]
    root = _Node(0, 0, width, height)
    _split(root, rng, budget=4)

    rooms: list[Room] = []
    _carve_rooms(root, grid, rng, rooms)
    _connect(root, grid, rng)

    dungeon = Dungeon(width=width, height=height, depth=depth, grid=grid, rooms=rooms)
    _place_features(dungeon, rng)
    return dungeon


def _generate_boss(depth: int, rng: random.Random, width: int, height: int) -> Dungeon:
    """A boss floor is a short approach into one big arena — nowhere to hide.

    The approach is a three-tile-wide hall, not a corridor: a single-file
    passage lets one big body plug the only route and wedge the whole party
    behind it.
    """
    grid = [[WALL] * width for _ in range(height)]

    entry_w, entry_h = 9, 5
    entry = Room(
        x=2,
        y=(height - entry_h) // 2,
        width=entry_w,
        height=entry_h,
    )
    arena_h = min(14, height - 4)
    arena_x = entry.x + entry_w + HALL_LENGTH
    arena = Room(
        x=arena_x,
        y=(height - arena_h) // 2,
        width=max(12, width - arena_x - 3),
        height=arena_h,
        is_boss=True,
    )
    _fill(grid, entry, FLOOR)
    _fill(grid, arena, FLOOR)
    _carve_hall(grid, entry, arena)

    dungeon = Dungeon(
        width=width,
        height=height,
        depth=depth,
        grid=grid,
        rooms=[entry, arena],
        is_boss_floor=True,
    )
    dungeon.entrance = entry.center
    if depth < MAX_DEPTH:
        sx, sy = arena.x + arena.width - 2, arena.y + arena.height - 2
        grid[sy][sx] = STAIRS
        dungeon.stairs = (sx, sy)
    else:
        # The final floor has no way down; killing the boss ends the run.
        dungeon.stairs = (-1, -1)
    dungeon.chest_spots = [(arena.x + 1, arena.y + 1)]
    return dungeon


def _place_features(dungeon: Dungeon, rng: random.Random) -> None:
    """Pick the entrance, put the stairs as far away as possible, scatter chests."""
    rooms = dungeon.rooms
    entrance_room = rooms[0]
    dungeon.entrance = entrance_room.center

    ex, ey = dungeon.entrance
    far_room = max(rooms[1:], key=lambda r: abs(r.center[0] - ex) + abs(r.center[1] - ey))
    sx, sy = far_room.center
    dungeon.grid[sy][sx] = STAIRS
    dungeon.stairs = (sx, sy)

    candidates = [room for room in rooms if room is not entrance_room and room is not far_room]
    rng.shuffle(candidates)
    for room in candidates[: rng.randint(1, 2)]:
        spot = rng.choice(room.tiles())
        if dungeon.tile(*spot) == FLOOR:
            dungeon.chest_spots.append(spot)


def spawn_tiles(dungeon: Dungeon, room: Room, count: int, rng: random.Random) -> list[tuple[int, int]]:
    """Pick ``count`` distinct free floor tiles inside ``room``."""
    options = [t for t in room.tiles() if dungeon.tile(*t) == FLOOR and t not in dungeon.chest_spots]
    rng.shuffle(options)
    return options[:count]


def is_connected(dungeon: Dungeon) -> bool:
    """Flood fill sanity check — used by the tests, not by generation."""
    walkable = set(dungeon.walkable_tiles())
    if not walkable:
        return False
    start = next(iter(walkable))
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in walkable and (nx, ny) not in seen:
                seen.add((nx, ny))
                stack.append((nx, ny))
    return seen == walkable


# --------------------------------------------------------------------------- #
# Grid helpers shared by combat, AI and rendering
# --------------------------------------------------------------------------- #


def neighbours(x: int, y: int) -> list[tuple[int, int]]:
    """Four-way movement — diagonals would make ranges and cover fiddly."""
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Manhattan distance, matching four-way movement."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def line(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """Bresenham line from ``a`` to ``b``, inclusive of both ends."""
    x0, y0 = a
    x1, y1 = b
    points = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return points
        err2 = err * 2
        if err2 > -dy:
            err -= dy
            x0 += sx
        if err2 < dx:
            err += dx
            y0 += sy


def has_line_of_sight(dungeon: Dungeon, a: tuple[int, int], b: tuple[int, int]) -> bool:
    return all(dungeon.is_walkable(x, y) for x, y in line(a, b)[1:-1])


def find_path(
    dungeon: Dungeon,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Breadth-first path from ``start`` to ``goal``, excluding ``start``.

    Returns ``[]`` when unreachable. ``goal`` itself is allowed to be blocked
    (that is the normal case: you are walking towards something standing there).
    """
    if start == goal:
        return []
    blocked = blocked or set()
    frontier: list[tuple[int, int]] = [start]
    came_from: dict[tuple[int, int], tuple[int, int]] = {start: start}

    while frontier:
        nxt: list[tuple[int, int]] = []
        for current in frontier:
            for step in neighbours(*current):
                if step in came_from or not dungeon.is_walkable(*step):
                    continue
                if step in blocked and step != goal:
                    continue
                came_from[step] = current
                if step == goal:
                    return _rebuild(came_from, start, goal)
                nxt.append(step)
        frontier = nxt
    return []


def _rebuild(
    came_from: dict[tuple[int, int], tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    path.reverse()
    return path[1:]
