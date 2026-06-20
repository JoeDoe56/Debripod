(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const CSRF_TOKEN = String(window.DEBRIPOD_CSRF_TOKEN || "");
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  const memoryCache = new Map();
  const pendingGets = new Map();
  const abortGroups = new Map();
  const recentTimings = [];
  const MEMORY_TTL_MS = 2000;
  const LIVE_PREFIXES = [
    "/api/client-state",
    "/api/library/building",
    "/api/playback/state"
  ];

  if(nativeFetch && !root.__csrfFetchInstalled){
    window.fetch = function(input, init){
      const opts = Object.assign({}, init || {});
      const method = String(opts.method || (input && input.method) || "GET").toUpperCase();
      if(["POST", "PUT", "PATCH", "DELETE"].indexOf(method) >= 0 && CSRF_TOKEN){
        let sameOrigin = true;
        try{
          const u = new URL((typeof input === "string") ? input : input.url, window.location.href);
          sameOrigin = u.origin === window.location.origin;
        }catch(e){}
        if(sameOrigin){
          const headers = new Headers(opts.headers || (input && input.headers) || {});
          if(!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", CSRF_TOKEN);
          opts.headers = headers;
        }
      }
      return nativeFetch(input, opts);
    };
    root.__csrfFetchInstalled = true;
  }

  function normalizeUrl(url){
    try{
      const u = new URL(url, window.location.href);
      return u.pathname + u.search;
    }catch(e){
      return String(url || "");
    }
  }

  function isLiveUrl(url){
    const path = normalizeUrl(url);
    return LIVE_PREFIXES.some((prefix)=> path === prefix || path.indexOf(prefix + "?") === 0 || path.indexOf(prefix + "/") === 0);
  }

  function clonePayload(value){
    if(value == null || typeof value !== "object") return value;
    try{ return JSON.parse(JSON.stringify(value)); }catch(e){ return value; }
  }

  function remember(url, payload){
    try{
      if(payload && (payload.stale === true || payload.building === true)) return;
      memoryCache.set(normalizeUrl(url), {payload: clonePayload(payload), savedAt: Date.now()});
      if(memoryCache.size > 160){
        const keys = Array.from(memoryCache.keys()).slice(0, 40);
        keys.forEach((key)=> memoryCache.delete(key));
      }
    }catch(e){}
  }

  function cachedMemory(url){
    try{
      const rec = memoryCache.get(normalizeUrl(url));
      if(!rec || Date.now() - Number(rec.savedAt || 0) > MEMORY_TTL_MS) return null;
      return clonePayload(rec.payload);
    }catch(e){
      return null;
    }
  }

  function scheduleRevalidate(url, opts, skipMirror){
    try{
      if(isLiveUrl(url)) return;
      const key = normalizeUrl(url);
      if(pendingGets.has(key)) return;
      fetchNetwork(url, Object.assign({}, opts, {background:true}), skipMirror).catch(()=>{});
    }catch(e){}
  }

  async function fetchNetwork(url, options, skipMirror){
    const opts = Object.assign({}, options || {});
    const key = normalizeUrl(url);
    delete opts.skipMirror;
    delete opts.localFirst;
    delete opts.networkOnly;
    delete opts.background;
    const abortKey = opts.abortKey;
    delete opts.abortKey;
    if(abortKey){
      try{
        const prev = abortGroups.get(abortKey);
        if(prev) prev.abort();
        const ctrl = new AbortController();
        abortGroups.set(abortKey, ctrl);
        opts.signal = ctrl.signal;
      }catch(e){}
    }
    if(!opts.cache) opts.cache = isLiveUrl(url) ? "no-store" : "default";
    if(pendingGets.has(key)) return pendingGets.get(key);
    const task = (async ()=>{
      const started = performance && performance.now ? performance.now() : Date.now();
      const r = await fetch(url, opts);
      rememberTiming("GET", url, r.status, started);
      if(!r.ok) throw new Error("HTTP " + r.status);
      const js = await r.json();
      remember(url, js);
      try{
        if(!skipMirror && root.clientSync && root.clientSync.maybeStoreApiGet){
          root.clientSync.maybeStoreApiGet(url, js);
        }
      }catch(e){}
      return js;
    })();
    pendingGets.set(key, task);
    try{
      return await task;
    }finally{
      pendingGets.delete(key);
      if(abortKey && abortGroups.get(abortKey) && opts.signal === abortGroups.get(abortKey).signal){
        abortGroups.delete(abortKey);
      }
    }
  }

  async function apiGet(url, options){
    const opts = Object.assign({}, options || {});
    const skipMirror = !!opts.skipMirror;
    const networkOnly = !!opts.networkOnly || skipMirror || isLiveUrl(url);
    const localFirst = opts.localFirst !== false && !networkOnly;
    try{
      if(localFirst){
        const hot = cachedMemory(url);
        if(hot){
          scheduleRevalidate(url, opts, skipMirror);
          return Object.assign({}, hot, {local:true, stale:true});
        }
        if(root.clientSync && root.clientSync.cachedApiGet){
          const cached = await root.clientSync.cachedApiGet(url);
          if(cached){
            remember(url, cached);
            scheduleRevalidate(url, opts, skipMirror);
            return Object.assign({}, clonePayload(cached), {local:true, stale:true});
          }
        }
      }
      return await fetchNetwork(url, opts, skipMirror);
    }catch(err){
      try{
        if(!skipMirror && root.clientSync && root.clientSync.cachedApiGet){
          const cached = await root.clientSync.cachedApiGet(url);
          if(cached) return Object.assign({}, clonePayload(cached), {stale:true, offline:true});
        }
      }catch(e){}
      throw err;
    }
  }

  async function apiPost(url, payload, options){
    const opts = Object.assign({
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload || {}),
      cache:"no-store"
    }, options || {});
    const started = performance && performance.now ? performance.now() : Date.now();
    const res = await fetch(url, opts);
    rememberTiming("POST", url, res.status, started);
    let j = null;
    try{ j = await res.json(); }catch(e){}
    return {ok: res.ok, status: res.status, json: j};
  }

  function rememberTiming(method, url, status, started){
    try{
      const now = performance && performance.now ? performance.now() : Date.now();
      recentTimings.push({
        method:String(method || "GET"),
        url:normalizeUrl(url),
        status:Number(status || 0),
        ms:Math.max(0, now - Number(started || now)),
        ts:Date.now()
      });
      while(recentTimings.length > 40) recentTimings.shift();
    }catch(e){}
  }

  root.apiClient = {
    apiGet,
    apiPost,
    csrfToken: CSRF_TOKEN,
    abortGroup: function(key){
      try{
        const ctrl = abortGroups.get(String(key || ""));
        if(ctrl) ctrl.abort();
        abortGroups.delete(String(key || ""));
      }catch(e){}
    },
    clearMemoryCache: function(){ memoryCache.clear(); },
    isLiveUrl,
    recentTimings: function(){ return recentTimings.slice(); },
    rememberTiming
  };
})();
