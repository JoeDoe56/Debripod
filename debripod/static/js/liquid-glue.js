  function applyUiTuningCss(){
    try{
      const root = document.documentElement;
      root.style.setProperty("--centerBounceScale", String(1 + clampNumber(uiSettings.centerBounceAmount, DEFAULT_UI_SETTINGS.centerBounceAmount, 0, 0.3)));
      root.style.setProperty("--centerBounceDuration", String(clampNumber(uiSettings.centerBounceDuration, DEFAULT_UI_SETTINGS.centerBounceDuration, 0, 1000)) + "ms");
      root.style.setProperty("--centerBounceOvershoot", String(clampNumber(uiSettings.centerBounceOvershoot, DEFAULT_UI_SETTINGS.centerBounceOvershoot, 0, 1.4)));
    }catch(e){}
  }
  applyUiTuningCss();

  function normalizeWheelRotationMaxDegrees(value){
    const n = Number(value);
    if(!Number.isFinite(n)) return 10;
    return Math.max(0, Math.min(12, n));
  }

  function liquidGlassPresetOptions(){
    const preset = LIQUID_GL_PRESETS[normalizeLiquidGlassPreset(liquidGlassPresetName)] || LIQUID_GL_PRESETS.default;
    const options = Object.assign({
      snapshot: "#divwrap",
      resolution: 1.0,
      reveal: "none",
      tilt: false,
      magnify: 1,
      glassMode: normalizeLiquidGlassMode(liquidGlassModeName)
    }, preset);
    return options;
  }

  function liquidGlassStyleOptions(presetName, modeName){
    const preset = LIQUID_GL_PRESETS[normalizeLiquidGlassPreset(presetName)] || LIQUID_GL_PRESETS.default;
    return Object.assign({
      glassMode: normalizeLiquidGlassMode(modeName)
    }, preset);
  }

  function asLiquidArray(value){
    if(!value) return [];
    return Array.isArray(value) ? value : [value];
  }

  function liquidGlassRenderers(){
    const list = [];
    try{
      if(window.__liquidGLRenderer__) list.push(window.__liquidGLRenderer__);
      const renderers = window.__liquidGLRenderers__;
      if(renderers && typeof renderers === "object"){
        Object.keys(renderers).forEach((key)=>{
          const renderer = renderers[key];
          if(renderer && list.indexOf(renderer) < 0) list.push(renderer);
        });
      }
    }catch(e){}
    return list;
  }

  function liquidGlassRendererByKey(key){
    try{
      const wanted = key || "default";
      const renderers = window.__liquidGLRenderers__;
      if(renderers && renderers[wanted]) return renderers[wanted];
      if(wanted === "default") return window.__liquidGLRenderer__ || null;
    }catch(e){}
    return null;
  }

  function liquidWheelRenderer(){
    return liquidGlassRendererByKey("wheel");
  }

  function applyLiquidGlassStyleOptions(options){
    try{
      const opts = options || liquidGlassStyleOptions(liquidGlassPresetName, liquidGlassModeName);
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.lenses) return;
        renderer.lenses.forEach((lens)=>{
          if(!lens || !lens.options) return;
          ["refraction", "bevelDepth", "bevelWidth", "frost", "specular"].forEach((key)=>{
            if(opts[key] !== undefined) lens.options[key] = opts[key];
          });
          lens.options.glassMode = normalizeLiquidGlassMode(opts.glassMode);
          if(lens._glassModeIndex) lens.glassModeIndex = lens._glassModeIndex(lens.options.glassMode);
        });
        if(renderer.render) renderer.render(currentVisualizerFrameState());
      });
    }catch(e){}
  }

  function transitionLiquidGlassStyle(fromOptions, toOptions){
    try{
      if(!liquidGlassReady){
        applyLiquidGlassStyleOptions(toOptions);
        return;
      }
      const duration = 420;
      const started = performance.now();
      const numericKeys = ["refraction", "bevelDepth", "bevelWidth", "frost"];
      const tick = (now)=>{
        const t = Math.max(0, Math.min(1, (now - started) / duration));
        const eased = 1 - Math.pow(1 - t, 3);
        const mixed = Object.assign({}, toOptions);
        mixed.glassMode = eased < 0.55 ? fromOptions.glassMode : toOptions.glassMode;
        numericKeys.forEach((key)=>{
          const a = Number(fromOptions[key]);
          const b = Number(toOptions[key]);
          mixed[key] = (Number.isFinite(a) ? a : 0) + ((Number.isFinite(b) ? b : 0) - (Number.isFinite(a) ? a : 0)) * eased;
        });
        applyLiquidGlassStyleOptions(mixed);
        if(t < 1){
          requestAnimationFrame(tick);
        }else{
          applyLiquidGlassStyleOptions(toOptions);
          scheduleLiquidGlassSnapshot("ui settings", true);
        }
      };
      requestAnimationFrame(tick);
    }catch(e){
      applyLiquidGlassStyleOptions(toOptions);
    }
  }

  function setLiquidGlassSettings(presetName, modeName, smooth){
    const fromOptions = liquidGlassStyleOptions(liquidGlassPresetName, liquidGlassModeName);
    liquidGlassPresetName = normalizeLiquidGlassPreset(presetName);
    liquidGlassModeName = normalizeLiquidGlassMode(modeName);
    uiSettings.liquidGlassPreset = liquidGlassPresetName;
    uiSettings.liquidGlassMode = liquidGlassModeName;
    saveUiSettings();
    const toOptions = liquidGlassStyleOptions(liquidGlassPresetName, liquidGlassModeName);
    if(smooth){
      transitionLiquidGlassStyle(fromOptions, toOptions);
    }else{
      applyLiquidGlassStyleOptions(toOptions);
    }
  }

  function mountLiquidCanvas(){
    try{
      const wrap = document.getElementById("divwrap");
      if(!wrap) return;
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.canvas) return;
        renderer.canvas.classList.add("liquidGlassCanvas");
        const key = renderer.rendererKey || (renderer === window.__liquidGLRenderer__ ? "default" : "");
        renderer.canvas.classList.toggle("liquidGlassCanvasDefault", key === "default");
        renderer.canvas.classList.toggle("liquidGlassCanvasWheel", key === "wheel");
        renderer.canvas.classList.toggle("liquidGlassCanvasNpOverlay", key === "npOverlay");
        renderer.canvas.classList.toggle("liquidGlassCanvasScreenFrame", key === "screenFrame");
        renderer.canvas.setAttribute("data-liquid-renderer", key || "unknown");
        if(key === "wheel"){
          const wheelHost = document.getElementById("wheel") || document.querySelector(".ipodWheelWrap");
          if(wheelHost && renderer.canvas.parentNode !== wheelHost){
            wheelHost.insertBefore(renderer.canvas, wheelHost.firstChild);
          }
          positionWheelLiquidCanvas();
        }else if(renderer.canvas.parentNode !== wrap){
          const afterBg = document.getElementById("visualizerBg");
          if(afterBg && afterBg.parentNode === wrap && afterBg.nextSibling){
            wrap.insertBefore(renderer.canvas, afterBg.nextSibling);
          }else{
            wrap.insertBefore(renderer.canvas, wrap.firstChild);
          }
        }
        renderer.canvas.style.pointerEvents = "none";
        renderer.canvas.style.setProperty("z-index", key === "screenFrame" ? "64" : (key === "npOverlay" ? "75" : (key === "wheel" ? "10" : "65")), "important");
      });
      debugLiquidGlassRenderers("mount");
    }catch(e){}
  }

  function positionWheelLiquidCanvas(){
    try{
      const renderer = liquidWheelRenderer();
      const canvas = renderer && renderer.canvas;
      const host = document.getElementById("wheel") || document.querySelector(".ipodWheelWrap");
      if(!canvas || !host) return;
      const rect = wheelGlassTiltRect || host.getBoundingClientRect();
      canvas.style.position = "absolute";
      canvas.style.setProperty("position", "absolute", "important");
      canvas.style.setProperty("inset", "auto", "important");
      canvas.style.setProperty("left", (-Math.round(rect.left || 0)) + "px", "important");
      canvas.style.setProperty("top", (-Math.round(rect.top || 0)) + "px", "important");
      canvas.style.right = "auto";
      canvas.style.bottom = "auto";
      canvas.style.setProperty("width", (window.innerWidth || canvas.width || 1) + "px", "important");
      canvas.style.setProperty("height", (window.innerHeight || canvas.height || 1) + "px", "important");
      canvas.style.setProperty("pointer-events", "none", "important");
      canvas.style.setProperty("z-index", "10", "important");
    }catch(e){}
  }

  function refreshLiquidGlassSource(renderer, reason){
    try{
      if(!renderer || !renderer.refreshSourceTexture) return;
      renderer.refreshSourceTexture(reason || "app");
    }catch(e){}
  }

  function refreshLiquidGlassVisualizerSources(reason){
    try{
      ["default", "wheel", "screenFrame"].forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(!renderer) return;
        if(visualizerBg && renderer.updateTextureFromCanvas){
          renderer.updateTextureFromCanvas(visualizerBg, {reason: reason || "visualizer", allowDark: true, sourceRect: {left:0, top:0, width: window.innerWidth || 1, height: window.innerHeight || 1}});
        }else{
          refreshLiquidGlassSource(renderer, reason || "visualizer fallback");
        }
      });
    }catch(e){}
  }

  function refreshNpOverlayGlassSource(reason){
    try{
      const renderer = liquidGlassRendererByKey("npOverlay");
      if(!renderer) return;
      const img = (npArt && npArt.complete && npArt.naturalWidth && npArt.naturalHeight) ? npArt : null;
      if(img && renderer.updateTextureFromCanvas){
        const rect = img.getBoundingClientRect();
        const cssW = Math.max(1, Math.round(rect.width || 0));
        const cssH = Math.max(1, Math.round(rect.height || 0));
        if(cssW > 1 && cssH > 1){
          if(!refreshNpOverlayGlassSource._canvas){
            refreshNpOverlayGlassSource._canvas = document.createElement("canvas");
            refreshNpOverlayGlassSource._ctx = refreshNpOverlayGlassSource._canvas.getContext("2d");
          }
          const canvas = refreshNpOverlayGlassSource._canvas;
          const ctx = refreshNpOverlayGlassSource._ctx;
          const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
          const drawW = Math.max(1, Math.round(cssW * dpr));
          const drawH = Math.max(1, Math.round(cssH * dpr));
          if(canvas.width !== drawW || canvas.height !== drawH){
            canvas.width = drawW;
            canvas.height = drawH;
          }
          if(ctx){
            const iw = img.naturalWidth || 1;
            const ih = img.naturalHeight || 1;
            const coverScale = Math.max(cssW / iw, cssH / ih);
            const srcW = Math.max(1, cssW / coverScale);
            const srcH = Math.max(1, cssH / coverScale);
            const sx = Math.max(0, (iw - srcW) / 2);
            const sy = Math.max(0, (ih - srcH) / 2);
            ctx.clearRect(0, 0, drawW, drawH);
            ctx.drawImage(img, sx, sy, srcW, srcH, 0, 0, drawW, drawH);
            renderer.updateTextureFromCanvas(canvas, {
              reason: reason || "album art visible crop",
              allowDark: true,
              sourceRect: {left: rect.left, top: rect.top, width: rect.width || cssW, height: rect.height || cssH}
            });
          }else if(renderer.updateTextureFromImage){
            renderer.updateTextureFromImage(img, {reason: reason || "album art"});
          }
        }else if(renderer.updateTextureFromImage){
          renderer.updateTextureFromImage(img, {reason: reason || "album art"});
        }
      }else if(renderer.updateTextureFromSolidColor){
        renderer.updateTextureFromSolidColor(8, 8, [5, 5, 7, 255], {reason: reason || "album art fallback", allowDark: true});
      }else{
      refreshLiquidGlassSource(renderer, reason || "album art fallback");
      }
    }catch(e){}
  }

  function applyNpOverlayGlassTuning(renderer){
    try{
      if(!renderer || !renderer.lenses) return;
      const dark = 0.18 * clampNumber(uiSettings.infoPillDarkMultiplier, 1, 0, 4);
      const light = 0.18 * clampNumber(uiSettings.infoPillLightMultiplier, 1, 0, 4);
      renderer.lenses.forEach((lens)=>{
        if(!lens || !lens.options) return;
        lens.options.glassDarkAmount = dark;
        lens.options.glassLightAmount = light;
      });
    }catch(e){}
  }

  function npOverlayPillRenderOpacity(){
    try{
      if(!npOverlayPill) return 1;
      const value = parseFloat(window.getComputedStyle(npOverlayPill).opacity || "1");
      return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
    }catch(e){
      return 1;
    }
  }

  function forceNpOverlayGlassRender(reason, refreshSource){
    try{
      const renderer = liquidGlassRendererByKey("npOverlay");
      if(!renderer) return;
      applyNpOverlayGlassTuning(renderer);
      if(renderer.setVisible) renderer.setVisible(true);
      renderer._metricsDirty = true;
      renderer._snapshotRectPx = null;
      if(renderer.lenses && renderer.lenses.length){
        renderer.lenses.forEach((lens)=>{
          try{
            lens.rectPx = null;
            if(lens.updateMetrics) lens.updateMetrics();
          }catch(e){}
        });
      }
      if(refreshSource !== false) refreshNpOverlayGlassSource(reason || "np overlay render");
      const opacity = npOverlayPillRenderOpacity();
      if(renderer.lenses && renderer.lenses.length){
        renderer.lenses.forEach((lens)=>{
          try{ lens._revealProgress = opacity; }catch(e){}
        });
      }
      if(renderer.render) renderer.render(currentVisualizerFrameState());
      if(renderer.canvas) renderer.canvas.style.opacity = String(opacity);
    }catch(e){}
  }

  function animateNpOverlayGlassTransition(reason, durationMs){
    try{
      const renderer = liquidGlassRendererByKey("npOverlay");
      if(!renderer) return;
      const dur = Math.max(80, Number(durationMs || 240));
      const token = ((animateNpOverlayGlassTransition._token || 0) + 1);
      animateNpOverlayGlassTransition._token = token;
      const started = performance.now();
      let didRefresh = false;
      const tick = ()=>{
        try{
          if(animateNpOverlayGlassTransition._token !== token) return;
          const elapsed = performance.now() - started;
          forceNpOverlayGlassRender(reason || "np overlay transition", !didRefresh);
          didRefresh = true;
          if(elapsed < dur){
            requestAnimationFrame(tick);
          }else{
            forceNpOverlayGlassRender((reason || "np overlay transition") + " end", false);
            try{
              if(npOverlayPill && npOverlayPill.classList.contains("npPillHidden") && renderer.setVisible){
                renderer.setVisible(false);
              }
            }catch(e){}
          }
        }catch(e){}
      };
      requestAnimationFrame(tick);
    }catch(e){}
  }

  function renderLiquidGlassNow(frameState){
    try{
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.render) return;
        if((renderer.rendererKey || "") === "npOverlay") applyNpOverlayGlassTuning(renderer);
        renderer.render(frameState || currentVisualizerFrameState());
      });
    }catch(e){}
  }

  function renderLiquidGlassVisualizerSourceNow(frameState){
    try{
      ["default", "wheel", "screenFrame"].forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(renderer && renderer.render) renderer.render(frameState || currentVisualizerFrameState());
      });
      if(isPathPillVisible()) forcePathPillGlassRender("visualizer frame", false);
    }catch(e){}
  }

  function captureLiquidGlassSnapshot(reason, includeScreenFrame){
    try{
      refreshLiquidGlassVisualizerSources(reason || "app");
      refreshNpOverlayGlassSource(reason || "app");
      if(includeScreenFrame) refreshLiquidGlassSource(liquidGlassRendererByKey("screenFrame"), reason || "app");
      renderLiquidGlassNow();
    }catch(e){}
  }

  function scheduleLiquidGlassSnapshot(reason, includeScreenFrame){
    try{ requestAnimationFrame(()=> captureLiquidGlassSnapshot(reason, includeScreenFrame)); }catch(e){}
  }

  function debugLiquidGlassRenderers(reason){
    try{
      const enabled = window.DEBRIPOD_UI_DEBUG === true || (localStorage.getItem("debripod_ui_debug") || "") === "1";
      if(!enabled || !console || !console.log) return;
      liquidGlassRenderers().forEach((renderer)=>{
        const lenses = (renderer.lenses || []).map((lens)=> lens && lens.el ? {
          className: lens.el.className,
          id: lens.el.id || "",
          hollow: !!lens.hollowMaskContent
        } : null).filter(Boolean);
        console.log("[DebriPod LiquidGL]", reason || "state", {
          rendererKey: renderer.rendererKey || "unknown",
          texture: String(renderer.textureWidth || 0) + "x" + String(renderer.textureHeight || 0),
          lensCount: renderer.lenses ? renderer.lenses.length : 0,
          lenses: lenses,
          canvasClassName: renderer.canvas ? renderer.canvas.className : "",
          canvasZIndex: renderer.canvas ? window.getComputedStyle(renderer.canvas).zIndex : ""
        });
      });
    }catch(e){}
  }

  function recaptureLiquidGlassElement(el){
    try{
      if(!el) return;
      if(el.tagName === "IMG"){
        refreshNpOverlayGlassSource("image " + (el.id || el.className || "load"));
        renderLiquidGlassNow();
        return;
      }
      renderLiquidGlassNow();
    }catch(e){}
  }

  function scheduleLiquidGlassRender(){
    try{ requestAnimationFrame(renderLiquidGlassNow); }catch(e){}
  }

  function scheduleNpOverlayGlassRender(){
    try{
      if(!npOverlayPill) return;
      requestAnimationFrame(()=>{
        forceNpOverlayGlassRender("np overlay scheduled", true);
      });
    }catch(e){}
  }

  function initLiquidGlass(){
    try{
      if(liquidGlassReady || typeof window.liquidGL !== "function") return;
      const base = liquidGlassPresetOptions();
      const sharedGlassOptions = Object.assign({}, base, {
        target: ".pathPillGlass.liquidGlass",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg",
        shadow: false
      });
      window.liquidGL(sharedGlassOptions);
      const wheelGlassInstances = asLiquidArray(window.liquidGL(Object.assign({}, base, {
        target: ".wheelGlassRing.liquidGlass, .wheelCenterGlass.liquidGlass",
        rendererKey: "wheel",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg",
        shadow: false
      })));
      liquidWheelLenses = wheelGlassInstances.filter(inst => inst && inst.el);
      window.liquidGL(Object.assign({}, base, {
        target: ".npOverlayGlass.liquidGlass",
        sourceType: "albumArtCanvasOrImage",
        sourceElement: "#npArt",
        rendererKey: "npOverlay",
        shadow: false
      }));
      window.liquidGL(Object.assign({}, base, {
        target: ".screenGlassFrame.liquidGlass",
        rendererKey: "screenFrame",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg",
        shadow: false,
        hollowMaskContent: true
      }));
      mountLiquidCanvas();
      refreshLiquidGlassVisualizerSources("init");
      refreshNpOverlayGlassSource("init");
      liquidGlassRenderers().forEach((renderer)=>{
        try{
          renderer.useExternalTicker = true;
          if(renderer._rafId){
            cancelAnimationFrame(renderer._rafId);
            renderer._rafId = null;
          }
        }catch(err){}
      });
      liquidGlassReady = true;
    }catch(e){
      liquidGlassReady = true;
      try{ document.documentElement.classList.add("liquidGlassFallback"); }catch(err){}
    }
  }

  function cacheWheelGlassTiltRect(){
    try{
      const lens = liquidWheelLenses[0];
      if(!lens || !lens.el) return null;
      liquidWheelLenses.forEach((item)=>{
        try{ if(item && item.updateMetrics) item.updateMetrics(); }catch(e){}
      });
      wheelGlassTiltRect = lens.rectPx || lens.el.getBoundingClientRect();
      positionWheelLiquidCanvas();
      return wheelGlassTiltRect;
    }catch(e){
      wheelGlassTiltRect = null;
      return null;
    }
  }

  function setWheelLensTilt(rotX, rotY){
    try{
      wheelGlassTiltX = Number.isFinite(rotX) ? rotX : 0;
      wheelGlassTiltY = Number.isFinite(rotY) ? rotY : 0;
      liquidWheelLenses.forEach((lens)=>{
        if(!lens) return;
        lens.tiltX = wheelGlassTiltX;
        lens.tiltY = wheelGlassTiltY;
      });
    }catch(e){}
  }

  function applyWheelTiltTransform(rotX, rotY){
    try{
      setWheelLensTilt(rotX, rotY);
      if(wheel){
        wheel.style.transition = "none";
        wheel.style.transform = "perspective(900px) rotateX(" + rotX.toFixed(3) + "deg) rotateY(" + rotY.toFixed(3) + "deg)";
      }
      renderWheelLiquidGlass();
    }catch(e){}
  }

  function wheelTiltEaseStep(){
    wheelTiltAnimFrame = 0;
    try{
      const dx = wheelTiltTargetX - wheelTiltRenderX;
      const dy = wheelTiltTargetY - wheelTiltRenderY;
      const dur = Math.max(1, Number(wheelTiltAnimUntil || 90));
      const factor = dur <= 16 ? 1 : Math.min(1, 16.7 / dur);
      wheelTiltRenderX += dx * factor;
      wheelTiltRenderY += dy * factor;
      if(Math.abs(dx) < 0.002 && Math.abs(dy) < 0.002){
        wheelTiltRenderX = wheelTiltTargetX;
        wheelTiltRenderY = wheelTiltTargetY;
      }
      applyWheelTiltTransform(wheelTiltRenderX, wheelTiltRenderY);
      if(wheelTiltRenderX !== wheelTiltTargetX || wheelTiltRenderY !== wheelTiltTargetY){
        wheelTiltAnimFrame = requestAnimationFrame(wheelTiltEaseStep);
      }else if(wheelTiltRenderX === 0 && wheelTiltRenderY === 0){
        try{ if(wheel) wheel.style.transform = ""; }catch(e){}
      }
    }catch(e){}
  }

  function setWheelTiltTarget(rotX, rotY, durationMs){
    try{
      wheelTiltTargetX = Number.isFinite(rotX) ? rotX : 0;
      wheelTiltTargetY = Number.isFinite(rotY) ? rotY : 0;
      wheelTiltAnimUntil = Math.max(0, Number(durationMs || 0));
      if(!wheelTiltAnimFrame) wheelTiltAnimFrame = requestAnimationFrame(wheelTiltEaseStep);
    }catch(e){}
  }

  function renderWheelLiquidGlass(frameState){
    try{
      const renderer = liquidWheelRenderer();
      if(renderer && renderer.render) renderer.render(frameState || currentVisualizerFrameState());
    }catch(e){}
  }

  function updateWheelGlassTilt(clientX, clientY){
    try{
      if(wheelGlassResetFrame){
        cancelAnimationFrame(wheelGlassResetFrame);
        wheelGlassResetFrame = 0;
      }
      const lens = liquidWheelLenses[0] || null;
      const rect = wheelGlassTiltRect || (lens && lens.rectPx) || cacheWheelGlassTiltRect() || (wheel ? wheel.getBoundingClientRect() : null);
      if(!rect.width || !rect.height) return;
      const pctX = Math.max(-1, Math.min(1, (clientX - (rect.left + rect.width / 2)) / (rect.width / 2)));
      const pctY = Math.max(-1, Math.min(1, (clientY - (rect.top + rect.height / 2)) / (rect.height / 2)));
      const maxTilt = normalizeWheelRotationMaxDegrees(wheelRotationMaxDegrees);
      const rotY = pctX * maxTilt;
      const rotX = -pctY * maxTilt;
      setWheelTiltTarget(rotX, rotY, clampNumber(uiSettings.wheelTiltRampDuration, DEFAULT_UI_SETTINGS.wheelTiltRampDuration, 0, 1000));
    }catch(e){}
  }

  function applyWheelGlassTilt(ev){
    try{
      if(!ev) return;
      if(wheelGlassResetTimer){
        clearTimeout(wheelGlassResetTimer);
        wheelGlassResetTimer = null;
      }
      wheelGlassTiltPoint = {x: ev.clientX, y: ev.clientY};
      if(wheelGlassTiltFrame) return;
      wheelGlassTiltFrame = requestAnimationFrame(()=>{
        wheelGlassTiltFrame = 0;
        const pt = wheelGlassTiltPoint;
        if(!pt) return;
        updateWheelGlassTilt(pt.x, pt.y);
      });
    }catch(e){}
  }

  function resetWheelGlassTilt(){
    try{
      if(wheelGlassTiltFrame){
        cancelAnimationFrame(wheelGlassTiltFrame);
        wheelGlassTiltFrame = 0;
      }
      wheelGlassTiltPoint = null;
      wheelGlassTiltRect = null;
      if(wheelGlassResetFrame){
        cancelAnimationFrame(wheelGlassResetFrame);
        wheelGlassResetFrame = 0;
      }
      setWheelTiltTarget(0, 0, clampNumber(uiSettings.wheelTiltReleaseDuration, DEFAULT_UI_SETTINGS.wheelTiltReleaseDuration, 0, 1200));
      if(wheelGlassResetTimer) clearTimeout(wheelGlassResetTimer);
      wheelGlassResetTimer = setTimeout(()=>{
        wheelGlassResetTimer = null;
        try{ if(wheel) wheel.style.transform = ""; }catch(e){}
      }, clampNumber(uiSettings.wheelTiltReleaseDuration, DEFAULT_UI_SETTINGS.wheelTiltReleaseDuration, 0, 1200) + 40);
    }catch(e){}
  }
