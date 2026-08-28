from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlparse

from selenium import webdriver

from ..challenge_detection import detect_challenge
from .discovery import BrowserInfo, discover_browsers


_HOST_LOCKS: dict[str, threading.Lock] = {}
_LOCK_GUARD = threading.Lock()


def _host_lock(host: str) -> threading.Lock:
    with _LOCK_GUARD:
        return _HOST_LOCKS.setdefault(host, threading.Lock())


class BrowserAdapter:
    def __init__(self, browser: BrowserInfo, profile_path: Path):
        self.browser = browser
        self.profile_path = profile_path

    def start(self):
        raise NotImplementedError


class ChromiumAdapter(BrowserAdapter):
    def start(self):
        options_class = webdriver.EdgeOptions if self.browser.adapter_id == "edge" else webdriver.ChromeOptions
        arguments = (
            f"--user-data-dir={self.profile_path}", "--no-first-run", "--no-default-browser-check",
            "--disable-popup-blocking", "--disable-blink-features=AutomationControlled",
            "--window-position=-32000,-32000", "--window-size=640,480", "--remote-debugging-port=0",
        )
        port_file = self.profile_path / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        process = subprocess.Popen(
            [self.browser.executable_path, *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not port_file.is_file():
                if process.poll() is not None:
                    raise RuntimeError("installed Chromium exited before DevTools became available")
                time.sleep(.1)
            if not port_file.is_file():
                raise RuntimeError("installed Chromium did not expose DevTools")
            port = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
            options = options_class()
            options.binary_location = self.browser.executable_path
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            driver = webdriver.Edge(options=options) if self.browser.adapter_id == "edge" else webdriver.Chrome(options=options)
            return _AttachedChromiumDriver(driver, process)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
            raise


class _AttachedChromiumDriver:
    def __init__(self, driver: Any, process: subprocess.Popen):
        self._driver = driver
        self._process = process

    def __getattr__(self, name: str) -> Any:
        return getattr(self._driver, name)

    def quit(self) -> None:
        try:
            self._driver.quit()
        finally:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except Exception:
                    self._process.kill()


class FirefoxAdapter(BrowserAdapter):
    def start(self):
        options = webdriver.FirefoxOptions()
        options.binary_location = self.browser.executable_path
        options.profile = str(self.profile_path)
        driver = webdriver.Firefox(options=options)
        driver.set_window_size(640, 480)
        driver.minimize_window()
        return driver


class SafariAdapter(BrowserAdapter):
    def start(self):
        try:
            return webdriver.Safari()
        except Exception as exc:
            raise RuntimeError("Safari automation is unavailable; enable safaridriver remote automation") from exc


class BrowserChallengeSolver:
    def __init__(self, *, repo_root: str | Path | None = None, status_store: Any = None, discover: Callable[[], list[BrowserInfo]] = discover_browsers, adapter_factory: Callable[[BrowserInfo, Path], BrowserAdapter] | None = None, timeout: float = 45, poll_interval: float = .5, sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time):
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[4]
        self.profile_root = self.repo_root / "data" / "browser-profiles"
        self.status_store = status_store
        self.discover = discover
        self.adapter_factory = adapter_factory or self._adapter
        self.timeout, self.poll_interval, self.sleep, self.now = float(timeout), float(poll_interval), sleep, now

    @staticmethod
    def _adapter(browser: BrowserInfo, profile: Path) -> BrowserAdapter:
        return FirefoxAdapter(browser, profile) if browser.family == "firefox" else SafariAdapter(browser, profile) if browser.family == "safari" else ChromiumAdapter(browser, profile)

    def _stored(self, indexer_id: str) -> dict[str, Any] | None:
        if self.status_store is None:
            return None
        status = self.status_store.get(indexer_id)
        if status.cookies and (not status.cookies_expiration or status.cookies_expiration > self.now()):
            return {"ok": True, "adapter": "stored", "browser": "stored clearance", "cookies": status.cookies, "user_agent": status.user_agent, "final_url": "", "elapsed_ms": 0}
        return None

    def solve(self, indexer_id: str, url: str, response: Any = None) -> dict[str, Any]:
        host = (urlparse(url).hostname or "").casefold()
        if not host:
            return {"ok": False, "error": "challenge URL has no host"}
        with _host_lock(host):
            stored = self._stored(indexer_id)
            if stored:
                return stored
            started = self.now()
            errors: list[str] = []
            for browser in self.discover():
                profile = self.profile_root / browser.adapter_id / hashlib.sha1(host.encode()).hexdigest()
                profile.mkdir(parents=True, exist_ok=True)
                driver = None
                try:
                    driver = self.adapter_factory(browser, profile).start()
                    driver.get(url)
                    consecutive = 0
                    while self.now() - started < self.timeout:
                        page = SimpleNamespace(status_code=503, headers={}, text=str(driver.page_source or ""))
                        consecutive = 0 if detect_challenge(page).detected else consecutive + 1
                        if consecutive >= 2:
                            cookies = [cookie for cookie in driver.get_cookies() if not cookie.get("domain") or host.endswith(str(cookie.get("domain") or "").lstrip("."))]
                            user_agent = str(driver.execute_script("return navigator.userAgent") or "")
                            result = {"ok": True, "adapter": browser.adapter_id, "browser": browser.display_name, "cookies": cookies, "user_agent": user_agent, "final_url": str(driver.current_url or ""), "elapsed_ms": int((self.now() - started) * 1000)}
                            if self.status_store is not None:
                                self.status_store.save_clearance(indexer_id, cookies, user_agent)
                            return result
                        self.sleep(self.poll_interval)
                    errors.append(f"{browser.display_name}: challenge timeout")
                except Exception as exc:
                    errors.append(f"{browser.display_name}: {exc}")
                finally:
                    if driver is not None:
                        try:
                            driver.quit()
                        except Exception:
                            pass
            return {"ok": False, "error": "; ".join(errors) or "no supported installed browser", "elapsed_ms": int((self.now() - started) * 1000)}
