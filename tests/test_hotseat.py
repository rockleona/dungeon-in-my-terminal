"""Hotseat play: who owns which hero, and when the keyboard changes hands."""

from __future__ import annotations

import autoplay
import pytest

from dungeon_in_my_terminal.core import classes, monsters
from dungeon_in_my_terminal.core.entity import Team
from dungeon_in_my_terminal.core.game import GameMode, World


@pytest.fixture
def table() -> World:
    """Two players, two heroes each, seats interleaved as the menu assigns them."""
    return World(
        [classes.WARRIOR, classes.RANGER, classes.MAGE, classes.CLERIC],
        seed=21,
        owners=[0, 1, 0, 1],
        mode=GameMode.HOTSEAT,
    )


def test_solo_runs_have_no_seats(world):
    assert not world.is_hotseat
    assert world.seats == []
    assert all(hero.owner is None for hero in world.party)


def test_seats_are_assigned_as_given(table):
    assert table.is_hotseat
    assert table.seats == [0, 1]
    assert [hero.owner for hero in table.party] == [0, 1, 0, 1]


def test_each_seat_knows_its_heroes(table):
    assert [h.name for h in table.heroes_of(0)] == ["戰士", "法師"]
    assert [h.name for h in table.heroes_of(1)] == ["遊俠", "牧師"]


def test_seat_labels_are_one_based_for_humans(table):
    assert table.seat_label(0) == "玩家 1"
    assert table.seat_label(3) == "玩家 4"
    assert table.seat_label(None) == ""


def test_a_seat_is_out_only_once_all_its_heroes_are_down(table):
    first, second = table.heroes_of(0)
    table.kill(first)
    assert not table.seat_is_out(0)
    table.kill(second)
    assert table.seat_is_out(0)
    assert not table.seat_is_out(1)


def test_the_run_continues_while_another_seat_still_has_heroes(table):
    for hero in table.heroes_of(0):
        table.kill(hero)
    assert not table.is_over, "一位玩家出局不該結束整局"


def test_kills_are_credited_to_the_seat_that_landed_them(table):
    warrior = table.heroes_of(0)[0]
    ranger = table.heroes_of(1)[0]
    victim = monsters.RAT.spawn(1)
    table.entities.append(victim)

    table.kill(victim, warrior)
    assert table.score.kills_by_seat == {0: 1}

    other = monsters.RAT.spawn(1)
    table.entities.append(other)
    table.kill(other, ranger)
    assert table.score.kills_by_seat == {0: 1, 1: 1}


def test_solo_kills_are_not_attributed_to_a_seat(world):
    victim = monsters.RAT.spawn(1)
    world.entities.append(victim)
    world.kill(victim, world.party[0])
    assert world.score.kills_by_seat == {}
    assert world.score.kills == 1


def test_every_hero_still_gets_a_turn_in_the_queue(table):
    assert {id(hero) for hero in table.party} <= {id(entity) for entity in table.order}


def test_the_keyboard_changes_hands_across_a_round(table):
    """Walk the queue and confirm both seats come up."""
    seen = set()
    for _ in range(len(table.order) * 3):
        hero = table.hero
        if hero is not None:
            seen.add(hero.owner)
        table.end_turn()
        if table.is_over:
            break
    assert seen == {0, 1}, f"只有 {seen} 拿到回合"


def test_delaying_can_hand_the_turn_to_the_other_player(table):
    first = table.hero
    assert first is not None
    if len([h for h in table.order if h.team is Team.PARTY and h.is_alive]) < 2:
        pytest.skip("這個種子只有一位隊員排在後面")
    assert table.delay_turn()
    assert table.hero is not first


def test_duplicate_classes_get_numbered_names():
    world = World([classes.WARRIOR] * 3 + [classes.MAGE], seed=3)
    assert [hero.name for hero in world.party] == ["戰士 1", "戰士 2", "戰士 3", "法師"]


def test_a_single_class_keeps_its_plain_name(world):
    assert [hero.name for hero in world.party] == ["戰士", "遊俠", "法師", "牧師"]


def test_explicit_names_win_over_the_defaults():
    world = World([classes.WARRIOR, classes.WARRIOR], seed=3, names=["阿明", "小美"])
    assert [hero.name for hero in world.party] == ["阿明", "小美"]


def test_a_hotseat_run_plays_through_to_an_ending():
    world = autoplay.play(6, owners=[0, 1, 2, 3], mode=GameMode.HOTSEAT)
    assert world.is_over
    assert world.is_hotseat
    assert sum(world.score.kills_by_seat.values()) <= world.score.kills
