import random

import pytest

from conftest import ScriptedRandom

from dungeon_in_my_terminal.core import dice


def test_parse_handles_the_shapes_the_data_files_use():
    assert dice.parse("1d8") == (1, 8, 0)
    assert dice.parse("2d6+3") == (2, 6, 3)
    assert dice.parse("d20-1") == (1, 20, -1)


def test_parse_rejects_nonsense():
    with pytest.raises(ValueError):
        dice.parse("兩顆骰子")


def test_roll_stays_within_bounds():
    rng = random.Random(7)
    for _ in range(500):
        result = dice.roll(rng, "2d6+3")
        assert 5 <= result.total <= 15
        assert len(result.dice) == 2


def test_critical_doubles_the_dice_but_not_the_modifier():
    rng = ScriptedRandom([4, 4])
    result = dice.roll(rng, "1d8+2", bonus=3, crit=True)
    assert len(result.dice) == 2
    assert result.total == 4 + 4 + 2 + 3


def test_damage_never_goes_negative():
    rng = ScriptedRandom([1])
    assert dice.roll(rng, "1d4-10").total == 0


def test_natural_twenty_hits_regardless_of_armour():
    rng = ScriptedRandom([20])
    result = dice.check(rng, modifier=-5, target=99)
    assert result.success and result.critical


def test_natural_one_misses_regardless_of_bonus():
    rng = ScriptedRandom([1])
    result = dice.check(rng, modifier=99, target=5)
    assert not result.success and result.fumble


def test_advantage_keeps_the_better_die():
    rng = ScriptedRandom([3, 17])
    result = dice.check(rng, modifier=0, target=10, advantage=True)
    assert result.natural == 17
    assert result.advantage_roll == 3


def test_advantage_and_disadvantage_cancel_out():
    rng = ScriptedRandom([11, 20])
    result = dice.check(rng, modifier=0, target=10, advantage=True, disadvantage=True)
    assert result.natural == 11
    assert result.advantage_roll is None


def test_roll_distribution_is_flat_enough():
    rng = random.Random(99)
    counts = [0] * 21
    for _ in range(20000):
        counts[dice.check(rng, 0, 10).natural] += 1
    for face in range(1, 21):
        assert 800 < counts[face] < 1200, f"面 {face} 出現 {counts[face]} 次"
