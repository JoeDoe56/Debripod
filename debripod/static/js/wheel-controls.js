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
  function dispatchControl(gesture, control, details){
    try{
      const dispatcher = window.DebriPod && DebriPod.controlDispatcher;
      if(!dispatcher || typeof dispatcher.dispatch !== "function") return Promise.resolve();
      return dispatcher.dispatch(gesture, control, details || {});
    }catch(error){
      return Promise.reject(error);
    }
  }

  // Pointer, wheel, and keyboard repeat can all arrive faster than a row can
  // settle. Keep one pending direction and release at most 24 row steps per
  // second. Coalescing the direction prevents a stale backlog after a fast
  // gesture or a page transition.
  const SELECTION_STEP_INTERVAL_MS = 1000 / 24;
  let selectionStepTimer = 0;
  let selectionStepPending = "";
  let selectionStepLastTs = 0;
  let selectionStepGeneration = 0;
  function cancelSelectionStepQueue(){
    selectionStepGeneration += 1;
    if(selectionStepTimer) clearTimeout(selectionStepTimer);
    selectionStepTimer = 0;
    selectionStepPending = "";
  }
  function queueSelectionStep(control){
    const value = String(control || "");
    if(value !== "scroll_forward" && value !== "scroll_back") return dispatchControl("wheel_step", value);
    if(nowPlaying && nowPlaying.style.display === "block" && seekMode) return dispatchControl("wheel_step", value);
    const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    const elapsed = now - selectionStepLastTs;
    if(!selectionStepPending && (selectionStepLastTs <= 0 || elapsed >= SELECTION_STEP_INTERVAL_MS)){
      selectionStepLastTs = now;
      return dispatchControl("wheel_step", value);
    }
    selectionStepPending = value;
    if(!selectionStepTimer){
      const generation = selectionStepGeneration;
      const wait = Math.max(1, SELECTION_STEP_INTERVAL_MS - Math.max(0, elapsed));
      selectionStepTimer = setTimeout(()=>{
        selectionStepTimer = 0;
        if(generation !== selectionStepGeneration) return;
        const pending = selectionStepPending;
        selectionStepPending = "";
        if(!pending) return;
        selectionStepLastTs = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        dispatchControl("wheel_step", pending).catch(()=>{});
      }, wait);
    }
    return Promise.resolve();
  }
  try{ window.cancelSelectionStepQueue = cancelSelectionStepQueue; }catch(e){}

  var wheelCenterAnimation = null;
  function pulseWheelCenter(){
    try{
      if(!btnCenter) return;
      if(wheelCenterAnimation) wheelCenterAnimation.cancel();
      const amount = clampNumber(uiSettings.centerBounceAmount, DEFAULT_UI_SETTINGS.centerBounceAmount, 0, .3);
      const duration = clampNumber(uiSettings.centerBounceDuration, DEFAULT_UI_SETTINGS.centerBounceDuration, 0, 1000);
      const overshoot = clampNumber(uiSettings.centerBounceOvershoot, DEFAULT_UI_SETTINGS.centerBounceOvershoot, 0, 1.4);
      const pose = scale => "translate(-50%,-50%) scale(" + scale + ")";
      wheelCenterAnimation = btnCenter.animate([
        {transform:pose(1), offset:0},
        {transform:pose(1 + amount), offset:.32},
        {transform:pose(1 - amount * .28 * overshoot), offset:.66},
        {transform:pose(1 + amount * .08 * overshoot), offset:.86},
        {transform:pose(1), offset:1}
      ], {duration, easing:"cubic-bezier(.35,0,.25,1)"});
      const animation = wheelCenterAnimation;
      const sync = ()=>{
        if(wheelCenterAnimation !== animation) return;
        markFrameWork({metrics:true, render:true, keepAlive:animation.playState === "running"});
        if(animation.playState === "running") requestAnimationFrame(sync);
      };
      sync();
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

  btnCenter.addEventListener("animationend", (ev)=>{
    try{ if(ev.animationName === "wheelCenterPulse") btnCenter.classList.remove("centerPulse"); }catch(e){}
  });

  function performWheelButtonTap(zone, control, options){
    cancelSelectionStepQueue();
    triggerWheelClickTilt(zone);
    if(options && options.pulse) pulseWheelCenter();
    vibeTick();
    if(nowPlaying.style.display === "block" && !(options && options.skipPlaybackPill)) playbackPillActivity(false, "wheel button");
    dispatchControl("tap", control).catch(()=>{});
  }

  function bindWheelButton(el, zone, control, options){
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
        dispatchControl("hold", control).catch(()=>{});
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
        if(shouldTap) performWheelButtonTap(zone, control, options);
      }
    };
    el.addEventListener("pointerup", finish, {passive:false});
    el.addEventListener("pointercancel", (ev)=>{ try{ ev.stopPropagation(); }catch(e){} clear(); wheelPointerEnd(); }, {passive:false});
    el.addEventListener("click", (ev)=>{
      if(isWheelClickSuppressed()){
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        return;
      }
      performWheelButtonTap(zone, control, options);
    });
  }

  bindWheelButton(btnMenu, "top", "top", {skipPlaybackPill:true});
  bindWheelButton(btnRev, "left", "left");
  bindWheelButton(btnFwd, "right", "right");
  bindWheelButton(btnPlay, "bottom", "bottom");
  bindWheelButton(btnCenter, "center", "center", {pulse:true});

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
        const item = (state.items || [])[state.sel] || null;
        dispatchControl("hold", "center", {item:item}).catch(()=>{});
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

  // A long press on a wheel label must remain a wheel gesture rather than
  // starting native text selection or drag handling.
  ["selectstart", "dragstart", "contextmenu"].forEach((eventName)=>{
    wheel.addEventListener(eventName, (ev)=>{
      ev.preventDefault();
    });
  });

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

    if(Math.abs(accum) >= step){
      const steps = Math.trunc(accum / step);
      const count = Math.abs(steps);
      const control = steps > 0 ? "scroll_forward" : "scroll_back";
      for(let i = 0; i < count; i++) queueSelectionStep(control).catch(()=>{});
      accum -= steps * step;
      if(nowPlaying.style.display === "block" && seekMode) showPlaybackPills(true, "seek wheel step");
      if(nowPlaying.style.display !== "block"){
        try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(accum / step); }catch(e){}
      }
    }else if(nowPlaying.style.display !== "block"){
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
    cancelSelectionStepQueue();
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
    const tgt = ev.target;
    if(keyboardInputTarget(tgt)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    try{
      const overList = !!(libList && tgt && tgt.closest && tgt.closest("#libList"));
      if(overList && nowPlaying.style.display !== "block") return;
    }catch(e){}

    ev.preventDefault();
    const dir = ev.deltaY > 0 ? 1 : -1;
    queueSelectionStep(dir > 0 ? "scroll_forward" : "scroll_back").catch(()=>{});
    if(nowPlaying.style.display !== "block"){
      try{ if(typeof setLibSelectionStretch === "function") setLibSelectionStretch(dir * 0.35); }catch(e){}
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

    let control = "";
    if(k === "w" || k === "W" || k === "Backspace") control = "top";
    else if(k === "a" || k === "A") control = "left";
    else if(k === "s" || k === "S" || k === "Enter") control = "center";
    else if(k === " ") control = "bottom";
    else if(k === "d" || k === "D") control = "right";
    else if(k === "q" || k === "Q") control = "scroll_back";
    else if(k === "e" || k === "E") control = "scroll_forward";
    if(!control) return;
    ev.preventDefault();
    if(control === "center") pulseWheelCenter();
    if(control === "scroll_forward" || control === "scroll_back") queueSelectionStep(control).catch(()=>{});
    else dispatchControl("keyboard", control).catch(()=>{});
  });

  window.addEventListener("keyup", (ev)=>{
    if(ev.key === "q" || ev.key === "Q" || ev.key === "e" || ev.key === "E") cancelSelectionStepQueue();
  }, {passive:true});



async function maybeOpenFromUrl(){
  try{
    if(window.DebriPod && DebriPod.linkIntake && typeof DebriPod.linkIntake.consumeDeepLinks === "function"){
      await DebriPod.linkIntake.consumeDeepLinks();
    }
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
