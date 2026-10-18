/* DebriPod's glass adapter.
 *
 * The glass engine is sfgl (static/vendor/sfgl). This file maps DebriPod's
 * elements, settings and state onto it: which elements are lenses and in
 * which layer, their materials, the reactive artwork or wallpaper backdrop,
 * the selected-row motion, the row pills, and the tilted wheel.
 */
  var glassTextUnderColorState = {
    lastRun: 0,
    lastSignature: "",
    runCount: 0
  };
  var debripodGlass = null;
  var debripodGlassMainSurface = null;

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
    const alpha = normalizeTextOpacity(uiSettings.textOpacity == null ? uiSettings.textTransparency : uiSettings.textOpacity);
    const strong = strongerForegroundOpacity(alpha);
    const key = normalizeTextMode(mode);
    if(key === "white" || group === "selectedRow" || group === "selectedRowPills") return "rgba(255,255,255," + strong.toFixed(3) + ")";
    return "rgba(255,255,255," + alpha.toFixed(3) + ")";
  }

  function applyTextModeClasses(){
    try{
      uiSettings.textOpacity = normalizeTextOpacity(uiSettings.textOpacity == null ? uiSettings.textTransparency : uiSettings.textOpacity);
      uiSettings.textTransparency = uiSettings.textOpacity;
      const doc = document.documentElement;
      const normal = textModeColor("transparent", "rows");
      const strong = textModeColor("white", "selectedRow");
      doc.style.setProperty("--dp-text-wheel-labels", normal);
      doc.style.setProperty("--dp-text-path-pill", normal);
      doc.style.setProperty("--dp-text-info-pill", normal);
      doc.style.setProperty("--dp-text-rows", normal);
      doc.style.setProperty("--dp-text-row-pills", normal);
      doc.style.setProperty("--dp-text-selected-row", strong);
      doc.style.setProperty("--dp-text-selected-row-pills", strong);
      doc.style.setProperty("--dp-text-transparent-alpha", uiSettings.textTransparency.toFixed(3));
      doc.style.setProperty("--ui-text-opacity", uiSettings.textOpacity.toFixed(3));
      doc.style.setProperty("--foreground-opacity", uiSettings.textOpacity.toFixed(3));
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
      applyGlassMaterialClass(document.getElementById("libListGlass"), all.libraryList.material);
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

  function applyRootGlassMaterialClass(material){
    try{
      applyGlassMaterialClass(document.documentElement, material);
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
    const transformScale = values.length === 6 ? Math.hypot(values[0], values[1]) : 1;
    const scaleParts=button?String(window.getComputedStyle(button).scale || "1").split(/\s+/).map(Number):[1];
    const scaleX=Number.isFinite(scaleParts[0])?scaleParts[0]:1;
    const scaleY=Number.isFinite(scaleParts[1])?scaleParts[1]:scaleX;
    const width = el.offsetWidth * transformScale * scaleX;
    const height = el.offsetHeight * transformScale * scaleY;
    return {left:base.left + (base.width - width) / 2, top:base.top + (base.height - height) / 2, width, height};
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
      // Check the rate before reading styles: this runs on animated frames.
      const nowEarly = performance && performance.now ? performance.now() : Date.now();
      if(!opts.force && (nowEarly - glassTextUnderColorState.lastRun) < (opts.activeAnimating ? 260 : 1200)) return false;
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

  // ------------------------------------------------------------------
  // Engine, surface and lens options
  // ------------------------------------------------------------------

  function debripodGlassInstance(){ return debripodGlass; }
  function debripodGlassSurface(){ return debripodGlassMainSurface; }

  function glassRequestRender(){
    try{ if(debripodGlass) debripodGlass.requestRender(); }catch(e){}
  }

  // Optical depth. Higher layers refract the glass below them.
  function debripodGlassLayer(el){
    if(!el) return 0;
    if(el.id === "libListSelectedGlass") return 2;
    if(el.hasAttribute && el.hasAttribute("data-liquid-row-pill")) return el.closest(".ipodItem.sel") ? 3 : 1;
    if(el.classList && (el.classList.contains("wheelCenterGlass") || el.classList.contains("pathPillGlass") || el.classList.contains("infoPillGlass"))) return 1;
    return 0;
  }

  // The wheel is tilted with a CSS 3D transform. Its glass is drawn on the
  // main surface with the same transform, so it tilts exactly like the
  // labels and hit areas.
  function wheelGlassTransform(){
    if(!wheelGlassTiltX && !wheelGlassTiltY) return null;
    const rect = wheelGlassLayoutRect();
    if(!rect) return null;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const matrix = new DOMMatrix().translate(cx, cy)
      .multiply(new DOMMatrix("perspective(900px)"))
      .rotateAxisAngle(1, 0, 0, wheelGlassTiltX)
      .rotateAxisAngle(0, 1, 0, wheelGlassTiltY)
      .translate(-cx, -cy);
    return {matrix, tiltX:wheelGlassTiltX, tiltY:wheelGlassTiltY};
  }

  function glassLensOptions(key){
    const settings = glassElementSettings(key);
    const options = {
      reveal: "none",
      material: normalizeLiquidGlassMaterial(settings.material, 0),
      layer: debripodGlassLayer
    };
    if(key === "libraryList"){
      options.geometry = "live";
      options.edgeFrost = ()=> document.getElementById("libList")?.scrollTop > 0 ? 1 : 0;
    }else if(key === "selectedRow"){
      options.geometry = "live";
      options.underlay = ()=> (window.DebriPod && window.DebriPod.rowRefraction) || null;
      options.opacity = ()=> Math.max(0, Math.min(1, Number(listSelectionMotion.currentOpacity) || 0));
    }else if(key === "listPills"){
      options.geometry = "dom";
      options.clip = ()=> document.getElementById("libList");
      options.clipToPaddingBox = true;
    }else if(key === "wheel"){
      options.geometry = wheelLensLayoutRect;
      options.transform = wheelGlassTransform;
    }else{
      options.geometry = "live";
    }
    return options;
  }

  // Kept for callers that still ask for element options by key.
  function liquidGlassElementOptions(key){ return glassLensOptions(key); }

  function liquidGlassLensElementKey(lens){
    const el = lens && lens.el;
    if(el && el.classList){
      if(el.classList.contains("infoPillGlass")) return "infoPill";
      if(el.classList.contains("pathPillGlass")) return "pathPill";
      if(el.classList.contains("ipodPill") && el.hasAttribute("data-liquid-row-pill")) return "listPills";
      if(el.classList.contains("wheelGlassRing") || el.classList.contains("wheelCenterGlass")) return "wheel";
    }
    if(el && el.id === "libListGlass") return "libraryList";
    if(el && el.id === "libListSelectedGlass") return "selectedRow";
    return "pathPill";
  }

  function glassLenses(){
    const surface = debripodGlassSurface();
    return surface ? surface.lenses.slice() : [];
  }

  // Lenses whose element has a class, for the path and info pill code.
  function glassLensesWithClass(className){
    return glassLenses().filter((lens)=> lens && lens.el && lens.el.classList && lens.el.classList.contains(className));
  }

  function applyLiquidGlassStyleOptions(){
    try{
      applyTextModeClasses();
      applyElementGlassMaterialClasses();
      updateLibSelectionGlass("style options");
      glassLenses().forEach((lens)=>{
        const options = glassLensOptions(liquidGlassLensElementKey(lens));
        lens.setOptions({material:options.material});
      });
      markFrameWork({render:true, textContrast:true});
    }catch(e){}
  }

  function previewLiquidGlassElementMaterial(elementKey, value){
    const material = normalizeLiquidGlassMaterial(value, 0);
    glassLenses().forEach((lens)=>{
      if(liquidGlassLensElementKey(lens) === elementKey) lens.setOptions({material:material});
    });
    const targets = {
      libraryList:[document.getElementById("libList"), document.getElementById("libListGlass")],
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

  // ------------------------------------------------------------------
  // Backdrop: the reactive artwork, or the test wallpaper
  // ------------------------------------------------------------------

  // The reactive artwork, rendered by sfgl in the glass context from the same
  // per-frame state the visualizer draws with. Matches the visualizer's
  // rotation, band response and fade; paused or missing art is opaque black.
  var DEBRIPOD_REACTIVE_BACKDROP = [
    "uniform sampler2D dp_art;",
    "uniform sampler2D dp_previousArt;",
    "uniform bool dp_hasArt;",
    "uniform float dp_artMix;",
    "uniform float dp_angle;",
    "uniform float dp_previousAngle;",
    "uniform vec2 dp_viewport;",
    "uniform float dp_lumaLow;",
    "uniform float dp_lumaHigh;",
    "uniform float dp_fade;",
    "uniform float dp_brightnessCap;",
    "uniform float dp_energy;",
    "uniform float dp_beat;",
    "uniform float dp_bands[9];",
    "uniform float dp_bandCenters[9];",
    "uniform float dp_bandWidths[9];",
    "uniform vec4 dp_frequencyResponse;",
    "uniform vec4 dp_energyResponse;",
    "uniform vec4 dp_beatResponse;",
    "vec2 dpProjectedUV(vec2 uv, float angle) {",
    "  vec2 backgroundUv = vec2(clamp(uv.x, 0.0, 1.0), 1.0 - clamp(uv.y, 0.0, 1.0));",
    "  vec2 screen = (backgroundUv - 0.5) * dp_viewport;",
    "  float c = cos(angle);",
    "  float s = sin(angle);",
    "  vec2 rotated = vec2(c * screen.x + s * screen.y, -s * screen.x + c * screen.y);",
    "  return clamp(rotated / max(1.0, length(dp_viewport)) + 0.5, 0.0, 1.0);",
    "}",
    "float dpBandWeight(float useful, float center, float width) {",
    "  return max(0.0, 1.0 - abs(useful - center) / max(0.0001, width));",
    "}",
    "vec4 sfBackdrop(vec2 uv) {",
    "  if (!dp_hasArt) return vec4(0.0, 0.0, 0.0, 1.0);",
    "  vec2 artUv = dpProjectedUV(uv, dp_angle);",
    "  vec4 color = texture2D(dp_art, vec2(artUv.x, 1.0 - artUv.y));",
    "  if (dp_artMix < 1.0) {",
    "    vec2 previousUv = dpProjectedUV(uv, dp_previousAngle);",
    "    vec4 previous = texture2D(dp_previousArt, vec2(previousUv.x, 1.0 - previousUv.y));",
    "    color = mix(previous, color, dp_artMix);",
    "  }",
    "  float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));",
    "  float useful = clamp((luma - dp_lumaLow) / max(0.08, dp_lumaHigh - dp_lumaLow), 0.0, 1.0);",
    "  float total = 0.0;",
    "  float weighted = 0.0;",
    "  for (int i = 0; i < 9; i++) {",
    "    float w = dpBandWeight(useful, dp_bandCenters[i], dp_bandWidths[i]);",
    "    total += w;",
    "    weighted += w * dp_bands[i];",
    "  }",
    "  float darkEnd = min(0.10, max(0.005, dp_lumaLow));",
    "  float lightStart = max(0.90, min(0.995, dp_lumaHigh));",
    "  float bandEligible = smoothstep(darkEnd * 0.4, darkEnd, luma) * (1.0 - smoothstep(lightStart, 1.0 - (1.0 - lightStart) * 0.4, luma));",
    "  float frequency = bandEligible * weighted / max(0.0001, total);",
    "  float brightness = clamp(1.0 + frequency * dp_frequencyResponse.x + dp_energy * dp_energyResponse.x + dp_beat * dp_beatResponse.x, 0.0, 4.0);",
    "  float opacity = clamp(1.0 + frequency * dp_frequencyResponse.y + dp_energy * dp_energyResponse.y + dp_beat * dp_beatResponse.y, 0.0, 1.0);",
    "  float saturation = clamp(1.0 + frequency * dp_frequencyResponse.z + dp_energy * dp_energyResponse.z + dp_beat * dp_beatResponse.z, 0.0, 3.0);",
    "  float contrast = clamp(1.0 + frequency * dp_frequencyResponse.w + dp_energy * dp_energyResponse.w + dp_beat * dp_beatResponse.w, 0.0, 3.0);",
    "  color.rgb = mix(vec3(luma), color.rgb, saturation);",
    "  color.rgb = min(clamp((color.rgb - 0.5) * contrast + 0.5, 0.0, 1.0) * brightness, vec3(dp_brightnessCap));",
    // The visualizer canvas clears to opaque black; composite over that and
    // keep the source opaque so paused glass shows its material over black.
    "  color.rgb *= opacity * dp_fade;",
    "  return vec4(color.rgb, 1.0);",
    "}"
  ].join("\n");

  function finiteOr(value, fallback){
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function visualizerSourceAdapter(){
    const renderer = window.DebriPod && window.DebriPod.visualizerRenderer;
    return renderer && typeof renderer.sourceForLiquidGL === "function" ? renderer.sourceForLiquidGL() : null;
  }

  var debripodReactiveBackdrop = {
    kind: "program",
    fragment: DEBRIPOD_REACTIVE_BACKDROP,
    ready: ()=> true,
    _state(frame){
      return typeof currentVisualizerFrameState === "function" ? currentVisualizerFrameState(frame && frame.timestamp) : {};
    },
    textures(){
      const adapter = visualizerSourceAdapter();
      const out = {};
      if(adapter && adapter.ready && adapter.image){
        const key = String(adapter.artKey || adapter.image.currentSrc || adapter.image.src || "art");
        out.dp_art = {source:adapter.image, key};
        const fs = typeof currentVisualizerFrameState === "function" ? currentVisualizerFrameState() : {};
        const transition = fs.artTransition || {};
        out.dp_previousArt = transition.active && transition.fromImage && transition.fromKey
          ? {source:transition.fromImage, key:String(transition.fromKey)}
          : {source:adapter.image, key};
      }
      return out;
    },
    uniforms(frame, size){
      const adapter = visualizerSourceAdapter();
      const fs = this._state(frame) || {};
      const transition = fs.artTransition || {};
      const responses = (kind)=> ["brightness", "opacity", "saturation", "contrast"].map((channel)=> finiteOr(fs.responseSettings && fs.responseSettings[kind] && fs.responseSettings[kind][channel], 0));
      const nine = (input, fallback)=> Array.from({length:9}, (_unused, index)=> finiteOr(input && input[index], fallback[index]));
      const hasPrevious = !!(transition.active && transition.fromImage && transition.fromKey);
      return {
        dp_hasArt: !!(adapter && adapter.ready && adapter.image),
        dp_artMix: hasPrevious ? Math.max(0, Math.min(1, finiteOr(transition.progress, 0))) : 1,
        dp_angle: transition.active ? finiteOr(transition.toAngle, Math.PI) : finiteOr(fs.angleRadians, Math.PI),
        dp_previousAngle: finiteOr(transition.fromAngle, finiteOr(fs.angleRadians, Math.PI)),
        dp_viewport: [window.innerWidth || size.width || 1, window.innerHeight || size.height || 1],
        dp_lumaLow: Math.max(0, Math.min(1, finiteOr(fs.lumaLow, 0))),
        dp_lumaHigh: Math.max(0.04, Math.min(1, finiteOr(fs.lumaHigh, 1))),
        dp_fade: Math.max(0, Math.min(1, finiteOr(fs.fade, fs.active ? 1 : 0))),
        dp_brightnessCap: Math.max(0, Math.min(1, finiteOr(fs.brightnessCap, 1))),
        dp_energy: Math.max(0, Math.min(1, finiteOr(fs.energy, 0))),
        dp_beat: Math.max(0, Math.min(1, finiteOr(fs.beat, 0))),
        dp_bands: nine(fs.bands, [0, 0, 0, 0, 0, 0, 0, 0, 0]),
        dp_bandCenters: nine(fs.bandCenters, [0, .125, .25, .375, .5, .625, .75, .875, 1]),
        dp_bandWidths: nine(fs.bandWidths, [.125, .125, .125, .125, .125, .125, .125, .125, .125]),
        dp_frequencyResponse: responses("frequency"),
        dp_energyResponse: responses("energy"),
        dp_beatResponse: responses("beat")
      };
    },
    // Animated while the visualizer shows or an artwork crossfade runs; the
    // prepare rate then follows the quality tier.
    dynamic(frame){
      const fs = this._state(frame) || {};
      const transition = fs.artTransition || {};
      return !!(transition.active || finiteOr(fs.fade, 0) > 0.002);
    },
    key(frame){
      const adapter = visualizerSourceAdapter();
      const fs = this._state(frame) || {};
      return [adapter && adapter.ready ? String(adapter.artKey || "") : "none", finiteOr(fs.fade, 0).toFixed(3), finiteOr(fs.angleRadians, 0).toFixed(4), window.innerWidth, window.innerHeight].join("|");
    }
  };

  var debripodWallpaperBackdrop = null;
  function currentGlassBackdrop(){
    const wallpaper = window.DebriPod && window.DebriPod.wallpaper;
    if(wallpaper && typeof wallpaper.active === "function" && wallpaper.active()){
      const source = wallpaper.source();
      if(source && source.image){
        if(!debripodWallpaperBackdrop || debripodWallpaperBackdrop._image !== source.image){
          debripodWallpaperBackdrop = SFGL.imageBackdrop(source.image, {fit:"cover", key:()=> String(source.artKey || "wallpaper")});
          debripodWallpaperBackdrop._image = source.image;
        }
        return debripodWallpaperBackdrop;
      }
    }
    return debripodReactiveBackdrop;
  }

  function refreshLiquidGlassVisualizerSources(reason, options){
    try{
      const glass = debripodGlassInstance();
      if(!glass) return;
      const provider = currentGlassBackdrop();
      if(glass._backdropProvider !== provider) glass.setBackdrop(provider);
      else glass.requestRender();
    }catch(e){}
  }

  // ------------------------------------------------------------------
  // Frames
  // ------------------------------------------------------------------

  function renderLiquidGlassNow(frameState, options){
    glassRequestRender();
  }

  function renderLiquidGlassVisualizerSourceNow(frameState, options){
    glassRequestRender();
  }

  function captureLiquidGlassSnapshot(reason, includeLibList){
    try{
      refreshLiquidGlassVisualizerSources(reason || "app");
      updateGlassTextUnderColors({reason:reason || "snapshot", force:true});
      if(debripodGlass) debripodGlass.invalidate(true);
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

  function scheduleLiquidGlassRender(){
    markFrameWork({metrics:true, render:true, textContrast:true});
  }

  function recaptureLiquidGlassElement(el){
    glassRequestRender();
  }

  // Older callers mounted canvases by hand; sfgl places its surface itself.
  function mountLiquidCanvas(){}

  // ------------------------------------------------------------------
  // Transient list glass: selected row and row pills
  // ------------------------------------------------------------------

  function destroyLibPillGlassLenses(reason){
    try{
      const surface = debripodGlassSurface();
      if(surface) surface.syncGroup("listPills", [], null);
      pillGlassTargetIds = [];
      document.querySelectorAll(".ipodPill[data-liquid-row-pill]").forEach((el)=>{
        try{
          el.removeAttribute("data-liquid-pill-id");
          el.style.visibility = "";
        }catch(e){}
      });
      markFrameWork({render:true});
    }catch(e){}
  }

  function destroyLibSelectionGlass(reason){
    try{
      cancelLibSelectionMotion();
      const surface = debripodGlassSurface();
      if(surface) surface.syncGroup("selectedRow", [], null);
      const el = document.getElementById("libListSelectedGlass");
      if(el){
        el.style.opacity = "0";
        el.classList.remove("isVisible");
      }
      markFrameWork({render:true});
    }catch(e){}
  }

  function destroyTransientListGlass(reason){
    destroyLibSelectionGlass(reason || "destroy transient list glass");
    destroyLibPillGlassLenses(reason || "destroy transient list glass");
  }

  var pillGlassTargetIds = [];
  function reconcileLibPillGlassTargets(reason){
    try{
      if(!liquidGlassReady || !debripodGlassSurface() || document.documentElement.classList.contains("liquidGlassFallback")) return;
      if(nowPlayingSurfaceVisible()){
        destroyLibPillGlassLenses(reason || "now playing visible");
        return;
      }
      const elements = computeEligibleRowPillElements();
      const nextIds = elements.map((el)=> String(el.getAttribute("data-liquid-pill-id") || ""));
      const surface = debripodGlassSurface();
      const same = pillGlassTargetIds.length === nextIds.length && pillGlassTargetIds.every((id, idx)=> id === nextIds[idx]) &&
        elements.every((el)=> surface.lenses.some((lens)=> lens.el === el));
      if(!same){
        surface.syncGroup("listPills", elements, glassLensOptions("listPills"));
        pillGlassTargetIds = nextIds;
        applyElementGlassMaterialClasses();
      }
      refreshLiquidGlassVisualizerSources(reason || "lib pills");
      invalidateLibPillGlass(reason || "lib pills");
    }catch(e){
      try{ console.error("[DebriPod glass] row-pill reconciliation failed", e); }catch(err){}
    }
  }

  function invalidateLibPillGlass(reason){
    try{
      updateLibSelectionGlass(reason || "");
      if(debripodGlass) debripodGlass.invalidate(false);
      markFrameWork({render:true, textContrast:true});
    }catch(e){}
  }

  function hideTransientListGlass(reason){
    destroyTransientListGlass(reason || "hide transient list glass");
  }

  function refreshLibPillGlassLenses(reason){
    reconcileLibPillGlassTargets(reason || "lib pills");
  }

  // ------------------------------------------------------------------
  // Diagnostics
  // ------------------------------------------------------------------

  function debugLiquidGlassRenderers(reason){
    try{
      const enabled = window.DEBRIPOD_UI_DEBUG === true || (localStorage.getItem("debripod_ui_debug") || "") === "1";
      if(!enabled || !debripodGlass || !console || !console.log) return;
      console.log("[DebriPod glass]", reason || "state", debripodGlass.statsSnapshot(), glassLenses().map((lens)=>({id:lens.el.id || "", className:lens.el.className, group:lens.group || "", rect:lens.rect})));
    }catch(e){}
  }

  function liquidGlassDiagnostics(){
    try{
      if(!debripodGlass) return [];
      const stats = debripodGlass.statsSnapshot();
      return [{
        key:"main",
        visible:glassLenses().some((lens)=> lens.rect),
        visibleLensCount:glassLenses().filter((lens)=> lens.rect).length,
        lensCount:stats.lenses,
        lens_count:stats.lenses,
        averageRenderSubmissionMs:stats.cpuMs,
        renderCount:stats.renders,
        sourceRefreshCount:stats.prepares,
        frostSamples:debripodGlass.frostEnabled() ? Number(DebriPod.uiSettings.settings.glassFrostSamples) || 0 : 0,
        renderScale:stats.renderScale,
        tier:stats.tier
      }];
    }catch(e){
      return [];
    }
  }

  // ------------------------------------------------------------------
  // Start-up
  // ------------------------------------------------------------------

  function initLiquidGlass(){
    try{
      if(liquidGlassReady || !window.SFGL || typeof SFGL.createGlass !== "function") return;
      const settings = ()=> (window.DebriPod && DebriPod.uiSettings && DebriPod.uiSettings.settings) || {};
      debripodGlass = SFGL.createGlass({
        scheduler: frameScheduler(),
        lighting: window.DebriPod && window.DebriPod.glassLighting,
        renderScale: ()=> settings().glassRenderScale,
        frost: ()=> settings().glassFrostSamples,
        quality: ()=> settings().glassQuality || "auto",
        debug: window.DEBRIPOD_UI_DEBUG === true
      });
      const stage = document.querySelector(".ipodStage");
      debripodGlassMainSurface = debripodGlass.surface({host:stage || undefined, z:65, className:"liquidGlassCanvasMain", attributes:{"data-liquid-renderer":"main"}});
      refreshLiquidGlassVisualizerSources("init");
      const surface = debripodGlassMainSurface;
      surface.syncGroup("libraryList", [document.getElementById("libListGlass")].filter(Boolean), glassLensOptions("libraryList"));
      surface.syncGroup("pathPill", Array.from(document.querySelectorAll(".pathPillGlass.liquidGlass")), glassLensOptions("pathPill"));
      surface.syncGroup("infoPill", Array.from(document.querySelectorAll(".infoPillGlass.liquidGlass")), glassLensOptions("infoPill"));
      surface.syncGroup("wheel", Array.from(document.querySelectorAll(".wheelGlassRing.liquidGlass, .wheelCenterGlass.liquidGlass")), glassLensOptions("wheel"));
      applyLiquidGlassStyleOptions();
      try{
        const root = window.DebriPod = window.DebriPod || {};
        root.glass = {instance:debripodGlass, surface:debripodGlassMainSurface, stats:()=> debripodGlass.statsSnapshot()};
      }catch(err){}
      try{
        const scheduler = frameScheduler();
        if(scheduler && scheduler.register){
          // DebriPod-only work; sfgl registers its own render task.
          scheduler.register("liquid-glass", (frameState)=>{
            const flags = frameState && frameState.flags ? frameState.flags : {};
            if(flags.refreshSources) refreshLiquidGlassVisualizerSources("scheduler");
            if(flags.textContrast) updateGlassTextUnderColors({reason:"scheduler", force:true});
            else if(flags.render || flags.metrics) updateGlassTextUnderColors({reason:"scheduler", activeAnimating:!!flags.keepAlive});
          }, {phase:"write"});
        }
      }catch(err){}
      liquidGlassReady = true;
      markFrameWork({refreshSources:true, metrics:true, render:true, textContrast:true});
    }catch(e){
      liquidGlassReady = true;
      try{ console.error("[DebriPod glass] initialization failed", e); }catch(err){}
      try{ document.documentElement.classList.add("liquidGlassFallback"); }catch(err){}
    }
  }

  // ------------------------------------------------------------------
  // Wheel tilt
  // ------------------------------------------------------------------

  function cacheWheelGlassTiltRect(){
    try{
      glassLensesWithClass("wheelGlassRing").concat(glassLensesWithClass("wheelCenterGlass")).forEach((lens)=> lens.invalidate(true));
      wheelGlassTiltRect = wheelGlassLayoutRect();
      return wheelGlassTiltRect;
    }catch(e){
      wheelGlassTiltRect = null;
      return null;
    }
  }

  function renderWheelLiquidGlass(frameState){
    glassRequestRender();
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

  function libSelectionDirectScrolling(){
    const scroll = window.DebriPod && window.DebriPod.listScroll;
    return !!(scroll && scroll.isDirectScrolling());
  }

  function suspendLibSelectionVisual(){
    if(listSelectionMotion.suppressed) return;
    listSelectionMotion.suppressed = true;
    cancelLibSelectionMotion();
    listSelectionMotion.initialized = false;
    listSelectionMotion.motionStepTs = 0;
    const list = document.getElementById("libList");
    if(list) list.classList.add("dpSelectionSuppressed");
    const el = document.getElementById("libListSelectedGlass");
    if(el){
      el.style.visibility = "hidden";
      el.style.opacity = "0";
      el.classList.remove("isVisible");
    }
    if(typeof setSelectedRowContentOffset === "function") setSelectedRowContentOffset(null, null);
    const refraction = window.DebriPod && window.DebriPod.rowRefraction;
    if(refraction) refraction.clear();
    applyLibSelectionForeground();
    markFrameWork({metrics:true, render:true});
  }

  function noteLibSelectionInput(now){
    const motion = listSelectionMotion;
    motion.rapidCount = motion.lastInputAt && now - motion.lastInputAt < 110 ? motion.rapidCount + 1 : 1;
    motion.lastInputAt = now;
    if(motion.rapidCount >= 3) motion.rapidInput = true;
    if(motion.settleTimer) clearTimeout(motion.settleTimer);
    motion.settleTimer = setTimeout(()=>{
      motion.settleTimer = 0;
      motion.rebaseOnReveal = motion.rapidInput;
      motion.rapidInput = false;
      motion.rapidCount = 0;
      updateLibSelectionGlass("input settled");
    }, 160);
  }

  // The foreground variables only style the selected row inside #libList.
  // Writing them there (not on :root) keeps each frame's style invalidation
  // to the list instead of the whole document, and unchanged values are
  // not written again.
  var libSelectionForegroundWritten = {};
  function applyLibSelectionForeground(){
      const fg = Math.max(0, Math.min(1, listSelectionMotion.foregroundProgress || 0));
      const target = document.getElementById("libList") || document.documentElement;
      const values = {
        "--dp-selected-foreground-progress": fg.toFixed(3),
        "--dp-selected-foreground-base-pct": ((1 - fg) * 100).toFixed(2) + "%",
        "--dp-selected-foreground-target-pct": (fg * 100).toFixed(2) + "%",
        "--dp-selected-foreground-scale": (1 + fg * 0.035).toFixed(4),
        "--dp-selected-pill-scale": (1 + fg * 0.025).toFixed(4)
      };
      if(libSelectionForegroundWritten.target !== target) libSelectionForegroundWritten = {target};
      Object.keys(values).forEach((key)=>{
        if(libSelectionForegroundWritten[key] === values[key]) return;
        libSelectionForegroundWritten[key] = values[key];
        target.style.setProperty(key, values[key]);
      });
  }

  function applyLibSelectionMotion(){
    try{
      if(listSelectionMotion.suppressed) return;
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
      applyLibSelectionForeground();
      if(typeof setSelectedRowContentOffset === "function") setSelectedRowContentOffset(renderY + (renderHeight - listSelectionMotion.currentHeight) / 2, listSelectionMotion.targetY);
      // The selected lens measures its element live; only a draw is needed.
      markFrameWork({render:true});
    }catch(e){}
  }

  function stepLibSelectionMotion(frameState){
    listSelectionMotion.raf = 0;
    try{
      if(listSelectionMotion.suppressed) return;
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
      const geometry = window.LiquidGlassMotion.advance(
        {x:listSelectionMotion.currentX,y:listSelectionMotion.currentY,width:listSelectionMotion.currentWidth,height:listSelectionMotion.currentHeight,radius:listSelectionMotion.currentRadius,stretch:listSelectionMotion.stretch || 0},
        {x:listSelectionMotion.targetX,y:listSelectionMotion.targetY,width:listSelectionMotion.targetWidth,height:listSelectionMotion.targetHeight,radius:listSelectionMotion.targetRadius,stretch:listSelectionMotion.targetStretch || 0},elapsed,40);
      for(const [key,field] of Object.entries({x:"X",y:"Y",width:"Width",height:"Height",radius:"Radius"}))listSelectionMotion["current"+field]=geometry[key];
      listSelectionMotion.currentOpacity += (listSelectionMotion.targetOpacity - listSelectionMotion.currentOpacity) * 0.42;
      listSelectionMotion.stretch = geometry.stretch;
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
      if(listSelectionMotion.suppressed) return;
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
      radius = Math.max(0, Math.min(radius, width / 2, height / 2));
      if(listSelectionMotion.initialized && listSelectionMotion.targetX === x && listSelectionMotion.targetY === y &&
         listSelectionMotion.targetWidth === width && listSelectionMotion.targetHeight === height &&
         listSelectionMotion.targetRadius === radius && listSelectionMotion.targetOpacity === opacity) return;
      listSelectionMotion.targetX = x;
      listSelectionMotion.targetY = y;
      listSelectionMotion.targetWidth = width;
      listSelectionMotion.targetHeight = height;
      listSelectionMotion.targetRadius = radius;
      listSelectionMotion.targetOpacity = opacity;
      listSelectionMotion.targetForegroundProgress = opacity > 0.5 ? 1 : 0;
      if(!listSelectionMotion.initialized || (listSelectionMotion.rebaseOnReveal && opacity > 0)){
        const reveal = listSelectionMotion.rebaseOnReveal && opacity > 0;
        listSelectionMotion.rebaseOnReveal = false;
        listSelectionMotion.currentX = x;
        listSelectionMotion.currentY = y;
        listSelectionMotion.currentWidth = width;
        listSelectionMotion.currentHeight = height;
        listSelectionMotion.currentRadius = radius;
        listSelectionMotion.currentOpacity = reveal ? 0 : opacity;
        listSelectionMotion.foregroundProgress = listSelectionMotion.targetForegroundProgress;
        listSelectionMotion.initialized = true;
        applyLibSelectionMotion();
        if(reveal) scheduleLibSelectionMotion();
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
      const directScrolling = libSelectionDirectScrolling();
      const selectedKey = String(state.itemsVersion || 0) + ":" + String(state.sel);
      if(listSelectionMotion.selectedKey !== selectedKey){
        listSelectionMotion.selectedKey = selectedKey;
        if(!directScrolling && reason !== "direct scroll settled") noteLibSelectionInput(performance.now());
      }
      if(directScrolling || listSelectionMotion.rapidInput){
        suspendLibSelectionVisual();
        return;
      }
      const settings = glassElementSettings("selectedRow");
      applyGlassMaterialClass(el, settings.material);
      const row = list.querySelector(".ipodItem.sel");
      const inner = selectedListInnerRect();
      if(!row || !inner){
        suspendLibSelectionVisual();
        return;
      }
      const rowRect = row.getBoundingClientRect();
      const left = Math.max(rowRect.left, inner.left);
      const right = Math.min(rowRect.right, inner.right);
      const visibleTop = Math.max(rowRect.top, inner.top);
      const visibleBottom = Math.min(rowRect.bottom, inner.bottom);
      if(right <= left || visibleBottom <= visibleTop){
        suspendLibSelectionVisual();
        return;
      }
      if(listSelectionMotion.suppressed){
        listSelectionMotion.suppressed = false;
        listSelectionMotion.rebaseOnReveal = true;
        list.classList.remove("dpSelectionSuppressed");
        el.style.visibility = "";
      }
      const host = document.getElementById("ipodScreen");
      const hostRect = host ? host.getBoundingClientRect() : {left:0, top:0};
      const targetHeight = Math.max(1, rowRect.height || (visibleBottom - visibleTop));
      const radius = Math.min(right - left, targetHeight) / 2;
      setLibSelectionTarget(left - hostRect.left, rowRect.top - hostRect.top, right - left, targetHeight, radius, 1);
      const surface = debripodGlassSurface();
      if(surface) surface.syncGroup("selectedRow", [el], glassLensOptions("selectedRow"));
      if(reason && surface) markFrameWork({render:true});
    }catch(e){}
  }

  function setWheelLensTilt(rotX, rotY){
    wheelGlassTiltX = Number.isFinite(rotX) ? rotX : 0;
    wheelGlassTiltY = Number.isFinite(rotY) ? rotY : 0;
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

  function updateWheelGlassTilt(clientX, clientY){
    try{
      if(wheelGlassResetFrame){
        cancelAnimationFrame(wheelGlassResetFrame);
        wheelGlassResetFrame = 0;
      }
      const rect = wheelGlassTiltRect || cacheWheelGlassTiltRect() || (wheel ? wheel.getBoundingClientRect() : null);
      if(!rect || !rect.width || !rect.height) return;
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
    // (Previously assigned to an undefined `root`, so the performance overlay
    // never received glass diagnostics.)
    (window.DebriPod = window.DebriPod || {}).liquidDiagnostics = {
      renderers: liquidGlassDiagnostics,
      visibleVisualizerRenderers: function(){ return liquidGlassDiagnostics().filter((row)=> row.visible).map((row)=> row.key); },
      textColorScans: function(){
        return {
          runCount: glassTextUnderColorState.runCount || 0,
          lastRun: glassTextUnderColorState.lastRun || 0,
          lastSignature: glassTextUnderColorState.lastSignature || ""
        };
      }
    };
  }catch(e){}
