"""Drive the curses interface inside a pty and print what the screen shows.

A TUI cannot be checked by reading code — this runs the real binary against a
real terminal emulator, feeds it keystrokes, and dumps the resulting screen as
plain text so layout and wide-character alignment can actually be verified.

    uv run python tools/tui_drive.py                 # walk through a short run
    uv run python tools/tui_drive.py --seed 30       # same dungeon every time
    uv run python tools/tui_drive.py --last 1        # only the final screen

Import ``drive`` from a scratch script to script your own key sequence.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import pty
import select
import struct
import sys
import termios
import time

import pyte

COLS, ROWS = 100, 34
LAUNCH = (
    "import sys; sys.path.insert(0, 'src'); "
    "from dungeon_in_my_terminal.cli import main; main()"
)


def drive(
    keys: list[tuple[str, bytes]],
    settle: float = 0.4,
    seed: int | None = None,
    cols: int = COLS,
    rows: int = ROWS,
    code: str | None = None,
) -> list[tuple[str, str]]:
    """Run the game, send each key, and snapshot the screen after each one.

    ``settle`` is how long to wait for output before snapshotting. Raise it if
    frames look like they lag a keypress behind; the dice animation and Esc
    handling both take a moment.
    """
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    env = dict(os.environ, TERM="xterm-256color", LINES=str(rows), COLUMNS=str(cols))

    pid, fd = pty.fork()
    if pid == 0:  # child: become the game
        argv = [sys.executable, "-c", code or LAUNCH]
        if seed is not None:
            argv += ["--seed", str(seed)]
        os.execvpe(sys.executable, argv, env)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(duration: float) -> None:
        deadline = time.time() + duration
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                return
            if not data:
                return
            stream.feed(data)

    frames = []
    pump(settle)
    frames.append(("start", "\n".join(screen.display)))
    for label, key in keys:
        os.write(fd, key)
        pump(settle)
        frames.append((label, "\n".join(screen.display)))

    os.close(fd)
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    return frames


def demo_script() -> list[tuple[str, bytes]]:
    """Menu, pick a full party, walk south until something is found, attack."""
    keys = [
        ("solo", b"1"),
        ("warrior", b"1"),
        ("ranger", b"2"),
        ("mage", b"3"),
        ("cleric", b"4"),
        ("start", b"\r"),
    ]
    for turn in range(9):
        keys += [(f"south {turn}.{step}", b"s") for step in range(5)]
        keys.append((f"end turn {turn}", b"e"))
    keys += [("aim ability 1", b"1"), ("confirm", b"\r")]
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=30)
    parser.add_argument("--settle", type=float, default=0.3)
    parser.add_argument("--last", type=int, default=0, help="only show the last N frames")
    parser.add_argument("--cols", type=int, default=COLS)
    parser.add_argument("--rows", type=int, default=ROWS)
    args = parser.parse_args()

    frames = drive(
        demo_script(), settle=args.settle, seed=args.seed, cols=args.cols, rows=args.rows
    )
    for label, frame in frames[-args.last :] if args.last else frames:
        print("=" * args.cols)
        print(f"### {label}")
        print(frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
