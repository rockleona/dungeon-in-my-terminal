"""Shared TOML-loading helpers for ``classes.py`` and ``monsters.py``.

Content (numbers, text, ability lists) lives in ``data/*.toml``; the shapes
that content lands in (``HeroClass``, ``MonsterDef``, ``Ability``) and the
rules that resolve them stay in Python and stay put in their own modules.
This module only turns TOML tables into ``Ability``/``Stats`` and reports
malformed input with the offending id and field named, since a misconfigured
file is meant to be fixable by someone who isn't reading this source.

Never call ``i18n.t()`` here. Loading can happen before ``i18n.set_language()``
runs (module import time), so a translation done during loading would be
frozen in whatever language happened to be active then — see ``i18n.py``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .abilities import Ability, AbilityKind, TargetKind
from .entity import Stats, Status


class ContentError(ValueError):
    """A TOML content file is malformed. The message names the offending
    entry id and field so a player editing their own content can fix it."""


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ContentError(f"content file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ContentError(f"{path}: invalid TOML ({exc})") from exc


def require(table: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in table:
        raise ContentError(f"{ctx}: missing required field {key!r}")
    return table[key]


def build_stats(raw: dict[str, Any], ctx: str) -> Stats:
    try:
        return Stats(**raw)
    except TypeError as exc:
        raise ContentError(f"{ctx}: invalid [stats] table ({exc})") from exc


def _enum(kind_cls: type, raw: object, field: str, ctx: str) -> Any:
    try:
        return kind_cls(raw)
    except ValueError:
        valid = ", ".join(repr(m.value) for m in kind_cls)
        raise ContentError(
            f"{ctx}: {field} = {raw!r} is not valid; choose one of {valid}"
        ) from None


def build_ability(raw: dict[str, Any], ctx: str) -> Ability:
    ability_id = require(raw, "id", ctx)
    ctx = f"{ctx} ability {ability_id!r}"
    kind = _enum(AbilityKind, require(raw, "kind", ctx), "kind", ctx)
    target = _enum(TargetKind, require(raw, "target", ctx), "target", ctx)
    status = raw.get("status")
    if status is not None:
        status = _enum(Status, status, "status", ctx)
    try:
        return Ability(
            id=ability_id,
            name=require(raw, "name", ctx),
            description=require(raw, "description", ctx),
            kind=kind,
            target=target,
            stat=raw.get("stat", "strength"),
            reach=raw.get("reach", 1),
            mp_cost=raw.get("mp_cost", 0),
            damage=raw.get("damage"),
            healing=raw.get("healing"),
            radius=raw.get("radius", 0),
            hits=raw.get("hits", 1),
            advantage=raw.get("advantage", False),
            status=status,
            status_rounds=raw.get("status_rounds", 0),
            friendly_fire=raw.get("friendly_fire", False),
        )
    except TypeError as exc:
        raise ContentError(f"{ctx}: {exc}") from exc
