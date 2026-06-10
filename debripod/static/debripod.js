(function(){
  const APP_INFO = window.DEBRIPOD_APP_INFO || {};
  function humanBytes(bytes){
    const v = Number(bytes || 0);
    if(!isFinite(v) || v <= 0) return "0 B";
    const units = ["B","KB","MB","GB","TB"];
    let n = v;
    let i = 0;
    while(n >= 1024 && i < units.length - 1){
      n /= 1024;
      i += 1;
    }
    const p = n >= 100 ? 0 : (n >= 10 ? 1 : 2);
    return n.toFixed(p) + " " + units[i];
  }

  async function apiPost(url, payload){
    const res = await fetch(url, {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload || {}),
      cache:"no-store"
    });
    let j = null;
    try{ j = await res.json(); }catch(e){}
    return {ok: res.ok, status: res.status, json: j};
  }

const libHeader = document.getElementById("libHeader");

  // ===== path pill show/hide (like Now Playing info pill) =====
  let pathPillPinned = false;
  let pathPillHideTimer = null;
  try{
    pathPillPinned = (localStorage.getItem("debripod_path_pill_pinned") || "") === "1";
  }catch(e){}

  function isLibraryTabActive(){
    try{
      const t = document.getElementById("tab-library");
      if(!t) return true;
      return (t.style.display !== "none");
    }catch(e){
      return true;
    }
  }

  function showPathPill(pinned){
    const effectivePinned = !!pinned || !!pathPillPinned;
    try{
      if(!libHeader) return;
      libHeader.classList.remove("pathPillHidden");
    }catch(e){}
    if(effectivePinned){
      try{ if(pathPillHideTimer) clearTimeout(pathPillHideTimer); }catch(e){}
      pathPillHideTimer = null;
    }
  }

  function scheduleHidePathPill(ms){
    try{
      if(!libHeader) return;
      try{ if(pathPillHideTimer) clearTimeout(pathPillHideTimer); }catch(e){}
      pathPillHideTimer = setTimeout(()=>{
        try{
          if(!isLibraryTabActive()) return;
          if(pathPillPinned) return;
          const ae = document.activeElement;
          if(ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT" || ae.isContentEditable)) return;
          libHeader.classList.add("pathPillHidden");
        }catch(e){}
      }, (ms || 2500));
    }catch(e){}
  }

  function pathPillActivity(pinned){
    const effectivePinned = !!pinned || !!pathPillPinned;
    showPathPill(effectivePinned);
    if(!effectivePinned) scheduleHidePathPill(2500);
  }

  function setPathPillPinned(on){
    pathPillPinned = !!on;
    try{ localStorage.setItem("debripod_path_pill_pinned", pathPillPinned ? "1" : "0"); }catch(e){}
    if(pathPillPinned){
      showPathPill(true);
    }else{
      pathPillActivity(false);
    }
  }

  if(libHeader){
    libHeader.addEventListener("click", ()=>{
      try{
        setPathPillPinned(!pathPillPinned);
      }catch(e){}
    });
  }

  window.addEventListener("pointerdown", ()=>{
    try{
      if(isLibraryTabActive()) pathPillActivity(false);
    }catch(e){}
  }, {passive:true});

  const libList = document.getElementById("libList");
  const ipodScreen = document.getElementById("ipodScreen");
  const visualizerBg = document.getElementById("visualizerBg");
  let npPageFadeTimer = null;
  let npPageFadeToken = 0;
  const nowPlaying = document.getElementById("nowPlaying");
  const npArt = document.getElementById("npArt");
  const npTitle = document.getElementById("npTitle");
  const npSub = document.getElementById("npSub");
  const npSeek = document.getElementById("npSeek");
  const npCur = document.getElementById("npCur");
  const npDur = document.getElementById("npDur");
  const npTech = document.getElementById("npTech");
  const npProgressWrap = document.getElementById("npProgressWrap");
  const npVideoOverlay = document.getElementById("npVideoOverlay");
  const npVideo = document.getElementById("npVideo");
  const npVolumeWrap = document.getElementById("npVolumeWrap");
  const npVolumeFill = document.getElementById("npVolumeFill");
  const npSeekIndicator = document.getElementById("npSeekIndicator");
  const npOverlayPill = document.getElementById("npOverlayPill");
  const npArtSwap = document.getElementById("npArtSwap");

  const audioMain = document.getElementById("audioMain");
  const npBufferedFill = document.getElementById("npBufferedFill");
  let activeAudio = audioMain;
  let standbyAudio = null;
  let activeAudioHls = null;
  let activeVideoHls = null;
  let preloadAudioHls = null;
  let preloadAudioEl = null;
  let preloadRequestNonce = 0;

// ===== volume (wheel controlled; native media element volume) =====
let userVol = 1.0;
try{
  const v = parseFloat(localStorage.getItem("debripod_volume") || "");
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
  const v = userVol;
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
  const ni = nextIndexPeek();
  if(ni === null) return;
  const next = state.playlist[ni];
  if(!next || !next.root || !next.rel) return;
  state.preloadedIndex = ni;
  const nonce = ++preloadRequestNonce;
  const manifestUrl = hlsManifestUrl(next.root.id, next.rel);
  try{
    preloadAudioEl = document.createElement("audio");
    preloadAudioEl.preload = "auto";
    preloadAudioEl.muted = true;
    preloadAudioEl.volume = 0;
    preloadAudioEl.playsInline = true;
    await loadHlsIntoElement(preloadAudioEl, manifestUrl, "preload");
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


let volBarTimer = null;
let seekMode = false;
let seekChanged = false;
let seekPreview = 0;
let seekIdleTimer = null;

let npPillHideTimer = null;
let npArtSwapTimer = null;
let npPillSwapTimer = null;
let visualizerEnabled = false;
let visualizerActive = false;
let visualizerTrackKey = "";
let visualizerSampleNonce = 0;
const defaultTheme = {
  accent: "rgba(10,132,255,.88)",
  accentStrong: "rgba(10,132,255,1)",
  accentSoft: "rgba(10,132,255,.18)",
  accentOutline: "rgba(10,132,255,.42)",
  accentBar: "rgba(10,132,255,.92)",
  accentGlow: "rgba(10,132,255,.36)",
  visualizerA: "rgba(10,132,255,.42)",
  visualizerB: "rgba(94,92,230,.30)",
  visualizerC: "rgba(255,69,58,.18)"
};

let visualizerAudioCtx = null;
let visualizerAnalyser = null;
let visualizerData = null;
let visualizerSources = new WeakMap();
let visualizerFrameHandle = 0;
let visualizerLastFrameTs = 0;
let visualizerEnergy = 0;
let visualizerBass = 0;
let visualizerMid = 0;
let visualizerTreble = 0;

function currentVisualizerMediaElement(){
  try{
    if(isVideoActive && isVideoActive() && npVideo) return npVideo;
  }catch(e){}
  try{
    if(activeAudio && activeAudio.src && !activeAudio.paused) return activeAudio;
  }catch(e){}
  return null;
}

function ensureVisualizerAudioGraphFor(el){
  try{
    if(!el || !(window.AudioContext || window.webkitAudioContext)) return false;
    if(!visualizerAudioCtx){
      const Ctx = window.AudioContext || window.webkitAudioContext;
      visualizerAudioCtx = new Ctx();
    }
    if(!visualizerAnalyser){
      visualizerAnalyser = visualizerAudioCtx.createAnalyser();
      visualizerAnalyser.fftSize = 128;
      visualizerAnalyser.smoothingTimeConstant = 0.68;
      visualizerData = new Uint8Array(visualizerAnalyser.frequencyBinCount);
    }
    if(!visualizerSources.has(el)){
      const srcNode = visualizerAudioCtx.createMediaElementSource(el);
      srcNode.connect(visualizerAnalyser);
      visualizerAnalyser.connect(visualizerAudioCtx.destination);
      visualizerSources.set(el, srcNode);
    }
    if(visualizerAudioCtx.state === "suspended"){
      try{ visualizerAudioCtx.resume(); }catch(e){}
    }
    return true;
  }catch(e){
    return false;
  }
}

function setVisualizerMotionVars(energy, bass, mid, treble){
  const root = document.documentElement;
  const e = Math.max(0, Math.min(1, Number(energy || 0)));
  const b = Math.max(0, Math.min(1, Number(bass || 0)));
  const m = Math.max(0, Math.min(1, Number(mid || 0)));
  const t = Math.max(0, Math.min(1, Number(treble || 0)));
  try{
    root.style.setProperty("--viz-energy", e.toFixed(4));
    root.style.setProperty("--viz-bass", b.toFixed(4));
    root.style.setProperty("--viz-mid", m.toFixed(4));
    root.style.setProperty("--viz-treble", t.toFixed(4));
    root.style.setProperty("--viz-x1", (50 + ((m - .5) * 24)).toFixed(2) + "%");
    root.style.setProperty("--viz-y1", (30 + ((b - .5) * 24)).toFixed(2) + "%");
    root.style.setProperty("--viz-x2", (20 + (b * 16)).toFixed(2) + "%");
    root.style.setProperty("--viz-y2", (74 - (t * 22)).toFixed(2) + "%");
    root.style.setProperty("--viz-x3", (80 - (m * 18)).toFixed(2) + "%");
    root.style.setProperty("--viz-y3", (64 - (b * 14) + (t * 12)).toFixed(2) + "%");
    root.style.setProperty("--viz-r1", (30 + (b * 30) + (e * 8)).toFixed(2) + "%");
    root.style.setProperty("--viz-r2", (34 + (m * 32) + (e * 7)).toFixed(2) + "%");
    root.style.setProperty("--viz-r3", (30 + (t * 34) + (e * 8)).toFixed(2) + "%");
    root.style.setProperty("--viz-blur", (1.5 + (e * 8)).toFixed(2) + "px");
  }catch(e){}
}

function visualizerFrame(ts){
  try{
    const nowTs = Number(ts || performance.now() || 0);
    if(visualizerLastFrameTs && (nowTs - visualizerLastFrameTs) < 33){
      visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
      return;
    }
    visualizerLastFrameTs = nowTs;
    const el = currentVisualizerMediaElement();
    const canAnalyze = !!(visualizerEnabled && visualizerActive && el && ensureVisualizerAudioGraphFor(el) && visualizerAnalyser && visualizerData);
    let nextBass = 0;
    let nextMid = 0;
    let nextTreble = 0;
    let nextEnergy = 0;
    if(canAnalyze){
      try{ visualizerAnalyser.getByteFrequencyData(visualizerData); }catch(e){}
      const n = visualizerData.length || 0;
      if(n > 0){
        const bassEnd = Math.max(1, Math.floor(n * 0.16));
        const midEnd = Math.max(bassEnd + 1, Math.floor(n * 0.50));
        let bassSum = 0, midSum = 0, trebleSum = 0, allSum = 0;
        for(let i = 0; i < n; i++){
          const v = Number(visualizerData[i] || 0) / 255;
          allSum += v;
          if(i < bassEnd) bassSum += v;
          else if(i < midEnd) midSum += v;
          else trebleSum += v;
        }
        nextBass = bassSum / Math.max(1, bassEnd);
        nextMid = midSum / Math.max(1, midEnd - bassEnd);
        nextTreble = trebleSum / Math.max(1, n - midEnd);
        nextEnergy = allSum / n;
        const bassPeak = Math.min(1, Math.max(0, (nextBass - 0.08) * 1.90));
        const midPeak = Math.min(1, Math.max(0, (nextMid - 0.06) * 1.62));
        const treblePeak = Math.min(1, Math.max(0, (nextTreble - 0.05) * 1.72));
        const energyPeak = Math.min(1, Math.max(0, (nextEnergy - 0.05) * 1.85));
        nextBass = Math.min(1, (nextBass * 0.55) + (bassPeak * 0.95));
        nextMid = Math.min(1, (nextMid * 0.62) + (midPeak * 0.88));
        nextTreble = Math.min(1, (nextTreble * 0.58) + (treblePeak * 0.92));
        nextEnergy = Math.min(1, (nextEnergy * 0.45) + (energyPeak * 1.05) + (bassPeak * 0.12));
      }
    }
    const easeUp = 0.42;
    const easeDown = 0.18;
    const mixVal = (prev, nxt)=> prev + (nxt - prev) * (nxt > prev ? easeUp : easeDown);
    visualizerBass = mixVal(visualizerBass, nextBass);
    visualizerMid = mixVal(visualizerMid, nextMid);
    visualizerTreble = mixVal(visualizerTreble, nextTreble);
    visualizerEnergy = mixVal(visualizerEnergy, nextEnergy);
    setVisualizerMotionVars(visualizerEnergy, visualizerBass, visualizerMid, visualizerTreble);
  }catch(e){}
  visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
}

function ensureVisualizerFrameLoop(){
  try{
    if(visualizerFrameHandle) return;
    visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
  }catch(e){}
}
try{
  visualizerEnabled = (localStorage.getItem("debripod_visualizer") || "") === "1";
}catch(e){}

let npPillPinned = false;
try{
  npPillPinned = (localStorage.getItem("debripod_np_pill_pinned") || "") === "1";
}catch(e){}

function setNpPillPinned(on){
  npPillPinned = !!on;
  try{ localStorage.setItem("debripod_np_pill_pinned", npPillPinned ? "1" : "0"); }catch(e){}
  if(npPillPinned){
    showNpPill(true);
  }else{
    npPillActivity(false);
  }
}

function hideNpPillImmediate(){
  try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
  npPillHideTimer = null;
  try{
    if(npOverlayPill) npOverlayPill.classList.add("npPillHidden");
  }catch(e){}
}

if(npArt){
  npArt.addEventListener("click", ()=>{
    if(nowPlaying.style.display !== "block") return;
    if(isNpPillShown()){
      npPillPinned = false;
      try{ localStorage.setItem("debripod_np_pill_pinned", "0"); }catch(e){}
      hideNpPillImmediate();
    }else{
      setNpPillPinned(true);
    }
  });
}


function clampByte(n){
  const v = Math.round(Number(n || 0));
  if(!isFinite(v)) return 0;
  return Math.max(0, Math.min(255, v));
}

function rgbaFrom(rgb, a){
  return "rgba(" + clampByte(rgb.r) + "," + clampByte(rgb.g) + "," + clampByte(rgb.b) + "," + Number(a).toFixed(3).replace(/0+$/,'').replace(/\.$/,'') + ")";
}

function mixRgb(a, b, t){
  const p = Math.max(0, Math.min(1, Number(t || 0)));
  return {
    r: Math.round((a.r || 0) + ((b.r || 0) - (a.r || 0)) * p),
    g: Math.round((a.g || 0) + ((b.g || 0) - (a.g || 0)) * p),
    b: Math.round((a.b || 0) + ((b.b || 0) - (a.b || 0)) * p)
  };
}

function themeFromBase(base){
  const white = {r:255,g:255,b:255};
  const black = {r:0,g:0,b:0};
  const a = mixRgb(base, white, .16);
  const b = mixRgb(base, {r:94,g:92,b:230}, .32);
  const c = mixRgb(base, {r:255,g:69,b:58}, .22);
  return {
    accent: rgbaFrom(a, .88),
    accentStrong: rgbaFrom(mixRgb(base, white, .12), 1),
    accentSoft: rgbaFrom(mixRgb(base, black, .06), .20),
    accentOutline: rgbaFrom(mixRgb(base, white, .10), .46),
    accentBar: rgbaFrom(mixRgb(base, white, .10), .94),
    accentGlow: rgbaFrom(base, .34),
    visualizerA: rgbaFrom(a, .46),
    visualizerB: rgbaFrom(b, .34),
    visualizerC: rgbaFrom(c, .22)
  };
}

function applyThemeVars(theme){
  const t = theme || defaultTheme;
  const root = document.documentElement;
  try{
    root.style.setProperty("--theme-accent", t.accent || defaultTheme.accent);
    root.style.setProperty("--theme-accent-strong", t.accentStrong || defaultTheme.accentStrong);
    root.style.setProperty("--theme-accent-soft", t.accentSoft || defaultTheme.accentSoft);
    root.style.setProperty("--theme-accent-outline", t.accentOutline || defaultTheme.accentOutline);
    root.style.setProperty("--theme-accent-bar", t.accentBar || defaultTheme.accentBar);
    root.style.setProperty("--theme-accent-glow", t.accentGlow || defaultTheme.accentGlow);
    root.style.setProperty("--theme-visualizer-a", t.visualizerA || defaultTheme.visualizerA);
    root.style.setProperty("--theme-visualizer-b", t.visualizerB || defaultTheme.visualizerB);
    root.style.setProperty("--theme-visualizer-c", t.visualizerC || defaultTheme.visualizerC);
  }catch(e){}
}

function visualizerShouldShow(){
  try{
    const hasArt = !!(state && state.now && state.nowMeta && state.nowMeta.art);
    const media = currentVisualizerMediaElement();
    return !!(visualizerEnabled && hasArt && media);
  }catch(e){
    return false;
  }
}

function setVisualizerActive(on){
  visualizerActive = !!on;
  try{
    if(!visualizerBg) return;
    visualizerBg.classList.toggle("active", !!on);
    visualizerBg.classList.toggle("off", !on);
  }catch(e){}
}

function updateVisualizerState(){
  ensureVisualizerFrameLoop();
  setVisualizerActive(visualizerShouldShow());
}

function setVisualizerEnabled(on){
  visualizerEnabled = !!on;
  try{ localStorage.setItem("debripod_visualizer", visualizerEnabled ? "1" : "0"); }catch(e){}
  updateVisualizerState();
  try{ if(state && state.current && state.current.kind === "libinfo") viewLibInfo(false); }catch(e){}
}

function sampleThemeFromArt(src){
  const art = nowPlayingArtSrcValue(src);
  const key = nowPlayingArtCompareKey(art);
  if(!key || !art){
    visualizerTrackKey = "";
    applyThemeVars(defaultTheme);
    updateVisualizerState();
    return;
  }
  visualizerTrackKey = key;
  const myNonce = ++visualizerSampleNonce;
  const img = new Image();
  img.decoding = "async";
  img.onload = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    try{
      const w = Math.max(8, Math.min(40, img.naturalWidth || 24));
      const h = Math.max(8, Math.min(40, img.naturalHeight || 24));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", {willReadFrequently:true});
      if(!ctx) throw new Error("no canvas context");
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;
      let r = 0, g = 0, b = 0, c = 0;
      for(let i = 0; i < data.length; i += 4){
        const a = Number(data[i + 3] || 0);
        if(a < 24) continue;
        const rr = Number(data[i] || 0);
        const gg = Number(data[i + 1] || 0);
        const bb = Number(data[i + 2] || 0);
        const mx = Math.max(rr, gg, bb);
        const mn = Math.min(rr, gg, bb);
        const sat = mx ? (mx - mn) / mx : 0;
        const lum = (rr * .299 + gg * .587 + bb * .114) / 255;
        if(lum < .08 || lum > .95) continue;
        const weight = Math.max(.18, sat) * (0.65 + (1 - Math.abs(lum - .5) * 1.2));
        r += rr * weight;
        g += gg * weight;
        b += bb * weight;
        c += weight;
      }
      if(!(c > 0)) throw new Error("empty sample");
      const base = {r: Math.round(r / c), g: Math.round(g / c), b: Math.round(b / c)};
      applyThemeVars(themeFromBase(base));
    }catch(err){
      applyThemeVars(defaultTheme);
    }
    updateVisualizerState();
  };
  img.onerror = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    applyThemeVars(defaultTheme);
    updateVisualizerState();
  };
  img.src = art;
}

function nowPlayingArtSrcValue(src){
  return String(src || "").trim();
}

function nowPlayingArtCompareKey(src){
  const v = nowPlayingArtSrcValue(src);
  if(!v) return "";
  try{
    const u = new URL(v, window.location.href);
    return (u.pathname || "") + "|" + (u.searchParams.get("v") || "");
  }catch(e){
    const q = v.split("?");
    let ver = "";
    try{
      const sp = new URLSearchParams(q[1] || "");
      ver = sp.get("v") || "";
    }catch(err){}
    return (q[0] || "") + "|" + ver;
  }
}

function currentNowPlayingArtSrc(){
  try{
    if(!npArt) return "";
    return nowPlayingArtSrcValue(npArt.getAttribute("src") || "");
  }catch(e){
    return "";
  }
}

function setNowPlayingArtSrc(src){
  try{
    if(!npArt) return;
    const v = nowPlayingArtSrcValue(src);
    if(v){
      npArt.src = v;
    }else{
      npArt.removeAttribute("src");
    }
  }catch(e){}
}

function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function artistAlbumHtml(artist, album){
  const a = String(artist || "").trim();
  const b = String(album || "").trim();
  if(a && b) return '<span class="artistStrong">' + escapeHtml(a) + '</span>   ' + escapeHtml(b);
  if(a) return '<span class="artistStrong">' + escapeHtml(a) + '</span>';
  return escapeHtml(b);
}

function setNowPlayingOverlayText(meta, fallbackLabel){
  const m = meta || {};
  try{ npTitle.textContent = m.title || fallbackLabel || "Track"; }catch(e){}
  try{ npSub.innerHTML = artistAlbumHtml(m.artist || "", m.album || ""); }catch(e){}
  try{ if(npTech) npTech.textContent = m.tech || ""; }catch(e){}
}

function isNpPillShown(){
  try{
    return !!(npOverlayPill && !npOverlayPill.classList.contains("npPillHidden"));
  }catch(e){
    return false;
  }
}

async function updateNowPlayingDisplay(meta, fallbackLabel, opts){
  const m = meta || {};
  const options = opts || {};
  const nextArt = nowPlayingArtSrcValue(m.art);
  const currentArt = currentNowPlayingArtSrc();
  const currentArtKey = nowPlayingArtCompareKey(currentArt);
  const nextArtKey = nowPlayingArtCompareKey(nextArt);
  const animateArt = !!(options.animateArt && npArt && npArtSwap && currentArtKey && nextArtKey && currentArtKey !== nextArtKey);
  const animatePill = !!(options.animatePill && isNpPillShown());
  sampleThemeFromArt(nextArt);
  const swapMs = 220;

  try{ if(npArtSwapTimer) clearTimeout(npArtSwapTimer); }catch(e){}
  npArtSwapTimer = null;
  try{ if(npPillSwapTimer) clearTimeout(npPillSwapTimer); }catch(e){}
  npPillSwapTimer = null;

  if(animateArt){
    try{
      if(currentArt){
        npArtSwap.src = currentArt;
      }else{
        npArtSwap.removeAttribute("src");
      }
      const prevTransition = npArtSwap.style.transition;
      npArtSwap.style.transition = "none";
      npArtSwap.classList.remove("npArtSwapHidden");
      void npArtSwap.offsetWidth;
      npArtSwap.style.transition = prevTransition || "";
    }catch(e){}
  }

  if(animatePill){
    try{
      npOverlayPill.classList.add("npPillSwapHidden");
    }catch(e){}
  }

  setNowPlayingArtSrc(nextArt);

  if(animateArt){
    requestAnimationFrame(()=>{
      requestAnimationFrame(()=>{
        try{ npArtSwap.classList.add("npArtSwapHidden"); }catch(e){}
      });
    });
    npArtSwapTimer = setTimeout(()=>{
      try{
        if(!npArtSwap) return;
        npArtSwap.removeAttribute("src");
        npArtSwap.classList.add("npArtSwapHidden");
      }catch(e){}
      npArtSwapTimer = null;
    }, swapMs + 40);
  }

  if(animatePill){
    npPillSwapTimer = setTimeout(()=>{
      try{ setNowPlayingOverlayText(m, fallbackLabel); }catch(e){}
      requestAnimationFrame(()=>{
        try{ if(npOverlayPill) npOverlayPill.classList.remove("npPillSwapHidden"); }catch(e){}
      });
      npPillSwapTimer = null;
    }, swapMs);
  }else{
    setNowPlayingOverlayText(m, fallbackLabel);
  }
}

function showNpPill(pinned){
  const effectivePinned = !!pinned || !!npPillPinned;
  try{
    if(!npOverlayPill) return;
    npOverlayPill.classList.remove("npPillHidden");
  }catch(e){}
  if(effectivePinned){
    try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
    npPillHideTimer = null;
  }
}


function scheduleHideNpPill(ms){
  try{
    if(!npOverlayPill) return;
    try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
    npPillHideTimer = setTimeout(()=>{
      try{
        if(nowPlaying.style.display !== "block") return;
        if(seekMode) return;
        if(npPillPinned) return;
        const m = wheelMedia();
        if(!m) return;
        if(m.paused) return;
        npOverlayPill.classList.add("npPillHidden");
      }catch(e){}
    }, (ms || 2500));
  }catch(e){}
}

function npPillActivity(pinned){
  const effectivePinned = !!pinned || !!npPillPinned;
  showNpPill(effectivePinned);
  if(!effectivePinned) scheduleHideNpPill(2500);
}


function showProgressBar(){
  try{
    npProgressWrap.style.display = "block";
    npVolumeWrap.style.display = "none";
  }catch(e){}
}

function showVolumeBar(){
  try{
    npProgressWrap.style.display = "none";
    npVolumeWrap.style.display = "block";
    if(npVolumeFill) npVolumeFill.style.width = Math.round(userVol * 100) + "%";
  }catch(e){}
}

function scheduleHideVolumeBar(){
  try{
    if(volBarTimer) clearTimeout(volBarTimer);
    volBarTimer = setTimeout(()=>{
      if(!seekMode && nowPlaying.style.display === "block"){
        showProgressBar();
      }
    }, 700);
  }catch(e){}
}

function resetSeekIdle(){
  try{
    if(seekIdleTimer) clearTimeout(seekIdleTimer);
    seekIdleTimer = setTimeout(()=>{
      cancelSeekMode();
    }, 2500);
  }catch(e){}
}

function updateSeekIndicator(){
  try{
    const m = wheelMedia();
    const d = (m && m.duration) ? m.duration : 0;
    if(d <= 0){
      npSeekIndicator.style.left = "0%";
      return;
    }
    const pct = Math.max(0, Math.min(1, (seekPreview || 0) / d)) * 100;
    npSeekIndicator.style.left = "calc(" + pct + "% - 1px)";
  }catch(e){}
}

function enterSeekMode(){
  if(nowPlaying.style.display !== "block") return;
  seekMode = true;
  seekChanged = false;
  showNpPill(true);
  const m = wheelMedia();
  seekPreview = (m && m.currentTime) ? m.currentTime : 0;
  showProgressBar();
  try{ npSeekIndicator.style.display = "block"; }catch(e){}
  updateSeekIndicator();
  resetSeekIdle();
  updateWheelLabels();
  scheduleHideNpPill(2000);
}

function cancelSeekMode(){
  if(!seekMode) return;
  seekMode = false;
  seekChanged = false;
  try{ if(seekIdleTimer) clearTimeout(seekIdleTimer); }catch(e){}
  seekIdleTimer = null;
  try{ npSeekIndicator.style.display = "none"; }catch(e){}
  showProgressBar();
  updateWheelLabels();
}

function commitSeekMode(){
  if(!seekMode) return;
  const m = wheelMedia();
  const d = (m && m.duration) ? m.duration : 0;
  if(d > 0){
    try{
      if(m) m.currentTime = Math.max(0, Math.min(d, seekPreview));
    }catch(e){}
  }
  cancelSeekMode();
}

function wheelLabelSvg(name, active){
  const filled = !!active;
  const icon = (b64, cls='') => '<img class="wheelSvgIcon' + (cls ? ' ' + cls : '') + '" aria-hidden="true" alt="" src="data:image/svg+xml;base64,' + b64 + '">';
  if(name === "menu") return '<span class="menuWord">MENU</span>';
  if(name === "heart") return icon(filled ? "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTE2LjQzMDcsMi43MjgwNUMyMC4wNDg1LDIuNzI4MDUgMjIuNDc5NCw2LjEyODk3IDIyLjQ3OTQsOS4zMDE2NEMyMi40Nzk0LDE1LjcyNjkgMTIuMzkwNywyMC45ODggMTIuMjA4MSwyMC45ODhDMTIuMDI1NSwyMC45ODggMS45MzY4OCwxNS43MjY5IDEuOTM2ODgsOS4zMDE2NEMxLjkzNjg4LDYuMTI4OTcgNC4zNjc3NCwyLjcyODA1IDcuOTg1NSwyLjcyODA1QzEwLjA2MjYsMi43MjgwNSAxMS40MjA3LDMuNzY2NTkgMTIuMjA4MSw0LjY3OTU4QzEyLjk5NTYsMy43NjY1OSAxNC4zNTM3LDIuNzI4MDUgMTYuNDMwNywyLjcyODA1TDE2LjQzMDcsMi43MjgwNVoiIHN0cm9rZT0iI0ZGRkZGRiIgc3Ryb2tlLXdpZHRoPSIyLjI4MjciIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0iI0ZGRkZGRiIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L2c+Cjwvc3ZnPgo=" : "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggc3Ryb2tlPSIjRkZGRkZGIiBzdHJva2Utd2lkdGg9IjIuMjgyNyIgZD0iTTE2LjQzMDcsMi43MjgwNUMyMC4wNDg1LDIuNzI4MDUgMjIuNDc5NCw2LjEyODk3IDIyLjQ3OTQsOS4zMDE2NEMyMi40Nzk0LDE1LjcyNjkgMTIuMzkwNywyMC45ODggMTIuMjA4MSwyMC45ODhDMTIuMDI1NSwyMC45ODggMS45MzY4OCwxNS43MjY5IDEuOTM2ODgsOS4zMDE2NEMxLjkzNjg4LDYuMTI4OTcgNC4zNjc3NCwyLjcyODA1IDcuOTg1NSwyLjcyODA1QzEwLjA2MjYsMi43MjgwNSAxMS40MjA3LDMuNzY2NTkgMTIuMjA4MSw0LjY3OTU4QzEyLjk5NTYsMy43NjY1OSAxNC4zNTM3LDIuNzI4MDUgMTYuNDMwNywyLjcyODA1TDE2LjQzMDcsMi43MjgwNVoiIGZpbGw9IiNGRkZGRkYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbC1vcGFjaXR5PSIwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+CjwvZz4KPC9zdmc+Cg==");
  if(name === "play") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMuMDAzMzUsMjBMMTQuMzM2NiwxMkwzLjAwMzM1LDRMMy4wMDMzNSwyMEwzLjAwMzM1LDIwWiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNMTkuMDAzNCw0TDE2LjMzNjcsNEwxNi4zMzY3LDIwTDE5LjAwMzQsMjBMMTkuMDAzNCw0TDE5LjAwMzQsNFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTIzLjcyMDksNEwyMS4wNTQyLDRMMjEuMDU0MiwyMEwyMy43MjA5LDIwTDIzLjcyMDksNEwyMy43MjA5LDRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==", filled ? 'isActive' : 'isInactive');
  if(name === "pause") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMuMDAzMzUsMjBMMTQuMzM2NiwxMkwzLjAwMzM1LDRMMy4wMDMzNSwyMEwzLjAwMzM1LDIwWiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNMTkuMDAzNCw0TDE2LjMzNjcsNEwxNi4zMzY3LDIwTDE5LjAwMzQsMjBMMTkuMDAzNCw0TDE5LjAwMzQsNFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTIzLjcyMDksNEwyMS4wNTQyLDRMMjEuMDU0MiwyMEwyMy43MjA5LDIwTDIzLjcyMDksNEwyMy43MjA5LDRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==", 'isPaused');
  if(name === "shuffle") return icon(filled ? "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsNTEyLDUxMiIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNTEyIDUxMjsiIHZlcnNpb249IjEuMSI+CjxkZWZzLz4KPGcgaWQ9ImxheWVyMCI+CjxwYXRoIGQ9Ik01MDMuODMsMzk3LjA3M0wzNzAuOTI4LDUwMy44M0w0MjcuNTc1LDM5Ny4wNzNMMzcwLjkyOCwyOTAuMzE2TDUwMy44MywzOTcuMDczWiIgZmlsbD0iI0ZFRkZGRiIvPgo8cGF0aCBkPSJNMzE2LjY1NSwxOTcuNzY4QzMxNy42MjgsMTk1LjE3OSAzMjQuNjc4LDE4OS44MDEgMzI3LjM1NCwxODkuNTVMMzYyLjc1OCwxODkuNTVMMzYyLjc1OCwyMjEuNjg2QzM2Mi43NTgsMjI0LjgzIDM2NC41NjIsMjI3LjY5NSAzNjcuMzk2LDIyOS4wNTNDMzcwLjIzMSwyMzAuNDE0IDM3My41OTIsMjMwLjAyNiAzNzYuMDQ0LDIyOC4wNTVMNTA4Ljk0NiwxMjEuMjk4QzUxMC44NzYsMTE5Ljc0OCA1MTEuOTk5LDExNy40MDYgNTExLjk5OSwxMTQuOTI5QzUxMS45OTksMTEyLjQ1MiA1MTAuODc2LDExMC4xMSA1MDguOTQ2LDEwOC41NkwzNzYuMDQ1LDEuODAxQzM3My41OTQsLTAuMTY3IDM3MC4yMzEsLTAuNTU3IDM2Ny4zOTcsMC44MDNDMzY0LjU2MiwyLjE2MyAzNjIuNzU5LDUuMDI2IDM2Mi43NTksOC4xN0wzNjIuNzU5LDQwLjMwNkwzMjcuMzU1LDQwLjMwNkMyOTMuNzExLDQwLjMwNiAyNTkuNDQzLDUyLjMxMiAyMzAuODYyLDc0LjExMkMyMDIuMjgyLDk1LjkxMiAxODEuNjQyLDEyNS43ODggMTcyLjc0NywxNTguMjM2TDE1NC40MiwyMjUuMDk4TDE0NS43MjMsMTkzLjM3QzE0My4xNCwxODMuOTUgMTI5LjA1OCwxNzMuMjA4IDExOS4yODksMTczLjIwOEwxNi4zNDEsMTczLjIwOEwxNi4zNDEsNTYuNjQ3TDExOS4yODYsNTYuNjQ3QzE0NC4zOSw1Ni42NDcgMTY5Ljc5MSw2NC4wNyAxOTIuNzQzLDc4LjExNUMxOTYuNTkyLDgwLjQ2OSAyMDEuNjIsNzkuMjU4IDIwMy45NzYsNzUuNDExQzIwNi4zMzEsNzEuNTYyIDIwNS4xMiw2Ni41MzMgMjAxLjI3MSw2NC4xNzZDMTc1Ljc1Miw0OC41NiAxNDcuNDAyLDQwLjMwNiAxMTkuMjg2LDQwLjMwNkw4LjE3MSw0MC4zMDZDMy42NTksNDAuMzA2IDAuMDAwOTk5NDUxLDQzLjk2NCAwLjAwMDk5OTQ1MSw0OC40NzZMMC4wMDA5OTk0NTEsMTgxLjM3OEMwLjAwMDk5OTQ1MSwxODUuODkxIDMuNjU5LDE4OS41NDggOC4xNzEsMTg5LjU0OEwxMTkuMjA3LDE4OS41NDZDMTIxLjk2MiwxODkuNzk5IDEyOS4wMTIsMTk1LjE3NyAxMjkuOTYyLDE5Ny42OTFMMTQ1Ljk0NiwyNTYuMDAyTDEyOS45ODUsMzE0LjIzM0MxMjkuMDEyLDMxNi44MjIgMTIxLjk2MiwzMjIuMTk5IDExOS4yODYsMzIyLjQ1MUw4LjE3MSwzMjIuNDUxQzMuNjU5LDMyMi40NTEgMC4wMDA5OTk0NTEsMzI2LjEwOCAwLjAwMDk5OTQ1MSwzMzAuNjIxTDAuMDAwOTk5NDUxLDQ2My41MjNDMC4wMDA5OTk0NTEsNDY4LjAzNiAzLjY1OSw0NzEuNjkzIDguMTcxLDQ3MS42OTNMMTE5LjI4Niw0NzEuNjkzQzE1Mi45Myw0NzEuNjkzIDE4Ny4xOTgsNDU5LjY4NyAyMTUuNzc5LDQzNy44ODdDMjQ0LjM1OSw0MTYuMDg3IDI2NC45OTksMzg2LjIxMSAyNzMuODk0LDM1My43NjNMMjg4LjgwNiwyOTkuMzYzTDMxNi42NTUsMTk3Ljc2OEwzMTYuNjU1LDE5Ny43NjhaTTIwNS44NjksNDI0Ljg5NkMxODAuMTE5LDQ0NC41MzcgMTQ5LjM2OSw0NTUuMzUzIDExOS4yODUsNDU1LjM1M0wxNi4zNDEsNDU1LjM1M0wxNi4zNDEsMzM4Ljc5MkwxMTkuMjg2LDMzOC43OTJDMTI5LjA1NSwzMzguNzkyIDE0My4xMzgsMzI4LjA1MSAxNDUuNzIyLDMxOC42MjhMMTg4LjUwNiwxNjIuNTU1QzE5Ni40NTksMTMzLjU0MiAyMTUuMDIyLDEwNi43NDcgMjQwLjc3Miw4Ny4xMDRDMjY2LjUyMSw2Ny40NjUgMjk3LjI3MSw1Ni42NDggMzI3LjM1NCw1Ni42NDhMMzcwLjkyOCw1Ni42NDhDMzc1LjQ0LDU2LjY0OCAzNzkuMDk4LDUyLjk5MSAzNzkuMDk4LDQ4LjQ3OEwzNzkuMDk4LDI1LjIxNEw0OTAuNzg0LDExNC45MjhMMzc5LjA5OCwyMDQuNjQzTDM3OS4wOTgsMTgxLjM3OUMzNzkuMDk4LDE3Ni44NjYgMzc1LjQ0LDE3My4yMDkgMzcwLjkyOCwxNzMuMjA5TDMyNy4zNTQsMTczLjIwOUMzMTcuNTg1LDE3My4yMDkgMzAzLjUwMiwxODMuOTUgMzAwLjkxOCwxOTMuMzczTDI1OC4xMzUsMzQ5LjQ0NkMyNTAuMTgxLDM3OC40NTggMjMxLjYxOSw0MDUuMjU0IDIwNS44NjksNDI0Ljg5NkwyMDUuODY5LDQyNC44OTZaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0yMTAuODIzLDgwLjYwOUMxODMuNjU4LDU5Ljg4OSAxNTEuMTQ5LDQ4LjQ3NyAxMTkuMjg1LDQ4LjQ3N0w4LjE3MSw0OC40NzdMOC4xNzEsMTgxLjM3OUwxMTkuMjg2LDE4MS4zNzlDMTI1LjMyMSwxODEuMzc5IDEzNi4yNDUsMTg5LjcxMiAxMzcuODQxLDE5NS41MzJMMTgwLjYyNSwzNTEuNjA1TDI2Ni4wMTUsMTYwLjM5N0MyNTcuNTksMTI5LjY2NiAyMzcuOTksMTAxLjMzMSAyMTAuODIzLDgwLjYwOUwyMTAuODIzLDgwLjYwOVoiIGZpbGw9IiNGRUZGRkYiLz4KPHBhdGggZD0iTTUwMy44MywxMTQuOTI4TDM3MC45MjgsMjIxLjY4Nkw0MjcuNTc1LDExNC45MjhMMzcwLjkyOCw4LjE3MUw1MDMuODMsMTE0LjkyOFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTQ2MC4yNTYsMzk3LjA3M0wzNzAuOTI4LDI5MC4zMTZMMzcwLjkyOCwzMzAuNjIyTDMyNy4zNTQsMzMwLjYyMkMzMjEuNywzMzAuNjIyIDMxMS43NjUsMzIzLjMxMiAzMDkuMjE2LDMxNy42MTVMMjQ5LjYzOSw0NDAuODQ0QzI3My42Nyw0NTUuNTYxIDMwMC43Myw0NjMuNTI1IDMyNy4zNTQsNDYzLjUyNUwzNzAuOTI4LDQ2My41MjVMMzcwLjkyOCw1MDMuODMxTDQ2MC4yNTYsMzk3LjA3M0w0NjAuMjU2LDM5Ny4wNzNaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0zMDkuMjE2LDMxNy42MTVMMjk3LjUyNywzNjAuMjQyQzI4OS4zMzUsMzkwLjE0NSAyNzIuNjM1LDQxOC4wNzYgMjQ5LjYzOSw0NDAuODQ0QzI0NC45LDQzNy45NTcgMjQwLjI4MSw0MzQuNzk4IDIzNS44MTUsNDMxLjM4OEMyMDguNjQ2LDQxMC42NjggMTg5LjA0OSwzODIuMzM0IDE4MC42MjgsMzUxLjYwM0wyNjYuMDEyLDE2MC4zOThMMzA4LjgwMiwzMTYuNDcxQzMwOC45LDMxNi44NDIgMzA5LjA0MSwzMTcuMjIzIDMwOS4yMTYsMzE3LjYxNUwzMDkuMjE2LDMxNy42MTVaIiBmaWxsPSIjRkZGRkZGIi8+CjxwYXRoIGQ9Ik00NjAuMjU2LDExNC45MjhMMzcwLjkyOCw4LjE3MUwzNzAuOTI4LDQ4LjQ3N0wzMjcuMzU0LDQ4LjQ3N0MyOTUuNDksNDguNDc3IDI2Mi45ODEsNTkuODg5IDIzNS44MTYsODAuNjA5QzIwOC42NDksMTAxLjMzIDE4OS4wNSwxMjkuNjY1IDE4MC42MjYsMTYwLjM5NkwxMzcuODQyLDMxNi40NjlDMTM2LjI0NiwzMjIuMjg5IDEyNS4zMjEsMzMwLjYyMiAxMTkuMjg3LDMzMC42MjJMOC4xNzEsMzMwLjYyMkw4LjE3MSw0NjMuNTI0TDExOS4yODYsNDYzLjUyNEMxNTEuMTUsNDYzLjUyNCAxODMuNjU5LDQ1Mi4xMTIgMjEwLjgyNCw0MzEuMzkyQzIzNy45OTEsNDEwLjY3MSAyNTcuNTksMzgyLjMzNiAyNjYuMDE0LDM1MS42MDVMMzA4Ljc5OCwxOTUuNTMyQzMxMC4zOTQsMTg5LjcxMiAzMjEuMzE5LDE4MS4zNzkgMzI3LjM1MywxODEuMzc5TDM3MC45MjcsMTgxLjM3OUwzNzAuOTI3LDIyMS42ODVMNDYwLjI1NiwxMTQuOTI4TDQ2MC4yNTYsMTE0LjkyOFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTUwOC45NDcsMzkwLjcwNUwzNzYuMDQ1LDI4My45NDdDMzczLjU5NCwyODEuOTc3IDM3MC4yMzEsMjgxLjU4OSAzNjcuMzk3LDI4Mi45NDlDMzY0LjU2MiwyODQuMzA3IDM2Mi43NTksMjg3LjE3MiAzNjIuNzU5LDI5MC4zMTZMMzYyLjc1OSwzMjIuNDUxTDMyNy40MzMsMzIyLjQ1M0MzMjQuNjg3LDMyMi4yMDEgMzE3LjY2OCwzMTYuODUzIDMxNi42NjQsMzE0LjI1NkMzMTUuNDQ5LDMwOS45MzcgMzEwLjk3NSwzMDcuNDA2IDMwNi42MzksMzA4LjU4OUMzMDIuMjg3LDMwOS43ODMgMjk5LjcyNywzMTQuMjc4IDMwMC45MiwzMTguNjNDMzAzLjUwNCwzMjguMDUxIDMxNy41ODYsMzM4Ljc5MiAzMjcuMzU2LDMzOC43OTJMMzcwLjkzLDMzOC43OTJDMzc1LjQ0MiwzMzguNzkyIDM3OS4xLDMzNS4xMzUgMzc5LjEsMzMwLjYyMkwzNzkuMSwzMDcuMzU5TDQ5MC43ODYsMzk3LjA3M0wzNzkuMSw0ODYuNzg4TDM3OS4xLDQ2My41MjRDMzc5LjEsNDU5LjAxMSAzNzUuNDQyLDQ1NS4zNTQgMzcwLjkzLDQ1NS4zNTRMMzI3LjM1Niw0NTUuMzU0QzMwMi4yNTIsNDU1LjM1NCAyNzYuODUxLDQ0Ny45MzEgMjUzLjg5OSw0MzMuODg2QzI1MC4wNSw0MzEuNTMzIDI0NS4wMjEsNDMyLjc0MiAyNDIuNjY1LDQzNi41OUMyNDAuMzEsNDQwLjQzOSAyNDEuNTIxLDQ0NS40NjggMjQ1LjM3LDQ0Ny44MjVDMjcwLjg4OSw0NjMuNDQxIDI5OS4yNCw0NzEuNjk1IDMyNy4zNTUsNDcxLjY5NUwzNjIuNzU5LDQ3MS42OTVMMzYyLjc1OSw1MDMuODMxQzM2Mi43NTksNTA2Ljk3NSAzNjQuNTYzLDUwOS44NCAzNjcuMzk3LDUxMS4xOThDMzY4LjUyMSw1MTEuNzM3IDM2OS43MjcsNTEyLjAwMSAzNzAuOTI4LDUxMi4wMDFDMzcyLjc1NSw1MTIuMDAxIDM3NC41NjYsNTExLjM4OCAzNzYuMDQ2LDUxMC4yTDUwOC45NDgsNDAzLjQ0M0M1MTAuODc4LDQwMS44OTMgNTEyLjAwMSwzOTkuNTUxIDUxMi4wMDEsMzk3LjA3NEM1MTIuMDAxLDM5NC41OTcgNTEwLjg3NywzOTIuMjU0IDUwOC45NDcsMzkwLjcwNUw1MDguOTQ3LDM5MC43MDVaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==" : "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsNTEyLDUxMiIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNTEyIDUxMjsiIHZlcnNpb249IjEuMSI+CjxkZWZzLz4KPGcgaWQ9ImxheWVyMCI+CjxwYXRoIGQ9Ik01MDguOTQ3LDM5MC43MDVMMzc2LjA0NSwyODMuOTQ3QzM3My41OTQsMjgxLjk3NyAzNzAuMjMxLDI4MS41ODkgMzY3LjM5NywyODIuOTQ5QzM2NC41NjIsMjg0LjMwNyAzNjIuNzU5LDI4Ny4xNzIgMzYyLjc1OSwyOTAuMzE2TDM2Mi43NTksMzIyLjQ1MUwzMjcuNDMzLDMyMi40NTNDMzI0LjY4NywzMjIuMjAxIDMxNy42NjgsMzE2Ljg1MyAzMTYuNjY0LDMxNC4yNTZDMzE1LjQ0OSwzMDkuOTM3IDMxMC45NzUsMzA3LjQwNiAzMDYuNjM5LDMwOC41ODlDMzAyLjI4NywzMDkuNzgzIDI5OS43MjcsMzE0LjI3OCAzMDAuOTIsMzE4LjYzQzMwMy41MDQsMzI4LjA1MSAzMTcuNTg2LDMzOC43OTIgMzI3LjM1NiwzMzguNzkyTDM3MC45MywzMzguNzkyQzM3NS40NDIsMzM4Ljc5MiAzNzkuMSwzMzUuMTM1IDM3OS4xLDMzMC42MjJMMzc5LjEsMzA3LjM1OUw0OTAuNzg2LDM5Ny4wNzNMMzc5LjEsNDg2Ljc4OEwzNzkuMSw0NjMuNTI0QzM3OS4xLDQ1OS4wMTEgMzc1LjQ0Miw0NTUuMzU0IDM3MC45Myw0NTUuMzU0TDMyNy4zNTYsNDU1LjM1NEMzMDIuMjUyLDQ1NS4zNTQgMjc2Ljg1MSw0NDcuOTMxIDI1My44OTksNDMzLjg4NkMyNTAuMDUsNDMxLjUzMyAyNDUuMDIxLDQzMi43NDIgMjQyLjY2NSw0MzYuNTlDMjQwLjMxLDQ0MC40MzkgMjQxLjUyMSw0NDUuNDY4IDI0NS4zNyw0NDcuODI1QzI3MC44ODksNDYzLjQ0MSAyOTkuMjQsNDcxLjY5NSAzMjcuMzU1LDQ3MS42OTVMMzYyLjc1OSw0NzEuNjk1TDM2Mi43NTksNTAzLjgzMUMzNjIuNzU5LDUwNi45NzUgMzY0LjU2Myw1MDkuODQgMzY3LjM5Nyw1MTEuMTk4QzM2OC41MjEsNTExLjczNyAzNjkuNzI3LDUxMi4wMDEgMzcwLjkyOCw1MTIuMDAxQzM3Mi43NTUsNTEyLjAwMSAzNzQuNTY2LDUxMS4zODggMzc2LjA0Niw1MTAuMkw1MDguOTQ4LDQwMy40NDNDNTEwLjg3OCw0MDEuODkzIDUxMi4wMDEsMzk5LjU1MSA1MTIuMDAxLDM5Ny4wNzRDNTEyLjAwMSwzOTQuNTk3IDUxMC44NzcsMzkyLjI1NCA1MDguOTQ3LDM5MC43MDVMNTA4Ljk0NywzOTAuNzA1WiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNNTAzLjgzLDM5Ny4wNzNMMzcwLjkyOCw1MDMuODNMNDI3LjU3NSwzOTcuMDczTDM3MC45MjgsMjkwLjMxNkw1MDMuODMsMzk3LjA3M1oiIGZpbGw9IiNGRUZGRkYiIGZpbGwtb3BhY2l0eT0iMCIvPgo8cGF0aCBkPSJNMzE2LjY1NSwxOTcuNzY4QzMxNy42MjgsMTk1LjE3OSAzMjQuNjc4LDE4OS44MDEgMzI3LjM1NCwxODkuNTVMMzYyLjc1OCwxODkuNTVMMzYyLjc1OCwyMjEuNjg2QzM2Mi43NTgsMjI0LjgzIDM2NC41NjIsMjI3LjY5NSAzNjcuMzk2LDIyOS4wNTNDMzcwLjIzMSwyMzAuNDE0IDM3My41OTIsMjMwLjAyNiAzNzYuMDQ0LDIyOC4wNTVMNTA4Ljk0NiwxMjEuMjk4QzUxMC44NzYsMTE5Ljc0OCA1MTEuOTk5LDExNy40MDYgNTExLjk5OSwxMTQuOTI5QzUxMS45OTksMTEyLjQ1MiA1MTAuODc2LDExMC4xMSA1MDguOTQ2LDEwOC41NkwzNzYuMDQ1LDEuODAxQzM3My41OTQsLTAuMTY3IDM3MC4yMzEsLTAuNTU3IDM2Ny4zOTcsMC44MDNDMzY0LjU2MiwyLjE2MyAzNjIuNzU5LDUuMDI2IDM2Mi43NTksOC4xN0wzNjIuNzU5LDQwLjMwNkwzMjcuMzU1LDQwLjMwNkMyOTMuNzExLDQwLjMwNiAyNTkuNDQzLDUyLjMxMiAyMzAuODYyLDc0LjExMkMyMDIuMjgyLDk1LjkxMiAxODEuNjQyLDEyNS43ODggMTcyLjc0NywxNTguMjM2TDE1NC40MiwyMjUuMDk4TDE0NS43MjMsMTkzLjM3QzE0My4xNCwxODMuOTUgMTI5LjA1OCwxNzMuMjA4IDExOS4yODksMTczLjIwOEwxNi4zNDEsMTczLjIwOEwxNi4zNDEsNTYuNjQ3TDExOS4yODYsNTYuNjQ3QzE0NC4zOSw1Ni42NDcgMTY5Ljc5MSw2NC4wNyAxOTIuNzQzLDc4LjExNUMxOTYuNTkyLDgwLjQ2OSAyMDEuNjIsNzkuMjU4IDIwMy45NzYsNzUuNDExQzIwNi4zMzEsNzEuNTYyIDIwNS4xMiw2Ni41MzMgMjAxLjI3MSw2NC4xNzZDMTc1Ljc1Miw0OC41NiAxNDcuNDAyLDQwLjMwNiAxMTkuMjg2LDQwLjMwNkw4LjE3MSw0MC4zMDZDMy42NTksNDAuMzA2IDAuMDAwOTk5NDUxLDQzLjk2NCAwLjAwMDk5OTQ1MSw0OC40NzZMMC4wMDA5OTk0NTEsMTgxLjM3OEMwLjAwMDk5OTQ1MSwxODUuODkxIDMuNjU5LDE4OS41NDggOC4xNzEsMTg5LjU0OEwxMTkuMjA3LDE4OS41NDZDMTIxLjk2MiwxODkuNzk5IDEyOS4wMTIsMTk1LjE3NyAxMjkuOTYyLDE5Ny42OTFMMTQ1Ljk0NiwyNTYuMDAyTDEyOS45ODUsMzE0LjIzM0MxMjkuMDEyLDMxNi44MjIgMTIxLjk2MiwzMjIuMTk5IDExOS4yODYsMzIyLjQ1MUw4LjE3MSwzMjIuNDUxQzMuNjU5LDMyMi40NTEgMC4wMDA5OTk0NTEsMzI2LjEwOCAwLjAwMDk5OTQ1MSwzMzAuNjIxTDAuMDAwOTk5NDUxLDQ2My41MjNDMC4wMDA5OTk0NTEsNDY4LjAzNiAzLjY1OSw0NzEuNjkzIDguMTcxLDQ3MS42OTNMMTE5LjI4Niw0NzEuNjkzQzE1Mi45Myw0NzEuNjkzIDE4Ny4xOTgsNDU5LjY4NyAyMTUuNzc5LDQzNy44ODdDMjQ0LjM1OSw0MTYuMDg3IDI2NC45OTksMzg2LjIxMSAyNzMuODk0LDM1My43NjNMMjg4LjgwNiwyOTkuMzYzTDMxNi42NTUsMTk3Ljc2OEwzMTYuNjU1LDE5Ny43NjhaTTIwNS44NjksNDI0Ljg5NkMxODAuMTE5LDQ0NC41MzcgMTQ5LjM2OSw0NTUuMzUzIDExOS4yODUsNDU1LjM1M0wxNi4zNDEsNDU1LjM1M0wxNi4zNDEsMzM4Ljc5MkwxMTkuMjg2LDMzOC43OTJDMTI5LjA1NSwzMzguNzkyIDE0My4xMzgsMzI4LjA1MSAxNDUuNzIyLDMxOC42MjhMMTg4LjUwNiwxNjIuNTU1QzE5Ni40NTksMTMzLjU0MiAyMTUuMDIyLDEwNi43NDcgMjQwLjc3Miw4Ny4xMDRDMjY2LjUyMSw2Ny40NjUgMjk3LjI3MSw1Ni42NDggMzI3LjM1NCw1Ni42NDhMMzcwLjkyOCw1Ni42NDhDMzc1LjQ0LDU2LjY0OCAzNzkuMDk4LDUyLjk5MSAzNzkuMDk4LDQ4LjQ3OEwzNzkuMDk4LDI1LjIxNEw0OTAuNzg0LDExNC45MjhMMzc5LjA5OCwyMDQuNjQzTDM3OS4wOTgsMTgxLjM3OUMzNzkuMDk4LDE3Ni44NjYgMzc1LjQ0LDE3My4yMDkgMzcwLjkyOCwxNzMuMjA5TDMyNy4zNTQsMTczLjIwOUMzMTcuNTg1LDE3My4yMDkgMzAzLjUwMiwxODMuOTUgMzAwLjkxOCwxOTMuMzczTDI1OC4xMzUsMzQ5LjQ0NkMyNTAuMTgxLDM3OC40NTggMjMxLjYxOSw0MDUuMjU0IDIwNS44NjksNDI0Ljg5NkwyMDUuODY5LDQyNC44OTZaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0yMTAuODIzLDgwLjYwOUMxODMuNjU4LDU5Ljg4OSAxNTEuMTQ5LDQ4LjQ3NyAxMTkuMjg1LDQ4LjQ3N0w4LjE3MSw0OC40NzdMOC4xNzEsMTgxLjM3OUwxMTkuMjg2LDE4MS4zNzlDMTI1LjMyMSwxODEuMzc5IDEzNi4yNDUsMTg5LjcxMiAxMzcuODQxLDE5NS41MzJMMTgwLjYyNSwzNTEuNjA1TDI2Ni4wMTUsMTYwLjM5N0MyNTcuNTksMTI5LjY2NiAyMzcuOTksMTAxLjMzMSAyMTAuODIzLDgwLjYwOUwyMTAuODIzLDgwLjYwOVoiIGZpbGw9IiNGRUZGRkYiIGZpbGwtb3BhY2l0eT0iMCIvPgo8cGF0aCBkPSJNNTAzLjgzLDExNC45MjhMMzcwLjkyOCwyMjEuNjg2TDQyNy41NzUsMTE0LjkyOEwzNzAuOTI4LDguMTcxTDUwMy44MywxMTQuOTI4WiIgZmlsbD0iI0ZGRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjxwYXRoIGQ9Ik00NjAuMjU2LDM5Ny4wNzNMMzcwLjkyOCwyOTAuMzE2TDM3MC45MjgsMzMwLjYyMkwzMjcuMzU0LDMzMC42MjJDMzIxLjcsMzMwLjYyMiAzMTEuNzY1LDMyMy4zMTIgMzA5LjIxNiwzMTcuNjE1TDI0OS42MzksNDQwLjg0NEMyNzMuNjcsNDU1LjU2MSAzMDAuNzMsNDYzLjUyNSAzMjcuMzU0LDQ2My41MjVMMzcwLjkyOCw0NjMuNTI1TDM3MC45MjgsNTAzLjgzMUw0NjAuMjU2LDM5Ny4wNzNMNDYwLjI1NiwzOTcuMDczWiIgZmlsbD0iI0ZFRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjxwYXRoIGQ9Ik0zMDkuMjE2LDMxNy42MTVMMjk3LjUyNywzNjAuMjQyQzI4OS4zMzUsMzkwLjE0NSAyNzIuNjM1LDQxOC4wNzYgMjQ5LjYzOSw0NDAuODQ0QzI0NC45LDQzNy45NTcgMjQwLjI4MSw0MzQuNzk4IDIzNS44MTUsNDMxLjM4OEMyMDguNjQ2LDQxMC42NjggMTg5LjA0OSwzODIuMzM0IDE4MC42MjgsMzUxLjYwM0wyNjYuMDEyLDE2MC4zOThMMzA4LjgwMiwzMTYuNDcxQzMwOC45LDMxNi44NDIgMzA5LjA0MSwzMTcuMjIzIDMwOS4yMTYsMzE3LjYxNUwzMDkuMjE2LDMxNy42MTVaIiBmaWxsPSIjRkZGRkZGIiBmaWxsLW9wYWNpdHk9IjAiLz4KPHBhdGggZD0iTTQ2MC4yNTYsMTE0LjkyOEwzNzAuOTI4LDguMTcxTDM3MC45MjgsNDguNDc3TDMyNy4zNTQsNDguNDc3QzI5NS40OSw0OC40NzcgMjYyLjk4MSw1OS44ODkgMjM1LjgxNiw4MC42MDlDMjA4LjY0OSwxMDEuMzMgMTg5LjA1LDEyOS42NjUgMTgwLjYyNiwxNjAuMzk2TDEzNy44NDIsMzE2LjQ2OUMxMzYuMjQ2LDMyMi4yODkgMTI1LjMyMSwzMzAuNjIyIDExOS4yODcsMzMwLjYyMkw4LjE3MSwzMzAuNjIyTDguMTcxLDQ2My41MjRMMTE5LjI4Niw0NjMuNTI0QzE1MS4xNSw0NjMuNTI0IDE4My42NTksNDUyLjExMiAyMTAuODI0LDQzMS4zOTJDMjM3Ljk5MSw0MTAuNjcxIDI1Ny41OSwzODIuMzM2IDI2Ni4wMTQsMzUxLjYwNUwzMDguNzk4LDE5NS41MzJDMzEwLjM5NCwxODkuNzEyIDMyMS4zMTksMTgxLjM3OSAzMjcuMzUzLDE4MS4zNzlMMzcwLjkyNywxODEuMzc5TDM3MC45MjcsMjIxLjY4NUw0NjAuMjU2LDExNC45MjhMNDYwLjI1NiwxMTQuOTI4WiIgZmlsbD0iI0ZGRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjwvZz4KPC9zdmc+Cg==");
  if(name === "prev") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTIyLDE4LjM0MjlMMTMuMjU3MSwxMi4xNzE0TDIyLDZMMjIsMTguMzQyOUwyMiwxOC4zNDI5WiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNNC41Mjg1NSwxMi4xNzE0TDEzLjI3MTUsMTguMzQyOUwxMy4yNzE1LDZMNC41Mjg1NSwxMi4xNzE0TDQuNTI4NTUsMTIuMTcxNFpNNC41Mjg1NSwxMi4xNzE0TDQuNTI4NTUsNkwyLjUyODU1LDZMMi41Mjg1NSwxOEw0LjUyODU1LDE4TDQuNTI4NTUsMTIuMTcxNEw0LjUyODU1LDEyLjE3MTRaIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiIGZpbGw9IiNGRkZGRkYiLz4KPC9nPgo8L3N2Zz4K");
  if(name === "next") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTIuNTI4NTUsMTguMzQyOUwxMS4yNzE1LDEyLjE3MTRMMi41Mjg1NSw2TDIuNTI4NTUsMTguMzQyOUwyLjUyODU1LDE4LjM0MjlaIiBmaWxsPSIjRkZGRkZGIi8+CjxwYXRoIGQ9Ik0yMCwxMi4xNzE0TDExLjI1NzEsMTguMzQyOUwxMS4yNTcxLDZMMjAsMTIuMTcxNEwyMCwxMi4xNzE0Wk0yMCwxMi4xNzE0TDIwLDZMMjIsNkwyMiwxOEwyMCwxOEwyMCwxMi4xNzE0TDIwLDEyLjE3MTRaIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiIGZpbGw9IiNGRkZGRkYiLz4KPC9nPgo8L3N2Zz4K");
  if(name === "back15") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMzIsMzIiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDMyIDMyOyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTEuMDA3LDEuNDEyQzEuMjUzLDEuNDEyIDEuNTAzLDEuNTAzIDEuNzA3LDEuNzA3TDQuNjg2LDQuNjg2QzcuNTgyLDEuNzkxIDExLjU4MiwwIDE2LDBDMjQuODM3LDAgMzIsNy4xNjMgMzIsMTZDMzIsMjQuODM3IDI0LjgzNywzMiAxNiwzMkM3LjE2MywzMiAwLDI0LjgzNyAwLDE2QzAsMTUuMzIxIDAsMi40MTQgMCwyLjQxNEMwLDEuODExIDAuNDkzLDEuNDEyIDEuMDA3LDEuNDEyTDEuMDA3LDEuNDEyWk0yLDEzTDEwLjA4NiwxM0w2LjE3Nyw5LjEyOEM4LjM1LDYuMDMyIDExLjkzOSw0IDE2LDRDMjIuNjE3LDQgMjgsOS4zODMgMjgsMTZDMjgsMjIuNjE3IDIyLjYxNywyOCAxNiwyOEM5LjM4MywyOCA0LDIyLjYxNyA0LDE2QzQsMTUuMzIzIDQuMDgxLDE0LjY0NSA0LjE5MywxNEwyLDE0TDIsMTZDMiwyMy43MiA4LjI4LDMwIDE2LDMwQzIzLjcyLDMwIDMwLDIzLjcyIDMwLDE2QzMwLDguMjggMjMuNzIsMiAxNiwyQzEyLjI2LDIgOC43NDUsMy40NTYgNi4xMDEsNi4xTDQuNjg3LDcuNTE0TDIsNC44MjhMMiwxM0wyLDEzWk0xMS4yOTMsMTRMNS4xOTEsMTRDNS4wNzEsMTQuNjQyIDUsMTUuMzIzIDUsMTZDNSwyMi4wNzUgOS45MjUsMjcgMTYsMjdDMjIuMDc1LDI3IDI3LDIyLjA3NSAyNywxNkMyNyw5LjkyNSAyMi4wNzUsNSAxNiw1QzEyLjU3NCw1IDkuNTI2LDYuNTc1IDcuNTA5LDkuMDNMMTEuNjQ3LDEzLjE0NkMxMS45NjEsMTMuNDYxIDExLjczOCwxNCAxMS4yOTMsMTRMMTEuMjkzLDE0WiIgZmlsbD0iI0ZGRkZGRiIvPgo8L2c+Cjwvc3ZnPgo=");
  if(name === "forward15") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMzIsMzIiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDMyIDMyOyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMwLjk5MywxLjQxMkMzMC43NDcsMS40MTIgMzAuNDk3LDEuNTAzIDMwLjI5MywxLjcwN0wyNy4zMTQsNC42ODZDMjQuNDE4LDEuNzkxIDIwLjQxOCwwIDE2LDBDNy4xNjMsMCAwLDcuMTYzIDAsMTZDMCwyNC44MzcgNy4xNjMsMzIgMTYsMzJDMjQuODM3LDMyIDMyLDI0LjgzNyAzMiwxNkMzMiwxNS4zMjEgMzIsMi40MTQgMzIsMi40MTRDMzIsMS44MTEgMzEuNTA3LDEuNDEyIDMwLjk5MywxLjQxMkwzMC45OTMsMS40MTJaTTMwLDEzTDIxLjkxNCwxM0wyNS44MjMsOS4xMjhDMjMuNjUsNi4wMzIgMjAuMDYxLDQgMTYsNEM5LjM4Myw0IDQsOS4zODMgNCwxNkM0LDIyLjYxNyA5LjM4MywyOCAxNiwyOEMyMi42MTcsMjggMjgsMjIuNjE3IDI4LDE2QzI4LDE1LjMyMyAyNy45MTksMTQuNjQ1IDI3LjgwNywxNEwzMCwxNEwzMCwxNkMzMCwyMy43MiAyMy43MiwzMCAxNiwzMEM4LjI4LDMwIDIsMjMuNzIgMiwxNkMyLDguMjggOC4yOCwyIDE2LDJDMTkuNzQsMiAyMy4yNTUsMy40NTYgMjUuODk5LDYuMUwyNy4zMTMsNy41MTRMMzAsNC44MjhMMzAsMTNMMzAsMTNaTTIwLjcwNywxNEwyNi44MDksMTRDMjYuOTI5LDE0LjY0MiAyNywxNS4zMjMgMjcsMTZDMjcsMjIuMDc1IDIyLjA3NSwyNyAxNiwyN0M5LjkyNSwyNyA1LDIyLjA3NSA1LDE2QzUsOS45MjUgOS45MjUsNSAxNiw1QzE5LjQyNiw1IDIyLjQ3NCw2LjU3NSAyNC40OTEsOS4wM0wyMC4zNTMsMTMuMTQ2QzIwLjAzOSwxMy40NjEgMjAuMjYyLDE0IDIwLjcwNywxNEwyMC43MDcsMTRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==");
  return '';
}

function setWheelLabelContent(el, html){
  try{ if(el) el.innerHTML = html || ""; }catch(e){}
}

function updateWheelLabels(){
  try{
    const lMenu = document.querySelector(".wheelLabel.wlTop, .wheelLabel.top");
    const lRev = document.querySelector(".wheelLabel.wlLeft, .wheelLabel.wlRev");
    const lFwd = document.querySelector(".wheelLabel.wlRight, .wheelLabel.wlFwd");
    const lPlay = document.querySelector(".wheelLabel.wlBottom, .wheelLabel.wlPlay");
    if(!lMenu || !lRev || !lFwd || !lPlay) return;

    if(state.current && state.current.kind === "np_playlist_add"){
      setWheelLabelContent(lMenu, "");
      setWheelLabelContent(lRev, "");
      setWheelLabelContent(lFwd, "");
      setWheelLabelContent(lPlay, "");
      lPlay.style.whiteSpace = "";
      lPlay.style.lineHeight = "";
      lPlay.style.fontSize = "";
      return;
    }

    if(nowPlaying.style.display === "block" && seekMode){
      if(!isVideoActive() && lastfmIsEnabled()){
        setWheelLabelContent(lMenu, wheelLabelSvg("heart", !!(lastfmState.lovedKnown && lastfmState.loved)));
      }else{
        setWheelLabelContent(lMenu, wheelLabelSvg("menu"));
      }
      setWheelLabelContent(lRev, wheelLabelSvg("back15"));
      setWheelLabelContent(lFwd, wheelLabelSvg("forward15"));
      if(isVideoActive()){
        const m = wheelMedia();
        setWheelLabelContent(lPlay, wheelLabelSvg((m && m.paused) ? "play" : "pause", !(m && m.paused)));
        lPlay.style.whiteSpace = "";
        lPlay.style.lineHeight = "";
        lPlay.style.fontSize = "";
      }else{
        setWheelLabelContent(lPlay, wheelLabelSvg("shuffle", !!state.shuffleEnabled));
        lPlay.style.whiteSpace = "";
        lPlay.style.lineHeight = "";
        lPlay.style.fontSize = "";
      }
    }else{
      setWheelLabelContent(lMenu, wheelLabelSvg("menu"));
      setWheelLabelContent(lRev, wheelLabelSvg("prev"));
      setWheelLabelContent(lFwd, wheelLabelSvg("next"));
      if(nowPlaying.style.display === "block"){
        const m = wheelMedia();
        setWheelLabelContent(lPlay, wheelLabelSvg((m && m.paused) ? "play" : "pause", !(m && m.paused)));
      }else if(state.now){
        const m = wheelMedia();
        const isPaused = m ? !!m.paused : !(state.serverNow && state.serverNow.playing);
        setWheelLabelContent(lPlay, wheelLabelSvg(isPaused ? "play" : "pause", !isPaused));
      }else{
        setWheelLabelContent(lPlay, wheelLabelSvg("play", false));
      }
      lPlay.style.whiteSpace = "";
      lPlay.style.lineHeight = "";
      lPlay.style.fontSize = "";
    }
  }catch(e){}
}



function adjustSeekPreview(dir){
  const m = wheelMedia();
  const d = (m && m.duration) ? m.duration : 0;
  if(d <= 0) return;
  const step = Math.max(2, d / 200);
  seekPreview = Math.max(0, Math.min(d, (seekPreview || 0) + (dir * step)));
  seekChanged = true;
  updateSeekIndicator();
  resetSeekIdle();
}




function scheduleVideoResume(targetSec){
  try{
    const tgtRaw = Number(targetSec || 0);
    if(!(tgtRaw > 0)) return;
    if(!npVideo) return;

    const startedAt = Date.now();
    const maxMs = 15000;
    let fallbackUsed = false;

    const clampTarget = ()=>{
      const d = (npVideo && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0;
      if(!(d > 0)) return null;
      const t = Math.min(Math.max(0, tgtRaw), Math.max(0, d - 0.5));
      return t;
    };

    const attempt = ()=>{
      try{
        if(!npVideo) return;
        if(Date.now() - startedAt > maxMs) return;

        const t = clampTarget();
        if(t === null){
          setTimeout(attempt, 200);
          return;
        }

        const cur = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
        if(Math.abs(cur - t) <= 1.5){
          return;
        }

        // Try direct seek first
        try{ npVideo.currentTime = t; }catch(e){}

        setTimeout(()=>{
          try{
            const cur2 = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
            if(Math.abs(cur2 - t) > 2.0 && !fallbackUsed){
              fallbackUsed = true;
              try{ resumeVideoViaSeekInputs(t); }catch(e){}
            }
          }catch(e){}
        }, 350);

        setTimeout(attempt, 800);
      }catch(e){}
    };

    // Trigger on key readiness events too
    try{
      const h = ()=>{ setTimeout(attempt, 0); };
      npVideo.addEventListener("loadedmetadata", h, {once:true});
      npVideo.addEventListener("loadeddata", h, {once:true});
      npVideo.addEventListener("canplay", h, {once:true});
      npVideo.addEventListener("canplaythrough", h, {once:true});
    }catch(e){}

    setTimeout(attempt, 250);
    setTimeout(attempt, 900);
  }catch(e){}
}

function resumeVideoViaSeekInputs(targetSec){
  try{
    if(!isVideoActive() || !npVideo) return;
    if(nowPlaying.style.display !== "block"){
      try{ showNowPlaying(true); }catch(e){}
    }

    // Ensure a clean seek mode state
    try{ if(seekMode) cancelSeekMode(); }catch(e){}

    // Enter seek mode using the same path as a center press
    try{ centerPress(); }catch(e){ try{ enterSeekMode(); }catch(e2){} }
    if(!seekMode){
      try{ enterSeekMode(); }catch(e){}
    }

    // Start preview from the actual current playback position for this video
    try{
      seekPreview = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
    }catch(e){ seekPreview = 0; }

    const startMs = Date.now();
    const maxMs = 120000;

    const tick = ()=>{
      try{
        if(!isVideoActive() || !npVideo) return;

        const d = (npVideo && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0;
        if(!(d > 0)){
          if(Date.now() - startMs < maxMs){
            setTimeout(tick, 60);
          }else{
            try{ cancelSeekMode(); }catch(e){}
          }
          return;
        }

        const tgt = Math.min(Math.max(0, Number(targetSec || 0)), Math.max(0, d - 0.5));
        const stepSec = Math.max(2, d / 200);

        if(!(isFinite(seekPreview))){
          seekPreview = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
        }

        let diff = tgt - (seekPreview || 0);
        if(Math.abs(diff) <= (stepSec / 2)){
          try{ centerPress(); }catch(e){ try{ commitSeekMode(); }catch(e2){} }
          try{ npVideo.play(); }catch(e){}
          return;
        }

        const dir = diff > 0 ? 1 : -1;

        // Simulate fast wheel rotation by applying many seek preview steps per tick
        const maxStepsPerTick = 120;
        const steps = Math.max(1, Math.min(maxStepsPerTick, Math.floor(Math.abs(diff) / stepSec)));

        for(let i = 0; i < steps; i++){
          adjustSeekPreview(dir);
        }

        // Continue until close enough, then commit via center press
        if(Date.now() - startMs < maxMs){
          setTimeout(tick, 10);
        }else{
          try{ cancelSeekMode(); }catch(e){}
        }
      }catch(e){
        try{ cancelSeekMode(); }catch(e2){}
      }
    };

    // Give the video a moment to start so seeking behaves like real user input
    setTimeout(tick, 250);
  }catch(e){}
}



function setVolume(v){
  userVol = Math.max(0, Math.min(1, v));
  try{ localStorage.setItem("debripod_volume", String(userVol)); }catch(e){}
  applyVolume();
}

function adjustVolumeStep(dir){
  const step = 0.03;
  setVolume(userVol + (dir * step));
  if(nowPlaying.style.display === "block" && !seekMode){
    showVolumeBar();
    scheduleHideVolumeBar();
    npPillActivity(false);
  }
}

applyVolume();

function fmtTime(sec){
    sec = Math.max(0, sec || 0);
    const m = Math.floor(sec/60);
    const s = Math.floor(sec%60);
    return m + ":" + (s<10 ? "0"+s : s);
  }

  function swapAudios(){
    activeAudio = audioMain;
    standbyAudio = null;
  }

  function canMediaSession(){
    return !!(navigator.mediaSession && window.MediaMetadata);
  }

  function ensurePlaybackAudioSession(){
    try{
      if("audioSession" in navigator && navigator.audioSession){
        if(navigator.audioSession.type !== "playback") navigator.audioSession.type = "playback";
      }
    }catch(e){}
  }

  function mediaSessionHasPrev(){
    try{
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && prevVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && prevIndexPeek() !== null);
    }catch(e){ return false; }
  }

  function mediaSessionHasNext(){
    try{
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && nextVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && nextIndexPeek() !== null);
    }catch(e){ return false; }
  }

  function syncMediaSessionPosition(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    if(!ms || typeof ms.setPositionState !== "function") return;
    try{
      const m = isVideoActive() ? npVideo : activeAudio;
      if(!m) return;
      const d = Number(m.duration || 0);
      const t = Number(m.currentTime || 0);
      const rate = Number(m.playbackRate || 1) || 1;
      if(!(d > 0) || !isFinite(d) || !isFinite(t) || !isFinite(rate)) return;
      ms.setPositionState({
        duration: d,
        playbackRate: rate,
        position: Math.max(0, Math.min(t, d))
      });
    }catch(e){}
  }

  function updateMediaSession(meta){
    if(!canMediaSession()) return;
    try{
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        artwork: meta.art ? [{src: meta.art, sizes: "400x400", type: "image/jpeg"}] : []
      });
    }catch(e){}
    try{ syncMediaSessionControls(); }catch(e){}
    try{ syncMediaSessionPosition(); }catch(e){}
  }

  function setMediaActionHandler(name, handler){
    if(!canMediaSession()) return;
    try{ navigator.mediaSession.setActionHandler(name, handler); }catch(e){}
  }

  function syncMediaSessionControls(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    try{
      ms.playbackState = ((isVideoActive() ? npVideo : activeAudio) && !(isVideoActive() ? npVideo : activeAudio).paused) ? "playing" : "paused";
    }catch(e){}
    setMediaActionHandler("play", ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ npVideo.play().catch(()=>{}); }catch(e){}
        return;
      }
      try{ if(standbyAudio && !standbyAudio.paused) standbyAudio.pause(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ activeAudio.play().catch(()=>{}); }catch(e){}
    });
    setMediaActionHandler("pause", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("stop", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("seekbackward", null);
    setMediaActionHandler("seekforward", null);
    setMediaActionHandler("seekto", null);
    setMediaActionHandler("previoustrack", mediaSessionHasPrev() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ playVideoPrev(); }catch(e){}
      }else{
        try{ playPrev(); }catch(e){}
      }
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
    setMediaActionHandler("nexttrack", mediaSessionHasNext() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ playVideoNext(); }catch(e){}
      }else{
        try{ playNext(); }catch(e){}
      }
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
  }
  syncMediaSessionControls();

  // Last.fm scrobbling
  const lastfmState = {
    key: "",
    startTs: 0,
    duration: 0,
    meta: null,
    sentNow: false,
    sentScrobble: false,
    lovedKnown: false,
    loved: false
  };

  function lastfmIsEnabled(){
    return !!state.lastfmEnabled;
  }

  function lastfmTrackKey(meta){
    const a = (meta && meta.artist ? meta.artist : "").trim().toLowerCase();
    const t = (meta && meta.title ? meta.title : "").trim().toLowerCase();
    const b = (meta && meta.album ? meta.album : "").trim().toLowerCase();
    return a + "\n" + t + "\n" + b;
  }

  async function lastfmPost(path, payload){
    if(!lastfmIsEnabled()) return;
    try{
      await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        keepalive: true
      });
    }catch(e){}
  }

  async function lastfmGetLoved(meta){
    if(!lastfmIsEnabled()) return;
    try{
      const a = encodeURIComponent((meta && meta.artist) ? meta.artist : "");
      const t = encodeURIComponent((meta && meta.title) ? meta.title : "");
      const b = encodeURIComponent((meta && meta.album) ? meta.album : "");
      if(!a || !t) return;
      const js = await apiGet("/api/lastfm/loved?artist=" + a + "&title=" + t + "&album=" + b);
      if(js && js.ok){
        lastfmState.loved = !!js.loved;
        lastfmState.lovedKnown = true;
        updateWheelLabels();
      }
    }catch(e){}
  }

  async function lastfmToggleLoved(meta){
    if(!lastfmIsEnabled()) return;
    let prevKnown = false;
    let prevLoved = false;
    let havePrev = false;
    try{
      const artist = (meta && meta.artist) ? meta.artist : "";
      const title = (meta && meta.title) ? meta.title : "";
      const album = (meta && meta.album) ? meta.album : "";
      if(!artist.trim() || !title.trim()) return;

      prevKnown = !!lastfmState.lovedKnown;
      prevLoved = !!lastfmState.loved;
      havePrev = true;

      // Optimistic flip so the UI responds immediately.
      const optimistic = prevKnown ? (!prevLoved) : true;
      lastfmState.loved = optimistic;
      lastfmState.lovedKnown = true;
      updateWheelLabels();

      const res = await apiPost("/api/lastfm/toggle_loved", {artist: artist, title: title, album: album});
      const js = (res && res.json) ? res.json : null;

      if(res && res.ok && js && js.ok){
        lastfmState.loved = !!js.loved;
        lastfmState.lovedKnown = true;
        updateWheelLabels();

        // Reconcile after propagation and any metadata normalization differences.
        setTimeout(()=>{ lastfmGetLoved(meta); }, 1500);
      }else{
        // Revert if server rejected.
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }catch(e){
      if(havePrev){
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }
  }

  // Server-side playback sync (Now Playing + Recently Played)
  async function playbackPost(payload){
    try{
      await fetch("/api/playback/update", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        cache: "no-store",
        keepalive: true
      });
    }catch(e){}
  }

  async function syncPlaybackFromServer(){
    try{
      const js = await apiGet("/api/playback/snapshot");
      state.serverNow = (js && js.now) ? js.now : null;
      state.serverRecent = (js && Array.isArray(js.recent)) ? js.recent : [];
      state.serverLoaded = true;
      if(state.serverNow && state.serverNow.root_id && state.serverNow.rel){
        state.now = {rootId: state.serverNow.root_id, rel: state.serverNow.rel, media: state.serverNow.media || "", streamed: !!state.serverNow.streamed};
      }else{
        // keep local state.now if it exists; otherwise clear
        if(!state.now) state.now = null;
      }
    }catch(e){
      state.serverLoaded = false;
    }
  }

  function nowBadgeText(){
    try{
      if(isVideoActive()){
        return (npVideo && !npVideo.paused) ? "playing" : "";
      }
      if(activeAudio && !activeAudio.paused){
        return "playing";
      }
      if(state.serverNow && state.serverNow.playing){
        return "playing";
      }
      return "";
    }catch(e){
      return "";
    }
  }

  function captureNavContext(){
    const nav = {};
    try{
      if(state.root && state.root.id){
        nav.root_id = state.root.id;
        nav.root_name = state.root.name || "";
      }
      if(state.current && state.current.kind){
        nav.kind = state.current.kind;
        nav.label = state.current.label || "";
        if(state.current.kind === "folder"){
          nav.rel = state.current.rel || "";
        }else if(state.current.kind === "metatop"){
          // nothing extra
        }else if(state.current.kind === "metalist"){
          nav.level = state.current.level || "";
          nav.value = state.current.value || "";
        }
      }
      // if we're on now playing screen, try to use the last non-now view for better restore
      if(nowPlaying && nowPlaying.style.display === "block" && state.history && state.history.length){
        const v = state.history[state.history.length - 1];
        if(v && v.kind){
          nav.kind = v.kind;
          nav.label = v.label || nav.label || "";
          if(v.kind === "folder") nav.rel = v.rel || "";
          if(v.kind === "metalist"){ nav.level = v.level || ""; nav.value = v.value || ""; }
        }
      }
    }catch(e){}
    return nav;
  }

  async function openNavContext(nav){
    try{
      if(!nav || !nav.root_id){
        return;
      }
      const cfg = await loadConfig();
      const root = (cfg.roots || []).find(r => r.id === nav.root_id);
      if(!root) return;

      state.root = root;
      state.history = [];
      state.current = null;

      if(nav.kind === "folder"){
        const rel = (nav.rel || "").trim();
        if(rel){
          const segs = rel.split("/");
          state.history.push(folderViewObj(root, "", ""));
          for(let i = 0; i < segs.length - 1; i++){
            const r = segs.slice(0, i + 1).join("/");
            state.history.push(folderViewObj(root, r, segs[i]));
          }
        }
        showNowPlaying(false);
        await setView(folderViewObj(root, rel, rel ? rel.split("/").slice(-1)[0] : ""), false);
        return;
      }

      if((root.mode || "folders") === "metadata"){
        if(nav.kind === "metalist" && nav.level){
          await viewMetaList(root, nav.level, nav.value || "", nav.label || nav.level, false);
          return;
        }
        await viewMetaTop(root, false);
        return;
      }

      // fallback
      await viewFolder(root, "", "", false);
    }catch(e){}
  }

  function lastfmSendNowPlaying(){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentNow) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    lastfmState.sentNow = true;
    lastfmPost("/api/lastfm/nowplaying", {
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      duration: (lastfmState.duration && isFinite(lastfmState.duration)) ? Math.round(lastfmState.duration) : null
    });
  }

  function lastfmOnTrack(meta){
    if(!lastfmIsEnabled()) return;
    if(!meta) return;
    const k = lastfmTrackKey(meta);
    if(!k.trim()) return;
    if(k !== lastfmState.key){
      lastfmState.key = k;
      lastfmState.startTs = Math.floor(Date.now()/1000);
      lastfmState.sentNow = false;
      lastfmState.sentScrobble = false;
      lastfmState.lovedKnown = false;
      lastfmState.loved = false;
      lastfmGetLoved(meta);
    }
    lastfmState.meta = meta;
    const d0 = (meta.duration && isFinite(meta.duration)) ? meta.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    lastfmState.duration = d;
    lastfmSendNowPlaying();
  }

  function lastfmMaybeScrobble(force){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentScrobble) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    const d0 = (lastfmState.duration && isFinite(lastfmState.duration)) ? lastfmState.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    if(!(d > 0)) return;
    if(d < 30) return;
    const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
    const need = Math.min(240, d * 0.5);
    if(force || t >= need){
      lastfmState.sentScrobble = true;
      lastfmPost("/api/lastfm/scrobble", {
        title: m.title || "",
        artist: m.artist || "",
        album: m.album || "",
        duration: Math.round(d),
        start_ts: lastfmState.startTs || Math.floor(Date.now()/1000)
      });
    }
  }

  const state = {
    root: null,
    roots: [],
    history: [],
    current: null,
    rootView: null,
    items: [],
    sel: 0,
    playlist: [],
    playIndex: -1,
    videoPlaylist: [],
    videoIndex: -1,
    now: null,
    libSearch: {q: "", filter: "", engine: "combined", cache_key: "", result_source: "combined", last_count: 0, results: [], knaben_results: [], slsk_users: [], editField: "", editValue: ""},
    playlistCreate: {editing: false, editValue: "", submitting: false},
    playlistEdit: {rel: "", label: "", editingName: false, editNameValue: "", submitting: false},
    libTasks: {tasks: []},
    pendingLibSearch: null,
    nowMeta: null,
    serverNow: null,
    serverRecent: [],
    serverLoaded: false,
    lastfmEnabled: false,
    preloadEnabled: true,
    preloadBytes: 2097152,
    shuffleEnabled: false,
    playOrder: null,
    orderPos: 0,
    playOrderPlaylist: null,
    preloadedIndex: null,
    visualizerEnabled: visualizerEnabled,
    streamQueue: [],
    streamQueueIndex: -1
  };

  let npPlaylistReturnView = null;

  try{
    state.shuffleEnabled = (localStorage.getItem("debripod_shuffle") === "1");
  }catch(e){ state.shuffleEnabled = false; }
  applyThemeVars(defaultTheme);
  updateVisualizerState();

  let playbackLastPostTs = 0;
  let playbackLastPos = -1;
  function playbackMaybePost(media, rootId, rel, metaObj, pos, dur, playing, ev){
    const nowTs = Date.now();
    const p = (pos && isFinite(pos)) ? Number(pos) : 0;
    if(ev === "time"){
      if(nowTs - playbackLastPostTs < 2000 && Math.abs(p - playbackLastPos) < 1.0) return;
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }else{
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }
    const m = metaObj || {};

    // include the current playback playlist context so next/prev works when restoring from server state
    let playlistCtx = null;
    try{
      if(media === "audio" && Array.isArray(state.playlist) && state.playlist.length){
        const items = state.playlist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: String(it.media || "audio"),
          label: it.label || "",
          streamed: !!it.streamed,
          source: it.source || "",
          ext: it.ext || "",
          quality: it.quality || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
      }else if(media === "video" && Array.isArray(state.videoPlaylist) && state.videoPlaylist.length){
        const items = state.videoPlaylist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: String(it.media || "video"),
          label: it.label || "",
          streamed: !!it.streamed,
          source: it.source || "",
          ext: it.ext || "",
          quality: it.quality || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.videoIndex >= 0 ? state.videoIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }
    playbackPost({
      media: media,
      root_id: rootId,
      rel: rel,
      playlist: playlistCtx,
      label: m.label || "",
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      art: m.art || "",
      position: p,
      duration: (dur && isFinite(dur)) ? Number(dur) : null,
      playing: !!playing,
      nav: captureNavContext(),
      event: ev || "time",
      streamed: !!m.streamed,
      source: m.source || "",
      ext: m.ext || "",
      quality: m.quality || ""
    });
  }


  function layoutNowPlayingToLibList(){
    try{
      const screen = document.querySelector(".ipodScreen");
      if(!screen || !nowPlaying || !libList) return;
      const sr = screen.getBoundingClientRect();
      const lr = libList.getBoundingClientRect();
      const pad = 2; // keep libList border visible
      const left = (lr.left - sr.left) + pad;
      const top = (lr.top - sr.top) + pad;
      const w = lr.width - (pad * 2);
      const h = lr.height - (pad * 2);
      nowPlaying.style.left = Math.max(0, left) + "px";
      nowPlaying.style.top = Math.max(0, top) + "px";
      nowPlaying.style.width = Math.max(0, w) + "px";
      nowPlaying.style.height = Math.max(0, h) + "px";
      nowPlaying.style.right = "auto";
      nowPlaying.style.bottom = "auto";
      nowPlaying.style.borderRadius = "20px";
    }catch(e){}
  }

  function resetNowPlayingLayout(){
    try{
      if(!nowPlaying) return;
      nowPlaying.style.left = "";
      nowPlaying.style.top = "";
      nowPlaying.style.width = "";
      nowPlaying.style.height = "";
      nowPlaying.style.right = "";
      nowPlaying.style.bottom = "";
      nowPlaying.style.borderRadius = "";
    }catch(e){}
  }

  function waitNowPlayingFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  function showNowPlaying(on){
    const fadeMs = 220;
    try{ if(libList) libList.style.display = "block"; }catch(e){}
    try{
      if(npPageFadeTimer){
        clearTimeout(npPageFadeTimer);
        npPageFadeTimer = null;
      }
    }catch(e){}
    npPageFadeToken += 1;
    const fadeToken = npPageFadeToken;

    if(on){
      try{ libList.classList.add("npUnderlay"); }catch(e){}
      layoutNowPlayingToLibList();
      nowPlaying.style.display = "block";
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      updateVisualizerState();
      requestAnimationFrame(()=>{
        requestAnimationFrame(()=>{
          try{
            if(fadeToken !== npPageFadeToken) return;
            nowPlaying.classList.add("npPageActive");
          }catch(e){}
        });
      });
      npPillActivity(false);
    }else{
      try{ libList.classList.remove("npUnderlay"); }catch(e){}
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      npPageFadeTimer = setTimeout(()=>{
        try{
          if(fadeToken !== npPageFadeToken) return;
          nowPlaying.style.display = "none";
          resetNowPlayingLayout();
          if(npOverlayPill) npOverlayPill.classList.add("npPillHidden");
        }catch(e){}
        npPageFadeTimer = null;
      }, fadeMs);
      try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
      npPillHideTimer = null;
    }
    if(!on){
      stopVideoOverlay();
      try{ if(volBarTimer) clearTimeout(volBarTimer); }catch(e){}
      volBarTimer = null;
    }
    cancelSeekMode();
    showProgressBar();
  }

  function syncWheelZoneHeight(){
    try{
      const wrapEl = document.getElementById("divwrap") || document.querySelector(".wrap");
      const screenEl = document.querySelector("#tab-library .ipodScreen");
      const wheelZoneEl = document.getElementById("wheelZone") || document.querySelector("#tab-library .wheelZone");
      if(!wrapEl || !screenEl || !wheelZoneEl) return;
      const wrapRect = wrapEl.getBoundingClientRect();
      const screenRect = screenEl.getBoundingClientRect();
      const rootStyle = getComputedStyle(document.documentElement);
      const wheelSize = parseFloat(rootStyle.getPropertyValue("--wheelSize")) || 0;
      const wheelGap = parseFloat(rootStyle.getPropertyValue("--wheelGap")) || 0;
      const minNeeded = Math.ceil(wheelSize + (wheelGap * 2));
      const available = Math.max(0, Math.round(wrapRect.bottom - screenRect.bottom));
      const target = Math.max(available, minNeeded);
      wheelZoneEl.style.height = target + "px";
      wheelZoneEl.style.minHeight = target + "px";
      wheelZoneEl.style.flex = "0 0 " + target + "px";
    }catch(e){}
  }


  window.addEventListener("resize", ()=>{
    try{ syncWheelZoneHeight(); }catch(e){}
    try{
      if(nowPlaying && nowPlaying.style.display === "block"){
        layoutNowPlayingToLibList();
      }
    }catch(e){}
  });

  function bringToNowPlayingIfPlaying(){
    if(!state.now) return;
    if(activeAudio && !activeAudio.paused){
      setTab("library");
      showNowPlaying(true);
    }
  }

  window.addEventListener("focus", bringToNowPlayingIfPlaying);
  document.addEventListener("visibilitychange", ()=>{
    if(document.hidden){
      try{ saveResumeNowPlaying(); }catch(e){}
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
    }else{
      bringToNowPlayingIfPlaying();
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
    }
  });

  window.addEventListener("pagehide", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  window.addEventListener("beforeunload", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  function saveResumeNowPlaying(){
    if(!state.now) return;
    try{
      localStorage.setItem("debripod_tab", "library");
      localStorage.setItem("debripod_resume_np", JSON.stringify({rootId: state.now.rootId, rel: state.now.rel, playing: (activeAudio && !activeAudio.paused), ts: Date.now()}));
    }catch(e){}
  }

  function encodeRel(rel){
    return (rel||"").split("\\").join("/").split("/").map(encodeURIComponent).join("/");
  }

  function escapeHtml(s){
    const str = String(s ?? "");
    return str
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }


  async function apiGet(url){
    const r = await fetch(url, {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  }

  async function loadConfig(){
    const js = await apiGet("/api/library/config");
        state.preloadEnabled = !!js.preload_enabled;
    state.preloadBytes = js.preload_bytes || state.preloadBytes;
    state.roots = js.roots || [];
    state.lastfmEnabled = !!js.lastfm_enabled;
    return js;
  }

  function headerText(){
    const parts = [];
    if(state.root && state.root.name) parts.push(state.root.name);
    for(const v of state.history){
      if(v && v.label) parts.push(v.label);
    }
    if(state.current && state.current.label) parts.push(state.current.label);
    return parts.length ? parts.join(" > ") : "Library";
  }

  function setHeader(){
    libHeader.textContent = headerText();
    try{ pathPillActivity(false); }catch(e){}
    try{
      const k = state.current ? state.current.kind : "";
      if(k !== "libsearch" && k !== "libsearch_files"){
        libControlsHide();
      }
    }catch(e){}
  }

  function beginPlaylistCreateEdit(){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      if(state.playlistCreate.submitting) return;
      state.playlistCreate.editing = true;
      if(typeof state.playlistCreate.editValue !== "string") state.playlistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  function beginSmartPlaylistCreateEdit(){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      if(state.smartPlaylistCreate.submitting) return;
      state.smartPlaylistCreate.editing = true;
      if(typeof state.smartPlaylistCreate.editValue !== "string") state.smartPlaylistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  async function closeNowPlayingPlaylistMode(){
    try{
      const prev = npPlaylistReturnView;
      npPlaylistReturnView = null;
      if(prev){
        await runLibraryPageTransition(async ()=>{
          state.current = prev;
          setHeader();
          await prev.load();
        });
      }
    }catch(e){}
    showNowPlaying(true);
    updateWheelLabels();
  }

  async function addCurrentNowPlayingTrackToPlaylist(playlistRel){
    const cur = state.current || {};
    const root = cur.root || null;
    const trackRel = String(cur.trackRel || "");
    const rel = String(playlistRel || "");
    if(!root || !root.id || !trackRel || !rel) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: rel, tracks: [trackRel]});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      if(js && js.error && String(js.error) === "No songs added"){
        return true;
      }
      throw new Error((js && js.error) ? js.error : "Failed to add song");
    }
    return true;
  }

  async function viewNowPlayingPlaylistMode(){
    const currentNow = state.now || null;
    const currentMedia = String((currentNow && currentNow.media) || (isVideoActive() ? "video" : "audio"));
    if(!currentNow || currentMedia !== "audio" || !currentNow.rootId || !currentNow.rel){
      return;
    }
    let root = null;
    try{
      if(!state.roots || !state.roots.length){
        await loadConfig();
      }
      root = (state.roots || []).find(r => r && r.id === currentNow.rootId) || null;
    }catch(e){ root = null; }
    if(!root) return;
    const alreadyInMode = !!(state.current && state.current.kind === "np_playlist_add");
    const existingAdded = (state.current && state.current.kind === "np_playlist_add" && state.current._added instanceof Set) ? state.current._added : new Set();
    if(!alreadyInMode){
      snapshotListState();
      npPlaylistReturnView = state.current || null;
    }
    const view = {
      kind: "np_playlist_add",
      label: "Add to playlist",
      root: root,
      trackRel: String(currentNow.rel || ""),
      _added: existingAdded,
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlists&value=");
        const items = [
          {kind:"np_playlist_close", label:"Close"},
          {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"}
        ];
        const all = Array.isArray(js.items) ? js.items : [];
        const playlistItems = all.filter(it => it && String(it.kind || "") === "playlist" && !it.smart);
        for(const it of playlistItems){
          const rel = String(it.rel || "");
          const added = !!(this._added && this._added.has(rel));
          items.push({
            kind:"np_playlist_entry",
            label:String(it.label || "Playlist"),
            rel:rel,
            root:root,
            selectable:true,
            selected:added,
            pills:[{text: added ? "âœ“" : "+", _selectPill:true}]
          });
        }
        if(!playlistItems.length){
          items.push({kind:"info", label:"No playlists found"});
        }
        resetList(items);
      }
    };
    state.current = view;
    setHeader();
    resetList([
      {kind:"np_playlist_close", label:"Close"},
      {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"},
      {kind:"info", label:"Loading playlists..."}
    ]);
    showNowPlaying(false);
    await runLibraryPageTransition(async ()=>{
      await view.load();
    });
    updateWheelLabels();
  }

  async function submitPlaylistCreate(rawName){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.playlistCreate.submitting = false;
        return;
      }
      state.playlistCreate.submitting = true;
      const res = await apiPost("/api/library/playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistCreate.submitting = false;
      state.playlistCreate.editing = false;
      state.playlistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        try{
          const wantRel = String(js.rel || "");
          if(wantRel){
            const idx = state.items.findIndex(x => x && x.kind === "np_playlist_entry" && x.rel === wantRel);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){}
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.playlistCreate.submitting = false; }catch(e2){}
      try{ state.playlistCreate.editing = false; state.playlistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function submitSmartPlaylistCreate(rawName){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.smartPlaylistCreate.submitting = false;
        return;
      }
      state.smartPlaylistCreate.submitting = true;
      const res = await apiPost("/api/library/smart_playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistCreate.submitting = false;
      state.smartPlaylistCreate.editing = false;
      state.smartPlaylistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error) alert(String(js.error));
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.smartPlaylistCreate.submitting = false; }catch(e2){}
      try{ state.smartPlaylistCreate.editing = false; state.smartPlaylistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  function isSmartPlaylistRel(rel){
    const v = String(rel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").toLowerCase();
    return v === "debripod-smartplaylists" || v.startsWith("debripod-smartplaylists/");
  }

  async function viewSmartPlaylistRules(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "smart_playlist_rules",
      label: "Edit rules",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        const js = await apiGet("/api/library/smart_playlist_rules?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.playlistRel || ""));
        if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
        state.smartPlaylistRules.text = String(js.text || "");
        state.smartPlaylistRules.saving = false;
        resetList([
          {kind:"smart_playlist_rules_text", label:"Rules"},
          {kind:"smart_playlist_rules_save", label:"Save rules"},
          {kind:"smart_playlist_rules_cancel", label:"Back"},
          {kind:"smart_playlist_rules_delete", label:"Delete playlist"}
        ]);
      }
    }, !!push);
  }

  async function saveSmartPlaylistRules(){
    const cur = state.current || {};
    if(cur.kind !== "smart_playlist_rules" || !cur.root || !cur.root.id) return;
    if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
    state.smartPlaylistRules.saving = true;
    try{
      const res = await apiPost("/api/library/smart_playlist_rules", {root_id: cur.root.id, rel: cur.playlistRel || "", text: String(state.smartPlaylistRules.text || "")});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistRules.saving = false;
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to save rules"));
        renderList();
        return;
      }
      await goBack();
    }catch(e){
      state.smartPlaylistRules.saving = false;
      alert(String(e && e.message ? e.message : e));
      try{ renderList(); }catch(e2){}
    }
  }


  function beginPlaylistRenameEdit(){
    try{
      const cur = state.current || {};
      if(cur.kind !== "playlist_edit_menu") return;
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      if(state.playlistEdit.submitting) return;
      state.playlistEdit.rel = String(cur.playlistRel || state.playlistEdit.rel || "");
      state.playlistEdit.label = String(cur.playlistLabel || state.playlistEdit.label || "");
      state.playlistEdit.editingName = true;
      if(typeof state.playlistEdit.editNameValue !== "string" || !state.playlistEdit.editNameValue){
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
      }
      renderList();
    }catch(e){}
  }

  async function submitPlaylistRename(rawName){
    try{
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      const cur = state.current || {};
      const root = cur.root || null;
      const playlistRel = String(cur.playlistRel || state.playlistEdit.rel || "");
      const name = String(rawName || "").trim();
      if(!root || !root.id || !playlistRel){
        state.playlistEdit.submitting = false;
        return;
      }
      state.playlistEdit.submitting = true;
      const res = await apiPost("/api/library/playlist_rename", {root_id: root.id, rel: playlistRel, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistEdit.submitting = false;
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      const newRel = String(js.rel || playlistRel);
      const newLabel = String(js.label || name || state.playlistEdit.label || "Playlist");
      state.playlistEdit.rel = newRel;
      state.playlistEdit.label = newLabel;
      state.playlistEdit.editNameValue = newLabel;
      state.playlistEdit.editingName = false;
      if(state.current && state.current.kind === "playlist_edit_menu"){
        state.current.playlistRel = newRel;
        state.current.playlistLabel = newLabel;
      }
      try{
        for(const h of (state.history || [])){
          if(h && h.kind === "metalist" && h.level === "playlist_tracks" && String(h.value || "") === playlistRel){
            h.value = newRel;
            h.label = newLabel;
          }
        }
      }catch(e){}
      renderList();
    }catch(e){
      try{ state.playlistEdit.submitting = false; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function viewPlaylistEditMenu(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_edit_menu",
      label: "Edit",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
        state.playlistEdit.rel = String(this.playlistRel || "");
        state.playlistEdit.label = String(this.playlistLabel || "");
        state.playlistEdit.editingName = false;
        state.playlistEdit.submitting = false;
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
        if(isSmartPlaylistRel(this.playlistRel || "")){
          resetList([
            {kind:"smart_playlist_rules_entry", label:"Edit rules"}
          ]);
        }else{
          resetList([
            {kind:"playlist_edit_name", label:"Edit name"},
            {kind:"playlist_edit_add", label:"Add songs"},
            {kind:"playlist_edit_remove", label:"Remove songs"},
            {kind:"playlist_edit_delete", label:"Delete playlist"}
          ]);
        }
      }
    }, !!push);
  }



  async function viewPlaylistDeleteConfirm(root, playlistRel, playlistLabel, returnKind, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_delete_confirm",
      label: "Delete",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      returnKind: returnKind || "",
      load: async function(){
        resetList([
          {kind:"info", label:"Are you sure?"},
          {kind:"playlist_delete_no", label:"No"},
          {kind:"playlist_delete_yes", label:"Yes"}
        ]);
      }
    }, !!push);
  }

  async function confirmDeletePlaylist(){
    const cur = state.current || {};
    if(cur.kind !== "playlist_delete_confirm" || !cur.root || !cur.root.id) return;
    try{
      const res = await apiPost("/api/library/playlist_delete", {root_id: cur.root.id, rel: cur.playlistRel || ""});
      const js = (res && res.json) ? res.json : {};
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to delete playlist"));
        return;
      }
      state.history = [];
      await viewMetaList(cur.root, "playlists", "", "Playlists", false);
    }catch(e){
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function playlistAddSongsToCurrentView(rels){
    const cur = state.current || {};
    const root = cur.root || null;
    const playlistRel = String(cur.playlistRel || "");
    if(!root || !root.id || !playlistRel) return false;
    const clean = Array.isArray(rels) ? rels.map(x=>String(x || "")).filter(Boolean) : [];
    if(!clean.length) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: playlistRel, tracks: clean});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      throw new Error((js && js.error) ? js.error : "Failed to add songs");
    }
    return true;
  }


  function playlistBrowseStartRel(playlistRel){
    const rel = String(playlistRel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if(!rel) return "";
    const lower = rel.toLowerCase();
    if(lower === "debripod-playlists" || lower.startsWith("debripod-playlists/") || lower === "debripod-smartplaylists" || lower.startsWith("debripod-smartplaylists/")){
      return "";
    }
    const idx = rel.lastIndexOf("/");
    if(idx < 0) return "";
    const out = rel.slice(0, idx).replace(/^\/+|\/+$/g, "");
    if(!out || out.toLowerCase() === "debripod-playlists") return "";
    return out;
  }

  async function viewPlaylistAddSongs(root, playlistRel, rel, push){
    showNowPlaying(false);
    const prevAdded = (state.current && state.current.kind === "playlist_add" && state.current._added instanceof Set) ? state.current._added : null;
    await setView({
      kind: "playlist_add",
      label: "Add songs",
      root: root,
      playlistRel: playlistRel || "",
      rel: rel || "",
      _added: prevAdded || new Set(),
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel || "");
        const js = await apiGet(url);
        const items = [];
        if(this.rel){
          items.push({kind:"up", label:".."});
        }
        const dirs = [];
        const songs = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            dirs.push({kind:"playlist_add_dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file" && e.media === "audio"){
            const relv = String(e.rel || "");
            const added = !!(this._added && this._added.has(relv));
            songs.push({kind:"playlist_add_file", label:e.name, rel:relv, root:root, media:"audio", selectable:true, selected:added});
          }
        }
        if(songs.length){
          const addedCount = songs.filter(x => x && x.selected).length;
          items.push({kind:"playlist_add_selectall", label:"Select all", badge: addedCount ? (String(addedCount) + " added") : String(songs.length)});
        }
        for(const d of dirs) items.push(d);
        for(const s of songs) items.push(s);
        if(!dirs.length && !songs.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function refreshPlaylistRemoveSelectionUI(){
    const cur = state.current || {};
    if(!cur || cur.kind !== "playlist_remove") return;
    const selected = (cur.selected instanceof Set) ? cur.selected : new Set();
    let trackCount = 0;
    let selectedCount = 0;
    for(const it of (state.items || [])){
      if(!it) continue;
      if(it.kind === "playlist_remove_track"){
        trackCount += 1;
        const relv = String(it.rel || "");
        const on = !!(relv && selected.has(relv));
        it.selected = on;
        if(on) selectedCount += 1;
      }else if(it.kind === "playlist_remove_selectall"){
        it.badge = selectedCount ? String(selectedCount) : (trackCount ? String(trackCount) : "");
      }else if(it.kind === "playlist_remove_commit"){
        it.badge = selectedCount ? String(selectedCount) : "";
      }
    }
    renderList();
  }

  async function viewPlaylistRemoveSongs(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    const prevSelected = (state.current && state.current.kind === "playlist_remove" && state.current.selected instanceof Set) ? state.current.selected : null;
    await setView({
      kind: "playlist_remove",
      label: "Remove songs",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      selected: prevSelected || new Set(),
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlist_tracks&value=" + encodeURIComponent(this.playlistRel || ""));
        const items = [];
        const tracks = [];
        for(const it of (js.items || [])){
          if(!it || it.kind !== "track") continue;
          const relv = String(it.rel || "");
          tracks.push({kind:"playlist_remove_track", label:String(it.label || "Track"), rel:relv, root:root, badge:String(it.badge || ""), selectable:true, selected:!!(this.selected && this.selected.has(relv))});
        }
        if(tracks.length){
          items.push({kind:"playlist_remove_selectall", label:"Select all", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
          items.push({kind:"playlist_remove_commit", label:"Remove selected", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
        }
        for(const tr of tracks) items.push(tr);
        if(!tracks.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function renderList(){
    const prevScroll = (libList ? libList.scrollTop : 0);
    let editInputToFocus = null;
    libList.innerHTML = "";
    for(let i=0;i<state.items.length;i++){
      const it = state.items[i];
      const li = document.createElement("li");

      const isSel = (i === state.sel);
      const twoLine = (it.kind === "libsearch_result" || it.kind === "libsearch_file" || it.kind === "libtask_file");
      li.className = "ipodItem" + (isSel ? " sel" : "") + (it.kind === "info" ? " info" : "") + (it.kind === "random" ? " random" : "") + (twoLine ? " twoLine" : "");

      if(it.kind === "smart_playlist_rules_text"){
        li.className += " editing";
        const ta = document.createElement("textarea");
        ta.className = "libInlineInput";
        ta.style.minHeight = "220px";
        ta.style.height = "220px";
        ta.style.whiteSpace = "pre";
        ta.value = (state.smartPlaylistRules && typeof state.smartPlaylistRules.text === "string") ? state.smartPlaylistRules.text : "";
        ta.placeholder = "Enter smart playlist rules";
        ta.addEventListener("input", ()=>{
          try{
            if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
            state.smartPlaylistRules.text = ta.value || "";
          }catch(e){}
        });
        li.appendChild(ta);
        editInputToFocus = ta;
        libList.appendChild(li);
        continue;
      }

      // Special inline input rows for Library search query/filter and playlist creation
      if(it.kind === "libsearch_query" || it.kind === "libsearch_filter" || it.kind === "playlist_create" || it.kind === "smart_playlist_create" || it.kind === "playlist_edit_name"){
        const isPlaylistCreate = (it.kind === "playlist_create");
        const isSmartPlaylistCreate = (it.kind === "smart_playlist_create");
        const isPlaylistRename = (it.kind === "playlist_edit_name");
        const field = (isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename) ? "name" : ((it.kind === "libsearch_filter") ? "filter" : "q");
        const placeholder = isPlaylistCreate ? "Create playlist" : (isSmartPlaylistCreate ? "Create smart playlist" : (isPlaylistRename ? "Edit name" : ((it.kind === "libsearch_filter") ? "Enter filters" : "Enter query")));
        const isEditing = (isPlaylistCreate || isSmartPlaylistCreate)
          ? !!(isSel && (isSmartPlaylistCreate ? state.smartPlaylistCreate : state.playlistCreate) && (isSmartPlaylistCreate ? state.smartPlaylistCreate.editing : state.playlistCreate.editing))
          : (isPlaylistRename ? !!(isSel && state.playlistEdit && state.playlistEdit.editingName) : !!(isSel && state.libSearch && state.libSearch.editField === field));
        if(isEditing){
          li.className += " editing";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.className = "libInlineInput";
          inp.value = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : "")
                : ((state.libSearch && typeof state.libSearch.editValue === "string") ? state.libSearch.editValue : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : ""))));
          inp.placeholder = placeholder;
          inp.addEventListener("input", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                state.playlistCreate.editValue = inp.value || "";
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                state.smartPlaylistCreate.editValue = inp.value || "";
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                state.playlistEdit.editNameValue = inp.value || "";
              }else{
                if(!state.libSearch) return;
                state.libSearch.editValue = inp.value || "";
                state.libSearch[field] = inp.value || "";
              }
            }catch(e){}
          });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitSmartPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editNameValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistRename(inp.value || ""); }catch(e){}
              }else{
                try{
                  if(state.libSearch){
                    state.libSearch.editValue = inp.value || "";
                    state.libSearch[field] = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                if(field === "q") {
                  try{ libDoSearch((state.libSearch && state.libSearch.engine) ? state.libSearch.engine : "combined", inp.value || ""); }catch(e){}
                }
              }
              return;
            }
            if(ev.key === "Escape"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editing = false;
                    state.playlistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editing = false;
                    state.smartPlaylistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editingName = false;
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else{
                try{ inp.blur(); }catch(e){}
              }
              return;
            }
          });
          inp.addEventListener("blur", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                if(state.playlistCreate.editing){
                  state.playlistCreate.editing = false;
                  state.playlistCreate.editValue = "";
                }
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                if(state.smartPlaylistCreate.editing){
                  state.smartPlaylistCreate.editing = false;
                  state.smartPlaylistCreate.editValue = "";
                }
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                if(state.playlistEdit.editingName){
                  state.playlistEdit.editingName = false;
                  if(!state.playlistEdit.submitting){
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }
              }else{
                if(!state.libSearch) return;
                state.libSearch[field] = inp.value || "";
                if(state.libSearch.editField === field){
                  state.libSearch.editField = "";
                  state.libSearch.editValue = "";
                }
              }
            }catch(e){}
            try{
              if(isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename){
                renderList();
              }else if(field === "filter"){
                libRefreshList(true);
              }else{
                renderList();
              }
            }catch(e){}
          });
          li.appendChild(inp);
          editInputToFocus = inp;
        }else{
          const labelSpan = document.createElement("span");
          labelSpan.className = "ipodLabel";
          const v = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : ((state.playlistEdit && state.playlistEdit.label) ? state.playlistEdit.label : ""))
                : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : "")));
          labelSpan.textContent = (v && v.trim()) ? v : placeholder;
          li.appendChild(labelSpan);

          const wrap = document.createElement("span");
          wrap.className = "ipodPills";
          const sp = document.createElement("span");
          sp.className = "ipodPill" + ((!isPlaylistCreate && !isPlaylistRename && field === "q") ? " v" : "");
          sp.textContent = isPlaylistCreate ? "New" : (isSmartPlaylistCreate ? "Smart" : (isPlaylistRename ? "Name" : ((field === "q") ? "Query" : "Filters")));
          wrap.appendChild(sp);
          // extra pills (status etc.)
          if(Array.isArray(it.pills)){
            for(const p of it.pills){
              if(!p) continue;
              const sp2 = document.createElement("span");
              if(typeof p === "string"){
                sp2.className = "ipodPill";
                sp2.textContent = p;
              }else{
                const tone = String(p.tone || "");
                sp2.className = "ipodPill" + (tone ? (" " + tone) : "");
                sp2.textContent = String(p.text || "");
              }
              wrap.appendChild(sp2);
            }
          }
          li.appendChild(wrap);
        }

        li.addEventListener("click", ()=>{
          const wasSel = (state.sel === i);
          state.sel = i;
          if(isPlaylistCreate){
            if(wasSel) beginPlaylistCreateEdit();
            else renderList();
          }else if(isSmartPlaylistCreate){
            if(wasSel) beginSmartPlaylistCreateEdit();
            else renderList();
          }else if(isPlaylistRename){
            if(wasSel) beginPlaylistRenameEdit();
            else renderList();
          }else if(!(state.libSearch && state.libSearch.editField === field)){
            renderList();
          }
        });

        libList.appendChild(li);
        continue;
      }

      const labelWrap = document.createElement("span");
      labelWrap.className = "ipodLabelWrap";
      const labelSpan = document.createElement("span");
      labelSpan.className = "ipodLabel";
      if(it && it.label_html){
        labelSpan.innerHTML = String(it.label_html || "");
      }else if(it && it.kind === "album") {
        let rendered = false;
        try{
          const raw = (typeof it.value === "string") ? JSON.parse(it.value) : (it.value || {});
          const artist = String((raw && raw.artist) || "").trim();
          const album = String((raw && raw.album) || "").trim();
          if(artist && album){
            labelSpan.innerHTML = escapeHtml(album) + '   ' + '<span class="artistStrong">' + escapeHtml(artist) + '</span>';
            rendered = true;
          }
        }catch(e){}
        if(!rendered) labelSpan.textContent = it.label || "";
      }else{
        labelSpan.textContent = it.label || "";
      }
      labelWrap.appendChild(labelSpan);
      if(it && it.sub_label){
        const sub = document.createElement("span");
        sub.className = "ipodSubLabel";
        sub.textContent = String(it.sub_label || "");
        labelWrap.appendChild(sub);
      }
      li.appendChild(labelWrap);

      const pills = [];
      if(Array.isArray(it.pills)){
        for(const p of it.pills){
          if(!p) continue;
          if(typeof p === "string"){
            pills.push({text: p, tone: "", bar: null});
          }else if(typeof p === "object"){
            const bar = (p.bar != null && isFinite(Number(p.bar))) ? Math.max(0, Math.min(1, Number(p.bar))) : null;
            pills.push({text: String(p.text || ""), tone: String(p.tone || ""), bar: bar});
          }
        }
      }
      if(it.badge){
        pills.push({text: String(it.badge), tone: "warn"});
      }

      if(it.selectable){
        pills.push({text: it.selected ? "Selected" : "Select", tone: it.selected ? "ok" : "" , _selectPill: true});
      }

      if(pills.length){
        const wrap = document.createElement("span");
        wrap.className = "ipodPills";
        for(const p of pills){
          const sp = document.createElement("span");
          const toneCls = p.tone ? (" " + p.tone) : "";
          if(p.bar != null && isFinite(Number(p.bar))){
            sp.className = "ipodPill bar" + toneCls;
            const fill = document.createElement("span");
            fill.className = "pillBarFill";
            fill.style.width = (Math.max(0, Math.min(1, Number(p.bar))) * 100).toFixed(1) + "%";
            const txt = document.createElement("span");
            txt.className = "pillBarText";
            txt.textContent = p.text || "";
            sp.appendChild(fill);
            sp.appendChild(txt);
          }else{
            sp.className = "ipodPill" + toneCls;
            sp.textContent = p.text || "";
          }
          if(p._selectPill){
            sp.addEventListener("click", (ev)=>{
              ev.preventDefault();
              ev.stopPropagation();
              state.sel = i;
              try{
                if(it.kind === "playlist_add_file"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(it.kind === "np_playlist_entry"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(it.kind === "playlist_remove_track"){
                  const cur = state.current || {};
                  if(!cur.selected) cur.selected = new Set();
                  const rp = String(it.rel || "");
                  if(rp){
                    if(cur.selected.has(rp)) cur.selected.delete(rp);
                    else cur.selected.add(rp);
                  }
                  const act = viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(typeof it.onToggle === "function"){
                  it.onToggle();
                }else{
                  it.selected = !it.selected;
                }
              }catch(e){}
              renderList();
            });
          }
          wrap.appendChild(sp);
        }
        li.appendChild(wrap);
      }

      li.addEventListener("click", ()=>{
        state.sel = i;
        renderList();
        try{
          const p = selectItem(it);
          if(p && typeof p.catch === "function"){ p.catch(()=>{}); }
        }catch(e){}
      });
      libList.appendChild(li);
    }
    if(state.items.length === 0){
      const li = document.createElement("li");
      li.className = "ipodItem info";
      li.textContent = "Empty";
      libList.appendChild(li);
    }

    // restore scroll position first, then ensure selection is visible without jumping to top
    try{
      if(libList) libList.scrollTop = prevScroll;
    }catch(e){}
    const selEl = libList.querySelector(".ipodItem.sel");
    if(selEl){
      selEl.scrollIntoView({block: "nearest"});
    }
    if(editInputToFocus){
      try{
        editInputToFocus.focus();
        editInputToFocus.click();
        const n = editInputToFocus.value.length;
        editInputToFocus.setSelectionRange(n, n);
      }catch(e){}
    }
  }

function vibeTick(){
  try{
    if(navigator && typeof navigator.vibrate === "function"){
      navigator.vibrate(8);
    }
  }catch(e){}
}

// ===== library actions (reindex, last.fm auth, forced fullscreen) =====
  let forceFullscreen = false;

  async function doLibraryReindex(){
    try{
      await fetch("/api/library/reindex", {method: "POST"});
      return true;
    }catch(e){
      alert("Reindex failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function getAnyIndexBuilding(){
    try{
      const js = await apiGet("/api/library/building");
      return !!(js && js.ok && js.any_building);
    }catch(e){
      return false;
    }
  }

  async function startLastfmLoginFlow(){
    let token = null;
    let authUrl = null;

    try{
      const r = await fetch("/api/lastfm/auth/start", {method: "GET"});
      const j = await r.json();
      if(!j || !j.ok){
        throw new Error((j && j.error) ? j.error : "Last.fm auth start failed");
      }
      token = j.token;
      authUrl = j.auth_url;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }

    try{
      if(authUrl){
        window.open(authUrl, "_blank", "noopener");
      }
    }catch(e){}

    let proceed = true;
    try{
      proceed = confirm("A Last.fm approval page was opened. After you approve Debripod, click OK to finish login.");
    }catch(e){}

    if(!proceed){
      return false;
    }

    try{
      const r2 = await fetch("/api/lastfm/auth/finish", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token: token})
      });
      const j2 = await r2.json();
      if(!j2 || !j2.ok){
        throw new Error((j2 && j2.error) ? j2.error : "Last.fm auth finish failed");
      }
      alert("Last.fm login complete.");
      return true;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function forceFullscreenOn(){
    forceFullscreen = true;
    try{
      if(!document.fullscreenElement && document.documentElement && document.documentElement.requestFullscreen){
        await document.documentElement.requestFullscreen();
      }
    }catch(e){}
  }

  document.addEventListener("fullscreenchange", ()=>{
    if(forceFullscreen && !document.fullscreenElement){
      setTimeout(async ()=>{
        if(forceFullscreen && !document.fullscreenElement){
          try{
            if(document.documentElement && document.documentElement.requestFullscreen){
              await document.documentElement.requestFullscreen();
            }
          }catch(e){}
        }
      }, 150);
    }
  });
;


  function scrollSel(delta){
    if(!state.items.length) return;
    const n = state.items.length;
    const prev = state.sel;
    state.sel = Math.max(0, Math.min(n - 1, state.sel + delta));
    if(state.sel !== prev){
      try{
        if(state.playlistCreate) state.playlistCreate.editing = false;
        if(state.smartPlaylistCreate) state.smartPlaylistCreate.editing = false;
        if(state.playlistEdit) state.playlistEdit.editingName = false;
        if(state.libSearch && state.libSearch.editField) state.libSearch.editField = "";
      }catch(e){}
      vibeTick();
    }
    renderList();
  }

  function _randomEligibleItem(it){
    if(!it) return false;
    const k = (it.kind || "");
    if(!k) return false;
    if(k === "info" || k === "up" || k === "random" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry") return false;
    return true;
  }

  function _shouldAddRandom(items){
    try{
      if(!state.current) return false;
      const vk = state.current.kind || "";
      // Remove Random from the top-level Browse screen
      if(vk !== "folder" && vk !== "metalist") return false;

      // Remove Random from individual album tracklists
      if(vk === "metalist" && (state.current.level || "") === "tracks") return false;

      for(const it of (items || [])){
        if(_randomEligibleItem(it)) return true;
      }
      return false;
    }catch(e){
      return false;
    }
  }

  function resetList(items){
    const arr = Array.isArray(items) ? items.slice() : [];
    if(_shouldAddRandom(arr)){
      const btn = {kind:"random", label:"Random"};
      let insertAt = 0;
      while(insertAt < arr.length){
        const k = (arr[insertAt] && arr[insertAt].kind) ? arr[insertAt].kind : "";
        if(k === "up" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry"){
          insertAt += 1;
          continue;
        }
        break;
      }
      arr.splice(insertAt, 0, btn);
    }
    state.items = arr;

    // Restore selection and scroll when returning to a list via Menu/back
    let restoreSel = null;
    let restoreScroll = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; }

    if(restoreSel != null){
      const max = Math.max(0, arr.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }
  }

  function snapshotListState(){
    try{
      if(state.current){
        state.current.savedSel = state.sel;
        if(libList) state.current.savedScroll = libList.scrollTop;
      }
    }catch(e){}
  }

  function waitLibPageFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  async function runLibraryPageTransition(loadFn){
    try{
      if(libList){
        libList.classList.add("pageFadeHidden");
        await waitLibPageFade(220);
      }
      await loadFn();
      if(libList){
        requestAnimationFrame(()=>{
          requestAnimationFrame(()=>{
            try{ libList.classList.remove("pageFadeHidden"); }catch(e){}
          });
        });
      }
    }catch(e){
      try{ if(libList) libList.classList.remove("pageFadeHidden"); }catch(_e){}
      throw e;
    }
  }

  async function setView(view, push){
    await runLibraryPageTransition(async ()=>{
      if(push && state.current){
        snapshotListState();
        state.history.push(state.current);
      }
      state.current = view;
      setHeader();
      await view.load();
    });
  }

  function rootViewObj(){
    return {
      kind: "roots",
      label: "",
      savedSel: 0,
      savedScroll: 0,
      load: async function(){
        await showRoots(false);
      }
    };
  }

  async function showRoots(resetHistory){
    const shouldResetHistory = (resetHistory !== false);
    showNowPlaying(false);
    const cfg = await loadConfig();
    await syncPlaybackFromServer();
    state.root = null;
    if(shouldResetHistory){
      state.history = [];
    }
    if(!state.rootView){
      state.rootView = rootViewObj();
    }
    state.current = state.rootView;
    const items = [{kind:"libsearch_entry", label:"Search"},{kind:"libtasks_entry", label:"Tasks"}].concat((cfg.roots||[]).map(r=>({kind:"root", label:r.name, root:r})));
    if(state.now || state.serverNow){
      items.push({kind:"nowplaying", label:"Now Playing"});
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }else{
      // show Recently Played only if there is history (even without now playing)
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }
    items.push({kind:"libinfo_entry", label:"Info"});
    resetList(items);
  }


  
  

  function libControlsHide(){}

  function libControlsShow(html){}

  function libSetStatus(msg, tone){
    try{
      if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[]};
      state.libSearch.status_msg = msg ? String(msg) : "";
      state.libSearch.status_tone = tone ? String(tone) : "";
    }catch(e){}
    // legacy element (if present)
    const el = document.getElementById("libSearchStatus");
    if(!el) return;
    if(!msg){
      el.style.display = "none";
      el.textContent = "";
      el.className = "ipodPill";
      return;
    }
    el.style.display = "inline-flex";
    el.textContent = String(msg);
    el.className = "ipodPill" + (tone ? (" " + tone) : "");
  }

  function libSetFileStatus(msg, tone){
    const view = state.current || null;
    if(view){
      view._fileStatus = msg ? String(msg) : "";
      view._fileStatusTone = tone ? String(tone) : "";
      const target = (view._searchResult || view._rd || view._slsk || view._slskbrowse || null);
      if(target && typeof target.buildItems === "function"){
        try{ libSearchRebuildFilesList(target.buildItems()); }catch(e){}
      }
    }
  }

  function libParseFilter(q){
    const s = String(q || "").trim().toLowerCase();
    const tokens = s.split(/\s+/).filter(Boolean);

    const out = {exts: new Set(), bitDepth: 0, sampleRate: 0, source: "", rest: []};

    for(const t of tokens){
      if(t === "source:knaben" || t === "src:knaben"){ out.source = "knaben"; continue; }
      else if(t === "source:soulseek" || t === "src:soulseek" || t === "source:slsk" || t === "src:slsk"){ out.source = "soulseek"; continue; }
      else if(t === "source:youtube" || t === "src:youtube" || t === "source:yt" || t === "src:yt"){ out.source = "youtube"; continue; }
      else if(t === "source:combined" || t === "src:combined"){ out.source = "combined"; continue; }
      if(t === "flac" || t === ".flac") out.exts.add("flac");
      else if(t === "mp3" || t === ".mp3") out.exts.add("mp3");
      else if(t === "m4a" || t === ".m4a") out.exts.add("m4a");
      else if(t === "aac" || t === ".aac") out.exts.add("aac");
      else if(t === "ogg" || t === ".ogg") out.exts.add("ogg");
      else if(t === "wav" || t === ".wav") out.exts.add("wav");
      else if(t === "alac" || t === ".alac") out.exts.add("alac");
      else if(t === "opus" || t === ".opus") out.exts.add("opus");
      else if(t === "16" || t === "16bit" || t === "16-bit") out.bitDepth = 16;
      else if(t === "24" || t === "24bit" || t === "24-bit") out.bitDepth = 24;
      else if(t === "32" || t === "32bit" || t === "32-bit") out.bitDepth = 32;
      else if(t === "44" || t === "44.1" || t === "44100" || t === "44khz" || t === "44.1khz") out.sampleRate = 44100;
      else if(t === "48" || t === "48000" || t === "48khz") out.sampleRate = 48000;
      else if(t === "88" || t === "88.2" || t === "88200" || t === "88khz" || t === "88.2khz") out.sampleRate = 88200;
      else if(t === "96" || t === "96000" || t === "96khz") out.sampleRate = 96000;
      else if(t === "176" || t === "176.4" || t === "176khz" || t === "176.4khz") out.sampleRate = 176400;
      else if(t === "192" || t === "192000" || t === "192khz") out.sampleRate = 192000;
      else out.rest.push(t);
    }
    return out;
  }

  function libTextHasAllTokens(text, tokens){
    const t = String(text || "").toLowerCase();
    for(const x of (tokens || [])){
      if(!x) continue;
      if(!t.includes(x)) return false;
    }
    return true;
  }

  function libGuessFromName(name){
    const s = String(name || "").toLowerCase();
    const mExt = s.match(/\.([a-z0-9]{2,5})$/);
    const ext = mExt ? mExt[1] : "";
    let bd = 0;
    let sr = 0;
    if(/\b24\s*bit\b/.test(s) || /\b24bit\b/.test(s)) bd = 24;
    else if(/\b16\s*bit\b/.test(s) || /\b16bit\b/.test(s)) bd = 16;
    else if(/\b32\s*bit\b/.test(s) || /\b32bit\b/.test(s)) bd = 32;

    const mK = s.match(/\b(44\.1|48|88\.2|96|176\.4|192)\s*k(?:hz)?\b/);
    if(mK){
      const v = mK[1];
      if(v === "44.1") sr = 44100;
      else if(v === "48") sr = 48000;
      else if(v === "88.2") sr = 88200;
      else if(v === "96") sr = 96000;
      else if(v === "176.4") sr = 176400;
      else if(v === "192") sr = 192000;
    }
    return {ext: ext, bitDepth: bd, sampleRate: sr};
  }

  function libHumanSpeed(v){
    const n = Number(v || 0);
    if(!n) return "";
    if(n >= 1000000) return (n/1000000).toFixed(1) + " MBps";
    if(n >= 1000) return (n/1000).toFixed(0) + " KBps";
    return String(Math.round(n)) + " Bps";
  }

  function libResultsToItems(){
    const q = state.libSearch.q || "";
    const filt = libParseFilter(state.libSearch.filter || "");
    const items = [];

    const stMsg = (state.libSearch && state.libSearch.status_msg) ? String(state.libSearch.status_msg) : "";
    const stTone = (state.libSearch && state.libSearch.status_tone) ? String(state.libSearch.status_tone) : "";
    const qPills = [];
    if(stMsg){
      qPills.push({text: stMsg, tone: stTone || ""});
    }
    items.push({kind:"libsearch_query", label:"Enter query", pills: qPills});
    items.push({kind:"libsearch_filter", label:"Enter filters"});

    items.push({kind:"libsearch_action", label:"Clear"});
    items.push({kind:"libsearch_action", label:"Search history"});

    for(const r of (state.libSearch.results || [])){
      const source = String(r.source || "").toLowerCase();
      if(filt.source && source !== filt.source) continue;

      const title = String(r.title || r.label || "Result");
      const user = String(r.user || "").trim();
      const searchable = [
        source,
        user,
        title,
        String(r.directory || ""),
        String(r.infohash || ""),
        String(r.category || ""),
        ...(Array.isArray(r.files) ? r.files.map(f => [f.name || "", f.ext || "", f.quality || ""].join(" ")) : [])
      ].join(" ").toLowerCase();
      if(filt.rest.length && !libTextHasAllTokens(searchable, filt.rest)) continue;

      const files = Array.isArray(r.files) ? r.files : [];
      if(filt.exts.size || filt.bitDepth || filt.sampleRate){
        let ok = false;
        for(const f of files){
          const ext = String(f.ext || "").toLowerCase();
          const bd = Number(f.bit_depth || 0);
          const sr = Number(f.sample_rate || 0);
          if(filt.exts.size && (!ext || !filt.exts.has(ext))) continue;
          if(filt.bitDepth && (!bd || bd !== filt.bitDepth)) continue;
          if(filt.sampleRate && (!sr || sr !== filt.sampleRate)) continue;
          ok = true;
          break;
        }
        if(!ok) continue;
      }

      const pills = [];
      pills.push({text: String(r.source_label || source || "source")});
      if(Number(r.file_count || 0) > 0) pills.push({text: String(r.file_count) + " files"});
      if(Number(r.size || 0) > 0) pills.push({text: humanBytes(Number(r.size || 0))});
      if(source === "soulseek" && Number(r.speed || 0) > 0){
        pills.push({text: libHumanSpeed(Number(r.speed || 0))});
      }else if(source === "knaben"){
        const s = Number(r.seeders || 0);
        const l = Number(r.leechers || 0);
        pills.push({text: "S " + String(s) + " L " + String(l)});
      }else if(source === "youtube"){
        if(r.length) pills.push({text: String(r.length)});
        if(r.published) pills.push({text: String(r.published)});
      }

      const primary = user ? ('<span class="artistStrong">' + escapeHtml(user) + '</span>') : ('<span class="artistStrong">' + escapeHtml(title) + '</span>');
      const sub = user ? title : String(r.directory_title || r.directory || r.category || "");

      items.push({
        kind:"libsearch_result",
        label: user || title,
        label_html: primary,
        sub_label: sub || "",
        source: source,
        result_id: r.result_id || "",
        raw: r,
        pills: pills
      });
    }

    return items;
  }

  function libRefreshList(preserveSel){
    const items = libResultsToItems();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);

    let restoreSel = null;
    let restoreScroll = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; }

    state.items = Array.isArray(items) ? items : [];
    if(preserveSel){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
    }else if(restoreSel != null){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(!preserveSel && restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }else{
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }

  function libSearchRebuildFilesList(items){
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const arr = Array.isArray(items) ? items : [];
    state.items = arr;
    const max = Math.max(0, arr.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }



  async function viewLibSearch(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch",
      label:"Search",
      load: async function(){
        libControlsHide();
        // keep existing query/filter text; list rows handle editing/focus
        state.libSearch.engine = state.libSearch.engine || "";
        libRefreshList(false);
      }
    }, push);
  }

// Library-root Tasks view (parity with Tasks tab, but in the iPod list UI)
async function viewLibTasks(push){
  showNowPlaying(false);
  await setView({
    kind:"libtasks",
    label:"Tasks",
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
      }catch(e){
        state.libTasks.tasks = [];
      }
      libTasksRefreshList(false);
    }
  }, push);
}

function libTasksBuildItems(){
  const tasks = Array.isArray(state.libTasks.tasks) ? state.libTasks.tasks : [];
  const items = [];
  items.push({kind:"libtasks_action", label:"Clear all tasks", action:"clear_all"});
  for(const t of tasks){
    const id = String(t.id || "");
    const title = String(t.title || "Task");
    const src = String(t.source || "rd").toLowerCase();
    const stLower = String(t.state || "").toLowerCase();
    const pills = [];
    pills.push(src === "soulseek" ? "Soulseek" : (src === "youtube" ? "YouTube" : "Debrid"));
    if(t.paused) pills.push({text:"paused", tone:"warn"});
    if(stLower){
      let tone = "";
      if(stLower === "done") tone = "ok";
      else if(stLower === "error" || stLower === "canceled") tone = "warn";
      pills.push({text: stLower, tone: tone});
    }
    // light overall percent indicator when available
    try{
      const ot = Number(t.overall_total || 0);
      const od = Number(t.overall_done || 0);
      if(ot > 0){
        const pct = Math.max(0, Math.min(100, Math.floor((od / ot) * 100)));
        pills.push(String(pct) + "%");
      }
    }catch(e){}
    items.push({kind:"libtask_entry", label:title, task_id:id, pills:pills});
  }
  if(tasks.length === 0){
    items.push({kind:"info", label:"No tasks"});
  }
  return items;
}

function libTasksRefreshList(preserveSel){
  const items = libTasksBuildItems();
  const prevSel = state.sel;
  const prevScroll = (libList ? libList.scrollTop : 0);

  let restoreSel = null;
  let restoreScroll = null;
  try{
    if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
      restoreSel = Number(state.current.savedSel);
    }
    if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
      restoreScroll = Number(state.current.savedScroll);
    }
  }catch(e){ restoreSel = null; restoreScroll = null; }

  state.items = Array.isArray(items) ? items : [];
  if(preserveSel){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
  }else if(restoreSel != null){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, restoreSel));
  }else{
    state.sel = 0;
  }

  setHeader();
  renderList();

  if(!preserveSel && restoreScroll != null && libList){
    const top = Math.max(0, restoreScroll);
    requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
  }else{
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }
}

function libTaskFilesForTask(t){
  const src = String((t && t.source) || "rd").toLowerCase();
  if(src === "soulseek"){
    return Array.isArray(t.slsk_files) ? t.slsk_files : [];
  }
  return Array.isArray(t.rd_files) ? t.rd_files : [];
}

function libTaskBuildItemsForView(view){
  const t = (view && view.task) ? view.task : {};
  const files = libTaskFilesForTask(t);
  const items = [];
  const selCount = (view && view.selected && view.selected.size) ? view.selected.size : 0;

  items.push({kind:"libtask_action", label:"Pause selected", action:"pause_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Cancel selected", action:"cancel_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Select all", action:"selectall"});
  items.push({kind:"libtask_action", label:"Clear task", action:"clear_task"});

  const msg = String((t && t.message) || "");
  if(msg){
    items.push({kind:"info", label: msg});
  }

  for(const f of files){
    const fid = String((f && f.file_id) || "");
    const rp = String((f && (f.name || f.remote_path || f.out_path)) || "");
    const name = (rp.split("\\").pop() || rp || fid || "File");
    const stLower = String((f && f.state) || "queued").toLowerCase();
    const done = Number((f && f.done) || 0);
    const total = Number((f && f.total) || 0);

    let pct = 0;
    let bar = 0;
    let pctText = "?";
    if(total > 0){
      pct = Math.max(0, Math.min(100, Math.floor((done / total) * 100)));
      bar = pct / 100;
      pctText = String(pct) + "%";
    }else if(stLower === "complete" || stLower === "done"){
      pct = 100;
      bar = 1;
      pctText = "100%";
    }else{
      pct = 0;
      bar = 0;
      pctText = "0%";
    }

    let stTone = "";
    if(stLower === "complete" || stLower === "done") stTone = "ok";
    else if(stLower === "failed" || stLower === "error" || stLower === "canceled" || stLower === "aborted" || stLower === "incomplete" || stLower === "paused") stTone = "warn";

    const stLabel = slskDownloadLabel(stLower) || String(stLower || "").toUpperCase();
    const pills = [
      {text: stLabel, tone: stTone},
      {text: pctText, tone: ""},
      {text: "", tone: "", bar: bar}
    ];

    const item = {
      kind:"libtask_file",
      label:name,
      task_id:String(view.task_id || ""),
      file_id:fid,
      selectable:true,
      selected:(view && view.selected && fid) ? view.selected.has(fid) : false,
      pills:pills
    };
    item.onToggle = ()=>{
      if(!view.selected) view.selected = new Set();
      if(view.selected.has(fid)) view.selected.delete(fid);
      else view.selected.add(fid);
      item.selected = view.selected.has(fid);
    };
    items.push(item);
  }

  if(!files.length){
    items.push({kind:"info", label:"No files"});
  }
  return items;
}

async function viewLibTask(push, taskId){
  showNowPlaying(false);
  await setView({
    kind:"libtask",
    label:"Task",
    task_id: String(taskId || ""),
    task: null,
    selected: new Set(),
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        const tasks = (js && js.tasks) ? js.tasks : [];
        const t = tasks.find(x => String(x.id || "") === String(this.task_id || ""));
        this.task = t || this.task || null;
        if(t && t.title){
          this.label = String(t.title);
        }
      }catch(e){}
      setHeader();
      resetList(libTaskBuildItemsForView(this));
    }
  }, push);
}

async function libTasksPollTick(){
  const vk = (state.current && state.current.kind) ? state.current.kind : "";
  if(vk !== "libtasks" && vk !== "libtask") return;
  try{
    const js = await apiGet("/api/tasks");
    const tasks = (js && js.tasks) ? js.tasks : [];
    if(vk === "libtasks"){
      state.libTasks.tasks = tasks;
      libTasksRefreshList(true);
    }else if(vk === "libtask"){
      const view = state.current;
      const t = tasks.find(x => String(x.id || "") === String(view.task_id || ""));
      if(t){
        view.task = t;
        if(t.title) view.label = String(t.title);
      }
      const prevSel = state.sel;
      const prevScroll = (libList ? libList.scrollTop : 0);
      state.items = libTaskBuildItemsForView(view);
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
      setHeader();
      renderList();
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }catch(e){}
}

// start/refresh library tasks poller
if(window.dpLibTasksTimer) clearInterval(window.dpLibTasksTimer);
window.dpLibTasksTimer = setInterval(()=>{ libTasksPollTick(); }, window.DEBRIPOD_TASKS_POLL_MS || 1200);

async function libDoSearch(engine, q){
    const qq = String(q || "").trim();
    if(!qq){
      libSetStatus("Enter a query", "warn");
      return;
    }
    const useEngine = String(engine || "combined").toLowerCase() || "combined";
    state.libSearch.q = qq;
    state.libSearch.engine = useEngine;
    libSetStatus("Searching", "");
    try{
      const endpoint = (useEngine === "youtube") ? "/api/libsearch/youtube?q=" : "/api/libsearch/combined?q=";
      const js = await apiGet(endpoint + encodeURIComponent(qq));
      if(!js || !js.ok){
        throw new Error((js && js.error) ? js.error : "Search failed");
      }
      state.libSearch.result_source = useEngine;
      state.libSearch.cache_key = js.cache_key || "";
      state.libSearch.results = Array.isArray(js.results) ? js.results : [];
      state.libSearch.knaben_results = js.knaben_results || [];
      state.libSearch.slsk_users = js.slsk_users || [];
      state.libSearch.last_count = Number(js.result_count || state.libSearch.results.length || 0);
      libSetStatus(String(state.libSearch.last_count) + " results", "ok");
      libRefreshList(true);
    }catch(e){
      libSetStatus("Error", "warn");
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function viewLibSearchHistory(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_history",
      label:"Search history",
      load: async function(){
        libControlsHide();
        let items = [];
        items.push({kind:"libsearch_history_action", label:"Clear", action:"clear_history"});
        try{
          const js = await apiGet("/api/search_history");
          const hist = (js && js.ok && Array.isArray(js.items)) ? js.items : [];
          for(const h of hist){
            const q = h.q || "";
            const engine = h.engine || "";
            const when = h.when || "";
            const lbl = q ? q : "(empty)";
            const pills = [];
            if(engine) pills.push(engine);
            if(when) pills.push(String(when));
            items.push({kind:"libsearch_history_entry", label: lbl, engine: engine, q: q, pills: pills});
          }
          if(!items.length){
            items.push({kind:"info", label:"No search history"});
          }
        }catch(e){
          items = [{kind:"info", label:"Failed to load history"}];
        }
        resetList(items);
      }
    }, push);
  }
  
  async function viewLibInfo(push){
    showNowPlaying(false);
    await setView({
      kind:"libinfo",
      label:"Info",
      load: async function(){
        libControlsHide();
        const items = [];

        const v = (APP_INFO && APP_INFO.version) ? String(APP_INFO.version) : "";
        const vPills = [];
        if(v) vPills.push("v" + v);
        items.push({kind:"info", label:"Debripod", pills: vPills});

        const host = (APP_INFO && APP_INFO.host) ? String(APP_INFO.host) : (location.hostname || "");
        const port = (APP_INFO && (APP_INFO.port !== undefined && APP_INFO.port !== null)) ? String(APP_INFO.port) : (location.port || "");
        const hp = [];
        if(host) hp.push(host);
        if(port) hp.push(port);
        items.push({kind:"info", label:"Host and port", pills: hp});

        const ddir = (APP_INFO && APP_INFO.ddir) ? String(APP_INFO.ddir) : "";
        const dP = [];
        if(ddir) dP.push(ddir);
        items.push({kind:"info", label:"Debrid download dir", pills: dP});

        const sdir = (APP_INFO && APP_INFO.sdir) ? String(APP_INFO.sdir) : "";
        const sP = [];
        if(sdir) sP.push(sdir);
        items.push({kind:"info", label:"Soulseek download dir", pills: sP});

        let anyBuilding = false;
        try{
          anyBuilding = await getAnyIndexBuilding();
        }catch(e){}
        const rp = anyBuilding ? ["indexing"] : [];
        items.push({kind:"libinfo_action", label:"Reindex", action:"reindex", pills: rp});

        let lfUser = "";
        try{
          const js = await apiGet("/api/lastfm/status");
          if(js && js.ok && js.username) lfUser = String(js.username || "");
        }catch(e){}
        const lp = [];
        if(lfUser) lp.push("logged in as " + lfUser);
        items.push({kind:"libinfo_action", label:"Login to Last.fm", action:"lastfm_login", pills: lp});

        items.push({kind:"libinfo_action", label:"Full Screen", action:"force_fullscreen"});
        items.push({kind:"libinfo_action", label:"Visualizer", action:"toggle_visualizer", pills:[visualizerEnabled ? "On" : "Off"]});
        items.push({kind:"libinfo_action", label:"Binds", action:"binds_menu"});

        resetList(items);
      }
    }, push);
  }


  async function viewLibBinds(push){
    showNowPlaying(false);
    await setView({
      kind:"libbinds",
      label:"Binds",
      load: async function(){
        libControlsHide();
        const items = [];

        items.push({kind:"info", label:"Navigation"});
        items.push({kind:"info", label:"W", pills:["Back or menu"]});
        items.push({kind:"info", label:"A", pills:["Previous or left"]});
        items.push({kind:"info", label:"S", pills:["Select or center"]});
        items.push({kind:"info", label:"D", pills:["Next or right"]});
        items.push({kind:"info", label:"Space", pills:["Play or pause"]});
        items.push({kind:"info", label:"Q", pills:["Scroll up"]});
        items.push({kind:"info", label:"E", pills:["Scroll down"]});
        items.push({kind:"info", label:"Mouse wheel", pills:["Scroll lists"]});
        items.push({kind:"info", label:"Arrow Up", pills:["Scroll up","Now Playing volume up","Seek left in seek mode"]});
        items.push({kind:"info", label:"Arrow Down", pills:["Scroll down","Now Playing volume down","Seek right in seek mode"]});

        resetList(items);
      }
    }, push);
  }

  function libBuildFileItemsFromRD(preview, title, magnet){
    const torrentId = preview.torrent_id || "";
    const files = preview.files || [];
    const view = state.current;
    view._rd = {title: title, magnet: magnet, torrent_id: torrentId, files: files, selected: new Set(), filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : "")};

    const build = ()=>{
      const f = libParseFilter(view._rd.filter || "");
      const items = [];
      const selCount = view._rd.selected.size;
      const statusMsg = String(view._fileStatus || "");

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"rd_download", badge: selCount ? String(selCount) : ""});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"rd_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"rd_clear"});

      for(const ff of files){
        const name = ff.path || "";
        const guess = libGuessFromName(name);
        const ft = (name || "").toLowerCase();
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size){
          if(!guess.ext || !f.exts.has(guess.ext)) continue;
        }
        if(f.bitDepth){
          if(!guess.bitDepth || guess.bitDepth !== f.bitDepth) continue;
        }
        if(f.sampleRate){
          if(!guess.sampleRate || guess.sampleRate !== f.sampleRate) continue;
        }

        const id = String(ff.id);
        const pills = [];
        if(guess.ext) pills.push(guess.ext);
        if(ff.bytes) pills.push(humanBytes(ff.bytes));
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"knaben",
          file_id:id,
          selectable:true,
          selected:view._rd.selected.has(id),
          pills:pills,
          onToggle: ()=>{
            if(view._rd.selected.has(id)) view._rd.selected.delete(id);
            else view._rd.selected.add(id);
          }
        });
      }
      return items;
    };
    view._rd.buildItems = build;
    return build();
  }

  async function viewLibSearchKnabenFiles(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Files",
      source:"knaben",
      load: async function(){
        const title = item.label || "Knaben item";
        const magnet = item.magnet || "";
        resetList([{kind:"info", label:"Loading files"}]);
        libSetFileStatus("", "");
        try{
          const res = await apiPost("/api/rd/preview_files", {magnet: magnet});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load files");
          }
          libSetFileStatus("", "");
          resetList(libBuildFileItemsFromRD(js, title, magnet));
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load files"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  function libStandardizePreviewFilesForKnaben(preview){
    const out = [];
    const files = Array.isArray(preview && preview.files) ? preview.files : [];
    for(const ff of files){
      const name = String(ff.path || ff.name || "");
      const guess = libGuessFromName(name);
      const bitDepth = Number(guess.bitDepth || 0);
      const sampleRate = Number(guess.sampleRate || 0);
      const quality = [];
      if(bitDepth) quality.push(String(bitDepth) + " bit");
      if(sampleRate) quality.push(String(Math.round(Number(sampleRate)/100)/10) + " kHz");
      out.push({
        name: name,
        title: name,
        ext: guess.ext || "",
        quality: quality.join(" "),
        bitrate: "",
        size: Number(ff.bytes || 0),
        file_id: String(ff.id || ""),
        bit_depth: bitDepth,
        sample_rate: sampleRate,
        source: "knaben",
        selectable: true
      });
    }
    return out;
  }

  function libBuildGenericResultItems(result){
    const view = state.current;
    const src = String((result && result.source) || "").toLowerCase();
    const prev = view._searchResult || null;
    let selected = new Map();
    if(prev && prev.result_id === String(result.result_id || "") && prev.selected instanceof Map){
      selected = prev.selected;
    }
    view._searchResult = {
      result_id: String(result.result_id || ""),
      result: result || {},
      source: src,
      selected: selected,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""),
      loadingBrowse: (prev && prev.loadingBrowse) ? true : false
    };

    const build = ()=>{
      const target = view._searchResult;
      const rr = target.result || {};
      const f = libParseFilter(target.filter || "");
      const items = [];
      const files = Array.isArray(rr.files) ? rr.files : [];
      const selCount = target.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const statusTone = String(view._fileStatusTone || "");
      const streamPills = [];
      const downloadPills = [];
      if(selCount){
        const countPill = {text: String(selCount), tone: ""};
        streamPills.push(countPill);
        downloadPills.push({text: String(selCount), tone: ""});
      }
      if(target.downloadQueued){
        downloadPills.push({text: "Queued", tone: "warn"});
      }
      const streamMsg = statusMsg.toLowerCase();
      if(streamMsg && rr.stream_available && (streamMsg.includes("stream") || streamMsg.includes("prepare"))){
        streamPills.push({text: statusMsg, tone: statusTone || ""});
      }
      if(rr.browse_available){
        items.push({kind:"libsearch_file_action", label:(src === "youtube" ? "Browse channel" : "Browse share"), action:"result_browse", badge: target.loadingBrowse ? "Loading" : ""});
      }
      if(rr.stream_available){
        items.push({kind:"libsearch_file_action", label:"Stream selected", action:"result_stream", pills: streamPills});
      }
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"result_download", pills: downloadPills});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"result_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"result_clear"});

      let visibleFileCount = 0;
      for(const ff of files){
        const name = String(ff.name || ff.title || ff.label || "");
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        const fileSource = String(ff.source || src || "").toLowerCase();
        const searchText = [fileSource, name, ext, String(ff.quality || ""), String(ff.bitrate || "")].join(" ").toLowerCase();
        if(f.source && fileSource && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(searchText, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;
        visibleFileCount += 1;
        const key = src === "knaben" ? ("file:" + String(ff.file_id || name)) : (src === "youtube" ? ("itag:" + String(ff.itag || ff.file_id || name)) : (String(ff.remote_path || name)));
        const dlState = normalizeSlskDownloadState(String(ff.download_state || ""));
        const pills = [];
        if(fileSource) pills.push({text:fileSource});
        if(ext) pills.push(ext);
        if(ff.quality) pills.push(String(ff.quality));
        if(ff.bitrate) pills.push(String(ff.bitrate));
        if(Number(ff.size || 0) > 0) pills.push(humanBytes(Number(ff.size || 0)));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:src,
          selectable: !dlState,
          selected: !dlState && target.selected.has(key),
          pills:pills,
          remote_path: String(ff.remote_path || ""),
          file_id: String(ff.file_id || ""),
          size: Number(ff.size || 0),
          source: fileSource || src,
          onToggle: ()=>{
            if(dlState) return;
            if(target.selected.has(key)) target.selected.delete(key);
            else target.selected.set(key, {key:key, remote_path:String(ff.remote_path || ""), file_id:String(ff.file_id || ""), itag:String(ff.itag || ff.format_id || ff.file_id || ""), format_id:String(ff.format_id || ff.itag || ff.file_id || ""), size:Number(ff.size || 0), name:name, source:String(ff.source || src || ""), ext:String(ff.ext || ""), quality:String(ff.quality || ""), bitrate:String(ff.bitrate || ""), media:String(ff.media || ""), direct_url:String(ff.direct_url || ""), url:String((target.result && target.result.url) || "")});
          }
        });
      }
      if(files.length && !visibleFileCount){
        items.push({kind:"info", label:"No files match the current filter"});
      }else if(!files.length){
        items.push({kind:"info", label:"No files available"});
      }
      return items;
    };
    view._searchResult.buildItems = build;
    return build();
  }

  function libBuildStreamQueue(items){
    return (Array.isArray(items) ? items : []).map(it=>({
      kind:"file",
      media:String(it.media || ""),
      root:{id:String(it.root_id || "")},
      rel:String(it.rel || ""),
      label:String(it.label || it.title || ""),
      streamed:!!it.streamed,
      source:String(it.source || ""),
      ext:String(it.ext || ""),
      quality:String(it.quality || "")
    })).filter(it=>it.root.id && it.rel && (it.media === "audio" || it.media === "video"));
  }

  async function startSearchStreamQueue(queue, index){
    const pl = libBuildStreamQueue(queue);
    if(!pl.length) throw new Error("No streamable items");
    const idx = Math.max(0, Math.min(pl.length - 1, Number(index || 0)));
    state.streamQueue = pl;
    state.streamQueueIndex = idx;
    const first = pl[idx];
    if(first.media === "video"){
      state.videoPlaylist = pl;
      state.videoIndex = idx;
      await startVideoFromItem(first, true, 0);
    }else{
      state.playlist = pl;
      state.playIndex = idx;
      await startAudioFromItem(first, pl, idx, true, 0);
    }
  }

  function isSearchStreamActive(){
    try{
      return !!(state.now && state.now.rootId === "__search_stream__" && Array.isArray(state.streamQueue) && state.streamQueue.length);
    }catch(e){
      return false;
    }
  }

  async function playStreamQueueIndex(i, forceShow){
    const q = Array.isArray(state.streamQueue) ? state.streamQueue : [];
    if(i < 0 || i >= q.length) return;
    state.streamQueueIndex = i;
    const item = q[i];
    if(item.media === "video"){
      state.videoPlaylist = q;
      state.videoIndex = i;
      await startVideoFromItem(item, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }else{
      state.playlist = q;
      state.playIndex = i;
      await startAudioFromItem(item, q, i, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }
  }

  async function viewLibSearchResultDetails(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_detail",
      label:"Files",
      source:String(item.source || ""),
      load: async function(){
        const raw = Object.assign({}, item.raw || {});
        resetList([{kind:"info", label:"Loading files"}]);
        libSetFileStatus("", "");
        try{
          if(String(raw.source || item.source || "") === "knaben" && !raw.files_loaded){
            const res = await apiPost("/api/rd/preview_files", {magnet: raw.magnet || ""});
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load files");
            }
            raw.preview = js;
            raw.torrent_id = js.torrent_id || raw.torrent_id || "";
            raw.files = libStandardizePreviewFilesForKnaben(js);
            raw.file_count = raw.files.length;
            raw.files_loaded = true;
          }else if(String(raw.source || item.source || "") === "youtube" && !raw.files_loaded){
            const js = await apiGet("/api/youtube/files?url=" + encodeURIComponent(raw.url || ""));
            if(!js || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load YouTube formats");
            }
            raw.files = Array.isArray(js.files) ? js.files : [];
            raw.file_count = Number(js.file_count || raw.files.length || 0);
            raw.size = Number(js.size || 0);
            raw.files_loaded = true;
          }
          resetList(libBuildGenericResultItems(raw));
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load files"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  function normalizeSlskDownloadState(v){
    const s = String(v || "").trim().toLowerCase();
    if(!s) return "";
    if(s === "canceled") return "aborted";
    if(s === "requesting" || s === "connecting") return "initializing";
    return s;
  }

  function slskDownloadTone(v){
    const s = normalizeSlskDownloadState(v);
    if(s === "complete") return "ok";
    if(s === "failed" || s === "incomplete" || s === "aborted" || s === "paused") return "warn";
    return "";
  }

  function slskDownloadLabel(v){
    const s = normalizeSlskDownloadState(v);
    return s ? s.toUpperCase() : "";
  }

  function libBuildFileItemsFromSlsk(user, directory, files){
    const view = state.current;
    const prev = view._slsk || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slsk = {user: user, directory: directory, files: files || [], selected: prevSel, downloadQueued: !!(prev && prev.downloadQueued), filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""), loadingBrowse: (prev && prev.loadingBrowse) ? true : false};

    const build = ()=>{
      const f = libParseFilter(view._slsk.filter || "");
      const items = [];
      const selCount = view._slsk.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slsk.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      items.push({kind:"libsearch_file_action", label:"Browse user share", action:"slsk_browse_user", badge: view._slsk.loadingBrowse ? "Loading user shares" : ""});
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});

      for(const ff of (view._slsk.files || [])){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slsk.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(fileSource) pills.push({text:fileSource});
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slsk.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slsk.selected.has(remote)) view._slsk.selected.delete(remote);
            else view._slsk.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }
      return items;
    };
    view._slsk.buildItems = build;
    return build();
  }

  function slskBrowseParentPath(path){
    const parts = String(path || "").split("\\").filter(Boolean);
    if(parts.length <= 1) return "";
    return parts.slice(0, -1).join("\\");
  }

  function libBuildBrowseItemsFromSlsk(user, allDirs, currentDir, selectedPath){
    const view = state.current;
    const prev = view._slskbrowse || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slskbrowse = {
      user: user || "",
      dirs: Array.isArray(allDirs) ? allDirs : [],
      current_dir: String(currentDir || ""),
      selected_path: String(selectedPath || ""),
      selected: prevSel,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : "")
    };

    const build = ()=>{
      const f = libParseFilter(view._slskbrowse.filter || "");
      const items = [];
      const cur = String(view._slskbrowse.current_dir || "");
      const dirs = Array.isArray(view._slskbrowse.dirs) ? view._slskbrowse.dirs : [];
      const curPrefix = cur ? (cur + "\\") : "";
      let curEntry = null;
      const childMap = new Map();

      for(const d of dirs){
        const dp = String((d && d.directory) || "");
        if(dp === cur){
          curEntry = d;
        }
        if(cur){
          if(!dp || dp === cur) continue;
          if(!dp.startsWith(curPrefix)) continue;
        }else if(!dp){
          continue;
        }
        const rest = cur ? dp.slice(curPrefix.length) : dp;
        if(!rest) continue;
        const parts = rest.split("\\").filter(Boolean);
        if(!parts.length) continue;
        const childName = parts[0];
        const childPath = cur ? (cur + "\\" + childName) : childName;
        let agg = childMap.get(childPath);
        if(!agg){
          agg = {name: childName, path: childPath, fileCount: 0, totalSize: 0};
          childMap.set(childPath, agg);
        }
        agg.fileCount += Number((d && d.total_files) || ((d && d.files) ? d.files.length : 0) || 0);
        agg.totalSize += Number((d && d.total_size) || 0);
      }

      const files = (curEntry && Array.isArray(curEntry.files)) ? curEntry.files : [];
      const selCount = view._slskbrowse.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slskbrowse.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      if(cur){
        items.push({kind:"libsearch_file_action", label:"..", action:"slsk_browse_up"});
      }
      if(files.length){
        items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
        items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
        items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});
      }

      const childDirs = Array.from(childMap.values()).sort((a,b)=> String(a.name || "").localeCompare(String(b.name || "")));
      for(const d of childDirs){
        const ft = (String(d.name || "") + " " + String(d.path || "")).toLowerCase();
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        const pills = [];
        if(d.fileCount) pills.push(String(d.fileCount) + " files");
        if(d.totalSize) pills.push(humanBytes(d.totalSize));
        items.push({
          kind:"slsk_browse_dir",
          label:String(d.name || "") || "(dir)",
          browse_path:String(d.path || ""),
          pills:pills
        });
      }

      for(const ff of files){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slskbrowse.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slskbrowse.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slskbrowse.selected.has(remote)) view._slskbrowse.selected.delete(remote);
            else view._slskbrowse.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }

      return items;
    };

    view._slskbrowse.buildItems = build;
    return build();
  }

  async function viewLibSearchSlskBrowse(push, user, selectedDir){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Browse",
      source:"soulseek",
      load: async function(){
        const browseUser = user || "";
        const wantedDir = String(selectedDir || "");
        libSetFileStatus("Loading shares", "");
        try{
          const js = await apiGet("/api/soulseek/browse_user?user=" + encodeURIComponent(browseUser) + "&selected_dir=" + encodeURIComponent(wantedDir));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load user shares");
          }
          const selectedPath = String(js.selected_dir || wantedDir || "");
          const currentDir = selectedPath ? slskBrowseParentPath(selectedPath) : "";
          libSetFileStatus("", "");
          const built = libBuildBrowseItemsFromSlsk(browseUser, js.dirs || [], currentDir, selectedPath);
          resetList(built);
          if(selectedPath){
            const idx = (state.items || []).findIndex(x=>x && x.kind === "slsk_browse_dir" && String(x.browse_path || "") === selectedPath);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load user shares"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchYouTubeChannel(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_list",
      label:"Channel",
      source:"youtube",
      load: async function(){
        resetList([{kind:"info", label:"Loading channel"}]);
        try{
          const js = await apiGet("/api/youtube/channel?channel_id=" + encodeURIComponent(item.channel_id || ""));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load channel videos");
          }
          const vids = Array.isArray(js.results) ? js.results : [];
          const items2 = [];
          for(const r of vids){
            const pills = [{text:"YouTube"}];
            if(Number(r.file_count || 0) > 0) pills.push({text:String(r.file_count) + " files"});
            if(Number(r.size || 0) > 0) pills.push({text:humanBytes(Number(r.size || 0))});
            if(r.published) pills.push({text:String(r.published)});
            items2.push({kind:"libsearch_result", label:r.user || r.title || "Video", label_html:'<span class="artistStrong">' + escapeHtml(String(r.user || r.title || "Video")) + '</span>', sub_label:String(r.title || ""), source:"youtube", result_id:r.result_id || "", raw:r, pills:pills});
          }
          if(!items2.length) items2.push({kind:"info", label:"No channel videos found"});
          resetList(items2);
        }catch(e){
          resetList([{kind:"info", label:"Failed to load channel videos"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchSlskFiles(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Files",
      source:"soulseek",
      load: async function(){
        const user = item.user || "";
        const directory = item.directory || "";
        const files = item.files || [];
        libSetFileStatus("", "");
        resetList(libBuildFileItemsFromSlsk(user, directory, files));
      }
    }, push);
  }

async function viewRecently(push){
    showNowPlaying(false);
    await syncPlaybackFromServer();
    await setView({
      kind: "recently",
      label: "Recently Played",
      root: null,
      load: async function(){
        let rec = [];
        try{
          const js = await apiGet("/api/playback/recent");
          rec = (js && Array.isArray(js.recent)) ? js.recent : [];
        }catch(e){ rec = []; }
        const items = [];
        if(state.history.length){
          items.push({kind:"up", label:".."});
        }
        for(const r of rec){
          if(!r || !r.root_id || !r.rel) continue;
          const media = (r.media || "").toLowerCase();
          let label = "";
          if(media === "audio"){
            const a = (r.artist || "").trim();
            const t = (r.title || "").trim();
            if(a && t) label = a + " - " + t;
            else if(t) label = t;
            else label = (r.label || r.rel || "").split("/").slice(-1)[0];
          }else{
            label = (r.title || r.label || r.rel || "").split("/").slice(-1)[0];
          }
          const pills = [];
          const extText = (()=>{
            const ex = String(r.ext || "").trim().toLowerCase();
            if(ex) return ex;
            const rel = String(r.rel || "");
            const base = rel.split("/").slice(-1)[0] || "";
            const dot = base.lastIndexOf(".");
            return (dot > 0 && dot < (base.length - 1)) ? base.slice(dot + 1).toLowerCase() : "";
          })();
          if(r.streamed) pills.push("Streamed");
          if(extText) pills.push(extText);
          if(r.quality) pills.push(String(r.quality));
          items.push({
            kind: "recent_item",
            label: label || "item",
            pills: pills,
            media: media,
            rootId: r.root_id,
            rel: r.rel,
            position: (r.position || 0),
            playing: !!r.playing,
            nav: r.nav || {},
            title: r.title || "",
            artist: r.artist || "",
            album: r.album || "",
            art: r.art || "",
            source: r.source || "",
            ext: r.ext || "",
            quality: r.quality || "",
            streamed: !!r.streamed,
            playlist: (r.playlist || null)
          });
        }
        if(items.length === (state.history.length ? 1 : 0)){
          items.push({kind:"info", label:"Empty"});
        }
        resetList(items);
      }
    }, !!push);
  }


  function folderViewObj(root, rel, label){
    return {
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        const js = await apiGet(url);
        const items = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    };
  }

  async function openNowFolder(){
    if(!state.now){
      showNowPlaying(false);
      await showRoots();
      return;
    }
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(r => r.id === state.now.rootId);
    if(!root){
      showNowPlaying(false);
      await showRoots();
      return;
    }

    let folderRel = "";
    try{
      const parts = (state.now.rel || "").split("/");
      parts.pop();
      folderRel = parts.join("/");
    }catch(e){ folderRel = ""; }

    state.root = root;
    state.history = [];
    state.current = null;

    if(folderRel){
      const segs = folderRel.split("/");
      state.history.push(folderViewObj(root, "", ""));
      for(let i = 0; i < segs.length - 1; i++){
        const rel = segs.slice(0, i + 1).join("/");
        state.history.push(folderViewObj(root, rel, segs[i]));
      }
    }

    showNowPlaying(false);
    await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
  }

  
  async function resumeFromServerNow(forceShow){
    await syncPlaybackFromServer();
    const sn = state.serverNow;
    if(!sn || !sn.root_id || !sn.rel){
      if(forceShow){
        showNowPlaying(false);
        await showRoots();
      }
      return;
    }

    // restore browsing context first so Menu goes back to where it was started
    if(sn.nav && sn.nav.root_id){
      await openNavContext(sn.nav);
    }

    if((sn.media || "") === "video"){
      try{
        if(sn.playlist && Array.isArray(sn.playlist.items) && sn.playlist.items.length){
          state.videoPlaylist = sn.playlist.items.map(x=>({kind:"file", media:"video", root:{id:x.root_id}, rel:x.rel, label:x.label || ""})).filter(x=>x.root.id && x.rel);
          const vi = isFinite(sn.playlist.index) ? Number(sn.playlist.index) : 0;
          state.videoIndex = Math.max(0, Math.min(state.videoPlaylist.length - 1, vi));
        }
      }catch(e){}
      await startVideoFromItem({kind:"file", media:"video", root:{id: sn.root_id}, rel: sn.rel, label: sn.label || ""}, true, (sn.position || 0));
      return;
    }

    // audio
    const it = {kind:"file", media:"audio", root:{id: sn.root_id}, rel: sn.rel, label: sn.label || ""};

    // Prefer server-provided playlist context (more reliable than rebuilding from the current view)
    let pl = null;
    let idx = -1;
    try{
      if(sn.playlist && Array.isArray(sn.playlist.items) && sn.playlist.items.length){
        pl = sn.playlist.items.map(x=>({kind:"file", media:"audio", root:{id:x.root_id}, rel:x.rel, label:x.label || ""})).filter(x=>x.root.id && x.rel);
        idx = isFinite(sn.playlist.index) ? Number(sn.playlist.index) : 0;
      }
    }catch(e){ pl = null; idx = -1; }

    if(!pl || !pl.length){
      pl = buildPlaylistFromItems(state.items);
      try{
        idx = pl.findIndex(x => x.rel === it.rel && x.root && x.root.id === it.root.id);
      }catch(e){ idx = -1; }
    }
    if(!pl || !pl.length){
      pl = [it];
      idx = 0;
    }else{
      idx = Math.max(0, Math.min(pl.length - 1, (idx >= 0 ? idx : 0)));
    }
    await startAudioFromItem(it, pl, idx, true, (sn.position || 0));
  }


async function goBack(){
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        showNpPill(true);
      }else{
        npPillActivity(false);
      }
      showNowPlaying(false);
      await waitNowPlayingFade(220);
      return;
    }
    if(state.history.length){
      await runLibraryPageTransition(async ()=>{
        state.current = state.history.pop();
        setHeader();
        await state.current.load();
        if(state.pendingLibSearch && state.current && state.current.kind === "libsearch"){
          const p = state.pendingLibSearch;
          state.pendingLibSearch = null;
          try{
            if(p && p.q) state.libSearch.q = p.q;
            const inQ = document.getElementById("libSearchInput");
            if(inQ && p && p.q) inQ.value = p.q;
            if(p && p.engine && p.q){
              await libDoSearch(p.engine, p.q);
            }
          }catch(e){}
        }
      });
      return;
    }
    await runLibraryPageTransition(async ()=>{
      await showRoots();
    });
  }

  function buildPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it.kind === "track" || (it.kind === "file" && it.media === "audio")){
        pl.push(it);
      }
    }
    return pl;
  }

  function buildVideoPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it && it.kind === "file" && it.media === "video"){
        pl.push(it);
      }
    }
    return pl;
  }

  async function refreshNowPlayingMeta(item){
    if(!item) return;
    const rootId = item.root.id;
    const rel = item.rel;

    // establish a video playlist context from the current view so next/prev works
    try{
      const vpl = buildVideoPlaylistFromItems(state.items || []);
      if(vpl && vpl.length){
        state.videoPlaylist = vpl;
        const vidx = vpl.findIndex(x => x && x.rel === rel && x.root && x.root.id === rootId);
        state.videoIndex = (vidx >= 0 ? vidx : 0);
      }else{
        // fallback to a single-item playlist
        state.videoPlaylist = [item];
        state.videoIndex = 0;
      }
    }catch(e){
      state.videoPlaylist = [item];
      state.videoIndex = 0;
    }
    try{
      const meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      state.now = {rootId: rootId, rel: rel, media: "audio", streamed: !!item.streamed};
      state.nowMeta = meta;
      saveResumeNowPlaying();
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
      npPillActivity(false);
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);
    }catch(e){}
  }
  let videoOverlayActive = false;


  function isVideoActive(){
    try{
      return !!(videoOverlayActive && npVideoOverlay && npVideo && npVideoOverlay.style.display !== "none" && npVideo.src);
    }catch(e){ return false; }
  }

  function wheelMedia(){
    return isVideoActive() ? npVideo : activeAudio;
  }

  function stopVideoOverlay(){
    if(!npVideoOverlay || !npVideo) return;

    // Only write playback state when a real video overlay is active.
    const wasActive = isVideoActive();

    if(wasActive){
      let d = 0;
      let t = 0;
      try{ d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0; }catch(e){ d = 0; }
      try{ t = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0; }catch(e){ t = 0; }
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "stop");
        }
      }catch(e){}
    }

    videoOverlayActive = false;
    try{ npVideo.pause(); }catch(e){}
    try{
      npVideo.removeAttribute("src");
      npVideo.load();
    }catch(e){}
    try{ npVideoOverlay.style.display = "none"; }catch(e){}
  }



  async function startVideoFromItem(item, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    if(forceShow) showNowPlaying(true);

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    resetGaplessPrime();
    destroyHlsController("audio");

    if(npVideoOverlay) npVideoOverlay.style.display = "flex";
    videoOverlayActive = true;

    const rootId = item.root.id;
    const rel = item.rel;

    try{
      if(isVideoActive() && state.now && state.now.media === "video" && state.now.rootId === rootId && state.now.rel === rel){
        const rt0 = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
        if(rt0 > 0){
          try{ setTimeout(()=>{ resumeVideoViaSeekInputs(rt0); }, 200); }catch(e){}
        }
        if(forceShow) showNowPlaying(true);
        return;
      }
    }catch(e){}

    let meta = {};
    try{
      meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
    }catch(e){ meta = {}; }

    state.now = {rootId: rootId, rel: rel, media: "video", streamed: !!item.streamed};
    state.nowMeta = meta;
    saveResumeNowPlaying();

    await updateNowPlayingDisplay(meta, item.label || "Video", {animateArt: true, animatePill: true});
    updateMediaSession({title: meta.title || item.label || "Video", artist: meta.artist || "", album: meta.album || "", art: meta.art || ""});
    try{ syncMediaSessionControls(); }catch(e){}

    const src = hlsManifestUrl(rootId, rel);
    try{
      try{ npVideo.pause(); }catch(e){}
      destroyHlsController("video");
      npVideo.removeAttribute("src");
      try{ npVideo.load(); }catch(e){}
      applyVolume();
      await loadHlsIntoElement(npVideo, src, "video");

      const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
      try{
        const pos0 = (rt > 0) ? rt : ((npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0);
        playbackMaybePost("video", rootId, rel, meta || {}, (pos0 || 0), null, true, "start");
      }catch(e){}

      const p = npVideo.play();
      try{ if(rt > 0) scheduleVideoResume(rt); }catch(e){}
      if(p && p.catch) p.catch(()=>{});
    }catch(e){}
  }



  async function startAudioFromItem(item, playlist, index, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    stopVideoOverlay();
    const rootId = item.root.id;
    const rel = item.rel;

    const same = state.now && state.now.rootId === rootId && state.now.rel === rel;
    if(same){
      state.playlist = playlist || state.playlist || [item];
      if(typeof index === "number") state.playIndex = index;
      ensurePlayOrder(false);
      if(forceShow) showNowPlaying(true);

      const meta = Object.assign({}, state.nowMeta || {}, {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: false, animatePill: false});
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);

      try{ applyVolume(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}

      let playlistCtx = null;
      try{
        if(Array.isArray(state.playlist) && state.playlist.length){
          const items = state.playlist.slice(0, 500).map(it=>({
            root_id: (it.root && it.root.id) ? it.root.id : "",
            rel: it.rel || "",
            media: "audio",
            label: it.label || ""
          })).filter(x=>x.root_id && x.rel);
          playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
        }
      }catch(e){ playlistCtx = null; }

      playbackPost({
        media: "audio",
        root_id: rootId,
        rel: rel,
        playlist: playlistCtx,
        label: item.label || "",
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        art: meta.art || "",
        position: (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0,
        duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : null,
        playing: (activeAudio && !activeAudio.paused),
        nav: captureNavContext(),
        event: "time"
      });

      preloadNextAudio();
      return;
    }

    if(forceShow) showNowPlaying(true);

    const meta = await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel));
    const src = hlsManifestUrl(rootId, rel);

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    destroyHlsController("audio");
    resetGaplessPrime();
    try{ activeAudio.removeAttribute("src"); activeAudio.load(); }catch(e){}

    try{ applyVolume(); }catch(e){}
    try{ enforceSingleAudio(); }catch(e){}

    await loadHlsIntoElement(activeAudio, src, "audio");

    const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
    if(rt > 0){
      try{
        await new Promise((resolve)=>{
          let done = false;
          const finish = ()=>{
            if(done) return;
            done = true;
            try{ activeAudio.removeEventListener("loadedmetadata", onMeta); }catch(e){}
            resolve();
          };
          const onMeta = ()=>finish();
          activeAudio.addEventListener("loadedmetadata", onMeta, {once:true});
          setTimeout(finish, 1200);
        });
        const maxT = (activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : rt;
        activeAudio.currentTime = Math.max(0, Math.min(rt, maxT));
      }catch(e){}
    }

    state.playlist = playlist || [item];
    state.playIndex = (typeof index === "number") ? index : 0;
    ensurePlayOrder(false);

    state.now = {rootId: rootId, rel: rel};
    state.nowMeta = meta;
    saveResumeNowPlaying();

    let playlistCtx = null;
    try{
      if(Array.isArray(state.playlist) && state.playlist.length){
        const items = state.playlist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: "audio",
          label: it.label || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }

    playbackPost({
      media: "audio",
      root_id: rootId,
      rel: rel,
      playlist: playlistCtx,
      label: item.label || "",
      title: meta.title || "",
      artist: meta.artist || "",
      album: meta.album || "",
      art: meta.art || "",
      position: (rt && isFinite(rt)) ? rt : 0,
      duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : (meta && meta.duration ? meta.duration : null),
      playing: true,
      nav: captureNavContext(),
      event: "start"
    });

    await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
    updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
    try{ syncMediaSessionControls(); }catch(e){}
    lastfmOnTrack(meta);

    try{ ensurePlaybackAudioSession(); }catch(e){}
    try{
      await activeAudio.play();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
    }catch(e){
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
    }

    setTimeout(()=>{ try{ preloadNextAudio(); }catch(e){} }, 250);
  }

  function togglePlay(){
    if(!isVideoActive() && !state.now) return;
    const m = wheelMedia();
    if(!m) return;
    if(m.paused){

      try{ m.play().catch(()=>{}); }catch(e){}
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
    }else{
      try{ m.pause(); }catch(e){}
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
    }
  }

  function seek(delta){
    if(nowPlaying.style.display !== "block") return;
    const m = wheelMedia();
    if(!m) return;
    const d = m.duration || 0;
    const t = m.currentTime || 0;
    const nt = Math.max(0, Math.min(d || (t + delta), t + delta));
    try{ m.currentTime = nt; }catch(e){}
    if(seekMode){
      seekPreview = nt;
      seekChanged = true;
      updateSeekIndicator();
      resetSeekIdle();
    }
  }

  function ensurePlayOrder(forceRebuild){
    if(!state.shuffleEnabled){
      state.playOrder = null;
      state.orderPos = 0;
      state.playOrderPlaylist = null;
      return;
    }
    const pl = state.playlist || [];
    const n = pl.length || 0;
    if(n <= 0){
      state.playOrder = [];
      state.orderPos = 0;
      state.playOrderPlaylist = pl;
      return;
    }
    const idx = (typeof state.playIndex === "number" && state.playIndex >= 0 && state.playIndex < n) ? state.playIndex : 0;

    const same = (!forceRebuild &&
      state.playOrderPlaylist === pl &&
      Array.isArray(state.playOrder) &&
      state.playOrder.length === n);

    if(same){
      const p = state.playOrder.indexOf(idx);
      if(p >= 0){
        state.orderPos = p;
        return;
      }
    }

    const rest = [];
    for(let i=0;i<n;i++){
      if(i !== idx) rest.push(i);
    }
    for(let i=rest.length-1;i>0;i--){
      const j = Math.floor(Math.random() * (i + 1));
      const tmp = rest[i];
      rest[i] = rest[j];
      rest[j] = tmp;
    }
    state.playOrder = [idx].concat(rest);
    state.orderPos = 0;
    state.playOrderPlaylist = pl;
  }

  function nextIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) + 1;
      if(p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const ni = (state.playIndex || 0) + 1;
    if(ni >= 0 && ni < state.playlist.length) return ni;
    return null;
  }

  function prevIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) - 1;
      if(p >= 0 && p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const pi = (state.playIndex || 0) - 1;
    if(pi >= 0 && pi < state.playlist.length) return pi;
    return null;
  }

  function setShuffleEnabled(on){
    state.shuffleEnabled = !!on;
    try{ localStorage.setItem("debripod_shuffle", state.shuffleEnabled ? "1" : "0"); }catch(e){}
    ensurePlayOrder(true);
    preloadNextAudio();
    updateWheelLabels();
  }

  function toggleShuffle(){
    setShuffleEnabled(!state.shuffleEnabled);
  }

  async function playIndex(i, forceShow){
    if(i < 0 || i >= state.playlist.length) return;
    if(typeof forceShow !== "boolean") forceShow = (nowPlaying.style.display === "block");
    const item = state.playlist[i];
    state.playIndex = i;
    await startAudioFromItem(item, state.playlist, i, forceShow);
  }

  function playNext(){
    if(isSearchStreamActive()){
      const ni = (state.streamQueueIndex || 0) + 1;
      if(ni >= 0 && ni < state.streamQueue.length){
        playStreamQueueIndex(ni, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const ni = nextIndexPeek();
    if(ni === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const np = (state.orderPos || 0) + 1;
      if(np >= 0 && np < state.playOrder.length) state.orderPos = np;
    }
    playIndex(ni);
  }

  function playPrev(){
    if(isSearchStreamActive()){
      const pi = (state.streamQueueIndex || 0) - 1;
      if(pi >= 0 && pi < state.streamQueue.length){
        playStreamQueueIndex(pi, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const pi = prevIndexPeek();
    if(pi === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const pp = (state.orderPos || 0) - 1;
      if(pp >= 0 && pp < state.playOrder.length) state.orderPos = pp;
    }
    playIndex(pi);
  }


  function playVideoIndex(i, forceShow, resumeTime){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length) return;
      if(i < 0 || i >= state.videoPlaylist.length) return;
      state.videoIndex = i;
      const it = state.videoPlaylist[i];
      startVideoFromItem(it, (typeof forceShow === "boolean" ? forceShow : true), (resumeTime || 0));
    }catch(e){}
  }

  function playVideoNext(){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        state.videoPlaylist = buildVideoPlaylistFromItems(state.items || []);
        state.videoIndex = 0;
      }
      const ni = (state.videoIndex || 0) + 1;
      if(ni >= 0 && ni < state.videoPlaylist.length){
        playVideoIndex(ni, true, 0);
      }
    }catch(e){}
  }

  function playVideoPrev(){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        state.videoPlaylist = buildVideoPlaylistFromItems(state.items || []);
        state.videoIndex = 0;
      }
      const pi = (state.videoIndex || 0) - 1;
      if(pi >= 0 && pi < state.videoPlaylist.length){
        playVideoIndex(pi, true, 0);
      }
    }catch(e){}
  }


  function wireAudio(el){
    el.addEventListener("timeupdate", ()=>{
      if(el !== activeAudio) return;
      const d = el.duration || 0;
      const t = el.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      lastfmMaybeScrobble(false);
      try{ updateBufferedBarFor(el); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{
        if(state.now && state.now.rootId && state.now.rel){
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!activeAudio.paused), "time");
        }
      }catch(e){}
    });
    el.addEventListener("ended", ()=>{
      if(el !== activeAudio) return;
      lastfmMaybeScrobble(true);
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = d || ((activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0);
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      clearBufferedBar();
      playNext();
    });
    el.addEventListener("play", ()=>{
      if(el !== activeAudio) return;
      try{ ensureVisualizerAudioGraphFor(el); }catch(e){}
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      npPillActivity(false);
    });
    el.addEventListener("pause", ()=>{
      if(el !== activeAudio) return;
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showNpPill(true);
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });
  }
  try{ ensurePlaybackAudioSession(); }catch(e){}
  wireAudio(audioMain);
  try{ ensureVisualizerFrameLoop(); }catch(e){}
  if(npVideo){
    npVideo.addEventListener("timeupdate", ()=>{
      if(!isVideoActive()) return;
      const d = npVideo.duration || 0;
      const t = npVideo.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ updateBufferedBarFor(npVideo); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!npVideo.paused), "time");
        }
      }catch(e){}
    });

    npVideo.addEventListener("play", ()=>{
      if(!isVideoActive()) return;
      try{ ensureVisualizerAudioGraphFor(npVideo); }catch(e){}
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      npPillActivity(false);
    });

    npVideo.addEventListener("pause", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showNpPill(true);
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = (npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0;
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });

    npVideo.addEventListener("ended", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = d || ((npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0);
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      if(isSearchStreamActive()) playNext();
    });
  }

  npSeek.addEventListener("input", ()=>{
    const m = wheelMedia();
    const d = (m && m.duration) ? m.duration : 0;
    if(d > 0){
      try{ m.currentTime = (parseInt(npSeek.value, 10) / 1000) * d; }catch(e){}
    }
  });

  // ===== views =====
  async function viewFolder(root, rel, label, push){
    showNowPlaying(false);
    await setView({
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        const js = await apiGet(url);
        const items = [];
        if(state.history.length || this.rel){
          items.push({kind:"up", label:".."});
        }
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaTop(root, push){
    showNowPlaying(false);
    await setView({
      kind: "metatop",
      label: "Browse",
      root: root,
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=top");
        const items = [];
        for(const c of (js.categories || [])){
          items.push({kind:"metacat", label:c.label, cat:c.key, root: root, badge: js.building ? "indexing" : ""});
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaList(root, level, value, label, push){
    showNowPlaying(false);
    await setView({
      kind: "metalist",
      label: label || level,
      root: root,
      level: level,
      value: value || "",
      load: async function(){
        const url = "/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=" + encodeURIComponent(this.level) + (this.value ? "&value=" + encodeURIComponent(this.value) : "");
        const js = await apiGet(url);
        const items = [];
        if(this.level === "playlists"){
          items.push({kind:"playlist_create", label:"Create playlist"});
          items.push({kind:"smart_playlist_create", label:"Create smart playlist"});
        }
        if(this.level === "playlist_tracks"){
          items.push({kind:"playlist_edit_entry", label:(isSmartPlaylistRel(this.value || "") ? "Edit rules" : "Edit"), rel:(this.value || ""), playlistLabel:(this.label || ""), root: root});
        }
        for(const it of (js.items || [])){
          if(it.kind === "info"){
            items.push({kind:"info", label: it.label || ""});
            continue;
          }
          const out = Object.assign({}, it);
          out.root = root;
          items.push(out);
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  function currentItem(){
    if(state.items.length === 0) return null;
    return state.items[state.sel] || null;
  }

  async function selectItem(forcedItem){
    const it = forcedItem || currentItem();
if(!it) return;
    if(it.kind === "info") return;

    if(it.kind === "libsearch_query" || it.kind === "libsearch_filter"){
      const field = (it.kind === "libsearch_filter") ? "filter" : "q";
      try{
        if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[], editField:"", editValue:""};
        state.libSearch.editField = field;
        state.libSearch.editValue = (typeof state.libSearch[field] === "string") ? state.libSearch[field] : "";
        renderList();
        try{
          const activeEdit = libList ? libList.querySelector(".ipodItem.sel .libInlineInput") : null;
          if(activeEdit){
            activeEdit.focus();
            activeEdit.click();
            const n = activeEdit.value.length;
            activeEdit.setSelectionRange(n, n);
          }
        }catch(e){}
      }catch(e){}
      return;
    }

    if(it.kind === "playlist_create"){
      beginPlaylistCreateEdit();
      return;
    }

    if(it.kind === "smart_playlist_create"){
      beginSmartPlaylistCreateEdit();
      return;
    }

    if(it.kind === "playlist_edit_name"){
      beginPlaylistRenameEdit();
      return;
    }

    if(it.kind === "playlist_edit_entry"){
      if(isSmartPlaylistRel(it.rel || "")){
        await viewSmartPlaylistRules(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }else{
        await viewPlaylistEditMenu(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }
      return;
    }

    if(it.kind === "smart_playlist_rules_entry"){
      const cur = state.current || {};
      await viewSmartPlaylistRules(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_save"){
      await saveSmartPlaylistRules();
      return;
    }

    if(it.kind === "smart_playlist_rules_cancel"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_edit_add"){
      const cur = state.current || {};
      const startRel = playlistBrowseStartRel(cur.playlistRel || "");
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", startRel, true);
      return;
    }

    if(it.kind === "playlist_edit_remove"){
      const cur = state.current || {};
      await viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }


    if(it.kind === "playlist_edit_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "playlist_edit_menu", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "smart_playlist_rules", true);
      return;
    }

    if(it.kind === "playlist_delete_no"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_delete_yes"){
      await confirmDeletePlaylist();
      return;
    }

    if(it.kind === "playlist_add_dir"){
      const cur = state.current || {};
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", it.rel || "", true);
      return;
    }

    if(it.kind === "playlist_add_selectall"){
      const cur = state.current || {};
      const rels = (state.items || []).filter(x => x && x.kind === "playlist_add_file" && !x.selected).map(x => x.rel).filter(Boolean);
      if(!rels.length) return;
      try{
        await playlistAddSongsToCurrentView(rels);
        if(cur._added){
          for(const rp of rels) cur._added.add(String(rp));
        }
        await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", cur.rel || "", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_add_file"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await playlistAddSongsToCurrentView([it.rel || ""]);
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_selectall"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const tracks = (state.items || []).filter(x => x && x.kind === "playlist_remove_track");
      let anyUnsel = false;
      for(const tr of tracks){
        if(tr && tr.rel && !cur.selected.has(String(tr.rel))){
          anyUnsel = true;
          break;
        }
      }
      if(anyUnsel){
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.add(String(tr.rel));
        }
      }else{
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.delete(String(tr.rel));
        }
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "playlist_remove_commit"){
      const cur = state.current || {};
      const rels = cur.selected ? Array.from(cur.selected.values()) : [];
      if(!rels.length) return;
      try{
        const res = await apiPost("/api/library/playlist_remove", {root_id: cur.root.id, rel: cur.playlistRel || "", tracks: rels});
        const js = (res && res.json) ? res.json : {};
        if(!res || !res.ok || !js.ok){
          throw new Error((js && js.error) ? js.error : "Failed to remove songs");
        }
        cur.selected = new Set();
        await viewMetaList(cur.root, "playlist_tracks", cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_track"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const rp = String(it.rel || "");
      if(rp){
        if(cur.selected.has(rp)) cur.selected.delete(rp);
        else cur.selected.add(rp);
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "np_playlist_close"){
      await closeNowPlayingPlaylistMode();
      return;
    }

    if(it.kind === "np_playlist_entry"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await addCurrentNowPlayingTrackToPlaylist(it.rel || "");
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        try{
          if(Array.isArray(it.pills) && it.pills.length){
            it.pills[0].text = "âœ“";
          }
        }catch(e){}
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "random"){
      const idxs = [];
      for(let i=0;i<state.items.length;i++){
        const cand = state.items[i];
        if(_randomEligibleItem(cand)) idxs.push(i);
      }
      if(!idxs.length) return;
      const ri = idxs[Math.floor(Math.random() * idxs.length)];
      state.sel = ri;
      renderList();
      try{ await new Promise(r=>setTimeout(r, 20)); }catch(e){}
      await selectItem();
      return;
    }


    if(it.kind === "up"){
      await goBack();
      return;
    }
    
    if(it.kind === "libsearch_entry"){
      await viewLibSearch(true);
      return;
    }



if(it.kind === "libtasks_entry"){
  await viewLibTasks(true);
  return;
}

    if(it.kind === "libinfo_entry"){
      await viewLibInfo(true);
      return;
    }

    if(it.kind === "libsearch_action"){
      if(it.label === "Clear"){
        state.libSearch.q = "";
        state.libSearch.filter = "";
        state.libSearch.engine = "combined";
        state.libSearch.cache_key = "";
        state.libSearch.result_source = "combined";
        state.libSearch.results = [];
        state.libSearch.knaben_results = [];
        state.libSearch.slsk_users = [];
        state.libSearch.last_count = 0;
        libSetStatus("", "");
        await viewLibSearch(false);
        return;
      }
      if(it.label === "Search history"){
        await viewLibSearchHistory(true);
        return;
      }
      if(it.engine){
        await libDoSearch(it.engine, state.libSearch.q || "");
        return;
      }
    }

    
    if(it.kind === "libinfo_action"){
      if(it.action === "reindex"){
        await doLibraryReindex();
        await viewLibInfo(false);
        return;
      }
      if(it.action === "lastfm_login"){
        await startLastfmLoginFlow();
        await viewLibInfo(false);
        return;
      }
      if(it.action === "force_fullscreen"){
        await forceFullscreenOn();
        // keep menu open
        await viewLibInfo(false);
        return;
      }
      if(it.action === "binds_menu"){
        await viewLibBinds(true);
        return;
      }
      if(it.action === "toggle_visualizer"){
        setVisualizerEnabled(!visualizerEnabled);
        await viewLibInfo(false);
        return;
      }
    }

if(it.kind === "libsearch_history_action"){
      if(it.action === "clear_history"){
        try{
          const res = await apiPost("/api/search_history/clear", {});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to clear history");
          }
        }catch(e){
          alert(String(e && e.message ? e.message : e));
        }
        await viewLibSearchHistory(false);
        return;
      }
    }

    if(it.kind === "libsearch_history_entry"){
      state.pendingLibSearch = {engine: it.engine || "", q: it.q || ""};
      await goBack();
      return;
    }

    if(it.kind === "libsearch_result"){
      await viewLibSearchResultDetails(true, it);
      return;
    }

    if(it.kind === "libsearch_file_action"){
      const view = state.current || {};
      if((it.action === "result_selectall" || it.action === "result_clear" || it.action === "result_download" || it.action === "result_browse" || it.action === "result_stream") && view._searchResult){
        const target = view._searchResult;
        const src = String(target.source || "");
        if(it.action === "result_browse"){
          if(src === "soulseek"){
            target.loadingBrowse = true;
            libSearchRebuildFilesList(target.buildItems());
            try{
              await viewLibSearchSlskBrowse(true, String((target.result && target.result.user) || ""), String((target.result && target.result.directory) || ""));
            }catch(e){
              target.loadingBrowse = false;
              libSearchRebuildFilesList(target.buildItems());
              throw e;
            }
          }else if(src === "youtube"){
            await viewLibSearchYouTubeChannel(true, target.result || {});
          }
          return;
        }
        if(it.action === "result_selectall"){
          const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file" && x.selectable);
          let anyUnsel = false;
          for(const v of visible){
            const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
            if(key && !target.selected.has(key)){ anyUnsel = true; break; }
          }
          target.downloadQueued = false;
          if(anyUnsel){
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
              if(!key) continue;
              target.selected.set(key, {key:key, remote_path:String(v.remote_path || ""), file_id:String(v.file_id || ""), itag:String(v.itag || v.format_id || v.file_id || ""), format_id:String(v.format_id || v.itag || v.file_id || ""), size:Number(v.size || 0), name:String(v.label || ""), source:String(v.source || src || ""), ext:String(v.ext || ((((v.pills || [])[1] && typeof (v.pills || [])[1] === "string") ? (v.pills || [])[1] : "") || "")), quality:String(v.quality || ""), bitrate:String(v.bitrate || ""), media:String(v.media || ""), direct_url:String(v.direct_url || ""), url:String((target.result && target.result.url) || "")});
            }
          }else{
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
              if(key) target.selected.delete(key);
            }
          }
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_clear"){
          target.selected = new Map();
          target.downloadQueued = false;
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_stream"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Preparing stream", "");
          try{
            const rr = target.result || {};
            const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path || "", file_id:x.file_id || "", itag:x.itag || x.format_id || x.file_id || "", format_id:x.format_id || x.itag || x.file_id || "", size:x.size || 0, name:x.name || "", source:x.source || src || "", ext:x.ext || "", quality:x.quality || "", bitrate:x.bitrate || "", media:x.media || "", direct_url:x.direct_url || "", url:x.url || rr.url || ""}));
            const res = await apiPost("/api/libsearch/stream_selected", {
              source: src,
              torrent_id: rr.torrent_id || "",
              magnet: rr.magnet || "",
              url: rr.url || "",
              channel: rr.channel || rr.user || "",
              thumbnail: rr.thumbnail || rr.art || "",
              title: rr.title || rr.directory_title || rr.directory || "Search stream",
              selected: sel
            });
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to prepare stream");
            libSetFileStatus("", "");
            await startSearchStreamQueue(js.items || [], 0);
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
        if(it.action === "result_download"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Queuing", "");
          try{
            if(src === "knaben"){
              const ids = Array.from(target.selected.values()).map(x=>String(x.file_id || "")).filter(Boolean);
              const rr = target.result || {};
              const res = await apiPost("/api/rd/enqueue_selected", {torrent_id: rr.torrent_id || "", file_ids: ids, title: rr.title || "Knaben item", magnet: rr.magnet || ""});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
            }else if(src === "youtube"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({
                file_id:String(x.file_id || x.itag || x.format_id || ""),
                itag:String(x.itag || x.format_id || x.file_id || ""),
                format_id:String(x.format_id || x.itag || x.file_id || ""),
                name:String(x.name || x.title || x.label || ""),
                title:String(x.title || x.name || x.label || ""),
                ext:String(x.ext || ""),
                media:String(x.media || ""),
                direct_url:String(x.direct_url || ""),
                url:String(x.url || rr.url || ""),
                size:Number(x.size || 0)
              })).filter(x=>x.itag || x.format_id || x.file_id || x.url);
              const res = await apiPost("/api/youtube/enqueue", {
                title: rr.title || rr.directory_title || rr.name || "YouTube",
                url: rr.url || "",
                selected: sel
              });
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              target.downloadQueued = true;
            }else if(src === "soulseek"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path, size:x.size || 0})).filter(x=>x.remote_path);
              const dirPath = String(rr.directory || "");
              const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
              const title = "Soulseek: " + String(rr.user || "") + " " + dirBase;
              const res = await apiPost("/api/soulseek/enqueue", {user: rr.user || "", directory: dirPath, title: title, files: sel});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              for(const x of sel){
                const key = String(x.remote_path || "");
                if(!key) continue;
                target.selected.set(key, {key:key, remote_path:key, size:Number(x.size || 0), download_state:"queued"});
                try{
                  const srcFiles = Array.isArray(rr.files) ? rr.files : [];
                  const hit = srcFiles.find(fx => String((fx && fx.remote_path) || "") === key);
                  if(hit) hit.download_state = "queued";
                }catch(e){}
              }
            }
            libSetFileStatus("", "");
            libSearchRebuildFilesList(target.buildItems());
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
      }
      if(it.action === "rd_selectall" && view._rd){
        const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file");
        let anyUnsel = false;
        for(const v of visible){
          if(v && v.file_id && !view._rd.selected.has(String(v.file_id))){
            anyUnsel = true;
            break;
          }
        }
        if(anyUnsel){
          for(const v of visible){
            if(v && v.file_id) view._rd.selected.add(String(v.file_id));
          }
        }else{
          for(const v of visible){
            if(v && v.file_id) view._rd.selected.delete(String(v.file_id));
          }
        }
        libSearchRebuildFilesList(view._rd.buildItems());
        return;
      }
      if(it.action === "rd_clear" && view._rd){
        view._rd.selected = new Set();
        libSearchRebuildFilesList(view._rd.buildItems());
        return;
      }
      if(it.action === "rd_download" && view._rd){
        if(!view._rd.selected || view._rd.selected.size === 0){
          libSetFileStatus("Select files", "warn");
          return;
        }
        libSetFileStatus("Queuing", "");
        try{
          const ids = Array.from(view._rd.selected.values());
          const res = await apiPost("/api/rd/enqueue_selected", {torrent_id: view._rd.torrent_id, file_ids: ids, title: view._rd.title || "Knaben item", magnet: view._rd.magnet || ""});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to queue download");
          }
          libSetFileStatus("", "");
        }catch(e){
          libSetFileStatus("Error", "warn");
          alert(String(e && e.message ? e.message : e));
        }
        return;
      }

      if(it.action === "slsk_browse_user" && view._slsk){
        view._slsk.loadingBrowse = true;
        libSearchRebuildFilesList(view._slsk.buildItems());
        try{
          await viewLibSearchSlskBrowse(true, view._slsk.user || "", view._slsk.directory || "");
        }catch(e){
          view._slsk.loadingBrowse = false;
          libSearchRebuildFilesList(view._slsk.buildItems());
          throw e;
        }
        return;
      }
      if(it.action === "slsk_browse_up" && view._slskbrowse){
        view._slskbrowse.current_dir = slskBrowseParentPath(view._slskbrowse.current_dir || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
        return;
      }
      if(it.action === "slsk_selectall" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.downloadQueued = false;
        const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file");
        let anyUnsel = false;
        for(const v of visible){
          if(v && v.remote_path && !target.selected.has(String(v.remote_path))){
            anyUnsel = true;
            break;
          }
        }
        if(anyUnsel){
          for(const v of visible){
            if(v && v.remote_path){
              const rp = String(v.remote_path);
              target.selected.set(rp, {remote_path: rp, size: Number(v.size || 0)});
            }
          }
        }else{
          for(const v of visible){
            if(v && v.remote_path) target.selected.delete(String(v.remote_path));
          }
        }
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_clear" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.selected = new Map();
        target.downloadQueued = false;
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_download" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        if(!target.selected || target.selected.size === 0){
          libSetFileStatus("Select files", "warn");
          return;
        }
        libSetFileStatus("Queuing", "");
        try{
          const sel = Array.from(target.selected.values()).map(x=>({remote_path: x.remote_path, size: x.size || 0}));
          const dirPath = String((target.directory || target.current_dir) || "");
          const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
          const title = "Soulseek: " + (target.user || "") + " " + dirBase;
          const res = await apiPost("/api/soulseek/enqueue", {user: target.user || "", directory: dirPath, title: title, files: sel});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to queue download");
          }
          target.downloadQueued = true;
          if(typeof target.buildItems === "function") libSearchRebuildFilesList(target.buildItems());
          libSetFileStatus("", "");
        }catch(e){
          libSetFileStatus("Error", "warn");
          alert(String(e && e.message ? e.message : e));
        }
        return;
      }
    }

    if(it.kind === "libsearch_file"){
      if(it.selectable){
        try{
          if(typeof it.onToggle === "function") it.onToggle();
          else it.selected = !it.selected;
        }catch(e){}
        const view = state.current || {};
        if(view._searchResult && typeof view._searchResult.buildItems === "function"){
          libSearchRebuildFilesList(view._searchResult.buildItems());
        }else if(view._rd && typeof view._rd.buildItems === "function"){
          libSearchRebuildFilesList(view._rd.buildItems());
        }else if(view._slsk && typeof view._slsk.buildItems === "function"){
          libSearchRebuildFilesList(view._slsk.buildItems());
        }else if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
          libSearchRebuildFilesList(view._slskbrowse.buildItems());
        }else{
          renderList();
        }
        return;
      }
    }

    if(it.kind === "slsk_browse_dir") {
      const view = state.current || {};
      if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
        view._slskbrowse.current_dir = String(it.browse_path || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
      }
      return;
    }



if(it.kind === "libtasks_action"){
  if(it.action === "clear_all"){
    await apiPost("/api/tasks/clear_all", {});
    try{
      const js = await apiGet("/api/tasks");
      state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
    }catch(e){
      state.libTasks.tasks = [];
    }
    libTasksRefreshList(false);
    return;
  }
}

if(it.kind === "libtask_entry"){
  await viewLibTask(true, it.task_id || "");
  return;
}

if(it.kind === "libtask_action"){
  const view = state.current || {};
  const tid = String(view.task_id || "");
  if(!tid) return;

  if(it.action === "selectall"){
    const visible = (state.items || []).filter(x=>x && x.kind === "libtask_file");
    let anyUnsel = false;
    for(const v of visible){
      if(v && v.file_id && view.selected && !view.selected.has(String(v.file_id))){
        anyUnsel = true; break;
      }
    }
    if(!view.selected) view.selected = new Set();
    if(anyUnsel){
      for(const v of visible){
        if(v && v.file_id) view.selected.add(String(v.file_id));
      }
    }else{
      for(const v of visible){
        if(v && v.file_id) view.selected.delete(String(v.file_id));
      }
    }
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "clear"){
    view.selected = new Set();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "pause_selected" || it.action === "cancel_selected"){
    if(!view.selected || view.selected.size === 0){
      return;
    }
    const action = (it.action === "pause_selected") ? "pause" : "cancel";
    for(const fid of Array.from(view.selected)){
      try{
        await apiPost("/api/tasks/file_action", {task_id: tid, file_id: String(fid), action: action});
      }catch(e){}
    }
    await libTasksPollTick();
    return;
  }

  if(it.action === "pause_task"){
    await apiPost("/api/tasks/pause", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "resume_task"){
    await apiPost("/api/tasks/resume", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "cancel_task"){
    await apiPost("/api/tasks/cancel", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "clear_task"){
    await apiPost("/api/tasks/clear", {task_id: tid});
    await libTasksPollTick();
    return;
  }
}

if(it.kind === "libtask_file"){
  if(it.selectable){
    try{
      if(typeof it.onToggle === "function") it.onToggle();
      else it.selected = !it.selected;
    }catch(e){}
    const view = state.current || {};
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }
}

if(it.kind === "root"){
      state.root = it.root;
      setHeader();
      if((it.root.mode || "folders") === "metadata"){
        await viewMetaTop(it.root, true);
      }else{
        await viewFolder(it.root, "", "", true);
      }
      return;
    }
    if(it.kind === "nowplaying"){
      await resumeFromServerNow(true);
      showNowPlaying(true);
      return;
    }
    if(it.kind === "recently"){
      await viewRecently(true);
      return;
    }
    if(it.kind === "recent_item"){
      // Restore the last browsing context first, then play
      const nav = (it.nav && typeof it.nav === "object") ? it.nav : {};
      if(nav && nav.root_id){
        await openNavContext(nav);
      }else{
        // fallback to folder containing the file
        try{
          const cfg = await loadConfig();
          const root = (cfg.roots || []).find(r => r.id === it.rootId);
          if(root){
            let folderRel = "";
            try{
              const parts = (it.rel || "").split("/");
              parts.pop();
              folderRel = parts.join("/");
            }catch(e){ folderRel = ""; }
            state.root = root;
            state.history = [];
            state.current = null;
            if(folderRel){
              const segs = folderRel.split("/");
              state.history.push(folderViewObj(root, "", ""));
              for(let i = 0; i < segs.length - 1; i++){
                const r = segs.slice(0, i + 1).join("/");
                state.history.push(folderViewObj(root, r, segs[i]));
              }
            }
            showNowPlaying(false);
            await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
          }
        }catch(e){}
      }

      // If selecting current now playing while it is still playing, just open it
      const sn = state.serverNow;
      const sameAsServer = (sn && sn.root_id === it.rootId && sn.rel === it.rel && (sn.media || "") === it.media);
      if(it.media === "audio"){
        const itemObj = {kind:"file", media:"audio", root:{id: it.rootId}, rel: it.rel, label: it.label};
        let pl = null;
        let idx = -1;
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            pl = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "audio"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
            idx = isFinite(it.playlist.index) ? Number(it.playlist.index) : 0;
          }
        }catch(e){ pl = null; idx = -1; }
        if(!pl || !pl.length){
          pl = buildPlaylistFromItems(state.items);
          try{
            idx = pl.findIndex(x => x.rel === itemObj.rel && x.root && x.root.id === itemObj.root.id);
          }catch(e){ idx = -1; }
        }
        if(!pl || !pl.length){
          pl = [itemObj];
          idx = 0;
        }else{
          idx = Math.max(0, Math.min(pl.length - 1, (idx >= 0 ? idx : 0)));
        }
        const resume = (sameAsServer && state.serverNow && state.serverNow.playing && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : 0;
        if(itemObj.root.id === "__search_stream__") {
          state.streamQueue = pl;
          state.streamQueueIndex = idx;
        }
        await startAudioFromItem(itemObj, pl, idx, true, resume);
        return;
      }
      if(it.media === "video"){
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            state.videoPlaylist = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "video"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
            const vi = isFinite(it.playlist.index) ? Number(it.playlist.index) : 0;
            state.videoIndex = Math.max(0, Math.min(state.videoPlaylist.length - 1, vi));
          }
        }catch(e){}
        const resume = (sameAsServer && state.serverNow && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : ((it.position && isFinite(it.position)) ? Number(it.position) : 0);
        if(it.rootId === "__search_stream__") {
          state.streamQueue = Array.isArray(state.videoPlaylist) ? state.videoPlaylist.slice() : [];
          state.streamQueueIndex = state.videoIndex || 0;
        }
        await startVideoFromItem({kind:"file", media:"video", root:{id: it.rootId}, rel: it.rel, label: it.label, streamed: !!it.streamed, source: it.source || "", ext: it.ext || "", quality: it.quality || ""}, true, resume);
        return;
      }
      return;
    }
    if(it.kind === "dir"){
      await viewFolder(it.root, it.rel, it.label, true);
      return;
    }
    if(it.kind === "metacat"){
      if(it.cat === "folders"){
        await viewFolder(it.root, "", "", true);
        return;
      }
      if(it.cat === "artists"){
        await viewMetaList(it.root, "artists", "", it.label, true);
        return;
      }
      if(it.cat === "albums"){
        await viewMetaList(it.root, "albums", "", it.label, true);
        return;
      }
      if(it.cat === "songs"){
        await viewMetaList(it.root, "songs", "", it.label, true);
        return;
      }
      if(it.cat === "liked_songs"){
        await viewMetaList(it.root, "liked_songs", "", it.label, true);
        return;
      }
      if(it.cat === "playlists"){
        await viewMetaList(it.root, "playlists", "", it.label, true);
        return;
      }
      if(it.cat === "genres"){
        await viewMetaList(it.root, "genres", "", it.label, true);
        return;
      }
      if(it.cat === "videos"){
        await viewMetaList(it.root, "videos", "", it.label, true);
        return;
      }
      return;
    }
    if(it.kind === "artist"){
      await viewMetaList(it.root, "albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "album"){
      await viewMetaList(it.root, "tracks", it.value, it.label, true);
      return;
    }
    if(it.kind === "genre"){
      await viewMetaList(it.root, "genre_albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "playlist"){
      await viewMetaList(it.root, "playlist_tracks", it.rel || "", it.label, true);
      return;
    }
    if(it.kind === "track"){
      const pl = buildPlaylistFromItems(state.items);
      const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
      await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
      return;
    }
    if(it.kind === "file"){
      if(it.media === "video"){
        await startVideoFromItem(it, true);
        return;
      }
      if(it.media === "audio"){
        const pl = buildPlaylistFromItems(state.items);
        const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
        await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
        return;
      }
    }
  }

  // ===== wheel controls =====
  const wheel = document.getElementById("wheel");
  const btnMenu = document.getElementById("btnMenu");
  const btnRev = document.getElementById("btnRev");
  const btnFwd = document.getElementById("btnFwd");
  const btnPlay = document.getElementById("btnPlay");
  const btnCenter = document.getElementById("btnCenter");

  
  const copyStreamBtn = document.getElementById("copyStreamBtn");
  if(copyStreamBtn){
    copyStreamBtn.addEventListener("click", ()=>{
      const el = document.getElementById("directStreamLink");
      if(!el) return;
      try{
        el.focus();
        el.select();
        el.setSelectionRange(0, el.value.length);
      }catch(e){}
      const txt = el.value;
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).catch(()=>{ try{ document.execCommand("copy"); }catch(e){} });
      }else{
        try{ document.execCommand("copy"); }catch(e){}
      }
    });
  }
btnMenu.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return;
    vibeTick();
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block") npPillActivity(false);
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive() && lastfmIsEnabled()){
      lastfmToggleLoved(lastfmState.meta);
      resetSeekIdle();
      return;
    }
    goBack();
  });

  function playButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive()){
      toggleShuffle();
      resetSeekIdle();
    }else{
      togglePlay();
    }
  }

  function revButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode){
      seek(-15);
      resetSeekIdle();
    }else{
      if(isVideoActive()){
        playVideoPrev();
      }else{
        playPrev();
      }
    }
  }

  function fwdButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode){
      seek(15);
      resetSeekIdle();
    }else{
      if(isVideoActive()){
        playVideoNext();
      }else{
        playNext();
      }
    }
  }

  btnPlay.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); playButtonPress(); });
  btnRev.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); revButtonPress(); });
  btnFwd.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); fwdButtonPress(); });

  function centerPress(){
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        if(!seekChanged && !isVideoActive()){
          const p = viewNowPlayingPlaylistMode();
          if(p && typeof p.catch === "function") p.catch(()=>{});
        }else{
          commitSeekMode();
        }
      }else{
        enterSeekMode();
      }
      return;
    }
    selectItem();
  }

  btnCenter.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); centerPress(); });

  updateWheelLabels();

  // rotation scroll on wheel ring
  let wheelPointerDown = false;
  let dragging = false;
  let lastAngle = 0;
  let accum = 0;
  let wheelStartX = 0;
  let wheelStartY = 0;
  let wheelDownOnButton = false;
  let wheelClickSuppressUntil = 0;
  const step = 18;
  const dragPx = 8;

  function isWheelClickSuppressed(){
    return Date.now() < wheelClickSuppressUntil;
  }
  function suppressWheelClicks(ms){
    const dur = Number(ms || 0);
    const until = Date.now() + (dur > 0 ? dur : 0);
    if(until > wheelClickSuppressUntil) wheelClickSuppressUntil = until;
  }

  function angleFromEvent(ev){
    const rect = wheel.getBoundingClientRect();
    const cx = rect.left + rect.width/2;
    const cy = rect.top + rect.height/2;
    const x = (ev.clientX - cx);
    const y = (ev.clientY - cy);
    return Math.atan2(y, x) * 180 / Math.PI;
  }

  function normDelta(a, b){
    let d = a - b;
    while(d > 180) d -= 360;
    while(d < -180) d += 360;
    return d;
  }

  wheel.addEventListener("pointerdown", (ev)=>{
    wheelPointerDown = true;
    dragging = false;
    wheelDownOnButton = false;
    try{
      if(ev.target === btnCenter) wheelDownOnButton = true;
      else if(ev.target && ev.target.closest && ev.target.closest(".wheelBtn")) wheelDownOnButton = true;
    }catch(e){
      wheelDownOnButton = false;
    }
    wheelStartX = ev.clientX;
    wheelStartY = ev.clientY;
    lastAngle = angleFromEvent(ev);
    accum = 0;

    // Avoid capturing immediately so taps on buttons stay reliable.
    // If the user drags, we will capture on move after a small threshold.
  }, {passive:false});

  wheel.addEventListener("pointermove", (ev)=>{
    if(!wheelPointerDown) return;

    if(!dragging){
      const dx = (ev.clientX - wheelStartX);
      const dy = (ev.clientY - wheelStartY);
      const dist = Math.hypot(dx, dy);
      if(dist < dragPx) return;

      dragging = true;
      if(wheelDownOnButton){
        // User started on a button area but is dragging, treat as wheel rotation.
        suppressWheelClicks(450);
      }
      try{ wheel.setPointerCapture(ev.pointerId); }catch(e){}
      try{ ev.preventDefault(); }catch(e){}
    }

    if(!dragging) return;

    const ang = angleFromEvent(ev);
    const d = normDelta(ang, lastAngle);
    lastAngle = ang;
    accum += d;

    if(nowPlaying.style.display === "block"){
      if(seekMode){
        showNpPill(true);
      }else{
        npPillActivity(false);
      }
      if(Math.abs(accum) >= step){
        if(seekMode){
          adjustSeekPreview(accum > 0 ? 1 : -1);
        }else{
          adjustVolumeStep(accum > 0 ? 1 : -1);
        }
        accum = 0;
      }
      return;
    }

    if(Math.abs(accum) >= step){
      scrollSel(accum > 0 ? 1 : -1);
      accum = 0;
    }
  }, {passive:false});

  function wheelPointerEnd(){
    wheelPointerDown = false;
    dragging = false;
    wheelDownOnButton = false;
  }

  wheel.addEventListener("pointerup", wheelPointerEnd, {passive:false});
  wheel.addEventListener("pointercancel", wheelPointerEnd, {passive:false});

  // keyboard and mouse wheel bindings
  window.addEventListener("wheel", (ev)=>{
    // Let normal browser zoom and text input scrolling work.
    if(ev.ctrlKey) return;
    const tgt = ev.target;
    if(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}


    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    ev.preventDefault();
    const dir = ev.deltaY > 0 ? 1 : -1;
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        adjustSeekPreview(dir);
      }else{
        adjustVolumeStep(dir);
      }
    }else{
      scrollSel(dir);
    }
  }, {passive:false});

  window.addEventListener("keydown", (ev)=>{

    // Don't hijack typing inside inputs/textareas/selects/contenteditable elements
    const tgt = ev.target;
    if(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    const k = ev.key;

    // iPod clickwheel shortcuts
    // w = top, a = left, s = middle, space = bottom, d = right
    if(k === "w" || k === "W"){
      ev.preventDefault();
      if(state.current && state.current.kind === "np_playlist_add") return;
      goBack();
    }else if(k === "a" || k === "A"){
      ev.preventDefault();
      revButtonPress();
    }else if(k === "s" || k === "S"){
      ev.preventDefault();
      centerPress();
    }else if(k === " "){
      ev.preventDefault();
      if(state.current && state.current.kind === "np_playlist_add") return;
      playButtonPress();
    }else if(k === "d" || k === "D"){
      ev.preventDefault();
      fwdButtonPress();
    }else if(k === "q" || k === "Q"){
      ev.preventDefault();
      scrollSel(-1);
    }else if(k === "e" || k === "E"){
      ev.preventDefault();
      scrollSel(1);
    }else if(k === "ArrowUp"){
      ev.preventDefault();
      if(nowPlaying.style.display === "block"){
        if(seekMode){
          adjustSeekPreview(-1);
        }else{
          adjustVolumeStep(1);
        }
      }else{
        scrollSel(-1);
      }
    }else if(k === "ArrowDown"){
      ev.preventDefault();
      if(nowPlaying.style.display === "block"){
        if(seekMode){
          adjustSeekPreview(1);
        }else{
          adjustVolumeStep(-1);
        }
      }else{
        scrollSel(1);
      }
    }
  });



async function maybeOpenFromUrl(){
  try{
    const p = new URLSearchParams(location.search || "");
    const rid = (p.get("root_id") || "").trim();
    if(!rid) return;
    const rel = (p.get("rel") || "").trim();
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(r => r.id === rid);
    if(!root) return;
    await viewFolder(root, rel, rel ? rel.split("/").pop() : root.name, false);
  }catch(e){}
}


  function updateTopbarVar(){
    try{
      const tb = document.querySelector(".topbar");
      const h = tb ? tb.getBoundingClientRect().height : 0;
      document.documentElement.style.setProperty("--topbarH", (h ? (h + "px") : "0px"));
    }catch(e){}
  }
  window.addEventListener("resize", updateTopbarVar);
  window.addEventListener("load", syncWheelZoneHeight);
  updateTopbarVar();
  syncWheelZoneHeight();


  // start
  (async ()=>{
    await showRoots();
    await maybeOpenFromUrl();
    syncWheelZoneHeight();
  })().catch(()=>{});
})();

