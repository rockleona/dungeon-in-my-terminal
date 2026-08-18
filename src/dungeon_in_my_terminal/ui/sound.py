"""Sound effects, played through ``pygame.mixer``.

Every call in here is best-effort. Headless CI, SSH sessions, and machines
with no audio device are all normal ways to run this game, and a hit landing
must never be what crashes a run — so init and playback both swallow failure
and just stay silent instead.

No audio assets ship with the package: the one effect we have is synthesised
on the fly, which sidesteps sourcing/licensing sample files for a single
short blip.
"""

from __future__ import annotations

import array
import math
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # keep pygame off curses' screen

try:
    import pygame
except ImportError:  # pragma: no cover - pygame ships as a normal dependency
    pygame = None

_FREQUENCY = 44100
_CHANNELS = 2

_enabled = False
_hit_sound: "pygame.mixer.Sound | None" = None


def init() -> None:
    """Start the mixer and prime the effects. Safe to call more than once."""
    global _enabled, _hit_sound
    if pygame is None or _enabled:
        return
    try:
        pygame.mixer.init(frequency=_FREQUENCY, size=-16, channels=_CHANNELS)
        _hit_sound = _make_hit_sound()
    except Exception:
        return
    _enabled = True


def play_hit() -> None:
    """Play the successful-hit blip, if the mixer came up."""
    if _enabled and _hit_sound is not None:
        try:
            _hit_sound.play()
        except Exception:
            pass


def _make_hit_sound() -> "pygame.mixer.Sound":
    duration = 0.07
    tone_hz = 220.0
    amplitude = 12000
    count = int(_FREQUENCY * duration)
    samples = array.array("h")
    for i in range(count):
        decay = 1.0 - i / count  # short percussive decay, not a sustained tone
        value = int(amplitude * decay * math.sin(2 * math.pi * tone_hz * i / _FREQUENCY))
        samples.extend((value,) * _CHANNELS)
    return pygame.mixer.Sound(buffer=samples.tobytes())
