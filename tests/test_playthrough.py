"""End-to-end smoke tests: play whole runs headlessly and check invariants."""

from __future__ import annotations

import autoplay
import pytest

from dungeon_in_my_terminal.core import classes, dungeon as D
from dungeon_in_my_terminal.core.entity import Team
from dungeon_in_my_terminal.core.game import Phase


@pytest.mark.parametrize("seed", [0, 3])
def test_a_whole_run_reaches_an_ending(seed):
    world = autoplay.play(seed)
    assert world.is_over, "跑完 5000 個行動仍未結束 — 流程可能卡住了"
    assert world.phase in (Phase.DEFEAT, Phase.VICTORY)
    assert world.score.depth_reached >= 1
    assert world.score.rounds > 0


def test_a_naive_party_still_gets_a_few_floors_in():
    """Guards against the difficulty curve becoming unplayable at floor 1."""
    depths = [autoplay.play(seed).score.depth_reached for seed in range(4)]
    assert sum(depths) / len(depths) >= 2.5, f"平均只到第 {sum(depths) / len(depths):.1f} 層，開場太難"


def test_the_run_ends_when_the_party_dies(seed=1):
    world = autoplay.play(seed)
    if world.phase is Phase.DEFEAT:
        assert not world.living(Team.PARTY)
        assert len(world.score.fallen) == len(world.party)


def test_state_stays_consistent_all_the_way_down():
    world = autoplay.play(2)
    for entity in world.entities:
        assert 0 <= entity.hp <= entity.max_hp
        assert 0 <= entity.mp <= entity.max_mp
        assert world.dungeon.in_bounds(*entity.position)
    positions = [e.position for e in world.living()]
    assert len(positions) == len(set(positions)), "有兩個單位站在同一格"
    assert world.score.depth_reached <= D.MAX_DEPTH


def test_a_solo_hero_can_also_play():
    world = autoplay.play(11, party=[classes.MAGE], max_actions=2000)
    assert len(world.party) == 1
    assert world.score.rounds > 0


def test_a_four_warrior_party_is_a_valid_run():
    world = autoplay.play(12, party=[classes.WARRIOR] * 4, max_actions=2000)
    assert len(world.party) == 4
    assert world.score.rounds > 0
