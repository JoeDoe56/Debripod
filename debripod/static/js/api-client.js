(function(){
  const root = window.DebriPod = window.DebriPod || {};
  const CSRF_TOKEN = String(window.DEBRIPOD_CSRF_TOKEN || "");
  const nativeFetch = window.fetch ? window.fetch.bind(window) : null;

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

  async function apiGet(url, options){
    const opts = Object.assign({cache:"no-store"}, options || {});
    const r = await fetch(url, opts);
    if(!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  }

  async function apiPost(url, payload, options){
    const opts = Object.assign({
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload || {}),
      cache:"no-store"
    }, options || {});
    const res = await fetch(url, opts);
    let j = null;
    try{ j = await res.json(); }catch(e){}
    return {ok: res.ok, status: res.status, json: j};
  }

  root.apiClient = {
    apiGet,
    apiPost,
    csrfToken: CSRF_TOKEN
  };
})();
