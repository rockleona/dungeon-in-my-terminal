"""Combat rules and monster behaviour.

Heroes and monsters go through the same functions here: ``resolve`` applies an
ability no matter who used it, and ``take_monster_turn`` is just an automatic
way of choosing which ability to feed it.

Everything takes a ``world`` (see :mod:`.game`) but only touches a small slice
of it — the dungeon, the entity list, the rng and the log — so the rules stay
testable without a screen attached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import dice
from .abilities import Ability, AbilityKind, TargetKind
from .dungeon import distance, find_path, has_line_of_sight
from .entity import Entity, Status, Team
from .monsters import AI, MonsterDef

if TYPE_CHECKING:  # pragma: no cover
    from .game import World

TOO_CLOSE = 2
"""A ranged monster inside this distance will try to back off before shooting."""


# --------------------------------------------------------------------------- #
# Turn order
# --------------------------------------------------------------------------- #


def roll_initiative(world: "World", entities: list[Entity]) -> list[Entity]:
    """Order units by d20 + dexterity, highest first.

    The roll is kept as the sort key so the ranger's dexterity actually buys it
    the first shot most of the time.
    """
    scored = []
    for entity in entities:
        result = dice.check(world.rng, entity.modifier("dexterity"), target=0)
        scored.append((result.total, entity.modifier("dexterity"), world.rng.random(), entity))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[-1] for item in scored]


# --------------------------------------------------------------------------- #
# Targeting rules
# --------------------------------------------------------------------------- #


def in_range(world: "World", actor: Entity, ability: Ability, spot: tuple[int, int]) -> bool:
    if distance(actor.position, spot) > ability.reach:
        return False
    return has_line_of_sight(world.dungeon, actor.position, spot)


def is_hostile(actor: Entity, other: Entity) -> bool:
    return actor.team is not other.team


def valid_targets(world: "World", actor: Entity, ability: Ability) -> list[Entity]:
    """Which entities this ability could legally be pointed at right now."""
    if ability.target is TargetKind.SELF:
        return [actor]
    candidates = []
    for other in world.living():
        if ability.target is TargetKind.ENEMY and not is_hostile(actor, other):
            continue
        if ability.target is TargetKind.ALLY and is_hostile(actor, other):
            continue
        if other is actor and ability.target is TargetKind.ENEMY:
            continue
        if not in_range(world, actor, ability, other.position):
            continue
        candidates.append(other)
    candidates.sort(key=lambda e: distance(actor.position, e.position))
    return candidates


def affordable(actor: Entity, ability: Ability) -> bool:
    return actor.mp >= ability.mp_cost


def blocked_reason(world: "World", actor: Entity, ability: Ability) -> str | None:
    """Why this ability can't be used, or ``None`` if it can."""
    if not affordable(actor, ability):
        return f"魔力不足（需要 {ability.mp_cost}MP）"
    if ability.target is TargetKind.TILE or ability.target is TargetKind.SELF:
        return None
    if not valid_targets(world, actor, ability):
        return "射程內沒有目標"
    return None


# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #


def occupied_tiles(world: "World", ignore: Entity | None = None) -> set[tuple[int, int]]:
    return {e.position for e in world.living() if e is not ignore}


def off_limits(world: "World", mover: Entity) -> set[tuple[int, int]]:
    """Tiles a leashed entity refuses to enter — everything outside its room."""
    room = mover.home_room
    if room is None:
        return set()
    return {tile for tile in world.dungeon.walkable_tiles() if not room.contains(*tile)}


def walk_towards(world: "World", mover: Entity, goal: tuple[int, int], steps: int) -> int:
    """Move up to ``steps`` tiles along the shortest path. Returns tiles moved.

    Corridors are one tile wide, so whoever gets there first can wall everyone
    else off. When no clear route exists we fall back to the route that ignores
    other units and walk it until we bump into someone — which leaves the
    mover face to face with whatever is in the way, ready to attack it.
    """
    if steps <= 0:
        return 0
    fenced = off_limits(world, mover)
    blocked = occupied_tiles(world, ignore=mover) | fenced
    path = find_path(world.dungeon, mover.position, goal, blocked)
    if not path:
        path = find_path(world.dungeon, mover.position, goal, fenced)
    if not path and fenced:
        # Leashed and the target is out of bounds: come to the edge of the
        # room nearest them and hold there rather than standing around.
        path = _approach_within_room(world, mover, goal, blocked)
    if not path:
        return 0
    moved = 0
    for tile in path[:steps]:
        if tile in blocked:
            break
        mover.position = tile
        moved += 1
    return moved


def _approach_within_room(
    world: "World", mover: Entity, goal: tuple[int, int], blocked: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    room = mover.home_room
    if room is None:
        return []
    reachable = [
        tile
        for tile in room.tiles()
        if world.dungeon.is_walkable(*tile) and tile not in blocked
    ]
    if not reachable:
        return []
    closest = min(reachable, key=lambda tile: distance(tile, goal))
    return find_path(world.dungeon, mover.position, closest, blocked)


def retreat_from(world: "World", mover: Entity, threat: Entity, steps: int) -> int:
    """Back away one step at a time, preferring tiles that keep line of sight."""
    blocked = occupied_tiles(world, ignore=mover) | off_limits(world, mover)
    moved = 0
    for _ in range(steps):
        best = None
        best_key = (distance(mover.position, threat.position), 0)
        for tile in _adjacent_free(world, mover.position, blocked):
            gap = distance(tile, threat.position)
            sight = 1 if has_line_of_sight(world.dungeon, tile, threat.position) else 0
            if (gap, sight) > best_key:
                best, best_key = tile, (gap, sight)
        if best is None:
            break
        mover.position = best
        moved += 1
    return moved


def _adjacent_free(
    world: "World", spot: tuple[int, int], blocked: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    x, y = spot
    return [
        (nx, ny)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
        if world.dungeon.is_walkable(nx, ny) and (nx, ny) not in blocked
    ]


# --------------------------------------------------------------------------- #
# Ability resolution
# --------------------------------------------------------------------------- #


def resolve(
    world: "World",
    actor: Entity,
    ability: Ability,
    target: Entity | tuple[int, int] | None = None,
) -> bool:
    """Apply ``ability``. Returns False (and logs why) if it could not be used."""
    if not affordable(actor, ability):
        world.log(f"{actor.name} 的魔力不足以施放 {ability.name}。", "warn")
        return False

    spot = _target_spot(actor, target)
    if ability.target is not TargetKind.SELF and spot is None:
        world.log(f"{ability.name} 需要一個目標。", "warn")
        return False
    if spot is not None and ability.reach and not in_range(world, actor, ability, spot):
        world.log(f"{ability.name} 打不到那裡。", "warn")
        return False

    actor.spend_mp(ability.mp_cost)

    match ability.kind:
        case AbilityKind.ATTACK:
            _resolve_attack(world, actor, ability, target)
        case AbilityKind.BURST:
            centre = actor.position if ability.target is TargetKind.SELF else spot
            _resolve_burst(world, actor, ability, centre or actor.position)
        case AbilityKind.HEAL:
            _resolve_heal(world, actor, ability, target)
        case AbilityKind.RESTORE:
            _resolve_restore(world, actor, ability, target)
        case AbilityKind.BUFF:
            _resolve_buff(world, actor, ability, target)
        case AbilityKind.TAUNT:
            _resolve_taunt(world, actor, ability)
    return True


def _target_spot(actor: Entity, target: Entity | tuple[int, int] | None) -> tuple[int, int] | None:
    if target is None:
        return None
    if isinstance(target, Entity):
        return target.position
    return target


def _resolve_attack(
    world: "World", actor: Entity, ability: Ability, target: Entity | tuple[int, int] | None
) -> None:
    if not isinstance(target, Entity):
        world.log(f"{ability.name} 需要指定一個單位。", "warn")
        return

    for swing in range(ability.hits):
        if not target.is_alive:
            break
        label = f"{actor.name} 的 {ability.name}"
        if ability.hits > 1:
            label += f"（第 {swing + 1} 擊）"
        result = dice.check(
            world.rng,
            actor.attack_modifier(ability.stat),
            target.effective_ac,
            advantage=ability.advantage,
        )
        report = world.note_roll(actor, ability.name, target, result)
        world.log(f"{label} → {target.name}: {result.describe()}", "roll")

        if not result.success:
            continue

        damage = dice.roll(
            world.rng,
            ability.damage or "1d4",
            bonus=actor.modifier(ability.stat) + actor.bonus_damage,
            crit=result.critical,
        )
        report.damage = damage
        dealt = target.take_damage(damage.total)
        world.log(f"  傷害 {damage.describe()} → {target.name} 損失 {dealt} 點生命。", "damage")
        _wake(target, actor)

        if ability.status and target.is_alive:
            target.apply(ability.status, ability.status_rounds)
            world.log(f"  {target.name} 陷入{ability.status.label}（{ability.status_rounds} 回合）。", "info")

        if not target.is_alive:
            world.kill(target, actor)
            break


def burst_victims(
    world: "World", actor: Entity, ability: Ability, centre: tuple[int, int]
) -> list[Entity]:
    """Everyone a burst centred on ``centre`` would actually catch.

    The UI previews a blast with this before the player commits the MP, so it
    lives next to the resolution below rather than being re-derived there —
    a preview that disagrees with the rules is worse than no preview.
    """
    return [
        victim
        for victim in world.living()
        if victim is not actor
        and (ability.friendly_fire or is_hostile(actor, victim))
        and distance(victim.position, centre) <= ability.radius
        and has_line_of_sight(world.dungeon, centre, victim.position)
    ]


def _resolve_burst(world: "World", actor: Entity, ability: Ability, centre: tuple[int, int]) -> None:
    world.log(f"{actor.name} 施放 {ability.name}！", "roll")
    for victim in burst_victims(world, actor, ability, centre):
        if not victim.is_alive:
            continue  # an earlier blast in this same burst already felled them

        damage = dice.roll(world.rng, ability.damage or "1d6")
        world.note_roll(actor, ability.name, victim).damage = damage
        dealt = victim.take_damage(damage.total)
        world.log(f"  {victim.name} 被波及 {damage.describe()} → 損失 {dealt} 點生命。", "damage")
        _wake(victim, actor)

        if ability.status and victim.is_alive and is_hostile(actor, victim):
            victim.apply(ability.status, ability.status_rounds)
            world.log(f"  {victim.name} 陷入{ability.status.label}。", "info")

        if not victim.is_alive:
            world.kill(victim, actor)


def _resolve_heal(
    world: "World", actor: Entity, ability: Ability, target: Entity | tuple[int, int] | None
) -> None:
    if not isinstance(target, Entity):
        target = actor
    roll = dice.roll(world.rng, ability.healing or "1d4", bonus=actor.modifier(ability.stat))
    world.note_roll(actor, ability.name, target).healing = roll
    healed = target.restore(roll.total)
    world.log(
        f"{actor.name} 對 {target.name} 施放 {ability.name}: {roll.describe()} → 回復 {healed} 點生命。",
        "heal",
    )


def _resolve_restore(
    world: "World", actor: Entity, ability: Ability, target: Entity | tuple[int, int] | None
) -> None:
    if not isinstance(target, Entity):
        target = actor
    roll = dice.roll(world.rng, ability.healing or "1d4")
    gained = min(target.max_mp - target.mp, roll.total)
    target.mp += gained
    world.log(f"{target.name} 回復了 {gained} 點魔力。", "heal")


def _resolve_buff(
    world: "World", actor: Entity, ability: Ability, target: Entity | tuple[int, int] | None
) -> None:
    if not isinstance(target, Entity):
        target = actor
    if ability.status:
        target.apply(ability.status, ability.status_rounds)
        world.log(
            f"{actor.name} 對 {target.name} 施放 {ability.name}"
            f" → {ability.status.label} {ability.status_rounds} 回合。",
            "heal",
        )


def _resolve_taunt(world: "World", actor: Entity, ability: Ability) -> None:
    pulled = 0
    for enemy in world.living():
        if not is_hostile(actor, enemy):
            continue
        if distance(enemy.position, actor.position) > ability.radius:
            continue
        enemy.apply(Status.TAUNTED, ability.status_rounds)
        enemy.taunted_by = actor
        enemy.awake = True
        pulled += 1
    world.log(f"{actor.name} 大吼挑釁，{pulled} 個敵人被激怒了！", "info")


def _wake(entity: Entity, source: Entity) -> None:
    """Getting hit always wakes something up, even out of its sight range."""
    if entity.team is Team.MONSTER:
        entity.awake = True


# --------------------------------------------------------------------------- #
# Monster AI
# --------------------------------------------------------------------------- #


def forecast(world: "World", actor: Entity, ability: Ability, target: Entity) -> tuple[int, int] | None:
    """What this attack needs to roll: ``(hits on, crits on)``.

    Returned before anything is rolled so the player can weigh the odds while
    still choosing a target. ``None`` for abilities that skip the to-hit roll.
    """
    if ability.kind is not AbilityKind.ATTACK:
        return None
    needed = target.effective_ac - actor.attack_modifier(ability.stat)
    return max(2, needed), 20


def average_damage(expression: str | None) -> float:
    if not expression:
        return 0.0
    count, faces, modifier = dice.parse(expression)
    return count * (faces + 1) / 2 + modifier


def should_wake(world: "World", monster: Entity) -> bool:
    definition = monster.archetype
    sight = definition.sight if isinstance(definition, MonsterDef) else 8
    for hero in world.living(Team.PARTY):
        if distance(monster.position, hero.position) <= sight and has_line_of_sight(
            world.dungeon, monster.position, hero.position
        ):
            return True
    return False


def choose_target(world: "World", monster: Entity) -> Entity | None:
    """Taunt wins; otherwise go for the closest hero, breaking ties on low HP."""
    heroes = world.living(Team.PARTY)
    if not heroes:
        return None
    if monster.taunted_by is not None and monster.taunted_by.is_alive:
        return monster.taunted_by
    return min(heroes, key=lambda h: (distance(monster.position, h.position), h.hp))


def _attacks(monster: Entity) -> list[Ability]:
    return [a for a in monster.abilities if a.kind in (AbilityKind.ATTACK, AbilityKind.BURST)]


def _best_attack(monster: Entity, gap: int) -> Ability | None:
    usable = [a for a in _attacks(monster) if a.reach >= gap and affordable(monster, a)]
    if not usable:
        return None
    return max(usable, key=lambda a: average_damage(a.damage))


def _longest_reach(monster: Entity) -> int:
    return max((a.reach for a in _attacks(monster)), default=1)


def take_monster_turn(world: "World", monster: Entity) -> None:
    """One full monster turn: wake check, movement, then a single action."""
    if not monster.is_alive:
        return

    if not monster.awake:
        if not should_wake(world, monster):
            return
        monster.awake = True
        world.log(f"{monster.name} 注意到了你們！", "warn")

    if monster.has(Status.STUNNED):
        world.log(f"{monster.name} 還在暈眩，這回合無法行動。", "info")
        return

    target = choose_target(world, monster)
    if target is None:
        return

    behaviour = monster.archetype.ai if isinstance(monster.archetype, MonsterDef) else AI.MELEE
    if behaviour is AI.SUPPORT and _try_support(world, monster):
        return

    moves = monster.effective_speed
    gap = distance(monster.position, target.position)

    if behaviour is AI.RANGED and gap <= TOO_CLOSE:
        retreat_from(world, monster, target, min(moves, 2))
    elif not _can_hit_now(world, monster, target):
        walk_towards(world, monster, target.position, moves)

    gap = distance(monster.position, target.position)
    ability = _best_attack(monster, gap)
    if ability is None or not has_line_of_sight(world.dungeon, monster.position, target.position):
        return

    if ability.kind is AbilityKind.BURST:
        resolve(world, monster, ability, target.position)
    else:
        resolve(world, monster, ability, target)


def _can_hit_now(world: "World", monster: Entity, target: Entity) -> bool:
    gap = distance(monster.position, target.position)
    if gap > _longest_reach(monster):
        return False
    return has_line_of_sight(world.dungeon, monster.position, target.position)


def _try_support(world: "World", monster: Entity) -> bool:
    """Healers patch up the worst-off ally before considering anything else."""
    heal = next((a for a in monster.abilities if a.kind is AbilityKind.HEAL), None)
    if heal is None:
        return False
    wounded = [
        ally
        for ally in world.living(monster.team)
        if ally.hp < ally.max_hp * 0.6 and in_range(world, monster, heal, ally.position)
    ]
    if not wounded:
        return False
    patient = min(wounded, key=lambda a: a.hp / a.max_hp)
    resolve(world, monster, heal, patient)
    return True
