(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const DB_NAME = "debripod-client-mirror";
  const DB_VERSION = 1;
  const SAFE_GET_PREFIXES = [
    "/api/library/config",
    "/api/library/browse",
    "/api/library/metadata",
    "/api/library/manifest",
    "/api/library/analysis",
    "/api/library/palette",
    "/api/client-state",
    "/api/sync",
    "/api/search_history",
    "/api/playback/recent",
    "/api/playback/snapshot"
  ];
  const SEARCH_TTL_MS = 1000 * 60 * 60 * 6;
  let dbPromise = null;
  let started = false;
  let timer = 0;
  let refreshing = false;
  let online = true;
  let scope = "anonymous@" + location.host;
  let stateSummary = null;
  let updateReloading = false;

  function openDb(){
    if(dbPromise) return dbPromise;
    dbPromise = new Promise((resolve)=>{
      if(!("indexedDB" in window)) return resolve(null);
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = ()=>{
        const db = req.result;
        if(!db.objectStoreNames.contains("kv")) db.createObjectStore("kv", {keyPath:"key"});
        if(!db.objectStoreNames.contains("api")) db.createObjectStore("api", {keyPath:"key"});
        if(!db.objectStoreNames.contains("views")) db.createObjectStore("views", {keyPath:"key"});
        if(!db.objectStoreNames.contains("search")) db.createObjectStore("search", {keyPath:"key"});
        if(!db.objectStoreNames.contains("playback")) db.createObjectStore("playback", {keyPath:"key"});
        if(!db.objectStoreNames.contains("artwork")) db.createObjectStore("artwork", {keyPath:"key"});
      };
      req.onsuccess = ()=>resolve(req.result || null);
      req.onerror = ()=>resolve(null);
      req.onblocked = ()=>resolve(null);
    });
    return dbPromise;
  }

  function apiKey(url){
    return scope + "::api::" + normalizeUrl(url);
  }

  function normalizeUrl(url){
    try{
      const u = new URL(url, location.href);
      return u.pathname + u.search;
    }catch(e){
      return String(url || "");
    }
  }

  function isSafeGet(url){
    const path = normalizeUrl(url);
    if(path.indexOf("include_secrets=1") >= 0) return false;
    if(path.indexOf("csrf") >= 0 || path.indexOf("passkey") >= 0 || path.indexOf("secret") >= 0) return false;
    return SAFE_GET_PREFIXES.some(prefix=> path === prefix || path.indexOf(prefix + "?") === 0);
  }

  function isSearchUrl(url){
    const path = normalizeUrl(url);
    return path.indexOf("/api/libsearch/") === 0 || path.indexOf("/api/search_history") === 0;
  }

  async function put(store, value){
    const db = await openDb();
    if(!db || !value || !value.key) return false;
    return new Promise((resolve)=>{
      try{
        const tx = db.transaction(store, "readwrite");
        tx.objectStore(store).put(value);
        tx.oncomplete = ()=>resolve(true);
        tx.onerror = ()=>resolve(false);
      }catch(e){ resolve(false); }
    });
  }

  async function get(store, key){
    const db = await openDb();
    if(!db) return null;
    return new Promise((resolve)=>{
      try{
        const tx = db.transaction(store, "readonly");
        const req = tx.objectStore(store).get(key);
        req.onsuccess = ()=>resolve(req.result || null);
        req.onerror = ()=>resolve(null);
      }catch(e){ resolve(null); }
    });
  }

  async function deleteByPrefix(store, prefix){
    const db = await openDb();
    if(!db) return;
    return new Promise((resolve)=>{
      try{
        const tx = db.transaction(store, "readwrite");
        const os = tx.objectStore(store);
        const req = os.openCursor();
        req.onsuccess = ()=>{
          const cur = req.result;
          if(cur){
            if(String(cur.key || "").indexOf(prefix) === 0) cur.delete();
            cur.continue();
          }
        };
        tx.oncomplete = ()=>resolve();
        tx.onerror = ()=>resolve();
      }catch(e){ resolve(); }
    });
  }

  async function cachedApiGet(url){
    if(!isSafeGet(url)) return null;
    const rec = await get("api", apiKey(url));
    if(!rec) return null;
    if(isSearchUrl(url) && rec.savedAt && Date.now() - rec.savedAt > SEARCH_TTL_MS) return null;
    return rec.payload || null;
  }

  async function maybeStoreApiGet(url, payload){
    if(!isSafeGet(url) || !payload || typeof payload !== "object") return false;
    return put("api", {
      key: apiKey(url),
      scope: scope,
      url: normalizeUrl(url),
      savedAt: Date.now(),
      payload: payload
    });
  }

  function applyScope(summary){
    const user = summary && summary.user ? String(summary.user) : "anonymous";
    const asset = summary && summary.asset_version ? String(summary.asset_version) : String(window.DEBRIPOD_ASSET_VERSION || "");
    const next = user + "@" + location.host + "::" + asset;
    if(next === scope) return;
    const old = scope;
    scope = next;
    get("kv", "active_scope").then((rec)=>{
      const prev = rec && rec.value;
      if(prev && prev !== scope){
        deleteByPrefix("api", prev + "::");
        deleteByPrefix("views", prev + "::");
        deleteByPrefix("search", prev + "::");
        deleteByPrefix("playback", prev + "::");
        deleteByPrefix("artwork", prev + "::");
      }else if(old && old !== scope && old.indexOf("anonymous@") === 0){
        deleteByPrefix("api", old + "::");
      }
      put("kv", {key:"active_scope", value:scope, savedAt:Date.now()});
    }).catch(()=>{});
  }

  function setOnline(next){
    online = !!next;
    try{
      document.documentElement.classList.toggle("serverUnavailable", !online);
    }catch(e){}
    if(!online) showOfflineStateIfEmpty();
  }

  function showOfflineStateIfEmpty(){
    try{
      if(!state || (state.items && state.items.length)) return;
      state.items = [{
        kind:"info",
        label:"DebriPod UI is cached on this device, but the local DebriPod server is not reachable."
      }];
      state.sel = 0;
      if(typeof renderList === "function") renderList();
    }catch(e){}
  }

  function activeRootId(){
    try{ return state && state.current && state.current.root ? String(state.current.root.id || "") : ""; }
    catch(e){ return ""; }
  }

  function currentViewKey(){
    try{
      const cur = state.current || {};
      const rootId = cur.root && cur.root.id ? String(cur.root.id) : "";
      return scope + "::view::" + [cur.kind || "", rootId, cur.rel || "", cur.level || "", cur.value || "", cur.playlistRel || ""].join("|");
    }catch(e){
      return scope + "::view::unknown";
    }
  }

  async function saveCurrentViewState(){
    try{
      if(!state || !state.current) return;
      await put("views", {
        key: currentViewKey(),
        scope: scope,
        savedAt: Date.now(),
        current: {
          kind: state.current.kind || "",
          label: state.current.label || "",
          rootId: state.current.root && state.current.root.id ? String(state.current.root.id) : "",
          rel: state.current.rel || "",
          level: state.current.level || "",
          value: state.current.value || "",
          playlistRel: state.current.playlistRel || ""
        },
        sel: Number(state.sel || 0),
        scrollTop: libList ? Number(libList.scrollTop || 0) : 0,
        items: Array.isArray(state.items) ? state.items.slice(0, 1000) : []
      });
    }catch(e){}
  }

  async function restoreCurrentViewState(){
    try{
      const rec = await get("views", currentViewKey());
      if(!rec || !Array.isArray(rec.items) || !rec.items.length) return false;
      state.items = rec.items;
      state.sel = Math.max(0, Math.min(rec.items.length - 1, Number(rec.sel || 0)));
      if(typeof renderList === "function") renderList();
      if(libList) libList.scrollTop = Number(rec.scrollTop || 0);
      return true;
    }catch(e){
      return false;
    }
  }

  async function refreshActiveRootView(rootId){
    if(refreshing || !rootId) return;
    let current = null;
    try{ current = state && state.current; }catch(e){ current = null; }
    if(!current || !current.root || String(current.root.id || "") !== rootId || typeof current.load !== "function") return;
    refreshing = true;
    const scrollTop = libList ? libList.scrollTop : 0;
    try{
      await current.load();
      if(libList) libList.scrollTop = scrollTop;
      if(typeof setHeader === "function") setHeader();
      await saveCurrentViewState();
    }catch(e){
      await restoreCurrentViewState();
    }finally{
      refreshing = false;
    }
  }

  async function syncFromServer(summary){
    try{
      const since = {
        library_versions: (summary && summary.library_versions) || {},
        search_history_version: summary && summary.search_history_version,
        playback_version: summary && summary.playback_version,
        settings_version: summary && summary.settings_version
      };
      const js = await apiGet("/api/sync?since=" + encodeURIComponent(JSON.stringify(since)), {skipMirror:true});
      if(!js || !js.ok) return;
      await put("kv", {key:scope + "::sync", value:js, savedAt:Date.now()});
      if(Array.isArray(js.roots)) await put("kv", {key:scope + "::roots", value:js.roots, savedAt:Date.now()});
      if(Array.isArray(js.search_history)) await put("search", {key:scope + "::history", value:js.search_history, savedAt:Date.now()});
      if(js.playback) await put("playback", {key:scope + "::recent", value:js.playback, savedAt:Date.now()});
    }catch(e){}
  }

  function serverHasNewerShell(summary){
    try{
      const serverAsset = String(summary && summary.asset_version || "");
      const localAsset = String(window.DEBRIPOD_ASSET_VERSION || "");
      if(serverAsset && localAsset && serverAsset !== localAsset) return true;
      const serverApp = String(summary && summary.app_version || "");
      const localApp = String(window.DEBRIPOD_APP_INFO && (window.DEBRIPOD_APP_INFO.display_version || window.DEBRIPOD_APP_INFO.version) || "");
      return !!(serverApp && localApp && serverApp !== localApp);
    }catch(e){
      return false;
    }
  }

  async function reloadForNewShell(summary){
    if(updateReloading) return;
    updateReloading = true;
    try{
      await put("kv", {key:"pending_shell_update", value:{server:summary || {}, localAsset:String(window.DEBRIPOD_ASSET_VERSION || "")}, savedAt:Date.now()});
    }catch(e){}
    try{
      if(navigator.serviceWorker && navigator.serviceWorker.getRegistration){
        const reg = await navigator.serviceWorker.getRegistration("/");
        if(reg){
          try{ await reg.update(); }catch(e){}
          if(reg.waiting) reg.waiting.postMessage({type:"SKIP_WAITING"});
        }
      }
    }catch(e){}
    try{
      if(window.caches && caches.keys){
        const keys = await caches.keys();
        await Promise.all(keys.filter(k=> /^debripod-/.test(k)).map(k=> caches.delete(k)));
      }
    }catch(e){}
    setTimeout(()=>{ try{ location.reload(); }catch(e){} }, 300);
  }

  async function tick(){
    timer = 0;
    let js = null;
    try{
      js = await apiGet("/api/client-state", {skipMirror:true});
      setOnline(true);
    }catch(e){
      setOnline(false);
      js = await cachedApiGet("/api/client-state");
    }
    if(js && js.ok){
      if(serverHasNewerShell(js)){
        await reloadForNewShell(js);
        return;
      }
      applyScope(js);
      const prev = stateSummary || {};
      stateSummary = js;
      await put("kv", {key:scope + "::client-state", value:js, savedAt:Date.now()});
      const prevVersions = prev.library_versions || {};
      const nextVersions = js.library_versions || {};
      const changed = [];
      Object.keys(nextVersions).forEach((rootId)=>{
        if(prevVersions[rootId] != null && Number(prevVersions[rootId] || 0) !== Number(nextVersions[rootId] || 0)){
          changed.push(rootId);
        }
      });
      await syncFromServer(js);
      const active = activeRootId();
      if(active && changed.indexOf(active) >= 0){
        await refreshActiveRootView(active);
      }
    }
    await saveCurrentViewState();
    schedule();
  }

  function schedule(){
    if(timer || !started) return;
    timer = setTimeout(tick, document.hidden ? 30000 : 6000);
  }

  function registerServiceWorker(){
    try{
      if(!("serviceWorker" in navigator)) return;
      navigator.serviceWorker.register("/debripod-sw.js", {scope:"/"}).catch(()=>{});
    }catch(e){}
  }

  async function start(){
    if(started) return;
    started = true;
    await openDb();
    registerServiceWorker();
    await restoreCurrentViewState();
    timer = setTimeout(tick, 250);
  }

  try{
    document.addEventListener("visibilitychange", ()=>{
      if(!document.hidden && started){
        if(timer) clearTimeout(timer);
        timer = setTimeout(tick, 250);
      }
    });
    window.addEventListener("beforeunload", ()=>{ saveCurrentViewState(); });
  }catch(e){}

  root.clientSync = {
    start,
    cachedApiGet,
    maybeStoreApiGet,
    restoreCurrentViewState,
    saveCurrentViewState,
    isSafeGet,
    getStateSummary: function(){ return stateSummary; }
  };
  start();
})();
