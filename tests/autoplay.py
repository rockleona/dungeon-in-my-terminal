"""A crude scripted player, used to drive whole runs without a terminal.

It is deliberately dumb — heal if someone is hurt, hit the best target in
reach, otherwise walk at the nearest woken monster or the stairs. That is
enough to prove a run can start, fight, descend and end without wedging.
"""

from __future__ import annotations

from dungeon_in_my_terminal.core import classes, combat
from dungeon_in_my_terminal.core.abilities import AbilityKind
from dungeon_in_my_terminal.core.dungeon import distance
from dungeon_in_my_terminal.core.entity import Team
from dungeon_in_my_terminal.core.game import GameMode, World
from dungeon_in_my_terminal.core.items import HEALING_POTION

DEFAULT_PARTY = [classes.WARRIOR, classes.RANGER, classes.MAGE, classes.CLERIC]


def _shop(world: World) -> None:
    """Spend gold the way the balance assumes a player would: gear first,
    best affordable slot upgrade per hero, then bank healing potions."""
    for hero in world.living(Team.PARTY):
        for slot in ("weapon", "armor"):
            worn = world.shop_gear() and next(
                (g for g in world.shop_gear() if g.id == hero.equipped.get(slot)), None
            )
            worn_tier = worn.tier if worn else 0
            upgrades = [
                g
                for g in world.shop_gear()
                if g.slot == slot and g.tier > worn_tier and g.price <= world.gold
            ]
            if upgrades:
                world.buy_gear(max(upgrades, key=lambda g: g.tier), hero)
    while world.buy_consumable(HEALING_POTION):
        if world.gold < 60:  # keep a little in reserve for gear next floor
            break


def _try_heal(world: World, hero) -> bool:
    for ability in hero.abilities:
        if ability.kind is not AbilityKind.HEAL or not combat.affordable(hero, ability):
            continue
        hurt = [a for a in combat.valid_targets(world, hero, ability) if a.hp < a.max_hp * 0.5]
        if hurt:
            return world.use_ability(ability, min(hurt, key=lambda e: e.hp))
    return False


def _try_attack(world: World, hero) -> bool:
    ranked = sorted(hero.abilities, key=lambda a: combat.average_damage(a.damage), reverse=True)
    for ability in ranked:
        if ability.kind is not AbilityKind.ATTACK or not combat.affordable(hero, ability):
            continue
        targets = combat.valid_targets(world, hero, ability)
        if targets:
            return world.use_ability(ability, targets[0])
    return False


def play(
    seed: int,
    party=None,
    max_actions: int = 5000,
    owners: list[int] | None = None,
    mode: GameMode = GameMode.SOLO,
) -> World:
    world = World(list(party or DEFAULT_PARTY), seed=seed, owners=owners, mode=mode)

    for _ in range(max_actions):
        if world.is_over:
            break
        hero = world.hero
        if hero is None:
            world.end_turn()
            continue

        acted = False
        if not world.turn.action_used:
            acted = _try_heal(world, hero) or _try_attack(world, hero)
        if world.is_over:
            break

        hero = world.hero
        if hero is None:
            continue

        awake = [m for m in world.living(Team.MONSTER) if m.awake]
        if hero.position == world.dungeon.stairs and not awake:
            _shop(world)  # a player would spend at the merchant before dropping
            world.descend()
            continue

        goal = (
            min(awake, key=lambda m: distance(hero.position, m.position)).position
            if awake
            else world.dungeon.stairs
        )
        if world.turn.moves_left > 0 and goal != (-1, -1):
            if combat.walk_towards(world, hero, goal, 1):
                world.turn.moves_left -= 1
                world._on_hero_entered(hero)
            else:
                world.end_turn()
                continue

        if world.turn.moves_left <= 0 or (acted and not awake):
            world.end_turn()

    return world
