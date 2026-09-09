  var pathPillPinned = false;
  var pathPillHideTimer = null;
  var playbackPillsPinned = false;
  var playbackPillsVisible = false;
  var playbackPillsHideTimer = null;
  var playbackPillMetadataVisible = false;
  var playbackPillTransitionMs = 220;
  var pathPillHideFinalTimer = null;
  var infoPillHideFinalTimer = null;
  var playbackPillVisibleClassTimer = null;
  try{
    pathPillPinned = (localStorage.getItem("debripod_path_pill_pinned") || "") === "1";
  }catch(e){}
  try{
    const savedPlayback = localStorage.getItem("debripod_playback_pills_pinned");
    if(savedPlayback === null){
      const savedNowPlaying = localStorage.getItem("debripod_np_pill_pinned");
      if(savedNowPlaying !== null) playbackPillsPinned = savedNowPlaying === "1";
      else playbackPillsPinned = (localStorage.getItem("debripod_path_pill_pinned") || "") === "1";
      localStorage.setItem("debripod_playback_pills_pinned", playbackPillsPinned ? "1" : "0");
    }else{
      playbackPillsPinned = savedPlayback === "1";
    }
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
      clearPlaybackPillHideFinalTimers();
      libHeader.classList.remove("pathPillHidden");
      updatePathPillMaxWidth();
      setTimeout(()=> startHScrollTextAuto(document.getElementById("libHeaderText")), playbackPillTransitionMs + 20);
      animatePathPillGlassTransition("path pill shown", playbackPillTransitionMs);
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
          if(playbackPillsVisible && hasNowPlayingMetadata()) return;
          if(playbackPillsPinned && hasNowPlayingMetadata()){
            showPlaybackPills(true, "path hide pinned guard");
            return;
          }
          if(pathPillPinned) return;
          const ae = document.activeElement;
          if(ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT" || ae.isContentEditable)) return;
          libHeader.classList.add("pathPillHidden");
          animatePathPillGlassTransition("path pill hidden", playbackPillTransitionMs);
          schedulePathPillHideFinal("path pill hidden final");
        }catch(e){}
      }, (ms || 2500));
    }catch(e){}
  }

  function pathPillActivity(pinned){
    try{
      if(playbackPillsPinned && hasNowPlayingMetadata()){
        showPlaybackPills(true, "path activity pinned guard");
        return;
      }
    }catch(e){}
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

  var libList = document.getElementById("libList");
  function hScrollTextIsScrollable(el){
    try{ return !!(el && el.scrollWidth > el.clientWidth + 1); }catch(e){ return false; }
  }
  function stopHScrollTextAuto(el){
    try{
      if(!el) return;
      if(el._dpHScrollAutoFrame) cancelAnimationFrame(el._dpHScrollAutoFrame);
      if(el._dpHScrollAutoTimer) clearTimeout(el._dpHScrollAutoTimer);
      el._dpHScrollAutoFrame = 0;
      el._dpHScrollAutoTimer = 0;
      el._dpHScrollAutoRunning = false;
    }catch(e){}
  }
  function startHScrollTextAuto(el){
    try{
      if(!el || !hScrollTextIsScrollable(el)) return;
      stopHScrollTextAuto(el);
      try{ el.style.textOverflow = "clip"; }catch(e){}
      el.scrollLeft = 0;
      const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth);
      if(maxScroll <= 1) return;
      el._dpHScrollAutoTimer = setTimeout(()=>{
        const start = performance.now();
        const pxPerSecond = 34;
        const travelMs = Math.max(900, (maxScroll / pxPerSecond) * 1000);
        el._dpHScrollAutoRunning = true;
        const tick = (now)=>{
          try{
            if(!el._dpHScrollAutoRunning || !document.body.contains(el)) return;
            const endpointPauseMs = 1350;
            const t = (Number(now || performance.now()) - start) % ((travelMs * 2) + (endpointPauseMs * 2));
            if(t <= travelMs){
              el.scrollLeft = Math.min(maxScroll, (t / travelMs) * maxScroll);
            }else if(t <= travelMs + endpointPauseMs){
              el.scrollLeft = maxScroll;
            }else{
              const backT = (t - travelMs - endpointPauseMs) / travelMs;
              el.scrollLeft = Math.max(0, maxScroll * (1 - backT));
            }
            el._dpHScrollAutoFrame = requestAnimationFrame(tick);
          }catch(e){}
        };
        el._dpHScrollAutoFrame = requestAnimationFrame(tick);
      }, 650);
    }catch(e){}
  }
  function refreshSelectedHScrollText(){
    try{
      if(!libList) return;
      libList.querySelectorAll(".hScrollText").forEach((el)=>{
        if(el.closest && el.closest(".ipodItem.sel")) startHScrollTextAuto(el);
        else{
          stopHScrollTextAuto(el);
          try{ el.scrollLeft = 0; }catch(e){}
        }
      });
      if(libHeader && isPathPillVisible()){
        const text = document.getElementById("libHeaderText");
        if(text) startHScrollTextAuto(text);
      }
    }catch(e){}
  }
  function bindHScrollTextDrag(el){
    try{
      if(!el || el._dpHScrollBound) return;
      el._dpHScrollBound = true;
      return;
      let down = false;
      let startX = 0;
      let startLeft = 0;
      let moved = false;
      el.addEventListener("pointerdown", (ev)=>{
        if(!hScrollTextIsScrollable(el)) return;
        stopHScrollTextAuto(el);
        down = true;
        moved = false;
        startX = ev.clientX;
        startLeft = el.scrollLeft;
      }, {passive:true});
      el.addEventListener("pointermove", (ev)=>{
        if(!down || !hScrollTextIsScrollable(el)) return;
        const dx = ev.clientX - startX;
        if(Math.abs(dx) < 4) return;
        moved = true;
        el.scrollLeft = startLeft - dx;
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
      }, {passive:false});
      const end = (ev)=>{
        if(moved){
          try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        }
        down = false;
        moved = false;
        if(el.closest && el.closest(".ipodItem.sel")) startHScrollTextAuto(el);
      };
      el.addEventListener("pointerup", end, {passive:false});
      el.addEventListener("pointercancel", end, {passive:false});
      el.addEventListener("wheel", (ev)=>{
        if(!hScrollTextIsScrollable(el) || Math.abs(ev.deltaX) <= Math.abs(ev.deltaY)) return;
        try{ ev.stopPropagation(); }catch(e){}
      }, {passive:true});
    }catch(e){}
  }
  var ipodScreen = document.getElementById("ipodScreen");
  var visualizerBg = document.getElementById("visualizerBg");
  var npPageFadeTimer = null;
  var npPageFadeToken = 0;
  var nowPlaying = document.getElementById("nowPlaying");
  var npArt = document.getElementById("npArt");
  var npArtStill = document.getElementById("npArtStill");
  var pathPillNowRow = document.getElementById("pathPillNowRow");
  var pathPillNowText = document.getElementById("pathPillNowText");
  var infoPill = document.getElementById("infoPill");
  var infoPillContent = document.getElementById("infoPillContent");
  var npSeek = document.getElementById("npSeek");
  var npCur = document.getElementById("npCur");
  var npDur = document.getElementById("npDur");
  var npTech = document.getElementById("npTech");
  var npProgressWrap = document.getElementById("npProgressWrap");
  var npProgressFill = document.getElementById("npProgressFill");
  var npVideoOverlay = document.getElementById("npVideoOverlay");
  var npVideo = document.getElementById("npVideo");
  var npVolumeWrap = document.getElementById("npVolumeWrap");
  var npVolumeFill = document.getElementById("npVolumeFill");
  var npSeekIndicator = document.getElementById("npSeekIndicator");
  var pathPillMotion = {
    currentWidth: 0,
    targetWidth: 0,
    currentHeight: 29,
    targetHeight: 29,
    raf: 0,
    lastStepTs: 0,
    initialized: false
  };
  if(infoPill){
    infoPill.addEventListener("transitionend", ()=>{ forceInfoPillGlassRender("info pill transition", false); }, {passive:true});
    try{
      new MutationObserver(()=>{ forceInfoPillGlassRender("info pill mutation", false); }).observe(infoPill, {
        attributes: true,
        attributeFilter: ["class"]
      });
    }catch(e){}
  }

  function isPathPillVisible(){
    try{
      return !!(libHeader && !libHeader.classList.contains("pathPillHidden"));
    }catch(e){
      return false;
    }
  }

  function constrainPathPillWidth(infoPillMaxWidth, coverDisplayedWidth, screenFallbackWidth){
    const fallback = Math.max(1, Number(screenFallbackWidth) || 1);
    const info = Math.max(1, Number(infoPillMaxWidth) || fallback);
    const cover = Math.max(1, Number(coverDisplayedWidth) || fallback);
    return Math.max(1, Math.floor(Math.min(info, cover)));
  }

  function pathPillMotionNextWidth(currentWidth, targetWidth, elapsedMs){
    const current = Number(currentWidth) || 0;
    const target = Number(targetWidth) || 0;
    const elapsed = Math.max(1, Number(elapsedMs) || 16.7);
    const mix = 1 - Math.exp(-elapsed / 92);
    return current + ((target - current) * mix);
  }

  function pathPillTextOverflows(scrollWidth, clientWidth){
    return Number(scrollWidth) > Number(clientWidth) + 1;
  }

  function updatePathPillScrollingMasks(){
    try{
      [document.getElementById("libHeaderText"), pathPillNowText].forEach((el)=>{
        if(!el || !el.classList) return;
        el.classList.toggle("pathPillTextScrollable", pathPillTextOverflows(el.scrollWidth, el.clientWidth));
      });
    }catch(e){}
  }

  function markPathPillWidthChanged(){
    try{
      const renderer = liquidGlassRendererByKey("main");
      if(renderer){
        renderer._metricsDirty = true;
        (renderer.lenses || []).forEach((lens)=>{ try{ if(lens && lens.el && lens.el.classList && lens.el.classList.contains("pathPillGlass")) lens.rectPx = null; }catch(e){} });
        // Width was applied in this frame; draw its lens before this frame's
        // paint rather than waiting for the scheduler's next RAF.
      }
      const scheduler = window.DebriPod && window.DebriPod.frameScheduler;
      if(scheduler && scheduler.mark) scheduler.mark({metrics:true, render:true, textContrast:true, keepAlive:true});
    }catch(e){}
  }

  function schedulePathPillMotion(){
    if(pathPillMotion.raf) return;
    pathPillMotion.raf = 1;
    const step = (frameState)=>{
      pathPillMotion.raf = 0;
      try{
        const now = Number((frameState && (frameState.timestamp || frameState.time)) || performance.now());
        const interval = (typeof animationFrameIntervalMs === "function") ? animationFrameIntervalMs("pathPill") : (1000 / 60);
        if(pathPillMotion.lastStepTs && now - pathPillMotion.lastStepTs < interval - 1){
          schedulePathPillMotion();
          return;
        }
        const elapsed = pathPillMotion.lastStepTs ? Math.max(1, now - pathPillMotion.lastStepTs) : interval;
        pathPillMotion.lastStepTs = now;
        pathPillMotion.currentWidth = pathPillMotionNextWidth(pathPillMotion.currentWidth, pathPillMotion.targetWidth, elapsed);
        pathPillMotion.currentHeight = pathPillMotionNextWidth(pathPillMotion.currentHeight, pathPillMotion.targetHeight, elapsed);
        if(Math.abs(pathPillMotion.targetWidth - pathPillMotion.currentWidth) < 0.35){
          pathPillMotion.currentWidth = pathPillMotion.targetWidth;
        }
        if(Math.abs(pathPillMotion.targetHeight - pathPillMotion.currentHeight) < 0.35){
          pathPillMotion.currentHeight = pathPillMotion.targetHeight;
        }
        document.documentElement.style.setProperty("--pathPillRenderedWidth", pathPillMotion.currentWidth.toFixed(2) + "px");
        document.documentElement.style.setProperty("--pathPillRenderedHeight", pathPillMotion.currentHeight.toFixed(2) + "px");
        markPathPillWidthChanged();
        updatePathPillScrollingMasks();
        if(pathPillMotion.currentWidth !== pathPillMotion.targetWidth || pathPillMotion.currentHeight !== pathPillMotion.targetHeight) schedulePathPillMotion();
      }catch(e){}
    };
    try{
      const scheduler = window.DebriPod && window.DebriPod.frameScheduler;
      if(scheduler && scheduler.request){
        scheduler.request("path-pill-motion", step);
        return;
      }
    }catch(e){}
    requestAnimationFrame((timestamp)=>step({timestamp:timestamp}));
  }

  function setPathPillTargetWidth(target){
    const next = Math.max(1, Number(target) || 1);
    const root = document.documentElement;
    root.style.setProperty("--pathPillTargetWidth", next + "px");
    pathPillMotion.targetWidth = next;
    if(!pathPillMotion.initialized){
      pathPillMotion.initialized = true;
      pathPillMotion.currentWidth = next;
      root.style.setProperty("--pathPillRenderedWidth", next + "px");
      updatePathPillScrollingMasks();
      return;
    }
    schedulePathPillMotion();
  }

  function setPathPillTargetHeight(target){
    const next = Math.max(1, Number(target) || 1);
    const root = document.documentElement;
    root.style.setProperty("--pathPillTargetHeight", next + "px");
    pathPillMotion.targetHeight = next;
    if(!pathPillMotion.initialized){
      pathPillMotion.initialized = true;
      pathPillMotion.currentHeight = next;
      root.style.setProperty("--pathPillRenderedHeight", next + "px");
      return;
    }
    schedulePathPillMotion();
  }

  function pathPillIntrinsicTextWidth(el){
    if(!el || !String(el.textContent || "").trim()) return 0;
    // scrollWidth includes the stretched row's box, so it cannot shrink.
    // A Range measures the inline content, including mixed title/album fonts.
    const range = document.createRange();
    range.selectNodeContents(el);
    const width = Math.ceil(range.getBoundingClientRect().width || 0);
    if(range.detach) range.detach();
    return width;
  }

  function updatePathPillMaxWidth(){
    try{
      const content = document.querySelector(".ipodScreenContent");
      const rect = content ? content.getBoundingClientRect() : null;
      const root = document.documentElement;
      const fallbackWidth = rect && rect.width ? Math.max(1, Math.floor(rect.width)) : Math.max(1, Math.floor(window.innerWidth || 1) - 24);
      const rootStyle = getComputedStyle(root);
      const screenFrame = Math.max(0, parseFloat(rootStyle.getPropertyValue("--screenFrame")) || 0);
      const infoWidth = Math.max(1, Math.floor(fallbackWidth - (screenFrame * 2)));
      const artCandidates = [npArt, npArtStill].filter(Boolean);
      const coverRect = artCandidates
        .map((el)=>{
          try{
            const style = window.getComputedStyle ? getComputedStyle(el) : null;
            const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
            return style && style.display === "none" ? null : rect;
          }catch(e){ return null; }
        })
        .find((rect)=>rect && rect.width > 1) || null;
      const coverWidth = coverRect && coverRect.width > 1 ? coverRect.width : fallbackWidth;
      const maxWidth = constrainPathPillWidth(infoWidth, coverWidth, fallbackWidth);
      root.style.setProperty("--pathPillMaxWidth", maxWidth + "px");
      root.style.setProperty("--infoPillWidth", infoWidth + "px");
      root.style.setProperty("--infoPillHeight", "42px");
      const pathText = document.getElementById("libHeaderText");
      const padX = Math.max(0, parseFloat(rootStyle.getPropertyValue("--playbackPillPadX")) || 10);
      const basePadX = 12;
      const pathWidth = pathPillIntrinsicTextWidth(pathText);
      const nowWidth = (libHeader && libHeader.classList.contains("pathPillExpanded") && pathPillNowText)
        ? pathPillIntrinsicTextWidth(pathPillNowText)
        : 0;
      const expanded = !!(libHeader && libHeader.classList.contains("pathPillExpanded"));
      const targetPad = expanded ? padX : basePadX;
      const measured = Math.max(pathWidth, nowWidth) + targetPad * 2;
      const minWidth = Math.min(maxWidth, targetPad * 2 + 1);
      const target = Math.max(1, Math.min(maxWidth, Math.max(minWidth, measured || minWidth)));
      setPathPillTargetWidth(target);
      const pathStyle = window.getComputedStyle ? getComputedStyle(libHeader) : null;
      const padY = Math.max(0, parseFloat(pathStyle && pathStyle.paddingTop || "5") || 5);
      const rowGap = Math.max(0, parseFloat(rootStyle.getPropertyValue("--playbackPillRowGap")) || 1);
      const pathHeight = Math.max(14, Math.ceil((pathText && pathText.getBoundingClientRect ? pathText.getBoundingClientRect().height : 14) || 14));
      const nowHeight = expanded && pathPillNowText
        ? Math.max(14, Math.ceil((pathPillNowText.getBoundingClientRect ? pathPillNowText.getBoundingClientRect().height : 14) || 14))
        : 0;
      setPathPillTargetHeight(pathHeight + (expanded ? nowHeight + rowGap : 0) + padY * 2);
    }catch(e){}
  }
  try{ window.updatePathPillMaxWidth = updatePathPillMaxWidth; }catch(e){}
  try{
    if("ResizeObserver" in window){
      const pathPillGeometryObserver = new ResizeObserver(()=>updatePathPillMaxWidth());
      [npArt, npArtStill, document.querySelector(".ipodScreenContent"), infoPill].filter(Boolean).forEach((el)=>pathPillGeometryObserver.observe(el));
    }
  }catch(e){}
  try{ if(npArtStill) npArtStill.addEventListener("load", ()=>updatePathPillMaxWidth(), {passive:true}); }catch(e){}

  function refreshPlaybackPillTextLayer(reason, force){
    try{
      if(typeof updateGlassTextUnderColors === "function"){
        updateGlassTextUnderColors({reason:reason || "playback pill text", force:force !== false});
      }
    }catch(e){}
    try{
      const scheduler = (window.DebriPod && window.DebriPod.frameScheduler) ? window.DebriPod.frameScheduler : null;
      if(scheduler && scheduler.mark) scheduler.mark({textContrast:true, render:true});
    }catch(e){}
  }

  function forcePathPillGlassRender(reason, refreshSource, refreshText){
    try{
      updatePathPillMaxWidth();
      if(refreshText !== false) refreshPlaybackPillTextLayer(reason || "path pill", false);
      const renderer = liquidGlassRendererByKey("main");
      if(!renderer) return;
      if(renderer.setVisible) renderer.setVisible(true);
      renderer._metricsDirty = true;
      let touched = false;
      if(renderer.lenses && renderer.lenses.length){
        renderer.lenses.forEach((lens)=>{
          try{
            if(!lens || !lens.el || !lens.el.classList || !lens.el.classList.contains("pathPillGlass")) return;
            touched = true;
            lens.rectPx = null;
            if(lens.updateMetrics) lens.updateMetrics();
            lens.revealTypeIndex = 1;
            lens._revealProgress = pathPillRenderOpacity();
          }catch(e){}
        });
      }
      if(refreshSource !== false) refreshLiquidGlassVisualizerSources(reason || "path pill", {keys:["main"]});
      if(touched && typeof markFrameWork === "function") markFrameWork({metrics:true, render:true, keepAlive:true});
    }catch(e){}
  }

  function hidePathPillGlassNow(reason){
    try{
      const renderer = liquidGlassRendererByKey("main");
      if(!renderer || !renderer.lenses) return;
      renderer.lenses.forEach((lens)=>{
        try{
          if(!lens || !lens.el || !lens.el.classList || !lens.el.classList.contains("pathPillGlass")) return;
          lens.revealTypeIndex = 1;
          lens._revealProgress = 0;
          lens.rectPx = null;
        }catch(e){}
      });
      if(typeof markFrameWork === "function") markFrameWork({metrics:true, render:true});
    }catch(e){}
  }

  function pathPillRenderOpacity(){
    try{
      const value = parseFloat(window.getComputedStyle(libHeader).opacity || "1");
      return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
    }catch(e){
      return 1;
    }
  }

  function animatePathPillGlassTransition(reason, durationMs){
    try{
      const dur = Math.max(80, Number(durationMs || 240));
      const token = ((animatePathPillGlassTransition._token || 0) + 1);
      animatePathPillGlassTransition._token = token;
      const started = performance.now();
      let didRefresh = false;
      const tick = (now)=>{
        try{
          if(animatePathPillGlassTransition._token !== token) return;
          const frameNow = Number(now || performance.now());
          const elapsed = frameNow - started;
          forcePathPillGlassRender(reason || "path pill transition", !didRefresh, !didRefresh);
          didRefresh = true;
          if(elapsed < dur) requestAnimationFrame(tick);
          else{
            forcePathPillGlassRender((reason || "path pill transition") + " end", false, true);
            refreshPlaybackPillTextLayer((reason || "path pill transition") + " text end", true);
          }
        }catch(e){}
      };
      requestAnimationFrame(tick);
    }catch(e){}
  }

  function schedulePathPillHideFinal(reason){
    try{
      if(pathPillHideFinalTimer) clearTimeout(pathPillHideFinalTimer);
      pathPillHideFinalTimer = setTimeout(()=>{
        pathPillHideFinalTimer = null;
        try{
          if(isPathPillVisible() || (libHeader && libHeader.classList.contains("playbackPillVisible"))) return;
          hidePathPillGlassNow(reason || "path pill hidden final");
        }catch(e){}
      }, playbackPillTransitionMs + 40);
    }catch(e){}
  }

  function scheduleInfoPillHideFinal(reason){
    try{
      if(infoPillHideFinalTimer) clearTimeout(infoPillHideFinalTimer);
      infoPillHideFinalTimer = setTimeout(()=>{
        infoPillHideFinalTimer = null;
        try{
          if(isInfoPillVisible() || (infoPill && infoPill.classList.contains("playbackPillVisible"))) return;
          hideInfoPillGlassNow(reason || "info pill hide final");
        }catch(e){}
      }, playbackPillTransitionMs + 40);
    }catch(e){}
  }

  function clearPlaybackPillHideFinalTimers(){
    try{
      if(pathPillHideFinalTimer) clearTimeout(pathPillHideFinalTimer);
      if(infoPillHideFinalTimer) clearTimeout(infoPillHideFinalTimer);
      if(playbackPillVisibleClassTimer) clearTimeout(playbackPillVisibleClassTimer);
      pathPillHideFinalTimer = null;
      infoPillHideFinalTimer = null;
      playbackPillVisibleClassTimer = null;
    }catch(e){}
  }

  function hasNowPlayingMetadata(){
    try{
      if(state && state.now) return true;
      if(state && state.nowMeta && typeof state.nowMeta === "object" && Object.keys(state.nowMeta).length) return true;
      return !!(pathPillNowText && String(pathPillNowText.dataset.text || pathPillNowText.textContent || "").trim());
    }catch(e){
      return false;
    }
  }

  function isInfoPillVisible(){
    try{
      return !!(infoPill && !infoPill.classList.contains("infoPillHidden"));
    }catch(e){
      return false;
    }
  }

  function forceInfoPillGlassRender(reason, refreshSource, refreshText){
    try{
      updatePathPillMaxWidth();
      if(refreshText !== false) refreshPlaybackPillTextLayer(reason || "info pill", false);
      const renderer = liquidGlassRendererByKey("main");
      if(!renderer) return;
      if(renderer.setVisible) renderer.setVisible(true);
      renderer._metricsDirty = true;
      let touched = false;
      if(renderer.lenses && renderer.lenses.length){
        renderer.lenses.forEach((lens)=>{
          try{
            if(!lens || !lens.el || !lens.el.classList || !lens.el.classList.contains("infoPillGlass")) return;
            touched = true;
            lens.rectPx = null;
            if(lens.updateMetrics) lens.updateMetrics();
            lens.revealTypeIndex = 1;
            lens._revealProgress = infoPillRenderOpacity();
          }catch(e){}
        });
      }
      if(refreshSource !== false) refreshLiquidGlassVisualizerSources(reason || "info pill", {keys:["main"]});
      if(touched && typeof markFrameWork === "function") markFrameWork({metrics:true, render:true, keepAlive:true});
    }catch(e){}
  }

  function hideInfoPillGlassNow(reason){
    try{
      const renderer = liquidGlassRendererByKey("main");
      if(!renderer || !renderer.lenses) return;
      renderer.lenses.forEach((lens)=>{
        try{
          if(!lens || !lens.el || !lens.el.classList || !lens.el.classList.contains("infoPillGlass")) return;
          lens.revealTypeIndex = 1;
          lens._revealProgress = 0;
          lens.rectPx = null;
        }catch(e){}
      });
      if(typeof markFrameWork === "function") markFrameWork({metrics:true, render:true});
    }catch(e){}
  }

  function infoPillRenderOpacity(){
    try{
      const value = parseFloat(window.getComputedStyle(infoPill).opacity || "1");
      return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
    }catch(e){
      return 1;
    }
  }

  function animateInfoPillGlassTransition(reason, durationMs){
    try{
      const dur = Math.max(80, Number(durationMs || 240));
      const token = ((animateInfoPillGlassTransition._token || 0) + 1);
      animateInfoPillGlassTransition._token = token;
      const started = performance.now();
      let didRefresh = false;
      const tick = (now)=>{
        try{
          if(animateInfoPillGlassTransition._token !== token) return;
          const frameNow = Number(now || performance.now());
          const elapsed = frameNow - started;
          forceInfoPillGlassRender(reason || "info pill transition", !didRefresh, !didRefresh);
          didRefresh = true;
          if(elapsed < dur) requestAnimationFrame(tick);
          else{
            forceInfoPillGlassRender((reason || "info pill transition") + " end", false, true);
            refreshPlaybackPillTextLayer((reason || "info pill transition") + " text end", true);
          }
        }catch(e){}
      };
      requestAnimationFrame(tick);
    }catch(e){}
  }

  function setPlaybackPillsPinned(on){
    playbackPillsPinned = !!on;
    try{ localStorage.setItem("debripod_playback_pills_pinned", playbackPillsPinned ? "1" : "0"); }catch(e){}
    if(playbackPillsPinned) showPlaybackPills(true, "pin");
    else hidePlaybackPillsImmediate("unpin", false);
  }

  function setPlaybackPillVisibleClass(on){
    try{
      if(libHeader) libHeader.classList.toggle("playbackPillVisible", !!on);
      if(infoPill) infoPill.classList.toggle("playbackPillVisible", !!on);
      if(on) refreshPlaybackPillTextLayer("playback pill visible class", true);
    }catch(e){}
  }

  function schedulePlaybackPillVisibleClassRemoval(){
    try{
      if(playbackPillVisibleClassTimer) clearTimeout(playbackPillVisibleClassTimer);
      playbackPillVisibleClassTimer = setTimeout(()=>{
        playbackPillVisibleClassTimer = null;
        setPlaybackPillVisibleClass(false);
        refreshPlaybackPillTextLayer("playback pill hidden class final", true);
      }, playbackPillTransitionMs + 20);
    }catch(e){}
  }

  function showPlaybackPills(pinned, reason){
    const effectivePinned = !!pinned || !!playbackPillsPinned;
    playbackPillsVisible = hasNowPlayingMetadata();
    if(!playbackPillsVisible){
      hidePlaybackPillsImmediate(reason || "no media");
      try{ if(libHeader) libHeader.classList.remove("pathPillExpanded"); }catch(e){}
      try{ updatePathPillMaxWidth(); }catch(e){}
      showPathPill(!!pathPillPinned);
      return;
    }
    try{ if(playbackPillsHideTimer) clearTimeout(playbackPillsHideTimer); }catch(e){}
    playbackPillsHideTimer = null;
    clearPlaybackPillHideFinalTimers();
    showPathPill(true);
    try{
      if(libHeader) libHeader.classList.add("pathPillExpanded");
      setPlaybackPillVisibleClass(true);
      updatePathPillMaxWidth();
      if(infoPill){
        const wasHidden = infoPill.classList.contains("infoPillHidden");
        infoPill.classList.remove("infoPillHidden");
        infoPill.style.pointerEvents = "";
        if(wasHidden) animateInfoPillGlassTransition(reason || "info pill show", playbackPillTransitionMs);
        else forceInfoPillGlassRender(reason || "info pill visible", false);
      }
      animatePathPillGlassTransition(reason || "playback pills show", playbackPillTransitionMs);
      setTimeout(()=> startHScrollTextAuto(pathPillNowText), playbackPillTransitionMs + 20);
    }catch(e){}
    if(!effectivePinned) scheduleHidePlaybackPills(2500);
  }

  function hidePlaybackPillsImmediate(reason, pinnedValue){
    if(typeof pinnedValue === "boolean"){
      playbackPillsPinned = !!pinnedValue;
      try{ localStorage.setItem("debripod_playback_pills_pinned", playbackPillsPinned ? "1" : "0"); }catch(e){}
      if(playbackPillsPinned && hasNowPlayingMetadata()){
        showPlaybackPills(true, reason || "pinned guard");
        return;
      }
    }else if(playbackPillsPinned && hasNowPlayingMetadata()){
      showPlaybackPills(true, reason || "pinned guard");
      return;
    }
    try{ if(playbackPillsHideTimer) clearTimeout(playbackPillsHideTimer); }catch(e){}
    playbackPillsHideTimer = null;
    playbackPillsVisible = false;
    try{
      if(infoPill){
        infoPill.classList.add("infoPillHidden");
        infoPill.style.pointerEvents = "none";
        animateInfoPillGlassTransition(reason || "info pill hide", playbackPillTransitionMs);
        scheduleInfoPillHideFinal(reason || "info pill hide final");
      }
      if(!pathPillPinned && libHeader) {
        libHeader.classList.add("pathPillHidden");
        animatePathPillGlassTransition(reason || "playback path hide", playbackPillTransitionMs);
        schedulePathPillHideFinal(reason || "playback path hide final");
      }
      schedulePlaybackPillVisibleClassRemoval();
    }catch(e){}
  }

    function scheduleHidePlaybackPills(ms){
    try{
      try{ if(playbackPillsHideTimer) clearTimeout(playbackPillsHideTimer); }catch(e){}
      playbackPillsHideTimer = setTimeout(()=>{
        try{
          if(playbackPillsPinned) return;
          if(seekMode) return;
          const m = (typeof wheelMedia === "function") ? wheelMedia() : null;
          if(m && m.paused) return;
          hidePlaybackPillsImmediate("auto hide");
        }catch(e){}
      }, (ms || 2500));
    }catch(e){}
  }

  function playbackPillActivity(pinned, reason){
    const effectivePinned = !!pinned || !!playbackPillsPinned;
    if(!hasNowPlayingMetadata()) return;
    if(!isPlaybackPillsShown()){
      showPlaybackPills(effectivePinned, reason || "activity");
    }else if(effectivePinned){
      try{ if(playbackPillsHideTimer) clearTimeout(playbackPillsHideTimer); }catch(e){}
      playbackPillsHideTimer = null;
    }else{
      scheduleHidePlaybackPills(2500);
    }
  }

  function isPlaybackPillsShown(){
    try{
      return !!(playbackPillsVisible && hasNowPlayingMetadata() && infoPill && !infoPill.classList.contains("infoPillHidden"));
    }catch(e){
      return false;
    }
  }

  function togglePlaybackPillsFromArt(){
    if(!hasNowPlayingMetadata()) return;
    try{
      const now = performance.now();
      if(togglePlaybackPillsFromArt._lastTs && now - togglePlaybackPillsFromArt._lastTs < 180) return;
      togglePlaybackPillsFromArt._lastTs = now;
    }catch(e){}
    if(playbackPillsPinned) hidePlaybackPillsImmediate("art unpin", false);
    else setPlaybackPillsPinned(true);
  }
  function bindPlaybackPillCoverToggle(el){
    try{
      if(!el || el._dpPlaybackPillToggleBound) return;
      el._dpPlaybackPillToggleBound = true;
      const singleClickDelayMs = 320;
      const gestureSuppressMs = 520;
      const commit = ()=>{
        bindPlaybackPillCoverToggle.timer = null;
        const now = performance.now();
        if(bindPlaybackPillCoverToggle.lastGestureAt && now - bindPlaybackPillCoverToggle.lastGestureAt < gestureSuppressMs) return;
        bindPlaybackPillCoverToggle.lastGestureAt = now;
        togglePlaybackPillsFromArt();
      };
      const run = ()=>{
        if(bindPlaybackPillCoverToggle.timer) clearTimeout(bindPlaybackPillCoverToggle.timer);
        bindPlaybackPillCoverToggle.timer = setTimeout(()=>{
          commit();
        }, singleClickDelayMs);
      };
      el.addEventListener("click", (ev)=>{
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        if(Number(ev.detail || 0) >= 2){
          if(bindPlaybackPillCoverToggle.timer) clearTimeout(bindPlaybackPillCoverToggle.timer);
          commit();
        }else run();
      }, {passive:false});
      el.addEventListener("dblclick", (ev)=>{
        try{ ev.preventDefault(); ev.stopPropagation(); }catch(e){}
        if(bindPlaybackPillCoverToggle.timer) clearTimeout(bindPlaybackPillCoverToggle.timer);
        bindPlaybackPillCoverToggle.timer = null;
      }, {passive:false});
    }catch(e){}
  }
  bindPlaybackPillCoverToggle(npArt);
  bindPlaybackPillCoverToggle(npArtStill);
  window.addEventListener("resize", ()=>{
    wheelGlassTiltRect = null;
    visualizerArtBounds = null;
    visualizerArtBoundsLastTs = 0;
    forcePathPillGlassRender("resize", true);
    forceInfoPillGlassRender("resize", true);
  }, {passive:true});
  if(window.visualViewport){
    window.visualViewport.addEventListener("resize", ()=>{
      wheelGlassTiltRect = null;
      visualizerArtBounds = null;
      visualizerArtBoundsLastTs = 0;
      forcePathPillGlassRender("visual viewport resize", true);
      forceInfoPillGlassRender("visual viewport resize", true);
    }, {passive:true});
    window.visualViewport.addEventListener("scroll", ()=>{
      wheelGlassTiltRect = null;
      visualizerArtBounds = null;
      visualizerArtBoundsLastTs = 0;
      forcePathPillGlassRender("visual viewport scroll", true);
      forceInfoPillGlassRender("visual viewport scroll", true);
    }, {passive:true});
  }
  setTimeout(()=>{
    forcePathPillGlassRender("initial path pill", true);
    forceInfoPillGlassRender("initial info pill", true);
  }, 0);
