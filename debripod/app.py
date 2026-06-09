from __future__ import annotations

from . import legacy


def create_app():
    return legacy.app


def main() -> None:
    legacy.main()


if __name__ == "__main__":
    main()
