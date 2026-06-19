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

  function glassElementSettings(key){
    try{
      liquidGlassElements = cloneGlassElementSettings(uiSettings.liquidGlassElements);
      return liquidGlassElements[key] || liquidGlassElements.libraryList;
    }catch(e){
      return cloneGlassElementSettings(DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS)[key] || DEFAULT_LIQUID_GLASS_ELEMENT_SETTINGS.libraryList;
    }
  }

  function liquidGlassElementOptions(key){
    const settings = glassElementSettings(key);
    const tint = normalizeLiquidGlassTint(settings.glassTint, liquidGlassModeToTint(settings.mode));
    const mode = liquidGlassTintMode(tint);
    const appleDarkAmount = 0.34;
    const appleLightAmount = 0.28;
    return Object.assign({
      snapshot: "#divwrap",
      resolution: settings.resolution,
      reveal: "none",
      tilt: false,
      magnify: settings.magnify,
      shadow: !!settings.shadow,
      glassMode: mode,
      glassDarkAmount: mode === "dark" ? (1 - tint) * appleDarkAmount : 0,
      glassLightAmount: mode === "light" ? (tint - 1) * appleLightAmount : 0
    }, settings, {
      glassMode: mode,
      glassTint: tint,
      glassDarkAmount: mode === "dark" ? (1 - tint) * appleDarkAmount : 0,
      glassLightAmount: mode === "light" ? (tint - 1) * appleLightAmount : 0
    });
  }

  function applyGlassModeClass(el, modeName){
    try{
      if(!el) return;
      const mode = typeof modeName === "number" ? liquidGlassTintMode(modeName) : normalizeLiquidGlassMode(modeName);
      el.classList.toggle("dpGlassModeClear", mode === "clear");
      el.classList.toggle("dpGlassModeLight", mode === "light");
      el.classList.toggle("dpGlassModeDark", mode === "dark");
      el.setAttribute("data-liquid-glass-mode", mode);
    }catch(e){}
  }

  function applyElementGlassModeClasses(){
    try{
      const all = cloneGlassElementSettings(uiSettings.liquidGlassElements);
      applyLiquidGlassModeClass(all.libraryList.glassTint);
      applyGlassModeClass(document.getElementById("libList"), all.libraryList.glassTint);
      applyGlassModeClass(document.getElementById("wheel"), all.wheel.glassTint);
      applyGlassModeClass(document.getElementById("libHeader"), all.pathPill.glassTint);
      applyGlassModeClass(document.getElementById("npOverlayPill"), all.nowPlayingPill.glassTint);
      document.querySelectorAll(".ipodPill[data-liquid-row-pill]").forEach((el)=> applyGlassModeClass(el, all.listPills.glassTint));
    }catch(e){}
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

  function frameScheduler(){
    try{ return root && root.frameScheduler ? root.frameScheduler : null; }catch(e){ return null; }
  }

  function markFrameWork(flags){
    try{
      const scheduler = frameScheduler();
      if(scheduler && scheduler.mark) scheduler.mark(flags || {render:true});
      else requestAnimationFrame(()=> renderLiquidGlassNow());
    }catch(e){}
  }

  function rendererTargetVisible(renderer){
    try{
      if(!renderer || !renderer.lenses || !renderer.lenses.length || document.hidden) return false;
      return renderer.lenses.some((lens)=>{
        if(!lens || !lens.el || !lens.el.isConnected) return false;
        const style = window.getComputedStyle ? window.getComputedStyle(lens.el) : null;
        if(style && (style.display === "none" || style.visibility === "hidden")) return false;
        let node = lens.el.parentElement;
        while(node && node !== document.body){
          const parentStyle = window.getComputedStyle ? window.getComputedStyle(node) : null;
          if(parentStyle && (parentStyle.display === "none" || parentStyle.visibility === "hidden" || Number(parentStyle.opacity || 1) <= 0.01)) return false;
          if(node.classList && (node.classList.contains("npPillHidden") || node.classList.contains("npPillSwapHidden"))) return false;
          node = node.parentElement;
        }
        const rect = lens.el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.right > -2 && rect.bottom > -2 && rect.left < (window.innerWidth || 0) + 2 && rect.top < (window.innerHeight || 0) + 2;
      });
    }catch(e){
      return true;
    }
  }

  function liquidWheelRenderer(){
    return liquidGlassRendererByKey("wheel");
  }

  function applyLiquidGlassModeClass(modeName){
    try{
      const mode = typeof modeName === "number" ? liquidGlassTintMode(modeName) : normalizeLiquidGlassMode(modeName || (glassElementSettings("libraryList").mode));
      const root = document.documentElement;
      root.classList.remove("dpGlassModeClear", "dpGlassModeLight", "dpGlassModeDark");
      root.setAttribute("data-liquid-glass-mode", mode);
    }catch(e){}
  }

  function applyLiquidGlassStyleOptions(){
    try{
      const byRenderer = {
        "default": liquidGlassElementOptions("pathPill"),
        "wheel": liquidGlassElementOptions("wheel"),
        "npOverlay": liquidGlassElementOptions("nowPlayingPill"),
        "libList": liquidGlassElementOptions("libraryList"),
        "libSelection": liquidGlassElementOptions("selectedRow"),
        "libPills": liquidGlassElementOptions("listPills")
      };
      applyElementGlassModeClasses();
      updateLibSelectionGlass("style options");
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.lenses) return;
        const opts = byRenderer[renderer.rendererKey || "default"] || byRenderer.default;
        renderer.lenses.forEach((lens)=>{
          if(!lens || !lens.options) return;
          ["refraction", "bevelDepth", "bevelWidth", "frost", "specular", "magnify", "glassDarkAmount", "glassLightAmount"].forEach((key)=>{
            if(opts[key] !== undefined) lens.options[key] = opts[key];
          });
          if(opts.refractionFill !== undefined) lens.options.refractionFill = opts.refractionFill;
          if(opts.shadow !== undefined && lens.options.shadow !== opts.shadow && typeof lens.setShadow === "function") lens.setShadow(!!opts.shadow);
          else if(opts.shadow !== undefined) lens.options.shadow = !!opts.shadow;
          lens.options.glassMode = normalizeLiquidGlassMode(opts.glassMode);
          if(lens._glassModeIndex) lens.glassModeIndex = lens._glassModeIndex(lens.options.glassMode);
        });
        if(renderer.render) renderer.render(currentVisualizerFrameState());
      });
    }catch(e){}
  }

  function setLiquidGlassElementSetting(elementKey, field, value){
    const current = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    if(!current[elementKey]) return;
    if(field === "mode"){
      current[elementKey].mode = normalizeLiquidGlassMode(value);
      current[elementKey].glassTint = liquidGlassModeToTint(current[elementKey].mode);
    }
    else if(field === "glassTint"){
      current[elementKey].glassTint = normalizeLiquidGlassTint(value, current[elementKey].glassTint);
      current[elementKey].mode = liquidGlassTintMode(current[elementKey].glassTint);
    }
    else if(field === "specular") current[elementKey].specular = !!value;
    else if(field === "shadow") current[elementKey].shadow = !!value;
    else current[elementKey][field] = clampNumber(Number(value), current[elementKey][field], field === "resolution" ? 0.25 : (field === "magnify" ? 0.001 : 0), field === "resolution" ? 3 : (field === "magnify" ? 3 : (field === "frost" ? 5 : (field === "bevelWidth" ? 0.5 : (field === "bevelDepth" ? 0.35 : (field === "refractionFill" ? 1 : 0.25))))));
    uiSettings.liquidGlassElements = cloneGlassElementSettings(current);
    liquidGlassElements = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    saveUiSettings();
    applyLiquidGlassStyleOptions();
    scheduleLiquidGlassSnapshot("glass element setting", true);
  }

  applyElementGlassModeClasses();

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
        renderer.canvas.classList.toggle("liquidGlassCanvasLibList", key === "libList");
        renderer.canvas.classList.toggle("liquidGlassCanvasLibSelection", key === "libSelection");
        renderer.canvas.classList.toggle("liquidGlassCanvasLibPills", key === "libPills");
        renderer.canvas.setAttribute("data-liquid-renderer", key || "unknown");
        if(key === "wheel"){
          const wheelHost = document.getElementById("wheel") || document.querySelector(".ipodWheelWrap");
          if(wheelHost && renderer.canvas.parentNode !== wheelHost){
            wheelHost.insertBefore(renderer.canvas, wheelHost.firstChild);
          }
          positionWheelLiquidCanvas();
        }else if(key === "libList"){
          const screenHost = document.getElementById("ipodScreen");
          if(screenHost && renderer.canvas.parentNode !== screenHost){
            screenHost.insertBefore(renderer.canvas, screenHost.firstChild);
          }
          positionLibListLiquidCanvas();
        }else if(key === "libPills"){
          const screenHost = document.getElementById("ipodScreen");
          if(screenHost && renderer.canvas.parentNode !== screenHost){
            screenHost.insertBefore(renderer.canvas, screenHost.firstChild);
          }
          positionLibPillsLiquidCanvas();
        }else if(key === "libSelection"){
          const screenHost = document.getElementById("ipodScreen");
          if(screenHost && renderer.canvas.parentNode !== screenHost){
            screenHost.insertBefore(renderer.canvas, screenHost.firstChild);
          }
          positionLibSelectionLiquidCanvas();
        }else if(key === "npOverlay"){
          const pillHost = document.getElementById("npOverlayPill");
          if(pillHost && renderer.canvas.parentNode !== pillHost){
            pillHost.insertBefore(renderer.canvas, pillHost.firstChild);
          }
          positionNpOverlayLiquidCanvas();
        }else if(renderer.canvas.parentNode !== wrap){
          const afterBg = document.getElementById("visualizerBg");
          if(afterBg && afterBg.parentNode === wrap && afterBg.nextSibling){
            wrap.insertBefore(renderer.canvas, afterBg.nextSibling);
          }else{
            wrap.insertBefore(renderer.canvas, wrap.firstChild);
          }
        }
        renderer.canvas.style.pointerEvents = "none";
        renderer.canvas.style.setProperty("z-index", (key === "libPills" || key === "libSelection") ? "2" : (key === "libList" ? "1" : (key === "npOverlay" ? "1" : (key === "wheel" ? "10" : "65"))), "important");
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
      canvas.style.setProperty("left", (-(rect.left || 0)).toFixed(3) + "px", "important");
      canvas.style.setProperty("top", (-(rect.top || 0)).toFixed(3) + "px", "important");
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
      ["default", "wheel", "libList", "libSelection", "libPills"].forEach((key)=>{
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
      const sourceImg = document.getElementById("npArtLiquidSource");
      if(sourceImg && sourceImg.complete && sourceImg.naturalWidth && sourceImg.naturalHeight){
        if(renderer.updateTextureFromImage){
          renderer.updateTextureFromImage(sourceImg, {reason: reason || "album art image"});
        }else{
          refreshLiquidGlassSource(renderer, reason || "album art image");
        }
        return;
      }
      const liveArtCanvas = root.albumArtTexture && root.albumArtTexture.renderToCanvas ? root.albumArtTexture.renderToCanvas(npArt) : null;
      if(liveArtCanvas && renderer.updateTextureFromCanvas){
        const artEl = npArt;
        const rect = artEl ? artEl.getBoundingClientRect() : {left:0, top:0, width:liveArtCanvas.width || 1, height:liveArtCanvas.height || 1};
        renderer.updateTextureFromCanvas(liveArtCanvas, {
          reason: reason || "album art canvas texture",
          allowDark: true,
          sourceRect: {left: rect.left || 0, top: rect.top || 0, width: rect.width || liveArtCanvas.width || 1, height: rect.height || liveArtCanvas.height || 1}
        });
        return;
      }
      if(renderer.texture || renderer._sourceTextureReady){
        if(renderer._sourceIsSolidFallback && renderer.clearSourceTexture){
          renderer.clearSourceTexture(reason || "album art source unavailable");
        }
        return;
      }else{
        return;
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
      positionNpOverlayLiquidCanvas();
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
      debugLiquidGlassRenderers(reason || "np overlay render");
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
      const tick = ()=>{
        try{
          if(animateNpOverlayGlassTransition._token !== token) return;
          const elapsed = performance.now() - started;
          forceNpOverlayGlassRender(reason || "np overlay transition", true);
          if(elapsed < dur){
            const scheduler = frameScheduler();
            if(scheduler && scheduler.request){
              scheduler.request("np-overlay-transition", tick);
              scheduler.mark({refreshSources:true, metrics:true, render:true, keepAlive:true});
            }else{
              requestAnimationFrame(tick);
            }
          }else{
            forceNpOverlayGlassRender((reason || "np overlay transition") + " end", true);
            try{
              if(npOverlayPill && npOverlayPill.classList.contains("npPillHidden") && renderer.setVisible){
                renderer.setVisible(false);
              }
            }catch(e){}
          }
        }catch(e){}
      };
      const scheduler = frameScheduler();
      if(scheduler && scheduler.request){
        scheduler.request("np-overlay-transition", tick);
        scheduler.mark({refreshSources:true, metrics:true, render:true, keepAlive:true});
      }else{
        requestAnimationFrame(tick);
      }
    }catch(e){}
  }

  function cssPointValue(style, name, axisSize, fallback){
    try{
      const raw = String(style.getPropertyValue(name) || "").trim();
      if(!raw) return fallback;
      if(raw.slice(-1) === "%") return (parseFloat(raw) || 0) / 100 * axisSize;
      return parseFloat(raw) || fallback;
    }catch(e){
      return fallback;
    }
  }

  function updateGlassTextUnderColors(){
    try{
      const root = document.documentElement;
      const style = window.getComputedStyle ? window.getComputedStyle(root) : null;
      if(!style) return;
      const width = window.innerWidth || 1;
      const height = window.innerHeight || 1;
      const colors = [
        {color: String(style.getPropertyValue("--theme-visualizer-a") || "rgba(10,132,255,.42)").trim(), x: cssPointValue(style, "--viz-x1", width, width * 0.5), y: cssPointValue(style, "--viz-y1", height, height * 0.28)},
        {color: String(style.getPropertyValue("--theme-visualizer-b") || "rgba(94,92,230,.30)").trim(), x: cssPointValue(style, "--viz-x2", width, width * 0.22), y: cssPointValue(style, "--viz-y2", height, height * 0.68)},
        {color: String(style.getPropertyValue("--theme-visualizer-c") || "rgba(255,69,58,.18)").trim(), x: cssPointValue(style, "--viz-x3", width, width * 0.78), y: cssPointValue(style, "--viz-y3", height, height * 0.64)}
      ];
      document.querySelectorAll(".glassText, .glassGlyph").forEach((el)=>{
        try{
          const rect = el.getBoundingClientRect();
          if(!rect.width || !rect.height || rect.bottom < 0 || rect.right < 0 || rect.left > width || rect.top > height) return;
          const cx = rect.left + rect.width / 2;
          const cy = rect.top + rect.height / 2;
          const ranked = colors.slice().sort((a, b)=>{
            const da = Math.hypot(cx - a.x, cy - a.y);
            const db = Math.hypot(cx - b.x, cy - b.y);
            return da - db;
          });
          el.style.setProperty("--dp-engrave-under-a", ranked[0].color);
          el.style.setProperty("--dp-engrave-under-b", ranked[1].color);
          el.style.setProperty("--dp-engrave-under-c", ranked[2].color);
        }catch(e){}
      });
    }catch(e){}
  }

  function renderLiquidGlassNow(frameState){
    try{
      updateGlassTextUnderColors();
      updateLibSelectionGlass("");
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.render) return;
        if(!rendererTargetVisible(renderer)){
          if(renderer.setVisible) renderer.setVisible(false);
          return;
        }
        if(renderer.setVisible) renderer.setVisible(true);
        const key = renderer.rendererKey || "";
        if(key === "npOverlay"){
          positionNpOverlayLiquidCanvas();
          applyNpOverlayGlassTuning(renderer);
        }
        if(key === "libList") positionLibListLiquidCanvas();
        if(key === "libSelection") positionLibSelectionLiquidCanvas();
        if(key === "libPills") positionLibPillsLiquidCanvas();
        renderer.render(frameState || currentVisualizerFrameState());
      });
    }catch(e){}
  }

  function renderLiquidGlassVisualizerSourceNow(frameState){
    try{
      updateGlassTextUnderColors();
      ["default", "wheel", "libList", "libSelection", "libPills"].forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(key === "libList") positionLibListLiquidCanvas();
        if(key === "libSelection") positionLibSelectionLiquidCanvas();
        if(key === "libPills") positionLibPillsLiquidCanvas();
        if(renderer && renderer.render && rendererTargetVisible(renderer)) renderer.render(frameState || currentVisualizerFrameState());
      });
      if(isPathPillVisible()) forcePathPillGlassRender("visualizer frame", false);
    }catch(e){}
  }

  function captureLiquidGlassSnapshot(reason, includeLibList){
    try{
      refreshLiquidGlassVisualizerSources(reason || "app");
      refreshNpOverlayGlassSource(reason || "app");
      if(includeLibList) refreshLiquidGlassSource(liquidGlassRendererByKey("libList"), reason || "app");
      renderLiquidGlassNow();
    }catch(e){}
  }

  function positionViewportCanvasInsideHost(renderer, host, zIndex){
    try{
      const canvas = renderer && renderer.canvas;
      if(!canvas || !host) return;
      const rect = host.getBoundingClientRect();
      canvas.style.position = "absolute";
      canvas.style.setProperty("position", "absolute", "important");
      canvas.style.setProperty("inset", "auto", "important");
      canvas.style.setProperty("left", (-(rect.left || 0)) + "px", "important");
      canvas.style.setProperty("top", (-(rect.top || 0)) + "px", "important");
      canvas.style.right = "auto";
      canvas.style.bottom = "auto";
      canvas.style.setProperty("width", (window.innerWidth || canvas.width || 1) + "px", "important");
      canvas.style.setProperty("height", (window.innerHeight || canvas.height || 1) + "px", "important");
      canvas.style.setProperty("pointer-events", "none", "important");
      canvas.style.setProperty("z-index", String(zIndex || 1), "important");
    }catch(e){}
  }

  function positionLibListLiquidCanvas(){
    positionViewportCanvasInsideHost(liquidGlassRendererByKey("libList"), document.getElementById("ipodScreen"), 1);
  }

  function positionLibPillsLiquidCanvas(){
    positionViewportCanvasInsideHost(liquidGlassRendererByKey("libPills"), document.getElementById("ipodScreen"), 2);
  }

  function positionLibSelectionLiquidCanvas(){
    positionViewportCanvasInsideHost(liquidGlassRendererByKey("libSelection"), document.getElementById("ipodScreen"), 2);
  }

  function selectedListInnerRect(){
    try{
      const list = document.getElementById("libList");
      if(!list) return null;
      const rect = list.getBoundingClientRect();
      const cs = window.getComputedStyle ? window.getComputedStyle(list) : null;
      const left = cs ? (parseFloat(cs.paddingLeft || "0") || 0) : 0;
      const right = cs ? (parseFloat(cs.paddingRight || "0") || 0) : left;
      const top = cs ? (parseFloat(cs.paddingTop || "0") || 0) : left;
      const bottom = cs ? (parseFloat(cs.paddingBottom || "0") || 0) : top;
      return {
        left: rect.left + left,
        top: rect.top + top,
        right: rect.right - right,
        bottom: rect.bottom - bottom
      };
    }catch(e){
      return null;
    }
  }

  var listSelectionMotion = {
    currentX: 0,
    currentY: 0,
    currentWidth: 0,
    currentHeight: 44,
    currentRadius: 999,
    currentOpacity: 0,
    targetX: 0,
    targetY: 0,
    targetWidth: 0,
    targetHeight: 44,
    targetRadius: 999,
    targetOpacity: 0,
    stretch: 0,
    direction: 0,
    raf: 0,
    initialized: false
  };

  function applyLibSelectionMotion(){
    try{
      const el = document.getElementById("libListSelectedGlass");
      if(!el) return;
      const stretchPx = Math.abs(listSelectionMotion.stretch || 0) * Math.min(18, Math.max(8, listSelectionMotion.currentHeight * 0.24));
      const direction = listSelectionMotion.direction || 0;
      const renderY = listSelectionMotion.currentY + (direction < 0 ? -stretchPx : 0);
      const renderHeight = Math.max(0, listSelectionMotion.currentHeight + stretchPx);
      el.style.transform = "translate3d(" + listSelectionMotion.currentX.toFixed(3) + "px," + renderY.toFixed(3) + "px,0)";
      el.style.width = Math.max(0, listSelectionMotion.currentWidth).toFixed(3) + "px";
      el.style.height = renderHeight.toFixed(3) + "px";
      el.style.borderRadius = Math.max(0, listSelectionMotion.currentRadius).toFixed(3) + "px";
      el.style.opacity = listSelectionMotion.currentOpacity.toFixed(3);
      el.classList.toggle("isVisible", listSelectionMotion.currentOpacity > 0.01);
      document.documentElement.style.setProperty("--dp-selected-x", listSelectionMotion.currentX.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-y", listSelectionMotion.currentY.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-w", Math.max(0, listSelectionMotion.currentWidth).toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-h", renderHeight.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-radius", Math.max(0, listSelectionMotion.currentRadius).toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-stretch", String(listSelectionMotion.stretch || 0));
      document.documentElement.style.setProperty("--dp-selected-opacity", listSelectionMotion.currentOpacity.toFixed(3));
      const renderer = liquidGlassRendererByKey("libSelection");
      if(renderer){
        renderer._metricsDirty = true;
        renderer._snapshotRectPx = null;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
        if(renderer.render) renderer.render(currentVisualizerFrameState());
      }
    }catch(e){}
  }

  function stepLibSelectionMotion(){
    listSelectionMotion.raf = 0;
    try{
      const stiffness = 0.34;
      listSelectionMotion.currentX += (listSelectionMotion.targetX - listSelectionMotion.currentX) * stiffness;
      listSelectionMotion.currentY += (listSelectionMotion.targetY - listSelectionMotion.currentY) * stiffness;
      listSelectionMotion.currentWidth += (listSelectionMotion.targetWidth - listSelectionMotion.currentWidth) * stiffness;
      listSelectionMotion.currentHeight += (listSelectionMotion.targetHeight - listSelectionMotion.currentHeight) * stiffness;
      listSelectionMotion.currentRadius += (listSelectionMotion.targetRadius - listSelectionMotion.currentRadius) * stiffness;
      listSelectionMotion.currentOpacity += (listSelectionMotion.targetOpacity - listSelectionMotion.currentOpacity) * 0.42;
      const done = (
        Math.abs(listSelectionMotion.targetX - listSelectionMotion.currentX) < 0.08 &&
        Math.abs(listSelectionMotion.targetY - listSelectionMotion.currentY) < 0.08 &&
        Math.abs(listSelectionMotion.targetWidth - listSelectionMotion.currentWidth) < 0.08 &&
        Math.abs(listSelectionMotion.targetHeight - listSelectionMotion.currentHeight) < 0.08 &&
        Math.abs(listSelectionMotion.targetRadius - listSelectionMotion.currentRadius) < 0.08 &&
        Math.abs(listSelectionMotion.targetOpacity - listSelectionMotion.currentOpacity) < 0.01
      );
      if(done){
        listSelectionMotion.currentX = listSelectionMotion.targetX;
        listSelectionMotion.currentY = listSelectionMotion.targetY;
        listSelectionMotion.currentWidth = listSelectionMotion.targetWidth;
        listSelectionMotion.currentHeight = listSelectionMotion.targetHeight;
        listSelectionMotion.currentRadius = listSelectionMotion.targetRadius;
        listSelectionMotion.currentOpacity = listSelectionMotion.targetOpacity;
      }
      applyLibSelectionMotion();
      if(!done){
        const scheduler = frameScheduler();
        if(scheduler && scheduler.request){
          listSelectionMotion.raf = -1;
          scheduler.request("lib-selection-motion", stepLibSelectionMotion);
          scheduler.mark({metrics:true, render:true, keepAlive:true});
        }else{
          listSelectionMotion.raf = requestAnimationFrame(stepLibSelectionMotion);
        }
      }
    }catch(e){}
  }

  function scheduleLibSelectionMotion(){
    try{
      if(listSelectionMotion.raf) return;
      const scheduler = frameScheduler();
      if(scheduler && scheduler.request){
        listSelectionMotion.raf = -1;
        scheduler.request("lib-selection-motion", stepLibSelectionMotion);
        scheduler.mark({metrics:true, render:true, keepAlive:true});
      }else{
        listSelectionMotion.raf = requestAnimationFrame(stepLibSelectionMotion);
      }
    }catch(e){}
  }

  function setLibSelectionTarget(x, y, width, height, radius, opacity){
    try{
      listSelectionMotion.targetX = x;
      listSelectionMotion.targetY = y;
      listSelectionMotion.targetWidth = width;
      listSelectionMotion.targetHeight = height;
      listSelectionMotion.targetRadius = radius;
      listSelectionMotion.targetOpacity = opacity;
      if(!listSelectionMotion.initialized){
        listSelectionMotion.currentX = x;
        listSelectionMotion.currentY = y;
        listSelectionMotion.currentWidth = width;
        listSelectionMotion.currentHeight = height;
        listSelectionMotion.currentRadius = radius;
        listSelectionMotion.currentOpacity = opacity;
        listSelectionMotion.initialized = true;
        applyLibSelectionMotion();
        return;
      }
      scheduleLibSelectionMotion();
    }catch(e){}
  }

  function setLibSelectionStretch(progress){
    try{
      const n = Number(progress || 0);
      const clamped = Math.max(-1, Math.min(1, Number.isFinite(n) ? n : 0));
      listSelectionMotion.stretch = Math.abs(clamped);
      listSelectionMotion.direction = clamped === 0 ? 0 : (clamped > 0 ? 1 : -1);
      applyLibSelectionMotion();
    }catch(e){}
  }

  function updateLibSelectionGlass(reason){
    try{
      const el = document.getElementById("libListSelectedGlass");
      const list = document.getElementById("libList");
      if(!el || !list) return;
      const settings = glassElementSettings("selectedRow");
      applyGlassModeClass(el, settings.glassTint);
      const row = list.querySelector(".ipodItem.sel");
      const inner = selectedListInnerRect();
      if(!row || !inner){
        setLibSelectionTarget(listSelectionMotion.targetX, listSelectionMotion.targetY, listSelectionMotion.targetWidth, listSelectionMotion.targetHeight, listSelectionMotion.targetRadius, 0);
        return;
      }
      const rowRect = row.getBoundingClientRect();
      const left = Math.max(rowRect.left, inner.left);
      const right = Math.min(rowRect.right, inner.right);
      const top = Math.max(rowRect.top, inner.top);
      const bottom = Math.min(rowRect.bottom, inner.bottom);
      if(right <= left || bottom <= top){
        setLibSelectionTarget(listSelectionMotion.targetX, listSelectionMotion.targetY, listSelectionMotion.targetWidth, listSelectionMotion.targetHeight, listSelectionMotion.targetRadius, 0);
        return;
      }
      const host = document.getElementById("ipodScreen");
      const hostRect = host ? host.getBoundingClientRect() : {left:0, top:0};
      const targetHeight = bottom - top;
      const radius = targetHeight > 58 ? 16 : 999;
      setLibSelectionTarget(left - hostRect.left, top - hostRect.top, right - left, targetHeight, radius, 1);
      const renderer = liquidGlassRendererByKey("libSelection");
      if(renderer){
        renderer._metricsDirty = true;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
      }
      if(reason && renderer && renderer.render) renderer.render(currentVisualizerFrameState());
    }catch(e){}
  }

  function invalidateLibPillGlass(reason){
    try{
      updateLibSelectionGlass(reason || "");
      const renderer = liquidGlassRendererByKey("libPills");
      if(renderer){
        renderer._metricsDirty = true;
        renderer._snapshotRectPx = null;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
      }
      markFrameWork({metrics:true, render:true, textContrast:true});
    }catch(e){}
  }

  function positionNpOverlayLiquidCanvas(){
    positionViewportCanvasInsideHost(liquidGlassRendererByKey("npOverlay"), document.getElementById("npOverlayPill"), 1);
  }

  function refreshLibPillGlassLenses(reason){
    try{
      if(typeof window.liquidGL !== "function") return;
      window.liquidGL(Object.assign({}, liquidGlassElementOptions("selectedRow"), {
        target: ".ipodPill.liquidGlass[data-liquid-row-pill]",
        rendererKey: "libPills",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg",
        clipTarget: "#libList",
        clipToPaddingBox: true,
        syncTargets: true
      }));
      applyElementGlassModeClasses();
      mountLiquidCanvas();
      refreshLiquidGlassVisualizerSources(reason || "lib pills");
      invalidateLibPillGlass(reason || "lib pills");
    }catch(e){}
  }

  function scheduleLiquidGlassSnapshot(reason, includeLibList){
    try{
      const scheduler = frameScheduler();
      if(scheduler && scheduler.request){
        scheduler.request("liquid-snapshot", ()=> captureLiquidGlassSnapshot(reason, includeLibList));
        scheduler.mark({refreshSources:true, metrics:true, render:true, textContrast:true});
      }else{
        requestAnimationFrame(()=> captureLiquidGlassSnapshot(reason, includeLibList));
      }
    }catch(e){}
  }

  function debugLiquidGlassRenderers(reason){
    try{
      const enabled = window.DEBRIPOD_UI_DEBUG === true || (localStorage.getItem("debripod_ui_debug") || "") === "1";
      if(!enabled || !console || !console.log) return;
      liquidGlassRenderers().forEach((renderer)=>{
        const lenses = (renderer.lenses || []).map((lens)=> lens && lens.el ? {
          className: lens.el.className,
          id: lens.el.id || "",
          hollow: !!lens.hollowMaskContent,
          rectPx: lens.rectPx ? {
            left: Math.round(lens.rectPx.left),
            top: Math.round(lens.rectPx.top),
            width: Math.round(lens.rectPx.width),
            height: Math.round(lens.rectPx.height)
          } : null
        } : null).filter(Boolean);
        console.log("[DebriPod LiquidGL]", reason || "state", {
          rendererKey: renderer.rendererKey || "unknown",
          texture: String(renderer.textureWidth || 0) + "x" + String(renderer.textureHeight || 0),
          textureWidth: renderer.textureWidth || 0,
          textureHeight: renderer.textureHeight || 0,
          lensCount: renderer.lenses ? renderer.lenses.length : 0,
          lenses: lenses,
          canvasClassName: renderer.canvas ? renderer.canvas.className : "",
          canvasZIndex: renderer.canvas ? window.getComputedStyle(renderer.canvas).zIndex : "",
          canvasOpacity: renderer.canvas ? window.getComputedStyle(renderer.canvas).opacity : ""
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
    markFrameWork({metrics:true, render:true, textContrast:true});
  }

  function scheduleNpOverlayGlassRender(){
    try{
      if(!npOverlayPill) return;
      const scheduler = frameScheduler();
      if(scheduler && scheduler.request){
        scheduler.request("np-overlay", ()=> forceNpOverlayGlassRender("np overlay scheduled", true));
        scheduler.mark({refreshSources:true, metrics:true, render:true});
      }else{
        requestAnimationFrame(()=> forceNpOverlayGlassRender("np overlay scheduled", true));
      }
    }catch(e){}
  }

  function initLiquidGlass(){
    try{
      if(liquidGlassReady || typeof window.liquidGL !== "function") return;
      const sharedGlassOptions = Object.assign({}, liquidGlassElementOptions("pathPill"), {
        target: ".pathPillGlass.liquidGlass",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg"
      });
      window.liquidGL(sharedGlassOptions);
      const wheelGlassInstances = asLiquidArray(window.liquidGL(Object.assign({}, liquidGlassElementOptions("wheel"), {
        target: ".wheelGlassRing.liquidGlass, .wheelCenterGlass.liquidGlass",
        rendererKey: "wheel",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg"
      })));
      liquidWheelLenses = wheelGlassInstances.filter(inst => inst && inst.el);
      window.liquidGL(Object.assign({}, liquidGlassElementOptions("nowPlayingPill"), {
        target: ".npOverlayGlass.liquidGlass",
        sourceType: "albumArtCanvasOrImage",
        sourceElement: "#npArtLiquidSource",
        rendererKey: "npOverlay"
      }));
      window.liquidGL(Object.assign({}, liquidGlassElementOptions("libraryList"), {
        target: "#libList.liquidGlass",
        rendererKey: "libList",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg"
      }));
      window.liquidGL(Object.assign({}, liquidGlassElementOptions("listPills"), {
        target: "#libListSelectedGlass.liquidGlass",
        rendererKey: "libSelection",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg"
      }));
      window.liquidGL(Object.assign({}, liquidGlassElementOptions("listPills"), {
        target: ".ipodPill.liquidGlass[data-liquid-row-pill]",
        rendererKey: "libPills",
        sourceType: "visualizerCanvas",
        sourceElement: "#visualizerBg",
        clipTarget: "#libList",
        clipToPaddingBox: true,
        syncTargets: true
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
      try{
        const scheduler = frameScheduler();
        if(scheduler && scheduler.register){
          scheduler.register("liquid-glass", (frameState)=>{
            const flags = frameState && frameState.flags ? frameState.flags : {};
            if(flags.refreshSources) refreshLiquidGlassVisualizerSources("scheduler");
            if(flags.textContrast) updateGlassTextUnderColors();
            if(flags.metrics || flags.render || flags.refreshSources || flags.textContrast || flags.keepAlive){
              renderLiquidGlassNow(frameState);
            }
          });
        }
      }catch(err){}
      liquidGlassReady = true;
      markFrameWork({refreshSources:true, metrics:true, render:true, textContrast:true});
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
        const scheduler = frameScheduler();
        if(scheduler && scheduler.request){
          wheelTiltAnimFrame = -1;
          scheduler.request("wheel-tilt", wheelTiltEaseStep);
          scheduler.mark({metrics:true, render:true, keepAlive:true});
        }else{
          wheelTiltAnimFrame = requestAnimationFrame(wheelTiltEaseStep);
        }
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
      if(!wheelTiltAnimFrame){
        const scheduler = frameScheduler();
        if(scheduler && scheduler.request){
          wheelTiltAnimFrame = -1;
          scheduler.request("wheel-tilt", wheelTiltEaseStep);
          scheduler.mark({metrics:true, render:true, keepAlive:true});
        }else{
          wheelTiltAnimFrame = requestAnimationFrame(wheelTiltEaseStep);
        }
      }
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
