"""Command line entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dungeon",
        description="終端機裡的地城 — 程序生成、骰子驅動的回合制地城探索。",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="固定亂數種子，用同一個地城重玩（結算畫面會顯示這局的種子碼）",
    )
    args = parser.parse_args(argv)

    try:
        import curses  # noqa: F401
    except ImportError:  # pragma: no cover - Windows without the shim
        print("找不到 curses。Windows 請先安裝：pip install windows-curses", file=sys.stderr)
        return 1

    from .ui.app import launch

    launch(seed=args.seed)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
