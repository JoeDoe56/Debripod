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
  function menuButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && !playbackPillsPinned) hidePlaybackPillsImmediate("menu button");
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive() && lastfmIsEnabled()){
      lastfmToggleLoved(lastfmState.meta);
      resetSeekIdle();
      return;
    }
    if(nowPlaying.style.display !== "block" && state.current && (state.current.kind === "history" || state.current.kind === "playback_queue")){
      showNowPlaying(true);
      return;
    }
    goBack();
  }

  function playButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive()){
      toggleShuffle();
      resetSeekIdle();
    }else{
      const p = togglePlay();
      if(p && typeof p.catch === "function") p.catch(()=>{});
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

  function performWheelButtonTap(zone, pressFn, options){
    triggerWheelClickTilt(zone);
    if(options && options.pulse) pulseWheelCenter();
    vibeTick();
    if(nowPlaying.style.display === "block" && !(options && options.skipPlaybackPill)) playbackPillActivity(false, "wheel button");
    pressFn();
  }

  function bindWheelButton(el, zone, pressFn, longFn, options){
    if(!el) return;
    let active = null;
    const clear = ()=>{
      if(active && active.timer) clearTimeout(active.timer);
      active = null;
    };
    el.addEventListener("pointerdown", (ev)=>{
      try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
      if(active) clear();
      const startX = ev.clientX;
      const startY = ev.clientY;
      active = {id:ev.pointerId, long:false, moved:false, timer:0, x:startX, y:startY};
      try{ el.setPointerCapture(ev.pointerId); }catch(e){}
      triggerWheelClickTilt(zone);
      if(options && options.pulse) pulseWheelCenter();
      startWheelRotationPointer(ev, true);
      active.timer = setTimeout(()=>{
        if(!active || active.moved) return;
        active.long = true;
        suppressWheelClicks(700);
        vibeTick();
        try{
          const result = longFn && longFn();
          if(result && typeof result.catch === "function") result.catch(()=>{});
        }catch(e){}
      }, 320);
    }, {passive:false});
    el.addEventListener("pointermove", (ev)=>{
      if(!active || active.id !== ev.pointerId) return;
      const dist = Math.hypot((ev.clientX || 0) - active.x, (ev.clientY || 0) - active.y);
      if(dist > 10){
        active.moved = true;
        if(active.timer){
          clearTimeout(active.timer);
          active.timer = 0;
        }
        moveWheelRotationPointer(ev);
      }
      try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
    }, {passive:false});
    const finish = (ev)=>{
      if(active && active.id === ev.pointerId){
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        const shouldTap = !active.long && !active.moved;
        const wasDrag = active.moved;
        clear();
        suppressWheelClicks(500);
        if(wasDrag) wheelPointerEnd();
        if(shouldTap) performWheelButtonTap(zone, pressFn, options);
      }
    };
    el.addEventListener("pointerup", finish, {passive:false});
    el.addEventListener("pointercancel", (ev)=>{ try{ ev.stopPropagation(); }catch(e){} clear(); wheelPointerEnd(); }, {passive:false});
    el.addEventListener("click", (ev)=>{
      if(isWheelClickSuppressed()){
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        return;
      }
      performWheelButtonTap(zone, pressFn, options);
    });
  }

  bindWheelButton(btnMenu, "top", menuButtonPress, ()=>{ if(typeof openNowFolder === "function") return openNowFolder(); }, {skipPlaybackPill:true});
  bindWheelButton(btnRev, "left", revButtonPress, ()=>{ if(typeof viewHistory === "function") return viewHistory(true); });
  bindWheelButton(btnFwd, "right", fwdButtonPress, ()=>{ if(typeof viewPlaybackQueue === "function") return viewPlaybackQueue(true); });
  bindWheelButton(btnPlay, "bottom", playButtonPress, null);
  bindWheelButton(btnCenter, "center", centerPress, null, {pulse:true});

  updateWheelLabels();

  function keyboardInputTarget(tgt){
    return !!(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable));
  }

  function rowFromEventTarget(tgt){
    try{
      return tgt && tgt.closest ? tgt.closest(".ipodItem[data-index]") : null;
    }catch(e){
      return null;
    }
  }

  if(libList && !libList._dpContextMenuBound){
    libList._dpContextMenuBound = true;
    libList.addEventListener("contextmenu", (ev)=>{
      try{
        if(keyboardInputTarget(ev.target)) return;
        ev.preventDefault();
        ev.stopPropagation();
        const row = rowFromEventTarget(ev.target);
        if(row && row.dataset && row.dataset.index != null){
          const idx = Number(row.dataset.index);
          if(Number.isFinite(idx) && idx >= 0 && idx < (state.items || []).length){
            setSelectionFast(idx);
          }
        }
        menuButtonPress();
      }catch(e){}
    });
  }

  if(libList && !libList._dpDirectTapBound){
    libList._dpDirectTapBound = true;
    let listPointer = null;
    const activateListRow = async (target)=>{
      if(keyboardInputTarget(target)) return;
      const row = rowFromEventTarget(target);
      if(!row || !row.dataset || row.dataset.index == null) return;
      const index = Number(row.dataset.index);
      if(!Number.isFinite(index) || index < 0 || index >= (state.items || []).length) return;
      const item = state.items[index];
      if(!item || item.disabled) return;
      setSelectionFast(index);
      try{ if(typeof selectItem === "function") await selectItem(item); }catch(e){}
    };
    libList.addEventListener("pointerdown", (ev)=>{
      if(ev.pointerType !== "touch" && ev.pointerType !== "pen") return;
      if(keyboardInputTarget(ev.target)) return;
      listPointer = {id:ev.pointerId, x:ev.clientX, y:ev.clientY, moved:false, target:ev.target};
    }, {passive:true});
    libList.addEventListener("pointermove", (ev)=>{
      if(!listPointer || ev.pointerId !== listPointer.id) return;
      if(Math.abs(ev.clientX - listPointer.x) > 9 || Math.abs(ev.clientY - listPointer.y) > 9) listPointer.moved = true;
    }, {passive:true});
    libList.addEventListener("pointerup", (ev)=>{
      if(!listPointer || ev.pointerId !== listPointer.id) return;
      const gesture = listPointer;
      listPointer = null;
      if(gesture.moved) return;
      libList._dpIgnoreDirectClickUntil = Date.now() + 450;
      activateListRow(ev.target || gesture.target);
    }, {passive:true});
    libList.addEventListener("pointercancel", ()=>{ listPointer = null; }, {passive:true});
    libList.addEventListener("click", (ev)=>{
      if(Date.now() < Number(libList._dpIgnoreDirectClickUntil || 0)) return;
      activateListRow(ev.target);
    });
  }
  if(document && !document._dpStageContextMenuBound){
    document._dpStageContextMenuBound = true;
    document.addEventListener("contextmenu", (ev)=>{
      try{
        if(keyboardInputTarget(ev.target)) return;
        const inStage = ev.target && ev.target.closest && ev.target.closest(".ipodStage");
        if(!inStage) return;
        ev.preventDefault();
        ev.stopPropagation();
        menuButtonPress();
      }catch(e){}
    });
  }

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

  function startWheelRotationPointer(ev, downOnButton){
    wheelPointerDown = true;
    dragging = false;
    wheelDownOnButton = !!downOnButton;
    wheelStartX = ev.clientX;
    wheelStartY = ev.clientY;
    wheelPointerRect = wheel.getBoundingClientRect();
    lastAngle = angleFromEvent(ev);
    accum = 0;
    cacheWheelGlassTiltRect();
  }

  function moveWheelRotationPointer(ev){
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
      if(Math.abs(accum) >= step){
        if(seekMode){
          showPlaybackPills(true, "seek wheel step");
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
  }

  wheel.addEventListener("pointerdown", (ev)=>{
    let downOnButton = false;
    try{
      if(ev.target === btnCenter) downOnButton = true;
      else if(ev.target && ev.target.closest && ev.target.closest(".wheelBtn")) downOnButton = true;
    }catch(e){
      downOnButton = false;
    }
    startWheelRotationPointer(ev, downOnButton);

    // Avoid capturing immediately so taps on buttons stay reliable.
    // If the user drags, we will capture on move after a small threshold.
  }, {passive:false});

  wheel.addEventListener("pointermove", (ev)=>{
    moveWheelRotationPointer(ev);
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
    if(keyboardInputTarget(tgt)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    try{
      const overList = !!(libList && tgt && tgt.closest && tgt.closest("#libList"));
      if(overList && nowPlaying.style.display !== "block") return;
    }catch(e){}

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
    if(keyboardInputTarget(tgt)){
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
      menuButtonPress();
    }else if(k === "Escape" || k === "Backspace"){
      ev.preventDefault();
      menuButtonPress();
    }else if(k === "a" || k === "A"){
      ev.preventDefault();
      revButtonPress();
    }else if(k === "ArrowLeft"){
      ev.preventDefault();
      revButtonPress();
    }else if(k === "s" || k === "S"){
      ev.preventDefault();
      pulseWheelCenter();
      centerPress();
    }else if(k === "Enter"){
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
    }else if(k === "ArrowRight"){
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
    }else if(k === "Home"){
      ev.preventDefault();
      if(nowPlaying.style.display !== "block") setSelectionFast(0);
    }else if(k === "End"){
      ev.preventDefault();
      if(nowPlaying.style.display !== "block") setSelectionFast(Math.max(0, (state.items || []).length - 1));
    }else if(k === "PageUp"){
      ev.preventDefault();
      if(nowPlaying.style.display !== "block") scrollSel(-Math.max(1, Math.floor(((libList && libList.clientHeight) || 320) / 56)));
    }else if(k === "PageDown"){
      ev.preventDefault();
      if(nowPlaying.style.display !== "block") scrollSel(Math.max(1, Math.floor(((libList && libList.clientHeight) || 320) / 56)));
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
