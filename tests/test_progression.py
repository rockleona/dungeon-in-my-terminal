"""Gold as a purse, XP into party levels, and gear bought from the merchant."""

from __future__ import annotations

from dungeon_in_my_terminal.core import classes, combat, game, shop
from dungeon_in_my_terminal.core.entity import Entity, Stats, Team
from dungeon_in_my_terminal.core.game import World
from dungeon_in_my_terminal.core.items import HEALING_POTION


def a_monster(world: World) -> Entity:
    return world.living(Team.MONSTER)[0]


# -- gold: lifetime score vs spendable purse --------------------------------- #


def test_earned_gold_fills_both_the_score_and_the_purse(world):
    world.gain_gold(50)
    assert world.score.gold == 50
    assert world.gold == 50


def test_spending_gold_leaves_the_lifetime_score_intact(world):
    world.gain_gold(100)
    item = HEALING_POTION
    assert world.buy_consumable(item)
    assert world.gold < 100  # purse shrank
    assert world.score.gold == 100  # score did not — shopping is not a penalty
    assert world.inventory[item.id] == 1


def test_a_purchase_you_cannot_afford_is_refused(world):
    world.gold = 0
    assert not world.buy_consumable(HEALING_POTION)
    assert HEALING_POTION.id not in world.inventory


# -- experience and party levels --------------------------------------------- #


def test_killing_a_monster_grants_party_xp(world):
    before = world.xp + (world.level - 1)  # any progress at all
    world.kill(a_monster(world), world.party[0])
    assert world.xp > 0 or world.level > 1
    assert (world.xp + world.level) > before


def test_crossing_the_threshold_levels_the_whole_party(world):
    warrior = next(h for h in world.party if h.archetype is classes.WARRIOR)
    hp_before = warrior.max_hp
    str_before = warrior.stats.strength

    world.level = 1
    # The price climbs with each level, so buy the first two in one payment.
    world.gain_xp(game.XP_PER_LEVEL * 1 + game.XP_PER_LEVEL * 2)

    assert world.level == 3
    assert warrior.max_hp > hp_before
    assert warrior.hp <= warrior.max_hp
    # One stat-up landed on the way (level 2), worth STAT_UP_AMOUNT points.
    assert warrior.stats.strength == str_before + game.STAT_UP_AMOUNT


def test_a_stat_up_always_moves_the_modifier(world):
    """Modifiers are ``(score - 10) // 2``, so an odd stat-up would be invisible.

    That invisibility is what made levelling feel flat, and it is easy to
    reintroduce by "just" lowering STAT_UP_AMOUNT — so pin it.
    """
    warrior = next(h for h in world.party if h.archetype is classes.WARRIOR)
    before = warrior.modifier("strength")

    world.level = game.STAT_UP_EVERY - 1
    world.gain_xp(world.xp_to_next)

    assert world.level % game.STAT_UP_EVERY == 0, "這一級應該要加屬性"
    assert warrior.modifier("strength") == before + 1


def test_the_fallen_do_not_level_up(world):
    victim = world.party[0]
    victim.hp = 0
    hp_before = victim.max_hp
    world.gain_xp(world.xp_to_next)
    assert victim.max_hp == hp_before


# -- gear bought from the merchant ------------------------------------------- #


def test_buying_a_weapon_boosts_hit_and_damage(world):
    hero = world.party[0]
    weapon = shop.BY_ID["keen_dagger"]
    world.gold = weapon.price
    assert world.buy_gear(weapon, hero)
    assert hero.bonus_hit == weapon.bonus_hit
    assert hero.bonus_damage == weapon.bonus_damage
    assert hero.equipped["weapon"] == weapon.id


def test_a_second_weapon_replaces_the_first_rather_than_stacking(world):
    hero = world.party[0]
    world.gold = 10_000
    world.buy_gear(shop.BY_ID["keen_dagger"], hero)
    world.buy_gear(shop.BY_ID["steel_sword"], hero)
    sword = shop.BY_ID["steel_sword"]
    assert hero.bonus_hit == sword.bonus_hit
    assert hero.bonus_damage == sword.bonus_damage
    assert hero.equipped["weapon"] == sword.id


def test_armour_raises_effective_ac_and_the_forecast_reflects_it(world):
    hero = world.party[0]
    plain_ac = hero.effective_ac
    world.gold = 10_000
    world.buy_gear(shop.BY_ID["chain_mail"], hero)
    assert hero.effective_ac == plain_ac + 2


def test_a_bought_weapon_lowers_the_number_a_hero_needs_to_roll(world):
    hero = next(h for h in world.party if h.archetype is classes.WARRIOR)
    target = a_monster(world)
    attack = next(a for a in hero.abilities if a.damage)
    before = combat.forecast(world, hero, attack, target)
    world.gold = 10_000
    world.buy_gear(shop.BY_ID["keen_dagger"], hero)  # +1 to hit
    after = combat.forecast(world, hero, attack, target)
    assert after[0] == before[0] - 1


# -- shop stock scales with depth -------------------------------------------- #


def test_deeper_floors_unlock_stronger_gear(world):
    world.depth = 1
    tier1 = {g.id for g in world.shop_gear()}
    world.depth = 8
    deep = {g.id for g in world.shop_gear()}
    assert "rune_blade" not in tier1
    assert "rune_blade" in deep
