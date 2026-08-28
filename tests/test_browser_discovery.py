from debripod.Services.indexers.browsers.discovery import discover_browsers


def test_windows_default_browser_is_first_and_supported_fallbacks_follow():
    existing = {
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    }
    browsers = discover_browsers(
        system="windows", default_resolver=lambda system: "chrome", which=lambda name: None,
        exists=lambda path: path.replace("/", "\\") in existing,
        environ={"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"},
    )
    assert [browser.adapter_id for browser in browsers] == ["chrome", "edge", "firefox"]
    assert browsers[0].is_default and browsers[0].family == "chromium"


def test_linux_uses_default_then_documented_order():
    paths = {"google-chrome": "/bin/chrome", "firefox": "/bin/firefox"}
    browsers = discover_browsers(system="linux", default_resolver=lambda system: "firefox", which=paths.get, exists=lambda path: False)
    assert [browser.adapter_id for browser in browsers] == ["firefox", "chrome"]
