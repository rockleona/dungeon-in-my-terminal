"""The TOML content loader (``core/content.py``) and the ``reload()`` /
``--content-dir`` wiring in ``classes.py``/``monsters.py``.

Malformed content must raise ``ContentError`` naming the offending id and
field rather than a bare Python traceback — that message is what a player
editing their own content actually sees (``cli.py`` prints it and exits).
"""

from __future__ import annotations

import pytest

from dungeon_in_my_terminal.core import classes, content, monsters


@pytest.fixture(autouse=True)
def _restore_registries():
    """Every test here calls reload(); put the built-in registries back so
    other test modules don't inherit a previous test's swapped-out content."""
    yield
    classes.reload()
    monsters.reload()


def test_load_toml_missing_file(tmp_path):
    with pytest.raises(content.ContentError, match="not found"):
        content.load_toml(tmp_path / "missing.toml")


def test_load_toml_invalid_syntax(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(content.ContentError, match="invalid TOML"):
        content.load_toml(bad)


def test_require_missing_field():
    with pytest.raises(content.ContentError, match=r"missing required field 'name'"):
        content.require({}, "name", "ctx")


def test_build_stats_rejects_unknown_field():
    with pytest.raises(content.ContentError, match=r"invalid \[stats\] table"):
        content.build_stats({"strength": 10, "nonsense": 1}, "ctx")


def test_build_ability_rejects_bad_kind():
    with pytest.raises(content.ContentError, match="kind"):
        content.build_ability(
            {"id": "x", "name": "x", "description": "x", "kind": "nope", "target": "enemy"},
            "ctx",
        )


def test_build_ability_rejects_bad_status():
    with pytest.raises(content.ContentError, match="status"):
        content.build_ability(
            {
                "id": "x",
                "name": "x",
                "description": "x",
                "kind": "attack",
                "target": "enemy",
                "status": "nope",
            },
            "ctx",
        )


CLASS_TOML = """
[warrior]
name = "測試戰士"
glyph = "W"
role = "role"
blurb = "blurb"
max_hp = 10
max_mp = 1
armor_class = 10
speed = 1
color = "red"

[warrior.stats]
strength = 10
dexterity = 10
intellect = 10
wisdom = 10
"""


def test_classes_reload_from_content_dir(tmp_path):
    (tmp_path / "classes.toml").write_text(CLASS_TOML, encoding="utf-8")
    classes.reload(tmp_path)
    assert [hero.id for hero in classes.CLASSES] == ["warrior"]
    assert classes.WARRIOR.name == "測試戰士"
    assert classes.RANGER is None


def test_classes_reload_falls_back_when_file_absent(tmp_path):
    classes.reload(tmp_path)  # tmp_path has no classes.toml
    assert classes.WARRIOR is not None
    assert classes.WARRIOR.name == "戰士"


def test_classes_reload_raises_on_malformed_file(tmp_path):
    (tmp_path / "classes.toml").write_text('[warrior]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(content.ContentError, match="missing required field"):
        classes.reload(tmp_path)


MONSTER_TOML_MISSING_BOSS_FLOOR = """
[slime]
name = "測試史萊姆"
glyph = "s"
max_hp = 5
armor_class = 10
speed = 1
ai = "melee"
is_boss = true

[slime.stats]
strength = 10
dexterity = 10
intellect = 10
wisdom = 10
"""

MONSTER_TOML_BAD_AI = """
[slime]
name = "測試史萊姆"
glyph = "s"
max_hp = 5
armor_class = 10
speed = 1
ai = "berserk"

[slime.stats]
strength = 10
dexterity = 10
intellect = 10
wisdom = 10
"""


def test_monsters_reload_boss_requires_boss_floor(tmp_path):
    (tmp_path / "monsters.toml").write_text(MONSTER_TOML_MISSING_BOSS_FLOOR, encoding="utf-8")
    with pytest.raises(content.ContentError, match="boss_floor"):
        monsters.reload(tmp_path)


def test_monsters_reload_rejects_bad_ai(tmp_path):
    (tmp_path / "monsters.toml").write_text(MONSTER_TOML_BAD_AI, encoding="utf-8")
    with pytest.raises(content.ContentError, match="ai"):
        monsters.reload(tmp_path)


def test_monsters_reload_falls_back_when_file_absent(tmp_path):
    # tmp_path has no monsters.toml — must still get the built-in bestiary.
    monsters.reload(tmp_path)
    assert monsters.SLIME is not None
    assert monsters.BOSSES[5].id == "goblin_king"
    assert monsters.BOSSES[10].id == "abyss_lord"


def test_content_dir_only_overrides_files_it_provides(tmp_path):
    """A content dir carrying only classes.toml must not disturb the
    built-in monster roster, and vice versa — each registry's reload()
    checks for its own file independently."""
    (tmp_path / "classes.toml").write_text(CLASS_TOML, encoding="utf-8")
    classes.reload(tmp_path)
    monsters.reload(tmp_path)
    assert classes.WARRIOR.name == "測試戰士"
    assert monsters.SLIME is not None
    assert monsters.SLIME.name == "史萊姆"


def test_default_files_load_without_error():
    """The shipped data/classes.toml and data/monsters.toml — the files
    reload() falls back to — must themselves parse cleanly."""
    assert len(classes.load(classes.DEFAULT_FILE)) == 4
    assert len(monsters.load(monsters.DEFAULT_FILE)) == 11
