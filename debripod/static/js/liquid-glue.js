  var LIQUID_VISUALIZER_RENDERER_KEYS = ["main", "wheel"];
  var glassTextUnderColorState = {
    lastRun: 0,
    lastSignature: "",
    runCount: 0
  };

  function applyUiTuningCss(){
    try{
      const doc = document.documentElement;
      doc.style.setProperty("--centerBounceScale", String(1 + clampNumber(uiSettings.centerBounceAmount, DEFAULT_UI_SETTINGS.centerBounceAmount, 0, 0.3)));
      doc.style.setProperty("--centerBounceDuration", String(clampNumber(uiSettings.centerBounceDuration, DEFAULT_UI_SETTINGS.centerBounceDuration, 0, 1000)) + "ms");
      doc.style.setProperty("--centerBounceOvershoot", String(clampNumber(uiSettings.centerBounceOvershoot, DEFAULT_UI_SETTINGS.centerBounceOvershoot, 0, 1.4)));
      applyTextModeClasses();
      applyAnimationTimingCss();
    }catch(e){}
  }

  function textModeColor(mode, group){
    const alpha = normalizeTextTransparency(uiSettings.textTransparency);
    const key = normalizeTextMode(mode);
    if(key === "white" || group === "selectedRow" || group === "selectedRowPills") return "#ffffff";
    return "rgba(255,255,255," + alpha.toFixed(3) + ")";
  }

  function applyTextModeClasses(){
    try{
      uiSettings.textModes = cloneTextModes(uiSettings.textModes);
      uiSettings.textTransparency = normalizeTextTransparency(uiSettings.textTransparency);
      const modes = uiSettings.textModes;
      const doc = document.documentElement;
      doc.style.setProperty("--dp-text-wheel-labels", textModeColor(modes.wheelLabels, "wheelLabels"));
      doc.style.setProperty("--dp-text-path-pill", textModeColor(modes.pathPill, "pathPill"));
      doc.style.setProperty("--dp-text-info-pill", textModeColor(modes.infoPill, "infoPill"));
      doc.style.setProperty("--dp-text-rows", textModeColor(modes.rows, "rows"));
      doc.style.setProperty("--dp-text-row-pills", textModeColor(modes.rowPills, "rowPills"));
      doc.style.setProperty("--dp-text-selected-row", textModeColor(modes.selectedRow, "selectedRow"));
      doc.style.setProperty("--dp-text-selected-row-pills", textModeColor(modes.selectedRowPills, "selectedRowPills"));
      doc.style.setProperty("--dp-text-transparent-alpha", uiSettings.textTransparency.toFixed(3));
      Object.keys(modes).forEach((key)=> doc.setAttribute("data-text-mode-" + key.replace(/[A-Z]/g, m=> "-" + m.toLowerCase()), modes[key]));
    }catch(e){}
  }

  function animationFrameIntervalMs(key){
    try{
      uiSettings.animationFps = cloneAnimationFps(uiSettings.animationFps);
      return 1000 / normalizeAnimationFps(uiSettings.animationFps && uiSettings.animationFps[key]);
    }catch(e){
      return 1000 / 60;
    }
  }

  function applyAnimationTimingCss(){
    try{
      uiSettings.animationFps = cloneAnimationFps(uiSettings.animationFps);
      const doc = document.documentElement;
      Object.keys(uiSettings.animationFps).forEach((key)=>{
        doc.style.setProperty("--dp-" + key.replace(/[A-Z]/g, m=> "-" + m.toLowerCase()) + "-frame-ms", animationFrameIntervalMs(key).toFixed(3) + "ms");
      });
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
    return {
      snapshot: "#divwrap",
      resolution: 0.25,
      reveal: "none",
      tilt: false,
      liveGeometry: true,
      material: normalizeLiquidGlassMaterial(settings.material, 0)
    };
  }

  function applyGlassMaterialClass(el, material){
    try{
      if(!el) return;
      const value = normalizeLiquidGlassMaterial(material, 0);
      const side = value < -0.005 ? "dark" : (value > 0.005 ? "light" : "transparent");
      el.classList.toggle("dpGlassMaterialTransparent", side === "transparent");
      el.classList.toggle("dpGlassMaterialLight", side === "light");
      el.classList.toggle("dpGlassMaterialDark", side === "dark");
      el.setAttribute("data-liquid-glass-material", String(value));
    }catch(e){}
  }

  function applyElementGlassMaterialClasses(){
    try{
      const all = cloneGlassElementSettings(uiSettings.liquidGlassElements);
      applyRootGlassMaterialClass(all.libraryList.material);
      applyGlassMaterialClass(document.getElementById("libList"), all.libraryList.material);
      applyGlassMaterialClass(document.getElementById("wheel"), all.wheel.material);
      applyGlassMaterialClass(document.getElementById("libHeader"), all.pathPill.material);
      applyGlassMaterialClass(document.getElementById("infoPill"), all.infoPill.material);
      document.querySelectorAll(".ipodPill[data-liquid-row-pill]").forEach((el)=> applyGlassMaterialClass(el, all.listPills.material));
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
      const wanted = key || "main";
      const renderers = window.__liquidGLRenderers__;
      if(renderers && renderers[wanted]) return renderers[wanted];
      if(wanted === "main") return window.__liquidGLRenderer__ || (renderers && renderers.default) || null;
    }catch(e){}
    return null;
  }

  function frameScheduler(){
    try{ return window.DebriPod && window.DebriPod.frameScheduler ? window.DebriPod.frameScheduler : null; }catch(e){ return null; }
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
        if(style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) <= 0.01)) return false;
        let node = lens.el.parentElement;
        while(node && node !== document.body){
          const parentStyle = window.getComputedStyle ? window.getComputedStyle(node) : null;
          if(parentStyle && (parentStyle.display === "none" || parentStyle.visibility === "hidden" || Number(parentStyle.opacity || 1) <= 0.01)) return false;
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

  function applyRootGlassMaterialClass(material){
    try{
      applyGlassMaterialClass(document.documentElement, material);
    }catch(e){}
  }

  function liquidGlassLensElementKey(renderer, lens){
    const el = lens && lens.el;
    if(el && el.classList){
      if(el.classList.contains("infoPillGlass")) return "infoPill";
      if(el.classList.contains("pathPillGlass")) return "pathPill";
      if(el.classList.contains("ipodPill") && el.hasAttribute("data-liquid-row-pill")) return "listPills";
    }
    if(el && el.id === "libList") return "libraryList";
    if(el && el.id === "libListSelectedGlass") return "selectedRow";
    const rendererKey = renderer && renderer.rendererKey;
    if(rendererKey === "wheel") return "wheel";
    return "pathPill";
  }

  function applyLiquidGlassStyleOptions(){
    try{
      applyTextModeClasses();
      applyElementGlassMaterialClasses();
      updateLibSelectionGlass("style options");
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.lenses) return;
        renderer.lenses.forEach((lens)=>{
          if(!lens) return;
          const opts = liquidGlassElementOptions(liquidGlassLensElementKey(renderer, lens));
          if(typeof lens.setOptions === "function") lens.setOptions({material:opts.material});
          else if(lens.options) lens.options.material = opts.material;
        });
      });
      markFrameWork({render:true, textContrast:true});
    }catch(e){}
  }

  function previewLiquidGlassElementMaterial(elementKey, value){
    const material = normalizeLiquidGlassMaterial(value, 0);
    liquidGlassRenderers().forEach((renderer)=>{
      (renderer.lenses || []).forEach((lens)=>{
        if(liquidGlassLensElementKey(renderer, lens) !== elementKey) return;
        if(typeof lens.setOptions === "function") lens.setOptions({material:material});
      });
    });
    const targets = {
      libraryList:[document.getElementById("libList")],
      wheel:[document.getElementById("wheel")],
      pathPill:[document.getElementById("libHeader")],
      infoPill:[document.getElementById("infoPill")],
      listPills:Array.from(document.querySelectorAll(".ipodPill[data-liquid-row-pill]")),
      selectedRow:[document.getElementById("libListSelectedGlass")]
    };
    (targets[elementKey] || []).forEach((el)=> applyGlassMaterialClass(el, material));
    markFrameWork({render:true, textContrast:true});
  }

  function setLiquidGlassElementSetting(elementKey, field, value){
    const current = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    if(!current[elementKey] || field !== "material") return;
    current[elementKey].material = normalizeLiquidGlassMaterial(value, current[elementKey].material);
    uiSettings.liquidGlassElements = cloneGlassElementSettings(current);
    liquidGlassElements = cloneGlassElementSettings(uiSettings.liquidGlassElements);
    saveUiSettings();
    applyLiquidGlassStyleOptions();
  }

  applyElementGlassMaterialClasses();

  function mountLiquidCanvas(){
    try{
      const wrap = document.getElementById("divwrap");
      if(!wrap) return;
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.canvas) return;
        renderer.canvas.classList.add("liquidGlassCanvas");
        const key = renderer.rendererKey || (renderer === window.__liquidGLRenderer__ ? "main" : "");
        renderer.canvas.classList.toggle("liquidGlassCanvasMain", key === "main");
        renderer.canvas.classList.toggle("liquidGlassCanvasWheel", key === "wheel");
        renderer.canvas.setAttribute("data-liquid-renderer", key || "unknown");
        if(key === "wheel"){
          const wheelHost = document.getElementById("wheel") || document.querySelector(".ipodWheelWrap");
          if(wheelHost && renderer.canvas.parentNode !== wheelHost){
            wheelHost.insertBefore(renderer.canvas, wheelHost.firstChild);
          }
          positionWheelLiquidCanvas();
        }else if(key === "main"){
          const stage = document.querySelector(".ipodStage");
          if(stage && renderer.canvas.parentNode !== stage){
            stage.insertBefore(renderer.canvas, stage.firstChild);
          }else if(!stage && renderer.canvas.parentNode !== wrap){
            const afterBg = document.getElementById("visualizerBg");
            if(afterBg && afterBg.parentNode === wrap && afterBg.nextSibling){
              wrap.insertBefore(renderer.canvas, afterBg.nextSibling);
            }else{
              wrap.insertBefore(renderer.canvas, wrap.firstChild);
            }
          }
          positionMainLiquidCanvas();
        }else if(renderer.canvas.parentNode !== wrap){
          const afterBg = document.getElementById("visualizerBg");
          if(afterBg && afterBg.parentNode === wrap && afterBg.nextSibling){
            wrap.insertBefore(renderer.canvas, afterBg.nextSibling);
          }else{
            wrap.insertBefore(renderer.canvas, wrap.firstChild);
          }
        }
        renderer.canvas.style.pointerEvents = "none";
        renderer.canvas.style.setProperty("z-index", key === "wheel" ? "10" : "65", "important");
      });
      debugLiquidGlassRenderers("mount");
    }catch(e){}
  }

  function wheelGlassLayoutRect(){
    const host = document.getElementById("wheel");
    const wrap = host && host.parentElement;
    if(!host || !wrap) return null;
    const box = wrap.getBoundingClientRect();
    const width = host.offsetWidth;
    const height = host.offsetHeight;
    return {left:box.left + (box.width - width) / 2, top:box.top + (box.height - height) / 2, width, height};
  }

  function wheelLensLayoutRect(el){
    const base = wheelGlassLayoutRect();
    if(!base || !el) return null;
    if(el.classList.contains("wheelGlassRing")) return base;
    const button = document.getElementById("btnCenter");
    const transform = button ? window.getComputedStyle(button).transform : "none";
    const matrix = transform && transform.match(/^matrix\(([^)]+)\)$/);
    const values = matrix ? matrix[1].split(",").map(Number) : [];
    const scale = values.length === 6 ? Math.hypot(values[0], values[1]) : 1;
    const width = el.offsetWidth * scale;
    const height = el.offsetHeight * scale;
    return {left:base.left + (base.width - width) / 2, top:base.top + (base.height - height) / 2, width, height};
  }

  function positionWheelLiquidCanvas(){
    try{
      const renderer = liquidWheelRenderer();
      const canvas = renderer && renderer.canvas;
      const host = document.getElementById("wheel") || document.querySelector(".ipodWheelWrap");
      if(!canvas || !host) return;
      const rect = wheelGlassLayoutRect() || host.getBoundingClientRect();
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
      if(!renderer || !renderer.refreshSourceTexture) return false;
      const updated = !!renderer.refreshSourceTexture(reason || "app");
      renderer._dpSourceRefreshCount = (renderer._dpSourceRefreshCount || 0) + 1;
      renderer._dpLastSourceRefreshReason = reason || "app";
      renderer._dpLastSourceRefreshSuccess = updated;
      return updated;
    }catch(e){}
    return false;
  }

  function normalizeLiquidRendererKeys(keys){
    try{
      if(!keys) return LIQUID_VISUALIZER_RENDERER_KEYS.slice();
      const raw = Array.isArray(keys) ? keys : [keys];
      const seen = new Set();
      const out = [];
      raw.forEach((key)=>{
        const value = String(key || "").trim();
        if(!value || LIQUID_VISUALIZER_RENDERER_KEYS.indexOf(value) < 0 || seen.has(value)) return;
        seen.add(value);
        out.push(value);
      });
      return out.length ? out : LIQUID_VISUALIZER_RENDERER_KEYS.slice();
    }catch(e){
      return LIQUID_VISUALIZER_RENDERER_KEYS.slice();
    }
  }

  function visibleLiquidGlassVisualizerRendererKeys(keys){
    const out = [];
    try{
      normalizeLiquidRendererKeys(keys).forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(renderer && rendererTargetVisible(renderer)) out.push(key);
      });
    }catch(e){}
    return out;
  }

  function markLiquidRendererSourceRefresh(renderer, reason, updated){
    try{
      if(!renderer) return;
      renderer._dpSourceRefreshCount = (renderer._dpSourceRefreshCount || 0) + 1;
      renderer._dpLastSourceRefreshReason = reason || "";
      renderer._dpLastSourceRefreshSuccess = updated === true;
    }catch(e){}
  }

  function refreshLiquidGlassVisualizerSources(reason, options){
    try{
      const opts = options || {};
      normalizeLiquidRendererKeys(opts.keys).forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(!renderer) return;
        if(!opts.force && !rendererTargetVisible(renderer)) return;
        const frame = typeof currentVisualizerFrameState === "function" ? currentVisualizerFrameState() : null;
        const artKey = frame && frame.artKey ? String(frame.artKey) : "";
        if(!opts.force && artKey && renderer._dpReactiveArtKey === artKey && renderer._reactiveArtActive && !renderer._sourceIsSolidFallback) return;
        let updated = false;
        let alreadyCounted = false;
        if((renderer.sourceType === "visualizerWebgl" || renderer.sourceType === "webglTexture") && renderer.refreshSourceTexture){
          updated = !!renderer.refreshSourceTexture(reason || "visualizer webgl");
        }else{
          updated = refreshLiquidGlassSource(renderer, reason || "visualizer fallback");
          alreadyCounted = true;
        }
        if(updated && artKey) renderer._dpReactiveArtKey = artKey;
        if(!alreadyCounted) markLiquidRendererSourceRefresh(renderer, reason || "visualizer", updated);
      });
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

  function glassTextUnderColorSignature(style, width, height){
    try{
      const modeBits = ["wheel-labels", "path-pill", "info-pill", "rows", "row-pills", "selected-row", "selected-row-pills"]
        .map((key)=> document.documentElement.getAttribute("data-text-mode-" + key) || "")
        .join(",");
      return [
        Math.round(width || 0),
        Math.round(height || 0),
        String(style.getPropertyValue("--theme-visualizer-a") || "").trim(),
        String(style.getPropertyValue("--theme-visualizer-b") || "").trim(),
        String(style.getPropertyValue("--theme-visualizer-c") || "").trim(),
        String(style.getPropertyValue("--viz-x1") || "").trim(),
        String(style.getPropertyValue("--viz-y1") || "").trim(),
        String(style.getPropertyValue("--viz-x2") || "").trim(),
        String(style.getPropertyValue("--viz-y2") || "").trim(),
        String(style.getPropertyValue("--viz-x3") || "").trim(),
        String(style.getPropertyValue("--viz-y3") || "").trim(),
        modeBits
      ].join("|");
    }catch(e){
      return "";
    }
  }

  function updateGlassTextUnderColors(options){
    try{
      const opts = options && typeof options === "object"
        ? options
        : (arguments.length ? {reason:String(options || ""), force:true} : {reason:"direct", force:true});
      const root = document.documentElement;
      const style = window.getComputedStyle ? window.getComputedStyle(root) : null;
      if(!style) return;
      const width = window.innerWidth || 1;
      const height = window.innerHeight || 1;
      const now = performance && performance.now ? performance.now() : Date.now();
      const signature = glassTextUnderColorSignature(style, width, height);
      const signatureChanged = signature !== glassTextUnderColorState.lastSignature;
      const activeRateMs = 260;
      const idleRateMs = 1200;
      const minInterval = opts.activeAnimating ? activeRateMs : idleRateMs;
      if(!opts.force && !signatureChanged && (now - glassTextUnderColorState.lastRun) < minInterval) return false;
      glassTextUnderColorState.lastRun = now;
      glassTextUnderColorState.lastSignature = signature;
      glassTextUnderColorState.runCount += 1;
      const colors = [
        {color: String(style.getPropertyValue("--theme-visualizer-a") || "rgba(10,132,255,.42)").trim(), x: cssPointValue(style, "--viz-x1", width, width * 0.5), y: cssPointValue(style, "--viz-y1", height, height * 0.28)},
        {color: String(style.getPropertyValue("--theme-visualizer-b") || "rgba(94,92,230,.30)").trim(), x: cssPointValue(style, "--viz-x2", width, width * 0.22), y: cssPointValue(style, "--viz-y2", height, height * 0.68)},
        {color: String(style.getPropertyValue("--theme-visualizer-c") || "rgba(255,69,58,.18)").trim(), x: cssPointValue(style, "--viz-x3", width, width * 0.78), y: cssPointValue(style, "--viz-y3", height, height * 0.64)}
      ];
      document.querySelectorAll(".glassText, .wheelIcon").forEach((el)=>{
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
      return true;
    }catch(e){}
    return false;
  }

  function renderLiquidGlassNow(frameState, options){
    try{
      const opts = options || {};
      updateGlassTextUnderColors({reason:opts.reason || "liquid render", activeAnimating:!!opts.activeAnimating});
      updateLibSelectionGlass("");
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer || !renderer.render) return;
        if(!rendererTargetVisible(renderer)){
          if(renderer.setVisible) renderer.setVisible(false);
          return;
        }
        if(renderer.setVisible) renderer.setVisible(true);
        const key = renderer.rendererKey || "";
        if(key === "main") positionMainLiquidCanvas();
        if(key === "wheel") positionWheelLiquidCanvas();
        renderer.render(Object.assign({}, currentVisualizerFrameState(frameState && frameState.timestamp), frameState || {}));
      });
    }catch(e){}
  }

  function renderLiquidGlassVisualizerSourceNow(frameState, options){
    try{
      const opts = options || {};
      const keys = visibleLiquidGlassVisualizerRendererKeys(opts.keys);
      updateGlassTextUnderColors({reason:opts.reason || "visualizer render", activeAnimating:opts.activeAnimating !== false});
      keys.forEach((key)=>{
        const renderer = liquidGlassRendererByKey(key);
        if(key === "main") positionMainLiquidCanvas();
        if(key === "wheel") positionWheelLiquidCanvas();
        if(renderer && renderer.render && rendererTargetVisible(renderer)) renderer.render(Object.assign({}, currentVisualizerFrameState(frameState && frameState.timestamp), frameState || {}));
      });
    }catch(e){}
  }

  function captureLiquidGlassSnapshot(reason, includeLibList){
    try{
      refreshLiquidGlassVisualizerSources(reason || "app");
      if(includeLibList){
        const mainRenderer = liquidGlassRendererByKey("main");
        if(mainRenderer && rendererTargetVisible(mainRenderer)) refreshLiquidGlassSource(mainRenderer, reason || "app");
      }
      updateGlassTextUnderColors({reason:reason || "snapshot", force:true});
      renderLiquidGlassNow(null, {reason:reason || "snapshot"});
    }catch(e){}
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

  function nowPlayingSurfaceVisible(){
    try{
      const np = document.getElementById("nowPlaying");
      if(!np) return false;
      const style = window.getComputedStyle ? window.getComputedStyle(np) : null;
      return np.classList.contains("npPageActive") || (style && style.display !== "none" && Number(style.opacity || 1) > 0.01);
    }catch(e){
      return false;
    }
  }

  // The shared main renderer initially registers the selected row and row
  // pills as one target set, so those lenses have no group marker.  Teardown
  // must therefore identify the actual elements as well as tagged groups.
  function syncLibTransientLenses(renderer, config){
    if(!renderer) return {selected:false, pills:0};
    const input = config || {};
    const selectedElement = input.selectedElement || null;
    const pillElements = Array.from(input.pillElements || []).filter(Boolean);
    const active = input.active !== false;
    const wanted = new Set(active ? [selectedElement].concat(pillElements).filter(Boolean) : []);
    const manageSelected = input.manageSelected !== false;
    const managePills = input.managePills !== false;
    const isSelected = (el, lens) => manageSelected && (
      el === selectedElement ||
      (el && el.id === "libListSelectedGlass") ||
      (lens && lens._dpLensGroup === "selectedRow")
    );
    const isPill = (el, lens) => managePills && (
      (el && el.matches && el.matches(".ipodPill[data-liquid-row-pill]")) ||
      (lens && lens._dpLensGroup === "listPills")
    );
    const next = [];
    (renderer.lenses || []).forEach((lens)=>{
      const el = lens && lens.el;
      const transientSelected = isSelected(el, lens);
      const transientPill = isPill(el, lens);
      if(!transientSelected && !transientPill){
        if(lens && el && el.isConnected !== false) next.push(lens);
        return;
      }
      const keep = active && wanted.has(el);
      if(keep){
        lens._dpLensGroup = transientSelected ? "selectedRow" : "listPills";
        next.push(lens);
      }else{
        try{ if(lens.destroy) lens.destroy(); }catch(e){}
      }
    });
    renderer.lenses = next;
    if(active && typeof renderer.addLens === "function"){
      const add = (el, group, options) => {
        if(!el || !el.isConnected || renderer.lenses.some((lens)=>lens && lens.el === el)) return;
        const lens = renderer.addLens(el, options || {});
        if(lens) lens._dpLensGroup = group;
      };
      if(manageSelected) add(selectedElement, "selectedRow", input.selectedOptions);
      if(managePills) pillElements.forEach((el)=>add(el, "listPills", input.pillOptions));
    }
    renderer._metricsDirty = true;
    renderer._snapshotRectPx = null;
    return {
      selected: !!(selectedElement && renderer.lenses.some((lens)=>lens && lens.el === selectedElement)),
      pills: renderer.lenses.filter((lens)=>lens && lens._dpLensGroup === "listPills").length
    };
  }

  function cancelLibSelectionMotion(){
    try{
      if(typeof listSelectionMotion === "undefined" || !listSelectionMotion) return;
      const pending = listSelectionMotion.raf;
      if(pending > 0 && typeof cancelAnimationFrame === "function") cancelAnimationFrame(pending);
      const scheduler = frameScheduler();
      if(pending === -1 && scheduler && scheduler.cancel) scheduler.cancel("lib-selection-motion");
      if(listSelectionMotion.boundaryReleaseTimer && typeof clearTimeout === "function") clearTimeout(listSelectionMotion.boundaryReleaseTimer);
      listSelectionMotion.raf = 0;
      listSelectionMotion.boundaryReleaseTimer = 0;
      listSelectionMotion.boundaryHeld = false;
      listSelectionMotion.boundaryDirection = 0;
      listSelectionMotion.targetOpacity = 0;
      listSelectionMotion.currentOpacity = 0;
      listSelectionMotion.targetStretch = 0;
      listSelectionMotion.stretch = 0;
      listSelectionMotion.targetForegroundProgress = 0;
      listSelectionMotion.foregroundProgress = 0;
    }catch(e){}
  }

  function destroyLibPillGlassLenses(reason){
    try{
      const renderer = liquidGlassRendererByKey("main");
      if(renderer) syncLibTransientLenses(renderer, {active:false, manageSelected:false, managePills:true});
      if(renderer) renderer._dpLiquidTargetIds = [];
      document.querySelectorAll(".ipodPill[data-liquid-row-pill]").forEach((el)=>{
        try{
          el.removeAttribute("data-liquid-pill-id");
          el.style.visibility = "";
        }catch(e){}
      });
      markFrameWork({metrics:true, render:true});
      debugLiquidGlassRenderers(reason || "destroy lib pills");
    }catch(e){}
  }

  function destroyLibSelectionGlass(reason){
    try{
      cancelLibSelectionMotion();
      const renderer = liquidGlassRendererByKey("main");
      if(renderer){
        syncLibTransientLenses(renderer, {active:false, manageSelected:true, managePills:false});
        renderer._metricsDirty = true;
        renderer._snapshotRectPx = null;
      }
      const el = document.getElementById("libListSelectedGlass");
      if(el){
        el.style.opacity = "0";
        el.classList.remove("isVisible");
      }
      markFrameWork({metrics:true, render:true});
      debugLiquidGlassRenderers(reason || "destroy lib selection");
    }catch(e){}
  }

  function destroyTransientListGlass(reason){
    destroyLibSelectionGlass(reason || "destroy transient list glass");
    destroyLibPillGlassLenses(reason || "destroy transient list glass");
  }

  function stableRowPillId(row, pill, index){
    try{
      const rowIndex = row && row.dataset ? String(row.dataset.index || "") : "";
      const item = window.state && state.items ? state.items[Number(rowIndex)] : null;
      const current = window.state && state.current ? state.current : {};
      const viewId = [
        current.kind || "",
        current.root && current.root.id || current.root_id || "",
        current.rel || "",
        current.level || "",
        current.value || "",
        current.label || ""
      ].join("|");
      const itemId = item && (item.key || item.rel || item.value || item.label || item.kind) || rowIndex;
      return [viewId, itemId, rowIndex, index || 0].join("::");
    }catch(e){
      return "pill::" + String(index || 0);
    }
  }

  function rowPillIntersectsListInnerRect(pillRect, innerRect, overscanPx){
    const pill = pillRect || {};
    const inner = innerRect || {};
    const overscan = Math.max(0, Number(overscanPx) || 0);
    return Number(pill.right) > Number(inner.left) - overscan &&
      Number(pill.left) < Number(inner.right) + overscan &&
      Number(pill.bottom) > Number(inner.top) - overscan &&
      Number(pill.top) < Number(inner.bottom) + overscan;
  }

  function positionMainLiquidCanvas(){
    try{
      const renderer = liquidGlassRendererByKey("main");
      const canvas = renderer && renderer.canvas;
      const host = document.querySelector(".ipodStage");
      if(!canvas || !host) return;
      const rect = host.getBoundingClientRect();
      canvas.style.setProperty("position", "absolute", "important");
      canvas.style.setProperty("inset", "auto", "important");
      canvas.style.setProperty("left", (-(rect.left || 0)).toFixed(3) + "px", "important");
      canvas.style.setProperty("top", (-(rect.top || 0)).toFixed(3) + "px", "important");
      canvas.style.setProperty("width", (window.innerWidth || canvas.width || 1) + "px", "important");
      canvas.style.setProperty("height", (window.innerHeight || canvas.height || 1) + "px", "important");
      canvas.style.setProperty("pointer-events", "none", "important");
      canvas.style.setProperty("z-index", "65", "important");
    }catch(e){}
  }

  function computeEligibleRowPillElements(){
    const out = [];
    try{
      const list = document.getElementById("libList");
      if(!list || nowPlayingSurfaceVisible()) return out;
      const inner = selectedListInnerRect();
      if(!inner) return out;
      const pills = Array.from(list.querySelectorAll(".ipodPill[data-liquid-row-pill]"));
      pills.forEach((pill)=>{
        try{
          if(!pill || !pill.isConnected) return;
          const row = pill.closest(".ipodItem");
          if(!row || !row.isConnected || !list.contains(row)) return;
          const rowRect = row.getBoundingClientRect();
          const pillRect = pill.getBoundingClientRect();
          if(rowRect.width <= 0 || rowRect.height <= 0 || pillRect.width <= 0 || pillRect.height <= 0) return;
          if(!rowPillIntersectsListInnerRect(pillRect, inner, 96)) return;
          pill.style.visibility = "";
          const rowPills = Array.from(row.querySelectorAll(".ipodPill[data-liquid-row-pill]"));
          pill.setAttribute("data-liquid-pill-id", stableRowPillId(row, pill, rowPills.indexOf(pill)));
          out.push(pill);
        }catch(e){}
      });
    }catch(e){}
    return out;
  }

  function reconcileLibPillGlassTargets(reason){
    try{
      if(typeof window.liquidGL !== "function") return;
      if(!liquidGlassReady || document.documentElement.classList.contains("liquidGlassFallback")) return;
      if(nowPlayingSurfaceVisible()){
        destroyLibPillGlassLenses(reason || "now playing visible");
        return;
      }
      const renderer = liquidGlassRendererByKey("main");
      const elements = computeEligibleRowPillElements();
      const nextIds = elements.map((el)=> String(el.getAttribute("data-liquid-pill-id") || ""));
      const currentIds = renderer && Array.isArray(renderer._dpLiquidTargetIds) ? renderer._dpLiquidTargetIds : [];
      const same = currentIds.length === nextIds.length && currentIds.every((id, idx)=> id === nextIds[idx]) && elements.every(el => renderer.lenses.some(lens => lens.el === el));
      if(renderer && same){
        if(renderer.canvas) renderer.canvas.style.visibility = "";
        renderer._metricsDirty = true;
        renderer._snapshotRectPx = null;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
        if(renderer.setVisible) renderer.setVisible(true);
        if(renderer.render) renderer.render(currentVisualizerFrameState());
        return;
      }
      const options = Object.assign({}, liquidGlassElementOptions("listPills"), {
        target: ".ipodPill.liquidGlass[data-liquid-row-pill][data-liquid-pill-id]",
        rendererKey: "main",
        sourceType: "visualizerWebgl",
        sourceElement: "#visualizerReactiveArt",
        clipTarget: "#libList",
        clipToPaddingBox: true,
        syncTargets: true
      });
      let nextRenderer = renderer;
      if(nextRenderer && nextRenderer.syncLensGroup){
        // Tag any lenses created by the shared initial target before syncing;
        // otherwise an ungrouped stale pill survives an empty group sync.
        syncLibTransientLenses(nextRenderer, {active:true, manageSelected:false, managePills:true, pillElements:elements, pillOptions:options});
        nextRenderer.syncLensGroup("listPills", elements, options);
      }else{
        window.liquidGL(options);
        nextRenderer = liquidGlassRendererByKey("main");
      }
      if(nextRenderer){
        nextRenderer._dpLiquidTargetIds = nextIds;
        nextRenderer._metricsDirty = true;
        nextRenderer._snapshotRectPx = null;
        if(nextRenderer.canvas) nextRenderer.canvas.style.visibility = "";
        if(nextRenderer.setVisible) nextRenderer.setVisible(true);
      }
      applyElementGlassMaterialClasses();
      mountLiquidCanvas();
      refreshLiquidGlassVisualizerSources(reason || "lib pills", {keys:["main"]});
      invalidateLibPillGlass(reason || "lib pills");
    }catch(e){
      try{ console.error("[DebriPod LiquidGL] row-pill reconciliation failed", e); }catch(err){}
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
    targetStretch: 0,
    direction: 0,
    targetDirection: 0,
    foregroundProgress: 0,
    targetForegroundProgress: 0,
    boundaryHeld: false,
    boundaryDirection: 0,
    boundaryLastInputTs: 0,
    boundaryReleaseTimer: 0,
    raf: 0,
    lastStepTs: 0,
    initialized: false,
    rapidInput: false,
    rapidCount: 0,
    lastInputAt: 0,
    settleTimer: 0
  };

  function noteLibSelectionInput(now){
    const motion = listSelectionMotion;
    motion.rapidCount = motion.lastInputAt && now - motion.lastInputAt < 110 ? motion.rapidCount + 1 : 1;
    motion.lastInputAt = now;
    if(motion.rapidCount >= 3) motion.rapidInput = true;
    if(motion.settleTimer) clearTimeout(motion.settleTimer);
    motion.settleTimer = setTimeout(()=>{
      motion.settleTimer = 0;
      motion.rapidInput = false;
      motion.rapidCount = 0;
      updateLibSelectionGlass("input settled");
    }, 160);
  }

  function applyLibSelectionForeground(){
      const fg = Math.max(0, Math.min(1, listSelectionMotion.foregroundProgress || 0));
      document.documentElement.style.setProperty("--dp-selected-foreground-progress", fg.toFixed(3));
      document.documentElement.style.setProperty("--dp-selected-foreground-base-pct", ((1 - fg) * 100).toFixed(2) + "%");
      document.documentElement.style.setProperty("--dp-selected-foreground-target-pct", (fg * 100).toFixed(2) + "%");
      document.documentElement.style.setProperty("--dp-selected-foreground-scale", (1 + fg * 0.035).toFixed(4));
      document.documentElement.style.setProperty("--dp-selected-pill-scale", (1 + fg * 0.025).toFixed(4));
  }

  function applyLibSelectionMotion(){
    try{
      const el = document.getElementById("libListSelectedGlass");
      if(!el) return;
      const stretchPx = Math.abs(listSelectionMotion.stretch || 0) * Math.min(18, Math.max(8, listSelectionMotion.currentHeight * 0.24));
      const horizontalInset = Math.min(Math.max(0, listSelectionMotion.currentWidth * 0.18), stretchPx * 0.14);
      const direction = listSelectionMotion.direction || 0;
      const renderY = listSelectionMotion.currentY + (direction < 0 ? -stretchPx : 0);
      const renderHeight = Math.max(0, listSelectionMotion.currentHeight + stretchPx);
      const renderX = listSelectionMotion.currentX + horizontalInset;
      const renderWidth = Math.max(12, listSelectionMotion.currentWidth - (horizontalInset * 2));
      el.style.transform = "translate3d(" + renderX.toFixed(3) + "px," + renderY.toFixed(3) + "px,0)";
      el.style.width = renderWidth.toFixed(3) + "px";
      el.style.height = renderHeight.toFixed(3) + "px";
      el.style.borderRadius = Math.max(0, listSelectionMotion.currentRadius).toFixed(3) + "px";
      el.style.opacity = listSelectionMotion.currentOpacity.toFixed(3);
      el.classList.toggle("isVisible", listSelectionMotion.currentOpacity > 0.01);
      document.documentElement.style.setProperty("--dp-selected-x", renderX.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-y", listSelectionMotion.currentY.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-w", renderWidth.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-h", renderHeight.toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-radius", Math.max(0, listSelectionMotion.currentRadius).toFixed(3) + "px");
      document.documentElement.style.setProperty("--dp-selected-stretch", String(listSelectionMotion.stretch || 0));
      document.documentElement.style.setProperty("--dp-selected-opacity", listSelectionMotion.currentOpacity.toFixed(3));
      applyLibSelectionForeground();
      if(typeof setSelectedRowContentOffset === "function") setSelectedRowContentOffset(renderY + (renderHeight - listSelectionMotion.currentHeight) / 2, listSelectionMotion.targetY);
      const renderer = liquidGlassRendererByKey("main");
      if(renderer){
        renderer._metricsDirty = true;
        renderer._snapshotRectPx = null;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
        markFrameWork({metrics:true, render:true});
      }
    }catch(e){}
  }

  function stepLibSelectionMotion(frameState){
    listSelectionMotion.raf = 0;
    try{
      const now = (frameState && frameState.timestamp) || (performance && performance.now ? performance.now() : Date.now());
      const interval = animationFrameIntervalMs("selectedRow");
      if(listSelectionMotion.lastStepTs && now - listSelectionMotion.lastStepTs < interval - 1){
        scheduleLibSelectionMotion();
        return;
      }
      listSelectionMotion.lastStepTs = now;
      const elapsed = listSelectionMotion.motionStepTs ? Math.max(1, Math.min(64, now - listSelectionMotion.motionStepTs)) : 16.667;
      listSelectionMotion.motionStepTs = now;
      const stiffness = 1 - Math.exp(-elapsed / 40);
      listSelectionMotion.currentX += (listSelectionMotion.targetX - listSelectionMotion.currentX) * stiffness;
      listSelectionMotion.currentY += (listSelectionMotion.targetY - listSelectionMotion.currentY) * stiffness;
      listSelectionMotion.currentWidth += (listSelectionMotion.targetWidth - listSelectionMotion.currentWidth) * stiffness;
      listSelectionMotion.currentHeight += (listSelectionMotion.targetHeight - listSelectionMotion.currentHeight) * stiffness;
      listSelectionMotion.currentRadius += (listSelectionMotion.targetRadius - listSelectionMotion.currentRadius) * stiffness;
      listSelectionMotion.currentOpacity += (listSelectionMotion.targetOpacity - listSelectionMotion.currentOpacity) * 0.42;
      listSelectionMotion.stretch += ((listSelectionMotion.targetStretch || 0) - (listSelectionMotion.stretch || 0)) * 0.28;
      if(Math.abs((listSelectionMotion.targetStretch || 0) - (listSelectionMotion.stretch || 0)) < 0.006) listSelectionMotion.stretch = listSelectionMotion.targetStretch || 0;
      listSelectionMotion.direction = listSelectionMotion.targetDirection || listSelectionMotion.direction || 0;
      if(Math.abs(listSelectionMotion.stretch) < 0.006 && !listSelectionMotion.targetStretch) listSelectionMotion.direction = 0;
      listSelectionMotion.foregroundProgress += ((listSelectionMotion.targetForegroundProgress || 0) - (listSelectionMotion.foregroundProgress || 0)) * stiffness;
      const done = (
        Math.abs(listSelectionMotion.targetX - listSelectionMotion.currentX) < 0.08 &&
        Math.abs(listSelectionMotion.targetY - listSelectionMotion.currentY) < 0.08 &&
        Math.abs(listSelectionMotion.targetWidth - listSelectionMotion.currentWidth) < 0.08 &&
        Math.abs(listSelectionMotion.targetHeight - listSelectionMotion.currentHeight) < 0.08 &&
        Math.abs(listSelectionMotion.targetRadius - listSelectionMotion.currentRadius) < 0.08 &&
        Math.abs(listSelectionMotion.targetOpacity - listSelectionMotion.currentOpacity) < 0.01 &&
        Math.abs((listSelectionMotion.targetStretch || 0) - (listSelectionMotion.stretch || 0)) < 0.01 &&
        Math.abs((listSelectionMotion.targetForegroundProgress || 0) - (listSelectionMotion.foregroundProgress || 0)) < 0.01
      );
      if(done){
        listSelectionMotion.currentX = listSelectionMotion.targetX;
        listSelectionMotion.currentY = listSelectionMotion.targetY;
        listSelectionMotion.currentWidth = listSelectionMotion.targetWidth;
        listSelectionMotion.currentHeight = listSelectionMotion.targetHeight;
        listSelectionMotion.currentRadius = listSelectionMotion.targetRadius;
        listSelectionMotion.currentOpacity = listSelectionMotion.targetOpacity;
        listSelectionMotion.stretch = listSelectionMotion.targetStretch || 0;
        listSelectionMotion.foregroundProgress = listSelectionMotion.targetForegroundProgress || 0;
      }
      applyLibSelectionMotion();
      if(!done){
        const scheduler = frameScheduler();
        if(scheduler && scheduler.request){
          listSelectionMotion.raf = -1;
          scheduler.request("lib-selection-motion", stepLibSelectionMotion);
          scheduler.mark({keepAlive:true});
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
      opacity = listSelectionMotion.rapidInput ? 0 : opacity;
      if(listSelectionMotion.initialized && listSelectionMotion.targetX === x && listSelectionMotion.targetY === y &&
         listSelectionMotion.targetWidth === width && listSelectionMotion.targetHeight === height &&
         listSelectionMotion.targetRadius === radius && listSelectionMotion.targetOpacity === opacity) return;
      listSelectionMotion.targetX = x;
      listSelectionMotion.targetY = y;
      listSelectionMotion.targetWidth = width;
      listSelectionMotion.targetHeight = height;
      listSelectionMotion.targetRadius = radius;
      opacity = listSelectionMotion.rapidInput ? 0 : opacity;
      listSelectionMotion.targetOpacity = opacity;
      listSelectionMotion.targetForegroundProgress = opacity > 0.5 ? 1 : 0;
      if(!listSelectionMotion.initialized){
        listSelectionMotion.currentX = x;
        listSelectionMotion.currentY = y;
        listSelectionMotion.currentWidth = width;
        listSelectionMotion.currentHeight = height;
        listSelectionMotion.currentRadius = radius;
        listSelectionMotion.currentOpacity = opacity;
        listSelectionMotion.foregroundProgress = listSelectionMotion.targetForegroundProgress;
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
      const direction = clamped === 0 ? 0 : (clamped > 0 ? 1 : -1);
      const activeState = window.state;
      const items = activeState && Array.isArray(activeState.items) ? activeState.items : [];
      const selected = activeState ? Number(activeState.sel) : NaN;
      const atBoundary = direction !== 0 && items.length > 0 && Number.isFinite(selected) && (
        (direction < 0 && selected <= 0) || (direction > 0 && selected >= items.length - 1)
      );
      if(listSelectionMotion.boundaryReleaseTimer){
        clearTimeout(listSelectionMotion.boundaryReleaseTimer);
        listSelectionMotion.boundaryReleaseTimer = 0;
      }
      if(direction !== 0 && atBoundary){
        // Repeated wheel ticks at a terminal row are one continuous pull. Hold
        // the maximum stretch instead of easing to zero between stale timers.
        if(listSelectionMotion.boundaryHeld && listSelectionMotion.boundaryDirection !== direction){
          listSelectionMotion.boundaryHeld = false;
          listSelectionMotion.boundaryDirection = 0;
          listSelectionMotion.targetStretch = 0;
          listSelectionMotion.targetDirection = 0;
          scheduleLibSelectionMotion();
          return;
        }
        listSelectionMotion.boundaryHeld = true;
        listSelectionMotion.boundaryDirection = direction;
        listSelectionMotion.boundaryLastInputTs = Date.now();
        listSelectionMotion.targetStretch = 1;
        listSelectionMotion.targetDirection = direction;
        scheduleLibSelectionMotion();
        return;
      }
      if(listSelectionMotion.boundaryHeld){
        const release = ()=>{
          listSelectionMotion.boundaryReleaseTimer = 0;
          listSelectionMotion.boundaryHeld = false;
          listSelectionMotion.boundaryDirection = 0;
          listSelectionMotion.targetStretch = 0;
          listSelectionMotion.targetDirection = 0;
          scheduleLibSelectionMotion();
        };
        if(direction === 0){
          const elapsed = Date.now() - Number(listSelectionMotion.boundaryLastInputTs || 0);
          const remaining = Math.max(0, 90 - elapsed);
          if(remaining > 0){
            listSelectionMotion.boundaryReleaseTimer = setTimeout(release, remaining);
            return;
          }
          release();
          return;
        }
        // A direction change releases the terminal pull before a new pull can
        // be established, including when the selection has moved off-edge.
        if(direction !== listSelectionMotion.boundaryDirection){
          release();
          return;
        }
        release();
        return;
      }
      listSelectionMotion.targetStretch = Math.abs(clamped);
      listSelectionMotion.targetDirection = direction;
      scheduleLibSelectionMotion();
    }catch(e){}
  }

  function updateLibSelectionGlass(reason){
    try{
      const el = document.getElementById("libListSelectedGlass");
      const list = document.getElementById("libList");
      if(!el || !list) return;
      if(list.hasAttribute("aria-hidden") || nowPlayingSurfaceVisible()){
        destroyLibSelectionGlass(reason || "now playing visible");
        return;
      }
      const settings = glassElementSettings("selectedRow");
      let selectionRenderer = liquidGlassRendererByKey("main");
      if(selectionRenderer && selectionRenderer.canvas) selectionRenderer.canvas.style.visibility = "";
      applyGlassMaterialClass(el, settings.material);
      const row = list.querySelector(".ipodItem.sel");
      const inner = selectedListInnerRect();
      if(!row || !inner){
        setLibSelectionTarget(listSelectionMotion.targetX, listSelectionMotion.targetY, listSelectionMotion.targetWidth, listSelectionMotion.targetHeight, listSelectionMotion.targetRadius, 0);
        return;
      }
      const selectedKey = String(state.itemsVersion || 0) + ":" + String(state.sel);
      if(listSelectionMotion.selectedKey !== selectedKey){
        listSelectionMotion.selectedKey = selectedKey;
        const changedAt = performance.now();
        noteLibSelectionInput(changedAt);
        if(!listSelectionMotion.selectionChangedAt || changedAt - listSelectionMotion.selectionChangedAt > 180) listSelectionMotion.foregroundProgress = 0;
        listSelectionMotion.selectionChangedAt = changedAt;
        listSelectionMotion.targetForegroundProgress = 1;
        applyLibSelectionForeground();
        scheduleLibSelectionMotion();
      }
      const rowRect = row.getBoundingClientRect();
      const left = Math.max(rowRect.left, inner.left);
      const right = Math.min(rowRect.right, inner.right);
      const visibleTop = Math.max(rowRect.top, inner.top);
      const visibleBottom = Math.min(rowRect.bottom, inner.bottom);
      if(right <= left || visibleBottom <= visibleTop){
        setLibSelectionTarget(listSelectionMotion.targetX, listSelectionMotion.targetY, listSelectionMotion.targetWidth, listSelectionMotion.targetHeight, listSelectionMotion.targetRadius, 0);
        return;
      }
      const host = document.getElementById("ipodScreen");
      const hostRect = host ? host.getBoundingClientRect() : {left:0, top:0};
      const targetHeight = Math.max(1, rowRect.height || (visibleBottom - visibleTop));
      const radius = targetHeight > 58 ? 16 : 999;
      setLibSelectionTarget(left - hostRect.left, rowRect.top - hostRect.top, right - left, targetHeight, radius, 1);
      const renderer = liquidGlassRendererByKey("main");
      if(renderer){
        syncLibTransientLenses(renderer, {
          active:true,
          manageSelected:true,
          managePills:false,
          selectedElement:el,
          selectedOptions:Object.assign({}, liquidGlassElementOptions("selectedRow"), {rendererKey:"main", clipTarget:null, clipToPaddingBox:false})
        });
        renderer._metricsDirty = true;
        if(renderer.lenses){
          renderer.lenses.forEach((lens)=>{ try{ lens.rectPx = null; }catch(e){} });
        }
      }
      if(reason && renderer) markFrameWork({metrics:true, render:true});
    }catch(e){}
  }

  function invalidateLibPillGlass(reason){
    try{
      updateLibSelectionGlass(reason || "");
      const renderer = liquidGlassRendererByKey("main");
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

  function hideTransientListGlass(reason){
    destroyTransientListGlass(reason || "hide transient list glass");
  }

  function refreshLibPillGlassLenses(reason){
    reconcileLibPillGlassTargets(reason || "lib pills");
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

  function liquidGlassDiagnostics(){
    const out = [];
    try{
      liquidGlassRenderers().forEach((renderer)=>{
        if(!renderer) return;
        const key = renderer.rendererKey || "main";
        const settingsKey = key === "wheel" ? "wheel" : "pathPill";
        const settings = glassElementSettings(settingsKey) || {};
        const canvasStyle = renderer.canvas && window.getComputedStyle ? window.getComputedStyle(renderer.canvas) : null;
        const targetRects = (renderer.lenses || []).map((lens)=>{
          try{
            const r = lens && lens.el ? lens.el.getBoundingClientRect() : null;
            return r ? {left:r.left, top:r.top, width:r.width, height:r.height} : null;
          }catch(e){ return null; }
        }).filter(Boolean);
        const row = {
          key:key,
          visible:rendererTargetVisible(renderer),
          resolution:Number(settings.resolution || renderer.resolution || 0),
          texture:String(renderer.textureWidth || 0) + "x" + String(renderer.textureHeight || 0),
          lens_count:renderer.lenses ? renderer.lenses.length : 0,
          lensCount:renderer.lenses ? renderer.lenses.length : 0,
          canvas_opacity:renderer.canvas && window.getComputedStyle ? window.getComputedStyle(renderer.canvas).opacity : "",
          renderCount: renderer._renderCount || renderer.renderCount || 0,
          sourceRefreshCount: renderer._dpSourceRefreshCount || 0,
          lastSourceRefreshReason: renderer._dpLastSourceRefreshReason || "",
          lastSourceRefreshSuccess: renderer._dpLastSourceRefreshSuccess === true
        };
        out.push(row);
      });
    }catch(e){}
    return out;
  }

  function recaptureLiquidGlassElement(el){
    try{
      if(!el) return;
      renderLiquidGlassNow();
    }catch(e){}
  }

  function scheduleLiquidGlassRender(){
    markFrameWork({metrics:true, render:true, textContrast:true});
  }

  function initLiquidGlass(){
    try{
      if(liquidGlassReady || typeof window.liquidGL !== "function") return;
      const sharedGlassOptions = Object.assign({}, liquidGlassElementOptions("pathPill"), {
        target: "#libList.liquidGlass, #libListSelectedGlass.liquidGlass, .pathPillGlass.liquidGlass, .infoPillGlass.liquidGlass",
        rendererKey: "main",
        sourceType: "visualizerWebgl",
        sourceElement: "#visualizerReactiveArt"
      });
      window.liquidGL(sharedGlassOptions);
      const wheelGlassInstances = asLiquidArray(window.liquidGL(Object.assign({}, liquidGlassElementOptions("wheel"), {
        target: ".wheelGlassRing.liquidGlass, .wheelCenterGlass.liquidGlass",
        rendererKey: "wheel",
        geometryRect: wheelLensLayoutRect,
        sourceType: "visualizerWebgl",
        sourceElement: "#visualizerReactiveArt"
      })));
      liquidWheelLenses = wheelGlassInstances.filter(inst => inst && inst.el);
      mountLiquidCanvas();
      refreshLiquidGlassVisualizerSources("init");
      applyLiquidGlassStyleOptions();
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
            if(flags.textContrast) updateGlassTextUnderColors({reason:"scheduler", force:true});
            if(flags.metrics || flags.render || flags.refreshSources || flags.textContrast){
              renderLiquidGlassNow(frameState, {reason:"scheduler", activeAnimating:!!flags.keepAlive});
            }
          });
        }
      }catch(err){}
      liquidGlassReady = true;
      markFrameWork({refreshSources:true, metrics:true, render:true, textContrast:true});
    }catch(e){
      liquidGlassReady = true;
      try{ console.error("[DebriPod LiquidGL] initialization failed", e); }catch(err){}
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
      wheelGlassTiltRect = wheelGlassLayoutRect() || lens.rectPx || lens.el.getBoundingClientRect();
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

  function wheelTiltEaseStep(frameState){
    wheelTiltAnimFrame = 0;
    try{
      const now = (frameState && frameState.timestamp) || (performance && performance.now ? performance.now() : Date.now());
      const interval = animationFrameIntervalMs("wheelTilt");
      if(wheelTiltEaseStep._last && now - wheelTiltEaseStep._last < interval - 1){
        const scheduler = frameScheduler();
        if(scheduler && scheduler.request){
          wheelTiltAnimFrame = -1;
          scheduler.request("wheel-tilt", wheelTiltEaseStep);
          scheduler.mark({keepAlive:true});
        }else{
          wheelTiltAnimFrame = requestAnimationFrame(wheelTiltEaseStep);
        }
        return;
      }
      wheelTiltEaseStep._last = now;
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
          scheduler.mark({keepAlive:true});
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
      if(renderer && renderer.render){
        positionWheelLiquidCanvas();
        renderer.render(Object.assign({}, currentVisualizerFrameState(frameState && frameState.timestamp), frameState || {}));
      }
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

  try{
    root.liquidDiagnostics = {
      renderers: liquidGlassDiagnostics,
      visibleVisualizerRenderers: visibleLiquidGlassVisualizerRendererKeys,
      textColorScans: function(){
        return {
          runCount: glassTextUnderColorState.runCount || 0,
          lastRun: glassTextUnderColorState.lastRun || 0,
          lastSignature: glassTextUnderColorState.lastSignature || ""
        };
      }
    };
  }catch(e){}
