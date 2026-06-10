from __future__ import annotations

import json
import subprocess
from typing import Callable, List, Tuple

_ffprobe_path_provider: Callable[[], str] = lambda: "ffprobe"


def configure_probe(*, ffprobe_path_provider: Callable[[], str]) -> None:
    global _ffprobe_path_provider
    _ffprobe_path_provider = ffprobe_path_provider


def run_cmd(args: List[str]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except Exception as e:
        return 1, "", str(e)


def ffprobe_json(path: str) -> dict:
    code, out, err = run_cmd([_ffprobe_path_provider(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if code != 0:
        raise RuntimeError(err.strip() or "ffprobe failed")
    try:
        return json.loads(out)
    except Exception:
        raise RuntimeError("ffprobe returned invalid json")
