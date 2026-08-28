from types import SimpleNamespace

from debripod.Services.indexers.browsers.discovery import BrowserInfo
from debripod.Services.indexers.browsers.solver import BrowserChallengeSolver


CHALLENGE = "<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>"
NORMAL = "<title>Tracker</title><main>results</main>"


class Driver:
    def __init__(self, pages, fail_get=False):
        self.pages = list(pages); self.reads = 0; self.fail_get = fail_get; self.quit_called = False; self.current_url = "https://tracker.test/search"
    def get(self, url):
        if self.fail_get: raise RuntimeError("navigation failed")
    @property
    def page_source(self):
        value = self.pages[min(self.reads, len(self.pages) - 1)]; self.reads += 1; return value
    def get_cookies(self): return [{"name": "clearance", "value": "ok", "domain": ".tracker.test", "path": "/"}]
    def execute_script(self, script): return "Browser UA"
    def quit(self): self.quit_called = True


class Adapter:
    def __init__(self, driver): self.driver = driver
    def start(self): return self.driver


def test_default_browser_first_fallback_and_two_clean_checks(tmp_path):
    browsers = [BrowserInfo("chromium", "Default", "default", "chrome", True), BrowserInfo("firefox", "Fallback", "fallback", "firefox")]
    drivers = {"chrome": Driver([CHALLENGE], fail_get=True), "firefox": Driver([CHALLENGE, NORMAL, NORMAL])}
    clock = [0.0]
    solver = BrowserChallengeSolver(repo_root=tmp_path, discover=lambda: browsers, adapter_factory=lambda browser, profile: Adapter(drivers[browser.adapter_id]), timeout=45, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0])
    result = solver.solve("demo", "https://tracker.test/search")
    assert result["ok"] and result["adapter"] == "firefox"
    assert result["cookies"][0]["name"] == "clearance" and result["user_agent"] == "Browser UA"
    assert drivers["chrome"].quit_called and drivers["firefox"].quit_called
    profile = tmp_path / "data" / "browser-profiles" / "firefox"
    assert profile.is_dir() and len(list(profile.iterdir())) == 1


def test_no_browser_reports_clear_unavailable_state(tmp_path):
    result = BrowserChallengeSolver(repo_root=tmp_path, discover=lambda: []).solve("demo", "https://tracker.test/")
    assert not result["ok"] and "no supported" in result["error"]
