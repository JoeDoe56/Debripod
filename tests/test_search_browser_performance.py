import contextlib
import http.server
import json
import socketserver
import shutil
import threading
import time
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait

from debripod.Services.indexers.browsers.discovery import discover_browsers


REPO = Path(__file__).resolve().parents[1]
JS_ROOT = REPO / "debripod" / "static" / "js"


PAGE = b"""<!doctype html><meta charset=utf-8>
<style>html,body{margin:0}#libList{display:block;height:600px;overflow:auto;margin:0;padding:0}.ipodItem{box-sizing:border-box;display:flex;height:76px;min-height:76px;overflow:hidden}.ipodVirtualSpacer{display:block}.ipodListEndSpacer{display:block;height:1px}</style>
<ul id=libList></ul>
<script>
window.__errors=[]; addEventListener('error',e=>__errors.push(String(e.error||e.message))); addEventListener('unhandledrejection',e=>__errors.push(String(e.reason)));
window.DebriPod={}; window.libList=document.getElementById('libList');
window.state={items:[],itemsVersion:0,rowHeightRevision:0,sel:0,current:{kind:'libsearch',label:'Search'},libSearch:null};
window.escapeHtml=s=>String(s); window.selectItem=()=>Promise.resolve(); window.showNowPlaying=()=>{}; window.setHeader=()=>{};
</script>
<script src=/js/search-results-worker.js></script><script>window.Worker=undefined;</script>
<script src=/js/search-results-model.js></script><script src=/js/list-view.js></script>
<script>
const rows=[];
for(let i=0;i<30000;i++){const torrent=(i%2)===1; rows.push({result_id:'result-'+i,provider_group:torrent?'torrents':'library',source:torrent?'torrent':'library',source_label:torrent?'Torrent':'Library',kind:torrent?'torrent':'song',kind_label:torrent?'Torrent':'Songs',title:'Synthetic result '+i,subtitle:'Row '+i,artist:'',album:'',year:'',duration:0,thumbnail:'',canonical_url:'',stable_source_id:String(i),search_blob:'synthetic result '+i,filter_values:{sources:[torrent?'Torrent':'Library'],types:[torrent?'Torrent':'Songs'],indexers:torrent?['Synthetic']:[],media:[torrent?'video':'music']},match_confidence:1,rank_score:30000-i,browse_available:false,stream_available:false,download_available:false,files_loaded:false,file_count:0,size:0,files:[],provider_data:{indexer_labels:torrent?['Synthetic']:[]}})}
state.libSearch=DebriPod.createSearchResultsState();
window.model=new DebriPod.SearchResultsModel(state.libSearch,{disableWorker:true,onChange:function(){state.items=model.resultRows();state.itemsVersion++;renderList();}});
model.ingestFinal({event:'done',results:rows,provider_status:[]});
window.applyTorrentFilter=()=>model.applyFilters('source:torrent indexer:Synthetic');
window.clearSearchFilter=()=>model.clearFilters();
window.goToFinal=()=>{state.sel=29999;libList.scrollTop=30000*76;libList.dispatchEvent(new Event('scroll'));};
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            data, content_type = PAGE, "text/html"
        elif self.path.startswith("/js/"):
            path = JS_ROOT / self.path.removeprefix("/js/").split("?", 1)[0]
            if not path.is_file():
                self.send_error(404); return
            data, content_type = path.read_bytes(), "text/javascript"
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *_args):
        pass


def _driver_executable(browser):
    names={"edge":"msedgedriver","firefox":"geckodriver"}
    name=names.get(browser.adapter_id,"chromedriver")
    direct=shutil.which(name)
    if direct: return direct
    matches=sorted((Path.home()/".cache"/"selenium"/name).glob("**/*.exe"))
    return str(matches[-1]) if matches else ""


def _driver(browser, profile):
    executable=_driver_executable(browser)
    if not executable: pytest.fail("Installed browser has no locally available Selenium driver")
    if browser.family == "firefox":
        options = webdriver.FirefoxOptions(); options.binary_location = browser.executable_path; options.add_argument("-headless"); options.profile = str(profile)
        return webdriver.Firefox(options=options,service=FirefoxService(executable_path=executable))
    if browser.family == "safari":
        pytest.skip("Safari headless mode is unavailable")
    options_class = webdriver.EdgeOptions if browser.adapter_id == "edge" else webdriver.ChromeOptions
    options = options_class(); options.binary_location = browser.executable_path
    for arg in ("--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}"):
        options.add_argument(arg)
    return webdriver.Edge(options=options,service=EdgeService(executable_path=executable)) if browser.adapter_id == "edge" else webdriver.Chrome(options=options,service=ChromeService(executable_path=executable))


def test_production_virtual_list_holds_30000_and_renders_under_140(tmp_path):
    browsers = discover_browsers()
    if not browsers:
        pytest.skip("No supported installed browser")
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    driver = None
    try:
        driver = _driver(browsers[0], tmp_path / "profile")
        driver.set_window_size(1000, 760)
        started = time.perf_counter(); driver.get(f"http://127.0.0.1:{server.server_address[1]}/")
        wait = WebDriverWait(driver, 15)
        wait.until(lambda d: d.execute_script("return window.model && state.libSearch.allResults.length===30000"))
        assert time.perf_counter() - started < 15
        assert driver.execute_script("return state.libSearch.allResults.length") == 30000
        assert driver.execute_script("return document.querySelectorAll('.ipodItem').length") < 140
        driver.execute_script("applyTorrentFilter()")
        wait.until(lambda d: d.execute_script("return state.libSearch.visibleIds.length===15000"))
        driver.execute_script("clearSearchFilter()")
        wait.until(lambda d: d.execute_script("return state.libSearch.visibleIds.length===30000"))
        driver.execute_script("goToFinal()")
        wait.until(lambda d: d.execute_script("return !!document.querySelector('[data-index=\"29999\"]')"))
        assert driver.execute_script("return state.items[29999].result_id") == "result-29999"
        assert driver.execute_script("return window.__errors") == []
    finally:
        if driver is not None:
            with contextlib.suppress(Exception): driver.quit()
        server.shutdown(); server.server_close(); thread.join(timeout=2)
