from __future__ import annotations

from typing import Callable


def register_shell_routes(app, render_shell: Callable[..., str]) -> None:
    @app.route("/", methods=["GET"])
    def index():
        return render_shell(autorefresh=0)
