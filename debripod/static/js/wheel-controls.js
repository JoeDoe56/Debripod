  var btnFwd = document.getElementById("btnFwd");
  var btnPlay = document.getElementById("btnPlay");
  var btnCenter = document.getElementById("btnCenter");

  
  var copyStreamBtn = document.getElementById("copyStreamBtn");
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
    triggerWheelClickTilt("top");
    vibeTick();
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block") hideNpPillImmediate("menu button");
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

  function pulseWheelCenter(){
    try{
      if(!btnCenter) return;
      btnCenter.classList.remove("centerPulse");
      void btnCenter.offsetWidth;
      btnCenter.classList.add("centerPulse");
    }catch(e){}
  }

  function triggerWheelClickTilt(zone){
    try{
      cacheWheelGlassTiltRect();
      const maxTilt = normalizeWheelRotationMaxDegrees(wheelRotationMaxDegrees) * clampNumber(uiSettings.wheelClickTiltAmount, DEFAULT_UI_SETTINGS.wheelClickTiltAmount, 0, 1);
      let rotX = 0;
      let rotY = 0;
      const z = String(zone || "");
      if(z === "top") rotX = maxTilt;
      else if(z === "bottom") rotX = -maxTilt;
      else if(z === "left") rotY = -maxTilt;
      else if(z === "right") rotY = maxTilt;
      else rotX = -maxTilt * 0.35;
      setWheelTiltTarget(rotX, rotY, Math.max(20, clampNumber(uiSettings.wheelTiltRampDuration, DEFAULT_UI_SETTINGS.wheelTiltRampDuration, 0, 1000) * 0.65));
      setTimeout(()=>{
        try{ setWheelTiltTarget(0, 0, clampNumber(uiSettings.wheelTiltReleaseDuration, DEFAULT_UI_SETTINGS.wheelTiltReleaseDuration, 0, 1200)); }catch(e){}
      }, Math.max(45, clampNumber(uiSettings.wheelTiltRampDuration, DEFAULT_UI_SETTINGS.wheelTiltRampDuration, 0, 1000)));
    }catch(e){}
  }

  btnPlay.addEventListener("pointerdown", ()=> triggerWheelClickTilt("bottom"), {passive:true});
  btnRev.addEventListener("pointerdown", ()=> triggerWheelClickTilt("left"), {passive:true});
  btnFwd.addEventListener("pointerdown", ()=> triggerWheelClickTilt("right"), {passive:true});
  btnMenu.addEventListener("pointerdown", ()=> triggerWheelClickTilt("top"), {passive:true});
  btnPlay.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; triggerWheelClickTilt("bottom"); vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); playButtonPress(); });
  btnRev.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; triggerWheelClickTilt("left"); vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); revButtonPress(); });
  btnFwd.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; triggerWheelClickTilt("right"); vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); fwdButtonPress(); });

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
    if(typeof rangeEditorCenterPress === "function" && rangeEditorCenterPress()){
      return;
    }
    selectItem();
  }

  btnCenter.addEventListener("animationend", (ev)=>{
    try{ if(ev.animationName === "wheelCenterPulse") btnCenter.classList.remove("centerPulse"); }catch(e){}
  });
  btnCenter.addEventListener("pointerdown", ()=>{ pulseWheelCenter(); triggerWheelClickTilt("center"); }, {passive:true});
  btnCenter.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; pulseWheelCenter(); triggerWheelClickTilt("center"); vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); centerPress(); });

  updateWheelLabels();

  // rotation scroll on wheel ring
  var wheelPointerDown = false;
  var dragging = false;
  var lastAngle = 0;
  var accum = 0;
  var wheelStartX = 0;
  var wheelStartY = 0;
  var wheelDownOnButton = false;
  var wheelClickSuppressUntil = 0;
  var wheelPointerRect = null;
  var step = 18;
  var dragPx = 8;

  function isWheelClickSuppressed(){
    return Date.now() < wheelClickSuppressUntil;
  }
  function suppressWheelClicks(ms){
    const dur = Number(ms || 0);
    const until = Date.now() + (dur > 0 ? dur : 0);
    if(until > wheelClickSuppressUntil) wheelClickSuppressUntil = until;
  }

  function angleFromEvent(ev){
    const rect = wheelPointerRect || wheel.getBoundingClientRect();
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
    wheelPointerRect = wheel.getBoundingClientRect();
    lastAngle = angleFromEvent(ev);
    accum = 0;
    cacheWheelGlassTiltRect();

    // Avoid capturing immediately so taps on buttons stay reliable.
    // If the user drags, we will capture on move after a small threshold.
  }, {passive:false});

  wheel.addEventListener("pointermove", (ev)=>{
    if(!wheelPointerDown) return;
    const events = (typeof ev.getCoalescedEvents === "function") ? ev.getCoalescedEvents() : null;
    const moveEvents = (events && events.length) ? events : [ev];
    const latestEv = moveEvents[moveEvents.length - 1] || ev;

    if(!dragging){
      const dx = (latestEv.clientX - wheelStartX);
      const dy = (latestEv.clientY - wheelStartY);
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
    applyWheelGlassTilt(latestEv);

    for(const mev of moveEvents){
      const ang = angleFromEvent(mev);
      const d = normDelta(ang, lastAngle);
      lastAngle = ang;
      accum += d;
    }

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

    if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive()){
      if(Math.abs(accum) >= step){
        const steps = Math.trunc(accum / step);
        try{ adjustRangeEditor(steps); }catch(e){}
        accum -= steps * step;
      }
      return;
    }

    if(Math.abs(accum) >= step){
      const steps = Math.trunc(accum / step);
      scrollSel(steps);
      accum -= steps * step;
      try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(accum / step); }catch(e){}
    }else{
      try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(accum / step); }catch(e){}
    }
  }, {passive:false});

  function wheelPointerEnd(){
    wheelPointerDown = false;
    dragging = false;
    wheelDownOnButton = false;
    wheelPointerRect = null;
    try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(0); }catch(e){}
    resetWheelGlassTilt();
  }

  wheel.addEventListener("pointerup", wheelPointerEnd, {passive:false});
  wheel.addEventListener("pointercancel", wheelPointerEnd, {passive:false});

  // keyboard and mouse wheel bindings
  window.addEventListener("wheel", (ev)=>{
    // Let normal browser zoom and text input scrolling work.
    if(ev.ctrlKey) return;
    if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive()){
      ev.preventDefault();
      const dir = ev.deltaY > 0 ? 1 : -1;
      try{ adjustRangeEditor(dir); }catch(e){}
      return;
    }
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
      if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive()){
        try{ adjustRangeEditor(dir); }catch(e){}
        return;
      }
      try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(dir * 0.35); }catch(e){}
      scrollSel(dir);
      setTimeout(()=>{ try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(0); }catch(e){} }, 90);
    }
  }, {passive:false});

  window.addEventListener("keydown", (ev)=>{

    // Don't hijack typing inside inputs/textareas/selects/contenteditable elements
    const tgt = ev.target;
    if(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable)){
      if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive() && (ev.key === "ArrowUp" || ev.key === "ArrowDown")){
        ev.preventDefault();
        adjustRangeEditor(ev.key === "ArrowUp" ? -1 : 1);
      }
      return;
    }

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
      pulseWheelCenter();
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
      }else if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive()){
        adjustRangeEditor(-1);
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
      }else if(typeof rangeEditorWheelActive === "function" && rangeEditorWheelActive()){
        adjustRangeEditor(1);
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
