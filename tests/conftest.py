"""Shared fixtures and a dice rigger for deterministic combat tests."""

from __future__ import annotations

import random

import pytest

from dungeon_in_my_terminal.core import classes
from dungeon_in_my_terminal.core.game import World


class ScriptedRandom(random.Random):
    """A ``Random`` whose ``randint`` results are queued up in advance.

    Anything not scripted falls back to the seeded sequence, so tests only have
    to pin down the rolls they actually care about.
    """

    def __init__(self, rolls: list[int] | None = None, seed: int = 0) -> None:
        super().__init__(seed)
        self.queued = list(rolls or [])

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        if self.queued:
            return max(a, min(b, self.queued.pop(0)))
        return super().randint(a, b)


@pytest.fixture
def party() -> list[classes.HeroClass]:
    return [classes.WARRIOR, classes.RANGER, classes.MAGE, classes.CLERIC]


@pytest.fixture
def world(party) -> World:
    return World(party, seed=1234)
