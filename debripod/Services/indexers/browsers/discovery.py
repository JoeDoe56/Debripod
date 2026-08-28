from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class BrowserInfo:
    family: str
    display_name: str
    executable_path: str
    adapter_id: str
    is_default: bool = False


def _default_browser(system: str) -> str:
    try:
        if system == "windows":
            import winreg
            key_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                progid = str(winreg.QueryValueEx(key, "ProgId")[0]).casefold()
            return "edge" if "edge" in progid else "chrome" if "chrome" in progid else "firefox" if "firefox" in progid else "brave" if "brave" in progid else ""
        if system == "linux":
            value = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True, timeout=3).stdout.casefold()
            return "chrome" if "chrome" in value else "chromium" if "chromium" in value else "brave" if "brave" in value else "edge" if "edge" in value else "firefox" if "firefox" in value else ""
        if system == "darwin":
            value = subprocess.run(["defaults", "read", "com.apple.LaunchServices/com.apple.launchservices.secure", "LSHandlers"], capture_output=True, text=True, timeout=3).stdout.casefold()
            return "chrome" if "chrome" in value else "chromium" if "chromium" in value else "brave" if "brave" in value else "firefox" if "firefox" in value else "safari" if "safari" in value else ""
    except Exception:
        return ""
    return ""


def discover_browsers(*, system: str | None = None, default_resolver: Callable[[str], str] = _default_browser, which: Callable[[str], str | None] = shutil.which, exists: Callable[[str], bool] = os.path.isfile, environ: dict[str, str] | None = None) -> list[BrowserInfo]:
    system = (system or platform.system()).casefold()
    env = dict(os.environ if environ is None else environ)
    candidates: list[tuple[str, str, str, list[str]]] = []
    if system == "windows":
        local, program, program86 = env.get("LOCALAPPDATA", ""), env.get("PROGRAMFILES", ""), env.get("PROGRAMFILES(X86)", "")
        candidates = [
            ("edge", "Microsoft Edge", "chromium", [str(Path(program) / "Microsoft/Edge/Application/msedge.exe"), "msedge"]),
            ("chrome", "Google Chrome", "chromium", [str(Path(program) / "Google/Chrome/Application/chrome.exe"), str(Path(local) / "Google/Chrome/Application/chrome.exe"), "chrome"]),
            ("chromium", "Chromium", "chromium", [str(Path(local) / "Chromium/Application/chrome.exe"), "chromium"]),
            ("brave", "Brave", "chromium", [str(Path(program) / "BraveSoftware/Brave-Browser/Application/brave.exe"), str(Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe"), "brave"]),
            ("firefox", "Firefox", "firefox", [str(Path(program) / "Mozilla Firefox/firefox.exe"), str(Path(program86) / "Mozilla Firefox/firefox.exe"), "firefox"]),
        ]
    elif system == "darwin":
        candidates = [
            ("chrome", "Google Chrome", "chromium", ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]),
            ("chromium", "Chromium", "chromium", ["/Applications/Chromium.app/Contents/MacOS/Chromium"]),
            ("brave", "Brave", "chromium", ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]),
            ("firefox", "Firefox", "firefox", ["/Applications/Firefox.app/Contents/MacOS/firefox"]),
            ("safari", "Safari", "safari", ["/Applications/Safari.app/Contents/MacOS/Safari"]),
        ]
    else:
        candidates = [
            ("chrome", "Google Chrome", "chromium", ["google-chrome", "google-chrome-stable"]),
            ("chromium", "Chromium", "chromium", ["chromium", "chromium-browser"]),
            ("brave", "Brave", "chromium", ["brave-browser", "brave"]),
            ("edge", "Microsoft Edge", "chromium", ["microsoft-edge", "microsoft-edge-stable"]),
            ("firefox", "Firefox", "firefox", ["firefox"]),
        ]
    default = default_resolver(system)
    found: list[BrowserInfo] = []
    for browser_id, display, family, paths in candidates:
        executable = ""
        for candidate in paths:
            executable = candidate if exists(candidate) else (which(candidate) or "" if os.path.basename(candidate) == candidate else "")
            if executable:
                break
        if executable:
            found.append(BrowserInfo(family, display, str(executable), browser_id, browser_id == default))
    found.sort(key=lambda item: (not item.is_default, next(index for index, candidate in enumerate(candidates) if candidate[0] == item.adapter_id)))
    return found


discover_installed_browsers = discover_browsers
