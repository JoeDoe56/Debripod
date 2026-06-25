function currentNowPlayingArtSrc(){
  try{
    if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.currentSource){
      return nowPlayingArtSrcValue(DebriPod.albumArtTexture.currentSource() || "");
    }
  }catch(e){
  }
  return "";
}

function setNowPlayingArtSrc(src, opts){
  try{
    if(!npArt) return;
    const v = nowPlayingArtSrcValue(src);
    const prevKey = nowPlayingArtCompareKey(currentNowPlayingArtSrc());
    const nextKey = nowPlayingArtCompareKey(v);
    const artChanged = prevKey !== nextKey;
    if(artChanged){
      try{
        const renderer = typeof liquidGlassRendererByKey === "function" ? liquidGlassRendererByKey("npOverlay") : null;
        if(renderer) renderer._npOverlaySourceKey = "";
      }catch(e){}
    }
    const sourceImg = document.getElementById("npArtLiquidSource");
    if(sourceImg && !sourceImg.__npLiquidSourceBound){
      sourceImg.__npLiquidSourceBound = true;
      try{ sourceImg.crossOrigin = "anonymous"; }catch(e){}
      sourceImg.addEventListener("load", ()=>{
        try{
          if(typeof forceNpOverlayGlassRender === "function") forceNpOverlayGlassRender("np art image loaded", true);
          else if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
        }catch(e){}
      }, {passive:true});
      sourceImg.addEventListener("error", ()=>{
        try{
          if(typeof forceNpOverlayGlassRender === "function") forceNpOverlayGlassRender("np art image unavailable", true);
          else if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
        }catch(e){}
      }, {passive:true});
    }
    if(sourceImg && !v && sourceImg.getAttribute("src")){
      sourceImg.removeAttribute("src");
      try{
        if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
      }catch(e){}
    }else if(sourceImg && v && (sourceImg.getAttribute("src") || "") !== v) sourceImg.src = v;
    else if(sourceImg && sourceImg.complete && sourceImg.naturalWidth && sourceImg.naturalHeight){
      try{
        if(typeof forceNpOverlayGlassRender === "function") forceNpOverlayGlassRender("np art image ready", true);
        else if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
      }catch(e){}
    }
    if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.setSource){
      DebriPod.albumArtTexture.setSource(v, opts || {});
    }
    try{
      if(window.DebriPod && DebriPod.albumArtTexture && DebriPod.albumArtTexture.renderGlassSourceCanvas){
        DebriPod.albumArtTexture.renderGlassSourceCanvas();
      }
    }catch(e){}
    recaptureLiquidGlassElement(npArt);
    if(artChanged){
      try{
        if(typeof forceNpOverlayGlassRender === "function") forceNpOverlayGlassRender("np art changed", true);
        else if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
      }catch(e){}
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
  var a = String(artist || "").trim();
  var b = String(album || "").trim();
  if(a && b) return '<span class="artistStrong">' + escapeHtml(a) + '</span>   ' + escapeHtml(b);
  if(a) return '<span class="artistStrong">' + escapeHtml(a) + '</span>';
  return escapeHtml(b);
}

function setNowPlayingOverlayText(meta, fallbackLabel){
  var m = meta || {};
  try{ npTitle.textContent = m.title || fallbackLabel || "Track"; }catch(e){}
  try{ npSub.innerHTML = artistAlbumHtml(m.artist || "", m.album || ""); }catch(e){}
  try{ if(npTech) npTech.textContent = m.tech || ""; }catch(e){}
  try{ if(nowPlaying && nowPlaying.style.display === "block") setHeader(); }catch(e){}
  scheduleLiquidGlassRender();
}

function refreshNowPlayingSurfaceAfterDisplay(reason){
  try{
    if(!nowPlaying || nowPlaying.style.display !== "block") return;
    const run = ()=>{
      try{
        if(window.DebriPod && DebriPod.albumArtTexture){
          if(DebriPod.albumArtTexture.renderToCanvas) DebriPod.albumArtTexture.renderToCanvas(npArt);
          if(DebriPod.albumArtTexture.renderGlassSourceCanvas) DebriPod.albumArtTexture.renderGlassSourceCanvas();
        }
      }catch(e){}
      try{ recaptureLiquidGlassElement(npArt); }catch(e){}
      try{
        if(typeof forceNpOverlayGlassRender === "function") forceNpOverlayGlassRender(reason || "np display refresh", true);
        else if(typeof scheduleNpOverlayGlassRender === "function") scheduleNpOverlayGlassRender();
      }catch(e){}
      try{ scheduleLiquidGlassRender(); }catch(e){}
    };
    requestAnimationFrame(()=> requestAnimationFrame(run));
    setTimeout(run, 90);
    setTimeout(run, 240);
  }catch(e){}
}

function isNpPillShown(){
  try{
    return !!(npOverlayPill && npPillVisible && !npOverlayPill.classList.contains("npPillHidden"));
  }catch(e){
    return false;
  }
}

async function updateNowPlayingDisplay(meta, fallbackLabel, opts){
  var m = meta || {};
  var options = opts || {};
  var nextArt = nowPlayingArtSrcValue(m.art);
  var currentArt = currentNowPlayingArtSrc();
  var currentArtKey = nowPlayingArtCompareKey(currentArt);
  var nextArtKey = nowPlayingArtCompareKey(nextArt);
  var animateArt = !!(options.animateArt && npArt && currentArtKey && nextArtKey && currentArtKey !== nextArtKey);
  var animatePill = false;
  sampleThemeFromArt(nextArt);
  var swapMs = 220;

  try{ if(npPillSwapTimer) clearTimeout(npPillSwapTimer); }catch(e){}
  npPillSwapTimer = null;

  if(animatePill){
    try{
      npOverlayPill.classList.add("npPillSwapHidden");
      scheduleNpOverlayGlassRender();
      animateNpOverlayGlassTransition("np pill swap out", swapMs);
    }catch(e){}
  }

  setNowPlayingArtSrc(nextArt, {animate: animateArt, duration: swapMs});

  if(animatePill){
    npPillSwapTimer = setTimeout(()=>{
      try{ setNowPlayingOverlayText(m, fallbackLabel); }catch(e){}
      requestAnimationFrame(()=>{
        try{
          if(npOverlayPill) npOverlayPill.classList.remove("npPillSwapHidden");
          scheduleNpOverlayGlassRender();
          animateNpOverlayGlassTransition("np pill swap in", swapMs);
        }catch(e){}
      });
      npPillSwapTimer = null;
    }, swapMs);
  }else{
    setNowPlayingOverlayText(m, fallbackLabel);
  }
  refreshNowPlayingSurfaceAfterDisplay("np display updated");
}

function showNpPill(pinned, reason){
  var effectivePinned = !!pinned || !!npPillPinned;
  setNpPillVisible(true, reason || "show", pinned ? true : undefined);
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
        setNpPillVisible(false, "auto hide", false);
      }catch(e){}
    }, (ms || 2500));
  }catch(e){}
}

function npPillActivity(pinned){
  var effectivePinned = !!pinned || !!npPillPinned;
  showNpPill(effectivePinned, pinned ? "activity pinned" : "activity");
  if(!effectivePinned) scheduleHideNpPill(2500);
}


function showProgressBar(){
  try{
    npProgressWrap.style.display = "block";
    npVolumeWrap.style.display = "none";
    scheduleNpOverlayGlassRender();
  }catch(e){}
}

function showVolumeBar(){
  try{
    npProgressWrap.style.display = "none";
    npVolumeWrap.style.display = "block";
    if(npVolumeFill) npVolumeFill.style.width = Math.round(userVol * 100) + "%";
    scheduleNpOverlayGlassRender();
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
  var m = wheelMedia();
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
  var m = wheelMedia();
  var d = (m && m.duration) ? m.duration : 0;
  if(d > 0){
    try{
      if(m) m.currentTime = Math.max(0, Math.min(d, seekPreview));
    }catch(e){}
  }
  cancelSeekMode();
}

function wheelLabelSvg(name, active){
  var filled = !!active;
  var icon = (b64, cls='') => {
    const className = 'wheelSvgIcon' + (cls ? ' ' + cls : '');
    const src = 'data:image/svg+xml;base64,' + b64;
    const layer = '<span class="' + className + '" aria-hidden="true" style="-webkit-mask-image:url(' + src + ');mask-image:url(' + src + ')"></span>';
    return '<span class="glassGlyph">' + layer + layer + layer + '</span>';
  };
  if(name === "menu") return '<span class="menuWord glassText" data-text="MENU">MENU</span>';
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
  var m = wheelMedia();
  var d = (m && m.duration) ? m.duration : 0;
  if(d <= 0) return;
  var step = Math.max(2, d / 200);
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
  var step = 0.03;
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
