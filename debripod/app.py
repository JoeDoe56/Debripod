from __future__ import annotations

from . import runtime


def create_app():
    return runtime.app


def main() -> None:
    runtime.main()


if __name__ == "__main__":
    main()
