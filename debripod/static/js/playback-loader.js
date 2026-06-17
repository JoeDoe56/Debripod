  var npArtSwap = document.getElementById("npArtSwap");

  var audioMain = document.getElementById("audioMain");
  var npBufferedFill = document.getElementById("npBufferedFill");
  var activeAudio = audioMain;
  var standbyAudio = null;
  var activeAudioHls = null;
  var activeVideoHls = null;
  var preloadAudioHls = null;
  var preloadAudioEl = null;
  var preloadRequestNonce = 0;

// ===== volume (wheel controlled; native media element volume) =====
var userVol = 1.0;
try{
  var v = parseFloat(localStorage.getItem("debripod_volume") || "");
  if(!isNaN(v)) userVol = Math.max(0, Math.min(1, v));
}catch(e){}

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
  try{
    if(activeAudio){
      activeAudio.muted = false;
      activeAudio.volume = v;
    }
  }catch(e){}
  try{ if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; } }catch(e){}
  try{ if(npVideo){ npVideo.muted = false; npVideo.volume = v; } }catch(e){}
  try{
    if(npVolumeFill){
      npVolumeFill.style.width = Math.round(v * 100) + "%";
    }
  }catch(e){}
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
    if(activeAudio){ activeAudio.muted = false; activeAudio.volume = userVol; }
    if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; }
  }catch(e){}
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

async function loadPlaybackIntoElement(el, rootId, rel, kind){
  var src = playbackSourceUrl(rootId, rel);
  if(playbackUsesHls()){
    await loadHlsIntoElement(el, src, kind);
    return src;
  }
  if(kind === "audio") destroyHlsController("audio");
  else if(kind === "video") destroyHlsController("video");
  else if(kind === "preload") destroyHlsController("preload");
  try{ el.src = src; el.load(); }catch(e){}
  try{ await waitForMediaReady(el, kind === "preload" ? 1200 : 5000); }catch(e){ warnMedia(kind, "load failed", el); throw e; }
  return src;
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
  if(!state.preloadEnabled) return;
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

function gaplessPrimeMaybe(d, t){}
function gaplessEarlyHandoffMaybe(d, t){ return false; }
function gaplessHandoffToNext(ni){ return false; }
