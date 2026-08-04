"""Layout helpers — the wide-character maths that keeps the panel aligned."""

from __future__ import annotations

import pytest

render = pytest.importorskip("dungeon_in_my_terminal.ui.render", reason="需要 curses")


def test_chinese_characters_count_as_two_columns():
    assert render.text_width("戰士") == 4
    assert render.text_width("W 戰士") == 6
    assert render.text_width("abc") == 3


def test_clip_never_splits_past_the_limit():
    assert render.clip("戰士遊俠", 5) == "戰士"  # 6 columns would overflow
    assert render.clip("abcdef", 3) == "abc"
    assert render.clip("anything", 0) == ""


def test_pad_fills_to_exactly_the_requested_columns():
    for text in ("戰士", "W 戰士", "ranger", ""):
        assert render.text_width(render.pad(text, 12)) == 12


def test_health_bar_tracks_the_ratio():
    assert render.bar(10, 10) == "█" * 10
    assert render.bar(0, 10) == "░" * 10
    assert render.bar(5, 10).count("█") == 5
    assert len(render.bar(3, 7, width=6)) == 6


def test_health_bar_survives_a_zero_maximum():
    assert render.bar(0, 0) == "░" * 10


def test_hp_colour_warns_as_health_drops(world):
    hero = world.party[0]
    hero.hp = hero.max_hp
    assert render.hp_colour(hero) == "green"
    hero.hp = int(hero.max_hp * 0.5)
    assert render.hp_colour(hero) == "yellow"
    hero.hp = 1
    assert render.hp_colour(hero) == "red"


def test_the_panel_splits_into_three_columns():
    for width in (72, 80, 100, 137):
        layout = render.columns(width)
        assert len(layout) == 3
        widths = [w for _, w in layout]
        assert max(widths) - min(widths) <= 2, f"寬度 {width} 的三欄不平均: {widths}"
        # Columns must not overlap and must stay inside the screen.
        for (x1, w1), (x2, _) in zip(layout, layout[1:]):
            assert x1 + w1 <= x2
        assert layout[-1][0] + layout[-1][1] <= width


def test_wrapping_keeps_every_character():
    text = "牧師 站在那裡，繞過去或請他先動（Tab）。"
    for width in (12, 20, 26, 40):
        lines = render.wrap(text, width)
        assert all(render.text_width(line) <= width for line in lines)
        assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_wrapping_keeps_short_phrases_whole():
    lines = render.wrap("巨鼠 擋在那裡 用攻擊而不是走過去。", 22)
    assert lines[-1] == "用攻擊而不是走過去。"


def test_odds_text_reads_the_way_a_player_thinks():
    assert render._odds_text(11, 20) == "11 以上命中 ‧ 20 爆擊"
    assert render._odds_text(None, 20) == "自動命中，不需擲骰"
    assert "只有 20" in render._odds_text(24, 20)


def test_splash_covers_the_radius_around_the_centre(world):
    from dungeon_in_my_terminal.core import classes
    from dungeon_in_my_terminal.core.dungeon import distance

    fireball = next(a for a in classes.MAGE.abilities if a.id == "fireball")
    centre = world.dungeon.entrance
    tiles = render.splash_tiles(world, fireball, centre)
    assert centre in tiles
    assert all(distance(tile, centre) <= fireball.radius for tile in tiles)
