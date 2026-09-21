function nowPlayingArtSrcValue(value){
  if(value && typeof value === "object"){
    value = value.url || value.src || value.href || "";
  }
  return String(value == null ? "" : value).trim();
}

function nowPlayingArtCompareKey(value){
  return nowPlayingArtSrcValue(value);
}

function currentNowPlayingArtSrc(){
  try{
    if(typeof currentNowPlayingArtTextureSrc === "function") return currentNowPlayingArtTextureSrc();
    if(npArt && npArt.dataset) return nowPlayingArtSrcValue(npArt.dataset.artSrc || "");
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
    if(typeof setNowPlayingArtTexture === "function") setNowPlayingArtTexture(v, opts || {});
    else if(npArt && npArt.dataset) npArt.dataset.artSrc = v;
    if(artChanged) sampleThemeFromArt(v);
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

function playbackTitleHtml(meta, fallbackLabel){
  var m = meta || {};
  const title = String((m && m.title) || fallbackLabel || "Track").trim();
  const artist = String((m && m.artist) || "").trim();
  const album = String((m && m.album) || "").trim();
  const main = artist ? (escapeHtml(title) + " - " + escapeHtml(artist)) : escapeHtml(title);
  return "<strong>" + main + "</strong>" + (album ? " <em>" + escapeHtml(album) + "</em>" : "");
}

function playbackTitlePlain(meta, fallbackLabel){
  var m = meta || {};
  const title = String((m && m.title) || fallbackLabel || "Track").trim();
  const artist = String((m && m.artist) || "").trim();
  const album = String((m && m.album) || "").trim();
  return (artist ? (title + " - " + artist) : title) + (album ? (" " + album) : "");
}

function setPlaybackPillMetadata(meta, fallbackLabel){
  var m = meta || {};
  try{
    const plain = playbackTitlePlain(m, fallbackLabel);
    if(pathPillNowText){
      pathPillNowText.innerHTML = playbackTitleHtml(m, fallbackLabel);
      pathPillNowText.dataset.text = plain;
      pathPillNowText.classList.remove("pathPillNowTextSmall");
      requestAnimationFrame(()=>{
        try{
          pathPillNowText.classList.toggle("pathPillNowTextSmall", pathPillNowText.scrollWidth > pathPillNowText.clientWidth + 1);
          if(typeof updatePathPillMaxWidth === "function") updatePathPillMaxWidth();
          if(typeof updatePathPillScrollingMasks === "function") updatePathPillScrollingMasks();
        }catch(e){}
      });
    }
    playbackPillMetadataVisible = !!plain.trim();
    if(libHeader) libHeader.classList.toggle("pathPillExpanded", hasNowPlayingMetadata());
    try{ if(typeof updatePathPillMaxWidth === "function") updatePathPillMaxWidth(); }catch(e){}
    if(!hasNowPlayingMetadata() && infoPill) infoPill.classList.add("infoPillHidden");
  }catch(e){}
  try{
    if(npTech) npTech.dataset.progressText = String(m.quality || m.tech || m.ext || "").trim();
    renderInfoPillLabels();
  }catch(e){}
  try{ if(nowPlaying && nowPlaying.style.display === "block") setHeader(); }catch(e){}
}

var nowPlayingDisplayedArtIdentity = "";

async function updateNowPlayingDisplay(meta, fallbackLabel, opts){
  var m = meta || {};
  var options = opts || {};
  var nextArt = nowPlayingArtSrcValue(m.art);
  var nextIdentity = String(m.artIdentity || "").trim();
  var currentArt = currentNowPlayingArtSrc();
  // Track-specific /art URLs may return the exact same image. Keep the
  // displayed image (and renderer) untouched when its content is unchanged.
  if(nextArt && currentArt && nextIdentity && nextIdentity === nowPlayingDisplayedArtIdentity){
    setPlaybackPillMetadata(m, fallbackLabel);
    return;
  }
  var currentArtKey = nowPlayingArtCompareKey(currentArt);
  var nextArtKey = nowPlayingArtCompareKey(nextArt);
  var animateArt = !!(options.animateArt && npArt && currentArtKey && nextArtKey && currentArtKey !== nextArtKey);
  setNowPlayingArtSrc(nextArt, {animate: animateArt, duration: 220});
  nowPlayingDisplayedArtIdentity = nextIdentity;
  setPlaybackPillMetadata(m, fallbackLabel);
}


var npControlMode = "progress";

function infoPillLabelValues(mode, volume, progress){
  if(mode === "volume"){
    return {left: "min", center: Math.round(Math.max(0, Math.min(1, Number(volume) || 0)) * 100) + "%", right: "max"};
  }
  var values = progress || {};
  return {left: values.left || "0:00", center: values.center || "", right: values.right || "0:00"};
}

function renderInfoPillLabels(){
  try{
    var media = (typeof wheelMedia === "function") ? wheelMedia() : null;
    var gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
    var progress = {
      left: fmtTime(gapless ? Number(gapless.position || 0) : (media && isFinite(media.currentTime) ? Number(media.currentTime) : 0)),
      center: (npTech && npTech.dataset && npTech.dataset.progressText) || "",
      right: fmtTime(gapless ? Number(gapless.duration || 0) : (media && isFinite(media.duration) ? Number(media.duration) : 0))
    };
    var labels = infoPillLabelValues(npControlMode, userVol, progress);
    if(npCur) npCur.textContent = labels.left;
    if(npTech) npTech.textContent = labels.center;
    if(npDur) npDur.textContent = labels.right;
  }catch(e){}
}

function setInfoPillControlMode(mode, reason){
  const next = mode === "volume" ? "volume" : "progress";
  if(npControlMode === next) return false;
  npControlMode = next;
  if(npProgressWrap) npProgressWrap.style.display = next === "progress" ? "block" : "none";
  if(npVolumeWrap) npVolumeWrap.style.display = next === "volume" ? "block" : "none";
  renderInfoPillLabels();
  return true;
}

function updateVolumeFillOnly(){
  try{
    const percent = Math.round(userVol * 100);
    if(npVolumeFill) npVolumeFill.style.width = percent + "%";
    const meter = npVolumeWrap && npVolumeWrap.querySelector ? npVolumeWrap.querySelector(".npVolumeMeter") : null;
    if(meter) meter.setAttribute("aria-valuenow", String(percent));
    renderInfoPillLabels();
  }catch(e){}
}

function updateProgressMeterFill(percent){
  try{
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    if(npProgressFill) npProgressFill.style.width = value.toFixed(2) + "%";
  }catch(e){}
}

function updateSeekPreviewOnly(){
  updateSeekIndicator();
}

function showProgressBar(reason){
  try{
    const changed = setInfoPillControlMode("progress", reason || "progress");
    if(changed && !isPlaybackPillsShown()) showPlaybackPills(false, reason || "progress mode show");
  }catch(e){}
}

function showVolumeBar(reason){
  try{
    const changed = setInfoPillControlMode("volume", reason || "volume");
    updateVolumeFillOnly();
    if(changed && !isPlaybackPillsShown()) showPlaybackPills(false, reason || "volume mode show");
  }catch(e){}
}

function scheduleHideVolumeBar(){
  try{
    if(volBarTimer) clearTimeout(volBarTimer);
    volBarTimer = setTimeout(()=>{
      if(!seekMode && nowPlaying.style.display === "block"){
        showProgressBar("volume timeout");
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
    const gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
    const d = gapless ? Number(gapless.duration || 0) : ((m && m.duration) ? m.duration : 0);
    const actualT = gapless ? Number(gapless.position || 0) : Number(m && m.currentTime || 0);
    if(d <= 0){
      npSeekIndicator.style.left = "0%";
      updateProgressMeterFill(0);
      return;
    }
    const pct = Math.max(0, Math.min(1, (seekPreview || 0) / d)) * 100;
    // The marker previews the wheel target; the white fill always reports
    // the decoder current position until the seek is committed.
    updateProgressMeterFill(Math.max(0, Math.min(1, actualT / d)) * 100);
    const wrapWidth = npProgressWrap ? Number(npProgressWrap.clientWidth || 0) : 0;
    const inset = Math.max(0, parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--infoBarInsetX")) || 0);
    npSeekIndicator.style.left = Math.round(inset + Math.max(0, wrapWidth - (inset * 2)) * (pct / 100) - 1) + "px";
  }catch(e){}
}

function enterSeekMode(){
  if(nowPlaying.style.display !== "block") return;
  seekMode = true;
  seekChanged = false;
  showPlaybackPills(true, "seek mode");
  var m = wheelMedia();
  var gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
  seekPreview = gapless ? Number(gapless.position || 0) : ((m && m.currentTime) ? m.currentTime : 0);
  showProgressBar("seek mode");
  try{ npSeekIndicator.style.display = "block"; }catch(e){}
  updateSeekIndicator();
  resetSeekIdle();
  updateWheelLabels();
  scheduleHidePlaybackPills(2000);
}

function cancelSeekMode(){
  if(!seekMode) return;
  seekMode = false;
  seekChanged = false;
  try{ if(seekIdleTimer) clearTimeout(seekIdleTimer); }catch(e){}
  seekIdleTimer = null;
  try{ npSeekIndicator.style.display = "none"; }catch(e){}
  try{
    const m = wheelMedia();
    const gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
    const d = gapless ? Number(gapless.duration || 0) : ((m && m.duration) ? m.duration : 0);
    const t = gapless ? Number(gapless.position || 0) : Number(m && m.currentTime || 0);
    updateProgressMeterFill(d > 0 ? ((t / d) * 100) : 0);
  }catch(e){}
  showProgressBar("seek cancel");
  updateWheelLabels();
}

function commitSeekMode(){
  if(!seekMode) return;
  var m = wheelMedia();
  var gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
  var d = gapless ? Number(gapless.duration || 0) : ((m && m.duration) ? m.duration : 0);
  if(d > 0){
    try{
      if(gapless && window.DebriPod && DebriPod.gaplessAudio && DebriPod.gaplessAudio.seek) DebriPod.gaplessAudio.seek(Math.max(0, Math.min(d, seekPreview)));
      else if(m) m.currentTime = Math.max(0, Math.min(d, seekPreview));
    }catch(e){}
  }
  cancelSeekMode();
}

function setWheelLabel(el, name, active, options){
  try{
    if(window.DebriPod && window.DebriPod.wheelIcons){
      window.DebriPod.wheelIcons.update(el, name, active, options);
    }
  }catch(e){}
}

function updateWheelLabels(){
  try{
    const lMenu = document.querySelector(".wheelLabel.wlTop, .wheelLabel.top");
    const lRev = document.querySelector(".wheelLabel.wlLeft, .wheelLabel.wlRev");
    const lFwd = document.querySelector(".wheelLabel.wlRight, .wheelLabel.wlFwd");
    const lPlay = document.querySelector(".wheelLabel.wlBottom, .wheelLabel.wlPlay");
    if(!lMenu || !lRev || !lFwd || !lPlay) return;

    if(state.current && state.current.kind === "np_playlist_add"){
      setWheelLabel(lMenu, "");
      setWheelLabel(lRev, "");
      setWheelLabel(lFwd, "");
      setWheelLabel(lPlay, "");
      return;
    }

    if(nowPlaying.style.display === "block" && seekMode){
      if(!isVideoActive()){
        setWheelLabel(lMenu, "heart", !!(lastfmState.lovedKnown && lastfmState.loved), {seekMode:true});
      }else{
        setWheelLabel(lMenu, "menu");
      }
      setWheelLabel(lRev, "back15", false, {seekMode:true});
      setWheelLabel(lFwd, "forward15", false, {seekMode:true});
      if(isVideoActive()){
        const m = wheelMedia();
        setWheelLabel(lPlay, (m && m.paused) ? "play" : "pause", !(m && m.paused), {seekMode:true});
      }else{
        setWheelLabel(lPlay, "shuffle", !!state.shuffleEnabled, {seekMode:true});
      }
    }else{
      setWheelLabel(lMenu, "menu");
      setWheelLabel(lRev, "prev");
      setWheelLabel(lFwd, "next");
      if(nowPlaying.style.display === "block"){
        const m = wheelMedia();
        const gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
        const paused = gapless ? !gapless.playing : !!(m && m.paused);
        setWheelLabel(lPlay, paused ? "play" : "pause", !paused);
      }else if(state.now){
        const m = wheelMedia();
        const isPaused = m ? !!m.paused : !(state.serverNow && state.serverNow.playing);
        setWheelLabel(lPlay, isPaused ? "play" : "pause", !isPaused);
      }else{
        setWheelLabel(lPlay, "play", false);
      }
    }
  }catch(e){}
}



function adjustSeekPreview(dir){  var m = wheelMedia();
  var gapless = (typeof gaplessPlaybackSnapshot === "function") ? gaplessPlaybackSnapshot() : null;
  var d = gapless ? Number(gapless.duration || 0) : ((m && m.duration) ? m.duration : 0);
  if(d <= 0) return;
  const pillsWereShown = (typeof isPlaybackPillsShown === "function") ? isPlaybackPillsShown() : false;
  var step = Math.max(2.5, d / 160);
  seekPreview = Math.max(0, Math.min(d, (seekPreview || 0) + (dir * step)));
  seekChanged = true;
  updateSeekPreviewOnly();
  resetSeekIdle();
  if(!pillsWereShown) playbackPillActivity(true, "seek preview");
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
      try{
        const nav = window.DebriPod && DebriPod.navigationController;
        if(nav && nav.openNowPlaying) nav.openNowPlaying();
        else showNowPlaying(true, {navigationControlled:true});
      }catch(e){}
    }

    // Ensure a clean seek mode state
    try{ if(seekMode) cancelSeekMode(); }catch(e){}

    // Enter seek mode using the same path as a center press
    try{ enterSeekMode(); }catch(e){}
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
          try{ commitSeekMode(); }catch(e){}
          try{ preparePlaybackMediaAudio(npVideo); }catch(e){}
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
  try{ localStorage.setItem(volumePreferenceStorageKey(), String(userVol)); }catch(e){}
  unlockPlaybackMediaAudio();
  applyVolume();
}

function adjustVolumeStep(dir){
  var step = 0.03;
  const pillsWereShown = (typeof isPlaybackPillsShown === "function") ? isPlaybackPillsShown() : false;
  const wasVolumeMode = npControlMode === "volume";
  setVolume(userVol + (dir * step));
  if(nowPlaying.style.display === "block" && !seekMode){
    showVolumeBar("volume step");
    scheduleHideVolumeBar();
    if(!pillsWereShown){
      playbackPillActivity(false, "volume step");
    }else if(!wasVolumeMode && typeof scheduleHidePlaybackPills === "function"){
      scheduleHidePlaybackPills(2500);
    }
  }
}

applyVolume();

function fmtTime(sec){
    sec = Math.max(0, sec || 0);
    const m = Math.floor(sec/60);
    const s = Math.floor(sec%60);
    return m + ":" + (s<10 ? "0"+s : s);
  }
