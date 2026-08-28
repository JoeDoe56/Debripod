import contextlib
import threading
import shutil
from pathlib import Path

import pytest
from flask import Flask
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from werkzeug.serving import make_server

from debripod.Services.indexers.browsers.discovery import discover_browsers
from debripod.Services.indexers.browsers.solver import BrowserAdapter, BrowserChallengeSolver


class HeadlessAdapter(BrowserAdapter):
    def start(self):
        browser=self.browser
        name={"edge":"msedgedriver","firefox":"geckodriver"}.get(browser.adapter_id,"chromedriver")
        executable=shutil.which(name)
        if not executable:
            matches=sorted((Path.home()/".cache"/"selenium"/name).glob("**/*.exe")); executable=str(matches[-1]) if matches else ""
        if not executable: pytest.fail("Installed browser has no locally available Selenium driver")
        if browser.family == "firefox":
            options=webdriver.FirefoxOptions(); options.binary_location=browser.executable_path; options.add_argument("-headless"); options.profile=str(self.profile_path)
            return webdriver.Firefox(options=options,service=FirefoxService(executable_path=executable))
        if browser.family == "safari": pytest.skip("Safari has no headless mode")
        options_class=webdriver.EdgeOptions if browser.adapter_id=="edge" else webdriver.ChromeOptions
        options=options_class(); options.binary_location=browser.executable_path
        for arg in ("--headless=new","--no-sandbox","--disable-dev-shm-usage",f"--user-data-dir={self.profile_path}","--no-first-run"): options.add_argument(arg)
        return webdriver.Edge(options=options,service=EdgeService(executable_path=executable)) if browser.adapter_id=="edge" else webdriver.Chrome(options=options,service=ChromeService(executable_path=executable))


def test_local_javascript_challenge_integration(tmp_path):
    browsers=discover_browsers()
    if not browsers: pytest.skip("No supported installed browser")
    app=Flask(__name__)
    @app.get("/challenge")
    def challenge():
        return "<html><title>Just a moment...</title><body><div id=challenge-running>Checking your browser</div><script>setTimeout(()=>{document.title='Ready';document.body.innerHTML='<main id=results>Search ready</main>'},150)</script></body></html>",503
    server=make_server("127.0.0.1",0,app); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        solver=BrowserChallengeSolver(repo_root=tmp_path,discover=lambda:[browsers[0]],adapter_factory=lambda browser,profile:HeadlessAdapter(browser,profile),timeout=10,poll_interval=.1)
        result=solver.solve("local",f"http://127.0.0.1:{server.server_port}/challenge")
        assert result["ok"] and result["adapter"]==browsers[0].adapter_id
        assert str(tmp_path/"data"/"browser-profiles") in str((tmp_path/"data"/"browser-profiles").resolve())
    finally:
        server.shutdown(); thread.join(timeout=2)
