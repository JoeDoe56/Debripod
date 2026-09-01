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

function isAuthNavigation(url){
  const path = url.pathname;
  return path === "/login" || path === "/logout" || path === "/setup" || path.indexOf("/account/") === 0;
}

function responseLooksLikeAppShell(response){
  try{
    if(!response || !response.ok || response.redirected) return false;
    const u = new URL(response.url || self.location.href);
    if(u.origin !== self.location.origin) return false;
    if(u.pathname === "/login" || u.pathname === "/setup" || u.pathname === "/logout") return false;
    return true;
  }catch(e){
    return false;
  }
}

function isShellAsset(url){
  if(url.pathname === "/" || url.pathname === "/site.webmanifest") return true;
  if(url.pathname === "/favicon.ico" || url.pathname === "/apple-touch-icon.png") return true;
  if(url.pathname === "/icon-192.png" || url.pathname === "/icon-512.png") return true;
  return url.pathname.startsWith("/static/");
}

function matchShellAsset(request){
  // Asset query strings contain the build version. Ignoring that query can
  // return CSS or JavaScript from an older shell and mix incompatible layers.
  return caches.match(request);
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
    if(isAuthNavigation(url)) return;
    if(url.pathname === "/"){
      event.respondWith(
        fetch(request)
          .then((response)=>{
            if(responseLooksLikeAppShell(response)){
              const copy = response.clone();
              caches.open(DP_CACHE).then((cache)=> cache.put("/", copy)).catch(()=>{});
            }
            return response;
          })
          .catch(()=> caches.match("/") || caches.match("/?pwa=1"))
      );
      return;
    }
    event.respondWith(
      caches.match("/")
        .then((cached)=>{
          const refresh = fetch(request)
            .then((response)=>{
              if(responseLooksLikeAppShell(response)){
                const copy = response.clone();
                caches.open(DP_CACHE).then((cache)=> cache.put("/", copy)).catch(()=>{});
              }
              return response;
            })
            .catch(()=> null);
          if(cached) return cached;
          return refresh.then((response)=> response || caches.match("/?pwa=1"));
        })
    );
    return;
  }

  if(isShellAsset(url)){
    event.respondWith(
      matchShellAsset(request)
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

  if(url.pathname.startsWith("/api/")) return;
});

self.addEventListener("push", (event)=>{
  let payload = null;
  try{ payload = event.data ? event.data.json() : null; }catch(_error){ payload = null; }
  if(!payload || typeof payload !== "object" || !payload.title || !payload.data || !payload.data.task_id) return;
  event.waitUntil(self.registration.showNotification(String(payload.title), {
    body:String(payload.body || "Task complete"),
    data:{task_id:String(payload.data.task_id), url:String(payload.data.url || ("/?task=" + payload.data.task_id))}
  }));
});

self.addEventListener("notificationclick", (event)=>{
  event.notification.close();
  const destination = String(event.notification.data && event.notification.data.url || "/");
  event.waitUntil(self.clients.matchAll({type:"window", includeUncontrolled:true}).then(clients=>{
    const matching = clients.find(client=>{
      try{ return new URL(client.url).origin === self.location.origin; }catch(_error){ return false; }
    });
    if(matching){
      return matching.navigate(destination).then(client=>client && client.focus());
    }
    return self.clients.openWindow(destination).then(client=>client && client.focus());
  }));
});
