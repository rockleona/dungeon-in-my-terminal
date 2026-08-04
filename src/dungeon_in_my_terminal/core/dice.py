"""Dice rolling and skill checks.

Everything random in the game funnels through here so that a single seeded
``random.Random`` reproduces an entire run, and so the UI has one consistent
place to pull "what was actually rolled" from when writing the combat log.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

DICE_PATTERN = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Roll:
    """The outcome of a dice expression such as ``2d6+3``."""

    faces: int
    dice: list[int] = field(default_factory=list)
    modifier: int = 0

    @property
    def total(self) -> int:
        return max(0, sum(self.dice) + self.modifier)

    def describe(self) -> str:
        parts = "+".join(str(d) for d in self.dice)
        if self.modifier:
            return f"[{parts}]{self.modifier:+d} = {self.total}"
        return f"[{parts}] = {self.total}"


@dataclass(frozen=True)
class Check:
    """A d20 check against a target number (attack vs AC, save vs DC...)."""

    natural: int
    modifier: int
    target: int
    advantage_roll: int | None = None

    @property
    def total(self) -> int:
        return self.natural + self.modifier

    @property
    def critical(self) -> bool:
        """Natural 20 always hits and doubles the damage dice."""
        return self.natural == 20

    @property
    def fumble(self) -> bool:
        """Natural 1 always misses, no matter how good the modifier is."""
        return self.natural == 1

    @property
    def success(self) -> bool:
        if self.critical:
            return True
        if self.fumble:
            return False
        return self.total >= self.target

    def describe(self) -> str:
        rolled = f"d20={self.natural}"
        if self.advantage_roll is not None:
            rolled = f"d20={self.natural}(優勢, 另一顆 {self.advantage_roll})"
        verdict = "重擊!" if self.critical else "大失敗!" if self.fumble else (
            "命中" if self.success else "落空"
        )
        return f"{rolled}{self.modifier:+d} = {self.total} vs {self.target} → {verdict}"


def parse(expression: str) -> tuple[int, int, int]:
    """Parse ``"2d6+3"`` into ``(count, faces, modifier)``."""
    match = DICE_PATTERN.match(expression)
    if not match:
        raise ValueError(f"看不懂的骰子式: {expression!r}")
    count_text, faces_text, modifier_text = match.groups()
    count = int(count_text) if count_text else 1
    modifier = int(modifier_text.replace(" ", "")) if modifier_text else 0
    return count, int(faces_text), modifier


def roll(rng: random.Random, expression: str, bonus: int = 0, crit: bool = False) -> Roll:
    """Roll a dice expression. ``crit`` doubles the number of dice, not the bonus."""
    count, faces, modifier = parse(expression)
    if crit:
        count *= 2
    dice = [rng.randint(1, faces) for _ in range(count)]
    return Roll(faces=faces, dice=dice, modifier=modifier + bonus)


def check(
    rng: random.Random,
    modifier: int,
    target: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> Check:
    """Roll d20 + modifier against ``target``.

    Advantage and disadvantage cancel each other out, as in tabletop play.
    """
    first = rng.randint(1, 20)
    if advantage == disadvantage:
        return Check(natural=first, modifier=modifier, target=target)
    second = rng.randint(1, 20)
    natural = max(first, second) if advantage else min(first, second)
    other = min(first, second) if advantage else max(first, second)
    return Check(natural=natural, modifier=modifier, target=target, advantage_roll=other)
