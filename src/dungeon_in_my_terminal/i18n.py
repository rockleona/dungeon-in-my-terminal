"""Language selection and string translation.

Every player-facing string is written as Traditional Chinese in the source —
that literal doubles as its own translation key (gettext-msgid style), so
adding a string never means inventing a key name. ``t()`` is the single
choke point: pass it the Chinese template (optionally with ``{name}``-style
placeholders) and any values to fill in, and it returns the string in
whichever language is currently selected.

No curses import here — this module is used by both ``core/`` and ``ui/``,
and ``core/`` must stay importable headlessly.
"""

from __future__ import annotations

import warnings

from .i18n_strings import TRANSLATIONS

_language = "zh"
_warned: set[str] = set()


def set_language(lang: str) -> None:
    global _language
    _language = lang


def get_language() -> str:
    return _language


def t(template: str, *, _ctx: str | None = None, **kwargs: object) -> str:
    """Translate ``template`` and fill in ``kwargs`` via ``str.format``.

    ``_ctx`` disambiguates the rare case where the same Chinese source string
    needs two different English translations depending on where it is used
    (e.g. the ability "祝福"/Bless vs. the status label "祝福"/Blessed) — it
    is folded into the lookup key, never into the formatted output.
    """
    key = template if _ctx is None else f"{_ctx}\x1f{template}"
    if _language != "zh":
        table = TRANSLATIONS.get(_language, {})
        translated = table.get(key)
        if translated is None:
            if key not in _warned:
                _warned.add(key)
                warnings.warn(
                    f"missing {_language!r} translation for {key!r}",
                    stacklevel=2,
                )
        else:
            template = translated
    return template.format(**kwargs) if kwargs else template
