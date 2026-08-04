"""What the player is allowed to know, and what the UI reads to show it.

The initiative strip, the monster roll-call and the legend all read live world
state. They must stay honest about turn order without leaking where unseen
monsters are.
"""

from __future__ import annotations

import pytest

from dungeon_in_my_terminal.core import classes, combat
from dungeon_in_my_terminal.core.abilities import Ability, AbilityKind, TargetKind
from dungeon_in_my_terminal.core.entity import Team

render = pytest.importorskip("dungeon_in_my_terminal.ui.render", reason="需要 curses")


# -- the queue lookahead ---------------------------------------------------- #


def test_upcoming_follows_the_queue_from_the_current_unit(world):
    alive = [e for e in world.order if e.is_alive]
    assert len(alive) > 3, "這個種子的隊列應該夠長"
    ahead = world.upcoming(3)
    assert len(ahead) == 3
    assert world.current not in ahead
    start = alive.index(world.current)
    assert ahead == [alive[(start + step) % len(alive)] for step in (1, 2, 3)]


def test_upcoming_never_repeats_a_unit(world):
    ahead = world.upcoming(len(world.order) * 2)
    assert len(ahead) == len({id(e) for e in ahead})


def test_upcoming_skips_the_fallen(world):
    victim = world.order[(world.turn_index + 1) % len(world.order)]
    victim.hp = 0
    assert victim not in world.upcoming(len(world.order))


def test_upcoming_wraps_into_the_next_round(world):
    """Standing at the end of the queue still shows who opens the next round."""
    world.turn_index = len(world.order) - 1
    ahead = world.upcoming(2)
    assert ahead and ahead[0] is world.order[0]


# -- what the strip is allowed to name -------------------------------------- #


def test_unseen_monsters_stay_anonymous_in_the_strip(world):
    monster = world.living(Team.MONSTER)[0]
    world.visible = set()
    assert render.initiative_label(world, monster) == "?"

    world.visible = {monster.position}
    assert monster.name in render.initiative_label(world, monster)


def test_heroes_are_always_named_in_the_strip(world):
    hero = world.party[0]
    world.visible = set()  # heroes are yours; fog never hides them from you
    assert hero.name in render.initiative_label(world, hero)


# -- the monster roll-call -------------------------------------------------- #


def test_monster_panel_lists_only_what_is_visible(world):
    monsters = world.living(Team.MONSTER)
    assert monsters, "這個種子應該要有怪物"
    world.visible = {monsters[0].position}
    listed = render.visible_monsters(world)
    assert listed == [monsters[0]]

    world.visible = set()
    assert render.visible_monsters(world) == []


def test_monster_panel_sorts_nearest_first(world):
    from dungeon_in_my_terminal.core.dungeon import distance

    world.visible = {m.position for m in world.living(Team.MONSTER)}
    focus = world.current or world.party[0]
    gaps = [distance(focus.position, m.position) for m in render.visible_monsters(world)]
    assert gaps == sorted(gaps)


# -- the legend ------------------------------------------------------------- #


def test_legend_covers_the_party_and_the_terrain(world):
    glyphs = [glyph for glyph, _, _ in render.legend_rows(world)]
    assert {"#", ".", ">", "$"} <= set(glyphs)
    for hero in world.party:
        assert hero.glyph in glyphs


def test_legend_does_not_leak_unmet_monsters(world):
    world.visible = set()
    meanings = " ".join(text for _, _, text in render.legend_rows(world))
    for monster in world.living(Team.MONSTER):
        assert monster.name not in meanings

    monster = world.living(Team.MONSTER)[0]
    world.visible = {monster.position}
    meanings = " ".join(text for _, _, text in render.legend_rows(world))
    assert monster.name in meanings


# -- burst previews match the rules ----------------------------------------- #


def _nova() -> Ability:
    return next(a for a in classes.MAGE.abilities if a.id == "frost_nova")


def test_a_burst_preview_names_exactly_who_the_blast_will_hit(world):
    mage = next(h for h in world.party if h.archetype is classes.MAGE)
    nova = _nova()
    monster = world.living(Team.MONSTER)[0]
    monster.position = mage.position  # squarely inside the radius

    caught = combat.burst_victims(world, mage, nova, mage.position)
    assert monster in caught
    assert mage not in caught, "施法者不會被自己的新星波及"


def test_a_burst_without_friendly_fire_spares_teammates(world):
    mage = next(h for h in world.party if h.archetype is classes.MAGE)
    nova = _nova()
    assert not nova.friendly_fire
    ally = next(h for h in world.party if h is not mage)
    ally.position = mage.position

    assert ally not in combat.burst_victims(world, mage, nova, mage.position)


def test_a_burst_with_friendly_fire_catches_teammates(world):
    mage = next(h for h in world.party if h.archetype is classes.MAGE)
    ally = next(h for h in world.party if h is not mage)
    ally.position = mage.position
    blast = Ability(
        id="test_blast",
        name="測試爆炸",
        description="",
        kind=AbilityKind.BURST,
        target=TargetKind.SELF,
        radius=2,
        damage="1d4",
        friendly_fire=True,
    )
    assert ally in combat.burst_victims(world, mage, blast, mage.position)


def test_a_burst_ignores_anything_outside_the_radius(world):
    from dungeon_in_my_terminal.core.dungeon import distance

    mage = next(h for h in world.party if h.archetype is classes.MAGE)
    nova = _nova()
    world.visible = {m.position for m in world.living(Team.MONSTER)}
    for victim in combat.burst_victims(world, mage, nova, mage.position):
        assert distance(victim.position, mage.position) <= nova.radius
