/* DebriPod PWA shell cache. Version tokens are injected by /debripod-sw.js. */
const DP_ASSET_VERSION = "__DEBRIPOD_ASSET_VERSION__";
const DP_ICON_VERSION = "__DEBRIPOD_ICON_VERSION__";
const DP_CACHE = "debripod-shell-" + DP_ASSET_VERSION;
const DP_RUNTIME_CACHE = "debripod-runtime-" + DP_ASSET_VERSION;
const DP_SHELL_ASSETS = __DEBRIPOD_SHELL_ASSETS__;

function sameOrigin(url){
  return url.origin === self.location.origin;
}

function isUnsafeRequest(request, url){
  if(request.method !== "GET") return true;
  if(!sameOrigin(url)) return true;
  const path = url.pathname;
  if(path.startsWith("/api/auth/") || path.startsWith("/api/settings") || path.startsWith("/api/setup") || path.startsWith("/api/services")) return true;
  if(path.startsWith("/api/playback/update") || path.startsWith("/api/lastfm") || path.startsWith("/api/tasks")) return true;
  if(path.startsWith("/stream") || path.startsWith("/hls") || path.startsWith("/download") || path.startsWith("/transcode")) return true;
  if(path.includes("csrf") || path.includes("secret") || path.includes("passkey")) return true;
  return false;
}

function isShellAsset(url){
  if(url.pathname === "/" || url.pathname === "/site.webmanifest") return true;
  if(url.pathname === "/favicon.ico" || url.pathname === "/apple-touch-icon.png" || url.pathname === "/apple-touch-icon-precomposed.png") return true;
  return url.pathname.startsWith("/static/");
}

self.addEventListener("install", (event)=>{
  event.waitUntil(
    caches.open(DP_CACHE)
      .then((cache)=> cache.addAll(DP_SHELL_ASSETS))
      .then(()=> self.skipWaiting())
  );
});

self.addEventListener("activate", (event)=>{
  event.waitUntil(
    caches.keys()
      .then((keys)=> Promise.all(keys.map((key)=>{
        if(key !== DP_CACHE && key !== DP_RUNTIME_CACHE && key.startsWith("debripod-")) return caches.delete(key);
        return Promise.resolve(false);
      })))
      .then(()=> self.clients.claim())
  );
});

self.addEventListener("message", (event)=>{
  const data = event && event.data ? event.data : {};
  if(data && data.type === "SKIP_WAITING"){
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event)=>{
  const request = event.request;
  let url;
  try{ url = new URL(request.url); }catch(e){ return; }
  if(isUnsafeRequest(request, url)) return;

  if(request.mode === "navigate"){
    event.respondWith(
      fetch(request)
        .then((response)=>{
          const copy = response.clone();
          caches.open(DP_CACHE).then((cache)=> cache.put("/", copy)).catch(()=>{});
          return response;
        })
        .catch(()=> caches.match("/") || caches.match("/?pwa=1"))
    );
    return;
  }

  if(isShellAsset(url)){
    event.respondWith(
      caches.match(request)
        .then((cached)=> cached || fetch(request).then((response)=>{
          if(response && response.ok){
            const copy = response.clone();
            caches.open(DP_CACHE).then((cache)=> cache.put(request, copy)).catch(()=>{});
          }
          return response;
        }))
    );
    return;
  }

  if(url.pathname.startsWith("/api/library/") || url.pathname === "/api/client-state" || url.pathname === "/api/sync" || url.pathname === "/api/search_history" || url.pathname === "/api/playback/recent" || url.pathname === "/api/playback/snapshot"){
    event.respondWith(
      fetch(request)
        .then((response)=>{
          if(response && response.ok){
            const copy = response.clone();
            caches.open(DP_RUNTIME_CACHE).then((cache)=> cache.put(request, copy)).catch(()=>{});
          }
          return response;
        })
        .catch(()=> caches.match(request))
    );
  }
});
