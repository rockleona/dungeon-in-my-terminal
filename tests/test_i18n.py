"""The English translation table must cover every string actually used.

Two kinds of string reach ``i18n.t()``: literal templates written directly at
the call site (log lines, menu labels, hints) and registry data threaded
through as a plain string (a hero's name, an item's description). The first
kind we can find by walking the source; the second we check by asking each
registry which of its fields the UI actually displays.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from dungeon_in_my_terminal import i18n
from dungeon_in_my_terminal.core import classes, items, monsters, shop
from dungeon_in_my_terminal.core.entity import STAT_NAMES
from dungeon_in_my_terminal.i18n_strings import EN

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "dungeon_in_my_terminal"


@pytest.fixture(autouse=True)
def _reset_language():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


def test_identity_in_chinese():
    assert i18n.t("隨便寫點什麼 {n}", n=3) == "隨便寫點什麼 3"


def test_translates_in_english():
    i18n.set_language("en")
    assert i18n.t("戰士") == "Warrior"


def test_falls_back_when_missing(recwarn):
    i18n.set_language("en")
    assert i18n.t("這句話沒有翻譯") == "這句話沒有翻譯"
    assert any("missing" in str(w.message) for w in recwarn.list)


def test_context_disambiguates():
    """"祝福" is both the Bless ability's name and the Blessed status label —
    ``_ctx`` keeps their translations independently editable even though
    both currently read "Bless"."""
    i18n.set_language("en")
    assert "祝福" in EN
    assert "status\x1f祝福" in EN
    assert i18n.t("祝福") == EN["祝福"]
    assert i18n.t("祝福", _ctx="status") == EN["status\x1f祝福"]


def _literal_t_calls() -> set[str]:
    """Every ``i18n.t("...")`` call site whose first argument is a string
    literal, keyed the same way ``i18n.t`` itself builds lookup keys."""
    keys: set[str] = set()
    for path in SRC.rglob("*.py"):
        if path.name in ("i18n.py", "i18n_strings.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_t_call = (
                isinstance(func, ast.Attribute)
                and func.attr == "t"
                and isinstance(func.value, ast.Name)
                and func.value.id == "i18n"
            )
            if not is_t_call or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue  # a variable (e.g. a translated entity name), not a literal
            ctx = None
            for kw in node.keywords:
                if kw.arg == "_ctx" and isinstance(kw.value, ast.Constant):
                    ctx = kw.value.value
            key = first.value if ctx is None else f"{ctx}\x1f{first.value}"
            keys.add(key)
    return keys


def test_every_literal_template_has_an_english_entry():
    missing = sorted(key for key in _literal_t_calls() if key not in EN)
    assert not missing, f"missing EN translations for: {missing!r}"


# Registry fields the UI actually reads through i18n.t() — see render.py and
# app.py. A field left off this list is never shown, so it needs no entry
# (e.g. Ability.description on monster/hero abilities, Gear.description).
def _displayed_registry_strings() -> set[str]:
    strings: set[str] = set()
    for hero in classes.CLASSES:
        strings.update({hero.name, hero.role, hero.blurb})
        strings.update(ability.name for ability in hero.abilities)
    for monster in monsters.ROSTER + list(monsters.BOSSES.values()):
        strings.add(monster.name)
        strings.update(ability.name for ability in monster.abilities)
    for item in items.ALL:
        strings.update({item.name, item.description, item.ability.name})
    for gear in shop.GEAR:
        strings.add(gear.name)
    strings.update(STAT_NAMES.values())  # game.py:_level_up, i18n.t(STAT_NAMES[stat])
    return strings


def test_every_displayed_registry_string_has_an_english_entry():
    missing = sorted(s for s in _displayed_registry_strings() if s not in EN)
    assert not missing, f"missing EN translations for: {missing!r}"
