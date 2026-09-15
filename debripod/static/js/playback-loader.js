  var audioMain = document.getElementById("audioMain");
  var npBufferedFill = document.getElementById("npBufferedFill");
  var activeAudio = audioMain;
  var standbyAudio = null;
  var activeAudioHls = null;
  var activeVideoHls = null;
  var preloadAudioHls = null;
var preloadAudioEl = null;
var preloadRequestNonce = 0;
var gaplessBufferCache = new Map();
var gaplessUiTimer = null;
var gaplessLoadNonce = 0;

function playbackText(value){
  return value == null ? "" : String(value).trim();
}

function playbackArtworkValue(value){
  if(value && typeof value === "object"){
    return playbackText(value.url || value.src || value.href);
  }
  return playbackText(value);
}

function playbackMetadataSource(raw){
  if(!raw || typeof raw !== "object") return {};
  // filemeta is intentionally a flat response. Keep these tolerant fallbacks
  // for cached sessions created by older clients without changing that API.
  if(raw.metadata && typeof raw.metadata === "object") return raw.metadata;
  if(raw.result && typeof raw.result === "object") return raw.result;
  if(raw.data && typeof raw.data === "object" && !Array.isArray(raw.data)) return raw.data;
  return raw;
}

function normalizePlaybackMetadata(raw, item, fallbackLabel){
  const source = playbackMetadataSource(raw);
  const entry = item && typeof item === "object" ? item : {};
  const rel = playbackText(entry.rel);
  const fileLabel = rel ? rel.split("/").pop() : "";
  const label = playbackText(source.label || entry.label || fallbackLabel || fileLabel || "Track");
  const title = playbackText(source.title || entry.title || label);
  const tech = playbackText(source.tech || source.quality || entry.tech || entry.quality || entry.ext);
  const rawDuration = source.duration != null ? source.duration : entry.duration;
  const durationNumber = Number(rawDuration);
  return Object.assign({}, source, {
    label: label,
    title: title,
    artist: playbackText(source.artist || entry.artist),
    album: playbackText(source.album || entry.album),
    genre: playbackText(source.genre || entry.genre),
    duration: Number.isFinite(durationNumber) ? durationNumber : null,
    tech: tech,
    art: [source.art, entry.art, entry.thumbnail, entry.poster]
      .map(playbackArtworkValue)
      .find((value)=>!!value) || "",
    streamed: !!(source.streamed != null ? source.streamed : entry.streamed),
    source: playbackText(source.source || entry.source),
    ext: playbackText(source.ext || entry.ext),
    quality: playbackText(source.quality || entry.quality || tech)
  });
}

function playbackArtworkUrl(value){
  const src = playbackText(value);
  if(!src) return "";
  try{ return new URL(src, window.location.href).href; }catch(e){ return src; }
}

try{
  window.DebriPod = window.DebriPod || {};
  window.DebriPod.playbackMetadata = {
    normalize: normalizePlaybackMetadata,
    artworkUrl: playbackArtworkUrl
  };
}catch(e){}

// ===== volume (wheel controlled; device-local software gain) =====
function volumePreferenceStorageKey(){
  try{
    var userId = String(window.DEBRIPOD_DEVICE_SETTINGS_USER_ID || "").trim();
    if(userId) return "debripod_volume:v3:" + userId;
  }catch(e){}
  return "debripod_volume";
}

var userVol = 1.0;
try{
  var volumeStorageKey = volumePreferenceStorageKey();
  var savedVolume = localStorage.getItem(volumeStorageKey);
  if(savedVolume == null && volumeStorageKey !== "debripod_volume"){
    savedVolume = localStorage.getItem("debripod_volume");
    if(savedVolume != null) localStorage.setItem(volumeStorageKey, savedVolume);
  }
  var v = parseFloat(savedVolume || "");
  if(!isNaN(v)) userVol = Math.max(0, Math.min(1, v));
}catch(e){}

function mediaAudioGraph(){
  try{ return window.DebriPod && window.DebriPod.mediaAudioGraph; }catch(e){ return null; }
}

function activePlaybackMediaElement(){
  try{
    if(typeof isVideoActive === "function" && isVideoActive() && npVideo) return npVideo;
  }catch(e){}
  return activeAudio || null;
}

function preparePlaybackMediaAudio(element){
  var graph = mediaAudioGraph();
  try{
    if(graph && graph.setActiveElement) return graph.setActiveElement(element);
  }catch(e){}
  return false;
}

function unlockPlaybackMediaAudio(){
  var graph = mediaAudioGraph();
  try{
    if(graph && graph.unlock){
      var pending = graph.unlock();
      if(pending && pending.catch) pending.catch(()=>{});
    }
  }catch(e){}
  try{
    const gapless = gaplessAudioApi();
    if(gapless && gapless.resumeContext){ const pending = gapless.resumeContext(); if(pending && pending.catch) pending.catch(()=>{}); }
  }catch(e){}
}

function destroyHlsController(which){
  try{
    if(which === "audio" && activeAudioHls){
      try{ activeAudioHls.destroy(); }catch(e){}
      activeAudioHls = null;
    }
    if(which === "video" && activeVideoHls){
      try{ activeVideoHls.destroy(); }catch(e){}
      activeVideoHls = null;
    }
    if(which === "preload" && preloadAudioHls){
      try{ preloadAudioHls.destroy(); }catch(e){}
      preloadAudioHls = null;
    }
  }catch(e){}
}

function clearBufferedBar(){
  try{ if(npBufferedFill) npBufferedFill.style.width = "0%"; }catch(e){}
}

function updateBufferedBarFor(el){
  try{
    if(!npBufferedFill || !el) return;
    const d = Number(el.duration || 0);
    if(!(d > 0) || !el.buffered || !el.buffered.length){
      npBufferedFill.style.width = "0%";
      return;
    }
    const t = Number(el.currentTime || 0);
    let end = 0;
    for(let i=0;i<el.buffered.length;i++){
      const s = Number(el.buffered.start(i) || 0);
      const e = Number(el.buffered.end(i) || 0);
      if(t >= s - 0.25 && t <= e + 0.25) end = Math.max(end, e);
    }
    if(!(end > 0)){
      end = Number(el.buffered.end(el.buffered.length - 1) || 0);
    }
    npBufferedFill.style.width = Math.max(0, Math.min(100, (end / d) * 100)).toFixed(2) + "%";
  }catch(e){}
}

function applyVolume(){
  var v = userVol;
  var graph = mediaAudioGraph();
  var target = activePlaybackMediaElement();
  try{
    if(graph && graph.setVolume) graph.setVolume(v);
    if(target) preparePlaybackMediaAudio(target);
  }catch(e){}
  if(!graph){
    try{ if(activeAudio){ activeAudio.muted = false; activeAudio.volume = v; } }catch(e){}
    try{ if(npVideo){ npVideo.muted = false; npVideo.volume = v; } }catch(e){}
  }
  try{ if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; } }catch(e){}
  try{
    if(npVolumeFill){
      npVolumeFill.style.width = Math.round(v * 100) + "%";
    }
  }catch(e){}
  try{ if(typeof renderInfoPillLabels === "function") renderInfoPillLabels(); }catch(e){}
}

function resetGaplessPrime(){
  try{
    preloadRequestNonce++;
    destroyHlsController("preload");
    if(preloadAudioEl){
      try{ preloadAudioEl.pause(); }catch(e){}
      try{ preloadAudioEl.removeAttribute("src"); preloadAudioEl.load(); }catch(e){}
      preloadAudioEl = null;
    }
  }catch(e){}
}

function enforceSingleAudio(){
  try{
    preparePlaybackMediaAudio(activePlaybackMediaElement());
    if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; }
  }catch(e){}
}

function gaplessAudioApi(){
  try{ return window.DebriPod && window.DebriPod.gaplessAudio; }catch(e){ return null; }
}

function gaplessItemKey(item){
  const api = gaplessAudioApi();
  try{ return api && api.testing && api.testing.keyFor ? api.testing.keyFor(item) : String(item && item.root && item.root.id || "") + "\u0000" + String(item && item.rel || ""); }catch(e){ return ""; }
}

async function gaplessDecodeItem(item){
  const api = gaplessAudioApi();
  if(!api || !api.supported()) throw new Error("gapless audio unavailable");
  const key = gaplessItemKey(item);
  if(gaplessBufferCache.has(key)) return gaplessBufferCache.get(key).promise;
  const controller = new AbortController();
  const entry = {controller, promise:null};
  entry.promise = Promise.resolve(api.decode(item,controller.signal)).then(buffer=>{entry.buffer=buffer;return buffer;}).catch(error=>{if(gaplessBufferCache.get(key)===entry)gaplessBufferCache.delete(key);throw error;});
  gaplessBufferCache.set(key,entry);
  return entry.promise;
}

function retainGaplessBuffers(items){
  const keep=new Set(items.filter(Boolean).map(gaplessItemKey));
  for(const [key,entry] of gaplessBufferCache){if(!keep.has(key)){entry.controller.abort();gaplessBufferCache.delete(key);}}
}

function stopGaplessPlayback(){
  gaplessLoadNonce++;
  const api=gaplessAudioApi();
  if(api)api.stop();
  if(activeAudio && activeAudio.__gapless)activeAudio=audioMain;
  stopGaplessUiTimer();retainGaplessBuffers([]);
}

function gaplessNextItem(){
  const queue=window.DebriPod && DebriPod.playbackQueue;
  if(queue && queue.orderedEntries){
    const entries=queue.orderedEntries();const pos=entries.findIndex(entry=>entry.canonicalIndex===queue.state.index);
    const next=entries[pos+1];
    if(pos<0 || !next)return null;
    const item=next.item;
    return Object.assign({},item,{root:item.root || {id:item.root_id},rel:item.rel});
  }
  const index=nextIndexPeek();return index==null?null:state.playlist[index];
}

function gaplessPlaybackSnapshot(){
  const api = gaplessAudioApi();
  try{ return api && api.snapshot ? api.snapshot() : null; }catch(e){ return null; }
}

function stopGaplessUiTimer(){
  if(gaplessUiTimer != null){ try{ clearInterval(gaplessUiTimer); }catch(e){} gaplessUiTimer = null; }
}

function updateGaplessUi(){
  const snap = gaplessPlaybackSnapshot();
  if(!snap) return;
  const d = Number(snap.duration || 0), t = Number(snap.position || 0);
  if(d > 0 && npSeek && !npSeekDragging && !seekMode){
    npSeek.value = String(Math.max(0, Math.min(1000, Math.round((t / d) * 1000))));
    try{ updateProgressMeterFill((t / d) * 100); }catch(e){}
  }
  try{ if(activeAudio && activeAudio.__gapless)activeAudio.tick(); }catch(e){}
  try{ renderInfoPillLabels(); }catch(e){}
  try{ syncMediaSessionPosition(); }catch(e){}
  try{ syncMediaSessionControls(); }catch(e){}
}

function startGaplessUiTimer(){
  stopGaplessUiTimer();
  gaplessUiTimer = setInterval(updateGaplessUi, 50);
}

function gaplessPlaybackActive(){ return !!gaplessPlaybackSnapshot(); }

async function startGaplessAudioFromItem(item, playlist, index, forceShow, resumeTime, origin){
  const api=gaplessAudioApi();
  if(!api || !state.preloadEnabled)return false;
  const nonce=++gaplessLoadNonce;
  const pl=Array.isArray(playlist)?playlist:state.playlist || [];
  const idx=typeof index === "number"?index:0;
  const next=gaplessNextItem();
  const nav=(origin && origin.playbackNav) || currentPlaybackNavContext();
  const sourceView=(origin && origin.sourceView) || (state.playbackSession && state.playbackSession.sourceView);
  const metaPromise=apiGet("/api/library/filemeta?root_id="+encodeURIComponent(item.root.id)+"&rel="+encodeURIComponent(item.rel))
    .then(raw=>normalizePlaybackMetadata(raw,item,item.label)).catch(()=>normalizePlaybackMetadata({},item,item.label));
  try{
    const prestarted=api.takePrestarted(item);
    if(!prestarted){
      retainGaplessBuffers([item,next]);
      const bufferPromise=gaplessDecodeItem(item);
      const nextPromise=next && next.media!=="video"?gaplessDecodeItem(next).catch(()=>null):Promise.resolve(null);
      const buffer=await bufferPromise;
      // A prepared skip must never wait for the following track to decode.
      const nextBuffer=api.snapshot()?.playing ? (next && gaplessBufferCache.get(gaplessItemKey(next))?.buffer || null) : await nextPromise;
      if(nonce!==gaplessLoadNonce)return true;
      if(!state.preloadEnabled)return false;
      if(!await api.resumeContext())throw new Error("Audio output is suspended");
      if(nonce!==gaplessLoadNonce)return true;
      try{window.DebriPod.playbackTransport?.cancel(api.media);}catch(e){}
      api.media.playbackRate=1;api.media.setTransportLevel(1);
      if(activeAudio && !activeAudio.__gapless){activeAudio.pause();activeAudio.removeAttribute("src");activeAudio.load();}
      activeAudio=api.media;
      if(!activeAudio._dpWired){wireAudio(activeAudio);activeAudio._dpWired=true;}
      preparePlaybackMediaAudio(activeAudio);applyVolume();
      if(!api.start(item,buffer,next,nextBuffer,{offset:Number(resumeTime)||0,gap:state.gaplessEnabled?0:0.12,
        onBoundary:(boundaryItem,finished)=>{
          try{lastfmMaybeScrobble(true);if(finished)playbackMaybePost("audio",finished.item.root.id,finished.item.rel,state.nowMeta || {},finished.duration,finished.duration,false,"ended");}catch(e){}
          const queue=window.DebriPod && DebriPod.playbackQueue;
          if(queue){const canonical=queue.state.items.find(entry=>(entry.root_id || entry.root?.id)===boundaryItem.root.id && entry.rel===boundaryItem.rel);if(canonical)queue.setCurrent(canonical.queue_id);}
          const items=queue?queue.state.items.map(entry=>Object.assign({},entry,{root:entry.root || {id:entry.root_id}})):state.playlist;
          const bi=items.findIndex(entry=>gaplessItemKey(entry)===gaplessItemKey(boundaryItem));
          startGaplessAudioFromItem(boundaryItem,items,bi,false,0,{playbackNav:state.nowNavContext,sourceView}).catch(error=>warnMedia("audio",String(error),activeAudio));
        },onEnded:()=>{lastfmMaybeScrobble(true);playbackMaybePost("audio",state.now.rootId,state.now.rel,state.nowMeta || {},activeAudio.duration,activeAudio.duration,false,"ended");playNext();}
      }))throw new Error("Audio source could not start");
    }else if(!api.snapshot().playing){await api.media.play();}
    if(nonce!==gaplessLoadNonce)return true;
    const meta=await metaPromise;
    if(nonce!==gaplessLoadNonce)return true;
    state.now={rootId:item.root.id,rel:item.rel,media:"audio",streamed:!!item.streamed,nav};
    state.nowMeta=meta;state.nowNavContext=nav;state.playlist=pl;state.playIndex=idx;
    buildPlaybackSessionUpdate({now:Object.assign({},state.now,{meta}),queue:pl,queueIndex:idx,nav,sourceView,media:"audio"},"playback-start");
    if(forceShow)openNowPlayingExplicit();
    try{loadVisualizerAnalysisForTrack(item.root.id,item.rel,"audio",{streamed:!!item.streamed});finishVisualizerTrackTransition(meta.art || "");}catch(e){}
    await updateNowPlayingDisplay(meta,item.label || "Track",{animateArt:true});
    updateMediaSession(meta);syncMediaSessionControls();lastfmOnTrack(meta);
    playbackMaybePost("audio",item.root.id,item.rel,meta,activeAudio.currentTime,activeAudio.duration,!activeAudio.paused,"start");
    startGaplessUiTimer();updateGaplessUi();preloadNextAudio();
    return true;
  }catch(error){
    if(nonce!==gaplessLoadNonce)return true;
    stopGaplessPlayback();return false;
  }
}

function hlsManifestUrl(rootId, rel){
  return "/hls/manifest?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel);
}

function httpStreamUrl(rootId, rel){
  return "/stream/" + encodeURIComponent(rootId) + "/" + encodeRel(rel || "");
}

function playbackUsesHls(){
  try{ return String(state.playbackStreamingMode || "http").toLowerCase() === "hls"; }catch(e){ return false; }
}

function playbackSourceUrl(rootId, rel){
  return playbackUsesHls() ? hlsManifestUrl(rootId, rel) : httpStreamUrl(rootId, rel);
}

function mediaErrorText(el){
  try{
    const err = el && el.error;
    if(!err) return "";
    const names = {1:"MEDIA_ERR_ABORTED", 2:"MEDIA_ERR_NETWORK", 3:"MEDIA_ERR_DECODE", 4:"MEDIA_ERR_SRC_NOT_SUPPORTED"};
    return (names[err.code] || ("MEDIA_ERR_" + err.code)) + (err.message ? (": " + err.message) : "");
  }catch(e){ return ""; }
}

var uiLogThrottle = new Map();

function uiDebugEnabled(){
  try{
    if(window.DEBRIPOD_UI_DEBUG === true) return true;
    return (localStorage.getItem("debripod_ui_debug") || "") === "1";
  }catch(e){ return false; }
}

function warnMedia(kind, message, el){
  try{
    if(kind === "preload" && !uiDebugEnabled()) return;
    const src = el && el.currentSrc ? el.currentSrc : (el && el.src ? el.src : "");
    const err = mediaErrorText(el);
    const key = [kind || "", message || "", src || "", err || ""].join("|");
    const now = Date.now();
    const last = uiLogThrottle.get(key) || 0;
    if(now - last < 8000) return;
    uiLogThrottle.set(key, now);
    console.warn("[DebriPod media] " + kind + " " + message, {src: src, error: err, readyState: el ? el.readyState : null, networkState: el ? el.networkState : null});
  }catch(e){}
}

function waitForMediaReady(el, timeoutMs){
  return new Promise((resolve, reject)=>{
    if(!el) return reject(new Error("media element missing"));
    if(el.readyState >= 1) return resolve(true);
    let done = false;
    let timer = null;
    const cleanup = ()=>{
      try{ el.removeEventListener("loadedmetadata", onReady); }catch(e){}
      try{ el.removeEventListener("canplay", onReady); }catch(e){}
      try{ el.removeEventListener("error", onError); }catch(e){}
      try{ if(timer) clearTimeout(timer); }catch(e){}
    };
    const finish = (fn, val)=>{
      if(done) return;
      done = true;
      cleanup();
      fn(val);
    };
    const onReady = ()=>finish(resolve, true);
    const onError = ()=>finish(reject, new Error(mediaErrorText(el) || "media load failed"));
    try{ el.addEventListener("loadedmetadata", onReady, {once:true}); }catch(e){}
    try{ el.addEventListener("canplay", onReady, {once:true}); }catch(e){}
    try{ el.addEventListener("error", onError, {once:true}); }catch(e){}
    timer = setTimeout(()=>finish(resolve, false), timeoutMs || 4000);
  });
}

function beginPlaybackLoad(el, rootId, rel, kind){
  try{
    if(window.DebriPod && DebriPod.clientSync && DebriPod.clientSync.isServerUnavailable && DebriPod.clientSync.isServerUnavailable()){
      throw new Error(DebriPod.clientSync.serverRequiredMessage ? DebriPod.clientSync.serverRequiredMessage("Playback") : "Playback requires the local DebriPod server.");
    }
  }catch(e){
    if(e && e.message) throw e;
  }
  var src = playbackSourceUrl(rootId, rel);
  if(playbackUsesHls()){
    return {src:src, ready:loadHlsIntoElement(el, src, kind)};
  }
  if(kind === "audio") destroyHlsController("audio");
  else if(kind === "video") destroyHlsController("video");
  else if(kind === "preload") destroyHlsController("preload");
  try{ el.src = src; el.load(); }catch(e){}
  const ready = waitForMediaReady(el, kind === "preload" ? 1200 : 5000).catch((e)=>{
    warnMedia(kind, "load failed", el);
    throw e;
  });
  return {src:src, ready:ready};
}

async function loadPlaybackIntoElement(el, rootId, rel, kind){
  const request = beginPlaybackLoad(el, rootId, rel, kind);
  await request.ready;
  return request.src;
}

function canUseHlsJs(){
  try{ return !!(window.Hls && window.Hls.isSupported && window.Hls.isSupported()); }catch(e){ return false; }
}

function loadHlsIntoElement(el, manifestUrl, kind){
  return new Promise((resolve, reject)=>{
    try{
      if(!el) throw new Error("media element missing");
      if(kind === "audio") destroyHlsController("audio");
      else if(kind === "video") destroyHlsController("video");
      else if(kind === "preload") destroyHlsController("preload");

      const onReady = ()=>resolve(true);

      if(el.canPlayType && el.canPlayType("application/vnd.apple.mpegurl")){
        try{ el.src = manifestUrl; el.load(); }catch(e){}
        el.addEventListener("loadedmetadata", onReady, {once:true});
        el.addEventListener("loadeddata", onReady, {once:true});
        setTimeout(onReady, 1200);
        return;
      }

      if(!canUseHlsJs()) throw new Error("HLS playback is not supported in this browser");
      const hls = new window.Hls({
        autoStartLoad: true,
        enableWorker: true,
        backBufferLength: 90,
        maxBufferLength: 90,
        maxMaxBufferLength: 180,
        maxBufferSize: 120 * 1000 * 1000,
        manifestLoadingMaxRetry: 6,
        levelLoadingMaxRetry: 6,
        fragLoadingMaxRetry: 6
      });
      if(kind === "audio") activeAudioHls = hls;
      else if(kind === "video") activeVideoHls = hls;
      else if(kind === "preload") preloadAudioHls = hls;
      hls.attachMedia(el);
      hls.on(window.Hls.Events.MEDIA_ATTACHED, ()=>{
        try{ hls.loadSource(manifestUrl); }catch(err){ reject(err); }
      });
      hls.on(window.Hls.Events.MANIFEST_PARSED, ()=>resolve(true));
      hls.on(window.Hls.Events.ERROR, (evt, data)=>{
        if(data && data.fatal){
          reject(new Error((data.details || data.type || "hls error") + ""));
        }
      });
    }catch(err){ reject(err); }
  });
}

async function preloadNextAudio(){
  state.preloadedIndex = null;
  resetGaplessPrime();
  if(!state.preloadEnabled){
    const api=gaplessAudioApi();if(api)api.cancelNext();
    retainGaplessBuffers([]);return;
  }
  if(gaplessPlaybackActive()){
    const current=gaplessPlaybackSnapshot().item,next=gaplessNextItem(),api=gaplessAudioApi();
    retainGaplessBuffers([current,next]);
    if(!next || next.media === "video"){api.cancelNext();return;}
    const owner=gaplessPlaybackSnapshot().key;
    const nonce=preloadRequestNonce;
    try{const buffer=await gaplessDecodeItem(next);if(nonce===preloadRequestNonce && state.preloadEnabled && gaplessPlaybackSnapshot()?.key===owner)api.scheduleNext(next,buffer);}catch(e){}
    return;
  }
  if(!state.playlist.length) return;
  var ni = nextIndexPeek();
  if(ni === null) return;
  var next = state.playlist[ni];
  if(!next || !next.root || !next.rel) return;
  state.preloadedIndex = ni;
  var nonce = ++preloadRequestNonce;
  try{
    preloadAudioEl = document.createElement("audio");
    preloadAudioEl.preload = "auto";
    preloadAudioEl.muted = true;
    preloadAudioEl.volume = 0;
    preloadAudioEl.playsInline = true;
    await loadPlaybackIntoElement(preloadAudioEl, next.root.id, next.rel, "preload");
    if(nonce !== preloadRequestNonce) return;
    try{
      if(preloadAudioHls && preloadAudioHls.startLoad) preloadAudioHls.startLoad(0);
      else if(preloadAudioEl.load) preloadAudioEl.load();
    }catch(e){}
    try{
      if(preloadAudioEl.play){
        const p = preloadAudioEl.play();
        if(p && p.then){
          p.then(()=>{
            try{ preloadAudioEl.pause(); preloadAudioEl.currentTime = 0; }catch(e){}
          }).catch(()=>{});
        }
      }
    }catch(e){}
  }catch(e){
    if(nonce === preloadRequestNonce) resetGaplessPrime();
  }
}
